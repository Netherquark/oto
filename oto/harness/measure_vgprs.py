#!/usr/bin/env python3
"""Measure real per-thread VGPRs from Tensile-emitted code objects.

Owns: reading the AMDGPU metadata of each phase's compiled ``.o`` and comparing
the measured VGPR count against the model, which is the only way to retire the
model's calibration headroom.

Does NOT own: the model itself (oto.tensile.gates.vgpr_model), building the
objects (the Tensile driver does that), or the audit that consumes the ratio
(oto.harness.occupancy_audit).

Public API: main.

Every run dir under the runs directory carries a phase's compiled kernel objects at
``<run>/<phase>/1_BenchmarkProblems/<Kernel>/00_Final/source/build_tmp/SOURCE/assembly/<kernel>.o``,
whose AMDGPU metadata holds the true ``vgpr_count``. This tool parses them with
``llvm-readelf`` (CPU-only, no GPU) and reports, per (dtype char, ThreadTile), the
measured per-kernel counts and median, the model's accumulator VGPRs for the same
ThreadTile, and the measured/model ratio -- the headroom indicator.

    python3 -m oto.harness.measure_vgprs                 # whole corpus
    python3 -m oto.harness.measure_vgprs --run run_20261008_030033
    python3 -m oto.harness.measure_vgprs --json out.json
"""


from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from oto import yamlio

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.device import loader as _loader
from oto.runners.paths import runs_dir as _runs_dir
from oto.tensile.gates.vgpr_model import measured_accvgpr

_TYPECODE_CORE = re.compile(r"_(MT\d+x\d+(?:x\d+)?)_")
_WEIGHT = {"S": 1, "D": 2, "H": 1, "C": 2, "Z": 8}


def _vgpr_from_object(obj: Path) -> dict[str, Any] | None:
    """Read the MAIN kernel's vgpr_count from the code-object metadata.

    The notes carry TWO kinds of `.name: X / .vgpr_count: N` pairs: the
    kernarg descriptors (indented `- .name:` list entries) and the kernel
    itself (top-level `.name: Cijk_...`). We must take the Cijk kernel's pair,
    not the first arg descriptor's.
    """
    out = subprocess.run(["llvm-readelf", "--notes", str(obj)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    pairs = re.findall(r"\.name:\s+(Cijk_\S+).*?\.vgpr_count:\s+(\d+)",
                       out.stdout, flags=re.DOTALL)
    vgpr = None
    kernel = obj.stem
    for name, count in pairs:
        if name.startswith("Cijk_") or name == obj.stem:
            vgpr = int(count)
            kernel = name
            break
    if vgpr is None:
        return None
    return {"vgpr": vgpr, "kernel": kernel}


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="only this run dir name")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--base-dir", "--base", type=Path, default=None,
                    help="repo root override")
    ap.add_argument("--runs", type=Path, default=None,
                    help="runs directory (default: <base-dir>/<codename>_runs)")
    return ap


def _collect_objects(runs_dir: Path, run_filter: str | None) -> list[Path]:
    objs: list[Path] = []
    for run_dir in sorted(runs_dir.glob("run_*")):
        if not run_dir.is_dir():
            continue
        if run_filter and run_dir.name != run_filter:
            continue
        objs += sorted(run_dir.glob("phase_*/1_BenchmarkProblems/*/00_Final/source/"
                                    "build_tmp/SOURCE/assembly/*.o"))
    return objs


def _extract_key(obj: Path) -> tuple[str, int, int] | None:
    """(dtype_char, TT0, TT1) from an object file, or None if not decodable."""
    info = _vgpr_from_object(obj)
    if not info:
        return None
    name = info["kernel"]
    # dtype from the kernel typecode token (SB/DB/HB/CB/ZB/HHS -> S/D/H/C/Z).
    tc = name.split("_MT")[0].split("_")
    code_ch = ""
    for tok in reversed(tc):
        u = tok.upper()
        if u in ("SN", "SE", "GB", "BH"):
            continue
        if u[:1] in _WEIGHT:
            code_ch = u[:1]
            break
    # ThreadTile lives in the phase dir name (phase_<fam>_<shape>_<mt>_tt<X>x<Y>_...)
    # for candidate phases, or in the phase's Data/00_Final.yaml for the
    # auto-pool phases (whose ids carry no tt token).
    phase_dir = obj.parent
    while not phase_dir.name.startswith("phase_") and phase_dir.parent != phase_dir:
        phase_dir = phase_dir.parent
    m_tt = re.search(r"tt(\d+)x(\d+)", phase_dir.name)
    tt = None
    if m_tt:
        tt = (int(m_tt.group(1)), int(m_tt.group(2)))
    else:
        cfg_yaml = phase_dir / "Data" / "00_Final.yaml"
        if cfg_yaml.exists():
            try:
                cfgd = yamlio.load_yaml(cfg_yaml) or {}
                ttr = str(cfgd.get("ThreadTile") or cfgd.get("thread_tile") or "")
                m2 = re.search(r"(\d+)x(\d+)", ttr.replace(",", "x"))
                if m2:
                    tt = (int(m2.group(1)), int(m2.group(2)))
            except Exception:
                tt = None
    if not code_ch or not tt:
        return None
    return (code_ch, tt[0], tt[1])


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'dtype':5} {'TT':8} {'n':>4} {'measured med':>12} {'model acc':>10} {'ratio':>7}")
    for _r in rows:
        print(f"{_r['dtype']:5} {_r['tt']:<6} {_r['n']:>4} "
              f"{_r['measured_median_vgpr']:>12} {_r['model_acc_vgpr']:>10} "
              f"{_r['ratio']:>7.2f}")


def main(profile=None) -> int:
    """CLI: measured per-thread VGPRs of emitted kernels. ``profile`` selects the device; ambient by default."""
    args = _build_arg_parser().parse_args()

    base = Path(args.base_dir) if args.base_dir else _HERE
    runs_dir = Path(args.runs) if args.runs else _runs_dir(base, _loader.resolve_profile(profile,).codename)
    objs = _collect_objects(runs_dir, args.run)
    if not objs:
        print("no Tensile assembly objects found (run a phase first)")
        return 1

    by_key: dict[tuple[str, int, int], dict[str, Any]] = defaultdict(lambda: {"counts": []})
    for obj in objs:
        key = _extract_key(obj)
        if key is None:
            continue
        info = _vgpr_from_object(obj)
        if info is None:
            continue
        by_key[key]["counts"].append(info["vgpr"])

    print(f"{len(objs)} objects scanned, {sum(len(v['counts']) for v in by_key.values())} mapped\n")
    rows: list[dict[str, Any]] = []
    for key in sorted(by_key):
        _ch, _tt0, _tt1 = key
        counts = sorted(by_key[key]["counts"])
        med = counts[len(counts) // 2]
        model = measured_accvgpr(key[1], key[2], _WEIGHT[key[0]])
        ratio = med / model if model else 0.0
        print(f"{key[0]:5} {key[1]}x{key[2]:<6} {len(counts):>4} {med:>12} {model:>10} {ratio:>7.2f}")
        rows.append({"dtype": key[0], "tt": f"{key[1]}x{key[2]}", "n": len(counts),
                     "measured_median_vgpr": med, "model_acc_vgpr": model,
                     "ratio": round(ratio, 2)})
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
