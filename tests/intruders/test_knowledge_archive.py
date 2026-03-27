"""Tests for dungeon_builder.intruders.knowledge_archive -- faction knowledge with uncertainty.

Dependencies: intruders.knowledge_archive, intruders.personal_map,
    intruders.archetypes, config
Dependents: (none)
"""

import pytest

from dungeon_builder.intruders.knowledge_archive import FactionMap, KnowledgeArchive
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.intruders.archetypes import IntruderStatus
from dungeon_builder.config import (
    VOXEL_STONE,
    VOXEL_AIR,
    VOXEL_SPIKE,
    VOXEL_LAVA,
    VOXEL_TARP,
    VOXEL_TREASURE,
    VOXEL_DOOR,
    KNOWLEDGE_STALE_TICKS,
    KNOWLEDGE_UNCERTAIN_THRESHOLD,
    KNOWLEDGE_CONTRADICTION_BASE,
    KNOWLEDGE_CONFIRM_DECAY,
    KNOWLEDGE_CHANGE_UNCERTAINTY,
)


class _FakeArchetype:
    """Minimal archetype stub for archive tests."""

    def __init__(self, map_memory: float = 1.0):
        self.map_memory = map_memory


class _FakeIntruder:
    """Minimal intruder stub for archive tests."""

    def __init__(
        self,
        personal_map: PersonalMap | None = None,
        status: IntruderStatus = IntruderStatus.GRUNT,
        map_memory: float = 1.0,
    ):
        self.personal_map = personal_map or PersonalMap()
        self.status = status
        self.archetype = _FakeArchetype(map_memory)


# ---------- FactionMap basics ----------


class TestFactionMap:
    def test_initially_empty(self):
        fm = FactionMap()
        assert len(fm.seen) == 0
        assert len(fm.hazards) == 0
        assert len(fm.treasures) == 0
        assert len(fm.doors) == 0
        assert len(fm.uncertainty) == 0


# ---------- archive_survivor ----------


class TestArchiveSurvivor:
    def test_archive_single_survivor(self):
        ka = KnowledgeArchive()
        pmap = PersonalMap()
        pmap.reveal(2, 3, 4, VOXEL_STONE, 0)
        intruder = _FakeIntruder(pmap)
        ka.archive_survivor(intruder, tick=100)

        stats = ka.get_stats()
        assert stats["cells_known"] == 1

    def test_confirmation_decreases_uncertainty(self):
        ka = KnowledgeArchive()
        pos = (5, 5, 5)

        # First report with some uncertainty
        pmap1 = PersonalMap()
        pmap1.reveal(5, 5, 5, VOXEL_STONE, 0)
        i1 = _FakeIntruder(pmap1)
        ka.archive_survivor(i1, tick=100)

        # Manually inject uncertainty
        faction = ka._data
        faction.uncertainty[pos] = 0.6

        # Second report: SAME type -> confirmation -> lower uncertainty
        pmap2 = PersonalMap()
        pmap2.reveal(5, 5, 5, VOXEL_STONE, 0)
        i2 = _FakeIntruder(pmap2)
        ka.archive_survivor(i2, tick=200)

        assert faction.uncertainty.get(pos, 0.0) < 0.6

    def test_contradiction_increases_uncertainty(self):
        ka = KnowledgeArchive()
        pos = (5, 5, 5)

        # First report: STONE
        pmap1 = PersonalMap()
        pmap1.reveal(5, 5, 5, VOXEL_STONE, 0)
        i1 = _FakeIntruder(pmap1)
        ka.archive_survivor(i1, tick=100)

        # Second report: AIR (contradicts STONE)
        pmap2 = PersonalMap()
        pmap2.reveal(5, 5, 5, VOXEL_AIR, 0)
        i2 = _FakeIntruder(pmap2)
        ka.archive_survivor(i2, tick=200)

        faction = ka._data
        unc = faction.uncertainty.get(pos, 0.0)
        assert unc > 0.0

    def test_hazard_tracking(self):
        ka = KnowledgeArchive()
        pmap = PersonalMap()
        pmap.reveal(1, 1, 1, VOXEL_SPIKE, 0)
        pmap.reveal(2, 2, 2, VOXEL_LAVA, 0)
        pmap.reveal(3, 3, 3, VOXEL_TARP, 0)
        intruder = _FakeIntruder(pmap)
        ka.archive_survivor(intruder, tick=100)

        stats = ka.get_stats()
        assert stats["hazards_known"] == 3

    def test_treasure_tracking(self):
        ka = KnowledgeArchive()
        pmap = PersonalMap()
        pmap.reveal(4, 4, 4, VOXEL_TREASURE, 0)
        intruder = _FakeIntruder(pmap)
        ka.archive_survivor(intruder, tick=100)

        stats = ka.get_stats()
        assert stats["treasures_known"] == 1

    def test_door_tracking(self):
        ka = KnowledgeArchive()
        pmap = PersonalMap()
        pmap.reveal(6, 6, 6, VOXEL_DOOR, 0)
        pmap.doors[(6, 6, 6)] = 1  # closed
        intruder = _FakeIntruder(pmap)
        ka.archive_survivor(intruder, tick=100)

        faction = ka._data
        assert (6, 6, 6) in faction.doors
        assert faction.doors[(6, 6, 6)] == 1

    def test_hazard_removed_when_type_changes(self):
        ka = KnowledgeArchive()
        pmap1 = PersonalMap()
        pmap1.reveal(1, 1, 1, VOXEL_SPIKE, 0)
        i1 = _FakeIntruder(pmap1)
        ka.archive_survivor(i1, tick=100)
        assert (1, 1, 1) in ka._data.hazards

        # Second report: no longer a spike
        pmap2 = PersonalMap()
        pmap2.reveal(1, 1, 1, VOXEL_STONE, 0)
        i2 = _FakeIntruder(pmap2)
        ka.archive_survivor(i2, tick=200)
        assert (1, 1, 1) not in ka._data.hazards


