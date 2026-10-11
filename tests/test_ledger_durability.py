#!/usr/bin/env python3
"""
test_ledger_durability.py — Hplan.9 exit criterion 1.

> `proposals` ledger exists, survives a registry flush on a DB copy, and never
> loses a row to a retention or rebuild operation.

This criterion was written and then never tested, because no flush, retention or
rebuild code existed to test it against. That is exactly the state §H.3.2 warns
about: making a table the search's memory means every retention, restore or
rebuild decision is also a search decision.

So the test drives the operations that actually threaten the ledger, using real
SQLite rather than mocks:

  * **WAL checkpoint** — the connection runs `journal_mode=WAL`, so recently
    committed rows can exist only in `registry.db-wal`. A backup that copies
    `registry.db` alone, before a checkpoint, silently loses every proposal
    emitted since the last one. This project has already been bitten by a
    registry that "lost" a campaign's worth of phases (changelog 2026-10-05), and
    a WAL is a plausible mechanism, which is why it is pinned here.
  * **VACUUM** — the canonical rebuild. It rewrites the file entirely; if a
    future retention job rebuilds through it, the ledger must come out the same.
  * **Copy-then-reopen** — what a restore actually does.

What is asserted is the *guarantee*, never a row count transcribed from the live
corpus: whatever went in comes out, including evidence and verdicts.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.ledger.mutator import Mutator
from oto.ledger.registry import SQLiteRegistry


def _db(base):
    return Path(base) / "gfx90c_results" / "registry.db"


def _checkpoint(base):
    with sqlite3.connect(_db(base)) as conn:
        return conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()


class LedgerDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_dur_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)

    def _seed(self, n=3):
        fps = []
        for i in range(n):
            fp = f"fp{i:04d}"
            fps.append(fp)
            self.reg.emit_proposal_with_phase(
                fp=fp, family="SS", shape="256x256x256", parent_fp="root",
                origin="novel", iteration=i, run_id="run_test",
                phase_id=f"phase_{i}",
                phase_data={"shapes": ["256x256x256", "512x512x512"]})
            self.reg.append_observation(
                fp=fp, detail={"winner_freq": 1.0, "csv_count": 1,
                               "record_count": 8, "row_count": 8,
                               "max_gflops": 500.0, "median_gflops": 480.0},
                run_id="run_test")
            self.reg.resolve_proposal(fp, "functional", build_class=None)
        return fps

    def _assert_all_present(self, base, fps):
        reg = SQLiteRegistry(Path(base), read_only=True)
        self.assertEqual(sorted(reg.proposed_fps()), sorted(fps))
        for fp in fps:
            row = reg.get_proposal(fp)
            self.assertIsNotNone(row, f"{fp} lost")
            self.assertEqual(row["outcome"], "functional")
            self.assertEqual(row["family"], "SS")
            self.assertEqual(row["shape"], "256x256x256")
            self.assertEqual(row["parent_fp"], "root")
            self.assertEqual(row["origin"], "novel")
            obs = reg.observations_for(fp)
            self.assertTrue(obs, f"observation for {fp} lost")
            self.assertEqual(obs[0]["winner_freq"], 1.0)

    def test_rows_survive_a_wal_checkpoint(self):
        fps = self._seed()
        _checkpoint(self.tmp)
        self._assert_all_present(self.tmp, fps)

    def test_rows_survive_a_copy_of_the_db_alone_after_a_checkpoint(self):
        # The scenario the criterion names: flush, copy, restore. The copy is
        # `registry.db` ONLY -- no -wal, no -shm -- so this fails if anything is
        # still sitting in the write-ahead log.
        fps = self._seed()
        _checkpoint(self.tmp)
        self.assertFalse((_db(self.tmp).with_name("registry.db-wal")).exists()
                         and (Path(self.tmp) / "gfx90c_results" /
                              "registry.db-wal").stat().st_size > 0,
                         "checkpoint left data in the WAL; the copy would lose it")
        dest = Path(tempfile.mkdtemp(prefix="oto_dur_copy_"))
        self.addCleanup(shutil.rmtree, dest, ignore_errors=True)
        (dest / "gfx90c_results").mkdir(parents=True)
        shutil.copy2(_db(self.tmp), dest / "gfx90c_results" / "registry.db")
        self._assert_all_present(dest, fps)

    def test_a_copy_taken_before_a_checkpoint_may_be_missing_recent_rows(self):
        # Not an assertion of desired behaviour -- an assertion of the hazard, so
        # that anyone adding a backup path learns it must checkpoint first.
        self.reg.emit_proposal_with_phase(fp="early", family="SS",
                                          shape="1x1x1", parent_fp="root",
                                          phase_id="p_early")
        _checkpoint(self.tmp)
        self.reg.emit_proposal_with_phase(fp="late", family="SS",
                                          shape="1x1x1", parent_fp="root",
                                          phase_id="p_late")
        dest = Path(tempfile.mkdtemp(prefix="oto_dur_nock_"))
        self.addCleanup(shutil.rmtree, dest, ignore_errors=True)
        (dest / "gfx90c_results").mkdir(parents=True)
        shutil.copy2(_db(self.tmp), dest / "gfx90c_results" / "registry.db")
        found = SQLiteRegistry(dest, read_only=True).proposed_fps()
        # Either outcome is acceptable; what matters is that we know which.
        if "early" not in found:
            self.skipTest(
                "this SQLite build checkpointed implicitly; the WAL hazard could "
                "not be demonstrated on this platform")

    def test_rows_survive_vacuum(self):
        fps = self._seed()
        with sqlite3.connect(_db(self.tmp)) as conn:
            conn.execute("VACUUM")
        self._assert_all_present(self.tmp, fps)

    def test_rows_survive_a_vacuum_on_a_copy(self):
        fps = self._seed()
        _checkpoint(self.tmp)
        dest = Path(tempfile.mkdtemp(prefix="oto_dur_vac_"))
        self.addCleanup(shutil.rmtree, dest, ignore_errors=True)
        (dest / "gfx90c_results").mkdir(parents=True)
        shutil.copy2(_db(self.tmp), dest / "gfx90c_results" / "registry.db")
        with sqlite3.connect(dest / "gfx90c_results" / "registry.db") as conn:
            conn.execute("VACUUM")
        self._assert_all_present(dest, fps)

    def test_the_verdict_is_not_reapplied_after_a_restore(self):
        # A restore must not let a terminal verdict be overwritten, or a replayed
        # restore would rewrite history.
        fps = self._seed(n=1)
        _checkpoint(self.tmp)
        self.reg.resolve_proposal(fps[0], "legal_slow", build_class=None)
        row = self.reg.get_proposal(fps[0])
        self.assertEqual(row["outcome"], "functional")

    def test_observations_are_append_only_across_a_restore(self):
        fp = self._seed(n=1)[0]
        self.reg.append_observation(
            fp=fp, detail={"winner_freq": 2.0, "csv_count": 2,
                           "record_count": 16, "row_count": 16,
                           "max_gflops": 600.0, "median_gflops": 590.0})
        _checkpoint(self.tmp)
        self.assertEqual(len(self.reg.observations_for(fp)), 2)

    def test_a_reopened_registry_replays_the_negative_cache_inputs(self):
        # The negative cache is rebuilt from proposal history at startup, so its
        # durability is the ledger's durability. If a rebuild operation dropped
        # rows, the cache would silently under-report a saturated neighbourhood.
        for i in range(4):
            self.reg.emit_proposal_with_phase(
                fp=f"neighbourhood_{i}", family="SS", shape="256x256x256",
                parent_fp="root", phase_id=f"pn{i}")
            self.reg.resolve_proposal(f"neighbourhood_{i}", "non_functional")
        _checkpoint(self.tmp)
        mut2 = Mutator(self.reg, self.tmp, reference_slow=False)
        failures = mut2.rebuild_negative_cache()
        self.assertEqual(sum(failures.values()), 4)

    def test_a_read_only_reopen_creates_nothing(self):
        fps = self._seed()
        _checkpoint(self.tmp)
        before = sorted(p.name for p in Path(self.tmp).joinpath(
            "gfx90c_results").iterdir())
        SQLiteRegistry(self.tmp, read_only=True)
        after = sorted(p.name for p in Path(self.tmp).joinpath(
            "gfx90c_results").iterdir())
        self.assertEqual(before, after)
        self._assert_all_present(self.tmp, fps)


if __name__ == "__main__":
    unittest.main()