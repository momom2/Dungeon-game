"""Tests for drag-select dig areas: queue_dig_area and camera drag bindings."""

import pytest

import dungeon_builder.config as _cfg
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.game_state import GameState
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.building.build_system import BuildSystem
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DIRT,
    VOXEL_BEDROCK,
    VOXEL_CORE,
    VOXEL_WATER,
    DEFAULT_SEED,
    DIG_DURATION,
)
from dungeon_builder.building.move_system import MoveSystem


def _make_stone_grid(w=8, d=8, h=4):
    """Create grid filled with stone and fully visible."""
    bus = EventBus()
    grid = VoxelGrid(width=w, depth=d, height=h)
    grid.grid[:, :, :] = VOXEL_STONE
    grid.visible[:] = True
    gs = GameState(DEFAULT_SEED)
    gs.event_bus = bus
    bs = BuildSystem(bus, grid, game_state=gs)
    return bus, grid, bs


def _make_grid_with_move(w=8, d=8, h=4):
    """Create grid + MoveSystem for loose-block pick-up tests."""
    bus = EventBus()
    grid = VoxelGrid(width=w, depth=d, height=h)
    grid.grid[:, :, :] = VOXEL_STONE
    grid.visible[:] = True
    gs = GameState(DEFAULT_SEED)
    gs.event_bus = bus
    ms = MoveSystem(bus, grid, gs)
    gs.move_system = ms
    bs = BuildSystem(bus, grid, game_state=gs)
    return bus, grid, bs, ms


