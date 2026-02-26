"""Per-voxel material property lookup tables.

Every material property used by the physics and building systems is
defined here as a dict keyed by voxel type.  Adding a new material
means adding an entry to each relevant LUT.

Dependencies: config.voxels
Dependents: config.__init__, world.physics.*, building.build_system,
            world.voxel_grid, intruders.decision
"""

from .voxels import (
    VOXEL_AIR,
    VOXEL_ALARM_BELL,
    VOXEL_BASALT,
    VOXEL_BEDROCK,
    VOXEL_CHALK,
    VOXEL_COPPER_INGOT,
    VOXEL_COPPER_ORE,
    VOXEL_CORE,
    VOXEL_DIRT,
    VOXEL_DOOR,
    VOXEL_ENCHANTED_METAL,
    VOXEL_FLOODGATE,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_GNEISS,
    VOXEL_GOLD_BAIT,
    VOXEL_GOLD_INGOT,
    VOXEL_GOLD_ORE,
    VOXEL_GRANITE,
    VOXEL_HEAT_BEACON,
    VOXEL_IRON_BARS,
    VOXEL_IRON_INGOT,
    VOXEL_IRON_ORE,
    VOXEL_LAVA,
    VOXEL_LAVA_SINK,
    VOXEL_LAVA_SOURCE,
    VOXEL_LIMESTONE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_MARBLE,
    VOXEL_OBSIDIAN,
    VOXEL_PIPE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_PUMP,
    VOXEL_REINFORCED_WALL,
    VOXEL_ROLLING_STONE,
    VOXEL_SANDSTONE,
    VOXEL_SHALE,
    VOXEL_SLATE,
    VOXEL_SLOPE,
    VOXEL_SPIKE,
    VOXEL_STAIRS,
    VOXEL_STEAM_VENT,
    VOXEL_STONE,
    VOXEL_TARP,
    VOXEL_TREASURE,
    VOXEL_WATER,
    VOXEL_WATER_SINK,
    VOXEL_WATER_SOURCE,
)

# ── Non-diggable voxel types ─────────────────────────────────────────

NON_DIGGABLE = frozenset({
    VOXEL_AIR, VOXEL_BEDROCK, VOXEL_CORE, VOXEL_LAVA, VOXEL_WATER,
    VOXEL_REINFORCED_WALL, VOXEL_IRON_BARS, VOXEL_FLOODGATE,
    VOXEL_WATER_SOURCE, VOXEL_WATER_SINK, VOXEL_LAVA_SOURCE, VOXEL_LAVA_SINK,
})

# ── Porosity (0.0 = impermeable, 1.0 = fully permeable) ─────────────

VOXEL_POROSITY = {
    VOXEL_AIR: 1.0,
    VOXEL_DIRT: 0.4,
    VOXEL_STONE: 0.005,
    VOXEL_BEDROCK: 0.0,
    VOXEL_CORE: 0.0,
    VOXEL_SANDSTONE: 0.35,
    VOXEL_LIMESTONE: 0.25,
    VOXEL_SHALE: 0.05,
    VOXEL_CHALK: 0.6,
    VOXEL_SLATE: 0.02,
    VOXEL_MARBLE: 0.01,
    VOXEL_GNEISS: 0.01,
    VOXEL_GRANITE: 0.005,
    VOXEL_BASALT: 0.01,
    VOXEL_OBSIDIAN: 0.0,
    VOXEL_IRON_ORE: 0.05,
    VOXEL_COPPER_ORE: 0.03,
    VOXEL_GOLD_ORE: 0.02,
    VOXEL_MANA_CRYSTAL: 0.0,
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 1.0,
    VOXEL_IRON_INGOT: 0.0,
    VOXEL_COPPER_INGOT: 0.0,
    VOXEL_GOLD_INGOT: 0.0,
    VOXEL_ENCHANTED_METAL: 0.0,
    VOXEL_REINFORCED_WALL: 0.0,
    VOXEL_SPIKE: 0.0,
    VOXEL_DOOR: 0.0,
    VOXEL_TREASURE: 0.0,
    VOXEL_ROLLING_STONE: 0.3,     # granular (rolls via angle of repose)
    VOXEL_TARP: 0.8,              # porous fabric
    VOXEL_SLOPE: 0.01,
    VOXEL_STAIRS: 0.01,
    VOXEL_GOLD_BAIT: 0.0,
    VOXEL_HEAT_BEACON: 0.0,
    VOXEL_PRESSURE_PLATE: 0.0,
    VOXEL_IRON_BARS: 0.8,           # transparent (LOS passes through)
    VOXEL_FLOODGATE: 0.0,
    VOXEL_ALARM_BELL: 0.0,
    VOXEL_FRAGILE_FLOOR: 0.6,       # chalky / weak
    VOXEL_PIPE: 0.0,
    VOXEL_PUMP: 0.0,
    VOXEL_STEAM_VENT: 0.3,          # obsidian-derived, some porosity
    VOXEL_WATER_SOURCE: 0.0,
    VOXEL_WATER_SINK: 0.0,
    VOXEL_LAVA_SOURCE: 0.0,
    VOXEL_LAVA_SINK: 0.0,
}

