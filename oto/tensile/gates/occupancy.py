"""Register-file and LDS occupancy gates.

Owns: the CPU-only model that reproduces every observed gfx90c occupancy
outcome -- ``occupancy_feasible`` (accumulator VGPRs + the LDS tile budget) and
``ldspad_feasible`` (padded LDS footprint plus the coupled swizzle
StaggerU/StaggerUMapping/StaggerUStride domains).
Does NOT own: the candidate generator (oto.tensile.candidate), the VGPR
*measurement* tables (oto.tensile.gates.vgpr_model), the legality class rules
(oto.tensile.gates.assembly), or any device constant (oto.device.peaks).

Why this is CPU-only: error 4 (``overflowedResources``) is raised while Tensile
generates the kernel, so without a model every rejected config costs a full
subprocess. Tensile source of truth -- Tensile/KernelWriterAssembly.py,
functionSuffix:

    vgprPerCU = 65536
    vgprPerThreadPerOccupancy = vgprPerCU // kernel["NumThreads"]
    numWorkGroupsPerCU = vgprPerThreadPerOccupancy // max(vgpr, agpr)
    if numWorkGroupsPerCU < 1:
        self.overflowedResources = 4      # "Occupancy limit"

i.e. error 4 is REGISTER-FILE exhaustion, not LDS. It is only detectable at
kernel-generation time, which is why it cannot be caught by the divisibility
or assembly-class gates -- those all pass on a config that dies here.

Model. With NumThreads = (MT0/TT0)*(MT1/TT1)*LocalSplitU:

    acc_vgprs_per_thread = TT0*TT1*R
    budget               = 65536 // NumThreads
    acc/budget           = R * MT0 * MT1 * LSU / 65536

The per-thread accumulator count (TT0*TT1*R) is what the 256 VGPR ISA ceiling
bounds; the *workgroup total* (R*MT0*MT1*LSU) is what Tensile's file check
bounds. The ThreadTile cancels out of the file check, so the two rules are
genuinely different constraints and both must be enforced:

  * per-thread:  TT0*TT1*R > 128          -> "total vgpr not in [0, 256]"
                 (TT 8x4 complex, the 8 ZZ phases that died 116 times each)
  * per-workgroup: R*MT0*MT1*LSU >= 65536 -> error 4 "Occupancy limit"
                 (C 128x128x8/tt4x4, Z 128x64x8/tt8x4: the accumulator alone
                  fills the 64K file, leaving nothing for operands)

The per-workgroup rule uses ``>=`` (not ``>``): an accumulator count equal to the
whole file already leaves no VGPRs for operands or addresses, so the kernel must
overflow. Calibrated cell-by-cell on the corpus (`gate_calibration`), it refuses
0 built phases and 40 empty ones.

RETIRED: this gate used to model R * MacroTile_area <= 65536/2. That model was
calibrated against the pass/fail boundary but was structurally wrong, and real
runs proved it. It predicted complex (Z) 128x64 and 64x128 would fail -- true,
but for the wrong reason -- while passing complex 128x32, which then died 116
times in run_20260928_024945. Building every phase's kernel with Tensile's own
writer (check_tensile_build.py, CPU-only) showed the per-thread constraint is the
per-thread accumulator count TT0*TT1*weight against the 256 VGPR/thread ISA
limit; the MacroTile-area term belongs to the *separate* workgroup-file rule
above, whose threshold (65536, not 32768) and boundary (>=, not >) are what that
old model got wrong. Calibration table now lives in oto.tensile.gates.vgpr_model;
post-mortem in potential_configs.md.
Public API: occupancy_feasible, ldspad_feasible, occupancy_workgroups_per_cu,
dtype_char, tile_dims, refuses_workgroup_register_file,
refuses_lds_reduction_buffer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from .vgpr_model import (ACCVGPR_BUDGET, BYTES_PER_ELEMENT, LDS_BUDGET,
                         MAX_LDS_BYTES, MAX_VGPR_PER_THREAD, MEASURED_VGPR,
                         MEASURED_VGPR_BY_DTYPE, VGPR_PER_CU, VGPR_PER_ELEMENT,
                         compute_bytes, depth_u, lds_base_bytes, local_split_u,
                         measured_accvgpr, num_threads)

#: Legal StaggerU values (Tensile Common.py:945).
STAGGER_U_DOMAIN = (0, 2, 4, 8, 16, 32, 64)
#: Legal StaggerUMapping values (Tensile Common.py:946).
STAGGER_MAPPING_DOMAIN = (0, 1, 2, 3, 4)
#: Legal StaggerUStride values (Tensile Common.py:947).
STAGGER_STRIDE_DOMAIN = (0, 16, 32, 64, 128, 256, 512, 1024, 2048)

#: Tensile's own default for StaggerU, used when a config omits the key. An
#: absent StaggerU therefore behaves as "stagger on".
STAGGER_U_DEFAULT = 32
#: Tensile's own default for StaggerUStride.
STAGGER_STRIDE_DEFAULT = 256
#: Tensile's own default for StaggerUMapping.
STAGGER_MAPPING_DEFAULT = 0


def tile_dims(config: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
    """(MT0, MT1, TT0, TT1) from MacroTile/ThreadTile, or None if unusable.

    Args:
        config: A Tensile solution dict.

    Returns:
        The four dims, or None when either key is absent, unparsable or
        non-positive. Callers treat None as "cannot model" and fail closed.
    """
    mt_raw = config.get("MacroTile")
    tt_raw = config.get("ThreadTile")
    if not mt_raw or not tt_raw:
        return None
    mt_clean = str(mt_raw).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
    tt_clean = str(tt_raw).lower().replace("_", "x")
    try:
        mt_parts = [int(x) for x in re.split(r'[xX]', mt_clean)]
        tt_parts = [int(x) for x in re.split(r'[xX]', tt_clean)]
    except ValueError:
        return None
    if len(mt_parts) < 2 or len(tt_parts) < 2:
        return None
    if mt_parts[0] <= 0 or mt_parts[1] <= 0 or tt_parts[0] <= 0 or tt_parts[1] <= 0:
        return None
    return mt_parts[0], mt_parts[1], tt_parts[0], tt_parts[1]


def dtype_char(config: Dict[str, Any]) -> str:
    """Dtype char for a config, or "" when it cannot be determined.

    Why: a wrong guess would pick the wrong VGPR weight (Z is 8, S is 1) and
    silently admit a config the gate must reject, so an unknown dtype fails
    closed with "".

    Args:
        config: A Tensile solution dict carrying ``DataType``/``dtype`` or a
            ``FamilyLabel``/``family_label``.

    Returns:
        The canonical dtype char (S/D/H/B/I8/C/Z), or "" when unreadable.
    """
    raw = config.get("DataType", config.get("dtype"))
    if raw is None:
        # Label-only configs exist in the auto-generated phases; the label
        # carries the same information, so resolve through it rather than
        # failing closed on a config whose dtype is knowable.
        raw = config.get("FamilyLabel", config.get("family_label"))
    if raw is None:
        return ""
    ch = str(raw).upper()
    # HPA families carry the base dtype in their label: HH_HPA is f16 pairs
    # (weight 1) and HS_HPA is f32 pairs (weight 1). Without these, a
    # label-only HPA config cannot be modelled and the register-file gate fails
    # it closed -- which silently removes the entire HPA deck from generation.
    return {
        "SS": "S", "DD": "D", "HH": "H", "ZZ": "Z", "CC": "C", "FF": "S",
        "HH_HPA": "H", "HS_HPA": "S",
    }.get(ch, ch)


# ---------------------------------------------------------------- rejections
#
# The reason strings are kept verbatim and in one place each, because the
# operator reads them against a Tensile log: a re-worded message is a message
# that no longer matches the error it is explaining.

def _unknown_dtype_rejection(ch: str) -> str:
    """Reject text for a dtype the model has no VGPR weight for."""
    return (f"DataType {ch or '<missing>'!r} has no VGPR weight in "
            f"VGPR_PER_ELEMENT; cannot prove register-file occupancy")


def _accvgpr_rejection(ch: str, r: int, tt0: int, tt1: int, acc: int) -> str:
    """Reject text for a thread tile whose accumulator demand exceeds budget."""
    observed = (MEASURED_VGPR_BY_DTYPE.get(ch) or {}).get((tt0, tt1))
    if observed is None:
        observed = MEASURED_VGPR.get((tt0, tt1))
    seen = f"; measured {observed} VGPRs" if observed else ""
    return (
        f"ThreadTile {tt0}x{tt1} needs {acc} accumulator VGPRs/thread "
        f"({ch} weight {r}), budget {ACCVGPR_BUDGET}{seen}. Tensile emits "
        f"'total vgpr: N not in [0, {MAX_VGPR_PER_THREAD}]' and refuses the "
        f"kernel. Reduce ThreadTile to {ACCVGPR_BUDGET // r} elements or fewer "
        f"(e.g. {(2, 2) if r >= 8 else (4, 4)} for this dtype)."
    )


def _workgroup_vgpr_rejection(ch: str, r: int, mt0: int, mt1: int, lsu: int,
                              nt: int) -> str:
    """Reject text for a workgroup whose accumulators alone fill the register file."""
    return (
        f"MacroTile {mt0}x{mt1} (LocalSplitU {lsu}, NumThreads {nt}) needs "
        f"{r*mt0*mt1*lsu} accumulator VGPRs across the workgroup ({ch} weight "
        f"{r}); the file holds {VGPR_PER_CU}. The accumulators alone fill it, so "
        f"Tensile raises 'Generating kernel source resulted in error 4' "
        f"(overflowedResources / the 'Occupancy limit' in KernelWriterAssembly "
        f"functionSuffix) with no room left for operands. Reduce MacroTile area "
        f"(<= {VGPR_PER_CU // r} elements per workgroup) or drop LocalSplitU."
    )


def _lds_reduction_rejection(ch: str, mt0: int, mt1: int, lsu: int,
                             compute: int, lds: int) -> str:
    """Reject text for an LSU reduction buffer past the per-CU LDS ceiling."""
    return (
        f"LocalSplitU {lsu} on MacroTile {mt0}x{mt1} needs a "
        f"{lds}-byte LDS reduction buffer ({lsu}*{mt0}*{mt1}*{compute}B compute), "
        f"over the {MAX_LDS_BYTES} per-CU ceiling; Tensile rejects it with "
        f"'Kernel Uses N > 65536 bytes of LDS' (SolutionStructs:4108,4334). "
        f"Reduce MacroTile area (<= {MAX_LDS_BYTES // (lsu * compute)} elements) "
        f"or set LocalSplitU 1."
    )


def _undetermined_depth_rejection() -> str:
    """Reject text for a config whose DepthU cannot be read."""
    return (
        "DepthU could not be determined from DepthU or MacroTile; cannot "
        "prove the LDS footprint. Set MacroTile as 'MT0xMT1xDepthU' or set "
        "DepthU explicitly."
    )


def _lds_rejection(ch: str, mt0: int, mt1: int, ku: int, lds: int) -> str:
    """Reject text for an LDS tile footprint past the budget."""
    return (
        f"MacroTile {mt0}x{mt1} at DepthU {ku} needs a {lds}-byte LDS tile "
        f"footprint for {ch}, budget {LDS_BUDGET}. Prefetch double-buffering "
        f"and offset alignment push the real figure well past 64 KB, so "
        f"Tensile rejects it with 'Kernel Uses N > 65536 bytes of LDS' and "
        f"the phase yields zero solutions. Reduce MacroTile area or DepthU "
        f"(keep (MT0+MT1)*DepthU <= {LDS_BUDGET // BYTES_PER_ELEMENT[ch]})."
    )


# ------------------------------------------------------------------- gates

def occupancy_workgroups_per_cu(config: Dict[str, Any]) -> int:
    """Modelled workgroups per CU; 0 when the gate rejects the config.

    Per-thread register demand is fixed by the thread tile (accumulators) and
    shared across the workgroup, so this is the 64K file divided by the
    per-thread cost. 0 means "this config is not launchable", not "zero
    occupancy".

    Args:
        config: A Tensile solution dict.

    Returns:
        Workgroups per CU, or 0 when ``occupancy_feasible`` would refuse it.
    """
    dims = tile_dims(config)
    if not dims:
        return 0
    mt0, mt1, tt0, tt1 = dims
    ch = dtype_char(config)
    r = VGPR_PER_ELEMENT.get(ch)
    if r is None:
        return 0
    lsu = local_split_u(config)
    acc = measured_accvgpr(tt0, tt1, r)
    if acc > ACCVGPR_BUDGET:
        return 0
    if r * mt0 * mt1 * lsu >= VGPR_PER_CU:
        return 0
    compute = compute_bytes(config, ch)
    if lsu > 1 and compute and lsu * mt0 * mt1 * compute > MAX_LDS_BYTES:
        return 0
    ku = depth_u(config)
    if ku <= 0:
        return 0
    if lds_base_bytes(mt0, mt1, dtype_char(config)) * ku > LDS_BUDGET:
        return 0
    return VGPR_PER_CU // acc


def occupancy_feasible(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Register-file gate: reject configs Tensile cannot generate.

    Complements the divisibility and assembly-class gates: an over-wide thread
    tile passes those and still dies here. Three calibrated rules, in the order
    Tensile reaches them:

    * per-thread accumulators -- ``TT0*TT1*weight > ACCVGPR_BUDGET`` (128).
      Tensile refuses past 256 VGPRs/thread; on gfx90c complex (Z), TT 4x4 =
      128 accVGPR passes and TT 8x4 = 256 -> 271 VGPRs FAILs.
    * the workgroup register file -- ``weight*MT0*MT1*LSU >= 65536`` (error 4,
      see :func:`_workgroup_file_check`); ThreadTile cancels, so it bounds
      MacroTile *area*.
    * the LDS reduction buffer -- ``LSU>1`` and
      ``LSU*MT0*MT1*computeBytes > 65536`` (``MaxLDS``, see
      :func:`_lds_reduction_check`).

    All three are corpus-calibrated with 0 false rejections. An earlier version
    modelled MacroTile *area* at ``<= 65536/2`` instead and was wrong in both
    directions (it passed the 8 ZZ TT8x4 phases that died 116 times each); the
    post-mortem is in ``potential_configs.md``.

    Args:
        config: A Tensile solution dict.

    Returns:
        ``(True, "")`` when the config is launchable, else ``(False, reason)``.
        No readable tile dims -> ``(True, "")`` ("nothing to model"); other
        gates own that case.
    """
    dims = tile_dims(config)
    if not dims:
        return True, ""                      # nothing to model; other gates own it
    mt0, mt1, tt0, tt1 = dims
    ch = dtype_char(config)
    r = VGPR_PER_ELEMENT.get(ch)
    if r is None:
        # Fail closed: an unmodelled dtype could be a complex one (Z weights 8),
        # and guessing low would let a config through that then dies as error 4.
        return False, _unknown_dtype_rejection(ch)
    acc = measured_accvgpr(tt0, tt1, r)
    if acc > ACCVGPR_BUDGET:
        return False, _accvgpr_rejection(ch, r, tt0, tt1, acc)
    lsu = local_split_u(config)
    reason = _workgroup_file_check(dims, mt0, mt1, r, lsu, ch)
    if reason:
        return False, reason
    reason = _lds_reduction_check(config, ch, mt0, mt1, lsu)
    if reason:
        return False, reason
    ku = depth_u(config)
    if ku <= 0:
        # Fail closed, like an unknown weight: an unread depth understates the
        # LDS footprint up to 16x (how 128x32x16 once slipped through).
        return False, _undetermined_depth_rejection()
    lds = lds_base_bytes(mt0, mt1, ch) * ku
    if lds > LDS_BUDGET:
        return False, _lds_rejection(ch, mt0, mt1, ku, lds)
    return True, ""


