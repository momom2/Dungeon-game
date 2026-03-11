# Hero Dramatic Pathing

## Problem Statement

Heroes are the game's boss-fight encounter: rare, extremely powerful
intruders (250 HP, 20 damage, 15% luck dodge) who never retreat.
Currently they use the same A* pathfinding as every other archetype,
finding the shortest or cheapest route to the core. This makes them
efficient but unremarkable -- a Hero sneaking through a side tunnel
feels wrong narratively and wastes the archetype's design as a
spectacle the player prepares for.

The Hero should prefer **dramatic routes**: wide corridors, the main
hallway, straight through the gauntlet the player has built. This
predictability is not a flaw -- it IS the counterplay. A Hero is nearly
unkillable in a fair fight, so the player's advantage is *knowing where
the Hero will go* and stacking overwhelming environmental punishment
along that path.

## Design Goals

1. Heroes visibly prefer grand, open, trap-laden routes over cramped
   shortcuts.
2. The preference is strong enough to be legible to the player but not
   absolute -- a fully walled-off dramatic route still forces a detour.
3. Players learn the pattern and exploit it: building a "kill corridor"
   that looks inviting to the Hero while concentrating lethal force.
4. The system integrates with the existing `PersonalPathfinder` cost
   model, not as a separate pathfinder.
5. No impact on non-dramatic archetypes.

## Mechanical Definition of "Dramatic"

A route is dramatic when it passes through cells that are **wide, open,
and eventful**. Three independent signals contribute to a cell's
dramatic appeal:

### Signal 1: Corridor Width (Openness)

A cell's openness is the count of orthogonal neighbors (6-connected:
+/-x, +/-y, +/-z) in the intruder's PersonalMap that are traversable
(air, slopes, stairs, doors, traps -- anything a Hero could walk
through). Values range from 0 (entombed) to 6 (open room).

- Openness >= 4: "grand" -- the Hero is drawn here. Apply a cost
  **discount**.
- Openness 2-3: "corridor" -- neutral, no modifier.
- Openness 0-1: "cramped" -- the Hero finds this undignified. Apply a
  cost **penalty**.

This is computed from the PersonalMap at pathfinding time, using only
revealed cells. The Hero cannot be lured into openness it hasn't seen.

### Signal 2: Hazard Density (Eventfulness)

Where cunning intruders *add* cost for known hazards (via
`HAZARD_PATH_COST * cunning`), the Hero does the opposite: known
hazards along a route make it **more** attractive. The Hero charges
through traps because that is what Heroes do.

For dramatic intruders, each known hazard in a cell applies a cost
**discount** rather than a penalty. The Hero with `cunning = 0.1`
already barely avoids hazards, but dramatic pathing goes further:
hazards become an active lure.

### Signal 3: Depth Alignment (Directionality)

Heroes prefer routes that drive straight toward the core rather than
zig-zagging laterally. A cell that is closer to the core along the
primary axis of approach (z-depth in a vertical dungeon) is slightly
preferred over one at the same distance but offset laterally. This
creates the classic "Hero marching straight down the main shaft" feel.

This is expressed as a small heuristic bias: the h(n) estimate is
reduced for cells whose z-coordinate is closer to the goal's z.
Mechanically, this is a weighted directional component added to the
existing Manhattan distance heuristic.

## Integration with the A* Cost System

All three signals are implemented as **cost modifiers** inside the
existing `_move_cost` function, gated on `archetype.dramatic`. No
separate pathfinder, no separate neighbor expansion. The Hero uses
`_find_path_standard` like most other archetypes.

### Modified `_move_cost` (pseudocode)

```
After computing the base cost for a traversable cell:

if archetype.dramatic:
    # Signal 1: Openness
    openness = count_traversable_neighbors(personal_map, pos)
    if openness >= DRAMATIC_WIDE_THRESHOLD:
        cost *= DRAMATIC_WIDE_DISCOUNT      # e.g., 0.3 (strong pull)
    elif openness <= DRAMATIC_CRAMPED_THRESHOLD:
        cost += DRAMATIC_CRAMPED_PENALTY     # e.g., +8.0

    # Signal 2: Hazard lure (replaces cunning penalty)
    if pos in personal_map.hazards:
        cost *= DRAMATIC_HAZARD_DISCOUNT     # e.g., 0.5 (traps attract)

    # Signal 3 is applied to the heuristic, not move_cost
```

### Modified `_heuristic` (pseudocode)

```
base = manhattan(a, b)

if dramatic:
    # Prefer cells aligned with the goal on the depth axis
    lateral_offset = abs(a[0] - b[0]) + abs(a[1] - b[1])
    depth_progress = abs(a[2] - b[2])
    # Slightly deflate heuristic for cells with more depth
    # progress relative to lateral offset
    base -= DRAMATIC_DEPTH_BIAS * (depth_progress / (lateral_offset + 1))

return base
```

