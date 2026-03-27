"""Tests for water/lava source and sink physics."""

import numpy as np
import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.physics.water import WaterPhysics
from dungeon_builder.world.physics.temperature import TemperaturePhysics
from dungeon_builder.world.physics.humidity import HumidityPhysics
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_WATER,
    VOXEL_WATER_SOURCE,
    VOXEL_WATER_SINK,
    VOXEL_LAVA,
    VOXEL_LAVA_SOURCE,
    VOXEL_LAVA_SINK,
    VOXEL_OBSIDIAN,
    LAVA_TEMPERATURE,
    WATER_SOURCE_OUTPUT,
    WATER_TICK_INTERVAL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(width=8, depth=8, height=16):
    """Create a bus, grid, and water physics instance.

    Height=16 so water can be placed below the surface evaporation zone.
    """
    bus = EventBus()
    grid = VoxelGrid(width=width, depth=depth, height=height)
    wp = WaterPhysics(bus, grid)
    return bus, grid, wp


def _tick(bus, n=1, start=1):
    """Publish n tick events starting from start."""
    for i in range(start, start + n):
        bus.publish("tick", tick=i)


def _tick_water(bus, n=1, start=0):
    """Publish ticks that trigger water physics (multiples of WATER_TICK_INTERVAL)."""
    for i in range(n):
        bus.publish("tick", tick=(start + i + 1) * WATER_TICK_INTERVAL)


# ===========================================================================
# Water Source tests
# ===========================================================================


class TestWaterSource:
    """Water source blocks generate water in adjacent air/water cells.

    Tests call _apply_sources_and_sinks() directly to isolate source
    behavior from flow physics.
    """

    def test_source_fills_adjacent_air(self):
        """Water source creates water in all adjacent air cells, including
        above.  Sources fill upward so rivers in deep channels can fill
        the full channel depth.
        """
        bus, grid, wp = _make()
        grid.grid[4, 4, 10] = VOXEL_WATER_SOURCE
        # Ensure neighbors are air
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nx, ny, nz = 4+dx, 4+dy, 10+dz
            grid.grid[nx, ny, nz] = VOXEL_AIR

        wp._apply_sources_and_sinks()

        # All 6 neighbors (4 lateral + 1 below + 1 above) should be water
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nx, ny, nz = 4+dx, 4+dy, 10+dz
            assert grid.grid[nx, ny, nz] == VOXEL_WATER, (
                f"({nx},{ny},{nz}) should be water"
            )
            assert grid.water_level[nx, ny, nz] == WATER_SOURCE_OUTPUT

    def test_source_tops_up_existing_water(self):
        """Water source tops up adjacent water cells to full level."""
        bus, grid, wp = _make()
        grid.grid[4, 4, 10] = VOXEL_WATER_SOURCE
        # Place partially-filled water neighbor
        grid.grid[5, 4, 10] = VOXEL_WATER
        grid.water_level[5, 4, 10] = 50

        wp._apply_sources_and_sinks()

        assert grid.water_level[5, 4, 10] == WATER_SOURCE_OUTPUT

    def test_source_does_not_overwrite_solid(self):
        """Water source should not overwrite solid (non-air) blocks."""
        bus, grid, wp = _make()
        grid.grid[4, 4, 10] = VOXEL_WATER_SOURCE
        grid.grid[5, 4, 10] = VOXEL_STONE

        wp._apply_sources_and_sinks()

        assert grid.grid[5, 4, 10] == VOXEL_STONE

    def test_source_replenishes_after_drain(self):
        """After draining, source refills adjacent cells."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_WATER_SOURCE
        grid.grid[5, 4, 10] = VOXEL_AIR

        wp._apply_sources_and_sinks()
        assert grid.grid[5, 4, 10] == VOXEL_WATER
        assert grid.water_level[5, 4, 10] == WATER_SOURCE_OUTPUT

        # Manually drain the neighbor
        grid.water_level[5, 4, 10] = 10

        wp._apply_sources_and_sinks()
        assert grid.water_level[5, 4, 10] == WATER_SOURCE_OUTPUT

    def test_source_with_flow_fills_contained_chamber(self):
        """Full tick: source fills a contained chamber over time."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        # Small chamber: source + 2 air cells in a row
        grid.grid[4, 4, 10] = VOXEL_WATER_SOURCE
        grid.grid[5, 4, 10] = VOXEL_AIR
        grid.grid[6, 4, 10] = VOXEL_AIR

        _tick_water(bus, 10)

        # Both cells should have water
        assert grid.grid[5, 4, 10] == VOXEL_WATER
        assert grid.grid[6, 4, 10] == VOXEL_WATER


