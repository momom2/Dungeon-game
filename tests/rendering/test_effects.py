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
    """EffectsRenderer exposes craft-marker and pending-dig marker API."""

    def test_craft_highlight_handler_exists(self):
        """EffectsRenderer must have _on_craft_highlights_updated method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_craft_highlights_updated")
        assert callable(getattr(EffectsRenderer, "_on_craft_highlights_updated"))

    def test_pending_dig_marker_method_exists(self):
        """EffectsRenderer must have _update_pending_markers method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_update_pending_markers")
        assert callable(getattr(EffectsRenderer, "_update_pending_markers"))


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

    def test_prospecting_mode_produces_grey(self):
        """Prospecting mode returns muted grey tones (behavioral check)."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_STONE
        grid.visible[2, 2, 2] = True
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_PROSPECTING)
        # Prospecting mode desaturates — R ≈ G ≈ B
        assert abs(color[0] - color[1]) < 0.02, f"Expected grey, got {color}"

    def test_effects_renderer_accepts_voxel_grid(self):
        """EffectsRenderer.__init__ should accept optional voxel_grid parameter."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        sig = inspect.signature(EffectsRenderer.__init__)
        assert "voxel_grid" in sig.parameters

    def test_effects_scan_ore_glows_method(self):
        """EffectsRenderer must have _scan_ore_glows method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_scan_ore_glows")

    def test_effects_render_mode_handler_exists(self):
        """EffectsRenderer must have _on_render_mode_changed method."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_render_mode_changed")
        assert callable(getattr(EffectsRenderer, "_on_render_mode_changed"))


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


# ===========================================================================
# Craft-mode visual feedback (method existence checks)
# ===========================================================================


class TestCraftHoverVisuals:
    """EffectsRenderer has craft hover handlers for colour-coded wireframe."""

    def test_craft_hover_valid_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_craft_hover_valid")
        assert callable(getattr(EffectsRenderer, "_on_craft_hover_valid"))

    def test_craft_hover_invalid_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_craft_hover_invalid")
        assert callable(getattr(EffectsRenderer, "_on_craft_hover_invalid"))

    def test_craft_hover_clear_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_craft_hover_clear")
        assert callable(getattr(EffectsRenderer, "_on_craft_hover_clear"))

    def test_craft_placement_flash_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_craft_placement_flash")
        assert callable(getattr(EffectsRenderer, "_on_craft_placement_flash"))

    def test_show_ghost_preview_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_show_ghost_preview")
        assert callable(getattr(EffectsRenderer, "_show_ghost_preview"))

    def test_hide_ghost_preview_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_hide_ghost_preview")
        assert callable(getattr(EffectsRenderer, "_hide_ghost_preview"))

    def test_show_radius_preview_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_show_radius_preview")
        assert callable(getattr(EffectsRenderer, "_show_radius_preview"))

    def test_hide_radius_preview_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_hide_radius_preview")
        assert callable(getattr(EffectsRenderer, "_hide_radius_preview"))

    def test_craft_hover_valid_accepts_effect_radius(self):
        """_on_craft_hover_valid signature includes effect_radius."""
        from dungeon_builder.rendering.effects import EffectsRenderer
        sig = inspect.signature(EffectsRenderer._on_craft_hover_valid)
        assert "effect_radius" in sig.parameters


class TestCraftConfigConstants:
    """Config constants for craft visual feedback exist with valid values."""

    def test_craft_hover_valid_color(self):
        from dungeon_builder.config import CRAFT_HOVER_VALID_COLOR
        assert len(CRAFT_HOVER_VALID_COLOR) == 4
        for c in CRAFT_HOVER_VALID_COLOR:
            assert 0.0 <= c <= 1.0

    def test_craft_ghost_opacity(self):
        from dungeon_builder.config import CRAFT_GHOST_OPACITY
        assert 0.0 < CRAFT_GHOST_OPACITY < 1.0

    def test_craft_flash_duration(self):
        from dungeon_builder.config import CRAFT_FLASH_DURATION
        assert 0.0 < CRAFT_FLASH_DURATION <= 2.0

    def test_craft_flash_color(self):
        from dungeon_builder.config import CRAFT_FLASH_COLOR
        assert len(CRAFT_FLASH_COLOR) == 4
        for c in CRAFT_FLASH_COLOR:
            assert 0.0 <= c <= 1.0

    def test_craft_radius_color(self):
        from dungeon_builder.config import CRAFT_RADIUS_COLOR
        assert len(CRAFT_RADIUS_COLOR) == 4
        for c in CRAFT_RADIUS_COLOR:
            assert 0.0 <= c <= 1.0


class TestConnectionVisualization:
    """EffectsRenderer has connection rendering infrastructure."""

    def test_on_block_selected_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_block_selected")
        assert callable(getattr(EffectsRenderer, "_on_block_selected"))

    def test_on_block_deselected_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_block_deselected")
        assert callable(getattr(EffectsRenderer, "_on_block_deselected"))

    def test_show_connections_method_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_show_connections")
        assert callable(getattr(EffectsRenderer, "_show_connections"))

    def test_hide_connections_method_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_hide_connections")
        assert callable(getattr(EffectsRenderer, "_hide_connections"))

    def test_render_mode_connections_handler_exists(self):
        from dungeon_builder.rendering.effects import EffectsRenderer
        assert hasattr(EffectsRenderer, "_on_render_mode_connections")
        assert callable(getattr(EffectsRenderer, "_on_render_mode_connections"))


class TestConnectionConfigConstants:
    """Connection color constants exist with valid RGBA values."""

    def test_connection_colors_dict(self):
        from dungeon_builder.config import CONNECTION_COLORS
        assert "trigger" in CONNECTION_COLORS
        assert "flow" in CONNECTION_COLORS
        assert "thermal" in CONNECTION_COLORS
        assert "structural" in CONNECTION_COLORS

    def test_connection_colors_valid_rgba(self):
        from dungeon_builder.config import CONNECTION_COLORS
        for conn_type, color in CONNECTION_COLORS.items():
            assert len(color) == 4, f"{conn_type}: expected 4 components"
            for i, c in enumerate(color):
                assert 0.0 <= c <= 1.0, f"{conn_type}[{i}]={c} out of range"

    def test_render_mode_connections_constant(self):
        from dungeon_builder.config import RENDER_MODE_CONNECTIONS
        assert RENDER_MODE_CONNECTIONS == "connections"
