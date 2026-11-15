#!/usr/bin/env python3
"""Best config per cell across ALL runs, and the knob reach per family.

Owns: the cross-run view -- winners across every run directory (not just the
latest), the load width each arm actually reached, and the never-exercised
knobs, because those are the three questions that decide what to run next.

Does NOT own: the winners of one run's own phases (`oto.metrics.benchmark_analytics`), the
acceptance verdicts (`oto.metrics.ab_audit`), or the registry it reads
(`oto.ledger.registry`).

Public API: main, DTYPE_BYTES, FAMILY_CHAR, GLOBAL_LOAD_CAP_BYTES.

It owns no parsing and no arithmetic of its own, by construction: it drives oto's
own loaders and aggregators (the driver's all-runs record loaders, and the
``compute_native_vs_spoof_delta`` median-per-kernel-first semantics), so it cannot
drift from the pipeline that produced the ledger. Byte widths come from the same
place as the gate's, which ``tests.test_measurement_integrity`` asserts.

    python3 -m `oto.tools.run_census`           # tables to stdout
    python3 -m `oto.tools.run_census` --json out.json  # machine-readable
    python3 -m `oto.tools.run_census` --family ZZ      # filter to one family

CPU only. Touches no GPU and launches no Tensile run.
"""


from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
for _p in (os.environ.get("TENSILE_ROOT"),):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import cube_side, dtype_to_family
from oto.metrics.benchmark_analytics import extract_family_from_phase_id
from oto.runners.driver import TensileDriver
from oto.runners.result_paths import runs_dir as _runs_dir

# bytes per element for the GLOBAL LOAD. Read from Tensile via
# consolidate.dtype_bytes rather than hardcoded: this table used to be a second
# copy of the profile's family_bytes_per_element and had already
# drifted, carrying
# the same wrong "Z": 8 (complex double is 16) that let VectorWidth 2 through
# the cap. tests.test_measurement_integrity asserts the two agree.
_DTYPE_CHARS = ("S", "D", "H", "C", "Z", "I8", "B")


def _load_dtype_bytes() -> dict:
    from oto.tools.consolidate import dtype_bytes
    out = {}
    for ch in _DTYPE_CHARS:
        n = dtype_bytes(ch)
        if n:
            out[ch] = n
    # Tensile unavailable: fall back to the cap only, never to a guess that
    # could understate a width and silently pass an illegal config.
    return out or dict.fromkeys(_DTYPE_CHARS, 16)


DTYPE_BYTES = _load_dtype_bytes()
# dtype char per family label. Mixed-precision families are governed by their
# widest loaded operand, matching oto.tensile.gates.loads.cap_vector_width: HS/HS_HPA load a
# single, HH_HPA loads a half.
FAMILY_CHAR = {"SS": "S", "DD": "D", "CC": "C", "ZZ": "Z", "HH": "H",
               "HH_HPA": "H", "HS_HPA": "S", "HS": "S", "HF": "H"}
# hard cap: the load gate rejects GLVW * bytes > 16
GLOBAL_LOAD_CAP_BYTES = 16


class _Knobs:
    """Per-(run, phase) knob lookup, YAML-first with the registry config as
    fallback. Run dirs that no longer exist (registry-only runs) have no YAML,
    only a 12-key config snapshot on the record itself."""

    def __init__(self, base: Path):
        self.base = base
        self._cache: dict[tuple[str, str], dict] = {}

    def get(self, run, phase_id, profile=None) -> dict:
        """Return one row of the phase ledger for the A/B arms view. ``profile`` selects the device; ambient by default."""
        key = (str(run), str(phase_id))
        if key in self._cache:
            return self._cache[key]
        self._cache[key] = {}
        d = _runs_dir(self.base, _loader.resolve_profile(profile,).codename) / str(run) / str(phase_id) / "2_BenchmarkData"
        if d.is_dir():
            for f in sorted(os.listdir(d)):
                if not f.endswith(".yaml"):
                    continue
                try:
                    k: dict = {}
                    for doc in yaml.safe_load_all(open(d / f)):
                        for item in (doc if isinstance(doc, list) else [doc]):
                            if isinstance(item, dict):
                                k.update(item)
                except Exception:
                    break
                if k:
                    self._cache[key] = k
                    return k
        return self._cache[key]


def _fam(rec, knobs: _Knobs) -> str:
    """Family label. The run's OWN FamilyLabel wins; the live phases.yaml no
    longer lists the reference hh_hpa/hs_hpa phases, so falling back to it
    silently folds them into HH. Then cell_key, then the phase id, then dtype."""
    k = knobs.get(rec.get("source_run"), rec.get("phase_id", ""))
    if k.get("FamilyLabel"):
        return str(k["FamilyLabel"]).upper()
    f = str(rec.get("family") or str(rec.get("cell_key", "")).split(":")[0] or "").upper()
    if not f or f == "?":
        f = extract_family_from_phase_id(str(rec.get("phase_id", ""))).upper()
    if not f:
        f = dtype_to_family().get(str(rec.get("DataType") or rec.get("dtype") or "").upper(), "?")
    return f


