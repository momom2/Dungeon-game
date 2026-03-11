"""Tests for logical connection detection between placed blocks.

Tests the pure ``find_connections`` function with small grids —
no Panda3D or rendering required.
"""

import pytest

from dungeon_builder.building.connections import (
    CONNECTABLE_TYPES,
    Connection,
    find_connections,
)
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_ALARM_BELL,
    VOXEL_DOOR,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    VOXEL_HEAT_BEACON,
    VOXEL_PIPE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_PUMP,
    VOXEL_ROLLING_STONE,
    VOXEL_SLOPE,
    VOXEL_SPIKE,
    VOXEL_STAIRS,
    VOXEL_STEAM_VENT,
    VOXEL_STONE,
    VOXEL_TARP,
    PRESSURE_PLATE_TRIGGER_RANGE,
    ALARM_BELL_DETECTION_RANGE,
)
from dungeon_builder.world.voxel_grid import VoxelGrid


def _make_grid(w=10, d=10, h=10):
    return VoxelGrid(width=w, depth=d, height=h)


# ── Trigger connections ──────────────────────────────────────────────


class TestTriggerConnections:
    """Pressure plates and alarm bells connect to nearby actuators."""

    def test_pressure_plate_finds_adjacent_enchanted_door(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[6, 5, 5] = VOXEL_ENCHANTED_DOOR
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].conn_type == "trigger"
        assert conns[0].target == (6, 5, 5)
        assert conns[0].bidirectional is False

    def test_pressure_plate_finds_adjacent_spike(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[5, 6, 5] = VOXEL_SPIKE
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].target == (5, 6, 5)

    def test_pressure_plate_finds_enchanted_floodgate(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[5, 5, 6] = VOXEL_ENCHANTED_FLOODGATE
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].target == (5, 5, 6)

    def test_pressure_plate_ignores_regular_door(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[6, 5, 5] = VOXEL_DOOR  # Regular, not enchanted
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_pressure_plate_range(self):
        """Targets within Chebyshev distance 1 are found (diagonal)."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[6, 6, 5] = VOXEL_SPIKE  # Diagonal — Chebyshev dist 1
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1

    def test_pressure_plate_out_of_range(self):
        """Target at distance 2 is NOT found by pressure plate (range=1)."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[7, 5, 5] = VOXEL_SPIKE  # Distance 2
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_alarm_bell_range_2(self):
        """Alarm bell finds targets within Chebyshev distance 2."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_ALARM_BELL
        grid.grid[7, 5, 5] = VOXEL_SPIKE  # Distance 2
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].conn_type == "trigger"

    def test_alarm_bell_out_of_range(self):
        """Target at distance 3 is NOT found by alarm bell (range=2)."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_ALARM_BELL
        grid.grid[8, 5, 5] = VOXEL_SPIKE  # Distance 3
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_multiple_targets(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PRESSURE_PLATE
        grid.grid[6, 5, 5] = VOXEL_SPIKE
        grid.grid[4, 5, 5] = VOXEL_ENCHANTED_DOOR
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 2

    def test_hypothetical_placement(self):
        """Pass vtype to preview connections before placing."""
        grid = _make_grid()
        grid.grid[6, 5, 5] = VOXEL_ENCHANTED_DOOR
        # Position (5,5,5) is air — but we pass vtype to simulate placement
        conns = find_connections(grid, 5, 5, 5, vtype=VOXEL_PRESSURE_PLATE)
        assert len(conns) == 1
        assert conns[0].conn_type == "trigger"


# ── Flow connections ─────────────────────────────────────────────────


class TestFlowConnections:
    """Pipes and pumps connect to adjacent pipes/pumps."""

    def test_pipe_finds_adjacent_pipe(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PIPE
        grid.grid[6, 5, 5] = VOXEL_PIPE
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].conn_type == "flow"
        assert conns[0].bidirectional is True

    def test_pipe_finds_adjacent_pump(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PIPE
        grid.grid[5, 6, 5] = VOXEL_PUMP
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].conn_type == "flow"

    def test_pipe_ignores_non_pipe_neighbor(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PIPE
        grid.grid[6, 5, 5] = VOXEL_STONE
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_pipe_only_6_connected(self):
        """Diagonal pipes are NOT connected (6-connected only)."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PIPE
        grid.grid[6, 6, 5] = VOXEL_PIPE  # Diagonal
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_pump_finds_pipe_chain(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_PUMP
        grid.grid[6, 5, 5] = VOXEL_PIPE
        grid.grid[4, 5, 5] = VOXEL_PIPE
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 2
        assert all(c.conn_type == "flow" for c in conns)


# ── Thermal connections ──────────────────────────────────────────────


class TestThermalConnections:
    """Heat beacons and steam vents radiate to nearby blocks."""

    def test_heat_beacon_finds_stone_within_radius(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_HEAT_BEACON
        grid.grid[7, 5, 5] = VOXEL_STONE  # Distance 2, within radius 3
        conns = find_connections(grid, 5, 5, 5)
        thermal = [c for c in conns if c.conn_type == "thermal"]
        targets = {c.target for c in thermal}
        assert (7, 5, 5) in targets
        assert all(c.bidirectional for c in thermal)

    def test_heat_beacon_ignores_air(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_HEAT_BEACON
        # All neighbors are air by default
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_heat_beacon_radius_3(self):
        """Block at Chebyshev distance 3 is found; distance 4 is not."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_HEAT_BEACON
        grid.grid[8, 5, 5] = VOXEL_STONE  # Distance 3
        grid.grid[9, 5, 5] = VOXEL_STONE  # Distance 4
        conns = find_connections(grid, 5, 5, 5)
        targets = {c.target for c in conns}
        assert (8, 5, 5) in targets
        assert (9, 5, 5) not in targets

    def test_steam_vent_finds_blocks_above(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_STEAM_VENT
        grid.grid[5, 5, 4] = VOXEL_STONE  # z-1 (shallower)
        grid.grid[5, 5, 3] = VOXEL_STONE  # z-2
        conns = find_connections(grid, 5, 5, 5)
        thermal = [c for c in conns if c.conn_type == "thermal"]
        assert len(thermal) == 2
        targets = {c.target for c in thermal}
        assert (5, 5, 4) in targets
        assert (5, 5, 3) in targets

    def test_steam_vent_only_above(self):
        """Steam vent does NOT connect to blocks below or beside."""
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_STEAM_VENT
        grid.grid[6, 5, 5] = VOXEL_STONE  # Beside
        grid.grid[5, 5, 6] = VOXEL_STONE  # Below (deeper z)
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0


# ── Structural connections ───────────────────────────────────────────


class TestStructuralConnections:
    """Rolling stones and tarps depend on structural features."""

    def test_rolling_stone_finds_slope_below(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_ROLLING_STONE
        grid.grid[5, 5, 6] = VOXEL_SLOPE  # z+1 is deeper (below)
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1
        assert conns[0].conn_type == "structural"
        assert conns[0].target == (5, 5, 6)
        assert conns[0].bidirectional is False

    def test_rolling_stone_finds_stairs_below(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_ROLLING_STONE
        grid.grid[5, 5, 6] = VOXEL_STAIRS
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 1

    def test_rolling_stone_no_slope(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_ROLLING_STONE
        # No slope below
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_tarp_finds_support_walls(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_TARP
        grid.grid[6, 5, 5] = VOXEL_STONE  # Wall +x
        grid.grid[4, 5, 5] = VOXEL_STONE  # Wall -x
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 2
        assert all(c.conn_type == "structural" for c in conns)

    def test_tarp_ignores_air_neighbors(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_TARP
        # All neighbors are air
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0


# ── General ──────────────────────────────────────────────────────────


class TestConnectableTypes:
    """The CONNECTABLE_TYPES set covers all block types with connections."""

    def test_all_connection_sources_in_set(self):
        expected = {
            VOXEL_PRESSURE_PLATE, VOXEL_ALARM_BELL,
            VOXEL_PIPE, VOXEL_PUMP,
            VOXEL_HEAT_BEACON, VOXEL_STEAM_VENT,
            VOXEL_ROLLING_STONE, VOXEL_TARP,
        }
        assert CONNECTABLE_TYPES == expected

    def test_stone_has_no_connections(self):
        grid = _make_grid()
        grid.grid[5, 5, 5] = VOXEL_STONE
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_air_has_no_connections(self):
        grid = _make_grid()
        conns = find_connections(grid, 5, 5, 5)
        assert len(conns) == 0

    def test_connection_is_frozen_dataclass(self):
        conn = Connection(
            source=(1, 2, 3), target=(4, 5, 6),
            conn_type="trigger", bidirectional=False,
        )
        with pytest.raises(AttributeError):
            conn.source = (0, 0, 0)  # type: ignore[misc]