# ── Thermal conductivity (0.0 = insulator, 1.0 = perfect conductor) ──

VOXEL_CONDUCTIVITY = {
    VOXEL_AIR: 0.05,
    VOXEL_DIRT: 0.3,
    VOXEL_STONE: 0.6,
    VOXEL_BEDROCK: 0.4,
    VOXEL_CORE: 0.1,
    VOXEL_SANDSTONE: 0.4,
    VOXEL_LIMESTONE: 0.45,
    VOXEL_SHALE: 0.35,
    VOXEL_CHALK: 0.3,
    VOXEL_SLATE: 0.55,
    VOXEL_MARBLE: 0.6,
    VOXEL_GNEISS: 0.65,
    VOXEL_GRANITE: 0.7,
    VOXEL_BASALT: 0.75,
    VOXEL_OBSIDIAN: 0.8,
    VOXEL_IRON_ORE: 0.5,
    VOXEL_COPPER_ORE: 0.55,
    VOXEL_GOLD_ORE: 0.6,
    VOXEL_MANA_CRYSTAL: 0.0,   # absorbs heat, does not conduct
    VOXEL_LAVA: 0.05,  # Low: solidified crust insulates; convection handles lava-lava
    VOXEL_WATER: 0.6,
    VOXEL_IRON_INGOT: 0.8,
    VOXEL_COPPER_INGOT: 0.85,
    VOXEL_GOLD_INGOT: 0.9,
    VOXEL_ENCHANTED_METAL: 0.5,
    VOXEL_REINFORCED_WALL: 0.75,
    VOXEL_SPIKE: 0.8,
    VOXEL_DOOR: 0.5,
    VOXEL_TREASURE: 0.9,
    VOXEL_ROLLING_STONE: 0.7,
    VOXEL_TARP: 0.1,
    VOXEL_SLOPE: 0.6,
    VOXEL_STAIRS: 0.6,
    VOXEL_GOLD_BAIT: 0.85,
    VOXEL_HEAT_BEACON: 0.90,
    VOXEL_PRESSURE_PLATE: 0.85,
    VOXEL_IRON_BARS: 0.80,
    VOXEL_FLOODGATE: 0.80,
    VOXEL_ALARM_BELL: 0.85,
    VOXEL_FRAGILE_FLOOR: 0.15,       # chalky insulator
    VOXEL_PIPE: 0.90,                 # good conductor (metal tube)
    VOXEL_PUMP: 0.80,
    VOXEL_STEAM_VENT: 0.80,
    VOXEL_WATER_SOURCE: 0.6,
    VOXEL_WATER_SINK: 0.5,
    VOXEL_LAVA_SOURCE: 1.0,
    VOXEL_LAVA_SINK: 0.8,
}

# ── Dig durations in ticks (at 20 ticks/sec) ─────────────────────────

