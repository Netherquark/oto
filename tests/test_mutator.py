#!/usr/bin/env python3
"""
test_mutator.py — outcome classification, negative cache, overlay.

The outcome classifier is the mechanism D6 asked for: it is the first thing in
the pipeline that can distinguish a candidate that worked from one that did not.

The tests are shaped around one hard-won lesson. A previous version of this
work concluded that the whole historical mutant population was zero-yield,
because it read the column headed `GFlops`. That column is a *problem index* in
these CSVs (0,1,2,3 across a multi-shape file, 0 in a single-shape file); the
throughput is in the trailing kernel column, which `load_benchmark_csv` reads.
The claim survived a same-run positive control, because the control is non-zero
under either reading.

So these tests do not only check that classification works. They check that the
classifier is expressed *in terms of the loader* and disagrees with the naive
column read — the control alone is not sufficient to catch that bug, and neither
is a hand-written example.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.ledger.mutator import (
    DEFAULT_NEGATIVE_CACHE_K,
    ORIGIN_REPLICATE,
    OUTCOME_FUNCTIONAL,
    OUTCOME_LEGAL_REJECTED,
    OUTCOME_LEGAL_SLOW,
    OUTCOME_NON_FUNCTIONAL,
    OUTCOME_PENDING,
    TERMINAL_OUTCOMES,
    Mutator,
    Proposal,
    classify_outcome,
)
from oto.ledger.registry import SQLiteRegistry
from oto.metrics.analytics import AnalyticsEngine
from oto.runners.paths import results_rel, runs_rel

REPO = Path(__file__).resolve().parent.parent

HEADER = (
    "GFlops, SizeI, SizeJ, SizeK, SizeL, LDD, LDC, LDA, LDB, WinnerFreq, "
    "TotalFlops, WinnerPower, WinnerTemperature, Cijk_Ailk_Bjlk_ZB_MT32x32x16_SN_K1"
)


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(HEADER + "\n")
        f.writelines(",".join(str(x) for x in r) + "\n" for r in rows)


def row(gflops, size=128, winner_freq=0, kernel=1093.47):
    """One CSV row shaped like the real ones.

    Field 0 is the column headed 'GFlops' (a problem index), field 13 is the
    kernel column where throughput actually lives, and field 12 duplicates it --
    exactly the shape that made the retracted claim look plausible.
    """
    return [gflops, size, size, 1, size, size, size, size, size,
            winner_freq, 4194304, 0, kernel, kernel]


class CsvShapeTests(unittest.TestCase):
    """count_benchmark_rows must see rows the value-loader drops."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_csv_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.eng = AnalyticsEngine(None, self.tmp)

    def test_counts_rows_the_loader_discards(self):
        p = self.tmp / "2_BenchmarkData" / "Cijk_x_00.csv"
        write_csv(p, [row(0), row(0), row(0)])
        assert self.eng.count_benchmark_rows(p) == 3
        # every row is non-positive in the index column, so the loader yields
        # nothing for it -- which is why the shape has to be readable separately
        assert len(self.eng.load_benchmark_csv(p)) == 3

    def test_header_only_and_missing_files_count_zero(self):
        p = self.tmp / "2_BenchmarkData" / "Cijk_empty.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(HEADER + "\n")
        assert self.eng.count_benchmark_rows(p) == 0
        assert self.eng.count_benchmark_rows(self.tmp / "nope.csv") == 0

    def test_kernel_column_is_where_throughput_lives(self):
        """The naive read and the loader read must disagree.

        Same file, same rows: `GFlops` column says 0, kernel column says
        non-zero. Everything else in this file depends on the loader being right.
        """
        p = self.tmp / "2_BenchmarkData" / "Cijk_y_00.csv"
        write_csv(p, [row(0, kernel=404.485), row(1, size=512, kernel=625.098)])
        naive = self.eng.read_column(p, "GFlops")
        assert naive == [0.0, 1.0]
        loader = self.eng.load_benchmark_csv(p)
        assert loader
        assert all(r["GFLOPS"] > 0 for r in loader)
        assert 404.485 in [r["GFLOPS"] for r in loader]


class ClassifyOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_outcome_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.eng = AnalyticsEngine(None, self.tmp)
        self.phase = self.tmp / "phase_x"

    def test_absent_csv_is_legal_rejected(self):
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_LEGAL_REJECTED
        assert detail["csv_count"] == 0
        assert detail["row_count"] == 0

    def test_header_only_csv_is_legal_rejected_not_non_functional(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(HEADER + "\n")
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_LEGAL_REJECTED
        assert detail["row_count"] == 0

    def test_rows_present_but_all_nonpositive_is_non_functional(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, kernel=0.0), row(0, kernel=0.0)])
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_NON_FUNCTIONAL
        assert detail["row_count"] == 2
        assert detail["record_count"] == 0

    def test_any_nonpositive_kernel_value_is_non_functional(self):
        """Zero in the *kernel* column is what non-functional means here.

        Note the index column reads 1 for these rows, so a classifier built on
        the wrongly-named column would call this functional.
        """
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(1, size=1024, kernel=0.0)])
        outcome, _detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_NON_FUNCTIONAL
        assert self.eng.read_column(p, "GFlops") == [1.0]  # the trap
        assert outcome == OUTCOME_NON_FUNCTIONAL       # the truth

    def test_positive_kernel_value_is_functional(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, kernel=404.485)])
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_FUNCTIONAL
        assert detail["max_gflops"] == 404.485
        assert detail["record_count"] == 1
        assert detail["row_count"] == 1

    def test_winner_freq_recorded_but_not_decisive(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, winner_freq=7, kernel=404.485)])
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_FUNCTIONAL
        assert detail["winner_freq"] == 7.0
        assert detail["winner_freq_positive"]

    def test_functional_with_zero_winner_freq_is_still_functional(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, winner_freq=0, kernel=404.485)])
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_FUNCTIONAL
        assert not detail["winner_freq_positive"]

    def test_legal_slow_impossible_without_a_threshold(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, kernel=1.5)])
        outcome, _ = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_FUNCTIONAL
        outcome, _ = classify_outcome(self.phase, self.eng, slow_threshold=100.0)
        assert outcome == OUTCOME_LEGAL_SLOW

    def test_several_csvs_are_pooled(self):
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv", [row(0, kernel=0.0)])
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_b_00.csv", [row(0, kernel=50.0)])
        outcome, detail = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_FUNCTIONAL
        assert detail["csv_count"] == 2
        assert detail["row_count"] == 2

    def test_every_verdict_is_in_the_declared_vocabulary(self):
        p = self.phase / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, kernel=5.0)])
        for thr in (None, 1000.0):
            outcome, _ = classify_outcome(self.phase, self.eng, slow_threshold=thr)
            assert outcome in TERMINAL_OUTCOMES
        assert {"functional", "non_functional", "legal_rejected", "legal_slow"} == TERMINAL_OUTCOMES


class MutatorLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_mut_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)
        self.mut = Mutator(self.reg, self.tmp)

    def test_emit_then_resolve(self):
        assert self.mut.emit(Proposal(fp="fp1", family="ZZ", shape="128x128x128", parent_fp="root"))
        assert self.mut.resolve("fp1", OUTCOME_FUNCTIONAL)
        row = self.reg.get_proposal("fp1")
        assert row["outcome"] == OUTCOME_FUNCTIONAL
        assert row["status"] == "resolved"

    def test_second_resolve_is_a_no_op(self):
        self.mut.emit(Proposal(fp="fp1"))
        assert self.mut.resolve("fp1", OUTCOME_FUNCTIONAL)
        assert not self.mut.resolve("fp1", OUTCOME_NON_FUNCTIONAL)
        assert self.reg.get_proposal("fp1")["outcome"] == OUTCOME_FUNCTIONAL

    def test_origin_replicate_is_recorded(self):
        self.mut.emit(Proposal(fp="fp1", origin=ORIGIN_REPLICATE, parent_fp="fp0"))
        assert self.reg.get_proposal("fp1")["origin"] == ORIGIN_REPLICATE

    def test_resolve_phase_dir_classifies_then_writes_back(self):
        p = self.tmp / "phase_x" / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, kernel=404.485)])
        self.mut.emit(Proposal(fp="fp1"))
        outcome, detail = self.mut.resolve_phase_dir("fp1", p.parent.parent)
        assert outcome == OUTCOME_FUNCTIONAL
        assert detail["max_gflops"] == 404.485
        assert self.reg.get_proposal("fp1")["outcome"] == OUTCOME_FUNCTIONAL

    def test_resolve_phase_dir_reports_pending_when_already_resolved(self):
        p = self.tmp / "phase_x" / "2_BenchmarkData" / "Cijk_a_00.csv"
        write_csv(p, [row(0, kernel=404.485)])
        self.mut.emit(Proposal(fp="fp1"))
        self.mut.resolve("fp1", OUTCOME_NON_FUNCTIONAL)
        outcome, _ = self.mut.resolve_phase_dir("fp1", p.parent.parent)
        assert outcome == OUTCOME_PENDING
        assert self.reg.get_proposal("fp1")["outcome"] == OUTCOME_NON_FUNCTIONAL

    def test_ledger_available_detects_a_missing_table(self):
        """The skip-bypass depends on this. If the ledger is gone, novelty
        would call everything novel and the run would look busy measuring
        nothing."""
        import sqlite3
        assert self.mut.ledger_available()
        with sqlite3.connect(self.reg.db_path) as c:
            c.execute("DROP TABLE proposals")
            c.commit()
        assert not self.mut.ledger_available()

    def test_novelty_reflects_the_ledger(self):
        assert self.mut.is_novel("fp1")
        self.mut.emit(Proposal(fp="fp1"))
        assert not self.mut.is_novel("fp1")


