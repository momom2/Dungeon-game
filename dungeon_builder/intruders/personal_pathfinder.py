"""A* pathfinder operating on an intruder's PersonalMap.

Unlike the global :class:`AStarPathfinder` in ``world/pathfinding.py``,
this pathfinder only knows about cells the intruder has *seen*.  Unrevealed
cells are treated as impassable.  Traversability depends on the intruder's
archetype abilities: diggers can path through solid, flyers can move
vertically without slopes, phase-walkers can pass through thin walls, etc.
Fire immunity is equipment-driven and passed as a separate flag.

Phase-walk uses an augmented A* state ``(x, y, z, walls_used)`` to track
consecutive wall cells traversed.  The wall counter is a hard constraint
(not a heuristic cost): it resets to 0 when entering a walkable cell and
blocks movement when it would exceed ``phase_thickness``.  This gives
phase-walkers a dual-cost pathfinding algorithm — heuristic distance for
route planning, wall budget for traversal legality.

Dependencies: config, intruders.archetypes, intruders.personal_map
Dependents: intruders.decision, tests/intruders/test_personal_pathfinder.py,
    tests/intruders/test_ai_improvements.py,
    tests/benchmarks/benchmark_performance.py
"""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_DOOR,
    VOXEL_SPIKE,
    VOXEL_TREASURE,
    VOXEL_TARP,
    VOXEL_ROLLING_STONE,
    VOXEL_LAVA,
    VOXEL_WATER,
    VOXEL_REINFORCED_WALL,
    VOXEL_BEDROCK,
    VOXEL_CORE,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_PRESSURE_PLATE,
    VOXEL_IRON_BARS,
    VOXEL_FLOODGATE,
    VOXEL_ALARM_BELL,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_PIPE,
    VOXEL_PUMP,
    VOXEL_STEAM_VENT,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    NON_DIGGABLE,
    PERSONAL_PATHFINDER_MAX_ITERATIONS,
    HAZARD_PATH_COST,
    PATHFINDING_VERTICAL_COST,
)

if TYPE_CHECKING:
    from dungeon_builder.intruders.archetypes import ArchetypeStats
    from dungeon_builder.intruders.personal_map import PersonalMap


# Block types universally traversable (when revealed)
_WALK_TYPES = frozenset({VOXEL_AIR, VOXEL_SLOPE, VOXEL_STAIRS})

# Block types that are walkable for the purpose of resetting the phase-walk
# wall counter (any block not classified as "solid wall" by _move_cost).
# This is a superset of _WALK_TYPES including doors, traps, etc.
_PHASE_RESET_TYPES = frozenset({
    VOXEL_AIR, VOXEL_SLOPE, VOXEL_STAIRS,
    VOXEL_DOOR, VOXEL_SPIKE, VOXEL_TREASURE, VOXEL_TARP,
    VOXEL_ROLLING_STONE, VOXEL_GOLD_BAIT, VOXEL_HEAT_BEACON,
    VOXEL_PRESSURE_PLATE, VOXEL_ALARM_BELL, VOXEL_FRAGILE_FLOOR,
    VOXEL_STEAM_VENT, VOXEL_FLOODGATE, VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE, VOXEL_LAVA,
})

# Types that phase-walkers cannot pass through regardless of budget
_PHASE_IMPASSABLE = frozenset({
    VOXEL_REINFORCED_WALL, VOXEL_BEDROCK, VOXEL_CORE,
    VOXEL_WATER, VOXEL_IRON_BARS,
})

# Movement cost for phasing through a wall cell
_PHASE_WALK_COST = 5.0


class PersonalPathfinder:
    """Fog-of-war A* for a single intruder."""

    @staticmethod
    def find_path(
        personal_map: PersonalMap,
        start: tuple[int, int, int],
        goal: tuple[int, int, int],
        archetype: ArchetypeStats,
        *,
        has_fire_immunity: bool = False,
        max_iterations: int = PERSONAL_PATHFINDER_MAX_ITERATIONS,
    ) -> list[tuple[int, int, int]] | None:
        """Return a path from *start* to *goal*, or *None*.

        Only uses cells present in *personal_map.seen*.  Traversability
        and move costs depend on the *archetype*'s abilities and
        *has_fire_immunity* (equipment-driven, not innate).

        For phase-walkers (``archetype.phase_thickness >= 1``), the search
        state is augmented with a wall counter to enforce the phase budget
        as a hard constraint while using normal movement cost for the
        heuristic.
        """
        if start == goal:
            return [start]

        # Goal must be revealed (or we can't know if we can reach it)
        if not personal_map.is_revealed(*goal):
            return None

        if archetype.phase_thickness >= 1:
            return _find_path_phase(
                personal_map, start, goal, archetype,
                has_fire_immunity=has_fire_immunity,
                max_iterations=max_iterations,
            )

        return _find_path_standard(
            personal_map, start, goal, archetype,
            has_fire_immunity=has_fire_immunity,
            max_iterations=max_iterations,
        )


