"""Rendering constants — colours, render modes, fog, ore glow, vertex noise.

Dependencies: config.voxels
Dependents: config.__init__, rendering.voxel_renderer, rendering.effects,
            rendering.intruder_renderer, ui.render_mode_selector
"""

from .voxels import (
    VOXEL_ALARM_BELL,
    VOXEL_BASALT,
    VOXEL_BEDROCK,
    VOXEL_CHALK,
    VOXEL_COPPER_INGOT,
    VOXEL_COPPER_ORE,
    VOXEL_CORE,
    VOXEL_DIRT,
    VOXEL_DOOR,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
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

# ── Render modes ─────────────────────────────────────────────────────

RENDER_MODE_MATTER = "matter"
RENDER_MODE_HUMIDITY = "humidity"
RENDER_MODE_HEAT = "heat"
RENDER_MODE_STRUCTURAL = "structural"
RENDER_MODE_PROSPECTING = "prospecting"

# ── Ore glow marker colours (Prospecting mode — x-ray visible ores) ──

ORE_GLOW_COLORS: dict[int, tuple[float, float, float, float]] = {
    VOXEL_IRON_ORE:     (0.60, 0.35, 0.25, 0.40),   # rusty orange
    VOXEL_COPPER_ORE:   (0.45, 0.65, 0.50, 0.40),   # greenish copper
    VOXEL_GOLD_ORE:     (0.95, 0.85, 0.20, 0.45),   # bright gold
    VOXEL_MANA_CRYSTAL: (0.55, 0.30, 0.85, 0.45),   # purple glow
}

# ── Fog of war ───────────────────────────────────────────────────────

FOG_COLOR = (0.03, 0.03, 0.04, 1.0)  # Near-black for unexplored blocks

# ── Ore / crystal x-ray visibility ───────────────────────────────────

PLAYER_XRAY_RANGE = 3  # mutable, future spells/upgrades increase this
XRAY_VISIBLE_TYPES = frozenset({
    VOXEL_IRON_ORE, VOXEL_COPPER_ORE, VOXEL_GOLD_ORE, VOXEL_MANA_CRYSTAL,
})

# ── Mana-lava rendering tint ─────────────────────────────────────────

MANA_LAVA_COLOR = (1.0, 0.35, 0.15, 1.0)

# ── Colours per voxel type (RGBA floats) ─────────────────────────────

VOXEL_COLORS = {
    VOXEL_DIRT: (0.55, 0.35, 0.17, 1.0),
    VOXEL_STONE: (0.5, 0.5, 0.5, 1.0),
    VOXEL_BEDROCK: (0.2, 0.2, 0.2, 1.0),
    VOXEL_CORE: (0.8, 0.1, 0.1, 1.0),
    VOXEL_SANDSTONE: (0.85, 0.75, 0.50, 1.0),
    VOXEL_LIMESTONE: (0.80, 0.80, 0.72, 1.0),
    VOXEL_SHALE: (0.40, 0.40, 0.45, 1.0),
    VOXEL_CHALK: (0.92, 0.91, 0.88, 1.0),
    VOXEL_SLATE: (0.45, 0.50, 0.55, 1.0),
    VOXEL_MARBLE: (0.90, 0.88, 0.85, 1.0),
    VOXEL_GNEISS: (0.55, 0.50, 0.48, 1.0),
    VOXEL_GRANITE: (0.65, 0.62, 0.60, 1.0),
    VOXEL_BASALT: (0.30, 0.30, 0.33, 1.0),
    VOXEL_OBSIDIAN: (0.10, 0.08, 0.12, 1.0),
    VOXEL_IRON_ORE: (0.60, 0.35, 0.25, 1.0),
    VOXEL_COPPER_ORE: (0.45, 0.65, 0.50, 1.0),
    VOXEL_GOLD_ORE: (0.85, 0.75, 0.20, 1.0),
    VOXEL_MANA_CRYSTAL: (0.55, 0.30, 0.85, 1.0),
    VOXEL_LAVA: (1.0, 0.30, 0.0, 1.0),
    VOXEL_WATER: (0.15, 0.40, 0.85, 0.7),
    VOXEL_IRON_INGOT: (0.70, 0.55, 0.50, 1.0),
    VOXEL_COPPER_INGOT: (0.75, 0.50, 0.30, 1.0),
    VOXEL_GOLD_INGOT: (0.95, 0.85, 0.30, 1.0),
    VOXEL_ENCHANTED_METAL: (0.40, 0.60, 0.90, 1.0),
    VOXEL_REINFORCED_WALL: (0.50, 0.52, 0.55, 1.0),   # steel gray
    VOXEL_SPIKE: (0.35, 0.30, 0.28, 1.0),              # dark metallic
    VOXEL_DOOR: (0.45, 0.35, 0.25, 1.0),               # wood/metal
    VOXEL_TREASURE: (0.95, 0.85, 0.20, 1.0),            # bright gold
    VOXEL_ROLLING_STONE: (0.60, 0.58, 0.55, 1.0),       # granite-like
    VOXEL_TARP: (0.65, 0.55, 0.35, 0.8),                # semi-transparent brown
    VOXEL_SLOPE: (0.55, 0.53, 0.50, 1.0),               # stone with slight warmth
    VOXEL_STAIRS: (0.58, 0.55, 0.52, 1.0),              # stone, slightly lighter
    VOXEL_GOLD_BAIT: (0.95, 0.85, 0.20, 1.0),         # same as treasure (deception!)
    VOXEL_HEAT_BEACON: (0.85, 0.45, 0.15, 1.0),       # glowing orange-copper
    VOXEL_PRESSURE_PLATE: (0.45, 0.45, 0.48, 1.0),    # dark steel (base, tinted by metal)
    VOXEL_IRON_BARS: (0.50, 0.50, 0.55, 0.7),         # semi-transparent metal
    VOXEL_FLOODGATE: (0.40, 0.50, 0.65, 1.0),         # blue-steel (base, tinted by metal)
    VOXEL_ENCHANTED_DOOR: (0.35, 0.25, 0.55, 1.0),       # purple-tinted
    VOXEL_ENCHANTED_FLOODGATE: (0.30, 0.40, 0.70, 1.0),   # deep blue
    VOXEL_ALARM_BELL: (0.80, 0.70, 0.30, 1.0),        # brass (base, tinted by metal)
    VOXEL_FRAGILE_FLOOR: (0.5, 0.5, 0.5, 1.0),        # same as stone (deception!)
    VOXEL_PIPE: (0.72, 0.52, 0.35, 0.9),              # copper-ish (base, tinted by metal)
    VOXEL_PUMP: (0.55, 0.55, 0.60, 1.0),              # iron-ish (base, tinted by metal)
    VOXEL_STEAM_VENT: (0.15, 0.12, 0.18, 0.8),        # dark obsidian, semi-transparent
    VOXEL_WATER_SOURCE: (0.9, 0.1, 0.1, 1.0),          # bright red (water origin)
    VOXEL_WATER_SINK: (0.7, 0.0, 0.0, 1.0),            # dark red (water drain)
    VOXEL_LAVA_SOURCE: (1.0, 0.4, 0.0, 0.9),           # bright orange (lava origin)
    VOXEL_LAVA_SINK: (0.6, 0.2, 0.0, 0.9),             # dark red-brown (lava drain)
}

# ── Vertex noise: per-material colour grain amplitude ────────────────

VERTEX_NOISE_AMPLITUDE = 0.07  # Default amplitude (0.0 = flat, 0.1 = subtle)

VOXEL_NOISE: dict[int, float] = {
    VOXEL_DIRT: 0.10,           # Rough, earthy
    VOXEL_STONE: 0.06,          # Moderate grain
    VOXEL_SANDSTONE: 0.09,      # Sandy variation
    VOXEL_LIMESTONE: 0.05,      # Smooth-ish
    VOXEL_SHALE: 0.07,          # Layered
    VOXEL_CHALK: 0.04,          # Powdery, smooth
    VOXEL_SLATE: 0.06,          # Layered stone
    VOXEL_MARBLE: 0.12,         # Veined (high variation)
    VOXEL_GNEISS: 0.08,         # Banded
    VOXEL_GRANITE: 0.08,        # Speckled
    VOXEL_BASALT: 0.05,         # Dense, smooth
    VOXEL_OBSIDIAN: 0.03,       # Glassy, smooth
    VOXEL_LAVA: 0.12,           # Roiling surface
    VOXEL_WATER: 0.04,          # Gentle ripple
    VOXEL_MANA_CRYSTAL: 0.10,   # Glowing facets
    VOXEL_GOLD_BAIT: 0.04,      # smooth metallic
    VOXEL_HEAT_BEACON: 0.05,    # glowing variation
    VOXEL_PRESSURE_PLATE: 0.03, # machined metal
    VOXEL_IRON_BARS: 0.03,      # uniform bars
    VOXEL_FLOODGATE: 0.03,      # machined metal
    VOXEL_ENCHANTED_DOOR: 0.03,      # machined enchanted metal
    VOXEL_ENCHANTED_FLOODGATE: 0.03, # machined enchanted metal
    VOXEL_ALARM_BELL: 0.03,     # polished bell
    VOXEL_FRAGILE_FLOOR: 0.06,  # same as stone (deception)
    VOXEL_PIPE: 0.03,           # smooth tube
    VOXEL_PUMP: 0.04,           # mechanical
    VOXEL_STEAM_VENT: 0.03,     # glassy
    VOXEL_WATER_SOURCE: 0.08,   # shimmering
    VOXEL_WATER_SINK: 0.05,     # subtle swirl
    VOXEL_LAVA_SOURCE: 0.12,    # roiling
    VOXEL_LAVA_SINK: 0.06,      # cooling crust
}

# ── Craft placement visual feedback ────────────────────────────────────

CRAFT_HOVER_VALID_COLOR = (0.2, 0.9, 0.3, 0.85)   # Green wireframe on valid pos
CRAFT_GHOST_OPACITY = 0.40                          # Semi-transparent ghost preview
CRAFT_FLASH_DURATION = 0.3                          # Seconds for placement flash
CRAFT_FLASH_COLOR = (0.9, 1.0, 0.9, 0.8)           # Bright white-green pulse
