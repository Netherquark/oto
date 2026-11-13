"""The LDS-pad and swizzle group-C legality gate.

Owns: ``ldspad_feasible`` -- the CPU-only model of the padded-LDS footprint
and the coupled StaggerU/StaggerUMapping/StaggerUStride domains -- plus the
``STAGGER_*`` domains (Tensile Common.py:945-947) it enforces. Conclusions
from the measured evidence: a LdsPad/AssertFree/StaggerUStride value the
gate cannot prove legal is refused at the launch boundary, never forwarded
to a mid-run error 4.

Imports the shared tile/dtype helpers from ``oto.tensile.gates.occupancy_common``.
"""

from __future__ import annotations

from typing import Any

import oto.device.peaks as _peaks

from .memo import memo_gate
from .occupancy_common import dtype_char, tile_dims
from .vgpr_model import BYTES_PER_ELEMENT, LDS_BUDGET, depth_u

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

def _pads_feasible(config: dict[str, Any], ku: int,
                    bpe: int | None) -> tuple[bool, str]:
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


def _int_or_reject(value, label: str) -> tuple[int | None, str | None]:
    """Parse an int knob, or produce the reject text for a non-integer one."""
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"{label} must be an integer (have {value!r})"


def _swizzle_domain_check(config: dict[str, Any]) -> str | None:
    """The three swizzle knobs' own domains, or None when they are legal.

    Tensile's domains (Common.py:945-947): StaggerU in {0,2,4,8,16,32,64},
    StaggerUMapping in {0,1,2,3,4}, StaggerUStride in
    {0,16,32,64,128,256,512,1024,2048}.
    """
    for key, domain, cite in (
            ("StaggerU", STAGGER_U_DOMAIN, "945"),
            ("StaggerUMapping", STAGGER_MAPPING_DOMAIN, "946"),
            ("StaggerUStride", STAGGER_STRIDE_DOMAIN, "947")):
        value = config.get(key)
        if value is None:
            continue
        parsed, err = _int_or_reject(value, key)
        if err or parsed not in domain:
            return (f"{key}={parsed} outside Tensile domain {domain} "
                    f"(Common.py:{cite})")
    return None


def _swizzle_feasible(config: dict[str, Any], ku: int,
                       bpe: int | None) -> tuple[bool, str]:
    """The coupled StaggerU / StaggerUMapping / StaggerUStride domains.

    Tensile source (SolutionStructs:3326-3342, Common.py:945-947, 1599-1601):

      * StaggerUStride=0 is only valid if StaggerU=0 -- the ONE reject.
      * StaggerU=0 FORCES StaggerUMapping=0 and StaggerUStride=0
        (":3334-3336"); it does not reject them.
      * StaggerUStride>0 requires staggerStrideShift = ceil(log2(SUS/(DU*bpe)))
        >= 0, i.e. SUS > 0.5*DepthU*bpeAB (the ":3342" reject). Tensile then
        internally raises SUS to a whole multiple of DepthU*bpe.
      * Legal domains: SU in :data:`STAGGER_U_DOMAIN`, SUM in
        :data:`STAGGER_MAPPING_DOMAIN`, SUS in :data:`STAGGER_STRIDE_DOMAIN`.
        SU requires BufferLoad==1 and is silently ignored otherwise.

    Why this was wrong until 2026-10-21: it read Tensile's FORCE as a reject
    ("StaggerUStride=256 requires StaggerU>0") and so refused every config with
    StaggerU=0 and the default stride 256. Tensile accepts those -- it zeroes
    the stride itself. The refusal was a false rejection that killed the whole
    "no-swizzle" arm: 14 deck rows (98 shape-records across the runs) were
    refused at the launch boundary as "skipped_illegal", so the axis was never
    measured at all.

    An earlier revision (2026-10-09) had the SUS bound BACKWARDS as well (it
    rejected SUS >= DepthU*bpe, i.e. exactly the legal swizzle values), which
    is why Group C swizzle forwarding was blocked -- every legal StaggerUStride
    was refused at the launch boundary. Corrected against the pinned checkout
    (Tensile commit e8a8999e).
    """
    domain = _swizzle_domain_check(config)
    if domain:
        return False, domain
    # Coupling. Tensile defaults SU=32 (absent SU = >0); absent SU = "stagger on".
    su_effective = (STAGGER_U_DEFAULT if config.get("StaggerU") is None
                    else int(config["StaggerU"]))
    stride_effective = (STAGGER_STRIDE_DEFAULT if config.get("StaggerUStride") is None
                        else int(config["StaggerUStride"]))

    if su_effective == 0:
        # Tensile FORCES the mapping and the stride to 0 here
        # (SolutionStructs:3334-3336). Whatever the config carried is
        # overwritten, not rejected -- so neither is a reason to refuse.
        return True, ""
    if stride_effective == 0:
        return False, (f"StaggerUStride=0 is only valid if StaggerU is 0 "
                       f"(have StaggerU={su_effective}; SolutionStructs:3325-3326)")
    if ku > 0 and bpe and stride_effective < ku * bpe:
        return False, (f"StaggerUStride={stride_effective} < DepthU({ku})*{bpe}B; "
                       f"Tensile requires StaggerUStride >= DepthU*BytesPerElement "
                       f"when StaggerU>0 (staggerStrideShift >= 0, SolutionStructs:3336-3342)")
    return True, ""


