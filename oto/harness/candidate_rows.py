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
#
# 2026-10-18: five rows that the gate refuses were removed/repointed here too
# (potential_configs.md §R24/§R27). This ladder was the *second* home of the
# dead wide tiles: SS/HH `32x32x16/2x2` at VW4/VW8 (TT 2 cannot be a multiple
# of a 4/8-wide load), CC `128x128x8/4x4` (the accumulators alone fill the 64K
# register file -> Tensile error 4; the widest legal CC tile is 128x64 with 8x4
# threads), and ZZ `128x64x8/4x2` / `64x128x8/2x4` (GLVW 1 does not divide a
# packed-2 B/A access; the widest legal ZZ tiles use 4x4). No row below is
# refused by the gate.

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
        {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 4},
        {"MacroTile": "128x128x32", "ThreadTile": "8x8", "VectorWidth": 8},
    ],
    "CC": [
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "128x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "64x128x8", "ThreadTile": "4x4", "VectorWidth": 2},
        {"MacroTile": "128x64x8", "ThreadTile": "8x4", "VectorWidth": 2},
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
        {"MacroTile": "128x32x8", "ThreadTile": "4x4", "VectorWidth": 1},
        {"MacroTile": "32x128x8", "ThreadTile": "4x4", "VectorWidth": 1},
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
    # 2026-10-20 (§R40): slot 4 restated slot 2, so the family covered only
    # three of the four contraction patterns. Winners stay in slots 1-2 (the
    # wide and narrow rows read [:2] and [0]).
    "HS_HPA": ("Ailk_Bjlk", "Alik_Bljk", "Alik_Bjlk", "Ailk_Bljk"),
}

# Target cells: family -> side list. Union of the user's three lists (far below
# ceiling / losing to the spoof floor / ORANGE), with the rest of each grid
# left alone (DD:768/1024/1365/192:768 etc stay settled). 2026-10-09: DD:256
# and HH:256 joined (§14.5 Group A wave-fill — DD:192/256 GSU2, HH:256/512 via
# 64x64 alternates only).
# 2026-10-20 (§R40): the list must cover every cell the report scores, or a
# candidate for that cell is never measured. DD's 768/1024/1365 and HH's 4096
# tie the floor but were absent, so no DD/HH row emitted here reached them.
TARGET_CELLS = {
    "SS": [256, 512, 768, 1000, 1024, 1365, 2048, 4096],
    "DD": [192, 256, 768, 1024, 1365, 2048],
    "HH": [256, 512, 1024, 2048, 4096],
    "CC": [192, 256, 512, 1024, 2048],
    "ZZ": [128, 192, 256, 512, 1024],
    "HH_HPA": [512, 1024, 2048, 4096],
    "HS_HPA": [512, 1024, 2048],
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
# tuning; `gfx90c_theoretical_limits.md` §5.1 owns that conclusion.
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
# in MatrixInstruction=1", SolutionStructs:4519-4521) and gfx90c has no MFMA,
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
    # TransposeLDS is NOT probed: it is unreachable on gfx90c in both of its
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
            "note": f"R47: WGM={_wgm} on the {fam} winner (7-CU tile grid)"})

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
                       "note": f"R47: StaggerU=0 on the {fam} winner (stagger off)"})
    PLAN_BATCH.append({**_base, "TransposeLDS": -1,
                       "note": f"R47: TransposeLDS=-1 on the {fam} winner "
                               f"(unroll-major LDS on the NT operand)"})
    for _nt in (1, 2):
        PLAN_BATCH.append({**_base, "NonTemporalC": _nt,
                           "note": f"R47: NonTemporalC={_nt} on the {fam} winner "
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
            "note": f"R47: MaxOccupancy={_mo} on the {fam} winner (LDS reservation)"})

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
_R48_SMALL_CELL_ROWS: Tuple[
        Tuple[str, str, str, int, int, str, Dict[str, Any]], ...] = (
    # SS:256 -- the 96x96 tile, other register blockings
    ("SS", "96x96x16", "8x6", 2, 16, "Ailk_Bjlk", {}),
    ("SS", "96x96x16", "6x8", 2, 16, "Ailk_Bjlk", {}),
    ("SS", "96x96x8", "8x6", 2, 8, "Ailk_Bjlk", {}),
    ("SS", "96x96x8", "6x8", 2, 8, "Ailk_Bjlk", {}),
    ("SS", "96x96x16", "4x6", 2, 16, "Ailk_Bjlk", {}),
    # HH:256 -- the 32x64 tile, other register blockings, and its transpose
    ("HH", "32x64x16", "8x4", 4, 16, "Ailk_Bjlk", {}),
    ("HH", "32x64x16", "4x8", 4, 16, "Ailk_Bjlk", {}),
    ("HH", "64x32x16", "4x8", 4, 16, "Ailk_Bjlk", {}),
    ("HH", "64x32x16", "8x4", 4, 16, "Ailk_Bjlk", {}),
    ("HH", "32x64x16", "4x4", 4, 16, "Alik_Bjlk", {}),
    # CC:192 -- more workgroups, and the other thread tiles of the winner
    ("CC", "32x64x8", "4x4", 2, 8, "Ailk_Bjlk", {}),
    ("CC", "64x32x8", "4x4", 2, 8, "Ailk_Bjlk", {}),
    ("CC", "64x64x8", "4x2", 2, 8, "Ailk_Bjlk", {}),
    ("CC", "64x64x8", "2x4", 2, 8, "Ailk_Bjlk", {}),
    ("CC", "64x64x8", "4x8", 2, 8, "Ailk_Bjlk", {}),
    ("CC", "64x64x8", "8x4", 2, 8, "Ailk_Bjlk", {}),
    ("CC", "64x64x16", "4x4", 2, 16, "Ailk_Bjlk", {}),
)
for _fam, _tile, _tt, _vw, _du, _pat, _extra in _R48_SMALL_CELL_ROWS:
    PLAN_BATCH.append({
        "fam": _fam, "pattern": _pat, "MacroTile": _tile,
        "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du, **_extra,
        "note": f"R48: {_fam} small cell -- fill/waste arithmetic, an "
                f"unmeasured geometry"})

