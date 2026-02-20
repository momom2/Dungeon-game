"""Tests for claimed territory flood-fill, fog-of-war visibility,
functional block propagation, territory restrictions, and timing."""

from __future__ import annotations

import numpy as np
import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.game_state import GameState
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.claimed_territory import ClaimedTerritorySystem
from dungeon_builder.building.build_system import BuildSystem
from dungeon_builder.building.move_system import MoveSystem
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DIRT,
    VOXEL_CORE,
    VOXEL_WATER,
    VOXEL_LAVA,
    VOXEL_DOOR,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_TARP,
    VOXEL_SPIKE,
    VOXEL_TREASURE,
    VOXEL_ROLLING_STONE,
    VOXEL_REINFORCED_WALL,
    CORE_X,
    CORE_Y,
    CORE_Z,
    CLAIMED_TICK_INTERVAL,
    FOG_COLOR,
    DEFAULT_SEED,
)


# ── Helpers (from test_claimed_territory.py) ─────────────────────────


def _setup():
    """Create a small grid with stone everywhere except a core block."""
    bus = EventBus()
    grid = VoxelGrid(width=16, depth=16, height=5)
    grid.grid[:] = VOXEL_STONE
    # Place core at a sensible location within this small grid
    cx, cy, cz = min(CORE_X, 8), min(CORE_Y, 8), min(CORE_Z, 2)
    grid.grid[cx, cy, cz] = VOXEL_CORE
    return bus, grid, cx, cy, cz


# ── Core with no air ─────────────────────────────────────────────────


class TestNoAir:
    def test_no_air_neighbors_means_no_claimed(self):
        bus, grid, cx, cy, cz = _setup()
        # Core surrounded by stone — no air at all
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert not np.any(grid.claimed)

    def test_core_always_visible_even_without_air(self):
        bus, grid, cx, cy, cz = _setup()
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_visible(cx, cy, cz)


# ── Room around core ─────────────────────────────────────────────────


class TestRoomAroundCore:
    def test_air_room_claimed(self):
        bus, grid, cx, cy, cz = _setup()
        # Carve a 3x3 air room around core
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = cx + dx, cy + dy
                if grid.in_bounds(nx, ny, cz) and (dx, dy) != (0, 0):
                    grid.grid[nx, ny, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        # All air cells should be claimed
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = cx + dx, cy + dy
                if (dx, dy) != (0, 0) and grid.in_bounds(nx, ny, cz):
                    assert grid.is_claimed(nx, ny, cz), f"({nx},{ny},{cz}) not claimed"

    def test_walls_adjacent_to_room_are_visible(self):
        bus, grid, cx, cy, cz = _setup()
        # Carve 3x3 air room
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = cx + dx, cy + dy
                if grid.in_bounds(nx, ny, cz) and (dx, dy) != (0, 0):
                    grid.grid[nx, ny, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        # Stone walls 1 cell beyond the air room should be visible
        wall_x = cx + 2
        if grid.in_bounds(wall_x, cy, cz):
            assert grid.is_visible(wall_x, cy, cz)

    def test_distant_stone_not_visible(self):
        bus, grid, cx, cy, cz = _setup()
        # Carve single air cell next to core
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        # Stone far away should not be visible
        far_x = cx + 5
        if grid.in_bounds(far_x, cy, cz):
            assert not grid.is_visible(far_x, cy, cz)


# ── Connectivity ──────────────────────────────────────────────────────


class TestConnectivity:
    def test_disconnected_pocket_not_claimed(self):
        bus, grid, cx, cy, cz = _setup()
        # Air next to core
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Disconnected air pocket far away (no air path to core)
        grid.grid[0, 0, 0] = VOXEL_AIR
        grid.grid[1, 0, 0] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 1, cy, cz)
        assert not grid.is_claimed(0, 0, 0)
        assert not grid.is_claimed(1, 0, 0)

    def test_corridor_connects_chambers(self):
        bus, grid, cx, cy, cz = _setup()
        # Chamber 1: around core
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Corridor
        grid.grid[cx + 2, cy, cz] = VOXEL_AIR
        grid.grid[cx + 3, cy, cz] = VOXEL_AIR
        # Chamber 2
        grid.grid[cx + 4, cy, cz] = VOXEL_AIR
        if grid.in_bounds(cx + 4, cy + 1, cz):
            grid.grid[cx + 4, cy + 1, cz] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 4, cy, cz)

    def test_blocking_corridor_disconnects(self):
        bus, grid, cx, cy, cz = _setup()
        # Air path: core -> cx+1 -> cx+2 -> cx+3
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        grid.grid[cx + 2, cy, cz] = VOXEL_AIR
        grid.grid[cx + 3, cy, cz] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 3, cy, cz)

        # Block the corridor
        grid.grid[cx + 2, cy, cz] = VOXEL_STONE
        sys.recompute()
        assert not grid.is_claimed(cx + 3, cy, cz)
        # Near side still claimed
        assert grid.is_claimed(cx + 1, cy, cz)


