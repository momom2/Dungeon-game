"""Tests for the fluid lava system: flow, heat transport, mana crystals, water interaction."""

import numpy as np
import pytest
import random

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.physics.water import WaterPhysics
from dungeon_builder.world.physics.temperature import TemperaturePhysics
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_WATER,
    VOXEL_LAVA,
    VOXEL_LAVA_SOURCE,
    VOXEL_LAVA_SINK,
    VOXEL_OBSIDIAN,
    LAVA_TEMPERATURE,
    WATER_TICK_INTERVAL,
    TEMPERATURE_TICK_INTERVAL,
    LAVA_SOURCE_OUTPUT,
    LAVA_FLOW_RATE,
    MANA_CRYSTAL_SPAWN_CHANCE,
    WATER_LAVA_PRODUCT,
)


def _make(width=10, depth=10, height=20):
    bus = EventBus()
    grid = VoxelGrid(width=width, depth=depth, height=height)
    wp = WaterPhysics(bus, grid)
    return bus, grid, wp


def _tick_water(bus, n=1, start=0):
    for i in range(n):
        bus.publish("tick", tick=(start + i + 1) * WATER_TICK_INTERVAL)


# ─────────────────────────────────────────────────────────────────────
# 1. Lava gravity flow
# ─────────────────────────────────────────────────────────────────────


class TestLavaGravityFlow:
    """Lava above air falls downward."""

    def test_lava_falls_through_air(self):
        """Lava placed above air should flow downward after _flow_lava()."""
        bus, grid, wp = _make()
        # Fill everything with stone
        grid.grid[:] = VOXEL_STONE

        # Place lava at (5,5,10) with air below at (5,5,11)
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 255
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE

        grid.grid[5, 5, 11] = VOXEL_AIR

        wp._flow_lava()

        # Lava should have moved down: lava_level at z=11 > 0
        assert int(grid.lava_level[5, 5, 11]) > 0
        # Source cell should be drained
        assert int(grid.lava_level[5, 5, 10]) == 0

    def test_lava_does_not_fall_through_solid(self):
        """Lava above stone should stay put."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place lava at z=10, stone at z=11 (already stone from fill)
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 255
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE

        wp._flow_lava()

        # Lava should stay at z=10
        assert int(grid.lava_level[5, 5, 10]) == 255
        assert int(grid.grid[5, 5, 10]) == VOXEL_LAVA


# ─────────────────────────────────────────────────────────────────────
# 2. Lava lateral leveling
# ─────────────────────────────────────────────────────────────────────


class TestLavaLateralLeveling:
    """Lava levels horizontally like a viscous fluid."""

    def test_lava_levels_laterally(self):
        """Lava at high level with adjacent air on same z should transfer significant lava."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Carve a 2-cell horizontal channel with stone floor below
        grid.grid[5, 5, 15] = VOXEL_LAVA
        grid.lava_level[5, 5, 15] = 200
        grid.temperature[5, 5, 15] = LAVA_TEMPERATURE

        grid.grid[6, 5, 15] = VOXEL_AIR

        wp._flow_lava()

        src = int(grid.lava_level[5, 5, 15])
        dst = int(grid.lava_level[6, 5, 15])
        # LAVA_FLOW_RATE=0.15, diff=200 initially, 2 iterations should
        # move meaningful amount (~30 first pass, ~25 second)
        assert dst > 20, f"Lava transfer too low: only {dst} units moved"
        # Conservation
        assert src + dst == 200

    def test_lava_equalizes_in_sealed_channel(self):
        """Lava in a sealed 3-cell channel should equalize within 20 ticks."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Carve 3-cell channel at z=15
        levels = [255, 100, 30]
        for i, x in enumerate(range(4, 7)):
            grid.grid[x, 5, 15] = VOXEL_LAVA
            grid.lava_level[x, 5, 15] = levels[i]
            grid.temperature[x, 5, 15] = LAVA_TEMPERATURE

        total = sum(levels)

        # Run 20 water ticks (lava is slower but should still converge)
        _tick_water(bus, n=20)

        result = [int(grid.lava_level[x, 5, 15]) for x in range(4, 7)]
        assert max(result) - min(result) <= 1, (
            f"Lava not equalized after 20 ticks: levels={result}"
        )
        assert sum(result) == total

    def test_lava_slower_than_water(self):
        """Lava should flow laterally slower than water given the same setup."""
        # Setup for lava
        bus_l, grid_l, wp_l = _make()
        grid_l.grid[:] = VOXEL_STONE
        grid_l.grid[5, 5, 15] = VOXEL_LAVA
        grid_l.lava_level[5, 5, 15] = 200
        grid_l.grid[6, 5, 15] = VOXEL_AIR

        # Setup for water (identical geometry)
        bus_w, grid_w, wp_w = _make()
        grid_w.grid[:] = VOXEL_STONE
        grid_w.grid[5, 5, 15] = VOXEL_WATER
        grid_w.water_level[5, 5, 15] = 200
        grid_w.grid[6, 5, 15] = VOXEL_AIR

        # Run one tick for each
        _tick_water(bus_l, n=1)
        _tick_water(bus_w, n=1)

        lava_transferred = int(grid_l.lava_level[6, 5, 15])
        water_transferred = int(grid_w.water_level[6, 5, 15])

        # Water should have transferred more than lava (WATER_FLOW_RATE=0.4 > LAVA_FLOW_RATE=0.15)
        assert water_transferred > lava_transferred, (
            f"Water ({water_transferred}) should transfer more than lava ({lava_transferred})"
        )


# ─────────────────────────────────────────────────────────────────────
# 3. Lava source output
# ─────────────────────────────────────────────────────────────────────


class TestLavaSourceOutput:
    """Lava sources fill adjacent air and top up adjacent lava."""

    def test_source_fills_adjacent_air(self):
        """Lava source with air neighbors should fill them with lava."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place lava source at center
        grid.grid[5, 5, 10] = VOXEL_LAVA_SOURCE

        # Air on one side
        grid.grid[6, 5, 10] = VOXEL_AIR

        wp._apply_sources_and_sinks()

        assert int(grid.grid[6, 5, 10]) == VOXEL_LAVA
        assert int(grid.lava_level[6, 5, 10]) == LAVA_SOURCE_OUTPUT

    def test_source_tops_up_lava(self):
        """Lava source next to partially-filled lava should top it up to 255."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        grid.grid[5, 5, 10] = VOXEL_LAVA_SOURCE
        grid.grid[6, 5, 10] = VOXEL_LAVA
        grid.lava_level[6, 5, 10] = 100

        wp._apply_sources_and_sinks()

        assert int(grid.lava_level[6, 5, 10]) == 255

    def test_source_does_not_overwrite_stone(self):
        """Stone neighbors of a lava source should remain stone."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        grid.grid[5, 5, 10] = VOXEL_LAVA_SOURCE

        wp._apply_sources_and_sinks()

        # All stone neighbors should remain stone
        assert int(grid.grid[4, 5, 10]) == VOXEL_STONE
        assert int(grid.grid[5, 4, 10]) == VOXEL_STONE
        assert int(grid.grid[5, 6, 10]) == VOXEL_STONE


