"""Tests for the intruder party system.

Dependencies: intruders.party, intruders.archetypes, intruders.agent,
    intruders.personal_map, intruders.equipment, utils.rng, config
Dependents: (none)
"""

import pytest

from dungeon_builder.intruders.party import (
    Party,
    PartyTemplate,
    choose_template,
    generate_composition,
    ALL_TEMPLATES,
    SCOUTING_BAND,
    WAR_PARTY,
    SIEGE_COMPANY,
    ARCANE_EXPEDITION,
    HEROS_RETINUE,
    EIDOLON_PAIR,
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
    IntruderObjective,
    IntruderStatus,
    ArchetypeStats,
)
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.equipment import Equipment
from dungeon_builder.utils.rng import SeededRNG
import dungeon_builder.config as _cfg


# ── Helpers ────────────────────────────────────────────────────────────


def _make(
    intruder_id: int,
    arch=EXPLORER,
    x: int = 0,
    y: int = 0,
    z: int = 0,
    objective=IntruderObjective.DESTROY_CORE,
    status: IntruderStatus = IntruderStatus.GRUNT,
) -> Intruder:
    return Intruder(
        intruder_id, x, y, z, arch, objective, PersonalMap(),
        status=status,
    )


def _make_rng(seed: int = 42) -> SeededRNG:
    return SeededRNG(seed)


# ── Template existence tests ──────────────────────────────────────────


class TestTemplateExistence:
    """Verify all six party templates are defined and accessible."""

    def test_scouting_band_exists(self):
        assert SCOUTING_BAND is not None
        assert SCOUTING_BAND.name == "Scouting Band"

    def test_war_party_exists(self):
        assert WAR_PARTY is not None
        assert WAR_PARTY.name == "War Party"

    def test_siege_company_exists(self):
        assert SIEGE_COMPANY is not None
        assert SIEGE_COMPANY.name == "Siege Company"

    def test_arcane_expedition_exists(self):
        assert ARCANE_EXPEDITION is not None
        assert ARCANE_EXPEDITION.name == "Arcane Expedition"

    def test_heros_retinue_exists(self):
        assert HEROS_RETINUE is not None
        assert HEROS_RETINUE.name == "Hero's Retinue"

    def test_eidolon_pair_exists(self):
        assert EIDOLON_PAIR is not None
        assert EIDOLON_PAIR.name == "Eidolon Pair"


class TestAllTemplates:
    """Verify ALL_TEMPLATES contains all 6 templates."""

    def test_all_templates_has_six(self):
        assert len(ALL_TEMPLATES) == 6

    def test_all_templates_contains_each(self):
        assert SCOUTING_BAND in ALL_TEMPLATES
        assert WAR_PARTY in ALL_TEMPLATES
        assert SIEGE_COMPANY in ALL_TEMPLATES
        assert ARCANE_EXPEDITION in ALL_TEMPLATES
        assert HEROS_RETINUE in ALL_TEMPLATES
        assert EIDOLON_PAIR in ALL_TEMPLATES

    def test_all_templates_weights_sum_to_1(self):
        total = sum(t.weight for t in ALL_TEMPLATES)
        assert total == pytest.approx(1.0)

    def test_choose_template_returns_valid_template(self):
        rng = _make_rng()
        for _ in range(50):
            tmpl = choose_template(rng)
            assert tmpl in ALL_TEMPLATES


# ── generate_composition tests ────────────────────────────────────────


