# Crafting Rework

**Status:** Draft -- 2026-03-10

## Dependency References

- `building/crafting_system.py`
- `building/crafting_book.py`
- `building/crafting_recipes_functional.py`
- `building/crafting_recipes_natural.py`
- `building/crafting_helpers.py`
- `building/crafting_journal.py`
- `building/move_system.py`
- `building/build_system.py`
- `dungeon_core/mana.py`
- `config/economy.py`
- `config/materials.py`
- `config/voxels.py`
- `config/building.py`
- `config/rendering.py`
- `rendering/effects.py`
- `rendering/camera.py`
- `ui/crafting_book_panel.py`
- `ui/enchanted_panel.py`
- `ui/hud.py`
- `ui/style.py`

---

## Problem Statement

The current crafting system requires the player to gather physical
materials (dig blocks, pick them up, carry them), select a recipe from
the crafting book panel, wait for valid positions to highlight, and click
to place. This flow has several problems:

1. **Material gathering is tedious, not strategic.** The interesting
   decision is WHERE an object goes and HOW it interacts with
   physics/neighbors. But the current flow front-loads a boring
   gather-carry loop before the interesting part begins.

2. **Mana costs are binary.** Six enchanted recipes have a `mana_cost`
   field, but it works as a simple gate: you have enough mana or you do
   not. There is no trade-off between spending mana vs. spending
   materials.

3. **No cost preview before committing.** The player selects a recipe,
   scans for green highlights, and only then discovers whether a
   position is valid. Costs are not shown in the UI until craft mode
   is already active.

4. **No visibility into object relationships.** Placing a pressure plate
   near an enchanted door creates a connection, but the player cannot see
   this relationship before or after placement. Building feels like
   placing isolated objects rather than engineering interconnected
   systems.

5. **The crafting book is a lookup chore.** 27 recipes listed vertically
   with text descriptions. The player must read descriptions and
   mentally map "what material do I need, where does it go" -- this is
   memorization, not design.

The game's shift toward a symbiotic dungeon-intruder relationship
amplifies these problems: the player needs to build more complex,
interconnected traps and entertainment structures, and the current system
makes that laborious rather than creative.

---

## Design Goals

1. Shift cognitive load from "gather ingredients" to "engineer spatial
   relationships."
2. Make mana a meaningful resource trade-off at every tier of play.
3. Teach through preview, not through text descriptions.
4. Make connections between objects visible and inspectable.
5. Maintain compatibility with existing save files and physics systems.
6. Stay headless-testable (no Panda3D required for logic tests).

---

## 1. Mana-or-Materials Cost Model

### 1.1 Core Principle

Every placeable object has a **total mana cost**. Materials in the
player's inventory **offset** that cost. Having the right physical
ingredient reduces the mana required; having nothing means you pay
the full cost in mana. Some high-tier ingredients are
**non-substitutable** -- no amount of mana can replace them.

This creates a spectrum from "pure mana crafting" (convenient,
expensive) to "full material crafting" (cheap in mana, requires
logistics), with partial substitution in between.

### 1.2 Cost Decomposition

Each recipe's total cost is composed of:

```
total_mana_cost = assembly_cost
               + sum(ingredient_mana_value[i] for each missing ingredient)
```

- **`assembly_cost`**: The irreducible mana cost of combining/
  transmuting ingredients into the output. Always paid, even with full
  materials. Represents the magical energy needed to forge, enchant, or
  bind. For basic blocks (slope, stairs, tarp), this is 0 -- no magic
  required.

- **`ingredient_mana_value`**: Per-ingredient mana substitute cost. If
  the player provides the physical ingredient, this component is waived.
  If not, the player pays this in mana. Different materials have
  different substitute costs reflecting their rarity and magical
  potency.

### 1.3 Mana Substitute Cost LUT

New LUT in `config/economy.py`, keyed by voxel type:

```python
MANA_SUBSTITUTE_COST: dict[int, int] = {
    # Natural materials (cheap -- common in dungeon)
    VOXEL_DIRT:        5,
    VOXEL_STONE:       10,
    VOXEL_SANDSTONE:   10,
    VOXEL_LIMESTONE:   12,
    VOXEL_CHALK:       8,
    VOXEL_GRANITE:     20,
    VOXEL_MARBLE:      18,
    VOXEL_BASALT:      22,
    VOXEL_OBSIDIAN:    40,

    # Metal ingots (moderate -- must be smelted)
    VOXEL_IRON_INGOT:    30,
    VOXEL_COPPER_INGOT:  25,
    VOXEL_GOLD_INGOT:    50,

    # Enchanted metal (expensive -- requires mana crystal + lava)
    VOXEL_ENCHANTED_METAL: 80,
}
```

Materials absent from `MANA_SUBSTITUTE_COST` are **non-substitutable**.
If a recipe requires them, the player must provide them physically.
This creates late-game logistics goals: mining deep for mana crystals
and gold ore, or collecting from intruders.

### 1.4 Revised Recipe Cost Structure

```python
@dataclass(frozen=True)
class RecipeIngredient:
    vtype: int                    # Voxel type required
    substitutable: bool = True    # Can mana replace this?
    mana_value: int = 0           # Mana cost if substituted (auto from LUT)

    def __post_init__(self):
        if self.substitutable and self.mana_value == 0:
            object.__setattr__(
                self, 'mana_value',
                MANA_SUBSTITUTE_COST.get(self.vtype, 0),
            )
        if self.vtype not in MANA_SUBSTITUTE_COST:
            object.__setattr__(self, 'substitutable', False)
```

```python
@dataclass
class CraftCost:
    assembly: int                            # Irreducible mana
    material_mana: int                       # Substitution mana
    total: int                               # assembly + material_mana
    materials_consumed: dict[int, int]       # What leaves the inventory
    missing: list[RecipeIngredient]           # Non-sub items not held
    craftable: bool                           # All non-sub ingredients present
```

### 1.5 Cost Computation

```python
def compute_craft_cost(
    recipe: CraftingRecipe,
    held_materials: dict[int, int],
) -> CraftCost:
    material_mana = 0
    materials_consumed: dict[int, int] = {}
    missing: list[RecipeIngredient] = []

    for ing in recipe.ingredients:
        if held_materials.get(ing.vtype, 0) > 0:
            # Player has this ingredient -- no mana substitution
            materials_consumed[ing.vtype] = (
                materials_consumed.get(ing.vtype, 0) + 1
            )
        elif ing.substitutable:
            material_mana += ing.mana_value
        else:
            missing.append(ing)

    total = recipe.assembly_cost + material_mana
    return CraftCost(
        assembly=recipe.assembly_cost,
        material_mana=material_mana,
        total=total,
        materials_consumed=materials_consumed,
        missing=missing,
        craftable=len(missing) == 0,
    )
```

### 1.6 Cost Display

Before placement, the palette shows a cost summary per object:

```
Spike Trap                      [30 mana]
  Iron Ingot: in bag (0 mana)    OR   missing (30 mana)
  Assembly: 10 mana
  Total: 10 mana                 OR   40 mana
```

For non-substitutable ingredients:

```
Gold Bait                       [cannot craft]
  Gold Ingot: REQUIRED (cannot substitute with mana)
  Assembly: 20 mana
```

Color coding: green (affordable with materials), yellow (affordable with
mana substitution), red (cannot afford or missing non-substitutable).

### 1.7 Worked Examples

**Early game (100 mana/s generation, 1000 max capacity):**

| Recipe | With materials | Without materials |
|--------|---------------|-------------------|
| Slope | 0 mana (mundane) | 10 mana (conjure stone) |
| Spike Trap | 10 mana (assembly only) | 40 mana (10 + 30 iron sub) |
| Tarp | 0 mana (mundane) | 5 mana (conjure dirt) |
| Fragile Floor | 0 mana (mundane) | 8 mana (conjure chalk) |

Player can build everything from materials alone, or spend small mana to
skip gathering. 25 spike traps at 40 mana each = 1000 mana = entire
pool. Pure-mana building is convenient but not free.

**Mid game (100 mana/s, growing trap upkeep):**

| Recipe | With materials | Without materials |
|--------|---------------|-------------------|
| Enchanted Door | 20 mana | 100 mana (20 + 80 enchanted sub) |
| Heat Beacon | 25 mana | 55 mana (25 + 30 metal sub) |
| Gold Bait | 20 mana | Cannot (gold non-substitutable) |
| Pressure Plate | 15 mana | 45 mana (15 + 30 metal sub) |

