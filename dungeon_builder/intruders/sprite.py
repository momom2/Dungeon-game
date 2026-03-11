"""Sprite familiar system for the Eidolon archetype.

Sprites are ethereal familiars summoned by Eidolons.  They fly around
independently, inspecting objects and keeping a memory of recently seen
blocks.  They have three notable behaviours:

1. **Inspection / dissipation:** Sprites move toward uninspected non-air
   blocks.  After inspecting ``SPRITE_INSPECTION_LIMIT`` objects they
   dissipate harmlessly.
2. **Sacrifice / mana injection:** If a sprite finds an unpowered
   enchanted block, it disappears and injects mana into the block's
   capacitance, temporarily powering it despite global mana depletion.
3. **Burst / explosion:** On command from a bored Eidolon, the sprite
   explodes — setting all blocks within a sphere of
   ``SPRITE_BURST_RADIUS`` loose (subject to gravity).

Dependencies: config, core.event_bus, world.voxel_grid, dungeon_core.mana
Dependents: intruders.agent, intruders.decision, core.save_system,
    tests/intruders/
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

import dungeon_builder.config as _cfg

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.dungeon_core.mana import ManaSystem
    from dungeon_builder.intruders.agent import Intruder
    from dungeon_builder.utils.rng import SeededRNG
    from dungeon_builder.world.voxel_grid import VoxelGrid


# ── State enum ────────────────────────────────────────────────────────────


class SpriteState(Enum):
    """Lifecycle states for a sprite familiar."""

    EXPLORING = auto()     # Flying around, inspecting objects
    SACRIFICING = auto()   # Moving toward an unpowered enchanted block
    BURSTING = auto()      # About to explode (ordered by eidolon)
    DISSIPATED = auto()    # Gone — inspection limit reached or sacrifice
    DEAD = auto()          # Killed by damage or burst


# ── Sprite entity ─────────────────────────────────────────────────────────


class Sprite:
    """An ethereal familiar controlled by an Eidolon.

    Much lighter than a full :class:`Intruder`.  Sprites fly (ignore
    terrain), keep a memory of inspected blocks, and interact with
    enchanted objects.
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
        # Memory / targeting
        "inspected",         # set[(x, y, z)] — already inspected
        "target",            # (x, y, z) | None — current movement goal
        "ticks_since_move",
    )

    def __init__(
        self,
        sprite_id: int,
        owner_id: int,
        x: int,
        y: int,
        z: int,
    ) -> None:
        self.id = sprite_id
        self.owner_id = owner_id

        self.x = x
        self.y = y
        self.z = z

        self.hp: int = _cfg.SPRITE_HP
        self.max_hp: int = _cfg.SPRITE_HP

        self.state = SpriteState.EXPLORING

        self.inspected: set[tuple[int, int, int]] = set()
        self.target: tuple[int, int, int] | None = None
        self.ticks_since_move: int = 0

    # ── Convenience properties ────────────────────────────────────

    @property
    def pos(self) -> tuple[int, int, int]:
        return (self.x, self.y, self.z)

    @property
    def alive(self) -> bool:
        return self.state not in (SpriteState.DISSIPATED, SpriteState.DEAD)

    @property
    def inspection_count(self) -> int:
        return len(self.inspected)

    def take_damage(self, amount: int) -> None:
        """Apply damage, clamping HP to 0."""
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.state = SpriteState.DEAD

    def __repr__(self) -> str:
        return (
            f"Sprite(id={self.id}, owner={self.owner_id}, "
            f"pos=({self.x},{self.y},{self.z}), "
            f"hp={self.hp}/{self.max_hp}, "
            f"inspected={self.inspection_count}, "
            f"state={self.state.name})"
        )


# ── Sprite controller ────────────────────────────────────────────────────


def spawn_sprites(
    eidolon: Intruder,
    next_id_start: int,
) -> list[Sprite]:
    """Create the initial pack of sprites for an Eidolon.

    Sprites spawn at the eidolon's position.
    """
    count = _cfg.EIDOLON_SPRITE_CAPACITY
    sprites: list[Sprite] = []
    for i in range(count):
        s = Sprite(
            sprite_id=next_id_start + i,
            owner_id=eidolon.id,
            x=eidolon.x,
            y=eidolon.y,
            z=eidolon.z,
        )
        sprites.append(s)
    return sprites


