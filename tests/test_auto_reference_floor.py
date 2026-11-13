#!/usr/bin/env python3
"""
test_auto_reference_floor.py -- --auto must always reach native tuning.

Regression for a policy bug that made overnight runs produce nothing. Three
consecutive runs (gfx900_ref_20260928_023401_resume / _023858_resume /
_092818_resume) each spent their entire budget on the mandatory reference floor
and completed 0 of 127 phases, because run_auto() returned early on any
incomplete or failed reference result. The floor is worth attempting, but it
must never be able to consume a whole budget with zero native measurements.

Run: python3 test_auto_reference_floor.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

# This file lives in tests/, so the repo root is one level up. BASE is both the
# import root and the data root, and both are the repo root -- the harness
# modules are imported flat, so they sit beside this file's parent.
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.runners.auto_prompt import AutoPlan
from oto.runners.cli import TensileDriver

#: Stand-in for "the reference floor still owes work". The value is opaque to
#: run_auto -- it only ever asks whether the count is zero -- so it is a
#: placeholder rather than a real corpus size, which would go stale the moment
#: a cell is re-triaged.
OWES_WORK = 1


def make_driver(tmp: Path, *, ref_exists: bool, remaining: int,
                resume_status: str, fresh_status: str) -> TensileDriver:
    """A driver with run_auto's collaborators stubbed out.

    Only the reference-floor bookkeeping and the first iteration are real, so
    each case runs in milliseconds and never touches a GPU.
    """
    drv = TensileDriver.__new__(TensileDriver)
    drv.run_dir = tmp
    drv._stop_requested = False
    drv._finish_after_iteration = False
    drv._last_ab_reference_run_id = None

    drv.run_preflight = lambda: True
    drv._reference_remaining = lambda: remaining
    drv._latest_reference_run = lambda exclude=None: "gfx900_ref_floor" if ref_exists else None
    drv.run_gfx900_reference = mock.Mock(return_value={"status": resume_status,
                                                      "run_id": "gfx900_ref_new"})

    # Stop right after the native loop's first pass.
    drv.load_phases_manifest = lambda: [{"phase_id": "p1"}]

    def _run_phases(**kw):
        drv._finish_after_iteration = True
        return {"executed": 0, "skipped": 0}

    drv.run_phases = _run_phases
    drv._retire_stable_candidates = lambda: None
    drv._load_analytics_from_run = list
    drv.generate_acceptance_report = lambda **kw: None
    # `agent` is assigned in __init__, which __new__ bypasses.
    drv.agent = types.SimpleNamespace(
        converged=lambda *a, **k: types.SimpleNamespace(converged=False, reason="continue"))
    return drv


class TestAutoAlwaysReachesNative(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/opencode/autofloor")
        self.tmp.mkdir(parents=True, exist_ok=True)

    def _run(self, plan=None, **kw):
        drv = make_driver(self.tmp, **kw)
        plan = plan or AutoPlan(rerun_illegal=True, rerun_underspecified=False)
        return drv, TensileDriver.run_auto(drv, budget=1, skip_reference=False, plan=plan)

    def test_complete_floor_is_authoritative(self):
        drv, res = self._run(ref_exists=True, remaining=0,
                             resume_status="completed", fresh_status="completed")
        assert drv._reference_floor_authoritative
        assert not res.get("reason", "").startswith("reference")

    def test_incomplete_recalled_floor_still_runs_native(self):
        drv, res = self._run(ref_exists=True, remaining=5,
                             resume_status="interrupted", fresh_status="completed")
        assert not drv._reference_floor_authoritative
        assert drv._reference_floor_status == "interrupted"
        assert "reference" not in res.get("reason", ""), "must not early-return before tuning"

    def test_floor_still_incomplete_after_resume_still_runs_native(self):
        """The exact shape of the three wasted overnight runs."""
        drv, res = self._run(ref_exists=True, remaining=5,
                             resume_status="failed", fresh_status="completed")
        assert not drv._reference_floor_authoritative
        assert drv._reference_floor_status == "failed"
        assert "reference" not in res.get("reason", ""), "must not early-return before tuning"

    def test_no_floor_and_fresh_attempt_fails_still_runs_native(self):
        drv, res = self._run(ref_exists=False, remaining=OWES_WORK,
                             resume_status="failed", fresh_status="failed")
        assert not drv._reference_floor_authoritative
        assert "reference" not in res.get("reason", ""), "must not early-return before tuning"

    def test_no_floor_and_fresh_attempt_completes_is_authoritative(self):
        drv, _ = self._run(ref_exists=False, remaining=0,
                          resume_status="completed", fresh_status="completed")
        assert drv._reference_floor_authoritative

    def test_native_phase_execution_was_reached(self):
        """Belt and braces: prove the loop body actually ran."""
        drv, _ = self._run(ref_exists=True, remaining=5,
                           resume_status="failed", fresh_status="completed")
        assert drv._finish_after_iteration, "run_phases was never reached"


class TestDeclinedReference(unittest.TestCase):
    """Answering no to all three questions must not quietly start a reference
    run -- and answering yes to any one of them must."""

    def setUp(self):
        self.tmp = Path("/tmp/opencode/autofloor")
        self.tmp.mkdir(parents=True, exist_ok=True)

    def test_no_answers_never_call_run_gfx900_reference(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=OWES_WORK,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_illegal=False,
                                             rerun_underspecified=False))
        drv.run_gfx900_reference.assert_not_called()
        assert not drv._reference_floor_authoritative
        assert "declined" in drv._reference_floor_status

    def test_yes_to_unreproducible_alone_does_call_it(self):
        """Q3 alone is a real opt-in: T3 cannot be rebuilt, but a Tensile
        upgrade may have changed that, so the user's yes must reach the run."""
        drv = make_driver(self.tmp, ref_exists=False, remaining=OWES_WORK,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_illegal=False,
                                             rerun_underspecified=False,
                                             rerun_unreproducible=True))
        drv.run_gfx900_reference.assert_called_once()
        assert drv.run_gfx900_reference.call_args.kwargs["release_drop"]
        # and it must NOT have dragged the ~1-day T2 release along with it
        assert not drv.run_gfx900_reference.call_args.kwargs["release_held"]

    def test_q2_alone_releases_only_held(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=OWES_WORK,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_underspecified=True))
        kw = drv.run_gfx900_reference.call_args.kwargs
        assert kw["release_held"]
        assert not kw["release_drop"]

    def test_legacy_flag_still_answers_q2_only(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=OWES_WORK,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               release_held=True,
                               plan=AutoPlan(rerun_illegal=False,
                                             rerun_underspecified=False))
        kw = drv.run_gfx900_reference.call_args.kwargs
        assert kw["release_held"]
        assert not kw["release_drop"]

    def test_yes_to_illegal_does_call_it(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=OWES_WORK,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_illegal=True,
                                             rerun_underspecified=False))
        drv.run_gfx900_reference.assert_called()

    def test_plan_numbers_reach_the_loop(self):
        drv = make_driver(self.tmp, ref_exists=True, remaining=0,
                          resume_status="completed", fresh_status="completed")
        plan = AutoPlan(rerun_illegal=True, iterations=10, mutations=3)
        TensileDriver.run_auto(drv, skip_reference=False, plan=plan)
        assert drv._auto_plan.iterations == 10
        assert drv._auto_plan.mutations == 3


