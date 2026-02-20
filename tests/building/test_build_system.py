"""Tests for the dig/build system, QoL features, and dig queue feedback."""

import inspect

import numpy as np
import pytest

import dungeon_builder.config as _cfg
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.game_state import GameState
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.building.build_system import BuildSystem
from dungeon_builder.world.claimed_territory import ClaimedTerritorySystem
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DIRT,
    VOXEL_BEDROCK,
    VOXEL_CORE,
    VOXEL_IRON_ORE,
    VOXEL_GOLD_ORE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_LAVA,
    VOXEL_REINFORCED_WALL,
    DEFAULT_SEED,
    DIG_DURATION,
    NON_DIGGABLE,
)


def test_queue_dig_on_stone():
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_STONE
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)

    assert bs.queue_dig(1, 1, 1) is True
    assert len(bs.dig_queue) == 1


def test_cannot_dig_air():
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.visible[:] = True  # must be visible for validation to fire
    bs = BuildSystem(bus, grid)

    assert bs.queue_dig(0, 0, 0) is False  # Air


def test_cannot_dig_bedrock():
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[0, 0, 0] = VOXEL_BEDROCK
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)

    assert bs.queue_dig(0, 0, 0) is False


def test_cannot_dig_lava():
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[0, 0, 0] = VOXEL_LAVA
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)

    assert bs.queue_dig(0, 0, 0) is False


def test_dig_creates_loose_material():
    """Dig completes by making material loose, not removing it."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_DIRT  # Dirt takes 20 ticks
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(1, 1, 1)

    completions = []
    bus.subscribe("dig_complete", lambda **kw: completions.append(kw))

    # Simulate 19 ticks — not yet complete
    for i in range(1, 20):
        bus.publish("tick", tick=i)
    assert len(completions) == 0
    assert grid.get(1, 1, 1) == VOXEL_DIRT
    assert not grid.is_loose(1, 1, 1)

    # 20th tick — complete, material is now loose
    bus.publish("tick", tick=20)
    assert len(completions) == 1
    assert grid.get(1, 1, 1) == VOXEL_DIRT  # Still dirt, but loose
    assert grid.is_loose(1, 1, 1)


def test_cannot_dig_already_loose():
    """Can't queue a dig on already-loose material."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_STONE
    grid.set_loose(1, 1, 1, True)
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)

    errors = []
    bus.subscribe("error_message", lambda **kw: errors.append(kw))

    assert bs.queue_dig(1, 1, 1) is False
    assert len(errors) == 1
    assert "already loose" in errors[0]["text"]


def test_no_double_queue():
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_STONE
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)

    assert bs.queue_dig(1, 1, 1) is True
    assert bs.queue_dig(1, 1, 1) is False  # Already queued


def test_stone_takes_longer_than_dirt():
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[0, 0, 0] = VOXEL_DIRT
    grid.grid[1, 0, 0] = VOXEL_STONE
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(0, 0, 0)
    bs.queue_dig(1, 0, 0)

    for i in range(1, 21):
        bus.publish("tick", tick=i)
    assert grid.is_loose(0, 0, 0)  # Dirt done at 20
    assert not grid.is_loose(1, 0, 0)  # Stone not yet done

    for i in range(21, 41):
        bus.publish("tick", tick=i)
    assert grid.is_loose(1, 0, 0)  # Stone done at 40


def test_left_click_dig_mode():
    """voxel_left_clicked with mode=dig should queue a dig."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_STONE
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)

    bus.publish("voxel_left_clicked", x=1, y=1, z=1, mode="dig")
    assert len(bs.dig_queue) == 1


# ---------------------------------------------------------------------------
# Dig overlay: is_being_dug and get_dig_progress
# ---------------------------------------------------------------------------


def test_is_being_dug_queued():
    """Queued blocks report as being dug."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_STONE
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(1, 1, 1)

    assert bs.is_being_dug(1, 1, 1) is True
    assert bs.is_being_dug(0, 0, 0) is False


def test_is_being_dug_active():
    """Active digs report as being dug."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_DIRT
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(1, 1, 1)

    # First tick promotes to active
    bus.publish("tick", tick=1)
    assert bs.is_being_dug(1, 1, 1) is True


def test_is_being_dug_completed():
    """Completed digs are no longer reported as being dug."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_DIRT  # 20 ticks
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(1, 1, 1)

    for i in range(1, 21):
        bus.publish("tick", tick=i)

    assert bs.is_being_dug(1, 1, 1) is False


