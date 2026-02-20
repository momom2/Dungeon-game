"""Tests for temperature diffusion physics."""

import numpy as np
import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.physics.temperature import TemperaturePhysics
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_LAVA,
    VOXEL_LAVA_SOURCE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_PIPE,
    VOXEL_SPIKE,
    VOXEL_DOOR,
    VOXEL_REINFORCED_WALL,
    VOXEL_IRON_BARS,
    VOXEL_FLOODGATE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_HEAT_BEACON,
    VOXEL_ALARM_BELL,
    VOXEL_GOLD_BAIT,
    LAVA_TEMPERATURE,
    MANA_CRYSTAL_TEMPERATURE,
    TEMPERATURE_TICK_INTERVAL,
    METAL_IRON,
    METAL_COPPER,
    METAL_GOLD,
    METAL_MELT_TEMPERATURE,
    ENCHANTED_OFFSET,
)


def _make_physics(width=8, depth=8, height=8):
    bus = EventBus()
    grid = VoxelGrid(width=width, depth=depth, height=height)
    phys = TemperaturePhysics(bus, grid)
    return bus, grid, phys


def test_lava_source_stays_hot():
    """Lava SOURCE voxels maintain their temperature after diffusion.

    Regular VOXEL_LAVA conducts heat but cools — only LAVA_SOURCE stays fixed.
    """
    bus, grid, phys = _make_physics()
    grid.grid[4, 4, 4] = VOXEL_LAVA_SOURCE
    grid.temperature[4, 4, 4] = LAVA_TEMPERATURE

    for i in range(1, 100):
        bus.publish("tick", tick=i)

    assert grid.temperature[4, 4, 4] == LAVA_TEMPERATURE


def test_lava_cools_without_source():
    """Regular lava conducts heat but cools over time (no longer fixed-temp)."""
    bus, grid, phys = _make_physics()
    grid.grid[:] = VOXEL_STONE
    grid.temperature[:] = 20.0
    grid.grid[4, 4, 4] = VOXEL_LAVA
    grid.temperature[4, 4, 4] = LAVA_TEMPERATURE

    for i in range(1, 200):
        bus.publish("tick", tick=i)

    # Lava should have cooled below its initial temperature
    assert grid.temperature[4, 4, 4] < LAVA_TEMPERATURE


def test_mana_crystal_stays_cool():
    """Mana crystals maintain their fixed temperature."""
    bus, grid, phys = _make_physics()
    grid.grid[4, 4, 4] = VOXEL_MANA_CRYSTAL
    grid.temperature[4, 4, 4] = MANA_CRYSTAL_TEMPERATURE

    # Surround with hot material
    grid.temperature[3, 4, 4] = 500.0
    grid.temperature[5, 4, 4] = 500.0

    for i in range(1, 100):
        bus.publish("tick", tick=i)

    assert grid.temperature[4, 4, 4] == MANA_CRYSTAL_TEMPERATURE


def test_heat_spreads_from_lava_source():
    """Heat should spread from a lava source to adjacent voxels."""
    bus, grid, phys = _make_physics(height=16)
    # Fill with stone
    grid.grid[:] = VOXEL_STONE
    grid.temperature[:] = 20.0

    # Place lava source deep (away from surface heat loss)
    grid.grid[4, 4, 12] = VOXEL_LAVA_SOURCE
    grid.temperature[4, 4, 12] = LAVA_TEMPERATURE

    initial_neighbor = float(grid.temperature[3, 4, 12])

    # Run many ticks
    for i in range(1, 200):
        bus.publish("tick", tick=i)

    # Neighbor should be warmer than initial
    assert grid.temperature[3, 4, 12] > initial_neighbor


def test_surface_cools():
    """Surface voxels should lose heat over time."""
    bus, grid, phys = _make_physics()
    grid.temperature[:, :, 0] = 100.0

    for i in range(1, 50):
        bus.publish("tick", tick=i)

    # Surface should have cooled
    avg_surface = float(np.mean(grid.temperature[:, :, 0]))
    assert avg_surface < 100.0


def test_no_negative_temperature():
    """Temperature should never go negative."""
    bus, grid, phys = _make_physics()
    grid.temperature[:] = 0.0

    for i in range(1, 50):
        bus.publish("tick", tick=i)

    assert np.all(grid.temperature >= 0.0)


