# Vision System Rework Proposal

## Status

**Draft** -- 2026-02-28

## Problem Statement

The current intruder vision system recomputes full Bresenham ray-casting
from scratch every time an intruder moves. With the default perception
ranges (3-6 cells) and the `_vision_dirty` flag, a single `compute_los`
call casts rays to every cell on the surface of a cube of side
`2r+1`. For perception range 6, that is up to 728 target cells on the
cube surface, each walked via 3D Bresenham. At 24 concurrent intruders
moving every 3-10 ticks, this creates thousands of ray-casts per second,
making vision the dominant per-tick cost.

Specific deficiencies:

1. **No incremental updates.** Moving one cell recomputes the entire
   visible set from zero. Most of the visible set (the "behind" hemisphere)
   is identical to the previous tick's.

2. **No party vision sharing.** Two party members standing next to each
   other each compute independent full LOS. The `PersonalMap.merge()`
   system shares *knowledge* after the fact, but the expensive ray-casting
   work is not shared.

3. **No temporal caching.** A cell confirmed visible 1 tick ago is re-verified
   from scratch even though the dungeon geometry almost certainly has not
   changed in that single tick.

4. **Arcane sight and thermal vision also iterate naively.** `compute_arcane_sight`
   and `compute_thermal_vision` use triple-nested loops over a Manhattan
   cube every update, allocating fresh sets each time.

## Design Goals

1. Support 24 simultaneous intruders without vision dominating tick cost.
2. Maintain fog-of-war accuracy: intruders see only what LOS permits.
3. Preserve vision deception (Gold Bait appears as Treasure, Fragile Floor
   appears as Stone to normal sight; arcane sight sees truth).
4. Integrate with the EventBus architecture (no direct cross-system imports).
5. Remain testable without Panda3D (pure Python + NumPy, no GPU).
6. Keep the `_vision_dirty` optimization.

---

## 1. Architecture Overview

The rework introduces a layered vision pipeline with three new concepts:

```
VisionCache (per-intruder)        -- stores last LOS result + metadata
    |
VisionDelta                       -- computes only the changed cells
    |
PartyVisionPool (per-party)       -- shares raw LOS across nearby members
    |
PersonalMap (existing, unchanged) -- fog-of-war with deception applied
```

### New Modules

| Module | Responsibility |
|--------|---------------|
| `intruders/vision_cache.py` | `VisionCache` dataclass and delta computation logic |
| `intruders/vision_pool.py` | `PartyVisionPool` class for shared LOS computation |
| `intruders/vision.py` (modified) | Add `compute_los_delta`, keep `compute_los` as fallback |

### Module Dependency Graph

```
vision.py          -- pure LOS algorithms (no EventBus dependency)
vision_cache.py    -- per-intruder cache state (imports vision.py)
vision_pool.py     -- party-level sharing (imports vision_cache.py)
hazard_response.py -- calls vision_cache / vision_pool (existing wiring point)
```

No new EventBus subscriptions are required for the core vision path.
The existing `"voxel_changed"` event is used to invalidate caches.

---

## 2. Incremental / Delta Vision Update Strategy

### Core Insight

When an intruder moves from position A to adjacent position B (Manhattan
distance 1), the visible set changes only at the "fringe": cells that
enter or leave visibility due to the positional shift. The vast majority
of visible cells remain visible.

For perception range `r`, a full recompute visits O(r^2) surface targets.
A delta recompute visits only the cells on the *new* fringe (one face of
the cube) plus a small correction band, totaling O(r) targets.

### Delta Algorithm

```python
def compute_los_delta(
    grid: VoxelGrid,
    old_pos: tuple[int, int, int],
    new_pos: tuple[int, int, int],
    perception_range: int,
    old_visible: set[tuple[int, int, int]],
) -> tuple[set[tuple[int, int, int]], set[tuple[int, int, int]]]:
    """Return (newly_visible, no_longer_visible) relative to old_visible.

    Instead of casting rays to the entire cube surface, only casts rays
    in the direction of movement (the "leading face") plus a correction
    band of 1 cell on each adjacent face to handle parallax shifts.

    Cells on the "trailing face" (opposite to movement) are assumed lost
    unless they fall within the new range, in which case they are kept
    from old_visible without re-casting.
    """
```

**Step-by-step:**

1. Compute the movement vector `(dx, dy, dz)` from `old_pos` to `new_pos`.

2. **Leading-face ray-cast.** Identify the face of the perception cube
   in the direction of movement. For example, if `dx = +1`, the leading
   face is the plane `x = new_x + r`. Cast rays from `new_pos` to every
   cell on this face. This is O(r) targets (one plane of the cube surface).

