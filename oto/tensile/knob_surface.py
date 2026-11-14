#!/usr/bin/env python3
"""The launch-boundary knob surface: what Tensile may and may not receive.

Owns: the machine-readable forwarding surface -- ``GLOBAL_LOAD_WIDTH_KEYS``,
``FORWARDED_GROUP_C_KNOBS``, ``FORWARDED_KNOBS``, ``NOT_FORWARDED_KNOBS`` and
``DEPRECATED_KEYS`` -- as one testable artifact. The writer consults it to
decide what reaches Tensile; the deck consults it to strip-and-report the
knobs that would benchmark at defaults while their manifest claims the
treatment ran.
Does NOT own: the gates that make a forwarded value legal (oto.tensile.gates),
the YAML emission itself (oto.tensile.config_writer), or the contraction
pattern vocabulary (oto.tensile.contraction_patterns).
Public API: GLOBAL_LOAD_WIDTH_KEYS, FORWARDED_GROUP_C_KNOBS, FORWARDED_KNOBS,
NOT_FORWARDED_KNOBS, DEPRECATED_KEYS.

Why this is its own module: the forwarding surface is the contract between
the deck and Tensile, and it is the one list whose silent drift turns a
sweep into a placebo three times over (``GlobalReduceVectorWidth``, the LDS
pads, and StaggerUStride-forwarded-alone). One home, pinned by
``tests/test_writer_forwards_sweep_knobs.py``.
"""

from __future__ import annotations

#: Global load/reduce widths. Tensile defaults these when absent, and the default
#: can contradict the named VectorWidth -> solution rejected ("GlobalLoad
#: VectorWidthA 2 must be == VectorWidth 4 or == 1").
GLOBAL_LOAD_WIDTH_KEYS = ("GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
                          "GlobalReduceVectorWidth")

#: LDS-pad / RCT knobs forwarded verbatim, after the ldspad gate passes. They
#: used to be silently dropped here, so candidates carrying them benchmarked
#: WITHOUT the knob (the marginal-value audit found 167/167 reference kernels
#: carrying pads benchmarked with pads stripped to 0).
#: The swizzle axis (StaggerU / StaggerUMapping / StaggerUStride) is forwarded
#: as a COUPLED TRIO: Tensile rejects StaggerUStride=0 unless StaggerU=0
#: (SolutionStructs:3326-3327) and forces StaggerUMapping=0 + StaggerUStride=0
#: when StaggerU=0 (:3333-3334), so forwarding StaggerUStride alone -- the
#: pre-2026-10-09 state -- silently benchmarked every swizzle candidate at the
#: defaults.
FORWARDED_GROUP_C_KNOBS = ("LdsPadA", "LdsPadB", "AssertFree0ElementMultiple",
                           "StaggerU", "StaggerUMapping", "StaggerUStride",
                           "StoreCInUnroll")

#: Keys Tensile must never receive. ``GlobalReduceVectorWidth`` is not a Tensile
#: parameter at all, despite reference kernel metadata carrying it as ``grvw``;
#: emitting it is what killed all 127 T1 reference reruns at "Filling in
#: Parameters With Defaults" having executed zero phases.
DEPRECATED_KEYS = ("MacroTile0", "MacroTile1")

#: The COMPLETE forwarding surface: every Tensile ``ForkParameters`` name
#: ``_fork_params`` can emit and ``_drop_unsupported`` leaves in place. Declared
#: once so "is this knob real?" has a single, testable answer -- the deck became
#: a placebo three times (``GlobalReduceVectorWidth``, the LDS pads, and
#: StaggerUStride-forwarded-alone) precisely because the surface was only
#: *implied* by the fork helpers. ``tests/test_writer_forwards_sweep_knobs.py``
#: pins this tuple to them, and ``docs/potential_configs.md`` §R16 is its prose.
FORWARDED_KNOBS = ("ThreadTile", "MacroTile", "WorkGroup", "WorkGroupMapping", "GlobalSplitU", "DepthU", "VectorWidth", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB", "NumLoadsCoalescedA", "NumLoadsCoalescedB", "PrefetchGlobalRead", "PrefetchLocalRead", "UseSgprForGRO", "InnerUnroll", "MaxOccupancy", "AggressivePerfMode", "FractionalLoad", "NonTemporalA", "NonTemporalB", "NonTemporalC", "NonTemporalD", "AssertFree1ElementMultiple", "TransposeLDS", *FORWARDED_GROUP_C_KNOBS)

#: Valid Tensile parameters a builder may name, which the launch boundary does
#: NOT forward. A candidate carrying one would benchmark at the Tensile default
#: while its manifest claims the treatment ran -- a silent placebo. Declared so
#: the deck can strip-and-REPORT it (``candidate_rows._NOT_FORWARDED_YET``)
#: rather than no-op it, and so §R16/§R20 have one home for what is unreachable
#: today and what it would cost to reach it.
NOT_FORWARDED_KNOBS = (
    "WaveSeparateGlobalReadA", "WaveSeparateGlobalReadB",
    "ThreadSeparateGlobalReadA", "ThreadSeparateGlobalReadB",
    "1LDSBuffer", "UnrollMajorLDSA", "UnrollMajorLDSB",
    "LdsBlockSizePerPadA", "LdsBlockSizePerPadB",
    "DirectToVgprA", "DirectToVgprB",
    "GlobalReadPerMfma", "LocalWritePerMfma", "DepthULdsDivisor",
    "PersistentKernel",
)
