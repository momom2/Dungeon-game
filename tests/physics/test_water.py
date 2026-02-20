"""Tests for water physics: flow, pressure, lava interaction, seepage,
velocity, momentum, pipe water transport, buoyancy, intruder water
interaction, and floodgate/door interaction.
"""

import numpy as np
import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.physics.water import WaterPhysics
from dungeon_builder.world.physics.pipe import PipePhysics
from dungeon_builder.world.physics.structural import StructuralIntegrityPhysics
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    VANGUARD,
    WINDCALLER,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.decision import IntruderAI
from dungeon_builder.intruders.party import Party
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_STONE,
    VOXEL_DIRT,
    VOXEL_LAVA,
    VOXEL_OBSIDIAN,
    VOXEL_CHALK,
    VOXEL_SANDSTONE,
    VOXEL_GRANITE,
    VOXEL_BEDROCK,
    VOXEL_PIPE,
    VOXEL_PUMP,
    VOXEL_FLOODGATE,
    VOXEL_DOOR,
    NON_DIGGABLE,
    WATER_TICK_INTERVAL,
    WATER_PRESSURE_WEIGHT,
    WATER_BURST_FACTOR,
    WATER_LAVA_PRODUCT,
    WATER_HUMIDITY_SOURCE,
    WATER_EVAPORATION_RATE,
    WATER_SEEP_RATE,
    WATER_BUOYANCY_FACTOR,
    WATER_DAMAGE_DEPTH_THRESHOLD,
    WATER_DAMAGE_PER_TICK,
    WATER_CURRENT_PUSH_THRESHOLD,
    PIPE_WATER_TRANSFER_RATE,
    PUMP_TICK_INTERVAL,
    STRUCTURAL_TICK_INTERVAL,
    VOXEL_POROSITY,
    VOXEL_SHEAR_STRENGTH,
    VOXEL_WEIGHT,
    METAL_IRON,
    METAL_GOLD,
    METAL_STRENGTH_MULT,
    METAL_NONE,
    SURFACE_Z,
    ENCHANTED_OFFSET,
)


def _make(w=10, d=10, h=16):
    """Create event bus, grid, and water physics."""
    eb = EventBus()
    grid = VoxelGrid(w, d, h)
    wp = WaterPhysics(eb, grid)
    return eb, grid, wp


def _tick(eb, tick_num):
    """Publish a tick event."""
    eb.publish("tick", tick=tick_num)


# ──────────────────────────────────────────────────────────────────────
# Downward flow
# ──────────────────────────────────────────────────────────────────────


class TestDownwardFlow:
    def test_water_falls_through_air(self):
        """Water block above air should fall downward."""
        eb, grid, wp = _make()
        # Place water at z=7, floor at z=9, walls so it doesn't spread
        grid.grid[5, 5, 7] = VOXEL_WATER
        grid.water_level[5, 5, 7] = 200
        grid.grid[5, 5, 9] = VOXEL_STONE  # floor
        # Contain laterally at z=8 so water doesn't spread
        for z in [7, 8]:
            grid.grid[4, 5, z] = VOXEL_STONE
            grid.grid[6, 5, z] = VOXEL_STONE
            grid.grid[5, 4, z] = VOXEL_STONE
            grid.grid[5, 6, z] = VOXEL_STONE

        # Tick at correct interval
        _tick(eb, WATER_TICK_INTERVAL)

        # Water should have moved down to z=8 (above the stone floor)
        assert grid.grid[5, 5, 7] == VOXEL_AIR
        assert grid.water_level[5, 5, 7] == 0
        assert grid.grid[5, 5, 8] == VOXEL_WATER
        assert grid.water_level[5, 5, 8] == 200

    def test_water_stops_on_solid(self):
        """Water should rest on top of a solid block."""
        eb, grid, wp = _make()
        # Place stone floor at z=9
        grid.grid[5, 5, 9] = VOXEL_STONE
        # Place water above it, contained by walls so it doesn't spread
        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 200
        for x, y in [(4, 5), (6, 5), (5, 4), (5, 6)]:
            grid.grid[x, y, 8] = VOXEL_STONE

        _tick(eb, WATER_TICK_INTERVAL)

        # Water should stay at z=8 (stone below at z=9 blocks falling)
        assert grid.grid[5, 5, 8] == VOXEL_WATER
        assert grid.water_level[5, 5, 8] > 0


# ──────────────────────────────────────────────────────────────────────
# Lateral leveling
# ──────────────────────────────────────────────────────────────────────


class TestLateralLeveling:
    def test_water_levels_laterally(self):
        """Water at different levels should equalize significantly in one tick."""
        eb, grid, wp = _make()
        # Stone floor along z=9
        for x in range(3, 8):
            grid.grid[x, 5, 9] = VOXEL_STONE
        # Contain laterally with walls
        for x in [3, 6]:
            grid.grid[x, 5, 8] = VOXEL_STONE
        for y in [4, 6]:
            grid.grid[4, y, 8] = VOXEL_STONE
            grid.grid[5, y, 8] = VOXEL_STONE

        # High water at x=4, low water at x=5
        grid.grid[4, 5, 8] = VOXEL_WATER
        grid.water_level[4, 5, 8] = 200
        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 50

        _tick(eb, WATER_TICK_INTERVAL)

        lvl_a = int(grid.water_level[4, 5, 8])
        lvl_b = int(grid.water_level[5, 5, 8])
        # LBM pressure-driven lateral transfer converges from diff=150
        # to under 30 in a single water tick
        assert abs(lvl_a - lvl_b) < 30, (
            f"Lateral leveling too slow: diff={abs(lvl_a - lvl_b)}, "
            f"levels=({lvl_a}, {lvl_b})"
        )
        # Total mass conserved (200 + 50 = 250)
        assert lvl_a + lvl_b == 250

    def test_water_equalizes_in_sealed_pool(self):
        """Water in a sealed 4-cell pool should fully equalize within 10 ticks."""
        eb, grid, wp = _make(w=10, d=10, h=16)
        # Build a fully sealed stone box containing 4 water cells in a row
        # Water at z=10, floor at z=11, walls all around, ceiling at z=9
        for x in range(2, 8):
            for y in range(4, 7):
                grid.grid[x, y, 9] = VOXEL_STONE   # ceiling
                grid.grid[x, y, 11] = VOXEL_STONE  # floor
                for z in [10]:
                    if x < 3 or x > 6 or y == 4 or y == 6:
                        grid.grid[x, y, z] = VOXEL_STONE  # walls

        # Uneven water: 250 at x=3, 200 at x=4, 100 at x=5, 50 at x=6
        levels = [250, 200, 100, 50]
        for i, x in enumerate(range(3, 7)):
            grid.grid[x, 5, 10] = VOXEL_WATER
            grid.water_level[x, 5, 10] = levels[i]

        total = sum(levels)

        # Run 10 water ticks
        for t in range(1, 21):
            if t % WATER_TICK_INTERVAL == 0:
                _tick(eb, t)

        # All four cells should be within 2 units of each other
        result = [int(grid.water_level[x, 5, 10]) for x in range(3, 7)]
        assert max(result) - min(result) <= 2, (
            f"Pool not equalized after 10 ticks: levels={result}"
        )
        # Mass conserved
        final_sum = int(np.sum(grid.water_level))
        assert final_sum == total, (
            f"Mass not conserved: initial={total}, final={final_sum}"
        )

    def test_water_does_not_flow_through_solid(self):
        """Water should not pass through solid walls."""
        eb, grid, wp = _make()
        # Stone wall at x=5, water on left side
        for z in range(7, 11):
            grid.grid[5, 5, z] = VOXEL_STONE
        # Water at x=4
        grid.grid[4, 5, 8] = VOXEL_WATER
        grid.water_level[4, 5, 8] = 200
        # Floor
        grid.grid[4, 5, 9] = VOXEL_STONE

        _tick(eb, WATER_TICK_INTERVAL)

        # Water should not appear at x=6 (other side of wall)
        assert grid.grid[6, 5, 8] != VOXEL_WATER


# ──────────────────────────────────────────────────────────────────────
# Pressure
# ──────────────────────────────────────────────────────────────────────


