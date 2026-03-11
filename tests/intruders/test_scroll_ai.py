"""Tests for scroll usage AI — trigger conditions and world effects.

Dependencies: intruders.scroll_ai, intruders.agent, intruders.archetypes,
    intruders.equipment, intruders.personal_map, world.voxel_grid, config
Dependents: (test-only)
"""

from __future__ import annotations

import pytest

from dungeon_builder.intruders.scroll_ai import (
    tick_scroll_use,
    SCROLL_HP_EMERGENCY,
    SCROLL_HP_COMFORTABLE,
    SCROLL_SHIELD_HAZARD_DENSITY,
    SCROLL_REVEAL_UNKNOWN_RATIO,
)
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    EIDOLON,
    CARTOMANCER,
    INQUISITOR,
    EXPLORER,
    IntruderObjective,
)
from dungeon_builder.intruders.equipment import (
    Equipment,
    ItemInstance,
    ItemEffect,
    SCROLL_SHIELD,
    SCROLL_TELEPORT,
    SCROLL_DISPEL,
    SCROLL_REVEAL,
    SCROLL_BRIDGE,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_ENCHANTED_DOOR,
    VOXEL_ENCHANTED_FLOODGATE,
    VOXEL_WATER,
    VOXEL_LAVA,
    EQUIPMENT_SHIELD_BASE_HP,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_intruder(
    archetype=INQUISITOR,
    x=5, y=5, z=1,
    hp_fraction=1.0,
    scrolls: list[ItemInstance] | None = None,
) -> Intruder:
    """Create an intruder with optional scroll equipment."""
    pm = PersonalMap()
    equip = Equipment(base_inventory_slots=6)
    intruder = Intruder(
        intruder_id=1,
        x=x, y=y, z=z,
        archetype=archetype,
        objective=IntruderObjective.DESTROY_CORE,
        personal_map=pm,
        equipment=equip,
    )
    if scrolls:
        for s in scrolls:
            equip.add_to_inventory(s)
    if hp_fraction < 1.0:
        intruder.hp = max(1, int(intruder.max_hp * hp_fraction))
    return intruder


def _make_grid(w=16, d=16, h=4, fill=VOXEL_AIR) -> VoxelGrid:
    """Create a small voxel grid, optionally pre-filled."""
    grid = VoxelGrid(width=w, depth=d, height=h)
    if fill is not None:
        grid.grid[:, :, :] = fill
    return grid


# ── Shield scroll tests ───────────────────────────────────────────────


class TestShieldScroll:
    """Shield scroll should trigger when HP is below threshold."""

    def test_shield_used_when_hp_low(self):
        """Non-cartomancer uses shield when HP < SCROLL_HP_EMERGENCY."""
        scroll = ItemInstance(SCROLL_SHIELD)
        intruder = _make_intruder(
            hp_fraction=SCROLL_HP_EMERGENCY - 0.05,
            scrolls=[scroll],
        )
        grid = _make_grid()
        assert intruder.shield_hp == 0
        tick_scroll_use(intruder, grid)
        assert intruder.shield_hp > 0
        assert scroll.depleted

    def test_shield_not_used_when_hp_high(self):
        """Shield not consumed when HP is above threshold."""
        scroll = ItemInstance(SCROLL_SHIELD)
        intruder = _make_intruder(hp_fraction=0.9, scrolls=[scroll])
        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert intruder.shield_hp == 0
        assert not scroll.depleted

    def test_shield_not_stacked_when_already_shielded(self):
        """If intruder already has shield_hp, don't use another scroll."""
        scroll = ItemInstance(SCROLL_SHIELD)
        intruder = _make_intruder(
            hp_fraction=SCROLL_HP_EMERGENCY - 0.05,
            scrolls=[scroll],
        )
        intruder.shield_hp = 10  # Already shielded
        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert intruder.shield_hp == 10  # Unchanged
        assert not scroll.depleted

    def test_cartomancer_uses_shield_proactively(self):
        """Cartomancer uses shield when enough nearby hazards exist."""
        scroll = ItemInstance(SCROLL_SHIELD)
        intruder = _make_intruder(
            archetype=CARTOMANCER,
            hp_fraction=0.9,  # HP fine
            scrolls=[scroll],
        )
        # Add enough hazards near the intruder
        ix, iy, iz = intruder.x, intruder.y, intruder.z
        for i in range(SCROLL_SHIELD_HAZARD_DENSITY):
            intruder.personal_map.hazards.add((ix + i + 1, iy, iz))
        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert intruder.shield_hp > 0

    def test_cartomancer_shield_threshold_higher(self):
        """Cartomancer uses shield at higher HP than non-cartomancer."""
        # HP between EMERGENCY and COMFORTABLE — only cartomancer uses shield
        hp_frac = (SCROLL_HP_EMERGENCY + SCROLL_HP_COMFORTABLE) / 2.0

        scroll_carto = ItemInstance(SCROLL_SHIELD)
        carto = _make_intruder(
            archetype=CARTOMANCER, hp_fraction=hp_frac,
            scrolls=[scroll_carto],
        )
        grid = _make_grid()
        tick_scroll_use(carto, grid)
        assert carto.shield_hp > 0

        scroll_inq = ItemInstance(SCROLL_SHIELD)
        inq = _make_intruder(
            archetype=INQUISITOR, hp_fraction=hp_frac,
            scrolls=[scroll_inq],
        )
        tick_scroll_use(inq, grid)
        assert inq.shield_hp == 0


# ── Teleport scroll tests ─────────────────────────────────────────────


class TestTeleportScroll:
    """Teleport triggers on very low HP with revealed air cells nearby."""

    def test_teleport_on_emergency_hp(self):
        """Intruder teleports toward surface when HP critically low."""
        scroll = ItemInstance(SCROLL_TELEPORT)
        intruder = _make_intruder(
            x=5, y=5, z=2,
            hp_fraction=SCROLL_HP_EMERGENCY - 0.05,
            scrolls=[scroll],
        )
        # Reveal some air cells above (closer to surface = lower z)
        intruder.personal_map.reveal(5, 5, 2, VOXEL_AIR)
        intruder.personal_map.reveal(5, 5, 1, VOXEL_AIR)
        intruder.personal_map.reveal(5, 5, 0, VOXEL_AIR)
        grid = _make_grid()
        old_z = intruder.z
        tick_scroll_use(intruder, grid)
        # Should have teleported closer to surface (lower z)
        assert intruder.z <= old_z
        assert scroll.depleted

    def test_teleport_not_used_at_high_hp(self):
        """Teleport not consumed when HP is fine."""
        scroll = ItemInstance(SCROLL_TELEPORT)
        intruder = _make_intruder(hp_fraction=0.8, scrolls=[scroll])
        intruder.personal_map.reveal(5, 5, 1, VOXEL_AIR)
        intruder.personal_map.reveal(5, 5, 0, VOXEL_AIR)
        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert not scroll.depleted


# ── Dispel scroll tests ───────────────────────────────────────────────


class TestDispelScroll:
    """Dispel removes enchanted doors/floodgates from the voxel grid."""

    def test_dispel_removes_enchanted_door_on_path(self):
        """Dispel scroll clears enchanted door on intruder's current path."""
        scroll = ItemInstance(SCROLL_DISPEL)
        intruder = _make_intruder(x=5, y=5, z=1, scrolls=[scroll])
        # Set a path that goes through an enchanted door
        intruder.path = [(5, 5, 1), (5, 6, 1), (5, 7, 1)]
        intruder.path_index = 0

        grid = _make_grid()
        grid.set(5, 6, 1, VOXEL_ENCHANTED_DOOR)

        tick_scroll_use(intruder, grid)
        assert grid.get(5, 6, 1) == VOXEL_AIR
        assert scroll.depleted

    def test_dispel_removes_enchanted_floodgate(self):
        """Dispel also clears enchanted floodgates."""
        scroll = ItemInstance(SCROLL_DISPEL)
        intruder = _make_intruder(x=5, y=5, z=1, scrolls=[scroll])
        intruder.path = [(5, 5, 1), (5, 6, 1)]
        intruder.path_index = 0

        grid = _make_grid()
        grid.set(5, 6, 1, VOXEL_ENCHANTED_FLOODGATE)

        tick_scroll_use(intruder, grid)
        assert grid.get(5, 6, 1) == VOXEL_AIR
        assert scroll.depleted

    def test_dispel_not_used_without_target(self):
        """Dispel not consumed when no enchanted blocks nearby."""
        scroll = ItemInstance(SCROLL_DISPEL)
        intruder = _make_intruder(scrolls=[scroll])
        intruder.path = [(5, 5, 1), (5, 6, 1)]
        intruder.path_index = 0

        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert not scroll.depleted

    def test_cartomancer_dispels_adjacent_enchanted_block(self):
        """Cartomancer proactively dispels enchanted blocks adjacent to them."""
        scroll = ItemInstance(SCROLL_DISPEL)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        # No path (so path-based check doesn't trigger)
        intruder.path = None
        # No shield scroll or low HP to trigger other scrolls first

        grid = _make_grid()
        grid.set(6, 5, 1, VOXEL_ENCHANTED_DOOR)

        tick_scroll_use(intruder, grid)
        assert grid.get(6, 5, 1) == VOXEL_AIR
        assert scroll.depleted


# ── Reveal scroll tests ───────────────────────────────────────────────


class TestRevealScroll:
    """Reveal scroll exposes cells on the personal map."""

    def test_reveal_used_in_unexplored_territory(self):
        """Reveal triggers when most nearby cells are unknown."""
        scroll = ItemInstance(SCROLL_REVEAL)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        # Don't reveal much -- the ratio should be low enough to trigger
        intruder.personal_map.reveal(5, 5, 1, VOXEL_AIR)

        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        # After reveal, many cells should now be in the personal map
        assert len(intruder.personal_map) > 1
        assert scroll.depleted

    def test_reveal_not_used_in_well_explored_area(self):
        """Reveal not consumed when most cells are already revealed."""
        scroll = ItemInstance(SCROLL_REVEAL)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        # Reveal many cells around the intruder to push ratio above threshold
        radius = SCROLL_REVEAL.value
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if abs(dx) + abs(dy) + abs(dz) <= radius:
                        intruder.personal_map.reveal(
                            5 + dx, 5 + dy, 1 + dz, VOXEL_AIR,
                        )
        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert not scroll.depleted

    def test_reveal_shows_true_voxel_types(self):
        """Revealed cells should show the actual voxel type from the grid."""
        scroll = ItemInstance(SCROLL_REVEAL)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        intruder.personal_map.reveal(5, 5, 1, VOXEL_AIR)

        grid = _make_grid()
        grid.set(6, 5, 1, VOXEL_STONE)

        tick_scroll_use(intruder, grid)
        # After reveal, the personal map should show the true type
        assert intruder.personal_map.get_type(6, 5, 1) == VOXEL_STONE


# ── Bridge scroll tests ───────────────────────────────────────────────


class TestBridgeScroll:
    """Bridge scroll creates walkable cells over water/lava on the path."""

    def test_bridge_over_water_on_path(self):
        """Bridge scroll replaces water on path with air."""
        scroll = ItemInstance(SCROLL_BRIDGE)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        intruder.path = [(5, 5, 1), (5, 6, 1), (5, 7, 1)]
        intruder.path_index = 0

        grid = _make_grid()
        grid.set(5, 6, 1, VOXEL_WATER)

        tick_scroll_use(intruder, grid)
        assert grid.get(5, 6, 1) == VOXEL_AIR
        assert scroll.depleted

    def test_bridge_over_lava_on_path(self):
        """Bridge scroll also bridges lava gaps."""
        scroll = ItemInstance(SCROLL_BRIDGE)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        intruder.path = [(5, 5, 1), (5, 6, 1)]
        intruder.path_index = 0

        grid = _make_grid()
        grid.set(5, 6, 1, VOXEL_LAVA)

        tick_scroll_use(intruder, grid)
        assert grid.get(5, 6, 1) == VOXEL_AIR
        assert scroll.depleted

    def test_bridge_not_used_without_water_gap(self):
        """Bridge not consumed when no water/lava on path."""
        scroll = ItemInstance(SCROLL_BRIDGE)
        intruder = _make_intruder(
            archetype=CARTOMANCER, x=5, y=5, z=1,
            scrolls=[scroll],
        )
        intruder.path = [(5, 5, 1), (5, 6, 1)]
        intruder.path_index = 0

        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        assert not scroll.depleted

    def test_non_cartomancer_without_path_skips_bridge(self):
        """Non-cartomancer without a path doesn't attempt to bridge."""
        scroll = ItemInstance(SCROLL_BRIDGE)
        intruder = _make_intruder(scrolls=[scroll])
        intruder.path = None

        grid = _make_grid()
        grid.set(6, 5, 1, VOXEL_WATER)  # Water nearby but no path
        tick_scroll_use(intruder, grid)
        assert not scroll.depleted


# ── Priority ordering ─────────────────────────────────────────────────


class TestScrollPriority:
    """Shield > Teleport > Dispel > Reveal > Bridge priority order."""

    def test_shield_takes_priority_over_teleport(self):
        """When both shield and teleport could trigger, shield is used first."""
        shield = ItemInstance(SCROLL_SHIELD)
        teleport = ItemInstance(SCROLL_TELEPORT)
        intruder = _make_intruder(
            hp_fraction=SCROLL_HP_EMERGENCY - 0.05,
            scrolls=[shield, teleport],
        )
        intruder.personal_map.reveal(5, 5, 1, VOXEL_AIR)
        intruder.personal_map.reveal(5, 5, 0, VOXEL_AIR)

        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        # Shield consumed, teleport untouched
        assert shield.depleted
        assert not teleport.depleted
        assert intruder.shield_hp > 0

    def test_only_one_scroll_per_tick(self):
        """At most one scroll is consumed per tick (no chain-casting)."""
        shield = ItemInstance(SCROLL_SHIELD)
        reveal = ItemInstance(SCROLL_REVEAL)
        intruder = _make_intruder(
            archetype=CARTOMANCER,
            hp_fraction=SCROLL_HP_EMERGENCY - 0.05,
            scrolls=[shield, reveal],
        )
        intruder.personal_map.reveal(5, 5, 1, VOXEL_AIR)

        grid = _make_grid()
        tick_scroll_use(intruder, grid)
        # Only shield should be consumed this tick
        assert shield.depleted
        assert not reveal.depleted
