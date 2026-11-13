#!/usr/bin/env python3
"""Regression tests for run_status.py's progress and ETA accounting.

No GPU work and no real Tensile: a throwaway sqlite registry is written per test
and the shipped-manifest load is stubbed with a small synthetic deck, so these
run in about a second.

Each test here pins a bug that shipped in the first draft:

  1. `bucket` must count a NULL result.status as a failure. Tensile rejects every
     solution and never fills in result.status, so "unknown" would have hidden
     every hard failure in the report.
  2. Counting per phase_id over-reports. phase_id embeds knobs our parsers
     derive, so a parser fix renames every phase and the same kernel appears
     under two ids. Counting raw phase_ids read 2298 decided against a 2285-cell
     corpus. Identity must come from phase_key (or the phase_id tag for records
     written before phase_key existed).
  3. Progress must be per-tier within the plan. The chain has already decided
     the whole corpus, so `decided / plan_units` reported >100% on a rerun and
     understated real work.
  4. Elapsed is scoped to the head run, not the chain. The chain spans days of
     unrelated ancestor runs.
  5. A run interrupted mid-phase must not be reported as decided.
"""
import io
import json
import sqlite3
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

# This file lives in tests/, so the repo root is one level up. ROOT is both the
# import root and the data root, and both are the repo root -- the harness
# modules are imported flat, so they sit beside this file's parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

import oto.metrics.run_status as rs
import oto.tensile.library as tl


def _phase(tag: str, kernel: str) -> dict:
    """A synthetic emitted phase with a stable tag suffix in its phase_id."""
    return {
        "phase_id": f"phase_ss_gfx900_Ailk_Bjlk_mt32-tt4-vw4-du16-gsu1-{tag}",
        "kernel": kernel,
    }


def _deck() -> list:
    """5 cells: 2 ILLEGAL, 2 UNDER-SPECIFIED, 1 UNREPRODUCIBLE."""
    phases = [_phase("aaa111", "k_aaa"), _phase("bbb222", "k_bbb"),
              _phase("ccc333", "k_ccc"), _phase("ddd444", "k_ddd"),
              _phase("eee555", "k_eee")]
    for i, p in enumerate(phases):
        p["_tier"] = (tl.TIER_FIRST if i < 2 else
                      tl.TIER_HELD if i < 4 else tl.TIER_DROP)
    return phases


def _record(run_id: str, phase: dict, status: str, result: str | None = None,
            *, with_key: bool = True, timestamp: str | None = None) -> dict:
    rec = {
        "type": "general",
        "phase_id": phase["phase_id"],
        "status": status,
        "result": {"status": result} if result is not None else {},
    }
    if with_key:
        rec["phase_key"] = tl.phase_key(phase)
    return rec


