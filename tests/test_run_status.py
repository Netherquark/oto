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
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

# This file lives in tests/, so the repo root is one level up. ROOT is both the
# import root and the data root, and both are the repo root -- the harness
# modules are imported flat, so they sit beside this file's parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run_status as rs  # noqa: E402
import tensile_library as tl  # noqa: E402


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


def _record(run_id: str, phase: dict, status: str, result: str = None,
            *, with_key: bool = True, timestamp: str = None) -> dict:
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
                resume_of: str = None, started: str = None,
                completed: str = None):
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

    def report(self, plan: rs.RunPlan = None):
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
                                   plan or rs.RunPlan(rerun_illegal=True))


class TestBucket(unittest.TestCase):
    def test_null_result_status_is_a_failure(self):
        # Tensile found no valid solution: status failed, result.status absent.
        self.assertEqual(rs.bucket("failed", None), "failed")
        self.assertEqual(rs.bucket("failed", ""), "failed")

    def test_completed_success(self):
        self.assertEqual(rs.bucket("completed", "success"), "success")

    def test_skipped_by_user_is_not_a_failure(self):
        self.assertEqual(rs.bucket("failed", "skipped_by_user"), "skipped")

    def test_started_is_active(self):
        self.assertEqual(rs.bucket("started", None), "active")


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
        self.assertEqual(rep["decided"], 1)
        self.assertLessEqual(rep["decided"], rep["corpus"])

    def test_pre_phase_key_records_resolve_by_tag(self):
        """2026-09-25/26 runs predate phase_key; they must still count."""
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", p, "completed", "success", with_key=False)
            for p in self.phases
        ])
        rep = self.report()
        self.assertEqual(rep["decided"], len(self.phases))
        self.assertEqual(rep["stale_records"], 0)

    def test_resume_overrides_ancestor_verdict(self):
        """A phase re-run in a resume counts once, with the newer verdict."""
        p = self.phases[0]
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", p, "completed", "success")])
        self.add_run("gfx900_ref_r2", "completed", [
            _record("gfx900_ref_r2", p, "failed", None)], resume_of="gfx900_ref_r1")
        rep = self.report()
        self.assertEqual(rep["decided"], 1)
        self.assertEqual(rep["tally"]["failed"], 1)
        self.assertEqual(rep["tally"]["success"], 0)

    def test_unresolvable_record_is_reported_not_hidden(self):
        """No phase_key and an unknown tag must not vanish or inflate."""
        ghost = {"phase_id": "phase_ss_gfx900_Xyz-ffffffff"}
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", ghost, "failed", None, with_key=False)])
        rep = self.report()
        self.assertEqual(rep["decided"], 0)
        self.assertEqual(rep["stale_records"], 1)


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
        self.assertEqual(rep["ref_total"], 2)
        self.assertEqual(rep["ref_done"], 2)
        self.assertEqual(rep["ref_remaining"], 0)

    def test_remaining_counts_undecided_cells_in_released_tiers(self):
        self._fill("gfx900_ref_r1", 1)
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        self.assertEqual(rep["ref_remaining"], 1)

    def test_percent_never_exceeds_100(self):
        """The whole corpus decided + a small plan must not read >100%."""
        self._fill("gfx900_ref_r1", 5)
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        self.assertLessEqual(rep["estimate"]["percent"], 100.0)

    def test_all_tiers_selected(self):
        self._fill("gfx900_ref_r1", 3)
        rep = self.report(rs.RunPlan(rerun_illegal=True,
                                      rerun_underspecified=True,
                                      rerun_unreproducible=True))
        self.assertEqual(rep["ref_total"], 5)
        self.assertEqual(rep["ref_remaining"], 2)

    def test_interrupted_phase_is_not_decided(self):
        p = self.phases[0]
        self.add_run("gfx900_ref_r1", "interrupted", [
            _record("gfx900_ref_r1", p, "completed", "success"),
            _record("gfx900_ref_r1", self.phases[1], "started", None),
        ])
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        self.assertEqual(rep["tally"]["active"], 1)
        self.assertEqual(rep["ref_done"], 1)
        self.assertEqual(rep["ref_remaining"], 1)

    def test_skipped_does_not_count_as_done(self):
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", self.phases[0], "failed", "skipped_by_user")])
        rep = self.report(rs.RunPlan(rerun_illegal=True))
        self.assertEqual(rep["decided"], 0)
        self.assertEqual(rep["ref_remaining"], 2)

    def test_tuning_units_follow_plan_and_deck(self):
        """deck * (1 + mutations) * iterations.

        Mutations are per-candidate, so a 10-candidate deck with 1 mutation is
        20 decided phases per iteration, not 11. An earlier docstring called
        (deck + mutations) an upper bound, which understated small decks 4x.
        """
        rep = self.report(rs.RunPlan(rerun_illegal=True, iterations=2,
                                      mutations=1, deck_size=10))
        self.assertEqual(rep["estimate"]["tuning_units"], 2 * 10 * 2)

    def test_tuning_units_scale_with_real_deck(self):
        """The 434-phase deck at the default 10x3 is the shipped shape."""
        rep = self.report(rs.RunPlan(rerun_illegal=True, iterations=10,
                                      mutations=3, deck_size=434))
        self.assertEqual(rep["estimate"]["tuning_units"], 10 * 434 * 4)

    def test_no_tuning_when_iterations_zero(self):
        rep = self.report(rs.RunPlan(rerun_illegal=True, iterations=0))
        self.assertEqual(rep["estimate"]["tuning_units"], 0)

    def test_empty_plan_reports_zero_units(self):
        rep = self.report(rs.RunPlan(rerun_illegal=False,
                                      rerun_underspecified=False,
                                      rerun_unreproducible=False,
                                      iterations=0))
        self.assertEqual(rep["estimate"]["units"], 0)
        self.assertIsNone(rep["estimate"]["percent"])


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
        self.assertEqual(rep["chain"], ["gfx900_ref_r1", "gfx900_ref_r2", "gfx900_ref_r3"])
        self.assertEqual(rep["head"], "gfx900_ref_r3")

    def test_elapsed_is_head_run_not_chain_span(self):
        """Two days of ancestor runs must not inflate this run's elapsed."""
        self.add_run("gfx900_ref_r1", "completed", [], started="2026-09-20T10:00:00",
                     completed="2026-09-20T12:00:00")
        self.add_run("gfx900_ref_r2", "interrupted", [], resume_of="gfx900_ref_r1",
                     started="2026-09-28T10:00:00", completed=None)
        rep = self.report()
        # Elapsed tracks r2 (still running -> falls back to now); the chain
        # span keeps the 8 days for context.
        self.assertLess(rep["elapsed_minutes"], 24 * 60)
        self.assertGreater(rep["chain_span_minutes"], 7 * 24 * 60)

    def test_completed_head_uses_recorded_timestamps(self):
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", self.phases[0], "completed", "success")],
            started="2026-09-25T10:00:00", completed="2026-09-25T12:30:00")
        rep = self.report()
        self.assertAlmostEqual(rep["elapsed_minutes"], 150.0, places=0)

    def test_cycle_guard_on_self_referential_resume(self):
        self.add_run("gfx900_ref_r1", "completed", [], resume_of="gfx900_ref_r1")
        rep = self.report()
        self.assertEqual(rep["chain"], ["gfx900_ref_r1"])


