"""Intruder AI decision engine tests.

Tests cover the IntruderAI state machine: spawning, vision, movement,
retreat, door interaction, spike interaction, treasure collection,
lava death, tarp fall, attacking, death handling, game over, cleanup,
and pillaging.

Dependencies: core.event_bus, world.voxel_grid, world.pathfinding,
    dungeon_core.core, intruders.agent, intruders.archetypes,
    intruders.personal_map, intruders.decision, intruders.party,
    utils.rng, config
Dependents: (none — test-only)
"""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.decision import IntruderAI
from dungeon_builder.intruders.party import Party
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_DOOR,
    VOXEL_SPIKE,
    VOXEL_TREASURE,
    VOXEL_TARP,
    VOXEL_LAVA,
    VOXEL_DIRT,
    VOXEL_REINFORCED_WALL,
    SURFACE_Z,
    DOOR_BASH_TICKS,
    DOOR_LOCKPICK_TICKS,
    TREASURE_GRAB_TICKS,
    DIG_DURATION,
    SPIKE_DAMAGE,
    INTRUDER_PARTY_SPAWN_INTERVAL,
    MAX_PARTIES,
)


# -- Helpers ---------------------------------------------------------------


# Core depth below surface -- all helpers use SURFACE_Z + _CORE_DEPTH
_CORE_DEPTH = 3


def _make_grid(width=10, depth=10, height=None):
    """Create a grid of stone with a full air surface at SURFACE_Z.

    Height is auto-calculated to fit SURFACE_Z + underground layers.
    """
    if height is None:
        height = SURFACE_Z + _CORE_DEPTH + 2  # room for core + floor below
    grid = VoxelGrid(width=width, depth=depth, height=height)
    grid.grid[:] = VOXEL_STONE
    grid.grid[:, :, :SURFACE_Z + 1] = VOXEL_AIR  # sky + surface layer
    return grid


def _make_corridor_grid():
    """Grid with surface, shaft, and corridor to core.

    Layout:
      z=0..SURFACE_Z: air (sky layers + surface)
      (5,0) z=SURFACE_Z..SURFACE_Z+3: vertical shaft
      (5,0-5) z=SURFACE_Z+3: horizontal corridor
      Core at (5, 5, SURFACE_Z+3)
    """
    grid = _make_grid()
    core_z = SURFACE_Z + _CORE_DEPTH
    for z in range(SURFACE_Z, core_z + 1):
        grid.grid[5, 0, z] = VOXEL_AIR
    for y in range(0, 6):
        grid.grid[5, y, core_z] = VOXEL_AIR
    return grid


def _make_simple_dungeon():
    """Grid with surface, shaft, and core room."""
    height = SURFACE_Z + _CORE_DEPTH + 2
    grid = VoxelGrid(width=10, depth=10, height=height)
    grid.grid[:] = VOXEL_STONE
    # Sky/surface air
    grid.grid[:, :, :SURFACE_Z + 1] = VOXEL_AIR
    core_z = SURFACE_Z + _CORE_DEPTH
    # Shaft from (5,0) surface to core
    for z in range(SURFACE_Z, core_z + 1):
        grid.grid[5, 0, z] = VOXEL_AIR
    # Corridor at core_z from (5,0) to (5,5)
    for y in range(0, 6):
        grid.grid[5, y, core_z] = VOXEL_AIR
    return grid


def _make_ai(grid=None, core_pos=None, core_hp=100, seed=42):
    """Create an IntruderAI with the given grid setup."""
    bus = EventBus()
    if grid is None:
        grid = _make_corridor_grid()
    if core_pos is None:
        core_pos = (5, 5, SURFACE_Z + _CORE_DEPTH)
    pf = AStarPathfinder(grid)
    core = DungeonCore(bus, *core_pos, hp=core_hp)
    rng = SeededRNG(seed)
    ai = IntruderAI(bus, grid, pf, core, rng)
    return ai, bus, grid, core, rng


