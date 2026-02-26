"""Game constants and balance parameters — domain-organized.

This package re-exports every constant from its sub-modules so that
existing ``from dungeon_builder.config import X`` imports continue to
work unchanged.  New code may import from the specific sub-module for
clarity (e.g., ``from dungeon_builder.config.materials import VOXEL_WEIGHT``).

Sub-modules
-----------
voxels      Voxel type IDs (uint8 constants).
world       Grid dimensions, timing, Z-levels, camera, terrain gen.
metals      Metal type system (constants, functions, property tables).
materials   Per-voxel material property LUTs.
physics     Physics tick intervals, fluid dynamics, structural constants.
rendering   Render modes, colours, fog, ore glow, vertex noise.
intruders   Intruder AI, party composition, social dynamics, pathfinding.
building    Dev mode, dig config, block gameplay, pipes & pumps.

Dependencies: (none — top-level re-export)
Dependents: virtually every module in the project
"""

# Re-export everything so ``from dungeon_builder.config import X`` works.
# Order follows the dependency graph (leaf modules first).

from dungeon_builder.config.voxels import *       # noqa: F401,F403
from dungeon_builder.config.world import *        # noqa: F401,F403
from dungeon_builder.config.metals import *       # noqa: F401,F403
from dungeon_builder.config.materials import *    # noqa: F401,F403
from dungeon_builder.config.physics import *      # noqa: F401,F403
from dungeon_builder.config.rendering import *    # noqa: F401,F403
from dungeon_builder.config.intruders import *    # noqa: F401,F403
from dungeon_builder.config.building import *     # noqa: F401,F403
