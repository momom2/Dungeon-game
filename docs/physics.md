# Physics Algorithm Reference

Developer reference for all physics systems in Dungeon Builder. Each
system runs on fixed tick intervals, uses NumPy arrays for state, and
communicates via EventBus.

All physics systems satisfy CFL stability (CFL < 1.0) where applicable,
cap cascading failures to `MAX_CASCADE_PER_TICK` (64) per tick, and use
LUT-based material properties from `config/materials.py`.

> **Source files documented here.** Update this doc when changing:
>
> - `world/physics/gravity.py`
> - `world/physics/structural.py`
> - `world/physics/temperature.py`
> - `world/physics/humidity.py`
> - `world/physics/thermal_stress.py`
> - `world/physics/water.py`
> - `world/physics/water_flow_strategies.py`
> - `world/physics/pipe.py`
> - `dungeon_core/mana.py`
> - `config/physics.py`
> - `config/materials.py`
> - `config/economy.py`
> - `world/voxel_grid.py`

---

## Tick Schedule

All physics runs on fixed intervals (20 ticks/sec = 50 ms/tick):

| System | Interval | File |
|--------|----------|------|
| Gravity (falling) | 1 | `world/physics/gravity.py` |
| Granular spreading | 2 | `world/physics/gravity.py` |
| Water & lava flow | 2 | `world/physics/water.py` |
| Temperature diffusion | 5 | `world/physics/temperature.py` |
| Humidity diffusion | 5 | `world/physics/humidity.py` |
| Pipe & pump networks | 5 | `world/physics/pipe.py` |
| Structural integrity | 10 | `world/physics/structural.py` |
| Connectivity check | 10 | `world/physics/gravity.py` |
| Thermal stress | 10 | `world/physics/thermal_stress.py` |

---

## 1. Gravity

**File:** `world/physics/gravity.py`
**Algorithm:** Discrete block falling + connectivity flood-fill + angle
of repose + impact cascades

### 1.1 Loose Block Falling

Every tick, loose blocks above air cells fall downward, up to
`MAX_FALL_PER_TICK` (5) cells per tick. Fall distance is tracked in a
`uint8` array for impact calculation.

### 1.2 Connectivity Check

Every 10 ticks, a 6-connected flood-fill propagates from anchor blocks
(bedrock, core, water/lava sources and sinks). Any solid block not
reached by the flood is marked loose and begins falling.

### 1.3 Angle of Repose (Granular Spreading)

Every 2 ticks, loose granular materials (porosity >= 0.2) resting on
solid ground spread laterally into adjacent air cells. This creates
natural piles and slopes after collapses.

### 1.4 Impact Cascades

When a falling block lands after 3+ cells of freefall, impact energy is
calculated:

```
impact_energy = fall_distance * WEIGHT[vtype] * 0.5
```

Impact damages the block below and propagates a shock wave outward
through solid blocks in 6 directions. Each propagation step attenuates
by `SHOCK_ATTENUATION` (0.7). When `shock / capacity > SHATTER_THRESHOLD`
(2.0), brittle materials shatter to air. Below that threshold, blocks
crack (set loose).

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `GRAVITY_TICK_INTERVAL` | 1 | `config/physics.py` |
| `MAX_FALL_PER_TICK` | 5 | `config/physics.py` |
| `CONNECTIVITY_TICK_INTERVAL` | 10 | `config/physics.py` |
| `REPOSE_TICK_INTERVAL` | 2 | `config/physics.py` |
| `SHOCK_ATTENUATION` | 0.7 | `config/physics.py` |
| `SHATTER_THRESHOLD` | 2.0 | `config/physics.py` |
| `MAX_CASCADE_PER_TICK` | 64 | `config/physics.py` |

### Data Structures

- `VoxelGrid.loose` — `np.bool_` array marking disconnected/falling
  blocks
- `fall_distance` — `np.uint8` array tracking accumulated fall per block
- Material LUTs: `WEIGHT`, `CAPACITY`, `SHOCK_TRANSMISSIVITY`,
  `BRITTLENESS` (all in `config/materials.py`)

### Events Published

