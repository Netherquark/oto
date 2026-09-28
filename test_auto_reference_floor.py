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

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import port_tensile  # noqa: E402
from port_tensile import TensileDriver  # noqa: E402
from auto_prompt import AutoPlan  # noqa: E402


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
    drv._load_analytics_from_run = lambda: []
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
        self.assertTrue(drv._reference_floor_authoritative)
        self.assertFalse(res.get("reason", "").startswith("reference"))

    def test_incomplete_recalled_floor_still_runs_native(self):
        drv, res = self._run(ref_exists=True, remaining=5,
                             resume_status="interrupted", fresh_status="completed")
        self.assertFalse(drv._reference_floor_authoritative)
        self.assertEqual(drv._reference_floor_status, "interrupted")
        self.assertNotIn("reference", res.get("reason", ""),
                         "must not early-return before tuning")

    def test_floor_still_incomplete_after_resume_still_runs_native(self):
        """The exact shape of the three wasted overnight runs."""
        drv, res = self._run(ref_exists=True, remaining=5,
                             resume_status="failed", fresh_status="completed")
        self.assertFalse(drv._reference_floor_authoritative)
        self.assertEqual(drv._reference_floor_status, "failed")
        self.assertNotIn("reference", res.get("reason", ""),
                         "must not early-return before tuning")

    def test_no_floor_and_fresh_attempt_fails_still_runs_native(self):
        drv, res = self._run(ref_exists=False, remaining=127,
                             resume_status="failed", fresh_status="failed")
        self.assertFalse(drv._reference_floor_authoritative)
        self.assertNotIn("reference", res.get("reason", ""),
                         "must not early-return before tuning")

    def test_no_floor_and_fresh_attempt_completes_is_authoritative(self):
        drv, _ = self._run(ref_exists=False, remaining=0,
                          resume_status="completed", fresh_status="completed")
        self.assertTrue(drv._reference_floor_authoritative)

    def test_native_phase_execution_was_reached(self):
        """Belt and braces: prove the loop body actually ran."""
        drv, _ = self._run(ref_exists=True, remaining=5,
                           resume_status="failed", fresh_status="completed")
        self.assertTrue(drv._finish_after_iteration,
                        "run_phases was never reached")


class TestDeclinedReference(unittest.TestCase):
    """Answering no to all three questions must not quietly start a reference
    run -- and answering yes to any one of them must."""

    def setUp(self):
        self.tmp = Path("/tmp/opencode/autofloor")
        self.tmp.mkdir(parents=True, exist_ok=True)

    def test_no_answers_never_call_run_gfx900_reference(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=127,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_illegal=False,
                                             rerun_underspecified=False))
        drv.run_gfx900_reference.assert_not_called()
        self.assertFalse(drv._reference_floor_authoritative)
        self.assertIn("declined", drv._reference_floor_status)

    def test_yes_to_unreproducible_alone_does_call_it(self):
        """Q3 alone is a real opt-in: T3 cannot be rebuilt, but a Tensile
        upgrade may have changed that, so the user's yes must reach the run."""
        drv = make_driver(self.tmp, ref_exists=False, remaining=277,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_illegal=False,
                                             rerun_underspecified=False,
                                             rerun_unreproducible=True))
        drv.run_gfx900_reference.assert_called_once()
        self.assertTrue(drv.run_gfx900_reference.call_args.kwargs["release_drop"])
        # and it must NOT have dragged the ~1-day T2 release along with it
        self.assertFalse(drv.run_gfx900_reference.call_args.kwargs["release_held"])

    def test_q2_alone_releases_only_held(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=1881,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               plan=AutoPlan(rerun_underspecified=True))
        kw = drv.run_gfx900_reference.call_args.kwargs
        self.assertTrue(kw["release_held"])
        self.assertFalse(kw["release_drop"])

    def test_legacy_flag_still_answers_q2_only(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=1881,
                          resume_status="completed", fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=False,
                               release_held=True,
                               plan=AutoPlan(rerun_illegal=False,
                                             rerun_underspecified=False))
        kw = drv.run_gfx900_reference.call_args.kwargs
        self.assertTrue(kw["release_held"])
        self.assertFalse(kw["release_drop"])

    def test_yes_to_illegal_does_call_it(self):
        drv = make_driver(self.tmp, ref_exists=False, remaining=127,
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
        self.assertEqual(drv._auto_plan.iterations, 10)
        self.assertEqual(drv._auto_plan.mutations, 3)


class TestSkipReference(unittest.TestCase):
    def test_skip_reference_marks_no_floor(self):
        drv = make_driver(Path("/tmp/opencode/autofloor"), ref_exists=True,
                          remaining=0, resume_status="completed",
                          fresh_status="completed")
        TensileDriver.run_auto(drv, budget=1, skip_reference=True,
                               plan=AutoPlan())
        self.assertIsNone(drv._last_ab_reference_run_id)
        self.assertTrue(drv._reference_floor_authoritative)


class TestProvisionalFloorIsLabelled(unittest.TestCase):
    """An unfinished floor must not produce a report that reads as final."""

    def test_summary_is_marked_provisional(self):
        from report import AcceptanceReporter
        rep = AcceptanceReporter(Path("/tmp/opencode/autofloor"))
        report = rep.generate_acceptance_report(
            run_id="r1", ab_verdicts=[], all_analytics=[], red_list=[],
            reference_run_id="gfx900_ref_floor",
            reference_floor_status="failed",
            reference_floor_authoritative=False,
        )
        self.assertIn("PROVISIONAL FLOOR", report.summary)
        self.assertIn("failed", report.summary)
        self.assertFalse(report.reference_floor_authoritative)

    def test_complete_floor_summary_is_unchanged(self):
        from report import AcceptanceReporter
        rep = AcceptanceReporter(Path("/tmp/opencode/autofloor"))
        report = rep.generate_acceptance_report(
            run_id="r1", ab_verdicts=[], all_analytics=[], red_list=[],
            reference_run_id="gfx900_ref_floor",
        )
        self.assertNotIn("PROVISIONAL FLOOR", report.summary)
        self.assertTrue(report.reference_floor_authoritative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