DIG_DURATION = {
    VOXEL_DIRT: 20,         # 1 second
    VOXEL_STONE: 40,        # 2 seconds (legacy)
    VOXEL_SANDSTONE: 30,    # 1.5 seconds
    VOXEL_LIMESTONE: 35,    # 1.75 seconds
    VOXEL_SHALE: 25,        # 1.25 seconds (brittle)
    VOXEL_CHALK: 20,        # 1 second (soft)
    VOXEL_SLATE: 60,        # 3 seconds
    VOXEL_MARBLE: 70,       # 3.5 seconds
    VOXEL_GNEISS: 65,       # 3.25 seconds
    VOXEL_GRANITE: 100,     # 5 seconds
    VOXEL_BASALT: 90,       # 4.5 seconds
    VOXEL_OBSIDIAN: 200,    # 10 seconds
    VOXEL_IRON_ORE: 50,     # 2.5 seconds
    VOXEL_COPPER_ORE: 55,   # 2.75 seconds
    VOXEL_GOLD_ORE: 60,     # 3 seconds
    VOXEL_MANA_CRYSTAL: 80, # 4 seconds
    VOXEL_SPIKE: 60,        # 3 seconds
    VOXEL_DOOR: 50,         # 2.5 seconds
    VOXEL_TREASURE: 30,     # 1.5 seconds
    VOXEL_ROLLING_STONE: 80, # 4 seconds
    VOXEL_TARP: 10,         # 0.5 seconds (flimsy)
    VOXEL_SLOPE: 45,        # 2.25 seconds
    VOXEL_STAIRS: 45,       # 2.25 seconds
    VOXEL_GOLD_BAIT: 60,    # 3 seconds
    VOXEL_HEAT_BEACON: 50,   # 2.5 seconds
    VOXEL_PRESSURE_PLATE: 50, # 2.5 seconds
    VOXEL_ALARM_BELL: 40,    # 2 seconds
    VOXEL_FRAGILE_FLOOR: 30, # 1.5 seconds (weak)
    VOXEL_PIPE: 40,           # 2 seconds
    VOXEL_PUMP: 50,           # 2.5 seconds
    VOXEL_STEAM_VENT: 80,    # 4 seconds (obsidian-like)
    # VOXEL_IRON_BARS and VOXEL_FLOODGATE are NON_DIGGABLE
}

# ── Material weight (arbitrary load units, granite=10.0 baseline) ────

VOXEL_WEIGHT = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 5.0,
    VOXEL_STONE: 8.0,
    VOXEL_BEDROCK: 0.0,
    VOXEL_CORE: 0.0,
    VOXEL_SANDSTONE: 6.0,
    VOXEL_LIMESTONE: 7.0,
    VOXEL_SHALE: 5.5,
    VOXEL_CHALK: 4.0,
    VOXEL_SLATE: 7.5,
    VOXEL_MARBLE: 8.5,
    VOXEL_GNEISS: 8.0,
    VOXEL_GRANITE: 10.0,
    VOXEL_BASALT: 11.0,
    VOXEL_OBSIDIAN: 9.0,
    VOXEL_IRON_ORE: 12.0,
    VOXEL_COPPER_ORE: 11.0,
    VOXEL_GOLD_ORE: 14.0,
    VOXEL_MANA_CRYSTAL: 0.0,
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 3.0,
    VOXEL_IRON_INGOT: 15.0,
    VOXEL_COPPER_INGOT: 14.0,
    VOXEL_GOLD_INGOT: 18.0,
    VOXEL_ENCHANTED_METAL: 10.0,
    VOXEL_REINFORCED_WALL: 12.0,
    VOXEL_SPIKE: 8.0,
    VOXEL_DOOR: 6.0,
    VOXEL_TREASURE: 20.0,
    VOXEL_ROLLING_STONE: 12.0,
    VOXEL_TARP: 0.5,
    VOXEL_SLOPE: 7.0,
    VOXEL_STAIRS: 7.0,
    VOXEL_GOLD_BAIT: 18.0,
    VOXEL_HEAT_BEACON: 14.0,
    VOXEL_PRESSURE_PLATE: 8.0,
    VOXEL_IRON_BARS: 10.0,
    VOXEL_FLOODGATE: 12.0,
    VOXEL_ALARM_BELL: 6.0,
    VOXEL_FRAGILE_FLOOR: 4.0,
    VOXEL_PIPE: 10.0,
    VOXEL_PUMP: 14.0,
    VOXEL_STEAM_VENT: 9.0,
    VOXEL_WATER_SOURCE: 0.0,
    VOXEL_WATER_SINK: 0.0,
    VOXEL_LAVA_SOURCE: 0.0,
    VOXEL_LAVA_SINK: 0.0,
}

# ── Max load capacity (compressive strength) ─────────────────────────
# 3× base values — cave-ins should be rare, deliberate action only

