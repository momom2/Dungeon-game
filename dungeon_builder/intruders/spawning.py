"""Spawning mixin -- party and intruder creation logic.

Extracts the spawn-related methods from ``IntruderAI`` into a mixin so that
``decision.py`` stays under the 600-line target.

Dependencies: config, intruders.agent, intruders.archetypes,
    intruders.equipment, intruders.familiar, intruders.party,
    intruders.personal_map, intruders.personal_pathfinder,
    intruders.knowledge_archive, intruders.reputation
Dependents: intruders.decision (IntruderAI inherits this mixin)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    IntruderStatus,
    EXPLORER,
)
from dungeon_builder.intruders.equipment import generate_loadout
from dungeon_builder.intruders.familiar import spawn_familiars
from dungeon_builder.intruders.party import (
    Party,
    choose_template,
    generate_composition,
)
from dungeon_builder.intruders.personal_map import PersonalMap
import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR,
    SURFACE_Z,
    LEVEL_WEIGHTS,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("dungeon_builder.intruders")


class SpawningMixin:
    """Mixin providing party/intruder spawning and level-assignment methods.

    Relies on attributes initialised by ``IntruderAI.__init__``:
        event_bus, voxel_grid, pathfinder, core, rng,
        intruders, parties, _next_id, _next_party_id,
        _next_familiar_id, _spawn_timer, _knowledge_archive,
        _reputation
    """

    # -- Spawning -----------------------------------------------------------

    def _tick_spawning(self) -> None:
        self._spawn_timer += 1
        if self._spawn_timer < _cfg.INTRUDER_PARTY_SPAWN_INTERVAL:
            return
        self._spawn_timer = 0

        alive_count = sum(1 for i in self.intruders if i.alive)
        active_parties = sum(1 for p in self.parties if not p.is_wiped)

        if alive_count >= _cfg.MAX_INTRUDERS_TOTAL:
            return
        if active_parties >= _cfg.MAX_PARTIES:
            return

        self._spawn_party()

    def _spawn_party(self) -> None:
        """Spawn a new party at a random surface edge."""
        party_rng = self.rng.fork(f"party_{self._next_party_id}")
        template = choose_template(party_rng)
        composition = generate_composition(template, party_rng)

        # Find spawn position
        spawn_pos = self._find_spawn_position()
        if spawn_pos is None:
            logger.debug("No valid spawn position found for party")
            return

        sx, sy, sz = spawn_pos
        members: list[Intruder] = []
        loyalty_mod = self._reputation.get_loyalty_modifier()
        level_shift = self._reputation.get_level_shift()

        for arch in composition:
            obj = self._pick_objective(arch, party_rng)
            level = self._assign_level(party_rng, level_shift)
            status = self._level_to_status(level)
            pmap = PersonalMap()
            self._knowledge_archive.inject_knowledge(
                pmap, self._spawn_timer, arch.cunning,
            )

            # Generate equipment loadout
            equipment = generate_loadout(
                arch, party_rng, level, status, self._reputation,
            )

            intruder = Intruder(
                intruder_id=self._next_id,
                x=sx, y=sy, z=sz,
                archetype=arch,
                objective=obj,
                personal_map=pmap,
                equipment=equipment,
                level=level,
                status=status,
            )
            intruder.loyalty_modifier += loyalty_mod
            self._next_id += 1
            intruder.state = IntruderState.ADVANCING

            # Spawn familiars for Mole Tamers
            if arch.familiar_capacity > 0:
                familiars = spawn_familiars(intruder, self._next_familiar_id)
                intruder.familiars = familiars
                self._next_familiar_id += len(familiars)

            members.append(intruder)

        if not members:
            return

        rep_modifier = self._reputation.get_objective_modifier()
        party = Party(self._next_party_id, members)
        party._vote_objective(reputation_modifier=rep_modifier)
        self._next_party_id += 1
        self.parties.append(party)
        self._party_by_id[party.id] = party

        for m in members:
            self.intruders.append(m)
            # Initial vision scan
            self._update_vision(m)
            # Initial path
            self._repath_intruder(m)
            self.event_bus.publish("intruder_spawned", intruder=m)

        logger.info(
            "Spawned party #%d (%s) with %d members at (%d,%d,%d)",
            party.id, template.name, len(members), sx, sy, sz,
        )

    def _spawn_intruder(self) -> None:
        """Spawn a single intruder (legacy compatibility for tests)."""
        spawn_pos = self._find_spawn_position()
        if spawn_pos is None:
            logger.debug("No valid spawn position found")
            return

        sx, sy, sz = spawn_pos
        equipment = generate_loadout(
            EXPLORER, self.rng, 1, IntruderStatus.GRUNT, self._reputation,
        )
        intruder = Intruder(
            intruder_id=self._next_id,
            x=sx, y=sy, z=sz,
            archetype=EXPLORER,
            objective=IntruderObjective.DESTROY_CORE,
            personal_map=PersonalMap(),
            equipment=equipment,
        )
        self._next_id += 1

        # Find path via global pathfinder
        path = self.pathfinder.find_path(
            (intruder.x, intruder.y, intruder.z),
            (self.core.x, self.core.y, self.core.z),
        )
        if path is None:
            logger.debug("No path from spawn to core for intruder #%d", intruder.id)
            return

        intruder.path = path
        intruder.path_index = 1
        intruder.state = IntruderState.ADVANCING
        self.intruders.append(intruder)
        self.event_bus.publish("intruder_spawned", intruder=intruder)
        logger.info("Spawned intruder #%d at (%d, %d, %d)", intruder.id, sx, sy, sz)

    @staticmethod
    def _pick_objective(arch, rng) -> IntruderObjective:
        """Pick an objective weighted by archetype's objective_weights."""
        w = arch.objective_weights
        roll = rng.random()
        if roll < w[0]:
            return IntruderObjective.DESTROY_CORE
        if roll < w[0] + w[1]:
            return IntruderObjective.EXPLORE
        return IntruderObjective.PILLAGE

    def _find_spawn_position(self) -> tuple[int, int, int] | None:
        """Find an air cell above terrain at or near the map edge.

        With varying terrain, the surface might not be air at SURFACE_Z.
        Scan upward from SURFACE_Z to find the first air cell.
        """
        grid = self.voxel_grid
        edges: list[tuple[int, int, int]] = []

        def _find_air(x: int, y: int) -> tuple[int, int, int] | None:
            """Scan from SURFACE_Z upward (decreasing z) to find air."""
            for z in range(SURFACE_Z, -1, -1):
                if grid.get(x, y, z) == VOXEL_AIR:
                    return (x, y, z)
            return None

        # Try edge cells first
        for x in range(grid.width):
            for y in [0, grid.depth - 1]:
                pos = _find_air(x, y)
                if pos is not None:
                    edges.append(pos)
        for y in range(grid.depth):
            for x in [0, grid.width - 1]:
                pos = _find_air(x, y)
                if pos is not None:
                    edges.append(pos)

        # Fallback: any cell
        if not edges:
            for x in range(grid.width):
                for y in range(grid.depth):
                    pos = _find_air(x, y)
                    if pos is not None:
                        edges.append(pos)

        if not edges:
            return None
        return self.rng.choice(edges)

    # -- Level & status assignment ------------------------------------------

    @staticmethod
    def _assign_level(rng, level_shift: float = 0.0) -> int:
        """Assign a level 1-5 using weighted random, shifted by reputation.

        *level_shift* moves probability from level 1 toward higher levels.
        """
        weights = list(LEVEL_WEIGHTS)
        if level_shift > 0.0:
            shift = min(level_shift, weights[0] * 0.8)
            weights[0] -= shift
            # Distribute shift evenly across levels 2-5
            per_level = shift / 4
            for i in range(1, 5):
                weights[i] += per_level
        roll = rng.random()
        cumulative = 0.0
        for i, w in enumerate(weights):
            cumulative += w
            if roll < cumulative:
                return i + 1
        return 5

    @staticmethod
    def _level_to_status(level: int) -> IntruderStatus:
        """Convert intruder level to IntruderStatus."""
        if level <= 2:
            return IntruderStatus.GRUNT
        if level == 3:
            return IntruderStatus.VETERAN
        if level == 4:
            return IntruderStatus.ELITE
        return IntruderStatus.CHAMPION
