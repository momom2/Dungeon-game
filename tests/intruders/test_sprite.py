"""Tests for sprite familiar system.

Verifies that sprites explore, inspect blocks, build memory, dissipate
after the inspection limit, sacrifice into unpowered enchanted blocks,
and explode on command — setting blocks loose in a sphere.

Dependencies: intruders.sprite, intruders.agent, intruders.archetypes,
    intruders.personal_map, world.voxel_grid, core.event_bus,
    dungeon_core.mana, utils.rng, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.sprite import (
    Sprite,
    SpriteState,
    spawn_sprites,
    update_sprite,
    order_burst,
)
from dungeon_builder.intruders.agent import Intruder
from dungeon_builder.intruders.archetypes import EIDOLON, IntruderObjective
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.dungeon_core.mana import ManaSystem
from dungeon_builder.utils.rng import SeededRNG
import dungeon_builder.config as _cfg


# ── Helpers ──────────────────────────────────────────────────────────────


class _StubBuildSystem:
    """Minimal stand-in for BuildSystem (only ``active_digs`` is queried)."""
    active_digs: list = []


def _make_eidolon(
    x: int = 5, y: int = 5, z: int = 5,
) -> Intruder:
    """Create a minimal Eidolon for sprite tests."""
    return Intruder(
        intruder_id=1,
        x=x, y=y, z=z,
        archetype=EIDOLON,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=PersonalMap(),
    )


def _make_grid(size: int = 15) -> VoxelGrid:
    return VoxelGrid(size, size, size)


def _make_mana_system(
    grid: VoxelGrid,
    eb: EventBus | None = None,
) -> ManaSystem:
    eb = eb or EventBus()
    bs = _StubBuildSystem()
    return ManaSystem(eb, grid, bs)


# ── Sprite creation ──────────────────────────────────────────────────────


class TestSpriteCreation:
    """Verify Sprite constructor and initial state."""

    def test_initial_state(self):
        s = Sprite(sprite_id=1, owner_id=10, x=3, y=4, z=5)
        assert s.id == 1
        assert s.owner_id == 10
        assert s.pos == (3, 4, 5)
        assert s.state == SpriteState.EXPLORING
        assert s.hp == _cfg.SPRITE_HP
        assert s.max_hp == _cfg.SPRITE_HP
        assert s.alive is True
        assert s.inspection_count == 0
        assert s.target is None

    def test_repr(self):
        s = Sprite(sprite_id=1, owner_id=2, x=0, y=0, z=0)
        r = repr(s)
        assert "Sprite" in r
        assert "EXPLORING" in r


class TestSpawnSprites:
    """Verify spawn_sprites creates the correct pack."""

    def test_spawn_count(self):
        eidolon = _make_eidolon()
        sprites = spawn_sprites(eidolon, next_id_start=100)
        assert len(sprites) == _cfg.EIDOLON_SPRITE_CAPACITY

    def test_spawn_position(self):
        eidolon = _make_eidolon(x=3, y=7, z=2)
        sprites = spawn_sprites(eidolon, next_id_start=1)
        for s in sprites:
            assert s.pos == (3, 7, 2)

    def test_spawn_ids_sequential(self):
        eidolon = _make_eidolon()
        sprites = spawn_sprites(eidolon, next_id_start=50)
        ids = [s.id for s in sprites]
        assert ids == list(range(50, 50 + _cfg.EIDOLON_SPRITE_CAPACITY))

    def test_owner_id_matches(self):
        eidolon = _make_eidolon()
        sprites = spawn_sprites(eidolon, next_id_start=1)
        for s in sprites:
            assert s.owner_id == eidolon.id


# ── Sprite exploration ───────────────────────────────────────────────────


class TestSpriteExploration:
    """Verify sprite movement and inspection behavior."""

    def test_inspects_adjacent_blocks(self):
        """Sprite inspects adjacent non-air blocks."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # Place stone adjacent to sprite
        grid.set(6, 5, 5, _cfg.VOXEL_STONE)
        grid.set(4, 5, 5, _cfg.VOXEL_STONE)

        # Run enough ticks for a move to occur
        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng)

        assert (6, 5, 5) in s.inspected
        assert (4, 5, 5) in s.inspected

    def test_does_not_inspect_air(self):
        """Air blocks are not added to the inspected set."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # All adjacent cells are air (default)
        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng)

        # Nothing should be inspected (all air around)
        assert s.inspection_count == 0

    def test_moves_toward_uninspected_blocks(self):
        """Sprite moves toward uninspected non-air blocks."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # Place stone blocks a few cells away
        grid.set(8, 5, 5, _cfg.VOXEL_STONE)

        # Run several move ticks
        for _ in range(20):
            update_sprite(s, eidolon, grid, rng)

        # Sprite should have moved (either closer to target or randomly)
        assert s.pos != (5, 5, 5)

    def test_memory_persists_across_ticks(self):
        """Inspected set accumulates over multiple ticks."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # Place blocks around initial position
        grid.set(6, 5, 5, _cfg.VOXEL_STONE)

        # Run moves
        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng)

        count_before = s.inspection_count
        assert count_before > 0

        # Place more blocks at new position
        sx, sy, sz = s.pos
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0)):
            nx, ny, nz = sx + dx, sy + dy, sz + dz
            if grid.in_bounds(nx, ny, nz) and (nx, ny, nz) not in s.inspected:
                grid.set(nx, ny, nz, _cfg.VOXEL_STONE)

        # Run more ticks
        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng)

        # Memory should have grown
        assert s.inspection_count >= count_before


# ── Sprite dissipation ───────────────────────────────────────────────────


class TestSpriteDissipation:
    """Verify sprites dissipate after reaching the inspection limit."""

    def test_dissipates_at_inspection_limit(self):
        """Sprite transitions to DISSIPATED after SPRITE_INSPECTION_LIMIT."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # Pre-fill inspected set to just below limit
        for i in range(_cfg.SPRITE_INSPECTION_LIMIT - 1):
            s.inspected.add((100 + i, 100, 100))

        # Place a block adjacent to push over the limit
        grid.set(6, 5, 5, _cfg.VOXEL_STONE)

        # Tick until inspection happens
        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng)

        assert s.state == SpriteState.DISSIPATED
        assert s.alive is False

    def test_alive_below_limit(self):
        """Sprite stays alive while below inspection limit."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        grid.set(6, 5, 5, _cfg.VOXEL_STONE)

        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng)

        assert s.inspection_count < _cfg.SPRITE_INSPECTION_LIMIT
        assert s.alive is True


# ── Sprite sacrifice ─────────────────────────────────────────────────────


class TestSpriteSacrifice:
    """Verify sprites sacrifice into unpowered enchanted blocks."""

    def test_transitions_to_sacrificing(self):
        """Sprite near an unpowered enchanted block transitions to SACRIFICING."""
        grid = _make_grid()
        eb = EventBus()
        ms = _make_mana_system(grid, eb)
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # Place an enchanted door adjacent, globally unpowered
        grid.set(6, 5, 5, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.traps_powered = False

        # Tick until the first move fires — the sprite inspects adjacent and
        # transitions to SACRIFICING.  Stop before the next tick would
        # complete the sacrifice (it's already adjacent).
        for _ in range(_cfg.SPRITE_MOVE_INTERVAL):
            update_sprite(s, eidolon, grid, rng, mana_system=ms)

        assert s.state == SpriteState.SACRIFICING
        assert s.target == (6, 5, 5)

    def test_sacrifice_injects_mana(self):
        """Completing sacrifice injects mana into the block."""
        grid = _make_grid()
        eb = EventBus()
        ms = _make_mana_system(grid, eb)
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        # Place enchanted door adjacent, unpowered
        grid.set(6, 5, 5, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.traps_powered = False

        # Manually set sprite to SACRIFICING at adjacent position
        s.state = SpriteState.SACRIFICING
        s.target = (6, 5, 5)

        # Tick — should inject mana and dissipate (already adjacent, dist=1)
        update_sprite(s, eidolon, grid, rng, mana_system=ms)

        assert s.state == SpriteState.DISSIPATED
        assert ms._capacitance[(6, 5, 5)] == _cfg.MANA_SPRITE_INJECT

    def test_sacrifice_publishes_event(self):
        """Sacrifice publishes a sprite_sacrificed event."""
        grid = _make_grid()
        eb = EventBus()
        ms = _make_mana_system(grid, eb)
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        grid.set(6, 5, 5, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.traps_powered = False

        events = []
        eb.subscribe("sprite_sacrificed", lambda **kw: events.append(kw))

        s.state = SpriteState.SACRIFICING
        s.target = (6, 5, 5)
        update_sprite(s, eidolon, grid, rng, event_bus=eb, mana_system=ms)

        assert len(events) == 1
        assert events[0]["sprite_id"] == 1

    def test_no_sacrifice_when_globally_powered(self):
        """Sprite does not sacrifice into a globally powered block."""
        grid = _make_grid()
        eb = EventBus()
        ms = _make_mana_system(grid, eb)
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=5, y=5, z=5)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)

        grid.set(6, 5, 5, _cfg.VOXEL_ENCHANTED_DOOR, event_bus=eb)
        ms.traps_powered = True  # Globally powered

        for _ in range(_cfg.SPRITE_MOVE_INTERVAL + 1):
            update_sprite(s, eidolon, grid, rng, mana_system=ms)

        # Should still be EXPLORING (enchanted block is powered)
        assert s.state == SpriteState.EXPLORING


# ── Sprite burst ─────────────────────────────────────────────────────────


class TestSpriteBurst:
    """Verify sprite explosion mechanics."""

    def test_burst_sets_blocks_loose(self):
        """Burst sets solid diggable blocks loose within radius."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=7, y=7, z=7)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=7, y=7, z=7)

        # Place stone blocks within burst radius
        r = _cfg.SPRITE_BURST_RADIUS
        placed = []
        for dx in range(-r, r + 1):
            nx = 7 + dx
            if grid.in_bounds(nx, 7, 7):
                grid.set(nx, 7, 7, _cfg.VOXEL_STONE)
                placed.append((nx, 7, 7))

        order_burst(s)
        assert s.state == SpriteState.BURSTING

        update_sprite(s, eidolon, grid, rng)

        assert s.state == SpriteState.DEAD
        assert s.alive is False

        # All placed blocks within sphere should be loose
        for pos in placed:
            x, y, z = pos
            dist_sq = (x - 7) ** 2
            if dist_sq <= r * r:
                assert grid.is_loose(x, y, z), f"Block at {pos} should be loose"

    def test_burst_skips_non_diggable(self):
        """Burst does not set NON_DIGGABLE blocks loose."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=7, y=7, z=7)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=7, y=7, z=7)

        # Place bedrock (non-diggable) adjacent
        grid.set(8, 7, 7, _cfg.VOXEL_BEDROCK)

        order_burst(s)
        update_sprite(s, eidolon, grid, rng)

        assert not grid.is_loose(8, 7, 7)

    def test_burst_publishes_event(self):
        """Burst publishes a sprite_burst event."""
        grid = _make_grid()
        eb = EventBus()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=7, y=7, z=7)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=7, y=7, z=7)

        events = []
        eb.subscribe("sprite_burst", lambda **kw: events.append(kw))

        order_burst(s)
        update_sprite(s, eidolon, grid, rng, event_bus=eb)

        assert len(events) == 1
        assert events[0]["sprite_id"] == 1
        assert events[0]["radius"] == _cfg.SPRITE_BURST_RADIUS

    def test_order_burst_on_dead_sprite_noop(self):
        """Ordering burst on a dead sprite does nothing."""
        s = Sprite(sprite_id=1, owner_id=1, x=0, y=0, z=0)
        s.state = SpriteState.DEAD
        order_burst(s)
        assert s.state == SpriteState.DEAD

    def test_burst_skips_air(self):
        """Burst doesn't try to set air blocks loose."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon(x=7, y=7, z=7)
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=7, y=7, z=7)

        # All air around — should burst without error
        order_burst(s)
        update_sprite(s, eidolon, grid, rng)

        assert s.state == SpriteState.DEAD