VOXEL_MAX_LOAD = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 90.0,
    VOXEL_STONE: 360.0,
    VOXEL_BEDROCK: float("inf"),
    VOXEL_CORE: float("inf"),
    VOXEL_SANDSTONE: 180.0,
    VOXEL_LIMESTONE: 225.0,
    VOXEL_SHALE: 135.0,
    VOXEL_CHALK: 68.0,
    VOXEL_SLATE: 315.0,
    VOXEL_MARBLE: 380.0,
    VOXEL_GNEISS: 340.0,
    VOXEL_GRANITE: 540.0,
    VOXEL_BASALT: 495.0,
    VOXEL_OBSIDIAN: 270.0,
    VOXEL_IRON_ORE: 290.0,
    VOXEL_COPPER_ORE: 250.0,
    VOXEL_GOLD_ORE: 200.0,
    VOXEL_MANA_CRYSTAL: float("inf"),
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,
    VOXEL_IRON_INGOT: 450.0,
    VOXEL_COPPER_INGOT: 360.0,
    VOXEL_GOLD_INGOT: 225.0,
    VOXEL_ENCHANTED_METAL: 675.0,
    VOXEL_REINFORCED_WALL: 900.0,  # strongest buildable block
    VOXEL_SPIKE: 180.0,
    VOXEL_DOOR: 360.0,
    VOXEL_TREASURE: 135.0,
    VOXEL_ROLLING_STONE: 450.0,
    VOXEL_TARP: 15.0,             # still fragile (breaks under a few blocks)
    VOXEL_SLOPE: 360.0,
    VOXEL_STAIRS: 360.0,
    VOXEL_GOLD_BAIT: 135.0,
    VOXEL_HEAT_BEACON: 360.0,
    VOXEL_PRESSURE_PLATE: 360.0,
    VOXEL_IRON_BARS: 450.0,
    VOXEL_FLOODGATE: 675.0,
    VOXEL_ALARM_BELL: 135.0,
    VOXEL_FRAGILE_FLOOR: 24.0,       # still deliberately weak
    VOXEL_PIPE: 360.0,
    VOXEL_PUMP: 405.0,
    VOXEL_STEAM_VENT: 180.0,
    VOXEL_WATER_SOURCE: float("inf"),
    VOXEL_WATER_SINK: float("inf"),
    VOXEL_LAVA_SOURCE: float("inf"),
    VOXEL_LAVA_SINK: float("inf"),
}

# ── Stiffness (load attraction: stiffer receivers take more load) ────
# In redundant structures, F_i = k_i / Σk_j × F_total (direct stiffness method)

VOXEL_STIFFNESS = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 1.0,
    VOXEL_STONE: 6.0,
    VOXEL_BEDROCK: 100.0,
    VOXEL_CORE: 100.0,
    VOXEL_SANDSTONE: 2.0,
    VOXEL_LIMESTONE: 3.5,
    VOXEL_SHALE: 1.5,
    VOXEL_CHALK: 0.5,
    VOXEL_SLATE: 5.0,
    VOXEL_MARBLE: 7.0,
    VOXEL_GNEISS: 6.5,
    VOXEL_GRANITE: 10.0,
    VOXEL_BASALT: 9.0,
    VOXEL_OBSIDIAN: 4.0,
    VOXEL_IRON_ORE: 5.0,
    VOXEL_COPPER_ORE: 4.5,
    VOXEL_GOLD_ORE: 3.0,
    VOXEL_MANA_CRYSTAL: 100.0,
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,
    VOXEL_IRON_INGOT: 12.0,
    VOXEL_COPPER_INGOT: 10.0,
    VOXEL_GOLD_INGOT: 6.0,
    VOXEL_ENCHANTED_METAL: 15.0,
    VOXEL_REINFORCED_WALL: 20.0,
    VOXEL_SPIKE: 8.0,
    VOXEL_DOOR: 10.0,
    VOXEL_TREASURE: 3.0,
    VOXEL_ROLLING_STONE: 10.0,
    VOXEL_TARP: 0.1,
    VOXEL_SLOPE: 6.0,
    VOXEL_STAIRS: 6.0,
    VOXEL_GOLD_BAIT: 3.0,
    VOXEL_HEAT_BEACON: 8.0,
    VOXEL_PRESSURE_PLATE: 9.0,
    VOXEL_IRON_BARS: 8.0,
    VOXEL_FLOODGATE: 10.0,
    VOXEL_ALARM_BELL: 4.0,
    VOXEL_FRAGILE_FLOOR: 1.0,
    VOXEL_PIPE: 7.0,
    VOXEL_PUMP: 8.0,
    VOXEL_STEAM_VENT: 4.0,
    VOXEL_WATER_SOURCE: 100.0,
    VOXEL_WATER_SINK: 100.0,
    VOXEL_LAVA_SOURCE: 100.0,
    VOXEL_LAVA_SINK: 100.0,
}