class TestGenerateComposition:
    """Verify generate_composition returns valid compositions."""

    def test_returns_non_empty_list(self):
        rng = _make_rng(99)
        for tmpl in ALL_TEMPLATES:
            comp = generate_composition(tmpl, rng)
            assert isinstance(comp, list)
            assert len(comp) > 0

    def test_returns_archetype_stats(self):
        rng = _make_rng(42)
        for tmpl in ALL_TEMPLATES:
            comp = generate_composition(tmpl, rng)
            for member in comp:
                assert isinstance(member, ArchetypeStats)

    def test_composition_sizes_respect_slot_bounds(self):
        """Generated compositions respect min/max counts from slot definitions."""
        rng = _make_rng(99)
        for tmpl in ALL_TEMPLATES:
            for _ in range(20):
                comp = generate_composition(tmpl, rng)
                min_total = sum(s.min_count for s in tmpl.slots)
                max_total = sum(s.max_count for s in tmpl.slots)
                assert min_total <= len(comp) <= max_total, (
                    f"{tmpl.name}: got {len(comp)}, "
                    f"expected [{min_total}, {max_total}]"
                )

    def test_scouting_band_has_explorers(self):
        rng = _make_rng(1)
        comp = generate_composition(SCOUTING_BAND, rng)
        names = [a.name for a in comp]
        assert "Explorer" in names

    def test_siege_company_has_mole_tamer(self):
        rng = _make_rng(1)
        comp = generate_composition(SIEGE_COMPANY, rng)
        names = [a.name for a in comp]
        assert "Mole Tamer" in names

    def test_eidolon_pair_has_two_eidolons(self):
        rng = _make_rng(1)
        comp = generate_composition(EIDOLON_PAIR, rng)
        assert len(comp) == 2
        assert all(a.name == "Eidolon" for a in comp)

    def test_heros_retinue_has_hero(self):
        rng = _make_rng(1)
        comp = generate_composition(HEROS_RETINUE, rng)
        names = [a.name for a in comp]
        assert "Hero" in names


# ── Party creation ────────────────────────────────────────────────────


class TestPartyCreation:
    """Party creation assigns party_id to all members."""

    def test_party_assigns_party_id(self):
        m1 = _make(1, EXPLORER)
        m2 = _make(2, INQUISITOR)
        party = Party(42, [m1, m2])
        assert m1.party_id == 42
        assert m2.party_id == 42

    def test_party_len(self):
        members = [_make(i, EXPLORER) for i in range(5)]
        party = Party(1, members)
        assert len(party) == 5

    def test_party_repr(self):
        members = [_make(1, EXPLORER), _make(2, GLOOMWARDEN)]
        party = Party(1, members)
        r = repr(party)
        assert "Party" in r
        assert "members=2" in r
        assert "alive=2" in r

    def test_is_wiped(self):
        m1 = _make(1, EXPLORER)
        party = Party(1, [m1])
        assert not party.is_wiped
        m1.state = IntruderState.DEAD
        assert party.is_wiped


# ── Leader election ───────────────────────────────────────────────────


class TestLeaderElection:
    """_elect_leader picks the member with highest status, then loyalty."""

    def test_leader_is_highest_status(self):
        grunt = _make(1, EXPLORER, status=IntruderStatus.GRUNT)
        veteran = _make(2, INQUISITOR, status=IntruderStatus.VETERAN)
        grunt.state = IntruderState.ADVANCING
        veteran.state = IntruderState.ADVANCING
        party = Party(100, [grunt, veteran])
        assert party.leader is not None
        assert party.leader.id == 2  # VETERAN > GRUNT

    def test_leader_same_status_picks_highest_loyalty(self):
        # Gloomwarden has loyalty=1.0, Explorer has loyalty=0.2
        m1 = _make(1, EXPLORER)
        m2 = _make(2, GLOOMWARDEN)
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        party = Party(100, [m1, m2])
        assert party.leader is not None
        assert party.leader.id == 2  # Gloomwarden (loyalty=1.0)

    def test_leader_tiebreak_by_id(self):
        # Two members with same archetype (same status, same loyalty)
        m1 = _make(5, EXPLORER)
        m2 = _make(3, EXPLORER)
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        party = Party(100, [m1, m2])
        assert party.leader is not None
        assert party.leader.id == 3  # Lower id wins tiebreak

    def test_leader_none_when_all_dead(self):
        m1 = _make(1, EXPLORER)
        party = Party(1, [m1])
        m1.state = IntruderState.DEAD
        party._elect_leader()
        assert party.leader is None

    def test_leader_reelection_on_death(self):
        m_gloom = _make(1, GLOOMWARDEN)  # loyalty=1.0
        m_explorer = _make(2, EXPLORER)   # loyalty=0.2
        m_gloom.state = IntruderState.ADVANCING
        m_explorer.state = IntruderState.ADVANCING
        party = Party(100, [m_gloom, m_explorer])
        assert party.leader.id == 1

        m_gloom.state = IntruderState.DEAD
        party.on_member_death(m_gloom)
        assert party.leader.id == 2


