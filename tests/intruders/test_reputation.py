"""Tests for dungeon_builder.intruders.reputation -- dungeon reputation system.

Dependencies: intruders.reputation, core.event_bus, config
Dependents: (none)
"""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.intruders.reputation import DungeonReputation, ReputationProfile
from dungeon_builder.config import (
    REPUTATION_DEADLY_LETHALITY,
    REPUTATION_RICH_RICHNESS,
    REPUTATION_UNKNOWN_THRESHOLD,
    REPUTATION_DEADLY_MODIFIER,
    REPUTATION_RICH_MODIFIER,
    REPUTATION_UNKNOWN_MODIFIER,
    REPUTATION_DEADLY_LOYALTY,
    REPUTATION_RICH_LOYALTY,
    LEVEL_DEADLY_SHIFT,
)


class _FakeIntruder:
    """Minimal intruder stub for reputation tests."""

    def __init__(self, loot_count: int = 0):
        self.loot_count = loot_count


def _make_reputation():
    bus = EventBus()
    rep = DungeonReputation(bus)
    return bus, rep


# ---------- ReputationProfile ----------


class TestReputationProfile:
    def test_frozen_dataclass(self):
        p = ReputationProfile(lethality=0.5, richness=0.3)
        assert p.lethality == 0.5
        assert p.richness == 0.3
        with pytest.raises(AttributeError):
            p.lethality = 0.9  # type: ignore[misc]


# ---------- DungeonReputation basics ----------


class TestDungeonReputationBasics:
    def test_initial_profile_moderate(self):
        """With no outcomes, lethality defaults to 0.5, richness to 0.0."""
        _, rep = _make_reputation()
        profile = rep.get_profile()
        assert profile.lethality == 0.5
        assert profile.richness == 0.0

    def test_subscribes_to_events(self):
        bus, rep = _make_reputation()
        # Verify subscriptions exist by checking that events don't crash
        bus.publish("intruder_died", intruder=None)
        bus.publish("intruder_escaped", intruder=None)
        bus.publish("intruder_collected_treasure")
        # No assertion needed -- we just verify no exceptions


# ---------- Counter tracking ----------


class TestCounterTracking:
    def test_intruder_died_increments_kills(self):
        bus, rep = _make_reputation()
        bus.publish("intruder_died", intruder=None)
        assert rep.total_kills == 1

    def test_intruder_escaped_increments_escapes(self):
        bus, rep = _make_reputation()
        bus.publish("intruder_escaped", intruder=None)
        assert rep.total_escapes == 1

    def test_escaped_with_loot_counted(self):
        bus, rep = _make_reputation()
        looter = _FakeIntruder(loot_count=3)
        bus.publish("intruder_escaped", intruder=looter)
        assert rep.total_escapes == 1
        assert rep.parties_with_loot_escaped == 1

    def test_escaped_without_loot_not_counted_as_loot_escape(self):
        bus, rep = _make_reputation()
        no_loot = _FakeIntruder(loot_count=0)
        bus.publish("intruder_escaped", intruder=no_loot)
        assert rep.total_escapes == 1
        assert rep.parties_with_loot_escaped == 0

    def test_treasure_collected_increments(self):
        bus, rep = _make_reputation()
        bus.publish("intruder_collected_treasure")
        assert rep.total_treasure_lost == 1

    def test_party_wiped_counted(self):
        _, rep = _make_reputation()
        rep.on_party_wiped()
        assert rep.total_parties_wiped == 1


# ---------- Profile computation ----------


class TestProfileComputation:
    def test_high_lethality(self):
        bus, rep = _make_reputation()
        for _ in range(9):
            bus.publish("intruder_died", intruder=None)
        bus.publish("intruder_escaped", intruder=None)
        profile = rep.get_profile()
        assert profile.lethality == pytest.approx(0.9)

    def test_high_richness(self):
        bus, rep = _make_reputation()
        for _ in range(3):
            bus.publish("intruder_died", intruder=None)
        for _ in range(7):
            bus.publish("intruder_collected_treasure")
        profile = rep.get_profile()
        # richness = 7 / (3 + 7) = 0.7
        assert profile.richness == pytest.approx(0.7)

    def test_lethality_capped_at_one(self):
        bus, rep = _make_reputation()
        for _ in range(10):
            bus.publish("intruder_died", intruder=None)
        profile = rep.get_profile()
        assert profile.lethality == pytest.approx(1.0)

    def test_zero_kills_and_escapes(self):
        _, rep = _make_reputation()
        profile = rep.get_profile()
        assert profile.lethality == 0.5  # default moderate