def _make_intruder(
    intruder_id=1, x=0, y=0, z=None, arch=INQUISITOR,
    objective=IntruderObjective.DESTROY_CORE,
):
    if z is None:
        z = SURFACE_Z
    return Intruder(intruder_id, x, y, z, arch, objective, PersonalMap())


# -- Party spawning --------------------------------------------------------


class TestPartySpawning:
    def test_spawn_party_creates_members(self):
        ai, bus, grid, core, rng = _make_ai()
        ai._spawn_party()
        assert len(ai.intruders) > 0
        assert len(ai.parties) == 1
        assert all(i.state == IntruderState.ADVANCING for i in ai.intruders)

    def test_spawn_party_publishes_events(self):
        ai, bus, grid, core, rng = _make_ai()
        spawned = []
        bus.subscribe("intruder_spawned", lambda **kw: spawned.append(kw))
        ai._spawn_party()
        assert len(spawned) == len(ai.intruders)

    def test_spawn_party_assigns_party_id(self):
        ai, bus, grid, core, rng = _make_ai()
        ai._spawn_party()
        party = ai.parties[0]
        for m in party.members:
            assert m.party_id == party.id

    def test_tick_spawning_respects_max_parties(self):
        """The _tick_spawning method enforces MAX_PARTIES limit."""
        ai, bus, grid, core, rng = _make_ai()
        ai.spawning_enabled = True
        # Manually spawn MAX_PARTIES parties
        for _ in range(MAX_PARTIES):
            ai._spawn_party()
        assert len(ai.parties) == MAX_PARTIES

        # Now _tick_spawning should refuse to spawn more
        ai._spawn_timer = INTRUDER_PARTY_SPAWN_INTERVAL  # Ready to spawn
        ai._tick_spawning()
        assert len(ai.parties) == MAX_PARTIES  # No new party

    def test_spawning_disabled_by_default(self):
        ai, bus, grid, core, rng = _make_ai()
        bus.publish("tick", tick=1)
        assert len(ai.intruders) == 0


# -- Vision integration ----------------------------------------------------


class TestVisionIntegration:
    def test_intruder_reveals_nearby_cells(self):
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(1, 5, 0, SURFACE_Z)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._update_vision(intruder)

        assert intruder.personal_map.is_revealed(5, 0, SURFACE_Z)
        assert len(intruder.personal_map) > 1

    def test_gloomwarden_arcane_sight(self):
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(1, 5, 0, SURFACE_Z, arch=GLOOMWARDEN)
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        ai._update_vision(intruder)

        # Gloomwarden sees through walls via arcane sight (range=3)
        assert intruder.personal_map.is_revealed(5, 0, SURFACE_Z + _CORE_DEPTH)


# -- Movement and path following -------------------------------------------


class TestMovement:
    def test_intruder_follows_path_to_core(self):
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(1, 5, 0, SURFACE_Z)
        path = ai.pathfinder.find_path((5, 0, SURFACE_Z), (5, 5, SURFACE_Z + _CORE_DEPTH))
        assert path is not None
        intruder.path = path
        intruder.path_index = 1
        intruder.state = IntruderState.ADVANCING
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        for _ in range(100):
            ai._update_intruder(intruder)
            if intruder.state == IntruderState.ATTACKING:
                break

        assert intruder.state == IntruderState.ATTACKING

    def test_intruder_moves_publishes_event(self):
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(1, 5, 0, SURFACE_Z)
        intruder.path = [(5, 0, SURFACE_Z), (5, 1, SURFACE_Z)]
        intruder.path_index = 1
        intruder.state = IntruderState.ADVANCING
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        moves = []
        bus.subscribe("intruder_moved", lambda **kw: moves.append(kw))

        ai._update_advancing(intruder)

        assert len(moves) == 1
        assert intruder.pos == (5, 1, SURFACE_Z)


# -- Retreat behavior ------------------------------------------------------