# ── Vertical ──────────────────────────────────────────────────────────


class TestVertical:
    def test_vertical_shaft_claimed(self):
        bus, grid, cx, cy, cz = _setup()
        # Air below core (shaft going deeper)
        grid.grid[cx, cy + 1, cz] = VOXEL_AIR  # air next to core
        for z in range(cz, min(cz + 3, grid.height)):
            grid.grid[cx, cy + 1, z] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        for z in range(cz, min(cz + 3, grid.height)):
            assert grid.is_claimed(cx, cy + 1, z), f"z={z} not claimed"


# ── Tick-based recompute ──────────────────────────────────────────────


class TestTickRecompute:
    def test_recompute_on_tick_interval(self):
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 1, cy, cz)

        # Add new air at cx+2 (not yet claimed since no recompute)
        grid.grid[cx + 2, cy, cz] = VOXEL_AIR

        # Wrong tick — no recompute
        bus.publish("tick", tick=1)
        assert not grid.is_claimed(cx + 2, cy, cz)

        # Right tick — recompute happens
        bus.publish("tick", tick=CLAIMED_TICK_INTERVAL)
        assert grid.is_claimed(cx + 2, cy, cz)


# ── Event publishing ──────────────────────────────────────────────────


class TestEvents:
    def test_event_fires_on_change(self):
        bus, grid, cx, cy, cz = _setup()
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        # No claimed territory yet

        events = []
        bus.subscribe("claimed_territory_changed", lambda **kw: events.append(True))

        # Add air and recompute — territory changes
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        sys.recompute()
        assert len(events) == 1

    def test_no_event_when_unchanged(self):
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)

        events = []
        bus.subscribe("claimed_territory_changed", lambda **kw: events.append(True))

        # Recompute with no changes
        sys.recompute()
        assert len(events) == 0


# ── Core block visibility ─────────────────────────────────────────────