# ── Tensile strength (governs cantilever/bending failure) ────────────
# Failure: load × span / 2 > tensile_strength
# 3× base — cantilevers are more forgiving

VOXEL_TENSILE_STRENGTH = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 9.0,
    VOXEL_STONE: 45.0,
    VOXEL_BEDROCK: float("inf"),
    VOXEL_CORE: float("inf"),
    VOXEL_SANDSTONE: 22.0,
    VOXEL_LIMESTONE: 36.0,
    VOXEL_SHALE: 18.0,
    VOXEL_CHALK: 9.0,
    VOXEL_SLATE: 54.0,
    VOXEL_MARBLE: 45.0,
    VOXEL_GNEISS: 50.0,
    VOXEL_GRANITE: 68.0,
    VOXEL_BASALT: 63.0,
    VOXEL_OBSIDIAN: 27.0,      # brittle glass, snaps more easily
    VOXEL_IRON_ORE: 36.0,
    VOXEL_COPPER_ORE: 32.0,
    VOXEL_GOLD_ORE: 22.0,
    VOXEL_MANA_CRYSTAL: float("inf"),
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,
    VOXEL_IRON_INGOT: 180.0,   # wrought iron, excellent in tension
    VOXEL_COPPER_INGOT: 135.0,
    VOXEL_GOLD_INGOT: 68.0,
    VOXEL_ENCHANTED_METAL: 225.0,
    VOXEL_REINFORCED_WALL: 270.0,
    VOXEL_SPIKE: 90.0,
    VOXEL_DOOR: 135.0,
    VOXEL_TREASURE: 22.0,
    VOXEL_ROLLING_STONE: 68.0,
    VOXEL_TARP: 3.0,
    VOXEL_SLOPE: 45.0,
    VOXEL_STAIRS: 45.0,
    VOXEL_GOLD_BAIT: 68.0,
    VOXEL_HEAT_BEACON: 250.0,
    VOXEL_PRESSURE_PLATE: 270.0,
    VOXEL_IRON_BARS: 290.0,
    VOXEL_FLOODGATE: 360.0,
    VOXEL_ALARM_BELL: 90.0,
    VOXEL_FRAGILE_FLOOR: 9.0,
    VOXEL_PIPE: 225.0,
    VOXEL_PUMP: 250.0,
    VOXEL_STEAM_VENT: 27.0,
    VOXEL_WATER_SOURCE: float("inf"),
    VOXEL_WATER_SINK: float("inf"),
    VOXEL_LAVA_SOURCE: float("inf"),
    VOXEL_LAVA_SINK: float("inf"),
}

# ── Shear strength (lateral load capacity) ───────────────────────────
# Typically ~15-20% of compressive for stone, ~30-40% for ductile metals
# 3× base — lateral loads need deliberate force to cause failure

VOXEL_SHEAR_STRENGTH = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 18.0,
    VOXEL_STONE: 72.0,
    VOXEL_BEDROCK: float("inf"),
    VOXEL_CORE: float("inf"),
    VOXEL_SANDSTONE: 27.0,
    VOXEL_LIMESTONE: 36.0,
    VOXEL_SHALE: 20.0,
    VOXEL_CHALK: 9.0,
    VOXEL_SLATE: 45.0,
    VOXEL_MARBLE: 54.0,
    VOXEL_GNEISS: 50.0,
    VOXEL_GRANITE: 90.0,
    VOXEL_BASALT: 81.0,
    VOXEL_OBSIDIAN: 36.0,
    VOXEL_IRON_ORE: 58.0,
    VOXEL_COPPER_ORE: 50.0,
    VOXEL_GOLD_ORE: 32.0,
    VOXEL_MANA_CRYSTAL: float("inf"),
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,
    VOXEL_IRON_INGOT: 180.0,
    VOXEL_COPPER_INGOT: 144.0,
    VOXEL_GOLD_INGOT: 68.0,
    VOXEL_ENCHANTED_METAL: 270.0,
    VOXEL_REINFORCED_WALL: 225.0,
    VOXEL_SPIKE: 68.0,
    VOXEL_DOOR: 112.0,
    VOXEL_TREASURE: 22.0,
    VOXEL_ROLLING_STONE: 90.0,
    VOXEL_TARP: 3.0,
    VOXEL_SLOPE: 54.0,
    VOXEL_STAIRS: 54.0,
    VOXEL_GOLD_BAIT: 54.0,
    VOXEL_HEAT_BEACON: 158.0,
    VOXEL_PRESSURE_PLATE: 180.0,
    VOXEL_IRON_BARS: 200.0,
    VOXEL_FLOODGATE: 270.0,
    VOXEL_ALARM_BELL: 68.0,
    VOXEL_FRAGILE_FLOOR: 6.0,
    VOXEL_PIPE: 135.0,
    VOXEL_PUMP: 158.0,
    VOXEL_STEAM_VENT: 36.0,
    VOXEL_WATER_SOURCE: float("inf"),
    VOXEL_WATER_SINK: float("inf"),
    VOXEL_LAVA_SOURCE: float("inf"),
    VOXEL_LAVA_SINK: float("inf"),
}

