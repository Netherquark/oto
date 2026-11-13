"""The measured VGPR model: tables and budgets the occupancy gate cites.

Owns: the numbers the register-file gate needs and cannot derive -- the global
load byte cap, the family bytes-per-element table, the per-dtype VGPR weights,
the accumulator VGPR budget, the LDS budgets (per-workgroup tile and per-CU
allocator), the compute-dtype byte table, and the two measured VGPR tables read
out of Tensile's own kernel writer. Also the config readers those numbers need
(``depth_u``, ``lds_base_bytes``, ``measured_accvgpr``, ``local_split_u``,
``num_threads``, ``is_hpa``, ``compute_bytes``).
Does NOT own: the pass/fail decision (oto.tensile.gates.occupancy) or the
legality classes (oto.tensile.gates.assembly).
Public API: GLOBAL_LOAD_BYTE_CAP, FAMILY_BYTES_PER_ELEMENT, VGPR_PER_CU,
MAX_VGPR_PER_THREAD, VGPR_PER_ELEMENT, ACCVGPR_BUDGET, LDS_BUDGET,
MAX_LDS_BYTES, BYTES_PER_ELEMENT, COMPUTE_BYTES_PER_ELEMENT, VGPR_BUDGET,
LDS_PER_CU_KB,
MEASURED_VGPR, MEASURED_VGPR_BY_DTYPE, measured_accvgpr, depth_u,
lds_base_bytes, local_split_u, num_threads, per_thread_vgpr, is_hpa,
compute_bytes, set_profile, restore_profile, bound_profile.
"""

from __future__ import annotations

import contextlib
from typing import Any

#: Bytes in the widest global load the classic (non-MFMA) path allows. Tensile
#: enforces this at SolutionStructs:3460 (`GLVW * bytesPerElement <= 16`), and
#: `validate_tensile_loads` rejects anything above it. (Refactor 2: sourced
#: from the default profile; module global kept for backward compat.)
try:
    from oto.device.loader import default_profile as _vgpr_dp
    GLOBAL_LOAD_BYTE_CAP = _vgpr_dp().global_load_byte_cap
except Exception:  # pragma: no cover
    GLOBAL_LOAD_BYTE_CAP = 16


_TRACKED = ("GLOBAL_LOAD_BYTE_CAP", "VGPR_PER_CU", "LDS_PER_CU_KB")

#: Gate modules that captured a profile-derived name with
#: ``from .vgpr_model import X`` at import time (the plain name in their
#: module namespace is a snapshot, so rebinding *our* globals would leave the
#: gates reading the gfx90c value). set_profile/restore_profile rebind these
#: module globals too; restore reverses them exactly. Only profile-derived
#: names are listed -- calibrated constants (LDS_BUDGET, MAX_LDS_BYTES,
#: ACCVGPR_BUDGET) stay fixed by design.
_DOWNSTREAM: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("oto.tensile.gates.occupancy", ("VGPR_PER_CU",)),
    ("oto.tensile.gates.loads", ("GLOBAL_LOAD_BYTE_CAP",)),
)


def _downstream_modules():
    import importlib
    for path, names in _DOWNSTREAM:
        try:
            yield importlib.import_module(path), names
        except Exception:  # pragma: no cover - a gate module must import cleanly
            continue


def set_profile(profile) -> dict[str, Any]:
    """Re-bind the module-level device constants to ``profile`` (Refactor 2).

    Returns the previous bindings so a scoped call site can
    :func:`restore_profile` them; the default (module-init) state is what a
    restore brings back. Also rebinds the import-time snapshots held by the
    gate modules (see ``_DOWNSTREAM``), or the bound profile would silently
    change nothing a gate reads.
    """
    global GLOBAL_LOAD_BYTE_CAP, VGPR_PER_CU, LDS_PER_CU_KB
    previous = {name: globals()[name] for name in _TRACKED}
    try:
        for mod, names in _downstream_modules():
            for name in names:
                if hasattr(mod, name):
                    previous[f"{mod.__name__}.{name}"] = getattr(mod, name)
        GLOBAL_LOAD_BYTE_CAP = profile.global_load_byte_cap
        VGPR_PER_CU = profile.vgpr_per_cu
        LDS_PER_CU_KB = profile.lds_per_cu_kb
        for mod, names in _downstream_modules():
            for name in names:
                if name in globals():
                    setattr(mod, name, globals()[name])
    except Exception:
        pass
    return previous


