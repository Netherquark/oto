"""The measured VGPR model: tables and budgets the occupancy gate cites.

Owns: the numbers the register-file gate needs and cannot derive -- the global
load byte cap, the family bytes-per-element table, the per-dtype VGPR weights,
the accumulator VGPR budget, the LDS budget, and the two measured VGPR tables
read out of Tensile's own kernel writer. Also the config readers those numbers
need (``depth_u``, ``lds_base_bytes``, ``measured_accvgpr``).
Does NOT own: the pass/fail decision (oto.tensile.gates.occupancy) or the
legality classes (oto.tensile.gates.assembly).
Public API: GLOBAL_LOAD_BYTE_CAP, FAMILY_BYTES_PER_ELEMENT, VGPR_PER_CU,
MAX_VGPR_PER_THREAD, VGPR_PER_ELEMENT, ACCVGPR_BUDGET, LDS_BUDGET,
BYTES_PER_ELEMENT, VGPR_BUDGET, MEASURED_VGPR, MEASURED_VGPR_BY_DTYPE,
measured_accvgpr, depth_u, lds_base_bytes.
"""

from __future__ import annotations

from typing import Dict, Optional

#: Bytes in the widest global load the classic (non-MFMA) path allows. Tensile
#: enforces this at SolutionStructs:3460 (`GLVW * bytesPerElement <= 16`), and
#: `validate_tensile_loads` rejects anything above it.
GLOBAL_LOAD_BYTE_CAP = 16

#: Bytes per element per family, matching the dtype table in
#: `validate_tensile_loads`. Cross-checked against ``Tensile.DataType.properties``
#: (``numBytes() == reg * 4``) by tests.test_measurement_integrity -- do not
#: hand-edit without updating that test. ZZ is complex *double*: 16 bytes, not
#: 8. The old 8 let VectorWidth 2 through the cap and Tensile rejected those
#: configs at assembly time.
FAMILY_BYTES_PER_ELEMENT = {
    "SS": 4, "DD": 8, "HH": 2, "HS": 4, "CC": 8, "ZZ": 16,
    "HH_HPA": 2, "HS_HPA": 4,
}

# Register file is 64K VGPRs per CU, but a single thread is architecturally
# capped at 256 VGPRs. Tensile enforces that cap when generating assembly and
# raises instead of emitting a kernel
# (KernelWriterAssembly: "total vgpr: N not in [0, 256]").
VGPR_PER_CU = 65536
MAX_VGPR_PER_THREAD = 256
#: Effective VGPRs consumed per thread-tile element, per dtype char.
VGPR_PER_ELEMENT = {"S": 1, "D": 2, "H": 1, "B": 1, "I8": 1, "C": 4, "Z": 8}
#: Accumulator VGPRs budgeted per thread, chosen from measurement (see
#: `measured_accvgpr`): 128 keeps the observed worst case (199 VGPRs for
#: TT 4x4 complex) under the 256 cap, while the first failing step
#: (TT 8x4 complex, 256 accVGPRs -> 271 VGPRs) is excluded.
ACCVGPR_BUDGET = 128
#: LDS budget per workgroup, expressed in the *unpadded* base tile footprint
#: (MacroTile0 + MacroTile1) * DepthU * bytesPerElement. Tensile's real check
#: (SolutionStructs:4334, "Kernel Uses %u > %u bytes of LDS") runs against an
#: allocator result inflated by prefetch double-buffering, power-of-two offset
#: alignment and LdsPad, so the base is not the number Tensile compares -- but it
#: is a sound *upper-bound* proxy in the only direction that matters here.
#: Measured complex (Z, 8 B) boundary on gfx90c: 16384 legal, 20480 dead
#: (128x32x16 needs 106496 B and is rejected). Deliberately conservative: it may
#: refuse a config Tensile would accept, never admits one Tensile refuses.
LDS_BUDGET = 16384
#: Bytes per element for the LDS footprint, by dtype char. Note this is NOT
#: VGPR_PER_ELEMENT: a f64 element is 8 bytes but only 2 VGPRs, while a complex
#: f64 element is 8 VGPRs and 8 bytes.
BYTES_PER_ELEMENT = {"S": 4, "D": 8, "H": 2, "B": 1, "I8": 1, "C": 8, "Z": 8}
#: Retained for the workgroup estimate: budget is expressed in accumulators, and
#: the register file is shared by every thread in a workgroup.
VGPR_BUDGET = VGPR_PER_CU // 2

