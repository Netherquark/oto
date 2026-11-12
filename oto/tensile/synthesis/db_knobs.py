#!/usr/bin/env python3
"""The forward-knob domains the DB-hooked mutator draws from.

Owns: ``FORWARD_KNOB_DOMAINS`` (what a forward knob may take), ``_DEFAULT_PATTERN``
(the fallback contraction pattern) and the donor-pool sizing knobs.
Does NOT own: the tile vocabulary (``TILE_KNOBS`` lives in
oto.tensile.synthesis.tile_space, imported by both synthesisers), the donor
loader that pops the pool (oto.tensile.synthesis.db), or the per-family mutation
patterns that consume these domains (oto.tensile.synthesis.db_patterns).
Public API: FORWARD_KNOB_DOMAINS, _DEFAULT_PATTERN, _DONOR_POOL, _FORWARD_DRAWS,
forward_domain, census_domain.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


from oto.device.peaks import FAMILY_DTYPE_CHAR

#: Forward knobs the manifest sampler cannot reach, with their legal domains.
#: Values are the Tensile-legal value sets (Common.py) intersected with what
#: the the device gates admit. This is the NARROW mutation space.
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
    "PrefetchGlobalRead": (0, 1, 2),
    "PrefetchLocalRead": (0, 1),
    "FractionalLoad": (0, 1, 2),
    "TransposeLDS": (-1, 0),   # 1 is the MFMA path; the device has no MFMA
    "GlobalLoadVectorWidthA": (1, 2, 4),
    "GlobalLoadVectorWidthB": (1, 2, 4),
    "NLCA": (-1, 1, 2, 3),
    "WorkGroupMapping": (1, 2, 3, 4, -1, -4),
    "StaggerU": (0, 8, 16, 32),
    "StaggerUMapping": (0, 1, 2),
    "StaggerUStride": (0, 64, 128, 256),
    "DepthU": (4, 8, 16, 32),
    "GlobalSplitU": (1, 2, 4),
    "AssertFree0ElementMultiple": (1, 2, 4),
    "AssertFree1ElementMultiple": (1, 2, 4),
    "MaxOccupancy": (8, 16, 32, 40),
    "NonTemporalA": (0, 1, 2, 3),
    "NonTemporalB": (0, 1, 2, 3),
    "NonTemporalC": (0, 1, 2, 3),
    "NonTemporalD": (0, 1, 2, 3),
}

#: Per-family overrides. A family absent here uses FORWARD_KNOB_DOMAINS.
#:
#: **Load widths** are dtype-dependent because of the *verified* 16-byte global-
#: load cap (``GLOBAL_LOAD_BYTE_CAP``): worst legal VectorWidth per dtype is
#: S 4, H 8, D 2, C 2, Z 1, and ``GLVW * bpe`` must stay <= 16 B. Drawing
#: GLVW=4 for DD/C/Z was a guaranteed gate refusal, wasting one of the five
#: forward draws the mutator gets per iteration.
#:
#: **GlobalSplitU** is restricted per family, and the two kinds of restriction
#: are NOT the same thing, so keep them apart:
#:
#: *Structural* -- ``>1`` can never run on this device, so offering it only burns
#: a draw. Tensile's own rule (SolutionStructs:3553) allows GSU only for single,
#: 8-bit float, double-with-BufferStore, Assembly-with-half-accumulate,
#: ``_GlobalAccumulation``, or MFMA. the device has no MFMA, which leaves:
#:   - ``CC`` / ``ZZ`` (complex) -- never legal.
#:   - ``HH_HPA`` / ``HS_HPA`` (half in, **f32** accumulate) -- never legal.
#:
#: *Deck state* -- ``HH`` is hardware-legal but banned **by decision**: GSU>1 on
#: half Assembly additionally requires ``AssertFree0ElementMultiple >= 2`` for the
#: atomics on edge tiles (SolutionStructs:3616), and the HH deck ships
#: ``AF0EM = 1``. See ``gfx90c_tuning_guide.md`` §9 ("HH GSU>1 structurally
#: banned (wide + narrow, test-locked)") and ``potential_configs.md`` pre-rewrite
#: §"SS is the only GSU-legal family". So this row is a *policy*, not a silicon
#: fact: lift it the day an HH candidate carries ``AF0EM >= 2``, and the axis
#: comes back without touching any other family.
#:
#: ``DD`` keeps ``(1, 2, 4)``: double plus BufferStore is a supported GSU case,
#: and the census classes DD as *coupled* rather than refused.
FAMILY_KNOB_DOMAINS: Dict[str, Dict[str, Tuple[Any, ...]]] = {
    "SS": {"GlobalLoadVectorWidthA": (1, 2, 4),
           "GlobalLoadVectorWidthB": (1, 2, 4)},
    "HH": {"GlobalLoadVectorWidthA": (1, 2, 4, 8),
           "GlobalLoadVectorWidthB": (1, 2, 4, 8),
           "GlobalSplitU": (1,)},
    "HH_HPA": {"GlobalLoadVectorWidthA": (1, 2, 4, 8),
               "GlobalLoadVectorWidthB": (1, 2, 4, 8),
               "GlobalSplitU": (1,)},
    "HS_HPA": {"GlobalLoadVectorWidthA": (1, 2, 4, 8),
               "GlobalLoadVectorWidthB": (1, 2, 4, 8),
               "GlobalSplitU": (1,)},
    "DD": {"GlobalLoadVectorWidthA": (1, 2),
           "GlobalLoadVectorWidthB": (1, 2)},
    "CC": {"GlobalLoadVectorWidthA": (1, 2),
           "GlobalLoadVectorWidthB": (1, 2),
           "GlobalSplitU": (1,)},
    "ZZ": {"GlobalLoadVectorWidthA": (1,),
           "GlobalLoadVectorWidthB": (1,),
           "GlobalSplitU": (1,)},
}


def forward_domain(family: Optional[str], knob: str) -> Tuple[Any, ...]:
    """The legal draw set for ``knob`` in ``family`` (family override wins).

    Calibrated on the device hardware facts, not on what the gfx900 floor chose.
    This is the *mutator's* set: it is narrowed per family so a draw the gate
    would refuse anyway does not burn one of the five draws an iteration gets.
    """
    if family:
        fam = FAMILY_KNOB_DOMAINS.get(str(family).upper())
        if fam and knob in fam:
            return fam[knob]
    return FORWARD_KNOB_DOMAINS[knob]


def census_domain(family: Optional[str], knob: str) -> Tuple[Any, ...]:
    """The device-truth draw set for ``knob``: global ∪ family override.

    The drawing mutator and the legality census want opposite things from a
    domain. The mutator wants ``forward_domain`` — narrow, so a value the gate
    refuses never wastes a draw. The census wants the *device truth*: a value
    refused by a structural class rule ("illegal on the device", "no
    MatrixInstruction") must still be **reported with its rule**, or a reader
    mistakes a deliberately-narrowed domain for a dead axis and "fixes" it.
    ``GlobalSplitU>1`` on CC/ZZ is exactly that case: structurally illegal
    (SolutionStructs:3553 — no MFMA), and absent from CC's ``forward_domain``.

    The union is the set of values either consumer can see, so the census
    neither misses a narrowed-away refusal (CC ``GlobalSplitU``) nor invents a
    refusal for a value only some family can draw (HH ``GLVW=8``).
    """
    vals = set(FORWARD_KNOB_DOMAINS[knob])
    if family:
        fam = FAMILY_KNOB_DOMAINS.get(str(family).upper())
        if fam and knob in fam:
            vals |= set(fam[knob])
    return tuple(sorted(vals))

#: Default ContractionPattern per family (matches the deck/first pattern).
_DEFAULT_PATTERN = {
    "SS": "Ailk_Bjlk", "DD": "Ailk_Bjlk", "HH": "Ailk_Bjlk",
    "CC": "Ailk_Bjlk", "ZZ": "Alik_Bjlk",
    "HH_HPA": "Ailk_Bjlk", "HS_HPA": "Ailk_Bjlk",
}

#: How many tile donors / forward draws to try per cell before gating.
_DONOR_POOL = 6
_FORWARD_DRAWS = 5  # increased from 3 to cover more knob combinations
