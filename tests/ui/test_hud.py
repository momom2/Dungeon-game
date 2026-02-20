"""Tests for HUD: inventory panel, hover display, hover highlight events.

Merged from:
- TestInventoryPanel (from test_rendering_fixes.py)
- TestVTypeNames, TestHUDHoverSubscription, TestHoverHandlerLogic (from test_hover_display.py)
- TestHoverEvents (from test_hover_highlight.py)
"""

from __future__ import annotations

import inspect

import pytest

from dungeon_builder.config import (
    VOXEL_DIRT, VOXEL_STONE, VOXEL_BEDROCK, VOXEL_CORE,
    VOXEL_SANDSTONE, VOXEL_LIMESTONE, VOXEL_SHALE, VOXEL_CHALK,
    VOXEL_SLATE, VOXEL_MARBLE, VOXEL_GNEISS,
    VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN,
    VOXEL_IRON_ORE, VOXEL_COPPER_ORE, VOXEL_GOLD_ORE, VOXEL_MANA_CRYSTAL,
    VOXEL_LAVA, VOXEL_WATER,
    VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT, VOXEL_ENCHANTED_METAL,
    VOXEL_REINFORCED_WALL, VOXEL_SPIKE, VOXEL_DOOR, VOXEL_TREASURE,
    VOXEL_ROLLING_STONE, VOXEL_TARP, VOXEL_SLOPE, VOXEL_STAIRS,
)
from dungeon_builder.core.event_bus import EventBus


# ===========================================================================
# Inventory panel (from test_rendering_fixes.py Fix 4)
# ===========================================================================


class TestInventoryPanel:
    """HUD has compact bag button and togglable inventory panel."""

    def test_hud_has_bag_btn_not_hand_label(self):
        """HUD should have bag_btn attribute, not hand_label."""
        from dungeon_builder.ui.hud import HUD
        source = inspect.getsource(HUD.__init__)
        assert "bag_btn" in source
        assert "hand_label" not in source

    def test_hud_has_bag_panel_methods(self):
        """HUD should have _build_bag_panel, _toggle_bag_panel, _refresh_bag_panel."""
        from dungeon_builder.ui.hud import HUD
        assert hasattr(HUD, "_build_bag_panel")
        assert hasattr(HUD, "_toggle_bag_panel")
        assert hasattr(HUD, "_refresh_bag_panel")

    def test_refresh_hand_updates_bag_total(self):
        """_refresh_hand should show total count on bag button."""
        from dungeon_builder.ui.hud import HUD
        source = inspect.getsource(HUD._refresh_hand)
        assert "Bag:" in source
        assert "sum(" in source or "total" in source

    def test_inventory_keybind_registered(self):
        """I key or toggle_inventory should be bound."""
        from dungeon_builder.ui.hud import HUD
        source = inspect.getsource(HUD.__init__)
        assert "toggle_inventory" in source or '"i"' in source


# ===========================================================================
# Hover display: voxel type names (from test_hover_display.py)
# ===========================================================================


class TestVTypeNames:
    """Verify the _VTYPE_NAMES dict covers all voxel types."""

    def test_all_solid_types_have_names(self):
        """Every non-air voxel type should have a friendly name."""
        from dungeon_builder.ui.hud import _VTYPE_NAMES

        expected_types = [
            VOXEL_DIRT, VOXEL_STONE, VOXEL_BEDROCK, VOXEL_CORE,
            VOXEL_SANDSTONE, VOXEL_LIMESTONE, VOXEL_SHALE, VOXEL_CHALK,
            VOXEL_SLATE, VOXEL_MARBLE, VOXEL_GNEISS,
            VOXEL_GRANITE, VOXEL_BASALT, VOXEL_OBSIDIAN,
            VOXEL_IRON_ORE, VOXEL_COPPER_ORE, VOXEL_GOLD_ORE, VOXEL_MANA_CRYSTAL,
            VOXEL_LAVA, VOXEL_WATER,
            VOXEL_IRON_INGOT, VOXEL_COPPER_INGOT, VOXEL_GOLD_INGOT,
            VOXEL_ENCHANTED_METAL,
            VOXEL_REINFORCED_WALL, VOXEL_SPIKE, VOXEL_DOOR, VOXEL_TREASURE,
            VOXEL_ROLLING_STONE, VOXEL_TARP, VOXEL_SLOPE, VOXEL_STAIRS,
        ]
        for vtype in expected_types:
            assert vtype in _VTYPE_NAMES, (
                f"Voxel type {vtype} missing from _VTYPE_NAMES"
            )

    def test_functional_blocks_present(self):
        """All functional block types should have names."""
        from dungeon_builder.ui.hud import _VTYPE_NAMES

        assert _VTYPE_NAMES[VOXEL_SLOPE] == "Slope"
        assert _VTYPE_NAMES[VOXEL_STAIRS] == "Stairs"
        assert _VTYPE_NAMES[VOXEL_DOOR] == "Door"
        assert _VTYPE_NAMES[VOXEL_SPIKE] == "Spike"
        assert _VTYPE_NAMES[VOXEL_TREASURE] == "Treasure"
        assert _VTYPE_NAMES[VOXEL_TARP] == "Tarp"
        assert _VTYPE_NAMES[VOXEL_ROLLING_STONE] == "Rolling Stone"
        assert _VTYPE_NAMES[VOXEL_REINFORCED_WALL] == "Reinforced Wall"

    def test_water_present(self):
        """Water should be in _VTYPE_NAMES."""
        from dungeon_builder.ui.hud import _VTYPE_NAMES
        assert _VTYPE_NAMES[VOXEL_WATER] == "Water"


