"""Enchanted block management panel — activation, charging, and status.

Appears when a player clicks an enchanted block.  Displays block name,
capacitance bar, and buttons for activate/deactivate and charge mode
(charge / stop / drain).  All interaction flows through the EventBus —
the panel never imports game-logic modules directly.

Dependencies: core.event_bus, core.game_state, ui.voxel_names, ui.style
Dependents: main (wiring)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from direct.gui.DirectGui import (
    DirectFrame,
    DirectLabel,
    DirectButton,
    DirectWaitBar,
)
from panda3d.core import TextNode
from direct.showbase.ShowBase import ShowBase

from dungeon_builder.ui.voxel_names import VTYPE_NAMES as _VTYPE_NAMES
from dungeon_builder.ui import style as _sty

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState

logger = logging.getLogger("dungeon_builder.ui")

# Button bounds: narrower than global BUTTON_SIZE for side-by-side layout
_BTN_SMALL = (-0.14, 0.14, -0.04, 0.05)
_BTN_WIDE = (-0.20, 0.20, -0.04, 0.05)


class EnchantedBlockPanel:
    """Panel for inspecting and controlling a selected enchanted block.

    Shown on ``enchanted_block_selected``, hidden on deselect/remove.
    """

    def __init__(
        self,
        app: ShowBase,
        event_bus: EventBus,
        game_state: GameState,
    ) -> None:
        self.app = app
        self.event_bus = event_bus
        self.game_state = game_state

        # Currently displayed block position (None when hidden)
        self._pos: tuple[int, int, int] | None = None
        # Cached state for button highlighting
        self._activated: bool = True
        self._charge_mode: str = "idle"

        self._build_panel()
        self._subscribe_events()

    # ── UI construction ──────────────────────────────────────────────

    def _build_panel(self) -> None:
        """Build the panel frame and all child widgets."""
        a2d = self.app.aspect2d

        self._frame = DirectFrame(
            parent=a2d,
            frameColor=_sty.BG_COLOR,
            frameSize=(-0.45, 0.45, -0.28, 0.28),
            pos=(-1.05, 0, -0.35),
            sortOrder=_sty.PANEL_SORT_ORDER,
        )
        self._frame.hide()

        # Title label (block name)
        self._title = DirectLabel(
            parent=self._frame,
            text="Enchanted Block",
            text_fg=_sty.TITLE_COLOR,
            text_scale=0.05,
            text_align=TextNode.ALeft,
            pos=(-0.40, 0, 0.20),
            frameColor=_sty.TRANSPARENT,
        )

        # Close button [X]
        DirectButton(
            parent=self._frame,
            text="X",
            text_fg=_sty.ERROR_COLOR,
            text_scale=0.045,
            frameColor=_sty.TRANSPARENT,
            pos=(0.40, 0, 0.20),
            command=self._on_close,
        )

        # Capacitance text label
        self._cap_label = DirectLabel(
            parent=self._frame,
            text="Mana: 0.0 / 0.0",
            text_fg=_sty.MANA_COLOR,
            text_scale=0.04,
            text_align=TextNode.ALeft,
            pos=(-0.40, 0, 0.12),
            frameColor=_sty.TRANSPARENT,
        )

        # Capacitance bar
        self._cap_bar = DirectWaitBar(
            parent=self._frame,
            range=100,
            value=0,
            frameSize=(-0.40, 0.40, -0.01, 0.02),
            pos=(0, 0, 0.07),
            barColor=_sty.MANA_COLOR,
            frameColor=(0.2, 0.2, 0.2, 0.8),
        )

        # ── Activation buttons ────────────────────────────────────────

        self._btn_active = DirectButton(
            parent=self._frame,
            text="Active",
            text_scale=0.04,
            text_fg=_sty.BUTTON_FG,
            frameColor=_sty.BUTTON_BG,
            frameSize=_BTN_WIDE,
            pos=(-0.22, 0, -0.01),
            command=self._on_toggle_activation,
        )

        self._btn_inactive = DirectButton(
            parent=self._frame,
            text="Inactive",
            text_scale=0.04,
            text_fg=_sty.BUTTON_FG,
            frameColor=_sty.BUTTON_BG,
            frameSize=_BTN_WIDE,
            pos=(0.22, 0, -0.01),
            command=self._on_toggle_activation,
        )

        # ── Charge mode buttons ───────────────────────────────────────

        self._btn_charge = DirectButton(
            parent=self._frame,
            text="Charge",
            text_scale=0.04,
            text_fg=_sty.BUTTON_FG,
            frameColor=_sty.BUTTON_BG,
            frameSize=_BTN_SMALL,
            pos=(-0.30, 0, -0.12),
            command=lambda: self._on_charge_mode("charging"),
        )

        self._btn_stop = DirectButton(
            parent=self._frame,
            text="Stop",
            text_scale=0.04,
            text_fg=_sty.BUTTON_FG,
            frameColor=_sty.BUTTON_BG,
            frameSize=_BTN_SMALL,
            pos=(0.0, 0, -0.12),
            command=lambda: self._on_charge_mode("idle"),
        )

        self._btn_drain = DirectButton(
            parent=self._frame,
            text="Drain",
            text_scale=0.04,
            text_fg=_sty.BUTTON_FG,
            frameColor=_sty.BUTTON_BG,
            frameSize=_BTN_SMALL,
            pos=(0.30, 0, -0.12),
            command=lambda: self._on_charge_mode("draining"),
        )

        # Drain info label
        self._drain_info = DirectLabel(
            parent=self._frame,
            text="",
            text_fg=_sty.MUTED_COLOR,
            text_scale=0.032,
            text_align=TextNode.ACenter,
            pos=(0.0, 0, -0.21),
            frameColor=_sty.TRANSPARENT,
        )

    # ── Event wiring ─────────────────────────────────────────────────

    def _subscribe_events(self) -> None:
        sub = self.event_bus.subscribe
        sub("enchanted_block_selected", self._on_selected)
        sub("enchanted_block_deselected", self._on_deselected)
        sub("enchanted_block_removed", self._on_removed)
        sub("enchanted_block_state_changed", self._on_state_changed)
        sub("mana_changed", self._on_mana_changed)

    # ── Event handlers ───────────────────────────────────────────────

    def _on_selected(self, x: int, y: int, z: int, **kw) -> None:
        """Show panel and populate with block state."""
        self._pos = (x, y, z)
        ms = self.game_state.mana_system
        if ms is None:
            return

        vtype = self.game_state.voxel_grid.get(x, y, z)
        name = _VTYPE_NAMES.get(vtype, f"Block {vtype}")
        self._title["text"] = name

        state = ms.get_enchanted_block_state(x, y, z)
        if state is not None:
            self._refresh(state)

        self._frame.show()

    def _on_deselected(self, **kw) -> None:
        self._pos = None
        self._frame.hide()

    def _on_removed(self, x: int, y: int, z: int, **kw) -> None:
        """Auto-deselect if the selected block was removed."""
        if self._pos == (x, y, z):
            self.game_state.selected_block = None
            self._pos = None
            self._frame.hide()

    def _on_state_changed(self, x: int, y: int, z: int, **kw) -> None:
        """Refresh if this is the selected block."""
        if self._pos != (x, y, z):
            return
        self._refresh(kw)

    def _on_mana_changed(self, **kw) -> None:
        """Refresh capacitance bar periodically (fires every ~10 ticks)."""
        if self._pos is None:
            return
        ms = self.game_state.mana_system
        if ms is None:
            return
        x, y, z = self._pos
        state = ms.get_enchanted_block_state(x, y, z)
        if state is not None:
            self._refresh_bar(state["capacitance"], state["max_capacitance"])

    # ── Button callbacks ─────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._pos is not None:
            self.game_state.selected_block = None
            self.event_bus.publish("enchanted_block_deselected")

    def _on_toggle_activation(self) -> None:
        if self._pos is None:
            return
        x, y, z = self._pos
        self.event_bus.publish(
            "enchanted_block_toggle_activation", x=x, y=y, z=z,
        )

    def _on_charge_mode(self, mode: str) -> None:
        if self._pos is None:
            return
        x, y, z = self._pos
        self.event_bus.publish(
            "enchanted_block_set_charge_mode", x=x, y=y, z=z, mode=mode,
        )

    # ── Refresh helpers ──────────────────────────────────────────────

    def _refresh(self, state: dict) -> None:
        """Update all widgets from a state dict."""
        cap = state.get("capacitance", 0.0)
        max_cap = state.get("max_capacitance", 1.0)
        activated = state.get("activated", True)
        charge_mode = state.get("charge_mode", "idle")

        self._activated = activated
        self._charge_mode = charge_mode

        self._refresh_bar(cap, max_cap)
        self._refresh_buttons()

    def _refresh_bar(self, cap: float, max_cap: float) -> None:
        """Update capacitance label and bar."""
        self._cap_label["text"] = f"Mana: {cap:.1f} / {max_cap:.1f}"
        pct = (cap / max_cap * 100) if max_cap > 0 else 0
        self._cap_bar["value"] = pct

    def _refresh_buttons(self) -> None:
        """Highlight the active button states."""
        # Activation buttons
        if self._activated:
            self._btn_active["frameColor"] = _sty.ENABLED_COLOR
            self._btn_inactive["frameColor"] = _sty.BUTTON_BG
        else:
            self._btn_active["frameColor"] = _sty.BUTTON_BG
            self._btn_inactive["frameColor"] = _sty.ENABLED_COLOR

        # Charge mode buttons
        mode_btns = {
            "charging": self._btn_charge,
            "idle": self._btn_stop,
            "draining": self._btn_drain,
        }
        for mode, btn in mode_btns.items():
            if mode == self._charge_mode:
                btn["frameColor"] = _sty.HIGHLIGHT_COLOR
            else:
                btn["frameColor"] = _sty.BUTTON_BG

        # Info text
        if self._charge_mode == "charging":
            self._drain_info["text"] = "Charging from core reserve"
        elif self._charge_mode == "draining":
            self._drain_info["text"] = "Draining \u2014 1 mana/s reclaimed"
        else:
            self._drain_info["text"] = ""