# ---------- inject_knowledge ----------


class TestInjectKnowledge:
    def test_inject_empty_archive(self):
        ka = KnowledgeArchive()
        pmap = PersonalMap()
        ka.inject_knowledge(pmap, current_tick=100, cunning=0.5)
        assert len(pmap.seen) == 0

    def test_inject_populates_personal_map(self):
        ka = KnowledgeArchive()
        # Archive some data
        pmap_src = PersonalMap()
        pmap_src.reveal(1, 2, 3, VOXEL_STONE, 0)
        i = _FakeIntruder(pmap_src)
        ka.archive_survivor(i, tick=100)

        # Inject into new intruder
        pmap_new = PersonalMap()
        ka.inject_knowledge(pmap_new, current_tick=110, cunning=0.0)
        assert (1, 2, 3) in pmap_new.seen

    def test_inject_filters_stale_data(self):
        ka = KnowledgeArchive()
        pmap_src = PersonalMap()
        pmap_src.reveal(1, 1, 1, VOXEL_STONE, 0)
        i = _FakeIntruder(pmap_src)
        ka.archive_survivor(i, tick=100)

        # Inject far in the future -> stale
        pmap_new = PersonalMap()
        ka.inject_knowledge(
            pmap_new,
            current_tick=100 + KNOWLEDGE_STALE_TICKS + 1,
            cunning=0.0,
        )
        assert len(pmap_new.seen) == 0

    def test_inject_filters_uncertain_data(self):
        ka = KnowledgeArchive()
        pmap_src = PersonalMap()
        pmap_src.reveal(1, 1, 1, VOXEL_STONE, 0)
        i = _FakeIntruder(pmap_src)
        ka.archive_survivor(i, tick=100)

        # Make cell very uncertain
        ka._data.uncertainty[(1, 1, 1)] = 0.99  # > threshold

        pmap_new = PersonalMap()
        ka.inject_knowledge(pmap_new, current_tick=110, cunning=0.0)
        assert len(pmap_new.seen) == 0

    def test_inject_cunning_adjusts_threshold(self):
        """High cunning lowers the threshold -> more data filtered out."""
        ka = KnowledgeArchive()
        pmap_src = PersonalMap()
        pmap_src.reveal(1, 1, 1, VOXEL_STONE, 0)
        i = _FakeIntruder(pmap_src)
        ka.archive_survivor(i, tick=100)

        # Set uncertainty just below normal threshold
        just_below = KNOWLEDGE_UNCERTAIN_THRESHOLD - 0.05
        ka._data.uncertainty[(1, 1, 1)] = just_below

        # Low cunning: threshold = 0.7, data passes
        pmap_low = PersonalMap()
        ka.inject_knowledge(pmap_low, current_tick=110, cunning=0.0)
        assert (1, 1, 1) in pmap_low.seen

        # High cunning: threshold = 0.7 - 1.0*0.2 = 0.5, data filtered
        pmap_high = PersonalMap()
        ka.inject_knowledge(pmap_high, current_tick=110, cunning=1.0)
        assert (1, 1, 1) not in pmap_high.seen


# ---------- on_voxel_changed ----------


class TestOnVoxelChanged:
    def test_voxel_change_increases_uncertainty(self):
        ka = KnowledgeArchive()
        pmap_src = PersonalMap()
        pmap_src.reveal(1, 1, 1, VOXEL_STONE, 0)
        i = _FakeIntruder(pmap_src)
        ka.archive_survivor(i, tick=100)

        ka.on_voxel_changed(1, 1, 1)
        unc = ka._data.uncertainty.get((1, 1, 1), 0.0)
        assert unc == pytest.approx(KNOWLEDGE_CHANGE_UNCERTAINTY)

    def test_voxel_change_unknown_cell_no_crash(self):
        ka = KnowledgeArchive()
        # Should not raise even if cell was never archived
        ka.on_voxel_changed(99, 99, 99)


# ---------- getters ----------


class TestGetters:
    def test_get_uncertainty_unknown_cell(self):
        ka = KnowledgeArchive()
        assert ka.get_uncertainty(0, 0, 0) == 0.0

    def test_get_stats_counts(self):
        ka = KnowledgeArchive()
        pmap = PersonalMap()
        pmap.reveal(1, 1, 1, VOXEL_STONE, 0)
        pmap.reveal(2, 2, 2, VOXEL_SPIKE, 0)
        pmap.reveal(3, 3, 3, VOXEL_TREASURE, 0)
        i = _FakeIntruder(pmap)
        ka.archive_survivor(i, tick=100)

        stats = ka.get_stats()
        assert stats["cells_known"] == 3
        assert stats["hazards_known"] == 1
        assert stats["treasures_known"] == 1
        assert stats["avg_uncertainty"] == 0.0
