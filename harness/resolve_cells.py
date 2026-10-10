#!/usr/bin/env python3
"""harness.resolve_cells — per-cell native-vs-floor winner resolution on the
full knob surface.

The authoritative per-cell evidence generator behind potential_configs.md §2
(the 38-cell deck map). For every cell graded by the acceptance report it
resolves, from the repo's canonical sources only (CPU-only — nothing here is
ever measured):

* **acceptance facts** — verdict (WIN/TIE/LOSS), native/floor median + value,
  delta %, and the cell's % of its realistic ceiling and % of theoretical
  peak (`per_family_coverage` in acceptance_report.json);
* **native winner** — the exact winning phase and its run, plus the phase's
  FULL structural knob config (MacroTile … LoopTail; the surface the docs'
  per-family triage is argued from). Resolution order is:
   1. the winner run's own `configs/*.yaml` (the `_write_phase_config`
      emission for that exact run — the compiled truth),
   2. the registry `phases.data.config` for the phase_id,
   3. any native run's `configs/*.yaml` bearing the same phase (newest run
      wins on tie),
   4. the kernel_db structural row for the phase (16-knob fallback);
* **spoof floor winner** — the best gfx900 reference kernel for the same
  cell under the standing winner rule (median-primary, best-seed secondary;
  same `_best` predicate as regression_matrix), config from the kernel_db
  row.

This supersedes the ad-hoc `/tmp/opencode/resolve_cells.py` + verdicts dump
that generated the docs' §2 evidence table; its outputs (JSON, full text
table, TSV) are the repo-homed successors.

Outputs (defaults under `gfx90c_results/analysis/`):

* `cells_resolved.json`   — machine cache: metadata + one row per cell
  (surfaces the same slot names the §2 table is curated from);
* `cells_resolved.full.txt` — the human evidence table (aligned, headers);
* `--tsv`                 — optional tabular verdicts dump (supersedes the
  old /tmp verdicts_full.tsv).

Usage:

    python3 harness/resolve_cells.py                     # table to stdout + caches
    python3 harness/resolve_cells.py --tsv verdicts.tsv  # + TSV verdict dump
    python3 harness/resolve_cells.py --no-json --no-text # table only
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Repo-root import (harness runs as `python3 harness/resolve_cells.py`, where
# sys.path[0] is harness/ — same bootstrap kernel_db.py and friends use).
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import yaml  # noqa: E402

from gfx90c_common import shipped_cell_set  # noqa: E402

# The full structural knob surface — MUST match the yaml emission surface of
# port_tensile._write_phase_config so docs citing a knob can find it here.
CFG_KEYS = [
    "MacroTile", "ThreadTile", "VectorWidth", "GlobalSplitU", "DepthU",
    "WorkGroupMapping", "WorkGroup", "GlobalLoadVectorWidthA",
    "GlobalLoadVectorWidthB", "GlobalReduceVectorWidth", "PrefetchGlobalRead",
    "NumLoadsCoalescedA", "NumLoadsCoalescedB", "LdsPadA", "LdsPadB",
    "StaggerUStride", "StaggerU", "StaggerUMapping",
    "AssertFree0ElementMultiple", "StoreCInUnroll", "PrefetchLocalRead",
    "MacroInstruction", "FractionalTransposeA", "TransposeA", "TransposeB",
    "WholeTileVector", "KernelLanguage", "EdgeType", "LoopTail",
]

# Structural keys kernel_db rows carry (final fallback / floor winners).
KB_CFG_KEYS = [
    "MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU", "VectorWidth",
    "DepthU", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
]


def _normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only known knobs; unwrap single-element lists (how the phase yaml
    emission stores scoped values)."""
    out: Dict[str, Any] = {}
    for k in CFG_KEYS:
        if k in cfg:
            v = cfg[k]
            if isinstance(v, (list, tuple)) and len(v) == 1:
                v = v[0]
            out[k] = v
    return out


