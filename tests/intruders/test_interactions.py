"""Tests for intruder micro-interaction system.

All checks use archetype flags and stats (can_fly, can_bash_door,
damage, cunning, etc.) rather than archetype name strings, so new
archetypes work automatically based on their stat block.

Dependencies: intruders.interactions, intruders.archetypes, intruders.agent,
    intruders.personal_map, config
Dependents: (none)
"""

from dataclasses import dataclass

import pytest

from dungeon_builder.intruders.interactions import (
    handle_block,
    InteractionResult,
    InteractionInfo,
)
from dungeon_builder.intruders.archetypes import (
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
    ALL_ARCHETYPES,
    IntruderObjective,
)
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_DOOR,
    VOXEL_SPIKE,
    VOXEL_TREASURE,
    VOXEL_TARP,
    VOXEL_ROLLING_STONE,
    VOXEL_REINFORCED_WALL,
    VOXEL_LAVA,
    VOXEL_WATER,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_STONE,
    SPIKE_DAMAGE,
    ROLLING_STONE_DAMAGE,
    DOOR_BASH_TICKS,
    DOOR_LOCKPICK_TICKS,
    GOLD_BAIT_INTERACT_TICKS,
    HEAT_BEACON_DAMAGE,
    STEAM_VENT_DAMAGE,
    TARP_DETECT_CUNNING,
    TREASURE_GRAB_TICKS,
    VOXEL_ALARM_BELL,
    VOXEL_FLOODGATE,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_IRON_BARS,
    VOXEL_PIPE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_PUMP,
    VOXEL_STEAM_VENT,
)
import dungeon_builder.config as _cfg


def _make(arch, objective=IntruderObjective.DESTROY_CORE):
    return Intruder(1, 0, 0, 0, arch, objective, PersonalMap())


# ── Mock helpers (for new block interaction tests) ────────────────────


@dataclass
class MockArch:
    name: str = "MockIntruder"
    greed: float = 0.5
    can_fly: bool = False
    can_dig: bool = False
    can_bash_door: bool = False
    can_lockpick: bool = False
    arcane_sight_range: int = 0
    trap_detect_range: int = 0
    cunning: float = 0.3
    speed: int = 2
    damage: int = 5


class MockIntruder:
    def __init__(self, **kwargs):
        self.archetype = MockArch(**kwargs)


# ── Air / Slope / Stairs -- always CONTINUE ──────────────────────────


class TestPassThrough:
    @pytest.mark.parametrize("vtype", [VOXEL_AIR, VOXEL_SLOPE, VOXEL_STAIRS])
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_always_continue(self, vtype, arch):
        info = handle_block(_make(arch), vtype, 0)
        assert info.result == InteractionResult.CONTINUE


# ── Door interactions ───────────────────────────────────────────────


