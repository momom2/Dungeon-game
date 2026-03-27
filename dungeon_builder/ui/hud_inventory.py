"""Inventory (bag) panel mixin for the HUD.

Extracted from hud.py to keep file sizes under ~600 lines.
Provides the left-side scrollable inventory overlay that lists
held materials, toggled by the bag button or the [I] key.

Dependencies: config, ui.voxel_names, ui.style
Dependents: ui.hud (HUD inherits InventoryMixin)
"""

from __future__ import annotations

from direct.gui.DirectGui import (
    DirectFrame, DirectLabel, DirectButton, DirectScrolledFrame,
)
from panda3d.core import TextNode

from dungeon_builder.config import VOXEL_COLORS
from dungeon_builder.ui.voxel_names import VTYPE_NAMES as _VTYPE_NAMES
from dungeon_builder.ui import style as _sty


class InventoryMixin:
    """Bag/inventory panel methods, mixed into :class:`HUD`.

    All ``self.*`` attributes referenced here are initialised by
    ``HUD.__init__`` before any mixin method is called.  The mixin
    only *defines* methods; it never defines ``__init__``.
    """

    # ── Inventory (bag) panel ────────────────────────────────────────

    def _build_bag_panel(self) -> None:
        """Build the left-side inventory panel (hidden initially)."""
        a2d = self.app.aspect2d  # type: ignore[attr-defined]
        self._bag_panel = DirectFrame(
            frameColor=_sty.BG_COLOR,
            frameSize=(-1.35, -0.55, -0.70, 0.70),
            pos=(0, 0, 0), parent=a2d, sortOrder=_sty.PANEL_SORT_ORDER,
        )
        DirectLabel(
            text="Inventory [I]",
            text_fg=_sty.TITLE_COLOR, text_scale=0.045,
            text_align=TextNode.A_left,
            pos=(-1.30, 0, 0.62),
            frameColor=_sty.TRANSPARENT, parent=self._bag_panel,
        )
        DirectButton(
            text="X",
            text_scale=0.04, text_fg=_sty.ERROR_COLOR,
            frameSize=(-0.03, 0.03, -0.02, 0.035),
            frameColor=_sty.BUTTON_BG_DIM,
            pos=(-0.58, 0, 0.64),
            command=self._toggle_bag_panel,
            parent=self._bag_panel,
        )
        self._bag_scroll = DirectScrolledFrame(
            frameColor=_sty.TRANSPARENT,
            frameSize=(-1.35, -0.57, -0.68, 0.56),
            canvasSize=(-1.35, -0.60, -1.0, 0),
            scrollBarWidth=0.025,
            pos=(0, 0, 0), parent=self._bag_panel,
        )
        self._bag_scroll.horizontalScroll.hide()
        self._bag_panel.hide()

    def _toggle_bag_panel(self) -> None:
        """Show/hide the inventory panel."""
        if self._bag_panel is None:
            return
        self._bag_panel_visible = not self._bag_panel_visible
        if self._bag_panel_visible:
            self._refresh_bag_panel()
            self._bag_panel.show()
        else:
            self._bag_panel.hide()

    def _refresh_bag_panel(self) -> None:
        """Rebuild the item list inside the inventory panel."""
        if self._bag_scroll is None:
            return
        canvas = self._bag_scroll.getCanvas()
        for lbl in self._bag_item_labels:
            lbl.destroy()
        self._bag_item_labels.clear()

        ms = self.game_state.move_system  # type: ignore[attr-defined]
        if ms is None or not ms.held_materials:
            lbl = DirectLabel(
                text="  (empty)",
                text_fg=_sty.MUTED_COLOR, text_scale=0.038,
                text_align=TextNode.A_left,
                pos=(-1.30, 0, -0.05),
                frameColor=_sty.TRANSPARENT, parent=canvas,
            )
            self._bag_item_labels.append(lbl)
            self._bag_scroll["canvasSize"] = (-1.35, -0.60, -0.15, 0)
            return

        y = -0.05
        y_step = 0.055
        for vtype, count in sorted(ms.held_materials.items()):
            name = _VTYPE_NAMES.get(vtype, f"Type {vtype}")
            vc = VOXEL_COLORS.get(vtype, (0.7, 0.7, 0.7, 1.0))
            text_color = (
                min(1.0, vc[0] + 0.3),
                min(1.0, vc[1] + 0.3),
                min(1.0, vc[2] + 0.3),
                1.0,
            )
            lbl = DirectLabel(
                text=f"  {name}  x{count}",
                text_fg=text_color, text_scale=0.038,
                text_align=TextNode.A_left,
                pos=(-1.30, 0, y),
                frameColor=_sty.TRANSPARENT, parent=canvas,
            )
            self._bag_item_labels.append(lbl)
            y -= y_step

        total_h = len(ms.held_materials) * y_step + 0.1
        self._bag_scroll["canvasSize"] = (-1.35, -0.60, -total_h, 0)

    def _refresh_hand(self) -> None:
        """Update the bag button text and refresh inventory panel if visible."""
        ms = self.game_state.move_system  # type: ignore[attr-defined]
        if ms is None or not ms.held_materials:
            self.bag_btn["text"] = "Bag: 0"  # type: ignore[attr-defined]
        else:
            total = sum(ms.held_materials.values())
            self.bag_btn["text"] = f"Bag: {total}"  # type: ignore[attr-defined]
        if self._bag_panel_visible:
            self._refresh_bag_panel()
