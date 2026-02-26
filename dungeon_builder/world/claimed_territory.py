"""Claimed territory: 3D flood-fill from core through traversable voxels.

Air, water, and player-built functional blocks (slopes, stairs, doors,
spikes, treasure, tarps, rolling stones, reinforced walls) reachable from
the dungeon core via 6-connected flood-fill are marked as "claimed".
Natural solid blocks and lava act as barriers.  Solid blocks adjacent to
claimed territory are marked as "visible" (for fog-of-war rendering).

Follows the same iterative NumPy dilation pattern as
``GravityPhysics._check_connectivity()`` in ``gravity.py``.

Dependencies: config, core.event_bus, world.voxel_grid
Dependents: main (wiring), tests/world/test_claimed_territory.py,
    tests/world/test_core_placement.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_WATER,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_DOOR,
    VOXEL_TARP,
    VOXEL_SPIKE,
    VOXEL_TREASURE,
    VOXEL_ROLLING_STONE,
    VOXEL_REINFORCED_WALL,
    CORE_X,
    CORE_Y,
    CORE_Z,
    CLAIMED_TICK_INTERVAL,
)

# Functional blocks that claiming can propagate through
_CLAIM_TRAVERSABLE = frozenset((
    VOXEL_AIR, VOXEL_WATER,
    VOXEL_SLOPE, VOXEL_STAIRS, VOXEL_DOOR, VOXEL_TARP,
    VOXEL_SPIKE, VOXEL_TREASURE, VOXEL_ROLLING_STONE,
    VOXEL_REINFORCED_WALL,
))

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid

logger = logging.getLogger("dungeon_builder.claimed_territory")


class ClaimedTerritorySystem:
    """Computes claimed territory via 6-connected flood-fill from core.

    Propagates through air, water, and functional blocks.
    Runs every ``CLAIMED_TICK_INTERVAL`` ticks.  After computing claimed
    territory, it also computes the *visible* mask for solid blocks: a
    solid block is visible if any of its 6 neighbours is claimed.
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        core_x: int = CORE_X,
        core_y: int = CORE_Y,
        core_z: int = CORE_Z,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.core_x = core_x
        self.core_y = core_y
        self.core_z = core_z

        self._dirty = False  # Deferred recompute flag (from batch events)
        self._recomputed_this_tick = False  # Prevents repeated recomputes in one tick

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("dig_complete", self._on_dig_complete)
        event_bus.subscribe("dig_batch_queued", self._mark_dirty)
        event_bus.subscribe("dig_batch_cancelled", self._mark_dirty)
        event_bus.subscribe("dig_batch_pending", self._mark_dirty)
        event_bus.subscribe("dig_batch_complete", self._mark_dirty)
        event_bus.subscribe("force_territory_recompute", self._on_force_recompute)

        # Initial computation
        self.recompute()

    def _mark_dirty(self, **kw) -> None:
        """Mark territory as needing recompute (deferred to next tick)."""
        self._dirty = True

    def _recompute_once(self) -> None:
        """Recompute at most once per tick.  Subsequent calls are skipped."""
        if self._recomputed_this_tick:
            return
        self._recomputed_this_tick = True
        self.recompute()

    def _on_tick(self, tick: int, **kw) -> None:
        self._recomputed_this_tick = False  # Reset at start of each tick
        if self._dirty or tick % CLAIMED_TICK_INTERVAL == 0:
            self._dirty = False
            self._recompute_once()

    def _on_voxel_changed(self, **kw) -> None:
        """Recompute immediately on voxel type change (at most once per tick)."""
        self._recompute_once()

    def _on_dig_complete(self, **kw) -> None:
        """Recompute on dig complete (at most once per tick)."""
        self._recompute_once()

    def _on_force_recompute(self, **kw) -> None:
        """Force recompute on demand (e.g. before render mode switch)."""
        self._recomputed_this_tick = False  # Allow even if already done this tick
        self.recompute()

    def recompute(self) -> None:
        """Full recomputation of claimed territory and visibility."""
        grid = self.voxel_grid
        voxels = grid.grid
        w, d, h = grid.width, grid.depth, grid.height

        # Dev mode: everything is claimed and visible — skip flood-fill
        if _cfg.DEV_MODE:
            old_claimed = grid.claimed.copy()
            old_visible = grid.visible.copy()
            grid.claimed[:] = True
            grid.visible[:] = True
            if not np.array_equal(old_claimed, grid.claimed) or not np.array_equal(old_visible, grid.visible):
                grid.mark_all_dirty()
                self.event_bus.publish("claimed_territory_changed")
            return

        # Traversable mask: air, water, and functional blocks propagate claims
        traversable = np.zeros_like(voxels, dtype=np.bool_)
        for vtype in _CLAIM_TRAVERSABLE:
            traversable |= (voxels == vtype)

        # Seed from traversable cells near the core block.
        # The core can float in mid-air, so if its immediate neighbors are
        # not traversable we fall back to the first solid block directly
        # below the core (the "pillar" or floor), then search outward from
        # *that* position.  Finally a wider-radius search around the core.
        cx, cy, cz = self.core_x, self.core_y, self.core_z
        seed = np.zeros((w, d, h), dtype=np.bool_)

        # 1) Try 6-adjacent to core
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0),
                           (0, 1, 0), (0, -1, 0),
                           (0, 0, 1), (0, 0, -1)):
            nx, ny, nz = cx + dx, cy + dy, cz + dz
            if 0 <= nx < w and 0 <= ny < d and 0 <= nz < h:
                if traversable[nx, ny, nz]:
                    seed[nx, ny, nz] = True

        # 2) Fallback: first solid block directly below core → seed from
        #    traversable cells adjacent to *that* block.  Allows the core
        #    to float in a large room while territory grows from the floor.
        if not np.any(seed):
            for z_below in range(cz + 1, h):
                if not traversable[cx, cy, z_below]:
                    # Found solid ground — seed from its traversable neighbors
                    for dx, dy, dz in ((1, 0, 0), (-1, 0, 0),
                                       (0, 1, 0), (0, -1, 0),
                                       (0, 0, 1), (0, 0, -1)):
                        nx, ny, nz = cx + dx, cy + dy, z_below + dz
                        if 0 <= nx < w and 0 <= ny < d and 0 <= nz < h:
                            if traversable[nx, ny, nz]:
                                seed[nx, ny, nz] = True
                    if np.any(seed):
                        logger.info(
                            "recompute: core floating, seeded from solid "
                            "block below at (%d, %d, %d)",
                            cx, cy, z_below,
                        )
                    break

        # 3) Wider radius search around core (robust against edge cases)
        if not np.any(seed):
            _SEED_SEARCH_RADIUS = 4
            r = _SEED_SEARCH_RADIUS
            x_lo = max(0, cx - r)
            x_hi = min(w, cx + r + 1)
            y_lo = max(0, cy - r)
            y_hi = min(d, cy + r + 1)
            z_lo = max(0, cz - r)
            z_hi = min(h, cz + r + 1)
            local_trav = traversable[x_lo:x_hi, y_lo:y_hi, z_lo:z_hi]
            if np.any(local_trav):
                seed[x_lo:x_hi, y_lo:y_hi, z_lo:z_hi] = local_trav
                logger.info(
                    "recompute: no immediate seed, found %d traversable cells "
                    "within radius %d of core",
                    int(np.sum(local_trav)), r,
                )

        if not np.any(seed):
            logger.warning(
                "recompute: NO SEED — no traversable cells near "
                "core (%d, %d, %d)! All visible set to False.",
                cx, cy, cz,
            )
            grid.claimed[:] = False
            grid.visible[:] = False
            # Core itself is always visible
            if grid.in_bounds(cx, cy, cz):
                grid.visible[cx, cy, cz] = True
            return

        # Iterative 6-connected dilation through air
        connected = seed.copy()
        max_iter = w + d + h

        for _ in range(max_iter):
            expanded = connected.copy()

            if w > 1:
                expanded[1:, :, :] |= connected[:-1, :, :]
                expanded[:-1, :, :] |= connected[1:, :, :]
            if d > 1:
                expanded[:, 1:, :] |= connected[:, :-1, :]
                expanded[:, :-1, :] |= connected[:, 1:, :]
            if h > 1:
                expanded[:, :, 1:] |= connected[:, :, :-1]
                expanded[:, :, :-1] |= connected[:, :, 1:]

            # Only keep expansion into traversable cells
            expanded &= traversable

            if np.array_equal(expanded, connected):
                break

            connected = expanded

        # Store claimed territory (save old state for change detection)
        old_claimed = grid.claimed.copy()
        old_visible = grid.visible.copy()
        grid.claimed[:] = connected

        # Compute visibility: solid blocks adjacent to at least one claimed cell
        # The "air-only" mask is needed so natural solids adjacent to claimed
        # air/functional blocks are visible (fog-of-war boundary).
        air_mask = (voxels == VOXEL_AIR) | (voxels == VOXEL_WATER)
        vis = np.zeros((w, d, h), dtype=np.bool_)
        if w > 1:
            vis[1:, :, :] |= connected[:-1, :, :]
            vis[:-1, :, :] |= connected[1:, :, :]
        if d > 1:
            vis[:, 1:, :] |= connected[:, :-1, :]
            vis[:, :-1, :] |= connected[:, 1:, :]
        if h > 1:
            vis[:, :, 1:] |= connected[:, :, :-1]
            vis[:, :, :-1] |= connected[:, :, 1:]

        # Natural solids adjacent to claimed territory are visible
        vis &= ~air_mask
        # Functional blocks that are themselves claimed are also visible
        vis |= (connected & ~air_mask)

        # Core block is always visible
        if grid.in_bounds(cx, cy, cz):
            vis[cx, cy, cz] = True

        # Ore x-ray dilation: ores/crystals within PLAYER_XRAY_RANGE of
        # visible blocks become visible (seeps through solid stone).
        xray_range = _cfg.PLAYER_XRAY_RANGE
        if xray_range > 0 and _cfg.XRAY_VISIBLE_TYPES:
            ore_mask = np.zeros((w, d, h), dtype=np.bool_)
            for vtype in _cfg.XRAY_VISIBLE_TYPES:
                ore_mask |= (voxels == vtype)
            xray_front = vis.copy()
            for _ in range(xray_range):
                expanded = xray_front.copy()
                # 6-connected dilation through solid blocks only
                if w > 1:
                    expanded[1:] |= xray_front[:-1]
                    expanded[:-1] |= xray_front[1:]
                if d > 1:
                    expanded[:, 1:] |= xray_front[:, :-1]
                    expanded[:, :-1] |= xray_front[:, 1:]
                if h > 1:
                    expanded[:, :, 1:] |= xray_front[:, :, :-1]
                    expanded[:, :, :-1] |= xray_front[:, :, 1:]
                # Only expand through solid (not air/water)
                expanded &= ~air_mask
                xray_front = expanded
            vis |= (xray_front & ore_mask)

        grid.visible[:] = vis

        claimed_count = int(np.sum(connected))
        visible_count = int(np.sum(vis))
        logger.debug("recompute: claimed=%d, visible=%d", claimed_count, visible_count)

        # If claimed territory or visibility changed, trigger chunk re-renders
        claimed_changed = not np.array_equal(old_claimed, connected)
        visible_changed = not np.array_equal(old_visible, vis)
        if claimed_changed or visible_changed:
            grid.mark_all_dirty()
            self.event_bus.publish("claimed_territory_changed")
            logger.debug(
                "Territory event fired: claimed_changed=%s, visible_changed=%s",
                claimed_changed, visible_changed,
            )
