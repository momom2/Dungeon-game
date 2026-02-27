"""Save/load system using zip-based .dungeon files.

Each save file is a zip archive containing:
- metadata.json: version, seed, timestamp, tick_count
- grid_arrays.npz: All VoxelGrid NumPy arrays (np.savez_compressed)
- game_state.json: build_mode, game_over, seed
- move_system.json: held_materials, temperatures, humidities, metal_types
- build_system.json: dig_queue, active_digs, pending_digs
- intruders.json: Full agent state with serialized PersonalMaps,
  equipment (item template names + charges), familiars, supplies
- parties.json: Party composition linked by intruder id
- core.json: DungeonCore HP/position
- intruder_ai.json: Spawn counters and flags
- mana.json: Mana pool state (mana, max_mana, souls)

Dependencies: config, intruders.personal_map, intruders.agent,
    intruders.archetypes, intruders.equipment, intruders.familiar,
    intruders.party, building.build_system, dungeon_core.mana
Dependents: main (wiring), tests/core/test_save_system.py
"""

from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("dungeon_builder.save")

SAVE_VERSION = 1

# Grid arrays to serialize — order must be stable for round-trip
_GRID_ARRAY_NAMES = (
    "grid", "humidity", "temperature", "loose", "load", "shear_load",
    "stress_ratio", "fall_distance", "water_level", "thermal_fatigue",
    "block_state", "metal_type", "claimed", "visible",
    "water_vx", "water_vy", "water_vz",
)


# ── Serialization helpers ─────────────────────────────────────────────


def _pos_to_str(pos: tuple[int, int, int]) -> str:
    """Convert a (x, y, z) tuple to a JSON-safe string key."""
    return f"{pos[0]},{pos[1]},{pos[2]}"


def _str_to_pos(s: str) -> tuple[int, int, int]:
    """Convert an 'x,y,z' string key back to a tuple."""
    parts = s.split(",")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _serialize_personal_map(pmap: Any) -> dict:
    """Serialize a PersonalMap to a JSON-safe dict."""
    return {
        "seen": {_pos_to_str(k): int(v) for k, v in pmap.seen.items()},
        "hazards": [_pos_to_str(p) for p in pmap.hazards],
        "treasures": [_pos_to_str(p) for p in pmap.treasures],
        "doors": {_pos_to_str(k): int(v) for k, v in pmap.doors.items()},
        "baits": [_pos_to_str(p) for p in pmap.baits],
        "alarms": [_pos_to_str(p) for p in pmap.alarms],
    }


def _deserialize_personal_map(data: dict) -> Any:
    """Deserialize a PersonalMap from a JSON dict."""
    from dungeon_builder.intruders.personal_map import PersonalMap

    pmap = PersonalMap()
    pmap.seen = {_str_to_pos(k): int(v) for k, v in data.get("seen", {}).items()}
    pmap.hazards = {_str_to_pos(s) for s in data.get("hazards", [])}
    pmap.treasures = {_str_to_pos(s) for s in data.get("treasures", [])}
    pmap.doors = {_str_to_pos(k): int(v) for k, v in data.get("doors", {}).items()}
    pmap.baits = {_str_to_pos(s) for s in data.get("baits", [])}
    pmap.alarms = {_str_to_pos(s) for s in data.get("alarms", [])}
    return pmap


def _serialize_equipment(equipment: Any) -> dict:
    """Serialize an Equipment instance to a JSON-safe dict."""
    gear: list[dict] = []
    for slot, item in equipment.gear_slots.items():
        gear.append({
            "slot": slot.name,
            "template_name": item.template.name,
            "charges_remaining": item.charges_remaining,
        })
    inventory: list[dict] = []
    for item in equipment.inventory:
        inventory.append({
            "template_name": item.template.name,
            "charges_remaining": item.charges_remaining,
        })
    return {
        "base_slots": equipment._base_slots,
        "gear": gear,
        "inventory": inventory,
    }


