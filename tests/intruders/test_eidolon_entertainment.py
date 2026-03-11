"""Tests for Eidolon entertainment system and sprite integration.

Verifies that Eidolons decay entertainment over time, summon sprites
when able, trigger boredom burst responses below the boredom threshold,
respect partner safety, and clean up dead/dissipated sprites.

Dependencies: intruders.decision, intruders.sprite, intruders.agent,
    intruders.archetypes, intruders.personal_map, intruders.party,
    world.voxel_grid, world.pathfinding, dungeon_core.core,
    core.event_bus, utils.rng, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    EIDOLON,
    IntruderObjective,
)
from dungeon_builder.intruders.decision import IntruderAI
from dungeon_builder.intruders.sprite import Sprite, SpriteState, spawn_sprites
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.party import Party
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.utils.rng import SeededRNG
import dungeon_builder.config as _cfg


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_ai(
    grid_w: int = 15, grid_d: int = 15, grid_h: int = 15,
    core_pos: tuple[int, int, int] = (7, 7, 7),
) -> tuple[IntruderAI, VoxelGrid, EventBus]:
    """Create a minimal IntruderAI with a small voxel grid."""
    eb = EventBus()
    grid = VoxelGrid(grid_w, grid_d, grid_h)
    pathfinder = AStarPathfinder(grid)
    cx, cy, cz = core_pos
    grid.set(cx, cy, cz, _cfg.VOXEL_CORE)
    core = DungeonCore(eb, cx, cy, cz)
    rng = SeededRNG(42)
    ai = IntruderAI(eb, grid, pathfinder, core, rng)
    return ai, grid, eb


def _make_eidolon(
    ai: IntruderAI,
    x: int = 3, y: int = 7, z: int = 7,
    party_id: int | None = None,
) -> Intruder:
    """Create an Eidolon intruder attached to the AI."""
    eidolon = Intruder(
        intruder_id=ai._next_id,
        x=x, y=y, z=z,
        archetype=EIDOLON,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=PersonalMap(),
        party_id=party_id,
    )
    ai._next_id += 1
    eidolon.state = IntruderState.ADVANCING
    ai.intruders.append(eidolon)
    return eidolon


def _make_eidolon_pair(
    ai: IntruderAI,
) -> tuple[Intruder, Intruder]:
    """Create a pair of Eidolons in the same party."""
    party_id = ai._next_party_id
    ai._next_party_id += 1

    e1 = _make_eidolon(ai, x=3, y=7, z=7, party_id=party_id)
    e2 = _make_eidolon(ai, x=4, y=7, z=7, party_id=party_id)

    party = Party(party_id=party_id, members=[e1, e2])
    ai.parties.append(party)
    return e1, e2


# ── Entertainment decay ────────────────────────────────────────────────


class TestEntertainmentDecay:
    """Verify entertainment decays each tick."""

    def test_decay_per_tick(self):
        """Entertainment decreases by EIDOLON_ENTERTAINMENT_DECAY each tick."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 1.0

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        expected = 1.0 - _cfg.EIDOLON_ENTERTAINMENT_DECAY
        assert abs(eidolon.entertainment - expected) < 1e-9

    def test_decay_clamps_to_zero(self):
        """Entertainment never goes below zero."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.0001  # Very small

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert eidolon.entertainment >= 0.0

    def test_decay_accumulates_over_ticks(self):
        """Multiple ticks accumulate decay."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 1.0

        for t in range(10):
            ai._tick_eidolon_entertainment(eidolon, tick=t)

        expected = max(0.0, 1.0 - 10 * _cfg.EIDOLON_ENTERTAINMENT_DECAY)
        assert abs(eidolon.entertainment - expected) < 1e-9


# ── Sprite summoning ──────────────────────────────────────────────────


class TestSpriteSummoning:
    """Verify sprites are summoned when conditions are met."""

    def test_summons_sprites_when_none_exist(self):
        """Eidolon summons sprites when no alive sprites and cooldown=0."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8  # Above boredom threshold
        eidolon.sprite_summon_cooldown = 0

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == _cfg.EIDOLON_SPRITE_CAPACITY

    def test_summoned_sprites_at_eidolon_position(self):
        """Summoned sprites spawn at the eidolon's position."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai, x=5, y=8, z=3)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 0

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        for s in eidolon.sprites:
            assert s.pos == (5, 8, 3)

    def test_no_summon_when_sprites_alive(self):
        """No new sprites summoned while existing ones are alive."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 0

        # Pre-add a sprite
        s = Sprite(sprite_id=99, owner_id=eidolon.id, x=5, y=5, z=5)
        eidolon.sprites.append(s)

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        # Should still only have the original sprite
        assert len(eidolon.sprites) == 1
        assert eidolon.sprites[0].id == 99

    def test_no_summon_below_boredom_threshold(self):
        """No summon when entertainment is below boredom threshold."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = _cfg.EIDOLON_BOREDOM_THRESHOLD - 0.01
        eidolon.sprite_summon_cooldown = 0

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == 0


# ── Summon cooldown ───────────────────────────────────────────────────


class TestSummonCooldown:
    """Verify summon cooldown is respected."""

    def test_cooldown_prevents_summon(self):
        """No sprites summoned while cooldown is active."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 5

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == 0

    def test_cooldown_decrements(self):
        """Cooldown decreases by 1 each tick."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 3

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert eidolon.sprite_summon_cooldown == 2

    def test_summon_sets_cooldown(self):
        """Summoning sprites sets the cooldown."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 0

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert eidolon.sprite_summon_cooldown == _cfg.SPRITE_SUMMON_COOLDOWN

    def test_summon_after_cooldown_expires(self):
        """Sprites summoned once cooldown reaches 0 and all sprites are dead."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 1

        # This tick: cooldown decrements to 0, then summon fires.
        # Summon resets the cooldown to SPRITE_SUMMON_COOLDOWN.
        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == _cfg.EIDOLON_SPRITE_CAPACITY
        assert eidolon.sprite_summon_cooldown == _cfg.SPRITE_SUMMON_COOLDOWN


