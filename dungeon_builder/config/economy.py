"""Mana economy constants — generation, costs, upkeep.

Dependencies: config.voxels
Dependents: config.__init__, dungeon_core.mana, building.crafting_system,
    building.crafting_book, tests/economy/test_mana_system.py
"""

from .voxels import (
    VOXEL_ALARM_BELL,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_PRESSURE_PLATE,
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