class TestQueueDigArea:
    """BuildSystem.queue_dig_area headless tests."""

    def test_3x3_area_queues_9_blocks(self):
        """A 3x3 area of stone should queue 9 blocks."""
        bus, grid, bs = _make_stone_grid()
        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 9

    def test_skips_air_blocks(self):
        """Air blocks in the selection area are skipped."""
        bus, grid, bs = _make_stone_grid()
        grid.grid[1, 1, 1] = VOXEL_AIR
        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 8  # 9 - 1 air

    def test_skips_bedrock(self):
        """Non-diggable blocks (bedrock) are skipped."""
        bus, grid, bs = _make_stone_grid()
        grid.grid[1, 1, 1] = VOXEL_BEDROCK
        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 8  # 9 - 1 bedrock

    def test_skips_already_queued(self):
        """Already-queued blocks are not double-counted."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig(1, 1, 1)  # Pre-queue one block
        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 8  # 9 - 1 already queued

    def test_skips_loose_blocks(self):
        """Loose blocks are skipped."""
        bus, grid, bs = _make_stone_grid()
        grid.set_loose(1, 1, 1, True)
        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 8  # 9 - 1 loose

    def test_3d_volume_2x2x3(self):
        """A 2x2x3 volume queues the correct number of blocks."""
        bus, grid, bs = _make_stone_grid()
        count = bs.queue_dig_area(0, 1, 0, 1, 0, 2)
        assert count == 12  # 2*2*3

    def test_feedback_message_published(self):
        """queue_dig_area publishes a feedback message with count."""
        bus, grid, bs = _make_stone_grid()
        messages = []
        bus.subscribe("error_message", lambda **kw: messages.append(kw))

        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        # Filter for area feedback (yellow color)
        area_msgs = [
            m for m in messages
            if "color" in m and m["color"] == (0.8, 0.8, 0.3, 1)
        ]
        assert len(area_msgs) == 1
        assert "9" in area_msgs[0]["text"]

    def test_drag_dig_area_event_triggers_queue(self):
        """Publishing 'drag_dig_area' event triggers queue_dig_area."""
        bus, grid, bs = _make_stone_grid()
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=1, y_min=0, y_max=1, z_min=1, z_max=1,
        )
        # 2x2 area = 4 blocks
        total = len(bs.dig_queue) + len(bs.active_digs)
        assert total == 4

    def test_empty_area_returns_zero(self):
        """An area with no diggable blocks returns 0 and no feedback."""
        bus, grid, bs = _make_stone_grid()
        # Make entire area air
        grid.grid[0:3, 0:3, 1] = VOXEL_AIR
        messages = []
        bus.subscribe("error_message", lambda **kw: messages.append(kw))

        count = bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 0
        # No area feedback message when count is 0
        area_msgs = [
            m for m in messages
            if "color" in m and m["color"] == (0.8, 0.8, 0.3, 1)
        ]
        assert len(area_msgs) == 0

    def test_single_block_area(self):
        """A 1x1x1 area queues exactly 1 block."""
        bus, grid, bs = _make_stone_grid()
        count = bs.queue_dig_area(3, 3, 3, 3, 2, 2)
        assert count == 1


class TestBatchEvents:
    """Batch operations publish batch events, not per-voxel events."""

    def test_queue_area_publishes_batch_event(self):
        """queue_dig_area publishes 'dig_batch_queued' with positions list."""
        bus, grid, bs = _make_stone_grid()
        batches = []
        bus.subscribe("dig_batch_queued", lambda **kw: batches.append(kw))
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert len(batches) == 1
        assert len(batches[0]["positions"]) == 9

    def test_queue_area_does_not_publish_per_voxel_events(self):
        """queue_dig_area should NOT publish per-voxel 'dig_queued' events."""
        bus, grid, bs = _make_stone_grid()
        per_voxel = []
        bus.subscribe("dig_queued", lambda **kw: per_voxel.append(kw))
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert len(per_voxel) == 0

    def test_cancel_area_publishes_batch_event(self):
        """cancel_dig_area publishes 'dig_batch_cancelled' with positions."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig_area(0, 1, 0, 1, 1, 1)
        batches = []
        bus.subscribe("dig_batch_cancelled", lambda **kw: batches.append(kw))
        bs.cancel_dig_area(0, 1, 0, 1, 1, 1)
        assert len(batches) == 1
        assert len(batches[0]["positions"]) == 4

    def test_cancel_area_does_not_publish_per_voxel_events(self):
        """cancel_dig_area should NOT publish per-voxel 'dig_cancelled'."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig_area(0, 1, 0, 1, 1, 1)
        per_voxel = []
        bus.subscribe("dig_cancelled", lambda **kw: per_voxel.append(kw))
        bs.cancel_dig_area(0, 1, 0, 1, 1, 1)
        assert len(per_voxel) == 0

    def test_queue_area_pending_publishes_batch_pending(self):
        """Invisible blocks in queue_dig_area publish 'dig_batch_pending'."""
        bus, grid, bs = _make_stone_grid()
        # Make some blocks invisible
        grid.visible[0:2, 0:2, 1] = False
        batches_q = []
        batches_p = []
        bus.subscribe("dig_batch_queued", lambda **kw: batches_q.append(kw))
        bus.subscribe("dig_batch_pending", lambda **kw: batches_p.append(kw))
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        # 4 invisible → pending, 5 visible → queued
        assert len(batches_q) == 1
        assert len(batches_q[0]["positions"]) == 5
        assert len(batches_p) == 1
        assert len(batches_p[0]["positions"]) == 4

    def test_single_queue_dig_still_publishes_per_voxel(self):
        """Single queue_dig() still publishes per-voxel event (not batch)."""
        bus, grid, bs = _make_stone_grid()
        per_voxel = []
        bus.subscribe("dig_queued", lambda **kw: per_voxel.append(kw))
        bs.queue_dig(1, 1, 1)
        assert len(per_voxel) == 1


class TestCancelDigArea:
    """BuildSystem.cancel_dig_area headless tests."""

    def test_cancel_3x3_area(self):
        """Cancelling a 3x3 area of queued digs removes all 9."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        count = bs.cancel_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 9
        assert len(bs.dig_queue) == 0

    def test_cancel_empty_area_returns_zero(self):
        """Cancelling an area with no queued digs returns 0."""
        bus, grid, bs = _make_stone_grid()
        count = bs.cancel_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 0

    def test_cancel_partial_overlap(self):
        """Cancelling a larger area only cancels blocks that were queued."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig_area(1, 2, 1, 2, 1, 1)  # Queue 4 blocks
        count = bs.cancel_dig_area(0, 3, 0, 3, 1, 1)  # Cancel wider area
        assert count == 4

    def test_cancel_feedback_message(self):
        """cancel_dig_area publishes a feedback message."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig_area(0, 1, 0, 1, 1, 1)
        messages = []
        bus.subscribe("error_message", lambda **kw: messages.append(kw))
        bs.cancel_dig_area(0, 1, 0, 1, 1, 1)
        cancel_msgs = [
            m for m in messages
            if "color" in m and m["color"] == (0.7, 0.5, 0.3, 1)
        ]
        assert len(cancel_msgs) == 1
        assert "Cancelled" in cancel_msgs[0]["text"]


