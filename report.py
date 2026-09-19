#!/usr/bin/env python3
"""
report.py — Stage 7: Acceptance A/B & Final Report

Scoped same-run A/B (native vs spoof); per-family acceptance report.
"""

import json
import math
import csv
import statistics
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from gfx90c_common import PEAK_GFLOPS, FAMILY_DTYPES, THEORETICAL_PEAKS
from analytics import AnalyticsEngine, CellAnalytics, REALISTIC_CEILINGS, FAMILY_TO_DTYPE
from policy import aggregate_cell, classify_tie


@dataclass
class ABVerdict:
    """Result of same-run A/B comparison."""
    dtype: str
    shape: str
    native_median: float
    spoof_median: float
    delta_pct: float
    tie: bool
    verdict: str  # "WIN", "TIE", "LOSS"


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


class AcceptanceReporter:
    """Stage 7 acceptance A/B and final report engine."""

    def __init__(self, base_dir: Path, cooldown_s: int = 30):
        self.base_dir = Path(base_dir)
        self.cooldown_s = cooldown_s
        self.mapping_path = self.base_dir / "mapping.md"

    def compute_ab_verdict(
        self,
        native_seeds: List[float],
        spoof_seeds: List[float],
        dtype: str,
        shape: str,
        tie_band_pct: float = 5.0
    ) -> ABVerdict:
        """
        Compute A/B verdict from seed lists.

        Args:
            native_seeds: List of native benchmark results
            spoof_seeds: List of spoof benchmark results
            dtype: Data type
            shape: Problem shape
            tie_band_pct: ±% band for tie classification (default 5%)

        Returns:
            ABVerdict object
        """
        if not native_seeds or not spoof_seeds:
            raise ValueError("Both native and spoof must have seeds")

        native_agg = aggregate_cell(native_seeds)
        spoof_agg = aggregate_cell(spoof_seeds)

        delta_pct = (
            ((native_agg.median - spoof_agg.median) / spoof_agg.median * 100.0)
            if spoof_agg.median > 0 else 0.0
        )

        tie = classify_tie(spoof_agg.median, native_agg.median, tie_band_pct)

        if tie:
            verdict = "TIE"
        elif delta_pct > 0:
            verdict = "WIN"
        else:
            verdict = "LOSS"

        return ABVerdict(
            dtype=dtype,
            shape=shape,
            native_median=native_agg.median,
            spoof_median=spoof_agg.median,
            delta_pct=delta_pct,
            tie=tie,
            verdict=verdict
        )

    def generate_acceptance_report(
        self,
        run_id: str,
        ab_verdicts: List[ABVerdict],
        all_analytics: List[CellAnalytics],
        red_list: List[Dict[str, Any]],
        red_threshold_pct: float = 50.0,
        family_timing: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> AcceptanceReport:
        """Generate final acceptance report."""
        per_family_coverage = self._compute_family_coverage(all_analytics)
        overall_pass = self._compute_overall_pass(ab_verdicts, red_list, red_threshold_pct)
        summary = self._generate_summary(ab_verdicts, red_list, overall_pass)

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
            family_timing=family_timing
        )

    def _compute_family_coverage(
        self,
        all_analytics: List[CellAnalytics]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compute per-family coverage vs mapping.md contract (7 families).
        """
        expected_families = ["CC", "DD", "ZZ", "HH", "HH_HPA", "HS_HPA", "SS"]
        expected_kernels = {
            "CC": 64,
            "DD": 104,
            "ZZ": 26,
            "HH": 314,
            "HH_HPA": 424,
            "HS_HPA": 493,
            "SS": 1641,
        }

        coverage = {}
        for family in expected_families:
            fam_lower = family.lower()
            # Match by explicit family prefix first (distinguishes HH / HH_HPA / HS_HPA),
            # fall back to single-letter dtype / family name / display name for cells
            # that carry no family tag (older runs / aggregate_by_cell path).
            family_cells = [a for a in all_analytics
                            if a.family == fam_lower]
            if not family_cells:
                short = FAMILY_TO_DTYPE.get(fam_lower)
                family_cells = [a for a in all_analytics
                                if a.dtype == short or a.dtype == family or a.dtype == self._family_to_dtype(family)]

            ceiling = REALISTIC_CEILINGS.get(family, PEAK_GFLOPS.get(FAMILY_DTYPES.get(family, "FP32"), 1613.0))
            theoretical = THEORETICAL_PEAKS.get(family, PEAK_GFLOPS.get(FAMILY_DTYPES.get(family, "FP32"), 1613.0))
            best_median = max([a.median_gflops for a in family_cells]) if family_cells else 0.0

            coverage[family] = {
                "expected_kernels": expected_kernels[family],
                "measured_cells": len(family_cells),
                "coverage_pct": min(100.0, (len(family_cells) / expected_kernels[family] * 100.0)
                                  if expected_kernels[family] > 0 else 0.0),
                "best_median": best_median,
                "ceiling_gflops": ceiling,
                "theoretical_peak_gflops": theoretical,
                "pct_of_theoretical": (best_median / theoretical * 100.0) if theoretical > 0 else 0.0,
            }

        return coverage

    def _family_to_dtype(self, family: str) -> str:
        mapping = {
            "SS": "FP32",
            "DD": "FP64",
            "HH": "FP16",
            "CC": "FP32",   # complex single (DataType C)
            "ZZ": "FP64",   # complex double (DataType Z)
            "HH_HPA": "FP32",
            "HS_HPA": "FP32",
        }
        return mapping.get(family, "FP32")

    def _compute_overall_pass(
        self,
        ab_verdicts: List[ABVerdict],
        red_list: List[Dict[str, Any]],
        red_threshold_pct: float = 50.0
    ) -> bool:
        if not ab_verdicts and not red_list:
            return True

        wins = sum(1 for v in ab_verdicts if v.verdict == "WIN")
        ties = sum(1 for v in ab_verdicts if v.verdict == "TIE")
        losses = sum(1 for v in ab_verdicts if v.verdict == "LOSS")

        if losses > (wins + ties):
            return False

        for cell in red_list:
            if cell.get("pct_of_ceiling", 0.0) < red_threshold_pct:
                return False

        return True

    def _generate_summary(
        self,
        ab_verdicts: List[ABVerdict],
        red_list: List[Dict[str, Any]],
        overall_pass: bool
    ) -> str:
        wins = sum(1 for v in ab_verdicts if v.verdict == "WIN")
        ties = sum(1 for v in ab_verdicts if v.verdict == "TIE")
        losses = sum(1 for v in ab_verdicts if v.verdict == "LOSS")

        status = "PASS" if overall_pass else "FAIL"
        return (
            f"Acceptance {status}: {wins} WIN / {ties} TIE / {losses} LOSS vs spoof floor. "
            f"{len(red_list)} RED cells remain."
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
                    "native_median": v.native_median,
                    "spoof_median": v.spoof_median,
                    "delta_pct": v.delta_pct,
                    "tie": v.tie,
                    "verdict": v.verdict
                }
                for v in report.per_cell_verdicts
            ],
            "red_list": report.red_list,
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

        verdict_rows = ""
        for v in report.per_cell_verdicts:
            if v.verdict == "WIN":
                v_cls, v_color = "tag-win", "var(--support-success)"
            elif v.verdict == "TIE":
                v_cls, v_color = "tag-tie", "var(--support-info)"
            else:
                v_cls, v_color = "tag-loss", "var(--support-error)"
            verdict_rows += f"""
            <tr>
                <td><code>{v.dtype}</code></td>
                <td class="mono strong">{v.shape}</td>
                <td class="num strong">{v.native_median:.1f}</td>
                <td class="num secondary">{v.spoof_median:.1f}</td>
                <td class="num strong" style="color: {v_color};">{v.delta_pct:+.1f}%</td>
                <td><span class="tag {v_cls}">{v.verdict}</span></td>
            </tr>
            """

        # Build family rows with a dynamic "vs acceptance ceiling" scale:
        # scale = max(100%, max measured) so values >100% are never clipped and the
        # actual value stays visible; a marker line shows where 100% sits.
        family_data = []
        for fam, cov in report.per_family_coverage.items():
            best = cov.get("best_median", 0.0)
            ceil = cov.get("ceiling_gflops", 1118.7)
            theo = cov.get("theoretical_peak_gflops", 0.0) or ceil
            pct = (best / ceil * 100.0) if ceil > 0 else 0.0
            pct_theo = (best / theo * 100.0) if theo > 0 else 0.0
            family_data.append((fam, cov, best, ceil, theo, pct, pct_theo))

        max_pct = max([d[5] for d in family_data] + [100.0])
        scale = max_pct
        marker_left = 100.0 / scale * 100.0  # % width where the 100% marker sits

        family_rows = ""
        for fam, cov, best, ceil, theo, pct, pct_theo in family_data:
            bar_width = pct / scale * 100.0
            family_rows += f"""
            <tr>
                <td class="mono strong">{fam}</td>
                <td class="num">{cov.get('measured_cells', 0)} / {cov.get('expected_kernels', 0)}</td>
                <td class="num strong">{best:.1f}</td>
                <td class="num secondary">{ceil:.1f}</td>
                <td class="num secondary">{theo:.1f}</td>
                <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz1" style="width: {bar_width:.1f}%;"></span><span class="bar-marker" style="left: {marker_left:.1f}%;"></span></span><span class="bar-label">{pct:.1f}%</span></span></td>
                <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz2" style="width: {min(pct_theo, 100):.1f}%;"></span></span><span class="bar-label">{pct_theo:.1f}%</span></span></td>
            </tr>
            """

        red_color = "var(--support-error)" if report.red_list else "var(--support-success)"

        section_explore = self._problem_space_section(report)
        section_coverage_matrix = self._coverage_matrix_section(report)
        section_telemetry = self._telemetry_section(report)

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
            --tag-success-bg: #defbe6;
            --tag-error-bg: #fff1f1;
            --tag-info-bg: #edf5ff;
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
            --tag-success-bg: #0a2b12;
            --tag-error-bg: #3a1212;
            --tag-info-bg: #0f2b4d;
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
                --tag-success-bg: #0a2b12;
                --tag-error-bg: #3a1212;
                --tag-info-bg: #0f2b4d;
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
        .bar-wrap { display: inline-flex; align-items: center; gap: 4px; }
        .bar {
            display: inline-block;
            width: 96px;
            height: 6px;
            background: var(--track);
            overflow: hidden;
        }
        .bar-fill { display: block; height: 100%; }
        .bar-viz1 { background: var(--viz-1); }
        .bar-viz2 { background: var(--viz-2); }
        .bar-label {
            font-family: var(--font-sans);
            font-size: 12px;
            font-variant-numeric: tabular-nums;
            color: var(--text-primary);
        }
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
                <div class="metric-label">Red cells remaining</div>
                <div class="metric-value" style="color: {red_color};">{len(report.red_list)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Architecture target</div>
                <div class="metric-value">gfx90c (Vega 7)</div>
            </div>
        </div>

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
                <table>
                    <thead>
                        <tr>
                            <th>Dtype</th>
                            <th>Problem shape</th>
                            <th>Native median</th>
                            <th>Spoof median</th>
                            <th>Delta (%)</th>
                            <th>Verdict</th>
                        </tr>
                    </thead>
                    <tbody>
                        {verdict_rows if verdict_rows else '<tr><td colspan="6" class="empty">No same-run A/B comparisons registered yet.</td></tr>'}
                    </tbody>
                </table>
            </div>
        </section>

        {section_explore}
        {section_coverage_matrix}
        {section_telemetry}
    </main>

    {js_toggle}
</body>
</html>"""

        with open(html_path, "w") as f:
            f.write(html)
        print(f"Acceptance dashboard HTML generated at: {html_path}")

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
                             f"({entry['measured_cells']}/{entry['expected_kernels']} kernels)")
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
                completed = f"{cov['measured_cells']} / {cov['expected_kernels']}"
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
        </section>
        """