def _cfg_from_kb_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Structural config from a kernel_db row (16-knob fallback)."""
    return {k: row.get(k) for k in KB_CFG_KEYS if row.get(k) is not None}


def parse_run_config_yaml(path: str) -> Optional[Dict[str, Any]]:
    """Full knob config from a Tensile `configs/*.yaml` phase emission.

    Same walk as the ad-hoc resolver validated against the live corpus:
    ForkParameters iterate the library keys, BenchmarkFinalParameters carry the
    resolved scalars (ProblemSizes excluded).
    """
    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
    except Exception:
        return None
    try:
        out: Dict[str, Any] = {}
        for entry in doc.get("BenchmarkProblems", [{}])[0] or []:
            if not isinstance(entry, dict):
                continue
            fp = entry.get("ForkParameters")
            if isinstance(fp, list):
                for item in fp:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            out[k] = v[0] if (isinstance(v, list) and v) else v
            bfp = entry.get("BenchmarkFinalParameters")
            if isinstance(bfp, list) and bfp and isinstance(bfp[0], dict):
                for k, v in bfp[0].items():
                    if k != "ProblemSizes":
                        out[k] = v
        return _normalize_cfg(out) if out else None
    except Exception:
        return None


def _load_registry_phases(registry_path: str) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """phase_id -> config for every registry phase (scheduler's record)."""
    out: Dict[str, Dict[str, Any]] = {}
    con = sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    try:
        for (pid, data) in con.execute("SELECT phase_id, data FROM phases"):
            try:
                cfg = json.loads(data).get("config", {})
            except Exception:
                cfg = {}
            n = _normalize_cfg(cfg)
            if n:
                out[pid] = n
    finally:
        con.close()
    return out, len(out)


def _load_run_configs(runs_dir: str) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]],
                                              Dict[str, Dict[str, Any]], int]:
    """Two views over every `gfx90c_runs/*/configs/*.yaml`:

    * run_scoped[runs_dir_name][phase_stub] — for winner-run-first lookup;
    * global[phase_stub] — newest run wins on a phase-name collision.
    Both index the phase yaml by its bare stub (`phase_auto_0_cc_..._2`) and
    its raw basename stem (`phase_phase_auto_0_cc_..._2`) — the registry ids
    use the bare form, the run configs use the raw form.
    """
    run_scoped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    global_cfg: Dict[str, Dict[str, Any]] = {}
    n_parsed = 0
    for yf in sorted(glob.glob(os.path.join(runs_dir, "*", "configs", "*.yaml"))):
        run_id = os.path.basename(os.path.dirname(os.path.dirname(yf)))
        stub = os.path.basename(yf)[:-5]
        bare = stub[len("phase_"):] if stub.startswith("phase_") else stub
        c = parse_run_config_yaml(yf)
        if not c:
            continue
        run_scoped.setdefault(run_id, {})[stub] = c
        run_scoped[run_id][bare] = c
        global_cfg[stub] = c
        global_cfg[bare] = c
        n_parsed += 1
    return run_scoped, global_cfg, n_parsed


