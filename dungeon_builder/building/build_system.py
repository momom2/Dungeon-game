"""Dig queue and construction system.

Dependencies: config, core.event_bus, core.game_state, world.voxel_grid,
    dungeon_core.mana (via mana_power_changed event)
Dependents: main (wiring), core.game_state, core.save_system,
    rendering.voxel_renderer, tests/building/, tests/rendering/
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR,
    NON_DIGGABLE,
    DIG_DURATION,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState
    from dungeon_builder.world.voxel_grid import VoxelGrid

logger = logging.getLogger("dungeon_builder.building")


class DigJob:
    """A queued dig operation on a single voxel."""

    __slots__ = ("x", "y", "z", "ticks_remaining", "total_ticks")

    def __init__(self, x: int, y: int, z: int, duration_ticks: int) -> None:
        self.x = x
        self.y = y
        self.z = z
        self.ticks_remaining = duration_ticks
        self.total_ticks = duration_ticks


class BuildSystem:
    """Manages the dig queue: queues dig jobs, processes them over ticks.

    Dig completion makes material loose (instead of removing it).

    Three dig lists:
    - ``pending_digs``: blocks not yet visible (through fog); skip ALL
      validation except duplicate check.  When they become visible they are
      either promoted to ``dig_queue`` (valid) or cancelled (invalid).
    - ``dig_queue``: validated, waiting for a concurrent-dig slot.
    - ``active_digs``: currently progressing.
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        game_state: GameState | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.game_state = game_state
        self.dig_queue: list[DigJob] = []
        self.active_digs: list[DigJob] = []
        self.pending_digs: list[DigJob] = []  # invisible blocks awaiting reveal
        # O(1) position index — mirrors all three lists above.
        # Every add/remove to pending/queue/active MUST also update this set.
        self._dig_positions: set[tuple[int, int, int]] = set()
        # Mana power flag — when False, active digs pause (no progress)
        self._digs_powered: bool = True

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("mana_power_changed", self._on_mana_power_changed)
        event_bus.subscribe("voxel_left_clicked", self._on_voxel_left_clicked)
        event_bus.subscribe("claimed_territory_changed", self._check_pending_digs)
        # Pending check removed from dig_complete — claimed_territory_changed
        # fires once after territory recomputes, which is the correct trigger.
        # The old per-event handler caused O(n²) scans on bulk completions.
        event_bus.subscribe("dig_complete", self._on_dig_complete_auto_bag)
        event_bus.subscribe("drag_dig_area", self._on_drag_dig_area)

    # ── Public API ────────────────────────────────────────────────────

    def queue_dig(self, x: int, y: int, z: int) -> bool:
        """Queue a dig at the given voxel position.  Returns True if queued.

        If the block is not yet visible (fog-of-war), it goes into
        ``pending_digs`` — no validation except duplicate check.
        """
        # Don't double-queue across any list
        if self._is_in_any_list(x, y, z):
            return False

        vtype = self.voxel_grid.get(x, y, z)

        # Can't dig air or non-diggable types regardless of visibility
        if vtype == VOXEL_AIR or vtype in NON_DIGGABLE:
            return False

        # If not visible, add as pending (skip remaining validation)
        if not self.voxel_grid.is_visible(x, y, z):
            # Use a placeholder duration; real duration set on promotion
            job = DigJob(x, y, z, 0)
            self.pending_digs.append(job)
            self._dig_positions.add((x, y, z))
            self.event_bus.publish("dig_pending", x=x, y=y, z=z)
            self.event_bus.publish(
                "error_message",
                text="Dig queued \u2014 will start when reachable",
                color=(0.8, 0.7, 0.3, 1),
            )
            logger.debug("Dig pending (invisible) at (%d, %d, %d)", x, y, z)
            return True

        # Can't dig already-loose material
        if self.voxel_grid.is_loose(x, y, z):
            self.event_bus.publish(
                "error_message", text="Material is already loose"
            )
            return False

        duration = DIG_DURATION.get(vtype, 40)
        job = DigJob(x, y, z, duration)
        self.dig_queue.append(job)
        self._dig_positions.add((x, y, z))
        self.event_bus.publish("dig_queued", x=x, y=y, z=z, duration=duration)
        logger.debug("Dig queued at (%d, %d, %d), duration=%d ticks", x, y, z, duration)
        return True

    def cancel_dig(self, x: int, y: int, z: int) -> bool:
        """Cancel a dig at (x, y, z).  Returns True if cancelled.

        Searches ``pending_digs``, ``dig_queue``, and ``active_digs``.
        Block is fully restored (no partial damage — dig only makes loose
        on completion).
        """
        for lst in (self.pending_digs, self.dig_queue, self.active_digs):
            for job in lst:
                if job.x == x and job.y == y and job.z == z:
                    lst.remove(job)
                    self._dig_positions.discard((x, y, z))
                    self.event_bus.publish("dig_cancelled", x=x, y=y, z=z)
                    logger.debug("Dig cancelled at (%d, %d, %d)", x, y, z)
                    return True
        return False

    def is_being_dug(self, x: int, y: int, z: int) -> bool:
        """Return True if the voxel is queued, active, *or* pending."""
        return self._is_in_any_list(x, y, z)

    def is_pending_dig(self, x: int, y: int, z: int) -> bool:
        """Return True if the voxel is in the pending (invisible) list."""
        for job in self.pending_digs:
            if job.x == x and job.y == y and job.z == z:
                return True
        return False

    def get_dig_progress(self, x: int, y: int, z: int) -> float:
        """Return dig progress as 0.0 (not started) to 1.0 (complete).

        Queued and pending jobs return 0.0.  Active jobs return fraction
        completed.  Returns -1.0 if the voxel is not being dug.
        """
        if (x, y, z) not in self._dig_positions:
            return -1.0
        for job in self.active_digs:
            if job.x == x and job.y == y and job.z == z:
                return 1.0 - (job.ticks_remaining / job.total_ticks)
        # In pending or queue — progress is 0
        return 0.0

    # ── Tick processing ───────────────────────────────────────────────

    def _on_tick(self, tick: int, **kw) -> None:
        # Promote queued jobs to active (dev mode overrides the limit)
        limit = (
            _cfg.DEV_MAX_CONCURRENT_DIGS if _cfg.DEV_MODE
            else _cfg.MAX_CONCURRENT_DIGS
        )
        while len(self.active_digs) < limit and self.dig_queue:
            job = self.dig_queue.pop(0)
            self.active_digs.append(job)

        # Process active digs (paused when mana depleted)
        completed: list[DigJob] = []
        for job in self.active_digs:
            if self._digs_powered:
                job.ticks_remaining -= 1
            if job.ticks_remaining <= 0:
                # Mark material as loose instead of removing it
                self.voxel_grid.set_loose(job.x, job.y, job.z, True)
                completed.append(job)
                logger.debug("Dig complete at (%d, %d, %d) — now loose", job.x, job.y, job.z)

        for job in completed:
            self.active_digs.remove(job)
            self._dig_positions.discard((job.x, job.y, job.z))

        # Publish completions: batch if multiple, per-voxel if single.
        # Multi-completions: batch auto-bag FIRST (so renderer sees final
        # state), then 'dig_batch_complete' (renderer rebuild), then
        # per-voxel 'dig_complete' (for pending checks).
        if len(completed) > 1:
            positions = [(j.x, j.y, j.z) for j in completed]
            # Batch auto-bag: one call, one event, no per-voxel voxel_changed
            self._auto_bag_batch(positions)
            self.event_bus.publish("dig_batch_complete", positions=positions)
        for job in completed:
            self.event_bus.publish("dig_complete", x=job.x, y=job.y, z=job.z)

    # ── Pending dig promotion ─────────────────────────────────────────

    def _check_pending_digs(self, **kw) -> None:
        """Promote or cancel pending digs whose blocks have become visible.

        Called on ``claimed_territory_changed`` and ``dig_complete``.
        Per design: pending digs skip ALL validation until visible.  Once
        visible, re-validate: if invalid (non-diggable, already loose, air)
        → cancel with ``dig_cancelled``.  If valid → promote to ``dig_queue``.
        """
        still_pending: list[DigJob] = []
        for job in self.pending_digs:
            x, y, z = job.x, job.y, job.z
            if not self.voxel_grid.is_visible(x, y, z):
                still_pending.append(job)
                continue

            # Now visible — validate
            vtype = self.voxel_grid.get(x, y, z)
            if (
                vtype == VOXEL_AIR
                or vtype in NON_DIGGABLE
                or self.voxel_grid.is_loose(x, y, z)
            ):
                # Invalid — cancel (player can now see why)
                self._dig_positions.discard((x, y, z))
                self.event_bus.publish("dig_cancelled", x=x, y=y, z=z)
                logger.debug(
                    "Pending dig cancelled at (%d, %d, %d): invalid (vtype=%d)",
                    x, y, z, vtype,
                )
                continue

            # Valid — set real duration and promote
            duration = DIG_DURATION.get(vtype, 40)
            job.ticks_remaining = duration
            job.total_ticks = duration
            self.dig_queue.append(job)
            self.event_bus.publish("dig_queued", x=x, y=y, z=z, duration=duration)
            logger.debug(
                "Pending dig promoted at (%d, %d, %d), duration=%d", x, y, z, duration
            )

        self.pending_digs = still_pending

    def queue_dig_area(
        self,
        x_min: int, x_max: int,
        y_min: int, y_max: int,
        z_min: int, z_max: int,
    ) -> int:
        """Queue digs for all valid blocks in the given 3D rectangle.

        Returns the number of blocks actually queued.
        Skips: air, non-diggable, already-loose, already-queued.

        Uses batched events (``dig_batch_queued`` / ``dig_batch_pending``)
        instead of per-voxel events to avoid O(n) chunk rebuilds.
        """
        queued: list[tuple[int, int, int]] = []
        pending: list[tuple[int, int, int]] = []
        for z in range(z_min, z_max + 1):
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    if self._is_in_any_list(x, y, z):
                        continue
                    vtype = self.voxel_grid.get(x, y, z)
                    # Skip air and non-diggable regardless of visibility
                    if vtype == VOXEL_AIR or vtype in NON_DIGGABLE:
                        continue
                    if not self.voxel_grid.is_visible(x, y, z):
                        job = DigJob(x, y, z, 0)
                        self.pending_digs.append(job)
                        self._dig_positions.add((x, y, z))
                        pending.append((x, y, z))
                        continue
                    if self.voxel_grid.is_loose(x, y, z):
                        continue
                    duration = DIG_DURATION.get(vtype, 40)
                    job = DigJob(x, y, z, duration)
                    self.dig_queue.append(job)
                    self._dig_positions.add((x, y, z))
                    queued.append((x, y, z))

        # Publish batch events — renderers rebuild each affected chunk once
        if queued:
            self.event_bus.publish("dig_batch_queued", positions=queued)
        if pending:
            self.event_bus.publish("dig_batch_pending", positions=pending)

        count = len(queued) + len(pending)
        if count > 0:
            self.event_bus.publish(
                "error_message",
                text=f"Queued {count} block{'s' if count != 1 else ''} for digging",
                color=(0.8, 0.8, 0.3, 1),
            )
        return count

    def cancel_dig_area(
        self,
        x_min: int, x_max: int,
        y_min: int, y_max: int,
        z_min: int, z_max: int,
    ) -> int:
        """Cancel all queued digs in the given 3D rectangle.

        Returns the number of digs actually cancelled.
        Uses a single ``dig_batch_cancelled`` event instead of per-voxel.
        """
        cancelled: list[tuple[int, int, int]] = []
        for z in range(z_min, z_max + 1):
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    if (x, y, z) not in self._dig_positions:
                        continue
                    for lst in (self.pending_digs, self.dig_queue,
                                self.active_digs):
                        found = None
                        for job in lst:
                            if job.x == x and job.y == y and job.z == z:
                                found = job
                                break
                        if found is not None:
                            lst.remove(found)
                            self._dig_positions.discard((x, y, z))
                            cancelled.append((x, y, z))
                            break

        if cancelled:
            self.event_bus.publish(
                "dig_batch_cancelled", positions=cancelled,
            )
            self.event_bus.publish(
                "error_message",
                text=f"Cancelled {len(cancelled)} dig{'s' if len(cancelled) != 1 else ''}",
                color=(0.7, 0.5, 0.3, 1),
            )
        return len(cancelled)

    def toggle_dig_area(
        self,
        x_min: int, x_max: int,
        y_min: int, y_max: int,
        z_min: int, z_max: int,
    ) -> int:
        """Toggle dig queue for blocks in the area.

        If ALL diggable blocks are already queued → cancel them all.
        Otherwise → queue the ones that aren't queued yet.
        Loose blocks in the area are always picked up (bagged).
        Returns the number of blocks affected (digs + pickups).
        """
        # First pass: classify blocks and collect loose blocks
        all_queued = True
        has_diggable = False
        loose_positions: list[tuple[int, int, int]] = []
        for z in range(z_min, z_max + 1):
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    vtype = self.voxel_grid.get(x, y, z)
                    if vtype == VOXEL_AIR or vtype in NON_DIGGABLE:
                        continue
                    if self.voxel_grid.is_loose(x, y, z):
                        loose_positions.append((x, y, z))
                        continue
                    has_diggable = True
                    if not self._is_in_any_list(x, y, z):
                        all_queued = False

        # Pick up loose blocks (always, regardless of toggle direction)
        picked_up = self._pick_up_loose_batch(loose_positions)

        if not has_diggable:
            return picked_up

        if all_queued:
            return picked_up + self.cancel_dig_area(
                x_min, x_max, y_min, y_max, z_min, z_max,
            )
        else:
            return picked_up + self.queue_dig_area(
                x_min, x_max, y_min, y_max, z_min, z_max,
            )

    def _pick_up_loose_batch(
        self, positions: list[tuple[int, int, int]],
    ) -> int:
        """Batch pick up loose blocks via the move system.

        Returns the number of blocks actually picked up.
        """
        if not positions:
            return 0
        if self.game_state is None:
            return 0
        ms = self.game_state.move_system
        if ms is None:
            return 0
        picked = ms.pick_up_batch(positions)
        if picked > 0:
            self.event_bus.publish(
                "error_message",
                text=f"Picked up {picked} loose block{'s' if picked != 1 else ''}",
                color=(0.3, 0.8, 0.3, 1),
            )
        return picked

    # ── Event handlers ────────────────────────────────────────────────

    def _on_voxel_left_clicked(self, x: int, y: int, z: int, mode: str, **kw) -> None:
        if mode == "dig":
            # If already being dug → cancel
            if self.is_being_dug(x, y, z):
                self.cancel_dig(x, y, z)
            else:
                self.queue_dig(x, y, z)

    def _on_drag_dig_area(
        self, x_min: int, x_max: int, y_min: int, y_max: int,
        z_min: int, z_max: int, **kw,
    ) -> None:
        """Handle drag-select area event — toggle dig queue."""
        self.toggle_dig_area(x_min, x_max, y_min, y_max, z_min, z_max)

    def _auto_bag_batch(self, positions: list[tuple[int, int, int]]) -> None:
        """Batch auto-bag for multiple completed digs (avoids per-voxel events).

        Called BEFORE ``dig_batch_complete`` so the renderer sees the
        final state (air) when it rebuilds chunks.
        """
        if not _cfg.AUTO_BAG_DIG:
            return
        if self.game_state is None:
            return
        ms = self.game_state.move_system
        if ms is None:
            return
        ms.pick_up_batch(positions)

    def _on_dig_complete_auto_bag(self, x: int, y: int, z: int, **kw) -> None:
        """Automatically pick up dug material into the player's bag.

        Skips if the block was already picked up by batch auto-bag.
        """
        if not _cfg.AUTO_BAG_DIG:
            return
        if self.game_state is None:
            return
        ms = self.game_state.move_system
        if ms is None:
            return
        # If already air (picked up by batch), skip
        if self.voxel_grid.get(x, y, z) == VOXEL_AIR:
            return
        ms.pick_up(x, y, z)

    def _on_mana_power_changed(self, digs_powered: bool, **kw) -> None:
        """Update dig power state from ManaSystem."""
        self._digs_powered = digs_powered

    # ── Internal helpers ──────────────────────────────────────────────

    def _is_in_any_list(self, x: int, y: int, z: int) -> bool:
        """Check if (x,y,z) appears in any of the three dig lists.  O(1)."""
        return (x, y, z) in self._dig_positions