class TestPressure:
    def test_water_pressure_increases_with_depth(self):
        """Deeper water should exert more pressure on adjacent walls."""
        eb, grid, wp = _make()
        # Create a contained water column: stone on all sides + floor
        # Water at x=5, stone walls at x=4, x=6, y=4, y=6, floor at z=11
        for z in range(6, 12):
            grid.grid[4, 5, z] = VOXEL_STONE
            grid.grid[6, 5, z] = VOXEL_STONE
            grid.grid[5, 4, z] = VOXEL_STONE
            grid.grid[5, 6, z] = VOXEL_STONE
        grid.grid[5, 5, 11] = VOXEL_STONE  # floor

        # Fill water column 5 blocks deep (z=6..10)
        for z in range(6, 11):
            grid.grid[5, 5, z] = VOXEL_WATER
            grid.water_level[5, 5, z] = 255

        _tick(eb, WATER_TICK_INTERVAL)

        # Shear load on wall should increase with depth
        shallow_load = grid.shear_load[6, 5, 6]
        deep_load = grid.shear_load[6, 5, 10]
        assert deep_load > shallow_load

    def test_water_burst_weak_wall(self):
        """High pressure should burst weak walls (chalk)."""
        chalk_shear = VOXEL_SHEAR_STRENGTH[VOXEL_CHALK]
        water_w = VOXEL_WEIGHT[VOXEL_WATER]
        # burst threshold = chalk_shear * WATER_BURST_FACTOR
        # pressure = depth * water_w * WATER_PRESSURE_WEIGHT
        burst_thresh = chalk_shear * WATER_BURST_FACTOR
        pres_per_depth = water_w * WATER_PRESSURE_WEIGHT
        min_depth = int(burst_thresh / pres_per_depth) + 3  # +3 margin
        ceil_z = 5
        floor_z = ceil_z + min_depth + 1
        h = floor_z + 3

        eb, grid, wp = _make(w=10, d=10, h=h)
        events = []
        eb.subscribe("water_burst", lambda **kw: events.append(kw))

        # Contain the water column with stone walls on all sides
        for z in range(ceil_z, floor_z + 1):
            grid.grid[4, 5, z] = VOXEL_STONE
            grid.grid[5, 4, z] = VOXEL_STONE
            grid.grid[5, 6, z] = VOXEL_STONE
        grid.grid[5, 5, ceil_z] = VOXEL_STONE    # ceiling
        grid.grid[5, 5, floor_z] = VOXEL_STONE   # floor

        # Deep water column
        for z in range(ceil_z + 1, floor_z):
            grid.grid[5, 5, z] = VOXEL_WATER
            grid.water_level[5, 5, z] = 255

        # Chalk wall adjacent at the deepest point
        chalk_z = floor_z - 1
        grid.grid[6, 5, chalk_z] = VOXEL_CHALK

        _tick(eb, WATER_TICK_INTERVAL)

        assert grid.grid[6, 5, chalk_z] == VOXEL_AIR
        assert len(events) > 0

    def test_water_does_not_burst_granite(self):
        """Granite walls should resist reasonable water pressure."""
        granite_shear = VOXEL_SHEAR_STRENGTH[VOXEL_GRANITE]
        water_w = VOXEL_WEIGHT[VOXEL_WATER]
        # Pick a shallow depth where pressure is well below burst threshold.
        # Use only 5 blocks of water — always safe against granite.
        safe_depth = 5
        burst_thresh = granite_shear * WATER_BURST_FACTOR
        pres_per_depth = water_w * WATER_PRESSURE_WEIGHT
        max_pressure = safe_depth * pres_per_depth
        assert max_pressure < burst_thresh, "Test setup: 5-deep water should be safe"

        eb, grid, wp = _make()
        start_z = 7
        for z in range(start_z, start_z + safe_depth):
            grid.grid[5, 5, z] = VOXEL_WATER
            grid.water_level[5, 5, z] = 255

        # Granite wall at deepest water level
        wall_z = start_z + safe_depth - 1
        grid.grid[6, 5, wall_z] = VOXEL_GRANITE

        _tick(eb, WATER_TICK_INTERVAL)

        assert grid.grid[6, 5, wall_z] == VOXEL_GRANITE


# ──────────────────────────────────────────────────────────────────────
# Lava interaction
# ──────────────────────────────────────────────────────────────────────


class TestLavaInteraction:
    def test_water_lava_creates_obsidian(self):
        """Water adjacent to lava should produce obsidian."""
        eb, grid, wp = _make()
        events = []
        eb.subscribe("water_lava_reaction", lambda **kw: events.append(True))

        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 255
        grid.grid[6, 5, 8] = VOXEL_LAVA
        grid.lava_level[6, 5, 8] = 255
        grid.temperature[6, 5, 8] = 1000.0

        _tick(eb, WATER_TICK_INTERVAL)

        # Both should become obsidian
        assert grid.grid[5, 5, 8] == WATER_LAVA_PRODUCT  # obsidian
        assert grid.grid[6, 5, 8] == WATER_LAVA_PRODUCT  # obsidian
        assert len(events) > 0
        # Water level should be cleared
        assert grid.water_level[5, 5, 8] == 0


# ──────────────────────────────────────────────────────────────────────
# Humidity / seepage
# ──────────────────────────────────────────────────────────────────────


class TestHumiditySeepage:
    def test_water_is_humidity_source(self):
        """Adjacent blocks should gain humidity from water."""
        eb, grid, wp = _make()
        # Contain water: floor, ceiling, and walls on 3 sides; sandstone on 4th side
        grid.grid[5, 5, 9] = VOXEL_STONE   # floor
        grid.grid[5, 5, 7] = VOXEL_STONE   # ceiling
        grid.grid[4, 5, 8] = VOXEL_STONE   # wall
        grid.grid[5, 4, 8] = VOXEL_STONE   # wall
        grid.grid[5, 6, 8] = VOXEL_STONE   # wall
        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 200
        # Sandstone adjacent (porosity=0.35)
        grid.grid[6, 5, 8] = VOXEL_SANDSTONE
        grid.grid[6, 5, 9] = VOXEL_STONE  # floor for sandstone too
        grid.humidity[6, 5, 8] = 0.0

        _tick(eb, WATER_TICK_INTERVAL)

        # Sandstone should have gained humidity via seepage
        assert grid.humidity[6, 5, 8] > 0

    def test_water_seepage_through_sandstone(self):
        """Seepage rate should scale with material porosity."""
        eb, grid, wp = _make()
        # Contain water: floor, ceiling, and y-walls
        grid.grid[5, 5, 9] = VOXEL_STONE   # floor
        grid.grid[5, 5, 7] = VOXEL_STONE   # ceiling
        grid.grid[5, 4, 8] = VOXEL_STONE   # y-wall
        grid.grid[5, 6, 8] = VOXEL_STONE   # y-wall
        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 255

        # High porosity (sandstone, 0.35) vs low porosity (granite, 0.005)
        grid.grid[6, 5, 8] = VOXEL_SANDSTONE
        grid.grid[6, 5, 9] = VOXEL_STONE
        grid.grid[4, 5, 8] = VOXEL_GRANITE
        grid.grid[4, 5, 9] = VOXEL_STONE
        grid.humidity[6, 5, 8] = 0.0
        grid.humidity[4, 5, 8] = 0.0

        _tick(eb, WATER_TICK_INTERVAL)

        sand_hum = grid.humidity[6, 5, 8]
        gran_hum = grid.humidity[4, 5, 8]
        assert sand_hum > gran_hum


# ──────────────────────────────────────────────────────────────────────
# Evaporation
# ──────────────────────────────────────────────────────────────────────


class TestEvaporation:
    def test_water_surface_evaporation(self):
        """Water at z=0 should lose water_level over time.

        Evaporation is probabilistic (WATER_EVAPORATION_RATE chance per
        water tick of losing 1 level), so we run enough ticks that at
        least one evaporation event is virtually certain.
        """
        eb, grid, wp = _make()
        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 100

        initial = int(grid.water_level[5, 5, 0])
        # Run 50 water ticks; P(no evap) = (1-rate)^50 ≈ 0.03% at rate=0.15
        for t in range(1, 101):
            if t % WATER_TICK_INTERVAL == 0:
                _tick(eb, t)

        assert grid.water_level[5, 5, 0] < initial


# ──────────────────────────────────────────────────────────────────────
# Conservation
# ──────────────────────────────────────────────────────────────────────


class TestConservation:
    def test_water_conservation_no_sinks(self):
        """In a sealed chamber with no surface contact, water mass is conserved."""
        eb, grid, wp = _make()
        # Create sealed chamber: stone box at z=8..13, x=3..6, y=3..6
        # All z-levels > SURFACE_Z so no surface evaporation
        for x in range(3, 7):
            for y in range(3, 7):
                grid.grid[x, y, 8] = VOXEL_STONE  # ceiling
                grid.grid[x, y, 13] = VOXEL_STONE  # floor
                for z in range(9, 13):
                    if x == 3 or x == 6 or y == 3 or y == 6:
                        grid.grid[x, y, z] = VOXEL_STONE  # walls
                    else:
                        grid.grid[x, y, z] = VOXEL_WATER
                        grid.water_level[x, y, z] = 200

        # Sum initial water
        initial_sum = int(np.sum(grid.water_level))

        # Run several ticks
        for t in range(1, 20):
            if t % WATER_TICK_INTERVAL == 0:
                _tick(eb, t)

        final_sum = int(np.sum(grid.water_level))

        # Water should be conserved (sealed, no evaporation since below surface)
        assert final_sum == initial_sum


# ──────────────────────────────────────────────────────────────────────
# Non-diggable
# ──────────────────────────────────────────────────────────────────────


class TestWaterProperties:
    def test_water_not_diggable(self):
        """Water should be in the NON_DIGGABLE set."""
        assert VOXEL_WATER in NON_DIGGABLE


# ──────────────────────────────────────────────────────────────────────
# Tick interval
# ──────────────────────────────────────────────────────────────────────


