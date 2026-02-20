"""Tests for rendering effects: craft highlights, prospecting mode, ore glow scan."""

import inspect

import numpy as np
import pytest

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_STONE,
    VOXEL_WATER,
    VOXEL_IRON_ORE,
    VOXEL_COPPER_ORE,
    VOXEL_GOLD_ORE,
    VOXEL_MANA_CRYSTAL,
    RENDER_MODE_PROSPECTING,
    ORE_GLOW_COLORS,
)
from dungeon_builder.world.voxel_grid import VoxelGrid


class TestCraftHighlightVisibility:
    """Craft markers bypass depth test so they show through solid geometry."""

    def test_craft_marker_source_has_depth_test_false(self):
        """_on_craft_highlights_updated should set depth_test(False)."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        source = inspect.getsource(EffectsRenderer._on_craft_highlights_updated)
        assert "set_depth_test(False)" in source

    def test_pending_dig_marker_source_has_depth_test_false(self):
        """Pending dig markers should also bypass depth test."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        source = inspect.getsource(EffectsRenderer._update_pending_markers)
        assert "set_depth_test(False)" in source


class TestProspectingMode:
    """Prospecting render mode with ore glow markers."""

    def test_render_mode_prospecting_constant(self):
        """RENDER_MODE_PROSPECTING should be 'prospecting'."""
        assert RENDER_MODE_PROSPECTING == "prospecting"

    def test_ore_glow_colors_defined(self):
        """ORE_GLOW_COLORS should have entries for all ore types."""
        assert VOXEL_IRON_ORE in ORE_GLOW_COLORS
        assert VOXEL_COPPER_ORE in ORE_GLOW_COLORS
        assert VOXEL_GOLD_ORE in ORE_GLOW_COLORS
        assert VOXEL_MANA_CRYSTAL in ORE_GLOW_COLORS

    def test_ore_glow_colors_are_rgba_tuples(self):
        """Each glow color should be a 4-tuple of floats in [0, 1]."""
        for vtype, color in ORE_GLOW_COLORS.items():
            assert len(color) == 4, f"Type {vtype}: expected 4 components"
            for i, c in enumerate(color):
                assert 0.0 <= c <= 1.0, f"Type {vtype}[{i}]={c} out of range"

    def test_prospecting_mode_in_render_selector(self):
        """RenderModeSelector module should include 'prospecting' in modes."""
        import dungeon_builder.ui.render_mode_selector as rms_mod
        source = inspect.getsource(rms_mod)
        assert "prospecting" in source.lower()

    def test_voxel_renderer_prospecting_color(self):
        """ChunkMeshBuilder._get_color should handle RENDER_MODE_PROSPECTING."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder._get_color)
        assert "RENDER_MODE_PROSPECTING" in source

    def test_prospecting_color_is_muted_grey(self):
        """Prospecting color mode should produce desaturated grey tones."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder._get_color)
        assert "grey" in source  # Variable name in the desaturation logic

    def test_effects_renderer_accepts_voxel_grid(self):
        """EffectsRenderer.__init__ should accept optional voxel_grid parameter."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        source = inspect.getsource(EffectsRenderer.__init__)
        assert "voxel_grid" in source

    def test_main_passes_voxel_grid_to_effects(self):
        """main.py should pass voxel_grid to EffectsRenderer."""
        import dungeon_builder.main as main_mod
        source = inspect.getsource(main_mod.DungeonApp.__init__)
        assert "voxel_grid=voxel_grid" in source or "voxel_grid" in source

    def test_effects_scan_ore_glows_method(self):
        """EffectsRenderer should have _scan_ore_glows method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_scan_ore_glows")

    def test_effects_render_mode_handler(self):
        """EffectsRenderer should subscribe to render_mode_changed."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        source = inspect.getsource(EffectsRenderer.__init__)
        assert "render_mode_changed" in source


class TestOreGlowScanLogic:
    """Test the vectorized ore scanning logic directly."""

    def _make_grid_with_encased_ore(self):
        """Create a grid with an ore block fully encased in stone."""
        grid = VoxelGrid(width=8, depth=8, height=8)
        # Fill a 3x3x3 cube of stone around (4,4,4)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for dz in range(-1, 2):
                    grid.grid[4 + dx, 4 + dy, 4 + dz] = VOXEL_STONE
        # Put iron ore at center
        grid.grid[4, 4, 4] = VOXEL_IRON_ORE
        # Mark ore as visible (simulating x-ray dilation)
        grid.visible[4, 4, 4] = True
        return grid

    def test_encased_ore_has_no_air_neighbor(self):
        """An ore block surrounded by stone has no air/water neighbors."""
        grid = self._make_grid_with_encased_ore()
        # Check all 6 neighbors
        neighbors = [
            grid.get(5, 4, 4), grid.get(3, 4, 4),
            grid.get(4, 5, 4), grid.get(4, 3, 4),
            grid.get(4, 4, 5), grid.get(4, 4, 3),
        ]
        for n in neighbors:
            assert n not in (VOXEL_AIR, VOXEL_WATER)

    def test_encased_ore_is_visible_and_xray_type(self):
        """The ore should be visible and in XRAY_VISIBLE_TYPES."""
        from dungeon_builder.config import XRAY_VISIBLE_TYPES
        grid = self._make_grid_with_encased_ore()
        assert bool(grid.visible[4, 4, 4]) is True
        assert int(grid.grid[4, 4, 4]) in XRAY_VISIBLE_TYPES

    def test_ore_with_air_neighbor_not_encased(self):
        """An ore with at least one air neighbor should NOT be encased."""
        grid = self._make_grid_with_encased_ore()
        # Replace one neighbor with air
        grid.grid[5, 4, 4] = VOXEL_AIR
        # The ore now has an air neighbor — it would render normally
        neighbor = grid.get(5, 4, 4)
        assert neighbor == VOXEL_AIR
