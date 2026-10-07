#!/usr/bin/env python3
"""harness.regression_matrix — deck-vs-floor-vs-all-time cell regression matrix.

The programmatic counterpart of potential_configs.md §12 and of the accepted
deck's regression list (changelog.md). For every cell of the shipped gfx900
grid (knowledge_base.md §6.1) it compares:

* **deck**   — what the committed `phases.yaml` ships for that cell
  (best per-kernel median, best seed as secondary);
* **floor**  — the best measured gfx900 reference kernel for that cell
  (median-primary, best-seed secondary) — the shipped baseline;
* **all-time** — the best measured native kernel *ever* for that cell,
  including candidates the deck rejected/that never landed.

Material regressions / losses follow the standing rules (median-of-seeds with
NumBenchmarks/Empirical ≥ 3, ±2% tie band, no best-of-runs vs best-of-history):
a cell is a **loss** when its deck median is >2% under the floor median, and a
**material median regression** when any *other* native kernel beats the shipped
one by >2% for the same cell. Config-identical losses (same structural
config, different measured GFlops) are flagged as pure cross-run variance.

The tool is the recommended entry point for candidate-gap work: `losses` and
`material_regressions` list the exact cells and configs to attack, and the
resulting probes (e.g. harness/README.md's N6 §SS:512-vw4 floor) must stay
inside the shipped grid (`check_library_parity.py` stops anything else).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

CONFIG_KEYS = ("MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU",
               "VectorWidth", "DepthU")


def _best(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best row under the standing winner rule (median-primary, best-secondary)."""
    return max(rows, key=lambda r: (r.get("gflops_median") or 0.0,
                                    r.get("gflops_best") or 0.0)) if rows else None


def _med(row: Optional[Dict[str, Any]]) -> float:
    return float(row.get("gflops_median") or 0.0) if row else 0.0


def _pct(a: float, b: float) -> Optional[float]:
    return ((a - b) / b * 100.0) if b > 0 else None


def _cfg(row: Optional[Dict[str, Any]]) -> Dict[str, str]:
    return {k: str(row.get(k) or "") for k in CONFIG_KEYS} if row else {}


_STRUCTURAL = ("MacroTile", "ThreadTile", "VectorWidth", "DepthU")

def _configs_identical(dk: Optional[Dict[str, Any]],
                       fl: Optional[Dict[str, Any]]) -> bool:
    """True when the structural keys both rows actually know about agree, and
    the macro-tile / thread-tile / vector-width / depth knobs are present and
    equal. Missing keys (e.g. floor rows rebuilt from the solution name without
    WorkGroup) can't disprove identity by mere absence."""
    a, b = _cfg(dk), _cfg(fl)
    if not a or not b:
        return False
    shared = [k for k in set(a) & set(b) if a.get(k) and b.get(k)]
    if any(a.get(k) != b.get(k) for k in shared):
        return False
    return all(a.get(k) and a.get(k) == b.get(k) for k in _STRUCTURAL)


