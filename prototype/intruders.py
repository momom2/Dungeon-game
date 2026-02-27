"""Prototype intruder systems: pathfinding, AI, and arrow traps.

Three classes:
  - PrototypePathfinder: A* that also traverses open doors
  - PrototypeIntruderAI: simplified spawn + per-intruder tick logic
  - ArrowTrapSystem: fires at intruders in adjacent air cells

Dependencies: dungeon_builder.config, dungeon_builder.world.pathfinding,
    dungeon_builder.intruders.agent, dungeon_builder.intruders.archetypes,
    dungeon_builder.intruders.personal_map, prototype.config
Dependents: prototype.main, tests/prototype/test_intruders.py,
    tests/prototype/test_arrow_trap.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_DOOR,
    CORE_X,
    CORE_Y,
    CORE_Z,
    GRID_WIDTH,
)
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    EXPLORER,
    IntruderObjective,
)
from dungeon_builder.intruders.personal_map import PersonalMap

from prototype.config import (
    VOXEL_ARROW_TRAP,
    ARROW_TRAP_DAMAGE,
    ARROW_TRAP_COOLDOWN,
    SPAWN_INTERVAL,
    SPAWN_EDGE_Y,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid
    from dungeon_builder.dungeon_core.core import DungeonCore

logger = logging.getLogger("prototype.intruders")

# 6-connected neighbor offsets (same as crafting_book.NEIGHBORS_6)
_NEIGHBORS_6 = [
    (1, 0, 0), (-1, 0, 0),
    (0, 1, 0), (0, -1, 0),
    (0, 0, 1), (0, 0, -1),
]


# ── Pathfinder ──────────────────────────────────────────────────────

class PrototypePathfinder(AStarPathfinder):
    """A* pathfinder that also treats open doors as walkable.

    An open door is VOXEL_DOOR with block_state == 0.
    Arrow traps (solid) remain impassable.
    """

    def _get_neighbors(self, pos: tuple[int, int, int]) -> list[tuple[int, int, int]]:
        x, y, z = pos
        neighbors: list[tuple[int, int, int]] = []
        grid = self.voxel_grid

        # Horizontal movement (4-directional)
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = x + dx, y + dy
            if grid.in_bounds(nx, ny, z):
                vtype = grid.get(nx, ny, z)
                if vtype == VOXEL_AIR:
                    neighbors.append((nx, ny, z))
                elif vtype == VOXEL_DOOR and grid.get_block_state(nx, ny, z) == 0:
                    # Open door is traversable
                    neighbors.append((nx, ny, z))

        # Vertical movement: down (z+1 = deeper)
        if grid.in_bounds(x, y, z + 1):
            vtype = grid.get(x, y, z + 1)
            if vtype == VOXEL_AIR or (vtype == VOXEL_DOOR and grid.get_block_state(x, y, z + 1) == 0):
                neighbors.append((x, y, z + 1))

        # Vertical movement: up (z-1 = toward surface)
        if z > 0 and grid.in_bounds(x, y, z - 1):
            vtype = grid.get(x, y, z - 1)
            if vtype == VOXEL_AIR or (vtype == VOXEL_DOOR and grid.get_block_state(x, y, z - 1) == 0):
                neighbors.append((x, y, z - 1))

        return neighbors


# ── Intruder AI ─────────────────────────────────────────────────────

class PrototypeIntruderAI:
    """Simplified intruder spawning and per-tick AI for the prototype.

    Behaviour:
      - Every SPAWN_INTERVAL ticks, spawn wave_number explorers at the
        map edge (y=0).
      - ADVANCING intruders walk their path toward the core.
      - ATTACKING intruders deal damage per attack_interval tick.
      - Intruders repath when the world changes (voxel_changed event).
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        pathfinder: PrototypePathfinder,
        core: DungeonCore,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.pathfinder = pathfinder
        self.core = core

        self.intruders: list[Intruder] = []
        self._next_id: int = 0
        self._wave_number: int = 0
        self._game_over: bool = False

        # Pathfinding goal: air cell adjacent to core (find_path rejects
        # non-AIR goals, so we pre-compute a suitable neighbor)
        self._core_goal: tuple[int, int, int] | None = None
        self._compute_core_goal()

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("game_over", self._on_game_over)
        event_bus.subscribe("voxel_changed", self._on_voxel_changed)

    def _compute_core_goal(self) -> None:
        """Find an air cell adjacent to the core for pathfinding."""
        for dx, dy, dz in _NEIGHBORS_6:
            nx, ny, nz = CORE_X + dx, CORE_Y + dy, CORE_Z + dz
            if self.voxel_grid.in_bounds(nx, ny, nz):
                if self.voxel_grid.get(nx, ny, nz) == VOXEL_AIR:
                    self._core_goal = (nx, ny, nz)
                    return
        # Fallback: use position in corridor direction
        self._core_goal = (CORE_X, CORE_Y - 1, CORE_Z)

    # ── Event handlers ──────────────────────────────────────────────

    def _on_tick(self, tick: int, **kwargs) -> None:
        if self._game_over:
            return

        # Spawn wave
        if tick > 0 and tick % SPAWN_INTERVAL == 0:
            self._wave_number += 1
            self._spawn_wave(self._wave_number)

        # Update each live intruder
        for intruder in self.intruders:
            if not intruder.alive:
                continue
            self._update_intruder(intruder, tick)

    def _on_game_over(self, **kwargs) -> None:
        self._game_over = True

    def _on_voxel_changed(self, **kwargs) -> None:
        """Repath all advancing intruders when the world changes."""
        self._compute_core_goal()
        for intruder in self.intruders:
            if intruder.alive and intruder.state == IntruderState.ADVANCING:
                self._compute_path(intruder)

    # ── Spawning ────────────────────────────────────────────────────

    def _spawn_wave(self, count: int) -> None:
        """Spawn *count* explorers at the map edge."""
        for i in range(count):
            # Spread spawns across the x-axis near the shaft
            spawn_x = min(CORE_X + i, GRID_WIDTH - 1)
            spawn_y = SPAWN_EDGE_Y
            # Find a valid air cell at spawn location
            spawn_z = self._find_surface_air(spawn_x, spawn_y)
            if spawn_z is None:
                continue

            intruder = Intruder(
                intruder_id=self._next_id,
                x=spawn_x,
                y=spawn_y,
                z=spawn_z,
                archetype=EXPLORER,
                objective=IntruderObjective.DESTROY_CORE,
                personal_map=PersonalMap(),
            )
            self._next_id += 1
            intruder.state = IntruderState.ADVANCING
            self._compute_path(intruder)
            self.intruders.append(intruder)

            self.event_bus.publish(
                "intruder_spawned", intruder=intruder,
            )
            logger.debug("Spawned intruder %d at (%d,%d,%d)",
                         intruder.id, intruder.x, intruder.y, intruder.z)

    def _find_surface_air(self, x: int, y: int) -> int | None:
        """Find the topmost air cell at (x, y) starting from sky."""
        grid = self.voxel_grid
        for z in range(grid.height):
            if grid.get(x, y, z) == VOXEL_AIR:
                return z
        return None

    # ── Per-intruder update ─────────────────────────────────────────

    def _update_intruder(self, intruder: Intruder, tick: int) -> None:
        if intruder.state == IntruderState.ADVANCING:
            self._advance(intruder)
        elif intruder.state == IntruderState.ATTACKING:
            self._attack(intruder, tick)

    def _advance(self, intruder: Intruder) -> None:
        """Move intruder one step along its path."""
        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        if intruder.path is None or intruder.path_index >= len(intruder.path):
            # No path or reached end — try to compute/repath
            self._compute_path(intruder)
            if intruder.path is None:
                return

        if intruder.path_index >= len(intruder.path):
            return

        # Move to next waypoint
        nx, ny, nz = intruder.path[intruder.path_index]
        intruder.x, intruder.y, intruder.z = nx, ny, nz
        intruder.path_index += 1

        self.event_bus.publish(
            "intruder_moved", intruder=intruder,
        )

        # Check if adjacent to core → switch to ATTACKING
        if self._is_adjacent_to_core(intruder):
            intruder.state = IntruderState.ATTACKING
            intruder.ticks_since_attack = 0

    def _attack(self, intruder: Intruder, tick: int) -> None:
        """Deal damage to the core per attack interval."""
        intruder.ticks_since_attack += 1
        if intruder.ticks_since_attack < intruder.attack_interval:
            return
        intruder.ticks_since_attack = 0

        if self.core.alive:
            self.core.take_damage(intruder.effective_damage)
            self.event_bus.publish(
                "core_hit",
                intruder=intruder,
                damage=intruder.effective_damage,
            )

    def _compute_path(self, intruder: Intruder) -> None:
        """Compute path from intruder's current position to the core goal."""
        if self._core_goal is None:
            intruder.path = None
            return
        start = intruder.pos
        path = self.pathfinder.find_path(start, self._core_goal)
        if path is not None:
            intruder.path = path
            intruder.path_index = 1  # Skip start position (already there)
        else:
            intruder.path = None

    def _is_adjacent_to_core(self, intruder: Intruder) -> bool:
        """Check if the intruder is in a cell adjacent to the core."""
        ix, iy, iz = intruder.x, intruder.y, intruder.z
        return (
            abs(ix - CORE_X) + abs(iy - CORE_Y) + abs(iz - CORE_Z) <= 1
        )


