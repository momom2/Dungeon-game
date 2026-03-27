"""Tests for prototype intruder AI: spawning, pathfinding, core attack.

Verifies wave spawning, PrototypePathfinder door traversal, and
intruder-core combat loop.
"""

from __future__ import annotations

import pytest

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DOOR,
    VOXEL_CORE,
    CORE_X,
    CORE_Y,
    CORE_Z,
    CORE_DEFAULT_HP,
    SURFACE_Z,
)
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import EXPLORER, IntruderObjective
from dungeon_builder.intruders.personal_map import PersonalMap

from prototype.config import SPAWN_INTERVAL, PROTOTYPE_CORE_HP, patch_shared_config
from prototype.map_gen import generate_prototype_map
from prototype.intruders import (
    PrototypePathfinder,
    PrototypeIntruderAI,
)


@pytest.fixture(autouse=True)
def _patched_config() -> None:
    patch_shared_config()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def proto_grid() -> VoxelGrid:
    grid = VoxelGrid()
    generate_prototype_map(grid, seed=42)
    return grid


class TestPrototypePathfinder:
    """Verify pathfinder traverses air and open doors."""

    def test_path_through_air(self) -> None:
        """Simple path through an air corridor."""
        grid = VoxelGrid(width=10, depth=10, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        # 1-wide corridor along y at x=2, z=2
        for y in range(10):
            grid.grid[2, y, 2] = VOXEL_AIR
        pf = PrototypePathfinder(grid)
        path = pf.find_path((2, 0, 2), (2, 9, 2))
        assert path is not None
        assert path[0] == (2, 0, 2)
        assert path[-1] == (2, 9, 2)

    def test_path_through_open_door(self) -> None:
        """Pathfinder can traverse an open door (block_state=0)."""
        grid = VoxelGrid(width=10, depth=10, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        for y in range(10):
            grid.grid[2, y, 2] = VOXEL_AIR
        # Place a door at midpoint
        grid.grid[2, 5, 2] = VOXEL_DOOR
        grid.set_block_state(2, 5, 2, 0)  # Open
        pf = PrototypePathfinder(grid)
        path = pf.find_path((2, 0, 2), (2, 9, 2))
        assert path is not None
        assert (2, 5, 2) in path

    def test_blocked_by_closed_door(self) -> None:
        """Pathfinder cannot traverse a closed door (block_state=1)."""
        grid = VoxelGrid(width=10, depth=10, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        for y in range(10):
            grid.grid[2, y, 2] = VOXEL_AIR
        # Place a closed door blocking the only path
        grid.grid[2, 5, 2] = VOXEL_DOOR
        grid.set_block_state(2, 5, 2, 1)  # Closed
        pf = PrototypePathfinder(grid)
        path = pf.find_path((2, 0, 2), (2, 9, 2))
        assert path is None

    def test_blocked_by_solid(self) -> None:
        """Pathfinder cannot traverse stone blocks."""
        grid = VoxelGrid(width=10, depth=10, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        for y in range(10):
            grid.grid[2, y, 2] = VOXEL_AIR
        # Block the corridor with stone
        grid.grid[2, 5, 2] = VOXEL_STONE
        pf = PrototypePathfinder(grid)
        path = pf.find_path((2, 0, 2), (2, 9, 2))
        assert path is None


class TestPrototypeIntruderAI:
    """Verify wave spawning and intruder behavior."""

    def test_no_spawn_before_interval(
        self, event_bus: EventBus, proto_grid: VoxelGrid,
    ) -> None:
        """No intruders should spawn before SPAWN_INTERVAL ticks."""
        pathfinder = PrototypePathfinder(proto_grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP)
        ai = PrototypeIntruderAI(event_bus, proto_grid, pathfinder, core)

        # Tick up to just before first spawn
        for t in range(1, SPAWN_INTERVAL):
            event_bus.publish("tick", tick=t)
        assert len(ai.intruders) == 0

    def test_first_wave_spawns_one(
        self, event_bus: EventBus, proto_grid: VoxelGrid,
    ) -> None:
        """First wave at tick SPAWN_INTERVAL spawns 1 intruder."""
        pathfinder = PrototypePathfinder(proto_grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP)
        ai = PrototypeIntruderAI(event_bus, proto_grid, pathfinder, core)

        event_bus.publish("tick", tick=SPAWN_INTERVAL)
        assert len(ai.intruders) == 1
        assert ai.intruders[0].state == IntruderState.ADVANCING

    def test_second_wave_spawns_two(
        self, event_bus: EventBus, proto_grid: VoxelGrid,
    ) -> None:
        """Second wave at tick 2*SPAWN_INTERVAL spawns 2 more intruders."""
        pathfinder = PrototypePathfinder(proto_grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP)
        ai = PrototypeIntruderAI(event_bus, proto_grid, pathfinder, core)

        event_bus.publish("tick", tick=SPAWN_INTERVAL)
        event_bus.publish("tick", tick=2 * SPAWN_INTERVAL)
        assert len(ai.intruders) == 3  # 1 + 2

    def test_intruders_have_paths(
        self, event_bus: EventBus, proto_grid: VoxelGrid,
    ) -> None:
        """Spawned intruders get a path to the core."""
        pathfinder = PrototypePathfinder(proto_grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP)
        ai = PrototypeIntruderAI(event_bus, proto_grid, pathfinder, core)

        event_bus.publish("tick", tick=SPAWN_INTERVAL)
        intruder = ai.intruders[0]
        assert intruder.path is not None
        assert len(intruder.path) > 0

    def test_game_over_stops_spawning(
        self, event_bus: EventBus, proto_grid: VoxelGrid,
    ) -> None:
        """After game_over, no more spawning happens."""
        pathfinder = PrototypePathfinder(proto_grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP)
        ai = PrototypeIntruderAI(event_bus, proto_grid, pathfinder, core)

        event_bus.publish("game_over", reason="core_destroyed")
        event_bus.publish("tick", tick=SPAWN_INTERVAL)
        assert len(ai.intruders) == 0

    def test_intruder_advances_toward_core(
        self, event_bus: EventBus, proto_grid: VoxelGrid,
    ) -> None:
        """Intruder moves along its path over ticks."""
        pathfinder = PrototypePathfinder(proto_grid)
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP)
        ai = PrototypeIntruderAI(event_bus, proto_grid, pathfinder, core)

        event_bus.publish("tick", tick=SPAWN_INTERVAL)
        intruder = ai.intruders[0]
        start_pos = intruder.pos

        # Tick enough times for it to move at least once
        move_interval = intruder.effective_move_interval
        for t in range(SPAWN_INTERVAL + 1, SPAWN_INTERVAL + 1 + move_interval * 5):
            event_bus.publish("tick", tick=t)

        assert intruder.pos != start_pos, "Intruder should have moved"


class TestIntruderCoreAttack:
    """Verify intruder attacks the core when adjacent."""

    def test_intruder_damages_core(self, event_bus: EventBus) -> None:
        """An intruder next to the core in ATTACKING state damages it."""
        grid = VoxelGrid(width=10, depth=10, height=20)
        grid.grid[:, :, :] = VOXEL_STONE
        # Small room around core
        cz = 10
        cx, cy = 5, 5
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                grid.grid[cx + dx, cy + dy, cz] = VOXEL_AIR
        grid.grid[cx, cy, cz] = VOXEL_CORE

        core = DungeonCore(event_bus, cx, cy, cz, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)

        # Manually create an intruder adjacent to core
        intruder = Intruder(
            intruder_id=99,
            x=cx - 1, y=cy, z=cz,
            archetype=EXPLORER,
            objective=IntruderObjective.DESTROY_CORE,
            personal_map=PersonalMap(),
        )
        intruder.state = IntruderState.ATTACKING
        intruder.ticks_since_attack = 0
        ai.intruders.append(intruder)

        # Tick enough for one attack (attack_interval = 20 for EXPLORER)
        for t in range(1, intruder.attack_interval + 1):
            event_bus.publish("tick", tick=t)

        assert core.hp < 100, "Core should have taken damage"
