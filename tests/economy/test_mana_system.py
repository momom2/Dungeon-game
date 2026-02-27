"""Tests for dungeon_builder.dungeon_core.mana — mana economy system.

Dependencies: dungeon_core.mana, config, core.event_bus, world.voxel_grid,
    building.build_system
Dependents: (none)
"""

import pytest
import numpy as np

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.building.build_system import BuildSystem, DigJob
from dungeon_builder.dungeon_core.mana import ManaSystem
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_ALARM_BELL,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    MANA_BASE_CAPACITY,
    MANA_GENERATION_PER_TICK,
    MANA_DIG_COST_PER_TICK,
    MANA_SOUL_CAPACITY_BONUS,
    MANA_UPKEEP_PER_SECOND,
    MAGICAL_TRAP_TYPES,
    TICKS_PER_SECOND,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def setup():
    """Create EventBus + VoxelGrid + BuildSystem + ManaSystem for tests."""
    eb = EventBus()
    grid = VoxelGrid(width=16, depth=16, height=8)
    grid.grid[:] = VOXEL_STONE
    grid.grid[:, :, 0] = VOXEL_AIR
    # Mark all as claimed so soul capture works
    grid.claimed[:] = True
    bs = BuildSystem(eb, grid)
    ms = ManaSystem(eb, grid, bs)
    return eb, grid, bs, ms


# ── TestManaGeneration ────────────────────────────────────────────────

class TestManaGeneration:
    def test_starting_mana_is_zero(self, setup):
        _, _, _, ms = setup
        assert ms.mana == 0.0

    def test_starting_max_mana(self, setup):
        _, _, _, ms = setup
        assert ms.max_mana == float(MANA_BASE_CAPACITY)

    def test_mana_increases_per_tick(self, setup):
        eb, _, _, ms = setup
        eb.publish("tick", tick=1)
        assert ms.mana == pytest.approx(MANA_GENERATION_PER_TICK)

    def test_mana_caps_at_max(self, setup):
        eb, _, _, ms = setup
        ms.mana = float(MANA_BASE_CAPACITY) - 1.0
        eb.publish("tick", tick=1)
        assert ms.mana == float(MANA_BASE_CAPACITY)

    def test_generation_continues_at_cap(self, setup):
        eb, _, _, ms = setup
        ms.mana = float(MANA_BASE_CAPACITY)
        eb.publish("tick", tick=1)
        assert ms.mana == float(MANA_BASE_CAPACITY)


# ── TestManaDrains ────────────────────────────────────────────────────