# ── Arrow Trap System ───────────────────────────────────────────────

class ArrowTrapSystem:
    """Tracks arrow traps and fires at intruders in adjacent air cells.

    Subscribes to ``voxel_changed`` to maintain a set of trap positions,
    and to ``tick`` for per-tick damage evaluation.
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        intruder_ai: PrototypeIntruderAI,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.intruder_ai = intruder_ai

        # Set of (x, y, z) positions that contain arrow traps
        self.trap_positions: set[tuple[int, int, int]] = set()

        # Per-trap cooldown: (x, y, z) -> ticks remaining
        self._cooldowns: dict[tuple[int, int, int], int] = {}

        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("tick", self._on_tick)

    def _on_voxel_changed(
        self, x: int = 0, y: int = 0, z: int = 0,
        old_type: int = 0, new_type: int = 0, **kwargs,
    ) -> None:
        pos = (x, y, z)
        if new_type == VOXEL_ARROW_TRAP:
            self.trap_positions.add(pos)
        elif old_type == VOXEL_ARROW_TRAP:
            self.trap_positions.discard(pos)
            self._cooldowns.pop(pos, None)

    def _on_tick(self, tick: int, **kwargs) -> None:
        if not self.trap_positions:
            return

        # Build spatial index of living intruders
        intruder_index: dict[tuple[int, int, int], list[Intruder]] = {}
        for intruder in self.intruder_ai.intruders:
            if intruder.alive:
                intruder_index.setdefault(intruder.pos, []).append(intruder)

        if not intruder_index:
            return

        # Tick cooldowns down
        expired = []
        for pos, remaining in self._cooldowns.items():
            if remaining <= 1:
                expired.append(pos)
            else:
                self._cooldowns[pos] = remaining - 1
        for pos in expired:
            del self._cooldowns[pos]

        # Check each trap
        for trap_pos in list(self.trap_positions):
            if trap_pos in self._cooldowns:
                continue  # Still on cooldown

            tx, ty, tz = trap_pos
            fired = False
            for dx, dy, dz in _NEIGHBORS_6:
                nx, ny, nz = tx + dx, ty + dy, tz + dz
                neighbor_pos = (nx, ny, nz)

                # Only fire into air cells
                if self.voxel_grid.get(nx, ny, nz) != VOXEL_AIR:
                    continue

                targets = intruder_index.get(neighbor_pos)
                if targets:
                    for intruder in targets:
                        if intruder.alive:
                            intruder.take_damage(ARROW_TRAP_DAMAGE)
                            fired = True
                            if not intruder.alive:
                                self.event_bus.publish(
                                    "intruder_died",
                                    intruder=intruder,
                                )
                                logger.debug(
                                    "Arrow trap at %s killed intruder %d",
                                    trap_pos, intruder.id,
                                )

            if fired:
                self._cooldowns[trap_pos] = ARROW_TRAP_COOLDOWN