The heuristic modification must remain admissible (never overestimate
the true cost) for A* correctness. Since we only *subtract* from the
base Manhattan distance and the subtracted amount is bounded by
`DRAMATIC_DEPTH_BIAS` (a small constant, e.g. 0.5), the heuristic
remains admissible -- Manhattan distance already overestimates true
path cost in most dungeon layouts.

### Call-Site Changes

`PersonalPathfinder.find_path` already receives the full `archetype`.
No signature changes needed. The `_move_cost` function already receives
the archetype and can check `archetype.dramatic`. The heuristic
requires a small refactor: currently `_heuristic` is a pure
`(a, b) -> float` function with no archetype parameter. Two options:

- **Option A (preferred):** Pass `archetype` through to a new
  `_heuristic_dramatic` variant, selected at the top of
  `_find_path_standard` based on `archetype.dramatic`. The standard
  heuristic remains untouched.
- **Option B:** Add an optional `dramatic_bias` float parameter to
  `_heuristic`, defaulting to 0.0. Simpler but slightly less clean.

Either way, `_find_path_phase` is unaffected -- Heroes do not have
`phase_thickness`.

### Openness Calculation

The `count_traversable_neighbors` function is called once per neighbor
expansion during A*. For each candidate cell, it checks the 6
orthogonal neighbors in `personal_map.seen` and counts how many have a
voxel type in the traversable set (air, slope, stairs, doors, traps --
the same types `_move_cost` returns a non-None cost for). This is O(6)
per cell, negligible in the context of A* expansion.

**Caching:** If profiling shows this is hot, the openness value for
each cell can be cached on the PersonalMap (invalidated on reveal).
This is an optimization, not a design requirement.

## New Config Constants

All constants live in `config/intruders.py` under a `# -- Hero
Dramatic Pathing` section:

| Constant | Type | Proposed Value | Purpose |
|---|---|---|---|
| `DRAMATIC_WIDE_THRESHOLD` | `int` | `4` | Openness >= this = "grand" |
| `DRAMATIC_CRAMPED_THRESHOLD` | `int` | `1` | Openness <= this = "cramped" |
| `DRAMATIC_WIDE_DISCOUNT` | `float` | `0.3` | Cost multiplier for grand cells (lower = stronger pull) |
| `DRAMATIC_CRAMPED_PENALTY` | `float` | `8.0` | Additive cost for cramped cells |
| `DRAMATIC_HAZARD_DISCOUNT` | `float` | `0.5` | Cost multiplier for cells with known hazards |
| `DRAMATIC_DEPTH_BIAS` | `float` | `0.5` | Heuristic bias toward depth-aligned cells |

No new archetype stats are needed. The `dramatic` bool on
`ArchetypeStats` already exists and is the sole gate. If a future
archetype (e.g., a "Champion" variant) also needs dramatic pathing, it
only needs `dramatic=True`.

### Tuning Notes

- `DRAMATIC_WIDE_DISCOUNT` is the most impactful constant. At 0.3,
  a grand corridor cell costs 30% of its base, making it roughly 3x
  cheaper than a neutral cell. This creates a strong but not absolute
  preference -- a sufficiently long detour through wide corridors will
  still lose to a short narrow path.
- `DRAMATIC_CRAMPED_PENALTY` at 8.0 makes a 1-wide tunnel about as
  expensive as bashing through a door (15.0), pushing the Hero toward
  wider alternatives when available.
- `DRAMATIC_HAZARD_DISCOUNT` at 0.5 means hazards halve the cost,
  creating a moderate lure. Combined with openness discount, a wide
  trap-filled hall becomes extremely attractive.

## What `_tick_dramatic` Does

The existing `_tick_dramatic` stub in `decision.py` is not the right
place for pathfinding cost modification (that belongs in the
pathfinder). Instead, `_tick_dramatic` serves a complementary role:
**periodic repath forcing**.

Normal intruders cache their path and only repath when the map changes
or the path is exhausted. The Hero should repath more aggressively as it
discovers new cells, because newly revealed wide corridors might offer
a more dramatic route than the one currently being followed.

```
_tick_dramatic behavior:
  Every DRAMATIC_REPATH_INTERVAL ticks (e.g., 20):
    If the Hero has revealed new cells since last repath:
      Invalidate the path cache
      Trigger repath
```

This ensures the Hero dynamically shifts toward dramatic routes as its
PersonalMap fills in, rather than committing to the first path found
from spawn.

| Constant | Type | Proposed Value | Purpose |
|---|---|---|---|
| `DRAMATIC_REPATH_INTERVAL` | `int` | `20` | Ticks between dramatic repath checks |

## Edge Cases and Failure Modes

### 1. No Wide Routes Exist

If the entire dungeon is 1-wide tunnels, the openness signal produces
only penalties, never discounts. The Hero still finds a path -- the
cramped penalty inflates costs but doesn't make cells impassable. The
Hero takes the shortest cramped path, behaving like a normal intruder
but slightly slower (the penalty makes it prefer the least cramped
option among equals).

