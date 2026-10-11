#!/usr/bin/env python3
"""The forward-knob domains and tile vocabulary the DB-hooked mutator draws from.

Owns: ``FORWARD_KNOB_DOMAINS`` (what a forward knob may take), ``_TILE_KNOBS``
(which keys make up a tile), ``_DEFAULT_PATTERN`` (the fallback contraction
pattern) and the donor-pool sizing knobs.
Does NOT own: the donor loader that pops the pool (oto.tensile.synthesis.db) or
the per-family mutation patterns that consume these domains.
Public API: FORWARD_KNOB_DOMAINS, _TILE_KNOBS, _DEFAULT_PATTERN, _DONOR_POOL,
_FORWARD_DRAWS.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


from oto.device.peaks import FAMILY_DTYPE_CHAR

#: Forward knobs the manifest sampler cannot reach, with their legal domains.
#: Values are the Tensile-legal value sets (Common.py) intersected with what
#: the gfx90c gates admit. This is the NARROW mutation space.
FORWARD_KNOB_DOMAINS: Dict[str, Tuple[Any, ...]] = {
    "LdsPadA": (0, 1, 2, 4),
    "LdsPadB": (0, 1, 2, 4),
    "PrefetchGlobalRead": (0, 1),
    "PrefetchLocalRead": (0, 1),
    "GlobalLoadVectorWidthA": (1, 2, 4),
    "GlobalLoadVectorWidthB": (1, 2, 4),
    "NLCA": (1, 2, 3),
    "WorkGroupMapping": (1, 4, 8),
    "StaggerU": (0, 8, 16, 32),
    "StaggerUMapping": (0, 1, 2),
    "StaggerUStride": (0, 256, 512),
    "DepthU": (4, 8, 16, 32),
    "GlobalSplitU": (1, 2, 4),
    "AssertFree0ElementMultiple": (1, 2),
}

#: Knobs that make up a "tile donor" (the wide axes the DB carries).
_TILE_KNOBS = ("MacroTile", "ThreadTile", "VectorWidth", "GlobalSplitU",
               "DepthU", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
               "WorkGroup")

#: Default ContractionPattern per family (matches the deck/first pattern).
_DEFAULT_PATTERN = {
    "SS": "Ailk_Bjlk", "DD": "Ailk_Bjlk", "HH": "Ailk_Bjlk",
    "CC": "Ailk_Bjlk", "ZZ": "Alik_Bjlk",
    "HH_HPA": "Ailk_Bjlk", "HS_HPA": "Ailk_Bjlk",
}

#: How many tile donors / forward draws to try per cell before gating.
_DONOR_POOL = 6
_FORWARD_DRAWS = 5  # increased from 3 to cover more knob combinations
