"""Candidate row builders, part 3: the small-cell evidence blocks.

Owns: ``_R47_WINNERS``, ``_R47_SMALL_CELLS``, ``_R48_SMALL_CELL_ROWS``,
``_R49_UNEXPLORED`` and the HPA blocks -- the evidence-derived small-cell
rows appended to ``PLAN_BATCH`` after ``_rows_frontier``. Import only after
``_rows_frontier``. See ``oto.harness.candidate_rows`` for the
consumer-facing re-exports.
"""

from __future__ import annotations

from typing import Any

from oto.harness._rows_core import AUTO_EXPLICIT, PLAN_BATCH

_R48_SMALL_CELL_ROWS: tuple[
        tuple[str, str, str, int, int, str, dict[str, Any]], ...] = (
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
_R49_UNEXPLORED: tuple[tuple[str, str, str, int, int], ...] = (
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
_R50_HPA: tuple[tuple[str, str, str, str, int, int, dict[str, Any]], ...] = (
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
_R50_KNOBS: tuple[tuple[str, str, str, str, int, int, dict[str, Any]], ...] = (
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

# R50d -- the coverage-graph hole-fill (potential_configs.md §R57).  The one
# virgin geometry class the 2026-10-22 coverage maps and the kernel_db
# census agree on: between the two measured-fast 128x128 accumulator classes
# (acc/thread 16 and 64 -- the census reads 140-201 and 120-403 across the
# measured shapes) the acc-32 rung -- ThreadTile 8x4 on a 128x128 tile, 512
# threads in one work-group -- has never been measured in either HPA family
# at any side.  R50b put TT 4x8 and 8x8 on 128-wide tiles but skipped this
# one.  The load law MT1*GLVW == TT0*TT1*DepthU admits the VW2 row outright
# (128*2 == 32*8) and, with GlobalLoadVectorWidth pinned to 4 (the R50b
# pattern), the VW4 twin (128*4 == 32*16) -- so the load width stays a
# controlled variable, not a confound.
_R50_D: tuple[tuple[str, int, int, dict[str, Any]], ...] = (
    ("HS_HPA", 2, 8, {}),
    ("HS_HPA", 4, 16, {"GlobalLoadVectorWidthA": 4, "GlobalLoadVectorWidthB": 4}),
    ("HH_HPA", 2, 8, {}),
    ("HH_HPA", 4, 16, {"GlobalLoadVectorWidthA": 4, "GlobalLoadVectorWidthB": 4}),
)
for _fam, _vw, _du, _extra in _R50_D:
    PLAN_BATCH.append({
        "fam": _fam, "pattern": "Ailk_Bjlk", "MacroTile": "128x128x8",
        "ThreadTile": "8x4", "VectorWidth": _vw, "DepthU": _du,
        **_extra,
        "note": "R50d: coverage hole-fill, the 128x128/8x4 (acc 32) class "
                "between the measured-fast acc-16 and acc-64 classes"})