def _deserialize_equipment(data: dict) -> Any:
    """Deserialize an Equipment instance from a JSON dict."""
    from dungeon_builder.intruders.equipment import (
        Equipment,
        GearSlot,
        ItemInstance,
        ITEM_TEMPLATE_BY_NAME,
    )

    base_slots = data.get("base_slots", 3)
    equip = Equipment(base_slots)

    for gear_entry in data.get("gear", []):
        template = ITEM_TEMPLATE_BY_NAME.get(gear_entry["template_name"])
        if template is None:
            logger.warning("Unknown item template '%s', skipping", gear_entry["template_name"])
            continue
        item = ItemInstance(template)
        item.charges_remaining = gear_entry.get("charges_remaining", template.charges)
        try:
            slot = GearSlot[gear_entry["slot"]]
        except KeyError:
            logger.warning("Unknown gear slot '%s', skipping", gear_entry["slot"])
            continue
        equip.gear_slots[slot] = item

    for inv_entry in data.get("inventory", []):
        template = ITEM_TEMPLATE_BY_NAME.get(inv_entry["template_name"])
        if template is None:
            logger.warning("Unknown item template '%s', skipping", inv_entry["template_name"])
            continue
        item = ItemInstance(template)
        item.charges_remaining = inv_entry.get("charges_remaining", template.charges)
        equip.inventory.append(item)

    return equip


def _serialize_familiar(familiar: Any) -> dict:
    """Serialize a Familiar to a JSON-safe dict."""
    return {
        "id": familiar.id,
        "owner_id": familiar.owner_id,
        "x": familiar.x,
        "y": familiar.y,
        "z": familiar.z,
        "hp": familiar.hp,
        "max_hp": familiar.max_hp,
        "state": familiar.state.name,
        "unruliness": familiar.unruliness,
        "dig_target": familiar.dig_target,
        "dig_progress": {
            _pos_to_str(k): v for k, v in familiar.dig_progress.items()
        },
    }


def _deserialize_familiar(data: dict) -> Any:
    """Deserialize a Familiar from a JSON dict."""
    from dungeon_builder.intruders.familiar import Familiar, FamiliarState

    f = Familiar(
        familiar_id=data["id"],
        owner_id=data["owner_id"],
        x=data["x"],
        y=data["y"],
        z=data["z"],
    )
    f.hp = data.get("hp", f.hp)
    f.max_hp = data.get("max_hp", f.max_hp)
    f.state = FamiliarState[data.get("state", "FOLLOWING")]
    f.unruliness = data.get("unruliness", 0.0)
    target = data.get("dig_target")
    f.dig_target = tuple(target) if target is not None else None
    raw_dp = data.get("dig_progress", {})
    f.dig_progress = {_str_to_pos(k): v for k, v in raw_dp.items()}
    return f


def _serialize_intruder(intruder: Any) -> dict:
    """Serialize a single Intruder to a JSON-safe dict."""
    data: dict[str, Any] = {
        "id": intruder.id,
        "archetype_name": intruder.archetype.name,
        "x": intruder.x,
        "y": intruder.y,
        "z": intruder.z,
        "hp": intruder.hp,
        "max_hp": intruder.max_hp,
        "shield_hp": intruder.shield_hp,
        "state": intruder.state.name,
        "objective": intruder.objective.name,
        "path": intruder.path,
        "path_index": intruder.path_index,
        "ticks_since_move": intruder.ticks_since_move,
        "move_interval": intruder.move_interval,
        "ticks_since_attack": intruder.ticks_since_attack,
        "attack_interval": intruder.attack_interval,
        "party_id": intruder.party_id,
        "loyalty_modifier": intruder.loyalty_modifier,
        "interaction_type": intruder.interaction_type,
        "interaction_target": intruder.interaction_target,
        "interaction_ticks": intruder.interaction_ticks,
        "loot_count": intruder.loot_count,
        "level": intruder.level,
        "status": intruder.status.name,
        "morale": intruder.morale,
        "food": intruder.food,
        "water": intruder.water,
        "maps_collected": intruder.maps_collected,
        "entertainment": intruder.entertainment,
        "personal_map": _serialize_personal_map(intruder.personal_map),
        "equipment": _serialize_equipment(intruder.equipment),
        "familiars": [_serialize_familiar(f) for f in intruder.familiars],
    }
    # dig_progress: dict of tuple keys -> int values
    data["dig_progress"] = {
        _pos_to_str(k): v for k, v in intruder.dig_progress.items()
    }
    return data