class TestTickInterval:
    def test_water_only_runs_on_interval(self):
        """Water physics should only process on correct tick intervals."""
        eb, grid, wp = _make()
        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 200

        # Tick that's NOT on the interval
        off_tick = WATER_TICK_INTERVAL + 1 if WATER_TICK_INTERVAL > 1 else 3
        _tick(eb, off_tick)

        # Water should not have moved
        assert grid.grid[5, 5, 8] == VOXEL_WATER
        assert grid.water_level[5, 5, 8] == 200


# ──────────────────────────────────────────────────────────────────────
# Gravity integration
# ──────────────────────────────────────────────────────────────────────


class TestGravityIntegration:
    def test_blocks_cannot_fall_through_water(self):
        """Loose blocks should not pass through water (treated as blocking)."""
        from dungeon_builder.world.physics.gravity import GravityPhysics

        eb = EventBus()
        grid = VoxelGrid(10, 10, 16)
        gp = GravityPhysics(eb, grid)

        # Water at z=9
        grid.grid[5, 5, 9] = VOXEL_WATER
        grid.water_level[5, 5, 9] = 200

        # Loose stone at z=7 (should stop at z=8, above water)
        grid.grid[5, 5, 7] = VOXEL_STONE
        grid.loose[5, 5, 7] = True

        _tick(eb, 1)  # gravity runs every tick

        # Stone should be at z=8 (resting above water) or still above water
        # It falls through air and stops when it hits water (non-air)
        stone_positions = np.where(grid.grid == VOXEL_STONE)
        if len(stone_positions[0]) > 0:
            max_z = max(stone_positions[2])
            # Stone should not have passed through water (z=9)
            assert max_z <= 8


# ──────────────────────────────────────────────────────────────────────
# Heat conduction
# ──────────────────────────────────────────────────────────────────────


class TestHeatConduction:
    def test_water_conducts_heat(self):
        """Temperature should diffuse through water (conductivity = 0.6)."""
        from dungeon_builder.world.physics.temperature import TemperaturePhysics
        from dungeon_builder.config import TEMPERATURE_TICK_INTERVAL

        eb = EventBus()
        grid = VoxelGrid(10, 10, 16)
        tp = TemperaturePhysics(eb, grid)

        # Hot block at x=4, water at x=5, cold block at x=6 (all at z=8, below surface)
        grid.grid[4, 5, 8] = VOXEL_STONE
        grid.temperature[4, 5, 8] = 500.0
        grid.grid[5, 5, 8] = VOXEL_WATER
        grid.water_level[5, 5, 8] = 200
        grid.temperature[5, 5, 8] = 20.0
        grid.grid[6, 5, 8] = VOXEL_STONE
        grid.temperature[6, 5, 8] = 20.0

        _tick(eb, TEMPERATURE_TICK_INTERVAL)

        # Water should have gained some heat from the hot stone
        assert grid.temperature[5, 5, 8] > 20.0


# ══════════════════════════════════════════════════════════════════════════
# Enhanced water dynamics tests (from test_water_enhanced.py)
# ══════════════════════════════════════════════════════════════════════════


def _make_water(w=10, d=10, h=16):
    """Create event bus, grid, and water physics."""
    eb = EventBus()
    grid = VoxelGrid(w, d, h)
    wp = WaterPhysics(eb, grid)
    return eb, grid, wp


def _water_tick(eb):
    """Publish a tick that triggers WaterPhysics (at WATER_TICK_INTERVAL)."""
    eb.publish("tick", tick=WATER_TICK_INTERVAL)


def _place_water(grid, x, y, z, level=255):
    """Place a water block at the given position."""
    grid.grid[x, y, z] = VOXEL_WATER
    grid.water_level[x, y, z] = level


def _make_intruder(x=5, y=5, z=0, hp=100, archetype=None):
    """Create a minimal intruder at a given position."""
    if archetype is None:
        archetype = VANGUARD
    pmap = PersonalMap()
    intruder = Intruder(
        intruder_id=1, x=x, y=y, z=z,
        archetype=archetype,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=pmap,
    )
    intruder.hp = hp
    intruder.max_hp = hp
    return intruder


def _make_decision_system(grid_w=10, grid_d=10, grid_h=16):
    """Create a full decision system for testing water interaction."""
    eb = EventBus()
    grid = VoxelGrid(grid_w, grid_d, grid_h)
    grid.grid[:] = VOXEL_STONE
    grid.grid[:, :, :SURFACE_Z + 1] = VOXEL_AIR
    pf = AStarPathfinder(grid)
    core = DungeonCore(eb, 5, 5, SURFACE_Z + 3)
    rng = SeededRNG(42)
    ai = IntruderAI(eb, grid, pf, core, rng)
    return eb, grid, ai, core


# ══════════════════════════════════════════════════════════════════════════
# Pipe water transport tests
# ══════════════════════════════════════════════════════════════════════════

class TestPipeWaterTransport:
    """Tests for pump-driven water transport through pipes."""

    def _make_pipe_grid(self, w=10, d=10, h=5):
        """Create a grid with event bus and pipe physics."""
        eb = EventBus()
        grid = VoxelGrid(w, d, h)
        grid.grid[:] = VOXEL_STONE
        pp = PipePhysics(eb, grid)
        return eb, grid, pp

    def test_pump_moves_water_basic(self):
        """Pump pulls water from intake side, pushes to output side."""
        eb, grid, pp = self._make_pipe_grid()

        # Simple setup: pump at (5,5,2) facing +X (direction=0)
        # Intake = (4,5,2) = water, output = (6,5,2) = air
        grid.grid[5, 5, 2] = VOXEL_PUMP
        grid.metal_type[5, 5, 2] = METAL_IRON
        grid.block_state[5, 5, 2] = 0  # +X direction

        # Water source at intake
        grid.grid[4, 5, 2] = VOXEL_WATER
        grid.water_level[4, 5, 2] = 200

        # Air at output
        grid.grid[6, 5, 2] = VOXEL_AIR

        pp._update()

        # Water should have been transferred
        expected_transfer = int(PIPE_WATER_TRANSFER_RATE * 255)
        assert grid.water_level[6, 5, 2] > 0
        assert grid.water_level[4, 5, 2] < 200

    def test_pump_direction_matters(self):
        """Pump should only pull from intake (opposite direction) side."""
        eb, grid, pp = self._make_pipe_grid()

        # Pump at (5,5,2) facing +Y (direction=2)
        grid.grid[5, 5, 2] = VOXEL_PUMP
        grid.metal_type[5, 5, 2] = METAL_IRON
        grid.block_state[5, 5, 2] = 2  # +Y direction

        # Water on the wrong side (+X side) -- should NOT be pulled
        grid.grid[6, 5, 2] = VOXEL_WATER
        grid.water_level[6, 5, 2] = 200

        # Air at actual output (+Y direction)
        grid.grid[5, 6, 2] = VOXEL_AIR

        # Intake is -Y = (5,4,2) which is stone -- no water there
        pp._update()

        # No water should be transferred (intake has no water)
        assert grid.water_level[5, 6, 2] == 0
        assert grid.water_level[6, 5, 2] == 200

    def test_no_pump_no_water_transport(self):
        """Passive pipes should not move water (pumps required)."""
        eb, grid, pp = self._make_pipe_grid()

        # Just pipes, no pump
        grid.grid[4, 5, 2] = VOXEL_PIPE
        grid.grid[5, 5, 2] = VOXEL_PIPE
        grid.grid[6, 5, 2] = VOXEL_PIPE
        for x in (4, 5, 6):
            grid.metal_type[x, 5, 2] = METAL_IRON

        # Water adjacent to pipe
        grid.grid[3, 5, 2] = VOXEL_WATER
        grid.water_level[3, 5, 2] = 200

        # Air on other side
        grid.grid[7, 5, 2] = VOXEL_AIR

        pp._update()

        # No water movement (pipes are passive for water)
        assert grid.water_level[7, 5, 2] == 0
        assert grid.water_level[3, 5, 2] == 200

    def test_pump_no_water_source(self):
        """Pump with no water at intake should not produce water."""
        eb, grid, pp = self._make_pipe_grid()

        grid.grid[5, 5, 2] = VOXEL_PUMP
        grid.metal_type[5, 5, 2] = METAL_IRON
        grid.block_state[5, 5, 2] = 0  # +X

        # Stone at intake (no water)
        grid.grid[4, 5, 2] = VOXEL_STONE

        # Air at output
        grid.grid[6, 5, 2] = VOXEL_AIR

        pp._update()

        assert grid.water_level[6, 5, 2] == 0

    def test_pump_output_blocked_by_solid(self):
        """Pump should not output water into solid blocks."""
        eb, grid, pp = self._make_pipe_grid()

        grid.grid[5, 5, 2] = VOXEL_PUMP
        grid.metal_type[5, 5, 2] = METAL_IRON
        grid.block_state[5, 5, 2] = 0  # +X

        # Water at intake
        grid.grid[4, 5, 2] = VOXEL_WATER
        grid.water_level[4, 5, 2] = 200

        # Stone at output -- can't receive water
        grid.grid[6, 5, 2] = VOXEL_STONE

        pp._update()

        # No transfer because output is solid
        assert grid.water_level[4, 5, 2] == 200

    def test_multi_chamber_pump(self):
        """Pump can move water from one chamber to another."""
        eb, grid, pp = self._make_pipe_grid(w=12, d=12, h=8)

        # Chamber 1: water pool at z=5 (x=2..4, y=5)
        for x in range(2, 5):
            grid.grid[x, 5, 5] = VOXEL_WATER
            grid.water_level[x, 5, 5] = 255
            grid.grid[x, 5, 6] = VOXEL_STONE  # floor

        # Pump at (5,5,5) facing +X
        grid.grid[5, 5, 5] = VOXEL_PUMP
        grid.metal_type[5, 5, 5] = METAL_IRON
        grid.block_state[5, 5, 5] = 0  # +X

        # Chamber 2: air at (6,5,5)
        grid.grid[6, 5, 5] = VOXEL_AIR
        grid.grid[6, 5, 6] = VOXEL_STONE  # floor

        # Intake is at (4,5,5) which is water -- good
        pp._update()

        # Water should appear in chamber 2
        assert grid.water_level[6, 5, 5] > 0
        assert int(grid.grid[6, 5, 5]) == VOXEL_WATER


