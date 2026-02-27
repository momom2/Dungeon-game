"""Tests for prototype crafting recipes (arrow trap + door).

Verifies recipe validation and execution for both prototype recipes.
"""

from __future__ import annotations

import pytest

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DOOR,
    GRID_HEIGHT,
)
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from prototype.config import VOXEL_ARROW_TRAP, patch_shared_config
from prototype.crafting import (
    PrototypeCraftingBook,
    _check_arrow_trap,
    _craft_arrow_trap,
    _check_door,
    _craft_door,
)


@pytest.fixture(autouse=True)
def _patched_config() -> None:
    """Ensure shared config is patched for all tests."""
    patch_shared_config()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def small_grid() -> VoxelGrid:
    """5×5×5 grid filled with stone, air in center."""
    grid = VoxelGrid(width=5, depth=5, height=5)
    grid.grid[:, :, :] = VOXEL_STONE
    # Carve a 3×3 air corridor at z=2
    for x in range(1, 4):
        for y in range(1, 4):
            grid.grid[x, y, 2] = VOXEL_AIR
    return grid


class TestArrowTrapRecipe:
    """Arrow trap: stone on stone block with ≥1 air neighbor."""

    def test_valid_placement(self, small_grid: VoxelGrid) -> None:
        """Stone block at (1,0,2) has air neighbor at (1,1,2)."""
        # (1,0,2) is stone (wall of corridor), (1,1,2) is air
        assert _check_arrow_trap(small_grid, 1, 0, 2, VOXEL_STONE)

    def test_invalid_no_air_neighbor(self, small_grid: VoxelGrid) -> None:
        """Deep stone block with no air neighbors is invalid."""
        # (0,0,4) is surrounded by stone/bedrock — no air
        assert not _check_arrow_trap(small_grid, 0, 0, 4, VOXEL_STONE)

    def test_invalid_target_is_air(self, small_grid: VoxelGrid) -> None:
        """Cannot place trap on air cell."""
        assert not _check_arrow_trap(small_grid, 2, 2, 2, VOXEL_STONE)

    def test_invalid_wrong_held(self, small_grid: VoxelGrid) -> None:
        """Cannot place trap without holding stone."""
        assert not _check_arrow_trap(small_grid, 1, 0, 2, VOXEL_DOOR)

    def test_craft_replaces_with_trap(
        self, small_grid: VoxelGrid, event_bus: EventBus,
    ) -> None:
        """Crafting replaces stone with arrow trap block."""
        assert small_grid.get(1, 0, 2) == VOXEL_STONE
        result = _craft_arrow_trap(small_grid, 1, 0, 2, VOXEL_STONE, event_bus)
        assert result is True
        assert small_grid.get(1, 0, 2) == VOXEL_ARROW_TRAP


class TestDoorRecipe:
    """Door: stone on air between 2 opposite walls."""

    def test_valid_between_walls(self, small_grid: VoxelGrid) -> None:
        """Air at (1,2,2) with stone at (0,2,2) and stone at boundary counts."""
        # The corridor at z=2 has walls at x=0 and x=4 (stone)
        # Air at x=1..3, y=1..3
        # Check (1,1,2): stone at (0,1,2) and air at (2,1,2)
        # We need opposite walls — let's use the narrow dimension
        # (1,1,2) has stone at x=0 side. Need stone at x=2 side → it's air.
        # Better: create a narrow corridor for this test.
        grid = VoxelGrid(width=5, depth=5, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        # Make a 1-wide corridor along Y at x=2, z=2
        for y in range(5):
            grid.grid[2, y, 2] = VOXEL_AIR
        # (2,2,2) is air with stone at (1,2,2) and (3,2,2) — opposite walls
        assert _check_door(grid, 2, 2, 2, VOXEL_STONE)

    def test_invalid_not_air(self, small_grid: VoxelGrid) -> None:
        """Cannot place door on a stone block."""
        assert not _check_door(small_grid, 0, 0, 0, VOXEL_STONE)

    def test_invalid_no_opposite_walls(self, small_grid: VoxelGrid) -> None:
        """Air in open area (no opposite walls) is invalid."""
        assert not _check_door(small_grid, 2, 2, 2, VOXEL_STONE)

    def test_invalid_wrong_held(self, small_grid: VoxelGrid) -> None:
        """Cannot place door without holding stone."""
        grid = VoxelGrid(width=5, depth=5, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        for y in range(5):
            grid.grid[2, y, 2] = VOXEL_AIR
        assert not _check_door(grid, 2, 2, 2, VOXEL_DOOR)

    def test_craft_places_closed_door(self, event_bus: EventBus) -> None:
        """Crafting places a door in closed state (block_state=1)."""
        grid = VoxelGrid(width=5, depth=5, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        for y in range(5):
            grid.grid[2, y, 2] = VOXEL_AIR
        result = _craft_door(grid, 2, 2, 2, VOXEL_STONE, event_bus)
        assert result is True
        assert grid.get(2, 2, 2) == VOXEL_DOOR
        assert grid.get_block_state(2, 2, 2) == 1  # closed


class TestPrototypeCraftingBook:
    """Verify the PrototypeCraftingBook has exactly the right recipes."""

    def test_only_two_recipes(self) -> None:
        book = PrototypeCraftingBook()
        assert len(book.recipes) == 2

    def test_recipe_names(self) -> None:
        book = PrototypeCraftingBook()
        names = [r.name for r in book.recipes]
        assert "Arrow Trap" in names
        assert "Door" in names

    def test_no_mana_cost(self) -> None:
        book = PrototypeCraftingBook()
        for recipe in book.recipes:
            assert recipe.mana_cost == 0

    def test_find_arrow_trap(self, small_grid: VoxelGrid) -> None:
        """find_recipe returns Arrow Trap for valid stone-on-stone."""
        book = PrototypeCraftingBook()
        recipe = book.find_recipe(small_grid, 1, 0, 2, VOXEL_STONE)
        assert recipe is not None
        assert recipe.name == "Arrow Trap"

    def test_find_door(self) -> None:
        """find_recipe returns Door for valid stone-on-air-between-walls."""
        grid = VoxelGrid(width=5, depth=5, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        for y in range(5):
            grid.grid[2, y, 2] = VOXEL_AIR
        book = PrototypeCraftingBook()
        recipe = book.find_recipe(grid, 2, 2, 2, VOXEL_STONE)
        assert recipe is not None
        assert recipe.name == "Door"

    def test_get_by_name(self) -> None:
        book = PrototypeCraftingBook()
        assert book.get_recipe_by_name("Arrow Trap") is not None
        assert book.get_recipe_by_name("Door") is not None
        assert book.get_recipe_by_name("Nonexistent") is None
