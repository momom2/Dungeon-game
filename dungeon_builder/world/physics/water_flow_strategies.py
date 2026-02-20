"""Water flow strategy implementations: pluggable physics backends.

Two strategies are provided, both conforming to :class:`WaterFlowStrategy`:

1. **LatticeBoltzmannFlow** (default) -- D3Q7 lattice Boltzmann with BGK
   collision for velocity dynamics, plus pressure-driven conservative
   water transfer.  O(N*7) per tick.  Fully vectorized.
2. **JacobiProjectionFlow** -- Jacobi-smoothed pressure field with
   conservative water transfer.  O(W*k) where W = water cells,
   k = iterations.

Both strategies share a common pipeline: ``_gravity_flow()`` for downward
movement, ``_pressure_lateral_transfer()`` for pressure-driven lateral flow,
and ``_level_equalization()`` for convergence at low levels.

Use :func:`create_strategy` to instantiate the active strategy by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_FLOODGATE,
)

if TYPE_CHECKING:
    from dungeon_builder.world.voxel_grid import VoxelGrid


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class WaterFlowStrategy(Protocol):
    """Interface for pluggable water flow physics."""

    def init_arrays(self, grid: "VoxelGrid") -> None:
        """Allocate any extra arrays needed by this strategy."""
        ...

    def flow(self, grid: "VoxelGrid", water_physics: object) -> None:
        """Move water: gravity + lateral flow + bookkeeping."""
        ...

    def update_velocity(self, grid: "VoxelGrid", water_physics: object) -> None:
        """Compute / update the velocity field."""
        ...

    def apply_decay(self, grid: "VoxelGrid", water_physics: object) -> None:
        """Damp velocities (friction / viscosity)."""
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _advect_water_level(grid: "VoxelGrid") -> bool:
    """Move water_level along the velocity field (donor-cell upwind).

    Returns True if any water moved (for dirty-marking).

    The scheme is first-order upwind per axis: for each cell, the outflow
    in each direction is proportional to the velocity component in that
    direction, capped so that a cell can't send more than it has.  A delta
    accumulator per axis avoids double-counting.
    """
    voxels = grid.grid
    water = grid.water_level
    vx, vy, vz = grid.water_vx, grid.water_vy, grid.water_vz
    w, d, h = grid.width, grid.depth, grid.height

    water_before = (voxels == VOXEL_WATER).copy()

    moved = False

    # Process each of the 6 half-axes (+/-x, +/-y, +/-z).  For each axis we
    # compute transfer from cells with positive velocity toward the
    # neighbour in that direction.
    for axis, vel, dim in [(0, vx, w), (1, vy, d), (2, vz, h)]:
        if dim <= 1:
            continue

        # Build slices for source (src) and destination (dst) along *axis*.
        # Positive velocity: src = 0..dim-2, dst = 1..dim-1
        # Negative velocity: src = 1..dim-1, dst = 0..dim-2
        for sign in (+1, -1):
            if sign == 1:
                src_sl = [slice(None)] * 3
                dst_sl = [slice(None)] * 3
                src_sl[axis] = slice(None, -1)
                dst_sl[axis] = slice(1, None)
            else:
                src_sl = [slice(None)] * 3
                dst_sl = [slice(None)] * 3
                src_sl[axis] = slice(1, None)
                dst_sl[axis] = slice(None, -1)
            src_sl = tuple(src_sl)
            dst_sl = tuple(dst_sl)

            src_vel = vel[src_sl]
            active_vel = src_vel * sign  # positive when pointing src->dst
            sending = active_vel > 0

            # Only send from water cells into air or water cells
            src_water = (voxels[src_sl] == VOXEL_WATER)
            dst_ok = (
                (voxels[dst_sl] == VOXEL_AIR)
                | (voxels[dst_sl] == VOXEL_WATER)
                | (
                    (voxels[dst_sl] == VOXEL_FLOODGATE)
                    & (grid.block_state[dst_sl] == 0)
                )
            )
            mask = sending & src_water & dst_ok

            if not np.any(mask):
                continue

            # Transfer proportional to |velocity|, capped at source level
            # and remaining capacity of destination.
            # Allow velocities > 1 to transfer more water per tick.
            frac = np.clip(active_vel, 0.0, 2.0)
            src_level = water[src_sl].astype(np.int16)
            dst_level = water[dst_sl].astype(np.int16)
            transfer = np.where(
                mask,
                np.minimum(
                    (frac * src_level).astype(np.int16),
                    np.minimum(src_level, 255 - dst_level),
                ),
                np.int16(0),
            )

            if not np.any(transfer > 0):
                continue

            moved = True

            # Apply
            delta_src = np.zeros_like(water, dtype=np.int16)
            delta_dst = np.zeros_like(water, dtype=np.int16)
            delta_src[src_sl] -= transfer
            delta_dst[dst_sl] += transfer

            new_water = np.clip(
                water.astype(np.int16) + delta_src + delta_dst, 0, 255
            ).astype(np.uint8)
            water[:] = new_water

    # Bookkeeping: update VOXEL_WATER / VOXEL_AIR markers
    became_empty = (water == 0) & (voxels == VOXEL_WATER)
    voxels[became_empty] = VOXEL_AIR
    became_water = (water > 0) & (voxels == VOXEL_AIR)
    voxels[became_water] = VOXEL_WATER

    # Dirty marking
    if moved:
        water_after = (voxels == VOXEL_WATER)
        changed = water_before != water_after
        if np.any(changed):
            xs, ys, zs = np.where(changed)
            grid.mark_blocks_dirty(xs, ys, zs)

    return moved


def _pressure_lateral_transfer(
    water: np.ndarray,
    voxels: np.ndarray,
    pressure: np.ndarray,
    alpha: float,
    w: int, d: int, h: int,
) -> None:
    """Transfer water laterally along pressure gradients (conservative).

    Processes each axis independently, applying transfers to ``water``
    between axes.  Within each axis, per-face outflow is capped at **half**
    the source's current water level so that a cell sending on two faces
    (left and right) can never drain more than it holds.

    Used by LatticeBoltzmann and Jacobi strategies.
    The transfer rate is controlled purely by the *alpha* parameter and the
    pressure field -- no ad-hoc accelerators are applied.
    """
    fluid_ok = (voxels == VOXEL_WATER) | (voxels == VOXEL_AIR)

    for axis, dim in [(0, w), (1, d)]:
        if dim <= 1:
            continue

        lo_sl = [slice(None)] * 3
        hi_sl = [slice(None)] * 3
        lo_sl[axis] = slice(None, -1)
        hi_sl[axis] = slice(1, None)
        lo_sl, hi_sl = tuple(lo_sl), tuple(hi_sl)

        p_lo = pressure[lo_sl]
        p_hi = pressure[hi_sl]
        # Read current water levels (updated from previous axis)
        w_lo = water[lo_sl].astype(np.int16)
        w_hi = water[hi_sl].astype(np.int16)

        dp = p_lo - p_hi

        can_flow = (
            fluid_ok[lo_sl] & fluid_ok[hi_sl]
            & ((voxels[lo_sl] == VOXEL_WATER)
               | (voxels[hi_sl] == VOXEL_WATER))
        )

        # Transfer from pressure gradient
        transfer_int = np.clip(dp * alpha, -127, 127).astype(np.int16)

        # Cap each face's outflow at HALF the source's level.
        half_lo = w_lo >> 1
        half_hi = w_hi >> 1

        # Positive: lo -> hi
        pos = can_flow & (transfer_int > 0)
        pos_t = np.where(
            pos,
            np.minimum(transfer_int, np.minimum(half_lo, 255 - w_hi)),
            np.int16(0),
        )

        # Negative: hi -> lo
        neg = can_flow & (transfer_int < 0)
        neg_t = np.where(
            neg,
            np.minimum(-transfer_int, np.minimum(half_hi, 255 - w_lo)),
            np.int16(0),
        )

        # Accumulate per-axis delta, then apply.
        delta = np.zeros((w, d, h), dtype=np.int16)
        delta[lo_sl] -= pos_t
        delta[lo_sl] += neg_t
        delta[hi_sl] += pos_t
        delta[hi_sl] -= neg_t

        water[:] = np.clip(
            water.astype(np.int16) + delta, 0, 255
        ).astype(np.uint8)

    # Bookkeeping
    became_empty = (water == 0) & (voxels == VOXEL_WATER)
    voxels[became_empty] = VOXEL_AIR
    became_water = (water > 0) & (voxels == VOXEL_AIR)
    voxels[became_water] = VOXEL_WATER


def _level_equalization(
    water: np.ndarray,
    voxels: np.ndarray,
    rate: float,
    w: int, d: int, h: int,
) -> None:
    """Equalize water levels between adjacent fluid cells (conservative).

    Transfers a fraction of the level difference between neighbors at the
    same z-level.  This ensures convergence to uniform levels even when
    integer pressure transfers stall at low values.

    Processes axes sequentially (like ``_pressure_lateral_transfer``) and
    caps per-face transfer at a quarter of the source level (conservative
    for up to 4 lateral neighbors).
    """
    fluid_ok = (voxels == VOXEL_WATER) | (voxels == VOXEL_AIR)
    eq_rate = max(0.25, rate)  # minimum equalization rate

    for axis, dim in [(0, w), (1, d)]:
        if dim <= 1:
            continue

        lo_sl = [slice(None)] * 3
        hi_sl = [slice(None)] * 3
        lo_sl[axis] = slice(None, -1)
        hi_sl[axis] = slice(1, None)
        lo_sl, hi_sl = tuple(lo_sl), tuple(hi_sl)

        w_lo = water[lo_sl].astype(np.int16)
        w_hi = water[hi_sl].astype(np.int16)

        # Level difference: positive = lo has more, negative = hi has more
        diff = w_lo - w_hi

        can_flow = (
            fluid_ok[lo_sl] & fluid_ok[hi_sl]
            & ((voxels[lo_sl] == VOXEL_WATER)
               | (voxels[hi_sl] == VOXEL_WATER))
        )

        # Transfer a fraction of the level difference
        transfer_raw = (diff.astype(np.float32) * eq_rate).astype(np.int16)

        # Cap at quarter of source level (4 faces per cell -> total <= level)
        quarter_lo = w_lo >> 2
        quarter_hi = w_hi >> 2

        # Positive: lo -> hi
        pos = can_flow & (transfer_raw > 0)
        pos_t = np.where(
            pos,
            np.minimum(transfer_raw, np.minimum(quarter_lo, 255 - w_hi)),
            np.int16(0),
        )

        # Negative: hi -> lo
        neg = can_flow & (transfer_raw < 0)
        neg_t = np.where(
            neg,
            np.minimum(-transfer_raw, np.minimum(quarter_hi, 255 - w_lo)),
            np.int16(0),
        )

        delta = np.zeros((w, d, h), dtype=np.int16)
        delta[lo_sl] -= pos_t
        delta[lo_sl] += neg_t
        delta[hi_sl] += pos_t
        delta[hi_sl] -= neg_t

        water[:] = np.clip(
            water.astype(np.int16) + delta, 0, 255
        ).astype(np.uint8)

    # Bookkeeping
    became_empty = (water == 0) & (voxels == VOXEL_WATER)
    voxels[became_empty] = VOXEL_AIR
    became_water = (water > 0) & (voxels == VOXEL_AIR)
    voxels[became_water] = VOXEL_WATER


def _gravity_flow(grid: "VoxelGrid") -> bool:
    """Move water downward (gravity): water above air falls.

    Shared by strategies so they all handle gravity identically to the
    cellular automata baseline.  Returns True if any water fell.
    """
    voxels = grid.grid
    water = grid.water_level
    h = grid.height

    if h <= 1:
        return False

    water_above = (voxels[:, :, :-1] == VOXEL_WATER)
    below_type = voxels[:, :, 1:]
    air_below = (below_type == VOXEL_AIR)
    gate_below = (
        (below_type == VOXEL_FLOODGATE)
        & (grid.block_state[:, :, 1:] == 0)
    )
    can_flow_down = water_above & (air_below | gate_below)

    if not np.any(can_flow_down):
        return False

    level_above = water[:, :, :-1].copy()
    transfer = np.where(can_flow_down, level_above, np.uint8(0))

    water[:, :, 1:] = np.where(
        can_flow_down,
        np.minimum(
            water[:, :, 1:].astype(np.int16) + transfer.astype(np.int16),
            255,
        ).astype(np.uint8),
        water[:, :, 1:],
    )
    voxels[:, :, 1:] = np.where(
        can_flow_down & (water[:, :, 1:] > 0),
        VOXEL_WATER,
        voxels[:, :, 1:],
    )

    water[:, :, :-1] = np.where(can_flow_down, np.uint8(0), water[:, :, :-1])
    voxels[:, :, :-1] = np.where(
        can_flow_down, VOXEL_AIR, voxels[:, :, :-1]
    )

    return True


def _compute_depth_map(water_mask: np.ndarray, w: int, d: int, h: int
                       ) -> np.ndarray:
    """Compute hydrostatic depth map using cumulative sum.

    For each column, depth counts consecutive water cells from top to
    bottom.  Uses vectorized cumsum with reset-on-break for efficiency.
    """
    # Build a depth counter via cumsum that resets at non-water cells.
    # For each (x,y) column, we want depth[z] = number of consecutive
    # water cells above (and including) z.
    #
    # Trick: cumsum of water_mask along z gives total water cells from z=0
    # to z.  We need consecutive runs.  Subtract the cumsum at the last
    # non-water cell to get run lengths.
    wm_int = water_mask.astype(np.float32)
    cs = np.cumsum(wm_int, axis=2)
    # At each non-water cell, record the cumsum value for resetting
    reset = np.where(water_mask, 0.0, cs)
    # Forward-fill the reset values: use maximum.accumulate on reset
    # (works because cumsum is monotonically increasing)
    reset_filled = np.maximum.accumulate(reset, axis=2)
    depth_map = cs - reset_filled
    return depth_map


def _laplacian_scalar(field: np.ndarray, mask_f: np.ndarray,
                      w: int, d: int, h: int) -> np.ndarray:
    """Compute Laplacian of a scalar field at masked cells (shared helper)."""
    lap = np.zeros((w, d, h), dtype=np.float32)
    cnt = np.zeros((w, d, h), dtype=np.float32)
    if w > 1:
        lap[:-1] += field[1:] * mask_f[1:]
        lap[1:] += field[:-1] * mask_f[:-1]
        cnt[:-1] += mask_f[1:]
        cnt[1:] += mask_f[:-1]
    if d > 1:
        lap[:, :-1] += field[:, 1:] * mask_f[:, 1:]
        lap[:, 1:] += field[:, :-1] * mask_f[:, :-1]
        cnt[:, :-1] += mask_f[:, 1:]
        cnt[:, 1:] += mask_f[:, :-1]
    if h > 1:
        lap[:, :, :-1] += field[:, :, 1:] * mask_f[:, :, 1:]
        lap[:, :, 1:] += field[:, :, :-1] * mask_f[:, :, :-1]
        cnt[:, :, :-1] += mask_f[:, :, 1:]
        cnt[:, :, 1:] += mask_f[:, :, :-1]
    np.maximum(cnt, 1.0, out=cnt)
    lap = lap / cnt - field
    return lap


def _divergence(vx: np.ndarray, vy: np.ndarray, vz: np.ndarray,
                mask_f: np.ndarray, w: int, d: int, h: int) -> np.ndarray:
    """Compute divergence div(v) using central differences at masked cells."""
    div = np.zeros((w, d, h), dtype=np.float32)
    if w > 2:
        div[1:-1, :, :] += (vx[2:, :, :] - vx[:-2, :, :]) * 0.5
    if w > 1:
        div[0, :, :] += vx[1, :, :] - vx[0, :, :]
        div[-1, :, :] += vx[-1, :, :] - vx[-2, :, :]
    if d > 2:
        div[:, 1:-1, :] += (vy[:, 2:, :] - vy[:, :-2, :]) * 0.5
    if d > 1:
        div[:, 0, :] += vy[:, 1, :] - vy[:, 0, :]
        div[:, -1, :] += vy[:, -1, :] - vy[:, -2, :]
    if h > 2:
        div[:, :, 1:-1] += (vz[:, :, 2:] - vz[:, :, :-2]) * 0.5
    if h > 1:
        div[:, :, 0] += vz[:, :, 1] - vz[:, :, 0]
        div[:, :, -1] += vz[:, :, -1] - vz[:, :, -2]
    div *= mask_f
    return div


def _gradient_pressure(pressure: np.ndarray, solid: np.ndarray,
                       mask_f: np.ndarray, w: int, d: int, h: int
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute grad(p) with Neumann BC at solid walls.

    At solid boundaries the pressure gradient normal to the wall is zero
    (no-penetration).  At fluid boundaries (water next to air), the air
    pressure is 0 so the gradient correctly pushes water outward.

    Optimized: computes forward + backward differences in-place using a
    single temp buffer per axis instead of two.
    """
    p = pressure
    gx = np.zeros((w, d, h), dtype=np.float32)
    gy = np.zeros((w, d, h), dtype=np.float32)
    gz = np.zeros((w, d, h), dtype=np.float32)

    if w > 1:
        # diff = p[i+1] - p[i] for all adjacent pairs
        diff_x = p[1:, :, :] - p[:-1, :, :]
        # Forward: apply where neighbor is not solid
        sol_hi = solid[1:, :, :]
        fwd = np.where(sol_hi, 0.0, diff_x)
        # Backward: apply where neighbor is not solid
        sol_lo = solid[:-1, :, :]
        bwd = np.where(sol_lo, 0.0, diff_x)
        # Average: gx[i] = (fwd[i] + bwd[i]) * 0.5
        gx[:-1] += fwd
        gx[1:] += bwd
        gx *= 0.5

    if d > 1:
        diff_y = p[:, 1:, :] - p[:, :-1, :]
        sol_hi = solid[:, 1:, :]
        fwd = np.where(sol_hi, 0.0, diff_y)
        sol_lo = solid[:, :-1, :]
        bwd = np.where(sol_lo, 0.0, diff_y)
        gy[:, :-1] += fwd
        gy[:, 1:] += bwd
        gy *= 0.5

    if h > 1:
        diff_z = p[:, :, 1:] - p[:, :, :-1]
        sol_hi = solid[:, :, 1:]
        fwd = np.where(sol_hi, 0.0, diff_z)
        sol_lo = solid[:, :, :-1]
        bwd = np.where(sol_lo, 0.0, diff_z)
        gz[:, :, :-1] += fwd
        gz[:, :, 1:] += bwd
        gz *= 0.5

    # Only apply at water cells
    gx *= mask_f
    gy *= mask_f
    gz *= mask_f
    return gx, gy, gz


