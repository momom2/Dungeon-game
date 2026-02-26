"""Intruder visual rendering using simple procedural cubes.

Each archetype gets a distinct color so the player can identify types at a
glance.  Intruder nodes are attached to the layer system so they inherit
z-level alpha transparency, matching the voxel depth-fade.

Dependencies: config, core.event_bus, intruders.agent, rendering.layer_slice
Dependents: main (wiring), tests/rendering/test_intruder_renderer.py
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
from direct.showbase.ShowBase import ShowBase

from dungeon_builder.config import (
    ARCHETYPE_COLORS,
    ARCHETYPE_DEFAULT_COLOR,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.intruders.agent import Intruder
    from dungeon_builder.rendering.layer_slice import LayerSliceManager

logger = logging.getLogger("dungeon_builder.rendering.intruders")


# ── Geometry helpers ──────────────────────────────────────────────────

def _make_cube_geom(r: float, g: float, b: float, size: float = 0.4) -> GeomNode:
    """Create a small colored cube GeomNode."""
    vdata = GeomVertexData("intruder", GeomVertexFormat.get_v3n3c4(), Geom.UH_static)
    vertex = GeomVertexWriter(vdata, "vertex")
    normal = GeomVertexWriter(vdata, "normal")
    color = GeomVertexWriter(vdata, "color")
    prim = GeomTriangles(Geom.UH_static)

    s = size / 2.0
    # 6 faces, 4 verts each
    faces = [
        # (normal, 4 corners)
        ((0, 0, 1), [(-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]),
        ((0, 0, -1), [(-s, s, -s), (s, s, -s), (s, -s, -s), (-s, -s, -s)]),
        ((1, 0, 0), [(s, -s, -s), (s, s, -s), (s, s, s), (s, -s, s)]),
        ((-1, 0, 0), [(-s, s, -s), (-s, -s, -s), (-s, -s, s), (-s, s, s)]),
        ((0, 1, 0), [(s, s, -s), (-s, s, -s), (-s, s, s), (s, s, s)]),
        ((0, -1, 0), [(-s, -s, -s), (s, -s, -s), (s, -s, s), (-s, -s, s)]),
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
    node = GeomNode("intruder_cube")
    node.add_geom(geom)
    return node


def _archetype_color(intruder: Intruder) -> tuple[float, float, float]:
    """Return the (R, G, B) color for an intruder based on archetype."""
    return ARCHETYPE_COLORS.get(
        intruder.archetype.name, ARCHETYPE_DEFAULT_COLOR
    )


# ── Renderer ──────────────────────────────────────────────────────────

class IntruderRenderer:
    """Renders intruders as colored cubes, updates positions via events.

    Each archetype gets a unique color.  Intruder nodes are parented to the
    layer system so they inherit z-level alpha transparency.
    """

    def __init__(
        self,
        app: ShowBase,
        event_bus: EventBus,
        layer_manager: LayerSliceManager | None = None,
    ) -> None:
        self.app = app
        self.event_bus = event_bus
        self._layer_manager = layer_manager
        self._models: dict[int, NodePath] = {}

        event_bus.subscribe("intruder_spawned", self._on_spawn)
        event_bus.subscribe("intruder_moved", self._on_moved)
        event_bus.subscribe("intruder_died", self._on_removed)
        event_bus.subscribe("intruder_escaped", self._on_removed)

    # ── Helpers ────────────────────────────────────────────────────────

    def _get_parent(self, z: int) -> NodePath:
        """Return the layer NodePath for the given z, or app.render as fallback."""
        if self._layer_manager is not None:
            return self._layer_manager.get_layer(z)
        return self.app.render

    # ── Event handlers ────────────────────────────────────────────────

    def _on_spawn(self, intruder: Intruder) -> None:
        rgb = _archetype_color(intruder)
        node = _make_cube_geom(*rgb, size=0.6)
        parent = self._get_parent(intruder.z)
        np = parent.attach_new_node(node)
        np.set_pos(intruder.x + 0.5, intruder.y + 0.5, -intruder.z + 0.5)
        self._models[intruder.id] = np

    def _on_moved(self, intruder: Intruder, **kwargs) -> None:
        np = self._models.get(intruder.id)
        if not np:
            return

        # Reparent to correct layer if z changed
        parent = self._get_parent(intruder.z)
        if np.get_parent() != parent:
            np.reparent_to(parent)

        np.set_pos(intruder.x + 0.5, intruder.y + 0.5, -intruder.z + 0.5)

    def _on_removed(self, intruder: Intruder, **kwargs) -> None:
        """Handle both death and escape — clean up the visual node."""
        np = self._models.pop(intruder.id, None)
        if np:
            np.remove_node()

