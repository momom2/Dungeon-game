"""Tests for fog-of-war A* pathfinder operating on PersonalMap.

Dependencies: intruders.personal_pathfinder, intruders.personal_map,
    intruders.archetypes, config
Dependents: (none)
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from dungeon_builder.intruders.personal_pathfinder import PersonalPathfinder
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.archetypes import (
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
)
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DOOR,
    VOXEL_LAVA,
    VOXEL_WATER,
    VOXEL_REINFORCED_WALL,
    VOXEL_BEDROCK,
    VOXEL_SPIKE,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_IRON_BARS,
    VOXEL_FLOODGATE,
    VOXEL_PRESSURE_PLATE,
    VOXEL_PIPE,
    VOXEL_PUMP,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_ALARM_BELL,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_STEAM_VENT,
    HAZARD_PATH_COST,
)


def _reveal_line(pm: PersonalMap, y_start: int, y_end: int, z: int = 0,
                 x: int = 0, vtype: int = VOXEL_AIR):
    """Reveal a horizontal line of cells in the personal map."""
    for y in range(y_start, y_end + 1):
        pm.reveal(x, y, z, vtype)


# ── Basic pathfinding ───────────────────────────────────────────────


class TestBasicPaths:
    def test_same_start_and_goal(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 0, 0), INQUISITOR)
        assert path == [(0, 0, 0)]

    def test_straight_line(self):
        pm = PersonalMap()
        _reveal_line(pm, 0, 5)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 5, 0), INQUISITOR)
        assert path is not None
        assert path[0] == (0, 0, 0)
        assert path[-1] == (0, 5, 0)
        assert len(path) == 6

    def test_no_path_returns_none(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 5, 0, VOXEL_AIR)
        # Gap between -- no intermediate cells revealed
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 5, 0), INQUISITOR)
        assert path is None

    def test_goal_unrevealed_returns_none(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 5, 0), INQUISITOR)
        assert path is None

    def test_path_around_wall(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)  # Wall!
        pm.reveal(1, 0, 0, VOXEL_AIR)
        pm.reveal(1, 1, 0, VOXEL_AIR)
        pm.reveal(1, 2, 0, VOXEL_AIR)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is not None
        assert (0, 1, 0) not in path  # Doesn't go through wall
        assert path[-1] == (0, 2, 0)


# ── Unrevealed cells ────────────────────────────────────────────────


class TestUnrevealed:
    def test_unrevealed_cells_impassable(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # (0,1,0) not revealed -- should block path
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is None

    def test_partial_reveal_finds_path(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_AIR)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is not None
        assert len(path) == 3


# ── Door traversal ──────────────────────────────────────────────────


class TestDoorTraversal:
    def test_open_door_traversable_by_all(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_DOOR, block_state=0)  # Open
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is not None

    def test_closed_door_blocked_for_non_interacters(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_DOOR, block_state=1)  # Closed
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Alchemist can't bash or lockpick
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), ALCHEMIST)
        assert path is None

    def test_closed_door_lockpicked_by_explorer(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_DOOR, block_state=1)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Explorer has can_lockpick=True
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EXPLORER)
        assert path is not None
        assert (0, 1, 0) in path

    def test_closed_door_bashed_by_inquisitor(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_DOOR, block_state=1)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Inquisitor has can_bash_door=True
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is not None


# ── Digger traversal ────────────────────────────────────────────────


class TestDiggerTraversal:
    def test_mole_tamer_familiars_cannot_dig_through_stone(self):
        """Mole Tamer has can_dig=False (familiars dig, not the tamer itself)."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), MOLE_TAMER)
        assert path is None

    def test_non_digger_blocked_by_stone(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is None

    def test_no_one_digs_reinforced(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_REINFORCED_WALL)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        for arch in [INQUISITOR, MOLE_TAMER, HERO]:
            path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), arch)
            assert path is None, f"{arch.name} should not pass through reinforced wall"

    def test_no_one_digs_bedrock(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_BEDROCK)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is None


# ── Flyer traversal ─────────────────────────────────────────────────


