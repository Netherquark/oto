#!/usr/bin/env python3
"""The candidate row builders: per-family tile ladders and the auto rows.

Owns: the wide tier's data -- the per-family tile ladders, the narrow-mutation knob map (mirroring the generator's neighbour map), the evidence-derived auto rows and the beat-the-spoof batch -- plus ``_pad_rows`` (the label/phase_id encoder they all go through).
Does NOT own: the deck/seed fingerprint sets (candidate_decks), the overlay read/write (candidate_overlay), or the pruning helpers (candidate_prune).
Public API: TARGET_CELLS, NARROW_NEIGHBOURS, PATTERNS, AUTO_EXPLICIT, PLAN_BATCH, _pad_rows."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from oto.device.peaks import FAMILY_DTYPE_CHAR, FAMILY_SHAPES  # noqa: E402
from oto.ledger.registry import fingerprint_config  # noqa: E402
from oto.tensile.config_writer import NOT_FORWARDED_KNOBS  # noqa: E402

#: Family label -> the Tensile dtype char, for the generated config's
#: ``DataType``. An alias of ``FAMILY_DTYPE_CHAR`` kept because the
#: generated rows are read alongside that name.
FAMILY_DTYPE = FAMILY_DTYPE_CHAR

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = REPO_ROOT / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"


# --- per-family tile ladders ------------------------------------------------
# (MacroTile, ThreadTile) pairs are validated by the occupancy gate below; the
# ones listed are vetted against the gate (complex double caps TT at 4x4, etc).
# Duplicated here so the generator does not depend on the deck precedence
# and can add anisotropy the decks never expressed.

LADDER: Dict[str, List[Dict[str, Any]]] = {
    "SS": [
        {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 4},
        {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 4},
        {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 2},
        {"MacroTile": "96x96x16", "ThreadTile": "6x6", "VectorWidth": 2},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x128x8", "ThreadTile": "4x8", "VectorWidth": 4},
        {"MacroTile": "128x64x8", "ThreadTile": "8x4", "VectorWidth": 4},
        {"MacroTile": "64x128x16", "ThreadTile": "4x8", "VectorWidth": 2},
        {"MacroTile": "128x64x16", "ThreadTile": "8x4", "VectorWidth": 2},
        {"MacroTile": "32x64x8", "ThreadTile": "4x8", "VectorWidth": 4},
        {"MacroTile": "64x32x16", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 4},
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 4},
    ],
    "DD": [
        {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x4", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
        {"MacroTile": "128x128x4", "ThreadTile": "8x8", "VectorWidth": 1},
        {"MacroTile": "64x128x4", "ThreadTile": "4x8", "VectorWidth": 1},
        {"MacroTile": "32x64x8", "ThreadTile": "2x4", "VectorWidth": 2},
    ],
    "HH": [
        {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 8},
        {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 4},
        {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 8},
        {"MacroTile": "64x32x16", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "256x128x8", "ThreadTile": "16x8", "VectorWidth": 4},
        {"MacroTile": "128x256x8", "ThreadTile": "8x16", "VectorWidth": 4},
        {"MacroTile": "96x96x16", "ThreadTile": "6x6", "VectorWidth": 2},
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 8},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "128x128x32", "ThreadTile": "8x8", "VectorWidth": 8},
    ],
    "CC": [
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "128x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x128x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "128x128x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "32x64x16", "ThreadTile": "2x4", "VectorWidth": 2},
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
        {"MacroTile": "64x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
    ],
    "ZZ": [
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "64x64x4", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "32x32x8", "ThreadTile": "2x2", "VectorWidth": 1},
        {"MacroTile": "32x64x8", "ThreadTile": "2x4", "VectorWidth": 1},
        {"MacroTile": "64x32x8", "ThreadTile": "4x2", "VectorWidth": 1},
        {"MacroTile": "128x64x8", "ThreadTile": "4x2", "VectorWidth": 1},
        {"MacroTile": "64x128x8", "ThreadTile": "2x4", "VectorWidth": 1},
    ],
    "HH_HPA": [
        {"MacroTile": "128x64x8", "ThreadTile": "8x4", "VectorWidth": 2},
        {"MacroTile": "64x128x8", "ThreadTile": "4x8", "VectorWidth": 2},
        {"MacroTile": "128x64x16", "ThreadTile": "8x4", "VectorWidth": 4},
        {"MacroTile": "64x128x16", "ThreadTile": "4x8", "VectorWidth": 4},
        {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 4},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 4},
    ],
    "HS_HPA": [
        {"MacroTile": "128x64x16", "ThreadTile": "8x4", "VectorWidth": 4},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "128x64x8", "ThreadTile": "8x4", "VectorWidth": 2},
        {"MacroTile": "64x128x8", "ThreadTile": "4x8", "VectorWidth": 2},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x128x16", "ThreadTile": "4x8", "VectorWidth": 4},
        {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 4},
    ],
}

# Extra DepthU / WGM / GSU variation applied per tile where legal (family-aware
# legality is enforced by the gate, not by this table).
DU_VARIANTS = (8, 16)
WGM_VARIANTS = (4, 1, 8)

# Patterns per family. CC/ZZ favour the natural complex loop; SS/HH span all
# four transposes because the deck already does.
#: Builder keys the launch boundary does not forward; a candidate carrying
#: one is stripped of it at emit time and the strip is reported (never a silent
#: no-op). The single home is ``config_writer.NOT_FORWARDED_KNOBS``
#: (potential_configs.md §R16); this is the name the harness reads it under.
_NOT_FORWARDED_YET = frozenset(NOT_FORWARDED_KNOBS)

PATTERNS = {
    "SS": ("Ailk_Bjlk", "Alik_Bjlk", "Ailk_Bljk", "Alik_Bljk"),
    "DD": ("Ailk_Bjlk", "Alik_Bljk", "Alik_Bjlk"),
    "HH": ("Ailk_Bjlk", "Alik_Bjlk", "Ailk_Bljk", "Alik_Bljk"),
    "CC": ("Ailk_Bjlk", "Alik_Bjlk", "Ailk_Bljk", "Alik_Bljk"),
    "ZZ": ("Alik_Bjlk", "Ailk_Bjlk", "Alik_Bljk", "Ailk_Bljk"),
    "HH_HPA": ("Ailk_Bljk", "Alik_Bjlk", "Ailk_Bjlk", "Alik_Bljk"),
    "HS_HPA": ("Ailk_Bjlk", "Alik_Bljk", "Alik_Bjlk", "Alik_Bljk"),
}

# Target cells: family -> side list. Union of the user's three lists (far below
# ceiling / losing to the spoof floor / ORANGE), with the rest of each grid
# left alone (DD:768/1024/1365/192:768 etc stay settled). 2026-10-09: DD:256
# and HH:256 joined (§14.5 Group A wave-fill — DD:192/256 GSU2, HH:256/512 via
# 64x64 alternates only).

TARGET_CELLS = {
    "SS": [256, 512, 768, 1000, 1024, 1365, 2048, 4096],
    "DD": [192, 256, 2048],
    "HH": [256, 512, 1024, 2048],
    "CC": [192, 256, 512, 1024, 2048],
    "ZZ": [128, 192, 256, 512, 1024],
    "HH_HPA": [512, 2048, 4096],
    "HS_HPA": [512, 2048],
}

# --- narrow-mutation knob map (mirrors the generator neighbour map) ---------
NARROW_NEIGHBOURS: Dict[str, Dict[str, List[Any]]] = {
    "MacroTile": {"96x96x16": ["128x128x16", "64x64x16"],
                  "128x128x16": ["96x96x16", "64x64x16"],
                  "64x64x16": ["96x96x16", "128x128x16", "32x32x16"],
                  "32x32x16": ["64x64x16"]},
    "ThreadTile": {"6x6": ["8x8", "4x4"], "8x8": ["6x6", "4x4"],
                   "4x4": ["6x6", "8x8", "2x2"], "2x2": ["4x4"]},
    "VectorWidth": {2: [1, 4], 1: [2], 4: [2]},
    "WorkGroupMapping": {4: [8, 1], 8: [4, 1], 1: [4, 8]},
    "GlobalSplitU": {1: [2, 4], 2: [1, 4], 4: [1, 2]},
}

# --- auto rows added explicitly (evidence-derived) --------------------------
# N6  SSE:512 floor vw4 kernel (deck never ships SS:512 with the floor tile;
#     its 128x128x8/8x8/VW4 phase covers 768..4096 but not 512).
#     Ailk_Bjlk, MT128x128x8, tt8x8, VW4, DU8, GSU1, WGM4.
# N7  HH_HPA:4096 stranded iteration-9 winner (median was −4.0% of deck).
#     HH_HPA 128x128x16/8x8 VW4 DU16 GSU1 WGM4 (the D1 probe's config).
AUTO_EXPLICIT: Dict[str, List[Dict[str, Any]]] = {
    "SS": [{
        "shapes": ["512x512x512"], "pattern": "Ailk_Bjlk",
        "MacroTile": "128x128x8", "ThreadTile": "8x8",
        "VectorWidth": 4, "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
        "note": "N6: floor vw4 kernel at SS:512 (deck covers 768..4096, not 512)",
    }],
    "HH_HPA": [{
        "shapes": ["4096x4096x4096"], "pattern": "Ailk_Bjlk",
        "MacroTile": "128x128x16", "ThreadTile": "8x8",
        "VectorWidth": 4, "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 4,
        "note": "N7: stranded HH_HPA:4096 winner re-measured (-4.0% median)",
    }],
}

# --- 2026-10-09 beat-the-spoof batch (auto tier, evidence-derived) ----------
# §14.5 items 3-5 + Group C ranked probes, decked as configs carrying knobs no
# other tier emits: LdsPadA/B, PrefetchGlobalRead/PLR, GLVW and NLCA, plus the
# CC WGM8 steal-adapt. Each config spans the family's full TARGET_CELLS (deck
# semantics: one phase, many exact sizes). Every row below is gate-verified
# before emission by iter_candidates (validate_config); two decided items are
# deliberately absent because the gate refuses them:
#   * CC GSU>1 — the old "MultipleBuffer wave-fill" rung (§13.5 rung 2, §14.5
#     item 3c). Tensile's supported-gate passes complex only via
#     _GlobalAccumulation (SolutionStructs:3543-3553), which the port never
#     sets on gfx90c, so the local gate refuses.
#   * NLCA=3 on 128-width tiles — legal only where NumLoads>=3 side-wise;
#     96x96x16/6x6/VW2 is the ladder tile with exactly 3 global loads per
#     K-slice (128x128x8/VW4 has NumLoads=1, so NLCA>1 is refused there).
# ZZ pads sit on the du8 winner geometry only: the ZZ:128/256/512 winner tile
# 32x32x16 is LDS-budget-full at the truthful 16 B/element (ZZ:16 per
# FAMILY_BYTES_PER_ELEMENT), so even pad 1 would overflow the 16 KB/WG budget.
# HH GSU2 stays banned here as everywhere (§13.4); HH wave-fill runs through
# the 64x64 alternates that TARGET_CELLS now includes for HH:256.
PLAN_BATCH: List[Dict[str, Any]] = [
    # 2026-10-16 Route G — the CC:256 steal (potential_configs.md §0 R8).
    # CC:256 is the ONLY cell in the corpus that is a genuine shortcoming: native
    # 210.8 vs spoof 212.3 (TIE, −0.7 %) while both sit at 19 % of the CC
    # realistic ceiling, and native's typical kernel is 63.6 % below spoof's
    # (median basis: 50.9 vs 139.8). Every other ORANGE cell is a ceiling
    # artefact where native already wins outright.
    #
    # Stolen from the gfx900 floor winner (cells_resolved.json):
    #   MacroTile 64x64, ThreadTile 4x4, VectorWidth 2, WorkGroup 16x16x1,
    #   WorkGroupMapping 4, GlobalSplitU 1, DepthU 8,
    #   GlobalLoadVectorWidthA/B = 2/2   (measured 212.34)
    # The native winner is the same geometry one area step down (MT 32x32,
    # WG 8x8x1, no GLVW) at 193.77 — so the gap is tile AREA + load width, not
    # contraction direction (both are Ailk_Bjlk/NT).
    #
    # Port record (gfx900 → gfx90c): MT, WG and GLVW are taken verbatim because
    # they are self-consistent consequences of MT/TT/VW rather than vendor magic
    # numbers. Everything else is re-swept because the source part had 60 CUs and
    # HBM2: StaggerU (32 was a 56-CU raster choice), WGM (7 CUs wants the
    # negative I/J-swap family), LdsPad (CC never pads in the floor — a blind
    # spot shared by Tensile's own Perf/*.yaml), AF0EM/AF1EM (Tensile's recipes
    # say 4 for single; the floor ships 1, i.e. no assertion).
    #
    # All 15 rows below were gate-verified CPU-only on 2026-10-16 through BOTH
    # validate_config and ldspad_feasible at LDS 16 KB/WG (half the budget).
    # NOTE: AssertFree* is an ASSERTION, not a hint — a wrong value gives
    # silently wrong results, so 256 (divisible by 4) is the precondition and
    # the first AF row must be checked against a reference GEMM before trusted.
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4,
     "note": "R8: CC:256 steal, floor winner verbatim (gfx900 212.34)"},

    # --- the three verbatim knobs, held; each new axis probed in isolation ---
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "LdsPadB": 1,
     "note": "R8: steal + LdsPadB=1 (bank-conflict pad, CC never pads in floor)"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "LdsPadB": 2,
     "note": "R8: steal + LdsPadB=2"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "LdsPadB": 4,
     "note": "R8: steal + LdsPadB=4"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "LdsPadA": 2,
     "note": "R8: steal + LdsPadA=2"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "LdsPadA": 2, "LdsPadB": 2,
     "note": "R8: steal + LdsPadA=2 LdsPadB=2"},

    # --- the assertion lever: unlocks UseSgprForGRO (VGPR relief) ---
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4,
     "AssertFree0ElementMultiple": 4, "AssertFree1ElementMultiple": 4,
     "note": "R8: steal + AF0EM/AF1EM=4 (Tensile's own recipe for single; "
             "unlocks UseSgprForGRO). 256 is 4-divisible; verify vs reference."},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "AssertFree0ElementMultiple": 4,
     "AssertFree1ElementMultiple": 4, "LdsPadB": 2,
     "note": "R8: steal + AF4/4 + LdsPadB=2 (the two compound levers)"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "AssertFree0ElementMultiple": 4,
     "AssertFree1ElementMultiple": 4, "LdsPadB": 2,
     "PrefetchGlobalRead": 0,
     "note": "R8: steal + AF4/4 + LdsPadB=2 + PGR=0 (register relief)"},

    # --- the 7-CU occupancy cliff: fill waves without shrinking the tile ---
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1,
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "LocalSplitU": 2,
     "note": "R8: steal + LocalSplitU=2 (wave-fill at fixed tile area; the "
             "legal complex equivalent of GSU, which the gate refuses). No "
             "explicit WorkGroup: `config_writer._fork_tile` emits an explicit "
             "one verbatim and would shadow the LSU into a no-op."},

    # --- WGM: 8 is a 56-CU artefact; probe the negative I/J-swap family ---
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 8,
     "note": "R8: steal + WGM=8 (the floor's own dominant value, re-probed "
             "because 8 asks for 8 J-column workgroups on a 7-CU part)"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": -4,
     "note": "R8: steal + WGM=−4 (negative I/J-swap family, never generated)"},
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1, "WorkGroup": [16, 16, 1],
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "StaggerU": 8, "StaggerUStride": 128,
     "note": "R8: steal + StaggerU=8/Stride=128 (the live stride axis: 256 "
             "silently rounds to DepthU*bpe, 128 is genuinely distinct)"},

    # --- the compound: all four levers on the stolen geometry at once ---
    {"fam": "CC", "pattern": "Ailk_Bjlk",
     "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
     "DepthU": 8, "GlobalSplitU": 1,
     "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
     "WorkGroupMapping": 4, "AssertFree0ElementMultiple": 4,
     "AssertFree1ElementMultiple": 4, "LdsPadB": 2,
     "PrefetchGlobalRead": 0, "LocalSplitU": 2,
     "note": "R8: FULL compound — steal + AF4/4 + LdsPadB2 + PGR0 + LSU2. "
             "This is the single best candidate to beat CC:256. No explicit "
             "WorkGroup, so the LSU really lands (see the row above)."},
]

def _pad_rows(fam: str, pattern: str, tile: str, tt: str, vw: int, du: int,
              note: str) -> List[Dict[str, Any]]:
    """LdsPadA/B rows for one winner geometry: pads {1,2,4} on each side."""
    rows = []
    for p in (1, 2, 4):
        rows.append({"fam": fam, "pattern": pattern, "MacroTile": tile,
                     "ThreadTile": tt, "VectorWidth": vw, "DepthU": du,
                     "LdsPadA": p, "note": f"{note} LdsPadA={p}"})
        rows.append({"fam": fam, "pattern": pattern, "MacroTile": tile,
                     "ThreadTile": tt, "VectorWidth": vw, "DepthU": du,
                     "LdsPadB": p, "note": f"{note} LdsPadB={p}"})
    return rows


# Group C pads — CC: winner geometry 64x64x8/4x4/VW2/DU8 (the §8.6 S3 steal
# tile; also wins CC:512/1024/2048), Ailk_Bjlk (the deck/steal unroll).
PLAN_BATCH += _pad_rows(
    "CC", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8,
    "2026-10-09 S3 steal-adapt: LDS pad on the CC winner geometry (§14.5 item 4)")
# Group C pads — ZZ: winner geometry 32x32x8/2x2/VW1/DU8 (zz:192), Alik_Bjlk.
PLAN_BATCH += _pad_rows(
    "ZZ", "Alik_Bjlk", "32x32x8", "2x2", 1, 8,
    "2026-10-09 Group C: LDS pad on the ZZ du8 winner geometry (§14.5 item 4)")
# CC steal-adapt variants (§14.5 item 3): WGM8 (CC's real lever), PGR=0
# (VGPR-bound residency) and GLVW=1 (narrower loads) on the steal tile. GSU2+
# workspace is absent — gate-refused for complex on gfx90c (see table comment).
for kw, note in (
    ({"WorkGroupMapping": 8}, "S3 steal-adapt: WGM8"),
    ({"WorkGroupMapping": 8, "LdsPadA": 2}, "S3 steal-adapt: WGM8 + LdsPadA=2"),
    ({"PrefetchGlobalRead": 0}, "S3 steal-adapt: PGR=0 (VGPR relief, §14.3)"),
    ({"LdsPadA": 2, "PrefetchGlobalRead": 0}, "S3 steal-adapt: LdsPadA=2 + PGR=0"),
    ({"GlobalLoadVectorWidthA": 1, "GlobalLoadVectorWidthB": 1},
     "S3 steal-adapt: GLVW=1 (narrower global loads)"),
    ({"WorkGroupMapping": 8, "LdsPadA": 2, "PrefetchGlobalRead": 0},
     "S3 steal-adapt: WGM8 + LdsPadA=2 + PGR=0"),
):
    PLAN_BATCH.append({"fam": "CC", "pattern": "Ailk_Bjlk",
                       "MacroTile": "64x64x8", "ThreadTile": "4x4",
                       "VectorWidth": 2, "DepthU": 8, **kw, "note": note})
# ZZ residency levers: PGR=0 frees the LDS double-buffer AND the prefetch
# registers (Common.py double-prefetch) — the dual relief valve (§14.3).
for tile, tt, du, note in (
    ("32x32x8", "2x2", 8, "PGR=0 on the ZZ du8 winner geometry"),
    ("32x32x16", "2x2", 16, "PGR=0 on the ZZ:128/256/512 winner geometry"),
):
    PLAN_BATCH.append({"fam": "ZZ", "pattern": "Alik_Bjlk", "MacroTile": tile,
                       "ThreadTile": tt, "VectorWidth": 1, "DepthU": du,
                       "PrefetchGlobalRead": 0, "note": f"2026-10-09: {note}"})
# SS residency / narrower-load reserves (§14.5 item 5): PGR=0 and single-buffer
# LDS (PLR=0) on the wide VGPR-bound tile, GLVW=1, PGR=0 on the 96x96 M2
# winner, and the only NLCA=3 tile in the ladder (3 loads/K-slice).
for tile, tt, vw, du, kw, note in (
    ("128x128x8", "8x8", 4, 8, {"PrefetchGlobalRead": 0},
     "PGR=0 on the wide SS tile (VGPR-bound occupancy, §14.3)"),
    ("128x128x8", "8x8", 4, 8, {"PrefetchLocalRead": 0},
     "single-buffer LDS (PLR=0) on the wide SS tile"),
    ("128x128x8", "8x8", 4, 8, {"GlobalLoadVectorWidthA": 1},
     "GLVW=1 narrower A-loads on the wide SS tile"),
    ("96x96x16", "6x6", 2, 16, {"PrefetchGlobalRead": 0},
     "PGR=0 on the SS:256 winner geometry"),
    ("96x96x16", "6x6", 2, 16, {"NLCA": 3},
     "NLCA=3 (3 global loads/K-slice, §14.5 item 4)"),
    ("128x128x16", "8x8", 4, 16, {"PrefetchGlobalRead": 0},
     "PGR=0 on the deep-16 wide SS tile"),
):
    PLAN_BATCH.append({"fam": "SS", "pattern": "Ailk_Bjlk", "MacroTile": tile,
                       "ThreadTile": tt, "VectorWidth": vw, "DepthU": du,
                       **kw, "note": "2026-10-09: " + note})
# HH residency + the HH NLCA=3 tile (96x96x16/6x6/VW2 is the 3-load shape too).
for tile, tt, vw, du, kw, note in (
    ("128x128x16", "8x8", 8, 16, {"PrefetchGlobalRead": 0},
     "PGR=0 on the wide HH tile (VGPR-bound, §14.3)"),
    ("96x96x16", "6x6", 2, 16, {"NLCA": 3},
     "NLCA=3 (3 global loads/K-slice, §14.5 item 4)"),
    ("64x64x16", "4x4", 4, 16, {"PrefetchGlobalRead": 0},
     "PGR=0 on the HH:512 64x64 alternate"),
):
    PLAN_BATCH.append({"fam": "HH", "pattern": "Ailk_Bjlk", "MacroTile": tile,
                       "ThreadTile": tt, "VectorWidth": vw, "DepthU": du,
                       **kw, "note": "2026-10-09: " + note})
# --- Group C swizzle axis (the remaining M3 axis, guide §9) ----------------
# StaggerU spreads the K-dimension start positions across memory channels to
# break bank/cache conflicts; it is ON by default (SU=32, SUS=256) and was
# never varied. Probes: disable (SU=0, which forces SUM=0 + SUS=0), and vary
# the stagger depth (SU) x mapping (SUM) on the CC/ZZ winner geometries + the
# wide SS tile. SUS>0 must exceed 0.5*DepthU*bpe (ldspad_feasible), so the
# stride is left at the legal default 256 except where noted.
for fam, pattern, tile, tt, vw, du, rows in (
    ("CC", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8,
     (({"StaggerU": 0, "StaggerUMapping": 0, "StaggerUStride": 0},
       "swizzle off (SU=0) on the CC winner geometry"),
      ({"StaggerU": 8, "StaggerUMapping": 1},
       "swizzle SU=8 + StaggerUMapping=1 on the CC winner geometry"),
      ({"StaggerU": 16, "StaggerUMapping": 2},
       "swizzle SU=16 + StaggerUMapping=2 on the CC winner geometry"),
      ({"StaggerU": 8, "StaggerUMapping": 1, "StaggerUStride": 512},
       "swizzle SU=8 + SUM=1 + SUS=512 on the CC winner geometry"))),
    ("ZZ", "Alik_Bjlk", "32x32x8", "2x2", 1, 8,
     (({"StaggerU": 0, "StaggerUMapping": 0, "StaggerUStride": 0},
       "swizzle off (SU=0) on the ZZ winner geometry"),
      ({"StaggerU": 8, "StaggerUMapping": 1},
       "swizzle SU=8 + StaggerUMapping=1 on the ZZ winner geometry"),
      ({"StaggerU": 16, "StaggerUMapping": 2},
       "swizzle SU=16 + StaggerUMapping=2 on the ZZ winner geometry"))),
    ("SS", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8,
     (({"StaggerU": 0, "StaggerUMapping": 0, "StaggerUStride": 0},
       "swizzle off (SU=0) on the wide SS tile"),
      ({"StaggerU": 8, "StaggerUMapping": 1},
       "swizzle SU=8 + StaggerUMapping=1 on the wide SS tile"))),
):
    for kw, note in rows:
        PLAN_BATCH.append({"fam": fam, "pattern": pattern, "MacroTile": tile,
                           "ThreadTile": tt, "VectorWidth": vw, "DepthU": du,
                           **kw, "note": "2026-10-09: " + note})


# --- tie-geometry adaptation (potential_configs.md rewrite 5 §R16) ----------
# The big-shape TIEs (SS 768-4096, HH 1024-4096, and the two HPA columns) are
# ties *because* native reproduces the floor's own gfx900 geometry -- the config
# is copied across SKUs and never adapted for a 7-CU / 1 MiB-L2 part.  The
# CC:256 steal batch above is the working template: take the measured winner
# tile and apply the forwarded knobs the corpus never co-varied with it.
#
# Only knobs the launch boundary actually forwards are used, so none of these
# is a silent no-op (config_writer.FORWARDED_KNOBS): NonTemporalA/B, MaxOccupancy,
# InnerUnroll, PrefetchGlobalRead, LocalSplitU, LdsPadA/B,
# StaggerU/UMapping/UStride.  The truly-virgin axes that R15 named
# (WaveSeparateGlobalRead, 1LDSBuffer, TransposeLDS) are in
# config_writer.NOT_FORWARDED_KNOBS and are deliberately absent -- see §R16.
#
# AggressivePerfMode is forwarded but unused here: mode 2 built 0 `.hsaco` for
# every family and tile across two runs (the measurement is recorded in
# decks.py), and mode 1 is Tensile's default, so a mode-1 row would re-measure
# the base tile.  LocalSplitU=2 appears only on tiles whose load wave survives
# the extra wavefront -- LSU multiplies NumThreads (SolutionStructs:1964), so it
# is legal on some geometries and refused on others (§R23).
#
# Tiles are the per-cell measured winners (cells_resolved.full.txt), so a row
# lands on the geometry that actually ties; `_offer_row` gate-verifies each
# against validate_config and ldspad_feasible, and a refusal is reported, never
# silently dropped.
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
        ({"LocalSplitU": 2}, "LocalSplitU=2"),
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
