"""State-handler mixin -- per-intruder state machine update methods.

Extracts the state-specific update logic (ADVANCING, INTERACTING, ATTACKING,
RETREATING, PILLAGING) and supporting movement/pathing helpers from
``IntruderAI`` so that ``decision.py`` stays under the 600-line target.

Dependencies: config, intruders.agent, intruders.archetypes,
    intruders.interactions, intruders.personal_pathfinder
Dependents: intruders.decision (IntruderAI inherits this mixin)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import IntruderObjective
from dungeon_builder.intruders.interactions import (
    handle_block,
    InteractionResult,
)
from dungeon_builder.intruders.personal_pathfinder import PersonalPathfinder
import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_DOOR,
    VOXEL_TREASURE,
    VOXEL_GOLD_BAIT,
    VOXEL_PRESSURE_PLATE,
    VOXEL_FRAGILE_FLOOR,
    SURFACE_Z,
    DIG_DURATION,
    NON_DIGGABLE,
    MORALE_DAMAGE_PENALTY,
    MORALE_TREASURE_BONUS,
    MORALE_LOW_THRESHOLD,
    MORALE_RETREAT_MULTIPLIER,
    SUPPLY_SAFETY_MARGIN,
    SUPPLY_COST_PER_CELL,
    EXPLORE_FRONTIER_MAX_CANDIDATES,
    EXPLORE_DEPTH_WEIGHT,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("dungeon_builder.intruders")


class StateHandlersMixin:
    """Mixin providing the per-state update methods and movement helpers.

    Relies on attributes initialised by ``IntruderAI.__init__``:
        event_bus, voxel_grid, pathfinder, core, rng,
        intruders, parties, _knowledge_archive
    Also calls methods from other mixins (e.g. ``_update_vision``,
    ``_activate_pressure_plate``, ``_check_fragile_floor``,
    ``_check_alarm_bells``), which are resolved at runtime via MRO.
    """

    # -- Supply-cost estimation ---------------------------------------------

    def _estimate_return_cost(self, intruder: Intruder) -> float:
        """Estimate the supply cost for this intruder to retreat to the exit.

        Uses Manhattan distance to the surface as a rough path-length proxy,
        multiplied by SUPPLY_COST_PER_CELL.
        """
        # Distance to surface exit (approximate)
        dist = abs(intruder.z - SURFACE_Z) + 5  # +5 for lateral traversal
        return dist * SUPPLY_COST_PER_CELL

    # -- ADVANCING state ----------------------------------------------------

    def _update_advancing(self, intruder: Intruder, tick: int = 0) -> None:
        # Check retreat condition
        self._check_retreat(intruder)
        if intruder.state != IntruderState.ADVANCING:
            return

        # Movement tick
        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        self._advance_along_path(intruder)

        # Check if we reached the core (within attack range)
        core_pos = (self.core.x, self.core.y, self.core.z)
        dist = (
            abs(intruder.x - core_pos[0])
            + abs(intruder.y - core_pos[1])
            + abs(intruder.z - core_pos[2])
        )
        if dist <= intruder.archetype.attack_range:
            intruder.state = IntruderState.ATTACKING
            logger.info("Intruder #%d reached attack range of core!", intruder.id)

    # -- INTERACTING state --------------------------------------------------

    def _update_interacting(self, intruder: Intruder) -> None:
        """Count down the interaction timer; complete when done."""
        intruder.interaction_ticks -= 1
        if intruder.interaction_ticks > 0:
            return

        itype = intruder.interaction_type
        target = intruder.interaction_target

        if target is None:
            intruder.state = IntruderState.ADVANCING
            return

        tx, ty, tz = target
        grid = self.voxel_grid

        if itype in ("bash_door", "lockpick"):
            # Open the door (set block_state to 0)
            if grid.get(tx, ty, tz) == VOXEL_DOOR:
                grid.set_block_state(tx, ty, tz, 0)
                intruder.personal_map.reveal(tx, ty, tz, VOXEL_DOOR, 0)
                logger.debug(
                    "Intruder #%d opened door at (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_opened_door",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )
        elif itype == "grab_treasure":
            if grid.get(tx, ty, tz) == VOXEL_TREASURE:
                grid.set(tx, ty, tz, VOXEL_AIR)
                intruder.loot_count += 1
                intruder.personal_map.remove_treasure(tx, ty, tz)
                intruder.morale = min(1.0, intruder.morale + MORALE_TREASURE_BONUS)
                logger.debug(
                    "Intruder #%d collected treasure at (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_collected_treasure",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )
        elif itype == "grab_bait":
            if grid.get(tx, ty, tz) == VOXEL_GOLD_BAIT:
                # Bait consumed
                grid.set(tx, ty, tz, VOXEL_AIR)
                # Intruder realizes they were tricked -- morale hit
                intruder.morale = max(0.0, intruder.morale - 0.1)
                intruder.personal_map.mark_bait(tx, ty, tz)
                logger.debug(
                    "Intruder #%d grabbed gold bait at (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_grabbed_bait",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )
                # Bait triggers adjacent traps (same as pressure plate)
                self._activate_pressure_plate(tx, ty, tz, intruder)

        elif itype == "dig":
            vtype = grid.get(tx, ty, tz)
            if vtype != VOXEL_AIR and vtype not in NON_DIGGABLE:
                grid.set(tx, ty, tz, VOXEL_AIR)
                intruder.personal_map.reveal(tx, ty, tz, VOXEL_AIR, 0)
                logger.debug(
                    "Intruder #%d dug through (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_digging",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )

        # Clear interaction state and resume
        intruder.interaction_type = None
        intruder.interaction_target = None
        intruder.interaction_ticks = 0

        if intruder.objective == IntruderObjective.PILLAGE:
            intruder.state = IntruderState.PILLAGING
        else:
            intruder.state = IntruderState.ADVANCING
        self._repath_intruder(intruder)

    # -- ATTACKING state ----------------------------------------------------

    def _update_attacking(self, intruder: Intruder) -> None:
        intruder.ticks_since_attack += 1
        if intruder.ticks_since_attack >= intruder.attack_interval:
            intruder.ticks_since_attack = 0
            damage = intruder.effective_damage
            self.core.take_damage(damage)
            logger.debug(
                "Intruder #%d attacks core for %d damage",
                intruder.id, damage,
            )

    # -- RETREATING state ---------------------------------------------------

    def _update_retreating(self, intruder: Intruder, tick: int = 0) -> None:
        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        self._advance_along_path(intruder)

        if intruder.z == SURFACE_Z:
            intruder.state = IntruderState.ESCAPED
            self._knowledge_archive.archive_survivor(intruder, tick)
            self.event_bus.publish("intruder_escaped", intruder=intruder)
            logger.info("Intruder #%d escaped to the surface!", intruder.id)

    # -- PILLAGING state ----------------------------------------------------

    def _update_pillaging(self, intruder: Intruder) -> None:
        """Head toward nearest known treasure, or retreat if none left."""
        self._check_retreat(intruder)
        if intruder.state != IntruderState.PILLAGING:
            return

        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        # If no path or path exhausted, find nearest treasure
        if intruder.path is None or intruder.path_index >= len(intruder.path):
            treasures = list(intruder.personal_map.treasures)
            if not treasures:
                self._start_retreat(intruder)
                return
            nearest = min(
                treasures,
                key=lambda t: (
                    abs(t[0] - intruder.x)
                    + abs(t[1] - intruder.y)
                    + abs(t[2] - intruder.z)
                ),
            )
            path = PersonalPathfinder.find_path(
                intruder.personal_map, intruder.pos, nearest, intruder.archetype,
            )
            if path and len(path) > 1:
                intruder.path = path
                intruder.path_index = 1
            else:
                self._start_retreat(intruder)
                return

        self._advance_along_path(intruder)

    # -- Path following & block interactions ---------------------------------

    def _advance_along_path(self, intruder: Intruder) -> None:
        """Move the intruder one step along its path, handling interactions."""
        if intruder.path is None:
            return
        if intruder.path_index >= len(intruder.path):
            if intruder.state == IntruderState.ADVANCING:
                self._repath_intruder(intruder)
            return

        next_pos = intruder.path[intruder.path_index]
        nx, ny, nz = next_pos
        grid = self.voxel_grid

        if not grid.in_bounds(nx, ny, nz):
            self._repath_intruder(intruder)
            return

        vtype = grid.get(nx, ny, nz)
        bstate = int(grid.block_state[nx, ny, nz])

        # Handle block interaction
        info = handle_block(intruder, vtype, bstate)

        if info.result == InteractionResult.CONTINUE:
            self._move_to(intruder, next_pos)

        elif info.result == InteractionResult.INTERACT:
            intruder.state = IntruderState.INTERACTING
            intruder.interaction_type = info.interaction_type
            intruder.interaction_target = next_pos
            intruder.interaction_ticks = info.ticks

        elif info.result == InteractionResult.DAMAGE:
            intruder.take_damage(info.damage)
            intruder.morale = max(0.0, intruder.morale - MORALE_DAMAGE_PENALTY)
            if intruder.alive:
                self._move_to(intruder, next_pos)
            else:
                self._on_intruder_death(intruder)

        elif info.result == InteractionResult.REPATH:
            if (
                intruder.archetype.can_dig
                and vtype not in NON_DIGGABLE
                and vtype != VOXEL_AIR
            ):
                self._start_digging(intruder, next_pos, vtype)
            else:
                self._repath_intruder(intruder)

        elif info.result == InteractionResult.COLLECT:
            intruder.state = IntruderState.INTERACTING
            intruder.interaction_type = info.interaction_type
            intruder.interaction_target = next_pos
            intruder.interaction_ticks = info.ticks

        elif info.result == InteractionResult.FALL:
            intruder.personal_map.mark_hazard(nx, ny, nz)
            grid.set(nx, ny, nz, VOXEL_AIR)
            self._move_to(intruder, next_pos)
            self.event_bus.publish(
                "intruder_fell", intruder=intruder, x=nx, y=ny, z=nz,
            )

        elif info.result == InteractionResult.DEATH:
            intruder.take_damage(intruder.hp)
            self._on_intruder_death(intruder)

        elif info.result == InteractionResult.DESTROY_BLOCK:
            intruder.take_damage(info.damage)
            if grid.get(nx, ny, nz) != VOXEL_AIR:
                grid.set(nx, ny, nz, VOXEL_AIR)
            if intruder.alive:
                self._move_to(intruder, next_pos)
            else:
                self._on_intruder_death(intruder)

    def _move_to(self, intruder: Intruder, pos: tuple[int, int, int]) -> None:
        """Move intruder to a new position and advance path index."""
        intruder.x, intruder.y, intruder.z = pos
        intruder.path_index += 1
        intruder._vision_dirty = True
        self.event_bus.publish("intruder_moved", intruder=intruder)

        # Post-move triggers on the cell we just stepped into
        grid = self.voxel_grid
        nx, ny, nz = pos
        if grid.in_bounds(nx, ny, nz):
            vtype = grid.get(nx, ny, nz)

            # Pressure plate activation
            if vtype == VOXEL_PRESSURE_PLATE:
                bstate = int(grid.block_state[nx, ny, nz])
                if bstate == 0:  # Not yet triggered
                    grid.set_block_state(nx, ny, nz, 1)
                    self._activate_pressure_plate(nx, ny, nz, intruder)

            # Fragile floor collapse check (flyers don't trigger)
            if vtype == VOXEL_FRAGILE_FLOOR and not intruder.archetype.can_fly:
                collapsed = self._check_fragile_floor(intruder, nx, ny, nz)
                if collapsed:
                    # Intruder falls -- check if there's air below
                    below_z = nz + 1  # z+1 = deeper
                    if (
                        grid.in_bounds(nx, ny, below_z)
                        and grid.get(nx, ny, below_z) == VOXEL_AIR
                    ):
                        intruder.z = below_z
                        intruder._vision_dirty = True
                        self.event_bus.publish(
                            "intruder_fell",
                            intruder=intruder, x=nx, y=ny, z=nz,
                        )

            # Alarm bell proximity check
            self._check_alarm_bells(intruder)

    def _move_random(self, intruder: Intruder) -> None:
        """Move the intruder to a random adjacent air cell."""
        grid = self.voxel_grid
        candidates = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = intruder.x + dx, intruder.y + dy
            nz = intruder.z
            if grid.in_bounds(nx, ny, nz) and grid.get(nx, ny, nz) == VOXEL_AIR:
                candidates.append((nx, ny, nz))
        if candidates:
            pos = self.rng.choice(candidates)
            intruder.x, intruder.y, intruder.z = pos
            intruder._vision_dirty = True
            self.event_bus.publish("intruder_moved", intruder=intruder)

    # -- Digging ------------------------------------------------------------

    def _start_digging(
        self,
        intruder: Intruder,
        target: tuple[int, int, int],
        vtype: int,
    ) -> None:
        """Start digging through a solid block.

        Dig duration is halved from base (all digger archetypes dig at
        the same rate -- specialisation comes from familiar usage, not
        innate speed).
        """
        base_ticks = DIG_DURATION.get(vtype, 40)
        dig_ticks = max(1, base_ticks // 2)

        intruder.state = IntruderState.INTERACTING
        intruder.interaction_type = "dig"
        intruder.interaction_target = target
        intruder.interaction_ticks = dig_ticks
        self.event_bus.publish(
            "intruder_digging",
            intruder=intruder, x=target[0], y=target[1], z=target[2],
        )

    # -- Retreat ------------------------------------------------------------

    def _check_retreat(self, intruder: Intruder) -> None:
        """Check whether an intruder should begin retreating.

        Retreat triggers (checked in order):
        1. Morale-based flee (below MORALE_FLEE_THRESHOLD)
        2. HP-based retreat (below retreat_threshold, modulated by risk_tolerance
           and morale)
        3. Supply-based retreat (food or water insufficient for return trip,
           with risk_tolerance reducing the safety margin)
        """
        arch = intruder.archetype

        # Archetypes with retreat_threshold=0.0 never retreat on HP,
        # but can still flee on morale or supplies.

        # Morale-based flee: very low morale -> abandon party
        if intruder.morale < _cfg.MORALE_FLEE_THRESHOLD:
            self._start_retreat(intruder)
            return

        # HP-based retreat (risk_tolerance lowers effective threshold)
        if arch.retreat_threshold > 0:
            hp_ratio = intruder.hp / intruder.max_hp
            # Bold intruders retreat at lower HP thresholds
            threshold = arch.retreat_threshold * (1.0 - arch.risk_tolerance * 0.5)
            # Low morale doubles the retreat threshold (flee at higher HP)
            if intruder.morale < MORALE_LOW_THRESHOLD:
                threshold *= MORALE_RETREAT_MULTIPLIER

            if hp_ratio < threshold:
                self._start_retreat(intruder)
                return

        # Supply-based retreat: ensure enough food/water to get back
        # Bold intruders accept thinner safety margins
        risk_margin = SUPPLY_SAFETY_MARGIN * (1.0 - arch.risk_tolerance * 0.2)
        return_cost = self._estimate_return_cost(intruder)
        if intruder.food < return_cost * risk_margin:
            self._start_retreat(intruder)
            return
        if intruder.water < return_cost * risk_margin:
            self._start_retreat(intruder)
            return

    def _start_retreat(self, intruder: Intruder) -> None:
        """Begin retreat toward the surface."""
        # Already at surface -> escape immediately
        if intruder.z == SURFACE_Z:
            intruder.state = IntruderState.RETREATING
            return
        intruder.state = IntruderState.RETREATING
        path = PersonalPathfinder.find_path(
            intruder.personal_map,
            intruder.pos,
            (intruder.x, intruder.y, SURFACE_Z),
            intruder.archetype,
        )
        if path and len(path) > 1:
            intruder.path = path
            intruder.path_index = 1
        else:
            # Fallback to global pathfinder
            path = self.pathfinder.find_path(
                intruder.pos, (intruder.x, intruder.y, SURFACE_Z),
            )
            if path and len(path) > 1:
                intruder.path = path
                intruder.path_index = 1
            else:
                intruder.state = IntruderState.ADVANCING
        logger.info("Intruder #%d retreating (HP: %d)", intruder.id, intruder.hp)

    # -- Pathing ------------------------------------------------------------

    def _repath_intruder(self, intruder: Intruder) -> None:
        """Find a new path for the intruder based on its objective/state."""
        if intruder.state == IntruderState.RETREATING:
            goal = (intruder.x, intruder.y, SURFACE_Z)
        elif intruder.state == IntruderState.PILLAGING:
            treasures = list(intruder.personal_map.treasures)
            if treasures:
                goal = min(
                    treasures,
                    key=lambda t: (
                        abs(t[0] - intruder.x)
                        + abs(t[1] - intruder.y)
                        + abs(t[2] - intruder.z)
                    ),
                )
            else:
                self._start_retreat(intruder)
                return
        elif intruder.state in (IntruderState.ADVANCING, IntruderState.SPAWNING):
            if intruder.objective == IntruderObjective.EXPLORE:
                goal = self._pick_explore_target(intruder)
                if goal is None:
                    self._start_retreat(intruder)
                    return
            else:
                goal = (self.core.x, self.core.y, self.core.z)
        else:
            return

        # Skip repathing if position, goal, and map haven't changed
        cache_key = (intruder.pos, goal, intruder.personal_map._generation)
        if (
            intruder._path_cache_key == cache_key
            and intruder.path is not None
            and intruder.path_index < len(intruder.path)
        ):
            return

        # Try personal pathfinder first
        path = PersonalPathfinder.find_path(
            intruder.personal_map, intruder.pos, goal, intruder.archetype,
        )
        if path and len(path) > 1:
            intruder.path = path
            intruder.path_index = 1
            intruder._path_cache_key = cache_key
        else:
            # Fallback to global pathfinder
            path = self.pathfinder.find_path(intruder.pos, goal)
            if path and len(path) > 1:
                intruder.path = path
                intruder.path_index = 1
                intruder._path_cache_key = cache_key
            else:
                logger.debug(
                    "Intruder #%d cannot find path from %s to %s",
                    intruder.id, intruder.pos, goal,
                )
                intruder.path = None
                intruder._path_cache_key = None

    # -- Explore target selection --------------------------------------------

    def _pick_explore_target(
        self, intruder: Intruder,
    ) -> tuple[int, int, int] | None:
        """Pick the best frontier cell for an EXPLORE-objective intruder.

        Frontier cells (revealed cells with unrevealed neighbors) are scored
        using a blend of depth (deeper = more interesting) and proximity
        (closer = more efficient).  ``exploration_drive`` biases the blend:
        high drive favors depth, low drive favors proximity.

        Returns *None* when the frontier is empty (everything explored).
        """
        frontier = intruder.personal_map.get_frontier()
        if not frontier:
            return None

        arch = intruder.archetype
        ix, iy, iz = intruder.x, intruder.y, intruder.z
        grid_h = self.voxel_grid.height

        # Depth weight blended with exploration_drive
        depth_w = EXPLORE_DEPTH_WEIGHT * (0.5 + arch.exploration_drive * 0.5)
        prox_w = 1.0 - depth_w

        # Score each frontier cell
        scored: list[tuple[float, tuple[int, int, int]]] = []
        for fx, fy, fz in frontier:
            # Depth score: deeper (higher z) = higher score, normalised 0-1
            depth_score = fz / grid_h if grid_h > 0 else 0.0
            # Proximity score: closer = higher, inverted Manhattan, normalised
            dist = abs(fx - ix) + abs(fy - iy) + abs(fz - iz)
            max_dist = grid_h + self.voxel_grid.width + self.voxel_grid.depth
            prox_score = 1.0 - (dist / max_dist) if max_dist > 0 else 0.0
            score = depth_score * depth_w + prox_score * prox_w
            scored.append((score, (fx, fy, fz)))

        # Sort descending by score and pick from top candidates
        scored.sort(key=lambda s: s[0], reverse=True)
        top_n = min(EXPLORE_FRONTIER_MAX_CANDIDATES, len(scored))
        candidates = scored[:top_n]

        # Weighted random selection from top candidates
        total = sum(s for s, _ in candidates)
        if total <= 0:
            return candidates[0][1]

        roll = self.rng.random() * total
        cumulative = 0.0
        for score, pos in candidates:
            cumulative += score
            if roll < cumulative:
                return pos
        return candidates[-1][1]
