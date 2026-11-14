"""Deterministic ALU-peak derivation for any ``DeviceProfile``.

Owns: the arithmetic that turns frozen hardware facts (``num_cus``,
``simds_per_cu``, ``lanes_per_simd``, ``max_clock_mhz``) into per-family
BLAS-8 peak GFLOPS. The same formula the gfx90c limits doc records by hand
is evaluated here on every call -- nothing is transcribed, no ceiling is
remembered.
Does NOT own: the realistic-ceilings catalogue (measured, and profile-owned),
the lane-class JSON tables (``profiles/<codename>.json``), or any legality
rule (``oto.tensile.gates``).

Formulas (GCN5 family, Vega subclass — the architecture class of both
reference devices for this project; other archs may need a wider table):

* FP32 pipe: ``2 * lanes * fGHz`` FMA(2)/clock, where
  ``lanes = num_cus * simds_per_cu * lanes_per_simd``.
* FP32-lane complex (C/Ailk-Bljk = fp32-ia): identical to FP32 (a complex
  MAC costs 4 real FMAs in the client but 8 BLAS-8 FLOPS -- same throughput,
  so the roof is the FP32 roof).
* FP64: FP32 / 16 (GCN5 rate, 1 desired:16).
* FP64-lane complex (Z/64-bit-complex): FP64 roof.
* FP16 (fast F16, v_pk_fma_f16): FP32 * 2.
* BF16 (no dot, no packed-in GCN5): FP32.
* INT8 (no dot, no dp4a): FP32 upper bound.

Rounding is ``floor(x + 0.5)`` — deterministic, no banker's rounding.

Public API: lanes, derive_lane_classes, derive_peak_gflops,
derive_theoretical_peaks_blas8.
"""

from __future__ import annotations

from oto.device.profile import DeviceProfile

#: Lane classes keyed to the family. HPA runs at the FP32 rate (the pipe
#: computes v_fma_f32 on 16-bit data); see gfx90c_theoretical_limits.md §2.2.
FAMILY_LANE = {
    "SS": "FP32",
    "DD": "FP64",
    "CC": "FP32",
    "ZZ": "FP64",
    "HH": "FP16",
    "HH_HPA": "FP32",
    "HS_HPA": "FP32",
    "BF16": "BF16",
    "INT8": "INT8",
}


def lanes(profile: DeviceProfile) -> int:
    """Total FP lanes across the GPU (CUs * SIMDs/CU * lanes/SIMD)."""
    return profile.num_cus * profile.simds_per_cu * profile.lanes_per_simd


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def derive_lane_classes(profile: DeviceProfile) -> dict[str, int]:
    """Per lane-class theoretical peaks (BLAS-8 convention) on ``profile``."""
    ln = lanes(profile)
    f = profile.max_clock_mhz / 1000.0
    fp32 = 2 * ln * f
    out = {
        "FP32": _round_half_up(fp32),
        "FP64": _round_half_up(fp32 / 16),
        "FP16": _round_half_up(2 * fp32),
        "BF16": _round_half_up(fp32),
        "INT8": _round_half_up(fp32),
    }
    if not profile.has_packed_bf16:
        out["BF16"] = out["FP32"]
    return out


def derive_peak_gflops(profile: DeviceProfile) -> dict[str, int]:
    """Lane-class peaks mapped onto the profile's `peak_gflops` keys."""
    return derive_lane_classes(profile)


def derive_theoretical_peaks_blas8(profile: DeviceProfile) -> dict[str, int]:
    """Per-family BLAS-8 theoretical peaks (the acceptance authority)."""
    classes = derive_lane_classes(profile)
    out = {}
    for fam, lane in FAMILY_LANE.items():
        out[fam] = classes[lane]
    return out


def _main() -> None:
    import argparse
    import json

    from oto.device import loader as _loader

    ap = argparse.ArgumentParser(description="Print the profile's derived limits.")
    ap.add_argument("--codename", default=None)
    args = ap.parse_args()
    p = (_loader.load_profile(args.codename) if args.codename
         else _loader.current_profile())
    blas8 = derive_theoretical_peaks_blas8(p)
    print(f"codename={p.codename} lanes={lanes(p)} ("
          f"num_cus={p.num_cus} simds_per_cu={p.simds_per_cu} "
          f"lanes_per_simd={p.lanes_per_simd}) f={p.max_clock_mhz/1000.0} GHz")
    print(json.dumps(blas8, indent=2, sort_keys=True))


if __name__ == "__main__":
    _main()