class TestDoorInteractions:
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_open_door_continue(self, arch):
        info = handle_block(_make(arch), VOXEL_DOOR, block_state=0)
        assert info.result == InteractionResult.CONTINUE

    def test_bash_ticks_derived_from_damage(self):
        """Door bash ticks = max(1, DOOR_BASH_TICKS - damage // 2)."""
        # Inquisitor: damage=8, can_bash_door=True
        info = handle_block(_make(INQUISITOR), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.INTERACT
        expected_ticks = max(1, DOOR_BASH_TICKS - INQUISITOR.damage // 2)
        assert info.ticks == expected_ticks
        assert info.interaction_type == "bash_door"

    def test_hero_bashes_faster_due_to_high_damage(self):
        """Hero has damage=20, so bash ticks should be lower than Inquisitor."""
        info_hero = handle_block(_make(HERO), VOXEL_DOOR, block_state=1)
        info_inq = handle_block(_make(INQUISITOR), VOXEL_DOOR, block_state=1)
        assert info_hero.result == InteractionResult.INTERACT
        assert info_hero.ticks < info_inq.ticks

    def test_explorer_lockpicks_closed_door(self):
        info = handle_block(_make(EXPLORER), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.INTERACT
        assert info.ticks == DOOR_LOCKPICK_TICKS
        assert info.interaction_type == "lockpick"

    def test_non_basher_non_lockpicker_repaths_closed_door(self):
        # Alchemist: can_bash_door=False, can_lockpick=False
        info = handle_block(_make(ALCHEMIST), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_gloomwarden_repaths_closed_door(self):
        # Gloomwarden: no bash, no lockpick
        info = handle_block(_make(GLOOMWARDEN), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_cartomancer_repaths_closed_door(self):
        info = handle_block(_make(CARTOMANCER), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH


# ── Spike interactions ──────────────────────────────────────────────


class TestSpikeInteractions:
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_retracted_spike_continue(self, arch):
        info = handle_block(_make(arch), VOXEL_SPIKE, block_state=0)
        assert info.result == InteractionResult.CONTINUE

    def test_can_bash_door_types_take_half_damage(self):
        """Intruders with can_bash_door take half spike damage."""
        # Inquisitor has can_bash_door=True
        info = handle_block(_make(INQUISITOR), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE // 2

    def test_hero_takes_half_damage(self):
        """Hero has can_bash_door=True."""
        info = handle_block(_make(HERO), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE // 2

    def test_trap_detect_avoids_spike(self):
        """Intruder with trap_detect_range > 0 detects and avoids spike."""
        # Explorer has trap_detect_range=2
        info = handle_block(_make(EXPLORER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_flyer_flies_over_spike(self):
        # Eidolon has can_fly=True
        info = handle_block(_make(EIDOLON), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.CONTINUE

    def test_regular_intruder_takes_full_damage(self):
        # Alchemist: no fly, no trap_detect, no bash
        info = handle_block(_make(ALCHEMIST), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE

    def test_mole_tamer_takes_full_damage(self):
        # Mole Tamer: no fly, trap_detect_range=0, no bash
        info = handle_block(_make(MOLE_TAMER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE

    def test_cartomancer_takes_full_damage(self):
        info = handle_block(_make(CARTOMANCER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE


# ── Lava interactions ───────────────────────────────────────────────


class TestLavaInteractions:
    def test_flyer_passes_over_lava(self):
        # Eidolon can fly
        info = handle_block(_make(EIDOLON), VOXEL_LAVA, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_non_flyer_dies_in_lava(self):
        for arch in ALL_ARCHETYPES:
            if arch.can_fly:
                continue
            info = handle_block(_make(arch), VOXEL_LAVA, 0)
            assert info.result == InteractionResult.DEATH, (
                f"{arch.name} should die in lava"
            )


# ── Water interactions ──────────────────────────────────────────────


class TestWaterInteractions:
    def test_water_returns_continue(self):
        """Water entry is permitted from interaction layer; deep-water
        handling happens in decision.py."""
        for arch in ALL_ARCHETYPES:
            info = handle_block(_make(arch), VOXEL_WATER, 0)
            assert info.result == InteractionResult.CONTINUE, (
                f"{arch.name} should get CONTINUE for water"
            )


# ── Treasure interactions ───────────────────────────────────────────


class TestTreasureInteractions:
    def test_greedy_intruder_collects(self):
        # Explorer: greed=0.7
        info = handle_block(_make(EXPLORER), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.COLLECT
        assert info.interaction_type == "grab_treasure"

    def test_non_greedy_intruder_ignores(self):
        # Hero: greed=0.0
        info = handle_block(_make(HERO), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_slightly_greedy_collects(self):
        # Inquisitor: greed=0.05 (>0)
        info = handle_block(_make(INQUISITOR), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.COLLECT


# ── Tarp interactions ───────────────────────────────────────────────


class TestTarpInteractions:
    def test_flyer_flies_over(self):
        # Eidolon: can_fly=True
        info = handle_block(_make(EIDOLON), VOXEL_TARP, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_arcane_sight_detects(self):
        # Gloomwarden: arcane_sight_range=3
        info = handle_block(_make(GLOOMWARDEN), VOXEL_TARP, 0)
        assert info.result == InteractionResult.REPATH

    def test_high_cunning_detects(self):
        # Explorer: cunning=0.7 >= TARP_DETECT_CUNNING (0.5)
        info = handle_block(_make(EXPLORER), VOXEL_TARP, 0)
        assert info.result == InteractionResult.REPATH

    def test_low_cunning_falls_through(self):
        # Hero: cunning=0.1, no fly, no arcane sight
        info = handle_block(_make(HERO), VOXEL_TARP, 0)
        assert info.result == InteractionResult.FALL

    def test_inquisitor_falls_through(self):
        # Inquisitor: cunning=0.2 < 0.5, no fly, no arcane
        info = handle_block(_make(INQUISITOR), VOXEL_TARP, 0)
        assert info.result == InteractionResult.FALL


# ── Rolling stone interactions ──────────────────────────────────────


class TestRollingStoneInteractions:
    def test_flyer_flies_over(self):
        info = handle_block(_make(EIDOLON), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_fast_intruder_dodges(self):
        # Explorer: speed=3 >= 3
        info = handle_block(_make(EXPLORER), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_slow_intruder_takes_damage(self):
        # Inquisitor: speed=1 < 3
        info = handle_block(_make(INQUISITOR), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == ROLLING_STONE_DAMAGE

    def test_flying_intruders_immune_to_ground_traps(self):
        """Flying intruders are immune to ground traps: spikes, tarp, rolling stone."""
        for vtype in (VOXEL_SPIKE, VOXEL_TARP, VOXEL_ROLLING_STONE):
            info = handle_block(_make(EIDOLON), vtype, 0)
            assert info.result == InteractionResult.CONTINUE, (
                f"Eidolon should be immune to {vtype}"
            )


# ── Reinforced wall ─────────────────────────────────────────────────


class TestReinforcedWall:
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_always_repath(self, arch):
        info = handle_block(_make(arch), VOXEL_REINFORCED_WALL, 0)
        assert info.result == InteractionResult.REPATH


# ── Other solid blocks ──────────────────────────────────────────────


class TestOtherSolids:
    def test_stone_repaths(self):
        info = handle_block(_make(INQUISITOR), VOXEL_STONE, 0)
        assert info.result == InteractionResult.REPATH


# ======================================================================
# Tests from test_new_block_interactions.py
# ======================================================================


# ── Gold Bait ────────────────────────────────────────────────────────


class TestGoldBait:
    """Gold Bait: REPATH if arcane_sight; COLLECT if greedy; CONTINUE otherwise."""

    def test_arcane_sight_detects_bait(self):
        """Intruder with arcane sight sees through the bait and repaths."""
        intruder = MockIntruder(arcane_sight_range=3, greed=0.8)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, 0)
        assert info.result == InteractionResult.REPATH

    def test_greedy_intruder_collects_bait(self):
        """Greedy intruder without arcane sight grabs the bait."""
        intruder = MockIntruder(greed=0.5, arcane_sight_range=0)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, 0)
        assert info.result == InteractionResult.COLLECT
        assert info.ticks == GOLD_BAIT_INTERACT_TICKS
        assert info.interaction_type == "grab_bait"

    def test_no_greed_continues(self):
        """Non-greedy intruder without arcane sight walks past."""
        intruder = MockIntruder(greed=0.0, arcane_sight_range=0)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_arcane_sight_takes_priority_over_greed(self):
        """Arcane sight check comes before greed check."""
        intruder = MockIntruder(arcane_sight_range=1, greed=1.0)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, 0)
        assert info.result == InteractionResult.REPATH


# ── Heat Beacon ──────────────────────────────────────────────────────


class TestHeatBeacon:
    """Heat Beacon: CONTINUE if can_fly; DAMAGE otherwise."""

    def test_flyer_ignores_beacon(self):
        intruder = MockIntruder(can_fly=True)
        info = handle_block(intruder, VOXEL_HEAT_BEACON, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_non_flyer_takes_damage(self):
        intruder = MockIntruder(can_fly=False)
        info = handle_block(intruder, VOXEL_HEAT_BEACON, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == HEAT_BEACON_DAMAGE

    def test_damage_amount_matches_config(self):
        """Verify the damage value is the exact config constant."""
        intruder = MockIntruder(can_fly=False)
        info = handle_block(intruder, VOXEL_HEAT_BEACON, 0)
        assert info.damage == _cfg.HEAT_BEACON_DAMAGE


# ── Pressure Plate ───────────────────────────────────────────────────


class TestPressurePlate:
    """Pressure Plate: always CONTINUE (activation handled in decision.py)."""

    def test_default_continues(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_PRESSURE_PLATE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_any_archetype_continues(self):
        """Even special archetypes just walk over it."""
        intruder = MockIntruder(can_fly=True, arcane_sight_range=5)
        info = handle_block(intruder, VOXEL_PRESSURE_PLATE, 0)
        assert info.result == InteractionResult.CONTINUE


# ── Iron Bars ────────────────────────────────────────────────────────


class TestIronBars:
    """Iron Bars: always REPATH."""

    def test_default_repaths(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_IRON_BARS, 0)
        assert info.result == InteractionResult.REPATH

    def test_strong_intruder_still_repaths(self):
        """Even bash-capable intruders cannot get through iron bars."""
        intruder = MockIntruder(can_bash_door=True, can_dig=True)
        info = handle_block(intruder, VOXEL_IRON_BARS, 0)
        assert info.result == InteractionResult.REPATH


# ── Floodgate ────────────────────────────────────────────────────────


class TestFloodgate:
    """Floodgate: CONTINUE if open (state=0); REPATH if closed (state!=0)."""

    def test_open_floodgate_continues(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_FLOODGATE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_closed_floodgate_repaths(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_FLOODGATE, 1)
        assert info.result == InteractionResult.REPATH

    def test_closed_floodgate_nonzero_state(self):
        """Any non-zero block_state means closed."""
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_FLOODGATE, 2)
        assert info.result == InteractionResult.REPATH


# ── Alarm Bell ───────────────────────────────────────────────────────


class TestAlarmBell:
    """Alarm Bell: always CONTINUE."""

    def test_default_continues(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_ALARM_BELL, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_any_archetype_continues(self):
        intruder = MockIntruder(can_fly=True)
        info = handle_block(intruder, VOXEL_ALARM_BELL, 0)
        assert info.result == InteractionResult.CONTINUE


# ── Fragile Floor ────────────────────────────────────────────────────


class TestFragileFloor:
    """Fragile Floor: CONTINUE if fly; REPATH if arcane/cunning; CONTINUE otherwise."""

    def test_flyer_passes_safely(self):
        intruder = MockIntruder(can_fly=True)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_arcane_sight_detects(self):
        intruder = MockIntruder(arcane_sight_range=2)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.REPATH

    def test_high_cunning_detects(self):
        intruder = MockIntruder(cunning=TARP_DETECT_CUNNING)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.REPATH

    def test_cunning_above_threshold_detects(self):
        intruder = MockIntruder(cunning=TARP_DETECT_CUNNING + 0.1)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.REPATH

    def test_cunning_below_threshold_continues(self):
        intruder = MockIntruder(cunning=TARP_DETECT_CUNNING - 0.1)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_default_walks_on_it(self):
        """Default intruder (low cunning, no arcane, no fly) walks onto it."""
        intruder = MockIntruder(cunning=0.3, arcane_sight_range=0, can_fly=False)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_fly_takes_priority_over_arcane(self):
        """Even with arcane sight, flyer gets CONTINUE (not REPATH)."""
        intruder = MockIntruder(can_fly=True, arcane_sight_range=3)
        info = handle_block(intruder, VOXEL_FRAGILE_FLOOR, 0)
        assert info.result == InteractionResult.CONTINUE


# ── Pipe ─────────────────────────────────────────────────────────────


class TestPipe:
    """Pipe: always REPATH."""

    def test_default_repaths(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_PIPE, 0)
        assert info.result == InteractionResult.REPATH

    def test_digger_still_repaths(self):
        intruder = MockIntruder(can_dig=True)
        info = handle_block(intruder, VOXEL_PIPE, 0)
        assert info.result == InteractionResult.REPATH


# ── Pump ─────────────────────────────────────────────────────────────


class TestPump:
    """Pump: always REPATH."""

    def test_default_repaths(self):
        intruder = MockIntruder()
        info = handle_block(intruder, VOXEL_PUMP, 0)
        assert info.result == InteractionResult.REPATH

    def test_any_archetype_repaths(self):
        intruder = MockIntruder(can_fly=True, can_dig=True)
        info = handle_block(intruder, VOXEL_PUMP, 0)
        assert info.result == InteractionResult.REPATH


# ── Steam Vent ───────────────────────────────────────────────────────


class TestSteamVent:
    """Steam Vent: CONTINUE if can_fly; DAMAGE otherwise."""

    def test_flyer_ignores(self):
        intruder = MockIntruder(can_fly=True)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_non_flyer_takes_damage(self):
        intruder = MockIntruder(can_fly=False)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == STEAM_VENT_DAMAGE

    def test_damage_amount_matches_config(self):
        intruder = MockIntruder(can_fly=False)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.damage == _cfg.STEAM_VENT_DAMAGE


# ======================================================================
# Tests from test_greed_appeal.py
# ======================================================================


# ── Gold Bait greed tests ────────────────────────────────────────────


class TestGoldBaitGreed:
    """Greedy intruders are attracted to gold bait; non-greedy ones walk past."""

    def test_greedy_intruder_attracted_to_gold_bait(self):
        """An intruder with greed > 0 gets COLLECT on gold bait."""
        intruder = MockIntruder(greed=0.5)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, block_state=0)
        assert info.result is InteractionResult.COLLECT

    def test_non_greedy_intruder_ignores_gold_bait(self):
        """An intruder with greed == 0 gets CONTINUE on gold bait."""
        intruder = MockIntruder(greed=0.0)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, block_state=0)
        assert info.result is InteractionResult.CONTINUE

    def test_arcane_sight_sees_through_gold_bait(self):
        """Arcane sight (range > 0) reveals gold bait as a trap -> REPATH."""
        intruder = MockIntruder(greed=0.8, arcane_sight_range=3)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, block_state=0)
        assert info.result is InteractionResult.REPATH

    def test_gold_bait_interaction_type_is_grab_bait(self):
        """COLLECT result on gold bait carries interaction_type='grab_bait'."""
        intruder = MockIntruder(greed=0.5)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, block_state=0)
        assert info.interaction_type == "grab_bait"

    def test_gold_bait_interaction_ticks(self):
        """COLLECT result on gold bait uses GOLD_BAIT_INTERACT_TICKS."""
        intruder = MockIntruder(greed=0.5)
        info = handle_block(intruder, VOXEL_GOLD_BAIT, block_state=0)
        assert info.ticks == GOLD_BAIT_INTERACT_TICKS


# ── Treasure greed tests ─────────────────────────────────────────────


class TestTreasureGreed:
    """Greedy intruders grab treasure; non-greedy ones walk past."""

    def test_greedy_intruder_attracted_to_treasure(self):
        """An intruder with greed > 0 gets COLLECT on treasure."""
        intruder = MockIntruder(greed=0.5)
        info = handle_block(intruder, VOXEL_TREASURE, block_state=0)
        assert info.result is InteractionResult.COLLECT

    def test_non_greedy_intruder_ignores_treasure(self):
        """An intruder with greed == 0 gets CONTINUE on treasure."""
        intruder = MockIntruder(greed=0.0)
        info = handle_block(intruder, VOXEL_TREASURE, block_state=0)
        assert info.result is InteractionResult.CONTINUE

    def test_treasure_interaction_type_is_grab_treasure(self):
        """COLLECT result on treasure carries interaction_type='grab_treasure'."""
        intruder = MockIntruder(greed=0.5)
        info = handle_block(intruder, VOXEL_TREASURE, block_state=0)
        assert info.interaction_type == "grab_treasure"
