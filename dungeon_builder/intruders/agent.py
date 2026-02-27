"""Individual intruder data model and state machine.

Dependencies: config, intruders.archetypes, intruders.equipment,
    intruders.familiar, intruders.personal_map
Dependents: core.save_system, intruders.decision, intruders.interactions,
    intruders.knowledge_archive, intruders.party, intruders.familiar,
    rendering.intruder_renderer, tests/intruders/,
    tests/physics/test_water.py, tests/core/test_save_system.py,
    tests/rendering/test_intruder_renderer.py,
    tests/building/test_pressure_plate_chain.py,
    tests/benchmarks/benchmark_performance.py
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    MORALE_LOW_THRESHOLD,
    MORALE_HIGH_THRESHOLD,
    MORALE_SLOW_FACTOR,
    MORALE_FAST_FACTOR,
    MORALE_DAMAGE_BONUS,
)

if TYPE_CHECKING:
    from dungeon_builder.intruders.archetypes import ArchetypeStats, IntruderObjective, IntruderStatus
    from dungeon_builder.intruders.equipment import Equipment, ItemEffect
    from dungeon_builder.intruders.familiar import Familiar
    from dungeon_builder.intruders.personal_map import PersonalMap


class IntruderState(Enum):
    SPAWNING = auto()
    ADVANCING = auto()       # Moving toward current objective target
    INTERACTING = auto()     # Handling a block interaction (bash, dig, etc.)
    ATTACKING = auto()       # At core, dealing damage
    RETREATING = auto()      # Low HP / objective complete, heading to surface
    PILLAGING = auto()       # Heading to / collecting treasure
    DEAD = auto()
    ESCAPED = auto()         # Reached surface while retreating


class Intruder:
    """A single intruder agent inside the dungeon.

    Each intruder is defined by its *archetype* (shared, immutable stats)
    plus per-instance mutable state (position, HP, equipment, personal
    map, food/water supplies, etc.).
    """

    __slots__ = (
        # Identity
        "id",
        "archetype",
        # Position
        "x", "y", "z",
        # Combat
        "hp", "max_hp",
        "shield_hp",
        # State machine
        "state",
        "objective",
        # Path following
        "path", "path_index",
        # Movement timing
        "ticks_since_move", "move_interval",
        # Attack timing
        "ticks_since_attack", "attack_interval",
        # Fog of war
        "personal_map",
        # Party
        "party_id",
        "loyalty_modifier",
        # Interaction state
        "interaction_type",
        "interaction_target",
        "interaction_ticks",
        # Loot
        "loot_count",
        # Tunneling progress: maps (x,y,z) -> ticks spent digging
        "dig_progress",
        # Vision cache: True when intruder has moved and needs re-scan
        "_vision_dirty",
        # Path cache: (start, goal, map_generation) -> avoids repathing
        "_path_cache_key",
        # Social dynamics
        "level",
        "status",
        "morale",
        # Equipment (fixed at spawn, only depleted)
        "equipment",
        # Familiars (Mole Tamer only)
        "familiars",
        # Supplies (constantly deplete)
        "food",
        "water",
        # Exploration data (all intruders, degree varies by archetype)
        "maps_collected",
        # Eidolon entertainment meter (stub)
        "entertainment",
    )

    def __init__(
        self,
        intruder_id: int,
        x: int,
        y: int,
        z: int,
        archetype: ArchetypeStats,
        objective: IntruderObjective,
        personal_map: PersonalMap,
        equipment: Equipment | None = None,
        party_id: int | None = None,
        level: int = 1,
        status: IntruderStatus | None = None,
    ) -> None:
        from dungeon_builder.intruders.archetypes import IntruderStatus as _IS

        self.id = intruder_id
        self.archetype = archetype

        self.x = x
        self.y = y
        self.z = z

        # Level stat scaling (applied to mutable instance fields, not frozen archetype)
        self.level: int = level
        self.status: IntruderStatus = status if status is not None else _IS.GRUNT
        hp_mult = 1.0 + (level - 1) * _cfg.LEVEL_HP_SCALE
        self.hp = int(archetype.hp * hp_mult)
        self.max_hp = self.hp
        self.shield_hp: int = 0

        self.state = IntruderState.SPAWNING
        self.objective = objective

        self.path: list[tuple[int, int, int]] | None = None
        self.path_index: int = 0

        self.ticks_since_move: int = 0
        self.move_interval: int = archetype.move_interval
        self.ticks_since_attack: int = 0
        self.attack_interval: int = archetype.attack_interval

        self.personal_map = personal_map
        self.party_id = party_id
        self.loyalty_modifier: float = 0.0

        self.interaction_type: str | None = None
        self.interaction_target: tuple[int, int, int] | None = None
        self.interaction_ticks: int = 0

        self.loot_count: int = 0
        self.dig_progress: dict[tuple[int, int, int], int] = {}
        self._vision_dirty: bool = True
        self._path_cache_key: tuple | None = None
        self.morale: float = _cfg.MORALE_BASE

        # Equipment
        if equipment is not None:
            self.equipment: Equipment = equipment
        else:
            from dungeon_builder.intruders.equipment import Equipment as _Eq
            self.equipment = _Eq(archetype.base_inventory_slots)

        # Initialize shield HP from equipped shield gear
        from dungeon_builder.intruders.equipment import ItemEffect as _IE
        self.shield_hp = self.equipment.get_passive_value(_IE.SHIELD)

        # Familiars (empty list for non-Mole-Tamers)
        self.familiars: list[Familiar] = []

        # Supplies
        self.food: float = archetype.food_capacity
        self.water: float = archetype.water_capacity

        # Exploration tracking
        self.maps_collected: int = 0

        # Eidolon entertainment (stub)
        self.entertainment: float = 1.0

    # ── Convenience properties ──────────────────────────────────────

    @property
    def pos(self) -> tuple[int, int, int]:
        return (self.x, self.y, self.z)

    @property
    def alive(self) -> bool:
        return self.state not in (IntruderState.DEAD, IntruderState.ESCAPED)

    @property
    def effective_loyalty(self) -> float:
        return min(1.0, max(0.0, self.archetype.loyalty + self.loyalty_modifier))

    @property
    def effective_speed(self) -> int:
        return self.archetype.speed

    @property
    def effective_damage(self) -> int:
        # Level scaling applied to base archetype damage
        damage_mult = 1.0 + (self.level - 1) * _cfg.LEVEL_DAMAGE_SCALE
        base = int(self.archetype.damage * damage_mult)
        # Equipment damage boost
        from dungeon_builder.intruders.equipment import ItemEffect as _IE
        gear_bonus = self.equipment.get_passive_value(_IE.DAMAGE_BOOST)
        base += gear_bonus
        # Morale bonus
        if self.morale > MORALE_HIGH_THRESHOLD:
            base = int(base * MORALE_DAMAGE_BONUS)
        return base

    @property
    def effective_move_interval(self) -> int:
        base = self.move_interval
        if self.morale < MORALE_LOW_THRESHOLD:
            base = int(base * MORALE_SLOW_FACTOR)
        elif self.morale > MORALE_HIGH_THRESHOLD:
            base = max(1, int(base * MORALE_FAST_FACTOR))
        return max(1, base)

    @property
    def has_fire_immunity(self) -> bool:
        """True if any carried equipment provides fire immunity."""
        from dungeon_builder.intruders.equipment import ItemEffect as _IE
        return self.equipment.has_effect(_IE.FIRE_IMMUNITY)

    @property
    def has_water_breathing(self) -> bool:
        """True if any carried equipment provides water breathing."""
        from dungeon_builder.intruders.equipment import ItemEffect as _IE
        return self.equipment.has_effect(_IE.WATER_BREATHING)

    @property
    def effective_perception(self) -> int:
        """Perception range including equipment bonuses (torch ILLUMINATE).

        Darkvision is NOT included here — it depends on position, so the
        decision engine applies it separately in ``_update_vision``.
        """
        base = self.archetype.perception_range
        from dungeon_builder.intruders.equipment import ItemEffect as _IE
        torch = self.equipment.find_item(_IE.ILLUMINATE)
        if torch is not None and not torch.depleted:
            base += torch.template.value
        return base

    @property
    def effective_food_rate(self) -> float:
        """Food consumed per tick, accounting for supply efficiency and sustenance."""
        return self.archetype.food_rate * self.archetype.supply_efficiency

    @property
    def effective_water_rate(self) -> float:
        """Water consumed per tick, accounting for supply efficiency."""
        return self.archetype.water_rate * self.archetype.supply_efficiency

    # ── Damage ──────────────────────────────────────────────────────

    def take_damage(self, amount: int) -> None:
        """Apply damage.  Shield HP absorbs first, then HP.  Clamps to 0."""
        if self.shield_hp > 0:
            absorbed = min(self.shield_hp, amount)
            self.shield_hp -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.state = IntruderState.DEAD

    def __repr__(self) -> str:
        return (
            f"Intruder(id={self.id}, {self.archetype.name}, "
            f"L{self.level} {self.status.name}, "
            f"pos=({self.x},{self.y},{self.z}), "
            f"hp={self.hp}/{self.max_hp}, morale={self.morale:.2f}, "
            f"food={self.food:.1f}, water={self.water:.1f}, "
            f"state={self.state.name})"
        )
