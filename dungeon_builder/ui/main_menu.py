"""Main menu overlay: title screen, options, and submenu navigation.

Appears on startup and when the player presses Escape during gameplay.
The game pauses while the menu is open.  Options submenus allow runtime
modification of game constants via sliders.

Dependencies: config, core.event_bus, core.game_state,
    core.keybinding_registry, ui.menu_constants, ui.style
Dependents: main (wiring), tests/ui/test_main_menu.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from direct.gui.DirectGui import (
    DirectFrame,
    DirectLabel,
    DirectButton,
    DirectSlider,
    DirectScrolledFrame,
    DirectOptionMenu,
)
from panda3d.core import TextNode
from direct.showbase.ShowBase import ShowBase

import dungeon_builder.config as _cfg
from dungeon_builder.core.keybinding_registry import (
    KeybindingRegistry,
    ACTION_LABELS,
)
from dungeon_builder.ui.menu_constants import (
    DIFFICULTY_SETTINGS,
    VISIBILITY_SETTINGS,
    FOG_COLOR_SETTINGS,
    WATER_FLOW_MODELS,
    WATER_FLOW_MODEL_LABELS,
    WATER_MODEL_SETTINGS,
    capture_defaults,
    capture_fog_defaults,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState

from dungeon_builder.ui.style import (
    BG_COLOR as _BG_COLOR,
    TITLE_COLOR as _TITLE_COLOR,
    TEXT_COLOR as _TEXT_COLOR,
    MUTED_COLOR as _MUTED_COLOR,
    BUTTON_FG as _BUTTON_FG,
    BUTTON_BG as _BUTTON_BG,
    BUTTON_SIZE as _BUTTON_SIZE,
    MENU_SORT_ORDER as _SORT_ORDER,
)

logger = logging.getLogger("dungeon_builder.ui")

# Menu states
_STATES = (
    "main", "options", "game_constants",
    "difficulty", "visibility",
    "keybinding", "sound", "water_physics",
)


class MainMenu:
    """Full-screen menu overlay with title, options, and submenu navigation.

    Navigation state machine with a stack for back-navigation.
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

        self._visible: bool = True
        self._first_play: bool = True
        self._speed_before_menu: int = 0
        self._state: str = "main"
        self._nav_stack: list[str] = []

        # Keybinding capture state
        self._kb_capture_active: bool = False
        self._kb_capture_action: str | None = None
        self._kb_capture_button: DirectButton | None = None
        self._kb_buttons: dict[str, DirectButton] = {}  # action → key button
        self._kb_accept_name: str | None = None  # track active accept for cleanup

        # Snapshot defaults for reset buttons
        self._defaults_difficulty = capture_defaults(DIFFICULTY_SETTINGS)
        self._defaults_visibility = capture_defaults(VISIBILITY_SETTINGS)
        self._fog_defaults = capture_fog_defaults()

        # Slider widgets for refreshing on reset
        self._sliders: dict[str, tuple[DirectSlider, DirectLabel]] = {}
        self._fog_sliders: dict[int, tuple[DirectSlider, DirectLabel]] = {}

        # Build the overlay and all frames
        a2d = app.aspect2d
        self._overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.85),
            frameSize=(-2.5, 2.5, -1.5, 1.5),
            pos=(0, 0, 0),
            parent=a2d,
            sortOrder=_SORT_ORDER,
        )

        self._frames: dict[str, DirectFrame] = {}
        self._build_main_frame()
        self._build_options_frame()
        self._build_game_constants_frame()
        self._build_difficulty_frame()
        self._build_visibility_frame()
        self._build_keybinding_frame()
        self._build_sound_frame()
        self._build_water_physics_frame()
        self._build_help_frame()

        # Show main frame initially
        self._set_state("main")

        # Bind Escape to toggle
        app.accept("escape", self.toggle)

    # ── Navigation ───────────────────────────────────────────────────

    def show(self) -> None:
        """Show the menu overlay and pause the game."""
        if self._visible:
            return
        self._visible = True
        self.game_state.menu_open = True
        # Save current speed and pause
        if self.game_state.time_manager is not None:
            self._speed_before_menu = self.game_state.time_manager.speed
            if self._speed_before_menu != 0:
                self.game_state.time_manager.set_speed(0)
        self._overlay.show()
        self._set_state("main")

    def hide(self) -> None:
        """Hide the menu and resume the game."""
        if not self._visible:
            return
        self._visible = False
        self.game_state.menu_open = False
        self._overlay.hide()
        self._nav_stack.clear()
        # Resume game speed
        if self.game_state.time_manager is not None:
            if self._speed_before_menu > 0:
                self.game_state.time_manager.set_speed(self._speed_before_menu)
            elif not self._first_play:
                self.game_state.time_manager.set_speed(1)

    def toggle(self) -> None:
        """Toggle the menu on/off (bound to Escape)."""
        if self._visible:
            if self._first_play:
                return  # Can't dismiss before first Play
            self.hide()
        else:
            self.show()

    def _on_play(self) -> None:
        was_first = self._first_play
        self._first_play = False
        self._speed_before_menu = 1
        self.hide()
        # Warn about dev mode on first play
        if was_first and _cfg.DEV_MODE:
            self.event_bus.publish(
                "error_message",
                text="Dev mode active \u2014 toggle in Options",
                color=(1.0, 0.9, 0.3, 1),
            )

    def _toggle_dev_mode(self) -> None:
        """Toggle dev mode on/off and notify all subsystems."""
        _cfg.DEV_MODE = not _cfg.DEV_MODE
        self.game_state.dev_mode = _cfg.DEV_MODE

        # Update button text and color
        if _cfg.DEV_MODE:
            self._dev_mode_btn["text"] = "Dev Mode: ON"
            self._dev_mode_btn["frameColor"] = (0.15, 0.25, 0.15, 0.9)
            # Refill bag when re-enabling dev mode
            ms = self.game_state.move_system
            if ms is not None:
                from dungeon_builder.main import DungeonApp
                DungeonApp._fill_dev_bag(ms)
                self.event_bus.publish(
                    "material_picked_up", materials=dict(ms.held_materials),
                )
        else:
            self._dev_mode_btn["text"] = "Dev Mode: OFF"
            self._dev_mode_btn["frameColor"] = _BUTTON_BG

        self.event_bus.publish("dev_mode_changed")
        # Force territory recompute
        self.event_bus.publish("force_territory_recompute")

    def _toggle_depth_fade(self) -> None:
        """Toggle depth-fade on/off and re-apply layer transparency."""
        _cfg.LAYER_DEPTH_FADE = not _cfg.LAYER_DEPTH_FADE
        if _cfg.LAYER_DEPTH_FADE:
            self._depth_fade_btn["text"] = "Depth Fade: ON"
            self._depth_fade_btn["frameColor"] = (0.15, 0.25, 0.15, 0.9)
        else:
            self._depth_fade_btn["text"] = "Depth Fade: OFF"
            self._depth_fade_btn["frameColor"] = _BUTTON_BG
        self.event_bus.publish("config_changed", key="LAYER_DEPTH_FADE")

    def _on_quit(self) -> None:
        self.app.userExit()

    def _on_save(self) -> None:
        """Request the app to save the game via event bus."""
        self.event_bus.publish("save_game_requested")
        self._set_status_text("Game saved!", (0.6, 0.9, 0.6, 1))

    def _on_load(self) -> None:
        """Request the app to load the game via event bus."""
        self.event_bus.publish("load_game_requested")
        self._set_status_text("Game loaded!", (0.6, 0.9, 0.6, 1))

    def _set_status_text(self, text: str, color: tuple = (0.6, 0.9, 0.6, 1)) -> None:
        """Show temporary status text on the main menu frame."""
        if hasattr(self, "_save_status_label"):
            self._save_status_label["text"] = text
            self._save_status_label["text_fg"] = color

    def _navigate_to(self, state: str) -> None:
        self._nav_stack.append(self._state)
        self._set_state(state)

    def _navigate_back(self) -> None:
        if self._nav_stack:
            prev = self._nav_stack.pop()
            self._set_state(prev)
        else:
            self.hide()

    def _set_state(self, state: str) -> None:
        for frame in self._frames.values():
            frame.hide()
        self._frames[state].show()
        self._state = state

    # ── Frame builders ───────────────────────────────────────────────

    def _make_frame(self, name: str) -> DirectFrame:
        """Create a submenu content frame inside the overlay."""
        frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-1.0, 1.0, -0.9, 0.9),
            pos=(0, 0, 0),
            parent=self._overlay,
        )
        frame.hide()
        self._frames[name] = frame
        return frame

    def _make_title(self, parent: DirectFrame, text: str) -> DirectLabel:
        return DirectLabel(
            text=text,
            text_fg=_TITLE_COLOR,
            text_scale=0.1,
            text_align=TextNode.A_center,
            pos=(0, 0, 0.7),
            frameColor=(0, 0, 0, 0),
            parent=parent,
        )

    def _make_button(
        self, parent: DirectFrame, text: str, y: float, command,
    ) -> DirectButton:
        return DirectButton(
            text=text,
            text_fg=_BUTTON_FG,
            text_scale=0.06,
            frameColor=_BUTTON_BG,
            frameSize=_BUTTON_SIZE,
            relief=1,
            pos=(0, 0, y),
            command=command,
            parent=parent,
        )

    def _make_back_button(self, parent: DirectFrame, y: float = -0.8) -> DirectButton:
        return self._make_button(parent, "Back", y, self._navigate_back)

    # ── Main menu ────────────────────────────────────────────────────

    def _build_main_frame(self) -> None:
        f = self._make_frame("main")
        self._make_title(f, "DUNGEON BUILDER")
        self._make_button(f, "Play", 0.40, self._on_play)
        self._make_button(f, "Save", 0.25, self._on_save)
        self._make_button(f, "Load", 0.10, self._on_load)
        self._make_button(f, "Options", -0.05, lambda: self._navigate_to("options"))
        self._make_button(f, "Help", -0.20, lambda: self._navigate_to("help"))
        self._make_button(f, "Quit", -0.35, self._on_quit)

        # Status label for save/load feedback
        self._save_status_label = DirectLabel(
            text="",
            text_fg=(0.6, 0.9, 0.6, 1),
            text_scale=0.04,
            text_align=TextNode.A_center,
            pos=(0, 0, -0.52),
            frameColor=(0, 0, 0, 0),
            parent=f,
        )

    # ── Options menu ─────────────────────────────────────────────────

    def _build_options_frame(self) -> None:
        f = self._make_frame("options")
        self._make_title(f, "OPTIONS")
        self._make_button(f, "Keybinding", 0.35, lambda: self._navigate_to("keybinding"))
        self._make_button(f, "Game Constants", 0.20, lambda: self._navigate_to("game_constants"))
        self._make_button(f, "Sound", 0.05, lambda: self._navigate_to("sound"))

        # Dev mode toggle
        dev_text = "Dev Mode: ON" if _cfg.DEV_MODE else "Dev Mode: OFF"
        dev_color = (0.15, 0.25, 0.15, 0.9) if _cfg.DEV_MODE else _BUTTON_BG
        self._dev_mode_btn = DirectButton(
            text=dev_text,
            text_fg=_BUTTON_FG,
            text_scale=0.06,
            frameColor=dev_color,
            frameSize=_BUTTON_SIZE,
            relief=1,
            pos=(0, 0, -0.10),
            command=self._toggle_dev_mode,
            parent=f,
        )
        self._make_back_button(f)

    # ── Game constants hub ───────────────────────────────────────────

    def _build_game_constants_frame(self) -> None:
        f = self._make_frame("game_constants")
        self._make_title(f, "GAME CONSTANTS")
        self._make_button(f, "Difficulty", 0.2, lambda: self._navigate_to("difficulty"))
        self._make_button(f, "Visibility", 0.05, lambda: self._navigate_to("visibility"))
        self._make_button(f, "Water Physics", -0.10, lambda: self._navigate_to("water_physics"))
        self._make_back_button(f)

    # ── Difficulty sliders ───────────────────────────────────────────

    def _build_difficulty_frame(self) -> None:
        f = self._make_frame("difficulty")
        self._make_title(f, "DIFFICULTY")
        y_start = 0.5
        for i, setting in enumerate(DIFFICULTY_SETTINGS):
            slider, label = self._build_slider_row(f, i, setting, y_start)
            self._sliders[setting["attr"]] = (slider, label)
        btn_y = y_start - len(DIFFICULTY_SETTINGS) * 0.09 - 0.05
        self._make_button(
            f, "Reset Defaults", btn_y,
            lambda: self._reset_defaults(
                DIFFICULTY_SETTINGS, self._defaults_difficulty,
            ),
        )
        self._make_back_button(f, min(btn_y - 0.15, -0.8))

    # ── Visibility sliders ───────────────────────────────────────────

    def _build_visibility_frame(self) -> None:
        f = self._make_frame("visibility")
        self._make_title(f, "VISIBILITY")
        y_start = 0.5
        idx = 0
        for setting in VISIBILITY_SETTINGS:
            slider, label = self._build_slider_row(f, idx, setting, y_start)
            self._sliders[setting["attr"]] = (slider, label)
            idx += 1
        # Fog colour sliders
        for fog_setting in FOG_COLOR_SETTINGS:
            slider, label = self._build_fog_slider(f, idx, fog_setting, y_start)
            self._fog_sliders[fog_setting["index"]] = (slider, label)
            idx += 1

        # Depth-fade toggle button
        toggle_y = y_start - idx * 0.09 - 0.05
        fade_text = "Depth Fade: ON" if _cfg.LAYER_DEPTH_FADE else "Depth Fade: OFF"
        fade_color = (0.15, 0.25, 0.15, 0.9) if _cfg.LAYER_DEPTH_FADE else _BUTTON_BG
        self._depth_fade_btn = DirectButton(
            text=fade_text,
            text_fg=_BUTTON_FG,
            text_scale=0.06,
            frameColor=fade_color,
            frameSize=_BUTTON_SIZE,
            relief=1,
            pos=(0, 0, toggle_y),
            command=self._toggle_depth_fade,
            parent=f,
        )

        btn_y = toggle_y - 0.12
        self._make_button(
            f, "Reset Defaults", btn_y,
            lambda: self._reset_visibility_defaults(),
        )
        self._make_back_button(f, min(btn_y - 0.15, -0.8))

    # ── Stub menus ───────────────────────────────────────────────────

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

    def _build_sound_frame(self) -> None:
        f = self._make_frame("sound")
        self._make_title(f, "SOUND")
        DirectLabel(
            text="Coming soon",
            text_fg=_MUTED_COLOR,
            text_scale=0.06,
            text_align=TextNode.A_center,
            pos=(0, 0, 0.1),
            frameColor=(0, 0, 0, 0),
            parent=f,
        )
        self._make_back_button(f)

    # ── Water physics model selector ──────────────────────────────

    def _build_water_physics_frame(self) -> None:
        f = self._make_frame("water_physics")
        self._make_title(f, "WATER PHYSICS")

        # Model dropdown
        DirectLabel(
            text="Flow Model:",
            text_fg=_TEXT_COLOR,
            text_scale=0.05,
            text_align=TextNode.A_left,
            pos=(-0.55, 0, 0.5),
            frameColor=(0, 0, 0, 0),
            parent=f,
        )

        labels = [WATER_FLOW_MODEL_LABELS[m] for m in WATER_FLOW_MODELS]
        current_model = _cfg.WATER_FLOW_MODEL
        try:
            initial_idx = WATER_FLOW_MODELS.index(current_model)
        except ValueError:
            initial_idx = 0

        self._water_model_menu = DirectOptionMenu(
            text="Model",
            scale=0.05,
            items=labels,
            initialitem=initial_idx,
            highlightColor=(0.65, 0.65, 0.65, 1),
            command=self._on_water_model_change,
            pos=(0.15, 0, 0.505),
            parent=f,
        )

        # Container for dynamic model-specific sliders
        self._water_slider_widgets: list = []
        self._water_slider_parent = f
        self._rebuild_water_sliders(current_model)

        self._make_back_button(f)

    def _on_water_model_change(self, label: str) -> None:
        """Handle water model dropdown change."""
        for model_key, model_label in WATER_FLOW_MODEL_LABELS.items():
            if model_label == label:
                _cfg.WATER_FLOW_MODEL = model_key
                self.event_bus.publish("config_changed", key="WATER_FLOW_MODEL", value=model_key)
                self._rebuild_water_sliders(model_key)
                return

    def _rebuild_water_sliders(self, model_key: str) -> None:
        """Destroy existing model sliders and build new ones for the selected model."""
        # Destroy old slider widgets
        for widget in self._water_slider_widgets:
            widget.destroy()
        self._water_slider_widgets.clear()

        settings = WATER_MODEL_SETTINGS.get(model_key, [])
        parent = self._water_slider_parent
        y_start = 0.35  # Below the dropdown

        for i, setting in enumerate(settings):
            y = y_start - i * 0.09
            attr = setting["attr"]
            current_val = getattr(_cfg, attr)
            fmt = ".2f" if setting["type"] is float else "d"

            # Label
            lbl = DirectLabel(
                text=setting["label"],
                text_fg=_TEXT_COLOR,
                text_scale=0.04,
                text_align=TextNode.A_left,
                pos=(-0.55, 0, y),
                frameColor=(0, 0, 0, 0),
                parent=parent,
            )
            self._water_slider_widgets.append(lbl)

            # Slider
            slider = DirectSlider(
                range=(setting["min"], setting["max"]),
                value=current_val,
                pageSize=setting["step"],
                scale=0.35,
                pos=(0.15, 0, y + 0.015),
                parent=parent,
            )
            self._water_slider_widgets.append(slider)

            # Value readout
            value_label = DirectLabel(
                text=f"{current_val:{fmt}}",
                text_fg=_TITLE_COLOR,
                text_scale=0.04,
                text_align=TextNode.A_right,
                pos=(0.65, 0, y),
                frameColor=(0, 0, 0, 0),
                parent=parent,
            )
            self._water_slider_widgets.append(value_label)

            # Also track in main slider dict for potential resets
            self._sliders[attr] = (slider, value_label)

            # Closure for callback
            def on_change(s=slider, vl=value_label, st=setting, f=fmt):
                raw = s["value"]
                step = st["step"]
                val = round(raw / step) * step
                val = st["type"](val)
                val = max(st["min"], min(st["max"], val))
                setattr(_cfg, st["attr"], val)
                vl["text"] = f"{val:{f}}"
                self.event_bus.publish("config_changed", key=st["attr"], value=val)

            slider["command"] = on_change

    # ── Help page ──────────────────────────────────────────────────

    def _build_help_frame(self) -> None:
        f = self._make_frame("help")
        self._make_title(f, "HELP")

        help_text = (
            "CONTROLS\n"
            "\n"
            "  Left-click       Dig block / pick up loose material\n"
            "  Right-click      Place material from bag\n"
            "  T                Scroll up (toward surface)\n"
            "  Y                Scroll down (deeper)\n"
            "  X                Toggle dig / move mode\n"
            "  B                Open crafting book\n"
            "  Escape           Open menu\n"
            "\n"
            "DRAG SELECT\n"
            "\n"
            "  Click and drag to select an area for digging.\n"
            "  Hold Shift during drag to extend vertically.\n"
            "\n"
            "GETTING STARTED\n"
            "\n"
            "  Dig rooms around your core to expand territory.\n"
            "  Pick up materials and craft them via the\n"
            "  crafting book (B).  Place traps, build walls,\n"
            "  and prepare your defenses.\n"
            "\n"
            "  Intruders will come from the surface to attack\n"
            "  your core.  Don't let them destroy it!"
        )

        DirectLabel(
            text=help_text,
            text_fg=(0.85, 0.85, 0.9, 1),
            text_scale=0.042,
            text_align=TextNode.A_left,
            pos=(-0.55, 0, 0.45),
            frameColor=(0, 0, 0, 0),
            parent=f,
        )
        self._make_back_button(f)

    # ── Slider helpers ───────────────────────────────────────────────

    def _build_slider_row(
        self,
        parent: DirectFrame,
        index: int,
        setting: dict,
        y_start: float,
    ) -> tuple[DirectSlider, DirectLabel]:
        """Build one slider row: label + slider + value readout."""
        y = y_start - index * 0.09
        attr = setting["attr"]
        current_val = getattr(_cfg, attr)
        fmt = ".2f" if setting["type"] is float else "d"

        # Label
        DirectLabel(
            text=setting["label"],
            text_fg=_TEXT_COLOR,
            text_scale=0.04,
            text_align=TextNode.A_left,
            pos=(-0.55, 0, y),
            frameColor=(0, 0, 0, 0),
            parent=parent,
        )

        # Slider
        slider = DirectSlider(
            range=(setting["min"], setting["max"]),
            value=current_val,
            pageSize=setting["step"],
            scale=0.35,
            pos=(0.15, 0, y + 0.015),
            parent=parent,
        )

        # Value readout
        value_label = DirectLabel(
            text=f"{current_val:{fmt}}",
            text_fg=_TITLE_COLOR,
            text_scale=0.04,
            text_align=TextNode.A_right,
            pos=(0.65, 0, y),
            frameColor=(0, 0, 0, 0),
            parent=parent,
        )

        # Closure for callback
        def on_change(s=slider, vl=value_label, st=setting, f=fmt):
            raw = s["value"]
            step = st["step"]
            val = round(raw / step) * step
            val = st["type"](val)
            # Clamp
            val = max(st["min"], min(st["max"], val))
            setattr(_cfg, st["attr"], val)
            vl["text"] = f"{val:{f}}"
            self.event_bus.publish("config_changed", key=st["attr"], value=val)

        slider["command"] = on_change
        return slider, value_label

    def _build_fog_slider(
        self,
        parent: DirectFrame,
        index: int,
        setting: dict,
        y_start: float,
    ) -> tuple[DirectSlider, DirectLabel]:
        """Build a fog colour component slider."""
        y = y_start - index * 0.09
        fog_idx = setting["index"]
        current_val = _cfg.FOG_COLOR[fog_idx]

        DirectLabel(
            text=setting["label"],
            text_fg=_TEXT_COLOR,
            text_scale=0.04,
            text_align=TextNode.A_left,
            pos=(-0.55, 0, y),
            frameColor=(0, 0, 0, 0),
            parent=parent,
        )

        slider = DirectSlider(
            range=(setting["min"], setting["max"]),
            value=current_val,
            pageSize=setting["step"],
            scale=0.35,
            pos=(0.15, 0, y + 0.015),
            parent=parent,
        )

        value_label = DirectLabel(
            text=f"{current_val:.2f}",
            text_fg=_TITLE_COLOR,
            text_scale=0.04,
            text_align=TextNode.A_right,
            pos=(0.65, 0, y),
            frameColor=(0, 0, 0, 0),
            parent=parent,
        )

        def on_fog_change(s=slider, vl=value_label, fi=fog_idx, st=setting):
            raw = s["value"]
            step = st["step"]
            val = round(raw / step) * step
            val = max(st["min"], min(st["max"], val))
            fog = list(_cfg.FOG_COLOR)
            fog[fi] = val
            _cfg.FOG_COLOR = tuple(fog)
            vl["text"] = f"{val:.2f}"
            self.event_bus.publish("config_changed", key="FOG_COLOR", value=_cfg.FOG_COLOR)

        slider["command"] = on_fog_change
        return slider, value_label

    # ── Reset defaults ───────────────────────────────────────────────

    def _reset_defaults(
        self,
        settings: list[dict],
        defaults: dict[str, object],
    ) -> None:
        """Restore config values and refresh slider positions."""
        for setting in settings:
            attr = setting["attr"]
            default_val = defaults[attr]
            setattr(_cfg, attr, default_val)
            # Refresh slider + label
            if attr in self._sliders:
                slider, label = self._sliders[attr]
                slider["value"] = default_val
                fmt = ".2f" if setting["type"] is float else "d"
                label["text"] = f"{default_val:{fmt}}"
        self.event_bus.publish("config_changed", key="all_difficulty")

    def _reset_visibility_defaults(self) -> None:
        """Reset visibility settings, fog colour, and depth-fade toggle."""
        self._reset_defaults(
            VISIBILITY_SETTINGS, self._defaults_visibility,
        )
        # Reset fog
        _cfg.FOG_COLOR = self._fog_defaults
        for fog_setting in FOG_COLOR_SETTINGS:
            fi = fog_setting["index"]
            val = self._fog_defaults[fi]
            if fi in self._fog_sliders:
                slider, label = self._fog_sliders[fi]
                slider["value"] = val
                label["text"] = f"{val:.2f}"
        # Reset depth-fade to default (True)
        _cfg.LAYER_DEPTH_FADE = True
        if hasattr(self, "_depth_fade_btn"):
            self._depth_fade_btn["text"] = "Depth Fade: ON"
            self._depth_fade_btn["frameColor"] = (0.15, 0.25, 0.15, 0.9)
        self.event_bus.publish("config_changed", key="all_visibility")
