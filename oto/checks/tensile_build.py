#!/usr/bin/env python3
"""CPU-only Tensile build proof: does Tensile's own writer accept this phase?

Owns: for each phase, driving the same pipeline the real tuner uses minus the GPU
(``BenchmarkProcess`` -> ``generateForkedSolutions`` ->
``KernelWriterAssembly.getSourceFileString``) and reporting Tensile's own
verdict, because the occupancy gate is a calibrated model, not Tensile's truth.

Does NOT own: the gates it cross-checks (oto.tensile.gates), the phases it reads
(oto.tensile.candidate), or any GPU work -- none happens here.

Public API: main, probe_phase_config, write_phase_configs, select_phases.

``getSourceFileString`` is where Tensile decides a kernel is unschedulable: it
sets ``ko.overflowedResources`` and stamps the body with ``s_endpgm //
overflowed resources``. The error code returned is Tensile's verdict, not ours,
which is the whole point of the tool. Because the writer's register pools are
live at that point, the same pass reports Tensile's real per-thread VGPR / SGPR /
accVGPR counts -- the measurement that would retire the calibrated model.

No benchmark is ever run: ``BenchmarkProblems`` / ``BenchmarkStructs`` (the part
that launches GEMMs on the device) is never invoked. The ROCm tools touched are
the path-locating helpers real runs use (``hipconfig``,
``rocm_agent_enumerator``), which only print config.

    python3 check_tensile_build.py                 # all phases
    python3 check_tensile_build.py --family ZZ     # just ZZ
    python3 check_tensile_build.py --phase-id <id> # one phase
    python3 check_tensile_build.py --compare       # also check the model
    python3 check_tensile_build.py --json out.json
"""


from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

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
def _init_tensile(arch: str = "the device") -> None:
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

    isa = {"gfx900": (9, 0, 0x00), "the device": (9, 0, 0x0C), "gfx906": (9, 0, 0x06)}.get(arch)
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
    from Tensile.BenchmarkProblems import BenchmarkProcess  # noqa: F401
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


# --------------------------------------------------------------------------
# Driver: one subprocess per phase (Tensile is heavy global state).
# --------------------------------------------------------------------------
def _worker(args: argparse.Namespace) -> int:
    _init_tensile(arch=args.arch)
    result = probe_phase_config(Path(args.phase_yaml))
    Path(args.result_json).write_text(json.dumps(result))
    return 0 if result["ok"] else 1


def write_phase_configs(phases: List[Dict[str, Any]], outdir: Path) -> Dict[str, Any]:
    """Render every phase's real Tensile config, serially, in the main thread.

    Done up front and in one thread on purpose: TensileDriver.__init__ installs
    signal handlers (main-thread only, and it would rewrite the acceptance
    report if signalled), and patching that out is process-global state that
    would race if several threads did it at once. Config rendering is pure YAML
    and costs nothing, so keep it serial and let only the proof subprocesses fan
    out.
    """
    sys.path.insert(0, str(REPO))
    import signal

    from oto.runners.driver import TensileDriver

    real_signal = signal.signal
    signal.signal = lambda *a, **k: None
    try:
        driver = TensileDriver(REPO, create_run=False)
    finally:
        signal.signal = real_signal

    configs: Dict[str, Any] = {}
    for phase in phases:
        pid = phase["phase_id"]
        cfg_path = outdir / f"{pid}.yaml"
        try:
            wrote, refusal = driver._write_phase_config(cfg_path, phase)
        except Exception as exc:  # noqa: BLE001
            configs[pid] = {"cfg": None, "refusal": f"config generation failed: {exc}"[:300]}
            continue
        configs[pid] = {
            "cfg": cfg_path if wrote else None,
            "refusal": None if wrote else f"refused pre-build: {refusal}",
        }
    return configs


def _rejection_reason(stdout: str) -> str:
    """Pull Tensile's own rejection explanation out of worker stdout.

    SolutionStructs.reject() writes "reject: <field>=<value> ..." to stdout when
    PrintSolutionRejectionReason is on, so the cause is already in the captured
    stream -- it just has to be picked out. Without this, a phase that yields no
    solutions reports only "0 valid solutions", which cannot be acted on.
    """
    lines = [ln.strip() for ln in (stdout or "").splitlines()]
    out: List[str] = []
    for i, ln in enumerate(lines):
        if ln.startswith("reject:"):
            detail = ln[len("reject:"):].strip()
            # The field list continues on following lines; keep a couple.
            for extra in lines[i + 1:i + 3]:
                if extra and not extra.startswith(("reject:", "[", "!!")):
                    detail += " " + extra
                    break
            if detail and detail not in out:
                out.append(detail)
    if not out:
        return ""
    return "; ".join(out[:3])[:400]


def run_phase(pid: str, cfg_path: Path, outdir: Path, arch: str, timeout: int) -> Dict[str, Any]:
    """Build-prove one already-rendered phase config in a dedicated subprocess.

    Tensile is heavy global state (globalParameters, working paths, module-level
    caches), so each phase gets its own process rather than sharing one.
    """
    result_path = outdir / f"{pid}.result.json"
    if result_path.exists():
        result_path.unlink()
    work = outdir / pid
    work.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(REPO / "check_tensile_build.py"),
        "--_worker",
        "--phase-yaml", str(cfg_path),
        "--result-json", str(result_path),
        "--arch", arch,
    ]
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            cmd, cwd=str(work), capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"timeout after {timeout}s", "solutions": 0}

    if not result_path.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        return {
            "ok": False,
            "reason": "worker produced no result: " + " | ".join(tail)[:400],
            "solutions": 0,
        }
    result = json.loads(result_path.read_text())
    if not result.get("ok"):
        detail = _rejection_reason(proc.stdout)
        if detail:
            result["reason"] = f"Tensile rejected: {detail}"
            result["tensile_reject"] = detail
    return result


