"""Tests for intruder archetype definitions, enums, and lookup tables.

Dependencies: intruders.archetypes
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.archetypes import (
    ArchetypeStats,
    IntruderObjective,
    IntruderStatus,
    STATUS_TRUST,
    ALL_ARCHETYPES,
    ARCHETYPE_BY_NAME,
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
)

_ALL_EIGHT_NAMES = (
    "Explorer", "Inquisitor", "Gloomwarden", "Mole Tamer",
    "Eidolon", "Alchemist", "Cartomancer", "Hero",
)

_ALL_EIGHT_INSTANCES = (
    EXPLORER, INQUISITOR, GLOOMWARDEN, MOLE_TAMER,
    EIDOLON, ALCHEMIST, CARTOMANCER, HERO,
)


# ── ALL_ARCHETYPES collection ──────────────────────────────────────────


class TestAllArchetypes:
    """Verify the ALL_ARCHETYPES tuple contains exactly the 8 archetypes."""

    def test_contains_exactly_8(self):
        assert len(ALL_ARCHETYPES) == 8

    def test_all_expected_archetypes_present(self):
        for instance in _ALL_EIGHT_INSTANCES:
            assert instance in ALL_ARCHETYPES

    def test_all_are_archetype_stats(self):
        for arch in ALL_ARCHETYPES:
            assert isinstance(arch, ArchetypeStats)


# ── ARCHETYPE_BY_NAME lookup ───────────────────────────────────────────


class TestArchetypeByName:
    """Verify the ARCHETYPE_BY_NAME dict maps all 8 names to correct instances."""

    def test_contains_all_8_names(self):
        assert set(ARCHETYPE_BY_NAME.keys()) == set(_ALL_EIGHT_NAMES)

    @pytest.mark.parametrize(
        "name, instance",
        zip(_ALL_EIGHT_NAMES, _ALL_EIGHT_INSTANCES),
        ids=_ALL_EIGHT_NAMES,
    )
    def test_name_maps_to_correct_instance(self, name, instance):
        assert ARCHETYPE_BY_NAME[name] is instance


# ── Name field on each archetype ───────────────────────────────────────


class TestArchetypeNames:
    """Verify each archetype instance has the expected name field."""

    @pytest.mark.parametrize(
        "instance, expected_name",
        zip(_ALL_EIGHT_INSTANCES, _ALL_EIGHT_NAMES),
        ids=_ALL_EIGHT_NAMES,
    )
    def test_archetype_name_matches(self, instance, expected_name):
        assert instance.name == expected_name

    def test_all_names_unique(self):
        names = [a.name for a in ALL_ARCHETYPES]
        assert len(names) == len(set(names))


# ── Innate flags ───────────────────────────────────────────────────────


class TestInnateFlags:
    """Verify that supernatural innate traits are correctly assigned."""

    def test_only_eidolon_has_phase_thickness(self):
        for arch in ALL_ARCHETYPES:
            if arch is EIDOLON:
                assert arch.phase_thickness > 0, "Eidolon should phase through walls"
            else:
                assert arch.phase_thickness == 0, (
                    f"{arch.name} should not have phase_thickness"
                )

    def test_only_mole_tamer_has_familiar_capacity(self):
        for arch in ALL_ARCHETYPES:
            if arch is MOLE_TAMER:
                assert arch.familiar_capacity > 0, (
                    "Mole Tamer should control familiars"
                )
            else:
                assert arch.familiar_capacity == 0, (
                    f"{arch.name} should not have familiar_capacity"
                )

    def test_only_hero_is_dramatic(self):
        for arch in ALL_ARCHETYPES:
            if arch is HERO:
                assert arch.dramatic is True, "Hero should be dramatic"
            else:
                assert arch.dramatic is False, (
                    f"{arch.name} should not be dramatic"
                )


# ── Objective weights ──────────────────────────────────────────────────


class TestObjectiveWeights:
    """Verify objective_weights on every archetype are well-formed."""

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_weights_are_3_tuple(self, arch):
        assert isinstance(arch.objective_weights, tuple)
        assert len(arch.objective_weights) == 3

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_weights_sum_to_approximately_one(self, arch):
        total = sum(arch.objective_weights)
        assert total == pytest.approx(1.0, abs=0.01), (
            f"{arch.name} objective_weights sum to {total}, expected ~1.0"
        )

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_weights_are_non_negative(self, arch):
        for w in arch.objective_weights:
            assert w >= 0.0, f"{arch.name} has negative objective weight {w}"


# ── IntruderObjective enum ─────────────────────────────────────────────


class TestIntruderObjective:
    """Verify the IntruderObjective enum has expected members."""

    def test_has_destroy_core(self):
        assert hasattr(IntruderObjective, "DESTROY_CORE")

    def test_has_explore(self):
        assert hasattr(IntruderObjective, "EXPLORE")

    def test_has_pillage(self):
        assert hasattr(IntruderObjective, "PILLAGE")

    def test_exactly_three_members(self):
        assert len(IntruderObjective) == 3


# ── IntruderStatus enum ───────────────────────────────────────────────


class TestIntruderStatus:
    """Verify the IntruderStatus enum has expected members."""

    def test_has_grunt(self):
        assert hasattr(IntruderStatus, "GRUNT")

    def test_has_veteran(self):
        assert hasattr(IntruderStatus, "VETERAN")

    def test_has_elite(self):
        assert hasattr(IntruderStatus, "ELITE")

    def test_has_champion(self):
        assert hasattr(IntruderStatus, "CHAMPION")

    def test_exactly_four_members(self):
        assert len(IntruderStatus) == 4


# ── STATUS_TRUST dict ─────────────────────────────────────────────────


class TestStatusTrust:
    """Verify STATUS_TRUST covers all IntruderStatus members."""

    def test_all_statuses_have_trust_value(self):
        for status in IntruderStatus:
            assert status in STATUS_TRUST, f"{status.name} missing from STATUS_TRUST"

    def test_trust_values_are_positive(self):
        for status, trust in STATUS_TRUST.items():
            assert trust > 0, f"{status.name} has non-positive trust {trust}"

    def test_trust_increases_with_rank(self):
        statuses = [
            IntruderStatus.GRUNT,
            IntruderStatus.VETERAN,
            IntruderStatus.ELITE,
            IntruderStatus.CHAMPION,
        ]
        for i in range(len(statuses) - 1):
            lower = STATUS_TRUST[statuses[i]]
            higher = STATUS_TRUST[statuses[i + 1]]
            assert higher > lower, (
                f"{statuses[i+1].name} trust ({higher}) should exceed "
                f"{statuses[i].name} trust ({lower})"
            )


# ── Frozen dataclass ──────────────────────────────────────────────────


class TestArchetypeFrozen:
    """Verify archetypes are immutable (frozen dataclass)."""

    def test_cannot_modify_hp(self):
        with pytest.raises(AttributeError):
            EXPLORER.hp = 999  # type: ignore[misc]

    def test_cannot_modify_name(self):
        with pytest.raises(AttributeError):
            HERO.name = "Villain"  # type: ignore[misc]