def update_sprite(
    sprite: Sprite,
    eidolon: Intruder,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
    event_bus: EventBus | None = None,
    mana_system: ManaSystem | None = None,
) -> None:
    """Tick one sprite.  Called every game tick from decision.py.

    - EXPLORING: fly around, inspect objects, check for enchanted blocks
    - SACRIFICING: move to unpowered enchanted block, inject mana, dissipate
    - BURSTING: explode immediately, set blocks loose
    - DISSIPATED / DEAD: skip
    """
    if not sprite.alive:
        return

    if sprite.state == SpriteState.EXPLORING:
        _tick_exploring(sprite, eidolon, voxel_grid, rng, mana_system)
    elif sprite.state == SpriteState.SACRIFICING:
        _tick_sacrificing(sprite, voxel_grid, mana_system, event_bus)
    elif sprite.state == SpriteState.BURSTING:
        _execute_burst(sprite, voxel_grid, event_bus)


def order_burst(sprite: Sprite) -> None:
    """Order a sprite to explode on its next update."""
    if sprite.alive:
        sprite.state = SpriteState.BURSTING


# ── Internal tick handlers ────────────────────────────────────────────────


def _tick_exploring(
    sprite: Sprite,
    eidolon: Intruder,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
    mana_system: ManaSystem | None = None,
) -> None:
    """Move toward uninspected objects, inspect adjacent blocks.

    Sprites fly freely (ignore terrain).  Each move tick:
    1. Inspect all adjacent non-air blocks.
    2. If an unpowered enchanted block is found → SACRIFICING.
    3. If inspection limit reached → DISSIPATED.
    4. Otherwise, move toward the nearest uninspected block.
    """
    sprite.ticks_since_move += 1
    if sprite.ticks_since_move < _cfg.SPRITE_MOVE_INTERVAL:
        return
    sprite.ticks_since_move = 0

    # 1. Inspect adjacent blocks
    _inspect_adjacent(sprite, voxel_grid, mana_system)

    # 2. Check state transitions from inspection
    if sprite.state != SpriteState.EXPLORING:
        return  # Transitioned to SACRIFICING

    # 3. Check dissipation
    if sprite.inspection_count >= _cfg.SPRITE_INSPECTION_LIMIT:
        sprite.state = SpriteState.DISSIPATED
        return

    # 4. Find next target if needed
    if sprite.target is None or sprite.pos == sprite.target:
        sprite.target = _find_inspection_target(sprite, voxel_grid, rng)

    # 5. Move toward target (flying — ignores terrain)
    if sprite.target is not None:
        tx, ty, tz = sprite.target
        dx = _sign(tx - sprite.x)
        dy = _sign(ty - sprite.y)
        dz = _sign(tz - sprite.z)
        nx, ny, nz = sprite.x + dx, sprite.y + dy, sprite.z + dz
        if voxel_grid.in_bounds(nx, ny, nz):
            sprite.x, sprite.y, sprite.z = nx, ny, nz
    else:
        # No targets in range — wander randomly
        _move_random(sprite, voxel_grid, rng)


def _inspect_adjacent(
    sprite: Sprite,
    voxel_grid: VoxelGrid,
    mana_system: ManaSystem | None = None,
) -> None:
    """Inspect all 6-adjacent blocks.

    Adds non-air blocks to the sprite's inspected set.  If an unpowered
    enchanted block is found, the sprite transitions to SACRIFICING —
    it will move to that block and inject mana.
    """
    for dx, dy, dz in (
        (1, 0, 0), (-1, 0, 0),
        (0, 1, 0), (0, -1, 0),
        (0, 0, 1), (0, 0, -1),
    ):
        nx, ny, nz = sprite.x + dx, sprite.y + dy, sprite.z + dz
        if not voxel_grid.in_bounds(nx, ny, nz):
            continue
        pos = (nx, ny, nz)
        if pos in sprite.inspected:
            continue
        vtype = voxel_grid.get(nx, ny, nz)
        if vtype == _cfg.VOXEL_AIR:
            continue

        sprite.inspected.add(pos)

        # Check for unpowered enchanted block → sacrifice
        if vtype in _cfg.MAGICAL_TRAP_TYPES and mana_system is not None:
            if not mana_system.is_block_powered(nx, ny, nz):
                sprite.target = pos
                sprite.state = SpriteState.SACRIFICING
                return


