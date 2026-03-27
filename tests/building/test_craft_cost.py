"""Tests for the mana-or-materials craft cost model.

Verifies RecipeIngredient auto-population, CraftCost computation for
all material availability scenarios, and backward-compatible properties
on CraftingRecipe.
"""

import pytest

from dungeon_builder.building.craft_cost import (
    RecipeIngredient,
    CraftCost,
    compute_craft_cost,
)
from dungeon_builder.config.economy import MANA_SUBSTITUTE_COST
from dungeon_builder.config.voxels import (
    VOXEL_DIRT,
    VOXEL_STONE,
    VOXEL_GRANITE,
    VOXEL_OBSIDIAN,
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_GOLD_INGOT,
    VOXEL_ENCHANTED_METAL,
    VOXEL_IRON_ORE,
    VOXEL_MANA_CRYSTAL,
)


# ── RecipeIngredient auto-population ────────────────────────────────


class TestRecipeIngredient:
    def test_substitutable_auto_fills_mana_value(self):
        """Substitutable ingredients get their mana_value from the LUT."""
        ing = RecipeIngredient(VOXEL_IRON_INGOT)
        assert ing.substitutable is True
        assert ing.mana_value == MANA_SUBSTITUTE_COST[VOXEL_IRON_INGOT]

    def test_non_substitutable_when_absent_from_lut(self):
        """Materials absent from MANA_SUBSTITUTE_COST are non-substitutable."""
        ing = RecipeIngredient(VOXEL_IRON_ORE)
        assert ing.substitutable is False
        assert ing.mana_value == 0

    def test_mana_crystal_non_substitutable(self):
        ing = RecipeIngredient(VOXEL_MANA_CRYSTAL)
        assert ing.substitutable is False

    def test_explicit_non_substitutable_overrides(self):
        """Explicitly marking substitutable=False is respected even for
        materials that ARE in the LUT (e.g., gold ingot for Treasure)."""
        ing = RecipeIngredient(VOXEL_GOLD_INGOT, substitutable=False)
        assert ing.substitutable is False
        # mana_value stays 0 since it's non-substitutable
        assert ing.mana_value == 0

    def test_explicit_mana_value(self):
        """Explicit mana_value overrides the LUT value."""
        ing = RecipeIngredient(VOXEL_STONE, mana_value=999)
        assert ing.mana_value == 999
        assert ing.substitutable is True

    def test_frozen(self):
        """RecipeIngredient should be immutable."""
        ing = RecipeIngredient(VOXEL_DIRT)
        with pytest.raises(AttributeError):
            ing.vtype = 999

    def test_all_lut_materials_are_substitutable(self):
        """Every material in the LUT produces a substitutable ingredient."""
        for vtype, cost in MANA_SUBSTITUTE_COST.items():
            ing = RecipeIngredient(vtype)
            assert ing.substitutable is True
            assert ing.mana_value == cost

    def test_alternatives_in_all_accepted(self):
        """all_accepted includes canonical type plus alternatives."""
        ing = RecipeIngredient(
            VOXEL_IRON_INGOT,
            alternatives=frozenset({VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT}),
        )
        assert ing.all_accepted == frozenset({
            VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
        })


# ── compute_craft_cost ──────────────────────────────────────────────


