# Familiar System Rework: Moles, Homunculi, Exhaustion, and Siege Operations

Design proposal for the two-archetype siege workflow. Mole Tamers
command moles that loosen blocks; Alchemists command homunculi that haul
blocks to the surface. A siege party requires both archetypes working in
concert.

**Terminology:** "Familiar" is the generic term for any sub-entity
attached to or summoned by a main intruder. Moles, Homunculi, and
Sprites are all familiar types. The existing `Familiar` class is renamed
to `Mole`.

---

## 1. Naming Rework

"Familiar" becomes the umbrella category. Each familiar kind gets its
own class: `Mole`, `Homunculus`, `Sprite`.

| Old name | New name | Scope |
|----------|----------|-------|
| `Familiar` class | `Mole` | `intruders/familiar.py` → `intruders/mole.py` |
| `FamiliarState` | `MoleState` | Same file |
| `spawn_familiars()` | `spawn_moles()` | Same file |
| `update_familiar()` | `update_mole()` | Same file |
| `recall_familiar()` | `recall_mole()` | Same file |
| `check_unruliness()` | `check_unruliness()` | Unchanged (mole-specific) |
| `intruder.familiars` | `intruder.moles` | `agent.py` slot (Mole Tamer) |
| — | `intruder.homunculi` | `agent.py` slot (Alchemist) |
| `FAMILIAR_HP` | `MOLE_HP` | `config/intruders.py` |
| `FAMILIAR_DIG_SPEED` | Removed → `MOLE_DIG_SPEED_MULTIPLIER` | config |
| `FAMILIAR_UNRULINESS_*` | `MOLE_UNRULINESS_*` | config |
| `FAMILIAR_UNRULY_THRESHOLD` | `MOLE_UNRULY_THRESHOLD` | config |
| `FAMILIAR_MOVE_INTERVAL` | `MOLE_MOVE_INTERVAL` | config |

The decision.py methods `_tick_familiars()` and `_command_familiars()`
keep their generic names because they now orchestrate ALL familiar types
across both Mole Tamers and Alchemists.

### Files touched by rename

- `intruders/familiar.py` → rename file to `intruders/mole.py`
- `intruders/agent.py` — slot `familiars` → `moles`; add `homunculi`
  slot
- `intruders/decision.py` — update imports and internal references
- `intruders/spawning.py` — `spawn_familiars` → `spawn_moles`; add
  `spawn_homunculi`
- `config/intruders.py` — rename all `FAMILIAR_*` → `MOLE_*`
- `tests/intruders/test_familiar.py` → rename to `test_mole.py`
- All test files importing from `familiar`
- Module docstrings throughout

---

## 2. Digging Rework

### 2.1 Material-Aware Dig Duration

Moles dig **~10× slower** than the player. This makes mole-dug blocks
an investment of time and familiar health, not a trivial bypass.

```
mole_dig_ticks = ceil(DIG_DURATION[voxel_type] * MOLE_DIG_SPEED_MULTIPLIER)
```

| Constant | Value | Notes |
|----------|-------|-------|
| `MOLE_DIG_SPEED_MULTIPLIER` | **10.0** | Moles take 10× the player's dig time. |

The old flat `FAMILIAR_DIG_SPEED = 8` is removed.

**Worked examples** (at 20 ticks/sec):

| Block | DIG_DURATION | Mole ticks | Real time |
|-------|-------------|------------|-----------|
| Dirt | 20 | 200 | 10 s |
| Stone | 40 | 400 | 20 s |
| Granite | 55 | 550 | 27.5 s |
| Obsidian | 100 | 1000 | 50 s |
| Marble | 50 | 500 | 25 s |

Adding a new block type only requires a `DIG_DURATION` entry — no mole
code changes.

### 2.2 Exhaustion vs. Dig Time — Natural Tier Gating

A single mole collapses (exhaustion 1.0) after ~333 continuous dig ticks
(`1.0 / MOLE_EXHAUSTION_PER_DIG_TICK`). This creates hard limits on what
a single unsupported mole can accomplish:

| Block | Mole ticks | Exhaustion | Single mole? |
|-------|-----------|------------|--------------|
| Dirt | 200 | 0.60 | Finishes, but tired |
| Stone | 400 | 1.20 | Collapses at 83% |
| Granite | 550 | 1.65 | Collapses at 61% |
| Obsidian | 1000 | 3.00 | Collapses at 33% |

**Anything beyond a single dirt block requires cycling** — the tamer
must recall tired moles and rotate fresh ones onto the same block. This
makes tamer status the primary determinant of siege capability (section
5).

### 2.3 Shared Dig Progress with Gradual Decay

Dig progress moves from per-mole storage to a **shared per-position
tracker** (`DigProgressTracker`) at the `IntruderAI` level. This enables
mole cycling: the tamer recalls one tired mole and sends another to
continue the same block.

```python
@dataclass
class DigProgressEntry:
    """Tracks cumulative dig progress at a world position."""
    __slots__ = ("progress", "max_ticks", "last_dig_tick")
    progress: int         # Accumulated dig ticks
    max_ticks: int        # DIG_DURATION[vtype] * multiplier
    last_dig_tick: int    # World tick when last actively dug
```

**Decay:** Each world tick, entries NOT actively dug this tick have
`progress` decremented by `DIG_PROGRESS_DECAY_RATE`. When progress
reaches 0, the entry is removed.

| Constant | Value | Notes |
|----------|-------|-------|
| `DIG_PROGRESS_DECAY_RATE` | **1** per tick | Block recovers 1 tick of progress per idle tick. |

With the 10× dig duration, the decay rate is small relative to dig
budgets (1/200 = 0.5% per idle tick for dirt, 0.1% for obsidian). The
primary cost of cycling is the exhaustion overhead, not progress loss.
But abandoned blocks do fully heal over time — a 400-tick stone block
decays in 400 idle ticks (20 seconds).

### 2.4 Dig Completion → Loose Block (not Air)

When a mole completes a dig, the block becomes **loose** rather than
being destroyed:

```python
voxel_grid.set_loose(tx, ty, tz, True)
```

The voxel retains its original type (stone, granite, dirt, etc.) but is
flagged loose. The existing `VoxelGrid.loose` infrastructure handles
everything:

- **Gravity:** Loose blocks fall through air (already in `gravity.py`).
- **Structural physics:** Loose blocks provide no support (already in
  `structural.py`).
- **Rendering:** Loose blocks are visually dimmed (already in
  `voxel_renderer.py`).
- **Save system:** The `loose` array is already serialized.
- **Pathfinding:** Loose blocks are still their original solid type, so
  they remain **impassable** until a homunculus hauls them away.

**No new voxel type is needed.** This mirrors the player's own
dig-and-pickup workflow (build_system.py already produces loose blocks on
dig completion).

### 2.5 Unruly Mole Dig-Shifting

Unruly moles dig at random targets. On each unruly tick, there is a
chance the mole **abandons its current dig target** and picks a new
adjacent block to dig instead.