class TestToggleDigArea:
    """BuildSystem.toggle_dig_area headless tests."""

    def test_toggle_untagged_area_queues_all(self):
        """Toggling an area with no digs queues all diggable blocks."""
        bus, grid, bs = _make_stone_grid()
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 9
        total = len(bs.dig_queue) + len(bs.active_digs)
        assert total == 9

    def test_toggle_fully_tagged_area_cancels_all(self):
        """Toggling an area where ALL blocks are queued cancels them."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert len(bs.dig_queue) == 9
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 9
        assert len(bs.dig_queue) == 0

    def test_toggle_mixed_area_queues_unqueued(self):
        """Toggling a mixed area (some queued, some not) queues the rest."""
        bus, grid, bs = _make_stone_grid()
        bs.queue_dig(0, 0, 1)
        bs.queue_dig(1, 0, 1)
        # 2 of 9 are queued, 7 are not → should queue the 7
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 7
        total = len(bs.dig_queue) + len(bs.active_digs)
        assert total == 9  # all 9 queued now

    def test_toggle_area_with_only_air_returns_zero(self):
        """Toggling an area of only air returns 0."""
        bus, grid, bs = _make_stone_grid()
        grid.grid[0:3, 0:3, 1] = VOXEL_AIR
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 0

    def test_toggle_area_ignores_bedrock_for_all_queued_check(self):
        """Bedrock doesn't count as 'diggable' for the all-queued check.

        If remaining diggable blocks are all queued, toggle cancels.
        """
        bus, grid, bs = _make_stone_grid()
        grid.grid[1, 1, 1] = VOXEL_BEDROCK
        # Queue 8 diggable blocks (9 - 1 bedrock)
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)
        assert len(bs.dig_queue) == 8
        # Now toggle — all diggable are queued → cancel
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 8
        assert len(bs.dig_queue) == 0

    def test_drag_event_uses_toggle(self):
        """'drag_dig_area' event uses toggle_dig_area, not plain queue."""
        bus, grid, bs = _make_stone_grid()
        # First drag → queue all
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=1, y_min=0, y_max=1, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) == 4
        # Second drag over same area → cancel all
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=1, y_min=0, y_max=1, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) == 0

    def test_drag_dig_area_delegates_to_toggle(self):
        """'drag_dig_area' event uses toggle_dig_area (queue then cancel)."""
        bus, grid, bs = _make_stone_grid()
        # First drag → queues
        bus.publish(
            "drag_dig_area",
            x_min=3, x_max=4, y_min=3, y_max=4, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) == 4
        # Second drag over same area → cancels (toggle behavior)
        bus.publish(
            "drag_dig_area",
            x_min=3, x_max=4, y_min=3, y_max=4, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) == 0


class TestCameraDragBindings:
    """Interface checks: CameraController exposes drag-select API."""

    def test_camera_has_mouse_handlers(self):
        """Camera must have left-down and left-up mouse handlers."""
        from dungeon_builder.rendering.camera import CameraController
        assert hasattr(CameraController, "_on_left_down")
        assert hasattr(CameraController, "_on_left_up")

    def test_camera_has_bind_controls(self):
        """Camera must have _bind_controls for input setup."""
        from dungeon_builder.rendering.camera import CameraController
        assert hasattr(CameraController, "_bind_controls")

    def test_camera_has_input_task(self):
        """Camera must have _input_task for per-frame drag tracking."""
        from dungeon_builder.rendering.camera import CameraController
        assert hasattr(CameraController, "_input_task")
        assert callable(getattr(CameraController, "_input_task"))

    def test_drag_select_threshold_configured(self):
        """DRAG_SELECT_THRESHOLD must be defined and positive in config."""
        from dungeon_builder.config import DRAG_SELECT_THRESHOLD
        assert DRAG_SELECT_THRESHOLD > 0



class TestEffectsDragPreview:
    """Interface checks: EffectsRenderer exposes drag-preview API."""

    def test_effects_has_drag_preview_handler(self):
        """EffectsRenderer must have _on_drag_preview method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_drag_preview")
        assert callable(getattr(EffectsRenderer, "_on_drag_preview"))

    def test_effects_has_drag_cleared_handler(self):
        """EffectsRenderer must have _on_drag_cleared method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_drag_cleared")
        assert callable(getattr(EffectsRenderer, "_on_drag_cleared"))

    def test_effects_has_init_drag_box(self):
        """EffectsRenderer must have _init_drag_box setup method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_init_drag_box")