def build_matrix(db_path: str, base_dir: str,
                 rebuild: bool = False) -> Dict[str, Any]:
    """deck / floor / all-time per shipped grid cell + aggregate verdicts.

    The universe of cells is the repo's canonical shipped grid
    (`gfx90c_common.shipped_cell_set`), so this tool can never report an
    out-of-grid cell; non-cube probe shapes have no cell and are excluded by
    construction.
    """
    sys.path.insert(0, base_dir)
    import yaml
    from harness.kernel_db import load_kernel_db
    from gfx90c_common import shipped_cell_set
    from library_parity import phase_family, phases_cells

    db = load_kernel_db(db_path, base_dir=base_dir, rebuild=rebuild)
    native: List[Dict[str, Any]] = []
    spoof: List[Dict[str, Any]] = []
    for run_id, rows in db.items():
        if run_id.startswith("gfx900_ref_"):
            spoof.extend(rows)
        else:
            native.extend(rows)

    grid = shipped_cell_set()  # {(family, shape)} — canonical, 38 cells

    def cell_of(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        shape = row.get("shape") or ""
        sides = shape.split("x")
        if len(sides) != 3 or not all(s.isdigit() for s in sides):
            return None  # non-cube probe row
        if not (sides[0] == sides[1] == sides[2]):
            return None  # non-cube (GEMM/TRSV etc.) row
        fam = phase_family({"phase_id": row.get("phase"), "shapes": []})
        if not fam and row.get("dtype"):
            fam = {"S": "SS", "D": "DD", "C": "CC", "Z": "ZZ",
                   "H": "HH"}.get((row.get("dtype") or "").upper(), "")
        if not fam:
            return None
        return (fam, shape) if (fam, shape) in grid else None

    deck_phase_ids = {p.get("phase_id") for p in
                      (yaml.safe_load((Path(base_dir) / "phases.yaml").read_text()) or [])}

    deck_rows: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    at_rows: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    floor_rows: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in native:
        c = cell_of(row)
        if c:
            at_rows[c].append(row)
            if row.get("phase") in deck_phase_ids:
                deck_rows[c].append(row)
    for row in spoof:
        c = cell_of(row)
        if c:
            floor_rows[c].append(row)

    keys = sorted({f"{f}:{s.split('x')[0]}" for f, s in set(deck_rows) | set(at_rows) | set(floor_rows)})
    result: Dict[str, Any] = {
        "meta": {
            "rule": "knowledge_base.md §6.1 coverage-parity contract",
            "winner": "median-of-seeds primary, best-seed secondary",
            "tie_band_pct": 2.0,
            "runs": sorted(db),
            "grid_size": len(grid),
            "cells_with_data": len(keys),
        },
        "cells": {},
        "cell_keys": keys,
        "losses": [],
        "material_regressions": [],
        "wins": [],
    }

    for key in keys:
        fam, side = key.split(":")
        dk = _best(deck_rows.get((fam, f"{side}x{side}x{side}"), []))
        fl = _best(floor_rows.get((fam, f"{side}x{side}x{side}"), []))
        at = _best(at_rows.get((fam, f"{side}x{side}x{side}"), []))
        entry = {
            "cell": key, "family": fam,
            "shape": f"{side}x{side}x{side}",
            "deck": _med(dk), "floor": _med(fl), "all_time": _med(at),
            "deck_phase": dk.get("phase") if dk else None,
            "deck_seeds": dk.get("n_seeds") if dk else None,
            "floor_phase": fl.get("phase") if fl else None,
            "all_time_phase": at.get("phase") if at else None,
            "deck_config": _cfg(dk), "floor_config": _cfg(fl),
            "vs_floor_pct": None, "loss_config_identical": False,
        }
        if dk and fl and _med(fl) > 0:
            diff = _pct(_med(dk), _med(fl))
            entry["vs_floor_pct"] = round(diff, 2) if diff is not None else None
            if diff is not None and diff > 2.0:
                result["wins"].append({"cell": key, "vs_floor_pct": round(diff, 2)})
            elif diff is not None and diff < -2.0:
                identical = _configs_identical(dk, fl)
                entry["loss_config_identical"] = identical
                result["losses"].append({"cell": key,
                                         "vs_floor_pct": round(diff, 2),
                                         "config_identical": identical})
        if dk and at and at is not dk and at.get("phase") != dk.get("phase"):
            diff = _pct(_med(dk), _med(at))
            if diff is not None and diff < -2.0:
                result["material_regressions"].append(
                    {"cell": key, "regressed_vs": at.get("phase"),
                     "pct": round(diff, 2)})
        result["cells"][key] = entry
    return result


def _table(r: Dict[str, Any]) -> str:
    lines = [f"{'cell':>12} {'deck med':>10} {'floor med':>10} {'% vs fl':>9}  kern"]
    lines.append("-" * 72)
    for key in r["cell_keys"]:
        e = r["cells"][key]
        kern = (e.get("deck_phase") or "").replace("phase_auto_", "")[:44]
        pct = f"{e['vs_floor_pct']:+.2f}" if e["vs_floor_pct"] is not None else "-"
        lines.append(f"{key:>12} {e['deck']:>10.2f} {e['floor']:>10.2f} "
                     f"{pct:>9}  {kern}")
    lines.append("-" * 72)
    lines.append(f"cells: {len(r['cell_keys'])} of {r['meta']['grid_size']}  "
                 f"wins(>+2%): {len(r['wins'])}  "
                 f"losses(<-2%): {len(r['losses'])}  "
                 f"material median regressions: {len(r['material_regressions'])}")
    for loss in r["losses"]:
        lines.append(f"  LOSS {loss['cell']:<10} {loss['vs_floor_pct']:+.1f}%  "
                     f"config-identical={loss['config_identical']}")
    for m in r["material_regressions"]:
        lines.append(f"  REGR {m['cell']:<10} {m['pct']:+.1f}% vs "
                     f"{m['regressed_vs'][:50]}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", default=None, help="repo root")
    ap.add_argument("--db", default="gfx90c_results/analysis/kernel_db.json",
                    help="kernel_db cache path")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild kernel_db from runs first")
    ap.add_argument("--json", default="gfx90c_results/analysis/regression_matrix.json",
                    help="write matrix here")
    ap.add_argument("--no-json", action="store_true", help="print table only")
    args = ap.parse_args(argv)

    base = args.base_dir or str(Path(__file__).resolve().parent.parent)
    result = build_matrix(args.db, base, rebuild=args.rebuild)
    print(_table(result))
    if not args.no_json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1, default=str))
        print(f"\nwrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())