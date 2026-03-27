"""Physics simulation constants — tick intervals, fluid dynamics, structural.

Covers temperature diffusion, gravity, structural load distribution,
humidity, water/lava flow, thermal stress, impact cascades, and angle
of repose.  Water flow model selection (LBM vs Jacobi) is configured here.

Dependencies: config.voxels
Dependents: config.__init__, world.physics.*, world.voxel_grid
"""

from .voxels import (
    VOXEL_BEDROCK,
    VOXEL_CORE,
    VOXEL_LAVA_SINK,
    VOXEL_LAVA_SOURCE,
    VOXEL_MANA_CRYSTAL,
    VOXEL_WATER_SINK,
    VOXEL_WATER_SOURCE,
)

# ── Temperature physics ──────────────────────────────────────────────

LAVA_TEMPERATURE = 1000.0
MANA_CRYSTAL_TEMPERATURE = 20.0
SURFACE_HEAT_LOSS = 0.05
TEMPERATURE_TICK_INTERVAL = 5   # run diffusion every N ticks
DIFFUSION_RATE = 0.1

# ── Gravity / structural physics ─────────────────────────────────────

GRAVITY_TICK_INTERVAL = 1        # Loose-fall runs every tick (responsive)
STRUCTURAL_TICK_INTERVAL = 10    # Load calc every 0.5s
CONNECTIVITY_TICK_INTERVAL = 10  # Connectivity flood-fill every 0.5s
MAX_FALL_PER_TICK = 5            # Loose blocks fall up to 5 cells per tick
MAX_CASCADE_PER_TICK = 64        # Cap structural failures per tick

# Structural anchors (absorb all load, infinite capacity)
STRUCTURAL_ANCHORS = frozenset({
    VOXEL_BEDROCK, VOXEL_CORE, VOXEL_MANA_CRYSTAL,
    VOXEL_WATER_SOURCE, VOXEL_WATER_SINK,
    VOXEL_LAVA_SOURCE, VOXEL_LAVA_SINK,
})

# Buttressing: each solid same-level neighbor reduces load by this factor
BUTTRESS_FACTOR = 0.03

# Multi-block arch detection
MAX_ARCH_SPAN = 5             # Maximum scanning distance for arch detection

# ── Environmental weakness factors ───────────────────────────────────

HUMIDITY_WEAKNESS = 0.3       # Base humidity weakness (scaled by porosity per material)
TEMP_WEAKNESS_MIN = 400.0     # Below this, no thermal weakening
TEMP_WEAKNESS_MAX = 800.0     # At this temp, maximum weakening
TEMP_WEAKNESS_FACTOR = 0.5    # At max temp, capacity drops to 50%

# ── Humidity diffusion ───────────────────────────────────────────────

HUMIDITY_TICK_INTERVAL = 5    # Run humidity diffusion every N ticks
HUMIDITY_DIFFUSION_RATE = 0.05  # Slower than heat (water seeps, not flows)
HUMIDITY_SURFACE_LOSS = 0.03  # Evaporation at surface
HUMIDITY_SOURCE_LEVEL = 0.8   # Blocks adjacent to lava produce steam -> humidity

# ── Impact damage ────────────────────────────────────────────────────

IMPACT_DAMAGE_THRESHOLD = 3   # Minimum fall distance (cells) to cause impact damage
IMPACT_DAMAGE_FACTOR = 0.5    # Fraction of (fall_distance * weight) applied as impact load

# ── Heat convection ──────────────────────────────────────────────────

CONVECTION_RATE = 0.3         # Fraction of humidity flow that carries proportional heat

# ── Lava flow physics ────────────────────────────────────────────────

LAVA_FLOW_RATE = 0.15            # Lateral leveling rate (water=0.4, lava is viscous)
MAX_LAVA_FLOW_PER_TICK = 2       # Flow iterations per tick (water=3)
LAVA_SOURCE_OUTPUT = 255         # Source output level (full)
LAVA_PRESSURE_WEIGHT = 0.5      # Pressure per depth (water=0.3, lava heavier)
LAVA_BURST_FACTOR = 1.2         # Wall burst threshold (water=1.5)
MANA_CRYSTAL_SPAWN_CHANCE = 0.05 # Per source per water tick: chance to spawn a mana crystal

# ── Angle of repose ──────────────────────────────────────────────────
# Loose granular materials spread laterally