With 20 active traps consuming 20-40 mana/s in upkeep, only 60-80
mana/s remains for new construction. Player is incentivized to mine
materials rather than conjure everything.

**Late game (expanded mana generation via crystal nodes):**

Enough mana income to conjure freely, but non-substitutable ingredients
(mana crystals for enchanted metal, gold for gold bait, future intruder
drops) still require physical logistics. Growth pressure: expand
territory to reach crystal veins and deep ores.

---

## 2. Object Palette Interface

### 2.1 Design Rationale

The crafting book is replaced by an **object palette** -- a categorized
grid of placeable objects. The emphasis shifts from "what ingredients do
I need?" to "what do I want to build, and where?"

### 2.2 Categories

Objects are organized into functional categories:

| Category | Contents |
|----------|----------|
| **Terrain** | Slope, Stairs, Granite Pillar, Marble Wall, Stone Brick |
| **Barriers** | Reinforced Wall, Door, Iron Bars, Floodgate |
| **Traps** | Spike Trap, Fragile Floor, Rolling Stone, Tarp |
| **Thermal** | Heat Beacon, Steam Vent, Obsidian Forge |
| **Enchanted** | Enchanted Door, Enchanted Floodgate, Gold Bait, Pressure Plate, Alarm Bell |
| **Plumbing** | Pipe, Pump |
| **Crafting** | Ore Smelting, Glass, Mana Infusion |

Stored in `CraftingRecipe.category` (new field), categories listed in
`config/building.py`:

```python
PALETTE_CATEGORIES = [
    "terrain", "barriers", "traps", "thermal",
    "enchanted", "plumbing", "crafting",
]
```

### 2.3 Palette UI Layout

New file `ui/object_palette.py` replaces `ui/crafting_book_panel.py`:

- **Category tabs** across the top. Clicking a tab filters the grid.
- **Object grid** below: clickable cells showing name, icon color (from
  `VOXEL_COLORS`), and compact cost indicator.
- **Cost indicator per cell**: mana cost with current inventory.
  Green = affordable with materials. Yellow = affordable via mana
  substitution. Red = cannot afford. Grey = undiscovered ("???").
- **Detail panel** at the bottom (on selection): full cost breakdown,
  description, behavior hint, effect radius.

### 2.4 Selection Flow

1. Player opens palette (B key -- same binding as current crafting book).
2. Player clicks an object cell.
3. System computes `CraftCost` given current inventory.
4. If `craftable` (all non-substitutable ingredients present), placement
   mode activates.
5. Cursor becomes ghost preview of the object (existing system).
6. Player moves cursor. Preview shows validity, cost, effect radius,
   connections (sections 3-4).
7. Player clicks to place. Mana deducted, materials consumed (if used).
8. Remains in placement mode until ESC or can no longer afford.

### 2.5 Differences from Current Flow

| Current | New |
|---------|-----|
| Must hold physical material | Can enter craft mode with or without materials |
| Text-based recipe list | Categorized grid with visual cost indicators |
| No cost preview until in craft mode | Cost visible in palette before selection |
| Materials consumed on placement only | Materials optionally consumed (reduce mana) |
| `required_inputs` is frozenset | `ingredients` is list with per-item substitution |

### 2.6 Backward Compatibility

`CraftingBook` is retained internally. `ObjectPalette` wraps it, adding
category grouping and cost computation. `CraftingJournal` continues to
track discovery. `CraftingSystem` state machine is refactored to accept
the new cost model, but `"craft_recipe_selected"` still passes a
`recipe_name`.

---

## 3. Placement Preview

### 3.1 What the Player Sees on Hover

When hovering a position in placement mode, four layers of feedback:

**Layer 1 -- Ghost Block (existing, extended)**

- Valid position: ghost block in object's color with green tint.
- Invalid position: ghost block in red tint, dimmer.
- Uses existing `_show_ghost_preview` in `rendering/effects.py`.

**Layer 2 -- Effect Radius (new)**

When `effect_radius > 0`, a semi-transparent boundary shell around the
affected area. Color matches function:

- Orange for thermal (heat beacon, steam vent)
- Blue for detection (pressure plate, alarm bell)
- Gold for lure (gold bait)

