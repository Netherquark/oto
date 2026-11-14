#!/usr/bin/env python3
"""Cell status: the RED / ORANGE / graded coverage classification.

Owns: ``classify_cell_status`` -- which contractual cells are missing, which sit
below half their realistic ceiling, and which are graded. A pure function of the
analytics list.
Does NOT own: the analytics themselves (oto.metrics.analytics), the ceilings they
are graded against (`oto.device.loader`), or the report layout
(oto.metrics.report).

Acceptance-report colour mapping (moved here from design_language.md; the report
renders each status with a Carbon support token, the status itself is decided
here):
  RED    -> support-error    no candidate measurement at (family, shape)
  ORANGE -> support-info     measured but best candidate < 50% of the family
                             realistic ceiling
  GREEN  -> support-success  measured at/above the ceiling (reserved; the
                             report emits RED/ORANGE today)
`red_list` / `orange_list` in acceptance_report.json carry the same roles so
status is legible without colour.

Public API: CellStatusMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oto.device import loader as _loader

if TYPE_CHECKING:  # pragma: no cover - typing only
    from oto.metrics.analytics import CellAnalytics


class CellStatusMixin:
    """Coverage classification, mixed into AnalyticsEngine."""


    def classify_cell_status(
        self,
        all_analytics: list[CellAnalytics],
        red_threshold_pct: float = 50.0, profile=None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Classify gfx900 contract cells (family x deck shape) for report.
        RED=MISSING, ORANGE=measured < threshold, GREEN=at/above threshold.
        ``profile`` -- optional, ambient by default.
        """
        from collections import defaultdict
        measured: dict[str, set[str]] = defaultdict(set)
        best_per_cell: dict[tuple[str, str], float] = {}
        # dtype char -> family fallback; ambiguous 'H' resolves to HH
        dtype_to_family = {}
        for family, ch in _loader.resolve_profile(profile,).family_dtype_char.items():
            dtype_to_family.setdefault(ch, family)

        for a in all_analytics:
            fam = str(a.family or "").upper()
            if fam not in _loader.resolve_profile(profile,).family_shapes:
                fam = dtype_to_family.get(str(a.dtype).upper(), "",)
            if not fam or fam not in _loader.resolve_profile(profile,).family_shapes:
                continue
            measured[fam].add(a.shape)
            key = (fam, a.shape)
            if a.median_gflops > best_per_cell.get(key, 0.0,):
                best_per_cell[key] = a.median_gflops

        def _entry(fam: str, shape: str, status: str, best: float) -> dict[str, Any]:
            ceiling = _loader.resolve_profile(profile).realistic_ceilings.get(
                fam, _loader.resolve_profile(profile).peak_gflops.get(_loader.resolve_profile(profile).family_dtypes.get(fam, "FP32",), 1613.0,)
            ,)
            pct = (best / ceiling * 100.0) if ceiling > 0 else 0.0
            return {
                "family": fam,
                "shape": shape,
                "status": status,
                "median_gflops": round(best, 1),
                "pct_of_ceiling": round(pct, 1),
            }

        red: list[dict[str, Any]] = []
        orange: list[dict[str, Any]] = []
        green: list[dict[str, Any]] = []

        for fam, sizes in _loader.resolve_profile(profile,).family_shapes.items():
            for s in sizes:
                shape = f"{s}x{s}x{s}"
                best = best_per_cell.get((fam, shape), 0.0,)
                if shape not in measured.get(fam, set(),):
                    red.append(_entry(fam, shape, "MISSING", best))
                    continue
                entry = _entry(fam, shape, "GREEN", best)
                if entry["pct_of_ceiling"] < red_threshold_pct:
                    entry["status"] = "ORANGE"
                    orange.append(entry)
                else:
                    green.append(entry)

        return {"red": red, "orange": orange, "green": green}
