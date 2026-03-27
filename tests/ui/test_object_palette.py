"""Tests for the ObjectPalette — categorized recipe panel with cost indicators.

Tests the headless-testable pure functions (filter_recipes_by_category,
compute_affordability) and the interface contract of ObjectPalette.
"""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.building.crafting_book import CraftingBook, CraftingRecipe
from dungeon_builder.building.craft_cost import RecipeIngredient
from dungeon_builder.ui.object_palette import (
    CATEGORIES,
    ObjectPalette,
    filter_recipes_by_category,
    compute_affordability,
)
from dungeon_builder.config import (
    VOXEL_STONE,
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_ENCHANTED_METAL,
    VOXEL_MANA_CRYSTAL,
    VOXEL_REINFORCED_WALL,
)


# ── Helpers ────────────────────────────────────────────────────────────────


class _FakeMana:
    """Minimal mana system stand-in for headless tests."""

    def __init__(self, mana: float = 0):
        self.mana = mana

    def can_spend(self, amount: float) -> bool:
        return self.mana >= amount


def _make_recipe(
    name: str = "Test",
    category: str = "traps",
    ingredients: list[RecipeIngredient] | None = None,
    assembly_cost: int = 0,
) -> CraftingRecipe:
    """Create a minimal CraftingRecipe for testing."""
    if ingredients is None:
        ingredients = [RecipeIngredient(VOXEL_IRON_INGOT)]
    return CraftingRecipe(
        name=name,
        description=f"Test recipe: {name}",
        ingredients=ingredients,
        assembly_cost=assembly_cost,
        check_fn=lambda *a: True,
        craft_fn=lambda *a, **kw: True,
        output_vtype=VOXEL_REINFORCED_WALL,
        category=category,
    )


# ── filter_recipes_by_category ─────────────────────────────────────────────


def test_filter_by_category():
    """Only recipes in the given category are returned."""
    r1 = _make_recipe("Wall", category="barriers")
    r2 = _make_recipe("Spike", category="traps")
    r3 = _make_recipe("Pipe", category="plumbing")
    result = filter_recipes_by_category(
        [r1, r2, r3], "traps", {"Wall", "Spike", "Pipe"},
    )
    assert len(result) == 1
    assert result[0].name == "Spike"


def test_filter_excludes_undiscovered():
    """Undiscovered recipes are filtered out."""
    r1 = _make_recipe("Known", category="traps")
    r2 = _make_recipe("Secret", category="traps")
    result = filter_recipes_by_category(
        [r1, r2], "traps", {"Known"},
    )
    assert len(result) == 1
    assert result[0].name == "Known"


def test_filter_empty_category():
    """Empty list when no recipes match the category."""
    r1 = _make_recipe("Wall", category="barriers")
    result = filter_recipes_by_category([r1], "thermal", {"Wall"})
    assert result == []


# ── compute_affordability ──────────────────────────────────────────────────


def test_affordability_material_held():
    """Returns 'material' when player holds the ingredient."""
    recipe = _make_recipe(ingredients=[RecipeIngredient(VOXEL_IRON_INGOT)])
    result = compute_affordability(recipe, {VOXEL_IRON_INGOT: 1}, None)
    assert result == "material"


def test_affordability_mana_only():
    """Returns 'mana_only' when mana can substitute the ingredient."""
    recipe = _make_recipe(ingredients=[RecipeIngredient(VOXEL_IRON_INGOT)])
    # Iron ingot mana_value = 30
    result = compute_affordability(recipe, {}, _FakeMana(100))
    assert result == "mana_only"


def test_affordability_unaffordable_no_mana():
    """Returns 'unaffordable' when neither material nor mana available."""
    recipe = _make_recipe(ingredients=[RecipeIngredient(VOXEL_IRON_INGOT)])
    result = compute_affordability(recipe, {}, None)
    assert result == "unaffordable"


def test_affordability_unaffordable_insufficient_mana():
    """Returns 'unaffordable' when mana is too low."""
    recipe = _make_recipe(ingredients=[RecipeIngredient(VOXEL_IRON_INGOT)])
    # Iron ingot mana_value = 30, only have 10
    result = compute_affordability(recipe, {}, _FakeMana(10))
    assert result == "unaffordable"


def test_affordability_non_substitutable_missing():
    """Returns 'unaffordable' when non-substitutable ingredient is missing."""
    # Mana Crystal is not in MANA_SUBSTITUTE_COST → non-substitutable
    recipe = _make_recipe(
        ingredients=[RecipeIngredient(VOXEL_MANA_CRYSTAL, substitutable=False)],
    )
    result = compute_affordability(recipe, {}, _FakeMana(1000))
    assert result == "unaffordable"


def test_affordability_free_recipe():
    """Zero-cost recipe returns 'material' regardless of mana."""
    recipe = _make_recipe(
        ingredients=[RecipeIngredient(VOXEL_STONE)],
        assembly_cost=0,
    )
    # Stone is substitutable (mana_value=10), but player holds it → free
    result = compute_affordability(recipe, {VOXEL_STONE: 1}, None)
    assert result == "material"


def test_affordability_assembly_plus_material():
    """Assembly cost + held material: affordable if mana covers assembly."""
    recipe = _make_recipe(
        ingredients=[RecipeIngredient(VOXEL_IRON_INGOT)],
        assembly_cost=20,
    )
    # Holding iron → material_mana = 0, total = 20 (assembly only)
    result = compute_affordability(recipe, {VOXEL_IRON_INGOT: 1}, _FakeMana(50))
    assert result == "material"


# ── CATEGORIES constant ───────────────────────────────────────────────────


def test_categories_cover_all_recipes():
    """Every recipe category in the CraftingBook is in CATEGORIES."""
    book = CraftingBook()
    cat_ids = {cat_id for cat_id, _ in CATEGORIES}
    recipe_cats = {r.category for r in book.recipes}
    missing = recipe_cats - cat_ids
    assert missing == set(), f"Recipes use categories not in CATEGORIES: {missing}"


# ── Interface contract ────────────────────────────────────────────────────


def test_object_palette_has_expected_methods():
    """ObjectPalette exposes the expected public interface."""
    assert callable(getattr(ObjectPalette, "toggle", None))
    assert hasattr(ObjectPalette, "is_visible")
    assert callable(getattr(ObjectPalette, "_on_recipe_click", None))
    assert callable(getattr(ObjectPalette, "_on_tab_click", None))
    assert callable(getattr(ObjectPalette, "_on_pin_toggle", None))
    assert callable(getattr(ObjectPalette, "_rebuild_recipe_list", None))