```python
# config/building.py (additions)
EFFECT_RADIUS: dict[int, int] = {
    VOXEL_HEAT_BEACON: 3,
    VOXEL_PRESSURE_PLATE: 1,
    VOXEL_ALARM_BELL: 2,
    VOXEL_STEAM_VENT: 3,
    VOXEL_GOLD_BAIT: 6,
}
```

Implementation: new `_show_radius_preview(x, y, z, radius, color)` in
`EffectsManager`, using the existing marker pooling pattern. Maximum
radius is 6 (gold bait) -- at most ~150 boundary cells, well within
the existing pool size.

**Layer 3 -- Behavior Hint (HUD text)**

The hover label in the HUD shows context-specific information:

```
[Spike Trap] 10 mana (iron saves 30)  |  Deals damage when stepped on
[Heat Beacon] 25 mana (full materials) |  Radiates heat in 3-cell radius
[Pressure Plate] 45 mana (no metal)   |  Triggers linked doors/gates on step
```

Behavior hint comes from `CraftingRecipe.behavior_hint` (new field).
Cost summary from `compute_craft_cost`. Replaces the current generic
"Click to craft X at (x, y, z)" text.

**Layer 4 -- Cost Tooltip (new panel)**

Small panel near the cursor showing the full cost breakdown from
section 1.6. Uses the `EnchantedBlockPanel` layout pattern -- a
`DirectFrame` with `DirectLabel` children, shown on hover, hidden on
hover-clear. New file `ui/cost_tooltip.py`.

### 3.2 Preview Data Flow

```
voxel_hover event
  -> CraftingSystem._on_voxel_hover
      -> compute check_fn(grid, x, y, z, ...)
      -> compute_craft_cost(recipe, held_materials)
      -> publish "craft_hover_valid" or "craft_hover_invalid"
          with: cost, effect_radius, behavior_hint    (NEW fields)
  -> EffectsManager
      -> _show_ghost_preview(...)
      -> _show_radius_preview(...)                    (NEW)
  -> HUD
      -> display cost summary + behavior hint
  -> CostTooltip                                      (NEW)
      -> display full cost breakdown
```

The `"craft_hover_valid"` event gains new keyword fields: `cost`,
`effect_radius`, `behavior_hint`. Existing subscribers that do not
use these fields are unaffected (they accept `**kw`).

### 3.3 Config Constants

```python
# config/rendering.py (additions)
RADIUS_PREVIEW_OPACITY = 0.25
RADIUS_COLOR_THERMAL = (1.0, 0.5, 0.1, 0.25)
RADIUS_COLOR_DETECTION = (0.3, 0.5, 1.0, 0.25)
RADIUS_COLOR_LURE = (1.0, 0.85, 0.2, 0.25)
```

---

## 4. Connection Visualization

### 4.1 Connection Types

Objects in the dungeon form logical connections:

| Type | Visual | Description | Examples |
|------|--------|-------------|----------|
| **Trigger** | Pulsing yellow line | Signal from sensor to actuator | Pressure plate -> enchanted door/floodgate |
| **Flow** | Animated blue arrows | Fluid movement direction | Pipe -> pump -> pipe, water source -> channel |
| **Thermal** | Orange gradient fade | Heat radiation path | Heat beacon -> affected cells |
| **Structural** | White dotted line | Load-bearing dependency | Rolling stone -> slope below, tarp -> walls |

### 4.2 When Connections Are Visible

Three visibility modes:

1. **On placement preview**: When hovering in placement mode, show
   connections that WOULD be created if the object were placed here.
   Teaches the player what this placement achieves.

2. **On block selection**: When the player clicks an existing placed
   block, show all connections from/to that block. Generalizes the
   existing `"enchanted_block_selected"` pattern to all connectable
   blocks.

3. **Render mode overlay**: A new "Connections" render mode in the
   render mode selector. Shows ALL connections on the current z-level.
   For design review -- the player sees the full picture.

### 4.3 Connection Detection

Connections computed on demand (not cached). New module
`building/connections.py`:

```python
@dataclass
class Connection:
    source: tuple[int, int, int]
    target: tuple[int, int, int]
    conn_type: str        # "trigger", "flow", "thermal", "structural"
    bidirectional: bool   # True for thermal, False for trigger signals

def find_connections(
    grid: VoxelGrid,
    x: int, y: int, z: int,
    vtype: int | None = None,
) -> list[Connection]:
    """Find all logical connections from the block at (x, y, z).

    If vtype is provided, compute connections as if that type were
    placed at (x, y, z) -- used for placement preview.
    """
```

