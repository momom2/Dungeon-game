"""Tests for the crafting system (highlight-mode state machine) and new block recipes."""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.game_state import GameState
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.building.move_system import MoveSystem
from dungeon_builder.building.crafting_system import CraftingSystem
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_DIRT,
    VOXEL_STONE,
    VOXEL_MARBLE,
    VOXEL_LIMESTONE,
    VOXEL_BASALT,
    VOXEL_GRANITE,
    VOXEL_SANDSTONE,
    VOXEL_CHALK,
    VOXEL_LAVA,
    VOXEL_WATER,
    VOXEL_OBSIDIAN,
    VOXEL_IRON_ORE,
    VOXEL_COPPER_ORE,
    VOXEL_IRON_INGOT,
    VOXEL_COPPER_INGOT,
    VOXEL_GOLD_INGOT,
    VOXEL_MANA_CRYSTAL,
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
    METAL_NONE,
    METAL_IRON,
    METAL_COPPER,
    METAL_GOLD,
    METAL_ENCH_IRON,
    METAL_ENCH_COPPER,
    METAL_ENCH_GOLD,
    ENCHANTED_OFFSET,
    DEFAULT_SEED,
)


def _setup(width=8, depth=8, height=8):
    bus = EventBus()
    grid = VoxelGrid(width=width, depth=depth, height=height)
    # Mark all blocks visible and claimed so territory checks don't interfere
    grid.visible[:] = True
    grid.claimed[:] = True
    gs = GameState(DEFAULT_SEED)
    gs.event_bus = bus
    ms = MoveSystem(bus, grid, gs)
    cs = CraftingSystem(bus, grid, ms, gs)
    gs.build_system = None
    gs.move_system = ms
    return bus, grid, ms, cs, gs


def _craft(bus, cs, recipe_name, x, y, z):
    """Helper: set z-level, select recipe, then craft at position. Returns success events."""
    successes = []
    bus.subscribe("craft_success", lambda **kw: successes.append(kw))

    # Ensure the crafting system scans at the target z-level
    cs._current_z = z
    bus.publish("craft_recipe_selected", recipe_name=recipe_name)
    bus.publish("craft_at_position", x=x, y=y, z=z)
    return successes


# ---------------------------------------------------------------------------
# Original recipe tests (7 existing recipes)
# ---------------------------------------------------------------------------