def _workgroup_file_check(dims, mt0, mt1, weight, lsu, ch) -> Optional[str]:
    """Reason when the accumulator set alone fills the 64K file, else None.

    Tensile's ``KernelWriterAssembly.functionSuffix`` sets ``overflowedResources
    = 4`` (error 4) when ``65536 // NumThreads // max(vgpr, agpr) < 1``. The
    accumulators are always allocated, so ``weight*MT0*MT1*LSU`` is a sound lower
    bound on the workgroup total and ``>= 65536`` is exactly "no room for one
    workgroup". ThreadTile cancels, so this bounds MacroTile *area*.
    """
    if weight * mt0 * mt1 * lsu >= VGPR_PER_CU:
        return _workgroup_vgpr_rejection(
            ch, weight, mt0, mt1, lsu, num_threads(dims, lsu))
    return None


def _lds_reduction_check(config, ch, mt0, mt1, lsu) -> Optional[str]:
    """Reason when the LSU reduction buffer exceeds 64 KiB, else None.

    Only emitted when ``LocalSplitU > 1``: Tensile sizes it at
    ``LSU*MT0*MT1`` *compute* elements and rejects past ``MaxLDS`` at
    ``SolutionStructs:4334``.
    """
    if lsu <= 1:
        return None
    compute = compute_bytes(config, ch)
    if not compute:
        return None
    size = lsu * mt0 * mt1 * compute
    if size > MAX_LDS_BYTES:
        return _lds_reduction_rejection(ch, mt0, mt1, lsu, compute, size)
    return None


