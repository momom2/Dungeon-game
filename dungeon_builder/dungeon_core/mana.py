"""Mana economy system — generation, consumption, soul capture.

The dungeon core generates mana passively each tick.  Active digs and
magical traps consume mana.  When mana is depleted, digs pause and traps
deactivate.  Intruder deaths on claimed territory capture souls which
permanently increase the core's mana capacity.

Dependencies: config, core.event_bus, world.voxel_grid, building.build_system
Dependents: building.crafting_system, main (wiring), core.save_system,
    tests/economy/test_mana_system.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.config import (
    MANA_BASE_CAPACITY,
    MANA_GENERATION_PER_TICK,
    MANA_DIG_COST_PER_TICK,
    MANA_SOUL_CAPACITY_BONUS,
    MANA_UPKEEP_PER_SECOND,
    MAGICAL_TRAP_TYPES,
    TICKS_PER_SECOND,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid
    from dungeon_builder.building.build_system import BuildSystem

logger = logging.getLogger("dungeon_builder.economy")


class ManaSystem:
    """Mana pool: generation, consumption, soul capture, power state.

    Pure Python, no Panda3D dependency — fully testable without a window.
    """

    __slots__ = (
        "event_bus",
        "voxel_grid",
        "mana",
        "max_mana",
        "souls",
        "_trap_counts",
        "_build_system",
        "digs_powered",
        "traps_powered",
    )

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        build_system: BuildSystem,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self._build_system = build_system

        self.mana: float = 0.0
        self.max_mana: float = float(MANA_BASE_CAPACITY)
        self.souls: int = 0

        # Per-type trap counts: vtype -> number on the map
        self._trap_counts: dict[int, int] = {}

        # Power flags (True = system has enough mana to operate)
        self.digs_powered: bool = True
        self.traps_powered: bool = True

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("intruder_died", self._on_intruder_died)

    # ── Tick processing ───────────────────────────────────────────────

    def _on_tick(self, tick: int, **kw) -> None:
        """Generate mana, deduct costs, update power state."""
        gen = MANA_GENERATION_PER_TICK
        dig_cost = len(self._build_system.active_digs) * MANA_DIG_COST_PER_TICK
        trap_cost = self._compute_trap_upkeep()

        net = gen - dig_cost - trap_cost
        old_mana = self.mana
        self.mana = max(0.0, min(self.max_mana, self.mana + net))

        # Power state: powered when mana > 0, OR when generation covers costs
        old_digs = self.digs_powered
        old_traps = self.traps_powered
        self.digs_powered = self.mana > 0.0 or net >= 0.0
        self.traps_powered = self.mana > 0.0 or net >= 0.0

        if self.digs_powered != old_digs or self.traps_powered != old_traps:
            self.event_bus.publish(
                "mana_power_changed",
                digs_powered=self.digs_powered,
                traps_powered=self.traps_powered,
            )

        # Publish mana state every 10 ticks (not every tick, to reduce churn)
        if tick % 10 == 0 or self.mana != old_mana:
            self.event_bus.publish(
                "mana_changed",
                mana=self.mana,
                max_mana=self.max_mana,
            )

    def _compute_trap_upkeep(self) -> float:
        """Sum per-type upkeep costs across all magical traps on the map."""
        total = 0.0
        for vtype, count in self._trap_counts.items():
            if count > 0:
                total += count * MANA_UPKEEP_PER_SECOND[vtype] / TICKS_PER_SECOND
        return total

    # ── Voxel tracking ────────────────────────────────────────────────

    def _on_voxel_changed(self, x: int, y: int, z: int,
                          old_type: int, new_type: int, **kw) -> None:
        """Track magical trap placement and removal."""
        if old_type in MAGICAL_TRAP_TYPES:
            self._trap_counts[old_type] = self._trap_counts.get(old_type, 1) - 1
        if new_type in MAGICAL_TRAP_TYPES:
            self._trap_counts[new_type] = self._trap_counts.get(new_type, 0) + 1

    # ── Soul capture ──────────────────────────────────────────────────

    def _on_intruder_died(self, intruder, **kw) -> None:
        """Capture soul when intruder dies on claimed territory."""
        x, y, z = intruder.x, intruder.y, intruder.z
        grid = self.voxel_grid
        if grid.in_bounds(x, y, z) and bool(grid.claimed[x, y, z]):
            self.souls += 1
            self.max_mana = float(
                MANA_BASE_CAPACITY + self.souls * MANA_SOUL_CAPACITY_BONUS
            )
            self.event_bus.publish(
                "soul_captured",
                souls=self.souls,
                max_mana=self.max_mana,
            )
            logger.info(
                "Soul captured (total %d, max mana now %.0f)",
                self.souls, self.max_mana,
            )

    # ── Mana spending ─────────────────────────────────────────────────

    def can_spend(self, amount: float) -> bool:
        """Return True if the mana pool has at least *amount*."""
        return self.mana >= amount

    def spend(self, amount: float) -> bool:
        """Deduct *amount* from the pool.  Returns False if insufficient."""
        if self.mana >= amount:
            self.mana -= amount
            self.event_bus.publish(
                "mana_changed",
                mana=self.mana,
                max_mana=self.max_mana,
            )
            return True
        return False

    # ── State query ───────────────────────────────────────────────────

    def get_trap_upkeep_per_second(self) -> float:
        """Return total trap upkeep in mana per second."""
        total = 0.0
        for vtype, count in self._trap_counts.items():
            if count > 0:
                total += count * MANA_UPKEEP_PER_SECOND[vtype]
        return total

    def get_stats(self) -> dict:
        """Return summary stats for HUD / debug."""
        trap_total = sum(max(0, c) for c in self._trap_counts.values())
        return {
            "mana": self.mana,
            "max_mana": self.max_mana,
            "souls": self.souls,
            "traps": trap_total,
            "trap_upkeep_per_s": self.get_trap_upkeep_per_second(),
            "digs_powered": self.digs_powered,
            "traps_powered": self.traps_powered,
        }

    def recount_traps(self) -> None:
        """Recount magical traps from the voxel grid.

        Called after loading a save to rebuild ``_trap_counts`` from
        the actual grid state.
        """
        import numpy as np

        self._trap_counts.clear()
        grid_arr = self.voxel_grid.grid
        for vtype in MAGICAL_TRAP_TYPES:
            count = int(np.count_nonzero(grid_arr == vtype))
            if count > 0:
                self._trap_counts[vtype] = count
