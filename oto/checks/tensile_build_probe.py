#!/usr/bin/env python3
"""The Tensile-side proof machinery for the tensile-build check.

Owns: everything that talks to the Tensile Python API -- initialising Tensile's
global parameters the way ``Tensile/Tensile.py main()`` does, and driving the
solution -> ``KernelWriterAssembly.getSourceFileString`` pipeline over one phase
config to report Tensile's own verdict (never the calibrated model's). No GPU
work happens anywhere in this module.
Does NOT own: the phase orchestration, progress display or CLI (that is
:mod:`oto.checks.tensile_build`).
Public API: probe_phase_config (the driver re-exports it).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from oto import yamlio  # noqa: E402
REPO = Path(__file__).resolve().parents[2]
DEFAULT_TENSILE_ROOT = Path(
    os.environ.get("TENSILE_ROOT", "")
) if os.environ.get("TENSILE_ROOT") else None

# Tensile's own error vocabulary, from KernelWriterAssembly.kernelBody.
ERR_MSG = {
    0: "ok",
    1: "too many vgprs",
    2: "too many sgprs",
    3: "half store requires >=2 elements per batch",
    4: "Occupancy limit",
    5: "reading and writing LDS at same time require 2 LDS buffer",
    6: "SIA2 better with occupancy 2",
    7: "too many accvgprs",
}


# --------------------------------------------------------------------------
# Tensile setup. Mirrors Tensile/Tensile.py main() -> assignGlobalParameters,
# because that function insists on a fully validated toolchain.
# --------------------------------------------------------------------------
def _default_arch() -> str:
    """The Tensile arch default: the resolved device profile's codename."""
    from oto.device.loader import default_profile
    return default_profile().codename


def _init_tensile(arch: Optional[str] = None) -> None:
    if arch is None:
        arch = _default_arch()
    tensile_root = _require_tensile_root()
    sys.path.insert(0, str(tensile_root))
    os.environ.setdefault("ROCM_PATH", "/usr")

    import Tensile.Common as Common
    from Tensile.Utilities.Toolchain import ToolchainDefaults, validateToolchain

    assembler = shutil.which("clang++") or ""
    cxx, cc, asm, bundler, hipconfig, dev_enum = validateToolchain(
        "hipcc",
        "hipcc",
        assembler,
        ToolchainDefaults.OFFLOAD_BUNDLER,
        ToolchainDefaults.HIP_CONFIG,
        ToolchainDefaults.DEVICE_ENUMERATOR,
    )

    Common.assignGlobalParameters(
        {
            # We never benchmark. Say so explicitly so nobody mistakes this
            # for a performance run.
            "PrintLevel": 1,
            "PrintSolutionRejectionReason": True,
            "PrintWinnersOnly": False,
            "WorkingPath": os.getcwd(),
            "BenchmarkProblemsPath": "BP",
            "BenchmarkDataPath": "BD",
            "SolutionParamsPath": "Solutions",
            "LibraryDirPath": "lib",
            "KernelTime": False,
            "ShortNames": False,
            "MergeFiles": False,
            "RemoveTemporariesFromAssembler": False,
            "CxxCompiler": cxx,
            "CCompiler": cc,
            "Assembler": asm,
            "OffloadBundler": bundler,
            "HipConfig": hipconfig,
            "ROCmAgentEnumeratorPath": dev_enum,
        }
    )

    # Detection reads the device to pick the ISA. This is a path/enumeration
    # query, not a workload, but pin the ISA anyway so the proof is explicitly
    # about the arch we ported and so the tool still works with no GPU present.
    import Tensile.Common as Common2

    from oto.device.tensile_isa import isa_triple
    isa = isa_triple(arch)
    if isa is not None:
        Common2.globalParameters["CurrentISA"] = isa


def _require_tensile_root(explicit: Optional[str] = None) -> Path:
    """Locate the Tensile checkout, honouring the repo `.env` convention."""
    from oto.runners.toolchain import require_tensile_root

    try:
        return require_tensile_root(Path(explicit) if explicit else None, None)
    except ValueError as exc:
        raise SystemExit(str(exc))


# --------------------------------------------------------------------------
# The proof itself.
# --------------------------------------------------------------------------
def _tensile_pipeline() -> Tuple[Any, Any, Any, Any, Any]:
    """Import Tensile's writer pipeline.

    Imported late (not at module scope) so the tool still imports and runs its
    CLI with no Tensile present, and still fails with Tensile's own ImportError
    before a config is read -- exactly as when the imports sat in
    `probe_phase_config`. Returns
    (BP, constructForkPermutations, Solution, KernelWriterAssembly,
    markDuplicateKernels).
    """
    from Tensile.BenchmarkProblems import constructForkPermutations
    from Tensile.SolutionStructs import Solution
    from Tensile.TensileCreateLibrary import KernelWriterAssembly, markDuplicateKernels
    from Tensile import BenchmarkProblems as BP

    return (BP, constructForkPermutations, Solution, KernelWriterAssembly,
            markDuplicateKernels)


def _dedup_kernels(solutions: List[Any], Solution: Any) -> List[Any]:
    """The distinct kernels among forked `solutions`, keyed by full name."""
    kernels = []
    seen = set()
    for sol in solutions:
        kern = sol.getKernels()
        name = Solution.getNameFull(kern)
        if name not in seen:
            seen.add(name)
            kernels.append(kern)
    return kernels