class TestRetreat:
    def test_inquisitor_retreats_below_threshold(self):
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(1, 5, 3, SURFACE_Z + _CORE_DEPTH)
        intruder.state = IntruderState.ADVANCING
        intruder.path = ai.pathfinder.find_path(
            (5, 3, SURFACE_Z + _CORE_DEPTH), (5, 5, SURFACE_Z + _CORE_DEPTH),
        )
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        # INQUISITOR retreat_threshold=0.10, max_hp=120 -> retreat at <12 HP
        intruder.hp = 10
        ai._update_intruder(intruder)
        assert intruder.state == IntruderState.RETREATING

    def test_hero_never_retreats_on_hp(self):
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            1, 5, 3, SURFACE_Z + _CORE_DEPTH, arch=HERO,
        )
        intruder.state = IntruderState.ADVANCING
        intruder.path = [
            (5, 3, SURFACE_Z + _CORE_DEPTH),
            (5, 4, SURFACE_Z + _CORE_DEPTH),
        ]
        intruder.path_index = 1
        intruder.move_interval = 1
        # Give plenty of supplies so supply-based retreat does not trigger
        intruder.food = 999.0
        intruder.water = 999.0
        ai.intruders.append(intruder)

        intruder.hp = 1
        ai._update_intruder(intruder)
        assert intruder.state != IntruderState.RETREATING

    def test_retreating_intruder_escapes_at_surface(self):
        ai, bus, grid, core, rng = _make_ai()
        # Intruder already at surface, path points just past end
        intruder = _make_intruder(1, 5, 0, SURFACE_Z)
        intruder.state = IntruderState.RETREATING
        intruder.move_interval = 1
        intruder.path = [(5, 0, SURFACE_Z)]
        intruder.path_index = 1  # Past end of path
        ai.intruders.append(intruder)

        escaped = []
        bus.subscribe("intruder_escaped", lambda **kw: escaped.append(kw))

        # First call: ticks_since_move goes 0->1, since 1 < 1 is false,
        # _advance_along_path does nothing (path_index past end), then z==SURFACE_Z check
        ai._update_retreating(intruder)

        assert intruder.state == IntruderState.ESCAPED
        assert len(escaped) == 1


# -- Door interaction ------------------------------------------------------


class TestDoorInteraction:
    def _setup_door(self):
        """Grid with air corridor at z=SURFACE_Z+_CORE_DEPTH, closed door at (5,2,SURFACE_Z+_CORE_DEPTH)."""
        grid = _make_grid()
        core_z = SURFACE_Z + _CORE_DEPTH
        for z in range(SURFACE_Z, core_z + 1):
            grid.grid[5, 0, z] = VOXEL_AIR
        for y in range(0, 6):
            grid.grid[5, y, core_z] = VOXEL_AIR
        # Place closed door at (5, 2, core_z)
        grid.grid[5, 2, core_z] = VOXEL_DOOR
        grid.block_state[5, 2, core_z] = 1  # Closed
        return grid

    def test_inquisitor_bashes_closed_door(self):
        grid = self._setup_door()
        ai, bus, _, core, rng = _make_ai(grid=grid)
        core_z = SURFACE_Z + _CORE_DEPTH

        intruder = _make_intruder(1, 5, 1, core_z, arch=INQUISITOR)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, core_z), (5, 2, core_z), (5, 3, core_z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert intruder.state == IntruderState.INTERACTING
        assert intruder.interaction_type == "bash_door"
        # INQUISITOR damage=8, so bash_ticks = max(1, DOOR_BASH_TICKS - 8//2)
        expected_bash_ticks = max(1, DOOR_BASH_TICKS - INQUISITOR.damage // 2)
        assert intruder.interaction_ticks == expected_bash_ticks

    def test_explorer_lockpicks_closed_door(self):
        grid = self._setup_door()
        ai, bus, _, core, rng = _make_ai(grid=grid)
        core_z = SURFACE_Z + _CORE_DEPTH

        intruder = _make_intruder(1, 5, 1, core_z, arch=EXPLORER)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, core_z), (5, 2, core_z), (5, 3, core_z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert intruder.state == IntruderState.INTERACTING
        assert intruder.interaction_type == "lockpick"
        assert intruder.interaction_ticks == DOOR_LOCKPICK_TICKS

    def test_door_opens_after_interaction(self):
        grid = self._setup_door()
        ai, bus, _, core, rng = _make_ai(grid=grid)
        core_z = SURFACE_Z + _CORE_DEPTH

        intruder = _make_intruder(1, 5, 1, core_z, arch=INQUISITOR)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, core_z), (5, 2, core_z), (5, 3, core_z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)
        assert intruder.state == IntruderState.INTERACTING

        expected_bash_ticks = max(1, DOOR_BASH_TICKS - INQUISITOR.damage // 2)
        for _ in range(expected_bash_ticks):
            ai._update_interacting(intruder)

        assert grid.block_state[5, 2, core_z] == 0
        assert intruder.state == IntruderState.ADVANCING


# -- Spike interaction -----------------------------------------------------


class TestSpikeInteraction:
    def test_inquisitor_takes_half_spike_damage(self):
        """INQUISITOR has can_bash_door=True, so it takes half spike damage."""
        grid = _make_grid()
        for y in range(0, 5):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_SPIKE
        grid.block_state[5, 2, SURFACE_Z] = 1  # Extended

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=INQUISITOR)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        initial_hp = intruder.hp
        ai._update_advancing(intruder)

        assert intruder.hp == initial_hp - SPIKE_DAMAGE // 2
        assert intruder.pos == (5, 2, SURFACE_Z)

    def test_explorer_detects_and_avoids_spike(self):
        """EXPLORER has trap_detect_range=2, so it repaths around extended spikes."""
        grid = _make_grid()
        for y in range(0, 5):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_SPIKE
        grid.block_state[5, 2, SURFACE_Z] = 1  # Extended

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=EXPLORER)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        initial_hp = intruder.hp
        ai._update_advancing(intruder)

        # Explorer repaths rather than walking into the spike
        assert intruder.hp == initial_hp
        assert intruder.pos != (5, 2, SURFACE_Z)


