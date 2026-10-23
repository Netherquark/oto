#!/usr/bin/env python3
"""The acceptance report's problem-space coverage section.

Owns: ``coverage_rows`` (the per-cell coverage numbers, read from the
coverage tool's hand-off file) and ``coverage_section`` (the rendered
section: one grouped coverage table, plus the maps in one appendix).

Does NOT own: the figures (oto.harness.coverage_graph writes them), the
report payload (oto.metrics.report_models) or the stylesheet
(oto.metrics.report_css).
Public API: coverage_rows, coverage_section, coverage_dir.

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


def _cell_share(row: Dict[str, Any]) -> float:
    """The unexplored share of ONE cell's legal space, in percent.

    The legal space is the same for every cell of a family (it does not depend
    on the shape), while the *measured* geometries differ per cell (the corpus
    ran each geometry on the cells it was scheduled for). So the ratio is a
    per-cell number and must never be summed across cells -- doing so divides
    a cell's own measurement count by the family's whole space.
    """
    legal = row.get("n_legal", 0) or 0
    measured = row.get("n_measured", 0) or 0
    return (1.0 - measured / legal) * 100.0 if legal else 0.0


def _relative_src(base_dir: Path, html_path: Path, name: str) -> str:
    """The figure's path relative to the report file, for an <img src>."""
    target = coverage_dir(base_dir) / name
    try:
        rel = os.path.relpath(target, Path(html_path).parent)
    except ValueError:
        rel = str(target)
    return html.escape(rel.replace(os.sep, "/"))


def _family_meta(items: List[Dict[str, Any]]) -> str:
    """One family's coverage summary, for its group row in the cell table."""
    legal = max(r.get("n_legal", 0) or 0 for r in items)
    measured = [r.get("n_measured", 0) or 0 for r in items]
    shares = sorted(_cell_share(r) for r in items)
    lo, hi = min(measured), max(measured)
    span = f"{lo}" if lo == hi else f"{lo}-{hi}"
    share = (f"{shares[0]:.0f}%" if abs(shares[0] - shares[-1]) < 0.5
             else f"{shares[0]:.0f}-{shares[-1]:.0f}%")
    peaks = sum(r.get("peaks", 0) or 0 for r in items)
    traps = sum(r.get("traps", 0) or 0 for r in items)
    return (f"{len(items)} cell{'' if len(items) == 1 else 's'} &middot; "
            f"{legal} legal per cell &middot; {span} measured per cell "
            f"&middot; {share} unexplored &middot; "
            f"{peaks} peak{'' if peaks == 1 else 's'} / "
            f"{traps} trap{'' if traps == 1 else 's'}")


def _coverage_table(rows: List[Dict[str, Any]]) -> str:
    """The per-cell coverage table, grouped by family.

    The family group row is a non-interactive summary. It replaces the old
    second table of family summaries *and* the seven per-family ``<details>``
    blocks: the data and the family roll-up now live in one hierarchy.
    """
    families: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        families.setdefault(str(row.get("family", "")), []).append(row)

    body = ""
    for family in sorted(families):
        items = families[family]
        body += f"""
            <tbody class="coverage-group">
                <tr class="group-row">
                    <th colspan="7" scope="rowgroup">
                        <span class="group-name mono strong">{html.escape(family)}</span>
                        <span class="group-meta">{_family_meta(items)}</span>
                    </th>
                </tr>"""
        for row in items:
            legal = row.get("n_legal", 0) or 0
            measured = row.get("n_measured", 0) or 0
            unexplored = row.get("unexplored", legal - measured)
            pct = row.get("pct_unexplored", _cell_share(row)) or 0.0
            body += f"""
                <tr class="coverage-row">
                    <th scope="row" class="mono">{html.escape(str(row.get('shape', '')))}</th>
                    <td class="num">{legal}</td>
                    <td class="num">{measured}</td>
                    <td class="num strong">{unexplored}</td>
                    <td><span class="bar-wrap"><span class="bar"><span class="bar-fill bar-viz1" style="width: {min(100.0, pct):.1f}%;"></span></span><span class="bar-label">{pct:.1f}%</span></span></td>
                    <td class="num">{row.get('peaks', 0)}</td>
                    <td class="num">{row.get('traps', 0)}</td>
                </tr>"""
        body += "            </tbody>"
    return f"""
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Family / cell</th>
                            <th>Legal geometries</th>
                            <th>Measured</th>
                            <th>Unexplored</th>
                            <th>% unexplored</th>
                            <th>Peaks</th>
                            <th>Traps</th>
                        </tr>
                    </thead>
                    {body}
                </table>
            </div>"""


def _figure_tile(row: Dict[str, Any], base_dir: Path,
                 html_path: Path) -> str:
    """One figure tile."""
    name = str(row.get("file", ""))
    if not name:
        return ""
    src = _relative_src(base_dir, html_path, name)
    family = html.escape(str(row.get("family", "")))
    shape = html.escape(str(row.get("shape", "")))
    return f"""
                <figure class="figure">
                    <img src="{src}" alt="Coverage of the legal geometry space for {family} {shape}" width="634" height="450" loading="lazy">
                    <figcaption class="mono">{shape}</figcaption>
                </figure>"""


def _coverage_appendix(rows: List[Dict[str, Any]], base_dir: Path,
                       html_path: Path) -> str:
    """The coverage maps, in one appendix instead of seven disclosures.

    The table above is the primary data. The maps are supporting evidence, so
    they sit behind one clearly-labelled native disclosure, grouped by family
    with a heading rather than another layer of controls.
    """
    families: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        families.setdefault(str(row.get("family", "")), []).append(row)
    groups = ""
    for family in sorted(families):
        items = families[family]
        figures = "".join(_figure_tile(r, base_dir, html_path) for r in items)
        groups += f"""
            <details class="figure-family">
                <summary class="figure-family-title">
                    <span class="mono strong">{html.escape(family)}</span>
                    <span class="secondary">{len(items)} cell{'' if len(items) == 1 else 's'}</span>
                </summary>
                <div class="figure-grid">{figures}</div>
            </details>"""
    return f"""
            <details class="figure-appendix">
                <summary>
                    <span class="figure-appendix-title">Coverage maps</span>
                    <span class="figure-appendix-meta">{len(rows)} cells &middot; open to inspect each cell&apos;s legal geometry space</span>
                </summary>
                <div class="figure-appendix-body">{groups}
                </div>
            </details>"""


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
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">
                Problem-space coverage
            </h2>
            <div class="section-body">
                <div class="table-wrap">
                    <table><tbody>
                    <tr><td class="empty">No coverage figures yet &mdash; run
                    <code>python3 -m oto.harness.coverage_graph</code> to sweep the
                    legal geometry space and draw them.</td></tr>
                    </tbody></table>
                </div>
            </div>
        </section>
        """
    shares = sorted(_cell_share(r) for r in rows)
    median = shares[len(shares) // 2] if shares else 0.0
    return f"""
        <section class="section collapsible" data-collapsed="true">
            <h2 class="section-title" tabindex="0" role="button" aria-expanded="false">
                Problem-space coverage
            </h2>
            <div class="section-body">
                <p class="section-note">Each row is one cell; the legal space is
                family-wide, so the unexplored share is per cell. <strong>Median
                {median:.0f}% of each cell&apos;s legal geometries have never been
                run.</strong> A green ring is a peak; a red ring is a trap. The maps
                are in the appendix below the table.</p>
                {_coverage_table(rows)}
                {_coverage_appendix(rows, base_dir, html_path)}
            </div>
        </section>
        """
