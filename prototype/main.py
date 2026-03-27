"""Prototype application — wires shared infrastructure with simplified logic.

No physics, no mana, no save/load, no main menu.  Starts unpaused with
stone terrain and auto-spawning explorer intruders.

Dependencies: panda3d, dungeon_builder.core.*, dungeon_builder.world.*,
    dungeon_builder.building.*, dungeon_builder.rendering.*,
    dungeon_builder.ui.*, dungeon_builder.intruders.agent,
    prototype.config, prototype.map_gen, prototype.crafting,
    prototype.intruders
Dependents: prototype.__main__
"""

from __future__ import annotations

import logging

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    WindowProperties,
    AmbientLight,
    DirectionalLight,
    LVector4f,
    AntialiasAttrib,
    loadPrcFileData,
)

# Set window size before ShowBase init
loadPrcFileData("", "win-size 1280 720")

from dungeon_builder.config import (
    DEFAULT_SEED,
    VOXEL_STONE,
    CORE_X,
    CORE_Y,
    CORE_Z,
)
from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.core.time_manager import TimeManager
from dungeon_builder.core.game_state import GameState
from dungeon_builder.core.keybinding_registry import KeybindingRegistry
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.claimed_territory import ClaimedTerritorySystem
from dungeon_builder.building.build_system import BuildSystem
from dungeon_builder.building.move_system import MoveSystem
from dungeon_builder.building.crafting_system import CraftingSystem
from dungeon_builder.building.crafting_journal import CraftingJournal
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.rendering.voxel_renderer import VoxelWorldRenderer
from dungeon_builder.rendering.layer_slice import LayerSliceManager
from dungeon_builder.rendering.camera import CameraController
from dungeon_builder.rendering.intruder_renderer import IntruderRenderer
from dungeon_builder.rendering.effects import EffectsRenderer
from dungeon_builder.ui.hud import HUD
from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel

from prototype.config import patch_shared_config, PROTOTYPE_CORE_HP, DEV_BAG_STONE
from prototype.map_gen import generate_prototype_map
from prototype.crafting import PrototypeCraftingBook
from prototype.intruders import (
    PrototypePathfinder,
    PrototypeIntruderAI,
    ArrowTrapSystem,
)

logger = logging.getLogger("prototype")


class PrototypeApp(ShowBase):
    """Stripped-down prototype for beta testers."""

    def __init__(self) -> None:
        ShowBase.__init__(self)
        self.disableMouse()
        self.setBackgroundColor(0.08, 0.08, 0.12, 1.0)

        logging.basicConfig(level=logging.INFO)

        # Window title
        props = WindowProperties()
        props.set_title("Dungeon Builder — Prototype")
        self.win.request_properties(props)
        self.render.set_antialias(AntialiasAttrib.M_auto)

        # ── Patch shared config for arrow traps ──
        patch_shared_config()

        # ── Core systems ──
        event_bus = EventBus()

        game_state = GameState(DEFAULT_SEED)
        game_state.event_bus = event_bus
        game_state.time_manager = TimeManager(event_bus)
        game_state.time_manager.set_speed(1)  # Start unpaused

        # Keybindings
        from pathlib import Path
        kb_registry = KeybindingRegistry()
        _kb_path = Path.home() / ".dungeon_builder" / "keybindings.json"
        kb_registry.load(_kb_path)
        game_state.keybinding_registry = kb_registry

        # ── World generation (stone-only) ──
        voxel_grid = VoxelGrid()
        generate_prototype_map(voxel_grid, seed=DEFAULT_SEED)
        game_state.voxel_grid = voxel_grid

        # ── Dungeon core ──
        core = DungeonCore(
            event_bus, CORE_X, CORE_Y, CORE_Z, hp=PROTOTYPE_CORE_HP,
        )
        game_state.core = core

        # ── Simulation systems (no physics) ──
        pathfinder = PrototypePathfinder(voxel_grid)
        game_state.pathfinder = pathfinder

        claimed_system = ClaimedTerritorySystem(event_bus, voxel_grid)

        build_system = BuildSystem(event_bus, voxel_grid, game_state=game_state)
        game_state.build_system = build_system

        # ManaSystem intentionally omitted (no mana cost)
        game_state.mana_system = None

        move_system = MoveSystem(event_bus, voxel_grid, game_state)
        game_state.move_system = move_system

        # Pre-fill bag with stone
        move_system.held_materials[VOXEL_STONE] = DEV_BAG_STONE

        crafting_system = CraftingSystem(
            event_bus, voxel_grid, move_system, game_state,
            mana_system=None,
        )
        # Replace the full crafting book with prototype-only recipes
        crafting_system.crafting_book = PrototypeCraftingBook()

        crafting_journal = CraftingJournal(event_bus, crafting_system.crafting_book)
        crafting_journal.discover_all()

        # ── Intruder AI + Arrow Traps ──
        intruder_ai = PrototypeIntruderAI(event_bus, voxel_grid, pathfinder, core)
        arrow_trap_system = ArrowTrapSystem(event_bus, voxel_grid, intruder_ai)

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
        crafting_book_panel = CraftingBookPanel(
            self, event_bus, crafting_journal, move_system,
            game_state=game_state,
            keybinding_registry=kb_registry,
        )

        # ── Main game loop ──
        def game_loop(task):
            dt = globalClock.get_dt()  # noqa: F821 (Panda3D global)
            game_state.time_manager.update(dt)
            return task.cont

        self.taskMgr.add(game_loop, "game_loop", sort=10)

        # Store references to prevent garbage collection
        self._game_state = game_state
        self._subsystems = {
            "event_bus": event_bus,
            "voxel_grid": voxel_grid,
            "core": core,
            "pathfinder": pathfinder,
            "claimed_system": claimed_system,
            "build_system": build_system,
            "move_system": move_system,
            "crafting_system": crafting_system,
            "crafting_journal": crafting_journal,
            "intruder_ai": intruder_ai,
            "arrow_trap_system": arrow_trap_system,
            "layer_manager": layer_manager,
            "world_renderer": world_renderer,
            "camera_ctrl": camera_ctrl,
            "intruder_renderer": intruder_renderer,
            "effects_renderer": effects_renderer,
            "hud": hud,
            "crafting_book_panel": crafting_book_panel,
        }

        logger.info("Prototype initialized. Game is running!")

    def _setup_lighting(self) -> None:
        """Add ambient and directional lights for the voxel world."""
        alight = AmbientLight("ambient")
        alight.set_color(LVector4f(0.3, 0.3, 0.35, 1.0))
        alnp = self.render.attach_new_node(alight)
        self.render.set_light(alnp)

        dlight = DirectionalLight("directional")
        dlight.set_color(LVector4f(0.8, 0.8, 0.75, 1.0))
        dlnp = self.render.attach_new_node(dlight)
        dlnp.set_hpr(45, -60, 0)
        self.render.set_light(dlnp)


def main() -> None:
    app = PrototypeApp()
    app.run()
