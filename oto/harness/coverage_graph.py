#!/usr/bin/env python3
"""Coverage graphs: the problem space as a 2D picture, and what is unexplored.

Owns: the 2D reduction of the legal geometry space (macro-tile area x
accumulators per thread), the SVG rendering of that grid, the local
extrema (the peaks and the traps) on it, and the index page that ties the
figures together.

Does NOT own: the legal space itself (oto.harness.coverage_map), the corpus
(oto.harness.kernel_db), the candidate deck (oto.harness.candidate_rows) or
the verdicts (oto.metrics.ab_audit).
Public API: legal_geometries, measured_geometries, coverage_row, main.

Why a 2D picture: the corpus is a *thin sample* of a large legal space --
8-13 % of it -- and that number is unreadable on its own. Projected onto
(macro-tile area, accumulators per thread), the space becomes a small grid
whose shape is the hardware's own: a wide, low-accumulator band, a narrow
high-accumulator band, and the corner nobody ever visits. Painting the
measured part of that grid with the value it reached shows, in one picture,
where the search has been and where it has not.

The grid, per cell:

* **x** -- the macro-tile area (elements), bucketed by power of two;
* **y** -- the accumulators per thread (TT0*TT1*weight), bucketed by power
  of two;
* **colour** -- the best measured seed-median in that bucket (dark = slow,
  bright = fast), blank where nothing was measured;
* **hatched** -- legal but never measured (the unexplored part);
* **rings** -- the local maxima (peaks) and the local minima (traps): a
  measured bucket whose measured neighbours are all better (a trap: the
  search keeps falling back to it) or all worse (a peak).

CPU only, read-only, and it writes only into
``<codename>_results/analysis/coverage/``. No dependency beyond the standard
library: the SVG is written by hand, so there is nothing to install.

    python3 -m oto.harness.coverage_graph                     # every cell
    python3 -m oto.harness.coverage_graph --family SS         # one family
    python3 -m oto.harness.coverage_graph --cell HH:256       # one cell
    python3 -m oto.harness.coverage_graph --no-svg            # numbers only
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import itertools

from oto.device.peaks import FAMILY_DTYPE_CHAR
from oto.harness.coverage_map import (
    _DEFAULT_CELLS,
    coverage_row,
    legal_geometries,
    measured_geometries,
)
from oto.runners.paths import results_rel

#: Where the figures go (and the index that lists them).
OUT_DIR_REL = results_rel("analysis", "coverage")

#: The power-of-two buckets of the two axes.
AREA_BUCKETS = (1024, 2048, 4096, 8192, 16384, 32768, 65536)
ACC_BUCKETS = (4, 8, 16, 32, 64, 128, 256)

#: The value ramp: (stop, colour) pairs, interpolated.
_RAMP = ((0.0, "#1b2a4a"), (0.25, "#25628f"), (0.5, "#38a08a"),
         (0.75, "#f2d357"), (1.0, "#f26b3a"))

#: The SVG geometry.
_CELL = 44          # pixel size of one bucket
_MARGIN_L = 96      # room for the y-axis labels
_MARGIN_T = 78      # room for the title
_MARGIN_B = 64      # room for the x-axis labels and the legend


def _bucket(value: int, buckets: Sequence[int]) -> int | None:
    """The bucket a value falls in (the largest edge not above it).

    A floor, not a ceiling: the axis label then reads as "8k" meaning
    "8k-ish", and a 96x96 tile (9216 elements) lands in the 8k column
    rather than being counted as a 16k tile.

    Args:
        value: The measured quantity.
        buckets: The bucket edges, ascending.

    Returns:
        The bucket, or None when the value falls outside the axis.
    """
    chosen = None
    for edge in buckets:
        if value >= edge:
            chosen = edge
        else:
            break
    return chosen


def _weight(family: str) -> int:
    """The accumulator VGPRs per element for a family (1 S, 2 D, 4 C, 8 Z)."""
    char = FAMILY_DTYPE_CHAR.get(family, "S")
    return {"S": 1, "H": 1, "D": 2, "C": 4, "Z": 8}.get(char, 1)


def _grid(family: str, legal: Iterable[Sequence[Any]],
          measured: dict[tuple[Any, ...], float]
          ) -> dict[tuple[int, int], dict[str, Any]]:
    """The 2D projection: bucket -> {legal, value, geometries}.

    Args:
        family: The family key (for the accumulator weight).
        legal: The legal geometries (tile, thread tile, vw, du).
        measured: The measured geometries of the cell.

    Returns:
        ``(area_bucket, acc_bucket) -> {"legal": bool, "value": float,
        "n_legal": int, "n_measured": int}``.
    """
    weight = _weight(family)
    grid: dict[tuple[int, int], dict[str, Any]] = {}
    for geom, _value in ((g, None) for g in legal):
        area = _area_of(geom)
        acc = _acc_of(geom, weight)
        if area is None or acc is None:
            continue
        key = (area, acc)
        cell = grid.setdefault(key, {"legal": True, "value": 0.0,
                                     "n_legal": 0, "n_measured": 0})
        cell["n_legal"] += 1
    for geom, value in measured.items():
        area = _area_of(geom)
        acc = _acc_of(geom, weight)
        if area is None or acc is None:
            continue
        key = (area, acc)
        cell = grid.setdefault(key, {"legal": True, "value": 0.0,
                                     "n_legal": 0, "n_measured": 0})
        cell["n_measured"] += 1
        cell["value"] = max(cell["value"], value)
    return grid


def _area_of(geom: Sequence[Any]) -> int | None:
    """The macro-tile area of a geometry, bucketed."""
    tile = str(geom[0])
    try:
        mt0, mt1 = (int(x) for x in tile.split("x")[:2])
    except (ValueError, IndexError):
        return None
    return _bucket(mt0 * mt1, AREA_BUCKETS)


def _acc_of(geom: Sequence[Any], weight: int) -> int | None:
    """The accumulators per thread of a geometry, bucketed."""
    tt = str(geom[1])
    try:
        tt0, tt1 = (int(x) for x in tt.split("x")[:2])
    except (ValueError, IndexError):
        return None
    return _bucket(tt0 * tt1 * weight, ACC_BUCKETS)


def _extrema(grid: dict[tuple[int, int], dict[str, Any]]
             ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The local maxima and the local minima of the measured grid.

    A measured bucket is a **local minimum** (a trap) when every measured
    neighbour is faster, and a **local maximum** (a peak) when every measured
    neighbour is slower. Buckets with fewer than two measured neighbours are
    not called either -- there is nothing to compare them against.

    Args:
        grid: The projected grid.

    Returns:
        (peaks, traps), each a list of (area, acc) buckets.
    """
    peaks: list[tuple[int, int]] = []
    traps: list[tuple[int, int]] = []
    for (area, acc), cell in grid.items():
        if not cell["n_measured"]:
            continue
        neighbours = []
        for da, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            other = grid.get((_step(area, da), _step(acc, dc)))
            if other and other["n_measured"]:
                neighbours.append(other["value"])
        if len(neighbours) < 2:
            continue
        if all(v < cell["value"] for v in neighbours):
            peaks.append((area, acc))
        elif all(v > cell["value"] for v in neighbours):
            traps.append((area, acc))
    return peaks, traps


