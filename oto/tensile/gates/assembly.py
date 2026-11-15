"""The assembly-class gate: is this GEMM class legal on this device at all?

Owns: ``assembly_class_valid``, the single source of truth for both seams (the
candidate generator's ``validate_config`` and the launch boundary's config
writer). Any cell that falls in an illegal class is caught pre-run, never
launched.
Does NOT own: the register-file/LDS model (`oto.tensile.gates.occupancy`), the
classic-path load divisibility (`oto.tensile.gates.loads`), or the candidate
sampler (`oto.tensile.candidate`).

Faithful to the Tensile SolutionStructs Assembly rejects reproduced from the 24
draft-run failures (this device = Assembly-only, FFMA, no MatrixInstruction/MFMA
escape; Tensile v4.44.0):

  SolutionStructs:3553  "GlobalSplitU only compatible with single, or asm and
                          (half or mixed) precision, or EnableMatrixInstruction"
  SolutionStructs:3616  "Assembly GSU half requires AssertFree0ElementMultiple>=2"
  SolutionStructs:3342  "StaggerUStride < DepthU * BytesPerElement"

Complex-MAC accounting (moved here from docs/research/complex_gemm_brief.md):
Tensile's complex MAC is exactly four real FMAs, so a complex GEMM is not
ALU-walled at a quarter of the real pipe:
  * MAC_F32C emits four `_v_mac_f32` per complex MAC; MAC_F64C emits four
    `v_fma_f64`; the MFMA path is the same count (`numMfmaPerIter *= 4`).
  * BLAS charges 8*M*N*K for CGEMM/ZGEMM vs 2*M*N*K for real GEMM -- a 4x
    cost, i.e. 2 flops per FMA, the real-GEMM ratio. An ALU-bound complex GEMM
    therefore has the same BLAS-8 ceiling as its real counterpart: on this device
    CGEMM <= 1613 and ZGEMM <= 101 GFLOPS. The "divide by 4" applies to
    complex-MAC throughput (~202 / ~12.6 G MAC/s), never to BLAS-8 GFLOPS.
  * Split schemes: 4M = 4 mul + 2 add, collapsing to 4 instructions with FMA
    and free negate (what Tensile emits); 3M (Gauss/Karatsuba) = 3 mul + 5 add,
    about 7-8 scalar ops per MAC but only 3 real GEMMs per GEMM with an
    O(MK+KN+MN) combine; 2M (Caday) = 2 real GEMMs.
Instruction-level escape hatches are closed on this device (no `v_mfma`, no
`v_dot*`/dp4a, no `v_pk_fma_bf16`); the levers are occupancy/register tiling
and the 3M decomposition.

GlobalSplitU reachability (this port): only the SingleBuffer-atomic path is
reachable (the config writer never forwards `GlobalSplitUAlgorithm` or a
reduction workspace), so complex/HPA GSU>1 has no MFMA escape and half
Assembly GSU>1 stays illegal while the deck ships AF0EM=1. SS is the only
GSU-legal family (ladder {1,2,4}).

Non-temporal loads: `NonTemporalA/B/C/D` lower to `buffer_load ...
th:TH_LOAD_NT` -- a load-flavor knob, not a class rule.

Public API: assembly_class_valid, assembly_depth_u, ASSEMBLY_DTYPE_ELEM_BYTES.
"""

from __future__ import annotations

import re
from typing import Any

from oto.device import loader as _loader

from .memo import memo_gate
from .vgpr_model import is_hpa, knob_int

#: Bytes per element for the assembly-class dtype check. Distinct from
#: ``oto.tensile.gates.vgpr_model.BYTES_PER_ELEMENT``, which is an LDS
#: footprint table: a complex double element is 16 bytes here and 8 there,
#: because the class rule counts the *element* and the LDS rule counts the
#: *padded row*.
ASSEMBLY_DTYPE_ELEM_BYTES = {
    "S": 4, "D": 8, "H": 2, "B": 2, "Z": 16, "C": 8, "I8": 1, "I1": 1,
}

#: Tensile's own default for StaggerUStride.
STAGGER_STRIDE_DEFAULT = 256
#: Tensile's own default for StaggerU.
STAGGER_U_DEFAULT = 32


def assembly_depth_u(config: dict[str, Any]) -> int:
    """Resolve DepthU: explicit key first, else from the MacroTile string.

    Why a second reader: this gate is called with deck/shipped configs, which
    always carry the depth in the MacroTile string, whereas the occupancy gates
    also receive scheduler-generated configs that carry it as a key. Both are
    handled by ``oto.tensile.gates.vgpr_model.depth_u``; this variant keeps
    the Assembly gate's historical default (16) instead of failing closed on an
    unreadable depth, because an unreadable depth here is a *deck* defect that
    the rest of the gates already refuse.

    Accepts a Tensile solution dict; returns the resolved depth, or 16 when it
    is not explicit and not in the string.
    """
    if config.get("DepthU") is not None:
        return int(config["DepthU"])
    mt = str(config.get("MacroTile", "64x64x16"))
    parts = re.split(r"[xX]", mt.replace("MT", ""))
    if len(parts) >= 3:
        try:
            return int(parts[2])
        except ValueError:
            pass
    return 16


def _allows_complex_gsu(prof) -> bool:
    """Complex k-split permission: policy-enabled or MFMA fallback."""
    policy = getattr(prof, "assembly_gates", None)
    if policy is not None and policy.complex_allows_gsu:
        return True
    return prof.has_mfma


