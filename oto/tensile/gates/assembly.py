"""The assembly-class gate: is this GEMM class legal on gfx90c at all?

Owns: ``assembly_class_valid``, the single source of truth for both seams (the
candidate generator's ``validate_config`` and the launch boundary's config
writer). Any cell that falls in an illegal class is caught pre-run, never
launched.
Does NOT own: the register-file/LDS model (oto.tensile.gates.occupancy), the
classic-path load divisibility (oto.tensile.gates.loads), or the candidate
sampler (oto.tensile.candidate).

Faithful to the Tensile SolutionStructs Assembly rejects reproduced from the 24
draft-run failures (gfx90c = Assembly-only, FFMA, no MatrixInstruction/MFMA
escape; Tensile v4.44.0):

  SolutionStructs:3553  "GlobalSplitU only compatible with single, or asm and
                          (half or mixed) precision, or EnableMatrixInstruction"
  SolutionStructs:3616  "Assembly GSU half requires AssertFree0ElementMultiple>=2"
  SolutionStructs:3342  "StaggerUStride < DepthU * BytesPerElement"
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

#: Bytes per element for the assembly-class dtype check. Distinct from
#: :data:`oto.tensile.gates.vgpr_model.BYTES_PER_ELEMENT`, which is an LDS
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


def assembly_depth_u(config: Dict[str, Any]) -> int:
    """Resolve DepthU: explicit key first, else from the MacroTile string.

    Why a second reader: this gate is called with deck/shipped configs, which
    always carry the depth in the MacroTile string, whereas the occupancy gates
    also receive scheduler-generated configs that carry it as a key. Both are
    handled by :func:`oto.tensile.gates.vgpr_model.depth_u`; this variant keeps
    the Assembly gate's historical default (16) instead of failing closed on an
    unreadable depth, because an unreadable depth here is a *deck* defect that
    the rest of the gates already refuse.

    Args:
        config: A Tensile solution dict.

    Returns:
        The resolved depth, or 16 when it is not explicit and not in the string.
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


def _is_hpa(config: Dict[str, Any], dtype_upper: str) -> bool:
    """True when the config runs half with an f32 accumulator (HPA class)."""
    return bool(config.get("HighPrecisionAccumulate", False)) or (
        "HPA" in str(config.get("FamilyLabel", "")).upper()
        or "HPA" in str(config.get("label", "")).upper()
    )


def _gsu_rejection(config: Dict[str, Any], dtype_upper: str,
                   gsu: int) -> Optional[str]:
    """GlobalSplitU class rejection text, or None when GSU is legal here.

    Rules:
      1. GlobalSplitU > 1 on complex (Z/C) -- illegal on gfx90c (no MFMA;
         SolutionStructs:3553).
      2. GlobalSplitU > 1 on half with f32 accumulate (HPA / HS_HPA,
         ComputeDataType 's') -- illegal (needs half/mixed compute or MFMA;
         SolutionStructs:3553).
      3. GlobalSplitU > 1 on half Assembly -- legal only if
         AssertFree0ElementMultiple >= 2 (deck ships AF0EM = 1 -> illegal;
         SolutionStructs:3616).
    """
    is_hpa = _is_hpa(config, dtype_upper)
    is_hs_hpa = is_hpa and dtype_upper in ("H", "B")

    if dtype_upper in ("Z", "C") and gsu > 1:
        return (f"GlobalSplitU={gsu} on complex {dtype_upper}: illegal on "
                "gfx90c (no MatrixInstruction; SolutionStructs:3553)")

    if dtype_upper in ("H", "B") and is_hs_hpa and gsu > 1:
        return (f"GlobalSplitU={gsu} on half with f32 accumulate "
                "(HPA): illegal on gfx90c (needs half/mixed compute or "
                "MFMA; SolutionStructs:3553)")

    if dtype_upper in ("H", "B") and gsu > 1:
        af0em = int(config.get("AssertFree0ElementMultiple",
                               config.get("AssertFree0Multiple", 1)))
        if af0em < 2:
            return (f"GlobalSplitU={gsu} on half Assembly requires "
                    "AssertFree0ElementMultiple>=2 (have "
                    f"{af0em}; SolutionStructs:3616)")
    return None


def _stagger_rejection(config: Dict[str, Any],
                       depth_u: int) -> Optional[str]:
    """StaggerUStride-vs-DepthU rejection text, or None when legal.

    When StaggerU > 0, StaggerUStride must be >= DepthU*BytesPerElement (the
    staggerStrideShift >= 0 floor, SolutionStructs:3336-3342; Tensile raises SUS
    to a whole multiple of DepthU*bpe internally). When StaggerU == 0,
    StaggerUStride is 0 by Tensile's own forcing (:3333-3334) and is legal -- an
    earlier revision of this rule applied the floor unconditionally and so
    refused every swizzle-off config.
    """
    bpe = ASSEMBLY_DTYPE_ELEM_BYTES.get(str(config.get("DataType", "S")).upper(), 4)
    stagger = int(config.get("StaggerUStride", STAGGER_STRIDE_DEFAULT))
    stagger_u = int(config.get("StaggerU", STAGGER_U_DEFAULT))
    if stagger_u > 0 and depth_u * bpe > stagger:
        return (f"DepthU={depth_u} * {bpe}B = {depth_u*bpe} > "
                f"StaggerUStride={stagger}: StaggerUStride must be >= "
                "DepthU*BytesPerElement when StaggerU>0 "
                "(SolutionStructs:3336-3342)")
    return None


def assembly_class_valid(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (True, "") if config is a legal gfx90c Assembly GEMM class.

    CLASS-BASED validity -- single source of truth for both seams (scheduler
    validate_config + the config writer). Any cell that falls in an illegal
    class is auto-caught pre-run, never launched on gfx90c.

    Args:
        config: A Tensile solution dict, normally with ``DataType`` merged in
            from the phase level (see the config writer's ``gate_config``).

    Returns:
        ``(True, "")`` when legal, else ``(False, reason)`` citing the Tensile
        source line that refuses it.
    """
    dtype_upper = str(config.get("DataType", "S")).upper()
    gsu = int(config.get("GlobalSplitU", 1))
    # Resolved before the GSU rules, exactly as before the split: a config whose
    # DepthU is named but unparsable raises here rather than falling through to
    # a "legal" verdict from a later rule.
    depth_u = assembly_depth_u(config)
    reject = _gsu_rejection(config, dtype_upper, gsu)
    if reject is not None:
        return False, reject
    reject = _stagger_rejection(config, depth_u)
    if reject is not None:
        return False, reject
    return True, ""
