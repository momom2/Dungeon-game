"""Functional and enchanted block crafting recipes.

Includes reinforced walls, doors, traps, pipes, enchanted variants, and
all other non-natural crafting recipes. Recipe order matters: find_recipe()
returns the first match, so ordering must be preserved from the original
crafting book.

Dependencies: config, building.craft_cost, building.crafting_helpers,
    building.crafting_book (CraftingRecipe)
Dependents: building.crafting_book (CraftingBook.__init__)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_DIRT,
    VOXEL_STONE,
    VOXEL_GRANITE,
    VOXEL_CHALK,
    VOXEL_OBSIDIAN,
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_GOLD_INGOT,
    VOXEL_ENCHANTED_METAL,
    VOXEL_REINFORCED_WALL,
    VOXEL_SPIKE,
    VOXEL_DOOR,
    VOXEL_TREASURE,
    VOXEL_ROLLING_STONE,
    VOXEL_TARP,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_PRESSURE_PLATE,
    VOXEL_IRON_BARS,
    VOXEL_FLOODGATE,
    VOXEL_ALARM_BELL,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_PIPE,
    VOXEL_PUMP,
    VOXEL_STEAM_VENT,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    METAL_NONE,
    METAL_IRON,
    METAL_COPPER,
    METAL_GOLD,
    ENCHANTED_OFFSET,
    HELD_TO_METAL,
    PIPEABLE_STONE_TYPES,
    base_metal_of,
)
from dungeon_builder.building.crafting_helpers import (
    _count_solid_sides_xy,
    _has_opposite_walls,
    _has_any_solid_neighbor,
    _has_lava_below,
    _has_adjacent_water,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid

# Alternative sets for multi-metal RecipeIngredients (canonical type excluded)
_COPPER_GOLD = frozenset({VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT})
_COPPER_GOLD_ENCHANTED = frozenset({VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT, VOXEL_ENCHANTED_METAL})
_IRON_COPPER_GOLD = frozenset({VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT})


# ---------------------------------------------------------------------------
# Functional block recipe implementations
# ---------------------------------------------------------------------------

def _check_reinforced_wall(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot on stone -> reinforced wall."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    return grid.get(x, y, z) == VOXEL_STONE


def _craft_reinforced_wall(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    grid.set(x, y, z, VOXEL_REINFORCED_WALL, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


def _check_treasure(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Gold ingot on stone -> treasure."""
    if held_type != VOXEL_GOLD_INGOT:
        return False
    return grid.get(x, y, z) == VOXEL_STONE


