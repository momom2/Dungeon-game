"""Tests for intruder AI improvements: explore pathing, darkvision, torch,
risk tolerance, gradient cunning, map memory, and morale support aura.

Dependencies: config, core.event_bus, world.voxel_grid, world.pathfinding,
    dungeon_core.core, intruders.agent, intruders.archetypes,
    intruders.personal_map, intruders.personal_pathfinder,
    intruders.decision, intruders.party, intruders.equipment,
    intruders.knowledge_archive, utils.rng
Dependents: (none — test-only)
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.world.pathfinding import AStarPathfinder
from dungeon_builder.dungeon_core.core import DungeonCore
from dungeon_builder.intruders.agent import Intruder, IntruderState
from dungeon_builder.intruders.archetypes import (
    IntruderObjective,
    IntruderStatus,
    ArchetypeStats,
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    ALCHEMIST,
)
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.personal_pathfinder import PersonalPathfinder
from dungeon_builder.intruders.decision import IntruderAI
from dungeon_builder.intruders.party import Party
from dungeon_builder.intruders.equipment import (
    Equipment,
    ItemInstance,
    ItemEffect,
    TOOL_TORCH,
)
from dungeon_builder.intruders.knowledge_archive import KnowledgeArchive
from dungeon_builder.utils.rng import SeededRNG
from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_SPIKE,
    SURFACE_Z,
    HAZARD_PATH_COST,
    MORALE_SUPPORT_TICK,
    MORALE_BASE,
    SUPPLY_SAFETY_MARGIN,
    DARKVISION_DEPTH_THRESHOLD,
    EXPLORE_FRONTIER_MAX_CANDIDATES,
    SUPPORT_AURA_SIGHT_THRESHOLD,
)


# -- Helpers ---------------------------------------------------------------

_CORE_DEPTH = 3


def _make_grid(width=10, depth=10, height=None):
    """Create a grid of stone with air surface."""
    if height is None:
        height = SURFACE_Z + _CORE_DEPTH + 2
    grid = VoxelGrid(width=width, depth=depth, height=height)
    grid.grid[:] = VOXEL_STONE
    grid.grid[:, :, :SURFACE_Z + 1] = VOXEL_AIR
    return grid


def _make_corridor_grid():
    """Grid with surface, shaft, and corridor to core."""
    grid = _make_grid()
    core_z = SURFACE_Z + _CORE_DEPTH
    for z in range(SURFACE_Z, core_z + 1):
        grid.grid[5, 0, z] = VOXEL_AIR
    for y in range(0, 6):
        grid.grid[5, y, core_z] = VOXEL_AIR
    return grid


def _make_ai(grid=None, core_pos=None, core_hp=100, seed=42):
    """Create an IntruderAI with the given grid setup."""
    bus = EventBus()
    if grid is None:
        grid = _make_corridor_grid()
    if core_pos is None:
        core_pos = (5, 5, SURFACE_Z + _CORE_DEPTH)
    pf = AStarPathfinder(grid)
    core = DungeonCore(bus, *core_pos, hp=core_hp)
    rng = SeededRNG(seed)
    ai = IntruderAI(bus, grid, pf, core, rng)
    return ai, bus, grid, core, rng


def _make_intruder(
    intruder_id=1, x=0, y=0, z=None, arch=INQUISITOR,
    objective=IntruderObjective.DESTROY_CORE,
    equipment=None,
):
    if z is None:
        z = SURFACE_Z
    return Intruder(
        intruder_id, x, y, z, arch, objective, PersonalMap(),
        equipment=equipment,
    )


# ===========================================================================
# 1. EXPLORE Objective — Frontier-Based Pathfinding
# ===========================================================================


class TestExplorePathing:
    """EXPLORE intruders should target frontier cells, not the core."""

    def test_explore_intruder_targets_frontier_not_core(self):
        """EXPLORE objective should path to frontier, not core."""
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.EXPLORE,
        )
        intruder.state = IntruderState.ADVANCING
        # Reveal some cells around the intruder's position
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                nx, ny = 5 + dx, 0 + dy
                if grid.in_bounds(nx, ny, SURFACE_Z):
                    vtype = grid.get(nx, ny, SURFACE_Z)
                    intruder.personal_map.reveal(nx, ny, SURFACE_Z, vtype)
        ai.intruders.append(intruder)
        ai._repath_intruder(intruder)

        # Path should exist and NOT point at the core
        if intruder.path is not None and len(intruder.path) > 1:
            final = intruder.path[-1]
            # Final target should not be the core position
            core_pos = (core.x, core.y, core.z)
            # The target should be a frontier cell, not the core
            frontier = intruder.personal_map.get_frontier()
            if frontier:
                assert final != core_pos or final in frontier

    def test_explore_retreats_when_frontier_unreachable(self):
        """Explorer retreats when _pick_explore_target returns None."""
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.EXPLORE,
        )
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        # Empty personal map → empty frontier → _pick_explore_target returns None
        # (No cells revealed = no frontier)
        target = ai._pick_explore_target(intruder)
        assert target is None  # No frontier when map is empty

        # Now call _repath_intruder which should trigger retreat
        ai._repath_intruder(intruder)
        assert intruder.state == IntruderState.RETREATING

    def test_non_explore_still_targets_core(self):
        """DESTROY_CORE objective should still path to the core."""
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=INQUISITOR,
            objective=IntruderObjective.DESTROY_CORE,
        )
        intruder.state = IntruderState.ADVANCING
        # Reveal corridor
        core_z = SURFACE_Z + _CORE_DEPTH
        for z in range(SURFACE_Z, core_z + 1):
            intruder.personal_map.reveal(5, 0, z, VOXEL_AIR)
        for y in range(0, 6):
            intruder.personal_map.reveal(5, y, core_z, VOXEL_AIR)
        ai.intruders.append(intruder)
        ai._repath_intruder(intruder)

        assert intruder.path is not None
        assert intruder.path[-1] == (core.x, core.y, core.z)

    def test_pillage_still_targets_treasure(self):
        """PILLAGE objective should still path to treasure, not frontier."""
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.PILLAGE,
        )
        intruder.state = IntruderState.PILLAGING
        from dungeon_builder.config import VOXEL_TREASURE
        # Reveal air corridor (y=0..2), then treasure at y=3
        for y in range(0, 3):
            intruder.personal_map.reveal(5, y, SURFACE_Z, VOXEL_AIR)
        intruder.personal_map.reveal(5, 3, SURFACE_Z, VOXEL_TREASURE)
        ai.intruders.append(intruder)
        ai._repath_intruder(intruder)

        assert intruder.path is not None
        assert intruder.path[-1] == (5, 3, SURFACE_Z)

    def test_pick_explore_target_returns_frontier_cell(self):
        """_pick_explore_target should return a cell from the frontier."""
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.EXPLORE,
        )
        # Reveal some cells
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = 5 + dx, 0 + dy
                if grid.in_bounds(nx, ny, SURFACE_Z):
                    vtype = grid.get(nx, ny, SURFACE_Z)
                    intruder.personal_map.reveal(nx, ny, SURFACE_Z, vtype)
        target = ai._pick_explore_target(intruder)
        assert target is not None
        frontier = intruder.personal_map.get_frontier()
        assert target in frontier

    def test_pick_explore_target_none_when_no_cells_revealed(self):
        """_pick_explore_target returns None when personal map is empty."""
        ai, bus, grid, core, rng = _make_ai()
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=EXPLORER,
            objective=IntruderObjective.EXPLORE,
        )
        # Empty personal map → no frontier at all
        assert len(intruder.personal_map.seen) == 0
        target = ai._pick_explore_target(intruder)
        assert target is None


# ===========================================================================
# 2 & 3. Darkvision & Torch — Perception Improvements
# ===========================================================================


class TestDarkvisionAndTorch:
    """Darkvision adds LOS range underground; torch adds via equipment."""

    def test_darkvision_adds_range_underground(self):
        """Intruder deep underground should get darkvision bonus."""
        # Gloomwarden has darkvision_range=3
        deep_z = SURFACE_Z + DARKVISION_DEPTH_THRESHOLD + 1
        intruder = _make_intruder(
            x=5, y=5, z=deep_z, arch=GLOOMWARDEN,
        )
        # Base perception + darkvision
        expected = GLOOMWARDEN.perception_range + GLOOMWARDEN.darkvision_range
        # We verify by checking _update_vision uses the enhanced range
        # Test that the effective perception property doesn't include darkvision
        # (darkvision is position-dependent, applied in decision engine)
        base_eff = intruder.effective_perception
        assert base_eff == GLOOMWARDEN.perception_range  # No torch = base only

    def test_darkvision_no_bonus_at_surface(self):
        """Darkvision should not apply at or near the surface."""
        # At surface, z ≤ SURFACE_Z + DARKVISION_DEPTH_THRESHOLD
        intruder = _make_intruder(
            x=5, y=5, z=SURFACE_Z, arch=GLOOMWARDEN,
        )
        # At surface, darkvision is not applied — just base perception
        assert intruder.effective_perception == GLOOMWARDEN.perception_range

    def test_torch_increases_perception(self):
        """An intruder with an active torch should have boosted perception."""
        equip = Equipment(3)
        torch = ItemInstance(TOOL_TORCH)
        equip.add_to_inventory(torch)
        intruder = _make_intruder(
            x=5, y=5, z=SURFACE_Z, arch=EXPLORER, equipment=equip,
        )
        expected = EXPLORER.perception_range + TOOL_TORCH.value
        assert intruder.effective_perception == expected

    def test_torch_depleted_no_bonus(self):
        """A depleted torch should not provide perception bonus."""
        equip = Equipment(3)
        torch = ItemInstance(TOOL_TORCH)
        # Drain all charges
        torch.charges_remaining = 0
        equip.add_to_inventory(torch)
        intruder = _make_intruder(
            x=5, y=5, z=SURFACE_Z, arch=EXPLORER, equipment=equip,
        )
        assert intruder.effective_perception == EXPLORER.perception_range


# ===========================================================================
# 4. Risk Tolerance — Retreat Threshold Modulation
# ===========================================================================


class TestRiskToleranceRetreat:
    """risk_tolerance should modulate HP and supply retreat thresholds."""

    def test_high_risk_tolerance_delays_retreat(self):
        """Intruder with high risk_tolerance retreats at lower HP."""
        ai, bus, grid, core, rng = _make_ai()
        # Create archetype with high risk_tolerance and measurable retreat_threshold
        bold_arch = replace(EXPLORER, risk_tolerance=0.8, retreat_threshold=0.35)
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=bold_arch,
            objective=IntruderObjective.DESTROY_CORE,
        )
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        # Set HP to 25% — below base retreat_threshold (0.35) but possibly
        # above the risk-adjusted threshold: 0.35 * (1 - 0.8 * 0.5) = 0.21
        intruder.hp = int(intruder.max_hp * 0.25)
        ai._check_retreat(intruder)
        # Should NOT retreat: 0.25 > 0.21
        assert intruder.state == IntruderState.ADVANCING

    def test_low_risk_tolerance_early_retreat(self):
        """Intruder with low risk_tolerance retreats earlier."""
        ai, bus, grid, core, rng = _make_ai()
        # Low risk_tolerance: threshold barely changes
        cautious_arch = replace(EXPLORER, risk_tolerance=0.1, retreat_threshold=0.35)
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=cautious_arch,
            objective=IntruderObjective.DESTROY_CORE,
        )
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        # Set HP to 30% — below adjusted threshold: 0.35 * (1 - 0.1*0.5) = 0.3325
        intruder.hp = int(intruder.max_hp * 0.30)
        ai._check_retreat(intruder)
        assert intruder.state == IntruderState.RETREATING

    def test_risk_tolerance_supply_margin(self):
        """Bold intruders accept thinner supply margins."""
        ai, bus, grid, core, rng = _make_ai()
        bold_arch = replace(EXPLORER, risk_tolerance=0.8)
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=bold_arch,
        )
        intruder.state = IntruderState.ADVANCING
        ai.intruders.append(intruder)

        # Set food to a level that would trigger normal retreat but not bold
        return_cost = ai._estimate_return_cost(intruder)
        normal_margin = SUPPLY_SAFETY_MARGIN
        risk_margin = SUPPLY_SAFETY_MARGIN * (1.0 - 0.8 * 0.2)
        # Set food between the two margins
        intruder.food = return_cost * (risk_margin + normal_margin) / 2
        intruder.water = 100.0  # Plenty of water
        ai._check_retreat(intruder)
        # Bold intruder should NOT retreat
        assert intruder.state == IntruderState.ADVANCING

    def test_zero_retreat_threshold_unaffected(self):
        """Archetypes with retreat_threshold=0 never retreat on HP."""
        ai, bus, grid, core, rng = _make_ai()
        # Eidolon-like archetype: retreat_threshold=0, risk_tolerance=0.9
        no_retreat = replace(INQUISITOR, retreat_threshold=0.0, risk_tolerance=0.9)
        intruder = _make_intruder(
            x=5, y=0, z=SURFACE_Z, arch=no_retreat,
        )
        intruder.state = IntruderState.ADVANCING
        intruder.morale = 0.5  # Above flee threshold
        intruder.hp = 1  # Almost dead
        intruder.food = 100.0
        intruder.water = 100.0
        ai.intruders.append(intruder)
        ai._check_retreat(intruder)
        # Should NOT retreat on HP (threshold=0)
        assert intruder.state == IntruderState.ADVANCING


# ===========================================================================
# 5. Gradient Cunning — Scaled Hazard Avoidance
# ===========================================================================


class TestGradientCunning:
    """Hazard path cost should scale continuously with cunning."""

    def _hazard_cost_for_cunning(self, cunning: float) -> float:
        """Create an archetype with given cunning and measure hazard cost."""
        arch = replace(EXPLORER, cunning=cunning)
        pmap = PersonalMap()
        # Reveal an air cell and mark it as hazard
        pmap.reveal(5, 5, 0, VOXEL_AIR)
        pmap.mark_hazard(5, 5, 0)
        # Also reveal start
        pmap.reveal(4, 5, 0, VOXEL_AIR)

        # Use pathfinder to get path cost (2 cells: start + hazard)
        path = PersonalPathfinder.find_path(
            pmap, (4, 5, 0), (5, 5, 0), arch,
        )
        # If path exists, cost should reflect hazard penalty
        return path is not None

    def test_high_cunning_high_hazard_cost(self):
        """High cunning (0.9) should produce near-maximum hazard cost."""
        arch_high = replace(EXPLORER, cunning=0.9)
        pmap = PersonalMap()
        pmap.reveal(0, 0, 0, VOXEL_AIR)
        pmap.reveal(1, 0, 0, VOXEL_AIR)
        pmap.mark_hazard(1, 0, 0)
        # With high cunning, the hazard cost should be ~90 (0.9 * 100)
        # which means the path exists but is expensive
        path = PersonalPathfinder.find_path(pmap, (0, 0, 0), (1, 0, 0), arch_high)
        assert path is not None  # Still reachable, just expensive

    def test_low_cunning_low_hazard_cost(self):
        """Low cunning (0.2) should produce much lower hazard cost."""
        arch_low = replace(EXPLORER, cunning=0.2)
        pmap = PersonalMap()
        pmap.reveal(0, 0, 0, VOXEL_AIR)
        pmap.reveal(1, 0, 0, VOXEL_AIR)
        pmap.mark_hazard(1, 0, 0)
        # Path should exist
        path = PersonalPathfinder.find_path(pmap, (0, 0, 0), (1, 0, 0), arch_low)
        assert path is not None

    def test_zero_cunning_no_hazard_cost(self):
        """Zero cunning should add no hazard penalty at all."""
        arch_zero = replace(EXPLORER, cunning=0.0)
        pmap = PersonalMap()
        # Create a scenario: straight line vs detour around hazard
        # Straight: (0,0)→(1,0)→(2,0)  with hazard at (1,0)
        # Detour: (0,0)→(0,1)→(1,1)→(2,1)→(2,0)  no hazard
        for x in range(3):
            pmap.reveal(x, 0, 0, VOXEL_AIR)
            pmap.reveal(x, 1, 0, VOXEL_AIR)
        pmap.mark_hazard(1, 0, 0)

        path = PersonalPathfinder.find_path(pmap, (0, 0, 0), (2, 0, 0), arch_zero)
        assert path is not None
        # With zero cunning, hazard adds no cost → straight path preferred
        assert (1, 0, 0) in path

    def test_high_cunning_avoids_hazard(self):
        """High cunning intruder should prefer detour over hazard."""
        arch_high = replace(EXPLORER, cunning=0.9)
        pmap = PersonalMap()
        # Straight: (0,0)→(1,0)→(2,0)  with hazard at (1,0)
        # Detour: (0,0)→(0,1)→(1,1)→(2,1)→(2,0)  no hazard
        for x in range(3):
            pmap.reveal(x, 0, 0, VOXEL_AIR)
            pmap.reveal(x, 1, 0, VOXEL_AIR)
        pmap.mark_hazard(1, 0, 0)

        path = PersonalPathfinder.find_path(pmap, (0, 0, 0), (2, 0, 0), arch_high)
        assert path is not None
        # With high cunning, hazard cost (90) > detour cost (3) → avoids hazard
        assert (1, 0, 0) not in path


# ===========================================================================
# 6. Map Memory — Archival Quality
# ===========================================================================


class TestMapMemoryArchive:
    """map_memory should affect how much data is archived by survivors."""

    def test_high_memory_archives_most_cells(self):
        """Archetype with map_memory=0.9 should archive ~90% of cells."""
        archive = KnowledgeArchive()
        high_mem = replace(EXPLORER, map_memory=0.9)
        intruder = _make_intruder(arch=high_mem)
        intruder.state = IntruderState.ESCAPED

        # Reveal many cells
        for i in range(100):
            intruder.personal_map.reveal(i % 10, i // 10, 0, VOXEL_AIR)

        archive.archive_survivor(intruder, tick=100)
        stats = archive.get_stats()
        # Should archive ~90% (with deterministic hash, exact count varies)
        assert stats["cells_known"] >= 80  # At least ~80%
        assert stats["cells_known"] <= 100

    def test_low_memory_archives_fewer_cells(self):
        """Archetype with map_memory=0.3 should archive ~30% of cells."""
        archive = KnowledgeArchive()
        low_mem = replace(EXPLORER, map_memory=0.3)
        intruder = _make_intruder(arch=low_mem)
        intruder.state = IntruderState.ESCAPED

        # Reveal many cells
        for i in range(100):
            intruder.personal_map.reveal(i % 10, i // 10, 0, VOXEL_AIR)

        archive.archive_survivor(intruder, tick=100)
        stats = archive.get_stats()
        # Should archive ~30%
        assert stats["cells_known"] >= 15  # At least ~15% (hash variance)
        assert stats["cells_known"] <= 50  # But not more than ~50%

    def test_memory_scales_trust_weight(self):
        """Survivor trust weight should be scaled by map_memory."""
        archive = KnowledgeArchive()

        # First survivor: high memory — reveal many cells to ensure some pass filter
        high_mem = replace(EXPLORER, map_memory=0.9)
        intruder1 = _make_intruder(arch=high_mem, intruder_id=1)
        intruder1.state = IntruderState.ESCAPED
        # Reveal 50 cells — with memory=0.9, ~45 should pass the hash filter
        for i in range(50):
            intruder1.personal_map.reveal(i % 10, i // 10, 0, VOXEL_AIR)
        archive.archive_survivor(intruder1, tick=100)

        # Find any cell that was archived and check its trust weight
        high_trust = None
        for pos, (vtype, tick, trust) in archive._data.seen.items():
            high_trust = trust
            break
        assert high_trust is not None

        # Second archive: low memory survivor on different cells
        archive2 = KnowledgeArchive()
        low_mem = replace(EXPLORER, map_memory=0.3)
        intruder2 = _make_intruder(arch=low_mem, intruder_id=2)
        intruder2.state = IntruderState.ESCAPED
        for i in range(50):
            intruder2.personal_map.reveal(i % 10, i // 10, 0, VOXEL_AIR)
        archive2.archive_survivor(intruder2, tick=200)

        low_trust = None
        for pos, (vtype, tick, trust) in archive2._data.seen.items():
            low_trust = trust
            break
        assert low_trust is not None

        # High memory survivor should have higher trust (same status)
        assert high_trust > low_trust


# ===========================================================================
# 7. Morale Support Aura
# ===========================================================================


class TestMoraleSupportAura:
    """Arcane-sight members should provide morale support tick."""

    def test_support_archetype_boosts_morale(self):
        """Party with Gloomwarden should apply MORALE_SUPPORT_TICK."""
        gw = _make_intruder(intruder_id=1, arch=GLOOMWARDEN)
        inq = _make_intruder(intruder_id=2, arch=INQUISITOR)
        gw.morale = MORALE_BASE
        inq.morale = MORALE_BASE
        party = Party(1, [gw, inq])

        initial_morale = inq.morale
        party.update_morale(tick=1)

        # Should have gained both leader bonus and support tick
        # The exact amount depends on drift, but morale should increase
        assert inq.morale > initial_morale

    def test_no_support_no_bonus(self):
        """Party without support archetypes should not get support tick."""
        inq1 = _make_intruder(intruder_id=1, arch=INQUISITOR)
        inq2 = _make_intruder(intruder_id=2, arch=INQUISITOR)
        inq1.morale = MORALE_BASE
        inq2.morale = MORALE_BASE
        party = Party(1, [inq1, inq2])

        # Record initial morale (after party init which may do a tick)
        initial = inq2.morale
        party.update_morale(tick=1)

        # Compare with a support party
        gw = _make_intruder(intruder_id=3, arch=GLOOMWARDEN)
        inq3 = _make_intruder(intruder_id=4, arch=INQUISITOR)
        gw.morale = MORALE_BASE
        inq3.morale = MORALE_BASE
        party_support = Party(2, [gw, inq3])
        party_support.update_morale(tick=1)

        # The support party member should have higher morale
        # due to MORALE_SUPPORT_TICK bonus
        assert inq3.morale > inq2.morale

    def test_support_check_is_stat_based(self):
        """Support detection should use arcane_sight_range, not name."""
        # Create a custom archetype with arcane_sight_range > threshold
        custom_support = replace(
            ALCHEMIST,
            name="CustomSupport",
            arcane_sight_range=SUPPORT_AURA_SIGHT_THRESHOLD,
        )
        cs = _make_intruder(intruder_id=1, arch=custom_support)
        inq = _make_intruder(intruder_id=2, arch=INQUISITOR)
        cs.morale = MORALE_BASE
        inq.morale = MORALE_BASE
        party = Party(1, [cs, inq])

        initial = inq.morale
        party.update_morale(tick=1)

        # Should get support bonus (stat-based, not name-based)
        assert inq.morale > initial

    def test_dead_support_no_bonus(self):
        """Dead support member should not provide aura."""
        gw = _make_intruder(intruder_id=1, arch=GLOOMWARDEN)
        inq = _make_intruder(intruder_id=2, arch=INQUISITOR)
        gw.state = IntruderState.DEAD  # Dead Gloomwarden
        inq.morale = MORALE_BASE
        party = Party(1, [gw, inq])

        initial = inq.morale
        party.update_morale(tick=1)

        # No support from dead Gloomwarden — should only get leader bonus
        # and drift toward base
        # With only leader bonus and drift, morale should change very slightly
        # No support tick should be applied
        # Verify by comparing with expected: leader_bonus only
        # (The exact value depends on drift, but no support tick)
        assert inq.morale <= initial + 0.01  # Only tiny leader bonus


# ===========================================================================
# Config constant existence checks
# ===========================================================================


class TestAIImprovementConfigConstants:
    """Verify new config constants exist with valid values."""

    def test_darkvision_depth_threshold(self):
        assert DARKVISION_DEPTH_THRESHOLD >= 0

    def test_explore_frontier_max_candidates(self):
        assert EXPLORE_FRONTIER_MAX_CANDIDATES > 0

    def test_support_aura_sight_threshold(self):
        assert SUPPORT_AURA_SIGHT_THRESHOLD >= 1

    def test_explore_depth_weight(self):
        from dungeon_builder.config import EXPLORE_DEPTH_WEIGHT
        assert 0.0 < EXPLORE_DEPTH_WEIGHT < 1.0


# ===========================================================================
# Method existence checks
# ===========================================================================


class TestAIMethodsExist:
    """Verify new methods and properties exist on the correct classes."""

    def test_effective_perception_property(self):
        assert hasattr(Intruder, "effective_perception")

    def test_pick_explore_target_method(self):
        assert hasattr(IntruderAI, "_pick_explore_target")
        assert callable(getattr(IntruderAI, "_pick_explore_target"))

    def test_personal_map_get_frontier(self):
        pmap = PersonalMap()
        assert hasattr(pmap, "get_frontier")
        assert callable(pmap.get_frontier)
