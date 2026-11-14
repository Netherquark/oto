#!/usr/bin/env python3
"""
test_legal_slow.py — `legal_slow` is measured against the gfx900 reference.

`legal_slow` is the bucket that separates "Tensile built it and it ran" from "it
ran usefully". Without it, a candidate that is legal but materially worse than
the shipped floor is indistinguishable from real progress, so the ledger learns
the wrong lesson from it — which is the §H.9 risk in one sentence.

The bar is **relative to how the reference ran**, and these tests exist mostly to
stop that from quietly degenerating into a constant:

  * an absolute GFlops threshold is wrong here by a wide margin — measured cell
    references span 4 to 857 GFlops, so one absolute number either condemns
    every small cell or none of them;
  * a bar that ignores the measurement band fires on noise, which is worse than
    not firing at all;
  * a cell the reference never ran has no bar, and must NOT be inferred slow.

The live-corpus numbers are deliberately not asserted. §H.7 forbids transcribing
corpus counts, and a test that pinned 18.288598 would break every time the corpus
grows — the same trap that produced the retracted zero-yield claim. What is pinned
is the *structure*: relative, band-subtracted, per-cell, and evidence-requiring.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oto.metrics.cell_coverage as coverage
from oto.ledger.mutator import (
    OUTCOME_FUNCTIONAL,
    OUTCOME_LEGAL_SLOW,
    Mutator,
    classify_outcome,
)
from oto.ledger.registry import SQLiteRegistry
from oto.metrics.benchmark_analytics import AnalyticsEngine

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


def row(gflops, size=128, winner_freq=1, kernel=100.0):
    return [gflops, size, size, 1, size, size, size, size, size,
            winner_freq, 4194304, 0, kernel, kernel]


def bar(value, reference):
    return {"bar_gflops": value, "reference_median": reference,
            "n_kernels": 7, "band_pct": 18.29}


class ReferenceThresholdTests(unittest.TestCase):
    """`coverage.reference_thresholds` — one scan, two answers."""

    def setUp(self):
        self._cache = dict(coverage._REFERENCE_CACHE)
        self._building = coverage._REFERENCE_BUILDING
        coverage._REFERENCE_CACHE.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        coverage._REFERENCE_CACHE.clear()
        coverage._REFERENCE_CACHE.update(self._cache)
        coverage._REFERENCE_BUILDING = self._building

    def test_an_unmeasurable_reference_yields_no_band_and_no_bars(self):
        import oto.metrics.ab_audit as ab_audit
        with mock.patch.object(ab_audit, "arm_record_sets",
                               side_effect=RuntimeError("no runs")):
            got = coverage.reference_thresholds(REPO)
        assert got["band_pct"] is None
        assert got["bars"] == {}
        assert not got["available"]

    def test_the_band_is_read_not_invented(self):
        # An empty corpus still yields the shipped floor, and says so; it never
        # yields a number with no provenance.
        import oto.metrics.ab_audit as ab_audit
        with mock.patch.object(ab_audit, "arm_record_sets",
                               return_value=([], [], [])):
            got = coverage.reference_thresholds(REPO)
        assert got["band_source"] == "shipped-floor"
        assert got["band_pct"] > 0

    def test_a_bar_is_the_reference_less_the_band(self):
        import oto.metrics.ab_audit as ab_audit
        deltas = {("S", "256x256x256", "SS"): {"spoof_median": 100.0,
                                               "n_spoof_kernels": 5}}
        with mock.patch.object(ab_audit, "arm_record_sets",
                               return_value=([], [], ["r1"])), \
             mock.patch.object(ab_audit, "cell_deltas", return_value=deltas):
            got = coverage.reference_thresholds(REPO)
        cell = ("S", "256x256x256")
        band = got["band_pct"] / 100.0
        self.assertAlmostEqual(got["bars"][cell]["bar_gflops"],
                               100.0 * (1 - band), places=6)

    def test_a_zero_reference_gets_no_bar(self):
        import oto.metrics.ab_audit as ab_audit
        deltas = {("S", "256x256x256", "SS"): {"spoof_median": 0.0,
                                               "n_spoof_kernels": 0}}
        with mock.patch.object(ab_audit, "arm_record_sets",
                               return_value=([], [], [])), \
             mock.patch.object(ab_audit, "cell_deltas", return_value=deltas):
            got = coverage.reference_thresholds(REPO)
        assert got["bars"] == {}

    def test_the_scan_is_cached_not_repeated(self):
        import oto.metrics.ab_audit as ab_audit
        calls = []
        with mock.patch.object(ab_audit, "arm_record_sets",
                               side_effect=lambda *a, **k: calls.append(1) or
                               ([], [], [])), \
             mock.patch.object(ab_audit, "cell_deltas", return_value={}):
            coverage.reference_thresholds(REPO)
            coverage.reference_thresholds(REPO)
            coverage.reference_thresholds(REPO)
        assert len(calls) == 1

    def test_an_explicit_band_is_cached_separately(self):
        # Otherwise a caller's override would be handed to the next default
        # lookup, and two callers would grade against two different bands.
        import oto.metrics.ab_audit as ab_audit
        calls = []
        with mock.patch.object(ab_audit, "arm_record_sets",
                               side_effect=lambda *a, **k: calls.append(1) or
                               ([], [], [])), \
             mock.patch.object(ab_audit, "cell_deltas", return_value={}):
            coverage.reference_thresholds(REPO, band_pct=1.0)
            coverage.reference_thresholds(REPO, band_pct=2.0)
            coverage.reference_thresholds(REPO, band_pct=1.0)
        assert len(calls) == 2

    def test_reentry_returns_empty_rather_than_recursing(self):
        # `arm_record_sets` builds a driver, which builds a Mutator. Asking for
        # thresholds from inside that construction must not start the cycle.
        coverage._REFERENCE_BUILDING = True
        try:
            got = coverage.reference_thresholds(REPO)
        finally:
            coverage._REFERENCE_BUILDING = False
        assert not got["available"]
        assert got["bars"] == {}

    def test_slow_bar_lookup_is_case_insensitive_and_safe(self):
        import oto.metrics.ab_audit as ab_audit
        deltas = {("S", "256x256x256", "SS"): {"spoof_median": 100.0,
                                               "n_spoof_kernels": 5}}
        with mock.patch.object(ab_audit, "arm_record_sets",
                               return_value=([], [], [])), \
             mock.patch.object(ab_audit, "cell_deltas", return_value=deltas):
            assert coverage.slow_bar(("s", "256x256x256"), REPO) is not None
            assert coverage.slow_bar(("Q", "1x1x1"), REPO) is None
            assert coverage.slow_bar(None, REPO) is None

    def test_a_malformed_cell_key_does_not_raise(self):
        # A bar lookup is on the per-phase path; it must not be able to crash a
        # classification run over a corpus we do not control.
        assert coverage.slow_bar(("S",), REPO) is None
        assert coverage.slow_bar("not-a-tuple", REPO) is None


class LegalSlowVerdictTests(unittest.TestCase):
    """The verdict itself, against synthetic bars with known geometry."""

    CELL = ("S", "256x256x256")
    OTHER = ("S", "512x512x512")
    BARS = {CELL: bar(80.0, 100.0), OTHER: bar(400.0, 500.0)}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_slow_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.eng = AnalyticsEngine(None, self.tmp)
        # The dtype lives in the phase id, not the CSV, exactly as the report
        # resolves it. A `phase_ss_` prefix is what `extract_dtype_from_phase_id`
        # parses, so the cell key matches the reference bars.
        self.phase = self.tmp / "phase_ss_a_256x256x256"

    def _classify(self, **kw):
        return classify_outcome(self.phase, self.eng, slow_bars=self.BARS, **kw)

    def test_a_candidate_below_the_bar_is_legal_slow(self):
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=10.0)])
        outcome, detail = self._classify()
        assert outcome == OUTCOME_LEGAL_SLOW
        assert detail["slow_bars_applied"] == 1

    def test_a_candidate_above_the_bar_is_functional(self):
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=95.0)])
        outcome, _ = self._classify()
        assert outcome == OUTCOME_FUNCTIONAL

    def test_the_boundary_is_the_bar_not_the_reference(self):
        # 100 is the reference median and must pass: the bar already subtracted
        # the band, so a tie with the reference is not slowness.
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=100.0)])
        outcome, _ = self._classify()
        assert outcome == OUTCOME_FUNCTIONAL

    def test_a_cell_the_reference_never_ran_is_not_slow(self):
        # Absence of evidence is not evidence of slowness.
        self.phase = self.tmp / "phase_ss_a_999x999x999"
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=999, kernel=1.0)])
        outcome, detail = self._classify()
        assert outcome == OUTCOME_FUNCTIONAL
        assert detail["slow_bars_applied"] == 0
        assert detail["slow_unmatched_cells"] == 1

    def test_no_bars_means_no_slow_verdict(self):
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=1.0)])
        outcome, _ = classify_outcome(self.phase, self.eng)
        assert outcome == OUTCOME_FUNCTIONAL

    def test_one_competitive_shape_rescues_a_sweep(self):
        # A multi-shape candidate is useful if ANY shape is competitive, so a
        # slow shape must not condemn the batch.
        self.phase = self.tmp / "phase_ss_a_256x256x256"
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=10.0),
                   row(1, size=512, kernel=450.0)])
        outcome, detail = self._classify()
        assert outcome == OUTCOME_FUNCTIONAL
        assert detail["slow_bars_applied"] == 2

    def test_a_sweep_that_is_slow_everywhere_is_legal_slow(self):
        self.phase = self.tmp / "phase_ss_a_256x256x256"
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=10.0),
                   row(1, size=512, kernel=50.0)])
        outcome, _ = self._classify()
        assert outcome == OUTCOME_LEGAL_SLOW

    def test_a_zero_result_is_non_functional_not_slow(self):
        # Order matters: "no throughput" is a different failure from "throughput
        # below the bar", and the former must not be reported as the latter.
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=0.0)])
        outcome, _ = self._classify()
        assert outcome == "non_functional"

    def test_the_absolute_bar_still_works(self):
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=5.0)])
        outcome, _ = classify_outcome(self.phase, self.eng, slow_threshold=50.0)
        assert outcome == OUTCOME_LEGAL_SLOW

    def test_the_dtype_is_resolved_from_the_phase_id(self):
        # Without this every key is (dtype='Unknown', shape), no bar matches, and
        # `legal_slow` silently never fires in production. The failure mode is
        # silence, so it needs an explicit test.
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=10.0)])
        _, detail = self._classify()
        assert detail["slow_bars_applied"] == 1

    def test_the_reference_is_recorded_for_the_report(self):
        write_csv(self.phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=10.0)])
        _, detail = self._classify()
        assert detail["slow_reference_median"] == 100.0

    def test_an_unreadable_phase_does_not_raise(self):
        self.phase.mkdir(parents=True, exist_ok=True)
        outcome, _ = self._classify()
        assert outcome == "legal_rejected"


class MutatorSlowBarTests(unittest.TestCase):
    """The Mutator resolves bars once, and refuses to re-enter."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_slowm_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = SQLiteRegistry(self.tmp)

    def test_bars_are_empty_when_the_reference_is_opted_out(self):
        mut = Mutator(self.reg, self.tmp, reference_slow=False)
        assert mut.slow_bars() == {}

    def test_opting_out_never_touches_the_corpus(self):
        mut = Mutator(self.reg, self.tmp, reference_slow=False)
        with mock.patch.object(coverage, "reference_thresholds",
                               side_effect=AssertionError("must not be called")):
            assert mut.slow_bars() == {}

    def test_construction_does_not_resolve_the_reference(self):
        # `arm_record_sets` builds a driver, which builds a Mutator; a lookup in
        # `__init__` would both cost ~90s per agent and re-enter that path.
        with mock.patch.object(coverage, "reference_thresholds",
                               side_effect=AssertionError("eager")) as m:
            Mutator(self.reg, self.tmp, reference_slow=True)
            assert m.call_count == 0

    def test_the_reference_is_resolved_once(self):
        mut = Mutator(self.reg, self.tmp, reference_slow=True)
        payload = {"bars": {("S", "1x1x1"): bar(1.0, 2.0)}, "band_pct": 5.0}
        with mock.patch.object(coverage, "reference_thresholds",
                               return_value=payload) as m:
            mut.slow_bars()
            mut.slow_bars()
            mut.slow_bars()
        assert m.call_count == 1

    def test_a_failing_reference_is_remembered_not_retried(self):
        mut = Mutator(self.reg, self.tmp, reference_slow=True)
        with mock.patch.object(coverage, "reference_thresholds",
                               side_effect=RuntimeError("boom")) as m:
            assert mut.slow_bars() == {}
            assert mut.slow_bars() == {}
        assert m.call_count == 1

    def test_the_threshold_lookup_is_case_insensitive(self):
        mut = Mutator(self.reg, self.tmp, reference_slow=False)
        mut._slow_bars = {("S", "1x1x1"): bar(50.0, 100.0)}
        assert mut.slow_threshold_for(("s", "1x1x1")) == 50.0
        assert mut.slow_threshold_for(("Q", "1x1x1")) is None
        assert mut.slow_threshold_for(None) is None

    def test_resolving_a_phase_applies_the_bars(self):
        phase = self.tmp / "phase_ss_a_256x256x256"
        write_csv(phase / "2_BenchmarkData" / "Cijk_a_00.csv",
                  [row(0, size=256, kernel=1.0)])
        mut = Mutator(self.reg, self.tmp, reference_slow=True)
        mut._slow_bars = {("S", "256x256x256"): bar(80.0, 100.0)}
        mut.emit(__import__("oto.ledger.mutator",
                                 fromlist=["Proposal"]).Proposal(fp="fp1", family="SS",
                                               shape="256x256x256"))
        outcome, _ = mut.resolve_phase_dir("fp1", phase)
        assert outcome == OUTCOME_LEGAL_SLOW


if __name__ == "__main__":
    unittest.main()
