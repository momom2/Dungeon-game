"""Tests for intruder micro-interaction system."""

from dataclasses import dataclass

import pytest

from dungeon_builder.intruders.interactions import (
    handle_block,
    InteractionResult,
    InteractionInfo,
)
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    VANGUARD, SHADOWBLADE, TUNNELER, PYREMANCER,
    WINDCALLER, WARDEN, GORECLAW, GLOOMSEER,
    ALL_ARCHETYPES,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.config import (
    VOXEL_AIR, VOXEL_DOOR, VOXEL_SPIKE, VOXEL_TREASURE,
    VOXEL_TARP, VOXEL_ROLLING_STONE, VOXEL_REINFORCED_WALL,
    VOXEL_LAVA, VOXEL_WATER, VOXEL_SLOPE, VOXEL_STAIRS,
    VOXEL_STONE,
    SPIKE_DAMAGE, ROLLING_STONE_DAMAGE,
    DOOR_BASH_TICKS, DOOR_BASH_TICKS_GORECLAW, DOOR_LOCKPICK_TICKS,
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


def _make(arch, objective=IntruderObjective.DESTROY_CORE):
    return Intruder(1, 0, 0, 0, arch, objective, PersonalMap())


# ── Mock helpers (for new block interaction tests) ────────────────────


@dataclass
class MockArch:
    name: str = "Vanguard"
    greed: float = 0.5
    fire_immune: bool = False
    can_fly: bool = False
    can_dig: bool = False
    can_bash_door: bool = False
    can_lockpick: bool = False
    arcane_sight_range: int = 0
    spike_detect_range: int = 0
    cunning: float = 0.3
    frenzy_threshold: float = 0.0
    speed: int = 2


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

    def test_vanguard_bashes_closed_door(self):
        info = handle_block(_make(VANGUARD), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.INTERACT
        assert info.ticks == DOOR_BASH_TICKS
        assert info.interaction_type == "bash_door"

    def test_shadowblade_lockpicks_closed_door(self):
        info = handle_block(_make(SHADOWBLADE), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.INTERACT
        assert info.ticks == DOOR_LOCKPICK_TICKS
        assert info.interaction_type == "lockpick"

    def test_goreclaw_bashes_closed_door_faster(self):
        info = handle_block(_make(GORECLAW), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.INTERACT
        assert info.ticks == DOOR_BASH_TICKS_GORECLAW

    def test_tunneler_bashes_closed_door(self):
        info = handle_block(_make(TUNNELER), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.INTERACT
        assert info.interaction_type == "bash_door"

    def test_pyremancer_repaths_closed_door(self):
        info = handle_block(_make(PYREMANCER), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_windcaller_repaths_closed_door(self):
        info = handle_block(_make(WINDCALLER), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_warden_repaths_closed_door(self):
        info = handle_block(_make(WARDEN), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_gloomseer_repaths_closed_door(self):
        info = handle_block(_make(GLOOMSEER), VOXEL_DOOR, block_state=1)
        assert info.result == InteractionResult.REPATH


# ── Spike interactions ──────────────────────────────────────────────


class TestSpikeInteractions:
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_retracted_spike_continue(self, arch):
        info = handle_block(_make(arch), VOXEL_SPIKE, block_state=0)
        assert info.result == InteractionResult.CONTINUE

    def test_vanguard_takes_half_damage(self):
        info = handle_block(_make(VANGUARD), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE // 2

    def test_shadowblade_detects_and_avoids(self):
        info = handle_block(_make(SHADOWBLADE), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.REPATH

    def test_goreclaw_smashes_spike(self):
        info = handle_block(_make(GORECLAW), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DESTROY_BLOCK
        assert info.damage == SPIKE_DAMAGE // 2  # Takes 10 damage

    def test_windcaller_flies_over_spike(self):
        info = handle_block(_make(WINDCALLER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.CONTINUE

    def test_warden_takes_full_damage(self):
        info = handle_block(_make(WARDEN), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE

    def test_tunneler_takes_full_damage(self):
        info = handle_block(_make(TUNNELER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE

    def test_pyremancer_takes_full_damage(self):
        info = handle_block(_make(PYREMANCER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE

    def test_gloomseer_takes_full_damage(self):
        info = handle_block(_make(GLOOMSEER), VOXEL_SPIKE, block_state=1)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == SPIKE_DAMAGE


# ── Treasure interactions ───────────────────────────────────────────


class TestTreasureInteractions:
    def test_shadowblade_collects(self):
        info = handle_block(_make(SHADOWBLADE), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.COLLECT
        assert info.interaction_type == "grab_treasure"

    def test_vanguard_ignores(self):
        info = handle_block(_make(VANGUARD), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.CONTINUE  # greed=0.0

    def test_goreclaw_ignores(self):
        info = handle_block(_make(GORECLAW), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.CONTINUE  # greed=0.0

    def test_pyremancer_collects_slightly(self):
        # Pyremancer has greed=0.1 (> 0)
        info = handle_block(_make(PYREMANCER), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.COLLECT

    def test_gloomseer_collects(self):
        # greed=0.1
        info = handle_block(_make(GLOOMSEER), VOXEL_TREASURE, 0)
        assert info.result == InteractionResult.COLLECT


# ── Tarp interactions ───────────────────────────────────────────────


class TestTarpInteractions:
    def test_windcaller_flies_over(self):
        info = handle_block(_make(WINDCALLER), VOXEL_TARP, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_gloomseer_detects_via_arcane(self):
        info = handle_block(_make(GLOOMSEER), VOXEL_TARP, 0)
        assert info.result == InteractionResult.REPATH

    def test_shadowblade_detects_high_cunning(self):
        # Shadowblade cunning=0.8 >= 0.5
        info = handle_block(_make(SHADOWBLADE), VOXEL_TARP, 0)
        assert info.result == InteractionResult.REPATH

    def test_vanguard_falls_through(self):
        # Vanguard cunning=0.0
        info = handle_block(_make(VANGUARD), VOXEL_TARP, 0)
        assert info.result == InteractionResult.FALL

    def test_goreclaw_falls_through(self):
        info = handle_block(_make(GORECLAW), VOXEL_TARP, 0)
        assert info.result == InteractionResult.FALL

    def test_tunneler_falls_through(self):
        # Tunneler cunning=0.3 < 0.5
        info = handle_block(_make(TUNNELER), VOXEL_TARP, 0)
        assert info.result == InteractionResult.FALL

    def test_warden_falls_through(self):
        # Warden cunning=0.4 < 0.5
        info = handle_block(_make(WARDEN), VOXEL_TARP, 0)
        assert info.result == InteractionResult.FALL


# ── Rolling stone interactions ──────────────────────────────────────


class TestRollingStoneInteractions:
    def test_windcaller_flies_over(self):
        info = handle_block(_make(WINDCALLER), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_shadowblade_dodges_high_speed(self):
        # Shadowblade speed=3 >= 3
        info = handle_block(_make(SHADOWBLADE), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_windcaller_dodges_high_speed(self):
        # Windcaller speed=4 >= 3
        info = handle_block(_make(WINDCALLER), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_vanguard_takes_damage(self):
        info = handle_block(_make(VANGUARD), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == ROLLING_STONE_DAMAGE

    def test_goreclaw_takes_damage(self):
        info = handle_block(_make(GORECLAW), VOXEL_ROLLING_STONE, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == ROLLING_STONE_DAMAGE


# ── Reinforced wall ─────────────────────────────────────────────────


class TestReinforcedWall:
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_always_repath(self, arch):
        info = handle_block(_make(arch), VOXEL_REINFORCED_WALL, 0)
        assert info.result == InteractionResult.REPATH


# ── Lava interactions ───────────────────────────────────────────────


class TestLavaInteractions:
    def test_pyremancer_walks_through(self):
        info = handle_block(_make(PYREMANCER), VOXEL_LAVA, 0)
        assert info.result == InteractionResult.CONTINUE

    @pytest.mark.parametrize("arch", [VANGUARD, SHADOWBLADE, TUNNELER,
                                       WINDCALLER, WARDEN, GORECLAW, GLOOMSEER],
                             ids=lambda a: a.name)
    def test_non_immune_death(self, arch):
        info = handle_block(_make(arch), VOXEL_LAVA, 0)
        assert info.result == InteractionResult.DEATH


# ── Water interactions ──────────────────────────────────────────────


class TestWaterInteractions:
    def test_pyremancer_dies_in_water(self):
        info = handle_block(_make(PYREMANCER), VOXEL_WATER, 0)
        assert info.result == InteractionResult.DEATH

    @pytest.mark.parametrize("arch", [VANGUARD, SHADOWBLADE, TUNNELER,
                                       WINDCALLER, WARDEN, GORECLAW, GLOOMSEER],
                             ids=lambda a: a.name)
    def test_non_fire_repath(self, arch):
        info = handle_block(_make(arch), VOXEL_WATER, 0)
        assert info.result == InteractionResult.REPATH


# ── Other solid blocks ──────────────────────────────────────────────


class TestOtherSolids:
    def test_stone_repaths(self):
        info = handle_block(_make(VANGUARD), VOXEL_STONE, 0)
        assert info.result == InteractionResult.REPATH


# ══════════════════════════════════════════════════════════════════════
# Tests from test_new_block_interactions.py
# ══════════════════════════════════════════════════════════════════════


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
    """Heat Beacon: CONTINUE if fire_immune; DAMAGE otherwise."""

    def test_fire_immune_ignores_beacon(self):
        intruder = MockIntruder(fire_immune=True)
        info = handle_block(intruder, VOXEL_HEAT_BEACON, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_non_immune_takes_damage(self):
        intruder = MockIntruder(fire_immune=False)
        info = handle_block(intruder, VOXEL_HEAT_BEACON, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == HEAT_BEACON_DAMAGE

    def test_damage_amount_matches_config(self):
        """Verify the damage value is the exact config constant."""
        intruder = MockIntruder(fire_immune=False)
        info = handle_block(intruder, VOXEL_HEAT_BEACON, 0)
        assert info.damage == 15  # HEAT_BEACON_DAMAGE


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
        intruder = MockIntruder(can_fly=True, fire_immune=True)
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
    """Steam Vent: CONTINUE if fire_immune or can_fly; DAMAGE otherwise."""

    def test_fire_immune_ignores(self):
        intruder = MockIntruder(fire_immune=True, can_fly=False)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_flyer_ignores(self):
        intruder = MockIntruder(fire_immune=False, can_fly=True)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_fire_immune_and_flyer_continues(self):
        intruder = MockIntruder(fire_immune=True, can_fly=True)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.result == InteractionResult.CONTINUE

    def test_non_immune_non_flyer_takes_damage(self):
        intruder = MockIntruder(fire_immune=False, can_fly=False)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.result == InteractionResult.DAMAGE
        assert info.damage == STEAM_VENT_DAMAGE

    def test_damage_amount_matches_config(self):
        intruder = MockIntruder(fire_immune=False, can_fly=False)
        info = handle_block(intruder, VOXEL_STEAM_VENT, 0)
        assert info.damage == 10  # STEAM_VENT_DAMAGE


# ══════════════════════════════════════════════════════════════════════
# Tests from test_greed_appeal.py
# ══════════════════════════════════════════════════════════════════════


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
