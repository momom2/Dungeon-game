"""Categorized recipe palette — replaces the flat CraftingBookPanel.

Shows discovered recipes in category tabs with live 3-color cost
indicators (green = material held, yellow = mana-only, red = cannot
afford).  A detail strip at the bottom gives the full cost breakdown
for the focused recipe.

Features carried forward from CraftingBookPanel:
- Recipe pinning with floating overlay
- Ingredient highlighting on description click
- Keyboard toggle (B key)
- Discovery integration (undiscovered = "???")

Dependencies: core.event_bus, core.game_state, core.keybinding_registry,
    building.crafting_journal, building.crafting_book, building.craft_cost,
    building.move_system, dungeon_core.mana, ui.voxel_names, ui.style
Dependents: main (wiring), tests/ui/test_object_palette.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from direct.gui.DirectGui import (
    DirectFrame,
    DirectLabel,
    DirectButton,
    DirectScrolledFrame,
    DGG,
)
from panda3d.core import TextNode
from direct.showbase.ShowBase import ShowBase

from dungeon_builder.building.craft_cost import compute_craft_cost
from dungeon_builder.building.crafting_book import CraftingBook, CraftingRecipe
from dungeon_builder.ui.voxel_names import VTYPE_NAMES as _VTYPE_NAMES
from dungeon_builder.ui import style as _sty

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState
    from dungeon_builder.core.keybinding_registry import KeybindingRegistry
    from dungeon_builder.building.crafting_journal import CraftingJournal
    from dungeon_builder.building.move_system import MoveSystem
    from dungeon_builder.dungeon_core.mana import ManaSystem

logger = logging.getLogger("dungeon_builder.ui")

# ── Categories ────────────────────────────────────────────────────────────

CATEGORIES: list[tuple[str, str]] = [
    ("terrain", "Terrain"),
    ("crafting", "Craft"),
    ("barriers", "Barrier"),
    ("traps", "Traps"),
    ("enchanted", "Ench"),
    ("plumbing", "Plumb"),
    ("thermal", "Thermal"),
]

# ── Pure helper functions (headless-testable) ─────────────────────────────


def filter_recipes_by_category(
    recipes: list[CraftingRecipe],
    category: str,
    discovered: set[str],
) -> list[CraftingRecipe]:
    """Return recipes in *category* that have been discovered."""
    return [
        r for r in recipes
        if r.category == category and r.name in discovered
    ]


def compute_affordability(
    recipe: CraftingRecipe,
    held_materials: dict[int, int],
    mana_system: ManaSystem | None,
) -> str:
    """Classify affordability: ``'material'``, ``'mana_only'``, or ``'unaffordable'``."""
    cost = compute_craft_cost(
        recipe.ingredients, recipe.assembly_cost, held_materials,
    )
    if not cost.craftable:
        return "unaffordable"
    if cost.materials_consumed:
        # Player has at least one physical ingredient
        if cost.total == 0:
            return "material"
        if mana_system is not None and mana_system.can_spend(cost.total):
            return "material"
        return "unaffordable"
    if cost.total == 0:
        return "material"
    if mana_system is not None and mana_system.can_spend(cost.total):
        return "mana_only"
    return "unaffordable"


def _input_names(required_inputs: frozenset[int]) -> str:
    """Comma-separated material names for the recipe's inputs."""
    names = [_VTYPE_NAMES.get(v, f"Type {v}") for v in sorted(required_inputs)]
    return ", ".join(names)


_AFFORD_COLOR = {
    "material": _sty.COST_AFFORDABLE,
    "mana_only": _sty.COST_MANA_ONLY,
    "unaffordable": _sty.COST_UNAFFORDABLE,
}


# ── ObjectPalette ─────────────────────────────────────────────────────────


