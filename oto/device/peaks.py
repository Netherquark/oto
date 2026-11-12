#!/usr/bin/env python3
"""Hardware peaks and the canonical cell/family vocabulary.

Owns: the peak GFLOPS table, the per-family shape grid, the family <-> Tensile
DataType-char mapping, the realistic ceilings, the hardware limits, and the
canonical cell/kernel identity helpers. The only package in oto that may hold a
numeric hardware constant; this is the authoritative PEAK_GFLOPS reference, so no
other consumer may re-derive a peak.

Does NOT own: the gates that use those limits (oto.tensile.gates), any measurement
or statistics (oto.metrics), or the refactor-2 device-profile seam.

Public API: PEAK_GFLOPS, FAMILY_SHAPES, FAMILY_DTYPE_CHAR, FAMILY_DTYPES,
REPORTED_TO_BLAS8, blas8_gflops, REALISTIC_CEILINGS, REALISTIC_CEILINGS_BLAS8,
THEORETICAL_PEAKS, THEORETICAL_PEAKS_BLAS8, kernel_typecode,
family_from_kernel_name, dtype_from_kernel_name, cube_side, cell_key,
shipped_cells, shipped_cell_set, kernel_key.
"""

from __future__ import annotations

import re
from typing import Dict, Set, Tuple

# Refactor 2: source device facts from the default profile so the profile is the
# single source of truth. Falls back to the the device literals if the profile
# cannot be loaded (e.g. during bootstrap).
try:
    from oto.device.loader import default_profile as _peaks_dp
    _P = _peaks_dp()
    PEAK_GFLOPS = dict(_P.peak_gflops)
    FAMILY_SHAPES = {k: list(v) for k, v in _P.family_shapes.items()}
    FAMILY_CELLS = {k: list(v) for k, v in _P.family_cells.items()}
    FAMILY_DTYPE_CHAR = dict(_P.family_dtype_char)
    FAMILY_DTYPES = dict(_P.family_dtypes)
    REALISTIC_CEILINGS = dict(_P.realistic_ceilings)
    REALISTIC_CEILINGS_BLAS8 = dict(_P.realistic_ceilings_blas8)
    REPORTED_TO_BLAS8 = dict(_P.reported_to_blas8)
    THEORETICAL_PEAKS = dict(_P.theoretical_peaks)
    THEORETICAL_PEAKS_BLAS8 = dict(_P.theoretical_peaks_blas8)
    FAMILY_BYTES_PER_ELEMENT = dict(_P.family_bytes_per_element)
    NUM_CUS = _P.num_cus
    NUM_SIMDS_PER_CU = _P.simds_per_cu
    LANES_PER_SIMD = _P.lanes_per_simd
    MAX_WAVES_PER_CU = _P.max_waves_per_cu
    MAX_CLOCK_MHZ = _P.max_clock_mhz
    LDS_PER_CU_KB = _P.lds_per_cu_kb
    L2_SIZE_KB = _P.l2_size_kb
    VGPR_PER_CU = _P.vgpr_per_cu
    GLOBAL_LOAD_BYTE_CAP = _P.global_load_byte_cap
except Exception:  # pragma: no cover
    PEAK_GFLOPS = {  # fallback (gfx90c)
        "FP32": 1613, "FP16": 3226, "BF16": 1613, "INT8": 1613, "FP64": 101,
    }
    FAMILY_SHAPES = {}
    FAMILY_CELLS = {}
    FAMILY_DTYPE_CHAR = {}
    FAMILY_DTYPES = {}
    REALISTIC_CEILINGS = {}
    REALISTIC_CEILINGS_BLAS8 = {}
    REPORTED_TO_BLAS8 = {}
    THEORETICAL_PEAKS = {}
    THEORETICAL_PEAKS_BLAS8 = {}
    FAMILY_BYTES_PER_ELEMENT = {}
    NUM_CUS = 7
    NUM_SIMDS_PER_CU = 4
    LANES_PER_SIMD = 16
    MAX_WAVES_PER_CU = 40
    MAX_CLOCK_MHZ = 1800
    LDS_PER_CU_KB = 64
    L2_SIZE_KB = 1024
    VGPR_PER_CU = 65536
    GLOBAL_LOAD_BYTE_CAP = 16

# Single-source PEAK_GFLOPS table @1800 MHz (now sourced from profile above;

def blas8_gflops(family: str, reported: float) -> float:
    """A client-reported GFLOPS figure in BLAS-8 units (complex x4).

    Args:
        family: Canonical family key ("CC", "ZZ", "SS", ...).
        reported: The GFLOPS number the Tensile client printed.

    Returns:
        The same throughput in BLAS-8 GFLOPS, which is the unit the hardware
        roof (:data:`PEAK_GFLOPS`) is stated in.
    """
    return reported * REPORTED_TO_BLAS8.get(family.upper(), 1.0)



