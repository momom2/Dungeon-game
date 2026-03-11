"""Tests for debug spawn buttons (temporary testing feature).

Covers:
- IntruderAI subscribes to debug spawn events
- Publishing debug events triggers party spawning
- HUD has spawn buttons (interface checks)

Dependencies: intruders.decision, core.event_bus, world.voxel_grid,
    world.pathfinding, dungeon_core.core, utils.rng, config
Dependents: (none)
"""

from __future__ import annotations

import pytest

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR, SURFACE_Z, CORE_X, CORE_Y, CORE_Z,
)
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.intruders.decision import IntruderAI


# -- Helpers --


def _make_grid_with_air_edges() -> VoxelGrid:
    """Create a grid with air cells at surface edges for spawning."""
    grid = VoxelGrid()
    # Surface edge air for surface spawning
    for x in range(grid.width):
        grid.grid[x, 0, SURFACE_Z] = VOXEL_AIR
        grid.grid[x, grid.depth - 1, SURFACE_Z] = VOXEL_AIR
    # Air path from surface to core so pathfinding works
    for y in range(grid.depth):
        grid.grid[CORE_X, y, SURFACE_Z] = VOXEL_AIR
    return grid


# -- Test: Debug spawn event subscriptions --


class TestDebugSpawnSubscriptions:
    """IntruderAI should subscribe to debug spawn events."""

    def test_debug_spawn_handler_exists(self):
        """IntruderAI should have a _on_debug_spawn_party method."""
        assert hasattr(IntruderAI, "_on_debug_spawn_party")
        assert callable(getattr(IntruderAI, "_on_debug_spawn_party"))


# -- Test: Debug spawn via event bus --


class TestDebugSpawnViaEventBus:
    """Publishing debug events should trigger spawning."""

    def test_debug_spawn_surface_party(self):
        """Publishing debug_spawn_party should create surface intruders."""
        event_bus = EventBus()
        grid = _make_grid_with_air_edges()
        pathfinder = AStarPathfinder(grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=100)
        rng = SeededRNG(42)
        ai = IntruderAI(event_bus, grid, pathfinder, core, rng)

        assert len(ai.intruders) == 0
        assert len(ai.parties) == 0

        event_bus.publish("debug_spawn_party")

        assert len(ai.intruders) > 0
        assert len(ai.parties) == 1

    def test_debug_spawn_enables_spawning(self):
        """Debug spawn should enable spawning_enabled flag."""
        _cfg.DEV_MODE = True  # Dev mode -> spawning starts disabled
        event_bus = EventBus()
        grid = _make_grid_with_air_edges()
        pathfinder = AStarPathfinder(grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=100)
        rng = SeededRNG(42)
        ai = IntruderAI(event_bus, grid, pathfinder, core, rng)

        assert ai.spawning_enabled is False
        event_bus.publish("debug_spawn_party")
        assert ai.spawning_enabled is True

    def test_debug_spawn_multiple_times(self):
        """Can spawn multiple parties via repeated debug events."""
        event_bus = EventBus()
        grid = _make_grid_with_air_edges()
        pathfinder = AStarPathfinder(grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=100)
        rng = SeededRNG(42)
        ai = IntruderAI(event_bus, grid, pathfinder, core, rng)

        event_bus.publish("debug_spawn_party")
        event_bus.publish("debug_spawn_party")

        assert len(ai.parties) == 2


# -- Test: Debug spawn single intruder --


class TestDebugSpawnSingle:
    """Publishing debug_spawn_single should create a single intruder."""

    def test_debug_spawn_single_creates_one_intruder(self):
        event_bus = EventBus()
        grid = _make_grid_with_air_edges()
        pathfinder = AStarPathfinder(grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=100)
        rng = SeededRNG(42)
        ai = IntruderAI(event_bus, grid, pathfinder, core, rng)

        assert len(ai.intruders) == 0
        event_bus.publish("debug_spawn_single")
        assert len(ai.intruders) == 1

    def test_debug_spawn_single_handler_exists(self):
        assert hasattr(IntruderAI, "_on_debug_spawn_single")
        assert callable(getattr(IntruderAI, "_on_debug_spawn_single"))


# -- Test: Debug kill all --


class TestDebugKillAll:
    """Publishing debug_kill_all should kill all intruders."""

    def test_debug_kill_all_clears_intruders(self):
        event_bus = EventBus()
        grid = _make_grid_with_air_edges()
        pathfinder = AStarPathfinder(grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=100)
        rng = SeededRNG(42)
        ai = IntruderAI(event_bus, grid, pathfinder, core, rng)

        event_bus.publish("debug_spawn_party")
        assert len(ai.intruders) > 0

        event_bus.publish("debug_kill_all")
        assert all(not i.alive for i in ai.intruders) or len(ai.intruders) == 0

    def test_debug_kill_all_handler_exists(self):
        assert hasattr(IntruderAI, "_on_debug_kill_all")
        assert callable(getattr(IntruderAI, "_on_debug_kill_all"))


# -- Test: HUD has spawn buttons (interface checks) --


class TestHUDSpawnButtons:
    """HUD should have debug spawn button handlers."""

    def test_update_spawn_buttons_method_exists(self):
        """HUD should have _update_spawn_buttons for debug spawn visibility."""
        from dungeon_builder.ui.hud import HUD
        assert hasattr(HUD, "_update_spawn_buttons")
        assert callable(getattr(HUD, "_update_spawn_buttons"))
