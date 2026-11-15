#!/usr/bin/env python3
"""Corpus snapshot / diff / telemetry verification.

Owns: proving the append-only law held -- a snapshot of run-dir file counts, sizes
and registry row counts; a diff of two snapshots that flags any reduction or
in-place rewrite as a violation; the telemetry funnel; and the cheapest LEGAL
live-deck phases for a smoke run.

Does NOT own: the ledger it counts (`oto.ledger.registry`) or the clocks it parses
(`oto.runners.clock_telemetry`).

Public API: snapshot, diff_snapshots, telemetry, cheapest, main.

    snapshot --out before.json        # record corpus state
    # ... run the driver ...
    diff before.json after.json       # did anything get clobbered?
    telemetry <run_id>                # is this run's telemetry actually usable?
    cheapest --family ZZ              # cheapest LEGAL phase, for a cheap smoke run

``diff`` exists because nothing else checks the append-only law: the config and
generate fingerprints hash kernel CONFIGS and ``PRAGMA integrity_check`` only
proves the SQLite file is not corrupt, so none of them notice a phase's benchmark
CSVs being rewritten.

``telemetry`` exists because clock bases are built from a chain of filters
(busy -> sclk range -> thermal), and if any filter is too strict the phase reports
as "unmeasured" -- indistinguishable from a run that never measured it. It
prints the survival count at every step.

The gate arithmetic itself is NOT reimplemented here: it is read through the
driver's own loaders, so this tool cannot disagree with the pipeline that produced
the verdict. CPU only. Touches no GPU and launches no Tensile run.
"""


from __future__ import annotations

import argparse
import contextlib
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from oto import yaml_cached as yamlio
from oto.device import loader as _loader
from oto.runners.result_paths import results_dir as _results_dir
from oto.runners.result_paths import runs_dir as _runs_dir

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

REGISTRY_TABLES = ("runs", "phases", "records")


# --------------------------------------------------------------------------
# corpus state
# --------------------------------------------------------------------------
def _dir_size(p: Path) -> tuple[int, int]:
    """(file count, total bytes) under a directory, via one walk."""
    files = 0
    size = 0
    for f in p.rglob("*"):
        if f.is_file():
            files += 1
            with contextlib.suppress(OSError):
                size += f.stat().st_size
    return files, size


def snapshot(base: Path = BASE, profile=None) -> dict[str, Any]:
    """Corpus state: per-run-directory file counts/sizes plus registry rows.

    Cheap enough to take around any run. Counts and bytes, not content hashes:
    the point is to catch a rewrite in place (a rewritten CSV rarely keeps its
    byte length) and to catch deletion, not to attest to contents. Hashing every
    CSV in the corpus would cost more than the runs being verified.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    runs_dir = _runs_dir(base, _loader.resolve_profile(profile,).codename)
    dirs: dict[str, list[int]] = {}
    if runs_dir.is_dir():
        for d in sorted(runs_dir.iterdir()):
            if d.is_dir():
                dirs[d.name] = list(_dir_size(d))

    db_path = _results_dir(base, _loader.resolve_profile(profile,).codename) / "registry.db"
    tables: dict[str, int | None] = {}
    if db_path.is_file():
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for t in REGISTRY_TABLES:
                try:
                    tables[t] = conn.execute(f'select count(*) from "{t}"').fetchone()[0]
                except sqlite3.Error:
                    tables[t] = None  # table absent, not zero
        finally:
            conn.close()

    return {"dirs": dirs, "tables": tables}


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What changed between two snapshots, split into appends and violations.

    An increase in a pre-existing directory is reported separately from a
    decrease, because only one of them can break a prior experiment: appending
    inside an existing run dir is suspicious, shrinking one means data went
    missing. Registry rows may only go up.
    """
    b_dirs, a_dirs = before.get("dirs", {}), after.get("dirs", {})
    added = sorted(set(a_dirs) - set(b_dirs))
    removed = sorted(set(b_dirs) - set(a_dirs))
    grown, shrunk, touched = [], [], []
    for name in sorted(set(b_dirs) & set(a_dirs)):
        bf, bs = b_dirs[name]
        af, as_ = a_dirs[name]
        if (bf, bs) == (af, as_):
            continue
        # Append-only: files inside an existing run dir should not appear at all.
        touched.append({"run_id": name, "before": [bf, bs], "after": [af, as_]})
        if af < bf or as_ < bs:
            shrunk.append({"run_id": name, "before": [bf, bs], "after": [af, as_]})
        else:
            grown.append({"run_id": name, "before": [bf, bs], "after": [af, as_]})

    b_tab, a_tab = before.get("tables", {}), after.get("tables", {})
    tables: dict[str, Any] = {}
    for t in REGISTRY_TABLES:
        bv, av = b_tab.get(t), a_tab.get(t)
        if bv is None or av is None:
            # Unknown, not zero: never let a missing table read as "lost rows".
            tables[t] = {"before": bv, "after": av, "delta": None, "decreased": False}
        else:
            tables[t] = {"before": bv, "after": av, "delta": av - bv,
                         "decreased": av < bv}

    violations: list[str] = []
    violations.extend(
        f"run {r['run_id']} SHRANK: {r['before']} -> {r['after']}" for r in shrunk)
    violations.extend(f"run {name} was REMOVED" for name in removed)
    violations.extend(
        f"run {r['run_id']} was modified in place: {r['before']} -> {r['after']} "
        f"(benchmark data is append-only)"
        for r in touched)
    for t, v in tables.items():
        if v.get("decreased"):
            violations.append(f"registry table {t} decreased: {v['before']} -> {v['after']}")

    return {"added": added, "removed": removed, "grown": grown,
            "shrunk": shrunk, "modified": touched, "tables": tables,
            "ok": not violations, "violations": violations}


