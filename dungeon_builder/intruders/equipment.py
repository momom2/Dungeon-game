"""Equipment and inventory system for intruders.

Every intruder carries a fixed loadout of gear and consumables determined
at spawn time.  Equipment can only be *depleted* during an incursion,
never gained (with rare exceptions).

Any intruder can carry and use any item — archetypes are distinguished
by the *quantity and selection* they bring, not by exclusive access.

Dependencies: config, intruders.archetypes, intruders.reputation, utils.rng
Dependents: intruders.agent, intruders.decision, core.save_system,
    tests/intruders/
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

import dungeon_builder.config as _cfg

if TYPE_CHECKING:
    from dungeon_builder.intruders.archetypes import ArchetypeStats, IntruderStatus
    from dungeon_builder.intruders.reputation import DungeonReputation
    from dungeon_builder.utils.rng import SeededRNG


# ── Enums ─────────────────────────────────────────────────────────────


class ItemCategory(Enum):
    """Broad classification of an item."""

    POTION = auto()     # Consumable, one-shot effect
    SCROLL = auto()     # Single-use spell effect
    TOOL = auto()       # Rope, torch, lockpick — passive or activated
    GEAR = auto()       # Armour, shield, containers — occupies a body slot


class GearSlot(Enum):
    """Body slot for equipping gear items (one item per slot)."""

    LEFT_LEG = auto()
    RIGHT_LEG = auto()
    LEFT_ARM = auto()
    RIGHT_ARM = auto()
    HEAD = auto()
    CHEST = auto()
    BELT = auto()
    BACK = auto()
    LEFT_BOOT = auto()
    RIGHT_BOOT = auto()


class ItemEffect(Enum):
    """What an item does when used or while equipped."""

    HEAL = auto()
    FIRE_IMMUNITY = auto()
    WATER_BREATHING = auto()
    SHIELD = auto()           # Absorb N damage then break
    TELEPORT = auto()         # Two modes: distance or destination
    BRIDGE = auto()           # Create temporary walkable surface
    REVEAL = auto()           # Reveal N-radius area on personal map
    DISPEL = auto()           # Neutralise trap in radius
    ILLUMINATE = auto()       # Provide light (extends perception)
    ROPE = auto()             # Create persistent climbable world object
    SUSTENANCE = auto()       # Replenish food/water
    EXTRA_SLOTS = auto()      # Container: opens additional inventory slots
    DAMAGE_BOOST = auto()     # Passive gear: increase melee damage


class TeleportMode(Enum):
    """How a teleport scroll targets its destination."""

    DISTANCE = auto()     # Offset (dx, dy, dz) from caster position
    DESTINATION = auto()  # Absolute (x, y, z) target coordinate


# ── Item templates (frozen, shared definitions) ───────────────────────


@dataclass(frozen=True)
class ItemTemplate:
    """Immutable definition of an item type.

    ``charges`` is the starting charge count for new instances:
    -1 means infinite / passive (gear that is always "on").

    ``value`` is the effect magnitude (heal amount, shield HP,
    rope length in cells, extra inventory slots, etc.).

    ``slot`` is non-None only for GEAR items that occupy a body slot.
    """

    name: str
    category: ItemCategory
    effect: ItemEffect
    charges: int
    value: int
    duration: int           # Ticks of effect, 0 = instant
    slot: GearSlot | None   # Body slot for GEAR, None for consumables


# ── Pre-defined item templates ────────────────────────────────────────

# Potions
POTION_HEAL = ItemTemplate(
    "Healing Potion", ItemCategory.POTION, ItemEffect.HEAL,
    charges=1, value=_cfg.POTION_HEAL_AMOUNT, duration=0, slot=None,
)
POTION_FIRE_IMMUNITY = ItemTemplate(
    "Fire Resistance Potion", ItemCategory.POTION, ItemEffect.FIRE_IMMUNITY,
    charges=1, value=0, duration=_cfg.POTION_FIRE_DURATION, slot=None,
)
POTION_WATER_BREATHING = ItemTemplate(
    "Water Breathing Potion", ItemCategory.POTION, ItemEffect.WATER_BREATHING,
    charges=1, value=0, duration=_cfg.POTION_WATER_DURATION, slot=None,
)
POTION_SUSTENANCE = ItemTemplate(
    "Sustenance Potion", ItemCategory.POTION, ItemEffect.SUSTENANCE,
    charges=1, value=_cfg.POTION_SUSTENANCE_VALUE, duration=0, slot=None,
)

# Scrolls
SCROLL_TELEPORT = ItemTemplate(
    "Teleport Scroll", ItemCategory.SCROLL, ItemEffect.TELEPORT,
    charges=1, value=_cfg.SCROLL_TELEPORT_MAX_RANGE, duration=0, slot=None,
)
SCROLL_BRIDGE = ItemTemplate(
    "Bridge Scroll", ItemCategory.SCROLL, ItemEffect.BRIDGE,
    charges=1, value=3, duration=_cfg.SCROLL_BRIDGE_DURATION, slot=None,
)
SCROLL_REVEAL = ItemTemplate(
    "Reveal Scroll", ItemCategory.SCROLL, ItemEffect.REVEAL,
    charges=1, value=_cfg.SCROLL_REVEAL_RADIUS, duration=0, slot=None,
)
SCROLL_DISPEL = ItemTemplate(
    "Dispel Scroll", ItemCategory.SCROLL, ItemEffect.DISPEL,
    charges=1, value=_cfg.SCROLL_DISPEL_RADIUS, duration=0, slot=None,
)
SCROLL_SHIELD = ItemTemplate(
    "Shield Scroll", ItemCategory.SCROLL, ItemEffect.SHIELD,
    charges=1, value=_cfg.EQUIPMENT_SHIELD_BASE_HP, duration=0, slot=None,
)

# Tools
TOOL_TORCH = ItemTemplate(
    "Torch", ItemCategory.TOOL, ItemEffect.ILLUMINATE,
    charges=_cfg.TORCH_DURATION, value=_cfg.TORCH_PERCEPTION_BONUS,
    duration=1, slot=None,
)
TOOL_ROPE = ItemTemplate(
    "Rope", ItemCategory.TOOL, ItemEffect.ROPE,
    charges=1, value=_cfg.ROPE_DEFAULT_LENGTH, duration=0, slot=None,
)

# Gear — containers
GEAR_POUCH = ItemTemplate(
    "Pouch", ItemCategory.GEAR, ItemEffect.EXTRA_SLOTS,
    charges=-1, value=_cfg.POUCH_EXTRA_SLOTS, duration=0, slot=GearSlot.BELT,
)
GEAR_BANDOLIER = ItemTemplate(
    "Bandolier", ItemCategory.GEAR, ItemEffect.EXTRA_SLOTS,
    charges=-1, value=_cfg.BANDOLIER_EXTRA_SLOTS, duration=0, slot=GearSlot.CHEST,
)
GEAR_BACKPACK = ItemTemplate(
    "Backpack", ItemCategory.GEAR, ItemEffect.EXTRA_SLOTS,
    charges=-1, value=_cfg.BACKPACK_EXTRA_SLOTS, duration=0, slot=GearSlot.BACK,
)

# Gear — protective
GEAR_LIGHT_SHIELD = ItemTemplate(
    "Light Shield", ItemCategory.GEAR, ItemEffect.SHIELD,
    charges=-1, value=_cfg.EQUIPMENT_SHIELD_BASE_HP, duration=0,
    slot=GearSlot.LEFT_ARM,
)

# All defined templates for iteration / lookup
ALL_ITEM_TEMPLATES: tuple[ItemTemplate, ...] = (
    POTION_HEAL, POTION_FIRE_IMMUNITY, POTION_WATER_BREATHING,
    POTION_SUSTENANCE,
    SCROLL_TELEPORT, SCROLL_BRIDGE, SCROLL_REVEAL, SCROLL_DISPEL,
    SCROLL_SHIELD,
    TOOL_TORCH, TOOL_ROPE,
    GEAR_POUCH, GEAR_BANDOLIER, GEAR_BACKPACK, GEAR_LIGHT_SHIELD,
)

ITEM_TEMPLATE_BY_NAME: dict[str, ItemTemplate] = {
    t.name: t for t in ALL_ITEM_TEMPLATES
}


# ── Mutable item instance ────────────────────────────────────────────


class ItemInstance:
    """A single item carried by an intruder.  Charges deplete during use."""

    __slots__ = ("template", "charges_remaining")

    def __init__(self, template: ItemTemplate) -> None:
        self.template = template
        self.charges_remaining: int = template.charges

    @property
    def depleted(self) -> bool:
        """True when the item has no charges left (and is not infinite)."""
        return self.charges_remaining == 0

    @property
    def infinite(self) -> bool:
        """True for passive gear that never runs out."""
        return self.template.charges == -1

    def use(self) -> bool:
        """Consume one charge.  Returns True if successful, False if depleted."""
        if self.charges_remaining == 0:
            return False
        if self.charges_remaining > 0:  # -1 = infinite
            self.charges_remaining -= 1
        return True

    def __repr__(self) -> str:
        return (
            f"ItemInstance({self.template.name!r}, "
            f"charges={self.charges_remaining}/{self.template.charges})"
        )


# ── Rope combining helper ────────────────────────────────────────────


def combine_ropes(rope_a: ItemInstance, rope_b: ItemInstance) -> ItemInstance:
    """Combine two rope items into one longer rope.

    Combined length = length_a + length_b - ROPE_KNOT_PENALTY.
    The original rope items should be removed from inventory afterward.
    """
    if (rope_a.template.effect != ItemEffect.ROPE
            or rope_b.template.effect != ItemEffect.ROPE):
        raise ValueError("Both items must be ropes")

    combined_length = (
        rope_a.template.value + rope_b.template.value - _cfg.ROPE_KNOT_PENALTY
    )
    combined_length = max(1, combined_length)

    combined_template = ItemTemplate(
        name="Knotted Rope",
        category=ItemCategory.TOOL,
        effect=ItemEffect.ROPE,
        charges=1,
        value=combined_length,
        duration=0,
        slot=None,
    )
    return ItemInstance(combined_template)


# ── Equipment container ──────────────────────────────────────────────


class Equipment:
    """All gear and consumables carried by one intruder.

    ``gear_slots`` holds equipped body-slot gear (one item per slot).
    ``inventory`` holds consumables and tools (capacity-limited).
    """

    __slots__ = ("gear_slots", "inventory", "_base_slots")

    def __init__(self, base_inventory_slots: int) -> None:
        self.gear_slots: dict[GearSlot, ItemInstance] = {}
        self.inventory: list[ItemInstance] = []
        self._base_slots: int = base_inventory_slots

    # ── Capacity ──────────────────────────────────────────────────

    @property
    def inventory_capacity(self) -> int:
        """Total consumable/tool slots = base + EXTRA_SLOTS from containers."""
        extra = sum(
            item.template.value
            for item in self.gear_slots.values()
            if item.template.effect == ItemEffect.EXTRA_SLOTS
        )
        return self._base_slots + extra

    @property
    def inventory_space_remaining(self) -> int:
        return max(0, self.inventory_capacity - len(self.inventory))

    # ── Equipping ─────────────────────────────────────────────────

    def equip(self, item: ItemInstance) -> bool:
        """Equip a gear item to its body slot.  Returns False if slot taken."""
        slot = item.template.slot
        if slot is None:
            return False
        if slot in self.gear_slots:
            return False
        self.gear_slots[slot] = item
        return True

    def add_to_inventory(self, item: ItemInstance) -> bool:
        """Add a consumable/tool to inventory.  Returns False if full."""
        if len(self.inventory) >= self.inventory_capacity:
            return False
        self.inventory.append(item)
        return True

    # ── Queries ───────────────────────────────────────────────────

    def has_effect(self, effect: ItemEffect) -> bool:
        """True if any carried item (gear or inventory) provides this effect
        and has charges remaining."""
        for item in self.gear_slots.values():
            if item.template.effect == effect and not item.depleted:
                return True
        for item in self.inventory:
            if item.template.effect == effect and not item.depleted:
                return True
        return False

    def get_passive_value(self, effect: ItemEffect) -> int:
        """Sum of ``value`` across all equipped gear with the given effect."""
        return sum(
            item.template.value
            for item in self.gear_slots.values()
            if item.template.effect == effect and not item.depleted
        )

    def find_item(self, effect: ItemEffect) -> ItemInstance | None:
        """Return the first non-depleted item with the given effect,
        checking inventory first (consumables), then gear."""
        for item in self.inventory:
            if item.template.effect == effect and not item.depleted:
                return item
        for item in self.gear_slots.values():
            if item.template.effect == effect and not item.depleted:
                return item
        return None

    def use_effect(self, effect: ItemEffect) -> bool:
        """Find and consume one charge of the given effect.  Returns True
        if an item was found and used, False otherwise."""
        item = self.find_item(effect)
        if item is None:
            return False
        return item.use()

    def remove_depleted(self) -> int:
        """Remove all depleted non-infinite items from inventory.
        Returns the number of items removed."""
        before = len(self.inventory)
        self.inventory = [
            item for item in self.inventory
            if not item.depleted or item.infinite
        ]
        return before - len(self.inventory)

    # ── Iteration ─────────────────────────────────────────────────

    def all_items(self) -> list[ItemInstance]:
        """Return a flat list of all carried items (gear + inventory)."""
        return list(self.gear_slots.values()) + list(self.inventory)

    def __repr__(self) -> str:
        gear_names = [f"{s.name}={i.template.name}" for s, i in self.gear_slots.items()]
        inv_names = [i.template.name for i in self.inventory]
        return (
            f"Equipment(gear=[{', '.join(gear_names)}], "
            f"inv=[{', '.join(inv_names)}], "
            f"cap={len(self.inventory)}/{self.inventory_capacity})"
        )


# ── Loadout generation ────────────────────────────────────────────────


def generate_loadout(
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> Equipment:
    """Build the full equipment loadout for one intruder at spawn time.

    Dispatches to archetype-specific loadout logic based on
    ``archetype.base_gear_loadout``.  All archetypes can carry any item;
    the loadout key controls *quantity and selection*.
    """
    equip = Equipment(archetype.base_inventory_slots)

    key = archetype.base_gear_loadout
    builder = _LOADOUT_BUILDERS.get(key, _build_default_loadout)
    builder(equip, archetype, rng, level, status, reputation)

    return equip


# ── Per-archetype loadout builders ────────────────────────────────────
# Each function populates an Equipment instance with appropriate gear
# and consumables for its archetype.  These are internal helpers.


def _build_default_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Fallback loadout: a torch and a healing potion."""
    equip.add_to_inventory(ItemInstance(TOOL_TORCH))
    equip.add_to_inventory(ItemInstance(POTION_HEAL))


