#!/usr/bin/env python3
"""
test_proposals_ledger.py — the append-only `proposals` ledger.

Covers the properties Option H Phase 1 depends on (proposal.md §H.3.1/§H.3.2,
implementation_plan.md Hplan.3 steps 2-4):

  * the migration is additive and never rewrites an existing table or row
  * one INSERT per emitted candidate; re-emission is a no-op, not an error
  * `outcome` advances pending -> terminal exactly once, and never back
  * novelty = absent from BOTH the ledger and the registry's decided set
  * novelty survives the loss of the registry's decided set (the durability
    claim), tested on a copy

Every count in this file is read from the database at runtime. No test asserts
a corpus size, and none transcribes a historical figure.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registry import SQLiteRegistry, fingerprint_config


def _record_data(fp, status="completed"):
    """A `records` row shaped like the real ones (fp nested inside JSON)."""
    return json.dumps({"fp": fp, "status": status, "phase_id": "phase_x"})


class LedgerSchemaTests(unittest.TestCase):
    """Additive migration."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_ledger_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)

    def test_tables_all_created_including_proposals(self):
        with sqlite3.connect(self.reg.db_path) as c:
            names = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        for expected in ("records", "phases", "runs", "proposals"):
            self.assertIn(expected, names)

    def test_reopening_an_existing_db_adds_proposals_without_losing_records(self):
        fp = fingerprint_config({"MacroTile": "64x64x16"})
        self.reg.append_record({"fp": fp, "status": "completed"}, run_id="r1")
        before = len(self.reg.read_records())

        # Simulate a pre-ledger database: drop the table, then reopen.
        with sqlite3.connect(self.reg.db_path) as c:
            c.execute("DROP TABLE proposals")
            c.commit()

        reopened = SQLiteRegistry(self.tmp)
        with sqlite3.connect(reopened.db_path) as c:
            names = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("proposals", names)
        self.assertEqual(len(reopened.read_records()), before)
        self.assertTrue(reopened.has_fp_passed(fp))

    def test_proposals_table_has_no_delete_path_on_the_registry(self):
        """The registry exposes no method that can remove a ledger row.

        Not a behavioural test so much as an interface one: append-only has to
        hold by construction, not by every future caller remembering.
        """
        offenders = [n for n in dir(self.reg) if "delete" in n.lower() or "remove" in n.lower()]
        self.assertEqual(offenders, [], f"registry grew a destructive method: {offenders}")

    def test_fp_expression_index_is_created_when_json1_available(self):
        try:
            with sqlite3.connect(":memory:") as c:
                c.execute("select json_extract('{\"a\":1}','$.a')")
        except sqlite3.OperationalError:
            self.skipTest("SQLite built without JSON1")
        with sqlite3.connect(self.reg.db_path) as c:
            idx = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_records_fp", idx)


class LedgerWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_ledger_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)

    def test_record_proposal_defaults_to_novel_and_pending(self):
        self.assertTrue(self.reg.record_proposal(fp="fp1"))
        row = self.reg.get_proposal("fp1")
        self.assertEqual(row["origin"], "novel")
        self.assertEqual(row["outcome"], "pending")
        self.assertEqual(row["status"], "pending")

    def test_re_emitting_same_fp_is_false_and_leaves_one_row(self):
        self.reg.record_proposal(fp="fp1", family="ZZ", shape="128x128x128")
        self.assertFalse(self.reg.record_proposal(fp="fp1", family="SS"))
        rows = self.reg.coverage_view()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.reg.coverage_view()[0]["family"], "ZZ")

    def test_empty_fp_is_refused(self):
        self.assertFalse(self.reg.record_proposal(fp=""))
        self.assertFalse(self.reg.record_proposal(fp=None))

    def test_resolve_is_monotonic_and_single_shot(self):
        self.reg.record_proposal(fp="fp1")
        self.assertTrue(self.reg.resolve_proposal("fp1", "functional"))
        self.assertFalse(self.reg.resolve_proposal("fp1", "non_functional"))
        self.assertFalse(self.reg.resolve_proposal("fp1", "legal_slow"))
        self.assertEqual(self.reg.get_proposal("fp1")["outcome"], "functional")

    def test_resolve_sets_build_class_for_rejections(self):
        self.reg.record_proposal(fp="fp1")
        self.reg.resolve_proposal("fp1", "legal_rejected", build_class="half_vw1_floor")
        self.assertEqual(self.reg.get_proposal("fp1")["build_class"], "half_vw1_floor")

    def test_resolve_refuses_pending_and_unknown_fp(self):
        self.reg.record_proposal(fp="fp1")
        self.assertFalse(self.reg.resolve_proposal("fp1", "pending"))
        self.assertFalse(self.reg.resolve_proposal("nope", "functional"))
        self.assertIsNone(self.reg.get_proposal("nope"))

    def test_rows_are_never_deleted_by_resolution(self):
        for i in range(5):
            self.reg.record_proposal(fp=f"fp{i}")
        for i in range(5):
            self.reg.resolve_proposal(f"fp{i}", "functional")
        self.assertEqual(len(self.reg.proposed_fps()), 5)
        self.assertEqual(self.reg.outcome_histogram(), {"functional": 5})


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_ledger_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)

    def test_novel_when_absent_from_both_sources(self):
        self.assertTrue(self.reg.is_novel("fp1"))

    def test_not_novel_once_in_the_ledger(self):
        self.reg.record_proposal(fp="fp1")
        self.assertFalse(self.reg.is_novel("fp1"))

    def test_not_novel_once_decided_by_the_registry(self):
        self.reg.append_record({"fp": "fp1", "status": "completed"}, run_id="r1")
        self.assertFalse(self.reg.is_novel("fp1"))

    def test_not_novel_when_recorded_only_as_started(self):
        """Novelty blocks on any registry record, including `started`.

        has_fp_passed is narrower -- it asks whether the config *passed*, and
        'started' is not in its status set. Novelty asks the different question
        "have we run this before?", which 'started' answers yes to. A run that
        was skipped or interrupted leaves exactly that row, so treating it as
        novel is how D2 rediscovery comes back.
        """
        self.reg.append_record({"fp": "fp1", "status": "started"}, run_id="r1")
        self.assertFalse(self.reg.has_fp_passed("fp1"))   # did not pass
        self.assertFalse(self.reg.is_novel("fp1"))        # but we have seen it
        self.assertIn("fp1", self.reg.decided_fps())

    def test_decided_fps_is_broader_than_has_fp_passed(self):
        """The two sets are meant to differ; assert they actually do.

        If this ever fails, novelty has silently narrowed to 'only configs that
        passed' and would re-propose every config that ran without winning.
        """
        self.reg.append_record({"fp": "passed", "status": "completed"}, run_id="r1")
        self.reg.append_record({"fp": "started", "status": "started"}, run_id="r1")
        self.reg.append_record({"fp": "failed", "status": "skipped"}, run_id="r1")
        decided = self.reg.decided_fps()
        self.assertEqual(decided, {"passed", "started", "failed"})
        self.assertEqual([fp for fp in decided if self.reg.has_fp_passed(fp)], ["passed"])

    def test_empty_fp_is_never_novel(self):
        self.assertFalse(self.reg.is_novel(""))
        self.assertFalse(self.reg.is_novel(None))

    def test_decided_fps_matches_has_fp_passed_semantics(self):
        """The SQL narrowing must not change has_fp_passed's verdict."""
        cases = [
            {"fp": "a", "status": "PASS"},
            {"fp": "b", "status": "completed"},
            {"fp": "c", "status": "success"},
            {"fp": "d", "status": "result", "result": {"status": "completed"}},
            {"fp": "e", "status": "failed"},
            {"fp": "f", "status": "skipped"},
            {"fp": "g"},  # no status at all
        ]
        for rec in cases:
            self.reg.append_record(rec, run_id="r1")
        for rec in cases:
            fp = rec["fp"]
            self.assertEqual(
                self.reg.has_fp_passed(fp),
                fp in {"a", "b", "c", "d"},
                f"has_fp_passed({fp!r}) disagrees with the documented status set",
            )