class TestManaDrains:
    def test_active_digs_drain_mana(self, setup):
        eb, grid, bs, ms = setup
        ms.mana = 100.0
        # Add an active dig manually
        bs.active_digs.append(DigJob(5, 5, 1, 100))
        eb.publish("tick", tick=1)
        expected = 100.0 + MANA_GENERATION_PER_TICK - MANA_DIG_COST_PER_TICK
        assert ms.mana == pytest.approx(expected)

    def test_multiple_digs_drain(self, setup):
        eb, grid, bs, ms = setup
        ms.mana = 100.0
        bs.active_digs.append(DigJob(5, 5, 1, 100))
        bs.active_digs.append(DigJob(6, 6, 1, 100))
        bs.active_digs.append(DigJob(7, 7, 1, 100))
        eb.publish("tick", tick=1)
        expected = 100.0 + MANA_GENERATION_PER_TICK - 3 * MANA_DIG_COST_PER_TICK
        assert ms.mana == pytest.approx(expected)

    def test_trap_upkeep_drains_mana(self, setup):
        eb, grid, _, ms = setup
        ms.mana = 100.0
        # Place a pressure plate on the grid
        grid.set(5, 5, 0, VOXEL_PRESSURE_PLATE)
        eb.publish("voxel_changed", x=5, y=5, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_PRESSURE_PLATE)
        eb.publish("tick", tick=1)
        upkeep_per_tick = MANA_UPKEEP_PER_SECOND[VOXEL_PRESSURE_PLATE] / TICKS_PER_SECOND
        expected = 100.0 + MANA_GENERATION_PER_TICK - upkeep_per_tick
        assert ms.mana == pytest.approx(expected)

    def test_mana_floors_at_zero(self, setup):
        eb, grid, bs, ms = setup
        ms.mana = 0.1
        # Add many active digs to overwhelm generation
        for i in range(100):
            bs.active_digs.append(DigJob(i % 16, i // 16, 1, 100))
        eb.publish("tick", tick=1)
        assert ms.mana == 0.0

    def test_queued_digs_dont_drain(self, setup):
        """Queued (but not yet active) digs don't cost mana.

        We verify by calling ManaSystem._on_tick directly to avoid the
        BuildSystem promoting the queued dig during the same tick event.
        """
        eb, grid, bs, ms = setup
        ms.mana = 100.0
        # Add to dig_queue, not active_digs
        bs.dig_queue.append(DigJob(5, 5, 1, 100))
        # Call mana tick directly (bypass BuildSystem promotion)
        ms._on_tick(tick=1)
        expected = 100.0 + MANA_GENERATION_PER_TICK
        assert ms.mana == pytest.approx(expected)


# ── TestManaPower ─────────────────────────────────────────────────────

class TestManaPower:
    def test_digs_powered_initially(self, setup):
        _, _, _, ms = setup
        assert ms.digs_powered is True

    def test_traps_powered_initially(self, setup):
        _, _, _, ms = setup
        assert ms.traps_powered is True

    def test_power_lost_when_mana_depleted(self, setup):
        eb, grid, bs, ms = setup
        ms.mana = 0.0
        # Add enough digs to overwhelm generation
        for i in range(100):
            bs.active_digs.append(DigJob(i % 16, i // 16, 1, 100))
        eb.publish("tick", tick=1)
        assert ms.digs_powered is False
        assert ms.traps_powered is False

    def test_power_restored_when_mana_returns(self, setup):
        eb, grid, bs, ms = setup
        ms.digs_powered = False
        ms.traps_powered = False
        ms.mana = 500.0
        eb.publish("tick", tick=1)
        assert ms.digs_powered is True
        assert ms.traps_powered is True

    def test_mana_power_changed_event_fires(self, setup):
        eb, grid, bs, ms = setup
        events = []
        eb.subscribe("mana_power_changed", lambda **kw: events.append(kw))
        ms.mana = 0.0
        for i in range(100):
            bs.active_digs.append(DigJob(i % 16, i // 16, 1, 100))
        eb.publish("tick", tick=1)
        assert len(events) == 1
        assert events[0]["digs_powered"] is False


# ── TestSoulCapture ───────────────────────────────────────────────────

class _FakeIntruder:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class TestSoulCapture:
    def test_soul_on_claimed_territory(self, setup):
        eb, grid, _, ms = setup
        intruder = _FakeIntruder(5, 5, 0)
        eb.publish("intruder_died", intruder=intruder)
        assert ms.souls == 1
        assert ms.max_mana == float(MANA_BASE_CAPACITY + MANA_SOUL_CAPACITY_BONUS)

    def test_no_soul_outside_claimed(self, setup):
        eb, grid, _, ms = setup
        grid.claimed[:] = False
        intruder = _FakeIntruder(5, 5, 0)
        eb.publish("intruder_died", intruder=intruder)
        assert ms.souls == 0
        assert ms.max_mana == float(MANA_BASE_CAPACITY)

    def test_multiple_souls_stack(self, setup):
        eb, grid, _, ms = setup
        for i in range(5):
            eb.publish("intruder_died", intruder=_FakeIntruder(i, i, 0))
        assert ms.souls == 5
        assert ms.max_mana == float(
            MANA_BASE_CAPACITY + 5 * MANA_SOUL_CAPACITY_BONUS
        )

    def test_soul_captured_event(self, setup):
        eb, grid, _, ms = setup
        events = []
        eb.subscribe("soul_captured", lambda **kw: events.append(kw))
        eb.publish("intruder_died", intruder=_FakeIntruder(5, 5, 0))
        assert len(events) == 1
        assert events[0]["souls"] == 1


# ── TestManaSpend ─────────────────────────────────────────────────────

class TestManaSpend:
    def test_can_spend(self, setup):
        _, _, _, ms = setup
        ms.mana = 100.0
        assert ms.can_spend(50.0) is True
        assert ms.can_spend(200.0) is False

    def test_spend_deducts(self, setup):
        _, _, _, ms = setup
        ms.mana = 100.0
        assert ms.spend(40.0) is True
        assert ms.mana == pytest.approx(60.0)

    def test_spend_fails_when_insufficient(self, setup):
        _, _, _, ms = setup
        ms.mana = 10.0
        assert ms.spend(50.0) is False
        assert ms.mana == pytest.approx(10.0)


# ── TestTrapCounting ──────────────────────────────────────────────────

class TestTrapCounting:
    def test_placing_trap_increments(self, setup):
        eb, grid, _, ms = setup
        eb.publish("voxel_changed", x=5, y=5, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_PRESSURE_PLATE)
        assert ms._trap_counts.get(VOXEL_PRESSURE_PLATE, 0) == 1

    def test_removing_trap_decrements(self, setup):
        eb, grid, _, ms = setup
        eb.publish("voxel_changed", x=5, y=5, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_PRESSURE_PLATE)
        eb.publish("voxel_changed", x=5, y=5, z=0,
                    old_type=VOXEL_PRESSURE_PLATE, new_type=VOXEL_AIR)
        assert ms._trap_counts.get(VOXEL_PRESSURE_PLATE, 0) == 0

    def test_non_magical_blocks_dont_affect_count(self, setup):
        eb, grid, _, ms = setup
        eb.publish("voxel_changed", x=5, y=5, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_STONE)
        assert len(ms._trap_counts) == 0

    def test_per_type_upkeep(self, setup):
        eb, grid, _, ms = setup
        # Place different trap types
        eb.publish("voxel_changed", x=1, y=1, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_PRESSURE_PLATE)
        eb.publish("voxel_changed", x=2, y=2, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_ALARM_BELL)
        upkeep = ms.get_trap_upkeep_per_second()
        expected = (
            MANA_UPKEEP_PER_SECOND[VOXEL_PRESSURE_PLATE]
            + MANA_UPKEEP_PER_SECOND[VOXEL_ALARM_BELL]
        )
        assert upkeep == pytest.approx(expected)

    def test_recount_traps(self, setup):
        _, grid, _, ms = setup
        # Place traps directly in the grid (simulating save/load)
        grid.grid[3, 3, 0] = VOXEL_ENCHANTED_DOOR
        grid.grid[4, 4, 0] = VOXEL_ENCHANTED_DOOR
        grid.grid[5, 5, 0] = VOXEL_GOLD_BAIT
        ms.recount_traps()
        assert ms._trap_counts.get(VOXEL_ENCHANTED_DOOR, 0) == 2
        assert ms._trap_counts.get(VOXEL_GOLD_BAIT, 0) == 1


# ── TestGetStats ──────────────────────────────────────────────────────

class TestGetStats:
    def test_stats_reflect_state(self, setup):
        eb, grid, _, ms = setup
        ms.mana = 500.0
        ms.souls = 3
        ms.max_mana = float(MANA_BASE_CAPACITY + 3 * MANA_SOUL_CAPACITY_BONUS)
        eb.publish("voxel_changed", x=1, y=1, z=0,
                    old_type=VOXEL_AIR, new_type=VOXEL_PRESSURE_PLATE)
        stats = ms.get_stats()
        assert stats["mana"] == 500.0
        assert stats["souls"] == 3
        assert stats["traps"] == 1
        assert stats["digs_powered"] is True
