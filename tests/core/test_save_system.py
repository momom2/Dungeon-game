"""Tests for dungeon_builder.core.save_system — save/load round-trip."""

import json
import zipfile

import numpy as np
import pytest

from dungeon_builder.core.save_system import (
    SaveSystem,
    SaveData,
    SAVE_VERSION,
    _GRID_ARRAY_NAMES,
    _pos_to_str,
    _str_to_pos,
    _serialize_personal_map,
    _deserialize_personal_map,
    _serialize_intruder,
    _deserialize_intruder,
    _serialize_dig_job,
    _deserialize_dig_job,
)


# ── Fixtures ──────────────────────────────────────────────────────────


class FakeEventBus:
    """Minimal event bus stub for tests."""

    def __init__(self):
        self._subs = {}

    def subscribe(self, event, fn):
        self._subs.setdefault(event, []).append(fn)

    def publish(self, event, **kwargs):
        for fn in self._subs.get(event, []):
            fn(**kwargs)


class FakeVoxelGrid:
    """Minimal VoxelGrid stub with the 17 arrays (14 original + 3 velocity)."""

    def __init__(self, w=8, d=8, h=5):
        self.width = w
        self.depth = d
        self.height = h
        self.grid = np.zeros((w, d, h), dtype=np.uint8)
        self.humidity = np.zeros((w, d, h), dtype=np.float32)
        self.temperature = np.zeros((w, d, h), dtype=np.float32)
        self.loose = np.zeros((w, d, h), dtype=np.bool_)
        self.load = np.zeros((w, d, h), dtype=np.float32)
        self.shear_load = np.zeros((w, d, h), dtype=np.float32)
        self.stress_ratio = np.zeros((w, d, h), dtype=np.float32)
        self.fall_distance = np.zeros((w, d, h), dtype=np.uint8)
        self.water_level = np.zeros((w, d, h), dtype=np.uint8)
        self.thermal_fatigue = np.zeros((w, d, h), dtype=np.float32)
        self.block_state = np.zeros((w, d, h), dtype=np.uint8)
        self.metal_type = np.zeros((w, d, h), dtype=np.uint8)
        self.claimed = np.zeros((w, d, h), dtype=np.bool_)
        self.visible = np.zeros((w, d, h), dtype=np.bool_)
        self.water_vx = np.zeros((w, d, h), dtype=np.float32)
        self.water_vy = np.zeros((w, d, h), dtype=np.float32)
        self.water_vz = np.zeros((w, d, h), dtype=np.float32)
        self._dirty_chunks = set()

    def mark_all_dirty(self):
        self._dirty_chunks.add("all")


class FakeGameState:
    def __init__(self, seed=42):
        self.seed = seed
        self.build_mode = "dig"
        self.game_over = False
        self.menu_open = False
        self.craft_mode_active = False


class FakeCore:
    def __init__(self, x=32, y=32, z=10):
        self.x = x
        self.y = y
        self.z = z
        self.hp = 500
        self.max_hp = 500
        self.alive = True


class FakeMoveSystem:
    def __init__(self):
        self.held_materials = {}
        self.held_temperatures = {}
        self.held_humidities = {}
        self.held_metal_types = {}
        self._last_picked_type = None


class FakeDigJob:
    __slots__ = ("x", "y", "z", "ticks_remaining", "total_ticks")

    def __init__(self, x, y, z, total):
        self.x = x
        self.y = y
        self.z = z
        self.ticks_remaining = total
        self.total_ticks = total


class FakeBuildSystem:
    def __init__(self):
        self.dig_queue = []
        self.active_digs = []
        self.pending_digs = []


class FakeTimeManager:
    def __init__(self):
        self.tick_count = 0


class FakeIntruderAI:
    def __init__(self):
        self.intruders = []
        self.parties = []
        self._next_id = 1
        self._next_party_id = 1
        self._spawn_timer = 0
        self._alarm_cooldowns = {}
        self._game_over = False
        self.spawning_enabled = False