**Player implication:** A pure-narrow dungeon neutralizes the dramatic
preference but doesn't exploit it. The Hero is still extremely
dangerous.

### 2. Multiple Equally Dramatic Routes

When two wide, trap-filled corridors lead to the core, the A* cost
tiebreaker (insertion order in the heap) determines which one wins.
This is acceptable -- the Hero is not required to be deterministic
across runs, only to be *predictable in pattern*. The player knows the
Hero will take *a* wide corridor, not which one.

If precise determinism is desired later, a secondary tiebreaker (e.g.,
prefer lower x, then lower y) can be added to the heap tuple.

### 3. Player Removes Walls Mid-Path

If the player opens a wide room while the Hero is en route through a
narrow path, the Hero will not immediately switch. It will switch at
the next `_tick_dramatic` repath check (every 20 ticks = 1 second) if
the new room is revealed by the Hero's vision. This creates a small
reaction window -- the player can "bait" the Hero by opening a grand
corridor at the right moment.

### 4. Corridor Width Changes Along the Route

A path that starts wide but narrows is still preferred if the total
cost is lower than an alternative. The dramatic bias is per-cell, not
per-path -- there is no "path coherence" penalty for width changes.
This is intentional: a wide entrance funneling into a narrow kill zone
is a valid and intended player strategy.

### 5. Unrevealed Cells and Openness Counting

Openness only counts *revealed* neighbors. A cell next to the map edge
(unrevealed void) appears less open than it truly is. This means the
Hero's dramatic preference strengthens as it explores -- early in its
run, with limited vision, it paths more like a normal intruder. As it
reveals the dungeon layout, its preference for wide routes sharpens.

This is a desirable emergent behavior: the Hero "reads the room" as it
goes, committing to increasingly dramatic routes as it understands the
dungeon.

### 6. Hazard Discount Interacting with Cunning

The Hero has `cunning = 0.1`. The existing cunning hazard penalty is
`HAZARD_PATH_COST * cunning = 100.0 * 0.1 = 10.0`. The dramatic
hazard discount should *replace* the cunning penalty, not stack with
it. Implementation should check `archetype.dramatic` first and skip
the cunning penalty branch if true.

### 7. Performance

The openness check adds 6 dict lookups per neighbor expansion. In
the worst case (5000 iterations, 6 neighbors each), this is 180,000
extra dict lookups -- negligible in Python. Heroes are rare (one per
Hero's Retinue party, 5% party spawn weight), so this code path is
exercised infrequently.

## How Players Exploit This

The dramatic pathing system is designed to be the Hero's fatal flaw.
Here are the intended counterplay strategies:

### The Kill Corridor

Build one wide, inviting hallway from the entrance to the core. Line
it with every trap available: spikes, rolling stones, pressure plates
chained to floodgates, steam vents, fragile floors over lava. The Hero
will prefer this route over any narrow bypass. Stack enough damage to
overcome 250 HP and 15% dodge chance -- roughly 300+ raw damage worth
of traps to kill reliably.

### The Funnel

Build a wide entrance (4+ openness) that narrows into a kill zone.
The Hero commits to the wide section, and by the time it reaches the
narrow kill zone, backtracking to find an alternative is more expensive
than pushing through. The width change is per-cell, so the Hero does
not re-evaluate the whole path until the next repath tick.

### The Scenic Detour

Build two paths: a short, narrow tunnel to the core, and a long,
wide scenic route that loops through multiple trap rooms. The Hero
takes the scenic route because the openness discount outweighs the
extra distance (up to a point -- if the detour is absurdly long, raw
distance still wins). This buys time for the player's other defenses
to recharge.

### Bait-and-Switch

During the Hero's approach, open a wall to reveal a grand chamber
(via a player-activated mechanism or by placing/removing blocks). The
Hero's periodic repath detects the newly revealed wide space and
diverts toward it. The chamber is a trap -- sealed exits, lava floor,
collapsing ceiling.

### Retinue Separation

The Hero arrives with a retinue party. Other party members (Explorer,
Gloomwarden, etc.) have cunning > 0 and will avoid the trap-laden
dramatic route. This naturally splits the Hero from its support,
letting the player deal with each separately. The Hero's `loyalty =
1.0` prevents betrayal, but the retinue members may flee on morale
while the Hero charges ahead.

## Summary

Dramatic pathing transforms the Hero from "a really tough intruder"
into a genuine boss encounter with legible, exploitable behavior. The
implementation is surgically scoped: cost modifiers in `_move_cost`, a
heuristic variant, and a periodic repath in `_tick_dramatic`. No new
archetype fields, no new pathfinder class, no changes to non-dramatic
archetypes. Seven new config constants control the tuning, all
following the project's config-driven design principle.

The core design tension -- the Hero is nearly invincible but
predictable -- creates a satisfying puzzle: the player must build a
dungeon that *looks dramatic* while being lethal. The Hero cooperates
by walking into the spectacle.
