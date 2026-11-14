#!/usr/bin/env python3
"""Measured occupancy of every emitted Tensile kernel in the run corpus.

Owns: reading Tensile's own generated assembly (the `amdhsa_next_free_vgpr` /
`amdhsa_group_segment_fixed_size` directives) and turning it into the kernels'
actual resident-wave occupancy, joined to the GFLOP/s those kernels measured —
plus the Tensile CSV column trap that joins it.
Does NOT own: the *predicted* occupancy gate (oto.tensile.gates.occupancy), the
VGPR/LDS calibration tables (oto.tensile.gates.vgpr_model), the device constants
(`oto.device.loader`), or the predicted resident-workgroup audit
(oto.harness.occupancy_audit). This module measures what was emitted; that
module predicts what a gate would allow.

Public API: waves_per_simd, binding_resource, parse_asm_kernel,
read_phase_gflops, measure_corpus, main.

Why this exists alongside `occupancy_audit.py`: that module audits the *predicted*
bounds of a `kernel_db.json` row, so its "resident workgroups per CU" is a
property of a candidate. This module audits the *emitted* code objects, so its
"waves per SIMD" is a property of a kernel that actually built and ran. The two
answer different questions and they must not be conflated: a cell can look
well-occupied in one unit and lonely in the other, and before this module existed
there was no way to see the difference or to check the gate's tables against
reality.

CPU only, read-only. Writes nothing into the repo.

    python3 -m oto.harness.asm_occupancy                       # whole corpus
    python3 -m oto.harness.asm_occupancy --dtype CC            # one family
    python3 -m oto.harness.asm_occupancy --top 20 --by gflops   # best first
    python3 -m oto.harness.asm_occupancy --binder              # resource tally
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parents[2]

# Device constants have one home. Read them off the profile at call time
# (attribute reads re-bind on rebind_profile()); nothing in this
# module may import-bind a scalar.
from oto.device import loader as _loader
from oto.runners.paths import runs_dir as _runs_dir

#: Wave size on gfx9. Fixed at 64; there is no wave32 mode on this target.
WAVE = 64

#: VGPR allocation granularity on gfx9 wave64, from LLVM's
#: ``getVGPRAllocGranule``. This is 4, NOT 8-or-16: the 8/16 rule is the older
#: model and it does not fit the hardware table (see ``_CALIBRATION`` below).
VGPR_GRANULE = 4

#: Register-file size of one SIMD = the CU file divided by the SIMD count.
#: With 65536 per CU and 4 SIMDs this is 16384, i.e. 64 KiB per SIMD.
def _simd_vgpr(profile=None) -> int:
    """CLI: measured occupancy audit of emitted kernels. ``profile`` selects the device; ambient by default."""
    return _loader.resolve_profile(profile,).vgpr_per_cu // _loader.resolve_profile(profile,).simds_per_cu


#: Max resident waves per SIMD. The hardware allows 10 (40/CU), which is what
#: rocminfo reports and what Tensile's own occupancy calculator assumes.
def _waves_per_simd_max(profile=None) -> int:
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    return _loader.resolve_profile(profile,).max_waves_per_cu // _loader.resolve_profile(profile,).simds_per_cu

#: The AMD/ORNL GFX9 VGPR-per-thread -> waves-per-SIMD table, the calibration this
#: model is built against. If `waves_per_simd` stops reproducing this column, the
#: granule or the file size in this module is wrong.
_CALIBRATION = {24: 10, 28: 9, 32: 8, 36: 7, 40: 6,
                48: 5, 64: 4, 84: 3, 128: 2, 256: 1}

#: Family typecode (Tensile's kernel-file suffix, e.g. ``Cijk_Ailk_Bjlk_HSS_BH_00``)
#: -> dtype char. The HPA families carry a two-part code and their inputs are
#: f16 either way (HHS = f16/f16/f32-acc; HSS = f16/f16/f32-out), so both take
#: the 2-byte H facts for the A/B tile. Their *store* width differs (HH_HPA
#: writes f16, HS writes f32) but that is a store-path fact, not an A/B-tile one.
DTYPE = {
    "SS": "S", "SB": "S", "DD": "D", "DB": "D", "HH": "H", "HB": "H",
    "HS": "S", "HSS_BH": "H", "HH_HPA": "H", "HHS_BH": "H",
    "CB": "C", "CC": "C", "ZB": "Z", "ZZ": "Z",
}

#: dtype char -> (bytes per element, flops per MAC). Mirrors Tensile's own
#: ``flopsPerMac`` (2 for real, 8 for complex) and ``numBytes`` (registers x 4).
_DTYPE_FACTS = {
    "S": (4, 2), "D": (8, 2), "H": (2, 2), "C": (8, 8), "Z": (16, 8),
}

#: LDS in bytes per CU, one home in the device profile.
def _lds_per_cu(profile=None) -> int:
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    return _loader.resolve_profile(profile,).lds_per_cu_kb * 1024

_KERNEL_MT = re.compile(r"_MT(\d+)x(\d+)x(\d+)_")
_TT_COMMENT = re.compile(r"/\*\s*ThreadTile=\s*(\d+)\s*x\s*(\d+)\s*\*/")
_SUBGROUP_COMMENT = re.compile(r"/\*\s*SubGroup=\s*(\d+)\s*x\s*(\d+)\s*\*/")
_VW_COMMENT = re.compile(r"/\*\s*VectorWidth\s*=\s*(\d+)\s*\*/")
_GLVW_A = re.compile(r"GlobalLoadVectorWidthA\s*=\s*(\d+)")
_GLVW_B = re.compile(r"GlobalLoadVectorWidthB\s*=\s*(\d+)")


def waves_per_simd(vgprs: int) -> int:
    """Resident waves per SIMD for a kernel's per-thread VGPR total.

    Args:
        vgprs: The kernel's ``amdhsa_next_free_vgpr`` value -- the *total*
            per-thread VGPR count including kernarg, operand and accumulator
            registers, not the accumulator demand a gate models.

    Returns:
        ``_simd_vgpr() // (WAVE * aligned)``, clamped to
        :data:`_waves_per_simd_max(). A total of 0 or less returns 0, which is
        "not a number", not "no occupancy".

    Why granule 4 and not 8 or 16: the 8/16 rule is the older model and it does
    not fit the hardware. AMD/ORNL's GFX9 table (see :data:`_CALIBRATION`) reads
    <=24 -> 10, 28 -> 9, 36 -> 7, 84 -> 3 waves; granule 4 reproduces all ten
    rows exactly, while granule 8 already mispredicts V=28 and V=84. Do not
    "fix" this to 8/16 without a measurement that contradicts the table.
    """
    if vgprs <= 0:
        return 0
    aligned = int(math.ceil(vgprs / VGPR_GRANULE) * VGPR_GRANULE)
    return min(_waves_per_simd_max(), _simd_vgpr() // (WAVE * aligned))


def binding_resource(vgprs: int, lds: int, threads: int, profile=None) -> tuple[str, int]:
    """Which resource caps this kernel, and the waves/CU it allows.

    Args:
        vgprs: Total per-thread VGPRs.
        lds: LDS bytes per workgroup (``group_segment_fixed_size``).
        threads: Workgroup size in threads.

    Returns:
        ``(binder, waves_per_cu)`` where binder is one of ``"VGPR"``, ``"LDS"``
        or ``"LDS+VGPR"`` when both cap identically, or ``"waveslots"`` when
        neither does. Ties are reported rather than broken by declaration order:
        15.9% of this corpus ties, and hiding that understates how often LDS is
        the binding constraint. LDS is unknown when it is 0 or the workgroup
        exceeds the 1024-thread maximum, in which case the LDS half is unmeasured
        and VGPR is reported.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    by_vgpr = waves_per_simd(vgprs) * _loader.resolve_profile(profile,).simds_per_cu
    if lds > 0 and threads > 0:
        by_lds = (_lds_per_cu() // lds) * (threads // WAVE)
    else:
        by_lds = _loader.resolve_profile(profile,).max_waves_per_cu
    by_waves = _loader.resolve_profile(profile,).max_waves_per_cu
    if by_vgpr == by_lds:
        return "LDS+VGPR", by_vgpr
    cands = {"VGPR": by_vgpr, "LDS": by_lds, "waveslots": by_waves}
    binder = min(cands, key=lambda k: cands[k])
    return binder, cands[binder]


def _family_of(path: Path) -> str | None:
    """Dtype char from the path's ``Cijk_..._HSS_BH_00`` directory, else None.

    The typecode is the whole non-numeric segment between the ``Bxxx_`` and the
    ``_NN`` index, so ``HSS_BH``/``HHS_BH`` survive intact -- splitting on the
    first underscore loses them.
    """
    for part in path.parts:
        m = re.match(r"Cijk_A[a-z]{3}_B[a-z]{3}_(.+?)_\d+$", part)
        if m:
            return DTYPE.get(m.group(1))
    return None


def parse_asm_kernel(path: Path) -> dict | None:
    """Read one Tensile-emitted assembly file's hardware directives.

    Args:
        path: A ``build_tmp/SOURCE/assembly/*.s`` file.

    Returns:
        A dict of ``vgpr``, ``sgpr``, ``lds``, ``scratch``, ``threads``, tile
        fields and the kernel name, or None when the file carries no
        ``amdhsa_next_free_vgpr`` directive (a stub, or not a Tensile kernel).
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    head = text.split(".end_amdhsa_kernel", 1)[0]
    out: dict = {}
    for key, directive in (("vgpr", "amdhsa_next_free_vgpr"),
                            ("sgpr", "amdhsa_next_free_sgpr"),
                            ("lds", "amdhsa_group_segment_fixed_size"),
                            ("scratch", "amdhsa_private_segment_fixed_size")):
        m = re.search(re.escape(directive) + r"\s+(\d+)", head)
        if m:
            out[key] = int(m.group(1))
    m = re.search(r"\.amdhsa_kernel\s+(\S+)", head)
    if m:
        out["kernel"] = m.group(1)
    for key, pat in (("tt", _TT_COMMENT), ("sg", _SUBGROUP_COMMENT)):
        m = re.search(pat, text)
        if m:
            out[key] = (int(m.group(1)), int(m.group(2)))
    for key, pat in (("vw", _VW_COMMENT), ("glvwa", _GLVW_A), ("glvwb", _GLVW_B)):
        m = re.search(pat, text)
        if m:
            out[key] = int(m.group(1))
    if "vgpr" not in out:
        return None
    return out


def read_phase_gflops(phase_dir: Path) -> dict[str, tuple[float, list[int]]]:
    """Best and per-problem GFLOP/s for every kernel in one phase.

    Tensile's ``2_BenchmarkData/*.csv`` header is **misaligned with its rows**:
    the header's field 0 is the literal string ``"GFlops"``, but the GFLOP/s
    value is the **last** field of a data row. The row is
    ``[problemIdx, I, J, K, L, LDD, LDC, LDA, LDB, WinnerFreq, TotalFlops,
    WinnerPower, WinnerTemperature, GFlops]``. Reading field 0 yields the
    problem index and a corpus-wide maximum under 10 GFLOP/s, which is the
    symptom of getting this wrong.

    Args:
        phase_dir: A phase directory containing ``2_BenchmarkData/``.

    Returns:
        ``{solution name: (best GFLOP/s, [I, J, K, L of the best])}``.
    """
    out: dict[str, tuple[float, list[int]]] = {}
    bd = phase_dir / "2_BenchmarkData"
    if not bd.is_dir():
        return out
    for csv_file in sorted(bd.glob("*.csv")):
        kernel = None
        try:
            handler = csv_file.open(newline="")
        except OSError:
            continue
        with handler as fh:
            for row in csv.reader(fh):
                if len(row) < 14:
                    continue
                if row[0].strip() == "GFlops":
                    kernel = row[-1].strip()
                    continue
                if kernel is None:
                    continue
                try:
                    gflops = float(row[13])
                    problem = [int(row[1]), int(row[2]),
                               int(row[3]), int(row[4])]
                except ValueError:
                    continue
                cur = out.get(kernel)
                if cur is None or gflops > cur[0]:
                    out[kernel] = (gflops, problem)
    return out


def iter_asm(runs_root: Path) -> Iterable[tuple[Path, dict]]:
    """Every emitted Tensile kernel under a runs root, with its phase dir."""
    for asm_dir in sorted(runs_root.rglob("SOURCE/assembly")):
        for asm in sorted(asm_dir.glob("*.s")):
            parsed = parse_asm_kernel(asm)
            if parsed is None:
                continue
            phase = asm_dir
            for part in asm_dir.parents:
                if part.name == "1_BenchmarkProblems":
                    phase = part.parent
                    break
            yield phase, {**parsed, "path": str(asm)}


def measure_corpus(runs_root: Path,
                   dtype: str | None = None) -> list[dict]:
    rows: list[dict] = []
    cache: dict[str, dict[str, tuple[float, list[int]]]] = {}
    for phase, k in iter_asm(runs_root):
        fam = _family_of(Path(k["path"]))
        if fam == dtype or (dtype is None):
            kern = k.get("kernel") or Path(k["path"]).stem
            mt = _KERNEL_MT.search(kern)
            threads = (k["sg"][0] * k["sg"][1]) if k.get("sg") else 0
            binder, waves_cu = binding_resource(k["vgpr"], k.get("lds", 0),
                                                threads)
            key = str(phase)
            if key not in cache:
                cache[key] = read_phase_gflops(phase)
            best = cache[key].get(kern)
            facts = _DTYPE_FACTS.get(fam)
            ai = None
            if mt and facts:
                bpe, flops_mac = facts
                # group(3) is the K-unroll; the arithmetic-intensity formula
                # below needs only M and N, so it is not parsed.
                m0, m1 = int(mt.group(1)), int(mt.group(2))
                ai = flops_mac * m0 * m1 / ((m0 + m1) * bpe)
            rows.append({
                "phase": phase.name,
                "dtype": fam,
                "kernel": kern,
                "mt0": int(mt.group(1)) if mt else None,
                "mt1": int(mt.group(2)) if mt else None,
                "depth_u": int(mt.group(3)) if mt else None,
                "tt": k.get("tt"),
                "threads": threads,
                "vw": k.get("vw"), "glvwa": k.get("glvwa"),
                "glvwb": k.get("glvwb"),
                "vgpr": k["vgpr"], "sgpr": k.get("sgpr"),
                "lds": k.get("lds", 0), "scratch": k.get("scratch", 0),
                "waves_per_simd": waves_per_simd(k["vgpr"]),
                "waves_per_cu": waves_cu,
                "binder": binder,
                "ai_flop_per_byte": ai,
                "gflops": best[0] if best else None,
                "problem": best[1] if best else None,
                "path": k["path"],
            })
    return rows


def _fmt(row: dict) -> str:
    size = "-"
    if row["mt0"] and row["depth_u"]:
        size = f"{row['mt0']}x{row['mt1']}x{row['depth_u']}"
    tt = "x".join(str(d) for d in row["tt"]) if row.get("tt") else "?"
    gf = f"{row['gflops']:9.1f}" if row["gflops"] is not None else "    no-gf"
    ai = f"{row['ai_flop_per_byte']:7.2f}" if row.get("ai_flop_per_byte") else "   n/a"
    return (f"{row['dtype'] or '?':3s} {size:13s} TT{tt:<6s} "
            f"v{row['vgpr']:<4d} L{row['lds']:>6d} t{row['threads']:>4d} "
            f"{row['waves_per_cu']:>3d}w/CU {ai} {gf}  {row['binder']}")


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Measured occupancy of Tensile's emitted kernels, joined "
                    "to their GFLOP/s. CPU only, reads nothing outside "
                    "<codename>_runs.")
    ap.add_argument("--base-dir", "--base", type=Path, default=None,
                    help="repo root override")
    ap.add_argument("--runs", default=None,
                    help="runs directory (default: <base-dir>/<codename>_runs)")
    ap.add_argument("--dtype", default=None, help="family typecode filter")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--by", choices=["gflops", "vgpr", "waves", "count"],
                    default="gflops")
    ap.add_argument("--binder", action="store_true",
                    help="print the resource tally and the waves distribution")
    ap.add_argument("--json", default=None, help="write all rows to this path")
    ap.add_argument("--check-calibration", action="store_true",
                    help="verify waves_per_simd against the AMD/ORNL GFX9 table")
    return ap


def _cmd_calibration() -> int:
    bad = [(v, waves_per_simd(v), want)
           for v, want in _CALIBRATION.items()
           if waves_per_simd(v) != want]
    if bad:
        print("CALIBRATION MISMATCH:", bad)
        return 1
    print("calibration OK: 10/10 rows of the AMD/ORNL GFX9 table reproduced")
    return 0


def _cmd_binder(rows: list[dict[str, Any]]) -> int:
    print("\n-- resource tally --")
    tally: dict[str, int] = {}
    for r in rows:
        tally[r["binder"]] = tally.get(r["binder"], 0) + 1
    for _k, _v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {_k:<10s} {_v:6d}  {100*_v/len(rows):5.1f}%")
    print("\n-- waves/CU distribution --")
    hist: dict[int, int] = {}
    for r in rows:
        hist[r["waves_per_cu"]] = hist.get(r["waves_per_cu"], 0) + 1
    for _w in sorted(hist):
        print(f"  {_w:>3d} waves/CU  {hist[_w]:6d}  {100*hist[_w]/len(rows):5.1f}%")
    spilled = sum(1 for r in rows if r["scratch"])
    if spilled:
        print(f"\n{spilled} kernels carry a private segment (spill)")
    return 0


def _cmd_count(rows: list[dict[str, Any]], top: int) -> int:
    groups: dict[tuple, int] = {}
    for r in rows:
        key = (r["dtype"], r["mt0"], r["mt1"], r["tt"], r["depth_u"])
        groups[key] = groups.get(key, 0) + 1
    ordered = sorted(groups.items(), key=lambda kv: -kv[1])[:top]
    print(f"{len(rows)} kernels, {len(groups)} distinct shapes")
    for key, _n in ordered:
        probe = next(r for r in rows
                     if (r["dtype"], r["mt0"], r["mt1"], r["tt"],
                         r["depth_u"]) == key)
        print(f"{_n:5d}  {_fmt(probe)}")
    return 0


def _cmd_sorted(rows: list[dict[str, Any]], args: Any) -> int:
    if args.by == "vgpr":
        ordered = sorted(rows, key=lambda r: -r["vgpr"])[:args.top]
    elif args.by == "waves":
        ordered = sorted(rows, key=lambda r: r["waves_per_cu"])[:args.top]
    else:
        measured = [r for r in rows if r["gflops"] is not None]
        ordered = sorted(measured, key=lambda r: -r["gflops"])[:args.top]
    print(f"{len(rows)} kernels; "
          f"{sum(1 for r in rows if r['gflops'] is not None)} with GFLOP/s")
    for _r in ordered:
        print(_fmt(_r))
    return 0


def main(profile=None) -> int:
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    args = _build_arg_parser().parse_args()

    if args.check_calibration:
        return _cmd_calibration()

    base = Path(args.base_dir) if args.base_dir else _HERE
    root = Path(args.runs) if args.runs else (_runs_dir(base, _loader.resolve_profile(profile,).codename))
    rows = measure_corpus(root, args.dtype)
    if not rows:
        print(f"no emitted kernels with an amdhsa directive under {root}")
        return 1

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, default=str))
        print(f"wrote {len(rows)} rows to {args.json}")

    if args.binder:
        return _cmd_binder(rows)
    if args.by == "count":
        return _cmd_count(rows, args.top)
    return _cmd_sorted(rows, args)


if __name__ == "__main__":
    raise SystemExit(main())
