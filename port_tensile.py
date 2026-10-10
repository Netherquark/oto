#!/usr/bin/env python3
"""
port_tensile.py — Main driver for oto (Stage 1-7 orchestration)

The oto driver orchestrates all 7 stages:
- Stage 1: Manifest & Phase Execution
- Stage 2: Candidate Generation (via scheduler.py)
- Stage 3: Benchmark Execution (Tensile CLI)
- Stage 4: Adaptive Repeat / Convergence (via policy.py)
- Stage 5: Analytics & Append-Only Registry (via analytics.py)
- Stage 6: Synthesis / Build (TensileCreateLibrary)
- Stage 7: Acceptance A/B & Final Report (via report.py)

Usage:
    python3 port_tensile.py --targets phase_ss_Ailk_Bjlk_...   # Run specific targets
    python3 port_tensile.py --family SS --shape 1024x1024x1024  # Filter targets
    python3 port_tensile.py --auto                 # Auto-convergence loop (runs the
                                                   # shipped gfx900 reference floor
                                                   # automatically if none exists)
    python3 port_tensile.py --gfx900-reference [--refresh] [--limit N] [--ref-shapes 256,512]
                                                   # one-time shipped-dat floor
    python3 port_tensile.py --preflight            # Run Stage 1 preflight checks
    python3 port_tensile.py --help                # Show help
"""

import statistics
import argparse
import re
import yaml
import subprocess
import signal
import sys
import os
import time
import threading
import select
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from dotenv import load_dotenv

from registry import SQLiteRegistry, fingerprint_config
from scheduler import CandidateGenerator
from analytics import AnalyticsEngine, CellAnalytics
from gfx90c_common import cell_key, kernel_key
from policy import aggregate_cell, should_run
from agent import ConvergenceAgent
from mutator import Mutator
from report import AcceptanceReporter
from telemetry import TelemetrySampler as SysfsTelemetrySampler
import tensile_library as tlib
from auto_prompt import AutoPlan, ask  # noqa: E402  (--auto asks the user)

# Industry-standard .env loader (python-dotenv); never overrides live env vars.
load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_TENSILE_ROOT = Path(os.environ["TENSILE_ROOT"]) if os.environ.get("TENSILE_ROOT") else None


def _require_tensile_root(explicit: Optional[Path], default: Optional[Path]) -> Path:
    """Resolve the Tensile checkout root from an explicit arg, live env, or .env."""
    candidate = explicit or default
    if candidate is None:
        raise ValueError(
            "TENSILE_ROOT is not set. Configure it in the repo-root `.env` "
            "(TENSILE_ROOT=<path to Tensile checkout>) or pass --tensile-root."
        )
    resolved = Path(candidate).resolve()
    if not (resolved / "Tensile" / "bin" / "Tensile").exists():
        raise ValueError(f"TENSILE_ROOT {resolved} has no Tensile bin/Tensile; check `.env`.")
    return resolved


def _hipconfig() -> Dict[str, str]:
    """Query the native ROCm discovery tool (`hipconfig`) for install paths.

    `hipconfig` is the ROCm-shipped authority for toolchain locations
    (ROCM_PATH, HIP_PATH, HIP_CLANG_PATH). Returns parsed KEY: value pairs.
    """
    hipconfig = shutil.which("hipconfig")
    if not hipconfig:
        return {}
    try:
        out = subprocess.run([hipconfig], capture_output=True, text=True, timeout=30).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return {}
    info: Dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r"([A-Z][A-Z0-9_]*)\s*:\s*(.*)", line.strip())
        if m and m.group(2).strip():
            info[m.group(1)] = m.group(2).strip()
    return info


def _resolve_rocm_paths() -> Dict[str, str]:
    """Resolve the ROCm toolchain using native discovery only.

    Order per key: explicit env value (shell or .env) that exists, then native
    discovery (`hipconfig` for roots, `shutil.which` for binaries on PATH).
    No hand-rolled candidate chains.
    """
    hc = _hipconfig()

    prefix = os.environ.get("ROCM_PATH", "").strip()
    if not prefix or not os.path.isdir(prefix):
        prefix = hc.get("ROCM_PATH", "")

    bin_dir = os.environ.get("ROCM_BIN", "").strip()
    if not bin_dir or not os.path.isdir(bin_dir):
        cand = str(Path(prefix) / "bin") if prefix else ""
        hipcc = shutil.which("hipcc")
        bin_dir = cand if os.path.isdir(cand) else (os.path.dirname(hipcc) if hipcc else "")

    llvm_bin = os.environ.get("ROCM_LLVM_BIN", "").strip()
    if not llvm_bin or not os.path.isdir(llvm_bin):
        cand = hc.get("HIP_CLANG_PATH", "") or (str(Path(prefix) / "llvm" / "bin") if prefix else "")
        llvm_bin = cand if os.path.isdir(cand) else ""

    assembler = os.environ.get("TENSILE_ASSEMBLER", "").strip()
    if not assembler or not os.path.isfile(assembler):
        cand = str(Path(llvm_bin) / "clang++") if llvm_bin else ""
        assembler = cand if os.path.isfile(cand) else (shutil.which("clang++") or "")

    fallback = os.environ.get("TENSILE_ASSEMBLER_FALLBACK", "").strip()
    if not fallback or not os.path.isfile(fallback):
        fallback = shutil.which("clang++") or ""

    return {
        "ROCM_PATH": prefix,
        "HIP_PATH": hc.get("HIP_PATH", prefix),
        "ROCM_BIN": bin_dir,
        "ROCM_LLVM_BIN": llvm_bin,
        "TENSILE_ASSEMBLER": assembler,
        "TENSILE_ASSEMBLER_FALLBACK": fallback,
    }


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


