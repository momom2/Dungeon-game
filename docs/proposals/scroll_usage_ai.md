# Scroll Usage AI -- Design Proposal

## Status

**Proposed** -- pending implementation.

## Summary

Intruders carry single-use scroll items (TELEPORT, BRIDGE, REVEAL, DISPEL,
SHIELD) but the AI currently has no logic for deciding when or how to use
them.  This proposal defines the complete decision framework: trigger
conditions, target selection, stat-driven thresholds, cartomancer vs.
non-cartomancer behavior, world-modifying effects, config constants, player
counterplay, and edge-case handling.

---

## 1. Philosophy: When to Use vs. When to Save

Scrolls are the rarest consumable class.  A potion heals or protects for
one moment; a scroll can reshape the dungeon, teleport past an entire trap
gauntlet, or neutralize the player's best enchantment.  The AI must
respect this asymmetry.

**Core tension: utility vs. scarcity.**

Every scroll usage decision runs through two competing pressures:

1. **Perceived utility** -- how much value does using this scroll provide
   right now?  Measured as a **urgency score** (0.0--1.0) computed from
   the intruder's current situation.

2. **Hoarding impulse** -- how reluctant is the intruder to spend an
   irreplaceable resource?  Modeled as a **use threshold** that the
   urgency must exceed before the intruder will act.

The use threshold varies by archetype identity and situation:

| Factor | Effect on threshold |
|--------|---------------------|
| Cartomancer archetype | Threshold halved (scrolls are their specialty) |
| High `cunning` | Lower threshold (smarter = better timing) |
| High `risk_tolerance` | Lower threshold (willing to gamble) |
| Low `morale` | Lower threshold (panic overrides frugality) |
| Multiple scrolls of same type | Lower threshold per extra copy |
| RETREATING state | Threshold reduced by 30% (survival mode) |
| HP below 50% | Threshold reduced by 20% |

**The decision never fires on every tick.**  Scroll evaluation happens
inside `_tick_equipment_use`, gated by a per-intruder cooldown
(`_scroll_eval_cooldown`) decremented each tick.  Default evaluation
interval: every `SCROLL_EVAL_INTERVAL` ticks (proposed: 5).  This
prevents expensive per-tick scanning and creates a realistic "reaction
time" -- intruders do not instantly respond to threats.

---

## 2. Integration Point: `_tick_equipment_use`

The existing method handles HEAL and SUSTENANCE.  Scroll logic slots in
after those checks, before `remove_depleted()`.

```python
@staticmethod
def _tick_equipment_use(intruder: Intruder) -> None:
    # ... existing HEAL logic ...
    # ... existing SUSTENANCE logic ...

    # --- Scroll usage (new) ---
    _tick_scroll_use(intruder, context)

    # Clean up depleted items periodically
    intruder.equipment.remove_depleted()
```

Because scroll usage needs world context (voxel grid, path, nearby
hazards), `_tick_equipment_use` can no longer be `@staticmethod`.  It
must become a regular method on `IntruderAI` (or accept a context
object).  The recommended approach is a lightweight `ScrollContext`
dataclass passed into a standalone `_tick_scroll_use` function, keeping
the scroll logic in its own module (`intruders/scroll_usage.py`) to
respect the 600-line file-size target.

```python
@dataclass
class ScrollContext:
    """Read-only snapshot of world state needed for scroll decisions."""
    intruder: Intruder
    voxel_grid: VoxelGrid
    event_bus: EventBus
    rng: SeededRNG
    traps_powered: bool
    mana_system: ManaSystem | None
    core_pos: tuple[int, int, int]
```

---

## 3. Per-Scroll Trigger Conditions and Target Selection

### 3.1 TELEPORT

**What it does:** Instantly moves the intruder up to `SCROLL_TELEPORT_MAX_RANGE`
cells (currently 8) to a target air cell.  Two modes exist in the template
(`TeleportMode.DISTANCE` and `TeleportMode.DESTINATION`); for AI purposes we
always use DESTINATION mode -- the intruder picks a specific target cell.

**World effect:** The intruder's position changes.  No blocks are modified.
The intruder's vision is dirtied (triggers re-scan).  Publish
`"intruder_teleported"` event with old and new position.

**Trigger conditions (any one suffices):**