class StatusFixture(unittest.TestCase):
    """Builds a temp registry + a stubbed deck, then runs build_report."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        # build_report reads the registry at <base>/gfx90c_results/registry.db
        self.db = self.base / "gfx90c_results" / "registry.db"
        self.db.parent.mkdir(parents=True)
        self.phases = _deck()
        self.tiers = {tl.phase_key(p): p["_tier"] for p in self.phases}
        self.keys = [tl.phase_key(p) for p in self.phases]
        self._init_db()

    def tearDown(self):
        self._tmp.cleanup()

    def _init_db(self):
        """Mirror registry.SQLiteRegistry._init_db, minus the side effects."""
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " run_id TEXT NOT NULL, record_type TEXT NOT NULL,"
                " data JSON NOT NULL, timestamp TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " run_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL,"
                " metadata JSON, started_at TEXT NOT NULL, completed_at TEXT)")
            conn.execute("CREATE INDEX idx_records_run_id ON records(run_id)")

    def add_run(self, run_id: str, status: str, records, *,
                resume_of: str | None = None, started: str | None = None,
                completed: str | None = None):
        meta = {"resume_of": resume_of} if resume_of else None
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, status, metadata, started_at,"
                " completed_at) VALUES (?,?,?,?,?)",
                (run_id, status, json.dumps(meta) if meta else None,
                 started or "2026-09-25T10:00:00",
                 completed or ("2026-09-25T12:00:00"
                               if status == "completed" else None)))
            for rec in records:
                conn.execute(
                    "INSERT INTO records (run_id, record_type, data, timestamp)"
                    " VALUES (?,?,?,?)",
                    (run_id, "general", json.dumps(rec),
                     "2026-09-25T11:00:00"))

    def report(self, plan: rs.RunPlan = None, now=None):
        tiers = self.tiers

        def fake_emit(shipped):
            return [{k: v for k, v in p.items() if k != "_tier"}
                    for p in self.phases]

        def fake_tier(phase, manifest):
            return tiers[tl.phase_key(phase)]

        with mock.patch.object(tl, "load_shipped_manifest",
                               return_value={"solutions": []}), \
             mock.patch.object(tl, "emit_spoof_phases", side_effect=fake_emit), \
             mock.patch.object(tl, "tier_for", side_effect=fake_tier), \
             mock.patch.object(rs.tlib, "load_rerun_manifest", return_value={}):
            return rs.build_report(self.base, None,
                                   plan or rs.RunPlan(rerun_illegal=True),
                                   now=now)


class TestBucket(unittest.TestCase):
    def test_null_result_status_is_a_failure(self):
        # Tensile found no valid solution: status failed, result.status absent.
        assert rs.bucket("failed", None) == "failed"
        assert rs.bucket("failed", "") == "failed"

    def test_completed_success(self):
        assert rs.bucket("completed", "success") == "success"

    def test_skipped_by_user_is_not_a_failure(self):
        assert rs.bucket("failed", "skipped_by_user") == "skipped"

    def test_started_is_active(self):
        assert rs.bucket("started", None) == "active"


class TestIdentityCounting(StatusFixture):
    def test_phase_id_rename_does_not_double_count(self):
        """Same kernel, two phase_id spellings -> one decided cell."""
        p = self.phases[0]
        renamed = dict(p, phase_id=p["phase_id"] + "-v2")
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", p, "completed", "success"),
            _record("gfx900_ref_r1", renamed, "completed", "success"),
        ])
        rep = self.report()
        assert rep["decided"] == 1
        assert rep["decided"] <= rep["corpus"]

    def test_pre_phase_key_records_resolve_by_tag(self):
        """2026-09-25/26 runs predate phase_key; they must still count."""
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", p, "completed", "success", with_key=False)
            for p in self.phases
        ])
        rep = self.report()
        assert rep["decided"] == len(self.phases)
        assert rep["stale_records"] == 0

    def test_resume_overrides_ancestor_verdict(self):
        """A phase re-run in a resume counts once, with the newer verdict."""
        p = self.phases[0]
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", p, "completed", "success")])
        self.add_run("gfx900_ref_r2", "completed", [
            _record("gfx900_ref_r2", p, "failed", None)], resume_of="gfx900_ref_r1")
        rep = self.report()
        assert rep["decided"] == 1
        assert rep["tally"]["failed"] == 1
        assert rep["tally"]["success"] == 0

    def test_unresolvable_record_is_reported_not_hidden(self):
        """No phase_key and an unknown tag must not vanish or inflate."""
        ghost = {"phase_id": "phase_ss_gfx900_Xyz-ffffffff"}
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", ghost, "failed", None, with_key=False)])
        rep = self.report()
        assert rep["decided"] == 0
        assert rep["stale_records"] == 1


class TestPlanProgress(StatusFixture):
    def _fill(self, run_id, n, *, resume_of=None, status="completed"):
        recs = [_record(run_id, p, "completed", "success")
                for p in self.phases[:n]]
        self.add_run(run_id, status, recs, resume_of=resume_of)

    def test_only_released_tiers_count_as_work(self):
        """Unreleased tiers are decided but are not this plan's work."""
        self._fill("gfx900_ref_r1", 5)
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        # 2 ILLEGAL released, 2 of them done -> 0 left.
        assert rep["ref_total"] == 2
        assert rep["ref_done"] == 2
        assert rep["ref_remaining"] == 0

    def test_remaining_counts_undecided_cells_in_released_tiers(self):
        self._fill("gfx900_ref_r1", 1)
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        assert rep["ref_remaining"] == 1

    def test_percent_never_exceeds_100(self):
        """The whole corpus decided + a small plan must not read >100%."""
        self._fill("gfx900_ref_r1", 5)
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        assert rep["estimate"]["percent"] <= 100.0

    def test_all_tiers_selected(self):
        self._fill("gfx900_ref_r1", 3)
        rep = self.report(rs.RunPlan(rerun_illegal=True,
                                      rerun_underspecified=True,
                                      rerun_unreproducible=True))
        assert rep["ref_total"] == 5
        assert rep["ref_remaining"] == 2

    def test_interrupted_phase_is_not_decided(self):
        p = self.phases[0]
        self.add_run("gfx900_ref_r1", "interrupted", [
            _record("gfx900_ref_r1", p, "completed", "success"),
            _record("gfx900_ref_r1", self.phases[1], "started", None),
        ])
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        assert rep["tally"]["active"] == 1
        assert rep["ref_done"] == 1
        assert rep["ref_remaining"] == 1

    def test_skipped_does_not_count_as_done(self):
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", self.phases[0], "failed", "skipped_by_user")])
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        assert rep["decided"] == 0
        assert rep["ref_remaining"] == 2

    def test_tuning_units_follow_plan_and_deck(self):
        """deck * (1 + mutations) * iterations.

        Mutations are per-candidate, so a 10-candidate deck with 1 mutation is
        20 decided phases per iteration, not 11. An earlier docstring called
        (deck + mutations) an upper bound, which understated small decks 4x.
        """
        rep = self.report(rs.RunPlan(rerun_illegal=True, iterations=2,
                                      mutations=1, deck_size=10))
        assert rep["estimate"]["tuning_units"] == 2 * 10 * 2

    def test_tuning_units_scale_with_real_deck(self):
        """The 434-phase deck at the default 10x3 is the shipped shape."""
        rep = self.report(rs.RunPlan(rerun_illegal=True, iterations=10,
                                      mutations=3, deck_size=434))
        assert rep["estimate"]["tuning_units"] == 10 * 434 * 4

    def test_no_tuning_when_iterations_zero(self):
        rep = self.report(rs.RunPlan(rerun_illegal=True, iterations=0))
        assert rep["estimate"]["tuning_units"] == 0

    def test_empty_plan_reports_zero_units(self):
        rep = self.report(rs.RunPlan(rerun_illegal=False,
                                      rerun_underspecified=False,
                                      rerun_unreproducible=False,
                                      iterations=0))
        assert rep["estimate"]["units"] == 0
        assert rep["estimate"]["percent"] is None