3. **Correction band.** On the four adjacent faces (perpendicular to the
   movement axis), cast rays to the outermost strip of 1 cell width.
   This accounts for cells that become visible or hidden due to parallax
   shifts around obstacles. This adds O(r) targets.

4. **Trailing-face pruning.** The face opposite to movement direction
   (`x = old_x - r` in the example) may lose cells. Rather than
   re-casting, simply subtract cells from `old_visible` that now fall
   outside the new perception cube. This is a set operation, O(r) worst case.

5. **Geometry-change correction.** If any `"voxel_changed"` events have
   fired since the last vision update (tracked via a generation counter
   on the grid, described in section 3), additionally re-cast rays toward
   all changed cells that lie within the perception cube. This handles
   doors opening, blocks being destroyed, etc.

6. **Combine.** The new visible set is:
   ```
   new_visible = (old_visible
                  - trailing_lost
                  - occluded_by_geometry_change)
                 | leading_gained
                 | correction_gained
                 | geometry_change_gained
   ```

7. Return `(newly_visible, no_longer_visible)` so the caller can update
   the `PersonalMap` incrementally (only calling `reveal()` for newly
   visible cells instead of iterating the entire visible set).

### Fallback to Full Recompute

Delta computation is only valid when the intruder moved exactly 1 cell
in a cardinal direction. In these cases, fall back to a full `compute_los`:

- First vision update after spawn (no previous visible set).
- Teleportation or push (moved more than 1 cell).
- Multi-axis diagonal movement (dx != 0 and dy != 0 and dz != 0).
- Cache invalidation due to excessive geometry changes (section 3).
- Arcane sight and thermal vision (these are cheap enough that delta
  would add complexity without proportional benefit -- see section 8).

### Complexity Analysis

| Scenario | Full recompute | Delta recompute |
|----------|---------------|-----------------|
| Targets visited | O(r^2) | O(r) |
| Per-target ray length | O(r) | O(r) |
| Total ray cells | O(r^3) | O(r^2) |
| r=6 (Explorer) | ~4,400 cells walked | ~800 cells walked |
| r=3 (Mole Tamer) | ~550 cells walked | ~120 cells walked |

Approximate 5x reduction in ray-casting work per move.

---

## 3. Caching Strategy

### 3.1 VisionCache (Per-Intruder)

Each intruder gains a `VisionCache` stored alongside its `PersonalMap`.

```python
@dataclass
class VisionCache:
    """Memoized state from the last vision computation."""

    # Position at which the cache was computed
    last_pos: tuple[int, int, int] | None = None

    # The raw set of cells visible from last_pos (before deception)
    last_visible: set[tuple[int, int, int]] | None = None

    # Grid geometry generation counter at time of computation.
    # If the grid's generation has advanced, some cached cells may
    # be stale.
    last_grid_generation: int = -1

    # Effective perception range used (for invalidation when torch
    # burns out, etc.)
    last_perception_range: int = 0
```

**Slot added to Intruder.__slots__:** `"_vision_cache"`

**Initialization in Intruder.__init__:**
```python
self._vision_cache = VisionCache()
```

### 3.2 Grid Geometry Generation Counter

`VoxelGrid` gains a monotonically increasing `_geometry_generation: int`
counter, bumped every time `set()` is called (i.e., any block type change).
This is extremely cheap (one integer increment per block change) and gives
vision caches a fast staleness check.

```python
# In VoxelGrid.set():
self._geometry_generation += 1
```

When a `VisionCache.last_grid_generation` does not match
`voxel_grid._geometry_generation`, the cache knows the world has changed.
However, it does not immediately recompute. Instead:

- If fewer than `VISION_GEOMETRY_CHANGE_THRESHOLD` changes have occurred,
  only the changed cells are re-checked (targeted ray-casts).
- If more than the threshold have occurred, a full recompute is triggered.

### 3.3 Changed-Cell Tracking

To enable targeted re-verification, the vision system maintains a
lightweight ring buffer or set of recently changed cell positions:

```python
# In IntruderAI (or a dedicated VisionManager):
_recently_changed_cells: set[tuple[int, int, int]]
```

Populated by subscribing to `"voxel_changed"` (already done in
`IntruderAI._on_voxel_changed`). Cleared once per tick after all
intruders have updated vision. This prevents unbounded growth.

When an intruder's delta computation runs, it checks whether any
recently changed cells fall within its perception cube. If so, those
cells are re-verified by casting a ray from the intruder's position
to the changed cell.

### 3.4 What Gets Cached vs. Recomputed

