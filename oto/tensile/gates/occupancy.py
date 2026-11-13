"""Register-file and LDS occupancy gates.

Owns: the CPU-only model that reproduces every observed device occupancy
outcome -- ``occupancy_feasible`` (accumulator VGPRs + the LDS tile budget); the
LdsPad/swizzle gate lives in ``oto.tensile.gates.ldspad_gate`` and is
re-exported here for the historical import path.
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
writer (``oto check tensile-build``, CPU-only) showed the per-thread constraint is the
per-thread accumulator count TT0*TT1*weight against the 256 VGPR/thread ISA
limit; the MacroTile-area term belongs to the *separate* workgroup-file rule
above, whose threshold (65536, not 32768) and boundary (>=, not >) are what that
old model got wrong. Calibration table now lives in oto.tensile.gates.vgpr_model;
post-mortem in potential_configs.md.
Public API: occupancy_feasible, ldspad_feasible (re-exported),
occupancy_workgroups_per_cu, dtype_char, tile_dims (shared; see
``oto.tensile.gates.occupancy_common``), refuses_workgroup_register_file,
refuses_per_thread_occupancy_limit, refuses_lds_reduction_buffer.
"""

from __future__ import annotations

from typing import Any

from .memo import memo_gate

__all__ = [
    'dtype_char',
    'ldspad_feasible',
    'occupancy_feasible',
    'occupancy_workgroups_per_cu',
    'refuses_lds_reduction_buffer',
    'refuses_per_thread_occupancy_limit',
    'refuses_workgroup_register_file',
    'tile_dims',
]
from .ldspad_gate import ldspad_feasible as ldspad_feasible  # re-export
from .occupancy_common import dtype_char as dtype_char
from .occupancy_common import tile_dims as tile_dims  # re-export
from .vgpr_model import (
    ACCVGPR_BUDGET,
    BYTES_PER_ELEMENT,
    LDS_BUDGET,
    MAX_LDS_BYTES,
    MAX_VGPR_PER_THREAD,
    MEASURED_VGPR,
    MEASURED_VGPR_BY_DTYPE,
    VGPR_PER_CU,
    VGPR_PER_ELEMENT,
    compute_bytes,
    depth_u,
    lds_base_bytes,
    local_split_u,
    measured_accvgpr,
    num_threads,
    per_thread_vgpr,
)

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