def refuses_workgroup_register_file(config: Dict[str, Any]) -> Optional[bool]:
    """The workgroup-register-file rule as a standalone predicate.

    ``None`` when the config cannot be modelled (unreadable tile dims or an
    unmapped dtype -- other gates own that case), else whether
    ``weight*MT0*MT1*LocalSplitU >= 65536``. This is the calibration-facing form
    ``oto.harness.rule_calibration`` probes; it re-uses the same
    :func:`_workgroup_file_check` ``occupancy_feasible`` enforces, so the two
    cannot drift.
    """
    dims = tile_dims(config)
    if not dims:
        return None
    mt0, mt1, _tt0, _tt1 = dims
    ch = dtype_char(config)
    weight = VGPR_PER_ELEMENT.get(ch)
    if weight is None:
        return None
    return _workgroup_file_check(
        dims, mt0, mt1, weight, local_split_u(config), ch) is not None


def refuses_lds_reduction_buffer(config: Dict[str, Any]) -> Optional[bool]:
    """The LSU LDS-reduction-buffer rule as a standalone predicate.

    ``None`` when the config cannot be modelled, else whether Tensile's
    reduction buffer exceeds ``MaxLDS`` (only possible when ``LocalSplitU > 1``):
    ``LSU*MT0*MT1*computeBytes > 65536``. Calibration-facing form of
    :func:`_lds_reduction_check`, kept on the same code path so the probe and the
    gate agree by construction.
    """
    dims = tile_dims(config)
    if not dims:
        return None
    mt0, mt1, _tt0, _tt1 = dims
    return _lds_reduction_check(
        config, dtype_char(config), mt0, mt1, local_split_u(config)) is not None