| Trigger | Urgency | Description |
|---------|---------|-------------|
| **Cornered** | 0.9 | No valid path exists AND intruder has taken damage in the last 10 ticks. Measured by: `intruder.path is None` and recent HP loss. |
| **Trap gauntlet ahead** | 0.5 | Next 3+ cells on current path contain known hazards. The scroll lets the intruder skip past the hazard cluster. |
| **Shortcut to goal** | 0.4 | Manhattan distance to goal through path > 2x Manhattan distance if teleported forward along path direction. Evaluated only when path length remaining > `SCROLL_TELEPORT_MAX_RANGE`. |
| **Retreat emergency** | 0.8 | State is RETREATING, HP below 30%, and distance to surface > teleport range (used to skip toward surface). |
| **Water/lava escape** | 0.95 | Currently standing in water with no water breathing, OR adjacent to lava with no fire immunity. Immediate survival. |

**Target selection algorithm:**

1. Collect all air cells within `SCROLL_TELEPORT_MAX_RANGE` Manhattan distance
   that are revealed on the intruder's personal map.
2. Filter out cells known to be hazards.
3. Score each candidate:
   - **Goal proximity bonus**: `1.0 - (dist_to_goal / max_possible_dist)`,
     weighted 0.6.
   - **Safety bonus**: `1.0` if no adjacent hazards known, `0.0` if 2+ adjacent
     hazards, weighted 0.3.
   - **Path continuity bonus**: `0.5` if the cell is on the intruder's current
     path (ahead of current index), weighted 0.1.
4. Select the highest-scoring candidate.  If tied, prefer the cell closest
   to the path goal.

**Failure modes:**
- No revealed air cells in range: scroll is not used (urgency is zeroed).
- All candidates are hazards: scroll is not used.
- Intruder is already adjacent to goal: TELEPORT provides no value; skip.

---

### 3.2 BRIDGE

**What it does:** Creates `value` (currently 3) temporary walkable air cells
in a line from a target position.  Bridge cells persist for
`SCROLL_BRIDGE_DURATION` ticks (currently 100), then revert to their
original voxel type.

**World effect:** Overwrites voxel types along the bridge line with
`VOXEL_AIR` (or a dedicated `VOXEL_BRIDGE` type if added later).  A
deferred timer reverts each cell after duration expires.  Publish
`"bridge_created"` event with positions and expiration tick.

Implementation detail: the bridge cells must be tracked in a
`_active_bridges` list on IntruderAI (or a standalone BridgeManager)
so they can be cleaned up.  Each entry stores `(positions, original_types,
expiration_tick)`.

**Trigger conditions:**

| Trigger | Urgency | Description |
|---------|---------|-------------|
| **Gap ahead** | 0.7 | Path is blocked because the next 1--3 cells on the desired path are non-air, non-walkable cells (empty gap, destroyed floor). The intruder's personal pathfinder returned REPATH and no alternate path exists within cost tolerance. |
| **Water crossing** | 0.6 | Path crosses water cells AND intruder has no water breathing. Bridge over the water instead of wading through. |
| **Lava crossing** | 0.95 | Path crosses lava cells AND intruder has no fire immunity AND cannot fly. Bridge is the only survival option. |
| **Collapsed floor bypass** | 0.5 | A fragile floor on the path has already collapsed (known hazard). Bridge restores passage. |

**Target selection algorithm:**

1. Identify the obstacle: the first non-passable cell on the path (or the
   first water/lava cell if the trigger is a fluid crossing).
2. Determine bridge direction: the normalized direction vector from the
   intruder's position toward the obstacle.
3. Place `value` bridge cells starting at the obstacle cell, extending
   in the bridge direction.
4. Validate: every bridge cell must be in-bounds.  If any cell would be
   out-of-bounds, truncate the bridge (minimum 1 cell placed to be
   useful).
5. Reject if the far end of the bridge is also impassable (bridging INTO
   a wall is useless).

**Failure modes:**
- Gap is wider than bridge length: scroll is not used (bridge would end
  mid-gap, providing no path).  Detected by checking if the cell at
  bridge_end + 1 is walkable.
- Target direction unclear (no path): fall back to direction toward goal.
- Bridge cells already air: no-op; scroll is not used.

---

### 3.3 REVEAL

**What it does:** Reveals all cells within `SCROLL_REVEAL_RADIUS` (currently 6)
around the intruder's current position on their personal map, bypassing
LOS requirements.

**World effect:** No blocks modified.  The intruder's personal map gains
entries for every in-bounds cell in the radius sphere.  Hazards, doors,
and treasures are recorded as if seen normally.  Vision deception still
applies (Gold Bait appears as Treasure, Fragile Floor as Stone) unless
the intruder has arcane sight.  Publish `"scroll_reveal_used"` event.

**Trigger conditions:**