class TestFlyerTraversal:
    def test_flyer_moves_vertically_through_air(self):
        pm = PersonalMap()
        pm.reveal(5, 5, 0, VOXEL_AIR)
        pm.reveal(5, 5, 1, VOXEL_AIR)
        pm.reveal(5, 5, 2, VOXEL_AIR)
        # Eidolon has can_fly=True
        path = PersonalPathfinder.find_path(pm, (5, 5, 0), (5, 5, 2), EIDOLON)
        assert path is not None
        assert len(path) == 3

    def test_non_flyer_cannot_go_up_through_air(self):
        pm = PersonalMap()
        pm.reveal(5, 5, 0, VOXEL_AIR)
        pm.reveal(5, 5, 1, VOXEL_AIR)
        # Inquisitor can't fly up
        path = PersonalPathfinder.find_path(pm, (5, 5, 1), (5, 5, 0), INQUISITOR)
        assert path is None

    def test_non_flyer_uses_slope_to_go_up(self):
        pm = PersonalMap()
        pm.reveal(5, 5, 1, VOXEL_AIR)
        pm.reveal(5, 5, 0, VOXEL_SLOPE)  # Slope at z=0
        path = PersonalPathfinder.find_path(pm, (5, 5, 1), (5, 5, 0), INQUISITOR)
        assert path is not None

    def test_non_flyer_uses_stairs_to_go_up(self):
        pm = PersonalMap()
        pm.reveal(5, 5, 1, VOXEL_AIR)
        pm.reveal(5, 5, 0, VOXEL_STAIRS)
        path = PersonalPathfinder.find_path(pm, (5, 5, 1), (5, 5, 0), INQUISITOR)
        assert path is not None

    def test_non_flyer_can_fall_down(self):
        pm = PersonalMap()
        pm.reveal(5, 5, 0, VOXEL_AIR)
        pm.reveal(5, 5, 1, VOXEL_AIR)
        # Going deeper (z+1) is falling -- should be allowed
        path = PersonalPathfinder.find_path(pm, (5, 5, 0), (5, 5, 1), INQUISITOR)
        assert path is not None


# ── Fire-immune traversal (equipment-driven) ──────────────────────


class TestFireImmuneTraversal:
    def test_fire_immune_through_lava(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_LAVA)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Use has_fire_immunity parameter (equipment-driven)
        path = PersonalPathfinder.find_path(
            pm, (0, 0, 0), (0, 2, 0), ALCHEMIST,
            has_fire_immunity=True,
        )
        assert path is not None

    def test_non_immune_blocked_by_lava(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_LAVA)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(
            pm, (0, 0, 0), (0, 2, 0), INQUISITOR,
            has_fire_immunity=False,
        )
        assert path is None


# ── Water / reinforced wall ─────────────────────────────────────────


class TestImpassables:
    def test_water_blocks_all(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_WATER)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        for arch in [INQUISITOR, EXPLORER, MOLE_TAMER, ALCHEMIST, EIDOLON]:
            path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), arch)
            assert path is None, f"{arch.name} should not pass through water"

    def test_reinforced_wall_blocks_all(self):
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_REINFORCED_WALL)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        for arch in [INQUISITOR, MOLE_TAMER, HERO]:
            path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), arch)
            assert path is None, f"{arch.name} should not pass through reinforced wall"


# ── Hazard avoidance ────────────────────────────────────────────────


