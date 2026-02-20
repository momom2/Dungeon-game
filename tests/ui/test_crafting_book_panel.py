"""Tests for CraftingBookPanel: recipe pinning, pin/unpin buttons."""

import inspect

import pytest


class TestRecipePinning:
    """Pin button is separate from craft mode entry."""

    def test_recipe_click_does_not_toggle_pin(self):
        """_on_recipe_click should NOT toggle _pinned_recipe."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        source = inspect.getsource(CraftingBookPanel._on_recipe_click)
        assert "_pinned_recipe" not in source

    def test_pin_toggle_method_exists(self):
        """CraftingBookPanel should have _on_pin_toggle method."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_on_pin_toggle")

    def test_pin_toggle_toggles_pinned_recipe(self):
        """_on_pin_toggle source should toggle _pinned_recipe."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        source = inspect.getsource(CraftingBookPanel._on_pin_toggle)
        assert "_pinned_recipe" in source
        # Should toggle: set to None if same, else set to recipe_name
        assert "None" in source

    def test_recipe_widgets_have_pin_button(self):
        """_create_recipe_entries should create 4-tuple widgets with pin_btn."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        source = inspect.getsource(CraftingBookPanel._create_recipe_entries)
        # Pin button created with _on_pin_toggle command
        assert "_on_pin_toggle" in source

    def test_pinned_overlay_click_enters_craft_mode(self):
        """Clicking pinned overlay should enter craft mode (not unpin)."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        source = inspect.getsource(CraftingBookPanel._on_pinned_overlay_click)
        assert "craft_recipe_selected" in source
        # Should NOT set _pinned_recipe = None
        assert "_pinned_recipe = None" not in source

    def test_pinned_unpin_button_exists(self):
        """Overlay should have separate unpin button."""
        from dungeon_builder.ui.crafting_book_panel import CraftingBookPanel
        assert hasattr(CraftingBookPanel, "_on_pinned_unpin_click")
        source = inspect.getsource(CraftingBookPanel._on_pinned_unpin_click)
        assert "_pinned_recipe = None" in source