class TestAirBlockFiltering:
    """Bug fix: drag-select should ignore air blocks."""

    def test_queue_area_skips_invisible_air(self):
        """Invisible air blocks should NOT be added to pending_digs."""
        bus, grid, bs = _make_stone_grid()
        # Make some blocks air AND invisible
        grid.grid[0, 0, 1] = VOXEL_AIR
        grid.grid[1, 0, 1] = VOXEL_AIR
        grid.visible[0:2, 0, 1] = False  # invisible air
        count = bs.queue_dig_area(0, 2, 0, 0, 1, 1)
        # Only stone block at (2,0,1) should be queued (visible stone)
        assert count == 1
        assert len(bs.pending_digs) == 0

    def test_queue_area_skips_invisible_water(self):
        """Invisible water blocks should NOT be added to pending_digs."""
        bus, grid, bs = _make_stone_grid()
        grid.grid[0, 0, 1] = VOXEL_WATER
        grid.visible[0, 0, 1] = False  # invisible water
        count = bs.queue_dig_area(0, 0, 0, 0, 1, 1)
        assert count == 0
        assert len(bs.pending_digs) == 0

    def test_queue_dig_single_rejects_air(self):
        """Single queue_dig() on air should return False."""
        bus, grid, bs = _make_stone_grid()
        grid.grid[1, 1, 1] = VOXEL_AIR
        result = bs.queue_dig(1, 1, 1)
        assert result is False
        assert len(bs.pending_digs) == 0

    def test_queue_dig_single_rejects_invisible_air(self):
        """Single queue_dig() on invisible air should return False."""
        bus, grid, bs = _make_stone_grid()
        grid.grid[1, 1, 1] = VOXEL_AIR
        grid.visible[1, 1, 1] = False
        result = bs.queue_dig(1, 1, 1)
        assert result is False
        assert len(bs.pending_digs) == 0

    def test_invisible_stone_still_goes_pending(self):
        """Invisible stone blocks should still be added to pending_digs."""
        bus, grid, bs = _make_stone_grid()
        grid.visible[0, 0, 1] = False  # invisible stone
        count = bs.queue_dig_area(0, 0, 0, 0, 1, 1)
        assert count == 1
        assert len(bs.pending_digs) == 1

    def test_toggle_area_ignores_air_for_classification(self):
        """Air blocks should not affect toggle all-queued classification."""
        bus, grid, bs = _make_stone_grid()
        # Mix of stone (queued) and air
        grid.grid[1, 1, 1] = VOXEL_AIR
        bs.queue_dig_area(0, 2, 0, 2, 1, 1)  # Queue 8 stone blocks
        assert len(bs.dig_queue) == 8
        # Toggle — all stone is queued, air is ignored → cancel
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 8
        assert len(bs.dig_queue) == 0


