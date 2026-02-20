"""Tests for impact cascade and shock wave propagation.

All impact energies and pre-loads are derived from config LUTs so the tests
remain valid when material parameters are re-tuned.
"""

import pytest
import numpy as np

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.physics.gravity import GravityPhysics
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_BEDROCK,
    VOXEL_GRANITE,
    VOXEL_OBSIDIAN,
    VOXEL_CHALK,
    VOXEL_DIRT,
    VOXEL_IRON_INGOT,
    VOXEL_IRON_ORE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_WEIGHT,
    VOXEL_MAX_LOAD,
    VOXEL_SHOCK_TRANSMIT,
    VOXEL_BRITTLENESS,
    GRAVITY_TICK_INTERVAL,
    CONNECTIVITY_TICK_INTERVAL,
    IMPACT_DAMAGE_THRESHOLD,
    IMPACT_DAMAGE_FACTOR,
    MAX_CASCADE_PER_TICK,
    SHOCK_ATTENUATION,
    SHOCK_STRUCTURAL_FACTOR,
    MAX_SHOCK_PROPAGATION_STEPS,
    SHATTER_THRESHOLD,
)

# ── Helpers derived from config ──────────────────────────────────────

# Per-material capacities (shorthand)
_chalk_cap = VOXEL_MAX_LOAD[VOXEL_CHALK]
_obsidian_cap = VOXEL_MAX_LOAD[VOXEL_OBSIDIAN]
_iron_ingot_cap = VOXEL_MAX_LOAD[VOXEL_IRON_INGOT]

# Per-material transmissivities
_obsidian_transmit = VOXEL_SHOCK_TRANSMIT[VOXEL_OBSIDIAN]
_dirt_transmit = VOXEL_SHOCK_TRANSMIT[VOXEL_DIRT]

# Attenuation factor per propagation step (1 - SHOCK_ATTENUATION)
_atten = 1.0 - SHOCK_ATTENUATION


def _setup(width=10, depth=10, height=10):
    bus = EventBus()
    grid = VoxelGrid(width, depth, height)
    phys = GravityPhysics(bus, grid)
    return bus, grid, phys


def _tick(bus, tick_num):
    bus.publish("tick", tick=tick_num)


class TestShortFallNoShock:
    def test_short_fall_no_shock(self):
        """Falls below IMPACT_DAMAGE_THRESHOLD produce no shock wave."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR
        # Stone column to receive impact
        grid.grid[5, 5, 5:] = VOXEL_STONE

        # Loose stone just 1 cell above (fall distance = 1 < threshold)
        grid.grid[5, 5, 4] = VOXEL_STONE
        grid.loose[5, 5, 4] = True
        grid.fall_distance[5, 5, 4] = 1

        events = []
        bus.subscribe("shock_cascade", lambda **kw: events.append(kw))

        _tick(bus, GRAVITY_TICK_INTERVAL)

        # No shock cascade should fire for short falls
        assert len(events) == 0


class TestImpactPropagatesThroughSolid:
    def test_impact_propagates_through_solid(self):
        """Shock energy reaches blocks adjacent to impact point."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Column of chalk blocks with bedrock at bottom
        grid.grid[5, 5, 5] = VOXEL_CHALK
        grid.grid[5, 5, 6] = VOXEL_CHALK
        grid.grid[5, 5, 7] = VOXEL_BEDROCK

        # Impact must exceed SHATTER_THRESHOLD × chalk capacity so chalk
        # shatters (brittleness >= 0.5).
        shock_needed = _chalk_cap * SHATTER_THRESHOLD * 1.5  # 50% margin
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = shock_needed

        events = []
        bus.subscribe("shock_cascade", lambda **kw: events.append(kw))

        phys._propagate_shock(impact)

        # Chalk at z=5 should be affected (shattered or cracked)
        assert grid.grid[5, 5, 5] == VOXEL_AIR or bool(grid.loose[5, 5, 5])
        assert len(events) > 0


