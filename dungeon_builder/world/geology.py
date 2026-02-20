"""Procedural geology generation with realistic strata, ores, and a surface river."""

from __future__ import annotations

import math

import numpy as np

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_BEDROCK,
    VOXEL_CORE,
    VOXEL_STONE,
    VOXEL_DIRT,
    VOXEL_SANDSTONE,
    VOXEL_LIMESTONE,
    VOXEL_SHALE,
    VOXEL_CHALK,
    VOXEL_SLATE,
    VOXEL_MARBLE,
    VOXEL_GNEISS,
    VOXEL_GRANITE,
    VOXEL_BASALT,
    VOXEL_OBSIDIAN,
    VOXEL_IRON_ORE,
    VOXEL_COPPER_ORE,
    VOXEL_GOLD_ORE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_LAVA,
    VOXEL_WATER,
    VOXEL_WATER_SOURCE,
    VOXEL_WATER_SINK,
    VOXEL_LAVA_SOURCE,
    VOXEL_LAVA_SINK,
    VOXEL_POROSITY,
    LAVA_TEMPERATURE,
    MANA_CRYSTAL_TEMPERATURE,
    SURFACE_Z,
    TERRAIN_VARIATION_MAX,
    TERRAIN_NOISE_SCALE,
    RIVER_CHANNEL_DEPTH,
    CAVE_CORE_EXCLUSION,
    CORE_X,
    CORE_Y,
    CORE_Z,
)
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.world.voxel_grid import VoxelGrid


# ---------------------------------------------------------------------------
# Value noise (no external deps)
# ---------------------------------------------------------------------------

class ValueNoise2D:
    """Hash-based 2D value noise with smoothstep interpolation."""

    def __init__(self, seed: int, scale: float = 16.0) -> None:
        self.seed = seed
        self.scale = scale

    def _hash(self, ix: int, iy: int) -> float:
        """Deterministic hash from grid coords to [0, 1]."""
        # Combine seed with coords using large primes
        h = (ix * 374761393 + iy * 668265263 + self.seed * 1274126177) & 0xFFFFFFFF
        h = ((h ^ (h >> 13)) * 1103515245 + 12345) & 0xFFFFFFFF
        return (h & 0x7FFFFFFF) / 0x7FFFFFFF

    @staticmethod
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    def sample(self, x: float, y: float) -> float:
        """Sample noise at world position. Returns value in [0, 1]."""
        sx = x / self.scale
        sy = y / self.scale
        ix0 = int(math.floor(sx))
        iy0 = int(math.floor(sy))
        fx = sx - ix0
        fy = sy - iy0
        fx = self._smoothstep(fx)
        fy = self._smoothstep(fy)

        v00 = self._hash(ix0, iy0)
        v10 = self._hash(ix0 + 1, iy0)
        v01 = self._hash(ix0, iy0 + 1)
        v11 = self._hash(ix0 + 1, iy0 + 1)

        v0 = v00 + (v10 - v00) * fx
        v1 = v01 + (v11 - v01) * fx
        return v0 + (v1 - v0) * fy

    def fbm(self, x: float, y: float, octaves: int = 3) -> float:
        """Fractional Brownian Motion — layered noise for organic shapes."""
        value = 0.0
        amplitude = 1.0
        frequency = 1.0
        total_amp = 0.0
        for _ in range(octaves):
            value += self.sample(x * frequency, y * frequency) * amplitude
            total_amp += amplitude
            amplitude *= 0.5
            frequency *= 2.0
        return value / total_amp


# ---------------------------------------------------------------------------
# Geology generator
# ---------------------------------------------------------------------------