# --------------------------------------------------------------------------
# telemetry usability
# --------------------------------------------------------------------------
def _driver():
    """A TensileDriver with only the telemetry loaders, no run context.

    Same trick tests/test_thermal_gate.py uses: the loaders are taken unbound
    from the real class so they cannot drift from what `oto.metrics.acceptance_report` consumes.
    """
    from oto.runners.driver import TensileDriver
    d = TensileDriver.__new__(TensileDriver)
    d.base_dir = BASE
    d._thermal_cache = None
    return d


def telemetry(run_id: str, base: Path = BASE, profile=None) -> dict[str, Any]:
    """Per-phase telemetry funnel: how many rows survive each filter, and why.

    Filters are reported cumulatively in the order `_telemetry_rows` applies
    them, so a phase losing everything at one step is obvious.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    from oto.runners.driver import TensileDriver

    path = _runs_dir(base, _loader.resolve_profile(profile,).codename) / run_id / "logs" / "telemetry.csv"
    if not path.is_file():
        return {"run_id": run_id, "ok": False,
                "error": f"no telemetry at {path.relative_to(base)}"}
    with path.open(newline="") as fh:
        rd = csv.DictReader(fh)
        fieldnames = rd.fieldnames or []
        rows = list(rd)
    tagged = [r for r in rows if (r.get("phase_id",) or "").strip()]
    schema_ok = "phase_id" in fieldnames
    per_phase: dict[str, dict[str, Any]] = {}
    for r in tagged:
        pid = r["phase_id"].strip()
        e = per_phase.setdefault(pid, {"rows": 0, "busy": 0, "sclk": 0, "clock": 0,
                                       "hot": 0, "sclk_values": []})
        e["rows"] += 1
        busy = _int(r.get("gpu_busy_percent",))
        hz = _int(r.get("sclk_hz",))
        temp_c = None if r.get("temp_mc",) in (None, "") else _int(r.get("temp_mc",)) / 1000.0
        if busy > TensileDriver.TELEMETRY_BUSY_PCT:
            e["busy"] += 1
        if TensileDriver.SCLK_MIN_HZ <= hz <= TensileDriver.SCLK_MAX_HZ:
            e["sclk"] += 1
            if temp_c is None or temp_c < TensileDriver.THERMAL_MAX_C:
                e["clock"] += 1
                e["sclk_values"].append(hz)
            else:
                e["hot"] += 1
    d = _driver()
    bases = d._load_telemetry_by_phase(_runs_dir(base, _loader.resolve_profile(profile,).codename) / run_id)
    for pid, e in per_phase.items():
        v = sorted(e.pop("sclk_values"))
        e["clock_median_hz"] = v[len(v) // 2] if v else 0
        e["clock_base_hz"] = bases.get(pid, {},).get("sclk_hz", 0,)
        e["has_base"] = e["clock_base_hz"] > 0
        e["ok"] = e["rows"] > 0 and e["has_base"]

    unmeasured = sorted(p for p, e in per_phase.items() if not e["has_base"])
    return {"run_id": run_id, "ok": schema_ok and not unmeasured and bool(per_phase),
            "schema_ok": schema_ok, "path": str(path.relative_to(base)),
            "columns": fieldnames, "rows": len(rows), "tagged_rows": len(tagged),
            "untagged_rows": len(rows) - len(tagged), "phases": per_phase,
            "unmeasured_phases": unmeasured,
            "busy_gate_pct": TensileDriver.TELEMETRY_BUSY_PCT,
            "busy_gate_enforced": TensileDriver.TELEMETRY_REQUIRE_BUSY,
            "sclk_range_hz": [TensileDriver.SCLK_MIN_HZ, TensileDriver.SCLK_MAX_HZ],
            "thermal_max_c": TensileDriver.THERMAL_MAX_C,
            "min_samples": TensileDriver.TELEMETRY_MIN_SAMPLES}


def _int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# cheapest legal phase
# --------------------------------------------------------------------------
def cheapest(family: str | None = None, n: int = 5,
             base: Path = BASE, profile=None) -> list[dict[str, Any]]:
    """The n cheapest LEGAL phases *in the live deck*, for a cheap smoke run.

    "Legal" is the whole point: sorting by problem volume alone hands back
    configs that Tensile rejects at assembly, which is how a smoke run turns
    into a debugging session. Gates come from consolidate, unmodified.

    Deliberately the LIVE `phases.yaml`, not `consolidate.load_deck()`. The
    driver executes the live deck; load_deck is the 1644-phase solution
    universe used for deck *selection*. Recommending from the union produces
    `--targets` the driver cannot resolve, which is worse than no answer.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    from oto.tools.consolidate import _is_legal

    deck_path = base / "phases.yaml"
    if not deck_path.is_file():
        return []
    phases = yamlio.load_yaml(deck_path) or []

    # Families are labelled "ZZ" but Tensile's DataType is "Z"; the mapping
    # belongs to oto.device.kernel_vocabulary, so accept either and let it resolve.
    want = _loader.resolve_profile(profile,).family_dtype_char.get(family, family,) if family else None

    def volume(phase: dict[str, Any]) -> float:
        pt = (phase.get("config",) or {}).get("ProblemType", "",)
        try:
            i, j, k = (int(x) for x in pt.split("x"))
            return float(i) * j * k
        except (ValueError, AttributeError):
            return float("inf")

    out = []
    for phase in phases:
        fam = (phase.get("config",) or {}).get("DataType", "",)
        if want and fam != want:
            continue
        ok, _why = _is_legal(phase,)
        if not ok:
            continue
        cfg = phase.get("config",) or {}
        out.append({"volume": volume(phase), "dtype": fam,
                    "problem_type": cfg.get("ProblemType", "",),
                    "contraction": cfg.get("ContractionPattern", "",),
                    "vector_width": cfg.get("VectorWidth", "",),
                    "shapes": phase.get("shapes", [],),
                    "phase_id": phase.get("phase_id", "",), "label": phase.get("label", "",)})
    out.sort(key=lambda r: (r["volume"], r["phase_id"]))
    return out[:n]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def add_json(sub: Any) -> None:
    sub.add_argument("--json", action="store_true", help="machine-readable output")


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", "--base", type=Path, default=BASE,
                    help="project base dir (default: repo root)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="record corpus state (dirs + registry rows)")
    s.add_argument("--out", help="write JSON here instead of stdout")
    add_json(s)

    d = sub.add_parser("diff", help="compare two snapshots; non-zero if data was lost")
    d.add_argument("before")
    d.add_argument("after")
    add_json(d)

    t = sub.add_parser("telemetry", help="per-phase telemetry funnel for one run")
    t.add_argument("run_id")
    add_json(t)

    c = sub.add_parser("cheapest", help="cheapest legal phases, for a cheap smoke run")
    c.add_argument("--family", help="dtype char filter, e.g. ZZ")
    c.add_argument("--n", type=int, default=5)
    c.add_argument("--json", action="store_true")
    return ap