# ── Boredom burst ────────────────────────────────────────────────────


class TestBoredomBurst:
    """Verify boredom triggers sprite burst."""

    def test_orders_burst_when_bored(self):
        """Sprites get burst order below boredom threshold."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = _cfg.EIDOLON_BOREDOM_THRESHOLD - 0.01

        # Pre-add sprites (far from any partner)
        s1 = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        s2 = Sprite(sprite_id=11, owner_id=eidolon.id, x=6, y=5, z=5)
        eidolon.sprites = [s1, s2]

        ai._eidolon_boredom_response(eidolon)

        assert s1.state == SpriteState.BURSTING
        assert s2.state == SpriteState.BURSTING

    def test_no_burst_above_threshold(self):
        """Sprites are not burst when above boredom threshold."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = _cfg.EIDOLON_BOREDOM_THRESHOLD + 0.1

        s = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        eidolon.sprites = [s]

        # Tick with entertainment above threshold
        ai._tick_eidolon_entertainment(eidolon, tick=1)

        # Should stay EXPLORING (boredom response not triggered)
        assert s.state != SpriteState.BURSTING

    def test_already_bursting_not_double_ordered(self):
        """Sprites already BURSTING are not re-ordered."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)

        s = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        s.state = SpriteState.BURSTING
        eidolon.sprites = [s]

        # Should not raise or change state
        ai._eidolon_boredom_response(eidolon)
        assert s.state == SpriteState.BURSTING


# ── Partner safety ───────────────────────────────────────────────────


class TestPartnerSafety:
    """Verify sprites don't burst near the eidolon's partner."""

    def test_no_burst_near_partner(self):
        """Sprite near partner is NOT ordered to burst."""
        ai, grid, eb = _make_ai()
        e1, e2 = _make_eidolon_pair(ai)

        # Sprite near partner (within SPRITE_PARTNER_SAFE_DISTANCE)
        s = Sprite(sprite_id=10, owner_id=e1.id, x=e2.x, y=e2.y, z=e2.z)
        e1.sprites = [s]

        ai._eidolon_boredom_response(e1)

        assert s.state == SpriteState.EXPLORING  # Not burst

    def test_burst_allowed_when_far_from_partner(self):
        """Sprite far from partner IS ordered to burst."""
        ai, grid, eb = _make_ai()
        e1, e2 = _make_eidolon_pair(ai)

        # Move partner far away
        e2.x, e2.y, e2.z = 14, 14, 14

        # Sprite near e1 but far from e2
        s = Sprite(sprite_id=10, owner_id=e1.id, x=3, y=7, z=7)
        e1.sprites = [s]

        ai._eidolon_boredom_response(e1)

        assert s.state == SpriteState.BURSTING

    def test_burst_allowed_when_partner_dead(self):
        """Sprite bursts freely when partner is dead."""
        ai, grid, eb = _make_ai()
        e1, e2 = _make_eidolon_pair(ai)

        e2.state = IntruderState.DEAD

        s = Sprite(sprite_id=10, owner_id=e1.id, x=e2.x, y=e2.y, z=e2.z)
        e1.sprites = [s]

        ai._eidolon_boredom_response(e1)

        assert s.state == SpriteState.BURSTING

    def test_burst_allowed_when_no_party(self):
        """Solo eidolon (no party) can burst freely."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)  # No party_id

        s = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        eidolon.sprites = [s]

        ai._eidolon_boredom_response(eidolon)

        assert s.state == SpriteState.BURSTING


# ── Sprite cleanup ───────────────────────────────────────────────────


class TestSpriteCleanup:
    """Verify dead/dissipated sprites are removed from the list."""

    def test_dead_sprites_removed(self):
        """Dead sprites are cleaned up after tick."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        # Set cooldown high to prevent re-summoning after cleanup
        eidolon.sprite_summon_cooldown = 50

        s = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        s.state = SpriteState.DEAD
        eidolon.sprites = [s]

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == 0

    def test_dissipated_sprites_removed(self):
        """Dissipated sprites are cleaned up after tick."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8
        eidolon.sprite_summon_cooldown = 50

        s = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        s.state = SpriteState.DISSIPATED
        eidolon.sprites = [s]

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == 0

    def test_alive_sprites_kept(self):
        """Alive sprites are kept in the list."""
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)
        eidolon.entertainment = 0.8

        s = Sprite(sprite_id=10, owner_id=eidolon.id, x=5, y=5, z=5)
        eidolon.sprites = [s]

        ai._tick_eidolon_entertainment(eidolon, tick=1)

        assert len(eidolon.sprites) == 1
        assert eidolon.sprites[0].id == 10


# ── _find_eidolon_partner ─────────────────────────────────────────────


class TestFindEidolonPartner:
    """Verify partner lookup."""

    def test_finds_partner(self):
        ai, grid, eb = _make_ai()
        e1, e2 = _make_eidolon_pair(ai)

        partner = ai._find_eidolon_partner(e1)
        assert partner is not None
        assert partner.id == e2.id

    def test_returns_none_for_solo(self):
        ai, grid, eb = _make_ai()
        eidolon = _make_eidolon(ai)

        partner = ai._find_eidolon_partner(eidolon)
        assert partner is None

    def test_returns_none_when_partner_dead(self):
        ai, grid, eb = _make_ai()
        e1, e2 = _make_eidolon_pair(ai)
        e2.state = IntruderState.DEAD

        partner = ai._find_eidolon_partner(e1)
        assert partner is None
