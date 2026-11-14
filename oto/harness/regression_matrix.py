#!/usr/bin/env python3
"""Deck-vs-floor-vs-all-time cell regression matrix.

Owns: for every cell of the shipped grid, the comparison of what the committed
deck ships, what the gfx900 floor measured, and the best native kernel ever --
and the standing loss / material-regression rules that decide which of those
differences is signal.

Does NOT own: the winner rule it shares with resolve_cells
(oto.harness.cell_resolver), the shipped grid itself (oto.tensile.library_parity),
or the acceptance report (oto.metrics.acceptance_report).

Public API: main, build_matrix.

Per cell it reports the **deck** (what ``phases.yaml`` ships: best per-kernel
median, best seed as secondary), the **floor** (best measured gfx900 reference
kernel: median-primary, best-seed secondary) and the **all-time** best native
kernel, including candidates the deck rejected or that never landed.

The standing rules are the ones the acceptance report grades on: median-of-seeds
with NumBenchmarks/Empirical >= 3, a +-2% tie band, and no best-of-runs against
best-of-history. A cell is a **loss** when its deck median is more than 2% under
the floor median, and a **material median regression** when any other native
kernel beats the shipped one by more than 2% for the same cell. Config-identical
losses (same structural config, different measured GFlops) are reported as pure
cross-run variance rather than a regression.

``losses`` and ``material_regressions`` are the entry point for candidate-gap
work: they name the exact cells and configs to attack.

    python3 -m oto.harness.regression_matrix
    python3 -m oto.harness.regression_matrix --rebuild
    python3 -m oto.harness.regression_matrix --no-json
"""


from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from oto import yaml_cached as yamlio
from oto.device import loader as _loader
from oto.runners.paths import results_dir

CONFIG_KEYS = ("MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU",
               "VectorWidth", "DepthU")


def _best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best row under the standing winner rule (median-primary, best-secondary)."""
    return max(rows, key=lambda r: (r.get("gflops_median") or 0.0,
                                    r.get("gflops_best") or 0.0)) if rows else None


def _med(row: dict[str, Any] | None) -> float:
    return float(row.get("gflops_median") or 0.0) if row else 0.0


def _pct(a: float, b: float) -> float | None:
    return ((a - b) / b * 100.0) if b > 0 else None


def _cfg(row: dict[str, Any] | None) -> dict[str, str]:
    return {k: str(row.get(k) or "") for k in CONFIG_KEYS} if row else {}


_STRUCTURAL = ("MacroTile", "ThreadTile", "VectorWidth", "DepthU")

def _configs_identical(dk: dict[str, Any] | None,
                       fl: dict[str, Any] | None) -> bool:
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


def _cell_of(row: dict[str, Any],
             grid: set[tuple[str, str]],
             phase_family: Any) -> tuple[str, str] | None:
    """(family, shape) grid cell for a row, or None for non-cube/non-grid."""
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


def _split_native_spoof(db: dict[str, Any]) -> tuple[list[dict[str, Any]],
                                                list[dict[str, Any]]]:
    """Native and floor rows, separated by the gfx900_ref run-id prefix."""
    native: list[dict[str, Any]] = []
    spoof: list[dict[str, Any]] = []
    for run_id, rows in db.items():
        if run_id.startswith("gfx900_ref_"):
            spoof.extend(dict(r, run=run_id) for r in rows)
        else:
            native.extend(dict(r, run=run_id) for r in rows)
    return native, spoof


def _filter_protocol(rows: list[dict[str, Any]],
                     any_protocol: bool) -> tuple[list[dict[str, Any]], int]:
    """Rows admitted under the like-for-like rule (protocol == 'family').

    Pre-protocol-stamp caches classify as 'unknown' and are admitted only
    with ``any_protocol=True``. Probe/single-problem invocations measure
    2-4x inflated against the deck protocol and must not win an all-time
    cell. Returns ``(admitted, dropped_count)``.
    """
    if any_protocol:
        return list(rows), 0
    keep = [r for r in rows if r.get("protocol") == "family"]
    return keep, len(rows) - len(keep)


def _deck_phase_ids(base_dir: str) -> set[str]:
    """The shipped deck's phase ids (the authoritative coverage universe)."""
    text = (Path(base_dir) / "phases.yaml").read_text()
    return {p.get("phase_id") for p in (yamlio.load_yaml_text(text) or [])}


def _bucket_rows(
    native: list[dict[str, Any]],
    spoof: list[dict[str, Any]],
    deck_phase_ids: set[str],
    grid: set[tuple[str, str]],
    phase_family: Any,
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]],
           dict[tuple[str, str], list[dict[str, Any]]],
           dict[tuple[str, str], list[dict[str, Any]]]]:
    """deck / all-time / floor row buckets keyed by (family, shape)."""
    deck_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    at_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    floor_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in native:
        c = _cell_of(row, grid, phase_family)
        if c:
            at_rows[c].append(row)
            if row.get("phase") in deck_phase_ids:
                deck_rows[c].append(row)
    for row in spoof:
        c = _cell_of(row, grid, phase_family)
        if c:
            floor_rows[c].append(row)
    return deck_rows, at_rows, floor_rows