class TestCoreBlockVisibility:
    """Core placed as VOXEL_CORE renders correctly in claimed territory."""

    def test_core_block_is_visible(self):
        """Core block (solid) with air neighbors is visible."""
        bus, grid, cx, cy, cz = _setup()
        # Carve air around core (simulates _carve_initial_dungeon)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if (dx, dy) != (0, 0) and grid.in_bounds(cx + dx, cy + dy, cz):
                    grid.grid[cx + dx, cy + dy, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_visible(cx, cy, cz), "Core block should be visible"

    def test_core_block_not_claimed(self):
        """Core block is solid, so it should not be claimed (only air/water are)."""
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert not grid.is_claimed(cx, cy, cz), "Solid core should not be claimed"

    def test_air_above_core_is_claimed(self):
        """Air above the core (headroom) should be claimed."""
        bus, grid, cx, cy, cz = _setup()
        # Air next to core at same level
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Air above core
        if grid.in_bounds(cx, cy, cz - 1):
            grid.grid[cx, cy, cz - 1] = VOXEL_AIR
            grid.grid[cx + 1, cy, cz - 1] = VOXEL_AIR
            sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
            assert grid.is_claimed(cx, cy, cz - 1), "Air above core should be claimed"


# ── Water propagation ──────────────────────────────────────────────────


class TestWaterPropagation:
    """Tests for claiming through water (but not lava)."""

    def test_water_corridor_claimed(self):
        """Water corridor between core and air pocket is claimed."""
        bus, grid, cx, cy, cz = _setup()
        # Air next to core
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Water corridor
        grid.grid[cx + 2, cy, cz] = VOXEL_WATER
        grid.grid[cx + 3, cy, cz] = VOXEL_WATER
        # Air pocket beyond water
        grid.grid[cx + 4, cy, cz] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 2, cy, cz)
        assert grid.is_claimed(cx + 3, cy, cz)
        assert grid.is_claimed(cx + 4, cy, cz)

    def test_lava_blocks_propagation(self):
        """Lava corridor blocks territory propagation."""
        bus, grid, cx, cy, cz = _setup()
        # Air next to core
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Lava barrier
        grid.grid[cx + 2, cy, cz] = VOXEL_LAVA
        # Air beyond lava
        grid.grid[cx + 3, cy, cz] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 1, cy, cz)
        assert not grid.is_claimed(cx + 3, cy, cz)

    def test_mixed_air_water_corridor(self):
        """Alternating air and water cells are all claimed."""
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        grid.grid[cx + 2, cy, cz] = VOXEL_WATER
        grid.grid[cx + 3, cy, cz] = VOXEL_AIR
        grid.grid[cx + 4, cy, cz] = VOXEL_WATER

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        for dx in range(1, 5):
            assert grid.is_claimed(cx + dx, cy, cz), f"dx={dx} not claimed"

    def test_water_not_visible(self):
        """Water cells that are claimed should NOT be marked visible."""
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        grid.grid[cx + 2, cy, cz] = VOXEL_WATER

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 2, cy, cz)
        assert not grid.is_visible(cx + 2, cy, cz)

    def test_stone_adjacent_to_water_is_visible(self):
        """Stone block adjacent to claimed water should be visible."""
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        grid.grid[cx + 2, cy, cz] = VOXEL_WATER
        # cx+3 remains stone

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_visible(cx + 3, cy, cz)

    def test_submerged_chamber_claimed(self):
        """Fully water-filled room connected to core is claimed."""
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR  # entry
        # 2x2 water chamber
        for dx in (2, 3):
            for dy in (0, 1):
                grid.grid[cx + dx, cy + dy, cz] = VOXEL_WATER

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        for dx in (2, 3):
            for dy in (0, 1):
                assert grid.is_claimed(cx + dx, cy + dy, cz), (
                    f"({cx+dx},{cy+dy},{cz}) not claimed"
                )

    def test_water_adjacent_to_core_seeds_flood_fill(self):
        """Water directly next to the core seeds the flood-fill."""
        bus, grid, cx, cy, cz = _setup()
        grid.grid[cx + 1, cy, cz] = VOXEL_WATER
        grid.grid[cx + 2, cy, cz] = VOXEL_AIR

        sys = ClaimedTerritorySystem(bus, grid, cx, cy, cz)
        assert grid.is_claimed(cx + 1, cy, cz)
        assert grid.is_claimed(cx + 2, cy, cz)


# ===========================================================================
# Functional block propagation (from test_claiming_functional_blocks.py)
# ===========================================================================


def _make_grid() -> VoxelGrid:
    """Create a grid filled with stone."""
    grid = VoxelGrid()
    grid.grid[:] = VOXEL_STONE
    grid.grid[CORE_X, CORE_Y, CORE_Z] = VOXEL_CORE
    return grid