# -- Mole Tamer (no innate digging) ---------------------------------------


class TestMoleTamerDigging:
    def test_mole_tamer_cannot_dig_itself(self):
        """MOLE_TAMER has can_dig=False; familiars dig, not the tamer."""
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_STONE

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=MOLE_TAMER)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        # MOLE_TAMER cannot dig, so it should repath instead of digging
        assert intruder.state != IntruderState.INTERACTING

    def test_mole_tamer_cannot_dig_reinforced(self):
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_REINFORCED_WALL

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=MOLE_TAMER)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert intruder.state != IntruderState.INTERACTING


# -- Treasure collection ---------------------------------------------------


class TestTreasureCollection:
    def test_explorer_collects_treasure(self):
        """EXPLORER has greed=0.7, so it stops to grab treasure."""
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_TREASURE

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=EXPLORER)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert intruder.state == IntruderState.INTERACTING
        assert intruder.interaction_type == "grab_treasure"

    def test_treasure_collected_after_interaction(self):
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_TREASURE

        ai, bus, _, core, rng = _make_ai(grid=grid)

        collected_events = []
        bus.subscribe(
            "intruder_collected_treasure",
            lambda **kw: collected_events.append(kw),
        )

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=EXPLORER)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)
        assert intruder.state == IntruderState.INTERACTING

        for _ in range(TREASURE_GRAB_TICKS):
            ai._update_interacting(intruder)

        assert grid.get(5, 2, SURFACE_Z) == VOXEL_AIR
        assert intruder.loot_count == 1
        assert len(collected_events) == 1

    def test_inquisitor_ignores_treasure(self):
        """INQUISITOR has greed=0.05, which is > 0, so it does collect.

        However, an intruder with greed=0 (like GLOOMWARDEN) would walk past.
        """
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_TREASURE

        ai, bus, _, core, rng = _make_ai(grid=grid)

        # GLOOMWARDEN has greed=0.0, so it ignores treasure
        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=GLOOMWARDEN)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z), (5, 3, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        # Gloomwarden walks right past treasure (greed=0.0)
        assert intruder.pos == (5, 2, SURFACE_Z)
        assert intruder.state == IntruderState.ADVANCING


# -- Lava death ------------------------------------------------------------


class TestLavaDeath:
    def test_non_fire_immune_dies_in_lava(self):
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_LAVA

        ai, bus, _, core, rng = _make_ai(grid=grid)

        died_events = []
        bus.subscribe("intruder_died", lambda **kw: died_events.append(kw))

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=INQUISITOR)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert intruder.state == IntruderState.DEAD
        assert len(died_events) == 1

    def test_eidolon_flies_over_lava(self):
        """EIDOLON has can_fly=True, so it passes over lava safely."""
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_LAVA

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=EIDOLON)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        # Eidolons have 0 food/water capacity but also 0 consumption rate.
        # Give artificial supply to prevent supply-based retreat from triggering.
        intruder.food = 999.0
        intruder.water = 999.0
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert intruder.alive
        assert intruder.pos == (5, 2, SURFACE_Z)


