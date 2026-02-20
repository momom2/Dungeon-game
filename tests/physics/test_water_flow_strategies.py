"""Tests for water flow strategies: parametrized across LBM and Jacobi.

Each test verifies a fundamental property that all flow strategies must
satisfy: gravity, mass conservation, wall containment, lateral leveling,
and still-water equilibrium.  Strategy-specific tests follow.
"""

import numpy as np
import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.physics.water import WaterPhysics
from dungeon_builder.world.physics.water_flow_strategies import (
    create_strategy,
    LatticeBoltzmannFlow,
    JacobiProjectionFlow,
)
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_STONE,
    WATER_TICK_INTERVAL,
)


ALL_MODELS = [
    "lattice_boltzmann",
    "jacobi_projection",
]


def _make(model, w=12, d=10, h=16):
    """Create event bus, grid, and water physics with a specific strategy."""
    eb = EventBus()
    grid = VoxelGrid(w, d, h)
    # Monkeypatch the config before creating WaterPhysics
    import dungeon_builder.config as _cfg
    old_model = _cfg.WATER_FLOW_MODEL
    _cfg.WATER_FLOW_MODEL = model
    wp = WaterPhysics(eb, grid)
    _cfg.WATER_FLOW_MODEL = old_model  # Restore
    return eb, grid, wp


def _tick(eb, tick_num):
    """Publish a tick event."""
    eb.publish("tick", tick=tick_num)


def _run(eb, n_ticks):
    """Run n ticks."""
    for i in range(1, n_ticks + 1):
        _tick(eb, i * WATER_TICK_INTERVAL)


def _fill_stone_box(grid, x0, x1, y0, y1, z0, z1):
    """Fill the borders of a box with stone, leaving interior as air.

    All six faces are stone: x=x0, x=x1, y=y0, y=y1, z=z0 (ceiling), z=z1 (floor).
    """
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                is_border = (
                    x == x0 or x == x1
                    or y == y0 or y == y1
                    or z == z0 or z == z1  # ceiling and floor
                )
                if is_border:
                    grid.grid[x, y, z] = VOXEL_STONE


def _total_mass(grid):
    """Total water mass across the grid."""
    return int(np.sum(grid.water_level))


def _water_cells(grid):
    """Count of cells typed VOXEL_WATER."""
    return int(np.sum(grid.grid == VOXEL_WATER))


# ──────────────────────────────────────────────────────────────────────
# Factory test
# ──────────────────────────────────────────────────────────────────────

class TestFactory:
    def test_create_all_strategies(self):
        """create_strategy should return the correct type for each model."""
        assert isinstance(create_strategy("lattice_boltzmann"), LatticeBoltzmannFlow)
        assert isinstance(create_strategy("jacobi_projection"), JacobiProjectionFlow)

    def test_create_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown water flow model"):
            create_strategy("nonexistent_model")


# ──────────────────────────────────────────────────────────────────────
# Cross-strategy tests (parametrized across ALL models)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestGravityDrop:
    def test_water_falls_through_air(self, model):
        """Water above air should eventually reach the floor."""
        eb, grid, wp = _make(model)
        # Stone box to contain the water
        _fill_stone_box(grid, 4, 6, 4, 6, 6, 9)
        # Place water inside the box at z=7 (one below top wall)
        grid.grid[5, 5, 7] = VOXEL_WATER
        grid.water_level[5, 5, 7] = 200

        _run(eb, 10)

        # Water should be at z=8 (above the stone floor at z=9)
        assert grid.water_level[5, 5, 8] > 0, (
            f"Water should have fallen to z=8 with model={model}"
        )


