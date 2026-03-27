"""Main menu overlay: title screen, options, and submenu navigation.

Appears on startup and when the player presses Escape during gameplay.
The game pauses while the menu is open.  Options submenus allow runtime
modification of game constants via sliders.

Dependencies: config, core.event_bus, core.game_state,
    core.keybinding_registry, ui.menu_constants, ui.menu_keybinding,
    ui.menu_settings, ui.style
Dependents: main (wiring), tests/ui/test_main_menu.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from direct.gui.DirectGui import (
    DirectFrame,
    DirectLabel,
    DirectButton,
)
from panda3d.core import TextNode
from direct.showbase.ShowBase import ShowBase

import dungeon_builder.config as _cfg
from dungeon_builder.ui.menu_constants import (
    DIFFICULTY_SETTINGS,
    VISIBILITY_SETTINGS,
    capture_defaults,
    capture_fog_defaults,
)
from dungeon_builder.ui.menu_keybinding import KeybindingMixin
from dungeon_builder.ui.menu_settings import SettingsMixin

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState

from dungeon_builder.ui.style import (
    TITLE_COLOR as _TITLE_COLOR,
    TEXT_COLOR as _TEXT_COLOR,
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


class MainMenu(KeybindingMixin, SettingsMixin):
    """Full-screen menu overlay with title, options, and submenu navigation.

    Navigation state machine with a stack for back-navigation.
    Keybinding editing is provided by ``KeybindingMixin``; settings
    panels (difficulty, visibility, sound, water, help) are provided
    by ``SettingsMixin``.
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

        # Keybinding capture state (used by KeybindingMixin)
        self._kb_capture_active: bool = False
        self._kb_capture_action: str | None = None
        self._kb_capture_button: DirectButton | None = None
        self._kb_buttons: dict[str, DirectButton] = {}  # action -> key button
        self._kb_accept_name: str | None = None  # track active accept for cleanup

        # Snapshot defaults for reset buttons (used by SettingsMixin)
        self._defaults_difficulty = capture_defaults(DIFFICULTY_SETTINGS)
        self._defaults_visibility = capture_defaults(VISIBILITY_SETTINGS)
        self._fog_defaults = capture_fog_defaults()

        # Slider widgets for refreshing on reset (used by SettingsMixin)
        self._sliders: dict[str, tuple] = {}
        self._fog_sliders: dict[int, tuple] = {}

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

    # ── Main menu frame ──────────────────────────────────────────────

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
