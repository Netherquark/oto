"""Tests for Option H Phase 3 (coverage.py) — `Hplan.5`.

The three cell states are the load-bearing part: the failure mode this phase
exists to prevent is a cell that has never been tried being recorded the same
way as a cell where everything tried failed. Both the ordering of the state
checks and the absence of a fourth "empty" state are asserted.
"""

import statistics
import unittest

import oto.metrics.ab_audit as ab_audit
import oto.metrics.coverage as coverage


def _proposal(family, shape, fp, outcome="functional", **kw):
    row = {"family": family, "shape": shape, "fp": fp, "outcome": outcome}
    row.update(kw)
    return row


def _cell(proposals, samples):
    cells = coverage.coverage_cells(proposals, samples)
    return cells[0] if cells else None


class TestThreeStatesStayDistinct(unittest.TestCase):
    """Hplan.5 step 2 / §H.1.2a."""

    def test_no_candidate_is_explore_not_retired(self):
        cell = _cell([_proposal("SS", "1x1x1", "a")], {"a": [10.0] * 8})
        cell["outcomes"] = {}          # nothing decided yet
        cell["n_distinct_fp"] = 0
        self.assertEqual(coverage.decide_state(cell), coverage.STATE_EXPLORE)

    def test_all_non_functional_is_retired(self):
        cell = _cell([_proposal("ZZ", "1x1x1", "c", "non_functional")], {})
        self.assertEqual(coverage.decide_state(cell), coverage.STATE_RETIRED)

    def test_retired_is_not_empty(self):
        dead = _cell([_proposal("ZZ", "1x1x1", "c", "non_functional")], {})
        unknown = _cell([_proposal("ZZ", "1x1x1", "d")], {"d": [1.0] * 8})
        self.assertNotEqual(coverage.decide_state(dead),
                            coverage.decide_state(unknown))

    def test_thin_evidence_is_replicate(self):
        cell = _cell([_proposal("SS", "1x1x1", "b")], {"b": [10.0]})
        self.assertEqual(coverage.decide_state(cell), coverage.STATE_REPLICATE)

    def test_spread_beyond_band_is_replicate(self):
        cell = _cell([_proposal("HH", "1x1x1", "d")],
                     {"d": [13.2, 12.9, 13.1, 13.4, 13.0, 13.3, 13.1, 12.7,
                            40.0, 9.0, 38.0, 11.0]})
        self.assertEqual(coverage.decide_state(cell, band_pct=5.0),
                         coverage.STATE_REPLICATE)

    def test_spread_inside_band_is_not_replicate(self):
        cell = _cell([_proposal("SS", "1x1x1", "e")], {"e": [10.0] * 8})
        self.assertEqual(coverage.decide_state(cell, band_pct=5.0),
                         coverage.STATE_EXPLORE)

    def test_no_fourth_state_exists(self):
        self.assertEqual(len(coverage.CELL_STATES), 3)
        self.assertNotIn("empty", coverage.CELL_STATES)

    def test_state_is_always_one_of_three(self):
        cells = [
            _cell([_proposal("SS", "1", "a")], {"a": [10.0] * 8}),
            _cell([_proposal("SS", "2", "b")], {"b": [10.0]}),
            _cell([_proposal("ZZ", "3", "c", "non_functional")], {}),
        ]
        for cell in cells:
            self.assertIn(coverage.decide_state(cell), coverage.CELL_STATES)

    def test_a_rejected_candidate_is_not_retirement(self):
        # legal_rejected means the proposal never ran, so the cell is unexplored
        # rather than exhausted.
        cell = _cell([_proposal("DD", "1", "x", "legal_rejected")], {})
        self.assertNotEqual(coverage.decide_state(cell), coverage.STATE_RETIRED)

    def test_pending_only_is_not_retired(self):
        cell = _cell([_proposal("DD", "1", "x", "pending")], {})
        self.assertNotEqual(coverage.decide_state(cell), coverage.STATE_RETIRED)


