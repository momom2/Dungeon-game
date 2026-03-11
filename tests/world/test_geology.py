"""Tests for geology generation."""

import numpy as np

from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.geology import GeologyGenerator
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_BEDROCK,
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
    LAVA_TEMPERATURE,
    MANA_CRYSTAL_TEMPERATURE,
    SURFACE_Z,
    TERRAIN_VARIATION_MAX,
    RIVER_CHANNEL_DEPTH,
    CAVE_CORE_EXCLUSION,
    CORE_X,
    CORE_Y,
)

SEDIMENTARY = {VOXEL_SANDSTONE, VOXEL_LIMESTONE, VOXEL_SHALE, VOXEL_CHALK}
METAMORPHIC = {VOXEL_SLATE, VOXEL_MARBLE, VOXEL_GNEISS}
IGNEOUS = {VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN}
ORES = {VOXEL_IRON_ORE, VOXEL_COPPER_ORE, VOXEL_GOLD_ORE, VOXEL_MANA_CRYSTAL}


def _make_grid(seed: int = 42, height: int = 21) -> VoxelGrid:
    grid = VoxelGrid(height=height)
    GeologyGenerator(SeededRNG(seed)).generate(grid)
    return grid


def test_surface_is_air():
    grid = _make_grid()
    for x in range(grid.width):
        for y in range(grid.depth):
            assert grid.get(x, y, 0) == VOXEL_AIR


def test_bedrock_floor():
    grid = _make_grid()
    h = grid.height
    for x in range(grid.width):
        for y in range(grid.depth):
            assert grid.get(x, y, h - 1) == VOXEL_BEDROCK


def test_bedrock_floor_varying_heights():
    """Bedrock is always the last layer regardless of height."""
    # Heights must be > SURFACE_Z + 1 to have underground layers
    for height in [10, 15, 21, 30]:
        grid = _make_grid(height=height)
        for x in range(grid.width):
            for y in range(grid.depth):
                assert grid.get(x, y, height - 1) == VOXEL_BEDROCK


def test_deterministic():
    grid1 = _make_grid(42)
    grid2 = _make_grid(42)
    assert (grid1.grid == grid2.grid).all()
    assert (grid1.humidity == grid2.humidity).all()
    assert (grid1.temperature == grid2.temperature).all()


def test_different_seeds_differ():
    grid1 = _make_grid(42)
    grid2 = _make_grid(99)
    assert not (grid1.grid == grid2.grid).all()


def test_shallow_layers_mostly_dirt():
    grid = _make_grid()
    h = grid.height
    # Just below surface should be mostly dirt (river carves some to air)
    underground_depth = h - 1 - SURFACE_Z
    dirt_z = SURFACE_Z + max(1, int(0.05 * underground_depth))  # near top of underground
    layer = grid.grid[:, :, dirt_z]
    dirt_count = np.sum(layer == VOXEL_DIRT)
    air_count = np.sum(layer == VOXEL_AIR)  # river riverbed
    total = layer.size
    assert (dirt_count + air_count) / total > 0.8


def test_deep_layers_mostly_igneous():
    grid = _make_grid()
    h = grid.height
    underground_depth = h - 1 - SURFACE_Z
    # ~70% underground depth should be mostly igneous rock or ores or air from caves
    deep_z = SURFACE_Z + int(0.70 * underground_depth)
    layer = grid.grid[:, :, deep_z]
    igneous_count = sum(np.sum(layer == v) for v in IGNEOUS)
    ore_count = sum(np.sum(layer == v) for v in ORES)
    air_count = np.sum(layer == VOXEL_AIR)
    total = layer.size
    assert (igneous_count + ore_count + air_count) / total > 0.80


