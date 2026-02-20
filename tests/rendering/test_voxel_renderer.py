"""Tests for voxel renderer: face transparency, winding, render mode colors."""

import inspect

import numpy as np
import pytest

from dungeon_builder.config import (
    VOXEL_AIR,
    VOXEL_BEDROCK,
    VOXEL_STONE,
    VOXEL_WATER,
    VOXEL_LAVA,
    FACE_TRANSPARENT_VOXELS,
    FLUID_VOXELS,
    RENDER_MODE_PROSPECTING,
    RENDER_MODE_MATTER,
)
from dungeon_builder.world.voxel_grid import VoxelGrid
from dungeon_builder.rendering.voxel_renderer import FACES


class TestFaceTransparentVoxels:
    """FACE_TRANSPARENT_VOXELS contains air and water."""

    def test_face_transparent_voxels_contains_air_and_water(self):
        """Both VOXEL_AIR and VOXEL_WATER must be in the set."""
        assert VOXEL_AIR in FACE_TRANSPARENT_VOXELS
        assert VOXEL_WATER in FACE_TRANSPARENT_VOXELS

    def test_water_neighbor_allows_face_render(self):
        """Stone next to water: neighbor is in FACE_TRANSPARENT_VOXELS."""
        grid = VoxelGrid(width=4, depth=4, height=4)
        grid.grid[1, 0, 0] = VOXEL_STONE
        grid.grid[2, 0, 0] = VOXEL_WATER
        neighbor = grid.get(2, 0, 0)
        assert neighbor in FACE_TRANSPARENT_VOXELS

    def test_stone_neighbor_blocks_face_render(self):
        """Stone next to stone: neighbor is NOT in FACE_TRANSPARENT_VOXELS."""
        assert VOXEL_STONE not in FACE_TRANSPARENT_VOXELS
        assert VOXEL_BEDROCK not in FACE_TRANSPARENT_VOXELS