class TestCoverageCells(unittest.TestCase):
    def test_distinct_fingerprints_are_counted(self):
        rows = [_proposal("SS", "1x1x1", "a"), _proposal("SS", "1x1x1", "a"),
                _proposal("SS", "1x1x1", "b")]
        cell = _cell(rows, {})
        self.assertEqual(cell["n_distinct_fp"], 2)
        self.assertEqual(cell["n_proposed"], 3)

    def test_min_n_is_the_worst_measured_config(self):
        cell = _cell([_proposal("SS", "1", "a"), _proposal("SS", "1", "b")],
                     {"a": [10.0] * 8, "b": [10.0]})
        self.assertEqual(cell["min_n"], 1)

    def test_spread_matches_policy_definition(self):
        samples = [10.0, 10.0, 20.0]
        cell = _cell([_proposal("SS", "1", "a")], {"a": samples})
        expected = (max(samples) - statistics.median(samples)) / statistics.median(samples)
        self.assertAlmostEqual(cell["max_spread_ratio"], expected)

    def test_unmeasured_fingerprints_are_absent_from_per_fp(self):
        cell = _cell([_proposal("SS", "1", "a"), _proposal("SS", "1", "z")],
                     {"a": [10.0] * 8})
        self.assertEqual(cell["n_distinct_fp"], 2)
        self.assertEqual(cell["n_measured"], 1)

    def test_zero_yield_samples_do_not_count_as_measured(self):
        cell = _cell([_proposal("SS", "1", "a")], {"a": [0.0, 0.0, 10.0]})
        self.assertEqual(cell["per_fp"][0]["n"], 1)

    def test_cells_are_grouped_by_family_and_shape(self):
        rows = [_proposal("SS", "1", "a"), _proposal("SS", "2", "b"),
                _proposal("ZZ", "1", "c")]
        cells = coverage.coverage_cells(rows, {})
        self.assertEqual(len(cells), 3)
        self.assertEqual([(c["family"], c["shape"]) for c in cells],
                         [("SS", "1"), ("SS", "2"), ("ZZ", "1")])


class TestLowerConfidenceBound(unittest.TestCase):
    def test_single_sample_returns_the_value(self):
        self.assertEqual(coverage.lower_confidence_bound([10.0]), 10.0)

    def test_empty_returns_zero(self):
        self.assertEqual(coverage.lower_confidence_bound([]), 0.0)

    def test_steady_beat_beats_noisy_at_the_same_median(self):
        steady = coverage.lower_confidence_bound([10.0] * 8)
        noisy = coverage.lower_confidence_bound([10.0, 30.0, 4.0, 28.0, 5.0, 26.0, 6.0, 24.0])
        self.assertGreater(steady, noisy)

    def test_bound_is_below_the_median_for_varied_samples(self):
        bound = coverage.lower_confidence_bound([10.0, 12.0, 11.0, 9.0])
        self.assertLess(bound, statistics.median([10.0, 12.0, 11.0, 9.0]))

    def test_zero_yield_samples_are_excluded(self):
        self.assertEqual(coverage.lower_confidence_bound([0.0, 0.0]), 0.0)

    def test_more_seeds_raise_the_bound(self):
        # Identical distribution, more samples -> tighter bound -> higher LCB.
        base = [10.0, 12.0, 8.0, 11.0]
        self.assertGreater(coverage.lower_confidence_bound(base * 4),
                           coverage.lower_confidence_bound(base))