# ── Coefficient of Thermal Expansion ─────────────────────────────────
# Higher = more susceptible to thermal shock (gradient × CTE = stress)
# Glass/obsidian extremely vulnerable; metals are ductile and resist

VOXEL_CTE = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 0.005,
    VOXEL_STONE: 0.008,
    VOXEL_BEDROCK: 0.0,
    VOXEL_CORE: 0.0,
    VOXEL_SANDSTONE: 0.010,
    VOXEL_LIMESTONE: 0.009,
    VOXEL_SHALE: 0.012,
    VOXEL_CHALK: 0.015,
    VOXEL_SLATE: 0.007,
    VOXEL_MARBLE: 0.008,
    VOXEL_GNEISS: 0.006,
    VOXEL_GRANITE: 0.005,
    VOXEL_BASALT: 0.006,
    VOXEL_OBSIDIAN: 0.025,        # glass! extreme thermal shock vulnerability
    VOXEL_IRON_ORE: 0.004,
    VOXEL_COPPER_ORE: 0.005,
    VOXEL_GOLD_ORE: 0.006,
    VOXEL_MANA_CRYSTAL: 0.0,
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,
    VOXEL_IRON_INGOT: 0.003,
    VOXEL_COPPER_INGOT: 0.004,
    VOXEL_GOLD_INGOT: 0.005,
    VOXEL_ENCHANTED_METAL: 0.001,
    VOXEL_REINFORCED_WALL: 0.003,
    VOXEL_SPIKE: 0.003,
    VOXEL_DOOR: 0.001,
    VOXEL_TREASURE: 0.005,
    VOXEL_ROLLING_STONE: 0.005,
    VOXEL_TARP: 0.001,
    VOXEL_SLOPE: 0.008,
    VOXEL_STAIRS: 0.008,
    VOXEL_GOLD_BAIT: 0.004,
    VOXEL_HEAT_BEACON: 0.003,
    VOXEL_PRESSURE_PLATE: 0.002,
    VOXEL_IRON_BARS: 0.003,
    VOXEL_FLOODGATE: 0.002,
    VOXEL_ALARM_BELL: 0.004,
    VOXEL_FRAGILE_FLOOR: 0.015,      # chalky, thermally vulnerable
    VOXEL_PIPE: 0.003,
    VOXEL_PUMP: 0.003,
    VOXEL_STEAM_VENT: 0.025,         # obsidian-level thermal cycling
    VOXEL_WATER_SOURCE: 0.0,
    VOXEL_WATER_SINK: 0.0,
    VOXEL_LAVA_SOURCE: 0.0,
    VOXEL_LAVA_SINK: 0.0,
}

# ── Shock wave transmissivity (inverse of absorption) ────────────────
# 0.0 = absorbs all shock (ductile), 1.0 = transmits all (rigid/brittle)

