"""Craft cost computation — mana-or-materials dual cost model.

Every placeable object has a total mana cost.  Materials in the player's
inventory offset that cost.  Having the right physical ingredient reduces
the mana required; having nothing means the player pays the full cost in
mana.  Some high-tier ingredients are non-substitutable — no amount of
mana can replace them.

Dependencies: config.economy
Dependents: building.crafting_book, building.crafting_system,
    tests/building/test_craft_cost.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dungeon_builder.config.economy import MANA_SUBSTITUTE_COST


@dataclass(frozen=True)
class RecipeIngredient:
    """A single ingredient required by a recipe.

    Attributes:
        vtype: Canonical voxel type ID required.
        substitutable: Whether mana can replace this ingredient.
            Auto-set to False if *vtype* is absent from
            ``MANA_SUBSTITUTE_COST``.
        mana_value: Mana cost when substituted.  Auto-filled from
            ``MANA_SUBSTITUTE_COST`` if not provided.
        alternatives: Other voxel types that can fill this ingredient
            slot (e.g., copper and gold ingots as alternatives to iron).
            The canonical *vtype* is used for mana cost calculation;
            alternatives are functionally equivalent at craft time.
    """

    vtype: int
    substitutable: bool = True
    mana_value: int = 0
    alternatives: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        # Non-substitutable if the material isn't in the LUT.
        if self.vtype not in MANA_SUBSTITUTE_COST:
            object.__setattr__(self, "substitutable", False)
            return
        # Auto-fill mana_value from LUT when not explicitly provided.
        if self.substitutable and self.mana_value == 0:
            object.__setattr__(
                self, "mana_value", MANA_SUBSTITUTE_COST[self.vtype]
            )

    @property
    def all_accepted(self) -> frozenset[int]:
        """Canonical type plus all alternatives."""
        return frozenset({self.vtype}) | self.alternatives


@dataclass
class CraftCost:
    """Result of a craft cost computation.

    Attributes:
        assembly: Irreducible mana cost (always paid).
        material_mana: Mana required to substitute missing ingredients.
        total: ``assembly + material_mana``.
        materials_consumed: ``{vtype: count}`` of inventory items used.
        missing: Non-substitutable ingredients the player does not have.
        craftable: True when all non-substitutable ingredients are present.
    """

    assembly: int = 0
    material_mana: int = 0
    total: int = 0
    materials_consumed: dict[int, int] = field(default_factory=dict)
    missing: list[RecipeIngredient] = field(default_factory=list)
    craftable: bool = True


def compute_craft_cost(
    ingredients: list[RecipeIngredient],
    assembly_cost: int,
    held_materials: dict[int, int],
) -> CraftCost:
    """Compute the mana cost and material consumption for a craft.

    For each ingredient the player holds, the ingredient's mana value is
    waived and the material is consumed instead.  Non-substitutable
    ingredients that are missing make the craft impossible.

    Args:
        ingredients: Recipe's ingredient list.
        assembly_cost: Irreducible mana cost of the recipe.
        held_materials: Player's current inventory ``{vtype: count}``.

    Returns:
        A :class:`CraftCost` with the full breakdown.
    """
    material_mana = 0
    materials_consumed: dict[int, int] = {}
    missing: list[RecipeIngredient] = []

    # Track remaining inventory so that multiple ingredients of the same
    # type are handled correctly (each consumes one unit).
    remaining = dict(held_materials)

    for ing in ingredients:
        # Check canonical type first, then alternatives.
        matched_vtype = None
        if remaining.get(ing.vtype, 0) > 0:
            matched_vtype = ing.vtype
        else:
            for alt in ing.alternatives:
                if remaining.get(alt, 0) > 0:
                    matched_vtype = alt
                    break

        if matched_vtype is not None:
            # Player has this ingredient — no mana substitution.
            materials_consumed[matched_vtype] = (
                materials_consumed.get(matched_vtype, 0) + 1
            )
            remaining[matched_vtype] -= 1
        elif ing.substitutable:
            material_mana += ing.mana_value
        else:
            missing.append(ing)

    total = assembly_cost + material_mana
    return CraftCost(
        assembly=assembly_cost,
        material_mana=material_mana,
        total=total,
        materials_consumed=materials_consumed,
        missing=missing,
        craftable=len(missing) == 0,
    )
