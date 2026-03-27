"""Tests for the intruder equipment and inventory system.

Dependencies: intruders.equipment, intruders.archetypes, utils.rng, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.equipment import (
    ItemCategory,
    GearSlot,
    ItemEffect,
    ItemTemplate,
    ItemInstance,
    Equipment,
    combine_ropes,
    generate_loadout,
    POTION_HEAL,
    TOOL_TORCH,
    TOOL_ROPE,
    GEAR_BACKPACK,
    GEAR_POUCH,
    GEAR_BANDOLIER,
    GEAR_LIGHT_SHIELD,
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
    IntruderStatus,
)
from dungeon_builder.utils.rng import SeededRNG
import dungeon_builder.config as _cfg


# ── ItemInstance creation & charge depletion ───────────────────────────


class TestItemInstance:
    """Verify ItemInstance creation, charges, and depletion."""

    def test_creation_copies_charges_from_template(self):
        item = ItemInstance(POTION_HEAL)
        assert item.charges_remaining == POTION_HEAL.charges
        assert item.template is POTION_HEAL

    def test_creation_with_multi_charge_template(self):
        item = ItemInstance(TOOL_TORCH)
        assert item.charges_remaining == _cfg.TORCH_DURATION

    def test_use_decrements_charge(self):
        item = ItemInstance(POTION_HEAL)
        assert item.charges_remaining == 1
        result = item.use()
        assert result is True
        assert item.charges_remaining == 0

    def test_use_returns_false_when_depleted(self):
        item = ItemInstance(POTION_HEAL)
        item.use()  # Use the single charge
        result = item.use()
        assert result is False

    def test_infinite_charges_never_deplete(self):
        """Gear items with charges=-1 can be used indefinitely."""
        item = ItemInstance(GEAR_LIGHT_SHIELD)
        assert item.infinite is True
        for _ in range(100):
            assert item.use() is True
        assert item.charges_remaining == -1

    def test_depleted_property_true_when_zero_charges(self):
        item = ItemInstance(POTION_HEAL)
        assert item.depleted is False
        item.use()
        assert item.depleted is True

    def test_depleted_property_false_for_infinite(self):
        """Infinite items are never depleted."""
        item = ItemInstance(GEAR_BACKPACK)
        assert item.depleted is False

    def test_depleted_property_false_when_charges_remain(self):
        item = ItemInstance(TOOL_TORCH)
        assert item.depleted is False
        item.use()
        assert item.depleted is False  # Still has many charges left


# ── Equipment.equip() ─────────────────────────────────────────────────


class TestEquipGear:
    """Verify gear equipping to body slots."""

    def test_equip_to_empty_slot_succeeds(self):
        equip = Equipment(base_inventory_slots=3)
        item = ItemInstance(GEAR_LIGHT_SHIELD)
        assert equip.equip(item) is True
        assert GearSlot.LEFT_ARM in equip.gear_slots
        assert equip.gear_slots[GearSlot.LEFT_ARM] is item

    def test_equip_to_occupied_slot_fails(self):
        equip = Equipment(base_inventory_slots=3)
        item1 = ItemInstance(GEAR_LIGHT_SHIELD)
        item2 = ItemInstance(GEAR_LIGHT_SHIELD)
        equip.equip(item1)
        assert equip.equip(item2) is False

    def test_equip_non_gear_item_fails(self):
        """Items with slot=None (consumables/tools) cannot be equipped."""
        equip = Equipment(base_inventory_slots=3)
        item = ItemInstance(POTION_HEAL)
        assert equip.equip(item) is False

    def test_equip_multiple_different_slots(self):
        equip = Equipment(base_inventory_slots=3)
        shield = ItemInstance(GEAR_LIGHT_SHIELD)  # LEFT_ARM
        pouch = ItemInstance(GEAR_POUCH)           # BELT
        backpack = ItemInstance(GEAR_BACKPACK)      # BACK
        assert equip.equip(shield) is True
        assert equip.equip(pouch) is True
        assert equip.equip(backpack) is True
        assert len(equip.gear_slots) == 3


# ── Equipment.add_to_inventory() capacity limits ──────────────────────


class TestInventoryCapacity:
    """Verify inventory capacity limits and add_to_inventory behavior."""

    def test_add_within_capacity(self):
        equip = Equipment(base_inventory_slots=3)
        for _ in range(3):
            assert equip.add_to_inventory(ItemInstance(POTION_HEAL)) is True
        assert len(equip.inventory) == 3

    def test_add_beyond_capacity_fails(self):
        equip = Equipment(base_inventory_slots=2)
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        assert equip.add_to_inventory(ItemInstance(POTION_HEAL)) is False
        assert len(equip.inventory) == 2

    def test_inventory_capacity_with_no_containers(self):
        equip = Equipment(base_inventory_slots=3)
        assert equip.inventory_capacity == 3

    def test_inventory_capacity_with_extra_slots_containers(self):
        equip = Equipment(base_inventory_slots=3)
        equip.equip(ItemInstance(GEAR_POUCH))      # +POUCH_EXTRA_SLOTS
        expected = 3 + _cfg.POUCH_EXTRA_SLOTS
        assert equip.inventory_capacity == expected

    def test_inventory_capacity_with_multiple_containers(self):
        equip = Equipment(base_inventory_slots=3)
        equip.equip(ItemInstance(GEAR_POUCH))       # BELT slot
        equip.equip(ItemInstance(GEAR_BANDOLIER))   # CHEST slot
        equip.equip(ItemInstance(GEAR_BACKPACK))    # BACK slot
        expected = (
            3
            + _cfg.POUCH_EXTRA_SLOTS
            + _cfg.BANDOLIER_EXTRA_SLOTS
            + _cfg.BACKPACK_EXTRA_SLOTS
        )
        assert equip.inventory_capacity == expected

    def test_space_remaining(self):
        equip = Equipment(base_inventory_slots=3)
        assert equip.inventory_space_remaining == 3
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        assert equip.inventory_space_remaining == 2


# ── Equipment.has_effect() ─────────────────────────────────────────────


class TestHasEffect:
    """Verify has_effect searches both gear slots and inventory."""

    def test_has_effect_from_inventory(self):
        equip = Equipment(base_inventory_slots=3)
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        assert equip.has_effect(ItemEffect.HEAL) is True
        assert equip.has_effect(ItemEffect.FIRE_IMMUNITY) is False

    def test_has_effect_from_gear(self):
        equip = Equipment(base_inventory_slots=3)
        equip.equip(ItemInstance(GEAR_LIGHT_SHIELD))
        assert equip.has_effect(ItemEffect.SHIELD) is True

    def test_has_effect_false_when_depleted(self):
        equip = Equipment(base_inventory_slots=3)
        item = ItemInstance(POTION_HEAL)
        equip.add_to_inventory(item)
        item.use()  # Deplete it
        assert equip.has_effect(ItemEffect.HEAL) is False

    def test_has_effect_false_on_empty_equipment(self):
        equip = Equipment(base_inventory_slots=3)
        assert equip.has_effect(ItemEffect.HEAL) is False


# ── Equipment.use_effect() ─────────────────────────────────────────────


class TestUseEffect:
    """Verify use_effect finds and depletes item charges."""

    def test_use_effect_depletes_charge(self):
        equip = Equipment(base_inventory_slots=3)
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        assert equip.use_effect(ItemEffect.HEAL) is True
        assert equip.has_effect(ItemEffect.HEAL) is False

    def test_use_effect_returns_false_when_missing(self):
        equip = Equipment(base_inventory_slots=3)
        assert equip.use_effect(ItemEffect.FIRE_IMMUNITY) is False

    def test_use_effect_first_item_consumed_second_remains(self):
        equip = Equipment(base_inventory_slots=3)
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        equip.use_effect(ItemEffect.HEAL)
        # One potion consumed, one remains
        assert equip.has_effect(ItemEffect.HEAL) is True

    def test_use_effect_returns_false_when_all_depleted(self):
        equip = Equipment(base_inventory_slots=3)
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
        equip.use_effect(ItemEffect.HEAL)
        assert equip.use_effect(ItemEffect.HEAL) is False


# ── combine_ropes() ───────────────────────────────────────────────────


class TestCombineRopes:
    """Verify rope combining with knot penalty."""

    def test_combined_length_with_knot_penalty(self):
        rope_a = ItemInstance(TOOL_ROPE)
        rope_b = ItemInstance(TOOL_ROPE)
        combined = combine_ropes(rope_a, rope_b)
        expected_length = (
            _cfg.ROPE_DEFAULT_LENGTH + _cfg.ROPE_DEFAULT_LENGTH
            - _cfg.ROPE_KNOT_PENALTY
        )
        assert combined.template.value == expected_length

    def test_combined_rope_is_new_instance(self):
        rope_a = ItemInstance(TOOL_ROPE)
        rope_b = ItemInstance(TOOL_ROPE)
        combined = combine_ropes(rope_a, rope_b)
        assert combined is not rope_a
        assert combined is not rope_b
        assert combined.template.name == "Knotted Rope"
        assert combined.template.effect == ItemEffect.ROPE

    def test_combined_length_never_below_one(self):
        """Even with extreme penalty, combined length is at least 1."""
        short_template = ItemTemplate(
            "Short Rope", ItemCategory.TOOL, ItemEffect.ROPE,
            charges=1, value=1, duration=0, slot=None,
        )
        rope_a = ItemInstance(short_template)
        rope_b = ItemInstance(short_template)
        combined = combine_ropes(rope_a, rope_b)
        assert combined.template.value >= 1

    def test_combine_non_rope_raises_error(self):
        rope = ItemInstance(TOOL_ROPE)
        potion = ItemInstance(POTION_HEAL)
        with pytest.raises(ValueError, match="ropes"):
            combine_ropes(rope, potion)


# ── generate_loadout() ─────────────────────────────────────────────────


class TestGenerateLoadout:
    """Verify generate_loadout returns valid Equipment for every archetype."""

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_returns_equipment_instance(self, arch):
        rng = SeededRNG(42)
        equip = generate_loadout(
            archetype=arch,
            rng=rng,
            level=1,
            status=IntruderStatus.GRUNT,
            reputation=None,
        )
        assert isinstance(equip, Equipment)

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_inventory_within_capacity(self, arch):
        rng = SeededRNG(42)
        equip = generate_loadout(
            archetype=arch,
            rng=rng,
            level=1,
            status=IntruderStatus.GRUNT,
            reputation=None,
        )
        assert len(equip.inventory) <= equip.inventory_capacity

    def test_eidolon_loadout_is_empty(self):
        """Eidolons carry nothing -- supernatural beings need no gear."""
        rng = SeededRNG(42)
        equip = generate_loadout(
            archetype=EIDOLON,
            rng=rng,
            level=1,
            status=IntruderStatus.GRUNT,
            reputation=None,
        )
        assert len(equip.inventory) == 0
        assert len(equip.gear_slots) == 0

    def test_inquisitor_has_shield(self):
        """Inquisitors should spawn with a light shield equipped."""
        rng = SeededRNG(42)
        equip = generate_loadout(
            archetype=INQUISITOR,
            rng=rng,
            level=1,
            status=IntruderStatus.GRUNT,
            reputation=None,
        )
        assert equip.has_effect(ItemEffect.SHIELD)

    def test_alchemist_has_bandolier(self):
        """Alchemists should spawn with a bandolier for extra capacity."""
        rng = SeededRNG(42)
        equip = generate_loadout(
            archetype=ALCHEMIST,
            rng=rng,
            level=1,
            status=IntruderStatus.GRUNT,
            reputation=None,
        )
        assert GearSlot.CHEST in equip.gear_slots

    def test_cartomancer_has_backpack(self):
        """Cartomancers should spawn with a backpack."""
        rng = SeededRNG(42)
        equip = generate_loadout(
            archetype=CARTOMANCER,
            rng=rng,
            level=1,
            status=IntruderStatus.GRUNT,
            reputation=None,
        )
        assert GearSlot.BACK in equip.gear_slots