class DurabilityTests(unittest.TestCase):
    """H.3.2: the ledger holds when the registry's decided set is destroyed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_durable_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)
        self.fps = [fingerprint_config({"MacroTile": mt}) for mt in ("64x64x16", "32x32x16")]
        for fp in self.fps:
            self.reg.append_record({"fp": fp, "status": "completed"}, run_id="native")
            self.reg.record_proposal(fp=fp, family="ZZ", shape="128x128x128")
        self.reg.resolve_proposal(self.fps[0], "functional")

    def test_novelty_survives_losing_every_decided_row(self):
        self.assertEqual(len(self.reg.decided_fps()), len(self.fps))
        with sqlite3.connect(self.reg.db_path) as c:
            c.execute("DELETE FROM records WHERE json_extract(data,'$.fp') IS NOT NULL")
            c.commit()
        self.assertEqual(self.reg.decided_fps(), set())
        # The registry no longer knows these fp at all...
        self.assertFalse(self.reg.has_fp_passed(self.fps[0]))
        # ...but the ledger still blocks them. That is the whole durability claim.
        self.assertFalse(self.reg.is_novel(self.fps[0]))
        self.assertFalse(self.reg.is_novel(self.fps[1]))

    def test_resolved_outcome_survives_the_strip(self):
        with sqlite3.connect(self.reg.db_path) as c:
            c.execute("DELETE FROM records WHERE json_extract(data,'$.fp') IS NOT NULL")
            c.commit()
        self.assertEqual(self.reg.get_proposal(self.fps[0])["outcome"], "functional")
        self.assertEqual(self.reg.pending_proposals()[0]["fp"], self.fps[1])


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_cover_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)

    def test_absent_cells_are_absent_not_zero_filled(self):
        """A cell with no candidate must be missing, not a zero row.

        A sampler needs to tell 'nothing proposed here' from 'proposed and
        failed'; flattening the first into the second is how a retired subspace
        gets re-sampled forever.
        """
        self.reg.record_proposal(fp="fp1", family="ZZ", shape="128x128x128")
        self.reg.resolve_proposal("fp1", "non_functional")
        view = self.reg.coverage_view()
        self.assertEqual(len(view), 1)
        self.assertEqual(view[0]["n_proposed"], 1)
        self.assertEqual(view[0]["n_non_functional"], 1)
        self.assertEqual(view[0]["n_functional"], 0)

    def test_pending_proposals_reports_the_unresolved(self):
        self.reg.record_proposal(fp="fp1")
        self.reg.record_proposal(fp="fp2")
        self.reg.resolve_proposal("fp2", "functional")
        pending = self.reg.pending_proposals()
        self.assertEqual([p["fp"] for p in pending], ["fp1"])

    def test_counts_are_read_live_not_transcribed(self):
        """Histogram and coverage must agree with what was inserted."""
        for i in range(7):
            self.reg.record_proposal(fp=f"fp{i}", family="SS", shape="1024x1024x1024")
        for i in range(3):
            self.reg.resolve_proposal(f"fp{i}", "functional")
        hist = self.reg.outcome_histogram()
        self.assertEqual(sum(hist.values()), 7)
        self.assertEqual(hist.get("functional"), 3)
        self.assertEqual(hist.get("pending"), 4)
        row = self.reg.coverage_view()[0]
        self.assertEqual(row["n_proposed"], 7)
        self.assertEqual(row["n_functional"], 3)
        self.assertEqual(row["n_pending"], 4)


if __name__ == "__main__":
    unittest.main()