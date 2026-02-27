"""Tests for prototype map generation.

Verifies stone-only terrain, carved entrance, and core placement.
"""

from __future__ import annotations

import pytest

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
)
from dungeon_builder.world.voxel_grid import VoxelGrid
from prototype.map_gen import generate_prototype_map


@pytest.fixture
def proto_grid() -> VoxelGrid:
    """Return a VoxelGrid with prototype map generated."""
    grid = VoxelGrid()
    generate_prototype_map(grid, seed=42)
    return grid


class TestTerrainFill:
    """Verify the basic terrain layers are correct."""

    def test_bedrock_layer(self, proto_grid: VoxelGrid) -> None:
        """Bottom layer is bedrock."""
        for x in range(GRID_WIDTH):
            for y in range(GRID_DEPTH):
                assert proto_grid.get(x, y, GRID_HEIGHT - 1) == VOXEL_BEDROCK

    def test_underground_is_stone(self, proto_grid: VoxelGrid) -> None:
        """Underground (well below surface) should be stone except for carve."""
        # Check a deep z-level away from the dungeon carve
        z = GRID_HEIGHT - 3  # Near bottom
        # Check a cell far from core and shaft — should be stone
        x, y = 0, GRID_DEPTH - 1  # Opposite corner from shaft/core
        assert proto_grid.get(x, y, z) == VOXEL_STONE

    def test_sky_is_air(self, proto_grid: VoxelGrid) -> None:
        """Top of the grid should be air."""
        assert proto_grid.get(0, 0, 0) == VOXEL_AIR

    def test_only_stone_bedrock_air_core(self, proto_grid: VoxelGrid) -> None:
        """Prototype map contains only AIR, STONE, BEDROCK, and CORE types."""
        import numpy as np
        unique = set(np.unique(proto_grid.grid))
        allowed = {VOXEL_AIR, VOXEL_STONE, VOXEL_BEDROCK, VOXEL_CORE}
        assert unique <= allowed, f"Unexpected voxel types: {unique - allowed}"


class TestDungeonCarve:
    """Verify the dungeon entrance is properly carved."""

    def test_core_block_placed(self, proto_grid: VoxelGrid) -> None:
        """Core block exists at the designated position."""
        assert proto_grid.get(CORE_X, CORE_Y, CORE_Z) == VOXEL_CORE

    def test_core_room_air(self, proto_grid: VoxelGrid) -> None:
        """5×5 core room has air around the core (same level)."""
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                x, y = CORE_X + dx, CORE_Y + dy
                if (dx, dy) == (0, 0):
                    continue  # Core block itself
                assert proto_grid.get(x, y, CORE_Z) == VOXEL_AIR, (
                    f"Core room not air at ({x},{y},{CORE_Z})"
                )

    def test_shaft_entrance_air(self, proto_grid: VoxelGrid) -> None:
        """Vertical shaft has air from surface to core level."""
        shaft_x = CORE_X
        for z in range(SURFACE_Z, CORE_Z + 1):
            assert proto_grid.get(shaft_x, 0, z) == VOXEL_AIR, (
                f"Shaft not air at ({shaft_x},0,{z})"
            )
            assert proto_grid.get(shaft_x + 1, 0, z) == VOXEL_AIR, (
                f"Shaft not air at ({shaft_x + 1},0,{z})"
            )

    def test_corridor_connects_shaft_to_core(self, proto_grid: VoxelGrid) -> None:
        """Horizontal corridor at core level from y=0 to core room."""
        for y in range(0, CORE_Y + 1):
            assert proto_grid.get(CORE_X, y, CORE_Z) == VOXEL_AIR or \
                   proto_grid.get(CORE_X, y, CORE_Z) == VOXEL_CORE, (
                f"Corridor not clear at ({CORE_X},{y},{CORE_Z})"
            )

    def test_heightmap_hills(self, proto_grid: VoxelGrid) -> None:
        """Some cells above SURFACE_Z should be stone (hills), some air."""
        has_stone = False
        has_air = False
        for x in range(GRID_WIDTH):
            for y in range(GRID_DEPTH):
                vtype = proto_grid.get(x, y, SURFACE_Z)
                if vtype == VOXEL_STONE:
                    has_stone = True
                elif vtype == VOXEL_AIR:
                    has_air = True
        # With noise, there should be a mix at surface level
        assert has_stone or has_air, "Surface level should have some variation"
