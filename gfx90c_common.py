#!/usr/bin/env python3
"""
gfx90c_common.py — Shared constants for gfx90c Tensile port

Single source of truth for all peak GFLOPS figures in the ecosystem.
This file is the authoritative PEAK_GFLOPS reference; all other
consumers import from here.

Device: AMD Ryzen 5 PRO 5650U (Cezanne-U PRO, Zen 3) iGPU = gfx90c
ISA: (9,0,12) — GFX9/GCN5 "Vega 7"
Max clock: 1800 MHz (DVFS pins at level-2 under load)
"""

# Single-source PEAK_GFLOPS table @1800 MHz
# Values are absolute; callers scale by actual sclk if needed
PEAK_GFLOPS = {
    # FP32: 7 CU × 4 SIMD × 16 lanes × 1.8 GHz = 806.4 ops/SIMD × 2 (FMA) = 1612.8
    "FP32": 1613,
    # FP16: dual-issue v_pk_fma_f16 = 2× FP32 = 3225.6
    "FP16": 3226,
    # BF16: no v_pk_fma_bf16 on any gfx9 → single-rate FP32 = 1612.8
    "BF16": 1613,
    # INT8: no dp4a on gfx90c → FP32-pipe bound = 1612.8 (UPPER bound only)
    "INT8": 1613,
    # FP64: VALU 1/16 of FP32 = 1612.8 / 16 = 100.8
    "FP64": 101,
}

# Family shapes for the gfx900 spoof reference + red-cell contract.
# Canonical family deck cubes (side lengths) benchmarked as "cells" per family.
FAMILY_SHAPES = {
    "SS": [256, 512, 768, 1000, 1024, 1365, 2048, 4096],
    "DD": [192, 256, 512, 768, 1024, 1365, 2048],
    "HH": [256, 512, 1024, 2048, 4096],
    "CC": [192, 256, 512, 1024, 2048],
    "ZZ": [128, 192, 256, 512, 1024],
    "HH_HPA": [512, 1024, 2048, 4096],
    "HS_HPA": [512, 1024, 2048, 4096],
}

# Complex families run at the REAL rate of their lane class
# (complex MAC = 4 real FMAs in Tensile expansion)
# DataType C = complexSingle (FP32 pipe), DataType Z = complexDouble (FP64 pipe)

# Family -> Tensile DataType char ('S'/'D'/'H'/'C'/'Z'), single source for
# scheduler, tensile_library, analytics and report. Char table (how Tensile
# sees the kernel) is distinct from FAMILY_DTYPES (which pipe precision the
# family runs at). Both are family-keyed and canonical here.
FAMILY_DTYPE_CHAR = {
    "SS": "S",
    "DD": "D",
    "HH": "H",
    "CC": "C",
    "ZZ": "Z",
    "HH_HPA": "H",
    "HS_HPA": "H",
}

# Family -> pipe precision for realistic-ceiling lookup (distinct from the
# Tensile DataType char; e.g. HH_HPA stores FP16 inputs but runs the FP32 pipe).
FAMILY_DTYPES = {
    "SS": "FP32",
    "DD": "FP64",
    "CC": "FP32",  # complex single → FP32 pipe
    "ZZ": "FP64",  # complex double → FP64 pipe
    "HH": "FP16",
    "HH_HPA": "FP32",  # FP16 in/out, FP32 acc → FP32 pipe
    "HS_HPA": "FP32",  # FP16 in, FP32 out/acc → FP32 pipe
}

# Realistic acceptance ceilings, family-keyed (gfx90c_theoretical_limits.md §5,
# which quotes these exact values). Measured-empirical on this box (precise
# measured bests: FP32 1118.7, FP64 98.6, HH 2461.0, BF16 1109, INT8 881);
# ZZ ≈ DD, CC/HPAs ≈ SS (derived-analytical). BF16/INT8 have no families of
# their own — listed so the code table is complete vs the doc.
REALISTIC_CEILINGS = {
    "SS": 1118.7,
    "DD": 98.6,
    "HH": 2461.0,
    "ZZ": 98.6,    # complex double (DataType Z) → FP64 rate
    "CC": 1118.7,  # complex single (DataType C) → FP32 rate
    "HH_HPA": 1118.7,
    "HS_HPA": 1118.7,
    "BF16": 1109,
    "INT8": 881,
}