class TestDetaggingWithTicks:
    """Bug fix: detagging via drag-select should work even after ticks."""

    def test_detag_after_ticks_promote_to_active(self):
        """Detagging works after ticks promote blocks to active_digs."""
        _cfg.MAX_CONCURRENT_DIGS = 999  # Allow all 9 to become active
        bus, grid, bs = _make_stone_grid()
        # First drag → queue
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=2, y_min=0, y_max=2, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) + len(bs.active_digs) == 9
        # Run ticks to promote
        for i in range(3):
            bus.publish("tick", tick=i)
        assert len(bs.active_digs) == 9
        assert len(bs.dig_queue) == 0
        # Second drag → cancel all (even active)
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=2, y_min=0, y_max=2, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) == 0
        assert len(bs.active_digs) == 0

    def test_detag_partial_completion(self):
        """Detagging works when some blocks have completed (now loose)."""
        bus, grid, bs = _make_stone_grid()
        # Queue 4 blocks
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=1, y_min=0, y_max=1, z_min=1, z_max=1,
        )
        assert len(bs.dig_queue) == 4
        # Complete one block manually (mark loose, remove from queue)
        grid.set_loose(0, 0, 1, True)
        bs.dig_queue = [j for j in bs.dig_queue if not (j.x == 0 and j.y == 0 and j.z == 1)]
        # Remaining 3 are queued, 1 is loose
        assert len(bs.dig_queue) == 3
        # Toggle → 3 remaining diggable are all queued → cancel
        count = bs.toggle_dig_area(0, 1, 0, 1, 1, 1)
        assert count == 3
        assert len(bs.dig_queue) == 0

    def test_detag_with_pending_digs(self):
        """Detagging works for areas with pending (invisible) blocks."""
        bus, grid, bs = _make_stone_grid()
        # Make some blocks invisible
        grid.visible[0, 0, 1] = False
        grid.visible[1, 0, 1] = False
        # Queue area: 2 pending + 2 visible queued
        count = bs.queue_dig_area(0, 1, 0, 1, 1, 1)
        assert count == 4
        assert len(bs.pending_digs) == 2
        assert len(bs.dig_queue) == 2
        # Toggle same area → all diggable are in list → cancel
        count = bs.toggle_dig_area(0, 1, 0, 1, 1, 1)
        assert count == 4
        assert len(bs.pending_digs) == 0
        assert len(bs.dig_queue) == 0


class TestZLevelCapture:
    """Bug fix: drag z-level captured at press time, not threshold time."""

    def test_camera_has_on_left_down(self):
        """_on_left_down must exist — z-capture happens there, not in _input_task."""
        from dungeon_builder.rendering.camera import CameraController
        assert hasattr(CameraController, "_on_left_down")
        assert callable(getattr(CameraController, "_on_left_down"))