| Data | Cached? | Invalidation trigger |
|------|---------|---------------------|
| Raw visible set (cell positions) | Yes, in `VisionCache` | Movement, geometry change, perception change |
| Deception-applied types (PersonalMap.seen) | No -- always derived from raw visible + grid.get() | N/A |
| Arcane sight set | No -- cheap enough to recompute | N/A |
| Thermal vision set | No -- cheap enough to recompute | N/A |
| Grid geometry generation | Counter on VoxelGrid | Every `set()` call |
| Recently changed cells | Per-tick set, cleared each tick | Every `set()` call adds to set |

**Rationale for not caching deception:** Vision deception (Gold Bait
appearing as Treasure) depends on the *current* block type at the time
of observation. If a Gold Bait is placed between vision updates, the
intruder should see it as Treasure on the next update. Caching the
deception result would risk showing stale deception data.

### 3.5 Perception Change Detection

The `_vision_dirty` flag currently fires on any movement. The reworked
system adds a second invalidation path: perception range change. This
handles:

- Torch burning out (perception drops by `TORCH_PERCEPTION_BONUS`).
- Torch being lit (perception increases).
- Equipment changes (unlikely mid-dungeon, but future-proof).

```python
# In VisionCache or in _update_vision:
if intruder.effective_perception != cache.last_perception_range:
    # Full recompute needed -- range changed
    cache.last_visible = None
```

---

## 4. Party Vision Sharing Optimization

### Current Situation

Each intruder in a party computes LOS independently. `Party.share_maps()`
then merges their `PersonalMap` data every `MAP_SHARE_INTERVAL` ticks.
This means:

- 4 intruders in the same corridor each cast ~4,400 ray cells (r=6).
- Total: ~17,600 ray cells for what is largely the same visible set.

### PartyVisionPool

A `PartyVisionPool` is a per-party structure that coalesces LOS
computation for intruders that are close together.

```python
class PartyVisionPool:
    """Shared vision computation for nearby party members.

    When two or more party members are within VISION_SHARE_RANGE cells
    of each other, the pool designates one as the "primary viewer" and
    shares its raw visible set with the others, who then only compute
    a small correction delta for their individual offset.
    """

    def compute_party_vision(
        self,
        members: list[Intruder],
        grid: VoxelGrid,
    ) -> dict[int, set[tuple[int, int, int]]]:
        """Return {intruder_id: visible_set} for all members."""
```

**Algorithm:**

1. **Cluster** alive party members by proximity. Two members are in the
   same cluster if their Chebyshev distance is <= `VISION_SHARE_RANGE`.
   Use a simple union-find or brute-force pairwise check (max 8 members
   per party).

2. For each cluster:

   a. **Elect a primary viewer**: the member with the highest effective
      perception range (sees the most). Ties broken by intruder ID.

   b. **Compute full or delta LOS** for the primary viewer using its
      `VisionCache`.

   c. For each secondary member in the cluster:
      - Compute the offset `(dx, dy, dz)` from primary to secondary.
      - If offset is `(0, 0, 0)` (same cell), reuse the primary's
        visible set directly.
      - Otherwise, compute a **correction delta**: cast rays only along
        the leading face relative to the offset direction, and subtract
        cells that are out of the secondary's perception range. This is
        O(r) work instead of O(r^2).
      - The secondary's raw visible set is:
        `primary_visible (clipped to secondary range) + correction_delta`

3. **Solo members** (not near any ally) compute vision normally via
   their own `VisionCache` + delta.

**Deception is always applied per-intruder**, even when sharing raw
visible sets. A Gloomwarden with arcane sight will reveal true types,
while a nearby Explorer will see deception. The raw visible set is
just cell *positions* -- type interpretation happens afterward.

### Complexity Savings

| Scenario | Without pool | With pool |
|----------|-------------|-----------|
| 4 members in same corridor, r=6 | 4 x 4,400 = 17,600 cells | 1 x 4,400 + 3 x 800 = 6,800 cells |
| 2 members in same cell, r=6 | 2 x 4,400 = 8,800 cells | 1 x 4,400 = 4,400 cells |
| 4 members spread out | 4 x 4,400 = 17,600 cells | 4 x 4,400 = 17,600 cells (no sharing) |

Worst case: no savings (all members far apart). Best case: N-1 full
recomputes eliminated. Typical case (party moving in formation):
60-70% reduction in ray-casting work.

### Integration with Existing Map Sharing

`PartyVisionPool` operates at the *raw visible set* level (positions
only). It does NOT replace `PersonalMap.merge()`. The data flow is:

1. `PartyVisionPool` shares raw visible positions (avoid redundant
   ray-casting).
2. Each intruder applies deception and `reveal()`s into their own
   `PersonalMap`.
