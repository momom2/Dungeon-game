# Event Catalog

Complete reference for all pub/sub events routed through the central
`EventBus`. Events are the sole communication mechanism between
subsystems — no system imports or calls another directly.

## Dependency References

This document catalogs events published and subscribed across:

- `core/event_bus.py` (mechanism)
- `core/time_manager.py`
- `core/save_system.py`
- `building/build_system.py`
- `building/crafting_system.py`
- `building/crafting_journal.py`
- `building/move_system.py`
- `building/connections.py`
- `dungeon_core/core.py`
- `dungeon_core/mana.py`
- `intruders/decision.py`
- `intruders/state_handlers.py`
- `intruders/hazard_response.py`
- `intruders/spawning.py`
- `intruders/reputation.py`
- `rendering/camera.py`
- `rendering/voxel_renderer.py`
- `rendering/effects.py`
- `rendering/intruder_renderer.py`
- `rendering/layer_slice.py`
- `ui/hud.py`
- `ui/main_menu.py`
- `ui/menu_settings.py`
- `ui/object_palette.py`
- `ui/enchanted_panel.py`
- `ui/render_mode_selector.py`
- `world/claimed_territory.py`
- `world/room_detection.py`
- `world/physics/gravity.py`
- `world/physics/structural.py`
- `world/physics/temperature.py`
- `world/physics/thermal_stress.py`
- `world/physics/humidity.py`
- `world/physics/water.py`
- `world/physics/pipe.py`
- `main.py`

---

## Event Mechanism

All events flow through `core/event_bus.py` — a minimal pub/sub bus
where subscribers receive keyword arguments:

```python
# Publishing
event_bus.publish("voxel_changed", x=5, y=3, z=10, old_type=1, new_type=0)

# Subscribing
event_bus.subscribe("voxel_changed", self._on_voxel_changed)

def _on_voxel_changed(self, x, y, z, old_type, new_type):
    ...
```

Events are dispatched synchronously in subscription order. There is no
priority system — ordering depends on initialization sequence in
`main.py`.

---

## 1. Tick and Simulation

### `tick`

Core simulation heartbeat. Published every game tick by `TimeManager`.

| Field | Type | Description |
|-------|------|-------------|
| `tick` | int | Monotonically increasing tick counter |

| Publisher | Subscriber |
|-----------|------------|
| `core/time_manager.py` | `building/build_system.py` |
| | `dungeon_core/mana.py` |
| | `intruders/decision.py` |
| | `rendering/voxel_renderer.py` |
| | `world/claimed_territory.py` |
| | `world/physics/gravity.py` |
| | `world/physics/structural.py` |
| | `world/physics/temperature.py` |
| | `world/physics/thermal_stress.py` |
| | `world/physics/humidity.py` |
| | `world/physics/water.py` |
| | `world/physics/pipe.py` |

### `speed_changed`

Game speed changed (pause / 1x / 3x).

| Field | Type | Description |
|-------|------|-------------|
| `speed` | float | New speed multiplier |
| `old_speed` | float | Previous speed multiplier |

| Publisher | Subscriber |
|-----------|------------|
| `core/time_manager.py` | (UI display) |

---

## 2. Voxel and World

### `voxel_changed`

A voxel was placed, removed, or transformed.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `old_type` | int | Previous voxel type ID |
| `new_type` | int | New voxel type ID |

| Publisher | Subscriber |
|-----------|------------|
| `world/voxel_grid.py` | `rendering/voxel_renderer.py` |
| | `dungeon_core/mana.py` |
| | `intruders/decision.py` |
| | `world/claimed_territory.py` |
| | `world/physics/pipe.py` |

### `voxel_hover`

Mouse is hovering over a voxel position.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/crafting_system.py` |
| | `rendering/effects.py` |
| | `ui/hud.py` |

### `voxel_hover_clear`

Mouse left the voxel grid area.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/crafting_system.py` |
| | `rendering/effects.py` |

### `voxel_left_clicked`

Player left-clicked a voxel (build/dig/move mode action).

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `mode` | str | Current build mode |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/build_system.py` |
| | `building/move_system.py` |

### `voxel_right_clicked`

Player right-clicked a voxel (context action — toggle door, cycle pump).

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/move_system.py` |

### `claimed_territory_changed`

