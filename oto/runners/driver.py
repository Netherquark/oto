#!/usr/bin/env python3
"""The driver composition root: identity, toolchain, and wiring.

Owns: what an oto run *is* -- the Tensile root and ROCm toolchain resolution, the
ledger/analytics/mutator/agent wiring, signal handling, the Tensile subprocess
environment, the preflight check, and the run-wide live status panel.
``TensileDriver`` is the composition root: it inherits one mixin per
responsibility (benchmark.py, phase_runner.py, reference_floor.py, convergence_loop.py,
acceptance_reporting.py, clock_telemetry.py, timing.py, library_build.py) and owns nothing else.
Does NOT own: the gates (oto.tensile.gates), the verdict model (oto.metrics), or
durable state (oto.ledger).
Public API: TensileDriver, NOT_A_TENSILE_PARAM, _TENSILE_VALID_PARAMS.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from oto.device.kernel_vocabulary import cell_key, kernel_key
from oto.ledger.convergence_agent import ConvergenceAgent
from oto.ledger.mutator import Mutator
from oto.ledger.registry import SQLiteRegistry
from oto.metrics.acceptance_report import AcceptanceReporter
from oto.metrics.benchmark_analytics import AnalyticsEngine
from oto.metrics.telemetry import TelemetrySampler as SysfsTelemetrySampler
from oto.runners import acceptance_reporting as _reporting
from oto.runners import benchmark as _benchmark
from oto.runners import clock_telemetry as _clocks
from oto.runners import convergence_loop as _auto
from oto.runners import corpus_loaders as _analytics
from oto.runners import library_build as _synthesis
from oto.runners import phase_runner as _phases
from oto.runners import reference_floor as _reference
from oto.runners import timing as _timing
from oto.runners.toolchain import (
    DEFAULT_TENSILE_ROOT,
    require_tensile_root,
    resolve_rocm_paths,
)
from oto.tensile.candidate import CandidateGenerator

# Legacy private aliases, kept because the old flat public surface used
# them (`from port_tensile import _require_tensile_root`). New code should use the
# public names on oto.runners.toolchain.
_require_tensile_root = require_tensile_root
_resolve_rocm_paths = resolve_rocm_paths

# Industry-standard .env loader (python-dotenv); never overrides live env vars.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


# Parameter names accepted by Tensile 4.44.0 (this checkout), snapshotted from
# SolutionStructs.validParameters. Tensile runs as a subprocess here, so the set
# cannot be imported cheaply at launch time, and Tensile aborts a phase outright
# on an unrecognised name (BenchmarkStructs.checkParametersAreValid ->
# printExit), which is a silent-until-you-read-the-log failure mode.
#
# Kept honest by test_tensile_params.py, which diffs this against the live
# Tensile list whenever Tensile is importable. Refresh procedure: regenerate
# from `Tensile.SolutionStructs.validParameters.keys()`.
_TENSILE_VALID_PARAMS = frozenset({
    "1LDSBuffer", "AggressivePerfMode", "AssertAIGreaterThanEqual",
    "AssertAILessThanEqual", "AssertAlphaValue", "AssertBetaValue",
    "AssertCEqualsD", "AssertFree0ElementMultiple", "AssertFree1ElementMultiple",
    "AssertMinApproxSize", "AssertSizeEqual", "AssertSizeGreaterThan",
    "AssertSizeLessThan", "AssertSizeMultiple", "AssertStrideAEqual",
    "AssertStrideBEqual", "AssertStrideCEqual", "AssertStrideDEqual",
    "AssertSummationElementMultiple", "AtomicAddC", "BufferLoad", "BufferStore",
    "CheckDimOverflow", "CheckTensorDimAsserts", "ClusterLocalRead",
    "CustomKernelName", "DebugStreamK", "DelayRemainingArguments", "DepthU",
    "DepthULdsDivisor", "DirectToLdsA", "DirectToLdsB", "DirectToVgprA",
    "DirectToVgprB", "DisableAtomicFail", "DisableKernelPieces",
    "DisableVgprOverlapping", "EdgeType", "ExpandPointerSwap", "ExtraLatencyForLR",
    "ExtraMiLatencyLeft", "ForceStoreSC1", "Fp16AltImpl", "Fp16AltImplRound",
    "FractionalLoad", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
    "GlobalRead2A", "GlobalRead2B", "GlobalReadCoalesceGroupA",
    "GlobalReadCoalesceGroupB", "GlobalReadCoalesceVectorA",
    "GlobalReadCoalesceVectorB", "GlobalReadPerMfma", "GlobalReadVectorWidth",
    "GlobalSplitU", "GlobalSplitUAlgorithm", "GlobalSplitUAtomicAdd",
    "GlobalSplitUSummationAssignmentRoundRobin", "GlobalSplitUWorkGroupMappingRoundRobin",
    "GroupLoadStore", "ISA", "InnerUnroll", "InterleaveAlpha", "KernelLanguage",
    "LdcEqualsLdd", "LdsBlockSizePerPadA", "LdsBlockSizePerPadB", "LdsPadA",
    "LdsPadB", "LocalDotLayout", "LocalRead2A", "LocalRead2B",
    "LocalReadVectorWidth", "LocalWrite2A", "LocalWrite2B",
    "LocalWritePerMfma", "LoopDoWhile", "LoopTail", "MACInstruction",
    "MIArchVgpr", "MacroTile", "MacroTileShapeMax", "MacroTileShapeMin",
    "MagicDivAlg", "MatrixInstruction", "MaxOccupancy", "MaxVgprNumber",
    "MemoryModifierFormat", "MinKForGSU", "MinVgprNumber", "NoReject",
    "NonTemporalA", "NonTemporalB", "NonTemporalC", "NonTemporalD",
    "NumElementsPerBatchStore", "NumLoadsCoalescedA", "NumLoadsCoalescedB",
    "OptNoLoadLoop", "OptPreLoopVmcnt", "PackBatchDims", "PackFreeDims",
    "PackGranularity", "PackSummationDims", "PerformanceSyncLocation",
    "PerformanceWaitCount", "PerformanceWaitLocation", "PersistentKernel",
    "PersistentKernelAlongBatch", "PrefetchAcrossPersistent",
    "PrefetchAcrossPersistentMode", "PrefetchGlobalRead", "PrefetchLocalRead",
    "PreloadKernelArguments", "ReplacementKernel", "ScheduleGlobalRead",
    "ScheduleLocalWrite", "ScheduleIterAlg", "SourceSwap", "StaggerU",
    "StaggerUMapping", "StaggerUStride", "StoreCInUnroll", "StoreCInUnrollExact",
    "StoreCInUnrollInterval", "StoreCInUnrollPostLoop", "StorePriorityOpt",
    "StoreRemapVectorWidth", "StoreSyncOpt", "StoreVectorWidth", "StreamK",
    "StreamKAtomic", "StreamKXCCMapping", "SuppressNoLoadLoop",
    "ThreadSeparateGlobalReadA", "ThreadSeparateGlobalReadB", "ThreadTile",
    "TransposeLDS", "UnrollIncIsDepthU", "UnrollMajorLDSA", "UnrollMajorLDSB",
    "UnrollMemFence", "Use64bShadowLimit", "UseInstOffsetForGRO",
    "UseSgprForGRO", "VectorAtomicWidth", "VectorStore", "VectorWidth",
    "VectorWidthB", "VgprForLocalReadPacking", "WaveSeparateGlobalReadA",
    "WaveSeparateGlobalReadB", "WavefrontSize", "WorkGroup", "WorkGroupMapping",
    "WorkGroupMappingType",
})

# Not a Tensile parameter at all, despite reference kernel metadata carrying it
# as `grvw`. Emitting it made every T1 reference phase abort.
NOT_A_TENSILE_PARAM = frozenset({"GlobalReduceVectorWidth"})


class TensileDriver(
    _benchmark.BenchmarkMixin,
    _phases.PhaseMixin,
    _reference.ReferenceMixin,
    _auto.AutoMixin,
    _analytics.CorpusMixin,
    _reporting.ReportingMixin,
    _clocks.ClockMixin,
    _timing.TimingMixin,
    _synthesis.SynthesisMixin,
):
    """Main driver for oto Tensile port.

    One mixin per responsibility; see each module's docstring for what it owns.
    The composition root itself holds only the wiring, the preflight check, the
    live status panel, and the shared class-level constants.
    """

    def __init__(
        self,
        base_dir: Path,
        phase_timeout_s: int = 3600,
        tensile_root: Path | None = None,
        cooldown_s: int = 30,
        create_run: bool = True,
        codename: str | None = None,
    profile=None,
    ):
        """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
        self.base_dir = Path(base_dir).resolve()
        self.phase_timeout_s = phase_timeout_s
        self.tensile_root = require_tensile_root(tensile_root, DEFAULT_TENSILE_ROOT)
        self.cooldown_s = cooldown_s
        self.create_run = create_run
        # Resolve the device profile: an explicit codename wins; otherwise the
        # ambient resolution order applies (OTO_PROFILE > rocminfo detection >
        # the committed default), the same order `oto.device.loader` documents.
        if codename is None:
            from oto.device.loader import resolve_profile
            codename = resolve_profile(profile).codename
        self.codename = codename
        from oto.device.loader import load_profile, rebind_profile
        self.profile = load_profile(codename)
        # Propagate the profile to every consumer through the canonical
        # accessor (thread-scoped for tests; process-global here).
        try:
            rebind_profile(self.profile)
        except Exception as e:
            print(f"[driver] failed to bind the profile for this process: {e}",
                  file=sys.stderr)

        self._init_registry_and_scheduler()
        self._init_run_dirs()
        self._init_analytics_and_mutator()
        self._init_agent_and_reporter()
        self._init_client_build_dir()
        self._init_state()
        self._setup_signal_handlers()

    def _init_run_dirs(self) -> None:
        """Create or skip the run directory and configs subdir."""
        if self.create_run:
            with contextlib.suppress(Exception):
                self.registry.cleanup_stale_runs()
            self.run_dir = self.registry.create_run_dir()
            self.configs_dir = self.run_dir / "configs"
            self.configs_dir.mkdir(exist_ok=True)
        else:
            self.run_dir = None
            self.configs_dir = None

    def _init_registry_and_scheduler(self) -> None:
        self.registry = SQLiteRegistry(self.base_dir)
        self.generator = CandidateGenerator(self.base_dir, registry=self.registry)

    def _init_analytics_and_mutator(self) -> None:
        self.analytics = AnalyticsEngine(self.registry, self.base_dir)
        # The ledger-backed mutator. Constructed here so the
        # mutation arm records proposals and resolves outcomes; when it is
        # absent ConvergenceAgent falls back to appending to phases.yaml and
        # keeps the identical-fp skip on (see ConvergenceAgent.skip_mutation_arm).
        self.mutator = None
        try:
            self.mutator = Mutator(self.registry, self.base_dir, self.analytics)
            if not self.mutator.ledger_available():
                # Ledger missing or unreadable: do NOT bypass the identical-fp
                # skip, because novelty would then be unverifiable.
                self.mutator = None
        except Exception as e:
            self.mutator = None
            print(f"[mutator] unavailable ({e}); mutation arm keeps phases.yaml "
                  "behaviour and the identical-fp skip")

    def _init_agent_and_reporter(self) -> None:
        self.agent = ConvergenceAgent(
            self.base_dir,
            self.generator,
            self.analytics,
            mutator=self.mutator,
        )
        self._sync_agent_run_id()
        self.reporter = AcceptanceReporter(self.base_dir, cooldown_s=self.cooldown_s)

    def _init_client_build_dir(self) -> None:
        # Shared client build dir: built once per run, reused by all phases
        # (Tensile client is config-independent; see ClientExecutable.getClientExecutable).
        self.client_build_dir = self.run_dir / "client_build" if self.run_dir else None
        if self.client_build_dir:
            self.client_build_dir.mkdir(exist_ok=True)

    def _init_state(self) -> None:
        # State
        self._stop_requested = False
        self._finish_after_iteration = False
        # Set by the GPU-loss guard in PhaseMixin._abort_run when consecutive
        # phases measure nothing; makes the run finalize as *failed* with the
        # reason recorded, not as a user *interrupt*.
        self._abort_note = None
        self._gpu_phases_run = 0
        self._current_proc = None
        self._last_ab_reference_run_id: str | None = None
        self._native_arm_records: list[dict[str, Any]] = []
        self._telemetry: SysfsTelemetrySampler | None = None
        self._telemetry_run_id: str | None = None
        # Live TTY status panel. None unless a run turned it on; see
        # _start_live_status / _stop_live_status.
        self._last_run_status = ""
        self._live_status = None
        self._live_enabled = True
        self._live_interval = 30.0
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM: kill child process group and exit immediately."""
        # Print to stderr so it's visible even with stdout redirected
        sys.stderr.write(f"\n[INTERRUPT] Signal {signum} received. Killing subprocess and exiting...\n")
        sys.stderr.flush()
        self._stop_requested = True
        if self._current_proc and self._current_proc.poll() is None:
            with contextlib.suppress(OSError):
                os.killpg(os.getpgid(self._current_proc.pid), signal.SIGKILL)
        # Mark current run as interrupted in registry before exiting
        with contextlib.suppress(Exception):
            self.registry.update_run_status(self.run_dir.name, "interrupted", {})
        # Emit partial acceptance report from data collected so far
        with contextlib.suppress(Exception):
            self.generate_acceptance_report()
        # Exit with 130 (standard Ctrl+C exit code: 128 + SIGINT(2))
        sys.exit(130)
    def _get_tensile_env(self) -> dict[str, str]:
        """Construct environment with Tensile on PYTHONPATH and ROCm toolchain on PATH."""
        env = os.environ.copy()
        tensile_pkg = str(self.tensile_root)
        current_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{tensile_pkg}:{current_pp}".strip(":")

        # Export the ROCm toolchain pinned by .env: ROCM_PATH (and ROCM_BIN /
        # ROCM_LLVM_BIN / ROCM_VERSION) with the nightly dirs prepended to
        # PATH, so subprocesses never silently pick up /usr's hipcc.
        rocm = resolve_rocm_paths()
        env["ROCM_PATH"] = rocm["ROCM_PATH"]
        env["HIP_PATH"] = rocm["HIP_PATH"]
        for key in ("ROCM_BIN", "ROCM_LLVM_BIN", "ROCM_VERSION"):
            if rocm.get(key):
                env[key] = rocm[key]

        current_path = env.get("PATH", "")
        paths_to_add = [p for p in [rocm["ROCM_LLVM_BIN"], rocm["ROCM_BIN"]]
                        if os.path.isdir(p) and p not in current_path]
        if paths_to_add:
            env["PATH"] = f"{':'.join(paths_to_add)}:{current_path}"
        return env
    def run_preflight(self) -> bool:
        """
        Preflight validation:
        Check Tensile binary, device info, and registry.
        """
        print("Running preflight checks...")
        tensile_bin = self.tensile_root / "Tensile" / "bin" / "Tensile"

        parity_line = "not checked"
        parity_ok = True
        try:
            from oto.tensile.library_parity import (
                load_pipeline_phases,
                parity_report,
            )
            manifest = load_pipeline_phases(
                self.base_dir,
                run_id=self.run_dir.name if self.run_dir else None)
            pr = parity_report(manifest)
            parity_line = (f"{pr['deck_cells']}/{pr['shipped_cells']} shipped cells "
                           f"({len(pr['missing'])} missing, {len(pr['extra'])} extra)")
            parity_ok = pr["parity_ok"]
        except Exception as exc:  # pragma: no cover - defensive (never blocks)
            parity_line = f"error: {exc}"

        checks = [
            ("Tensile root exists", self.tensile_root.is_dir()),
            ("Tensile CLI exists", tensile_bin.is_file()),
            ("Registry DB accessible", self.registry.db_path.exists() or self.registry.results_dir.is_dir()),
            ("phases.yaml accessible", (self.base_dir / "phases.yaml").exists()),
            # Coverage-parity rule (docs/knowledge_base.md §6.1): the produced
            # TensileLibrary must address exactly the shipped gfx900 cell grid.
            ("TensileLibrary shape/dtype parity vs shipped gfx900", parity_ok),
        ]

        all_ok = True
        for _name, ok in checks:
            status = "[OK]" if ok else "[FAIL]"
            print(f"  {status} {_name}"
                  if _name != checks[-1][0]
                  else f"  {status} {_name} ({parity_line})")
            if not ok:
                all_ok = False

        return all_ok
    def _sync_agent_run_id(self) -> None:
        """Keep `agent.run_id` bound to the currently active run dir.

        Proposals carry the run that emitted them, and the overlay is written per
        run. Both read this one binding, so a swapped run dir (the reference path
        creates its own) cannot leave them pointing at a finished run.
        """
        if getattr(self, "agent", None) is None:
            return
        self.agent.run_id = self.run_dir.name if self.run_dir else None
    def _current_arm(self) -> str:
        """Arm of the run whose phases execute_phase is running: spoof for the
        gfx900 reference floor runs, native otherwise."""
        prefix = (getattr(self.profile, "spoof_reference", "")
                  if getattr(self, "profile", None) else "") or "gfx900"
        return "spoof" if f"{prefix}_ref" in str(self.run_dir.name) else "native"
    def _named_cell_stamps(self, phase: dict[str, Any], arm: str | None = None) -> dict[str, Any]:
        """cell-key stamps for a phase's registry records.

        Identity comes from the authoritative config (FamilyLabel + MacroTile +
        ProblemType), NOT re-derived from phase_id text — this is what keeps
        HH_HPA/HS_HPA distinct from HH in the named-cell mapping.
        """
        arm = arm or self._current_arm()
        config = phase.get("config", {})
        shapes = phase.get("shapes") or [str(config.get("ProblemType", ""))]
        stamps = {
            "cell_key": cell_key(config.get("FamilyLabel", phase.get("family", "")),
                                 shapes[0] if shapes else ""),
            "arm": arm,
            "kernel_key": kernel_key(config),
        }
        if stamps["cell_key"] is None:
            stamps.pop("cell_key")
        return stamps

    # --- live status panel --------------------------------------------------
    # CPU-only: run_status reads the registry, so the panel adds no GPU work and
    # no Tensile invocation.

    _KEY_POLL_S = 0.2

    def _start_live_status(self, run_id: str | None = None,
                           plan=None, interval: float | None = None) -> None:
        """Paint run_status into the TTY for the duration of a run.

        CPU-only: build_report reads the registry, so this adds no GPU work and
        no Tensile invocation. Failures are swallowed -- a status display must
        never be the reason a run dies. When stdout is not a TTY (piped log,
        CI) LiveStatus degrades to periodic plain lines instead of repainting,
        which keeps the log readable.
        """
        if not getattr(self, "_live_enabled", True):
            return
        if self._live_status is not None:
            return
        # Bind to THIS run. With no run_dir the panel would fall back to the
        # most recent run in the registry and display an unrelated run's tally
        # and ETA for the whole duration -- a confidently wrong display is worse
        # than none, so decline instead.
        resolved = run_id or (self.run_dir.name if self.run_dir else None)
        if not resolved:
            return
        try:
            from oto.metrics.run_status import LiveStatus, RunPlan
            self._live_status = LiveStatus(
                base=self.base_dir,
                run_id=resolved,
                plan=plan or RunPlan(rerun_illegal=True),
                interval=interval if interval is not None else self._live_interval,
                compact=True,
            ).start()
            self._live_status.refresh()
        except BaseException as e:
            # BaseException, not Exception: run_status raises SystemExit when the
            # registry is not there yet, and that must not abort a run that is
            # in the middle of creating one.
            self._live_status = None
            print(f"[live] status panel unavailable ({e}); continuing without it")
    def _stop_live_status(self) -> None:
        panel, self._live_status = self._live_status, None
        if panel is None:
            return
        with contextlib.suppress(BaseException):
            panel.stop()