VOXEL_SHOCK_TRANSMIT = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 0.1,
    VOXEL_STONE: 0.5,
    VOXEL_BEDROCK: 0.0,
    VOXEL_CORE: 0.0,
    VOXEL_SANDSTONE: 0.3,
    VOXEL_LIMESTONE: 0.4,
    VOXEL_SHALE: 0.6,
    VOXEL_CHALK: 0.2,
    VOXEL_SLATE: 0.55,
    VOXEL_MARBLE: 0.5,
    VOXEL_GNEISS: 0.45,
    VOXEL_GRANITE: 0.6,
    VOXEL_BASALT: 0.65,
    VOXEL_OBSIDIAN: 0.8,          # glass transmits shock extremely well
    VOXEL_IRON_ORE: 0.4,
    VOXEL_COPPER_ORE: 0.35,
    VOXEL_GOLD_ORE: 0.3,
    VOXEL_MANA_CRYSTAL: 0.0,
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,             # liquid absorbs shock
    VOXEL_IRON_INGOT: 0.2,
    VOXEL_COPPER_INGOT: 0.15,
    VOXEL_GOLD_INGOT: 0.1,
    VOXEL_ENCHANTED_METAL: 0.05,
    VOXEL_REINFORCED_WALL: 0.15,
    VOXEL_SPIKE: 0.3,
    VOXEL_DOOR: 0.1,
    VOXEL_TREASURE: 0.1,
    VOXEL_ROLLING_STONE: 0.5,
    VOXEL_TARP: 0.0,
    VOXEL_SLOPE: 0.5,
    VOXEL_STAIRS: 0.5,
    VOXEL_GOLD_BAIT: 0.3,
    VOXEL_HEAT_BEACON: 0.6,
    VOXEL_PRESSURE_PLATE: 0.7,
    VOXEL_IRON_BARS: 0.6,
    VOXEL_FLOODGATE: 0.7,
    VOXEL_ALARM_BELL: 0.4,
    VOXEL_FRAGILE_FLOOR: 0.2,
    VOXEL_PIPE: 0.5,
    VOXEL_PUMP: 0.6,
    VOXEL_STEAM_VENT: 0.8,
    VOXEL_WATER_SOURCE: 0.0,
    VOXEL_WATER_SINK: 0.0,
    VOXEL_LAVA_SOURCE: 0.0,
    VOXEL_LAVA_SINK: 0.0,
}

# ── Brittleness (shatter vs crack on impact) ─────────────────────────
# 0.0 = always cracks (ductile), 1.0 = always shatters to air (brittle)

VOXEL_BRITTLENESS = {
    VOXEL_AIR: 0.0,
    VOXEL_DIRT: 0.0,
    VOXEL_STONE: 0.3,
    VOXEL_BEDROCK: 0.0,
    VOXEL_CORE: 0.0,
    VOXEL_SANDSTONE: 0.4,
    VOXEL_LIMESTONE: 0.35,
    VOXEL_SHALE: 0.6,
    VOXEL_CHALK: 0.8,
    VOXEL_SLATE: 0.5,
    VOXEL_MARBLE: 0.4,
    VOXEL_GNEISS: 0.3,
    VOXEL_GRANITE: 0.2,
    VOXEL_BASALT: 0.25,
    VOXEL_OBSIDIAN: 0.95,         # glass shatters spectacularly
    VOXEL_IRON_ORE: 0.3,
    VOXEL_COPPER_ORE: 0.25,
    VOXEL_GOLD_ORE: 0.2,
    VOXEL_MANA_CRYSTAL: 0.0,
    VOXEL_LAVA: 0.0,
    VOXEL_WATER: 0.0,
    VOXEL_IRON_INGOT: 0.05,
    VOXEL_COPPER_INGOT: 0.05,
    VOXEL_GOLD_INGOT: 0.02,
    VOXEL_ENCHANTED_METAL: 0.01,
    VOXEL_REINFORCED_WALL: 0.05,
    VOXEL_SPIKE: 0.1,
    VOXEL_DOOR: 0.05,
    VOXEL_TREASURE: 0.2,
    VOXEL_ROLLING_STONE: 0.2,
    VOXEL_TARP: 0.0,
    VOXEL_SLOPE: 0.3,
    VOXEL_STAIRS: 0.3,
    VOXEL_GOLD_BAIT: 0.15,
    VOXEL_HEAT_BEACON: 0.08,
    VOXEL_PRESSURE_PLATE: 0.05,
    VOXEL_IRON_BARS: 0.05,
    VOXEL_FLOODGATE: 0.05,
    VOXEL_ALARM_BELL: 0.10,
    VOXEL_FRAGILE_FLOOR: 0.8,       # chalky, shatters easily
    VOXEL_PIPE: 0.08,
    VOXEL_PUMP: 0.05,
    VOXEL_STEAM_VENT: 0.80,         # obsidian-level brittleness
    VOXEL_WATER_SOURCE: 0.0,
    VOXEL_WATER_SINK: 0.0,
    VOXEL_LAVA_SOURCE: 0.0,
    VOXEL_LAVA_SINK: 0.0,
}