def _craft_treasure(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else METAL_GOLD
    grid.set(x, y, z, VOXEL_TREASURE, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


def _check_slope(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Stone on air with solid below + solid on exactly 1 side (X or Y)."""
    if held_type != VOXEL_STONE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Solid below (z+1 is deeper)
    if grid.get(x, y, z + 1) == VOXEL_AIR:
        return False
    return _count_solid_sides_xy(grid, x, y, z) == 1


def _craft_slope(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_SLOPE, event_bus=event_bus)
    return True


def _check_stairs(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Stone on air with solid below + solid on exactly 1 side + air above."""
    if held_type != VOXEL_STONE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Solid below (z+1 is deeper)
    if grid.get(x, y, z + 1) == VOXEL_AIR:
        return False
    # Air above (z-1 is shallower)
    if z == 0 or grid.get(x, y, z - 1) != VOXEL_AIR:
        return False
    return _count_solid_sides_xy(grid, x, y, z) == 1


def _craft_stairs(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_STAIRS, event_bus=event_bus)
    return True


def _check_door(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot on air between 2 opposite walls."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return _has_opposite_walls(grid, x, y, z)


def _craft_door(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    # If held type is enchanted, the metal should already have the enchanted bit
    grid.set(x, y, z, VOXEL_DOOR, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Doors start closed (state=1)
    grid.set_block_state(x, y, z, 1)
    return True


def _check_spike_trap(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot on air with solid below."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Solid below (z+1 is deeper)
    return grid.get(x, y, z + 1) != VOXEL_AIR


def _craft_spike_trap(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    grid.set(x, y, z, VOXEL_SPIKE, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Spikes start extended (state=1)
    grid.set_block_state(x, y, z, 1)
    return True


def _check_tarp(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Dirt on air between 2 opposite walls."""
    if held_type != VOXEL_DIRT:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return _has_opposite_walls(grid, x, y, z)


def _craft_tarp(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_TARP, event_bus=event_bus)
    return True


def _check_rolling_stone(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Granite on air above slope or stairs."""
    if held_type != VOXEL_GRANITE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Must have slope or stairs below (z+1 is deeper)
    below = grid.get(x, y, z + 1)
    return below in (VOXEL_SLOPE, VOXEL_STAIRS)


def _craft_rolling_stone(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_ROLLING_STONE, event_bus=event_bus)
    grid.set_loose(x, y, z, True)  # Rolling stone starts loose
    return True


# ---------------------------------------------------------------------------
# New functional block recipe implementations (IDs 78-87)
# ---------------------------------------------------------------------------

# -- Gold Bait (78) --------------------------------------------------------

def _check_gold_bait(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Enchanted metal or gold ingot on air with solid below + >=1 wall."""
    if held_type not in (VOXEL_ENCHANTED_METAL, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Must be solid below
    if grid.get(x, y, z + 1) == VOXEL_AIR:
        return False
    # Lateral support: at least 1 solid XY neighbor
    if _count_solid_sides_xy(grid, x, y, z) < 1:
        return False
    return True


def _craft_gold_bait(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    if held_metal != METAL_NONE:
        metal = held_metal
    elif held_type == VOXEL_ENCHANTED_METAL:
        metal = METAL_GOLD | ENCHANTED_OFFSET
    else:
        metal = HELD_TO_METAL.get(held_type, METAL_GOLD)
    # Gold Bait is an enchanted output — ensure enchanted bit is set
    if base_metal_of(metal) == metal:
        metal = metal | ENCHANTED_OFFSET
    # Gold bait requires gold -- validate base metal is gold
    if base_metal_of(metal) != METAL_GOLD:
        return False
    grid.set(x, y, z, VOXEL_GOLD_BAIT, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


# -- Heat Beacon (79) ------------------------------------------------------

def _check_heat_beacon(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot (enchanted or regular) on stone with temperature > 200."""
    if held_type not in (VOXEL_ENCHANTED_METAL, VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_STONE:
        return False
    return grid.get_temperature(x, y, z) > 200.0


def _craft_heat_beacon(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    if held_metal != METAL_NONE:
        metal = held_metal
    elif held_type == VOXEL_ENCHANTED_METAL:
        metal = HELD_TO_METAL.get(held_type, METAL_COPPER) | ENCHANTED_OFFSET
    else:
        metal = HELD_TO_METAL.get(held_type, METAL_COPPER)
    # Heat Beacon is an enchanted output — ensure enchanted bit is set
    if base_metal_of(metal) == metal:
        metal = metal | ENCHANTED_OFFSET
    grid.set(x, y, z, VOXEL_HEAT_BEACON, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


# -- Pressure Plate (80) ---------------------------------------------------

def _check_pressure_plate(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot (enchanted or regular) on stone with air above."""
    if held_type not in (VOXEL_ENCHANTED_METAL, VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_STONE:
        return False
    # Air above (z-1 is shallower)
    if z == 0:
        return True  # topmost layer counts as "air above"
    return grid.get(x, y, z - 1) == VOXEL_AIR


def _craft_pressure_plate(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON) | ENCHANTED_OFFSET
    grid.set(x, y, z, VOXEL_PRESSURE_PLATE, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Pressure plate starts unarmed (state=0)
    return True


# -- Iron Bars (81) --------------------------------------------------------

def _check_iron_bars(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot on air with 2 opposite walls."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return _has_opposite_walls(grid, x, y, z)


def _craft_iron_bars(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    grid.set(x, y, z, VOXEL_IRON_BARS, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


# -- Floodgate (82) --------------------------------------------------------

def _check_floodgate(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot on stone with adjacent water."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_STONE:
        return False
    return _has_adjacent_water(grid, x, y, z)


def _craft_floodgate(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    grid.set(x, y, z, VOXEL_FLOODGATE, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Floodgate starts closed (state=1)
    grid.set_block_state(x, y, z, 1)
    return True


# -- Alarm Bell (83) -------------------------------------------------------

def _check_alarm_bell(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot (enchanted or regular) on air with solid below + >=1 wall."""
    if held_type not in (VOXEL_ENCHANTED_METAL, VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Solid below
    if grid.get(x, y, z + 1) == VOXEL_AIR:
        return False
    # Lateral support
    if _count_solid_sides_xy(grid, x, y, z) < 1:
        return False
    return True


def _craft_alarm_bell(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON) | ENCHANTED_OFFSET
    grid.set(x, y, z, VOXEL_ALARM_BELL, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


# -- Fragile Floor (84) ----------------------------------------------------

def _check_fragile_floor(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Chalk on air with >=2 walls + solid below."""
    if held_type != VOXEL_CHALK:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Solid below
    if grid.get(x, y, z + 1) == VOXEL_AIR:
        return False
    # At least 2 solid sides for lateral support
    if _count_solid_sides_xy(grid, x, y, z) < 2:
        return False
    return True


def _craft_fragile_floor(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    grid.set(x, y, z, VOXEL_FRAGILE_FLOOR, event_bus=event_bus)
    # No metal_type (non-metallic)
    return True


# -- Pipe (85) -------------------------------------------------------------

def _check_pipe(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any base metal ingot on air (with solid neighbor) or non-loose stone."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    target = grid.get(x, y, z)
    if target == VOXEL_AIR:
        return _has_any_solid_neighbor(grid, x, y, z)
    # Can also build into non-loose pipeable stone
    if target in PIPEABLE_STONE_TYPES and not grid.is_loose(x, y, z):
        return True
    return False


def _craft_pipe(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    grid.set(x, y, z, VOXEL_PIPE, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    return True


# -- Pump (86) -------------------------------------------------------------

def _check_pump(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any base metal ingot on an existing pipe."""
    if held_type not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    return grid.get(x, y, z) == VOXEL_PIPE


def _craft_pump(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    metal = held_metal if held_metal != METAL_NONE else HELD_TO_METAL.get(held_type, METAL_IRON)
    grid.set(x, y, z, VOXEL_PUMP, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Pump starts with direction +X (state=0); player clicks to cycle
    grid.set_block_state(x, y, z, 0)
    return True


# -- Steam Vent (87) -------------------------------------------------------

def _check_steam_vent(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Obsidian on air with lava within 2 cells below."""
    if held_type != VOXEL_OBSIDIAN:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return _has_lava_below(grid, x, y, z, max_depth=2)


def _craft_steam_vent(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    grid.set(x, y, z, VOXEL_STEAM_VENT, event_bus=event_bus)
    # No metal_type (non-metallic, obsidian-derived)
    return True


# ---------------------------------------------------------------------------
# Enchanted functional block recipe implementations (IDs 92-93)
# ---------------------------------------------------------------------------

# -- Enchanted Door (92) ---------------------------------------------------

def _check_enchanted_door(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot (enchanted or regular) on air between 2 opposite walls."""
    if held_type not in (VOXEL_ENCHANTED_METAL, VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return _has_opposite_walls(grid, x, y, z)


def _craft_enchanted_door(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    if held_metal != METAL_NONE:
        metal = held_metal
    elif held_type == VOXEL_ENCHANTED_METAL:
        metal = HELD_TO_METAL.get(held_type, METAL_IRON) | ENCHANTED_OFFSET
    else:
        metal = HELD_TO_METAL.get(held_type, METAL_IRON)
    # Enchanted Door is an enchanted output — ensure enchanted bit is set
    if base_metal_of(metal) == metal:
        metal = metal | ENCHANTED_OFFSET
    grid.set(x, y, z, VOXEL_ENCHANTED_DOOR, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Enchanted doors start closed (state=1)
    grid.set_block_state(x, y, z, 1)
    return True


# -- Enchanted Floodgate (93) ----------------------------------------------

def _check_enchanted_floodgate(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Any metal ingot (enchanted or regular) on stone with adjacent water."""
    if held_type not in (VOXEL_ENCHANTED_METAL, VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    if grid.get(x, y, z) != VOXEL_STONE:
        return False
    return _has_adjacent_water(grid, x, y, z)


def _craft_enchanted_floodgate(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    held_metal: int = METAL_NONE,
) -> bool:
    if held_metal != METAL_NONE:
        metal = held_metal
    elif held_type == VOXEL_ENCHANTED_METAL:
        metal = HELD_TO_METAL.get(held_type, METAL_IRON) | ENCHANTED_OFFSET
    else:
        metal = HELD_TO_METAL.get(held_type, METAL_IRON)
    # Enchanted Floodgate is an enchanted output — ensure enchanted bit is set
    if base_metal_of(metal) == metal:
        metal = metal | ENCHANTED_OFFSET
    grid.set(x, y, z, VOXEL_ENCHANTED_FLOODGATE, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    # Enchanted floodgate starts closed (state=1)
    grid.set_block_state(x, y, z, 1)
    return True


# ---------------------------------------------------------------------------
# Recipe list builder
# ---------------------------------------------------------------------------

def get_functional_recipes() -> list:
    """Return all functional and enchanted block recipes in order.

    Recipe ordering is critical: find_recipe() returns the first match.
    The order here must match the original crafting book.

    Returns a list of CraftingRecipe instances. Import is deferred to
    avoid circular dependencies (crafting_book imports this module).
    """
    from dungeon_builder.building.crafting_book import CraftingRecipe
    from dungeon_builder.building.craft_cost import RecipeIngredient

    return [
        # --- Terrain / structural ---
        CraftingRecipe(
            "Reinforced Wall",
            "Apply metal ingot to stone to reinforce it.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_reinforced_wall,
            _craft_reinforced_wall,
            output_vtype=VOXEL_REINFORCED_WALL,
            category="barriers",
            behavior_hint="Increases structural strength. Metal type affects resistance.",
        ),
        CraftingRecipe(
            "Treasure",
            "Apply gold ingot to stone to create a treasure.",
            [RecipeIngredient(VOXEL_GOLD_INGOT, substitutable=False)],
            0,
            _check_treasure,
            _craft_treasure,
            output_vtype=VOXEL_TREASURE,
            category="terrain",
            behavior_hint="Attracts intruders. Lure for entertainment and soul capture.",
        ),
        CraftingRecipe(
            "Slope",
            "Place on air with solid below and one wall.",
            [RecipeIngredient(VOXEL_STONE)],
            0,
            _check_slope,
            _craft_slope,
            output_vtype=VOXEL_SLOPE,
            category="terrain",
            behavior_hint="Angled surface. Rolling stones travel down slopes.",
        ),
        CraftingRecipe(
            "Stairs",
            "Place on air with solid below, one wall, and air above.",
            [RecipeIngredient(VOXEL_STONE)],
            0,
            _check_stairs,
            _craft_stairs,
            output_vtype=VOXEL_STAIRS,
            category="terrain",
            behavior_hint="Walkable vertical connection between levels.",
        ),
        CraftingRecipe(
            "Door",
            "Place metal ingot between two opposite walls.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_door,
            _craft_door,
            output_vtype=VOXEL_DOOR,
            category="barriers",
            behavior_hint="Click to open/close. Blocks intruder movement when closed.",
        ),
        CraftingRecipe(
            "Spike Trap",
            "Place on floor. Deals piercing damage when stepped on.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_spike_trap,
            _craft_spike_trap,
            output_vtype=VOXEL_SPIKE,
            category="traps",
            behavior_hint="Deals damage when an intruder steps on it.",
        ),
        CraftingRecipe(
            "Tarp",
            "Stretch between two opposite walls to disguise a pit.",
            [RecipeIngredient(VOXEL_DIRT)],
            0,
            _check_tarp,
            _craft_tarp,
            output_vtype=VOXEL_TARP,
            category="traps",
            behavior_hint="Conceals the gap below. Breaks when stepped on.",
        ),
        CraftingRecipe(
            "Rolling Stone",
            "Place granite above a slope or stairs.",
            [RecipeIngredient(VOXEL_GRANITE)],
            0,
            _check_rolling_stone,
            _craft_rolling_stone,
            output_vtype=VOXEL_ROLLING_STONE,
            category="traps",
            behavior_hint="Rolls downhill on slopes. Damages intruders in its path.",
        ),
        # --- Enchanted / mana-powered ---
        CraftingRecipe(
            "Gold Bait",
            "Place in air with floor and wall to lure intruders.",
            [RecipeIngredient(VOXEL_GOLD_INGOT, substitutable=False, alternatives=frozenset({VOXEL_ENCHANTED_METAL}))],
            20,
            _check_gold_bait,
            _craft_gold_bait,
            output_vtype=VOXEL_GOLD_BAIT,
            category="enchanted",
            effect_radius=6,
            behavior_hint="Lures intruders from up to 6 cells away.",
        ),
        CraftingRecipe(
            "Heat Beacon",
            "Apply metal ingot to hot stone (>200) to create a heat source.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD_ENCHANTED)],
            25,
            _check_heat_beacon,
            _craft_heat_beacon,
            output_vtype=VOXEL_HEAT_BEACON,
            category="thermal",
            effect_radius=3,
            behavior_hint="Radiates heat in a 3-cell radius. Can cause thermal stress.",
        ),
        CraftingRecipe(
            "Pressure Plate",
            "Apply metal ingot to stone with air above.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD_ENCHANTED)],
            15,
            _check_pressure_plate,
            _craft_pressure_plate,
            output_vtype=VOXEL_PRESSURE_PLATE,
            category="enchanted",
            effect_radius=1,
            behavior_hint="Triggers linked enchanted doors and floodgates when stepped on.",
        ),
        CraftingRecipe(
            "Iron Bars",
            "Place metal ingot between opposite walls.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_iron_bars,
            _craft_iron_bars,
            output_vtype=VOXEL_IRON_BARS,
            category="barriers",
            behavior_hint="Blocks intruder movement. Allows vision and fluid flow.",
        ),
        CraftingRecipe(
            "Floodgate",
            "Apply metal ingot to stone near water.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_floodgate,
            _craft_floodgate,
            output_vtype=VOXEL_FLOODGATE,
            category="barriers",
            behavior_hint="Click to open/close. Controls water flow.",
        ),
        CraftingRecipe(
            "Alarm Bell",
            "Place metal ingot in air with floor and wall.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD_ENCHANTED)],
            20,
            _check_alarm_bell,
            _craft_alarm_bell,
            output_vtype=VOXEL_ALARM_BELL,
            category="enchanted",
            effect_radius=2,
            behavior_hint="Detects intruders within 2 cells. Alerts connected traps.",
        ),
        CraftingRecipe(
            "Enchanted Door",
            "Place metal ingot between walls for a signal-responsive door.",
            [RecipeIngredient(VOXEL_ENCHANTED_METAL, alternatives=_IRON_COPPER_GOLD)],
            20,
            _check_enchanted_door,
            _craft_enchanted_door,
            output_vtype=VOXEL_ENCHANTED_DOOR,
            category="enchanted",
            behavior_hint="Opens/closes via pressure plate signal. Mana-powered.",
        ),
        CraftingRecipe(
            "Enchanted Floodgate",
            "Apply metal ingot to stone near water for a signal-responsive gate.",
            [RecipeIngredient(VOXEL_ENCHANTED_METAL, alternatives=_IRON_COPPER_GOLD)],
            20,
            _check_enchanted_floodgate,
            _craft_enchanted_floodgate,
            output_vtype=VOXEL_ENCHANTED_FLOODGATE,
            category="enchanted",
            behavior_hint="Opens/closes via pressure plate signal. Controls water flow.",
        ),
        CraftingRecipe(
            "Fragile Floor",
            "Place chalk in air with floor and 2+ walls.",
            [RecipeIngredient(VOXEL_CHALK)],
            0,
            _check_fragile_floor,
            _craft_fragile_floor,
            output_vtype=VOXEL_FRAGILE_FLOOR,
            category="traps",
            behavior_hint="Looks solid. Collapses under weight.",
        ),
        CraftingRecipe(
            "Pipe",
            "Place metal ingot in air or stone to build pipe.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_pipe,
            _craft_pipe,
            output_vtype=VOXEL_PIPE,
            category="plumbing",
            behavior_hint="Carries water/lava. Connects to adjacent pipes.",
        ),
        CraftingRecipe(
            "Pump",
            "Place metal ingot on a pipe to drive flow.",
            [RecipeIngredient(VOXEL_IRON_INGOT, alternatives=_COPPER_GOLD)],
            0,
            _check_pump,
            _craft_pump,
            output_vtype=VOXEL_PUMP,
            category="plumbing",
            behavior_hint="Click to change direction. Drives fluid through pipe network.",
        ),
        CraftingRecipe(
            "Steam Vent",
            "Place obsidian in air above lava.",
            [RecipeIngredient(VOXEL_OBSIDIAN)],
            0,
            _check_steam_vent,
            _craft_steam_vent,
            output_vtype=VOXEL_STEAM_VENT,
            category="thermal",
            effect_radius=3,
            behavior_hint="Produces steam column. Damages and obscures vision.",
        ),
    ]
