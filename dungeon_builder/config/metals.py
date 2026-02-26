"""Metal type system — per-voxel uint8 specifying what metal a block is made of.

Properties (melt temp, strength, greed, color) are derived compositionally
from metal type × block type.  Adding a new metal means adding entries to
the tables here and (optionally) colour entries in ``rendering.py``.

Dependencies: config.voxels
Dependents: config.__init__, building.crafting_book, building.build_system,
            world.physics.temperature, rendering.voxel_renderer
"""

from .voxels import (
    VOXEL_ALARM_BELL,
    VOXEL_COPPER_INGOT,
    VOXEL_COPPER_ORE,
    VOXEL_DOOR,
    VOXEL_ENCHANTED_METAL,
    VOXEL_FLOODGATE,
    VOXEL_GOLD_BAIT,
    VOXEL_GOLD_INGOT,
    VOXEL_GOLD_ORE,
    VOXEL_HEAT_BEACON,
    VOXEL_IRON_BARS,
    VOXEL_IRON_INGOT,
    VOXEL_IRON_ORE,
    VOXEL_PIPE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_PUMP,
    VOXEL_REINFORCED_WALL,
    VOXEL_SPIKE,
)

# ── Base metal constants ─────────────────────────────────────────────

METAL_NONE = 0       # Non-metallic blocks (stone, dirt, etc.)
METAL_IRON = 1
METAL_COPPER = 2
METAL_GOLD = 3
# Future: METAL_BRONZE = 4, METAL_STEEL = 5, METAL_MITHRIL = 6, ...

# Enchanted variants: bit 7 set → melt-immune, otherwise same base metal
ENCHANTED_OFFSET = 128
METAL_ENCH_IRON = METAL_IRON | ENCHANTED_OFFSET      # 129
METAL_ENCH_COPPER = METAL_COPPER | ENCHANTED_OFFSET   # 130
METAL_ENCH_GOLD = METAL_GOLD | ENCHANTED_OFFSET       # 131

# ── Helper functions ─────────────────────────────────────────────────


def is_enchanted_metal(metal_type: int) -> bool:
    """True if metal_type represents an enchanted variant (melt-immune)."""
    return (metal_type & ENCHANTED_OFFSET) != 0


def base_metal_of(metal_type: int) -> int:
    """Strip enchanted bit to get base metal (METAL_IRON/COPPER/GOLD)."""
    return metal_type & 0x7F


def make_enchanted(metal_type: int) -> int:
    """Return the enchanted version of a base metal type."""
    return metal_type | ENCHANTED_OFFSET


# ── Voxel ↔ metal mappings ───────────────────────────────────────────

# Map held voxel type → metal constant for crafting
HELD_TO_METAL = {
    VOXEL_IRON_INGOT: METAL_IRON,
    VOXEL_COPPER_INGOT: METAL_COPPER,
    VOXEL_GOLD_INGOT: METAL_GOLD,
    VOXEL_ENCHANTED_METAL: METAL_NONE,  # generic enchanted — caller sets from source
}

# Map ore voxel → base metal type
ORE_TO_METAL = {
    VOXEL_IRON_ORE: METAL_IRON,
    VOXEL_COPPER_ORE: METAL_COPPER,
    VOXEL_GOLD_ORE: METAL_GOLD,
}

# ── Metal property tables (independent of block type) ────────────────

METAL_MELT_TEMPERATURE = {
    METAL_NONE: 0.0,       # non-metallic → never melts via metal system
    METAL_IRON: 1200.0,
    METAL_COPPER: 800.0,
    METAL_GOLD: 600.0,
}

METAL_STRENGTH_MULT = {    # multiplier on block's base shear/tensile/max_load
    METAL_NONE: 1.0,
    METAL_IRON: 1.0,       # baseline
    METAL_COPPER: 0.7,
    METAL_GOLD: 0.4,
}

METAL_GREED_APPEAL = {     # added to intruder greed calculation when visible
    METAL_NONE: 0.0,
    METAL_IRON: 0.0,
    METAL_COPPER: 0.2,
    METAL_GOLD: 0.8,
}

METAL_COLORS: dict[int, tuple[float, float, float]] = {
    METAL_NONE: (0.5, 0.5, 0.5),
    METAL_IRON: (0.55, 0.55, 0.60),
    METAL_COPPER: (0.72, 0.52, 0.35),
    METAL_GOLD: (0.95, 0.85, 0.20),
}

METAL_CONDUCTIVITY_MULT = {  # thermal conductivity multiplier for pipes
    METAL_NONE: 0.0,
    METAL_IRON: 0.8,
    METAL_COPPER: 1.0,       # best conductor
    METAL_GOLD: 0.9,
}

# ── Metallic block classifications ───────────────────────────────────

# Blocks that use metal_type (metallic objects)
METALLIC_BLOCKS = frozenset({
    VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
    VOXEL_ENCHANTED_METAL,
    VOXEL_REINFORCED_WALL, VOXEL_SPIKE, VOXEL_DOOR,
    VOXEL_GOLD_BAIT, VOXEL_HEAT_BEACON, VOXEL_PRESSURE_PLATE,
    VOXEL_IRON_BARS, VOXEL_FLOODGATE, VOXEL_ALARM_BELL,
    VOXEL_PIPE, VOXEL_PUMP,
})

# Blocks that can melt (enchanted metal_type is immune regardless)
MELTABLE_BLOCKS = frozenset({
    VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
    VOXEL_REINFORCED_WALL, VOXEL_SPIKE,
    VOXEL_HEAT_BEACON, VOXEL_PIPE, VOXEL_PUMP,
    VOXEL_DOOR, VOXEL_IRON_BARS, VOXEL_FLOODGATE,
    VOXEL_PRESSURE_PLATE, VOXEL_ALARM_BELL, VOXEL_GOLD_BAIT,
})