class ObjectPalette:
    """Categorized recipe palette with live cost indicators.

    Right-side panel with 7 category tabs, a scrollable recipe list,
    and a detail strip at the bottom showing cost breakdown.
    """

    def __init__(
        self,
        app: ShowBase,
        event_bus: EventBus,
        crafting_journal: CraftingJournal,
        move_system: MoveSystem,
        game_state: GameState | None = None,
        mana_system: ManaSystem | None = None,
        keybinding_registry: KeybindingRegistry | None = None,
    ) -> None:
        self.app = app
        self.event_bus = event_bus
        self.journal = crafting_journal
        self.move_system = move_system
        self.game_state = game_state
        self.mana_system = mana_system
        self._kb = keybinding_registry

        self._visible = False
        self._active_category: str = "terrain"
        self._selected_recipe: str | None = None
        self._pinned_recipe: str | None = None
        self._current_z: int = 0
        self._focused_recipe: str | None = None  # for detail strip

        # Build DirectGui elements (hidden initially)
        self._build_panel()
        self.panel.hide()

        # Floating pinned-recipe overlay
        self._build_pinned_overlay()
        self._pinned_frame.hide()

        # Keyboard toggle
        _key = self._kb.get("toggle_crafting_book") if self._kb else "b"
        app.accept(_key, self.toggle)

        # Event subscriptions
        event_bus.subscribe("toggle_crafting_book", self._on_toggle_event)
        event_bus.subscribe("recipe_discovered", self._on_recipe_discovered)
        event_bus.subscribe("material_picked_up", self._on_material_changed)
        event_bus.subscribe("material_dropped", self._on_material_changed)
        event_bus.subscribe("mana_changed", self._on_material_changed)
        event_bus.subscribe("craft_success", self._on_craft_success)
        event_bus.subscribe("craft_mode_entered", self._on_craft_mode_entered)
        event_bus.subscribe("craft_mode_exited", self._on_craft_mode_exited)
        event_bus.subscribe("z_level_changed", self._on_z_level_changed)

    # ── Panel construction ────────────────────────────────────────────

    def _build_panel(self) -> None:
        """Construct the DirectGui panel hierarchy."""
        a2d = self.app.aspect2d

        self.panel = DirectFrame(
            frameColor=_sty.BG_COLOR,
            frameSize=(0.55, 1.35, -0.92, 0.92),
            pos=(0, 0, 0),
            parent=a2d,
            sortOrder=_sty.PANEL_SORT_ORDER,
        )

        # Title
        self._title_label = DirectLabel(
            text="Palette [B]",
            text_fg=_sty.TITLE_COLOR,
            text_scale=0.05,
            text_align=TextNode.A_left,
            pos=(0.6, 0, 0.84),
            frameColor=_sty.TRANSPARENT,
            parent=self.panel,
        )

        # Close button
        self._close_btn = DirectButton(
            text="X",
            text_scale=0.045,
            text_fg=_sty.ERROR_COLOR,
            frameSize=(-0.035, 0.035, -0.025, 0.04),
            frameColor=_sty.BUTTON_BG_DIM,
            pos=(1.28, 0, 0.86),
            command=self.toggle,
            parent=self.panel,
        )

        # Discovered count
        self._count_label = DirectLabel(
            text="",
            text_fg=_sty.MUTED_COLOR,
            text_scale=0.035,
            text_align=TextNode.A_left,
            pos=(0.6, 0, 0.77),
            frameColor=_sty.TRANSPARENT,
            parent=self.panel,
        )

        # Category tabs
        self._tab_buttons: list[DirectButton] = []
        self._build_category_tabs()

        # Scrollable recipe list
        self._scroll_frame = DirectScrolledFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(0.55, 1.33, -0.60, 0.68),
            canvasSize=(0.55, 1.30, -2.5, 0),
            scrollBarWidth=0.03,
            pos=(0, 0, 0),
            parent=self.panel,
        )
        self._scroll_frame.horizontalScroll.hide()

        # Recipe entry widgets: list of (btn, desc_btn, recipe_name, pin_btn)
        self._recipe_widgets: list[
            tuple[DirectButton, DirectButton, str, DirectButton]
        ] = []

        # Detail strip at bottom
        self._detail_frame = DirectFrame(
            frameColor=(0.08, 0.08, 0.12, 0.8),
            frameSize=(0.56, 1.34, -0.91, -0.62),
            pos=(0, 0, 0),
            parent=self.panel,
        )
        self._detail_name = DirectLabel(
            text="",
            text_fg=_sty.TITLE_COLOR,
            text_scale=0.038,
            text_align=TextNode.A_left,
            pos=(0.58, 0, -0.66),
            frameColor=_sty.TRANSPARENT,
            parent=self.panel,
        )
        self._detail_desc = DirectLabel(
            text="",
            text_fg=_sty.MUTED_COLOR,
            text_scale=0.028,
            text_align=TextNode.A_left,
            pos=(0.58, 0, -0.72),
            frameColor=_sty.TRANSPARENT,
            parent=self.panel,
        )
        self._detail_cost = DirectLabel(
            text="",
            text_fg=_sty.TEXT_COLOR,
            text_scale=0.028,
            text_align=TextNode.A_left,
            pos=(0.58, 0, -0.78),
            frameColor=_sty.TRANSPARENT,
            parent=self.panel,
        )
        self._detail_total = DirectLabel(
            text="",
            text_fg=_sty.MANA_COLOR,
            text_scale=0.030,
            text_align=TextNode.A_left,
            pos=(0.58, 0, -0.84),
            frameColor=_sty.TRANSPARENT,
            parent=self.panel,
        )

        # Initial recipe list
        self._rebuild_recipe_list()

    def _build_category_tabs(self) -> None:
        """Create category tab buttons across the top."""
        tab_y = 0.71
        tab_width = 0.105
        x_start = 0.58
        for i, (cat_id, label) in enumerate(CATEGORIES):
            x = x_start + i * tab_width
            btn = DirectButton(
                text=label,
                text_scale=0.028,
                text_fg=_sty.TEXT_COLOR,
                text_align=TextNode.A_center,
                frameSize=(-0.05, 0.05, -0.018, 0.028),
                frameColor=_sty.PALETTE_TAB_BG,
                pos=(x, 0, tab_y),
                command=self._on_tab_click,
                extraArgs=[cat_id],
                parent=self.panel,
            )
            self._tab_buttons.append(btn)
        self._highlight_active_tab()

    def _highlight_active_tab(self) -> None:
        """Color the active tab gold, others default."""
        for i, (cat_id, _) in enumerate(CATEGORIES):
            btn = self._tab_buttons[i]
            if cat_id == self._active_category:
                btn["frameColor"] = _sty.PALETTE_TAB_ACTIVE
                btn["text_fg"] = _sty.HIGHLIGHT_COLOR
            else:
                btn["frameColor"] = _sty.PALETTE_TAB_BG
                btn["text_fg"] = _sty.TEXT_COLOR

    # ── Recipe list ────────────────────────────────────────────────────

    def _rebuild_recipe_list(self) -> None:
        """Clear and rebuild the recipe list for the active category."""
        # Destroy old widgets
        for btn, desc_btn, _, pin_btn in self._recipe_widgets:
            btn.destroy()
            desc_btn.destroy()
            pin_btn.destroy()
        self._recipe_widgets.clear()

        canvas = self._scroll_frame.getCanvas()
        crafting_book = self.journal._crafting_book
        discovered = self.journal.discovered_names

        # Get recipes in active category (discovered + undiscovered)
        cat_recipes = [
            r for r in crafting_book.recipes
            if r.category == self._active_category
        ]

        y_start = -0.04
        y_step = 0.10

        for i, recipe in enumerate(cat_recipes):
            y = y_start - i * y_step
            is_discovered = recipe.name in discovered
            display_name = recipe.name if is_discovered else "???"
            is_pinned = self._pinned_recipe == recipe.name

            # Affordability color
            if is_discovered:
                afford = compute_affordability(
                    recipe, self.move_system.held_materials, self.mana_system,
                )
                name_color = _AFFORD_COLOR[afford]
                if self._selected_recipe == recipe.name:
                    name_color = (1.0, 0.9, 0.3, 1)  # gold highlight
            else:
                name_color = (0.35, 0.35, 0.35, 1)

            if is_pinned and is_discovered:
                display_name = f"\1underline\1{display_name}\2"

            btn = DirectButton(
                text=display_name,
                text_scale=0.038,
                text_fg=name_color,
                text_align=TextNode.A_left,
                frameSize=(0.0, 0.65, -0.025, 0.045),
                frameColor=(
                    _sty.RECIPE_BG_ACTIVE
                    if self._selected_recipe == recipe.name
                    else _sty.RECIPE_BG_ENABLED
                    if is_discovered
                    else (0.1, 0.1, 0.1, 0.6)
                ),
                pos=(0.02, 0, y),
                parent=canvas,
                command=self._on_recipe_click,
                extraArgs=[recipe.name],
                state=DGG.NORMAL if is_discovered else DGG.DISABLED,
            )

            # Cost / requirement text
            if is_discovered:
                cost_text = self._cost_summary(recipe)
            else:
                cost_text = "[Craft this recipe to reveal]"
            desc_btn = DirectButton(
                text=cost_text,
                text_fg=_sty.DIM_COLOR if not is_discovered else _sty.MUTED_COLOR,
                text_scale=0.028,
                text_align=TextNode.A_left,
                frameSize=(0.0, 0.72, -0.018, 0.022),
                frameColor=_sty.TRANSPARENT,
                pos=(0.04, 0, y - 0.04),
                parent=canvas,
                command=self._on_ingredient_click,
                extraArgs=[recipe.name],
                state=DGG.NORMAL if is_discovered else DGG.DISABLED,
            )

            # Pin button
            pin_btn = DirectButton(
                text="*" if is_pinned else "o",
                text_scale=0.038,
                text_fg=(
                    (0.95, 0.80, 0.20, 1) if is_pinned
                    else _sty.DISABLED_COLOR
                ),
                text_align=TextNode.A_center,
                frameSize=(-0.025, 0.025, -0.02, 0.035),
                frameColor=(
                    (0.25, 0.22, 0.08, 0.8) if is_pinned
                    else (0.15, 0.15, 0.2, 0.6)
                ),
                pos=(0.70, 0, y + 0.01),
                parent=canvas,
                command=self._on_pin_toggle,
                extraArgs=[recipe.name],
                state=DGG.NORMAL if is_discovered else DGG.DISABLED,
            )

            self._recipe_widgets.append((btn, desc_btn, recipe.name, pin_btn))

        # Adjust canvas height
        total_h = len(cat_recipes) * y_step + 0.1
        self._scroll_frame["canvasSize"] = (0.0, 0.75, -total_h, 0)

        # Update discovered count
        self._count_label["text"] = (
            f"Discovered: {self.journal.discovered_count}"
            f" / {self.journal.total_recipes}"
        )

    def _cost_summary(self, recipe: CraftingRecipe) -> str:
        """Short cost string for the recipe list row."""
        cost = compute_craft_cost(
            recipe.ingredients, recipe.assembly_cost,
            self.move_system.held_materials,
        )
        parts: list[str] = []
        if cost.materials_consumed:
            names = [_VTYPE_NAMES.get(v, "?") for v in cost.materials_consumed]
            parts.append(" + ".join(names))
        if cost.total > 0:
            parts.append(f"{cost.total} mana")
        elif not parts:
            parts.append("Free")
        return " | ".join(parts)

    # ── Detail strip ──────────────────────────────────────────────────

    def _update_detail(self, recipe_name: str | None) -> None:
        """Populate the bottom detail strip for the given recipe."""
        if recipe_name is None:
            self._detail_name["text"] = ""
            self._detail_desc["text"] = ""
            self._detail_cost["text"] = ""
            self._detail_total["text"] = ""
            return

        recipe = self.journal._crafting_book.get_recipe_by_name(recipe_name)
        if recipe is None:
            return

        self._detail_name["text"] = recipe.name
        self._detail_desc["text"] = recipe.description

        cost = compute_craft_cost(
            recipe.ingredients, recipe.assembly_cost,
            self.move_system.held_materials,
        )

        # Material line
        mat_parts: list[str] = []
        for ing in recipe.ingredients:
            name = _VTYPE_NAMES.get(ing.vtype, f"Type {ing.vtype}")
            if ing.substitutable:
                mat_parts.append(f"{name} ({ing.mana_value} mana)")
            else:
                mat_parts.append(f"{name} (required)")
        self._detail_cost["text"] = (
            f"Assembly: {recipe.assembly_cost}   "
            + "  ".join(mat_parts)
        )

        # Total line
        if cost.materials_consumed:
            held = ", ".join(
                _VTYPE_NAMES.get(v, "?") for v in cost.materials_consumed
            )
            self._detail_total["text"] = (
                f"Total: {cost.total} mana (holding {held})"
            )
        elif cost.total > 0:
            self._detail_total["text"] = f"Total: {cost.total} mana (conjuring)"
        else:
            self._detail_total["text"] = "Total: Free"

    # ── Pinned overlay ────────────────────────────────────────────────

    def _build_pinned_overlay(self) -> None:
        """Build floating overlay for pinned recipe (shown when panel closed)."""
        a2d = self.app.aspect2d
        self._pinned_frame = DirectFrame(
            frameColor=(0.08, 0.08, 0.14, 0.88),
            frameSize=(0.0, 0.50, -0.07, 0.04),
            pos=(1.05, 0, -0.85),
            parent=a2d,
            sortOrder=55,
        )
        self._pinned_label = DirectButton(
            text="",
            text_fg=_sty.HIGHLIGHT_COLOR,
            text_scale=0.032,
            text_align=TextNode.A_left,
            frameSize=(0.0, 0.42, -0.065, 0.035),
            frameColor=_sty.TRANSPARENT,
            pos=(0.015, 0, 0.0),
            parent=self._pinned_frame,
            command=self._on_pinned_overlay_click,
        )
        self._pinned_unpin_btn = DirectButton(
            text="x",
            text_scale=0.028,
            text_fg=(0.7, 0.3, 0.3, 1),
            frameSize=(-0.018, 0.018, -0.015, 0.02),
            frameColor=(0.18, 0.12, 0.12, 0.7),
            pos=(0.46, 0, 0.015),
            parent=self._pinned_frame,
            command=self._on_pinned_unpin_click,
        )

    def _update_pinned_overlay(self) -> None:
        """Show/hide the floating pinned overlay."""
        if self._pinned_recipe and not self._visible:
            recipe = self.journal._crafting_book.get_recipe_by_name(
                self._pinned_recipe
            )
            if recipe is not None:
                req = _input_names(recipe.required_inputs)
                self._pinned_label["text"] = (
                    f"{self._pinned_recipe}\n  {req}"
                )
            else:
                self._pinned_label["text"] = self._pinned_recipe
            self._pinned_frame.show()
        else:
            self._pinned_frame.hide()

    # ── Click handlers ────────────────────────────────────────────────

    def _on_tab_click(self, category: str) -> None:
        """Switch active category tab."""
        if category == self._active_category:
            return
        self._active_category = category
        self._highlight_active_tab()
        self._rebuild_recipe_list()
        self._update_detail(None)

    def _on_recipe_click(self, recipe_name: str) -> None:
        """Enter craft mode for clicked recipe."""
        if recipe_name == "???":
            return
        self._focused_recipe = recipe_name
        self._update_detail(recipe_name)
        self.event_bus.publish(
            "craft_recipe_selected", recipe_name=recipe_name,
        )

    def _on_pin_toggle(self, recipe_name: str) -> None:
        """Toggle pin state for a recipe."""
        if recipe_name == "???":
            return
        if self._pinned_recipe == recipe_name:
            self._pinned_recipe = None
        else:
            self._pinned_recipe = recipe_name
        self._update_pinned_overlay()
        if self._visible:
            self._rebuild_recipe_list()

    def _on_ingredient_click(self, recipe_name: str) -> None:
        """Scan z-level for visible instances of the recipe's inputs."""
        if recipe_name == "???":
            return
        if self.game_state is None:
            return

        recipe = self.journal._crafting_book.get_recipe_by_name(recipe_name)
        if recipe is None:
            return

        grid = self.game_state.voxel_grid
        if grid is None:
            return

        z = self._current_z
        positions: set[tuple[int, int, int]] = set()
        for vtype in recipe.required_inputs:
            for x in range(grid.width):
                for y in range(grid.depth):
                    if (
                        grid.get(x, y, z) == vtype
                        and grid.is_visible(x, y, z)
                    ):
                        positions.add((x, y, z))

        if positions:
            self.event_bus.publish(
                "ingredient_highlight", positions=positions,
            )
        else:
            names = [
                _VTYPE_NAMES.get(v, "?") for v in recipe.required_inputs
            ]
            self.event_bus.publish(
                "error_message",
                text=f"You can't find any {'/'.join(names)} nearby",
            )

        # Also show detail for this recipe
        self._focused_recipe = recipe_name
        self._update_detail(recipe_name)

    def _on_pinned_overlay_click(self) -> None:
        """Clicking floating overlay enters craft mode."""
        if self._pinned_recipe:
            self.event_bus.publish(
                "craft_recipe_selected", recipe_name=self._pinned_recipe,
            )

    def _on_pinned_unpin_click(self) -> None:
        """Unpin the pinned recipe."""
        self._pinned_recipe = None
        self._update_pinned_overlay()
        if self._visible:
            self._rebuild_recipe_list()

    # ── Visibility ────────────────────────────────────────────────────

    def toggle(self) -> None:
        """Toggle panel visibility."""
        if self._visible:
            self.panel.hide()
            self._visible = False
            self._update_pinned_overlay()
        else:
            self._rebuild_recipe_list()
            self._update_detail(self._focused_recipe)
            self.panel.show()
            self._visible = True
            self._pinned_frame.hide()

    @property
    def is_visible(self) -> bool:
        """Whether the panel is currently shown."""
        return self._visible

    # ── Event handlers ────────────────────────────────────────────────

    def _on_toggle_event(self, **kwargs) -> None:
        self.toggle()

    def _on_recipe_discovered(self, **kwargs) -> None:
        if self._visible:
            self._rebuild_recipe_list()

    def _on_material_changed(self, **kwargs) -> None:
        if self._visible:
            self._rebuild_recipe_list()
            self._update_detail(self._focused_recipe)

    def _on_craft_success(self, **kwargs) -> None:
        if self._visible:
            self._rebuild_recipe_list()

    def _on_craft_mode_entered(self, recipe_name: str, **kwargs) -> None:
        self._selected_recipe = recipe_name
        self._focused_recipe = recipe_name
        if self._visible:
            self._rebuild_recipe_list()
            self._update_detail(recipe_name)

    def _on_craft_mode_exited(self, **kwargs) -> None:
        self._selected_recipe = None
        if self._visible:
            self._rebuild_recipe_list()

    def _on_z_level_changed(self, z: int, **kwargs) -> None:
        self._current_z = z
