"""Logical connection detection between placed blocks.

Connections represent functional relationships: trigger signals (pressure
plate → enchanted door), fluid flow (pipe ↔ pipe), thermal radiation
(heat beacon → nearby blocks), and structural dependencies (rolling stone
→ slope below).

All detection is local (1–6 cell radius) and computed on demand — no
caching.  ``find_connections`` is a pure function suitable for headless
testing.

Dependencies: config.voxels, config.building, world.voxel_grid
Dependents: rendering.effects, tests/building/test_connections.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dungeon_builder.config.building import (
    ALARM_BELL_DETECTION_RANGE,
    PRESSURE_PLATE_TRIGGER_RANGE,
    STEAM_VENT_RANGE,
)
from dungeon_builder.config.voxels import (
    VOXEL_AIR,
    VOXEL_ALARM_BELL,
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
    VOXEL_TARP,
    VOXEL_WATER,
)

if TYPE_CHECKING:
    from dungeon_builder.world.voxel_grid import VoxelGrid


# ── Constants ────────────────────────────────────────────────────────

# Target block types that respond to trigger signals
TRIGGER_TARGETS = frozenset({
    VOXEL_SPIKE, VOXEL_ENCHANTED_DOOR, VOXEL_ENCHANTED_FLOODGATE,
})

# Block types that participate in pipe flow networks
FLOW_TYPES = frozenset({VOXEL_PIPE, VOXEL_PUMP})

# Heat beacon scans this Chebyshev radius for thermal connections
HEAT_BEACON_THERMAL_RADIUS = 3

# All block types that can have logical connections
CONNECTABLE_TYPES = frozenset({
    VOXEL_PRESSURE_PLATE, VOXEL_ALARM_BELL,
    VOXEL_PIPE, VOXEL_PUMP,
    VOXEL_HEAT_BEACON, VOXEL_STEAM_VENT,
    VOXEL_ROLLING_STONE, VOXEL_TARP,
})

# 6-connected neighbor offsets (±x, ±y, ±z)
_OFFSETS_6 = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


# ── Data ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Connection:
    """A logical relationship between two blocks."""
    source: tuple[int, int, int]
    target: tuple[int, int, int]
    conn_type: str          # "trigger", "flow", "thermal", "structural"
    bidirectional: bool


# ── Detection ────────────────────────────────────────────────────────

def find_connections(
    grid: VoxelGrid,
    x: int, y: int, z: int,
    vtype: int | None = None,
) -> list[Connection]:
    """Find all logical connections from/to the block at (x, y, z).

    If *vtype* is provided, compute connections as if that type were
    placed at (x, y, z) — used for placement preview.
    """
    if vtype is None:
        vtype = int(grid.get(x, y, z))
    if vtype == VOXEL_AIR:
        return []

    result: list[Connection] = []
    src = (x, y, z)

    if vtype in (VOXEL_PRESSURE_PLATE, VOXEL_ALARM_BELL):
        result.extend(_find_trigger(grid, x, y, z, vtype, src))
    if vtype in FLOW_TYPES:
        result.extend(_find_flow(grid, x, y, z, src))
    if vtype == VOXEL_HEAT_BEACON:
        result.extend(_find_thermal_beacon(grid, x, y, z, src))
    if vtype == VOXEL_STEAM_VENT:
        result.extend(_find_thermal_vent(grid, x, y, z, src))
    if vtype == VOXEL_ROLLING_STONE:
        result.extend(_find_structural_rolling(grid, x, y, z, src))
    if vtype == VOXEL_TARP:
        result.extend(_find_structural_tarp(grid, x, y, z, src))

    return result


# ── Private helpers ──────────────────────────────────────────────────

def _find_trigger(
    grid: VoxelGrid, x: int, y: int, z: int,
    vtype: int, src: tuple[int, int, int],
) -> list[Connection]:
    """Trigger connections: sensor → actuator within Chebyshev range."""
    radius = (
        PRESSURE_PLATE_TRIGGER_RANGE if vtype == VOXEL_PRESSURE_PLATE
        else ALARM_BELL_DETECTION_RANGE
    )
    conns: list[Connection] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                nx, ny, nz = x + dx, y + dy, z + dz
                neighbor = grid.get(nx, ny, nz)
                if neighbor in TRIGGER_TARGETS:
                    conns.append(Connection(
                        source=src,
                        target=(nx, ny, nz),
                        conn_type="trigger",
                        bidirectional=False,
                    ))
    return conns


def _find_flow(
    grid: VoxelGrid, x: int, y: int, z: int,
    src: tuple[int, int, int],
) -> list[Connection]:
    """Flow connections: pipe/pump ↔ adjacent pipe/pump (6-connected)."""
    conns: list[Connection] = []
    for dx, dy, dz in _OFFSETS_6:
        nx, ny, nz = x + dx, y + dy, z + dz
        neighbor = grid.get(nx, ny, nz)
        if neighbor in FLOW_TYPES:
            conns.append(Connection(
                source=src,
                target=(nx, ny, nz),
                conn_type="flow",
                bidirectional=True,
            ))
    return conns


def _find_thermal_beacon(
    grid: VoxelGrid, x: int, y: int, z: int,
    src: tuple[int, int, int],
) -> list[Connection]:
    """Thermal connections: heat beacon → all solid blocks within radius."""
    conns: list[Connection] = []
    r = HEAT_BEACON_THERMAL_RADIUS
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                nx, ny, nz = x + dx, y + dy, z + dz
                neighbor = grid.get(nx, ny, nz)
                if neighbor not in (VOXEL_AIR, VOXEL_WATER):
                    conns.append(Connection(
                        source=src,
                        target=(nx, ny, nz),
                        conn_type="thermal",
                        bidirectional=True,
                    ))
    return conns


def _find_thermal_vent(
    grid: VoxelGrid, x: int, y: int, z: int,
    src: tuple[int, int, int],
) -> list[Connection]:
    """Thermal connections: steam vent → cells directly above (shallower z)."""
    conns: list[Connection] = []
    for dz in range(1, STEAM_VENT_RANGE + 1):
        nz = z - dz  # Shallower z (toward surface)
        neighbor = grid.get(x, y, nz)
        if neighbor not in (VOXEL_AIR, VOXEL_WATER):
            conns.append(Connection(
                source=src,
                target=(x, y, nz),
                conn_type="thermal",
                bidirectional=True,
            ))
    return conns


def _find_structural_rolling(
    grid: VoxelGrid, x: int, y: int, z: int,
    src: tuple[int, int, int],
) -> list[Connection]:
    """Structural: rolling stone → slope/stairs below (deeper z)."""
    conns: list[Connection] = []
    nz = z + 1  # Deeper z (below)
    neighbor = grid.get(x, y, nz)
    if neighbor in (VOXEL_SLOPE, VOXEL_STAIRS):
        conns.append(Connection(
            source=src,
            target=(x, y, nz),
            conn_type="structural",
            bidirectional=False,
        ))
    return conns


def _find_structural_tarp(
    grid: VoxelGrid, x: int, y: int, z: int,
    src: tuple[int, int, int],
) -> list[Connection]:
    """Structural: tarp → support walls at ±x and ±y."""
    conns: list[Connection] = []
    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        nx, ny = x + dx, y + dy
        neighbor = grid.get(nx, ny, z)
        if neighbor not in (VOXEL_AIR, VOXEL_WATER):
            conns.append(Connection(
                source=src,
                target=(nx, ny, z),
                conn_type="structural",
                bidirectional=False,
            ))
    return conns