# ── Sprite damage ────────────────────────────────────────────────────────


class TestSpriteDamage:
    """Verify sprite HP and damage mechanics."""

    def test_take_damage_reduces_hp(self):
        s = Sprite(sprite_id=1, owner_id=1, x=0, y=0, z=0)
        s.take_damage(2)
        assert s.hp == _cfg.SPRITE_HP - 2

    def test_lethal_damage_kills(self):
        s = Sprite(sprite_id=1, owner_id=1, x=0, y=0, z=0)
        s.take_damage(9999)
        assert s.hp == 0
        assert s.state == SpriteState.DEAD
        assert s.alive is False

    def test_dead_sprite_skipped(self):
        """update_sprite skips dead sprites."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon()
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)
        s.state = SpriteState.DEAD

        old_pos = s.pos
        update_sprite(s, eidolon, grid, rng)
        assert s.pos == old_pos  # Didn't move

    def test_dissipated_sprite_skipped(self):
        """update_sprite skips dissipated sprites."""
        grid = _make_grid()
        rng = SeededRNG(42)
        eidolon = _make_eidolon()
        s = Sprite(sprite_id=1, owner_id=eidolon.id, x=5, y=5, z=5)
        s.state = SpriteState.DISSIPATED

        update_sprite(s, eidolon, grid, rng)
        assert s.state == SpriteState.DISSIPATED
