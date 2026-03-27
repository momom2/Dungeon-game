"""Tests for core block placement during world initialization."""

import numpy as np
import pytest

from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.world.geology import GeologyGenerator
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.claimed_territory import ClaimedTerritorySystem
from dungeon_builder.config import (
    CORE_X,
    CORE_Y,
    CORE_Z,
    VOXEL_AIR,
    VOXEL_BEDROCK,
    VOXEL_CORE,
    VOXEL_DIRT,
    VOXEL_STONE,
    DEFAULT_SEED,
    GRANULAR_POROSITY_THRESHOLD,
    VOXEL_POROSITY,
)


def _build_world():
    """Replicate the main.py world setup without Panda3D."""
    rng = SeededRNG(DEFAULT_SEED)
    grid = VoxelGrid()
    GeologyGenerator(rng).generate(grid)

    # Carve initial dungeon (mirrors main.py _carve_initial_dungeon)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if grid.in_bounds(CORE_X + dx, CORE_Y + dy, CORE_Z):
                grid.grid[CORE_X + dx, CORE_Y + dy, CORE_Z] = VOXEL_AIR
            if grid.in_bounds(CORE_X + dx, CORE_Y + dy, CORE_Z - 1):
                grid.grid[CORE_X + dx, CORE_Y + dy, CORE_Z - 1] = VOXEL_AIR

    shaft_x = CORE_X
    for z in range(0, CORE_Z + 1):
        for dx in range(2):
            for dy in range(2):
                x, y = shaft_x + dx, dy
                if grid.in_bounds(x, y, z):
                    grid.grid[x, y, z] = VOXEL_AIR

    for y in range(0, CORE_Y + 1):
        for dx in range(2):
            x = shaft_x + dx
            if grid.in_bounds(x, y, CORE_Z):
                grid.grid[x, y, CORE_Z] = VOXEL_AIR

    for dx in range(-2, 4):
        for dy in range(4):
            x, y = shaft_x + dx, dy
            if grid.in_bounds(x, y, 0):
                grid.grid[x, y, 0] = VOXEL_AIR

    # Place core block (the fix)
    grid.grid[CORE_X, CORE_Y, CORE_Z] = VOXEL_CORE

    return grid


class TestCorePlacement:
    """Verify core block is properly placed in the grid."""

    def test_core_placed_as_voxel_core(self):
        grid = _build_world()
        assert grid.get(CORE_X, CORE_Y, CORE_Z) == VOXEL_CORE

    def test_air_above_core(self):
        """Headroom carved above core so top face renders."""
        grid = _build_world()
        assert grid.get(CORE_X, CORE_Y, CORE_Z - 1) == VOXEL_AIR

    def test_air_around_core_at_same_level(self):
        """Room carved around core at its z-level."""
        grid = _build_world()
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            assert grid.get(CORE_X + dx, CORE_Y + dy, CORE_Z) == VOXEL_AIR, (
                f"({CORE_X+dx},{CORE_Y+dy},{CORE_Z}) should be air"
            )

    def test_core_has_5_exposed_faces(self):
        """Core has air on 4 sides + above = 5 air neighbors."""
        grid = _build_world()
        air_count = 0
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,-1),(0,0,1)]:
            if grid.get(CORE_X+dx, CORE_Y+dy, CORE_Z+dz) == VOXEL_AIR:
                air_count += 1
        assert air_count >= 5, f"Expected >=5 air faces, got {air_count}"