def _matrix_entry(
    key: str,
    fam: str,
    side: str,
    dk: dict[str, Any] | None,
    fl: dict[str, Any] | None,
    at: dict[str, Any] | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    """One matrix cell entry; appends wins/losses/regressions to `result`."""
    entry = {
        "cell": key, "family": fam,
        "shape": f"{side}x{side}x{side}",
        "deck": _med(dk), "floor": _med(fl), "all_time": _med(at),
        "deck_phase": dk.get("phase") if dk else None,
        "deck_run": dk.get("run") if dk else None,
        "deck_seeds": dk.get("n_seeds") if dk else None,
        "floor_phase": fl.get("phase") if fl else None,
        "floor_run": fl.get("run") if fl else None,
        "all_time_phase": at.get("phase") if at else None,
        "all_time_run": at.get("run") if at else None,
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
    return entry


def build_matrix(db_path: str, base_dir: str,
                 rebuild: bool = False,
                 any_protocol: bool = False) -> dict[str, Any]:
    """deck / floor / all-time per shipped grid cell + aggregate verdicts.

    The universe of cells is the repo's canonical shipped grid
    (`oto.device.kernel_vocabulary.shipped_cell_set`), so this tool can never report an
    out-of-grid cell; non-cube probe shapes have no cell and are excluded by
    construction. Rows are admitted under the like-for-like rule
    (`protocol='family'`) unless ``any_protocol=True``.
    """
    from oto.device.kernel_vocabulary import shipped_cell_set
    from oto.harness.kernel_db import load_kernel_db
    from oto.tensile.library_parity import phase_family

    db = load_kernel_db(db_path, base_dir=base_dir, rebuild=rebuild)
    native, spoof = _split_native_spoof(db)
    native, drop_nat = _filter_protocol(native, any_protocol)
    spoof, drop_spo = _filter_protocol(spoof, any_protocol)

    grid = shipped_cell_set()  # {(family, shape)} — canonical, 38 cells
    deck_phase_ids = _deck_phase_ids(base_dir)
    deck_rows, at_rows, floor_rows = _bucket_rows(native, spoof,
                                                  deck_phase_ids, grid,
                                                  phase_family)

    keys = sorted({f"{f}:{s.split('x')[0]}" for f, s in set(deck_rows) | set(at_rows) | set(floor_rows)})
    result: dict[str, Any] = {
        "meta": {
            "rule": "docs/knowledge_base.md §6.1 coverage-parity contract",
            "winner": "median-of-seeds primary, best-seed secondary",
            "tie_band_pct": 2.0,
            "runs": sorted(db),
            "grid_size": len(grid),
            "cells_with_data": len(keys),
            "protocol": "any" if any_protocol else "family",
            "excluded_protocol_rows": drop_nat + drop_spo,
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
        result["cells"][key] = _matrix_entry(key, fam, side, dk, fl, at, result)
    return result


def _table(r: dict[str, Any]) -> str:
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
    lines.extend(
        f"  LOSS {loss['cell']:<10} {loss['vs_floor_pct']:+.1f}%  "
        f"config-identical={loss['config_identical']}"
        for loss in r["losses"])
    lines.extend(
        f"  REGR {m['cell']:<10} {m['pct']:+.1f}% vs {m['regressed_vs'][:50]}"
        for m in r["material_regressions"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, profile=None) -> int:
    """CLI: deck-vs-floor regression matrix. ``profile`` selects the device; ambient by default."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", "--base", default=None, help="repo root")
    ap.add_argument("--db", default=None,
                    help="kernel_db cache path (default: "
                         "<base-dir>/<codename>_results/analysis/kernel_db.json)")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild kernel_db from runs first")
    ap.add_argument("--json", default=None,
                    help="write matrix here")
    ap.add_argument("--no-json", action="store_true", help="print table only")
    ap.add_argument("--any-protocol", action="store_true",
                    help="admit rows from every invocation form (deck generation, "
                         "default is like-for-like 'family' only)")
    args = ap.parse_args(argv)

    base = args.base_dir or str(Path(__file__).resolve().parents[2])
    res_dir = results_dir(base, _loader.resolve_profile(profile,).codename)
    db_path = args.db or res_dir / "analysis" / "kernel_db.json"
    json_path = (Path(args.json) if args.json
                 else res_dir / "analysis" / "regression_matrix.json")
    result = build_matrix(db_path, base, rebuild=args.rebuild,
                          any_protocol=args.any_protocol)
    print(_table(result))
    if not args.no_json:
        out = json_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1, default=str))
        print(f"\nwrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