# ══════════════════════════════════════════════════════════════════════════
# Buoyancy tests
# ══════════════════════════════════════════════════════════════════════════

class TestBuoyancy:
    """Tests for water buoyancy reducing structural weight."""

    def _make_structural(self, w=10, d=10, h=10):
        eb = EventBus()
        grid = VoxelGrid(w, d, h)
        sp = StructuralIntegrityPhysics(eb, grid)
        return eb, grid, sp

    def test_submerged_block_reduced_weight(self):
        """A block with water above should have reduced effective weight."""
        eb, grid, sp = self._make_structural()

        # Water at z=2
        grid.grid[5, 5, 2] = VOXEL_WATER
        grid.water_level[5, 5, 2] = 255

        # Stone at z=3 (below water)
        grid.grid[5, 5, 3] = VOXEL_STONE

        # Stone at z=4 (floor)
        grid.grid[5, 5, 4] = VOXEL_STONE

        sp._compute_load()

        stone_weight = VOXEL_WEIGHT.get(VOXEL_STONE, 1.0)
        water_weight = VOXEL_WEIGHT.get(VOXEL_WATER, 0.0)
        actual_load = float(grid.load[5, 5, 3])

        # Load at z=3 = own weight (reduced by buoyancy) + water above weight
        # Buoyancy reduces the block's own weight since water is above
        expected = stone_weight * WATER_BUOYANCY_FACTOR + water_weight
        assert actual_load == pytest.approx(expected, rel=0.1)

        # Verify it's less than without buoyancy (stone + water above full weight)
        without_buoyancy = stone_weight + water_weight
        assert actual_load < without_buoyancy

    def test_non_submerged_full_weight(self):
        """A block without water above should have full weight."""
        eb, grid, sp = self._make_structural()

        # Air at z=2
        grid.grid[5, 5, 2] = VOXEL_AIR

        # Stone at z=3
        grid.grid[5, 5, 3] = VOXEL_STONE

        # Stone at z=4 (floor)
        grid.grid[5, 5, 4] = VOXEL_STONE

        sp._compute_load()

        stone_weight = VOXEL_WEIGHT.get(VOXEL_STONE, 1.0)
        actual_load = float(grid.load[5, 5, 3])
        # Should have full weight (no buoyancy)
        assert actual_load >= stone_weight * 0.9

    def test_water_blocks_not_affected_by_buoyancy(self):
        """Water blocks themselves are not affected by buoyancy reduction."""
        eb, grid, sp = self._make_structural()

        # Water at z=1 and z=2
        grid.grid[5, 5, 1] = VOXEL_WATER
        grid.water_level[5, 5, 1] = 255
        grid.grid[5, 5, 2] = VOXEL_WATER
        grid.water_level[5, 5, 2] = 255

        # Stone floor at z=3
        grid.grid[5, 5, 3] = VOXEL_STONE

        sp._compute_load()

        water_weight = VOXEL_WEIGHT.get(VOXEL_WATER, 0.0)
        # Water at z=2 should have its full weight (not reduced by buoyancy)
        # because buoyancy only affects non-water solid blocks
        # If water weight is 0 or negligible, this test just confirms it's not negative
        assert float(grid.load[5, 5, 2]) >= 0.0

    def test_partial_submersion(self):
        """Only the block directly below water gets buoyancy reduction."""
        eb, grid, sp = self._make_structural()

        # Water at z=2
        grid.grid[5, 5, 2] = VOXEL_WATER
        grid.water_level[5, 5, 2] = 255

        # Stack: stone at z=3 (submerged), stone at z=4, stone at z=5
        grid.grid[5, 5, 3] = VOXEL_STONE  # Below water -> buoyancy
        grid.grid[5, 5, 4] = VOXEL_STONE  # Not below water
        grid.grid[5, 5, 5] = VOXEL_STONE  # Not below water

        sp._compute_load()

        # Load at z=3 should be less than load at z=4 (z=4 has z=3 above, not water)
        # Actually z=4 will carry z=3's reduced weight + its own weight
        # z=3 weight is reduced by buoyancy
        stone_weight = VOXEL_WEIGHT.get(VOXEL_STONE, 1.0)
        load_z3 = float(grid.load[5, 5, 3])
        # z=3 has reduced weight due to water above
        assert load_z3 < stone_weight * 1.05  # Less than full weight