def restore_profile(state: dict[str, Any]) -> None:
    """Restore the bindings :func:`set_profile` replaced (Refactor 2)."""
    import importlib

    for key, value in state.items():
        if "." in key:
            mod_name, _, name = key.rpartition(".")
            try:
                setattr(importlib.import_module(mod_name), name, value)
            except Exception:  # pragma: no cover
                pass
        else:
            globals()[key] = value


@contextlib.contextmanager
def bound_profile(profile):
    """Scope ``set_profile`` to the ``with`` block; restore on exit."""
    state = set_profile(profile)
    try:
        yield
    finally:
        restore_profile(state)

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
try:
    from oto.device.loader import default_profile as _vgpr_dp2
    VGPR_PER_CU = _vgpr_dp2().vgpr_per_cu
    LDS_PER_CU_KB = _vgpr_dp2().lds_per_cu_kb
except Exception:  # pragma: no cover
    VGPR_PER_CU = 65536
    LDS_PER_CU_KB = 64
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
#: Measured complex (Z, 8 B) boundary on the device: 16384 legal, 20480 dead
#: (128x32x16 needs 106496 B and is rejected). Deliberately conservative: it may
#: refuse a config Tensile would accept, never admits one Tensile refuses.
LDS_BUDGET = 16384
#: Bytes per element for the LDS footprint, by dtype char. This is Tensile's
#: own ``DataType.numBytes()`` (= ``properties['reg'] * 4``) -- EXCEPT "Z", which
#: is deliberately left at half that value. See DECISION REQUIRED in
#: <codename>_theoretical_limits.md §6: complex double is 4 registers = 16 bytes in
#: Tensile/DataType.py:82 (and FAMILY_BYTES_PER_ELEMENT agrees, "ZZ": 16), but
#: LDS_BUDGET below was calibrated against the 8-byte value, so correcting this
#: entry alone would reject ZZ configs Tensile builds and runs. The two must be
#: decided together. A f64 element is 8 bytes but 2 accumulator VGPRs (per
#: element); a complex f64 element is 8 accumulator VGPRs and 16 LDS bytes.
#:
#: The *global-load* half of that decision is now settled and does NOT live here:
#: the classic-load gate has its own table, ``gates.loads.LOAD_DTYPE_INFO``, whose
#: ``Z`` row reads ComplexDouble's 4 registers / 16 bytes, so the 16 B load cap
#: refuses ZZ VectorWidth 2 (see potential_configs.md §R23). This LDS table stays
#: at 8 because LDS_BUDGET was calibrated against it.
BYTES_PER_ELEMENT = {"S": 4, "D": 8, "H": 2, "B": 1, "I8": 1, "C": 8, "Z": 8}
#: Retained for the workgroup estimate: budget is expressed in accumulators, and
#: the register file is shared by every thread in a workgroup.
VGPR_BUDGET = VGPR_PER_CU // 2


#: Tensile's ``globalParameters["MaxLDS"]`` -- the *per-CU* LDS allocator ceiling,
#: 64 KiB. Distinct from :data:`LDS_BUDGET`, which is the conservative
#: per-workgroup tile proxy of 16 KiB. The two must not be conflated: the tile
#: proxy is deliberately conservative (it may refuse a config Tensile accepts),
#: whereas this is the exact number Tensile compares against at
#: SolutionStructs:4334, so a rule built on it is sound in both directions.
MAX_LDS_BYTES = 65536

#: ``ComputeDataType.numBytes()`` per assembly dtype char. Drives the LDS
#: reduction buffer (``multiplier = bytesPerComElem // bytesPerLoadElem``,
#: SolutionStructs:4104-4108), whose footprint in bytes simplifies to
#: ``LocalSplitU * MT0 * MT1 * compute bytes`` because the multiplier cancels the
#: load element size. Half defaults to 2 (half accumulate); ``compute_bytes``
#: raises it to 4 when the config is HPA (f32 accumulate).
COMPUTE_BYTES_PER_ELEMENT = {
    "S": 4, "D": 8, "H": 2, "B": 2, "I8": 1, "I1": 1, "C": 8, "Z": 16,
}