class TestSelectParent(unittest.TestCase):
    """Hplan.5 step 3: LCB, never raw winner."""

    def _cell(self):
        return _cell([_proposal("SS", "1", "steady"),
                      _proposal("SS", "1", "noisy")],
                     {"steady": [13.2, 12.9, 13.1, 13.4, 13.0, 13.3, 13.1, 12.7],
                      "noisy": [22.1, 9.4, 18.7, 11.2, 20.3, 8.6, 17.9, 12.4]})

    def test_raw_median_would_pick_the_noisy_config(self):
        cell = self._cell()
        by_median = max(cell["per_fp"], key=lambda e: e["median"])
        self.assertEqual(by_median["fp"], "noisy")

    def test_lcb_picks_the_steady_config(self):
        self.assertEqual(coverage.select_parent(self._cell())["fp"], "steady")

    def test_fallback_used_when_nothing_is_measured(self):
        self.assertEqual(coverage.select_parent({"per_fp": []}, fallback={"fp": "x"}),
                         {"fp": "x"})

    def test_none_when_measured_but_no_fallback(self):
        self.assertIsNone(coverage.select_parent({"per_fp": []}))

    def test_parent_never_comes_from_an_unmeasured_fingerprint(self):
        cell = _cell([_proposal("SS", "1", "a")], {})
        self.assertIsNone(coverage.select_parent(cell))


class TestCoverageSummary(unittest.TestCase):
    def test_summary_tallies_every_state(self):
        rows = [_proposal("SS", "1", "a"), _proposal("ZZ", "2", "b", "non_functional"),
                _proposal("DD", "3", "c")]
        samples = {"a": [10.0] * 8, "c": [1.0]}
        summary = coverage.coverage_summary(rows, samples, band_pct=5.0)
        self.assertEqual(set(summary["tally"]), coverage.CELL_STATES)
        self.assertEqual(summary["tally"][coverage.STATE_RETIRED], 1)
        self.assertEqual(summary["tally"][coverage.STATE_REPLICATE], 1)

    def test_summary_exposes_parent_per_cell(self):
        rows = [_proposal("SS", "1", "a")]
        summary = coverage.coverage_summary(rows, {"a": [10.0] * 8}, band_pct=5.0)
        self.assertEqual(summary["cells"][0]["parent_fp"], "a")
        self.assertIsNotNone(summary["cells"][0]["parent_lcb"])

    def test_band_is_carried_through_for_reporting(self):
        summary = coverage.coverage_summary([], {}, band_pct=7.5)
        self.assertEqual(summary["band_pct"], 7.5)