class TestChainAndClock(StatusFixture):
    def test_chain_follows_resume_of(self):
        self.add_run("gfx900_ref_r1", "completed", [], started="2026-09-25T10:00:00",
                     completed="2026-09-25T12:00:00")
        self.add_run("gfx900_ref_r2", "completed", [], resume_of="gfx900_ref_r1",
                     started="2026-09-26T10:00:00",
                     completed="2026-09-26T12:00:00")
        self.add_run("gfx900_ref_r3", "interrupted", [], resume_of="gfx900_ref_r2",
                     started="2026-09-28T10:00:00", completed=None)
        rep = self.report()
        assert rep["chain"] == ["gfx900_ref_r1", "gfx900_ref_r2", "gfx900_ref_r3"]
        assert rep["head"] == "gfx900_ref_r3"

    def test_closed_interrupted_run_does_not_outrank_newer_floor(self):
        """A finished interrupted run is history, not the current head.

        Real occurrence: gfx900_ref_20260928_155422_resume was interrupted but
        had closed, while the floor locked five days later had completed. The
        default view stopped on the interrupted run, so every tier count and ETA
        came from a chain eight days stale.
        """
        self.add_run("gfx900_ref_old", "interrupted", [], resume_of=None,
                     started="2026-09-28T10:00:00",
                     completed="2026-09-28T12:00:00")
        self.add_run("gfx900_ref_floor", "completed", [],
                     started="2026-10-03T10:00:00",
                     completed="2026-10-03T12:00:00")
        rep = self.report()
        assert rep["head"] == "gfx900_ref_floor"
        assert rep["chain"] == ["gfx900_ref_floor"]

    def test_unclosed_interrupted_run_still_outranks_older_floor(self):
        """The mirror case: no completed_at means live, resumable work."""
        self.add_run("gfx900_ref_floor", "completed", [],
                     started="2026-10-03T10:00:00",
                     completed="2026-10-03T12:00:00")
        self.add_run("gfx900_ref_live", "interrupted", [],
                     started="2026-10-05T10:00:00", completed=None)
        rep = self.report()
        assert rep["head"] == "gfx900_ref_live"

    def test_newer_native_run_outranks_older_reference(self):
        """Default head must span ALL runs, not just gfx900_ref_* chains.

        Regression: the standalone default was hard-scoped to the gfx900_ref_
        prefix, so it locked onto the newest reference run (a zero-duration
        floor marker) and reported a reference-only 0/1600 progress while the
        real native overnight run sat unused. Native tuning runs are the primary
        workflow; the newest completed run of ANY kind is the head.
        """
        self.add_run("gfx900_ref_old", "completed", [],
                      started="2026-10-03T10:00:00",
                      completed="2026-10-03T12:00:00")
        self.add_run("run_20261009_205427", "completed", [],
                      started="2026-10-09T20:54:00",
                      completed="2026-10-10T04:35:00")
        rep = self.report()
        assert rep["head"] == "run_20261009_205427"
        assert rep["chain"] == ["run_20261009_205427"]

    def test_zero_duration_completed_run_reports_zero_elapsed(self):
        """A completed run that started and stopped at the same instant has
        elapsed 0, not its wall-clock age."""
        self.add_run("gfx900_ref_zero", "completed", [],
                      started="2026-10-03T10:00:00",
                      completed="2026-10-03T10:00:00")
        rep = self.report()
        assert rep["elapsed_minutes"] == 0.0

    def test_elapsed_is_head_run_not_chain_span(self):
        """Two days of ancestor runs must not inflate this run's elapsed."""
        self.add_run("gfx900_ref_r1", "completed", [], started="2026-09-20T10:00:00",
                     completed="2026-09-20T12:00:00")
        self.add_run("gfx900_ref_r2", "interrupted", [], resume_of="gfx900_ref_r1",
                     started="2026-09-28T10:00:00", completed=None)
        # Pin the clock: r2 is still running, so its elapsed is measured against
        # now. Deriving now from the fixture instead of hardcoding it keeps the
        # assertion true no matter what the real calendar says.
        rep = self.report(now=datetime(2026, 9, 28, 12, 0, 0))
        # Elapsed tracks r2 (still running -> falls back to now); the chain
        # span keeps the 8 days for context.
        assert rep["elapsed_minutes"] < 24 * 60
        assert rep["chain_span_minutes"] > 7 * 24 * 60

    def test_completed_head_uses_recorded_timestamps(self):
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", self.phases[0], "completed", "success")],
            started="2026-09-25T10:00:00", completed="2026-09-25T12:30:00")
        rep = self.report()
        self.assertAlmostEqual(rep["elapsed_minutes"], 150.0, places=0)

    def test_cycle_guard_on_self_referential_resume(self):
        self.add_run("gfx900_ref_r1", "completed", [], resume_of="gfx900_ref_r1")
        rep = self.report()
        assert rep["chain"] == ["gfx900_ref_r1"]


