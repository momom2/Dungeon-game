"""Tests for dungeon_builder.core.keybinding_registry — configurable key bindings."""

import json

import pytest

from dungeon_builder.core.keybinding_registry import (
    KeybindingRegistry,
    DEFAULT_BINDINGS,
    ACTION_LABELS,
    SAVE_VERSION,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_registry(**overrides):
    """Create a registry with small default set for isolated tests."""
    defaults = {
        "pan_forward": "w",
        "pan_backward": "s",
        "pan_left": "a",
        "pan_right": "d",
        "rotate_left": "q",
        "rotate_right": "e",
        "z_up": "t",
        "z_down": "y",
        "toggle_tool": "x",
        "toggle_pause": "space",
    }
    defaults.update(overrides)
    return KeybindingRegistry(defaults)


# ── Default bindings ────────────────────────────────────────────────────


class TestDefaultBindings:
    def test_all_default_actions_present(self):
        reg = KeybindingRegistry()
        for action in DEFAULT_BINDINGS:
            assert reg.get(action) == DEFAULT_BINDINGS[action]

    def test_all_actions_have_labels(self):
        for action in DEFAULT_BINDINGS:
            assert action in ACTION_LABELS, f"Missing label for {action}"

    def test_all_actions_property(self):
        reg = _make_registry()
        assert len(reg.all_actions) == 10


# ── get / set ───────────────────────────────────────────────────────────


class TestGetSet:
    def test_get_returns_default(self):
        reg = _make_registry()
        assert reg.get("pan_forward") == "w"

    def test_get_unknown_action_raises(self):
        reg = _make_registry()
        with pytest.raises(KeyError, match="Unknown action"):
            reg.get("nonexistent")

    def test_set_changes_binding(self):
        reg = _make_registry()
        result = reg.set("pan_forward", "i")
        assert result is None  # No conflict
        assert reg.get("pan_forward") == "i"

    def test_set_unknown_action_raises(self):
        reg = _make_registry()
        with pytest.raises(KeyError):
            reg.set("nonexistent", "z")

    def test_set_detects_conflict(self):
        reg = _make_registry()
        # "w" is already bound to pan_forward
        conflict = reg.set("rotate_left", "w")
        assert conflict == "pan_forward"

    def test_set_no_conflict_with_self(self):
        reg = _make_registry()
        # Rebinding to the same key should not detect self as conflict
        result = reg.set("pan_forward", "w")
        assert result is None


# ── Reverse lookup ──────────────────────────────────────────────────────


class TestReverseLookup:
    def test_get_action_for_key(self):
        reg = _make_registry()
        assert reg.get_action_for_key("w") == "pan_forward"

    def test_get_action_for_unbound_key(self):
        reg = _make_registry()
        assert reg.get_action_for_key("z") is None

    def test_get_all_actions_for_key(self):
        reg = _make_registry()
        # Force two actions to same key
        reg.set("rotate_left", "w")
        actions = reg.get_all_actions_for_key("w")
        assert "pan_forward" in actions
        assert "rotate_left" in actions

    def test_get_conflicts(self):
        reg = _make_registry()
        conflicts = reg.get_conflicts("w", exclude_action="pan_forward")
        assert conflicts == []  # No conflict when excluding the owner

        reg.set("rotate_left", "w")
        conflicts = reg.get_conflicts("w", exclude_action="rotate_left")
        assert conflicts == ["pan_forward"]


# ── Swap ────────────────────────────────────────────────────────────────


class TestSwap:
    def test_swap_exchanges_keys(self):
        reg = _make_registry()
        # pan_forward=w, rotate_left=q
        reg.swap("pan_forward", "q")
        assert reg.get("pan_forward") == "q"
        assert reg.get("rotate_left") == "w"

    def test_swap_no_conflict(self):
        reg = _make_registry()
        reg.swap("pan_forward", "i")  # "i" is unused
        assert reg.get("pan_forward") == "i"

    def test_swap_unknown_action_raises(self):
        reg = _make_registry()
        with pytest.raises(KeyError):
            reg.swap("bogus", "z")


# ── Reset ───────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_defaults_restores_all(self):
        reg = _make_registry()
        reg.set("pan_forward", "i")
        reg.set("pan_backward", "k")
        reg.reset_defaults()
        assert reg.get("pan_forward") == "w"
        assert reg.get("pan_backward") == "s"

    def test_reset_action_restores_one(self):
        reg = _make_registry()
        reg.set("pan_forward", "i")
        reg.set("pan_backward", "k")
        reg.reset_action("pan_forward")
        assert reg.get("pan_forward") == "w"
        assert reg.get("pan_backward") == "k"  # Unchanged

    def test_reset_unknown_action_raises(self):
        reg = _make_registry()
        with pytest.raises(KeyError):
            reg.reset_action("bogus")


# ── Save / Load ─────────────────────────────────────────────────────────


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        reg = _make_registry()
        reg.set("pan_forward", "i")
        path = tmp_path / "keys.json"
        reg.save(path)

        reg2 = _make_registry()
        assert reg2.load(path) is True
        assert reg2.get("pan_forward") == "i"

    def test_save_creates_parent_dirs(self, tmp_path):
        reg = _make_registry()
        path = tmp_path / "deep" / "nested" / "keys.json"
        reg.save(path)
        assert path.is_file()

    def test_load_nonexistent_file(self, tmp_path):
        reg = _make_registry()
        result = reg.load(tmp_path / "nope.json")
        assert result is False
        # Defaults preserved
        assert reg.get("pan_forward") == "w"

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{invalid json", encoding="utf-8")
        reg = _make_registry()
        assert reg.load(path) is False
        assert reg.get("pan_forward") == "w"

    def test_load_wrong_version(self, tmp_path):
        path = tmp_path / "v99.json"
        data = {"version": 99, "bindings": {"pan_forward": "i"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        reg = _make_registry()
        assert reg.load(path) is False

    def test_load_ignores_unknown_actions(self, tmp_path):
        path = tmp_path / "extra.json"
        data = {
            "version": SAVE_VERSION,
            "bindings": {"pan_forward": "i", "bogus_action": "z"},
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        reg = _make_registry()
        assert reg.load(path) is True
        assert reg.get("pan_forward") == "i"
        # bogus_action silently ignored
        with pytest.raises(KeyError):
            reg.get("bogus_action")

    def test_load_preserves_unmentioned_actions(self, tmp_path):
        """A save file that only has a subset of actions should keep others at default."""
        path = tmp_path / "partial.json"
        data = {"version": SAVE_VERSION, "bindings": {"pan_forward": "i"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        reg = _make_registry()
        assert reg.load(path) is True
        assert reg.get("pan_forward") == "i"
        assert reg.get("pan_backward") == "s"  # Still default

    def test_save_file_is_valid_json(self, tmp_path):
        reg = _make_registry()
        path = tmp_path / "keys.json"
        reg.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == SAVE_VERSION
        assert isinstance(data["bindings"], dict)
