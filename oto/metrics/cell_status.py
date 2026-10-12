#!/usr/bin/env python3
"""Cell status: the RED / ORANGE / graded coverage classification.

Owns: ``classify_cell_status`` -- which contractual cells are missing, which sit
below half their realistic ceiling, and which are graded. A pure function of the
analytics list.
Does NOT own: the analytics themselves (oto.metrics.analytics), the ceilings they
are graded against (oto.device.peaks), or the report layout
(oto.metrics.report).
Public API: CellStatusMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple

from oto.device.peaks import (FAMILY_DTYPE_CHAR, FAMILY_DTYPES, FAMILY_SHAPES,
                              PEAK_GFLOPS, REALISTIC_CEILINGS)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from oto.metrics.analytics import CellAnalytics


class CellStatusMixin:
    """Coverage classification, mixed into AnalyticsEngine."""


    def classify_cell_status(
        self,
        all_analytics: List[CellAnalytics],
        red_threshold_pct: float = 50.0
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Classify the gfx900 contract cells (family x deck shape) for the report.

        The contract grid is the shipped gfx900 footprint sampled at each
        family's canonical deck shapes (FAMILY_SHAPES). A cell is:

          RED    — MISSING: no candidate measurement at (family, shape) at all.
          ORANGE — measured but the best candidate median < red_threshold_pct
                   of the family realistic ceiling.
          GREEN  — measured and at/above the threshold.

        A cell's median is the best candidate median across configs at that
        shape — the deck winner the shipped floor must be compared against.
        """
        from collections import defaultdict

        measured: Dict[str, Set[str]] = defaultdict(set)
        best_per_cell: Dict[Tuple[str, str], float] = {}

        # dtype char -> family fallback for analytics rows missing a family tag.
        # setdefault keeps the FIRST family per char, so the ambiguous 'H'
        # (HH / HH_HPA / HS_HPA) resolves to canonical HH; the HPA variants are
        # only ever distinguished by their phase_id family prefix, never by char.
        dtype_to_family = {}
        for family, ch in FAMILY_DTYPE_CHAR.items():
            dtype_to_family.setdefault(ch, family)

        for a in all_analytics:
            fam = str(a.family or "").upper()
            if fam not in FAMILY_SHAPES:
                fam = dtype_to_family.get(str(a.dtype).upper(), "")
            if not fam or fam not in FAMILY_SHAPES:
                continue
            measured[fam].add(a.shape)
            key = (fam, a.shape)
            if a.median_gflops > best_per_cell.get(key, 0.0):
                best_per_cell[key] = a.median_gflops

        def _entry(fam: str, shape: str, status: str, best: float) -> Dict[str, Any]:
            ceiling = REALISTIC_CEILINGS.get(
                fam, PEAK_GFLOPS.get(FAMILY_DTYPES.get(fam, "FP32"), 1613.0)
            )
            pct = (best / ceiling * 100.0) if ceiling > 0 else 0.0
            return {
                "family": fam,
                "shape": shape,
                "status": status,
                "median_gflops": round(best, 1),
                "pct_of_ceiling": round(pct, 1),
            }

        red: List[Dict[str, Any]] = []
        orange: List[Dict[str, Any]] = []
        green: List[Dict[str, Any]] = []

        for fam, sizes in FAMILY_SHAPES.items():
            for s in sizes:
                shape = f"{s}x{s}x{s}"
                best = best_per_cell.get((fam, shape), 0.0)
                if shape not in measured.get(fam, set()):
                    red.append(_entry(fam, shape, "MISSING", best))
                    continue
                entry = _entry(fam, shape, "GREEN", best)
                if entry["pct_of_ceiling"] < red_threshold_pct:
                    entry["status"] = "ORANGE"
                    orange.append(entry)
                else:
                    green.append(entry)

        return {"red": red, "orange": orange, "green": green}
