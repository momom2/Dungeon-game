"""Tests for the familiar sub-entity system (Mole Tamer familiars).

Dependencies: intruders.familiar, intruders.agent, intruders.archetypes,
    intruders.equipment, intruders.personal_map, utils.rng, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.familiar import (
    Familiar,
    FamiliarState,
    spawn_familiars,
    order_dig,
    recall_familiar,
    check_unruliness,
)
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    MOLE_TAMER,
    EXPLORER,
    IntruderObjective,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.utils.rng import SeededRNG
import dungeon_builder.config as _cfg


def _make_tamer(x=5, y=5, z=3) -> Intruder:
    """Create a Mole Tamer intruder at the given position."""
    return Intruder(
        intruder_id=1,
        x=x, y=y, z=z,
        archetype=MOLE_TAMER,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=PersonalMap(),
    )


# ── Familiar creation ─────────────────────────────────────────────────


class TestFamiliarCreation:
    """Verify Familiar constructor sets initial state correctly."""

    def test_created_at_specified_position(self):
        f = Familiar(familiar_id=10, owner_id=1, x=5, y=10, z=3)
        assert f.pos == (5, 10, 3)

    def test_initial_state_is_following(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        assert f.state == FamiliarState.FOLLOWING

    def test_initial_hp_from_config(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        assert f.hp == _cfg.FAMILIAR_HP
        assert f.max_hp == _cfg.FAMILIAR_HP

    def test_initial_unruliness_zero(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        assert f.unruliness == 0.0

    def test_alive_when_created(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        assert f.alive is True

    def test_id_and_owner_set(self):
        f = Familiar(familiar_id=42, owner_id=7, x=0, y=0, z=0)
        assert f.id == 42
        assert f.owner_id == 7


# ── spawn_familiars() ─────────────────────────────────────────────────


class TestSpawnFamiliars:
    """Verify spawn_familiars creates the correct number at owner position."""

    def test_creates_correct_count(self):
        tamer = _make_tamer(x=5, y=10, z=3)
        familiars = spawn_familiars(tamer, next_id_start=100)
        assert len(familiars) == MOLE_TAMER.familiar_capacity

    def test_familiars_at_tamer_position(self):
        tamer = _make_tamer(x=5, y=10, z=3)
        familiars = spawn_familiars(tamer, next_id_start=100)
        for f in familiars:
            assert f.pos == (5, 10, 3)

    def test_familiars_have_sequential_ids(self):
        tamer = _make_tamer()
        familiars = spawn_familiars(tamer, next_id_start=100)
        for i, f in enumerate(familiars):
            assert f.id == 100 + i

    def test_familiars_reference_tamer_id(self):
        tamer = _make_tamer()
        familiars = spawn_familiars(tamer, next_id_start=100)
        for f in familiars:
            assert f.owner_id == tamer.id

    def test_non_tamer_archetype_spawns_none(self):
        """An Explorer with familiar_capacity=0 spawns no familiars."""
        explorer = Intruder(
            intruder_id=2,
            x=0, y=0, z=0,
            archetype=EXPLORER,
            objective=IntruderObjective.EXPLORE,
            personal_map=PersonalMap(),
        )
        familiars = spawn_familiars(explorer, next_id_start=200)
        assert len(familiars) == 0


# ── Familiar.take_damage() and death ──────────────────────────────────


class TestFamiliarDamage:
    """Verify take_damage clamps HP and transitions to DEAD."""

    def test_take_damage_reduces_hp(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        initial_hp = f.hp
        f.take_damage(5)
        assert f.hp == initial_hp - 5

    def test_lethal_damage_sets_dead(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.take_damage(f.hp + 100)
        assert f.hp == 0
        assert f.state == FamiliarState.DEAD
        assert f.alive is False

    def test_exact_lethal_damage(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.take_damage(f.hp)
        assert f.hp == 0
        assert f.state == FamiliarState.DEAD

    def test_hp_never_goes_negative(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.take_damage(9999)
        assert f.hp == 0


# ── check_unruliness() ────────────────────────────────────────────────


class TestCheckUnruliness:
    """Verify unruliness checking behavior."""

    def test_below_threshold_returns_false(self):
        """A familiar below the unruly threshold should never trigger."""
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.unruliness = _cfg.FAMILIAR_UNRULY_THRESHOLD - 0.1
        rng = SeededRNG(42)
        assert check_unruliness(f, rng) is False
        assert f.state == FamiliarState.FOLLOWING

    def test_at_max_unruliness_triggers(self):
        """A familiar at unruliness=1.0 will always trigger (rng.random() < 1.0)."""
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.unruliness = 1.0
        # At unruliness=1.0, rng.random() < 1.0 is always True
        rng = SeededRNG(42)
        triggered = check_unruliness(f, rng)
        assert triggered is True
        assert f.state == FamiliarState.UNRULY

    def test_zero_unruliness_never_triggers(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.unruliness = 0.0
        rng = SeededRNG(42)
        assert check_unruliness(f, rng) is False


# ── order_dig() ───────────────────────────────────────────────────────


class TestOrderDig:
    """Verify order_dig transitions state correctly."""

    def test_following_familiar_transitions_to_digging(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        assert f.state == FamiliarState.FOLLOWING
        target = (3, 4, 5)
        order_dig(f, target)
        assert f.state == FamiliarState.DIGGING
        assert f.dig_target == target

    def test_order_dig_clears_path(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.path = [(1, 1, 1), (2, 2, 2)]
        f.path_index = 1
        order_dig(f, (3, 4, 5))
        assert f.path is None
        assert f.path_index == 0

    def test_order_dig_ignored_if_not_following(self):
        """Only FOLLOWING familiars accept dig orders."""
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.DIGGING
        f.dig_target = (1, 1, 1)
        order_dig(f, (9, 9, 9))
        assert f.dig_target == (1, 1, 1)  # Unchanged

    def test_order_dig_ignored_if_dead(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.DEAD
        order_dig(f, (3, 4, 5))
        assert f.state == FamiliarState.DEAD


# ── recall_familiar() ─────────────────────────────────────────────────


class TestRecallFamiliar:
    """Verify recall_familiar transitions state back to FOLLOWING."""

    def test_recall_from_digging(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.DIGGING
        f.dig_target = (3, 4, 5)
        recall_familiar(f)
        assert f.state == FamiliarState.FOLLOWING
        assert f.dig_target is None

    def test_recall_clears_path(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.DIGGING
        f.path = [(1, 1, 1)]
        recall_familiar(f)
        assert f.path is None
        assert f.path_index == 0

    def test_recall_from_following_is_noop(self):
        """Recalling a FOLLOWING familiar keeps it FOLLOWING."""
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.FOLLOWING
        recall_familiar(f)
        assert f.state == FamiliarState.FOLLOWING

    def test_recall_ignored_if_dead(self):
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.DEAD
        recall_familiar(f)
        assert f.state == FamiliarState.DEAD

    def test_recall_ignored_if_unruly(self):
        """Unruly familiars cannot be recalled."""
        f = Familiar(familiar_id=10, owner_id=1, x=0, y=0, z=0)
        f.state = FamiliarState.UNRULY
        recall_familiar(f)
        assert f.state == FamiliarState.UNRULY
