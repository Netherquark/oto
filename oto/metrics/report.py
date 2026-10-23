#!/usr/bin/env python3
"""Stage 7 acceptance report: the verdict compute and the JSON writer.

Owns: ``AcceptanceReporter`` -- the composition root over the section builders
(``SectionMixin``) and the HTML renderer (``HtmlMixin``), plus the compute
itself: per-family coverage against the realistic and theoretical ceilings, the
overall pass/fail gate, and the one-line summary.
Does NOT own: the payload shape (report_models), the HTML (report_html), the
static assets (report_css), or how a verdict is graded (oto.metrics.ab_audit).
Public API: AcceptanceReporter, ABVerdict, AcceptanceReport.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from oto.device.peaks import (FAMILY_DTYPES, FAMILY_SHAPES, PEAK_GFLOPS,
                              REALISTIC_CEILINGS, THEORETICAL_PEAKS)
from oto.metrics.analytics import (AnalyticsEngine, CellAnalytics,
                                   FAMILY_TO_DTYPE)
from oto.metrics.report_html import HtmlMixin
from oto.metrics.report_models import ABVerdict, AcceptanceReport
from oto.metrics.report_sections import SectionMixin

import oto.tensile.library as tlib

__all__ = ["AcceptanceReporter", "ABVerdict", "AcceptanceReport"]

#: The per-cell verdict fields serialized into the JSON report, in order. Each
#: key equals the attribute name, so the dict is built by lookup rather than by
#: 34 hand-written lines that could silently drop a field when a verdict grows
#: one. Order is the JSON key order and is part of the artifact.
_VERDICT_FIELDS = (
    "dtype", "shape", "fp", "native_median", "spoof_median", "native_best",
    "spoof_best", "native_best_median", "spoof_best_median",
    "native_worst_median", "spoof_worst_median", "agg", "native_value",
    "spoof_value", "clock_adjusted", "native_clock_coverage",
    "spoof_clock_coverage", "sclk_ref_hz", "native_clock_sclk_hz",
    "spoof_clock_sclk_hz", "native_temp_c", "spoof_temp_c",
    "native_temp_max_c", "spoof_temp_max_c", "family", "delta_pct", "tie",
    "verdict", "native_runs", "native_winner_run", "native_winner_phase",
    "n_native_runs", "n_native_kernels", "n_spoof_kernels",
)


class AcceptanceReporter(SectionMixin, HtmlMixin):
    """Stage-7 acceptance A/B compute + report payload assembly.

    One mixin per responsibility; see each module's docstring for what it owns.
    The payload dataclasses live in oto.metrics.report_models.
    """

    def __init__(self, base_dir: Path, cooldown_s: int = 30):
        self.base_dir = Path(base_dir)
        self.cooldown_s = cooldown_s

    def generate_acceptance_report(
        self,
        run_id: str,
        ab_verdicts: List[ABVerdict],
        all_analytics: List[CellAnalytics],
        red_list: List[Dict[str, Any]],
        red_threshold_pct: float = 50.0,
        family_timing: Optional[Dict[str, Dict[str, Any]]] = None,
        execution_timing: Optional[Dict[str, Any]] = None,
        orange_list: Optional[List[Dict[str, Any]]] = None,
        reference_run_id: Optional[str] = None,
        native_arm: Optional[Dict[str, Any]] = None,
        reference_floor_status: str = "not attempted",
        reference_floor_authoritative: bool = True,
    ) -> AcceptanceReport:
        """Generate final acceptance report."""
        orange_list = orange_list or []
        shipped = self._load_shipped_manifest()
        per_family_coverage = self._compute_family_coverage(all_analytics, shipped)
        overall_pass = self._compute_overall_pass(
            ab_verdicts, red_list, orange_list, red_threshold_pct, reference_run_id
        )
        summary = self._generate_summary(
            ab_verdicts, red_list, orange_list, overall_pass, reference_run_id,
            execution_timing=execution_timing
        )
        if not reference_floor_authoritative:
            summary = (
                f"PROVISIONAL FLOOR (status={reference_floor_status}): the gfx900 "
                f"reference chain did not finish, so these A/B verdicts are "
                f"indicative only and must not gate a release. {summary}"
            )

        return AcceptanceReport(
            timestamp=datetime.now().isoformat(),
            run_id=run_id,
            per_family_coverage=per_family_coverage,
            per_cell_verdicts=ab_verdicts,
            red_list=red_list,
            overall_pass=overall_pass,
            summary=summary,
            all_analytics=all_analytics,
            run_dir=str(self.base_dir / "gfx90c_runs" / run_id) if self.base_dir else None,
            family_timing=family_timing,
            execution_timing=execution_timing,
            orange_list=orange_list,
            reference_run_id=reference_run_id,
            shipped_manifest=shipped,
            native_arm=native_arm,
            reference_floor_status=reference_floor_status,
            reference_floor_authoritative=reference_floor_authoritative,
        )

    def _load_shipped_manifest(self) -> Dict[str, Any]:
        """Pinned (scan-once) gfx900 shipped-library manifest for this repo."""
        try:
            return tlib.load_shipped_manifest(self.base_dir)
        except Exception:
            return {"expected_kernels": {}, "total_shipped_kernels": 0}

    def _family_cells(
        self,
        all_analytics: List[CellAnalytics],
        family: str,
        fam_lower: str,
        short: Optional[str],
    ) -> List[CellAnalytics]:
        """Cells belonging to `family` (explicit prefix or dtype fallback)."""
        family_cells = [a for a in all_analytics
                        if str(a.family or "").upper() == family]
        if not family_cells:
            family_cells = [a for a in all_analytics
                            if str(a.dtype or "").upper() == str(short or "").upper()
                            or str(a.dtype or "").upper() == family]
        return family_cells

    def _by_size_breakdown(
        self,
        family_cells: List[CellAnalytics],
        ceiling: float,
        theoretical: float,
    ) -> Dict[str, Dict[str, Any]]:
        """Per-kernel-size bucket: cells, best_median and % of ceiling/theoretical."""
        by_size: Dict[str, Dict[str, Any]] = {}
        for a in family_cells:
            size = self._kernel_size_from_shape(a.shape)
            bucket = by_size.setdefault(size, {"cells": 0, "best_median": 0.0})
            bucket["cells"] += 1
            bucket["best_median"] = max(bucket["best_median"], a.median_gflops)
        sorted_sizes = sorted(by_size.items(),
                              key=lambda kv: (int(kv[0]) if kv[0].isdigit() else 10 ** 9, kv[0]))
        for _, bucket in sorted_sizes:
            bucket["pct_of_ceiling"] = (bucket["best_median"] / ceiling * 100.0) if ceiling > 0 else 0.0
            bucket["pct_of_theoretical"] = (bucket["best_median"] / theoretical * 100.0) if theoretical > 0 else 0.0
        return dict(sorted_sizes)

    def _compute_family_coverage(
        self,
        all_analytics: List[CellAnalytics],
        shipped: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compute per-family coverage of the gfx900 contract deck.

        The contract deck is each family's canonical FAMILY_SHAPES cube grid
        (the cells the acceptance report classifies RED/ORANGE/GREEN).
        Numerator = distinct *deck cells* measured; denominator = len(deck).
        The shipped gfx900 footprint (expected_kernels from the pinned dat
        manifest) is reported separately as an informational `footprint_pct`,
        not as the coverage gate.
        """
        shipped = shipped or self._load_shipped_manifest()
        expected_kernels = shipped.get("expected_kernels", {})
        expected_families = ["CC", "DD", "ZZ", "HH", "HH_HPA", "HS_HPA", "SS"]

        coverage = {}
        for family in expected_families:
            coverage[family] = self._family_coverage_entry(
                family, all_analytics, expected_kernels)
        return coverage

    def _family_coverage_entry(
        self,
        family: str,
        all_analytics: List[CellAnalytics],
        expected_kernels: Dict[str, int],
    ) -> Dict[str, Any]:
        fam_lower = family.lower()
        short = FAMILY_TO_DTYPE.get(fam_lower)

        # Match by explicit family prefix first (distinguishes HH / HH_HPA / HS_HPA),
        # fall back to single-letter dtype / family name for cells that carry
        # no family tag (older runs / aggregate_by_cell path).
        # Case-insensitive: CellAnalytics.family is canonical UPPERCASE
        # (analytics.aggregate_by_cell_typecode uppercases the typecode
        # family), while older runs carry lowercase families. Comparing
        # `a.family == fam_lower` silently emptied the HH_HPA / HS_HPA
        # buckets, whose dtype fallback then grabbed every packed-FP16 HH
        # cell and reported 2749 GFLOPS as "170% of the HPA ceiling".
        family_cells = self._family_cells(all_analytics, family, fam_lower, short)

        ceiling = REALISTIC_CEILINGS.get(family, PEAK_GFLOPS.get(FAMILY_DTYPES.get(family, "FP32"), 1613.0))
        theoretical = THEORETICAL_PEAKS.get(family, PEAK_GFLOPS.get(FAMILY_DTYPES.get(family, "FP32"), 1613.0))
        best_median = max([a.median_gflops for a in family_cells]) if family_cells else 0.0

        # Contract deck: distinct family deck shapes measured (the cells the
        # acceptance grid classifies), distinct from the config-cell count.
        deck_sizes = FAMILY_SHAPES.get(family, [])
        deck_shapes = {f"{s}x{s}x{s}" for s in deck_sizes}
        measured_shapes = {a.shape for a in family_cells}
        deck_cells_measured = len(measured_shapes & deck_shapes)

        by_size = self._by_size_breakdown(family_cells, ceiling, theoretical)

        exp = expected_kernels.get(family, 0)
        return {
            "expected_kernels": exp,
            "deck_cells_measured": deck_cells_measured,
            "deck_cells": len(deck_shapes),
            "coverage_pct": (deck_cells_measured / len(deck_shapes) * 100.0) if deck_shapes else 0.0,
            "measured_cells": len(family_cells),
            "footprint_pct": min(100.0, (len(family_cells) / exp * 100.0) if exp > 0 else 0.0),
            "best_median": best_median,
            "ceiling_gflops": ceiling,
            "theoretical_peak_gflops": theoretical,
            "pct_of_theoretical": (best_median / theoretical * 100.0) if theoretical > 0 else 0.0,
            "by_size": by_size,
        }

    def _kernel_size_from_shape(self, shape: str) -> str:
        """Extract a kernel size label from a problem shape.

        Cubic GEMM shapes (MxMxM) report the cube side; non-cubic / GEMV shapes
        report the leading (M) dimension so 32x4096x1 → 32, 64x4096x1 → 64.
        """
        try:
            m = str(shape).split("x")[0].strip()
            return str(int(m))
        except (ValueError, IndexError):
            return "?"

    def _compute_overall_pass(
        self,
        ab_verdicts: List[ABVerdict],
        red_list: List[Dict[str, Any]],
        orange_list: List[Dict[str, Any]],
        red_threshold_pct: float = 50.0,
        reference_run_id: Optional[str] = None
    ) -> bool:
        """Pass only if every gfx900 contract cell is covered and at/above threshold.

        red_list = MISSING cells (no measurement), orange_list = measured but
        below the acceptance ceiling threshold. Both are blocking. With no
        recalled shipped reference floor there is no comparison basis, so the
        run can never pass ("no data" is not a pass).
        """
        if not reference_run_id:
            return False

        if not ab_verdicts and not red_list and not orange_list:
            return True

        wins = sum(1 for v in ab_verdicts if v.verdict == "WIN")
        ties = sum(1 for v in ab_verdicts if v.verdict == "TIE")
        losses = sum(1 for v in ab_verdicts if v.verdict == "LOSS")

        if losses > (wins + ties):
            return False

        if red_list:
            return False

        for cell in orange_list:
            if cell.get("pct_of_ceiling", 0.0) < red_threshold_pct:
                return False

        return True

    def _generate_summary(
        self,
        ab_verdicts: List[ABVerdict],
        red_list: List[Dict[str, Any]],
        orange_list: List[Dict[str, Any]],
        overall_pass: bool,
        reference_run_id: Optional[str] = None,
        red_threshold_pct: float = 50.0,
        execution_timing: Optional[Dict[str, Any]] = None
    ) -> str:
        wins = sum(1 for v in ab_verdicts if v.verdict == "WIN")
        ties = sum(1 for v in ab_verdicts if v.verdict == "TIE")
        losses = sum(1 for v in ab_verdicts if v.verdict == "LOSS")

        status = "PASS" if overall_pass else "FAIL"
        if reference_run_id:
            ref = f" (ref {reference_run_id})"
        else:
            ref = " (no shipped gfx900 reference floor yet — run --gfx900-reference or --auto)"
        if not ab_verdicts:
            return (
                f"Acceptance {status}: no native-vs-spoof pairs could be formed{ref}. "
                f"{len(red_list)} RED (missing) / {len(orange_list)} ORANGE cells. "
                f"An all-zero coverage table here means the native arm is empty, not that "
                f"the hardware measured zero."
            )
        timing = ""
        native = ((execution_timing or {}).get("native_run") or {})
        if native.get("elapsed_human") and native["elapsed_human"] != "unknown":
            timing = f" Execution time: {native['elapsed_human']}."
        elif native.get("in_flight"):
            timing = " Execution time: still running."
        return (
            f"Acceptance {status}: {wins} WIN / {ties} TIE / {losses} LOSS vs "
            f"gfx900 shipped floor{ref}. {len(red_list)} RED (missing) / "
            f"{len(orange_list)} ORANGE (<{int(red_threshold_pct)}% ceiling) cells."
            f"{timing}"
        )

    def write_report(self, report: AcceptanceReport, output_path: Optional[Path] = None) -> None:
        """Write acceptance report to JSON and HTML files."""
        if output_path is None:
            output_path = self.base_dir / "gfx90c_results" / "acceptance_report.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize all_analytics minimally for the "Problem space explored" section
        # Only the fields needed: dtype, shape, family
        all_analytics_serialized = []
        if report.all_analytics:
            for a in report.all_analytics:
                all_analytics_serialized.append({
                    "dtype": a.dtype,
                    "shape": a.shape,
                    "family": a.family,
                })

        report_dict = {
            "timestamp": report.timestamp,
            "run_id": report.run_id,
            "per_family_coverage": report.per_family_coverage,
            "per_cell_verdicts": [
                {f: getattr(v, f) for f in _VERDICT_FIELDS}
                for v in report.per_cell_verdicts
            ],
            "red_list": report.red_list,
            "orange_list": report.orange_list,
            "execution_timing": report.execution_timing,
            "family_timing": report.family_timing,
            "reference_run_id": report.reference_run_id,
            "native_arm": report.native_arm,
            "shipped_manifest": {
                "total_shipped_kernels": (report.shipped_manifest or {}).get("total_shipped_kernels", 0),
                "expected_kernels": (report.shipped_manifest or {}).get("expected_kernels", {}),
                "rocm_prefixes": (report.shipped_manifest or {}).get("rocm_prefixes", []),
                "generated_at": (report.shipped_manifest or {}).get("generated_at", ""),
            },
            "all_analytics": all_analytics_serialized,
            "overall_pass": report.overall_pass,
            "summary": report.summary
        }

        with open(output_path, "w") as f:
            json.dump(report_dict, f, indent=2)

        html_path = output_path.with_suffix(".html")
        self.write_html_report(report, html_path)