def _cmd_snapshot(args, base: Path) -> int:
    snap = snapshot(base)
    text = json.dumps(snap, indent=2, sort_keys=True)
    if args.json:
        print(text)
        if args.out:
            Path(args.out).write_text(text + "\n")
        return 0
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}: {len(snap['dirs'])} run dirs, "
              f"tables {snap['tables']}")
    else:
        print(text)
    return 0


def _cmd_diff(args) -> int:
    res = diff_snapshots(_load(args.before), _load(args.after))
    if args.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"added:   {res['added'] or 'none'}")
    print(f"removed: {res['removed'] or 'none'}")
    print(f"modified in place: {[r['run_id'] for r in res['modified']] or 'none'}")
    for t_, v in res["tables"].items():
        print(f"  {t_:<8} {v['before']} -> {v['after']} "
              f"(delta {v.get('delta', 'n/a')})")
    if res["ok"]:
        print("OK: additive only, nothing lost")
        return 0
    print("VIOLATIONS:")
    for v in res["violations"]:
        print(f"  - {v}")
    return 1


def _cmd_telemetry(args, base: Path) -> int:
    res = telemetry(args.run_id, base)
    if args.json:
        print(json.dumps(res, indent=2, default=str))
        return 1 if "error" in res else 0
    if "error" in res:
        print(res["error"])
        return 1
    print(f"{res['run_id']}  rows={res['rows']} tagged={res['tagged_rows']} "
          f"untagged={res['untagged_rows']}  phase_id column={res['schema_ok']}")
    print(f"  gates: busy>{res['busy_gate_pct']}% "
          f"(enforced={res['busy_gate_enforced']}), "
          f"sclk in {res['sclk_range_hz']}, thermal<{res['thermal_max_c']}C")
    hdr = f"  {'phase':<46} {'rows':>5} {'busy':>5} {'sclk':>5} {'clock':>6} {'hot':>4}"
    print(hdr)
    for pid, e in sorted(res["phases"].items()):
        print(f"  {pid[:46]:<46} {e['rows']:>5} {e['busy']:>5} {e['sclk']:>5} "
              f"{e['clock']:>6} {e['hot']:>4}"
              f"  base={e['clock_base_hz']/1e6:.0f}MHz"
              f"{'' if e['ok'] else '  <-- NO CLOCK BASE'}")
    if res["unmeasured_phases"]:
        print(f"  UNMEASURED: {res['unmeasured_phases']}")
        return 1
    return 0 if res["ok"] else 1


def _cmd_cheapest(args, base: Path) -> int:
    rows = cheapest(args.family, args.n, base)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"  {'volume':>14} {'dtype':<6} {'problem':<14} {'vw':<3} "
              f"{'shapes':<7} phase")
        for r in rows:
            print(f"  {r['volume']:>14.0f} {r['dtype']:<6} {r['problem_type']:<14} "
                  f"{r['vector_width']!s:<3} {len(r['shapes']):<7} {r['phase_id']}")
        print("\ndrive one with:")
        print(f"  python3 -m oto bench --dry-run --native "
              f"--targets {rows[0]['phase_id']}" if rows else "  (none)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    base = args.base_dir.resolve()

    if args.cmd == "snapshot":
        return _cmd_snapshot(args, base)
    if args.cmd == "diff":
        return _cmd_diff(args)
    if args.cmd == "telemetry":
        return _cmd_telemetry(args, base)
    if args.cmd == "cheapest":
        return _cmd_cheapest(args, base)
    return 2


if __name__ == "__main__":
    sys.exit(main())