# ─────────────────────────────────────────────────────────────────────
# 4. Lava sink drain
# ─────────────────────────────────────────────────────────────────────


class TestLavaSinkDrain:
    """Lava sinks drain adjacent lava cells."""

    def test_sink_drains_adjacent_lava(self):
        """Lava adjacent to a sink should be drained (level=0, becomes air on cleanup)."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        grid.grid[5, 5, 10] = VOXEL_LAVA_SINK
        grid.grid[6, 5, 10] = VOXEL_LAVA
        grid.lava_level[6, 5, 10] = 200
        grid.temperature[6, 5, 10] = LAVA_TEMPERATURE

        wp._apply_sources_and_sinks()

        assert int(grid.lava_level[6, 5, 10]) == 0

    def test_sink_clears_mana_crystals(self):
        """Sink should also zero mana_crystals of drained lava."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        grid.grid[5, 5, 10] = VOXEL_LAVA_SINK
        grid.grid[6, 5, 10] = VOXEL_LAVA
        grid.lava_level[6, 5, 10] = 200
        grid.mana_crystals[6, 5, 10] = 3

        wp._apply_sources_and_sinks()

        assert int(grid.mana_crystals[6, 5, 10]) == 0


# ─────────────────────────────────────────────────────────────────────
# 5. Lava pressure
# ─────────────────────────────────────────────────────────────────────