class TestComputeCraftCost:
    def test_full_materials_no_substitution(self):
        """Player has all ingredients — pays assembly only."""
        ingredients = [RecipeIngredient(VOXEL_IRON_INGOT)]
        held = {VOXEL_IRON_INGOT: 5}
        cost = compute_craft_cost(ingredients, assembly_cost=10, held_materials=held)

        assert cost.assembly == 10
        assert cost.material_mana == 0
        assert cost.total == 10
        assert cost.materials_consumed == {VOXEL_IRON_INGOT: 1}
        assert cost.missing == []
        assert cost.craftable is True

    def test_no_materials_full_substitution(self):
        """Player has nothing — pays assembly + full substitution."""
        ingredients = [RecipeIngredient(VOXEL_IRON_INGOT)]
        held: dict[int, int] = {}
        cost = compute_craft_cost(ingredients, assembly_cost=10, held_materials=held)

        iron_sub = MANA_SUBSTITUTE_COST[VOXEL_IRON_INGOT]
        assert cost.assembly == 10
        assert cost.material_mana == iron_sub
        assert cost.total == 10 + iron_sub
        assert cost.materials_consumed == {}
        assert cost.craftable is True

    def test_non_substitutable_missing(self):
        """Non-substitutable ingredient missing — craft impossible."""
        ingredients = [RecipeIngredient(VOXEL_IRON_ORE)]
        held: dict[int, int] = {}
        cost = compute_craft_cost(ingredients, assembly_cost=0, held_materials=held)

        assert cost.craftable is False
        assert len(cost.missing) == 1
        assert cost.missing[0].vtype == VOXEL_IRON_ORE

    def test_non_substitutable_present(self):
        """Non-substitutable ingredient present — consumed, no mana cost."""
        ingredients = [RecipeIngredient(VOXEL_IRON_ORE)]
        held = {VOXEL_IRON_ORE: 1}
        cost = compute_craft_cost(ingredients, assembly_cost=0, held_materials=held)

        assert cost.craftable is True
        assert cost.total == 0
        assert cost.materials_consumed == {VOXEL_IRON_ORE: 1}

    def test_mixed_ingredients(self):
        """Recipe with multiple ingredients, some held, some substituted."""
        ingredients = [
            RecipeIngredient(VOXEL_IRON_INGOT),
            RecipeIngredient(VOXEL_GRANITE),
        ]
        # Player has iron but not granite
        held = {VOXEL_IRON_INGOT: 3}
        cost = compute_craft_cost(ingredients, assembly_cost=5, held_materials=held)

        granite_sub = MANA_SUBSTITUTE_COST[VOXEL_GRANITE]
        assert cost.assembly == 5
        assert cost.material_mana == granite_sub
        assert cost.total == 5 + granite_sub
        assert cost.materials_consumed == {VOXEL_IRON_INGOT: 1}
        assert cost.craftable is True

    def test_multiple_same_ingredient(self):
        """Multiple units of the same ingredient consume from inventory."""
        ingredients = [
            RecipeIngredient(VOXEL_STONE),
            RecipeIngredient(VOXEL_STONE),
            RecipeIngredient(VOXEL_STONE),
        ]
        # Player has only 2 stone — third must be substituted
        held = {VOXEL_STONE: 2}
        cost = compute_craft_cost(ingredients, assembly_cost=0, held_materials=held)

        stone_sub = MANA_SUBSTITUTE_COST[VOXEL_STONE]
        assert cost.material_mana == stone_sub  # 1 missing
        assert cost.materials_consumed == {VOXEL_STONE: 2}
        assert cost.craftable is True

    def test_zero_assembly_zero_ingredients(self):
        """Edge case: recipe with no ingredients and no assembly cost."""
        cost = compute_craft_cost([], assembly_cost=0, held_materials={})
        assert cost.total == 0
        assert cost.craftable is True

    def test_assembly_only_no_ingredients(self):
        """Recipe with only assembly cost, no ingredients."""
        cost = compute_craft_cost([], assembly_cost=50, held_materials={})
        assert cost.total == 50
        assert cost.craftable is True

    def test_mixed_substitutable_and_non(self):
        """Recipe with both substitutable and non-substitutable ingredients."""
        ingredients = [
            RecipeIngredient(VOXEL_IRON_INGOT),       # substitutable
            RecipeIngredient(VOXEL_MANA_CRYSTAL),      # non-substitutable
        ]
        # Player has neither
        held: dict[int, int] = {}
        cost = compute_craft_cost(ingredients, assembly_cost=30, held_materials=held)

        assert cost.craftable is False
        assert len(cost.missing) == 1
        assert cost.missing[0].vtype == VOXEL_MANA_CRYSTAL
        # Iron would be substituted if craftable
        iron_sub = MANA_SUBSTITUTE_COST[VOXEL_IRON_INGOT]
        assert cost.material_mana == iron_sub

    def test_mixed_substitutable_and_non_all_held(self):
        """Both substitutable and non-substitutable present — no mana for materials."""
        ingredients = [
            RecipeIngredient(VOXEL_IRON_INGOT),
            RecipeIngredient(VOXEL_MANA_CRYSTAL),
        ]
        held = {VOXEL_IRON_INGOT: 1, VOXEL_MANA_CRYSTAL: 1}
        cost = compute_craft_cost(ingredients, assembly_cost=30, held_materials=held)

        assert cost.craftable is True
        assert cost.total == 30  # assembly only
        assert cost.materials_consumed == {VOXEL_IRON_INGOT: 1, VOXEL_MANA_CRYSTAL: 1}

    def test_inventory_not_mutated(self):
        """compute_craft_cost must not modify the held_materials dict."""
        held = {VOXEL_IRON_INGOT: 3}
        ingredients = [RecipeIngredient(VOXEL_IRON_INGOT)]
        compute_craft_cost(ingredients, assembly_cost=0, held_materials=held)
        assert held == {VOXEL_IRON_INGOT: 3}

    def test_explicitly_non_sub_in_lut_material(self):
        """Gold ingot marked non-substitutable (Treasure recipe)."""
        ingredients = [RecipeIngredient(VOXEL_GOLD_INGOT, substitutable=False)]
        held: dict[int, int] = {}
        cost = compute_craft_cost(ingredients, assembly_cost=10, held_materials=held)

        assert cost.craftable is False
        assert len(cost.missing) == 1
        assert cost.missing[0].vtype == VOXEL_GOLD_INGOT

    def test_alternative_material_matches(self):
        """An alternative vtype satisfies the ingredient without mana substitution."""
        ingredients = [RecipeIngredient(
            VOXEL_IRON_INGOT,
            alternatives=frozenset({VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT}),
        )]
        # Player holds copper, not iron
        held = {VOXEL_COPPER_INGOT: 1}
        cost = compute_craft_cost(ingredients, assembly_cost=5, held_materials=held)

        assert cost.craftable is True
        assert cost.material_mana == 0
        assert cost.total == 5
        assert cost.materials_consumed == {VOXEL_COPPER_INGOT: 1}

    def test_canonical_preferred_over_alternative(self):
        """Canonical type is consumed before alternatives."""
        ingredients = [RecipeIngredient(
            VOXEL_IRON_INGOT,
            alternatives=frozenset({VOXEL_COPPER_INGOT}),
        )]
        held = {VOXEL_IRON_INGOT: 1, VOXEL_COPPER_INGOT: 1}
        cost = compute_craft_cost(ingredients, assembly_cost=0, held_materials=held)

        assert cost.materials_consumed == {VOXEL_IRON_INGOT: 1}

    def test_alternative_falls_back_to_substitution(self):
        """If neither canonical nor alternative is held, mana substitution applies."""
        ingredients = [RecipeIngredient(
            VOXEL_IRON_INGOT,
            alternatives=frozenset({VOXEL_COPPER_INGOT}),
        )]
        held: dict[int, int] = {}
        cost = compute_craft_cost(ingredients, assembly_cost=0, held_materials=held)

        iron_sub = MANA_SUBSTITUTE_COST[VOXEL_IRON_INGOT]
        assert cost.material_mana == iron_sub
        assert cost.craftable is True


