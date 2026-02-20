"""Water & lava fluid physics: pluggable flow strategies, pressure, and interaction.

Water flow is handled by pluggable strategies (Lattice Boltzmann or Jacobi
Projection) — see :mod:`water_flow_strategies`.  This module orchestrates
the tick pipeline: sources/sinks → lava interaction → strategy.flow() →
lava flow → velocity/decay → seepage → pressure → evaporation → cleanup.

Lava additionally carries heat with its flow (flow-based convection) and
transports discrete mana crystals probabilistically.

Water level is tracked per-voxel as uint8 (0-255); lava_level likewise.
A voxel is typed VOXEL_WATER when water_level > 0 and VOXEL_LAVA when
lava_level > 0.  When levels reach 0, voxels revert to VOXEL_AIR.
"""

from __future__ import annotations

import numpy as np
import random
from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_LAVA,
    VOXEL_OBSIDIAN,
    VOXEL_DOOR,
    VOXEL_FLOODGATE,
    VOXEL_WATER_SOURCE,
    VOXEL_WATER_SINK,
    VOXEL_LAVA_SOURCE,
    VOXEL_LAVA_SINK,
    VOXEL_POROSITY,
    VOXEL_SHEAR_STRENGTH,
    VOXEL_WEIGHT,
    SURFACE_Z,
    WATER_TICK_INTERVAL,
    WATER_SEEP_RATE,
    WATER_PRESSURE_WEIGHT,
    WATER_BURST_FACTOR,
    WATER_HUMIDITY_SOURCE,
    WATER_TEMPERATURE,
    WATER_EVAPORATION_RATE,
    WATER_LAVA_PRODUCT,
    WATER_SOURCE_OUTPUT,
    LAVA_TEMPERATURE,
    MAX_CASCADE_PER_TICK,
    METAL_STRENGTH_MULT,
    ENCHANTED_OFFSET,
    LAVA_FLOW_RATE,
    MAX_LAVA_FLOW_PER_TICK,
    LAVA_SOURCE_OUTPUT,
    LAVA_PRESSURE_WEIGHT,
    LAVA_BURST_FACTOR,
    MANA_CRYSTAL_SPAWN_CHANCE,
)
from dungeon_builder.world.physics.water_flow_strategies import create_strategy

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid


class WaterPhysics:
    """Pluggable fluid flow for water (LBM/Jacobi) and lava (cellular automata).

    Runs every WATER_TICK_INTERVAL ticks.
    - Water flow: delegated to pluggable strategy (LBM or Jacobi)
    - Seepage: water increases humidity of adjacent porous solids
    - Pressure: column depth exerts shear load on adjacent solid walls
    - Burst: if pressure > shear_strength * BURST_FACTOR, wall bursts
    - Lava-water interaction: probabilistic obsidian formation
    - Lava heat transport: heat moves with lava flow
    - Mana crystal drift: discrete crystals move probabilistically with flow
    """

    def __init__(self, event_bus: EventBus, voxel_grid: VoxelGrid) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid

        # Pre-build LUTs
        self._porosity_lut = np.zeros(256, dtype=np.float32)
        for vtype, poro in VOXEL_POROSITY.items():
            if 0 <= vtype < 256:
                self._porosity_lut[vtype] = poro

        self._shear_lut = np.zeros(256, dtype=np.float32)
        for vtype, shear in VOXEL_SHEAR_STRENGTH.items():
            if 0 <= vtype < 256:
                self._shear_lut[vtype] = min(shear, 1e9)

        self._weight_lut = np.zeros(256, dtype=np.float32)
        for vtype, w in VOXEL_WEIGHT.items():
            if 0 <= vtype < 256:
                self._weight_lut[vtype] = w

        # Lava flow tracking: per-direction outflow arrays for heat/mana transport.
        # Allocated once and reused each tick to avoid allocation churn.
        # Shape will be set on first tick.
        self._lava_outflow: dict[str, np.ndarray] | None = None

        # Water flow strategy (pluggable physics backend)
        # Read from module (not the import-time copy) so tests can monkeypatch
        import dungeon_builder.config as _cfg_mod
        self._current_model = _cfg_mod.WATER_FLOW_MODEL
        self._strategy = create_strategy(self._current_model)
        self._strategy.init_arrays(voxel_grid)

        event_bus.subscribe("config_changed", self._on_config_changed)
        event_bus.subscribe("tick", self._on_tick)

    def _on_config_changed(self, **kw) -> None:
        """Hot-swap the water flow strategy when the user changes it."""
        import dungeon_builder.config as _cfg
        if _cfg.WATER_FLOW_MODEL != self._current_model:
            self._current_model = _cfg.WATER_FLOW_MODEL
            self._strategy = create_strategy(self._current_model)
            self._strategy.init_arrays(self.voxel_grid)

    def _on_tick(self, tick: int, **kw) -> None:
        if tick % WATER_TICK_INTERVAL != 0:
            return
        self._apply_sources_and_sinks()
        self._lava_water_interaction()
        self._strategy.flow(self.voxel_grid, self)
        self._flow_lava()
        self._transport_lava_heat()
        self._drift_mana_crystals()
        self._strategy.update_velocity(self.voxel_grid, self)
        self._strategy.apply_decay(self.voxel_grid, self)
        self._apply_seepage()
        self._apply_pressure()
        self._surface_evaporation()
        self._cleanup()
        # Notify renderer that water has changed so dirty chunks are flushed.
        self.event_bus.publish("water_flowed")

    # ------------------------------------------------------------------
    # Sources and sinks
    # ------------------------------------------------------------------

    def _apply_sources_and_sinks(self) -> None:
        """Enforce source/sink invariants before flow processing.

        Water sources: adjacent air → VOXEL_WATER at full level;
                       adjacent water → topped up to full level.
        Water sinks:   own water_level and humidity forced to 0;
                       adjacent water flows into sink via normal physics.
        Lava sources:  temperature forced to LAVA_TEMPERATURE;
                       adjacent air/obsidian → VOXEL_LAVA at full lava_level;
                       adjacent existing lava → topped up to full level;
                       occasional mana crystal spawn.
        Lava sinks:    temperature clamped low;
                       adjacent lava → drained (lava_level=0, mana_crystals=0).
        """
        grid = self.voxel_grid
        voxels = grid.grid
        wl = grid.water_level
        ll = grid.lava_level
        w, d, h = grid.width, grid.depth, grid.height

        # ── Water sources ──────────────────────────────────────────────
        ws_mask = voxels == VOXEL_WATER_SOURCE
        if np.any(ws_mask):
            ws_positions = np.argwhere(ws_mask)
            for pos in ws_positions:
                x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
                for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    nx, ny, nz = x+dx, y+dy, z+dz
                    if not grid.in_bounds(nx, ny, nz):
                        continue
                    ntype = int(voxels[nx, ny, nz])
                    if ntype == VOXEL_WATER:
                        wl[nx, ny, nz] = WATER_SOURCE_OUTPUT
                    elif ntype == VOXEL_AIR:
                        # Fill all adjacent air: lateral, downward, AND
                        # upward.  Sources need to push water above them
                        # so rivers in deep channels can fill properly.
                        voxels[nx, ny, nz] = VOXEL_WATER
                        wl[nx, ny, nz] = WATER_SOURCE_OUTPUT
                        grid.mark_block_dirty(nx, ny, nz)

        # ── Water sinks ───────────────────────────────────────────────
        wk_mask = voxels == VOXEL_WATER_SINK
        if np.any(wk_mask):
            wl[wk_mask] = 0
            grid.humidity[wk_mask] = 0.0
            wk_positions = np.argwhere(wk_mask)
            for pos in wk_positions:
                x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
                for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    nx, ny, nz = x+dx, y+dy, z+dz
                    if not grid.in_bounds(nx, ny, nz):
                        continue
                    if int(voxels[nx, ny, nz]) == VOXEL_WATER:
                        wl[nx, ny, nz] = 0

        # ── Lava sources ──────────────────────────────────────────────
        ls_mask = voxels == VOXEL_LAVA_SOURCE
        if np.any(ls_mask):
            # Force source temperature
            grid.temperature[ls_mask] = LAVA_TEMPERATURE
            ls_positions = np.argwhere(ls_mask)
            for pos in ls_positions:
                x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
                for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    nx, ny, nz = x+dx, y+dy, z+dz
                    if not grid.in_bounds(nx, ny, nz):
                        continue
                    ntype = int(voxels[nx, ny, nz])
                    if ntype in (VOXEL_AIR, VOXEL_OBSIDIAN):
                        voxels[nx, ny, nz] = VOXEL_LAVA
                        ll[nx, ny, nz] = LAVA_SOURCE_OUTPUT
                        grid.temperature[nx, ny, nz] = LAVA_TEMPERATURE
                        grid.mark_block_dirty(nx, ny, nz)
                    elif ntype == VOXEL_LAVA:
                        # Top up existing lava to full level
                        ll[nx, ny, nz] = LAVA_SOURCE_OUTPUT

            # Mana crystal spawning: each source has a random chance per
            # water tick to increment mana_crystals of a random adjacent lava cell.
            for pos in ls_positions:
                if random.random() >= MANA_CRYSTAL_SPAWN_CHANCE:
                    continue
                x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
                lava_neighbors = []
                for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    nx, ny, nz = x+dx, y+dy, z+dz
                    if not grid.in_bounds(nx, ny, nz):
                        continue
                    if int(voxels[nx, ny, nz]) == VOXEL_LAVA and ll[nx, ny, nz] > 0:
                        lava_neighbors.append((nx, ny, nz))
                if lava_neighbors:
                    nx, ny, nz = random.choice(lava_neighbors)
                    current = int(grid.mana_crystals[nx, ny, nz])
                    if current < 255:
                        grid.mana_crystals[nx, ny, nz] = current + 1
                    grid.mark_block_dirty(nx, ny, nz)

        # ── Lava sinks ───────────────────────────────────────────────
        lk_mask = voxels == VOXEL_LAVA_SINK
        if np.any(lk_mask):
            grid.temperature[lk_mask] = 20.0
            lk_positions = np.argwhere(lk_mask)
            for pos in lk_positions:
                x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
                for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    nx, ny, nz = x+dx, y+dy, z+dz
                    if not grid.in_bounds(nx, ny, nz):
                        continue
                    if int(voxels[nx, ny, nz]) == VOXEL_LAVA:
                        voxels[nx, ny, nz] = VOXEL_AIR
                        ll[nx, ny, nz] = 0
                        grid.mana_crystals[nx, ny, nz] = 0
                        grid.temperature[nx, ny, nz] = 20.0
                        grid.mark_block_dirty(nx, ny, nz)

    # ------------------------------------------------------------------
    # Lava flow
    # ------------------------------------------------------------------

    def _flow_lava(self) -> None:
        """Gravity-driven downward flow + lateral leveling for lava.

        Similar to water flow but:
        - Uses LAVA_FLOW_RATE (slower, viscous)
        - Uses MAX_LAVA_FLOW_PER_TICK iterations
        - Cannot flow through open floodgates
        - Cannot flow into cells occupied by water (triggers interaction)
        - Tracks per-direction outflow for heat transport and mana drift
        """
        grid = self.voxel_grid
        voxels = grid.grid
        lava = grid.lava_level
        w, d, h = grid.width, grid.depth, grid.height

        # Snapshot lava state for targeted dirty marking
        lava_before = (voxels == VOXEL_LAVA).copy()

        # Reset outflow tracking for this tick
        # Outflow arrays: how much lava flowed from each cell in each direction
        # Used by _transport_lava_heat() and _drift_mana_crystals()
        self._lava_outflow = {
            'down': np.zeros((w, d, h), dtype=np.float32),
            'xp': np.zeros((w, d, h), dtype=np.float32),   # +x
            'xn': np.zeros((w, d, h), dtype=np.float32),   # -x
            'yp': np.zeros((w, d, h), dtype=np.float32),   # +y
            'yn': np.zeros((w, d, h), dtype=np.float32),   # -y
        }
        # Snapshot lava levels before flow for computing fractions
        self._lava_level_before = lava.copy()

        flowed = False

        for _ in range(MAX_LAVA_FLOW_PER_TICK):
            moved = False

            # --- Downward flow (z increases = deeper) ---
            if h > 1:
                lava_above = (voxels[:, :, :-1] == VOXEL_LAVA)
                air_below = (voxels[:, :, 1:] == VOXEL_AIR)
                can_flow_down = lava_above & air_below

                if np.any(can_flow_down):
                    moved = True
                    level_above = lava[:, :, :-1].copy()
                    transfer = np.where(can_flow_down, level_above, np.uint8(0))

                    # Track outflow for heat/mana transport
                    self._lava_outflow['down'][:, :, :-1] += np.where(
                        can_flow_down, transfer.astype(np.float32), 0.0
                    )

                    lava[:, :, 1:] = np.where(
                        can_flow_down,
                        np.minimum(
                            lava[:, :, 1:].astype(np.int16) + transfer.astype(np.int16),
                            255,
                        ).astype(np.uint8),
                        lava[:, :, 1:],
                    )
                    voxels[:, :, 1:] = np.where(
                        can_flow_down & (lava[:, :, 1:] > 0),
                        VOXEL_LAVA,
                        voxels[:, :, 1:],
                    )

                    lava[:, :, :-1] = np.where(can_flow_down, np.uint8(0), lava[:, :, :-1])
                    voxels[:, :, :-1] = np.where(
                        can_flow_down & (lava[:, :, :-1] == 0), VOXEL_AIR, voxels[:, :, :-1]
                    )

            # --- Lateral leveling ---
            # Process each axis sequentially to avoid checkerboard oscillation.
            # Transfer capped at diff//2 for stability.

            # (slc_a, slc_b, key_a_to_b, key_b_to_a)
            lateral_axes = [
                ((slice(None, -1), slice(None), slice(None)),
                 (slice(1, None), slice(None), slice(None)), 'xp', 'xn'),
                ((slice(None), slice(None, -1), slice(None)),
                 (slice(None), slice(1, None), slice(None)), 'yp', 'yn'),
            ]

            for slc_a, slc_b, key_ab, key_ba in lateral_axes:
                # Re-read masks after each axis application
                lava_mask = (voxels == VOXEL_LAVA)
                a_lava = lava_mask[slc_a]
                b_lava = lava_mask[slc_b]
                b_is_air = (voxels[slc_b] == VOXEL_AIR)
                a_is_air = (voxels[slc_a] == VOXEL_AIR)

                a_can_send = a_lava & (b_lava | b_is_air)
                b_can_send = b_lava & (a_lava | a_is_air)
                can_level = a_can_send | b_can_send

                if not np.any(can_level):
                    continue

                a_level = lava[slc_a].astype(np.int16)
                b_level = lava[slc_b].astype(np.int16)
                diff = a_level - b_level

                # Only flow when diff >= 2 (diff=1 is integer equilibrium)
                abs_diff = np.abs(diff)
                half_diff = abs_diff >> 1
                flow_mask = can_level & (half_diff > 0)
                if not np.any(flow_mask):
                    continue

                # Cap at half_diff to target equilibrium (no overshoot)
                raw_transfer = np.where(
                    flow_mask,
                    np.maximum((abs_diff * LAVA_FLOW_RATE).astype(np.int16), 1),
                    0,
                ).astype(np.int16)
                transfer_mag = np.minimum(raw_transfer, half_diff)

                transfer = np.where(diff > 0, transfer_mag, -transfer_mag)

                pos_mask = transfer > 0
                neg_mask = transfer < 0
                transfer = np.where(
                    pos_mask,
                    np.minimum(transfer, np.minimum(a_level, 255 - b_level)),
                    transfer,
                )
                transfer = np.where(
                    neg_mask,
                    np.maximum(transfer, -np.minimum(b_level, 255 - a_level)),
                    transfer,
                )

                active = flow_mask & (transfer != 0)
                if not np.any(active):
                    continue

                moved = True

                # Track outflow for heat/mana transport
                self._lava_outflow[key_ab][slc_a] += np.where(
                    active & (transfer > 0), transfer.astype(np.float32), 0.0
                )
                self._lava_outflow[key_ba][slc_b] += np.where(
                    active & (transfer < 0), (-transfer).astype(np.float32), 0.0
                )

                # Delta accumulator for this single axis (avoids
                # overlapping writes between adjacent pairs).
                delta = np.zeros((w, d, h), dtype=np.int16)
                delta[slc_a] -= np.where(active, transfer, 0)
                delta[slc_b] += np.where(active, transfer, 0)

                # Apply this axis immediately
                new_lava = np.clip(
                    lava.astype(np.int16) + delta, 0, 255
                ).astype(np.uint8)
                changed = new_lava != lava
                lava[:] = new_lava

                became_empty = changed & (lava == 0) & (voxels == VOXEL_LAVA)
                voxels[became_empty] = VOXEL_AIR
                became_lava = changed & (lava > 0) & (voxels == VOXEL_AIR)
                voxels[became_lava] = VOXEL_LAVA

            if not moved:
                break
            flowed = True

        if flowed:
            lava_after = (voxels == VOXEL_LAVA)
            changed = lava_before != lava_after
            if np.any(changed):
                xs, ys, zs = np.where(changed)
                grid.mark_blocks_dirty(xs, ys, zs)

    # ------------------------------------------------------------------
    # Lava heat transport (flow-based convection)
    # ------------------------------------------------------------------

    def _transport_lava_heat(self) -> None:
        """Move heat proportionally with lava flow.

        When lava flows from cell A to cell B, a proportional fraction of
        A's heat transfers with it:
            fraction = flow_amount / old_source_level
            heat_moved = fraction * source_temp

        This replaces the old neighbor-averaging lava convection entirely.
        Heat travels with the fluid — no more averaging.
        """
        if self._lava_outflow is None:
            return

        grid = self.voxel_grid
        temp = grid.temperature
        old_level = self._lava_level_before
        w, d, h = grid.width, grid.depth, grid.height

        # Safe denominator: avoid division by zero
        safe_old = np.maximum(old_level.astype(np.float32), 1.0)

        # Process downward flow heat transport
        down = self._lava_outflow['down']
        if np.any(down > 0) and h > 1:
            fraction = down[:, :, :-1] / safe_old[:, :, :-1]
            fraction = np.minimum(fraction, 1.0)
            heat_moved = fraction * temp[:, :, :-1]
            # Remove from source
            temp[:, :, :-1] -= heat_moved
            # Add to destination (weighted by relative volume)
            dest_old = old_level[:, :, 1:].astype(np.float32)
            dest_new_total = dest_old + down[:, :, :-1]
            safe_dest_total = np.maximum(dest_new_total, 1.0)
            # Weighted average of destination's existing heat and incoming heat
            has_flow = down[:, :, :-1] > 0
            temp[:, :, 1:] = np.where(
                has_flow,
                (temp[:, :, 1:] * dest_old + heat_moved * down[:, :, :-1] / np.maximum(down[:, :, :-1], 1.0)) / safe_dest_total * dest_new_total / safe_dest_total,
                temp[:, :, 1:],
            )
            # Simplified: just do weighted average
            temp[:, :, 1:] = np.where(
                has_flow,
                np.where(
                    dest_new_total > 0,
                    (temp[:, :, 1:] * dest_old + heat_moved) / safe_dest_total,
                    temp[:, :, 1:],
                ),
                temp[:, :, 1:],
            )

        # Process lateral flow heat transport
        lateral_configs = [
            ('xp', (slice(None, -1), slice(None), slice(None)),
                   (slice(1, None), slice(None), slice(None))),
            ('xn', (slice(1, None), slice(None), slice(None)),
                   (slice(None, -1), slice(None), slice(None))),
            ('yp', (slice(None), slice(None, -1), slice(None)),
                   (slice(None), slice(1, None), slice(None))),
            ('yn', (slice(None), slice(1, None), slice(None)),
                   (slice(None), slice(None, -1), slice(None))),
        ]

        for key, slc_src, slc_dst in lateral_configs:
            outflow = self._lava_outflow[key]
            flow_here = outflow[slc_src]
            if not np.any(flow_here > 0):
                continue
            fraction = flow_here / np.maximum(safe_old[slc_src], 1.0)
            fraction = np.minimum(fraction, 1.0)
            heat_moved = fraction * temp[slc_src]
            has_flow = flow_here > 0
            # Remove from source
            temp[slc_src] = np.where(has_flow, temp[slc_src] - heat_moved, temp[slc_src])
            # Add to destination (weighted average)
            dest_old_level = old_level[slc_dst].astype(np.float32)
            dest_new_total = dest_old_level + flow_here
            safe_dest_total = np.maximum(dest_new_total, 1.0)
            temp[slc_dst] = np.where(
                has_flow & (dest_new_total > 0),
                (temp[slc_dst] * dest_old_level + heat_moved) / safe_dest_total,
                temp[slc_dst],
            )

        # Safety: clamp temperature non-negative
        np.maximum(temp, 0.0, out=temp)

    # ------------------------------------------------------------------
    # Mana crystal drift
    # ------------------------------------------------------------------

    def _drift_mana_crystals(self) -> None:
        """Drift mana crystals probabilistically with lava flow.

        For each cell with mana_crystals > 0, compute flow fractions to
        each destination.  Each crystal independently rolls against
        the distribution: P(dest) = flow_to_dest / total_outflow_plus_remaining.
        """
        if self._lava_outflow is None:
            return

        grid = self.voxel_grid
        mana = grid.mana_crystals
        old_level = self._lava_level_before
        w, d, h = grid.width, grid.depth, grid.height

        # Find cells with mana crystals
        has_mana = mana > 0
        if not np.any(has_mana):
            return

        mana_positions = np.argwhere(has_mana)

        # Build per-cell outflow lookup
        down = self._lava_outflow['down']
        xp = self._lava_outflow['xp']
        xn = self._lava_outflow['xn']
        yp = self._lava_outflow['yp']
        yn = self._lava_outflow['yn']

        # New mana array (accumulate changes, then apply)
        new_mana = mana.copy()

        for pos in mana_positions:
            x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
            n_crystals = int(mana[x, y, z])
            if n_crystals == 0:
                continue

            # Compute outflow to each destination
            flows = []
            targets = []

            # Downward
            f_down = float(down[x, y, z])
            if f_down > 0 and z + 1 < h:
                flows.append(f_down)
                targets.append((x, y, z + 1))

            # +x
            f_xp = float(xp[x, y, z])
            if f_xp > 0 and x + 1 < w:
                flows.append(f_xp)
                targets.append((x + 1, y, z))

            # -x
            f_xn = float(xn[x, y, z])
            if f_xn > 0 and x - 1 >= 0:
                flows.append(f_xn)
                targets.append((x - 1, y, z))

            # +y
            f_yp = float(yp[x, y, z])
            if f_yp > 0 and y + 1 < d:
                flows.append(f_yp)
                targets.append((x, y + 1, z))

            # -y
            f_yn = float(yn[x, y, z])
            if f_yn > 0 and y - 1 >= 0:
                flows.append(f_yn)
                targets.append((x, y - 1, z))

            total_outflow = sum(flows)
            if total_outflow <= 0:
                continue  # No flow, crystals stay

            # Remaining lava in cell
            remaining = max(float(old_level[x, y, z]) - total_outflow, 0.0)
            total = total_outflow + remaining

            if total <= 0:
                continue

            # Build probability distribution
            probs = [f / total for f in flows]
            prob_stay = remaining / total

            # For each crystal, roll and assign
            for _ in range(n_crystals):
                roll = random.random()
                cumulative = 0.0
                moved = False
                for i, p in enumerate(probs):
                    cumulative += p
                    if roll < cumulative:
                        tx, ty, tz = targets[i]
                        new_mana[x, y, z] -= 1
                        if new_mana[tx, ty, tz] < 255:
                            new_mana[tx, ty, tz] += 1
                        moved = True
                        break
                # If not moved, crystal stays (prob_stay covers the rest)

        mana[:] = new_mana

    # ------------------------------------------------------------------
    # Seepage
    # ------------------------------------------------------------------

    def _apply_seepage(self) -> None:
        """Water increases humidity of adjacent porous solid blocks."""
        grid = self.voxel_grid
        voxels = grid.grid
        hum = grid.humidity
        w, d, h = grid.width, grid.depth, grid.height

        water_mask = (voxels == VOXEL_WATER)
        if not np.any(water_mask):
            return

        poro = self._porosity_lut[voxels]

        adj_water = np.zeros((w, d, h), dtype=np.bool_)
        if w > 1:
            adj_water[1:, :, :] |= water_mask[:-1, :, :]
            adj_water[:-1, :, :] |= water_mask[1:, :, :]
        if d > 1:
            adj_water[:, 1:, :] |= water_mask[:, :-1, :]
            adj_water[:, :-1, :] |= water_mask[:, 1:, :]
        if h > 1:
            adj_water[:, :, 1:] |= water_mask[:, :, :-1]
            adj_water[:, :, :-1] |= water_mask[:, :, 1:]

        receives = adj_water & (voxels != VOXEL_AIR) & (voxels != VOXEL_WATER) & (poro > 0)
        if np.any(receives):
            seepage = WATER_SEEP_RATE * poro[receives]
            hum[receives] = np.minimum(hum[receives] + seepage, 1.0)

    # ------------------------------------------------------------------
    # Pressure (both water and lava)
    # ------------------------------------------------------------------

    def _apply_pressure(self) -> None:
        """Compute hydrostatic pressure from water and lava column depth.

        Both water and lava columns exert pressure on adjacent solid walls.
        """
        grid = self.voxel_grid
        voxels = grid.grid
        w, d, h = grid.width, grid.depth, grid.height

        # --- Water pressure ---
        water_mask = (voxels == VOXEL_WATER)
        lava_mask = (voxels == VOXEL_LAVA)

        has_water = np.any(water_mask)
        has_lava = np.any(lava_mask)

        if not has_water and not has_lava:
            return

        fluid_mask = water_mask | lava_mask
        solid = ~fluid_mask & (voxels != VOXEL_AIR)
        shear = self._shear_lut[voxels]
        total_pressure = np.zeros((w, d, h), dtype=np.float32)

        if has_water:
            depth = np.zeros((w, d, h), dtype=np.float32)
            for z in range(h):
                if z == 0:
                    depth[:, :, z] = np.where(water_mask[:, :, z], 1.0, 0.0)
                else:
                    depth[:, :, z] = np.where(
                        water_mask[:, :, z], depth[:, :, z - 1] + 1.0, 0.0)
            water_weight = self._weight_lut[VOXEL_WATER]
            total_pressure += depth * water_weight * WATER_PRESSURE_WEIGHT

        # --- Lava pressure ---
        if has_lava:
            depth = np.zeros((w, d, h), dtype=np.float32)
            for z in range(h):
                if z == 0:
                    depth[:, :, z] = np.where(lava_mask[:, :, z], 1.0, 0.0)
                else:
                    depth[:, :, z] = np.where(
                        lava_mask[:, :, z], depth[:, :, z - 1] + 1.0, 0.0)
            # Lava is denser; use lava weight (or VOXEL_WEIGHT[VOXEL_LAVA])
            # VOXEL_LAVA weight is 0 in config (fluid), so use a reasonable
            # weight based on density.  Use water weight * density ratio.
            lava_effective_weight = max(self._weight_lut[VOXEL_LAVA], 5.0)
            total_pressure += depth * lava_effective_weight * LAVA_PRESSURE_WEIGHT

        if not np.any(total_pressure > 0):
            return

        # Apply pressure as shear load to adjacent solid walls
        adj_pressure = np.zeros((w, d, h), dtype=np.float32)
        if w > 1:
            adj_pressure[1:, :, :] = np.maximum(adj_pressure[1:, :, :], total_pressure[:-1, :, :])
            adj_pressure[:-1, :, :] = np.maximum(adj_pressure[:-1, :, :], total_pressure[1:, :, :])
        if d > 1:
            adj_pressure[:, 1:, :] = np.maximum(adj_pressure[:, 1:, :], total_pressure[:, :-1, :])
            adj_pressure[:, :-1, :] = np.maximum(adj_pressure[:, :-1, :], total_pressure[:, 1:, :])
        if h > 1:
            adj_pressure[:, :, 1:] = np.maximum(adj_pressure[:, :, 1:], total_pressure[:, :, :-1])
            adj_pressure[:, :, :-1] = np.maximum(adj_pressure[:, :, :-1], total_pressure[:, :, 1:])

        wall_pressure = np.where(solid, adj_pressure, 0.0)
        grid.shear_load += wall_pressure

        # --- Gate/door pressure burst ---
        self._check_gate_burst(voxels, wall_pressure, shear, grid)

        # Burst check: use the maximum burst factor from both fluids
        burst_factor = min(WATER_BURST_FACTOR, LAVA_BURST_FACTOR)
        safe_shear = np.where(shear > 0, shear, 1e9)
        should_burst = (
            solid
            & (wall_pressure > safe_shear * burst_factor)
            & (shear > 0)
            & (~grid.loose)
        )

        if not np.any(should_burst):
            return

        xs, ys, zs = np.where(should_burst)
        count = min(len(xs), MAX_CASCADE_PER_TICK)
        if len(xs) > count:
            worst = np.argpartition(wall_pressure[xs, ys, zs], -count)[-count:]
            xs, ys, zs = xs[worst], ys[worst], zs[worst]

        voxels[xs, ys, zs] = VOXEL_AIR
        grid.loose[xs, ys, zs] = False
        grid.bump_physics_generation()
        grid.mark_blocks_dirty(xs, ys, zs)
        self.event_bus.publish("water_burst", count=int(count))

    def _check_gate_burst(
        self,
        voxels: np.ndarray,
        wall_pressure: np.ndarray,
        shear: np.ndarray,
        grid: VoxelGrid,
    ) -> None:
        """Force open closed doors/floodgates under fluid pressure."""
        gate_types = frozenset({VOXEL_DOOR, VOXEL_FLOODGATE})
        metal_type_arr = grid.metal_type
        block_state_arr = grid.block_state

        for gate_type in gate_types:
            mask = (voxels == gate_type) & (block_state_arr != 0)
            if not np.any(mask):
                continue

            positions = np.argwhere(mask)
            for pos in positions:
                x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
                pressure = wall_pressure[x, y, z]
                if pressure <= 0:
                    continue

                base_shear = float(shear[x, y, z])
                mt = int(metal_type_arr[x, y, z])
                base_mt = mt & 0x7F
                strength_mult = METAL_STRENGTH_MULT.get(base_mt, 1.0)
                effective_shear = base_shear * strength_mult

                if pressure > effective_shear * WATER_BURST_FACTOR:
                    grid.set_block_state(x, y, z, 0)
                    self.event_bus.publish(
                        "gate_pressure_burst",
                        x=x, y=y, z=z, vtype=gate_type,
                    )

    # ------------------------------------------------------------------
    # Lava-water interaction (probabilistic)
    # ------------------------------------------------------------------

    def _lava_water_interaction(self) -> None:
        """Probabilistic water-lava interaction.

        For adjacent water and lava cells:
            chance = min(water_level, lava_level) / 255
        If obsidian forms: both consumed, steam generated.
        Otherwise: dominant fluid keeps abs(water_level - lava_level),
        the other disappears.
        """
        grid = self.voxel_grid
        voxels = grid.grid
        temp = grid.temperature
        wl = grid.water_level
        ll = grid.lava_level
        mana = grid.mana_crystals
        w, d, h = grid.width, grid.depth, grid.height

        water_mask = (voxels == VOXEL_WATER)
        lava_mask = (voxels == VOXEL_LAVA)

        if not (np.any(water_mask) and np.any(lava_mask)):
            return

        # Find water cells adjacent to lava
        water_near_lava = np.zeros((w, d, h), dtype=np.bool_)
        if w > 1:
            water_near_lava[1:, :, :] |= lava_mask[:-1, :, :]
            water_near_lava[:-1, :, :] |= lava_mask[1:, :, :]
        if d > 1:
            water_near_lava[:, 1:, :] |= lava_mask[:, :-1, :]
            water_near_lava[:, :-1, :] |= lava_mask[:, 1:, :]
        if h > 1:
            water_near_lava[:, :, 1:] |= lava_mask[:, :, :-1]
            water_near_lava[:, :, :-1] |= lava_mask[:, :, 1:]
        water_near_lava &= water_mask

        # Find lava cells adjacent to water
        lava_near_water = np.zeros((w, d, h), dtype=np.bool_)
        if w > 1:
            lava_near_water[1:, :, :] |= water_mask[:-1, :, :]
            lava_near_water[:-1, :, :] |= water_mask[1:, :, :]
        if d > 1:
            lava_near_water[:, 1:, :] |= water_mask[:, :-1, :]
            lava_near_water[:, :-1, :] |= water_mask[:, 1:, :]
        if h > 1:
            lava_near_water[:, :, 1:] |= water_mask[:, :, :-1]
            lava_near_water[:, :, :-1] |= water_mask[:, :, 1:]
        lava_near_water &= lava_mask

        if not (np.any(water_near_lava) or np.any(lava_near_water)):
            return

        reacted = False

        # Process each water cell near lava
        water_positions = np.argwhere(water_near_lava)
        for pos in water_positions:
            x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
            if int(voxels[x, y, z]) != VOXEL_WATER:
                continue  # already consumed

            # Find an adjacent lava cell
            for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                nx, ny, nz = x+dx, y+dy, z+dz
                if not grid.in_bounds(nx, ny, nz):
                    continue
                if int(voxels[nx, ny, nz]) != VOXEL_LAVA:
                    continue

                water_lvl = int(wl[x, y, z])
                lava_lvl = int(ll[nx, ny, nz])
                if water_lvl == 0 or lava_lvl == 0:
                    continue

                chance = min(water_lvl, lava_lvl) / 255.0
                if random.random() < chance:
                    # Obsidian forms: both consumed
                    reacted = True
                    avg_temp = (float(temp[x, y, z]) + float(temp[nx, ny, nz])) / 2.0
                    # Water cell becomes obsidian
                    voxels[x, y, z] = WATER_LAVA_PRODUCT
                    temp[x, y, z] = avg_temp
                    wl[x, y, z] = 0
                    grid.loose[x, y, z] = False
                    # Lava cell becomes obsidian
                    voxels[nx, ny, nz] = WATER_LAVA_PRODUCT
                    temp[nx, ny, nz] = avg_temp
                    ll[nx, ny, nz] = 0
                    mana[nx, ny, nz] = 0
                    grid.loose[nx, ny, nz] = False
                    grid.mark_block_dirty(x, y, z)
                    grid.mark_block_dirty(nx, ny, nz)
                    # Generate steam
                    self._generate_steam_at(x, y, z)
                else:
                    # Dominant fluid remains with difference
                    reacted = True
                    if water_lvl > lava_lvl:
                        remaining = water_lvl - lava_lvl
                        wl[x, y, z] = remaining
                        ll[nx, ny, nz] = 0
                        mana[nx, ny, nz] = 0
                        voxels[nx, ny, nz] = VOXEL_AIR
                        grid.mark_block_dirty(nx, ny, nz)
                    else:
                        remaining = lava_lvl - water_lvl
                        ll[nx, ny, nz] = remaining
                        wl[x, y, z] = 0
                        voxels[x, y, z] = VOXEL_AIR
                        grid.mark_block_dirty(x, y, z)
                        # mana_crystals stay in lava
                break  # Only interact with one lava neighbor per water cell

        if reacted:
            grid.bump_physics_generation()
            self.event_bus.publish("water_lava_reaction")

    def _generate_steam_at(self, x: int, y: int, z: int) -> None:
        """Set high humidity on blocks adjacent to a single steam source."""
        grid = self.voxel_grid
        voxels = grid.grid
        hum = grid.humidity
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nx, ny, nz = x+dx, y+dy, z+dz
            if not grid.in_bounds(nx, ny, nz):
                continue
            ntype = int(voxels[nx, ny, nz])
            if ntype != VOXEL_LAVA and ntype != VOXEL_WATER:
                hum[nx, ny, nz] = max(float(hum[nx, ny, nz]), WATER_HUMIDITY_SOURCE)

    def _generate_steam(self, source_mask: np.ndarray) -> None:
        """Set high humidity on blocks adjacent to steam source positions."""
        grid = self.voxel_grid
        voxels = grid.grid
        hum = grid.humidity
        w, d, h = grid.width, grid.depth, grid.height

        adj = np.zeros((w, d, h), dtype=np.bool_)
        if w > 1:
            adj[1:, :, :] |= source_mask[:-1, :, :]
            adj[:-1, :, :] |= source_mask[1:, :, :]
        if d > 1:
            adj[:, 1:, :] |= source_mask[:, :-1, :]
            adj[:, :-1, :] |= source_mask[:, 1:, :]
        if h > 1:
            adj[:, :, 1:] |= source_mask[:, :, :-1]
            adj[:, :, :-1] |= source_mask[:, :, 1:]

        receives_steam = adj & (voxels != VOXEL_LAVA) & (voxels != VOXEL_WATER)
        if np.any(receives_steam):
            hum[receives_steam] = np.maximum(
                hum[receives_steam], WATER_HUMIDITY_SOURCE
            )

    # ------------------------------------------------------------------
    # Surface evaporation
    # ------------------------------------------------------------------

    def _surface_evaporation(self) -> None:
        """Topmost water cells at sky/surface layers (z <= SURFACE_Z) evaporate."""
        grid = self.voxel_grid
        water = grid.water_level
        w, d, h = grid.width, grid.depth, grid.height

        sky_slice = grid.grid[:, :, :SURFACE_Z + 1]
        surface_water = (sky_slice == VOXEL_WATER)
        if not np.any(surface_water):
            return

        exposed = np.zeros_like(surface_water)
        sz = min(SURFACE_Z + 1, h)
        exposed[:, :, 0] = surface_water[:, :, 0]
        if sz > 1:
            above_not_water = (sky_slice[:, :, :sz - 1] != VOXEL_WATER)
            exposed[:, :, 1:sz] = surface_water[:, :, 1:sz] & above_not_water

        if not np.any(exposed):
            return

        roll = np.random.random(exposed.shape)
        evaporates = exposed & (roll < WATER_EVAPORATION_RATE)
        if not np.any(evaporates):
            return

        current = water[:, :, :SURFACE_Z + 1].astype(np.int16)
        new_level = np.where(
            evaporates,
            np.maximum(current - 1, 0),
            current,
        ).astype(np.uint8)
        water[:, :, :SURFACE_Z + 1] = new_level

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        """Remove VOXEL_WATER/VOXEL_LAVA where levels have dropped to 0."""
        grid = self.voxel_grid
        voxels = grid.grid

        # Water cleanup
        empty_water = (voxels == VOXEL_WATER) & (grid.water_level == 0)
        if np.any(empty_water):
            voxels[empty_water] = VOXEL_AIR
            xs, ys, zs = np.where(empty_water)
            grid.mark_blocks_dirty(xs, ys, zs)

        # Lava cleanup
        empty_lava = (voxels == VOXEL_LAVA) & (grid.lava_level == 0)
        if np.any(empty_lava):
            voxels[empty_lava] = VOXEL_AIR
            grid.mana_crystals[empty_lava] = 0  # safety
            xs, ys, zs = np.where(empty_lava)
            grid.mark_blocks_dirty(xs, ys, zs)