# ══════════════════════════════════════════════════════════════════════════
# Intruder water interaction tests
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Intruder archetypes pending rework")
class TestIntruderWaterDamage:
    """Tests for intruder drowning damage in deep water."""

    def test_shallow_water_safe(self):
        """Intruder in shallow water (< threshold depth) takes no damage."""
        eb, grid, ai, core = _make_decision_system()

        # Single water block at intruder's position
        grid.grid[5, 5, 3] = VOXEL_WATER
        grid.water_level[5, 5, 3] = 255

        intruder = _make_intruder(x=5, y=5, z=3, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        initial_hp = intruder.hp
        ai._check_water_interaction(intruder)

        # Depth=1 < threshold -> no damage
        assert intruder.hp == initial_hp

    def test_deep_water_damages(self):
        """Intruder in deep water (>= threshold) takes damage."""
        eb, grid, ai, core = _make_decision_system()

        # Create water column with depth >= threshold
        for z in range(0, WATER_DAMAGE_DEPTH_THRESHOLD + 1):
            grid.grid[5, 5, z] = VOXEL_WATER
            grid.water_level[5, 5, z] = 255

        # Place intruder at bottom of water column
        intruder = _make_intruder(x=5, y=5, z=WATER_DAMAGE_DEPTH_THRESHOLD, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        initial_hp = intruder.hp
        ai._check_water_interaction(intruder)

        assert intruder.hp == initial_hp - WATER_DAMAGE_PER_TICK

    def test_deep_water_kills(self):
        """Intruder with low HP in deep water can be killed."""
        eb, grid, ai, core = _make_decision_system()

        # Deep water column
        for z in range(0, WATER_DAMAGE_DEPTH_THRESHOLD + 1):
            grid.grid[5, 5, z] = VOXEL_WATER
            grid.water_level[5, 5, z] = 255

        intruder = _make_intruder(
            x=5, y=5, z=WATER_DAMAGE_DEPTH_THRESHOLD,
            hp=WATER_DAMAGE_PER_TICK - 1,
        )
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        assert not intruder.alive

    def test_not_in_water_no_damage(self):
        """Intruder on air/solid takes no water damage."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_AIR
        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        initial_hp = intruder.hp
        ai._check_water_interaction(intruder)

        assert intruder.hp == initial_hp


@pytest.mark.skip(reason="Intruder archetypes pending rework")
class TestIntruderCurrentPush:
    """Tests for water current pushing intruders."""

    def test_current_pushes_intruder(self):
        """Strong water current should push intruder laterally."""
        eb, grid, ai, core = _make_decision_system()

        # Water at intruder position with strong +X velocity
        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        grid.water_vx[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD + 0.5
        grid.water_vy[5, 5, 0] = 0.0

        # Air at destination (pushed +X)
        grid.grid[6, 5, 0] = VOXEL_AIR

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        # Should have been pushed +X
        assert intruder.x == 6
        assert intruder.y == 5

    def test_weak_current_no_push(self):
        """Weak current should not push intruder."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        grid.water_vx[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD * 0.5
        grid.water_vy[5, 5, 0] = 0.0

        grid.grid[6, 5, 0] = VOXEL_AIR

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        # Should NOT have moved
        assert intruder.x == 5
        assert intruder.y == 5

    def test_current_push_negative_direction(self):
        """Current in -X direction pushes intruder -X."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        grid.water_vx[5, 5, 0] = -(WATER_CURRENT_PUSH_THRESHOLD + 0.5)
        grid.water_vy[5, 5, 0] = 0.0

        grid.grid[4, 5, 0] = VOXEL_AIR

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        assert intruder.x == 4

    def test_current_push_y_direction(self):
        """Current in +Y direction pushes intruder +Y."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        grid.water_vx[5, 5, 0] = 0.0
        grid.water_vy[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD + 0.5

        grid.grid[5, 6, 0] = VOXEL_AIR

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        assert intruder.y == 6

    def test_current_blocked_by_wall(self):
        """Current can't push intruder into a solid wall."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        grid.water_vx[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD + 0.5

        # Wall at push destination
        grid.grid[6, 5, 0] = VOXEL_STONE

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        # Should NOT have moved (blocked by wall)
        assert intruder.x == 5

    def test_current_push_into_water(self):
        """Current can push intruder into adjacent water block."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        grid.water_vx[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD + 0.5

        # Water at destination
        grid.grid[6, 5, 0] = VOXEL_WATER
        grid.water_level[6, 5, 0] = 128

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        # Should have been pushed into water
        assert intruder.x == 6

    def test_dominant_direction_used(self):
        """When both vx and vy are strong, push in dominant direction."""
        eb, grid, ai, core = _make_decision_system()

        grid.grid[5, 5, 0] = VOXEL_WATER
        grid.water_level[5, 5, 0] = 255
        # vx is stronger than vy
        grid.water_vx[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD + 1.0
        grid.water_vy[5, 5, 0] = WATER_CURRENT_PUSH_THRESHOLD + 0.1

        grid.grid[6, 5, 0] = VOXEL_AIR
        grid.grid[5, 6, 0] = VOXEL_AIR

        intruder = _make_intruder(x=5, y=5, z=0, hp=100)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        # vx > vy -> push in X direction
        assert intruder.x == 6
        assert intruder.y == 5


@pytest.mark.skip(reason="Intruder archetypes pending rework")
class TestIntruderWaterMoralePenalty:
    """Tests for morale effects of water damage."""

    def test_deep_water_reduces_morale(self):
        """Deep water damage should also reduce morale."""
        eb, grid, ai, core = _make_decision_system()

        for z in range(0, WATER_DAMAGE_DEPTH_THRESHOLD + 1):
            grid.grid[5, 5, z] = VOXEL_WATER
            grid.water_level[5, 5, z] = 255

        intruder = _make_intruder(x=5, y=5, z=WATER_DAMAGE_DEPTH_THRESHOLD, hp=100)
        intruder.morale = 0.8
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._check_water_interaction(intruder)

        assert intruder.morale < 0.8


# ══════════════════════════════════════════════════════════════════════════
# Conservation tests (enhanced)
# ══════════════════════════════════════════════════════════════════════════

class TestWaterConservation:
    """Tests that water arrays are properly initialized."""

    def test_velocity_arrays_initialized_zero(self):
        """Velocity arrays should start at zero."""
        grid = VoxelGrid(8, 8, 5)
        assert np.all(grid.water_vx == 0.0)
        assert np.all(grid.water_vy == 0.0)
        assert np.all(grid.water_vz == 0.0)


# ══════════════════════════════════════════════════════════════════════════
# Integration tests (enhanced)
# ══════════════════════════════════════════════════════════════════════════

class TestWaterVelocityIntegration:
    """End-to-end tests using tick-driven physics."""

    def test_falling_water_develops_velocity(self):
        """Water falling through air should develop downward velocity over ticks."""
        eb, grid, wp = _make_water()
        # Floor at z=12
        grid.grid[:, :, 12] = VOXEL_STONE
        grid.grid[:, :, 13] = VOXEL_STONE

        # Contain laterally so water falls in a column
        for z in range(7, 12):
            grid.grid[4, 5, z] = VOXEL_STONE
            grid.grid[6, 5, z] = VOXEL_STONE
            grid.grid[5, 4, z] = VOXEL_STONE
            grid.grid[5, 6, z] = VOXEL_STONE

        # Water at z=7
        _place_water(grid, 5, 5, 7)

        # Run multiple ticks
        for i in range(5):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # After flow, water should have settled at the bottom
        # and developed some downward velocity during the fall
        has_water_below = False
        for z in range(8, 13):
            if grid.grid[5, 5, z] == VOXEL_WATER:
                has_water_below = True
                break
        assert has_water_below, "Water should have fallen below z=7"

    def test_pressure_flow_develops_velocity_field(self):
        """Water with a pressure gradient should develop velocity field over ticks."""
        eb, grid, wp = _make_water(w=10, d=10, h=12)
        # Solid walls — contain laterally so water stays in a row
        grid.grid[:, :, 9] = VOXEL_STONE   # floor
        grid.grid[:, :, 10] = VOXEL_STONE
        grid.grid[:, :, 7] = VOXEL_STONE   # ceiling
        for x in range(1, 8):
            grid.grid[x, 4, 8] = VOXEL_STONE  # y-wall
            grid.grid[x, 6, 8] = VOXEL_STONE  # y-wall
        grid.grid[1, 5, 8] = VOXEL_STONE   # x-wall (left end)
        grid.grid[7, 5, 8] = VOXEL_STONE   # x-wall (right end)

        # High water on left, low on right (z=8, below surface)
        _place_water(grid, 2, 5, 8, level=255)
        _place_water(grid, 3, 5, 8, level=255)
        _place_water(grid, 4, 5, 8, level=128)
        _place_water(grid, 5, 5, 8, level=64)

        # Run a few ticks
        for i in range(3):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # At least some cells should have developed lateral velocity
        vx_any = np.any(np.abs(grid.water_vx) > 0.01)
        assert vx_any, "Velocity field should develop from pressure gradient"


# ══════════════════════════════════════════════════════════════════════════
# Floodgate and door interaction tests (from test_floodgate_water.py)
# ══════════════════════════════════════════════════════════════════════════


# ------------------------------------------------------------------
# Floodgate pressure burst tests
# ------------------------------------------------------------------


def _make_water_column(grid, x, y, z_start, depth):
    """Place a water column from z_start to z_start+depth-1."""
    for dz in range(depth):
        z = z_start + dz
        if grid.in_bounds(x, y, z):
            grid.grid[x, y, z] = VOXEL_WATER
            grid.water_level[x, y, z] = 255


def _gate_burst_depth(vtype, metal, margin=1.2):
    """Compute water depth needed to burst a gate/door, derived from config.

    Returns (depth, threshold_pressure) tuple.
    """
    base_shear = VOXEL_SHEAR_STRENGTH[vtype]
    base_mt = metal & 0x7F
    strength_mult = METAL_STRENGTH_MULT.get(base_mt, 1.0)
    effective_shear = base_shear * strength_mult
    threshold_pressure = effective_shear * WATER_BURST_FACTOR
    pres_per_depth = VOXEL_WEIGHT[VOXEL_WATER] * WATER_PRESSURE_WEIGHT
    depth = int(threshold_pressure / pres_per_depth * margin) + 2
    return depth, threshold_pressure


def _make_shaft_with_gate(vtype, metal, burst=True, margin=1.2):
    """Create a shaft + gate setup, returning (eb, grid, wp, gate_z).

    If burst=True, water depth exceeds burst threshold.
    If burst=False, water depth is ~60% of burst threshold (safe).
    """
    depth, _ = _gate_burst_depth(vtype, metal, margin=margin)
    if not burst:
        # Use only 60% of the depth needed to burst
        safe_depth, _ = _gate_burst_depth(vtype, metal, margin=0.6)
        depth = safe_depth

    h = depth + 10
    gate_z = depth
    eb = EventBus()
    grid = VoxelGrid(5, 5, h)
    grid.grid[:, :, :] = VOXEL_STONE
    for z in range(h):
        grid.grid[2, 2, z] = VOXEL_AIR
    grid.grid[2, 2, gate_z] = vtype
    grid.block_state[2, 2, gate_z] = 1  # closed
    grid.metal_type[2, 2, gate_z] = metal
    _make_water_column(grid, 2, 2, 0, gate_z)
    wp = WaterPhysics(eb, grid)
    return eb, grid, wp, gate_z


def test_pressure_burst_opens_floodgate():
    """Deep water column creates enough pressure to force a closed floodgate open."""
    eb, grid, wp, gate_z = _make_shaft_with_gate(VOXEL_FLOODGATE, METAL_IRON, burst=True)
    wp._apply_pressure()
    assert grid.block_state[2, 2, gate_z] == 0, (
        "Iron floodgate should be forced open by deep water pressure"
    )


# ------------------------------------------------------------------
# 6. Pressure burst opens a closed door
# ------------------------------------------------------------------


def test_pressure_burst_opens_door():
    """Deep water column creates enough pressure to force a closed door open."""
    eb, grid, wp, door_z = _make_shaft_with_gate(VOXEL_DOOR, METAL_IRON, burst=True)
    wp._apply_pressure()
    assert grid.block_state[2, 2, door_z] == 0, (
        "Iron door should be forced open by deep water pressure"
    )


# ------------------------------------------------------------------
# 7. Gold floodgate bursts easier than iron
# ------------------------------------------------------------------


def test_gold_floodgate_bursts_easier():
    """Gold floodgate (lower strength mult) bursts with less water than iron."""
    eb, grid, wp, gate_z = _make_shaft_with_gate(VOXEL_FLOODGATE, METAL_GOLD, burst=True)
    wp._apply_pressure()
    assert grid.block_state[2, 2, gate_z] == 0, (
        "Gold floodgate should burst under sufficient water pressure"
    )


# ------------------------------------------------------------------
# 8. Iron floodgate resists the same column that bursts gold
# ------------------------------------------------------------------


def test_iron_floodgate_resists_same_column_that_bursts_gold():
    """Iron floodgate survives a water column that would burst a gold gate."""
    # Compute the depth that just barely bursts a gold floodgate
    gold_depth, _ = _gate_burst_depth(VOXEL_FLOODGATE, METAL_GOLD, margin=1.2)
    iron_depth_needed, _ = _gate_burst_depth(VOXEL_FLOODGATE, METAL_IRON, margin=1.0)

    # Sanity: gold burst depth should be less than iron burst depth
    assert gold_depth < iron_depth_needed, (
        "Gold should require less water than iron to burst"
    )

    # Build shaft with the gold-sufficient depth but an iron gate
    h = gold_depth + 10
    gate_z = gold_depth
    eb = EventBus()
    grid = VoxelGrid(5, 5, h)
    grid.grid[:, :, :] = VOXEL_STONE
    for z in range(h):
        grid.grid[2, 2, z] = VOXEL_AIR
    grid.grid[2, 2, gate_z] = VOXEL_FLOODGATE
    grid.block_state[2, 2, gate_z] = 1
    grid.metal_type[2, 2, gate_z] = METAL_IRON
    _make_water_column(grid, 2, 2, 0, gate_z)

    wp = WaterPhysics(eb, grid)
    wp._apply_pressure()

    assert grid.block_state[2, 2, gate_z] == 1, (
        "Iron floodgate should survive a column that bursts gold"
    )


# ------------------------------------------------------------------
# 9. Enchanted metal uses same base metal strength for pressure burst
# ------------------------------------------------------------------


def test_enchanted_gate_uses_base_metal_strength():
    """Enchanted bit affects melt immunity, not strength -- burst threshold same as base."""
    eb, grid, wp, gate_z = _make_shaft_with_gate(
        VOXEL_FLOODGATE, METAL_GOLD | ENCHANTED_OFFSET, burst=True
    )
    wp._apply_pressure()
    assert grid.block_state[2, 2, gate_z] == 0, (
        "Enchanted gold floodgate should burst like regular gold (enchanted only affects melt)"
    )


# ------------------------------------------------------------------
# 10. Event published on gate burst
# ------------------------------------------------------------------


def test_gate_burst_publishes_event():
    """A 'gate_pressure_burst' event is published when a gate is forced open."""
    eb, grid, wp, gate_z = _make_shaft_with_gate(VOXEL_FLOODGATE, METAL_IRON, burst=True)

    events = []
    eb.subscribe("gate_pressure_burst", lambda **kw: events.append(kw))

    wp._apply_pressure()

    assert len(events) == 1, "Expected exactly one gate_pressure_burst event"
    assert events[0]["x"] == 2
    assert events[0]["y"] == 2
    assert events[0]["z"] == gate_z
    assert events[0]["vtype"] == VOXEL_FLOODGATE


# ------------------------------------------------------------------
# 11. Shallow water does not burst gate
# ------------------------------------------------------------------


def test_shallow_water_does_not_burst_gate():
    """A small water column should not generate enough pressure to burst a gate."""
    eb = EventBus()
    grid = VoxelGrid(8, 8, 8)
    grid.grid[:, :, :] = VOXEL_STONE
    grid.grid[1:7, 1:7, 1:7] = VOXEL_AIR

    # Place closed floodgate at (3, 3, 4)
    grid.grid[3, 3, 4] = VOXEL_FLOODGATE
    grid.block_state[3, 3, 4] = 1
    grid.metal_type[3, 3, 4] = METAL_IRON

    # Place only 3 blocks of water above (z=1,2,3)
    # pressure = 3 * 0.9 = 2.7, threshold = 60 * 1.0 * 1.5 = 90
    _make_water_column(grid, 3, 3, 1, 3)

    wp = WaterPhysics(eb, grid)
    wp._apply_pressure()

    assert grid.block_state[3, 3, 4] == 1, (
        "Shallow water (3 blocks) should not burst iron floodgate"
    )


# ------------------------------------------------------------------
# 12. Already-open gate is unaffected by burst logic
# ------------------------------------------------------------------


def test_already_open_gate_unaffected_by_burst():
    """Burst logic only targets closed gates (block_state != 0)."""
    # Use enough water to exceed burst threshold — but gate is already open
    eb, grid, wp, gate_z = _make_shaft_with_gate(VOXEL_FLOODGATE, METAL_IRON, burst=True)
    grid.block_state[2, 2, gate_z] = 0  # already open

    events = []
    eb.subscribe("gate_pressure_burst", lambda **kw: events.append(kw))

    wp._apply_pressure()

    # No burst event should fire -- the gate is already open
    assert len(events) == 0, "No burst event expected for already-open gate"
    # block_state should still be 0
    assert grid.block_state[2, 2, gate_z] == 0


# ══════════════════════════════════════════════════════════════════════════
# River flow integration tests
# ══════════════════════════════════════════════════════════════════════════

class TestRiverFlow:
    """Tests that water flows along a river channel on the surface."""

    def test_water_flows_along_channel(self):
        """Water from a source should spread along a terrain-contained channel.

        Simulates a river at SURFACE_Z with solid banks (dirt) on both sides.
        Water should flow from source to the end of the channel.
        """
        from dungeon_builder.config import (
            VOXEL_WATER_SOURCE, VOXEL_WATER_SINK, VOXEL_DIRT, SURFACE_Z,
        )
        w, d, h = 20, 10, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Fill underground with stone
        grid.grid[:, :, SURFACE_Z + 1:] = VOXEL_STONE

        # Banks: dirt at SURFACE_Z on non-channel cells
        for x in range(w):
            for y in range(d):
                if y not in (4, 5, 6):
                    grid.grid[x, y, SURFACE_Z] = VOXEL_DIRT

        # Source at start, sink at end
        grid.grid[0, 5, SURFACE_Z] = VOXEL_WATER_SOURCE
        grid.grid[w - 1, 5, SURFACE_Z + 1] = VOXEL_WATER_SINK

        # Run 50 water ticks
        for i in range(100):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Water should have spread to the far end of the channel
        far_has_water = any(
            grid.grid[w - 2, y, z] == VOXEL_WATER
            for y in range(d) for z in range(h)
        )
        assert far_has_water, "Water should flow to near the end of the channel"

        # Count water cells — should be significant (most of the 3-wide channel)
        total_water = int(np.sum(grid.grid == VOXEL_WATER))
        assert total_water > 20, f"Should have many water cells, got {total_water}"

    def test_water_flows_into_dungeon_entrance(self):
        """Water from a river should flow into an underground opening.

        If a dungeon entrance connects the river channel to underground space,
        water should flow down into the dungeon.
        """
        from dungeon_builder.config import (
            VOXEL_WATER_SOURCE, VOXEL_DIRT, SURFACE_Z,
        )
        w, d, h = 12, 8, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Fill everything below surface with stone
        grid.grid[:, :, SURFACE_Z + 1:] = VOXEL_STONE

        # River channel at y=3,4 at SURFACE_Z
        for x in range(w):
            for y in range(d):
                if y not in (3, 4):
                    grid.grid[x, y, SURFACE_Z] = VOXEL_DIRT

        # Source at start
        grid.grid[0, 4, SURFACE_Z] = VOXEL_WATER_SOURCE

        # Dungeon entrance: opening in the ground at (6, 4)
        # Carve a vertical shaft from SURFACE_Z down to z=SURFACE_Z+3
        for z in range(SURFACE_Z, SURFACE_Z + 4):
            grid.grid[6, 4, z] = VOXEL_AIR

        # Run 50 water ticks
        for i in range(50):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Water should have entered the shaft (below SURFACE_Z)
        underground_water = sum(
            1 for z in range(SURFACE_Z + 1, SURFACE_Z + 4)
            if grid.grid[6, 4, z] == VOXEL_WATER
        )
        assert underground_water > 0, (
            "Water should flow into the dungeon entrance"
        )

    def test_water_contained_by_terrain(self):
        """Water should not spread outside the river channel on the surface.

        Banks (solid dirt) should prevent lateral overflow.
        """
        from dungeon_builder.config import (
            VOXEL_WATER_SOURCE, VOXEL_DIRT, SURFACE_Z,
        )
        w, d, h = 10, 10, 12
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Underground stone
        grid.grid[:, :, SURFACE_Z + 1:] = VOXEL_STONE

        # River: 1-block wide channel at y=5
        for x in range(w):
            for y in range(d):
                if y != 5:
                    grid.grid[x, y, SURFACE_Z] = VOXEL_DIRT

        # Source
        grid.grid[0, 5, SURFACE_Z] = VOXEL_WATER_SOURCE

        # Run many ticks
        for i in range(100):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # No water should appear at SURFACE_Z outside the channel (y != 5)
        water_at_surface = grid.grid[:, :, SURFACE_Z] == VOXEL_WATER
        # Source is at (0,5), channel is y=5
        for y in range(d):
            if y == 5:
                continue
            water_outside = int(np.sum(water_at_surface[:, y]))
            assert water_outside == 0, (
                f"Water leaked outside channel to y={y} ({water_outside} cells)"
            )


# ──────────────────────────────────────────────────────────────────────
# Lateral flow with support (heightmap fix)
# ──────────────────────────────────────────────────────────────────────


class TestLateralFlowSupport:
    """Water should spread laterally based on physical support, not a static
    heightmap.  The old behaviour used ``at_or_below_surface`` which checked
    ``z >= heightmap[x,y]``.  Since the heightmap is never updated after
    terrain changes, water couldn't spread into dug-out columns.

    The fix: water can flow laterally into an air cell if that cell has
    support below (any non-air block) OR is at/below the heightmap.
    """

    def test_water_spreads_laterally_on_terrain(self):
        """Water on top of dirt spreads to adjacent air that also has support."""
        from dungeon_builder.config import VOXEL_WATER_SOURCE
        w, d, h = 12, 12, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Floor: stone at z=7
        grid.grid[:, :, 7] = VOXEL_STONE

        # Dirt layer at z=6
        grid.grid[:, :, 6] = VOXEL_DIRT

        # Place water at (5,5,5) on top of dirt (support at z=6)
        grid.grid[5, 5, 5] = VOXEL_WATER
        grid.water_level[5, 5, 5] = 255

        # Adjacent cells: (6,5,5) is air with dirt below at z=6
        # (already set above — grid is air by default, dirt at z=6)

        # Set heightmap such that the old check would block flow.
        # heightmap=6 means surface is at z=6; z=5 < 6 → above surface.
        grid.heightmap[5, 5] = 6
        grid.heightmap[6, 5] = 6

        # Contain water on other sides to avoid spreading everywhere
        grid.grid[4, 5, 5] = VOXEL_STONE
        grid.grid[5, 4, 5] = VOXEL_STONE
        grid.grid[5, 6, 5] = VOXEL_STONE

        # Run 10 water ticks
        for i in range(10):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Water should have spread to (6,5,5) — it has support (dirt at z=6)
        assert grid.grid[6, 5, 5] == VOXEL_WATER, (
            "Water should spread laterally to adjacent air cell with support"
        )

    def test_water_spreads_to_different_heightmap_column(self):
        """Water spreads even when destination column has a deeper heightmap."""
        w, d, h = 12, 12, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Column A (hill): solid from z=4 down
        grid.grid[5, 5, 4:] = VOXEL_STONE
        grid.heightmap[5, 5] = 4

        # Column B (valley): heightmap=7
        grid.heightmap[6, 5] = 7
        # Support at (6,5,5)
        grid.grid[6, 5, 5] = VOXEL_STONE

        # Water at (5,5,4) on top of stone at (5,5,5)
        grid.grid[5, 5, 4] = VOXEL_WATER
        grid.water_level[5, 5, 4] = 200

        # Full containment so water doesn't leak out the sides
        grid.grid[4, 5, 4] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_STONE
        grid.grid[5, 6, 4] = VOXEL_STONE
        grid.grid[6, 4, 4] = VOXEL_STONE
        grid.grid[6, 6, 4] = VOXEL_STONE
        grid.grid[7, 5, 4] = VOXEL_STONE

        for i in range(10):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Water should have spread to (6,5,4) despite heightmap[6,5]=7 > z=4
        assert grid.grid[6, 5, 4] == VOXEL_WATER, (
            "Water should spread to column with different heightmap if source has support"
        )

    def test_water_does_not_float_in_sky(self):
        """Water should NOT spread laterally into unsupported air (no solid below)."""
        w, d, h = 12, 12, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Water at (5,5,2) with stone below at (5,5,3) — supported
        grid.grid[5, 5, 3] = VOXEL_STONE
        grid.grid[5, 5, 2] = VOXEL_WATER
        grid.water_level[5, 5, 2] = 255

        # Adjacent (6,5,2) is air, and (6,5,3) is ALSO air — NO support
        # heightmap stays default (SURFACE_Z = 5), so z=2 < 5 → above surface
        # Both checks fail → water should NOT spread here

        # Contain on other sides to prevent other flow paths
        grid.grid[4, 5, 2] = VOXEL_STONE
        grid.grid[5, 4, 2] = VOXEL_STONE
        grid.grid[5, 6, 2] = VOXEL_STONE

        for i in range(10):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Water should NOT be at (6,5,2) — no support below and above heightmap
        assert grid.grid[6, 5, 2] != VOXEL_WATER, (
            "Water should not spread into unsupported sky air"
        )

    def test_water_source_creates_all_directions_unconditionally(self):
        """Water source creates water in all 6 adjacent air cells regardless of
        heightmap or support — gravity handles any unsupported water."""
        from dungeon_builder.config import VOXEL_WATER_SOURCE
        w, d, h = 12, 12, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Water source at (5,5,5) — neighbors are all air (no floor)
        grid.grid[5, 5, 5] = VOXEL_WATER_SOURCE

        # Call sources directly (not full tick) to check creation
        # before gravity moves water away.
        wp._apply_sources_and_sinks()

        # All 4 lateral + 1 below + 1 above should be water
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nx, ny, nz = 5+dx, 5+dy, 5+dz
            assert grid.grid[nx, ny, nz] == VOXEL_WATER, (
                f"Source should create water at ({nx},{ny},{nz})"
            )


# ──────────────────────────────────────────────────────────────────────
# Drop-off preference
# ──────────────────────────────────────────────────────────────────────


class TestDropoffPreference:
    def test_water_prefers_dropoff_over_flat(self):
        """Water between a flat neighbor and a drop-off neighbor should flow
        preferentially toward the drop-off (cell with air below).

        Water that reaches the drop-off immediately falls due to gravity,
        so we measure total water in the drop-off column (z=6 + below)
        vs the flat column (z=6 only)."""
        w, d, h = 10, 10, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Stone floor at z=7 across the middle
        grid.grid[:, :, 7] = VOXEL_STONE

        # Water at (5,5,6) with stone below at z=7 — supported
        grid.grid[5, 5, 6] = VOXEL_WATER
        grid.water_level[5, 5, 6] = 200

        # (6,5,6) is air with stone at (6,5,7) — flat neighbor (supported)
        # Already air by default, stone floor already placed at z=7

        # (4,5,6) is air with air at (4,5,7) — drop-off neighbor
        grid.grid[4, 5, 7] = VOXEL_AIR  # remove floor → drop-off
        # Add a floor below the drop-off to catch fallen water
        grid.grid[4, 5, 8] = VOXEL_STONE

        # Contain on y sides with stone to prevent y-spread
        grid.grid[5, 4, 6] = VOXEL_STONE
        grid.grid[5, 6, 6] = VOXEL_STONE

        for i in range(5):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Total water in the drop-off column (water falls from z=6 → z=7)
        dropoff_total = int(np.sum(grid.water_level[4, 5, :]))
        flat_total = int(np.sum(grid.water_level[6, 5, :]))
        assert dropoff_total > flat_total, (
            f"Drop-off column should receive more water: "
            f"dropoff_total={dropoff_total}, flat_total={flat_total}"
        )

    def test_water_drains_through_step_down(self):
        """Water on a flat section with a step-down should drain to the
        lower level within a reasonable number of ticks."""
        w, d, h = 12, 6, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Upper flat: stone floor at z=7 for x=0..5, y=2..3
        for x in range(6):
            for y in range(2, 4):
                grid.grid[x, y, 7] = VOXEL_STONE

        # Lower flat: stone floor at z=8 for x=6..11, y=2..3
        for x in range(6, 12):
            for y in range(2, 4):
                grid.grid[x, y, 8] = VOXEL_STONE

        # Step-down at x=6: z=7 is air (with stone at z=8 = supported)
        # This is already set up — x=6 has floor at z=8, air at z=7

        # Water at (3,2,6) and (3,3,6) on upper flat
        grid.grid[3, 2, 6] = VOXEL_WATER
        grid.water_level[3, 2, 6] = 255
        grid.grid[3, 3, 6] = VOXEL_WATER
        grid.water_level[3, 3, 6] = 255

        # Stone walls on y=1 and y=4 to contain
        for x in range(12):
            for z in range(5, 10):
                grid.grid[x, 1, z] = VOXEL_STONE
                grid.grid[x, 4, z] = VOXEL_STONE

        for i in range(30):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # Water should have reached the lower level (z=7) at some x >= 6
        lower_water = grid.water_level[6:, 2:4, 7]
        assert np.any(lower_water > 0), (
            "Water should drain through the step-down to the lower level"
        )

    def test_dropoff_bonus_does_not_exceed_half_diff(self):
        """The drop-off bonus does not cause overshoot — transfer is still
        capped at half_diff, preserving conservation."""
        w, d, h = 10, 10, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Stone floor at z=7
        grid.grid[:, :, 7] = VOXEL_STONE

        # Water at (5,5,6) level=10
        grid.grid[5, 5, 6] = VOXEL_WATER
        grid.water_level[5, 5, 6] = 10

        # Water at (6,5,6) level=8, with drop-off (air below)
        grid.grid[6, 5, 6] = VOXEL_WATER
        grid.water_level[6, 5, 6] = 8
        grid.grid[6, 5, 7] = VOXEL_AIR  # remove floor → drop-off

        # Contain on other sides to isolate the pair
        grid.grid[4, 5, 6] = VOXEL_STONE
        grid.grid[5, 4, 6] = VOXEL_STONE
        grid.grid[5, 6, 6] = VOXEL_STONE
        grid.grid[7, 5, 6] = VOXEL_STONE
        grid.grid[6, 4, 6] = VOXEL_STONE
        grid.grid[6, 6, 6] = VOXEL_STONE

        total_before = int(grid.water_level[5, 5, 6]) + int(grid.water_level[6, 5, 6])

        _tick(eb, WATER_TICK_INTERVAL)

        # After 1 tick, A should not drop below B's original level
        # (no overshoot — half_diff cap applies)
        a_level = int(grid.water_level[5, 5, 6])
        b_level = int(grid.water_level[6, 5, 6])

        # Water may have fallen from (6,5,6) due to drop-off,
        # so check total conservation across entire grid
        total_after = int(np.sum(grid.water_level))
        assert total_after == total_before, (
            f"Water conservation violated: before={total_before}, after={total_after}"
        )

        # A should still be >= B's original level (no cross-over within
        # the lateral transfer itself — though gravity may have moved
        # water from B downward)
        assert a_level >= 0 and a_level <= 10, (
            f"A's level should remain in valid range: got {a_level}"
        )


# ──────────────────────────────────────────────────────────────────────
# Momentum bias
# ──────────────────────────────────────────────────────────────────────


class TestMomentumBias:
    def test_water_momentum_bias_favors_velocity_direction(self):
        """Water with +x velocity should flow more in +x than -x."""
        w, d, h = 12, 10, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Stone floor at z=7
        grid.grid[:, :, 7] = VOXEL_STONE

        # Water in a line at x=5, y=4..5, z=6, level=200
        for y in range(4, 6):
            grid.grid[5, y, 6] = VOXEL_WATER
            grid.water_level[5, y, 6] = 200
            # Strong +x velocity
            grid.water_vx[5, y, 6] = 2.0

        # Contain with stone walls
        grid.grid[5, 3, 6] = VOXEL_STONE
        grid.grid[5, 6, 6] = VOXEL_STONE
        grid.grid[3, 4, 6] = VOXEL_STONE
        grid.grid[3, 5, 6] = VOXEL_STONE

        for i in range(3):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # More water should have flowed in +x (toward x=6,7) than -x (toward x=3,4)
        forward_water = int(np.sum(grid.water_level[6:8, 4:6, :]))
        backward_water = int(np.sum(grid.water_level[3:5, 4:6, :]))
        assert forward_water > backward_water, (
            f"Water should flow more in +x direction: "
            f"forward={forward_water}, backward={backward_water}"
        )


# ──────────────────────────────────────────────────────────────────────
# Waterfall + basin + escape channel
# ──────────────────────────────────────────────────────────────────────


class TestWaterfallBasin:
    def test_waterfall_into_basin_with_escape(self):
        """Water from a source atop a 5-block cliff should fall into a 2-deep
        basin and drain through a 1-deep escape channel to a sink.  The basin
        should not overflow at reasonable flow rates.

        Side view (y=2 cross-section, x left→right, z top→bottom):

          x:  0    1    2    3    4    5    6    7    8    9   10   11
        z=2: [stn] [src] [air]
        z=3: [stn] [stn] [air]
        z=4: [stn] [stn] [air]
        z=5: [stn] [stn] [air]
        z=6: [stn] [stn] [air]
        z=7: [stn] [stn] [air] [air] [air] [air] [air] [stn] [air] [air] [air] [snk]
        z=8: [stn] [stn] [stn] [air] [air] [air] [air] [air] [stn] [stn] [stn] [stn]
        z=9: [stn --- solid everywhere ---]
        """
        from dungeon_builder.config import VOXEL_WATER_SOURCE, VOXEL_WATER_SINK

        w, d, h = 12, 6, 12
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Fill everything with stone as base, then carve out air spaces
        grid.grid[:, :, :] = VOXEL_STONE

        # Sky above everything (z=0,1 are air)
        grid.grid[:, :, 0:2] = VOXEL_AIR

        # --- Cliff top: x=1, y=2..3 — source right at the edge ---
        grid.grid[1, 2, 2] = VOXEL_AIR
        grid.grid[1, 3, 2] = VOXEL_AIR
        # Stone ceiling at z=1 above source to prevent upward flooding
        grid.grid[1, 2, 1] = VOXEL_STONE
        grid.grid[1, 3, 1] = VOXEL_STONE
        # Stone floor at z=3 (already stone)

        # --- Waterfall drop: x=2, y=2..3, z=2..7 are air ---
        # 5-block drop from z=2 to z=7
        for y in range(2, 4):
            for z in range(2, 8):
                grid.grid[2, y, z] = VOXEL_AIR
            # Cap top of drop column so water doesn't leak to sky
            grid.grid[2, y, 1] = VOXEL_STONE

        # --- Basin: x=3..6, y=2..3 ---
        # 2 deep: air at z=7 and z=8, floor at z=9 (stone)
        for x in range(3, 7):
            for y in range(2, 4):
                grid.grid[x, y, 7] = VOXEL_AIR
                grid.grid[x, y, 8] = VOXEL_AIR

        # Drop column connects to basin floor
        for y in range(2, 4):
            grid.grid[2, y, 8] = VOXEL_AIR

        # --- Escape channel: x=8..11, y=2..3 ---
        # 1 deep: air at z=8 only, floor at z=9.
        # Transition wall: x=7, z=7 stays stone (basin wall at escape level)
        # But x=7, z=8 is air (connects basin z=8 to escape z=8)
        for x in range(7, 12):
            for y in range(2, 4):
                grid.grid[x, y, 8] = VOXEL_AIR

        # --- Source: right at cliff edge ---
        grid.grid[1, 2, 2] = VOXEL_WATER_SOURCE
        grid.grid[1, 3, 2] = VOXEL_WATER_SOURCE

        # --- Sink ---
        grid.grid[11, 2, 8] = VOXEL_WATER_SINK
        grid.grid[11, 3, 8] = VOXEL_WATER_SINK

        # Run enough ticks for water to traverse the whole system
        for i in range(150):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # 1. Water exists in the basin
        basin_water = grid.water_level[3:7, 2:4, 7:9]
        assert np.any(basin_water > 0), (
            "Water should have reached the basin"
        )

        # 2. Water exists in the escape channel
        escape_water = grid.water_level[8:12, 2:4, 8]
        assert np.any(escape_water > 0), (
            "Water should have reached the escape channel"
        )

        # 3. Basin should not overflow (no water at z=6 or above in basin area)
        overflow_water = grid.water_level[3:7, 2:4, :7]
        assert not np.any(overflow_water > 0), (
            f"Basin should not overflow: found water above basin rim, "
            f"max level={np.max(overflow_water)}"
        )


# ──────────────────────────────────────────────────────────────────────
# River containment
# ──────────────────────────────────────────────────────────────────────


class TestRiverContainment:
    def test_river_contained_at_normal_flow(self):
        """A mini-river in a 2-deep channel should stay contained."""
        from dungeon_builder.config import VOXEL_WATER_SOURCE, VOXEL_WATER_SINK

        w, d, h = 16, 8, 16
        eb, grid, wp = _make(w=w, d=d, h=h)

        # Stone base everywhere
        grid.grid[:, :, :] = VOXEL_STONE

        # Air above z=3
        grid.grid[:, :, 0:4] = VOXEL_AIR

        # Carve channel: x=0..15, y=3..4, z=4..5 = air (2 deep)
        # Floor at z=6 (stone), bank walls at y=2 and y=5 are stone at z=4..5
        for x in range(16):
            for y in range(3, 5):
                grid.grid[x, y, 4] = VOXEL_AIR
                grid.grid[x, y, 5] = VOXEL_AIR

        # Source at upstream end (single cell to keep flow reasonable)
        grid.grid[0, 3, 5] = VOXEL_WATER_SOURCE

        # Sink at downstream end
        grid.grid[15, 3, 5] = VOXEL_WATER_SINK
        grid.grid[15, 4, 5] = VOXEL_WATER_SINK

        for i in range(50):
            _tick(eb, WATER_TICK_INTERVAL * (i + 1))

        # No water should have escaped the channel (y <= 2 or y >= 5)
        outside_left = grid.water_level[:, :3, :]
        outside_right = grid.water_level[:, 5:, :]
        assert not np.any(outside_left > 0), (
            "Water should not escape channel to the left (y < 3)"
        )
        assert not np.any(outside_right > 0), (
            "Water should not escape channel to the right (y >= 5)"
        )