def _floor_best(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best row under the standing winner rule (median-primary, best-secondary)
    — the same predicate regression_matrix uses."""
    return max(rows, key=lambda r: (r.get("gflops_median") or 0.0,
                                    r.get("gflops_best") or 0.0)) if rows else None


def _clamp_pct(x: Optional[float]) -> Optional[float]:
    return round(x, 1) if x is not None else None


def build(base_dir: str = ".",
          acceptance_path: Optional[str] = None,
          registry_path: Optional[str] = None,
          db_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Resolve every cell of the acceptance report -> (cells, meta).

    CPU-only. All inputs are canonical repo caches / registries.
    """
    base = Path(base_dir)
    acceptance_path = acceptance_path or str(base / "gfx90c_results" / "acceptance_report.json")
    registry_path = registry_path or str(base / "gfx90c_results" / "registry.db")
    db_path = db_path or str(base / "gfx90c_results" / "analysis" / "kernel_db.json")
    runs_dir = base / "gfx90c_runs"

    with open(acceptance_path) as f:
        report = json.load(f)
    pv = report["per_cell_verdicts"]
    cov = report["per_family_coverage"]
    run_id = report.get("run_id", "?")
    ref_run = report.get("reference_run_id", "?")

    with open(db_path) as f:
        kdb = json.load(f)
    floor_rows: List[Dict[str, Any]] = []
    native_kb_cfg: Dict[str, Dict[str, Any]] = {}
    for rid, rows in kdb.items():
        if "gfx900_ref" in rid:
            floor_rows.extend(rows)
        else:
            for r in rows:
                if r.get("phase"):
                    native_kb_cfg.setdefault(r["phase"], _cfg_from_kb_row(r))

    run_scoped, run_global, n_yamls = _load_run_configs(str(runs_dir))
    registry, n_registry = _load_registry_phases(registry_path)
    n_resolver = len({**run_global, **registry})

    # Floor best per (family, shape) cell.
    floor_best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in floor_rows:
        fam = r.get("family")
        shp = r.get("shape")
        if not fam or not shp:
            continue
        key = (fam, shp)
        cur = floor_best.get(key)
        if _floor_best([r] if cur is None else [cur, r]) is r:
            floor_best[key] = r

    def native_config(win_phase: str, win_run: str) -> Dict[str, Any]:
        if not win_phase:
            return {}
        scoped = run_scoped.get(win_run, {})
        for cand in (scoped.get(win_phase), scoped.get("phase_" + win_phase),
                     registry.get(win_phase), run_global.get(win_phase),
                     run_global.get("phase_" + win_phase),
                     native_kb_cfg.get(win_phase)):
            if cand:
                return cand
        return {}

    def spoof_config(key: Tuple[str, str]) -> Dict[str, Any]:
        row = floor_best.get(key)
        if row is None:
            return {}
        ph = row.get("phase")
        if ph:
            for cand in (registry.get(ph), run_global.get(ph)):
                if cand:
                    return cand
        return _cfg_from_kb_row(row)

    cells: List[Dict[str, Any]] = []
    for v in sorted(pv, key=lambda v: (v["family"], v["shape"])):
        fam = v["family"]
        shp = v["shape"]
        key = (fam, shp)
        nv = v.get("native_value") or 0.0
        sv = v.get("spoof_value") or 0.0
        delta = ((nv - sv) / sv * 100.0) if sv else None
        nwp = v.get("native_winner_phase") or ""
        nrun = v.get("native_winner_run") or ""
        ncfg = native_config(nwp, nrun)
        scfg = spoof_config(key)
        fcov = cov.get(fam, {})
        ceiling = fcov.get("ceiling_gflops") or 0.0
        peak = fcov.get("theoretical_peak_gflops") or 0.0
        cells.append({
            "family": fam,
            "shape": shp,
            "dtype": v.get("dtype", ""),
            "verdict": v.get("verdict", "?"),
            "delta_pct": delta,
            "native_median": v.get("native_median"),
            "native_value": nv,
            "spoof_median": v.get("spoof_median"),
            "spoof_value": sv,
            "pct_ceiling": _clamp_pct(nv / ceiling * 100.0) if ceiling else None,
            "pct_theoretical": _clamp_pct(nv / peak * 100.0) if peak else None,
            "native_winner_phase": nwp,
            "native_winner_run": nrun,
            "native_config": ncfg,
            "spoof_config": scfg,
        })

    meta = {
        "tool": "harness.resolve_cells",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "acceptance_run_id": run_id,
        "reference_run_id": ref_run,
        "n_cells": len(cells),
        "sources": {
            "acceptance_report": str(Path(acceptance_path).relative_to(base)),
            "registry_phases": n_registry,
            "run_config_yamls": n_yamls,
            "resolver_keys": n_resolver,
        },
    }
    return cells, meta


def _compact_cfg(cfg: Dict[str, Any], kb: bool = False) -> str:
    if not cfg:
        return "?"
    if kb:
        return ("MT=%s TT=%s VW=%s DU=%s GSU=%s WG=%s"
                % (cfg.get("MacroTile"), cfg.get("ThreadTile"),
                   cfg.get("VectorWidth"), cfg.get("DepthU"),
                   cfg.get("GlobalSplitU"), cfg.get("WorkGroup")))
    return ("MT=%s TT=%s VW=%s DU=%s GSU=%s WGM=%s WG=%s PGR=%s NLCA=%s "
            "pads=%s/%s GLVW=%s/%s"
            % (cfg.get("MacroTile"), cfg.get("ThreadTile"),
               cfg.get("VectorWidth"), cfg.get("DepthU"),
               cfg.get("GlobalSplitU"), cfg.get("WorkGroupMapping"),
               cfg.get("WorkGroup"), cfg.get("PrefetchGlobalRead"),
               cfg.get("NumLoadsCoalescedA"), cfg.get("LdsPadA"),
               cfg.get("LdsPadB"), cfg.get("GlobalLoadVectorWidthA"),
               cfg.get("GlobalLoadVectorWidthB")))


def _pct_str(x: Optional[float], w: int = 6) -> str:
    if x is None:
        return "-".rjust(w)
    return ("%+6.1f" % x) if w == 6 else ("%6.1f" % x)


def _table(cells: List[Dict[str, Any]]) -> str:
    lines = [
        f"{'fam':<4}{'shape':<18}{'verdict':<7}{'d%':>7}{'nat':>8}{'spoof':>8}"
        f"{'%ceil':>7}{'%theo':>7}  {'NATIVE WINNER CONFIG':<82}  FLOOR CONFIG",
    ]
    for c in cells:
        nw = c["native_config"]
        nstr = _compact_cfg(nw)
        sstr = _compact_cfg(c["spoof_config"], kb=not c["spoof_config"])
        lines.append("%-4s %-18s %-7s %s %7.1f %7.1f %s %s  %-82s %s"
                     % (c["family"], c["shape"], c["verdict"],
                        _pct_str(c["delta_pct"]), c["native_value"],
                        c["spoof_value"], _clamp_pct(c["pct_ceiling"] or 0) or "-",
                        _clamp_pct(c["pct_theoretical"] or 0) or "-",
                        nstr, sstr))
    return "\n".join(lines)


def _tsv(cells: List[Dict[str, Any]]) -> str:
    head = ("family\tshape\tdtype\tverdict\tdelta_pct\tnative_median\tnative_value"
            "\tspoof_median\tspoof_value\tpct_ceiling\tpct_theoretical"
            "\tnative_winner_phase\tnative_winner_run\tnative_config\tspoof_config")
    rows = [head]
    for c in cells:
        rows.append("\t".join(str(v) for v in (
            c["family"], c["shape"], c["dtype"], c["verdict"],
            "" if c["delta_pct"] is None else round(c["delta_pct"], 2),
            c["native_median"], c["native_value"],
            c["spoof_median"], c["spoof_value"],
            c["pct_ceiling"], c["pct_theoretical"],
            c["native_winner_phase"], c["native_winner_run"],
            _compact_cfg(c["native_config"]),
            _compact_cfg(c["spoof_config"]),
        )))
    return "\n".join(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", default=None, help="repo root")
    ap.add_argument("--acceptance", default=None,
                    help="acceptance_report.json path (default: <base>/gfx90c_results/…)")
    ap.add_argument("--registry", default=None,
                    help="registry.db path (default: <base>/gfx90c_results/…)")
    ap.add_argument("--db", default=None,
                    help="kernel_db cache path (default: <base>/gfx90c_results/analysis/…)")
    ap.add_argument("--json", default="gfx90c_results/analysis/cells_resolved.json",
                    help="write machine cache here")
    ap.add_argument("--text", default="gfx90c_results/analysis/cells_resolved.full.txt",
                    help="write the aligned evidence table here")
    ap.add_argument("--tsv", default=None, help="also write this verdicts TSV")
    ap.add_argument("--no-json", action="store_true", help="do not write the JSON cache")
    ap.add_argument("--no-text", action="store_true", help="do not write the text table")
    ap.add_argument("--no-table", action="store_true", help="do not print the table to stdout")
    args = ap.parse_args(argv)

    base = args.base_dir or str(_HERE)
    cells, meta = build(base, args.acceptance, args.registry, args.db)

    if not args.no_table:
        print(_table(cells))

    def _write(flag_off: bool, path: str, payload: str) -> None:
        if flag_off:
            return
        out = Path(path)
        if not out.is_absolute():
            out = Path(base) / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload)
        print(f"wrote -> {out}")

    _write(args.no_json, args.json, json.dumps(
        {"meta": meta, "cells": cells}, indent=1))
    _write(args.no_text, args.text,
           f"# cells_resolved — {meta['acceptance_run_id']} vs ref "
           f"{meta['reference_run_id']} ({meta['generated_at']} UTC)\n"
           f"# sources: {json.dumps(meta['sources'])}\n\n" + _table(cells) + "\n")
    if args.tsv:
        _write(False, args.tsv, _tsv(cells) + "\n")
    print(f"{len(cells)} cells resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())