# -- Tarp fall -------------------------------------------------------------


class TestTarpFall:
    def test_inquisitor_falls_through_tarp(self):
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_TARP

        ai, bus, _, core, rng = _make_ai(grid=grid)

        fell_events = []
        bus.subscribe("intruder_fell", lambda **kw: fell_events.append(kw))

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=INQUISITOR)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert len(fell_events) == 1
        assert grid.get(5, 2, SURFACE_Z) == VOXEL_AIR  # Tarp destroyed
        assert (5, 2, SURFACE_Z) in intruder.personal_map.hazards

    def test_eidolon_flies_over_tarp(self):
        """EIDOLON has can_fly=True, so it passes over tarps."""
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 2, SURFACE_Z] = VOXEL_TARP

        ai, bus, _, core, rng = _make_ai(grid=grid)

        fell_events = []
        bus.subscribe("intruder_fell", lambda **kw: fell_events.append(kw))

        intruder = _make_intruder(1, 5, 1, SURFACE_Z, arch=EIDOLON)
        intruder.state = IntruderState.ADVANCING
        intruder.path = [(5, 1, SURFACE_Z), (5, 2, SURFACE_Z)]
        intruder.path_index = 1
        intruder.move_interval = 1
        # Eidolons have 0 food/water capacity but also 0 consumption rate.
        # Give artificial supply to prevent supply-based retreat from triggering.
        intruder.food = 999.0
        intruder.water = 999.0
        ai.intruders.append(intruder)

        ai._update_advancing(intruder)

        assert len(fell_events) == 0
        assert intruder.pos == (5, 2, SURFACE_Z)


# -- Attacking behavior ----------------------------------------------------


class TestAttacking:
    def test_core_takes_damage_from_attacking_inquisitor(self):
        ai, bus, grid, core, rng = _make_ai()

        # INQUISITOR has damage=8
        intruder = _make_intruder(1, 5, 5, SURFACE_Z + _CORE_DEPTH, arch=INQUISITOR)
        intruder.state = IntruderState.ATTACKING
        intruder.attack_interval = 1
        ai.intruders.append(intruder)

        for _ in range(5):
            ai._update_attacking(intruder)

        # 5 attacks x 8 damage (INQUISITOR base damage) = 40 damage
        assert core.hp == 60

    def test_hero_does_heavy_damage(self):
        """HERO has damage=20 and attack_interval=15."""
        ai, bus, grid, core, rng = _make_ai()

        intruder = _make_intruder(
            1, 5, 5, SURFACE_Z + _CORE_DEPTH, arch=HERO,
        )
        intruder.state = IntruderState.ATTACKING
        intruder.attack_interval = 1
        ai.intruders.append(intruder)

        for _ in range(3):
            ai._update_attacking(intruder)

        # 3 attacks x 20 damage (HERO base damage) = 60
        assert core.hp == 40


# -- Death handling --------------------------------------------------------