def _make_intruder(intruder_id=1, x=5, y=5, z=0, archetype_name="Inquisitor",
                    hp=None, state_name="ADVANCING", objective_name="DESTROY_CORE",
                    level=1):
    """Create a real Intruder object for serialization tests."""
    from dungeon_builder.intruders.agent import Intruder, IntruderState
    from dungeon_builder.intruders.archetypes import (
        ARCHETYPE_BY_NAME, IntruderObjective,
    )
    from dungeon_builder.intruders.personal_map import PersonalMap

    archetype = ARCHETYPE_BY_NAME[archetype_name]

    pmap = PersonalMap()
    pmap.reveal(x, y, z, 0)  # reveal starting cell as air

    objective = IntruderObjective[objective_name]
    intruder = Intruder(
        intruder_id=intruder_id,
        x=x, y=y, z=z,
        archetype=archetype,
        objective=objective,
        personal_map=pmap,
        level=level,
    )
    intruder.state = IntruderState[state_name]
    if hp is not None:
        intruder.hp = hp
    return intruder


def _make_party(party_id, members):
    """Create a real Party object for tests."""
    from dungeon_builder.intruders.party import Party
    return Party(party_id, members)


def _make_subsystems(voxel_grid=None):
    """Create a full set of fake subsystems for save/load tests."""
    gs = FakeGameState()
    vg = voxel_grid or FakeVoxelGrid()
    core = FakeCore()
    ms = FakeMoveSystem()
    bs = FakeBuildSystem()
    tm = FakeTimeManager()
    ai = FakeIntruderAI()
    return gs, vg, core, ms, bs, tm, ai


# ── Helper function tests ────────────────────────────────────────────


class TestPositionSerialization:
    def test_pos_to_str(self):
        assert _pos_to_str((1, 2, 3)) == "1,2,3"

    def test_str_to_pos(self):
        assert _str_to_pos("1,2,3") == (1, 2, 3)

    def test_roundtrip(self):
        pos = (10, 20, 5)
        assert _str_to_pos(_pos_to_str(pos)) == pos

    def test_negative_coords(self):
        pos = (-1, 0, 3)
        assert _str_to_pos(_pos_to_str(pos)) == pos


# ── PersonalMap serialization ─────────────────────────────────────────


class TestPersonalMapSerialization:
    def test_empty_map_roundtrip(self):
        from dungeon_builder.intruders.personal_map import PersonalMap
        pmap = PersonalMap()
        data = _serialize_personal_map(pmap)
        restored = _deserialize_personal_map(data)
        assert len(restored.seen) == 0
        assert len(restored.hazards) == 0

    def test_seen_cells_roundtrip(self):
        from dungeon_builder.intruders.personal_map import PersonalMap
        pmap = PersonalMap()
        pmap.reveal(1, 2, 3, 5)  # stone
        pmap.reveal(4, 5, 6, 0)  # air
        data = _serialize_personal_map(pmap)
        restored = _deserialize_personal_map(data)
        assert restored.seen[(1, 2, 3)] == 5
        assert restored.seen[(4, 5, 6)] == 0

    def test_hazards_roundtrip(self):
        from dungeon_builder.intruders.personal_map import PersonalMap
        from dungeon_builder.config import VOXEL_SPIKE
        pmap = PersonalMap()
        pmap.reveal(3, 3, 3, VOXEL_SPIKE)
        data = _serialize_personal_map(pmap)
        restored = _deserialize_personal_map(data)
        assert (3, 3, 3) in restored.hazards

    def test_doors_roundtrip(self):
        from dungeon_builder.intruders.personal_map import PersonalMap
        from dungeon_builder.config import VOXEL_DOOR
        pmap = PersonalMap()
        pmap.reveal(2, 2, 2, VOXEL_DOOR, block_state=1)
        data = _serialize_personal_map(pmap)
        restored = _deserialize_personal_map(data)
        assert restored.doors[(2, 2, 2)] == 1

    def test_baits_and_alarms_roundtrip(self):
        from dungeon_builder.intruders.personal_map import PersonalMap
        pmap = PersonalMap()
        pmap.baits.add((1, 1, 1))
        pmap.alarms.add((2, 2, 2))
        data = _serialize_personal_map(pmap)
        restored = _deserialize_personal_map(data)
        assert (1, 1, 1) in restored.baits
        assert (2, 2, 2) in restored.alarms

    def test_treasures_roundtrip(self):
        from dungeon_builder.intruders.personal_map import PersonalMap
        from dungeon_builder.config import VOXEL_TREASURE
        pmap = PersonalMap()
        pmap.reveal(7, 7, 3, VOXEL_TREASURE)
        data = _serialize_personal_map(pmap)
        restored = _deserialize_personal_map(data)
        assert (7, 7, 3) in restored.treasures


