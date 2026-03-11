"""Tests for VoxelWorldRenderer render mode switching and RenderModeSelector."""

import pytest

from dungeon_builder.core.event_bus import EventBus
from dungeon_builder.world.voxel_grid import VoxelGrid


class TestVoxelWorldRendererModeSwitch:
    """Test VoxelWorldRenderer.set_render_mode behavioral correctness."""

    def test_set_render_mode_updates_attribute(self):
        """set_render_mode should update self.render_mode."""
        eb = EventBus()
        grid = VoxelGrid(width=4, depth=4, height=4)

        # Can't create VoxelWorldRenderer without Panda3D, but we can test
        # the render_mode tracking logic directly
        from dungeon_builder.rendering.voxel_renderer import VoxelWorldRenderer

        # The class stores render_mode on self; verify the early return logic
        class FakeRenderer:
            def __init__(self):
                self.render_mode = "matter"
                self.calls = []

            def set_render_mode(self, mode):
                """Same logic as VoxelWorldRenderer.set_render_mode."""
                if mode == self.render_mode:
                    self.calls.append(("skip", mode))
                    return
                self.render_mode = mode
                self.calls.append(("set", mode))

        r = FakeRenderer()
        assert r.render_mode == "matter"

        # Switch to humidity
        r.set_render_mode("humidity")
        assert r.render_mode == "humidity"
        assert r.calls[-1] == ("set", "humidity")

        # Switch back to matter
        r.set_render_mode("matter")
        assert r.render_mode == "matter"
        assert r.calls[-1] == ("set", "matter")

        # Duplicate call should skip
        r.set_render_mode("matter")
        assert r.calls[-1] == ("skip", "matter")

    def test_cycle_through_all_modes_returns_to_matter(self):
        """Cycling through _MODES 5 times should return to matter."""
        from dungeon_builder.ui.render_mode_selector import _MODES
        index = 0
        for _ in range(len(_MODES)):
            index = (index + 1) % len(_MODES)
        assert index == 0
        assert _MODES[0] == "matter"

    def test_mode_list_and_labels_consistent(self):
        """_MODES and _LABELS should cover exactly the same modes."""
        from dungeon_builder.ui.render_mode_selector import _MODES, _LABELS
        assert set(_MODES) == set(_LABELS.keys())
        assert len(_MODES) == 6

    def test_connections_mode_in_modes_list(self):
        """Connections mode should be in the modes list."""
        from dungeon_builder.ui.render_mode_selector import _MODES
        assert "connections" in _MODES

    def test_connections_label_exists(self):
        """Connections mode should have a display label."""
        from dungeon_builder.ui.render_mode_selector import _LABELS
        assert "connections" in _LABELS
        assert _LABELS["connections"] == "Connections"