# 2026-10-21 R49 -- the budget batch: the ranked unexplored space of the three
# ORANGE cells.
#
# The deck's new work has to fill a 10 h run, and the auto-mutator only
# contributes ~10 candidates per iteration (the 2026-10-20 run: 702 deck phases
# completed, 10 mutator phases). The coverage map says where the rest of the
# legal space is, ranked by how well each geometry's *measured neighbours*
# scored (oto.harness.coverage_map): the neighbourhood of each cell's winner,
# ordered. These are the geometries the corpus has never run on ANY cell of
# that family, so every one of them is real new work rather than a re-measure.
#
# The three cells are the only ones with headroom (SS:256 at 83 % of its own
# fill-and-waste bound, HH:256 at 64 %, CC:192 at 53 % -- potential_configs.md
# R48.2), and the ranking puts the plausible mechanisms first: the winner's own
# tile with a different register blocking, then the smaller tiles that
# multiply the workgroup count.
#
# 16 candidate(s) were dropped as gate-illegal while the batch was built
# (the load-divisibility coupling on a GLVW/VW pair); the list is the
# gate-clean remainder, so the whole batch is launchable.
_R49_UNEXPLORED: Tuple[Tuple[str, str, str, int, int], ...] = (
    ("CC", "32x32x16", "4x4", 1, 16),
    ("CC", "32x64x8", "4x4", 1, 8),
    ("CC", "32x64x16", "4x4", 1, 16),
    ("CC", "32x64x8", "4x4", 2, 8),
    ("CC", "32x64x16", "4x4", 2, 16),
    ("CC", "64x32x8", "4x4", 1, 8),
    ("CC", "64x32x16", "4x4", 1, 16),
    ("CC", "64x64x16", "2x2", 1, 16),
    ("CC", "64x64x16", "2x2", 2, 16),
    ("CC", "64x64x8", "2x4", 1, 8),
    ("CC", "64x64x16", "2x4", 1, 16),
    ("CC", "64x64x8", "2x4", 2, 8),
    ("CC", "64x64x16", "2x4", 2, 16),
    ("CC", "64x64x8", "2x8", 1, 8),
    ("CC", "64x64x16", "2x8", 1, 16),
    ("CC", "64x64x8", "2x8", 2, 8),
    ("CC", "64x64x16", "2x8", 2, 16),
    ("CC", "64x64x8", "4x2", 1, 8),
    ("CC", "64x64x16", "4x2", 1, 16),
    ("CC", "64x64x8", "4x2", 2, 8),
    ("CC", "64x64x16", "4x2", 2, 16),
    ("CC", "64x64x8", "4x8", 1, 8),
    ("CC", "64x64x16", "4x8", 1, 16),
    ("CC", "64x64x8", "4x8", 2, 8),
    ("CC", "64x64x16", "4x8", 2, 16),
    ("CC", "64x64x8", "8x2", 1, 8),
    ("CC", "64x64x16", "8x2", 1, 16),
    ("CC", "64x64x8", "8x2", 2, 8),
    ("CC", "64x64x16", "8x2", 2, 16),
    ("CC", "64x64x8", "8x4", 1, 8),
    ("CC", "64x64x16", "8x4", 1, 16),
    ("CC", "64x64x8", "8x4", 2, 8),
    ("CC", "64x64x16", "8x4", 2, 16),
    ("CC", "32x32x8", "2x4", 1, 8),
    ("CC", "32x32x16", "2x4", 1, 16),
    ("CC", "32x32x8", "2x4", 2, 8),
    ("CC", "32x32x16", "2x4", 2, 16),
    ("CC", "32x32x8", "2x8", 1, 8),
    ("CC", "32x32x16", "2x8", 1, 16),
    ("CC", "32x32x8", "2x8", 2, 8),
    ("CC", "32x32x16", "2x8", 2, 16),
    ("CC", "32x32x8", "4x2", 1, 8),
    ("CC", "32x32x16", "4x2", 1, 16),
    ("CC", "32x32x8", "4x2", 2, 8),
    ("CC", "32x32x16", "4x2", 2, 16),
    ("CC", "32x32x8", "8x2", 1, 8),
    ("CC", "32x32x16", "8x2", 1, 16),
    ("CC", "32x32x8", "8x2", 2, 8),
    ("CC", "32x32x16", "8x2", 2, 16),
    ("CC", "64x32x16", "2x2", 1, 16),
    ("CC", "64x32x16", "2x2", 2, 16),
    ("CC", "64x32x8", "2x4", 1, 8),
    ("CC", "64x32x16", "2x4", 1, 16),
    ("CC", "64x32x8", "2x4", 2, 8),
    ("CC", "64x32x16", "2x4", 2, 16),
    ("CC", "64x32x8", "2x8", 1, 8),
    ("CC", "64x32x16", "2x8", 1, 16),
    ("CC", "64x32x8", "2x8", 2, 8),
    ("CC", "64x32x16", "2x8", 2, 16),
    ("CC", "64x32x8", "4x2", 1, 8),
    ("HH", "32x64x16", "2x2", 2, 16),
    ("HH", "32x64x8", "2x8", 2, 8),
    ("HH", "32x64x16", "2x8", 2, 16),
    ("HH", "32x64x8", "4x2", 2, 8),
    ("HH", "32x64x16", "4x2", 2, 16),
    ("HH", "32x64x8", "4x4", 2, 8),
    ("HH", "32x64x16", "4x4", 2, 16),
    ("HH", "32x64x8", "4x8", 2, 8),
    ("HH", "32x64x16", "4x8", 2, 16),
    ("HH", "32x64x8", "8x2", 2, 8),
    ("HH", "32x64x16", "8x2", 2, 16),
    ("HH", "32x64x8", "8x4", 2, 8),
    ("HH", "32x64x16", "8x4", 2, 16),
    ("HH", "32x64x8", "8x4", 4, 8),
    ("HH", "32x64x16", "8x4", 4, 16),
    ("HH", "64x32x8", "4x4", 2, 8),
    ("HH", "64x32x16", "2x2", 2, 16),
    ("HH", "64x32x8", "2x4", 2, 8),
    ("HH", "64x32x8", "2x8", 2, 8),
    ("HH", "64x32x16", "2x8", 2, 16),
    ("HH", "64x32x8", "4x2", 2, 8),
    ("HH", "64x32x8", "4x8", 2, 8),
    ("HH", "64x32x16", "4x8", 2, 16),
    ("HH", "64x32x8", "4x8", 4, 8),
    ("HH", "64x32x16", "4x8", 4, 16),
    ("HH", "64x32x8", "8x2", 2, 8),
    ("HH", "64x32x16", "8x2", 2, 16),
    ("HH", "64x32x8", "8x4", 2, 8),
    ("HH", "64x32x16", "8x4", 2, 16),
    ("HH", "32x32x8", "2x4", 2, 8),
    ("HH", "32x32x16", "2x4", 2, 16),
    ("HH", "32x32x8", "2x8", 2, 8),
    ("HH", "32x32x16", "2x8", 2, 16),
    ("HH", "32x32x8", "4x2", 2, 8),
    ("HH", "32x32x16", "4x2", 2, 16),
    ("HH", "32x32x8", "8x2", 2, 8),
    ("HH", "32x32x16", "8x2", 2, 16),
    ("HH", "64x64x8", "16x4", 2, 8),
    ("HH", "64x64x16", "16x4", 2, 16),
    ("HH", "64x64x8", "16x4", 4, 8),
    ("HH", "64x64x16", "16x4", 4, 16),
    ("HH", "64x64x8", "2x4", 2, 8),
    ("HH", "64x64x16", "2x4", 2, 16),
    ("HH", "64x64x8", "2x8", 2, 8),
    ("HH", "64x64x16", "2x8", 2, 16),
    ("HH", "64x64x8", "4x16", 2, 8),
    ("HH", "64x64x16", "4x16", 2, 16),
    ("HH", "64x64x8", "4x16", 4, 8),
    ("HH", "64x64x16", "4x16", 4, 16),
    ("HH", "64x64x8", "4x2", 2, 8),
    ("HH", "64x64x16", "4x2", 2, 16),
    ("HH", "64x64x8", "4x8", 2, 8),
    ("HH", "64x64x16", "4x8", 2, 16),
    ("HH", "64x64x8", "4x8", 4, 8),
    ("HH", "64x64x8", "8x2", 2, 8),
    ("HH", "64x64x16", "8x2", 2, 16),
    ("HH", "64x64x8", "8x4", 2, 8),
    ("HH", "64x64x16", "8x4", 2, 16),
    ("HH", "64x64x8", "8x4", 4, 8),
    ("HH", "64x64x16", "8x4", 4, 16),
    ("HH", "128x128x8", "16x4", 2, 8),
    ("HH", "128x128x16", "16x4", 2, 16),
    ("HH", "128x128x8", "16x4", 4, 8),
    ("HH", "128x128x16", "16x4", 4, 16),
    ("HH", "128x128x8", "16x8", 2, 8),
    ("HH", "128x128x16", "16x8", 2, 16),
    ("HH", "128x128x8", "16x8", 4, 8),
    ("HH", "128x128x16", "16x8", 4, 16),
    ("HH", "128x128x8", "16x8", 8, 8),
    ("HH", "128x128x16", "16x8", 8, 16),
    ("HH", "128x128x8", "2x8", 2, 8),
    ("HH", "128x128x16", "2x8", 2, 16),
    ("HH", "128x128x8", "4x16", 2, 8),
    ("HH", "128x128x16", "4x16", 2, 16),
    ("HH", "128x128x8", "4x16", 4, 8),
    ("HH", "128x128x16", "4x16", 4, 16),
    ("HH", "128x128x8", "4x4", 2, 8),
    ("HH", "128x128x8", "4x8", 2, 8),
    ("HH", "128x128x16", "4x8", 2, 16),
    ("HH", "128x128x16", "4x8", 4, 16),
    ("HH", "128x128x8", "8x16", 2, 8),
    ("HH", "128x128x16", "8x16", 2, 16),
    ("HH", "128x128x8", "8x16", 4, 8),
    ("HH", "128x128x16", "8x16", 4, 16),
    ("HH", "128x128x8", "8x16", 8, 8),
    ("HH", "128x128x16", "8x16", 8, 16),
    ("HH", "128x128x8", "8x2", 2, 8),
    ("HH", "128x128x16", "8x2", 2, 16),
    ("HH", "128x128x8", "8x4", 2, 8),
    ("HH", "128x128x16", "8x4", 2, 16),
    ("HH", "128x128x16", "8x4", 4, 16),
    ("HH", "128x32x8", "4x8", 2, 8),
    ("HH", "128x32x16", "4x8", 2, 16),
    ("HH", "128x32x16", "4x8", 4, 16),
    ("HH", "128x64x8", "16x4", 2, 8),
    ("HH", "128x64x16", "16x4", 2, 16),
    ("HH", "128x64x8", "16x4", 4, 8),
    ("HH", "128x64x16", "16x4", 4, 16),
    ("HH", "128x64x8", "16x8", 2, 8),
    ("HH", "128x64x16", "16x8", 2, 16),
    ("HH", "128x64x8", "16x8", 4, 8),
    ("HH", "128x64x16", "16x8", 4, 16),
    ("HH", "128x64x8", "16x8", 8, 8),
    ("HH", "128x64x16", "16x8", 8, 16),
    ("HH", "128x64x16", "2x4", 2, 16),
    ("HH", "128x64x8", "2x8", 2, 8),
    ("HH", "128x64x16", "2x8", 2, 16),
    ("HH", "128x64x8", "4x16", 2, 8),
    ("HH", "128x64x16", "4x16", 2, 16),
    ("HH", "128x64x8", "4x16", 4, 8),
    ("HH", "128x64x16", "4x16", 4, 16),
    ("HH", "128x64x16", "4x2", 2, 16),
    ("HH", "128x64x8", "4x4", 2, 8),
    ("HH", "128x64x16", "4x4", 2, 16),
    ("HH", "128x64x8", "4x8", 2, 8),
    ("HH", "128x64x16", "4x8", 2, 16),
    ("HH", "128x64x8", "8x16", 2, 8),
    ("HH", "128x64x16", "8x16", 2, 16),
    ("HH", "128x64x8", "8x16", 4, 8),
    ("HH", "128x64x16", "8x16", 4, 16),
    ("SS", "96x96x8", "4x6", 2, 8),
    ("SS", "96x96x16", "4x6", 2, 16),
    ("SS", "96x96x8", "6x4", 2, 8),
    ("SS", "96x96x16", "6x4", 2, 16),
    ("SS", "96x96x8", "6x8", 2, 8),
    ("SS", "96x96x16", "6x8", 2, 16),
    ("SS", "96x96x8", "8x6", 2, 8),
    ("SS", "96x96x16", "8x6", 2, 16),
    ("SS", "32x32x8", "4x4", 2, 8),
    ("SS", "32x64x8", "4x4", 2, 8),
    ("SS", "32x64x16", "4x4", 2, 16),
    ("SS", "64x32x8", "4x4", 2, 8),
    ("SS", "64x64x8", "16x4", 2, 8),
    ("SS", "64x64x16", "16x4", 2, 16),
    ("SS", "64x64x8", "16x4", 4, 8),
    ("SS", "64x64x16", "16x4", 4, 16),
    ("SS", "64x64x8", "2x4", 2, 8),
    ("SS", "64x64x8", "2x8", 2, 8),
    ("SS", "64x64x16", "2x8", 2, 16),
    ("SS", "64x64x8", "4x16", 2, 8),
    ("SS", "64x64x16", "4x16", 2, 16),
    ("SS", "64x64x8", "4x16", 4, 8),
    ("SS", "64x64x16", "4x16", 4, 16),
    ("SS", "64x64x8", "4x2", 2, 8),
    ("SS", "64x64x16", "4x2", 2, 16),
    ("SS", "64x64x8", "4x8", 2, 8),
    ("SS", "64x64x16", "4x8", 2, 16),
    ("SS", "64x64x8", "4x8", 4, 8),
    ("SS", "64x64x16", "4x8", 4, 16),
    ("SS", "64x64x8", "8x2", 2, 8),
    ("SS", "64x64x16", "8x2", 2, 16),
    ("SS", "64x64x8", "8x4", 2, 8),
    ("SS", "64x64x16", "8x4", 2, 16),
    ("SS", "64x64x8", "8x4", 4, 8),
    ("SS", "64x64x16", "8x4", 4, 16),
    ("SS", "64x64x8", "8x8", 2, 8),
    ("SS", "64x64x16", "8x8", 2, 16),
    ("SS", "32x64x16", "2x2", 2, 16),
    ("SS", "32x64x8", "2x4", 2, 8),
    ("SS", "32x64x16", "2x4", 2, 16),
    ("SS", "32x64x8", "2x8", 2, 8),
    ("SS", "32x64x16", "2x8", 2, 16),
    ("SS", "32x64x8", "4x2", 2, 8),
    ("SS", "32x64x16", "4x2", 2, 16),
    ("SS", "32x64x8", "4x8", 2, 8),
    ("SS", "32x64x16", "4x8", 2, 16),
    ("SS", "32x64x8", "8x2", 2, 8),
    ("SS", "32x64x16", "8x2", 2, 16),
    ("SS", "32x64x8", "8x4", 2, 8),
    ("SS", "32x64x16", "8x4", 2, 16),
    ("SS", "32x64x8", "8x4", 4, 8),
    ("SS", "32x64x16", "8x4", 4, 16),
    ("SS", "64x32x8", "4x8", 2, 8),
    ("SS", "64x32x16", "4x8", 2, 16),
    ("SS", "64x32x8", "4x8", 4, 8),
    ("SS", "64x32x16", "4x8", 4, 16),
    ("SS", "32x32x8", "2x4", 2, 8),
    ("SS", "32x32x8", "2x8", 2, 8),
    ("SS", "32x32x16", "2x8", 2, 16),
    ("SS", "32x32x8", "4x2", 2, 8),
    ("SS", "32x32x8", "8x2", 2, 8),
    ("SS", "32x32x16", "8x2", 2, 16),
    ("SS", "96x32x8", "6x4", 2, 8),
    ("SS", "96x32x16", "6x4", 2, 16),
    ("SS", "96x48x8", "6x4", 2, 8),
    ("SS", "96x48x16", "6x4", 2, 16),
    ("SS", "96x64x8", "6x8", 2, 8),
    ("SS", "96x64x16", "6x8", 2, 16),
    ("SS", "32x96x8", "4x6", 2, 8),
    ("SS", "32x96x16", "4x6", 2, 16),
    ("SS", "48x96x16", "4x6", 2, 16),
    ("SS", "64x96x8", "8x6", 2, 8),
    ("SS", "64x96x16", "8x6", 2, 16),
    ("SS", "128x128x8", "16x4", 2, 8),
    ("SS", "128x128x16", "16x4", 2, 16),
    ("SS", "128x128x8", "16x4", 4, 8),
    ("SS", "128x128x16", "16x4", 4, 16),
    ("SS", "128x128x8", "16x8", 2, 8),
    ("SS", "128x128x16", "16x8", 2, 16),
    ("SS", "128x128x8", "16x8", 4, 8),
    ("SS", "128x128x16", "16x8", 4, 16),
    ("SS", "128x128x8", "4x16", 2, 8),
    ("SS", "128x128x16", "4x16", 2, 16),
    ("SS", "128x128x8", "4x16", 4, 8),
    ("SS", "128x128x16", "4x16", 4, 16),
    ("SS", "128x128x8", "4x8", 2, 8),
    ("SS", "128x128x16", "4x8", 2, 16),
    ("SS", "128x128x16", "4x8", 4, 16),
    ("SS", "128x128x8", "8x16", 2, 8),
    ("SS", "128x128x16", "8x16", 2, 16),
    ("SS", "128x128x8", "8x16", 4, 8),
    ("SS", "128x128x16", "8x16", 4, 16),
    ("SS", "128x128x8", "8x4", 2, 8),
    ("SS", "128x128x16", "8x4", 2, 16),
    ("SS", "128x128x16", "8x4", 4, 16),
    ("SS", "128x32x8", "8x4", 2, 8),
    ("SS", "128x32x16", "8x4", 2, 16),
    ("SS", "128x32x16", "8x4", 4, 16),
    ("SS", "128x64x8", "16x4", 2, 8),
    ("SS", "128x64x16", "16x4", 2, 16),
    ("SS", "128x64x8", "16x4", 4, 8),
    ("SS", "128x64x16", "16x4", 4, 16),
    ("SS", "128x64x8", "16x8", 2, 8),
    ("SS", "128x64x16", "16x8", 2, 16),
    ("SS", "128x64x8", "16x8", 4, 8),
    ("SS", "128x64x16", "16x8", 4, 16),
    ("SS", "128x64x16", "2x4", 2, 16),
    ("SS", "128x64x8", "2x8", 2, 8),
    ("SS", "128x64x16", "2x8", 2, 16),
    ("SS", "128x64x8", "4x16", 2, 8),
    ("SS", "128x64x16", "4x16", 2, 16),
    ("SS", "128x64x8", "4x16", 4, 8),
    ("SS", "128x64x16", "4x16", 4, 16),
    ("SS", "128x64x16", "4x2", 2, 16),
    ("SS", "128x64x8", "4x4", 2, 8),
    ("SS", "128x64x16", "4x4", 2, 16),
    ("SS", "128x64x8", "4x8", 2, 8),
    ("SS", "128x64x16", "4x8", 2, 16),
    ("SS", "128x64x8", "8x16", 2, 8),
    ("SS", "128x64x16", "8x16", 2, 16),
)
for _fam, _tile, _tt, _vw, _du in _R49_UNEXPLORED:
    PLAN_BATCH.append({
        "fam": _fam, "pattern": "Ailk_Bjlk", "MacroTile": _tile,
        "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
        "note": "R49: the ranked unexplored space of the ORANGE cell"})


