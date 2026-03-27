"""Tests for Mole Tamer familiar commanding AI.

Verifies that Mole Tamers actively command their familiars to dig
obstacles out of their path, creating a bypass-focused archetype that
relies entirely on its familiars for traversal through solid terrain.

Dependencies: intruders.decision, intruders.familiar, intruders.agent,
    intruders.archetypes, intruders.personal_map, world.voxel_grid,
    world.pathfinding, dungeon_core.core, core.event_bus, utils.rng, config
Dependents: (test-only)
"""

import pytest

from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    MOLE_TAMER,
    IntruderObjective,
)
from dungeon_builder.intruders.decision import IntruderAI
from dungeon_builder.intruders.familiar import (
    Familiar,
    FamiliarState,
    spawn_familiars,
    order_dig,
    update_familiar,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.utils.rng import SeededRNG
import dungeon_builder.config as _cfg


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_ai(
    grid_w: int = 10, grid_d: int = 10, grid_h: int = 10,
    core_pos: tuple[int, int, int] = (5, 5, 5),
) -> tuple[IntruderAI, VoxelGrid, EventBus]:
    """Create a minimal IntruderAI with a small voxel grid."""
    eb = EventBus()
    grid = VoxelGrid(grid_w, grid_d, grid_h)
    pathfinder = AStarPathfinder(grid)
    cx, cy, cz = core_pos
    grid.set(cx, cy, cz, _cfg.VOXEL_CORE)
    core = DungeonCore(eb, cx, cy, cz)
    rng = SeededRNG(42)
    ai = IntruderAI(eb, grid, pathfinder, core, rng)
    return ai, grid, eb


def _make_tamer(
    ai: IntruderAI,
    x: int = 2, y: int = 5, z: int = 5,
) -> Intruder:
    """Create a Mole Tamer intruder attached to the AI."""
    tamer = Intruder(
        intruder_id=ai._next_id,
        x=x, y=y, z=z,
        archetype=MOLE_TAMER,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=PersonalMap(),
    )
    ai._next_id += 1
    tamer.state = IntruderState.ADVANCING
    # Spawn familiars
    tamer.familiars = spawn_familiars(tamer, ai._next_familiar_id)
    ai._next_familiar_id += len(tamer.familiars)
    ai.intruders.append(tamer)
    return tamer


# ── Dig target finding ───────────────────────────────────────────────────


class TestTamerDigTargetFinding:
    """Verify _find_tamer_dig_targets identifies correct blocks."""

    def test_path_lookahead_finds_stone(self):
        """Scan ahead on path finds stone blocks as dig targets."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Place stone on the path ahead
        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        grid.set(4, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5), (4, 5, 5), (5, 5, 5)]
        tamer.path_index = 0

        targets = ai._find_tamer_dig_targets(tamer)
        assert (3, 5, 5) in targets
        assert (4, 5, 5) in targets

    def test_path_lookahead_skips_air(self):
        """Air blocks on the path are not dig targets."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Path through air
        tamer.path = [(3, 5, 5), (4, 5, 5), (5, 5, 5)]
        tamer.path_index = 0

        targets = ai._find_tamer_dig_targets(tamer)
        assert len(targets) == 0

    def test_path_lookahead_skips_non_diggable(self):
        """NON_DIGGABLE blocks (bedrock, reinforced) are not targets."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        grid.set(3, 5, 5, _cfg.VOXEL_BEDROCK)
        tamer.path = [(3, 5, 5), (4, 5, 5)]
        tamer.path_index = 0

        targets = ai._find_tamer_dig_targets(tamer)
        assert (3, 5, 5) not in targets

    def test_path_lookahead_limited_by_config(self):
        """Only scans TAMER_DIG_LOOKAHEAD steps ahead."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Place stone at positions beyond lookahead
        for i in range(8):
            grid.set(3 + i, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3 + i, 5, 5) for i in range(8)]
        tamer.path_index = 0

        targets = ai._find_tamer_dig_targets(tamer)
        assert len(targets) == _cfg.TAMER_DIG_LOOKAHEAD

    def test_pathless_fallback_finds_adjacent_diggable(self):
        """Without a path, scan adjacent cells toward core."""
        ai, grid, _ = _make_ai(core_pos=(5, 5, 5))
        tamer = _make_tamer(ai, x=2, y=5, z=5)
        tamer.path = None

        # Place stone adjacent to tamer, between tamer and core
        grid.set(3, 5, 5, _cfg.VOXEL_STONE)

        targets = ai._find_tamer_dig_targets(tamer)
        assert (3, 5, 5) in targets

    def test_pathless_fallback_sorted_by_distance_to_goal(self):
        """Adjacent dig targets sorted closest-to-core first."""
        ai, grid, _ = _make_ai(core_pos=(9, 5, 5))
        tamer = _make_tamer(ai, x=5, y=5, z=5)
        tamer.path = None

        # Stone on both sides
        grid.set(6, 5, 5, _cfg.VOXEL_STONE)  # Closer to core
        grid.set(4, 5, 5, _cfg.VOXEL_STONE)  # Farther from core

        targets = ai._find_tamer_dig_targets(tamer)
        assert targets[0] == (6, 5, 5)  # Closer first


