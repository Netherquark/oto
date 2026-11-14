#!/usr/bin/env python3
"""Ground-truth per-kernel-per-shape GFLOPS database.

Owns: walking every run/phase directory under the runs directory and producing, per
(phase, kernel-shape) row, the per-seed best and median GFlops plus the
structural config -- the canonical, repo-homed provenance the other harness
modules cite.

Does NOT own: the verdicts (oto.metrics.ab_audit), the regression rules
(oto.harness.regression_matrix), or the candidate deck
(oto.harness.candidate_rows).

Public API: load_kernel_db, read_kernel_db, build_kernel_db, main.

The structural config comes from each folder's ``Data/00_Final.yaml``; the gfx900
floor config is rebuilt from the solution name when the folder is absent. Dtype
is resolved from the config's ``ProblemType.DataType`` enum
(0=S f32, 1=D f64, 2=C complex f32, 3=Z complex f64, 4=H f16).

Default scopes: native runs = every ``<runs>/run_*`` directory; the spoof
floor = ``<runs>/gfx900_ref_locked_*`` only. ``--all-ref`` also folds in the
other completed ``gfx900_ref_*`` directories, which are chained rebuilds and are
excluded by default so a regeneration stays byte-identical to the published
matrix.

Output: ``<codename>_results/analysis/kernel_db.json`` (run_id -> rows). CPU only.

    python3 -m oto.harness.kernel_db --rebuild
    python3 -m oto.harness.kernel_db --json out.json
    python3 -m oto.harness.kernel_db --all-ref
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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Repo-root import for the canonical typecode->family resolver (single source of
# truth in oto/device/loader.py). kernel_db runs as
# `python3 -m oto.harness.kernel_db`,
# where sys.path[0] is the harness dir, so the repo root must be inserted first.
_HERE = Path(__file__).resolve().parents[2]
for _p in (str(_HERE), os.environ.get("TENSILE_ROOT")):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from oto.device import loader as _loader
from oto.device.vocabulary import family_from_kernel_name, kernel_typecode
from oto.metrics.family_attribution import extract_family_from_phase_id
from oto.metrics.protocol import classify_count, problem_count_text
from oto.runners.paths import results_rel
from oto.runners.paths import runs_dir as _runs_dir

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
                  all_ref: bool = False, profile=None) -> list[tuple[str, str]]:
    """[(run_id, kind)] for native `run_*` + spoof floor runs.

    kind is 'native' for `run_*` and 'spoof' for `gfx900_ref_*`. With
    all_ref=False only the locked floor (`gfx900_ref_locked_*`) is included,
    matching the published regression matrix; all_ref=True includes every
    gfx900 reference directory.
    """
    runs_dir = _runs_dir(base_dir, _loader.resolve_profile(profile,).codename)
    out: list[tuple[str, str]] = []
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


def parse_config(yaml_path: str) -> dict[str, Any]:
    """Structural config from a Tensile `Data/00_Final.yaml`.

    Text-scan based (same parser the exploration script validated against the
    live corpus) — reads scalars, the ProblemType DataType enum, and the ISA.
    Also reads the INTENDED PROBLEM COUNT (the number of ``- Exact:`` rows,
    i.e. how large an invocation the phase declared) as ``ProblemSizesCount``:
    that count plus the CSV's measured sides is what the invocation-form
    classifier (oto.metrics.protocol) stamps per row (§R56.3).
    Returns {} on any read failure; callers fall back to their run-level
    default config.
    """
    try:
        with open(yaml_path) as f:
            text = f.read()
    except OSError:
        return {}
    cfg: dict[str, Any] = {}
    for key in CONFIG_KEYS:
        m = re.search(rf"^  {re.escape(key)}: (.+)$", text, re.MULTILINE)
        if m:
            cfg[key] = m.group(1).strip()
    pt = text.find("ProblemType:")
    if pt >= 0:
        m = re.search(r"DataType: (\d+)", text[pt:pt + 800])
        if m:
            cfg["DataTypeEnum"] = int(m.group(1))
    m = re.search(r"^  ISA: \[([^\]]+)\]", text, re.MULTILINE)
    if m:
        cfg["ISA"] = m.group(1).split(",")
    n_problems = problem_count_text(text)
    if n_problems:
        cfg["ProblemSizesCount"] = n_problems
    return cfg


def floor_config_from_name(phase_id: str) -> dict[str, Any]:
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


def _yaml_index(phase_dir: str) -> dict[str, str]:
    """folder -> 00_Final.yaml, keyed by the BenchmarkProblems subfolder."""
    folder_yaml: dict[str, str] = {}
    for y in sorted(glob.glob(os.path.join(
            phase_dir, "1_BenchmarkProblems", "*", "Data", "00_Final.yaml"))):
        folder_yaml[os.path.basename(os.path.dirname(os.path.dirname(y)))] = y
    return folder_yaml


def _yaml_for(cpath: str, phase_dir: str,
              folder_yaml: dict[str, str]) -> str | None:
    """The 00_Final.yaml a CSV belongs to, by folder or by file stem."""
    rel = os.path.relpath(cpath, phase_dir)
    parts = rel.split(os.sep)
    if "Data" in parts:
        idx = parts.index("Data")
        if idx >= 2:
            return folder_yaml.get(parts[idx - 1])
    base = os.path.basename(cpath)
    stem = base.split("__")[0]
    stem = stem.removesuffix(".csv")
    return folder_yaml.get(stem)


def _accumulate_rows(
    csvs: list[str],
    phase_dir: str,
    folder_yaml: dict[str, str],
    cfg: dict[str, Any],
) -> dict[tuple[str, str], list[tuple[float, dict[str, Any]]]]:
    """phase measurement rows, keyed by (kernel column, shape)."""
    per_kernel: dict[tuple[str, str], list[tuple[float, dict[str, Any]]]] = \
        defaultdict(list)
    for cpath in csvs:
        ypath = _yaml_for(cpath, phase_dir, folder_yaml) or (os.path.join(
            os.path.dirname(cpath), "00_Final.yaml")
            if os.path.exists(os.path.join(os.path.dirname(cpath),
                                           "00_Final.yaml")) else None)
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
    return per_kernel


def _family_and_dtype(cfg: dict[str, Any], kc: str,
                      phase_id: str, profile=None) -> tuple[str, str, Any]:
    """(family, dtype, dtype_enum) for one kernel row.

    Family attribution: the kernel's own typecode is the ground truth
    (SB/DB/HB/CB/ZB, HHS/HSS -> HH). phase_id text and the config enum can
    both lie about family — the `phase_auto_*` pool used to resolve to 'S'
    through its 'auto' prefix (the §13.2 contamination). Never derive a
    cell family from text when the kernel name is available.
    """
    dt_enum = cfg.get("DataTypeEnum",)
    tc_family = family_from_kernel_name(kc)
    if tc_family:
        family = tc_family
        dt = _loader.resolve_profile(profile,).family_dtype_char.get(family, "?",)
    else:
        m = FAMILY_RE.match(phase_id)
        family = _DEFAULT_DTYPE.get(m.group(1), "",) if m else ""
        if family:
            family = _REVERSE_DEFAULT_DTYPE.get(family, "",)
        dt_enum = cfg.get("DataTypeEnum",)
        if dt_enum is None:
            dt = family or "?"
            dt_enum = -1
        else:
            dt = ENUM_TO_DTYPE.get(dt_enum, f"?{dt_enum}",)
    return family, dt, dt_enum


def _kernel_entry(kc: str, s: str, vcfg: list[tuple[float, dict[str, Any]]],
                  phase_id: str, measured_sides: list[str],
                  n_problems: int | None = None,
                  phase_family: str = "") -> dict[str, Any] | None:
    """One kernel-db row for a (kernel column, shape) group."""
    vals = [v for v, _ in vcfg]
    cfgset = [c for _, c in vcfg]
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    med = (vals[n // 2] + vals[(n - 1) // 2]) / 2.0
    cfg = cfgset[0] if cfgset else {}
    family, dt, dt_enum = _family_and_dtype(cfg, kc, phase_id)
    # Invocation form (§R56.3): the number of problems the phase asked for
    # (from its own yaml) plus the sides its CSVs yielded, classified under
    # the PHASE's family -- the deck intent the phase was launched for, not
    # the kernel typecode alone (an HPA phase's kernels read 'HH', which
    # would misgrade its form against the HH contract's five cells).
    fam_for_protocol = phase_family or (family if family != "?" else "")
    entry: dict[str, Any] = {
        "phase": phase_id,
        "kernel": kc,
        "shape": s,
        "gflops_best": max(vals),
        "gflops_median": round(med, 3),
        "n_seeds": n,
        "dtype": dt,
        "dtype_enum": dt_enum,
        "family": family,
        "typecode": kernel_typecode(kc),
        "n_problems": n_problems,
        "protocol": classify_count(fam_for_protocol, n_problems,
                                   measured_sides),
    }
    for kk in ("MacroTile", "ThreadTile", "WorkGroup", "GlobalSplitU",
               "VectorWidth", "DepthU", "GlobalLoadVectorWidthA",
               "GlobalLoadVectorWidthB", "ISA"):
        entry[kk] = cfg.get(kk)
    return entry


def phase_survey(phase_dir: str, phase_id: str,
                 is_spoof: bool) -> list[dict[str, Any]]:
    """All (kernel-shape) rows for one phase directory."""
    folder_yaml = _yaml_index(phase_dir)

    cfg: dict[str, Any] = {}
    if folder_yaml:
        cfg = parse_config(folder_yaml[min(folder_yaml)])
    elif is_spoof:
        cfg = floor_config_from_name(phase_id)

    csvs = sorted(glob.glob(os.path.join(
        phase_dir, "1_BenchmarkProblems", "*", "Data", "00_Final.csv")))
    csvs += sorted(glob.glob(os.path.join(phase_dir, "2_BenchmarkData", "*.csv")))
    if not csvs:
        return []

    per_kernel = _accumulate_rows(csvs, phase_dir, folder_yaml, cfg)
    if not per_kernel:
        return []

    # The phase's invocation form is a phase-level fact: every row it merged
    # shares the declared problem count (the sum of its folder yamls' counts
    # -- almost always one folder; the floor's rejection-dumped phases have no
    # yaml at all, which leaves the count UNKNOWN and the CSV sides decide)
    # and its measured side set. Rows inherit it.
    counts: list[int] = []
    for ypath in folder_yaml.values():
        try:
            counts.append(problem_count_text(Path(ypath).read_text()))
        except OSError:
            continue
    n_problems = sum(counts) or None
    measured_sides = sorted({s for (_kc, s) in per_kernel})
    pfam = extract_family_from_phase_id(phase_id)

    out: list[dict[str, Any]] = []
    for (kc, s), vcfg in sorted(per_kernel.items()):
        entry = _kernel_entry(kc, s, vcfg, phase_id, measured_sides,
                              n_problems=n_problems, phase_family=pfam)
        if entry is not None:
            out.append(entry)
    return out


def build_kernel_db(base_dir: str,
                    run_ids: Sequence[str] | None = None,
                    all_ref: bool = False,
                    quiet: bool = False, profile=None) -> dict[str, list[dict[str, Any]]]:
    """Rebuild the full kernel DB from run directories (CPU-only).

    `quiet=True` suppresses the per-run progress lines (used by the automatic
    post-run refresh in registry.SQLiteRegistry).
    """
    runs = discover_runs(base_dir, all_ref=all_ref, profile=profile,)
    if run_ids:
        runs = [(rid, kind) for rid, kind in runs if rid in set(run_ids)]
    cache: dict[str, list[dict[str, Any]]] = {}
    for run_id, kind in runs:
        run_dir = str(_runs_dir(base_dir, _loader.resolve_profile(profile,).codename) / run_id)
        if not os.path.isdir(run_dir):
            cache[run_id] = []
            continue
        phases = sorted(glob.glob(os.path.join(run_dir, "phase_*"))
                        + glob.glob(os.path.join(run_dir, "probe_*")))
        acc: list[dict[str, Any]] = []
        for pd in phases:
            try:
                acc.extend(phase_survey(pd, os.path.basename(pd), kind == "spoof"))
            except Exception as exc:  # pragma: no cover - defensive
                sys.stderr.write(f"  {run_id}/{os.path.basename(pd)}: skipped ({exc})\n")
        cache[run_id] = acc
        if not quiet:
            sys.stderr.write(f"{run_id}: {len(phases)} phase dirs "
                             f"-> {len(acc)} kernel-shape rows\n")
    return cache


#: The parsed cache, keyed by (path, size, mtime). The file is 18 MB of JSON
#: and every census, resolver and coverage map parses it; the corpus does not
#: change inside a session, so one parse serves them all.
_LOADED_CACHE: dict[tuple[str, int, float], dict[str, list[dict[str, Any]]]] = {}


def read_kernel_db(cache_path: str) -> dict[str, list[dict[str, Any]]]:
    """Read the cached kernel DB, memoised, without ever rebuilding it.

    The read-only sibling of :func:`load_kernel_db`: the analysis tools want
    the cache that is on disk (and an empty mapping when there is none), not a
    rebuild. The parse is memoised on (path, size, mtime), so the 18 MB of
    JSON is read once per session and a rewritten cache is re-read.

    Args:
        cache_path: The ``kernel_db.json`` to read.

    Returns:
        The ``run_id -> rows`` mapping (empty when the file is absent).
    """
    path = Path(cache_path)
    if not path.is_file():
        return {}
    try:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime)
        hit = _LOADED_CACHE.get(key)
        if hit is not None:
            return hit
        with open(path) as f:
            doc = json.load(f)
        if len(_LOADED_CACHE) > 4:
            _LOADED_CACHE.clear()
        _LOADED_CACHE[key] = doc
        return doc
    except (OSError, ValueError):
        return {}


def load_kernel_db(cache_path: str, base_dir: str | None = None,
                   rebuild: bool = False,
                   run_ids: Sequence[str] | None = None,
                   all_ref: bool = False,
                   quiet: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Load the cached kernel DB, rebuilding when missing/forced.

    `base_dir` (default: repo root) enables a lazy rebuild when the cache is
    absent, so a fresh checkout can regenerate without a prior artifact.
    The rebuild writes the cache atomically (temp file + rename), so a reader
    that opens the cache mid-rebuild never sees a torn JSON blob.

    The parsed document is memoised on (path, size, mtime): a rewritten cache
    is re-read, and a reader that arrives during a rebuild sees the old
    document rather than a torn one.
    """
    path = Path(cache_path)
    if not rebuild and path.is_file():
        try:
            stat = path.stat()
            key = (str(path.resolve()), stat.st_size, stat.st_mtime)
            hit = _LOADED_CACHE.get(key)
            if hit is not None:
                return hit
            with open(path) as f:
                doc = json.load(f)
            if len(_LOADED_CACHE) > 4:
                _LOADED_CACHE.clear()
            _LOADED_CACHE[key] = doc
            return doc
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


DEFAULT_CACHE = results_rel("analysis", "kernel_db.json")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", "--base", default=None,
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