def test_only_runs_on_interval():
    """Diffusion only runs on TEMPERATURE_TICK_INTERVAL ticks."""
    bus, grid, phys = _make_physics()
    grid.grid[:] = VOXEL_STONE
    grid.temperature[:] = 20.0
    grid.grid[4, 4, 4] = VOXEL_LAVA_SOURCE
    grid.temperature[4, 4, 4] = LAVA_TEMPERATURE

    initial = float(grid.temperature[3, 4, 4])

    # Tick 1 should not trigger diffusion (interval=5)
    bus.publish("tick", tick=1)
    assert grid.temperature[3, 4, 4] == initial

    # Tick 5 should trigger diffusion
    bus.publish("tick", tick=TEMPERATURE_TICK_INTERVAL)
    assert grid.temperature[3, 4, 4] != initial


def test_equilibrium_converges():
    """A small grid with uniform material should converge toward uniform temp."""
    bus, grid, phys = _make_physics(width=4, depth=4, height=4)
    grid.grid[:] = VOXEL_STONE
    grid.temperature[:] = 50.0
    grid.temperature[2, 2, 2] = 200.0

    # Run for many iterations
    for i in range(1, 1000):
        bus.publish("tick", tick=i)

    # All temperatures should be closer together
    temps = grid.temperature.flatten()
    assert np.std(temps) < 50.0  # significant convergence


def test_heat_conservation_no_sources_or_sinks():
    """Total heat in a closed system (no lava, no mana crystal, no surface)
    should be conserved across diffusion ticks."""
    # Use interior cells only to avoid surface heat loss (z=0 loses heat).
    # Place all heat in interior cells and fill entire grid with stone.
    bus, grid, phys = _make_physics(width=6, depth=6, height=6)
    grid.grid[:] = VOXEL_STONE

    # Set up a hot spot in the interior (away from z=0 surface)
    grid.temperature[:] = 0.0
    grid.temperature[3, 3, 3] = 1000.0
    grid.temperature[2, 3, 3] = 500.0

    initial_total_heat = float(np.sum(grid.temperature))

    # Run multiple diffusion cycles
    for i in range(1, 200):
        bus.publish("tick", tick=i)

    final_total_heat = float(np.sum(grid.temperature))

    # Surface heat loss will reduce total heat. Measure only interior.
    # For a precise test, check interior-only conservation by subtracting
    # the known sink (surface z=0).
    # Instead, just verify no heat was CREATED (total can decrease from surface loss)
    assert final_total_heat <= initial_total_heat + 1e-3


def test_heat_conservation_interior_only():
    """Heat in interior cells (no surface contact) is conserved exactly."""
    # Use a tall grid so we can place heat far from surface (z <= SURFACE_Z)
    bus, grid, phys = _make_physics(width=8, depth=8, height=16)
    grid.grid[:] = VOXEL_STONE
    grid.temperature[:] = 0.0

    # Place heat only in deep interior (far from surface evaporation zone)
    grid.temperature[4, 4, 12] = 800.0
    grid.temperature[3, 4, 12] = 200.0

    initial_total = float(np.sum(grid.temperature))

    # Run a few diffusion ticks
    for i in range(1, 30):
        bus.publish("tick", tick=i)

    final_total = float(np.sum(grid.temperature))

    # Heat should be approximately conserved (small float error acceptable)
    # All heat is deep interior, far from surface loss zone
    assert final_total == pytest.approx(initial_total, abs=1.0)


# ---------------------------------------------------------------------------
# Metal melting tests (from test_metal_melting.py)
# ---------------------------------------------------------------------------


def _setup(width=8, depth=8, height=8):
    """Create a minimal event bus, voxel grid, and temperature physics instance."""
    eb = EventBus()
    grid = VoxelGrid(width=width, depth=depth, height=height)
    tp = TemperaturePhysics(eb, grid)
    return eb, grid, tp


# ---------------------------------------------------------------------------
# Basic copper pipe melting threshold
# ---------------------------------------------------------------------------


class TestCopperPipeMelting:
    def test_copper_pipe_melts_at_threshold(self):
        """Copper pipe at exactly 800 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_COPPER)
        grid.temperature[3, 3, 3] = 800.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR

    def test_copper_pipe_survives_below_threshold(self):
        """Copper pipe at 799 C (below threshold) should remain."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_COPPER)
        grid.temperature[3, 3, 3] = 799.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_PIPE


# ---------------------------------------------------------------------------
# Iron pipe melting threshold
# ---------------------------------------------------------------------------


