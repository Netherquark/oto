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

# Complex families run at the REAL rate of their lane class
# (complex MAC = 4 real FMAs in Tensile expansion)
# DataType C = complexSingle (FP32 pipe), DataType Z = complexDouble (FP64 pipe)
COMPLEX_PEAKS = {
    "CC": 1613,  # complex single (DataType C) → FP32 rate
    "ZZ": 101,   # complex double (DataType Z) → FP64 rate
}

# Family-to-dtype mapping for ceiling lookup
FAMILY_DTYPES = {
    "SS": "FP32",
    "DD": "FP64",
    "CC": "FP32",  # complex single → FP32 pipe
    "ZZ": "FP64",  # complex double → FP64 pipe
    "HH": "FP16",
    "HH_HPA": "FP32",  # FP16 in/out, FP32 acc → FP32 pipe
    "HS_HPA": "FP32",  # FP16 in, FP32 out/acc → FP32 pipe
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

# Bound classes for ruler/throttle system
BOUND_CLASSES = ["ALU", "DDR"]

# Hardware constants
NUM_CUS = 7
NUM_SIMDS_PER_CU = 4
LANES_PER_SIMD = 16
MAX_WAVES_PER_CU = 40
MAX_CLOCK_MHZ = 1800
LDS_PER_CU_KB = 64
L2_SIZE_KB = 1024

# DDR roofline (measured-achievable on this box)
DDR_ROOFLINE_GBPS = 42  # ~82% of DDR4-3200 dual-channel theoretical 51.2 GB/s
