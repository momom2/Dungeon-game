# Intruder AI Decision Framework

Developer reference for the intruder AI system. Intruders spawn in
parties, navigate through fog-of-war, respond to hazards, and
coordinate through shared knowledge. The architecture uses three
decision layers: party-level coordination, per-intruder state machine,
and subsystem integration (vision, pathfinding, equipment, familiars).

> **Source files documented here.** Update this doc when changing:
>
> - `intruders/decision.py`
> - `intruders/agent.py`
> - `intruders/archetypes.py`
> - `intruders/party.py`
> - `intruders/state_handlers.py`
> - `intruders/hazard_response.py`
> - `intruders/vision.py`
> - `intruders/personal_map.py`
> - `intruders/personal_pathfinder.py`
> - `intruders/equipment.py`
> - `intruders/scroll_ai.py`
> - `intruders/familiar.py`
> - `intruders/sprite.py`
> - `intruders/spawning.py`
> - `intruders/interactions.py`
> - `intruders/knowledge_archive.py`
> - `intruders/reputation.py`
> - `config/intruders.py`

---

## The Complete Tick Loop

`IntruderAI._on_tick(tick)` runs every game tick. The full sequence:

```
1. SPAWNING
   If spawning enabled:
     Increment spawn timer
     If timer >= INTRUDER_PARTY_SPAWN_INTERVAL (400 ticks = 20 sec):
       If alive < MAX_INTRUDERS_TOTAL (24) AND parties < MAX_PARTIES (3):
         Spawn new party

2. PARTY UPDATES (for each non-wiped party)
   party.share_maps()      -- merge personal maps within range
   party.update_morale()   -- leader bonus, support aura, drift
   check_betrayals(party)  -- greed vs. loyalty vs. treasure proximity

3. PER-INTRUDER UPDATES (for each alive intruder)
   a. Vision update (if moved since last tick)
      - Compute LOS with effective perception
      - Compute arcane sight (Gloomwarden)
      - Compute thermal vision (fire immunity)
      - Apply morale penalty for newly discovered hazards

   b. Water interaction
      - Deep water damage (if column depth >= threshold)
      - Current push (if water velocity >= threshold)

   c. State-specific behavior
      SPAWNING    -> switch to ADVANCING, initial pathfind
      ADVANCING   -> move along path, check retreat, check core range
      INTERACTING -> countdown timer, execute on completion
      ATTACKING   -> countdown timer, deal core damage
      RETREATING  -> move toward surface, check supplies
      PILLAGING   -> seek and collect nearby treasures

   d. Supply consumption (food/water depletion)

   e. Equipment use
      - Auto-heal at 50% HP
      - Auto-sustenance when starving
      - Scroll AI (Shield > Teleport > Dispel > Reveal > Bridge)
      - Clean up depleted items

   f. Familiar orchestration (Mole Tamer only)
      - Update each mole's state machine
      - Every TAMER_COMMAND_INTERVAL: command moles (dig, recall)

   g. Eidolon entertainment (Eidolon only)
      - Decay entertainment
      - Summon sprites if cooldown expired
      - Update sprite state machines
      - Trigger boredom response (burst)

4. CLEANUP (every 100 ticks)
   Remove dead/escaped intruders
   Check for party wipes, update reputation
```

---

## State Machine

**File:** `intruders/agent.py` (IntruderState enum),
`intruders/state_handlers.py` (per-state update logic)

```
SPAWNING -----> ADVANCING -----> ATTACKING -----> (deal core damage)
                    |                                    |
                    +-----> INTERACTING -----> ADVANCING  (bash, dig, grab)
                    |
                    +-----> PILLAGING -----> ADVANCING    (collect treasures)
                    |
                    +-----> RETREATING -----> ESCAPED     (path to surface)

                    Any state + HP=0 -----> DEAD
```

### State Details