def _build_explorer_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Explorers: light gear, torch, rope, maybe a healing potion."""
    equip.add_to_inventory(ItemInstance(TOOL_TORCH))
    equip.add_to_inventory(ItemInstance(TOOL_ROPE))
    if level >= 2 or rng.random() < 0.5:
        equip.add_to_inventory(ItemInstance(POTION_HEAL))


def _build_inquisitor_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Inquisitors: shield gear, healing potions, shield scrolls at rank."""
    from dungeon_builder.intruders.archetypes import IntruderStatus as _IS

    equip.equip(ItemInstance(GEAR_LIGHT_SHIELD))
    equip.add_to_inventory(ItemInstance(POTION_HEAL))
    if level >= 2:
        equip.add_to_inventory(ItemInstance(POTION_HEAL))
    if status.value >= _IS.VETERAN.value:
        equip.add_to_inventory(ItemInstance(SCROLL_SHIELD))
    if status.value >= _IS.ELITE.value:
        equip.equip(ItemInstance(GEAR_POUCH))
        equip.add_to_inventory(ItemInstance(POTION_HEAL))


def _build_gloomwarden_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Gloomwardens: torch (always), healing potion, sustenance at rank."""
    from dungeon_builder.intruders.archetypes import IntruderStatus as _IS

    equip.add_to_inventory(ItemInstance(TOOL_TORCH))
    equip.add_to_inventory(ItemInstance(POTION_HEAL))
    if status.value >= _IS.VETERAN.value:
        equip.add_to_inventory(ItemInstance(POTION_SUSTENANCE))


def _build_mole_tamer_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Mole Tamers: light gear, healing potion, rope."""
    equip.add_to_inventory(ItemInstance(POTION_HEAL))
    if rng.random() < 0.5:
        equip.add_to_inventory(ItemInstance(TOOL_ROPE))