def test_dig_progress_queued():
    """Queued digs have progress 0.0."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_STONE
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(1, 1, 1)

    assert bs.get_dig_progress(1, 1, 1) == pytest.approx(0.0)


def test_dig_progress_active():
    """Active digs report fractional progress."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    grid.grid[1, 1, 1] = VOXEL_DIRT  # 20 ticks
    grid.visible[:] = True
    bs = BuildSystem(bus, grid)
    bs.queue_dig(1, 1, 1)

    # Tick 1 promotes to active and decrements once (19 remaining / 20 total)
    bus.publish("tick", tick=1)
    assert bs.get_dig_progress(1, 1, 1) == pytest.approx(1.0 / 20.0)

    # After 10 more ticks (11 total), 9 remaining / 20 total
    for i in range(2, 12):
        bus.publish("tick", tick=i)
    assert bs.get_dig_progress(1, 1, 1) == pytest.approx(11.0 / 20.0)


def test_dig_progress_not_digging():
    """Non-digging blocks return -1.0."""
    bus = EventBus()
    grid = VoxelGrid(width=4, depth=4, height=4)
    bs = BuildSystem(bus, grid)

    assert bs.get_dig_progress(0, 0, 0) == pytest.approx(-1.0)


# ══════════════════════════════════════════════════════════════════════
# Pending digs
# ══════════════════════════════════════════════════════════════════════


class TestPendingDigs:
    """Invisible blocks go to pending_digs, promoted on visibility."""

    def _setup(self):
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=4)
        grid.grid[:] = VOXEL_STONE
        bs = BuildSystem(bus, grid)
        return bus, grid, bs

    def test_invisible_block_goes_pending(self):
        bus, grid, bs = self._setup()
        # Not visible → pending
        assert bs.queue_dig(4, 4, 2) is True
        assert len(bs.pending_digs) == 1
        assert len(bs.dig_queue) == 0

    def test_pending_publishes_event(self):
        bus, grid, bs = self._setup()
        events = []
        bus.subscribe("dig_pending", lambda **kw: events.append(kw))
        bs.queue_dig(4, 4, 2)
        assert len(events) == 1
        assert events[0]["x"] == 4

    def test_is_being_dug_includes_pending(self):
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        assert bs.is_being_dug(4, 4, 2) is True
        assert bs.is_pending_dig(4, 4, 2) is True

    def test_pending_progress_is_zero(self):
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        assert bs.get_dig_progress(4, 4, 2) == pytest.approx(0.0)

    def test_no_double_queue_pending(self):
        bus, grid, bs = self._setup()
        assert bs.queue_dig(4, 4, 2) is True
        assert bs.queue_dig(4, 4, 2) is False  # duplicate

    def test_pending_promoted_when_visible(self):
        """When block becomes visible, pending dig moves to dig_queue."""
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        assert len(bs.pending_digs) == 1

        # Make it visible and trigger check
        grid.visible[4, 4, 2] = True
        bs._check_pending_digs()

        assert len(bs.pending_digs) == 0
        assert len(bs.dig_queue) == 1
        # Duration should be set for stone
        job = bs.dig_queue[0]
        assert job.total_ticks == DIG_DURATION[VOXEL_STONE]

    def test_air_rejected_before_pending(self):
        """Air blocks are rejected upfront — never go to pending."""
        bus, grid, bs = self._setup()
        grid.grid[4, 4, 2] = VOXEL_AIR
        # Air is rejected regardless of visibility
        assert bs.queue_dig(4, 4, 2) is False
        assert len(bs.pending_digs) == 0

    def test_non_diggable_rejected_before_pending(self):
        """Non-diggable blocks (bedrock) are rejected upfront — never pending."""
        bus, grid, bs = self._setup()
        grid.grid[4, 4, 2] = VOXEL_BEDROCK
        assert bs.queue_dig(4, 4, 2) is False
        assert len(bs.pending_digs) == 0

    def test_pending_cancelled_when_visible_becomes_air(self):
        """Pending dig cancelled if block type changed to air before reveal."""
        bus, grid, bs = self._setup()
        # Queue invisible stone → goes to pending
        assert bs.queue_dig(4, 4, 2) is True
        assert len(bs.pending_digs) == 1

        # Block type changes to air while still pending
        grid.grid[4, 4, 2] = VOXEL_AIR

        cancelled = []
        bus.subscribe("dig_cancelled", lambda **kw: cancelled.append(kw))

        grid.visible[4, 4, 2] = True
        bs._check_pending_digs()

        assert len(bs.pending_digs) == 0
        assert len(bs.dig_queue) == 0
        assert len(cancelled) == 1

    def test_pending_stays_pending_if_still_invisible(self):
        """Blocks that are still invisible stay in pending_digs."""
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        bs._check_pending_digs()
        assert len(bs.pending_digs) == 1

    def test_claimed_territory_changed_triggers_check(self):
        """The 'claimed_territory_changed' event triggers _check_pending_digs."""
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        # Make visible before firing event
        grid.visible[4, 4, 2] = True
        bus.publish("claimed_territory_changed")
        assert len(bs.pending_digs) == 0
        assert len(bs.dig_queue) == 1