# ── Standard A* (non-phase-walkers) ─────────────────────────────────────


def _find_path_standard(
    personal_map: PersonalMap,
    start: tuple[int, int, int],
    goal: tuple[int, int, int],
    archetype: ArchetypeStats,
    *,
    has_fire_immunity: bool = False,
    max_iterations: int = PERSONAL_PATHFINDER_MAX_ITERATIONS,
) -> list[tuple[int, int, int]] | None:
    """Standard A* without phase-walk augmentation."""
    open_set: list[tuple[float, int, tuple[int, int, int]]] = []
    counter = 0
    g_score: dict[tuple[int, int, int], float] = {start: 0.0}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    f0 = _heuristic(start, goal)
    heapq.heappush(open_set, (f0, counter, start))
    counter += 1

    iterations = 0
    while open_set and iterations < max_iterations:
        iterations += 1
        _, _, current = heapq.heappop(open_set)

        if current == goal:
            return _reconstruct(came_from, current)

        current_g = g_score[current]

        for neighbor, move_cost in _get_neighbors(
            personal_map, current, archetype,
            has_fire_immunity=has_fire_immunity,
        ):
            tentative_g = current_g + move_cost
            if tentative_g < g_score.get(neighbor, float("inf")):
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                f = tentative_g + _heuristic(neighbor, goal)
                heapq.heappush(open_set, (f, counter, neighbor))
                counter += 1

    return None


# ── Phase-walk A* (augmented state) ──────────────────────────────────────

# Augmented state: (x, y, z, walls_used)
# walls_used = number of consecutive wall cells traversed in the current
# phase-walk sequence.  Resets to 0 when entering a non-wall cell.
# A move into a wall cell is only allowed if walls_used < phase_thickness.

_AugState = tuple[int, int, int, int]  # (x, y, z, walls_used)


def _find_path_phase(
    personal_map: PersonalMap,
    start: tuple[int, int, int],
    goal: tuple[int, int, int],
    archetype: ArchetypeStats,
    *,
    has_fire_immunity: bool = False,
    max_iterations: int = PERSONAL_PATHFINDER_MAX_ITERATIONS,
) -> list[tuple[int, int, int]] | None:
    """A* with augmented state for phase-walk wall budget tracking.

    The search state is ``(x, y, z, walls_used)`` where ``walls_used``
    counts consecutive wall cells traversed.  This is a hard constraint:
    moves into wall cells are only allowed while ``walls_used <
    phase_thickness``.  The counter resets to 0 when the eidolon enters
    any non-wall (walkable) cell.
    """
    start_aug: _AugState = (start[0], start[1], start[2], 0)
    phase_max = archetype.phase_thickness

    open_set: list[tuple[float, int, _AugState]] = []
    counter = 0
    g_score: dict[_AugState, float] = {start_aug: 0.0}
    came_from: dict[_AugState, _AugState] = {}
    f0 = _heuristic(start, goal)
    heapq.heappush(open_set, (f0, counter, start_aug))
    counter += 1

    iterations = 0
    while open_set and iterations < max_iterations:
        iterations += 1
        _, _, current = heapq.heappop(open_set)

        cx, cy, cz, cwalls = current
        if (cx, cy, cz) == goal:
            return _reconstruct_phase(came_from, current)

        current_g = g_score[current]

        for neighbor_aug, move_cost in _get_neighbors_phase(
            personal_map, current, archetype, phase_max,
            has_fire_immunity=has_fire_immunity,
        ):
            tentative_g = current_g + move_cost
            if tentative_g < g_score.get(neighbor_aug, float("inf")):
                g_score[neighbor_aug] = tentative_g
                came_from[neighbor_aug] = current
                nx, ny, nz, _ = neighbor_aug
                f = tentative_g + _heuristic((nx, ny, nz), goal)
                heapq.heappush(open_set, (f, counter, neighbor_aug))
                counter += 1

    return None


