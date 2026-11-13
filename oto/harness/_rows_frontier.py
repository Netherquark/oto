"""Candidate row builders, part 2: the tie-adapt and frontier blocks.

Owns: ``_TIE_ADAPT``, ``_PROBE_AXES``, ``_TIE_WINNERS``, ``_FRONTIER`` and
the AF/WGM row generators -- the measured-winner blocks appended to
``PLAN_BATCH`` after ``_rows_core`` builds it. Import only after
``_rows_core`` (it mutates ``PLAN_BATCH``). See ``oto.harness.candidate_rows``
for the consumer-facing re-exports.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from oto.harness._rows_core import PLAN_BATCH, PATTERNS

_TIE_ADAPT: List[Tuple[str, str, str, str, int, int,
                       List[Tuple[Dict[str, Any], str]]]] = [
    # SS:512-1365 winner; SS:2048/4096 use the DepthU-16 variant below.
    ("SS", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, [
        ({"NonTemporalA": 1}, "NonTemporalA (stream past the 1 MiB L2)"),
        ({"NonTemporalB": 1}, "NonTemporalB"),
        ({"MaxOccupancy": 8}, "MaxOccupancy=8 (7-CU residency clamp)"),
        ({"InnerUnroll": 2}, "InnerUnroll=2 (fewer loop issues)"),
        ({"StaggerU": 16, "StaggerUMapping": 2}, "swizzle SU16/SUM2"),
        ({"LdsPadB": 1}, "LdsPadB=1 (bank pad, 4 B rows)"),
    ]),
    # SS:2048/4096 winner (DepthU 16).
    ("SS", "Ailk_Bjlk", "128x128x16", "8x8", 4, 16, [
        ({"NonTemporalA": 1}, "NonTemporalA on the deep tile"),
        ({"PrefetchGlobalRead": 0}, "PGR=0 (register/LDS relief)"),
    ]),
    # SS LSU=2: the winner tile is *illegal* at LSU 2 -- the reduction buffer
    # 2*128*128*4 B = 131072 B exceeds the 65536 per-CU LDS ceiling
    # (potential_configs.md §R24) -- so the wave-fill probe runs on the widest
    # LEGAL LSU-2 tile instead: M and DepthU kept, N halved to sit exactly on
    # the reduction cap, VW2 because a 4-wide load does not divide the 8x4
    # operand access.
    ("SS", "Ailk_Bjlk", "128x64x16", "8x4", 2, 16, [
        ({"LocalSplitU": 2}, "LocalSplitU=2 on the widest legal tile"),
    ]),
    # HH:1024-4096 winner.  VW=8 is 2 B x 8 == the 16 B load cap.
    ("HH", "Ailk_Bjlk", "128x128x16", "8x8", 8, 16, [
        ({"NonTemporalA": 1}, "NonTemporalA"),
        ({"NonTemporalB": 1}, "NonTemporalB"),
        ({"MaxOccupancy": 8}, "MaxOccupancy=8"),
        ({"InnerUnroll": 2}, "InnerUnroll=2"),
        ({"StaggerU": 0, "StaggerUMapping": 0, "StaggerUStride": 0},
         "swizzle off"),
        ({"StaggerU": 16, "StaggerUMapping": 2}, "swizzle SU16/SUM2"),
        ({"LdsPadB": 1}, "LdsPadB=1"),
        ({"WorkGroupMapping": -4}, "WGM=-4 (negative I/J-swap family)"),
    ]),
    # DD:768-2048 winner (near-bar; residual is issue rate).
    ("DD", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8, [
        ({"NonTemporalA": 1}, "NonTemporalA"),
        ({"MaxOccupancy": 8}, "MaxOccupancy=8"),
        ({"InnerUnroll": 2}, "InnerUnroll=2"),
        ({"LocalSplitU": 2}, "LocalSplitU=2"),
    ]),
    # HH_HPA:1024/2048 winner (no floor data; native is 123-129% of bar).
    ("HH_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 4, 16, [
        ({"NonTemporalA": 1}, "NonTemporalA"),
        ({"MaxOccupancy": 8}, "MaxOccupancy=8"),
        ({"InnerUnroll": 2}, "InnerUnroll=2"),
    ]),
    # HH_HPA:512 winner (the 2.2x cell).
    ("HH_HPA", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, [
        ({"NonTemporalA": 1}, "NonTemporalA on the :512 winner"),
    ]),
    # HS_HPA:1024 winner.
    ("HS_HPA", "Ailk_Bjlk", "128x64x16", "8x4", 4, 16, [
        ({"NonTemporalA": 1}, "NonTemporalA"),
        ({"MaxOccupancy": 8}, "MaxOccupancy=8"),
        ({"InnerUnroll": 2}, "InnerUnroll=2"),
    ]),
    # HS_HPA:512 winner.
    ("HS_HPA", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, [
        ({"NonTemporalA": 1}, "NonTemporalA on the :512 winner"),
    ]),
]
for _fam, _pat, _tile, _tt, _vw, _du, _variants in _TIE_ADAPT:
    for _kw, _note in _variants:
        PLAN_BATCH.append({"fam": _fam, "pattern": _pat, "MacroTile": _tile,
                           "ThreadTile": _tt, "VectorWidth": _vw,
                           "DepthU": _du, **_kw,
                           "note": "2026-10-17 tie-adapt: " + _note})


# --- the never-co-varied forwarded axes (potential_configs.md rewrite 7 §R37) --
#
# §R37 is why these exist. The 2026-10-18 run left 18 cells inside the report's
# +/-5% tie band; the `_TIE_ADAPT` batch above had already probed NonTemporalA/B,
# MaxOccupancy, InnerUnroll, the StaggerU swizzle, LdsPadB and PGR on those same
# winner geometries, and every one of them measured 0.83-0.98 of the base. So the
# geometry is a local optimum for *those* axes, and re-probing them is dead
# budget. What is left is the set of forwarded knobs that no phase in the
# registry has ever carried on a winner geometry:
#
#   * UseSgprForGRO -- absent from the registry entirely (0 of 1137 phases).
#   * PrefetchLocalRead -- absent from the registry entirely.
#   * LdsPadA -- only ever carried by the broken `phases.yaml` `sw*` generation
#     (§R35), which measured ~0.5x of its own same-run winner because it was
#     built on Ailk_Bljk + VectorWidth 1, so its reading is void.
#
# `NumLoadsCoalescedA/B` is deliberately ABSENT, and this is a *proof*, not an
# omission. `gates/loads.py::_nlca_stage` implements Tensile's joint rule
# (SolutionStructs:2058): NLCA must divide `numLoads`, divide
# `totalVectorsCoalesced`, and leave `totalElementsPerp` divisible by
# `numLoads // NLCA`. On the winner tiles GLVW saturates the 16-B cap, so
# numLoads is 1 and NLCA>1 fails `NLCA > NumLoads` outright -- on exactly the
# geometries a 7-CU part would want re-tuned. The axis is unreachable, not
# unexplored: were GLVW ever lowered, NLCA>1 would open up, and the gate is what
# will say so.
#
# Every key below is in `config_writer.FORWARDED_KNOBS` (UseSgprForGRO/InnerUnroll
# via `_fork_sweep_int_knobs`, PrefetchLocalRead via `_fork_prefetch`, LdsPadA/B
# via FORWARDED_GROUP_C_KNOBS), verified knob by knob against
# `_fork_list_for_phase` rather than inferred from this comment. `LocalSplitU` is
# absent too: it is in neither `FORWARDED_KNOBS` nor `NOT_FORWARDED_KNOBS`, so the
# launch boundary strips nothing and the writer drops it, which makes the two
# `LocalSplitU: 2` rows above silent no-ops.
#
# Bases are the per-cell measured winners from `cells_resolved.full.txt`, so a
# row lands on the geometry that actually ties. GlobalLoadVectorWidth is left
# implicit, as in `_TIE_ADAPT`: Tensile defaults it to VectorWidth, which is what
# every measured winner recorded.
_PROBE_AXES: List[Tuple[Dict[str, Any], str]] = [
    ({"UseSgprForGRO": 1}, "UseSgprForGRO (0 of 1137 phases ever set it)"),
    ({"PrefetchLocalRead": 0}, "PrefetchLocalRead=0 (LDS read-prefetch relief)"),
    ({"LdsPadA": 4, "LdsPadB": 4}, "pad both LDS rows to 8 B"),
    ({"InnerUnroll": 2, "UseSgprForGRO": 1}, "InnerUnroll=2 with SgprForGRO"),
]

#: (family, pattern, MacroTile, ThreadTile, VectorWidth, DepthU, sides) -- the
#: measured winner of every cell that currently ties the floor. `sides` is
#: documentation: a row is offered across its whole family, and `_offer_row`
#: decides which of those sizes its element-multiple assertions accept.
_TIE_WINNERS: List[Tuple[str, str, str, str, int, int, Tuple[int, ...]]] = [
    ("SS", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, (768, 1000, 1024, 1365)),
    ("SS", "Ailk_Bjlk", "128x128x16", "8x8", 4, 16, (2048, 4096)),
    ("CC", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8, (512, 1024, 2048)),
    ("DD", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8, (768,)),
    ("DD", "Alik_Bjlk", "64x32x8", "4x2", 1, 8, (1024,)),
    ("DD", "Ailk_Bjlk", "32x32x16", "2x2", 1, 16, (1365,)),
    ("DD", "Alik_Bljk", "64x64x8", "4x4", 2, 8, (2048,)),
    ("HH", "Ailk_Bjlk", "128x128x16", "8x8", 8, 16, (1024, 2048, 4096)),
    ("HH_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 4, 16, (1024,)),
    ("HH_HPA", "Ailk_Bjlk", "128x64x8", "8x4", 2, 8, (2048,)),
    ("HS_HPA", "Ailk_Bjlk", "128x64x16", "8x4", 4, 16, (1024,)),
    ("HS_HPA", "Alik_Bjlk", "64x128x16", "4x8", 4, 16, (2048,)),
]
for _fam, _pat, _tile, _tt, _vw, _du, _sides in _TIE_WINNERS:
    for _kw, _note in _PROBE_AXES:
        PLAN_BATCH.append({"fam": _fam, "pattern": _pat, "MacroTile": _tile,
                           "ThreadTile": _tt, "VectorWidth": _vw,
                           "DepthU": _du, **_kw,
                           "note": "2026-10-19 virgin-axis: " + _note})


# --- the reachable tile frontier, and the assertion that unlocks it (§R40) ---
#
# WHY EVERY TIE SURVIVED THE KNOB SWEEPS, AND WHY "TRY A BIGGER TILE" WAS
# NEVER ACTUALLY TESTED. §R37 re-probed each forwarded knob on the tied cells'
# winner geometry and every probe measured 0.83-0.98 of its base. That is a
# real result, but it is a statement about *knobs*, not about geometry: the
# winners all sit at a 128x128 (SS/HH) or 64x64 (CC/DD) tile, and the corpus
# holds exactly two tiles above 16384 elements -- 128x256 and 256x128, both
# with ThreadTile 16x8, i.e. 128 accumulators a thread against the winner's 64.
# Read off the emitted code objects, that confound is the whole effect:
#
#   SS 128x128 TT8x8  DU8   vgpr 113  LDS 16384  -> 2 WGs x 4 waves =  8 waves
#   SS 256x128 TT16x8 DU8   vgpr 199  LDS 28736  -> 1 WG  x 4 waves =  4 waves
#   HH 128x128 TT8x8  DU16  vgpr  63  LDS 24832  -> 2 WGs x 4 waves =  8 waves
#   HH 256x128 TT16x8 DU8   vgpr 105  LDS 14336  -> 2 WGs x 4 waves =  8 waves
#
# so SS's only large-tile point loses half its residency by construction, and
# HH's ran at VW4 (8 B) instead of the winner's VW8 (16 B == the load cap):
# 256x128 at VW8 was never emitted for any family.
#
# It was never emitted because it is *illegal*, and that is the real finding.
# `gates/loads.py` ports SolutionStructs' classic load structure, where operand
# B's load is legal only when `MT1*DepthU` and `NumThreads*GLVW` are
# commensurate. With GLVW == VectorWidth, ThreadTile t0xt1 and LocalSplitU 1
# that reduces to one line:
#
#     MT1 * GLVW  ==  t0 * t1 * DepthU          (the no-assertion case)
#
# because then NumThreads*GLVW == MT0*DepthU exactly, so operand A balances for
# *any* MT0 and operand B balances iff MT0/MT1 is an integer. Every other
# combination either fails the divisibility stage or -- at MT0/MT1 = 2, 4, ...
# -- leaves GLVW_eff = GLVW/pv unequal to VectorWidth, which Tensile refuses
# unless `AssertFree0/1ElementMultiple` certifies the free dimension is a
# multiple of the wide load (SolutionStructs:4583-4596). Sweeping MT0, MT1 in
# [64, 512] step 8, ten thread tiles, every legal vector width and DepthU
# 8/16/32 through the real gate (`tests/test_tile_frontier.py` ships the sweep)
# returns exactly two supra-16384 tiles for SS -- 256x128 and its mirror -- and
# four for each 16-bit-input family: the same pair plus 64x512 / 512x64, whose
# 8x depth lets the pv case land on GLVW_eff == 1 with no assertion at all.
#
# So the frontier below is the whole remaining geometry space, not a sample of
# it. Each 2:1 tile is measured twice -- at the halved vector width (legal
# outright) and at the full width (legal only under the assertion) -- so the
# load width is a controlled variable and not a confound. The assertion itself
# is the second virgin axis: it appears in 37 of 7622 emitted configs. It is
# what Tensile's `GuaranteeNoPartial` reads, so setting it lets the kernel drop
# the per-tile free-dimension predication -- and it is the only way to reach the
# full load width at 2x area.
#
# The frontier also closes the two families that look worst on the report. CC's
# accumulator cap is MTarea < 16384 and its no-assertion rule is MT1*GLVW ==
# 4*4*8 = 128, so its widest legal tiles are 128x64 (VW2) and 64x128 (VW1),
# both already measured and both worse than 64x64. ZZ's rule is the same with
# VW 1, MT1 = 128, and the 8192-element accumulator cap then refuses 64x128, so
# its largest legal tile is 64x64 -- also measured. The 1118.7 GFLOPS CC bar and
# the 98.6 GFLOPS ZZ bar are therefore unreachable by construction, not by
# tuning; `<codename>_theoretical_limits.md` §5.1 owns that conclusion.
_FRONTIER: Dict[str, Tuple[str, Tuple[Tuple[str, str, int, int, Dict[str, Any]], ...]]] = {
    "SS": ("float32, DU8 (the deepest depth with (m+n)*8*4 <= 16384 above 128 wide)",
           (("256x128x8", "8x8", 2, 8, {}),
            ("128x256x8", "8x8", 2, 8, {}),
            ("256x128x8", "8x8", 4, 8, {"AssertFree1ElementMultiple": 2}),
            ("128x256x8", "8x8", 4, 8, {"AssertFree0ElementMultiple": 2}))),
    "HH": ("float16, DU16 at 2:1; DU8 also admits a 4:1 tile with no assertion "
           "at all, which is the clean area-versus-aspect control",
           (("256x128x16", "8x8", 4, 16, {}),
            ("128x256x16", "8x8", 4, 16, {}),
            ("256x128x16", "8x8", 8, 16, {"AssertFree1ElementMultiple": 4}),
            ("128x256x16", "8x8", 8, 16, {"AssertFree0ElementMultiple": 4}),
            ("64x512x8", "8x8", 8, 8, {}),
            ("512x64x8", "8x8", 8, 8, {}))),
    "HH_HPA": ("fp16 in / fp32 accumulate: 2:1 under the assertion, and the "
               "4:1 DU8 tile that needs none",
               (("256x128x16", "4x8", 2, 16, {}),
                ("128x256x16", "4x8", 2, 16, {}),
                ("256x128x16", "4x8", 4, 16, {"AssertFree1ElementMultiple": 2}),
                ("128x256x16", "4x8", 4, 16, {"AssertFree0ElementMultiple": 2}),
                ("64x512x8", "8x8", 8, 8, {}),
                ("512x64x8", "8x8", 8, 8, {}))),
    "HS_HPA": ("fp16 in / fp32 accumulate with an fp32 B operand: the fp32 "
               "operand doubles the LDS footprint, so only VW2 stays legal",
               (("256x128x8", "8x4", 2, 8, {}),
                ("128x256x8", "8x4", 2, 8, {}),
                ("256x128x16", "8x4", 2, 16, {}),
                ("128x256x16", "8x4", 2, 16, {}),
                ("64x512x8", "8x8", 2, 8, {}),
                ("512x64x8", "8x8", 2, 8, {}))),
}

#: The assertion axis on the *measured* winners: same tile, same threads, only
#: the free-dimension guarantee changes, so any delta is codegen (the dropped
#: edge predication) and not geometry. `8` is the largest value every measured
#: side satisfies except 1365, which `_shapes_satisfying_assertions` then drops
#: from the row instead of silently measuring a false assertion.
_AF_TILES: Tuple[Tuple[str, str, str, int, int], ...] = (
    ("SS", "128x128x8", "8x8", 4, 8),
    ("SS", "128x128x16", "8x8", 4, 16),
    ("HH", "128x128x16", "8x8", 8, 16),
    ("CC", "64x64x8", "4x4", 2, 8),
    ("DD", "64x64x8", "4x4", 2, 8),
    ("ZZ", "64x64x8", "4x4", 1, 8),
    ("HH_HPA", "64x128x16", "4x8", 4, 16),
    ("HS_HPA", "128x64x16", "8x4", 4, 16),
)
_AF_LEVELS: Tuple[int, ...] = (2, 4, 8)

for _fam, (_why, _tiles) in _FRONTIER.items():
    for _tile, _tt, _vw, _du, _extra in _tiles:
        for _pat in PATTERNS[_fam]:
            PLAN_BATCH.append({
                "fam": _fam, "pattern": _pat, "MacroTile": _tile,
                "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du, **_extra,
                "note": f"2026-10-20 frontier: {_why}"})
for _fam, _tile, _tt, _vw, _du in _AF_TILES:
    for _lvl in _AF_LEVELS:
        for _pat in PATTERNS[_fam]:
            PLAN_BATCH.append({
                "fam": _fam, "pattern": _pat, "MacroTile": _tile,
                "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
                "AssertFree0ElementMultiple": _lvl,
                "AssertFree1ElementMultiple": _lvl,
                "note": f"2026-10-20 assertion axis: both free dims "
                        f"asserted a multiple of {_lvl}"})
#: The raster rows. WGM 1 and 8 both lose to 4 on every family and 2 and 3 were
#: never emitted; the two places it can still matter are the frontier (the tile
#: order changes at 2x area) and DD, whose four ties are wave quantisation on
#: the sides no power-of-two tile divides and which is otherwise at 98 % of its
#: peak. DD's winner is here rather than in `_FRONTIER` because DD has no legal
#: tile above 16384 -- it is the only row in this batch that reaches 1365.
_WGM_ROWS: Tuple[Tuple[str, str, str, int, int, Dict[str, Any]], ...] = (
    *((fam, tile, tt, vw, du, extra)
      for fam in ("SS", "HH")
      for tile, tt, vw, du, extra in _FRONTIER[fam][1]),
    ("DD", "64x64x8", "4x4", 2, 8, {}),
)
for _fam, _tile, _tt, _vw, _du, _extra in _WGM_ROWS:
    for _wgm in (2, 3):
        for _pat in PATTERNS[_fam][:2]:
            PLAN_BATCH.append({
                "fam": _fam, "pattern": _pat, "MacroTile": _tile,
                "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
                "WorkGroupMapping": _wgm, **_extra,
                "note": f"2026-10-20 frontier raster: WGM={_wgm} (untried)"})

#: The frontier at half the thread tile: same 256x128 area, 32 accumulators a
#: thread instead of 64, 1024 threads in a single workgroup. This is the
#: control that separates "the area is bad" from "the registers ran out" --
#: with only these four rows a loss at 256x128/8x8 and a win at 256x128/8x4 is
#: unambiguously a residency effect. HH needs the free-dimension assertion at
#: VW4 for the same load-divisibility reason as the frontier itself.
#:
#: The SS half of the control is GONE, and it was never legal: 256x128 at TT
#: 8x4 is 1024 threads, and at 1024 threads the file leaves 65536/1024 = 64
#: VGPRs/thread while the thread tile emits 77 -- Tensile's error 4
#: ("Generating kernel source resulted in error 4"). The 8 SS rows died that
#: way in the 2026-10-20 run and the occupancy gate now refuses them before
#: launch (the per-thread occupancy limit, `gates/occupancy.py`
#: `_occupancy_limit_check`). The control is not "bad", it is impossible on
#: this part: at 256x128 the only thread tile that fits 1024 threads needs
#: more than 64 VGPRs/thread. HH's control survives (H 8x4 emits 57).
_FRONTIER_THREAD_CONTROLS: Tuple[
        Tuple[str, str, str, int, int, Dict[str, Any]], ...] = (
    ("HH", "256x128x16", "8x4", 4, 16, {"AssertFree1ElementMultiple": 2}),
    ("HH", "128x256x16", "4x8", 4, 16, {"AssertFree0ElementMultiple": 2}),
)
for _fam, _tile, _tt, _vw, _du, _extra in _FRONTIER_THREAD_CONTROLS:
    for _pat in PATTERNS[_fam]:
        PLAN_BATCH.append({
            "fam": _fam, "pattern": _pat, "MacroTile": _tile,
            "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du, **_extra,
            "note": "2026-10-20 frontier thread control: half the accumulators "
                    "at the same area"})

# 2026-10-21 R44/R45 — virgin-knob probes on the winner geometries.
# Each knob below has zero variance in the gfx900 floor (tuning guide §9.1) and is
# now in FORWARD_KNOB_DOMAINS; the rows are gate-verified by
# tests/test_generate_candidates.py::TestEveryDeckRowIsGenerative.
# LdsPad=1 (the value the floor never uses), NLCA=-1 (least-coalesced regime),
# StaggerUMapping=1/2 (vendor-recommended, never measured), MaxOccupancy=16/32
# (cap LDS to buy occupancy), NonTemporal=1/2/3 (cache hints on 1 MiB L2),
# PrefetchGlobalRead=2 (gated by the doubled-LDS check in ldspad_feasible).
for _fam, _tile, _tt, _vw, _du, _pat_list in (
    ("CC", "64x64x8", "4x4", 2, 8, ("Ailk_Bjlk",)),
    ("ZZ", "32x32x8", "2x2", 1, 8, ("Alik_Bjlk",)),
    ("SS", "128x128x8", "8x8", 4, 8, ("Ailk_Bjlk",)),
    ("HH", "128x128x16", "8x8", 8, 16, ("Ailk_Bjlk",)),
    ("DD", "64x64x8", "4x4", 2, 8, ("Ailk_Bjlk",)),
):
    for _pat in _pat_list:
        for _pad in (1,):
            PLAN_BATCH.append({"fam": _fam, "pattern": _pat,
                "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
                "DepthU": _du, "LdsPadA": _pad,
                "note": "R45 virgin: LdsPadA=1 (never measured in floor)"})
            PLAN_BATCH.append({"fam": _fam, "pattern": _pat,
                "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
                "DepthU": _du, "LdsPadB": _pad,
                "note": "R45 virgin: LdsPadB=1 (never measured in floor)"})
        for _sm in (1, 2):
            PLAN_BATCH.append({"fam": _fam, "pattern": _pat,
                "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
                "DepthU": _du, "StaggerUMapping": _sm,
                "note": f"R45 virgin: StaggerUMapping={_sm}"})
        for _mo in (16, 32):
            PLAN_BATCH.append({"fam": _fam, "pattern": _pat,
                "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
                "DepthU": _du, "MaxOccupancy": _mo,
                "note": f"R45 virgin: MaxOccupancy={_mo}"})
        for _nt in (1, 2, 3):
            PLAN_BATCH.append({"fam": _fam, "pattern": _pat,
                "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
                "DepthU": _du, "NonTemporalC": _nt,
                "note": f"R45 virgin: NonTemporalC={_nt}"})

# NLCA=-1 (least-coalesced regime) on the 3-load tiles only.
for _fam, _tile, _tt, _vw, _du in (
    ("CC", "64x64x8", "4x4", 2, 8),
    ("ZZ", "32x32x8", "2x2", 1, 8),
    ("SS", "96x96x16", "6x6", 2, 16),
):
    PLAN_BATCH.append({"fam": _fam, "pattern": "Ailk_Bjlk" if _fam != "ZZ" else "Alik_Bjlk",
        "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
        "DepthU": _du, "NLCA": -1,
        "note": "R45 virgin: NLCA=-1 (least-coalesced, never measured)"})

# PrefetchGlobalRead=2 on the larger tiles (gated by doubled LDS).
for _fam, _tile, _tt, _vw, _du in (
    ("SS", "128x128x8", "8x8", 4, 8),
    ("HH", "128x128x16", "8x8", 8, 16),
):
    PLAN_BATCH.append({"fam": _fam, "pattern": "Ailk_Bjlk",
        "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
        "DepthU": _du, "PrefetchGlobalRead": 2,
        "note": "R45 virgin: PrefetchGlobalRead=2 (2x prefetch, gated)"})

# 2026-10-21 R44/R45 (cont.) -- FractionalLoad=2 and TransposeLDS=-1, now that
# both are forwarded. FractionalLoad frees the DepthU choice on ragged M/N/K;
# TransposeLDS=-1 forces UnrollMajorLDS on the non-transposed operand
# (SolutionStructs:3874-3875) -- a real, untried knob on this part.
# NOT TransposeLDS=1: that value is the MFMA path ("TransposeLds Supports only
# in MatrixInstruction=1", SolutionStructs:4519-4521) and this device has no MFMA,
# so it yields zero solutions. The gate refuses it now.
for _fam, _tile, _tt, _vw, _du in (
    ("CC", "64x64x8", "4x4", 2, 8),
    ("ZZ", "32x32x8", "2x2", 1, 8),
    ("SS", "128x128x8", "8x8", 4, 8),
    ("HH", "128x128x16", "8x8", 8, 16),
    ("DD", "64x64x8", "4x4", 2, 8),
):
    PLAN_BATCH.append({"fam": _fam, "pattern": "Ailk_Bjlk" if _fam != "ZZ" else "Alik_Bjlk",
        "MacroTile": _tile, "ThreadTile": _tt, "VectorWidth": _vw,
        "DepthU": _du, "FractionalLoad": 2,
        "note": "R45 virgin: FractionalLoad=2 (ragged edge handling)"})
    # TransposeLDS is NOT probed: it is unreachable on this device in both of its
    # non-zero values -- 1 is the MFMA path and -1 forces UnrollMajorLDS, which
    # the classic VALU path rejects ("didn't support UnrollMajorLDS in VALU
    # mode yet", SolutionStructs:2890). The deck check found the second one on
    # 2026-10-22; the gate now refuses both.

# 2026-10-21 R47 -- the batch the *corrected* analysis asks for.
#
# §R47 re-read the corpus with the complex families scored in the unit the
# client reports (CC/ZZ are at 80-97 % of the roof, not 20 %), and with the
# tie taxonomy: 9 of the 15 ties run the floor's own config, so the delta
# there is measurement environment (17.5 points wide) and not tuning. The
# cells that really are behind are SS:256, HH:256 and CC:192, and the axes
# that have never actually been varied are StaggerU=0 (the gate used to refuse
# it), TransposeLDS (never emitted), NonTemporalC/D (never emitted) and the
# WorkGroupMapping values other than 1 and 4 (a 56-CU knob on a 7-CU part).
#
# Every row below is a CONFIG on a geometry the corpus already reaches, so the
# only new machinery is the launch itself. The batch is gate-clean by
# construction: `tests/test_generate_candidates.py` pins it.

#: The winner geometry per family, as the corpus has measured it (the cell's
#: best seed-median geometry; `kernel_db.json`). These are the geometries the
#: untried axes are worth probing on.
_R47_WINNERS: Tuple[Tuple[str, str, str, int, int], ...] = (
    ("SS", "128x128x8", "8x8", 4, 8),
    ("HH", "128x128x16", "8x8", 8, 16),
    ("DD", "64x64x8", "4x4", 2, 8),
    ("CC", "64x64x8", "4x4", 2, 8),
    ("ZZ", "32x32x8", "2x2", 1, 8),
    ("HH_HPA", "64x128x16", "4x8", 4, 16),
    ("HS_HPA", "64x128x16", "4x8", 4, 16),
)

#: (1) The WorkGroupMapping axis. The floor's configs are tuned for 56 CUs;
#: this part has 7. WGM 1 and 4 are measured, 2/3/-1/-4 are not, and the tile
#: grid on 7 CUs is exactly where the mapping matters.
for _fam, _tile, _tt, _vw, _du in _R47_WINNERS:
    for _wgm in (2, 3, -1, -4):
        PLAN_BATCH.append({
            "fam": _fam, "pattern": PATTERNS[_fam][0], "MacroTile": _tile,
            "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
            "WorkGroupMapping": _wgm,
            "note": f"R47: WGM={_wgm} on the {_fam} winner (7-CU tile grid)"})

#: (2) The axes that were never varied because they were *declared* but not
#: reachable: StaggerU=0 (the store stagger off -- the gate used to refuse it),
#: TransposeLDS=-1 (unroll-major LDS on the NT operand; 1 is the MFMA path and
#: is refused), NonTemporalC 1/2 (glc/slc on the C operand: L2 pollution
#: control on a 1 MB L2).
for _fam, _tile, _tt, _vw, _du in _R47_WINNERS:
    _base = {"fam": _fam, "pattern": PATTERNS[_fam][0], "MacroTile": _tile,
             "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du}
    PLAN_BATCH.append({**_base, "StaggerU": 0, "StaggerUMapping": 0,
                       "StaggerUStride": 0,
                       "note": f"R47: StaggerU=0 on the {_fam} winner (stagger off)"})
    PLAN_BATCH.append({**_base, "TransposeLDS": -1,
                       "note": f"R47: TransposeLDS=-1 on the {_fam} winner "
                               f"(unroll-major LDS on the NT operand)"})
    for _nt in (1, 2):
        PLAN_BATCH.append({**_base, "NonTemporalC": _nt,
                           "note": f"R47: NonTemporalC={_nt} on the {_fam} winner "
                                   f"(C-operand L2 flavour)"})

#: (3) MaxOccupancy: Tensile reserves LDS to *limit* the workgroups per CU.
#: On a 7-CU part the opposite may be wanted (or the reservation may be what
#: caps residency at the small cells), so 16 and 32 are worth one probe each.
for _fam, _tile, _tt, _vw, _du in _R47_WINNERS:
    for _mo in (16, 32):
        PLAN_BATCH.append({
            "fam": _fam, "pattern": PATTERNS[_fam][0], "MacroTile": _tile,
            "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
            "MaxOccupancy": _mo,
            "note": f"R47: MaxOccupancy={_mo} on the {_fam} winner (LDS reservation)"})

#: (4) The small cells: the *winner tile* with the thread tiles the coverage
#: map found legal, unmeasured, and adjacent to the winner
#: (`oto.harness.coverage_map`). SS:256's winner is 96x96/6x6 (412 GFLOPS) and
#: the same tile with 4x6 / 6x4 / 8x6 has never been measured; HH:256's winner
#: is 32x64/4x4 (763) and 32x64/4x8 is unmeasured; CC:192's winner is 64x64
#: and 64x64/4x2 is unmeasured; DD:192's winner is 32x32/2x2.
#: Each entry is (family, tile, thread tile, vector width, depth). The thread
#: tiles are the legal, unmeasured ones next to the winner in the coverage
#: map -- the classic load structure pins the vector width per thread tile
#: (MT1 * GLVW == TT0 * TT1 * DepthU), so some of them only exist at the
#: lower width.
_R47_SMALL_CELLS: Tuple[Tuple[str, str, str, int, int], ...] = (
    ("SS", "96x96x16", "4x6", 2, 16),
    ("SS", "96x96x16", "6x4", 2, 16),
    ("SS", "96x96x16", "8x6", 2, 16),
    ("HH", "32x64x16", "8x4", 4, 16),
    ("HH", "32x64x16", "4x8", 4, 16),
    ("HH", "32x64x16", "2x4", 2, 16),
    ("CC", "64x64x8", "4x2", 2, 8),
    ("CC", "64x64x8", "2x4", 2, 8),
    ("CC", "64x64x8", "4x8", 2, 8),
    ("DD", "32x32x8", "2x4", 2, 8),
    ("DD", "32x32x8", "4x2", 2, 8),
    ("DD", "32x32x8", "4x4", 2, 8),
)
for _fam, _tile, _tt, _vw, _du in _R47_SMALL_CELLS:
    PLAN_BATCH.append({
        "fam": _fam, "pattern": PATTERNS[_fam][0], "MacroTile": _tile,
        "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
        "note": f"R47: {_fam} small cell -- the winner tile with an "
                f"unmeasured thread tile ({_tt})"})

# 2026-10-21 R48 -- the three cells that are really behind, aimed by the
# fill/waste arithmetic (potential_configs.md R48).
#
# The graded number on a small cell is NOT the kernel's quality: the SAME
# binary that scores 412 at SS:256 scores 981 at SS:4096. What the cell costs
# is the wave quantisation (workgroups vs 7 CUs) and the edge waste (a tile
# that does not divide the shape). Both are geometry, so both are reachable:
#
#   SS:256  winner 96x96/6x6, 9 workgroups (2 waves, 64% fill) and a 1.27x
#          edge waste -> 83% of its own bound. The untried lever is the
#          REGISTER BLOCKING inside that tile: 8x6 and 6x8 keep the tile (and
#          the fill) but raise the FMA:LDS ratio from 3.0 to 3.4 per float.
#   HH:256  winner 32x64/4x4, 32 workgroups (91% fill, no waste) but only
#          2.0 FMAs per LDS float -> 64% of its bound. 8x4 and 4x8 keep the
#          workgroup count and raise the ratio to 2.67; 64x32/4x8 is the
#          transposed tile with the same 32 workgroups and a different wave
#          layout.
#   CC:192  winner 64x64/4x4, 9 workgroups (64% fill) -> 53% of its bound.
#          The lever is a tile with MORE workgroups (32x64, 64x32 -> 18 and
#          24) and the other thread tiles of 64x64.
#
# Every row is legal by the real gate (tests/test_generate_candidates.py
# pins the batch gate-clean) and every one is a *geometry* the corpus has
# never measured on that cell.