class TestSkipReference(unittest.TestCase):
    def test_skip_reference_marks_no_floor(self):
        drv = make_driver(Path("/tmp/opencode/autofloor"), ref_exists=True,
                          remaining=0, resume_status="completed",
                          fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=True,
                               plan=AutoPlan())
        assert drv._last_ab_reference_run_id is None
        assert drv._reference_floor_authoritative


class TestProvisionalFloorIsLabelled(unittest.TestCase):
    """An unfinished floor must not produce a report that reads as final."""

    def test_summary_is_marked_provisional(self):
        from oto.metrics.report import AcceptanceReporter
        rep = AcceptanceReporter(Path("/tmp/opencode/autofloor"))
        report = rep.generate_acceptance_report(
            run_id="r1", ab_verdicts=[], all_analytics=[], red_list=[],
            reference_run_id="gfx900_ref_floor",
            reference_floor_status="failed",
            reference_floor_authoritative=False,
        )
        assert "PROVISIONAL FLOOR" in report.summary
        assert "failed" in report.summary
        assert not report.reference_floor_authoritative

    def test_complete_floor_summary_is_unchanged(self):
        from oto.metrics.report import AcceptanceReporter
        rep = AcceptanceReporter(Path("/tmp/opencode/autofloor"))
        report = rep.generate_acceptance_report(
            run_id="r1", ab_verdicts=[], all_analytics=[], red_list=[],
            reference_run_id="gfx900_ref_floor",
        )
        assert "PROVISIONAL FLOOR" not in report.summary
        assert report.reference_floor_authoritative


