"""Human-readable names for voxel types.

Dependencies: (none — pure data module)
Dependents: ui.hud, ui.object_palette
"""

from __future__ import annotations

# Map voxel type int → friendly display name.
# Kept in sync with config.py VOXEL_* constants.
VTYPE_NAMES: dict[int, str] = {
    1: "Dirt", 2: "Stone", 3: "Bedrock", 4: "Core",
    10: "Sandstone", 11: "Limestone", 12: "Shale", 13: "Chalk",
    20: "Slate", 21: "Marble", 22: "Gneiss",
    30: "Granite", 31: "Basalt", 32: "Obsidian",
    40: "Iron Ore", 41: "Copper Ore", 42: "Gold Ore", 43: "Mana Crystal",
    50: "Lava", 51: "Water",
    60: "Iron Ingot", 61: "Copper Ingot", 62: "Gold Ingot",
    63: "Enchanted Metal",
    70: "Reinforced Wall", 71: "Spike", 72: "Door", 73: "Treasure",
    74: "Rolling Stone", 75: "Tarp", 76: "Slope", 77: "Stairs",
    78: "Gold Bait", 79: "Heat Beacon", 80: "Pressure Plate",
    81: "Iron Bars", 82: "Floodgate", 83: "Alarm Bell",
    84: "Fragile Floor", 85: "Pipe", 86: "Pump", 87: "Steam Vent",
    88: "Water Source", 89: "Water Sink", 90: "Lava Source", 91: "Lava Sink",
    92: "Enchanted Door", 93: "Enchanted Floodgate",
}