def _occupancy_limit_rejection(ch: str, tt0: int, tt1: int, vgpr: int,
                                nt: int) -> str:
    """Reject text for a kernel whose per-thread VGPRs do not fit the file."""
    return (
        f"ThreadTile {tt0}x{tt1} emits {vgpr} VGPRs/thread and the workgroup "
        f"has {nt} threads: Tensile's occupancy limit is "
        f"65536 // {nt} = {VGPR_PER_CU // nt} VGPRs/thread, so the workgroup "
        f"needs {vgpr * nt} VGPRs against the file's {VGPR_PER_CU}. Tensile "
        f"raises 'Generating kernel source resulted in error 4' "
        f"(KernelWriterAssembly.functionSuffix: "
        f"numWorkGroupsPerCU = (65536 // NumThreads) // max(vgpr, agpr) < 1). "
        f"Use a smaller thread tile, a smaller MacroTile, or a tile with more "
        f"threads per element."
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

def occupancy_workgroups_per_cu(config: dict[str, Any]) -> int:
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


def _register_file_checks(config: dict[str, Any], dims, ch: str, r: int,
                          lsu: int) -> str | None:
    """The register-file rules, in the order Tensile reaches them.

    * the LocalSplitU spelling contradiction (a config that means two things),
    * the workgroup register file (``weight*MT0*MT1*LSU >= 65536``),
    * the per-thread occupancy limit (the EMITTED VGPRs against
      ``65536 // NumThreads``),
    * the LDS reduction buffer (``LSU*MT0*MT1*computeBytes > 65536``).
    """
    reason = _local_split_u_contradiction(config)
    if reason:
        return reason
    mt0, mt1, _tt0, _tt1 = dims
    reason = _workgroup_file_check(dims, mt0, mt1, r, lsu, ch)
    if reason:
        return reason
    reason = _occupancy_limit_check(dims, ch, dims[2], dims[3], lsu)
    if reason:
        return reason
    return _lds_reduction_check(config, ch, mt0, mt1, lsu)


@memo_gate
def occupancy_feasible(config: dict[str, Any], profile=None) -> tuple[bool, str]:
    """Register-file gate: reject configs Tensile cannot generate.

    Complements the divisibility and assembly-class gates: an over-wide thread
    tile passes those and still dies here. Three calibrated rules, in the order
    Tensile reaches them:

    * per-thread accumulators -- ``TT0*TT1*weight > ACCVGPR_BUDGET`` (128).
      Tensile refuses past 256 VGPRs/thread; on this device, complex (Z), TT 4x4 =
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
    if profile is None:
        return _occupancy_feasible_impl(config)
    from .vgpr_model import bound_profile as _bp
    with _bp(profile):
        return _occupancy_feasible_impl(config)


def _occupancy_feasible_impl(config: dict[str, Any]) -> tuple[bool, str]:
    """Body of :func:`occupancy_feasible` with any bound profile applied."""
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
    reason = _register_file_checks(config, dims, ch, r, lsu)
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


def _local_split_u_contradiction(config: dict[str, Any]) -> str | None:
    """Reason when the two spellings of LocalSplitU disagree, else None.

    Tensile reads LocalSplitU from ``WorkGroup[2]`` and has no standalone key,
    so a config carrying both a ``LocalSplitU`` key and an explicit
    ``WorkGroup`` has two answers to the same question. The writer folds the
    key into element [2] (so the knob is honoured rather than dropped), but a
    row whose two spellings *disagree* is a config that means two different
    things -- refuse it rather than benchmark one of them by accident.
    """
    key = config.get("LocalSplitU")
    wg = config.get("WorkGroup")
    if key is None or not isinstance(wg, (list, tuple)) or len(wg) < 3:
        return None
    try:
        want, have = int(key), int(wg[2])
    except (TypeError, ValueError):
        return None
    if want == have:
        return None
    return (f"LocalSplitU={want} contradicts WorkGroup[2]={have}: Tensile reads "
            f"LocalSplitU from WorkGroup[2] and ignores the key, so the config "
            f"would run as LSU={have}. Use one spelling.")


def _workgroup_file_check(dims, mt0, mt1, weight, lsu, ch) -> str | None:
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


def _occupancy_limit_check(dims, ch, tt0, tt1, lsu) -> str | None:
    """Reason when the EMITTED per-thread VGPRs do not fit the workgroup.

    Tensile's error-4 test (``KernelWriterAssembly.functionSuffix``) is

        vgprPerThreadPerOccupancy = 65536 // NumThreads
        numWorkGroupsPerCU = vgprPerThreadPerOccupancy // max(vgpr, agpr)
        if numWorkGroupsPerCU < 1: overflowedResources = 4

    The *emitted* ``vgpr`` (accumulators **plus** the A/B operand fragments and
    the addresses) has to fit in ``65536 // NumThreads``. The accumulator-only
    rules miss this: SS 256x128 with TT 8x4 emits 79 VGPRs/thread over 1024
    threads (64 VGPRs/thread available) and dies with error 4, while its
    accumulator total is only 32768 -- half the file, so both accumulator rules
    pass it. The classic path has no arch accumulator registers (``agpr`` is 0),
    so the test is on ``vgpr`` alone.
    """
    nt = num_threads(dims, lsu)
    if nt <= 0:
        return None
    vgpr = per_thread_vgpr(ch, tt0, tt1)
    if not vgpr:
        return None
    if VGPR_PER_CU // nt < vgpr:
        return _occupancy_limit_rejection(ch, tt0, tt1, vgpr, nt)
    return None


def _lds_reduction_check(config, ch, mt0, mt1, lsu) -> str | None:
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


def refuses_workgroup_register_file(config: dict[str, Any]) -> bool | None:
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


def refuses_per_thread_occupancy_limit(config: dict[str, Any]) -> bool | None:
    """The per-thread occupancy limit (Tensile's error 4) as a predicate.

    ``None`` when the config cannot be modelled (unreadable tile dims), else
    whether the EMITTED per-thread VGPRs do not fit ``65536 // NumThreads``.

    This is the rule that was *probed and rejected* on 2026-10-18 and
    **adopted** on 2026-10-21: the probe said it would refuse one phase
    Tensile built (complex Z tt2x2 at 64x64, 1024 threads, "71 VGPRs"), but
    the measured value was wrong -- that kernel emits **63** VGPRs (read out
    of its own code object), which fits the 64 VGPRs/thread a 1024-thread
    workgroup has. With the measured table corrected, the rule refuses
    exactly the phases that die: SS 256x128 at tt8x4 (77 VGPRs/thread over
    1024 threads), the 8 phases of run_20261020_214103 that errored out.
    """
    dims = tile_dims(config)
    if not dims:
        return None
    _mt0, _mt1, tt0, tt1 = dims
    nt = num_threads(dims, local_split_u(config))
    if nt <= 0:
        return None
    vgpr = per_thread_vgpr(dtype_char(config), tt0, tt1)
    if not vgpr:
        return None
    return VGPR_PER_CU // nt < vgpr


def refuses_lds_reduction_buffer(config: dict[str, Any]) -> bool | None:
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