def _step(bucket: int, direction: int) -> int:
    """The neighbouring bucket (the buckets are consecutive powers of two)."""
    for index, edge in enumerate(AREA_BUCKETS if bucket in AREA_BUCKETS
                                 else ACC_BUCKETS):
        if edge == bucket:
            neighbour = index + direction
            if 0 <= neighbour < len(AREA_BUCKETS if bucket in AREA_BUCKETS
                                    else ACC_BUCKETS):
                return (AREA_BUCKETS if bucket in AREA_BUCKETS
                        else ACC_BUCKETS)[neighbour]
    return bucket


def _ramp(fraction: float) -> str:
    """A colour on the value ramp."""
    fraction = max(0.0, min(1.0, fraction))
    for (lo, clo), (hi, chi) in itertools.pairwise(_RAMP):
        if fraction <= hi:
            span = (hi - lo) or 1.0
            t = (fraction - lo) / span
            return _mix(clo, chi, t)
    return _RAMP[-1][1]


def _mix(c1: str, c2: str, t: float) -> str:
    """Two hex colours mixed."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b, strict=False))


def _esc(text: str) -> str:
    """XML-escape a string."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _rect(x: float, y: float, w: float, h: float, fill: str,
          extra: str = "") -> str:
    """One SVG rectangle."""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" {extra}/>')