# ── CraftingRecipe backward compatibility ───────────────────────────


class TestCraftingRecipeCompat:
    """Verify backward-compatible properties on the new CraftingRecipe."""

    def _make_recipe(self, ingredients, assembly_cost=0):
        from dungeon_builder.building.crafting_book import CraftingRecipe
        return CraftingRecipe(
            name="Test",
            description="Test recipe",
            ingredients=ingredients,
            assembly_cost=assembly_cost,
            check_fn=lambda *a, **kw: True,
            craft_fn=lambda *a, **kw: True,
        )

    def test_required_inputs_property(self):
        """required_inputs returns frozenset of all ingredient vtypes."""
        recipe = self._make_recipe([
            RecipeIngredient(VOXEL_IRON_INGOT),
            RecipeIngredient(VOXEL_GRANITE),
        ])
        assert recipe.required_inputs == frozenset({VOXEL_IRON_INGOT, VOXEL_GRANITE})

    def test_required_inputs_includes_alternatives(self):
        """required_inputs includes alternative vtypes from ingredients."""
        recipe = self._make_recipe([
            RecipeIngredient(
                VOXEL_IRON_INGOT,
                alternatives=frozenset({VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT}),
            ),
        ])
        assert recipe.required_inputs == frozenset({
            VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
        })

    def test_mana_cost_property(self):
        """mana_cost returns assembly_cost (backward compat with old field)."""
        recipe = self._make_recipe(
            [RecipeIngredient(VOXEL_IRON_INGOT)],
            assembly_cost=10,
        )
        assert recipe.mana_cost == 10

    def test_max_mana_cost_property(self):
        """max_mana_cost returns total cost assuming no materials held."""
        recipe = self._make_recipe(
            [RecipeIngredient(VOXEL_IRON_INGOT)],
            assembly_cost=10,
        )
        iron_sub = MANA_SUBSTITUTE_COST[VOXEL_IRON_INGOT]
        assert recipe.max_mana_cost == 10 + iron_sub

    def test_max_mana_cost_excludes_non_substitutable(self):
        """max_mana_cost only sums substitutable ingredient values."""
        recipe = self._make_recipe(
            [
                RecipeIngredient(VOXEL_IRON_INGOT),
                RecipeIngredient(VOXEL_IRON_ORE),  # non-sub, mana_value=0
            ],
            assembly_cost=5,
        )
        iron_sub = MANA_SUBSTITUTE_COST[VOXEL_IRON_INGOT]
        assert recipe.max_mana_cost == 5 + iron_sub

    def test_has_non_substitutable(self):
        recipe = self._make_recipe([
            RecipeIngredient(VOXEL_IRON_INGOT),
            RecipeIngredient(VOXEL_MANA_CRYSTAL),
        ])
        assert recipe.has_non_substitutable is True

    def test_no_non_substitutable(self):
        recipe = self._make_recipe([
            RecipeIngredient(VOXEL_IRON_INGOT),
            RecipeIngredient(VOXEL_STONE),
        ])
        assert recipe.has_non_substitutable is False

    def test_category_default(self):
        recipe = self._make_recipe([])
        assert recipe.category == "traps"

    def test_effect_radius_default(self):
        recipe = self._make_recipe([])
        assert recipe.effect_radius == 0

    def test_behavior_hint_default(self):
        recipe = self._make_recipe([])
        assert recipe.behavior_hint == ""