class TestRender(unittest.TestCase):
    def test_bar_is_bounded(self):
        assert rs.bar(0.0).startswith("[")
        assert rs.bar(100.0).endswith("]")
        assert rs.bar(-5.0).startswith("[")
        assert rs.bar(500.0).endswith("]")

    def test_fmt_duration(self):
        assert rs.fmt_duration(90) == "1h 30m"
        assert "d" in rs.fmt_duration(60 * 24 * 3)
        assert rs.fmt_duration(None) == "unknown"

    def test_render_survives_empty_report(self):
        rep = {"chain": [], "head": "", "head_status": "unknown",
               "in_flight": False, "corpus": 0, "tally": {}, "decided": 0,
               "tier_rows": [], "ref_total": 0, "ref_done": 0,
               "ref_remaining": 0,
               "elapsed_minutes": None, "chain_span_minutes": None,
               "stale_records": 0, "tuning_tracked": False,
               "estimate": {"units": 0, "decided": 0, "remaining": 0,
                            "percent": None, "minutes_per_unit": None,
                            "rate_per_hour": 0.0, "eta_minutes": None,
                            "source": "unknown", "tuning_units": 0,
                            "deck_size": 0,
                            "rate_sample": [], "rate_sample_n": 0},
               "plan": {"rerun_illegal": False, "iterations": 0,
                        "mutations": 0}, "thermals": None}
        out = rs.render(rep, show_thermals=False)
        assert "nothing selected" in out