| State | Behavior | Transition Out |
|-------|----------|----------------|
| `SPAWNING` | Initial state at creation | Immediately to ADVANCING |
| `ADVANCING` | Move along path toward objective | ATTACKING (core in range), INTERACTING (block on path), RETREATING (low HP/supplies/morale), PILLAGING (greedy + treasure nearby) |
| `INTERACTING` | Timed action on a block (bash door, lockpick, dig, grab treasure) | ADVANCING (action complete) |
| `ATTACKING` | Deal damage to dungeon core every `attack_interval` ticks | DEAD (killed), RETREATING (low HP) |
| `RETREATING` | Path toward surface exit, check supplies | ESCAPED (reached surface), DEAD |
| `PILLAGING` | Search for and collect nearby treasures | ADVANCING (no more treasures or supplies critical) |
| `DEAD` | Terminal. Triggers reputation update, soul capture if on claimed territory | — |
| `ESCAPED` | Terminal. Archives personal map to knowledge archive | — |

### Retreat Trigger

An intruder retreats when any of:
- `HP < retreat_threshold * max_HP`
- Food or water below `SUPPLY_SAFETY_MARGIN` (1.3x estimated return cost)
- `morale < MORALE_RETREAT_MULTIPLIER * retreat_threshold`

---

## Archetypes

**File:** `intruders/archetypes.py`

Eight frozen dataclass constants define all intruder types. Individual
intruders reference their archetype — no per-instance duplication.

| Archetype | HP | Speed | Damage | Key Abilities | Objective Weights |
|-----------|-----|-------|--------|---------------|-------------------|
| Explorer | 35 | 3 | 3 | Perception 6, lockpick, high greed (0.7) | 0.1 / 0.5 / 0.4 |
| Inquisitor | 120 | 1 | 8 | Bash door, high loyalty (0.9), tanky | 0.9 / 0.0 / 0.1 |
| Gloomwarden | 60 | 2 | 4 | Arcane sight 3 (innate), loyalty 1.0 | 0.4 / 0.4 / 0.2 |
| Mole Tamer | 50 | 2 | 3 | Familiar capacity 3 (moles) | 0.6 / 0.3 / 0.1 |
| Eidolon | 75 | 2 | 5 | Flight, phase-walk (thickness 2), sprites | 0.0 / 0.7 / 0.3 |
| Alchemist | 55 | 2 | 4 | 5 inventory slots, potions | 0.3 / 0.3 / 0.4 |
| Cartomancer | 65 | 2 | 5 | Scrolls (count scales with status), arcane sight 1 | 0.2 / 0.6 / 0.2 |
| Hero | 100 | 2 | 10 | Dramatic (innate luck), never retreats | 0.8 / 0.1 / 0.1 |

Objective weights = (destroy core, explore, pillage). Used for party
objective voting.

### Status System

| Status | Rank | Trust Weight | Level Range |
|--------|------|-------------|-------------|
| GRUNT | 0 | 0.5 | 1-2 |
| VETERAN | 1 | 1.0 | 3 |
| ELITE | 2 | 1.5 | 4 |
| CHAMPION | 3 | 2.0 | 5 |

Level scaling: HP *= `1 + (level-1) * 0.15`, damage *= `1 + (level-1) * 0.10`.

---

## Party Coordination

**File:** `intruders/party.py`

### Party Templates (Weighted Selection)

| Template | Weight | Composition |
|----------|--------|-------------|
| Scouting Band | 30% | 2-3 Explorers, 0-1 Gloomwarden |
| War Party | 30% | 1-2 Inquisitors, 1-2 Gloomwardens, 0-1 Alchemist |
| Siege Company | 15% | 1 Mole Tamer, 1-2 Inquisitors, 0-1 Cartomancer |
| Arcane Expedition | 10% | 1-2 Cartomancers, 1 Alchemist, 0-1 Explorer |
| Hero's Retinue | 5% | 1 Hero, 2-3 (Inquisitor / Gloomwarden / Alchemist) |
| Eidolon Pair | 10% | 2 Eidolons (always in pairs) |

### Leader Election

Highest status wins. Ties broken by loyalty, then by intruder ID.

### Objective Voting