def test_marble_wall():
    """Marble on air with stone behind -> marble wall."""
    bus, grid, ms, cs, gs = _setup()
    # Stone on one side, air on the other
    grid.grid[3, 4, 4] = VOXEL_STONE  # west neighbor
    # (4,4,4) is air, (5,4,4) is air
    ms.held_materials = {VOXEL_MARBLE: 1}

    successes = _craft(bus, cs, "Marble Wall", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Marble Wall"
    assert grid.get(4, 4, 4) == VOXEL_MARBLE
    assert not ms.has_material(VOXEL_MARBLE)


def test_ore_smelting():
    """Iron ore on air with high temperature -> iron ingot."""
    bus, grid, ms, cs, gs = _setup()
    grid.temperature[4, 4, 4] = 900.0  # hot enough
    ms.held_materials = {VOXEL_IRON_ORE: 2}

    successes = _craft(bus, cs, "Ore Smelting", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_IRON_INGOT
    assert grid.is_loose(4, 4, 4)
    # Should have 1 remaining
    assert ms.held_materials == {VOXEL_IRON_ORE: 1}


def test_ore_smelting_too_cold():
    """Ore in low temperature -> no valid positions."""
    bus, grid, ms, cs, gs = _setup()
    grid.temperature[4, 4, 4] = 100.0  # not hot enough
    ms.held_materials = {VOXEL_IRON_ORE: 1}

    bus.publish("craft_recipe_selected", recipe_name="Ore Smelting")

    # Craft mode entered but no highlighted positions at z=4
    # (The position (4,4,4) doesn't satisfy the temperature check)
    # Trying to craft there should cancel (not in highlighted set)
    highlights = []
    bus.subscribe("craft_highlights_updated", lambda **kw: highlights.append(kw))

    # Set z-level to scan at z=4
    cs._current_z = 4
    cs._scan_and_highlight(4)

    # No valid positions at this z-level with low temperature
    assert len(cs._highlighted_positions) == 0


def test_obsidian_forge():
    """Basalt on lava -> obsidian."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_LAVA
    ms.held_materials = {VOXEL_BASALT: 1}

    successes = _craft(bus, cs, "Obsidian Forge", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_OBSIDIAN
    assert grid.is_loose(4, 4, 4)


def test_mana_infusion():
    """Mana crystal on iron ingot near lava -> enchanted metal."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_IRON_INGOT
    grid.grid[6, 4, 4] = VOXEL_LAVA  # within 3 blocks
    ms.held_materials = {VOXEL_MANA_CRYSTAL: 1}

    successes = _craft(bus, cs, "Mana Infusion", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_ENCHANTED_METAL


def test_mana_infusion_no_lava_nearby():
    """Mana crystal on ingot without lava nearby -> not in highlights."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_IRON_INGOT
    ms.held_materials = {VOXEL_MANA_CRYSTAL: 1}

    bus.publish("craft_recipe_selected", recipe_name="Mana Infusion")

    # Position (4,4,4) should NOT be in highlights since no lava nearby
    cs._current_z = 4
    cs._scan_and_highlight(4)
    assert (4, 4, 4) not in cs._highlighted_positions


def test_stone_brick():
    """Limestone on air near a wall -> limestone block."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[3, 4, 4] = VOXEL_STONE  # neighboring wall
    ms.held_materials = {VOXEL_LIMESTONE: 1}

    successes = _craft(bus, cs, "Stone Brick", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_LIMESTONE


def test_glass():
    """Sandstone on hot air -> chalk (glass)."""
    bus, grid, ms, cs, gs = _setup()
    grid.temperature[4, 4, 4] = 700.0
    ms.held_materials = {VOXEL_SANDSTONE: 1}

    successes = _craft(bus, cs, "Glass", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_CHALK


def test_granite_pillar():
    """Granite on air above solid ground -> granite pillar."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
    ms.held_materials = {VOXEL_GRANITE: 1}

    successes = _craft(bus, cs, "Granite Pillar", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_GRANITE


# ---------------------------------------------------------------------------
# Functional block recipe tests (8 new recipes)
# ---------------------------------------------------------------------------


def test_reinforced_wall():
    """Iron ingot on stone -> reinforced wall."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    successes = _craft(bus, cs, "Reinforced Wall", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Reinforced Wall"
    assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
    assert not ms.has_material(VOXEL_IRON_INGOT)


def test_reinforced_wall_wrong_target():
    """Iron ingot on dirt -> not in highlights (must be stone)."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_DIRT
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

    cs._current_z = 4
    cs._scan_and_highlight(4)
    # Dirt is not a valid target for Reinforced Wall
    assert (4, 4, 4) not in cs._highlighted_positions
    # Material still held
    assert ms.held_materials == {VOXEL_IRON_INGOT: 1}


def test_treasure():
    """Gold ingot on stone -> treasure."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_GOLD_INGOT: 1}

    successes = _craft(bus, cs, "Treasure", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Treasure"
    assert grid.get(4, 4, 4) == VOXEL_TREASURE


def test_spike_trap():
    """Iron ingot on air with solid below -> spike with state=1 (extended)."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    successes = _craft(bus, cs, "Spike Trap", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Spike Trap"
    assert grid.get(4, 4, 4) == VOXEL_SPIKE
    assert grid.get_block_state(4, 4, 4) == 1  # extended


def test_spike_trap_no_floor():
    """Iron ingot on air, air below -> not in highlights."""
    bus, grid, ms, cs, gs = _setup()
    # No solid below (4,4,5) is air
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    bus.publish("craft_recipe_selected", recipe_name="Spike Trap")
    cs._current_z = 4
    cs._scan_and_highlight(4)

    assert (4, 4, 4) not in cs._highlighted_positions


def test_door():
    """Metal ingot on air between two opposite walls -> door (closed)."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[3, 4, 4] = VOXEL_STONE  # -X wall
    grid.grid[5, 4, 4] = VOXEL_STONE  # +X wall
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    successes = _craft(bus, cs, "Door", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Door"
    assert grid.get(4, 4, 4) == VOXEL_DOOR
    assert grid.get_block_state(4, 4, 4) == 1  # closed


def test_door_no_opposite_walls():
    """Metal ingot with only one wall -> not in highlights."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[3, 4, 4] = VOXEL_STONE  # only -X wall, no +X wall
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    bus.publish("craft_recipe_selected", recipe_name="Door")
    cs._current_z = 4
    cs._scan_and_highlight(4)

    assert (4, 4, 4) not in cs._highlighted_positions


def test_tarp():
    """Dirt on air between two opposite walls -> tarp."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 3, 4] = VOXEL_STONE  # -Y wall
    grid.grid[4, 5, 4] = VOXEL_STONE  # +Y wall
    ms.held_materials = {VOXEL_DIRT: 1}

    successes = _craft(bus, cs, "Tarp", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Tarp"
    assert grid.get(4, 4, 4) == VOXEL_TARP


def test_tarp_one_wall():
    """Dirt on air with only one wall -> not in highlights."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 3, 4] = VOXEL_STONE  # only -Y wall
    ms.held_materials = {VOXEL_DIRT: 1}

    bus.publish("craft_recipe_selected", recipe_name="Tarp")
    cs._current_z = 4
    cs._scan_and_highlight(4)

    assert (4, 4, 4) not in cs._highlighted_positions


def test_slope():
    """Stone on air with solid below and one solid side -> slope.

    Block above is solid to prevent stairs from also matching.
    """
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
    grid.grid[3, 4, 4] = VOXEL_STONE  # one solid side (-X)
    grid.grid[4, 4, 3] = VOXEL_STONE  # solid above (blocks stairs, slope-only)
    ms.held_materials = {VOXEL_STONE: 1}

    successes = _craft(bus, cs, "Slope", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Slope"
    assert grid.get(4, 4, 4) == VOXEL_SLOPE


def test_stairs():
    """Stone on air with solid below, one side, air above -> stairs via explicit recipe selection."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
    grid.grid[3, 4, 4] = VOXEL_STONE  # one solid side (-X)
    # z=3 is above z=4 (shallower), ensure it's air (default)
    ms.held_materials = {VOXEL_STONE: 1}

    # With the new system, the player explicitly selects "Stairs" from the panel
    successes = _craft(bus, cs, "Stairs", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Stairs"
    assert grid.get(4, 4, 4) == VOXEL_STAIRS


def test_stairs_blocked_above():
    """Stone on air with solid below and side but solid above -> only slope valid (not stairs)."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
    grid.grid[3, 4, 4] = VOXEL_STONE  # one solid side (-X)
    grid.grid[4, 4, 3] = VOXEL_STONE  # solid above -> blocks stairs

    ms.held_materials = {VOXEL_STONE: 1}

    # Stairs should not be valid at this position
    bus.publish("craft_recipe_selected", recipe_name="Stairs")
    cs._current_z = 4
    cs._scan_and_highlight(4)

    assert (4, 4, 4) not in cs._highlighted_positions

    # But slope works
    bus.publish("craft_cancel")
    successes = _craft(bus, cs, "Slope", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Slope"
    assert grid.get(4, 4, 4) == VOXEL_SLOPE


def test_rolling_stone():
    """Granite on air above slope -> rolling stone (loose)."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_SLOPE  # slope below
    ms.held_materials = {VOXEL_GRANITE: 1}

    successes = _craft(bus, cs, "Rolling Stone", 4, 4, 4)

    assert len(successes) == 1
    assert successes[0]["recipe"] == "Rolling Stone"
    assert grid.get(4, 4, 4) == VOXEL_ROLLING_STONE
    assert grid.is_loose(4, 4, 4)


def test_rolling_stone_above_stairs():
    """Granite on air above stairs -> rolling stone."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STAIRS  # stairs below
    ms.held_materials = {VOXEL_GRANITE: 1}

    successes = _craft(bus, cs, "Rolling Stone", 4, 4, 4)

    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_ROLLING_STONE


def test_rolling_stone_no_slope():
    """Granite on air above regular stone -> granite pillar, NOT rolling stone."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # regular stone below (not slope/stairs)
    ms.held_materials = {VOXEL_GRANITE: 1}

    # Rolling Stone requires slope/stairs below — should not be in highlights
    bus.publish("craft_recipe_selected", recipe_name="Rolling Stone")
    cs._current_z = 4
    cs._scan_and_highlight(4)
    assert (4, 4, 4) not in cs._highlighted_positions

    # But Granite Pillar matches
    bus.publish("craft_cancel")
    successes = _craft(bus, cs, "Granite Pillar", 4, 4, 4)
    assert len(successes) == 1
    assert successes[0]["recipe"] == "Granite Pillar"
    assert grid.get(4, 4, 4) == VOXEL_GRANITE


# ---------------------------------------------------------------------------
# Highlight-mode state machine tests
# ---------------------------------------------------------------------------


def test_recipe_selection_enters_craft_mode():
    """Selecting a recipe enters craft mode with highlights."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    mode_events = []
    highlight_events = []
    bus.subscribe("craft_mode_entered", lambda **kw: mode_events.append(kw))
    bus.subscribe("craft_highlights_updated", lambda **kw: highlight_events.append(kw))

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

    assert gs.craft_mode_active is True
    assert cs.is_craft_mode_active is True
    assert len(mode_events) == 1
    assert mode_events[0]["recipe_name"] == "Reinforced Wall"
    assert len(highlight_events) >= 1


def test_craft_cancel_exits_mode():
    """Cancelling clears highlights and exits craft mode."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
    assert gs.craft_mode_active is True

    exit_events = []
    clear_events = []
    bus.subscribe("craft_mode_exited", lambda **kw: exit_events.append(kw))
    bus.subscribe("craft_highlights_cleared", lambda **kw: clear_events.append(kw))

    bus.publish("craft_cancel")

    assert gs.craft_mode_active is False
    assert cs.is_craft_mode_active is False
    assert len(exit_events) == 1
    assert len(clear_events) == 1


def test_click_non_highlighted_stays_in_craft_mode():
    """Clicking a non-highlighted position warns but stays in craft mode."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
    assert gs.craft_mode_active is True

    errors = []
    bus.subscribe("error_message", lambda **kw: errors.append(kw))

    # Click a position that's NOT highlighted (0,0,0) is air, not a valid target
    bus.publish("craft_at_position", x=0, y=0, z=0)

    # Should stay in craft mode with an error message
    assert gs.craft_mode_active is True
    assert cs.is_craft_mode_active is True
    assert len(errors) == 1
    assert "cannot craft" in errors[0]["text"].lower()


def test_material_depleted_exits_craft_mode():
    """When material runs out after crafting, craft mode exits automatically."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}  # exactly 1

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
    bus.publish("craft_at_position", x=4, y=4, z=4)

    # Should have exited craft mode since iron is depleted
    assert gs.craft_mode_active is False
    assert not ms.has_material(VOXEL_IRON_INGOT)


def test_toggle_same_recipe_exits():
    """Selecting the same recipe again exits craft mode."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
    assert gs.craft_mode_active is True

    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
    assert gs.craft_mode_active is False


def test_no_matching_material_no_mana_error():
    """Selecting a substitutable recipe without material or mana is rejected."""
    bus, grid, ms, cs, gs = _setup()
    ms.held_materials = {VOXEL_STONE: 1}  # no iron ingot, no mana system

    errors = []
    bus.subscribe("error_message", lambda **kw: errors.append(kw))

    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

    assert len(errors) == 1
    assert "mana" in errors[0]["text"].lower()
    assert gs.craft_mode_active is False


def test_z_level_change_rescans():
    """Changing z-level while in craft mode rescans highlights."""
    bus, grid, ms, cs, gs = _setup()
    # Set up valid position at z=4
    grid.grid[4, 4, 4] = VOXEL_STONE
    # Set up valid position at z=2
    grid.grid[4, 4, 2] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 2}

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

    # Change z-level
    highlight_events = []
    bus.subscribe("craft_highlights_updated", lambda **kw: highlight_events.append(kw))

    bus.publish("z_level_changed", z=2)

    assert len(highlight_events) >= 1
    # Should have scanned z=2 and found the stone there
    assert (4, 4, 2) in cs._highlighted_positions


def test_multiple_crafts_in_sequence():
    """Can craft multiple times in a row from the same recipe selection."""
    bus, grid, ms, cs, gs = _setup()
    # Two stone blocks
    grid.grid[4, 4, 4] = VOXEL_STONE
    grid.grid[5, 5, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 2}

    successes = []
    bus.subscribe("craft_success", lambda **kw: successes.append(kw))

    cs._current_z = 4
    bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

    # Craft at first position
    bus.publish("craft_at_position", x=4, y=4, z=4)
    assert len(successes) == 1
    assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL

    # Still in craft mode with 1 iron remaining
    assert gs.craft_mode_active is True
    assert ms.held_materials == {VOXEL_IRON_INGOT: 1}

    # Craft at second position
    bus.publish("craft_at_position", x=5, y=5, z=4)
    assert len(successes) == 2
    assert grid.get(5, 5, 4) == VOXEL_REINFORCED_WALL

    # Now depleted — should auto-exit craft mode
    assert gs.craft_mode_active is False


def test_find_valid_positions_basic():
    """CraftingBook.find_valid_positions scans z-level for valid spots."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[2, 2, 4] = VOXEL_STONE
    grid.grid[6, 6, 4] = VOXEL_STONE

    recipe = cs.crafting_book.get_recipe_by_name("Reinforced Wall")
    positions = cs.crafting_book.find_valid_positions(
        recipe, grid, VOXEL_IRON_INGOT, z_level=4
    )

    assert (2, 2, 4) in positions
    assert (6, 6, 4) in positions


def test_craft_success_event_has_position():
    """craft_success event includes the position of the craft."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 4] = VOXEL_STONE
    ms.held_materials = {VOXEL_IRON_INGOT: 1}

    successes = _craft(bus, cs, "Reinforced Wall", 4, 4, 4)

    assert successes[0]["x"] == 4
    assert successes[0]["y"] == 4
    assert successes[0]["z"] == 4


def test_drop_no_longer_triggers_crafting():
    """MoveSystem.drop on air places as loose — no crafting."""
    bus, grid, ms, cs, gs = _setup()
    grid.grid[4, 4, 5] = VOXEL_STONE  # solid below for spike
    ms.held_materials = {VOXEL_IRON_INGOT: 2}

    # Drop should place as loose, NOT craft a spike
    result = ms.drop(4, 4, 4)

    assert result is True
    assert grid.get(4, 4, 4) == VOXEL_IRON_INGOT
    assert grid.is_loose(4, 4, 4)
    assert ms.held_materials == {VOXEL_IRON_INGOT: 1}


def test_no_recipe_drop_places_loose():
    """MoveSystem.drop on air with no matching recipe places as loose."""
    bus, grid, ms, cs, gs = _setup()
    # No special conditions — just bare air, copper ingot has no air-target recipe
    ms.held_materials = {VOXEL_COPPER_INGOT: 1}

    result = ms.drop(4, 4, 4)

    assert result is True
    assert grid.get(4, 4, 4) == VOXEL_COPPER_INGOT
    assert grid.is_loose(4, 4, 4)
    assert ms.held_materials == {}


def test_required_inputs_on_recipes():
    """All recipes have required_inputs set."""
    book = _cs_book()
    for recipe in book.recipes:
        assert isinstance(recipe.required_inputs, frozenset)
        assert len(recipe.required_inputs) > 0, f"Recipe {recipe.name} has empty required_inputs"


def _cs_book():
    """Helper to get a CraftingBook instance."""
    from dungeon_builder.building.crafting_book import CraftingBook
    return CraftingBook()


# ===========================================================================
# New block crafting tests (from test_new_block_crafting.py)
# ===========================================================================


def _setup_nbc(width=10, depth=10, height=10, mana=None):
    bus = EventBus()
    grid = VoxelGrid(width=width, depth=depth, height=height)
    grid.visible[:] = True
    grid.claimed[:] = True
    gs = GameState(DEFAULT_SEED)
    gs.event_bus = bus
    ms = MoveSystem(bus, grid, gs)
    mana_system = None
    if mana is not None:
        from dungeon_builder.dungeon_core.mana import ManaSystem
        mana_system = ManaSystem(bus, grid, build_system=None)
        mana_system.mana = mana
    cs = CraftingSystem(bus, grid, ms, gs, mana_system=mana_system)
    gs.move_system = ms
    return bus, grid, ms, cs


def _craft_nbc(bus, cs, recipe_name, x, y, z, ms, held_materials, held_metal_types=None):
    """Helper: set held materials, select recipe, craft at position."""
    ms.held_materials = held_materials.copy()
    if held_metal_types:
        ms.held_metal_types = held_metal_types.copy()
    cs._current_z = z
    bus.publish("craft_recipe_selected", recipe_name=recipe_name)
    bus.publish("craft_at_position", x=x, y=y, z=z)


# ---------------------------------------------------------------------------
# Existing recipes now set metal_type
# ---------------------------------------------------------------------------

class TestExistingRecipesMetalType:
    def test_reinforced_wall_iron(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        _craft_nbc(bus, cs, "Reinforced Wall", 4, 4, 4, ms,
               {VOXEL_IRON_INGOT: 1}, {VOXEL_IRON_INGOT: METAL_IRON})
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        assert grid.get_metal_type(4, 4, 4) == METAL_IRON

    def test_reinforced_wall_copper(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        _craft_nbc(bus, cs, "Reinforced Wall", 4, 4, 4, ms,
               {VOXEL_COPPER_INGOT: 1}, {VOXEL_COPPER_INGOT: METAL_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        assert grid.get_metal_type(4, 4, 4) == METAL_COPPER

    def test_reinforced_wall_gold(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        _craft_nbc(bus, cs, "Reinforced Wall", 4, 4, 4, ms,
               {VOXEL_GOLD_INGOT: 1}, {VOXEL_GOLD_INGOT: METAL_GOLD})
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        assert grid.get_metal_type(4, 4, 4) == METAL_GOLD

    def test_spike_trap_metal_type(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
        _craft_nbc(bus, cs, "Spike Trap", 4, 4, 4, ms,
               {VOXEL_COPPER_INGOT: 1}, {VOXEL_COPPER_INGOT: METAL_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_SPIKE
        assert grid.get_metal_type(4, 4, 4) == METAL_COPPER

    def test_door_metal_type(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[3, 4, 4] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_STONE
        _craft_nbc(bus, cs, "Door", 4, 4, 4, ms,
               {VOXEL_COPPER_INGOT: 1}, {VOXEL_COPPER_INGOT: METAL_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_DOOR
        assert grid.get_metal_type(4, 4, 4) == METAL_COPPER


# ---------------------------------------------------------------------------
# Gold Bait
# ---------------------------------------------------------------------------

class TestGoldBait:
    def test_craft_gold_bait(self):
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
        grid.grid[5, 4, 4] = VOXEL_STONE  # wall
        _craft_nbc(bus, cs, "Gold Bait", 4, 4, 4, ms,
               {VOXEL_ENCHANTED_METAL: 1}, {VOXEL_ENCHANTED_METAL: METAL_ENCH_GOLD})
        assert grid.get(4, 4, 4) == VOXEL_GOLD_BAIT
        assert grid.get_metal_type(4, 4, 4) == METAL_ENCH_GOLD

    def test_gold_bait_requires_gold(self):
        """Gold bait fails if held enchanted metal is not gold."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_STONE
        _craft_nbc(bus, cs, "Gold Bait", 4, 4, 4, ms,
               {VOXEL_ENCHANTED_METAL: 1}, {VOXEL_ENCHANTED_METAL: METAL_ENCH_IRON})
        # Craft should fail (iron is not gold)
        assert grid.get(4, 4, 4) == VOXEL_AIR

    def test_gold_bait_needs_floor(self):
        """Gold bait on air without solid below fails."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_AIR  # no floor
        grid.grid[5, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_ENCHANTED_METAL: 1}
        ms.held_metal_types = {VOXEL_ENCHANTED_METAL: METAL_ENCH_GOLD}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Gold Bait")
        # Position should not be highlighted — check highlighted_positions
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_gold_bait_needs_wall(self):
        """Gold bait on air without lateral support fails."""
        bus, grid, ms, cs = _setup_nbc()
        # All air around
        grid.grid[:] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # floor only
        ms.held_materials = {VOXEL_ENCHANTED_METAL: 1}
        ms.held_metal_types = {VOXEL_ENCHANTED_METAL: METAL_ENCH_GOLD}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Gold Bait")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Heat Beacon
# ---------------------------------------------------------------------------

class TestHeatBeacon:
    def test_craft_heat_beacon(self):
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.temperature[4, 4, 4] = 300.0
        _craft_nbc(bus, cs, "Heat Beacon", 4, 4, 4, ms,
               {VOXEL_ENCHANTED_METAL: 1}, {VOXEL_ENCHANTED_METAL: METAL_ENCH_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_HEAT_BEACON
        assert grid.get_metal_type(4, 4, 4) == METAL_ENCH_COPPER

    def test_heat_beacon_requires_temperature(self):
        """Heat beacon fails if stone temperature <= 200."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.temperature[4, 4, 4] = 100.0  # too cold
        ms.held_materials = {VOXEL_COPPER_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Heat Beacon")
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_heat_beacon_requires_metal(self):
        """Heat beacon only accepts metal ingot or enchanted metal."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.temperature[4, 4, 4] = 300.0
        ms.held_materials = {VOXEL_DIRT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Heat Beacon")
        # Dirt not in required_inputs for heat beacon
        assert cs._active_recipe is None or cs._active_recipe.name != "Heat Beacon"


# ---------------------------------------------------------------------------
# Pressure Plate
# ---------------------------------------------------------------------------

class TestPressurePlate:
    def test_craft_pressure_plate(self):
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.grid[4, 4, 3] = VOXEL_AIR  # air above
        _craft_nbc(bus, cs, "Pressure Plate", 4, 4, 4, ms,
               {VOXEL_ENCHANTED_METAL: 1}, {VOXEL_ENCHANTED_METAL: METAL_ENCH_IRON})
        assert grid.get(4, 4, 4) == VOXEL_PRESSURE_PLATE
        assert grid.get_metal_type(4, 4, 4) == METAL_ENCH_IRON

    def test_pressure_plate_needs_air_above(self):
        """Pressure plate fails if no air above."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.grid[4, 4, 3] = VOXEL_STONE  # solid above
        ms.held_materials = {VOXEL_ENCHANTED_METAL: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Pressure Plate")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Iron Bars
# ---------------------------------------------------------------------------

class TestIronBars:
    def test_craft_iron_bars(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[3, 4, 4] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_STONE
        _craft_nbc(bus, cs, "Iron Bars", 4, 4, 4, ms,
               {VOXEL_GOLD_INGOT: 1}, {VOXEL_GOLD_INGOT: METAL_GOLD})
        assert grid.get(4, 4, 4) == VOXEL_IRON_BARS
        assert grid.get_metal_type(4, 4, 4) == METAL_GOLD

    def test_iron_bars_needs_opposite_walls(self):
        """Iron bars fail without 2 opposite walls."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[3, 4, 4] = VOXEL_STONE  # only one wall
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Iron Bars")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Floodgate
# ---------------------------------------------------------------------------

class TestFloodgate:
    def test_craft_floodgate(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_WATER  # adjacent water
        _craft_nbc(bus, cs, "Floodgate", 4, 4, 4, ms,
               {VOXEL_IRON_INGOT: 1}, {VOXEL_IRON_INGOT: METAL_IRON})
        assert grid.get(4, 4, 4) == VOXEL_FLOODGATE
        assert grid.get_metal_type(4, 4, 4) == METAL_IRON
        assert grid.get_block_state(4, 4, 4) == 1  # starts closed

    def test_floodgate_needs_adjacent_water(self):
        """Floodgate fails without adjacent water."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        # No water nearby
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Floodgate")
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_floodgate_detects_water_level(self):
        """Floodgate recognizes water_level > 0 as adjacent water."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_AIR
        grid.water_level[5, 4, 4] = 100  # water level but not VOXEL_WATER
        _craft_nbc(bus, cs, "Floodgate", 4, 4, 4, ms,
               {VOXEL_COPPER_INGOT: 1}, {VOXEL_COPPER_INGOT: METAL_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_FLOODGATE


# ---------------------------------------------------------------------------
# Alarm Bell
# ---------------------------------------------------------------------------

class TestAlarmBell:
    def test_craft_alarm_bell(self):
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
        grid.grid[5, 4, 4] = VOXEL_STONE  # wall
        _craft_nbc(bus, cs, "Alarm Bell", 4, 4, 4, ms,
               {VOXEL_ENCHANTED_METAL: 1}, {VOXEL_ENCHANTED_METAL: METAL_ENCH_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_ALARM_BELL
        assert grid.get_metal_type(4, 4, 4) == METAL_ENCH_COPPER

    def test_alarm_bell_needs_floor_and_wall(self):
        """Alarm bell fails without solid below + wall."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[:] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # floor only, no walls
        ms.held_materials = {VOXEL_ENCHANTED_METAL: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Alarm Bell")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Fragile Floor
# ---------------------------------------------------------------------------

class TestFragileFloor:
    def test_craft_fragile_floor(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # solid below
        grid.grid[3, 4, 4] = VOXEL_STONE  # wall 1
        grid.grid[5, 4, 4] = VOXEL_STONE  # wall 2
        _craft_nbc(bus, cs, "Fragile Floor", 4, 4, 4, ms, {VOXEL_CHALK: 1})
        assert grid.get(4, 4, 4) == VOXEL_FRAGILE_FLOOR
        assert grid.get_metal_type(4, 4, 4) == METAL_NONE  # non-metallic

    def test_fragile_floor_needs_two_walls(self):
        """Fragile floor fails with fewer than 2 solid sides."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE
        grid.grid[3, 4, 4] = VOXEL_STONE  # only 1 wall
        ms.held_materials = {VOXEL_CHALK: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Fragile Floor")
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_fragile_floor_needs_solid_below(self):
        """Fragile floor fails without solid below."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_AIR  # no floor
        grid.grid[3, 4, 4] = VOXEL_STONE
        grid.grid[5, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_CHALK: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Fragile Floor")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Pipe
# ---------------------------------------------------------------------------

class TestPipe:
    def test_craft_pipe_in_air(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[5, 4, 4] = VOXEL_STONE  # solid neighbor
        _craft_nbc(bus, cs, "Pipe", 4, 4, 4, ms,
               {VOXEL_COPPER_INGOT: 1}, {VOXEL_COPPER_INGOT: METAL_COPPER})
        assert grid.get(4, 4, 4) == VOXEL_PIPE
        assert grid.get_metal_type(4, 4, 4) == METAL_COPPER

    def test_craft_pipe_in_stone(self):
        """Pipes can be built into non-loose stone."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.loose[4, 4, 4] = False
        _craft_nbc(bus, cs, "Pipe", 4, 4, 4, ms,
               {VOXEL_IRON_INGOT: 1}, {VOXEL_IRON_INGOT: METAL_IRON})
        assert grid.get(4, 4, 4) == VOXEL_PIPE
        assert grid.get_metal_type(4, 4, 4) == METAL_IRON

    def test_pipe_in_air_needs_solid_neighbor(self):
        """Pipe in air fails without any solid neighbor."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[:] = VOXEL_AIR  # all air
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Pipe")
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_pipe_cannot_build_into_loose_stone(self):
        """Pipe can't be built into loose stone."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.loose[4, 4, 4] = True  # loose!
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Pipe")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------

class TestPump:
    def test_craft_pump_on_pipe(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_PIPE
        _craft_nbc(bus, cs, "Pump", 4, 4, 4, ms,
               {VOXEL_IRON_INGOT: 1}, {VOXEL_IRON_INGOT: METAL_IRON})
        assert grid.get(4, 4, 4) == VOXEL_PUMP
        assert grid.get_metal_type(4, 4, 4) == METAL_IRON
        assert grid.get_block_state(4, 4, 4) == 0  # default direction

    def test_pump_requires_pipe_target(self):
        """Pump fails on non-pipe targets."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE  # not a pipe
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Pump")
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_pump_direction_cycle(self):
        """Left-clicking a pump cycles its direction 0-5."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_PUMP
        grid.loose[4, 4, 4] = False
        grid.set_block_state(4, 4, 4, 0)

        events = []
        bus.subscribe("pump_direction_changed", lambda **kw: events.append(kw))

        for expected_dir in [1, 2, 3, 4, 5, 0]:
            bus.publish("voxel_left_clicked", x=4, y=4, z=4, mode="move")
            assert grid.get_block_state(4, 4, 4) == expected_dir
        assert len(events) == 6


# ---------------------------------------------------------------------------
# Steam Vent
# ---------------------------------------------------------------------------

class TestSteamVent:
    def test_craft_steam_vent(self):
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_LAVA  # lava 1 below
        _craft_nbc(bus, cs, "Steam Vent", 4, 4, 4, ms, {VOXEL_OBSIDIAN: 1})
        assert grid.get(4, 4, 4) == VOXEL_STEAM_VENT
        assert grid.get_metal_type(4, 4, 4) == METAL_NONE

    def test_steam_vent_lava_2_deep(self):
        """Steam vent works with lava 2 cells below."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE  # not lava at depth 1
        grid.grid[4, 4, 6] = VOXEL_LAVA   # lava at depth 2
        _craft_nbc(bus, cs, "Steam Vent", 4, 4, 4, ms, {VOXEL_OBSIDIAN: 1})
        assert grid.get(4, 4, 4) == VOXEL_STEAM_VENT

    def test_steam_vent_no_lava(self):
        """Steam vent fails without lava below."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE
        grid.grid[4, 4, 6] = VOXEL_STONE
        ms.held_materials = {VOXEL_OBSIDIAN: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Steam Vent")
        assert (4, 4, 4) not in cs._highlighted_positions

    def test_steam_vent_lava_too_deep(self):
        """Steam vent fails if lava is 3+ cells below (only checks 2)."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[4, 4, 5] = VOXEL_STONE
        grid.grid[4, 4, 6] = VOXEL_STONE
        grid.grid[4, 4, 7] = VOXEL_LAVA  # too deep
        ms.held_materials = {VOXEL_OBSIDIAN: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Steam Vent")
        assert (4, 4, 4) not in cs._highlighted_positions


# ---------------------------------------------------------------------------
# Metal_type fallback when held_metal_types not set
# ---------------------------------------------------------------------------

class TestMetalTypeFallback:
    def test_reinforced_wall_fallback_from_held_type(self):
        """When no held_metal_types, metal_type derived from held voxel type."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        # Don't set held_metal_types — test fallback
        ms.held_materials = {VOXEL_GOLD_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        assert grid.get_metal_type(4, 4, 4) == METAL_GOLD

    def test_pipe_fallback_from_held_type(self):
        """Pipe with no held_metal_types uses HELD_TO_METAL fallback."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_AIR
        grid.grid[5, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_COPPER_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Pipe")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_PIPE
        assert grid.get_metal_type(4, 4, 4) == METAL_COPPER


# ===========================================================================
# Craft UI experience tests (hover feedback, forgiving misclick, etc.)
# ===========================================================================


class TestCraftModeHoverFeedback:
    """Hover events during craft mode publish craft_hover_valid/invalid."""

    def test_hover_valid_position(self):
        """Hovering a highlighted position publishes craft_hover_valid."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        assert (4, 4, 4) in cs._highlighted_positions

        valid_events = []
        bus.subscribe("craft_hover_valid", lambda **kw: valid_events.append(kw))

        bus.publish("voxel_hover", x=4, y=4, z=4)

        assert len(valid_events) == 1
        assert valid_events[0]["x"] == 4
        assert valid_events[0]["recipe_name"] == "Reinforced Wall"
        assert valid_events[0]["output_vtype"] == VOXEL_REINFORCED_WALL

    def test_hover_invalid_position(self):
        """Hovering a non-highlighted position publishes craft_hover_invalid."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

        invalid_events = []
        bus.subscribe("craft_hover_invalid", lambda **kw: invalid_events.append(kw))

        bus.publish("voxel_hover", x=0, y=0, z=0)  # Air, not highlighted

        assert len(invalid_events) == 1
        assert invalid_events[0]["x"] == 0

    def test_hover_clear_publishes_craft_hover_clear(self):
        """Mouse leaving grid in craft mode publishes craft_hover_clear."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

        clear_events = []
        bus.subscribe("craft_hover_clear", lambda **kw: clear_events.append(True))

        bus.publish("voxel_hover_clear")

        assert len(clear_events) == 1

    def test_no_hover_events_outside_craft_mode(self):
        """Hovering outside craft mode does not publish craft hover events."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE

        valid = []
        invalid = []
        bus.subscribe("craft_hover_valid", lambda **kw: valid.append(kw))
        bus.subscribe("craft_hover_invalid", lambda **kw: invalid.append(kw))

        bus.publish("voxel_hover", x=4, y=4, z=4)

        assert len(valid) == 0
        assert len(invalid) == 0


class TestCraftModeStaysOnMisclick:
    """Clicking non-highlighted positions stays in craft mode (forgiving)."""

    def test_misclick_shows_error_stays_active(self):
        """Non-highlighted click shows error but keeps craft mode."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 2}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        assert gs.craft_mode_active is True

        errors = []
        bus.subscribe("error_message", lambda **kw: errors.append(kw))

        # Click non-highlighted air
        bus.publish("craft_at_position", x=0, y=0, z=0)

        assert gs.craft_mode_active is True
        assert len(errors) == 1

    def test_esc_still_exits(self):
        """ESC / right-click (craft_cancel) still exits craft mode."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        assert gs.craft_mode_active is True

        bus.publish("craft_cancel")

        assert gs.craft_mode_active is False

    def test_can_still_craft_after_misclick(self):
        """Player can still craft at a valid position after a misclick."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 2}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

        # Misclick on air
        bus.publish("craft_at_position", x=0, y=0, z=0)
        assert gs.craft_mode_active is True

        # Now craft at the actual valid position
        successes = []
        bus.subscribe("craft_success", lambda **kw: successes.append(kw))
        bus.publish("craft_at_position", x=4, y=4, z=4)

        assert len(successes) == 1
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL


class TestCraftRemainingCount:
    """Remaining count is published on enter and after each craft."""

    def test_remaining_on_enter(self):
        """craft_remaining_updated published when entering craft mode."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 5}

        remaining_events = []
        bus.subscribe("craft_remaining_updated", lambda **kw: remaining_events.append(kw))

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

        assert len(remaining_events) == 1
        assert remaining_events[0]["remaining"] == 5
        assert remaining_events[0]["recipe_name"] == "Reinforced Wall"

    def test_remaining_decreases_after_craft(self):
        """Count decreases after successful craft."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.grid[5, 5, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 3}

        remaining_events = []
        bus.subscribe("craft_remaining_updated", lambda **kw: remaining_events.append(kw))

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        # First event: enter (3)
        assert remaining_events[-1]["remaining"] == 3

        bus.publish("craft_at_position", x=4, y=4, z=4)
        # Second event: after craft (2)
        assert remaining_events[-1]["remaining"] == 2


class TestCraftPlacementFlash:
    """Placement flash event on successful craft."""

    def test_flash_on_success(self):
        """craft_placement_flash published on successful craft."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        flashes = []
        bus.subscribe("craft_placement_flash", lambda **kw: flashes.append(kw))

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)

        assert len(flashes) == 1
        assert flashes[0]["x"] == 4
        assert flashes[0]["y"] == 4
        assert flashes[0]["z"] == 4

    def test_no_flash_on_invalid_click(self):
        """No flash when clicking non-highlighted position."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        flashes = []
        bus.subscribe("craft_placement_flash", lambda **kw: flashes.append(kw))

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=0, y=0, z=0)  # Invalid

        assert len(flashes) == 0


class TestCraftRecipeOutputVtype:
    """CraftingRecipe.output_vtype field exists with correct values."""

    def test_output_vtype_field_exists(self):
        """All recipes have output_vtype attribute."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        for recipe in book.recipes:
            assert hasattr(recipe, "output_vtype")
            assert isinstance(recipe.output_vtype, int)

    def test_known_output_vtypes(self):
        """Recipes with fixed output have correct output_vtype."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        expected = {
            "Marble Wall": VOXEL_MARBLE,
            "Obsidian Forge": VOXEL_OBSIDIAN,
            "Reinforced Wall": VOXEL_REINFORCED_WALL,
            "Spike Trap": VOXEL_SPIKE,
            "Door": VOXEL_DOOR,
            "Treasure": VOXEL_TREASURE,
            "Tarp": VOXEL_TARP,
            "Slope": VOXEL_SLOPE,
            "Stairs": VOXEL_STAIRS,
        }
        for name, expected_vtype in expected.items():
            recipe = book.get_recipe_by_name(name)
            assert recipe is not None, f"Recipe '{name}' not found"
            assert recipe.output_vtype == expected_vtype, (
                f"{name}: expected {expected_vtype}, got {recipe.output_vtype}"
            )

    def test_variable_output_is_zero(self):
        """Ore Smelting has output_vtype=0 (variable output)."""
        from dungeon_builder.building.crafting_book import CraftingBook
        book = CraftingBook()
        recipe = book.get_recipe_by_name("Ore Smelting")
        assert recipe is not None
        assert recipe.output_vtype == 0

    def test_output_vtype_included_in_hover_event(self):
        """craft_hover_valid includes output_vtype from the recipe."""
        bus, grid, ms, cs, gs = _setup()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")

        valid_events = []
        bus.subscribe("craft_hover_valid", lambda **kw: valid_events.append(kw))

        bus.publish("voxel_hover", x=4, y=4, z=4)

        assert len(valid_events) == 1
        assert valid_events[0]["output_vtype"] == VOXEL_REINFORCED_WALL


# ===========================================================================
# Mana-or-materials dual cost model tests
# ===========================================================================


class TestManaCrafting:
    """Verify compute_craft_cost integration in CraftingSystem."""

    def test_mana_only_craft_enters_mode(self):
        """Mana-only crafting (no held material) enters craft mode."""
        bus, grid, ms, cs = _setup_nbc(mana=100)
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {}  # no materials at all
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        # Iron ingot is substitutable (mana_value=30), assembly=0 → total=30
        assert cs.is_craft_mode_active
        assert cs._active_held_type == VOXEL_IRON_INGOT  # canonical type

    def test_mana_only_craft_succeeds(self):
        """Mana-only crafting places the block and deducts mana."""
        bus, grid, ms, cs = _setup_nbc(mana=100)
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        # 30 mana deducted (iron ingot mana_value)
        assert cs.mana_system.mana == 70

    def test_mana_only_no_material_consumed(self):
        """Mana-only crafting doesn't consume materials from inventory."""
        bus, grid, ms, cs = _setup_nbc(mana=100)
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_STONE: 5}  # unrelated material
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        assert ms.held_materials[VOXEL_STONE] == 5  # untouched

    def test_insufficient_mana_rejected(self):
        """Mana-only craft with insufficient mana is rejected."""
        bus, grid, ms, cs = _setup_nbc(mana=10)
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {}
        errors = []
        bus.subscribe("error_message", lambda **kw: errors.append(kw))
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        # Total cost=30, only 10 mana
        assert not cs.is_craft_mode_active
        assert len(errors) == 1
        assert "mana" in errors[0]["text"].lower()

    def test_material_offsets_mana_cost(self):
        """Holding material reduces mana to assembly cost only."""
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        ms.held_metal_types = {VOXEL_IRON_INGOT: METAL_IRON}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL
        # Reinforced Wall: assembly=0, material held → total=0 → no mana spent
        assert cs.mana_system.mana == 500
        # Material consumed
        assert ms.get_count(VOXEL_IRON_INGOT) == 0

    def test_assembly_cost_deducted_with_material(self):
        """Assembly cost is deducted even when material is held."""
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.temperature[4, 4, 4] = 300.0
        ms.held_materials = {VOXEL_ENCHANTED_METAL: 1}
        ms.held_metal_types = {VOXEL_ENCHANTED_METAL: METAL_ENCH_COPPER}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Heat Beacon")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_HEAT_BEACON
        # Heat Beacon: assembly=25, material held → total=25
        assert cs.mana_system.mana == 475

    def test_zero_cost_craft_no_mana_system(self):
        """Zero-cost recipe works without a mana system."""
        bus, grid, ms, cs = _setup_nbc()  # no mana
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_REINFORCED_WALL

    def test_material_depleted_exits_without_mana(self):
        """Depleting material exits craft mode when no mana available."""
        bus, grid, ms, cs = _setup_nbc()  # no mana system
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert not cs.is_craft_mode_active

    def test_material_depleted_stays_with_mana(self):
        """Depleting material keeps craft mode when mana can substitute."""
        bus, grid, ms, cs = _setup_nbc(mana=100)
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.grid[5, 5, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 1}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        # Material depleted, but mana=100 can cover cost=30
        assert cs.is_craft_mode_active
        # Now it's in mana-only mode with canonical type
        assert cs._active_held_type == VOXEL_IRON_INGOT

    def test_remaining_count_material_based(self):
        """Remaining count reflects held material count."""
        bus, grid, ms, cs = _setup_nbc()
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {VOXEL_IRON_INGOT: 5}

        remaining = []
        bus.subscribe(
            "craft_remaining_updated", lambda **kw: remaining.append(kw)
        )

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        assert remaining[-1]["remaining"] == 5

    def test_remaining_count_mana_based(self):
        """Remaining count reflects mana when crafting without material."""
        bus, grid, ms, cs = _setup_nbc(mana=100)
        grid.grid[4, 4, 4] = VOXEL_STONE
        ms.held_materials = {}

        remaining = []
        bus.subscribe(
            "craft_remaining_updated", lambda **kw: remaining.append(kw)
        )

        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Reinforced Wall")
        # 100 mana / 30 cost per craft = 3
        assert remaining[-1]["remaining"] == 3

    def test_enchanted_offset_from_craft_fn(self):
        """Enchanted offset is applied by craft_fn, not by CraftingSystem."""
        bus, grid, ms, cs = _setup_nbc(mana=500)
        grid.grid[4, 4, 4] = VOXEL_STONE
        grid.temperature[4, 4, 4] = 300.0
        # Hold regular copper — craft_fn should apply enchanted offset
        ms.held_materials = {VOXEL_COPPER_INGOT: 1}
        ms.held_metal_types = {VOXEL_COPPER_INGOT: METAL_COPPER}
        cs._current_z = 4
        bus.publish("craft_recipe_selected", recipe_name="Heat Beacon")
        bus.publish("craft_at_position", x=4, y=4, z=4)
        assert grid.get(4, 4, 4) == VOXEL_HEAT_BEACON
        # craft_fn applies enchanted offset: METAL_COPPER -> METAL_ENCH_COPPER
        assert grid.get_metal_type(4, 4, 4) == METAL_ENCH_COPPER