| Trigger | Urgency | Description |
|---------|---------|-------------|
| **Fog ratio high** | 0.5 | Fewer than `SCROLL_REVEAL_FOG_THRESHOLD` fraction (proposed: 0.3) of cells within 2x perception range are revealed. The intruder is in deep unknown territory. |
| **No path found** | 0.7 | Pathfinder returned None and intruder has been pathless for `SCROLL_REVEAL_PATHLESS_TICKS` (proposed: 15) ticks. Revealing nearby cells may uncover a route. |
| **Entering new depth** | 0.3 | Intruder just descended to a new z-level never previously visited (first cell at this depth on personal map). Proactive scouting. |
| **Exploration objective** | 0.4 | Objective is EXPLORE and frontier cells are sparse (< 3 frontier cells visible). Reveal to find new frontiers. |

**Target selection:** Always centered on the intruder's current position.
No directional choice needed.

**Failure modes:**
- Most cells in radius are already revealed: urgency is scaled down by
  `(1.0 - revealed_fraction)`.  If revealed fraction > 0.8, urgency
  drops to near zero.
- Intruder is at surface level with full visibility: useless; skip.

---

### 3.4 DISPEL

**What it does:** Neutralizes all active enchanted traps within
`SCROLL_DISPEL_RADIUS` (currently 1) around a target cell.  "Neutralize"
means: drain the enchanted block's capacitance to zero and set it to
inactive.  For non-enchanted traps (spikes, pressure plates), DISPEL
retracts them (sets block_state to 0, i.e., deactivated).

**World effect:** Modifies enchanted block state via ManaSystem:
`mana_system.dispel_block(x, y, z)` sets capacitance to 0 and activated
to False.  For regular traps, sets `block_state` to 0 via voxel_grid.
Publish `"scroll_dispel_used"` event with center position and affected
block positions.

**Trigger conditions:**

| Trigger | Urgency | Description |
|---------|---------|-------------|
| **Enchanted door blocking path** | 0.8 | Next cell on path is a closed `VOXEL_ENCHANTED_DOOR` or `VOXEL_ENCHANTED_FLOODGATE` AND the intruder cannot bash or lockpick it. Dispel neutralizes the enchantment, effectively opening it. |
| **Known enchanted trap cluster** | 0.6 | 2+ enchanted hazard blocks (enchanted door, enchanted floodgate with block_state=1) within dispel radius of a cell on the upcoming path (next 5 cells). |
| **Active spike gauntlet** | 0.5 | 2+ extended spikes (`block_state == 1`) within dispel radius of a reachable cell on the path. Dispel retracts them. |
| **Pressure plate disarm** | 0.4 | A pressure plate on the upcoming path has been detected (via trap_detect_range or revealed on personal map). Dispel preemptively deactivates it. |
| **Alarm bell silence** | 0.3 | An alarm bell is on or adjacent to the path. Dispelling it prevents alerting the player. Lower urgency because alarm bells are inconvenient, not lethal. |

**Target selection algorithm:**

1. From the trigger, identify the "center of threat" -- the position of
   the most dangerous enchanted block, or the centroid of the hazard
   cluster.
2. Validate that at least one affected cell within `SCROLL_DISPEL_RADIUS`
   of the target actually contains an enchanted or active trap block.
3. If multiple valid centers exist (multiple clusters ahead), pick the one
   that maximizes the number of traps neutralized.

**Interaction with the enchanted block system:**

- Dispel drains capacitance to 0 and sets the block to inactive.  The
  player can recharge it, but this costs time and mana -- creating a
  window for the intruder party to pass through.
- If the enchanted block is already inactive or has 0 capacitance, dispel
  has no additional effect on it (but may still affect regular traps
  in the radius).
- Dispel does NOT destroy blocks.  The player's infrastructure remains
  intact.  This is an intentional balance decision: dispel is a temporary
  setback, not permanent destruction.

**Failure modes:**
- No enchanted or active trap blocks within radius of any reachable
  target: scroll is not used.
- Traps are not powered (global mana depleted and no capacitance):
  traps are already inactive; dispel is redundant; skip.
- DISPEL_RADIUS is only 1, so a spread-out trap layout defeats a single
  scroll.  This is by design -- dense trap placement is the player's
  counter to dispel.

---

### 3.5 SHIELD

**What it does:** Grants the intruder `value` (currently 30) shield HP
that absorbs damage before real HP.  Instant effect, no target needed.

**World effect:** Sets `intruder.shield_hp += scroll.template.value`.
No blocks modified.  Publish `"scroll_shield_used"` event.

**Trigger conditions:**