def _pads_feasible(config: Dict[str, Any], ku: int,
                    bpe: Optional[int]) -> Tuple[bool, str]:
    """LdsPad legality, including the padded LDS footprint.

    Why: `_write_phase_config` used to drop LdsPadA/B silently, so a candidate
    carrying pads benchmarked with pads stripped to 0 (every reference kernel). The gate exists so the FORWARDED value is never what kills a
    phase quietly.
    """
    pad_a = config.get("LdsPadA", 0)
    pad_b = config.get("LdsPadB", 0)
    try:
        pad_a, pad_b = int(pad_a or 0), int(pad_b or 0)
    except (TypeError, ValueError):
        return False, f"LdsPadA/B must be integers (have {pad_a!r}/{pad_b!r})"
    if pad_a < 0 or pad_b < 0:
        return False, f"LdsPadA/B must be >= 0 (have {pad_a}/{pad_b})"
    if pad_a or pad_b:
        if not config.get("MacroTile") or ku <= 0 or not bpe:
            return False, (
                "LdsPad requires a resolvable MacroTile, DepthU and dtype to "
                "prove the padded LDS footprint"
            )
        dims = tile_dims(config)
        if not dims:
            return False, "LdsPad requires a resolvable ThreadTile"
        mt0, mt1, _, _ = dims
        footprint = (mt0 + pad_a + mt1 + pad_b) * bpe * ku
        if footprint > LDS_BUDGET:
            return False, (
                f"padded LDS footprint {footprint} > budget {LDS_BUDGET} with "
                f"LdsPadA={pad_a} LdsPadB={pad_b} at DepthU {ku}; the pads would "
                f"be dropped or the phase rejected by Tensile"
            )
    return True, ""