# ── Objective voting ──────────────────────────────────────────────────


class TestObjectiveVoting:
    """Party objective comes from weighted vote of alive member archetype weights."""

    def test_all_inquisitors_vote_destroy(self):
        # Inquisitor objective_weights=(0.9, 0.0, 0.1) -> DESTROY_CORE
        members = [_make(i, INQUISITOR) for i in range(3)]
        for m in members:
            m.state = IntruderState.ADVANCING
        party = Party(100, members)
        assert party.objective == IntruderObjective.DESTROY_CORE

    def test_all_explorers_vote_explore(self):
        # Explorer objective_weights=(0.1, 0.5, 0.4) -> EXPLORE
        members = [_make(i, EXPLORER) for i in range(3)]
        for m in members:
            m.state = IntruderState.ADVANCING
        party = Party(100, members)
        assert party.objective == IntruderObjective.EXPLORE

    def test_mixed_party_weighted_vote(self):
        # 2 Inquisitors (0.9, 0.0, 0.1 each) + 1 Explorer (0.1, 0.5, 0.4)
        # destroy = 0.9+0.9+0.1 = 1.9, explore = 0.0+0.0+0.5 = 0.5, pillage = 0.1+0.1+0.4 = 0.6
        # -> DESTROY_CORE
        members = [_make(1, INQUISITOR), _make(2, INQUISITOR), _make(3, EXPLORER)]
        for m in members:
            m.state = IntruderState.ADVANCING
        party = Party(100, members)
        assert party.objective == IntruderObjective.DESTROY_CORE

    def test_revote_after_death(self):
        # 1 Inquisitor (0.9, 0.0, 0.1) + 2 Explorers (0.1, 0.5, 0.4 each)
        # Initial: destroy=0.9+0.1+0.1=1.1, explore=0.0+0.5+0.5=1.0, pillage=0.1+0.4+0.4=0.9
        # -> DESTROY_CORE
        m_inq = _make(1, INQUISITOR)
        m_e1 = _make(2, EXPLORER)
        m_e2 = _make(3, EXPLORER)
        for m in (m_inq, m_e1, m_e2):
            m.state = IntruderState.ADVANCING
        party = Party(100, [m_inq, m_e1, m_e2])
        assert party.objective == IntruderObjective.DESTROY_CORE

        # Kill inquisitor -> destroy=0.1+0.1=0.2, explore=0.5+0.5=1.0, pillage=0.4+0.4=0.8
        # -> EXPLORE
        m_inq.state = IntruderState.DEAD
        party.on_member_death(m_inq)
        assert party.objective == IntruderObjective.EXPLORE


# ── Map sharing ───────────────────────────────────────────────────────