def test_geological_progression():
    """Verify sedimentary is above metamorphic is above igneous."""
    grid = _make_grid()
    h = grid.height
    underground_depth = h - 1 - SURFACE_Z

    def dominant_class(z: int) -> str:
        layer = grid.grid[:, :, z]
        sed = sum(int(np.sum(layer == v)) for v in SEDIMENTARY)
        met = sum(int(np.sum(layer == v)) for v in METAMORPHIC)
        ign = sum(int(np.sum(layer == v)) for v in IGNEOUS)
        if sed >= met and sed >= ign:
            return "sedimentary"
        if met >= ign:
            return "metamorphic"
        return "igneous"

    # Proportional checks relative to underground depth
    sed_z = SURFACE_Z + int(0.20 * underground_depth)
    met_z = SURFACE_Z + int(0.42 * underground_depth)
    ign_z = SURFACE_Z + int(0.70 * underground_depth)
    assert dominant_class(sed_z) == "sedimentary"
    assert dominant_class(met_z) == "metamorphic"
    assert dominant_class(ign_z) == "igneous"


def test_geological_progression_tall_map():
    """Geological layers work on a taller map too."""
    grid = _make_grid(seed=42, height=30)
    h = grid.height
    underground_depth = h - 1 - SURFACE_Z

    def dominant_class(z: int) -> str:
        layer = grid.grid[:, :, z]
        sed = sum(int(np.sum(layer == v)) for v in SEDIMENTARY)
        met = sum(int(np.sum(layer == v)) for v in METAMORPHIC)
        ign = sum(int(np.sum(layer == v)) for v in IGNEOUS)
        if sed >= met and sed >= ign:
            return "sedimentary"
        if met >= ign:
            return "metamorphic"
        return "igneous"

    sed_z = SURFACE_Z + int(0.20 * underground_depth)
    met_z = SURFACE_Z + int(0.42 * underground_depth)
    ign_z = SURFACE_Z + int(0.70 * underground_depth)
    assert dominant_class(sed_z) == "sedimentary"
    assert dominant_class(met_z) == "metamorphic"
    assert dominant_class(ign_z) == "igneous"


def test_river_channel():
    """River at SURFACE_Z with source/sink, contained by terrain banks."""
    grid = _make_grid()
    river_cells = getattr(grid, '_river_cells', set())
    river_bed_z = getattr(grid, '_river_bed_z', {})
    river_path = getattr(grid, '_river_path', [])
    assert len(river_cells) > 20, "River should have significant coverage"
    # Source and sink are on opposite edges, so the path must cross at
    # least half the map dimension.
    min_span = min(grid.width, grid.depth) // 2
    assert len(river_path) > min_span, (
        f"River path should span at least half the map ({min_span} cells), "
        f"got {len(river_path)}"
    )

    # All river cells should be at SURFACE_Z
    water_types = {VOXEL_WATER, VOXEL_WATER_SOURCE, VOXEL_WATER_SINK}
    water_count = 0
    for rx, ry in river_cells:
        bed_z = river_bed_z.get((rx, ry), SURFACE_Z)
        vtype = grid.get(rx, ry, bed_z)
        # Bed z should be water, source, or sink
        assert vtype in (VOXEL_AIR, *water_types), (
            f"River cell ({rx},{ry}) at bed z={bed_z} should be air or water, "
            f"got type {vtype}"
        )
        if vtype in water_types:
            water_count += 1

    assert water_count > 5, "River should have water voxels"

    # Source at path start (elevated 1 above channel floor), sink at path end
    src_x, src_y = river_path[0]
    src_bed = river_bed_z.get((src_x, src_y), SURFACE_Z)
    src_elevated = max(src_bed - 1, 0)
    assert grid.get(src_x, src_y, src_elevated) == VOXEL_WATER_SOURCE, (
        f"Source should be at path start ({src_x},{src_y},{src_elevated})"
    )

    end_x, end_y = river_path[-1]
    end_bed = river_bed_z.get((end_x, end_y), SURFACE_Z)
    assert grid.get(end_x, end_y, end_bed) == VOXEL_WATER_SINK, (
        f"Sink should be at path end ({end_x},{end_y},{end_bed})"
    )

    # Source and sink should be on map edges
    w, d = grid.width, grid.depth
    assert src_x == 0 or src_x == w - 1 or src_y == 0 or src_y == d - 1, \
        "Source should be on a map edge"
    assert end_x == 0 or end_x == w - 1 or end_y == 0 or end_y == d - 1, \
        "Sink should be on a map edge"