# ══════════════════════════════════════════════════════════════════════
# Cancel dig
# ══════════════════════════════════════════════════════════════════════


class TestCancelDig:
    """Click-to-cancel: clicking a block being dug cancels it fully."""

    def _setup(self):
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=4)
        grid.grid[:] = VOXEL_STONE
        grid.visible[:] = True
        bs = BuildSystem(bus, grid)
        return bus, grid, bs

    def test_cancel_queued_dig(self):
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        assert bs.cancel_dig(4, 4, 2) is True
        assert not bs.is_being_dug(4, 4, 2)

    def test_cancel_active_dig(self):
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)
        bus.publish("tick", tick=1)  # promotes to active
        assert len(bs.active_digs) == 1

        assert bs.cancel_dig(4, 4, 2) is True
        assert len(bs.active_digs) == 0
        assert not bs.is_being_dug(4, 4, 2)

    def test_cancel_pending_dig(self):
        bus, grid, bs = self._setup()
        grid.visible[4, 4, 2] = False  # make invisible → goes to pending
        bs.queue_dig(4, 4, 2)
        assert len(bs.pending_digs) == 1

        assert bs.cancel_dig(4, 4, 2) is True
        assert len(bs.pending_digs) == 0

    def test_cancel_publishes_event(self):
        bus, grid, bs = self._setup()
        bs.queue_dig(4, 4, 2)

        events = []
        bus.subscribe("dig_cancelled", lambda **kw: events.append(kw))
        bs.cancel_dig(4, 4, 2)

        assert len(events) == 1
        assert events[0]["x"] == 4

    def test_cancel_nonexistent_returns_false(self):
        bus, grid, bs = self._setup()
        assert bs.cancel_dig(4, 4, 2) is False

    def test_left_click_toggles_dig(self):
        """Left-clicking a block being dug should cancel it."""
        bus, grid, bs = self._setup()
        bus.publish("voxel_left_clicked", x=4, y=4, z=2, mode="dig")
        assert bs.is_being_dug(4, 4, 2) is True

        bus.publish("voxel_left_clicked", x=4, y=4, z=2, mode="dig")
        assert bs.is_being_dug(4, 4, 2) is False

    def test_block_not_loose_after_cancel(self):
        """Cancelled active dig does not make block loose."""
        bus, grid, bs = self._setup()
        grid.grid[4, 4, 2] = VOXEL_DIRT
        bs.queue_dig(4, 4, 2)
        # Simulate some ticks
        for i in range(1, 11):
            bus.publish("tick", tick=i)
        # Partially dug — cancel
        bs.cancel_dig(4, 4, 2)
        assert not grid.is_loose(4, 4, 2)


# ══════════════════════════════════════════════════════════════════════
# Multiple concurrent digs
# ══════════════════════════════════════════════════════════════════════