def _carve_corridor_with_block(grid: VoxelGrid, block_type: int) -> tuple[int, int, int]:
    """Carve air around core, place block_type in a corridor, and air beyond it.

    Layout at z=CORE_Z:
    core @ (CORE_X, CORE_Y) -> air @ (CORE_X+1, CORE_Y) ->
    block_type @ (CORE_X+2, CORE_Y) -> air @ (CORE_X+3, CORE_Y)

    Returns the position of the air cell beyond the functional block.
    """
    cx, cy, cz = CORE_X, CORE_Y, CORE_Z
    # Air adjacent to core
    grid.grid[cx + 1, cy, cz] = VOXEL_AIR
    # Functional block in middle
    grid.grid[cx + 2, cy, cz] = block_type
    # Air beyond the block
    grid.grid[cx + 3, cy, cz] = VOXEL_AIR
    return (cx + 3, cy, cz)


class TestFunctionalBlockPropagation:
    """Claiming should propagate through all functional block types."""

    @pytest.mark.parametrize("block_type,name", [
        (VOXEL_SLOPE, "Slope"),
        (VOXEL_STAIRS, "Stairs"),
        (VOXEL_DOOR, "Door"),
        (VOXEL_TARP, "Tarp"),
        (VOXEL_SPIKE, "Spike"),
        (VOXEL_TREASURE, "Treasure"),
        (VOXEL_ROLLING_STONE, "Rolling Stone"),
        (VOXEL_REINFORCED_WALL, "Reinforced Wall"),
    ])
    def test_claiming_propagates_through_block(self, block_type: int, name: str):
        """Air beyond a functional block should be claimed."""
        grid = _make_grid()
        beyond_pos = _carve_corridor_with_block(grid, block_type)

        bus = EventBus()
        system = ClaimedTerritorySystem(bus, grid)

        bx, by, bz = beyond_pos
        assert bool(grid.claimed[bx, by, bz]) is True, (
            f"Air beyond {name} should be claimed"
        )

    @pytest.mark.parametrize("block_type,name", [
        (VOXEL_SLOPE, "Slope"),
        (VOXEL_STAIRS, "Stairs"),
        (VOXEL_DOOR, "Door"),
        (VOXEL_TARP, "Tarp"),
        (VOXEL_SPIKE, "Spike"),
        (VOXEL_TREASURE, "Treasure"),
        (VOXEL_ROLLING_STONE, "Rolling Stone"),
        (VOXEL_REINFORCED_WALL, "Reinforced Wall"),
    ])
    def test_functional_block_itself_is_claimed(self, block_type: int, name: str):
        """The functional block cell itself should be claimed."""
        grid = _make_grid()
        _carve_corridor_with_block(grid, block_type)

        bus = EventBus()
        system = ClaimedTerritorySystem(bus, grid)

        cx = CORE_X + 2
        assert bool(grid.claimed[cx, CORE_Y, CORE_Z]) is True, (
            f"{name} block itself should be claimed"
        )

    @pytest.mark.parametrize("block_type,name", [
        (VOXEL_SLOPE, "Slope"),
        (VOXEL_STAIRS, "Stairs"),
        (VOXEL_DOOR, "Door"),
        (VOXEL_SPIKE, "Spike"),
        (VOXEL_TREASURE, "Treasure"),
        (VOXEL_REINFORCED_WALL, "Reinforced Wall"),
    ])
    def test_functional_block_is_visible(self, block_type: int, name: str):
        """Claimed functional blocks should be visible (for rendering)."""
        grid = _make_grid()
        _carve_corridor_with_block(grid, block_type)

        bus = EventBus()
        system = ClaimedTerritorySystem(bus, grid)

        cx = CORE_X + 2
        assert bool(grid.visible[cx, CORE_Y, CORE_Z]) is True, (
            f"Claimed {name} should be visible"
        )