def _build_eidolon_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Eidolons: carry nothing.  Supernatural beings need no equipment."""
    pass


def _build_alchemist_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Alchemists: reputation-driven counter-potions.

    Check the dungeon's dominant threat and brew appropriate counters.
    Always bring a bandolier for extra capacity.
    """
    equip.equip(ItemInstance(GEAR_BANDOLIER))

    # Determine counter-potions based on reputation
    potion_count = _cfg.ALCHEMIST_POTION_SLOTS + max(0, level - 1)
    dominant_threat = ""
    if reputation is not None:
        dominant_threat = reputation.get_dominant_threat()

    for _ in range(potion_count):
        if dominant_threat == "water":
            equip.add_to_inventory(ItemInstance(POTION_WATER_BREATHING))
        elif dominant_threat == "fire":
            equip.add_to_inventory(ItemInstance(POTION_FIRE_IMMUNITY))
        elif dominant_threat == "trap":
            equip.add_to_inventory(ItemInstance(POTION_HEAL))
        else:
            # Unknown or mixed threats: bring healing
            equip.add_to_inventory(ItemInstance(POTION_HEAL))


def _build_cartomancer_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Cartomancers: pre-prepared spell scrolls.

    Scroll count scales with status rank.  Selection influenced by
    reputation (what the dungeon is known for).
    """
    from dungeon_builder.intruders.archetypes import IntruderStatus as _IS

    equip.equip(ItemInstance(GEAR_BACKPACK))

    status_rank = max(0, status.value - _IS.GRUNT.value)
    scroll_count = (
        _cfg.CARTOMANCER_BASE_SCROLLS
        + status_rank * _cfg.CARTOMANCER_STATUS_BONUS_SCROLLS
    )

    # Build a weighted scroll pool based on reputation
    scroll_pool: list[ItemTemplate] = [
        SCROLL_REVEAL, SCROLL_DISPEL, SCROLL_BRIDGE,
        SCROLL_TELEPORT, SCROLL_SHIELD,
    ]

    for _ in range(scroll_count):
        idx = rng.randint(0, len(scroll_pool) - 1)
        equip.add_to_inventory(ItemInstance(scroll_pool[idx]))


def _build_hero_loadout(
    equip: Equipment,
    archetype: ArchetypeStats,
    rng: SeededRNG,
    level: int,
    status: IntruderStatus,
    reputation: DungeonReputation | None,
) -> None:
    """Heroes: minimal equipment — they rely on brute force and luck."""
    equip.add_to_inventory(ItemInstance(POTION_HEAL))
    equip.add_to_inventory(ItemInstance(POTION_HEAL))


# Dispatch table: base_gear_loadout string → builder function
_LOADOUT_BUILDERS: dict[str, type[None]] = {
    "explorer": _build_explorer_loadout,
    "inquisitor": _build_inquisitor_loadout,
    "gloomwarden": _build_gloomwarden_loadout,
    "mole_tamer": _build_mole_tamer_loadout,
    "eidolon": _build_eidolon_loadout,
    "alchemist": _build_alchemist_loadout,
    "cartomancer": _build_cartomancer_loadout,
    "hero": _build_hero_loadout,
}