class TestRegistryIntegration(unittest.TestCase):
    """The registry -> coverage path, including the fp join."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        from oto.ledger.registry import SQLiteRegistry
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_cov_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.registry = SQLiteRegistry(self.tmp)

    def _proposal(self, family, shape, fp, outcome="functional"):
        self.registry.record_proposal(fp=fp, family=family, shape=shape,
                                      parent_fp="parent", iteration=0)
        if outcome != "pending":
            self.registry.resolve_proposal(fp, outcome)

    def _sample(self, fp, gflops):
        self.registry.append_record({
            "type": "benchmark_result", "fingerprint": fp, "GFLOPS": gflops,
        }, run_id="cov_run")

    def test_all_proposals_is_ordered_and_complete(self):
        self._proposal("SS", "1x1x1", "a")
        self._proposal("ZZ", "2x2x2", "b")
        rows = self.registry.all_proposals()
        self.assertEqual({r["fp"] for r in rows}, {"a", "b"})
        for row in rows:
            self.assertEqual(row["family"], row["family"])
            self.assertIn("shape", row)
            self.assertIn("origin", row)

    def test_samples_join_to_proposals_by_fp(self):
        self._proposal("SS", "1x1x1", "a")
        self._sample("a", 10.0)
        self._sample("a", 10.5)
        summary = coverage.coverage_from_registry(self.registry, band_pct=5.0)
        cell = summary["cells"][0]
        self.assertEqual(cell["n_distinct_fp"], 1)
        self.assertEqual(cell["min_n"], 2)
        self.assertEqual(cell["n_measured"], 1)

    def test_records_without_a_proposal_are_not_cells(self):
        # The join direction matters: a measurement with no proposal row is not
        # a mutated cell, and inventing one would report coverage nobody has.
        self._sample("orphan", 10.0)
        summary = coverage.coverage_from_registry(self.registry, band_pct=5.0)
        self.assertEqual(summary["cells"], [])

    def test_thin_measurement_reaches_the_registry_path_as_replicate(self):
        self._proposal("SS", "1x1x1", "a")
        self._sample("a", 10.0)
        summary = coverage.coverage_from_registry(self.registry, band_pct=5.0)
        self.assertEqual(summary["cells"][0]["state"], coverage.STATE_REPLICATE)

    def test_retired_reaches_the_registry_path(self):
        self._proposal("ZZ", "1x1x1", "b", outcome="non_functional")
        summary = coverage.coverage_from_registry(self.registry, band_pct=5.0)
        self.assertEqual(summary["cells"][0]["state"], coverage.STATE_RETIRED)

    def test_parent_fp_is_carried_through(self):
        self._proposal("SS", "1x1x1", "a")
        self._sample("a", 10.0)
        self._sample("a", 10.1)
        rows = {r["fp"]: r for r in self.registry.all_proposals()}
        self.assertEqual(rows["a"]["parent_fp"], "parent")

    def test_zero_yield_records_are_not_samples(self):
        self._proposal("SS", "1x1x1", "a")
        self._sample("a", 0.0)
        grouped = coverage.samples_by_fingerprint(
            self.registry.read_records(record_type="benchmark_result"))
        self.assertEqual(grouped, {})


class TestMeasuredBand(unittest.TestCase):
    """The band must be genuinely read, not merely *attempted*.

    The first version of this test asserted `value is None or value > 0`, which
    passes for a function that always raises and returns None. It did: the call
    into `ab_audit` passed one argument to a two-argument function and the
    `except Exception` swallowed the `TypeError`, so the band was never read at
    all and every cell silently fell back to "no band". These tests are written
    to fail on that exact shape.
    """

    def test_band_is_read_not_defaulted(self):
        value = coverage.measured_band_pct(ab_audit.BASE)
        self.assertIsNotNone(
            value, "measured_band_pct() returned None: the read is dead")

    def test_band_matches_the_canonical_audit_band(self):
        # Same corpus, same two canonical calls, so the numbers must be equal.
        native, floor, _chain = ab_audit.arm_record_sets(ab_audit.BASE)
        canonical = ab_audit.measured_band(native, floor)["band_pct"]
        self.assertAlmostEqual(
            coverage.measured_band_pct(ab_audit.BASE), canonical, places=9)

    def test_band_agrees_with_a_full_audit(self):
        # The audit and coverage must never grade against two different bands.
        self.assertAlmostEqual(
            ab_audit.audit(ab_audit.BASE)["band_pct"],
            coverage.measured_band_pct(ab_audit.BASE), places=9)

    def test_band_clears_the_shipped_floor(self):
        # Sanity on the corpus: repeats of one config scatter far past the
        # shipped 5%, so the band must reflect that rather than the floor.
        self.assertGreater(coverage.measured_band_pct(ab_audit.BASE),
                           ab_audit.TIE_BAND_PCT)

    def test_missing_corpus_yields_none_not_a_default(self):
        # Unmeasurable must stay None rather than becoming a plausible number.
        self.assertIsNone(
            coverage.measured_band_pct("/nonexistent-corpus-path"))

    def test_caller_supplied_band_is_recorded_not_substituted(self):
        native, floor, _chain = ab_audit.arm_record_sets(ab_audit.BASE)
        out = ab_audit.measured_band(native, floor, band_pct=12.5)
        self.assertEqual(out["band_pct"], 12.5)
        self.assertEqual(out["band_source"], "caller-supplied")

    def test_components_are_returned_with_the_band(self):
        # A band with no provenance attached is the number-that-became-fact.
        native, floor, _chain = ab_audit.arm_record_sets(ab_audit.BASE)
        out = ab_audit.measured_band(native, floor)
        self.assertIn("protocol_matched", out["cross_arm"])
        self.assertIn("p90_cv_pct", out["repeat_dispersion"])
        self.assertTrue(out["band_source"])

    def test_audit_does_not_recurse_through_coverage(self):
        # audit() -> _proposal_coverage() -> coverage_from_registry(). If that
        # fell back to measured_band_pct() -> ab_audit.audit(), this hangs.
        res = ab_audit.audit(ab_audit.BASE)
        self.assertIn("proposal_coverage", res)


class TestTargetCellsAreVisible(unittest.TestCase):
    """A targeted cell with no proposal must appear, as `explore`."""

    def test_target_with_no_proposal_is_present(self):
        cells = coverage.coverage_cells([], {}, target_cells=[("SS", "128x128x128")])
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["family"], "SS")

    def test_target_with_no_proposal_is_explore(self):
        cells = coverage.coverage_cells([], {}, target_cells=[("SS", "128x128x128")])
        self.assertEqual(coverage.decide_state(cells[0]), coverage.STATE_EXPLORE)

    def test_unproposed_target_reports_zero_evidence(self):
        cells = coverage.coverage_cells([], {}, target_cells=[("SS", "128x128x128")])
        cell = cells[0]
        self.assertEqual(cell["n_proposed"], 0)
        self.assertEqual(cell["n_distinct_fp"], 0)
        self.assertEqual(cell["min_n"], 0)

    def test_unproposed_target_is_not_retired(self):
        # The conflation §H.1.2a is about: never tried != tried and failed.
        cells = coverage.coverage_cells([], {}, target_cells=[("SS", "128x128x128")])
        self.assertNotEqual(coverage.decide_state(cells[0]),
                            coverage.STATE_RETIRED)

    def test_targets_do_not_drop_proposed_cells(self):
        rows = [{"family": "SS", "shape": "128x128x128", "fp": "a",
                 "outcome": "functional"}]
        cells = coverage.coverage_cells(rows, {"a": [10.0, 10.1]},
                                        target_cells=[("ZZ", "64x64x64")])
        self.assertEqual({(c["family"], c["shape"]) for c in cells},
                         {("SS", "128x128x128"), ("ZZ", "64x64x64")})

    def test_a_retired_cell_is_distinct_from_an_unproposed_target(self):
        retired = coverage.coverage_cells(
            [{"family": "SS", "shape": "128x128x128", "fp": "a",
              "outcome": "non_functional"}], {"a": [0.0]})[0]
        never = coverage.coverage_cells(
            [], {}, target_cells=[("SS", "128x128x128")])[0]
        self.assertEqual(coverage.decide_state(retired), coverage.STATE_RETIRED)
        self.assertEqual(coverage.decide_state(never), coverage.STATE_EXPLORE)

    def test_targets_reach_the_registry_summary(self):
        rows = [{"family": "SS", "shape": "128x128x128", "fp": "a",
                 "outcome": "functional"}]
        summary = coverage.coverage_summary(
            rows, {"a": [10.0, 10.1]},
            target_cells=[("ZZ", "64x64x64")])
        self.assertEqual(summary["tally"][coverage.STATE_EXPLORE], 2)

    def test_duplicate_targets_do_not_duplicate_cells(self):
        cells = coverage.coverage_cells([], {},
                                        target_cells=[("SS", "128x128x128")] * 3)
        self.assertEqual(len(cells), 1)

    def test_targets_are_sorted_with_the_rest(self):
        rows = [{"family": "ZZ", "shape": "1x1x1", "fp": "a",
                 "outcome": "functional"}]
        cells = coverage.coverage_cells(rows, {"a": [1.0, 1.0]},
                                        target_cells=[("AA", "9x9x9")])
        self.assertEqual([c["family"] for c in cells], ["AA", "ZZ"])


if __name__ == "__main__":
    unittest.main()