Connection rules defined per vtype:

- **Trigger**: pressure plate scans within trigger range for enchanted
  doors/floodgates. Alarm bell scans detection range.
- **Flow**: pipe/pump scan 6-neighbors for other pipes/pumps.
- **Thermal**: heat beacon scans within `EFFECT_RADIUS` for any block.
- **Structural**: rolling stone checks slope/stairs below; tarp checks
  opposite walls.

### 4.4 Rendering

Connections rendered as 3D line segments using `LineSegs` (Panda3D
primitive). `EffectsManager` gains a `_connection_nps` pool for markers,
using the same pooling pattern as craft markers. Color from connection
type:

```python
# config/rendering.py (additions)
CONNECTION_COLOR_TRIGGER = (1.0, 0.9, 0.2, 0.6)
CONNECTION_COLOR_FLOW = (0.3, 0.5, 1.0, 0.6)
CONNECTION_COLOR_THERMAL = (1.0, 0.5, 0.1, 0.5)
CONNECTION_COLOR_STRUCTURAL = (0.8, 0.8, 0.8, 0.4)
```

### 4.5 Events

```python
"block_selected"         # Player clicked any block (generalizes enchanted_block_selected)
    # x, y, z, vtype
"connections_updated"    # Connection visualization data ready
    # connections: list[Connection]
"connections_cleared"    # Clear connection visualization
```

---

## 5. Recipe Structure Changes

### 5.1 CraftingRecipe Evolution

```python
# BEFORE
@dataclass
class CraftingRecipe:
    name: str
    description: str
    required_inputs: frozenset[int]
    check_fn: Callable[..., bool]
    craft_fn: Callable[..., bool]
    output_vtype: int = 0
    mana_cost: int = 0

# AFTER
@dataclass
class CraftingRecipe:
    name: str
    description: str
    ingredients: list[RecipeIngredient]
    assembly_cost: int
    check_fn: Callable[..., bool]
    craft_fn: Callable[..., bool]
    output_vtype: int = 0
    category: str = "traps"
    effect_radius: int = 0
    behavior_hint: str = ""

    @property
    def required_inputs(self) -> frozenset[int]:
        """Backward-compatible: all ingredient voxel types."""
        return frozenset(ing.vtype for ing in self.ingredients)

    @property
    def has_non_substitutable(self) -> bool:
        return any(not ing.substitutable for ing in self.ingredients)

    @property
    def mana_cost(self) -> int:
        """Backward-compatible: total cost assuming no materials."""
        return self.assembly_cost + sum(
            ing.mana_value for ing in self.ingredients
            if ing.substitutable
        )
```

### 5.2 Example Conversion: Spike Trap

```python
# BEFORE
CraftingRecipe(
    "Spike Trap",
    "Place any metal ingot on air above solid ground to set a spike trap",
    frozenset({VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT}),
    _check_spike_trap,
    _craft_spike_trap,
    output_vtype=VOXEL_SPIKE,
)

# AFTER
CraftingRecipe(
    "Spike Trap",
    "Place on floor. Deals piercing damage when stepped on.",
    ingredients=[RecipeIngredient(VOXEL_IRON_INGOT)],
    assembly_cost=10,
    check_fn=_check_spike_trap,
    craft_fn=_craft_spike_trap,
    output_vtype=VOXEL_SPIKE,
    category="traps",
    effect_radius=0,
    behavior_hint="Deals damage when an intruder steps on it.",
)
```

The recipe specifies a single canonical ingredient for cost calculation.
Alternative metals (copper, gold) are still accepted by `check_fn`,
which validates geometry regardless of specific metal type.

### 5.3 check_fn and craft_fn Adaptations

`check_fn` signature unchanged: `(grid, x, y, z, held_type) -> bool`.
When the player has no physical material (pure mana crafting),
`held_type` is set to the recipe's canonical ingredient vtype.
`check_fn` validates geometry only.

`craft_fn` gains optional `cost` parameter:

```python
def _craft_spike_trap(
    grid, x, y, z, held_type, event_bus,
    held_metal=METAL_NONE,
    cost: CraftCost | None = None,
) -> bool:
```