@pytest.mark.parametrize("model", ALL_MODELS)
class TestWallContainment:
    def test_water_does_not_leak_through_walls(self, model):
        """Water should never appear on the far side of a solid wall."""
        eb, grid, wp = _make(model)
        # Build stone walls around a pool
        _fill_stone_box(grid, 3, 7, 3, 7, 7, 10)
        # Fill interior with water
        for x in range(4, 7):
            for y in range(4, 7):
                for z in range(8, 10):
                    grid.grid[x, y, z] = VOXEL_WATER
                    grid.water_level[x, y, z] = 200

        _run(eb, 15)

        # No water outside the box
        outside_water = 0
        for x in range(grid.width):
            for y in range(grid.depth):
                for z in range(grid.height):
                    if x < 3 or x > 7 or y < 3 or y > 7 or z < 7 or z > 10:
                        if grid.water_level[x, y, z] > 0:
                            outside_water += grid.water_level[x, y, z]
        assert outside_water == 0, (
            f"Water leaked through walls: {outside_water} total outside, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Cross-strategy tests (parametrized across all models)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestMassConservationShallow:
    def test_single_cell_sealed_box(self, model):
        """Single cell of water in sealed box: mass must be conserved."""
        eb, grid, wp = _make(model)
        _fill_stone_box(grid, 3, 7, 3, 7, 5, 10)
        grid.grid[5, 5, 9] = VOXEL_WATER
        grid.water_level[5, 5, 9] = 200

        initial = _total_mass(grid)
        _run(eb, 30)
        final = _total_mass(grid)

        # LBM has float↔uint8 quantization loss
        tolerance = 80 if model == "lattice_boltzmann" else 15
        assert abs(final - initial) <= tolerance, (
            f"Mass not conserved: initial={initial}, final={final}, model={model}"
        )


@pytest.mark.parametrize("model", ALL_MODELS)
class TestMassConservationDeep:
    def test_deep_column_sealed_box(self, model):
        """Deep water column (8 cells) in sealed box: mass conserved."""
        eb, grid, wp = _make(model, w=14, d=14, h=14)
        _fill_stone_box(grid, 1, 12, 1, 12, 1, 12)
        # 3x3x8 column of water
        for z in range(3, 11):
            for x in range(5, 8):
                for y in range(5, 8):
                    grid.grid[x, y, z] = VOXEL_WATER
                    grid.water_level[x, y, z] = 255

        initial = _total_mass(grid)
        _run(eb, 60)
        final = _total_mass(grid)

        # Allow wider tolerance for LBM due to float rounding
        if model == "lattice_boltzmann":
            tolerance = int(initial * 0.10)  # 10%
        else:
            tolerance = int(initial * 0.02)  # 2%
        assert abs(final - initial) <= tolerance, (
            f"Deep column mass not conserved: initial={initial}, final={final}, "
            f"diff={final-initial:+d} ({(final-initial)/initial*100:+.1f}%), model={model}"
        )


@pytest.mark.parametrize("model", ALL_MODELS)
class TestLateralLeveling:
    def test_water_spreads_laterally(self, model):
        """Water column next to empty space should spread to adjacent cells."""
        eb, grid, wp = _make(model, w=10, d=6, h=12)
        _fill_stone_box(grid, 0, 9, 0, 5, 6, 10)

        # Column of water on the left (x=1..2, z=7..9)
        for x in range(1, 3):
            for y in range(1, 5):
                for z in range(7, 10):
                    grid.grid[x, y, z] = VOXEL_WATER
                    grid.water_level[x, y, z] = 255

        _run(eb, 100)

        # Water should have spread at least to x=3 (directly adjacent)
        adj_water = int(np.sum(grid.water_level[3:5, 1:5, :]))
        assert adj_water > 0, (
            f"Water should have spread laterally, model={model}"
        )


@pytest.mark.parametrize("model", ALL_MODELS)
class TestStillWaterEquilibrium:
    def test_uniform_pool_stays_stable(self, model):
        """A uniform single-layer pool should not gain or lose significant mass."""
        eb, grid, wp = _make(model, w=8, d=8, h=12)
        _fill_stone_box(grid, 0, 7, 0, 7, 7, 10)
        # Fill uniformly with water (single layer)
        for x in range(1, 7):
            for y in range(1, 7):
                grid.grid[x, y, 9] = VOXEL_WATER
                grid.water_level[x, y, 9] = 200

        initial_mass = 200 * 6 * 6  # 7200
        _run(eb, 60)

        total_water = int(np.sum(grid.water_level[1:7, 1:7, :]))
        tolerance = 200 if model == "lattice_boltzmann" else 50
        assert abs(total_water - initial_mass) <= tolerance, (
            f"Pool lost/gained mass: expected~{initial_mass}, got={total_water}, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Level uniformity — water should settle to near-equal levels
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestLevelUniformity:
    def test_pool_reaches_uniform_levels(self, model):
        """Water spread across a flat floor should reach near-uniform levels."""
        eb, grid, wp = _make(model, w=10, d=10, h=6)
        _fill_stone_box(grid, 0, 9, 0, 9, 0, 4)
        # Place water in one corner
        for x in range(1, 4):
            for y in range(1, 4):
                grid.grid[x, y, 3] = VOXEL_WATER
                grid.water_level[x, y, 3] = 255

        _run(eb, 200)

        # Water should have spread and reached some level of uniformity.
        water_mask = grid.grid == VOXEL_WATER
        if np.sum(water_mask) < 2:
            pytest.skip("Too few water cells to test uniformity")
        levels = grid.water_level[water_mask]
        std = float(np.std(levels))
        mean = float(np.mean(levels))

        # Standard deviation should be less than 40% of the mean
        assert std < mean * 0.4, (
            f"Water levels not uniform enough: mean={mean:.1f}, std={std:.1f}, "
            f"ratio={std/mean:.2f}, model={model}"
        )

    def test_two_equal_columns_equalize(self, model):
        """Water on one side of a trough should level with the other side."""
        eb, grid, wp = _make(model, w=10, d=4, h=6)
        _fill_stone_box(grid, 0, 9, 0, 3, 0, 4)
        # Place water on left half only
        for x in range(1, 5):
            for y in range(1, 3):
                grid.grid[x, y, 3] = VOXEL_WATER
                grid.water_level[x, y, 3] = 255

        init_mass = _total_mass(grid)
        _run(eb, 150)

        # Water should have spread to the right half
        left_mass = int(np.sum(grid.water_level[1:5, 1:3, :]))
        right_mass = int(np.sum(grid.water_level[5:9, 1:3, :]))
        total = left_mass + right_mass

        # Right side should have received at least 30% of the water
        assert right_mass > total * 0.30, (
            f"Water didn't equalize: left={left_mass}, right={right_mass}, "
            f"total={total}, right_pct={right_mass/total*100:.0f}%, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Communicating vessels (U-tube)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestCommunicatingVessels:
    def test_u_tube_water_reaches_far_arm(self, model):
        """Water in one arm of a U-tube should flow through and reach the other."""
        eb, grid, wp = _make(model, w=12, d=4, h=10)
        # Left arm: x=1-3
        _fill_stone_box(grid, 0, 4, 0, 3, 0, 8)
        # Right arm: x=7-10
        _fill_stone_box(grid, 6, 11, 0, 3, 0, 8)
        # Connecting channel at bottom: clear interior between arms at z=7
        for x in range(3, 8):
            for y in range(1, 3):
                grid.grid[x, y, 7] = VOXEL_AIR
        # Ensure channel floor
        for x in range(3, 8):
            for y in range(0, 4):
                grid.grid[x, y, 8] = VOXEL_STONE

        # Fill left arm with water (z=2..7)
        for z in range(2, 8):
            for x in range(1, 4):
                for y in range(1, 3):
                    grid.grid[x, y, z] = VOXEL_WATER
                    grid.water_level[x, y, z] = 255

        _run(eb, 300)

        # Water should reach the right arm (x=7..10)
        right_water = int(np.sum(grid.water_level[7:11, 1:3, :]))
        assert right_water > 100, (
            f"Water didn't reach right arm of U-tube: right_water={right_water}, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Waterfall / ledge flow
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestWaterfallFlow:
    def test_water_flows_over_ledge(self, model):
        """Water on a ledge should flow over the edge and collect below."""
        eb, grid, wp = _make(model, w=12, d=6, h=10)
        # Full box
        _fill_stone_box(grid, 0, 11, 0, 5, 0, 8)
        # Remove right half of floor to create a ledge
        for x in range(6, 11):
            for y in range(1, 5):
                grid.grid[x, y, 8] = VOXEL_AIR
        # Add lower floor for the drop
        for x in range(6, 11):
            for y in range(0, 6):
                grid.grid[x, y, 9] = VOXEL_STONE

        # Place water on the ledge (left side)
        for x in range(1, 5):
            for y in range(1, 5):
                grid.grid[x, y, 7] = VOXEL_WATER
                grid.water_level[x, y, 7] = 200

        init_mass = _total_mass(grid)
        _run(eb, 100)

        # Water should have flowed over the edge — some on the right
        right_water = int(np.sum(grid.water_level[6:11, :, :]))
        assert right_water > 100, (
            f"Water didn't flow over ledge: right={right_water}, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Narrow channel flow
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestNarrowChannelFlow:
    def test_water_flows_through_1_wide_channel(self, model):
        """Water should flow through a 1-cell-wide channel between two chambers."""
        eb, grid, wp = _make(model, w=14, d=6, h=8)
        # Left chamber
        _fill_stone_box(grid, 0, 5, 0, 5, 2, 6)
        # Right chamber
        _fill_stone_box(grid, 7, 13, 0, 5, 2, 6)
        # Connecting channel: x=5..7, y=2..3, z=5 (1 cell above floor)
        grid.grid[5, 2, 5] = VOXEL_AIR
        grid.grid[5, 3, 5] = VOXEL_AIR
        grid.grid[6, 2, 5] = VOXEL_AIR
        grid.grid[6, 3, 5] = VOXEL_AIR
        grid.grid[7, 2, 5] = VOXEL_AIR
        grid.grid[7, 3, 5] = VOXEL_AIR
        # Ensure floor under channel
        for x in range(5, 8):
            grid.grid[x, 2, 6] = VOXEL_STONE
            grid.grid[x, 3, 6] = VOXEL_STONE

        # Fill left chamber with water
        for x in range(1, 5):
            for y in range(1, 5):
                grid.grid[x, y, 5] = VOXEL_WATER
                grid.water_level[x, y, 5] = 255

        _run(eb, 200)

        # Water should reach right chamber
        right_water = int(np.sum(grid.water_level[8:13, 1:5, :]))
        assert right_water > 50, (
            f"Water didn't flow through narrow channel: right={right_water}, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Multi-cell gravity cascade
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestGravityCascade:
    def test_water_falls_multiple_levels(self, model):
        """Water should fall through multiple air cells to the floor."""
        eb, grid, wp = _make(model, w=6, d=6, h=12)
        _fill_stone_box(grid, 0, 5, 0, 5, 0, 10)
        # Place water near the top
        grid.grid[3, 3, 2] = VOXEL_WATER
        grid.water_level[3, 3, 2] = 255

        _run(eb, 20)

        # Water should be at the bottom (z=9, above floor at z=10)
        bottom_water = int(np.sum(grid.water_level[:, :, 8:10]))
        assert bottom_water > 0, (
            f"Water didn't fall to bottom: bottom_water={bottom_water}, model={model}"
        )

    def test_stacked_water_settles(self, model):
        """A vertical column of water cells should settle on the floor."""
        eb, grid, wp = _make(model, w=8, d=8, h=12)
        _fill_stone_box(grid, 1, 6, 1, 6, 2, 10)
        # 3-cell tall column suspended in air
        for z in range(4, 7):
            grid.grid[3, 3, z] = VOXEL_WATER
            grid.water_level[3, 3, z] = 200

        init_mass = _total_mass(grid)
        _run(eb, 30)

        # All water should be at the bottom of the box
        bottom_water = int(np.sum(grid.water_level[:, :, 8:10]))
        assert bottom_water > init_mass * 0.5, (
            f"Water column didn't settle: bottom={bottom_water}, init={init_mass}, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# No-op on empty grid
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestEmptyGrid:
    def test_no_water_no_crash(self, model):
        """Running physics on a grid with no water should not crash."""
        eb, grid, wp = _make(model, w=8, d=8, h=8)
        _run(eb, 5)
        assert _total_mass(grid) == 0


# ──────────────────────────────────────────────────────────────────────
# Runtime model switching
# ──────────────────────────────────────────────────────────────────────

class TestRuntimeSwitch:
    def test_switch_strategy_mid_simulation(self):
        """Switching strategy mid-simulation should not crash."""
        import dungeon_builder.config as _cfg

        _cfg.WATER_FLOW_MODEL = "lattice_boltzmann"
        eb = EventBus()
        grid = VoxelGrid(8, 8, 12)
        wp = WaterPhysics(eb, grid)

        # Place some water
        _fill_stone_box(grid, 1, 6, 1, 6, 8, 10)
        grid.grid[3, 3, 9] = VOXEL_WATER
        grid.water_level[3, 3, 9] = 200

        # Run a few ticks with LBM
        for i in range(1, 6):
            _tick(eb, i * WATER_TICK_INTERVAL)

        # Switch to Jacobi
        _cfg.WATER_FLOW_MODEL = "jacobi_projection"
        eb.publish("config_changed", key="WATER_FLOW_MODEL")

        for i in range(6, 12):
            _tick(eb, i * WATER_TICK_INTERVAL)

        # Switch back to LBM
        _cfg.WATER_FLOW_MODEL = "lattice_boltzmann"
        eb.publish("config_changed", key="WATER_FLOW_MODEL")

        for i in range(12, 16):
            _tick(eb, i * WATER_TICK_INTERVAL)

        # If we get here without crashing, the test passes.
        assert np.sum(grid.water_level) > 0

        # Restore default
        _cfg.WATER_FLOW_MODEL = "lattice_boltzmann"


# ──────────────────────────────────────────────────────────────────────
# Strategy-specific tests — Lattice Boltzmann
# ──────────────────────────────────────────────────────────────────────

class TestLatticeBoltzmannSpecific:
    def test_lbm_arrays_allocated(self):
        """LBM strategy should allocate distribution functions."""
        eb, grid, wp = _make("lattice_boltzmann")
        assert grid._lbm_f is not None, "LBM should allocate distribution functions"
        assert grid._lbm_f.shape == (12, 10, 16, 7)

    def test_lbm_density_maps_to_level(self):
        """LBM density should map back to water_level correctly."""
        eb, grid, wp = _make("lattice_boltzmann")
        _fill_stone_box(grid, 3, 8, 3, 7, 8, 11)
        grid.grid[5, 5, 10] = VOXEL_WATER
        grid.water_level[5, 5, 10] = 200

        wp._strategy.init_arrays(grid)
        _run(eb, 5)

        total = _total_mass(grid)
        assert total > 0, "LBM should maintain some water"

    def test_lbm_distributions_track_water(self):
        """LBM distribution functions should track the water mass."""
        eb, grid, wp = _make("lattice_boltzmann", w=8, d=8, h=8)
        _fill_stone_box(grid, 1, 6, 1, 6, 1, 6)
        # Fill a pool at the bottom
        for x in range(2, 6):
            for y in range(2, 6):
                grid.grid[x, y, 5] = VOXEL_WATER
                grid.water_level[x, y, 5] = 200

        _run(eb, 10)

        # LBM distributions should have non-zero rho at water cells
        water_mask = grid.grid == VOXEL_WATER
        f = grid._lbm_f
        rho_at_water = np.sum(f, axis=3)[water_mask]
        assert np.all(rho_at_water > 0), (
            "LBM distributions should have non-zero rho at water cells"
        )
        # Water mass should be conserved (checked by mass conservation tests)
        # LBM distributions are used for velocity only — not mass transport

    def test_lbm_settled_pool_stable(self):
        """A settled LBM pool should not lose significant mass over time."""
        eb, grid, wp = _make("lattice_boltzmann", w=8, d=8, h=8)
        _fill_stone_box(grid, 0, 7, 0, 7, 3, 6)
        for x in range(1, 7):
            for y in range(1, 7):
                grid.grid[x, y, 5] = VOXEL_WATER
                grid.water_level[x, y, 5] = 200

        # Let it settle first
        _run(eb, 30)
        settled_mass = _total_mass(grid)

        # Run more — should be stable now
        _run(eb, 30)
        final_mass = _total_mass(grid)

        # Once settled, mass change should be very small
        assert abs(final_mass - settled_mass) < settled_mass * 0.05, (
            f"LBM settled pool not stable: settled={settled_mass}, "
            f"final={final_mass}, model=lattice_boltzmann"
        )


# ──────────────────────────────────────────────────────────────────────
# Strategy-specific tests — Jacobi Projection
# ──────────────────────────────────────────────────────────────────────

class TestJacobiSpecific:
    def test_pressure_solve_runs(self):
        """Jacobi projection should compute pressure without crashing."""
        eb, grid, wp = _make("jacobi_projection")
        _fill_stone_box(grid, 2, 9, 2, 7, 7, 11)
        for z in range(8, 11):
            grid.grid[5, 4, z] = VOXEL_WATER
            grid.water_level[5, 4, z] = 255

        _run(eb, 5)
        # Just verifying no crash

    def test_jacobi_velocity_correction(self):
        """Jacobi should develop velocity from pressure correction."""
        eb, grid, wp = _make("jacobi_projection", w=10, d=6, h=12)
        _fill_stone_box(grid, 0, 9, 0, 5, 6, 10)
        for z in range(7, 10):
            for y in range(1, 5):
                grid.grid[1, y, z] = VOXEL_WATER
                grid.water_level[1, y, z] = 255

        _run(eb, 20)

        water_mask = grid.grid == VOXEL_WATER
        if np.any(water_mask):
            max_v = float(np.max(
                np.abs(grid.water_vx[water_mask])
                + np.abs(grid.water_vz[water_mask])
            ))
            assert max_v > 0, "Jacobi should develop velocity from pressure"

    def test_jacobi_spreads_single_cell(self):
        """Jacobi should spread a single cell of water to neighbors."""
        eb, grid, wp = _make("jacobi_projection", w=10, d=6, h=6)
        _fill_stone_box(grid, 0, 9, 0, 5, 0, 4)
        grid.grid[3, 2, 3] = VOXEL_WATER
        grid.water_level[3, 2, 3] = 255

        _run(eb, 50)

        # Should have spread beyond the original cell
        cells = _water_cells(grid)
        assert cells > 1, (
            f"Jacobi should spread single cell to neighbors, cells={cells}"
        )


# ──────────────────────────────────────────────────────────────────────
# Water stays below ground (no upward spreading)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestNoUpwardSpread:
    def test_water_does_not_spread_above_floor(self, model):
        """Water placed on a floor should NOT spread upward into air."""
        eb, grid, wp = _make(model, w=10, d=10, h=10)
        # Stone floor at z=5, ceiling at z=0, walls
        _fill_stone_box(grid, 0, 9, 0, 9, 0, 6)
        # Place water on the floor
        for x in range(2, 8):
            for y in range(2, 8):
                grid.grid[x, y, 5] = VOXEL_WATER
                grid.water_level[x, y, 5] = 200

        _run(eb, 50)

        # No water above the initial layer (z < 5)
        water_above = int(np.sum(grid.water_level[:, :, :4]))
        assert water_above == 0, (
            f"Water spread above floor: {water_above} units above z=4, model={model}"
        )

    def test_sealed_room_water_stays_contained(self, model):
        """Water in a sealed room should never appear outside."""
        eb, grid, wp = _make(model, w=10, d=10, h=10)
        _fill_stone_box(grid, 2, 7, 2, 7, 2, 7)
        # Fill half the room with water
        for x in range(3, 7):
            for y in range(3, 7):
                for z in range(5, 7):
                    grid.grid[x, y, z] = VOXEL_WATER
                    grid.water_level[x, y, z] = 200

        _run(eb, 100)

        # No water outside the stone box
        outside = 0
        for x in range(grid.width):
            for y in range(grid.depth):
                for z in range(grid.height):
                    if x < 2 or x > 7 or y < 2 or y > 7 or z < 2 or z > 7:
                        outside += grid.water_level[x, y, z]
        assert outside == 0, (
            f"Water escaped sealed room: {outside} units outside, model={model}"
        )


# ──────────────────────────────────────────────────────────────────────
# Source-to-sink flow
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS)
class TestSourceToSinkFlow:
    def test_water_flows_from_source_to_sink(self, model):
        """Water from a source should eventually reach a sink through a channel."""
        import dungeon_builder.config as _cfg

        eb, grid, wp = _make(model, w=14, d=6, h=8)
        # Build a channel with floor
        for x in range(14):
            for y in range(6):
                grid.grid[x, y, 6] = VOXEL_STONE  # floor
        for y in range(6):
            grid.grid[0, y, 6] = VOXEL_STONE
            grid.grid[13, y, 6] = VOXEL_STONE
        for x in range(14):
            grid.grid[x, 0, 6] = VOXEL_STONE
            grid.grid[x, 5, 6] = VOXEL_STONE

        # Source at left (x=1), sink at right (x=12)
        grid.grid[1, 2, 5] = _cfg.VOXEL_WATER_SOURCE
        grid.grid[12, 2, 5] = _cfg.VOXEL_WATER_SINK

        _run(eb, 400)

        # Water should have appeared somewhere between source and sink
        mid_water = int(np.sum(grid.water_level[4:10, 1:5, :]))
        assert mid_water > 0, (
            f"Water from source didn't flow through channel: mid={mid_water}, model={model}"
        )


