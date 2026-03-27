"""Prototype-specific constants and shared-config patching.

Dependencies: dungeon_builder.config (rendering, materials, world)
Dependents: prototype.map_gen, prototype.crafting, prototype.intruders,
    prototype.main, tests/prototype/
"""

from __future__ import annotations

# ── Arrow trap block ────────────────────────────────────────────────
VOXEL_ARROW_TRAP = 100
ARROW_TRAP_COLOR = (0.65, 0.35, 0.30, 1.0)  # Reddish stone tint
ARROW_TRAP_NOISE = 0.06                       # Same grain as stone
ARROW_TRAP_DIG_DURATION = 30                  # 1.5 seconds
ARROW_TRAP_DAMAGE = 10                        # Damage per firing
ARROW_TRAP_COOLDOWN = 10                      # Ticks between firings

# ── Spawning ────────────────────────────────────────────────────────
SPAWN_INTERVAL = 1000                         # Ticks between waves
SPAWN_EDGE_Y = 0                              # Intruders enter at y=0

# ── Prototype core ──────────────────────────────────────────────────
PROTOTYPE_CORE_HP = 100

# ── Dev bag ─────────────────────────────────────────────────────────
DEV_BAG_STONE = 999                           # Starting stone in bag


def patch_shared_config() -> None:
    """Inject arrow-trap data into shared dungeon_builder LUTs.

    Must be called once at startup, before any rendering or building
    system reads the lookup tables.
    """
    from dungeon_builder.config.rendering import VOXEL_COLORS, VOXEL_NOISE
    from dungeon_builder.config.materials import DIG_DURATION
    import dungeon_builder.world.claimed_territory as _ct

    # Render colour and noise grain
    VOXEL_COLORS[VOXEL_ARROW_TRAP] = ARROW_TRAP_COLOR
    VOXEL_NOISE[VOXEL_ARROW_TRAP] = ARROW_TRAP_NOISE

    # Diggable (player can remove traps)
    DIG_DURATION[VOXEL_ARROW_TRAP] = ARROW_TRAP_DIG_DURATION

    # Claimed-territory traversal: traps don't block claim propagation
    # _CLAIM_TRAVERSABLE is a frozenset — replace with expanded version
    _ct._CLAIM_TRAVERSABLE = _ct._CLAIM_TRAVERSABLE | frozenset({VOXEL_ARROW_TRAP})
