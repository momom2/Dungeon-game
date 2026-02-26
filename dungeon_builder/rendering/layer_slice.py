"""Z-level layer transparency management for slice rendering.

Asymmetric visibility: layers above the focus (ceiling) are very
transparent, while layers below (depth) extend further with a gradual fade.

Dependencies: config, core.event_bus
Dependents: main (wiring), rendering.camera, rendering.effects,
    rendering.intruder_renderer, rendering.voxel_renderer
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from panda3d.core import NodePath, TransparencyAttrib

import dungeon_builder.config as _cfg
from dungeon_builder.config import GRID_HEIGHT, CORE_Z

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus


class LayerSliceManager:
    """Manages per-Z-level parent NodePaths and their transparency.

    The focused Z-level is fully opaque. Layers above are very faint
    (ceiling context). Layers below extend deeper with gradual fade.
    """

    def __init__(self, render_node: NodePath, event_bus: EventBus | None = None) -> None:
        self.render_node = render_node
        self.layers: dict[int, NodePath] = {}
        self.current_z: int = CORE_Z  # Start focused on the dungeon core

        self._create_layers()
        self.set_focus_z(self.current_z)

        if event_bus is not None:
            event_bus.subscribe("config_changed", self._on_config_changed)

    def _create_layers(self) -> None:
        for z in range(GRID_HEIGHT):
            layer_np = self.render_node.attach_new_node(f"layer_{z}")
            self.layers[z] = layer_np

    def get_layer(self, z: int) -> NodePath | None:
        return self.layers.get(z)

    def set_focus_z(self, z: int) -> None:
        z = max(0, min(GRID_HEIGHT - 1, z))
        self.current_z = z

        # When depth-fade is disabled, every layer is fully opaque & visible.
        if not _cfg.LAYER_DEPTH_FADE:
            for _zl, np in self.layers.items():
                np.show()
                np.clear_transparency()
                np.set_alpha_scale(1.0)
            return

        for zl, np in self.layers.items():
            if zl == z:
                # Focus layer: fully opaque
                np.show()
                np.clear_transparency()
                np.set_alpha_scale(1.0)
            elif zl < z:
                # Above focus (toward surface)
                offset = z - zl
                if offset > _cfg.LAYER_MAX_VISIBLE_ABOVE:
                    np.hide()
                else:
                    np.show()
                    alpha = _cfg.LAYER_ALPHA_ABOVE.get(offset, 0.0)
                    if alpha < 1.0:
                        np.set_transparency(TransparencyAttrib.M_alpha)
                        np.set_alpha_scale(alpha)
                    else:
                        np.clear_transparency()
                        np.set_alpha_scale(1.0)
            else:
                # Below focus (deeper)
                offset = zl - z
                if offset > _cfg.LAYER_MAX_VISIBLE_BELOW:
                    np.hide()
                else:
                    np.show()
                    alpha = _cfg.LAYER_ALPHA_BELOW.get(offset, 0.0)
                    if alpha < 1.0:
                        np.set_transparency(TransparencyAttrib.M_alpha)
                        np.set_alpha_scale(alpha)
                    else:
                        np.clear_transparency()
                        np.set_alpha_scale(1.0)

    def _on_config_changed(self, key: str = "", **kwargs) -> None:
        """Re-apply layer visibility when relevant config changes."""
        _LAYER_KEYS = {
            "LAYER_MAX_VISIBLE_BELOW", "LAYER_MAX_VISIBLE_ABOVE",
            "LAYER_ALPHA_ABOVE", "LAYER_ALPHA_BELOW",
            "LAYER_DEPTH_FADE",
            "all_visibility",
        }
        if key in _LAYER_KEYS:
            self.set_focus_z(self.current_z)