Each member's archetype `objective_weights` are summed and modified by
dungeon reputation. Leader breaks ties. Result determines party behavior
(DESTROY_CORE, EXPLORE, or PILLAGE).

### Map Sharing

Every `MAP_SHARE_INTERVAL` (10) ticks, alive members within
`MAP_SHARE_RANGE` (3 Chebyshev) merge their personal maps. The merge
tracks generation numbers to skip redundant copies.

### Morale System

Morale is a per-intruder float in [0.0, 1.0]. It affects move speed,
damage, and retreat decisions.

| Factor | Effect |
|--------|--------|
| Leader alive | +`MORALE_LEADER_BONUS` (0.001) / tick |
| Support aura (arcane sight member) | +`MORALE_SUPPORT_TICK` (0.002) / tick |
| Natural drift | Toward `MORALE_BASE` (0.7) at 0.001/tick |
| Ally death | -`MORALE_ALLY_DEATH_PENALTY` (0.15) |
| Damage taken | -`MORALE_DAMAGE_PENALTY` (0.03) |
| New hazard spotted | -`MORALE_HAZARD_PENALTY` (0.01) |
| Treasure collected | +`MORALE_TREASURE_BONUS` (0.1) |

Low morale: move interval *= `MORALE_SLOW_FACTOR` (1.5).
High morale: move interval *= `MORALE_FAST_FACTOR` (0.8), damage *= `MORALE_DAMAGE_BONUS` (1.2).

### Betrayal

Each tick, for each member adjacent to treasure:

```
chance = greed * (1 - effective_loyalty)
if RNG < chance: member betrays
```

Betrayer switches to PILLAGING and leaves the party. Party re-elects
leader and re-votes objective.

---

## Vision

**File:** `intruders/vision.py`

### Line of Sight

Bresenham 3D ray-casting from the intruder's position to all cells
within `effective_perception` range.

- **Transparent:** Air, slope, stairs, iron bars
- **State-dependent:** Doors, floodgates (open = transparent)
- **Opaque:** Stone, walls, all solid blocks
- **Water:** Blocks LOS after `WATER_LOS_DEPTH` (2) consecutive cells

### Arcane Sight

Gloomwarden innate ability (`arcane_sight_range = 3`). Sees through
walls within range. Reveals **true** voxel types — immune to deception
(gold baits appear as bait, not treasure).

### Thermal Vision

Granted by fire immunity equipment + `perception >= 4`. Reveals heat
signatures through walls.

### Vision Deception

- **Gold baits** appear as treasure to normal vision. Arcane sight sees
  the true type.
- **Fragile floors** appear as stone to normal vision.

### Dirty Flag Optimization

Vision is only recomputed when `_vision_dirty` is True (set on movement).
Stationary intruders skip the expensive ray-casting.

---

## Pathfinding

**File:** `intruders/personal_pathfinder.py`

A* operating exclusively on the intruder's personal map. Unrevealed
cells are impassable — intruders can only path through cells they've
seen.

### Movement Costs

| Cell Type | Cost |
|-----------|------|
| Walkable (air, slope, stairs) | 1.0 |
| Hazard (spike, tarp) | `HAZARD_PATH_COST` (100.0) |
| Lava-adjacent | `LAVA_ADJACENT_PATH_COST` (10.0) |
| Vertical movement | 1.5x multiplier |

### Phase-Walk (Eidolon)

Eidolons can phase through thin walls. The A* state is augmented to
`(x, y, z, walls_used)`:

- Wall counter increments for each solid cell entered.
- Resets to 0 when entering a walkable cell.
- Hard constraint: `walls_used <= phase_thickness` (default 2).
- Phase cost: 5.0 per wall cell (high but not prohibitive).
- Impassable even for phasing: reinforced wall, bedrock, core, water,
  iron bars.

Max iterations: `PERSONAL_PATHFINDER_MAX_ITERATIONS` (5000).

---

## Fog of War

**File:** `intruders/personal_map.py`

Sparse per-intruder map of "seen" cells. Only cells in this map are
available for pathfinding.