class TestBottomFaceSkip:
    """Verify bottom face is in FACES list (for skip logic)."""

    def test_bottom_face_in_faces_list(self):
        """FACES[1] should be the bottom face entry."""
        assert FACES[1][3] == "bottom"

    def test_bottom_face_skip_in_build_source(self):
        """build() method should skip 'bottom' faces."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        assert "bottom" in source
        assert "continue" in source


class TestFaceWinding:
    """All face vertex quads must have CCW winding matching their normal."""

    @staticmethod
    def _cross(a, b):
        """3D cross product of tuples a and b."""
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    @staticmethod
    def _sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def test_all_side_faces_have_correct_ccw_winding(self):
        """East/west/north/south geometric normals match intended normals."""
        from dungeon_builder.rendering.voxel_renderer import FACE_VERTICES, FACE_NORMALS
        for face_name in ("east", "west", "north", "south"):
            verts = FACE_VERTICES[face_name]
            v0, v1, v2 = verts[0], verts[1], verts[2]
            edge1 = self._sub(v1, v0)
            edge2 = self._sub(v2, v0)
            geometric_normal = self._cross(edge1, edge2)
            intended = FACE_NORMALS[face_name]
            assert geometric_normal == intended, (
                f"{face_name}: geometric {geometric_normal} != intended {intended}"
            )

    def test_top_face_has_correct_ccw_winding(self):
        """Top face geometric normal matches (0, 0, 1)."""
        from dungeon_builder.rendering.voxel_renderer import FACE_VERTICES, FACE_NORMALS
        verts = FACE_VERTICES["top"]
        v0, v1, v2 = verts[0], verts[1], verts[2]
        edge1 = self._sub(v1, v0)
        edge2 = self._sub(v2, v0)
        geometric_normal = self._cross(edge1, edge2)
        assert geometric_normal == FACE_NORMALS["top"]


class TestRenderModeColorOutput:
    """ChunkMeshBuilder._get_color returns correct colors for each render mode.

    These are *behavioral* tests: they exercise the actual color logic with
    a real VoxelGrid, not just inspect source strings.
    """

    def _make_visible_grid(self):
        """Return a grid with a visible stone block at (2,2,2)."""
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_STONE
        grid.visible[2, 2, 2] = True
        return grid

    def test_matter_mode_returns_voxel_color(self):
        """Matter mode returns the base VOXEL_COLORS for the block type."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import VOXEL_COLORS, RENDER_MODE_MATTER
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_MATTER)
        expected = VOXEL_COLORS[VOXEL_STONE]
        assert color == expected, f"Matter color {color} != expected {expected}"

    def test_humidity_mode_returns_tinted_matter_color(self):
        """Humidity mode tints matter colors toward blue, not replacing them."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import VOXEL_COLORS, RENDER_MODE_HUMIDITY
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        # Default humidity is 0.0 → pure matter color (no tint)
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_HUMIDITY)
        expected = VOXEL_COLORS[VOXEL_STONE]
        assert color == expected, f"At h=0, humidity color should be matter: {color}"
        # Set humidity high → blue tint applied
        grid.humidity[2, 2, 2] = 1.0
        color_wet = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_HUMIDITY)
        assert color_wet[2] > color_wet[0], f"Expected blue > red at h=1: {color_wet}"
        assert color_wet != expected, "High humidity should differ from matter"

    def test_heat_mode_returns_temperature_color(self):
        """Heat mode returns temperature-based blue-white-red gradient."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import RENDER_MODE_HEAT
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        # Default temp is 0.0 → deep blue
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_HEAT)
        assert color[2] > 0.3, f"Expected blue channel > 0.3 at 0°C, got {color}"

    def test_structural_mode_returns_stress_color(self):
        """Structural mode returns green (low stress) to red (high stress)."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import RENDER_MODE_STRUCTURAL
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        # Default stress_ratio is 0.0 → green-ish (low stress)
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_STRUCTURAL)
        # At stress=0: (0, 0.7, 0, 1)
        assert color[1] >= 0.7, f"Expected green channel >= 0.7 at zero stress, got {color}"

    def test_prospecting_mode_returns_grey(self):
        """Prospecting mode returns muted grey tones."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_PROSPECTING)
        # Should be greyish — R ≈ G ≈ B, all in 0.18-0.30 range
        assert 0.15 < color[0] < 0.35, f"Prospecting grey R out of range: {color}"
        assert abs(color[0] - color[1]) < 0.02, f"Prospecting R/G mismatch: {color}"

    def test_matter_after_humidity_returns_correct_colors(self):
        """Switching matter→humidity→matter should return original matter colors.

        This is the KEY bug test: the user reports 'all shades of black'
        when switching back to matter mode.
        """
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import VOXEL_COLORS, RENDER_MODE_MATTER, RENDER_MODE_HUMIDITY
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        grid.humidity[2, 2, 2] = 0.8  # high humidity so tint is visible

        # 1. Get matter color
        matter_color_1 = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_MATTER)
        expected = VOXEL_COLORS[VOXEL_STONE]
        assert matter_color_1 == expected

        # 2. Get humidity color (simulates switching to humidity — tinted blue)
        humidity_color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_HUMIDITY)
        assert humidity_color != expected, "Humidity at 0.8 should differ from matter"

        # 3. Get matter color again (simulates switching back)
        matter_color_2 = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_MATTER)
        assert matter_color_2 == expected, (
            f"Matter color after switch: {matter_color_2} != expected {expected}. "
            "This is the 'shades of black' bug!"
        )

    def test_cycling_all_modes_then_back_to_matter(self):
        """Cycle through all 5 modes and back to matter — colors should be correct."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import VOXEL_COLORS, RENDER_MODE_MATTER
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid()
        expected = VOXEL_COLORS[VOXEL_STONE]

        modes = ["matter", "humidity", "heat", "structural", "prospecting"]
        for mode in modes:
            builder._get_color(grid, 2, 2, 2, VOXEL_STONE, mode)

        # Back to matter
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_MATTER)
        assert color == expected, (
            f"After cycling all modes: {color} != {expected}"
        )

    def test_invisible_block_returns_fog_color(self):
        """Invisible block should return FOG_COLOR regardless of mode."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        import dungeon_builder.config as _cfg
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_STONE
        # visible is False by default
        assert not grid.is_visible(2, 2, 2)

        for mode in ["matter", "humidity", "heat", "structural", "prospecting"]:
            color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, mode)
            assert color == _cfg.FOG_COLOR, (
                f"Mode {mode}: invisible block returned {color}, expected FOG_COLOR"
            )


