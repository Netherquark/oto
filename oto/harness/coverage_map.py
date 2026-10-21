#!/usr/bin/env python3
"""Coverage map: what the corpus has measured, and what it has not.

Owns: the *problem space* view of the corpus -- for every (family, contract
cell), the set of geometries the real gate admits, which of them the corpus has
measured, the best measured value per geometry, and the legal-but-unmeasured
geometries ranked by how well their neighbours measured. That last number is the
local-minimum finder: a geometry whose siblings (same tile, other thread tile;
same thread tile, other tile) measure well is the one worth running next.

Does NOT own: the gate (oto.tensile.gates), the corpus (oto.harness.kernel_db),
the candidate deck (oto.harness.candidate_rows), the per-cell winners
(oto.harness.resolve_cells) or the verdicts (oto.metrics.ab_audit).

Public API: legal_geometries, measured_geometries, coverage_row, neighbour_score,
main.

Why it exists: candidate generation asks "has this cell, at this geometry, on
this axis, already been measured -- and how did it score?". The corpus census
(oto.harness.corpus_census) answers the second half for *what exists*; this
answers the first half for the *whole legal space*, so a run spends its budget
on unexplored ground instead of re-measuring a neighbour of a winner.

CPU only, read-only, no Tensile, no GPU.

    python3 -m oto.harness.coverage_map                 # every family
    python3 -m oto.harness.coverage_map --family SS
    python3 -m oto.harness.coverage_map --cell SS:256 --top 12
    python3 -m oto.harness.coverage_map --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.harness.kernel_db import read_kernel_db  # noqa: E402
from oto.device.peaks import FAMILY_SHAPES  # noqa: E402
from oto.harness.candidate_pool import _base_config, _strip_not_forwarded  # noqa: E402
from oto.tensile.candidate import CandidateGenerator  # noqa: E402

#: The thread tiles the harness can express. This is the set the CORPUS has
#: measured (plus the tile-frontier sweep's set), not an invented grid: the
#: 6x6 thread tile carries the SS:256 winner (96x96/6x6 = 412 GFLOPS), so a
#: tool that omits it cannot see the cell's best geometry at all.
THREAD_TILES = ("16x8", "8x16", "16x4", "4x16", "8x8", "8x4", "4x8",
                "4x4", "2x4", "4x2", "6x6", "4x6", "6x4", "8x6", "6x8",
                "2x2", "2x8", "8x2", "3x3")

#: Macro-tile sides the sweep walks. 32..256 step 16 covers every tile the
#: corpus uses plus the neighbours around them.
TILE_SIDES = tuple(range(32, 257, 16))

#: Vector widths per family, capped by the 16 B global-load rule.
VECTOR_WIDTHS = {"SS": (4, 2), "HH": (8, 4, 2), "CC": (2, 1), "DD": (2, 1),
                 "ZZ": (1,), "HH_HPA": (8, 4, 2), "HS_HPA": (4, 2)}

#: DepthU values the deck uses.
DEPTHS = (8, 16)

#: The assertion levels that open the load-divisibility frontier.
ASSERTIONS = (0, 2)

#: The cell shapes the coverage map reports per family (the contract grid).
_DEFAULT_CELLS = {fam: [f"{s}x{s}x{s}" for s in sides]
                  for fam, sides in FAMILY_SHAPES.items()}

#: A geometry key: (macro tile, thread tile, vector width, depth).
Geometry = Tuple[str, str, int, int]


def _generator() -> CandidateGenerator:
    return CandidateGenerator(_HERE)


def _legal(fam: str, geom: Geometry, extra: Optional[Dict[str, Any]] = None
           ) -> Tuple[bool, str]:
    """One geometry through the real generator gate."""
    tile, tt, vw, du = geom
    config = {**_base_config(fam), "MacroTile": f"{tile}x{du}", "ThreadTile": tt,
              "VectorWidth": vw, "DepthU": du,
              "ContractionPattern": "Ailk_Bjlk", **(extra or {})}
    config, _ = _strip_not_forwarded(config)
    return _generator().validate_config(config)


def legal_geometries(fam: str) -> List[Geometry]:
    """Every geometry the gate admits for a family (assertion level 0 or 2).

    Args:
        fam: Canonical family key ("SS", "HH", "CC", ...).

    Returns:
        The legal geometries, de-duplicated and sorted.
    """
    out: set = set()
    gen = _generator()
    for mt0 in TILE_SIDES:
        for mt1 in TILE_SIDES:
            tile = f"{mt0}x{mt1}"
            for tt in THREAD_TILES:
                t0, t1 = (int(x) for x in tt.split("x"))
                if mt0 % t0 or mt1 % t1:
                    continue
                threads = (mt0 // t0) * (mt1 // t1)
                if threads > 1024 or threads % 64:
                    continue
                for vw in VECTOR_WIDTHS.get(fam, (2,)):
                    for du in DEPTHS:
                        for level in ASSERTIONS:
                            extra = {} if not level else {
                                "AssertFree0ElementMultiple": level,
                                "AssertFree1ElementMultiple": level}
                            config = {**_base_config(fam),
                                      "MacroTile": f"{tile}x{du}",
                                      "ThreadTile": tt, "VectorWidth": vw,
                                      "DepthU": du,
                                      "ContractionPattern": "Ailk_Bjlk",
                                      **extra}
                            config, _ = _strip_not_forwarded(config)
                            if gen.validate_config(config)[0]:
                                out.add((tile, tt, vw, du))
    return sorted(out)


def _dims(value: Any) -> Optional[str]:
    """A "[128, 128]" (YAML list) or "128x128" pair as "128x128"."""
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("["):
        parts = [p.strip() for p in text.strip("[]").split(",")]
        if len(parts) < 2:
            return None
        return "x".join(parts)
    if "x" in text:
        return text.lower()
    return None


#: The deck family a corpus row belongs to. The corpus attributes the
#: half-precision-accumulate kernels to family ``HH`` and tells them apart by
#: typecode alone (``HHS`` -> HH_HPA, ``HSS`` -> HS_HPA), so a cell-level map
#: keyed on the row's family would show the HPA columns as 100% unexplored
#: when they are not.
_TYPECODE_FAMILY = {"HHS": "HH_HPA", "HSS": "HS_HPA"}


def _cell_family(row: Dict[str, Any]) -> str:
    """The deck family a kernel_db row belongs to."""
    typecode = str(row.get("typecode") or "").upper()
    return _TYPECODE_FAMILY.get(typecode) or str(row.get("family") or "")


def measured_geometries(db_path: Optional[Path] = None
                         ) -> Dict[Tuple[str, str], Dict[Geometry, float]]:
    """``(family, shape) -> {geometry: best seed-median}`` from the corpus.

    Args:
        db_path: The kernel_db cache; the repo default when None.

    Returns:
        The measured geometry map, empty when the cache does not exist.
    """
    path = db_path or (_HERE / "gfx90c_results" / "analysis" / "kernel_db.json")
    if not path.exists():
        return {}
    db = json.loads(path.read_text())
    out: Dict[Tuple[str, str], Dict[Geometry, float]] = {}
    for rows in db.values():
        for r in rows:
            fam = _cell_family(r)
            shape = r.get("shape")
            mt = _dims(r.get("MacroTile"))
            tt = _dims(r.get("ThreadTile"))
            vw, du = r.get("VectorWidth"), r.get("DepthU")
            if not (fam and shape and mt and tt):
                continue
            try:
                geom = (mt, tt, int(vw), int(du))
            except (TypeError, ValueError):
                continue
            value = r.get("gflops_median") or 0.0
            cell = out.setdefault((fam, shape), {})
            if value > cell.get(geom, 0.0):
                cell[geom] = value
    return out


def neighbour_score(geom: Geometry, measured: Dict[Geometry, float]
                    ) -> float:
    """How well the *neighbours* of an unmeasured geometry measure.

    The local-minimum heuristic: a geometry is worth running when the
    geometries next to it (same tile with another thread tile, or the same
    thread tile with another tile) measure well. That is the signature of a
    local minimum: the neighbourhood is fast, the point itself is untried.

    Args:
        geom: The unmeasured geometry.
        measured: The measured geometries of the same cell.

    Returns:
        The best measured value among the neighbours (0.0 when there are none).
    """
    tile, tt, _vw, _du = geom
    mt0, _, mt1 = tile.partition("x")
    best = 0.0
    for (otile, ott, _ovw, _odu), value in measured.items():
        same_tile = otile == tile
        same_tt = ott == tt
        # A neighbour shares the tile (other thread tile) or the thread tile
        # (other tile), and is one step away in the tile grid.
        if not (same_tt or (same_tile and ott != tt)):
            continue
        if same_tt and not same_tile:
            o0, _, o1 = otile.partition("x")
            try:
                if abs(int(o0) - int(mt0)) > 32 or abs(int(o1) - int(mt1)) > 32:
                    continue
            except ValueError:
                continue
        best = max(best, value)
    return best


def coverage_row(fam: str, shape: str, legal: Sequence[Geometry],
                  measured: Dict[Geometry, float]) -> Dict[str, Any]:
    """One cell's coverage: legal space, measured part, and the gaps.

    Args:
        fam: The family key.
        shape: The cell shape ("256x256x256").
        legal: The legal geometries for the family.
        measured: The cell's measured geometries (geometry -> best median).

    Returns:
        A row with the coverage counts, the best measured value, and the
        unmeasured geometries ranked by their neighbours' score.
    """
    hit = {g: v for g, v in measured.items() if g in set(legal)}
    gaps = []
    for g in legal:
        if g in hit:
            continue
        gaps.append((neighbour_score(g, hit), g))
    gaps.sort(key=lambda x: (-x[0], x[1]))
    best = max(hit.values()) if hit else 0.0
    return {
        "family": fam,
        "shape": shape,
        "n_legal": len(legal),
        "n_measured": len(hit),
        "coverage_pct": (len(hit) / len(legal) * 100.0) if legal else 0.0,
        "best_measured": best,
        "best_geometry": max(hit, key=lambda g: hit[g]) if hit else None,
        "unmeasured": [{"geometry": list(g), "neighbour_score": s}
                       for s, g in gaps],
    }


def _fmt_geom(geom: Optional[Sequence[Any]]) -> str:
    if not geom:
        return "-"
    tile, tt, vw, du = geom
    return f"{tile:>9} {tt:>5} vw{vw} du{du}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", action="append",
                    help="limit to a family (repeatable)")
    ap.add_argument("--cell", help="one cell, 'FAMILY:side' (e.g. SS:256)")
    ap.add_argument("--top", type=int, default=8,
                    help="how many unexplored geometries to list per cell")
    ap.add_argument("--json", type=Path, help="write the map here")
    args = ap.parse_args(argv)

    fams = list(args.family) if args.family else sorted(_DEFAULT_CELLS)
    only_cell = args.cell
    if only_cell:
        fam, _, side = only_cell.partition(":")
        fams = [fam]
        side = int(side)

    measured = measured_geometries()
    rows: List[Dict[str, Any]] = []
    for fam in fams:
        legal = legal_geometries(fam)
        shapes = _DEFAULT_CELLS.get(fam, [])
        if only_cell:
            shapes = [f"{side}x{side}x{side}"]
        for shape in shapes:
            cell_measured = measured.get((fam, shape), {})
            rows.append(coverage_row(fam, shape, legal, cell_measured))

    print(f"{'cell':<18}{'legal':>7}{'meas':>7}{'cover':>8}{'best':>10}  "
          f"{'best geometry':<28} unexplored (ranked by neighbour score)")
    for row in rows:
        print(f"{row['family'] + ':' + row['shape']:<18}{row['n_legal']:>7}"
              f"{row['n_measured']:>7}{row['coverage_pct']:>7.1f}%"
              f"{row['best_measured']:>10.1f}  "
              f"{_fmt_geom(row['best_geometry']):<28} "
              f"{len(row['unmeasured'])} open")
        for gap in row["unmeasured"][:args.top]:
            print(f"    {gap['neighbour_score']:>8.1f}  {_fmt_geom(gap['geometry'])}")

    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = _HERE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"rows": rows}, indent=1))
        print(f"wrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
