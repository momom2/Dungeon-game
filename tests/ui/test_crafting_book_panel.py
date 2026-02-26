"""Tests for CraftingBookPanel: recipe pinning, pin/unpin buttons."""

import pytest


class TestRecipePinning:
    """Pin button is separate from craft mode entry."""

    def test_recipe_click_handler_exists(self):
        """CraftingBookPanel must have _on_recipe_click method."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_on_recipe_click")
        assert callable(getattr(CraftingBookPanel, "_on_recipe_click"))

    def test_pin_toggle_method_exists(self):
        """CraftingBookPanel must have _on_pin_toggle (separate from recipe click)."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_on_pin_toggle")
        assert callable(getattr(CraftingBookPanel, "_on_pin_toggle"))

    def test_recipe_entries_builder_exists(self):
        """CraftingBookPanel must have _create_recipe_entries method."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_create_recipe_entries")

    def test_pinned_overlay_click_handler_exists(self):
        """CraftingBookPanel must have _on_pinned_overlay_click (enters craft mode)."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_on_pinned_overlay_click")
        assert callable(getattr(CraftingBookPanel, "_on_pinned_overlay_click"))

    def test_pinned_unpin_handler_exists(self):
        """CraftingBookPanel must have separate _on_pinned_unpin_click method."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_on_pinned_unpin_click")
        assert callable(getattr(CraftingBookPanel, "_on_pinned_unpin_click"))
