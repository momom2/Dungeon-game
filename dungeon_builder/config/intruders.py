"""Intruder AI, party composition, equipment, and pathfinding constants.

Dependencies: (none — pure data module)
Dependents: config.__init__, intruders.*, ui.options_panel
"""

# ── Intruder global multipliers (applied to archetype base stats) ────
# Adjustable via Options menu sliders to scale difficulty.

INTRUDER_HP_MULTIPLIER = 1.0       # Applied to archetype base HP
INTRUDER_DAMAGE_MULTIPLIER = 1.0   # Applied to archetype base damage
# INTRUDER_SPAWN_INTERVAL: Stubbed — automatic spawning will be
# overhauled when intruder society is implemented.  Currently,
# INTRUDER_PARTY_SPAWN_INTERVAL (below) controls party spawn timing.

# ── Party spawning ───────────────────────────────────────────────────

INTRUDER_PARTY_SPAWN_INTERVAL = 400   # 20 seconds between party spawns
MAX_PARTIES = 3                        # Max concurrent parties
MAX_INTRUDERS_TOTAL = 24               # Hard cap on alive intruders

# ── Map sharing ──────────────────────────────────────────────────────

MAP_SHARE_RANGE = 3                    # Allies within N cells share maps
MAP_SHARE_INTERVAL = 10                # Share maps every N ticks (throttle)

# ── Interaction durations (ticks) ────────────────────────────────────

DOOR_BASH_TICKS = 15
DOOR_LOCKPICK_TICKS = 5
TREASURE_GRAB_TICKS = 10

# ── Trap damage ──────────────────────────────────────────────────────

SPIKE_DAMAGE = 20
ROLLING_STONE_DAMAGE = 30
TARP_DETECT_CUNNING = 0.5             # Cunning threshold to detect tarps

# ── Equipment — general ──────────────────────────────────────────────

EQUIPMENT_SHIELD_BASE_HP = 30
POTION_HEAL_AMOUNT = 20
POTION_FIRE_DURATION = 300             # Ticks of fire immunity per potion
POTION_WATER_DURATION = 300            # Ticks of water breathing per potion
POTION_SUSTENANCE_VALUE = 5            # Food/water units restored
BASE_INVENTORY_SLOTS = 3              # Default consumable capacity (no containers)
POUCH_EXTRA_SLOTS = 2
BANDOLIER_EXTRA_SLOTS = 3
BACKPACK_EXTRA_SLOTS = 4

# ── Equipment — torch & illumination ─────────────────────────────────

TORCH_PERCEPTION_BONUS = 2            # Perception range boost while torch lit
TORCH_DURATION = 500                   # Ticks before torch burns out

# ── Equipment — scrolls ──────────────────────────────────────────────

SCROLL_TELEPORT_MAX_RANGE = 8         # Max cells for distance-mode teleport
SCROLL_REVEAL_RADIUS = 6
SCROLL_BRIDGE_DURATION = 100           # Ticks before bridge disappears
SCROLL_DISPEL_RADIUS = 1              # Cells around target to neutralise

# ── Equipment — rope ─────────────────────────────────────────────────

ROPE_DEFAULT_LENGTH = 5               # Cells of vertical coverage
ROPE_KNOT_PENALTY = 4                 # combined_length = l1 + l2 - penalty

# ── Familiars (Mole Tamer) ───────────────────────────────────────────

FAMILIAR_HP = 15
FAMILIAR_DIG_SPEED = 8                # Ticks per dig action
FAMILIAR_UNRULINESS_PER_DIG = 0.1     # Unruliness increase per completed dig
FAMILIAR_UNRULY_THRESHOLD = 0.7       # Above this: familiar goes unruly
FAMILIAR_MOVE_INTERVAL = 4            # Ticks between familiar moves

# ── Mole Tamer commanding ─────────────────────────────────────────────

TAMER_COMMAND_INTERVAL = 10           # Ticks between command decisions
TAMER_DIG_LOOKAHEAD = 3               # Path steps ahead to scan for diggables
TAMER_MAX_FAMILIAR_DISTANCE = 8       # Recall familiars beyond this (Manhattan)

# ── Eidolon ──────────────────────────────────────────────────────────

