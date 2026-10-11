"""Tests for LCB parent selection in `ConvergenceAgent.harvest` (`Hplan.5` step 3).

The defect being closed is specific: `harvest()` used to take
`max(median_gflops)`, so a config whose median was high because one seed landed
well became the parent of the next batch. These tests build both configs through
the real `compute_cell_analytics`, so the seeds the LCB needs are the ones
analytics actually produced.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from oto.ledger.agent import ConvergenceAgent
from oto.metrics.analytics import AnalyticsEngine
from oto.ledger.registry import SQLiteRegistry

# A steady cell: median ~13.1, tiny spread.
STEADY = [13.2, 12.9, 13.1, 13.4, 13.0, 13.3, 13.1, 12.7]
# A lucky cell: median ~15.1 (higher!), enormous spread.
LUCKY = [22.1, 9.4, 18.7, 11.2, 20.3, 8.6, 17.9, 12.4]


class _StubScheduler:
    family_decks = {"SS": [{"MacroTile": "64x64x16", "ThreadTile": "4x4"}]}

    def emit_candidate(self, **kw):
        return None

    def validate_config(self, config):
        return True, ""

    def mutate_winner(self, config, budget):
        return []


class HarvestParentSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_harvest_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.registry = SQLiteRegistry(self.tmp)
        (self.tmp / "phases.yaml").write_text("[]")
        self.analytics = AnalyticsEngine(self.registry, self.tmp)
        self.agent = ConvergenceAgent(
            self.tmp, _StubScheduler(), self.analytics)

    def _cell(self, fp, seeds, shape="128x128x128", family="SS"):
        return self.analytics.compute_cell_analytics(
            family, shape, fp, seeds, family=family)

    def _cells(self):
        return [self._cell("fp_steady", STEADY),
                self._cell("fp_lucky", LUCKY)]

    def test_the_premise_holds(self):
        # Guards the test itself: if LUCKY's median were not higher, the whole
        # "raw winner picks noise" argument would be vacuous here.
        steady, lucky = self._cells()
        self.assertGreater(lucky.median_gflops, steady.median_gflops)

    def test_lcb_prefers_the_steady_config(self):
        winners = self.agent.harvest(self._cells())
        self.assertEqual(winners["SS_128x128x128"]["fp"], "fp_steady")

    def test_median_policy_still_picks_the_lucky_config(self):
        # The old rule remains reachable so the two can be compared, and this
        # pins that they genuinely differ on this data.
        winners = self.agent.harvest(self._cells(), parent_by="median")
        self.assertEqual(winners["SS_128x128x128"]["fp"], "fp_lucky")

    def test_the_divergence_is_recorded_on_the_winner(self):
        winners = self.agent.harvest(self._cells())
        self.assertTrue(winners["SS_128x128x128"]["selected_by_lcb"])

    def test_policy_is_recorded_on_every_winner(self):
        winners = self.agent.harvest(self._cells())
        for key, w in winners.items():
            self.assertEqual(w["parent_by"], "lcb", key)
            self.assertIn("parent_score", w)
            self.assertIn("n_seeds", w)

    def test_no_divergence_flag_when_raw_winner_agrees(self):
        winners = self.agent.harvest([self._cell("fp_only", STEADY)])
        self.assertFalse(winners["SS_128x128x128"]["selected_by_lcb"])

    def test_seeds_travel_with_the_cell(self):
        steady, _ = self._cells()
        self.assertEqual(steady.seeds, STEADY)

    def test_single_seed_cell_is_still_usable_as_a_parent(self):
        # n=1 has no variance, so the bound equals the median. The cell is routed
        # to `replicate` by coverage state; harvest must not crash or drop it.
        winners = self.agent.harvest([self._cell("fp_one", [12.0])])
        self.assertEqual(winners["SS_128x128x128"]["fp"], "fp_one")
        self.assertEqual(winners["SS_128x128x128"]["n_seeds"], 1)

    def test_cells_without_seeds_do_not_raise(self):
        # A hand-built CellAnalytics (no seeds attached) must degrade to the
        # median rather than invent a variance.
        bare = self._cell("fp_bare", STEADY)
        bare.seeds = []
        winners = self.agent.harvest([bare])
        self.assertEqual(winners["SS_128x128x128"]["fp"], "fp_bare")

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            self.agent.harvest(self._cells(), parent_by="vibes")

    def test_both_policies_agree_when_evidence_is_uniform(self):
        steady = self._cell("fp_steady", STEADY)
        lucky = self._cell("fp_lucky", [15.1] * 8)
        by_lcb = self.agent.harvest([steady, lucky], parent_by="lcb")
        by_median = self.agent.harvest([steady, lucky], parent_by="median")
        self.assertEqual(by_lcb["SS_128x128x128"]["fp"],
                         by_median["SS_128x128x128"]["fp"])

    def test_each_cell_gets_its_own_parent(self):
        winners = self.agent.harvest([
            self._cell("fp_steady", STEADY),
            self._cell("fp_zz", [40.0] * 8, family="ZZ"),
        ])
        self.assertEqual(set(winners), {"SS_128x128x128", "ZZ_128x128x128"})
        self.assertEqual(winners["ZZ_128x128x128"]["fp"], "fp_zz")


if __name__ == "__main__":
    unittest.main()