def _text(x: float, y: float, content: str, size: int = 11,
          fill: str = "#1b1b1b", anchor: str = "start",
          weight: str = "normal") -> str:
    """One SVG text run."""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="ui-monospace, '
            f'monospace" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{_esc(content)}</text>')


def _figure(family: str, shape: str, row: dict[str, Any],
            grid: dict[tuple[int, int], dict[str, Any]],
            peaks: Sequence[tuple[int, int]],
            traps: Sequence[tuple[int, int]]) -> str:
    """The SVG of one cell's coverage grid.

    Args:
        family: The family key.
        shape: The cell shape.
        row: The coverage row (the counts and the best measured).
        grid: The projected grid.
        peaks: The local maxima.
        traps: The local minima.

    Returns:
        The SVG document.
    """
    width = _MARGIN_L + _CELL * len(AREA_BUCKETS) + 230
    height = _MARGIN_T + _CELL * len(ACC_BUCKETS) + _MARGIN_B
    best = row["best_measured"] or 1.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
           f'height="{height}" viewBox="0 0 {width} {height}">',
           _rect(0, 0, width, height, "#ffffff"),
           '<defs><pattern id="gap" width="6" height="6" '
           'patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
           '<rect width="6" height="6" fill="#f2f2f2"/>'
           '<line x1="0" y1="0" x2="0" y2="6" stroke="#c9c9c9" '
           'stroke-width="2"/></pattern></defs>']
    out.append(_text(_MARGIN_L, 28, f"{family}  {shape}", size=17, weight="bold"))
    out.append(_text(_MARGIN_L, 48, f"legal geometries {row['n_legal']}   "
                        f"measured {row['n_measured']}   "
                        f"unexplored {row['n_legal'] - row['n_measured']} "
                        f"({(1 - row['n_measured'] / row['n_legal']) * 100:.0f}%)",
                        size=12, fill="#555555"))
    out.append(_text(_MARGIN_L, 64, f"best measured {row['best_measured']:.1f}   "
                        f"peaks {len(peaks)}   traps {len(traps)}", size=12,
                        fill="#555555"))
    out += _grid_svg(grid, best, peaks, traps)
    out += _axes_svg()
    out += _legend_svg(best, row)
    out.append("</svg>")
    return "\n".join(out)


def _grid_svg(grid: dict[tuple[int, int], dict[str, Any]], best: float,
              peaks: Sequence[tuple[int, int]],
              traps: Sequence[tuple[int, int]]) -> list[str]:
    """The painted grid, with the peaks and the traps marked."""
    out: list[str] = []
    for (area, acc), cell in grid.items():
        x = _MARGIN_L + AREA_BUCKETS.index(area) * _CELL
        y = _MARGIN_T + (len(ACC_BUCKETS) - 1 - ACC_BUCKETS.index(acc)) * _CELL
        if cell["n_measured"]:
            value = cell["value"] / best
            out.append(_rect(x, y, _CELL - 1, _CELL - 1, _ramp(value)))
        else:
            out.append(_rect(x, y, _CELL - 1, _CELL - 1, "url(#gap)"))
    for area, acc in peaks:
        x = _MARGIN_L + AREA_BUCKETS.index(area) * _CELL
        y = _MARGIN_T + (len(ACC_BUCKETS) - 1 - ACC_BUCKETS.index(acc)) * _CELL
        out.append(_rect(x + 3, y + 3, _CELL - 7, _CELL - 7, "none",
                         extra='stroke="#0b6b2f" stroke-width="2.5"'))
    for area, acc in traps:
        x = _MARGIN_L + AREA_BUCKETS.index(area) * _CELL
        y = _MARGIN_T + (len(ACC_BUCKETS) - 1 - ACC_BUCKETS.index(acc)) * _CELL
        out.append(_rect(x + 3, y + 3, _CELL - 7, _CELL - 7, "none",
                         extra='stroke="#b00020" stroke-width="2.5"'))
    return out


