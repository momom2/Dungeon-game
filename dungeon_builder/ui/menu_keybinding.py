"""Keybinding submenu mixin for the main menu.

Provides the scrollable keybinding editor — rebind keys, reset individual
actions, or reset all to defaults.  Mixed into MainMenu so that the
keybinding frame is built and managed alongside the other submenus.

Dependencies: config, core.keybinding_registry, ui.style
Dependents: ui.main_menu (mixin consumer)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from direct.gui.DirectGui import (
    DirectButton,
    DirectLabel,
    DirectScrolledFrame,
)
from panda3d.core import TextNode

from dungeon_builder.core.keybinding_registry import (
    KeybindingRegistry,
    ACTION_LABELS,
)
from dungeon_builder.ui.style import (
    TITLE_COLOR as _TITLE_COLOR,
    TEXT_COLOR as _TEXT_COLOR,
    MUTED_COLOR as _MUTED_COLOR,
    BUTTON_FG as _BUTTON_FG,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("dungeon_builder.ui")


class KeybindingMixin:
    """Mixin that adds keybinding editing to MainMenu.

    Expects the host class to provide:
    - ``self.app``  (ShowBase)
    - ``self.game_state``  (GameState)
    - ``self._kb_capture_active``, ``self._kb_capture_action``,
      ``self._kb_capture_button``, ``self._kb_buttons``,
      ``self._kb_accept_name``  (initialised in ``__init__``)
    - ``self._make_frame(name)``
    - ``self._make_title(parent, text)``
    - ``self._make_button(parent, text, y, command)``
    - ``self._make_back_button(parent, y)``
    """

    # ── Keybinding frame builder ─────────────────────────────────────

    def _build_keybinding_frame(self) -> None:
        f = self._make_frame("keybinding")
        self._make_title(f, "KEYBINDING")

        kb = self._get_kb_registry()
        if kb is None:
            # No registry available — show placeholder
            DirectLabel(
                text="No keybinding registry",
                text_fg=_MUTED_COLOR, text_scale=0.06,
                text_align=TextNode.A_center, pos=(0, 0, 0.1),
                frameColor=(0, 0, 0, 0), parent=f,
            )
            self._make_back_button(f)
            return

        # Scrollable list of keybindings
        scroll = DirectScrolledFrame(
            canvasSize=(-0.7, 0.7, -len(kb.all_actions) * 0.07 - 0.1, 0.0),
            frameSize=(-0.75, 0.75, -0.65, 0.55),
            frameColor=(0.08, 0.08, 0.12, 0.6),
            pos=(0, 0, 0),
            parent=f,
            scrollBarWidth=0.03,
        )
        canvas = scroll.getCanvas()

        for idx, action in enumerate(kb.all_actions):
            y = -idx * 0.07 - 0.02
            label_text = ACTION_LABELS.get(action, action)
            key_text = kb.get(action)

            # Action label (left)
            DirectLabel(
                text=label_text, text_fg=_TEXT_COLOR, text_scale=0.035,
                text_align=TextNode.A_left, pos=(-0.65, 0, y),
                frameColor=(0, 0, 0, 0), parent=canvas,
            )

            # Key button (right) — click to rebind
            key_btn = DirectButton(
                text=f"[{key_text}]", text_fg=_TITLE_COLOR, text_scale=0.035,
                frameColor=(0.15, 0.15, 0.2, 0.8),
                frameSize=(-0.15, 0.15, -0.025, 0.035),
                relief=1, pos=(0.35, 0, y),
                command=self._start_key_capture, extraArgs=[action],
                parent=canvas,
            )
            self._kb_buttons[action] = key_btn

            # Reset single action
            DirectButton(
                text="X", text_fg=(0.8, 0.3, 0.3, 1), text_scale=0.03,
                frameColor=(0.15, 0.15, 0.2, 0.6),
                frameSize=(-0.025, 0.025, -0.02, 0.03),
                relief=1, pos=(0.55, 0, y),
                command=self._reset_single_keybinding, extraArgs=[action],
                parent=canvas,
            )

        # Reset All Defaults button
        self._make_button(f, "Reset All Keybindings", -0.72, self._reset_all_keybindings)
        self._make_back_button(f, -0.85)

    # ── Keybinding helpers ───────────────────────────────────────────

    def _get_kb_registry(self) -> KeybindingRegistry | None:
        """Return the keybinding registry from game_state, or None."""
        return getattr(self.game_state, "keybinding_registry", None)

    def _start_key_capture(self, action: str) -> None:
        """Enter key capture mode for the given action."""
        if self._kb_capture_active:
            self._cancel_key_capture()

        self._kb_capture_active = True
        self._kb_capture_action = action
        btn = self._kb_buttons.get(action)
        self._kb_capture_button = btn
        if btn:
            btn["text"] = "[Press a key...]"
            btn["text_fg"] = (1.0, 0.9, 0.3, 1)

        # Accept any keystroke via Panda3D's keystroke event
        self._kb_accept_name = "keystroke"
        self.app.accept(self._kb_accept_name, self._on_key_captured)

    def _on_key_captured(self, keyname: str) -> None:
        """Handle a captured key press during rebinding."""
        if not self._kb_capture_active or self._kb_capture_action is None:
            return

        # Ignore empty or modifier-only keys
        if not keyname or keyname in ("shift", "control", "alt", "meta"):
            return

        action = self._kb_capture_action
        kb = self._get_kb_registry()
        if kb is None:
            self._cancel_key_capture()
            return

        # Check for conflicts
        conflicts = kb.get_conflicts(keyname, exclude_action=action)
        if conflicts:
            # Auto-swap with first conflict
            kb.swap(action, keyname)
            # Update the swapped button text too
            for conflict_action in conflicts:
                if conflict_action in self._kb_buttons:
                    new_key = kb.get(conflict_action)
                    self._kb_buttons[conflict_action]["text"] = f"[{new_key}]"
                    self._kb_buttons[conflict_action]["text_fg"] = _TITLE_COLOR
        else:
            kb.set(action, keyname)

        # Update button
        btn = self._kb_buttons.get(action)
        if btn:
            btn["text"] = f"[{keyname}]"
            btn["text_fg"] = _TITLE_COLOR

        self._cancel_key_capture()
        self._save_keybindings()

    def _cancel_key_capture(self) -> None:
        """Exit key capture mode without changing anything."""
        if self._kb_accept_name:
            self.app.ignore(self._kb_accept_name)
            self._kb_accept_name = None

        if self._kb_capture_button and self._kb_capture_action:
            kb = self._get_kb_registry()
            if kb:
                current = kb.get(self._kb_capture_action)
                self._kb_capture_button["text"] = f"[{current}]"
                self._kb_capture_button["text_fg"] = _TITLE_COLOR

        self._kb_capture_active = False
        self._kb_capture_action = None
        self._kb_capture_button = None

    def _reset_single_keybinding(self, action: str) -> None:
        """Reset a single keybinding to its default."""
        kb = self._get_kb_registry()
        if kb is None:
            return
        kb.reset_action(action)
        if action in self._kb_buttons:
            self._kb_buttons[action]["text"] = f"[{kb.get(action)}]"
        self._save_keybindings()

    def _reset_all_keybindings(self) -> None:
        """Reset all keybindings to defaults."""
        kb = self._get_kb_registry()
        if kb is None:
            return
        kb.reset_defaults()
        for action, btn in self._kb_buttons.items():
            btn["text"] = f"[{kb.get(action)}]"
        self._save_keybindings()

    def _save_keybindings(self) -> None:
        """Persist keybindings to disk."""
        kb = self._get_kb_registry()
        if kb is None:
            return
        from pathlib import Path
        path = Path.home() / ".dungeon_builder" / "keybindings.json"
        try:
            kb.save(path)
        except OSError as exc:
            logger.warning("Failed to save keybindings: %s", exc)