| Trigger | Urgency | Description |
|---------|---------|-------------|
| **Low HP** | 0.7 | HP below 40% of max AND no healing potions available. Shield is a substitute for healing. |
| **Entering known danger zone** | 0.5 | Next 3+ cells on path contain known hazards (spikes, lava-adjacent, steam vents). Pre-emptive shielding. |
| **About to engage core** | 0.3 | Within 5 cells of the dungeon core. Buffer for the attack phase where the intruder will be stationary and vulnerable to counter-attacks. |
| **Morale panic** | 0.6 | Morale below `MORALE_LOW_THRESHOLD` (0.3) and HP below 60%. Psychological comfort as much as mechanical benefit. |
| **No shield HP remaining** | +0.2 urgency bonus | If `intruder.shield_hp == 0`, add a flat bonus to any active trigger. Encourages refreshing expired shields. |

**Target selection:** Self-only.  No spatial targeting needed.

**Failure modes:**
- Shield HP already at or above the scroll's value: scroll is wasted;
  skip.  Only use when `intruder.shield_hp < scroll.template.value * 0.5`.
- Intruder is at full HP with no known threats ahead: urgency is near
  zero; hoarding wins.

---

## 4. Cunning and Risk Tolerance Influence

The two primary behavioral stats that shape scroll usage are `cunning`
and `risk_tolerance`.  They affect the system at three levels:

### 4.1 Use Threshold Calculation

```python
def compute_scroll_threshold(intruder: Intruder, is_cartomancer: bool) -> float:
    """Compute the urgency threshold an intruder must exceed to use a scroll."""
    base = SCROLL_BASE_USE_THRESHOLD  # proposed: 0.6

    # Cunning: smarter intruders use scrolls at better moments (lower threshold)
    cunning_mod = intruder.archetype.cunning * SCROLL_CUNNING_FACTOR  # proposed: -0.15

    # Risk tolerance: bold intruders spend resources more readily
    risk_mod = intruder.archetype.risk_tolerance * SCROLL_RISK_FACTOR  # proposed: -0.10

    # Morale: panicking intruders lower their standards
    if intruder.morale < MORALE_LOW_THRESHOLD:
        morale_mod = SCROLL_PANIC_THRESHOLD_REDUCTION  # proposed: -0.15
    else:
        morale_mod = 0.0

    # HP urgency
    hp_ratio = intruder.hp / intruder.max_hp if intruder.max_hp > 0 else 1.0
    hp_mod = SCROLL_LOW_HP_THRESHOLD_REDUCTION if hp_ratio < 0.5 else 0.0  # proposed: -0.10

    # Retreat urgency
    retreat_mod = SCROLL_RETREAT_THRESHOLD_REDUCTION if intruder.state == IntruderState.RETREATING else 0.0  # proposed: -0.15

    # Cartomancer: specialty halves effective threshold
    threshold = base + cunning_mod + risk_mod + morale_mod + hp_mod + retreat_mod
    if is_cartomancer:
        threshold *= SCROLL_CARTOMANCER_THRESHOLD_MULT  # proposed: 0.5

    return max(0.05, min(0.95, threshold))
```

### 4.2 Trigger Perception

High-cunning intruders detect scroll-worthy situations earlier:

- **Trap gauntlet lookahead**: Base is 3 cells ahead.  Cunning >= 0.6 extends
  to 5 cells.  Cunning >= 0.8 extends to 7 cells.
- **Enchanted block awareness**: Intruders with cunning < 0.4 do not
  proactively dispel -- they only react to enchanted doors that directly
  block their path (urgency trigger, not proactive).
- **Reveal timing**: Low-cunning intruders only use REVEAL when pathless.
  High-cunning intruders proactively reveal when fog ratio is high.

### 4.3 Target Quality

High-cunning intruders pick better teleport destinations:

- Cunning < 0.4: Teleport to the first valid air cell in the direction of
  the goal (greedy, no scoring).
- Cunning 0.4--0.7: Score candidates but only consider goal proximity and
  safety (2-factor scoring).
- Cunning >= 0.7: Full 3-factor scoring (goal proximity + safety + path
  continuity), as described in section 3.1.

Risk tolerance affects the safety weighting in target scoring:

- Low risk tolerance (< 0.3): Safety weight increases from 0.3 to 0.5.
  These intruders refuse to teleport near hazards.
- High risk tolerance (> 0.7): Safety weight decreases from 0.3 to 0.1.
  These intruders will teleport into semi-dangerous areas if it gets them
  closer to the goal.

---

## 5. Cartomancer vs. Non-Cartomancer Behavior

The difference is **quantity and willingness**, not capability.

### Cartomancer (scroll specialist)

- Starts with 2--5 scrolls (base 2 + status rank bonus).
- Use threshold is halved (see section 4.1).
- Evaluates scroll usage every `SCROLL_EVAL_INTERVAL` ticks (5).
- Will use scrolls proactively: REVEAL on entering a new floor,
  SHIELD before entering a danger zone, DISPEL preemptively on detected
  enchanted blocks.