# Cell-key labelling — canonical workload-cell identity for the
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


# ---------------------------------------------------------------------------
# Kernel-name typecode -> family. Tensile kernel columns / shipped gfx900
# names carry the data-type token immediately before "_MT":
#
#   Cijk_Ailk_Bjlk_SB_MT32x64x16_SN_K1        -> SB      -> SS
#   Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1    -> HHS_BH  -> HH   (fp16 family!)
#   Cijk_Ailk_Bljk_ZB_GB_MT32x32x16_SN_...    -> ZB_GB   -> ZZ
#   Cijk_Ailk_Bjlk_DB_... / CB_... / HB_...   -> DB/CB/HB
#
# The FIRST operand letter is the family class. SB/DB/HB/CB/ZB are the corpus's
# canonical single-typed kernels; HHS/HSS (fp16-in, fp16/fp32 mixed) belong to
# the HH family and MUST never be tallied into the SS cells (the §13.2
# typecode-filter rule). This is the single resolver every cell-attribution
# consumer (analytics, harness/kernel_db, port_tensile) uses, so a family is
# decided exactly once, by the kernel's own name, not by phase_id text.
# ---------------------------------------------------------------------------

# Tokens that precede "_MT" but are NOT the dtype typecode (Tensile layout /
# schedule markers such as HHS_BH's "BH", ZB_GB's "GB", "SN"/"SE" stream).
_KERNEL_LAYOUT_TOKENS = frozenset({
    "SN", "SE", "NN", "NT", "TN", "TT", "TC", "NC",
    "BH", "HN", "HT", "GB", "NB",
})

_TYPECODE_TO_FAMILY = {"S": "SS", "D": "DD", "H": "HH", "C": "CC", "Z": "ZZ"}


def kernel_typecode(kernel_name: object) -> str:
    """Raw dtype token of a Tensile kernel name ('' when unparseable).

    Reads the last non-layout token before ``_MT``, so ``HHS_BH`` and ``ZB_GB``
    resolve to ``HHS`` / ``ZB`` rather than the layout marker. Uppercased; the
    token must open with a dtype letter (S/D/H/C/Z) or it is rejected (the
    token before ``_MT`` is only meaningful on a real Tensile kernel name).
    """
    name = str(kernel_name or "").split("_MT")[0]
    if not name:
        return ""
    for tok in reversed(name.split("_")):
        if not tok:
            continue
        u = tok.upper()
        if u in _KERNEL_LAYOUT_TOKENS:
            continue
        if u[:1] in _TYPECODE_TO_FAMILY:
            return u
        return ""
    return ""


def family_from_kernel_name(kernel_name: object) -> str:
    """Canonical family of a kernel by its typecode ('' when unparseable)."""
    code = kernel_typecode(kernel_name)
    if not code:
        return ""
    return _TYPECODE_TO_FAMILY.get(code[0], "")


def dtype_from_kernel_name(kernel_name: object) -> str:
    """Canonical DataType char of a kernel by its typecode ('' when unknown)."""
    return FAMILY_DTYPE_CHAR.get(family_from_kernel_name(kernel_name), "")


def cube_side(shape: object) -> "int | None":
    """Side length N of an 'NxNxN' cube shape string; None for non-cubes.

    Non-cube workloads (GEMV-probe shapes such as 32x4096x1) have no A/B cell
    and are excluded at the pairing boundary, not in production kernels.
    """
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


def shipped_cells() -> Dict[str, Dict[str, str]]:
    """The canonical the device "shape x dtype" coverage grid (the coverage-parity rule).

    This is the *single* definition of what the produced gfx90c TensileLibrary
    may address: the exact cell set the shipped gfx900 library addresses today.

    Cell = (family, cube shape); family implies the Tensile DataType char via
    :data:`FAMILY_DTYPE_CHAR` (the shipped per-family `.dat` are keyed the same
    way). Returns ``{"SS:256": {"family": "SS", "shape": "256x256x256",
    "side": "256", "dtype": "S"}, ...}``. The rule itself (both clauses) is
    stated once in `knowledge_base.md` §6.1 and enforced by
    `check_library_parity.py` + `library_parity.parity_report`.
    """
    return {
        f"{fam}:{side}": {
            "family": fam,
            "shape": f"{side}x{side}x{side}",
            "side": str(side),
            "dtype": FAMILY_DTYPE_CHAR[fam],
        }
        for fam in FAMILY_SHAPES
        for side in FAMILY_SHAPES[fam]
    }


def shipped_cell_set() -> "Set[Tuple[str, str]]":
    """The coverage-parity grid as a set of ``(family, "NxNxN")`` tuples."""
    return {(v["family"], v["shape"]) for v in shipped_cells().values()}


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