def _get_neighbors_phase(
    personal_map: PersonalMap,
    state: _AugState,
    archetype: ArchetypeStats,
    phase_max: int,
    *,
    has_fire_immunity: bool = False,
) -> list[tuple[_AugState, float]]:
    """Return (augmented_neighbor, cost) pairs for phase-walk A*."""
    x, y, z, walls_used = state
    result: list[tuple[_AugState, float]] = []

    for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                        (0, 0, 1), (0, 0, -1)):
        nx, ny, nz = x + dx, y + dy, z + dz

        vtype = personal_map.get_type(nx, ny, nz)
        if vtype is None:
            continue

        # First, try the standard move cost
        cost = _move_cost(personal_map, (nx, ny, nz), vtype, archetype, dz,
                          has_fire_immunity=has_fire_immunity)
        if cost is not None:
            # Non-wall cell: reset wall counter to 0
            result.append(((nx, ny, nz, 0), cost))
            continue

        # Standard move failed — try phase-walk (horizontal only)
        if dz != 0:
            continue
        if vtype in _PHASE_IMPASSABLE:
            continue
        # This is a solid wall cell. Phase through if budget allows.
        new_walls = walls_used + 1
        if new_walls > phase_max:
            continue  # Wall budget exhausted
        result.append(((nx, ny, nz, new_walls), _PHASE_WALK_COST))

    return result


def _reconstruct_phase(
    came_from: dict[_AugState, _AugState],
    current: _AugState,
) -> list[tuple[int, int, int]]:
    """Reconstruct path from augmented states, stripping wall counter."""
    path: list[tuple[int, int, int]] = [(current[0], current[1], current[2])]
    while current in came_from:
        current = came_from[current]
        path.append((current[0], current[1], current[2]))
    path.reverse()
    return path


# ── Standard neighbor expansion ─────────────────────────────────────────


def _heuristic(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _get_neighbors(
    personal_map: PersonalMap,
    pos: tuple[int, int, int],
    archetype: ArchetypeStats,
    *,
    has_fire_immunity: bool = False,
) -> list[tuple[tuple[int, int, int], float]]:
    """Return (neighbor, cost) pairs reachable from *pos*."""
    x, y, z = pos
    result: list[tuple[tuple[int, int, int], float]] = []

    # 4 horizontal + 2 vertical
    for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                        (0, 0, 1), (0, 0, -1)):
        nx, ny, nz = x + dx, y + dy, z + dz
        npos = (nx, ny, nz)

        vtype = personal_map.get_type(nx, ny, nz)
        if vtype is None:
            continue

        cost = _move_cost(personal_map, npos, vtype, archetype, dz,
                          has_fire_immunity=has_fire_immunity)
        if cost is not None:
            result.append((npos, cost))

    return result