def _load_arms(base: Path, profile=None):
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    drv = TensileDriver(base, create_run=False)
    native = drv._native_records_all_runs()
    floor: list[dict] = []
    ref_ids = drv._reference_floor_runs(None,)
    for ref in ref_ids:
        d = _runs_dir(base, _loader.resolve_profile(profile,).codename) / ref
        if d.is_dir():
            _n, recs = drv._ab_records_from_csv(d, force_arm="spoof")
            for r in recs:
                r["source_run"] = ref
            floor.extend(recs)
    return drv, native, floor, ref_ids


def _winners(records, arm, knobs: _Knobs):
    """Best config per (family, cube side). median-per-kernel, then max."""
    grouped: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        gf = float(r.get("GFLOPS") or 0.0)
        if gf <= 0:
            continue
        side = cube_side(r.get("ProblemType") or r.get("shape") or "")
        if not side:
            continue
        gkey = (str(r.get("source_run")), str(r.get("phase_id")), str(r.get("fingerprint")))
        grouped[(_fam(r, knobs), side)][gkey].append(gf)
    out = {}
    for cell, kernels in grouped.items():
        med = {k: statistics.median(v) for k, v in kernels.items() if v}
        if not med:
            continue
        w = max(med, key=lambda k: med[k])
        win_rec = next((r for r in records
                        if (str(r.get("source_run")), str(r.get("phase_id")),
                            str(r.get("fingerprint"))) == w), {})
        kn = dict(win_rec.get("config") or {})      # registry 12-key snapshot
        kn.update(knobs.get(w[0], w[1]) or {})       # YAML wins
        out[cell] = {"arm": arm, "family": cell[0], "side": cell[1],
                         "gflops": med[w], "n_kernels": len(med), "n_samples": len(kernels[w]),
                         "run": w[0], "phase_id": w[1], "kernel": w[2], "knobs": kn,
                         "knob_src": "yaml" if knobs.get(w[0], w[1]) else "registry_config"}
    return out


def _reach(records, arm, knobs: _Knobs):
    """(VW, MacroTile, ThreadTile) triples this arm has actually run."""
    triples: dict = defaultdict(set)
    for r in records:
        k = knobs.get(r.get("source_run"), r.get("phase_id", "")) or r.get("config") or {}
        vw, mt, tt = k.get("VectorWidth"), k.get("MacroTile"), k.get("ThreadTile")
        if vw is None or not mt or not tt:
            continue
        mt_s = mt if isinstance(mt, str) else "x".join(map(str, mt))
        tt_s = tt if isinstance(tt, str) else "x".join(map(str, tt))
        triples[_fam(r, knobs)].add((mt_s, tt_s, int(vw)))
    return triples


def _fmt(x):
    return "x".join(map(str, x)) if isinstance(x, (list, tuple)) else str(x)


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", "--base", type=Path, default=BASE)
    ap.add_argument("--family", help="filter tables to one family label (e.g. ZZ)")
    ap.add_argument("--json", type=Path, help="also write machine-readable output here")
    return ap


def _filter_by_family(nat, flr, nat_t, flr_t, family):
    """Apply --family to all four tables (cell keys vs family keys)."""
    if not family:
        return nat, flr, nat_t, flr_t
    want = family.upper()
    def keep(c):
        return c[0].upper() == want
    nat = {k: v for k, v in nat.items() if keep(k)}
    flr = {k: v for k, v in flr.items() if keep(k)}
    nat_t = {k: v for k, v in nat_t.items() if k.upper() == want}
    flr_t = {k: v for k, v in flr_t.items() if k.upper() == want}
    return nat, flr, nat_t, flr_t


def _print_summary(base, ref_ids, native, floor, nat, flr):
    """The header block: arms, cell counts and the partial-knob list."""
    print(f"base-dir     : {base}")
    print(f"floor runs   : {ref_ids}")
    print(f"native arm   : {len(native)} records / {len({r.get('source_run') for r in native})} run(s)")
    print(f"floor arm    : {len(floor)} records / {len({r.get('source_run') for r in floor})} run(s)")
    print(f"native cells : {len(nat)}   floor cells: {len(flr)}   shared: {len(set(nat) & set(flr))}")
    thin = sorted(f"{c[0]}:{c[1]}" for c, w in list(nat.items()) + list(flr.items())
                  if w["knob_src"] != "yaml")
    if thin:
        print(f"\npartial-knob cells (registry 12-key snapshot, no YAML): {thin}")
    print("\nnote: a 2_BenchmarkData CSV is a MULTI-SIZE SWEEP — GFlops is the LAST")
    print("      column, column 0 is the row index, and SizeL is the real K.")