def test_terrain_varies():
    """Terrain heightmap should have variation (not flat)."""
    grid = _make_grid()
    heightmap = grid.heightmap
    assert heightmap is not None, "Heightmap should be stored on voxel_grid"
    unique_heights = np.unique(heightmap)
    assert len(unique_heights) >= 2, "Terrain should have multiple height levels"
    # All heights within valid range
    # River channel cells can be up to RIVER_CHANNEL_DEPTH below SURFACE_Z
    # (higher z value = deeper in inverted coordinate system)
    assert heightmap.min() >= 0
    assert heightmap.max() <= SURFACE_Z + RIVER_CHANNEL_DEPTH


def test_terrain_has_dirt_hills():
    """Hill columns should have dirt at the top, air above."""
    grid = _make_grid()
    heightmap = grid.heightmap
    river_channel = getattr(grid, '_river_channel', set())
    assert heightmap is not None

    # Find a hill column NOT in the river channel
    hill_found = False
    for x in range(grid.width):
        for y in range(grid.depth):
            if (x, y) in river_channel:
                continue
            top_z = int(heightmap[x, y])
            if top_z < SURFACE_Z:
                # This column has a hill: top_z..SURFACE_Z should be dirt
                assert grid.get(x, y, top_z) == VOXEL_DIRT, (
                    f"Hill at ({x},{y}) z={top_z} should be dirt"
                )
                # Above the hill should be air
                if top_z > 0:
                    assert grid.get(x, y, top_z - 1) == VOXEL_AIR, (
                        f"Above hill at ({x},{y}) z={top_z - 1} should be air"
                    )
                hill_found = True
                break
        if hill_found:
            break
    assert hill_found, "Should have at least one hill column"


def test_river_follows_terrain():
    """River follows terrain naturally — starts high, flows downhill.

    The river bed_z along the path should be monotonically non-decreasing
    (water flows from low z = high altitude toward high z = low altitude).
    All bed_z values must be within terrain range and at or above SURFACE_Z.
    """
    grid = _make_grid()
    heightmap = grid.heightmap
    river_path = getattr(grid, '_river_path', [])
    river_bed_z = getattr(grid, '_river_bed_z', {})
    river_channel = getattr(grid, '_river_channel', set())
    assert heightmap is not None
    assert len(river_path) > 0

    # bed_z along path should be monotonically non-decreasing (descending altitude)
    # Sink cells (there are 3-6 of them now) may be deeper, so skip those.
    prev_z = 0
    for px, py in river_path:
        bed_z = river_bed_z.get((px, py), SURFACE_Z)
        vtype = grid.get(px, py, bed_z)
        if vtype == VOXEL_WATER_SINK:
            # Sink is 1 below deepest bed — just verify it's deeper
            assert bed_z >= prev_z, (
                f"Sink at ({px},{py}) z={bed_z} should be at or below prev z={prev_z}"
            )
            continue
        assert bed_z >= prev_z, (
            f"River bed at ({px},{py}) z={bed_z} went uphill from z={prev_z}"
        )
        assert bed_z <= SURFACE_Z + RIVER_CHANNEL_DEPTH, (
            f"River bed at ({px},{py}) z={bed_z} should be at or above "
            f"SURFACE_Z + RIVER_CHANNEL_DEPTH={SURFACE_Z + RIVER_CHANNEL_DEPTH}"
        )
        prev_z = bed_z

    # Water or source/sink should be at each channel cell's bed
    water_types = {VOXEL_WATER, VOXEL_WATER_SOURCE, VOXEL_WATER_SINK}
    for rx, ry in list(river_channel)[:30]:
        bed_z = river_bed_z.get((rx, ry), SURFACE_Z)
        vtype = grid.get(rx, ry, bed_z)
        assert vtype in water_types or vtype == VOXEL_AIR, (
            f"River cell ({rx},{ry}) at z={bed_z} should be water-related, got {vtype}"
        )


def test_river_channel_descends():
    """River channel should have varied z-levels (descends from start to end)."""
    grid = _make_grid()
    river_bed_z = getattr(grid, '_river_bed_z', {})
    river_path = getattr(grid, '_river_path', [])
    assert len(river_path) > 0

    # The river channel should span multiple z-levels
    # (starts high, ends at SURFACE_Z), not all at the same level
    channel_zs: set[int] = set()
    for px, py in river_path:
        bz = river_bed_z.get((px, py))
        if bz is not None:
            channel_zs.add(bz)

    assert len(channel_zs) >= 2, (
        f"River channel should span multiple z-levels, got only {channel_zs}"
    )