class GeologyGenerator:
    """Fills a VoxelGrid with geologically-inspired strata, ores, and rivers.

    Layer structure (by proportional depth, z=0 is surface, z=h-1 is bedrock):
      0.00:           Air (surface)
      0.00-0.10:      Dirt (topsoil, noise-varied thickness)
      0.10-0.30:      Sedimentary (sandstone, limestone, shale, chalk)
      0.30-0.55:      Metamorphic (slate, marble, gneiss)
      0.55-0.90:      Igneous (granite, basalt, rare obsidian)
      0.90-0.95:      Dense granite/basalt
      0.95-1.00:      Bedrock (indestructible)

    Adapts to any grid height — not all layers appear on shallow maps.
    """

    def __init__(self, rng: SeededRNG) -> None:
        self.rng = rng.fork("geology")

    def generate(self, voxel_grid: VoxelGrid) -> None:
        w, d, h = voxel_grid.width, voxel_grid.depth, voxel_grid.height
        grid = voxel_grid.grid

        # Noise layers for strata boundaries and variation
        strata_noise = ValueNoise2D(self.rng.randint(0, 2**31), scale=20.0)
        detail_noise = ValueNoise2D(self.rng.randint(0, 2**31), scale=10.0)
        ore_noise = ValueNoise2D(self.rng.randint(0, 2**31), scale=8.0)

        # --- Terrain heightmap with river path ---
        # 1) Generate base rolling hills.
        # 2) Plan the river path (follows low terrain naturally).
        # 3) Apply the heightmap to voxels.
        # 4) _generate_river() places water at terrain surface level.

        terrain_noise = ValueNoise2D(
            self.rng.randint(0, 2**31), scale=TERRAIN_NOISE_SCALE,
        )

        # Base heightmap: noise → hill height → z-level of topmost solid
        heightmap = np.empty((w, d), dtype=np.int32)
        for x in range(w):
            for y in range(d):
                n = terrain_noise.fbm(float(x), float(y), octaves=2)
                hill_frac = max(0.0, (n - 0.3) / 0.7)
                hill_height = int(round(hill_frac * TERRAIN_VARIATION_MAX))
                heightmap[x, y] = max(0, SURFACE_Z - hill_height)

        # Plan river path (follows low terrain naturally)
        river_path, river_channel = self._plan_river_path(w, d, heightmap)

        # ── Flatten terrain to river level along the channel ──────────
        # Compute river level along the path using a running max of
        # heightmap values (monotonically non-decreasing z = descending
        # altitude).  Set channel cells AND raise surrounding terrain
        # so the river has solid banks at every z-level it passes through.
        path_bed: dict[tuple[int, int], int] = {}
        running_z = int(heightmap[river_path[0][0], river_path[0][1]])
        for px, py in river_path:
            running_z = max(running_z, int(heightmap[px, py]))
            path_bed[(px, py)] = running_z

        # Assign river level to widened channel cells
        channel_bed: dict[tuple[int, int], int] = {}
        for rx, ry in river_channel:
            if (rx, ry) in path_bed:
                channel_bed[(rx, ry)] = path_bed[(rx, ry)]
            else:
                best_dist = float('inf')
                best_z = running_z
                for px, py in river_path:
                    dist = abs(rx - px) + abs(ry - py)
                    if dist < best_dist:
                        best_dist = dist
                        best_z = path_bed[(px, py)]
                channel_bed[(rx, ry)] = best_z

        # Force heightmap for channel cells to the deepened river level.
        # channel_bed holds the *surface* level; we add RIVER_CHANNEL_DEPTH
        # so the floor is carved deeper.  Bank neighbors stay at the
        # surface level → natural walls of height RIVER_CHANNEL_DEPTH.
        for rx, ry in river_channel:
            heightmap[rx, ry] = min(
                channel_bed[(rx, ry)] + RIVER_CHANNEL_DEPTH, h - 2
            )

        # Raise bank neighbors (non-channel cells adjacent to channel)
        # to match the river level so they form solid banks.
        for rx, ry in river_channel:
            river_z = channel_bed[(rx, ry)]
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                bx, by = rx + ddx, ry + ddy
                if 0 <= bx < w and 0 <= by < d and (bx, by) not in river_channel:
                    if heightmap[bx, by] > river_z:
                        heightmap[bx, by] = river_z

        # Apply heightmap to voxels: air above, dirt at/below surface
        grid[:, :, :SURFACE_Z + 1] = VOXEL_AIR
        for x in range(w):
            for y in range(d):
                top_z = int(heightmap[x, y])
                if top_z <= SURFACE_Z:
                    grid[x, y, top_z:SURFACE_Z + 1] = VOXEL_DIRT

        # Store heightmap
        voxel_grid.heightmap = heightmap
        # Store river path for _generate_river()
        voxel_grid._river_path = river_path  # type: ignore[attr-defined]
        voxel_grid._river_channel = river_channel  # type: ignore[attr-defined]
        # Store original surface-level bed for full-depth carving
        voxel_grid._channel_bed = channel_bed  # type: ignore[attr-defined]

        # --- Fill each column based on proportional depth + noise ---
        # depth_ratio is 0.0 at SURFACE_Z+1 (just below ground) and 1.0 at deepest
        underground_depth = max(h - 1 - SURFACE_Z, 1)
        for x in range(w):
            for y in range(d):
                n = strata_noise.fbm(float(x), float(y), octaves=3)
                d2 = detail_noise.fbm(float(x), float(y), octaves=2)
                # Noise offset as proportion of total depth (±5%)
                offset = (n - 0.5) * 0.10

                for z in range(SURFACE_Z + 1, h):
                    depth_ratio = (z - SURFACE_Z) / underground_depth
                    vtype = self._pick_rock_type(depth_ratio, offset, d2)
                    grid[x, y, z] = vtype

        # --- Bedrock floor (last layer always bedrock) ---
        grid[:, :, h - 1] = VOXEL_BEDROCK

        # --- Ore deposits ---
        self._place_ores(voxel_grid, ore_noise)

        # --- Natural caves ---
        self._carve_caves(voxel_grid)

        # --- Surface river ---
        self._generate_river(voxel_grid)

        # --- Lava river (deep) ---
        self._generate_lava_river(voxel_grid)

        # --- Humidity ---
        self._initialize_humidity(voxel_grid)

        # --- Temperature ---
        self._initialize_temperature(voxel_grid)

    def _pick_rock_type(self, depth_ratio: float, offset: float, detail: float) -> int:
        """Choose voxel type for a given proportional depth, with noise variation.

        depth_ratio: 0.0 = surface, 1.0 = deepest.
        offset: noise-based shift (±0.05).
        detail: secondary noise value in [0, 1].
        """
        eff = depth_ratio + offset

        # Dirt layer (0.00-0.10)
        if eff < 0.10 + detail * 0.02:
            return VOXEL_DIRT

        # Sedimentary zone (0.10-0.30)
        if eff < 0.30 + detail * 0.02:
            band = (eff - 0.10) / 0.20  # 0..1 through the zone
            if band < 0.3:
                return VOXEL_SANDSTONE
            elif band < 0.55:
                return VOXEL_LIMESTONE
            elif band < 0.75:
                return VOXEL_CHALK if detail > 0.5 else VOXEL_SANDSTONE
            else:
                return VOXEL_SHALE

        # Metamorphic zone (0.30-0.55)
        if eff < 0.55 + detail * 0.02:
            band = (eff - 0.30) / 0.25
            if band < 0.35:
                return VOXEL_SLATE
            elif band < 0.65:
                return VOXEL_MARBLE if detail > 0.6 else VOXEL_GNEISS
            else:
                return VOXEL_GNEISS

        # Igneous zone (0.55-0.90)
        if eff < 0.90:
            band = (eff - 0.55) / 0.35
            if detail > 0.85 and eff > 0.75:
                return VOXEL_OBSIDIAN
            elif band < 0.5:
                return VOXEL_GRANITE
            else:
                return VOXEL_BASALT

        # Dense zone (0.90-0.95)
        if eff < 0.95:
            return VOXEL_BASALT if detail > 0.5 else VOXEL_GRANITE

        return VOXEL_BEDROCK

    # -------------------------------------------------------------------
    # Ore placement
    # -------------------------------------------------------------------

    def _place_ores(self, voxel_grid: VoxelGrid, ore_noise: ValueNoise2D) -> None:
        """Scatter ore clusters at geologically appropriate depths."""
        w, d, h = voxel_grid.width, voxel_grid.depth, voxel_grid.height
        # Ore depth ratios are relative to underground range only
        max_z = max(h - 1 - SURFACE_Z, 1)

        # (ore_type, min_ratio, max_ratio, cluster_count, cluster_size_range)
        ore_defs = [
            (VOXEL_IRON_ORE, 0.10, 0.50, 12, (3, 7)),     # iron in sedimentary/metamorphic
            (VOXEL_COPPER_ORE, 0.30, 0.65, 10, (3, 6)),    # copper in metamorphic
            (VOXEL_GOLD_ORE, 0.55, 0.90, 6, (2, 5)),       # gold in igneous
            (VOXEL_MANA_CRYSTAL, 0.70, 0.95, 4, (2, 4)),   # mana crystals deep
        ]

        for ore_type, r_min, r_max, count, (sz_min, sz_max) in ore_defs:
            z_min = max(SURFACE_Z + 1, SURFACE_Z + int(r_min * max_z))
            z_max = min(h - 2, SURFACE_Z + int(r_max * max_z))
            if z_min >= z_max:
                continue
            for _ in range(count):
                cx = self.rng.randint(4, w - 4)
                cy = self.rng.randint(4, d - 4)
                cz = self.rng.randint(z_min, z_max)
                size = self.rng.randint(sz_min, sz_max)
                self._place_ore_cluster(voxel_grid, ore_type, cx, cy, cz, size)

    def _place_ore_cluster(
        self, voxel_grid: VoxelGrid, ore_type: int,
        cx: int, cy: int, cz: int, size: int,
    ) -> None:
        """Place a small irregular cluster of ore voxels."""
        grid = voxel_grid.grid
        placed = 0
        x, y, z = cx, cy, cz
        for _ in range(size * 3):  # attempts
            if placed >= size:
                break
            if voxel_grid.in_bounds(x, y, z):
                current = int(grid[x, y, z])
                # Only replace solid rock, not air/bedrock/core/other ores/lava
                if current not in (VOXEL_AIR, VOXEL_BEDROCK, VOXEL_CORE, VOXEL_LAVA) and current < 40:
                    grid[x, y, z] = ore_type
                    placed += 1
            # Random walk to next position
            direction = self.rng.randint(0, 5)
            if direction == 0: x += 1
            elif direction == 1: x -= 1
            elif direction == 2: y += 1
            elif direction == 3: y -= 1
            elif direction == 4: z += 1
            else: z -= 1

    # -------------------------------------------------------------------
    # Cave carving
    # -------------------------------------------------------------------

    def _carve_caves(self, voxel_grid: VoxelGrid) -> None:
        """Carve a few small natural caverns.

        Caves are excluded from a Chebyshev-distance zone around
        (CORE_X, CORE_Y) so they don't undermine the core room,
        shaft, or corridor.
        """
        h = voxel_grid.height
        underground = h - 1 - SURFACE_Z
        num_caves = self.rng.randint(3, 8)
        for _ in range(num_caves):
            cx = self.rng.randint(8, voxel_grid.width - 8)
            cy = self.rng.randint(8, voxel_grid.depth - 8)
            # Caves in the 30-80% of underground depth range
            cz = self.rng.randint(
                max(SURFACE_Z + 2, SURFACE_Z + int(0.30 * underground)),
                max(SURFACE_Z + 3, SURFACE_Z + int(0.80 * underground)),
            )
            radius = self.rng.randint(2, 4)
            # Skip caves too close to the core room / dungeon entrance.
            # Account for radius so the sphere doesn't overlap the core.
            exclusion = CAVE_CORE_EXCLUSION + radius
            if (abs(cx - CORE_X) < exclusion
                    and abs(cy - CORE_Y) < exclusion):
                continue
            self._carve_sphere(voxel_grid, cx, cy, cz, radius)

    def _carve_sphere(
        self, voxel_grid: VoxelGrid, cx: int, cy: int, cz: int, radius: int,
    ) -> None:
        """Carve a roughly spherical air pocket."""
        for x in range(cx - radius, cx + radius + 1):
            for y in range(cy - radius, cy + radius + 1):
                for z in range(cz - radius, cz + radius + 1):
                    if not voxel_grid.in_bounds(x, y, z):
                        continue
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2)
                    if dist < radius + self.rng.uniform(-0.5, 0.5):
                        if voxel_grid.grid[x, y, z] not in (VOXEL_BEDROCK, VOXEL_LAVA):
                            voxel_grid.grid[x, y, z] = VOXEL_AIR

    # -------------------------------------------------------------------
    # River path planning (used by terrain heightmap generation)
    # -------------------------------------------------------------------

    def _plan_river_path(
        self, w: int, d: int, heightmap: np.ndarray,
    ) -> tuple[list[tuple[int, int]], set[tuple[int, int]]]:
        """Plan a meandering river path from one edge to the opposite.

        Returns (path, channel) where path is the ordered center-line
        and channel is the widened set of (x, y) cells.  The path
        follows low terrain naturally (scoring favors lower heightmap
        values), so the river sits in valleys without needing to modify
        the heightmap.
        """
        # Pick random source and sink edges (must be different).
        edges = ["x0", "xw", "y0", "yd"]
        self.rng.shuffle(edges)
        source_edge = edges[0]
        sink_edge = edges[1]

        # Random position along the source edge
        margin = 3  # stay a few cells from corners
        if source_edge == "x0":
            src_y = self.rng.randint(margin, max(margin, d - 1 - margin))
            src_x = 0
        elif source_edge == "xw":
            src_y = self.rng.randint(margin, max(margin, d - 1 - margin))
            src_x = w - 1
        elif source_edge == "y0":
            src_x = self.rng.randint(margin, max(margin, w - 1 - margin))
            src_y = 0
        else:
            src_x = self.rng.randint(margin, max(margin, w - 1 - margin))
            src_y = d - 1

        # Random position along the sink edge → path biases toward it
        if sink_edge == "x0":
            tgt_y = self.rng.randint(margin, max(margin, d - 1 - margin))
            tgt_x = 0
        elif sink_edge == "xw":
            tgt_y = self.rng.randint(margin, max(margin, d - 1 - margin))
            tgt_x = w - 1
        elif sink_edge == "y0":
            tgt_x = self.rng.randint(margin, max(margin, w - 1 - margin))
            tgt_y = 0
        else:
            tgt_x = self.rng.randint(margin, max(margin, w - 1 - margin))
            tgt_y = d - 1

        # Dungeon entrance exclusion: keep the river path away from the
        # entrance shaft so water doesn't flood the dungeon.  The shaft is
        # at (CORE_X..CORE_X+1, 0..1); we use a generous minimum distance
        # so the widened channel (±2) also stays clear.
        _ENTRANCE_MIN_DIST = 5  # Chebyshev distance from entrance center
        _entrance_cx = CORE_X + 0.5
        _entrance_cy = 0.5
        _ENTRANCE_PENALTY = -20.0  # strong penalty for cells too close

        # Trace center-line from source toward target on sink edge
        path: list[tuple[int, int]] = [(src_x, src_y)]
        visited: set[tuple[int, int]] = {(src_x, src_y)}
        cx, cy = src_x, src_y

        src_edges: set[str] = set()
        if src_x == 0:      src_edges.add("x0")
        if src_x == w - 1:  src_edges.add("xw")
        if src_y == 0:      src_edges.add("y0")
        if src_y == d - 1:  src_edges.add("yd")

        for _ in range(w + d + 40):
            best, best_score = None, float('-inf')
            # Distance from current cell to target (for bias normalisation)
            dist_to_tgt = max(abs(tgt_x - cx) + abs(tgt_y - cy), 1)
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < d):
                    continue
                if (nx, ny) in visited:
                    continue
                # Score: prefer downhill (higher heightmap = lower terrain)
                # plus bias toward the target point on the sink edge,
                # plus meander noise.
                # Bias: positive when step reduces Manhattan distance to target.
                old_dist = abs(tgt_x - cx) + abs(tgt_y - cy)
                new_dist = abs(tgt_x - nx) + abs(tgt_y - ny)
                toward_tgt = (old_dist - new_dist)  # +1 if closer, -1 if farther
                score = (
                    float(heightmap[nx, ny])
                    + toward_tgt * 0.8  # bias toward target
                    + self.rng.uniform(-0.5, 0.5)
                )
                # Penalise cells near the dungeon entrance
                ent_dist = max(abs(nx - _entrance_cx), abs(ny - _entrance_cy))
                if ent_dist < _ENTRANCE_MIN_DIST:
                    score += _ENTRANCE_PENALTY
                if score > best_score:
                    best_score, best = score, (nx, ny)

            if best is None:
                break

            cx, cy = best
            path.append((cx, cy))
            visited.add((cx, cy))

            # Stop at a non-source edge
            cell_edges: set[str] = set()
            if cx == 0:      cell_edges.add("x0")
            if cx == w - 1:  cell_edges.add("xw")
            if cy == 0:      cell_edges.add("y0")
            if cy == d - 1:  cell_edges.add("yd")
            if cell_edges and not cell_edges.issubset(src_edges):
                break

        # Widen path to 2-3 block channel
        channel: set[tuple[int, int]] = set()
        for px, py in path:
            hw = self.rng.choice([1, 1, 1, 2])
            for dx in range(-hw, hw + 1):
                for dy in range(-hw, hw + 1):
                    rx, ry = px + dx, py + dy
                    if 0 <= rx < w and 0 <= ry < d:
                        channel.add((rx, ry))

        return path, channel

    # -------------------------------------------------------------------
    # Surface river generation
    # -------------------------------------------------------------------

    def _generate_river(self, voxel_grid: VoxelGrid) -> None:
        """Place source and sink along the pre-planned river channel.

        The heightmap has already been flattened to match the river level
        for channel cells and their banks (done in generate() before the
        heightmap is applied to voxels).  Each channel cell is air at the
        river bed level.

        The channel is left empty — water flows naturally from source to
        sink via the fluid physics system (gravity + lateral leveling).

        Source at the high end (path start), sink 1 block below the
        deepest river bed so water always drains toward the exit.
        """
        if voxel_grid.height <= SURFACE_Z:
            voxel_grid._river_cells = set()  # type: ignore[attr-defined]
            voxel_grid._river_bed_z = {}  # type: ignore[attr-defined]
            return

        w, d, h = voxel_grid.width, voxel_grid.depth, voxel_grid.height
        grid = voxel_grid.grid
        heightmap = voxel_grid.heightmap
        river_path = getattr(voxel_grid, '_river_path', None)
        river_channel = getattr(voxel_grid, '_river_channel', None)
        channel_bed = getattr(voxel_grid, '_channel_bed', None)

        if heightmap is None or river_path is None or not river_channel:
            voxel_grid._river_cells = set()  # type: ignore[attr-defined]
            voxel_grid._river_bed_z = {}  # type: ignore[attr-defined]
            return

        river_cells: set[tuple[int, int]] = set()
        river_bed_z: dict[tuple[int, int], int] = {}
        deepest_bed = 0

        for rx, ry in river_channel:
            bed_z = int(heightmap[rx, ry])
            # Carve the full channel depth: from the original surface
            # level down to the deepened floor.  The strata loop fills
            # everything from SURFACE_Z+1 downward with rock, so we
            # must explicitly carve the channel interior to air.
            surface_z = channel_bed[(rx, ry)] if channel_bed else bed_z
            for z in range(surface_z, bed_z + 1):
                if voxel_grid.in_bounds(rx, ry, z):
                    if grid[rx, ry, z] != VOXEL_AIR:
                        grid[rx, ry, z] = VOXEL_AIR
            river_cells.add((rx, ry))
            river_bed_z[(rx, ry)] = bed_z
            if bed_z > deepest_bed:
                deepest_bed = bed_z

        # ── Source segment at path start (3-6 cells along the edge) ───
        # Find channel cells near the first few path cells — these become
        # water sources so the river has a visible, wide origin.
        src_x, src_y = river_path[0]
        src_head = set(river_path[:6])  # first ~6 path cells
        source_cells: list[tuple[int, int, int]] = []
        for rx, ry in river_channel:
            if (rx, ry) in src_head or any(
                abs(rx - px) + abs(ry - py) <= 1
                for px, py in src_head
            ):
                bz = river_bed_z.get((rx, ry))
                if bz is not None:
                    source_cells.append((rx, ry, bz))
        # Limit to 3-6 cells (prefer cells closest to the path start)
        source_cells.sort(
            key=lambda c: abs(c[0] - src_x) + abs(c[1] - src_y)
        )
        source_cells = source_cells[:6]
        if len(source_cells) < 3:
            # Fallback: at least the path start itself
            bz = river_bed_z.get((src_x, src_y), SURFACE_Z)
            source_cells = [(src_x, src_y, bz)]
        for sx, sy, sz in source_cells:
            # Place source one z-level above the channel floor so water
            # fills the channel depth.  Sources fill all 6 adjacent air
            # cells (including upward), creating head pressure that
            # pushes water through the channel.
            elevated_z = max(sz - 1, 0)
            if grid[sx, sy, elevated_z] != VOXEL_AIR:
                grid[sx, sy, elevated_z] = VOXEL_AIR
            grid[sx, sy, elevated_z] = VOXEL_WATER_SOURCE

        # ── Sink segment at path end (3-6 cells, 1 below deepest bed) ─
        sink_x, sink_y = river_path[-1]
        sink_tail = set(river_path[-6:])  # last ~6 path cells
        sink_candidates: list[tuple[int, int]] = []
        for rx, ry in river_channel:
            if (rx, ry) in sink_tail or any(
                abs(rx - px) + abs(ry - py) <= 1
                for px, py in sink_tail
            ):
                sink_candidates.append((rx, ry))
        sink_candidates.sort(
            key=lambda c: abs(c[0] - sink_x) + abs(c[1] - sink_y)
        )
        sink_candidates = sink_candidates[:6]
        if len(sink_candidates) < 3:
            sink_candidates = [(sink_x, sink_y)]
        sink_z = min(deepest_bed + 1, h - 2)
        # Types already strong enough — don't overwrite these.
        _STRONG_SINK = frozenset((
            VOXEL_AIR, VOXEL_STONE, VOXEL_BEDROCK, VOXEL_CORE,
            VOXEL_WATER_SOURCE, VOXEL_WATER_SINK,
            VOXEL_LAVA_SOURCE, VOXEL_LAVA_SINK,
            VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN,
        ))
        for kx, ky in sink_candidates:
            grid[kx, ky, sink_z] = VOXEL_WATER_SINK
            voxel_grid.water_level[kx, ky, sink_z] = 0
            river_bed_z[(kx, ky)] = sink_z
            # Reinforce neighbors so weak material doesn't collapse
            # and bury the sink during pre-stabilization.
            for ddx, ddy, ddz in [
                (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0),
                (0, 0, 1),  # below
            ]:
                nx, ny, nz = kx + ddx, ky + ddy, sink_z + ddz
                if voxel_grid.in_bounds(nx, ny, nz):
                    if grid[nx, ny, nz] not in _STRONG_SINK:
                        grid[nx, ny, nz] = VOXEL_STONE

        # ── Store metadata ────────────────────────────────────────────
        voxel_grid._river_cells = river_cells  # type: ignore[attr-defined]
        voxel_grid._river_bed_z = river_bed_z  # type: ignore[attr-defined]

    # -------------------------------------------------------------------
    # Lava river generation (deep)
    # -------------------------------------------------------------------

    def _generate_lava_river(self, voxel_grid: VoxelGrid) -> None:
        """Generate an inclined lava river at 80-90% depth with source/sink.

        The river flows north-to-south (y=0 to y=d-1).  Source end (y=0)
        sits 3 blocks higher than sink end (y=d-1).  A cluster of up to 6
        VOXEL_LAVA_SOURCE cells at the head pumps heat into the river,
        while VOXEL_LAVA_SINK at the tail absorbs lava and resets it to
        ambient temperature.
        """
        w, d, h = voxel_grid.width, voxel_grid.depth, voxel_grid.height
        grid = voxel_grid.grid

        underground = h - 1 - SURFACE_Z
        if underground < 5:
            return  # too shallow for lava

        # Lava river z-level: ~85% of underground depth
        # Use SURFACE_Z + 4 minimum so the tunnel (bed_z - 1) has ≥2 blocks
        # of solid rock above it for structural integrity.
        sink_z = max(SURFACE_Z + 4, SURFACE_Z + int(0.85 * underground))
        if sink_z >= h - 1:
            sink_z = h - 2  # don't overwrite bedrock
        # Source is 3 blocks higher (shallower) than sink — steeper slope
        # drives faster lava convection, keeping the river hot end-to-end
        source_z = max(SURFACE_Z + 4, sink_z - 3)

        # River flows roughly north-to-south (y=0 to y=d-1)
        third = w // 3
        start_x = self.rng.randint(third, 2 * third)
        end_x = self.rng.randint(third, 2 * third)

        num_waypoints = 5
        waypoints: list[tuple[float, float]] = [(float(start_x), 0.0)]
        for i in range(1, num_waypoints):
            t = i / num_waypoints
            base_y = t * (d - 1)
            base_x = start_x + t * (end_x - start_x)
            deviation = self.rng.uniform(-6.0, 6.0)
            waypoints.append((base_x + deviation, base_y))
        waypoints.append((float(end_x), float(d - 1)))

        # Interpolate path — track per-cell bed z-level for incline
        lava_cells: set[tuple[int, int]] = set()
        lava_bed_z: dict[tuple[int, int], int] = {}
        for i in range(len(waypoints) - 1):
            x0, y0 = waypoints[i]
            x1, y1 = waypoints[i + 1]
            steps = int(max(abs(x1 - x0), abs(y1 - y0))) * 2 + 1
            for s in range(steps + 1):
                t = s / max(steps, 1)
                px = x0 + (x1 - x0) * t
                py = y0 + (y1 - y0) * t
                ix, iy = int(round(px)), int(round(py))
                # Progress along river (0 at source y=0, 1 at sink y=d-1)
                global_t = iy / max(d - 1, 1)
                bed_z = source_z + int(global_t * (sink_z - source_z))
                # Lava channel width: 2-3 blocks (wide Mustafar-style river)
                half_w = self.rng.choice([2, 2, 2, 3])
                for dx in range(-half_w, half_w + 1):
                    for dy in range(-half_w, half_w + 1):
                        rx, ry = ix + dx, iy + dy
                        if 0 <= rx < w and 0 <= ry < d:
                            lava_cells.add((rx, ry))
                            # Keep the deepest bed_z for each cell
                            prev = lava_bed_z.get((rx, ry), -1)
                            if bed_z > prev:
                                lava_bed_z[(rx, ry)] = bed_z

        # Place lava voxels at their bed z-level and carve tunnel above
        for rx, ry in lava_cells:
            bed_z = lava_bed_z.get((rx, ry), sink_z)
            if voxel_grid.in_bounds(rx, ry, bed_z):
                current = int(grid[rx, ry, bed_z])
                if current != VOXEL_BEDROCK:
                    grid[rx, ry, bed_z] = VOXEL_LAVA
                    voxel_grid.lava_level[rx, ry, bed_z] = 255
            # Carve 1-block-high air tunnel above lava (ceiling stays solid)
            tunnel_z = bed_z - 1
            if voxel_grid.in_bounds(rx, ry, tunnel_z):
                current = int(grid[rx, ry, tunnel_z])
                if current not in (VOXEL_BEDROCK, VOXEL_LAVA):
                    grid[rx, ry, tunnel_z] = VOXEL_AIR

        # Place LAVA_SOURCE cluster at river head (y ≤ 2, up to 6 cells).
        # Multiple sources pump more heat into the river, keeping it hot.
        src_candidates = sorted(
            [(rx, ry) for rx, ry in lava_cells if ry <= 2],
            key=lambda c: c[1],  # prefer cells closest to y=0
        )[:6]
        if not src_candidates:
            # Fallback: any cell at minimum y
            min_y = min(ry for _, ry in lava_cells)
            src_candidates = [(rx, ry) for rx, ry in lava_cells if ry == min_y][:3]
        for rx, ry in src_candidates:
            bed_z = lava_bed_z.get((rx, ry), source_z)
            if voxel_grid.in_bounds(rx, ry, bed_z):
                grid[rx, ry, bed_z] = VOXEL_LAVA_SOURCE

        # Place LAVA_SINK at y=d-1 edge
        for rx, ry in lava_cells:
            if ry == d - 1:
                bed_z = lava_bed_z.get((rx, ry), sink_z)
                if voxel_grid.in_bounds(rx, ry, bed_z):
                    grid[rx, ry, bed_z] = VOXEL_LAVA_SINK

        # Store for temperature initialization
        voxel_grid._lava_cells = lava_cells  # type: ignore[attr-defined]
        voxel_grid._lava_z = sink_z  # type: ignore[attr-defined]
        voxel_grid._lava_bed_z = lava_bed_z  # type: ignore[attr-defined]

    # -------------------------------------------------------------------
    # Humidity initialization
    # -------------------------------------------------------------------

    def _initialize_humidity(self, voxel_grid: VoxelGrid) -> None:
        """Set initial humidity: river=1.0, gradient near river, depth-based baseline."""
        w, d, h = voxel_grid.width, voxel_grid.depth, voxel_grid.height
        humidity = voxel_grid.humidity
        grid = voxel_grid.grid

        # Baseline humidity: increases with depth (below SURFACE_Z) and porosity
        underground_depth = max(h - 1 - SURFACE_Z, 1)
        for z in range(h):
            if z <= SURFACE_Z:
                depth_factor = 0.0  # sky/surface: minimal baseline
            else:
                depth_factor = (z - SURFACE_Z) / underground_depth
            base_humidity = 0.05 + depth_factor * 0.25  # 0.05..0.30
            for x in range(w):
                for y in range(d):
                    vtype = int(grid[x, y, z])
                    porosity = VOXEL_POROSITY.get(vtype, 0.0)
                    # Porous rock retains more moisture
                    humidity[x, y, z] = base_humidity * porosity

        # River channel: max humidity at per-cell bed z-level
        river_cells = getattr(voxel_grid, '_river_cells', set())
        river_bed_z = getattr(voxel_grid, '_river_bed_z', {})
        for rx, ry in river_cells:
            bed_z = river_bed_z.get((rx, ry), SURFACE_Z)
            for z in (bed_z, min(bed_z + 1, h - 1)):
                humidity[rx, ry, z] = 1.0

        # Propagate humidity gradient around river
        max_spread = 5
        for rx, ry in river_cells:
            bed_z = river_bed_z.get((rx, ry), SURFACE_Z)
            for dx in range(-max_spread, max_spread + 1):
                for dy in range(-max_spread, max_spread + 1):
                    nx, ny = rx + dx, ry + dy
                    if not (0 <= nx < w and 0 <= ny < d):
                        continue
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist < 1.0:
                        continue
                    # Humidity falls off with distance, scaled by porosity
                    for z in range(bed_z, min(bed_z + 4, h)):
                        vtype = int(grid[nx, ny, z])
                        porosity = VOXEL_POROSITY.get(vtype, 0.0)
                        falloff = max(0.0, 1.0 - dist / max_spread) * porosity
                        if falloff > humidity[nx, ny, z]:
                            humidity[nx, ny, z] = falloff

    # -------------------------------------------------------------------
    # Temperature initialization
    # -------------------------------------------------------------------

    def _initialize_temperature(self, voxel_grid: VoxelGrid) -> None:
        """Set initial temperature: baseline increases with depth, lava=hot, mana=fixed."""
        w, d, h = voxel_grid.width, voxel_grid.depth, voxel_grid.height
        temperature = voxel_grid.temperature
        grid = voxel_grid.grid

        # Baseline: 20 at surface/sky, increases with underground depth
        underground_depth = max(h - 1 - SURFACE_Z, 1)
        for z in range(h):
            if z <= SURFACE_Z:
                depth_factor = 0.0
            else:
                depth_factor = (z - SURFACE_Z) / underground_depth
            base_temp = 20.0 + depth_factor * 80.0
            for x in range(w):
                for y in range(d):
                    temperature[x, y, z] = base_temp

        # Lava / lava source: fixed high temperature; mana crystal: fixed low
        for x in range(w):
            for y in range(d):
                for z in range(h):
                    vtype = int(grid[x, y, z])
                    if vtype in (VOXEL_LAVA, VOXEL_LAVA_SOURCE):
                        temperature[x, y, z] = LAVA_TEMPERATURE
                    elif vtype == VOXEL_MANA_CRYSTAL:
                        temperature[x, y, z] = MANA_CRYSTAL_TEMPERATURE
