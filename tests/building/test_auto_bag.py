"""Tests for auto-bag: dug blocks go directly into the player's bag."""

import inspect

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.game_state import GameState
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.building.build_system import BuildSystem
from dungeon_builder.building.move_system import MoveSystem
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DIRT,
    VOXEL_BEDROCK,
    DEFAULT_SEED,
    DIG_DURATION,
)
import dungeon_builder.config as _cfg


def _make_auto_bag_env(vtype=VOXEL_DIRT, auto_bag=True):
    """Create event bus, grid, game_state, build_system, move_system for auto-bag tests."""
    bus = EventBus()
    grid = VoxelGrid(width=8, depth=8, height=4)
    grid.grid[2, 2, 1] = vtype
    grid.visible[:] = True

    gs = GameState(DEFAULT_SEED)
    gs.event_bus = bus
    gs.voxel_grid = grid

    ms = MoveSystem(bus, grid, gs)
    gs.move_system = ms

    bs = BuildSystem(bus, grid, game_state=gs)
    gs.build_system = bs

    old_val = _cfg.AUTO_BAG_DIG
    _cfg.AUTO_BAG_DIG = auto_bag

    return bus, grid, gs, bs, ms, old_val


def _complete_dig(bus, vtype=VOXEL_DIRT):
    """Simulate enough ticks to complete a dig on the given vtype."""
    duration = DIG_DURATION.get(vtype, 40)
    for i in range(1, duration + 1):
        bus.publish("tick", tick=i)


class TestAutoBag:
    """Auto-bag picks up dug material automatically."""

    def test_auto_bag_picks_up_on_dig_complete(self):
        """Block should be AIR and material in bag after dig completes."""
        bus, grid, gs, bs, ms, old = _make_auto_bag_env()
        try:
            bs.queue_dig(2, 2, 1)
            _complete_dig(bus, VOXEL_DIRT)

            # Block should be air (picked up), material in bag
            assert grid.get(2, 2, 1) == VOXEL_AIR
            assert ms.get_count(VOXEL_DIRT) == 1
        finally:
            _cfg.AUTO_BAG_DIG = old

    def test_auto_bag_disabled_leaves_block_loose(self):
        """With AUTO_BAG_DIG=False, block stays loose after dig."""
        bus, grid, gs, bs, ms, old = _make_auto_bag_env(auto_bag=False)
        try:
            bs.queue_dig(2, 2, 1)
            _complete_dig(bus, VOXEL_DIRT)

            # Block is still there, just loose
            assert grid.get(2, 2, 1) == VOXEL_DIRT
            assert grid.is_loose(2, 2, 1)
            assert ms.get_count(VOXEL_DIRT) == 0
        finally:
            _cfg.AUTO_BAG_DIG = old

    def test_auto_bag_without_game_state_no_crash(self):
        """BuildSystem without game_state doesn't crash on dig complete."""
        bus = EventBus()
        grid = VoxelGrid(width=4, depth=4, height=4)
        grid.grid[1, 1, 1] = VOXEL_DIRT
        grid.visible[:] = True
        bs = BuildSystem(bus, grid)  # No game_state

        bs.queue_dig(1, 1, 1)
        _complete_dig(bus, VOXEL_DIRT)

        # Block should be loose (not picked up, no crash)
        assert grid.get(1, 1, 1) == VOXEL_DIRT
        assert grid.is_loose(1, 1, 1)

    def test_auto_bag_captures_temperature(self):
        """Auto-bagged block carries its temperature."""
        bus, grid, gs, bs, ms, old = _make_auto_bag_env()
        try:
            grid.set_temperature(2, 2, 1, 100.0)
            bs.queue_dig(2, 2, 1)
            _complete_dig(bus, VOXEL_DIRT)

            assert ms.get_count(VOXEL_DIRT) == 1
            assert ms.held_temperatures.get(VOXEL_DIRT, 0.0) == pytest.approx(100.0)
        finally:
            _cfg.AUTO_BAG_DIG = old

    def test_auto_bag_publishes_material_picked_up(self):
        """Auto-bag triggers 'material_picked_up' event."""
        bus, grid, gs, bs, ms, old = _make_auto_bag_env()
        try:
            pickups = []
            bus.subscribe("material_picked_up", lambda **kw: pickups.append(kw))

            bs.queue_dig(2, 2, 1)
            _complete_dig(bus, VOXEL_DIRT)

            assert len(pickups) >= 1
        finally:
            _cfg.AUTO_BAG_DIG = old

    def test_auto_bag_source_references_config(self):
        """_on_dig_complete_auto_bag should check AUTO_BAG_DIG from config."""
        source = inspect.getsource(BuildSystem._on_dig_complete_auto_bag)
        assert "AUTO_BAG_DIG" in source

    def test_auto_bag_source_calls_pick_up(self):
        """_on_dig_complete_auto_bag should call move_system.pick_up."""
        source = inspect.getsource(BuildSystem._on_dig_complete_auto_bag)
        assert "pick_up" in source
