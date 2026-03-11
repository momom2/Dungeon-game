"""Mana economy constants — generation, costs, upkeep, substitution.

Dependencies: config.voxels
Dependents: config.__init__, dungeon_core.mana, building.craft_cost,
    building.crafting_system, building.crafting_book,
    tests/economy/test_mana_system.py
"""

from .voxels import (
    VOXEL_ALARM_BELL,
    VOXEL_BASALT,
    VOXEL_CHALK,
    VOXEL_COPPER_INGOT,
    VOXEL_DIRT,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    VOXEL_ENCHANTED_METAL,
    VOXEL_GOLD_BAIT,
    VOXEL_GOLD_INGOT,
    VOXEL_GRANITE,
    VOXEL_HEAT_BEACON,
    VOXEL_IRON_INGOT,
    VOXEL_LIMESTONE,
    VOXEL_MARBLE,
    VOXEL_OBSIDIAN,
    VOXEL_PRESSURE_PLATE,
    VOXEL_SANDSTONE,
    VOXEL_STONE,
)

# ── Core mana pool ────────────────────────────────────────────────────

MANA_BASE_CAPACITY = 1000
MANA_GENERATION_PER_TICK = 5.0       # 100 mana/s ÷ 20 tps
MANA_DIG_COST_PER_TICK = 0.5         # 10 mana/s ÷ 20 tps per active dig
MANA_SOUL_CAPACITY_BONUS = 100       # +100 max mana per captured soul

# ── Per-block mana craft cost ─────────────────────────────────────────
# One-time cost when using regular metal instead of enchanted metal.

MANA_CRAFT_COST: dict[int, int] = {
    VOXEL_ENCHANTED_DOOR: 100,
    VOXEL_ENCHANTED_FLOODGATE: 100,
    VOXEL_GOLD_BAIT: 150,
    VOXEL_HEAT_BEACON: 120,
    VOXEL_PRESSURE_PLATE: 80,
    VOXEL_ALARM_BELL: 100,
}

# ── Per-block mana upkeep ────────────────────────────────────────────
# Mana consumed per second.  Divided by TICKS_PER_SECOND at runtime.

MANA_UPKEEP_PER_SECOND: dict[int, float] = {
    VOXEL_ENCHANTED_DOOR: 1.0,
    VOXEL_ENCHANTED_FLOODGATE: 1.0,
    VOXEL_GOLD_BAIT: 2.0,
    VOXEL_HEAT_BEACON: 2.0,
    VOXEL_PRESSURE_PLATE: 0.5,
    VOXEL_ALARM_BELL: 1.0,
}

# Derived: set of all magical trap types (have mana upkeep)
MAGICAL_TRAP_TYPES = frozenset(MANA_UPKEEP_PER_SECOND)

# ── Per-block mana capacitance ──────────────────────────────────────
# Maximum local mana a block can store.  Player controls per-block
# activation (active vs inactive drain rate) and charge mode (charging
# from core, idle, or draining back to core).  Sprites inject directly.

MANA_CAPACITANCE: dict[int, float] = {
    VOXEL_ENCHANTED_DOOR: 50.0,
    VOXEL_ENCHANTED_FLOODGATE: 50.0,
    VOXEL_GOLD_BAIT: 30.0,
    VOXEL_HEAT_BEACON: 40.0,
    VOXEL_PRESSURE_PLATE: 20.0,
    VOXEL_ALARM_BELL: 25.0,
}

# ── Per-block enchanted management rates (per second) ──────────────
# Converted to per-tick at runtime via TICKS_PER_SECOND.

ENCHANTED_ACTIVE_DRAIN_PER_S = 1.0     # Capacitance lost/s when active
ENCHANTED_INACTIVE_DRAIN_PER_S = 0.1   # Capacitance lost/s when inactive
ENCHANTED_CHARGE_PER_S = 2.0           # Capacitance gained/s from core
ENCHANTED_PLAYER_DRAIN_PER_S = 10.0    # Capacitance lost/s when player-draining
ENCHANTED_DRAIN_RECLAIM_PER_S = 1.0    # Mana returned to core/s when draining

MANA_SPRITE_INJECT = 15.0   # Mana injected by a sprite sacrifice

# ── Per-material mana substitute cost ────────────────────────────────
# Mana cost to conjure one unit of this material from raw mana.
# Higher = rarer / more valuable material.  Materials NOT in this table
# cannot be substituted — the player must provide them physically.

MANA_SUBSTITUTE_COST: dict[int, int] = {
    # Natural materials (cheap — common in dungeon)
    VOXEL_DIRT:        5,
    VOXEL_STONE:       10,
    VOXEL_SANDSTONE:   10,
    VOXEL_LIMESTONE:   12,
    VOXEL_CHALK:       8,
    VOXEL_GRANITE:     20,
    VOXEL_MARBLE:      18,
    VOXEL_BASALT:      22,
    VOXEL_OBSIDIAN:    40,

    # Metal ingots (moderate — must be smelted)
    VOXEL_IRON_INGOT:    30,
    VOXEL_COPPER_INGOT:  25,
    VOXEL_GOLD_INGOT:    50,

    # Enchanted metal (expensive — requires mana crystal + lava)
    VOXEL_ENCHANTED_METAL: 80,

    # Ores and mana crystals are NOT listed — non-substitutable.
}