def test_lava_river():
    """Lava river should exist at ~85% underground depth with source/sink and tunnel."""
    grid = _make_grid()
    h = grid.height
    d = grid.depth
    underground_depth = h - 1 - SURFACE_Z
    lava_z = getattr(grid, '_lava_z', None)
    lava_cells = getattr(grid, '_lava_cells', set())
    lava_bed_z = getattr(grid, '_lava_bed_z', {})

    assert lava_z is not None, "Lava river z-level should be set"
    assert len(lava_cells) > 10, "Lava river should have coverage"

    # Check lava_z (sink z) is at approximately 85% underground depth
    expected_z = SURFACE_Z + int(0.85 * underground_depth)
    assert abs(lava_z - expected_z) <= 2

    # Check actual lava/source/sink voxels exist at their bed z-levels
    # AND that air tunnel exists above each lava cell
    lava_types = {VOXEL_LAVA, VOXEL_LAVA_SOURCE, VOXEL_LAVA_SINK}
    lava_count = 0
    tunnel_count = 0
    for rx, ry in lava_cells:
        bed_z = lava_bed_z.get((rx, ry), lava_z)
        if grid.get(rx, ry, bed_z) in lava_types:
            lava_count += 1
        # Air tunnel above lava
        tunnel_z = bed_z - 1
        if grid.in_bounds(rx, ry, tunnel_z):
            if grid.get(rx, ry, tunnel_z) == VOXEL_AIR:
                tunnel_count += 1
    assert lava_count > 5, "Should have lava voxels placed"
    assert tunnel_count > 5, "Should have air tunnel above lava"

    # Source blocks at y=0 edge
    source_count = sum(
        1 for rx, ry in lava_cells
        if ry == 0 and grid.get(rx, ry, lava_bed_z.get((rx, ry), lava_z)) == VOXEL_LAVA_SOURCE
    )
    assert source_count > 0, "Should have lava source blocks at y=0 edge"

    # Sink blocks at y=d-1 edge
    sink_count = sum(
        1 for rx, ry in lava_cells
        if ry == d - 1 and grid.get(rx, ry, lava_bed_z.get((rx, ry), lava_z)) == VOXEL_LAVA_SINK
    )
    assert sink_count > 0, "Should have lava sink blocks at y=d-1 edge"


def test_lava_tunnel_ceiling_intact():
    """Ceiling above lava tunnel should be mostly solid rock (not air).

    A few cells may be air if a natural cave intersects the lava tunnel,
    but the vast majority of ceiling cells should be solid.
    """
    grid = _make_grid()
    lava_cells = getattr(grid, '_lava_cells', set())
    lava_bed_z = getattr(grid, '_lava_bed_z', {})

    solid_count = 0
    checked = 0
    for rx, ry in lava_cells:
        bed_z = lava_bed_z.get((rx, ry), 0)
        ceiling_z = bed_z - 2  # 1 above tunnel (which is at bed_z - 1)
        if grid.in_bounds(rx, ry, ceiling_z):
            vtype = grid.get(rx, ry, ceiling_z)
            if vtype != VOXEL_AIR:
                solid_count += 1
            checked += 1
    assert checked > 0, "Should have checked some ceiling cells"
    solid_ratio = solid_count / checked
    assert solid_ratio > 0.90, (
        f"At least 90% of ceiling cells should be solid, got {solid_ratio:.1%} "
        f"({solid_count}/{checked})"
    )


def test_lava_temperature():
    """Lava voxels should be at LAVA_TEMPERATURE."""
    grid = _make_grid()
    lava_cells = getattr(grid, '_lava_cells', set())
    lava_bed_z = getattr(grid, '_lava_bed_z', {})

    if not lava_cells:
        return

    checked = 0
    for rx, ry in list(lava_cells)[:20]:
        bed_z = lava_bed_z.get((rx, ry), 0)
        if grid.get(rx, ry, bed_z) == VOXEL_LAVA:
            assert grid.get_temperature(rx, ry, bed_z) == LAVA_TEMPERATURE
            checked += 1
    assert checked > 0, "Should have checked at least one lava cell temperature"


