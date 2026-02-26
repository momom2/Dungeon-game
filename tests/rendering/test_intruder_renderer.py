"""Tests for per-archetype intruder rendering colors and config.

These tests verify the color mapping logic without requiring Panda3D.

Dependencies: config, intruders.archetypes, intruders.agent,
    intruders.personal_map, rendering.intruder_renderer
Dependents: (none)
"""

import pytest

from dungeon_builder.config import (
    ARCHETYPE_COLORS,
    ARCHETYPE_DEFAULT_COLOR,
)
from dungeon_builder.intruders.archetypes import (
    ALL_ARCHETYPES,
    EXPLORER,
    INQUISITOR,
    GLOOMWARDEN,
    MOLE_TAMER,
    EIDOLON,
    ALCHEMIST,
    CARTOMANCER,
    HERO,
    IntruderObjective,
)
from dungeon_builder.intruders.agent import Intruder
from dungeon_builder.intruders.personal_map import PersonalMap
from dungeon_builder.rendering.intruder_renderer import _archetype_color


def _make(arch):
    return Intruder(1, 0, 0, 0, arch, IntruderObjective.DESTROY_CORE, PersonalMap())


# -- Color mapping per archetype --


class TestArchetypeColors:
    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_every_archetype_has_a_color(self, arch):
        """Each archetype must have an entry in ARCHETYPE_COLORS."""
        assert arch.name in ARCHETYPE_COLORS

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_colors_are_valid_rgb(self, arch):
        r, g, b = ARCHETYPE_COLORS[arch.name]
        assert 0.0 <= r <= 1.0
        assert 0.0 <= g <= 1.0
        assert 0.0 <= b <= 1.0

    def test_all_colors_are_distinct(self):
        """No two archetypes should share the same color."""
        colors = list(ARCHETYPE_COLORS.values())
        assert len(colors) == len(set(colors))

    def test_default_color_is_valid_rgb(self):
        r, g, b = ARCHETYPE_DEFAULT_COLOR
        assert 0.0 <= r <= 1.0
        assert 0.0 <= g <= 1.0
        assert 0.0 <= b <= 1.0


# -- _archetype_color helper --


class TestArchetypeColorHelper:
    def test_explorer_gets_forest_green(self):
        color = _archetype_color(_make(EXPLORER))
        assert color == ARCHETYPE_COLORS["Explorer"]

    def test_inquisitor_gets_steel_blue(self):
        color = _archetype_color(_make(INQUISITOR))
        assert color == ARCHETYPE_COLORS["Inquisitor"]

    def test_gloomwarden_gets_pale_gold(self):
        color = _archetype_color(_make(GLOOMWARDEN))
        assert color == ARCHETYPE_COLORS["Gloomwarden"]

    def test_mole_tamer_gets_brown(self):
        color = _archetype_color(_make(MOLE_TAMER))
        assert color == ARCHETYPE_COLORS["Mole Tamer"]

    def test_eidolon_gets_violet(self):
        color = _archetype_color(_make(EIDOLON))
        assert color == ARCHETYPE_COLORS["Eidolon"]

    def test_alchemist_gets_acid_green(self):
        color = _archetype_color(_make(ALCHEMIST))
        assert color == ARCHETYPE_COLORS["Alchemist"]

    def test_cartomancer_gets_deep_blue(self):
        color = _archetype_color(_make(CARTOMANCER))
        assert color == ARCHETYPE_COLORS["Cartomancer"]

    def test_hero_gets_gold(self):
        color = _archetype_color(_make(HERO))
        assert color == ARCHETYPE_COLORS["Hero"]

    @pytest.mark.parametrize("arch", ALL_ARCHETYPES, ids=lambda a: a.name)
    def test_color_matches_config(self, arch):
        """_archetype_color returns the same color as ARCHETYPE_COLORS."""
        color = _archetype_color(_make(arch))
        assert color == ARCHETYPE_COLORS[arch.name]