def _store_knobs_feasible(config: dict[str, Any]) -> tuple[bool, str]:
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

    # TransposeLDS is unreachable on this device, in BOTH of its non-zero values:
    #   * 1 is the MFMA path ("TransposeLds Supports only in
    #     MatrixInstruction=1", SolutionStructs:4519-4521) and the device has no
    #     MFMA (no v_mfma_*);
    #   * -1 forces UnrollMajorLDS on the non-transposed operand
    #     (":3874-3875"), and the classic (VALU) path rejects UnrollMajorLDS
    #     outright -- "didn't support UnrollMajorLDS in VALU mode yet"
    #     (":2890").
    # The deck check found the second one: a Z 32x32/2x2 phase with
    # TransposeLDS=-1 was refused by Tensile with exactly that message
    # (2026-10-22). The same reject applies to UnrollMajorLDSA/B and
    # LdsBlockSizePerPadA/B (":2890-2892"), which is why those two are
    # *unreachable* rather than "virgin" in the tuning guide's §9.1.
    tlds = config.get("TransposeLDS")
    if tlds is not None:
        tv, err = _int_or_reject(tlds, "TransposeLDS")
        if err:
            return False, err
        if tv == 1:
            return False, ("TransposeLDS=1 requires MatrixInstruction=1 "
                           f"(SolutionStructs:4519-4521) and {_peaks.CODENAME} has no MFMA")
        if tv == -1:
            return False, ("TransposeLDS=-1 forces UnrollMajorLDS, which the "
                           "classic (VALU) path rejects: 'didn't support "
                           "UnrollMajorLDS in VALU mode yet' "
                           "(SolutionStructs:2890)")
    return True, ""


@memo_gate
def ldspad_feasible(config: dict[str, Any], profile=None) -> tuple[bool, str]:
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
    if profile is None:
        return _ldspad_feasible_impl(config)
    from .vgpr_model import bound_profile as _bp
    with _bp(profile):
        return _ldspad_feasible_impl(config)


def _ldspad_feasible_impl(config: dict[str, Any]) -> tuple[bool, str]:
    """Body of :func:`ldspad_feasible` with any bound profile applied."""
    ku = depth_u(config)
    ch = dtype_char(config)
    bpe = BYTES_PER_ELEMENT.get(ch)

    # PrefetchGlobalRead=2 doubles the LDS prefetch buffer; gate it against
    # the same budget so a 2-deep prefetch cannot silently overflow LDS.
    pgr = config.get("PrefetchGlobalRead")
    if pgr is not None:
        try:
            pgr_i = int(pgr)
        except (TypeError, ValueError):
            return False, f"PrefetchGlobalRead must be an int (have {pgr!r})"
        if pgr_i == 2:
            dims = tile_dims(config)
            if dims and ku > 0 and bpe:
                mt0, mt1, _, _ = dims
                if (mt0 + mt1) * bpe * ku * 2 > LDS_BUDGET:
                    return False, (
                        f"PrefetchGlobalRead=2 needs a doubled LDS footprint "
                        f"({(mt0+mt1)*bpe*ku*2} > {LDS_BUDGET}) on this tile"
                    )

    for gate in (_pads_feasible, _swizzle_feasible):
        ok, reason = gate(config, ku, bpe)
        if not ok:
            return False, reason
    return _store_knobs_feasible(config)

