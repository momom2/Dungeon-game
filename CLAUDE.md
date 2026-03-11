# CLAUDE.md — Dungeon Builder

## Project

Dungeon defense sandbox — a simulation game where the player builds
intricate dungeons with environmental and artificial hazards to defend a
magical core from AI-driven intruder parties. Gameplay emerges from a
complex physics system (structural, fluid, thermal, humidity) creating
puzzle-like challenges: the player must understand and exploit physical
mechanics rather than rely on brute-force solutions.

The codebase is designed to be moddable and extensible — easy for others
to add content (block types, recipes, intruder archetypes) and features
(new physics systems, magic schools, UI panels).

- **Language:** Python 3.11+
- **Engine:** Panda3D 1.10.14+
- **Data:** NumPy (voxel grid, physics arrays)
- **Run:** `python -m dungeon_builder.main`
- **Test:** `pytest` (run all), `pytest tests/integration/` (behavioral),
  `pytest tests/<domain>/` (unit by domain)
- **No other external dependencies.**

---

## Architecture Principles

### 1. Event-Driven Loose Coupling
All subsystems communicate through the central `EventBus` (pub/sub).
Systems must never import or call each other directly — publish an event
and let the subscriber handle it. This keeps systems modular and testable
in isolation.

### 2. Simulation–Rendering Separation
All game logic (physics, AI, building, crafting) must be testable without
a Panda3D window. Rendering subscribes to events and reads state — it
never drives game logic. Tests run headless by design.

### 3. Config-Driven Design
All tunable parameters live in config (currently `config.py`, to be
refactored into domain-specific modules). Game balance, physics constants,
material properties, and UI layout values are never hardcoded in logic.
This makes the game moddable — a modder can tweak config to reshape
gameplay without touching system code.

### 4. Physics as Foundation
Emergent gameplay comes from interacting physics systems in preference to scripted
behaviors. New content should leverage existing physics rather than
special-casing. A trap's lethality comes from real structural/thermal/
fluid mechanics, not a hardcoded "deal X damage" check.

Physics implementations should draw from established scientific methods
in the literature (finite element, lattice Boltzmann, Navier-Stokes,
etc.), simplified and optimized for real-time voxel simulation. Document
the source method and any compromises made for performance. The water
flow system exemplifies this: four interchangeable strategies (Cellular
Automata, Weakly Compressible SPH, Lattice Boltzmann D3Q7, Jacobi
Projection) each rooted in real fluid dynamics.

The simulation does not need to be deterministic — physical behaviors
should be correct in expectation and respect conservation laws, but
stochastic variation is acceptable and often desirable.

### 5. LUT-Based Material Properties
Block behaviors are defined by lookup tables (weight, strength,
porosity, conductivity, dig duration, etc.), not by if/else chains on
voxel type. Adding a new material means adding entries to LUTs, not
modifying system code. This is the primary extensibility mechanism.

### 6. Tick-Based Simulation
All physics and AI run on fixed tick intervals, not frame time. The
`TimeManager` controls game speed (pause / 1× / 3×).

---

## Code Style

### File Size
Target ~600 lines per file. When a file grows beyond this, split by
responsibility. Current oversize files are legacy — refactoring them
down is an active goal.

### Naming
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private members: `_leading_underscore`
- Event names: `"snake_case"` strings (e.g., `"voxel_changed"`)

### Imports & Dependencies
- No circular imports. If system A needs to call system B, publish an
  event instead.
- No unused imports — clean them as you go.
- `TYPE_CHECKING` blocks for type hints that would create circular deps.
- **Every file must have a module docstring** listing its dependencies
  (what it imports from within the project) and its dependents (what
  imports it). Keep these up to date when changing imports. Example:

  ```python
  """Gravity physics — block falling and loose-block propagation.

  Dependencies: config, core.event_bus, world.voxel_grid
  Dependents: main (wiring), tests/physics/test_gravity.py
  """
  ```

### Data Patterns
- Material properties → LUT dicts in config, keyed by voxel type
- Settings/sliders → dataclass or TypedDict, not raw dicts
- Widget groups → NamedTuple or dataclass, not anonymous tuples
- Color constants → shared style module, not inline tuples

### Encapsulation
- Never access private (`_prefixed`) attributes of another system.
  If you need the data, add a public method to the owning system.
- UI components must not import game logic modules directly —
  communicate through EventBus.

---

## Testing

### Philosophy
Tests exist to verify that gameplay behavior is correct without manual
inspection. Prefer meaningful behavioral tests over exhaustive unit
tests. A test should answer: "would a player notice if this broke?"

### Test Categories
- **`tests/integration/`** — Behavioral/integration tests. These verify
  that systems work together correctly: water flows downhill, structures
  collapse under excess load, intruders pathfind around hazards, crafting
  produces expected results. **Run these after every change.**
- **`tests/<domain>/`** — Domain unit tests (physics, building, intruders,
  rendering, ui, world, core, utils). Run the relevant domain when
  working in that area. Not necessary to run all domains every time.
- **`tests/benchmarks/`** — Performance profiling. Run manually when
  optimizing.

### Guidelines
- All game logic must have tests — but focus on behaviors that matter,
  not line coverage for its own sake.
- Tests run headless — no Panda3D window, no GPU.
- Use `config.py` values in assertions (not hardcoded duplicates) so
  tests stay valid when balance changes.
- Fixtures in `conftest.py` for common setups (small grids, stone grids).
- **Never weaken tests without user confirmation.** When a test fails,
  fix the underlying code — don't relax thresholds, loosen assertions,
  or widen tolerances. A failing test is a signal that something is
  wrong; investigate the root cause first.

---

## Working Style

- **High autonomy.** Read, write, edit files, and run tests freely.
- **Give best effort.** Write production-quality code, not sketches.
  Handle edge cases. Add docstrings to public APIs.
- **Run relevant tests after changes** — don't submit broken code.
- **Research first.** For complex systems (physics, AI, algorithms),
  review the scientific/engineering literature online before
  implementing. Don't reinvent the wheel — adapt established methods,
  document the source, and note any simplifications made.
- **Ask before:** major architectural changes (new subsystem, changing
  EventBus contract, restructuring directory layout), git operations
  (commits, branch changes), deleting files.
- **Don't ask for:** refactoring within established patterns, fixing
  bugs, removing dead code, adding tests, cleaning imports.