class TestRender(unittest.TestCase):
    def test_bar_is_bounded(self):
        self.assertTrue(rs.bar(0.0).startswith("["))
        self.assertTrue(rs.bar(100.0).endswith("]"))
        self.assertTrue(rs.bar(-5.0).startswith("["))
        self.assertTrue(rs.bar(500.0).endswith("]"))

    def test_fmt_duration(self):
        self.assertEqual(rs.fmt_duration(90), "1h 30m")
        self.assertIn("d", rs.fmt_duration(60 * 24 * 3))
        self.assertEqual(rs.fmt_duration(None), "unknown")

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
        self.assertIn("nothing selected", out)


class TestRunPlan(unittest.TestCase):
    def test_parse_key_values(self):
        plan = rs.RunPlan.from_args(["rerun_illegal=1", "iterations=3",
                                     "mutations=2"])
        self.assertTrue(plan.rerun_illegal)
        self.assertEqual(plan.iterations, 3)
        self.assertEqual(plan.mutations, 2)

    def test_rejects_unknown_key(self):
        with self.assertRaises(SystemExit):
            rs.RunPlan.from_args(["nonsense=1"])

    def test_rejects_malformed_pair(self):
        with self.assertRaises(SystemExit):
            rs.RunPlan.from_args(["iterations"])

    def test_rejects_non_integer_iterations(self):
        with self.assertRaises(SystemExit):
            rs.RunPlan.from_args(["iterations=many"])

    def test_default_matches_auto_prompt_defaults(self):
        """The status tool must not assume a tier the driver will not rerun.

        The first draft hardcoded rerun_illegal=True while AutoPlan defaults it
        to False, so a bare run_status.py promised ~2 days of GPU work that
        --auto would never schedule.
        """
        import auto_prompt
        driver = auto_prompt.AutoPlan()
        for field in ("rerun_illegal", "rerun_underspecified",
                      "rerun_unreproducible"):
            self.assertEqual(getattr(rs.RunPlan.from_args([]), field),
                             getattr(driver, field),
                             f"{field} default diverges from --auto")
        self.assertEqual(rs.RunPlan.from_args([]).iterations,
                         driver.iterations)
        self.assertEqual(rs.RunPlan.from_args([]).mutations, driver.mutations)


if __name__ == "__main__":
    unittest.main(verbosity=2)