# ── Intruder serialization ───────────────────────────────────────────


class TestIntruderSerialization:
    def test_basic_roundtrip(self):
        intruder = _make_intruder()
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.id == intruder.id
        assert restored.archetype.name == "Inquisitor"
        assert restored.x == intruder.x
        assert restored.y == intruder.y
        assert restored.z == intruder.z

    def test_hp_preserved(self):
        intruder = _make_intruder(hp=42)
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.hp == 42

    def test_state_preserved(self):
        from dungeon_builder.intruders.agent import IntruderState
        intruder = _make_intruder(state_name="RETREATING")
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.state == IntruderState.RETREATING

    def test_objective_preserved(self):
        from dungeon_builder.intruders.archetypes import IntruderObjective
        intruder = _make_intruder(objective_name="PILLAGE")
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.objective == IntruderObjective.PILLAGE

    def test_personal_map_preserved(self):
        intruder = _make_intruder()
        intruder.personal_map.reveal(10, 10, 2, 5)
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.personal_map.get_type(10, 10, 2) == 5

    def test_dig_progress_preserved(self):
        intruder = _make_intruder()
        intruder.dig_progress[(3, 4, 5)] = 10
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.dig_progress[(3, 4, 5)] == 10

    def test_path_preserved(self):
        intruder = _make_intruder()
        intruder.path = [(1, 1, 0), (2, 2, 0), (3, 3, 0)]
        intruder.path_index = 1
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.path == [(1, 1, 0), (2, 2, 0), (3, 3, 0)]
        assert restored.path_index == 1
        # Verify tuples (not lists)
        assert isinstance(restored.path[0], tuple)

    def test_eidolon_archetype_roundtrip(self):
        intruder = _make_intruder(archetype_name="Eidolon")
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.archetype.name == "Eidolon"

    def test_level_and_status_preserved(self):
        from dungeon_builder.intruders.archetypes import IntruderStatus
        intruder = _make_intruder(level=3)
        intruder.status = IntruderStatus.ELITE
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.level == 3
        assert restored.status == IntruderStatus.ELITE

    def test_morale_preserved(self):
        intruder = _make_intruder()
        intruder.morale = 0.75
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.morale == pytest.approx(0.75)

    def test_interaction_state_preserved(self):
        intruder = _make_intruder()
        intruder.interaction_type = "bash_door"
        intruder.interaction_target = (4, 5, 6)
        intruder.interaction_ticks = 15
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored.interaction_type == "bash_door"
        assert restored.interaction_target == (4, 5, 6)
        assert restored.interaction_ticks == 15

    def test_unknown_archetype_returns_none(self):
        data = {
            "id": 99,
            "archetype_name": "NonexistentType",
            "x": 0, "y": 0, "z": 0,
            "hp": 10, "max_hp": 10,
            "shield_hp": 0,
            "state": "ADVANCING",
            "objective": "DESTROY_CORE",
            "path": None,
            "path_index": 0,
            "ticks_since_move": 0,
            "move_interval": 5,
            "ticks_since_attack": 0,
            "attack_interval": 20,
            "party_id": None,
            "loyalty_modifier": 0.0,
            "interaction_type": None,
            "interaction_target": None,
            "interaction_ticks": 0,
            "loot_count": 0,
            "level": 1,
            "status": "GRUNT",
            "morale": 0.5,
            "food": 10.0,
            "water": 8.0,
            "maps_collected": 0,
            "entertainment": 1.0,
            "personal_map": {"seen": {}, "hazards": [], "treasures": [],
                             "doors": {}, "baits": [], "alarms": []},
            "equipment": {"base_slots": 3, "gear": [], "inventory": []},
            "familiars": [],
            "dig_progress": {},
        }
        assert _deserialize_intruder(data) is None

    def test_vision_dirty_reset_on_load(self):
        intruder = _make_intruder()
        intruder._vision_dirty = False
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored._vision_dirty is True

    def test_path_cache_reset_on_load(self):
        intruder = _make_intruder()
        intruder._path_cache_key = ("cached",)
        data = _serialize_intruder(intruder)
        restored = _deserialize_intruder(data)
        assert restored._path_cache_key is None