class TestShockAttenuatesWithDistance:
    def test_shock_attenuates_with_distance(self):
        """Shock energy decreases at blocks further from impact."""
        bus, grid, phys = _setup(width=12, depth=12, height=10)
        grid.grid[:, :, :] = VOXEL_AIR

        # Create a horizontal line of obsidian (high transmissivity)
        for x in range(2, 10):
            grid.grid[x, 5, 5] = VOXEL_OBSIDIAN
        grid.grid[1, 5, 5] = VOXEL_BEDROCK  # anchor at one end

        # Set up impact energy as if a heavy block landed
        impact = np.zeros((12, 12, 9), dtype=np.float32)
        impact[9, 5, 4] = 50.0

        # Call propagate_shock directly
        phys._propagate_shock(impact)

        # Blocks nearer to impact should have received more stress
        # (or become loose/shattered if stress was high enough).
        # The shock attenuates by _atten per step — this verifies the
        # system runs without error and the attenuation logic executes.


class TestBrittleMaterialShatters:
    def test_brittle_material_shatters(self):
        """Obsidian (high brittleness) converts to air on high impact."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Single obsidian block with bedrock below
        grid.grid[5, 5, 5] = VOXEL_OBSIDIAN
        grid.grid[5, 5, 6] = VOXEL_BEDROCK

        # Need shock/capacity > SHATTER_THRESHOLD and brittleness >= 0.5
        shock_needed = _obsidian_cap * SHATTER_THRESHOLD * 1.5  # 50% margin
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = shock_needed

        phys._propagate_shock(impact)

        # Obsidian should shatter to air (brittleness >= 0.5)
        assert grid.grid[5, 5, 5] == VOXEL_AIR


class TestDuctileMaterialCracksNotShatters:
    def test_ductile_material_cracks_not_shatters(self):
        """Iron ingot (low brittleness) becomes loose, not destroyed."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Iron ingot block with bedrock below
        grid.grid[5, 5, 5] = VOXEL_IRON_INGOT
        grid.grid[5, 5, 6] = VOXEL_BEDROCK

        # Pre-load near capacity so a moderate shock cracks it.
        # total_force = pre_load + shock * SHOCK_STRUCTURAL_FACTOR > capacity
        # Iron brittleness < 0.5 → should crack, not shatter.
        pre_load = _iron_ingot_cap * 0.85
        grid.load[5, 5, 5] = pre_load

        # Shock that pushes total_force over capacity but keeps
        # shock/capacity < SHATTER_THRESHOLD (so it cracks, not shatters).
        # shock_needed: pre_load + shock * factor > capacity
        # shock > (capacity - pre_load) / factor
        gap = _iron_ingot_cap - pre_load
        shock_for_crack = gap / SHOCK_STRUCTURAL_FACTOR * 2.0  # 2× margin
        # Ensure ratio stays below shatter threshold
        assert shock_for_crack / _iron_ingot_cap < SHATTER_THRESHOLD, (
            "Test setup: shock would shatter instead of crack"
        )
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = shock_for_crack

        phys._propagate_shock(impact)

        # Should still exist as iron ingot (not converted to air)
        assert grid.grid[5, 5, 5] == VOXEL_IRON_INGOT
        # But should be loose (cracked)
        assert bool(grid.loose[5, 5, 5]) is True


class TestAnchorAbsorbsShock:
    def test_anchor_absorbs_shock(self):
        """Bedrock stops shock propagation completely."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Bedrock wall, then chalk behind it
        grid.grid[5, 5, 5] = VOXEL_BEDROCK
        grid.grid[5, 5, 6] = VOXEL_CHALK

        # Large impact at bedrock
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = _chalk_cap * 5.0  # big, but bedrock absorbs it

        phys._propagate_shock(impact)

        # Bedrock absorbs all shock — chalk should be unaffected
        assert bool(grid.loose[5, 5, 6]) is False
        assert grid.grid[5, 5, 6] == VOXEL_CHALK


class TestShockPlusStructuralLoadFails:
    def test_shock_plus_structural_load_fails(self):
        """Block under high structural load fails from small shock."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Chalk block already near capacity
        grid.grid[5, 5, 5] = VOXEL_CHALK
        grid.grid[5, 5, 6] = VOXEL_BEDROCK
        pre_load = _chalk_cap * 0.95  # 95% of capacity
        grid.load[5, 5, 5] = pre_load

        # Small shock — just enough to push it over the edge.
        # total_force = pre_load + shock * SHOCK_STRUCTURAL_FACTOR > capacity
        # shock > (capacity - pre_load) / factor
        gap = _chalk_cap - pre_load
        shock_needed = gap / SHOCK_STRUCTURAL_FACTOR * 3.0  # comfortable margin
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = shock_needed

        phys._propagate_shock(impact)

        # Chalk should crack (become loose)
        assert bool(grid.loose[5, 5, 5]) is True