| Event | Payload | When |
|-------|---------|------|
| `blocks_fell` | — | Loose blocks moved downward |
| `blocks_spread` | — | Granular materials spread laterally |
| `impact` | `count` | Impact cascade damaged blocks |
| `structural_disconnect` | `count` | Connectivity check found floating blocks |

---

## 2. Structural Integrity

**File:** `world/physics/structural.py`
**Algorithm:** Direct stiffness method for load distribution + arch
detection + compressive/shear/tensile failure

### 2.1 Load Distribution

Every 10 ticks, loads are distributed top-down through the voxel grid.
Each block's weight flows downward, distributed to supporting blocks
proportional to their stiffness:

```
F_i = (k_i / sum(k_j)) * F_total
```

Where `k_i` is the stiffness of supporting block `i`.

**Buttressing:** Cardinal neighbors at the same z-level reduce
transmitted load. Each buttressing neighbor applies `BUTTRESS_FACTOR`
(0.03) reduction, clamped to [0.5, 1.0] multiplier on the transmitted
load.

### 2.2 Arch Detection

When a block has no direct support below (air underneath), load is
distributed to the nearest solid blocks up to `MAX_ARCH_SPAN` (5) cells
away in 4 cardinal directions, weighted by `1 / distance`. Line-of-sight
to the support is checked — obstructed paths don't transfer load.

### 2.3 Environmental Modifiers

- **Temperature:** Between 400K and 800K, capacity reduces by up to
  `TEMP_WEAKNESS_FACTOR` (0.5). Represents heat softening.
- **Humidity:** Capacity reduced by `humidity * HUMIDITY_WEAKNESS * porosity`.
  Porous wet materials are weaker.
- **Water buoyancy:** Submerged blocks have weight reduced by
  `WATER_BUOYANCY_FACTOR` (0.6).

### 2.4 Failure Modes

| Mode | Condition | Result |
|------|-----------|--------|
| Compressive | `load > max_load` | Block set loose |
| Shear | `lateral_load > shear_strength` | Block set loose |
| Tensile | `load * span / 2 > tensile_strength` | Unsupported cantilever breaks |

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `STRUCTURAL_TICK_INTERVAL` | 10 | `config/physics.py` |
| `MAX_ARCH_SPAN` | 5 | `config/physics.py` |
| `BUTTRESS_FACTOR` | 0.03 | `config/physics.py` |
| `HUMIDITY_WEAKNESS` | 0.3 | `config/physics.py` |
| `TEMP_WEAKNESS_MIN` | 400 K | `config/physics.py` |
| `TEMP_WEAKNESS_MAX` | 800 K | `config/physics.py` |
| `TEMP_WEAKNESS_FACTOR` | 0.5 | `config/physics.py` |
| `WATER_BUOYANCY_FACTOR` | 0.6 | `config/physics.py` |

### Data Structures

- `load` — `np.float32` array of accumulated vertical load
- `shear_load` — `np.float32` array of accumulated lateral load
- `stress_ratio` — `np.float32` array of load/capacity ratio
- Material LUTs: `WEIGHT`, `CAPACITY`, `STIFFNESS`, `TENSILE_STRENGTH`,
  `SHEAR_STRENGTH`, `POROSITY` (all in `config/materials.py`)

### Events Published

| Event | Payload | When |
|-------|---------|------|
| `structural_failure` | `count` | Blocks collapsed from compressive/shear overload |
| `tensile_failure` | `count` | Blocks broke from unsupported cantilever tension |

---

## 3. Temperature Diffusion

**File:** `world/physics/temperature.py`
**Algorithm:** Discrete heat equation with explicit Euler integration

### 3.1 Heat Diffusion

Every 5 ticks, heat flows between adjacent cells:

```
flow = (T_neighbor - T_self) * min(cond_self, cond_neighbor) * DIFFUSION_RATE
T_new = T + sum(flows for 6 neighbors)
```

CFL stability: max rate = 0.1, max conductivity = 1.0, 6 neighbors
→ CFL = 0.6 < 1.0.

### 3.2 Fixed-Temperature Sources