# ── Command issuing ──────────────────────────────────────────────────────


class TestTamerCommandIssuing:
    """Verify _command_familiars assigns familiars to dig targets."""

    def test_assigns_following_familiars_to_targets(self):
        """FOLLOWING familiars get assigned dig targets."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5)]
        tamer.path_index = 0

        ai._command_familiars(tamer)

        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        assert len(digging) >= 1
        assert digging[0].dig_target == (3, 5, 5)

    def test_does_not_double_assign_same_target(self):
        """Two familiars don't get assigned the same target."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Only one dig target
        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5)]
        tamer.path_index = 0

        ai._command_familiars(tamer)

        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        # Only one should be assigned (one target available)
        assert len(digging) == 1

    def test_multiple_targets_multiple_familiars(self):
        """Multiple dig targets get multiple familiars assigned."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        grid.set(4, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5), (4, 5, 5)]
        tamer.path_index = 0

        ai._command_familiars(tamer)

        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        assert len(digging) == 2
        targets = {f.dig_target for f in digging}
        assert targets == {(3, 5, 5), (4, 5, 5)}

    def test_no_assignment_when_no_targets(self):
        """No familiars assigned when path is clear."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Path through air
        tamer.path = [(3, 5, 5), (4, 5, 5)]
        tamer.path_index = 0

        ai._command_familiars(tamer)

        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        assert len(digging) == 0


# ── Recall distant familiars ─────────────────────────────────────────────


class TestTamerRecallsDistant:
    """Verify familiars beyond max distance are recalled."""

    def test_distant_familiar_recalled(self):
        """Familiars far from tamer are recalled to FOLLOWING."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Send a familiar far away and mark it digging
        f = tamer.familiars[0]
        f.state = FamiliarState.DIGGING
        f.dig_target = (9, 9, 9)
        f.x, f.y, f.z = 9, 9, 9  # Very far from tamer

        ai._command_familiars(tamer)

        assert f.state == FamiliarState.FOLLOWING
        assert f.dig_target is None

    def test_nearby_familiar_not_recalled(self):
        """Familiars within range keep digging."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        f = tamer.familiars[0]
        f.state = FamiliarState.DIGGING
        f.dig_target = (3, 5, 5)
        f.x, f.y, f.z = 3, 5, 5  # Adjacent to tamer

        ai._command_familiars(tamer)

        assert f.state == FamiliarState.DIGGING


# ── Unruly familiars ─────────────────────────────────────────────────────


class TestUnrulyNotCommanded:
    """Verify unruly familiars are not assigned new targets."""

    def test_unruly_familiar_not_assigned(self):
        """Unruly familiars are skipped for dig assignment."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Set all familiars to unruly
        for f in tamer.familiars:
            f.state = FamiliarState.UNRULY

        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5)]
        tamer.path_index = 0

        ai._command_familiars(tamer)

        # None should be digging
        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        assert len(digging) == 0

    def test_dead_familiar_not_assigned(self):
        """Dead familiars are skipped."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        for f in tamer.familiars:
            f.state = FamiliarState.DEAD

        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5)]
        tamer.path_index = 0

        ai._command_familiars(tamer)

        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        assert len(digging) == 0


# ── Integration: tick_familiars ──────────────────────────────────────────


class TestTamerTickIntegration:
    """Verify _tick_familiars integrates update + commanding."""

    def test_tick_familiars_updates_and_commands(self):
        """At TAMER_COMMAND_INTERVAL ticks, familiars get commands."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        grid.set(3, 5, 5, _cfg.VOXEL_STONE)
        tamer.path = [(3, 5, 5)]
        tamer.path_index = 0

        # Tick at a multiple of TAMER_COMMAND_INTERVAL
        tick = _cfg.TAMER_COMMAND_INTERVAL
        ai._tick_familiars(tamer, tick)

        # At least one familiar should be digging
        digging = [
            f for f in tamer.familiars
            if f.state == FamiliarState.DIGGING
        ]
        assert len(digging) >= 1

    def test_non_command_tick_still_updates(self):
        """Off-interval ticks still update familiar state machines."""
        ai, grid, _ = _make_ai()
        tamer = _make_tamer(ai, x=2, y=5, z=5)

        # Place familiar far from tamer — it should step closer
        f = tamer.familiars[0]
        f.x, f.y, f.z = 8, 5, 5
        f.ticks_since_move = _cfg.FAMILIAR_MOVE_INTERVAL - 1

        # Use a tick that's NOT a command interval
        tick = 1
        ai._tick_familiars(tamer, tick)

        # Familiar should have moved closer (FOLLOWING state moves toward tamer)
        assert f.x < 8 or f.y != 5 or f.z != 5