class TestHazardAvoidance:
    def test_cunning_avoids_hazards_if_alternative(self):
        """High-cunning intruder avoids spike if safe detour exists."""
        pm = PersonalMap()
        # Direct: (0,0) -> (0,1)[spike] -> (0,2)
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_AIR)
        pm.hazards.add((0, 1, 0))  # Marked as hazard
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Detour: (0,0) -> (1,0) -> (1,1) -> (1,2) -> (0,2)
        pm.reveal(1, 0, 0, VOXEL_AIR)
        pm.reveal(1, 1, 0, VOXEL_AIR)
        pm.reveal(1, 2, 0, VOXEL_AIR)
        # Gloomwarden has cunning=0.6 (>=0.5)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), GLOOMWARDEN)
        assert path is not None
        # Should avoid the hazard cell
        assert (0, 1, 0) not in path

    def test_low_cunning_walks_through_hazard(self):
        """Low-cunning intruder ignores hazards, takes direct path."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_AIR)
        pm.hazards.add((0, 1, 0))
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Hero has cunning=0.1 (< 0.5)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), HERO)
        assert path is not None
        assert (0, 1, 0) in path  # Direct path through hazard


# ── Phase-walk ──────────────────────────────────────────────────────


class TestPhaseWalk:
    """Test phase-walk: pathfinder should find path through thin walls
    when archetype.phase_thickness > 0."""

    def test_eidolon_phases_through_thin_wall(self):
        """Eidolon (phase_thickness=2) can phase through a revealed solid wall
        if there is revealed air on the other side."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)  # Thin wall (thickness 1)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Eidolon has phase_thickness=2 and can_fly=True
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is not None
        assert path[-1] == (0, 2, 0)

    def test_non_phaser_cannot_pass_thin_wall(self):
        """Non-phase archetype cannot pass through a thin wall."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Inquisitor has phase_thickness=0
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), INQUISITOR)
        assert path is None

    def test_phase_prefers_air_over_phasing(self):
        """When an air detour exists, phase-walk should prefer it due to higher cost."""
        pm = PersonalMap()
        # Direct path through stone wall
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)  # Wall
        pm.reveal(0, 2, 0, VOXEL_AIR)
        # Air detour
        pm.reveal(1, 0, 0, VOXEL_AIR)
        pm.reveal(1, 1, 0, VOXEL_AIR)
        pm.reveal(1, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is not None
        # Phase-walk cost is 5.0 per cell, air is 1.0.
        # The air detour is 5 steps (0,0)->(1,0)->(1,1)->(1,2)->(0,2) = cost 4.0
        # Phase direct is (0,0)->(0,1)->(0,2) = cost 5.0+1.0 = 6.0
        # Eidolon should prefer the air detour
        assert (0, 1, 0) not in path


class TestPhaseWalkDualCost:
    """Test dual-cost augmented-state A* for phase-walk.

    The wall budget is a hard constraint (not a heuristic cost).  The wall
    counter resets on entering walkable cells and blocks when exceeding
    phase_thickness.
    """

    def test_wall_budget_exact_match(self):
        """Eidolon (phase_thickness=2) can phase through exactly 2 wall cells."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_STONE)
        pm.reveal(0, 3, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 3, 0), EIDOLON)
        assert path is not None
        assert path[-1] == (0, 3, 0)

    def test_wall_budget_exceeded(self):
        """Eidolon cannot phase through 3 consecutive walls (budget is 2)."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_STONE)
        pm.reveal(0, 3, 0, VOXEL_STONE)
        pm.reveal(0, 4, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 4, 0), EIDOLON)
        assert path is None

    def test_wall_counter_resets_at_air(self):
        """Wall counter resets to 0 when entering air, allowing multiple phases."""
        pm = PersonalMap()
        # Wall(1) -> Air -> Wall(1) -> Air: two separate 1-thick walls
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        pm.reveal(0, 3, 0, VOXEL_STONE)
        pm.reveal(0, 4, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 4, 0), EIDOLON)
        assert path is not None
        assert path[-1] == (0, 4, 0)

    def test_reinforced_wall_blocks_phase(self):
        """Phase-walkers cannot phase through reinforced walls regardless of budget."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_REINFORCED_WALL)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is None

    def test_bedrock_blocks_phase(self):
        """Phase-walkers cannot phase through bedrock."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_BEDROCK)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is None

    def test_water_blocks_phase(self):
        """Phase-walkers cannot phase through water."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_WATER)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is None

    def test_iron_bars_block_phase(self):
        """Phase-walkers cannot phase through iron bars."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_IRON_BARS)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is None

    def test_custom_phase_thickness_1(self):
        """Custom archetype with phase_thickness=1 can only do 1 wall cell."""
        phase1 = replace(EIDOLON, phase_thickness=1)
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), phase1)
        assert path is not None

        # But 2 consecutive walls should fail
        pm2 = PersonalMap()
        pm2.reveal(0, 0, 0, VOXEL_AIR)
        pm2.reveal(0, 1, 0, VOXEL_STONE)
        pm2.reveal(0, 2, 0, VOXEL_STONE)
        pm2.reveal(0, 3, 0, VOXEL_AIR)
        path2 = PersonalPathfinder.find_path(pm2, (0, 0, 0), (0, 3, 0), phase1)
        assert path2 is None

    def test_phase_path_includes_wall_cells(self):
        """Phase path should include the wall cells traversed."""
        pm = PersonalMap()
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 2, 0), EIDOLON)
        assert path is not None
        # Path should be: air -> wall -> air
        assert (0, 1, 0) in path

    def test_phase_route_through_gap_in_thick_wall(self):
        """When a thick wall has a gap (air cell), phase-walker should use it
        to reset the wall counter and traverse a longer wall section."""
        pm = PersonalMap()
        # Layout: AIR - STONE - AIR - STONE - AIR
        # Two 1-thick walls separated by air gap: traversable even with budget 2
        pm.reveal(0, 0, 0, VOXEL_AIR)
        pm.reveal(0, 1, 0, VOXEL_STONE)
        pm.reveal(0, 2, 0, VOXEL_AIR)   # Gap resets counter
        pm.reveal(0, 3, 0, VOXEL_STONE)
        pm.reveal(0, 4, 0, VOXEL_AIR)
        phase1 = replace(EIDOLON, phase_thickness=1)
        path = PersonalPathfinder.find_path(pm, (0, 0, 0), (0, 4, 0), phase1)
        assert path is not None
        assert (0, 2, 0) in path  # Must go through the gap


# ── Max iterations ──────────────────────────────────────────────────


class TestMaxIterations:
    def test_returns_none_when_exceeded(self):
        pm = PersonalMap()
        for y in range(50):
            pm.reveal(0, y, 0, VOXEL_AIR)
        path = PersonalPathfinder.find_path(
            pm, (0, 0, 0), (0, 49, 0), INQUISITOR, max_iterations=5
        )
        assert path is None  # Not enough iterations to find long path


# ======================================================================
# Tests from test_new_block_pathfinding.py
# ======================================================================


# ── Helpers ──────────────────────────────────────────────────────────


def _make_corridor(pmap: PersonalMap, length: int = 5, block_at: int = 2,
                   block_type: int = VOXEL_AIR, block_state: int = 0
                   ) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Create a 1-D corridor of air with one block of *block_type* in the middle.

    Returns ``(start, goal)`` positions.
    """
    for i in range(length):
        if i == block_at:
            pmap.reveal(i, 0, 0, block_type, block_state)
        else:
            pmap.reveal(i, 0, 0, VOXEL_AIR)
    return (0, 0, 0), (length - 1, 0, 0)


