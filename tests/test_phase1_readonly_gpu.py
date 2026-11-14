#!/usr/bin/env python3
"""Phase 1 read-only reporting and GPU-loss abort regression tests.

Read-only surfaces must never mutate the registry, and a lost GPU during a run
must abort the outcome write-back cleanly instead of persisting garbage.
See ``tests/phase1_harness.py`` for the fixtures.
"""
import shutil
from pathlib import Path

import pytest
from phase1_harness import Harness, _StubScheduler

from oto.ledger.registry import SQLiteRegistry
from oto.runners.driver import TensileDriver
from oto.runners.paths import results_rel


class ReadOnlyRegistryTests(Harness):
    """A reporting path must not write to the registry it reports on.

    Found the hard way: `ab_audit` constructs a `SQLiteRegistry`, whose
    `__init__` ran the additive schema migration unconditionally. Every audit run
    therefore rewrote the live floor registry's bytes -- schema only, no row
    touched, but a report had changed its own subject.
    """

    def test_read_only_construction_does_not_create_a_database(self):
        base = self.tmp / "empty"
        (base / results_rel("")).mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            SQLiteRegistry(base, read_only=True)
        assert not (base / results_rel("registry.db")).exists()

    def test_read_only_construction_leaves_the_file_byte_identical(self):
        SQLiteRegistry(self.tmp)          # writable: creates + migrates
        before = self.registry.db_path.read_bytes()
        SQLiteRegistry(self.tmp, read_only=True)
        assert self.registry.db_path.read_bytes() == before

    def test_read_only_readers_still_work(self):
        self.registry.record_proposal(fp="ro1", family="SS", shape="1x1x1")
        self.registry.resolve_proposal("ro1", "functional")
        ro = SQLiteRegistry(self.tmp, read_only=True)
        assert ro.get_proposal("ro1")["outcome"] == "functional"
        assert len(ro.all_proposals()) == 1
        assert ro.outcome_histogram()["functional"] == 1

    def test_read_only_refuses_every_write(self):
        self.registry.record_proposal(fp="ro2", family="SS", shape="1x1x1")
        ro = SQLiteRegistry(self.tmp, read_only=True)
        for call in (
            lambda: ro.record_proposal(fp="ro3", family="SS"),
            lambda: ro.resolve_proposal("ro2", "non_functional"),
            lambda: ro.append_record({"type": "x"}, run_id="r"),
            lambda: ro.append_phase("p1", "f1", {}),
            lambda: ro.append_observation("ro2", outcome="functional"),
            lambda: ro.emit_proposal_with_phase(fp="ro4", phase_id="p2"),
            lambda: ro.update_run_status("r", "completed"),
        ):
            with pytest.raises(PermissionError):
                call()

    def test_a_refused_write_changes_nothing(self):
        self.registry.record_proposal(fp="ro5", family="SS", shape="1x1x1")
        self.registry.resolve_proposal("ro5", "functional")
        before = self.registry.db_path.read_bytes()
        ro = SQLiteRegistry(self.tmp, read_only=True)
        with pytest.raises(PermissionError):
            ro.resolve_proposal("ro5", "non_functional")
        assert self.registry.db_path.read_bytes() == before
        assert self.registry.get_proposal("ro5")["outcome"] == "functional"

    def test_the_audit_path_is_read_only(self):
        import oto.metrics.ab_audit as ab_audit
        seen = {}

        def spy(base, read_only=False):
            seen["read_only"] = read_only
            return SQLiteRegistry(base, read_only=True)
        # ab_audit imports SQLiteRegistry inside the function; patch the module.
        import unittest.mock as mock
        with mock.patch("oto.ledger.registry.SQLiteRegistry", spy):
            ab_audit._proposal_coverage(self.tmp, band_pct=10.0)
        assert seen.get("read_only")

    def test_full_audit_does_not_change_the_file(self):
        import tempfile as tf
        base = Path(tf.mkdtemp(prefix="oto_ro_audit_"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / results_rel("")).mkdir(parents=True)
        (base / "phases.yaml").write_text("[]")
        reg = SQLiteRegistry(base)
        reg.create_run_dir("run_ro")
        before = reg.db_path.read_bytes()
        import oto.metrics.ab_audit as ab_audit
        ab_audit.audit(base)          # an empty corpus must not raise
        assert reg.db_path.read_bytes() == before


# ------------------------------------------------------------------- GPU loss

class GpuLossAbortTests(Harness):
    """A long streak of client-run phases that measure nothing must abort the run.

    The 2026-10-19 overnight run lost the GPU after its first phase: every later
    client aborted in ``Tensile::Client::GetHardware`` (``hipErrorNoDevice``,
    SIGABRT / exit 134), so 413 of 414 phases wrote no measurement and 9h47m of
    budget produced nothing but void phases. Without this guard the loop happily
    iterates the remaining deck against a dead GPU.

    The streak counts only phases whose client *ran*: a Tensile refusal is a
    decided outcome, and a phase that never launched the client died at kernel
    generation -- a per-config verdict, not a lost device. Both distinctions are
    pinned below, because counting either one aborts healthy runs (see
    ``test_a_streak_of_build_failures_does_not_abort``).
    """

    def _driver(self, run_id="run_gpu_loss"):
        from oto.ledger.agent import ConvergenceAgent
        driver = TensileDriver.__new__(TensileDriver)
        driver.base_dir = self.tmp
        driver.registry = self.registry
        driver.analytics = self.analytics
        driver.scheduler = _StubScheduler()
        driver.mutator = self.mutator
        driver.agent = ConvergenceAgent(self.tmp, _StubScheduler(),
                                        self.analytics, mutator=self.mutator)
        driver.run_dir = self.registry.create_run_dir(run_id)
        driver.configs_dir = driver.run_dir / "configs"
        driver.configs_dir.mkdir(exist_ok=True)
        driver._sync_agent_run_id()
        driver._stop_requested = False
        driver._finish_after_iteration = False
        driver._abort_note = None
        driver._gpu_phases_run = 0
        driver.cooldown_s = 0
        driver.phase_timeout_s = 1
        driver._last_run_status = None
        driver._start_live_status = lambda *a, **k: None
        driver._stop_live_status = lambda *a, **k: None
        driver._read_key = lambda block=True, **k: ""
        driver._apply_cooldown = lambda: True
        driver._ensure_telemetry = lambda: None
        driver._named_cell_stamps = lambda phase: {}
        driver._write_phase_config = lambda path, phase: (True, None)
        return driver

    def _deck(self, driver, n=8):
        from oto.ledger.registry import fingerprint_config
        # Replace the fixture's one-row curated deck so the phase count under
        # test is exactly n (the curated row would otherwise skew the streak).
        (self.tmp / "phases.yaml").write_text("[]")
        rows = []
        for i in range(n):
            cfg = {"Architecture": "gfx90c", "DataType": "S",
                   "MacroTile": f"{32 + 8 * i}x32x16"}
            rows.append({"phase_id": f"phase_gpu_{i}", "label": f"g{i}",
                         "dtype": "s", "shapes": ["128x128x128"],
                         "config": cfg, "fp": fingerprint_config(cfg)})
        self.write_overlay(driver.run_dir.name, rows)
        return rows

    @staticmethod
    def _client_ran(run_dir, phase_id, extra=""):
        """Write a phase dir whose log shows Tensile launched the client.

        The invocation line is exactly what the guard reads: it separates "the
        client ran and measured nothing" (the device is gone) from "the tile
        never built" (a per-config verdict that must not abort a run).
        """
        d = Path(run_dir) / phase_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "stdout.log").write_text(
            "loading config file .../ClientParameters.ini\n" + extra)

    def _run_status(self, run_id):
        import json
        import sqlite3
        with sqlite3.connect(self.registry.db_path) as conn:
            status, meta = conn.execute(
                "SELECT status, metadata FROM runs WHERE run_id=?",
                (run_id,)).fetchone()
        return status, json.loads(meta or "{}")

    def test_a_streak_of_empty_phases_aborts_the_run(self):
        from oto.runners.phases import ABORT_AFTER_CONSECUTIVE_EMPTY
        driver = self._driver()
        self._deck(driver, n=8)
        executed = []

        def fake_execute(phase, run_dir):
            pid = phase["phase_id"]
            executed.append(pid)
            # Mirror the real failure: Tensile's driver hands the config to the
            # client, the client aborts at the probe with a SIGABRT, and no
            # 2_BenchmarkData CSV is written at all.
            self._client_ran(run_dir, pid,
                             "clientExit=1 (ERROR) ... exited with code 134\n"
                             "HIP error: hipErrorNoDevice\n")
            return {"status": "failed", "returncode": 134, "csv_count": 0}

        driver.execute_phase = fake_execute
        driver.run_phases()
        assert len(executed) == ABORT_AFTER_CONSECUTIVE_EMPTY, "the loop iterated past the abort threshold"
        assert driver._stop_requested
        assert "consecutive phases produced no measurement" in driver._abort_note
        assert "hipErrorNoDevice" in driver._abort_note
        status, meta = self._run_status(driver.run_dir.name)
        assert status == "failed", "a GPU-loss abort is a failed run, not an interrupt"
        assert "abort_reason" in meta

    def test_a_client_reached_streak_aborts_without_probe_markers(self):
        """The probe markers only sharpen the message; they must not gate it.

        One of the void run's client-reached phases logged neither
        ``exited with code 134`` nor ``hipErrorNoDevice`` -- its log simply ended
        at ``Log level: Debug``. Deciding the abort on the markers would have
        missed that phase and kept the night burning.
        """
        from oto.runners.phases import ABORT_AFTER_CONSECUTIVE_EMPTY
        driver = self._driver("run_gpu_no_probe")
        self._deck(driver, n=8)
        executed = []

        def fake_execute(phase, run_dir):
            pid = phase["phase_id"]
            executed.append(pid)
            self._client_ran(run_dir, pid, "Log level: Debug\n")
            return {"status": "timeout", "csv_count": 0}

        driver.execute_phase = fake_execute
        driver.run_phases()
        assert len(executed) == ABORT_AFTER_CONSECUTIVE_EMPTY
        assert driver._stop_requested
        assert "consecutive phases produced no measurement" in driver._abort_note

    def test_a_streak_of_build_failures_does_not_abort(self):
        """run_20261017_092909 pinned: five unbuildable tiles in a row is a deck
        verdict, not a lost GPU.

        Its first five executed phases failed with "Generating kernel source
        resulted in error 4" and no client ever ran, yet the run went on to
        complete 400 phases and supply the corpus's A/B -- and
        run_20261018_004835 opened with the same failure three phases deep. A
        guard that counts them aborts a healthy run.
        """
        from oto.runners.phases import ABORT_AFTER_CONSECUTIVE_EMPTY
        driver = self._driver("run_build_fail")
        n = ABORT_AFTER_CONSECUTIVE_EMPTY + 3
        self._deck(driver, n=n)
        executed = []

        def fake_execute(phase, run_dir):
            pid = phase["phase_id"]
            executed.append(pid)
            d = run_dir / pid
            d.mkdir(parents=True, exist_ok=True)
            (d / "stdout.log").write_text(
                "# Filtering processing errors... Done in 0.0 secs\n"
                "Generating kernel source resulted in error 4\n")
            return {"status": "failed", "returncode": 1, "csv_count": 0}

        driver.execute_phase = fake_execute
        driver.run_phases()
        assert len(executed) == n, "a build failure is not evidence the GPU is gone"
        assert not driver._stop_requested
        assert driver._abort_note is None
        assert self._run_status(driver.run_dir.name)[0] == "completed"

    def test_a_measured_phase_resets_the_streak(self):
        driver = self._driver("run_gpu_reset")
        self._deck(driver, n=8)
        executed = []

        def fake_execute(phase, run_dir):
            pid = phase["phase_id"]
            executed.append(pid)
            ok = len(executed) % 5 == 0      # 4 client-run empties, then a result
            self._client_ran(run_dir, pid)
            return {"status": "success" if ok else "failed",
                    "returncode": 0 if ok else 134,
                    "csv_count": 1 if ok else 0}

        driver.execute_phase = fake_execute
        driver.run_phases()
        assert len(executed) == 8, "a lone success must reset the streak"
        assert not driver._stop_requested
        assert driver._abort_note is None
        assert self._run_status(driver.run_dir.name)[0] == "completed"

    def test_a_refused_tile_does_not_count_towards_the_streak(self):
        driver = self._driver("run_gpu_refused")
        self._deck(driver, n=8)
        executed = []
        driver.execute_phase = lambda phase, run_dir: (
            executed.append(phase["phase_id"]) or
            {"status": "skipped_illegal", "phase_id": phase["phase_id"]})
        driver.run_phases()
        assert len(executed) == 8, "a decided refusal is not a lost GPU"
        assert not driver._stop_requested

    def test_a_run_shorter_than_the_threshold_still_completes(self):
        from oto.runners.phases import ABORT_AFTER_CONSECUTIVE_EMPTY
        driver = self._driver("run_gpu_short")
        self._deck(driver, n=ABORT_AFTER_CONSECUTIVE_EMPTY - 1)

        def fake_execute(phase, run_dir):
            self._client_ran(run_dir, phase["phase_id"])
            return {"status": "failed", "returncode": 134, "csv_count": 0}

        driver.execute_phase = fake_execute
        driver.run_phases()
        assert not driver._stop_requested, "aborted below the threshold"
        assert self._run_status(driver.run_dir.name)[0] == "completed"
