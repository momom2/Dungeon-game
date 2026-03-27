"""Free-camera controls: orbit, pan, zoom, Z-level scrolling, and mouse picking.

Dependencies: config, core.event_bus, core.game_state,
    core.keybinding_registry, rendering.layer_slice
Dependents: main (wiring), tests/rendering/test_camera.py,
    tests/building/test_drag_select.py
"""

from __future__ import annotations

import math
import logging
from typing import TYPE_CHECKING

from panda3d.core import (
    LPoint3f,
    LVector3f,
)
from direct.showbase.ShowBase import ShowBase

import dungeon_builder.config as _cfg
from dungeon_builder.config import (
    GRID_HEIGHT,
    VOXEL_AIR,
    CORE_X,
    CORE_Y,
    CORE_Z,
    CAMERA_DEFAULT_DISTANCE,
    CAMERA_DEFAULT_HEADING,
    CAMERA_DEFAULT_PITCH,
    DRAG_SELECT_THRESHOLD,
    DRAG_VERTICAL_SENSITIVITY,
)

if TYPE_CHECKING:
    from dungeon_builder.core.event_bus import EventBus
    from dungeon_builder.core.game_state import GameState
    from dungeon_builder.core.keybinding_registry import KeybindingRegistry
    from dungeon_builder.rendering.layer_slice import LayerSliceManager

logger = logging.getLogger("dungeon_builder.camera")

# Mouse movement threshold (in NDC) to distinguish click from drag
_RIGHT_CLICK_THRESHOLD = 0.02