# --------------------------------------------------------------------------
def select_phases(args: argparse.Namespace) -> List[Dict[str, Any]]:
    deck = yamlio.load_yaml(REPO / "phases.yaml") or []
    if args.phase_id:
        deck = [p for p in deck if p.get("phase_id") == args.phase_id]
        if not deck:
            raise SystemExit(f"phase_id {args.phase_id!r} not in phases.yaml")
    if args.family:
        want = args.family.upper()
        deck = [
            p for p in deck
            if str((p.get("config") or {}).get("FamilyLabel", "")).upper() == want
        ]
    return deck


def print_progress(row: Dict[str, Any], i: int, total: int, outdir: Path,
                   passed: int, failed: int) -> None:
    regs = [r for r in row["results"] if r.get("vgprs") is not None]
    vg = max((r["vgprs"] for r in regs), default=None)
    ag = max((r.get("accvgprs") or 0 for r in regs), default=None)
    flag = "PASS" if row["ok"] else "FAIL"
    print(
        f"[{i:>3}/{total}] {flag} {row['phase_id']:<44} "
        f"MT={row['macro_tile']} TT={row['thread_tile']} "
        f"sols={row['solutions']}"
        + (f" vgpr<={vg}" if vg is not None else "")
        + (f" accvgpr<={ag}" if ag else "")
        + ("" if row["ok"] else f"  <- {row['reason']}"),
        flush=True,
    )
    if "model_ok" in row:
        agree = "MATCH" if row["model_ok"] == row["ok"] else "*** MISMATCH ***"
        print(f"          model: {'legal' if row['model_ok'] else 'illegal'} / Tensile: "
              f"{'legal' if row['ok'] else 'illegal'}  {agree}", flush=True)


def _probe_row(
    i_phase: Tuple[int, Dict[str, Any]],
    configs: Dict[str, Any],
    outdir: Path,
    args: Any,
    model_fn: Any,
) -> Dict[str, Any]:
    """Probe one phase and shape its report row (may run in a worker thread)."""
    _, phase = i_phase
    pid = phase["phase_id"]
    cfg = phase.get("config") or {}
    mt, tt = cfg.get("MacroTile"), cfg.get("ThreadTile")
    info = configs.get(pid) or {}
    if not info.get("cfg"):
        res = {"ok": False, "reason": info.get("refusal") or "no config", "solutions": 0}
    else:
        res = run_phase(pid, info["cfg"], outdir, args.arch, args.timeout)
    row = {
        "phase_id": pid,
        "label": phase.get("label"),
        "family": cfg.get("FamilyLabel"),
        "macro_tile": mt,
        "thread_tile": tt,
        "depth_u": cfg.get("DepthU"),
        "data_type": cfg.get("DataType"),
        "shapes": phase.get("shapes"),
        "ok": bool(res.get("ok")),
        "solutions": res.get("solutions", 0),
        "reason": res.get("reason"),
        "worst_err": res.get("worst_err"),
        "results": res.get("results", []),
    }
    if model_fn is not None:
        pred_ok, pred_why = model_fn(cfg) if mt else (False, "no MacroTile")
        row["model_ok"] = pred_ok
        row["model_reason"] = pred_why
    return row


def _build_arg_parser() -> argparse.ArgumentParser:
    """The CLI surface of the build proof."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", help="only this FamilyLabel (e.g. ZZ)")
    ap.add_argument("--phase-id")
    ap.add_argument("--arch", default="the device")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per phase")
    ap.add_argument("--jobs", type=int, default=1, help="parallel phase subprocesses")
    ap.add_argument("--json", help="write full report here")
    ap.add_argument("--compare", action="store_true",
                    help="cross-check oto's occupancy model against Tensile's verdict")
    ap.add_argument("--keep", help="keep build artifacts in this dir")
    # internal
    ap.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--phase-yaml", help=argparse.SUPPRESS)
    ap.add_argument("--result-json", help=argparse.SUPPRESS)
    return ap


def main() -> int:
    args = _build_arg_parser().parse_args()

    if args._worker:
        return _worker(args)

    phases = select_phases(args)
    outdir = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="tensile_build_"))
    outdir.mkdir(parents=True, exist_ok=True)

    model_fn = None
    if args.compare:
        sys.path.insert(0, str(REPO))
        from oto.tensile.candidate import occupancy_feasible as model_fn

    rows: List[Dict[str, Any]] = []
    passed = failed = 0
    print(f"Tensile CPU-only build proof: {len(phases)} phase(s), arch={args.arch}, "
          f"jobs={args.jobs}\n", flush=True)

    configs = write_phase_configs(phases, outdir)

    if args.jobs > 1:
        from concurrent.futures import ThreadPoolExecutor

        # Each phase runs in its own subprocess (Tensile global state), so
        # threads are just process supervision -- no shared mutable state.
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            done = list(pool.map(
                lambda ip: _probe_row(ip, configs, outdir, args, model_fn),
                enumerate(phases, 1)))
    else:
        done = []
        for i_phase in enumerate(phases, 1):
            row = _probe_row(i_phase, configs, outdir, args, model_fn)
            done.append(row)
            print_progress(row, i_phase[0], len(phases), outdir, passed, failed)

    for i, row in enumerate(done, 1):
        print_progress(row, i, len(phases), outdir, passed, failed)
        passed += 1 if row["ok"] else 0
        failed += 0 if row["ok"] else 1
        rows.append(row)

    print(f"\n{passed} passed, {failed} failed, {len(rows)} total")
    if not args.keep:
        shutil.rmtree(outdir, ignore_errors=True)
    else:
        print(f"artifacts: {outdir}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"report: {args.json}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