def _legend_svg(best: float, row: dict[str, Any]) -> list[str]:
    """The key: the value ramp, the hatch, and the two rings."""
    x = _MARGIN_L + _CELL * len(AREA_BUCKETS) + 24
    y = _MARGIN_T + 6
    out = [_text(x, y, "measured value", size=11, weight="bold")]
    out.extend(_rect(x + index * 18, y + 8, 17, 14, _ramp(index / 6.0))
               for index in range(7))
    out.append(_text(x, y + 36, "slow", size=10, fill="#555555"))
    out.append(_text(x + 6 * 18 + 6, y + 36, "fast", size=10, fill="#555555",
                     anchor="end"))
    out.append(_text(x, y + 58, f"best {row['best_measured']:.1f} GFLOPS",
                     size=10, fill="#555555"))
    out.append(_rect(x, y + 70, 17, 14, "url(#gap)"))
    out.append(_text(x + 24, y + 82, "legal, never measured", size=10,
                     fill="#333333"))
    out.append(_rect(x + 2, y + 94, 13, 13, "none",
                     extra='stroke="#0b6b2f" stroke-width="2.5"'))
    out.append(_text(x + 24, y + 106, "local maximum (peak)", size=10,
                     fill="#333333"))
    out.append(_rect(x + 2, y + 118, 13, 13, "none",
                     extra='stroke="#b00020" stroke-width="2.5"'))
    out.append(_text(x + 24, y + 130, "local minimum (trap)", size=10,
                     fill="#333333"))
    return out


def _axes_svg() -> list[str]:
    """The axis labels and the legend."""
    out: list[str] = []
    for index, area in enumerate(AREA_BUCKETS):
        x = _MARGIN_L + index * _CELL + (_CELL - 1) / 2
        out.append(_text(x, _MARGIN_T + _CELL * len(ACC_BUCKETS) + 18,
                         f"{area // 1024}k", anchor="middle", size=10,
                         fill="#555555"))
    out.append(_text(_MARGIN_L + _CELL * len(AREA_BUCKETS) / 2,
                     _MARGIN_T + _CELL * len(ACC_BUCKETS) + 36,
                     "macro-tile area (elements)", anchor="middle", size=11,
                     fill="#333333"))
    for index, acc in enumerate(ACC_BUCKETS):
        y = _MARGIN_T + (len(ACC_BUCKETS) - 1 - index) * _CELL + (_CELL - 1) / 2 + 4
        out.append(_text(_MARGIN_L - 10, y, str(acc), anchor="end", size=10,
                         fill="#555555"))
    mid = _MARGIN_T + _CELL * len(ACC_BUCKETS) / 2
    out.append(f'<text x="22" y="{mid:.1f}" font-family="ui-monospace, '
               f'monospace" font-size="11" fill="#333333" text-anchor="middle" '
               f'transform="rotate(-90 22 {mid:.1f})">accumulators/thread</text>')
    return out


def _summary(family: str, shape: str, row: dict[str, Any],
             peaks: Sequence[tuple[int, int]],
             traps: Sequence[tuple[int, int]]) -> str:
    """One line of the text summary."""
    free = row["n_legal"] - row["n_measured"]
    return (f"{family:7} {shape:16} {row['n_legal']:5} {row['n_measured']:5} "
            f"{free:5} {free / max(1, row['n_legal']) * 100:6.1f}% "
            f"{row['best_measured']:8.1f} {len(peaks):5} {len(traps):5}")