class CameraController:
    """RTS-style orbiting camera with Z-level scrolling and voxel picking."""

    def __init__(
        self,
        app: ShowBase,
        event_bus: EventBus,
        game_state: GameState,
        layer_manager: LayerSliceManager,
        keybinding_registry: KeybindingRegistry | None = None,
    ) -> None:
        self.app = app
        self.event_bus = event_bus
        self.game_state = game_state
        self.layer_manager = layer_manager
        self._kb = keybinding_registry

        # Camera state
        self.focus = LPoint3f(CORE_X + 0.5, CORE_Y + 0.5, -CORE_Z)
        self.distance = CAMERA_DEFAULT_DISTANCE
        self.heading = CAMERA_DEFAULT_HEADING
        self.pitch = CAMERA_DEFAULT_PITCH

        # Track held keys
        self._keys: dict[str, bool] = {}
        self._mouse_right_down = False
        self._mouse_mid_down = False
        self._last_mouse_x = 0.0
        self._last_mouse_y = 0.0

        # Right-click tracking (distinguish click from drag)
        self._right_click_start_x = 0.0
        self._right_click_start_y = 0.0

        # Left-click drag-select tracking
        self._mouse_left_down = False
        self._left_click_start_x = 0.0
        self._left_click_start_y = 0.0
        self._drag_selecting = False
        self._drag_start_grid: tuple[int, int] | None = None
        self._drag_current_grid: tuple[int, int] | None = None
        self._drag_shift_held = False
        self._drag_z_start = 0
        self._drag_z_current = 0
        self._drag_shift_anchor_y = 0.0  # mouse Y when shift pressed
        self._drag_notified_shift = False

        # Hover tracking — last hovered voxel for highlight
        self._hovered_voxel: tuple[int, int, int] | None = None

        self._bind_controls()
        self._update_camera()

    def _kb_get(self, action: str, fallback: str) -> str:
        """Get key for action from registry, or use fallback if no registry."""
        if self._kb is not None:
            return self._kb.get(action)
        return fallback

    def _bind_controls(self) -> None:
        app = self.app

        # Continuous-hold keys: bind by action name so _input_task can
        # check self._keys["camera_pan_forward"] etc.
        _hold_actions = [
            ("camera_pan_forward", "w"),
            ("camera_pan_backward", "s"),
            ("camera_pan_left", "a"),
            ("camera_pan_right", "d"),
            ("camera_rotate_left", "q"),
            ("camera_rotate_right", "e"),
            ("camera_pan_forward_alt", "arrow_up"),
            ("camera_pan_backward_alt", "arrow_down"),
            ("camera_pan_left_alt", "arrow_left"),
            ("camera_pan_right_alt", "arrow_right"),
        ]
        for action, fallback in _hold_actions:
            key = self._kb_get(action, fallback)
            self._keys[action] = False
            app.accept(key, self._set_key, [action, True])
            app.accept(f"{key}-up", self._set_key, [action, False])

        # Z-level scrolling (one-shot)
        app.accept(self._kb_get("z_level_up", "t"), self._z_up)
        app.accept(self._kb_get("z_level_down", "y"), self._z_down)

        # Zoom (mouse — not rebindable)
        app.accept("wheel_up", self._zoom_in)
        app.accept("wheel_down", self._zoom_out)

        # Mouse buttons (not rebindable)
        app.accept("mouse3", self._on_right_down)
        app.accept("mouse3-up", self._on_right_up)
        app.accept("mouse2", self._on_mid_down)
        app.accept("mouse2-up", self._on_mid_up)
        app.accept("mouse1", self._on_left_down)
        app.accept("mouse1-up", self._on_left_up)

        # Shift tracking for vertical drag-select
        app.accept("shift", self._on_shift_down)
        app.accept("shift-up", self._on_shift_up)

        # Tool switching (one-shot)
        app.accept(self._kb_get("toggle_tool", "x"), self._toggle_tool)

        # Register continuous input task
        app.taskMgr.add(self._input_task, "camera_input", sort=5)

    def _set_key(self, key: str, value: bool) -> None:
        self._keys[key] = value

    def _input_task(self, task):
        # Suppress all camera input while menu is open
        if self.game_state.menu_open:
            # Still track mouse position to avoid jumps on menu close
            if self.app.mouseWatcherNode.has_mouse():
                self._last_mouse_x = self.app.mouseWatcherNode.get_mouse_x()
                self._last_mouse_y = self.app.mouseWatcherNode.get_mouse_y()
            return task.cont

        dt = globalClock.get_dt()

        # WASD + Arrow key panning (relative to camera heading)
        move = LVector3f(0, 0, 0)
        if self._keys.get("camera_pan_forward") or self._keys.get("camera_pan_forward_alt"):
            move.y += 1
        if self._keys.get("camera_pan_backward") or self._keys.get("camera_pan_backward_alt"):
            move.y -= 1
        if self._keys.get("camera_pan_left") or self._keys.get("camera_pan_left_alt"):
            move.x -= 1
        if self._keys.get("camera_pan_right") or self._keys.get("camera_pan_right_alt"):
            move.x += 1

        if move.length_squared() > 0:
            move.normalize()
            speed = _cfg.CAMERA_PAN_SPEED * dt
            # Rotate movement by heading
            rad = math.radians(self.heading)
            cos_h = math.cos(rad)
            sin_h = math.sin(rad)
            dx = move.x * cos_h - move.y * sin_h
            dy = move.x * sin_h + move.y * cos_h
            self.focus.x += dx * speed
            self.focus.y += dy * speed

        # Q/E rotation
        if self._keys.get("camera_rotate_left"):
            self.heading -= _cfg.CAMERA_ROTATE_SPEED * dt
        if self._keys.get("camera_rotate_right"):
            self.heading += _cfg.CAMERA_ROTATE_SPEED * dt

        # Mouse drag rotation / panning
        if self.app.mouseWatcherNode.has_mouse():
            mx = self.app.mouseWatcherNode.get_mouse_x()
            my = self.app.mouseWatcherNode.get_mouse_y()

            if self._mouse_right_down:
                dx = mx - self._last_mouse_x
                dy = my - self._last_mouse_y
                self.heading -= dx * 100
                self.pitch = max(-89, min(-10, self.pitch + dy * 100))

            if self._mouse_mid_down:
                dx = mx - self._last_mouse_x
                dy = my - self._last_mouse_y
                speed = self.distance * 0.5
                rad = math.radians(self.heading)
                cos_h = math.cos(rad)
                sin_h = math.sin(rad)
                self.focus.x -= (dx * cos_h + dy * sin_h) * speed
                self.focus.y -= (dx * sin_h - dy * cos_h) * speed

            self._last_mouse_x = mx
            self._last_mouse_y = my

            # ── Drag-select state machine ──
            if self._mouse_left_down and not self._drag_selecting:
                dist = math.hypot(
                    mx - self._left_click_start_x,
                    my - self._left_click_start_y,
                )
                if dist > DRAG_SELECT_THRESHOLD:
                    self._drag_selecting = True
                    # z was already captured in _on_left_down

            if self._drag_selecting:
                # When Shift is held, only move vertically (freeze XY)
                if not self._drag_shift_held:
                    hit = self._ray_hit_layer(
                        *self._get_mouse_ray()
                    ) if self._get_mouse_ray() is not None else None
                    if hit is not None:
                        self._drag_current_grid = hit

                # Vertical z extension when Shift is held
                if self._drag_shift_held:
                    z_offset = int(
                        (my - self._drag_shift_anchor_y)
                        / DRAG_VERTICAL_SENSITIVITY
                    )
                    # Moving mouse up selects higher (lower z), down selects deeper
                    self._drag_z_current = max(
                        0, min(GRID_HEIGHT - 1, self._drag_z_start - z_offset)
                    )
                else:
                    self._drag_z_current = self._drag_z_start

                # Publish preview
                if (
                    self._drag_start_grid is not None
                    and self._drag_current_grid is not None
                ):
                    sx, sy = self._drag_start_grid
                    cx, cy = self._drag_current_grid
                    z_lo = min(self._drag_z_start, self._drag_z_current)
                    z_hi = max(self._drag_z_start, self._drag_z_current)
                    self.event_bus.publish(
                        "drag_select_preview",
                        x_min=min(sx, cx), x_max=max(sx, cx),
                        y_min=min(sy, cy), y_max=max(sy, cy),
                        z_min=z_lo, z_max=z_hi,
                    )

                # Shift notification (once per drag)
                if not self._drag_shift_held and not self._drag_notified_shift:
                    self._drag_notified_shift = True
                    self.event_bus.publish(
                        "error_message",
                        text="Hold Shift to select vertically",
                        color=(0.7, 0.7, 0.9, 1),
                    )

        self._update_camera()
        self._update_hover()
        return task.cont

    def _update_hover(self) -> None:
        """Update the hovered voxel highlight each frame."""
        hit = self._pick_voxel()
        if hit != self._hovered_voxel:
            self._hovered_voxel = hit
            if hit is not None:
                self.event_bus.publish(
                    "voxel_hover", x=hit[0], y=hit[1], z=hit[2]
                )
            else:
                self.event_bus.publish("voxel_hover_clear")

    def _update_camera(self) -> None:
        # Spherical to Cartesian
        pitch_rad = math.radians(self.pitch)
        heading_rad = math.radians(self.heading)

        cam_x = self.focus.x + self.distance * math.cos(pitch_rad) * math.sin(heading_rad)
        cam_y = self.focus.y - self.distance * math.cos(pitch_rad) * math.cos(heading_rad)
        cam_z = self.focus.z - self.distance * math.sin(pitch_rad)

        self.app.camera.set_pos(cam_x, cam_y, cam_z)
        self.app.camera.look_at(self.focus)

    def _z_up(self) -> None:
        if self.game_state.menu_open:
            return
        new_z = max(0, self.layer_manager.current_z - 1)
        self.layer_manager.set_focus_z(new_z)
        self.focus.z = -new_z
        self.event_bus.publish("z_level_changed", z=new_z)

    def _z_down(self) -> None:
        if self.game_state.menu_open:
            return
        new_z = min(GRID_HEIGHT - 1, self.layer_manager.current_z + 1)
        self.layer_manager.set_focus_z(new_z)
        self.focus.z = -new_z
        self.event_bus.publish("z_level_changed", z=new_z)

    def _zoom_in(self) -> None:
        if self.game_state.menu_open:
            return
        self.distance = max(_cfg.CAMERA_MIN_DISTANCE, self.distance - _cfg.CAMERA_ZOOM_STEP)

    def _zoom_out(self) -> None:
        if self.game_state.menu_open:
            return
        self.distance = min(_cfg.CAMERA_MAX_DISTANCE, self.distance + _cfg.CAMERA_ZOOM_STEP)

    def _on_right_down(self) -> None:
        self._mouse_right_down = True
        if self.app.mouseWatcherNode.has_mouse():
            self._right_click_start_x = self.app.mouseWatcherNode.get_mouse_x()
            self._right_click_start_y = self.app.mouseWatcherNode.get_mouse_y()

    def _on_right_up(self) -> None:
        self._mouse_right_down = False
        if self.game_state.menu_open:
            return

        # Check if this was a click (not a drag)
        if self.app.mouseWatcherNode.has_mouse():
            mx = self.app.mouseWatcherNode.get_mouse_x()
            my = self.app.mouseWatcherNode.get_mouse_y()
            dx = abs(mx - self._right_click_start_x)
            dy = abs(my - self._right_click_start_y)
            if dx < _RIGHT_CLICK_THRESHOLD and dy < _RIGHT_CLICK_THRESHOLD:
                self._on_right_click()

    def _on_mid_down(self) -> None:
        self._mouse_mid_down = True

    def _on_mid_up(self) -> None:
        self._mouse_mid_down = False

    def _toggle_tool(self) -> None:
        """Toggle between dig and move tools."""
        if self.game_state.menu_open:
            return
        if self.game_state.build_mode == "dig":
            self.game_state.build_mode = "move"
        else:
            self.game_state.build_mode = "dig"
        self.event_bus.publish("tool_changed", mode=self.game_state.build_mode)

    def _on_left_down(self) -> None:
        """Handle left mouse button press: begin potential drag-select."""
        if self.game_state.menu_open:
            return
        if self.game_state.craft_mode_active:
            # In craft mode, clicks are immediate (no drag-select)
            self._on_left_click()
            return

        self._mouse_left_down = True
        self._drag_selecting = False
        self._drag_notified_shift = False
        if self.app.mouseWatcherNode.has_mouse():
            self._left_click_start_x = self.app.mouseWatcherNode.get_mouse_x()
            self._left_click_start_y = self.app.mouseWatcherNode.get_mouse_y()

        # Record grid position AND z-level at press time (not at threshold)
        # so that drag-select z matches single-click z exactly.
        self._drag_z_start = self.layer_manager.current_z
        self._drag_z_current = self._drag_z_start
        ray = self._get_mouse_ray()
        if ray is not None:
            hit = self._ray_hit_layer(*ray)
            self._drag_start_grid = hit
            self._drag_current_grid = hit

    def _on_left_up(self) -> None:
        """Handle left mouse button release: finish drag or single-click."""
        if not self._mouse_left_down:
            return
        self._mouse_left_down = False

        if self._drag_selecting:
            # Finish drag-select: publish area and clear
            if (
                self._drag_start_grid is not None
                and self._drag_current_grid is not None
            ):
                sx, sy = self._drag_start_grid
                cx, cy = self._drag_current_grid
                z_lo = min(self._drag_z_start, self._drag_z_current)
                z_hi = max(self._drag_z_start, self._drag_z_current)
                self.event_bus.publish(
                    "drag_dig_area",
                    x_min=min(sx, cx), x_max=max(sx, cx),
                    y_min=min(sy, cy), y_max=max(sy, cy),
                    z_min=z_lo, z_max=z_hi,
                )
            self.event_bus.publish("drag_select_cleared")
            self._drag_selecting = False
            self._drag_start_grid = None
            self._drag_current_grid = None
            return

        # Was a single click — dispatch normally
        self._on_left_click()

    def _on_shift_down(self) -> None:
        """Handle Shift press for vertical drag extension."""
        self._drag_shift_held = True
        if self._drag_selecting and self.app.mouseWatcherNode.has_mouse():
            self._drag_shift_anchor_y = self.app.mouseWatcherNode.get_mouse_y()

    def _on_shift_up(self) -> None:
        """Handle Shift release."""
        self._drag_shift_held = False
        if self._drag_selecting:
            # Reset to single z-level when shift released
            self._drag_z_current = self._drag_z_start

    def _on_left_click(self) -> None:
        """Handle left-click: pick a voxel and dispatch action."""
        if self.game_state.menu_open:
            return

        # Craft mode: click to place at position
        if self.game_state.craft_mode_active:
            hit = self._pick_voxel()
            if hit is None:
                hit = self._pick_air_voxel()
            if hit is not None:
                self.event_bus.publish(
                    "craft_at_position", x=hit[0], y=hit[1], z=hit[2]
                )
            else:
                self.event_bus.publish("craft_cancel")
            return

        hit = self._pick_voxel()
        if hit is None:
            # Allow clicking on air for pending digs on invisible blocks
            hit = self._pick_air_voxel()
            if hit is not None:
                vx, vy, vz = hit
                grid = self.game_state.voxel_grid
                if grid is not None and not grid.is_visible(vx, vy, vz):
                    # Target the solid block below the air (z+1 is deeper)
                    target_z = vz + 1
                    if grid.in_bounds(vx, vy, target_z):
                        self.event_bus.publish(
                            "voxel_left_clicked", x=vx, y=vy, z=target_z,
                            mode="dig",
                        )
            return

        vx, vy, vz = hit
        grid = self.game_state.voxel_grid
        if grid is None:
            return

        # Deselect any currently selected enchanted block
        if self.game_state.selected_block is not None:
            self.game_state.selected_block = None
            self.event_bus.publish("enchanted_block_deselected")
            self.event_bus.publish("block_deselected")

        # Publish general block selection for connection visualization
        vtype = grid.get(vx, vy, vz)
        self.event_bus.publish(
            "block_selected", x=vx, y=vy, z=vz, vtype=vtype,
        )

        # Select enchanted blocks instead of digging them
        if (
            vtype in _cfg.MAGICAL_TRAP_TYPES
            and not grid.is_loose(vx, vy, vz)
        ):
            self.game_state.selected_block = (vx, vy, vz)
            self.event_bus.publish(
                "enchanted_block_selected", x=vx, y=vy, z=vz,
            )
            return

        # Auto-switch: determine mode from block state
        # Loose blocks → move; solid blocks → dig
        if grid.is_loose(vx, vy, vz):
            mode = "move"
        else:
            mode = "dig"

        self.event_bus.publish(
            "voxel_left_clicked", x=vx, y=vy, z=vz, mode=mode
        )

    def _on_right_click(self) -> None:
        """Handle right-click: pick a voxel and dispatch right-click action."""
        # In craft mode, right-click cancels
        if self.game_state.craft_mode_active:
            self.event_bus.publish("craft_cancel")
            return

        hit = self._pick_voxel()
        if hit is None:
            # Right-click on air: try to find the air voxel for dropping
            hit = self._pick_air_voxel()
            if hit is None:
                return

        vx, vy, vz = hit
        self.event_bus.publish(
            "voxel_right_clicked",
            x=vx, y=vy, z=vz,
            mode=self.game_state.build_mode,
        )

    def _get_mouse_ray(self) -> tuple[LPoint3f, LVector3f] | None:
        """Get the mouse ray origin and direction in world space.

        Returns (origin, direction) or None if mouse is not available.
        """
        if not self.app.mouseWatcherNode.has_mouse():
            return None

        mpos = self.app.mouseWatcherNode.get_mouse()

        near_point = LPoint3f()
        far_point = LPoint3f()
        lens = self.app.camNode.get_lens()
        if not lens.extrude(mpos, near_point, far_point):
            return None

        # Transform to world space
        cam_mat = self.app.camera.get_mat(self.app.render)
        origin = cam_mat.xform_point(near_point)
        far_world = cam_mat.xform_point(far_point)

        # Direction is from near to far
        direction = LVector3f(far_world - origin)
        direction.normalize()
        return origin, direction

    def _ray_hit_layer(
        self, origin: LPoint3f, direction: LVector3f
    ) -> tuple[int, int] | None:
        """Intersect a ray with the horizontal plane of the current layer.

        The current layer at grid z = current_z is rendered at world z in
        the range [-current_z, -current_z + 1].  We intersect the ray with
        the middle of that slab (world_z = -current_z + 0.5) and return
        the (grid_x, grid_y) of the hit cell, or None if the ray is
        parallel to the plane or the hit is outside the grid.
        """
        z_level = self.layer_manager.current_z
        # Voxels at grid z render with their top face at world z = -z_level + 1
        # and bottom face at world z = -z_level.  Use the midpoint.
        plane_z = -z_level + 0.5

        # Ray: P = origin + t * direction
        # Solve for t where P.z == plane_z
        dz = direction.z
        if abs(dz) < 1e-12:
            return None  # Ray parallel to the layer plane

        t = (plane_z - origin.z) / dz
        if t < 0:
            return None  # Plane is behind the camera

        hit_x = origin.x + t * direction.x
        hit_y = origin.y + t * direction.y

        gx = int(math.floor(hit_x))
        gy = int(math.floor(hit_y))

        grid = self.game_state.voxel_grid
        if grid is None:
            return None
        if not grid.in_bounds(gx, gy, z_level):
            return None

        return gx, gy

    def _pick_voxel(self) -> tuple[int, int, int] | None:
        """Pick the solid voxel under the mouse on the current layer.

        Returns (x, y, z) grid coordinates or None.
        """
        ray = self._get_mouse_ray()
        if ray is None:
            return None

        hit = self._ray_hit_layer(*ray)
        if hit is None:
            return None

        gx, gy = hit
        z_level = self.layer_manager.current_z
        grid = self.game_state.voxel_grid
        if grid is None:
            return None

        if grid.get(gx, gy, z_level) != VOXEL_AIR:
            return (gx, gy, z_level)
        return None

    def _pick_air_voxel(self) -> tuple[int, int, int] | None:
        """Pick the air voxel under the mouse on the current layer.

        Used for right-click drop: find an air space to drop material into.
        """
        ray = self._get_mouse_ray()
        if ray is None:
            return None

        hit = self._ray_hit_layer(*ray)
        if hit is None:
            return None

        gx, gy = hit
        z_level = self.layer_manager.current_z
        grid = self.game_state.voxel_grid
        if grid is None:
            return None

        if grid.get(gx, gy, z_level) == VOXEL_AIR:
            return (gx, gy, z_level)
        return None