- Treats scrolls as primary tools, not emergency reserves.
- When down to their last scroll, threshold increases by 0.15 (a small
  saving instinct, but still lower than non-cartomancers' base).

### Non-Cartomancer (scroll as rare windfall)

- Carries 0--1 scrolls (only Inquisitor veterans get a SHIELD scroll;
  others carry none by default).
- Use threshold is at full base value (0.6 before modifiers).
- Evaluates scroll usage every `SCROLL_EVAL_INTERVAL * 2` ticks (10).
  Slower reaction time -- scrolls are unfamiliar.
- Will only use scrolls reactively: cornered (TELEPORT), path completely
  blocked (BRIDGE), near death and no potions (SHIELD).
- Never uses REVEAL proactively -- only when pathless for 15+ ticks.
- Never uses DISPEL proactively -- only when an enchanted door directly
  blocks the path.
- Treats scrolls as last-resort emergency items.

### Behavioral summary table

| Behavior | Cartomancer | Non-Cartomancer |
|----------|-------------|-----------------|
| TELEPORT on trap gauntlet | Yes (urgency 0.5) | No (below threshold) |
| TELEPORT when cornered | Yes (urgency 0.9) | Yes (urgency 0.9) |
| BRIDGE over water | Yes (urgency 0.6) | Only if no alternate path |
| BRIDGE over lava | Yes (urgency 0.95) | Yes (urgency 0.95) |
| REVEAL proactively | Yes (fog ratio trigger) | No |
| REVEAL when pathless | Yes (urgency 0.7) | Yes after 15 ticks (urgency 0.7) |
| DISPEL proactively | Yes (cluster trigger) | No |
| DISPEL on blocking door | Yes (urgency 0.8) | Yes (urgency 0.8) |
| SHIELD before danger | Yes (urgency 0.5) | No (below threshold) |
| SHIELD at low HP | Yes (urgency 0.7) | Yes (urgency 0.7) |

---

## 6. What Scroll Effects Do in the Game World

Each scroll produces a concrete, observable change.  The player should
always be able to see what happened and understand why.

### TELEPORT
- Intruder vanishes from position A, appears at position B.
- Visual: particle effect at both endpoints (puff of smoke / arcane flash).
- Sound: distinctive "blink" sound cue.
- Event: `"intruder_teleported"` with `old_pos`, `new_pos`, `intruder`.
- The intruder's path is invalidated and repathed from the new position.
- Vision is dirtied (immediate re-scan from new location).

### BRIDGE
- 1--3 cells change from their current type to walkable (VOXEL_AIR or a
  new VOXEL_BRIDGE type).
- Original voxel types are stored; cells revert after `SCROLL_BRIDGE_DURATION`
  ticks.
- Visual: glowing translucent surface spanning the gap.
- Sound: crystalline formation sound.
- Event: `"bridge_created"` with positions, expiration tick, and creator
  intruder ID.
- Other intruders in the same party can also walk on the bridge.
- When the bridge expires, any intruder standing on a bridge cell that
  reverts to non-walkable (e.g., back to empty gap or water) takes fall
  damage or drowning damage as appropriate.

### REVEAL
- The intruder's personal map gains entries for all cells in a sphere of
  radius `SCROLL_REVEAL_RADIUS` around their position.
- Vision deception applies: Gold Bait still looks like Treasure, Fragile
  Floor still looks like Stone -- unless the intruder has arcane sight.
- Visual: expanding ring of light emanating from the intruder.
- Sound: soft chime / divination sound.
- Event: `"scroll_reveal_used"` with center position and radius.
- The intruder repathing after reveal may find previously unknown
  shortcuts or detect traps they can now avoid.

### DISPEL
- All enchanted blocks within `SCROLL_DISPEL_RADIUS` of the target:
  - Capacitance set to 0.
  - Activation set to False.
  - Block state set to 0 (open for doors/floodgates).
- All regular active traps within radius:
  - Spikes: block_state set to 0 (retracted).
  - Pressure plates: block_state set to 0 (reset).
  - Alarm bells: added to cooldown map with very long cooldown
    (`SCROLL_DISPEL_ALARM_SILENCE_TICKS`, proposed 200).
- Visual: dark pulse / anti-magic wave rippling outward from target.
- Sound: deep thrum / magical discharge.
- Event: `"scroll_dispel_used"` with target pos, affected positions,
  and block types neutralized.
- The player's enchanted blocks remain in place -- only their charge
  and activation are reset.  The player can recharge them.

### SHIELD
- `intruder.shield_hp` increases by the scroll's value (30).
- If the intruder already has shield HP (from gear), the scroll value
  stacks additively: `shield_hp += value`.
- Cap shield HP at `SCROLL_SHIELD_MAX_STACK` (proposed: 60) to prevent
  absurd stacking from multiple scrolls.
- Visual: translucent barrier / aura around the intruder.
- Sound: harmonic resonance / ward activation.
- Event: `"scroll_shield_used"` with intruder and new shield HP value.

---

## 7. Config Constants

All tuning parameters in `config/intruders.py`, grouped under a new
scroll-usage section:

```python
# ── Equipment -- scroll AI usage ────────────────────────────────────

# Evaluation timing
SCROLL_EVAL_INTERVAL = 5             # Ticks between scroll evaluations
SCROLL_EVAL_INTERVAL_NON_CARTO = 10  # Non-cartomancers evaluate slower

# Base threshold and modifiers
SCROLL_BASE_USE_THRESHOLD = 0.60     # Urgency must exceed this to use
SCROLL_CUNNING_FACTOR = -0.15        # Per-point cunning reduces threshold
SCROLL_RISK_FACTOR = -0.10           # Per-point risk_tolerance reduces threshold
SCROLL_PANIC_THRESHOLD_REDUCTION = -0.15   # When morale < LOW_THRESHOLD
SCROLL_LOW_HP_THRESHOLD_REDUCTION = -0.10  # When HP < 50%
SCROLL_RETREAT_THRESHOLD_REDUCTION = -0.15 # When RETREATING
SCROLL_CARTOMANCER_THRESHOLD_MULT = 0.50   # Halve threshold for cartomancers
SCROLL_LAST_SCROLL_THRESHOLD_BUMP = 0.15   # Increase when down to last scroll

# TELEPORT tuning
SCROLL_TELEPORT_CORNERED_URGENCY = 0.90
SCROLL_TELEPORT_GAUNTLET_URGENCY = 0.50
SCROLL_TELEPORT_SHORTCUT_URGENCY = 0.40
SCROLL_TELEPORT_RETREAT_URGENCY = 0.80
SCROLL_TELEPORT_FLUID_ESCAPE_URGENCY = 0.95
SCROLL_TELEPORT_GAUNTLET_MIN_HAZARDS = 3   # Hazards ahead to trigger gauntlet
SCROLL_TELEPORT_SHORTCUT_RATIO = 2.0       # Path/direct ratio to trigger shortcut
SCROLL_TELEPORT_RETREAT_HP_THRESHOLD = 0.30

# BRIDGE tuning
SCROLL_BRIDGE_GAP_URGENCY = 0.70
SCROLL_BRIDGE_WATER_URGENCY = 0.60
SCROLL_BRIDGE_LAVA_URGENCY = 0.95
SCROLL_BRIDGE_COLLAPSED_URGENCY = 0.50

# REVEAL tuning
SCROLL_REVEAL_FOG_URGENCY = 0.50
SCROLL_REVEAL_PATHLESS_URGENCY = 0.70
SCROLL_REVEAL_NEW_DEPTH_URGENCY = 0.30
SCROLL_REVEAL_EXPLORE_URGENCY = 0.40
SCROLL_REVEAL_FOG_THRESHOLD = 0.30   # Fraction of nearby cells that must be revealed
SCROLL_REVEAL_PATHLESS_TICKS = 15    # Ticks pathless before REVEAL triggers
SCROLL_REVEAL_WASTE_THRESHOLD = 0.80 # Skip if this fraction already revealed

# DISPEL tuning
SCROLL_DISPEL_DOOR_URGENCY = 0.80
SCROLL_DISPEL_CLUSTER_URGENCY = 0.60
SCROLL_DISPEL_SPIKE_URGENCY = 0.50
SCROLL_DISPEL_PLATE_URGENCY = 0.40
SCROLL_DISPEL_ALARM_URGENCY = 0.30
SCROLL_DISPEL_MIN_CLUSTER_SIZE = 2        # Enchanted blocks in radius to trigger
SCROLL_DISPEL_LOOKAHEAD_CELLS = 5         # Path cells ahead to scan
SCROLL_DISPEL_ALARM_SILENCE_TICKS = 200   # Cooldown applied to dispelled alarms
SCROLL_DISPEL_CUNNING_PROACTIVE = 0.40    # Minimum cunning for proactive dispel

# SHIELD tuning
SCROLL_SHIELD_LOW_HP_URGENCY = 0.70
SCROLL_SHIELD_DANGER_ZONE_URGENCY = 0.50
SCROLL_SHIELD_CORE_APPROACH_URGENCY = 0.30
SCROLL_SHIELD_PANIC_URGENCY = 0.60
SCROLL_SHIELD_NO_SHIELD_BONUS = 0.20      # Bonus urgency when shield_hp == 0
SCROLL_SHIELD_LOW_HP_THRESHOLD = 0.40     # HP fraction for low-HP trigger
SCROLL_SHIELD_CORE_APPROACH_DIST = 5      # Cells from core to trigger
SCROLL_SHIELD_DANGER_LOOKAHEAD = 3        # Path cells ahead to check for hazards
SCROLL_SHIELD_MAX_STACK = 60              # Max shield HP from scroll stacking
SCROLL_SHIELD_WASTE_THRESHOLD = 0.50      # Don't use if shield_hp > value * this
```

---

## 8. Player Counterplay

Good AI is predictable enough to be exploitable.  Every scroll usage
pattern has a counter.

### TELEPORT counters
- **Alarm bell networks**: When an intruder teleports, they land in a new
  position.  Alarm bells near likely teleport destinations alert the
  player.  Since the intruder's vision resets on teleport, they may
  teleport INTO a danger they did not see.
- **Sparse safe zones**: The teleport target must be a revealed air cell.
  If the player designs corridors with few open air cells visible from
  trap positions, teleport destinations are constrained.
- **Trap placement behind gaps**: If the player places traps after an open
  area (where intruders might teleport to), the intruder teleports into
  danger.
- **Distributed hazards**: Spread traps out rather than clustering them.
  Clustered traps trigger gauntlet-skip teleport; distributed traps give
  no single trigger.

### BRIDGE counters
- **Wide gaps**: Design gaps wider than 3 cells (bridge length).  The
  scroll cannot span the full distance, so the bridge is useless.
- **Multi-layer hazards**: Place lava or water on both sides of the gap.
  Even if the intruder bridges the middle, they must still cross the
  edges.
- **Destructible bridge foundation**: If the bridge spans over a
  structurally unstable area, gravity simulation may collapse the
  bridge cells when they revert (architecture-dependent).

### REVEAL counters
- **Depth over breadth**: Reveal has a fixed radius.  Deep, narrow
  dungeons force intruders to use REVEAL at each depth level rather
  than once for a wide floor.
- **Dynamic traps**: Traps that change state (pressure-plate-activated
  spikes, floodgates) may not be in their dangerous state when
  revealed.  The intruder's map snapshot becomes stale.
- **Gold bait behind fog**: Place Gold Bait where REVEAL will expose it.
  Greedy intruders will waste time chasing the bait, and non-arcane-
  sight intruders still see it as Treasure even through REVEAL.

### DISPEL counters
- **Spread enchanted blocks**: DISPEL radius is only 1.  Place enchanted
  doors and floodgates at least 3 cells apart so one dispel cannot
  neutralize multiple blocks.
- **Layered defenses**: Put a regular trap layer behind the enchanted
  layer.  Even if the enchanted door is dispelled, the intruder faces
  spikes / rolling stones next.
- **Rapid recharge**: Use the enchanted block panel to set blocks to
  "charging" mode.  After a dispel, the block recharges from the core
  reserve.  High-capacitance blocks recharge faster than the intruder
  can advance.
- **Capacitance reserves**: Keep blocks at high capacitance.  Even if
  dispel drains them, the block was already powered and the intruder
  has passed by the time it would have mattered.  (This is more a
  mindset than a mechanic -- the point is that dispel costs the
  intruder a scroll slot.)
- **Non-enchanted alternatives**: Regular doors and floodgates are immune
  to DISPEL.  A hybrid defense with both enchanted and regular blocks
  forces the intruder to bring both DISPEL scrolls and lockpick/bash
  capability.

### SHIELD counters
- **Sustained damage over time**: Shield HP is finite (30, stacks to 60).
  Water drowning damage, heat beacons, and steam vents deal damage
  every tick.  A shield scroll buys only a few ticks of protection
  against sustained hazards.
- **Multiple damage sources**: Design kill zones where spikes, rolling
  stones, AND steam vents all trigger in sequence.  Shield absorbs
  the first hit; subsequent hits reach HP.
- **Mana drain**: Drain global mana to depower traps, then re-power
  them after the intruder has used their shield scroll.  The
  intruder wasted a scroll on a threat that was temporarily absent.

---

## 9. Edge Cases

### 9.1 No valid target

If a scroll's target selection finds no valid cell (teleport to nowhere,
bridge over nothing, dispel with no traps in radius), the scroll is NOT
consumed.  The urgency for that scroll type is cached as 0.0 for the next
`SCROLL_EVAL_INTERVAL` ticks to avoid re-evaluating an impossible action.

