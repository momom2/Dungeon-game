"""Crafting recipe definitions — the CRAFTING BOOK.

Each recipe has:
  - name / description: human-readable metadata
  - ingredients: list of RecipeIngredient (materials + mana substitution rules)
  - assembly_cost: irreducible mana cost always paid on craft
  - check_fn(grid, x, y, z, held_type) -> bool: can the craft happen here?
  - craft_fn(grid, x, y, z, held_type, event_bus) -> bool: execute the craft
  - category / effect_radius / behavior_hint: palette UI metadata

Backward-compatible properties ``required_inputs`` and ``mana_cost`` are
provided so that existing code continues to work during migration.

Recipe implementations live in:
  - building.crafting_recipes_natural (marble, ore smelting, obsidian, etc.)
  - building.crafting_recipes_functional (doors, traps, pipes, enchanted blocks)

Dependencies: config, building.craft_cost, building.crafting_helpers,
    building.crafting_recipes_natural, building.crafting_recipes_functional
Dependents: building.crafting_journal, building.crafting_system,
    tests/building/test_crafting.py, tests/building/test_crafting_journal.py,
    prototype.crafting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

from dungeon_builder.building.craft_cost import RecipeIngredient

# Re-export helpers for backward compatibility (prototype.crafting imports these)
from dungeon_builder.building.crafting_helpers import (  # noqa: F401
    NEIGHBORS_6,
    ORE_TO_INGOT,
    METAL_INGOTS,
    _count_solid_sides_xy,
    _has_opposite_walls,
    _has_any_solid_neighbor,
    _has_lava_below,
    _has_adjacent_water,
)
from dungeon_builder.building.crafting_recipes_natural import get_natural_recipes
from dungeon_builder.building.crafting_recipes_functional import get_functional_recipes

if TYPE_CHECKING:
    from dungeon_builder.world.voxel_grid import VoxelGrid


@dataclass
class CraftingRecipe:
    """A placeable object in the crafting book.

    New fields (``ingredients``, ``assembly_cost``, ``category``,
    ``effect_radius``, ``behavior_hint``) support the mana-or-materials
    cost model and object palette UI.  The legacy ``required_inputs`` and
    ``mana_cost`` properties remain for backward compatibility.
    """

    name: str
    description: str
    ingredients: list[RecipeIngredient]
    assembly_cost: int
    check_fn: Callable[..., bool]
    craft_fn: Callable[..., bool]
    output_vtype: int = 0
    category: str = "traps"
    effect_radius: int = 0
    behavior_hint: str = ""

    # ------------------------------------------------------------------
    # Backward-compatible properties
    # ------------------------------------------------------------------

    @property
    def required_inputs(self) -> frozenset[int]:
        """All accepted voxel types including alternatives (legacy accessor)."""
        result: set[int] = set()
        for ing in self.ingredients:
            result.add(ing.vtype)
            result |= ing.alternatives
        return frozenset(result)

    @property
    def has_non_substitutable(self) -> bool:
        """True if any ingredient cannot be replaced with mana."""
        return any(not ing.substitutable for ing in self.ingredients)

    @property
    def mana_cost(self) -> int:
        """Legacy mana cost — returns assembly_cost for backward compatibility.

        In Phase 1 of the crafting rework, assembly_cost is set to match the
        old mana_cost values (0 for non-mana recipes, >0 for enchanted/mana
        recipes).  Phase 2 will replace CraftingSystem's use of this property
        with ``compute_craft_cost``.
        """
        return self.assembly_cost

    @property
    def max_mana_cost(self) -> int:
        """Total mana cost assuming NO materials held (worst case).

        Used by the palette UI (Phase 3) for cost indicators.
        """
        return self.assembly_cost + sum(
            ing.mana_value for ing in self.ingredients if ing.substitutable
        )


class CraftingBook:
    """Contains all crafting recipes. Recipes are checked in order."""

    def __init__(self) -> None:
        self.recipes: list[CraftingRecipe] = (
            get_natural_recipes() + get_functional_recipes()
        )

        # Name -> recipe lookup for quick access
        self._by_name: dict[str, CraftingRecipe] = {
            r.name: r for r in self.recipes
        }

    def get_recipe_by_name(self, name: str) -> CraftingRecipe | None:
        """Return recipe by name, or None if not found."""
        return self._by_name.get(name)

    def find_recipe(
        self, grid: VoxelGrid, x: int, y: int, z: int, held_type: int
    ) -> CraftingRecipe | None:
        """Return the first matching recipe, or None."""
        for recipe in self.recipes:
            if recipe.check_fn(grid, x, y, z, held_type):
                return recipe
        return None

    def find_all_recipes(
        self, grid: VoxelGrid, x: int, y: int, z: int, held_type: int
    ) -> list[CraftingRecipe]:
        """Return ALL matching recipes (not just the first)."""
        return [r for r in self.recipes if r.check_fn(grid, x, y, z, held_type)]

    def find_valid_positions(
        self,
        recipe: CraftingRecipe,
        grid: VoxelGrid,
        held_type: int,
        z_level: int,
    ) -> list[tuple[int, int, int]]:
        """Scan visible/claimed voxels at *z_level* for valid craft positions.

        Only checks the given z-level (the player's current view) for
        performance — 64x64 = 4096 cells per scan.
        """
        results: list[tuple[int, int, int]] = []
        w, d = grid.width, grid.depth
        if z_level < 0 or z_level >= grid.height:
            return results
        for x in range(w):
            for y in range(d):
                if not grid.is_visible(x, y, z_level) and not grid.is_claimed(x, y, z_level):
                    continue
                if recipe.check_fn(grid, x, y, z_level, held_type):
                    results.append((x, y, z_level))
        return results
