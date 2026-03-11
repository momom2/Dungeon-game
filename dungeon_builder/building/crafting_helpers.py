"""Shared geometry helpers and constants for crafting recipes.

Dependencies: config, world.voxel_grid (TYPE_CHECKING only)
Dependents: building.crafting_book, building.crafting_recipes_natural,
    building.crafting_recipes_functional, prototype.crafting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_IRON_ORE,
    VOXEL_COPPER_ORE,
    VOXEL_GOLD_ORE,
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_GOLD_INGOT,
    VOXEL_ENCHANTED_METAL,
    VOXEL_LAVA,
    VOXEL_WATER,
)

if TYPE_CHECKING:
    from dungeon_builder.world.voxel_grid import VoxelGrid

# Ore -> Metal ingot mapping
ORE_TO_INGOT = {
    VOXEL_IRON_ORE: VOXEL_IRON_INGOT,
    VOXEL_COPPER_ORE: VOXEL_COPPER_INGOT,
    VOXEL_GOLD_ORE: VOXEL_GOLD_INGOT,
}

# Metal ingot types (for pile stacking)
METAL_INGOTS = frozenset({
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_GOLD_INGOT,
    VOXEL_ENCHANTED_METAL,
})

# 6-connected neighbor offsets
NEIGHBORS_6 = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


def _count_solid_sides_xy(grid: VoxelGrid, x: int, y: int, z: int) -> int:
    """Count how many of the 4 cardinal XY neighbors are solid (non-air)."""
    count = 0
    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        if grid.get(x + dx, y + dy, z) != VOXEL_AIR:
            count += 1
    return count


def _has_opposite_walls(grid: VoxelGrid, x: int, y: int, z: int) -> bool:
    """Check if there are solid blocks on 2 opposite sides (X or Y axis)."""
    # Check X axis
    if grid.get(x + 1, y, z) != VOXEL_AIR and grid.get(x - 1, y, z) != VOXEL_AIR:
        return True
    # Check Y axis
    if grid.get(x, y + 1, z) != VOXEL_AIR and grid.get(x, y - 1, z) != VOXEL_AIR:
        return True
    return False


def _has_any_solid_neighbor(grid: VoxelGrid, x: int, y: int, z: int) -> bool:
    """Check if any of the 6 neighbors is solid (non-air)."""
    for dx, dy, dz in NEIGHBORS_6:
        if grid.get(x + dx, y + dy, z + dz) != VOXEL_AIR:
            return True
    return False


def _has_lava_below(grid: VoxelGrid, x: int, y: int, z: int, max_depth: int = 2) -> bool:
    """Check if there is lava within *max_depth* cells below (z+1..z+max_depth)."""
    for dz in range(1, max_depth + 1):
        nz = z + dz
        if grid.get(x, y, nz) == VOXEL_LAVA:
            return True
        if grid.in_bounds(x, y, nz) and grid.get_lava_level(x, y, nz) > 0:
            return True
    return False


def _has_adjacent_water(grid: VoxelGrid, x: int, y: int, z: int) -> bool:
    """Check if any of the 6 neighbors contains water."""
    for dx, dy, dz in NEIGHBORS_6:
        nx, ny, nz = x + dx, y + dy, z + dz
        if grid.get(nx, ny, nz) == VOXEL_WATER:
            return True
        if grid.in_bounds(nx, ny, nz) and grid.get_water_level(nx, ny, nz) > 0:
            return True
    return False
