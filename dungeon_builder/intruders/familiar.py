"""Familiar sub-entity system for the Mole Tamer archetype.

Familiars are lightweight digging creatures controlled by a Mole Tamer
intruder.  They can dig tunnels, follow their owner, and become unruly
(losing control) after too much digging.  They are actual entities with
position, HP, and simple pathfinding — not abstract abilities.

Dependencies: config, intruders.agent, intruders.personal_map, utils.rng,
    world.voxel_grid
Dependents: intruders.agent, intruders.decision, core.save_system,
    tests/intruders/
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

import dungeon_builder.config as _cfg

if TYPE_CHECKING:
    from dungeon_builder.intruders.agent import Intruder
    from dungeon_builder.intruders.personal_map import PersonalMap
    from dungeon_builder.utils.rng import SeededRNG
    from dungeon_builder.world.voxel_grid import VoxelGrid


class FamiliarState(Enum):
    """Lifecycle states for a familiar."""

    FOLLOWING = auto()    # Trailing the tamer, awaiting orders
    DIGGING = auto()      # Actively tunnelling at a target block
    UNRULY = auto()       # Lost control — random movement / digging
    DEAD = auto()


class Familiar:
    """A single digging familiar controlled by a Mole Tamer.

    Much lighter than a full :class:`Intruder`: no personal map, no
    equipment, no party membership.  Pathfinds using the owner's
    personal map.
    """

    __slots__ = (
        "id",
        "owner_id",
        # Position
        "x", "y", "z",
        # Combat
        "hp", "max_hp",
        # State
        "state",
        # Digging
        "dig_target",         # (x, y, z) | None
        "dig_progress",       # dict[(x,y,z), ticks_spent]
        "unruliness",         # 0.0-1.0, increases with digging
        # Movement
        "path",
        "path_index",
        "ticks_since_move",
    )

    def __init__(
        self,
        familiar_id: int,
        owner_id: int,
        x: int,
        y: int,
        z: int,
    ) -> None:
        self.id = familiar_id
        self.owner_id = owner_id

        self.x = x
        self.y = y
        self.z = z

        self.hp: int = _cfg.FAMILIAR_HP
        self.max_hp: int = _cfg.FAMILIAR_HP

        self.state = FamiliarState.FOLLOWING

        self.dig_target: tuple[int, int, int] | None = None
        self.dig_progress: dict[tuple[int, int, int], int] = {}
        self.unruliness: float = 0.0

        self.path: list[tuple[int, int, int]] | None = None
        self.path_index: int = 0
        self.ticks_since_move: int = 0

    # ── Convenience properties ────────────────────────────────────

    @property
    def pos(self) -> tuple[int, int, int]:
        return (self.x, self.y, self.z)

    @property
    def alive(self) -> bool:
        return self.state != FamiliarState.DEAD

    def take_damage(self, amount: int) -> None:
        """Apply damage, clamping HP to 0."""
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.state = FamiliarState.DEAD

    def __repr__(self) -> str:
        return (
            f"Familiar(id={self.id}, owner={self.owner_id}, "
            f"pos=({self.x},{self.y},{self.z}), "
            f"hp={self.hp}/{self.max_hp}, "
            f"unruly={self.unruliness:.2f}, "
            f"state={self.state.name})"
        )


# ── Familiar controller ──────────────────────────────────────────────


def spawn_familiars(
    tamer: Intruder,
    next_id_start: int,
) -> list[Familiar]:
    """Create the initial pack of familiars for a Mole Tamer.

    Familiars spawn at the tamer's position.  The number is determined
    by ``tamer.archetype.familiar_capacity``.
    """
    count = tamer.archetype.familiar_capacity
    familiars: list[Familiar] = []
    for i in range(count):
        f = Familiar(
            familiar_id=next_id_start + i,
            owner_id=tamer.id,
            x=tamer.x,
            y=tamer.y,
            z=tamer.z,
        )
        familiars.append(f)
    return familiars


def update_familiar(
    familiar: Familiar,
    tamer: Intruder,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
) -> None:
    """Tick one familiar.  Called every game tick from decision.py.

    - FOLLOWING: move toward tamer
    - DIGGING: continue dig progress, check unruliness
    - UNRULY: random movement / random digging
    - DEAD: skip
    """
    if not familiar.alive:
        return

    if familiar.state == FamiliarState.FOLLOWING:
        _tick_following(familiar, tamer)
    elif familiar.state == FamiliarState.DIGGING:
        _tick_digging(familiar, tamer, voxel_grid, rng)
    elif familiar.state == FamiliarState.UNRULY:
        _tick_unruly(familiar, voxel_grid, rng)


def order_dig(
    familiar: Familiar,
    target: tuple[int, int, int],
) -> None:
    """Order a following familiar to dig at a target position."""
    if familiar.state != FamiliarState.FOLLOWING:
        return
    familiar.state = FamiliarState.DIGGING
    familiar.dig_target = target
    familiar.path = None
    familiar.path_index = 0


def recall_familiar(familiar: Familiar) -> None:
    """Recall a familiar back to following state (if not dead/unruly)."""
    if familiar.state == FamiliarState.DEAD:
        return
    if familiar.state == FamiliarState.UNRULY:
        return  # Can't recall an unruly familiar
    familiar.state = FamiliarState.FOLLOWING
    familiar.dig_target = None
    familiar.path = None
    familiar.path_index = 0


def check_unruliness(familiar: Familiar, rng: SeededRNG) -> bool:
    """Check if a familiar goes unruly after a dig.

    Returns True if the familiar just became unruly.
    """
    if familiar.unruliness >= _cfg.FAMILIAR_UNRULY_THRESHOLD:
        if rng.random() < familiar.unruliness:
            familiar.state = FamiliarState.UNRULY
            familiar.dig_target = None
            familiar.path = None
            return True
    return False


# ── Internal tick handlers ────────────────────────────────────────────


def _tick_following(familiar: Familiar, tamer: Intruder) -> None:
    """Move the familiar toward the tamer's position."""
    familiar.ticks_since_move += 1
    if familiar.ticks_since_move < _cfg.FAMILIAR_MOVE_INTERVAL:
        return
    familiar.ticks_since_move = 0

    # Simple movement toward tamer (Manhattan step)
    dx = _sign(tamer.x - familiar.x)
    dy = _sign(tamer.y - familiar.y)
    dz = _sign(tamer.z - familiar.z)

    if dx != 0 or dy != 0 or dz != 0:
        familiar.x += dx
        familiar.y += dy
        familiar.z += dz