class TestAbSubjectIsNotTheFloor(unittest.TestCase):
    """The A/B subject run must never be the gfx900 floor itself.

    Regression found while preflighting the overnight run. With no run
    directory (--dry-run, --report) the report fell back to
    registry.latest_run_id(), which returns the newest row in the runs table
    whatever its arm -- and the newest row is normally the reference floor. The
    floor as subject is doubly wrong: _reference_floor_runs() excludes the
    subject when the subject is a gfx900_ref run, so the floor ended up scored
    against itself minus its own head. That halved every spoof kernel count and
    moved four verdicts with no error anywhere:

        CC:1024      LOSS -5.47  ->  TIE  +3.05
        HH_HPA:4096  LOSS -9.76  ->  WIN +17.87
        HS_HPA:4096  TIE  -0.67  ->  WIN +16.75
        ZZ:1024      TIE  +4.64  ->  WIN  +5.67

    11/11/16 became 14/10/14 -- a report that looked better because it was
    measuring a different thing.
    """

    def _registry(self, tmp):
        from oto.ledger.registry import SQLiteRegistry
        reg = SQLiteRegistry(Path(tmp))          # creates the schema for us
        import sqlite3
        with sqlite3.connect(str(reg.db_path)) as conn:
            for run_id in ("run_native_old", "run_native_new",
                           "gfx900_ref_20260926_resume",
                           "gfx900_ref_20260929_resume"):
                conn.execute(
                    "INSERT INTO runs (run_id, status, metadata, started_at,"
                    " completed_at) VALUES (?, 'completed', NULL, ?, ?)",
                    (run_id, "2026-09-25T10:00:00", "2026-09-25T12:00:00"))
        return reg

    def test_latest_run_id_can_exclude_the_reference_arm(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._registry(tmp)
            # Unfiltered: the newest row is the floor head.
            assert reg.latest_run_id() == "gfx900_ref_20260929_resume"
            # Native-only: the newest native run.
            assert reg.latest_run_id(arm="native") == "run_native_new"

    def test_report_subject_resolves_to_a_native_run(self):
        """regenerate_report must hand a native run to the A/B, not the floor.

        Asserted at the hand-off rather than by running the whole report, so
        the test needs no analytics/CSV state: the bug was in run_id selection,
        not in report generation.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = TensileDriver.__new__(TensileDriver)
            d.base_dir = Path(tmp)
            d.run_dir = None
            d.registry = self._registry(tmp)
            seen = {}
            with mock.patch.object(
                TensileDriver, "generate_acceptance_report",
                side_effect=lambda run_dir=None, run_id=None, **kw:
                    seen.update(run_id=run_id) or {"run_id": run_id},
            ):
                got = d.regenerate_report()
            assert seen.get("run_id") == "run_native_new", "A/B subject resolved to the reference floor"
            assert got["run_id"] == "run_native_new"

    def test_explicit_run_id_is_still_honoured(self):
        """The arm filter is only a default; an explicit run_id wins."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = TensileDriver.__new__(TensileDriver)
            d.base_dir = Path(tmp)
            d.run_dir = None
            d.registry = self._registry(tmp)
            seen = {}
            with mock.patch.object(
                TensileDriver, "generate_acceptance_report",
                side_effect=lambda run_dir=None, run_id=None, **kw:
                    seen.update(run_id=run_id) or {"run_id": run_id},
            ):
                d.regenerate_report(run_id="run_native_old")
            assert seen.get("run_id") == "run_native_old"


if __name__ == "__main__":
    unittest.main(verbosity=2)