When `cost.materials_consumed` is empty (pure mana craft), `craft_fn`
uses the default metal type. When materials are consumed, the metal type
comes from the consumed material, as today.

### 5.4 Full Recipe Migration Table

| Recipe | Category | Assembly | Ingredients (mana sub) | Effect Radius |
|--------|----------|----------|------------------------|---------------|
| Marble Wall | terrain | 0 | marble (18) | 0 |
| Ore Smelting | crafting | 0 | ore (non-sub) | 0 |
| Obsidian Forge | crafting | 0 | basalt (22) | 0 |
| Mana Infusion | crafting | 30 | mana crystal (non-sub) | 0 |
| Stone Brick | terrain | 0 | limestone (12) | 0 |
| Glass | crafting | 0 | sandstone (10) | 0 |
| Granite Pillar | terrain | 0 | granite (20) | 0 |
| Reinforced Wall | barriers | 5 | metal ingot (30) | 0 |
| Treasure | terrain | 10 | gold ingot (non-sub) | 0 |
| Slope | terrain | 0 | stone (10) | 0 |
| Stairs | terrain | 0 | stone (10) | 0 |
| Door | barriers | 5 | metal ingot (30) | 0 |
| Spike Trap | traps | 10 | metal ingot (30) | 0 |
| Tarp | traps | 0 | dirt (5) | 0 |
| Rolling Stone | traps | 5 | granite (20) | 0 |
| Gold Bait | enchanted | 20 | gold ingot (non-sub) | 6 |
| Heat Beacon | thermal | 25 | metal ingot (30) | 3 |
| Pressure Plate | enchanted | 15 | metal ingot (30) | 1 |
| Iron Bars | barriers | 5 | metal ingot (30) | 0 |
| Floodgate | barriers | 10 | metal ingot (30) | 0 |
| Alarm Bell | enchanted | 20 | metal ingot (30) | 2 |
| Enchanted Door | enchanted | 20 | enchanted metal (80) | 0 |
| Enchanted Floodgate | enchanted | 20 | enchanted metal (80) | 0 |
| Fragile Floor | traps | 0 | chalk (8) | 0 |
| Pipe | plumbing | 5 | metal ingot (30) | 0 |
| Pump | plumbing | 10 | metal ingot (30) | 0 |
| Steam Vent | thermal | 15 | obsidian (40) | 3 |

---

## 6. Migration Path

Six phases, each independently testable. No phase breaks existing tests
until explicitly noted.

### Phase 1: Data Model

Introduce `RecipeIngredient`, `CraftCost`, `compute_craft_cost()` without
changing runtime behavior.

**Create:**
- `building/craft_cost.py` -- new dataclasses and cost function

**Modify:**
- `config/economy.py` -- add `MANA_SUBSTITUTE_COST` LUT
- `building/crafting_book.py` -- add `ingredients`, `assembly_cost`,
  `category`, `effect_radius`, `behavior_hint` to `CraftingRecipe`.
  Keep `required_inputs` and `mana_cost` as backward-compatible
  properties
- `building/crafting_recipes_natural.py` -- convert declarations
- `building/crafting_recipes_functional.py` -- convert declarations

**Tests:** New `tests/building/test_craft_cost.py`. All existing tests
pass (backward-compatible properties).

### Phase 2: CraftingSystem Cost Integration

Replace the binary mana check with `compute_craft_cost`.

**Modify:**
- `building/crafting_system.py` -- use `compute_craft_cost` instead of
  `is_mana_powered` logic. Consume from `cost.materials_consumed`.
  Deduct `cost.total`. Remove `_active_held_type` tracking.

**Behavior change:** Players can craft without holding materials (paying
mana). Players with materials pay less mana. This is the core gameplay
change.

**Tests:** Extend `tests/building/test_crafting.py` for mana-only,
partial-material, and non-substitutable blocking.

### Phase 3: Object Palette UI

Replace `CraftingBookPanel` with `ObjectPalette`.

**Create:**
- `ui/object_palette.py` -- categorized grid panel

**Modify:**
- `ui/hud.py` -- update button label and event wiring
- `main.py` -- wire `ObjectPalette`

**Keep:** `building/crafting_journal.py` unchanged. Discovery works.

