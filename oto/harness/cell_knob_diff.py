#!/usr/bin/env python3
"""
harness.cell_knob_diff — per-cell native-vs-floor winner knob fingerprint diff.

Turns "the floor wins at 128-bit / WGM8 / GSU1" into an exact, per-cell knob
delta — the input the §9 candidate deck and the spoof-steal workflow are derived
from. Never benchmarked numbers, always the SAME data the acceptance report
grades on (kernel_db.json rows, typecode-filtered families):

  * native winner  = the native kernel with the best per-cell median in each
    (family, cell-shape) cell (per-{run,phase}, seed-medians already folded);
  * floor winner   = the shipped gfx900 floor kernel with the best per-cell
    median in the same cell;
  * output         = one line per cell: both winners' short names, their
    structural knob dicts, the GFLOPS delta % and the knob diff (changed /
    identical), so a "floor wins at WGM8 + VW2 + DU8" claim is exact.

CPU only. Reads gfx90c_results/analysis/kernel_db.json (rebuild with
`python3 harness/kernel_db.py --rebuild` — same provenance the report cites).

Usage:
    python3 harness/cell_knob_diff.py                 # all cells
    python3 harness/cell_knob_diff.py --family SS     # one family
    python3 harness/cell_knob_diff.py --json out.json
    python3 harness/cell_knob_diff.py --floor-wins-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.device.peaks import FAMILY_SHAPES    # noqa: E402

STRUCTURAL_KNOBS = (
    "MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU", "DepthU",
    "VectorWidth", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
)

_FAMILY_ORDER = ("SS", "DD", "HH", "HH_HPA", "HS_HPA", "CC", "ZZ")


def _side(shape: object) -> Optional[int]:
    try:
        return int(str(shape).split("x")[0])
    except (ValueError, TypeError, IndexError):
        return None


def _winner_per_cell(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """Best per-(family, side) row by gflops_median (seed-median already folded)."""
    best: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in rows:
        fam = r.get("family") or ""
        side = _side(r.get("shape"))
        if not fam or not side:
            continue
        key = (fam, side)
        if key not in best or (r.get("gflops_median") or 0) > (best[key].get("gflops_median") or 0):
            best[key] = r
    return best


def _knob_dict(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in STRUCTURAL_KNOBS if r.get(k) is not None}


def _knob_diff(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    keys = sorted(set(a) | set(b))
    only_a = {k: a[k] for k in keys if k in a and k not in b}
    only_b = {k: b[k] for k in keys if k in b and k not in a}
    changed = {k: (a.get(k), b.get(k)) for k in keys
               if k in a and k in b and a[k] != b[k]}
    summary = []
    for k in keys:
        va, vb = a.get(k, "—"), b.get(k, "—")
        if va == vb:
            summary.append(f"{k}={va}")
        else:
            summary.append(f"{k}: native {va} vs floor {vb}")
    return {"only_native": only_a, "only_floor": only_b, "changed": changed}, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path,
                    default=_HERE / "gfx90c_results" / "analysis" / "kernel_db.json")
    ap.add_argument("--family", help="only this family (SS/DD/HH/CC/ZZ/HH_HPA/HS_HPA)")
    ap.add_argument("--floor-wins-only", action="store_true",
                    help="only print cells the floor wins")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    db = json.loads(args.db.read_text())
    native_rows: List[Dict[str, Any]] = []
    floor_rows: List[Dict[str, Any]] = []
    for run_id, rows in db.items():
        if run_id.startswith("gfx900_ref"):
            floor_rows += rows
        else:
            native_rows += rows

    native_w = _winner_per_cell(native_rows)
    floor_w = _winner_per_cell(floor_rows)

    cells = sorted(set(native_w) & set(floor_w),
                   key=lambda c: (_FAMILY_ORDER.index(c[0]) if c[0] in _FAMILY_ORDER else 99, c[1]))
    if args.family:
        cells = [c for c in cells if c[0].upper() == args.family.upper()]

    rows_out: List[Dict[str, Any]] = []
    for fam, side in cells:
        n, f = native_w[(fam, side)], floor_w[(fam, side)]
        ng, fg = n.get("gflops_median") or 0, f.get("gflops_median") or 0
        dt = (fg - ng) / ng * 100.0 if ng else float("inf")
        floor_wins = fg > ng
        if args.floor_wins_only and not floor_wins:
            continue
        knob_n, knob_f = _knob_dict(n), _knob_dict(f)
        _, summary = _knob_diff(knob_n, knob_f)
        line = (
            f"  {fam}:{side:<6} native {ng:8.1f}  floor {fg:8.1f}  "
            f"Δ{dt:+7.1f}%  {'FLOOR' if floor_wins else 'native'}\n"
            f"      native {n['kernel']}\n"
            f"      floor  {f['kernel']}\n"
            f"      knobs  {' | '.join(summary)}"
        )
        print(line + "\n")
        rows_out.append({
            "cell": f"{fam}:{side}", "native_gflops": round(ng, 1),
            "floor_gflops": round(fg, 1), "delta_pct": round(dt, 2),
            "winner": "floor" if floor_wins else "native",
            "native_kernel": n["kernel"], "floor_kernel": f["kernel"],
            "knob_diff": _knob_diff(knob_n, knob_f)[0],
        })

    n_floor = sum(1 for r in rows_out if r["winner"] == "floor")
    print(f"{len(rows_out)} cells shared; floor wins {n_floor} ({len(cells)} total paired)")
    if args.json:
        args.json.write_text(json.dumps(rows_out, indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())