class TestNaturalSolidsStillBlock:
    """Natural solid blocks should still block claiming."""

    def test_stone_blocks_propagation(self):
        """Stone should NOT allow claiming through."""
        grid = _make_grid()
        cx, cy, cz = CORE_X, CORE_Y, CORE_Z
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Stone stays at cx+2 (default fill)
        grid.grid[cx + 3, cy, cz] = VOXEL_AIR

        bus = EventBus()
        system = ClaimedTerritorySystem(bus, grid)

        # Air beyond stone should NOT be claimed
        assert bool(grid.claimed[cx + 3, cy, cz]) is False

    def test_lava_blocks_propagation(self):
        """Lava should NOT allow claiming through."""
        grid = _make_grid()
        cx, cy, cz = CORE_X, CORE_Y, CORE_Z
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        grid.grid[cx + 2, cy, cz] = VOXEL_LAVA
        grid.grid[cx + 3, cy, cz] = VOXEL_AIR

        bus = EventBus()
        system = ClaimedTerritorySystem(bus, grid)

        assert bool(grid.claimed[cx + 3, cy, cz]) is False


class TestStairsVerticalClaiming:
    """Stairs should allow vertical territory propagation."""

    def test_stairs_bridge_z_levels(self):
        """Air above stairs should be claimable (vertical propagation)."""
        grid = _make_grid()
        cx, cy, cz = CORE_X, CORE_Y, CORE_Z
        # Air adjacent to core
        grid.grid[cx + 1, cy, cz] = VOXEL_AIR
        # Stairs at cx+2
        grid.grid[cx + 2, cy, cz] = VOXEL_STAIRS
        # Air above stairs (one z-level up, lower z-index)
        grid.grid[cx + 2, cy, cz - 1] = VOXEL_AIR

        bus = EventBus()
        system = ClaimedTerritorySystem(bus, grid)

        assert bool(grid.claimed[cx + 2, cy, cz - 1]) is True, (
            "Air above stairs should be claimed via vertical propagation"
        )


# ===========================================================================
# Territory restrictions (from test_territory_restrictions.py)
# ===========================================================================


# ── Helpers ──────────────────────────────────────────────────────────


def _dig_setup():
    """Grid with a stone block that is NOT visible (not near claimed territory)."""
    bus = EventBus()
    grid = VoxelGrid(width=8, depth=8, height=4)
    grid.grid[:] = VOXEL_STONE
    # visible is all False by default
    bs = BuildSystem(bus, grid)
    return bus, grid, bs


def _move_setup():
    """Grid for move tests."""
    bus = EventBus()
    grid = VoxelGrid(width=8, depth=8, height=4)
    grid.grid[:] = VOXEL_STONE
    # visible and claimed are all False by default
    gs = GameState(DEFAULT_SEED)
    gs.event_bus = bus
    ms = MoveSystem(bus, grid, gs)
    return bus, grid, ms


# ── Digging territory restrictions ───────────────────────────────────


class TestDigTerritoryRestrictions:
    def test_invisible_block_becomes_pending_dig(self):
        """Digging a non-visible block goes to pending_digs (not rejected)."""
        bus, grid, bs = _dig_setup()
        # Block at (4,4,2) is stone but not visible

        assert bs.queue_dig(4, 4, 2) is True
        assert len(bs.pending_digs) == 1
        assert len(bs.dig_queue) == 0  # NOT in dig_queue yet

    def test_can_dig_visible_block(self):
        """Digging a visible block (border of claimed territory) succeeds."""
        bus, grid, bs = _dig_setup()
        grid.visible[4, 4, 2] = True

        assert bs.queue_dig(4, 4, 2) is True
        assert len(bs.dig_queue) == 1

    def test_dig_border_block_adjacent_to_claimed_air(self):
        """A solid block next to a claimed air cell is visible and diggable."""
        bus, grid, bs = _dig_setup()
        # Carve air cell and mark it claimed
        grid.grid[4, 4, 2] = VOXEL_AIR
        grid.claimed[4, 4, 2] = True
        # The adjacent stone block should be visible (border)
        grid.visible[5, 4, 2] = True

        assert bs.queue_dig(5, 4, 2) is True

    def test_dig_deeply_buried_block_becomes_pending(self):
        """A solid block far from any claimed air goes to pending_digs."""
        bus, grid, bs = _dig_setup()
        # Everything is stone, nothing is claimed or visible

        assert bs.queue_dig(0, 0, 0) is True
        assert len(bs.pending_digs) == 1

    def test_left_click_dig_outside_territory_goes_pending(self):
        """Left-click dig on non-visible block goes to pending_digs."""
        bus, grid, bs = _dig_setup()

        bus.publish("voxel_left_clicked", x=4, y=4, z=2, mode="dig")
        assert len(bs.dig_queue) == 0
        assert len(bs.pending_digs) == 1