class TestMapSharing:
    """share_maps() merges personal maps when members are in range."""

    def test_nearby_members_share_maps(self):
        m1 = _make(1, EXPLORER, x=0, y=0, z=0)
        m2 = _make(2, INQUISITOR, x=1, y=0, z=0)  # distance=1 <= MAP_SHARE_RANGE
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        m1.personal_map.reveal(5, 5, 5, 2)  # some vtype
        m2.personal_map.reveal(10, 10, 10, 1)  # some vtype

        party = Party(100, [m1, m2])
        party.share_maps()

        # Both should know about each other's cells
        assert m1.personal_map.is_revealed(10, 10, 10)
        assert m2.personal_map.is_revealed(5, 5, 5)

    def test_distant_members_do_not_share(self):
        m1 = _make(1, EXPLORER, x=0, y=0, z=0)
        m2 = _make(2, INQUISITOR, x=0, y=0, z=_cfg.MAP_SHARE_RANGE + 1)
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        m1.personal_map.reveal(5, 5, 5, 2)

        party = Party(100, [m1, m2])
        party.share_maps()

        assert not m2.personal_map.is_revealed(5, 5, 5)

    def test_dead_members_excluded_from_sharing(self):
        m1 = _make(1, EXPLORER, x=0, y=0, z=0)
        m2 = _make(2, EXPLORER, x=1, y=0, z=0)
        m1.state = IntruderState.ADVANCING
        m1.personal_map.reveal(5, 5, 5, 2)
        m2.state = IntruderState.DEAD

        party = Party(100, [m1, m2])
        party.share_maps()

        assert not m2.personal_map.is_revealed(5, 5, 5)


# ── Betrayal ──────────────────────────────────────────────────────────


class TestBetrayal:
    """check_betrayals(): high greed + low loyalty + treasure = betrayal."""

    def test_greedy_near_treasure_can_betray(self):
        # Explorer: greed=0.7, loyalty=0.2 -> chance = 0.7 * (1-0.2) = 0.56
        explorer = _make(1, EXPLORER, x=0, y=0, z=0)
        tank = _make(2, INQUISITOR, x=1, y=0, z=0)  # greed=0.05
        explorer.state = IntruderState.ADVANCING
        tank.state = IntruderState.ADVANCING

        treasure_adj = {1: True, 2: False}

        # Try many seeds to trigger betrayal
        betrayed = False
        for seed in range(200):
            e = _make(1, EXPLORER, x=0, y=0, z=0)
            t = _make(2, INQUISITOR, x=1, y=0, z=0)
            e.state = IntruderState.ADVANCING
            t.state = IntruderState.ADVANCING
            p = Party(100, [e, t])
            rng = _make_rng(seed)
            betrayers = p.check_betrayals(treasure_adj, rng)
            if betrayers:
                betrayed = True
                break

        assert betrayed

    def test_no_greed_never_betrays(self):
        # Hero: greed=0.0
        hero = _make(1, HERO, x=0, y=0, z=0)
        hero.state = IntruderState.ADVANCING
        party = Party(100, [hero])
        treasure_adj = {1: True}

        rng = _make_rng(42)
        for _ in range(100):
            betrayers = party.check_betrayals(treasure_adj, rng)
            assert len(betrayers) == 0

    def test_not_adjacent_to_treasure_never_betrays(self):
        explorer = _make(1, EXPLORER, x=0, y=0, z=0)
        explorer.state = IntruderState.ADVANCING
        party = Party(100, [explorer])
        treasure_adj = {1: False}

        rng = _make_rng(42)
        for _ in range(100):
            betrayers = party.check_betrayals(treasure_adj, rng)
            assert len(betrayers) == 0

    def test_betrayer_switches_to_pillage(self):
        treasure_adj = {1: True, 2: False}

        betrayed_member = None
        for seed in range(1000):
            e = _make(1, EXPLORER, x=0, y=0, z=0)
            t = _make(2, INQUISITOR, x=1, y=0, z=0)
            e.state = IntruderState.ADVANCING
            t.state = IntruderState.ADVANCING
            p = Party(100, [e, t])
            rng = _make_rng(seed)
            betrayers = p.check_betrayals(treasure_adj, rng)
            if betrayers:
                betrayed_member = betrayers[0]
                break

        assert betrayed_member is not None
        assert betrayed_member.objective == IntruderObjective.PILLAGE
        assert betrayed_member.party_id is None

    def test_betrayer_removed_from_party(self):
        treasure_adj = {1: True, 2: False}

        for seed in range(1000):
            e = _make(1, EXPLORER, x=0, y=0, z=0)
            t = _make(2, INQUISITOR, x=1, y=0, z=0)
            e.state = IntruderState.ADVANCING
            t.state = IntruderState.ADVANCING
            p = Party(100, [e, t])
            rng = _make_rng(seed)
            betrayers = p.check_betrayals(treasure_adj, rng)
            if betrayers:
                assert len(p.members) == 1
                assert p.members[0].id == 2  # Only tank remains
                break