3. `Party.share_maps()` continues to merge `PersonalMap` knowledge
   at `MAP_SHARE_INTERVAL` (sharing door states, hazard markers, etc.
   that go beyond raw visibility).

---

## 5. Memory vs. Computation Tradeoffs

### Memory Costs

| Structure | Size estimate | Per-entity |
|-----------|--------------|------------|
| `VisionCache.last_visible` | ~700 cells x 24 bytes (3 ints in a tuple in a set) = ~17 KB | Per intruder |
| `VisionCache` metadata | ~50 bytes (pos, generation, range) | Per intruder |
| `_recently_changed_cells` | Variable, typically <100 entries x 24 bytes = ~2.4 KB | Global (shared) |
| `PartyVisionPool` | ~200 bytes + cluster list | Per party |
| Grid `_geometry_generation` | 8 bytes (single int) | Global |

**Total additional memory for 24 intruders:**
- 24 x 17 KB (vision caches) = ~408 KB
- 1 x 2.4 KB (changed cells) = ~2.4 KB
- 3 x 200 bytes (party pools) = ~0.6 KB
- **Total: ~411 KB**

This is negligible compared to the voxel grid itself (50 x 50 x 40 x
multiple arrays = several MB).

### Tradeoff Decisions

1. **Cache the raw visible set (17 KB per intruder) vs. recompute.**
   Caching wins: the memory cost is trivial and it enables delta
   computation, which saves thousands of ray-cell walks per tick.

2. **Track changed cells globally vs. per-intruder.**
   Global wins: a single set is simpler, uses less memory, and is
   cleared once per tick. Each intruder filters it against their own
   perception cube (a fast bounding-box check).

3. **Party vision pool overhead vs. savings.**
   The clustering step is O(n^2) per party where n <= 8, so at most
   28 distance checks. This is negligible compared to even one
   `compute_los` call. The pool is worth it whenever >= 2 members
   are close.

4. **Not caching arcane sight / thermal vision.**
   These are Manhattan-distance iterations with no ray-casting. For
   arcane_sight_range=3, that is at most 85 cells checked (Manhattan
   ball radius 3 in 3D). For thermal_vision range=4, similarly small.
   Caching these would add complexity for marginal gain.

5. **Deception applied per-intruder, not cached.**
   A cell that is a Gold Bait might be revealed as Treasure to one
   intruder and as Gold Bait to another (arcane sight). Caching the
   deception result per-intruder would create subtle correctness bugs
   if the block type changes between ticks. Since `reveal()` is a
   dict update (O(1)), applying deception per cell is cheap.

---

## 6. Migration Path

The rework can be implemented in four phases, each independently
testable and deployable.

### Phase 1: Grid Generation Counter + Changed-Cell Tracking

**Files modified:** `world/voxel_grid.py`, `intruders/decision.py`

- Add `_geometry_generation: int` to `VoxelGrid.__init__`.
- Increment it in `VoxelGrid.set()`.
- Add `_recently_changed_cells: set` to `IntruderAI.__init__`.
- Populate it in `_on_voxel_changed`.
- Clear it at the end of `_on_tick` after all intruders have updated.
- No behavioral change -- this is pure infrastructure.

**Tests:** Verify generation counter increments on `set()`. Verify
changed-cell set is populated and cleared correctly.

### Phase 2: VisionCache + Delta Computation

**Files modified:** `intruders/vision.py` (add `compute_los_delta`),
new file `intruders/vision_cache.py`

**Files modified:** `intruders/agent.py` (add `_vision_cache` slot),
`intruders/hazard_response.py` (use cache in `_update_vision`)

- Implement `VisionCache` dataclass.
- Implement `compute_los_delta` in `vision.py`.
- Modify `_update_vision` in `hazard_response.py`:
  - If cache is valid and intruder moved 1 cell cardinally, use delta.
  - Otherwise, fall back to full `compute_los`.
  - After computing, update cache.
  - Apply deception and `reveal()` only for newly visible cells.
  - For cells no longer visible, no action needed (PersonalMap retains
    last-seen data by design).

**Tests:**
- Unit test: `compute_los_delta` produces the same result as full
  `compute_los` on small grids (correctness verification).
- Unit test: `VisionCache` invalidation triggers (perception change,
  geometry change, teleportation).
- Integration test: intruder moving through a corridor sees the same
  cells as before the rework (regression test).
- Integration test: Gold Bait deception still works with delta updates.
- Benchmark: measure `_update_vision` time before/after on a 50x50x40
  grid with 24 intruders.

### Phase 3: PartyVisionPool

**New file:** `intruders/vision_pool.py`