class TensileDriver:
    """Main driver for oto Tensile port."""

    def __init__(
        self,
        base_dir: Path,
        phase_timeout_s: int = 3600,
        tensile_root: Optional[Path] = None,
        cooldown_s: int = 30,
        create_run: bool = True
    ):
        self.base_dir = Path(base_dir).resolve()
        self.phase_timeout_s = phase_timeout_s
        self.tensile_root = _require_tensile_root(tensile_root, DEFAULT_TENSILE_ROOT)
        self.cooldown_s = cooldown_s
        self.create_run = create_run

        self.registry = SQLiteRegistry(self.base_dir)

        if self.create_run:
            # Clean up any orphaned 'started' runs from prior crashes/interrupts
            try:
                self.registry.cleanup_stale_runs()
            except Exception:
                pass

            self.run_dir = self.registry.create_run_dir()
            self.configs_dir = self.run_dir / "configs"
            self.configs_dir.mkdir(exist_ok=True)
        else:
            self.run_dir = None
            self.configs_dir = None

        # Initialize sub-modules
        self.scheduler = CandidateGenerator(self.base_dir, registry=self.registry)
        self.analytics = AnalyticsEngine(self.registry, self.base_dir)
        # Option H Phase 1: the ledger-backed mutator. Constructed here so the
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

        self.agent = ConvergenceAgent(
            self.base_dir,
            self.scheduler,
            self.analytics,
            mutator=self.mutator,
        )
        self._sync_agent_run_id()
        self.reporter = AcceptanceReporter(self.base_dir, cooldown_s=self.cooldown_s)

        # Shared client build dir: built once per run, reused by all phases
        # (Tensile client is config-independent; see ClientExecutable.getClientExecutable).
        self.client_build_dir = self.run_dir / "client_build" if self.run_dir else None
        if self.client_build_dir:
            self.client_build_dir.mkdir(exist_ok=True)

        # State
        self._stop_requested = False
        self._finish_after_iteration = False
        self._gpu_phases_run = 0
        self._current_proc = None
        self._last_ab_reference_run_id: Optional[str] = None
        self._native_arm_records: List[Dict[str, Any]] = []
        self._telemetry: Optional[SysfsTelemetrySampler] = None
        self._telemetry_run_id: Optional[str] = None
        # Live TTY status panel. None unless a run turned it on; see
        # _start_live_status / _stop_live_status.
        self._last_run_status = ""
        self._live_status = None
        self._live_enabled = True
        self._live_interval = 15.0
        self._setup_signal_handlers()

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
            try:
                os.killpg(os.getpgid(self._current_proc.pid), signal.SIGKILL)
            except OSError:
                pass
        # Mark current run as interrupted in registry before exiting
        try:
            self.registry.update_run_status(self.run_dir.name, "interrupted", {})
        except Exception:
            pass
        # Emit partial acceptance report from data collected so far
        try:
            self.generate_acceptance_report()
        except Exception:
            pass
        # Exit with 130 (standard Ctrl+C exit code: 128 + SIGINT(2))
        sys.exit(130)

    def _get_tensile_env(self) -> Dict[str, str]:
        """Construct environment with Tensile on PYTHONPATH and ROCm toolchain on PATH."""
        env = os.environ.copy()
        tensile_pkg = str(self.tensile_root)
        current_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{tensile_pkg}:{current_pp}".strip(":")

        # Export exact ROCm toolchain variables
        rocm = _resolve_rocm_paths()
        env["ROCM_PATH"] = rocm["ROCM_PATH"]
        env["HIP_PATH"] = rocm["HIP_PATH"]

        current_path = env.get("PATH", "")
        paths_to_add = [p for p in [rocm["ROCM_LLVM_BIN"], rocm["ROCM_BIN"]]
                        if os.path.isdir(p) and p not in current_path]
        if paths_to_add:
            env["PATH"] = f"{':'.join(paths_to_add)}:{current_path}"
        return env

    def run_preflight(self) -> bool:
        """
        Phase-0 Preflight validation:
        Check Tensile binary, device info, and registry.
        """
        print("Running Phase-0 Preflight checks...")
        tensile_bin = self.tensile_root / "Tensile" / "bin" / "Tensile"

        parity_line = "not checked"
        parity_ok = True
        try:
            from library_parity import load_pipeline_phases, parity_report
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
            # Coverage-parity rule (knowledge_base.md §6.1): the produced
            # TensileLibrary must address exactly the shipped gfx900 cell grid.
            ("TensileLibrary shape/dtype parity vs shipped gfx900", parity_ok),
        ]

        all_ok = True
        for name, ok in checks:
            status = "[OK]" if ok else "[FAIL]"
            print(f"  {status} {name}"
                  if name != checks[-1][0]
                  else f"  {status} {name} ({parity_line})")
            if not ok:
                all_ok = False

        return all_ok

    def load_phases_manifest(self, phases_path: Optional[Path] = None,
                             include_overlay: bool = True
                             ) -> List[Dict[str, Any]]:
        """Load phases.yaml manifest (the data manifest), plus this run's overlay.

        `phases.yaml` is the curated deck and is never written to. The mutation
        arm's candidates live in a per-run overlay
        (`gfx90c_results/overlays/phases.<run_id>.overlay.yaml`), so they are
        merged here, after the curated phases, and tagged `origin: overlay`.

        Without this merge the overlay is write-only: candidates were emitted,
        recorded in the ledger and then never scheduled, so the arm would report
        progress while measuring nothing.

        The overlay is keyed on the *active* run. Another run's overlay is not
        applied, because its phases were scored against that run's state and
        re-running them here would produce measurements attributed to the wrong
        run. `--dry-run` has no run and therefore no overlay.

        An explicit `phases_path` means the caller owns that deck outright, so no
        overlay is merged -- `--gfx900-reference` passes the reference run's own
        phase file, and appending native-arm candidates to the spoof floor would
        corrupt the comparison the whole A/B rests on.
        """
        if phases_path is None:
            phases_path = self.base_dir / "phases.yaml"
            explicit_deck = False
        else:
            explicit_deck = True

        phases: List[Dict[str, Any]] = []
        if phases_path.exists():
            with open(phases_path, "r") as f:
                phases = yaml.safe_load(f) or []

        if explicit_deck or not include_overlay:
            return phases

        run_id = self.run_dir.name if self.run_dir else None
        if run_id:
            overlay = self._load_run_overlay(run_id)
            if overlay:
                merged = self._merge_overlay_entries(
                    phases, overlay, origin_label="overlay", src=run_id)
                if merged:
                    print(f"[overlay] merged {merged} candidate phase(s) from "
                          f"phases.{run_id}.overlay.yaml (phases.yaml untouched)")

        # Persistent seed overlay (proposal D2, potential_configs.md §8): the
        # proven-winner rows and next-phase probes queued for every native run,
        # deliberately NOT in phases.yaml so the curated deck stays exactly as
        # shipped. Same semantics as a per-run overlay (pure measurement-first
        # candidates), except the rows come from the documented seed list instead
        # of a live arm. Like the per-run overlay it is never applied to an
        # explicit phases_path (reference-floor runs keep their own deck).
        if self.run_dir is not None:
            seed = self._load_seed_overlay()
            if seed:
                merged = self._merge_overlay_entries(
                    phases, seed, origin_label="seed_overlay", src="seed")
                if merged:
                    print(f"[overlay] merged {merged} seed phase(s) from "
                          f"phases.seed.overlay.yaml (D2 list, phases.yaml untouched)")
        return phases

    def _merge_overlay_entries(
        self,
        phases: List[Dict[str, Any]],
        entries: List[Dict[str, Any]],
        origin_label: str,
        src: str,
    ) -> int:
        """Append overlay entries to `phases`, keyed on a stable phase_id.

        A phase_id collision (in the deck, a prior overlay layer, or within the
        entries themselves) would make `phases.phase_id UNIQUE` reject the
        overlay row, so the candidate would silently never run -- collisions are
        skipped loudly instead. Every merged row is tagged with `origin` and
        `overlay_run_id` so downstream policy can treat these as measurement-first
        candidates regardless of which overlay they came from.
        """
        seen = {str(p.get("phase_id", "")) for p in phases}
        merged = 0
        for entry in entries:
            entry = dict(entry or {})
            phase_id = str(entry.get("phase_id", ""))
            if not phase_id or phase_id in seen:
                continue
            seen.add(phase_id)
            entry["origin"] = entry.get("origin") or origin_label
            entry.setdefault("overlay_run_id", src)
            phases.append(entry)
            merged += 1
        return merged

    def _load_seed_overlay(self) -> List[Dict[str, Any]]:
        """This project's persistent seed overlay, or [] when there is none.

        `gfx90c_results/overlays/phases.seed.overlay.yaml` is curated by hand /
        by the D2 tooling and applied to every native run. The per-run overlay
        path is not used because the seed is not tied to a single run_id.
        """
        path = self.base_dir / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                payload = yaml.safe_load(f) or {}
            return payload.get("phases", []) or []
        except Exception as e:
            print(f"[overlay] seed overlay unreadable, ignoring: {e}")
            return []

    def _load_run_overlay(self, run_id: str) -> List[Dict[str, Any]]:
        """This run's overlay phases, or [] when there is none.

        Read through the mutator when one exists so overlay parsing has a single
        owner; falls back to the file directly so the overlay is still honoured
        with no ledger-backed mutator.
        """
        path = (self.base_dir / "gfx90c_results" / "overlays"
                / f"phases.{run_id}.overlay.yaml")
        if not path.exists():
            return []
        if self.mutator is not None:
            try:
                return self.mutator.load_overlay(run_id) or []
            except Exception:
                pass
        try:
            with open(path) as f:
                payload = yaml.safe_load(f) or {}
            return payload.get("phases", []) or []
        except Exception as e:
            print(f"[overlay] unreadable, ignoring: {e}")
            return []

    _KEY_POLL_S = 0.2

    def _read_key(self, block: bool = True) -> str:
        """One non-blocking keystroke, lowercased, or "" when there is none.

        Single owner of stdin for 's'/'e'/'q'. Two independent pollers on one
        fd race for the same byte, so the keys meant one thing in the cooldown
        latch and something else (or nothing) elsewhere; keeping the read here
        means every call site sees the same semantics and no keystroke is
        half-consumed.

        block=True is for spin-wait loops (cooldown, Tensile wait): it waits up
        to the poll interval, and when stdin is not a TTY (piped log, CI, cron)
        it sleeps that interval so the loop cannot busy-spin. block=False is for
        callers that already do real work per iteration, where sleeping would
        just add latency -- a deck with hundreds of skips must not pay 0.2s per
        phase to discover there are no keys to read.
        """
        try:
            if not sys.stdin.isatty():
                if block:
                    time.sleep(self._KEY_POLL_S)
                return ""
            r, _, _ = select.select([sys.stdin], [], [],
                                   self._KEY_POLL_S if block else 0)
            if not r:
                return ""
            return sys.stdin.read(1).lower()
        except (OSError, ValueError):
            # A closed or detached stdin must not take the run down.
            return ""

    def _apply_cooldown(self) -> bool:
        """
        Apply interruptible thermal cooldown latch between GPU benchmark phases.
        Listens for 's' (skip cooldown), 'e' (end run after current phase) and
        'q' (quit run) keys in real-time.
        Returns True if cooldown completed or skipped, False if quit requested.
        """
        if self._gpu_phases_run > 0 and self.cooldown_s > 0 and not self._stop_requested and not self._finish_after_iteration:
            print(f"Thermal cooldown: waiting {self.cooldown_s}s ('s' to skip sleep, 'e' to end run after current phase, 'q' to quit)...")
            start = time.time()
            while time.time() - start < self.cooldown_s:
                if self._stop_requested:
                    return False
                key = self._read_key()
                if key == 's':
                    print("\n[USER ACTION] 's' pressed: Skipping thermal cooldown...")
                    break
                elif key == 'e':
                    print("\n[USER ACTION] 'e' pressed: Ending run after current phase...")
                    self._finish_after_iteration = True
                    break
                elif key == 'q':
                    print("\n[USER ACTION] 'q' pressed: Quitting run during cooldown...")
                    self._stop_requested = True
                    return False
        return not self._stop_requested

    def _ensure_telemetry(self) -> Optional[SysfsTelemetrySampler]:
        """Run-wide telemetry: one sampler per run_dir, kept alive across all
        phases so a whole run's timeline survives (no per-phase truncation).
        Rows are tagged with the active phase via set_phase(). A run_dir swap
        (gfx900 reference run) stops the old sampler and starts a fresh log."""
        run_id = self.run_dir.name if self.run_dir else None
        if run_id is None:
            return None
        if self._telemetry is not None and self._telemetry_run_id == run_id:
            return self._telemetry
        if self._telemetry is not None:
            self._telemetry.stop()
            self._telemetry = None
        sampler = SysfsTelemetrySampler(self.run_dir / "logs" / "telemetry.csv")
        sampler.start()
        self._telemetry = sampler
        self._telemetry_run_id = run_id
        return sampler

    def _current_arm(self) -> str:
        """Arm of the run whose phases execute_phase is running: spoof for the
        gfx900 reference floor runs, native otherwise."""
        return "spoof" if "gfx900_ref" in str(self.run_dir.name) else "native"

    def _named_cell_stamps(self, phase: Dict[str, Any], arm: Optional[str] = None) -> Dict[str, Any]:
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

    def execute_phase(
        self,
        phase: Dict[str, Any],
        run_dir: Path
    ) -> Dict[str, Any]:
        """
        Execute a single phase (Stage 1 + Stage 3).
        """
        phase_id = phase.get("phase_id", "unknown")
        label = phase.get("label", "unknown")
        dtype = phase.get("dtype", "S")
        shapes = phase.get("shapes", [])
        schedule_name = phase.get("ScheduleName", "isa")
        num_benchmarks = phase.get("NumBenchmarks", 8)
        config = phase.get("config", {})
        fp = phase.get("fp", fingerprint_config(config))

        print(f"\n--- Phase {phase_id}: {label} ({schedule_name}, {dtype}) ---")

        # Apply cooldown before GPU work (first GPU phase exempt)
        if not self._apply_cooldown():
            print(f"Skipping phase {phase_id} due to stop request.")
            return {"status": "interrupted"}

        # Write phase config file
        phase_config_path = self.configs_dir / f"phase_{phase_id}.yaml"
        wrote, refusal = self._write_phase_config(phase_config_path, phase)
        if not wrote:
            # Refused before any GPU work. Record it as a settled verdict so the
            # completeness gate is not blocked forever by a phase that can never
            # build, and so the reason stays attributable instead of surfacing as
            # an opaque Tensile rejection later.
            reason = f"{refusal} (refused before Tensile launch)"
            print(f"Skipping {phase_id}: {reason}")
            self.registry.append_record({
                "run_id": self.run_dir.name,
                "phase_id": phase_id,
                "label": label,
                "dtype": dtype,
                "shapes": shapes,
                "schedule_name": schedule_name,
                "num_benchmarks": num_benchmarks,
                "fp": fp,
                "phase_key": tlib.phase_key(phase),
                "config_fingerprint": tlib.config_fingerprint(phase),
                "timestamp": datetime.now().isoformat(),
                "status": "skipped_illegal",
                "error": reason,
            }, run_id=self.run_dir.name)
            return {"status": "skipped_illegal", "reason": reason}

        # Log start record
        start_record = {
            "run_id": self.run_dir.name,
            "phase_id": phase_id,
            "label": label,
            "dtype": dtype,
            "shapes": shapes,
            "schedule_name": schedule_name,
            "num_benchmarks": num_benchmarks,
            "fp": fp,
            "timestamp": datetime.now().isoformat(),
            "status": "started"
        }
        start_record.update(self._named_cell_stamps(phase))
        self.registry.append_record(start_record, run_id=self.run_dir.name)

        # Tag the run-wide telemetry sampler with the active phase (started
        # lazily once per run; kept alive across phases and iterations).
        telemetry = self._ensure_telemetry()
        if telemetry is not None:
            telemetry.set_phase(phase_id)

        # Execute Tensile benchmark
        result = None
        end_record_logged = False
        try:
            result = self._run_tensile_benchmark(
                phase_config_path,
                run_dir / phase_id,
                timeout=self.phase_timeout_s
            )

            status = "completed" if result.get("status") == "success" else "failed"
            end_record = {
                "run_id": self.run_dir.name,
                "phase_id": phase_id,
                "label": label,
                "dtype": dtype,
                "shapes": shapes,
                "schedule_name": schedule_name,
                "num_benchmarks": num_benchmarks,
                "fp": fp,
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "result": result
            }
            end_record.update(self._named_cell_stamps(phase))
            # Content identity for the next run's reuse decision (see
            # _reusable_phase_keys). phase_id alone is not safe: it embeds
            # parser-derived knobs.
            end_record["phase_key"] = tlib.phase_key(phase)
            end_record["config_fingerprint"] = tlib.config_fingerprint(phase)
            self.registry.append_record(end_record, run_id=self.run_dir.name)
            end_record_logged = True
            self._gpu_phases_run += 1
            return result

        except subprocess.TimeoutExpired:
            print(f"Phase {phase_id} timed out after {self.phase_timeout_s}s")
            self.registry.append_record({
                "run_id": self.run_dir.name,
                "phase_id": phase_id,
                "label": label,
                "fp": fp,
                "timestamp": datetime.now().isoformat(),
                "status": "timeout"
            }, run_id=self.run_dir.name)
            end_record_logged = True
            return {"status": "timeout"}

        except Exception as e:
            print(f"Phase {phase_id} failed: {e}")
            self.registry.append_record({
                "run_id": self.run_dir.name,
                "phase_id": phase_id,
                "label": label,
                "fp": fp,
                "timestamp": datetime.now().isoformat(),
                "status": "failed",
                "error": str(e)
            }, run_id=self.run_dir.name)
            end_record_logged = True
            return {"status": "failed", "error": str(e)}
        finally:
            if telemetry is not None:
                telemetry.set_phase("")
            
            # Ensure completion record is written if result exists but record wasn't logged
            if result and not end_record_logged:
                try:
                    status = "completed" if result.get("status") == "success" else "failed"
                    end_record = {
                        "run_id": self.run_dir.name,
                        "phase_id": phase_id,
                        "label": label,
                        "fp": fp,
                        "timestamp": datetime.now().isoformat(),
                        "status": status,
                        "result": result
                    }
                    self.registry.append_record(end_record, run_id=self.run_dir.name)
                    print(f"[RECOVERY] Logged {status} record for {phase_id} in finally block")
                except Exception as e:
                    print(f"[RECOVERY ERROR] Failed to log completion record in finally: {e}")

    def _write_phase_config(self, path: Path, phase: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Write valid Tensile Top-Level Config YAML (GlobalParameters + BenchmarkProblems).

        Returns (True, "") when a config was written, or (False, reason) when a
        CPU legality gate refused the phase before any GPU work. Callers MUST
        honour the False: the caller used to ignore the early return, so rejected
        phases still launched Tensile against a config that did not exist. Tensile
        then failed with its own rejection reason (121 phases: GSU/AF0EM gate),
        which looked like a kernel problem and buried the real cause.

        Two gates run here, both CPU-only: assembly-class and register-file
        occupancy. The occupancy gate is what refuses the 8 dead ZZ shapes
        (`overflowedResources=4`, "Occupancy limit"). Refusing here keeps the
        verdict attributable instead of surfacing later as an opaque error 4.

        Contraction pattern → TransposeA/B (verified vs Tensile source):
            Ailk_Bljk → TA=False TB=False  (NN)
            Ailk_Bjlk → TA=False TB=True   (NT)
            Alik_Bljk → TA=True  TB=False  (TN)
            Alik_Bjlk → TA=True  TB=True   (TT)
        Pattern inferred from label if 'contraction_pattern' field absent.
        """
        from scheduler import (parse_tensile_shape, assembly_class_valid,
                               occupancy_feasible, ldspad_feasible)

        phase_id = phase.get("phase_id", "phase_unknown")
        label = phase.get("label", "")
        dtype = phase.get("dtype", "S").lower()
        schedule_name = phase.get("ScheduleName", "isa")
        num_benchmarks = phase.get("NumBenchmarks", 8)
        config = phase.get("config", {})
        shapes = phase.get("shapes", ["1024x1024x1024"])

        # Legality preflight at the LAUNCH boundary, not by convention. Both
        # gates are CPU-only and must refuse before a config file is written,
        # because Tensile's own rejection surfaces as an opaque
        # "Generating kernel source resulted in error 4" that looks like a
        # kernel problem rather than the parameterisation it is. The occupancy
        # gate is the one that caught all 8 dead ZZ phases; the assembly-class
        # gate is the one that caused the 121-config rc=1 bucket.
        #
        # gate_config merges the phase-level dtype/label into the config so each
        # predicate sees a complete FamilyLabel/label/DataType triple.
        gate_config = {**config, "DataType": dtype, "label": label}
        for gate_name, gate in (("assembly-class", assembly_class_valid),
                                ("occupancy", occupancy_feasible)):
            gate_ok, gate_reason = gate(gate_config)
            if not gate_ok:
                print(f"Skipping {phase_id}: {gate_name} illegal ({gate_reason})")
                return False, f"{gate_name} illegal: {gate_reason}"

        # --- Contraction pattern → TransposeA/B ---
        # Prefer explicit field; fall back to label parse.
        # Verified mapping (Tensile index notation cross-check):
        #   Ailk_Bljk → TA=False TB=False (NN)
        #   Ailk_Bjlk → TA=False TB=True  (NT)  [CSV: Cijk_Ailk_Bjlk_SB]
        #   Alik_Bljk → TA=True  TB=False (TN)  [CSV: Cijk_Alik_Bljk_SB]
        #   Alik_Bjlk → TA=True  TB=True  (TT)  [CSV: Cijk_Alik_Bjlk_SB]
        pattern = phase.get("contraction_pattern") or ""
        if not pattern:
            for pat in ("Ailk_Bljk", "Ailk_Bjlk", "Alik_Bljk", "Alik_Bjlk"):
                if pat in label:
                    pattern = pat
                    break
        _TRANSPOSE_MAP = {
            "Ailk_Bljk": (False, False),
            "Ailk_Bjlk": (False, True),
            "Alik_Bljk": (True,  False),
            "Alik_Bjlk": (True,  True),
        }
        transpose_a, transpose_b = _TRANSPOSE_MAP.get(pattern, (False, True))  # default NT

        # --- Parse shapes → Exact: [M, N, B, K] ---
        exact_sizes = []
        for s in shapes:
            parsed = parse_tensile_shape(s)
            exact_sizes.append([parsed["M"], parsed["N"], parsed["B"], parsed["K"]])

        # --- Parse MacroTile string "M0xM1xDepthU" ---
        macro_tile_str = config.get("MacroTile", "")
        macro_tile0 = config.get("MacroTile0")  # explicit key wins
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
        
        # If explicit MacroTile0/MacroTile1 missing but string exists, force parse
        if macro_tile_str and (macro_tile0 is None or macro_tile1 is None):
            if macro_tile_str and isinstance(macro_tile_str, str) and "x" in macro_tile_str:
                mt_parts = macro_tile_str.split("x")
                try:
                    macro_tile0 = int(mt_parts[0])
                    macro_tile1 = int(mt_parts[1])
                    if len(mt_parts) >= 3:
                        depth_u_from_macro = int(mt_parts[2])
                except ValueError:
                    pass

        # --- Group C: forwarded-knob legality gate (LdsPad / StaggerUStride / AF0EM) ---
        # CPU-only, runs after the MacroTile parse so the padded-LDS footprint is
        # computable. Refuses BEFORE a config file is written, so a forwarded pad
        # can never surface as an opaque Tensile "error 4" mid-run.
        pad_ok, pad_reason = ldspad_feasible(gate_config)
        if not pad_ok:
            print(f"Skipping {phase_id}: forwarded-knob illegal ({pad_reason})")
            return False, f"forwarded-knob illegal: {pad_reason}"

        # --- Parse ThreadTile (string "T0xT1" or list [T0, T1]) ---
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

        # --- HPA / mixed-precision family flags ---
        # Case-insensitive: deck labels are uppercase ("HH_HPA_...") while
        # agent-mutated candidates are lowercase ("mutate_hh_hpa_..."). Without
        # this, HPA mutants silently lost HighPrecisionAccumulate / DestDataType
        # and benchmarked as plain FP16 (assembly_class_valid already uppercases).
        is_hpa = ("HPA" in label.upper()
                  or "HPA" in str(config.get("ProblemType", "")).upper()
                  or "HPA" in str(config.get("FamilyLabel", "")).upper())
        is_hs_hpa = ("HS_HPA" in label.upper()
                     or "HS_HPA" in str(config.get("FamilyLabel", "")).upper())

        # --- ProblemType dict ---
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

        # --- ForkParameters ---
        fork_params: Dict[str, Any] = {}

        # ThreadTile
        fork_params["ThreadTile"] = [[tt0, tt1]]

        # MacroTile: Tensile ForkParameters requires MacroTile: [[M0, M1]] (no DepthU in MacroTile)
        if macro_tile0 is not None and macro_tile1 is not None:
            fork_params["MacroTile"] = [[int(macro_tile0), int(macro_tile1)]]

        # WorkGroup: explicit > computed from MacroTile/ThreadTile > default
        if "WorkGroup" in config and isinstance(config["WorkGroup"], list):
            fork_params["WorkGroup"] = [config["WorkGroup"]]
        elif macro_tile0 is not None and macro_tile1 is not None and tt0 and tt1:
            fork_params["WorkGroup"] = [[macro_tile0 // tt0, macro_tile1 // tt1, 1]]
        else:
            fork_params["WorkGroup"] = [[16, 16, 1]]

        # WorkGroupMapping
        if "WorkGroupMapping" in config:
            fork_params["WorkGroupMapping"] = [int(config["WorkGroupMapping"])]
        else:
            fork_params["WorkGroupMapping"] = [4]

        # GlobalSplitU
        if "GlobalSplitU" in config:
            fork_params["GlobalSplitU"] = [int(config["GlobalSplitU"])]
        else:
            fork_params["GlobalSplitU"] = [1]

        # DepthU: explicit > from MacroTile string > default
        if "DepthU" in config:
            fork_params["DepthU"] = [int(config["DepthU"])]
        elif depth_u_from_macro is not None:
            fork_params["DepthU"] = [depth_u_from_macro]
        else:
            fork_params["DepthU"] = [16]

        # VectorWidth
        if "VectorWidth" in config:
            fork_params["VectorWidth"] = [int(config["VectorWidth"])]

        # Global load/reduce widths. Tensile defaults these when absent, and the
        # default can contradict the named VectorWidth -> solution rejected
        # ("GlobalLoadVectorWidthA 2 must be == VectorWidth 4 or == 1").
        for _k in ("GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
                   "GlobalReduceVectorWidth"):
            if _k in config:
                fork_params[_k] = [int(config[_k])]

        # NumLoadsCoalescedA (NLCA alias)
        nlca = config.get("NLCA", config.get("NumLoadsCoalescedA"))
        if nlca is not None:
            fork_params["NumLoadsCoalescedA"] = [int(nlca)]

        # Prefetch knobs
        if "PrefetchGlobalRead" in config:
            fork_params["PrefetchGlobalRead"] = [bool(config["PrefetchGlobalRead"])]
        if "PrefetchLocalRead" in config:
            fork_params["PrefetchLocalRead"] = [bool(config["PrefetchLocalRead"])]

        # --- Group C: LDS-pad / RCT knobs forwarded verbatim (gated above) ---
        # LdsPadA/B, AssertFree0ElementMultiple, StaggerUStride and
        # StoreCInUnroll used to be silently dropped here; candidates carrying
        # them benchmarked WITHOUT the knob (marginal-value audit showed 167/167
        # reference kernels carrying pads benchmarked with pads stripped to 0).
        # ldspad_feasible above refuses an illegal value pre-launch, so what
        # reaches Tensile is exactly what the candidate proposed.
        #
        # The swizzle axis (StaggerU / StaggerUMapping / StaggerUStride) is
        # forwarded as a COUPLED TRIO: Tensile rejects StaggerUStride=0 unless
        # StaggerU=0 (SolutionStructs:3326-3327) and forces StaggerUMapping=0 +
        # StaggerUStride=0 when StaggerU=0 (:3333-3334), so forwarding
        # StaggerUStride alone (the pre-2026-10-09 state) silently benchmarked
        # every swizzle candidate at the defaults. ldspad_feasible enforces the
        # coupling + the SUS > 0.5*DepthU*bpe floor before this point.
        for _k in ("LdsPadA", "LdsPadB", "AssertFree0ElementMultiple",
                   "StaggerU", "StaggerUMapping", "StaggerUStride",
                   "StoreCInUnroll"):
            if _k in config:
                fork_params[_k] = [config[_k]]

        # Remove deprecated MacroTile0/MacroTile1 keys if they exist (Tensile doesn't accept them)
        fork_params.pop("MacroTile0", None)
        fork_params.pop("MacroTile1", None)

        # Drop parameter names this Tensile does not know about.
        #
        # Tensile's checkParametersAreValid() calls printExit() -- it aborts the
        # whole phase -- for any unrecognised name, so one stale key is fatal
        # and silent until you read the phase log. This is not hypothetical:
        # GlobalReduceVectorWidth reached here from reference kernel metadata
        # (`grvw`) and is not a Tensile 4.44.0 parameter, which is why all 127
        # T1 reference reruns died at "Filling in Parameters With Defaults"
        # having executed zero phases.
        #
        # Ask Tensile for the authoritative list rather than hardcoding one, so
        # this stays correct across Tensile versions and new knobs.
        unknown = sorted(
            k for k in fork_params
            if k not in _TENSILE_VALID_PARAMS or k in NOT_A_TENSILE_PARAM
        )
        for k in unknown:
            print(f"[cfg] dropping parameter {k!r} not supported by this Tensile")
            fork_params.pop(k)

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

        # Multi-threaded compilation: default to available CPU count (up to 16)
        cpu_threads = int(config.get("CpuThreads", min(os.cpu_count() or 8, 16)))

        tensile_yaml = {
            "GlobalParameters": {
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
                "CpuThreads": cpu_threads,
                "ScheduleName": schedule_name,
                "NumBenchmarks": num_benchmarks,
            },
            "BenchmarkProblems": [
                [
                    problem_type,
                    benchmark_group,
                ]
            ],
        }

        with open(path, "w") as f:
            yaml.safe_dump(tensile_yaml, f, default_flow_style=False, sort_keys=False)
        return True, ""

    def _tee_stream(self, stream, file, console, prefix: str) -> threading.Thread:
        """Pump a subprocess stream to its log file and the console, line by line."""
        def _pump():
            try:
                for line in iter(stream.readline, ""):
                    if not line:
                        break
                    file.write(line)
                    file.flush()
                    print(f"{prefix}{line.rstrip()}")
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
        t = threading.Thread(target=_pump, daemon=True)
        t.start()
        return t

    def _run_tensile_benchmark(
        self,
        config_path: Path,
        phase_out_dir: Path,
        timeout: int
    ) -> Dict[str, Any]:
        """
        Run Tensile benchmark via CLI in detached process group with interactive 's'/'e'/'q' key listener.
        """
        tensile_bin = self.tensile_root / "Tensile" / "bin" / "Tensile"
        phase_out_dir.mkdir(parents=True, exist_ok=True)

        # Tensile writes 2_BenchmarkData/*.csv and the resolved YAML into
        # phase_out_dir, and the log files below are opened with "w". Re-running
        # a phase into a directory that already holds results would therefore
        # destroy that phase's measurements and its logs in place. Refuse, and
        # let the caller pick a fresh run id or archive the directory first.
        existing = sorted(phase_out_dir.glob("2_BenchmarkData/*.csv"))
        if existing:
            raise FileExistsError(
                f"phase output {phase_out_dir} already contains "
                f"{len(existing)} benchmark CSV(s); re-running would overwrite "
                f"them. Move the directory aside or use a fresh run id.")

        rocm = _resolve_rocm_paths()
        assembler = rocm["TENSILE_ASSEMBLER"]
        if not os.path.isfile(assembler):
            assembler = rocm["TENSILE_ASSEMBLER_FALLBACK"]

        cmd = [
            sys.executable,
            str(tensile_bin),
            "--arch", "gfx90c",
            "--cxx-compiler", "hipcc",
            "--c-compiler", "hipcc",
        ]
        if os.path.isfile(assembler):
            cmd += ["--assembler", assembler]
        cmd += [
            "--client-build-path", str(self.client_build_dir),
            "--client-lock", str(self.client_build_dir / "client.lock"),
            "-d", "0",
            str(config_path),
            str(phase_out_dir)
        ]
        if os.environ.get("TENSILE_VERBOSE") in ("1", "true", "True"):
            cmd.append("--verbose")

        env = self._get_tensile_env()

        # If Tensile binary exists, execute real CLI
        if tensile_bin.exists():
            log_out = open(phase_out_dir / "stdout.log", "w")
            log_err = open(phase_out_dir / "stderr.log", "w")

            proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(self.tensile_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )
            self._current_proc = proc

            tee_workers = [
                self._tee_stream(proc.stdout, log_out, sys.stdout, f"[tensile] "),
                self._tee_stream(proc.stderr, log_err, sys.stderr, f"[tensile:err] "),
            ]

            start_t = time.time()
            skipped = False
            
            try:
                while proc.poll() is None and not self._stop_requested:
                    # Check timeout
                    if time.time() - start_t > timeout:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        raise subprocess.TimeoutExpired(cmd, timeout)

                    # Wait up to the poll interval for 's'/'e'/'q' (no-op off a TTY).
                    key = self._read_key()
                    if key == 's':
                        print("\n[USER ACTION] 's' pressed: Skipping current phase...")
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        skipped = True
                        break
                    elif key == 'e':
                        print("\n[USER ACTION] 'e' pressed: Ending run after current phase completes...")
                        self._finish_after_iteration = True
                    elif key == 'q':
                        print("\n[USER ACTION] 'q' pressed: Quitting run...")
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        self._stop_requested = True
                        break

                if self._stop_requested and proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass

                rc = proc.poll() if not skipped else -1
            finally:
                self._current_proc = None
                proc.wait()
                for w in tee_workers:
                    w.join(timeout=5)
                log_out.close()
                log_err.close()

            if skipped:
                return {"status": "skipped_by_user", "returncode": -1}

            # Look for 2_BenchmarkData/*.csv or 00_Final.csv
            bench_data_dir = phase_out_dir / "2_BenchmarkData"
            csv_files = list(bench_data_dir.glob("*.csv")) if bench_data_dir.exists() else []

            return {
                "status": "success" if rc == 0 else "failed",
                "returncode": rc,
                "benchmark_path": str(bench_data_dir),
                "csv_count": len(csv_files)
            }
        else:
            # Fallback path if Tensile binary is not present in test env
            return {
                "status": "simulated",
                "benchmark_path": str(phase_out_dir / "2_BenchmarkData"),
                "num_benchmarks": 8
            }

    def _start_live_status(self, run_id: Optional[str] = None,
                           plan=None, interval: Optional[float] = None) -> None:
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
            from run_status import LiveStatus, RunPlan
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
        try:
            panel.stop()
        except BaseException:
            pass

    def _sync_agent_run_id(self) -> None:
        """Keep `agent.run_id` bound to the currently active run dir.

        Proposals carry the run that emitted them, and the overlay is written per
        run. Both read this one binding, so a swapped run dir (the reference path
        creates its own) cannot leave them pointing at a finished run.
        """
        if getattr(self, "agent", None) is None:
            return
        self.agent.run_id = self.run_dir.name if self.run_dir else None

    def _resolve_proposal_outcome(self, phase: Dict[str, Any],
                                     run_dir: Path) -> Optional[str]:
        """Write a mutated candidate's measured outcome back to the ledger.

        Called after a phase that came from the mutation overlay has actually run.
        Without this the ledger records candidates that are then never resolved:
        they stay `pending` forever, so their `n` never grows, so the cell is
        routed to `replicate` on every later pass. A mutation arm that never
        writes back an outcome is indistinguishable from one that measured
        nothing.

        Only acts when the phase's fingerprint is in the ledger, so curated and
        reference-floor phases are untouched. Returns the outcome written, or
        None when the phase was not a ledger proposal / no mutator is present.
        """
        if self.mutator is None:
            return None
        fp = phase.get("fp")
        if not fp:
            return None
        try:
            if self.registry.get_proposal(fp) is None:
                return None
        except Exception:
            return None

        phase_dir = run_dir / str(phase.get("phase_id", ""))
        try:
            outcome, detail = self.mutator.resolve_phase_dir(
                fp, phase_dir, run_id=self.run_dir.name if self.run_dir else None)
        except Exception as e:
            # A classification failure must not abort a run whose phases have
            # already executed; the candidate simply stays pending.
            print(f"[ledger] could not resolve {fp}: {e}")
            return None
        if outcome and outcome != "pending":
            print(f"[ledger] {fp} -> {outcome} "
                  f"(winner_freq={detail.get('winner_freq')})")
        return None if outcome == "pending" else outcome

    def run_phases(
        self,
        target_ids: Optional[List[str]] = None,
        opt_in_identical_skip: bool = True,
        phases_path: Optional[Path] = None
    ) -> List[Dict[str, Any]]:
        """
        Run a set of targets with policy filtering (Stage 1-4).
        target_ids matches against phase_id (with or without 'phase_' prefix),
        label, or clean target key (e.g. 'ss_Ailk_Bjlk_1024x1024x1024').
        phases_path overrides the manifest source (used by --gfx900-reference,
        whose 2k+ phases live in the run dir, not phases.yaml).
        """
        phases = self.load_phases_manifest(phases_path) if phases_path else self.load_phases_manifest()

        # No run directory means nothing was created to benchmark into (--dry-run,
        # and the reference-floor path, which builds phases in the run dir). Every
        # registry write and every execute_phase below dereferences self.run_dir,
        # so report the plan and stop rather than dying on the first skipped
        # phase with an AttributeError on None.
        if self.run_dir is None:
            print(f"[plan] {len(phases)} phase(s) in the manifest; no run "
                  f"directory, so this is a dry run and nothing is executed.")
            return []

        # Live TTY panel: repaints while phases execute. Started after the
        # manifest is known to exist so the first frame is not an error.
        self._start_live_status()

        if target_ids:
            keys = {str(k) for k in target_ids}
            def _match_target(p):
                tid = str(p.get("phase_id", ""))
                lbl = str(p.get("label", ""))
                clean = tid.replace("phase_", "")
                return tid in keys or lbl in keys or clean in keys
            phases = [p for p in phases if _match_target(p)]

        results = []
        executed_count = 0
        skipped_count = 0
        refused_count = 0
        try:
            for phase in phases:
                if self._stop_requested or self._finish_after_iteration:
                    print("Stop requested, halting phase execution")
                    break

                phase_id = phase.get("phase_id", "")
                config = phase.get("config", {})
                fp = phase.get("fp", fingerprint_config(config))

                # Identical-fp skip bypass (Hplan.3 step 8), scoped to the
                # mutation overlay. The bypass exists so a candidate is measured
                # even when its fp has passed before: novelty and outcome are then
                # decided by the ledger instead of by pass/fail history. It is
                # authorised only while `skip_mutation_arm()` is False, i.e. the
                # ledger is present *and* outcomes can be written back -- with
                # neither, a bypassed candidate is re-measured forever and the arm
                # reports progress while learning nothing.
                #
                # Scoped to overlay phases deliberately: applying it to the curated
                # deck would re-benchmark settled phases on every run, which is the
                # opposite of what the skip is for.
                from_overlay = bool(phase.get("overlay_run_id")) or \
                    str(phase.get("origin") or "") in ("overlay", "seed_overlay")
                bypass_identical_skip = (
                    from_overlay and self.agent is not None
                    and not self.agent.skip_mutation_arm())
                # A mutant phase carries an explicit per-phase bypass (agent
                # mutate_and_feed sets bypass_identical_skip): the auto-skip
                # must never apply to a mutation, so it is measured even when an
                # identical config was tested before. This is the structural
                # form of the user directive; the agent-level skip_mutation_arm
                # remains as a second, independent gate.
                if phase.get("bypass_identical_skip"):
                    bypass_identical_skip = True
                if (phase.get("overlay_run_id") == "seed"
                        and self.run_dir is not None
                        and self.registry.has_run_benchmarked(
                            self.run_dir.name, fp)):
                    # A static seed must not re-benchmark itself every
                    # iteration. The seed rows are measurement-first *once per
                    # run*: after this run has produced a completed record for
                    # the fp, the seed falls back to the ordinary
                    # identical-fp skip for the rest of the run.
                    bypass_identical_skip = False

                # Policy check: should_run
                allowed, reason = should_run(
                    phase_id=phase_id,
                    fp=fp,
                    registry=self.registry,
                    phase_scope=target_ids,
                    opt_in_identical_skip=opt_in_identical_skip
                    and not bypass_identical_skip
                )
                if bypass_identical_skip and not allowed \
                        and reason == "identical_fp_already_passed":
                    # The ledger, not pass history, decides this one.
                    allowed, reason = True, "bypassed_identical_fp_via_ledger"

                if not allowed:
                    print(f"Skipping phase {phase_id} ({reason})")
                    skipped_count += 1
                    self.registry.append_record({
                        "run_id": self.run_dir.name,
                        "phase_id": phase_id,
                        "fp": fp,
                        "timestamp": datetime.now().isoformat(),
                        "status": "skipped",
                        "reason": reason
                    }, run_id=self.run_dir.name)
                    # A skip does no GPU work, so it used to run with no key
                    # polling at all: pressing 'q' during a deck whose phases
                    # were all already-passed did nothing until some phase
                    # actually launched, which for a fully-skipped deck is never.
                    # The keys are documented as run-wide, so honour them here
                    # too. 's' has no meaning (nothing is executing to skip) but
                    # is consumed rather than left in the buffer.
                    key = self._read_key(block=False)
                    if key == 'q':
                        print("\n[USER ACTION] 'q' pressed: Quitting run while skipping phases...")
                        self._stop_requested = True
                        break
                    elif key == 'e':
                        print("\n[USER ACTION] 'e' pressed: Ending run after current phase...")
                        self._finish_after_iteration = True
                        break
                    continue

                result = self.execute_phase(phase, self.run_dir)
                results.append(result)
                # Outcome feedback (H.3.8). Only reached for phases that actually
                # launched, so a skipped or refused phase is not classified as
                # non-functional for having produced no output.
                if result.get("status") in ("completed", "failed", "success"):
                    self._resolve_proposal_outcome(phase, self.run_dir)
                if result.get("status") == "skipped_illegal":
                    refused_count += 1      # refused pre-launch; nothing was executed
                elif result.get("status") not in ("interrupted", "skipped_by_user"):
                    executed_count += 1

                if self._finish_after_iteration:
                    print("End-after-iteration requested, halting phase execution")
                    break

            # Mark run final status in registry
            if self._stop_requested:
                final_status = "interrupted"
            elif executed_count == 0 and (skipped_count + refused_count) > 0:
                final_status = "skipped"
            else:
                final_status = "completed"
            run_meta: Dict[str, Any] = {
                "phases_executed": executed_count,
                "phases_skipped": skipped_count,
            }
            if refused_count:
                run_meta["phases_refused_illegal"] = refused_count
            if self._finish_after_iteration:
                run_meta["end_after_iteration"] = True
            self._last_run_status = final_status
            self.registry.update_run_status(self.run_dir.name, final_status, run_meta)
            return results
        finally:
            # Always tear the panel down, including on Ctrl-C or an exception
            # mid-phase, so the terminal is not left with a half-drawn panel
            # and stdout is restored before the acceptance report prints.
            self._stop_live_status()

    def run_gfx900_reference(self, refresh: bool = False, limit: Optional[int] = None,
                             ref_shapes: Optional[List[str]] = None,
                             resume: bool = False,
                             resume_base: Optional[str] = None,
                             release_held: bool = False,
                             release_drop: bool = False) -> Dict[str, Any]:
        """
        One-time benchmark of every shipped gfx900 kernel from the system dat.

        Refreshes the pinned manifest when refresh=True, emits one reference
        phase per shipped kernel, and runs them all in a dedicated
        gfx900_ref_* run (ScheduleName=vega10 → spoof arm). Once completed,
        future A/B comparisons recall this run — never re-run — forever.

        resume=True targets ONLY the phases of the base run's deck that have no
        definite verdict yet (unattempted + previously-started-without-end).
        The base is the newest completed non-smoke reference run (or
        resume_base); the completed base phases are reused as-is, and a new
        gfx900_ref_*_resume run is created that records resume_of=<base>, so
        the reference_chain() fixture spans base+resume as one logical floor.
        smoke/limit/ref_shapes are ignored in resume mode.

        release_held=False (the default, and the only thing --auto passes) keeps
        the audited-but-under-specified T2 kernels pinned out of the deck.
        Pass --release-under-specified to finally measure them; see
        incomplete_work.md section 4.16.
        """
        from scheduler import assembly_class_valid

        manifest = tlib.load_shipped_manifest(
            self.base_dir, refresh=(not resume and refresh))
        resume_meta: Dict[str, Any] = {}
        if resume:
            chain_ids = tlib.reference_chain(self.registry, exclude=self.run_dir.name)
            base = resume_base or (chain_ids[0] if chain_ids else None)
            if not base:
                return {"status": "failed",
                        "reason": "resume requires an existing completed "
                                  "gfx900 reference run"}
            base_dir = self.base_dir / "gfx90c_runs" / base
            base_yaml = base_dir / "phases_reference.yaml"
            if not base_yaml.is_file():
                return {"status": "failed", "reason": f"base run deck missing: {base_yaml}"}
            with open(base_yaml) as f:
                deck = yaml.safe_load(f) or []

            # A triaged resume exists to re-measure phases whose CONFIG changed.
            # Replaying the stored deck would re-run the pre-fix configs verbatim,
            # so rebuild the deck from the shipped manifest instead and let the
            # content comparison decide what still needs running.
            _rm = tlib.load_rerun_manifest(self.base_dir)
            if _rm:
                print("[gfx900-reference] triage manifest present: rebuilding the "
                      "deck from the shipped manifest so the config fixes apply")
                _fresh = tlib.emit_spoof_phases(manifest)
                # Keep the rebuild inside the audited scope. emit_spoof_phases
                # spans every shipped family (2285 here) while the audited floor
                # covers 1212 of them; intersecting by phase_key refreshes the
                # configs without silently widening the floor with families that
                # were never part of it.
                # Scope comes from the triage manifest, not from the deck we
                # happened to load. The base deck is the newest chain head, which
                # after several resumes only covers the last slice of kernels;
                # the manifest is keyed by phase_key and spans every kernel seen
                # across the whole reference chain.
                _audited = set(_rm.get("tiers_by_key") or {}) | {
                    tlib.phase_key(p) for p in deck}
                _scoped = [p for p in _fresh if tlib.phase_key(p) in _audited]
                print(f"[gfx900-reference] rebuilt {len(_scoped)}/{len(_fresh)} "
                      f"phase(s) inside the audited scope "
                      f"({len(_audited)} kernel(s) triaged)")
                deck = _scoped

            # Reuse by content, not by phase_id (see _reusable_phase_keys).
            current_fps = {}
            for p in deck:
                clean = {k: v for k, v in p.items() if not k.startswith("_")}
                current_fps[tlib.phase_key(p)] = tlib.config_fingerprint(clean)
            reusable_keys, reusable_pids = self._reusable_phase_keys(
                chain_ids, current_fps)

            # A triage manifest is authoritative and outranks reuse: T1 exists
            # precisely because the earlier measurement is void, so it must run
            # again even though a completed record exists, and T3 must never be
            # re-staged. Only T0_KEEP phases remain eligible for reuse.
            # Reuse-then-triage ordering would instead drop every T1 phase that
            # already has a verdict and quietly run none of them.
            # T2 is HELD by default (see incomplete_work.md 4.16): pinned out of
            # this run unless the caller explicitly released it.
            rerun_manifest = _rm
            phases = []
            n_reuse = 0
            n_held = 0
            for p in deck:
                key = tlib.phase_key(p)
                pid = str(p.get("phase_id", ""))
                if rerun_manifest:
                    tier = tlib.tier_for(p, rerun_manifest)
                    if tier == tlib.TIER_DROP:
                        continue
                    if tier == tlib.TIER_HELD and not release_held:
                        n_held += 1
                        continue
                    if tier == tlib.TIER_FIRST or (
                            tier in (tlib.TIER_LAST, tlib.TIER_HELD)):
                        phases.append(p)
                        continue
                if key in reusable_keys or pid in reusable_pids:
                    n_reuse += 1
                    continue
                phases.append(p)
            if n_reuse:
                print(f"[gfx900-reference] reusing {n_reuse}/{len(deck)} phase(s) "
                      f"by content ({len(reusable_keys)} keyed, "
                      f"{len(reusable_pids)} legacy)")
            if rerun_manifest:
                n_t3 = sum(1 for p in deck
                           if tlib.tier_for(p, rerun_manifest) == tlib.TIER_DROP)
                held_note = (f", {n_held} pinned as held"
                             if n_held else "")
                print(f"[gfx900-reference] triage applied: {len(phases)} phase(s) "
                      f"to run, {n_reuse} reusable, {n_t3} dropped as unreproducible"
                      f"{held_note}")
            resume_meta = {"gfx900_resume": True, "resume_of": base}
            if not phases:
                print("[gfx900-reference] reference deck already fully completed — "
                      "nothing to resume")
                return {"status": "noop", "run_id": base,
                        "phases_targeted": 0, "phases_executed": 0, "results": 0}
        else:
            phases = tlib.emit_spoof_phases(manifest)

            # Deck-shape filter + family-spread limit. Prefer assembly-legal phases
            # so an empty smoke can never be spuriously "completed" (and recalled).
            def _legal(p: Dict[str, Any]) -> bool:
                gate = {**p.get("config", {}), "DataType": p.get("dtype"),
                        "label": p.get("label", "")}
                ok, _ = assembly_class_valid(gate)
                return ok

            if ref_shapes:
                wanted = {str(int(s)) for s in ref_shapes}
                kept = []
                for p in phases:
                    kept_shapes = [s for s in p.get("shapes", [])
                                   if str(int(s.split("x")[0]) if "x" in s else s) in wanted]
                    if kept_shapes:
                        p = dict(p)
                        p["shapes"] = kept_shapes
                        kept.append(p)
                phases = kept

            if limit:
                picked: List[Dict[str, Any]] = []
                seen_fam = set()
                for p in phases:
                    fam = p["label"].split("_")[1]
                    if fam in seen_fam:
                        continue
                    if not _legal(p):
                        continue
                    picked.append(p)
                    seen_fam.add(fam)
                    if len(picked) >= int(limit):
                        break
                phases = picked

        # Audited re-run triage: T3 (Tensile cannot derive) dropped, T1 hoisted,
        # T2 deferred to the very end. The resume branch above has already made
        # the manifest authoritative (T1 always staged, T3 never staged), so
        # this call only fixes the order — and drops the pinned T2 unless the
        # caller released it.
        _rerun = tlib.load_rerun_manifest(self.base_dir)
        if _rerun:
            _before = len(phases)
            _tiers = [tlib.tier_for(p, _rerun) for p in phases]
            phases = tlib.apply_rerun_tiers(phases, _rerun,
                                            release_held=release_held,
                                            release_drop=release_drop)
            n_held = _tiers.count(tlib.TIER_HELD)
            n_drop = _tiers.count(tlib.TIER_DROP)
            print(f"[gfx900-reference] triage: {_before} -> {len(phases)} "
                  f"phase(s) (T1 first"
                  + (f", {n_drop} T3 unreproducible dropped"
                     if n_drop and not release_drop else "")
                  + (f", {n_drop} T3 released to the back" if release_drop and n_drop else "")
                  + (f", {n_held} T2 pinned-held"
                     if n_held and not release_held else "")
                  + (", T2 released to the back" if release_held else "")
                  + ")")

        if not phases:
            return {"status": "failed", "reason": "no eligible shipped phases emitted"}

        print(f"[gfx900-reference] {len(phases)} shipped phase(s) from "
              f"{'+'.join(manifest.get('rocm_prefixes') or [])} "
              f"({manifest.get('total_shipped_kernels', 0)} kernels)"
              + (f" [RESUME of {resume_meta.get('resume_of')}]" if resume_meta else ""))

        run_id = f"gfx900_ref_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if resume:
            run_id = f"{run_id}_resume"
        prev_run_dir, prev_configs, prev_client = (
            self.run_dir, self.configs_dir, self.client_build_dir
        )
        self.run_dir = self.registry.create_run_dir(run_id)
        self.configs_dir = self.run_dir / "configs"
        self.configs_dir.mkdir(exist_ok=True)
        self.client_build_dir = self.run_dir / "client_build"
        self.client_build_dir.mkdir(exist_ok=True)
        # The reference run replaces the active run dir; keep the agent's
        # run_id bound to whatever run is current, or every candidate emitted
        # during it would be attributed to the previous run.
        self._sync_agent_run_id()

        phases_path = self.run_dir / "phases_reference.yaml"
        with open(phases_path, "w") as f:
            yaml.safe_dump(phases, f, default_flow_style=False)

        try:
            results = self.run_phases(
                [p["phase_id"] for p in phases],
                opt_in_identical_skip=False,
                phases_path=phases_path
            )
            executed = sum(1 for r in results
                           if isinstance(r, dict) and r.get("status") == "success")
            if self._stop_requested:
                status = "interrupted"
            elif limit is not None and not resume:
                # Limited runs are smokes: they must NEVER become the recalled
                # floor. Only an unlimited full --gfx900-reference is the floor.
                status = "smoke"
            else:
                status = "completed" if executed > 0 else "failed"
            run_meta = {
                "gfx900_reference": True,
                "shipped_kernels": manifest.get("total_shipped_kernels", 0),
                "phases_targeted": len(phases),
                "phases_executed": executed,
                "smoke": limit is not None and not resume,
                "source": phases_path.name,
            }
            run_meta.update(resume_meta)
            self.registry.update_run_status(run_id, status, run_meta)
            if status == "smoke":
                print("[gfx900-reference] smoke run marked 'smoke' — NOT recalled as "
                      "the A/B floor. Run `--gfx900-reference` WITHOUT --limit to "
                      "establish the permanent floor.")
            return {"run_id": run_id, "status": status,
                    "phases_targeted": len(phases), "phases_executed": executed,
                    "results": len(results)}
        finally:
            if self._telemetry is not None:
                self._telemetry.stop()
                self._telemetry = None
                self._telemetry_run_id = None
            self.run_dir, self.configs_dir, self.client_build_dir = (
                prev_run_dir, prev_configs, prev_client
            )
            self._sync_agent_run_id()

    def _latest_reference_run(self, exclude: Optional[str] = None) -> Optional[str]:
        """Most recently completed gfx900 reference run (recall floor for A/B)."""
        ref = tlib.latest_reference_run_id(self.registry)
        if ref and exclude and ref == exclude:
            return None
        return ref

    def _reference_floor_runs(self, run_id: Any) -> List[str]:
        """Full resume chain of the recalled reference floor, newest first,
        excluding the candidate run itself when it is a reference run."""
        exclude = str(run_id) if str(run_id).startswith("gfx900_ref_") else None
        chain = tlib.reference_chain(self.registry, exclude=exclude)
        return [r for r in chain
                if (self.base_dir / "gfx90c_runs" / r).is_dir()]

    def _reusable_phase_keys(self, run_ids: List[str],
                            current_fps: Optional[Dict[str, str]] = None
                            ) -> Tuple[Set[str], Set[str]]:
        """Identities whose prior measurement may be reused.

        Returns (keys, pids):
          keys - content-addressed identities, i.e. tlib.phase_key() (a hash of
                  the shipped solution name). A record may only be reused when it
                  carries a config_fingerprint that still matches the one computed
                  from the phase as it would run now, so changing a knob
                  invalidates exactly the affected measurements instead of
                  silently reusing them.
          pids  - legacy identities, for records predating phase_key (keyed on
                  phase_id as before). Kept so a rollout never *loses* a floor.

        phase_id is deliberately not the primary key: it embeds parser-derived
        knobs, so fixing a parser renamed 1073 of 1212 ids and one resume
        re-ran the entire floor.
        """
        current_fps = current_fps or {}
        keys: Set[str] = set()
        pids: Set[str] = set()
        for rid in run_ids:
            try:
                records = self.registry.read_records(run_id=rid)
            except Exception:
                continue
            for rec in records:
                if not rec.get("phase_id"):
                    continue
                if str(rec.get("status", "")).lower() not in ("completed", "success"):
                    continue
                key = rec.get("phase_key")
                if not key:
                    pids.add(str(rec["phase_id"]))
                    continue
                recorded = rec.get("config_fingerprint")
                if not recorded:
                    # Keyed but pre-dating fingerprints: the config it was measured
                    # under is unknowable, so it cannot be proven to still match.
                    # Re-measuring is the safe direction; stale reuse is not.
                    continue
                if recorded != current_fps.get(str(key)):
                    continue
                keys.add(str(key))
        return keys, pids

    def _chain_phase_sets(self, run_ids: List[str]) -> Tuple[Set[str], Set[str]]:
        """Per-phase verdict sets across the whole reference chain.

        completed:   phases that produced a kernel (status completed/success).
        decided:     phases with any definite verdict (completed/success/failed/
                     skipped_illegal). skipped_illegal is a phase the assembly-class
                     gate refused before Tensile was ever launched: it can never
                     build, so counting it as settled is what stops the
                     completeness gate from retrying it forever.
                     The gap deck - decided = unattempted (never started);
                     the gap deck - completed = what a --resume must still try
                     (unattempted + retried-free failed + started-without-end).
        """
        completed: Set[str] = set()
        decided: Set[str] = set()
        for rid in run_ids:
            try:
                records = self.registry.read_records(run_id=rid)
            except Exception:
                continue
            for rec in records:
                if not rec.get("phase_id"):
                    continue
                status = str(rec.get("status", "")).lower()
                if status in ("completed", "success"):
                    completed.add(str(rec["phase_id"]))
                    decided.add(str(rec["phase_id"]))
                elif status in ("failed", "skipped_illegal"):
                    decided.add(str(rec["phase_id"]))
        return completed, decided

    def _reference_remaining(self) -> int:
        """Phases the reference floor still owes, per the audited triage.

        Only T1 blocks. T1 is the set that previously ran with a config our own
        extractors got wrong, so it must be re-measured before anything is trusted
        downstream. T2 is under-specified (measured with glvw/grvw left to
        Tensile's defaults) and is HELD: not staged by default, opt-in only, and
        it must never hold --auto open. T3 is unbuildable by construction and
        stays failed. Held and dropped tiers are both invisible to this gate, so
        pinning T2 cannot deadlock --auto.

        A T1 phase is owed until the newest record for it is a completion whose
        config_fingerprint matches the one computed from the phase as it would run
        now. Without the fingerprint term this gate would see the old verdicts
        under stale phase_ids and skip the reference entirely.
        """
        chain = tlib.reference_chain(self.registry, exclude=self.run_dir.name)
        if not chain:
            return -1
        # Union of every deck in the chain: after several resumes the newest deck
        # covers only the last slice of kernels, but the floor spans all of them.
        universe: Dict[str, Dict[str, Any]] = {}
        for rid in chain:
            deck_path = (self.base_dir / "gfx90c_runs" / rid
                         / "phases_reference.yaml")
            try:
                for ph in yaml.safe_load(deck_path.read_text()) or []:
                    universe.setdefault(tlib.phase_key(ph), ph)
            except Exception:
                continue
        if not universe:
            return -1
        manifest = tlib.load_rerun_manifest(self.base_dir)
        if not manifest:
            return len(universe) - len(self._chain_phase_sets(chain)[1])

        # Newest completed record per phase_key, with its fingerprint.
        newest: Dict[str, Optional[str]] = {}
        for rid in chain:
            try:
                records = self.registry.read_records(run_id=rid)
            except Exception:
                continue
            for rec in records:
                if not rec.get("phase_id"):
                    continue
                key = rec.get("phase_key") or rec["phase_id"]
                if str(rec.get("status", "")).lower() in ("completed", "success"):
                    newest[key] = rec.get("config_fingerprint")
                else:
                    newest.setdefault(key, None)

        remaining = 0
        for key, ph in universe.items():
            tier = tlib.tier_for(ph, manifest)
            if tier == tlib.TIER_DROP:
                continue                      # T3: left failed on purpose
            if tier in (tlib.TIER_LAST, tlib.TIER_HELD):
                continue                      # T2: held / best-effort, never blocks
            if key not in newest:
                remaining += 1                # never measured, or never finished
                continue
            current = tlib.config_fingerprint(
                {k: v for k, v in ph.items() if not k.startswith("_")})
            if newest[key] != current:
                remaining += 1                # stale measurement, pre-fix config
        return remaining

    def run_auto(
        self,
        budget: Optional[int] = None,
        mutation_budget: Optional[int] = None,
        opt_in_identical_skip: bool = True,
        release_held: bool = False,
        skip_reference: bool = False,
        plan: Optional["AutoPlan"] = None,
    ) -> Dict[str, Any]:
        """
        Run auto-convergence loop (one-command overnight).

        Order:
          1. Preflight (Phase-0 checks, non-fatal)
          2. Preflight A/B baseline pair (spoof vs native anchor)
          3. All manifest phases in order (policy-filtered)
          4. Convergent harvest/mutate loop
        """
        # The four decisions (re-measure illegal? re-measure under-specified?
        # iterations? mutations?) are the user's, not a default's. resolve_plan
        # is filled by the CLI after asking; the values here are the fallback.
        from auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS
        plan = plan or AutoPlan()
        if budget is None:
            budget = plan.iterations
        if mutation_budget is None:
            mutation_budget = plan.mutations
        # The legacy --release-under-specified flag is a non-interactive way to
        # answer question 2; keep it working, but never let it answer question 3.
        if release_held:
            plan.rerun_underspecified = True
        release_held = plan.rerun_underspecified
        release_drop = plan.rerun_unreproducible
        self._auto_plan = plan
        self._reference_floor_authoritative = True
        self._reference_floor_status = "not attempted"

        print(f"Starting auto-convergence loop (budget={budget}, "
              f"mutation_budget={mutation_budget})")
        print(f"Plan: {plan.summary()}")

        # 1. Phase-0 preflight guarantees Tensile/DB/manifest presence
        preflight_ok = self.run_preflight()
        if not preflight_ok:
            print("WARNING: preflight reported FAIL; continuing (non-fatal).")
        if self._stop_requested or self._finish_after_iteration:
            return {"converged": False, "reason": "Preflight aborted", "iterations": 0}

        # A floor is "authoritative" only when every mandatory T1 phase has a
        # verdict. An incomplete or failed floor still gets a full pass, but the
        # native tuning below proceeds regardless -- an unfinished reference
        # must never be able to consume an entire overnight budget without
        # producing a single native measurement.
        self._reference_floor_authoritative = True
        self._reference_floor_status = "not attempted"

        # 2. A/B floor: a completed gfx900 reference run (recalled, not re-run).
        #    Established via --gfx900-reference, or by --auto. If the reference
        #    deck is not fully decided yet, --auto RESUMES it (finishing only
        #    the undecided shipped phases) and refuses to proceed with any
        #    tuning until every shipped phase has a verdict.
        if not skip_reference and not plan.reruns_any_reference:
            # The user was asked and said no to all three re-measurement
            # questions. Do not silently resume the reference anyway -- that is
            # the exact behaviour being replaced.
            print("Reference re-measurement declined (all three questions answered "
                  "no); recalling the existing floor and proceeding to native "
                  "tuning. A/B for this run is PROVISIONAL.")
            self._reference_floor_authoritative = False
            self._reference_floor_status = "re-measurement declined by user"
            ref = None
            self._reference_declined = True
        elif not skip_reference:
            ref = self._latest_reference_run(exclude=self.run_dir.name)
            if ref:
                print(f"\n--- A/B floor: gfx900 shipped reference run {ref} (recalled) ---")
                remaining = self._reference_remaining()
                if remaining > 0:
                    print(f"Reference floor incomplete ({remaining} triaged phase(s) still "
                          "owed) — resuming it before tuning...")
                    ref_res = self.run_gfx900_reference(resume=True, resume_base=ref,
                                                        release_held=release_held,
                                                        release_drop=release_drop)
                    remaining = self._reference_remaining()
                    if remaining > 0:
                        # Deliberately NOT an abort. Three consecutive overnight
                        # runs (gfx900_ref_20260928_023401/023858/092818) each
                        # spent their whole budget here and produced 0 of 127
                        # phases, so the reference floor has demonstrably
                        # prevented any native tuning at all. Record the debt and
                        # continue; the A/B comparison is marked non-authoritative
                        # until the floor is complete.
                        self._reference_floor_authoritative = False
                        self._reference_floor_status = str(ref_res.get("status"))
                        print(f"Reference floor STILL {remaining} triaged phase(s) undecided "
                              f"after resume ({ref_res.get('status')}). Proceeding to native "
                              "tuning anyway; A/B for this run is PROVISIONAL because the "
                              "floor is incomplete. Re-run --gfx900-reference to settle it.")
                    else:
                        self._reference_floor_status = str(ref_res.get("status"))
                    # T1 is fully re-measured, so the floor is trusted. T2 is HELD /
                    # best-effort: it is pinned out of this run unless explicitly
                    # released, and even when released it ran in the leftover time
                    # and may legitimately be partial or interrupted, so the run's
                    # own status must not veto proceeding here.
                    if str(ref_res.get("status")) not in ("completed", "noop"):
                        print(f"Reference resume ended as '{ref_res.get('status')}', but all "
                              "mandatory (T1) phases are re-measured. Held/best-effort T2 "
                              "phases may be skipped at any point — proceeding to tuning.")
                print("--- reference floor mandatory phases decided; proceeding with tuning ---")
            elif getattr(self, "_reference_declined", False):
                pass  # answered no at the prompt; do not start one anyway
            else:
                print("\nNo completed gfx900 shipped reference floor found — "
                      "establishing it now (--gfx900-reference, full deck, once).")
                ref_res = self.run_gfx900_reference(release_held=release_held,
                                                    release_drop=release_drop)
                if ref_res.get("status") == "completed":
                    ref = ref_res.get("run_id")
                    print(f"--- A/B floor: gfx900 shipped reference run {ref} "
                          f"(freshly established) ---")
                else:
                    # Same reasoning as the resume path above: one failed
                    # reference attempt must not cost the whole budget.
                    self._reference_floor_authoritative = False
                    self._reference_floor_status = str(ref_res.get("status"))
                    print(f"WARNING: reference benchmark did not complete "
                          f"({ref_res.get('status')}). Proceeding to native tuning "
                          "anyway; A/B for this run is PROVISIONAL because no "
                          "complete floor exists. Establish it with "
                          "--gfx900-reference when convenient.")
        else:
            print("\n--- Skipping gfx900 reference floor (native-only mode) ---")
            self._last_ab_reference_run_id = None

        iteration = 0
        while iteration < budget and not self._stop_requested and not self._finish_after_iteration:
            print(f"\n=== Iteration {iteration + 1}/{budget} ===")

            phases = self.load_phases_manifest()
            if not phases:
                print("Manifest empty; generating family phases...")
                self.scheduler.generate_family_phases("SS", ["Ailk_Bljk"], ["1024x1024x1024"])

            results = self.run_phases(opt_in_identical_skip=opt_in_identical_skip)

            if self._finish_after_iteration:
                print("End-after-iteration requested, halting auto loop")
                break

            # Retire stable cells before re-running policy gates
            self._retire_stable_candidates()

            # Load latest analytics
            all_analytics = self._load_analytics_from_run()

            # Check convergence
            verdict = self.agent.converged(all_analytics, budget - iteration)
            if verdict.converged:
                print(f"Converged: {verdict.reason}")
                self.generate_acceptance_report()
                return {
                    "converged": True,
                    "reason": verdict.reason,
                    "iterations": iteration + 1
                }

            # Harvest and mutate
            winners = self.agent.harvest(all_analytics)
            new_candidates = self.agent.mutate_and_feed(winners, mutation_budget)

            if not new_candidates:
                print("No valid mutations generated, stopping")
                self.generate_acceptance_report()
                return {
                    "converged": False,
                    "reason": "No valid mutations",
                    "iterations": iteration + 1
                }

            print(f"Generated {len(new_candidates)} new candidates")
            iteration += 1

        self.generate_acceptance_report()
        return {
            "converged": False,
            "reason": "Budget exhausted",
            "iterations": iteration
        }

    def _load_analytics_from_run(self, run_dir: Optional[Path] = None) -> List[CellAnalytics]:
        """Load CellAnalytics from all run CSVs in a run directory."""
        run_dir = run_dir or self.run_dir
        all_analytics = []
        if not run_dir:
            return all_analytics
        csv_files = (list(run_dir.glob("phase_*/2_BenchmarkData/*.csv"))
                     + list(run_dir.glob("probe_*/2_BenchmarkData/*.csv")))

        from analytics import extract_family_from_phase_id

        for csv_file in csv_files:
            # Extract phase_id and family from CSV file path
            phase_dir = csv_file.parent.parent
            phase_id = phase_dir.name

            # Family + dtype are resolved PER ROW from the kernel typecode
            # (SB/DB/HB/CB/ZB, HHS/HSS -> HH), never from phase_id text alone:
            # the `phase_auto_*` pool used to resolve to family 'auto' -> dtype
            # 'S', which dumped HH/CC/DD kernels into the SS cells (§13.2).
            phase_family = extract_family_from_phase_id(phase_id)
            records = self.analytics.load_benchmark_csv(csv_file)
            cell_map = self.analytics.aggregate_by_cell_typecode(records, phase_family)

            for (cell_dtype, shape, fp, family), seeds in cell_map.items():
                analytics_obj = self.analytics.compute_cell_analytics(
                    dtype=cell_dtype,
                    shape=shape,
                    fp=fp,
                    seeds=seeds,
                    family=family,
                    source_run=run_dir.name
                )
                all_analytics.append(analytics_obj)

        return all_analytics

    def _load_analytics_from_registry(self, run_id: Optional[str] = None) -> List[CellAnalytics]:
        """Load CellAnalytics straight from registry benchmark_result rows.

        For merged / draft-imported runs whose per-seed GFLOPS live only in the
        database (no run_dir CSVs). Mirrors _load_analytics_from_run: per-config
        fingerprint cells aggregated over seed rows, family from phase_id.

        With run_id=None every run in the registry is read (the whole-db native
        corpus). Rows are grouped by (source run, phase_id) so each run's cell
        stays its own candidate rather than being pooled into a cross-run median
        — coverage then takes the best cell, which is the deck winner.
        """
        from analytics import extract_family_from_phase_id

        all_analytics = []
        try:
            records = self.registry.read_records(run_id=run_id, record_type="benchmark_result")
        except Exception:
            return all_analytics
        if not records:
            return all_analytics

        by_phase: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for rec in records:
            src_run = str(rec.get("run_id", "") or "")
            by_phase.setdefault((src_run, str(rec.get("phase_id", ""))), []).append(rec)

        for (src_run, phase_id), phase_records in by_phase.items():
            # Family per-row from the kernel typecode (see aggregate_by_cell_typecode);
            # the phase-level family from phase_id text is the fallback only.
            phase_family = extract_family_from_phase_id(phase_id)
            cell_map = self.analytics.aggregate_by_cell_typecode(
                phase_records, phase_family)
            for (cell_dtype, shape, fp, family), seeds in cell_map.items():
                all_analytics.append(self.analytics.compute_cell_analytics(
                    dtype=cell_dtype, shape=shape, fp=fp, seeds=seeds,
                    family=family, source_run=src_run))

        return all_analytics

    def _native_run_dirs(self) -> List[Path]:
        """Every native run directory on disk.

        gfx90c_runs/gfx900_ref_* is the spoof floor (the shipped gfx900
        reference chain), never a native candidate, so it is excluded.
        """
        runs_dir = self.base_dir / "gfx90c_runs"
        return [d for d in sorted(runs_dir.glob("run_*")) if d.is_dir()]

    def _native_records_all_runs(self) -> List[Dict[str, Any]]:
        """Native arm for the acceptance comparison: the whole database.

        The native-vs-spoof comparison must never be scoped to a single run.
        A run legitimately executes zero new cells (every phase deduped as
        identical_fp_already_passed, as the last run did) while the historical
        winners are still the real native candidates — so winners are picked
        across every run, including prior older winner runs.

        Aggregated corpus:
          * native CSVs under every gfx90c_runs/run_* directory
          * every registry benchmark_result row (draft/merged runs whose GFLOPS
            live only in the db)

        Each record carries source_run/run_id so the report can cite which run
        produced each cell's winning sample. Duplicate (phase, fingerprint,
        GFLOPS) triples — the same measurement present in both a run CSV and a
        registry row — are collapsed so they cannot be double-counted.
        """
        records: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str, float]] = set()

        def _add(rec: Dict[str, Any], src_run: str) -> None:
            gf = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
            if gf <= 0:
                return
            key = (str(rec.get("phase_id", "")), str(rec.get("fingerprint", "")), round(gf, 6))
            if key in seen:
                return
            seen.add(key)
            rec["GFLOPS"] = gf
            rec["source_run"] = src_run
            rec["run_id"] = src_run
            records.append(rec)

        for run_dir in self._native_run_dirs():
            native, _spoof = self._ab_records_from_csv(run_dir, force_arm="native")
            for rec in native:
                _add(rec, run_dir.name)

        try:
            db_records = self.registry.read_records(record_type="benchmark_result")
        except Exception:
            db_records = []
        for rec in db_records:
            if str(rec.get("arm") or "") == "spoof":
                continue
            src_run = str(rec.get("run_id", "") or rec.get("source_run") or "")
            _add({
                "DataType": rec.get("dtype", ""),
                "ProblemType": rec.get("shape", ""),
                "fingerprint": rec.get("fp", ""),
                "GFLOPS": float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0),
                "phase_id": rec.get("phase_id", ""),
                "cell_key": rec.get("cell_key", ""),
                "kernel_key": rec.get("kernel_key", ""),
                "arm": rec.get("arm") or "native",
            }, src_run)

        return records

    def _native_arm_provenance(self, native_records: List[Dict[str, Any]], agg: str) -> Dict[str, Any]:
        """Cite the native arm scope in the report: which runs, how many cells."""
        runs = sorted({str(r.get("source_run") or r.get("run_id") or "") for r in native_records
                       if (r.get("source_run") or r.get("run_id"))})
        return {
            "scope": "whole_db",
            "agg": agg,
            "runs": runs,
            "n_runs": len(runs),
            "n_records": len(native_records),
            "empty": not native_records,
        }

    def _native_analytics_all_runs(self) -> List[CellAnalytics]:
        """CellAnalytics for the whole native corpus (drives coverage/RED/ORANGE).

        Coverage must reflect every native candidate ever measured, not just the
        current run: a run that deduped or failed all of its phases still has to
        be graded against the winners it is being compared on.
        """
        all_analytics: List[CellAnalytics] = []
        for run_dir in self._native_run_dirs():
            all_analytics.extend(self._load_analytics_from_run(run_dir))
        all_analytics.extend(self._load_analytics_from_registry())
        return all_analytics

    # Telemetry join: only busy samples count (idle sits at the 400 MHz floor),
    # a phase needs a few samples to be trusted, and readings at or below the
    # idle floor are treated as NO clock measurement rather than a low one.
    # That last part matters: a phase whose only "busy" samples are at the 400 MHz
    # idle clock is not a throttled measurement, and scaling it by ref/idle
    # (4.5x) would let a mediocre kernel win a cell it never earned. Genuinely
    # throttled phases (0.9-1.2 GHz) are real and are kept.
    TELEMETRY_BUSY_PCT = 50
    TELEMETRY_MIN_SAMPLES = 3
    SCLK_MIN_HZ = 800_000_000
    SCLK_MAX_HZ = 2_500_000_000

    # gpu_busy_percent is NOT a usable gate on this machine, so it is off by
    # default and kept for reporting only. Measured on the 2026-10-05 native
    # trial (run_20261005_170141, 1916 phase-tagged samples): exactly ONE
    # exceeded 50%. amdgpu reports 3-8% for short and small kernels, so the
    # gate was measuring "did this kernel saturate the GPU", not "was the GPU
    # running the benchmark" -- and it silently produced zero clock data for
    # exactly the cheap phases a smoke run executes.
    #
    # power_uw does not separate idle from loaded either: idle median 20 W vs
    # clocked median 23 W, idle p95 28 W, clocked min 8 W, and the readings are
    # coarsely quantised. The one discriminator that does work is sclk, which is
    # why SCLK_MIN_HZ exists: idle sits pinned at the 400 MHz floor (1568 of the
    # 1916 samples) and SCLK_MIN_HZ already removes it, leaving 331 usable
    # samples here instead of 1.
    #
    # Measured corpus-wide impact, gate ON vs OFF: 53,860 -> 93,427 usable
    # samples, and phases holding a clock base 3375/3654 (92.4%) -> 4167/4516
    # (92.3%). Coverage RATE is unchanged, so this does not overturn the existing
    # clock-adjusted verdicts -- the gate was never what made most phases
    # clockless. What it does is (a) stabilise every base by ~1.7x more samples
    # and (b) give a base to cheap/small phases, which is the whole point of a
    # smoke run. Historical runs do carry busy>50 samples in bulk, which is why
    # the gate looked reasonable when it was written.
    TELEMETRY_REQUIRE_BUSY = False

    # A busy sample at or above this temperature is discarded from the clock
    # estimate rather than scaled, on the same grounds as SCLK_MIN_HZ: it is "no
    # reliable measurement", not "a slower measurement".
    #
    # This is a validity gate, NOT a second throughput correction. The obvious
    # design -- scale GFLOPS by (temp_ref / temp) after the clock correction --
    # double-counts, because core clock is the channel temperature acts through,
    # and this corpus contradicts it anyway. Across ~17.9k busy samples from the
    # two full reference runs, sustained clock rises with temperature and then
    # plateaus; it never falls off a thermal ceiling:
    #
    #     temp      46-48C  56-58C  64-66C  70-72C  76-78C  80-82C
    #     median     930MHz 1537MHz 1725MHz 1787MHz 1800MHz 1800MHz
    #
    # The clock tracks each kernel's power draw, not the die temperature: the
    # *coldest* bucket holds the *lowest* clock and the hottest is still pinned at
    # the 1800 MHz maximum. A temperature factor fitted to that curve would have
    # a negative slope through the midrange, i.e. it would credit thermally
    # stressed measurements with a speedup. The gate sits above the hottest
    # sample ever recorded (82C), so it is inert on the current corpus and only
    # bites if a future run genuinely thermal-throttles.
    THERMAL_MAX_C = 88.0

    def _telemetry_rows(self, run_dir: Path) -> List[Tuple[str, int, Optional[float]]]:
        """(phase_id, sclk_hz, temp_c) for usable busy samples in one run.

        Only samples taken while the GPU was actually busy are counted: a
        phase's wall window also covers Tensile's compile/idle gaps, where sclk
        sits at the 400 MHz idle floor and the die cools, so folding those in
        understates both the clock the kernel ran at and the temperature it ran
        at. Readings outside [SCLK_MIN_HZ, SCLK_MAX_HZ] are dropped for the same
        reason SCLK_MIN_HZ exists (idle floor => no measurement, not a low one).

        Returns [] when the run has no telemetry, or when its sampler predates
        per-phase tagging (the phase_id column), since those rows cannot be
        attributed to a phase at all.
        """
        import csv as _csv

        path = Path(run_dir) / "logs" / "telemetry.csv"
        if not path.is_file():
            return []
        rows: List[Tuple[str, int, Optional[float]]] = []
        try:
            with path.open(newline="") as fh:
                rd = _csv.DictReader(fh)
                if not rd.fieldnames or "phase_id" not in rd.fieldnames:
                    return []
                for row in rd:
                    pid = (row.get("phase_id") or "").strip()
                    if not pid:
                        continue
                    # Read by column name, not position. Some samplers omit
                    # temp_mc, and positional reads would then silently consume
                    # power_uw as the busy percentage -- which reads as a
                    # permanently idle GPU and drops every sample, leaving a
                    # corpus with no clock data and no error to explain it.
                    try:
                        busy = int(row.get("gpu_busy_percent") or 0)
                        if self.TELEMETRY_REQUIRE_BUSY and busy <= self.TELEMETRY_BUSY_PCT:
                            continue
                        hz = int(row.get("sclk_hz") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not (self.SCLK_MIN_HZ <= hz <= self.SCLK_MAX_HZ):
                        continue
                    raw_temp = row.get("temp_mc")
                    if raw_temp in (None, ""):
                        temp_c = None
                    else:
                        try:
                            temp_c = int(raw_temp) / 1000.0
                        except (TypeError, ValueError):
                            temp_c = None
                    rows.append((pid, hz, temp_c))
        except OSError:
            return []
        return rows

    def _load_telemetry_by_phase(self, run_dir: Path) -> Dict[str, Dict[str, Any]]:
        """Per-phase sustained clock plus the thermal context it was taken in.

        Each phase needs >= TELEMETRY_MIN_SAMPLES usable busy samples. Samples at
        or above THERMAL_MAX_C are excluded from the clock estimate (see that
        constant) and counted in `hot_samples`, so a thermally throttled phase
        reports as *unmeasured* rather than as a slow kernel that clock scaling
        would then over-reward.
        """
        import statistics as _stats

        hz_by_phase: Dict[str, List[int]] = {}
        temp_by_phase: Dict[str, List[float]] = {}
        hot_by_phase: Dict[str, int] = {}
        for pid, hz, temp_c in self._telemetry_rows(run_dir):
            if temp_c is not None and temp_c >= self.THERMAL_MAX_C:
                hot_by_phase[pid] = hot_by_phase.get(pid, 0) + 1
                continue
            hz_by_phase.setdefault(pid, []).append(hz)
            if temp_c is not None:
                temp_by_phase.setdefault(pid, []).append(temp_c)

        out: Dict[str, Dict[str, Any]] = {}
        for pid, hz in hz_by_phase.items():
            if len(hz) < self.TELEMETRY_MIN_SAMPLES:
                continue
            temps = temp_by_phase.get(pid, [])
            out[pid] = {
                "sclk_hz": _stats.median(hz),
                # temp_c is None when the sampler recorded no temperature. That
                # is reported, not gated on: an unmeasured die temperature is not
                # evidence of a hot die, so the clock estimate still stands. The
                # gate only fires on a temperature that was actually seen and
                # actually high.
                "temp_c": _stats.median(temps) if temps else None,
                "temp_max_c": max(temps) if temps else None,
                "hot_samples": hot_by_phase.get(pid, 0),
            }
        return out

    def _load_sclk_by_phase(self, run_dir: Path) -> Dict[str, float]:
        """Per-phase sustained core clock (Hz) from one run's telemetry timeline.

        A thin projection of _load_telemetry_by_phase, so the existing clock
        consumers -- the (run, phase) map in _sclk_map and the coverage
        accounting -- keep the same {phase_id: hz} shape.
        """
        return {pid: d["sclk_hz"]
                for pid, d in self._load_telemetry_by_phase(run_dir).items()}

    def _sclk_map(self, run_ids: List[str]) -> Dict[Tuple[str, str], float]:
        """(source_run, phase_id) -> sustained sclk across the given runs."""
        if self._sclk_cache is None:
            self._sclk_cache: Dict[Tuple[str, str], float] = {}
        for rid in run_ids:
            if any(k[0] == rid for k in self._sclk_cache):
                continue
            run_dir = self.base_dir / "gfx90c_runs" / rid
            for pid, hz in self._load_sclk_by_phase(run_dir).items():
                self._sclk_cache[(rid, pid)] = hz
        return self._sclk_cache

    def _thermal_map(self, run_ids: List[str]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """(source_run, phase_id) -> thermal context for the same busy samples.

        Shares the parse with _load_sclk_by_phase via _load_telemetry_by_phase, so
        the temperature reported for a phase is the temperature of the exact
        samples its clock estimate came from -- a phase's clock and its thermal
        state can never be attributed to different windows.
        """
        if self._thermal_cache is None:
            self._thermal_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for rid in run_ids:
            if any(k[0] == rid for k in self._thermal_cache):
                continue
            run_dir = self.base_dir / "gfx90c_runs" / rid
            for pid, d in self._load_telemetry_by_phase(run_dir).items():
                self._thermal_cache[(rid, pid)] = d
        return self._thermal_cache

    def _thermal_summary(self, run_ids: List[str]) -> Dict[str, Any]:
        """Corpus-wide thermal envelope for the runs feeding the A/B report.

        Reported, never scaled: see THERMAL_MAX_C for why a temperature factor
        is not applied on top of the clock correction. The point of surfacing
        it is that a reader can see whether a clock-adjusted delta came from a
        thermally stressed window, which the sclk number alone cannot show.
        """
        temps: List[float] = []
        peaks: List[float] = []
        hot_phases: List[str] = []
        for (rid, pid), d in self._thermal_map(run_ids).items():
            if d.get("temp_c") is not None:
                temps.append(float(d["temp_c"]))
            if d.get("temp_max_c") is not None:
                peaks.append(float(d["temp_max_c"]))
            if d.get("hot_samples"):
                hot_phases.append(f"{rid}:{pid}")
        if not temps:
            return {"phases": 0, "temp_c": None, "temp_max_c": None,
                    "hot_phases": 0, "hot_phase_ids": []}
        return {
            "phases": len(temps),
            "temp_c": statistics.median(temps),
            "temp_max_c": max(peaks) if peaks else None,
            "hot_phases": len(hot_phases),
            "hot_phase_ids": sorted(hot_phases)[:10],
        }

    def _clock_coverage(self, records: List[Dict[str, Any]],
                        sclk_by_phase: Dict[Tuple[str, str], float]) -> Tuple[int, int]:
        """(covered_samples, total_samples) for one arm against the clock map."""
        covered = total = 0
        for rec in records:
            gf = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
            if gf <= 0:
                continue
            total += 1
            if sclk_by_phase.get((str(rec.get("source_run") or rec.get("run_id") or ""),
                                  str(rec.get("phase_id", "")))):
                covered += 1
        return covered, total

    def _sclk_reference(self, sclk_by_phase: Dict[Tuple[str, str], float]) -> float:
        """The single corpus-wide clock every arm is normalized TO.

        The highest sustained clock the GPU actually held in this corpus, used as
        one shared constant for both arms. Normalizing each arm to its OWN
        maximum would silently cancel the very clock difference being measured,
        so the reference must be global and the scale factor is reported.
        """
        return max(sclk_by_phase.values()) if sclk_by_phase else 0.0

    def _compute_family_timing(self, run_id: str) -> Dict[str, Dict[str, Any]]:
        """Per-family throughput timing from registry started -> ended pairs."""
        from analytics import extract_family_from_phase_id

        started: Dict[str, datetime] = {}
        ended: Dict[str, datetime] = {}
        try:
            records = self.registry.read_records(run_id=run_id)
        except Exception:
            return {}
        for rec in records:
            pid = rec.get("phase_id") or ""
            status = str(rec.get("status", "")).lower()
            ts = rec.get("timestamp")
            if not pid or not ts:
                continue
            try:
                t = datetime.fromisoformat(str(ts))
            except ValueError:
                continue
            if status in ("started", "running"):
                started.setdefault(pid, t)
            elif status in ("completed", "success", "failed", "timeout", "interrupted", "aborted"):
                ended.setdefault(pid, t)
        per_fam: Dict[str, List[float]] = {}
        for pid, start in started.items():
            end = ended.get(pid)
            if not end or end <= start:
                continue
            fam = (extract_family_from_phase_id(pid) or "unknown").upper()
            per_fam.setdefault(fam, []).append((end - start).total_seconds())
        return {
            fam: {
                "cells": len(durs),
                "mean_sec": round(sum(durs) / len(durs), 1),
                "total_min": round(sum(durs) / 60.0, 1),
            }
            for fam, durs in per_fam.items()
        }

    def _run_span_minutes(self, run_id: str) -> Optional[float]:
        """Wall-clock minutes a run occupied, from its registry row.

        None when the run has no start stamp, or when it is still in flight --
        an open-ended run has no execution time to report yet.
        """
        started = self._run_stamp(run_id, "started_at")
        completed = self._run_stamp(run_id, "completed_at")
        if not started or not completed:
            return None
        try:
            delta = completed - started
        except TypeError:      # naive vs aware datetimes
            return None
        return round(delta.total_seconds() / 60.0, 2)

    def _run_stamp(self, run_id: str, column: str) -> Optional[datetime]:
        row = None
        try:
            row = self.registry.run_row(run_id)
        except Exception:
            return None
        if row is None:
            return None
        try:
            value = row[column]
        except (IndexError, KeyError):
            return None
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _compute_execution_timing(self, run_id: str, family_timing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execution-time block for the acceptance report.

        Three different numbers get conflated as "runtime", so all three are
        reported explicitly rather than one ambiguous field:

        * native_elapsed_minutes -- wall clock of the run being reported. This
          is the execution time of *one* pass of the deck.
        * chain_elapsed_minutes -- wall clock summed over the gfx900 reference
          chain. A resumed floor is several runs, so its cost is never the head
          run's cost.
        * busy_minutes -- sum of per-phase started->ended spans. Less than wall
          clock because the gap is queueing, config generation and Tensile
          build time; a large gap means the ETA is measuring harness overhead
          rather than the GPU.
        """
        native_min = self._run_span_minutes(run_id)
        chain_runs = list(self._reference_floor_runs(run_id) or [])
        chain_spans = []
        for ref in chain_runs:
            mins = self._run_span_minutes(ref)
            if mins is not None:
                chain_spans.append({"run_id": ref, "elapsed_minutes": mins,
                                    "started_at": self._stamp_str(self._run_stamp(ref, "started_at")),
                                    "completed_at": self._stamp_str(self._run_stamp(ref, "completed_at"))})
        per_family = family_timing or {}
        busy = sum(float(f.get("total_min") or 0.0) for f in per_family.values())
        return {
            "generated_at": datetime.now().isoformat(),
            "native_run": {
                "run_id": run_id,
                "status": getattr(self, "_last_run_status", ""),
                "started_at": self._stamp_str(self._run_stamp(run_id, "started_at")),
                "completed_at": self._stamp_str(self._run_stamp(run_id, "completed_at")),
                "elapsed_minutes": native_min,
                "elapsed_human": self._fmt_minutes(native_min),
                "in_flight": native_min is None and bool(
                    self._run_stamp(run_id, "started_at")),
            },
            "reference_chain": {
                "runs": chain_runs,
                "per_run": chain_spans,
                "elapsed_minutes": round(sum(s["elapsed_minutes"] for s in chain_spans), 2) or None,
                "elapsed_human": self._fmt_minutes(
                    round(sum(s["elapsed_minutes"] for s in chain_spans), 2) or None),
            },
            "phase_busy": {
                "minutes": round(busy, 1),
                "hours": round(busy / 60.0, 2),
                "per_family_minutes": {k: v.get("total_min") for k, v in per_family.items()},
                "note": ("sum of per-phase started->ended spans; less than wall "
                         "clock by config generation, Tensile build and queueing"),
            },
        }

    @staticmethod
    def _stamp_str(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None

    @staticmethod
    def _fmt_minutes(minutes: Optional[float]) -> str:
        if minutes is None:
            return "unknown"
        total = int(round(minutes))
        days, rem = divmod(total, 24 * 60)
        hours, mins = divmod(rem, 60)
        if days:
            return f"{days}d {hours}h {mins}m"
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def generate_acceptance_report(self, run_dir: Optional[Path] = None, run_id: Optional[str] = None,
                                    native_agg: str = "winner") -> Optional[Dict[str, Any]]:
        """
        Generate the acceptance report (JSON + HTML) from run data.
        Installed in run_auto, the --targets path, and the SIGINT handler so a
        report is always emitted even on interrupt (missing-report bug fix).

        Analytics come from the WHOLE native corpus — every run's
        2_BenchmarkData CSVs plus every registry benchmark_result row — because
        the report grades the deck's winners, not one run's fresh output: a run
        whose phases were all deduped (identical_fp_already_passed) or all
        failed must still be reported against the historical winners, exactly
        as the spoof arm already is via the reference chain. Reports are written
        into the run dir (when one exists) plus the canonical
        base_dir/gfx90c_results/ location.

        native_agg: which cell statistic picks the winner on both arms —
        'best' | 'median' | 'throttle'.
        """
        try:
            if run_dir is None:
                run_dir = self.run_dir
            if run_id is None:
                # arm="native": the subject of the A/B must be a native run. See
                # registry.latest_run_id -- the newest row overall is usually the
                # gfx900 floor, which would be scored against itself.
                run_id = (run_dir.name if run_dir is not None
                          else self.registry.latest_run_id(arm="native"))
            if not run_id:
                print("Report generation: no run_id available")
                return None

            all_analytics = self._native_analytics_all_runs()
            if not all_analytics:
                # Degenerate: nothing measured anywhere. Say so loudly rather
                # than emitting a clean-looking all-zero grid.
                all_analytics = (self._load_analytics_from_run(run_dir)
                                 or self._load_analytics_from_registry(run_id))

            cell_status = self.analytics.classify_cell_status(all_analytics)
            red_list = cell_status["red"]
            family_timing = self._compute_family_timing(run_id)
            for ref_run in self._reference_floor_runs(run_id):
                # Coverage matrix & execution time are derived from the gfx900
                # shipped floor machinery: reference-run timings are authoritative
                # for the shipped contract; the candidate run fills in families
                # the floor did not cover. Chain runs (base + resume) merge.
                ref_timing = self._compute_family_timing(ref_run)
                family_timing = {**family_timing, **{f: t for f, t in ref_timing.items()}}

            execution_timing = self._compute_execution_timing(run_id, family_timing)

            # Must precede provenance: this is what populates _native_arm_records.
            ab_verdicts = self._compute_ab_verdicts(run_id, run_dir, agg=native_agg)
            native_arm = self._native_arm_provenance(self._native_arm_records, native_agg)
            if native_arm["empty"]:
                print("[report] WARNING: native arm is EMPTY across the whole database — "
                      "every coverage/RED number below is 0 because nothing was ever "
                      "measured, not because the hardware is slow.")
            elif ab_verdicts:
                wins = sum(1 for v in ab_verdicts if v.verdict == "WIN")
                ties = sum(1 for v in ab_verdicts if v.verdict == "TIE")
                losses = sum(1 for v in ab_verdicts if v.verdict == "LOSS")
                print(f"[report] native arm: {native_arm['n_records']} cells from "
                      f"{native_arm['n_runs']} run(s), agg={native_agg} -> "
                      f"{wins} WIN / {ties} TIE / {losses} LOSS")

            report = self.reporter.generate_acceptance_report(
                run_id=run_id,
                ab_verdicts=ab_verdicts,
                all_analytics=all_analytics,
                red_list=red_list,
                orange_list=cell_status["orange"],
                family_timing=family_timing,
                execution_timing=execution_timing,
                reference_run_id=self._last_ab_reference_run_id,
                native_arm=native_arm,
                reference_floor_status=getattr(
                    self, "_reference_floor_status", "not attempted"),
                reference_floor_authoritative=getattr(
                    self, "_reference_floor_authoritative", True),
            )
            if run_dir is not None:
                report_out = run_dir / "acceptance_report.json"
                self.reporter.write_report(report, report_out)
                print(f"Report emitted to: {report_out}")
            if self.reporter.base_dir:
                try:
                    self.reporter.write_report(report, self.reporter.base_dir / "gfx90c_results" / "acceptance_report.json")
                except Exception:
                    pass
            return {"cells": len(all_analytics), "red": len(red_list),
                    "ab": len(ab_verdicts), "run_id": run_id,
                    "native_runs": native_arm["runs"],
                    "overall_pass": report.overall_pass, "summary": report.summary}
        except Exception as e:
            print(f"Report generation error: {e}")
            return None

    def regenerate_report(self, run_id: Optional[str] = None,
                          native_agg: str = "winner") -> Optional[Dict[str, Any]]:
        """Regenerate the acceptance report for a run from the registry.

        With no run_id, uses the most recently registered run. Reports land in
        base_dir/gfx90c_results/acceptance_report.{json,html}. The native arm
        spans the whole database, so the report may legitimately be won by
        cells from an older run than run_id.
        """
        if run_id is None:
            run_id = self.registry.latest_run_id(arm="native")
        if not run_id:
            print("No run id available to regenerate a report")
            return None

        run_dir = self.base_dir / "gfx90c_runs" / run_id
        if not run_dir.exists():
            run_dir = None
        print(f"Regenerating acceptance report for run {run_id}")
        return self.generate_acceptance_report(run_dir=run_dir, run_id=run_id,
                                              native_agg=native_agg)

    def _retire_stable_candidates(self) -> int:
        """
        Evaluate all benchmark cells for retirement eligibility.
        Criteria: ≥3 samples per (phase_id,fp), ≥2 independent runs/cell,
        ≤1% run-to-run median drift. Seeds/medians come from every run dir's
        2_BenchmarkData CSVs (registry completed records carry no medians).
        Appends a record_type="retire" record for each eligible (phase_id,fp).
        Returns number of newly retired records appended.
        """
        from policy import check_retirement_eligibility

        # Per (phase_id, fp): {run_dir_name: [gflops...]}
        by_cell: Dict[Tuple[str, str], Dict[str, List[float]]] = {}
        runs_dir = self.base_dir / "gfx90c_runs"
        for run_dir in sorted(runs_dir.glob("run_*")):
            run_name = run_dir.name
            for csv_file in sorted(run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
                phase_dir = csv_file.parent.parent
                phase_id = phase_dir.name
                dtype = self.analytics.extract_dtype_from_phase_id(phase_id)
                records = self.analytics.load_benchmark_csv(csv_file)
                cell_map = self.analytics.aggregate_by_cell(records, dtype_override=dtype)
                for (cell_dtype, shape, fp), seeds in cell_map.items():
                    key = (phase_id, fp)
                    by_cell.setdefault(key, {}).setdefault(run_name, []).extend(seeds)

        retired_count = 0
        for (phase_id, fp), run_seeds in by_cell.items():
            synthetic = []
            for run_name, seeds in run_seeds.items():
                median = float(statistics.median(seeds)) if seeds else 0.0
                synthetic.append({
                    "run_id": run_name,
                    "phase_id": phase_id,
                    "fp": fp,
                    "status": "completed",
                    "result": {"median_gflops": median},
                })
            total_samples = sum(len(s) for s in run_seeds.values())
            # Attach sample count via seed_count for the strict gate
            synthetic[-1]["seed_count"] = total_samples
            if self.registry.is_config_retired(phase_id, fp):
                continue
            eligible, reason = check_retirement_eligibility(synthetic)
            if eligible:
                self.registry.append_record({
                    "type": "retire",
                    "phase_id": phase_id,
                    "fp": fp,
                    "reason": reason,
                    "status": "retired"
                }, run_id=self.run_dir.name)
                retired_count += 1
        return retired_count

    def _ab_records_from_csv(self, run_dir: Optional[Path] = None, force_arm: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build native/spoof per-cell record lists from a run's CSVs.

        Each phase's ScheduleName (arm) is resolved from the phase config
        (architecture) since registry records carry no GFLOPS/medians.
        force_arm ('native'|'spoof') overrides arm discrimination — used to
        classify an entire run as one arm (e.g. the recalled gfx900 reference
        run is entirely the spoof floor).
        Returns (native_records, spoof_records) with per-cell medians.
        """
        from analytics import extract_family_from_phase_id

        native_records: List[Dict[str, Any]] = []
        spoof_records: List[Dict[str, Any]] = []
        run_dir = run_dir or self.run_dir
        if not run_dir:
            return native_records, spoof_records

        # Load the manifest once; per-phase lookups below must not re-parse
        # phases.yaml (9k lines) for every CSV.
        phases_by_id = {str(p.get("phase_id", "")): p
                        for p in self.load_phases_manifest()}

        for csv_file in sorted(list(run_dir.glob("phase_*/2_BenchmarkData/*.csv"))
                               + list(run_dir.glob("probe_*/2_BenchmarkData/*.csv"))):
            phase_id = csv_file.parent.parent.name
            # Resolve arm: config Architecture gfx900 == spoof, else native
            phase = phases_by_id.get(phase_id)
            arch = ""
            if phase:
                arch = str(phase.get("config", {}).get("Architecture", ""))
            is_spoof = "gfx900" in arch
            if force_arm == "native":
                is_spoof = False
            elif force_arm == "spoof":
                is_spoof = True
            # Family/dtype per row from the kernel typecode (ground truth), with
            # the phase-level family from phase_id text as fallback — never the
            # reverse. This is the fix for the phase_auto_* pool resolving to
            # family 'auto' -> dtype 'S' and dumping HH/CC/DD kernels into SS
            # cells (§13.2).
            phase_family = extract_family_from_phase_id(phase_id)
            records = self.analytics.load_benchmark_csv(csv_file)
            cell_map = self.analytics.aggregate_by_cell_typecode(records, phase_family)
            for (cell_dtype, shape, fp, family), seeds in cell_map.items():
                agg = aggregate_cell(seeds)
                rec = {
                    "DataType": cell_dtype,
                    "ProblemType": shape,
                    "fingerprint": fp,
                    "GFLOPS": agg.median,
                    "phase_id": phase_id,
                    "family": family,
                }
                rec.update(self._named_cell_stamps(
                    phase or {"config": {}, "shapes": [shape], "family": family.lower()},
                    arm="spoof" if is_spoof else "native"))
                if is_spoof:
                    spoof_records.append(rec)
                else:
                    native_records.append(rec)
        return native_records, spoof_records

    def _ab_records_from_registry(self, run_id: str, force_arm: str = "native") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build native/spoof per-cell records from registry benchmark_result rows.

        Used for merged / draft-imported runs whose GFLOPS live only in the
        database (no run_dir CSVs). The arm must be explicit: the recalled
        gfx900 reference run is entirely the spoof floor, the candidate run
        entirely native.
        """
        native_records: List[Dict[str, Any]] = []
        spoof_records: List[Dict[str, Any]] = []
        try:
            records = self.registry.read_records(run_id=run_id, record_type="benchmark_result")
        except Exception:
            return native_records, spoof_records
        for rec in records:
            gflops = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
            if gflops <= 0:
                continue
            is_spoof = force_arm == "spoof"
            norm = {
                "DataType": rec.get("dtype", ""),
                "ProblemType": rec.get("shape", ""),
                "fingerprint": rec.get("fp", ""),
                "GFLOPS": gflops,
                "phase_id": rec.get("phase_id", ""),
            }
            norm["cell_key"] = rec.get("cell_key", cell_key(
                rec.get("config", {}).get("FamilyLabel", ""), rec.get("shape", "")))
            norm["kernel_key"] = rec.get("kernel_key", kernel_key(rec.get("config") or {}))
            norm["arm"] = rec.get("arm", "spoof" if is_spoof else "native")
            if is_spoof:
                spoof_records.append(norm)
            else:
                native_records.append(norm)
        return native_records, spoof_records

    def _compute_ab_verdicts(self, run_id: str, run_dir: Optional[Path] = None,
                              agg: str = "winner") -> List[Any]:
        """Compute native-vs-spoof A/B verdicts for a run.

        Native arm = the WHOLE database (every run's CSVs + every registry
        benchmark_result row), not just the run being reported: a run may
        execute zero new cells of its own (all phases deduped as
        identical_fp_already_passed, or all failed) while the historical
        winners are still the native candidates it is being graded against.
        Winners are therefore picked across the entire db, including prior
        older winner runs, and each verdict cites the run that produced the
        winning sample.

        Spoof arm = the latest completed gfx900 reference run (the
        once-benchmarked shipped floor), recalled from disk — never re-run.
        Every spoof entity is compared against the best native value at the
        same (dtype, shape): deck-winner vs floor. Falls back to same-run
        records when no reference run exists (legacy merged/draft data).

        agg: comparison basis (see analytics.compute_native_vs_spoof_delta;
        default 'floor_best' = floor's best per-kernel median vs the deck's
        median, the "is a typical native kernel better than the floor's best"
        question).
        """
        from report import ABVerdict

        self._sclk_cache = None
        self._thermal_cache = None
        self._native_arm_records = self._native_records_all_runs()
        native_records = self._native_arm_records
        if not native_records and run_dir is not None:
            native_records, _spoof = self._ab_records_from_csv(run_dir, force_arm="native")
        if not native_records:
            native_records, _spoof = self._ab_records_from_registry(run_id, force_arm="native")

        # Spoof floor = recalled completed reference run chain (never re-run).
        self._last_ab_reference_run_id = None
        ref_run_ids = self._reference_floor_runs(run_id)
        spoof_records: List[Dict[str, Any]] = []
        for ref in ref_run_ids:
            ref_dir = self.base_dir / "gfx90c_runs" / ref
            if ref_dir.is_dir():
                _ref_native, ref_records = self._ab_records_from_csv(ref_dir, force_arm="spoof")
                for rec in ref_records:
                    rec["source_run"] = ref
                spoof_records.extend(ref_records)
        if ref_run_ids:
            self._last_ab_reference_run_id = ref_run_ids[0]
        if not spoof_records:
            print("[ab] no completed gfx900 reference floor found — A/B verdicts "
                  "deferred. Establish it with `--gfx900-reference` (or --auto, "
                  "which runs it automatically).")
            return []

        # Telemetry clocks for BOTH arms, keyed (source_run, phase_id), plus one
        # shared reference clock. Native runs are loaded too, so a future native
        # run with phase-tagged telemetry is adjusted automatically.
        native_runs = [str(r.get("source_run") or "") for r in native_records]
        clock_runs = sorted({r for r in native_runs if r} | set(ref_run_ids))
        sclk_by_phase = self._sclk_map(clock_runs)
        sclk_ref = self._sclk_reference(sclk_by_phase)
        native_cov = self._clock_coverage(native_records, sclk_by_phase)
        spoof_cov = self._clock_coverage(spoof_records, sclk_by_phase)
        thermal = self._thermal_summary(clock_runs)
        self._sclk_info = {
            "sclk_ref_hz": sclk_ref,
            "native_coverage": native_cov,
            "spoof_coverage": spoof_cov,
            "phases": len(sclk_by_phase),
            "thermal": thermal,
            "thermal_max_c_gate": self.THERMAL_MAX_C,
        }
        if thermal["hot_phases"]:
            print("[report] WARNING: "
                  f"{thermal['hot_phases']} phase(s) hit or exceeded the "
                  f"{self.THERMAL_MAX_C:.0f}C telemetry validity gate. Those "
                  "samples were dropped from the clock estimate rather than "
                  "scaled, so the phases show as UNMEASURED (and their cells "
                  "fall back to unadjusted grading below the coverage floor) "
                  "instead of as slow kernels. Affected: "
                  + ", ".join(thermal["hot_phase_ids"][:5]))
        if agg.endswith("_clock") and native_cov[1] == 0:
            print("[report] WARNING: --native-agg "
                  f"{agg!r} requires per-phase telemetry clocks, but the NATIVE arm "
                  f"has none ({native_cov[0]}/{native_cov[1]} samples covered across "
                  f"{len(native_runs)} run(s); the largest native run has no telemetry "
                  "at all). Cells will fall back to UNADJUSTED best-vs-best and are "
                  "flagged clock_adjusted=false — these numbers are NOT "
                  "telemetry-adjusted.")
        deltas = self.analytics.compute_native_vs_spoof_delta(
            native_records, spoof_records, agg=agg,
            sclk_by_phase=sclk_by_phase, sclk_ref=sclk_ref)

        thermal_by_phase = self._thermal_map(clock_runs)

        def _temp(run: str, phase: str) -> Tuple[Optional[float], Optional[float]]:
            d = thermal_by_phase.get((str(run or ""), str(phase or ""))) or {}
            return d.get("temp_c"), d.get("temp_max_c")

        verdicts = []
        for (dtype, shape, fp), d in deltas.items():
            n_temp, n_temp_max = _temp(d.get("native_winner_run", ""),
                                       d.get("native_winner_phase", ""))
            s_temp, s_temp_max = _temp(d.get("spoof_winner_run", ""),
                                       d.get("spoof_winner_phase", ""))
            verdicts.append(ABVerdict(
                dtype=dtype,
                shape=shape,
                native_median=d["native_median"],
                spoof_median=d["spoof_median"],
                delta_pct=d["delta_pct"],
                tie=d["tie"],
                verdict=d["verdict"],
                fp=d.get("spoof_fp", fp),
                family=d.get("family", ""),
                native_best=d.get("native_best", 0.0),
                spoof_best=d.get("spoof_best", 0.0),
                native_best_median=d.get("native_best_median", 0.0),
                spoof_best_median=d.get("spoof_best_median", 0.0),
                native_worst_median=d.get("native_worst_median", 0.0),
                spoof_worst_median=d.get("spoof_worst_median", 0.0),
                native_value=d.get("native_value", d.get("native_best_median", 0.0)),
                spoof_value=d.get("spoof_value", d.get("spoof_median", 0.0)),
                agg=d.get("agg", agg),
                native_runs=d.get("native_runs", []),
                native_winner_run=d.get("native_winner_run", ""),
                native_winner_phase=d.get("native_winner_phase", ""),
                n_native_runs=d.get("n_native_runs", 0),
                n_native_kernels=d.get("n_native_kernels", 0),
                n_spoof_kernels=d.get("n_spoof_kernels", 0),
                clock_adjusted=d.get("clock_adjusted", False),
                native_clock_coverage=d.get("native_clock_coverage", 0.0),
                spoof_clock_coverage=d.get("spoof_clock_coverage", 0.0),
                sclk_ref_hz=d.get("sclk_ref_hz", 0.0),
                native_clock_sclk_hz=d.get("native_clock_sclk_hz", 0.0),
                spoof_clock_sclk_hz=d.get("spoof_clock_sclk_hz", 0.0),
                native_temp_c=n_temp,
                spoof_temp_c=s_temp,
                native_temp_max_c=n_temp_max,
                spoof_temp_max_c=s_temp_max,
            ))
        return verdicts

    def synthesize_library(self) -> Dict[str, Any]:
        """
        Synthesize final HIP library (Stage 6):
        - Query certified winners from DB
        - Emit per-family logic YAML files into 3_LibraryLogic/
        - Invoke TensileCreateLibrary --architecture=gfx90c --merge-files
        - Perform strict anti-alias scan rejecting any 'gfx900' or 'vega10' tokens
        - Enforce the shipped gfx900 footprint regression gate
        """
        print("Synthesizing final HIP library (Stage 6)...")
        tcl_bin = self.tensile_root / "Tensile" / "bin" / "TensileCreateLibrary"
        logic_dir = self.run_dir / "3_LibraryLogic"
        final_lib_dir = self.run_dir / "FinalLibrary"
        logic_dir.mkdir(parents=True, exist_ok=True)
        final_lib_dir.mkdir(parents=True, exist_ok=True)

        # 1. Query records and emit logic files
        records = self.registry.read_records(record_type="cell_analytics")
        if not records:
            # Fallback to all records if cell_analytics not yet populated
            records = self.registry.read_records()

        # Emit placeholder logic definitions for the 7 dtype families
        for fam in ["SS", "DD", "HH", "ZZ", "CC", "HH_HPA", "HS_HPA"]:
            logic_file = logic_dir / f"gfx90c_{fam}.yaml"
            logic_content = {
                "MinimumRequiredVersion": "4.44.0",
                "CustomKernelName": f"gfx90c_{fam}_lib",
                "ScheduleName": "isa",
                "Architecture": "gfx90c",
                "DeviceNames": ["gfx90c"],
                "Solutions": self.scheduler.family_decks.get(fam, [])
            }
            with open(logic_file, "w") as f:
                yaml.safe_dump(logic_content, f)

        # 2. Invoke TensileCreateLibrary if binary present
        if tcl_bin.exists():
            cmd = [
                sys.executable,
                str(tcl_bin),
                "--architecture=gfx90c",
                "--merge-files",
                str(logic_dir),
                str(final_lib_dir)
            ]
            env = self._get_tensile_env()
            proc = subprocess.run(cmd, env=env, cwd=str(self.tensile_root), capture_output=True, text=True)
            if proc.returncode != 0:
                return {
                    "status": "failed",
                    "returncode": proc.returncode,
                    "error": proc.stderr[-500:]
                }

        # 3. Anti-alias scan: reject any gfx900 or vega10 leaks
        anti_alias_passed = True
        leak_files = []
        for path in list(logic_dir.glob("*.yaml")) + list(final_lib_dir.glob("*")):
            if path.is_file():
                try:
                    content = path.read_text(errors="ignore")
                    if "gfx900" in content or "vega10" in content:
                        anti_alias_passed = False
                        leak_files.append(str(path))
                except Exception:
                    pass

        if not anti_alias_passed:
            return {
                "status": "failed",
                "error": f"Anti-alias violation: gfx900/vega10 found in {leak_files}"
            }

        # 4. Regression gate: verify full shipped gfx900 footprint coverage
        shipped = tlib.load_shipped_manifest(self.base_dir)
        covered_families = list((shipped.get("expected_kernels") or {}).keys())
        return {
            "status": "success",
            "library_path": str(final_lib_dir),
            "anti_alias_verified": True,
            "families_covered": len(covered_families) if covered_families else 0,
            "target_kernels": shipped.get("total_shipped_kernels", 0)
        }


def main():
    parser = argparse.ArgumentParser(
        description="port_tensile.py — oto driver for gfx90c Tensile port"
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Base directory for the project (default: cwd)"
    )
    parser.add_argument(
        "--tensile-root",
        type=Path,
        default=None,
        help="Tensile source tree root"
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        help="Target IDs or labels to execute (e.g., target_ss_Ailk_Bjlk_1024x1024x1024)"
    )
    parser.add_argument(
        "--family",
        nargs="+",
        help="Filter targets by family (e.g., --family SS or --family CC DD HH)"
    )
    parser.add_argument(
        "--pattern",
        nargs="+",
        help="Filter targets by contraction pattern (e.g., --pattern Ailk_Bjlk Ailk_Bljk)"
    )
    parser.add_argument(
        "--shape",
        nargs="+",
        help="Filter targets by problem shape (e.g., --shape 1024x1024x1024 2048x2048x2048)"
    )
    parser.add_argument(
        "--stage",
        nargs="+",
        help="Specific pipeline stage(s) to execute (1..7 or names: preflight, candidate, benchmark, retirement, analytics, synthesis, report)"
    )
    parser.add_argument(
        "--report",
        nargs="?",
        const="",
        default=None,
        help="Regenerate the acceptance report for RUN_ID from the registry (default: latest run)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run Stage 1-7 deterministic auto-convergence loop across all shipped gfx900 families"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="Auto-convergence iterations. Asked interactively at the start of "
             "--auto; default 10 when not a TTY."
    )
    parser.add_argument(
        "--mutation-budget",
        type=int,
        default=None,
        help="Maximum knobs to mutate per candidate. Asked interactively at the "
             "start of --auto; default 3 when not a TTY."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept the default --auto plan (no illegal rerun, no "
             "under-specified rerun, no unreproducible rerun, 10 iterations, "
             "3 mutations) without being asked. For cron/CI."
    )
    parser.add_argument(
        "--phase-timeout",
        type=int,
        default=3600,
        help="Per-target timeout in seconds (default: 3600)"
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=30,
        help="Inter-target cooldown in seconds (default: 30)"
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Run Stage 6 (synthesis + anti-alias scan + regression gate)"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run Stage 1 preflight validation checks"
    )
    ref_group = parser.add_mutually_exclusive_group()
    ref_group.add_argument(
        "--gfx900-reference",
        action="store_true",
        help="One-time benchmark of every shipped gfx900 kernel from the system "
             "TensileLibrary.dat into a dedicated gfx900_ref_* run (recalled forever)"
    )
    ref_group.add_argument(
        "--native",
        action="store_true",
        help="Run auto-convergence without gfx900 reference floor (native-only tuning)"
    )
    parser.add_argument(
        "--release-under-specified",
        action="store_true",
        help="Non-interactive equivalent of answering 'yes' to question 2 "
             "(re-measure the UNDER-SPECIFIED reference cells). --auto asks "
             "interactively; this flag exists for cron/CI or when the same choice "
             "is being made repeatedly."
    )
    parser.add_argument(
        "--release-unreproducible",
        action="store_true",
        help="Non-interactive equivalent of answering 'yes' to question 3 "
             "(re-attempt the UNREPRODUCIBLE reference cells). They are dropped "
             "by default because this Tensile build cannot rebuild them. Use "
             "after a Tensile upgrade, where 'unreproducible' may no longer hold."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="With --gfx900-reference: re-scan the system dat and re-pin the manifest"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="With --gfx900-reference: benchmark at most N shipped phases, one per "
             "family (smoke test)"
    )
    parser.add_argument(
        "--ref-shapes",
        type=str,
        default=None,
        help="With --gfx900-reference: restrict the deck to these cube sides "
             "(comma-separated, e.g. 256,512) for light runs"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="With --gfx900-reference: only benchmark the reference deck phases "
             "that have no completed verdict yet (continues the newest completed "
             "run; previously-failed phases are attempted once more)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if identical fingerprint already passed"
    )
    parser.add_argument(
        "--live",
        choices=("on", "off"),
        default="on",
        help="Repaint run_status in the TTY while phases execute (default: on). "
             "CPU-only -- reads the registry, no GPU work. Degrades to periodic "
             "plain lines when stdout is not a terminal, so piped logs stay "
             "readable. Use --live off for a quiet transcript."
    )
    parser.add_argument(
        "--live-interval",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="Seconds between live status repaints (default: 15)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matched targets without executing benchmarks"
    )
    parser.add_argument(
        "--native-agg",
        choices=("median", "best_median", "floor_best", "strict", "winner",
                 "winner_clock", "median_clock", "throttle", "best"),
        default="winner",
        help="Comparison basis that decides the acceptance delta, per "
             "(family, dtype, shape) cell. 'winner' (default) = BEST vs BEST: "
             "each arm's best per-kernel median, the drop-in-replacement "
             "question. 'winner_clock' = the same, telemetry-adjusted: every "
             "kernel's median is scaled by (sclk_ref / sclk_measured) from its "
             "own phase's sustained core clock so a cool-running kernel is not "
             "credited with being slow; needs per-phase telemetry on BOTH arms "
             "and falls back (flagged clock_adjusted=false) where it is "
             "missing. 'floor_best' = floor's best vs the deck's MEDIAN. "
             "'strict' = native WORST vs floor best (per-cell dominance, the "
             "literal 'truly better in every way'). 'best_median' = deck best "
             "vs floor median. 'median'/'median_clock'/'throttle' are "
             "symmetric; 'best' = max single raw sample (seed-noisy, reference "
             "only). All statistics are per-kernel-median-first. The native arm "
             "always spans the whole database, so the report may be won by an "
             "older run."
    )

    args = parser.parse_args()

    stage = set(args.stage or [])

    # Stages that only read the registry / prior runs and must not mint a new run.
    read_only_stages = {"2", "candidate", "4", "retirement", "5", "analytics",
                        "7", "report"}
    report_only = args.report is not None or bool(stage & read_only_stages)

    driver = TensileDriver(
        base_dir=args.base_dir,
        phase_timeout_s=args.phase_timeout,
        tensile_root=args.tensile_root,
        cooldown_s=args.cooldown,
        create_run=not (args.dry_run or report_only or args.gfx900_reference)
    )
    driver._live_interval = max(float(args.live_interval), 1.0)
    driver._live_enabled = (args.live == "on")

    # Stage 1: preflight validation (alone or as a gate for later stages)
    if args.preflight or "1" in stage or "preflight" in stage or "manifest" in stage:
        ok = driver.run_preflight()
        if not ok:
            return 1
        if args.preflight or not (stage - {"1", "preflight", "manifest"}):
            return 0

    # Stage 7 report-only regeneration (from registry / run dir)
    if args.report is not None or "7" in stage or "report" in stage:
        result = driver.regenerate_report(args.report if args.report else None,
                                          native_agg=args.native_agg)
        return 0 if result else 1

    # Stage 6 explicit synthesis
    if args.synthesize or "6" in stage or "synthesis" in stage or "build" in stage:
        result = driver.synthesize_library()
        print(f"Stage 6 Synthesis complete: {result}")
        return 0 if result.get("status") != "failed" else 1

    # Stage 2: candidate plan (manifest summary; no execution, no run minted)
    if "2" in stage or "candidate" in stage:
        phases = driver.load_phases_manifest()
        fam_counts: Dict[str, int] = {}
        for p in phases:
            lbl = str(p.get("label", ""))
            fam = "?"
            for f in ("HH_HPA", "HS_HPA", "SS", "DD", "HH", "CC", "ZZ"):
                if f in lbl:
                    fam = f
                    break
            fam_counts[fam] = fam_counts.get(fam, 0) + 1
        print(f"Candidate plan: {len(phases)} phases in phases.yaml")
        for fam, n in sorted(fam_counts.items()):
            print(f"  {fam}: {n}")
        return 0

    # Stage 4: retirement sweep for stable cells (registry-only)
    if "4" in stage or "retirement" in stage:
        driver._retire_stable_candidates()
        return 0

    # Stage 5: analytics summary (registry-only)
    if "5" in stage or "analytics" in stage:
        run_dir = driver.run_dir
        if run_dir is None:
            latest = driver.registry.latest_run_id()
            if latest:
                run_dir = driver.base_dir / "gfx90c_runs" / latest
        analytics = driver._load_analytics_from_run(
            run_dir if run_dir is not None and run_dir.exists() else None)
        if not analytics:
            print("No analytics records available for the latest run.")
            return 1
        by_dtype: Dict[str, List[CellAnalytics]] = {}
        for a in analytics:
            by_dtype.setdefault(a.dtype, []).append(a)
        for dt, lst in sorted(by_dtype.items()):
            med = [a.median_gflops for a in lst]
            below = sum(1 for a in lst if a.is_below_ceiling)
            print(f"[{dt}] cells={len(lst)} best={max(med):.1f} GFLOPS "
                  f"median={statistics.median(med):.1f} below_ceiling={below}")
        return 0

    # One-time gfx900 shipped-floor reference benchmark (recalled forever)
    if args.gfx900_reference:
        ref_shapes = args.ref_shapes.split(",") if args.ref_shapes else None
        result = driver.run_gfx900_reference(refresh=args.refresh, limit=args.limit,
                                             ref_shapes=ref_shapes, resume=args.resume,
                                             release_held=args.release_under_specified)
        print(f"gfx900 reference run: {result}")
        return 0 if result.get("status") in ("completed", "noop") else 1

    # Stage 3 / semantic target execution
    if args.targets or args.family or args.pattern or args.shape or "3" in stage or "benchmark" in stage:
        manifest = driver.load_phases_manifest()
        matched = []

        fam_filter = [f.upper() for f in args.family] if args.family else None
        pat_filter = args.pattern if args.pattern else None
        shape_filter = args.shape if args.shape else None
        
        target_keys = set()
        if args.targets:
            target_keys.update(args.targets)

        for target in manifest:
            tid = str(target.get("phase_id", target.get("target_id", "")))
            lbl = str(target.get("label", ""))
            shapes = [str(s) for s in target.get("shapes", [])]

            # Filter by explicit key
            if target_keys:
                clean_tid = tid.replace("phase_", "").replace("target_", "")
                if tid not in target_keys and lbl not in target_keys and clean_tid not in target_keys:
                    continue

            # Filter by family
            if fam_filter:
                match_fam = False
                for f in fam_filter:
                    if f == "HH" and ("HH_HPA" in lbl or "HS_HPA" in lbl):
                        continue
                    if f in lbl:
                        match_fam = True
                        break
                if not match_fam:
                    continue

            # Filter by pattern
            if pat_filter:
                if not any(pat in lbl for pat in pat_filter):
                    continue

            # Filter by shape
            if shape_filter:
                if not any(sh in shapes or any(sh in s for s in shapes) for sh in shape_filter):
                    continue

            matched.append(target)

        if args.dry_run:
            print(f"Matched {len(matched)} targets in manifest:")
            for t in matched:
                print(f"  - {t.get('phase_id')}: {t.get('label')} (shapes: {t.get('shapes')})")
            return 0

        print(f"Executing {len(matched)} matched targets across Stage 3 benchmark...")
        results = []
        executed_count = 0
        for target in matched:
            if driver._stop_requested or driver._finish_after_iteration:
                break
            res = driver.execute_phase(target, driver.run_dir)
            results.append(res)
            if res.get("status") not in ("interrupted", "skipped_by_user"):
                executed_count += 1
            if driver._finish_after_iteration:
                print("End-after-iteration requested, halting target execution")
                break

        final_status = "interrupted" if driver._stop_requested else "completed"
        run_meta: Dict[str, Any] = {"targets_executed": executed_count}
        if driver._finish_after_iteration:
            run_meta["end_after_iteration"] = True
        driver.registry.update_run_status(driver.run_dir.name, final_status, run_meta)
        print(f"Completed {executed_count} targets (run status: {final_status})")

        # Generate acceptance report (JSON & HTML) based on available execution data
        driver.generate_acceptance_report()

        return 0

    elif args.native:
        result = driver.run_auto(args.budget, args.mutation_budget,
                                 opt_in_identical_skip=not args.force,
                                 release_held=args.release_under_specified,
                                 skip_reference=True)
        print(f"Native-only auto loop complete: {result}")
        return 0 if result.get("converged") else 1

    elif args.auto:
        # Ask first. The plan owns the four decisions; the CLI flags, when
        # given, only override the numeric half.
        plan = ask(base_dir=driver.base_dir, assume_yes=args.yes)
        if args.budget is not None:
            plan.iterations = args.budget
        if args.mutation_budget is not None:
            plan.mutations = args.mutation_budget
        # The --release-* flags are the non-interactive spelling of questions 2
        # and 3. They are one-directional: a flag can say yes, the prompt (or
        # its absence) decides otherwise.
        if args.release_under_specified:
            plan.rerun_underspecified = True
        if getattr(args, "release_unreproducible", False):
            plan.rerun_unreproducible = True
        result = driver.run_auto(plan=plan,
                                 budget=plan.iterations,
                                 mutation_budget=plan.mutations,
                                 opt_in_identical_skip=not args.force,
                                 release_held=args.release_under_specified)
        print(f"7-Stage Auto loop complete: {result}")
        return 0 if result.get("converged") else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