def _print_load_width(nat_t, flr_t):
    """Load width actually reached, per arm x family."""
    print("\n=== load width actually reached, per arm x family ===")
    print(f"  {'family':8} {'native':26} {'floor':26} verdict")
    fams = sorted(set(nat_t) | set(flr_t))
    for f in fams:
        b = DTYPE_BYTES.get(FAMILY_CHAR.get(f, f[0]), 4)
        nb = sorted({t[2] * b for t in nat_t.get(f, ())})
        fb = sorted({t[2] * b for t in flr_t.get(f, ())})
        n_at_cap = GLOBAL_LOAD_CAP_BYTES in nb
        f_at_cap = GLOBAL_LOAD_CAP_BYTES in fb
        v = ("both at cap" if n_at_cap and f_at_cap else
             "NATIVE-only at cap" if n_at_cap else
             "FLOOR-only at cap" if f_at_cap else
             f"neither at {GLOBAL_LOAD_CAP_BYTES}B cap")
        print(f"  {f:8} {[f'{x}B' for x in nb]!s:26} {[f'{x}B' for x in fb]!s:26} {v}")


def _print_best_table(w, _label=None):
    """Best config per cell, one arm."""
    print(f"\n=== best config per cell — {_label} ===")
    print(f"  {'cell':14} {'GFLOPS':>9} {'nker':>5} {'MT':11} {'TT':6} {'VW':>3} "
          f"{'loadB':>6} {'DU':>4} {'WGM':>4} {'GSU':>4} pattern")
    for cell in sorted(w):
        rec = w[cell]
        k = rec["knobs"]
        vw = k.get("VectorWidth")
        b = DTYPE_BYTES.get(FAMILY_CHAR.get(cell[0], cell[0][0]), 4)
        lb = f"{int(vw) * b}B" if vw is not None else "?"
        print(f"  {f'{cell[0]}:{cell[1]}':14} {rec['gflops']:9.1f} {rec['n_kernels']:5} "
              f"{_fmt(k.get('MacroTile')):11} {_fmt(k.get('ThreadTile')):6} {vw!s:>3} "
              f"{lb:>6} {k.get('DepthU')!s:>4} {k.get('WorkGroupMapping')!s:>4} "
              f"{k.get('GlobalSplitU')!s:>4} {k.get('ContractionPattern')}")


def _print_triples(nat_t, flr_t):
    """(MacroTile / ThreadTile / VectorWidth) triples per arm x family."""
    print("\n=== (MacroTile / ThreadTile / VectorWidth) triples per arm x family ===")
    for _arm, tri in (("native", nat_t), ("floor", flr_t)):
        print(f"\n-- {_arm}")
        for f in sorted(tri):
            b = DTYPE_BYTES.get(FAMILY_CHAR.get(f, f[0]), 4)
            ts = sorted(tri[f])
            at_cap = [t for t in ts if t[2] * b == GLOBAL_LOAD_CAP_BYTES]
            print(f"   {f:8} n={len(ts):3}  " + ", ".join(f"{a}/{b_}/vw{c}" for a, b_, c in ts))
            if at_cap:
                print(f"   {'':8} at {GLOBAL_LOAD_CAP_BYTES}B cap: "
                      + ", ".join(f"{a}/{b_}/vw{c}" for a, b_, c in at_cap))


def _print_never_exercised(nat, flr):
    """Knobs that exist in the schema but were never exercised by either arm."""
    print("\n=== never-exercised knobs (both arms, all cells) ===")
    for knob in ("GlobalSplitU", "ContractionPattern", "StaggerU", "DepthU",
                 "WorkGroupMapping", "LdsPadB", "PrefetchGlobalRead"):
        vals = set()
        for arm in (nat, flr):
            for rec in arm.values():
                if knob in rec["knobs"]:
                    vals.add(str(rec["knobs"][knob]))
        if vals and len(vals) == 1:
            print(f"  {knob:20} = {sorted(vals)}   <- only ever this one value")


def _write_all_runs_json(path, ref_ids, native, floor, nat, flr, nat_t, flr_t):
    """The machine-readable dump of every table this tool printed."""
    path.write_text(json.dumps(
        {"floor_runs": ref_ids,
         "records": {"native": len(native), "floor": len(floor)},
         "winners": {a: {f"{c[0]}:{c[1]}": v for c, v in wn.items()}
                     for a, wn in (("native", nat), ("floor", flr))},
         "triples": {a: {f: sorted(map(list, t)) for f, t in tr.items()}
                     for a, tr in (("native", nat_t), ("floor", flr_t))}},
        indent=1, default=str))


def main() -> int:
    args = _build_arg_parser().parse_args()

    base = args.base_dir.resolve()
    knobs = _Knobs(base)
    _drv, native, floor, ref_ids = _load_arms(base)

    nat = _winners(native, "native", knobs)
    flr = _winners(floor, "floor", knobs)
    nat_t, flr_t = _reach(native, "native", knobs), _reach(floor, "floor", knobs)

    nat, flr, nat_t, flr_t = _filter_by_family(nat, flr, nat_t, flr_t, args.family)
    _print_summary(base, ref_ids, native, floor, nat, flr)
    _print_load_width(nat_t, flr_t)
    for label, wn in (("NATIVE", nat), ("FLOOR", flr)):
        _print_best_table(wn, label)
    _print_triples(nat_t, flr_t)
    _print_never_exercised(nat, flr)

    if args.json:
        _write_all_runs_json(args.json, ref_ids, native, floor,
                            nat, flr, nat_t, flr_t)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