def _deserialize_intruder(data: dict) -> Any:
    """Deserialize a single Intruder from a JSON dict."""
    from dungeon_builder.intruders.agent import Intruder, IntruderState
    from dungeon_builder.intruders.archetypes import (
        ARCHETYPE_BY_NAME,
        IntruderObjective,
        IntruderStatus,
    )

    name = data["archetype_name"]
    archetype = ARCHETYPE_BY_NAME.get(name)
    if archetype is None:
        logger.warning("Unknown archetype '%s', skipping intruder %d", name, data["id"])
        return None

    pmap = _deserialize_personal_map(data["personal_map"])
    objective = IntruderObjective[data["objective"]]
    status = IntruderStatus[data["status"]]

    # Deserialize equipment before constructing the Intruder so we can pass it in
    equipment = None
    if "equipment" in data:
        equipment = _deserialize_equipment(data["equipment"])

    intruder = Intruder(
        intruder_id=data["id"],
        x=data["x"],
        y=data["y"],
        z=data["z"],
        archetype=archetype,
        objective=objective,
        personal_map=pmap,
        equipment=equipment,
        party_id=data.get("party_id"),
        level=data.get("level", 1),
        status=status,
    )

    # Override mutable state that the constructor initialized
    intruder.hp = data["hp"]
    intruder.max_hp = data["max_hp"]
    intruder.shield_hp = data.get("shield_hp", 0)
    intruder.state = IntruderState[data["state"]]
    intruder.path = data.get("path")
    # Paths are lists of lists in JSON; convert back to tuples
    if intruder.path is not None:
        intruder.path = [tuple(p) for p in intruder.path]
    intruder.path_index = data.get("path_index", 0)
    intruder.ticks_since_move = data.get("ticks_since_move", 0)
    intruder.move_interval = data.get("move_interval", archetype.move_interval)
    intruder.ticks_since_attack = data.get("ticks_since_attack", 0)
    intruder.attack_interval = data.get("attack_interval", archetype.attack_interval)
    intruder.loyalty_modifier = data.get("loyalty_modifier", 0.0)
    intruder.interaction_type = data.get("interaction_type")
    target = data.get("interaction_target")
    intruder.interaction_target = tuple(target) if target is not None else None
    intruder.interaction_ticks = data.get("interaction_ticks", 0)
    intruder.loot_count = data.get("loot_count", 0)
    intruder.morale = data.get("morale", 0.5)
    intruder.food = data.get("food", archetype.food_capacity)
    intruder.water = data.get("water", archetype.water_capacity)
    intruder.maps_collected = data.get("maps_collected", 0)
    intruder.entertainment = data.get("entertainment", 1.0)

    # Familiars
    intruder.familiars = [
        _deserialize_familiar(fd) for fd in data.get("familiars", [])
    ]

    # dig_progress
    raw_dp = data.get("dig_progress", {})
    intruder.dig_progress = {_str_to_pos(k): v for k, v in raw_dp.items()}

    # Reset cache fields
    intruder._vision_dirty = True
    intruder._path_cache_key = None

    return intruder


def _serialize_dig_job(job: Any) -> dict:
    """Serialize a DigJob to a JSON-safe dict."""
    return {
        "x": job.x,
        "y": job.y,
        "z": job.z,
        "ticks_remaining": job.ticks_remaining,
        "total_ticks": job.total_ticks,
    }


def _deserialize_dig_job(data: dict) -> Any:
    """Deserialize a DigJob from a JSON dict."""
    from dungeon_builder.building.build_system import DigJob

    job = DigJob(data["x"], data["y"], data["z"], data["total_ticks"])
    job.ticks_remaining = data["ticks_remaining"]
    return job


# ── SaveData container ────────────────────────────────────────────────


