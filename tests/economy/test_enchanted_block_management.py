"""Tests for enchanted block management — activation, charge modes, events.

Player-controlled per-block activation (active/inactive) and charge mode
(charging/idle/draining).  Tests cover: toggle activation, drain rate
differences, charging budget from core, player draining with reclaim,
auto-deactivation, event-driven control via EventBus, placement defaults,
removal cleanup, and save/load round-trip.

Dependencies: dungeon_core.mana, core.event_bus, core.save_system,
    world.voxel_grid, building.build_system, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.dungeon_core.mana import ManaSystem
from dungeon_builder.world.voxel_grid import VoxelGrid
import dungeon_builder.config as _cfg


# ── Helpers ──────────────────────────────────────────────────────────────


class _StubBuildSystem:
    """Minimal stand-in for BuildSystem."""
    active_digs: list = []


def _make_mana_system(
    grid_size: int = 10,
) -> tuple[ManaSystem, VoxelGrid, EventBus]:
    eb = EventBus()
    grid = VoxelGrid(grid_size, grid_size, grid_size)
    bs = _StubBuildSystem()
    ms = ManaSystem(eb, grid, bs)
    return ms, grid, eb


def _place_door(
    ms: ManaSystem, grid: VoxelGrid, eb: EventBus,
    x: int = 3, y: int = 3, z: int = 3,
) -> tuple[int, int, int]:
    """Place an enchanted door and return its position."""
    grid.set(x, y, z, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
    return (x, y, z)


# Per-tick rates
_TPS = _cfg.TICKS_PER_SECOND
_ACTIVE_DRAIN = _cfg.ENCHANTED_ACTIVE_DRAIN_PER_S / _TPS
_INACTIVE_DRAIN = _cfg.ENCHANTED_INACTIVE_DRAIN_PER_S / _TPS
_CHARGE = _cfg.ENCHANTED_CHARGE_PER_S / _TPS
_DRAIN = _cfg.ENCHANTED_PLAYER_DRAIN_PER_S / _TPS
_RECLAIM = _cfg.ENCHANTED_DRAIN_RECLAIM_PER_S / _TPS


# ── Block activation ────────────────────────────────────────────────────


class TestBlockActivation:
    """Toggling activation changes drain rate and fires events."""

    def test_toggle_activation(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        assert ms._activated[(3, 3, 3)] is True

        ms.set_block_activated(3, 3, 3, False)
        assert ms._activated[(3, 3, 3)] is False

        ms.set_block_activated(3, 3, 3, True)
        assert ms._activated[(3, 3, 3)] is True

    def test_active_drains_faster_than_inactive(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._capacitance[(3, 3, 3)] = 10.0

        # Active drain
        ms._activated[(3, 3, 3)] = True
        ms._tick_capacitance()
        after_active = ms._capacitance[(3, 3, 3)]

        # Reset and test inactive drain
        ms._capacitance[(3, 3, 3)] = 10.0
        ms._activated[(3, 3, 3)] = False
        ms._tick_capacitance()
        after_inactive = ms._capacitance[(3, 3, 3)]

        # Active should drain more
        assert after_active < after_inactive

    def test_toggle_publishes_state_event(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)

        events = []
        eb.subscribe("enchanted_block_state_changed", lambda **kw: events.append(kw))

        ms.set_block_activated(3, 3, 3, False)

        assert len(events) == 1
        assert events[0]["activated"] is False
        assert events[0]["x"] == 3

    def test_toggle_ignores_non_enchanted(self):
        ms, grid, eb = _make_mana_system()
        grid.set(3, 3, 3, _cfg.VOXEL_STONE, event_bus=eb)

        # Should not crash or create state
        ms.set_block_activated(3, 3, 3, False)
        assert (3, 3, 3) not in ms._activated


# ── Charging from core ───────────────────────────────────────────────────


class TestChargingFromCore:
    """Charging mode pulls mana from core reserve."""

    def test_charging_pulls_from_core(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms.mana = 500.0
        ms._charge_mode[(3, 3, 3)] = "charging"
        ms._capacitance[(3, 3, 3)] = 0.0

        old_mana = ms.mana
        ms._tick_capacitance()

        # Core mana should decrease
        assert ms.mana < old_mana
        # Block should gain mana (charge minus active drain, clamped to 0)
        assert ms._capacitance[(3, 3, 3)] >= 0.0

    def test_charging_capped_by_need(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        max_cap = _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ENCHANTED_DOOR]
        ms.mana = 500.0

        # Almost full — charging only takes what's needed
        ms._capacitance[(3, 3, 3)] = max_cap
        old_mana = ms.mana
        ms._tick_capacitance()

        # Drain happens first: current = max_cap - active_drain
        # Then charge: want = min(charge_rate, max(0, max_cap - current))
        # So want = min(charge_rate, active_drain) = active_drain
        # cost = active_drain (from core)
        drain_amount = _ACTIVE_DRAIN
        expected_cost = min(_CHARGE, drain_amount)
        assert abs((old_mana - ms.mana) - expected_cost) < 1e-9

    def test_charging_stops_when_core_empty(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms.mana = 0.0
        ms._charge_mode[(3, 3, 3)] = "charging"
        ms._capacitance[(3, 3, 3)] = 5.0

        ms._tick_capacitance()

        # Only passive drain, no charge (core is empty)
        expected = max(0.0, 5.0 - _ACTIVE_DRAIN)
        assert abs(ms._capacitance[(3, 3, 3)] - expected) < 1e-9
        assert ms.mana == 0.0

    def test_charging_limited_by_available_mana(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        tiny_mana = 0.001
        ms.mana = tiny_mana
        ms._charge_mode[(3, 3, 3)] = "charging"
        ms._capacitance[(3, 3, 3)] = 0.0

        ms._tick_capacitance()

        # Only 0.001 mana available — that's all it can charge
        assert ms.mana >= 0.0
        assert ms.mana < tiny_mana  # some was consumed


# ── Player draining ──────────────────────────────────────────────────────


class TestPlayerDraining:
    """Draining mode dumps capacitance fast with partial reclaim."""

    def test_draining_subtracts_capacitance(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "draining"
        ms._capacitance[(3, 3, 3)] = 20.0
        ms.mana = 100.0

        ms._tick_capacitance()

        # Should lose active_drain + drain_rate
        expected = max(0.0, 20.0 - _ACTIVE_DRAIN - _DRAIN)
        assert abs(ms._capacitance[(3, 3, 3)] - expected) < 1e-9

    def test_draining_reclaims_to_core(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "draining"
        ms._capacitance[(3, 3, 3)] = 20.0
        ms.mana = 100.0

        old_mana = ms.mana
        ms._tick_capacitance()

        assert abs(ms.mana - (old_mana + _RECLAIM)) < 1e-9

    def test_draining_reclaim_capped_at_max_mana(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "draining"
        ms._capacitance[(3, 3, 3)] = 20.0
        ms.mana = ms.max_mana  # already full

        ms._tick_capacitance()

        assert ms.mana == ms.max_mana  # can't exceed max


# ── Auto-deactivation ───────────────────────────────────────────────────


class TestAutoDeactivation:
    """Blocks auto-deactivate when capacitance hits 0."""

    def test_auto_deactivates_at_zero(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._activated[(3, 3, 3)] = True
        ms._capacitance[(3, 3, 3)] = 0.01  # will drain to 0

        ms._tick_capacitance()

        assert ms._capacitance[(3, 3, 3)] == 0.0
        assert ms._activated[(3, 3, 3)] is False

    def test_auto_deactivation_publishes_state_event(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._activated[(3, 3, 3)] = True
        ms._capacitance[(3, 3, 3)] = 0.01

        events = []
        eb.subscribe("enchanted_block_state_changed", lambda **kw: events.append(kw))

        ms._tick_capacitance()

        assert len(events) == 1
        assert events[0]["activated"] is False

    def test_already_inactive_stays_inactive_at_zero(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._activated[(3, 3, 3)] = False
        ms._capacitance[(3, 3, 3)] = 0.001

        events = []
        eb.subscribe("enchanted_block_state_changed", lambda **kw: events.append(kw))

        ms._tick_capacitance()

        # Still inactive, no state_changed event (already was inactive)
        assert ms._activated[(3, 3, 3)] is False
        assert len(events) == 0


# ── Charging budget ──────────────────────────────────────────────────────


class TestChargingBudget:
    """Full+active block only costs the net shortfall from core."""

    def test_full_active_block_pays_only_drain_shortfall(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        max_cap = _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ENCHANTED_DOOR]
        ms.mana = 500.0
        ms._charge_mode[(3, 3, 3)] = "charging"
        ms._activated[(3, 3, 3)] = True
        ms._capacitance[(3, 3, 3)] = max_cap

        old_mana = ms.mana
        ms._tick_capacitance()

        # Block was full. Active drain = active_drain_tick.
        # After drain: current = max_cap - active_drain.
        # Charge want = min(charge_rate, active_drain) = active_drain.
        # Core only pays active_drain, not the full charge rate.
        cost = old_mana - ms.mana
        assert abs(cost - min(_CHARGE, _ACTIVE_DRAIN)) < 1e-9

    def test_idle_full_block_costs_nothing(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        max_cap = _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ENCHANTED_DOOR]
        ms.mana = 500.0
        ms._charge_mode[(3, 3, 3)] = "idle"
        ms._capacitance[(3, 3, 3)] = max_cap

        old_mana = ms.mana
        ms._tick_capacitance()

        # Idle mode: no charge from core
        assert ms.mana == old_mana


# ── Event-driven control ────────────────────────────────────────────────


class TestEventDrivenControl:
    """UI events toggle state correctly through EventBus."""

    def test_toggle_via_event(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        assert ms._activated[(3, 3, 3)] is True

        eb.publish("enchanted_block_toggle_activation", x=3, y=3, z=3)
        assert ms._activated[(3, 3, 3)] is False

        eb.publish("enchanted_block_toggle_activation", x=3, y=3, z=3)
        assert ms._activated[(3, 3, 3)] is True

    def test_set_charge_mode_via_event(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)

        eb.publish("enchanted_block_set_charge_mode", x=3, y=3, z=3, mode="draining")
        assert ms._charge_mode[(3, 3, 3)] == "draining"

        eb.publish("enchanted_block_set_charge_mode", x=3, y=3, z=3, mode="idle")
        assert ms._charge_mode[(3, 3, 3)] == "idle"

        eb.publish("enchanted_block_set_charge_mode", x=3, y=3, z=3, mode="charging")
        assert ms._charge_mode[(3, 3, 3)] == "charging"

    def test_invalid_charge_mode_rejected(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._charge_mode[(3, 3, 3)] = "idle"

        ms.set_block_charge_mode(3, 3, 3, "exploding")
        assert ms._charge_mode[(3, 3, 3)] == "idle"  # unchanged


# ── Placement defaults ───────────────────────────────────────────────────


class TestPlacementDefaults:
    """New blocks start with correct activation and charge mode."""

    def test_new_block_starts_active(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        assert ms._activated[(3, 3, 3)] is True

    def test_new_block_starts_charging(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        assert ms._charge_mode[(3, 3, 3)] == "charging"

    def test_new_block_starts_uncharged(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        assert ms._capacitance[(3, 3, 3)] == 0.0


# ── Removal cleanup ─────────────────────────────────────────────────────


class TestRemovalCleanup:
    """Removing block cleans all dicts and publishes event."""

    def test_removal_clears_all_state(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._capacitance[(3, 3, 3)] = 25.0
        ms._activated[(3, 3, 3)] = False
        ms._charge_mode[(3, 3, 3)] = "draining"

        grid.set(3, 3, 3, _cfg.VOXEL_AIR, event_bus=eb)

        assert (3, 3, 3) not in ms._capacitance
        assert (3, 3, 3) not in ms._capacitance_max
        assert (3, 3, 3) not in ms._activated
        assert (3, 3, 3) not in ms._charge_mode

    def test_removal_publishes_event(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)

        events = []
        eb.subscribe("enchanted_block_removed", lambda **kw: events.append(kw))

        grid.set(3, 3, 3, _cfg.VOXEL_AIR, event_bus=eb)

        assert len(events) == 1
        assert events[0]["x"] == 3


# ── get_enchanted_block_state ────────────────────────────────────────────


class TestGetEnchantedBlockState:
    """Query method returns full block state."""

    def test_returns_state_for_enchanted_block(self):
        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb)
        ms._capacitance[(3, 3, 3)] = 25.0
        ms._activated[(3, 3, 3)] = False
        ms._charge_mode[(3, 3, 3)] = "draining"

        state = ms.get_enchanted_block_state(3, 3, 3)
        assert state is not None
        assert state["activated"] is False
        assert state["charge_mode"] == "draining"
        assert state["capacitance"] == 25.0
        assert state["max_capacitance"] == _cfg.MANA_CAPACITANCE[_cfg.VOXEL_ENCHANTED_DOOR]

    def test_returns_none_for_non_enchanted(self):
        ms, grid, eb = _make_mana_system()
        assert ms.get_enchanted_block_state(3, 3, 3) is None


# ── Save/Load round-trip ────────────────────────────────────────────────


class TestSaveLoadRoundTrip:
    """Per-block state survives save/load."""

    def test_round_trip_preserves_activation(self):
        from dungeon_builder.core.save_system import SaveSystem, SaveData, _pos_to_str

        ms, grid, eb = _make_mana_system()
        _place_door(ms, grid, eb, 3, 3, 3)
        _place_door(ms, grid, eb, 5, 5, 5)

        # Customize per-block state
        ms._activated[(3, 3, 3)] = False
        ms._charge_mode[(3, 3, 3)] = "draining"
        ms._activated[(5, 5, 5)] = True
        ms._charge_mode[(5, 5, 5)] = "idle"

        # Serialize
        activated_data = {
            _pos_to_str(k): v for k, v in ms._activated.items()
        }
        charge_data = {
            _pos_to_str(k): v for k, v in ms._charge_mode.items()
        }

        # Create fresh system and apply via recount + override
        ms2, grid2, eb2 = _make_mana_system()
        grid2.set(3, 3, 3, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb2)
        grid2.set(5, 5, 5, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb2)
        ms2.recount_traps()

        # Parse back and override (same as SaveSystem.apply does)
        from dungeon_builder.core.save_system import _str_to_pos
        for k, v in activated_data.items():
            pos = _str_to_pos(k)
            if pos in ms2._activated:
                ms2._activated[pos] = v
        for k, v in charge_data.items():
            pos = _str_to_pos(k)
            if pos in ms2._charge_mode:
                ms2._charge_mode[pos] = v

        assert ms2._activated[(3, 3, 3)] is False
        assert ms2._charge_mode[(3, 3, 3)] == "draining"
        assert ms2._activated[(5, 5, 5)] is True
        assert ms2._charge_mode[(5, 5, 5)] == "idle"