class TestLavaPressure:
    """Lava column exerts hydrostatic pressure on adjacent walls."""

    def test_lava_column_applies_shear(self):
        """A 5-deep lava column adjacent to stone should produce shear_load > 0."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Carve a vertical column of lava 5 deep at x=5, with stone wall at x=4
        for z in range(10, 15):
            grid.grid[5, 5, z] = VOXEL_LAVA
            grid.lava_level[5, 5, z] = 255
            grid.temperature[5, 5, z] = LAVA_TEMPERATURE

        # Clear shear load first
        grid.shear_load[:] = 0.0

        wp._apply_pressure()

        # Adjacent stone wall should have shear_load > 0
        # Check the deepest point where pressure is highest
        assert float(grid.shear_load[4, 5, 14]) > 0


# ─────────────────────────────────────────────────────────────────────
# 6. Lava cleanup
# ─────────────────────────────────────────────────────────────────────


class TestLavaCleanup:
    """Empty lava cells revert to air on cleanup."""

    def test_empty_lava_becomes_air(self):
        """VOXEL_LAVA with lava_level=0 should become VOXEL_AIR after cleanup."""
        bus, grid, wp = _make()
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 0

        wp._cleanup()

        assert int(grid.grid[5, 5, 10]) == VOXEL_AIR

    def test_cleanup_clears_mana_crystals(self):
        """Cleanup should also reset mana_crystals to 0 for emptied lava."""
        bus, grid, wp = _make()
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 0
        grid.mana_crystals[5, 5, 10] = 4

        wp._cleanup()

        assert int(grid.grid[5, 5, 10]) == VOXEL_AIR
        assert int(grid.mana_crystals[5, 5, 10]) == 0


# ─────────────────────────────────────────────────────────────────────
# 7. Lava heat transport
# ─────────────────────────────────────────────────────────────────────


class TestLavaHeatTransport:
    """Heat moves with lava flow (flow-based convection)."""

    def test_heat_moves_with_flow(self):
        """Hot lava flowing downward should carry heat to the destination cell."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place hot lava at z=10, air at z=11
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 255
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE

        grid.grid[5, 5, 11] = VOXEL_AIR
        grid.temperature[5, 5, 11] = 0.0

        wp._flow_lava()
        wp._transport_lava_heat()

        # Destination cell should have received some heat
        assert float(grid.temperature[5, 5, 11]) > 0


# ─────────────────────────────────────────────────────────────────────
# 8. Mana crystal spawn
# ─────────────────────────────────────────────────────────────────────


class TestManaCrystalSpawn:
    """Lava sources spawn mana crystals in adjacent lava over time."""

    def test_source_spawns_crystals(self):
        """After many water ticks, at least one adjacent lava cell should have mana_crystals > 0."""
        random.seed(42)
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place lava source at center with lava neighbors
        grid.grid[5, 5, 10] = VOXEL_LAVA_SOURCE
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE

        # Place lava cells adjacent to the source
        for dx, dy, dz in [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]:
            nx, ny, nz = 5 + dx, 5 + dy, 10 + dz
            grid.grid[nx, ny, nz] = VOXEL_LAVA
            grid.lava_level[nx, ny, nz] = 255
            grid.temperature[nx, ny, nz] = LAVA_TEMPERATURE

        # Run 200 water ticks
        # With MANA_CRYSTAL_SPAWN_CHANCE=0.05 per source per tick and 4 lava neighbors,
        # P(no spawn in 200 ticks) = (1 - 0.05)^200 ≈ 0.000035 → virtually guaranteed
        _tick_water(bus, n=200)

        # Check if any adjacent cell has mana_crystals > 0
        total_mana = 0
        for dx, dy, dz in [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]:
            nx, ny, nz = 5 + dx, 5 + dy, 10 + dz
            total_mana += int(grid.mana_crystals[nx, ny, nz])

        assert total_mana > 0, "Expected at least one mana crystal after 200 ticks"


# ─────────────────────────────────────────────────────────────────────
# 9. Mana crystal drift
# ─────────────────────────────────────────────────────────────────────


class TestManaCrystalDrift:
    """Mana crystals drift with lava flow."""

    def test_crystals_drift_with_flow(self):
        """Mana crystals in flowing lava should move toward the flow destination."""
        random.seed(42)
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place lava with mana crystals at z=10, air at z=11
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 255
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE
        grid.mana_crystals[5, 5, 10] = 5

        grid.grid[5, 5, 11] = VOXEL_AIR

        wp._flow_lava()
        wp._drift_mana_crystals()

        # Some crystals should have moved to z=11
        assert int(grid.mana_crystals[5, 5, 11]) > 0

    def test_crystal_conservation(self):
        """Total mana crystals should be conserved through drift."""
        random.seed(42)
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place lava with crystals at z=10, air below and to the side
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 255
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE
        grid.mana_crystals[5, 5, 10] = 5

        grid.grid[5, 5, 11] = VOXEL_AIR

        total_before = int(np.sum(grid.mana_crystals))

        wp._flow_lava()
        wp._drift_mana_crystals()

        total_after = int(np.sum(grid.mana_crystals))

        assert total_before == total_after