**Files modified:** `intruders/hazard_response.py` (or a new
`VisionManager` extracted from the mixin)

- Implement `PartyVisionPool` with clustering and primary-viewer
  election.
- Modify the per-tick vision update to:
  1. For each party, call `pool.compute_party_vision(members, grid)`.
  2. For solo intruders (no party), compute vision individually.
  3. Each intruder applies deception to its received visible set.

**Tests:**
- Unit test: two intruders at the same position get identical visible
  sets, with only one full LOS computed.
- Unit test: intruders far apart get independent visible sets.
- Unit test: deception is applied per-intruder (Gloomwarden sees truth,
  Explorer sees deception, from the same raw visible set).
- Integration test: party moving in formation -- verify PersonalMap
  contents match pre-rework behavior.

### Phase 4: Optimization Pass

- Profile with `cProfile` or the existing benchmark harness.
- Tune `VISION_SHARE_RANGE` and `VISION_GEOMETRY_CHANGE_THRESHOLD`.
- Consider NumPy vectorization for the leading-face ray-cast if
  profiling shows it is still hot.
- Consider pre-computing a "ray template" LUT: for each
  `(dx, dy, dz)` offset within range `r`, store the Bresenham cell
  list. On delta computation, look up the template rather than
  recomputing Bresenham. Memory cost: O(r^3) tuples per range value
  used, shared across all intruders with the same range. This is a
  classic time-memory tradeoff -- only implement if profiling warrants.

---

## 7. Performance Analysis

### Baseline (Current System)

Assumptions:
- 24 intruders alive.
- Average perception range: 5 cells (weighted by archetype frequency).
- Average move interval: 5 ticks (weighted average).
- Each `compute_los` for range 5: visits ~602 surface targets, each ray
  walks ~5 cells on average = ~3,010 cell visits per call.
- Per tick: ~24 / 5 = ~4.8 intruders move per tick.
- Per tick: ~4.8 x 3,010 = ~14,448 ray-cell visits.
- At 20 ticks/second: ~289,000 ray-cell visits per second.

Each ray-cell visit involves:
- Array index (NumPy `grid_arr[cx, cy, cz]`): ~50ns.
- Set membership check and add: ~50ns.
- Bresenham step arithmetic: ~30ns.
- Total per cell: ~130ns.

**Baseline vision cost: ~289,000 x 130ns = ~37.6 ms/s** (3.76% of
wall time at 20 ticks/s, but bursty -- when many intruders move on the
same tick, can spike to 10ms+ for a single tick).

### After Phase 2 (Delta Updates)

- Delta recompute visits ~1/5 the cells (leading face + correction).
- Per delta: ~602 cells instead of 3,010.
- Per tick: ~4.8 x 602 = ~2,890 ray-cell visits.
- Full recompute still needed on spawn and teleport: assume ~1/20 ticks
  = 0.24 full recomputes/tick = ~720 cells.
- Per tick total: ~3,610 cells.
- At 20 ticks/second: ~72,200 ray-cell visits per second.
- **Cost: ~9.4 ms/s.** ~75% reduction from baseline.

### After Phase 3 (Party Vision Pool)

- Assume 3 parties of ~8 members each, average cluster size 3.
- Instead of 3 full/delta computations per cluster, do 1 full/delta + 2
  corrections.
- Correction cost per intruder: ~60% of a delta (~360 cells).
- Effective per-tick: ~1.6 full-delta + ~3.2 corrections = ~1.6 x 602 +
  3.2 x 360 = ~2,115 cells.
- At 20 ticks/second: ~42,300 ray-cell visits per second.
- **Cost: ~5.5 ms/s.** ~85% reduction from baseline.

### Summary Table

| Phase | Ray-cells/tick | Ray-cells/second | ms/second | Reduction |
|-------|---------------|-----------------|-----------|-----------|
| Current | ~14,448 | ~289,000 | ~37.6 | -- |
| Phase 2 (delta) | ~3,610 | ~72,200 | ~9.4 | 75% |
| Phase 3 (pool) | ~2,115 | ~42,300 | ~5.5 | 85% |

These are rough estimates. Actual improvement depends on intruder
distribution, dungeon geometry, and Python overhead. The benchmark
harness should be used to validate after each phase.

---

## 8. Config Constants

New constants to add to `config/intruders.py` under a `# -- Vision (rework)` section:

```python
# -- Vision (rework) ────────────────────────────────────────────────────

# Maximum perception range difference between two intruders for party
# vision sharing.  If the secondary's range exceeds the primary's by
# more than this, the secondary computes its own LOS independently
# rather than using a correction delta (the correction would be too
# large to be worthwhile).
VISION_SHARE_RANGE_TOLERANCE = 2

# Chebyshev distance within which party members share raw visible sets.
# This is separate from MAP_SHARE_RANGE (which governs PersonalMap
# merging).  VISION_SHARE_RANGE should be <= MAP_SHARE_RANGE.
VISION_SHARE_RANGE = 3

# Number of geometry changes (voxel_changed events) since last vision
# update before a full recompute is forced instead of targeted
# re-verification.  Below this threshold, only changed cells within the
# perception cube are re-checked.  Above it, a full compute_los is
# cheaper than N targeted ray-casts.
VISION_GEOMETRY_CHANGE_THRESHOLD = 20

# Maximum number of ticks a vision cache is considered "warm" even when
# the intruder has not moved.  After this many ticks without movement,
# the cache is evicted to free memory.  The _vision_dirty flag prevents
# recomputation while stationary, so this only affects memory.
VISION_CACHE_EVICTION_TICKS = 200

# Whether to enable party vision pooling.  Set to False to disable
# the optimization (useful for debugging correctness or benchmarking
# the delta-only path).
VISION_POOL_ENABLED = True

# Whether to enable delta vision updates.  Set to False to force full
# recomputation on every move (useful for debugging correctness).
VISION_DELTA_ENABLED = True
```

These constants are tuning knobs that can be adjusted without changing
code, consistent with the config-driven design principle.

### Existing Constants Retained (No Changes)

- `WATER_LOS_DEPTH = 2` -- used by ray-casting, unchanged.
- `DARKVISION_DEPTH_THRESHOLD = 3` -- used in `_update_vision`, unchanged.
- `MAP_SHARE_RANGE = 3` -- governs PersonalMap merge distance, separate
  from `VISION_SHARE_RANGE`.
- `MAP_SHARE_INTERVAL = 10` -- governs PersonalMap merge frequency,
  unchanged.

---

## 9. Detailed Implementation Notes

### 9.1 Modified `_update_vision` Flow

The reworked `_update_vision` in `hazard_response.py`:

```python
def _update_vision(self, intruder: Intruder) -> None:
    if not intruder._vision_dirty:
        return
    intruder._vision_dirty = False

    grid = self.voxel_grid
    arch = intruder.archetype
    x, y, z = intruder.x, intruder.y, intruder.z
    pmap = intruder.personal_map
    cache = intruder._vision_cache

    hazards_before = len(pmap.hazards)

    # Effective perception range
    eff_range = intruder.effective_perception
    if z > SURFACE_Z + DARKVISION_DEPTH_THRESHOLD:
        eff_range += arch.darkvision_range

    # Determine whether delta is possible
    can_delta = (
        VISION_DELTA_ENABLED
        and cache.last_visible is not None
        and cache.last_pos is not None
        and cache.last_perception_range == eff_range
        and _is_adjacent(cache.last_pos, (x, y, z))
        and self._geometry_changes_in_range(x, y, z, eff_range)
            < VISION_GEOMETRY_CHANGE_THRESHOLD
    )

    if can_delta:
        newly_visible, no_longer_visible = compute_los_delta(
            grid, cache.last_pos, (x, y, z), eff_range,
            cache.last_visible,
        )
        # Also re-verify any recently changed cells in range
        changed_in_range = self._changed_cells_in_range(x, y, z, eff_range)
        if changed_in_range:
            extra_visible = _recheck_cells(grid, x, y, z, changed_in_range)
            newly_visible |= (extra_visible - cache.last_visible)
            no_longer_visible -= extra_visible

        visible = (cache.last_visible - no_longer_visible) | newly_visible
        reveal_set = newly_visible | changed_in_range
    else:
        visible = compute_los(grid, x, y, z, eff_range)
        reveal_set = visible

    # Update cache
    cache.last_pos = (x, y, z)
    cache.last_visible = visible
    cache.last_grid_generation = grid._geometry_generation
    cache.last_perception_range = eff_range

    # Apply deception and reveal ONLY for new/changed cells
    for vx, vy, vz in reveal_set:
        vtype = grid.get(vx, vy, vz)
        bstate = int(grid.block_state[vx, vy, vz])
        if vtype == VOXEL_GOLD_BAIT:
            pmap.reveal(vx, vy, vz, VOXEL_TREASURE, bstate)
        elif vtype == VOXEL_FRAGILE_FLOOR:
            pmap.reveal(vx, vy, vz, VOXEL_STONE, bstate)
        else:
            pmap.reveal(vx, vy, vz, vtype, bstate)

    # Arcane sight (unchanged -- cheap enough)
    if arch.arcane_sight_range > 0:
        arcane = compute_arcane_sight(grid, x, y, z, arch.arcane_sight_range)
        for vx, vy, vz in arcane:
            vtype = grid.get(vx, vy, vz)
            bstate = int(grid.block_state[vx, vy, vz])
            pmap.reveal(vx, vy, vz, vtype, bstate)
            if vtype == VOXEL_GOLD_BAIT:
                pmap.mark_bait(vx, vy, vz)
            elif vtype == VOXEL_FRAGILE_FLOOR:
                pmap.mark_hazard(vx, vy, vz)

    # Thermal vision (unchanged -- cheap enough)
    if intruder.has_fire_immunity and arch.perception_range >= 4:
        thermal = compute_thermal_vision(grid, x, y, z, 4)
        for vx, vy, vz in thermal:
            vtype = grid.get(vx, vy, vz)
            bstate = int(grid.block_state[vx, vy, vz])
            pmap.reveal(vx, vy, vz, vtype, bstate)

    # Morale penalty for newly revealed hazards
    new_hazards = len(pmap.hazards) - hazards_before
    if new_hazards > 0:
        intruder.morale = max(
            0.0, intruder.morale - MORALE_HAZARD_PENALTY * new_hazards,
        )
```