# ── Pick up territory restrictions ───────────────────────────────────


class TestPickUpTerritoryRestrictions:
    def test_cannot_pick_up_outside_territory(self):
        """Picking up a loose block outside visible territory is rejected."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_STONE
        grid.loose[4, 4, 2] = True
        # visible is False

        errors = []
        bus.subscribe("error_message", lambda **kw: errors.append(kw))

        assert ms.pick_up(4, 4, 2) is False
        assert len(errors) == 1
        assert "territory" in errors[0]["text"].lower()

    def test_can_pick_up_in_territory(self):
        """Picking up a loose visible block succeeds."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_STONE
        grid.loose[4, 4, 2] = True
        grid.visible[4, 4, 2] = True

        assert ms.pick_up(4, 4, 2) is True
        assert ms.held_materials == {VOXEL_STONE: 1}


# ── Drop territory restrictions ──────────────────────────────────────


class TestDropTerritoryRestrictions:
    def test_cannot_drop_on_unclaimed_air(self):
        """Dropping onto an unclaimed air cell is rejected."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_STONE
        grid.loose[4, 4, 2] = True
        grid.visible[4, 4, 2] = True
        ms.pick_up(4, 4, 2)

        # Target is air but not claimed
        grid.grid[3, 3, 2] = VOXEL_AIR

        errors = []
        bus.subscribe("error_message", lambda **kw: errors.append(kw))

        assert ms.drop(3, 3, 2) is False
        assert len(errors) == 1
        assert "territory" in errors[0]["text"].lower()

    def test_can_drop_on_claimed_air(self):
        """Dropping onto a claimed air cell succeeds."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_STONE
        grid.loose[4, 4, 2] = True
        grid.visible[4, 4, 2] = True
        ms.pick_up(4, 4, 2)

        grid.grid[3, 3, 2] = VOXEL_AIR
        grid.claimed[3, 3, 2] = True

        assert ms.drop(3, 3, 2) is True
        assert grid.get(3, 3, 2) == VOXEL_STONE

    def test_drop_on_solid_rejected(self):
        """Dropping onto a solid block is rejected (no auto-crafting)."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_STONE
        grid.loose[4, 4, 2] = True
        grid.visible[4, 4, 2] = True
        ms.pick_up(4, 4, 2)

        # Target is stone and visible
        grid.grid[0, 0, 0] = VOXEL_STONE
        grid.visible[0, 0, 0] = True

        errors = []
        bus.subscribe("error_message", lambda **kw: errors.append(kw))

        assert ms.drop(0, 0, 0) is False
        assert len(errors) == 1
        assert "solid" in errors[0]["text"].lower()


# ── Door toggle territory restrictions ────────────────────────────────


class TestDoorToggleTerritoryRestrictions:
    def test_cannot_toggle_door_outside_territory(self):
        """Non-visible door cannot be toggled."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_DOOR
        grid.loose[4, 4, 2] = False
        grid.block_state[4, 4, 2] = 1  # closed
        # visible is False

        bus.publish("voxel_left_clicked", x=4, y=4, z=2, mode="move")

        # Door should NOT have been toggled
        assert grid.get_block_state(4, 4, 2) == 1

    def test_can_toggle_visible_door(self):
        """Visible door can be toggled."""
        bus, grid, ms = _move_setup()
        grid.grid[4, 4, 2] = VOXEL_DOOR
        grid.loose[4, 4, 2] = False
        grid.block_state[4, 4, 2] = 1  # closed
        grid.visible[4, 4, 2] = True

        events = []
        bus.subscribe("door_toggled", lambda **kw: events.append(kw))

        bus.publish("voxel_left_clicked", x=4, y=4, z=2, mode="move")

        assert grid.get_block_state(4, 4, 2) == 0  # now open
        assert len(events) == 1