class TestCoreClaimedTerritory:
    """Verify claiming works with core block placed."""

    def test_core_is_visible(self):
        grid = _build_world()
        eb = EventBus()
        cts = ClaimedTerritorySystem(eb, grid)
        assert grid.is_visible(CORE_X, CORE_Y, CORE_Z)

    def test_room_around_core_claimed(self):
        grid = _build_world()
        eb = EventBus()
        cts = ClaimedTerritorySystem(eb, grid)
        # Air cells in the 5x5 room should be claimed
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                x, y = CORE_X + dx, CORE_Y + dy
                if (dx, dy) != (0, 0):
                    assert grid.is_claimed(x, y, CORE_Z), (
                        f"({x},{y},{CORE_Z}) should be claimed"
                    )

    def test_headroom_above_core_claimed(self):
        grid = _build_world()
        eb = EventBus()
        cts = ClaimedTerritorySystem(eb, grid)
        # z-1 level room should be claimed
        assert grid.is_claimed(CORE_X + 1, CORE_Y, CORE_Z - 1)

    def test_shaft_to_surface_claimed(self):
        grid = _build_world()
        eb = EventBus()
        cts = ClaimedTerritorySystem(eb, grid)
        # Shaft at (CORE_X, 0) should be claimed all the way up
        for z in range(0, CORE_Z):
            assert grid.is_claimed(CORE_X, 0, z), f"Shaft at z={z} not claimed"

    def test_significant_claimed_territory(self):
        """Overall claimed count should be substantial (shaft + corridor + room)."""
        grid = _build_world()
        eb = EventBus()
        cts = ClaimedTerritorySystem(eb, grid)
        claimed = int(np.sum(grid.claimed))
        assert claimed > 100, f"Only {claimed} claimed cells (expected >100)"

    def test_significant_visible_territory(self):
        """Visible blocks should include walls of claimed areas."""
        grid = _build_world()
        eb = EventBus()
        cts = ClaimedTerritorySystem(eb, grid)
        visible = int(np.sum(grid.visible))
        assert visible > 100, f"Only {visible} visible cells (expected >100)"


# ===========================================================================
# Stone platform reinforcement (from test_rendering_fixes.py)
# ===========================================================================