# ── Iron bars -- always impassable ───────────────────────────────────


class TestIronBarsImpassable:

    def test_iron_bars_blocks_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_IRON_BARS)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is None


# ── Floodgate -- state-dependent ─────────────────────────────────────


class TestFloodgatePathfinding:

    def test_closed_floodgate_blocks_path(self):
        """A closed floodgate (block_state=1) is impassable."""
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_FLOODGATE,
                                     block_state=1)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is None

    def test_open_floodgate_allows_path(self):
        """An open floodgate (block_state=0) is passable."""
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_FLOODGATE,
                                     block_state=0)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert start in path
        assert goal in path
        assert (2, 0, 0) in path  # passes through the floodgate cell


# ── Pressure plate -- traversable, cunning adds hazard cost ──────────


class TestPressurePlatePathfinding:

    def test_pressure_plate_traversable(self):
        """Non-cunning archetype walks right through."""
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_PRESSURE_PLATE)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert (2, 0, 0) in path

    def test_pressure_plate_cunning_cost(self):
        """A cunning archetype still finds a path but incurs higher cost.

        With a single-corridor layout there is no alternative route, so the
        path must still go through the pressure plate.  We verify the plate
        is in the path and, when an alternative air-only route exists, the
        cunning archetype prefers it.
        """
        cunning_arch = replace(INQUISITOR, cunning=0.8)
        # Single corridor -- no alternative, must pass through
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_PRESSURE_PLATE)
        path = PersonalPathfinder.find_path(pmap, start, goal, cunning_arch)
        assert path is not None
        assert (2, 0, 0) in path

        # Now provide an alternative air-only corridor (row y=1).
        # The cunning archetype should prefer the air bypass because the
        # pressure plate is a hazard (cost = 1 + HAZARD_PATH_COST).
        pmap2 = PersonalMap()
        # Main corridor with pressure plate at (2,0,0)
        for i in range(5):
            if i == 2:
                pmap2.reveal(i, 0, 0, VOXEL_PRESSURE_PLATE)
            else:
                pmap2.reveal(i, 0, 0, VOXEL_AIR)
        # Bypass corridor at y=1 (slightly longer: 7 cells, but no hazard)
        for i in range(5):
            pmap2.reveal(i, 1, 0, VOXEL_AIR)

        path2 = PersonalPathfinder.find_path(pmap2, (0, 0, 0), (4, 0, 0),
                                             cunning_arch)
        assert path2 is not None
        # The cunning archetype should avoid (2, 0, 0) by going via y=1
        assert (2, 0, 0) not in path2


# ── Pipe -- impassable solid ─────────────────────────────────────────


class TestPipeImpassable:

    def test_pipe_blocks_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_PIPE)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is None


# ── Pump -- impassable solid ─────────────────────────────────────────


class TestPumpImpassable:

    def test_pump_blocks_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_PUMP)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is None


# ── Gold bait -- traversable (interaction handles effect) ────────────


class TestGoldBaitTraversable:

    def test_gold_bait_allows_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_GOLD_BAIT)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert (2, 0, 0) in path


# ── Heat beacon -- traversable ───────────────────────────────────────


class TestHeatBeaconTraversable:

    def test_heat_beacon_allows_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_HEAT_BEACON)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert (2, 0, 0) in path


# ── Alarm bell -- traversable ────────────────────────────────────────


class TestAlarmBellTraversable:

    def test_alarm_bell_allows_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_ALARM_BELL)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert (2, 0, 0) in path


# ── Fragile floor -- traversable (looks like stone to intruders) ─────


class TestFragileFloorTraversable:

    def test_fragile_floor_allows_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_FRAGILE_FLOOR)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert (2, 0, 0) in path


# ── Steam vent -- traversable ────────────────────────────────────────


class TestSteamVentTraversable:

    def test_steam_vent_allows_path(self):
        pmap = PersonalMap()
        start, goal = _make_corridor(pmap, block_type=VOXEL_STEAM_VENT)
        path = PersonalPathfinder.find_path(pmap, start, goal, INQUISITOR)
        assert path is not None
        assert (2, 0, 0) in path