# ---------------------------------------------------------------------------
# 1. Lattice Boltzmann D3Q7  (fully vectorized -- no Python loops over dirs)
# ---------------------------------------------------------------------------

# D3Q7 lattice: rest + 6 cardinal directions
# Indices: 0=rest, 1=+x, 2=-x, 3=+y, 4=-y, 5=+z(down), 6=-z(up)
_D3Q7_E = np.array([
    [0, 0, 0],   # rest
    [1, 0, 0],   # +x
    [-1, 0, 0],  # -x
    [0, 1, 0],   # +y
    [0, -1, 0],  # -y
    [0, 0, 1],   # +z (down in our coord system)
    [0, 0, -1],  # -z (up)
], dtype=np.int8)

_D3Q7_W = np.array([1.0 / 4.0] + [1.0 / 8.0] * 6, dtype=np.float32)

# Opposite direction indices for bounce-back
_D3Q7_OPP = np.array([0, 2, 1, 4, 3, 6, 5], dtype=np.int8)

# Pre-computed direction pairs: (dir_index, opp_index, axis, sign)
# Used by the streaming step to avoid building slices in a Python loop.
# For dir i with displacement (ex,ey,ez): axis = which axis, sign = +1/-1
_LBM_DIR_INFO = [
    # (i, opp, axis, sign)
    (1, 2, 0, +1),   # +x
    (2, 1, 0, -1),   # -x
    (3, 4, 1, +1),   # +y
    (4, 3, 1, -1),   # -y
    (5, 6, 2, +1),   # +z (down)
    (6, 5, 2, -1),   # -z (up)
]


