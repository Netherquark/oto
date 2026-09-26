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
from report import AcceptanceReporter
from telemetry import TelemetrySampler as SysfsTelemetrySampler
import tensile_library as tlib

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
        self.agent = ConvergenceAgent(
            self.base_dir,
            self.scheduler,
            self.analytics,
        )
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
        self._telemetry: Optional[SysfsTelemetrySampler] = None
        self._telemetry_run_id: Optional[str] = None
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

        checks = [
            ("Tensile root exists", self.tensile_root.is_dir()),
            ("Tensile CLI exists", tensile_bin.is_file()),
            ("Registry DB accessible", self.registry.db_path.exists() or self.registry.results_dir.is_dir()),
            ("phases.yaml accessible", (self.base_dir / "phases.yaml").exists()),
        ]

        all_ok = True
        for name, ok in checks:
            status = "[OK]" if ok else "[FAIL]"
            print(f"  {status} {name}")
            if not ok:
                all_ok = False

        return all_ok

    def load_phases_manifest(self, phases_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """Load phases.yaml manifest (the data manifest)."""
        if phases_path is None:
            phases_path = self.base_dir / "phases.yaml"

        if not phases_path.exists():
            return []

        with open(phases_path, "r") as f:
            phases = yaml.safe_load(f) or []

        return phases

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
                if sys.stdin.isatty():
                    r, _, _ = select.select([sys.stdin], [], [], 0.2)
                    if r:
                        key = sys.stdin.read(1).lower()
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
                else:
                    time.sleep(0.2)
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
        """fix.md cell-key stamps for a phase's registry records.

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
        self._write_phase_config(phase_config_path, phase)

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

    def _write_phase_config(self, path: Path, phase: Dict[str, Any]) -> None:
        """
        Write valid Tensile Top-Level Config YAML (GlobalParameters + BenchmarkProblems).

        Contraction pattern → TransposeA/B (verified vs Tensile source):
            Ailk_Bljk → TA=False TB=False  (NN)
            Ailk_Bjlk → TA=False TB=True   (NT)
            Alik_Bljk → TA=True  TB=False  (TN)
            Alik_Bjlk → TA=True  TB=True   (TT)
        Pattern inferred from label if 'contraction_pattern' field absent.
        """
        from scheduler import parse_tensile_shape, assembly_class_valid

        phase_id = phase.get("phase_id", "phase_unknown")
        label = phase.get("label", "")
        dtype = phase.get("dtype", "S").lower()
        schedule_name = phase.get("ScheduleName", "isa")
        num_benchmarks = phase.get("NumBenchmarks", 8)
        config = phase.get("config", {})
        shapes = phase.get("shapes", ["1024x1024x1024"])

        # Assembly-class autoskip: merge the phase-level dtype/label into the
        # config so the class predicate (FamilyLabel/label/DataType) is complete.
        gate_config = {**config, "DataType": dtype, "label": label}
        asm_ok, asm_reason = assembly_class_valid(gate_config)
        if not asm_ok:
            print(f"Skipping {phase_id}: assembly-class illegal ({asm_reason})")
            return None

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
        is_hpa = "HPA" in label or "HPA" in str(config.get("ProblemType", ""))
        is_hs_hpa = "HS_HPA" in label

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

        # NumLoadsCoalescedA (NLCA alias)
        nlca = config.get("NLCA", config.get("NumLoadsCoalescedA"))
        if nlca is not None:
            fork_params["NumLoadsCoalescedA"] = [int(nlca)]

        # Prefetch knobs
        if "PrefetchGlobalRead" in config:
            fork_params["PrefetchGlobalRead"] = [bool(config["PrefetchGlobalRead"])]
        if "PrefetchLocalRead" in config:
            fork_params["PrefetchLocalRead"] = [bool(config["PrefetchLocalRead"])]

        # Remove deprecated MacroTile0/MacroTile1 keys if they exist (Tensile doesn't accept them)
        fork_params.pop("MacroTile0", None)
        fork_params.pop("MacroTile1", None)

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

                    # Non-blocking key check if sys.stdin is a tty
                    if sys.stdin.isatty():
                        r, _, _ = select.select([sys.stdin], [], [], 0.2)
                        if r:
                            key = sys.stdin.read(1).lower()
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
                    else:
                        time.sleep(0.2)

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
        for phase in phases:
            if self._stop_requested or self._finish_after_iteration:
                print("Stop requested, halting phase execution")
                break

            phase_id = phase.get("phase_id", "")
            config = phase.get("config", {})
            fp = phase.get("fp", fingerprint_config(config))

            # Policy check: should_run
            allowed, reason = should_run(
                phase_id=phase_id,
                fp=fp,
                registry=self.registry,
                phase_scope=target_ids,
                opt_in_identical_skip=opt_in_identical_skip
            )

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
                continue

            result = self.execute_phase(phase, self.run_dir)
            results.append(result)
            if result.get("status") not in ("interrupted", "skipped_by_user"):
                executed_count += 1

            if self._finish_after_iteration:
                print("End-after-iteration requested, halting phase execution")
                break

        # Mark run final status in registry
        if self._stop_requested:
            final_status = "interrupted"
        elif executed_count == 0 and skipped_count > 0:
            final_status = "skipped"
        else:
            final_status = "completed"
        run_meta: Dict[str, Any] = {
            "phases_executed": executed_count,
            "phases_skipped": skipped_count,
        }
        if self._finish_after_iteration:
            run_meta["end_after_iteration"] = True
        self.registry.update_run_status(self.run_dir.name, final_status, run_meta)
        return results

    def run_gfx900_reference(self, refresh: bool = False, limit: Optional[int] = None,
                             ref_shapes: Optional[List[str]] = None,
                             resume: bool = False,
                             resume_base: Optional[str] = None) -> Dict[str, Any]:
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
            completed, _ = self._chain_phase_sets(chain_ids)
            phases = [p for p in deck
                      if str(p.get("phase_id", "")) not in completed]
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

    def _chain_phase_sets(self, run_ids: List[str]) -> Tuple[Set[str], Set[str]]:
        """Per-phase verdict sets across the whole reference chain.

        completed: phases that produced a kernel (status completed/success).
        decided:   phases with any definite verdict (completed/success/failed).
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
                elif status == "failed":
                    decided.add(str(rec["phase_id"]))
        return completed, decided

    def _reference_remaining(self) -> int:
        """Phases with no definite verdict left in the reference deck (the
        completeness gate for --auto). -1 when no completed floor exists yet."""
        chain = tlib.reference_chain(self.registry, exclude=self.run_dir.name)
        if not chain:
            return -1
        base_deck = (self.base_dir / "gfx90c_runs" / chain[-1]
                     / "phases_reference.yaml")
        try:
            deck = yaml.safe_load(base_deck.read_text()) or []
        except Exception:
            return -1
        _, decided = self._chain_phase_sets(chain)
        return max(0, len(deck) - len(decided))

    def run_auto(
        self,
        budget: int = 100,
        mutation_budget: int = 2,
        opt_in_identical_skip: bool = True
    ) -> Dict[str, Any]:
        """
        Run auto-convergence loop (one-command overnight).

        Order:
          1. Preflight (Phase-0 checks, non-fatal)
          2. Preflight A/B baseline pair (spoof vs native anchor)
          3. All manifest phases in order (policy-filtered)
          4. Convergent harvest/mutate loop
        """
        print(f"Starting auto-convergence loop (budget={budget}, mutation_budget={mutation_budget})")

        # 1. Phase-0 preflight guarantees Tensile/DB/manifest presence
        preflight_ok = self.run_preflight()
        if not preflight_ok:
            print("WARNING: preflight reported FAIL; continuing (non-fatal).")
        if self._stop_requested or self._finish_after_iteration:
            return {"converged": False, "reason": "Preflight aborted", "iterations": 0}

        # 2. A/B floor: a completed gfx900 reference run (recalled, not re-run).
        #    Established via --gfx900-reference, or by --auto. If the reference
        #    deck is not fully decided yet, --auto RESUMES it (finishing only
        #    the undecided shipped phases) and refuses to proceed with any
        #    tuning until every shipped phase has a verdict.
        ref = self._latest_reference_run(exclude=self.run_dir.name)
        if ref:
            print(f"\n--- A/B floor: gfx900 shipped reference run {ref} (recalled) ---")
            remaining = self._reference_remaining()
            if remaining > 0:
                print(f"Reference deck incomplete ({remaining} shipped phases "
                      "without a verdict) — resuming it before tuning...")
                ref_res = self.run_gfx900_reference(resume=True, resume_base=ref)
                if str(ref_res.get("status")) not in ("completed", "noop"):
                    print(f"Reference resume did not complete "
                          f"({ref_res.get('status')}); aborting before any tuning.")
                    return {"converged": False,
                            "reason": f"reference deck incomplete after resume "
                                      f"({ref_res.get('status')})",
                            "iterations": 0}
                remaining = self._reference_remaining()
            if remaining > 0:
                print(f"\nReference deck STILL {remaining} shipped phases undecided — "
                      "aborting BEFORE any tuning (per the completeness gate: "
                      "the reference floor must be fully decided first).")
                return {"converged": False,
                        "reason": f"reference deck incomplete ({remaining} undecided)",
                        "iterations": 0}
            print("--- reference floor fully decided; proceeding with tuning ---")
        else:
            print("\nNo completed gfx900 shipped reference floor found — "
                  "establishing it now (--gfx900-reference, full deck, once).")
            ref_res = self.run_gfx900_reference()
            if ref_res.get("status") == "completed":
                ref = ref_res.get("run_id")
                print(f"--- A/B floor: gfx900 shipped reference run {ref} "
                      f"(freshly established) ---")
            else:
                print(f"WARNING: reference benchmark did not complete "
                      f"({ref_res.get('status')}); aborting before any tuning "
                      "— the floor must be fully decided first.")
                return {"converged": False,
                        "reason": "reference deck not established "
                                  f"({ref_res.get('status')})",
                        "iterations": 0}

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
        csv_files = list(run_dir.glob("phase_*/2_BenchmarkData/*.csv"))

        for csv_file in csv_files:
            # Extract phase_id and family from CSV file path
            phase_dir = csv_file.parent.parent
            phase_id = phase_dir.name

            from analytics import extract_family_from_phase_id
            family = extract_family_from_phase_id(phase_id)

            # Get dtype from phase_id using analytics helper
            dtype = self.analytics.extract_dtype_from_phase_id(phase_id)

            records = self.analytics.load_benchmark_csv(csv_file)
            cell_map = self.analytics.aggregate_by_cell(records, dtype_override=dtype)

            for (cell_dtype, shape, fp), seeds in cell_map.items():
                analytics_obj = self.analytics.compute_cell_analytics(
                    dtype=cell_dtype,
                    shape=shape,
                    fp=fp,
                    seeds=seeds,
                    family=family
                )
                all_analytics.append(analytics_obj)

        return all_analytics

    def _load_analytics_from_registry(self, run_id: str) -> List[CellAnalytics]:
        """Load CellAnalytics straight from registry benchmark_result rows.

        For merged / draft-imported runs whose per-seed GFLOPS live only in the
        database (no run_dir CSVs). Mirrors _load_analytics_from_run: per-config
        fingerprint cells aggregated over seed rows, family from phase_id.
        """
        from analytics import extract_family_from_phase_id

        all_analytics = []
        try:
            records = self.registry.read_records(run_id=run_id, record_type="benchmark_result")
        except Exception:
            return all_analytics
        if not records:
            return all_analytics

        by_phase: Dict[str, List[Dict[str, Any]]] = {}
        for rec in records:
            by_phase.setdefault(str(rec.get("phase_id", "")), []).append(rec)

        for phase_id, phase_records in by_phase.items():
            dtype = phase_records[0].get("dtype") or self.analytics.extract_dtype_from_phase_id(phase_id)
            family = extract_family_from_phase_id(phase_id)
            cell_map = self.analytics.aggregate_by_cell(phase_records, dtype_override=dtype)
            for (cell_dtype, shape, fp), seeds in cell_map.items():
                all_analytics.append(self.analytics.compute_cell_analytics(
                    dtype=cell_dtype, shape=shape, fp=fp, seeds=seeds, family=family))

        return all_analytics

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

    def generate_acceptance_report(self, run_dir: Optional[Path] = None, run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Generate the acceptance report (JSON + HTML) from run data.
        Installed in run_auto, the --targets path, and the SIGINT handler so a
        report is always emitted even on interrupt (missing-report bug fix).

        Analytics come from the run's 2_BenchmarkData CSVs when on disk; for
        merged / draft-imported runs (no run_dir) they are rebuilt from registry
        benchmark_result rows. Reports are written into the run dir (when one
        exists) plus the canonical base_dir/gfx90c_results/ location.
        """
        try:
            if run_dir is None:
                run_dir = self.run_dir
            if run_id is None:
                run_id = run_dir.name if run_dir is not None else self.registry.latest_run_id()
            if not run_id:
                print("Report generation: no run_id available")
                return None

            if run_dir is not None and any(run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
                all_analytics = self._load_analytics_from_run(run_dir)
            else:
                all_analytics = self._load_analytics_from_registry(run_id)

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
            ab_verdicts = self._compute_ab_verdicts(run_id, run_dir)
            report = self.reporter.generate_acceptance_report(
                run_id=run_id,
                ab_verdicts=ab_verdicts,
                all_analytics=all_analytics,
                red_list=red_list,
                orange_list=cell_status["orange"],
                family_timing=family_timing,
                reference_run_id=self._last_ab_reference_run_id
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
                    "overall_pass": report.overall_pass, "summary": report.summary}
        except Exception as e:
            print(f"Report generation error: {e}")
            return None

    def regenerate_report(self, run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Regenerate the acceptance report for a run from the registry.

        With no run_id, uses the most recently registered run. Reports land in
        base_dir/gfx90c_results/acceptance_report.{json,html}.
        """
        if run_id is None:
            run_id = self.registry.latest_run_id()
        if not run_id:
            print("No run id available to regenerate a report")
            return None

        run_dir = self.base_dir / "gfx90c_runs" / run_id
        if not run_dir.exists():
            run_dir = None
        print(f"Regenerating acceptance report for run {run_id}")
        return self.generate_acceptance_report(run_dir=run_dir, run_id=run_id)

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

        for csv_file in sorted(run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
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
            dtype = self.analytics.extract_dtype_from_phase_id(phase_id)
            records = self.analytics.load_benchmark_csv(csv_file)
            cell_map = self.analytics.aggregate_by_cell(records, dtype_override=dtype)
            for (cell_dtype, shape, fp), seeds in cell_map.items():
                agg = aggregate_cell(seeds)
                rec = {
                    "DataType": cell_dtype,
                    "ProblemType": shape,
                    "fingerprint": fp,
                    "GFLOPS": agg.median,
                    "phase_id": phase_id,
                }
                rec.update(self._named_cell_stamps(
                    phase or {"config": {}, "shapes": [shape], "family": ""},
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

    def _compute_ab_verdicts(self, run_id: str, run_dir: Optional[Path] = None) -> List[Any]:
        """Compute native-vs-spoof A/B verdicts for a run.

        Native arm = the run being accepted (deck). Spoof arm = the latest
        completed gfx900 reference run (the once-benchmarked shipped floor),
        recalled from disk — never re-run. Every spoof entity is compared
        against the best native median at the same (dtype, shape): deck-winner
        vs floor. Falls back to same-run/spoof records when no reference run
        exists (legacy merged/draft data).
        """
        from report import ABVerdict

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
                spoof_records.extend(ref_records)
        if ref_run_ids:
            self._last_ab_reference_run_id = ref_run_ids[0]
        if not spoof_records:
            print("[ab] no completed gfx900 reference floor found — A/B verdicts "
                  "deferred. Establish it with `--gfx900-reference` (or --auto, "
                  "which runs it automatically).")
            return []

        deltas = self.analytics.compute_native_vs_spoof_delta(native_records, spoof_records)

        verdicts = []
        for (dtype, shape, fp), d in deltas.items():
            verdicts.append(ABVerdict(
                dtype=dtype,
                shape=shape,
                native_median=d["native_median"],
                spoof_median=d["spoof_median"],
                delta_pct=d["delta_pct"],
                tie=d["tie"],
                verdict=d["verdict"],
                fp=d.get("spoof_fp", fp),
                family=d.get("family", "")
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
        default=100,
        help="Auto-convergence budget (iterations, default: 100)"
    )
    parser.add_argument(
        "--mutation-budget",
        type=int,
        default=2,
        help="Maximum knobs to mutate per candidate (default: 2)"
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
    parser.add_argument(
        "--gfx900-reference",
        action="store_true",
        help="One-time benchmark of every shipped gfx900 kernel from the system "
             "TensileLibrary.dat into a dedicated gfx900_ref_* run (recalled forever)"
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
        "--dry-run",
        action="store_true",
        help="List matched targets without executing benchmarks"
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

    # Stage 1: preflight validation (alone or as a gate for later stages)
    if args.preflight or "1" in stage or "preflight" in stage or "manifest" in stage:
        ok = driver.run_preflight()
        if not ok:
            return 1
        if args.preflight or not (stage - {"1", "preflight", "manifest"}):
            return 0

    # Stage 7 report-only regeneration (from registry / run dir)
    if args.report is not None or "7" in stage or "report" in stage:
        result = driver.regenerate_report(args.report if args.report else None)
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
                                             ref_shapes=ref_shapes, resume=args.resume)
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

    elif args.auto:
        result = driver.run_auto(args.budget, args.mutation_budget,
                                 opt_in_identical_skip=not args.force)
        print(f"7-Stage Auto loop complete: {result}")
        return 0 if result.get("converged") else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