```
p_shift = MOLE_UNRULY_DIG_SHIFT_CHANCE   (per dig tick while UNRULY)
```

| Constant | Value | Notes |
|----------|-------|-------|
| `MOLE_UNRULY_DIG_SHIFT_CHANCE` | **0.05** | 5% chance per tick to abandon and re-target. |

At 5% per tick, an unruly mole shifts every ~20 ticks on average. Since
even dirt takes 200 ticks, an unruly mole almost never completes a block
above soft soil. The scattered partial progress decays back to zero. This
makes unruly moles effectively useless for hard materials — the tamer
has lost a productive worker.

Unruly digs also produce loose blocks on the rare completion, not air.

---

## 3. Mole State Machine

### Current states (pre-rework)

```
FOLLOWING --> DIGGING --> FOLLOWING  (normal cycle)
                 |
                 v
              UNRULY  (terminal)
                 |
                 v
               DEAD
```

### Proposed states

```
FOLLOWING <--> DIGGING         (normal work cycle — digs set blocks LOOSE)
    |              |
    v              v
  RESTING       UNRULY -------> FERAL -------> DEAD
    |              ^               |
    v              |               v
 FOLLOWING     (tamer recall)   (re-taming) --> FOLLOWING (new owner)
```

| State | Description |
|-------|-------------|
| `FOLLOWING` | Trailing the tamer, awaiting orders. Exhaustion recovers at `MOLE_EXHAUSTION_RECOVERY_FOLLOWING` per tick. |
| `DIGGING` | Tunnelling at a target block. Exhaustion increases by `MOLE_EXHAUSTION_PER_DIG_TICK` per tick. Dig completion sets the block **loose** (not air). |
| `RESTING` | Stationary near the tamer, recovering exhaustion at `MOLE_EXHAUSTION_RECOVERY_RESTING` (5× faster). Cannot receive dig orders. Returns to FOLLOWING when exhaustion drops below `MOLE_REST_DONE_THRESHOLD`. |
| `UNRULY` | Lost control. Erratic movement, random dig-shifting (section 2.5). Gains exhaustion at `MOLE_EXHAUSTION_PER_UNRULY_TICK`. Can be recalled by CHAMPION tamers. |
| `FERAL` | No owner. Panicked wandering, burns energy fast at `MOLE_EXHAUSTION_PER_FERAL_TICK`. Can be re-tamed by nearby tamers (section 9). |
| `DEAD` | Terminal. Reached when HP = 0 or exhaustion = 1.0 (collapse). |

### State transitions

| From | To | Trigger |
|------|----|---------|
| FOLLOWING | DIGGING | `order_dig()` from tamer |
| FOLLOWING | RESTING | Exhaustion ≥ `MOLE_TIRED_THRESHOLD` and tamer issues rest (or auto-rest for experienced tamers, or spontaneous self-rest for low-obedience moles) |
| DIGGING | FOLLOWING | Dig complete, unruliness check passed |
| DIGGING | UNRULY | Unruliness check failed |
| DIGGING | DEAD | Exhaustion reaches 1.0 (collapse) |
| RESTING | FOLLOWING | Exhaustion drops below `MOLE_REST_DONE_THRESHOLD` |
| UNRULY | FOLLOWING | Tamer recall succeeds |
| UNRULY | FERAL | Tamer dies, or unruly for `MOLE_UNRULY_TO_FERAL_TICKS` |
| UNRULY | DEAD | Exhaustion reaches 1.0 |
| FERAL | FOLLOWING | Re-tamed by a nearby tamer |
| FERAL | DEAD | Exhaustion reaches 1.0, or HP reaches 0 |
| Any | DEAD | HP reaches 0 |

---

## 4. Mole Exhaustion

Exhaustion is a float in `[0.0, 1.0]` representing cumulative physical
strain. Unlike unruliness (psychological resistance), exhaustion is a
physiological resource that must be managed.

### 4.1 Accumulation

| Source | Rate | Notes |
|--------|------|-------|
| Per tick while DIGGING | `MOLE_EXHAUSTION_PER_DIG_TICK` = **0.003** | Primary drain. Collapse after 333 continuous ticks. |
| Per dig order received | `MOLE_EXHAUSTION_PER_ORDER` = **0.005** | Penalises rapid re-ordering. |
| Per tick while UNRULY | `MOLE_EXHAUSTION_PER_UNRULY_TICK` = **0.002** | Erratic movement is tiring. |
| Per tick while FERAL | `MOLE_EXHAUSTION_PER_FERAL_TICK` = **0.004** | Panicked moles burn fast. Primary death clock. |
| Rapid-order penalty | `MOLE_EXHAUSTION_RAPID_ORDER_PENALTY` = **0.01** | Applied when re-ordered within `MOLE_RAPID_ORDER_WINDOW` (5 ticks). |

With 10× dig durations, a fresh mole barely survives one dirt block (0.6
exhaustion). Anything harder requires cycling or the mole collapses.
A feral mole with zero exhaustion survives ~250 ticks (~12.5 seconds).

### 4.2 Recovery

| Condition | Rate | Notes |
|-----------|------|-------|
| While FOLLOWING | `MOLE_EXHAUSTION_RECOVERY_FOLLOWING` = **0.001** | Slow passive recovery. Full recovery from 0.5 takes 500 ticks (25 sec). |
| While RESTING | `MOLE_EXHAUSTION_RECOVERY_RESTING` = **0.005** | 5× faster. Full recovery from 0.5 in 100 ticks (5 sec). |

The 5× difference between FOLLOWING and RESTING recovery is the key
advantage of ELITE+ tamers — they issue explicit REST commands, getting
moles ready for the next dig much faster than passive FOLLOWING recovery.

### 4.3 Thresholds

| Threshold | Value | Effect |
|-----------|-------|--------|
| `MOLE_TIRED_THRESHOLD` | **0.5** | Dig speed penalty: `effective_ticks = base_ticks * (1 + 0.5 * exhaustion)`. Experienced tamers consider resting this mole. |
| `MOLE_REFUSAL_THRESHOLD` | **0.7** | May refuse orders. Probability = `(exhaustion - 0.7) / 0.3 * (1 - obedience)`. Obedient moles never refuse. |
| `MOLE_COLLAPSE_THRESHOLD` | **1.0** | Mole dies. No recovery possible. |

### 4.4 Obedience

Per-mole trait in `[0.0, 1.0]`, initialized from:

```
obedience = clamp(MOLE_BASE_OBEDIENCE + rng.gauss(0, MOLE_OBEDIENCE_SPREAD), 0.0, 1.0)
```

| Constant | Value | Notes |
|----------|-------|-------|
| `MOLE_BASE_OBEDIENCE` | **0.6** | Mean obedience. |
| `MOLE_OBEDIENCE_SPREAD` | **0.15** | Std dev. Most moles fall in [0.3, 0.9]. |