EIDOLON_ENTERTAINMENT_DECAY = 0.002   # Entertainment lost per tick
EIDOLON_BOREDOM_THRESHOLD = 0.3       # Below this: eidolon becomes destructive
EIDOLON_GIFT_THRESHOLD = 0.8          # Above this: eidolon bestows a gift
EIDOLON_PHASE_THICKNESS = 2           # Max wall thickness to phase through

# ── Sprites (Eidolon familiars) ────────────────────────────────────────

SPRITE_HP = 5                          # Very fragile
SPRITE_MOVE_INTERVAL = 2              # Ticks between moves (faster than moles)
SPRITE_INSPECTION_LIMIT = 15          # Inspections before harmless dissipation
SPRITE_BURST_RADIUS = 3              # Explosion sphere radius (set blocks loose)
SPRITE_SUMMON_COOLDOWN = 100          # Ticks before eidolon can summon new sprites
EIDOLON_SPRITE_CAPACITY = 2          # Max sprites per eidolon
SPRITE_MEMORY_RANGE = 4              # Manhattan range for target searching
SPRITE_PARTNER_SAFE_DISTANCE = 5     # Don't burst sprites within this of partner

# ── Alchemist ────────────────────────────────────────────────────────

ALCHEMIST_POTION_SLOTS = 3            # Base potion count for alchemists

# ── Cartomancer ──────────────────────────────────────────────────────

CARTOMANCER_BASE_SCROLLS = 2          # Scrolls at GRUNT status
CARTOMANCER_STATUS_BONUS_SCROLLS = 1  # Extra scrolls per status rank above GRUNT

# ── Explorer ─────────────────────────────────────────────────────────

EXPLORER_MAP_VALUE_PER_CELL = 1       # Reputation intel per explored cell

# ── Hero ─────────────────────────────────────────────────────────────

HERO_LUCK_DODGE_CHANCE = 0.15         # Chance to dodge trap damage

# ── Food & Water (survival) ──────────────────────────────────────────

SUPPLY_SAFETY_MARGIN = 1.3            # Must have 1.3x estimated return cost
SUPPLY_COST_PER_CELL = 0.05           # Supply cost per cell of travel (estimate)

# ── Archetype render colours ─────────────────────────────────────────

ARCHETYPE_COLORS: dict[str, tuple[float, float, float]] = {
    "Explorer":     (0.2, 0.7, 0.3),   # Forest green (outdoor scout)
    "Inquisitor":   (0.7, 0.7, 0.9),   # Steel blue (armoured knight)
    "Gloomwarden":  (0.9, 0.9, 0.5),   # Pale gold (torch-bearing ranger)
    "Mole Tamer":   (0.6, 0.4, 0.2),   # Brown (earthy beast handler)
    "Eidolon":      (0.6, 0.3, 0.9),   # Violet (supernatural being)
    "Alchemist":    (0.3, 0.7, 0.2),   # Acid green (chemical brewer)
    "Cartomancer":  (0.3, 0.3, 0.8),   # Deep blue (magic user)
    "Hero":         (1.0, 0.85, 0.0),  # Gold (legendary champion)
}
ARCHETYPE_DEFAULT_COLOR: tuple[float, float, float] = (1.0, 0.2, 0.2)  # Fallback red

# ── Party composition weights ────────────────────────────────────────

PARTY_WEIGHT_SCOUTING_BAND = 0.30
PARTY_WEIGHT_WAR_PARTY = 0.30
PARTY_WEIGHT_SIEGE_COMPANY = 0.15
PARTY_WEIGHT_ARCANE_EXPEDITION = 0.10
PARTY_WEIGHT_HEROS_RETINUE = 0.05
PARTY_WEIGHT_EIDOLON_PAIR = 0.10

# ── Social Dynamics: Level & Status ──────────────────────────────────

LEVEL_HP_SCALE = 0.15                   # Per-level HP multiplier increment
LEVEL_DAMAGE_SCALE = 0.10               # Per-level damage multiplier increment
LEVEL_WEIGHTS = (0.40, 0.30, 0.20, 0.08, 0.02)  # Probability for levels 1-5
LEVEL_DEADLY_SHIFT = 0.10               # Weight shifted from level 1 per 0.1 lethality above 0.5