Claimed territory boundaries were recomputed.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `world/claimed_territory.py` | `building/build_system.py` |
| | `rendering/voxel_renderer.py` |
| | `rendering/effects.py` |

### `force_territory_recompute`

Force an immediate territory recompute (e.g., after config change).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/voxel_renderer.py` | `world/claimed_territory.py` |
| `ui/main_menu.py` | |

### `room_detected`

A new enclosed room was detected by flood-fill.

| Field | Type | Description |
|-------|------|-------------|
| `room` | object | Room data (bounds, volume, openings) |

| Publisher | Subscriber |
|-----------|------------|
| `world/room_detection.py` | (future systems) |

### `z_level_changed`

Viewing layer changed by player.

| Field | Type | Description |
|-------|------|-------------|
| `z` | int | New viewing Z level |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/crafting_system.py` |
| | `rendering/effects.py` |
| | `ui/object_palette.py` |

---

## 3. Dig Events

### `dig_pending`

A dig job has been accepted and is waiting to start.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |

### `dig_queued`

A dig job is actively queued with a duration countdown.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `duration` | int | Ticks remaining |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |

### `dig_complete`

A single dig job finished — voxel was removed.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `building/build_system.py` (chain) |
| | `rendering/voxel_renderer.py` |
| | `world/claimed_territory.py` |
| | `world/room_detection.py` |

### `dig_cancelled`

A single dig job was cancelled by the player.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |

### `dig_batch_pending`

Multiple dig jobs in pending state (drag-select).

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | List of (x, y, z) positions |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |
| | `world/claimed_territory.py` |

### `dig_batch_queued`

Multiple dig jobs actively queued.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | List of (x, y, z) positions |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/voxel_renderer.py` |
| | `world/claimed_territory.py` |

### `dig_batch_complete`

Multiple dig jobs finished in one batch.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | List of (x, y, z) positions |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/voxel_renderer.py` |
| | `world/claimed_territory.py` |

### `dig_batch_cancelled`

Multiple dig jobs cancelled.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | List of (x, y, z) cancelled positions |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |
| | `world/claimed_territory.py` |

### `drag_dig_area`

Player completed a drag-select for batch digging.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | Selected (x, y, z) positions |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/build_system.py` |

### `drag_select_preview`

Player is actively dragging a selection rectangle.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | Preview (x, y, z) positions |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `rendering/effects.py` |

### `drag_select_cleared`

Player cancelled a drag selection.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `rendering/effects.py` |

---

## 4. Crafting Events

### `craft_recipe_selected`

Player selected a recipe from the crafting book.

| Field | Type | Description |
|-------|------|-------------|
| `recipe_name` | str | Name of the selected recipe |

| Publisher | Subscriber |
|-----------|------------|
| `ui/object_palette.py` | `building/crafting_system.py` |

### `craft_at_position`

Player clicked to place a crafted block.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/crafting_system.py` |

### `craft_mode_entered`

Crafting placement mode activated.

| Field | Type | Description |
|-------|------|-------------|
| `recipe_name` | str | Active recipe name |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |
| | `ui/object_palette.py` |
| | `ui/hud.py` |

### `craft_mode_exited`

Crafting placement mode deactivated.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |
| | `ui/object_palette.py` |

### `craft_success`

A recipe was successfully placed.

| Field | Type | Description |
|-------|------|-------------|
| `recipe` | object | Recipe that was crafted |
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `building/crafting_journal.py` |
| | `ui/object_palette.py` |

### `craft_cancel`

Player cancelled craft mode (Escape key or tool switch).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `building/crafting_system.py` |

### `craft_highlights_updated`

Valid craft placement positions recalculated.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | Valid (x, y, z) placement positions |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |

### `craft_highlights_cleared`

Craft highlight overlay removed.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |
| | `rendering/voxel_renderer.py` |

### `craft_hover_valid`

Mouse is hovering over a valid craft placement position.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `recipe_name` | str | Active recipe name |
| `output_vtype` | int | Output voxel type |
| `effect_radius` | int | Effect radius (0 = point) |
| `behavior_hint` | str | Human-readable hint |
| `mana_cost` | int | Total mana cost |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |
| | `ui/hud.py` |

### `craft_hover_invalid`

Mouse is hovering over an invalid craft placement position.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |
| | `ui/hud.py` |

### `craft_hover_clear`

