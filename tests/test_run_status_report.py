#!/usr/bin/env python3
"""Report-side regression tests for run_status accounting and rendering.

No GPU work and no real Tensile: a throwaway sqlite registry is written per
test and the shipped-manifest load is stubbed with a small synthetic deck.

Each test here pins a bug that shipped in the first draft:

  1. `bucket` must count a NULL result.status as a failure.
  2. Counting per phase_id over-reports; identity comes from phase_key.
  3. Progress must be per-tier within the plan, not decided/plan_units.
  4. Elapsed is scoped to the head run, not the chain.
  5. A run interrupted mid-phase must not be reported as decided.
"""
import unittest
from datetime import datetime

import pytest

# (import side effect: the fixture module puts the repo root on sys.path)
from support_run_status import StatusFixture, _record

import oto.metrics.run_status as rs


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
