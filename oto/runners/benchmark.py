#!/usr/bin/env python3
"""Phase execution: the one place a Tensile subprocess is launched.

Owns: ``execute_phase`` (the whole lifecycle of one phase -- cooldown, config
write, ledger records, telemetry tag, launch, timeout/failure recovery) and
``_run_tensile_benchmark`` (the argv/env, the detached process group, the log
tee, the key poll, the CSV collection). Also the two shared mechanisms those
need: ``_read_key`` (single owner of stdin) and ``_apply_cooldown``.
Does NOT own: what makes a config legal (oto.tensile.gates), what a config is
(oto.tensile.config_writer), or which phases run in what order (phases.py).
Public API: BenchmarkMixin.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import oto.tensile.shipped_floor_manifest as tlib
from oto.device import loader as _loader
from oto.ledger.registry import fingerprint_config
from oto.metrics.telemetry import TelemetrySampler as SysfsTelemetrySampler
from oto.runners.toolchain import resolve_rocm_paths
from oto.tensile import config_writer


def _refuse_reuse_of(phase_out_dir: Path) -> None:
    """Refuse to benchmark into a directory that already holds results."""
    existing = sorted(phase_out_dir.glob("2_BenchmarkData/*.csv"))
    if existing:
        raise FileExistsError(
            f"phase output {phase_out_dir} already contains "
            f"{len(existing)} benchmark CSV(s); re-running would overwrite "
            f"them. Move the directory aside or use a fresh run id.")


def _tensile_client(tensile_root: Path) -> Path | None:
    """Locate the Tensile client binary, or return None with a hint.

    Tensile v4.50.0 dropped ``--client-build-path``; it now resolves the
    client from ``./build/client/tensile-client`` relative to its CWD
    (here, the Tensile checkout) or from ``--prebuilt-client``. Override
    with the ``OTO_TENSILE_CLIENT`` environment variable.
    """
    env = os.environ.get("OTO_TENSILE_CLIENT", "").strip()
    if env:
        cand = Path(env).resolve()
        return cand if cand.is_file() else None
    default = tensile_root / "build" / "client" / "tensile-client"
    return default if default.is_file() else None


def _tensile_command(
    driver,
    tensile_bin: Path,
    config_path: Path,
    phase_out_dir: Path,
profile=None,
) -> tuple[list[str], dict[str, str]]:
    """The Tensile argv and environment for one phase config.

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    rocm = resolve_rocm_paths()
    assembler = rocm["TENSILE_ASSEMBLER"]
    if not os.path.isfile(assembler):
        assembler = rocm["TENSILE_ASSEMBLER_FALLBACK"]

    codename = getattr(getattr(driver, "profile", None), "codename",
                       _loader.resolve_profile(profile,).codename)
    client = _tensile_client(driver.tensile_root)
    if client is None:
        client = driver.tensile_root / "build" / "client" / "tensile-client"

    cmd = [
        sys.executable,
        str(tensile_bin),
        "--arch", codename,
        "--cxx-compiler", "hipcc",
        "--c-compiler", "hipcc",
    ]
    if os.path.isfile(assembler):
        cmd += ["--assembler", assembler]
    cmd += [
        "--prebuilt-client", str(client),
        "--client-lock", str(driver.client_build_dir / "client.lock")
        if driver.client_build_dir else
        str(driver.tensile_root / "build" / "client" / "client.lock"),
        "-d", "0",
        str(config_path),
        str(phase_out_dir)
    ]
    if os.environ.get("TENSILE_VERBOSE",) in ("1", "true", "True"):
        cmd.append("--verbose")

    return cmd, driver._get_tensile_env()