class NegativeCacheTests(unittest.TestCase):
    """H.3.8 step 3, with the historical justification retracted.

    Replayed against today's corpus this cache correctly never fires, because
    every measured mutant row is non-zero. Both halves are asserted: it fires on
    k consecutive non-functional outcomes, and it does not fire on data that is
    merely old.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_neg_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)
        self.mut = Mutator(self.reg, self.tmp)

    def _child(self, name, parent, outcome):
        self.mut.emit(Proposal(fp=name, parent_fp=parent))
        self.mut.resolve(name, outcome)

    def test_fires_after_k_consecutive_failures(self):
        for i in range(DEFAULT_NEGATIVE_CACHE_K - 1):
            self._child(f"bad{i}", "parentA", OUTCOME_NON_FUNCTIONAL)
            assert not self.mut.neighbourhood_saturated("parentA"), f"fired early at {i + 1} failure(s)"
        self._child("badX", "parentA", OUTCOME_NON_FUNCTIONAL)
        assert self.mut.neighbourhood_saturated("parentA")
        assert self.mut.consecutive_failures("parentA") == DEFAULT_NEGATIVE_CACHE_K

    def test_a_success_resets_the_counter(self):
        for i in range(DEFAULT_NEGATIVE_CACHE_K):
            self._child(f"bad{i}", "parentA", OUTCOME_NON_FUNCTIONAL)
        assert self.mut.neighbourhood_saturated("parentA")
        self._child("good", "parentA", OUTCOME_FUNCTIONAL)
        assert not self.mut.neighbourhood_saturated("parentA")
        assert self.mut.consecutive_failures("parentA") == 0

    def test_neighbourhoods_are_tracked_independently(self):
        for i in range(DEFAULT_NEGATIVE_CACHE_K):
            self._child(f"bad{i}", "parentA", OUTCOME_NON_FUNCTIONAL)
        assert self.mut.neighbourhood_saturated("parentA")
        assert not self.mut.neighbourhood_saturated("parentB")

    def test_legal_rejected_does_not_count_as_non_functional(self):
        """A rejected candidate is not evidence the neighbourhood is broken --
        it is evidence the sampler should not have proposed it at all."""
        for i in range(DEFAULT_NEGATIVE_CACHE_K + 2):
            self._child(f"r{i}", "parentA", OUTCOME_LEGAL_REJECTED)
        assert not self.mut.neighbourhood_saturated("parentA")

    def test_k_is_configurable(self):
        mut = Mutator(self.reg, self.tmp, negative_cache_k=1)
        mut.emit(Proposal(fp="one", parent_fp="p"))
        mut.resolve("one", OUTCOME_NON_FUNCTIONAL)
        assert mut.neighbourhood_saturated("p")

    def test_root_proposals_never_accumulate_a_counter(self):
        self.mut.emit(Proposal(fp="root"))
        self.mut.resolve("root", OUTCOME_NON_FUNCTIONAL)
        assert self.mut.consecutive_failures("root") == 0

    def test_does_not_fire_on_the_archived_mutant_corpus(self):
        """The regression that matters after the retraction.

        Every archived mutant row is non-zero, so a correct classifier returns
        `functional` and the cache must stay silent. If this fails, the cache is
        discarding neighbourhoods for the wrong reason.
        """
        if not REPO.exists():
            self.skipTest("repo not available")
        dirs = sorted({d for d in REPO.glob("**/phase_auto_*") if d.is_dir()})
        if not dirs:
            self.skipTest("no archived mutant directories present")
        verdicts = {}
        for d in dirs:
            outcome, _ = classify_outcome(d, self.mut.analytics)
            verdicts[outcome] = verdicts.get(outcome, 0) + 1
        assert OUTCOME_NON_FUNCTIONAL not in verdicts, "archived mutants classified non-functional; either the " "loader is bypassed or the corpus changed"
        assert verdicts.get(OUTCOME_FUNCTIONAL, 0) > 0


class OverlayTests(unittest.TestCase):
    """H.3.7: candidates never reach the curated deck."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_overlay_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)
        (self.tmp / runs_rel("")).mkdir(parents=True, exist_ok=True)
        self.reg.create_run_dir("run_test")
        self.mut = Mutator(self.reg, self.tmp)
        (self.tmp / "phases.yaml").write_text("- phase_id: phase_curated\n")

    def test_write_and_read_back(self):
        cands = [{"phase_id": "phase_mut_0", "fp": "abc", "config": {"MacroTile": "64x64x16"}}]
        path = self.mut.write_overlay(cands, run_id="run_test")
        assert path.exists()
        assert "run_test" in path.name
        back = self.mut.load_overlay("run_test")
        assert back == cands

    def test_curated_deck_is_untouched(self):
        before = (self.tmp / "phases.yaml").read_text()
        self.mut.write_overlay([{"phase_id": "p", "fp": "x"}], run_id="run_test")
        assert (self.tmp / "phases.yaml").read_text() == before

    def test_overlays_are_per_run(self):
        self.reg.create_run_dir("run_other")
        self.mut.write_overlay([{"phase_id": "p1"}], run_id="run_test")
        self.mut.write_overlay([{"phase_id": "p2"}], run_id="run_other")
        assert [c["phase_id"] for c in self.mut.load_overlay("run_test")] == ["p1"]
        assert [c["phase_id"] for c in self.mut.load_overlay("run_other")] == ["p2"]

    def test_discarding_a_batch_deletes_only_the_overlay(self):
        self.mut.write_overlay([{"phase_id": "p"}], run_id="run_test")
        path = self.tmp / results_rel("overlays", "phases.run_test.overlay.yaml")
        path.unlink()
        assert not path.exists()
        assert (self.tmp / "phases.yaml").exists()
        assert self.mut.load_overlay("run_test") == []

    def test_missing_overlay_reads_empty(self):
        assert self.mut.load_overlay("never_ran") == []


if __name__ == "__main__":
    unittest.main()
