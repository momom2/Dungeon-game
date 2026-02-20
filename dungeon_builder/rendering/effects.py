"""Visual effects for the dungeon core, hover highlight, craft markers, dig indicators, and ore glows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from panda3d.core import (
    Geom,
    GeomLines,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
    TransparencyAttrib,
)
from direct.showbase.ShowBase import ShowBase

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    RENDER_MODE_PROSPECTING,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid

logger = logging.getLogger("dungeon_builder.rendering.effects")


def _make_core_marker() -> GeomNode:
    """Create a glowing cube for the dungeon core."""
    vdata = GeomVertexData("core", GeomVertexFormat.get_v3n3c4(), Geom.UH_static)
    vertex = GeomVertexWriter(vdata, "vertex")
    normal = GeomVertexWriter(vdata, "normal")
    color = GeomVertexWriter(vdata, "color")
    prim = GeomTriangles(Geom.UH_static)

    s = 0.35
    c = 0.5  # center offset
    r, g, b = 0.9, 0.1, 0.2

    faces = [
        ((0, 0, 1), [(c-s, c-s, c+s), (c+s, c-s, c+s), (c+s, c+s, c+s), (c-s, c+s, c+s)]),
        ((0, 0, -1), [(c-s, c+s, c-s), (c+s, c+s, c-s), (c+s, c-s, c-s), (c-s, c-s, c-s)]),
        ((1, 0, 0), [(c+s, c-s, c-s), (c+s, c+s, c-s), (c+s, c+s, c+s), (c+s, c-s, c+s)]),
        ((-1, 0, 0), [(c-s, c+s, c-s), (c-s, c-s, c-s), (c-s, c-s, c+s), (c-s, c+s, c+s)]),
        ((0, 1, 0), [(c+s, c+s, c-s), (c-s, c+s, c-s), (c-s, c+s, c+s), (c+s, c+s, c+s)]),
        ((0, -1, 0), [(c-s, c-s, c-s), (c+s, c-s, c-s), (c+s, c-s, c+s), (c-s, c-s, c+s)]),
    ]

    vi = 0
    for nrm, corners in faces:
        for cx, cy, cz in corners:
            vertex.add_data3f(cx, cy, cz)
            normal.add_data3f(*nrm)
            color.add_data4f(r, g, b, 1.0)
        prim.add_vertices(vi, vi + 1, vi + 2)
        prim.add_vertices(vi, vi + 2, vi + 3)
        vi += 4

    geom = Geom(vdata)
    geom.add_primitive(prim)
    node = GeomNode("core_marker")
    node.add_geom(geom)
    return node


def _make_highlight_cube() -> GeomNode:
    """Create a wireframe cube for hover highlighting.

    The cube spans from (-m, -m, -m) to (1+m, 1+m, 1+m), slightly larger
    than a unit voxel so it renders outside the block faces.
    """
    m = 0.02  # margin outside the voxel
    vdata = GeomVertexData("highlight", GeomVertexFormat.get_v3c4(), Geom.UH_static)
    vertex = GeomVertexWriter(vdata, "vertex")
    color = GeomVertexWriter(vdata, "color")
    prim = GeomLines(Geom.UH_static)

    # 8 corners of the cube
    corners = [
        (-m, -m, -m),          # 0: bottom-SW
        (1 + m, -m, -m),       # 1: bottom-SE
        (1 + m, 1 + m, -m),    # 2: bottom-NE
        (-m, 1 + m, -m),       # 3: bottom-NW
        (-m, -m, 1 + m),       # 4: top-SW
        (1 + m, -m, 1 + m),    # 5: top-SE
        (1 + m, 1 + m, 1 + m), # 6: top-NE
        (-m, 1 + m, 1 + m),    # 7: top-NW
    ]

    r, g, b, a = 1.0, 1.0, 1.0, 0.85

    for cx, cy, cz in corners:
        vertex.add_data3f(cx, cy, cz)
        color.add_data4f(r, g, b, a)

    # 12 edges of a cube
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),  # bottom face
        (4, 5), (5, 6), (6, 7), (7, 4),  # top face
        (0, 4), (1, 5), (2, 6), (3, 7),  # vertical edges
    ]
    for v0, v1 in edges:
        prim.add_vertices(v0, v1)

    geom = Geom(vdata)
    geom.add_primitive(prim)
    node = GeomNode("highlight_cube")
    node.add_geom(geom)
    return node


def _make_craft_marker() -> GeomNode:
    """Create a semi-transparent green cube for craft-valid air positions.

    Uses the same geometry as the core marker but green with alpha=0.35.
    """
    return _make_glow_marker(0.2, 0.9, 0.3, 0.35, name="craft_marker")


def _make_pending_dig_marker() -> GeomNode:
    """Create a semi-transparent golden cube for pending dig positions."""
    return _make_glow_marker(0.8, 0.65, 0.0, 0.25, name="pending_dig_marker")


def _make_glow_marker(
    r: float, g: float, b: float, a: float, *, name: str = "glow_marker",
) -> GeomNode:
    """Create a semi-transparent colored cube marker.

    Slightly smaller than a full voxel (margin 0.05) to avoid z-fighting.
    Used for craft highlights, pending digs, and ore glows.
    """
    vdata = GeomVertexData(name, GeomVertexFormat.get_v3n3c4(), Geom.UH_static)
    vertex = GeomVertexWriter(vdata, "vertex")
    normal = GeomVertexWriter(vdata, "normal")
    color = GeomVertexWriter(vdata, "color")
    prim = GeomTriangles(Geom.UH_static)

    m = 0.05

    faces = [
        ((0, 0, 1), [(m, m, 1 - m), (1 - m, m, 1 - m), (1 - m, 1 - m, 1 - m), (m, 1 - m, 1 - m)]),
        ((0, 0, -1), [(m, 1 - m, m), (1 - m, 1 - m, m), (1 - m, m, m), (m, m, m)]),
        ((1, 0, 0), [(1 - m, m, m), (1 - m, 1 - m, m), (1 - m, 1 - m, 1 - m), (1 - m, m, 1 - m)]),
        ((-1, 0, 0), [(m, 1 - m, m), (m, m, m), (m, m, 1 - m), (m, 1 - m, 1 - m)]),
        ((0, 1, 0), [(1 - m, 1 - m, m), (m, 1 - m, m), (m, 1 - m, 1 - m), (1 - m, 1 - m, 1 - m)]),
        ((0, -1, 0), [(m, m, m), (1 - m, m, m), (1 - m, m, 1 - m), (m, m, 1 - m)]),
    ]

    vi = 0
    for nrm, corners in faces:
        for cx, cy, cz in corners:
            vertex.add_data3f(cx, cy, cz)
            normal.add_data3f(*nrm)
            color.add_data4f(r, g, b, a)
        prim.add_vertices(vi, vi + 1, vi + 2)
        prim.add_vertices(vi, vi + 2, vi + 3)
        vi += 4

    geom = Geom(vdata)
    geom.add_primitive(prim)
    node = GeomNode(name)
    node.add_geom(geom)
    return node


class EffectsRenderer:
    """Renders visual indicators for the core, hover highlight, craft markers,
    pending dig markers, and ore glow markers."""

    def __init__(
        self,
        app: ShowBase,
        event_bus: EventBus,
        voxel_grid: VoxelGrid | None = None,
    ) -> None:
        self.app = app
        self.event_bus = event_bus
        self._voxel_grid = voxel_grid
        self._core_np: NodePath | None = None
        self._highlight_np: NodePath | None = None
        self._craft_marker_nps: list[NodePath] = []  # Pool of reusable markers
        self._pending_dig_nps: list[NodePath] = []
        self._pending_dig_positions: set[tuple[int, int, int]] = set()
        self._ore_glow_nps: list[NodePath] = []
        self._ore_glow_positions: set[tuple[int, int, int]] = set()
        self._current_z: int = 1
        self._render_mode: str = "matter"

        # Drag-select preview box (hidden by default)
        self._drag_box_np: NodePath | None = None

        # Create the reusable highlight cube (hidden initially)
        self._init_highlight()
        self._init_drag_box()

        event_bus.subscribe("voxel_hover", self._on_voxel_hover)
        event_bus.subscribe("voxel_hover_clear", self._on_voxel_hover_clear)
        event_bus.subscribe("craft_highlights_updated", self._on_craft_highlights_updated)
        event_bus.subscribe("craft_highlights_cleared", self._on_craft_highlights_cleared)
        event_bus.subscribe("dig_pending", self._on_dig_pending)
        event_bus.subscribe("dig_cancelled", self._on_dig_cancelled)
        event_bus.subscribe("dig_queued", self._on_dig_promoted)
        event_bus.subscribe("claimed_territory_changed", self._on_territory_changed)
        event_bus.subscribe("z_level_changed", self._on_z_changed)
        event_bus.subscribe("render_mode_changed", self._on_render_mode_changed)
        event_bus.subscribe("drag_select_preview", self._on_drag_preview)
        event_bus.subscribe("drag_select_cleared", self._on_drag_cleared)
        event_bus.subscribe("dig_batch_pending", self._on_dig_batch_pending)
        event_bus.subscribe("dig_batch_cancelled", self._on_dig_batch_cancelled)

    def _init_highlight(self) -> None:
        """Create the wireframe highlight cube, hidden by default."""
        node = _make_highlight_cube()
        np = self.app.render.attach_new_node(node)
        np.set_transparency(TransparencyAttrib.M_alpha)
        np.set_render_mode_thickness(2.0)
        np.set_light_off()   # Unaffected by scene lighting
        np.set_bin("fixed", 50)  # Render on top of voxels
        np.set_depth_test(False)
        np.set_depth_write(False)
        np.hide()
        self._highlight_np = np

    def _init_drag_box(self) -> None:
        """Create the wireframe drag selection box, hidden by default."""
        node = _make_highlight_cube()
        np = self.app.render.attach_new_node(node)
        np.set_transparency(TransparencyAttrib.M_alpha)
        np.set_render_mode_thickness(2.0)
        np.set_light_off()
        np.set_bin("fixed", 55)
        np.set_depth_test(False)
        np.set_depth_write(False)
        np.set_color_scale(1.0, 0.85, 0.3, 0.9)  # Golden-white
        np.hide()
        self._drag_box_np = np

    def _on_drag_preview(
        self,
        x_min: int, x_max: int,
        y_min: int, y_max: int,
        z_min: int, z_max: int,
        **kwargs,
    ) -> None:
        """Position and show the drag selection box."""
        if self._drag_box_np is None:
            return
        width = x_max - x_min + 1
        depth = y_max - y_min + 1
        height = z_max - z_min + 1
        self._drag_box_np.set_pos(x_min, y_min, -z_max)
        self._drag_box_np.set_scale(width, depth, height)
        self._drag_box_np.show()

    def _on_drag_cleared(self, **kwargs) -> None:
        """Hide the drag selection box."""
        if self._drag_box_np is not None:
            self._drag_box_np.hide()

    def _on_voxel_hover(self, x: int, y: int, z: int) -> None:
        """Move highlight cube to the hovered voxel."""
        if self._highlight_np is not None:
            self._highlight_np.set_pos(x, y, -z)
            self._highlight_np.show()

    def _on_voxel_hover_clear(self, **kwargs) -> None:
        """Hide highlight cube when no voxel is hovered."""
        if self._highlight_np is not None:
            self._highlight_np.hide()

    def place_core_marker(self, x: int, y: int, z: int) -> None:
        """Place a visual marker at the dungeon core position."""
        node = _make_core_marker()
        np = self.app.render.attach_new_node(node)
        np.set_pos(x, y, -z)
        self._core_np = np

    # ── Craft highlight markers ──────────────────────────────────────

    def _on_craft_highlights_updated(self, positions: set, **kwargs) -> None:
        """Show green markers at all valid craft positions."""
        # Hide all existing markers first
        for np in self._craft_marker_nps:
            np.hide()

        # Show/create markers for each position
        for i, (x, y, z) in enumerate(positions):
            if i >= len(self._craft_marker_nps):
                # Create a new marker node and add to pool
                node = _make_craft_marker()
                np = self.app.render.attach_new_node(node)
                np.set_transparency(TransparencyAttrib.M_alpha)
                np.set_light_off()
                np.set_bin("fixed", 45)
                np.set_depth_write(False)
                np.set_depth_test(False)
                self._craft_marker_nps.append(np)
            marker = self._craft_marker_nps[i]
            marker.set_pos(x, y, -z)
            marker.show()

    def _on_craft_highlights_cleared(self, **kwargs) -> None:
        """Hide all craft markers."""
        for np in self._craft_marker_nps:
            np.hide()

    # ── Pending dig markers ──────────────────────────────────────────

    def _on_dig_pending(self, x: int, y: int, z: int, **kwargs) -> None:
        """Show a golden marker at a pending dig position."""
        self._pending_dig_positions.add((x, y, z))
        self._update_pending_markers()

    def _on_dig_cancelled(self, x: int, y: int, z: int, **kwargs) -> None:
        """Remove marker when a pending dig is cancelled."""
        self._pending_dig_positions.discard((x, y, z))
        self._update_pending_markers()

    def _on_dig_promoted(self, x: int, y: int, z: int, **kwargs) -> None:
        """Remove marker when a pending dig is promoted to active queue."""
        self._pending_dig_positions.discard((x, y, z))
        self._update_pending_markers()

    def _on_dig_batch_pending(
        self, positions: list[tuple[int, int, int]], **kwargs,
    ) -> None:
        """Add all pending positions at once, update markers once."""
        for pos in positions:
            self._pending_dig_positions.add(pos)
        self._update_pending_markers()

    def _on_dig_batch_cancelled(
        self, positions: list[tuple[int, int, int]], **kwargs,
    ) -> None:
        """Remove all cancelled positions at once, update markers once."""
        for pos in positions:
            self._pending_dig_positions.discard(pos)
        self._update_pending_markers()

    def _update_pending_markers(self) -> None:
        """Update the pool of pending dig markers to match current positions."""
        for np in self._pending_dig_nps:
            np.hide()

        for i, (x, y, z) in enumerate(self._pending_dig_positions):
            if i >= len(self._pending_dig_nps):
                node = _make_pending_dig_marker()
                np = self.app.render.attach_new_node(node)
                np.set_transparency(TransparencyAttrib.M_alpha)
                np.set_light_off()
                np.set_bin("fixed", 44)
                np.set_depth_write(False)
                np.set_depth_test(False)
                self._pending_dig_nps.append(np)
            marker = self._pending_dig_nps[i]
            marker.set_pos(x, y, -z)
            marker.show()

    # ── Ore glow markers (Prospecting mode) ──────────────────────────

    def _on_territory_changed(self, **kwargs) -> None:
        """Re-scan ore glows when claimed territory updates."""
        if self._render_mode == RENDER_MODE_PROSPECTING:
            self._scan_ore_glows()

    def _on_z_changed(self, z: int, **kwargs) -> None:
        """Re-scan ore glows when z-level changes."""
        self._current_z = z
        if self._render_mode == RENDER_MODE_PROSPECTING:
            self._scan_ore_glows()

    def _on_render_mode_changed(self, mode: str, **kwargs) -> None:
        """Show/hide ore glows based on render mode."""
        self._render_mode = mode
        if mode == RENDER_MODE_PROSPECTING:
            self._scan_ore_glows()
        else:
            self._hide_ore_glows()

    def _hide_ore_glows(self) -> None:
        """Hide all ore glow markers."""
        for np in self._ore_glow_nps:
            np.hide()
        self._ore_glow_positions = set()

    def _scan_ore_glows(self) -> None:
        """Find visible ore blocks with no air-adjacent face (fully encased).

        Uses vectorized NumPy for performance.  Only scans z ± 2 levels
        around the current focus layer.
        """
        if self._voxel_grid is None:
            return
        grid = self._voxel_grid
        w, d, h = grid.width, grid.depth, grid.height
        z_min = max(0, self._current_z - 2)
        z_max = min(h, self._current_z + 3)

        voxels = grid.grid
        visible = grid.visible

        # Build ore mask for the slab
        ore_mask = np.zeros((w, d, z_max - z_min), dtype=np.bool_)
        for vtype in _cfg.XRAY_VISIBLE_TYPES:
            ore_mask |= (voxels[:, :, z_min:z_max] == vtype)

        vis_slab = visible[:, :, z_min:z_max]
        ore_visible = ore_mask & vis_slab

        if not np.any(ore_visible):
            self._update_ore_markers(set())
            return

        # Check for air/water neighbors in all 6 directions
        transparent = np.zeros_like(voxels, dtype=np.bool_)
        transparent |= (voxels == VOXEL_AIR)
        transparent |= (voxels == VOXEL_WATER)

        has_air = np.zeros((w, d, z_max - z_min), dtype=np.bool_)
        # +x / -x
        if w > 1:
            has_air[:-1, :, :] |= transparent[1:, :, z_min:z_max]
            has_air[1:, :, :] |= transparent[:-1, :, z_min:z_max]
        # +y / -y
        if d > 1:
            has_air[:, :-1, :] |= transparent[:, 1:, z_min:z_max]
            has_air[:, 1:, :] |= transparent[:, :-1, z_min:z_max]
        # +z / -z (using full grid boundaries)
        if z_min > 0:
            has_air[:, :, 0] |= transparent[:, :, z_min - 1]
        if z_max < h:
            has_air[:, :, -1] |= transparent[:, :, z_max]
        slab_h = z_max - z_min
        if slab_h > 1:
            has_air[:, :, :-1] |= transparent[:, :, z_min + 1:z_max]
            has_air[:, :, 1:] |= transparent[:, :, z_min:z_max - 1]

        encased = ore_visible & ~has_air
        xs, ys, zs_local = np.where(encased)
        zs = zs_local + z_min
        new_positions = set(zip(xs.tolist(), ys.tolist(), zs.tolist()))
        self._update_ore_markers(new_positions)

    def _update_ore_markers(self, positions: set[tuple[int, int, int]]) -> None:
        """Update the pool of ore glow markers to match current positions."""
        if positions == self._ore_glow_positions:
            return  # No change

        for np_node in self._ore_glow_nps:
            np_node.hide()

        self._ore_glow_positions = positions

        for i, (x, y, z) in enumerate(positions):
            if i >= len(self._ore_glow_nps):
                # Create white-base marker; tint via set_color_scale
                node = _make_glow_marker(1.0, 1.0, 1.0, 1.0, name="ore_glow")
                np_node = self.app.render.attach_new_node(node)
                np_node.set_transparency(TransparencyAttrib.M_alpha)
                np_node.set_light_off()
                np_node.set_bin("fixed", 40)
                np_node.set_depth_write(False)
                np_node.set_depth_test(False)
                self._ore_glow_nps.append(np_node)

            marker = self._ore_glow_nps[i]
            # Per-ore-type color via color_scale
            if self._voxel_grid is not None:
                vtype = int(self._voxel_grid.grid[x, y, z])
                glow_color = _cfg.ORE_GLOW_COLORS.get(vtype, (0.5, 0.5, 0.5, 0.3))
                marker.set_color_scale(*glow_color)
            marker.set_pos(x, y, -z)
            marker.show()
