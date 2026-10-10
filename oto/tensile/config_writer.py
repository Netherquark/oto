#!/usr/bin/env python3
"""The launch-boundary config writer.

Owns: turning one phase dict into a Tensile Top-Level Config YAML, and refusing
before it is written when a CPU gate cannot prove legality. This is the one place
a knob becomes Tensile YAML, so it is the one place that has to answer for every
silent-drop bug in the project's history (GlobalReduceVectorWidth, dropped LDS
pads, dropped StaggerUStride).
Does NOT own: the gates it consults (oto.tensile.gates), the shape parser it
uses (oto.tensile.candidate.parse_tensile_shape), or the driver that calls it
(oto.runners.benchmark).
Public API: write_phase_config, TRANSPOSE_MAP, GLOBAL_LOAD_WIDTH_KEYS,
FORWARDED_GROUP_C_KNOBS, _TENSILE_VALID_PARAMS (re-exported from driver).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from oto.tensile.candidate import parse_tensile_shape
from oto.tensile.gates.assembly import assembly_class_valid
from oto.tensile.gates.occupancy import ldspad_defasible

#: Contraction pattern -> (TransposeA, TransposeB). Verified against Tensile
#: index notation and the corpus' own kernel names:
#: Ailk_Bljk -> NN, Ailk_Bjlk -> NT, Alik_Bljk -> TN, Alik_Bjlk -> TT.
#: A pattern that matches none of these falls back to NT, which is what the
#: reference metadata's own labels almost always mean.
TRANSPOSE_MAP = {
    "Ailk_Bljk": (False, False),
    "Ailk_Bjlk": (False, True),
    "Alik_Bljk": (True,  False),
    "Alik_Bjlk": (True,  True),
}

#: Patterns recognised in a label, in the order they are matched.
_PATTERNS = ("Ailk_Bljk", "Ailk_Bjlk", "Alik_Bljk", "Alik_Bjlk")

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
_DEPRECATED_KEYS = ("MacroTile0", "MacroTile1")


# ---------------------------------------------------------------- readers

def _pattern_of(label: str, explicit: Optional[str]) -> str:
    """Contraction pattern from the explicit field, else from the label.

    Why the label fallback exists: shipped reference metadata and deck entries
    carry the pattern in the label text rather than as a field, and a phase
    parsed as the wrong pattern silently benchmarks a different GEMM.
    """
    if explicit:
        return explicit
    for pat in _PATTERNS:
        if pat in label:
            return pat
    return ""


def _transposes(pattern: str) -> Tuple[bool, bool]:
    """(TransposeA, TransposeB) for a contraction pattern."""
    return TRANSPOSE_MAP.get(pattern, (False, True))          # default NT


def _exact_sizes(shapes: List[str]) -> List[List[int]]:
    """Problem sizes as Tensile ``Exact: [M, N, B, K]`` lists."""
    return [[(p := parse_tensile_shape(s))["M"], p["N"], p["B"], p["K"]]
            for s in shapes]


def _macro_tile(config: Dict[str, Any]) -> Tuple[Optional[int], Optional[int],
                                                 Optional[int]]:
    """(MacroTile0, MacroTile1, DepthU-from-string) from a config.

    Explicit MacroTile0/MacroTile1 keys win over the string; DepthU is only ever
    taken from the string's third field, because an explicit DepthU key is the
    caller's business (see _depth_u_of).
    """
    macro_tile_str = config.get("MacroTile", "")
    macro_tile0 = config.get("MacroTile0")
    macro_tile1 = config.get("MacroTile1")
    depth_u_from_macro = None
    if macro_tile_str and isinstance(macro_tile_str, str) and "x" in macro_tile_str:
        mt_parts = macro_tile_str.split("x")
        try:
            if macro_tile0 is None and len(mt_parts) >= 1:
                macro_tile0 = int(mt_parts[0])
            if macro_tile1 is None and len(mt_parts) >= 2:
                macro_tile1 = int(mt_parts[1])
            if len(mt_parts) >= 3:
                depth_u_from_macro = int(mt_parts[2])
        except ValueError:
            pass
    return macro_tile0, macro_tile1, depth_u_from_macro


def _thread_tile(config: Dict[str, Any]) -> Tuple[int, int]:
    """ThreadTile dims from a ``"T0xT1"`` string or a ``[T0, T1]`` list."""
    thread_tile = config.get("ThreadTile")
    tt0, tt1 = 4, 4
    if isinstance(thread_tile, str) and "x" in thread_tile:
        try:
            tt_parts = thread_tile.split("x")
            tt0, tt1 = int(tt_parts[0]), int(tt_parts[1])
        except (ValueError, IndexError):
            pass
    elif isinstance(thread_tile, list) and len(thread_tile) >= 2:
        tt0, tt1 = int(thread_tile[0]), int(thread_tile[1])
    return tt0, tt1


def _hpa_flags(label: str, config: Dict[str, Any]) -> Tuple[bool, bool]:
    """(is_hpa, is_hs_hpa) for a phase.

    Case-insensitive: deck labels are uppercase ("HH_HPA_...") while
    agent-mutated candidates are lowercase ("mutate_hh_hpa_..."). Without this,
    HPA mutants silently lost HighPrecisionAccumulate / DestDataType and
    benchmarked as plain FP16.
    """
    is_hpa = ("HPA" in label.upper()
              or "HPA" in str(config.get("ProblemType", "")).upper()
              or "HPA" in str(config.get("FamilyLabel", "")).upper())
    is_hs_hpa = ("HS_HPA" in label.upper()
                 or "HS_HPA" in str(config.get("FamilyLabel", "")).upper())
    return is_hpa, is_hs_hpa


# --------------------------------------------------------------- assembly

def _problem_type(dtype: str, transpose_a: bool, transpose_b: bool,
                  is_hpa: bool, is_hs_hpa: bool) -> Dict[str, Any]:
    """The ``ProblemType`` block of a BenchmarkProblems entry."""
    problem_type: Dict[str, Any] = {
        "OperationType": "GEMM",
        "DataType": dtype,
        "TransposeA": transpose_a,
        "TransposeB": transpose_b,
        "UseBeta": True,
        "Batched": True,
    }
    if is_hpa or is_hs_hpa:
        problem_type["HighPrecisionAccumulate"] = True
    if is_hs_hpa:
        problem_type["DestDataType"] = "s"
        problem_type["ComputeDataType"] = "s"
    return problem_type


def _fork_params(config: Dict[str, Any], tt0: int, tt1: int,
                 macro_tile0: Optional[int], macro_tile1: Optional[int],
                 depth_u_from_macro: Optional[int]) -> Dict[str, Any]:
    """The ``ForkParameters`` list, in a stable order so a config is
    diff-reviewable across runs.

    Each block below is a knob that used to be dropped, dropped wrongly, or
    defaulted into contradiction. The comments are the history.
    """
    fork: Dict[str, Any] = {}

    fork["ThreadTile"] = [[tt0, tt1]]

    # Tensile ForkParameters requires MacroTile: [[M0, M1]] (no DepthU here).
    if macro_tile0 is not None and macro_tile1 is not None:
        fork["MacroTile"] = [[int(macro_tile0), int(macro_tile1)]]

    # WorkGroup: explicit > computed from MacroTile/ThreadTile > default
    if "WorkGroup" in config and isinstance(config["WorkGroup"], list):
        fork["WorkGroup"] = [config["WorkGroup"]]
    elif macro_tile0 is not None and macro_tile1 is not None and tt0 and tt1:
        fork["WorkGroup"] = [[macro_tile0 // tt0, macro_tile1 // tt1, 1]]
    else:
        fork["WorkGroup"] = [[16, 16, 1]]

    if "WorkGroupMapping" in config:
        fork["WorkGroupMapping"] = [int(config["WorkGroupMapping"])]
    else:
        fork["WorkGroupMapping"] = [4]

    if "GlobalSplitU" in config:
        fork["GlobalSplitU"] = [int(config["GlobalSplitU"])]
    else:
        fork["GlobalSplitU"] = [1]

    # DepthU: explicit > from MacroTile string > default
    if "DepthU" in config:
        fork["DepthU"] = [int(config["DepthU"])]
    elif depth_u_from_macro is not None:
        fork["DepthU"] = [depth_u_from_macro]
    else:
        fork["DepthU"] = [16]

    if "VectorWidth" in config:
        fork["VectorWidth"] = [int(config["VectorWidth"])]

    for key in GLOBAL_LOAD_WIDTH_KEYS:
        if key in config:
            fork[key] = [int(config[key])]

    nlca = config.get("NLCA", config.get("NumLoadsCoalescedA"))
    if nlca is not None:
        fork["NumLoadsCoalescedA"] = [int(nlca)]

    for key in ("PrefetchGlobalRead", "PrefetchLocalRead"):
        if key in config:
            fork[key] = [bool(config[key])]

    for key in FORWARDED_GROUP_C_KNOBS:
        if key in config:
            fork[key] = [config[key]]

    return fork


def _drop_unsupported(fork_params: Dict[str, Any],
                      valid_params, not_tensile_param) -> List[str]:
    """Drop parameter names this Tensile does not know about; return the names.

    Tensile's checkParametersAreValid() calls printExit() -- it aborts the whole
    phase -- for any unrecognised name, so one stale key is fatal and silent
    until you read the phase log.
    """
    unknown = sorted(k for k in fork_params
                    if k not in valid_params or k in not_tensile_param)
    for key in unknown:
        fork_params.pop(key)
    return unknown


def _global_parameters(schedule_name: str,
                       num_benchmarks: int) -> Dict[str, Any]:
    """The fixed ``GlobalParameters`` block. CpuThreads is the only variable."""
    return {
        "MinimumRequiredVersion": "4.4.0",
        "PrintLevel": 1,
        "ForceRedoBenchmarkProblems": True,
        "ForceRedoLibraryLogic": True,
        "ForceRedoLibraryClient": True,
        "CMakeBuildType": "Release",
        "EnqueuesPerSync": 1,
        "SyncsPerBenchmark": 1,
        "LibraryPrintDebug": False,
        "NumElementsToValidate": 0,
        "ValidationMaxToPrint": 4,
        "ValidationPrintValids": False,
        "ShortNames": False,
        "MergeFiles": True,
        "Platform": 0,
        "Device": 0,
        "KernelTime": True,
        "PinClocks": False,
        "SleepPercent": 50,
        "PrintSolutionRejectionReason": True,
        "DataInitTypeBeta": 0,
        "HardwareMonitor": False,
        "CpuThreads": cpu_threads(),
        "ScheduleName": schedule_name,
        "NumBenchmarks": num_benchmarks,
    }


def cpu_threads(config: Optional[Dict[str, Any]] = None) -> int:
    """Multi-threaded compilation threads: available CPUs, capped at 16.

    Why capped: Tensile's own CpuThreads scales the client build, and a 128-core
    host oversubscribes the assembler badly enough to slow the whole phase down.
    """
    if config and "CpuThreads" in config:
        return int(config["CpuThreads"])
    return int(min(os.cpu_count() or 8, 16))


# -------------------------------------------------------------- main entry

def _launch_gate_refusal(driver, phase: Dict[str, Any]
                         ) -> Optional[str]:
    """CPU legality refusal text, or None when the phase may launch.

    Three gates, all CPU-only, all refusing before a config file is written.
    Why here and not by convention: Tensile's own rejection surfaces as an opaque
    "Generating kernel source resulted in error 4" that looks like the kernel
    rather than the parameterisation. The occupancy gate is the one that caught
    all 8 dead ZZ phases; the assembly-class gate is the one that caused the
    121-config rc=1 bucket; the forwarded-knob gate is the one that stopped a
    pad or a stride from being silently dropped.

    gate_config merges the phase-level dtype/label into the config so each
    predicate sees a complete FamilyLabel/label/DataType triple.
    """
    config = phase.get("config", {})
    label = phase.get("label", "")
    dtype = phase.get("dtype", "S").lower()
    gate_config = {**config, "DataType": dtype, "label": label}
    for gate_name, gate in (("assembly-class", assembly_class_valid),
                            ("occupancy", _occupancy)):
        gate_ok, gate_reason = gate(gate_config)
        if not gate_ok:
            print(f"Skipping {phase.get('phase_id', 'phase_unknown')}: "
                  f"{gate_name} illegal ({gate_reason})")
            return f"{gate_name} illegal: {gate_reason}"

    pad_ok, pad_reason = ldspad_defasible(gate_config)
    if not pad_ok:
        print(f"Skipping {phase.get('phase_id', 'phase_unknown')}: "
              f"forwarded-knob illegal ({pad_reason})")
        return f"forwarded-knob illegal: {pad_reason}"
    return None


def _occupancy(config: Dict[str, Any]) -> Tuple[bool, str]:
    """The occupancy gate, imported lazily so this module stays import-cheap."""
    from oto.tensile.gates.occupancy import occupancy_feasible

    return occupancy_feasible(config)


def write_phase_config(driver, path: Path,
                       phase: Dict[str, Any]) -> Tuple[bool, str]:
    """Write a valid Tensile Top-Level Config (GlobalParameters + BenchmarkProblems).

    Args:
        driver: The TensileDriver, used for the Tensile parameter snapshot and to
            locate nothing else -- the writer deliberately reads no other driver
            state so it can be exercised offline.
        path: The YAML file to write.
        phase: One phase dict from the manifest.

    Returns:
        ``(True, "")`` when a config was written, or ``(False, reason)`` when a
        CPU legality gate refused the phase before any GPU work. Callers MUST
        honour the False: the caller used to ignore the early return, so rejected
        phases still launched Tensile against a config that did not exist, and
        Tensile then failed with its own rejection reason (121 phases: GSU/AF0EM
        gate) -- which looked like a kernel problem and buried the real cause.
    """
    from oto.runners.driver import NOT_A_TENSILE_PARAM, _TENSILE_VALID_PARAMS

    refusal = _launch_gate_refusal(driver, phase)
    if refusal:
        return False, refusal

    label = phase.get("label", "")
    dtype = phase.get("dtype", "S").lower()
    schedule_name = phase.get("ScheduleName", "isa")
    num_benchmarks = phase.get("NumBenchmarks", 8)
    config = phase.get("config", {})
    shapes = phase.get("shapes", ["1024x1024x1024"])

    pattern = _pattern_of(label, phase.get("contraction_pattern"))
    transpose_a, transpose_b = _transposes(pattern)
    exact_sizes = _exact_sizes(shapes)
    macro_tile0, macro_tile1, depth_u_from_macro = _macro_tile(config)
    tt0, tt1 = _thread_tile(config)
    is_hpa, is_hs_hpa = _hpa_flags(label, config)

    fork_params = _fork_params(config, tt0, tt1, macro_tile0, macro_tile1,
                              depth_u_from_macro)

    # Remove deprecated keys, then anything this Tensile does not know.
    for key in _DEPRECATED_KEYS:
        fork_params.pop(key, None)
    for key in _drop_unsupported(fork_params, _TENSILE_VALID_PARAMS,
                                 NOT_A_TENSILE_PARAM):
        print(f"[cfg] dropping parameter {key!r} not supported by this Tensile")

    fork_list = [{k: v} for k, v in fork_params.items()]

    benchmark_common = [
        {"KernelLanguage": ["Assembly"]},
        {"EdgeType": ["ShiftPtr"]},
        {"LoopTail": [True]},
    ]

    benchmark_group = {
        "InitialSolutionParameters": None,
        "BenchmarkCommonParameters": benchmark_common,
        "ForkParameters": fork_list,
        "BenchmarkForkParameters": None,
        "JoinParameters": None,
        "BenchmarkJoinParameters": None,
        "BenchmarkFinalParameters": [
            {
                "ProblemSizes": [{"Exact": size} for size in exact_sizes]
            }
        ],
    }

    tensile_yaml = {
        "GlobalParameters": _global_parameters(schedule_name, num_benchmarks),
        "BenchmarkProblems": [
            [
                _problem_type(dtype, transpose_a, transpose_b, is_hpa, is_hs_hpa),
                benchmark_group,
            ]
        ],
    }

    with open(path, "w") as f:
        yaml.safe_dump(tensile_yaml, f, default_flow_style=False, sort_keys=False)
    return True, ""