class TestGoldenOverlayAllFaces:
    """Dig-queued blocks show golden overlay on ALL faces, not just air-adjacent."""

    def test_build_checks_is_being_dug_before_face_culling(self):
        """build() should check is_being_dug to bypass face culling."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        assert "is_being_dug" in source

    def test_is_being_dug_check_is_per_voxel(self):
        """is_being_dug check should appear BEFORE the face loop, not inside it.

        The variable 'is_dig' is set per-voxel (before iterating faces),
        so we check it appears before 'for face_idx'.
        """
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        # is_dig assignment should come before the face loop
        is_dig_pos = source.find("is_dig")
        face_loop_pos = source.find("for face_idx")
        assert is_dig_pos != -1, "is_dig not found in build()"
        assert face_loop_pos != -1, "face loop not found in build()"
        assert is_dig_pos < face_loop_pos, (
            "is_dig should be computed before the face loop (per-voxel, not per-face)"
        )

    def test_non_dig_blocks_still_get_normal_culling(self):
        """Non-dig blocks should still skip faces adjacent to solid neighbors."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        # The culling condition should check: not is_dig AND neighbor not transparent
        assert "not is_dig" in source
        assert "FACE_TRANSPARENT_VOXELS" in source

    def test_dig_blocks_bypass_face_culling(self):
        """Dig-queued blocks should render faces even with solid neighbors.

        The logic: if is_dig is True, the 'continue' for solid neighbors
        is skipped, so ALL faces are rendered.
        """
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        # Find the culling line — it should be:
        # if not is_dig and neighbor not in FACE_TRANSPARENT_VOXELS:
        #     continue
        assert "if not is_dig and neighbor not in FACE_TRANSPARENT_VOXELS" in source