class TestStonePlatformReinforcement:
    """Shaft entrance uses stone platform instead of bedrock lining."""

    def _make_grid_and_carve(self):
        """Create a VoxelGrid, generate geology, and carve the dungeon."""
        rng = SeededRNG(42)
        grid = VoxelGrid()
        GeologyGenerator(rng).generate(grid)

        # We need to call _carve_initial_dungeon the same way main.py does.
        # Import the method's logic inline to avoid Panda3D ShowBase dependency.
        _STRONG = frozenset((VOXEL_AIR, VOXEL_STONE, VOXEL_BEDROCK, VOXEL_CORE))

        # Carve core room
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if grid.in_bounds(CORE_X + dx, CORE_Y + dy, CORE_Z):
                    grid.grid[CORE_X + dx, CORE_Y + dy, CORE_Z] = VOXEL_AIR
                if grid.in_bounds(CORE_X + dx, CORE_Y + dy, CORE_Z - 1):
                    grid.grid[CORE_X + dx, CORE_Y + dy, CORE_Z - 1] = VOXEL_AIR

        # Reinforce core room shell
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                is_perimeter = abs(dx) == 3 or abs(dy) == 3
                for z in (CORE_Z - 2, CORE_Z - 1, CORE_Z, CORE_Z + 1):
                    if z in (CORE_Z - 2, CORE_Z + 1) or is_perimeter:
                        x, y = CORE_X + dx, CORE_Y + dy
                        if grid.in_bounds(x, y, z):
                            if grid.grid[x, y, z] not in _STRONG:
                                grid.grid[x, y, z] = VOXEL_STONE

        # Carve shaft
        shaft_x, shaft_y = CORE_X, 0
        for z in range(0, CORE_Z + 1):
            for dx in range(2):
                for dy in range(2):
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        grid.grid[x, y, z] = VOXEL_AIR

        # Carve corridor
        for y in range(0, CORE_Y + 1):
            for dx in range(2):
                x = shaft_x + dx
                if grid.in_bounds(x, y, CORE_Z):
                    grid.grid[x, y, CORE_Z] = VOXEL_AIR

        # Stone platform
        _PLATFORM_RADIUS = 2
        _PLATFORM_DEPTH = 2
        for z in range(1, 1 + _PLATFORM_DEPTH):
            for dx in range(-_PLATFORM_RADIUS, 2 + _PLATFORM_RADIUS):
                for dy in range(-_PLATFORM_RADIUS, 2 + _PLATFORM_RADIUS):
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        if grid.grid[x, y, z] not in _STRONG:
                            grid.grid[x, y, z] = VOXEL_STONE

        # Corridor reinforcement
        for y in range(0, CORE_Y + 1):
            for dx in (-1, 2):
                x = shaft_x + dx
                for dz in (-1, 0, 1):
                    z = CORE_Z + dz
                    if grid.in_bounds(x, y, z):
                        if grid.grid[x, y, z] not in _STRONG:
                            grid.grid[x, y, z] = VOXEL_STONE
            for dx in range(-1, 3):
                x = shaft_x + dx
                for dz in (-1, 1):
                    z = CORE_Z + dz
                    if grid.in_bounds(x, y, z):
                        if grid.grid[x, y, z] not in _STRONG:
                            grid.grid[x, y, z] = VOXEL_STONE

        # Place core
        grid.grid[CORE_X, CORE_Y, CORE_Z] = VOXEL_CORE

        return grid, shaft_x, shaft_y, CORE_X, CORE_Y, CORE_Z, VOXEL_DIRT

    def test_no_dirt_adjacent_to_shaft_at_surface(self):
        """Dirt should not be adjacent to the shaft at z=1 and z=2."""
        grid, shaft_x, shaft_y, *_, _VOXEL_DIRT = self._make_grid_and_carve()

        for z in (1, 2):
            # Check all blocks in the platform radius around the shaft
            for dx in range(-2, 4):
                for dy in range(-2, 4):
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        vtype = grid.grid[x, y, z]
                        assert vtype != VOXEL_DIRT, (
                            f"Dirt at ({x},{y},{z}) should be stone in platform"
                        )

    def test_no_granular_blocks_adjacent_to_shaft(self):
        """No granular material (porosity >= 0.2) should be next to the shaft."""
        grid, shaft_x, shaft_y, *_ = self._make_grid_and_carve()

        # Check 1-block ring around shaft at all z-levels of the shaft
        for z in range(1, 3):  # Platform z-levels
            for dx in (-1, 0, 1, 2):
                for dy in (-1, 0, 1, 2):
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        vtype = int(grid.grid[x, y, z])
                        if vtype == VOXEL_AIR:
                            continue
                        porosity = VOXEL_POROSITY.get(vtype, 0.0)
                        assert porosity < GRANULAR_POROSITY_THRESHOLD, (
                            f"Granular block type {vtype} (porosity={porosity}) "
                            f"at ({x},{y},{z}) should have been replaced with stone"
                        )

    def test_no_bedrock_in_shaft_walls(self):
        """Shaft walls should NOT contain bedrock (uses stone instead)."""
        grid, shaft_x, shaft_y, *_ = self._make_grid_and_carve()

        # Check the immediate shell around the 2x2 shaft
        for z in range(1, 11):  # shaft z=1 to z=10
            for dx in (-1, 0, 1, 2):
                for dy in (-1, 0, 1, 2):
                    # Skip shaft interior
                    if 0 <= dx <= 1 and 0 <= dy <= 1:
                        continue
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        vtype = grid.grid[x, y, z]
                        assert vtype != VOXEL_BEDROCK, (
                            f"Bedrock at ({x},{y},{z}) — shaft walls should "
                            f"use natural geology or stone, not bedrock"
                        )

    def test_corridor_walls_not_bedrock(self):
        """Corridor walls should be stone (or natural rock), not bedrock."""
        grid, shaft_x, _, _, _, _CORE_Z, _ = self._make_grid_and_carve()

        for y in range(0, 33):  # corridor y range
            for dx in (-1, 2):
                x = shaft_x + dx
                if grid.in_bounds(x, y, _CORE_Z):
                    vtype = grid.grid[x, y, _CORE_Z]
                    assert vtype != VOXEL_BEDROCK, (
                        f"Bedrock at corridor wall ({x},{y},{_CORE_Z})"
                    )

    def test_stone_platform_preserves_shaft_air(self):
        """The shaft interior should remain air after stone placement."""
        grid, shaft_x, shaft_y, *_ = self._make_grid_and_carve()

        for z in range(0, 11):
            for dx in range(2):
                for dy in range(2):
                    x, y = shaft_x + dx, shaft_y + dy
                    assert grid.grid[x, y, z] == VOXEL_AIR, (
                        f"Shaft interior at ({x},{y},{z}) should be air"
                    )