def _tick_digging(
    familiar: Familiar,
    tamer: Intruder,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
) -> None:
    """Progress on the current dig target."""
    target = familiar.dig_target
    if target is None:
        familiar.state = FamiliarState.FOLLOWING
        return

    # Move toward dig target if not adjacent
    tx, ty, tz = target
    dist = abs(familiar.x - tx) + abs(familiar.y - ty) + abs(familiar.z - tz)
    if dist > 1:
        familiar.ticks_since_move += 1
        if familiar.ticks_since_move >= _cfg.FAMILIAR_MOVE_INTERVAL:
            familiar.ticks_since_move = 0
            familiar.x += _sign(tx - familiar.x)
            familiar.y += _sign(ty - familiar.y)
            familiar.z += _sign(tz - familiar.z)
        return

    # Adjacent — dig
    progress = familiar.dig_progress.get(target, 0) + 1
    familiar.dig_progress[target] = progress

    if progress >= _cfg.FAMILIAR_DIG_SPEED:
        # Dig complete — convert to air
        voxel_grid.set_voxel(tx, ty, tz, _cfg.VOXEL_AIR)
        del familiar.dig_progress[target]
        familiar.dig_target = None

        # Increase unruliness
        familiar.unruliness = min(
            1.0,
            familiar.unruliness + _cfg.FAMILIAR_UNRULINESS_PER_DIG,
        )

        # Check if we go unruly
        if not check_unruliness(familiar, rng):
            familiar.state = FamiliarState.FOLLOWING


def _tick_unruly(
    familiar: Familiar,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
) -> None:
    """Random movement and random digging for an unruly familiar."""
    familiar.ticks_since_move += 1
    if familiar.ticks_since_move < _cfg.FAMILIAR_MOVE_INTERVAL:
        return
    familiar.ticks_since_move = 0

    # Random direction
    direction = rng.randint(0, 5)
    dx, dy, dz = [
        (1, 0, 0), (-1, 0, 0),
        (0, 1, 0), (0, -1, 0),
        (0, 0, 1), (0, 0, -1),
    ][direction]

    nx, ny, nz = familiar.x + dx, familiar.y + dy, familiar.z + dz

    # Bounds check
    if not voxel_grid.in_bounds(nx, ny, nz):
        return

    vtype = voxel_grid.get_voxel(nx, ny, nz)
    if vtype == _cfg.VOXEL_AIR:
        familiar.x = nx
        familiar.y = ny
        familiar.z = nz
    elif vtype not in _cfg.NON_DIGGABLE:
        # Random dig attempt
        voxel_grid.set_voxel(nx, ny, nz, _cfg.VOXEL_AIR)
        familiar.unruliness = min(
            1.0,
            familiar.unruliness + _cfg.FAMILIAR_UNRULINESS_PER_DIG,
        )


# ── Helpers ───────────────────────────────────────────────────────────


def _sign(n: int) -> int:
    """Return -1, 0, or 1."""
    if n > 0:
        return 1
    if n < 0:
        return -1
    return 0