def _tick_sacrificing(
    sprite: Sprite,
    voxel_grid: VoxelGrid,
    mana_system: ManaSystem | None = None,
    event_bus: EventBus | None = None,
) -> None:
    """Move to the target enchanted block and inject mana, then dissipate."""
    if sprite.target is None:
        sprite.state = SpriteState.EXPLORING
        return

    tx, ty, tz = sprite.target
    dist = abs(sprite.x - tx) + abs(sprite.y - ty) + abs(sprite.z - tz)

    if dist <= 1:
        # Adjacent — inject mana and dissipate
        if mana_system is not None:
            mana_system.inject_mana(tx, ty, tz, _cfg.MANA_SPRITE_INJECT)
        sprite.state = SpriteState.DISSIPATED
        if event_bus is not None:
            event_bus.publish(
                "sprite_sacrificed",
                sprite_id=sprite.id,
                x=tx, y=ty, z=tz,
            )
    else:
        # Move toward target (flying)
        sprite.ticks_since_move += 1
        if sprite.ticks_since_move >= _cfg.SPRITE_MOVE_INTERVAL:
            sprite.ticks_since_move = 0
            dx = _sign(tx - sprite.x)
            dy = _sign(ty - sprite.y)
            dz = _sign(tz - sprite.z)
            nx, ny, nz = sprite.x + dx, sprite.y + dy, sprite.z + dz
            if voxel_grid.in_bounds(nx, ny, nz):
                sprite.x, sprite.y, sprite.z = nx, ny, nz


def _execute_burst(
    sprite: Sprite,
    voxel_grid: VoxelGrid,
    event_bus: EventBus | None = None,
) -> None:
    """Explode: set all blocks in a sphere of SPRITE_BURST_RADIUS loose.

    Only affects solid, diggable blocks.  Bedrock, reinforced walls,
    and other NON_DIGGABLE blocks are immune.
    """
    r = _cfg.SPRITE_BURST_RADIUS
    cx, cy, cz = sprite.x, sprite.y, sprite.z
    r_sq = r * r

    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if dx * dx + dy * dy + dz * dz > r_sq:
                    continue  # Outside sphere
                nx, ny, nz = cx + dx, cy + dy, cz + dz
                if not voxel_grid.in_bounds(nx, ny, nz):
                    continue
                vtype = voxel_grid.get(nx, ny, nz)
                if vtype != _cfg.VOXEL_AIR and vtype not in _cfg.NON_DIGGABLE:
                    voxel_grid.set_loose(nx, ny, nz, True)

    sprite.state = SpriteState.DEAD
    if event_bus is not None:
        event_bus.publish(
            "sprite_burst",
            sprite_id=sprite.id,
            x=cx, y=cy, z=cz, radius=r,
        )


# ── Target finding ────────────────────────────────────────────────────────


def _find_inspection_target(
    sprite: Sprite,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
) -> tuple[int, int, int] | None:
    """Find the nearest uninspected non-air block within SPRITE_MEMORY_RANGE.

    Picks randomly from the top 5 closest candidates to add variety.
    Returns None if no targets are available.
    """
    r = _cfg.SPRITE_MEMORY_RANGE
    cx, cy, cz = sprite.x, sprite.y, sprite.z
    candidates: list[tuple[int, tuple[int, int, int]]] = []

    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for dz in range(-r, r + 1):
                nx, ny, nz = cx + dx, cy + dy, cz + dz
                pos = (nx, ny, nz)
                if pos in sprite.inspected:
                    continue
                if not voxel_grid.in_bounds(nx, ny, nz):
                    continue
                vtype = voxel_grid.get(nx, ny, nz)
                if vtype == _cfg.VOXEL_AIR:
                    continue
                dist = abs(dx) + abs(dy) + abs(dz)
                candidates.append((dist, pos))

    if not candidates:
        return None

    candidates.sort()
    top = candidates[:5]
    return rng.choice(top)[1]


# ── Helpers ───────────────────────────────────────────────────────────────


def _move_random(
    sprite: Sprite,
    voxel_grid: VoxelGrid,
    rng: SeededRNG,
) -> None:
    """Move the sprite in a random direction (flying — ignores terrain)."""
    direction = rng.randint(0, 5)
    dx, dy, dz = [
        (1, 0, 0), (-1, 0, 0),
        (0, 1, 0), (0, -1, 0),
        (0, 0, 1), (0, 0, -1),
    ][direction]
    nx, ny, nz = sprite.x + dx, sprite.y + dy, sprite.z + dz
    if voxel_grid.in_bounds(nx, ny, nz):
        sprite.x, sprite.y, sprite.z = nx, ny, nz


def _sign(n: int) -> int:
    """Return -1, 0, or 1."""
    if n > 0:
        return 1
    if n < 0:
        return -1
    return 0