# ===========================================================================
# Water Sink tests
# ===========================================================================


class TestWaterSink:
    """Water sink blocks drain adjacent water."""

    def test_sink_drains_adjacent_water(self):
        """Water sink drains adjacent water cells to level 0."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_WATER_SINK
        grid.grid[5, 4, 10] = VOXEL_WATER
        grid.water_level[5, 4, 10] = 200

        wp._apply_sources_and_sinks()

        assert grid.water_level[5, 4, 10] == 0

    def test_sink_forces_own_water_level_zero(self):
        """Sink block's own water_level is always forced to 0."""
        bus, grid, wp = _make()
        grid.grid[4, 4, 10] = VOXEL_WATER_SINK
        grid.water_level[4, 4, 10] = 100

        wp._apply_sources_and_sinks()

        assert grid.water_level[4, 4, 10] == 0

    def test_sink_forces_own_humidity_zero(self):
        """Sink block's own humidity is forced to 0."""
        bus, grid, wp = _make()
        grid.grid[4, 4, 10] = VOXEL_WATER_SINK
        grid.humidity[4, 4, 10] = 0.8

        wp._apply_sources_and_sinks()

        assert grid.humidity[4, 4, 10] == 0.0

    def test_sink_does_not_affect_non_water_neighbors(self):
        """Sink should not affect stone or air neighbors."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_WATER_SINK
        grid.grid[5, 4, 10] = VOXEL_AIR

        wp._apply_sources_and_sinks()

        assert grid.grid[5, 4, 10] == VOXEL_AIR
        assert grid.grid[3, 4, 10] == VOXEL_STONE


# ===========================================================================
# Water Source + Sink Equilibrium
# ===========================================================================


class TestWaterEquilibrium:
    """Source and sink together create a flow equilibrium."""

    def test_source_sink_corridor(self):
        """Source at one end, sink at other end of a short corridor.

        After many ticks, source-side has water, sink stays at 0,
        and source-side level > sink-side level (gradient).
        """
        bus, grid, wp = _make(width=6, depth=3, height=16)
        grid.grid[:] = VOXEL_STONE
        # Short corridor: source, 2 air, sink
        grid.grid[1, 1, 10] = VOXEL_WATER_SOURCE
        grid.grid[2, 1, 10] = VOXEL_AIR
        grid.grid[3, 1, 10] = VOXEL_AIR
        grid.grid[4, 1, 10] = VOXEL_WATER_SINK

        # Run many ticks
        _tick_water(bus, 50)

        # Source neighbor should have water
        assert grid.grid[2, 1, 10] == VOXEL_WATER
        assert grid.water_level[2, 1, 10] > 0
        # Sink's own water_level forced to 0
        assert grid.water_level[4, 1, 10] == 0
        # Water gradient: source-side > sink-side
        assert grid.water_level[2, 1, 10] > grid.water_level[3, 1, 10]


# ===========================================================================
# Lava Source tests
# ===========================================================================


class TestLavaSource:
    """Lava source blocks generate lava in adjacent air/obsidian cells."""

    def test_lava_source_fills_adjacent_air(self):
        """Lava source converts adjacent air to lava."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_LAVA_SOURCE
        grid.grid[5, 4, 10] = VOXEL_AIR

        wp._apply_sources_and_sinks()

        assert int(grid.grid[5, 4, 10]) == VOXEL_LAVA
        assert grid.temperature[5, 4, 10] == LAVA_TEMPERATURE

    def test_lava_source_fills_obsidian(self):
        """Lava source regenerates through obsidian (converts to lava)."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_LAVA_SOURCE
        grid.grid[5, 4, 10] = VOXEL_OBSIDIAN

        wp._apply_sources_and_sinks()

        assert int(grid.grid[5, 4, 10]) == VOXEL_LAVA

    def test_lava_source_maintains_temperature(self):
        """Lava source block itself always stays at LAVA_TEMPERATURE."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_LAVA_SOURCE
        grid.temperature[4, 4, 10] = 50.0  # someone cooled it

        wp._apply_sources_and_sinks()

        assert grid.temperature[4, 4, 10] == LAVA_TEMPERATURE

    def test_lava_source_does_not_overwrite_stone(self):
        """Lava source should not overwrite solid blocks like stone."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_LAVA_SOURCE

        wp._apply_sources_and_sinks()

        # All stone neighbors should remain stone
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nx, ny, nz = 4+dx, 4+dy, 10+dz
            assert grid.grid[nx, ny, nz] == VOXEL_STONE


# ===========================================================================
# Lava Sink tests
# ===========================================================================


class TestLavaSink:
    """Lava sink blocks absorb adjacent lava."""

    def test_lava_sink_removes_adjacent_lava(self):
        """Lava sink converts adjacent lava to air."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_LAVA_SINK
        grid.grid[5, 4, 10] = VOXEL_LAVA
        grid.temperature[5, 4, 10] = LAVA_TEMPERATURE

        wp._apply_sources_and_sinks()

        assert grid.grid[5, 4, 10] == VOXEL_AIR
        assert grid.temperature[5, 4, 10] == 20.0

    def test_lava_sink_stays_cool(self):
        """Lava sink temperature is always clamped to 20."""
        bus, grid, wp = _make()
        grid.grid[4, 4, 10] = VOXEL_LAVA_SINK
        grid.temperature[4, 4, 10] = 500.0

        wp._apply_sources_and_sinks()

        assert grid.temperature[4, 4, 10] == 20.0

    def test_lava_sink_does_not_affect_stone(self):
        """Lava sink should only remove lava, not other blocks."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 10] = VOXEL_LAVA_SINK

        wp._apply_sources_and_sinks()

        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nx, ny, nz = 4+dx, 4+dy, 10+dz
            assert grid.grid[nx, ny, nz] == VOXEL_STONE


# ===========================================================================
# Lava Source + Sink Equilibrium
# ===========================================================================


class TestLavaEquilibrium:
    """Lava source and sink together create equilibrium."""

    def test_lava_source_sink_chain(self):
        """Lava source generates lava; lava sink absorbs it.

        Source at one end of a corridor, sink at the other.
        After many ticks, lava near source exists (high level) while lava
        near sink is drained (lower level or air).  With fluid lava, the
        corridor fills but the sink continuously drains the adjacent cell.
        """
        bus, grid, wp = _make(width=8, depth=3, height=16)
        grid.grid[:] = VOXEL_STONE
        # Corridor from x=1 to x=6 at y=1, z=10
        for x in range(1, 7):
            grid.grid[x, 1, 10] = VOXEL_AIR
        grid.grid[1, 1, 10] = VOXEL_LAVA_SOURCE
        grid.temperature[1, 1, 10] = LAVA_TEMPERATURE
        grid.grid[6, 1, 10] = VOXEL_LAVA_SINK

        # Run many ticks — source generates, sink absorbs
        _tick_water(bus, 30)

        # Source neighbor should have lava
        assert int(grid.grid[2, 1, 10]) == VOXEL_LAVA
        # Source neighbor should have high lava level
        assert grid.lava_level[2, 1, 10] > 0
        # Source stays as source type
        assert grid.grid[1, 1, 10] == VOXEL_LAVA_SOURCE
        # Sink stays as sink type
        assert grid.grid[6, 1, 10] == VOXEL_LAVA_SINK
        # Sink-adjacent cell (5,1,10) has lower lava than source-adjacent (2,1,10)
        # because the sink continuously drains it
        assert grid.lava_level[5, 1, 10] < grid.lava_level[2, 1, 10]


# ===========================================================================
# Temperature physics integration with lava sources
# ===========================================================================


class TestLavaSourceTemperature:
    """Temperature physics interacts correctly with lava source/sink."""

    def test_lava_source_fixed_temperature_in_temp_physics(self):
        """TemperaturePhysics also maintains LAVA_SOURCE at LAVA_TEMPERATURE."""
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=16)
        tp = TemperaturePhysics(bus, grid)
        grid.grid[:] = VOXEL_STONE
        grid.temperature[:] = 20.0
        grid.grid[4, 4, 10] = VOXEL_LAVA_SOURCE
        grid.temperature[4, 4, 10] = LAVA_TEMPERATURE

        for i in range(1, 100):
            bus.publish("tick", tick=i)

        # Source stays at LAVA_TEMPERATURE
        assert grid.temperature[4, 4, 10] == LAVA_TEMPERATURE
        # Nearby stone should have warmed up
        assert grid.temperature[3, 4, 10] > 20.0

    def test_lava_cools_with_distance_from_source(self):
        """Lava chain: blocks further from source should be cooler."""
        bus = EventBus()
        grid = VoxelGrid(width=12, depth=3, height=16)
        tp = TemperaturePhysics(bus, grid)

        grid.grid[:] = VOXEL_STONE
        grid.temperature[:] = 20.0

        # Lava chain: source → lava → lava → lava → lava
        grid.grid[1, 1, 10] = VOXEL_LAVA_SOURCE
        grid.temperature[1, 1, 10] = LAVA_TEMPERATURE
        for x in range(2, 8):
            grid.grid[x, 1, 10] = VOXEL_LAVA
            grid.temperature[x, 1, 10] = LAVA_TEMPERATURE

        # Run many diffusion ticks — lava conducts but cools
        for i in range(1, 500):
            bus.publish("tick", tick=i)

        # Source always hot
        assert grid.temperature[1, 1, 10] == LAVA_TEMPERATURE
        # Near source should be hotter than far from source
        near = float(grid.temperature[3, 1, 10])
        far = float(grid.temperature[7, 1, 10])
        assert near > far, f"Near ({near}) should be hotter than far ({far})"


# ===========================================================================
# Humidity physics integration with water sources/sinks
# ===========================================================================


class TestWaterSourceHumidity:
    """Humidity physics treats water sources like water for moisture."""

    def test_water_source_generates_humidity(self):
        """Blocks adjacent to water source should gain humidity."""
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=16)
        hp = HumidityPhysics(bus, grid)

        grid.grid[:] = VOXEL_STONE
        grid.humidity[:] = 0.0
        grid.grid[4, 4, 10] = VOXEL_WATER_SOURCE

        for i in range(1, 100):
            bus.publish("tick", tick=i)

        # Adjacent stone should have gained humidity
        assert grid.humidity[3, 4, 10] > 0.0

    def test_water_sink_forces_humidity_zero(self):
        """Humidity physics forces sink humidity to 0 each tick."""
        bus = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=16)
        hp = HumidityPhysics(bus, grid)

        grid.grid[:] = VOXEL_STONE
        grid.humidity[:] = 0.5
        grid.grid[4, 4, 10] = VOXEL_WATER_SINK

        for i in range(1, 100):
            bus.publish("tick", tick=i)

        assert grid.humidity[4, 4, 10] == 0.0