### 9.2 Scroll used during INTERACTING state

Intruders in `IntruderState.INTERACTING` (bashing a door, digging, etc.)
should not evaluate scrolls.  The interaction is a committed action.
Exception: SHIELD can be used during INTERACTING (it is self-buff with
no spatial component) if HP drops below 30% during the interaction.

### 9.3 Multiple scroll types available

When an intruder carries multiple scroll types, evaluate all of them and
pick the one with the highest urgency (after threshold filtering).  If
two scrolls have equal urgency, prefer the one that addresses the most
immediate threat:

Priority order: TELEPORT (escape) > SHIELD (survival) > DISPEL (obstacle
removal) > BRIDGE (traversal) > REVEAL (information).

### 9.4 Concurrent scroll effects

- An intruder can have both shield HP from a SHIELD scroll and a bridge
  active from a BRIDGE scroll.  These do not conflict.
- If an intruder uses TELEPORT while standing on their own bridge, the
  bridge persists (it is world state, not intruder state).
- If two intruders in the same party both have REVEAL scrolls, the second
  reveal is largely redundant (most cells already revealed by the first).
  Party-level coordination is out of scope for this proposal but noted
  as a future enhancement.

### 9.5 Blocked by environment after scroll use

- TELEPORT to a cell that becomes non-air before the teleport resolves
  (impossible with current tick-based system since scroll use is
  instantaneous, but documented for safety): cancel the teleport, do
  not consume the scroll.