# --- 2026-10-23 R50 -- the like-for-like batch (potential_configs.md §R55) ---
# The 2026-10-22 like-for-like regrade (§R50) measured the four ORANGE
# "winners" as protocol artefacts: the corpus bests of SS:256, CC:192, DD:192
# and HH:256 are single-problem-phase readings, while the floor arm was only
# ever measured under the family protocol, so each was graded WIN at
# +174-279% that a same-config A/B collapses to a tie (HH:256's 32x64x16/4x4
# read 763.4 single-problem and 194-206 family-protocol across three runs --
# same client params, 3.7-3.9x).  The batch answers with three small tiers.
#
# R50a -- iso-protocol calibration: one shapes-narrowed phase per affected
# cell, cloning the config that holds the single-problem corpus best, so one
# run measures BOTH protocols on the SAME config and the A/B verdict stops
# depending on which run happened to hold each evidence row.  WorkGroupMapping
# is stated explicitly on every clone: the single-problem-era winners ran
# WGM8/4 while the ladder emits no WGM key, so the explicit key also keeps the
# clone's config fingerprint distinct from the family-wide row it would
# otherwise collapse into.
#
# R50b (below it) -- the HPA 512-band geometry push: the only cells with
# real headroom left (38-39% of the family bar like-for-like, vs 76%+ at
# every larger size).  These rows span the family, so they re-measure the
# 1024+ winners as a stability side effect.
#
# R50c (last) -- the fill-starved micro-cube knob salvo: the five cells whose
# like-for-like state is 8-28% of bar get 1-knob variants (WGM, residency
# clamp, pads, unroll) on their measured winner geometry -- the cheapest work
# that can still move them, since the geometry itself is already at its
# fill-friendly minimum.
AUTO_EXPLICIT["SS"] += [{
    "shapes": ["256x256x256"], "pattern": "Ailk_Bjlk",
    "MacroTile": "96x96x16", "ThreadTile": "6x6",
    "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 8,
    "note": "R50a: SS:256 iso-protocol calibration, draft-42 WGM8 clone "
            "(412 single-problem vs 98 family, same config)"},
    {
    "shapes": ["256x256x256"], "pattern": "Ailk_Bjlk",
    "MacroTile": "32x64x8", "ThreadTile": "4x8",
    "VectorWidth": 4, "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
    "note": "R50a: SS:256 iso-protocol calibration, family-protocol winner"},
]
AUTO_EXPLICIT["CC"] = [{
    "shapes": ["192x192x192"], "pattern": "Ailk_Bljk",
    "MacroTile": "64x64x8", "ThreadTile": "4x4",
    "VectorWidth": 2, "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 8,
    "note": "R50a: CC:192 iso-protocol calibration, trialD1 WGM8 clone "
            "(118.2 single-problem)"},
    {
    "shapes": ["192x192x192"], "pattern": "Ailk_Bjlk",
    "MacroTile": "32x32x8", "ThreadTile": "4x4",
    "VectorWidth": 2, "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
    "note": "R50a: CC:192 iso-protocol calibration, family winner copy"},
]
AUTO_EXPLICIT["HH"] = [{
    "shapes": ["256x256x256"], "pattern": "Ailk_Bjlk",
    "MacroTile": "32x64x16", "ThreadTile": "4x4",
    "VectorWidth": 4, "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 4,
    "note": "R50a: HH:256 iso-protocol calibration, the config whose 763.4 "
            "single-problem / 194 family split proved the protocol artefact"},
]
AUTO_EXPLICIT["DD"] = [{
    "shapes": ["192x192x192"], "pattern": "Alik_Bljk",
    "MacroTile": "32x32x16", "ThreadTile": "2x2",
    "VectorWidth": 2, "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
    "note": "R50a: DD:192 iso-protocol calibration, trio-phase winner clone"},
]
AUTO_EXPLICIT["ZZ"] = [{
    "shapes": ["128x128x128"], "pattern": "Alik_Bjlk",
    "MacroTile": "32x32x16", "ThreadTile": "2x2",
    "VectorWidth": 1, "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 4,
    "note": "R50a: ZZ:128 iso-protocol calibration, single-problem winner "
            "geometry"}]