class TestMultipleDigs:
    """Multiple blocks can be dug simultaneously."""

    def test_concurrent_limit_respected(self):
        """Only MAX_CONCURRENT_DIGS blocks are promoted to active."""
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=4)
        grid.grid[:] = VOXEL_DIRT
        grid.visible[:] = True
        bs = BuildSystem(bus, grid)

        # Queue 10 digs (default limit is 5)
        for i in range(10):
            assert bs.queue_dig(i % 8, i // 8, 0) is True

        bus.publish("tick", tick=1)
        assert len(bs.active_digs) == _cfg.MAX_CONCURRENT_DIGS
        assert len(bs.dig_queue) == 10 - _cfg.MAX_CONCURRENT_DIGS

    def test_many_digs_with_high_limit(self):
        """With a high limit, all queued digs become active."""
        old = _cfg.MAX_CONCURRENT_DIGS
        _cfg.MAX_CONCURRENT_DIGS = 999
        try:
            bus = EventBus()
            grid = VoxelGrid(width=8, depth=8, height=4)
            grid.grid[:] = VOXEL_DIRT
            grid.visible[:] = True
            bs = BuildSystem(bus, grid)

            for i in range(10):
                assert bs.queue_dig(i % 8, i // 8, 0) is True

            bus.publish("tick", tick=1)
            assert len(bs.active_digs) == 10
        finally:
            _cfg.MAX_CONCURRENT_DIGS = old


# ══════════════════════════════════════════════════════════════════════
# Ore X-ray visibility
# ══════════════════════════════════════════════════════════════════════


class TestOreXray:
    """Ores within PLAYER_XRAY_RANGE of visible blocks become visible."""

    def _setup(self):
        bus = EventBus()
        grid = VoxelGrid(width=10, depth=10, height=5)
        grid.grid[:] = VOXEL_STONE
        return bus, grid

    def test_ore_visible_through_stone(self):
        """Iron ore 2 blocks from a visible block becomes visible."""
        import dungeon_builder.config as _cfg
        old_range = _cfg.PLAYER_XRAY_RANGE
        _cfg.PLAYER_XRAY_RANGE = 3
        try:
            bus, grid = self._setup()
            # Set up core + claimed territory
            grid.grid[5, 5, 2] = VOXEL_CORE
            grid.grid[5, 5, 1] = VOXEL_AIR  # above core
            grid.grid[5, 5, 3] = VOXEL_STONE
            # Place ore 2 blocks away through solid stone
            grid.grid[7, 5, 2] = VOXEL_IRON_ORE  # 2 blocks from border

            ct = ClaimedTerritorySystem(bus, grid, 5, 5, 2)
            ct.recompute()

            # The ore should be visible via x-ray dilation
            assert bool(grid.visible[7, 5, 2]) is True
        finally:
            _cfg.PLAYER_XRAY_RANGE = old_range

    def test_non_ore_not_revealed_by_xray(self):
        """Regular stone blocks are NOT revealed by x-ray."""
        import dungeon_builder.config as _cfg
        old_range = _cfg.PLAYER_XRAY_RANGE
        _cfg.PLAYER_XRAY_RANGE = 3
        try:
            bus, grid = self._setup()
            grid.grid[5, 5, 2] = VOXEL_CORE
            grid.grid[5, 5, 1] = VOXEL_AIR
            # Stone at distance 2 — NOT an ore type
            grid.grid[7, 5, 2] = VOXEL_STONE

            ct = ClaimedTerritorySystem(bus, grid, 5, 5, 2)
            ct.recompute()

            # Regular stone at distance 2 should NOT be visible
            # (only the immediate neighbors of claimed air are visible)
            if not grid.claimed[6, 5, 2]:
                assert bool(grid.visible[7, 5, 2]) is False
        finally:
            _cfg.PLAYER_XRAY_RANGE = old_range

    def test_ore_beyond_range_not_visible(self):
        """Ore too far from visible blocks is NOT revealed."""
        import dungeon_builder.config as _cfg
        old_range = _cfg.PLAYER_XRAY_RANGE
        _cfg.PLAYER_XRAY_RANGE = 2
        try:
            bus, grid = self._setup()
            grid.grid[5, 5, 2] = VOXEL_CORE
            grid.grid[5, 5, 1] = VOXEL_AIR
            # Ore at distance 4 from nearest visible block
            grid.grid[9, 5, 2] = VOXEL_IRON_ORE

            ct = ClaimedTerritorySystem(bus, grid, 5, 5, 2)
            ct.recompute()

            # Beyond x-ray range — should NOT be visible
            assert bool(grid.visible[9, 5, 2]) is False
        finally:
            _cfg.PLAYER_XRAY_RANGE = old_range

    def test_xray_range_zero_disables(self):
        """Setting PLAYER_XRAY_RANGE=0 disables ore x-ray."""
        import dungeon_builder.config as _cfg
        old_range = _cfg.PLAYER_XRAY_RANGE
        _cfg.PLAYER_XRAY_RANGE = 0
        try:
            bus, grid = self._setup()
            grid.grid[5, 5, 2] = VOXEL_CORE
            grid.grid[5, 5, 1] = VOXEL_AIR
            grid.grid[7, 5, 2] = VOXEL_IRON_ORE

            ct = ClaimedTerritorySystem(bus, grid, 5, 5, 2)
            ct.recompute()

            # Should NOT be visible with range=0
            assert bool(grid.visible[7, 5, 2]) is False
        finally:
            _cfg.PLAYER_XRAY_RANGE = old_range

    def test_mana_crystal_visible_through_stone(self):
        """Mana crystal (in XRAY_VISIBLE_TYPES) is revealed through stone."""
        import dungeon_builder.config as _cfg
        old_range = _cfg.PLAYER_XRAY_RANGE
        _cfg.PLAYER_XRAY_RANGE = 3
        try:
            bus, grid = self._setup()
            grid.grid[5, 5, 2] = VOXEL_CORE
            grid.grid[5, 5, 1] = VOXEL_AIR
            grid.grid[7, 5, 2] = VOXEL_MANA_CRYSTAL

            ct = ClaimedTerritorySystem(bus, grid, 5, 5, 2)
            ct.recompute()

            assert bool(grid.visible[7, 5, 2]) is True
        finally:
            _cfg.PLAYER_XRAY_RANGE = old_range


# ══════════════════════════════════════════════════════════════════════
# Build system: dig_complete triggers pending check
# ══════════════════════════════════════════════════════════════════════


class TestDigCompleteTriggersPendingCheck:
    """When territory changes after a dig, pending digs get promoted."""

    def test_territory_changed_triggers_pending_check(self):
        """claimed_territory_changed promotes pending digs to dig_queue."""
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=4)
        grid.grid[:] = VOXEL_STONE
        bs = BuildSystem(bus, grid)

        # Add a pending dig
        bs.queue_dig(4, 4, 2)
        assert len(bs.pending_digs) == 1

        # Make it visible and simulate territory recompute
        grid.visible[4, 4, 2] = True
        bus.publish("claimed_territory_changed")

        # The pending dig should have been promoted
        assert len(bs.pending_digs) == 0
        assert len(bs.dig_queue) == 1

    def test_dig_complete_alone_does_not_check_pending(self):
        """dig_complete alone no longer triggers pending check (perf fix)."""
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=4)
        grid.grid[:] = VOXEL_STONE
        bs = BuildSystem(bus, grid)

        bs.queue_dig(4, 4, 2)
        assert len(bs.pending_digs) == 1

        # Make visible but only fire dig_complete (not territory_changed)
        grid.visible[4, 4, 2] = True
        bus.publish("dig_complete", x=0, y=0, z=0)

        # Should NOT be promoted — pending check is on territory_changed
        assert len(bs.pending_digs) == 1


