#!/usr/bin/env python3
"""
report.py — Stage 7: Acceptance A/B & Final Report

Scoped native-vs-shipped-floor A/B; per-family acceptance report.
"""

import json
import csv
import statistics
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from gfx90c_common import PEAK_GFLOPS, FAMILY_DTYPES, THEORETICAL_PEAKS, FAMILY_SHAPES, REALISTIC_CEILINGS
from analytics import AnalyticsEngine, CellAnalytics, FAMILY_TO_DTYPE
from policy import aggregate_cell
import tensile_library as tlib


@dataclass
class ABVerdict:
    """Result of native-vs-shipped-floor A/B comparison."""
    dtype: str
    shape: str
    native_median: float
    spoof_median: float
    delta_pct: float
    tie: bool
    verdict: str  # "WIN", "TIE", "LOSS"
    fp: str = ""  # spoof entity fingerprint (config) being compared
    family: str = ""  # family from the spoof phase (SS/DD/HH/HH_HPA/HS_HPA/CC/ZZ)
    native_best: float = 0.0
    spoof_best: float = 0.0
    native_best_median: float = 0.0  # deck winner's per-kernel median
    spoof_best_median: float = 0.0
    native_worst_median: float = 0.0  # deck's weakest kernel (dominance basis)
    spoof_worst_median: float = 0.0
    native_value: float = 0.0  # the two operands actually compared
    spoof_value: float = 0.0
    agg: str = ""  # comparison basis these operands came from
    clock_adjusted: bool = False  # both arms really had per-phase clock data
    native_clock_coverage: float = 0.0  # fraction of native samples clocked
    spoof_clock_coverage: float = 0.0
    sclk_ref_hz: float = 0.0  # shared reference clock both arms normalized TO
    native_clock_sclk_hz: float = 0.0  # clock the winning native kernel ran at
    spoof_clock_sclk_hz: float = 0.0
    # Thermal context for the same busy samples the clocks came from. Reported
    # alongside the clock, never folded into it: core clock is the channel
    # temperature acts through, so a second temperature factor would
    # double-count (see port_tensile.THERMAL_MAX_C).
    native_temp_c: Optional[float] = None  # median die temp, winning native phase
    spoof_temp_c: Optional[float] = None
    native_temp_max_c: Optional[float] = None
    spoof_temp_max_c: Optional[float] = None
    native_runs: List[str] = field(default_factory=list)
    native_winner_run: str = ""  # run that produced this cell's best native sample
    native_winner_phase: str = ""
    n_native_runs: int = 0
    n_native_kernels: int = 0
    n_spoof_kernels: int = 0


@dataclass
class AcceptanceReport:
    """Final acceptance report."""
    timestamp: str
    run_id: str
    per_family_coverage: Dict[str, Dict[str, Any]]
    per_cell_verdicts: List[ABVerdict]
    red_list: List[Dict[str, Any]]
    overall_pass: bool
    summary: str
    all_analytics: List[CellAnalytics] = field(default_factory=list)
    run_dir: Optional[str] = None
    family_timing: Optional[Dict[str, Dict[str, Any]]] = None
    # Execution time. family_timing is per-family phase cost; this is the
    # wall-clock cost of the run and of the reference chain, which are
    # different numbers for a resumed floor and must not be conflated.
    execution_timing: Optional[Dict[str, Any]] = None
    orange_list: List[Dict[str, Any]] = field(default_factory=list)
    reference_run_id: Optional[str] = None
    shipped_manifest: Optional[Dict[str, Any]] = None
    native_arm: Optional[Dict[str, Any]] = None
    # Provenance of the A/B floor. A floor that never finished is not evidence,
    # so the report must say so rather than letting its verdicts read as final.
    reference_floor_status: str = "not attempted"
    reference_floor_authoritative: bool = True


