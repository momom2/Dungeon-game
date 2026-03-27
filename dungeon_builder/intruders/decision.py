"""Intruder AI: party spawning, per-intruder state machine, vision, pathfinding.

This is the main integration module that ties together archetypes, parties,
personal maps, vision, personal pathfinding, and block interactions into a
tick-driven simulation.  Each tick:

1. Parties are spawned at surface edges (if the timer is ready).
2. Each party shares maps, updates morale, checks betrayals.
3. Each alive intruder updates its state machine (vision -> decision -> move).
4. Dead/escaped intruders and wiped parties are cleaned up.

Method implementations are split across three mixins to keep this file
under ~600 lines:
  - SpawningMixin (intruders.spawning): party creation, level assignment
  - StateHandlersMixin (intruders.state_handlers): per-state updates, movement
  - HazardResponseMixin (intruders.hazard_response): vision, water, traps

Dependencies: config, core.event_bus, world.voxel_grid, world.pathfinding,
    dungeon_core.core, utils.rng, intruders.agent, intruders.archetypes,
    intruders.equipment, intruders.familiar, intruders.sprite, intruders.party,
    intruders.personal_map, intruders.personal_pathfinder,
    intruders.vision, intruders.interactions, intruders.knowledge_archive,
    intruders.reputation, intruders.scroll_ai, intruders.spawning,
    intruders.state_handlers, intruders.hazard_response
Dependents: main (wiring), tests/intruders/, tests/physics/test_water.py,
    tests/ui/test_debug_spawn_buttons.py,
    tests/building/test_pressure_plate_chain.py,
    tests/benchmarks/benchmark_performance.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    IntruderStatus,
    EXPLORER,
)
from dungeon_builder.intruders.equipment import ItemEffect
from dungeon_builder.intruders.familiar import (
    update_familiar, order_dig, recall_familiar, FamiliarState,
)
from dungeon_builder.intruders.sprite import (
    Sprite, SpriteState, spawn_sprites, update_sprite, order_burst,
)
from dungeon_builder.intruders.party import Party
from dungeon_builder.intruders.knowledge_archive import KnowledgeArchive
from dungeon_builder.intruders.reputation import DungeonReputation
from dungeon_builder.intruders.spawning import SpawningMixin
from dungeon_builder.intruders.state_handlers import StateHandlersMixin
from dungeon_builder.intruders.hazard_response import HazardResponseMixin
from dungeon_builder.intruders.scroll_ai import tick_scroll_use
import dungeon_builder.config as _cfg

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.dungeon_core.mana import ManaSystem
    from dungeon_builder.world.voxel_grid import VoxelGrid
    from dungeon_builder.world.pathfinding import AStarPathfinder
    from dungeon_builder.dungeon_core.core import DungeonCore
    from dungeon_builder.utils.rng import SeededRNG

logger = logging.getLogger("dungeon_builder.intruders")


class IntruderAI(SpawningMixin, StateHandlersMixin, HazardResponseMixin):
    """Manages intruder parties, spawning, movement, and decision-making.

    Public interface (kept compatible with main.py):
    - Constructor takes (event_bus, voxel_grid, pathfinder, core, rng)
    - ``intruders`` list contains all intruder agents
    - ``spawning_enabled`` flag controls whether parties are spawned
    - Subscribes to ``tick``, ``intruder_needs_repath``, ``game_over``

    Method implementations are split across three mixins:
    - SpawningMixin: party/intruder spawning, level assignment
    - StateHandlersMixin: per-state updates, movement, retreat, pathing
    - HazardResponseMixin: vision, water, pressure plates, alarm bells
    """

    def __init__(
        self,
        event_bus: EventBus,
        voxel_grid: VoxelGrid,
        pathfinder: AStarPathfinder,
        core: DungeonCore,
        rng: SeededRNG,
        mana_system: ManaSystem | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.voxel_grid = voxel_grid
        self.pathfinder = pathfinder  # Global pathfinder (fallback)
        self.core = core
        self.rng = rng
        self._mana_system = mana_system

        self.intruders: list[Intruder] = []
        self.parties: list[Party] = []
        self._party_by_id: dict[int, Party] = {}
        self._next_id = 1
        self._next_party_id = 1
        self._next_familiar_id = 1
        self._next_sprite_id = 1
        self._spawn_timer = 0

        # Social dynamics systems
        self._knowledge_archive = KnowledgeArchive()
        self._reputation = DungeonReputation(event_bus)

        # Alarm bell cooldown tracking: pos -> remaining ticks
        self._alarm_cooldowns: dict[tuple[int, int, int], int] = {}
        # Spatial index of alarm bell positions for O(bells) detection
        self._alarm_bell_positions: set[tuple[int, int, int]] = set()
        # Mana power flag — when False, magical traps are deactivated
        self._traps_powered: bool = True

        event_bus.subscribe("tick", self._on_tick)
        event_bus.subscribe("mana_power_changed", self._on_mana_power_changed)
        event_bus.subscribe("intruder_needs_repath", self._on_needs_repath)
        event_bus.subscribe("game_over", self._on_game_over)
        event_bus.subscribe("voxel_changed", self._on_voxel_changed)
        event_bus.subscribe("debug_spawn_party", self._on_debug_spawn_party)
        event_bus.subscribe("debug_spawn_single", self._on_debug_spawn_single)
        event_bus.subscribe("debug_kill_all", self._on_debug_kill_all)
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

    def _on_mana_power_changed(self, traps_powered: bool, **kw) -> None:
        self._traps_powered = traps_powered

    def _is_trap_powered_at(self, x: int, y: int, z: int) -> bool:
        """Check if a trap at (x, y, z) is powered.

        Powered globally (all traps active) OR locally via block
        capacitance (individual block has stored mana).
        """
        if self._traps_powered:
            return True
        if self._mana_system is not None:
            return self._mana_system.is_block_powered(x, y, z)
        return False

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
        """When the player modifies a cell, update knowledge and alarm bell index."""
        self._knowledge_archive.on_voxel_changed(x, y, z)
        # Update alarm bell spatial index
        pos = (x, y, z)
        if self.voxel_grid.in_bounds(x, y, z):
            from dungeon_builder.config import VOXEL_ALARM_BELL
            if self.voxel_grid.get(x, y, z) == VOXEL_ALARM_BELL:
                self._alarm_bell_positions.add(pos)
            else:
                self._alarm_bell_positions.discard(pos)

    def _on_debug_spawn_party(self, **kwargs) -> None:
        """Debug: immediately spawn a surface intruder party."""
        self.spawning_enabled = True
        self._spawn_party()

    def _on_debug_spawn_single(self, **kwargs) -> None:
        """Debug: spawn a single explorer intruder."""
        self._spawn_intruder()

    def _on_debug_kill_all(self, **kwargs) -> None:
        """Debug: kill all alive intruders."""
        for intruder in self.intruders:
            if intruder.alive:
                self._on_intruder_death(intruder)
        self._cleanup()

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

        # Guard: state processing (step 3) may have killed the intruder
        if not intruder.alive:
            return

        # 4. Supply consumption (every tick for all alive intruders)
        self._tick_supply_consumption(intruder)

        # 5. Equipment use (heal, consumables)
        self._tick_equipment_use(intruder)

        # 6. Familiar orchestration (Mole Tamer)
        if intruder.archetype.familiar_capacity > 0:
            self._tick_familiars(intruder, tick)

        # 7. Eidolon entertainment
        if intruder.archetype.phase_thickness > 0:
            self._tick_eidolon_entertainment(intruder, tick)

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

    def _tick_equipment_use(self, intruder: Intruder) -> None:
        """Use consumables intelligently each tick.

        - Heal potion when HP < 50%
        - Sustenance potion when food/water critically low
        - Scroll usage (Shield > Teleport > Dispel > Reveal > Bridge)
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

        # Scroll usage AI
        tick_scroll_use(intruder, self.voxel_grid, self.event_bus)

        # Clean up depleted items periodically
        intruder.equipment.remove_depleted()

    # -- Familiar tick --------------------------------------------------

    def _tick_familiars(self, intruder: Intruder, tick: int) -> None:
        """Update all familiars and issue commands for Mole Tamers.

        Each tick:
        1. Update each alive familiar's state machine.
        2. Every ``TAMER_COMMAND_INTERVAL`` ticks, evaluate dig/recall orders
           and repath the tamer (familiars may have cleared new passages).
        """
        familiar_rng = self.rng.fork(f"familiar_{intruder.id}_{tick}")
        for familiar in intruder.familiars:
            if familiar.alive:
                update_familiar(
                    familiar, intruder, self.voxel_grid, familiar_rng,
                    event_bus=self.event_bus,
                )

        # Command decisions (throttled)
        if tick % _cfg.TAMER_COMMAND_INTERVAL == 0:
            self._command_familiars(intruder)
            # Repath — familiars may have opened new corridors
            self._repath_intruder(intruder)

    def _command_familiars(self, intruder: Intruder) -> None:
        """Issue dig/recall commands based on the tamer's pathfinding needs.

        Strategy:
        - Recall familiars that have drifted too far from the tamer.
        - Find blocks on the tamer's upcoming path that need digging.
        - Assign available (FOLLOWING) familiars to those targets.
        """
        # Recall distant familiars first
        for f in intruder.familiars:
            if f.alive and f.state == FamiliarState.DIGGING:
                dist = (
                    abs(f.x - intruder.x)
                    + abs(f.y - intruder.y)
                    + abs(f.z - intruder.z)
                )
                if dist > _cfg.TAMER_MAX_FAMILIAR_DISTANCE:
                    recall_familiar(f)

        available = [
            f for f in intruder.familiars
            if f.alive and f.state == FamiliarState.FOLLOWING
        ]
        if not available:
            return

        # Find dig targets
        dig_targets = self._find_tamer_dig_targets(intruder)

        # Filter out targets already assigned to other familiars
        busy_targets = {
            f.dig_target
            for f in intruder.familiars
            if f.alive and f.state == FamiliarState.DIGGING and f.dig_target
        }
        new_targets = [t for t in dig_targets if t not in busy_targets]

        # Assign familiars to targets (one-to-one)
        for familiar, target in zip(available, new_targets):
            order_dig(familiar, target)

    def _find_tamer_dig_targets(
        self, intruder: Intruder,
    ) -> list[tuple[int, int, int]]:
        """Identify solid diggable blocks the tamer needs cleared.

        Two strategies:
        1. Scan ahead on the current path for solid blocks.
        2. If pathless, search adjacent cells toward the objective.
        """
        targets: list[tuple[int, int, int]] = []
        grid = self.voxel_grid

        # Strategy 1: Path lookahead
        if intruder.path is not None and intruder.path_index < len(intruder.path):
            end = min(
                intruder.path_index + _cfg.TAMER_DIG_LOOKAHEAD,
                len(intruder.path),
            )
            for i in range(intruder.path_index, end):
                px, py, pz = intruder.path[i]
                if grid.in_bounds(px, py, pz):
                    vtype = grid.get(px, py, pz)
                    if vtype != _cfg.VOXEL_AIR and vtype not in _cfg.NON_DIGGABLE:
                        targets.append((px, py, pz))

        # Strategy 2: If no path targets, find adjacent diggable blocks
        # toward the objective
        if not targets:
            goal = (self.core.x, self.core.y, self.core.z)
            ix, iy, iz = intruder.x, intruder.y, intruder.z
            candidates: list[tuple[int, tuple[int, int, int]]] = []
            for dx, dy, dz in (
                (1, 0, 0), (-1, 0, 0),
                (0, 1, 0), (0, -1, 0),
                (0, 0, 1), (0, 0, -1),
            ):
                nx, ny, nz = ix + dx, iy + dy, iz + dz
                if not grid.in_bounds(nx, ny, nz):
                    continue
                vtype = grid.get(nx, ny, nz)
                if vtype != _cfg.VOXEL_AIR and vtype not in _cfg.NON_DIGGABLE:
                    dist_to_goal = (
                        abs(nx - goal[0])
                        + abs(ny - goal[1])
                        + abs(nz - goal[2])
                    )
                    candidates.append((dist_to_goal, (nx, ny, nz)))
            candidates.sort()
            targets = [pos for _, pos in candidates]

        return targets

    # -- Eidolon entertainment -------------------------------------------

    def _tick_eidolon_entertainment(self, intruder: Intruder, tick: int) -> None:
        """Eidolon entertainment decay, sprite management, and boredom response.

        Each tick:
        1. Decay entertainment by ``EIDOLON_ENTERTAINMENT_DECAY``.
        2. Summon sprites when: no alive sprites, cooldown expired,
           entertainment is above boredom threshold.
        3. Update each alive sprite's state machine.
        4. Trigger boredom response when entertainment drops below threshold.
        5. Clean up dead/dissipated sprites.
        """
        # 1. Decay entertainment
        intruder.entertainment = max(
            0.0,
            intruder.entertainment - _cfg.EIDOLON_ENTERTAINMENT_DECAY,
        )

        # 2. Summon sprites when none alive and cooldown expired
        if intruder.sprite_summon_cooldown > 0:
            intruder.sprite_summon_cooldown -= 1

        alive_sprites = [s for s in intruder.sprites if s.alive]
        if (
            not alive_sprites
            and intruder.sprite_summon_cooldown <= 0
            and intruder.entertainment >= _cfg.EIDOLON_BOREDOM_THRESHOLD
        ):
            new_sprites = spawn_sprites(intruder, self._next_sprite_id)
            self._next_sprite_id += len(new_sprites)
            intruder.sprites.extend(new_sprites)
            intruder.sprite_summon_cooldown = _cfg.SPRITE_SUMMON_COOLDOWN
            alive_sprites = new_sprites

        # 3. Update each alive sprite
        sprite_rng = self.rng.fork(f"sprite_{intruder.id}_{tick}")
        for sprite in alive_sprites:
            update_sprite(
                sprite, intruder, self.voxel_grid, sprite_rng,
                event_bus=self.event_bus,
                mana_system=self._mana_system,
            )

        # 4. Boredom response
        if intruder.entertainment < _cfg.EIDOLON_BOREDOM_THRESHOLD:
            self._eidolon_boredom_response(intruder)

        # 5. Clean up dead/dissipated sprites
        intruder.sprites = [s for s in intruder.sprites if s.alive]

    def _eidolon_boredom_response(self, intruder: Intruder) -> None:
        """Order alive sprites to burst, unless it would harm the partner.

        Eidolons always come in pairs (EIDOLON_PAIR party).  A sprite is
        only ordered to burst if its partner is either absent or far
        enough away (``SPRITE_PARTNER_SAFE_DISTANCE``).
        """
        partner = self._find_eidolon_partner(intruder)

        for sprite in intruder.sprites:
            if not sprite.alive or sprite.state == SpriteState.BURSTING:
                continue
            # Safety check: don't burst near partner
            if partner is not None and partner.alive:
                dist = (
                    abs(sprite.x - partner.x)
                    + abs(sprite.y - partner.y)
                    + abs(sprite.z - partner.z)
                )
                if dist < _cfg.SPRITE_PARTNER_SAFE_DISTANCE:
                    continue
            order_burst(sprite)

    def _find_eidolon_partner(self, intruder: Intruder) -> Intruder | None:
        """Find the other alive member in this eidolon's party.

        Returns None if no partner is found (solo, partner dead, or no
        matching party).  Uses ``_party_by_id`` for O(1) party lookup.
        """
        if intruder.party_id is None:
            return None
        party = self._get_party(intruder.party_id)
        if party is None:
            return None
        for member in party.members:
            if member.id != intruder.id and member.alive:
                return member
        return None

    def _get_party(self, party_id: int) -> Party | None:
        """Look up a party by ID.  O(1) via index, linear fallback."""
        party = self._party_by_id.get(party_id)
        if party is not None:
            return party
        # Fallback: scan (handles test setups that bypass _spawn_party)
        for p in self.parties:
            if p.id == party_id:
                self._party_by_id[party_id] = p  # Cache for next time
                return p
        return None

    # -- Hero dramatic pathing (stub) -----------------------------------

    @staticmethod
    def _tick_dramatic(intruder: Intruder) -> None:
        """Stub: Hero dramatic pathing bias.

        Future implementation will bias the Hero's pathing toward the most
        dramatic route (widest corridors, through the thick of traps).
        The predictability IS the weakness players can exploit.
        """
        return

    # -- Death handling -------------------------------------------------

    def _on_intruder_death(self, intruder: Intruder) -> None:
        """Handle intruder death: notify party, publish event."""
        intruder.state = IntruderState.DEAD
        self.event_bus.publish("intruder_died", intruder=intruder)
        logger.info(
            "Intruder #%d (%s) died", intruder.id, intruder.archetype.name,
        )

        # Notify party
        if intruder.party_id is not None:
            party = self._get_party(intruder.party_id)
            if party is not None:
                party.on_member_death(intruder)

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
                self._party_by_id.pop(party.id, None)

        self.parties = [p for p in self.parties if not p.is_wiped]