**High obedience (> 0.7):** Obeys even when exhausted past refusal
threshold. Won't self-rest — will collapse if tamer doesn't manage it.
Reliable but requires active management.

**Low obedience (< 0.4):** Readily refuses orders when tired.
Spontaneously enters RESTING when exhaustion > `MOLE_TIRED_THRESHOLD`.
Self-preserving but unpredictable.

**Spontaneous rest probability** (per command tick, when exhaustion >
`MOLE_TIRED_THRESHOLD`):

```
p_self_rest = (1 - obedience) * (exhaustion - MOLE_TIRED_THRESHOLD) / 0.5
```

Clamped to `[0.0, 0.5]`.

---

## 5. Tamer Mole Cycling

Cycling — recalling a tired mole and rotating a fresh one onto the same
block — is the core mechanic that determines siege capability. The
tamer's status controls whether and how intelligently cycling is
performed.

### 5.1 Status-Dependent Cycling Logic

**GRUNT (no cycling):** Sends any FOLLOWING mole to dig. Does not track
exhaustion. Does not recall digging moles. Moles dig until they finish
or collapse. For dirt, the mole barely survives. For stone and above,
moles collapse and progress depends on whether another mole is sent
before decay erases the work.

```python
# GRUNT: pick any idle mole, order to dig
for mole in moles:
    if mole.state == MoleState.FOLLOWING:
        order_dig(mole, target)
        break
```

**VETERAN (passive rotation):** Recalls moles at
`MOLE_REFUSAL_THRESHOLD` (0.7) — prevents collapse but leaves moles
very tired. Prefers sending the least-exhausted FOLLOWING mole. Does NOT
issue REST commands — moles recover passively at the slow FOLLOWING rate
(0.001/tick). This means long waits between cycling stints.

```python
# VETERAN: recall at 0.7, skip tired moles
for mole in moles:
    if mole.state == MoleState.DIGGING and mole.exhaustion >= 0.7:
        recall_mole(mole)
candidates = [m for m in moles if m.state == MoleState.FOLLOWING
              and m.exhaustion < MOLE_TIRED_THRESHOLD]
if candidates:
    best = min(candidates, key=lambda m: m.exhaustion)
    order_dig(best, target)
```

**ELITE (active rotation):** Recalls at `MOLE_TIRED_THRESHOLD` (0.5)
and immediately orders REST — moles recover at 5× speed. Actively sorts
moles by exhaustion, assigns least-exhausted to dig, rests the most-
exhausted. With 3 moles the typical pattern is: 1 digging, 1 resting,
1 following (ready to rotate in).

```python
# ELITE: recall at 0.5, issue REST, send freshest
for mole in moles:
    if mole.state == MoleState.DIGGING and mole.exhaustion >= 0.5:
        recall_mole(mole)
        order_rest(mole)
candidates = sorted(
    [m for m in moles if m.state == MoleState.FOLLOWING],
    key=lambda m: m.exhaustion
)
if candidates:
    order_dig(candidates[0], target)
```

**CHAMPION:** Same as ELITE, but rests obedient moles more aggressively
(threshold lowered by 0.1 for obedience > 0.7). Can recall UNRULY moles
with `TAMER_CHAMPION_RECALL_CHANCE` (**0.3**) probability.

### 5.2 Siege Capability by Status

| Status | Dirt | Stone | Granite | Obsidian |
|--------|------|-------|---------|----------|
| GRUNT | 1 block per mole | Collapses. 2 moles per block | Collapses. 2 moles | **Cannot finish** (3 moles insufficient) |
| VETERAN | Sustainable (slow) | Sustainable (slow recovery) | Sustainable | Sustainable (very slow) |
| ELITE | Efficient | Efficient rotation | Efficient rotation | Efficient rotation |
| CHAMPION | Efficient | Efficient | Efficient | Efficient + unruly recall |

**Key result:** GRUNT tamers physically cannot breach obsidian walls.
Three moles contribute 3 × 333 = 999 dig ticks, falling 1 tick short
of the 1000 required (plus decay losses during switches). This makes
obsidian a reliable defense against low-tier siege parties.

### 5.3 Command Frequency

```python
effective_interval = max(
    TAMER_COMMAND_INTERVAL_MIN,
    TAMER_COMMAND_INTERVAL - status_rank * TAMER_STATUS_INTERVAL_REDUCTION,
)
```

| Constant | Value |
|----------|-------|
| `TAMER_COMMAND_INTERVAL_MIN` | **6** ticks |
| `TAMER_STATUS_INTERVAL_REDUCTION` | **1** tick per rank |

GRUNT=10, VETERAN=9, ELITE=8, CHAMPION=7. Higher-status tamers also
issue fewer unnecessary orders — only when moles are idle, not
re-ordering in-progress digs.

---

## 6. Homunculus Familiar

Homunculi are alchemical constructs — **soulless** familiars commanded
by Alchemists. Their primary role is hauling loose blocks to the surface.
Their secondary role is triggering traps as a last resort during retreat.

### 6.1 Classification

`Homunculus` is a new class in `intruders/homunculus.py`, following the
Sprite pattern (each familiar kind = own class with own `__slots__`).

```python
class Homunculus:
    __slots__ = (
        "id", "owner_id",
        "x", "y", "z",
        "hp", "max_hp",
        "state",
        "carried_block",       # int (voxel type) or None
        "carried_from",        # (x,y,z) where block was picked up
        "path", "path_index",
        "ticks_since_move",
        "haul_target",         # (x,y,z) loose block to pick up
        "surface_exit",        # (x,y,z) target surface cell
        "trap_target",         # (x,y,z) trap to trigger
    )
```

Stored on the alchemist: `intruder.homunculi: list[Homunculus]`.

**Soulless implications:**
- No morale, no fleeing, no independent decisions.
- No personal map — uses the alchemist's map for all pathfinding.
- Follows orders mechanically until destroyed or the alchemist dies.
- Cannot be re-tamed — constructs, not creatures.
- Death has no morale impact on party members.

### 6.2 Homunculus Count by Alchemist Status

| Status | Homunculi |
|--------|-----------|
| GRUNT | 1 |
| VETERAN | 2 |
| ELITE | 3 |
| CHAMPION | 4 |

Formula: `HOMUNCULUS_BASE_COUNT + status_rank * HOMUNCULUS_STATUS_BONUS`.

| Constant | Value |
|----------|-------|
| `HOMUNCULUS_BASE_COUNT` | **1** |
| `HOMUNCULUS_STATUS_BONUS` | **1** per rank above GRUNT |

### 6.3 Homunculus Stats

| Stat | Value | Notes |
|------|-------|-------|
| `HOMUNCULUS_HP` | **25** | Expendable but not paper-thin. |
| `HOMUNCULUS_MOVE_INTERVAL` | **6** | Ticks between moves. Slower than most intruders. |
| `HOMUNCULUS_HAUL_SPEED_PENALTY` | **3** | Extra ticks per move while carrying. Effective interval = 9. |
| `HOMUNCULUS_PICKUP_TICKS` | **4** | Ticks to pick up a loose block. |
| `HOMUNCULUS_DISPOSE_TICKS` | **5** | Ticks to destroy block at surface. |
| `HOMUNCULUS_REPATH_INTERVAL` | **30** | Ticks between repath attempts while stuck. |