| Source | Temperature | Condition |
|--------|------------|-----------|
| Lava | 1000 K | Lava voxels |
| Mana crystals (in lava) | 1000 K | Crystal adjacent to lava |
| Mana crystal blocks | 20 K | Cooling effect |
| Heat beacons | Configurable | Functional block |

### 3.3 Surface Heat Loss

Blocks at `z <= SURFACE_Z` lose 5% of their temperature per tick
(environmental sink toward ambient).

### 3.4 Steam Vents

Heat pulses upward through air cells, up to `STEAM_VENT_RANGE` cells.
Blocked by solid voxels.

### 3.5 Metal Melting

Metallic blocks melt when `T >= melt_temperature` (per metal type LUT
in `config/metals.py`). Enchanted blocks are immune to melting.

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `TEMPERATURE_TICK_INTERVAL` | 5 | `config/physics.py` |
| `DIFFUSION_RATE` | 0.1 | `config/physics.py` |
| `SURFACE_HEAT_LOSS` | 0.05 | `config/physics.py` |
| `LAVA_TEMPERATURE` | 1000 K | `config/physics.py` |
| `MANA_CRYSTAL_TEMPERATURE` | 20 K | `config/physics.py` |

### Data Structures

- `temperature` — `np.float32` array
- Material LUT: `CONDUCTIVITY` (`config/materials.py`)
- Metal LUT: `MELT_TEMPERATURE` (`config/metals.py`)

### Events Published

| Event | Payload | When |
|-------|---------|------|
| `metal_melted` | — | A metallic block exceeded its melt temperature |

---

## 4. Humidity Diffusion

**File:** `world/physics/humidity.py`
**Algorithm:** Discrete diffusion equation with porosity-weighted
conductivity + convective heat transport

### 4.1 Humidity Diffusion

Every 5 ticks, humidity flows between adjacent cells weighted by
porosity:

```
rate = min(porosity_a, porosity_b) * HUMIDITY_DIFFUSION_RATE
flow = (H_neighbor - H_self) * rate
```

CFL stability: max rate = 0.05, max porosity = 1.0, 6 neighbors
→ CFL = 0.3 < 1.0.

### 4.2 Convective Heat Transport

Humidity flow carries heat proportionally:

```
heat_carry = |humidity_flow| * CONVECTION_RATE * T_source
```

This models moisture evaporation/condensation transferring thermal
energy. Water near hot blocks creates steam that carries heat away.

### 4.3 Humidity Sources

| Source | Level | Condition |
|--------|-------|-----------|
| Lava-adjacent blocks | `HUMIDITY_SOURCE_LEVEL * porosity` | Block next to lava |
| Water-adjacent blocks | `WATER_HUMIDITY_SOURCE * porosity` | Block next to water |
| Steam vents | `STEAM_VENT_HUMIDITY_PULSE` per cell | Pushed upward through air |

### 4.4 Surface Evaporation

Humidity at `z <= SURFACE_Z` loses 3% per tick.

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `HUMIDITY_TICK_INTERVAL` | 5 | `config/physics.py` |
| `HUMIDITY_DIFFUSION_RATE` | 0.05 | `config/physics.py` |
| `HUMIDITY_SURFACE_LOSS` | 0.03 | `config/physics.py` |
| `HUMIDITY_SOURCE_LEVEL` | 0.8 | `config/physics.py` |
| `WATER_HUMIDITY_SOURCE` | 0.9 | `config/physics.py` |
| `CONVECTION_RATE` | 0.3 | `config/physics.py` |

### Data Structures

- `humidity` — `np.float32` array
- Material LUT: `POROSITY` (`config/materials.py`)

### Events Published

None — updates grid arrays in-place.

---

## 5. Thermal Stress

**File:** `world/physics/thermal_stress.py`
**Algorithm:** Temperature gradient detection + fatigue accumulation

### 5.1 Stress Calculation

Every 10 ticks, thermal stress is computed from the maximum temperature
gradient across a block's 6 neighbors:

```
stress = max(|T_neighbor - T_self|) * CTE[vtype]
thermal_ratio = stress / TENSILE_STRENGTH[vtype]
```

### 5.2 Fatigue Accumulation

Fatigue accumulates when thermal ratio exceeds a threshold:

```
if thermal_ratio >= 0.1:
    fatigue += thermal_ratio * ACCUMULATION_RATE
else:
    fatigue -= DECAY_RATE   (recovery when stress is low)
```

### 5.3 Quench Amplification

Blocks adjacent to water have their thermal stress multiplied by
`QUENCH_MULTIPLIER` (3.0). This models rapid cooling causing explosive
thermal cracking — the same physics that makes obsidian form from
lava-water contact.

### 5.4 Failure

When `fatigue >= THERMAL_CRACK_THRESHOLD` (1.0), the block is set loose
(cracks). Capped at `MAX_CASCADE_PER_TICK` (64) cracks per tick.

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `THERMAL_STRESS_TICK_INTERVAL` | 10 | `config/physics.py` |
| `THERMAL_FATIGUE_ACCUMULATION` | 0.1 | `config/physics.py` |
| `THERMAL_FATIGUE_DECAY` | 0.02 | `config/physics.py` |
| `QUENCH_MULTIPLIER` | 3.0 | `config/physics.py` |
| `THERMAL_CRACK_THRESHOLD` | 1.0 | `config/physics.py` |

### Data Structures

- `thermal_fatigue` — `np.float32` array
- Material LUTs: `CTE` (coefficient of thermal expansion),
  `TENSILE_STRENGTH` (both in `config/materials.py`)

### Events Published

| Event | Payload | When |
|-------|---------|------|
| `thermal_crack` | `count` | Blocks cracked from thermal fatigue |

---

## 6. Water & Lava Flow

**File:** `world/physics/water.py`, `world/physics/water_flow_strategies.py`
**Algorithm:** Pluggable flow strategies with shared gravity + pressure
pipeline

The water system supports two interchangeable flow strategies selected
via `WATER_FLOW_MODEL` config. Both share a common pipeline for gravity
flow, pressure-driven lateral transfer, and level equalization.

### 6.1 Lattice Boltzmann D3Q7 (Default)

**Method:** BGK collision operator on a 7-direction lattice (rest + 6
cardinal) with bounce-back boundary conditions at solid walls.

```
Collision: f_new = f - (1/tau) * (f - f_eq)
Equilibrium: f_eq[i] = w[i] * rho * (1 + 3 * (e_i . u))
Body force: gravity added to z-components (LBM_GRAVITY = 0.003)
Streaming: f_new[neighbor] += f[direction] with bounce-back at solids
```

Density and velocity extracted from distributions. Hydrostatic depth
adds pressure.

| Constant | Value |
|----------|-------|
| `LBM_TAU` | 0.8 (BGK relaxation) |
| `LBM_GRAVITY` | 0.003 |
| `LBM_REST_DENSITY` | 1.0 |

### 6.2 Jacobi Projection

**Method:** Pressure field smoothing via iterative Jacobi solver +
velocity reconstruction from pressure gradients.

```
Pressure: p = water_level + hydrostatic_depth * gravity
Jacobi:   p_new = 0.3 * p_old + 0.7 * avg(neighbors)   (5 iterations)
Velocity: u = -grad(p) * 0.3
Friction: u *= 0.85 per tick
Viscosity: velocity diffusion at 0.02 rate
```

| Constant | Value |
|----------|-------|
| `JACOBI_ITERATIONS` | 5 |
| `JACOBI_GRAVITY` | 1.0 |
| `JACOBI_FRICTION` | 0.85 |

### 6.3 Shared Pipeline

Both strategies share these steps after strategy-specific computation:

1. **Gravity flow:** Water above air falls at full level.
2. **Pressure-driven transfer:** Water moves laterally along pressure
   gradients, capped at half source level per face (conservative).
3. **Level equalization:** 15% rate diffusion smooths oscillations.

### 6.4 Lava Flow (Cellular Automata)

Lava always uses simple cellular automata (not pluggable):

- Gravity: downward at full level.
- Lateral leveling: `diff * LAVA_FLOW_RATE` units transferred, capped
  at half-difference.
- Tracks per-direction outflow for heat and mana crystal transport.

### 6.5 Lava-Water Interaction

When lava and water cells are adjacent:

```
chance = min(water_level, lava_level) / 255
if RNG < chance:
    both consumed → obsidian forms, steam generated
else:
    dominant fluid survives with level = |difference|
```

### 6.6 Water Pressure & Gate Bursting

Column depth exerts hydrostatic pressure as shear load on adjacent
walls. When `pressure > SHEAR_STRENGTH[vtype] * BURST_FACTOR`, the wall
block is destroyed (gate burst).

### 6.7 Seepage

Water adjacent to porous solids increases their humidity:
`humidity += WATER_SEEP_RATE * POROSITY[vtype]`.

### 6.8 Mana Crystal Drift

Discrete mana crystals move probabilistically with lava outflow. Drift
direction follows the lava outflow distribution across faces.

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `WATER_TICK_INTERVAL` | 2 | `config/physics.py` |
| `WATER_FLOW_MODEL` | `"lattice_boltzmann"` | `config/physics.py` |
| `WATER_PRESSURE_WEIGHT` | 0.3 | `config/physics.py` |
| `WATER_BURST_FACTOR` | 1.5 | `config/physics.py` |
| `WATER_SEEP_RATE` | 0.02 | `config/physics.py` |
| `LAVA_FLOW_RATE` | 0.15 | `config/physics.py` |
| `LAVA_PRESSURE_WEIGHT` | 0.5 | `config/physics.py` |
| `LAVA_BURST_FACTOR` | 1.2 | `config/physics.py` |
| `MANA_CRYSTAL_SPAWN_CHANCE` | 0.05 | `config/physics.py` |

### Data Structures

- `water_level`, `lava_level` — `np.uint8` arrays (0-255)
- `water_vx`, `water_vy`, `water_vz` — `np.float32` velocity fields
- `pressure` — `np.float32` array
- LBM `f` — 7-direction distribution array (`np.float32`)
- `mana_crystals` — `np.uint8` array

### Events Published

| Event | Payload | When |
|-------|---------|------|
| `water_flowed` | — | Water levels changed |
| `water_burst` | `count` | Gate blocks burst from pressure |
| `water_lava_reaction` | — | Obsidian formed from lava-water contact |

---

## 7. Pipe & Pump Networks

**File:** `world/physics/pipe.py`
**Algorithm:** BFS component detection + conduction averaging + active
pumping

### 7.1 Network Topology

BFS finds connected components of pipe and pump blocks. Networks are
cached and rebuilt only when `voxel_changed` events fire on pipe/pump
cells.

### 7.2 Passive Conduction

Heat and humidity average across all blocks in a network:

```
conductivity = PIPE_CONDUCTIVITY_BASE * METAL_CONDUCTIVITY_MULT[metal_type]
```

Higher-conductivity metals (copper > iron > gold) transfer heat faster
across pipe networks.

### 7.3 Active Pumping