class TestDragSelectLooseBlocks:
    """Drag-select over loose blocks should pick them up (bag them)."""

    def test_drag_loose_blocks_are_bagged(self):
        """Loose blocks in a drag-select area are picked up."""
        bus, grid, bs, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        grid.set_loose(1, 0, 1, True)
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=1, y_min=0, y_max=0, z_min=1, z_max=1,
        )
        # Both loose blocks should be in the bag
        assert ms.get_count(VOXEL_STONE) == 2
        # Blocks should now be air
        assert grid.get(0, 0, 1) == VOXEL_AIR
        assert grid.get(1, 0, 1) == VOXEL_AIR

    def test_drag_mixed_loose_and_solid_queues_and_bags(self):
        """Drag area with mix of loose and solid: bags loose, queues solid."""
        bus, grid, bs, ms = _make_grid_with_move()
        # 2 loose blocks + 2 solid blocks
        grid.set_loose(0, 0, 1, True)
        grid.set_loose(1, 0, 1, True)
        bus.publish(
            "drag_dig_area",
            x_min=0, x_max=1, y_min=0, y_max=1, z_min=1, z_max=1,
        )
        # Loose blocks picked up
        assert ms.get_count(VOXEL_STONE) == 2
        # Solid blocks queued for digging
        total_queued = len(bs.dig_queue) + len(bs.active_digs)
        assert total_queued == 2

    def test_drag_all_loose_no_solid(self):
        """Area with only loose blocks: all bagged, nothing queued."""
        bus, grid, bs, ms = _make_grid_with_move()
        for x in range(3):
            for y in range(3):
                grid.set_loose(x, y, 1, True)
        count = bs.toggle_dig_area(0, 2, 0, 2, 1, 1)
        assert count == 9  # 9 loose blocks picked up
        assert ms.get_count(VOXEL_STONE) == 9
        assert len(bs.dig_queue) == 0

    def test_drag_loose_publishes_feedback(self):
        """Picking up loose blocks via drag publishes a feedback message."""
        bus, grid, bs, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        messages = []
        bus.subscribe("error_message", lambda **kw: messages.append(kw))
        bs.toggle_dig_area(0, 0, 0, 0, 1, 1)
        green_msgs = [
            m for m in messages
            if "color" in m and m["color"] == (0.3, 0.8, 0.3, 1)
        ]
        assert len(green_msgs) == 1
        assert "Picked up" in green_msgs[0]["text"]

    def test_drag_loose_plus_detag(self):
        """Loose blocks are picked up even when detagging queued blocks."""
        bus, grid, bs, ms = _make_grid_with_move()
        # Queue ALL solid blocks in the area first
        bs.queue_dig(0, 0, 1)  # will become loose below
        bs.queue_dig(1, 0, 1)
        bs.queue_dig(0, 1, 1)
        bs.queue_dig(1, 1, 1)
        assert len(bs.dig_queue) == 4
        # Make one block loose (simulating completed dig)
        grid.set_loose(0, 0, 1, True)
        # Cancel the now-loose block's dig
        bs.cancel_dig(0, 0, 1)
        # Now: 3 queued solid + 1 loose
        # Toggle area: all solid diggable ARE queued → cancel; loose → bag
        count = bs.toggle_dig_area(0, 1, 0, 1, 1, 1)
        assert ms.get_count(VOXEL_STONE) == 1  # 1 loose picked up
        assert len(bs.dig_queue) == 0  # 3 queued cancelled
        assert count == 4  # 1 picked up + 3 cancelled

    def test_no_move_system_skips_pickup(self):
        """Without MoveSystem, loose blocks are silently skipped."""
        bus, grid, bs = _make_stone_grid()
        grid.set_loose(0, 0, 1, True)
        count = bs.toggle_dig_area(0, 0, 0, 0, 1, 1)
        # No move system → no pickup, and the only block is loose → no diggable
        assert count == 0


class TestBatchAutoBag:
    """Batch auto-bag on dig completion avoids per-voxel events."""

    def test_batch_auto_bag_picks_up_all(self):
        """When multiple digs complete at once, all are batch-bagged."""
        bus, grid, bs, ms = _make_grid_with_move()
        # Queue 4 blocks with short duration
        for x in range(2):
            for y in range(2):
                bs.queue_dig(x, y, 1)
        # Fast-forward: promote to active, then complete
        bus.publish("tick", tick=0)  # promote to active
        # Set ticks_remaining to 1 so next tick completes all
        for job in bs.active_digs:
            job.ticks_remaining = 1
        bus.publish("tick", tick=1)  # complete all
        # All 4 blocks should be in the bag
        assert ms.get_count(VOXEL_STONE) == 4
        # All 4 positions should be air
        for x in range(2):
            for y in range(2):
                assert grid.get(x, y, 1) == VOXEL_AIR

    def test_batch_auto_bag_single_event(self):
        """Batch auto-bag publishes only one material_picked_up event."""
        bus, grid, bs, ms = _make_grid_with_move()
        # Queue 4 blocks
        for x in range(2):
            for y in range(2):
                bs.queue_dig(x, y, 1)
        bus.publish("tick", tick=0)  # promote
        for job in bs.active_digs:
            job.ticks_remaining = 1
        events = []
        bus.subscribe("material_picked_up", lambda **kw: events.append(kw))
        bus.publish("tick", tick=1)  # complete all
        # Should get exactly 1 material_picked_up event (from batch)
        assert len(events) == 1

    def test_batch_auto_bag_no_per_voxel_changed(self):
        """Batch auto-bag does not publish per-voxel voxel_changed events."""
        bus, grid, bs, ms = _make_grid_with_move()
        for x in range(2):
            for y in range(2):
                bs.queue_dig(x, y, 1)
        bus.publish("tick", tick=0)
        for job in bs.active_digs:
            job.ticks_remaining = 1
        voxel_changes = []
        bus.subscribe("voxel_changed", lambda **kw: voxel_changes.append(kw))
        bus.publish("tick", tick=1)
        # Batch pick_up uses set() without event_bus → no voxel_changed
        assert len(voxel_changes) == 0

    def test_single_completion_still_uses_per_voxel(self):
        """A single dig completion still uses per-voxel pick_up."""
        bus, grid, bs, ms = _make_grid_with_move()
        bs.queue_dig(0, 0, 1)
        bus.publish("tick", tick=0)
        for job in bs.active_digs:
            job.ticks_remaining = 1
        voxel_changes = []
        bus.subscribe("voxel_changed", lambda **kw: voxel_changes.append(kw))
        bus.publish("tick", tick=1)
        # Single completion uses per-voxel pick_up → voxel_changed fires
        assert len(voxel_changes) == 1
        assert ms.get_count(VOXEL_STONE) == 1


