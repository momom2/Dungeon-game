"""Structural integrity physics: load distribution and collapse detection.

Models real architectural principles:
- Stiffness-weighted distribution: stiffer receivers attract more load
  (direct stiffness method: F_i = k_i / Σk_j × F_total)
- Multi-block arches: air gaps redirect load laterally to nearest solid,
  weighted by inverse distance, up to MAX_ARCH_SPAN
- Buttressing: adjacent solid blocks reduce effective transmitted load
- Compressive failure: accumulated load exceeds compressive strength
- Shear failure: lateral loads exceed shear strength
- Tensile failure: bending moment in cantilevers exceeds tensile strength
  (tension = load × span / 2, simply-supported beam approximation)
- Foundation: deeper blocks bear accumulated weight from above

Dependencies: config, core.event_bus, world.voxel_grid
Dependents: main (wiring), tests/physics/test_structural.py
"""

from __future__ import annotations

import numpy as np
from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_WEIGHT,
    VOXEL_MAX_LOAD,
    VOXEL_POROSITY,
    VOXEL_STIFFNESS,
    VOXEL_TENSILE_STRENGTH,
    VOXEL_SHEAR_STRENGTH,
    STRUCTURAL_ANCHORS,
    STRUCTURAL_TICK_INTERVAL,
    MAX_CASCADE_PER_TICK,
    MAX_ARCH_SPAN,
    BUTTRESS_FACTOR,
    HUMIDITY_WEAKNESS,
    TEMP_WEAKNESS_MIN,
    TEMP_WEAKNESS_MAX,
    TEMP_WEAKNESS_FACTOR,
    WATER_BUOYANCY_FACTOR,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid


class StructuralIntegrityPhysics:
    """Computes load distribution and detects structural failure.

    Load flows downward (+z direction) with stiffness-weighted distribution.
    When accumulated load exceeds a block's capacity (modified by
    temperature and humidity), the block becomes loose.

    Three failure modes:
    - Compressive: total load exceeds compressive strength (VOXEL_MAX_LOAD)
    - Shear: lateral load exceeds shear strength (VOXEL_SHEAR_STRENGTH)
    - Tensile: bending moment exceeds tensile strength (VOXEL_TENSILE_STRENGTH)
    """

    def __init__(self, event_bus: EventBus, voxel_grid: VoxelGrid) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid

        # Pre-build LUTs (256 entries each)
        self._weight_lut = np.zeros(256, dtype=np.float32)
        self._capacity_lut = np.zeros(256, dtype=np.float32)
        self._anchor_lut = np.zeros(256, dtype=np.bool_)
        self._porosity_lut = np.zeros(256, dtype=np.float32)
        self._stiffness_lut = np.zeros(256, dtype=np.float32)
        self._tensile_lut = np.zeros(256, dtype=np.float32)
        self._shear_lut = np.zeros(256, dtype=np.float32)

        for vtype, w in VOXEL_WEIGHT.items():
            if 0 <= vtype < 256:
                self._weight_lut[vtype] = w

        for vtype, cap in VOXEL_MAX_LOAD.items():
            if 0 <= vtype < 256:
                # Use large finite value for inf (NumPy operations)
                self._capacity_lut[vtype] = min(cap, 1e9)

        for vtype in STRUCTURAL_ANCHORS:
            if 0 <= vtype < 256:
                self._anchor_lut[vtype] = True

        for vtype, poro in VOXEL_POROSITY.items():
            if 0 <= vtype < 256:
                self._porosity_lut[vtype] = poro

        for vtype, stiff in VOXEL_STIFFNESS.items():
            if 0 <= vtype < 256:
                self._stiffness_lut[vtype] = stiff

        for vtype, tens in VOXEL_TENSILE_STRENGTH.items():
            if 0 <= vtype < 256:
                self._tensile_lut[vtype] = min(tens, 1e9)

        for vtype, shear in VOXEL_SHEAR_STRENGTH.items():
            if 0 <= vtype < 256:
                self._shear_lut[vtype] = min(shear, 1e9)

        # Snapshots for skip-if-unchanged optimisation
        self._last_structural_grid: np.ndarray | None = None
        self._last_structural_loose: np.ndarray | None = None

        # Track whether blocks fell recently.  While blocks are actively
        # falling, structural recomputation is deferred to avoid O(n) work
        # every 10 ticks on a transient state that changes each tick.
        self._falling_active: bool = False

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("blocks_fell", self._on_blocks_fell)
        event_bus.subscribe("blocks_spread", self._on_blocks_fell)

    def reset_snapshots(self) -> None:
        """Reset skip-if-unchanged snapshots to the current grid state.

        Call after bulk modifications (e.g. terrain stabilization) so the
        first real tick doesn't erroneously skip its structural check.
        """
        grid = self._grid
        self._last_structural_grid = grid.grid.copy()
        self._last_structural_loose = grid.loose.copy()

    def _on_blocks_fell(self, **kw) -> None:
        """Note that blocks are actively falling; defer structural checks."""
        self._falling_active = True

    def _on_tick(self, tick: int, **kw) -> None:
        if tick % STRUCTURAL_TICK_INTERVAL != 0:
            return

        # While blocks are actively falling, defer expensive recompute.
        # Gravity fires every tick; structural every 10.  When blocks are
        # mid-fall the grid changes every tick → recomputing load is wasted
        # because it'll change again next tick.  Skip this interval and
        # clear the flag — if falling continues, the flag will be re-set
        # by the next blocks_fell event before our next interval.
        if self._falling_active:
            self._falling_active = False
            return

        # Skip full recomputation if grid and loose arrays haven't changed
        grid = self.voxel_grid
        if (
            self._last_structural_grid is not None
            and np.array_equal(grid.grid, self._last_structural_grid)
            and np.array_equal(grid.loose, self._last_structural_loose)
        ):
            return

        self._compute_load()
        # Compute all three capacity arrays once (shared environmental modifier)
        comp_cap, shear_cap, tensile_cap = self._compute_all_capacities()
        self._check_failures(comp_cap, shear_cap)
        self._compute_tensile_failures(tensile_cap)

        # Save snapshot for next skip check
        self._last_structural_grid = grid.grid.copy()
        self._last_structural_loose = grid.loose.copy()

    def _compute_load(self) -> None:
        """Top-down load accumulation with stiffness-weighted distribution.

        Uses the direct stiffness method: each receiver block attracts
        load proportional to its stiffness relative to total receiver
        stiffness (F_i = k_i / Σk_j × F_total).

        Load arriving laterally (from lateral distribution or arch
        redistribution) is tracked separately in shear_load.
        """
        grid = self.voxel_grid
        voxels = grid.grid
        loose = grid.loose
        w, d, h = grid.width, grid.depth, grid.height

        # Weight of each block from LUT
        self_weight = self._weight_lut[voxels].copy()

        # --- Buoyancy: reduce weight for blocks submerged in water ---
        water_mask = (voxels == VOXEL_WATER)
        if np.any(water_mask):
            self._apply_buoyancy(self_weight, water_mask, voxels, h)

        # Solid mask (non-air, non-loose blocks bear load)
        solid = (voxels != VOXEL_AIR) & (~loose)

        # Anchor mask
        anchors = self._anchor_lut[voxels]

        # Stiffness of each block
        stiffness = self._stiffness_lut[voxels]

        # Accumulated load array (reset each computation)
        load = np.zeros((w, d, h), dtype=np.float32)
        shear = np.zeros((w, d, h), dtype=np.float32)

        # Pre-allocate reusable 2D buffers (avoid per-z allocation)
        k_lat = np.empty((4, w, d), dtype=np.float32)
        frac_lat = np.empty((4, w, d), dtype=np.float32)
        neighbor_count = np.empty((w, d), dtype=np.float32)

        # Process top-to-bottom (z=0 is surface, z=h-1 is deepest)
        for z in range(h):
            solid_z = solid[:, :, z]

            # Skip entirely empty z-levels (no solid blocks to load)
            if not np.any(solid_z):
                continue

            load_z = load[:, :, z]

            # Each block starts with its own weight
            load_z += self_weight[:, :, z]

            # Anchors absorb all load; non-solid can't transmit
            anchor_z = anchors[:, :, z]
            load_z[anchor_z] = 0.0
            load_z[~solid_z] = 0.0

            if z >= h - 1:
                continue

            # Buttressing: count solid cardinal neighbors at same z-level
            solid_z_f = solid_z.astype(np.float32)
            neighbor_count[:] = 0.0
            neighbor_count[1:, :] += solid_z_f[:-1, :]
            neighbor_count[:-1, :] += solid_z_f[1:, :]
            neighbor_count[:, 1:] += solid_z_f[:, :-1]
            neighbor_count[:, :-1] += solid_z_f[:, 1:]

            buttress_mult = np.clip(
                1.0 - neighbor_count * BUTTRESS_FACTOR, 0.5, 1.0
            )
            effective_load = load_z * buttress_mult

            # --- Stiffness-weighted distribution ---
            solid_below = solid[:, :, z + 1]

            # Fast path: if the level below is entirely solid, all load
            # goes directly below (100% compressive, no lateral, no arch).
            # This skips all the expensive np.where calls for stiffness
            # fractions.  Common for deep underground z-levels.
            if np.all(solid_below):
                load[:, :, z + 1] += effective_load
                continue

            stiff_z1 = stiffness[:, :, z + 1]

            # Direct below stiffness (compressive receiver)
            k_below = np.where(solid_below, stiff_z1, 0.0)

            # Lateral-below stiffness (shear receivers)
            k_lat[:] = 0.0
            if w > 1:
                k_lat[0, :-1, :] = np.where(
                    solid[1:, :, z + 1], stiffness[1:, :, z + 1], 0.0
                )
                k_lat[1, 1:, :] = np.where(
                    solid[:-1, :, z + 1], stiffness[:-1, :, z + 1], 0.0
                )
            if d > 1:
                k_lat[2, :, :-1] = np.where(
                    solid[:, 1:, z + 1], stiffness[:, 1:, z + 1], 0.0
                )
                k_lat[3, :, 1:] = np.where(
                    solid[:, :-1, z + 1], stiffness[:, :-1, z + 1], 0.0
                )

            # Total stiffness of all receivers
            k_total = k_below + k_lat[0] + k_lat[1] + k_lat[2] + k_lat[3]

            # Compute fractions (safe division)
            has_receivers = k_total > 0
            safe_k = np.where(has_receivers, k_total, 1.0)
            frac_below = np.where(has_receivers, k_below / safe_k, 0.0)
            for i in range(4):
                frac_lat[i] = np.where(has_receivers, k_lat[i] / safe_k, 0.0)

            # Distribute effective_load proportional to stiffness fractions
            direct_below_load = effective_load * frac_below
            load[:, :, z + 1] += direct_below_load

            # Lateral-below (shear) — compute and distribute in place
            distributed = direct_below_load.copy()
            if w > 1:
                lat_0 = effective_load[:-1, :] * frac_lat[0, :-1, :]
                load[1:, :, z + 1] += lat_0
                shear[1:, :, z + 1] += lat_0
                distributed[:-1, :] += lat_0

                lat_1 = effective_load[1:, :] * frac_lat[1, 1:, :]
                load[:-1, :, z + 1] += lat_1
                shear[:-1, :, z + 1] += lat_1
                distributed[1:, :] += lat_1
            if d > 1:
                lat_2 = effective_load[:, :-1] * frac_lat[2, :, :-1]
                load[:, 1:, z + 1] += lat_2
                shear[:, 1:, z + 1] += lat_2
                distributed[:, :-1] += lat_2

                lat_3 = effective_load[:, 1:] * frac_lat[3, :, 1:]
                load[:, :-1, z + 1] += lat_3
                shear[:, :-1, z + 1] += lat_3
                distributed[:, 1:] += lat_3

            # --- Multi-block arch detection ---
            air_below = (~solid_below) & (voxels[:, :, z + 1] == VOXEL_AIR)
            blocked_load = np.where(air_below, effective_load * frac_below, 0.0)

            if np.any(blocked_load > 0):
                arch_distributed = self._distribute_arch_load(
                    blocked_load, solid, stiffness, shear, load, z, w, d
                )
                distributed += arch_distributed

            # Undistributed load stays on the current block as retained stress
            undistributed = np.maximum(effective_load - distributed, 0.0)
            load_z += undistributed

        grid.load[:] = load
        grid.shear_load[:] = shear

    @staticmethod
    def _apply_buoyancy(
        weights: np.ndarray,
        water_mask: np.ndarray,
        voxels: np.ndarray,
        h: int,
    ) -> None:
        """Reduce effective weight for blocks submerged in water.

        A solid block with water directly above it (z-1, toward surface)
        has its weight reduced by ``WATER_BUOYANCY_FACTOR``.  This makes
        blocks at the bottom of deep water columns structurally lighter,
        preventing unrealistic collapses of submerged structures.

        Water blocks themselves are not affected (they have their own
        weight for pressure calculations).
        """
        for z in range(1, h):
            # Check if water exists above (z-1 = toward surface)
            water_above = water_mask[:, :, z - 1]
            # Only apply to solid non-water blocks
            solid_here = (
                (voxels[:, :, z] != VOXEL_AIR)
                & (voxels[:, :, z] != VOXEL_WATER)
            )
            submerged = water_above & solid_here
            if np.any(submerged):
                weights[:, :, z] = np.where(
                    submerged,
                    weights[:, :, z] * WATER_BUOYANCY_FACTOR,
                    weights[:, :, z],
                )

    def _distribute_arch_load(
        self,
        blocked_load: np.ndarray,
        solid: np.ndarray,
        stiffness: np.ndarray,
        shear: np.ndarray,
        load: np.ndarray,
        z: int,
        w: int,
        d: int,
    ) -> np.ndarray:
        """Distribute blocked load (intended for air below) via arch action.

        Scans 4 cardinal directions at z+1 for nearest solid block up to
        MAX_ARCH_SPAN. Requires line-of-sight (all intermediate cells air).
        Weights by 1/distance for each found flanking block.
        Arch-redistributed load counts as shear.

        Returns amount of blocked_load that was successfully distributed.
        """
        z1 = z + 1
        arch_distributed = np.zeros((w, d), dtype=np.float32)

        # Collect inverse-distance weights and positions for each direction
        # Weight[dir][dist] = (1/dist) if solid and line-of-sight clear
        inv_dist_total = np.zeros((w, d), dtype=np.float32)

        # Store per-direction-distance contributions
        # We accumulate inv_dist weights, then normalize
        contributions = []  # list of (inv_dist_weight, slice_info)

        for dist in range(1, MAX_ARCH_SPAN + 1):
            inv_d = 1.0 / dist

            # +X direction: source at [:-dist], receiver at [dist:]
            if w > dist:
                # Check line-of-sight: all intermediate cells must be air at z+1
                los = np.ones((w - dist, d), dtype=np.bool_)
                for mid in range(1, dist):
                    los &= ~solid[mid:w - dist + mid, :, z1]
                # Receiver must be solid
                receiver_solid = solid[dist:, :, z1] & los
                weight = np.where(
                    receiver_solid,
                    inv_d * blocked_load[:w - dist, :],
                    0.0
                )
                inv_dist_total[:w - dist, :] += np.where(
                    receiver_solid, inv_d, 0.0
                )
                contributions.append(('+x', dist, weight, receiver_solid))

            # -X direction: source at [dist:], receiver at [:-dist]
            if w > dist:
                los = np.ones((w - dist, d), dtype=np.bool_)
                for mid in range(1, dist):
                    los &= ~solid[dist - mid:w - mid, :, z1]
                receiver_solid = solid[:w - dist, :, z1] & los
                weight = np.where(
                    receiver_solid,
                    inv_d * blocked_load[dist:, :],
                    0.0
                )
                inv_dist_total[dist:, :] += np.where(
                    receiver_solid, inv_d, 0.0
                )
                contributions.append(('-x', dist, weight, receiver_solid))

            # +Y direction
            if d > dist:
                los = np.ones((w, d - dist), dtype=np.bool_)
                for mid in range(1, dist):
                    los &= ~solid[:, mid:d - dist + mid, z1]
                receiver_solid = solid[:, dist:, z1] & los
                weight = np.where(
                    receiver_solid,
                    inv_d * blocked_load[:, :d - dist],
                    0.0
                )
                inv_dist_total[:, :d - dist] += np.where(
                    receiver_solid, inv_d, 0.0
                )
                contributions.append(('+y', dist, weight, receiver_solid))

            # -Y direction
            if d > dist:
                los = np.ones((w, d - dist), dtype=np.bool_)
                for mid in range(1, dist):
                    los &= ~solid[:, dist - mid:d - mid, z1]
                receiver_solid = solid[:, :d - dist, z1] & los
                weight = np.where(
                    receiver_solid,
                    inv_d * blocked_load[:, dist:],
                    0.0
                )
                inv_dist_total[:, dist:] += np.where(
                    receiver_solid, inv_d, 0.0
                )
                contributions.append(('-y', dist, weight, receiver_solid))

        # Now normalize and distribute: each receiver gets
        # blocked_load * (inv_d / inv_dist_total) of the source's blocked load
        for direction, dist, weight, receiver_solid in contributions:
            if direction == '+x':
                safe_total = np.where(
                    inv_dist_total[:w - dist, :] > 0,
                    inv_dist_total[:w - dist, :], 1.0
                )
                has_arch = inv_dist_total[:w - dist, :] > 0
                normalized = np.where(
                    has_arch, weight / safe_total, 0.0
                )
                load[dist:, :, z + 1] += normalized
                shear[dist:, :, z + 1] += normalized
                arch_distributed[:w - dist, :] += normalized

            elif direction == '-x':
                safe_total = np.where(
                    inv_dist_total[dist:, :] > 0,
                    inv_dist_total[dist:, :], 1.0
                )
                has_arch = inv_dist_total[dist:, :] > 0
                normalized = np.where(
                    has_arch, weight / safe_total, 0.0
                )
                load[:w - dist, :, z + 1] += normalized
                shear[:w - dist, :, z + 1] += normalized
                arch_distributed[dist:, :] += normalized

            elif direction == '+y':
                safe_total = np.where(
                    inv_dist_total[:, :d - dist] > 0,
                    inv_dist_total[:, :d - dist], 1.0
                )
                has_arch = inv_dist_total[:, :d - dist] > 0
                normalized = np.where(
                    has_arch, weight / safe_total, 0.0
                )
                load[:, dist:, z + 1] += normalized
                shear[:, dist:, z + 1] += normalized
                arch_distributed[:, :d - dist] += normalized

            elif direction == '-y':
                safe_total = np.where(
                    inv_dist_total[:, dist:] > 0,
                    inv_dist_total[:, dist:], 1.0
                )
                has_arch = inv_dist_total[:, dist:] > 0
                normalized = np.where(
                    has_arch, weight / safe_total, 0.0
                )
                load[:, :d - dist, z + 1] += normalized
                shear[:, :d - dist, z + 1] += normalized
                arch_distributed[:, dist:] += normalized

        return arch_distributed

    def _compute_environmental_modifier(self) -> np.ndarray:
        """Compute shared environmental modifier for all capacity types.

        Returns a (w, d, h) float32 array of combined humidity + temperature
        weakness factor.  Each capacity type multiplies its base LUT by this.

        Humidity weakness is scaled by material porosity: porous materials
        (chalk, sandstone) weaken far more than dense ones (obsidian, granite).
        """
        grid = self.voxel_grid
        voxels = grid.grid

        porosity = self._porosity_lut[voxels]
        humidity_mod = np.clip(
            1.0 - grid.humidity * HUMIDITY_WEAKNESS * porosity, 0.5, 1.0
        )

        temp_factor = np.clip(
            (grid.temperature - TEMP_WEAKNESS_MIN)
            / (TEMP_WEAKNESS_MAX - TEMP_WEAKNESS_MIN),
            0.0,
            1.0,
        )
        temp_mod = 1.0 - temp_factor * TEMP_WEAKNESS_FACTOR

        return humidity_mod * temp_mod

    def _compute_all_capacities(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute compressive, shear, and tensile capacities in one pass.

        Shares the expensive environmental modifier computation across all
        three capacity types, saving ~12 temporary array allocations.

        Returns (comp_cap, shear_cap, tensile_cap) as float32 arrays.
        """
        voxels = self.voxel_grid.grid
        env_mod = self._compute_environmental_modifier()

        comp_cap = self._capacity_lut[voxels] * env_mod
        shear_cap = self._shear_lut[voxels] * env_mod
        tensile_cap = self._tensile_lut[voxels] * env_mod

        return comp_cap, shear_cap, tensile_cap

    def _check_failures(
        self,
        effective_comp_cap: np.ndarray,
        effective_shear_cap: np.ndarray,
    ) -> None:
        """Compare load against capacity. Overloaded blocks become loose.

        Checks both compressive and shear failure modes:
        - Compressive: total load vs compressive strength
        - Shear: lateral load vs shear strength
        stress_ratio = max(compressive_ratio, shear_ratio) for rendering.
        """
        grid = self.voxel_grid
        voxels = grid.grid
        loose = grid.loose

        load = grid.load
        shear_load = grid.shear_load

        # Compute compressive stress ratio
        safe_comp_cap = np.where(effective_comp_cap > 0, effective_comp_cap, 1.0)
        comp_ratio = np.where(
            effective_comp_cap > 0, load / safe_comp_cap, 0.0
        )

        # Compute shear stress ratio
        safe_shear_cap = np.where(effective_shear_cap > 0, effective_shear_cap, 1.0)
        shear_ratio = np.where(
            effective_shear_cap > 0, shear_load / safe_shear_cap, 0.0
        )

        # Overall stress ratio for rendering = max of both modes
        grid.stress_ratio[:] = np.maximum(comp_ratio, shear_ratio)

        # Find overloaded blocks (either mode)
        solid = (voxels != VOXEL_AIR) & (~loose)
        anchors = self._anchor_lut[voxels]

        comp_failed = (
            (load > effective_comp_cap) & solid & (~anchors)
            & (effective_comp_cap > 0)
        )
        shear_failed = (
            (shear_load > effective_shear_cap) & solid & (~anchors)
            & (effective_shear_cap > 0)
        )
        overloaded = comp_failed | shear_failed

        if not np.any(overloaded):
            return

        # Cap cascading: prioritize highest stress first
        xs, ys, zs = np.where(overloaded)
        count = min(len(xs), MAX_CASCADE_PER_TICK)

        if len(xs) > MAX_CASCADE_PER_TICK:
            stress_vals = grid.stress_ratio[xs, ys, zs]
            worst_indices = np.argpartition(stress_vals, -count)[-count:]
            xs, ys, zs = xs[worst_indices], ys[worst_indices], zs[worst_indices]

        loose[xs, ys, zs] = True
        grid.bump_physics_generation()
        grid.mark_blocks_dirty(xs, ys, zs)

        self.event_bus.publish("structural_failure", count=int(count))

    def _compute_tensile_failures(self, effective_tensile: np.ndarray) -> None:
        """Check for tensile/bending failure in cantilevered blocks.

        For each unsupported solid block (no solid directly below, not an
        anchor, not at grid bottom), compute the minimum distance to a
        supported block in 4 cardinal directions along the same z-level.

        Bending moment approximation (simply-supported beam):
            tension = load × span / 2

        If tension exceeds the block's tensile strength (with environmental
        modifiers), the block becomes loose.
        """
        grid = self.voxel_grid
        voxels = grid.grid
        loose = grid.loose
        load = grid.load
        w, d, h = grid.width, grid.depth, grid.height

        solid = (voxels != VOXEL_AIR) & (~loose)
        anchors = self._anchor_lut[voxels]

        total_new_loose = 0
        dirty_positions: list[tuple] = []  # Collect (txs, tys, z) for dirty marking

        for z in range(h):
            solid_z = solid[:, :, z]
            anchor_z = anchors[:, :, z]

            # A block is "supported" if:
            # - it's an anchor, OR
            # - it has a solid block directly below (z+1), OR
            # - it's at grid bottom (z == h-1)
            supported = anchor_z.copy()
            if z < h - 1:
                supported |= solid[:, :, z + 1]
            if z == h - 1:
                supported |= solid_z  # bottom of grid = supported

            # Unsupported solid blocks need tensile check
            unsupported = solid_z & (~supported) & (~anchor_z)

            if not np.any(unsupported):
                continue

            # Compute minimum span to nearest supported block in 4 cardinal
            # directions along this z-level (vectorized).
            # span = min distance to a supported-and-solid block.
            # If no supported block found in any direction, span = infinity.
            max_span = np.float32(w + d)
            min_span = np.full((w, d), max_span, dtype=np.float32)

            # Support mask: cells that are both supported and solid
            support_mask = supported & solid_z

            # +x direction: distance from nearest supported cell to the left
            # Build index array where supported cells record their x index
            x_idx = np.arange(w, dtype=np.float32)[:, None] * np.ones(d, dtype=np.float32)[None, :]
            # Replace non-support with -inf, then cumulative max along x axis
            sup_x_fwd = np.where(support_mask, x_idx, np.float32(-1))
            np.maximum.accumulate(sup_x_fwd, axis=0, out=sup_x_fwd)
            span_fwd_x = x_idx - sup_x_fwd
            # Only valid where sup_x_fwd >= 0 (found a supported cell)
            valid_fwd_x = (sup_x_fwd >= 0) & unsupported
            min_span = np.where(valid_fwd_x & (span_fwd_x < min_span), span_fwd_x, min_span)

            # -x direction: distance from nearest supported cell to the right
            sup_x_bwd = np.where(support_mask, x_idx, np.float32(-1))
            sup_x_bwd_rev = sup_x_bwd[::-1, :]
            # Cumulative max of reversed → finds nearest support to the right
            np.maximum.accumulate(sup_x_bwd_rev, axis=0, out=sup_x_bwd_rev)
            sup_x_bwd = sup_x_bwd_rev[::-1, :]
            span_bwd_x = sup_x_bwd - x_idx
            valid_bwd_x = (sup_x_bwd >= 0) & unsupported
            min_span = np.where(valid_bwd_x & (span_bwd_x < min_span), span_bwd_x, min_span)

            # +y direction: distance from nearest supported cell above (in y)
            y_idx = np.ones(w, dtype=np.float32)[:, None] * np.arange(d, dtype=np.float32)[None, :]
            sup_y_fwd = np.where(support_mask, y_idx, np.float32(-1))
            np.maximum.accumulate(sup_y_fwd, axis=1, out=sup_y_fwd)
            span_fwd_y = y_idx - sup_y_fwd
            valid_fwd_y = (sup_y_fwd >= 0) & unsupported
            min_span = np.where(valid_fwd_y & (span_fwd_y < min_span), span_fwd_y, min_span)

            # -y direction: distance from nearest supported cell below (in y)
            sup_y_bwd = np.where(support_mask, y_idx, np.float32(-1))
            sup_y_bwd_rev = sup_y_bwd[:, ::-1]
            np.maximum.accumulate(sup_y_bwd_rev, axis=1, out=sup_y_bwd_rev)
            sup_y_bwd = sup_y_bwd_rev[:, ::-1]
            span_bwd_y = sup_y_bwd - y_idx
            valid_bwd_y = (sup_y_bwd >= 0) & unsupported
            min_span = np.where(valid_bwd_y & (span_bwd_y < min_span), span_bwd_y, min_span)

            # Compute bending moment: tension = load × span / 2
            block_load = load[:, :, z]
            tension = block_load * min_span / 2.0

            # Check tensile failure
            tensile_cap = effective_tensile[:, :, z]
            tensile_failed = (
                unsupported
                & (tension > tensile_cap)
                & (tensile_cap > 0)
            )

            if not np.any(tensile_failed):
                continue

            # Update stress ratio for tensile-failed blocks
            safe_tensile = np.where(tensile_cap > 0, tensile_cap, 1.0)
            tensile_ratio = np.where(
                tensile_cap > 0, tension / safe_tensile, 0.0
            )
            # Max with existing stress ratio
            grid.stress_ratio[:, :, z] = np.maximum(
                grid.stress_ratio[:, :, z], tensile_ratio
            )

            # Apply cascade cap
            txs, tys = np.where(tensile_failed)
            remaining = MAX_CASCADE_PER_TICK - total_new_loose
            if remaining <= 0:
                break

            count = min(len(txs), remaining)
            if len(txs) > remaining:
                stress_vals = tensile_ratio[txs, tys]
                worst = np.argpartition(stress_vals, -count)[-count:]
                txs, tys = txs[worst], tys[worst]

            loose[txs, tys, z] = True
            total_new_loose += count
            dirty_positions.append((txs, tys, z))

        if total_new_loose > 0:
            grid.bump_physics_generation()
            for d_txs, d_tys, d_z in dirty_positions:
                d_zs = np.full_like(d_txs, d_z)
                grid.mark_blocks_dirty(d_txs, d_tys, d_zs)
            self.event_bus.publish("tensile_failure", count=total_new_loose)
