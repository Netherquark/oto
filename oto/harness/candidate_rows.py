#!/usr/bin/env python3
"""The candidate row builders: per-family tile ladders and the auto rows.

Owns: the wide tier's data -- the per-family tile ladders, the narrow-mutation knob map (mirroring the scheduler's neighbour map), the evidence-derived auto rows and the 2026-10-09 beat-the-spoof batch -- plus ``_pad_rows`` (the label/phase_id encoder they all go through).
Does NOT own: the deck/seed fingerprint sets (candidate_decks), the overlay read/write (candidate_overlay), or the pruning helpers (candidate_prune).
Public API: TARGET_CELLS, PROBE_CELLS, NARROW_NEIGHBOURS, AUTO_ROWS, BEAT_THE_SPOOF_ROWS, _pad_rows."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from oto.device.peaks import FAMILY_DTYPE_CHAR, FAMILY_SHAPES  # noqa: E402
from oto.ledger.registry import fingerprint_config  # noqa: E402

#: Family label -> the Tensile dtype char, for the generated config's
#: ``DataType``. An alias of ``FAMILY_DTYPE_CHAR`` kept because the
#: generated rows are read alongside that name.
FAMILY_DTYPE = FAMILY_DTYPE_CHAR

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = REPO_ROOT / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"


# --- per-family tile ladders ------------------------------------------------
# (MacroTile, ThreadTile) pairs are validated by the occupancy gate below; the
# ones listed are vetted against the gate (complex double caps TT at 4x4, etc).
# Duplicated here so the generator does not depend on scheduler deck precedence
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
#: Builder keys the launch boundary does not forward yet; a candidate carrying
#: one is stripped of it at emit time and the strip is reported.
_NOT_FORWARDED_YET = frozenset({
    "LdsBlockSizePerPadA", "LdsBlockSizePerPadB", "DirectToVgprA", "DirectToVgprB",
})

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

# Off-grid probe-only cells (not in FAMILY_SHAPES; cannot ship under §6.1).
PROBE_CELLS = {
    "SS": [32, 64, 128],
    "DD": [128],
}

# --- narrow-mutation knob map (mirrors the scheduler neighbour map) ---------
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
#     sets on gfx90c, so the local gate refuses (scheduler:1379-1382).
#   * NLCA=3 on 128-width tiles — legal only where NumLoads>=3 side-wise;
#     96x96x16/6x6/VW2 is the ladder tile with exactly 3 global loads per
#     K-slice (128x128x8/VW4 has NumLoads=1, so NLCA>1 is refused there).
# ZZ pads sit on the du8 winner geometry only: the ZZ:128/256/512 winner tile
# 32x32x16 is LDS-budget-full at the truthful 16 B/element (ZZ:16 per
# FAMILY_BYTES_PER_ELEMENT), so even pad 1 would overflow the 16 KB/WG budget.
# HH GSU2 stays banned here as everywhere (§13.4); HH wave-fill runs through
# the 64x64 alternates that TARGET_CELLS now includes for HH:256.
PLAN_BATCH: List[Dict[str, Any]] = []

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
# wide SS tile. SUS>0 must exceed 0.5*DepthU*bpe (ldspad_defasible), so the
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
