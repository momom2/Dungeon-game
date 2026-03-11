"""Crafting system: highlight-mode state machine for recipe placement.

Flow:
1. Player clicks a recipe in the panel -> "craft_recipe_selected" event
2. System scans for valid positions and highlights them
3. Player hovers voxels -> system evaluates validity, publishes hover events
4. Player clicks a highlighted voxel -> "craft_at_position" event
5. System executes the recipe, consumes material, re-scans highlights
6. Player cancels (ESC/right-click) or runs out of material -> exit craft mode

Dependencies: building.crafting_book, building.craft_cost, core.event_bus,
    core.game_state, world.voxel_grid, building.move_system, dungeon_core.mana
Dependents: main (wiring), tests/building/test_crafting.py,
    tests/building/test_block_state.py, tests/building/test_metal_type_system.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.building.craft_cost import CraftCost, compute_craft_cost
from dungeon_builder.building.crafting_book import CraftingBook, CraftingRecipe

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState
    from dungeon_builder.world.voxel_grid import VoxelGrid
    from dungeon_builder.building.move_system import MoveSystem
    from dungeon_builder.dungeon_core.mana import ManaSystem

logger = logging.getLogger("dungeon_builder.building")


class CraftingSystem:
    """Manages recipe selection, position highlighting, and craft execution.

    Replaces the old auto-craft-on-drop flow with an explicit
    panel -> highlight -> click workflow.  Provides hover feedback,
    ghost preview data, remaining-material counts, and placement flash.

    Crafting uses a mana-or-materials dual cost model:

    - Each recipe has an *assembly cost* (irreducible mana) and a list
      of ingredients with individual *mana values*.
    - Holding a matching material offsets that ingredient's mana cost.
    - Missing substitutable ingredients are conjured with mana.
    - Non-substitutable ingredients must be held physically.
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        move_system: MoveSystem,
        game_state: GameState,
        mana_system: ManaSystem | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.move_system = move_system
        self.game_state = game_state
        self.mana_system = mana_system
        self.crafting_book = CraftingBook()

        # Highlight-mode state
        self._active_recipe: CraftingRecipe | None = None
        self._active_held_type: int | None = None
        self._highlighted_positions: set[tuple[int, int, int]] = set()
        self._current_z: int = 0

        event_bus.subscribe("craft_recipe_selected", self._on_recipe_selected)
        event_bus.subscribe("craft_cancel", self._on_craft_cancel)
        event_bus.subscribe("craft_at_position", self._on_craft_at_position)
        event_bus.subscribe("z_level_changed", self._on_z_changed)
        event_bus.subscribe("voxel_hover", self._on_voxel_hover)
        event_bus.subscribe("voxel_hover_clear", self._on_voxel_hover_clear)

    @property
    def is_craft_mode_active(self) -> bool:
        """Return True if a recipe is selected and highlights are showing."""
        return self._active_recipe is not None

    # ── Cost helpers ──────────────────────────────────────────────────

    def _current_cost(self, recipe: CraftingRecipe) -> CraftCost:
        """Compute craft cost against the player's current inventory."""
        return compute_craft_cost(
            recipe.ingredients,
            recipe.assembly_cost,
            self.move_system.held_materials,
        )

    def _can_afford_mana(self, cost: CraftCost) -> bool:
        """Return True if the player can pay *cost.total* mana (or free)."""
        if cost.total == 0:
            return True
        return (
            self.mana_system is not None
            and self.mana_system.can_spend(cost.total)
        )

    def _resolve_held_type(self, recipe: CraftingRecipe) -> int | None:
        """Pick a held_type for the recipe, or None if uncraftable.

        Prefers a physical material from inventory.  Falls back to the
        recipe's canonical ingredient type for mana-only crafting.
        """
        held_keys = set(self.move_system.held_materials.keys())
        matching = held_keys & recipe.required_inputs
        if matching:
            return next(iter(matching))
        # Mana-only fallback: use canonical ingredient type.
        if recipe.ingredients:
            return recipe.ingredients[0].vtype
        return None

    # ── Recipe selection ─────────────────────────────────────────────

    def _on_recipe_selected(self, recipe_name: str, **kw) -> None:
        """Player clicked a recipe in the panel."""
        # If already in craft mode for this recipe, toggle it off
        if (
            self._active_recipe is not None
            and self._active_recipe.name == recipe_name
        ):
            self._exit_craft_mode()
            return

        recipe = self.crafting_book.get_recipe_by_name(recipe_name)
        if recipe is None:
            logger.warning("Unknown recipe: %s", recipe_name)
            return

        cost = self._current_cost(recipe)

        if not cost.craftable:
            self.event_bus.publish(
                "error_message", text="Missing required material"
            )
            return

        if not self._can_afford_mana(cost):
            self.event_bus.publish(
                "error_message",
                text=f"Not enough mana ({cost.total})",
            )
            return

        held_type = self._resolve_held_type(recipe)
        if held_type is None:
            self.event_bus.publish(
                "error_message", text="Missing required material"
            )
            return

        self._active_recipe = recipe
        self._active_held_type = held_type

        # Scan and highlight
        self._scan_and_highlight(self._current_z)

        self.game_state.craft_mode_active = True
        self.event_bus.publish(
            "craft_mode_entered", recipe_name=recipe.name
        )

        # Publish initial remaining count
        self._publish_remaining_count()

        logger.info(
            "Craft mode entered: %s (held_type=%d)", recipe.name, held_type
        )

    # ── Position scanning ────────────────────────────────────────────

    def _scan_and_highlight(self, z_level: int) -> None:
        """Find all valid craft positions at z_level and publish highlights."""
        if self._active_recipe is None or self._active_held_type is None:
            return

        cost = self._current_cost(self._active_recipe)

        if not cost.craftable or not self._can_afford_mana(cost):
            # Can't afford or missing non-substitutable material
            self._highlighted_positions = set()
            self.event_bus.publish(
                "craft_highlights_updated",
                positions=self._highlighted_positions,
            )
            return

        positions = self.crafting_book.find_valid_positions(
            self._active_recipe, self.voxel_grid, self._active_held_type,
            z_level,
        )
        self._highlighted_positions = set(positions)

        self.event_bus.publish(
            "craft_highlights_updated",
            positions=self._highlighted_positions,
        )

    # ── Hover feedback ───────────────────────────────────────────────

    def _on_voxel_hover(self, x: int, y: int, z: int, **kw) -> None:
        """Evaluate hovered position and publish craft hover feedback."""
        if self._active_recipe is None:
            return

        if (x, y, z) in self._highlighted_positions:
            cost = self._current_cost(self._active_recipe)
            self.event_bus.publish(
                "craft_hover_valid",
                x=x, y=y, z=z,
                recipe_name=self._active_recipe.name,
                output_vtype=self._active_recipe.output_vtype,
                effect_radius=self._active_recipe.effect_radius,
                behavior_hint=self._active_recipe.behavior_hint,
                mana_cost=cost.total,
            )
        else:
            self.event_bus.publish(
                "craft_hover_invalid", x=x, y=y, z=z,
            )

    def _on_voxel_hover_clear(self, **kw) -> None:
        """Clear craft hover when mouse leaves the grid."""
        if self._active_recipe is not None:
            self.event_bus.publish("craft_hover_clear")

    # ── Craft execution ──────────────────────────────────────────────

    def _on_craft_at_position(self, x: int, y: int, z: int, **kw) -> None:
        """Player clicked a position while in craft mode."""
        if self._active_recipe is None:
            return

        if (x, y, z) not in self._highlighted_positions:
            # Forgiving misclick: warn but stay in craft mode
            self.event_bus.publish(
                "error_message", text="Cannot craft here"
            )
            return

        recipe = self._active_recipe
        held_type = self._active_held_type

        # Recompute cost (inventory may have changed since scan)
        cost = self._current_cost(recipe)

        if not cost.craftable:
            self.event_bus.publish(
                "error_message", text="Missing required material"
            )
            return

        if not self._can_afford_mana(cost):
            self.event_bus.publish(
                "error_message",
                text=f"Not enough mana ({cost.total})",
            )
            return

        # Execute the recipe — craft_fns handle enchanted offset
        held_metal = self.move_system.get_held_metal_type(held_type)
        success = recipe.craft_fn(
            self.voxel_grid, x, y, z, held_type, self.event_bus,
            held_metal=held_metal,
        )
        if not success:
            self.event_bus.publish(
                "error_message", text="Craft failed"
            )
            return

        # Deduct mana
        if cost.total > 0:
            self.mana_system.spend(cost.total)

        # Consume materials
        for vtype, count in cost.materials_consumed.items():
            self.move_system.consume(vtype, count)

        self.event_bus.publish(
            "craft_success",
            recipe=recipe.name,
            x=x, y=y, z=z,
        )
        self.event_bus.publish(
            "craft_placement_flash", x=x, y=y, z=z,
        )
        logger.info(
            "Crafted '%s' at (%d, %d, %d)", recipe.name, x, y, z
        )

        # Re-determine held_type and check if we can keep crafting
        new_held = self._resolve_held_type(recipe)
        new_cost = self._current_cost(recipe)

        if (
            new_held is None
            or not new_cost.craftable
            or not self._can_afford_mana(new_cost)
        ):
            self._exit_craft_mode()
            return

        self._active_held_type = new_held

        # Re-scan highlights
        self._scan_and_highlight(self._current_z)

        # Update remaining count after consumption
        self._publish_remaining_count()

    # ── Remaining count ──────────────────────────────────────────────

    def _publish_remaining_count(self) -> None:
        """Publish the remaining craft count for the active recipe."""
        if self._active_recipe is None or self._active_held_type is None:
            return

        cost = self._current_cost(self._active_recipe)
        remaining = self._remaining_crafts(cost)

        self.event_bus.publish(
            "craft_remaining_updated",
            recipe_name=self._active_recipe.name,
            remaining=remaining,
        )

    def _remaining_crafts(self, cost: CraftCost) -> int:
        """How many more times the player can afford this recipe."""
        remaining: float = float("inf")

        # Limited by materials
        for vtype, count in cost.materials_consumed.items():
            available = self.move_system.get_count(vtype)
            remaining = min(remaining, available // count)

        # Limited by mana
        if cost.total > 0:
            if self.mana_system is not None:
                remaining = min(
                    remaining, self.mana_system.mana // cost.total
                )
            else:
                remaining = 0

        return 0 if remaining == float("inf") else int(remaining)

    # ── Cancellation ─────────────────────────────────────────────────

    def _on_craft_cancel(self, **kw) -> None:
        """Player cancelled craft mode (ESC, right-click, panel toggle)."""
        if self._active_recipe is not None:
            self._exit_craft_mode()

    def _exit_craft_mode(self) -> None:
        """Clear craft mode state and notify subscribers."""
        self._active_recipe = None
        self._active_held_type = None
        self._highlighted_positions.clear()

        self.game_state.craft_mode_active = False
        self.event_bus.publish("craft_highlights_cleared")
        self.event_bus.publish("craft_mode_exited")
        logger.info("Craft mode exited")

    # ── Z-level change ───────────────────────────────────────────────

    def _on_z_changed(self, z: int, **kw) -> None:
        """Re-scan valid positions when the view layer changes."""
        self._current_z = z
        if self._active_recipe is not None:
            self._scan_and_highlight(z)