#: Measured per-thread VGPR totals from Tensile's own kernel writer on gfx90c,
#: reported by check_tensile_build.py. (threadtile, accvgpr, observed total).
#: Every entry satisfies: total = accvgpr + a small tile-dependent overhead, and
#: the pass/fail boundary is exactly accvgpr > 128 for complex.
MEASURED_VGPR = {
    (2, 2): 63, (4, 2): 95, (2, 4): 99, (4, 4): 154,
    (2, 8): 171, (8, 4): 271, (8, 8): 519,
}

#: Measured TOTAL per-thread VGPRs (kernarg + operand + accumulator), read
#: 2026-10-09 from the run corpus' emitted code objects with
#: `python3 -m oto.harness.measure_vgprs` (llvm-readelf on the Tensile assembly
#: .o metadata, CPU-only). Prefer the dtype-keyed table over MEASURED_VGPR
#: (which is the weight-8 complex table used when no dtype is in hand).
MEASURED_VGPR_BY_DTYPE = {
    "S": {(2, 2): 26, (2, 4): 43, (4, 2): 43, (4, 4): 47, (4, 6): 65,
          (4, 8): 77, (6, 4): 65, (6, 6): 83, (8, 4): 79, (8, 8): 119,
          (8, 16): 199, (16, 8): 199},
    "D": {(2, 2): 39, (2, 4): 53, (4, 2): 53, (4, 4): 79, (4, 8): 131,
          (8, 4): 131, (8, 8): 215},
    "H": {(2, 2): 21, (4, 4): 35, (4, 8): 57, (6, 6): 48, (8, 4): 57,
          (8, 8): 65, (8, 16): 105, (16, 8): 105},
    "C": {(2, 2): 39, (2, 4): 59, (4, 2): 59, (4, 4): 79, (4, 8): 134,
          (8, 4): 134},
    "Z": {(2, 2): 71, (2, 4): 99, (4, 2): 99, (2, 8): 171, (4, 4): 167},
}


def measured_accvgpr(tt0: int, tt1: int, weight: int) -> int:
    """Accumulator VGPRs per thread for a thread tile and dtype weight.

    Args:
        tt0, tt1: ThreadTile dimensions.
        weight: Effective VGPRs per element for the dtype
            (:data:`VGPR_PER_ELEMENT`).

    Returns:
        ``tt0 * tt1 * weight``.
    """
    return tt0 * tt1 * weight


def depth_u(config: Dict) -> int:
    """DepthU (K-dimension tile depth), 0 when it cannot be determined.

    Why: Depth lives in two different places depending on who wrote the config:
    generator-produced phases carry it as the third MacroTile field
    ("128x32x16" -> 16) and omit the DepthU key entirely, while explicit configs
    and tests set DepthU directly. Both must resolve, or the LDS gate silently
    computes a footprint 16x too small and waves through 128x32x16
    (the two readers are the two places a config can legitimately hide DepthU).

    Args:
        config: A Tensile solution dict.

    Returns:
        The resolved depth, or 0 when neither location holds a positive integer.
    """
    for key in ("DepthU", "depth_u"):
        raw = config.get(key)
        try:
            ku = int(raw)
        except (TypeError, ValueError):
            continue
        if ku > 0:
            return ku
    raw_mt = config.get("MacroTile", config.get("macro_tile"))
    if raw_mt:
        parts = str(raw_mt).split("x")
        if len(parts) >= 3:
            try:
                ku = int(parts[2])
            except ValueError:
                return 0
            return ku if ku > 0 else 0
    return 0


def lds_base_bytes(mt0: int, mt1: int, ch: str) -> int:
    """Unpadded LDS footprint of one workgroup's A and B tiles.

    Args:
        mt0, mt1: MacroTile dimensions.
        ch: Dtype char (see :data:`BYTES_PER_ELEMENT`).

    Returns:
        ``(mt0 + mt1) * bytesPerElement``, or 0 for an unknown dtype char so the
        caller sees "cannot model" rather than a falsely small footprint.
    """
    bpe = BYTES_PER_ELEMENT.get(ch)
    if bpe is None:
        return 0
    return (mt0 + mt1) * bpe