def _index_page(entries: list[dict[str, Any]], out_dir: Path) -> None:
    """The index: every figure with its numbers."""
    rows = [
        f'<tr><td>{html.escape(entry["family"])}</td>'
        f'<td>{html.escape(entry["shape"])}</td>'
        f'<td>{entry["n_legal"]}</td><td>{entry["n_measured"]}</td>'
        f'<td>{entry["unexplored"]}</td>'
        f'<td>{entry["pct_unexplored"]:.1f}%</td>'
        f'<td>{entry["best"]:.1f}</td>'
        f'<td>{entry["peaks"]}</td><td>{entry["traps"]}</td>'
        f'<td><img src="{entry["file"]}" width="520"></td></tr>'
        for entry in entries]
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>oto coverage graphs</title>
<style>
body {{ font: 13px ui-monospace, monospace; margin: 24px; color: #1b1b1b; }}
table {{ border-collapse: collapse; }}
td, th {{ border: 1px solid #ddd; padding: 6px 10px; vertical-align: top; }}
th {{ background: #f4f4f4; text-align: left; }}
h1 {{ font-size: 18px; }}
</style></head><body>
<h1>oto coverage graphs -- the legal geometry space, and what is unexplored</h1>
<p>Each figure is one contract cell. x: macro-tile area (elements, bucketed by
power of two). y: accumulators per thread. Dark = slow, bright = fast.
Hatched = legal but never measured. Green ring = a local maximum (a peak).
Red ring = a local minimum (a trap: every measured neighbour is faster).</p>
<table>
<tr><th>family</th><th>shape</th><th>legal</th><th>measured</th>
<th>unexplored</th><th>% unexplored</th><th>best</th><th>peaks</th>
<th>traps</th><th>figure</th></tr>
{''.join(rows)}
</table></body></html>"""
    (out_dir / "index.html").write_text(page)


def _write_data(entries: list[dict[str, Any]], out_dir: Path) -> None:
    """The numbers behind the figures, as JSON.

    The acceptance report embeds the figures and prints their numbers; it must
    not re-derive them (the legal-space sweep takes minutes). This file is
    the hand-off between the two.
    """
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": entries,
    }
    (out_dir / "coverage.json").write_text(json.dumps(payload, indent=1))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", action="append", help="limit to a family")
    ap.add_argument("--cell", action="append",
                    help="one cell, 'FAMILY:side' (repeatable)")
    ap.add_argument("--base-dir", "--base", type=Path, default=None,
                    help="repo root override (default: this file's parent of package)")
    ap.add_argument("--out", default=None,
                    help="where the figures go (default: <base-dir>/<codename>_results/analysis/coverage)")
    ap.add_argument("--no-svg", action="store_true",
                    help="print the numbers only")
    args = ap.parse_args(argv)

    fams = list(args.family) if args.family else sorted(_DEFAULT_CELLS)
    only: list[tuple[str, int]] = []
    for spec in args.cell or []:
        fam, _, side = spec.partition(":")
        only.append((fam, int(side)))
    if only:
        fams = sorted({f for f, _ in only})
    measured = measured_geometries()
    out_dir = Path(args.out) if args.out else ((Path(args.base_dir) if args.base_dir else _HERE) / OUT_DIR_REL)
    entries: list[dict[str, Any]] = []
    print(f"{'cell':24} {'legal':>5} {'meas':>5} {'unexp':>5} "
          f"{'%unexp':>7} {'best':>8} {'peaks':>5} {'traps':>5}")
    for family in fams:
        legal = legal_geometries(family)
        for shape in _DEFAULT_CELLS.get(family, []):
            if only and (family, int(shape.split("x")[0])) not in only:
                continue
            cell_measured = measured.get((family, shape), {})
            row = coverage_row(family, shape, legal, cell_measured)
            grid = _grid(family, legal, cell_measured)
            peaks, traps = _extrema(grid)
            print(_summary(family, shape, row, peaks, traps))
            entry = {"family": family, "shape": shape,
                     "n_legal": row["n_legal"], "n_measured": row["n_measured"],
                     "unexplored": row["n_legal"] - row["n_measured"],
                     "pct_unexplored": (1 - row["n_measured"] / row["n_legal"]) * 100
                     if row["n_legal"] else 0.0,
                     "best": row["best_measured"], "peaks": len(peaks),
                     "traps": len(traps),
                     "file": f"{family}_{shape}.svg"}
            entries.append(entry)
            if not args.no_svg:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / entry["file"]).write_text(
                    _figure(family, shape, row, grid, peaks, traps))
    if not args.no_svg:
        out_dir.mkdir(parents=True, exist_ok=True)
        _index_page(entries, out_dir)
        _write_data(entries, out_dir)
        print(f"\nwrote {len(entries)} figure(s) + index.html + coverage.json"
              f" -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