Mouse left the craft hover area.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |

### `craft_placement_flash`

Visual flash feedback after successful craft.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | `rendering/effects.py` |

### `craft_remaining_updated`

Material remaining count changed for active recipe.

| Field | Type | Description |
|-------|------|-------------|
| `recipe_name` | str | Recipe name |
| `remaining` | int | Remaining material count |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_system.py` | (UI display) |

### `recipe_discovered`

Player discovered a new recipe (first craft or exploration).

| Field | Type | Description |
|-------|------|-------------|
| `recipe_name` | str | Discovered recipe name |

| Publisher | Subscriber |
|-----------|------------|
| `building/crafting_journal.py` | `ui/object_palette.py` |
| | `ui/hud.py` |

### `ingredient_highlight`

Highlight ingredient blocks for a recipe in the crafting book.

| Field | Type | Description |
|-------|------|-------------|
| `positions` | list[tuple] | (x, y, z) positions of ingredient blocks |

| Publisher | Subscriber |
|-----------|------------|
| `ui/object_palette.py` | `rendering/voxel_renderer.py` |

### `toggle_crafting_book`

Toggle crafting book panel visibility.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/hud.py` | `ui/object_palette.py` |

---

## 5. Material and Inventory

### `material_picked_up`

Player picked up a loose block into inventory.

| Field | Type | Description |
|-------|------|-------------|
| `vtype` | int | Voxel type picked up |
| `materials` | dict | Current inventory {vtype: count} |

| Publisher | Subscriber |
|-----------|------------|
| `building/move_system.py` | `rendering/voxel_renderer.py` |
| | `ui/object_palette.py` |
| | `ui/hud.py` |

### `material_dropped`

Player dropped a block from inventory.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `vtype` | int | Voxel type dropped |
| `materials` | dict | Current inventory {vtype: count} |

| Publisher | Subscriber |
|-----------|------------|
| `building/move_system.py` | `ui/object_palette.py` |

### `door_toggled`

Door block state changed (open/closed).

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `state` | int | 0 = closed, 1 = open |

| Publisher | Subscriber |
|-----------|------------|
| `building/move_system.py` | (rendering) |

### `pump_direction_changed`

Pump block direction cycled to next facing.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `direction` | int | Direction index (0-5, one per face) |

| Publisher | Subscriber |
|-----------|------------|
| `building/move_system.py` | (pipe system) |

---

## 6. Intruder Events

### `intruder_spawned`

A new intruder manifested or entered from the surface.

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The spawned intruder object |

| Publisher | Subscriber |
|-----------|------------|
| `intruders/spawning.py` | `rendering/intruder_renderer.py` |

### `intruder_moved`

An intruder moved to a new grid position.

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The intruder that moved |

| Publisher | Subscriber |
|-----------|------------|
| `intruders/state_handlers.py` | `rendering/intruder_renderer.py` |
| `intruders/hazard_response.py` | |

### `intruder_died`

An intruder was killed (by hazard, trap, or combat).

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The dead intruder |

| Publisher | Subscriber |
|-----------|------------|
| `intruders/decision.py` | `dungeon_core/mana.py` (soul capture) |
| | `intruders/reputation.py` |
| | `rendering/intruder_renderer.py` |

### `intruder_escaped`

An intruder reached the surface exit and escaped.

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The escaped intruder |

| Publisher | Subscriber |
|-----------|------------|
| `intruders/state_handlers.py` | `intruders/reputation.py` |
| | `rendering/intruder_renderer.py` |

### `intruder_betrayed`

An intruder betrayed their party (low morale + opportunity).

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The betraying intruder |

| Publisher | Subscriber |
|-----------|------------|
| `intruders/hazard_response.py` | (party system) |

### `intruder_collected_treasure`

An intruder looted treasure from the dungeon.

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The intruder who collected |
| `value` | int | Treasure value |

| Publisher | Subscriber |
|-----------|------------|
| `intruders/state_handlers.py` | `intruders/reputation.py` |

### `intruder_needs_repath`

Request for an intruder to recalculate their path. Reserved for future
use — subscribed in `decision.py` but not currently published.

| Field | Type | Description |
|-------|------|-------------|
| `intruder` | Intruder | The intruder to repath |

| Publisher | Subscriber |
|-----------|------------|
| (reserved) | `intruders/decision.py` |