Pump blocks pull heat, humidity, and water from their intake direction
(opposite the pump's facing) and distribute evenly to all pipes in the
network. Water transfers at `PIPE_WATER_TRANSFER_RATE` (0.5 level units
per pump tick).

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `PUMP_TICK_INTERVAL` | 5 | `config/physics.py` |
| `PIPE_CONDUCTIVITY_BASE` | 0.5 | `config/physics.py` |
| `PUMP_CONVECTION_RATE` | 0.2 | `config/physics.py` |
| `PIPE_WATER_TRANSFER_RATE` | 0.5 | `config/physics.py` |

### Events Published

None — updates grid arrays in-place.

---

## 8. Mana Economy

**File:** `dungeon_core/mana.py`
**Algorithm:** Reservoir with generation, consumption, and per-block
capacitance

### 8.1 Core Reserve

The dungeon core generates `MANA_GENERATION_PER_TICK` (0.5) mana per
tick, capped at `max_mana`. Base capacity is `MANA_BASE_CAPACITY` (1000).

### 8.2 Consumption

- **Digs:** Each active dig costs `MANA_DIG_COST_PER_TICK` per tick.
- **Traps:** Each active trap costs its `MANA_UPKEEP_PER_SECOND` value,
  divided by 20 (ticks/sec). Costs are per trap type, defined in a LUT.

### 8.3 Per-Block Capacitance

Enchanted blocks store mana locally, tracked in `MANA_CAPACITANCE[vtype]`:

- **Active blocks:** Drain at `ENCHANTED_ACTIVE_DRAIN_PER_S`.
- **Inactive blocks:** Drain at `ENCHANTED_INACTIVE_DRAIN_PER_S` (slower).
- **Charging mode:** Block pulls mana from core reserve.
- **Draining mode:** Block dumps mana back to core (partial reclaim).

When a block's local mana reaches 0, it depowers and publishes
`block_capacitance_depleted`.

### 8.4 Soul Capture

When an intruder dies on claimed territory, `max_mana` increases by
`MANA_SOUL_CAPACITY_BONUS` (500). This rewards defensive play with
permanent mana growth.

### 8.5 Power State

Digs and traps are powered when `mana > 0` OR `generation >= total_costs`.
Power state changes publish `mana_power_changed`.

### Config

| Constant | Value | Source |
|----------|-------|--------|
| `MANA_BASE_CAPACITY` | 1000.0 | `config/economy.py` |
| `MANA_GENERATION_PER_TICK` | 0.5 | `config/economy.py` |
| `MANA_DIG_COST_PER_TICK` | 1.0 | `config/economy.py` |
| `MANA_SOUL_CAPACITY_BONUS` | 500.0 | `config/economy.py` |

### Events Published

| Event | Payload | When |
|-------|---------|------|
| `mana_changed` / `mana_amount_changed` | `mana, max_mana, digs_powered, traps_powered` | Mana level changed |
| `mana_power_changed` | `digs_powered, traps_powered` | Power state toggled |
| `block_capacitance_depleted` | `pos` | Enchanted block ran out of local mana |
| `soul_captured` | — | Intruder killed on claimed territory |
| `enchanted_block_state_changed` | `pos, mana, max_mana, active, charge_mode` | Block mana state update |

---

## Material Properties

**File:** `config/materials.py`

All physics systems look up material properties from LUT dicts keyed by
voxel type. Adding a new material means adding entries here — no system
code changes.

| Property | Type | Used By |
|----------|------|---------|
| `WEIGHT` | float | Gravity (impact), structural (load) |
| `CAPACITY` (max load) | float | Structural (compressive failure) |
| `STIFFNESS` | float | Structural (load attraction) |
| `TENSILE_STRENGTH` | float | Structural (cantilever), thermal stress |
| `SHEAR_STRENGTH` | float | Structural (lateral), water pressure |
| `POROSITY` | float | Humidity diffusion, water seepage, structural humidity weakness |
| `CONDUCTIVITY` | float | Temperature diffusion |
| `CTE` | float | Thermal stress (expansion coefficient) |
| `SHOCK_TRANSMISSIVITY` | float | Gravity (shock wave propagation) |
| `BRITTLENESS` | float | Gravity (shatter vs. crack on impact) |
| `DIG_DURATION` | int | Building (player dig time), future mole dig time |

### Notable Materials

| Material | Key Trait |
|----------|-----------|
| Obsidian | Extreme CTE (0.025), high brittleness (0.95) — shatters under thermal shock |
| Chalk | Soft, porous (0.6), high CTE — weak but permeable |
| Granite/Basalt | Dense, strong baseline rock |
| Reinforced Wall | Strongest buildable (capacity 900, stiffness 20) |
| Iron/Copper/Gold ingots | High stiffness, good tensile, ductile (low brittleness) |

---

## Design Principles

1. **Conservation:** Heat, humidity, water flow, and load distribution
   all conserve quantity (sum = 0 or bounded).
2. **CFL stability:** All diffusion systems satisfy CFL < 1.0 to prevent
   numerical divergence.
3. **Per-tick caps:** `MAX_CASCADE_PER_TICK` (64) prevents runaway in a
   single frame.
4. **LUT-based:** Material properties are lookups, never hardcoded.
   Adding a material = adding LUT entries, not modifying system code.
5. **Event-driven output:** Physics systems publish events for UI and
   logging; they never import rendering code.
6. **Vectorized NumPy:** All computations use array operations, not
   Python loops (except BFS network rebuilds in pipe.py).
