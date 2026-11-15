#!/usr/bin/env python3
"""Resident-workgroup audit per (family, shape) cell.

Owns: the physical residency bounds on the current kernel_db rebuild -- LDS-bound,
VGPR-bound and wave-slot-bound -- and their minimum, because ``MaxOccupancy`` in
the kernel metadata is a REGISTER-SLOT count, not resident workgroups.

Does NOT own: the register-file model it takes as truth
(`oto.tensile.gates.vgpr_model`), the kernel_db rows it reads
(`oto.harness.kernel_db`), or the gate that decides launchability
(`oto.tensile.gates.occupancy`).

Public API: main.

The three bounds per cell are ``LDS-bound = 64 KB/CU / (double-buffered A+B tile
footprint)``, ``VGPR-bound = 64 K/CU / (workgroup threads x measured total
VGPR/thread)`` and ``wave-bound = 40 wave slots/CU / (waves per workgroup,
wave64)``; resident workgroups per CU is their minimum. Tensile prefetches A and
B into two LDS buffers, so the double-buffer factor is adjustable with
``--lds-factor`` (1 = single-buffered probe). ``--side floor`` audits the spoof
arm instead of the native winners.

CPU only. Reads ``<codename>_results/analysis/kernel_db.json`` (typecode-corrected
rebuild, the same provenance ``cell_knob_diff`` and the acceptance report cite).

    python3 -m `oto.harness.occupancy_bounds`                 # native winners
    python3 -m `oto.harness.occupancy_bounds` --side floor    # spoof-floor winners
    python3 -m `oto.harness.occupancy_bounds` --lds-factor 1  # single-buffered LDS
    python3 -m `oto.harness.occupancy_bounds` --at-most 3     # cells at <= N wg/CU
"""


from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from statistics import median

from oto.device import loader as _loader
from oto.runners.result_paths import results_dir
from oto.tensile.gates.vgpr_model import (
    BYTES_PER_ELEMENT,
    MEASURED_VGPR_BY_DTYPE,
)

FAMILY_CHAR = {                            # typecode -> dtype character
    "SS": "S", "DD": "D", "HH": "H", "HS": "S",
    "CC": "C", "ZZ": "Z", "FF": "S",
    "HH_HPA": "H", "HS_HPA": "S",
}


def _ints(raw: object) -> list[int]:
    """All integer tokens in `raw` (``[]`` when `raw` is empty)."""
    if not raw:
        return []
    return [int(x) for x in re.findall(r"\d+", str(raw))]


def _winner_per_cell(rows: Iterable[dict]) -> dict[tuple[str, int], dict]:
    """Best per-(family, side) row by gflops_median (seed-medians pre-folded)."""
    best: dict[tuple[str, int], dict] = {}
    for r in rows:
        fam, shape = r.get("family"), r.get("shape")
        if not fam or not shape or not str(shape).count("x"):
            continue
        try:
            side = int(str(shape).split("x")[0])
        except ValueError:
            continue
        med = r.get("gflops_median") or 0
        key = (fam, side)
        if key not in best or med > (best[key].get("gflops_median") or 0):
            best[key] = r
    return best