---

## 7. Physics Events

### `blocks_fell`

Gravity simulation completed and blocks fell.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/gravity.py` | `world/physics/structural.py` |

### `blocks_spread`

Loose blocks propagated (angle of repose).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/gravity.py` | `world/physics/structural.py` |

### `impact`

Blocks impacted the ground after falling.

| Field | Type | Description |
|-------|------|-------------|
| `count` | int | Number of blocks that impacted |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/gravity.py` | (effects, damage) |

### `structural_disconnect`

Blocks lost structural connectivity (floating).

| Field | Type | Description |
|-------|------|-------------|
| `count` | int | Number of disconnected blocks |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/gravity.py` | (effects) |

### `structural_failure`

Blocks collapsed under compressive/shear load.

| Field | Type | Description |
|-------|------|-------------|
| `count` | int | Number of failed blocks |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/structural.py` | (effects, gravity cascade) |

### `tensile_failure`

Blocks failed under tensile stress (unsupported cantilever).

| Field | Type | Description |
|-------|------|-------------|
| `count` | int | Number of failed blocks |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/structural.py` | (effects) |

### `water_flowed`

Water simulation step completed.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/water.py` | `rendering/voxel_renderer.py` |

### `water_burst`

Water overpressure caused a burst event.

| Field | Type | Description |
|-------|------|-------------|
| `count` | int | Number of burst cells |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/water.py` | (effects) |

### `water_lava_reaction`

Water and lava interacted (produces obsidian).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/water.py` | (effects) |

### `metal_melted`

A metal voxel reached its melting point and was destroyed.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/temperature.py` | (effects) |

### `thermal_crack`

Thermal stress caused blocks to crack and break.

| Field | Type | Description |
|-------|------|-------------|
| `count` | int | Number of cracked blocks |

| Publisher | Subscriber |
|-----------|------------|
| `world/physics/thermal_stress.py` | (effects) |

---

## 8. Dungeon Core and Mana

### `core_damaged`

The dungeon core took damage from an intruder.

| Field | Type | Description |
|-------|------|-------------|
| `hp` | int | Current HP |
| `max_hp` | int | Maximum HP |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/core.py` | (UI, effects) |

### `game_over`

The dungeon core was destroyed — game lost.

| Field | Type | Description |
|-------|------|-------------|
| `reason` | str | Always `"core_destroyed"` |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/core.py` | `intruders/decision.py` |

### `mana_changed`

Mana pool value changed (generation, consumption, or soul capture).

| Field | Type | Description |
|-------|------|-------------|
| `mana` | float | Current mana |
| `max_mana` | float | Maximum mana capacity |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/mana.py` | (UI display) |

### `mana_power_changed`

Mana power state toggled (enough mana to power digs/traps, or not).

| Field | Type | Description |
|-------|------|-------------|
| `digs_powered` | bool | Whether digs are mana-powered |
| `traps_powered` | bool | Whether traps are mana-powered |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/mana.py` | `building/build_system.py` |
| | `intruders/decision.py` |

### `soul_captured`

An intruder soul was captured on claimed territory.

| Field | Type | Description |
|-------|------|-------------|
| `souls` | int | Total souls captured |
| `max_mana` | float | New maximum mana capacity |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/mana.py` | (UI display) |

### `enchanted_block_state_changed`

An enchanted block's activation or charge mode changed.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `activated` | bool | Whether the block is active |
| `charge_mode` | str | `"charging"`, `"idle"`, or `"draining"` |
| `capacitance` | float | Current charge |
| `max_capacitance` | float | Maximum charge |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/mana.py` | (UI, rendering) |

### `enchanted_block_removed`