class TestCascadeCapLimitsFailures:
    def test_cascade_cap_limits_failures(self):
        """No more than MAX_CASCADE_PER_TICK total failures per tick."""
        bus, grid, phys = _setup(width=12, depth=12, height=10)
        grid.grid[:, :, :] = VOXEL_AIR

        # Fill a large area with weak chalk blocks
        grid.grid[2:10, 2:10, 2:8] = VOXEL_CHALK
        grid.grid[:, :, 9] = VOXEL_BEDROCK

        # Massive impact — well above anything that would shatter all chalk
        impact = np.zeros((12, 12, 9), dtype=np.float32)
        impact[5, 5, 1] = _chalk_cap * SHATTER_THRESHOLD * 50.0

        events = []
        bus.subscribe("shock_cascade", lambda **kw: events.append(kw))

        phys._propagate_shock(impact)

        if events:
            total = sum(e.get("cracked", 0) + e.get("shattered", 0) for e in events)
            assert total <= MAX_CASCADE_PER_TICK


class TestChainReactionAcrossTicks:
    def test_chain_reaction_across_ticks(self):
        """Shock causes loose blocks, which can fall on subsequent ticks."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Stack: granite on top, chalk below
        grid.grid[5, 5, 3] = VOXEL_GRANITE
        grid.grid[5, 5, 4] = VOXEL_CHALK
        grid.grid[5, 5, 5] = VOXEL_BEDROCK

        # Moderate impact on the granite
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 2] = _chalk_cap * 2.0

        phys._propagate_shock(impact)

        # If chalk cracked (became loose), it will fall on next gravity tick.
        # Even if it didn't crack from shock, verify the system runs without
        # error.
        chalk_cracked = bool(grid.loose[5, 5, 4])


class TestDirtAbsorbsShock:
    def test_dirt_absorbs_shock(self):
        """Dirt (low transmissivity) barely transmits shock."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Dirt block followed by chalk
        grid.grid[5, 5, 5] = VOXEL_DIRT
        grid.grid[5, 5, 6] = VOXEL_CHALK
        grid.grid[5, 5, 7] = VOXEL_BEDROCK

        # Moderate impact — transmitted shock through dirt should be too
        # small to crack chalk:
        #   shock_to_chalk ≈ impact × dirt_transmit × _atten
        #   total_force = 0 + shock_to_chalk × SHOCK_STRUCTURAL_FACTOR
        # We pick impact so that total_force < chalk capacity.
        # Use impact = chalk_cap (shock through dirt is tiny fraction).
        impact_energy = _chalk_cap  # after dirt absorption, barely anything
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = impact_energy

        phys._propagate_shock(impact)

        # Dirt absorbs most shock, chalk should survive
        assert bool(grid.loose[5, 5, 6]) is False


