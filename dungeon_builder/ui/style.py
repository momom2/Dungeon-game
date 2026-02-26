"""Shared UI style constants for consistent theming across all panels.

Dependencies: (none — pure data module)
Dependents: ui.main_menu, ui.hud, ui.crafting_book_panel,
            ui.render_mode_selector
"""

from __future__ import annotations

# ── Colours ──────────────────────────────────────────────────────────────

BG_COLOR = (0.05, 0.05, 0.1, 0.92)       # Panel/overlay background
BAR_BG = (0, 0, 0, 0.7)                  # Top/bottom bar background
TRANSPARENT = (0, 0, 0, 0)               # Invisible frame background

TITLE_COLOR = (0.9, 0.8, 0.4, 1)         # Panel headers
HIGHLIGHT_COLOR = (0.9, 0.8, 0.4, 1)     # Gold — selection/emphasis
TEXT_COLOR = (0.9, 0.9, 0.9, 1)          # Primary body text
MUTED_COLOR = (0.6, 0.6, 0.6, 1)        # Secondary / less important text
DIM_COLOR = (0.4, 0.4, 0.4, 1)          # Very low emphasis text
ERROR_COLOR = (1.0, 0.3, 0.3, 1)        # Errors, close buttons, core HP
SUCCESS_COLOR = (0.3, 1.0, 0.3, 1)      # Craft success, enabled states
ENABLED_COLOR = (0.3, 1.0, 0.3, 1)       # Green — available/active
DISABLED_COLOR = (0.4, 0.4, 0.4, 1)      # Grey — unavailable/inactive

# ── Button styling ───────────────────────────────────────────────────────

BUTTON_FG = (0.9, 0.9, 0.9, 1)
BUTTON_BG = (0.15, 0.15, 0.2, 0.9)
BUTTON_BG_DIM = (0.15, 0.15, 0.2, 0.8)   # Slightly more transparent variant
BUTTON_SIZE = (-0.3, 0.3, -0.045, 0.055)

# ── Recipe list styling (crafting panel) ─────────────────────────────────

RECIPE_BG = (0.12, 0.12, 0.18, 0.7)      # Inactive recipe row
RECIPE_BG_ENABLED = (0.12, 0.18, 0.12, 0.8)  # Recipe has required material
RECIPE_BG_ACTIVE = (0.25, 0.22, 0.08, 0.9)   # Currently crafting this recipe

# ── Z-ordering ───────────────────────────────────────────────────────────

MENU_SORT_ORDER = 100    # Main menu — above everything
PANEL_SORT_ORDER = 50    # Side panels (crafting book, inventory)
HUD_SORT_ORDER = 10      # HUD elements