def _int_or_reject(value, label: str) -> Tuple[Optional[int], Optional[str]]:
    """Parse an int knob, or produce the reject text for a non-integer one."""
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"{label} must be an integer (have {value!r})"


def _swizzle_feasible(config: Dict[str, Any], ku: int,
                       bpe: Optional[int]) -> Tuple[bool, str]:
    """The coupled StaggerU / StaggerUMapping / StaggerUStride domains.

    Tensile source (SolutionStructs:3326-3342, Common.py:945-947, 1599-1601):

      * StaggerUStride=0 is only valid if StaggerU=0.
      * StaggerU=0 forces StaggerUMapping=0 and StaggerUStride=0.
      * StaggerUStride>0 requires staggerStrideShift = ceil(log2(SUS/(DU*bpe)))
        >= 0, i.e. SUS > 0.5*DepthU*bpeAB (the ":3342" reject). Tensile then
        internally raises SUS to a whole multiple of DepthU*bpe.
      * Legal domains: SU in :data:`STAGGER_U_DOMAIN`, SUM in
        :data:`STAGGER_MAPPING_DOMAIN`, SUS in :data:`STAGGER_STRIDE_DOMAIN`.
        SU requires BufferLoad==1 and is silently ignored otherwise.

    Why an earlier revision was wrong: it had the SUS bound BACKWARDS (it
    rejected SUS >= DepthU*bpe, i.e. exactly the legal swizzle values), which is
    why Group C swizzle forwarding was blocked -- every legal StaggerUStride was
    refused at the launch boundary. Corrected 2026-10-09 against the pinned
    checkout (Tensile commit e8a8999e).
    """
    stagger_u = config.get("StaggerU")
    stagger_mapping = config.get("StaggerUMapping")
    su = config.get("StaggerUStride")
    if stagger_u is not None:
        su_val, err = _int_or_reject(stagger_u, "StaggerU")
        if err or su_val not in STAGGER_U_DOMAIN:
            return False, (f"StaggerU={su_val} outside Tensile domain "
                           f"{STAGGER_U_DOMAIN} (Common.py:945)")
    if stagger_mapping is not None:
        sum_val, err = _int_or_reject(stagger_mapping, "StaggerUMapping")
        if err or sum_val not in STAGGER_MAPPING_DOMAIN:
            return False, (f"StaggerUMapping={sum_val} outside Tensile domain "
                           f"{STAGGER_MAPPING_DOMAIN} (Common.py:946)")
    if su is not None:
        stride, err = _int_or_reject(su, "StaggerUStride")
        if err or stride < 0 or stride not in STAGGER_STRIDE_DOMAIN:
            return False, (f"StaggerUStride={stride} outside Tensile domain "
                           f"{STAGGER_STRIDE_DOMAIN} (Common.py:947)")
    # Coupling. Tensile defaults SU=32 (absent SU = >0); absent SU = "stagger on".
    su_effective = STAGGER_U_DEFAULT if stagger_u is None else int(stagger_u)
    stride_effective = STAGGER_STRIDE_DEFAULT if su is None else int(su)
    mapping_effective = (STAGGER_MAPPING_DEFAULT if stagger_mapping is None
                         else int(stagger_mapping))

    if su_effective == 0:
        if mapping_effective != 0:
            return False, (f"StaggerUMapping={mapping_effective} requires "
                           f"StaggerU>0 (SolutionStructs:3333-3334)")
        if stride_effective != 0:
            return False, (f"StaggerUStride={stride_effective} requires "
                           f"StaggerU>0 (SolutionStructs:3326-3327)")
    elif stride_effective == 0:
        return False, (f"StaggerUStride=0 is only valid if StaggerU is 0 "
                       f"(have StaggerU={su_effective}; SolutionStructs:3326-3327)")
    elif ku > 0 and bpe and stride_effective < ku * bpe:
        return False, (f"StaggerUStride={stride_effective} < DepthU({ku})*{bpe}B; "
                       f"Tensile requires StaggerUStride >= DepthU*BytesPerElement "
                       f"when StaggerU>0 (staggerStrideShift >= 0, SolutionStructs:3336-3342)")
    return True, ""


