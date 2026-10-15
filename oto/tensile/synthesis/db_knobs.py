#!/usr/bin/env python3
"""The forward-knob domains the DB-hooked mutator draws from.

Owns: ``FORWARD_KNOB_DOMAINS`` (what a forward knob may take), ``_DEFAULT_PATTERN``
(the fallback contraction pattern) and the donor-pool sizing knobs.
Does NOT own: the tile vocabulary (``TILE_KNOBS`` lives in
oto.tensile.synthesis.tile_space, imported by both synthesisers), the donor
loader that pops the pool (oto.tensile.synthesis.db), or the per-family mutation
patterns that consume these domains (oto.tensile.synthesis.db_patterns).
Public API: FORWARD_KNOB_DOMAINS, _DEFAULT_PATTERN, _DONOR_POOL, _FORWARD_DRAWS.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


from oto.device.peaks import FAMILY_DTYPE_CHAR

#: Forward knobs the manifest sampler cannot reach, with their legal domains.
#: Values are the Tensile-legal value sets (Common.py) intersected with what
#: the gfx90c gates admit. This is the NARROW mutation space.
#:
#: 2026-10-16 revisions (potential_configs.md §0 R6):
#: * ``StaggerUStride`` (0,64,128,256). Tensile silently raises SUS to a whole
#:   multiple of DepthU*bpe, so 256 collapses to 64 for DU=16/bpe=4 and most of
#:   the old (0,256,512) domain was one point. 64/128 are live and already in
#:   ``STAGGER_STRIDE_DOMAIN``.
#: * ``WorkGroupMapping`` (1,2,3,4,-1,-4). 8 is the floor's dominant value
#:   because it was tuned for 56-60 CUs; on 7 CUs it asks for 8 workgroups in
#:   the J-column before wrapping. The negative (I/J-swap) family has never
#:   been generated at all.
FORWARD_KNOB_DOMAINS: Dict[str, Tuple[Any, ...]] = {
    "LdsPadA": (0, 1, 2, 4),
    "LdsPadB": (0, 1, 2, 4),
    "PrefetchGlobalRead": (0, 1),
    "PrefetchLocalRead": (0, 1),
    "GlobalLoadVectorWidthA": (1, 2, 4),
    "GlobalLoadVectorWidthB": (1, 2, 4),
    "NLCA": (1, 2, 3),
    "WorkGroupMapping": (1, 2, 3, 4, -1, -4),
    "StaggerU": (0, 8, 16, 32),
    "StaggerUMapping": (0, 1, 2),
    "StaggerUStride": (0, 64, 128, 256),
    "DepthU": (4, 8, 16, 32),
    "GlobalSplitU": (1, 2, 4),
    "AssertFree0ElementMultiple": (1, 2),
    "AssertFree1ElementMultiple": (1, 2),
}

#: Per-family overrides. A family absent here uses FORWARD_KNOB_DOMAINS.
#:
#: The load-width domains are dtype-dependent because of the *verified* 16-byte
#: global-load cap (``GLOBAL_LOAD_BYTE_CAP``): worst legal VectorWidth per dtype
#: is S 4, H 8, D 2, C 2, Z 1, and ``GLVW * bpe`` must stay <= 16 B. Drawing
#: GLVW=4 for DD/C/Z was a guaranteed gate refusal, wasting one of the five
#: forward draws the mutator gets per iteration.
FAMILY_KNOB_DOMAINS: Dict[str, Dict[str, Tuple[Any, ...]]] = {
    "SS": {"GlobalLoadVectorWidthA": (1, 2, 4),
           "GlobalLoadVectorWidthB": (1, 2, 4)},
    "HH": {"GlobalLoadVectorWidthA": (1, 2, 4, 8),
           "GlobalLoadVectorWidthB": (1, 2, 4, 8)},
    "HH_HPA": {"GlobalLoadVectorWidthA": (1, 2, 4, 8),
               "GlobalLoadVectorWidthB": (1, 2, 4, 8)},
    "HS_HPA": {"GlobalLoadVectorWidthA": (1, 2, 4, 8),
               "GlobalLoadVectorWidthB": (1, 2, 4, 8)},
    "DD": {"GlobalLoadVectorWidthA": (1, 2),
           "GlobalLoadVectorWidthB": (1, 2)},
    "CC": {"GlobalLoadVectorWidthA": (1, 2),
           "GlobalLoadVectorWidthB": (1, 2)},
    "ZZ": {"GlobalLoadVectorWidthA": (1,),
           "GlobalLoadVectorWidthB": (1,)},
}


def forward_domain(family: Optional[str], knob: str) -> Tuple[Any, ...]:
    """The legal draw set for ``knob`` in ``family`` (family override wins).

    Calibrated on gfx90c hardware facts, not on what the gfx900 floor chose.
    """
    if family:
        fam = FAMILY_KNOB_DOMAINS.get(str(family).upper())
        if fam and knob in fam:
            return fam[knob]
    return FORWARD_KNOB_DOMAINS[knob]

#: Default ContractionPattern per family (matches the deck/first pattern).
_DEFAULT_PATTERN = {
    "SS": "Ailk_Bjlk", "DD": "Ailk_Bjlk", "HH": "Ailk_Bjlk",
    "CC": "Ailk_Bjlk", "ZZ": "Alik_Bjlk",
    "HH_HPA": "Ailk_Bjlk", "HS_HPA": "Ailk_Bjlk",
}

#: How many tile donors / forward draws to try per cell before gating.
_DONOR_POOL = 6
_FORWARD_DRAWS = 5  # increased from 3 to cover more knob combinations
