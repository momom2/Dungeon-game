# Project Directory Overview

Structured walkthrough of every directory in the Dungeon Builder project.
Each section lists purpose, file count, approximate line count, key files,
and notable patterns.

## Dependency References

This document covers the structure of:

- `dungeon_builder/` (all subdirectories)
- `tests/` (all subdirectories)
- `docs/` (documentation and proposals)
- `prototype/` (simplified MVP)
- Top-level files (CLAUDE.md, GRAPHICS.md, README.md, pyproject.toml)

---

## Top-Level Files

| File | Description |
|------|-------------|
| `CLAUDE.md` | Project instructions, architecture principles, code style, testing philosophy |
| `GRAPHICS.md` | Art and asset conventions, visual style, voxel textures, rendering systems |
| `README.md` | Quick start, project description, current focus |
| `pyproject.toml` | Python project metadata and tool configuration |
| `requirements.txt` | Dependencies: Panda3D 1.10.14+, NumPy |

---

## dungeon_builder/ -- Game Engine

Entry point: `python -m dungeon_builder.main`

### dungeon_builder/ (root)

**1 file, ~515 lines**

| File | Role |
|------|------|
| `main.py` | Panda3D application init, system wiring, dependency graph. Creates all subsystems, registers event subscriptions, handles save/load coordination |

**Patterns:** All subsystem instantiation happens here. Systems are
connected exclusively through EventBus subscriptions — `main.py` is the
only file that imports multiple subsystems.

---

### dungeon_builder/core/ -- Engine Fundamentals

**6 files, ~1,140 lines**

Purpose: Core infrastructure shared by all subsystems — event routing,
game state, time control, persistence, input binding.

| File | Lines | Role |
|------|-------|------|
| `event_bus.py` | 41 | Pub/sub event system. Zero dependencies. All inter-system communication flows through this |
| `game_state.py` | 51 | Central state container. Holds references to voxel_grid, build_system, core, mana, etc. |
| `time_manager.py` | 55 | Tick-based simulation driver. Pause/1x/3x speed control |
| `keybinding_registry.py` | 221 | Key-to-action mapping with rebinding and conflict detection |
| `save_system.py` | 775 | Zip-based `.dungeon` save format. Serializes grid arrays (npz), game state (json), intruders, parties, mana |

**Patterns:** EventBus is the foundation — every other system depends on
it. SaveSystem serializes each subsystem's state independently (numpy
arrays for grid, JSON for metadata).

---

### dungeon_builder/config/ -- Configuration and Constants

**11 files, ~1,680 lines**

Purpose: All tunable parameters in one place. Config-driven design means
modders can reshape gameplay by editing these files without touching
system code.

| File | Lines | Role |
|------|-------|------|
| `__init__.py` | 34 | Re-exports all config modules |
| `voxels.py` | 93 | Voxel type IDs (VOXEL_STONE, VOXEL_WATER, VOXEL_LAVA, etc.). 30+ block types |
| `materials.py` | 658 | Per-voxel material property LUTs: weight, strength, porosity, conductivity, dig duration, color |
| `metals.py` | 141 | Metal type definitions for enchanted blocks (copper, iron, silver, gold) |
| `physics.py` | 143 | Gravity, structural limits, flow rates, temperature coefficients |
| `rendering.py` | 187 | Camera speed, chunk size, fog, vertex noise, overlay colors |
| `economy.py` | 74 | Mana generation rate, costs, soul capacity, charge rates |
| `intruders.py` | 212 | Spawn rates, party templates, archetype stats, decision thresholds |
| `building.py` | 71 | Dig duration, pressure plate timings, multi-block flags |
| `world.py` | 71 | Grid dimensions (64x64x32), surface level, water river params, seeds |

**Patterns:** LUT dicts keyed by voxel type are the primary data
structure. Adding a new material means adding entries to the LUTs in
`materials.py` — no system code changes needed.

---

### dungeon_builder/building/ -- Build, Dig, and Craft Systems

**9 files, ~2,440 lines**

Purpose: Player-facing construction systems — digging blocks, picking up
and placing materials, crafting multi-block structures from recipes.