# ── CraftingBook integration ────────────────────────────────────────


class TestCraftingBookIntegration:
    """Verify that the CraftingBook loads all recipes with new fields."""

    def test_all_recipes_have_ingredients(self):
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        for recipe in book.recipes:
            assert isinstance(recipe.ingredients, list), (
                f"{recipe.name}: ingredients should be a list"
            )
            assert len(recipe.ingredients) > 0 or recipe.assembly_cost >= 0, (
                f"{recipe.name}: recipe should have ingredients or assembly cost"
            )

    def test_all_recipes_have_category(self):
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        valid_categories = {
            "terrain", "barriers", "traps", "thermal",
            "enchanted", "plumbing", "crafting",
        }
        for recipe in book.recipes:
            assert recipe.category in valid_categories, (
                f"{recipe.name}: invalid category '{recipe.category}'"
            )

    def test_required_inputs_backward_compat(self):
        """Every recipe's required_inputs property returns a non-empty frozenset."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        for recipe in book.recipes:
            ri = recipe.required_inputs
            assert isinstance(ri, frozenset), f"{recipe.name}: not a frozenset"
            assert len(ri) > 0, f"{recipe.name}: empty required_inputs"

    def test_recipe_count_unchanged(self):
        """Total recipe count should be 27 (7 natural + 20 functional)."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        assert len(book.recipes) == 27

    def test_get_recipe_by_name(self):
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        spike = book.get_recipe_by_name("Spike Trap")
        assert spike is not None
        assert spike.category == "traps"
        assert spike.assembly_cost == 0  # Phase 1: matches old mana_cost=0
        assert spike.behavior_hint != ""

    def test_enchanted_recipes_have_assembly_cost(self):
        """All enchanted-category recipes should have assembly_cost > 0."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        for recipe in book.recipes:
            if recipe.category == "enchanted":
                assert recipe.assembly_cost > 0, (
                    f"{recipe.name}: enchanted recipe needs assembly cost"
                )

    def test_effect_radius_recipes(self):
        """Recipes with effect_radius > 0 should be in expected set."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        radius_recipes = {r.name for r in book.recipes if r.effect_radius > 0}
        expected = {"Gold Bait", "Heat Beacon", "Pressure Plate", "Alarm Bell", "Steam Vent"}
        assert radius_recipes == expected