# ===========================================================================
# Territory timing: immediate recompute on voxel changes
# (from test_rendering_fixes.py)
# ===========================================================================


class TestTerritoryTimingOnDig:
    """Visibility updates immediately on voxel_changed, not delayed."""

    def test_visibility_updates_after_voxel_change(self):
        """Adjacent blocks become visible immediately when air is created."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 4] = VOXEL_CORE
        grid.grid[4, 4, 3] = VOXEL_AIR  # Air adjacent to core

        territory = ClaimedTerritorySystem(eb, grid, core_x=4, core_y=4, core_z=4)
        # Air at (4,4,3) should be claimed, stone at (4,4,2) should be visible
        assert grid.is_visible(4, 4, 2), "Stone adjacent to claimed air should be visible"

        # Now dig (4,4,2) -> set to air via event bus
        grid.set(4, 4, 2, VOXEL_AIR, event_bus=eb)
        # Territory should recompute immediately on voxel_changed
        # New stone at (4,4,1) should now be visible
        assert grid.is_visible(4, 4, 1), (
            "Stone at (4,4,1) should become visible after air created at (4,4,2)"
        )

    def test_visible_changes_trigger_event(self):
        """When visibility changes, claimed_territory_changed event fires."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 4] = VOXEL_CORE
        grid.grid[4, 4, 3] = VOXEL_AIR

        territory = ClaimedTerritorySystem(eb, grid, core_x=4, core_y=4, core_z=4)

        events = []
        eb.subscribe("claimed_territory_changed", lambda **kw: events.append(1))

        # Create new air, expanding visibility
        grid.set(4, 4, 2, VOXEL_AIR, event_bus=eb)
        assert len(events) >= 1, "claimed_territory_changed should fire on visibility change"

    def test_dig_complete_triggers_recompute(self):
        """dig_complete event triggers immediate territory recompute."""
        eb = EventBus()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[:] = VOXEL_STONE
        grid.grid[4, 4, 4] = VOXEL_CORE
        grid.grid[4, 4, 3] = VOXEL_AIR

        territory = ClaimedTerritorySystem(eb, grid, core_x=4, core_y=4, core_z=4)

        # Simulate dig complete by making block loose (doesn't change type)
        # but publish dig_complete event
        events = []
        eb.subscribe("claimed_territory_changed", lambda **kw: events.append(1))

        # Manually change grid and fire dig_complete
        grid.grid[4, 4, 2] = VOXEL_AIR  # Simulate removal
        eb.publish("dig_complete", x=4, y=4, z=2)

        # Territory should have recomputed and (4,4,1) should now be visible
        assert grid.is_visible(4, 4, 1), (
            "Stone at (4,4,1) should become visible after dig_complete at (4,4,2)"
        )

    def test_no_seed_handles_gracefully(self):
        """When core has no traversable neighbors, system handles gracefully."""
        eb = EventBus()
        grid = VoxelGrid(width=4, depth=4, height=4)
        grid.grid[:] = VOXEL_STONE
        grid.grid[2, 2, 2] = VOXEL_CORE
        # No air adjacent to core — all neighbors are stone

        # Should not crash
        territory = ClaimedTerritorySystem(eb, grid, core_x=2, core_y=2, core_z=2)
        # Core itself should still be visible
        assert grid.is_visible(2, 2, 2), "Core should always be visible"
        # Everything else should be invisible
        grid.visible[2, 2, 2] = False  # temporarily unset for check
        assert not np.any(grid.visible), "No other block should be visible when core has no air"
        grid.visible[2, 2, 2] = True  # restore
