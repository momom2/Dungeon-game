"""Natural material crafting recipes (marble, ore smelting, obsidian, etc.).

Dependencies: config, building.craft_cost, building.crafting_helpers,
    building.crafting_book (CraftingRecipe)
Dependents: building.crafting_book (CraftingBook.__init__)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_MARBLE,
    VOXEL_LIMESTONE,
    VOXEL_BASALT,
    VOXEL_GRANITE,
    VOXEL_SANDSTONE,
    VOXEL_CHALK,
    VOXEL_LAVA,
    VOXEL_OBSIDIAN,
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_GOLD_INGOT,
    VOXEL_IRON_ORE,
    VOXEL_COPPER_ORE,
    VOXEL_GOLD_ORE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_ENCHANTED_METAL,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    METAL_NONE,
    METAL_IRON,
    ENCHANTED_OFFSET,
    HELD_TO_METAL,
    ORE_TO_METAL,
)
from dungeon_builder.building.crafting_helpers import (
    ORE_TO_INGOT,
    NEIGHBORS_6,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.world.voxel_grid import VoxelGrid


# ---------------------------------------------------------------------------
# Recipe implementations — natural materials
# ---------------------------------------------------------------------------

def _check_marble_wall(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Marble on air with air on one side and stone on the opposite."""
    if held_type != VOXEL_MARBLE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Check for air/stone opposing pair in XY plane
    pairs = [
        ((1, 0, 0), (-1, 0, 0)),
        ((0, 1, 0), (0, -1, 0)),
    ]
    for (dx1, dy1, dz1), (dx2, dy2, dz2) in pairs:
        n1 = grid.get(x + dx1, y + dy1, z + dz1)
        n2 = grid.get(x + dx2, y + dy2, z + dz2)
        if n1 == VOXEL_AIR and n2 != VOXEL_AIR:
            return True
        if n2 == VOXEL_AIR and n1 != VOXEL_AIR:
            return True
    return False


def _craft_marble_wall(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_MARBLE, event_bus=event_bus)
    return True


