"""Configurable keybinding registry with JSON persistence.

Maps logical action names (e.g. ``"camera_pan_forward"``) to Panda3D key
strings (e.g. ``"w"``).  All keyboard accept() calls should go through
``registry.get(action)`` instead of hardcoding key names.

Mouse bindings (mouse1/2/3, wheel) are NOT included — they're not rebindable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("dungeon_builder.keybinding")

SAVE_VERSION = 1

# ── Default bindings ────────────────────────────────────────────────────
# Keys use Panda3D naming: lowercase letters, "arrow_up", "space", etc.

DEFAULT_BINDINGS: dict[str, str] = {
    # Camera movement (continuous hold)
    "camera_pan_forward": "w",
    "camera_pan_backward": "s",
    "camera_pan_left": "a",
    "camera_pan_right": "d",
    "camera_pan_forward_alt": "arrow_up",
    "camera_pan_backward_alt": "arrow_down",
    "camera_pan_left_alt": "arrow_left",
    "camera_pan_right_alt": "arrow_right",
    "camera_rotate_left": "q",
    "camera_rotate_right": "e",
    # Z-level
    "z_level_up": "t",
    "z_level_down": "y",
    # Tools
    "toggle_tool": "x",
    "toggle_crafting_book": "b",
    "toggle_inventory": "i",
    "cycle_render_mode": "v",
    # Simulation speed
    "toggle_pause": "space",
    "speed_up": "+",
    "speed_up_alt": "=",
    "speed_down": "-",
}

# Human-readable labels for the keybinding menu
ACTION_LABELS: dict[str, str] = {
    "camera_pan_forward": "Pan Forward",
    "camera_pan_backward": "Pan Backward",
    "camera_pan_left": "Pan Left",
    "camera_pan_right": "Pan Right",
    "camera_pan_forward_alt": "Pan Forward (Alt)",
    "camera_pan_backward_alt": "Pan Backward (Alt)",
    "camera_pan_left_alt": "Pan Left (Alt)",
    "camera_pan_right_alt": "Pan Right (Alt)",
    "camera_rotate_left": "Rotate Left",
    "camera_rotate_right": "Rotate Right",
    "z_level_up": "Z-Level Up",
    "z_level_down": "Z-Level Down",
    "toggle_tool": "Toggle Tool",
    "toggle_crafting_book": "Crafting Book",
    "toggle_inventory": "Inventory",
    "cycle_render_mode": "Render Mode",
    "toggle_pause": "Pause/Resume",
    "speed_up": "Speed Up",
    "speed_up_alt": "Speed Up (Alt)",
    "speed_down": "Speed Down",
}


class KeybindingRegistry:
    """Central registry for configurable keyboard bindings.

    Pure Python, no Panda3D dependency — fully testable without a window.
    """

    def __init__(self, defaults: dict[str, str] | None = None) -> None:
        self._defaults: dict[str, str] = dict(defaults or DEFAULT_BINDINGS)
        self._bindings: dict[str, str] = dict(self._defaults)

    # ── Lookup ──────────────────────────────────────────────────────────

    def get(self, action: str) -> str:
        """Return the key currently bound to *action*.

        Raises ``KeyError`` if *action* is not a known action.
        """
        if action not in self._bindings:
            raise KeyError(f"Unknown action: {action!r}")
        return self._bindings[action]

    def get_action_for_key(self, key: str) -> str | None:
        """Reverse lookup: return the action bound to *key*, or ``None``."""
        for action, bound_key in self._bindings.items():
            if bound_key == key:
                return action
        return None

    def get_all_actions_for_key(self, key: str) -> list[str]:
        """Return all actions bound to *key* (may be multiple)."""
        return [a for a, k in self._bindings.items() if k == key]

    def get_conflicts(self, key: str, exclude_action: str) -> list[str]:
        """Return actions bound to *key* other than *exclude_action*."""
        return [
            a for a, k in self._bindings.items()
            if k == key and a != exclude_action
        ]

    @property
    def all_actions(self) -> list[str]:
        """Return all known action names in definition order."""
        return list(self._bindings)

    # ── Modification ────────────────────────────────────────────────────

    def set(self, action: str, key: str) -> str | None:
        """Bind *action* to *key*.  Returns conflicting action name or None.

        Does NOT automatically resolve conflicts — the caller must handle
        swaps or rejections.

        Raises ``KeyError`` if *action* is not a known action.
        """
        if action not in self._bindings:
            raise KeyError(f"Unknown action: {action!r}")

        conflicts = self.get_conflicts(key, exclude_action=action)
        self._bindings[action] = key
        return conflicts[0] if conflicts else None

    def swap(self, action: str, key: str) -> None:
        """Bind *action* to *key*, swapping with any conflicting action.

        If another action was using *key*, it gets *action*'s old key.
        """
        if action not in self._bindings:
            raise KeyError(f"Unknown action: {action!r}")

        old_key = self._bindings[action]
        conflicts = self.get_conflicts(key, exclude_action=action)

        self._bindings[action] = key
        for conflict_action in conflicts:
            self._bindings[conflict_action] = old_key

    def reset_defaults(self) -> None:
        """Restore all bindings to their defaults."""
        self._bindings = dict(self._defaults)

    def reset_action(self, action: str) -> None:
        """Restore a single action to its default binding.

        Raises ``KeyError`` if *action* is not a known action.
        """
        if action not in self._defaults:
            raise KeyError(f"Unknown action: {action!r}")
        self._bindings[action] = self._defaults[action]

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Serialize current bindings to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "version": SAVE_VERSION,
            "bindings": dict(self._bindings),
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Keybindings saved to %s", path)

    def load(self, path: Path) -> bool:
        """Load bindings from a JSON file.

        Returns ``True`` on success, ``False`` on any failure (missing file,
        corrupt JSON, version mismatch). On failure the registry keeps its
        current bindings.
        """
        if not path.is_file():
            logger.info("No keybinding file at %s, using defaults", path)
            return False

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read keybindings: %s", exc)
            return False

        if not isinstance(raw, dict):
            logger.warning("Keybinding file has invalid structure")
            return False

        version = raw.get("version", 0)
        if version != SAVE_VERSION:
            logger.warning(
                "Keybinding version mismatch: got %s, expected %s",
                version, SAVE_VERSION,
            )
            return False

        bindings = raw.get("bindings", {})
        if not isinstance(bindings, dict):
            return False

        # Only apply known actions (ignore stale entries)
        for action, key in bindings.items():
            if action in self._bindings and isinstance(key, str):
                self._bindings[action] = key

        logger.info("Keybindings loaded from %s", path)
        return True
