"""Party system for intruder groups.

Intruders travel in parties of 2-8 members.  Each party has a composition
template, a leader, a collective objective (voted from member weights), and
mechanics for map sharing, morale, and betrayal.

Healing, shielding, and other support effects are equipment-driven — any
intruder with the right items can provide them.  There are no archetype-
specific party aura mechanics; all support is through the equipment system.

Dependencies: config, utils.rng, intruders.agent, intruders.archetypes
Dependents: core.save_system, intruders.decision, tests/intruders/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
    ArchetypeStats,
)
from dungeon_builder.config import (
    MAP_SHARE_RANGE,
    MAP_SHARE_INTERVAL,
    PARTY_WEIGHT_SCOUTING_BAND,
    PARTY_WEIGHT_WAR_PARTY,
    PARTY_WEIGHT_SIEGE_COMPANY,
    PARTY_WEIGHT_ARCANE_EXPEDITION,
    PARTY_WEIGHT_HEROS_RETINUE,
    PARTY_WEIGHT_EIDOLON_PAIR,
    MORALE_BASE,
    MORALE_LEADER_BONUS,
    MORALE_SUPPORT_TICK,
    MORALE_DRIFT_RATE,
    MORALE_ALLY_DEATH_PENALTY,
)

if TYPE_CHECKING:
    from dungeon_builder.intruders.agent import Intruder
    from dungeon_builder.utils.rng import SeededRNG


# ── Composition templates ──────────────────────────────────────────────

@dataclass(frozen=True)
class _MemberSlot:
    """One or more archetypes to choose from for a party slot."""
    choices: tuple[ArchetypeStats, ...]
    min_count: int
    max_count: int


@dataclass(frozen=True)
class PartyTemplate:
    """A weighted template describing a possible party composition."""
    name: str
    weight: float
    slots: tuple[_MemberSlot, ...]


SCOUTING_BAND = PartyTemplate(
    name="Scouting Band",
    weight=PARTY_WEIGHT_SCOUTING_BAND,
    slots=(
        _MemberSlot((EXPLORER,), 2, 3),
        _MemberSlot((GLOOMWARDEN,), 0, 1),
    ),
)

WAR_PARTY = PartyTemplate(
    name="War Party",
    weight=PARTY_WEIGHT_WAR_PARTY,
    slots=(
        _MemberSlot((INQUISITOR,), 1, 2),
        _MemberSlot((GLOOMWARDEN,), 1, 2),
        _MemberSlot((ALCHEMIST,), 0, 1),
    ),
)

SIEGE_COMPANY = PartyTemplate(
    name="Siege Company",
    weight=PARTY_WEIGHT_SIEGE_COMPANY,
    slots=(
        _MemberSlot((MOLE_TAMER,), 1, 1),
        _MemberSlot((INQUISITOR,), 1, 2),
        _MemberSlot((CARTOMANCER,), 0, 1),
    ),
)

ARCANE_EXPEDITION = PartyTemplate(
    name="Arcane Expedition",
    weight=PARTY_WEIGHT_ARCANE_EXPEDITION,
    slots=(
        _MemberSlot((CARTOMANCER,), 1, 2),
        _MemberSlot((ALCHEMIST,), 1, 1),
        _MemberSlot((EXPLORER,), 0, 1),
    ),
)

HEROS_RETINUE = PartyTemplate(
    name="Hero's Retinue",
    weight=PARTY_WEIGHT_HEROS_RETINUE,
    slots=(
        _MemberSlot((HERO,), 1, 1),
        _MemberSlot((INQUISITOR, GLOOMWARDEN, ALCHEMIST), 2, 3),
    ),
)

EIDOLON_PAIR = PartyTemplate(
    name="Eidolon Pair",
    weight=PARTY_WEIGHT_EIDOLON_PAIR,
    slots=(
        _MemberSlot((EIDOLON,), 2, 2),
    ),
)

ALL_TEMPLATES: tuple[PartyTemplate, ...] = (
    SCOUTING_BAND, WAR_PARTY, SIEGE_COMPANY,
    ARCANE_EXPEDITION, HEROS_RETINUE, EIDOLON_PAIR,
)


# ── Composition generation ─────────────────────────────────────────────

def _choose_from_templates(
    templates: tuple[PartyTemplate, ...], rng: SeededRNG,
) -> PartyTemplate:
    """Weighted random selection from a set of templates."""
    roll = rng.random()
    cumulative = 0.0
    for tmpl in templates:
        cumulative += tmpl.weight
        if roll < cumulative:
            return tmpl
    return templates[-1]


def choose_template(rng: SeededRNG) -> PartyTemplate:
    """Weighted random selection of a party template."""
    return _choose_from_templates(ALL_TEMPLATES, rng)


def generate_composition(
    template: PartyTemplate, rng: SeededRNG,
) -> list[ArchetypeStats]:
    """Generate a concrete list of archetypes from a party template.

    For each slot, a random count between min_count and max_count is chosen.
    For each member in that slot, a random archetype from the slot choices
    is picked.
    """
    result: list[ArchetypeStats] = []
    for slot in template.slots:
        count = rng.randint(slot.min_count, slot.max_count)
        for _ in range(count):
            result.append(rng.choice(slot.choices))
    return result


# ── Party class ────────────────────────────────────────────────────────

class Party:
    """A group of intruders traveling together.

    The party manages shared objectives, map merging, morale updates,
    betrayal checks, and leader election.  Support effects (healing,
    shielding) are equipment-driven and handled in decision.py.
    """

    __slots__ = (
        "id",
        "members",
        "_leader_id",
        "_objective",
        "_share_tick_counter",
    )

    def __init__(self, party_id: int, members: list[Intruder]) -> None:
        self.id = party_id
        self.members: list[Intruder] = list(members)
        self._leader_id: int | None = None
        self._objective: IntruderObjective | None = None
        self._share_tick_counter: int = MAP_SHARE_INTERVAL - 1

        # Assign party_id to all members
        for m in self.members:
            m.party_id = party_id

        # Initial elections
        self._elect_leader()
        self._vote_objective()

    # ── Leader election ────────────────────────────────────────────

    def _elect_leader(self) -> None:
        """Elect the alive member with highest status, then loyalty, as leader.

        Status (CHAMPION > ELITE > VETERAN > GRUNT) takes priority.
        Loyalty breaks ties within the same status.
        Intruder id breaks remaining ties for determinism.
        """
        alive = [m for m in self.members if m.alive]
        if not alive:
            self._leader_id = None
            return
        # Sort by (-status.value, -loyalty, id) -> highest status first
        best = min(alive, key=lambda m: (-m.status.value, -m.effective_loyalty, m.id))
        self._leader_id = best.id

    @property
    def leader(self) -> Intruder | None:
        """Return the current leader, or None if everyone is dead."""
        if self._leader_id is None:
            return None
        for m in self.members:
            if m.id == self._leader_id and m.alive:
                return m
        # Leader died since last election -> re-elect
        self._elect_leader()
        if self._leader_id is None:
            return None
        for m in self.members:
            if m.id == self._leader_id:
                return m
        return None

    # ── Objective voting ───────────────────────────────────────────

    def _vote_objective(
        self,
        reputation_modifier: tuple[float, float, float] | None = None,
    ) -> None:
        """Set party objective by weighted vote from alive members.

        Each member contributes its archetype's objective_weights, optionally
        shifted by a reputation modifier (destroy, explore, pillage offsets).
        The objective with the highest total weight wins.
        Leader breaks ties.
        """
        alive = [m for m in self.members if m.alive]
        if not alive:
            self._objective = IntruderObjective.DESTROY_CORE
            return

        mod = reputation_modifier or (0.0, 0.0, 0.0)
        totals = [0.0, 0.0, 0.0]  # destroy, explore, pillage
        for m in alive:
            w = m.archetype.objective_weights
            totals[0] += w[0] + mod[0]
            totals[1] += w[1] + mod[1]
            totals[2] += w[2] + mod[2]

        objectives = [
            IntruderObjective.DESTROY_CORE,
            IntruderObjective.EXPLORE,
            IntruderObjective.PILLAGE,
        ]

        max_val = max(totals)
        # Collect all objectives tied at max
        tied = [objectives[i] for i, v in enumerate(totals) if v == max_val]

        if len(tied) == 1:
            self._objective = tied[0]
        else:
            # Leader breaks the tie: pick whichever the leader prefers most
            leader = self.leader
            if leader is not None:
                lw = leader.archetype.objective_weights
                best = max(tied, key=lambda o: lw[objectives.index(o)])
                self._objective = best
            else:
                self._objective = tied[0]

    @property
    def objective(self) -> IntruderObjective:
        """The party's collective objective."""
        if self._objective is None:
            return IntruderObjective.DESTROY_CORE
        return self._objective

    # ── Alive helpers ──────────────────────────────────────────────

    @property
    def alive_members(self) -> list[Intruder]:
        return [m for m in self.members if m.alive]

    @property
    def alive_count(self) -> int:
        return sum(1 for m in self.members if m.alive)

    @property
    def is_wiped(self) -> bool:
        return self.alive_count == 0

    # ── Map sharing ────────────────────────────────────────────────

    def share_maps(self) -> None:
        """Merge personal maps of alive members within MAP_SHARE_RANGE cells.

        Distance is Chebyshev (max of |dx|, |dy|, |dz|) so members in
        adjacent cells share instantly.

        Throttled to run every MAP_SHARE_INTERVAL ticks.  Within each merge
        pass, generation-based skip in PersonalMap.merge() avoids redundant
        dict copies when nothing has changed.
        """
        self._share_tick_counter += 1
        if self._share_tick_counter < MAP_SHARE_INTERVAL:
            return
        self._share_tick_counter = 0

        alive = self.alive_members
        n = len(alive)
        if n < 2:
            return

        for i in range(n):
            for j in range(i + 1, n):
                a, b = alive[i], alive[j]
                dist = max(
                    abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z),
                )
                if dist <= MAP_SHARE_RANGE:
                    a.personal_map.merge(b.personal_map)
                    b.personal_map.merge(a.personal_map)

    # ── Member death ──────────────────────────────────────────────

    def on_member_death(self, dead: Intruder) -> None:
        """Handle a member's death.

        All alive members suffer a morale penalty from witnessing a death.
        Re-elects leader and re-votes objective after any death.
        """
        # Morale penalty for witnessing ally death
        for m in self.alive_members:
            m.morale = max(0.0, m.morale - MORALE_ALLY_DEATH_PENALTY)

        self._elect_leader()
        self._vote_objective()

    # ── Morale update ─────────────────────────────────────────────

    def update_morale(self, tick: int) -> None:
        """Update morale for all alive members each tick.

        - Leader alive bonus: +MORALE_LEADER_BONUS per tick
        - Support archetype nearby: +MORALE_SUPPORT_TICK per tick
        - Natural decay: drift toward MORALE_BASE
        """
        alive = self.alive_members
        leader = self.leader

        for m in alive:
            # Leader alive bonus
            if leader is not None:
                m.morale += MORALE_LEADER_BONUS

            # Natural drift toward MORALE_BASE
            if m.morale < MORALE_BASE:
                m.morale = min(MORALE_BASE, m.morale + MORALE_DRIFT_RATE)
            elif m.morale > MORALE_BASE:
                m.morale = max(MORALE_BASE, m.morale - MORALE_DRIFT_RATE)

            # Clamp
            m.morale = min(1.0, max(0.0, m.morale))

    # ── Betrayal ───────────────────────────────────────────────────

    def check_betrayals(
        self,
        treasure_adjacent: dict[int, bool],
        rng: SeededRNG,
    ) -> list[Intruder]:
        """Check each member for betrayal.

        *treasure_adjacent* maps intruder id -> whether that intruder is
        adjacent to a treasure cell.

        Betrayal chance per tick:
            greed x (1 - effective_loyalty) x treasure_factor
        where treasure_factor is 1.0 if adjacent to treasure, else 0.0.

        On betrayal: the intruder leaves the party, switches objective to
        PILLAGE, and its party_id is cleared.

        Returns a list of intruders who betrayed this tick.
        """
        betrayers: list[Intruder] = []
        alive = self.alive_members

        for m in alive:
            if m.archetype.greed <= 0.0:
                continue
            if not treasure_adjacent.get(m.id, False):
                continue

            chance = m.archetype.greed * (1.0 - m.effective_loyalty)
            if rng.random() < chance:
                betrayers.append(m)

        # Process betrayals
        for m in betrayers:
            m.objective = IntruderObjective.PILLAGE
            m.party_id = None
            self.members.remove(m)

        if betrayers:
            self._elect_leader()
            self._vote_objective()

        return betrayers

    # ── Dunder ─────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.members)

    def __repr__(self) -> str:
        alive = self.alive_count
        return (
            f"Party(id={self.id}, members={len(self.members)}, "
            f"alive={alive}, objective={self.objective.name})"
        )