| File | Lines | Role |
|------|-------|------|
| `build_system.py` | 477 | Dig queue management. Accepts dig requests, tracks progress, publishes completion events |
| `move_system.py` | 334 | Pick up loose blocks into inventory, drop them elsewhere. Unlimited multi-type inventory |
| `crafting_system.py` | 305 | Highlight-mode state machine for recipe placement. Player selects recipe, system highlights valid positions, player clicks to craft |
| `crafting_book.py` | 109 | Recipe metadata and category filtering |
| `crafting_journal.py` | 98 | Discovery tracking — records which recipes the player has learned |
| `crafting_helpers.py` | 94 | Shared validation utilities (material checking, block placement) |
| `crafting_recipes_functional.py` | 729 | 25+ functional block recipes (doors, pressure plates, pumps, traps) |
| `crafting_recipes_natural.py` | 292 | 15+ natural material recipes (stone variants, ores, crystals) |

**Patterns:** Crafting uses a state machine: idle -> recipe selected ->
highlights shown -> hover preview -> click to place -> consume materials.
All recipe definitions are data (recipe objects), not code.

---

### dungeon_builder/world/ -- Voxel Grid, Geology, Physics

**6 files + physics/ subdirectory, ~5,830 lines total**

Purpose: The simulation world — 3D voxel grid, procedural terrain
generation, claimed territory, room detection, pathfinding, and all
physics subsystems.

#### World (top-level)

| File | Lines | Role |
|------|-------|------|
| `voxel_grid.py` | 301 | 3D NumPy-backed voxel grid (64x64x32 default). Read/write, type checks, neighbor queries |
| `geology.py` | 880 | Procedural terrain: strata, ores, surface river, cave systems. Fractal Brownian motion |
| `claimed_territory.py` | 315 | Player-claimed region tracking. Souls captured on claimed territory increase mana capacity |
| `pathfinding.py` | 128 | Global A* for world-space queries |
| `room_detection.py` | 121 | Flood-fill to identify enclosed rooms |

#### world/physics/ -- Physics Subsystems

**8 files, ~4,090 lines**

All physics systems operate on fixed tick intervals, not frame time.

| File | Lines | Role |
|------|-------|------|
| `gravity.py` | 605 | Block falling, cascade physics, loose-block propagation, angle of repose, shock waves |
| `structural.py` | 756 | Direct stiffness load distribution, arch detection, buttressing, compressive/shear/tensile failure |
| `water.py` | 1,010 | Water and lava simulation. Pluggable flow strategies, sources/sinks, pressure, seepage, evaporation, lava-water reactions |
| `water_flow_strategies.py` | 813 | Four interchangeable algorithms: Cellular Automata, Weakly Compressible SPH, Lattice Boltzmann D3Q7, Jacobi Projection |
| `temperature.py` | 206 | Discrete heat equation. Diffusion from hot sources, metal melting |
| `humidity.py` | 228 | Porosity-weighted moisture diffusion, condensation, steam generation |
| `thermal_stress.py` | 169 | Temperature gradient stress, fatigue accumulation, quench amplification |
| `pipe.py` | 300 | BFS pipe network detection, directional fluid transport, active pumping |

**Patterns:** Physics systems are independent — they subscribe to `tick`
events and operate on shared NumPy arrays in `VoxelGrid`. Each system
has its own tick interval (gravity every tick, temperature every 3 ticks,
etc.). Water flow uses a Strategy pattern for pluggable algorithms.

---

### dungeon_builder/dungeon_core/ -- Magical Core and Mana

**3 files, ~490 lines**

Purpose: The dungeon core (defense objective) and the mana economy that
powers player abilities.

| File | Lines | Role |
|------|-------|------|
| `core.py` | 52 | DungeonCore: HP, position, damage handling, game-over detection |
| `mana.py` | 437 | Mana economy: generation per tick, dig/trap consumption, soul capture, per-block enchanted capacitance with charge modes (charging/idle/draining) |

**Patterns:** Mana acts as a resource budget — the player generates mana
from the core and soul captures, spends it on powered digs and traps.
Enchanted blocks have individual capacitance that charges/drains
independently.

---

### dungeon_builder/intruders/ -- AI and Intruder System

**18 files, ~6,340 lines**

Purpose: The full intruder AI system — archetypes, parties, vision,
pathfinding, combat, equipment, familiars, social dynamics.