class BenchmarkMixin:
    """Phase execution and Tensile process management, mixed into TensileDriver."""

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
            import os
            if os.environ.get("OTO_NO_INPUT") or not sys.stdin.isatty():
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
                if key == 'e':
                    print("\n[USER ACTION] 'e' pressed: Ending run after current phase...")
                    self._finish_after_iteration = True
                    break
                if key == 'q':
                    print("\n[USER ACTION] 'q' pressed: Quitting run during cooldown...")
                    self._stop_requested = True
                    return False
        return not self._stop_requested
    def _ensure_telemetry(self) -> SysfsTelemetrySampler | None:
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
    def _write_phase_config(self, path: Path,
                            phase: dict[str, Any]) -> tuple[bool, str]:
        """Render one phase's Tensile YAML, refusing illegal configs.

        Kept as a method (the pre-split `TensileDriver._write_phase_config`
        surface) so `oto.checks.tensile_build.write_phase_configs` and tests can
        call or patch it on the driver; the ~240-line implementation lives in
        oto.tensile.config_writer.write_phase_config and is delegated to here.
        """
        return config_writer.write_phase_config(self, path, phase)

    def execute_phase(
        self,
        phase: dict[str, Any],
        run_dir: Path
    ) -> dict[str, Any]:
        """
        Execute a single phase (the preflight stage + the benchmark stage).
        """
        phase_id = phase.get("phase_id", "unknown")
        label = phase.get("label", "unknown")
        dtype = phase.get("dtype", "S")
        schedule_name = phase.get("ScheduleName", "isa")
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
            return self._refuse_phase(phase, fp, refusal)

        # Log start record
        self.registry.append_record(self._start_record(phase, fp),
                                    run_id=self.run_dir.name)

        # Execute Tensile benchmark; the telemetry tag is applied inside.
        return self._benchmark_phase(phase, fp, phase_config_path, run_dir)

    def _refuse_phase(
        self,
        phase: dict[str, Any],
        fp: str,
        refusal: str
    ) -> dict[str, Any]:
        """Record a phase the config writer refused, before any GPU work.

        A refused phase is settled as `skipped_illegal` so the completeness gate
        is not blocked forever by a phase that can never build, and so the reason
        stays attributable instead of surfacing as an opaque Tensile rejection
        later.
        """
        phase_id = phase.get("phase_id", "unknown")
        label = phase.get("label", "unknown")
        dtype = phase.get("dtype", "S")
        shapes = phase.get("shapes", [])
        schedule_name = phase.get("ScheduleName", "isa")
        num_benchmarks = phase.get("NumBenchmarks", 8)
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

    def _start_record(self, phase: dict[str, Any], fp: str) -> dict[str, Any]:
        """The `started` ledger record for a phase."""
        record = {
            "run_id": self.run_dir.name,
            "phase_id": phase.get("phase_id", "unknown"),
            "label": phase.get("label", "unknown"),
            "dtype": phase.get("dtype", "S"),
            "shapes": phase.get("shapes", []),
            "schedule_name": phase.get("ScheduleName", "isa"),
            "num_benchmarks": phase.get("NumBenchmarks", 8),
            "fp": fp,
            "timestamp": datetime.now().isoformat(),
            "status": "started"
        }
        record.update(self._named_cell_stamps(phase))
        return record

    def _end_record(
        self,
        phase: dict[str, Any],
        fp: str,
        status: str,
        result: dict[str, Any]
    ) -> dict[str, Any]:
        """The completion record, tagged with the phase's content identity.

        `phase_id` alone is not safe for the next run's reuse decision (see
        `_reusable_phase_keys`): it embeds parser-derived knobs.
        """
        record = {
            "run_id": self.run_dir.name,
            "phase_id": phase.get("phase_id", "unknown"),
            "label": phase.get("label", "unknown"),
            "dtype": phase.get("dtype", "S"),
            "shapes": phase.get("shapes", []),
            "schedule_name": phase.get("ScheduleName", "isa"),
            "num_benchmarks": phase.get("NumBenchmarks", 8),
            "fp": fp,
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "result": result
        }
        record.update(self._named_cell_stamps(phase))
        record["phase_key"] = tlib.phase_key(phase)
        record["config_fingerprint"] = tlib.config_fingerprint(phase)
        return record

    def _outcome_record(
        self,
        phase: dict[str, Any],
        fp: str,
        status: str,
        error: str | None = None
    ) -> dict[str, Any]:
        """A minimal timeout/failure ledger record (no result payload)."""
        record = {
            "run_id": self.run_dir.name,
            "phase_id": phase.get("phase_id", "unknown"),
            "label": phase.get("label", "unknown"),
            "fp": fp,
            "timestamp": datetime.now().isoformat(),
            "status": status
        }
        if error is not None:
            record["error"] = error
        return record

    def _recover_completion(
        self,
        phase_id: str,
        label: str,
        fp: str,
        result: dict[str, Any]
    ) -> None:
        """Write the completion record if the benchmark returned without one."""
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

    def _benchmark_phase(
        self,
        phase: dict[str, Any],
        fp: str,
        phase_config_path: Path,
        run_dir: Path
    ) -> dict[str, Any]:
        """Launch one phase's Tensile run and ledger its outcome.

        Tags the run-wide telemetry sampler with the active phase for the
        duration (started lazily once per run; kept alive across phases).
        """
        phase_id = phase.get("phase_id", "unknown")
        telemetry = self._ensure_telemetry()
        if telemetry is not None:
            telemetry.set_phase(phase_id)

        result = None
        end_record_logged = False
        try:
            result = self._run_tensile_benchmark(
                phase_config_path,
                run_dir / phase_id,
                timeout=self.phase_timeout_s
            )

            status = "completed" if result.get("status") == "success" else "failed"
            self.registry.append_record(
                self._end_record(phase, fp, status, result),
                run_id=self.run_dir.name)
            end_record_logged = True
            self._gpu_phases_run += 1
            return result

        except subprocess.TimeoutExpired:
            print(f"Phase {phase_id} timed out after {self.phase_timeout_s}s")
            self.registry.append_record(
                self._outcome_record(phase, fp, "timeout"),
                run_id=self.run_dir.name)
            end_record_logged = True
            return {"status": "timeout"}

        except Exception as e:
            print(f"Phase {phase_id} failed: {e}")
            self.registry.append_record(
                self._outcome_record(phase, fp, "failed", error=str(e)),
                run_id=self.run_dir.name)
            end_record_logged = True
            return {"status": "failed", "error": str(e)}

        finally:
            if telemetry is not None:
                telemetry.set_phase("")
            if result and not end_record_logged:
                self._recover_completion(
                    phase_id, phase.get("label", "unknown"), fp, result)

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
                with contextlib.suppress(Exception):
                    stream.close()
        t = threading.Thread(target=_pump, daemon=True)
        t.start()
        return t
    def _run_tensile_benchmark(
        self,
        config_path: Path,
        phase_out_dir: Path,
        timeout: int
    ) -> dict[str, Any]:
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
        _refuse_reuse_of(phase_out_dir)

        cmd, env = _tensile_command(self, tensile_bin, config_path, phase_out_dir)

        # If Tensile binary exists, execute real CLI
        if not tensile_bin.exists():
            # Fallback path if Tensile binary is not present in test env
            return {
                "status": "simulated",
                "benchmark_path": str(phase_out_dir / "2_BenchmarkData"),
                "num_benchmarks": 8
            }

        proc, tee_workers, log_out, log_err = self._spawn_tensile(
            cmd, env, phase_out_dir)

        rc, skipped = self._supervise_tensile(
            proc, cmd, timeout, tee_workers, log_out, log_err)

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

    def _spawn_tensile(
        self,
        cmd: list[str],
        env: dict[str, str],
        phase_out_dir: Path
    ) -> tuple[Any, list[threading.Thread], Any, Any]:
        """Open the phase logs, spawn Tensile detached, tee both streams."""
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
            self._tee_stream(proc.stdout, log_out, sys.stdout, "[tensile] "),
            self._tee_stream(proc.stderr, log_err, sys.stderr, "[tensile:err] "),
        ]
        return proc, tee_workers, log_out, log_err

    def _supervise_tensile(
        self,
        proc,
        cmd: list[str],
        timeout: int,
        tee_workers: list[threading.Thread],
        log_out,
        log_err
    ) -> tuple[int, bool]:
        """Poll a live Tensile proc for timeout/keys, then drain and reap it.

        Returns (returncode, skipped); raises TimeoutExpired once the process
        group has been killed and the tee threads drained.
        """
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
                if key == 'e':
                    print("\n[USER ACTION] 'e' pressed: Ending run after current phase completes...")
                    self._finish_after_iteration = True
                elif key == 'q':
                    print("\n[USER ACTION] 'q' pressed: Quitting run...")
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    self._stop_requested = True
                    break

            if self._stop_requested and proc.poll() is None:
                with contextlib.suppress(Exception):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

            rc = proc.poll() if not skipped else -1
        finally:
            self._current_proc = None
            proc.wait()
            for w in tee_workers:
                w.join(timeout=5)
            log_out.close()
            log_err.close()

        return rc, skipped
