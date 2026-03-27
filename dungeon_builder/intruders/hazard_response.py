"""Hazard-response mixin -- environmental awareness and hazard interactions.

Extracts vision, water interaction, pressure plate activation, fragile floor
collapse, alarm bell detection, alarm cooldowns, and betrayal logic from
``IntruderAI`` so that ``decision.py`` stays under the 600-line target.

Dependencies: config, intruders.agent, intruders.archetypes, intruders.party,
    intruders.vision
Dependents: intruders.decision (IntruderAI inherits this mixin)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.vision import (
    compute_los,
    compute_arcane_sight,
    compute_thermal_vision,
)
from dungeon_builder.config import (
    VOXEL_STONE,
    VOXEL_WATER,
    VOXEL_TREASURE,
    VOXEL_SPIKE,
    VOXEL_GOLD_BAIT,
    VOXEL_PRESSURE_PLATE,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    VOXEL_AIR,
    SURFACE_Z,
    MORALE_DAMAGE_PENALTY,
    MORALE_HAZARD_PENALTY,
    PRESSURE_PLATE_TRIGGER_RANGE,
    ALARM_BELL_DETECTION_RANGE,
    ALARM_BELL_COOLDOWN,
    FRAGILE_FLOOR_WEIGHT_THRESHOLD,
    WATER_DAMAGE_DEPTH_THRESHOLD,
    WATER_DAMAGE_PER_TICK,
    WATER_CURRENT_PUSH_THRESHOLD,
    DARKVISION_DEPTH_THRESHOLD,
)

if TYPE_CHECKING:
    from dungeon_builder.intruders.party import Party

logger = logging.getLogger("dungeon_builder.intruders")


class HazardResponseMixin:
    """Mixin providing environmental awareness and hazard interactions.

    Relies on attributes initialised by ``IntruderAI.__init__``:
        event_bus, voxel_grid, rng,
        _alarm_cooldowns, _traps_powered
    Also calls ``_on_intruder_death`` and ``_repath_intruder`` from
    other mixins / the main class, resolved at runtime via MRO.
    """

    # -- Vision -------------------------------------------------------------

    def _update_vision(self, intruder: Intruder) -> None:
        """Update the intruder's personal map from current LOS + special vision.

        Only recomputes when the intruder has moved since the last vision update
        (_vision_dirty flag), avoiding expensive ray-casting on stationary ticks.
        """
        if not intruder._vision_dirty:
            return
        intruder._vision_dirty = False

        grid = self.voxel_grid
        arch = intruder.archetype
        x, y, z = intruder.x, intruder.y, intruder.z
        pmap = intruder.personal_map

        # Track hazards known before vision update (for morale penalty)
        hazards_before = len(pmap.hazards)

        # Effective perception: base + torch bonus + darkvision underground
        eff_range = intruder.effective_perception
        if z > SURFACE_Z + DARKVISION_DEPTH_THRESHOLD:
            eff_range += arch.darkvision_range

        # Standard LOS (with vision deception for certain blocks)
        visible = compute_los(grid, x, y, z, eff_range)
        for vx, vy, vz in visible:
            vtype = grid.get(vx, vy, vz)
            bstate = int(grid.block_state[vx, vy, vz])
            # Vision deception: Gold Bait looks like Treasure to normal sight
            if vtype == VOXEL_GOLD_BAIT:
                pmap.reveal(vx, vy, vz, VOXEL_TREASURE, bstate)
            # Vision deception: Fragile Floor looks like Stone to normal sight
            elif vtype == VOXEL_FRAGILE_FLOOR:
                pmap.reveal(vx, vy, vz, VOXEL_STONE, bstate)
            else:
                pmap.reveal(vx, vy, vz, vtype, bstate)

        # Arcane sight (Gloomwarden) -- sees true types through walls
        if arch.arcane_sight_range > 0:
            arcane = compute_arcane_sight(grid, x, y, z, arch.arcane_sight_range)
            for vx, vy, vz in arcane:
                vtype = grid.get(vx, vy, vz)
                bstate = int(grid.block_state[vx, vy, vz])
                # Arcane sight sees true types (no deception)
                pmap.reveal(vx, vy, vz, vtype, bstate)
                # Additionally mark baits and hazards for true types
                if vtype == VOXEL_GOLD_BAIT:
                    pmap.mark_bait(vx, vy, vz)
                elif vtype == VOXEL_FRAGILE_FLOOR:
                    pmap.mark_hazard(vx, vy, vz)

        # Thermal vision -- equipment-based fire immunity grants thermal sense
        if intruder.has_fire_immunity and arch.perception_range >= 4:
            thermal = compute_thermal_vision(grid, x, y, z, 4)
            for vx, vy, vz in thermal:
                vtype = grid.get(vx, vy, vz)
                bstate = int(grid.block_state[vx, vy, vz])
                pmap.reveal(vx, vy, vz, vtype, bstate)

        # Morale penalty for newly revealed hazards
        new_hazards = len(pmap.hazards) - hazards_before
        if new_hazards > 0:
            intruder.morale = max(
                0.0, intruder.morale - MORALE_HAZARD_PENALTY * new_hazards,
            )

    # -- Water interaction --------------------------------------------------

    def _check_water_interaction(self, intruder: Intruder) -> None:
        """Check for water hazards at the intruder's position.

        - **Deep water damage**: If the intruder is in water and the water
          column depth (contiguous water blocks above) meets or exceeds
          ``WATER_DAMAGE_DEPTH_THRESHOLD``, the intruder takes
          ``WATER_DAMAGE_PER_TICK`` damage each tick.  Intruders with
          water-breathing equipment are immune.
        - **Current push**: If the water velocity magnitude at the intruder's
          position exceeds ``WATER_CURRENT_PUSH_THRESHOLD``, the intruder is
          pushed one cell in the dominant lateral velocity direction.
        """
        grid = self.voxel_grid
        x, y, z = intruder.x, intruder.y, intruder.z

        if not grid.in_bounds(x, y, z):
            return

        vtype = int(grid.grid[x, y, z])
        if vtype != VOXEL_WATER:
            return

        # --- Deep water damage ---
        # Count contiguous water above (toward surface, z-1, z-2, ...)
        depth = 1
        check_z = z - 1
        while check_z >= 0 and int(grid.grid[x, y, check_z]) == VOXEL_WATER:
            depth += 1
            check_z -= 1

        if depth >= WATER_DAMAGE_DEPTH_THRESHOLD:
            # Water-breathing equipment prevents drowning damage
            if not intruder.has_water_breathing:
                intruder.take_damage(WATER_DAMAGE_PER_TICK)
                intruder.morale = max(0.0, intruder.morale - MORALE_DAMAGE_PENALTY)
                if not intruder.alive:
                    self._on_intruder_death(intruder)
                    return

        # --- Current push ---
        vx = float(grid.water_vx[x, y, z])
        vy = float(grid.water_vy[x, y, z])
        # Only consider lateral velocity (vx, vy), not vertical
        speed = (vx * vx + vy * vy) ** 0.5

        if speed < WATER_CURRENT_PUSH_THRESHOLD:
            return

        # Push in dominant lateral direction
        if abs(vx) >= abs(vy):
            push_dx = 1 if vx > 0 else -1
            push_dy = 0
        else:
            push_dx = 0
            push_dy = 1 if vy > 0 else -1

        nx, ny = x + push_dx, y + push_dy
        if (
            grid.in_bounds(nx, ny, z)
            and int(grid.grid[nx, ny, z]) in (VOXEL_AIR, VOXEL_WATER)
        ):
            intruder.x, intruder.y = nx, ny
            intruder._vision_dirty = True
            self.event_bus.publish("intruder_moved", intruder=intruder)

    # -- Pressure plate activation ------------------------------------------

    def _activate_pressure_plate(
        self, x: int, y: int, z: int, intruder: Intruder,
    ) -> None:
        """Activate a pressure plate and trigger adjacent traps.

        Only fires when the pressure plate is powered — either globally
        via ``_traps_powered`` or locally via block mana capacitance.

        Within PRESSURE_PLATE_TRIGGER_RANGE, activates:
        - Spikes: set block_state = 1 (extended)
        - Enchanted Doors: toggle block_state (open<->closed)
        - Enchanted Floodgates: toggle block_state (open<->closed)

        Regular doors and floodgates do NOT respond to pressure plates.
        """
        if not self._is_trap_powered_at(x, y, z):
            return
        grid = self.voxel_grid
        r = PRESSURE_PLATE_TRIGGER_RANGE
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    nx, ny, nz = x + dx, y + dy, z + dz
                    if not grid.in_bounds(nx, ny, nz):
                        continue
                    vtype = grid.get(nx, ny, nz)
                    if vtype == VOXEL_SPIKE:
                        grid.set_block_state(nx, ny, nz, 1)  # Extend
                    elif vtype == VOXEL_ENCHANTED_DOOR:
                        # Toggle: open->closed, closed->open
                        old = int(grid.block_state[nx, ny, nz])
                        grid.set_block_state(nx, ny, nz, 1 - old)
                    elif vtype == VOXEL_ENCHANTED_FLOODGATE:
                        # Toggle: open->closed, closed->open
                        old = int(grid.block_state[nx, ny, nz])
                        grid.set_block_state(nx, ny, nz, 1 - old)
        self.event_bus.publish(
            "pressure_plate_activated",
            intruder=intruder, x=x, y=y, z=z,
        )

    # -- Fragile floor collapse ---------------------------------------------

    def _check_fragile_floor(
        self, intruder: Intruder, x: int, y: int, z: int,
    ) -> bool:
        """Check and handle fragile floor collapse.

        Increments block_state each step. If >= FRAGILE_FLOOR_WEIGHT_THRESHOLD,
        the floor collapses to air and the intruder falls.

        Returns True if the floor collapsed (caller should handle the fall).
        """
        grid = self.voxel_grid
        if grid.get(x, y, z) != VOXEL_FRAGILE_FLOOR:
            return False

        current = int(grid.block_state[x, y, z])
        new_state = current + 1
        if new_state >= FRAGILE_FLOOR_WEIGHT_THRESHOLD:
            # Collapse!
            grid.set(x, y, z, VOXEL_AIR)
            intruder.personal_map.mark_hazard(x, y, z)
            self.event_bus.publish(
                "fragile_floor_collapsed",
                intruder=intruder, x=x, y=y, z=z,
            )
            return True
        else:
            grid.set_block_state(x, y, z, new_state)
            return False

    # -- Alarm bell detection -----------------------------------------------

    def _check_alarm_bells(self, intruder: Intruder) -> None:
        """Check if intruder is within range of any alarm bell.

        Uses ``_alarm_bell_positions`` spatial index (O(bells) instead of
        O(r^3)) and filters by Manhattan distance. Each bell has a cooldown
        (tracked in ``_alarm_cooldowns``) to prevent spam.

        Deactivated when mana is depleted — unless the specific bell
        has local capacitance from a sprite.
        """
        ix, iy, iz = intruder.x, intruder.y, intruder.z
        r = ALARM_BELL_DETECTION_RANGE

        for bell_pos in self._alarm_bell_positions:
            bx, by, bz = bell_pos
            if abs(bx - ix) + abs(by - iy) + abs(bz - iz) > r:
                continue
            # Per-bell power check (global or local capacitance)
            if not self._is_trap_powered_at(bx, by, bz):
                continue
            # Check cooldown
            if self._alarm_cooldowns.get(bell_pos, 0) > 0:
                continue
            # Trigger alarm!
            self._alarm_cooldowns[bell_pos] = ALARM_BELL_COOLDOWN
            # Share alarm zone with intruder's personal map
            intruder.personal_map.mark_alarm_zone(bx, by, bz)
            self.event_bus.publish(
                "alarm_bell_triggered",
                intruder=intruder,
                bell_x=bx, bell_y=by, bell_z=bz,
            )

    def _tick_alarm_cooldowns(self) -> None:
        """Decrement all alarm bell cooldowns each tick."""
        expired: list[tuple[int, int, int]] = []
        for pos, cd in self._alarm_cooldowns.items():
            if cd <= 1:
                expired.append(pos)
            else:
                self._alarm_cooldowns[pos] = cd - 1
        for pos in expired:
            del self._alarm_cooldowns[pos]

    # -- Betrayal -----------------------------------------------------------

    def _tick_betrayals(self, party: Party) -> None:
        """Check for treasure betrayals in a party."""
        grid = self.voxel_grid
        treasure_adj: dict[int, bool] = {}

        for m in party.alive_members:
            found = False
            for dx, dy, dz in (
                (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                (0, 0, 1), (0, 0, -1),
            ):
                nx, ny, nz = m.x + dx, m.y + dy, m.z + dz
                if (
                    grid.in_bounds(nx, ny, nz)
                    and grid.get(nx, ny, nz) == VOXEL_TREASURE
                ):
                    found = True
                    break
            treasure_adj[m.id] = found

        betrayers = party.check_betrayals(treasure_adj, self.rng)
        for b in betrayers:
            b.state = IntruderState.PILLAGING
            self._repath_intruder(b)
            logger.info("Intruder #%d betrayed their party for treasure!", b.id)
            self.event_bus.publish("intruder_betrayed", intruder=b)