def _move_cost(
    personal_map: PersonalMap,
    pos: tuple[int, int, int],
    vtype: int,
    archetype: ArchetypeStats,
    dz: int,
    *,
    has_fire_immunity: bool = False,
) -> float | None:
    """Return the move cost into *pos*, or *None* if impassable.

    *dz* is -1 (up in array = shallower), +1 (down = deeper), or 0 (horizontal).
    *has_fire_immunity* is True when the intruder's equipment grants fire
    immunity (equipment-driven, not an innate archetype trait).

    Phase-walk is NOT handled here — it's managed by the augmented-state
    A* in ``_find_path_phase`` / ``_get_neighbors_phase``.
    """
    base_cost = 1.0

    # --- Universal traversals ---
    if vtype in _WALK_TYPES:
        # Vertical movement without slope/stairs: only flyers
        if dz != 0 and vtype == VOXEL_AIR and not archetype.can_fly:
            # Non-flyers need slope/stairs for vertical movement
            # But going "down" (z+1) through air is falling — allowed
            if dz == -1:
                return None  # Can't go up through plain air without flying
        cost = base_cost if dz == 0 else PATHFINDING_VERTICAL_COST
        # Hazard modifiers
        if pos in personal_map.hazards and archetype.cunning > 0:
            cost += HAZARD_PATH_COST * archetype.cunning
        return cost

    # --- Doors ---
    if vtype == VOXEL_DOOR:
        door_state = personal_map.get_door_state(*pos)
        if door_state == 0:  # Open
            return base_cost
        # Closed door
        if archetype.can_lockpick:
            return base_cost + 5.0  # Lockpick cost
        if archetype.can_bash_door:
            return base_cost + 15.0  # Bash cost
        return None  # Can't get through

    # --- Functional blocks (spike, treasure, tarp, rolling stone) ---
    # These are traversable (the interaction system handles what happens)
    if vtype in (VOXEL_SPIKE, VOXEL_TREASURE, VOXEL_TARP, VOXEL_ROLLING_STONE):
        cost = base_cost
        if pos in personal_map.hazards and archetype.cunning > 0:
            cost += HAZARD_PATH_COST * archetype.cunning
        return cost

    # --- New traversable blocks ---
    # Gold bait, heat beacon, alarm bell: traversable (interaction handles)
    if vtype in (VOXEL_GOLD_BAIT, VOXEL_HEAT_BEACON, VOXEL_ALARM_BELL):
        cost = base_cost
        if pos in personal_map.hazards and archetype.cunning > 0:
            cost += HAZARD_PATH_COST * archetype.cunning
        return cost

    # Pressure plate: traversable, cunning adds hazard cost
    if vtype == VOXEL_PRESSURE_PLATE:
        cost = base_cost
        if pos in personal_map.hazards and archetype.cunning > 0:
            cost += HAZARD_PATH_COST * archetype.cunning
        return cost

    # Fragile floor: traversable (looks like stone), hazard cost if known
    if vtype == VOXEL_FRAGILE_FLOOR:
        cost = base_cost
        if pos in personal_map.hazards and archetype.cunning > 0:
            cost += HAZARD_PATH_COST * archetype.cunning
        return cost

    # Steam vent: traversable, cunning adds hazard cost
    if vtype == VOXEL_STEAM_VENT:
        cost = base_cost
        if pos in personal_map.hazards and archetype.cunning > 0:
            cost += HAZARD_PATH_COST * archetype.cunning
        return cost

    # Iron bars: impassable (no one can pass through)
    if vtype == VOXEL_IRON_BARS:
        return None

    # Floodgate: state-dependent (open=passable, closed=impassable)
    if vtype == VOXEL_FLOODGATE:
        door_state = personal_map.get_door_state(*pos)
        if door_state == 0:  # Open
            return base_cost
        return None  # Closed — impassable

    # Enchanted Door: same as regular door (lockpick/bash/repath)
    if vtype == VOXEL_ENCHANTED_DOOR:
        door_state = personal_map.get_door_state(*pos)
        if door_state == 0:  # Open
            return base_cost
        if archetype.can_lockpick:
            return base_cost + 5.0
        if archetype.can_bash_door:
            return base_cost + 15.0
        return None

    # Enchanted Floodgate: same as regular floodgate
    if vtype == VOXEL_ENCHANTED_FLOODGATE:
        door_state = personal_map.get_door_state(*pos)
        if door_state == 0:  # Open
            return base_cost
        return None

    # Pipe / Pump: impassable solid
    if vtype in (VOXEL_PIPE, VOXEL_PUMP):
        return None

    # --- Lava ---
    if vtype == VOXEL_LAVA:
        if has_fire_immunity:
            return base_cost + 2.0  # Slight preference for non-lava
        return None  # Death

    # --- Water ---
    if vtype == VOXEL_WATER:
        return None  # Nobody can swim (for now)

    # --- Reinforced wall / bedrock / core ---
    if vtype in (VOXEL_REINFORCED_WALL, VOXEL_BEDROCK, VOXEL_CORE):
        return None  # Never traversable

    # --- Other solid blocks ---
    if archetype.can_dig and vtype not in NON_DIGGABLE:
        # Digger can tunnel through diggable solids
        # Cost = high (reflects time to dig)
        return base_cost + 20.0
    return None  # Solid, can't traverse


def _reconstruct(
    came_from: dict[tuple[int, int, int], tuple[int, int, int]],
    current: tuple[int, int, int],
) -> list[tuple[int, int, int]]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