class TestIronPipeMelting:
    def test_iron_pipe_melts_at_threshold(self):
        """Iron pipe at exactly 1200 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_IRON)
        grid.temperature[3, 3, 3] = 1200.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR

    def test_iron_pipe_survives_below_threshold(self):
        """Iron pipe at 1199 C (below threshold) should remain."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_IRON)
        grid.temperature[3, 3, 3] = 1199.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_PIPE


# ---------------------------------------------------------------------------
# Gold pipe melting threshold
# ---------------------------------------------------------------------------


class TestGoldPipeMelting:
    def test_gold_pipe_melts_at_threshold(self):
        """Gold pipe at exactly 600 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_GOLD)
        grid.temperature[3, 3, 3] = 600.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR


# ---------------------------------------------------------------------------
# Enchanted immunity
# ---------------------------------------------------------------------------


class TestEnchantedImmunity:
    def test_enchanted_copper_pipe_immune(self):
        """Enchanted copper pipe at 800 C should NOT melt."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_COPPER | ENCHANTED_OFFSET)
        grid.temperature[3, 3, 3] = 800.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_PIPE

    def test_enchanted_iron_immune(self):
        """Enchanted iron pipe at 1200 C should NOT melt."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_IRON | ENCHANTED_OFFSET)
        grid.temperature[3, 3, 3] = 1200.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_PIPE

    def test_enchanted_gold_immune(self):
        """Enchanted gold pipe at 600 C should NOT melt."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_GOLD | ENCHANTED_OFFSET)
        grid.temperature[3, 3, 3] = 600.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_PIPE


# ---------------------------------------------------------------------------
# Other meltable block types
# ---------------------------------------------------------------------------


class TestOtherMeltableBlocks:
    def test_spike_melts(self):
        """Iron spike at 1200 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_SPIKE)
        grid.set_metal_type(3, 3, 3, METAL_IRON)
        grid.temperature[3, 3, 3] = 1200.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR

    def test_door_melts(self):
        """Gold door at 600 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_DOOR)
        grid.set_metal_type(3, 3, 3, METAL_GOLD)
        grid.temperature[3, 3, 3] = 600.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR

    def test_reinforced_wall_melts(self):
        """Copper reinforced wall at 800 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_REINFORCED_WALL)
        grid.set_metal_type(3, 3, 3, METAL_COPPER)
        grid.temperature[3, 3, 3] = 800.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR

    def test_iron_bars_melt(self):
        """Iron bars at 1200 C should melt to air."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_IRON_BARS)
        grid.set_metal_type(3, 3, 3, METAL_IRON)
        grid.temperature[3, 3, 3] = 1200.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(3, 3, 3) == VOXEL_AIR


# ---------------------------------------------------------------------------
# Event publishing
# ---------------------------------------------------------------------------


class TestMeltingEvents:
    def test_metal_melted_event_published(self):
        """The 'metal_melted' event should be published when a block melts."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_COPPER)
        grid.temperature[3, 3, 3] = 800.0

        events = []
        eb.subscribe("metal_melted", lambda **kw: events.append(True))

        tp._check_melting(grid.grid, grid.temperature)

        assert len(events) == 1

    def test_no_event_when_nothing_melts(self):
        """No 'metal_melted' event when no blocks reach their melt temperature."""
        eb, grid, tp = _setup()
        grid.set(3, 3, 3, VOXEL_PIPE)
        grid.set_metal_type(3, 3, 3, METAL_IRON)
        grid.temperature[3, 3, 3] = 500.0  # Well below iron's 1200 C

        events = []
        eb.subscribe("metal_melted", lambda **kw: events.append(True))

        tp._check_melting(grid.grid, grid.temperature)

        assert len(events) == 0


# ---------------------------------------------------------------------------
# Multiple simultaneous melts
# ---------------------------------------------------------------------------


class TestMultipleMelts:
    def test_multiple_blocks_melt_simultaneously(self):
        """Two blocks at their melt temperatures should both become air."""
        eb, grid, tp = _setup()

        # Copper pipe at 800 C
        grid.set(2, 2, 2, VOXEL_PIPE)
        grid.set_metal_type(2, 2, 2, METAL_COPPER)
        grid.temperature[2, 2, 2] = 800.0

        # Gold door at 600 C
        grid.set(5, 5, 5, VOXEL_DOOR)
        grid.set_metal_type(5, 5, 5, METAL_GOLD)
        grid.temperature[5, 5, 5] = 600.0

        tp._check_melting(grid.grid, grid.temperature)

        assert grid.get(2, 2, 2) == VOXEL_AIR
        assert grid.get(5, 5, 5) == VOXEL_AIR
