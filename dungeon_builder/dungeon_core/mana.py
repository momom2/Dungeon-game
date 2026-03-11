"""Mana economy system — generation, consumption, soul capture, per-block management.

The dungeon core generates mana passively each tick.  Active digs and
magical traps consume mana.  When mana is depleted, digs pause and traps
deactivate.  Intruder deaths on claimed territory capture souls which
permanently increase the core's mana capacity.

Enchanted blocks have per-block capacitance with player-controlled
activation (active/inactive) and charge mode (charging/idle/draining).
Active blocks drain capacitance faster; charging pulls from the core
reserve; draining dumps capacitance with partial reclaim to the core.

Dependencies: config, core.event_bus, world.voxel_grid, building.build_system
Dependents: building.crafting_system, main (wiring), core.save_system,
    ui.enchanted_panel, tests/economy/
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
    MANA_CAPACITANCE,
    ENCHANTED_ACTIVE_DRAIN_PER_S,
    ENCHANTED_INACTIVE_DRAIN_PER_S,
    ENCHANTED_CHARGE_PER_S,
    ENCHANTED_PLAYER_DRAIN_PER_S,
    ENCHANTED_DRAIN_RECLAIM_PER_S,
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
        # Per-block mana capacitance
        "_capacitance",       # dict[(x,y,z), float] — current stored mana
        "_capacitance_max",   # dict[(x,y,z), float] — max capacity (from LUT)
        # Per-block activation and charge mode
        "_activated",         # dict[(x,y,z), bool]  — True if block is active
        "_charge_mode",       # dict[(x,y,z), str]   — "idle"|"charging"|"draining"
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

        # Per-block mana capacitance (sparse — only enchanted blocks)
        self._capacitance: dict[tuple[int, int, int], float] = {}
        self._capacitance_max: dict[tuple[int, int, int], float] = {}
        # Per-block activation and charge mode
        self._activated: dict[tuple[int, int, int], bool] = {}
        self._charge_mode: dict[tuple[int, int, int], str] = {}

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("intruder_died", self._on_intruder_died)
        event_bus.subscribe(
            "enchanted_block_toggle_activation", self._on_toggle_activation,
        )
        event_bus.subscribe(
            "enchanted_block_set_charge_mode", self._on_set_charge_mode,
        )

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

        # Capacitance: charge or drain per-block mana storage
        self._tick_capacitance()

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

    def _tick_capacitance(self) -> None:
        """Update per-block mana based on activation state and charge mode.

        Each enchanted block per tick:
        1. Passive drain — active blocks lose more than inactive ones.
        2. Charge mode — charging pulls from core reserve (capped by what
           the block actually needs); draining dumps capacitance fast with
           partial reclaim to core.
        3. Clamp to [0, max_cap].
        4. Auto-deactivate when capacitance reaches 0.
        """
        if not self._capacitance:
            return

        tps = TICKS_PER_SECOND
        active_drain = ENCHANTED_ACTIVE_DRAIN_PER_S / tps
        inactive_drain = ENCHANTED_INACTIVE_DRAIN_PER_S / tps
        charge_rate = ENCHANTED_CHARGE_PER_S / tps
        drain_rate = ENCHANTED_PLAYER_DRAIN_PER_S / tps
        drain_reclaim = ENCHANTED_DRAIN_RECLAIM_PER_S / tps

        depleted: list[tuple[int, int, int]] = []
        auto_deactivated: list[tuple[int, int, int]] = []

        for pos in list(self._capacitance):
            current = self._capacitance[pos]
            max_cap = self._capacitance_max.get(pos, 0.0)
            is_active = self._activated.get(pos, True)
            mode = self._charge_mode.get(pos, "idle")

            # 1. Passive drain based on activation state
            if is_active:
                current -= active_drain
            else:
                current -= inactive_drain

            # 2. Charge mode effects
            if mode == "charging":
                # Charge from core — only what the block actually needs
                want = min(charge_rate, max(0.0, max_cap - current))
                cost = min(want, self.mana)
                current += cost
                self.mana -= cost
            elif mode == "draining":
                current -= drain_rate
                # Reclaim some mana to core
                self.mana = min(self.max_mana, self.mana + drain_reclaim)

            # 3. Clamp
            current = max(0.0, min(max_cap, current))
            self._capacitance[pos] = current

            # 4. Auto-deactivate when depleted
            if current <= 0.0:
                depleted.append(pos)
                if is_active:
                    self._activated[pos] = False
                    auto_deactivated.append(pos)

        for pos in depleted:
            self.event_bus.publish(
                "block_capacitance_depleted",
                x=pos[0], y=pos[1], z=pos[2],
            )

        for pos in auto_deactivated:
            self.event_bus.publish(
                "enchanted_block_state_changed",
                x=pos[0], y=pos[1], z=pos[2],
                activated=False,
                charge_mode=self._charge_mode.get(pos, "idle"),
                capacitance=0.0,
                max_capacitance=self._capacitance_max.get(pos, 0.0),
            )

    # ── Voxel tracking ────────────────────────────────────────────────

    def _on_voxel_changed(self, x: int, y: int, z: int,
                          old_type: int, new_type: int, **kw) -> None:
        """Track magical trap placement/removal and capacitance."""
        if old_type in MAGICAL_TRAP_TYPES:
            self._trap_counts[old_type] = self._trap_counts.get(old_type, 1) - 1
        if new_type in MAGICAL_TRAP_TYPES:
            self._trap_counts[new_type] = self._trap_counts.get(new_type, 0) + 1

        # Capacitance tracking
        pos = (x, y, z)
        if old_type in MANA_CAPACITANCE:
            self._capacitance.pop(pos, None)
            self._capacitance_max.pop(pos, None)
            self._activated.pop(pos, None)
            self._charge_mode.pop(pos, None)
            self.event_bus.publish(
                "enchanted_block_removed", x=x, y=y, z=z,
            )
        if new_type in MANA_CAPACITANCE:
            self._capacitance_max[pos] = MANA_CAPACITANCE[new_type]
            self._capacitance[pos] = 0.0          # starts uncharged
            self._activated[pos] = True            # starts active
            self._charge_mode[pos] = "charging"    # starts charging

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

    # ── Capacitance queries ─────────────────────────────────────────────

    def inject_mana(self, x: int, y: int, z: int, amount: float) -> bool:
        """Inject mana into a block's capacitance (e.g. from a sprite).

        Returns True if the block has capacitance and accepted the mana.
        """
        pos = (x, y, z)
        max_cap = self._capacitance_max.get(pos)
        if max_cap is None:
            return False
        current = self._capacitance.get(pos, 0.0)
        self._capacitance[pos] = min(max_cap, current + amount)
        return True

    def is_block_powered(self, x: int, y: int, z: int) -> bool:
        """Return True if a block is active and has mana to operate.

        A block is powered when it is activated AND either the global
        system is powered or it has local capacitance > 0.
        """
        pos = (x, y, z)
        if not self._activated.get(pos, True):
            return False
        if self.traps_powered:
            return True
        return self._capacitance.get(pos, 0.0) > 0.0

    def get_block_capacitance(self, x: int, y: int, z: int) -> float:
        """Return current stored mana for a block (0.0 if no capacitance)."""
        return self._capacitance.get((x, y, z), 0.0)

    # ── Enchanted block control ──────────────────────────────────────

    def set_block_activated(self, x: int, y: int, z: int, active: bool) -> None:
        """Set whether an enchanted block is active or inactive."""
        pos = (x, y, z)
        if pos not in self._capacitance_max:
            return
        self._activated[pos] = active
        self._publish_block_state(pos)

    def set_block_charge_mode(self, x: int, y: int, z: int, mode: str) -> None:
        """Set charge mode: ``'idle'``, ``'charging'``, or ``'draining'``."""
        pos = (x, y, z)
        if pos not in self._capacitance_max:
            return
        if mode not in ("idle", "charging", "draining"):
            return
        self._charge_mode[pos] = mode
        self._publish_block_state(pos)

    def get_enchanted_block_state(
        self, x: int, y: int, z: int,
    ) -> dict | None:
        """Return full state for an enchanted block, or None if not enchanted."""
        pos = (x, y, z)
        max_cap = self._capacitance_max.get(pos)
        if max_cap is None:
            return None
        return {
            "activated": self._activated.get(pos, True),
            "charge_mode": self._charge_mode.get(pos, "idle"),
            "capacitance": self._capacitance.get(pos, 0.0),
            "max_capacitance": max_cap,
        }

    def _publish_block_state(self, pos: tuple[int, int, int]) -> None:
        """Publish the full enchanted block state for a position."""
        self.event_bus.publish(
            "enchanted_block_state_changed",
            x=pos[0], y=pos[1], z=pos[2],
            activated=self._activated.get(pos, True),
            charge_mode=self._charge_mode.get(pos, "idle"),
            capacitance=self._capacitance.get(pos, 0.0),
            max_capacitance=self._capacitance_max.get(pos, 0.0),
        )

    def _on_toggle_activation(
        self, x: int, y: int, z: int, **kw,
    ) -> None:
        """EventBus handler: toggle a block's activation state."""
        pos = (x, y, z)
        current = self._activated.get(pos, True)
        self.set_block_activated(x, y, z, not current)

    def _on_set_charge_mode(
        self, x: int, y: int, z: int, mode: str, **kw,
    ) -> None:
        """EventBus handler: set a block's charge mode."""
        self.set_block_charge_mode(x, y, z, mode)

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
        """Recount magical traps and rebuild capacitance from the grid.

        Called after loading a save to rebuild ``_trap_counts`` and
        ``_capacitance`` from the actual grid state.
        """
        import numpy as np

        self._trap_counts.clear()
        grid_arr = self.voxel_grid.grid
        for vtype in MAGICAL_TRAP_TYPES:
            count = int(np.count_nonzero(grid_arr == vtype))
            if count > 0:
                self._trap_counts[vtype] = count

        # Rebuild capacitance and activation maps
        self._capacitance.clear()
        self._capacitance_max.clear()
        self._activated.clear()
        self._charge_mode.clear()
        for vtype, max_cap in MANA_CAPACITANCE.items():
            positions = np.argwhere(grid_arr == vtype)
            for pos in positions:
                key = (int(pos[0]), int(pos[1]), int(pos[2]))
                self._capacitance_max[key] = max_cap
                self._capacitance[key] = max_cap  # Assume fully charged on load
                self._activated[key] = True        # Default: active
                self._charge_mode[key] = "idle"    # Default: idle (save overrides)