| File | Lines | Role |
|------|-------|------|
| `decision.py` | 581 | Main AI loop. Tick processing, state transitions, vision/pathfinding integration |
| `agent.py` | 292 | Intruder data model. Stats, position, equipment, personal map, state |
| `archetypes.py` | 300 | 8 archetype definitions as frozen dataclasses |
| `party.py` | 449 | Party coordination: templates, leader election, morale, objective voting, betrayal |
| `state_handlers.py` | 608 | Per-state behavior (move, dig, heal, loot, retreat, escape) |
| `hazard_response.py` | 347 | Hazard damage: water, lava, heat, cold, gas. Triggers fleeing or death |
| `personal_pathfinder.py` | 484 | A* on personal fog-of-war map. Archetype-specific traversal costs |
| `personal_map.py` | 191 | Per-intruder explored cell tracking |
| `vision.py` | 296 | Bresenham 3D line-of-sight, arcane sight, thermal vision |
| `equipment.py` | 600 | Equipment loadout, item depletion, usage priority |
| `scroll_ai.py` | 428 | Scroll reading AI: knowledge-driven equipment deployment |
| `familiar.py` | 335 | Summoned creatures: moles, sprites. Exhaustion mechanic |
| `sprite.py` | 415 | Eidolon sprite/ghost orchestration |
| `spawning.py` | 270 | Wave timing, archetype selection, party creation |
| `interactions.py` | 335 | Block interactions: pressure plates, doors, item pickup |
| `knowledge_archive.py` | 212 | Persistent knowledge with uncertainty tracking across waves |
| `reputation.py` | 199 | Dungeon reputation (lethality/richness) affecting future waves |

**Patterns:** Three-layer architecture: party coordination (shared
objectives, morale) -> per-intruder state machine (SPAWNING -> ADVANCING
-> INTERACTING/ATTACKING/RETREATING -> DEAD/ESCAPED) -> subsystem
integration (vision, pathfinding, equipment). Each intruder maintains a
personal fog-of-war map updated by vision each tick.

---

### dungeon_builder/rendering/ -- Graphics and Visualization

**5 files, ~2,410 lines**

Purpose: Panda3D rendering — chunk-based voxel meshes, camera, particle
effects, intruder sprites, layer slicing.

| File | Lines | Role |
|------|-------|------|
| `voxel_renderer.py` | 863 | Chunk-based GeomNode mesh generation. Overlay layers for dig highlights, selection, fog of war |
| `camera.py` | 638 | RTS-style camera: orbit, pan, zoom. Mouse picking (raycasts to voxel grid). Input dispatch |
| `effects.py` | 653 | Particle effects: dust, impacts, thermal blooms, water splashes, mana sparks |
| `intruder_renderer.py` | 146 | Intruder sprite rendering as colored cubes with equipment visualization |
| `layer_slice.py` | 106 | Single-layer 2D slices for debugging (water level, temperature, humidity per Z-level) |

**Patterns:** Rendering subscribes to game events and reads state — it
never drives game logic. The camera doubles as the input dispatcher,
translating mouse clicks into `voxel_left_clicked`, `voxel_hover`, etc.
events. Chunk meshes are rebuilt only when voxels change (dirty flag
system).

---

### dungeon_builder/ui/ -- User Interface

**13 files, ~2,790 lines**

Purpose: All UI panels and HUD elements. Built with Panda3D's DirectGui.

| File | Lines | Role |
|------|-------|------|
| `hud.py` | 555 | Main HUD overlay: core HP, tick counter, speed controls, Z-level, tool info, error messages |
| `main_menu.py` | 341 | Title menu, new game, load game, pause overlay |
| `crafting_book_panel.py` | 496 | Filterable recipe browser with material preview |
| `menu_settings.py` | 465 | Options: dev mode, difficulty sliders, physics config, rendering config |
| `enchanted_panel.py` | 324 | Per-block enchanted management: activation toggle, charge mode, capacitance readout |
| `hud_inventory.py` | 133 | Inventory display (held material counts by type) |
| `menu_keybinding.py` | 229 | Keybinding editor with conflict detection |
| `render_mode_selector.py` | 80 | Render mode toggle (normal, thermal, humidity, water overlay) |
| `menu_constants.py` | 94 | Layout constants: button sizes, spacing, alignment |
| `style.py` | 45 | Shared colors, fonts, padding |
| `voxel_names.py` | 27 | Human-readable voxel type names |
| `build_palette.py` | 0 | Empty stub (build selector moved to main HUD) |

**Patterns:** UI components never import game logic — all communication
is through EventBus. Widget groups use NamedTuples or dataclasses.
Layout constants live in `menu_constants.py` and `style.py`.

---

### dungeon_builder/utils/ -- Shared Utilities

**3 files, ~70 lines**

| File | Lines | Role |
|------|-------|------|
| `logging.py` | 23 | Logging formatters and handlers |
| `rng.py` | 45 | Seeded RNG for reproducible procedural generation and AI decisions |

---

### dungeon_builder/magic/ and dungeon_builder/society/

Empty stub directories reserved for future expansion (magic schools,
social simulation).

---

## prototype/ -- Simplified MVP

**7 files, ~900 lines**