An enchanted block was destroyed or dug out.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/mana.py` | (UI, rendering) |

### `block_capacitance_depleted`

An enchanted block's capacitance reached zero.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `dungeon_core/mana.py` | (effects) |

### `enchanted_block_toggle_activation`

UI request to toggle an enchanted block's active state.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `ui/enchanted_panel.py` | `dungeon_core/mana.py` |

### `enchanted_block_set_charge_mode`

UI request to change an enchanted block's charge mode.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `mode` | str | `"charging"`, `"idle"`, or `"draining"` |

| Publisher | Subscriber |
|-----------|------------|
| `ui/enchanted_panel.py` | `dungeon_core/mana.py` |

### `enchanted_block_selected`

Player clicked an enchanted block to open the management panel.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `ui/enchanted_panel.py` |

### `enchanted_block_deselected`

Enchanted block panel closed.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | (UI panel) |
| `ui/enchanted_panel.py` | |

### `block_selected`

Player clicked any non-air block (generalizes enchanted_block_selected).
Used for connection visualization.

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Grid x coordinate |
| `y` | int | Grid y coordinate |
| `z` | int | Grid z coordinate |
| `vtype` | int | Voxel type at position |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `rendering/effects.py` |

### `block_deselected`

Block deselected (clicking another block or entering craft mode).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | `rendering/effects.py` |

---

## 9. Camera and Rendering

### `tool_changed`

Player switched build mode (build/dig/move/craft).

| Field | Type | Description |
|-------|------|-------------|
| `mode` | str | New build mode name |

| Publisher | Subscriber |
|-----------|------------|
| `rendering/camera.py` | (UI, build system) |

### `render_mode_changed`

Visualization mode changed (terrain/wireframe/thermal/water overlay).

| Field | Type | Description |
|-------|------|-------------|
| `mode` | str | New render mode name |

| Publisher | Subscriber |
|-----------|------------|
| `ui/render_mode_selector.py` | `rendering/effects.py` |

### `config_changed`

A config value was changed through the settings UI.

| Field | Type | Description |
|-------|------|-------------|
| `key` | str | Config key name |
| `value` | any | New value (optional, some keys are toggles) |

| Publisher | Subscriber |
|-----------|------------|
| `ui/main_menu.py` | `rendering/layer_slice.py` |
| `ui/menu_settings.py` | `world/physics/water.py` |

Common keys: `LAYER_DEPTH_FADE`, `WATER_FLOW_MODEL`, `FOG_COLOR`,
`all_difficulty`, `all_visibility`, plus physics/rendering slider keys.

---

## 10. Save/Load Events

### `save_game_requested`

Player requested a save through the menu.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/main_menu.py` | `main.py` |

### `load_game_requested`

Player requested to load a save file.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/main_menu.py` | `main.py` |

### `game_loaded`

Save file was successfully loaded and world state restored.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `main.py` | (all systems) |

---

## 11. UI and Feedback

### `error_message`

Display an error/warning message to the player.

| Field | Type | Description |
|-------|------|-------------|
| `text` | str | Human-readable error message |

| Publisher | Subscriber |
|-----------|------------|
| `building/build_system.py` | `ui/hud.py` |
| `building/crafting_system.py` | |
| `building/move_system.py` | |
| `rendering/camera.py` | |
| `ui/object_palette.py` | |
| `ui/main_menu.py` | |

### `dev_mode_changed`

Developer mode toggled on/off.

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/main_menu.py` | `intruders/decision.py` |

---

## 12. Debug Events

### `debug_spawn_party`

Spawn a full intruder party (dev mode only).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/hud.py` | `intruders/decision.py` |

### `debug_spawn_single`

Spawn a single intruder (dev mode only).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/hud.py` | `intruders/decision.py` |

### `debug_kill_all`

Kill all active intruders (dev mode only).

| Field | Type | Description |
|-------|------|-------------|
| (none) | | |

| Publisher | Subscriber |
|-----------|------------|
| `ui/hud.py` | `intruders/decision.py` |

---

## Summary

| Domain | Events | Key Flow |
|--------|--------|----------|
| Tick/Simulation | 2 | TimeManager ticks all systems |
| Voxel/World | 7 | Camera → click/hover → build/craft |
| Dig | 11 | BuildSystem queues → processes → completes |
| Crafting | 15 | Panel → CraftingSystem → effects/renderer |
| Material | 4 | MoveSystem pickup/drop → UI/renderer |
| Intruder | 7 | Spawning → movement → death/escape |
| Physics | 11 | Physics engines → effects/gravity cascade |
| Core/Mana | 13 | Mana economy + enchanted block management + connections |
| Camera/Rendering | 3 | Mode switches → renderer/effects |
| Save/Load | 3 | Menu → main.py save/load handlers |
| UI/Feedback | 2 | Error messages, dev mode toggle |
| Debug | 3 | Dev-mode intruder spawn/kill |

**Total: 81 distinct event types across 35 source files.**
