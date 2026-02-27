"""Tests for the arrow trap system.

Verifies trap firing, cooldown, placement tracking, and intruder kills.
"""

from __future__ import annotations

import pytest

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_CORE,
)
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import EXPLORER, IntruderObjective
from dungeon_builder.intruders.personal_map import PersonalMap

from prototype.config import (
    VOXEL_ARROW_TRAP,
    ARROW_TRAP_DAMAGE,
    ARROW_TRAP_COOLDOWN,
    patch_shared_config,
)
from prototype.intruders import (
    PrototypePathfinder,
    PrototypeIntruderAI,
    ArrowTrapSystem,
)


@pytest.fixture(autouse=True)
def _patched_config() -> None:
    patch_shared_config()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


def _make_test_grid() -> VoxelGrid:
    """Create a 10×10×5 grid with a corridor and core."""
    grid = VoxelGrid(width=10, depth=10, height=5)
    grid.grid[:, :, :] = VOXEL_STONE
    # Air corridor at z=2, x=2, y=0..9
    for y in range(10):
        grid.grid[2, y, 2] = VOXEL_AIR
    # Small core room
    grid.grid[5, 5, 2] = VOXEL_CORE
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            if (dx, dy) != (0, 0):
                grid.grid[5 + dx, 5 + dy, 2] = VOXEL_AIR
    return grid


def _make_intruder(x: int, y: int, z: int, intruder_id: int = 0) -> Intruder:
    return Intruder(
        intruder_id=intruder_id,
        x=x, y=y, z=z,
        archetype=EXPLORER,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=PersonalMap(),
    )


class TestArrowTrapTracking:
    """Verify traps are tracked via voxel_changed events."""

    def test_trap_registered_on_placement(self, event_bus: EventBus) -> None:
        """Placing an arrow trap via voxel_changed adds it to tracking."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )
        assert (1, 3, 2) in traps.trap_positions

    def test_trap_unregistered_on_removal(self, event_bus: EventBus) -> None:
        """Digging out an arrow trap removes it from tracking."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        # Place then remove
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_ARROW_TRAP, new_type=VOXEL_AIR,
        )
        assert (1, 3, 2) not in traps.trap_positions


class TestArrowTrapFiring:
    """Verify trap fires at intruders in adjacent air cells."""

    def test_damages_adjacent_intruder(self, event_bus: EventBus) -> None:
        """Trap at (1,3,2) should damage intruder at (2,3,2) (air cell)."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        # Place trap next to corridor
        grid.grid[1, 3, 2] = VOXEL_ARROW_TRAP
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )

        # Put intruder in adjacent air cell
        intruder = _make_intruder(2, 3, 2)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        original_hp = intruder.hp
        event_bus.publish("tick", tick=1)
        assert intruder.hp == original_hp - ARROW_TRAP_DAMAGE

    def test_cooldown_prevents_rapid_fire(self, event_bus: EventBus) -> None:
        """After firing, trap should be on cooldown and not fire again."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        grid.grid[1, 3, 2] = VOXEL_ARROW_TRAP
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )

        intruder = _make_intruder(2, 3, 2)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        # First tick: fires
        event_bus.publish("tick", tick=1)
        hp_after_first = intruder.hp

        # Second tick: should be on cooldown
        event_bus.publish("tick", tick=2)
        assert intruder.hp == hp_after_first, "Trap should be on cooldown"

    def test_fires_again_after_cooldown(self, event_bus: EventBus) -> None:
        """After cooldown expires, trap fires again."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        grid.grid[1, 3, 2] = VOXEL_ARROW_TRAP
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )

        intruder = _make_intruder(2, 3, 2)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        # First firing
        event_bus.publish("tick", tick=1)
        hp_after_first = intruder.hp

        # Wait out cooldown
        for t in range(2, 2 + ARROW_TRAP_COOLDOWN + 1):
            event_bus.publish("tick", tick=t)

        # Should have fired again
        assert intruder.hp < hp_after_first, "Trap should fire after cooldown"

    def test_does_not_fire_into_stone(self, event_bus: EventBus) -> None:
        """Trap does not fire into solid neighbors."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        # Place trap deep in stone wall — all neighbors are stone
        grid.grid[0, 0, 0] = VOXEL_ARROW_TRAP
        event_bus.publish(
            "voxel_changed", x=0, y=0, z=0,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )

        # Put intruder at (1,0,0) — but that cell is STONE, not air
        intruder = _make_intruder(1, 0, 0)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        original_hp = intruder.hp
        event_bus.publish("tick", tick=1)
        assert intruder.hp == original_hp, "Trap shouldn't fire into stone"


class TestArrowTrapKill:
    """Verify trap can kill an intruder."""

    def test_kills_low_hp_intruder(self, event_bus: EventBus) -> None:
        """Intruder with HP <= ARROW_TRAP_DAMAGE should die."""
        grid = _make_test_grid()
        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        grid.grid[1, 3, 2] = VOXEL_ARROW_TRAP
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )

        intruder = _make_intruder(2, 3, 2)
        intruder.state = IntruderState.ADVANCING
        intruder.hp = ARROW_TRAP_DAMAGE  # Exactly lethal
        ai.intruders.append(intruder)

        died_events = []
        event_bus.subscribe("intruder_died", lambda **kw: died_events.append(kw))

        event_bus.publish("tick", tick=1)
        assert intruder.hp == 0
        assert intruder.state == IntruderState.DEAD
        assert len(died_events) == 1

    def test_multiple_traps_stack(self, event_bus: EventBus) -> None:
        """Multiple traps adjacent to the same intruder all fire."""
        grid = VoxelGrid(width=10, depth=10, height=5)
        grid.grid[:, :, :] = VOXEL_STONE
        # Air at (2,3,2) with traps on both sides
        grid.grid[2, 3, 2] = VOXEL_AIR
        grid.grid[1, 3, 2] = VOXEL_ARROW_TRAP
        grid.grid[3, 3, 2] = VOXEL_ARROW_TRAP

        core = DungeonCore(event_bus, 5, 5, 2, hp=100)
        pathfinder = PrototypePathfinder(grid)
        ai = PrototypeIntruderAI(event_bus, grid, pathfinder, core)
        traps = ArrowTrapSystem(event_bus, grid, ai)

        # Register both traps
        event_bus.publish(
            "voxel_changed", x=1, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )
        event_bus.publish(
            "voxel_changed", x=3, y=3, z=2,
            old_type=VOXEL_STONE, new_type=VOXEL_ARROW_TRAP,
        )

        intruder = _make_intruder(2, 3, 2)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)
        original_hp = intruder.hp

        event_bus.publish("tick", tick=1)
        # Both traps should fire: 2 × ARROW_TRAP_DAMAGE
        assert intruder.hp == original_hp - 2 * ARROW_TRAP_DAMAGE