### 6.4 Pathfinding — Alchemist's Map

Homunculi do NOT maintain their own personal map. They are extensions of
the alchemist's will and use the **alchemist's personal map** for all
pathfinding queries. This means:

- An alchemist with better perception → homunculi have better navigation.
- If the alchemist's map is stale, all homunculi navigate on stale data.
- Map sharing within the party (from other members) indirectly benefits
  homunculi through the alchemist's updated map.

Homunculi use `PersonalPathfinder` with the alchemist's map reference.

### 6.5 Homunculus State Machine

```
                     +-----------+
                     | FOLLOWING |<-----------------------------+
                     +-----+-----+                              |
                           |                                    |
              (order: haul) |    (order: trigger trap)          |
                     +------+------+                            |
                     |             |                            |
               +-----v-------+  +-v--------------+             |
               | PICKING_UP  |  | TRIGGERING_TRAP|             |
               +-----+-------+  +-------+--------+             |
                     |                   |                      |
               (block acquired)    (trap effect applied)        |
                     |                   |                      |
               +-----v-----+      (survived?) ─── yes ─────────+
               |  HAULING  |                   └── no → DESTROYED
               +--+----+---+
                  |    |
     (reached     |    | (no path)
      surface)    |    |
                  |  +-v------+
                  |  | STUCK  | (notify alchemist, bag block)
                  |  +--------+
                  |
            +-----v--------+
            | DISPOSING    |
            +-----+--------+
                  |
            +-----v--------+
            | RETURNING    | (path back to alchemist)
            +-----+--------+
                  |
            (reached alchemist)────────────────────────────────+

           Alchemist dies → INERT (permanent)
           HP = 0 → DESTROYED (if carrying: block reappears)
```

| State | Description |
|-------|-------------|
| `FOLLOWING` | Trailing the alchemist. Default state. |
| `PICKING_UP` | Adjacent to loose block, spending `HOMUNCULUS_PICKUP_TICKS` ticks. |
| `HAULING` | Carrying a block, pathing to nearest surface exit. Movement slowed by `HOMUNCULUS_HAUL_SPEED_PENALTY`. |
| `STUCK` | Cannot path to surface while carrying. Notifies alchemist. Block is "bagged." Periodic repath every `HOMUNCULUS_REPATH_INTERVAL`. |
| `DISPOSING` | At surface cell. Spending `HOMUNCULUS_DISPOSE_TICKS` to destroy block. |
| `RETURNING` | Empty-handed, pathing back to alchemist's position. |
| `TRIGGERING_TRAP` | Moving toward a known trap cell. On arrival, takes the trap's effect. If HP > 0 after, transitions to FOLLOWING. |
| `INERT` | Alchemist is dead. Homunculus stops all movement and action. Permanent. |
| `DESTROYED` | Terminal. HP ≤ 0. If carrying: block reappears at death position. |

### 6.6 Block Carrying Mechanics

**Pickup:**
1. Homunculus moves adjacent to the loose block.
2. Spends `HOMUNCULUS_PICKUP_TICKS` ticks.
3. Stores: `h.carried_block = voxel_grid.get(x, y, z)`,
   `h.carried_from = (x, y, z)`.
4. Removes block: `voxel_grid.set(x, y, z, VOXEL_AIR)`. Cell is now
   passable.
5. Publishes `"block_picked_up"` event.

**Disposal at surface:**
1. Homunculus reaches a surface-level air cell.
2. Spends `HOMUNCULUS_DISPOSE_TICKS` ticks.
3. Clears: `h.carried_block = None`.
4. Publishes `"block_disposed"` event.
5. Transitions to RETURNING.

**Destroyed while carrying:**
1. Block reappears at the homunculus's death position:
   `voxel_grid.set(h.x, h.y, h.z, h.carried_block)`.
2. If that cell is occupied, scan 6-adjacent cells for air and place
   there. If no air cell, the block is lost.
3. Publishes `"homunculus_destroyed_carrying"` event.

This creates a tactical opportunity for the player: killing a carrying
homunculus plugs the tunnel back up.

