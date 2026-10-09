#!/usr/bin/env python3
"""
harness/generate_candidates.py — wide / narrow / auto candidate generator.

Builds the next-run candidate overlay for the gfx90c port, appended to the D2
seed overlay (`gfx90c_results/overlays/phases.seed.overlay.yaml`) so the next
native run merges and benchmarks every row once. Every candidate is validated
CPU-only (validate_config + occupancy + fp novelty) before it is written; a row
the run would have refused at the launch boundary is never emitted.

Three tiers, matching the wide / narrow / auto vocabulary:

  wide    architectural redesigns — MT/TT anisotropy, DepthU, VW ladder,
          WGM, per-family contraction patterns and GSU where legal. This is
          the bulk of the pool and the source of genuinely new kernels.
  narrow  1-knob neighbours around a cell's measured winner (the scheduler
          knob map), so proven tiles are bracketed by data.
  auto    evidence-derived rows: MEASURED floor winners the deck never
          expressed (spoof-steal), the stranded HH_HPA:4096 winner (N7) and
          the floor's SS:512 floor kernel (N6), plus the 2026-10-09
          beat-the-spoof batch (PLAN_BATCH — LDS pads, PGR/PLR, GLVW, NLCA
          and the CC WGM8 steal-adapt, §14.5 items 3-5).

Grid/parity model (§6.1): in-grid cells are shippable candidates (graded true).
Off-grid shapes (SS 32/64/128, DD 128 — not in FAMILY_SHAPES) are measurable
probe-only rows (graded false, phase_id prefixed `probe_`); they may never be
shipped to the produced TensileLibrary. The parity gate is untouched.

Knobs that `_write_phase_config` does not forward to Tensile are stripped here
(Group C, 2026-10-09: LdsPadA/B, AssertFree0ElementMultiple, StaggerUStride and
StoreCInUnroll ARE forwarded now, behind the ldspad_feasible legality gate, so
candidates may carry them; the strip set is empty). Idempotent: already-present
fps are excluded, so re-running appends nothing.

Usage:
    python3 harness/generate_candidates.py [--dry-run] [--max-fp N]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gfx90c_common import FAMILY_DTYPE_CHAR, FAMILY_SHAPES  # noqa: E402
from registry import fingerprint_config  # noqa: E402
from scheduler import CandidateGenerator, ldspad_feasible  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = REPO_ROOT / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"

# Builder keys that _write_phase_config forwards into Tensile ForkParameters.
_FORWARDED = {
    "MacroTile", "ThreadTile", "WorkGroup", "WorkGroupMapping", "GlobalSplitU",
    "DepthU", "VectorWidth", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
    "GlobalReduceVectorWidth", "NLCA", "PrefetchGlobalRead", "PrefetchLocalRead",
    # Group C (2026-10-09): _write_phase_config now forwards these verbatim
    # behind the ldspad_feasible legality gate, so candidates may carry them.
    # The swizzle axis (StaggerU/StaggerUMapping/StaggerUStride) is forwarded
    # as a coupled trio — see the Group C comment in port_tensile.py.
    "LdsPadA", "LdsPadB", "AssertFree0ElementMultiple", "StaggerU",
    "StaggerUMapping", "StaggerUStride", "StoreCInUnroll",
}
# builder keys that are still stripped — the writer does NOT forward them yet,
# so emitting a row that silently no-ops wastes GPU time and pollutes the
# ledger. Group C moved the pad/RCT set into _FORWARDED; anything still here is
# refused unless the caller forces it.
_NOT_FORWARDED_YET = {}

FAMILY_DTYPE = FAMILY_DTYPE_CHAR  # S/H/C/Z char per family

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


def _tile_key(mt: str, tt: str) -> str:
    return f"{mt.lower()}_tt{tt.lower()}"


def _label_for(fam: str, pattern: str, knobs: Dict[str, Any]) -> str:
    return (f"{fam}_{pattern}_mt{knobs['MacroTile']}_tt{knobs['ThreadTile']}"
            f"_vw{knobs.get('VectorWidth', 1)}_wgm{knobs.get('WorkGroupMapping', 4)}"
            f"_du{knobs.get('DepthU', 16)}_alu")


def _base_config(fam: str) -> Dict[str, Any]:
    return {
        "Architecture": "gfx90c",
        "DataType": FAMILY_DTYPE[fam],
        "FamilyLabel": fam,
        "ScheduleName": "isa",
        "ProblemType": "Contraction",
    }


def _fingerprint(config: Dict[str, Any]) -> str:
    return fingerprint_config(config)


def _load_deck_fps() -> Set[str]:
    fps: Set[str] = set()
    p = REPO_ROOT / "phases.yaml"
    if p.exists():
        for row in __yaml_load(p, fallback=[]):
            if isinstance(row, dict) and row.get("fp"):
                fps.add(row["fp"])
    return fps


def __yaml_load(path: Path, fallback: Any = []) -> Any:
    import yaml
    try:
        with open(path) as f:
            return yaml.safe_load(f) or fallback
    except Exception:
        return fallback


def _load_seed_fps() -> Set[str]:
    """fps already scheduled by the *curated* seed rows (never the generator's
    own previous appends: those are exactly what a re-run must skip deduping
    against, or wide rows colliding with the last append silently vanish)."""
    fps: Set[str] = set()
    payload = __yaml_load(OVERLAY_PATH, fallback={})
    for row in (payload.get("phases", []) or []):
        if not isinstance(row, dict) or not row.get("fp"):
            continue
        if str(row.get("origin", "")).startswith("generated_"):
            continue
        fps.add(row["fp"])
    return fps


def _strip_not_forwarded(config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    dropped = [k for k in _NOT_FORWARDED_YET if k in config]
    return {k: v for k, v in config.items() if k not in _NOT_FORWARDED_YET}, dropped


def iter_candidates() -> Iterator[Dict[str, Any]]:
    """Yield validated, fp-deduped candidate rows (open/free of overlay state).

    A candidate *phase* is one config carrying a SHAPE LIST (like the deck
    rows); a fingerprint is config-level and needs exactly one row, or the
    spread of shapes collapses to the first cell that mentions it.
    """
    sched = CandidateGenerator(REPO_ROOT, registry=None)

    seen_fp: Set[str] = set(_load_deck_fps())
    seen_fp.update(_load_seed_fps())

    # fp -> row, one per config. Two sinks so off-grid (graded False) rows are
    # keyed separately and never lose their off-grid shapes to an in-grid row.
    pool: Dict[str, Dict[str, Any]] = {}
    probe_pool: Dict[str, Dict[str, Any]] = {}

    def _offer(
        fam: str,
        tier: str,
        pattern: str,
        knobs: Dict[str, Any],
        sides: Tuple[int, ...],
        graded: bool,
        note: str = "",
        sink: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        sink = sink if sink is not None else pool
        knobs = dict(knobs)
        if "DepthU" not in knobs:
            mt_parts = [int(x) for x in re.split(r"[xX]",
                        str(knobs.get("MacroTile", "64x64x16")))]
            knobs["DepthU"] = mt_parts[2] if len(mt_parts) >= 3 else 16
        config = {**_base_config(fam), **knobs, "ContractionPattern": pattern}
        config, dropped = _strip_not_forwarded(config)
        if dropped:
            note = (note + f" [stripped {','.join(dropped)}: not forwarded]").strip()
        ok, why = sched.validate_config(config)
        if not ok:
            return None
        # Group C gate: pads/swizzle/AF0EM must also survive ldspad_feasible,
        # or the row would be refused at the launch boundary after consuming a
        # generation slot. Same CPU-only gate the writer applies.
        pad_ok, _pad_why = ldspad_feasible(config)
        if not pad_ok:
            return None
        fp = _fingerprint(config)
        existing = sink.get(fp)
        if existing is None:
            if fp in seen_fp:
                # Already scheduled by the deck or seed this run. The deck row
                # carries its own shapes, so re-offering adds nothing.
                return None
            side0 = sides[0]
            fam_key = fam.lower()
            mt = knobs["MacroTile"]
            tt = knobs["ThreadTile"]
            vw = knobs.get("VectorWidth", 1)
            du = knobs.get("DepthU", 16)
            gsu = knobs.get("GlobalSplitU", 1)
            wgm = knobs.get("WorkGroupMapping", 4)
            prefix = "probe_C" if not graded else "phase_cand"
            phase_id = (f"{prefix}_{fam_key}_{side0}_{_tile_key(mt, tt)}"
                        f"_{pattern}_vw{vw}_du{du}_g{gsu}_w{wgm}")
            # Two configs can share every id-encoded knob (e.g. the 2026-10-09
            # pad / PGR / NLCA variants of the same tile), so pin uniqueness to
            # the fingerprint tail. The prefix stays knob-decodeable.
            phase_id = f"{phase_id}_{fp[:8]}"
            row = {
                "phase_id": phase_id,
                "label": _label_for(fam, pattern, knobs),
                "dtype": FAMILY_DTYPE[fam].lower(),
                "shapes": sorted(f"{s}x{s}x{s}" for s in sides),
                "ScheduleName": "isa",
                "NumBenchmarks": 8,
                "contraction_pattern": pattern,
                "config": config,
                "fp": fp,
                "origin": "generated_" + tier,
                "graded": graded,
                "tier": tier,
            }
            if note:
                row["note"] = note
            sink[fp] = row
        else:
            existing["shapes"] = sorted(
                set(existing["shapes"]) | {f"{s}x{s}x{s}" for s in sides})
            if note and not existing.get("note"):
                existing["note"] = note
        return sink[fp] if existing is None else None

    # --- wide tier: ladder tiles x patterns x DU/GSU, one row per config ---
    # A config is shape-agnostic, so it spans every in-grid target cell of its
    # family (matching deck semantics: one phase, many exact sizes).
    for fam in TARGET_CELLS:
        ladder = LADDER.get(fam, [])
        pats = PATTERNS.get(fam, ("Ailk_Bjlk",))[:2]
        sides = tuple(TARGET_CELLS[fam])
        for tile in ladder:
            mt = tile["MacroTile"]; tt = tile["ThreadTile"]
            vw = tile["VectorWidth"]
            du_choices = [tile.get("DepthU", 8)] if "DepthU" in tile else list(DU_VARIANTS)
            gsu_choices = (tile.get("GlobalSplitU", 1) if "GlobalSplitU" in tile
                           else (1, 2, 4) if fam == "SS" else (1,))
            for pat in pats:
                for du in du_choices:
                    for gsu in gsu_choices:
                        knobs = {
                            "MacroTile": mt, "ThreadTile": tt,
                            "VectorWidth": vw, "DepthU": du,
                            "GlobalSplitU": gsu, "WorkGroupMapping": 4,
                            **(tile.get("extra") or {}),
                        }
                        row = _offer(fam, "wide", pat, knobs, sides, graded=True)
                        if row:
                            yield row
        # narrow-tier neighbours attach their cell to whatever config wins it
        yield from _narrow_row_gen(sched, fam, sides, seen_fp, pool, _offer)

    # --- auto tier: explicit evidence-derived rows ---------------------------
    for fam, specs in AUTO_EXPLICIT.items():
        for spec_ in specs:
            side = int(spec_["shapes"][0].split("x")[0])
            knobs = {k: v for k, v in spec_.items()
                     if k not in ("shapes", "pattern", "note")}
            row = _offer(fam, "auto", spec_["pattern"], knobs, (side,),
                         graded=True, note=spec_.get("note", ""))
            if row:
                yield row

    # --- auto tier: 2026-10-09 beat-the-spoof batch (PLAN_BATCH) ----------
    # Configs span the family's full TARGET_CELLS like the wide tier; every row
    # carries a knob (pads / PGR / PLR / GLVW / NLCA / WGM8) no other tier
    # emits, so fp-dedupe never collapses them into a wide row.
    for spec_ in PLAN_BATCH:
        fam = spec_["fam"]
        knobs = {k: v for k, v in spec_.items()
                 if k not in ("fam", "pattern", "note")}
        row = _offer(fam, "auto", spec_["pattern"], knobs,
                     tuple(TARGET_CELLS[fam]), graded=True,
                     note=spec_.get("note", ""))
        if row:
            yield row

    # --- probe tier: off-grid cells (graded False, kept in a separate pool) ---
    # DepthU is forced to 4 and the DD 64x64x4 / 64x128x4 tiles are excluded so
    # probe configs are structurally disjoint from the in-grid pool: the wide
    # tier only ever emits DepthU 8/16, and the two DD tiles the ladder fixes at
    # DepthU 4 are the only du-4 in-grid rows.
    for fam in PROBE_CELLS:
        ladder = LADDER.get(fam, [])
        if fam == "DD":
            ladder = [t for t in ladder
                      if t.get("MacroTile") not in ("64x64x4", "64x128x4")]
        pat = PATTERNS.get(fam, ("Ailk_Bjlk",))[0]
        sides = tuple(PROBE_CELLS[fam])
        for tile in ladder:
            knobs = {
                "MacroTile": tile["MacroTile"],
                "ThreadTile": tile["ThreadTile"],
                "VectorWidth": tile["VectorWidth"],
                "DepthU": 4,
                "GlobalSplitU": 1,
                "WorkGroupMapping": 4,
            }
            row = _offer(
                fam, "probe", pat, knobs, sides, graded=False,
                note=("off-grid probe: "
                      + f"{'/'.join(str(s) for s in sides)} not in FAMILY_SHAPES; "
                      "measurable, never shipped"),
                sink=probe_pool)
            if row:
                yield row


def _narrow_row_gen(sched, fam: str, sides: Tuple[int, ...],
                    seen_fp: Set[str], pool: Dict[str, Dict[str, Any]],
                    offer) -> Iterator[Dict[str, Any]]:
    """1-knob neighbours of each cell's deck winner (falls back to the ladder).

    Yields the neighbours as their own rows, except when the neighbour's fp
    already exists in `pool` (a wide row measures it) — then the cell is added
    to that row's shapes instead so the same config is never benchmarked twice.
    """
    deck = _deck_rows_by_family()
    ladder = LADDER.get(fam, [])
    for side in sides:
        winner = _deck_winner_for(deck, fam, side)
        if winner is None:
            if not ladder:
                continue
            winner = {"MacroTile": ladder[0]["MacroTile"],
                      "ThreadTile": ladder[0]["ThreadTile"],
                      "VectorWidth": ladder[0]["VectorWidth"],
                      "WorkGroupMapping": 4, "GlobalSplitU": 1}
        for knob in NARROW_NEIGHBOURS:
            val = winner.get(knob)
            if knob == "GlobalSplitU" and fam in ("CC", "ZZ", "HH", "HH_HPA",
                                                  "HS_HPA"):
                continue  # GSU>1 illegal on complex/HPA; banned on HH (§13.4)
            nbrs = NARROW_NEIGHBOURS[knob].get(val)
            if not nbrs:
                continue
            for nb in nbrs:
                knobs = {**winner, knob: nb}
                fp = _fingerprint({**_base_config(fam), **knobs,
                                   "ContractionPattern":
                                   _pattern_for(fam, knobs.get("MacroTile", ""))})
                if fp in pool:
                    pool[fp]["shapes"] = sorted(
                        set(pool[fp]["shapes"]) | {f"{side}x{side}x{side}"})
                    continue
                if fp in seen_fp:
                    continue
                row = offer(fam, "narrow",
                            _pattern_for(fam, knobs.get("MacroTile", "")),
                            knobs, (side,), graded=True)
                if row:
                    yield row


def _deck_rows_by_family() -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in __yaml_load(REPO_ROOT / "phases.yaml", fallback=[]):
        if not isinstance(row, dict):
            continue
        cfg = row.get("config") or {}
        fam = str(cfg.get("FamilyLabel") or row.get("label") or "").upper()
        for f in FAMILY_DTYPE_CHAR:
            if fam.startswith(f):
                fam = f
                break
        if fam in FAMILY_DTYPE_CHAR:
            rows.setdefault(fam, []).append({**row, "config": cfg})
    return rows


def _deck_winner_for(deck: Dict[str, List[Dict[str, Any]]], fam: str,
                     side: int) -> Optional[Dict[str, Any]]:
    shape = f"{side}x{side}x{side}"
    for row in deck.get(fam, []):
        if shape in (row.get("shapes") or []):
            cfg = row.get("config") or {}
            return {
                "MacroTile": cfg.get("MacroTile"),
                "ThreadTile": cfg.get("ThreadTile"),
                "VectorWidth": cfg.get("VectorWidth"),
                "WorkGroupMapping": cfg.get("WorkGroupMapping", 4),
                "GlobalSplitU": cfg.get("GlobalSplitU", 1),
            }
    return None


def _pattern_for(fam: str, mt: str) -> str:
    return PATTERNS.get(fam, ("Ailk_Bjlk",))[0]


def _write_overlay(rows: List[Dict[str, Any]], probe_rows: List[Dict[str, Any]],
                   dry_run: bool, with_probes: bool = False) -> int:
    """Append in-grid candidate rows to the persistent seed overlay.

    Probe rows (off-grid cells, graded False) are deliberately NOT appended to
    the seed overlay: the tied §6.1 parity rule
    (tests/test_library_parity.py, seed-only-extends-within-grid) pins every
    overlay row to the shipped grid, and probe cells are outside it. They are
    always recorded in the timestamped mirror, and `with_probes` opts them into
    the seed (which WILL fail the parity tests until the rule is amended).
    """
    payload = __yaml_load(OVERLAY_PATH, fallback={"phases": []})
    if not isinstance(payload, dict):
        payload = {"phases": []}
    existing_ids = {str(p.get("phase_id", "")) for p in payload.get("phases", [])}
    existing_fps = {str(p.get("fp", "")) for p in payload.get("phases", [])}
    added = [r for r in rows
             if r["phase_id"] not in existing_ids and r["fp"] not in existing_fps]
    seed_probes = probe_rows if with_probes else []
    seed_list = added + seed_probes
    if dry_run:
        return len(seed_list)
    if not seed_list:
        return 0
    payload.setdefault("phases", []).extend(seed_list)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload["note"] = (payload.get("note", "") +
                       f"\nAppended {len(seed_list)} generated candidates "
                       f"({len(added)} in-grid, {len(seed_probes)} probe) at "
                       f"{stamp} by harness/generate_candidates.py")
    import yaml
    with open(OVERLAY_PATH, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)
    # Timestamped standalone mirror (provenance / easy seed-file pruning).
    mirror = OVERLAY_PATH.parent / f"phases.candidates.{stamp}.overlay.yaml"
    mirror_payload = {
        "run_id": f"candidates-{stamp}",
        "created_at": stamp,
        "note": ("Candidate pool emitted by harness/generate_candidates.py; "
                 "probe rows (graded: false) are off-grid and must NOT be "
                 "merged into the seed overlay without amending the parity "
                 "rule. Safe to load as a run overlay, or archive after the "
                 "run and strip these phase_ids from "
                 "phases.seed.overlay.yaml to keep future runs light."),
        "phases": added,
        "probes": probe_rows,
    }
    with open(mirror, "w") as f:
        yaml.safe_dump(mirror_payload, f, sort_keys=False, default_flow_style=False)
    print(f"mirror written: {mirror.relative_to(OVERLAY_PATH.parent.parent.parent)}")
    return len(seed_list)


def _prune_candidates_from_seed(dry_run: bool = False) -> Tuple[int, int]:
    """Strip `phase_cand_*` rows from the persistent seed overlay (todo hygiene).

    The mirror note already instructs this after every candidate run: candidate
    pools grow without bound under `--auto` and their knob-encoded ids can drift
    from the `config` that is ground truth. Proven winners / accepted rows and
    `probe_*` rows are kept. State is preserved into a timestamped archive copy
    of the seed before stripping, so the action is reversible by diffing the two
    files. Returns (stripped, kept)."""
    payload = __yaml_load(OVERLAY_PATH, fallback={"phases": []})
    if not isinstance(payload, dict):
        payload = {"phases": []}
    kept, stripped = [], []
    for p in payload.get("phases", []):
        if str(p.get("phase_id", "")).startswith("phase_cand_"):
            stripped.append(p)
        else:
            kept.append(p)
    if not stripped:
        return 0, len(kept)
    if dry_run:
        return len(stripped), len(kept)
    import yaml
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = OVERLAY_PATH.parent / f"phases.cand_archive.{stamp}.overlay.yaml"
    yaml.safe_dump({"note": f"phase_cand_* rows stripped from the seed by "
                            f"--prune-candidates at {stamp}",
                    "phases": stripped},
                   open(archive, "w"), sort_keys=False, default_flow_style=False)
    payload["phases"] = kept
    payload["note"] = (payload.get("note", "") +
                       f"\nStripped {len(stripped)} phase_cand_* rows "
                       f"(archived: {archive.name}) at {stamp}")
    yaml.safe_dump(payload, open(OVERLAY_PATH, "w"),
                   sort_keys=False, default_flow_style=False)
    return len(stripped), len(kept)


def _round_robin_prune(rows: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    """Keep a fair (family, cell) share when the pool overshoots the run budget.

    Round-robin across buckets so the biggest family (SS) cannot starve the
    HPA families at the cap; removes the least-valuable rows (probe -> narrow ->
    wide, per bucket) first.
    """
    if len(rows) <= cap:
        return rows
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for r in rows:
        fam = str(r["config"].get("FamilyLabel", "")).upper() or "?"
        side = int(r["shapes"][0].split("x")[0])
        buckets.setdefault((fam, side), []).append(r)
    for lst in buckets.values():
        lst.sort(key=lambda r: {"probe": 0, "narrow": 1, "auto": 0, "wide": 2}.get(r["tier"], 3))
    kept: List[Dict[str, Any]] = []
    keys = list(buckets)
    while len(kept) < cap and buckets:
        for k in keys:
            if not buckets[k]:
                continue
            kept.append(buckets[k].pop(0))
            if len(kept) >= cap:
                break
    return kept


def _summarise(rows: List[Dict[str, Any]]) -> None:
    by_family: Dict[str, Dict[str, int]] = {}
    for r in rows:
        fam = str(r["config"].get("FamilyLabel", "")).upper() or "?"
        by_family.setdefault(fam, {}).setdefault(r["tier"], 0)
        by_family[fam][r["tier"]] += 1
    total = [0]
    for fam in sorted(by_family):
        counts = by_family[fam]
        line = "  " + fam.ljust(8) + " " + "  ".join(
            f"{k}={counts[k]}" for k in sorted(counts))
        print(line)
        total[0] += sum(counts.values())
    print(f"  TOTAL  candidates={total[0]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + count only; do not write the overlay")
    ap.add_argument("--max-fp", type=int, default=300,
                    help="cap total emitted candidates (round-robin across "
                         "family/cell buckets; default 300)")
    ap.add_argument("--with-probes", action="store_true",
                    help="append off-grid probe rows to the seed overlay too "
                         "(breaks the §6.1 parity test until the rule is amended; "
                         "probes are always mirrored regardless)")
    ap.add_argument("--prune-candidates", action="store_true",
                    help="strip phase_cand_* rows from the seed overlay "
                         "(archive first, keep probe_*/accepted rows); "
                         "overrides all generation")
    args = ap.parse_args()

    if args.prune_candidates:
        stripped, kept = _prune_candidates_from_seed(dry_run=args.dry_run)
        print(f"{'[dry-run] would strip' if args.dry_run else 'stripped'} "
              f"{stripped} phase_cand_* rows; {kept} rows kept in "
              f"{OVERLAY_PATH.name}")
        return 0

    rows: List[Dict[str, Any]] = list(iter_candidates())
    rows = _round_robin_prune(rows, args.max_fp)
    probes = [r for r in rows if not r["graded"]]
    grid_rows = [r for r in rows if r["graded"]]
    _summarise(rows)
    written = _write_overlay(grid_rows, probes, dry_run=args.dry_run,
                             with_probes=args.with_probes)
    print(f"{'[dry-run] would append' if args.dry_run else 'appended'} "
          f"{written} candidate(s) to {OVERLAY_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())