- BRIDGE cells that are overwritten by physics (water flow, gravity
  collapse) before the bridge expires: the bridge cells are lost early.
  No special handling needed -- the bridge entry is cleaned up when
  expiration fires and finds the cell already changed.

### 9.6 Dead intruder's scrolls

When an intruder dies, their scrolls are lost.  No transfer to party
members.  This is intentional: killing the cartomancer before they use
their scrolls is a major player victory and should be rewarded.

### 9.7 Scroll used on the same tick as death

If an intruder takes lethal damage and triggers a scroll evaluation in the
same tick, the scroll check runs BEFORE death processing (it is in step 5
of `_update_intruder`, before the alive guard at step end).  However, if
the intruder died in step 2 (water) or step 3 (state processing), they
are already dead and `_tick_equipment_use` is skipped.  This is correct:
a dead intruder cannot use scrolls.

### 9.8 Scroll shield stacking with gear shield

The `take_damage` method already handles shield HP correctly -- it absorbs
damage from any source regardless of whether the shield came from gear or
a scroll.  No special handling needed.  The `SCROLL_SHIELD_MAX_STACK` cap
prevents degenerate stacking from multiple SHIELD scrolls.

---

## 10. Implementation Plan

### New files
- `dungeon_builder/intruders/scroll_usage.py` -- Contains `ScrollContext`,
  `_tick_scroll_use()`, per-scroll evaluator functions, target selection,
  and threshold computation.  Target ~400 lines.

