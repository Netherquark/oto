#!/usr/bin/env python3
"""The dashboard's HTML section builders.

Owns: one function per rendered section -- the execution-time block, the
provenance line, the per-aggregation column headers, the gfx900 contract-cell
grid, the problem-space table, the coverage/execution-time matrix, and the
telemetry insights table.
Does NOT own: the report payload (report_models), the verdict compute
(report.py), or the static assets (report_css).
Public API: SectionMixin.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import ClassVar

from oto.device import loader as _loader
from oto.tensile.shape_order import ordered_shapes


class SectionMixin:
    """HTML section builders, mixed into AcceptanceReporter."""


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
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">Execution time</h2>
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
                out += (" &middot; Native arm: <strong>EMPTY</strong> — no native measurement "
                        "anywhere in the db, so every cell reads 0/MISSING")
        if report.reference_run_id:
            out += f" &middot; Spoof floor: gfx900 shipped TensileLibrary (ref <code>{report.reference_run_id}</code>)"
        prefixes = (report.shipped_manifest or {}).get("rocm_prefixes", [])
        if prefixes:
            out += f" &middot; ROCm: {', '.join(f'<code>{p}</code>' for p in prefixes)}"
        return out

    # Column headers per comparison basis, so the two rendered columns are
    # always exactly the operands behind delta_pct (never a proxy for them).
    _BASIS_HEADERS: ClassVar[dict[str, tuple[str, str]]] = {
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
        cells = [(e, "RED", "tag-loss", "var(--support-error)")
                 for e in report.red_list]
        cells.extend((e, "ORANGE", "tag-orange", "var(--support-warning)")
                    for e in report.orange_list)

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
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">gfx900 contract cells (RED = missing, ORANGE = &lt;50% ceiling)</h2>
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
        """Problem-space table derived from the per-cell verdicts."""
        verdicts = report.per_cell_verdicts or []
        groups = {}
        for v in verdicts:
            label = (v.family or v.dtype or "unknown").upper()
            groups.setdefault(label, []).append(v.shape)

        empty = ("<section class=\"section collapsible\" data-collapsed=\"true\"><h2 class=\"section-title\" tabindex=\"0\" role=\"button\" aria-expanded=\"false\">Problem "
                 "space explored</h2><div class=\"section-body\"><div class=\"table-wrap\"><table><tbody>"
                 "<tr><td class=\"empty\">No analytics recorded yet.</td></tr>"
                 "</tbody></table></div></div></section>")
        if not groups:
            return empty

        cov = report.per_family_coverage or {}
        rows = ""
        for label in sorted(groups):
            shapes = ", ".join(ordered_shapes(set(groups[label])))
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
                    <td class="num strong">{len(groups[label])}</td>
                    <td class="num">{footprint}</td>
                </tr>"""
        return f"""
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">Problem space explored</h2>
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

    def _coverage_matrix_row(self, fam, cov, t):
        """Build one row for the coverage matrix table."""
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
            tag, status = "tag tag-pass", "Active"
        else:
            tag, status = "tag tag-info", "No data"
        return f"""
                <tr>
                    <td class="mono strong">{fam}</td>
                    <td class="num">{completed}</td>
                    <td class="num">{mean_sec}</td>
                    <td class="num">{total_min}</td>
                    <td><span class="{tag}">{status}</span></td>
                </tr>"""

    def _coverage_matrix_rows(self, report, fam_keys, timing):
        """Build all rows for the coverage matrix table."""
        rows = ""
        for fam in sorted(fam_keys):
            cov = report.per_family_coverage.get(fam)
            t = timing.get(fam)
            rows += self._coverage_matrix_row(fam, cov, t)
        return rows

    def _coverage_matrix_section(self, report) -> str:
        """Coverage + exec-time matrix from registry timing."""
        timing = report.family_timing or {}
        fam_keys = set(report.per_family_coverage.keys())
        fam_keys |= set(timing.keys())

        empty = ("<section class=\"section\"><h2 class=\"section-title\">Coverage "
                 "matrix &amp; execution time</h2><div class=\"table-wrap\"><table>"
                 "<tbody><tr><td class=\"empty\">No measurement data recorded yet.</td>"
                 "</tr></tbody></table></div></section>")
        if not fam_keys:
            return empty

        rows = self._coverage_matrix_rows(report, fam_keys, timing)
        return f"""
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">
                Coverage matrix & execution time
            </h2>
            <div class="section-body">
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
            </div>
        </section>
        """

    def _load_run_telemetry(self, run_dir) -> dict[str, dict[str, float]] | None:
        """Parse logs/telemetry.csv from the run directory (median + peak per metric)."""
        if not run_dir:
            return None
        p = Path(run_dir) / "logs" / "telemetry.csv"
        if not p.exists():
            return None

        cols: dict[str, list[float]] = {}
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

    def _telemetry_section(self, report, profile=None) -> str:
        """Telemetry table derived from the run's telemetry.csv (drop fabricated values)."""
        stats = self._load_run_telemetry(report.run_dir)

        empty = ("<section class=\"section collapsible\" data-collapsed=\"true\"><h2 class=\"section-title\" tabindex=\"0\" role=\"button\" aria-expanded=\"false\">Telemetry "
                 f"insights ({_loader.resolve_profile(profile,).codename})</h2><div class=\"section-body\"><div class=\"table-wrap\"><table><tbody>"
                 "<tr><td class=\"empty\">No telemetry CSV recorded for this run.</td>"
                 "</tr></tbody></table></div></div></section>")
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
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">Telemetry insights (the device APU)</h2>
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