# ===========================================================================
# Dig queue feedback (from test_rendering_fixes.py)
# ===========================================================================


class TestDigQueueFeedback:
    """Pending digs on non-visible blocks give visual feedback."""

    def test_pending_dig_publishes_confirmation_message(self):
        """Queueing a dig on an invisible block should emit error_message."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[3, 3, 5] = VOXEL_STONE
        # Block is not visible — no claimed territory around it
        assert not grid.is_visible(3, 3, 5)

        messages = []
        eb.subscribe("error_message", lambda **kw: messages.append(kw))

        bs = BuildSystem(eb, grid)
        result = bs.queue_dig(3, 3, 5)
        assert result is True
        assert len(messages) == 1
        assert "queued" in messages[0]["text"].lower()

    def test_pending_dig_publishes_dig_pending_event(self):
        """Queueing on invisible block should emit dig_pending event."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[3, 3, 5] = VOXEL_STONE

        pending_events = []
        eb.subscribe("dig_pending", lambda **kw: pending_events.append(kw))

        bs = BuildSystem(eb, grid)
        bs.queue_dig(3, 3, 5)
        assert len(pending_events) == 1
        assert pending_events[0]["x"] == 3
        assert pending_events[0]["z"] == 5

    def test_pending_dig_tracked_in_pending_list(self):
        """Invisible-block dig should be in pending_digs, not dig_queue."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[3, 3, 5] = VOXEL_STONE

        bs = BuildSystem(eb, grid)
        bs.queue_dig(3, 3, 5)
        assert bs.is_pending_dig(3, 3, 5)
        assert len(bs.dig_queue) == 0  # Not in active queue

    def test_pending_dig_no_double_queue(self):
        """Can't queue same pending dig twice."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[3, 3, 5] = VOXEL_STONE

        bs = BuildSystem(eb, grid)
        assert bs.queue_dig(3, 3, 5) is True
        assert bs.queue_dig(3, 3, 5) is False  # Already pending

    def test_camera_pending_dig_targets_z_plus_1(self):
        """Camera should target z+1 (solid below) when clicking air above non-visible."""
        from dungeon_builder.rendering.camera import CameraController
        source = inspect.getsource(CameraController._on_left_click)
        # Should contain "target_z = vz + 1"
        assert "target_z" in source
        assert "vz + 1" in source

    def test_hud_error_message_accepts_color(self):
        """HUD._on_error_message should accept optional color kwarg."""
        from dungeon_builder.ui.hud import HUD
        source = inspect.getsource(HUD._on_error_message)
        assert "color" in source
