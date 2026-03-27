"""Tests for dungeon_builder.core.game_state — GameState container."""

from dungeon_builder.core.game_state import GameState


class TestGameState:
    """Unit tests for the GameState container."""

    def test_initial_seed(self):
        gs = GameState(seed=42)
        assert gs.seed == 42

    def test_initial_build_mode(self):
        gs = GameState(seed=0)
        assert gs.build_mode == "dig"

    def test_initial_game_over_false(self):
        gs = GameState(seed=0)
        assert gs.game_over is False

    def test_initial_menu_open_true(self):
        gs = GameState(seed=0)
        assert gs.menu_open is True

    def test_initial_craft_mode_active_false(self):
        gs = GameState(seed=0)
        assert gs.craft_mode_active is False

    def test_subsystem_refs_initially_none(self):
        gs = GameState(seed=0)
        assert gs.event_bus is None
        assert gs.time_manager is None
        assert gs.voxel_grid is None
        assert gs.core is None
        assert gs.build_system is None
        assert gs.move_system is None
        assert gs.pathfinder is None

    def test_build_mode_mutable(self):
        gs = GameState(seed=0)
        gs.build_mode = "move"
        assert gs.build_mode == "move"

    def test_can_assign_subsystems(self):
        gs = GameState(seed=0)
        sentinel = object()
        gs.event_bus = sentinel
        assert gs.event_bus is sentinel