def _kernel_writer(kernels: List[Any], Solution: Any,
                   KernelWriterAssembly: Any,
                   markDuplicateKernels: Any) -> Any:
    """Mirror writeBenchmarkFiles: one writer owns naming and duplicate flags."""
    min_naming = Solution.getMinNaming(kernels)
    serial_naming = Solution.getSerialNaming(kernels)
    writer = KernelWriterAssembly(
        min_naming, serial_naming, removeTemporaries=False
    )
    markDuplicateKernels(kernels, writer)
    return writer


def _probe_kernel(writer: Any, kern: Any, gidx: int) -> Dict[str, Any]:
    """Compile one kernel through Tensile's writer; return its verdict record."""
    exc_text = ""
    try:
        err, src = writer.getSourceFileString(kern)
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        err, src = -2, ""
        exc_text = f"{type(exc).__name__}: {exc}"
    if err != 0 and not exc_text:
        # getSourceFileString swallows the body-generation exception and returns
        # -2. Re-run the generator to get the actual reason instead of "unknown".
        try:
            writer.getKernelSource(kern)
        except Exception as exc:  # noqa: BLE001
            exc_text = f"{type(exc).__name__}: {exc}"[:220]
    if err == -1 and not exc_text:
        exc_text = "assembler/subprocess rejected generated source"

    reason = exc_text or ERR_MSG.get(err, f"error code {err}")
    return {
        "group": gidx,
        "ok": err == 0,
        "err": err,
        "reason": reason[:300],
        "kernel": _kernel_label(kern),
        "src_bytes": len(src) if isinstance(src, str) else None,
        "vgprs": _pool(writer, "vgprPool"),
        "sgprs": _pool(writer, "sgprPool"),
        "accvgprs": _pool(writer, "agprPool"),
    }


def _probe_group(
    problem_type_cfg: Any,
    group_cfg: Any,
    gidx: int,
    worst: int,
    tensile: Tuple[Any, Any, Any, Any, Any],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Probe one BenchmarkProblems size group.

    Returns (records, kernels_compiled, worst_err); `worst` is threaded through
    and returned so the caller keeps one running kernel-count and one running
    Tensile error code across every problem and group.
    """
    (BP, constructForkPermutations, Solution, KernelWriterAssembly,
     markDuplicateKernels) = tensile
    records: List[Dict[str, Any]] = []
    total = 0

    proc = BP.BenchmarkProcess(problem_type_cfg, group_cfg)
    for step in proc:
        perms = constructForkPermutations(step.forkParams, step.paramGroups)
        solutions = BP.generateForkedSolutions(
            proc.problemType, step.constantParams, perms
        )
        if not solutions:
            records.append(
                {
                    "group": gidx,
                    "ok": False,
                    "err": None,
                    "reason": "0 valid solutions after SolutionStructs validation",
                    "kernel": None,
                }
            )
            continue

        kernels = _dedup_kernels(solutions, Solution)
        if not kernels:
            records.append(
                {
                    "group": gidx, "ok": False, "err": None,
                    "reason": "all solutions collapsed to duplicate kernels",
                    "kernel": None,
                }
            )
            worst = -2
            continue

        writer = _kernel_writer(kernels, Solution, KernelWriterAssembly,
                                markDuplicateKernels)

        for kern in kernels:
            record = _probe_kernel(writer, kern, gidx)
            total += 1
            if not record["ok"] and worst == 0:
                worst = record["err"]
            records.append(record)

    return records, total, worst


def probe_phase_config(phase_yaml: Path) -> Dict[str, Any]:
    """Run Tensile's solution + kernel-writer pipeline over one phase config.

    Returns a verdict dict; never raises for a bad phase (a bad phase *is* the
    answer we want to report).
    """
    tensile = _tensile_pipeline()

    cfg = yamlio.load_yaml(phase_yaml)
    problems = cfg.get("BenchmarkProblems") or []
    if not problems:
        return {"ok": False, "reason": "phase config has no BenchmarkProblems section"}

    # Each BenchmarkProblems entry is [[problemType, [sizeGroup, ...]], ...]
    per_problem: List[Dict[str, Any]] = []
    worst = 0
    total = 0

    for entry in problems:
        problem_type_cfg = entry[0]
        size_groups = entry[1:] or [{}]
        for gidx, group_cfg in enumerate(size_groups):
            records, n, worst = _probe_group(
                problem_type_cfg, group_cfg, gidx, worst, tensile)
            per_problem.extend(records)
            total += n

    failed = sum(1 for r in per_problem if not r["ok"])
    return {
        "ok": failed == 0 and total > 0,
        "solutions": total,
        "failed_solutions": failed,
        "worst_err": None if worst == 0 else worst,
        "results": per_problem,
        "reason": None
        if worst == 0
        else next((r["reason"] for r in per_problem if not r["ok"]), "failed"),
    }


def _kernel_label(kern: Any) -> str:
    """Short stable label for a solution. getNameMin needs the naming param
    vector; SolutionNameMin is already materialised by markDuplicateKernels."""
    name = kern.get("SolutionNameMin")
    if name:
        return str(name)
    from Tensile.SolutionStructs import Solution

    return str(Solution.getNameFull(kern))[:120]


def _pool(ko: Any, name: str) -> Optional[int]:
    pool = getattr(ko, name, None)
    size = getattr(pool, "size", None)
    if callable(size):
        try:
            return int(size())
        except Exception:  # noqa: BLE001
            return None
    return None



