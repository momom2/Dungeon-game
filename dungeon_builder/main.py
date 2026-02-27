"""Entry point: Panda3D application initialization and system wiring.

Subsystem Dependency Map
========================
Each subsystem is listed with where it's referenced beyond its own
instantiation line.  When disabling or refactoring a subsystem, update
**all** of the listed sites.

  event_bus          → passed to every subsystem; game_state.event_bus
  rng                → GeologyGenerator, IntruderAI, _subsystems
  game_state         → camera_ctrl, hud, build_system, move_system,
                       crafting_system, crafting_book_panel, main_menu,
                       _game_state, _save_game, _load_game
  voxel_grid         → game_state.voxel_grid, most subsystems, _subsystems,
                       _save_game, _load_game
  core               → game_state.core, IntruderAI, effects_renderer,
                       _subsystems, _save_game, _load_game
  pathfinder         → game_state.pathfinder, IntruderAI, _subsystems
  claimed_system     → _subsystems only (wired via event_bus)
  build_system       → game_state.build_system, world_renderer.build_system,
                       _subsystems, _save_game, _load_game
  move_system        → game_state.move_system, crafting_system,
                       crafting_book_panel, _subsystems, _save_game, _load_game
  crafting_system    → crafting_journal, _subsystems
  crafting_journal   → crafting_book_panel, _subsystems
  temperature_physics→ _subsystems only (wired via event_bus)
  humidity_physics   → _subsystems only (wired via event_bus)
  pipe_physics       → _subsystems only (wired via event_bus)
  gravity_physics    → _subsystems only (wired via event_bus)
  structural_physics → _subsystems only (wired via event_bus)
  intruder_ai        → _subsystems, _save_game, _load_game
  layer_manager      → world_renderer, camera_ctrl, _subsystems
  world_renderer     → render_mode_selector, _subsystems
  camera_ctrl        → _subsystems only (wired via event_bus)
  intruder_renderer  → _subsystems only (wired via event_bus)
  effects_renderer   → _subsystems only (explicit place_core_marker call)
  hud                → _subsystems only (wired via event_bus)
  render_mode_selector→ _subsystems only
  crafting_book_panel→ _subsystems only
  main_menu          → _subsystems only

  DISABLED:
  room_detector      → was _subsystems only (wired via event_bus dig_complete).
                       Disabled due to O(n) BFS flood-fill per dig completion.
"""

from __future__ import annotations

import logging

import numpy as np
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    WindowProperties,
    AmbientLight,
    DirectionalLight,
    LVector4f,
    AntialiasAttrib,
    loadPrcFileData,
)

# Set window size before ShowBase init (must happen before window creation)
loadPrcFileData("", "win-size 1280 720")

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    DEFAULT_SEED,
    VOXEL_AIR,
    VOXEL_BEDROCK,
    VOXEL_STONE,
    VOXEL_CORE,
    CORE_X,
    CORE_Y,
    CORE_Z,
    CORE_DEFAULT_HP,
    SURFACE_Z,
)
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.time_manager import TimeManager
from dungeon_builder.core.game_state import GameState
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.geology import GeologyGenerator
# Room detection disabled — will be reworked from the ground up.
# from dungeon_builder.world.room_detection import RoomDetector
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.world.physics.temperature import TemperaturePhysics
from dungeon_builder.world.physics.humidity import HumidityPhysics
from dungeon_builder.world.physics.water import WaterPhysics
from dungeon_builder.world.physics.pipe import PipePhysics
from dungeon_builder.world.physics.gravity import GravityPhysics
from dungeon_builder.world.physics.structural import StructuralIntegrityPhysics
from dungeon_builder.world.claimed_territory import ClaimedTerritorySystem
from dungeon_builder.building.build_system import BuildSystem
from dungeon_builder.building.move_system import MoveSystem
from dungeon_builder.building.crafting_system import CraftingSystem
from dungeon_builder.building.crafting_journal import CraftingJournal
from dungeon_builder.intruders.decision import IntruderAI
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.dungeon_core.mana import ManaSystem
from dungeon_builder.rendering.voxel_renderer import VoxelWorldRenderer
from dungeon_builder.rendering.layer_slice import LayerSliceManager
from dungeon_builder.rendering.camera import CameraController
from dungeon_builder.rendering.intruder_renderer import IntruderRenderer
from dungeon_builder.rendering.effects import EffectsRenderer
from dungeon_builder.ui.hud import HUD
from dungeon_builder.ui.render_mode_selector import RenderModeSelector
from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
from dungeon_builder.ui.main_menu import MainMenu
from dungeon_builder.core.keybinding_registry import KeybindingRegistry
from dungeon_builder.core.save_system import SaveSystem
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.utils.logging import setup_logging

