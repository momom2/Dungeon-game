"""Scroll usage AI — decides when and how intruders use scroll consumables.

Each scroll type has specific trigger conditions.  Cartomancers use scrolls
more freely; other archetypes hoard them for emergencies.

Dependencies: config, intruders.agent, intruders.equipment,
    intruders.personal_map
Dependents: intruders.decision
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_builder.intruders.equipment import ItemEffect
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    VOXEL_LAVA,
    VOXEL_WATER,
)

if TYPE_CHECKING:
    from dungeon_builder.intruders.agent import Intruder
    from dungeon_builder.world.voxel_grid import VoxelGrid
    from dungeon_builder.core.event_bus import EventBus


# ── Config constants for scroll AI ────────────────────────────────────────

# Willingness thresholds: cartomancers use scrolls below these HP/morale
# ratios. Non-cartomancers only use in emergencies (lower thresholds).
SCROLL_HP_EMERGENCY = 0.3        # Non-cartomancer HP threshold for scroll use
SCROLL_HP_COMFORTABLE = 0.5      # Cartomancer HP threshold
SCROLL_MORALE_DESPERATE = 0.2    # Morale threshold for emergency scroll use

# Reveal usage: use when fewer than this fraction of nearby cells are revealed
SCROLL_REVEAL_UNKNOWN_RATIO = 0.6

# Shield usage: preemptive shielding when entering hazard-dense areas
SCROLL_SHIELD_HAZARD_DENSITY = 2  # Known hazards within perception range


def tick_scroll_use(
    intruder: Intruder,
    voxel_grid: VoxelGrid,
    event_bus: EventBus | None = None,
) -> None:
    """Evaluate and use scrolls each tick.

    Called from ``IntruderAI._tick_equipment_use`` after heal/sustenance.
    Each scroll type has independent trigger logic.  At most one scroll
    is used per tick to prevent chain-casting.
    """
    is_carto = intruder.archetype.base_gear_loadout == "cartomancer"
    hp_ratio = intruder.hp / intruder.max_hp if intruder.max_hp > 0 else 1.0

    # Priority order: Shield > Teleport > Dispel > Reveal > Bridge
    if _try_shield(intruder, hp_ratio, is_carto):
        return
    if _try_teleport(intruder, voxel_grid, hp_ratio, is_carto):
        return
    if _try_dispel(intruder, voxel_grid, is_carto, event_bus):
        return
    if _try_reveal(intruder, voxel_grid, is_carto):
        return
    if _try_bridge(intruder, voxel_grid, is_carto):
        return


# ── Shield scroll ───────────────────────────────────────────────────────


def _try_shield(intruder: Intruder, hp_ratio: float, is_carto: bool) -> bool:
    """Use Shield scroll when HP is low or entering hazardous area.

    Cartomancers use it proactively when they see hazards.
    Others only use it in HP emergencies.
    """
    if intruder.shield_hp > 0:
        return False  # Already shielded

    item = intruder.equipment.find_item(ItemEffect.SHIELD)
    if item is None:
        return False

    # Emergency: HP critically low
    threshold = SCROLL_HP_COMFORTABLE if is_carto else SCROLL_HP_EMERGENCY
    if hp_ratio < threshold:
        if item.use():
            intruder.shield_hp += item.template.value
            return True

    # Proactive (cartomancer only): many known hazards nearby
    if is_carto:
        hazard_count = _count_nearby_hazards(intruder)
        if hazard_count >= SCROLL_SHIELD_HAZARD_DENSITY:
            if item.use():
                intruder.shield_hp += item.template.value
                return True

    return False


# ── Teleport scroll ────────────────────────────────────────────────────


def _try_teleport(
    intruder: Intruder,
    voxel_grid: VoxelGrid,
    hp_ratio: float,
    is_carto: bool,
) -> bool:
    """Use Teleport scroll to escape danger or skip past obstacles.

    Triggers:
    - HP critically low and no path to retreat (escape teleport)
    - Stuck with no path for multiple ticks (desperation)
    - Cartomancer: proactive skip past hazardous path segments
    """
    item = intruder.equipment.find_item(ItemEffect.TELEPORT)
    if item is None:
        return False

    max_range = item.template.value

    # Emergency escape: very low HP, teleport toward surface
    if hp_ratio < SCROLL_HP_EMERGENCY:
        target = _find_teleport_escape(intruder, voxel_grid, max_range)
        if target is not None and item.use():
            intruder.x, intruder.y, intruder.z = target
            intruder._vision_dirty = True
            return True

    # Stuck: no path available (pathfinder returned None)
    if intruder.path is None and is_carto:
        target = _find_teleport_forward(intruder, voxel_grid, max_range)
        if target is not None and item.use():
            intruder.x, intruder.y, intruder.z = target
            intruder._vision_dirty = True
            return True

    return False


def _find_teleport_escape(
    intruder: Intruder, voxel_grid: VoxelGrid, max_range: int,
) -> tuple[int, int, int] | None:
    """Find the best escape position within teleport range.

    Prefers revealed air cells closer to the surface (lower z).
    """
    ix, iy, iz = intruder.x, intruder.y, intruder.z
    pmap = intruder.personal_map
    best: tuple[int, int, int] | None = None
    best_z = iz  # Lower z = closer to surface

    for dx in range(-max_range, max_range + 1):
        for dy in range(-max_range, max_range + 1):
            if abs(dx) + abs(dy) > max_range:
                continue
            nx, ny = ix + dx, iy + dy
            # Check at current z and above
            for nz in range(max(0, iz - 2), iz + 1):
                if not voxel_grid.in_bounds(nx, ny, nz):
                    continue
                vtype = pmap.get_type(nx, ny, nz)
                if vtype is not None and vtype == VOXEL_AIR:
                    if nz < best_z or best is None:
                        best = (nx, ny, nz)
                        best_z = nz

    return best


def _find_teleport_forward(
    intruder: Intruder, voxel_grid: VoxelGrid, max_range: int,
) -> tuple[int, int, int] | None:
    """Find an air cell ahead in the general objective direction."""
    ix, iy, iz = intruder.x, intruder.y, intruder.z
    pmap = intruder.personal_map

    # Scan revealed air cells within range, prefer those deeper (higher z)
    best: tuple[int, int, int] | None = None
    best_z = -1

    for dx in range(-max_range, max_range + 1):
        for dy in range(-max_range, max_range + 1):
            if abs(dx) + abs(dy) > max_range:
                continue
            nx, ny = ix + dx, iy + dy
            for nz in range(iz, min(iz + 3, voxel_grid.depth)):
                if not voxel_grid.in_bounds(nx, ny, nz):
                    continue
                vtype = pmap.get_type(nx, ny, nz)
                if vtype is not None and vtype == VOXEL_AIR:
                    if nz > best_z:
                        best = (nx, ny, nz)
                        best_z = nz

    return best


# ── Dispel scroll ──────────────────────────────────────────────────────


def _try_dispel(
    intruder: Intruder,
    voxel_grid: VoxelGrid,
    is_carto: bool,
    event_bus: EventBus | None = None,
) -> bool:
    """Use Dispel scroll to neutralize nearby enchanted traps.

    Targets enchanted doors/floodgates blocking the path, or enchanted
    blocks powering nearby traps.  Cartomancers use dispel proactively;
    others only when directly blocked.
    """
    item = intruder.equipment.find_item(ItemEffect.DISPEL)
    if item is None:
        return False

    radius = item.template.value
    target = _find_dispel_target(intruder, voxel_grid, radius, is_carto)
    if target is None:
        return False

    if not item.use():
        return False

    # Dispel effect: set block to air within radius of target
    tx, ty, tz = target
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if abs(dx) + abs(dy) + abs(dz) > radius:
                    continue
                nx, ny, nz = tx + dx, ty + dy, tz + dz
                if not voxel_grid.in_bounds(nx, ny, nz):
                    continue
                vtype = voxel_grid.get(nx, ny, nz)
                if vtype in (VOXEL_ENCHANTED_DOOR, VOXEL_ENCHANTED_FLOODGATE):
                    voxel_grid.set(nx, ny, nz, VOXEL_AIR, event_bus=event_bus)

    return True


def _find_dispel_target(
    intruder: Intruder,
    voxel_grid: VoxelGrid,
    radius: int,
    is_carto: bool,
) -> tuple[int, int, int] | None:
    """Find the best enchanted block to dispel.

    Priority: blocks on the current path > blocks adjacent to intruder.
    """
    # Check path ahead for enchanted obstacles
    if intruder.path is not None:
        end = min(intruder.path_index + 5, len(intruder.path))
        for i in range(intruder.path_index, end):
            px, py, pz = intruder.path[i]
            if voxel_grid.in_bounds(px, py, pz):
                vtype = voxel_grid.get(px, py, pz)
                if vtype in (VOXEL_ENCHANTED_DOOR, VOXEL_ENCHANTED_FLOODGATE):
                    return (px, py, pz)

    # Cartomancer proactive: check adjacent cells
    if is_carto:
        ix, iy, iz = intruder.x, intruder.y, intruder.z
        for dx, dy, dz in (
            (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
            (0, 0, 1), (0, 0, -1),
        ):
            nx, ny, nz = ix + dx, iy + dy, iz + dz
            if voxel_grid.in_bounds(nx, ny, nz):
                vtype = voxel_grid.get(nx, ny, nz)
                if vtype in (VOXEL_ENCHANTED_DOOR, VOXEL_ENCHANTED_FLOODGATE):
                    return (nx, ny, nz)

    return None


# ── Reveal scroll ──────────────────────────────────────────────────────


def _try_reveal(intruder: Intruder, voxel_grid: VoxelGrid, is_carto: bool) -> bool:
    """Use Reveal scroll when in poorly-explored territory.

    Checks the ratio of revealed cells in a sphere around the intruder.
    Cartomancers are more willing to use reveal proactively.
    """
    item = intruder.equipment.find_item(ItemEffect.REVEAL)
    if item is None:
        return False

    radius = item.template.value
    pmap = intruder.personal_map
    ix, iy, iz = intruder.x, intruder.y, intruder.z

    # Count revealed vs total cells in reveal radius
    total = 0
    revealed = 0
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if abs(dx) + abs(dy) + abs(dz) > radius:
                    continue
                total += 1
                if pmap.get_type(ix + dx, iy + dy, iz + dz) is not None:
                    revealed += 1

    if total == 0:
        return False

    ratio = revealed / total
    threshold = SCROLL_REVEAL_UNKNOWN_RATIO if is_carto else 0.4

    if ratio < threshold:
        if item.use():
            # Mark all cells in radius as revealed (reveal true types)
            # NOTE: The actual reveal uses the intruder's personal map,
            # which respects vision deception for non-arcane-sight intruders.
            # Reveal scroll grants arcane sight for its area.
            _apply_reveal(intruder, voxel_grid, radius)
            return True

    return False


def _apply_reveal(
    intruder: Intruder, voxel_grid: VoxelGrid, radius: int,
) -> None:
    """Reveal all cells in radius around intruder on their personal map.

    Reveal scrolls grant true-type vision (no deception) for the revealed area,
    similar to arcane sight but instantaneous and area-of-effect.
    """
    pmap = intruder.personal_map
    ix, iy, iz = intruder.x, intruder.y, intruder.z

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if abs(dx) + abs(dy) + abs(dz) > radius:
                    continue
                nx, ny, nz = ix + dx, iy + dy, iz + dz
                if voxel_grid.in_bounds(nx, ny, nz):
                    vtype = voxel_grid.get(nx, ny, nz)
                    pmap.reveal(nx, ny, nz, vtype)


# ── Bridge scroll ──────────────────────────────────────────────────────


def _try_bridge(
    intruder: Intruder, voxel_grid: VoxelGrid, is_carto: bool,
) -> bool:
    """Use Bridge scroll to cross water or lava gaps.

    Only triggers when the path ahead crosses water/lava and the intruder
    lacks the appropriate immunity.
    """
    if not is_carto:
        # Non-cartomancers only bridge when directly facing an impassable gap
        if intruder.path is None:
            return False

    item = intruder.equipment.find_item(ItemEffect.BRIDGE)
    if item is None:
        return False

    gap = _find_bridge_gap(intruder, voxel_grid)
    if gap is None:
        return False

    if not item.use():
        return False

    # Place temporary bridge blocks (air) over the gap
    # In the real implementation, these would be temporary blocks
    # that revert after SCROLL_BRIDGE_DURATION ticks.
    # For now, we mark them in the personal map as traversable.
    for pos in gap:
        voxel_grid.set(pos[0], pos[1], pos[2], VOXEL_AIR)

    return True


def _find_bridge_gap(
    intruder: Intruder, voxel_grid: VoxelGrid,
) -> list[tuple[int, int, int]] | None:
    """Find a water/lava gap ahead that needs bridging."""
    if intruder.path is None:
        return None

    gap: list[tuple[int, int, int]] = []
    end = min(intruder.path_index + 4, len(intruder.path))

    for i in range(intruder.path_index, end):
        px, py, pz = intruder.path[i]
        if not voxel_grid.in_bounds(px, py, pz):
            continue
        vtype = voxel_grid.get(px, py, pz)
        if vtype in (VOXEL_WATER, VOXEL_LAVA):
            # Check immunities
            if vtype == VOXEL_WATER and intruder.has_water_breathing:
                continue
            if vtype == VOXEL_LAVA and intruder.has_fire_immunity:
                continue
            gap.append((px, py, pz))

    return gap if gap else None


# ── Helpers ────────────────────────────────────────────────────────────


def _count_nearby_hazards(intruder: Intruder) -> int:
    """Count known hazards within perception range."""
    ix, iy, iz = intruder.x, intruder.y, intruder.z
    r = intruder.effective_perception
    count = 0
    for hx, hy, hz in intruder.personal_map.hazards:
        if abs(hx - ix) + abs(hy - iy) + abs(hz - iz) <= r:
            count += 1
    return count