### Modified files
- `dungeon_builder/intruders/decision.py` -- Change `_tick_equipment_use`
  from `@staticmethod` to instance method.  Add `ScrollContext` creation
  and call to `_tick_scroll_use`.  Add `_active_bridges` list and bridge
  expiration logic to `_on_tick`.
- `dungeon_builder/config/intruders.py` -- Add all config constants from
  section 7.
- `dungeon_builder/dungeon_core/mana.py` -- Add `dispel_block(x, y, z)`
  public method that sets capacitance to 0 and activated to False.
- `dungeon_builder/intruders/agent.py` -- Add `scroll_eval_cooldown: int`
  to `__slots__` and initialize to 0.

### New events
- `"intruder_teleported"` -- old_pos, new_pos, intruder
- `"bridge_created"` -- positions, original_types, expiration_tick, intruder
- `"bridge_expired"` -- positions
- `"scroll_reveal_used"` -- intruder, center_pos, radius
- `"scroll_dispel_used"` -- intruder, target_pos, affected_positions
- `"scroll_shield_used"` -- intruder, shield_hp

### Tests
- `tests/intruders/test_scroll_usage.py` -- Unit tests for each scroll
  evaluator, threshold computation, target selection, edge cases.
- `tests/integration/test_scroll_ai.py` -- Integration test: spawn
  cartomancer, place traps, verify scroll is used at the right moment.

### Estimated scope
- ~400 lines new code (`scroll_usage.py`)
- ~50 lines config constants
- ~30 lines modifications to existing files
- ~300 lines tests
- Total: ~780 lines of changes