class TestRunPlan(unittest.TestCase):
    def test_parse_key_values(self):
        plan = rs.RunPlan.from_args(["rerun_illegal=1", "iterations=3",
                                     "mutations=2"])
        assert plan.rerun_illegal
        assert plan.iterations == 3
        assert plan.mutations == 2

    def test_rejects_unknown_key(self):
        with pytest.raises(SystemExit):
            rs.RunPlan.from_args(["nonsense=1"])

    def test_rejects_malformed_pair(self):
        with pytest.raises(SystemExit):
            rs.RunPlan.from_args(["iterations"])

    def test_rejects_non_integer_iterations(self):
        with pytest.raises(SystemExit):
            rs.RunPlan.from_args(["iterations=many"])

    def test_default_matches_auto_prompt_defaults(self):
        """The status tool must not assume a tier the driver will not rerun.

        The first draft hardcoded rerun_illegal=True while AutoPlan defaults it
        to False, so a bare run_status.py promised ~2 days of GPU work that
        --auto would never schedule.
        """
        import oto.runners.auto_prompt as auto_prompt
        driver = auto_prompt.AutoPlan()
        for field in ("rerun_illegal", "rerun_underspecified",
                      "rerun_unreproducible"):
            assert getattr(rs.RunPlan.from_args([]), field) == getattr(driver, field), f"{field} default diverges from --auto"
        assert rs.RunPlan.from_args([]).iterations == driver.iterations
        assert rs.RunPlan.from_args([]).mutations == driver.mutations


class TestLiveStatus(StatusFixture):
    """The live TTY panel must never be able to kill the run it is watching."""

    def _panel(self, base=None, **kw):
        import io
        return rs.LiveStatus(base or self.base, interval=kw.pop("interval", 0.05),
                             stream=kw.pop("stream", None) or io.StringIO(), **kw)

    def _seed(self):
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", self.phases[0], "completed", "success")],
            started="2026-09-25T10:00:00", completed="2026-09-25T12:00:00")

    class _Tty(io.StringIO):
        """A stream that claims to be a terminal, so the ANSI path is taken."""

        def isatty(self):
            return True

    def test_survives_a_missing_registry(self):
        """build_report raises SystemExit with no registry -- not an Exception.

        A first run starts in exactly that state. If _paint/refresh let it
        escape, the live status takes down the run it was meant to observe.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as empty:
            p = rs.LiveStatus(Path(empty), interval=0.05, stream=io.StringIO())
            p.start()
            p.refresh()          # must not raise
            time.sleep(0.15)
            p.stop()
        assert p.errors > 0, "missing registry was not counted"

    def test_start_and_stop_restore_stdout(self):
        self._seed()
        before = sys.stdout
        p = rs.LiveStatus(self.base, interval=0.05, stream=self._Tty())
        p.start()
        assert sys.stdout is not before, "panel did not wrap stdout"
        p.stop()
        assert sys.stdout is before, "stdout was not restored"

    def test_non_tty_emits_no_ansi_and_appends(self):
        """A piped log must stay readable: no escape codes, no repainting."""
        self._seed()
        buf = io.StringIO()
        p = rs.LiveStatus(self.base, interval=0.05, stream=buf)
        p.start()
        p.refresh()
        time.sleep(0.15)
        p.stop()
        out = buf.getvalue()
        assert "\x1b[" not in out, "ANSI escapes leaked into a non-TTY log"
        assert "elapsed" in out

    def test_panel_lines_are_erased_before_run_output(self):
        """A run's own prints must clear the panel, or the next repaint shreds them."""
        self._seed()
        buf = io.StringIO()
        p = rs.LiveStatus(self.base, interval=0.05, stream=buf)
        p._isatty = True
        p._painted = 5
        proxy = rs._PanelStdout(buf, p)
        proxy.write("Skipping phase phase_ss_x_1\n")
        out = buf.getvalue()
        # The erase must come first, so the panel is gone before the new line
        # is written and the next repaint cannot overwrite the line.
        assert out.startswith("\x1b[5A\x1b[J"), f"panel was not erased first: {out!r}"
        assert "Skipping phase phase_ss_x_1" in out
        assert p._painted == 0

    def test_errors_do_not_escape_a_refresh(self):
        self._seed()
        p = self._panel()
        with mock.patch.object(rs, "build_report", side_effect=SystemExit("no db")):
            p.refresh()          # must not raise
        assert p.errors == 1