GRANULAR_POROSITY_THRESHOLD = 0.2  # dirt, sand, chalk, sandstone
REPOSE_TICK_INTERVAL = 2     # Run lateral spreading every N ticks (responsive)
MAX_SPREAD_PER_TICK = 3       # Max lateral moves per tick

# ── Thermal stress ───────────────────────────────────────────────────

THERMAL_STRESS_TICK_INTERVAL = 10  # Same as structural (runs alongside)
THERMAL_FATIGUE_ACCUMULATION = 0.1 # Fraction of instantaneous ratio added to fatigue
THERMAL_FATIGUE_DECAY = 0.02       # Fatigue heals slowly when gradient is low
QUENCH_MULTIPLIER = 3.0            # Multiplier when water is adjacent (rapid cooling)
THERMAL_CRACK_THRESHOLD = 1.0      # When fatigue >= 1.0, block cracks

# ── Impact cascade ───────────────────────────────────────────────────

SHOCK_ATTENUATION = 0.7           # Fraction of shock absorbed by each block
SHOCK_STRUCTURAL_FACTOR = 0.5     # How much shock contributes to structural load
MAX_SHOCK_PROPAGATION_STEPS = 5   # Max BFS depth for shock wave
SHATTER_THRESHOLD = 2.0           # shock/capacity ratio to shatter instead of crack
MAX_CASCADE_DEPTH = 3             # Max chain reaction levels per tick

# ── Water physics ────────────────────────────────────────────────────

WATER_TICK_INTERVAL = 2           # Run water flow every 2 ticks (responsive)
WATER_SEEP_RATE = 0.02            # Rate at which water seeps through porous solids
WATER_PRESSURE_WEIGHT = 0.3       # Lateral pressure per unit of water depth
WATER_BURST_FACTOR = 1.5          # Pressure must exceed shear_strength * factor to burst
WATER_HUMIDITY_SOURCE = 0.9       # Water blocks set adjacent humidity (scaled by porosity)
WATER_TEMPERATURE = 20.0          # Default temperature of water blocks
WATER_EVAPORATION_RATE = 0.01     # Probability of losing 1 water_level per water tick (surface)
                                  # Standing pool (255): dries in ~25500 water ticks (~2550s at 20TPS)
                                  # River with source: source refills 255/tick, evap ~0.01/tick → negligible
WATER_LAVA_PRODUCT = 32           # VOXEL_OBSIDIAN produced when water meets lava
PIPE_WATER_TRANSFER_RATE = 0.5    # Water level units transferred through pipes per pump tick
WATER_BUOYANCY_FACTOR = 0.6       # Weight reduction for submerged blocks (1.0 = full, 0.0 = none)
WATER_DAMAGE_DEPTH_THRESHOLD = 3  # Min water depth (cells) before intruder takes damage
WATER_DAMAGE_PER_TICK = 5         # Damage to intruders submerged in deep water
WATER_CURRENT_PUSH_THRESHOLD = 1.5  # Velocity magnitude needed to push intruders

# ── Water flow model selection ───────────────────────────────────────

WATER_FLOW_MODEL = "lattice_boltzmann"  # "lattice_boltzmann" | "jacobi_projection"

# Lattice Boltzmann D3Q7 constants (default strategy)
LBM_TAU = 0.8                # BGK relaxation time (0.5 < tau; higher = more viscous)
LBM_GRAVITY = 0.003          # Body force per tick (in lattice units)
LBM_REST_DENSITY = 1.0       # Reference density for equilibrium
LBM_PRESSURE_DIFFUSION = 1.0 # Lateral transfer rate (fraction of pressure diff → water transfer)

# Jacobi Projection constants (alternative strategy)
JACOBI_ITERATIONS = 5        # Pressure solve iterations per tick
JACOBI_GRAVITY = 1.0         # Gravity acceleration per tick
JACOBI_FRICTION = 0.85       # Velocity damping per tick
JACOBI_VISCOSITY = 0.02      # Velocity diffusion
JACOBI_PRESSURE_DIFFUSION = 1.5  # Lateral transfer rate

# ── Source/sink physics ──────────────────────────────────────────────

WATER_SOURCE_OUTPUT = 255             # Water level forced on cells adjacent to water source
LAVA_SOURCE_REGEN = True              # Lava source fills adjacent air/obsidian with lava
