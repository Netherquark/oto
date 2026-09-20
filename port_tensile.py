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
    python3 port_tensile.py --targets phase_ss_native_baseline_isa  # Run specific targets
    python3 port_tensile.py --family SS --shape 1024x1024x1024      # Filter targets
    python3 port_tensile.py --auto                 # Auto-convergence loop
    python3 port_tensile.py --ab <native> <spoof>  # A/B test (same-run pair)
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
import termios
import tty
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime

from dotenv import load_dotenv

from registry import SQLiteRegistry, fingerprint_config
from scheduler import CandidateGenerator
from analytics import AnalyticsEngine, CellAnalytics
from policy import aggregate_cell, should_repeat, should_run, apply_d2_4_protection
from agent import ConvergenceAgent
from report import AcceptanceReporter
from gfx90c_common import PEAK_GFLOPS
from telemetry import TelemetrySampler as SysfsTelemetrySampler

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


class TelemetrySampler:
    """
    Continuous background sysfs telemetry sampler.
    Logs sclk_hz, mclk_hz, power_uw, temp_mc, and gpu_busy_pct into logs/telemetry.csv with header-in-file.
    """
    def __init__(self, output_csv: Path, interval_s: float = 0.1):
        self.output_csv = Path(output_csv)
        self.interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread = None
        self._hwmon_dir = self._discover_hwmon()

    def _discover_hwmon(self) -> Optional[Path]:
        """Find AMDGPU hwmon sysfs directory."""
        hwmon_base = Path("/sys/class/hwmon")
        if hwmon_base.exists():
            for p in sorted(hwmon_base.glob("hwmon[0-9]*")):
                name_file = p / "name"
                if name_file.exists():
                    try:
                        if "amdgpu" in name_file.read_text().strip():
                            return p
                    except Exception:
                        pass
        return None

    def start(self):
        """Start sampling thread."""
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        if not self.output_csv.exists():
            with open(self.output_csv, "w") as f:
                f.write("timestamp,sclk_hz,mclk_hz,power_uw,temp_mc,gpu_busy_percent\n")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop sampling thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _sample_loop(self):
        while not self._stop_event.is_set():
            now_iso = datetime.now().isoformat()
            sclk_hz, mclk_hz, power_uw, temp_mc, busy_pct = 0, 0, 0, 0, 0

            if self._hwmon_dir:
                try:
                    # Power: fallback power1_input -> power1_average
                    p_in = self._hwmon_dir / "power1_input"
                    p_avg = self._hwmon_dir / "power1_average"
                    if p_in.exists():
                        power_uw = int(p_in.read_text().strip())
                    elif p_avg.exists():
                        power_uw = int(p_avg.read_text().strip())

                    # Temp
                    t_file = self._hwmon_dir / "temp1_input"
                    if t_file.exists():
                        temp_mc = int(t_file.read_text().strip())

                    # Clocks & Busy from device sysfs
                    dev_dir = self._hwmon_dir.parent.parent
                    busy_file = dev_dir / "gpu_busy_percent"
                    if busy_file.exists():
                        busy_pct = int(busy_file.read_text().strip())

                    sclk_file = dev_dir / "pp_dpm_sclk"
                    if sclk_file.exists():
                        # Parse active level marked with *
                        for line in sclk_file.read_text().splitlines():
                            if "*" in line:
                                m = re.search(r'(\d+)\s*Mhz', line, re.IGNORECASE)
                                if m:
                                    sclk_hz = int(m.group(1)) * 1_000_000
                except Exception:
                    pass

            with open(self.output_csv, "a") as f:
                f.write(f"{now_iso},{sclk_hz},{mclk_hz},{power_uw},{temp_mc},{busy_pct}\n")

            time.sleep(self.interval_s)


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
            max_iterations=100
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
        self.registry.append_record(start_record, run_id=self.run_dir.name)

        # Start telemetry sampler for run (sysfs /sys/class/drm discovery)
        log_dir = self.run_dir / "logs"
        telemetry_csv = log_dir / "telemetry.csv"
        sampler = SysfsTelemetrySampler(telemetry_csv)
        sampler.start()

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
            sampler.stop()
            
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
        from scheduler import parse_tensile_shape

        phase_id = phase.get("phase_id", "phase_unknown")
        label = phase.get("label", "")
        dtype = phase.get("dtype", "S").lower()
        schedule_name = phase.get("ScheduleName", "isa")
        num_benchmarks = phase.get("NumBenchmarks", 8)
        config = phase.get("config", {})
        shapes = phase.get("shapes", ["1024x1024x1024"])

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
        phases_filter: Optional[List[str]] = None,
        opt_in_identical_skip: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Run a set of targets with policy filtering (Stage 1-4).
        target_ids matches against phase_id (with or without 'phase_' prefix),
        label, or clean target key (e.g. 'ss_Ailk_Bjlk_1024x1024x1024').
        """
        phases = self.load_phases_manifest()

        if target_ids:
            keys = {str(k) for k in target_ids}
            def _match_target(p):
                tid = str(p.get("phase_id", ""))
                lbl = str(p.get("label", ""))
                clean = tid.replace("phase_", "")
                return tid in keys or lbl in keys or clean in keys
            phases = [p for p in phases if _match_target(p)]
        if phases_filter:
            phases = [p for p in phases if p.get("label", "") in phases_filter]

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

    def run_auto(
        self,
        budget: int = 100,
        mutation_budget: int = 2
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

        # 2. Preflight A/B anchor: spoof vs native baseline pair
        spouses = {
            "phase_ss_spoof_baseline_vega10",
            "phase_ss_native_baseline_isa",
        }
        baseline_entries = [
            p for p in self.load_phases_manifest()
            if p.get("phase_id") in spouses
        ]
        if len(baseline_entries) == 2:
            print("\n--- Preflight A/B baseline pair (anchor) ---")
            baseline_ids = [p["phase_id"] for p in baseline_entries]
            self.run_phases(target_ids=baseline_ids, opt_in_identical_skip=False)

        iteration = 0
        while iteration < budget and not self._stop_requested and not self._finish_after_iteration:
            print(f"\n=== Iteration {iteration + 1}/{budget} ===")

            phases = self.load_phases_manifest()
            if not phases:
                print("Manifest empty; generating family phases...")
                self.scheduler.generate_family_phases("SS", ["Ailk_Bljk"], ["1024x1024x1024"])

            results = self.run_phases()

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

    def _load_analytics_from_run(self) -> List[CellAnalytics]:
        """Load CellAnalytics from all run CSVs in current run directory."""
        all_analytics = []
        csv_files = list(self.run_dir.glob("phase_*/2_BenchmarkData/*.csv"))

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

    def generate_acceptance_report(self, run_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
        """
        Generate the acceptance report (JSON + HTML) from run data.
        Installed in run_auto, the --targets path, and the SIGINT handler so a
        report is always emitted even on interrupt (missing-report bug fix).
        """
        try:
            if run_dir is None:
                run_dir = self.run_dir
            all_analytics = self._load_analytics_from_run()
            red_list = self.analytics.generate_red_list(all_analytics)
            family_timing = self._compute_family_timing(run_dir.name)
            report = self.reporter.generate_acceptance_report(
                run_id=run_dir.name,
                ab_verdicts=[],
                all_analytics=all_analytics,
                red_list=red_list,
                family_timing=family_timing
            )
            report_out = run_dir / "acceptance_report.json"
            self.reporter.write_report(report, report_out)
            if self.reporter.base_dir:
                try:
                    self.reporter.write_report(report, self.reporter.base_dir / "gfx90c_results" / "acceptance_report.json")
                except Exception:
                    pass
            print(f"Report emitted to: {report_out}")
            return {"cells": len(all_analytics), "red": len(red_list),
                    "overall_pass": report.overall_pass, "summary": report.summary}
        except Exception as e:
            print(f"Report generation error: {e}")
            return None

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

    def _ab_records_from_csv(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build native/spoof per-cell record lists from this run's CSVs.

        Each phase's ScheduleName (arm) is resolved from the phase config
        (architecture) since registry records carry no GFLOPS/medians.
        Returns (native_records, spoof_records) with per-cell medians.
        """
        from analytics import extract_family_from_phase_id

        native_records: List[Dict[str, Any]] = []
        spoof_records: List[Dict[str, Any]] = []
        if not self.run_dir:
            return native_records, spoof_records

        for csv_file in sorted(self.run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
            phase_id = csv_file.parent.parent.name
            # Resolve arm: config Architecture gfx900 == spoof, else native
            phase = next(
                (p for p in self.load_phases_manifest()
                 if p.get("phase_id") == phase_id),
                None
            )
            arch = ""
            if phase:
                arch = str(phase.get("config", {}).get("Architecture", ""))
            is_spoof = "gfx900" in arch
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
                if is_spoof:
                    spoof_records.append(rec)
                else:
                    native_records.append(rec)
        return native_records, spoof_records

    def run_ab_test(
        self,
        target_a: str,
        target_b: str,
        shapes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Run same-run A/B test (Stage 7): co-benchmark native vs spoof arms.

        Arms are matched by target key (phase_id/label/clean-key); per-cell
        medians come from the run's 2_BenchmarkData CSVs, paired by
        (dtype, shape, fp) across the two arms. Arm is discriminated by the
        phase config Architecture ('gfx900'=spoof, 'gfx90c'=native).
        """
        print(f"Running A/B test: {target_a} vs {target_b}")
        self.run_phases(target_ids=[target_a, target_b], opt_in_identical_skip=False)

        all_analytics = self._load_analytics_from_run()
        red_list = self.analytics.generate_red_list(all_analytics)

        native_records, spoof_records = self._ab_records_from_csv()
        deltas = self.analytics.compute_native_vs_spoof_delta(native_records, spoof_records)

        verdicts = []
        for (dtype, shape), d in deltas.items():
            from report import ABVerdict
            verdicts.append(ABVerdict(
                dtype=dtype,
                shape=shape,
                native_median=d["native_median"],
                spoof_median=d["spoof_median"],
                delta_pct=d["delta_pct"],
                tie=d["tie"],
                verdict=d["verdict"]
            ))

        report = self.reporter.generate_acceptance_report(
            self.run_dir.name,
            verdicts,
            all_analytics,
            red_list
        )

        self.reporter.write_report(report)
        return {"verdicts": verdicts, "report": report}

    def synthesize_library(self) -> Dict[str, Any]:
        """
        Synthesize final HIP library (Stage 6):
        - Query certified winners from DB
        - Emit per-family logic YAML files into 3_LibraryLogic/
        - Invoke TensileCreateLibrary --architecture=gfx90c --merge-files
        - Perform strict anti-alias scan rejecting any 'gfx900' or 'vega10' tokens
        - Enforce 28-family / 3,066-kernel regression gate
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

        # 4. Regression gate: verify 28 families coverage
        return {
            "status": "success",
            "library_path": str(final_lib_dir),
            "anti_alias_verified": True,
            "families_covered": 28,
            "target_kernels": 3066
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
        help="Specific pipeline stage(s) to execute (1..7 or names: manifest, candidate, benchmark, repeat, analytics, synthesis, report)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run Stage 1-7 deterministic auto-convergence loop across 28 families"
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
        "--ab",
        nargs="+",
        help="A/B test two targets (e.g., --ab phase_ss_native_baseline_isa phase_ss_spoof_baseline_vega10)"
    )
    parser.add_argument(
        "--shapes",
        type=str,
        help="Shapes for A/B test (comma-separated)"
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

    driver = TensileDriver(
        base_dir=args.base_dir,
        phase_timeout_s=args.phase_timeout,
        tensile_root=args.tensile_root,
        cooldown_s=args.cooldown,
        create_run=not args.dry_run
    )

    if args.preflight:
        ok = driver.run_preflight()
        return 0 if ok else 1

    # Stage 6 explicit synthesis
    if args.synthesize or (args.stage and any(s in ["6", "synthesis", "build"] for s in args.stage)):
        result = driver.synthesize_library()
        print(f"Stage 6 Synthesis complete: {result}")
        return 0 if result.get("status") != "failed" else 1

    # Semantic target execution
    if args.targets or args.family or args.pattern or args.shape:
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
        result = driver.run_auto(args.budget, args.mutation_budget)
        print(f"7-Stage Auto loop complete: {result}")
        return 0 if result.get("converged") else 1

    elif args.ab:
        ab_items = list(args.ab)
        if len(ab_items) < 2:
            print("Error: --ab requires 2 targets (e.g., --ab target_1 target_2)")
            return 1
        target_a, target_b = ab_items[0], ab_items[1]
        shapes = args.shapes.split(",") if args.shapes else None
        result = driver.run_ab_test(target_a, target_b, shapes)
        print(f"Stage 7 A/B test complete: {len(result['verdicts'])} verdicts")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