### 9.2 Leading-Face Ray Target Selection

The leading face targets for a movement in direction `(dx, 0, 0)` where
`dx = +1`:

```python
def _leading_face_targets(
    cx: int, cy: int, cz: int,
    dx: int, dy: int, dz: int,
    r: int,
) -> list[tuple[int, int, int]]:
    """Return target cells on the leading face of the perception cube."""
    targets = []
    if dx != 0:
        face_x = cx + r * dx  # dx is +1 or -1
        for fy in range(cy - r, cy + r + 1):
            for fz in range(cz - r, cz + r + 1):
                targets.append((face_x, fy, fz))
    elif dy != 0:
        face_y = cy + r * dy
        for fx in range(cx - r, cx + r + 1):
            for fz in range(cz - r, cz + r + 1):
                targets.append((fx, face_y, fz))
    elif dz != 0:
        face_z = cz + r * dz
        for fx in range(cx - r, cx + r + 1):
            for fy in range(cy - r, cy + r + 1):
                targets.append((fx, fy, face_z))
    return targets
```

The correction band adds the outermost strip on each perpendicular
face. For movement in `+x`, this is cells at `y = cy +/- r` on the
y-faces, and `z = cz +/- r` on the z-faces, for the full extent
of the new cube:

```python
def _correction_band_targets(
    cx: int, cy: int, cz: int,
    dx: int, dy: int, dz: int,
    r: int,
) -> list[tuple[int, int, int]]:
    """Return target cells on the correction band (outermost strip of
    perpendicular faces)."""
    targets = []
    if dx != 0:
        # Y-faces: y = cy +/- r, full x and z range of new cube
        for fx in range(cx - r, cx + r + 1):
            for fz in range(cz - r, cz + r + 1):
                targets.append((fx, cy + r, fz))
                targets.append((fx, cy - r, fz))
        # Z-faces: z = cz +/- r, full x and y range (excluding corners already covered)
        for fx in range(cx - r, cx + r + 1):
            for fy in range(cy - r + 1, cy + r):
                targets.append((fx, fy, cz + r))
                targets.append((fx, fy, cz - r))
    # Similar for dy != 0 and dz != 0 (symmetric)
    return targets
```

### 9.3 Adjacency Check

```python
def _is_adjacent(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> bool:
    """True if a and b differ by exactly 1 in one axis and 0 in others."""
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    dz = abs(a[2] - b[2])
    return (dx + dy + dz) == 1
```

### 9.4 Save/Load Considerations

`VisionCache` is **transient** -- it is not saved or loaded. On load,
each intruder's `_vision_cache` is reset to default (empty), causing
the first post-load vision update to be a full recompute. This is
correct: one extra full recompute on load is negligible, and it avoids
serializing mutable set data.

The `PersonalMap` continues to be the persistent fog-of-war state,
saved and loaded as before.

### 9.5 EventBus Integration

No new events are introduced. The existing event flow is:

- `"voxel_changed"` -> `_on_voxel_changed` -> populates
  `_recently_changed_cells` (new behavior) + existing alarm bell index
  update.
- `"tick"` -> `_on_tick` -> vision updates for all intruders -> clears
  `_recently_changed_cells` at end of tick.
- `"intruder_moved"` -> published as before by `_move_to`.

This maintains the event-driven loose coupling: the vision system
observes `"voxel_changed"` through the EventBus rather than importing
VoxelGrid mutation methods.

---

## 10. Test Plan

### New Test Files

