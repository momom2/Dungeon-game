"""Stone-only map generation for the prototype.

Generates a simplified world: stone terrain with a heightmap, a vertical
shaft from the surface to the core room, and a horizontal corridor
connecting the shaft to the core.

Dependencies: dungeon_builder.config (world, voxels), dungeon_builder.world.geology,
    dungeon_builder.world.voxel_grid
Dependents: prototype.main, tests/prototype/test_map_gen.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_builder.config import (
    GRID_WIDTH,
    GRID_DEPTH,
    GRID_HEIGHT,
    SURFACE_Z,
    CORE_X,
    CORE_Y,
    CORE_Z,
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_BEDROCK,
    VOXEL_CORE,
    TERRAIN_NOISE_SCALE,
    TERRAIN_VARIATION_MAX,
)
from dungeon_builder.world.geology import ValueNoise2D

if TYPE_CHECKING:
    from dungeon_builder.world.voxel_grid import VoxelGrid


def generate_prototype_map(voxel_grid: VoxelGrid, seed: int = 42) -> None:
    """Fill *voxel_grid* with stone-only terrain plus a carved dungeon.

    1. Bedrock floor at z = GRID_HEIGHT - 1
    2. Stone from z = SURFACE_Z + 1 down to z = GRID_HEIGHT - 2
    3. Simple heightmap hills (0–TERRAIN_VARIATION_MAX blocks of stone
       above SURFACE_Z) using ValueNoise2D
    4. Carved dungeon entrance: vertical shaft + horizontal corridor +
       5×5 core room
    5. Core block placed at (CORE_X, CORE_Y, CORE_Z)
    """
    grid = voxel_grid.grid

    # 1. Bedrock floor
    grid[:, :, GRID_HEIGHT - 1] = VOXEL_BEDROCK

    # 2. Underground stone fill
    grid[:, :, SURFACE_Z + 1 : GRID_HEIGHT - 1] = VOXEL_STONE

    # 3. Surface heightmap — rolling stone hills
    noise = ValueNoise2D(seed, scale=TERRAIN_NOISE_SCALE)
    for x in range(GRID_WIDTH):
        for y in range(GRID_DEPTH):
            # ValueNoise2D.sample returns [0, 1]; scale to hill height
            h = int(noise.sample(float(x), float(y)) * TERRAIN_VARIATION_MAX)
            # h blocks of stone above the underground surface
            for dz in range(h):
                z = SURFACE_Z - dz
                if 0 <= z < GRID_HEIGHT:
                    grid[x, y, z] = VOXEL_STONE

    # 4. Carve dungeon entrance
    _carve_dungeon(voxel_grid)

    # 5. Place core block
    grid[CORE_X, CORE_Y, CORE_Z] = VOXEL_CORE


def _carve_dungeon(voxel_grid: VoxelGrid) -> None:
    """Carve a vertical shaft, horizontal corridor, and 5×5 core room.

    Simplified version of DungeonApp._carve_initial_dungeon — no marble
    pillars, no reinforcement (no structural stress in prototype).
    """
    grid = voxel_grid.grid
    in_bounds = voxel_grid.in_bounds

    # ── 5×5 core room (2 z-levels of headroom) ──
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            for z in (CORE_Z, CORE_Z - 1):
                x, y = CORE_X + dx, CORE_Y + dy
                if in_bounds(x, y, z):
                    grid[x, y, z] = VOXEL_AIR

    # ── Vertical shaft from surface to core level ──
    # 2×2 shaft at (CORE_X, 0)
    shaft_x, shaft_y = CORE_X, 0
    for z in range(SURFACE_Z, CORE_Z + 1):
        for dx in range(2):
            for dy in range(2):
                x, y = shaft_x + dx, shaft_y + dy
                if in_bounds(x, y, z):
                    grid[x, y, z] = VOXEL_AIR

    # Clear any hill blocks above the shaft entrance
    for z in range(0, SURFACE_Z):
        for dx in range(2):
            for dy in range(2):
                x, y = shaft_x + dx, shaft_y + dy
                if in_bounds(x, y, z):
                    grid[x, y, z] = VOXEL_AIR

    # ── Horizontal corridor from shaft to core room at core level ──
    for y in range(0, CORE_Y + 1):
        for dx in range(2):
            x = shaft_x + dx
            if in_bounds(x, y, CORE_Z):
                grid[x, y, CORE_Z] = VOXEL_AIR