# ── Member death ──────────────────────────────────────────────────────


class TestOnMemberDeath:
    """on_member_death() triggers morale penalty and re-election."""

    def test_morale_penalty_on_death(self):
        m1 = _make(1, EXPLORER)
        m2 = _make(2, INQUISITOR)
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        party = Party(100, [m1, m2])
        initial_morale = m1.morale

        m2.state = IntruderState.DEAD
        party.on_member_death(m2)

        assert m1.morale == pytest.approx(
            max(0.0, initial_morale - _cfg.MORALE_ALLY_DEATH_PENALTY),
        )

    def test_reelection_after_death(self):
        m1 = _make(1, GLOOMWARDEN)  # loyalty=1.0
        m2 = _make(2, EXPLORER)      # loyalty=0.2
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        party = Party(100, [m1, m2])
        assert party.leader.id == 1

        m1.state = IntruderState.DEAD
        party.on_member_death(m1)
        assert party.leader.id == 2

    def test_revote_objective_after_death(self):
        m_inq = _make(1, INQUISITOR)
        m_e1 = _make(2, EXPLORER)
        m_e2 = _make(3, EXPLORER)
        for m in (m_inq, m_e1, m_e2):
            m.state = IntruderState.ADVANCING
        party = Party(100, [m_inq, m_e1, m_e2])
        assert party.objective == IntruderObjective.DESTROY_CORE

        m_inq.state = IntruderState.DEAD
        party.on_member_death(m_inq)
        # With 2 explorers left, should be EXPLORE
        assert party.objective == IntruderObjective.EXPLORE


# ── Morale update ─────────────────────────────────────────────────────


class TestUpdateMorale:
    """update_morale() drifts toward MORALE_BASE."""

    def test_morale_drifts_upward_toward_base(self):
        m1 = _make(1, EXPLORER)
        m1.state = IntruderState.ADVANCING
        m1.morale = 0.3  # Below MORALE_BASE
        party = Party(1, [m1])

        for t in range(200):
            party.update_morale(tick=t)

        # Should have drifted toward MORALE_BASE
        assert m1.morale > 0.3

    def test_morale_drifts_downward_toward_base(self):
        m1 = _make(1, EXPLORER)
        m1.state = IntruderState.ADVANCING
        m1.morale = 1.0  # Above MORALE_BASE
        party = Party(1, [m1])

        for t in range(200):
            party.update_morale(tick=t)

        # Should have drifted downward (toward MORALE_BASE)
        assert m1.morale < 1.0

    def test_leader_alive_bonus_applies(self):
        m1 = _make(1, EXPLORER)
        m2 = _make(2, INQUISITOR)
        m1.state = IntruderState.ADVANCING
        m2.state = IntruderState.ADVANCING
        party = Party(1, [m1, m2])

        # Set morale slightly below base
        for m in party.alive_members:
            m.morale = _cfg.MORALE_BASE - 0.05

        party.update_morale(tick=1)

        # Leader is alive, so members get MORALE_LEADER_BONUS
        for m in party.alive_members:
            assert m.morale > _cfg.MORALE_BASE - 0.05

    def test_morale_clamped_between_zero_and_one(self):
        m1 = _make(1, EXPLORER)
        m1.state = IntruderState.ADVANCING
        m1.morale = 0.999
        party = Party(1, [m1])
        party.update_morale(tick=1)
        assert 0.0 <= m1.morale <= 1.0
