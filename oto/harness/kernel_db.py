#!/usr/bin/env python3
"""harness.kernel_db — ground-truth per-kernel-per-shape GFLOPS database.

Walks every run/phase directory under `gfx90c_runs/` and produces, per
(phase, kernel-shape) row, the per-seed best and median GFlops and the
structural config (from each folder's `Data/00_Final.yaml`; the gfx900 floor
config is rebuilt from the solution name when the folder is absent). High-level
design inherited from the exploration script that produced the published
matrix (potential_configs.md §12); this is the canonical, repo-homed version.

Dtype is resolved from the config's `ProblemType.DataType` enum:
    0=S(f32) 1=D(f64) 2=C(complex f32) 3=Z(complex f64) 4=H(f16)

Default rules:

* native runs   = every `gfx90c_runs/run_*` directory;
* spoof floor   = `gfx90c_runs/gfx900_ref_locked_*` only (`--all-ref` also
  folds in the other completed `gfx900_ref_*` dirs — they were chained
  rebuilds and are excluded by default so regens stay identical to the
  published matrix).

Output: `gfx90c_results/analysis/kernel_db.json` (run_id -> rows). CPU-only.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Repo-root import for the canonical typecode->family resolver (single source of
# truth in gfx90c_common). kernel_db runs as `python3 harness/kernel_db.py`,
# where sys.path[0] is the harness dir, so the repo root must be inserted first.
_HERE = Path(__file__).resolve().parents[2]
for _p in (str(_HERE), os.environ.get("TENSILE_ROOT")):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from oto.device.peaks import (            # noqa: E402  (path set up above)
    FAMILY_DTYPE_CHAR,
    family_from_kernel_name,
    kernel_typecode,
)

ENUM_TO_DTYPE = {0: "S", 1: "D", 2: "C", 3: "Z", 4: "H"}
# Family token immediately after the phase / probe / auto-pool prefix, so
# `phase_ss_...`, `phase_auto_3_hh_...` and `probe_dd_...` all resolve.
FAMILY_RE = re.compile(r"^(?:phase|probe)_(?:auto_\d+_)?(ss|dd|hh|cc|zz)(?:_\w+)*?")
_DEFAULT_DTYPE = {"ss": "S", "dd": "D", "hh": "H", "cc": "C", "zz": "Z"}
_REVERSE_DEFAULT_DTYPE = {v: k for k, v in _DEFAULT_DTYPE.items()}

CONFIG_KEYS = [
    "MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU", "VectorWidth",
    "DepthU", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
    "GlobalLoadVectorWidth", "EnableMatrixInstruction", "KernelLanguage",
]


def discover_runs(base_dir: str,
                  all_ref: bool = False) -> List[Tuple[str, str]]:
    """[(run_id, kind)] for native `run_*` + spoof floor runs.

    kind is 'native' for `run_*` and 'spoof' for `gfx900_ref_*`. With
    all_ref=False only the locked floor (`gfx900_ref_locked_*`) is included,
    matching the published regression matrix; all_ref=True includes every
    gfx900 reference directory.
    """
    runs_dir = Path(base_dir) / "gfx90c_runs"
    out: List[Tuple[str, str]] = []
    if not runs_dir.is_dir():
        return out
    for entry in sorted(runs_dir.iterdir()):
        name = entry.name
        if not entry.is_dir():
            continue
        if name.startswith("run_"):
            out.append((name, "native"))
        elif name.startswith("gfx900_ref_"):
            if all_ref or name.startswith("gfx900_ref_locked_"):
                out.append((name, "spoof"))
    return out


def parse_config(yaml_path: str) -> Dict[str, Any]:
    """Structural config from a Tensile `Data/00_Final.yaml`.

    Text-scan based (same parser the exploration script validated against the
    live corpus) — reads scalars, the ProblemType DataType enum, and the ISA.
    Returns {} on any read failure; callers fall back to their run-level
    default config.
    """
    try:
        with open(yaml_path) as f:
            text = f.read()
    except OSError:
        return {}
    cfg: Dict[str, Any] = {}
    for key in CONFIG_KEYS:
        m = re.search(r"^  %s: (.+)$" % re.escape(key), text, re.M)
        if m:
            cfg[key] = m.group(1).strip()
    pt = text.find("ProblemType:")
    if pt >= 0:
        m = re.search(r"DataType: (\d+)", text[pt:pt + 800])
        if m:
            cfg["DataTypeEnum"] = int(m.group(1))
    m = re.search(r"^  ISA: \[([^\]]+)\]", text, re.M)
    if m:
        cfg["ISA"] = m.group(1).split(",")
    return cfg


def floor_config_from_name(phase_id: str) -> Dict[str, Any]:
    """Structural config for a spoof phase from its phase_id.

    Spoof ids carry `_mt<M>-tt<T>-vw<V>-du<D>-gsu<G>-<hash>`; the macro tile
    is square in these kernels so MT[N, N] covers both dims.
    """
    m = re.search(r"_mt(\d+)-tt(\d+)-vw(\d+)-du(\d+)-gsu(\d+)-", phase_id)
    if not m:
        return {}
    mt, tt, vw, du, gsu = m.groups()
    return {"MacroTile": f"[{mt}, {mt}]", "ThreadTile": f"[{tt}, {tt}]",
            "VectorWidth": vw, "DepthU": du, "GlobalSplitU": gsu}


def phase_survey(phase_dir: str, phase_id: str,
                 is_spoof: bool) -> List[Dict[str, Any]]:
    """All (kernel-shape) rows for one phase directory."""
    out: List[Dict[str, Any]] = []

    folder_yaml: Dict[str, str] = {}
    for y in sorted(glob.glob(os.path.join(
            phase_dir, "1_BenchmarkProblems", "*", "Data", "00_Final.yaml"))):
        folder_yaml[os.path.basename(os.path.dirname(os.path.dirname(y)))] = y

    def yaml_for(cpath: str) -> Optional[str]:
        rel = os.path.relpath(cpath, phase_dir)
        parts = rel.split(os.sep)
        if "Data" in parts:
            idx = parts.index("Data")
            if idx >= 2:
                return folder_yaml.get(parts[idx - 1])
        base = os.path.basename(cpath)
        stem = base.split("__")[0]
        if stem.endswith(".csv"):
            stem = stem[:-4]
        return folder_yaml.get(stem)

    cfg: Dict[str, Any] = {}
    if folder_yaml:
        cfg = parse_config(folder_yaml[sorted(folder_yaml)[0]])
    elif is_spoof:
        cfg = floor_config_from_name(phase_id)

    csvs = sorted(glob.glob(os.path.join(
        phase_dir, "1_BenchmarkProblems", "*", "Data", "00_Final.csv")))
    csvs += sorted(glob.glob(os.path.join(phase_dir, "2_BenchmarkData", "*.csv")))
    if not csvs:
        return out

    per_kernel: Dict[Tuple[str, str], List[Tuple[float, Dict[str, Any]]]] = defaultdict(list)
    for cpath in csvs:
        ypath = yaml_for(cpath) or (os.path.join(os.path.dirname(cpath), "00_Final.yaml")
                                    if os.path.exists(os.path.join(os.path.dirname(cpath),
                                                                   "00_Final.yaml"))
                                    else None)
        ecfg = parse_config(ypath) if ypath else dict(cfg)
        try:
            with open(cpath) as f:
                rd = csv.DictReader(f)
                if rd.fieldnames:
                    rd.fieldnames = [h.strip() for h in rd.fieldnames]
                cols = rd.fieldnames or []
                rows = [{k.strip(): v.strip() for k, v in row.items()
                         if k is not None and v is not None} for row in rd]
            kcols = [c for c in cols if "Cijk" in c or "MT" in c]
            if not kcols:
                continue
            kc = kcols[0]
            for row in rows:
                if not row or not row.get("SizeI"):
                    continue
                s = f"{row['SizeI']}x{row['SizeJ']}x{row.get('SizeL', '1024')}"
                try:
                    val = float(row[kc])
                except (ValueError, TypeError):
                    continue
                per_kernel[(kc, s)].append((val, ecfg))
        except (OSError, ValueError):
            continue

    for (kc, s), vcfg in sorted(per_kernel.items()):
        vals = [v for v, _ in vcfg]
        cfgset = [c for _, c in vcfg]
        if not vals:
            continue
        vals.sort()
        n = len(vals)
        med = (vals[n // 2] + vals[(n - 1) // 2]) / 2.0
        cfg = cfgset[0] if cfgset else {}
        dt_enum = cfg.get("DataTypeEnum")
        # Family attribution: the kernel's own typecode is the ground truth
        # (SB/DB/HB/CB/ZB, HHS/HSS -> HH). phase_id text and the config enum can
        # both lie about family — the `phase_auto_*` pool used to resolve to 'S'
        # through its 'auto' prefix (the §13.2 contamination). Never derive a
        # cell family from text when the kernel name is available.
        tc_family = family_from_kernel_name(kc)
        tc_code = kernel_typecode(kc)
        if tc_family:
            family = tc_family
            dt = FAMILY_DTYPE_CHAR.get(family, "?")
        else:
            m = FAMILY_RE.match(phase_id)
            family = _DEFAULT_DTYPE.get(m.group(1), "") if m else ""
            if family:
                family = _REVERSE_DEFAULT_DTYPE.get(family, "")
            dt_enum = cfg.get("DataTypeEnum")
            if dt_enum is None:
                dt = family or "?"
                dt_enum = -1
            else:
                dt = ENUM_TO_DTYPE.get(dt_enum, f"?{dt_enum}")
        entry: Dict[str, Any] = {
            "phase": phase_id,
            "kernel": kc,
            "shape": s,
            "gflops_best": max(vals),
            "gflops_median": round(med, 3),
            "n_seeds": n,
            "dtype": dt,
            "dtype_enum": dt_enum,
            "family": family,
            "typecode": tc_code,
        }
        for kk in ("MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU",
                   "VectorWidth", "DepthU", "GlobalLoadVectorWidthA",
                   "GlobalLoadVectorWidthB", "ISA"):
            entry[kk] = cfg.get(kk)
        out.append(entry)
    return out


def build_kernel_db(base_dir: str,
                    run_ids: Optional[Sequence[str]] = None,
                    all_ref: bool = False,
                    quiet: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """Rebuild the full kernel DB from run directories (CPU-only).

    `quiet=True` suppresses the per-run progress lines (used by the automatic
    post-run refresh in registry.SQLiteRegistry).
    """
    runs = discover_runs(base_dir, all_ref=all_ref)
    if run_ids:
        runs = [(rid, kind) for rid, kind in runs if rid in set(run_ids)]
    cache: Dict[str, List[Dict[str, Any]]] = {}
    for run_id, kind in runs:
        run_dir = os.path.join(base_dir, "gfx90c_runs", run_id)
        if not os.path.isdir(run_dir):
            cache[run_id] = []
            continue
        phases = sorted(glob.glob(os.path.join(run_dir, "phase_*"))
                        + glob.glob(os.path.join(run_dir, "probe_*")))
        acc: List[Dict[str, Any]] = []
        for pd in phases:
            acc.extend(phase_survey(pd, os.path.basename(pd), kind == "spoof"))
        cache[run_id] = acc
        if not quiet:
            sys.stderr.write(f"{run_id}: {len(phases)} phase dirs "
                             f"-> {len(acc)} kernel-shape rows\n")
    return cache


def load_kernel_db(cache_path: str, base_dir: Optional[str] = None,
                   rebuild: bool = False,
                   run_ids: Optional[Sequence[str]] = None,
                   all_ref: bool = False,
                   quiet: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """Load the cached kernel DB, rebuilding when missing/forced.

    `base_dir` (default: repo root) enables a lazy rebuild when the cache is
    absent, so a fresh checkout can regenerate without a prior artifact.
    The rebuild writes the cache atomically (temp file + rename), so a reader
    that opens the cache mid-rebuild never sees a torn JSON blob.
    """
    if not rebuild and Path(cache_path).is_file():
        try:
            with open(cache_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    if base_dir is None:
        base_dir = str(Path(__file__).resolve().parents[2])
    db = build_kernel_db(base_dir, run_ids=run_ids, all_ref=all_ref, quiet=quiet)
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{cache_path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(db, f)
    os.replace(tmp, cache_path)
    return db


DEFAULT_CACHE = "gfx90c_results/analysis/kernel_db.json"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", default=None,
                    help="repo root (default: this repo)")
    ap.add_argument("--json", default=DEFAULT_CACHE,
                    help=f"cache path (default: {DEFAULT_CACHE})")
    ap.add_argument("--rebuild", action="store_true",
                    help="rescan run dirs and overwrite the cache")
    ap.add_argument("--all-ref", action="store_true",
                    help="include every gfx900_ref_* dir (default: locked floor only)")
    ap.add_argument("--run-id", nargs="*", default=None,
                    help="only these run ids")
    args = ap.parse_args(argv)

    base = args.base_dir or str(Path(__file__).resolve().parents[2])
    db = load_kernel_db(args.json, base_dir=base, rebuild=args.rebuild,
                        run_ids=args.run_id, all_ref=args.all_ref)
    n_rows = sum(len(v) for v in db.values())
    n_runs = sum(1 for v in db.values() if v)
    print(f"{args.json}: {n_runs} runs with data, {n_rows} kernel-shape rows "
          f"({len(db)} runs scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())