**Tests:** New `tests/ui/test_object_palette.py`.

### Phase 4: Preview Extensions

Add effect radius, behavior hints, cost tooltip.

**Create:**
- `ui/cost_tooltip.py` -- hover cost breakdown panel
- Add `EFFECT_RADIUS` to `config/building.py`
- Add radius/tooltip constants to `config/rendering.py`

**Modify:**
- `rendering/effects.py` -- add `_show_radius_preview`
- `ui/hud.py` -- extend `_on_craft_hover_valid` for hints and cost
- `building/crafting_system.py` -- pass new fields in hover events

**Tests:** New `tests/rendering/test_preview.py`.

### Phase 5: Connection Visualization

Show logical connections between blocks.

**Create:**
- `building/connections.py` -- `find_connections()`, `Connection`
  dataclass, detection rules per vtype

**Modify:**
- `rendering/effects.py` -- connection line rendering with pooling
- `rendering/camera.py` -- publish `"block_selected"` on click
- `ui/render_mode_selector.py` -- add "Connections" mode

**Tests:** New `tests/building/test_connections.py`.

### Phase 6: Cleanup

Remove deprecated code.

**Remove:**
- `ui/crafting_book_panel.py` (replaced by `object_palette.py`)

**Modify:**
- `docs/events.md` -- add new events, update existing

---

## 7. Impact on Game Loop

### 7.1 Early Game (first ~100 seconds)

**Current:** Player digs for ores, smelts ingots, carries them. Building
is slow because of gather-carry.

**New:** Player immediately places basic traps using mana. 5-40 mana per
placement. At 100 mana/s and 1000 max, ~25 basic traps before needing
to wait. The emphasis shifts to "where do I place these?" The preview
system teaches what each object does through hover feedback.

Digging still rewards: mined materials reduce mana cost. A player who
smelts iron for a spike trap pays 10 mana (assembly) instead of 40
(assembly + iron substitute).

### 7.2 Mid Game (~2-8 minutes)

Mana-or-materials trade-off becomes the central economic tension:

- Spend mana freely to build fast (risk running dry for trap upkeep)
- Invest in material logistics to reduce mana costs (slower, sustainable)
- Prioritize which traps get physical materials (non-substitutable gold
  for gold bait, mana crystals for enchanted blocks)

With 20 active traps consuming 20-40 mana/s in upkeep, only 60-80
mana/s remains for new construction. Growth pressure drives territorial
expansion toward mana crystal veins.

### 7.3 Late Game (8+ minutes)

Non-substitutable ingredients create logistics goals:

- Mana crystals (deep excavation) for enchanted metal
- Gold ore (deep, rare) for gold bait
- Future: exotic materials from intruder equipment

Mana generation expands through soul capture (+100 max per soul),
crystal nodes, and sprite injection (existing mechanics). The player
is an engineer optimizing an interconnected system: trap placement for
physics interactions, connection networks for automation, material
logistics for non-substitutables, mana budgeting across construction
and upkeep.

### 7.4 Symbiotic Loop Integration

- Intruder equipment becomes a source of non-substitutable ingredients
  (future: exotic metals, crystals)
- Entertainment structures (gold bait, treasure) are expensive but
  attract intruders who provide souls
- Preview and connection systems help the player design traps that fit 
  together to accomplish some specific objective (kill the intruder, 
  give them loot, scare them away...)

---

## 8. Config Constants Summary

### `config/economy.py` additions

```python
MANA_SUBSTITUTE_COST: dict[int, int] = {
    VOXEL_DIRT: 5,       VOXEL_STONE: 10,       VOXEL_SANDSTONE: 10,
    VOXEL_LIMESTONE: 12, VOXEL_CHALK: 8,        VOXEL_GRANITE: 20,
    VOXEL_MARBLE: 18,    VOXEL_BASALT: 22,      VOXEL_OBSIDIAN: 40,
    VOXEL_IRON_INGOT: 30, VOXEL_COPPER_INGOT: 25, VOXEL_GOLD_INGOT: 50,
    VOXEL_ENCHANTED_METAL: 80,
}
```

### `config/building.py` additions