def test_ore_distribution():
    """Ores should exist at appropriate depth ranges."""
    grid = _make_grid()
    h = grid.height
    underground_depth = h - 1 - SURFACE_Z

    # Iron should exist in sedimentary/metamorphic range (10-50% underground depth)
    iron_count = 0
    z_min = SURFACE_Z + max(1, int(0.10 * underground_depth))
    z_max = min(h - 2, SURFACE_Z + int(0.50 * underground_depth))
    for z in range(z_min, z_max + 1):
        iron_count += int(np.sum(grid.grid[:, :, z] == VOXEL_IRON_ORE))
    assert iron_count > 0, "Iron ore should be present in sedimentary layers"

    # Mana crystals should exist deep (70-95% underground depth)
    mana_count = 0
    z_min = SURFACE_Z + int(0.70 * underground_depth)
    z_max = min(h - 2, SURFACE_Z + int(0.95 * underground_depth))
    for z in range(z_min, z_max + 1):
        mana_count += int(np.sum(grid.grid[:, :, z] == VOXEL_MANA_CRYSTAL))
    assert mana_count > 0, "Mana crystals should be present in deep layers"


def test_humidity_gradient():
    """Humidity should be higher near river and at depth."""
    grid = _make_grid()
    river_cells = getattr(grid, '_river_cells', set())
    river_bed_z = getattr(grid, '_river_bed_z', {})
    if not river_cells:
        return

    # Pick a river cell and check humidity at its bed z-level
    rx, ry = next(iter(river_cells))
    bed_z = river_bed_z.get((rx, ry), SURFACE_Z)
    river_humidity = grid.get_humidity(rx, ry, bed_z)
    assert river_humidity == 1.0

    # Check that far-away surface cells have lower humidity
    # Find a cell far from river
    for x in range(grid.width):
        far = True
        for rc in river_cells:
            if abs(x - rc[0]) < 10:
                far = False
                break
        if far:
            assert grid.get_humidity(x, grid.depth // 2, SURFACE_Z) < 0.5
            break


def test_temperature_baseline():
    """Temperature should increase with depth."""
    grid = _make_grid()
    h = grid.height

    # Surface should be around 20
    surface_temp = grid.get_temperature(grid.width // 2, grid.depth // 2, 0)
    assert 15.0 <= surface_temp <= 25.0

    # Deep should be higher
    deep_z = int(0.8 * (h - 1))
    deep_temp = grid.get_temperature(grid.width // 2, grid.depth // 2, deep_z)
    assert deep_temp > surface_temp


def test_mana_crystal_temperature():
    """Mana crystals should be at their fixed temperature."""
    grid = _make_grid()
    h = grid.height

    for x in range(grid.width):
        for y in range(grid.depth):
            for z in range(h):
                if grid.get(x, y, z) == VOXEL_MANA_CRYSTAL:
                    assert grid.get_temperature(x, y, z) == MANA_CRYSTAL_TEMPERATURE
                    return  # found one, that's enough
    # If no mana crystals found, test still passes (stochastic)


def test_no_lava_on_shallow_map():
    """Very shallow maps should skip lava generation gracefully."""
    grid = _make_grid(seed=42, height=4)
    # Should not crash; no lava expected on 4-layer map
    assert grid.height == 4


def test_river_channel_depth():
    """River channel should be deeper than surrounding banks.

    With RIVER_CHANNEL_DEPTH > 0, channel cells should have bank walls
    (solid blocks) on at least one cardinal side at the channel floor level.
    """
    grid = _make_grid()
    river_cells = getattr(grid, '_river_cells', set())
    river_bed_z = getattr(grid, '_river_bed_z', {})
    river_channel = getattr(grid, '_river_channel', set())

    if not river_cells or RIVER_CHANNEL_DEPTH == 0:
        return  # nothing to test

    water_types = {VOXEL_WATER, VOXEL_WATER_SOURCE, VOXEL_WATER_SINK}
    walled_count = 0

    for rx, ry in river_cells:
        bed_z = river_bed_z.get((rx, ry))
        if bed_z is None:
            continue

        # Check cardinal neighbors not in the channel
        for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            bx, by = rx + ddx, ry + ddy
            if (bx, by) in river_channel:
                continue
            if not grid.in_bounds(bx, by, bed_z):
                continue
            btype = grid.get(bx, by, bed_z)
            # Bank neighbor at channel floor should be solid (not air/water)
            if btype != VOXEL_AIR and btype not in water_types:
                walled_count += 1
                break  # found at least one solid bank wall for this cell

    # Most channel cells on the edge should have a solid bank wall
    edge_cells = [
        (rx, ry) for rx, ry in river_cells
        if any(
            (rx + dx, ry + dy) not in river_channel
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        )
    ]
    assert walled_count > len(edge_cells) * 0.5, (
        f"At least half the edge channel cells should have solid bank walls "
        f"at bed_z, got {walled_count}/{len(edge_cells)}"
    )


def test_caves_excluded_from_core_zone():
    """Caves should not overlap the core room reinforcement zone.

    Caves are skipped when their center + radius would place them
    within CAVE_CORE_EXCLUSION + radius blocks of (CORE_X, CORE_Y).
    We verify by patching _carve_sphere to record cave positions,
    then checking none overlap the core zone.
    """
    from unittest.mock import patch
    from dungeon_builder.world.geology import GeologyGenerator as GG

    for seed in (42, 99, 123, 777, 2025):
        carved_caves: list[tuple[int, int, int, int]] = []
        original_carve = GG._carve_sphere

        def tracking_carve(self, vg, cx, cy, cz, radius,
                           _orig=original_carve, _out=carved_caves):
            _out.append((cx, cy, cz, radius))
            return _orig(self, vg, cx, cy, cz, radius)

        carved_caves.clear()
        with patch.object(GG, '_carve_sphere', tracking_carve):
            _make_grid(seed=seed)

        for cx, cy, cz, radius in carved_caves:
            # No carved sphere should reach within ±3 of (CORE_X, CORE_Y)
            closest_x = max(cx - radius, cx) if abs(cx - CORE_X) > radius else CORE_X
            closest_y = max(cy - radius, cy) if abs(cy - CORE_Y) > radius else CORE_Y
            # Simple check: sphere center ± radius must not overlap ±3 zone
            x_overlap = abs(cx - CORE_X) < radius + 4  # 4 = 3 (room) + 1 margin
            y_overlap = abs(cy - CORE_Y) < radius + 4
            assert not (x_overlap and y_overlap), (
                f"Seed {seed}: cave at ({cx},{cy},{cz}) r={radius} "
                f"overlaps core zone (CORE={CORE_X},{CORE_Y})"
            )


def test_sink_reinforced_with_stone():
    """Water sink neighbors should be reinforced with stone (not weak material).

    Sinks are placed 1 below the deepest river bed.  Their cardinal
    neighbors and the block below should be stone (or stronger) so
    pre-stabilization gravity doesn't collapse and bury them.
    """
    # Strong types that don't need reinforcement
    _STRONG = {
        VOXEL_AIR, VOXEL_STONE, VOXEL_BEDROCK,
        VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN,
        VOXEL_WATER_SOURCE, VOXEL_WATER_SINK,
        VOXEL_LAVA_SOURCE, VOXEL_LAVA_SINK,
    }

    for seed in (42, 99, 123):
        grid = _make_grid(seed=seed)
        w, d, h = grid.width, grid.depth, grid.height

        # Find all sink cells
        sink_positions = list(zip(*np.where(grid.grid == VOXEL_WATER_SINK)))
        assert len(sink_positions) > 0, f"Seed {seed}: no sinks found"

        for sx, sy, sz in sink_positions:
            # Check cardinal + below neighbors
            for ddx, ddy, ddz in [
                (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0),
                (0, 0, 1),  # below
            ]:
                nx, ny, nz = sx + ddx, sy + ddy, sz + ddz
                if not grid.in_bounds(nx, ny, nz):
                    continue
                vtype = int(grid.grid[nx, ny, nz])
                assert vtype in _STRONG, (
                    f"Seed {seed}: sink at ({sx},{sy},{sz}) has weak "
                    f"neighbor type {vtype} at ({nx},{ny},{nz})"
                )
