"""Dropdown menu for switching between render modes (matter/humidity/heat).

Dependencies: config, core.event_bus, core.keybinding_registry,
    rendering.voxel_renderer
Dependents: main (wiring), tests/ui/test_render_mode_selector.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from direct.gui.DirectGui import DirectOptionMenu
from direct.showbase.ShowBase import ShowBase

from dungeon_builder.config import (
    RENDER_MODE_MATTER,
    RENDER_MODE_HUMIDITY,
    RENDER_MODE_HEAT,
    RENDER_MODE_STRUCTURAL,
    RENDER_MODE_PROSPECTING,
    RENDER_MODE_CONNECTIONS,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.keybinding_registry import KeybindingRegistry
    from dungeon_builder.rendering.voxel_renderer import VoxelWorldRenderer

logger = logging.getLogger("dungeon_builder.render_mode")

_MODES = [RENDER_MODE_MATTER, RENDER_MODE_HUMIDITY, RENDER_MODE_HEAT, RENDER_MODE_STRUCTURAL, RENDER_MODE_PROSPECTING, RENDER_MODE_CONNECTIONS]
_LABELS = {"matter": "Matter", "humidity": "Humidity", "heat": "Heat", "structural": "Structural", "prospecting": "Prospecting", "connections": "Connections"}


class RenderModeSelector:
    """Dropdown and keyboard shortcut (V) for switching render overlays."""

    def __init__(
        self,
        app: ShowBase,
        event_bus: EventBus,
        world_renderer: VoxelWorldRenderer,
        keybinding_registry: KeybindingRegistry | None = None,
    ) -> None:
        self.app = app
        self.event_bus = event_bus
        self.world_renderer = world_renderer
        self._kb = keybinding_registry
        self._current_index = 0

        self.menu = DirectOptionMenu(
            text="View",
            scale=0.06,
            items=[_LABELS[m] for m in _MODES],
            initialitem=0,
            highlightColor=(0.65, 0.65, 0.65, 1),
            command=self._on_select,
            pos=(1.1, 0, 0.82),
        )

        _key = self._kb.get("cycle_render_mode") if self._kb else "v"
        app.accept(_key, self._cycle_mode)

    def _on_select(self, label: str) -> None:
        logger.debug("_on_select(%r) called, current_index=%d", label, self._current_index)
        for mode, lbl in _LABELS.items():
            if lbl == label:
                self._current_index = _MODES.index(mode)
                self.world_renderer.set_render_mode(mode)
                self.event_bus.publish("render_mode_changed", mode=mode)
                return
        logger.warning("_on_select: no matching mode for label %r", label)

    def _cycle_mode(self) -> None:
        self._current_index = (self._current_index + 1) % len(_MODES)
        mode = _MODES[self._current_index]
        logger.debug("_cycle_mode: index=%d, mode=%r", self._current_index, mode)
        self.world_renderer.set_render_mode(mode)
        self.menu.set(self._current_index, fCommand=0)
        self.event_bus.publish("render_mode_changed", mode=mode)