# ─────────────────────────────────────────────────────────────────────
# 10. Mana crystal temperature pin
# ─────────────────────────────────────────────────────────────────────


class TestManaCrystalTemperaturePin:
    """Lava cells with mana crystals stay pinned at LAVA_TEMPERATURE."""

    def test_mana_lava_pinned_at_lava_temp(self):
        """Lava with mana_crystals >= 1 should remain at LAVA_TEMPERATURE after diffusion."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place lava with mana crystals in stone shell
        grid.grid[5, 5, 10] = VOXEL_LAVA
        grid.lava_level[5, 5, 10] = 255
        grid.mana_crystals[5, 5, 10] = 1
        grid.temperature[5, 5, 10] = LAVA_TEMPERATURE

        # Set up temperature physics
        tp = TemperaturePhysics(bus, grid)

        # Run temperature diffusion for 10 ticks
        for i in range(10):
            bus.publish("tick", tick=(i + 1) * TEMPERATURE_TICK_INTERVAL)

        # Cell with mana_crystals >= 1 should still be at LAVA_TEMPERATURE
        assert float(grid.temperature[5, 5, 10]) == pytest.approx(
            LAVA_TEMPERATURE, abs=0.1
        )


# ─────────────────────────────────────────────────────────────────────
# 11. Water-lava interaction
# ─────────────────────────────────────────────────────────────────────


class TestWaterLavaInteraction:
    """Water meeting lava produces obsidian or dominant fluid survives."""

    def test_obsidian_forms_from_interaction(self):
        """When random chance triggers obsidian, both cells become WATER_LAVA_PRODUCT."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Place water and lava adjacent to each other
        grid.grid[5, 5, 10] = VOXEL_WATER
        grid.water_level[5, 5, 10] = 255

        grid.grid[6, 5, 10] = VOXEL_LAVA
        grid.lava_level[6, 5, 10] = 255
        grid.temperature[6, 5, 10] = LAVA_TEMPERATURE

        # Seed so random.random() < chance (chance = min(255,255)/255 = 1.0)
        # With chance = 1.0, any random value < 1.0 will trigger obsidian
        random.seed(42)

        wp._lava_water_interaction()

        # Both cells should become obsidian
        assert int(grid.grid[5, 5, 10]) == WATER_LAVA_PRODUCT
        assert int(grid.grid[6, 5, 10]) == WATER_LAVA_PRODUCT

    def test_dominant_fluid_survives(self):
        """When obsidian does not form, dominant fluid keeps the difference."""
        bus, grid, wp = _make()
        grid.grid[:] = VOXEL_STONE

        # Water dominates: 200 vs 100
        grid.grid[5, 5, 10] = VOXEL_WATER
        grid.water_level[5, 5, 10] = 200

        grid.grid[6, 5, 10] = VOXEL_LAVA
        grid.lava_level[6, 5, 10] = 100
        grid.temperature[6, 5, 10] = LAVA_TEMPERATURE

        # chance = min(200,100)/255 ≈ 0.39
        # We need random.random() >= chance so obsidian does NOT form.
        # Seed to get a value that will be >= 0.39 on the first roll.
        # Use a seed that gives random.random() > 0.4
        # Let's just loop to find a good seed
        for seed_val in range(1000):
            random.seed(seed_val)
            val = random.random()
            if val >= 100 / 255.0:
                break

        # Re-seed and run
        random.seed(seed_val)
        wp._lava_water_interaction()

        # Water should remain with level = 200 - 100 = 100
        assert int(grid.grid[5, 5, 10]) == VOXEL_WATER
        assert int(grid.water_level[5, 5, 10]) == 100

        # Lava should be gone (becomes air)
        assert int(grid.grid[6, 5, 10]) == VOXEL_AIR
        assert int(grid.lava_level[6, 5, 10]) == 0


# ─────────────────────────────────────────────────────────────────────
# 12. Mana crystal accumulation
# ─────────────────────────────────────────────────────────────────────


class TestManaCrystalAccumulation:
    """Basic getter/setter for mana_crystals."""

    def test_multiple_crystals_in_one_cell(self):
        """Directly set mana_crystals[x,y,z] = 5, verify get_mana_crystals returns 5."""
        _, grid, _ = _make()
        grid.mana_crystals[3, 4, 5] = 5
        assert grid.get_mana_crystals(3, 4, 5) == 5