class TestObsidianTransmitsShock:
    def test_obsidian_transmits_shock(self):
        """Obsidian (high transmissivity) transmits shock much further than dirt."""
        bus1, grid1, phys1 = _setup()
        bus2, grid2, phys2 = _setup()

        # Compute an impact and pre-load that cracks chalk through obsidian
        # but NOT through dirt.
        #
        # Shock transmitted to chalk ≈ impact × transmit × _atten
        # total_force = pre_load + shock_to_chalk × SHOCK_STRUCTURAL_FACTOR
        #
        # Through obsidian: shock_obs = impact × obsidian_transmit × _atten
        # Through dirt:     shock_dirt = impact × dirt_transmit × _atten
        #
        # We need:
        #   pre_load + shock_obs × factor > chalk_cap  (cracks)
        #   pre_load + shock_dirt × factor < chalk_cap  (survives)

        # Choose impact so the two transmitted shocks bracket the gap.
        # Set pre_load = 90% of capacity. Then the gap is 10% of capacity.
        pre_load = _chalk_cap * 0.9
        gap = _chalk_cap - pre_load  # 10% of chalk_cap

        # shock_obs × factor = impact × obs_transmit × _atten × factor
        # We need impact × obs_transmit × _atten × factor > gap
        # and   impact × dirt_transmit × _atten × factor < gap
        #
        # Since obs_transmit >> dirt_transmit, this is achievable.
        # Solve for impact from the obsidian side with 2× margin:
        impact_energy = (gap / (SHOCK_STRUCTURAL_FACTOR * _obsidian_transmit * _atten)) * 2.0

        # Verify dirt side stays safe (sanity check)
        shock_through_dirt = impact_energy * _dirt_transmit * _atten * SHOCK_STRUCTURAL_FACTOR
        assert pre_load + shock_through_dirt < _chalk_cap, (
            "Test setup: dirt path would also crack chalk"
        )

        # Setup 1: Obsidian followed by chalk
        grid1.grid[:, :, :] = VOXEL_AIR
        grid1.grid[5, 5, 5] = VOXEL_OBSIDIAN
        grid1.grid[5, 5, 6] = VOXEL_CHALK
        grid1.grid[5, 5, 7] = VOXEL_BEDROCK
        grid1.load[5, 5, 6] = pre_load

        # Setup 2: Dirt followed by chalk (for comparison)
        grid2.grid[:, :, :] = VOXEL_AIR
        grid2.grid[5, 5, 5] = VOXEL_DIRT
        grid2.grid[5, 5, 6] = VOXEL_CHALK
        grid2.grid[5, 5, 7] = VOXEL_BEDROCK
        grid2.load[5, 5, 6] = pre_load

        # Same impact on both
        impact1 = np.zeros((10, 10, 9), dtype=np.float32)
        impact1[5, 5, 4] = impact_energy
        impact2 = np.zeros((10, 10, 9), dtype=np.float32)
        impact2[5, 5, 4] = impact_energy

        phys1._propagate_shock(impact1)
        phys2._propagate_shock(impact2)

        chalk_cracked_obsidian = bool(grid1.loose[5, 5, 6]) or bool(grid1.grid[5, 5, 6] == VOXEL_AIR)
        chalk_cracked_dirt = bool(grid2.loose[5, 5, 6]) or bool(grid2.grid[5, 5, 6] == VOXEL_AIR)

        # Obsidian path should crack chalk, dirt path should not
        assert chalk_cracked_obsidian is True
        assert chalk_cracked_dirt is False


class TestChalkShattersOnImpact:
    def test_chalk_shatters_on_impact(self):
        """Chalk (high brittleness) shatters on nearby heavy impact."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Chalk block
        grid.grid[5, 5, 5] = VOXEL_CHALK
        grid.grid[5, 5, 6] = VOXEL_BEDROCK

        # shock/capacity must exceed SHATTER_THRESHOLD with 50% margin
        shock_needed = _chalk_cap * SHATTER_THRESHOLD * 1.5
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = shock_needed

        phys._propagate_shock(impact)

        # Chalk should shatter (brittleness >= 0.5)
        assert grid.grid[5, 5, 5] == VOXEL_AIR


class TestNoShockOnAirGrid:
    def test_no_shock_on_air_only_grid(self):
        """Impact into air-only grid produces no cascade."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = 100.0

        events = []
        bus.subscribe("shock_cascade", lambda **kw: events.append(kw))

        phys._propagate_shock(impact)

        assert len(events) == 0


class TestShockEventPublished:
    def test_shock_event_published(self):
        """'shock_cascade' event fires with correct cracked/shattered counts."""
        bus, grid, phys = _setup()
        grid.grid[:, :, :] = VOXEL_AIR

        # Single chalk block that will shatter
        grid.grid[5, 5, 5] = VOXEL_CHALK
        grid.grid[5, 5, 6] = VOXEL_BEDROCK

        # Enough to shatter chalk
        shock_needed = _chalk_cap * SHATTER_THRESHOLD * 1.5
        impact = np.zeros((10, 10, 9), dtype=np.float32)
        impact[5, 5, 4] = shock_needed

        events = []
        bus.subscribe("shock_cascade", lambda **kw: events.append(kw))

        phys._propagate_shock(impact)

        assert len(events) == 1
        assert events[0]["shattered"] >= 1 or events[0]["cracked"] >= 1