A stripped-down version of the game for rapid prototyping. No physics,
no mana, no save/load. Auto-spawns explorer intruders, unpaused by
default.

| File | Lines | Role |
|------|-------|------|
| `main.py` | 224 | Simplified Panda3D app without physics or mana |
| `intruders.py` | 385 | Simplified archetypes and spawning (no equipment system) |
| `crafting.py` | 112 | Reduced crafting palette (basic blocks only) |
| `map_gen.py` | 115 | Flat stone terrain with river |
| `config.py` | 48 | Prototype-specific config overrides |
| `__init__.py` | 9 | Package marker |
| `__main__.py` | 5 | Entry point: `python -m prototype` |

---

## tests/ -- Test Suite

**~119 files, ~27,900 lines**

Tests verify gameplay behavior without a Panda3D window (headless).
Organized by domain to mirror the source tree.

### Test Organization

| Directory | Files | Lines | Coverage |
|-----------|-------|-------|----------|
| `tests/building/` | 9 | ~4,810 | Dig queue, crafting, drag-select, inventory, pressure plates |
| `tests/intruders/` | 16 | ~8,450 | Decision AI, pathfinding, party, equipment, vision, familiars, scrolls, sprites |
| `tests/physics/` | 13 | ~8,300 | All 9 physics systems: gravity, structural, water (4 strategies), temperature, humidity, thermal stress, pipes, lava, steam |
| `tests/world/` | 6 | ~2,710 | Geology generation, claimed territory, voxel grid, pathfinding, rooms |
| `tests/core/` | 7 | ~1,470 | Save/load round-trips, keybinding, event bus, game state, time manager |
| `tests/economy/` | 3 | ~1,110 | Mana system, enchanted block capacitance |
| `tests/rendering/` | 7 | ~1,270 | Chunk rendering, camera, effects, overlays |
| `tests/ui/` | 6 | ~920 | Main menu, HUD, debug spawn, render mode selector |
| `tests/utils/` | 2 | ~90 | RNG, logging |
| `tests/prototype/` | 4 | ~790 | Prototype intruders, crafting, traps, terrain |
| `tests/benchmarks/` | 1 | ~740 | Performance profiling (intruder spawning, pathfinding, physics ticks) |

### Key Test Files

- `tests/physics/test_water.py` (2,003 lines) — Most comprehensive
  single test file. Covers all water/lava behaviors: flow, pressure,
  seepage, evaporation, sources/sinks, lava reactions.
- `tests/building/test_crafting.py` (1,441 lines) — Recipe placement,
  material consumption, multi-block pattern validation.
- `tests/core/test_save_system.py` (991 lines) — Full save/load
  round-trips across all subsystem state.
- `tests/intruders/test_decision.py` (956 lines) — State machine
  transitions, AI behavior trees.

### Shared Fixtures

`tests/conftest.py` provides:
- `event_bus` — Fresh EventBus instance
- `small_grid` — 8x8x8 voxel grid
- `stone_grid` — Grid filled with stone
- Dev mode auto-disable between tests

---

## docs/ -- Documentation

| File | Description |
|------|-------------|
| `physics.md` | Physics algorithm reference (9 systems) |
| `intruder_ai.md` | Intruder AI decision framework |
| `events.md` | Complete event catalog (79 events) |
| `directory.md` | This file — project directory overview |

### docs/proposals/ -- Design Proposals

| File | Description |
|------|-------------|
| `familiar_exhaustion.md` | Familiar exhaustion, mole cycling, homunculus system |
| `scroll_usage_ai.md` | Scroll reading AI and knowledge-driven equipment deployment |
| `vision_rework.md` | Vision system redesign (cone-of-sight, light tracking) |
| `hero_dramatic_pathing.md` | Drama-tier intruder special abilities |

---

## Summary Statistics

| Component | Files | Lines |
|-----------|-------|-------|
| Game engine (`dungeon_builder/`) | 71 | ~20,750 |
| Tests (`tests/`) | 119 | ~27,900 |
| Prototype (`prototype/`) | 7 | ~900 |
| Documentation (`docs/`) | 8 | ~5,000 |
| **Total** | **205** | **~54,550** |

### Largest Subsystems by Line Count

1. Intruder AI (18 files, 6,340 lines)
2. World + Physics (14 files, 5,830 lines)
3. UI (13 files, 2,790 lines)
4. Building (9 files, 2,440 lines)
5. Rendering (5 files, 2,410 lines)
6. Config (11 files, 1,680 lines)
7. Core (6 files, 1,140 lines)
8. Dungeon Core/Mana (3 files, 490 lines)