def _allows_half_gsu(prof) -> bool:
    """Half GSU permission: policy-enabled or MFMA fallback."""
    policy = getattr(prof, "assembly_gates", None)
    if policy is not None and policy.half_allows_gsu:
        return True
    return prof.has_mfma


def _is_hpa(config: dict[str, Any], dtype_upper: str) -> bool:
    """True when the config runs half with an f32 accumulator (HPA class).

    Thin alias: the reader (key-or-label, the two places the class is recorded)
    lives in ``oto.tensile.gates.vgpr_model.is_hpa`` so this rule and the
    compute-byte reader cannot disagree.
    """
    return is_hpa(config)


def _gsu_rejection(config: dict[str, Any], dtype_upper: str,
                   gsu: int, profile=None) -> str | None:
    """GlobalSplitU class rejection text, or None when GSU is legal.

    Rules:
      1. GSU > 1 on complex (Z/C) -- policy-enabled or MFMA; SolutionStructs:3553.
      2. GSU > 1 on half with f32 accumulate (HPA / HS_HPA,
         ComputeDataType 's') -- policy-enabled or MFMA; SolutionStructs:3553.
      3. GSU > 1 on half Assembly -- legal only if
         AssertFree0ElementMultiple >= 2 (deck ships AF0EM = 1 -> illegal;
         SolutionStructs:3616).
    ``profile`` is an optional ``DeviceProfile``; it defaults to the process's ambient profile.
    """
    prof = _loader.resolve_profile(profile,)
    is_hs_hpa = _is_hpa(config, dtype_upper) and dtype_upper in ("H", "B")

    if dtype_upper in ("Z", "C") and gsu > 1 and not _allows_complex_gsu(prof):
        return (f"GlobalSplitU={gsu} on complex {dtype_upper}: illegal on "
                f"{prof.codename} (no MatrixInstruction; SolutionStructs:3553)")

    if dtype_upper in ("H", "B") and is_hs_hpa and gsu > 1 and not _allows_half_gsu(prof):
        return (f"GlobalSplitU={gsu} on half with f32 accumulate "
                f"(HPA): illegal on {prof.codename} (needs half/mixed compute or "
                "MFMA; SolutionStructs:3553)")

    if dtype_upper in ("H", "B") and gsu > 1:
        af0em = knob_int(config.get("AssertFree0ElementMultiple",
                                     config.get("AssertFree0Multiple", 1,),), 1)
        if af0em < 2:
            return (f"GlobalSplitU={gsu} on half Assembly requires "
                    "AssertFree0ElementMultiple>=2 (have "
                    f"{af0em}; SolutionStructs:3616)")
    return None


def _stagger_rejection(config: dict[str, Any],
                       depth_u: int) -> str | None:
    """StaggerUStride-vs-DepthU rejection text, or None when legal.

    When StaggerU > 0, StaggerUStride must be >= DepthU*BytesPerElement (the
    staggerStrideShift >= 0 floor, SolutionStructs:3336-3342; Tensile raises SUS
    to a whole multiple of DepthU*bpe internally). When StaggerU == 0,
    StaggerUStride is 0 by Tensile's own forcing (:3333-3334) and is legal -- an
    earlier revision of this rule applied the floor unconditionally and so
    refused every swizzle-off config.
    """
    bpe = ASSEMBLY_DTYPE_ELEM_BYTES.get(str(config.get("DataType", "S")).upper(), 4)
    stagger = knob_int(config.get("StaggerUStride"), STAGGER_STRIDE_DEFAULT)
    stagger_u = knob_int(config.get("StaggerU"), STAGGER_U_DEFAULT)
    if stagger_u > 0 and depth_u * bpe > stagger:
        return (f"DepthU={depth_u} * {bpe}B = {depth_u*bpe} > "
                f"StaggerUStride={stagger}: StaggerUStride must be >= "
                "DepthU*BytesPerElement when StaggerU>0 "
                "(SolutionStructs:3336-3342)")
    return None


@memo_gate
def assembly_class_valid(config: dict[str, Any],
                        profile=None) -> tuple[bool, str]:
    """Return (True, "") if config is a legal Assembly GEMM class for the device.

    CLASS-BASED validity -- single source of truth for both seams (scheduler
    validate_config + the config writer). Any cell that falls in an illegal
    class is auto-caught pre-run, never launched on the device.

    Accepts a Tensile solution dict, normally with ``DataType`` merged in
    from the phase level (see the config writer's ``gate_config``). Returns
    ``(True, "")`` when legal, else ``(False, reason)`` citing the Tensile
    source line that refuses it. ``profile`` is an optional
    ``DeviceProfile``; it defaults to the process's ambient profile.
    """
    dtype_upper = str(config.get("DataType", "S",)).upper()
    gsu = knob_int(config.get("GlobalSplitU",), 1)
    # Resolved before the GSU rules, exactly as before the split: a config whose
    # DepthU is named but unparsable raises here rather than falling through to
    # a "legal" verdict from a later rule.
    depth_u = assembly_depth_u(config)
    reject = _gsu_rejection(config, dtype_upper, gsu, profile=profile,)
    if reject is not None:
        return False, reject
    reject = _stagger_rejection(config, depth_u)
    if reject is not None:
        return False, reject
    return True, ""