# ── Social Dynamics: Knowledge Archive ───────────────────────────────

KNOWLEDGE_STALE_TICKS = 4000            # ~3.3 minutes — intel older than this is filtered
KNOWLEDGE_UNCERTAIN_THRESHOLD = 0.7     # Skip cells above this uncertainty at injection
KNOWLEDGE_CONTRADICTION_BASE = 0.3      # Uncertainty added per contradiction
KNOWLEDGE_CONFIRM_DECAY = 0.5           # Uncertainty multiplier on confirmation
KNOWLEDGE_CHANGE_UNCERTAINTY = 0.4      # Uncertainty added when player changes a cell

# ── Social Dynamics: Reputation ──────────────────────────────────────

REPUTATION_DEADLY_LETHALITY = 0.7       # Lethality threshold for "deadly" profile
REPUTATION_RICH_RICHNESS = 0.4          # Richness threshold for "rich" profile
REPUTATION_UNKNOWN_THRESHOLD = 5        # Fewer total outcomes → "unknown" profile
REPUTATION_DEADLY_MODIFIER = (0.3, 0.1, -0.2)   # (destroy, explore, pillage) offsets
REPUTATION_RICH_MODIFIER = (-0.1, 0.1, 0.3)
REPUTATION_UNKNOWN_MODIFIER = (0.0, 0.2, 0.0)
REPUTATION_DEADLY_LOYALTY = -0.1        # Loyalty modifier for deadly dungeon
REPUTATION_RICH_LOYALTY = -0.15         # Loyalty modifier for rich dungeon

# ── Social Dynamics: Morale ──────────────────────────────────────────

MORALE_BASE = 0.7                       # Starting morale for all intruders
MORALE_LOW_THRESHOLD = 0.3             # Below this: slower movement, earlier retreat
MORALE_HIGH_THRESHOLD = 0.8            # Above this: faster movement, damage bonus
MORALE_FLEE_THRESHOLD = 0.1            # Below this: abandon party and flee solo
MORALE_ALLY_DEATH_PENALTY = 0.15       # Morale loss per ally death witnessed
MORALE_DAMAGE_PENALTY = 0.03           # Morale loss per hit taken
MORALE_HAZARD_PENALTY = 0.01           # Morale loss per new hazard seen
MORALE_TREASURE_BONUS = 0.1            # Morale gain per treasure collected
MORALE_LEADER_BONUS = 0.001            # Morale gain per tick while leader alive
MORALE_SUPPORT_TICK = 0.002            # Morale gain per tick near support archetype
MORALE_DRIFT_RATE = 0.001              # Drift toward MORALE_BASE per tick
MORALE_SLOW_FACTOR = 1.5               # Move interval multiplier when low morale
MORALE_FAST_FACTOR = 0.8               # Move interval multiplier when high morale
MORALE_DAMAGE_BONUS = 1.2              # Damage multiplier when high morale
MORALE_RETREAT_MULTIPLIER = 2.0        # Retreat threshold multiplier when low morale

# ── Pathfinding ──────────────────────────────────────────────────────

PERSONAL_PATHFINDER_MAX_ITERATIONS = 5000
HAZARD_PATH_COST = 100.0              # Extra cost for detected spike cells
LAVA_ADJACENT_PATH_COST = 10.0        # Extra cost for lava-adjacent cells
PATHFINDING_MAX_ITERATIONS = 10000
PATHFINDING_VERTICAL_COST = 1.5

# ── Vision ──────────────────────────────────────────────────────────────

WATER_LOS_DEPTH = 2                   # Water blocks LOS after N consecutive cells

# ── Darkvision ─────────────────────────────────────────────────────────────

DARKVISION_DEPTH_THRESHOLD = 3        # z > SURFACE_Z + this = "dark" (darkvision applies)

# ── Exploration (EXPLORE objective) ────────────────────────────────────────

EXPLORE_FRONTIER_MAX_CANDIDATES = 20  # Max frontier targets evaluated per repath
EXPLORE_DEPTH_WEIGHT = 0.6            # Weight for depth vs proximity in frontier scoring

# ── Support aura ───────────────────────────────────────────────────────────

SUPPORT_AURA_SIGHT_THRESHOLD = 1      # arcane_sight_range >= this = support role