def _bounds(row: dict, lds_factor: int, profile=None) -> tuple[int, int, int, int, str, dict] | None:
    """(lds_bound, vgpr_bound, wave_bound, resident, binder, info).

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    fam = row.get("family", "",)
    ch = FAMILY_CHAR.get(fam,)
    if not ch:
        return None
    mt = _ints(row.get("MacroTile",))
    tt = _ints(row.get("ThreadTile",))
    wg = _ints(row.get("WorkGroup",))
    ku = _ints(row.get("DepthU",))
    if len(mt) < 2 or len(tt) < 2:
        return None
    wg_threads = (wg[0] * wg[1]) if len(wg) >= 2 else (mt[0] * mt[1]) // (tt[0] * tt[1])
    if wg_threads <= 0:
        wg_threads = 256
    ku = ku[0] if ku else 8
    bpe = _loader.resolve_profile(profile,).family_bytes_per_element.get(fam,) or BYTES_PER_ELEMENT.get(ch, 1,)
    measured = (MEASURED_VGPR_BY_DTYPE.get(ch,) or {}).get((tt[0], tt[1]),)
    if measured is None:
        return None
    lds_base = (mt[0] + mt[1]) * bpe * ku
    lds_bound = max(1, (_loader.resolve_profile(profile,).lds_per_cu_kb * 1024) // (max(1, lds_base) * lds_factor))
    vgpr_bound = max(1, _loader.resolve_profile(profile,).vgpr_per_cu // (wg_threads * measured))
    waves_per_wg = max(1, wg_threads // 64)
    wave_bound = max(1, _loader.resolve_profile(profile,).max_waves_per_cu // waves_per_wg)
    resident = min(lds_bound, vgpr_bound, wave_bound)
    binder = ("LDS" if lds_bound == resident else
              "VGPR" if vgpr_bound == resident else "waves")
    info = {
        "ch": ch, "bpe": bpe, "ku": ku, "mt": mt[:2], "tt": tt[:2],
        "wg_threads": wg_threads, "measured_vgpr": measured,
        "lds_base_b": lds_base, "waves_per_wg": waves_per_wg,
    }
    return lds_bound, vgpr_bound, wave_bound, resident, binder, info


def _floor_rows(db: dict[str, list[dict]]) -> tuple[list[dict], list[str]]:
    """Floor rows for the audit.

    Locked reference runs are preferred (the published floor); when the
    cache carries no locked run this falls back to every ``gfx900_ref_*``
    run present, never to a hardcoded run id. Returns ``(rows, chosen)``.
    """
    _locked = f"{_loader.spoof_prefix()}_ref_locked_"
    _floor = f"{_loader.spoof_prefix()}_ref_"
    chosen = sorted(k for k in db if k.startswith(_locked))
    if not chosen:
        chosen = sorted(k for k in db if k.startswith(_floor))
    return [r for k in chosen for r in db[k]], chosen


def _audit(rows_iter: Iterable[dict], lds_factor: int, profile=None) -> list[dict]:
    """Resident-workgroup audit per cell. ``profile`` selects the device; ambient by default."""
    winners = _winner_per_cell(rows_iter)
    out: list[dict] = []
    for (fam, side), row in sorted(winners.items()):
        b = _bounds(row, lds_factor, profile=profile,)
        if b is None:
            continue
        lds, vgp, wav, res, binder, info = b
        waves_cu = res * info["waves_per_wg"]
        out.append({
            "cell": f"{fam}:{side}", "kernel": row.get("kernel", "",),
            "lds_bound": lds, "vgpr_bound": vgp, "wave_bound": wav,
            "resident": res, "binder": binder,
            "waves_per_cu": waves_cu,
            "pct_of_40": waves_cu / _loader.resolve_profile(profile,).max_waves_per_cu * 100,
            "median_gflops": row.get("gflops_median",) or 0,
        })
    return out


def _select_rows(db: dict, args, profile) -> list[dict] | None:
    """Rows for ``args.side``, or None with the reason printed to stderr."""
    if args.side == "floor":
        rows, chosen = _floor_rows(db)
        if not rows:
            print(f"no floor rows found (no {_loader.spoof_prefix(profile)}_ref_* keys in kernel_db.json)",
                  file=sys.stderr)
            return None
        print(f"floor runs: {', '.join(chosen)}", file=sys.stderr)
        return rows
    floor = f"{_loader.spoof_prefix(profile)}_ref_"
    rows = [r for run, rs in db.items()
            for r in rs if not run.startswith(floor)]
    if not rows:
        print(f"no rows under side={args.side}", file=sys.stderr)
        return None
    return rows


def main(profile=None) -> int:
    """Print the resident-workgroup audit; ``profile`` selects the device (ambient by default)."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--side", choices=("native", "floor"), default="native",
                    help="audit native winners (default) or the locked reference floor")
    ap.add_argument("--lds-factor", type=int, default=2,
                    help="LDS double-buffer factor (1 = single-buffer probe)")
    ap.add_argument("--at-most", type=int, default=None,
                    help="only print cells with resident wg/CU <= N")
    ap.add_argument("--base-dir", "--base", type=Path, default=None,
                    help="repo root (default: this module's parent package root)")
    args = ap.parse_args()

    base = args.base_dir or Path(__file__).resolve().parents[2]
    db_path = results_dir(base, _loader.resolve_profile(profile,).codename) / "analysis" / "kernel_db.json"
    with open(db_path) as f:
        db = json.load(f)
    rows = _select_rows(db, args, profile)
    if rows is None:
        return 1

    cells = _audit(rows, args.lds_factor, profile=profile,)
    if not cells:
        print("no auditable cells (measured-VGPR table missing their TT)", file=sys.stderr)
        return 1

    hdr = (f"{'cell':<9}{'resident':>8}{'binder':>7}{'waves/CU':>9}"
           f"{'% of 40':>8}{'LDS':>5}{'VGPR':>6}{'WAV':>5}{'med GF':>9}")
    print(f"occupancy audit: side={args.side} lds_factor={args.lds_factor} "
          f"cells={len(cells)}")
    print(hdr)
    for c in cells:
        if args.at_most is not None and c["resident"] > args.at_most:
            continue
        print(f"{c['cell']:<9}{c['resident']:>8}{c['binder']:>7}"
              f"{c['waves_per_cu']:>9}{c['pct_of_40']:>7.0f}%"
              f"{c['lds_bound']:>5}{c['vgpr_bound']:>6}{c['wave_bound']:>5}"
              f"{c['median_gflops']:>9.1f}")

    res = [c["resident"] for c in cells]
    waves = [c["waves_per_cu"] for c in cells]
    low = [c for c in cells if c["resident"] <= 3]
    binders = Counter(c["binder"] for c in cells)
    print(f"\nresident wg/CU: min={min(res)} median={median(res)} max={max(res)}")
    print(f"cells at <=3 resident wg/CU: {len(low)} / {len(cells)}")
    print(f"waves/CU: min={min(waves)} median={median(waves)} max={max(waves)}"
          f" (budget {_loader.resolve_profile(profile,).max_waves_per_cu}/CU)")
    print(f"binding resource tally: {dict(binders)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