```python
seen: dict[(x,y,z) -> voxel_type]
hazards: set[(x,y,z)]       # spikes, lava, tarp, plates, vents, fragile
treasures: set[(x,y,z)]
doors: dict[(x,y,z) -> state]  # open/closed
baits: set[(x,y,z)]           # gold baits (arcane sight only)
alarms: set[(x,y,z)]
```

**Generation tracking:** `_generation` counter bumps on every
`reveal()` or `merge()`. Map sharing skips merges when the source
map's generation hasn't changed since the last merge.

---

## Equipment & Consumables

**File:** `intruders/equipment.py`

### Item System

Items are `ItemTemplate` instances with: category (POTION, SCROLL, TOOL,
GEAR), effect, charges (-1 = infinite), value, duration, and optional
gear slot.

### Pre-defined Items

| Category | Items |
|----------|-------|
| Potions | Heal, Fire Immunity, Water Breathing, Sustenance |
| Scrolls | Teleport, Bridge, Reveal, Dispel, Shield |
| Tools | Torch, Lockpick, Rope |
| Gear | Shields (3 types), Containers (Pouch, Bandolier, Backpack) |

### Loadout Generation

Each archetype has a `base_gear_loadout` key that maps to a loadout
table. Loadouts scale with level and status (higher = better gear).
Reputation feedback: deadly dungeons → more healing; rich dungeons →
more potions.

### Auto-Use (in `decision.py._tick_equipment_use`)

1. Heal if HP < 50%
2. Sustenance if food/water critical
3. Scroll AI (see below)
4. Remove depleted items

---

## Scroll AI

**File:** `intruders/scroll_ai.py`

Priority order: **Shield > Teleport > Dispel > Reveal > Bridge**.
Only one scroll consumed per tick.

| Scroll | Trigger | Cartomancer Difference |
|--------|---------|----------------------|
| Shield | HP < 30%, no active shield | Proactive: uses when hazard_density >= 2, HP < 50% |
| Teleport | HP < 30% and no retreat path | Uses when stuck with no path (forward teleport) |
| Dispel | Enchanted door/floodgate blocking path | Proactive in hazard areas |
| Reveal | < 60% of nearby cells revealed | Same threshold |
| Bridge | Gap/pit on path requiring dangerous fall | Same trigger |

---

## Block Interactions

**File:** `intruders/interactions.py`

Flag-based, not archetype-name checks. Each block type returns an
`InteractionResult`:

| Block | Result | Conditional |
|-------|--------|-------------|
| Door | INTERACT (bash or lockpick) | `can_bash_door` or `can_lockpick` |
| Spike | DAMAGE | Reduced by armor |
| Treasure | COLLECT | Grab and remove |
| Tarp | FALL + DAMAGE | Cunning-based detection |
| Reinforced Wall | REPATH | Unbreakable |
| Lava | DEATH or DAMAGE | DAMAGE if fire immune |
| Pressure Plate | INTERACT | Triggers adjacent traps |
| Fragile Floor | COLLAPSE + FALL | Weight-based |
| Enchanted Door | INTERACT or DAMAGE | Depends on mana power |
| Gold Bait | COLLECT (fake) | Same as treasure |

---

## Familiar Systems

### Mole Tamer — Moles

**File:** `intruders/familiar.py`

Lightweight digging entities. States: FOLLOWING, DIGGING, UNRULY, DEAD.

Tamer orchestration (every `TAMER_COMMAND_INTERVAL` = 10 ticks):
1. Recall moles drifting > `TAMER_MAX_FAMILIAR_DISTANCE` (8) away
2. Find dig targets on tamer's path (lookahead `TAMER_DIG_LOOKAHEAD` = 3)
3. Assign available FOLLOWING moles to unique targets

Unruliness increases by `FAMILIAR_UNRULINESS_PER_DIG` (0.1) per
completed dig. At `FAMILIAR_UNRULY_THRESHOLD` (0.7), the mole becomes
UNRULY (erratic, random digging).

### Eidolon — Sprites

**File:** `intruders/sprite.py`