class TestExecutionTiming(StatusFixture):
    """Execution time in the acceptance report."""

    def _driver(self):
        from oto.ledger.registry import SQLiteRegistry
        from oto.runners.cli import TensileDriver
        d = TensileDriver.__new__(TensileDriver)
        d.base_dir = self.base
        d._last_run_status = "completed"
        d.registry = SQLiteRegistry(self.base)
        d._reference_floor_runs = lambda rid: ["gfx900_ref_floor_r1"]
        return d

    def test_run_timing_reports_wall_clock(self):
        self.add_run("gfx900_ref_floor_r1", "completed", [],
                     started="2026-09-25T10:00:00",
                     completed="2026-09-26T12:30:00")
        d = self._driver()
        t = d._compute_execution_timing("gfx900_ref_floor_r1")
        run = t["native_run"]
        self.assertAlmostEqual(run["elapsed_minutes"], 1590.0, places=1)
        assert run["elapsed_human"] == "1d 2h 30m"
        assert not run["in_flight"]

    def test_in_flight_run_reports_no_elapsed_yet(self):
        """A run still going has no execution time; saying so beats 0.0."""
        self.add_run("gfx900_ref_floor_r1", "interrupted", [],
                     started="2026-09-25T10:00:00", completed=None)
        d = self._driver()
        run = d._compute_execution_timing("gfx900_ref_floor_r1")["native_run"]
        assert run["elapsed_minutes"] is None
        assert run["elapsed_human"] == "unknown"
        assert run["in_flight"]

    def test_chain_and_native_are_reported_separately(self):
        """A resumed floor spans runs; one number would understate its cost."""
        self.add_run("gfx900_ref_floor_r1", "completed", [],
                     started="2026-09-25T10:00:00", completed="2026-09-25T12:00:00")
        d = self._driver()
        t = d._compute_execution_timing("gfx900_ref_floor_r1",
                                        {"SS": {"total_min": 5.0}})
        assert t["reference_chain"]["elapsed_minutes"] == 120.0
        assert t["phase_busy"]["minutes"] == 5.0
        assert "SS" in t["phase_busy"]["per_family_minutes"]

    def test_unknown_run_does_not_raise(self):
        d = self._driver()
        t = d._compute_execution_timing("no_such_run")
        assert t["native_run"]["elapsed_minutes"] is None
        assert t["native_run"]["elapsed_human"] == "unknown"

    def test_summary_includes_execution_time(self):
        from oto.metrics.report import ABVerdict, AcceptanceReporter
        r = AcceptanceReporter(self.base)
        v = [ABVerdict(dtype="S", shape="1024x1024x1024", fp="f",
                       native_median=1.0, spoof_median=1.0, delta_pct=0.0,
                       tie=True, verdict="TIE", family="SS",
                       native_value=1.0, spoof_value=1.0, agg="winner")]
        timing = {"native_run": {"elapsed_human": "1d 2h 30m",
                                 "elapsed_minutes": 1590.0, "in_flight": False}}
        rep = r.generate_acceptance_report(
            run_id="r1", ab_verdicts=v, all_analytics=[], red_list=[],
            execution_timing=timing)
        assert "Execution time: 1d 2h 30m" in rep.summary
        assert rep.execution_timing == timing

    def test_timing_is_serialised_into_the_report_json(self):
        """family_timing used to be computed and then dropped on the floor."""
        from oto.metrics.report import AcceptanceReporter
        r = AcceptanceReporter(self.base)
        timing = {"native_run": {"elapsed_human": "3h", "elapsed_minutes": 180.0,
                                 "in_flight": False}}
        ft = {"SS": {"cells": 3, "mean_sec": 10.0, "total_min": 0.5}}
        rep = r.generate_acceptance_report(
            run_id="r1", ab_verdicts=[], all_analytics=[], red_list=[],
            family_timing=ft, execution_timing=timing)
        out = self.base / "rep.json"
        r.write_report(rep, out)
        got = json.loads(out.read_text())
        assert got["execution_timing"] == timing
        assert got["family_timing"] == ft


if __name__ == "__main__":
    unittest.main(verbosity=2)