# R50b -- the HPA 512-band push.  HH_HPA/HS_HPA:512 are the two cells with
# real like-for-like headroom (38-39% of the 1118.7 GFLOPS bar at :512 while
# :1024 and up hold 123-130%).  The measured :512 winners are 64x128x16/4x8
# (HH_HPA 484, 2026-10-19) and the 128-deep variants; the unexplored legal
# space around them is what the coverage maps rank highest (HH_HPA:512 was
# 91% unexplored at 589 legal configs).  VW is capped at 4 for HS_HPA
# (operand B is fp32, 4 x 4 B == the 16 B load cap); VW8 is fp16-only
# (2 B x 8 == the cap), so it runs on HH_HPA only.
_R50_HPA: Tuple[Tuple[str, str, str, str, int, int, Dict[str, Any]], ...] = (
    ("HH_HPA", "Ailk_Bjlk", "64x64x16", "4x4", 4, 16, {}),
    ("HH_HPA", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8, {}),
    ("HH_HPA", "Ailk_Bjlk", "64x64x16", "4x4", 2, 16, {}),
    ("HH_HPA", "Ailk_Bjlk", "128x128x16", "8x8", 4, 16, {"WorkGroupMapping": 2}),
    ("HH_HPA", "Ailk_Bjlk", "128x128x16", "8x8", 8, 16, {}),
    ("HH_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 2, 8, {}),
    ("HH_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 4, 16, {"WorkGroupMapping": 2}),
    ("HH_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 4, 16, {"WorkGroupMapping": 8}),
    ("HH_HPA", "Ailk_Bjlk", "128x64x16", "8x4", 4, 16, {}),
    ("HH_HPA", "Ailk_Bjlk", "96x96x16", "6x6", 2, 16, {}),
    ("HH_HPA", "Ailk_Bjlk", "32x64x16", "4x8", 2, 16, {}),
    # HS_HPA mirrors (VW <= 4 everywhere: operand B is fp32).
    ("HS_HPA", "Ailk_Bjlk", "64x64x16", "4x4", 4, 16, {}),
    ("HS_HPA", "Ailk_Bjlk", "64x64x8", "4x4", 2, 8, {}),
    ("HS_HPA", "Ailk_Bjlk", "128x128x16", "8x8", 4, 16, {}),
    ("HS_HPA", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, {}),
    ("HS_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 2, 8, {}),
    ("HS_HPA", "Ailk_Bjlk", "64x128x16", "4x8", 4, 16, {"WorkGroupMapping": 2}),
    ("HS_HPA", "Ailk_Bjlk", "128x64x16", "8x4", 4, 16, {}),
    ("HS_HPA", "Ailk_Bjlk", "96x96x16", "6x6", 2, 16, {}),
    ("HS_HPA", "Ailk_Bjlk", "32x64x16", "4x8", 2, 16, {}),
)
for _fam, _pat, _tile, _tt, _vw, _du, _extra in _R50_HPA:
    # HPA templates default GLVW=2 (a 4 B fp16 load); anything wider must pin
    # GLVWA/B to the vector width or the load gate refuses the row.
    _glvw = ({"GlobalLoadVectorWidthA": _vw, "GlobalLoadVectorWidthB": _vw}
             if _vw > 2 else {})
    PLAN_BATCH.append({
        "fam": _fam, "pattern": _pat, "MacroTile": _tile,
        "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
        **_glvw, **_extra,
        "note": "R50b: HPA 512-band geometry push"})

# R50c -- micro-cube knob salvo on the five fill-starved cells.  The like-for-
# like winners are all single-WG-wave geometries; the remaining legal levers
# are scheduling and residency, not geometry: WorkGroupMapping order, the
# MaxOccupancy residency clamp, LdsPad bank offsets and InnerUnroll.  Each row
# is 1 knob on the measured winner tile, so any delta is attributable.
_R50_KNOBS: Tuple[Tuple[str, str, str, str, int, int, Dict[str, Any]], ...] = (
    # SS:256 -- winner 32x64x8/4x8/4/8 (129.9 family, tie like-for-like).
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"WorkGroupMapping": 2}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"WorkGroupMapping": 8}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"MaxOccupancy": 4}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"MaxOccupancy": 8}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"InnerUnroll": 2}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"NonTemporalA": 1}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"LdsPadA": 1}),
    ("SS", "Ailk_Bjlk", "32x64x8", "4x8", 4, 8, {"LdsPadB": 1}),
    # SS:512 -- 78.7% bar, weakest SS cell; WGM variants on the 128x128x8
    # winner tie-adapt tile (NonTemporal/MaxO/IU already emitted in R16).
    ("SS", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, {"WorkGroupMapping": 2}),
    ("SS", "Ailk_Bjlk", "128x128x8", "8x8", 4, 8, {"WorkGroupMapping": -4}),
    # CC:192 -- winner 32x32x8/4x4/2/8 (45.0 family).
    ("CC", "Ailk_Bjlk", "32x32x8", "4x4", 2, 8, {"WorkGroupMapping": 2}),
    ("CC", "Ailk_Bjlk", "32x32x8", "4x4", 2, 8, {"WorkGroupMapping": 8}),
    ("CC", "Ailk_Bjlk", "32x32x8", "4x4", 2, 8, {"MaxOccupancy": 8}),
    ("CC", "Ailk_Bjlk", "32x32x8", "4x4", 2, 8, {"InnerUnroll": 2}),
    ("CC", "Ailk_Bjlk", "32x32x8", "4x4", 2, 8, {"LdsPadA": 1}),
    # HH:256 -- family winner 32x64x16/4x4/4/16 (194-206 family).
    ("HH", "Ailk_Bjlk", "32x64x16", "4x4", 4, 16, {"WorkGroupMapping": 2}),
    ("HH", "Ailk_Bjlk", "32x64x16", "4x4", 4, 16, {"WorkGroupMapping": 8}),
    ("HH", "Ailk_Bjlk", "32x64x16", "4x4", 4, 16, {"MaxOccupancy": 4}),
    ("HH", "Ailk_Bjlk", "32x64x16", "4x4", 4, 16, {"MaxOccupancy": 8}),
    ("HH", "Ailk_Bjlk", "32x64x16", "4x4", 4, 16, {"InnerUnroll": 2}),
    ("HH", "Ailk_Bjlk", "32x64x16", "4x4", 4, 16, {"LdsPadA": 1}),
    # DD:192 -- winner 32x32x8/4x2/2/8 (21.1, tie like-for-like; floor 21.4).
    ("DD", "Ailk_Bjlk", "32x32x8", "4x2", 2, 8, {"WorkGroupMapping": 2}),
    ("DD", "Ailk_Bjlk", "32x32x8", "4x2", 2, 8, {"WorkGroupMapping": 8}),
    ("DD", "Ailk_Bjlk", "32x32x8", "4x2", 2, 8, {"MaxOccupancy": 8}),
    ("DD", "Ailk_Bjlk", "32x32x8", "4x2", 2, 8, {"InnerUnroll": 2}),
    ("DD", "Ailk_Bjlk", "32x32x8", "4x2", 2, 8, {"LdsPadA": 1}),
    # ZZ:128 -- 6.9 family winner 32x32x16/2x2/1/16 (WIN +40% but 28% bar).
    ("ZZ", "Alik_Bjlk", "32x32x16", "2x2", 1, 16, {"WorkGroupMapping": 2}),
    ("ZZ", "Alik_Bjlk", "32x32x16", "2x2", 1, 16, {"MaxOccupancy": 8}),
    ("ZZ", "Alik_Bjlk", "32x32x16", "2x2", 1, 16, {"InnerUnroll": 2}),
    ("ZZ", "Alik_Bjlk", "32x32x16", "2x2", 1, 16, {"LdsPadA": 1}),
)
for _fam, _pat, _tile, _tt, _vw, _du, _extra in _R50_KNOBS:
    PLAN_BATCH.append({
        "fam": _fam, "pattern": _pat, "MacroTile": _tile,
        "ThreadTile": _tt, "VectorWidth": _vw, "DepthU": _du,
        **_extra,
        "note": "R50c: micro-cube knob salvo on the like-for-like winner"})