Ethereal flying familiars. States: EXPLORING, SACRIFICING, BURSTING,
DISSIPATED, DEAD.

- **EXPLORING:** Inspect non-air blocks. Dissipate after
  `SPRITE_INSPECTION_LIMIT` (15) inspections.
- **SACRIFICING:** Move to unpowered enchanted block, inject mana,
  dissipate.
- **BURSTING:** On boredom trigger, all blocks in `SPRITE_BURST_RADIUS`
  (3) set loose. Gravity handles the collapse.

Entertainment decays at `EIDOLON_ENTERTAINMENT_DECAY` (0.002/tick).
Below `EIDOLON_BOREDOM_THRESHOLD` (0.3), eidolon orders sprites to
burst (unless partner is too close).

---

## Social Dynamics

### Knowledge Archive

**File:** `intruders/knowledge_archive.py`

Persistent faction intelligence. When an intruder escapes, their
personal map is archived (filtered by `map_memory` stat and status trust
weight). New parties receive this intel at spawn, skipping cells that
are:
- Stale (> `KNOWLEDGE_STALE_TICKS` = 4000 ticks old)
- Uncertain (> `KNOWLEDGE_UNCERTAIN_THRESHOLD` = 0.7)

Uncertainty increases on contradictions (+0.3) and player changes (+0.4),
decreases on confirmations (*0.5).

### Reputation

**File:** `intruders/reputation.py`

Tracks cumulative outcomes to shape future invasions:

```
lethality = kills / (kills + escapes)
richness = treasure_lost / (kills + treasure_lost)
```

| Profile | Threshold | Effect on Spawn |
|---------|-----------|-----------------|
| Deadly | lethality > 0.7 | Favor destroy objective, higher-level intruders, less loyal |
| Rich | richness > 0.4 | Favor pillage objective, less loyal (more greed) |
| Unknown | < 5 total outcomes | Favor explore objective |

---

## Spawning

**File:** `intruders/spawning.py`

### Level Assignment

```
LEVEL_WEIGHTS = (0.40, 0.30, 0.20, 0.08, 0.02)
```

40% level 1, 30% level 2, etc. Deadly dungeons shift weights toward
higher levels.

### Spawn Flow

1. Select party template (weighted RNG)
2. Generate composition from template
3. Find spawn position at surface edge
4. For each archetype in composition:
   - Assign level and status
   - Create personal map, inject knowledge archive
   - Generate equipment loadout
   - Create Intruder instance
   - Apply reputation loyalty modifier
   - Spawn familiars if applicable
5. Create Party, vote objective
6. Initial vision scan and pathfinding

---

## Hazard Response

**File:** `intruders/hazard_response.py`

Mixin handling environmental interactions:

- **Vision update:** LOS + arcane + thermal (dirty flag optimization)
- **Water damage:** Deep water hurts non-water-breathers
- **Water current:** Strong lateral water flow pushes intruders
- **Pressure plates:** Trigger adjacent explosive traps
- **Fragile floors:** Collapse under heavy intruders
- **Alarm bells:** Alert nearby parties (detection range + cooldown)
- **Betrayal checks:** Delegate to `party.check_betrayals()`

---

## Extensibility

Adding new content without touching core AI logic:

| Extension | What to Do |
|-----------|-----------|
| New archetype | Add `ArchetypeStats` constant in `archetypes.py` |
| New equipment | Add `ItemTemplate` + loadout table entry in `equipment.py` |
| New block interaction | Add `InteractionResult` case in `interactions.py` |
| New objective | Extend `IntruderObjective` enum + `objective_weights` in archetypes |
| New vision system | Add function in `vision.py`, call from `hazard_response.py` |
| New morale factor | Add calculation in `party.update_morale()` |
| New reputation metric | Extend `ReputationProfile`, subscribe to events |
| New scroll type | Add `ItemEffect` + handler in `scroll_ai.py` |
| New familiar behavior | Add state to `FamiliarState`, handle in `update_familiar()` |

All systems are config-driven: tuning difficulty and balance requires
only changing constants in `config/intruders.py`.
