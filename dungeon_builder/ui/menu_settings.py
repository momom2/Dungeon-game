"""Settings submenu mixins for the main menu.

Provides the game-constants, difficulty, visibility, sound, water-physics,
and help frame builders, plus the slider-row factory and reset helpers.
Mixed into MainMenu so that all settings panels are built alongside
the other submenus.

Dependencies: config, core.event_bus, ui.menu_constants, ui.style
Dependents: ui.main_menu (mixin consumer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from direct.gui.DirectGui import (
    DirectButton,
    DirectFrame,
    DirectLabel,
    DirectOptionMenu,
    DirectSlider,
)
from panda3d.core import TextNode

import dungeon_builder.config as _cfg
from dungeon_builder.ui.menu_constants import (
    DIFFICULTY_SETTINGS,
    VISIBILITY_SETTINGS,
    FOG_COLOR_SETTINGS,
    WATER_FLOW_MODELS,
    WATER_FLOW_MODEL_LABELS,
    WATER_MODEL_SETTINGS,
)
from dungeon_builder.ui.style import (
    TITLE_COLOR as _TITLE_COLOR,
    TEXT_COLOR as _TEXT_COLOR,
    MUTED_COLOR as _MUTED_COLOR,
    BUTTON_FG as _BUTTON_FG,
    BUTTON_BG as _BUTTON_BG,
    BUTTON_SIZE as _BUTTON_SIZE,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus


class SettingsMixin:
    """Mixin that adds settings submenus to MainMenu.

    Expects the host class to provide:
    - ``self.event_bus``  (EventBus)
    - ``self._defaults_difficulty``, ``self._defaults_visibility``,
      ``self._fog_defaults``  (initialised in ``__init__``)
    - ``self._sliders``, ``self._fog_sliders``  (initialised in ``__init__``)
    - ``self._make_frame(name)``
    - ``self._make_title(parent, text)``
    - ``self._make_button(parent, text, y, command)``
    - ``self._make_back_button(parent, y)``
    - ``self._navigate_to(state)``
    """

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

    # ── Sound (stub) ─────────────────────────────────────────────────

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

    # ── Water physics model selector ─────────────────────────────────

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

    # ── Help page ────────────────────────────────────────────────────

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