class AcceptanceReporter:
    """Stage 7 acceptance A/B and final report engine."""

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
        not as the coverage gate — measuring N deck shapes against thousands of
        shipped kernels would cap coverage at a meaningless ~1%.
        """
        shipped = shipped or self._load_shipped_manifest()
        expected_kernels = shipped.get("expected_kernels", {})
        expected_families = ["CC", "DD", "ZZ", "HH", "HH_HPA", "HS_HPA", "SS"]

        coverage = {}
        for family in expected_families:
            fam_lower = family.lower()
            # Match by explicit family prefix first (distinguishes HH / HH_HPA / HS_HPA),
            # fall back to single-letter dtype / family name for cells that carry
            # no family tag (older runs / aggregate_by_cell path).
            family_cells = [a for a in all_analytics
                            if a.family == fam_lower]
            if not family_cells:
                short = FAMILY_TO_DTYPE.get(fam_lower)
                family_cells = [a for a in all_analytics
                                if a.dtype == short or a.dtype == family]

            ceiling = REALISTIC_CEILINGS.get(family, PEAK_GFLOPS.get(FAMILY_DTYPES.get(family, "FP32"), 1613.0))
            theoretical = THEORETICAL_PEAKS.get(family, PEAK_GFLOPS.get(FAMILY_DTYPES.get(family, "FP32"), 1613.0))
            best_median = max([a.median_gflops for a in family_cells]) if family_cells else 0.0

            # Contract deck: distinct family deck shapes measured (the cells the
            # acceptance grid classifies), distinct from the config-cell count.
            deck_sizes = FAMILY_SHAPES.get(family, [])
            deck_shapes = {f"{s}x{s}x{s}" for s in deck_sizes}
            measured_shapes = {a.shape for a in family_cells}
            deck_cells_measured = len(measured_shapes & deck_shapes)

            # Per-kernel-size breakdown (256/512/1024/2048/... cube sides, GEMV M dim).
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

            exp = expected_kernels.get(family, 0)
            coverage[family] = {
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
                "by_size": dict(sorted_sizes),
            }

        return coverage

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

        report_dict = {
            "timestamp": report.timestamp,
            "run_id": report.run_id,
            "per_family_coverage": report.per_family_coverage,
            "per_cell_verdicts": [
                {
                    "dtype": v.dtype,
                    "shape": v.shape,
                    "fp": v.fp,
                    "native_median": v.native_median,
                    "spoof_median": v.spoof_median,
                    "native_best": v.native_best,
                    "spoof_best": v.spoof_best,
                    "native_best_median": v.native_best_median,
                    "spoof_best_median": v.spoof_best_median,
                    "native_worst_median": v.native_worst_median,
                    "spoof_worst_median": v.spoof_worst_median,
                    "agg": v.agg,
                    "native_value": v.native_value,
                    "spoof_value": v.spoof_value,
                    "clock_adjusted": v.clock_adjusted,
                    "native_clock_coverage": v.native_clock_coverage,
                    "spoof_clock_coverage": v.spoof_clock_coverage,
                    "sclk_ref_hz": v.sclk_ref_hz,
                    "native_clock_sclk_hz": v.native_clock_sclk_hz,
                    "spoof_clock_sclk_hz": v.spoof_clock_sclk_hz,
                    "native_temp_c": v.native_temp_c,
                    "spoof_temp_c": v.spoof_temp_c,
                    "native_temp_max_c": v.native_temp_max_c,
                    "spoof_temp_max_c": v.spoof_temp_max_c,
                    "family": v.family,
                    "delta_pct": v.delta_pct,
                    "tie": v.tie,
                    "verdict": v.verdict,
                    "native_runs": v.native_runs,
                    "native_winner_run": v.native_winner_run,
                    "native_winner_phase": v.native_winner_phase,
                    "n_native_runs": v.n_native_runs,
                    "n_native_kernels": v.n_native_kernels,
                    "n_spoof_kernels": v.n_spoof_kernels,
                }
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
            "overall_pass": report.overall_pass,
            "summary": report.summary
        }

        with open(output_path, "w") as f:
            json.dump(report_dict, f, indent=2)

        html_path = output_path.with_suffix(".html")
        self.write_html_report(report, html_path)

    def write_html_report(self, report: AcceptanceReport, html_path: Path) -> None:
        """Generate rich inline HTML dashboard for acceptance report.

        Visual language: IBM Carbon (see design_language.md). Semantic tokens
        power both light and dark themes via a data-theme attribute, defaulting
        to the OS preference. Dark mode uses strict inverse layering
        (#161616 → #262626 → #393939) with restrained borders.
        """
        now = report.timestamp
        status_badge = "Pass" if report.overall_pass else "Fail"
        status_class = "tag-pass" if report.overall_pass else "tag-fail"

        verdict_families = {}  # family -> list of row html fragments
        for v in report.per_cell_verdicts:
            if v.verdict == "WIN":
                v_cls, v_color = "tag-win", "var(--support-success)"
            elif v.verdict == "TIE":
                v_cls, v_color = "tag-tie", "var(--support-info)"
            else:
                v_cls, v_color = "tag-loss", "var(--support-error)"
            row = f"""
            <tr>
                <td><code>{v.dtype}</code></td>
                <td class="mono strong">{v.shape}</td>
                <td class="mono secondary" title="spoof entity config fingerprint">{v.fp[:10]}{'…' if len(v.fp) > 10 else ''}</td>
                <td class="num strong">{v.native_value:.1f}</td>
                <td class="num secondary">{v.spoof_value:.1f}</td>
                <td class="num strong" style="color: {v_color};">{v.delta_pct:+.1f}%</td>
                <td><span class="tag {v_cls}">{v.verdict}</span></td>
            </tr>
            """
            verdict_families.setdefault(v.family or v.dtype or "Unknown", []).append(row)
        agg_used = report.per_cell_verdicts[0].agg if report.per_cell_verdicts else ""
        native_col, spoof_col = self._basis_headers(agg_used)
        verdict_sections = ""
        for fam in sorted(verdict_families):
            fam_rows = "".join(verdict_families[fam])
            verdict_sections += f"""
        <section class="section">
            <h2 class="section-title">Native vs spoof A/B &mdash; {fam}</h2>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Dtype</th>
                            <th>Problem shape</th>
                            <th>Spoof entity (config)</th>
                            <th>{native_col}</th>
                            <th>{spoof_col}</th>
                            <th>Delta (%)</th>
                            <th>Verdict</th>
                        </tr>
                    </thead>
                    <tbody>{fam_rows}
                    </tbody>
                </table>
            </div>
        </section>
        """

        # Build family rows with a dynamic "vs acceptance ceiling" scale:
        # scale = max(100%, max measured) so values >100% are never clipped and the
        # actual value stays visible; a marker line shows where 100% sits.
        # Both bar columns (ceiling utilization and % of theoretical) get their own
        # dynamic scale + 100% marker, and the per-kernel-size detail rows reuse the
        # same scales so every bar stays directly comparable and nothing is clipped.
        family_data = []
        size_data: Dict[str, List[Tuple[Any, ...]]] = {}
        for fam, cov in report.per_family_coverage.items():
            best = cov.get("best_median", 0.0)
            ceil = cov.get("ceiling_gflops", 1118.7)
            theo = cov.get("theoretical_peak_gflops", 0.0) or ceil
            pct = (best / ceil * 100.0) if ceil > 0 else 0.0
            pct_theo = (best / theo * 100.0) if theo > 0 else 0.0
            family_data.append((fam, cov, best, ceil, theo, pct, pct_theo))

            sizes = []
            for size_key, s in sorted(cov.get("by_size", {}).items(),
                                      key=lambda kv: (int(kv[0]) if str(kv[0]).isdigit() else 10 ** 9, kv[0])):
                sb = s.get("best_median", 0.0)
                spct = s.get("pct_of_ceiling", (sb / ceil * 100.0) if ceil > 0 else 0.0)
                spct_theo = s.get("pct_of_theoretical", (sb / theo * 100.0) if theo > 0 else 0.0)
                sizes.append((size_key, s, sb, spct, spct_theo))
            size_data[fam] = sizes

        all_pcts = ([d[5] for d in family_data]
                    + [s[3] for sd in size_data.values() for s in sd] + [100.0])
        all_pct_theo = ([d[6] for d in family_data]
                        + [s[4] for sd in size_data.values() for s in sd] + [100.0])
        scale = max(all_pcts)
        scale_theo = max(all_pct_theo)
        marker_left = 100.0 / scale * 100.0  # % width where the 100% marker sits
        marker_left_theo = 100.0 / scale_theo * 100.0

        family_rows = ""
        for fam, cov, best, ceil, theo, pct, pct_theo in family_data:
            bar_width = pct / scale * 100.0
            bar_width_theo = pct_theo / scale_theo * 100.0
            expand_id = f"fam-{fam}"
            sizes = size_data.get(fam, [])
            detail_html = ""
            if sizes:
                size_rows = ""
                for size_key, s, sb, spct, spct_theo in sizes:
                    sw = spct / scale * 100.0
                    sw_theo = spct_theo / scale_theo * 100.0
                    size_rows += f"""
                    <tr>
                        <td class="mono secondary">k={size_key}</td>
                        <td class="num">{s.get('cells', 0)}</td>
                        <td class="num strong">{sb:.1f}</td>
                        <td class="num secondary">{ceil:.1f}</td>
                        <td class="num secondary">{theo:.1f}</td>
                        <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz1" style="width: {sw:.1f}%;"></span><span class="bar-marker" style="left: {marker_left:.1f}%;"></span></span><span class="bar-label">{spct:.1f}%</span></span></td>
                        <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz2" style="width: {sw_theo:.1f}%;"></span><span class="bar-marker" style="left: {marker_left_theo:.1f}%;"></span></span><span class="bar-label">{spct_theo:.1f}%</span></span></td>
                    </tr>
                    """
                detail_html = f"""
                <tr class="family-detail" id="{expand_id}" hidden>
                    <td colspan="7">
                        <table class="size-table">
                            <thead>
                                <tr>
                                    <th>Kernel size</th>
                                    <th>Cells</th>
                                    <th>Best median</th>
                                    <th>Realistic ceiling</th>
                                    <th>Theoretical peak</th>
                                    <th>Ceiling utilization</th>
                                    <th>% of theoretical</th>
                                </tr>
                            </thead>
                            <tbody>
                                {size_rows}
                            </tbody>
                        </table>
                    </td>
                </tr>
                """
            family_rows += f"""
            <tr class="family-row">
                <td class="mono strong">
                    {f'<button type="button" class="row-toggle" aria-expanded="false" aria-controls="{expand_id}" data-target="{expand_id}"><span class="caret" aria-hidden="true">&#9656;</span></button>' if sizes else ''}
                    {fam}
                </td>
                <td class="num">{cov.get('deck_cells_measured', 0)} / {cov.get('deck_cells', 0)} <span class="mono secondary" title="distinct shipped gfx900 kernels in the pinned manifest for this family">{cov.get('expected_kernels', 0)} shipped</span></td>
                <td class="num strong">{best:.1f}</td>
                <td class="num secondary">{ceil:.1f}</td>
                <td class="num secondary">{theo:.1f}</td>
                <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz1" style="width: {bar_width:.1f}%;"></span><span class="bar-marker" style="left: {marker_left:.1f}%;"></span></span><span class="bar-label">{pct:.1f}%</span></span></td>
                <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz2" style="width: {bar_width_theo:.1f}%;"></span><span class="bar-marker" style="left: {marker_left_theo:.1f}%;"></span></span><span class="bar-label">{pct_theo:.1f}%</span></span></td>
            </tr>
            {detail_html}
            """

        red_color = "var(--support-error)" if report.red_list else "var(--support-success)"

        section_explore = self._problem_space_section(report)
        section_coverage_matrix = self._coverage_matrix_section(report)
        section_telemetry = self._telemetry_section(report)
        section_cell_status = self._cell_status_section(report)

        css = """
        :root {
            --font-sans: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
            --font-mono: "IBM Plex Mono", "Menlo", "DejaVu Sans Mono",
                          "Bitstream Vera Sans Mono", Courier, monospace;
            --background: #f4f4f4;
            --layer-01: #ffffff;
            --layer-02: #f4f4f4;
            --text-primary: #161616;
            --text-secondary: #525252;
            --border-subtle: #e0e0e0;
            --border-strong: #8d8d8d;
            --interactive: #0f62fe;
            --interactive-hover: #0043ce;
            --focus: #0f62fe;
            --support-success: #24a148;
            --support-error: #da1e28;
            --support-info: #0f62fe;
            --support-warning: #b28600;
            --tag-success-bg: #defbe6;
            --tag-error-bg: #fff1f1;
            --tag-info-bg: #edf5ff;
            --tag-warning-bg: #fff8dd;
            --track: #e0e0e0;
            --hover-row: #e8e8e8;
            --viz-1: #0f62fe;
            --viz-2: #009d9a;
            color-scheme: light;
        }
        [data-theme="dark"] {
            --background: #121212;
            --layer-01: #1e1e1e;
            --layer-02: #2a2a2a;
            --text-primary: #f4f4f4;
            --text-secondary: #a8a8a8;
            --border-subtle: #333333;
            --border-strong: #6f6f6f;
            --interactive: #0f62fe;
            --interactive-hover: #0043ce;
            --focus: #78a9ff;
            --support-success: #42be65;
            --support-error: #fa4d56;
            --support-info: #78a9ff;
            --support-warning: #f1c21b;
            --tag-success-bg: #0a2b12;
            --tag-error-bg: #3a1212;
            --tag-info-bg: #0f2b4d;
            --tag-warning-bg: #33270a;
            --track: #393939;
            --hover-row: #252525;
            --viz-1: #78a9ff;
            --viz-2: #08bdba;
            color-scheme: dark;
        }
        @media (prefers-color-scheme: dark) {
            :root:not([data-theme="light"]) {
                --background: #121212;
                --layer-01: #1e1e1e;
                --layer-02: #2a2a2a;
                --text-primary: #f4f4f4;
                --text-secondary: #a8a8a8;
                --border-subtle: #333333;
                --border-strong: #6f6f6f;
                --interactive: #0f62fe;
                --interactive-hover: #0043ce;
                --focus: #78a9ff;
                --support-success: #42be65;
                --support-error: #fa4d56;
                --support-info: #78a9ff;
                --support-warning: #f1c21b;
                --tag-success-bg: #0a2b12;
                --tag-error-bg: #3a1212;
                --tag-info-bg: #0f2b4d;
                --tag-warning-bg: #33270a;
                --track: #393939;
                --hover-row: #252525;
                --viz-1: #78a9ff;
                --viz-2: #08bdba;
            }
        }
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; }
        body {
            background: var(--background);
            color: var(--text-primary);
            font-family: var(--font-sans);
            font-size: 14px;
            line-height: 18px;
        }
        :focus-visible {
            outline: 2px solid var(--focus);
            outline-offset: 2px;
        }
        .shell {
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 48px;
            padding: 0 16px;
            border-bottom: 1px solid var(--border-subtle);
        }
        .shell-group { display: flex; align-items: baseline; gap: 12px; }
        .shell-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
        .shell-sub { font-size: 12px; color: var(--text-secondary); }
        .shell-actions { display: flex; align-items: center; gap: 8px; }
        .theme-toggle {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            padding: 0;
            border: none;
            background: transparent;
            font-family: var(--font-sans);
            font-size: 16px;
            line-height: 1;
            color: var(--text-primary);
            cursor: pointer;
        }
        .page { padding: 16px; max-width: 1280px; margin: 0 auto; }
        .page-title {
            margin: 24px 0 4px 0;
            font-size: 20px;
            line-height: 28px;
            font-weight: 600;
            color: var(--text-primary);
        }
        .page-sub { margin: 0 0 24px 0; font-size: 14px; color: var(--text-secondary); }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .metric {
            background: var(--layer-01);
            border: 1px solid var(--border-subtle);
            padding: 8px 16px;
        }
        .metric-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 2px; }
        .metric-value {
            font-size: 20px;
            line-height: 28px;
            font-weight: 400;
            color: var(--text-primary);
            font-variant-numeric: tabular-nums;
        }
        .section {
            background: var(--layer-01);
            margin-bottom: 16px;
        }
        .section-title {
            margin: 0;
            padding: 12px 16px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text-primary);
            border-bottom: 1px solid var(--border-subtle);
        }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        thead th {
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-primary);
            padding: 8px 16px;
            background: var(--layer-02);
            border-bottom: 2px solid var(--border-strong);
            white-space: nowrap;
        }
        tbody td {
            padding: 6px 16px;
            border-bottom: 1px solid var(--border-subtle);
            color: var(--text-primary);
            vertical-align: middle;
        }
        tbody tr:last-child td { border-bottom: none; }
        tbody tr:hover { background: var(--hover-row); }
        .mono { font-family: var(--font-mono); }
        .mono.strong { font-weight: 600; }
        .num {
            font-family: var(--font-sans);
            text-align: right;
            font-variant-numeric: tabular-nums;
        }
        .num.strong { font-weight: 600; color: var(--text-primary); }
        .num.secondary { color: var(--text-secondary); }
        code {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-secondary);
        }
        .tag {
            display: inline-flex;
            align-items: center;
            font-size: 12px;
            font-weight: 600;
            line-height: 16px;
            padding: 2px 8px;
            white-space: nowrap;
        }
        .tag-pass { color: var(--support-success); background: var(--tag-success-bg); }
        .tag-fail { color: var(--support-error); background: var(--tag-error-bg); }
        .tag-win { color: var(--support-success); background: var(--tag-success-bg); }
        .tag-tie { color: var(--support-info); background: var(--tag-info-bg); }
        .tag-loss { color: var(--support-error); background: var(--tag-error-bg); }
        .tag-orange { color: var(--support-warning); background: var(--tag-warning-bg); }
        .bar-wrap { display: inline-flex; align-items: center; gap: 4px; }
        .bar {
            display: inline-block;
            position: relative;
            width: 96px;
            height: 6px;
            background: var(--track);
            overflow: hidden;
        }
        .bar-fill { display: block; height: 100%; }
        .bar-viz1 { background: var(--viz-1); }
        .bar-viz2 { background: var(--viz-2); }
        .bar-marker {
            position: absolute;
            top: 0;
            bottom: 0;
            width: 2px;
            margin-left: -1px;
            background: var(--text-secondary);
            opacity: 0.65;
        }
        .bar-label {
            font-family: var(--font-sans);
            font-size: 12px;
            font-variant-numeric: tabular-nums;
            color: var(--text-primary);
        }
        .row-toggle {
            background: none;
            border: none;
            cursor: pointer;
            padding: 0;
            margin-right: 4px;
            font-size: 12px;
            line-height: 1;
            color: var(--interactive);
            font-family: var(--font-mono);
            vertical-align: baseline;
        }
        .family-detail td { padding: 0; }
        .size-table { margin: 4px 12px 12px 44px; width: calc(100% - 56px); min-width: 460px; }
        .size-table thead th { background: var(--layer-02); }
        .size-table tbody tr:last-child td { border-bottom: none; }
        .empty {
            padding: 24px 16px;
            text-align: center;
            color: var(--text-secondary);
        }
        @media (max-width: 640px) {
            .metrics { grid-template-columns: 1fr 1fr; }
            .shell { padding: 0 8px; }
            .page { padding: 8px; }
            thead th, tbody td { padding-left: 8px; padding-right: 8px; }
        }
        """

        js_init = """
        <script>
        (function () {
            var t = null;
            try { t = localStorage.getItem('report-theme'); } catch (e) {}
            var dark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
        })();
        </script>
        """

        js_toggle = r"""
        <script>
        (function () {
            var btn = document.getElementById('theme-toggle');
            if (!btn) return;
            var SUN = '\u2600\uFE0E';
            var MOON = '\u263E';
            function update() {
                var dark = document.documentElement.getAttribute('data-theme') === 'dark';
                if (dark) {
                    btn.textContent = SUN;
                    btn.setAttribute('aria-label', 'Switch to light mode');
                } else {
                    btn.textContent = MOON;
                    btn.setAttribute('aria-label', 'Switch to dark mode');
                }
            }
            btn.addEventListener('click', function () {
                var dark = document.documentElement.getAttribute('data-theme') === 'dark';
                document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
                try { localStorage.setItem('report-theme', dark ? 'light' : 'dark'); } catch (e) {}
                update();
            });
            update();
        })();
        </script>
        """

        js_expand = r"""
        <script>
        (function () {
            var toggles = document.querySelectorAll('.row-toggle');
            Array.prototype.forEach.call(toggles, function (btn) {
                btn.addEventListener('click', function () {
                    var target = document.getElementById(btn.getAttribute('data-target'));
                    var expanded = btn.getAttribute('aria-expanded') === 'true';
                    var open = !expanded;
                    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                    btn.querySelector('.caret').innerHTML = open ? '\u25BE' : '\u25B8';
                    if (target) target.hidden = !open;
                });
            });
        })();
        </script>
        """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tensile gfx90c Port Acceptance Dashboard</title>
    {js_init}
    <style>
{css}
    </style>
</head>
<body>
    <div class="shell">
        <div class="shell-group">
            <span class="shell-title">AMD gfx90c Tensile Port</span>
            <span class="shell-sub">Acceptance dashboard</span>
        </div>
        <div class="shell-actions">
            <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Switch to dark mode">☾</button>
        </div>
    </div>

    <main class="page">
        <h1 class="page-title">Acceptance Report</h1>
        <p class="page-sub">
            Run ID: <code>{report.run_id}</code> &middot; Timestamp: {now}
            {self._provenance_line(report)}
        </p>

        <div class="metrics">
            <div class="metric">
                <div class="metric-label">Overall verdict</div>
                <div class="metric-value"><span class="tag {status_class}">{status_badge}</span></div>
            </div>
            <div class="metric">
                <div class="metric-label">A/B tested cells</div>
                <div class="metric-value">{len(report.per_cell_verdicts)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Red (missing)</div>
                <div class="metric-value" style="color: {red_color};">{len(report.red_list)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Orange (&lt;50% ceiling)</div>
                <div class="metric-value" style="color: var(--support-info);">{len(report.orange_list)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Shipped gfx900 kernels</div>
                <div class="metric-value">{(report.shipped_manifest or {}).get('total_shipped_kernels', 0)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Run execution time</div>
                <div class="metric-value">{self._timing_metric(report)}</div>
            </div>
        </div>
        {self._timing_section(report)}

        <section class="section">
            <h2 class="section-title">Family matrix coverage &amp; peak utilization</h2>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Family</th>
                            <th>Coverage (cells / footprint)</th>
                            <th>Measured best median</th>
                            <th>Realistic ceiling</th>
                            <th>Theoretical peak</th>
                            <th>Ceiling utilization</th>
                            <th>% of theoretical</th>
                        </tr>
                    </thead>
                    <tbody>
                        {family_rows}
                    </tbody>
                </table>
            </div>
        </section>

        <section class="section">
            <h2 class="section-title">Native vs spoof A/B head-to-head</h2>
            <div class="table-wrap">
                {verdict_sections if verdict_sections else '<p class="empty">No native-vs-shipped-floor comparisons registered yet — run <code>--gfx900-reference</code> (established once, recalled forever) then a candidate run.</p>'}
            </div>
        </section>

        {section_cell_status}

        {section_explore}
        {section_coverage_matrix}
        {section_telemetry}
    </main>

    {js_expand}
    {js_toggle}
</body>
</html>"""

        with open(html_path, "w") as f:
            f.write(html)
        print(f"Acceptance dashboard HTML generated at: {html_path}")

    def _timing_metric(self, report) -> str:
        """Headline execution-time figure for the metrics row."""
        t = report.execution_timing or {}
        native = t.get("native_run") or {}
        human = native.get("elapsed_human")
        if human and human != "unknown":
            return human
        if native.get("in_flight"):
            return "in flight"
        return "unknown"

    def _timing_section(self, report) -> str:
        """Execution-time detail table.

        Native run and reference chain are shown separately: a resumed floor
        spans several runs, so quoting one number for "the run" would
        understate the floor's cost by however many resumes it took.
        """
        t = report.execution_timing or {}
        if not t:
            return ""
        native = t.get("native_run") or {}
        chain = t.get("reference_chain") or {}
        busy = t.get("phase_busy") or {}
        rows = []
        if native.get("started_at"):
            rows.append((
                "Native run",
                native.get("elapsed_human") or "unknown",
                f"{native.get('started_at', '')} &rarr; {native.get('completed_at') or 'in flight'}",
            ))
        if chain.get("elapsed_human"):
            rows.append((
                "Reference floor chain",
                chain["elapsed_human"],
                f"{len(chain.get('per_run') or [])} run(s): "
                f"{', '.join(r['run_id'] for r in chain.get('per_run') or [])}",
            ))
        if busy.get("minutes"):
            rows.append((
                "Phase busy time",
                f"{busy['hours']:.2f} h",
                "sum of per-phase spans; the gap to wall clock is config "
                "generation, Tensile build and queueing",
            ))
        if not rows:
            return ""
        body = "".join(
            f"<tr><td>{label}</td><td class='mono strong'>{value}</td>"
            f"<td class='mono secondary'>{detail}</td></tr>"
            for label, value, detail in rows
        )
        return f"""
        <section class="section">
            <h2 class="section-title">Execution time</h2>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Scope</th><th>Wall clock</th><th>Detail</th></tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </div>
        </section>
        """

    def _provenance_line(self, report) -> str:
        """One-line provenance: native arm scope, spoof floor source + reference run, ROCm prefixes."""
        out = ""
        arm = report.native_arm or {}
        if arm:
            runs = arm.get("runs", [])
            stat = arm.get("agg", "best")
            if runs:
                shown = ", ".join(f"<code>{r}</code>" for r in runs[:4])
                more = f" +{len(runs) - 4} more" if len(runs) > 4 else ""
                out += (f" &middot; Native arm: whole-db best/{stat} across {arm.get('n_runs', len(runs))} "
                        f"run(s) [{shown}{more}] ({arm.get('n_records', 0)} cells)")
            else:
                out += (f" &middot; Native arm: <strong>EMPTY</strong> — no native measurement "
                        f"anywhere in the db, so every cell reads 0/MISSING")
        if report.reference_run_id:
            out += f" &middot; Spoof floor: gfx900 shipped TensileLibrary (ref <code>{report.reference_run_id}</code>)"
        prefixes = (report.shipped_manifest or {}).get("rocm_prefixes", [])
        if prefixes:
            out += f" &middot; ROCm: {', '.join('<code>%s</code>' % p for p in prefixes)}"
        return out

    # Column headers per comparison basis, so the two rendered columns are
    # always exactly the operands behind delta_pct (never a proxy for them).
    _BASIS_HEADERS = {
        "floor_best":   ("Native median", "Floor best median"),
        "strict":       ("Native worst median", "Floor best median"),
        "best_median":  ("Native best median", "Floor median"),
        "winner":       ("Native best median", "Floor best median"),
        "winner_clock": ("Native best (clk-adj)", "Floor best (clk-adj)"),
        "median_clock": ("Native median (clk-adj)", "Floor median (clk-adj)"),
        "median":       ("Native median", "Floor median"),
        "throttle":     ("Native throttle-adj", "Floor throttle-adj"),
        "best":         ("Native max sample", "Floor max sample"),
    }

    def _basis_headers(self, agg: str):
        return self._BASIS_HEADERS.get(agg, ("Native value", "Floor value"))

    def _cell_status_section(self, report) -> str:
        """Gfx900 contract cell grid: RED missing / ORANGE below threshold / GREEN."""
        cells = []
        for e in report.red_list:
            cells.append((e, "RED", "tag-loss", "var(--support-error)"))
        for e in report.orange_list:
            cells.append((e, "ORANGE", "tag-orange", "var(--support-warning)"))

        row_html = ""
        for e, label, cls, _color in cells:
            row_html += f"""
                <tr>
                    <td class="mono strong">{e.get('family', e.get('dtype', ''))}</td>
                    <td class="mono">{e.get('shape', '')}</td>
                    <td class="num">{e.get('median_gflops', 0.0):.1f}</td>
                    <td class="num">{e.get('pct_of_ceiling', 0.0):.1f}%</td>
                    <td><span class="tag {cls}">{label}</span></td>
                </tr>"""

        if not row_html:
            row_html = '<tr><td colspan="5" class="empty">No missing or below-threshold cells — every gfx900 contract cell covered at/above the bar.</td></tr>'

        return f"""
        <section class="section">
            <h2 class="section-title">gfx900 contract cells (RED = missing, ORANGE = &lt;50% ceiling)</h2>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Family</th>
                            <th>Problem shape</th>
                            <th>Best median</th>
                            <th>% of ceiling</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>{row_html}
                    </tbody>
                </table>
            </div>
        </section>
        """

    def _problem_space_section(self, report) -> str:
        """Problem-space table derived from the recorded cell analytics."""
        cells = report.all_analytics or []
        groups = {}
        for c in cells:
            label = (c.family or c.dtype or "unknown").upper()
            groups.setdefault(label, []).append(c)

        empty = ("<section class=\"section\"><h2 class=\"section-title\">Problem "
                 "space explored</h2><div class=\"table-wrap\"><table><tbody>"
                 "<tr><td class=\"empty\">No analytics recorded yet.</td></tr>"
                 "</tbody></table></div></section>")
        if not groups:
            return empty

        cov = report.per_family_coverage or {}
        rows = ""
        for label in sorted(groups):
            cg = groups[label]
            shapes = ", ".join(sorted({c.shape for c in cg}))
            entry = cov.get(label)
            if entry:
                footprint = (f"{entry['coverage_pct']:.1f}% "
                             f"({entry['deck_cells_measured']}/{entry['deck_cells']} deck cells; "
                             f"{entry['measured_cells']} config-cells)")
            else:
                footprint = "—"
            rows += f"""
                <tr>
                    <td class="mono strong">{label}</td>
                    <td class="mono">{shapes}</td>
                    <td class="num strong">{len(cg)}</td>
                    <td class="num">{footprint}</td>
                </tr>"""
        return f"""
        <section class="section">
            <h2 class="section-title">Problem space explored</h2>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Family</th>
                            <th>Active shapes</th>
                            <th>Total explored cells</th>
                            <th>Footprint coverage</th>
                        </tr>
                    </thead>
                    <tbody>{rows}
                    </tbody>
                </table>
            </div>
        </section>
        """

    def _coverage_matrix_section(self, report) -> str:
        """Coverage + execution-time table derived from coverage and registry timing."""
        timing = report.family_timing or {}
        fam_keys = set(report.per_family_coverage.keys())
        fam_keys |= set(timing.keys())

        empty = ("<section class=\"section\"><h2 class=\"section-title\">Coverage "
                 "matrix &amp; execution time</h2><div class=\"table-wrap\"><table>"
                 "<tbody><tr><td class=\"empty\">No measurement data recorded yet.</td>"
                 "</tr></tbody></table></div></section>")
        if not fam_keys:
            return empty

        rows = ""
        for fam in sorted(fam_keys):
            cov = report.per_family_coverage.get(fam)
            t = timing.get(fam)
            if cov is not None:
                completed = (f"{cov['deck_cells_measured']} / {cov['deck_cells']} deck"
                             f" <span class=\"mono secondary\" title=\"measured config-cells vs shipped kernels\">"
                             f"{cov['measured_cells']} / {cov['expected_kernels']} kernels</span>")
                measured = cov["measured_cells"] > 0
            else:
                completed = f"{t['cells'] if t else 0} / —"
                measured = bool(t and t["cells"])
            mean_sec = f"{t['mean_sec']:.1f}" if t else "—"
            total_min = f"{t['total_min']:.1f}" if t else "—"
            if measured:
                tag = "tag tag-pass"
                status = "Active"
            else:
                tag = "tag tag-info"
                status = "No data"
            rows += f"""
                <tr>
                    <td class="mono strong">{fam}</td>
                    <td class="num">{completed}</td>
                    <td class="num">{mean_sec}</td>
                    <td class="num">{total_min}</td>
                    <td><span class="{tag}">{status}</span></td>
                </tr>"""
        return f"""
        <section class="section">
            <h2 class="section-title">Coverage matrix &amp; execution time</h2>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Family</th>
                            <th>Completed cells</th>
                            <th>Mean time / cell (s)</th>
                            <th>Total time (min)</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>{rows}
                    </tbody>
                </table>
            </div>
        </section>
        """

    def _load_run_telemetry(self, run_dir) -> Optional[Dict[str, Dict[str, float]]]:
        """Parse logs/telemetry.csv from the run directory (median + peak per metric)."""
        if not run_dir:
            return None
        p = Path(run_dir) / "logs" / "telemetry.csv"
        if not p.exists():
            return None

        cols: Dict[str, List[float]] = {}
        try:
            with open(p, newline="") as f:
                rd = csv.DictReader(f)
                for row in rd:
                    for col in ("power_uw", "temp_mc", "sclk_hz", "mclk_hz", "gpu_busy_percent"):
                        try:
                            cols.setdefault(col, []).append(float(row[col]))
                        except (KeyError, ValueError, TypeError):
                            continue
        except (OSError, ValueError):
            return None
        if not any(cols.values()):
            return None

        div = {"power_uw": 1e6, "temp_mc": 1e3, "sclk_hz": 1e6, "mclk_hz": 1e6, "gpu_busy_percent": 1.0}
        out = {}
        for col, values in cols.items():
            if not values:
                continue
            # Drop metrics whose sensor never reported (all-zero reads).
            if max(values) == 0.0:
                continue
            out[col] = {
                "median": round(statistics.median(values) / div[col], 1),
                "peak": round(max(values) / div[col], 1),
            }
        return out

    def _telemetry_section(self, report) -> str:
        """Telemetry table derived from the run's telemetry.csv (drop fabricated values)."""
        stats = self._load_run_telemetry(report.run_dir)

        empty = ("<section class=\"section\"><h2 class=\"section-title\">Telemetry "
                 "insights (gfx90c APU)</h2><div class=\"table-wrap\"><table><tbody>"
                 "<tr><td class=\"empty\">No telemetry CSV recorded for this run.</td>"
                 "</tr></tbody></table></div></section>")
        if not stats:
            return empty

        labels = {
            "power_uw": "Package Power",
            "temp_mc": "Edge Temperature",
            "sclk_hz": "Shader Clock (SCLK)",
            "mclk_hz": "Memory Clock (MCLK)",
            "gpu_busy_percent": "GPU Busy",
        }
        units = {
            "power_uw": "W",
            "temp_mc": "°C",
            "sclk_hz": "MHz",
            "mclk_hz": "MHz",
            "gpu_busy_percent": "%",
        }
        rows = ""
        for col in labels:
            if col not in stats:
                continue
            s = stats[col]
            rows += f"""
                <tr>
                    <td class="mono strong">{labels[col]}</td>
                    <td class="num">{s['median']} {units[col]}</td>
                    <td class="num">{s['peak']} {units[col]}</td>
                </tr>"""
        return f"""
        <section class="section">
            <h2 class="section-title">Telemetry insights (gfx90c APU)</h2>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Metric</th>
                            <th>Observed median</th>
                            <th>Peak recorded</th>
                        </tr>
                    </thead>
                    <tbody>{rows}
                    </tbody>
                </table>
            </div>
            <p class="note">Throughput is normalized for sustained shader clock,
            using GPU-busy samples only. Temperature is a measurement-validity
            gate, not a throughput correction: core clock is the channel
            temperature acts through, so scaling throughput by temperature as
            well would double-count. A phase at or above the gate temperature
            is reported as unmeasured rather than as a slow kernel.</p>
        </section>
        """