def _store_knobs_feasible(config: Dict[str, Any]) -> Tuple[bool, str]:
    """AssertFree0ElementMultiple and StoreCInUnroll sanity.

    Why only sanity-checks: the half-Assembly GSU rule for AF0EM (>=2) is
    enforced by ``assembly_class_valid``; enforcing a *second* copy here would
    be two homes for one fact.
    """
    af0em = config.get("AssertFree0ElementMultiple")
    if af0em is not None:
        av, err = _int_or_reject(af0em, "AssertFree0ElementMultiple")
        if err:
            return False, err
        if av < 1:
            return False, f"AssertFree0ElementMultiple must be >= 1 (have {av})"

    sci = config.get("StoreCInUnroll")
    if sci is not None and not (isinstance(sci, bool) or int(str(sci)) in (0, 1)):
        return False, f"StoreCInUnroll must be a bool (have {sci!r})"
    return True, ""


def ldspad_feasible(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Group C legality gate for the forwarded LDS-pad / RCT knobs.

    Why: the launch boundary forwards LdsPadA/B, AssertFree0ElementMultiple,
    StaggerUStride and StoreCInUnroll only when this CPU-only gate passes, so a
    forwarded value can never surface as an opaque Tensile "error 4" mid-run.

    Configs that carry none of these keys trivially pass -- the gate exists so
    the FORWARDED value is never what kills a phase silently.

    Args:
        config: A Tensile solution dict.

    Returns:
        ``(True, "")`` or ``(False, reason)``.
    """
    ku = depth_u(config)
    ch = dtype_char(config)
    bpe = BYTES_PER_ELEMENT.get(ch)

    for gate in (_pads_feasible, _swizzle_feasible):
        ok, reason = gate(config, ku, bpe)
        if not ok:
            return False, reason
    return _store_knobs_feasible(config)