# Theoretical ALU peaks per family (BLAS flop count @1800 MHz)
# From gfx90c_theoretical_limits.md §2
THEORETICAL_PEAKS = {
    "SS": 1613,
    "DD": 101,
    "CC": 1613,   # complex single (C) → FP32 pipe
    "ZZ": 101,    # complex double (Z) → FP64 pipe
    "HH": 3226,   # packed FP16 = 2× FP32
    "HH_HPA": 1613,  # FP16 in/out, FP32 acc → FP32 pipe
    "HS_HPA": 1613,  # FP16 in, FP32 out/acc → FP32 pipe
    "BF16": 1613,  # no v_pk_fma_bf16 → FP32 rate
    "INT8": 1613,  # no dp4a on gfx90c → FP32 pipe (upper bound)
}

# Hardware constants
NUM_CUS = 7
NUM_SIMDS_PER_CU = 4
LANES_PER_SIMD = 16
MAX_WAVES_PER_CU = 40
MAX_CLOCK_MHZ = 1800
LDS_PER_CU_KB = 64
L2_SIZE_KB = 1024


# ---------------------------------------------------------------------------
# Cell-key labelling (fix.md) — canonical workload-cell identity for the
# spoof-baseline <-> native-candidate mapping in the acceptance A/B flow.
#
# A workload cell is (family, cube shape side). cell_key("HH", "1024x1024x1024")
# -> "HH:1024" is the mapping key between the two arms. kernel_key is a
# drill-down citation only (never the pairing key). Identity is stamped at emit
# time from the authoritative config (family/shape), NOT re-derived from
# phase_id text, so HH_HPA/HS_HPA never collapse into HH.
# ---------------------------------------------------------------------------

# DataType char -> canonical family (first-wins; 'H' resolves to HH — the HPA
# variants are only disambiguated by an explicit family / phase_id, never by
# dtype char alone).
DTYPE_TO_FAMILY = {}
for _fam, _ch in FAMILY_DTYPE_CHAR.items():
    DTYPE_TO_FAMILY.setdefault(_ch, _fam)


def cube_side(shape: object) -> "int | None":
    """Side length N of an 'NxNxN' cube shape string; None for non-cubes.

    Non-cube workloads (GEMV-probe shapes such as 32x4096x1) have no A/B cell
    and are excluded at the pairing boundary, not in production kernels.
    """
    import re
    m = re.match(r"\s*(\d+)x(\d+)x(\d+)", str(shape))
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return a if a == b == c else None


def cell_key(family: object, shape: object) -> "str | None":
    """Canonical workload-cell key 'FAMILY:SIDE'; None if family unknown or
    shape is not a cube."""
    side = cube_side(shape)
    if not side:
        return None
    fam = str(family or "").upper()
    if not fam or fam == "NONE":
        return None
    return f"{fam}:{side}"


def kernel_key(cfg: object) -> str:
    """Canonical kernel-identity key (config knobs) for drill-down citation.

    Citation only — the cell is keyed by cell_key. Unstable/missing configs
    yield '' (matched by the shape+family pairing regardless).
    """
    if not isinstance(cfg, dict):
        return ""
    parts = []
    for k in ("contraction_pattern", "ContractionPattern", "DataType"):
        if cfg.get(k):
            parts.append(f"{k}={cfg[k]}")
    for k in ("MacroTile", "MT0", "MT1", "ThreadTile", "TT0", "TT1",
              "VectorWidth", "DepthU", "GlobalSplitU", "WorkGroupMapping"):
        if cfg.get(k) is not None:
            parts.append(f"{k}={cfg[k]}")
    return "|".join(parts)