logger = logging.getLogger("dungeon_builder")


class DungeonApp(ShowBase):
    """Main game application."""

    def __init__(self) -> None:
        ShowBase.__init__(self)
        self.disableMouse()
        self.setBackgroundColor(0.08, 0.08, 0.12, 1.0)

        setup_logging(logging.INFO)

        # Window title
        props = WindowProperties()
        props.set_title("Dungeon Builder")
        self.win.request_properties(props)

        # Anti-aliasing
        self.render.set_antialias(AntialiasAttrib.M_auto)

        # ── Core systems ──
        event_bus = EventBus()
        rng = SeededRNG(DEFAULT_SEED)

        game_state = GameState(DEFAULT_SEED)
        game_state.event_bus = event_bus
        game_state.time_manager = TimeManager(event_bus)
        game_state.time_manager.set_speed(0)  # Start paused (main menu showing)

        # ── Keybinding registry ──
        from pathlib import Path
        kb_registry = KeybindingRegistry()
        _kb_path = Path.home() / ".dungeon_builder" / "keybindings.json"
        kb_registry.load(_kb_path)  # Load user overrides (no-op if file missing)
        game_state.keybinding_registry = kb_registry

        # ── World generation ──
        voxel_grid = VoxelGrid()
        GeologyGenerator(rng).generate(voxel_grid)
        game_state.voxel_grid = voxel_grid

        # Carve entrance and core room, then place the core block
        self._carve_initial_dungeon(voxel_grid)
        voxel_grid.grid[CORE_X, CORE_Y, CORE_Z] = VOXEL_CORE

        # ── Dungeon core ──
        core = DungeonCore(event_bus, CORE_X, CORE_Y, CORE_Z, hp=CORE_DEFAULT_HP)
        game_state.core = core

        # ── Simulation systems ──
        pathfinder = AStarPathfinder(voxel_grid)
        game_state.pathfinder = pathfinder

        # Room detection disabled — BFS flood fill on every dig_complete
        # causes severe lag with bulk digs.  Will be reworked.
        # room_detector = RoomDetector(event_bus, voxel_grid)
        claimed_system = ClaimedTerritorySystem(event_bus, voxel_grid)

        build_system = BuildSystem(event_bus, voxel_grid, game_state=game_state)
        game_state.build_system = build_system

        mana_system = ManaSystem(event_bus, voxel_grid, build_system)
        game_state.mana_system = mana_system

        move_system = MoveSystem(event_bus, voxel_grid, game_state)
        game_state.move_system = move_system

        # Dev mode: fill bag with 50 of every resource
        if _cfg.DEV_MODE:
            self._fill_dev_bag(move_system)

        crafting_system = CraftingSystem(
            event_bus, voxel_grid, move_system, game_state,
            mana_system=mana_system,
        )

        crafting_journal = CraftingJournal(event_bus, crafting_system.crafting_book)
        crafting_journal.discover_all()  # All recipes known for now

        temperature_physics = TemperaturePhysics(event_bus, voxel_grid)
        humidity_physics = HumidityPhysics(event_bus, voxel_grid)
        water_physics = WaterPhysics(event_bus, voxel_grid)
        pipe_physics = PipePhysics(event_bus, voxel_grid)
        gravity_physics = GravityPhysics(event_bus, voxel_grid)
        structural_physics = StructuralIntegrityPhysics(event_bus, voxel_grid)

        intruder_ai = IntruderAI(event_bus, voxel_grid, pathfinder, core, rng)

        # ── Pre-stabilize terrain ──
        # Run gravity + structural passes until the world stops changing.
        # This prevents cascade-lag when the player first unpauses.
        # Use tick multiples of LCM(1, 2, 10) = 10 so all physics fire.
        logger.info("Stabilizing terrain...")
        _MAX_STABILIZE = 50
        for i in range(_MAX_STABILIZE):
            fake_tick = i * 10  # ensures gravity(1), repose(2), structural(10) all fire
            prev_grid = voxel_grid.grid.copy()
            prev_loose = voxel_grid.loose.copy()
            gravity_physics._on_tick(tick=fake_tick)
            structural_physics._on_tick(tick=fake_tick)
            if (np.array_equal(voxel_grid.grid, prev_grid)
                    and np.array_equal(voxel_grid.loose, prev_loose)):
                logger.info("Terrain stabilized after %d passes", i)
                break
        else:
            logger.warning(
                "Terrain did not fully stabilize after %d passes", _MAX_STABILIZE
            )
        # Clear any dirty chunks from stabilization (renderer not built yet)
        voxel_grid.pop_dirty_chunks()
        # Reset skip-if-unchanged snapshots so first real tick doesn't skip
        gravity_physics._last_connectivity_grid = voxel_grid.grid.copy()
        gravity_physics._last_connectivity_loose = voxel_grid.loose.copy()
        structural_physics._last_structural_grid = voxel_grid.grid.copy()
        structural_physics._last_structural_loose = voxel_grid.loose.copy()

        # ── Lighting ──
        self._setup_lighting()

        # ── Rendering ──
        layer_manager = LayerSliceManager(self.render, event_bus)

        world_renderer = VoxelWorldRenderer(event_bus, voxel_grid, layer_manager)
        world_renderer.build_system = build_system
        world_renderer.build_all_chunks()

        camera_ctrl = CameraController(
            self, event_bus, game_state, layer_manager,
            keybinding_registry=kb_registry,
        )
        intruder_renderer = IntruderRenderer(self, event_bus, layer_manager)

        effects_renderer = EffectsRenderer(
            self, event_bus, voxel_grid=voxel_grid, layer_manager=layer_manager,
        )
        effects_renderer.place_core_marker(CORE_X, CORE_Y, CORE_Z)

        # ── UI ──
        hud = HUD(self, event_bus, game_state, keybinding_registry=kb_registry)
        render_mode_selector = RenderModeSelector(
            self, event_bus, world_renderer,
            keybinding_registry=kb_registry,
        )
        crafting_book_panel = CraftingBookPanel(
            self, event_bus, crafting_journal, move_system,
            game_state=game_state,
            keybinding_registry=kb_registry,
        )

        # ── Main menu (title screen / options overlay) ──
        main_menu = MainMenu(self, event_bus, game_state)

        # ── Main game loop ──
        def game_loop(task):
            dt = globalClock.get_dt()
            game_state.time_manager.update(dt)
            return task.cont

        self.taskMgr.add(game_loop, "game_loop", sort=10)

        # Store references to prevent garbage collection
        self._game_state = game_state
        self._kb_registry = kb_registry
        self._kb_path = _kb_path
        self._save_path = Path.home() / ".dungeon_builder" / "savegame.dungeon"
        self._subsystems = {
            "event_bus": event_bus,
            "rng": rng,
            "voxel_grid": voxel_grid,
            "core": core,
            "pathfinder": pathfinder,
            # "room_detector": room_detector,  # disabled — see import block
            "claimed_system": claimed_system,
            "build_system": build_system,
            "move_system": move_system,
            "crafting_system": crafting_system,
            "crafting_journal": crafting_journal,
            "temperature_physics": temperature_physics,
            "humidity_physics": humidity_physics,
            "water_physics": water_physics,
            "pipe_physics": pipe_physics,
            "gravity_physics": gravity_physics,
            "structural_physics": structural_physics,
            "intruder_ai": intruder_ai,
            "layer_manager": layer_manager,
            "world_renderer": world_renderer,
            "camera_ctrl": camera_ctrl,
            "intruder_renderer": intruder_renderer,
            "effects_renderer": effects_renderer,
            "hud": hud,
            "render_mode_selector": render_mode_selector,
            "crafting_book_panel": crafting_book_panel,
            "main_menu": main_menu,
        }

        # ── Save/Load event handlers ──
        event_bus.subscribe("save_game_requested", self._save_game)
        event_bus.subscribe("load_game_requested", self._load_game)

        logger.info("Dungeon Builder initialized. Press SPACE to start!")

    def _save_game(self, **kwargs) -> None:
        """Save the current game state to disk."""
        try:
            sub = self._subsystems
            SaveSystem.save(
                self._save_path,
                game_state=self._game_state,
                voxel_grid=sub["voxel_grid"],
                core=sub["core"],
                move_system=sub["move_system"],
                build_system=sub["build_system"],
                intruder_ai=sub["intruder_ai"],
                time_manager=self._game_state.time_manager,
            )
            logger.info("Game saved to %s", self._save_path)
        except Exception:
            logger.exception("Failed to save game")

    def _load_game(self, **kwargs) -> None:
        """Load game state from disk and apply to live subsystems."""
        save_data = SaveSystem.load(self._save_path)
        if save_data is None:
            logger.warning("No save file found at %s", self._save_path)
            return
        try:
            sub = self._subsystems
            SaveSystem.apply(
                save_data,
                game_state=self._game_state,
                voxel_grid=sub["voxel_grid"],
                core=sub["core"],
                move_system=sub["move_system"],
                build_system=sub["build_system"],
                intruder_ai=sub["intruder_ai"],
                time_manager=self._game_state.time_manager,
            )
            # Rebuild all chunks to reflect loaded grid
            sub["world_renderer"].build_all_chunks()
            # Notify subsystems
            sub["event_bus"].publish("game_loaded")
            logger.info("Game loaded from %s", self._save_path)
        except Exception:
            logger.exception("Failed to load game")

    @staticmethod
    def _fill_dev_bag(move_system: MoveSystem) -> None:
        """Fill the bag with 50 of every placeable resource for dev mode."""
        from dungeon_builder.config import (
            VOXEL_DIRT, VOXEL_STONE,
            VOXEL_SANDSTONE, VOXEL_LIMESTONE, VOXEL_SHALE, VOXEL_CHALK,
            VOXEL_SLATE, VOXEL_MARBLE, VOXEL_GNEISS,
            VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN,
            VOXEL_IRON_ORE, VOXEL_COPPER_ORE, VOXEL_GOLD_ORE,
            VOXEL_MANA_CRYSTAL,
            VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
            VOXEL_ENCHANTED_METAL,
        )
        dev_materials = (
            VOXEL_DIRT, VOXEL_STONE,
            VOXEL_SANDSTONE, VOXEL_LIMESTONE, VOXEL_SHALE, VOXEL_CHALK,
            VOXEL_SLATE, VOXEL_MARBLE, VOXEL_GNEISS,
            VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN,
            VOXEL_IRON_ORE, VOXEL_COPPER_ORE, VOXEL_GOLD_ORE,
            VOXEL_MANA_CRYSTAL,
            VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
            VOXEL_ENCHANTED_METAL,
        )
        for vtype in dev_materials:
            move_system.held_materials[vtype] = 50

    def _carve_initial_dungeon(self, voxel_grid: VoxelGrid) -> None:
        """Carve a vertical shaft and corridor so intruders can reach the core.

        Weak materials (dirt, chalk, etc.) adjacent to carved spaces are
        replaced with stone to prevent structural collapse.  The core room
        has marble pillars at its four corners for additional support.
        """
        from dungeon_builder.config import VOXEL_MARBLE

        grid = voxel_grid
        # Set of block types that are already strong enough — skip these.
        _STRONG = frozenset((VOXEL_AIR, VOXEL_STONE, VOXEL_BEDROCK, VOXEL_CORE))

        # Clear 5x5 room around core (at core level and one above for headroom)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if grid.in_bounds(CORE_X + dx, CORE_Y + dy, CORE_Z):
                    grid.grid[CORE_X + dx, CORE_Y + dy, CORE_Z] = VOXEL_AIR
                if grid.in_bounds(CORE_X + dx, CORE_Y + dy, CORE_Z - 1):
                    grid.grid[CORE_X + dx, CORE_Y + dy, CORE_Z - 1] = VOXEL_AIR

        # Reinforce core room: replace weak materials in 1-block shell
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                is_perimeter = abs(dx) == 3 or abs(dy) == 3
                for z in (CORE_Z - 2, CORE_Z - 1, CORE_Z, CORE_Z + 1):
                    # Reinforce ceiling, floor, and perimeter walls
                    if z in (CORE_Z - 2, CORE_Z + 1) or is_perimeter:
                        x, y = CORE_X + dx, CORE_Y + dy
                        if grid.in_bounds(x, y, z):
                            if grid.grid[x, y, z] not in _STRONG:
                                grid.grid[x, y, z] = VOXEL_STONE

        # Marble pillars at the four corners of the core room.
        # Each pillar spans both room levels (floor + headroom) and connects
        # the reinforced floor (CORE_Z+1) to the reinforced ceiling (CORE_Z-2),
        # transferring load directly through high-stiffness marble (7.0) and
        # preventing the ceiling slab from acting as an unsupported span.
        for dx in (-2, 2):
            for dy in (-2, 2):
                x, y = CORE_X + dx, CORE_Y + dy
                for z in (CORE_Z, CORE_Z - 1):
                    if grid.in_bounds(x, y, z):
                        grid.grid[x, y, z] = VOXEL_MARBLE

        # Vertical shaft from ground level (SURFACE_Z) down to core level
        # Located at (CORE_X, 0) to (CORE_X+1, 1)
        shaft_x, shaft_y = CORE_X, 0
        for z in range(SURFACE_Z, CORE_Z + 1):
            for dx in range(2):
                for dy in range(2):
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        grid.grid[x, y, z] = VOXEL_AIR

        # Horizontal corridor at core level from shaft to core room
        for y in range(0, CORE_Y + 1):
            for dx in range(2):
                x = shaft_x + dx
                if grid.in_bounds(x, y, CORE_Z):
                    grid.grid[x, y, CORE_Z] = VOXEL_AIR

        # Stone platform around shaft entrance — prevents soft topsoil
        # (dirt, sand) from crumbling into the shaft.  Extends 2 blocks
        # out from the shaft walls and 2 z-levels deep below ground.
        _PLATFORM_RADIUS = 2
        _PLATFORM_DEPTH = 2
        for z in range(SURFACE_Z + 1, SURFACE_Z + 1 + _PLATFORM_DEPTH):
            for dx in range(-_PLATFORM_RADIUS, 2 + _PLATFORM_RADIUS):
                for dy in range(-_PLATFORM_RADIUS, 2 + _PLATFORM_RADIUS):
                    x, y = shaft_x + dx, shaft_y + dy
                    if grid.in_bounds(x, y, z):
                        if grid.grid[x, y, z] not in _STRONG:
                            grid.grid[x, y, z] = VOXEL_STONE

        # Reinforce corridor walls: replace weak adjacent blocks with stone
        for y in range(0, CORE_Y + 1):
            for dx in (-1, 2):  # Left and right walls
                x = shaft_x + dx
                for dz in (-1, 0, 1):
                    z = CORE_Z + dz
                    if grid.in_bounds(x, y, z):
                        if grid.grid[x, y, z] not in _STRONG:
                            grid.grid[x, y, z] = VOXEL_STONE
            for dx in range(-1, 3):  # Ceiling and floor
                x = shaft_x + dx
                for dz in (-1, 1):
                    z = CORE_Z + dz
                    if grid.in_bounds(x, y, z):
                        if grid.grid[x, y, z] not in _STRONG:
                            grid.grid[x, y, z] = VOXEL_STONE

        # Also clear surface around entrance for spawning
        for dx in range(-2, 4):
            for dy in range(4):
                x, y = shaft_x + dx, dy
                if grid.in_bounds(x, y, SURFACE_Z):
                    grid.grid[x, y, SURFACE_Z] = VOXEL_AIR

    def _setup_lighting(self) -> None:
        """Add ambient and directional lights for the voxel world."""
        # Ambient light
        alight = AmbientLight("ambient")
        alight.set_color(LVector4f(0.3, 0.3, 0.35, 1.0))
        alnp = self.render.attach_new_node(alight)
        self.render.set_light(alnp)

        # Directional light (sun-like, from above-front)
        dlight = DirectionalLight("directional")
        dlight.set_color(LVector4f(0.8, 0.8, 0.75, 1.0))
        dlnp = self.render.attach_new_node(dlight)
        dlnp.set_hpr(45, -60, 0)
        self.render.set_light(dlnp)


def main() -> None:
    app = DungeonApp()
    app.run()


if __name__ == "__main__":
    main()
