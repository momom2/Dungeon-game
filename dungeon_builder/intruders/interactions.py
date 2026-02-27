"""Per-block-type micro-interaction system for intruders.

When an intruder is about to step onto or interact with a functional block,
the interaction handler determines what happens: damage, timed interaction,
repath, collection, or pass-through.

All logic is flag/stat-based — no archetype name checks.  Damage reduction
and interaction speed scale from numeric stats (``damage``, ``can_bash_door``,
``can_fly``, etc.) rather than hard-coded archetype identities.

Dependencies: config, intruders.agent (TYPE_CHECKING only)
Dependents: intruders.decision, tests/intruders/test_interactions.py,
    tests/intruders/test_ai_improvements.py
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_DOOR,
    VOXEL_SPIKE,
    VOXEL_TREASURE,
    VOXEL_TARP,
    VOXEL_ROLLING_STONE,
    VOXEL_REINFORCED_WALL,
    VOXEL_LAVA,
    VOXEL_WATER,
    VOXEL_SLOPE,
    VOXEL_STAIRS,
    VOXEL_GOLD_BAIT,
    VOXEL_HEAT_BEACON,
    VOXEL_PRESSURE_PLATE,
    VOXEL_IRON_BARS,
    VOXEL_FLOODGATE,
    VOXEL_ALARM_BELL,
    VOXEL_FRAGILE_FLOOR,
    VOXEL_PIPE,
    VOXEL_PUMP,
    VOXEL_STEAM_VENT,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    SPIKE_DAMAGE,
    ROLLING_STONE_DAMAGE,
    DOOR_BASH_TICKS,
    DOOR_LOCKPICK_TICKS,
    TREASURE_GRAB_TICKS,
    TARP_DETECT_CUNNING,
    GOLD_BAIT_INTERACT_TICKS,
    HEAT_BEACON_DAMAGE,
    STEAM_VENT_DAMAGE,
)

if TYPE_CHECKING:
    from dungeon_builder.intruders.agent import Intruder


class InteractionResult(Enum):
    """Outcome of an intruder stepping onto a functional block."""

    CONTINUE = auto()      # No interaction needed, proceed
    INTERACT = auto()      # Start a timed interaction (door bash, dig, treasure grab)
    DAMAGE = auto()        # Intruder takes damage but continues
    REPATH = auto()        # Cannot proceed, needs new path
    COLLECT = auto()       # Collect item (treasure)
    FALL = auto()          # Fall through (tarp collapse)
    DEATH = auto()         # Instant death (lava for non-immune)
    DESTROY_BLOCK = auto() # Block is destroyed (e.g. spike smash)


class InteractionInfo:
    """Details about an interaction result.

    Wraps the result enum plus any additional data (damage amount,
    interaction duration, block to destroy, etc.).
    """

    __slots__ = ("result", "damage", "ticks", "interaction_type")

    def __init__(
        self,
        result: InteractionResult,
        damage: int = 0,
        ticks: int = 0,
        interaction_type: str = "",
    ) -> None:
        self.result = result
        self.damage = damage
        self.ticks = ticks
        self.interaction_type = interaction_type

    def __repr__(self) -> str:
        return (
            f"InteractionInfo({self.result.name}, damage={self.damage}, "
            f"ticks={self.ticks}, type={self.interaction_type!r})"
        )


def handle_block(
    intruder: Intruder,
    voxel_type: int,
    block_state: int,
) -> InteractionInfo:
    """Determine the interaction when *intruder* encounters *voxel_type*.

    This is a pure function -- it does NOT modify intruder state or the grid.
    The caller (decision engine) applies the result.

    All checks use archetype flags and stats (``can_fly``, ``can_bash_door``,
    ``damage``, ``cunning``, etc.) rather than archetype name strings, so new
    archetypes work automatically based on their stat block.

    Parameters
    ----------
    intruder : Intruder
        The intruder encountering the block.
    voxel_type : int
        The voxel type of the block being entered.
    block_state : int
        The block_state value (door open/closed, spike extended/retracted).

    Returns
    -------
    InteractionInfo
        What should happen.
    """
    arch = intruder.archetype

    # -- Air / Slope / Stairs -- pass through --------------------------
    if voxel_type in (VOXEL_AIR, VOXEL_SLOPE, VOXEL_STAIRS):
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Door ----------------------------------------------------------
    if voxel_type == VOXEL_DOOR:
        if block_state == 0:  # Open
            return InteractionInfo(InteractionResult.CONTINUE)
        # Closed door
        if arch.can_lockpick:
            return InteractionInfo(
                InteractionResult.INTERACT,
                ticks=DOOR_LOCKPICK_TICKS,
                interaction_type="lockpick",
            )
        if arch.can_bash_door:
            # Stronger intruders bash faster: each 2 points of damage
            # shaves 1 tick off the base bash duration (minimum 1 tick).
            bash_ticks = max(1, DOOR_BASH_TICKS - arch.damage // 2)
            return InteractionInfo(
                InteractionResult.INTERACT,
                ticks=bash_ticks,
                interaction_type="bash_door",
            )
        return InteractionInfo(InteractionResult.REPATH)

    # -- Spike ---------------------------------------------------------
    if voxel_type == VOXEL_SPIKE:
        if block_state == 0:  # Retracted
            return InteractionInfo(InteractionResult.CONTINUE)
        # Extended spike
        # Flyers pass over
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        # Trap-aware intruders detect and avoid
        if arch.trap_detect_range > 0:
            return InteractionInfo(InteractionResult.REPATH)
        # Armored types (can_bash_door) take half spike damage
        if arch.can_bash_door:
            return InteractionInfo(
                InteractionResult.DAMAGE,
                damage=SPIKE_DAMAGE // 2,
            )
        # Everyone else takes full damage
        return InteractionInfo(
            InteractionResult.DAMAGE,
            damage=SPIKE_DAMAGE,
        )

    # -- Treasure ------------------------------------------------------
    if voxel_type == VOXEL_TREASURE:
        if arch.greed > 0:
            return InteractionInfo(
                InteractionResult.COLLECT,
                ticks=TREASURE_GRAB_TICKS,
                interaction_type="grab_treasure",
            )
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Tarp ----------------------------------------------------------
    if voxel_type == VOXEL_TARP:
        # Flyers pass over
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        # Arcane sight detects via supernatural sense
        if arch.arcane_sight_range > 0:
            return InteractionInfo(InteractionResult.REPATH)
        # High cunning detects
        if arch.cunning >= TARP_DETECT_CUNNING:
            return InteractionInfo(InteractionResult.REPATH)
        # Everyone else falls through
        return InteractionInfo(InteractionResult.FALL)

    # -- Rolling stone -------------------------------------------------
    if voxel_type == VOXEL_ROLLING_STONE:
        # Flyers pass over
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        # Fast intruders dodge (speed >= 3)
        if arch.speed >= 3:
            return InteractionInfo(InteractionResult.CONTINUE)
        # Flat damage to everyone else -- no archetype-specific reductions
        return InteractionInfo(
            InteractionResult.DAMAGE,
            damage=ROLLING_STONE_DAMAGE,
        )

    # -- Gold Bait -----------------------------------------------------
    if voxel_type == VOXEL_GOLD_BAIT:
        # Arcane sight reveals it as bait
        if arch.arcane_sight_range > 0:
            return InteractionInfo(InteractionResult.REPATH)
        # Greedy intruders grab the bait
        if arch.greed > 0:
            return InteractionInfo(
                InteractionResult.COLLECT,
                ticks=GOLD_BAIT_INTERACT_TICKS,
                interaction_type="grab_bait",
            )
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Heat Beacon ---------------------------------------------------
    if voxel_type == VOXEL_HEAT_BEACON:
        # Flyers avoid (not close enough to the heat source)
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        return InteractionInfo(
            InteractionResult.DAMAGE,
            damage=HEAT_BEACON_DAMAGE,
        )

    # -- Pressure Plate ------------------------------------------------
    if voxel_type == VOXEL_PRESSURE_PLATE:
        # Activation logic is handled in decision.py
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Iron Bars -----------------------------------------------------
    if voxel_type == VOXEL_IRON_BARS:
        return InteractionInfo(InteractionResult.REPATH)

    # -- Floodgate -----------------------------------------------------
    if voxel_type == VOXEL_FLOODGATE:
        if block_state == 0:  # Open
            return InteractionInfo(InteractionResult.CONTINUE)
        return InteractionInfo(InteractionResult.REPATH)  # Closed

    # -- Enchanted Door ------------------------------------------------
    if voxel_type == VOXEL_ENCHANTED_DOOR:
        if block_state == 0:  # Open
            return InteractionInfo(InteractionResult.CONTINUE)
        # Closed enchanted door — same interactions as regular door
        if arch.can_lockpick:
            return InteractionInfo(
                InteractionResult.INTERACT,
                ticks=DOOR_LOCKPICK_TICKS,
                interaction_type="lockpick",
            )
        if arch.can_bash_door:
            bash_ticks = max(1, DOOR_BASH_TICKS - arch.damage // 2)
            return InteractionInfo(
                InteractionResult.INTERACT,
                ticks=bash_ticks,
                interaction_type="bash_door",
            )
        return InteractionInfo(InteractionResult.REPATH)

    # -- Enchanted Floodgate -------------------------------------------
    if voxel_type == VOXEL_ENCHANTED_FLOODGATE:
        if block_state == 0:  # Open
            return InteractionInfo(InteractionResult.CONTINUE)
        return InteractionInfo(InteractionResult.REPATH)  # Closed

    # -- Alarm Bell ----------------------------------------------------
    if voxel_type == VOXEL_ALARM_BELL:
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Fragile Floor -------------------------------------------------
    if voxel_type == VOXEL_FRAGILE_FLOOR:
        # Flyers pass over without triggering
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        # Arcane sight detects it
        if arch.arcane_sight_range > 0:
            return InteractionInfo(InteractionResult.REPATH)
        # High cunning detects
        if arch.cunning >= TARP_DETECT_CUNNING:
            return InteractionInfo(InteractionResult.REPATH)
        # Everyone else walks on it (collapse handled in decision.py)
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Pipe / Pump ---------------------------------------------------
    if voxel_type in (VOXEL_PIPE, VOXEL_PUMP):
        return InteractionInfo(InteractionResult.REPATH)

    # -- Steam Vent ----------------------------------------------------
    if voxel_type == VOXEL_STEAM_VENT:
        # Flyers avoid the ground-level vent
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        return InteractionInfo(
            InteractionResult.DAMAGE,
            damage=STEAM_VENT_DAMAGE,
        )

    # -- Reinforced wall -----------------------------------------------
    if voxel_type == VOXEL_REINFORCED_WALL:
        return InteractionInfo(InteractionResult.REPATH)

    # -- Lava ----------------------------------------------------------
    if voxel_type == VOXEL_LAVA:
        # Flyers can pass over lava
        if arch.can_fly:
            return InteractionInfo(InteractionResult.CONTINUE)
        return InteractionInfo(InteractionResult.DEATH)

    # -- Water ---------------------------------------------------------
    if voxel_type == VOXEL_WATER:
        # Water entry is always permitted from the interaction layer.
        # Deep-water damage and flow push are handled in decision.py,
        # which checks equipment (has_water_breathing) at that point.
        return InteractionInfo(InteractionResult.CONTINUE)

    # -- Other solid blocks -- impassable ------------------------------
    # Digger handled by pathfinder (not here, since dig is a timed action)
    return InteractionInfo(InteractionResult.REPATH)
