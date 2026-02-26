# GRAPHICS.md — Art & Asset Conventions for Dungeon Builder

> **Audience:** Artists and asset creators working on the game.
> **Last updated:** 2026-02-26

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Visual Style Direction](#2-visual-style-direction)
3. [Current Rendering System](#3-current-rendering-system)
4. [Asset Categories](#4-asset-categories)
   - 4a. Voxel Face Textures
   - 4b. UI Icons & Sprites
   - 4c. Intruder Character Art
   - 4d. Menu Art & Logo
   - 4e. Particle & Effect Textures
5. [File Formats & Technical Requirements](#5-file-formats--technical-requirements)
6. [Directory Structure](#6-directory-structure)
7. [Naming Conventions](#7-naming-conventions)
8. [Color Palette Reference](#8-color-palette-reference)
9. [Material & Block Reference](#9-material--block-reference)
10. [Intruder Archetype Reference](#10-intruder-archetype-reference)
11. [Render Modes & Overlays](#11-render-modes--overlays)
12. [Integration Notes for Programmers](#12-integration-notes-for-programmers)

---

## 1. Project Overview

Dungeon Builder is a dungeon defense sandbox where the player builds
underground dungeons with physics-based traps to defend a magical core from
AI-driven intruder parties. The world is a 3D voxel grid (64x64x32 default)
viewed from a free-orbiting RTS-style camera pitched downward at ~45 degrees.

**Engine:** Panda3D 1.10.14+ (Python)
**Current visuals:** 100% procedural — flat-colored voxel cubes, text-only
UI, colored cubes for intruders. Zero external art assets exist today.

The game is designed to be **moddable**: block types, recipes, and intruder
archetypes are all data-driven. Art assets should follow the same principle —
adding a new block type's texture should require dropping a file into the
right folder and adding one line to a config, not modifying renderer code.

---

## 2. Visual Style Direction

**Target style: Pixel art / retro.**

Think early Minecraft resource packs, Dwarf Fortress tilesets, or Ultima
Underworld. The voxel grid and top-down-ish perspective lend themselves
naturally to chunky, readable pixel art.

### Style Guidelines

- **Readability at distance.** The camera sits 15–60 units from the focus
  point. At max zoom-out, a single voxel face is ~20 screen pixels across.
  Textures must read clearly at that scale — avoid tiny details that
  collapse into noise.
- **High contrast between block types.** The player needs to instantly
  distinguish stone from limestone from marble from bedrock at a glance.
  Silhouette and pattern matter more than color alone.
- **Consistent lighting direction.** The game has a directional light at
  heading 45 degrees, pitch -60 degrees (upper-left-front). Baked
  highlights/shadows in textures should be subtle or absent — the engine
  applies per-face shading (see Section 3).
- **Muted natural palette, vivid accents.** Terrain should feel earthy and
  grounded. Ores, crafted items, and magical blocks can be more saturated
  to draw the eye.
- **Tile seamlessly.** Voxel face textures tile on all four edges since
  adjacent blocks of the same type share boundaries.
- **Deception must be visual.** Some blocks are designed to trick intruders
  (fragile floor looks like stone, treasure bait looks like treasure). The
  textures for these must be deliberately similar to what they mimic.

---

## 3. Current Rendering System

Understanding the rendering pipeline helps create assets that integrate
cleanly. Here's how voxels currently get from config to screen.

### 3a. Geometry

Each voxel is a 1x1x1 axis-aligned cube. Only **exposed faces** (adjacent
to air, water, or lava) are rendered — interior faces are culled. Bottom
faces are always skipped (camera never sees them). This means each block
has at most 5 rendered faces.

Fluids (water, lava) render as **partial-height cubes** — the top face
lowers proportional to the fluid level (0–255 maps to 0.0–1.0 height).

Geometry is built in **16x16x1 chunks** (horizontal slabs at each z-level)
using Panda3D GeomNode. Chunks rebuild lazily when voxels change.

### 3b. Vertex Format

Currently: `v3n3c4` (position + normal + RGBA color). Adding texture
support will require switching to `v3n3t2c4` (adding UV coordinates) or
a shader-based approach. See Section 12 for integration notes.

### 3c. Face Shading

Each face direction has a fixed brightness multiplier simulating directional
light:

| Face    | Shade | Notes                         |
|---------|-------|-------------------------------|
| Top     | 1.00  | Brightest (toward surface)    |
| North   | 0.90  | (+Y direction)                |
| East    | 0.80  | (+X direction)                |
| West    | 0.70  | (-X direction)                |
| South   | 0.60  | (-Y direction, darkest)       |
| Bottom  | 0.50  | Never rendered                |

This multiplier is applied to **vertex colors** after the base color. When
textures are introduced, this shading should still apply (either as vertex
color modulation or via a simple shader).

### 3d. Vertex Noise

Per-vertex color noise is currently used to simulate surface texture. Each
material has a noise amplitude (0.03 for polished obsidian up to 0.12 for
rough granite). When face textures are added, this noise system can be
reduced or removed for textured blocks, since the texture itself provides
visual variation.

### 3e. Render Modes

The game has 5 render modes. Textures will primarily appear in **Matter
mode** (the default). The other modes override or tint colors:

| Mode         | Effect on block visuals                          |
|--------------|--------------------------------------------------|
| Matter       | Default view — block textures visible            |
| Humidity     | Tints all blocks toward blue based on moisture   |
| Heat         | Replaces colors with blue-white-red gradient     |
| Structural   | Replaces colors with green-yellow-red gradient   |
| Prospecting  | Desaturates to grayscale, adds ore glow markers  |

**Implication:** In Heat, Structural, and Prospecting modes, textures will
likely be replaced by solid-color gradients (the texture detail would be
lost anyway). In Humidity mode, textures could show through with a blue
overlay tint. The programmer will handle these mode transitions.

### 3f. Layer Transparency

The game uses Z-level slicing. Layers above the camera focus are rendered
very transparent (ghostly ceiling), layers below fade out with depth. All
objects at a given z-level inherit alpha from their layer node. This is
automatic and doesn't affect asset creation.

---

## 4. Asset Categories

### 4a. Voxel Face Textures

**What:** Tileable square textures for each block type's face. A block can
have **up to 3 distinct face textures**: top, side, and (optionally)
bottom (currently unused but worth future-proofing).

**Resolution options:**
- **16x16 pixels** — Classic pixel art. Very forgiving, fast iteration.
  Ideal at the game's typical zoom level where a voxel face is ~20px on
  screen.
- **32x32 pixels** — More detail per block while staying retro. Better
  readability at close zoom. Slightly heavier on texture memory.

Choose whichever resolution reads best at the game's camera distances
(15–60 units from focus). Both are valid. All textures for a given block
should use the same resolution. Mixing 16x16 and 32x32 within one
block is fine (e.g., 16x16 for a simple top, 32x32 for a detailed side).

**Tiling:** All face textures must tile seamlessly on all 4 edges. Adjacent
blocks of the same type sit flush — seams will be visible if tiling breaks.

**Color space:** sRGB, 8-bit per channel. Use PNG with transparency where
needed (fluids, doors, bars). Fully opaque blocks should have alpha = 255
everywhere.

**Palette discipline:** Start from the existing base colors (Section 8) and
build texture detail around them. The average color of a texture should
approximately match the current flat color so the game looks consistent
during the transition from procedural to textured rendering.

#### What to Create — Priority Order

**Tier 1 (Core terrain — create first):**
- Stone (most common block, the "default" texture)
- Dirt
- Bedrock
- Air/void (probably not needed — air is empty space)

**Tier 2 (Rock varieties — geological character):**
- Sandstone, Limestone, Shale, Chalk
- Slate, Marble, Gneiss
- Granite, Basalt, Obsidian

**Tier 3 (Ores — must be visually distinct from host rock):**
- Iron Ore (rusty speckles in stone)
- Copper Ore (green-blue veins in stone)
- Gold Ore (bright flecks in stone)
- Mana Crystal (purple crystalline, magical feel)

**Tier 4 (Fluids — semi-transparent, animated potential):**
- Water (blue, alpha varies with level)
- Lava (orange-red, emissive feel)
- Water Source / Water Sink (distinct from regular water)
- Lava Source / Lava Sink

**Tier 5 (Crafted metals):**
- Iron Ingot, Copper Ingot, Gold Ingot
- Enchanted Metal (purple shimmer variant)

**Tier 6 (Functional/trap blocks):**
- Reinforced Wall, Spike, Door (open/closed variants)
- Treasure, Rolling Stone, Tarp
- Slope, Stairs
- Pressure Plate, Floodgate, Alarm Bell
- Iron Bars, Pipe, Pump, Steam Vent
- Fragile Floor (**must look like Stone** — it's a trap!)
- Treasure Bait (**must look like Treasure** — also a trap!)

### 4b. UI Icons & Sprites

**What:** Small icons for blocks/materials in the inventory panel, crafting
book, and HUD. Currently these are text-only ("Iron Ore x3").

**Resolution:** 32x32 or 48x48 pixels recommended. Must be legible at
~24px display size (they'll appear in tight list layouts).

**Background:** Transparent PNG. Icons float over dark panel backgrounds
(~`rgb(13, 13, 26)` at 92% opacity).

**Style:** Isometric or flat top-down representation of the block.
Consistent perspective across all icons. A slight dark outline (1–2px)
helps readability against the dark UI.

#### What to Create

- **One icon per block type** (same types as the voxel texture list above,
  ~45 total). These represent the block in inventory and crafting lists.
- **Tool icons** (2): Dig tool, Move/pickup tool
- **Status icons**: Core HP heart/gem, speed indicators (pause/play/fast),
  intruder skull/figure
- **Crafting icons**: Pin marker, recipe discovered/undiscovered indicators
- **Render mode icons** (5): One per render mode for the mode selector
  dropdown (Matter, Humidity, Heat, Structural, Prospecting)

### 4c. Intruder Character Art

**What:** Visual representations of the 8+ intruder archetypes (currently
rendered as solid-colored 0.6-unit cubes). See Section 10 for the full
archetype list with colors and personality descriptions.

**Three viable approaches** — create prototypes and we'll decide:

#### Option A: Billboarded Sprites
2D sprite sheets that always face the camera (classic Doom/early-RTS
style). Each archetype gets a sprite sheet with directional frames.

- **Sheet layout:** 4 or 8 directions x animation frames (idle, walk,
  attack, die)
- **Sprite size:** 32x32 or 48x48 pixels per frame
- **Must include:** Idle (1 frame min), Walk cycle (4 frames min)
- **Nice to have:** Attack, hurt, death, special ability animations

#### Option B: Voxel Models
Small voxel characters built in MagicaVoxel or similar. Exported as `.vox`
or converted to mesh. Fits the world aesthetic perfectly.

- **Scale:** ~8x8x16 voxels (body proportions, not 1:1 with world voxels)
- **Must include:** Static pose minimum, T-pose for rigging potential
- **File format:** `.vox` (MagicaVoxel) or `.obj` + texture

#### Option C: Low-Poly 3D Models
Simple polygonal models with pixel-art textures. Most flexible for
animation but requires 3D modeling skills.

- **Tri budget:** ~200–500 triangles per model
- **Texture:** Single 64x64 or 128x128 atlas per archetype
- **Format:** `.gltf` / `.glb` preferred (Panda3D has good support), or
  `.obj` + `.png` texture

#### Archetype Visual Identity

Each archetype should have a **silhouette** distinct enough to identify at
distance. Color alone isn't sufficient — the shapes/outfits should differ:

| Archetype    | Personality                     | Visual Direction               |
|--------------|----------------------------------|--------------------------------|
| Explorer     | Stealthy scout, treasure hunter | Hooded cloak, lockpicks, light |
| Inquisitor   | Armored crusader, siege leader  | Heavy plate, shield, hammer    |
| Gloomwarden  | Torch-bearing ranger, support   | Lantern/torch, light armor     |
| Mole Tamer   | Beast handler, tunnel specialist| Earthy robes, mole companions  |
| Eidolon      | Supernatural, phases through walls | Violet ethereal glow, floating |
| Alchemist    | Chemical brewer, potion expert  | Goggles, bandolier of bottles  |
| Cartomancer  | Scroll mage, teleporter        | Deep-blue robes, scroll case   |
| Hero         | Legendary champion, unstoppable | Gold armor, dramatic presence  |

Underworld variants (Magmawraith, Crystalweaver, etc.) should look darker
and more alien — subterranean creatures rather than surface adventurers.

### 4d. Menu Art & Logo

**What:** Title screen art, game logo, menu background.

- **Game logo:** "DUNGEON BUILDER" — pixel art logotype. Currently rendered
  as plain gold text at 0.1 scale. Needs a proper logo.
  - Provide at **2 sizes**: large (for title screen, ~512px wide) and small
    (for corner HUD branding, ~128px wide)
- **Title screen background:** Atmospheric dungeon scene, displayed behind
  the main menu buttons. Keep it dark (buttons overlay on top with
  `rgba(5, 5, 10, 92%)` panel backgrounds).
- **Menu panel decorations:** Optional border/frame art for the settings
  panels. Current panels are plain dark rectangles.

### 4e. Particle & Effect Textures

**What:** Small textures for future particle systems (not yet implemented
but planned).

- **Dust/debris:** For block breaking and collapse (2–4 frames, 8x8)
- **Water splash:** For fluid interaction (4 frames, 16x16)
- **Fire/smoke:** For lava and Pyremancer effects (4–8 frames, 16x16)
- **Magic sparkle:** For mana crystals and enchantment (4 frames, 8x8)
- **Glow orbs:** For ore prospecting mode highlights (single frame, 16x16,
  in 4 colors: iron rust, copper green, gold yellow, mana purple)

**Format:** PNG sprite strips (horizontal layout, equal frame sizes).

---

## 5. File Formats & Technical Requirements

### Accepted Formats

| Asset Type        | Format      | Notes                                  |
|-------------------|-------------|----------------------------------------|
| Textures/sprites  | `.png`      | 8-bit sRGB, transparency via alpha     |
| Sprite sheets     | `.png`      | Horizontal strip, equal frame widths   |
| Voxel models      | `.vox`      | MagicaVoxel native                     |
| 3D models         | `.gltf`     | Preferred; `.glb` or `.obj` also OK    |
| Texture atlases   | `.png`      | Power-of-two dimensions recommended    |

### Technical Constraints

- **Power-of-two textures** are recommended for GPU efficiency but not
  strictly required by Panda3D.
- **No JPEG** — lossy compression creates artifacts on pixel art.
- **Premultiplied alpha:** Not required. Use straight alpha.
- **Color profile:** sRGB. Do not embed ICC profiles.
- **Max texture size:** 2048x2048 for atlases. Individual block faces
  should be 16x16 or 32x32.
- **No spaces in filenames.** Use underscores.

---

## 6. Directory Structure

All art assets live under a top-level `assets/` directory:

```
assets/
  textures/
    blocks/                  # Voxel face textures
      stone_top.png
      stone_side.png
      dirt_top.png
      dirt_side.png
      iron_ore_side.png
      water.png              # Fluids only need one (no top/side distinction)
      ...
    ui/                      # UI icons and interface art
      icons/                 # Block/item icons for inventory & crafting
        stone.png
        iron_ore.png
        spike.png
        ...
      tools/                 # Tool icons
        dig.png
        move.png
      status/                # Status indicator icons
        core_hp.png
        speed_pause.png
        speed_play.png
        speed_fast.png
        intruder.png
      modes/                 # Render mode selector icons
        matter.png
        humidity.png
        heat.png
        structural.png
        prospecting.png
    effects/                 # Particle & effect textures
      dust.png               # Sprite strip
      splash.png
      fire.png
      sparkle.png
      glow_iron.png
      glow_copper.png
      glow_gold.png
      glow_mana.png
    menu/                    # Title screen & menu art
      logo_large.png
      logo_small.png
      title_bg.png
      panel_border.png       # Optional decorative frame
  models/                    # 3D models (if applicable)
    intruders/
      vanguard.gltf          # Or .vox
      shadowblade.gltf
      ...
  sprites/                   # 2D sprite sheets (if applicable)
    intruders/
      vanguard.png           # Sprite strip: directions x frames
      vanguard.json          # Frame metadata (size, count, fps)
      shadowblade.png
      shadowblade.json
      ...
```

---

## 7. Naming Conventions

### General Rules

- **All lowercase**, underscores for word separation: `iron_ore_side.png`
- **No spaces, no hyphens, no special characters**
- **Block textures:** `{block_name}_{face}.png`
  - Faces: `top`, `side`, `bottom`
  - If all faces are the same: just `{block_name}.png`
- **UI icons:** `{item_name}.png`
- **Sprite sheets:** `{archetype_name}.png` + `{archetype_name}.json`
- **Particle strips:** `{effect_name}.png`

### Block Name Mapping

Use these exact names (matching the code's internal identifiers):

| Block              | Filename prefix      | Notes                         |
|--------------------|----------------------|-------------------------------|
| Dirt               | `dirt`               |                               |
| Stone              | `stone`              |                               |
| Bedrock            | `bedrock`            |                               |
| Dungeon Core       | `core`               | Glowing red, magical          |
| Sandstone          | `sandstone`          |                               |
| Limestone          | `limestone`          |                               |
| Shale              | `shale`              | Layered, fissile              |
| Chalk              | `chalk`              | Soft white                    |
| Slate              | `slate`              | Dark, flat planes             |
| Marble             | `marble`             | White with veins              |
| Gneiss             | `gneiss`             | Banded metamorphic            |
| Granite            | `granite`            | Speckled crystalline          |
| Basalt             | `basalt`             | Dark fine-grained             |
| Obsidian           | `obsidian`           | Glossy black                  |
| Iron Ore           | `iron_ore`           | Rusty flecks in stone         |
| Copper Ore         | `copper_ore`         | Green-blue veins in stone     |
| Gold Ore           | `gold_ore`           | Bright flecks in stone        |
| Mana Crystal       | `mana_crystal`       | Purple crystalline, glowing   |
| Water              | `water`              | Semi-transparent blue         |
| Lava               | `lava`               | Orange-red, emissive look     |
| Water Source        | `water_source`       |                               |
| Water Sink          | `water_sink`         |                               |
| Lava Source         | `lava_source`        |                               |
| Lava Sink           | `lava_sink`          |                               |
| Iron Ingot          | `iron_ingot`         | Refined metal block           |
| Copper Ingot        | `copper_ingot`       |                               |
| Gold Ingot          | `gold_ingot`         |                               |
| Enchanted Metal     | `enchanted_metal`    | Purple shimmer                |
| Reinforced Wall     | `reinforced_wall`    | Steel-plated stone            |
| Spike               | `spike`              | Dark metallic points          |
| Door                | `door`               | Need open + closed variants   |
| Treasure            | `treasure`           | Gold coins/gems               |
| Rolling Stone       | `rolling_stone`      | Heavy boulder                 |
| Tarp                | `tarp`               | Fabric/canvas                 |
| Slope               | `slope`              | Angled surface                |
| Stairs              | `stairs`             | Step pattern                  |
| Fragile Floor       | `fragile_floor`      | **Must look like `stone`!**   |
| Treasure Bait       | `treasure_bait`      | **Must look like `treasure`!**|
| Pressure Plate      | `pressure_plate`     | Recessed tile                 |
| Floodgate           | `floodgate`          | Need open + closed variants   |
| Alarm Bell          | `alarm_bell`         | Bell shape                    |
| Iron Bars           | `iron_bars`          | Semi-transparent grid         |
| Pipe                | `pipe`               | Cylindrical conduit           |
| Pump                | `pump`               | Mechanical device             |
| Steam Vent          | `steam_vent`         | Grate with steam              |

---

## 8. Color Palette Reference

These are the current procedural colors for every block type. New textures
should use these as their **average/dominant color** to maintain visual
consistency. The hex values are approximate — see the RGBA floats for
precision.

### Natural Terrain

| Block        | RGBA Float                  | Approx Hex | Visual         |
|--------------|-----------------------------|------------|----------------|
| Dirt         | (0.55, 0.35, 0.17, 1.0)    | `#8C592B`  | Earthy brown   |
| Stone        | (0.50, 0.50, 0.50, 1.0)    | `#808080`  | Neutral gray   |
| Bedrock      | (0.20, 0.20, 0.20, 1.0)    | `#333333`  | Very dark gray |
| Core         | (0.80, 0.10, 0.10, 1.0)    | `#CC1A1A`  | Bright red     |

### Rock Types

| Block        | RGBA Float                  | Approx Hex | Visual           |
|--------------|-----------------------------|------------|------------------|
| Sandstone    | (0.85, 0.75, 0.50, 1.0)    | `#D9BF80`  | Sandy yellow     |
| Limestone    | (0.80, 0.80, 0.72, 1.0)    | `#CCCCB8`  | Pale cream       |
| Shale        | (0.35, 0.32, 0.30, 1.0)    | `#59524D`  | Dark slate-brown |
| Chalk        | (0.92, 0.90, 0.85, 1.0)    | `#EBE6D9`  | Near-white cream |
| Slate        | (0.30, 0.32, 0.35, 1.0)    | `#4D5259`  | Blue-gray dark   |
| Marble       | (0.90, 0.88, 0.85, 1.0)    | `#E6E0D9`  | Near-white       |
| Gneiss       | (0.45, 0.42, 0.38, 1.0)    | `#736B61`  | Banded gray      |
| Granite      | (0.62, 0.58, 0.55, 1.0)    | `#9E948C`  | Speckled gray    |
| Basalt       | (0.25, 0.24, 0.26, 1.0)    | `#403D42`  | Very dark        |
| Obsidian     | (0.10, 0.08, 0.12, 1.0)    | `#1A141F`  | Near-black       |

### Ores

| Block        | RGBA Float                  | Approx Hex | Visual           |
|--------------|-----------------------------|------------|------------------|
| Iron Ore     | (0.60, 0.35, 0.25, 1.0)    | `#995940`  | Rusty orange     |
| Copper Ore   | (0.45, 0.65, 0.50, 1.0)    | `#73A680`  | Green-copper     |
| Gold Ore     | (0.85, 0.75, 0.20, 1.0)    | `#D9BF33`  | Bright gold      |
| Mana Crystal | (0.55, 0.30, 0.85, 1.0)    | `#8C4DD9`  | Purple           |

### Fluids

| Block        | RGBA Float                  | Approx Hex | Visual           |
|--------------|-----------------------------|------------|------------------|
| Water        | (0.15, 0.40, 0.85, 0.70)   | `#2666D9`  | Semi-trans blue  |
| Lava         | (1.00, 0.30, 0.00, 1.00)   | `#FF4D00`  | Bright orange    |

### Crafted Metals

| Block            | RGBA Float                  | Approx Hex | Visual       |
|------------------|-----------------------------|------------|--------------|
| Iron Ingot       | (0.70, 0.55, 0.50, 1.0)    | `#B38C80`  | Dull gray    |
| Copper Ingot     | (0.75, 0.50, 0.30, 1.0)    | `#BF804D`  | Warm copper  |
| Gold Ingot       | (0.95, 0.85, 0.30, 1.0)    | `#F2D94D`  | Shiny gold   |
| Enchanted Metal  | (0.60, 0.20, 0.90, 1.0)    | `#9933E6`  | Purple magic |

### Functional Blocks

| Block            | RGBA Float                  | Approx Hex | Visual          |
|------------------|-----------------------------|------------|-----------------|
| Reinforced Wall  | (0.50, 0.52, 0.55, 1.0)    | `#80858C`  | Steel gray      |
| Spike            | (0.35, 0.30, 0.28, 1.0)    | `#594D47`  | Dark metallic   |
| Door             | (0.45, 0.35, 0.25, 1.0)    | `#735940`  | Wood/metal      |
| Treasure         | (0.95, 0.85, 0.20, 1.0)    | `#F2D933`  | Bright gold     |
| Rolling Stone    | (0.55, 0.50, 0.45, 1.0)    | `#8C8073`  | Boulder gray    |
| Tarp             | (0.40, 0.35, 0.25, 1.0)    | `#665940`  | Canvas brown    |
| Slope            | (0.50, 0.50, 0.50, 1.0)    | `#808080`  | Stone-matched   |
| Stairs           | (0.50, 0.50, 0.50, 1.0)    | `#808080`  | Stone-matched   |
| Pressure Plate   | (0.42, 0.42, 0.44, 1.0)    | `#6B6B70`  | Metal tile      |
| Floodgate        | (0.42, 0.42, 0.50, 1.0)    | `#6B6B80`  | Blue-steel      |
| Alarm Bell       | (0.80, 0.70, 0.20, 1.0)    | `#CCB333`  | Brass            |
| Iron Bars        | (0.45, 0.45, 0.50, 0.70)   | `#737380`  | Semi-transparent |
| Pipe             | (0.50, 0.50, 0.55, 1.0)    | `#80808C`  | Conduit gray    |
| Pump             | (0.55, 0.45, 0.35, 1.0)    | `#8C7359`  | Mechanical      |
| Steam Vent       | (0.50, 0.50, 0.52, 0.80)   | `#808085`  | Semi-transparent |
| Fragile Floor    | (0.50, 0.50, 0.50, 1.0)    | `#808080`  | **= Stone!**    |
| Treasure Bait    | (0.95, 0.85, 0.20, 1.0)    | `#F2D933`  | **= Treasure!** |

### Metal Tinting Colors

When a block is made from a specific metal (iron, copper, gold), its base
color is lerped 40% toward the metal tint:

| Metal  | Tint RGB                | Effect                        |
|--------|-------------------------|-------------------------------|
| None   | (0.50, 0.50, 0.50)     | Neutral (no tint)             |
| Iron   | (0.55, 0.55, 0.60)     | Slightly bluish steel         |
| Copper | (0.72, 0.52, 0.35)     | Warm copper tone              |
| Gold   | (0.95, 0.85, 0.20)     | Bright gold                   |

Enchanted blocks additionally blend 15% toward purple (0.6, 0.2, 0.9).

### UI Colors

| Purpose      | RGBA Float                  | Approx Hex | Usage              |
|--------------|-----------------------------|------------|--------------------|
| Panel BG     | (0.05, 0.05, 0.10, 0.92)   | `#0D0D1A`  | All panel overlays |
| Bar BG       | (0.00, 0.00, 0.00, 0.70)   | `#000000`  | Top/bottom bars    |
| Title/Gold   | (0.90, 0.80, 0.40, 1.00)   | `#E6CC66`  | Headers, emphasis  |
| Body Text    | (0.90, 0.90, 0.90, 1.00)   | `#E6E6E6`  | Primary text       |
| Muted        | (0.60, 0.60, 0.60, 1.00)   | `#999999`  | Secondary text     |
| Error/Red    | (1.00, 0.30, 0.30, 1.00)   | `#FF4D4D`  | Errors, danger     |
| Success/Grn  | (0.30, 1.00, 0.30, 1.00)   | `#4DFF4D`  | Enabled, success   |
| Button BG    | (0.15, 0.15, 0.20, 0.90)   | `#262633`  | Button fills       |

---

## 9. Material & Block Reference

### Block Categories (for grouping art work)

**Natural terrain (always present in world generation):**
Dirt, Stone, Bedrock, Core, Sandstone, Limestone, Shale, Chalk, Slate,
Marble, Gneiss, Granite, Basalt, Obsidian

**Ores (spawn in rock layers):**
Iron Ore, Copper Ore, Gold Ore, Mana Crystal

**Fluids (flow through the world):**
Water, Lava, Water Source, Water Sink, Lava Source, Lava Sink

**Crafted materials (player-made via smelting/crafting):**
Iron Ingot, Copper Ingot, Gold Ingot, Enchanted Metal

**Functional blocks (player-placed with gameplay effects):**
Reinforced Wall, Spike, Door, Treasure, Rolling Stone, Tarp, Slope,
Stairs, Pressure Plate, Floodgate, Alarm Bell, Iron Bars, Pipe, Pump,
Steam Vent

**Deceptive blocks (intentionally mimic other blocks):**
Fragile Floor (looks like Stone), Treasure Bait (looks like Treasure)

### Material Properties (useful for texture design)

Each material has physical properties that should inform its visual design:

| Material    | Weight | Porosity | Key Trait                          |
|-------------|--------|----------|------------------------------------|
| Dirt        | Light  | High     | Soft, crumbly, organic             |
| Stone       | Medium | Low      | Solid, default structural block    |
| Sandstone   | Medium | High     | Granular, porous, warm             |
| Limestone   | Medium | Medium   | Chalky, fossiliferous              |
| Marble      | Heavy  | None     | Polished, veined, prestigious      |
| Granite     | Heavy  | None     | Hard, speckled, crystalline        |
| Obsidian    | Heavy  | None     | Volcanic glass, smooth and dark    |
| Basalt      | Heavy  | Low      | Fine-grained volcanic              |
| Bedrock     | Max    | None     | Indestructible, primordial         |

---

## 10. Intruder Archetype Reference

### 8 Surface Archetypes

| Archetype    | Color RGB              | Hex       | Personality & Role                          |
|--------------|------------------------|-----------|---------------------------------------------|
| Explorer     | (0.20, 0.70, 0.30)    | `#33B34D` | Scout/thief. Lockpicks, trap detector       |
| Inquisitor   | (0.70, 0.70, 0.90)    | `#B3B3E6` | Armored crusader. Bashes doors, high HP     |
| Gloomwarden  | (0.90, 0.90, 0.50)    | `#E6E680` | Torch-bearing ranger. Arcane sight, support |
| Mole Tamer   | (0.60, 0.40, 0.20)    | `#996633` | Beast handler. Mole familiars dig tunnels   |
| Eidolon      | (0.60, 0.30, 0.90)    | `#994DE6` | Supernatural. Phases through walls, flies   |
| Alchemist    | (0.30, 0.70, 0.20)    | `#4DB333` | Potion brewer. Counter-brews vs dungeon     |
| Cartomancer  | (0.30, 0.30, 0.80)    | `#4D4DCC` | Scroll mage. Teleport, reveal, bridge       |
| Hero         | (1.00, 0.85, 0.00)    | `#FFD900` | Legendary champion. Never retreats, lucky   |

**Low morale:** When morale drops below threshold, intruders slow down and
retreat earlier. Visual indication via desaturation or hunched posture
rather than a color override.

---

## 11. Render Modes & Overlays

These overlays affect how blocks appear. The artist doesn't need to create
assets for these (they're computed by the renderer), but understanding
them helps ensure base textures work well under overlays.

### Contextual Overlays (applied in Matter mode)

| Overlay              | Color                      | Blend | When                       |
|----------------------|----------------------------|-------|----------------------------|
| Dig progress         | Gold (1.0, 0.85, 0.0)     | 40-70%| Block being dug            |
| Craft valid position | Green (0.2, 1.0, 0.3)     | 45%   | Player in craft mode       |
| Ingredient highlight | Cyan (0.3, 0.9, 1.0)      | 50%   | Clicked ingredient label   |
| Fog of war           | Near-black (0.03, 0.03, 0.04) | 100% | Unexplored territory    |
| Loose material       | 70% brightness             | —     | Block has no support       |

### Render Mode Overlays

| Mode        | Visual Effect                                          |
|-------------|--------------------------------------------------------|
| Humidity    | Blue tint (0.1, 0.3, 0.9) blended over base, max 60%  |
| Heat        | Full color replacement: blue → white → red gradient    |
| Structural  | Full color replacement: green → yellow → red gradient  |
| Prospecting | Grayscale desaturation + ore glow marker cubes         |

**Takeaway:** Textures should have enough contrast and detail that they
remain readable under a 60% blue humidity tint. Avoid textures that are
already very blue — they'll disappear in humidity mode.

---

## 12. Integration Notes for Programmers

This section is for the programmer integrating art assets into the engine.

### Texture Integration Path

The current vertex format is `v3n3c4` (no UVs). Adding textures requires:

1. **Add UV coordinates** to the chunk mesh builder. Each face quad maps
   `(0,0) → (1,1)` (full tile per face). Change vertex format to
   `v3n3t2c4`.
2. **Build a texture atlas** at load time from individual face PNGs. Each
   block type gets a small region on the atlas. UV coordinates index into
   atlas regions rather than individual textures.
3. **Multiply vertex color by texture sample** — the existing face shading
   (0.5–1.0 multiplier) and overlay tints should modulate the texture
   color. This requires either:
   - A simple fragment shader: `final = texture_sample * vertex_color`
   - Or Panda3D's `TextureStage` with `M_modulate` combine mode
4. **Per-face texture selection**: Look up `{block}_top.png` vs
   `{block}_side.png` based on face direction. Fall back to
   `{block}.png` if only one texture exists.
5. **Render mode bypass**: In Heat, Structural, and Prospecting modes,
   skip texturing and use solid computed colors (current behavior). In
   Humidity mode, apply the blue tint as a multiplicative overlay on the
   textured output.

### Sprite/Model Integration Path

For intruder rendering (replacing colored cubes):

1. **Billboarded sprites**: Use Panda3D's `BillboardEffect` on a textured
   quad. Swap texture frames for animation. Each intruder gets a sprite
   node instead of a GeomNode cube.
2. **Voxel/3D models**: Load `.gltf` via `loader.load_model()`, set
   archetype-specific color scale, parent to the z-level layer node.
3. **Low morale**: Apply slight desaturation or hunched posture animation
   to convey low morale. Use `setColorScale` for subtle visual feedback.

### UI Icon Integration Path

1. Load PNGs as Panda3D textures.
2. Use `DirectButton(image=...)` or `OnscreenImage` for icon placement.
3. Fall back to text labels if icon files are missing (for modding
   compatibility).

### Asset Discovery Convention

The engine should scan `assets/textures/blocks/` at load time and build a
mapping from block name to texture. If a texture file is missing, fall
back to the current procedural flat color. This allows incremental art
addition — the game works with zero, some, or all textures present.

```python
# Pseudocode for texture fallback
def get_block_texture(block_name: str, face: str) -> Texture | None:
    paths = [
        f"assets/textures/blocks/{block_name}_{face}.png",
        f"assets/textures/blocks/{block_name}.png",
    ]
    for p in paths:
        if os.path.exists(p):
            return loader.load_texture(p)
    return None  # Fall back to procedural color
```