# ===========================================================================
# HUD hover subscription (from test_hover_display.py)
# ===========================================================================


class TestHUDHoverSubscription:
    """HUD should subscribe to hover events."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        from dungeon_builder.ui.hud import HUD
        self.cls = HUD
        self.init_src = inspect.getsource(HUD.__init__)

    def test_subscribes_to_voxel_hover(self):
        """HUD.__init__ should subscribe to 'voxel_hover'."""
        assert "voxel_hover" in self.init_src

    def test_subscribes_to_voxel_hover_clear(self):
        """HUD.__init__ should subscribe to 'voxel_hover_clear'."""
        assert "voxel_hover_clear" in self.init_src

    def test_hover_handler_exists(self):
        """HUD should have a _on_voxel_hover method."""
        assert hasattr(self.cls, "_on_voxel_hover")

    def test_hover_clear_handler_exists(self):
        """HUD should have a _on_voxel_hover_clear method."""
        assert hasattr(self.cls, "_on_voxel_hover_clear")

    def test_hover_label_created(self):
        """HUD should create a hover_label widget."""
        assert "hover_label" in self.init_src


# ===========================================================================
# Hover handler logic (from test_hover_display.py)
# ===========================================================================


class TestHoverHandlerLogic:
    """Verify hover handler logic via source inspection."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        from dungeon_builder.ui.hud import HUD
        self.hover_src = inspect.getsource(HUD._on_voxel_hover)
        self.clear_src = inspect.getsource(HUD._on_voxel_hover_clear)

    def test_hover_looks_up_vtype(self):
        """Hover handler should look up voxel type from grid."""
        assert "grid.get(" in self.hover_src

    def test_hover_uses_vtype_names(self):
        """Hover handler should use _VTYPE_NAMES dict."""
        assert "_VTYPE_NAMES" in self.hover_src

    def test_hover_updates_label(self):
        """Hover handler should update hover_label text."""
        assert 'hover_label["text"]' in self.hover_src or "hover_label['text']" in self.hover_src

    def test_clear_empties_label(self):
        """Clear handler should set hover_label text to empty."""
        assert 'hover_label["text"]' in self.clear_src or "hover_label['text']" in self.clear_src


# ===========================================================================
# Hover highlight events (from test_hover_highlight.py)
# ===========================================================================


class TestHoverEvents:
    """Test that hover events propagate correctly through the event bus."""

    def test_voxel_hover_event_published(self):
        """voxel_hover event carries x, y, z coordinates."""
        bus = EventBus()
        received = []
        bus.subscribe("voxel_hover", lambda x, y, z: received.append((x, y, z)))

        bus.publish("voxel_hover", x=10, y=20, z=3)
        assert received == [(10, 20, 3)]

    def test_voxel_hover_clear_event_published(self):
        """voxel_hover_clear event fires with no coordinates."""
        bus = EventBus()
        received = []
        bus.subscribe("voxel_hover_clear", lambda **kw: received.append(True))

        bus.publish("voxel_hover_clear")
        assert received == [True]

    def test_hover_then_clear_sequence(self):
        """A hover followed by a clear produces the correct event sequence."""
        bus = EventBus()
        events = []
        bus.subscribe("voxel_hover", lambda x, y, z: events.append(("hover", x, y, z)))
        bus.subscribe("voxel_hover_clear", lambda **kw: events.append(("clear",)))

        bus.publish("voxel_hover", x=5, y=5, z=1)
        bus.publish("voxel_hover_clear")

        assert events == [("hover", 5, 5, 1), ("clear",)]

    def test_hover_changes_voxel(self):
        """Moving hover from one voxel to another publishes two hover events."""
        bus = EventBus()
        received = []
        bus.subscribe("voxel_hover", lambda x, y, z: received.append((x, y, z)))

        bus.publish("voxel_hover", x=1, y=2, z=3)
        bus.publish("voxel_hover", x=4, y=5, z=6)

        assert received == [(1, 2, 3), (4, 5, 6)]


# ===========================================================================
# Hover mode-specific info (vision mode context data)
# ===========================================================================


class TestHoverModeInfo:
    """Verify hover handler includes mode-specific data per render mode."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        from dungeon_builder.ui.hud import HUD
        self.cls = HUD
        self.init_src = inspect.getsource(HUD.__init__)
        self.hover_src = inspect.getsource(HUD._on_voxel_hover)

    def test_hover_handler_reads_temperature(self):
        """Hover handler should read temperature for heat mode."""
        assert "temperature" in self.hover_src

    def test_hover_handler_reads_humidity(self):
        """Hover handler should read humidity for humidity mode."""
        assert "humidity" in self.hover_src

    def test_hover_handler_reads_stress(self):
        """Hover handler should read stress_ratio for structural mode."""
        assert "stress_ratio" in self.hover_src

    def test_render_mode_tracked(self):
        """HUD should subscribe to render_mode_changed event."""
        assert "render_mode_changed" in self.init_src

    def test_render_mode_handler_exists(self):
        """HUD should have _on_render_mode_changed method."""
        assert hasattr(self.cls, "_on_render_mode_changed")

    def test_infused_lava_removed_from_vtype_names(self):
        """Infused Lava (type 92) should NOT be in _VTYPE_NAMES (replaced by mana_crystals)."""
        from dungeon_builder.ui.hud import _VTYPE_NAMES
        assert 92 not in _VTYPE_NAMES