class TestHumidityTintOverlay:
    """Humidity mode tints matter colours toward blue proportionally."""

    def _make_visible_grid(self, humidity: float = 0.0):
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_STONE
        grid.visible[2, 2, 2] = True
        grid.humidity[2, 2, 2] = humidity
        return grid

    def test_tint_zero_returns_base_color(self):
        """At h=0, tint overlay returns the base colour unchanged."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        base = (0.5, 0.5, 0.5, 1.0)
        result = humidity_to_color(0.0, base_color=base)
        assert result == base

    def test_tint_full_humidity_shifts_blue(self):
        """At h=1.0, blue channel is significantly increased."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        base = (0.5, 0.5, 0.5, 1.0)
        r, g, b, a = humidity_to_color(1.0, base_color=base)
        # t = 0.6, so b = 0.5*(1-0.6) + 0.9*0.6 = 0.2 + 0.54 = 0.74
        assert b == pytest.approx(0.74)
        assert r < base[0], "Red should decrease with humidity tint"
        assert a == base[3], "Alpha should be preserved"

    def test_tint_preserves_material_identity(self):
        """Different materials tinted at same humidity still differ."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        from dungeon_builder.config import VOXEL_COLORS, VOXEL_DIRT
        stone_base = VOXEL_COLORS[VOXEL_STONE]
        dirt_base = VOXEL_COLORS[VOXEL_DIRT]
        stone_wet = humidity_to_color(0.8, base_color=stone_base)
        dirt_wet = humidity_to_color(0.8, base_color=dirt_base)
        assert stone_wet != dirt_wet, "Tinted stone and dirt should still differ"

    def test_tint_max_sixty_percent(self):
        """Even at h=1.0 the tint is capped at 60 % blend."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        base = (1.0, 1.0, 1.0, 1.0)
        r, g, b, a = humidity_to_color(1.0, base_color=base)
        # With 60% blend: r = 1.0*0.4 + 0.1*0.6 = 0.46
        assert r == pytest.approx(0.46)
        # g = 1.0*0.4 + 0.3*0.6 = 0.58
        assert g == pytest.approx(0.58)
        # b = 1.0*0.4 + 0.9*0.6 = 0.94
        assert b == pytest.approx(0.94)

    def test_get_color_humidity_uses_matter_as_base(self):
        """_get_color in humidity mode returns tinted matter colour."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        from dungeon_builder.config import VOXEL_COLORS, RENDER_MODE_HUMIDITY
        builder = ChunkMeshBuilder()
        grid = self._make_visible_grid(humidity=0.5)
        color = builder._get_color(grid, 2, 2, 2, VOXEL_STONE, RENDER_MODE_HUMIDITY)
        base = VOXEL_COLORS[VOXEL_STONE]
        # Should be between base and blue target
        assert color[2] > base[2], "Blue channel should increase at h=0.5"
        assert color[0] < base[0], "Red channel should decrease at h=0.5"

    def test_legacy_gradient_without_base_color(self):
        """Legacy gradient (no base_color) still produces blue→cyan→green."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        # h=0 → deep blue
        r, g, b, a = humidity_to_color(0.0)
        assert b == pytest.approx(1.0)
        assert r == pytest.approx(0.0)
        # h=1 → green
        r, g, b, a = humidity_to_color(1.0)
        assert g == pytest.approx(1.0)
        assert b == pytest.approx(0.0)

    def test_face_name_param_accepted_but_ignored_with_base(self):
        """face_name is accepted for API compat but ignored when base_color given."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        base = (0.5, 0.5, 0.5, 1.0)
        c_top = humidity_to_color(0.7, face_name="top", base_color=base)
        c_east = humidity_to_color(0.7, face_name="east", base_color=base)
        assert c_top == c_east, "face_name should not affect tint overlay"

    def test_humidity_clamps_to_range(self):
        """Humidity values outside [0,1] are clamped."""
        from dungeon_builder.rendering.voxel_renderer import humidity_to_color
        base = (0.5, 0.5, 0.5, 1.0)
        assert humidity_to_color(-0.5, base_color=base) == humidity_to_color(0.0, base_color=base)
        assert humidity_to_color(1.5, base_color=base) == humidity_to_color(1.0, base_color=base)


class TestLayerDepthFade:
    """LAYER_DEPTH_FADE config controls depth-based transparency."""

    def test_depth_fade_off_shows_all_layers(self):
        """When LAYER_DEPTH_FADE is False, all layers should be visible."""
        import dungeon_builder.config as _cfg
        _cfg.LAYER_DEPTH_FADE = False
        try:
            from dungeon_builder.rendering.layer_slice import LayerSliceManager
            from panda3d.core import NodePath
            root = NodePath("root")
            lm = LayerSliceManager(root)
            lm.set_focus_z(10)
            # Every layer should be shown (not hidden)
            for z, np in lm.layers.items():
                assert not np.is_hidden(), f"Layer {z} hidden with depth_fade off"
        finally:
            _cfg.LAYER_DEPTH_FADE = True

    def test_depth_fade_on_hides_distant_layers(self):
        """When LAYER_DEPTH_FADE is True, far layers should be hidden."""
        import dungeon_builder.config as _cfg
        _cfg.LAYER_DEPTH_FADE = True
        from dungeon_builder.rendering.layer_slice import LayerSliceManager
        from panda3d.core import NodePath
        root = NodePath("root")
        lm = LayerSliceManager(root)
        lm.set_focus_z(10)
        # Layer far below focus should be hidden
        far_z = 10 + _cfg.LAYER_MAX_VISIBLE_BELOW + 1
        if far_z < _cfg.GRID_HEIGHT:
            assert lm.layers[far_z].is_hidden(), f"Layer {far_z} should be hidden"

    def test_config_changed_reapplies(self):
        """Publishing config_changed with LAYER_DEPTH_FADE key re-applies."""
        import dungeon_builder.config as _cfg
        from dungeon_builder.core.event_bus import EventBus
        from dungeon_builder.rendering.layer_slice import LayerSliceManager
        from panda3d.core import NodePath
        bus = EventBus()
        root = NodePath("root")
        lm = LayerSliceManager(root, event_bus=bus)
        lm.set_focus_z(10)
        # Now disable depth fade via config
        _cfg.LAYER_DEPTH_FADE = False
        bus.publish("config_changed", key="LAYER_DEPTH_FADE")
        # All layers should now be visible
        for z, np in lm.layers.items():
            assert not np.is_hidden(), f"Layer {z} hidden after config toggle"
        _cfg.LAYER_DEPTH_FADE = True  # cleanup


class TestFluidRendering:
    """Partial-height fluid rendering: geometry, face culling, and alpha."""

    def test_fluid_voxels_constant_contains_water_and_lava(self):
        """FLUID_VOXELS frozenset has both VOXEL_WATER and VOXEL_LAVA."""
        assert VOXEL_WATER in FLUID_VOXELS
        assert VOXEL_LAVA in FLUID_VOXELS
        assert VOXEL_STONE not in FLUID_VOXELS
        assert VOXEL_AIR not in FLUID_VOXELS

    def test_water_alpha_at_full_level(self):
        """Water at level=255 should have alpha=0.7 (existing default)."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_WATER
        grid.water_level[2, 2, 2] = 255
        grid.visible[2, 2, 2] = True
        color = builder._get_matter_color(grid, 2, 2, 2, VOXEL_WATER)
        assert color[3] == pytest.approx(0.7)

    def test_water_alpha_at_half_level(self):
        """Water at level=128 should have proportional alpha."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_WATER
        grid.water_level[2, 2, 2] = 128
        grid.visible[2, 2, 2] = True
        color = builder._get_matter_color(grid, 2, 2, 2, VOXEL_WATER)
        expected_alpha = 128 / 255.0
        assert color[3] == pytest.approx(expected_alpha)

    def test_water_alpha_minimum_floor(self):
        """Water at very low level should have alpha >= 0.3."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_WATER
        grid.water_level[2, 2, 2] = 10
        grid.visible[2, 2, 2] = True
        color = builder._get_matter_color(grid, 2, 2, 2, VOXEL_WATER)
        assert color[3] == pytest.approx(0.3)

    def test_lava_alpha_unchanged_at_full(self):
        """Lava at level=255 still has alpha=1.0 (regression)."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_LAVA
        grid.lava_level[2, 2, 2] = 255
        grid.visible[2, 2, 2] = True
        color = builder._get_matter_color(grid, 2, 2, 2, VOXEL_LAVA)
        assert color[3] == pytest.approx(1.0)

    def test_lava_alpha_at_half_level(self):
        """Lava at level=128 should have proportional alpha."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        builder = ChunkMeshBuilder()
        grid = VoxelGrid(width=8, depth=8, height=8)
        grid.grid[2, 2, 2] = VOXEL_LAVA
        grid.lava_level[2, 2, 2] = 128
        grid.visible[2, 2, 2] = True
        color = builder._get_matter_color(grid, 2, 2, 2, VOXEL_LAVA)
        expected_alpha = 128 / 255.0
        assert color[3] == pytest.approx(expected_alpha)

    def test_build_computes_fill_fraction_for_fluids(self):
        """build() should compute fill_fraction from fluid level."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        assert "FLUID_VOXELS" in source
        assert "fill_fraction" in source
        assert "fluid_level" in source

    def test_build_adjusts_vertex_height_for_fluids(self):
        """build() should lower oz=1 vertices to fill_fraction."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        assert "oz == 1" in source
        assert "fill_fraction" in source

    def test_build_has_fluid_face_culling(self):
        """build() should skip faces between same-type same-level fluids."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        assert "neighbor_level" in source
        assert "is_fluid" in source

    def test_fill_fraction_before_face_loop(self):
        """fill_fraction computed per-voxel (before face iteration)."""
        from dungeon_builder.rendering.voxel_renderer import ChunkMeshBuilder
        source = inspect.getsource(ChunkMeshBuilder.build)
        ff_pos = source.find("fill_fraction")
        face_loop_pos = source.find("for face_idx")
        assert ff_pos != -1, "fill_fraction not found in build()"
        assert face_loop_pos != -1, "face loop not found in build()"
        assert ff_pos < face_loop_pos, (
            "fill_fraction should be computed before the face loop (per-voxel)"
        )
