"""Intruder archetype definitions — 8 distinct adventurer types.

Each archetype is a frozen dataclass defining the base stats, innate
abilities, behavioral parameters, and supply needs for one category of
intruder.  Archetype-specific *powers* are expressed through stat fields
(``phase_thickness``, ``familiar_capacity``, ``dramatic``), not a
separate ability enum.  Everything else — healing, shielding,
illumination — is equipment-driven and available to any intruder that
carries the right items.

Dependencies: (none — standalone)
Dependents: core.save_system, intruders.agent, intruders.decision,
    intruders.equipment, intruders.knowledge_archive, intruders.party,
    intruders.personal_pathfinder, tests/intruders/
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class IntruderObjective(Enum):
    """High-level goal an intruder is pursuing."""

    DESTROY_CORE = auto()
    EXPLORE = auto()
    PILLAGE = auto()


class IntruderStatus(Enum):
    """Rank/status of an intruder, determines leadership priority and intel trust."""

    GRUNT = auto()       # Rank 0 — expendable, intel trust weight 0.5
    VETERAN = auto()     # Rank 1 — experienced, trust weight 1.0
    ELITE = auto()       # Rank 2 — seasoned, trust weight 1.5
    CHAMPION = auto()    # Rank 3 — exceptional, trust weight 2.0


# Trust weight per status (how much faction trusts this intruder's intel)
STATUS_TRUST: dict[IntruderStatus, float] = {
    IntruderStatus.GRUNT: 0.5,
    IntruderStatus.VETERAN: 1.0,
    IntruderStatus.ELITE: 1.5,
    IntruderStatus.CHAMPION: 2.0,
}


@dataclass(frozen=True)
class ArchetypeStats:
    """Immutable stat block shared by all intruders of one archetype.

    Instances are module-level constants (e.g. ``EXPLORER``, ``HERO``).
    Individual :class:`Intruder` objects hold a *reference* to their
    archetype so there is zero per-intruder duplication.

    **Design philosophy:** Innate supernatural traits are expressed as
    stat fields (``phase_thickness``, ``familiar_capacity``, ``dramatic``).
    Everything else — fire immunity, healing, shielding, illumination —
    is equipment-driven.  Any intruder *can* use any item; archetypes
    differ in the *quantity and selection* of equipment they bring.
    """

    name: str

    # ── Combat ────────────────────────────────────────────────────────
    hp: int
    speed: int              # 1-4 (higher = faster)
    damage: int
    attack_interval: int    # ticks between core attacks
    attack_range: int       # 1 = melee, >1 = ranged

    # ── Perception ────────────────────────────────────────────────────
    perception_range: int     # LOS radius in cells
    darkvision_range: int     # extra range in dark (future-proof)
    arcane_sight_range: int   # see-through-walls range (Gloomwarden innate)
    trap_detect_range: int    # detect traps N cells away

    # ── Movement ──────────────────────────────────────────────────────
    move_interval: int        # ticks between moves

    # ── Behavioral parameters ─────────────────────────────────────────
    retreat_threshold: float    # HP fraction to trigger retreat (0.0 = never)
    greed: float                # 0-1, probability of betrayal for treasure
    loyalty: float              # 0-1, resistance to leaving party
    cunning: float              # 0-1, hazard avoidance intelligence
    exploration_drive: float    # 0-1, how much this archetype prioritises mapping
    risk_tolerance: float       # 0-1, willingness to push deeper despite danger
    map_memory: float           # 0-1, quality of map data retained for knowledge
    supply_efficiency: float    # multiplier on supply consumption (1.0 = normal)

    # ── Traversal flags ───────────────────────────────────────────────
    can_fly: bool
    can_dig: bool
    can_bash_door: bool
    can_lockpick: bool

    # ── Innate supernatural traits ────────────────────────────────────
    # These are rare, reserved for truly supernatural or species-specific
    # powers that are always present and cannot be gained via equipment.
    phase_thickness: int    # max wall thickness to phase through (0 = none)
    familiar_capacity: int  # max familiars controlled (0 = none)
    dramatic: bool          # supernatural luck + narrative binding (Hero)

    # ── Supply capacity ───────────────────────────────────────────────
    food_capacity: float    # max food at spawn
    water_capacity: float   # max water at spawn
    food_rate: float        # food consumed per tick (before supply_efficiency)
    water_rate: float       # water consumed per tick (before supply_efficiency)

    # ── Equipment ─────────────────────────────────────────────────────
    base_inventory_slots: int  # consumable carrying capacity (before containers)
    base_gear_loadout: str     # key into loadout tables for spawn-time selection

    # ── Objective weights (destroy_core, explore, pillage) ────────────
    objective_weights: tuple[float, float, float]


# ── Archetype instances ─────────────────────────────────────────────

EXPLORER = ArchetypeStats(
    name="Explorer",
    # Scout / map-seller.  Fast, fragile, greedy for loot and intel.
    # Anyone can sell maps — explorers are distinguished by how much
    # risk they take for mapping and how much data they gather.
    hp=35, speed=3, damage=3,
    attack_interval=20, attack_range=1,
    perception_range=6, darkvision_range=1,
    arcane_sight_range=0, trap_detect_range=2,
    move_interval=3,
    retreat_threshold=0.35, greed=0.7, loyalty=0.2, cunning=0.7,
    exploration_drive=0.9, risk_tolerance=0.3,
    map_memory=0.9, supply_efficiency=0.8,
    can_fly=False, can_dig=False, can_bash_door=False, can_lockpick=True,
    phase_thickness=0, familiar_capacity=0, dramatic=False,
    food_capacity=6.0, water_capacity=5.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=3, base_gear_loadout="explorer",
    objective_weights=(0.1, 0.5, 0.4),
)

INQUISITOR = ArchetypeStats(
    name="Inquisitor",
    # Tank / core-seeker.  Slow, heavily armoured, methodical.
    # Carries shield scrolls and healing potions (equipment, not innate).
    # At higher status: more selfish — willing to sacrifice allies.
    hp=120, speed=1, damage=8,
    attack_interval=20, attack_range=1,
    perception_range=4, darkvision_range=0,
    arcane_sight_range=0, trap_detect_range=0,
    move_interval=10,
    retreat_threshold=0.10, greed=0.05, loyalty=0.9, cunning=0.2,
    exploration_drive=0.1, risk_tolerance=0.8,
    map_memory=0.5, supply_efficiency=1.0,
    can_fly=False, can_dig=False, can_bash_door=True, can_lockpick=False,
    phase_thickness=0, familiar_capacity=0, dramatic=False,
    food_capacity=12.0, water_capacity=10.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=3, base_gear_loadout="inquisitor",
    objective_weights=(0.9, 0.0, 0.1),
)

GLOOMWARDEN = ArchetypeStats(
    name="Gloomwarden",
    # Support / protector.  Rangers of the dark — illuminate, disarm
    # traps, provide morale.  Innate arcane sight (supernatural sense).
    # Pacifist tendency (loyalty=1.0 makes them stay with party,
    # low greed means they never betray for treasure).
    hp=60, speed=2, damage=4,
    attack_interval=20, attack_range=1,
    perception_range=5, darkvision_range=3,
    arcane_sight_range=3, trap_detect_range=1,
    move_interval=5,
    retreat_threshold=0.25, greed=0.0, loyalty=1.0, cunning=0.6,
    exploration_drive=0.4, risk_tolerance=0.5,
    map_memory=0.7, supply_efficiency=0.9,
    can_fly=False, can_dig=False, can_bash_door=False, can_lockpick=False,
    phase_thickness=0, familiar_capacity=0, dramatic=False,
    food_capacity=10.0, water_capacity=8.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=3, base_gear_loadout="gloomwarden",
    objective_weights=(0.4, 0.4, 0.2),
)

MOLE_TAMER = ArchetypeStats(
    name="Mole Tamer",
    # Siege / bypass.  Controls digging familiars (innate).
    # Familiars grow unruly the more they dig — exploitable.
    hp=50, speed=2, damage=3,
    attack_interval=20, attack_range=1,
    perception_range=3, darkvision_range=2,
    arcane_sight_range=0, trap_detect_range=0,
    move_interval=6,
    retreat_threshold=0.20, greed=0.1, loyalty=0.6, cunning=0.5,
    exploration_drive=0.3, risk_tolerance=0.5,
    map_memory=0.6, supply_efficiency=1.0,
    can_fly=False, can_dig=False, can_bash_door=False, can_lockpick=False,
    phase_thickness=0, familiar_capacity=3, dramatic=False,
    food_capacity=10.0, water_capacity=8.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=2, base_gear_loadout="mole_tamer",
    objective_weights=(0.6, 0.3, 0.1),
)

EIDOLON = ArchetypeStats(
    name="Eidolon",
    # Wild card.  Supernatural, non-hostile by default.  Seeks
    # entertainment — bored eidolons wreck things, entertained ones
    # bestow gifts.  Innate flight and phase-walk through thin walls.
    # Always travel in pairs, no status rank.
    hp=80, speed=3, damage=6,
    attack_interval=20, attack_range=1,
    perception_range=6, darkvision_range=4,
    arcane_sight_range=0, trap_detect_range=0,
    move_interval=4,
    retreat_threshold=0.0, greed=0.0, loyalty=1.0, cunning=0.4,
    exploration_drive=0.8, risk_tolerance=0.9,
    map_memory=0.3, supply_efficiency=0.0,  # eidolons don't consume supplies
    can_fly=True, can_dig=False, can_bash_door=False, can_lockpick=False,
    phase_thickness=2, familiar_capacity=0, dramatic=False,
    food_capacity=0.0, water_capacity=0.0,
    food_rate=0.0, water_rate=0.0,
    base_inventory_slots=0, base_gear_loadout="eidolon",
    objective_weights=(0.0, 0.8, 0.2),
)

ALCHEMIST = ArchetypeStats(
    name="Alchemist",
    # Bruiser / harvester.  Brings reputation-driven counter-potions:
    # if the dungeon drowns intruders, alchemists brew water-breathing;
    # if it burns them, fire-immunity.  Distinguished by the *amount*
    # of potions brought, not exclusive access to them.
    hp=55, speed=2, damage=5,
    attack_interval=20, attack_range=1,
    perception_range=4, darkvision_range=0,
    arcane_sight_range=0, trap_detect_range=0,
    move_interval=5,
    retreat_threshold=0.20, greed=0.3, loyalty=0.5, cunning=0.6,
    exploration_drive=0.2, risk_tolerance=0.6,
    map_memory=0.5, supply_efficiency=1.0,
    can_fly=False, can_dig=False, can_bash_door=False, can_lockpick=False,
    phase_thickness=0, familiar_capacity=0, dramatic=False,
    food_capacity=8.0, water_capacity=7.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=5, base_gear_loadout="alchemist",
    objective_weights=(0.5, 0.1, 0.4),
)

CARTOMANCER = ArchetypeStats(
    name="Cartomancer",
    # Utility mage.  Carries pre-prepared spell scrolls chosen by
    # reputation.  Physically frail but terrifyingly versatile.
    # Scroll count scales with status rank.
    hp=30, speed=2, damage=2,
    attack_interval=20, attack_range=1,
    perception_range=4, darkvision_range=0,
    arcane_sight_range=0, trap_detect_range=0,
    move_interval=5,
    retreat_threshold=0.35, greed=0.1, loyalty=0.5, cunning=0.7,
    exploration_drive=0.3, risk_tolerance=0.4,
    map_memory=0.8, supply_efficiency=1.0,
    can_fly=False, can_dig=False, can_bash_door=False, can_lockpick=False,
    phase_thickness=0, familiar_capacity=0, dramatic=False,
    food_capacity=6.0, water_capacity=5.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=6, base_gear_loadout="cartomancer",
    objective_weights=(0.7, 0.2, 0.1),
)

HERO = ArchetypeStats(
    name="Hero",
    # Boss.  Extreme power, supernatural luck, narrative binding.
    # Follows the most dramatic path (stubbed — predictability IS the
    # weakness).  Never retreats.  Barely any magic, brute-forces
    # everything.  Always high status.
    hp=250, speed=2, damage=20,
    attack_interval=15, attack_range=1,
    perception_range=5, darkvision_range=0,
    arcane_sight_range=0, trap_detect_range=0,
    move_interval=5,
    retreat_threshold=0.0, greed=0.0, loyalty=1.0, cunning=0.1,
    exploration_drive=0.0, risk_tolerance=1.0,
    map_memory=0.3, supply_efficiency=0.5,
    can_fly=False, can_dig=False, can_bash_door=True, can_lockpick=False,
    phase_thickness=0, familiar_capacity=0, dramatic=True,
    food_capacity=15.0, water_capacity=12.0,
    food_rate=0.01, water_rate=0.015,
    base_inventory_slots=2, base_gear_loadout="hero",
    objective_weights=(1.0, 0.0, 0.0),
)


# ── Lookup tables ────────────────────────────────────────────────────

ALL_ARCHETYPES: tuple[ArchetypeStats, ...] = (
    EXPLORER, INQUISITOR, GLOOMWARDEN, MOLE_TAMER,
    EIDOLON, ALCHEMIST, CARTOMANCER, HERO,
)

ARCHETYPE_BY_NAME: dict[str, ArchetypeStats] = {a.name: a for a in ALL_ARCHETYPES}
