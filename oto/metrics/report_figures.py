#!/usr/bin/env python3
"""The acceptance report's problem-space coverage section.

Owns: ``coverage_rows`` (the per-cell coverage numbers, read from the
coverage tool's hand-off file) and ``coverage_section`` (the rendered
section: a dense summary table and the figure grid).

Does NOT own: the figures (oto.harness.coverage_graph writes them), the
report payload (oto.metrics.report_models) or the stylesheet
(oto.metrics.report_css).

Why the section exists: the acceptance report said *how fast* the best kernel
on each cell is, and nothing about *how much of the space was searched*. Those
are different questions, and the second one is the one that explains a run
that "improved nothing": the corpus is a thin strip of a much larger legal
space, and the report now shows it.

The numbers come from ``gfx90c_results/analysis/coverage/coverage.json`` --
the coverage tool's hand-off. The report never re-derives them (the legal-space
sweep takes minutes) and says so plainly when the file is absent.

CPU only, read-only.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Where the coverage tool writes its figures and its hand-off file.
COVERAGE_DIR = Path("gfx90c_results") / "analysis" / "coverage"
DATA_NAME = "coverage.json"


def coverage_dir(base_dir: Path) -> Path:
    """The coverage artefact directory for a repo root."""
    return Path(base_dir) / COVERAGE_DIR


def coverage_rows(base_dir: Path) -> List[Dict[str, Any]]:
    """The per-cell coverage rows, or an empty list when they are absent.

    Args:
        base_dir: The repo root.

    Returns:
        One dict per cell: family, shape, legal/measured/unexplored counts,
        the best measured value, the peaks and the traps, and the figure file.
    """
    path = coverage_dir(base_dir) / DATA_NAME
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    rows = payload.get("rows") if isinstance(payload, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _relative_src(base_dir: Path, html_path: Path, name: str) -> str:
    """The figure's path relative to the report file, for an <img src>."""
    target = coverage_dir(base_dir) / name
    try:
        rel = os.path.relpath(target, Path(html_path).parent)
    except ValueError:
        rel = str(target)
    return html.escape(rel.replace(os.sep, "/"))


def _summary_table(rows: List[Dict[str, Any]], base_dir: Path,
                   html_path: Path) -> str:
    """The dense per-cell coverage table."""
    body = ""
    for row in rows:
        legal = row.get("n_legal", 0) or 0
        measured = row.get("n_measured", 0) or 0
        pct = row.get("pct_unexplored", 0.0) or 0.0
        body += f"""
                <tr>
                    <td class="mono strong">{html.escape(str(row.get('family', '')))}</td>
                    <td class="mono">{html.escape(str(row.get('shape', '')))}</td>
                    <td class="num">{legal}</td>
                    <td class="num">{measured}</td>
                    <td class="num strong">{legal - measured}</td>
                    <td class="num"><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz1" style="width: {min(100.0, pct):.1f}%;"></span></span><span class="bar-label">{pct:.1f}%</span></span></td>
                    <td class="num strong">{row.get('best', 0.0):.1f}</td>
                    <td class="num">{row.get('peaks', 0)}</td>
                    <td class="num">{row.get('traps', 0)}</td>
                </tr>"""
    return f"""
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Family</th>
                            <th>Cell</th>
                            <th>Legal geometries</th>
                            <th>Measured</th>
                            <th>Unexplored</th>
                            <th>% unexplored</th>
                            <th>Best measured</th>
                            <th>Peaks</th>
                            <th>Traps</th>
                        </tr>
                    </thead>
                    <tbody>{body}
                    </tbody>
                </table>
            </div>"""


def _figure_grid(rows: List[Dict[str, Any]], base_dir: Path,
                 html_path: Path) -> str:
    """The grid of per-cell coverage figures."""
    cells = ""
    for row in rows:
        name = str(row.get("file", ""))
        if not name:
            continue
        src = _relative_src(base_dir, html_path, name)
        cells += f"""
                <figure class="figure">
                    <img src="{src}" alt="Coverage of the legal geometry space for {html.escape(str(row.get('family', '')))} {html.escape(str(row.get('shape', '')))}" loading="lazy">
                    <figcaption class="mono">{html.escape(str(row.get('family', '')))} {html.escape(str(row.get('shape', '')))} &middot; {row.get('n_measured', 0)}/{row.get('n_legal', 0)} measured &middot; {row.get('peaks', 0)} peak / {row.get('traps', 0)} trap</figcaption>
                </figure>"""
    return f"""<div class="figure-grid">{cells}</div>"""


def coverage_section(base_dir: Path, html_path: Path) -> str:
    """The rendered problem-space coverage section.

    Args:
        base_dir: The repo root (where the coverage artefacts live).
        html_path: Where the report is being written (the figures are linked
            relative to it, so the report works from the run directory too).

    Returns:
        The section HTML. When the artefacts are absent it says so and names
        the command that produces them.
    """
    rows = coverage_rows(base_dir)
    if not rows:
        return """
        <section class="section">
            <h2 class="section-title">Problem-space coverage</h2>
            <div class="table-wrap">
                <table><tbody>
                <tr><td class="empty">No coverage figures yet &mdash; run
                <code>python3 -m oto.harness.coverage_graph</code> to sweep the
                legal geometry space and draw them.</td></tr>
                </tbody></table>
            </div>
        </section>
        """
    total_legal = sum(r.get("n_legal", 0) or 0 for r in rows)
    total_measured = sum(r.get("n_measured", 0) or 0 for r in rows)
    total_open = sum(r.get("unexplored", 0) or 0 for r in rows)
    share = (total_open / total_legal * 100.0) if total_legal else 0.0
    return f"""
        <section class="section">
            <h2 class="section-title">Problem-space coverage</h2>
            <p class="section-note">The legal geometry space of every cell, and
            the part of it the corpus has measured. <strong>{share:.0f}% of the
            legal geometries have never been run</strong>
            ({total_open} of {total_legal}); a green ring is a local maximum
            (a peak), a red ring a local minimum (a trap &mdash; a legal
            configuration whose measured neighbours are all faster).</p>
            {_summary_table(rows, base_dir, html_path)}
            {_figure_grid(rows, base_dir, html_path)}
        </section>
        """