def _build_lbm_slices(w: int, d: int, h: int
                      ) -> list[tuple[tuple, tuple, int, int]]:
    """Build (src_slice, dst_slice, dir_idx, opp_idx) for each LBM direction.

    Cached by the LBM strategy after init to avoid per-tick slice creation.
    """
    result = []
    for i, opp, axis, sign in _LBM_DIR_INFO:
        src = [slice(None)] * 3
        dst = [slice(None)] * 3
        if sign > 0:
            src[axis] = slice(None, -1)
            dst[axis] = slice(1, None)
        else:
            src[axis] = slice(1, None)
            dst[axis] = slice(None, -1)
        result.append((tuple(src), tuple(dst), i, opp))
    return result


class LatticeBoltzmannFlow:
    """D3Q7 Lattice Boltzmann with BGK collision for velocity dynamics.

    Uses _gravity_flow() for reliable gravity and _pressure_lateral_transfer()
    + _level_equalization() for conservative water movement (same as Jacobi).
    The LBM collision+streaming runs on a separate density field to compute
    velocity and pressure -- these are then used for rendering and to drive
    the pressure-based transfer.

    This avoids the fundamental conflict between LBM's float32 distributions
    and the game's uint8 water_level system: LBM computes the physics, but
    the integer-conservative helpers move the actual water.

    Optimizations vs. naive implementation:
    - Pre-computed slice tuples for streaming (no per-tick slice building)
    - Manual e_dot_u computation instead of einsum (D3Q7 has trivial vectors)
    - Vectorized depth map via cumsum instead of Python z-loop
    - Pre-allocated f_new buffer reused across ticks
    """

    def __init__(self) -> None:
        self._slices: list[tuple[tuple, tuple, int, int]] | None = None
        self._f_new: np.ndarray | None = None
        self._f_eq: np.ndarray | None = None
        self._grid_shape: tuple[int, int, int] | None = None

    def _ensure_buffers(self, w: int, d: int, h: int,
                        f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Ensure work buffers are allocated and match the grid size.

        Returns (f_new, f_eq) pre-allocated work arrays.
        """
        shape = (w, d, h)
        if self._grid_shape != shape:
            self._slices = _build_lbm_slices(w, d, h)
            self._f_new = np.zeros_like(f)
            self._f_eq = np.empty_like(f)
            self._grid_shape = shape
        return self._f_new, self._f_eq  # type: ignore[return-value]

    def init_arrays(self, grid: "VoxelGrid") -> None:
        f = grid.ensure_lbm_arrays()
        voxels = grid.grid
        water = grid.water_level
        water_mask = (voxels == VOXEL_WATER)

        rho = np.where(
            water_mask,
            water.astype(np.float32) / 255.0,
            0.0,
        )
        f[:] = _D3Q7_W[np.newaxis, np.newaxis, np.newaxis, :] * rho[:, :, :, np.newaxis]

    def flow(self, grid: "VoxelGrid", water_physics: object) -> None:
        import dungeon_builder.config as _cfg

        voxels = grid.grid
        water = grid.water_level
        pressure = grid.water_pressure
        vx, vy, vz = grid.water_vx, grid.water_vy, grid.water_vz
        w, d, h = grid.width, grid.depth, grid.height
        f = grid.ensure_lbm_arrays()

        tau = _cfg.LBM_TAU
        g_force = _cfg.LBM_GRAVITY
        rest_density = _cfg.LBM_REST_DENSITY

        water_before = (voxels == VOXEL_WATER).copy()

        # -- 1. Gravity via direct transfer (reliable, same as CA) --
        _gravity_flow(grid)

        water_mask = (voxels == VOXEL_WATER)
        if not np.any(water_mask):
            pressure[:] = 0.0
            return

        # -- 2. LBM collision+streaming for velocity field --
        # Sync distributions to current water state
        wf = water.astype(np.float32)
        target_rho = np.where(water_mask, wf * (rest_density / 255.0), 0.0)
        current_rho = f.sum(axis=3)

        # Init cells with no distributions
        needs_init = water_mask & (current_rho < 1e-10)
        if np.any(needs_init):
            f[needs_init] = _D3Q7_W[np.newaxis, :] * target_rho[needs_init, np.newaxis]

        # Rescale cells where water_level changed
        has_rho = water_mask & (current_rho > 1e-10)
        rho_safe_cur = np.maximum(current_rho, 1e-10)
        scale = np.where(has_rho, target_rho / rho_safe_cur, 1.0)
        needs_rescale = has_rho & (np.abs(scale - 1.0) > 0.01)
        if np.any(needs_rescale):
            f[needs_rescale] *= scale[needs_rescale, np.newaxis]

        f[~water_mask] = 0.0

        # Macroscopic quantities
        rho = f.sum(axis=3)
        rho_safe = np.maximum(rho, 1e-10)

        # Extract velocity components directly (no einsum needed for D3Q7)
        ux = (f[:, :, :, 1] - f[:, :, :, 2]) / rho_safe
        uy = (f[:, :, :, 3] - f[:, :, :, 4]) / rho_safe
        uz = (f[:, :, :, 5] - f[:, :, :, 6]) / rho_safe

        # Equilibrium distribution -- manual e_dot_u for D3Q7
        # Uses pre-allocated f_eq buffer to avoid per-tick allocation.
        f_new, f_eq = self._ensure_buffers(w, d, h, f)
        w0 = _D3Q7_W[0]
        w1 = _D3Q7_W[1]  # same for all dirs 1-6

        f_eq[:, :, :, 0] = w0 * rho
        f_eq[:, :, :, 1] = w1 * rho * (1.0 + 3.0 * ux)
        f_eq[:, :, :, 2] = w1 * rho * (1.0 - 3.0 * ux)
        f_eq[:, :, :, 3] = w1 * rho * (1.0 + 3.0 * uy)
        f_eq[:, :, :, 4] = w1 * rho * (1.0 - 3.0 * uy)
        f_eq[:, :, :, 5] = w1 * rho * (1.0 + 3.0 * uz)
        f_eq[:, :, :, 6] = w1 * rho * (1.0 - 3.0 * uz)

        # BGK collision at water cells only
        inv_tau = 1.0 / tau
        wm_4d = water_mask[:, :, :, np.newaxis]
        f[:] = np.where(wm_4d, f - inv_tau * (f - f_eq), f)

        # Gravity body force -- safe to apply everywhere since non-water
        # cells are zero (adding gravity_term to zero is harmless; they get
        # zeroed again after streaming via f_new[~water_mask] = 0).
        gravity_term = w1 * 3.0 * g_force
        wm_f32 = water_mask.astype(np.float32)
        f[:, :, :, 5] += gravity_term * wm_f32
        f[:, :, :, 6] -= gravity_term * wm_f32

        # Streaming with bounce-back using pre-computed slices
        solid_mask = (voxels != VOXEL_WATER) & (voxels != VOXEL_AIR)
        f_new[:] = 0.0
        f_new[:, :, :, 0] = f[:, :, :, 0]

        for src_sl, dst_sl, i, opp in self._slices:  # type: ignore[union-attr]
            dst_solid = solid_mask[dst_sl]
            src_water = water_mask[src_sl]
            f_src = np.where(src_water, f[src_sl[0], src_sl[1], src_sl[2], i], 0.0)

            # Stream to fluid, bounce-back at solid
            f_new[dst_sl[0], dst_sl[1], dst_sl[2], i] += np.where(
                ~dst_solid, f_src, 0.0
            )
            f_new[src_sl[0], src_sl[1], src_sl[2], opp] += np.where(
                dst_solid, f_src, 0.0
            )

            # Boundary bounce-back (edge of grid)
            _, _, axis, sign = _LBM_DIR_INFO[i - 1]
            if sign > 0:
                # Boundary at high end of axis
                bnd = [slice(None)] * 3
                bnd[axis] = -1
                bnd_t = tuple(bnd)
                m = water_mask[bnd_t]
                f_new[bnd_t[0], bnd_t[1], bnd_t[2], opp] += np.where(
                    m, f[bnd_t[0], bnd_t[1], bnd_t[2], i], 0.0
                )
            else:
                # Boundary at low end of axis
                bnd = [slice(None)] * 3
                bnd[axis] = 0
                bnd_t = tuple(bnd)
                m = water_mask[bnd_t]
                f_new[bnd_t[0], bnd_t[1], bnd_t[2], opp] += np.where(
                    m, f[bnd_t[0], bnd_t[1], bnd_t[2], i], 0.0
                )

        f_new[solid_mask] = 0.0
        f_new[~water_mask] = 0.0
        f[:] = f_new

        # Extract post-streaming velocity for rendering
        rho_post = f.sum(axis=3)
        rho_post_safe = np.maximum(rho_post, 1e-10)
        ux = (f[:, :, :, 1] - f[:, :, :, 2]) / rho_post_safe
        uy = (f[:, :, :, 3] - f[:, :, :, 4]) / rho_post_safe
        uz = (f[:, :, :, 5] - f[:, :, :, 6]) / rho_post_safe

        # -- 3. Pressure from equation of state + hydrostatic depth --
        pressure[:] = np.where(water_mask, wf, 0.0)

        depth_map = _compute_depth_map(water_mask, w, d, h)
        pressure += depth_map * 20.0  # beta(4.0) * hydro_scale(5.0)

        # -- 4. Pressure-driven lateral transfer (conservative) --
        alpha = _cfg.LBM_PRESSURE_DIFFUSION
        _pressure_lateral_transfer(water, voxels, pressure, alpha, w, d, h)

        # -- 5. Level equalization --
        _level_equalization(water, voxels, 0.15, w, d, h)

        # -- 6. Write velocity from LBM to grid --
        final_water = (voxels == VOXEL_WATER)
        vx[:] = np.where(final_water, ux, 0.0)
        vy[:] = np.where(final_water, uy, 0.0)
        vz[:] = np.where(final_water, uz, 0.0)

        # Dirty marking
        water_after = (voxels == VOXEL_WATER)
        changed = water_before != water_after
        if np.any(changed):
            xs, ys, zs = np.where(changed)
            grid.mark_blocks_dirty(xs, ys, zs)

    def update_velocity(self, grid: "VoxelGrid", water_physics: object) -> None:
        # Velocity extracted inside flow()
        pass

    def apply_decay(self, grid: "VoxelGrid", water_physics: object) -> None:
        # LBM handles dissipation through tau (relaxation time)
        eps = 0.01
        small = (
            (np.abs(grid.water_vx) < eps)
            & (np.abs(grid.water_vy) < eps)
            & (np.abs(grid.water_vz) < eps)
        )
        grid.water_vx[small] = 0.0
        grid.water_vy[small] = 0.0
        grid.water_vz[small] = 0.0


# ---------------------------------------------------------------------------
# 2. Jacobi Projection
# ---------------------------------------------------------------------------

class JacobiProjectionFlow:
    """Pressure projection with Jacobi-smoothed pressure field.

    Uses _gravity_flow() for reliable gravity, then computes a pressure
    field via Jacobi iterations and transfers water along pressure
    gradients.  The Jacobi smoothing spreads pressure information across
    the water body faster than per-cell differences, enabling water to
    "feel" distant level differences and flow toward them.

    1. Gravity via direct transfer (same as CA)
    2. Compute pressure from water density + hydrostatic depth
    3. Jacobi iterations: smooth pressure across water body
    4. Transfer water along pressure gradients

    Optimizations vs. naive:
    - Pre-allocated work buffers (p_sum, n_nbr) reused across iterations
    - Vectorized depth map via cumsum
    """

    def __init__(self) -> None:
        self._p_sum: np.ndarray | None = None
        self._n_nbr: np.ndarray | None = None
        self._grid_shape: tuple[int, int, int] | None = None

    def _ensure_buffers(self, w: int, d: int, h: int) -> None:
        """Pre-allocate Jacobi iteration work buffers."""
        shape = (w, d, h)
        if self._grid_shape != shape:
            self._p_sum = np.empty(shape, dtype=np.float32)
            self._n_nbr = np.empty(shape, dtype=np.float32)
            self._grid_shape = shape

    def init_arrays(self, grid: "VoxelGrid") -> None:
        grid.water_pressure[:] = 0.0

    def flow(self, grid: "VoxelGrid", water_physics: object) -> None:
        import dungeon_builder.config as _cfg

        voxels = grid.grid
        water = grid.water_level
        pressure = grid.water_pressure
        vx, vy, vz = grid.water_vx, grid.water_vy, grid.water_vz
        w, d, h = grid.width, grid.depth, grid.height

        n_iter = int(_cfg.JACOBI_ITERATIONS)
        friction = _cfg.JACOBI_FRICTION
        gravity = _cfg.JACOBI_GRAVITY
        viscosity = _cfg.JACOBI_VISCOSITY

        water_before = (voxels == VOXEL_WATER).copy()

        # -- 1. Gravity via direct transfer --
        _gravity_flow(grid)

        water_mask = (voxels == VOXEL_WATER)
        if not np.any(water_mask):
            pressure[:] = 0.0
            return

        wm_f = water_mask.astype(np.float32)

        # -- 2. Pressure from equation of state --
        wl_f = water.astype(np.float32)
        pressure[:] = np.where(water_mask, wl_f, 0.0)

        # Add hydrostatic component (deeper = higher pressure)
        depth_map = _compute_depth_map(water_mask, w, d, h)
        pressure += depth_map * (gravity * 10.0)

        # -- 3. Jacobi smoothing with pre-allocated buffers --
        self._ensure_buffers(w, d, h)
        p_sum = self._p_sum
        n_nbr = self._n_nbr

        for _ in range(n_iter):
            np.copyto(p_sum, pressure)      # start with self
            np.copyto(n_nbr, wm_f)          # count self
            if w > 1:
                p_sum[:-1] += pressure[1:] * wm_f[1:]
                p_sum[1:] += pressure[:-1] * wm_f[:-1]
                n_nbr[:-1] += wm_f[1:]
                n_nbr[1:] += wm_f[:-1]
            if d > 1:
                p_sum[:, :-1] += pressure[:, 1:] * wm_f[:, 1:]
                p_sum[:, 1:] += pressure[:, :-1] * wm_f[:, :-1]
                n_nbr[:, :-1] += wm_f[:, 1:]
                n_nbr[:, 1:] += wm_f[:, :-1]
            if h > 1:
                p_sum[:, :, :-1] += pressure[:, :, 1:] * wm_f[:, :, 1:]
                p_sum[:, :, 1:] += pressure[:, :, :-1] * wm_f[:, :, :-1]
                n_nbr[:, :, :-1] += wm_f[:, :, 1:]
                n_nbr[:, :, 1:] += wm_f[:, :, :-1]

            np.maximum(n_nbr, 1.0, out=n_nbr)
            p_sum /= n_nbr  # p_new = p_sum / n_nbr (in-place)
            pressure[:] = np.where(
                water_mask,
                pressure * 0.3 + p_sum * 0.7,
                0.0,
            )

        # -- 4. Pressure-driven lateral water transfer (conservative) --
        alpha = _cfg.JACOBI_PRESSURE_DIFFUSION
        _pressure_lateral_transfer(water, voxels, pressure, alpha, w, d, h)

        # -- 5. Direct level equalization --
        _level_equalization(water, voxels, viscosity, w, d, h)

        # -- Update velocity for rendering --
        solid = (voxels != VOXEL_WATER) & (voxels != VOXEL_AIR)
        wm_f2 = (voxels == VOXEL_WATER).astype(np.float32)
        gpx, gpy, gpz = _gradient_pressure(
            pressure, solid, wm_f2, w, d, h
        )
        vx[:] = np.where(voxels == VOXEL_WATER, -gpx * 0.3, 0.0)
        vy[:] = np.where(voxels == VOXEL_WATER, -gpy * 0.3, 0.0)
        vz[:] = np.where(voxels == VOXEL_WATER, -gpz * 0.3, 0.0)

        vx *= friction
        vy *= friction
        vz *= friction

        # Dirty marking
        water_after = (voxels == VOXEL_WATER)
        changed = water_before != water_after
        if np.any(changed):
            xs, ys, zs = np.where(changed)
            grid.mark_blocks_dirty(xs, ys, zs)

    def update_velocity(self, grid: "VoxelGrid", water_physics: object) -> None:
        pass

    def apply_decay(self, grid: "VoxelGrid", water_physics: object) -> None:
        eps = 0.01
        small = (
            (np.abs(grid.water_vx) < eps)
            & (np.abs(grid.water_vy) < eps)
            & (np.abs(grid.water_vz) < eps)
        )
        grid.water_vx[small] = 0.0
        grid.water_vy[small] = 0.0
        grid.water_vz[small] = 0.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_STRATEGY_MAP = {
    "lattice_boltzmann": LatticeBoltzmannFlow,
    "jacobi_projection": JacobiProjectionFlow,
}


def create_strategy(model_name: str) -> WaterFlowStrategy:
    """Create a water flow strategy by config name."""
    cls = _STRATEGY_MAP.get(model_name)
    if cls is None:
        raise ValueError(
            f"Unknown water flow model {model_name!r}. "
            f"Choose from: {list(_STRATEGY_MAP)}"
        )
    return cls()  # type: ignore[return-value]
