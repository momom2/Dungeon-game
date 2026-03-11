"""Prototype crafting recipes: arrow trap and door.

Only two recipes exist in the prototype:
  - Arrow Trap: hold stone, click a stone block with >= 1 air neighbor
  - Door: hold stone, click an air cell between 2 opposite walls

Dependencies: dungeon_builder.config, dungeon_builder.building.crafting_book,
    prototype.config
Dependents: prototype.main, tests/prototype/test_crafting.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_builder.config import VOXEL_AIR, VOXEL_STONE, VOXEL_DOOR
from dungeon_builder.building.crafting_book import (
    CraftingBook,
    CraftingRecipe,
    NEIGHBORS_6,
    _has_opposite_walls,
)
from dungeon_builder.building.craft_cost import RecipeIngredient
from prototype.config import VOXEL_ARROW_TRAP

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid


# ── Arrow Trap recipe ───────────────────────────────────────────────

def _check_arrow_trap(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int,
) -> bool:
    """Stone on a stone block that has at least one air neighbor."""
    if held_type != VOXEL_STONE:
        return False
    if grid.get(x, y, z) != VOXEL_STONE:
        return False
    # At least one adjacent air cell (the trap needs an exposed face to fire)
    for dx, dy, dz in NEIGHBORS_6:
        if grid.get(x + dx, y + dy, z + dz) == VOXEL_AIR:
            return True
    return False


def _craft_arrow_trap(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int,
    event_bus: EventBus, **kwargs,
) -> bool:
    """Replace the stone block with an arrow trap."""
    grid.set(x, y, z, VOXEL_ARROW_TRAP, event_bus=event_bus)
    return True


# ── Door recipe ─────────────────────────────────────────────────────

def _check_door(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int,
) -> bool:
    """Stone on air between 2 opposite walls."""
    if held_type != VOXEL_STONE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return _has_opposite_walls(grid, x, y, z)


def _craft_door(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int,
    event_bus: EventBus, **kwargs,
) -> bool:
    """Place a door and set initial state to closed."""
    grid.set(x, y, z, VOXEL_DOOR, event_bus=event_bus)
    grid.set_block_state(x, y, z, 1)  # closed
    return True


# ── Prototype crafting book ─────────────────────────────────────────

class PrototypeCraftingBook(CraftingBook):
    """Crafting book with only arrow trap and door recipes.

    Overrides the parent's full recipe list with the two prototype recipes.
    No mana cost for either.
    """

    def __init__(self) -> None:
        # Skip parent __init__ (which populates all recipes)
        self.recipes: list[CraftingRecipe] = [
            CraftingRecipe(
                "Arrow Trap",
                "Apply stone to a stone block with exposed face to create a trap",
                [RecipeIngredient(VOXEL_STONE)],
                0,
                _check_arrow_trap,
                _craft_arrow_trap,
                output_vtype=VOXEL_ARROW_TRAP,
            ),
            CraftingRecipe(
                "Door",
                "Place stone between two opposite walls to build a door",
                [RecipeIngredient(VOXEL_STONE)],
                0,
                _check_door,
                _craft_door,
                output_vtype=VOXEL_DOOR,
            ),
        ]
        self._by_name: dict[str, CraftingRecipe] = {
            r.name: r for r in self.recipes
        }
