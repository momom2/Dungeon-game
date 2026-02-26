"""Building, crafting, and dev-mode gameplay constants.

Dependencies: config.voxels
Dependents: config.__init__, building.build_system, building.crafting_system,
            main, ui.hud
"""

from .voxels import (
    VOXEL_BASALT,
    VOXEL_CHALK,
    VOXEL_GNEISS,
    VOXEL_GRANITE,
    VOXEL_LIMESTONE,
    VOXEL_MARBLE,
    VOXEL_OBSIDIAN,
    VOXEL_SANDSTONE,
    VOXEL_SHALE,
    VOXEL_SLATE,
    VOXEL_STONE,
)

# ── Dev Mode ─────────────────────────────────────────────────────────
# Game starts in dev mode.  Togglable in Options menu.

DEV_MODE = True
DEV_MAX_CONCURRENT_DIGS = 999  # unlimited digs in dev mode

# ── Concurrent dig limits ────────────────────────────────────────────

MAX_CONCURRENT_DIGS = 5  # mutable — upgrades can increase this at runtime
AUTO_BAG_DIG = True  # When True, dug blocks go directly into the player's bag

# ── Drag-select constants ────────────────────────────────────────────

DRAG_SELECT_THRESHOLD = 0.02  # NDC distance to distinguish click from drag
DRAG_VERTICAL_SENSITIVITY = 0.1  # NDC units of mouse Y movement per z-level

# ── New block gameplay constants ─────────────────────────────────────

GOLD_BAIT_INTERACT_TICKS = 10     # Same as treasure grab
HEAT_BEACON_TEMPERATURE = 500.0   # Source temp (< lava 1000)
HEAT_BEACON_DAMAGE = 15           # Burn damage to non-immune intruders
PRESSURE_PLATE_TRIGGER_RANGE = 1  # Adjacent activation distance
ALARM_BELL_DETECTION_RANGE = 2    # LOS detection range (cells)
ALARM_BELL_COOLDOWN = 40          # Ticks between alarm triggers
FRAGILE_FLOOR_WEIGHT_THRESHOLD = 10  # block_state accumulation before collapse
STEAM_VENT_DAMAGE = 10            # Steam burn damage
STEAM_VENT_HEAT_PULSE = 150.0     # Heat added to cells above
STEAM_VENT_HUMIDITY_PULSE = 0.7   # Humidity added to cells above
STEAM_VENT_RANGE = 3              # Cells above to affect

# ── Pipe & pump constants ────────────────────────────────────────────

PIPE_CONDUCTIVITY_BASE = 0.5      # Base heat/humidity transfer rate through pipes
PUMP_CONVECTION_RATE = 0.3        # Active pumping multiplier
PUMP_TICK_INTERVAL = 5            # Pump operates every N ticks

# Pump direction encoding (stored in block_state)
PUMP_DIR_POS_X = 0
PUMP_DIR_NEG_X = 1
PUMP_DIR_POS_Y = 2
PUMP_DIR_NEG_Y = 3
PUMP_DIR_POS_Z = 4   # up (shallower)
PUMP_DIR_NEG_Z = 5   # down (deeper)

# Stone types that pipes can be built into
PIPEABLE_STONE_TYPES = frozenset({
    VOXEL_STONE, VOXEL_SANDSTONE, VOXEL_LIMESTONE, VOXEL_SHALE, VOXEL_CHALK,
    VOXEL_SLATE, VOXEL_MARBLE, VOXEL_GNEISS, VOXEL_GRANITE, VOXEL_BASALT,
    VOXEL_OBSIDIAN,
})