```python
PALETTE_CATEGORIES = [
    "terrain", "barriers", "traps", "thermal",
    "enchanted", "plumbing", "crafting",
]

EFFECT_RADIUS: dict[int, int] = {
    VOXEL_HEAT_BEACON: 3,    VOXEL_PRESSURE_PLATE: 1,
    VOXEL_ALARM_BELL: 2,     VOXEL_STEAM_VENT: 3,
    VOXEL_GOLD_BAIT: 6,
}
```

### `config/rendering.py` additions

```python
RADIUS_PREVIEW_OPACITY = 0.25
RADIUS_COLOR_THERMAL = (1.0, 0.5, 0.1, 0.25)
RADIUS_COLOR_DETECTION = (0.3, 0.5, 1.0, 0.25)
RADIUS_COLOR_LURE = (1.0, 0.85, 0.2, 0.25)

CONNECTION_COLOR_TRIGGER = (1.0, 0.9, 0.2, 0.6)
CONNECTION_COLOR_FLOW = (0.3, 0.5, 1.0, 0.6)
CONNECTION_COLOR_THERMAL = (1.0, 0.5, 0.1, 0.5)
CONNECTION_COLOR_STRUCTURAL = (0.8, 0.8, 0.8, 0.4)
```

### `ui/style.py` additions

```python
PALETTE_CELL_BG = (0.12, 0.12, 0.18, 0.7)
PALETTE_CELL_SELECTED = (0.25, 0.22, 0.08, 0.9)
COST_AFFORDABLE_COLOR = (0.3, 1.0, 0.3, 1)
COST_TIGHT_COLOR = (1.0, 0.85, 0.2, 1)
COST_UNAFFORDABLE_COLOR = (1.0, 0.3, 0.3, 1)
```

---

## 9. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Pure mana trivializes early game | Substitute costs add up: 25 spike traps = 1000 mana = entire pool. Players learn materials save mana. |
| Non-substitutable ingredients frustrate new players | No non-substitutable ingredients in early game. Preview shows "REQUIRED" clearly before commit. |
| Effect radius preview too expensive | Marker pooling (existing pattern). Max radius 6, shell is ~150 cells. Pool 50 markers. |
| Connection computation too slow | Local detection only (1-6 cell radius). ~26 neighbors checked. Negligible vs. a single `check_fn`. |
| Backward-compatible properties cause confusion | Docstring and deprecation warning. Remove after phase 6. |
| Save file migration | Recipes are code-defined, not serialized. No save migration needed. |

---

## 10. New Module Dependency Graph

```
config/economy.py           -- MANA_SUBSTITUTE_COST (new LUT)
    |
building/craft_cost.py      -- RecipeIngredient, CraftCost, compute_craft_cost()
    |                          Deps: config/economy
    |
building/crafting_book.py   -- CraftingRecipe (extended)
    |                          Deps: craft_cost, config
    |
building/crafting_system.py -- Cost-integrated placement
    |                          Deps: crafting_book, craft_cost, mana
    |
building/connections.py     -- Connection detection (new)
    |                          Deps: config, world.voxel_grid
    |
ui/object_palette.py        -- Categorized build panel (new)
    |                          Deps: crafting_journal, craft_cost, style
    |
ui/cost_tooltip.py          -- Hover cost breakdown (new)
    |                          Deps: core.event_bus, style
    |
rendering/effects.py        -- Radius preview, connection lines (extended)
                               Deps: config/rendering, config/building
```

No circular dependencies introduced. All new modules follow EventBus
communication between UI and game logic.

---

## 11. Testing Strategy

### New Test Files

- `tests/building/test_craft_cost.py` -- `compute_craft_cost` with all
  combinations: full materials, partial, none, non-substitutable missing,
  mana affordability, multiple ingredients
- `tests/building/test_connections.py` -- connection detection for
  trigger, flow, thermal, structural types
- `tests/ui/test_object_palette.py` -- category filtering, cost
  computation, selection events, discovery integration

### Extended Test Files

- `tests/building/test_crafting.py` -- mana-only crafting,
  partial-material crafting, non-substitutable blocking, cost deduction
- `tests/economy/test_mana_system.py` -- verify mana deduction via
  `CraftCost.total`

### Regression

All existing crafting tests pass without modification during Phase 1
(backward-compatible properties). After Phase 2, tests referencing
`mana_cost` directly are updated to use `assembly_cost` +
`compute_craft_cost`.
