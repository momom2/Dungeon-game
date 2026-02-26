"""Voxel type constants — uint8 IDs for the numpy voxel grid.

Every voxel type in the game is defined here.  Adding a new material
means adding a new constant and then populating the relevant LUTs in
``materials.py`` (and optionally ``rendering.py`` for colour).

Dependencies: (none — pure data module)
Dependents: config.world, config.metals, config.materials,
            config.physics, config.rendering, config.building,
            and transitively every system that uses voxel IDs
"""

# ── Natural terrain ──────────────────────────────────────────────────

VOXEL_AIR = 0
VOXEL_DIRT = 1
VOXEL_STONE = 2       # generic stone (treated as granite for gameplay)
VOXEL_BEDROCK = 3
VOXEL_CORE = 4

# Sedimentary rocks (upper layers)
VOXEL_SANDSTONE = 10
VOXEL_LIMESTONE = 11
VOXEL_SHALE = 12
VOXEL_CHALK = 13

# Metamorphic rocks (mid layers)
VOXEL_SLATE = 20
VOXEL_MARBLE = 21
VOXEL_GNEISS = 22

# Igneous rocks (deep layers)
VOXEL_GRANITE = 30
VOXEL_BASALT = 31
VOXEL_OBSIDIAN = 32

# Ores
VOXEL_IRON_ORE = 40
VOXEL_COPPER_ORE = 41
VOXEL_GOLD_ORE = 42
VOXEL_MANA_CRYSTAL = 43

# ── Liquids ──────────────────────────────────────────────────────────

VOXEL_LAVA = 50
VOXEL_WATER = 51

# Face culling: render a face if the neighbor is one of these "transparent" types
FACE_TRANSPARENT_VOXELS = frozenset({VOXEL_AIR, VOXEL_WATER, VOXEL_LAVA})

# Fluid voxel types that render as partial-height cubes
FLUID_VOXELS = frozenset({VOXEL_WATER, VOXEL_LAVA})

# ── Crafted materials ────────────────────────────────────────────────

VOXEL_IRON_INGOT = 60
VOXEL_COPPER_INGOT = 61
VOXEL_GOLD_INGOT = 62
VOXEL_ENCHANTED_METAL = 63

# ── Crafted functional blocks ────────────────────────────────────────

VOXEL_REINFORCED_WALL = 70
VOXEL_SPIKE = 71
VOXEL_DOOR = 72
VOXEL_TREASURE = 73
VOXEL_ROLLING_STONE = 74
VOXEL_TARP = 75
VOXEL_SLOPE = 76
VOXEL_STAIRS = 77

# New functional blocks (dungeon expansion)
VOXEL_GOLD_BAIT = 78
VOXEL_HEAT_BEACON = 79
VOXEL_PRESSURE_PLATE = 80
VOXEL_IRON_BARS = 81
VOXEL_FLOODGATE = 82
VOXEL_ALARM_BELL = 83
VOXEL_FRAGILE_FLOOR = 84
VOXEL_PIPE = 85
VOXEL_PUMP = 86
VOXEL_STEAM_VENT = 87

# ── Source/sink blocks (permanent world anchors) ─────────────────────

VOXEL_WATER_SOURCE = 88   # Always full (water_level=255), water flows out naturally
VOXEL_WATER_SINK = 89     # Always empty (water_level=0, humidity=0), absorbs by physics
VOXEL_LAVA_SOURCE = 90    # Always LAVA_TEMPERATURE, regenerates lava in adjacent air
VOXEL_LAVA_SINK = 91      # Always cool, absorbs adjacent lava