def _check_ore_smelting(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Drop ore on air where temperature > 800."""
    if held_type not in ORE_TO_INGOT:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return grid.get_temperature(x, y, z) > 800.0


def _craft_ore_smelting(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    ingot = ORE_TO_INGOT[held_type]
    metal = ORE_TO_METAL[held_type]
    grid.set(x, y, z, ingot, event_bus=event_bus)
    grid.set_metal_type(x, y, z, metal)
    grid.set_loose(x, y, z, True)
    return True


def _check_obsidian_forge(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Drop basalt on lava -> obsidian."""
    if held_type != VOXEL_BASALT:
        return False
    return grid.get(x, y, z) == VOXEL_LAVA


def _craft_obsidian_forge(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_OBSIDIAN, event_bus=event_bus)
    grid.set_loose(x, y, z, True)
    return True


def _check_mana_infusion(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Drop mana crystal on a base metal ingot near lava (within 3 blocks).

    Only base (non-enchanted) ingots can be infused.
    """
    if held_type != VOXEL_MANA_CRYSTAL:
        return False
    target = grid.get(x, y, z)
    # Only base ingots, not already-enchanted
    if target not in (VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT):
        return False
    # Check for lava within 3 blocks (voxel type or fluid lava_level)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            for dz in range(-3, 4):
                nx, ny, nz = x + dx, y + dy, z + dz
                if grid.get(nx, ny, nz) == VOXEL_LAVA:
                    return True
                if grid.in_bounds(nx, ny, nz) and grid.get_lava_level(nx, ny, nz) > 0:
                    return True
    return False


def _craft_mana_infusion(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    # Determine source metal from the ingot being enchanted
    source_metal = grid.get_metal_type(x, y, z)
    # If the ingot has no metal_type set (legacy), derive from voxel type
    if source_metal == METAL_NONE:
        target = grid.get(x, y, z)
        source_metal = HELD_TO_METAL.get(target, METAL_IRON)
    grid.set(x, y, z, VOXEL_ENCHANTED_METAL, event_bus=event_bus)
    grid.set_metal_type(x, y, z, source_metal | ENCHANTED_OFFSET)
    grid.set_loose(x, y, z, True)
    return True


def _check_stone_brick(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Drop limestone on air near a wall (any solid neighbor) -> limestone block."""
    if held_type != VOXEL_LIMESTONE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Must have at least one solid neighbor
    for dx, dy, dz in NEIGHBORS_6:
        n = grid.get(x + dx, y + dy, z + dz)
        if n != VOXEL_AIR:
            return True
    return False


def _craft_stone_brick(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_LIMESTONE, event_bus=event_bus)
    return True


def _check_glass(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Drop sandstone on air where temperature > 600 -> chalk (glass-like)."""
    if held_type != VOXEL_SANDSTONE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    return grid.get_temperature(x, y, z) > 600.0


def _craft_glass(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_CHALK, event_bus=event_bus)
    grid.set_loose(x, y, z, True)
    return True


def _check_granite_pillar(grid: VoxelGrid, x: int, y: int, z: int, held_type: int) -> bool:
    """Drop granite on air with solid below -> granite pillar.

    Does not match if below is slope/stairs (rolling stone takes priority).
    """
    if held_type != VOXEL_GRANITE:
        return False
    if grid.get(x, y, z) != VOXEL_AIR:
        return False
    # Must have solid below (z+1 = deeper), but not slope/stairs
    below = grid.get(x, y, z + 1)
    if below == VOXEL_AIR:
        return False
    if below in (VOXEL_SLOPE, VOXEL_STAIRS):
        return False
    return True


def _craft_granite_pillar(
    grid: VoxelGrid, x: int, y: int, z: int, held_type: int, event_bus: EventBus,
    **kwargs,
) -> bool:
    grid.set(x, y, z, VOXEL_GRANITE, event_bus=event_bus)
    return True


# ---------------------------------------------------------------------------
# Recipe list builder
# ---------------------------------------------------------------------------

def get_natural_recipes() -> list:
    """Return all natural material recipes in order.

    Returns a list of CraftingRecipe instances. Import is deferred to
    avoid circular dependencies (crafting_book imports this module).
    """
    from dungeon_builder.building.crafting_book import CraftingRecipe
    from dungeon_builder.building.craft_cost import RecipeIngredient

    return [
        CraftingRecipe(
            "Marble Wall",
            "Place marble against stone to build a decorative wall.",
            [RecipeIngredient(VOXEL_MARBLE)],
            0,
            _check_marble_wall,
            _craft_marble_wall,
            output_vtype=VOXEL_MARBLE,
            category="terrain",
            behavior_hint="Decorative stone wall. Higher structural strength than dirt.",
        ),
        CraftingRecipe(
            "Ore Smelting",
            "Drop ore in high heat (>800) to smelt into metal ingot.",
            [RecipeIngredient(VOXEL_IRON_ORE, substitutable=False, alternatives=frozenset({VOXEL_COPPER_ORE, VOXEL_GOLD_ORE}))],
            0,
            _check_ore_smelting,
            _craft_ore_smelting,
            output_vtype=0,  # Variable: depends on ore type
            category="crafting",
            behavior_hint="Produces a loose metal ingot. Requires temperature >800.",
        ),
        CraftingRecipe(
            "Obsidian Forge",
            "Drop basalt on lava to create obsidian.",
            [RecipeIngredient(VOXEL_BASALT)],
            0,
            _check_obsidian_forge,
            _craft_obsidian_forge,
            output_vtype=VOXEL_OBSIDIAN,
            category="crafting",
            behavior_hint="Produces loose obsidian. Requires lava contact.",
        ),
        CraftingRecipe(
            "Mana Infusion",
            "Drop mana crystal on metal ingot near lava to enchant.",
            [RecipeIngredient(VOXEL_MANA_CRYSTAL, substitutable=False)],
            0,
            _check_mana_infusion,
            _craft_mana_infusion,
            output_vtype=VOXEL_ENCHANTED_METAL,
            category="crafting",
            behavior_hint="Produces enchanted metal. Requires lava within 3 cells.",
        ),
        CraftingRecipe(
            "Stone Brick",
            "Place limestone next to a wall to build a brick.",
            [RecipeIngredient(VOXEL_LIMESTONE)],
            0,
            _check_stone_brick,
            _craft_stone_brick,
            output_vtype=VOXEL_LIMESTONE,
            category="terrain",
            behavior_hint="Solid building block. Good structural support.",
        ),
        CraftingRecipe(
            "Glass",
            "Drop sandstone in high heat (>600) to create glass.",
            [RecipeIngredient(VOXEL_SANDSTONE)],
            0,
            _check_glass,
            _craft_glass,
            output_vtype=VOXEL_CHALK,
            category="crafting",
            behavior_hint="Produces loose glass. Requires temperature >600.",
        ),
        CraftingRecipe(
            "Granite Pillar",
            "Place granite on solid ground to build a pillar.",
            [RecipeIngredient(VOXEL_GRANITE)],
            0,
            _check_granite_pillar,
            _craft_granite_pillar,
            output_vtype=VOXEL_GRANITE,
            category="terrain",
            behavior_hint="Load-bearing column. High structural strength.",
        ),
    ]
