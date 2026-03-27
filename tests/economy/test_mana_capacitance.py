"""Tests for mana capacitance — per-block local mana storage.

Enchanted blocks store mana locally.  When in "charging" mode, they
pull from the core reserve.  Active blocks drain faster than inactive
ones.  Sprites inject mana directly.

Dependencies: dungeon_core.mana, core.event_bus, world.voxel_grid,
    building.build_system, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.dungeon_core.mana import ManaSystem
from dungeon_builder.world.voxel_grid import VoxelGrid
import dungeon_builder.config as _cfg


# ── Helpers ──────────────────────────────────────────────────────────────


class _StubBuildSystem:
    """Minimal stand-in for BuildSystem (only ``active_digs`` is queried)."""
    active_digs: list = []


def _make_mana_system(
    grid_size: int = 10,
) -> tuple[ManaSystem, VoxelGrid, EventBus]:
    """Create a ManaSystem with a small grid for testing."""
    eb = EventBus()
    grid = VoxelGrid(grid_size, grid_size, grid_size)
    bs = _StubBuildSystem()
    ms = ManaSystem(eb, grid, bs)
    return ms, grid, eb


# Per-tick rates (derived from per-second constants)
_ACTIVE_DRAIN_TICK = _cfg.ENCHANTED_ACTIVE_DRAIN_PER_S / _cfg.TICKS_PER_SECOND
_INACTIVE_DRAIN_TICK = _cfg.ENCHANTED_INACTIVE_DRAIN_PER_S / _cfg.TICKS_PER_SECOND
_CHARGE_TICK = _cfg.ENCHANTED_CHARGE_PER_S / _cfg.TICKS_PER_SECOND
_DRAIN_TICK = _cfg.ENCHANTED_PLAYER_DRAIN_PER_S / _cfg.TICKS_PER_SECOND
_RECLAIM_TICK = _cfg.ENCHANTED_DRAIN_RECLAIM_PER_S / _cfg.TICKS_PER_SECOND


# ── Capacitance tracking ────────────────────────────────────────────────


class TestCapacitanceVoxelTracking:
    """Placing/removing enchanted blocks updates capacitance maps."""

    def test_placing_enchanted_door_tracks_capacitance(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        assert ms._capacitance_max.get((3, 3, 3)) == _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ENCHANTED_DOOR]
        assert ms._capacitance.get((3, 3, 3)) == 0.0  # starts uncharged

    def test_removing_enchanted_block_clears_capacitance(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        assert (3, 3, 3) in ms._capacitance_max
        grid.set(3, 3, 3, _cfg.VOXEL_AIR, event_bus=eb)
        assert (3, 3, 3) not in ms._capacitance_max
        assert (3, 3, 3) not in ms._capacitance

    def test_non_enchanted_block_not_tracked(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_STONE, event_bus=eb)
        assert (3, 3, 3) not in ms._capacitance_max

    def test_placement_initializes_activation_and_charge_mode(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        assert ms._activated[(3, 3, 3)] is True
        assert ms._charge_mode[(3, 3, 3)] == "charging"

    def test_removal_cleans_activation_and_charge_mode(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        grid.set(3, 3, 3, _cfg.VOXEL_AIR, event_bus=eb)
        assert (3, 3, 3) not in ms._activated
        assert (3, 3, 3) not in ms._charge_mode


# ── Capacitance charging ────────────────────────────────────────────────


class TestCapacitanceCharging:
    """Blocks charge when in charging mode."""

    def test_charges_when_in_charging_mode(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.mana = 500.0

        # Block starts in charging mode and active
        ms._tick_capacitance()

        stored = ms._capacitance[(3, 3, 3)]
        # Net: charge_tick - active_drain_tick
        expected = _CHARGE_TICK - _ACTIVE_DRAIN_TICK
        assert abs(stored - expected) < 1e-9

    def test_charges_up_to_max(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_PRESSURE_PLATE, event_bus=eb)
        max_cap = _cfg.MANA_CAPACITANCE[_cfg.VOXEL_PRESSURE_PLATE]
        ms.mana = 500.0

        # Set capacitance just below max (within one charge tick)
        ms._capacitance[(3, 3, 3)] = max_cap - 0.001
        ms._tick_capacitance()

        assert ms._capacitance[(3, 3, 3)] == max_cap

    def test_does_not_exceed_max(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ALARM_BELL, event_bus=eb)
        max_cap = _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ALARM_BELL]
        ms.mana = 500.0

        # Already at max — charging compensates drain at most
        ms._capacitance[(3, 3, 3)] = max_cap
        ms._tick_capacitance()

        assert ms._capacitance[(3, 3, 3)] <= max_cap

    def test_no_charge_when_idle_mode(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.mana = 500.0
        ms._charge_mode[(3, 3, 3)] = "idle"

        ms._capacitance[(3, 3, 3)] = 10.0
        old_mana = ms.mana
        ms._tick_capacitance()

        # Only passive drain, no charge from core
        assert ms._capacitance[(3, 3, 3)] == 10.0 - _ACTIVE_DRAIN_TICK
        assert ms.mana == old_mana  # core mana unchanged


# ── Capacitance draining ────────────────────────────────────────────────


class TestCapacitanceDraining:
    """Blocks drain based on activation state."""

    def test_active_drain_rate(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 10.0
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._activated[(3, 3, 3)] = True

        ms._tick_capacitance()

        assert abs(ms._capacitance[(3, 3, 3)] - (10.0 - _ACTIVE_DRAIN_TICK)) < 1e-9

    def test_inactive_drain_rate_slower(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 10.0
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._activated[(3, 3, 3)] = False

        ms._tick_capacitance()

        assert abs(ms._capacitance[(3, 3, 3)] - (10.0 - _INACTIVE_DRAIN_TICK)) < 1e-9
        # Inactive drain is slower than active
        assert _INACTIVE_DRAIN_TICK < _ACTIVE_DRAIN_TICK

    def test_drain_fires_event_at_zero(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 0.01  # Less than drain per tick
        ms._charge_mode[(3, 3, 3)] = "idle"

        events = []
        eb.subscribe("block_capacitance_depleted", lambda **kw: events.append(kw))

        ms._tick_capacitance()

        assert ms._capacitance[(3, 3, 3)] == 0.0
        assert len(events) == 1
        assert events[0]["x"] == 3

    def test_drain_clamps_to_zero(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_PRESSURE_PLATE, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 0.001
        ms._charge_mode[(3, 3, 3)] = "idle"

        ms._tick_capacitance()

        assert ms._capacitance[(3, 3, 3)] == 0.0


# ── Mana injection ──────────────────────────────────────────────────────


class TestCapacitanceInjection:
    """inject_mana adds mana to a block's capacitance."""

    def test_inject_adds_mana(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)

        result = ms.inject_mana(3, 3, 3, 15.0)
        assert result is True
        assert ms._capacitance[(3, 3, 3)] == 15.0

    def test_inject_capped_at_max(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_PRESSURE_PLATE, event_bus=eb)
        max_cap = _cfg.MANA_CAPACITANCE[_cfg.VOXEL_PRESSURE_PLATE]

        result = ms.inject_mana(3, 3, 3, 9999.0)
        assert result is True
        assert ms._capacitance[(3, 3, 3)] == max_cap

    def test_inject_rejected_for_non_enchanted(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_STONE, event_bus=eb)

        result = ms.inject_mana(3, 3, 3, 15.0)
        assert result is False

    def test_inject_stacks_with_existing(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 10.0

        ms.inject_mana(3, 3, 3, 5.0)
        assert ms._capacitance[(3, 3, 3)] == 15.0


# ── is_block_powered ────────────────────────────────────────────────────


class TestIsBlockPowered:
    """is_block_powered returns correct state."""

    def test_powered_when_globally_powered_and_active(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.traps_powered = True
        ms._activated[(3, 3, 3)] = True
        assert ms.is_block_powered(3, 3, 3) is True

    def test_not_powered_when_deactivated(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.traps_powered = True
        ms._activated[(3, 3, 3)] = False
        assert ms.is_block_powered(3, 3, 3) is False

    def test_powered_by_local_capacitance(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 5.0
        ms._activated[(3, 3, 3)] = True
        ms.traps_powered = False

        assert ms.is_block_powered(3, 3, 3) is True

    def test_unpowered_when_no_global_and_no_local(self):
        ms, grid, eb = _make_mana_system()
        ms.traps_powered = False

        assert ms.is_block_powered(3, 3, 3) is False

    def test_unpowered_when_local_drained(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms._capacitance[(3, 3, 3)] = 0.0
        ms._activated[(3, 3, 3)] = True
        ms.traps_powered = False

        assert ms.is_block_powered(3, 3, 3) is False


# ── Recount includes capacitance ────────────────────────────────────────


class TestRecountTrapsIncludesCapacitance:
    """recount_traps rebuilds capacitance maps from the grid."""

    def test_recount_rebuilds_capacitance(self):
        ms, grid, eb = _make_mana_system()
        # Place blocks directly on grid (bypass event)
        grid.grid[3, 3, 3] = _cfg.VOXEL_ENCHANTED_DOOR
        grid.grid[4, 4, 4] = _cfg.VOXEL_PRESSURE_PLATE

        ms.recount_traps()

        assert (3, 3, 3) in ms._capacitance_max
        assert (4, 4, 4) in ms._capacitance_max
        # On load, capacitance starts fully charged
        assert ms._capacitance[(3, 3, 3)] == _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ENCHANTED_DOOR]
        assert ms._capacitance[(4, 4, 4)] == _cfg.MANA_CAPACITANCE[_cfg.VOXEL_PRESSURE_PLATE]

    def test_recount_rebuilds_activation_and_charge_mode(self):
        ms, grid, eb = _make_mana_system()
        grid.grid[3, 3, 3] = _cfg.VOXEL_ENCHANTED_DOOR

        ms.recount_traps()

        assert ms._activated[(3, 3, 3)] is True
        assert ms._charge_mode[(3, 3, 3)] == "idle"