@dataclass
class SaveData:
    """Container for all deserialized save data.

    After loading, the caller is responsible for applying these values
    to the live game objects.
    """

    # Metadata
    version: int = SAVE_VERSION
    seed: int = 0
    timestamp: float = 0.0
    tick_count: int = 0

    # Grid arrays as a dict of name → ndarray
    grid_arrays: dict[str, np.ndarray] = field(default_factory=dict)
    grid_width: int = 0
    grid_depth: int = 0
    grid_height: int = 0

    # GameState scalars
    build_mode: str = "dig"
    game_over: bool = False

    # DungeonCore
    core_x: int = 0
    core_y: int = 0
    core_z: int = 0
    core_hp: int = 0
    core_max_hp: int = 0
    core_alive: bool = True

    # MoveSystem inventory
    held_materials: dict[int, int] = field(default_factory=dict)
    held_temperatures: dict[int, float] = field(default_factory=dict)
    held_humidities: dict[int, float] = field(default_factory=dict)
    held_metal_types: dict[int, int] = field(default_factory=dict)
    last_picked_type: int | None = None

    # BuildSystem dig queues
    dig_queue: list[dict] = field(default_factory=list)
    active_digs: list[dict] = field(default_factory=list)
    pending_digs: list[dict] = field(default_factory=list)

    # Intruders (raw dicts -> deserialized later or on access)
    intruders: list[Any] = field(default_factory=list)
    parties: list[dict] = field(default_factory=list)

    # IntruderAI counters
    next_intruder_id: int = 1
    next_party_id: int = 1
    spawning_enabled: bool = False

    # ManaSystem
    mana: float = 0.0
    max_mana: float = 1000.0
    souls: int = 0


# ── Save ──────────────────────────────────────────────────────────────


