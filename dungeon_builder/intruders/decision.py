"""Intruder AI: party spawning, per-intruder state machine, vision, pathfinding.

This is the main integration module that ties together archetypes, parties,
personal maps, vision, personal pathfinding, and block interactions into a
tick-driven simulation.  Each tick:

1. Parties are spawned at surface edges (if the timer is ready).
2. Each party shares maps, updates morale, checks betrayals.
3. Each alive intruder updates its state machine (vision -> decision -> move).
4. Dead/escaped intruders and wiped parties are cleaned up.

Dependencies: config, core.event_bus, world.voxel_grid, world.pathfinding,
    dungeon_core.core, utils.rng, intruders.agent, intruders.archetypes,
    intruders.equipment, intruders.familiar, intruders.party,
    intruders.personal_map, intruders.personal_pathfinder,
    intruders.vision, intruders.interactions, intruders.knowledge_archive,
    intruders.reputation
Dependents: main (wiring), tests/intruders/, tests/physics/test_water.py,
    tests/ui/test_debug_spawn_buttons.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    IntruderStatus,
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.personal_pathfinder import PersonalPathfinder
from dungeon_builder.intruders.vision import (
    compute_los,
    compute_arcane_sight,
    compute_thermal_vision,
)
from dungeon_builder.intruders.interactions import (
    handle_block,
    InteractionResult,
)
from dungeon_builder.intruders.party import (
    Party,
    choose_template,
    generate_composition,
)
from dungeon_builder.intruders.equipment import (
    generate_loadout,
    ItemEffect,
)
from dungeon_builder.intruders.familiar import (
    spawn_familiars,
    update_familiar,
)
from dungeon_builder.intruders.knowledge_archive import KnowledgeArchive
from dungeon_builder.intruders.reputation import DungeonReputation
import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_WATER,
    VOXEL_TREASURE,
    VOXEL_DOOR,
    VOXEL_SPIKE,
    VOXEL_LAVA,
    VOXEL_TARP,
    VOXEL_GOLD_BAIT,
    VOXEL_PRESSURE_PLATE,
    VOXEL_FLOODGATE,
    VOXEL_ALARM_BELL,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_STEAM_VENT,
    SURFACE_Z,
    DIG_DURATION,
    NON_DIGGABLE,
    LEVEL_WEIGHTS,
    MORALE_DAMAGE_PENALTY,
    MORALE_HAZARD_PENALTY,
    MORALE_TREASURE_BONUS,
    MORALE_LOW_THRESHOLD,
    MORALE_RETREAT_MULTIPLIER,
    PRESSURE_PLATE_TRIGGER_RANGE,
    ALARM_BELL_DETECTION_RANGE,
    ALARM_BELL_COOLDOWN,
    FRAGILE_FLOOR_WEIGHT_THRESHOLD,
    WATER_DAMAGE_DEPTH_THRESHOLD,
    WATER_DAMAGE_PER_TICK,
    WATER_CURRENT_PUSH_THRESHOLD,
    SUPPLY_SAFETY_MARGIN,
    SUPPLY_COST_PER_CELL,
)

_HAZARD_TYPES = frozenset((
    VOXEL_SPIKE, VOXEL_LAVA, VOXEL_TARP,
    VOXEL_PRESSURE_PLATE, VOXEL_STEAM_VENT, VOXEL_FRAGILE_FLOOR,
))

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid
    from dungeon_builder.world.pathfinding import AStarPathfinder
    from dungeon_builder.dungeon_core.core import DungeonCore
    from dungeon_builder.utils.rng import SeededRNG

logger = logging.getLogger("dungeon_builder.intruders")


class IntruderAI:
    """Manages intruder parties, spawning, movement, and decision-making.

    Public interface (kept compatible with main.py):
    - Constructor takes (event_bus, voxel_grid, pathfinder, core, rng)
    - ``intruders`` list contains all intruder agents
    - ``spawning_enabled`` flag controls whether parties are spawned
    - Subscribes to ``tick``, ``intruder_needs_repath``, ``game_over``
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        pathfinder: AStarPathfinder,
        core: DungeonCore,
        rng: SeededRNG,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.pathfinder = pathfinder  # Global pathfinder (fallback)
        self.core = core
        self.rng = rng

        self.intruders: list[Intruder] = []
        self.parties: list[Party] = []
        self._next_id = 1
        self._next_party_id = 1
        self._next_familiar_id = 1
        self._spawn_timer = 0

        # Social dynamics systems
        self._knowledge_archive = KnowledgeArchive()
        self._reputation = DungeonReputation(event_bus)

        # Alarm bell cooldown tracking: pos -> remaining ticks
        self._alarm_cooldowns: dict[tuple[int, int, int], int] = {}

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("intruder_needs_repath", self._on_needs_repath)
        event_bus.subscribe("game_over", self._on_game_over)
        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("debug_spawn_party", self._on_debug_spawn_party)
        event_bus.subscribe("dev_mode_changed", self._on_dev_mode_changed)

        self._game_over = False
        # In normal mode, intruders spawn automatically.
        # In dev mode, they only spawn via debug buttons.
        self.spawning_enabled = not _cfg.DEV_MODE

    # -- Event handlers -------------------------------------------------

    def _on_game_over(self, **kwargs) -> None:
        self._game_over = True

    def _on_dev_mode_changed(self, **kwargs) -> None:
        self.spawning_enabled = not _cfg.DEV_MODE

    def _on_tick(self, tick: int) -> None:
        if self._game_over:
            return

        if self.spawning_enabled:
            self._tick_spawning()

        # Party-level updates
        for party in self.parties:
            if party.is_wiped:
                continue
            party.share_maps()
            party.update_morale(tick)
            self._tick_betrayals(party)

        # Alarm bell cooldown decrement
        if self._alarm_cooldowns:
            self._tick_alarm_cooldowns()

        # Per-intruder update
        for intruder in self.intruders:
            if not intruder.alive:
                continue
            self._update_intruder(intruder, tick)

        # Periodic cleanup
        if tick % 100 == 0:
            self._cleanup()

    def _on_needs_repath(self, intruder: Intruder, **kwargs) -> None:
        self._repath_intruder(intruder)

    def _on_voxel_changed(self, x: int = 0, y: int = 0, z: int = 0, **kwargs) -> None:
        """When the player modifies a cell, increase uncertainty in faction archives."""
        self._knowledge_archive.on_voxel_changed(x, y, z)

    def _on_debug_spawn_party(self, **kwargs) -> None:
        """Debug: immediately spawn a surface intruder party."""
        self.spawning_enabled = True
        self._spawn_party()

    # -- Spawning -------------------------------------------------------

    def _tick_spawning(self) -> None:
        self._spawn_timer += 1
        if self._spawn_timer < _cfg.INTRUDER_PARTY_SPAWN_INTERVAL:
            return
        self._spawn_timer = 0

        alive_count = sum(1 for i in self.intruders if i.alive)
        active_parties = sum(1 for p in self.parties if not p.is_wiped)

        if alive_count >= _cfg.MAX_INTRUDERS_TOTAL:
            return
        if active_parties >= _cfg.MAX_PARTIES:
            return

        self._spawn_party()

    def _spawn_party(self) -> None:
        """Spawn a new party at a random surface edge."""
        party_rng = self.rng.fork(f"party_{self._next_party_id}")
        template = choose_template(party_rng)
        composition = generate_composition(template, party_rng)

        # Find spawn position
        spawn_pos = self._find_spawn_position()
        if spawn_pos is None:
            logger.debug("No valid spawn position found for party")
            return

        sx, sy, sz = spawn_pos
        members: list[Intruder] = []
        loyalty_mod = self._reputation.get_loyalty_modifier()
        level_shift = self._reputation.get_level_shift()

        for arch in composition:
            obj = self._pick_objective(arch, party_rng)
            level = self._assign_level(party_rng, level_shift)
            status = self._level_to_status(level)
            pmap = PersonalMap()
            self._knowledge_archive.inject_knowledge(
                pmap, self._spawn_timer, arch.cunning,
            )

            # Generate equipment loadout
            equipment = generate_loadout(
                arch, party_rng, level, status, self._reputation,
            )

            intruder = Intruder(
                intruder_id=self._next_id,
                x=sx, y=sy, z=sz,
                archetype=arch,
                objective=obj,
                personal_map=pmap,
                equipment=equipment,
                level=level,
                status=status,
            )
            intruder.loyalty_modifier += loyalty_mod
            self._next_id += 1
            intruder.state = IntruderState.ADVANCING

            # Spawn familiars for Mole Tamers
            if arch.familiar_capacity > 0:
                familiars = spawn_familiars(intruder, self._next_familiar_id)
                intruder.familiars = familiars
                self._next_familiar_id += len(familiars)

            members.append(intruder)

        if not members:
            return

        rep_modifier = self._reputation.get_objective_modifier()
        party = Party(self._next_party_id, members)
        party._vote_objective(reputation_modifier=rep_modifier)
        self._next_party_id += 1
        self.parties.append(party)

        for m in members:
            self.intruders.append(m)
            # Initial vision scan
            self._update_vision(m)
            # Initial path
            self._repath_intruder(m)
            self.event_bus.publish("intruder_spawned", intruder=m)

        logger.info(
            "Spawned party #%d (%s) with %d members at (%d,%d,%d)",
            party.id, template.name, len(members), sx, sy, sz,
        )

    def _spawn_intruder(self) -> None:
        """Spawn a single intruder (legacy compatibility for tests)."""
        spawn_pos = self._find_spawn_position()
        if spawn_pos is None:
            logger.debug("No valid spawn position found")
            return

        sx, sy, sz = spawn_pos
        equipment = generate_loadout(
            EXPLORER, self.rng, 1, IntruderStatus.GRUNT, self._reputation,
        )
        intruder = Intruder(
            intruder_id=self._next_id,
            x=sx, y=sy, z=sz,
            archetype=EXPLORER,
            objective=IntruderObjective.DESTROY_CORE,
            personal_map=PersonalMap(),
            equipment=equipment,
        )
        self._next_id += 1

        # Find path via global pathfinder
        path = self.pathfinder.find_path(
            (intruder.x, intruder.y, intruder.z),
            (self.core.x, self.core.y, self.core.z),
        )
        if path is None:
            logger.debug("No path from spawn to core for intruder #%d", intruder.id)
            return

        intruder.path = path
        intruder.path_index = 1
        intruder.state = IntruderState.ADVANCING
        self.intruders.append(intruder)
        self.event_bus.publish("intruder_spawned", intruder=intruder)
        logger.info("Spawned intruder #%d at (%d, %d, %d)", intruder.id, sx, sy, sz)

    @staticmethod
    def _pick_objective(arch, rng) -> IntruderObjective:
        """Pick an objective weighted by archetype's objective_weights."""
        w = arch.objective_weights
        roll = rng.random()
        if roll < w[0]:
            return IntruderObjective.DESTROY_CORE
        if roll < w[0] + w[1]:
            return IntruderObjective.EXPLORE
        return IntruderObjective.PILLAGE

    def _find_spawn_position(self) -> tuple[int, int, int] | None:
        """Find an air cell above terrain at or near the map edge.

        With varying terrain, the surface might not be air at SURFACE_Z.
        Scan upward from SURFACE_Z to find the first air cell.
        """
        grid = self.voxel_grid
        edges: list[tuple[int, int, int]] = []

        def _find_air(x: int, y: int) -> tuple[int, int, int] | None:
            """Scan from SURFACE_Z upward (decreasing z) to find air."""
            for z in range(SURFACE_Z, -1, -1):
                if grid.get(x, y, z) == VOXEL_AIR:
                    return (x, y, z)
            return None

        # Try edge cells first
        for x in range(grid.width):
            for y in [0, grid.depth - 1]:
                pos = _find_air(x, y)
                if pos is not None:
                    edges.append(pos)
        for y in range(grid.depth):
            for x in [0, grid.width - 1]:
                pos = _find_air(x, y)
                if pos is not None:
                    edges.append(pos)

        # Fallback: any cell
        if not edges:
            for x in range(grid.width):
                for y in range(grid.depth):
                    pos = _find_air(x, y)
                    if pos is not None:
                        edges.append(pos)

        if not edges:
            return None
        return self.rng.choice(edges)

    # -- Per-intruder state machine -------------------------------------

    def _update_intruder(self, intruder: Intruder, tick: int = 0) -> None:
        """Main per-tick update for a single intruder."""
        # 1. Vision update
        self._update_vision(intruder)

        # 2. Water interaction (damage from deep water, current push)
        self._check_water_interaction(intruder)
        if not intruder.alive:
            return

        # 3. State-specific behavior
        state = intruder.state
        if state == IntruderState.SPAWNING:
            intruder.state = IntruderState.ADVANCING
            self._repath_intruder(intruder)
        elif state == IntruderState.ADVANCING:
            self._update_advancing(intruder, tick)
        elif state == IntruderState.INTERACTING:
            self._update_interacting(intruder)
        elif state == IntruderState.ATTACKING:
            self._update_attacking(intruder)
        elif state == IntruderState.RETREATING:
            self._update_retreating(intruder, tick)
        elif state == IntruderState.PILLAGING:
            self._update_pillaging(intruder)

        # 4. Supply consumption (every tick for all alive intruders)
        self._tick_supply_consumption(intruder)

        # 5. Equipment use (heal, consumables)
        self._tick_equipment_use(intruder)

        # 6. Familiar orchestration (Mole Tamer)
        if intruder.archetype.familiar_capacity > 0:
            self._tick_familiars(intruder, tick)

        # 7. Eidolon entertainment (stub)
        if intruder.archetype.phase_thickness > 0:
            self._tick_eidolon_entertainment(intruder)

        # 8. Hero dramatic pathing (stub)
        if intruder.archetype.dramatic:
            self._tick_dramatic(intruder)

    # -- Supply consumption ---------------------------------------------

    @staticmethod
    def _tick_supply_consumption(intruder: Intruder) -> None:
        """Deplete food and water each tick based on effective rates."""
        intruder.food -= intruder.effective_food_rate
        intruder.water -= intruder.effective_water_rate
        # Clamp to zero (cannot go negative)
        if intruder.food < 0.0:
            intruder.food = 0.0
        if intruder.water < 0.0:
            intruder.water = 0.0

    # -- Equipment use --------------------------------------------------

    @staticmethod
    def _tick_equipment_use(intruder: Intruder) -> None:
        """Use consumables intelligently each tick.

        - Heal potion when HP < 50%
        - Other equipment use based on cunning and risk_tolerance
        """
        # Heal when HP below 50%
        hp_ratio = intruder.hp / intruder.max_hp if intruder.max_hp > 0 else 1.0
        if hp_ratio < 0.5:
            heal_item = intruder.equipment.find_item(ItemEffect.HEAL)
            if heal_item is not None:
                if heal_item.use():
                    heal_amount = heal_item.template.value
                    intruder.hp = min(intruder.max_hp, intruder.hp + heal_amount)

        # Sustenance potion when food or water critically low
        if intruder.food < 1.0 or intruder.water < 1.0:
            sust_item = intruder.equipment.find_item(ItemEffect.SUSTENANCE)
            if sust_item is not None:
                if sust_item.use():
                    restore = sust_item.template.value
                    intruder.food = min(
                        intruder.archetype.food_capacity,
                        intruder.food + restore,
                    )
                    intruder.water = min(
                        intruder.archetype.water_capacity,
                        intruder.water + restore,
                    )

        # Clean up depleted items periodically
        intruder.equipment.remove_depleted()

    # -- Familiar tick --------------------------------------------------

    def _tick_familiars(self, intruder: Intruder, tick: int) -> None:
        """Update all familiars belonging to this intruder.

        Familiars follow, dig, or go unruly according to their own state
        machine (see familiar.py).  The decision engine calls
        ``update_familiar`` for each alive familiar every tick.
        """
        familiar_rng = self.rng.fork(f"familiar_{intruder.id}_{tick}")
        for familiar in intruder.familiars:
            if familiar.alive:
                update_familiar(
                    familiar, intruder, self.voxel_grid, familiar_rng,
                )

    # -- Eidolon entertainment (stub) -----------------------------------

    @staticmethod
    def _tick_eidolon_entertainment(intruder: Intruder) -> None:
        """Stub: Eidolon entertainment decay and behaviour changes.

        Future implementation will decay the entertainment meter each tick.
        Bored eidolons become destructive; entertained ones bestow gifts.
        """
        return

    # -- Hero dramatic pathing (stub) -----------------------------------

    @staticmethod
    def _tick_dramatic(intruder: Intruder) -> None:
        """Stub: Hero dramatic pathing bias.

        Future implementation will bias the Hero's pathing toward the most
        dramatic route (widest corridors, through the thick of traps).
        The predictability IS the weakness players can exploit.
        """
        return

    # -- Supply-cost estimation -----------------------------------------

    def _estimate_return_cost(self, intruder: Intruder) -> float:
        """Estimate the supply cost for this intruder to retreat to the exit.

        Uses Manhattan distance to the surface as a rough path-length proxy,
        multiplied by SUPPLY_COST_PER_CELL.
        """
        # Distance to surface exit (approximate)
        dist = abs(intruder.z - SURFACE_Z) + 5  # +5 for lateral traversal
        return dist * SUPPLY_COST_PER_CELL

    # -- Vision ---------------------------------------------------------

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

        # Standard LOS (with vision deception for certain blocks)
        visible = compute_los(grid, x, y, z, arch.perception_range)
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

    # -- Water interaction ----------------------------------------------

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

    # -- ADVANCING state ------------------------------------------------

    def _update_advancing(self, intruder: Intruder, tick: int = 0) -> None:
        # Check retreat condition
        self._check_retreat(intruder)
        if intruder.state != IntruderState.ADVANCING:
            return

        # Movement tick
        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        self._advance_along_path(intruder)

        # Check if we reached the core (within attack range)
        core_pos = (self.core.x, self.core.y, self.core.z)
        dist = (
            abs(intruder.x - core_pos[0])
            + abs(intruder.y - core_pos[1])
            + abs(intruder.z - core_pos[2])
        )
        if dist <= intruder.archetype.attack_range:
            intruder.state = IntruderState.ATTACKING
            logger.info("Intruder #%d reached attack range of core!", intruder.id)

    # -- INTERACTING state ----------------------------------------------

    def _update_interacting(self, intruder: Intruder) -> None:
        """Count down the interaction timer; complete when done."""
        intruder.interaction_ticks -= 1
        if intruder.interaction_ticks > 0:
            return

        itype = intruder.interaction_type
        target = intruder.interaction_target

        if target is None:
            intruder.state = IntruderState.ADVANCING
            return

        tx, ty, tz = target
        grid = self.voxel_grid

        if itype in ("bash_door", "lockpick"):
            # Open the door (set block_state to 0)
            if grid.get(tx, ty, tz) == VOXEL_DOOR:
                grid.set_block_state(tx, ty, tz, 0)
                intruder.personal_map.reveal(tx, ty, tz, VOXEL_DOOR, 0)
                logger.debug(
                    "Intruder #%d opened door at (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_opened_door",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )
        elif itype == "grab_treasure":
            if grid.get(tx, ty, tz) == VOXEL_TREASURE:
                grid.set(tx, ty, tz, VOXEL_AIR)
                intruder.loot_count += 1
                intruder.personal_map.remove_treasure(tx, ty, tz)
                intruder.morale = min(1.0, intruder.morale + MORALE_TREASURE_BONUS)
                logger.debug(
                    "Intruder #%d collected treasure at (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_collected_treasure",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )
        elif itype == "grab_bait":
            if grid.get(tx, ty, tz) == VOXEL_GOLD_BAIT:
                # Bait consumed
                grid.set(tx, ty, tz, VOXEL_AIR)
                # Intruder realizes they were tricked -- morale hit
                intruder.morale = max(0.0, intruder.morale - 0.1)
                intruder.personal_map.mark_bait(tx, ty, tz)
                logger.debug(
                    "Intruder #%d grabbed gold bait at (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_grabbed_bait",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )
                # Bait triggers adjacent traps (same as pressure plate)
                self._activate_pressure_plate(tx, ty, tz, intruder)

        elif itype == "dig":
            vtype = grid.get(tx, ty, tz)
            if vtype != VOXEL_AIR and vtype not in NON_DIGGABLE:
                grid.set(tx, ty, tz, VOXEL_AIR)
                intruder.personal_map.reveal(tx, ty, tz, VOXEL_AIR, 0)
                logger.debug(
                    "Intruder #%d dug through (%d,%d,%d)",
                    intruder.id, tx, ty, tz,
                )
                self.event_bus.publish(
                    "intruder_digging",
                    intruder=intruder, x=tx, y=ty, z=tz,
                )

        # Clear interaction state and resume
        intruder.interaction_type = None
        intruder.interaction_target = None
        intruder.interaction_ticks = 0

        if intruder.objective == IntruderObjective.PILLAGE:
            intruder.state = IntruderState.PILLAGING
        else:
            intruder.state = IntruderState.ADVANCING
        self._repath_intruder(intruder)

    # -- ATTACKING state ------------------------------------------------

    def _update_attacking(self, intruder: Intruder) -> None:
        intruder.ticks_since_attack += 1
        if intruder.ticks_since_attack >= intruder.attack_interval:
            intruder.ticks_since_attack = 0
            damage = intruder.effective_damage
            self.core.take_damage(damage)
            logger.debug(
                "Intruder #%d attacks core for %d damage",
                intruder.id, damage,
            )

    # -- RETREATING state -----------------------------------------------

    def _update_retreating(self, intruder: Intruder, tick: int = 0) -> None:
        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        self._advance_along_path(intruder)

        if intruder.z == SURFACE_Z:
            intruder.state = IntruderState.ESCAPED
            self._knowledge_archive.archive_survivor(intruder, tick)
            self.event_bus.publish("intruder_escaped", intruder=intruder)
            logger.info("Intruder #%d escaped to the surface!", intruder.id)

    # -- PILLAGING state ------------------------------------------------

    def _update_pillaging(self, intruder: Intruder) -> None:
        """Head toward nearest known treasure, or retreat if none left."""
        self._check_retreat(intruder)
        if intruder.state != IntruderState.PILLAGING:
            return

        intruder.ticks_since_move += 1
        if intruder.ticks_since_move < intruder.effective_move_interval:
            return
        intruder.ticks_since_move = 0

        # If no path or path exhausted, find nearest treasure
        if intruder.path is None or intruder.path_index >= len(intruder.path):
            treasures = list(intruder.personal_map.treasures)
            if not treasures:
                self._start_retreat(intruder)
                return
            nearest = min(
                treasures,
                key=lambda t: (
                    abs(t[0] - intruder.x)
                    + abs(t[1] - intruder.y)
                    + abs(t[2] - intruder.z)
                ),
            )
            path = PersonalPathfinder.find_path(
                intruder.personal_map, intruder.pos, nearest, intruder.archetype,
            )
            if path and len(path) > 1:
                intruder.path = path
                intruder.path_index = 1
            else:
                self._start_retreat(intruder)
                return

        self._advance_along_path(intruder)

    # -- Path following & block interactions -----------------------------

    def _advance_along_path(self, intruder: Intruder) -> None:
        """Move the intruder one step along its path, handling interactions."""
        if intruder.path is None:
            return
        if intruder.path_index >= len(intruder.path):
            if intruder.state == IntruderState.ADVANCING:
                self._repath_intruder(intruder)
            return

        next_pos = intruder.path[intruder.path_index]
        nx, ny, nz = next_pos
        grid = self.voxel_grid

        if not grid.in_bounds(nx, ny, nz):
            self._repath_intruder(intruder)
            return

        vtype = grid.get(nx, ny, nz)
        bstate = int(grid.block_state[nx, ny, nz])

        # Handle block interaction
        info = handle_block(intruder, vtype, bstate)

        if info.result == InteractionResult.CONTINUE:
            self._move_to(intruder, next_pos)

        elif info.result == InteractionResult.INTERACT:
            intruder.state = IntruderState.INTERACTING
            intruder.interaction_type = info.interaction_type
            intruder.interaction_target = next_pos
            intruder.interaction_ticks = info.ticks

        elif info.result == InteractionResult.DAMAGE:
            intruder.take_damage(info.damage)
            intruder.morale = max(0.0, intruder.morale - MORALE_DAMAGE_PENALTY)
            if intruder.alive:
                self._move_to(intruder, next_pos)
            else:
                self._on_intruder_death(intruder)

        elif info.result == InteractionResult.REPATH:
            if (
                intruder.archetype.can_dig
                and vtype not in NON_DIGGABLE
                and vtype != VOXEL_AIR
            ):
                self._start_digging(intruder, next_pos, vtype)
            else:
                self._repath_intruder(intruder)

        elif info.result == InteractionResult.COLLECT:
            intruder.state = IntruderState.INTERACTING
            intruder.interaction_type = info.interaction_type
            intruder.interaction_target = next_pos
            intruder.interaction_ticks = info.ticks

        elif info.result == InteractionResult.FALL:
            intruder.personal_map.mark_hazard(nx, ny, nz)
            grid.set(nx, ny, nz, VOXEL_AIR)
            self._move_to(intruder, next_pos)
            self.event_bus.publish(
                "intruder_fell", intruder=intruder, x=nx, y=ny, z=nz,
            )

        elif info.result == InteractionResult.DEATH:
            intruder.take_damage(intruder.hp)
            self._on_intruder_death(intruder)

        elif info.result == InteractionResult.DESTROY_BLOCK:
            intruder.take_damage(info.damage)
            if grid.get(nx, ny, nz) != VOXEL_AIR:
                grid.set(nx, ny, nz, VOXEL_AIR)
            if intruder.alive:
                self._move_to(intruder, next_pos)
            else:
                self._on_intruder_death(intruder)

    def _move_to(self, intruder: Intruder, pos: tuple[int, int, int]) -> None:
        """Move intruder to a new position and advance path index."""
        intruder.x, intruder.y, intruder.z = pos
        intruder.path_index += 1
        intruder._vision_dirty = True
        self.event_bus.publish("intruder_moved", intruder=intruder)

        # Post-move triggers on the cell we just stepped into
        grid = self.voxel_grid
        nx, ny, nz = pos
        if grid.in_bounds(nx, ny, nz):
            vtype = grid.get(nx, ny, nz)

            # Pressure plate activation
            if vtype == VOXEL_PRESSURE_PLATE:
                bstate = int(grid.block_state[nx, ny, nz])
                if bstate == 0:  # Not yet triggered
                    grid.set_block_state(nx, ny, nz, 1)
                    self._activate_pressure_plate(nx, ny, nz, intruder)

            # Fragile floor collapse check (flyers don't trigger)
            if vtype == VOXEL_FRAGILE_FLOOR and not intruder.archetype.can_fly:
                collapsed = self._check_fragile_floor(intruder, nx, ny, nz)
                if collapsed:
                    # Intruder falls -- check if there's air below
                    below_z = nz + 1  # z+1 = deeper
                    if (
                        grid.in_bounds(nx, ny, below_z)
                        and grid.get(nx, ny, below_z) == VOXEL_AIR
                    ):
                        intruder.z = below_z
                        intruder._vision_dirty = True
                        self.event_bus.publish(
                            "intruder_fell",
                            intruder=intruder, x=nx, y=ny, z=nz,
                        )

            # Alarm bell proximity check
            self._check_alarm_bells(intruder)

    def _move_random(self, intruder: Intruder) -> None:
        """Move the intruder to a random adjacent air cell."""
        grid = self.voxel_grid
        candidates = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = intruder.x + dx, intruder.y + dy
            nz = intruder.z
            if grid.in_bounds(nx, ny, nz) and grid.get(nx, ny, nz) == VOXEL_AIR:
                candidates.append((nx, ny, nz))
        if candidates:
            pos = self.rng.choice(candidates)
            intruder.x, intruder.y, intruder.z = pos
            intruder._vision_dirty = True
            self.event_bus.publish("intruder_moved", intruder=intruder)

    # -- Digging --------------------------------------------------------

    def _start_digging(
        self,
        intruder: Intruder,
        target: tuple[int, int, int],
        vtype: int,
    ) -> None:
        """Start digging through a solid block.

        Dig duration is halved from base (all digger archetypes dig at
        the same rate -- specialisation comes from familiar usage, not
        innate speed).
        """
        base_ticks = DIG_DURATION.get(vtype, 40)
        dig_ticks = max(1, base_ticks // 2)

        intruder.state = IntruderState.INTERACTING
        intruder.interaction_type = "dig"
        intruder.interaction_target = target
        intruder.interaction_ticks = dig_ticks
        self.event_bus.publish(
            "intruder_digging",
            intruder=intruder, x=target[0], y=target[1], z=target[2],
        )

    # -- Retreat --------------------------------------------------------

    def _check_retreat(self, intruder: Intruder) -> None:
        """Check whether an intruder should begin retreating.

        Retreat triggers (checked in order):
        1. Morale-based flee (below MORALE_FLEE_THRESHOLD)
        2. HP-based retreat (below retreat_threshold, amplified by low morale)
        3. Supply-based retreat (food or water insufficient for return trip)
        """
        arch = intruder.archetype

        # Archetypes with retreat_threshold=0.0 never retreat on HP,
        # but can still flee on morale or supplies.

        # Morale-based flee: very low morale -> abandon party
        if intruder.morale < _cfg.MORALE_FLEE_THRESHOLD:
            self._start_retreat(intruder)
            return

        # HP-based retreat
        if arch.retreat_threshold > 0:
            hp_ratio = intruder.hp / intruder.max_hp
            # Low morale doubles the retreat threshold (flee at higher HP)
            threshold = arch.retreat_threshold
            if intruder.morale < MORALE_LOW_THRESHOLD:
                threshold *= MORALE_RETREAT_MULTIPLIER

            if hp_ratio < threshold:
                self._start_retreat(intruder)
                return

        # Supply-based retreat: ensure enough food/water to get back
        return_cost = self._estimate_return_cost(intruder)
        if intruder.food < return_cost * SUPPLY_SAFETY_MARGIN:
            self._start_retreat(intruder)
            return
        if intruder.water < return_cost * SUPPLY_SAFETY_MARGIN:
            self._start_retreat(intruder)
            return

    def _start_retreat(self, intruder: Intruder) -> None:
        """Begin retreat toward the surface."""
        # Already at surface -> escape immediately
        if intruder.z == SURFACE_Z:
            intruder.state = IntruderState.RETREATING
            return
        intruder.state = IntruderState.RETREATING
        path = PersonalPathfinder.find_path(
            intruder.personal_map,
            intruder.pos,
            (intruder.x, intruder.y, SURFACE_Z),
            intruder.archetype,
        )
        if path and len(path) > 1:
            intruder.path = path
            intruder.path_index = 1
        else:
            # Fallback to global pathfinder
            path = self.pathfinder.find_path(
                intruder.pos, (intruder.x, intruder.y, SURFACE_Z),
            )
            if path and len(path) > 1:
                intruder.path = path
                intruder.path_index = 1
            else:
                intruder.state = IntruderState.ADVANCING
        logger.info("Intruder #%d retreating (HP: %d)", intruder.id, intruder.hp)

    # -- Pathing --------------------------------------------------------

    def _repath_intruder(self, intruder: Intruder) -> None:
        """Find a new path for the intruder based on its objective/state."""
        if intruder.state == IntruderState.RETREATING:
            goal = (intruder.x, intruder.y, SURFACE_Z)
        elif intruder.state == IntruderState.PILLAGING:
            treasures = list(intruder.personal_map.treasures)
            if treasures:
                goal = min(
                    treasures,
                    key=lambda t: (
                        abs(t[0] - intruder.x)
                        + abs(t[1] - intruder.y)
                        + abs(t[2] - intruder.z)
                    ),
                )
            else:
                self._start_retreat(intruder)
                return
        elif intruder.state in (IntruderState.ADVANCING, IntruderState.SPAWNING):
            goal = (self.core.x, self.core.y, self.core.z)
        else:
            return

        # Skip repathing if position, goal, and map haven't changed
        cache_key = (intruder.pos, goal, intruder.personal_map._generation)
        if (
            intruder._path_cache_key == cache_key
            and intruder.path is not None
            and intruder.path_index < len(intruder.path)
        ):
            return

        # Try personal pathfinder first
        path = PersonalPathfinder.find_path(
            intruder.personal_map, intruder.pos, goal, intruder.archetype,
        )
        if path and len(path) > 1:
            intruder.path = path
            intruder.path_index = 1
            intruder._path_cache_key = cache_key
        else:
            # Fallback to global pathfinder
            path = self.pathfinder.find_path(intruder.pos, goal)
            if path and len(path) > 1:
                intruder.path = path
                intruder.path_index = 1
                intruder._path_cache_key = cache_key
            else:
                logger.debug(
                    "Intruder #%d cannot find path from %s to %s",
                    intruder.id, intruder.pos, goal,
                )
                intruder.path = None
                intruder._path_cache_key = None

    # -- Pressure plate activation --------------------------------------

    def _activate_pressure_plate(
        self, x: int, y: int, z: int, intruder: Intruder,
    ) -> None:
        """Activate a pressure plate and trigger adjacent traps.

        Within PRESSURE_PLATE_TRIGGER_RANGE, activates:
        - Spikes: set block_state = 1 (extended)
        - Doors: set block_state = 1 (closed)
        - Floodgates: toggle block_state (open<->closed)
        """
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
                    elif vtype == VOXEL_DOOR:
                        grid.set_block_state(nx, ny, nz, 1)  # Close
                    elif vtype == VOXEL_FLOODGATE:
                        # Toggle: open->closed, closed->open
                        old = int(grid.block_state[nx, ny, nz])
                        grid.set_block_state(nx, ny, nz, 1 - old)
        self.event_bus.publish(
            "pressure_plate_activated",
            intruder=intruder, x=x, y=y, z=z,
        )

    # -- Fragile floor collapse -----------------------------------------

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

    # -- Alarm bell detection -------------------------------------------

    def _check_alarm_bells(self, intruder: Intruder) -> None:
        """Check if intruder is within range of any alarm bell.

        Alarm bells detect intruders within ALARM_BELL_DETECTION_RANGE
        (Manhattan distance) and publish an alarm event. Each bell has a
        cooldown (tracked in ``_alarm_cooldowns``) to prevent spam.
        """
        grid = self.voxel_grid
        ix, iy, iz = intruder.x, intruder.y, intruder.z
        r = ALARM_BELL_DETECTION_RANGE

        # Scan the area around the intruder for alarm bells
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if abs(dx) + abs(dy) + abs(dz) > r:
                        continue
                    bx, by, bz = ix + dx, iy + dy, iz + dz
                    if not grid.in_bounds(bx, by, bz):
                        continue
                    if grid.get(bx, by, bz) != VOXEL_ALARM_BELL:
                        continue
                    bell_pos = (bx, by, bz)
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

    # -- Betrayal -------------------------------------------------------

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

    # -- Death handling -------------------------------------------------

    def _on_intruder_death(self, intruder: Intruder) -> None:
        """Handle intruder death: notify party, publish event."""
        intruder.state = IntruderState.DEAD
        self.event_bus.publish("intruder_died", intruder=intruder)
        logger.info(
            "Intruder #%d (%s) died", intruder.id, intruder.archetype.name,
        )

        # Notify party
        for party in self.parties:
            if any(m.id == intruder.id for m in party.members):
                party.on_member_death(intruder)
                break

    # -- Cleanup --------------------------------------------------------

    def _cleanup(self) -> None:
        """Remove dead/escaped intruders and wiped parties."""
        self.intruders = [i for i in self.intruders if i.alive]

        # Detect party wipes before removing them
        for party in self.parties:
            if party.is_wiped and all(
                m.state == IntruderState.DEAD for m in party.members
            ):
                self._reputation.on_party_wiped()

        self.parties = [p for p in self.parties if not p.is_wiped]

    # -- Level & status assignment --------------------------------------

    @staticmethod
    def _assign_level(rng, level_shift: float = 0.0) -> int:
        """Assign a level 1-5 using weighted random, shifted by reputation.

        *level_shift* moves probability from level 1 toward higher levels.
        """
        weights = list(LEVEL_WEIGHTS)
        if level_shift > 0.0:
            shift = min(level_shift, weights[0] * 0.8)
            weights[0] -= shift
            # Distribute shift evenly across levels 2-5
            per_level = shift / 4
            for i in range(1, 5):
                weights[i] += per_level
        roll = rng.random()
        cumulative = 0.0
        for i, w in enumerate(weights):
            cumulative += w
            if roll < cumulative:
                return i + 1
        return 5

    @staticmethod
    def _level_to_status(level: int) -> IntruderStatus:
        """Convert intruder level to IntruderStatus."""
        if level <= 2:
            return IntruderStatus.GRUNT
        if level == 3:
            return IntruderStatus.VETERAN
        if level == 4:
            return IntruderStatus.ELITE
        return IntruderStatus.CHAMPION
