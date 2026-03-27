"""Chunk-based voxel mesh generation and rendering using Panda3D GeomNode.

Dependencies: config (voxel constants, colors, render modes),
             building.build_system (dig state), world.voxel_grid,
             rendering.layer_slice
Dependents: main (wiring), tests/rendering/test_voxel_renderer.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
)

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    CHUNK_SIZE,
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_COLORS,
    VOXEL_DOOR,
    VOXEL_FLOODGATE,
    VOXEL_IRON_BARS,
    VOXEL_STEAM_VENT,
    VOXEL_NOISE,
    VERTEX_NOISE_AMPLITUDE,
    RENDER_MODE_MATTER,
    RENDER_MODE_HUMIDITY,
    RENDER_MODE_HEAT,
    RENDER_MODE_STRUCTURAL,
    RENDER_MODE_PROSPECTING,
    METALLIC_BLOCKS,
    METAL_COLORS,
    ENCHANTED_OFFSET,
    FACE_TRANSPARENT_VOXELS,
    FLUID_VOXELS,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.building.build_system import BuildSystem
    from dungeon_builder.rendering.layer_slice import LayerSliceManager
    from dungeon_builder.world.voxel_grid import VoxelGrid

logger = logging.getLogger("dungeon_builder.rendering")

# Vertex format: position + normal + color
VOXEL_VERTEX_FORMAT = GeomVertexFormat.get_v3n3c4()

# Six face directions: (dx, dy, dz, face_name)
FACES = [
    (0, 0, -1, "top"),     # Toward surface (z decreasing = up in world)
    (0, 0, 1, "bottom"),   # Toward depth (z increasing = down in world)
    (1, 0, 0, "east"),
    (-1, 0, 0, "west"),
    (0, 1, 0, "north"),
    (0, -1, 0, "south"),
]

# Normal vectors for each face (in world space, where Z is up)
FACE_NORMALS = {
    "top": (0, 0, 1),
    "bottom": (0, 0, -1),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "north": (0, 1, 0),
    "south": (0, -1, 0),
}

# Quad vertices for each face (offsets within a unit cube)
# The cube goes from (0,0,0) to (1,1,1) in local voxel space
# World mapping: voxel at grid (gx, gy, gz) renders at world (gx, gy, -gz)
# So the "top" face (toward surface) is at higher world-Z
FACE_VERTICES = {
    "top": [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
    "bottom": [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)],
    "east": [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
    "west": [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)],
    "north": [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)],
    "south": [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],
}

# Slight color variation per face for pseudo-lighting
FACE_SHADE = {
    "top": 1.0,
    "bottom": 0.5,
    "east": 0.8,
    "west": 0.7,
    "north": 0.9,
    "south": 0.6,
}


def _vertex_noise(
    gx: int, gy: int, gz: int, face_idx: int, vert_idx: int,
) -> float:
    """Deterministic per-vertex color noise in [-1, +1] range.

    Uses an FNV-1a-inspired hash for speed (no imports needed).
    Same inputs always produce the same output (stable across frames).
    """
    h = 2166136261
    for v in (gx, gy, gz, face_idx, vert_idx):
        h ^= v & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return (h / 2147483647.0) - 1.0


def _lerp_color(
    base: tuple[float, float, float, float],
    target: tuple[float, ...],
    t: float,
) -> tuple[float, float, float, float]:
    """Linearly interpolate from *base* toward *target* by factor *t*.

    *target* may be an RGB 3-tuple (alpha preserved from *base*) or an
    RGBA 4-tuple.
    """
    return (
        base[0] * (1 - t) + target[0] * t,
        base[1] * (1 - t) + target[1] * t,
        base[2] * (1 - t) + target[2] * t,
        base[3],
    )


def humidity_to_color(
    h: float,
    face_name: str | None = None,
    base_color: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    """Map humidity [0..1] to a colour.

    When *base_color* is provided the result is a **tint overlay**: the
    matter colour is blended toward blue proportional to humidity so that
    block types remain identifiable even at high moisture.

    When *base_color* is ``None`` the legacy blue→cyan→green gradient is
    returned (kept for backward-compatible callers / tests).
    """
    h = max(0.0, min(1.0, h))

    if base_color is not None:
        # Tint overlay: lerp toward deep blue, max 60 %
        t = h * 0.6
        return (
            base_color[0] * (1 - t) + 0.1 * t,
            base_color[1] * (1 - t) + 0.3 * t,
            base_color[2] * (1 - t) + 0.9 * t,
            base_color[3],
        )

    # Legacy gradient (no base_color)
    if h < 0.5:
        t = h / 0.5
        return (0.0, t, 1.0, 1.0)
    else:
        t = (h - 0.5) / 0.5
        return (0.0, 1.0, 1.0 - t, 1.0)


def stress_to_color(stress: float) -> tuple[float, float, float, float]:
    """Map stress ratio [0..1+] to green-yellow-orange-red gradient."""
    stress = max(0.0, stress)
    if stress <= 0.5:
        t = stress / 0.5
        # Green -> Yellow
        return (0.9 * t, 0.7 + 0.2 * t, 0.0, 1.0)
    elif stress <= 0.8:
        t = (stress - 0.5) / 0.3
        # Yellow -> Orange
        return (0.9 + 0.1 * t, 0.9 - 0.4 * t, 0.0, 1.0)
    elif stress <= 1.0:
        t = (stress - 0.8) / 0.2
        # Orange -> Red
        return (1.0, 0.5 - 0.5 * t, 0.0, 1.0)
    else:
        return (1.0, 0.0, 0.0, 1.0)


def temperature_to_color(temp: float) -> tuple[float, float, float, float]:
    """Map temperature to blue-white-red gradient.

    0-20: deep blue
    20-100: blue to white
    100-500: white to red
    500+: bright red
    """
    if temp <= 20.0:
        return (0.0, 0.0, 0.5, 1.0)
    elif temp <= 100.0:
        t = (temp - 20.0) / 80.0
        # Blue to white
        return (t, t, 0.5 + 0.5 * t, 1.0)
    elif temp <= 500.0:
        t = (temp - 100.0) / 400.0
        # White to red
        return (1.0, 1.0 - t, 1.0 - t, 1.0)
    else:
        return (1.0, 0.0, 0.0, 1.0)


class ChunkMeshBuilder:
    """Builds a GeomNode for one 16x16x1 chunk."""

    def build(
        self,
        voxel_grid: VoxelGrid,
        chunk_x: int,
        chunk_y: int,
        z_level: int,
        render_mode: str = RENDER_MODE_MATTER,
        build_system: BuildSystem | None = None,
        craft_highlights: set | None = None,
        ingredient_highlights: set | None = None,
    ) -> GeomNode | None:
        """Build mesh for chunk at (chunk_x, chunk_y, z_level).

        Returns GeomNode or None if chunk has no visible faces.
        """
        import numpy as np

        # ── Fast pre-check: skip chunk if no voxels are visible ──
        # This avoids the expensive per-voxel Python loop for fully-
        # interior chunks (98% of all chunks in a typical world).
        x_off = chunk_x * CHUNK_SIZE
        y_off = chunk_y * CHUNK_SIZE
        x_end = min(x_off + CHUNK_SIZE, voxel_grid.width)
        y_end = min(y_off + CHUNK_SIZE, voxel_grid.depth)
        chunk_visible = voxel_grid.visible[x_off:x_end, y_off:y_end, z_level]
        if not np.any(chunk_visible):
            # No visible voxels → also no pending-dig fog highlights
            if build_system is None or not build_system._dig_positions:
                return None
            # Check if any dig positions fall in this chunk
            has_dig_in_chunk = False
            for dx in range(x_end - x_off):
                for dy in range(y_end - y_off):
                    if (x_off + dx, y_off + dy, z_level) in build_system._dig_positions:
                        has_dig_in_chunk = True
                        break
                if has_dig_in_chunk:
                    break
            if not has_dig_in_chunk:
                return None

        # ── Fast pre-check #2: skip chunk if no transparent neighbors ──
        # A chunk of entirely solid blocks surrounded by solid blocks on
        # all sides has zero exposed faces.  Check if any air/water exists
        # in or adjacent to this chunk's z-level slice.
        # This catches deep underground chunks even in DEV_MODE where
        # visible[:] = True.
        grid_arr = voxel_grid.grid
        chunk_slice = grid_arr[x_off:x_end, y_off:y_end, z_level]

        # Quick check: any transparent voxel within the chunk itself?
        # VOXEL_AIR=0, VOXEL_WATER=51 — check both
        has_transparent = (
            np.any(chunk_slice == VOXEL_AIR)
            or np.any(chunk_slice == VOXEL_WATER)
            or np.any(chunk_slice == _cfg.VOXEL_LAVA)
        )

        if not has_transparent:
            # Check z-neighbors (above/below) for transparency
            if z_level > 0:
                above = grid_arr[x_off:x_end, y_off:y_end, z_level - 1]
                has_transparent = np.any(above == VOXEL_AIR) or np.any(above == VOXEL_WATER) or np.any(above == _cfg.VOXEL_LAVA)
            if not has_transparent and z_level < voxel_grid.height - 1:
                below = grid_arr[x_off:x_end, y_off:y_end, z_level + 1]
                has_transparent = np.any(below == VOXEL_AIR) or np.any(below == VOXEL_WATER) or np.any(below == _cfg.VOXEL_LAVA)
            # Check x-boundary neighbors (one-voxel-thick strips)
            if not has_transparent and x_off > 0:
                left = grid_arr[x_off - 1, y_off:y_end, z_level]
                has_transparent = np.any(left == VOXEL_AIR) or np.any(left == VOXEL_WATER) or np.any(left == _cfg.VOXEL_LAVA)
            if not has_transparent and x_end < voxel_grid.width:
                right = grid_arr[x_end, y_off:y_end, z_level]
                has_transparent = np.any(right == VOXEL_AIR) or np.any(right == VOXEL_WATER) or np.any(right == _cfg.VOXEL_LAVA)
            # Check y-boundary neighbors
            if not has_transparent and y_off > 0:
                front = grid_arr[x_off:x_end, y_off - 1, z_level]
                has_transparent = np.any(front == VOXEL_AIR) or np.any(front == VOXEL_WATER) or np.any(front == _cfg.VOXEL_LAVA)
            if not has_transparent and y_end < voxel_grid.depth:
                back = grid_arr[x_off:x_end, y_end, z_level]
                has_transparent = np.any(back == VOXEL_AIR) or np.any(back == VOXEL_WATER) or np.any(back == _cfg.VOXEL_LAVA)
            if not has_transparent:
                return None

        vdata = GeomVertexData(
            f"chunk_{chunk_x}_{chunk_y}_{z_level}",
            VOXEL_VERTEX_FORMAT,
            Geom.UH_static,
        )
        vertex = GeomVertexWriter(vdata, "vertex")
        normal = GeomVertexWriter(vdata, "normal")
        color = GeomVertexWriter(vdata, "color")
        prim = GeomTriangles(Geom.UH_static)

        vertex_count = 0

        for lx in range(CHUNK_SIZE):
            gx = x_off + lx
            if gx >= voxel_grid.width:
                continue
            for ly in range(CHUNK_SIZE):
                gy = y_off + ly
                if gy >= voxel_grid.depth:
                    continue

                vtype = voxel_grid.get(gx, gy, z_level)
                if vtype == VOXEL_AIR:
                    continue

                # Partial-height fluid rendering
                is_fluid = vtype in FLUID_VOXELS
                if is_fluid:
                    if vtype == VOXEL_WATER:
                        fluid_level = voxel_grid.get_water_level(gx, gy, z_level)
                    else:
                        fluid_level = voxel_grid.get_lava_level(gx, gy, z_level)
                    fill_fraction = fluid_level / 255.0
                else:
                    fill_fraction = 1.0

                # Dig-queued blocks render ALL faces (golden overlay
                # visible even against solid neighbors).  The adjacent
                # solid block still culls its face toward us (no z-fight).
                is_dig = (
                    build_system is not None
                    and build_system.is_being_dug(gx, gy, z_level)
                )

                # Choose color based on render mode (pass is_dig to
                # avoid redundant O(1) lookup + linear progress scan)
                base_color = self._get_color(
                    voxel_grid, gx, gy, z_level, vtype, render_mode,
                    build_system, craft_highlights, ingredient_highlights,
                    is_dig=is_dig,
                )

                # Per-material noise amplitude
                use_noise = (
                    render_mode == RENDER_MODE_MATTER
                    and base_color != _cfg.FOG_COLOR
                )
                noise_amp = (
                    VOXEL_NOISE.get(vtype, VERTEX_NOISE_AMPLITUDE)
                    if use_noise else 0.0
                )

                for face_idx, (dx, dy, dz, face_name) in enumerate(FACES):
                    # Skip bottom faces: camera pitch is clamped to [-89, -10]
                    # (always looking down), so bottom faces are never visible
                    # and cause z-fighting between adjacent layers.
                    if face_name == "bottom":
                        continue

                    nx, ny, nz = gx + dx, gy + dy, z_level + dz
                    # Render face if neighbor is transparent (air or water)
                    # — or if this block is being dug (show gold on all faces)
                    neighbor = voxel_grid.get(nx, ny, nz)
                    if not is_dig and neighbor not in FACE_TRANSPARENT_VOXELS:
                        continue

                    # Fluid-fluid face culling: skip interior faces between
                    # same-type fluids at the same fill level
                    if is_fluid and neighbor == vtype:
                        if vtype == VOXEL_WATER:
                            neighbor_level = voxel_grid.get_water_level(nx, ny, nz)
                        else:
                            neighbor_level = voxel_grid.get_lava_level(nx, ny, nz)
                        if face_name == "top":
                            # Top face occluded if fluid above has ≥ level
                            if neighbor_level >= fluid_level:
                                continue
                        else:
                            # Side face is interior if same level
                            if neighbor_level == fluid_level:
                                continue

                    shade = FACE_SHADE[face_name]
                    fc = (
                        base_color[0] * shade,
                        base_color[1] * shade,
                        base_color[2] * shade,
                        base_color[3],
                    )
                    nrm = FACE_NORMALS[face_name]
                    offsets = FACE_VERTICES[face_name]
                    base_idx = vertex_count

                    for vi, (ox, oy, oz) in enumerate(offsets):
                        # Partial-height fluids: lower top vertices
                        vz = oz
                        if fill_fraction < 1.0 and oz == 1:
                            vz = fill_fraction
                        vertex.add_data3f(gx + ox, gy + oy, -z_level + vz)
                        normal.add_data3f(*nrm)
                        if noise_amp > 0.0:
                            n = _vertex_noise(gx, gy, z_level, face_idx, vi)
                            nc = (
                                max(0.0, min(1.0, fc[0] + n * noise_amp)),
                                max(0.0, min(1.0, fc[1] + n * noise_amp * 0.8)),
                                max(0.0, min(1.0, fc[2] + n * noise_amp * 0.6)),
                                fc[3],
                            )
                            color.add_data4f(*nc)
                        else:
                            color.add_data4f(*fc)
                        vertex_count += 1

                    # Two triangles for the quad
                    prim.add_vertices(base_idx, base_idx + 1, base_idx + 2)
                    prim.add_vertices(base_idx, base_idx + 2, base_idx + 3)

        if vertex_count == 0:
            return None

        geom = Geom(vdata)
        geom.add_primitive(prim)
        node = GeomNode(f"chunk_{chunk_x}_{chunk_y}_{z_level}")
        node.add_geom(geom)
        return node

    def _get_color(
        self,
        voxel_grid: VoxelGrid,
        x: int,
        y: int,
        z: int,
        vtype: int,
        render_mode: str,
        build_system: BuildSystem | None = None,
        craft_highlights: set | None = None,
        ingredient_highlights: set | None = None,
        is_dig: bool = False,
        face_name: str | None = None,
    ) -> tuple[float, float, float, float]:
        """Get the color for a voxel based on render mode."""
        # Fog of war: blocks not adjacent to claimed territory are dark
        # Exception: pending digs show dim gold even through fog
        if not voxel_grid.is_visible(x, y, z):
            if build_system is not None and build_system.is_pending_dig(x, y, z):
                return _lerp_color(_cfg.FOG_COLOR, (0.8, 0.65, 0.0), 0.25)
            return _cfg.FOG_COLOR

        if render_mode == RENDER_MODE_STRUCTURAL:
            s = float(voxel_grid.stress_ratio[x, y, z])
            return stress_to_color(s)

        if render_mode == RENDER_MODE_HUMIDITY:
            h = voxel_grid.get_humidity(x, y, z)
            matter = self._get_matter_color(
                voxel_grid, x, y, z, vtype,
                build_system, craft_highlights, ingredient_highlights,
                is_dig,
            )
            return humidity_to_color(h, base_color=matter)

        if render_mode == RENDER_MODE_HEAT:
            temp = voxel_grid.get_temperature(x, y, z)
            return temperature_to_color(temp)

        if render_mode == RENDER_MODE_PROSPECTING:
            # Muted grey tones so ore glow markers stand out
            base = VOXEL_COLORS.get(vtype, (1.0, 0.0, 1.0, 1.0))
            grey = 0.18 + 0.12 * (base[0] * 0.3 + base[1] * 0.59 + base[2] * 0.11)
            return (grey, grey, grey * 1.05, base[3])

        # Matter mode (default)
        return self._get_matter_color(
            voxel_grid, x, y, z, vtype,
            build_system, craft_highlights, ingredient_highlights,
            is_dig,
        )

    def _get_matter_color(
        self,
        voxel_grid: VoxelGrid,
        x: int,
        y: int,
        z: int,
        vtype: int,
        build_system: BuildSystem | None = None,
        craft_highlights: set | None = None,
        ingredient_highlights: set | None = None,
        is_dig: bool = False,
    ) -> tuple[float, float, float, float]:
        """Compute the matter-mode colour for a voxel.

        Includes metal tinting, dig overlay, craft highlights, door
        transparency, loose dimming — everything except render-mode
        overlays (humidity/heat/structural/prospecting).
        """
        base = VOXEL_COLORS.get(vtype, (1.0, 0.0, 1.0, 1.0))

        # Metal-variant tinting for metallic blocks
        if vtype in METALLIC_BLOCKS:
            mt = voxel_grid.get_metal_type(x, y, z)
            base_mt = mt & 0x7F  # strip enchanted bit
            if base_mt in METAL_COLORS:
                base = _lerp_color(base, METAL_COLORS[base_mt], 0.4)
            # Enchanted blocks get a purple shimmer
            if mt & ENCHANTED_OFFSET:
                base = _lerp_color(base, (0.6, 0.2, 0.9), 0.15)

        # Golden overlay for blocks being dug
        if is_dig:
            progress = build_system.get_dig_progress(x, y, z)
            # 0.4 blend at start, 0.7 near done
            t = 0.4 + 0.3 * max(0.0, progress)
            return _lerp_color(base, (1.0, 0.85, 0.0), t)

        # Green overlay for craft-valid positions (solid blocks)
        if craft_highlights is not None and (x, y, z) in craft_highlights:
            return _lerp_color(base, (0.2, 1.0, 0.3), 0.45)

        # Cyan overlay for ingredient highlights (temporary, from crafting panel)
        if ingredient_highlights is not None and (x, y, z) in ingredient_highlights:
            return _lerp_color(base, (0.3, 0.9, 1.0), 0.5)

        # Open doors and open floodgates are semi-transparent
        if vtype == VOXEL_DOOR and voxel_grid.get_block_state(x, y, z) == 0:
            return (base[0], base[1], base[2], 0.3)
        if vtype == VOXEL_FLOODGATE and voxel_grid.get_block_state(x, y, z) == 0:
            return (base[0], base[1], base[2], 0.3)
        # Iron bars: semi-transparent (you can see through)
        if vtype == VOXEL_IRON_BARS:
            return (base[0], base[1], base[2], 0.7)
        # Water: alpha varies with water_level (matches lava pattern)
        if vtype == VOXEL_WATER:
            water_lvl = voxel_grid.get_water_level(x, y, z)
            alpha = max(0.3, water_lvl / 255.0) if water_lvl < 255 else 0.7
            return (base[0], base[1], base[2], alpha)
        # Lava: alpha based on lava_level, mana crystal tint
        if vtype == _cfg.VOXEL_LAVA:
            lava_lvl = voxel_grid.get_lava_level(x, y, z)
            alpha = max(0.3, lava_lvl / 255.0) if lava_lvl < 255 else 1.0
            mana_count = voxel_grid.get_mana_crystals(x, y, z)
            if mana_count >= 1:
                # Tint toward MANA_LAVA_COLOR (orange-magenta)
                t = min(0.5, mana_count * 0.15)
                tinted = _lerp_color(base, _cfg.MANA_LAVA_COLOR, t)
                return (tinted[0], tinted[1], tinted[2], alpha)
            return (base[0], base[1], base[2], alpha)
        # Steam vent: slight transparency
        if vtype == VOXEL_STEAM_VENT:
            return (base[0], base[1], base[2], 0.8)
        # Dim loose material slightly
        if voxel_grid.is_loose(x, y, z):
            return (base[0] * 0.7, base[1] * 0.7, base[2] * 0.7, base[3])
        return base


class VoxelWorldRenderer:
    """Manages all chunk meshes and updates them when voxels change."""

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        layer_manager: LayerSliceManager,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.layer_manager = layer_manager
        self.mesh_builder = ChunkMeshBuilder()
        self.render_mode: str = RENDER_MODE_MATTER
        self.build_system: BuildSystem | None = None  # set after construction
        self.craft_highlights: set[tuple[int, int, int]] | None = None

        # chunk_key (cx, cy, z) -> NodePath
        self._chunk_nodes: dict[tuple[int, int, int], NodePath] = {}

        # Track chunks containing active digs for periodic progress refresh
        self._dig_chunks: set[tuple[int, int, int]] = set()

        # Ingredient highlight (temporary cyan tint from crafting panel)
        self._ingredient_highlights: set[tuple[int, int, int]] | None = None
        self._ingredient_clear_tick: int = 0
        self._current_tick: int = 0
        self._batch_rebuilt_chunks: set[tuple[int, int, int]] = set()

        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("dig_queued", self._on_dig_state_changed)
        event_bus.subscribe("dig_complete", self._on_dig_state_changed)
        event_bus.subscribe("dig_cancelled", self._on_dig_state_changed)
        event_bus.subscribe("dig_pending", self._on_dig_state_changed)
        event_bus.subscribe("dig_batch_queued", self._on_dig_batch_changed)
        event_bus.subscribe("dig_batch_cancelled", self._on_dig_batch_changed)
        event_bus.subscribe("dig_batch_pending", self._on_dig_batch_changed)
        event_bus.subscribe("dig_batch_complete", self._on_dig_batch_changed)
        event_bus.subscribe("tick", self._on_tick_refresh_digs)
        event_bus.subscribe(
            "claimed_territory_changed",
            lambda **kw: self.update_dirty_chunks(),
        )
        # Batch pick-up (drag-select loose, auto-bag) sets voxels to air
        # without per-voxel voxel_changed — flush dirty chunks on the
        # single material_picked_up event instead.
        event_bus.subscribe(
            "material_picked_up",
            lambda **kw: self.update_dirty_chunks(),
        )
        event_bus.subscribe(
            "water_flowed",
            lambda **kw: self.update_dirty_chunks(),
        )
        event_bus.subscribe("craft_highlights_updated", self._on_craft_highlights_updated)
        event_bus.subscribe("craft_highlights_cleared", self._on_craft_highlights_cleared)
        event_bus.subscribe("ingredient_highlight", self._on_ingredient_highlight)

    def set_render_mode(self, mode: str) -> None:
        """Switch render mode and rebuild all chunks."""
        if mode == self.render_mode:
            logger.debug("set_render_mode(%r): SKIPPED (same mode)", mode)
            return
        old_mode = self.render_mode
        self.render_mode = mode
        # Force a territory recompute so visible[] is fresh before rebuild
        self.event_bus.publish("force_territory_recompute")
        # Force a complete rebuild (don't rely on the dirty-chunk path which
        # might race with tick-driven territory / physics updates).
        self._force_rebuild_all()
        logger.debug(
            "set_render_mode: %r → %r, %d chunks in scene",
            old_mode, mode, len(self._chunk_nodes),
        )

    def _force_rebuild_all(self) -> None:
        """Rebuild every chunk from scratch, bypassing the dirty-chunk set.

        This avoids any race where ``pop_dirty_chunks()`` returns a stale or
        incomplete set due to concurrent dirty-marking from tick events.

        Optimisation: skips z-levels that have no visible blocks (fog of
        war) to avoid unnecessary mesh builds during mode switches.
        """
        import numpy as np
        vg = self.voxel_grid
        vis_count = int(np.count_nonzero(vg.visible))
        total_solid = int(np.count_nonzero(vg.grid != VOXEL_AIR))
        logger.debug(
            "_force_rebuild_all: visible=%d / total_solid=%d (mode=%s)",
            vis_count, total_solid, self.render_mode,
        )

        # Pre-compute which z-levels have any visible blocks
        has_visible = np.any(vg.visible, axis=(0, 1))  # shape (h,)

        for z in range(vg.height):
            if not has_visible[z]:
                # No visible blocks at this z — remove any old meshes and skip
                for cx in range(vg.chunks_x):
                    for cy in range(vg.chunks_y):
                        key = (cx, cy, z)
                        old = self._chunk_nodes.pop(key, None)
                        if old is not None:
                            old.remove_node()
                continue
            for cx in range(vg.chunks_x):
                for cy in range(vg.chunks_y):
                    self._rebuild_chunk(cx, cy, z)
        # Flush any dirty chunks that were added during the rebuild so the
        # next ``update_dirty_chunks()`` call doesn't redo the work.
        vg.pop_dirty_chunks()

    def build_all_chunks(self) -> None:
        """Build meshes for the entire world. Called once at startup."""
        logger.info("Building all chunk meshes...")
        count = 0
        for z in range(self.voxel_grid.height):
            for cx in range(self.voxel_grid.chunks_x):
                for cy in range(self.voxel_grid.chunks_y):
                    self._rebuild_chunk(cx, cy, z)
                    count += 1
        logger.info("Built %d chunks", count)

    def update_dirty_chunks(self) -> None:
        """Rebuild any chunks that were marked dirty."""
        dirty = self.voxel_grid.pop_dirty_chunks()
        for cx, cy, z in dirty:
            self._rebuild_chunk(cx, cy, z)

    def _rebuild_chunk(self, cx: int, cy: int, z: int) -> None:
        key = (cx, cy, z)

        # Remove old mesh if it exists
        old = self._chunk_nodes.pop(key, None)
        if old is not None:
            old.remove_node()

        # Build new mesh
        geom_node = self.mesh_builder.build(
            self.voxel_grid, cx, cy, z, render_mode=self.render_mode,
            build_system=self.build_system,
            craft_highlights=self.craft_highlights,
            ingredient_highlights=self._ingredient_highlights,
        )
        if geom_node is None:
            return

        # Attach to the appropriate layer
        layer_np = self.layer_manager.get_layer(z)
        if layer_np is None:
            return

        np = layer_np.attach_new_node(geom_node)
        self._chunk_nodes[key] = np

    def _on_voxel_changed(self, x: int, y: int, z: int, **kwargs) -> None:
        """Schedule chunk rebuilds when a voxel changes."""
        # The VoxelGrid already marks dirty chunks, so we just need to
        # rebuild on next update. We could do it immediately, but batching
        # via update_dirty_chunks is more efficient during bulk operations.
        self.update_dirty_chunks()

    def _on_dig_state_changed(self, x: int, y: int, z: int, **kwargs) -> None:
        """Rebuild the chunk when a dig is queued or completed."""
        cx, cy = x // CHUNK_SIZE, y // CHUNK_SIZE
        key = (cx, cy, z)
        self._dig_chunks.discard(key)
        # Track chunk if dig is still active
        if self.build_system is not None and self.build_system.is_being_dug(x, y, z):
            self._dig_chunks.add(key)
        # Skip if already rebuilt by a batch event this tick
        if key in self._batch_rebuilt_chunks:
            return
        self._rebuild_chunk(cx, cy, z)

    def _on_dig_batch_changed(
        self, positions: list[tuple[int, int, int]], **kwargs,
    ) -> None:
        """Rebuild each *unique* chunk once for a batch of dig changes."""
        chunks_to_rebuild: set[tuple[int, int, int]] = set()
        dig_set = (
            self.build_system._dig_positions
            if self.build_system is not None
            else set()
        )
        for x, y, z in positions:
            cx, cy = x // CHUNK_SIZE, y // CHUNK_SIZE
            key = (cx, cy, z)
            self._dig_chunks.discard(key)
            if (x, y, z) in dig_set:
                self._dig_chunks.add(key)
            chunks_to_rebuild.add(key)
        for cx, cy, z in chunks_to_rebuild:
            self._rebuild_chunk(cx, cy, z)
        # Record so per-voxel dig_complete events skip these chunks
        self._batch_rebuilt_chunks.update(chunks_to_rebuild)

    def _on_tick_refresh_digs(self, tick: int, **kwargs) -> None:
        """Periodically rebuild dig chunks to show progress animation."""
        self._current_tick = tick
        self._batch_rebuilt_chunks.clear()

        # Safety: repopulate _dig_chunks if digs exist but tracking was lost
        if not self._dig_chunks and self.build_system is not None:
            for job in self.build_system.active_digs + self.build_system.dig_queue:
                cx, cy = job.x // CHUNK_SIZE, job.y // CHUNK_SIZE
                self._dig_chunks.add((cx, cy, job.z))
            # Also track pending digs (they need chunk rebuilds too)
            if hasattr(self.build_system, 'pending_digs'):
                for job in self.build_system.pending_digs:
                    cx, cy = job.x // CHUNK_SIZE, job.y // CHUNK_SIZE
                    self._dig_chunks.add((cx, cy, job.z))

        if not self._dig_chunks:
            # Clear ingredient highlights if timer expired
            if self._ingredient_highlights and tick >= self._ingredient_clear_tick:
                self._clear_ingredient_highlights()
            return
        # Refresh every 5 ticks (~4x/sec) for smooth progress updates
        if tick % 5 != 0:
            # Still check ingredient highlight timeout
            if self._ingredient_highlights and tick >= self._ingredient_clear_tick:
                self._clear_ingredient_highlights()
            return
        # Rebuild all chunks that have active digs
        stale = set()
        for key in list(self._dig_chunks):
            cx, cy, z = key
            self._rebuild_chunk(cx, cy, z)
            # Check if any digs remain in this chunk via position index
            # (O(chunk_area) set lookups instead of O(chunk_area × queue_size))
            has_digs = False
            if self.build_system is not None:
                x_off = cx * CHUNK_SIZE
                y_off = cy * CHUNK_SIZE
                dig_set = self.build_system._dig_positions
                for lx in range(CHUNK_SIZE):
                    for ly in range(CHUNK_SIZE):
                        if (x_off + lx, y_off + ly, z) in dig_set:
                            has_digs = True
                            break
                    if has_digs:
                        break
            if not has_digs:
                stale.add(key)
        self._dig_chunks -= stale

        # Check ingredient highlight timeout
        if self._ingredient_highlights and tick >= self._ingredient_clear_tick:
            self._clear_ingredient_highlights()

    def _on_craft_highlights_updated(self, positions: set, **kwargs) -> None:
        """Store highlights and rebuild affected chunks."""
        old = self.craft_highlights or set()
        self.craft_highlights = positions if positions else None
        # Rebuild chunks that gained or lost highlights
        affected_chunks: set[tuple[int, int, int]] = set()
        for x, y, z in old | (positions or set()):
            affected_chunks.add((x // CHUNK_SIZE, y // CHUNK_SIZE, z))
        for cx, cy, z in affected_chunks:
            self._rebuild_chunk(cx, cy, z)

    def _on_craft_highlights_cleared(self, **kwargs) -> None:
        """Clear highlights and rebuild affected chunks."""
        if self.craft_highlights:
            old = self.craft_highlights
            self.craft_highlights = None
            affected_chunks: set[tuple[int, int, int]] = set()
            for x, y, z in old:
                affected_chunks.add((x // CHUNK_SIZE, y // CHUNK_SIZE, z))
            for cx, cy, z in affected_chunks:
                self._rebuild_chunk(cx, cy, z)

    # ── Ingredient highlighting (temporary cyan) ─────────────────────

    def _on_ingredient_highlight(self, positions: set, **kwargs) -> None:
        """Show cyan highlights on ingredient blocks for 3 seconds."""
        old = self._ingredient_highlights or set()
        self._ingredient_highlights = positions if positions else None
        # Clear after 60 ticks (3 seconds at 20 TPS)
        self._ingredient_clear_tick = self._current_tick + 60
        # Rebuild affected chunks
        affected: set[tuple[int, int, int]] = set()
        for x, y, z in old | (positions or set()):
            affected.add((x // CHUNK_SIZE, y // CHUNK_SIZE, z))
        for cx, cy, z in affected:
            self._rebuild_chunk(cx, cy, z)

    def _clear_ingredient_highlights(self) -> None:
        """Remove ingredient highlights and rebuild affected chunks."""
        if not self._ingredient_highlights:
            return
        old = self._ingredient_highlights
        self._ingredient_highlights = None
        affected: set[tuple[int, int, int]] = set()
        for x, y, z in old:
            affected.add((x // CHUNK_SIZE, y // CHUNK_SIZE, z))
        for cx, cy, z in affected:
            self._rebuild_chunk(cx, cy, z)