class SaveSystem:
    """Handles serialization and deserialization of the full game state."""

    @staticmethod
    def save(
        path: Path | str,
        *,
        game_state: Any,
        voxel_grid: Any,
        core: Any,
        move_system: Any,
        build_system: Any,
        intruder_ai: Any,
        time_manager: Any,
    ) -> None:
        """Save the entire game state to a .dungeon zip file.

        Parameters
        ----------
        path : Path
            Destination file path (will be created/overwritten).
        game_state : GameState
        voxel_grid : VoxelGrid
        core : DungeonCore
        move_system : MoveSystem
        build_system : BuildSystem
        intruder_ai : IntruderAI
        time_manager : TimeManager
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. Metadata
            metadata = {
                "version": SAVE_VERSION,
                "seed": game_state.seed,
                "timestamp": time.time(),
                "tick_count": time_manager.tick_count,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

            # 2. Grid arrays
            buf = io.BytesIO()
            arrays = {}
            for name in _GRID_ARRAY_NAMES:
                arr = getattr(voxel_grid, name)
                arrays[name] = arr
            np.savez_compressed(buf, **arrays)
            buf.seek(0)
            zf.writestr("grid_arrays.npz", buf.read())

            # Also save grid dimensions
            grid_info = {
                "width": voxel_grid.width,
                "depth": voxel_grid.depth,
                "height": voxel_grid.height,
            }
            zf.writestr("grid_info.json", json.dumps(grid_info))

            # 3. Game state
            gs_data = {
                "seed": game_state.seed,
                "build_mode": game_state.build_mode,
                "game_over": game_state.game_over,
            }
            zf.writestr("game_state.json", json.dumps(gs_data, indent=2))

            # 4. Core
            core_data = {
                "x": core.x,
                "y": core.y,
                "z": core.z,
                "hp": core.hp,
                "max_hp": core.max_hp,
                "alive": core.alive,
            }
            zf.writestr("core.json", json.dumps(core_data, indent=2))

            # 5. Move system
            # JSON keys must be strings — convert int vtype keys
            move_data = {
                "held_materials": {str(k): v for k, v in move_system.held_materials.items()},
                "held_temperatures": {str(k): v for k, v in move_system.held_temperatures.items()},
                "held_humidities": {str(k): v for k, v in move_system.held_humidities.items()},
                "held_metal_types": {str(k): v for k, v in move_system.held_metal_types.items()},
                "last_picked_type": move_system._last_picked_type,
            }
            zf.writestr("move_system.json", json.dumps(move_data, indent=2))

            # 6. Build system
            build_data = {
                "dig_queue": [_serialize_dig_job(j) for j in build_system.dig_queue],
                "active_digs": [_serialize_dig_job(j) for j in build_system.active_digs],
                "pending_digs": [_serialize_dig_job(j) for j in build_system.pending_digs],
            }
            zf.writestr("build_system.json", json.dumps(build_data, indent=2))

            # 7. Intruders
            intruder_data = [_serialize_intruder(i) for i in intruder_ai.intruders]
            zf.writestr("intruders.json", json.dumps(intruder_data, indent=2))

            # 8. Parties
            def _serialize_party(party):
                return {
                    "id": party.id,
                    "member_ids": [m.id for m in party.members],
                }

            parties_data = {
                "parties": [_serialize_party(p) for p in intruder_ai.parties],
            }
            zf.writestr("parties.json", json.dumps(parties_data, indent=2))

            # 9. IntruderAI counters
            ai_data = {
                "next_id": intruder_ai._next_id,
                "next_party_id": intruder_ai._next_party_id,
                "spawning_enabled": intruder_ai.spawning_enabled,
            }
            zf.writestr("intruder_ai.json", json.dumps(ai_data, indent=2))

            # 10. Mana system
            mana_system = game_state.mana_system
            if mana_system is not None:
                mana_data = {
                    "mana": mana_system.mana,
                    "max_mana": mana_system.max_mana,
                    "souls": mana_system.souls,
                }
                zf.writestr("mana.json", json.dumps(mana_data, indent=2))

        logger.info("Game saved to %s", path)

    @staticmethod
    def load(path: Path | str) -> SaveData | None:
        """Load game state from a .dungeon zip file.

        Returns a :class:`SaveData` container on success, or ``None``
        if the file is missing, corrupt, or has an incompatible version.
        """
        path = Path(path)
        if not path.is_file():
            logger.warning("Save file not found: %s", path)
            return None

        try:
            with zipfile.ZipFile(path, "r") as zf:
                sd = SaveData()

                # 1. Metadata
                metadata = json.loads(zf.read("metadata.json"))
                if metadata.get("version", 0) != SAVE_VERSION:
                    logger.warning(
                        "Incompatible save version %s (expected %s)",
                        metadata.get("version"), SAVE_VERSION,
                    )
                    return None
                sd.version = metadata["version"]
                sd.seed = metadata["seed"]
                sd.timestamp = metadata["timestamp"]
                sd.tick_count = metadata["tick_count"]

                # 2. Grid arrays
                npz_bytes = zf.read("grid_arrays.npz")
                npz_buf = io.BytesIO(npz_bytes)
                with np.load(npz_buf, allow_pickle=False) as npz:
                    for name in _GRID_ARRAY_NAMES:
                        if name in npz:
                            sd.grid_arrays[name] = npz[name]

                # Grid dimensions
                if "grid_info.json" in zf.namelist():
                    gi = json.loads(zf.read("grid_info.json"))
                    sd.grid_width = gi["width"]
                    sd.grid_depth = gi["depth"]
                    sd.grid_height = gi["height"]

                # 3. Game state
                gs = json.loads(zf.read("game_state.json"))
                sd.seed = gs.get("seed", sd.seed)
                sd.build_mode = gs.get("build_mode", "dig")
                sd.game_over = gs.get("game_over", False)

                # 4. Core
                core = json.loads(zf.read("core.json"))
                sd.core_x = core["x"]
                sd.core_y = core["y"]
                sd.core_z = core["z"]
                sd.core_hp = core["hp"]
                sd.core_max_hp = core["max_hp"]
                sd.core_alive = core["alive"]

                # 5. Move system
                ms = json.loads(zf.read("move_system.json"))
                sd.held_materials = {int(k): v for k, v in ms.get("held_materials", {}).items()}
                sd.held_temperatures = {int(k): v for k, v in ms.get("held_temperatures", {}).items()}
                sd.held_humidities = {int(k): v for k, v in ms.get("held_humidities", {}).items()}
                sd.held_metal_types = {int(k): v for k, v in ms.get("held_metal_types", {}).items()}
                sd.last_picked_type = ms.get("last_picked_type")

                # 6. Build system
                bs = json.loads(zf.read("build_system.json"))
                sd.dig_queue = bs.get("dig_queue", [])
                sd.active_digs = bs.get("active_digs", [])
                sd.pending_digs = bs.get("pending_digs", [])

                # 7. Intruders
                raw_intruders = json.loads(zf.read("intruders.json"))
                for raw in raw_intruders:
                    intruder = _deserialize_intruder(raw)
                    if intruder is not None:
                        sd.intruders.append(intruder)

                # 8. Parties
                parties = json.loads(zf.read("parties.json"))
                # Support both old format ("surface" key) and new ("parties" key)
                sd.parties = parties.get("parties", parties.get("surface", []))

                # 9. IntruderAI counters
                ai = json.loads(zf.read("intruder_ai.json"))
                sd.next_intruder_id = ai.get("next_id", 1)
                sd.next_party_id = ai.get("next_party_id", 1)
                sd.spawning_enabled = ai.get("spawning_enabled", False)

                # 10. Mana system (optional — old saves may not have it)
                if "mana.json" in zf.namelist():
                    mana = json.loads(zf.read("mana.json"))
                    sd.mana = mana.get("mana", 0.0)
                    sd.max_mana = mana.get("max_mana", 1000.0)
                    sd.souls = mana.get("souls", 0)

            logger.info("Game loaded from %s (tick %d)", path, sd.tick_count)
            return sd

        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to load save file %s: %s", path, exc)
            return None

    @staticmethod
    def apply(
        save_data: SaveData,
        *,
        game_state: Any,
        voxel_grid: Any,
        core: Any,
        move_system: Any,
        build_system: Any,
        intruder_ai: Any,
        time_manager: Any,
    ) -> None:
        """Apply loaded :class:`SaveData` to live game objects.

        This restores all mutable state and marks the entire grid dirty
        for re-rendering.  The caller should publish a ``game_loaded``
        event after calling this.
        """
        from dungeon_builder.intruders.party import Party

        sd = save_data

        # Game state
        game_state.seed = sd.seed
        game_state.build_mode = sd.build_mode
        game_state.game_over = sd.game_over

        # Time manager
        time_manager.tick_count = sd.tick_count

        # Voxel grid arrays
        for name in _GRID_ARRAY_NAMES:
            if name in sd.grid_arrays:
                target = getattr(voxel_grid, name)
                source = sd.grid_arrays[name]
                # Handle potential shape/dtype mismatch gracefully
                if source.shape == target.shape:
                    target[:] = source
                else:
                    logger.warning(
                        "Grid array '%s' shape mismatch: save=%s grid=%s",
                        name, source.shape, target.shape,
                    )
        voxel_grid.mark_all_dirty()

        # Core
        core.x = sd.core_x
        core.y = sd.core_y
        core.z = sd.core_z
        core.hp = sd.core_hp
        core.max_hp = sd.core_max_hp
        core.alive = sd.core_alive

        # Move system
        move_system.held_materials = dict(sd.held_materials)
        move_system.held_temperatures = dict(sd.held_temperatures)
        move_system.held_humidities = dict(sd.held_humidities)
        move_system.held_metal_types = dict(sd.held_metal_types)
        move_system._last_picked_type = sd.last_picked_type

        # Build system — reconstruct DigJobs
        build_system.dig_queue = [_deserialize_dig_job(d) for d in sd.dig_queue]
        build_system.active_digs = [_deserialize_dig_job(d) for d in sd.active_digs]
        build_system.pending_digs = [_deserialize_dig_job(d) for d in sd.pending_digs]

        # Intruders
        intruder_ai.intruders = list(sd.intruders)
        intruder_ai._next_id = sd.next_intruder_id
        intruder_ai._next_party_id = sd.next_party_id
        intruder_ai.spawning_enabled = sd.spawning_enabled
        intruder_ai._game_over = sd.game_over

        # Build intruder lookup for party reconstruction
        intruder_by_id: dict[int, Any] = {i.id: i for i in sd.intruders}

        # Reconstruct parties
        intruder_ai.parties = []
        for pdata in sd.parties:
            members = [intruder_by_id[mid] for mid in pdata["member_ids"]
                        if mid in intruder_by_id]
            if members:
                party = Party.__new__(Party)
                party.id = pdata["id"]
                party.members = members
                party._leader_id = None
                party._objective = None
                from dungeon_builder.config import MAP_SHARE_INTERVAL
                party._share_tick_counter = MAP_SHARE_INTERVAL - 1
                # Re-elect and re-vote
                party._elect_leader()
                party._vote_objective()
                # Update party_id on members
                for m in members:
                    m.party_id = party.id
                intruder_ai.parties.append(party)

        # Reset transient AI state
        intruder_ai._spawn_timer = 0
        intruder_ai._alarm_cooldowns = {}

        # Mana system — restore pool and recount traps from grid
        mana_system = game_state.mana_system
        if mana_system is not None:
            mana_system.mana = sd.mana
            mana_system.max_mana = sd.max_mana
            mana_system.souls = sd.souls
            mana_system.recount_traps()

        logger.info("Save data applied (tick %d, %d intruders, %d parties)",
                     sd.tick_count, len(sd.intruders),
                     len(intruder_ai.parties))