class TestPickUpBatch:
    """MoveSystem.pick_up_batch unit tests."""

    def test_batch_picks_up_loose_blocks(self):
        """pick_up_batch picks up multiple loose blocks."""
        bus, grid, _, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        grid.set_loose(1, 0, 1, True)
        grid.set_loose(2, 0, 1, True)
        count = ms.pick_up_batch([(0, 0, 1), (1, 0, 1), (2, 0, 1)])
        assert count == 3
        assert ms.get_count(VOXEL_STONE) == 3

    def test_batch_skips_non_loose(self):
        """pick_up_batch skips blocks that are not loose."""
        bus, grid, _, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        # (1,0,1) is solid — should be skipped
        count = ms.pick_up_batch([(0, 0, 1), (1, 0, 1)])
        assert count == 1
        assert ms.get_count(VOXEL_STONE) == 1

    def test_batch_skips_air(self):
        """pick_up_batch skips air blocks."""
        bus, grid, _, ms = _make_grid_with_move()
        grid.grid[0, 0, 1] = VOXEL_AIR
        count = ms.pick_up_batch([(0, 0, 1)])
        assert count == 0

    def test_batch_publishes_single_event(self):
        """pick_up_batch publishes exactly one material_picked_up event."""
        bus, grid, _, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        grid.set_loose(1, 0, 1, True)
        events = []
        bus.subscribe("material_picked_up", lambda **kw: events.append(kw))
        ms.pick_up_batch([(0, 0, 1), (1, 0, 1)])
        assert len(events) == 1

    def test_batch_no_event_when_nothing_picked(self):
        """pick_up_batch publishes no event when nothing was picked up."""
        bus, grid, _, ms = _make_grid_with_move()
        events = []
        bus.subscribe("material_picked_up", lambda **kw: events.append(kw))
        ms.pick_up_batch([(0, 0, 1)])  # solid, not loose
        assert len(events) == 0

    def test_batch_sets_blocks_to_air(self):
        """pick_up_batch sets picked blocks to air."""
        bus, grid, _, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        grid.set_loose(1, 0, 1, True)
        ms.pick_up_batch([(0, 0, 1), (1, 0, 1)])
        assert grid.get(0, 0, 1) == VOXEL_AIR
        assert grid.get(1, 0, 1) == VOXEL_AIR

    def test_batch_accumulates_temperature(self):
        """pick_up_batch accumulates running average temperature."""
        bus, grid, _, ms = _make_grid_with_move()
        grid.set_loose(0, 0, 1, True)
        grid.set_loose(1, 0, 1, True)
        grid.set_temperature(0, 0, 1, 100.0)
        grid.set_temperature(1, 0, 1, 200.0)
        ms.pick_up_batch([(0, 0, 1), (1, 0, 1)])
        # Average of 100 and 200
        assert ms.held_temperatures[VOXEL_STONE] == pytest.approx(150.0)