#: Measured per-thread VGPR totals from Tensile's own kernel writer on the device,
#: reported by check_tensile_build.py. (threadtile, accvgpr, observed total).
#: Every entry satisfies: total = accvgpr + a small tile-dependent overhead, and
#: the pass/fail boundary is exactly accvgpr > 128 for complex.
MEASURED_VGPR = {
    (2, 2): 63, (4, 2): 95, (2, 4): 99, (4, 4): 154,
    (2, 8): 171, (8, 4): 271, (8, 8): 519,
}

#: Measured TOTAL per-thread VGPRs (kernarg + operand + accumulator), read
#: 2026-10-21 from the run corpus' emitted code objects with
#: `python3 -m oto.harness.measure_vgprs` (llvm-readelf on the Tensile assembly
#: .o metadata, CPU-only) over 4419 code objects. These are the corpus MEDIANs
#: per (dtype, thread tile): a median, not a worst case, because the occupancy
#: gate needs a representative number -- a pessimistic one refuses kernels
#: Tensile builds (Z 2x2 measures 63, not 71, and a 64x64/2x2 workgroup of
#: 1024 threads has exactly 64 VGPRs/thread to spend). Prefer the dtype-keyed
#: table over MEASURED_VGPR (which is the weight-8 complex table used when no
#: dtype is in hand).
MEASURED_VGPR_BY_DTYPE = {
    "S": {(2, 2): 24, (2, 4): 43, (4, 2): 43, (4, 4): 47, (4, 6): 65,
          (4, 8): 77, (6, 4): 65, (6, 6): 83, (8, 4): 77, (8, 8): 113,
          (8, 16): 199, (16, 8): 199},
    "D": {(2, 2): 35, (2, 4): 53, (4, 2): 53, (4, 4): 79, (4, 8): 131,
          (8, 4): 131, (8, 8): 215},
    "H": {(2, 2): 21, (4, 4): 35, (4, 8): 57, (6, 6): 48, (8, 4): 57,
          (8, 8): 65, (8, 16): 105, (16, 8): 105},
    "C": {(2, 2): 39, (2, 4): 59, (4, 2): 59, (4, 4): 79, (4, 8): 134,
          (8, 4): 134},
    "Z": {(2, 2): 63, (2, 4): 99, (4, 2): 99, (2, 8): 171, (4, 4): 167},
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


def depth_u(config: dict) -> int:
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
            return max(0, ku)
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


def knob_int(value: Any, default: int) -> int:
    """`int(value)`, treating absent / None / unusable as `default`.

    A gate must return a verdict, never raise. A config dict can carry a key
    with a None value -- a knob present in the template but unset -- and
    ``int(None)`` raises ``TypeError``, which escapes the launch boundary and
    becomes exactly the opaque mid-run failure these gates exist to prevent.
    Found by `verify_gate_differential`: the pre-refactor gate returned a
    verdict for ``NLCA: None`` and this one raised.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_hpa(config: dict[str, Any]) -> bool:
    """True when the config accumulates half inputs in f32 (the HPA class).

    Reads Tensile's own key first, then the family label -- the two places the
    class is recorded. Shared by the compute-byte reader here and the
    GlobalSplitU class rule (oto.tensile.gates.assembly), so the two cannot
    disagree about which family a config belongs to.
    """
    return bool(config.get("HighPrecisionAccumulate", False)) or (
        "HPA" in str(config.get("FamilyLabel", "")).upper()
        or "HPA" in str(config.get("label", "")).upper()
    )


def compute_bytes(config: dict[str, Any], ch: str) -> int:
    """``ComputeDataType.numBytes()`` for a config's dtype char, or 0 if unknown.

    Half with f32 accumulate (HPA) computes in f32, so it returns 4, not 2. The
    complex chars carry their own width (C 8, Z 16); an unknown char returns 0 so
    a caller sees "cannot model" rather than a falsely small reduction buffer.
    """
    if ch == "H" and is_hpa(config):
        return 4
    return COMPUTE_BYTES_PER_ELEMENT.get(ch, 0)


def local_split_u(config: dict[str, Any]) -> int:
    """LocalSplitU as Tensile will actually receive it (SolutionStructs:1958).

    Tensile has no standalone ``LocalSplitU`` key: it reads the workgroup's third
    element. ``config_writer._fork_tile`` emits an explicit ``WorkGroup``
    verbatim and only folds the ``LocalSplitU`` key in when WorkGroup is absent,
    so an explicit ``WorkGroup: [16,16,1]`` *shadows* a ``LocalSplitU: 2`` beside
    it and the knob is then a silent no-op (potential_configs.md §R23). The gate
    models the emitted config, because that is the one Tensile judges -- reading
    the intent instead would refuse phases Tensile builds.

    This reader lives here, with the other config readers (``depth_u``,
    ``lds_base_bytes``), because both the load-divisibility gate and the
    register/LDS feasibility gate need the same NumThreads multiplier.
    """
    wg = config.get("WorkGroup")
    third: Any = None
    if isinstance(wg, (list, tuple)) and len(wg) >= 3:
        third = wg[2]
    elif isinstance(wg, str) and "x" in wg:
        parts = wg.lower().split("x")
        if len(parts) >= 3:
            third = parts[2]
    if third is None:
        third = config.get("LocalSplitU")
    try:
        return max(1, int(third))
    except (TypeError, ValueError):
        return 1


def num_threads(dims: tuple[int, int, int, int], lsu: int) -> int:
    """NumThreads = (MT0/TT0) * (MT1/TT1) * LocalSplitU (SolutionStructs:1964).

    Args:
        dims: ``(MT0, MT1, TT0, TT1)`` from :func:`tile_dims`.
        lsu: LocalSplitU from :func:`local_split_u`.

    Returns:
        The workgroup's thread count, or 0 when any tile dim is non-positive so
        the caller fails closed instead of dividing by zero.
    """
    mt0, mt1, tt0, tt1 = dims
    if min(mt0, mt1, tt0, tt1) <= 0:
        return 0
    return (mt0 // tt0) * (mt1 // tt1) * lsu


def per_thread_vgpr(ch: str, tt0: int, tt1: int) -> int:
    """The kernel's per-thread VGPR count, as Tensile would emit it.

    Tensile's error-4 test (``KernelWriterAssembly.functionSuffix``) is

        vgprPerThreadPerOccupancy = 65536 // NumThreads
        numWorkGroupsPerCU = vgprPerThreadPerOccupancy // max(vgpr, agpr)
        if numWorkGroupsPerCU < 1: overflowedResources = 4

    so the *emitted* per-thread VGPR count -- not just the accumulators -- has
    to fit in ``65536 // NumThreads``. The classic (non-MFMA) path has no arch
    accumulator registers, so ``agpr`` is 0 and the test is on ``vgpr`` alone.

    Args:
        ch: The dtype char ("S", "D", "H", "C", "Z").
        tt0, tt1: The thread-tile dimensions.

    Returns:
        The measured per-thread VGPR total when the corpus has one for this
        (dtype, thread tile), else a conservative upper bound (the
        accumulators plus the largest operand overhead ever measured for this
        dtype) so the caller errs toward refusing, never toward admitting an
        error-4 kernel.
    """
    measured = (MEASURED_VGPR_BY_DTYPE.get(ch) or {}).get((tt0, tt1))
    if measured is not None:
        return measured
    weight = VGPR_PER_ELEMENT.get(ch)
    if not weight:
        return 0
    acc = tt0 * tt1 * weight
    return acc + _max_operand_overhead(ch)


def _max_operand_overhead(ch: str) -> int:
    """The largest (measured total - accumulators) ever seen for a dtype.

    The operand fragments (A/B tiles, addresses, the alpha/beta path) cost more
    VGPRs than the accumulators alone, and the cost grows with the thread
    tile. For an unmeasured thread tile the largest observed overhead is the
    only defensible bound: it may refuse a kernel Tensile would accept, but it
    never admits one Tensile refuses with error 4.
    """
    weight = VGPR_PER_ELEMENT.get(ch) or 0
    overheads = [total - (tt0 * tt1 * weight)
                 for (tt0, tt1), total in
                 (MEASURED_VGPR_BY_DTYPE.get(ch) or {}).items()]
    return max(overheads) if overheads else 0

