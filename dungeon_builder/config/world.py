"""World geometry, simulation timing, camera, and terrain generation.

Dependencies: (none — pure data module)
Dependents: config.__init__, main, world.voxel_grid, world.geology,
            rendering.camera, rendering.layer_slice, core.time_manager
"""

# ── Grid dimensions ──────────────────────────────────────────────────

GRID_WIDTH = 50
GRID_DEPTH = 50
GRID_HEIGHT = 40  # Z index 0 (highest sky) to Z index 39 (deepest)
CHUNK_SIZE = 16   # 16x16x1 per chunk

# ── Simulation timing ────────────────────────────────────────────────

TICKS_PER_SECOND = 20
SPEED_MULTIPLIERS = {0: 0.0, 1: 1.0, 2: 3.0}  # pause / play / fast

# ── RNG ──────────────────────────────────────────────────────────────

DEFAULT_SEED = 42

# ── Z-level mapping ──────────────────────────────────────────────────
# 5 sky layers (0-4) above ground level (SURFACE_Z=5)
# Array index 0 = highest sky, SURFACE_Z = flat ground, DEEPEST_Z = bedrock

SURFACE_Z = 5
DEEPEST_Z = 39

# ── Dungeon core ─────────────────────────────────────────────────────

CORE_DEFAULT_HP = 100
CORE_X = GRID_WIDTH // 2   # Center of the map
CORE_Y = GRID_DEPTH // 2   # Center of the map
CORE_Z = 15  # Array index (shifted +5 from old value 10)

# ── Layer-slice transparency (asymmetric: above vs below focus) ──────
# Above focus (toward surface, lower z-index): ceiling context, barely visible

LAYER_ALPHA_ABOVE = {1: 1.0, 2: 0.15}
LAYER_MAX_VISIBLE_ABOVE = 2

# Below focus (deeper, higher z-index): extended depth view
LAYER_ALPHA_BELOW = {1: 0.7, 2: 0.5, 3: 0.35, 4: 0.2, 5: 0.1}
LAYER_MAX_VISIBLE_BELOW = 5

# When False, all layers are shown at full opacity (no depth fade)
LAYER_DEPTH_FADE = True

# ── Camera defaults ──────────────────────────────────────────────────

CAMERA_DEFAULT_DISTANCE = 40.0
CAMERA_MIN_DISTANCE = 10.0
CAMERA_MAX_DISTANCE = 100.0
CAMERA_DEFAULT_HEADING = 45.0
CAMERA_DEFAULT_PITCH = -60.0
CAMERA_PAN_SPEED = 30.0
CAMERA_ROTATE_SPEED = 90.0
CAMERA_ZOOM_STEP = 5.0

# ── Claimed territory ────────────────────────────────────────────────

CLAIMED_TICK_INTERVAL = 10  # Recompute every 0.5s (same as connectivity)

# ── Terrain generation ───────────────────────────────────────────────

TERRAIN_VARIATION_MAX = 3             # Max hill height (blocks above SURFACE_Z ground)
RIVER_CHANNEL_DEPTH = 2              # Extra blocks carved below river surface level
TERRAIN_NOISE_SCALE = 24.0            # Noise scale for rolling hills (larger = smoother)
CAVE_CORE_EXCLUSION = 6              # Min Chebyshev distance from (CORE_X, CORE_Y) for cave centers