# ── DigJob serialization ─────────────────────────────────────────────


class TestDigJobSerialization:
    def test_roundtrip(self):
        from dungeon_builder.building.build_system import DigJob
        job = DigJob(5, 10, 3, 40)
        job.ticks_remaining = 25
        data = _serialize_dig_job(job)
        restored = _deserialize_dig_job(data)
        assert restored.x == 5
        assert restored.y == 10
        assert restored.z == 3
        assert restored.total_ticks == 40
        assert restored.ticks_remaining == 25


# ── Full save/load round-trip ────────────────────────────────────────


class TestSaveLoadRoundtrip:
    def test_empty_world_roundtrip(self, tmp_path):
        """Save and load an empty world."""
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd is not None
        assert sd.version == SAVE_VERSION
        assert sd.seed == 42

    def test_grid_arrays_preserved(self, tmp_path):
        """All 14 grid arrays should round-trip with correct dtypes."""
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        # Set some non-zero values
        vg.grid[1, 2, 3] = 5
        vg.humidity[0, 0, 0] = 0.75
        vg.temperature[3, 3, 3] = 500.0
        vg.loose[2, 2, 2] = True
        vg.water_level[4, 4, 4] = 200
        vg.block_state[5, 5, 1] = 1
        vg.claimed[0, 0, 0] = True
        vg.visible[0, 0, 0] = True

        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd is not None
        assert len(sd.grid_arrays) == 17  # 14 original + 3 velocity
        assert sd.grid_arrays["grid"][1, 2, 3] == 5
        assert sd.grid_arrays["humidity"][0, 0, 0] == pytest.approx(0.75)
        assert sd.grid_arrays["temperature"][3, 3, 3] == pytest.approx(500.0)
        assert bool(sd.grid_arrays["loose"][2, 2, 2]) is True
        assert sd.grid_arrays["water_level"][4, 4, 4] == 200
        assert sd.grid_arrays["block_state"][5, 5, 1] == 1
        assert bool(sd.grid_arrays["claimed"][0, 0, 0]) is True
        assert bool(sd.grid_arrays["visible"][0, 0, 0]) is True

    def test_grid_dtype_preservation(self, tmp_path):
        """Array dtypes should be preserved through save/load."""
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.grid_arrays["grid"].dtype == np.uint8
        assert sd.grid_arrays["humidity"].dtype == np.float32
        assert sd.grid_arrays["temperature"].dtype == np.float32
        assert sd.grid_arrays["loose"].dtype == np.bool_
        assert sd.grid_arrays["water_level"].dtype == np.uint8
        assert sd.grid_arrays["thermal_fatigue"].dtype == np.float32

    def test_game_state_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        gs.build_mode = "move"
        gs.game_over = True
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.build_mode == "move"
        assert sd.game_over is True

    def test_core_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        core.hp = 250
        core.alive = False
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.core_hp == 250
        assert sd.core_max_hp == 500
        assert sd.core_alive is False
        assert sd.core_x == 32
        assert sd.core_y == 32
        assert sd.core_z == 10

    def test_move_system_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        ms.held_materials = {5: 10, 40: 3}
        ms.held_temperatures = {5: 100.0, 40: 25.0}
        ms.held_humidities = {5: 0.5}
        ms.held_metal_types = {40: 2}
        ms._last_picked_type = 5
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.held_materials == {5: 10, 40: 3}
        assert sd.held_temperatures[5] == pytest.approx(100.0)
        assert sd.held_humidities[5] == pytest.approx(0.5)
        assert sd.held_metal_types[40] == 2
        assert sd.last_picked_type == 5

    def test_build_system_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        bs.dig_queue = [FakeDigJob(1, 2, 3, 40)]
        bs.active_digs = [FakeDigJob(4, 5, 6, 30)]
        bs.active_digs[0].ticks_remaining = 15
        bs.pending_digs = [FakeDigJob(7, 8, 9, 0)]
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert len(sd.dig_queue) == 1
        assert sd.dig_queue[0]["x"] == 1
        assert len(sd.active_digs) == 1
        assert sd.active_digs[0]["ticks_remaining"] == 15
        assert len(sd.pending_digs) == 1

    def test_tick_count_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        tm.tick_count = 9999
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.tick_count == 9999

    def test_intruders_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        i1 = _make_intruder(intruder_id=1, x=5, y=5, z=0, hp=80)
        i2 = _make_intruder(intruder_id=2, x=10, y=10, z=1,
                            archetype_name="Explorer", state_name="PILLAGING")
        ai.intruders = [i1, i2]
        ai._next_id = 3
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert len(sd.intruders) == 2
        assert sd.intruders[0].id == 1
        assert sd.intruders[0].hp == 80
        assert sd.intruders[1].archetype.name == "Explorer"
        assert sd.next_intruder_id == 3

    def test_parties_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        i1 = _make_intruder(intruder_id=1)
        i2 = _make_intruder(intruder_id=2, archetype_name="Gloomwarden")
        party = _make_party(1, [i1, i2])
        ai.intruders = [i1, i2]
        ai.parties = [party]
        ai._next_party_id = 2
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert len(sd.parties) == 1
        assert set(sd.parties[0]["member_ids"]) == {1, 2}
        assert sd.next_party_id == 2

    def test_multiple_parties_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        i1 = _make_intruder(intruder_id=1, archetype_name="Eidolon")
        i2 = _make_intruder(intruder_id=2, archetype_name="Eidolon")
        i3 = _make_intruder(intruder_id=3, archetype_name="Alchemist")
        party1 = _make_party(1, [i1, i2])
        party2 = _make_party(2, [i3])
        ai.intruders = [i1, i2, i3]
        ai.parties = [party1, party2]
        ai._next_party_id = 3
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert len(sd.parties) == 2
        assert set(sd.parties[0]["member_ids"]) == {1, 2}
        assert sd.parties[1]["member_ids"] == [3]
        assert sd.next_party_id == 3

    def test_spawning_enabled_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        ai.spawning_enabled = True
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.spawning_enabled is True

    def test_save_creates_parent_dirs(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        path = tmp_path / "deep" / "nested" / "save.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        assert path.is_file()

    def test_save_is_valid_zip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            assert "metadata.json" in names
            assert "grid_arrays.npz" in names
            assert "game_state.json" in names
            assert "core.json" in names
            assert "move_system.json" in names
            assert "build_system.json" in names
            assert "intruders.json" in names
            assert "parties.json" in names
            assert "intruder_ai.json" in names

    def test_timestamp_set(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.timestamp > 0


# ── Error handling ────────────────────────────────────────────────────


class TestLoadErrors:
    def test_load_nonexistent_file(self, tmp_path):
        result = SaveSystem.load(tmp_path / "nope.dungeon")
        assert result is None

    def test_load_corrupt_zip(self, tmp_path):
        path = tmp_path / "bad.dungeon"
        path.write_text("this is not a zip file")
        result = SaveSystem.load(path)
        assert result is None

    def test_load_wrong_version(self, tmp_path):
        path = tmp_path / "v99.dungeon"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("metadata.json", json.dumps({"version": 99, "seed": 1,
                        "timestamp": 0, "tick_count": 0}))
        result = SaveSystem.load(path)
        assert result is None

    def test_load_missing_entry(self, tmp_path):
        """A zip with metadata but missing other entries should return None."""
        path = tmp_path / "partial.dungeon"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("metadata.json", json.dumps({
                "version": SAVE_VERSION, "seed": 1,
                "timestamp": 0, "tick_count": 0,
            }))
            # Missing all other entries → KeyError on read
        result = SaveSystem.load(path)
        assert result is None


# ── Apply tests ──────────────────────────────────────────────────────


class TestApply:
    def test_apply_restores_grid(self, tmp_path):
        """apply() should copy arrays into the live voxel grid."""
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        vg.grid[2, 2, 2] = 10
        vg.temperature[3, 3, 3] = 200.0
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        # Create fresh subsystems (all zeros)
        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        assert vg2.grid[2, 2, 2] == 0

        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert vg2.grid[2, 2, 2] == 10
        assert vg2.temperature[3, 3, 3] == pytest.approx(200.0)
        assert "all" in vg2._dirty_chunks  # mark_all_dirty called

    def test_apply_restores_core(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        core.hp = 100
        core.alive = False
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert core2.hp == 100
        assert core2.alive is False

    def test_apply_restores_inventory(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        ms.held_materials = {5: 3}
        ms.held_temperatures = {5: 50.0}
        ms._last_picked_type = 5
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert ms2.held_materials == {5: 3}
        assert ms2.held_temperatures[5] == pytest.approx(50.0)
        assert ms2._last_picked_type == 5

    def test_apply_restores_dig_jobs(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        bs.dig_queue = [FakeDigJob(1, 2, 3, 40)]
        bs.active_digs = [FakeDigJob(4, 5, 6, 30)]
        bs.active_digs[0].ticks_remaining = 10
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert len(bs2.dig_queue) == 1
        assert bs2.dig_queue[0].x == 1
        assert len(bs2.active_digs) == 1
        assert bs2.active_digs[0].ticks_remaining == 10

    def test_apply_restores_intruders_and_parties(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        i1 = _make_intruder(intruder_id=1, hp=50)
        i2 = _make_intruder(intruder_id=2, archetype_name="Gloomwarden")
        party = _make_party(1, [i1, i2])
        ai.intruders = [i1, i2]
        ai.parties = [party]
        ai._next_id = 3
        ai._next_party_id = 2
        ai.spawning_enabled = True
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert len(ai2.intruders) == 2
        assert ai2.intruders[0].hp == 50
        assert len(ai2.parties) == 1
        assert ai2.parties[0].id == 1
        assert len(ai2.parties[0].members) == 2
        assert ai2._next_id == 3
        assert ai2._next_party_id == 2
        assert ai2.spawning_enabled is True

    def test_apply_restores_tick_count(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        tm.tick_count = 5000
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert tm2.tick_count == 5000

    def test_apply_resets_spawn_timers(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        ai._spawn_timer = 999
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        # Timers are reset, not restored
        assert ai2._spawn_timer == 0

    def test_apply_game_state_fields(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        gs.build_mode = "craft"
        gs.game_over = True
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )

        gs2, vg2, core2, ms2, bs2, tm2, ai2 = _make_subsystems()
        sd = SaveSystem.load(path)
        SaveSystem.apply(
            sd,
            game_state=gs2, voxel_grid=vg2, core=core2,
            move_system=ms2, build_system=bs2, intruder_ai=ai2,
            time_manager=tm2,
        )
        assert gs2.build_mode == "craft"
        assert gs2.game_over is True


# ── Grid dimensions ──────────────────────────────────────────────────


class TestGridDimensions:
    def test_different_grid_sizes(self, tmp_path):
        """Save/load should handle non-default grid sizes."""
        gs = FakeGameState()
        vg = FakeVoxelGrid(w=16, d=16, h=10)
        core = FakeCore()
        ms = FakeMoveSystem()
        bs = FakeBuildSystem()
        tm = FakeTimeManager()
        ai = FakeIntruderAI()
        vg.grid[15, 15, 9] = 3  # Set corner block
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.grid_width == 16
        assert sd.grid_depth == 16
        assert sd.grid_height == 10
        assert sd.grid_arrays["grid"][15, 15, 9] == 3


# ── Water state ───────────────────────────────────────────────────────


class TestWaterState:
    def test_water_level_roundtrip(self, tmp_path):
        gs, vg, core, ms, bs, tm, ai = _make_subsystems()
        vg.water_level[3, 3, 3] = 255
        vg.water_level[4, 4, 4] = 128
        path = tmp_path / "test.dungeon"
        SaveSystem.save(
            path,
            game_state=gs, voxel_grid=vg, core=core,
            move_system=ms, build_system=bs, intruder_ai=ai,
            time_manager=tm,
        )
        sd = SaveSystem.load(path)
        assert sd.grid_arrays["water_level"][3, 3, 3] == 255
        assert sd.grid_arrays["water_level"][4, 4, 4] == 128
