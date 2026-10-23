#!/usr/bin/env python3
"""The acceptance dashboard renderer (JSON payload -> one HTML file).

Owns: ``write_html_report`` and the pure sub-builders it composes -- the A/B
head-to-head sections, the family coverage matrix (data prep + rendered rows),
the problem-space coverage section (report_figures) and the document template.
Nothing here writes anything but the final file.
Does NOT own: the report payload (report_models), the section builders
(report_sections), the coverage figures themselves (report_figures reads
oto.harness.coverage_graph's hand-off) or the static assets (report_css).
Public API: HtmlMixin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from oto.metrics.report_css import (DASHBOARD_CSS, JS_THEME_INIT,
                                     JS_THEME_TOGGLE, JS_COLLAPSIBLE)
from oto.metrics.report_figures import coverage_section
from oto.metrics.report_models import AcceptanceReport


class HtmlMixin:
    """HTML dashboard rendering, mixed into AcceptanceReporter."""

    # -- A/B head-to-head --------------------------------------------------

    def _ab_verdict_sections(self, report: AcceptanceReport) -> str:
        """The per-family A/B head-to-head tables.

        Grouped by family because the operator reads one family at a time, and
        the column headers depend on the aggregation basis the verdicts were
        computed with -- a header that says "median" over a "best" comparison is
        a wrong number, not a cosmetic issue.
        """
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
        return verdict_sections

    # -- family coverage matrix --------------------------------------------

    def _coverage_data(self, report: AcceptanceReport) -> Dict[str, Any]:
        """Per-family coverage rows plus the one scale they are drawn against.

        The scale is derived, not fixed: it is ``max(100%, max measured %)`` so a
        family that beats its realistic ceiling is shown above 100 instead of
        being clipped to a full bar, and the 100% marker keeps its meaning.
        """
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
        return {"family_data": family_data, "size_data": size_data,
                "scale": scale, "scale_theo": scale_theo,
                "marker_left": marker_left, "marker_left_theo": marker_left_theo}


    def _util_bar(self, pct: float, scale: float, marker_left: float,
                  viz: str) -> str:
        """One utilization bar, drawn against the shared scale."""
        width = pct / scale * 100.0
        return (f'<span class="bar-wrap"><span class="bar">'
                f'<span class="bar-fill {viz}" style="width: {width:.1f}%;"></span>'
                f'<span class="bar-marker" style="left: {marker_left:.1f}%;"></span>'
                f'</span><span class="bar-label">{pct:.1f}%</span></span>')

    def _family_matrix_rows(self, family_data, size_data, scale, scale_theo,
                            marker_left, marker_left_theo) -> str:
        """Family subtotal rows, each followed by its always-visible size rows.

        The old version hid the size rows behind a 7x12 caret and rendered a
        nested table inside a detail row. That made the most useful breakdown
        the least discoverable part of the section. The family row is now a
        visible subtotal; the size rows are ordinary rows underneath it, so the
        table is readable without discovering or operating a control.
        """
        rows = []
        for fam, cov, best, ceil, theo, pct, pct_theo in family_data:
            rows.append(f"""
            <tbody class="family-group">
                <tr class="family-row">
                    <th scope="rowgroup" class="mono strong">{fam}</th>
                    <td class="num">{cov.get('deck_cells_measured', 0)} / {cov.get('deck_cells', 0)} <span class="mono secondary" title="distinct shipped gfx900 kernels in the pinned manifest for this family">{cov.get('expected_kernels', 0)} shipped</span></td>
                    <td class="num strong">{best:.1f}</td>
                    <td class="num secondary">{ceil:.1f}</td>
                    <td class="num secondary">{theo:.1f}</td>
                    <td>{self._util_bar(pct, scale, marker_left, 'bar-viz1')}</td>
                    <td>{self._util_bar(pct_theo, scale_theo, marker_left_theo, 'bar-viz2')}</td>
                </tr>""")
            for size_key, s, sb, spct, spct_theo in size_data.get(fam, []):
                rows.append(f"""
                <tr class="size-row">
                    <th scope="row" class="mono">k={size_key}</th>
                    <td class="num">{s.get('cells', 0)}</td>
                    <td class="num strong">{sb:.1f}</td>
                    <td class="num secondary">{ceil:.1f}</td>
                    <td class="num secondary">{theo:.1f}</td>
                    <td>{self._util_bar(spct, scale, marker_left, 'bar-viz1')}</td>
                    <td>{self._util_bar(spct_theo, scale_theo, marker_left_theo, 'bar-viz2')}</td>
                </tr>""")
            rows.append("            </tbody>")
        return "".join(rows)


    # -- document template fragments ---------------------------------------
    #
    # The original single 98-line f-string is split at its five natural
    # boundaries. Each fragment reproduces its literal bytes exactly and the
    # caller concatenates them in order, so the emitted document is unchanged.

    def _document_head(self, report, now: str, provenance: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tensile gfx90c Port Acceptance Dashboard</title>
    {JS_THEME_INIT}
    <style>
{DASHBOARD_CSS}
    </style>
</head>
<body>
    <div class="shell">
        <div class="shell-group">
            <span class="shell-title">AMD gfx90c Tensile Port</span>
            <span class="shell-sub">Acceptance dashboard</span>
        </div>
        <div class="shell-actions">
            <button id="expand-all" class="theme-toggle" type="button" aria-label="Expand all sections">Expand all</button>
            <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Switch to dark mode">☾</button>
        </div>
    </div>

    <main class="page">
        <h1 class="page-title">Acceptance Report</h1>
        <p class="page-sub">
            Run ID: <code>{report.run_id}</code> &middot; Timestamp: {now}
            {self._provenance_line(report)}
        </p>

"""

    def _metrics_row(self, report, status_class: str, status_badge: str,
                     red_color: str, timing_metric: str,
                     timing_section: str) -> str:
        return f"""        <div class="metrics">
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
"""

    def _family_matrix_section(self, family_rows: str) -> str:
        return f"""
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">
                Family matrix coverage & peak utilization
            </h2>
            <div class="section-body">
                <p class="section-note">Each family row is a subtotal. The indented
                rows underneath are the per-kernel-size measurements behind it, so
                the breakdown is visible without opening anything.</p>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Family / kernel size</th>
                                <th>Coverage (cells / footprint)</th>
                                <th>Measured best median</th>
                                <th>Realistic ceiling</th>
                                <th>Theoretical peak</th>
                                <th>Ceiling utilization</th>
                                <th>% of theoretical</th>
                            </tr>
                        </thead>
                        {family_rows}
                    </table>
                </div>
            </div>
        </section>
"""

    def _ab_section(self, verdict_sections: str) -> str:
        return f"""
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">
                Native vs spoof A/B head-to-head
            </h2>
            <div class="section-body">
                <div class="table-wrap">
                    {verdict_sections if verdict_sections else '<p class="empty">No native-vs-shipped-floor comparisons registered yet — run <code>--gfx900-reference</code> (established once, recalled forever) then a candidate run.</p>'}
                </div>
            </div>
        </section>
"""

    def _document_tail(self, section_cell_status: str, section_explore: str,
                       section_coverage_matrix: str,
                       section_telemetry: str,
                       section_coverage_figures: str = "") -> str:
        return f"""
        {section_coverage_figures}
        {section_cell_status}

        {section_explore}
        {section_coverage_matrix}
        {section_telemetry}
    </main>

    {JS_THEME_TOGGLE}
    {JS_COLLAPSIBLE}
</body>
</html>"""

    def _report_base_dir(self) -> Path:
        """The repo root the report is written for (the figures live under it)."""
        return Path(getattr(self, "base_dir", None) or Path.cwd())

    def write_html_report(self, report: AcceptanceReport,
                          html_path: Path) -> None:
        """Render the whole dashboard to ``html_path``.

        The document is assembled from five pure fragments (see
        ``_document_head`` / ``_metrics_row`` / ``_family_matrix_section`` /
        ``_ab_section`` / ``_document_tail``) so each one can be read and
        reviewed without the others.
        """
        now = report.timestamp
        status_badge = "Pass" if report.overall_pass else "Fail"
        status_class = "tag-pass" if report.overall_pass else "tag-fail"
        red_color = ("var(--support-error)" if report.red_list
                     else "var(--support-success)")

        verdict_sections = self._ab_verdict_sections(report)

        data = self._coverage_data(report)
        family_rows = self._family_matrix_rows(
            data["family_data"], data["size_data"], data["scale"],
            data["scale_theo"], data["marker_left"], data["marker_left_theo"])

        # Assigned in the order the renderer reads them; each is a pure builder
        # over `report`.
        section_cell_status = self._cell_status_section(report)
        section_explore = self._problem_space_section(report)
        section_coverage_matrix = self._coverage_matrix_section(report)
        section_telemetry = self._telemetry_section(report)
        section_coverage_figures = coverage_section(
            self._report_base_dir(), html_path)

        html = "".join((
            self._document_head(report, now, self._provenance_line(report)),
            self._metrics_row(report, status_class, status_badge, red_color,
                              self._timing_metric(report),
                              self._timing_section(report)),
            self._family_matrix_section(family_rows),
            self._ab_section(verdict_sections),
            self._document_tail(section_cell_status, section_explore,
                                section_coverage_matrix, section_telemetry,
                                section_coverage_figures),
        ))

        with open(html_path, "w") as f:
            f.write(html)
        print(f"Acceptance dashboard HTML generated at: {html_path}")