- `tests/intruders/test_vision_cache.py` -- VisionCache invalidation,
  delta correctness.
- `tests/intruders/test_vision_pool.py` -- PartyVisionPool clustering,
  primary election, shared visibility.

### Regression Tests

For every test listed below, the expected result should match the
pre-rework behavior exactly (same cells visible, same deception
applied, same PersonalMap contents).

1. **Single intruder in open air.** Vision result with delta matches
   full recompute.
2. **Single intruder in corridor.** Walls block LOS correctly with delta.
3. **Gold Bait deception.** Explorer sees Treasure. Gloomwarden with
   arcane sight sees Gold Bait and marks it.
4. **Fragile Floor deception.** Explorer sees Stone. Arcane sight
   sees Fragile Floor and marks hazard.
5. **Water LOS depth.** Vision blocked after `WATER_LOS_DEPTH`
   consecutive water cells.
6. **Door state transparency.** Open door is transparent, closed door
   is opaque. Verify after door state change with delta update.
7. **Perception range change.** Torch burning out triggers full
   recompute with reduced range.
8. **Teleportation.** Intruder pushed by water current > 1 cell
   triggers full recompute, not delta.
9. **Party vision pool.** Two intruders at same position get identical
   `PersonalMap` after vision update.
10. **Party vision pool with deception divergence.** Gloomwarden and
    Explorer at same position: Gloomwarden sees true Gold Bait,
    Explorer sees Treasure.
11. **Geometry change during tick.** Block destroyed while intruder is
    stationary (no `_vision_dirty`) -- verify cell is re-checked on
    next move via `_recently_changed_cells`.
12. **Arcane sight unaffected.** `compute_arcane_sight` returns same
    results as before (no caching or delta applied).
13. **Morale penalty.** New hazards discovered via delta update correctly
    apply `MORALE_HAZARD_PENALTY`.

### Benchmark

Add a vision-specific benchmark to `tests/benchmarks/`:

```python
def benchmark_vision_24_intruders():
    """Time _update_vision for 24 intruders over 200 ticks.

    Compare delta-enabled vs delta-disabled (VISION_DELTA_ENABLED flag).
    Compare pool-enabled vs pool-disabled (VISION_POOL_ENABLED flag).
    Report: total time, per-tick average, per-intruder average.
    """
```

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Delta produces incorrect visible set (LOS mismatch) | Intruders see cells they should not, or miss cells they should see | Extensive regression tests comparing delta vs full recompute on identical scenarios. Debug toggle `VISION_DELTA_ENABLED = False` to instantly revert. |
| Party pool shares visibility across deception boundary incorrectly | Deception leaks between arcane-sight and normal intruders | Pool only shares raw cell *positions*. Deception is always applied per-intruder from grid data, never shared. |
| Cache eviction too aggressive -- intruders stuck recomputing every tick | No performance gain | `VISION_CACHE_EVICTION_TICKS` is conservative (200 ticks = 10 seconds). Eviction only frees memory; it does not force recomputation. |
| Memory growth if changed-cell set is not cleared | Unbounded set growth over long games | Set is cleared at end of every tick. Size is bounded by the number of `set()` calls per tick, which is at most O(grid_size) and typically < 10. |
| Complexity of delta + pool makes debugging harder | Harder to trace vision bugs | Both features have independent disable flags. Logging at DEBUG level shows which path was taken (delta vs full, pool vs solo). |

---

## 12. Future Considerations

These are explicitly out of scope for this rework but worth noting:

1. **NumPy-vectorized ray-casting.** Replace the per-ray Python loop
   with batch Bresenham using NumPy integer arrays. Could yield another
   2-5x speedup, but requires significant refactoring of `compute_los`.
   Worth pursuing only if Phase 4 profiling shows vision is still a
   bottleneck.

2. **Hierarchical visibility (octree/BVH).** For very large grids
   (100x100x80+), a spatial hierarchy could skip entire empty regions.
   Current 50x50x40 grid does not warrant this.

3. **GPU-accelerated LOS.** Panda3D provides shader compute
   capabilities. A GPU LOS kernel could process all 24 intruders in
   parallel. Only worthwhile if the game scales to 50+ intruders or
   much larger grids.

4. **Auditory vision.** Intruders detecting events by sound (explosions,
   water flow, alarms) regardless of LOS. This would be a separate
   system layered on top of vision, not a modification of LOS.

5. **Ray template LUT.** Pre-compute Bresenham paths for all (dx, dy, dz)
   offsets within each perception range. Eliminates Bresenham arithmetic
   entirely at the cost of ~100 KB of stored tuples per range value.
   Mentioned in Phase 4; implement only if profiling warrants.
