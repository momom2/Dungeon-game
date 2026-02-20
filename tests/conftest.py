"""Shared test fixtures."""

import pytest
import dungeon_builder.config as _cfg
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.config import VOXEL_AIR, VOXEL_STONE


@pytest.fixture(autouse=True)
def _disable_dev_mode():
    """Ensure tests run in normal mode (DEV_MODE=False) by default.

    Tests that need dev mode can set ``_cfg.DEV_MODE = True`` explicitly.
    Restores the original value after each test.
    """
    original = _cfg.DEV_MODE
    _cfg.DEV_MODE = False
    yield
    _cfg.DEV_MODE = original


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def small_grid():
    """A small 16x16x5 grid for fast tests."""
    grid = VoxelGrid(width=16, depth=16, height=5)
    # Fill with stone, surface is air
    grid.grid[:, :, 0] = VOXEL_AIR
    grid.grid[:, :, 1:] = VOXEL_STONE
    return grid


@pytest.fixture
def stone_grid_8():
    """An 8x8x8 grid filled with stone, visible=True everywhere."""
    grid = VoxelGrid(width=8, depth=8, height=8)
    grid.grid[:] = VOXEL_STONE
    grid.visible[:] = True
    return grid