# ---------- Modifier outputs ----------


class TestModifierOutputs:
    def _make_deadly_rep(self):
        """Helper: create a reputation with high lethality."""
        bus, rep = _make_reputation()
        # Need enough outcomes to exceed REPUTATION_UNKNOWN_THRESHOLD
        for _ in range(REPUTATION_UNKNOWN_THRESHOLD + 5):
            bus.publish("intruder_died", intruder=None)
        return bus, rep

    def _make_rich_rep(self):
        """Helper: create a reputation with high richness."""
        bus, rep = _make_reputation()
        # Need outcomes above threshold + high richness
        for _ in range(3):
            bus.publish("intruder_died", intruder=None)
        for _ in range(REPUTATION_UNKNOWN_THRESHOLD):
            bus.publish("intruder_escaped", intruder=None)
        for _ in range(10):
            bus.publish("intruder_collected_treasure")
        return bus, rep

    def test_objective_modifier_unknown(self):
        _, rep = _make_reputation()
        # Too few outcomes
        assert rep.get_objective_modifier() == REPUTATION_UNKNOWN_MODIFIER

    def test_objective_modifier_deadly(self):
        _, rep = self._make_deadly_rep()
        profile = rep.get_profile()
        assert profile.lethality > REPUTATION_DEADLY_LETHALITY
        assert rep.get_objective_modifier() == REPUTATION_DEADLY_MODIFIER

    def test_objective_modifier_rich(self):
        _, rep = self._make_rich_rep()
        profile = rep.get_profile()
        assert profile.richness > REPUTATION_RICH_RICHNESS
        assert rep.get_objective_modifier() == REPUTATION_RICH_MODIFIER

    def test_template_weight_modifier_deadly(self):
        _, rep = self._make_deadly_rep()
        mods = rep.get_template_weight_modifier()
        assert "Siege Company" in mods
        assert mods["Siege Company"] > 0

    def test_template_weight_modifier_deadly_has_new_names(self):
        """Template weight modifier uses new template names."""
        _, rep = self._make_deadly_rep()
        mods = rep.get_template_weight_modifier()
        # Should use new names: "Siege Company", "War Party", "Scouting Band"
        assert "Siege Company" in mods
        assert "War Party" in mods
        assert "Scouting Band" in mods

    def test_loyalty_modifier_deadly(self):
        _, rep = self._make_deadly_rep()
        assert rep.get_loyalty_modifier() == pytest.approx(REPUTATION_DEADLY_LOYALTY)

    def test_loyalty_modifier_unknown(self):
        _, rep = _make_reputation()
        assert rep.get_loyalty_modifier() == 0.0

    def test_level_shift_above_half(self):
        _, rep = self._make_deadly_rep()
        profile = rep.get_profile()
        assert profile.lethality > 0.5
        shift = rep.get_level_shift()
        assert shift > 0.0


# ---------- get_dominant_threat ----------


class TestDominantThreat:
    def test_get_dominant_threat_returns_unknown(self):
        """get_dominant_threat() returns 'unknown' as stub."""
        _, rep = _make_reputation()
        assert rep.get_dominant_threat() == "unknown"

    def test_get_dominant_threat_still_unknown_after_events(self):
        """Even after many events, stub still returns 'unknown'."""
        bus, rep = _make_reputation()
        for _ in range(20):
            bus.publish("intruder_died", intruder=None)
        assert rep.get_dominant_threat() == "unknown"


# ---------- Event publishing ----------


class TestReputationEvents:
    def test_reputation_changed_event_published(self):
        bus, rep = _make_reputation()
        events = []
        bus.subscribe("reputation_changed", lambda **kw: events.append(kw))

        bus.publish("intruder_died", intruder=None)
        assert len(events) >= 1
        assert "lethality" in events[0]
        assert "richness" in events[0]
