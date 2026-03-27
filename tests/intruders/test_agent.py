"""Tests for the Intruder agent data model and state machine.

Dependencies: intruders.agent, intruders.archetypes, intruders.equipment,
    intruders.personal_map, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    EXPLORER,
    INQUISITOR,
    EIDOLON,
    HERO,
    MOLE_TAMER,
    IntruderObjective,
    IntruderStatus,
)
from dungeon_builder.intruders.equipment import (
    Equipment,
    ItemInstance,
    POTION_HEAL,
    GEAR_LIGHT_SHIELD,
    ItemEffect,
)
from dungeon_builder.intruders.personal_map import PersonalMap
import dungeon_builder.config as _cfg


def _make_intruder(archetype=EXPLORER, equipment=None, level=1, status=None):
    """Create an Intruder with sensible defaults for testing."""
    return Intruder(
        intruder_id=1,
        x=10, y=20, z=3,
        archetype=archetype,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=PersonalMap(),
        equipment=equipment,
        level=level,
        status=status,
    )


# ── Intruder creation ─────────────────────────────────────────────────


class TestIntruderCreation:
    """Verify Intruder constructor initializes correctly."""

    def test_basic_construction(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.id == 1
        assert i.pos == (10, 20, 3)
        assert i.archetype is EXPLORER
        assert i.state == IntruderState.SPAWNING

    def test_hp_from_archetype(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.hp == EXPLORER.hp
        assert i.max_hp == EXPLORER.hp

    def test_different_archetypes_different_hp(self):
        explorer = _make_intruder(archetype=EXPLORER)
        inquisitor = _make_intruder(archetype=INQUISITOR)
        assert explorer.hp != inquisitor.hp
        assert explorer.hp == EXPLORER.hp
        assert inquisitor.hp == INQUISITOR.hp

    def test_equipment_defaults_to_empty(self):
        """If no equipment passed, a default empty Equipment is created."""
        i = _make_intruder(archetype=EXPLORER)
        assert isinstance(i.equipment, Equipment)

    def test_equipment_passed_at_construction(self):
        equip = Equipment(base_inventory_slots=5)
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        i = _make_intruder(archetype=EXPLORER, equipment=equip)
        assert i.equipment is equip
        assert i.equipment.has_effect(ItemEffect.HEAL)

    def test_default_status_is_grunt(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.status == IntruderStatus.GRUNT

    def test_explicit_status(self):
        i = _make_intruder(archetype=EXPLORER, status=IntruderStatus.VETERAN)
        assert i.status == IntruderStatus.VETERAN


# ── Food/water initialization ─────────────────────────────────────────


class TestFoodWaterInit:
    """Verify food and water are initialized from archetype capacity."""

    def test_food_initialized_from_archetype(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.food == EXPLORER.food_capacity

    def test_water_initialized_from_archetype(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.water == EXPLORER.water_capacity

    def test_eidolon_has_zero_supplies(self):
        """Eidolons are supernatural -- they need no food or water."""
        i = _make_intruder(archetype=EIDOLON)
        assert i.food == 0.0
        assert i.water == 0.0


# ── take_damage() with shield absorption ──────────────────────────────


class TestTakeDamage:
    """Verify damage absorption order: shield_hp first, then HP."""

    def test_damage_reduces_hp(self):
        i = _make_intruder(archetype=EXPLORER)
        initial_hp = i.hp
        i.take_damage(10)
        assert i.hp == initial_hp - 10

    def test_lethal_damage_kills(self):
        i = _make_intruder(archetype=EXPLORER)
        i.state = IntruderState.ADVANCING
        i.take_damage(9999)
        assert i.hp == 0
        assert i.state == IntruderState.DEAD
        assert i.alive is False

    def test_hp_never_goes_negative(self):
        i = _make_intruder(archetype=EXPLORER)
        i.take_damage(i.hp + 100)
        assert i.hp == 0

    def test_shield_absorbs_damage_first(self):
        equip = Equipment(base_inventory_slots=3)
        equip.equip(ItemInstance(GEAR_LIGHT_SHIELD))
        i = _make_intruder(archetype=INQUISITOR, equipment=equip)
        initial_hp = i.hp
        shield_hp = i.shield_hp
        assert shield_hp > 0, "Inquisitor with shield should have shield_hp"

        # Damage less than shield
        i.take_damage(shield_hp - 5)
        assert i.hp == initial_hp  # HP untouched
        assert i.shield_hp == 5    # Shield partially depleted

    def test_damage_overflow_from_shield_to_hp(self):
        equip = Equipment(base_inventory_slots=3)
        equip.equip(ItemInstance(GEAR_LIGHT_SHIELD))
        i = _make_intruder(archetype=INQUISITOR, equipment=equip)
        initial_hp = i.hp
        shield_hp = i.shield_hp

        overflow = 10
        i.take_damage(shield_hp + overflow)
        assert i.shield_hp == 0
        assert i.hp == initial_hp - overflow

    def test_zero_damage_is_safe(self):
        i = _make_intruder(archetype=EXPLORER)
        initial_hp = i.hp
        i.take_damage(0)
        assert i.hp == initial_hp


# ── has_fire_immunity property ─────────────────────────────────────────


class TestFireImmunity:
    """Verify has_fire_immunity is equipment-driven."""

    def test_no_fire_immunity_by_default(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.has_fire_immunity is False

    def test_fire_immunity_with_potion(self):
        from dungeon_builder.intruders.equipment import POTION_FIRE_IMMUNITY
        equip = Equipment(base_inventory_slots=3)
        equip.add_to_inventory(ItemInstance(POTION_FIRE_IMMUNITY))
        i = _make_intruder(archetype=EXPLORER, equipment=equip)
        assert i.has_fire_immunity is True


# ── has_water_breathing property ───────────────────────────────────────


class TestWaterBreathing:
    """Verify has_water_breathing is equipment-driven."""

    def test_no_water_breathing_by_default(self):
        i = _make_intruder(archetype=EXPLORER)
        assert i.has_water_breathing is False

    def test_water_breathing_with_potion(self):
        from dungeon_builder.intruders.equipment import POTION_WATER_BREATHING
        equip = Equipment(base_inventory_slots=3)
        equip.add_to_inventory(ItemInstance(POTION_WATER_BREATHING))
        i = _make_intruder(archetype=EXPLORER, equipment=equip)
        assert i.has_water_breathing is True


# ── effective_food_rate and effective_water_rate ───────────────────────


class TestEffectiveRates:
    """Verify supply consumption rate properties."""

    def test_effective_food_rate(self):
        i = _make_intruder(archetype=EXPLORER)
        expected = EXPLORER.food_rate * EXPLORER.supply_efficiency
        assert i.effective_food_rate == pytest.approx(expected)

    def test_effective_water_rate(self):
        i = _make_intruder(archetype=EXPLORER)
        expected = EXPLORER.water_rate * EXPLORER.supply_efficiency
        assert i.effective_water_rate == pytest.approx(expected)

    def test_eidolon_zero_rates(self):
        """Eidolons have supply_efficiency=0.0, so rates are zero."""
        i = _make_intruder(archetype=EIDOLON)
        assert i.effective_food_rate == 0.0
        assert i.effective_water_rate == 0.0

    def test_rates_differ_by_archetype(self):
        explorer = _make_intruder(archetype=EXPLORER)
        inquisitor = _make_intruder(archetype=INQUISITOR)
        # Explorer has supply_efficiency=0.8, Inquisitor has 1.0
        assert explorer.effective_food_rate != inquisitor.effective_food_rate


# ── effective_damage with level scaling ────────────────────────────────


class TestEffectiveDamage:
    """Verify effective_damage accounts for level scaling and equipment."""

    def test_level_1_base_damage(self):
        i = _make_intruder(archetype=EXPLORER, level=1)
        # At level 1, damage_mult = 1.0, so effective = archetype.damage
        # (no gear bonus, morale is MORALE_BASE which is between thresholds)
        assert i.effective_damage == EXPLORER.damage

    def test_higher_level_increases_damage(self):
        # Use INQUISITOR (damage=8) so int truncation doesn't mask scaling
        i_low = _make_intruder(archetype=INQUISITOR, level=1)
        i_high = _make_intruder(archetype=INQUISITOR, level=3)
        assert i_high.effective_damage > i_low.effective_damage

    def test_level_scaling_formula(self):
        level = 3
        i = _make_intruder(archetype=EXPLORER, level=level)
        damage_mult = 1.0 + (level - 1) * _cfg.LEVEL_DAMAGE_SCALE
        expected = int(EXPLORER.damage * damage_mult)
        # Account for morale being at base (between thresholds, no bonus)
        assert i.effective_damage == expected

    def test_damage_boost_from_equipment(self):
        """DAMAGE_BOOST gear increases effective damage."""
        from dungeon_builder.intruders.equipment import (
            ItemTemplate, ItemCategory, GearSlot,
        )
        boost_gear = ItemTemplate(
            "Power Gauntlets", ItemCategory.GEAR, ItemEffect.DAMAGE_BOOST,
            charges=-1, value=5, duration=0, slot=GearSlot.RIGHT_ARM,
        )
        equip = Equipment(base_inventory_slots=3)
        equip.equip(ItemInstance(boost_gear))
        i = _make_intruder(archetype=EXPLORER, equipment=equip, level=1)
        assert i.effective_damage == EXPLORER.damage + 5


# ── IntruderState enum ─────────────────────────────────────────────────


class TestIntruderState:
    """Verify IntruderState has all expected members."""

    def test_has_all_states(self):
        expected = {
            "SPAWNING", "ADVANCING", "INTERACTING", "ATTACKING",
            "RETREATING", "PILLAGING", "DEAD", "ESCAPED",
        }
        actual = {s.name for s in IntruderState}
        assert actual == expected

    def test_alive_excludes_dead_and_escaped(self):
        i = _make_intruder()
        assert i.alive is True
        i.state = IntruderState.DEAD
        assert i.alive is False

    def test_alive_excludes_escaped(self):
        i = _make_intruder()
        i.state = IntruderState.ESCAPED
        assert i.alive is False

    def test_alive_for_active_states(self):
        i = _make_intruder()
        active_states = [
            IntruderState.SPAWNING, IntruderState.ADVANCING,
            IntruderState.INTERACTING, IntruderState.ATTACKING,
            IntruderState.RETREATING, IntruderState.PILLAGING,
        ]
        for state in active_states:
            i.state = state
            assert i.alive is True, f"alive should be True for {state.name}"
