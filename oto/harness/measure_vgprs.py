#!/usr/bin/env python3
"""Measure real per-thread VGPRs from Tensile-emitted code objects.

Owns: reading the AMDGPU metadata of each phase's compiled ``.o`` and comparing
the measured VGPR count against the model, which is the only way to retire the
model's calibration headroom.

Does NOT own: the model itself (oto.tensile.gates.vgpr_model), building the
objects (the Tensile driver does that), or the audit that consumes the ratio
(oto.harness.occupancy_audit).

Public API: main.

Every run dir under ``gfx90c_runs/`` carries a phase's compiled kernel objects at
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
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.device.peaks import FAMILY_DTYPE_CHAR          # noqa: E402
from oto.tensile.gates.occupancy import tile_dims  # noqa: E402
from oto.tensile.gates.vgpr_model import measured_accvgpr  # noqa: E402

_TYPECODE_CORE = re.compile(r"_(MT\d+x\d+(?:x\d+)?)_")
_WEIGHT = {"S": 1, "D": 2, "H": 1, "C": 2, "Z": 8}


def _vgpr_from_object(obj: Path) -> Optional[Dict[str, Any]]:
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
                       out.stdout, flags=re.S)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="only this run dir name")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    runs_dir = _HERE / "gfx90c_runs"
    objs: List[Path] = []
    for run_dir in sorted(runs_dir.glob("run_*")):
        if not run_dir.is_dir():
            continue
        if args.run and run_dir.name != args.run:
            continue
        objs += sorted(run_dir.glob("phase_*/1_BenchmarkProblems/*/00_Final/source/"
                                    "build_tmp/SOURCE/assembly/*.o"))
    if not objs:
        print("no Tensile assembly objects found (run a phase first)")
        return 1

    by_key: Dict[Tuple[str, int, int], Dict[str, Any]] = defaultdict(lambda: {"counts": []})
    for obj in objs:
        info = _vgpr_from_object(obj)
        if not info:
            continue
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
                import yaml
                try:
                    cfgd = yaml.safe_load(cfg_yaml.read_text()) or {}
                    ttr = str(cfgd.get("ThreadTile") or cfgd.get("thread_tile") or "")
                    m2 = re.search(r"(\d+)x(\d+)", ttr.replace(",", "x"))
                    if m2:
                        tt = (int(m2.group(1)), int(m2.group(2)))
                except Exception:
                    tt = None
        if not code_ch or not tt:
            continue
        key = (code_ch, tt[0], tt[1])
        by_key[key]["counts"].append(info["vgpr"])

    print(f"{len(objs)} objects scanned, {sum(len(v['counts']) for v in by_key.values())} mapped\n")
    print(f"{'dtype':5} {'TT':8} {'n':>4} {'measured med':>12} {'model acc':>10} {'ratio':>7}")
    rows: List[Dict[str, Any]] = []
    for key in sorted(by_key):
        ch, tt0, tt1 = key
        counts = sorted(by_key[key]["counts"])
        med = counts[len(counts) // 2]
        model = measured_accvgpr(tt0, tt1, _WEIGHT[ch])
        ratio = med / model if model else 0.0
        print(f"{ch:5} {tt0}x{tt1:<6} {len(counts):>4} {med:>12} {model:>10} {ratio:>7.2f}")
        rows.append({"dtype": ch, "tt": f"{tt0}x{tt1}", "n": len(counts),
                     "measured_median_vgpr": med, "model_acc_vgpr": model,
                     "ratio": round(ratio, 2)})
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())