**Stuck (can't path to surface):**
1. Pathfinding to surface returns None (e.g., bridge spell expired).
2. Homunculus enters STUCK state. Publishes `"homunculus_stuck"` event.
3. Block is "bagged": homunculus keeps carrying but cannot pick up
   another.
4. Periodic repath every `HOMUNCULUS_REPATH_INTERVAL` ticks. If path
   becomes available, homunculus resumes HAULING.

### 6.7 Trap Triggering (Last Resort)

The alchemist can order a homunculus to walk into a known trap cell to
clear it for the party's retreat. This is a **last resort** — it
sacrifices a hauler (and potentially the homunculus itself) to open an
escape route.

**When used:** The party is retreating and a trap blocks the only viable
escape path. The alchemist identifies the trap (via perception or map
data) and orders the nearest FOLLOWING homunculus to trigger it.

**Mechanics:**
1. Homunculus enters `TRIGGERING_TRAP` state, paths to the trap cell.
2. On arrival, the trap activates against the homunculus (existing hazard
   system handles damage/effects).
3. If the homunculus survives, it transitions back to FOLLOWING.
4. If destroyed, the trap is consumed and the path is clear.

Alchemist status affects trap-trigger intelligence:

| Status | Behavior |
|--------|----------|
| GRUNT | Never uses trap-triggering. Doesn't think of it. |
| VETERAN | Uses when party is retreating and the trap is the sole obstacle on the escape path. |
| ELITE | Same as VETERAN. Can identify traps earlier (uses party's combined perception). |
| CHAMPION | Can use preemptively when the party plans to pass through a trapped area, not only during retreat. |

---

## 7. Alchemist Command Logic

The alchemist manages homunculi independently from the tamer's mole
operations. Coordination between the two archetypes is **indirect** —
the loose blocks in the world are the shared interface.

### 7.1 Command Flow

1. **Scan for loose blocks** within `ALCHEMIST_LOOSE_SCAN_RANGE`.
   Identify loose blocks not already assigned to a homunculus.
2. **Assign FOLLOWING homunculi** to unassigned loose blocks, nearest
   first.
3. **Check for stuck homunculi** — re-attempt pathfinding periodically.
4. **Retreat trap check** — if party is fleeing and a trap blocks escape,
   consider ordering a homunculus to trigger it.

| Constant | Value |
|----------|-------|
| `ALCHEMIST_LOOSE_SCAN_RANGE` | **6** (Manhattan) |
| `ALCHEMIST_COMMAND_INTERVAL` | **8** ticks |

### 7.2 Status-Dependent Homunculus Intelligence

| Status | Hauling Behavior | Trap Trigger |
|--------|-----------------|--------------|
| GRUNT | Assigns nearest homunculus to nearest loose block. No optimization. | Never. |
| VETERAN | Avoids sending to blocks about to fall (air below → gravity handles). | On retreat, sole obstacle only. |
| ELITE | Prioritizes blocks on the party's planned path. Re-checks stuck homunculi. | Same as VETERAN, uses party perception. |
| CHAMPION | Optimal routing. Coordinates multiple homunculi to avoid congestion at narrow passages. | Can use preemptively. |

---

## 8. Death Cascades

### 8.1 Tamer Death → Mole Cascade

Gradual degradation with a re-taming window:

```
Tick 0:   Tamer dies. Moles enter "orphaned" state (internal flag).
Tick 1-N: Unruliness climbs at MOLE_ORPHAN_UNRULINESS_RATE per tick.
          FOLLOWING moles mill in place. DIGGING moles finish current dig.
Tick ~30: Unruliness crosses MOLE_UNRULY_THRESHOLD.
          Moles probabilistically transition to UNRULY.
Tick ~80: UNRULY for MOLE_UNRULY_TO_FERAL_TICKS → FERAL.
Tick ~330: Feral moles collapse from exhaustion.
```

| Constant | Value | Notes |
|----------|-------|-------|
| `MOLE_ORPHAN_UNRULINESS_RATE` | **0.015** / tick | ~47 ticks to reach unruly threshold from 0. |
| `MOLE_UNRULY_TO_FERAL_TICKS` | **50** ticks | Time in UNRULY before FERAL. |
| `MOLE_ORPHAN_EXHAUSTION_RATE` | **0.001** / tick | Orphaned stress adds to exhaustion. |

Orphaned moles are moved to `IntruderAI._orphaned_moles` and ticked
independently until they die or are re-tamed.

### 8.2 Alchemist Death → Homunculus Deactivation

Homunculi are soulless constructs. When their alchemist dies, they
**go inert immediately**. No gradual degradation, no autonomous escape —
they simply stop.

1. All homunculi transition to INERT state.
2. Carrying homunculi **drop their block** at their current position
   (same mechanic as death-while-carrying, but the homunculus is not
   destroyed — just frozen).
3. Publishes `"homunculus_inert"` event for each.
4. Inert homunculi remain in the world as obstacles. They can be
   destroyed by traps, hazards, or the player.

**Inert homunculi cannot be re-activated.** A different alchemist cannot
adopt them — each alchemist crafts their own homunculi.

Orphaned homunculi are moved to `IntruderAI._inert_homunculi` for
hazard/damage ticking only.

---

## 9. Re-Taming (Moles Only)

Feral moles are a resource: nearby tamers can adopt them, gaining extra
digging capacity mid-run. Homunculi cannot be re-tamed (constructs).

### 9.1 Conditions

All must be true:
1. Mole state is FERAL.
2. Tamer is alive and within `TAMER_RETAME_RANGE` (Manhattan).
3. Tamer has capacity: `len(alive_moles) < archetype.familiar_capacity`.
4. Cooldown elapsed: `TAMER_RETAME_COOLDOWN` ticks since last attempt.

| Constant | Value |
|----------|-------|
| `TAMER_RETAME_RANGE` | **5** (Manhattan) |
| `TAMER_RETAME_COOLDOWN` | **30** ticks |
| `TAMER_RETAME_DURATION` | **20** ticks (tamer is occupied) |

### 9.2 Success Probability

```
p_tame = TAMER_RETAME_BASE_CHANCE
       + TAMER_RETAME_STATUS_BONUS * status_rank
       - TAMER_RETAME_EXHAUSTION_PENALTY * mole.exhaustion
```

Clamped to `[0.05, 0.95]`.

| Constant | Value |
|----------|-------|
| `TAMER_RETAME_BASE_CHANCE` | **0.4** |
| `TAMER_RETAME_STATUS_BONUS` | **0.15** per rank |
| `TAMER_RETAME_EXHAUSTION_PENALTY` | **0.3** |

### 9.3 On Success

1. `mole.owner_id = new_tamer.id`
2. `mole.state = MoleState.FOLLOWING`
3. `mole.unruliness = MOLE_RETAME_UNRULINESS_RESET` (**0.3**)
4. Append to `new_tamer.moles`. Remove from `_orphaned_moles`.
5. Publish `"mole_tamed"` event.

### 9.4 On Failure

Tamer wasted `TAMER_RETAME_DURATION` ticks. Cooldown still applies.
Mole remains FERAL.

---

## 10. Siege Party Composition

Siege operations require **both** a Mole Tamer and an Alchemist in the
same party. The tamer's moles loosen blocks; the alchemist's homunculi
haul them away. Neither archetype can breach a wall alone.

### 10.1 Updated SIEGE_COMPANY Template

```python
SIEGE_COMPANY = PartyTemplate(
    name="Siege Company",
    weight=0.15,
    slots=[
        PartySlot(archetype_choices=["Mole Tamer"], min_count=1, max_count=1),
        PartySlot(archetype_choices=["Alchemist"], min_count=1, max_count=1),
        PartySlot(archetype_choices=["Inquisitor"], min_count=0, max_count=2),
        PartySlot(archetype_choices=["Cartomancer"], min_count=0, max_count=1),
    ],
)
```

Total: 2-5 members (was 2-4). The Alchemist replaces one Inquisitor
slot (min 0 instead of min 1).

### 10.2 Alchemist Archetype Change

The existing Alchemist archetype (`archetypes.py:227`) gains
`familiar_capacity` for homunculi:

```python
ALCHEMIST = ArchetypeStats(
    ...
    familiar_capacity=HOMUNCULUS_BASE_COUNT,  # was 0
    ...
)
```

Actual homunculus count scales with status (section 6.2), using
`familiar_capacity` as the base.

### 10.3 Indirect Coordination

The tamer and alchemist **do not communicate directly**. Their
cooperation emerges from shared world state:

1. Tamer orders mole to dig → block becomes **loose**.
2. Alchemist scans for loose blocks → orders homunculus to haul.
3. Homunculus clears the cell → mole can proceed to next block.

This fits the EventBus architecture: `"block_loosened"` events are
published, but the alchemist primarily works by scanning the voxel grid
for `is_loose()` cells within range. No direct import between tamer and
alchemist subsystems.

---

## 11. Events

| Event | Payload | When |
|-------|---------|------|
| `"mole_collapsed"` | `mole_id, owner_id, exhaustion, pos` | Exhaustion reaches 1.0. |
| `"mole_feral"` | `mole_id, former_owner_id, pos` | UNRULY → FERAL. |
| `"mole_tamed"` | `mole_id, old_owner_id, new_owner_id` | Re-taming success. |
| `"mole_resting"` | `mole_id, owner_id` | Mole enters RESTING. |
| `"mole_order_refused"` | `mole_id, owner_id, exhaustion` | Mole refuses dig order. |
| `"block_loosened"` | `x, y, z, voxel_type, mole_id` | Mole completes dig, block set loose. |
| `"block_picked_up"` | `x, y, z, voxel_type, homunculus_id` | Homunculus picks up loose block. |
| `"block_disposed"` | `voxel_type, homunculus_id` | Homunculus destroys block at surface. |
| `"homunculus_stuck"` | `homunculus_id, owner_id, x, y, z` | Cannot path to surface. |
| `"homunculus_destroyed_carrying"` | `homunculus_id, x, y, z, voxel_type` | Destroyed with block (block reappears). |
| `"homunculus_inert"` | `homunculus_id, owner_id` | Alchemist died, homunculus deactivated. |
| `"homunculus_triggered_trap"` | `homunculus_id, x, y, z, survived` | Homunculus triggered a trap. |

---

## 12. Config Constants (Consolidated)

```python
# ── Mole exhaustion ──────────────────────────────────────────────────

MOLE_EXHAUSTION_PER_DIG_TICK = 0.003
MOLE_EXHAUSTION_PER_ORDER = 0.005
MOLE_EXHAUSTION_PER_UNRULY_TICK = 0.002
MOLE_EXHAUSTION_PER_FERAL_TICK = 0.004
MOLE_EXHAUSTION_RAPID_ORDER_PENALTY = 0.01
MOLE_RAPID_ORDER_WINDOW = 5

MOLE_EXHAUSTION_RECOVERY_FOLLOWING = 0.001
MOLE_EXHAUSTION_RECOVERY_RESTING = 0.005

MOLE_TIRED_THRESHOLD = 0.5
MOLE_REFUSAL_THRESHOLD = 0.7
MOLE_COLLAPSE_THRESHOLD = 1.0
MOLE_REST_DONE_THRESHOLD = 0.2

# ── Mole obedience ──────────────────────────────────────────────────

MOLE_BASE_OBEDIENCE = 0.6
MOLE_OBEDIENCE_SPREAD = 0.15

# ── Mole tamer death / orphan cascade ───────────────────────────────

MOLE_ORPHAN_UNRULINESS_RATE = 0.015
MOLE_UNRULY_TO_FERAL_TICKS = 50
MOLE_ORPHAN_EXHAUSTION_RATE = 0.001

# ── Unruly dig-shifting ─────────────────────────────────────────────

MOLE_UNRULY_DIG_SHIFT_CHANCE = 0.05

# ── Re-taming ───────────────────────────────────────────────────────

TAMER_RETAME_RANGE = 5
TAMER_RETAME_COOLDOWN = 30
TAMER_RETAME_DURATION = 20
TAMER_RETAME_BASE_CHANCE = 0.4
TAMER_RETAME_STATUS_BONUS = 0.15
TAMER_RETAME_EXHAUSTION_PENALTY = 0.3
MOLE_RETAME_UNRULINESS_RESET = 0.3

# ── Experienced tamer tuning ────────────────────────────────────────

TAMER_COMMAND_INTERVAL_MIN = 6
TAMER_STATUS_INTERVAL_REDUCTION = 1
TAMER_CHAMPION_RECALL_CHANCE = 0.3

# ── Digging rework ──────────────────────────────────────────────────

MOLE_DIG_SPEED_MULTIPLIER = 10.0
DIG_PROGRESS_DECAY_RATE = 1

# ── Homunculus stats ─────────────────────────────────────────────────

HOMUNCULUS_BASE_COUNT = 1
HOMUNCULUS_STATUS_BONUS = 1
HOMUNCULUS_HP = 25
HOMUNCULUS_MOVE_INTERVAL = 6
HOMUNCULUS_HAUL_SPEED_PENALTY = 3
HOMUNCULUS_PICKUP_TICKS = 4
HOMUNCULUS_DISPOSE_TICKS = 5
HOMUNCULUS_REPATH_INTERVAL = 30

# ── Alchemist command ────────────────────────────────────────────────

ALCHEMIST_LOOSE_SCAN_RANGE = 6
ALCHEMIST_COMMAND_INTERVAL = 8
```

---

## 13. Impact on Existing Systems

### 13.1 `intruders/familiar.py` → `intruders/mole.py`

Rename class `Familiar` → `Mole`, `FamiliarState` → `MoleState`. All
functions renamed (`spawn_familiars` → `spawn_moles`, etc.). Add slots:
`exhaustion`, `obedience`, `owner_alive`, `unruly_ticks`,
`last_order_tick`, `retame_cooldown`. Add `RESTING` and `FERAL` states.
Dig completion changes from `voxel_grid.set(... VOXEL_AIR)` to
`voxel_grid.set_loose(...)`. Dig progress reads from the shared
`DigProgressTracker` instead of per-mole dict. Unruly digging includes
random target shifting (section 2.5) and produces loose blocks.
New functions: `order_rest()`, `_tick_resting()`, `_tick_feral()`,
`update_orphaned_mole()`, `attempt_retame()`.

### 13.2 NEW: `intruders/homunculus.py` (~250 lines)

`HomunculusState` enum, `Homunculus` class with `__slots__`,
`spawn_homunculi()`, `update_homunculus()`, `order_pickup()`,
`order_trigger_trap()`. Per-state tick handlers: `_tick_following`,
`_tick_picking_up`, `_tick_hauling`, `_tick_stuck`, `_tick_disposing`,
`_tick_returning`, `_tick_triggering_trap`. Simpler than mole.py — no
exhaustion, no obedience, no unruliness.

### 13.3 NEW: `intruders/dig_tracker.py` (~80 lines)

`DigProgressEntry` dataclass, `DigProgressTracker` class. Methods:
`add_progress(pos, voxel_type, tick)`, `tick_decay(current_tick)`,
`get_progress(pos)`, `remove(pos)`. Managed by `IntruderAI`.

### 13.4 `intruders/decision.py`

`_tick_familiars()` expanded to tick moles (for tamers) and homunculi
(for alchemists). Status-based command intervals for both. Tamer cycling
logic (section 5) in `_command_tamer_moles()`. Alchemist hauling logic
(section 7) in `_command_alchemist_homunculi()`. New methods:
`_tick_homunculi()`, `_manage_mole_cycling()`, `_scan_loose_blocks()`,
`_attempt_retame()`, `_check_trap_trigger()`. Death handling extended:
tamer death → orphan moles; alchemist death → deactivate homunculi.
`IntruderAI.__init__()` gains `_orphaned_moles`, `_inert_homunculi`,
`_dig_tracker`.

### 13.5 `intruders/agent.py`

Rename `familiars` slot → `moles` (Mole Tamer). Add `homunculi` slot
(Alchemist). Initialize both as empty lists.

### 13.6 `intruders/spawning.py`

`spawn_familiars()` → `spawn_moles()`. Add `spawn_homunculi()` (count
derived from alchemist status). Moles spawned for tamers, homunculi
spawned for alchemists, during party spawn.

### 13.7 `intruders/archetypes.py`

Alchemist archetype gains `familiar_capacity = HOMUNCULUS_BASE_COUNT`.

### 13.8 `intruders/party.py`

SIEGE_COMPANY template updated to require 1 Alchemist (section 10.1).

### 13.9 `config/intruders.py`

Rename all `FAMILIAR_*` → `MOLE_*`. Add all new constants (section 12).

### 13.10 `intruders/personal_pathfinder.py`

No changes. Loose blocks remain impassable (still their original solid
type in the voxel grid). The `loose` flag is transparent to the
pathfinder.

### 13.11 `core/save_system.py`

Serialize/deserialize mole exhaustion, obedience, owner_alive,
unruly_ticks. Serialize homunculi (simpler than moles — no exhaustion or
obedience). Serialize `DigProgressTracker` entries. Serialize orphaned
moles and inert homunculi. All new fields use `data.get()` defaults for
backward compatibility.

---

## 14. Worked Examples

### 14.1 GRUNT Tamer vs. Stone Wall (400 ticks)

```
Tick 0:    Tamer orders mole A to dig stone.
Tick 333:  A collapses (exhaustion 1.0). Progress: 333/400.
           "mole_collapsed" published. A is dead.
Tick 340:  Next command cycle. GRUNT tamer sends mole B (doesn't check
           exhaustion). Decay during gap: 7 ticks → progress 326.
Tick 340-414: B digs 74 ticks. Progress 400/400. Block → LOOSE.
              B exhaustion: 0.22 (fine).
           "block_loosened" published.
Total: ~414 ticks. Mole A lost. Block loosened but not cleared.
```

### 14.2 GRUNT Tamer vs. Obsidian Wall — FAILURE (1000 ticks)

```
Tick 0:    Mole A starts.
Tick 333:  A collapses. Progress: 333. Gap ~10 → 323.
Tick 343:  Mole B starts.
Tick 676:  B collapses. Progress: 323+333 = 656. Gap ~10 → 646.
Tick 686:  Mole C starts.
Tick 1019: C collapses. Progress: 646+333 = 979. All 3 moles dead.
           21 ticks short of completion. Progress decays to 0.
           OBSIDIAN HOLDS. Tamer has no moles left.
```

### 14.3 ELITE Tamer — 3-Mole Cycling on Obsidian (1000 ticks)

```
Tick 0:    Mole A starts digging. B, C following.
Tick 167:  A at tired threshold (0.5). ELITE recalls A, orders REST.
           Sends B. Switch: 3 ticks. Progress: 167 → 164.
Tick 334:  B at 0.5. Recalled, rested. Sends C. Progress: 331 → 328.
Tick 501:  C at 0.5. Recalled. A fully rested (rested 167+167=334 ticks
           @ 0.005 = 1.67, capped at 0.5→0). Send A. Progress: 495→492.
Tick 668:  A at 0.5 again. Send B (recovered). Progress: 659 → 656.
Tick 835:  B at 0.5. Send C (recovered). Progress: 823 → 820.
Tick 1002: C at 0.5. Send A. Progress: 987 → 984.
Tick 1000+: A digs 16 ticks. Progress: 1000. Block → LOOSE.

Total: ~1036 ticks. No moles lost. All recoverable.
Overhead: 3.6% over theoretical minimum. Excellent.
```

### 14.4 Two-Archetype Siege — Full Cycle

```
ELITE tamer (moles A/B/C) + VETERAN alchemist (homunculi H1/H2).

Tick 0-1036:  Tamer cycles moles through obsidian (example 14.3).
Tick 1036:    Block → LOOSE. "block_loosened" event.
Tick 1044:    Alchemist command cycle. Detects loose block. Orders H1.
Tick 1044-1060: H1 paths to loose block (few cells).
Tick 1060-1064: H1 picks up block (4 ticks). Cell → VOXEL_AIR.
                Tunnel is now passable. "block_picked_up".
Tick 1064+:   H1 begins HAULING to surface (move interval = 9).
              Meanwhile, tamer starts moles on the NEXT block.
Tick ~1200:   H1 reaches surface. Disposes (5 ticks). Returns.
              Second block is ~50% dug by now.

Throughput: One block loosened per ~1036 ticks. Homunculus round-trip
~160 ticks. With 2 homunculi, alchemist easily keeps up with 1 tamer.
```

### 14.5 Homunculus Destroyed While Carrying

```
Tick 40:   H1 at (5, 3, 8) carrying VOXEL_GRANITE.
           Steps on spike trap. Takes damage. HP → 0.
           H1 → DESTROYED.
           Block placed at (5, 3, 8): voxel_grid.set(5, 3, 8, VOXEL_GRANITE).
           "homunculus_destroyed_carrying" published.
           Tunnel is plugged again! Tamer must re-dig, alchemist re-haul.
```

### 14.6 Trap Triggering on Retreat

```
Party is retreating. Spike trap at (3, 2, 5) blocks the only escape.
VETERAN alchemist recognizes the situation.

Tick 0:    Alchemist orders H2 (FOLLOWING, not carrying) to trigger trap
           at (3, 2, 5). H2 → TRIGGERING_TRAP.
Tick 12:   H2 reaches trap cell. Spike activates. H2 takes 20 damage.
           H2 HP: 25 → 5. Survives!
           Trap consumed. Path clear. H2 → FOLLOWING.
           Party retreats through cleared cell.
```

### 14.7 Tamer Death — Mole Cascade, Alchemist Continues

```
Tick 0:    Tamer dies (spike trap). Alchemist alive.
           Moles X (DIGGING), Y (FOLLOWING).
           Homunculi H1 (HAULING), H2 (FOLLOWING).

           H1 and H2 are unaffected — alchemist is alive.
           H1 continues hauling its block normally.

           X finishes current dig → loose block. Then mills. Orphan unruliness.
           Y mills in place. Orphan unruliness.
Tick 47:   X → UNRULY. Random dig-shifting, accomplishes nothing.
Tick 80:   Y → UNRULY.
Tick 97:   X → FERAL. Available for re-taming.
Tick 130:  Y → FERAL.
           No tamer in party to re-tame. Feral moles wander and die.

           Alchemist's homunculi keep hauling any remaining loose blocks
           but no new ones are being created. Siege stalls.
```

### 14.8 Alchemist Death — Homunculi Go Inert

```
Tick 0:    Alchemist dies. Tamer alive.
           H1 (HAULING granite), H2 (FOLLOWING).

           H1 → INERT. Drops granite at current position.
                 voxel_grid.set(h1.x, h1.y, h1.z, VOXEL_GRANITE).
           H2 → INERT. Stops moving.

           Tamer's moles can still dig → blocks become loose.
           But no homunculi to haul them away. Loose blocks pile up,
           blocking the tunnel. Siege stalls.

           Inert homunculi remain as physical obstacles until destroyed.
```

---

## 15. Testing Strategy

### `tests/intruders/test_mole.py` (renamed from `test_familiar.py`)

All existing tests updated for `Mole`/`MoleState` naming.

### NEW: `tests/intruders/test_mole_exhaustion.py`

| Test | Verifies |
|------|----------|
| `test_exhaustion_increases_while_digging` | Per-tick accumulation at `MOLE_EXHAUSTION_PER_DIG_TICK`. |
| `test_exhaustion_per_order` | Order cost applied on `order_dig()`. |
| `test_rapid_order_penalty` | Extra penalty for orders within `MOLE_RAPID_ORDER_WINDOW`. |
| `test_recovery_following` | Slow recovery while FOLLOWING. |
| `test_recovery_resting` | 5× faster recovery while RESTING. |
| `test_collapse_at_max` | Mole dies at exhaustion 1.0. Event published. |
| `test_tired_dig_speed_penalty` | Material-aware dig takes longer when tired. |
| `test_refusal_based_on_obedience` | Obedient mole never refuses; disobedient mole does. |
| `test_obedient_collapses_without_rest` | GRUNT tamer pushes obedient mole to death. |
| `test_disobedient_self_rests` | Low-obedience mole spontaneously rests. |
| `test_resting_exits_at_threshold` | Mole returns to FOLLOWING at `MOLE_REST_DONE_THRESHOLD`. |

### NEW: `tests/intruders/test_mole_tamer_death.py`

| Test | Verifies |
|------|----------|
| `test_orphan_unruliness_climb` | Unruliness increases at orphan rate. |
| `test_following_to_unruly_on_death` | Orphaned mole → UNRULY. |
| `test_unruly_to_feral` | UNRULY mole → FERAL after timer. |
| `test_feral_exhaustion_death` | Feral mole collapses. |
| `test_orphaned_still_tick` | Moles continue updating after tamer death. |
| `test_full_cascade_timeline` | End-to-end timing matches config. |

### NEW: `tests/intruders/test_mole_retaming.py`

| Test | Verifies |
|------|----------|
| `test_requires_feral_state` | Only FERAL moles can be re-tamed. |
| `test_requires_capacity` | Full tamer cannot adopt. |
| `test_requires_range` | Too far → cannot re-tame. |
| `test_cooldown` | Cannot attempt during cooldown. |
| `test_success_probability` | Matches formula (status + exhaustion). |
| `test_success_state_reset` | Owner updated, state FOLLOWING, unruliness reset. |
| `test_failure_no_change` | Mole remains FERAL on failure. |

### NEW: `tests/intruders/test_homunculus.py`

| Test | Verifies |
|------|----------|
| `test_spawn_count_by_status` | GRUNT=1, VETERAN=2, ELITE=3, CHAMPION=4. |
| `test_follows_alchemist` | FOLLOWING homunculus moves toward alchemist. |
| `test_pickup_loose_block` | Ordered to loose block; picks up; cell becomes air. |
| `test_haul_to_surface` | Carries block to surface, disposes. |
| `test_stuck_no_path` | Cannot reach surface → STUCK, notifies alchemist. |
| `test_stuck_repath_success` | Stuck homunculus finds new path, resumes hauling. |
| `test_destroyed_while_carrying` | Block reappears at death position. |
| `test_destroyed_occupied_cell` | Block placed in adjacent air cell. |
| `test_alchemist_death_inert` | All homunculi go INERT. Carrying one drops block. |
| `test_inert_not_retameable` | Another alchemist cannot adopt inert homunculi. |
| `test_uses_alchemist_map` | Homunculus pathfinds using alchemist's personal map. |
| `test_trap_trigger_survives` | Orders to trigger trap. Takes damage. Survives → FOLLOWING. |
| `test_trap_trigger_destroyed` | Triggers trap. HP → 0 → DESTROYED. Trap consumed. |

### NEW: `tests/intruders/test_dig_progress_decay.py`

| Test | Verifies |
|------|----------|
| `test_progress_accumulates` | Progress increments each dig tick. |
| `test_material_aware_10x` | Dirt (200 ticks) faster than granite (550). |
| `test_completion_sets_loose` | Block flagged loose on completion. |
| `test_decays_when_idle` | Progress decrements per idle tick. |
| `test_removed_at_zero` | Entry cleaned up at 0 progress. |
| `test_cycling_preserves_partial` | Second mole benefits from first's work. |
| `test_long_idle_resets` | Block fully heals if idle long enough. |
| `test_unruly_shift_loses_progress` | Shifting target abandons old block. |

### NEW: `tests/intruders/test_tamer_cycling.py`

| Test | Verifies |
|------|----------|
| `test_grunt_no_cycling` | GRUNT tamer doesn't recall digging moles. |
| `test_grunt_cannot_dig_obsidian` | 3 moles collapse, block incomplete. |
| `test_veteran_recalls_at_refusal` | VETERAN recalls at 0.7 exhaustion. |
| `test_veteran_sends_freshest` | VETERAN picks least-exhausted mole. |
| `test_elite_recalls_at_tired` | ELITE recalls at 0.5, issues REST. |
| `test_elite_rest_rotation` | ELITE rotates dig/rest assignments. |
| `test_elite_obsidian_no_deaths` | ELITE cycles through obsidian, no mole loss. |
| `test_champion_aggressive_rest` | CHAMPION lowers threshold for obedient moles. |
| `test_champion_recalls_unruly` | CHAMPION can recall UNRULY moles. |

### Extended: `tests/intruders/test_tamer_commanding.py`

| Test | Verifies |
|------|----------|
| `test_alchemist_assigns_homunculus_to_loose` | Loose block detected → homunculus ordered. |
| `test_elite_alchemist_prioritizes_path_blocks` | ELITE alchemist clears path blocks first. |
| `test_full_siege_cycle` | Mole digs → loose → homunculus hauls → air. End-to-end. |
| `test_two_archetype_coordination` | Tamer + alchemist cooperate through loose blocks. |

---

## 16. Migration and Backward Compatibility

- **Save format:** All new fields use `data.get()` defaults. Old saves
  load with zero exhaustion, default obedience, `owner_alive=True`,
  empty homunculus lists, no dig tracker entries.
- **Existing tests:** The naming rename requires updating imports. The
  only behavioral change is that completed digs produce loose blocks
  instead of air — tests checking `VOXEL_AIR` after a dig must check
  `is_loose()` instead.
- **Alchemist archetype:** Adding `familiar_capacity` is backward
  compatible — old saves with alchemists simply have no homunculi until
  they respawn.
- **Party template:** SIEGE_COMPANY now requires an alchemist. Old
  parties without an alchemist still function (moles can loosen blocks
  but nobody hauls them → tunnel fills with loose blocks).
- **Performance:** `DigProgressTracker` iterates active entries each
  tick. With max ~9 dig sites (3 tamers × 3 moles), negligible.
  Homunculi add ~4 entities per alchemist with simple pathfinding
  throttled to command intervals. No per-homunculus personal map (they
  share the alchemist's), saving memory.