class TestDeathHandling:
    def test_death_publishes_event(self):
        ai, bus, grid, core, rng = _make_ai()
        died = []
        bus.subscribe("intruder_died", lambda **kw: died.append(kw))

        intruder = _make_intruder(1, 5, 0, SURFACE_Z)
        ai.intruders.append(intruder)
        ai._on_intruder_death(intruder)

        assert intruder.state == IntruderState.DEAD
        assert len(died) == 1

    def test_party_notified_on_member_death(self):
        ai, bus, grid, core, rng = _make_ai()

        m1 = _make_intruder(1, 5, 0, SURFACE_Z, arch=GLOOMWARDEN)
        m2 = _make_intruder(2, 5, 1, SURFACE_Z, arch=INQUISITOR)
        party = Party(1, [m1, m2])
        ai.parties.append(party)
        ai.intruders.extend([m1, m2])

        initial_morale = m2.morale
        ai._on_intruder_death(m1)

        # Ally death applies MORALE_ALLY_DEATH_PENALTY to survivors
        assert m2.morale < initial_morale


# -- Game over -------------------------------------------------------------


class TestGameOver:
    def test_game_over_stops_ai(self):
        ai, bus, grid, core, rng = _make_ai()
        bus.publish("game_over", reason="core_destroyed")
        assert ai._game_over is True

        ai.spawning_enabled = True
        ai._spawn_timer = 9999
        bus.publish("tick", tick=1)
        assert len(ai.intruders) == 0


# -- Cleanup ---------------------------------------------------------------


class TestCleanup:
    def test_cleanup_removes_dead(self):
        ai, bus, grid, core, rng = _make_ai()
        m1 = _make_intruder(1, 5, 0, SURFACE_Z)
        m2 = _make_intruder(2, 5, 1, SURFACE_Z)
        ai.intruders.extend([m1, m2])

        m1.state = IntruderState.DEAD
        ai._cleanup()

        assert len(ai.intruders) == 1
        assert ai.intruders[0].id == 2

    def test_cleanup_removes_wiped_parties(self):
        ai, bus, grid, core, rng = _make_ai()
        m1 = _make_intruder(1, 5, 0, SURFACE_Z)
        party = Party(1, [m1])
        ai.parties.append(party)

        m1.state = IntruderState.DEAD
        ai._cleanup()

        assert len(ai.parties) == 0


# -- Pillaging -------------------------------------------------------------


class TestPillaging:
    def test_betrayed_intruder_heads_to_treasure(self):
        grid = _make_grid()
        for y in range(0, 6):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR
        grid.grid[5, 4, SURFACE_Z] = VOXEL_TREASURE

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(
            1, 5, 1, SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.PILLAGE,
        )
        intruder.state = IntruderState.PILLAGING
        intruder.move_interval = 1
        ai.intruders.append(intruder)

        # Reveal the corridor and treasure
        for y in range(0, 6):
            intruder.personal_map.reveal(5, y, SURFACE_Z, VOXEL_AIR)
        intruder.personal_map.reveal(5, 4, SURFACE_Z, VOXEL_TREASURE)

        ai._update_pillaging(intruder)

        # Should have found a path to the treasure
        assert intruder.path is not None
        assert len(intruder.path) > 1

    def test_pillager_retreats_when_no_treasure(self):
        grid = _make_grid()
        for y in range(0, 4):
            grid.grid[5, y, SURFACE_Z] = VOXEL_AIR

        ai, bus, _, core, rng = _make_ai(grid=grid)

        intruder = _make_intruder(
            1, 5, 1, SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.PILLAGE,
        )
        intruder.state = IntruderState.PILLAGING
        intruder.move_interval = 1
        # Reveal some cells so retreat pathfinding works
        for y in range(0, 4):
            intruder.personal_map.reveal(5, y, SURFACE_Z, VOXEL_AIR)
        ai.intruders.append(intruder)

        ai._update_pillaging(intruder)

        assert intruder.state == IntruderState.RETREATING


# =========================================================================
# Tests from test_intruder_ai.py (migrated to new archetypes)
# =========================================================================


def test_intruder_spawns():
    bus = EventBus()
    grid = _make_simple_dungeon()
    pf = AStarPathfinder(grid)
    core = DungeonCore(bus, 5, 5, SURFACE_Z + _CORE_DEPTH, hp=100)
    rng = SeededRNG(42)

    ai = IntruderAI(bus, grid, pf, core, rng)

    spawned = []
    bus.subscribe("intruder_spawned", lambda **kw: spawned.append(kw))

    # Force spawn a party
    ai._spawn_party()

    assert len(ai.intruders) > 0
    assert all(i.state == IntruderState.ADVANCING for i in ai.intruders)
    # All spawned intruders should have a valid archetype name
    for intruder in ai.intruders:
        assert intruder.archetype.name in (
            "Explorer", "Inquisitor", "Gloomwarden", "Mole Tamer",
            "Eidolon", "Alchemist", "Cartomancer", "Hero",
        )


def test_intruder_follows_path():
    bus = EventBus()
    grid = _make_simple_dungeon()
    pf = AStarPathfinder(grid)
    core = DungeonCore(bus, 5, 5, SURFACE_Z + _CORE_DEPTH, hp=100)
    rng = SeededRNG(42)

    ai = IntruderAI(bus, grid, pf, core, rng)

    intruder = _make_intruder(1, 5, 0, SURFACE_Z)
    path = pf.find_path((5, 0, SURFACE_Z), (5, 5, SURFACE_Z + _CORE_DEPTH))
    assert path is not None
    intruder.path = path
    intruder.path_index = 1
    intruder.state = IntruderState.ADVANCING
    intruder.move_interval = 1  # Move every tick for faster testing
    ai.intruders.append(intruder)

    moves = []
    bus.subscribe("intruder_moved", lambda **kw: moves.append(1))

    for tick in range(1, 100):
        ai._update_intruder(intruder)
        if intruder.state == IntruderState.ATTACKING:
            break

    assert intruder.state == IntruderState.ATTACKING
    # INQUISITOR has attack_range=1, so it attacks from within 1 cell of the core
    core_z = SURFACE_Z + _CORE_DEPTH
    dist = abs(intruder.x - 5) + abs(intruder.y - 5) + abs(intruder.z - core_z)
    assert dist <= intruder.archetype.attack_range


def test_intruder_attacks_core():
    bus = EventBus()
    grid = _make_simple_dungeon()
    pf = AStarPathfinder(grid)
    core = DungeonCore(bus, 5, 5, SURFACE_Z + _CORE_DEPTH, hp=100)
    rng = SeededRNG(42)

    ai = IntruderAI(bus, grid, pf, core, rng)

    # INQUISITOR has damage=8 and attack_interval=20
    # Use a custom approach: set attack_interval to 1 for fast testing
    intruder = _make_intruder(1, 5, 5, SURFACE_Z + _CORE_DEPTH)
    intruder.state = IntruderState.ATTACKING
    intruder.attack_interval = 1  # Attack every tick
    ai.intruders.append(intruder)

    for tick in range(1, 6):
        ai._update_intruder(intruder)

    # 5 attacks x 8 damage (INQUISITOR damage) = 40
    assert core.hp == 60


def test_intruder_retreats_at_low_hp():
    bus = EventBus()
    grid = _make_simple_dungeon()
    pf = AStarPathfinder(grid)
    core = DungeonCore(bus, 5, 5, SURFACE_Z + _CORE_DEPTH, hp=100)
    rng = SeededRNG(42)

    ai = IntruderAI(bus, grid, pf, core, rng)

    intruder = _make_intruder(1, 5, 3, SURFACE_Z + _CORE_DEPTH)
    intruder.state = IntruderState.ADVANCING
    intruder.path = pf.find_path(
        (5, 3, SURFACE_Z + _CORE_DEPTH), (5, 5, SURFACE_Z + _CORE_DEPTH),
    )
    intruder.path_index = 1
    intruder.move_interval = 1
    ai.intruders.append(intruder)

    # INQUISITOR retreat_threshold = 0.10, max_hp = 120
    # 120 * 0.10 = 12 -> must be below 12
    intruder.hp = 10

    ai._update_intruder(intruder)
    assert intruder.state == IntruderState.RETREATING
