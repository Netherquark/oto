"""Option H Phase 4: coverage-guided constrained synthesis (`Hplan.6`).

The four requirements, and the failure each is guarding against:

* step 1 — coverage-guided sampling replaces the lattice walk, and the lattice
  remains a deterministic fallback so behaviour degrades rather than fails.
  Without the fallback, a family the manifest does not cover ends the run; with a
  *silent* fallback, a run spends iterations on lattice draws while reporting
  prior-guided work.
* step 2 — extend beyond the lattice's knobs, manifest-legal values only. This is
  asserted structurally, without calling `validate_config`: a sampler that leans
  on the assertion it is supposed to precede passes for the wrong reason.
* step 3 — multi-shape family sweeps, or a mutant is born ungradable (Hplan.1
  item 5).
* step 4 — `ThreadTile`/`WorkGroup` derived from `MacroTile` so the product
  constraint holds by construction.
"""

import collections
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

import coverage
import legality
import synthesis
import yaml
from gfx90c_common import FAMILY_DTYPES
from mutator import Mutator
from scheduler import CandidateConfig


class StubGenerator:
    """Minimal CandidateGenerator surface that `mutate_and_feed` uses."""

    def __init__(self, mutants=(), valid=True, reason=""):
        self._mutants = list(mutants)
        self._valid = valid
        self._reason = reason
        self.appended = []

    def mutate_winner(self, config, mutation_budget):
        return list(self._mutants)

    def emit_candidate(self, phase_id, label, dtype, shapes, template, knobs):
        import hashlib
        import json
        full = {**template, **knobs}
        fp = hashlib.sha256(
            json.dumps(full, sort_keys=True).encode()).hexdigest()
        return CandidateConfig(
            phase_id=phase_id, label=label, dtype=dtype, shapes=list(shapes),
            template=template, knobs=knobs, fingerprint=fp)

    def validate_config(self, config):
        return (self._valid, self._reason)

    def append_to_phases(self, candidate, phases_file=None):
        self.appended.append(candidate)
        return candidate.phase_id

REPO = Path(__file__).resolve().parent.parent

DECK = [
    {"phase_id": "p_ss", "shapes": ["256x256x256", "512x512x512", "1024x1024x1024"],
     "config": {"FamilyLabel": "SS"}},
    {"phase_id": "p_zz", "shapes": ["128x128x128", "256x256x256"],
     "config": {"FamilyLabel": "ZZ"}},
    # Same family, different shapes: the sweep must union, not silently pick one.
    {"phase_id": "p_ss2", "shapes": ["256x256x256", "768x768x768"],
     "config": {"FamilyLabel": "SS"}},
    {"phase_id": "p_nofam", "shapes": ["1x1x1"], "config": {}},
]


class ShapeSweepTests(unittest.TestCase):
    def test_sweep_is_read_per_family(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        self.assertEqual(set(sweeps), {"SS", "ZZ"})

    def test_same_family_shapes_are_unioned(self):
        # Picking one phase's shapes would silently benchmark the mutant over a
        # subset of what the floor was measured over.
        self.assertEqual(synthesis.family_shape_sweeps(DECK)["SS"],
                         ["256x256x256", "512x512x512", "1024x1024x1024",
                          "768x768x768"])

    def test_sweep_is_deduplicated_order_preserving(self):
        self.assertEqual(len(synthesis.family_shape_sweeps(DECK)["SS"]), 4)

    def test_a_family_without_a_label_is_skipped(self):
        # Not invented under some default family either.
        self.assertNotIn("", synthesis.family_shape_sweeps(DECK))
        self.assertNotIn(None, synthesis.family_shape_sweeps(DECK))

    def test_shape_lists_are_normalised_to_text(self):
        sweeps = synthesis.family_shape_sweeps(
            [{"shapes": [[128, 128, 128], [256, 256, 256]],
              "config": {"FamilyLabel": "DD"}}])
        self.assertEqual(sweeps["DD"], ["128x128x128", "256x256x256"])

    def test_empty_deck_yields_no_sweeps(self):
        self.assertEqual(synthesis.family_shape_sweeps([]), {})
        self.assertEqual(synthesis.family_shape_sweeps(None), {})

    def test_a_two_shape_sweep_counts_as_graded(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        self.assertTrue(synthesis.sweep_for_family("ZZ", sweeps))

    def test_a_one_shape_sweep_is_not_graded(self):
        sweeps = {"DD": ["128x128x128"]}
        out = synthesis.sweep_for_family("DD", sweeps,
                                         fallback=["256x256x256"])
        self.assertEqual(out, ["256x256x256"])

    def test_no_sweep_and_no_fallback_stays_single_shape(self):
        # Better than inventing shapes: an ungradable candidate that says so.
        self.assertEqual(synthesis.sweep_for_family("QQ", {}, fallback=None), [])

    def test_fallback_is_used_when_the_family_is_absent(self):
        out = synthesis.sweep_for_family("QQ", synthesis.family_shape_sweeps(DECK),
                                         fallback=["1024x1024x1024"])
        self.assertEqual(out, ["1024x1024x1024"])

    def test_lookup_is_case_insensitive(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        self.assertEqual(synthesis.sweep_for_family("ss", sweeps),
                         sweeps["SS"])


class ReconcileTileTests(unittest.TestCase):
    def _tile(self, macro, wg, tt):
        return {"MacroTile": macro, "WorkGroup": wg, "ThreadTile": tt}

    def test_a_consistent_tile_is_untouched(self):
        cfg = self._tile("64x64x16", "16x16x1", "4x4")
        self.assertEqual(synthesis.reconcile_tile(cfg), cfg)

    def test_missing_thread_tile_is_solved_from_workgroup(self):
        out = synthesis.reconcile_tile(
            self._tile("128x64x16", "32x8x1", None))
        self.assertEqual(out["ThreadTile"], "4x8")

    def test_missing_workgroup_is_solved_from_thread_tile(self):
        out = synthesis.reconcile_tile(
            self._tile("64x32x16", None, "4x4"))
        self.assertEqual(out["WorkGroup"], "16x8x1")

    def test_a_disagreeing_pair_reconciles_to_the_macrotile(self):
        # Tensile trusts the MacroTile: it has to have a shipped schedule to be
        # valid at all, whereas a ThreadTile that does not tile it is meaningless.
        out = synthesis.reconcile_tile(
            self._tile("64x64x16", "16x16x1", "8x8"))
        self.assertEqual(out["ThreadTile"], "4x4")

    def test_reconciliation_makes_the_product_hold(self):
        out = synthesis.reconcile_tile(self._tile("64x64x16", "16x16x1", "8x8"))
        self.assertTrue(synthesis.tile_product_holds(out))

    def test_an_unsolved_dimension_never_renders_as_the_string_none(self):
        # Regression: an unsolved dim once formatted as a literal "None", which
        # Tensile rejects at parameter-parse time rather than at our check.
        for wg, tt in (("24x24x1", None), ("32x8x1", None),
                       (None, "8x8"), ("16x16x1", "99x99")):
            out = synthesis.reconcile_tile(
                self._tile("64x64x16", wg, tt))
            for key in ("WorkGroup", "ThreadTile"):
                self.assertNotIn("None", out[key], out)
                self.assertTrue(all(int(p) >= 1 for p in out[key].split("x")))

    def test_a_non_tileable_pair_is_left_rather_than_guessed(self):
        # 64 % 24 != 0, so there is no integer ThreadTile; inventing one would
        # produce a config that looks reconciled and is not.
        cfg = self._tile("64x64x16", "24x24x1", None)
        self.assertFalse(synthesis.tile_product_holds(cfg))
        self.assertFalse(synthesis.tile_product_holds(
            synthesis.reconcile_tile(cfg)))

    def test_a_missing_macrotile_is_a_no_op(self):
        cfg = {"WorkGroup": "16x16x1", "ThreadTile": "4x4"}
        self.assertEqual(synthesis.reconcile_tile(cfg), cfg)

    def test_an_unparseable_macrotile_is_a_no_op(self):
        cfg = self._tile("64", "16x16x1", "4x4")
        self.assertEqual(synthesis.reconcile_tile(cfg), cfg)

    def test_product_check_passes_when_there_is_no_tile_to_check(self):
        self.assertTrue(synthesis.tile_product_holds({"MacroTile": None}))

    def test_product_check_fails_when_either_half_is_absent(self):
        self.assertFalse(synthesis.tile_product_holds(
            {"MacroTile": "64x64x16", "ThreadTile": "4x4"}))
        self.assertFalse(synthesis.tile_product_holds(
            {"MacroTile": "64x64x16", "WorkGroup": "16x16x1"}))

    def test_product_check_only_examines_m_and_n(self):
        # K is not part of the constraint Tensile enforces per M/N dimension.
        self.assertTrue(synthesis.tile_product_holds(
            self._tile("64x64x16", "16x16x4", "4x4")))

    def test_a_zero_dimension_is_treated_as_absent(self):
        # `0x16x1` is not a workgroup. A zero parses to "unset" rather than
        # multiplying out to a spurious zero that trivially matches nothing.
        cfg = self._tile("64x64x16", "0x16x1", "4x4")
        self.assertFalse(synthesis.tile_product_holds(cfg))


class CoverageGuidanceTests(unittest.TestCase):
    def _cell(self, groups, spread=0.9):
        return {"per_fp": [{"fp": "a", "spread_ratio": spread, "groups": groups}]}

    def test_an_unstable_group_is_excluded(self):
        cell = self._cell(["split"])
        picks = collections.Counter()
        rng = random.Random(0)
        for _ in range(400):
            picks.update(synthesis.choose_groups(cell, 2, rng, band_pct=10.0))
        self.assertEqual(picks["split"], 0)
        self.assertGreater(picks["tile"], 0)

    def test_without_a_band_nothing_is_excluded(self):
        # Guessing a threshold is how a sampler starts avoiding knobs for no
        # reason at all.
        cell = self._cell(["split"])
        picks = collections.Counter()
        rng = random.Random(0)
        for _ in range(400):
            picks.update(synthesis.choose_groups(cell, 2, rng, band_pct=None))
        self.assertGreater(picks["split"], 0)

    def test_a_stable_config_does_not_exclude_its_groups(self):
        cell = self._cell(["split"], spread=0.01)
        picks = collections.Counter()
        rng = random.Random(0)
        for _ in range(400):
            picks.update(synthesis.choose_groups(cell, 2, rng, band_pct=10.0))
        self.assertGreater(picks["split"], 0)

    def test_an_unknown_group_name_is_ignored(self):
        cell = self._cell(["not_a_group"])
        picks = synthesis.choose_groups(cell, 2, random.Random(0), band_pct=10.0)
        self.assertTrue(set(picks) <= set(synthesis.ALL_GROUPS))

    def test_no_cell_means_no_guidance(self):
        picks = synthesis.choose_groups(None, 2, random.Random(0), band_pct=10.0)
        self.assertTrue(set(picks) <= set(synthesis.ALL_GROUPS))

    def test_excluding_everything_still_returns_a_draw(self):
        # A cell unstable in every group is unstable everywhere; returning
        # nothing would let the caller report it as unexplored.
        cell = self._cell(list(synthesis.ALL_GROUPS))
        picks = synthesis.choose_groups(cell, 2, random.Random(0), band_pct=1.0)
        self.assertTrue(picks)

    def test_the_requested_width_is_honoured(self):
        for n in (1, 2, 3):
            picks = synthesis.choose_groups(None, n, random.Random(1),
                                            band_pct=10.0)
            self.assertEqual(len(picks), min(n, len(synthesis.ALL_GROUPS)))

    def test_draws_are_reproducible_for_a_seed(self):
        a = synthesis.choose_groups(self._cell(["split"]), 2,
                                    random.Random(5), band_pct=10.0)
        b = synthesis.choose_groups(self._cell(["split"]), 2,
                                    random.Random(5), band_pct=10.0)
        self.assertEqual(sorted(a), sorted(b))

    def test_unknown_groups_never_appear(self):
        for seed in range(20):
            picks = synthesis.choose_groups(None, 3, random.Random(seed),
                                            band_pct=10.0)
            self.assertTrue(set(picks) <= set(legality.KNOB_GROUPS))


class SynthesisDrawTests(unittest.TestCase):
    def test_candidates_are_wall_clean(self):
        # Structural legality, asserted without validate_config: leaning on the
        # assertion the sampler is supposed to precede passes for the wrong reason.
        res = synthesis.synthesize_cell(
            REPO, "SS", base_config={"MacroTile": "64x64x16"},
            groups=2, draws=8, seed=3, shape="128x128x128")
        self.assertTrue(res["candidates"])
        for cand in res["candidates"]:
            cfg = {"Architecture": "gfx90c", "DataType": "S",
                   "ProblemType": "Contraction", **cand["knobs"]}
            ok, reason = legality.check_hard_walls(cfg)
            self.assertTrue(ok, f"{reason}: {cfg}")

    def test_every_candidate_tiles(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=8, seed=4,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            self.assertTrue(synthesis.tile_product_holds(cand["knobs"]),
                            cand["knobs"])

    def test_template_keys_are_never_emitted(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=6, seed=5,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            self.assertFalse(set(cand["knobs"]) & set(synthesis.TEMPLATE_KEYS))

    def test_drawn_groups_are_reported(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=6, seed=6,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            self.assertTrue(set(cand["groups"]) <= set(synthesis.ALL_GROUPS))

    def test_a_family_with_no_support_yields_nothing_and_says_why(self):
        res = synthesis.synthesize_cell(REPO, "QQ", draws=4, seed=0,
                                        shape="128x128x128")
        self.assertEqual(res["candidates"], [])
        self.assertIn("QQ", " ".join(res["dropped"]))

    def test_the_sweep_is_reported_and_flagged_graded(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        res = synthesis.synthesize_cell(REPO, "SS", draws=2, seed=7,
                                        shape="128x128x128", sweeps=sweeps)
        self.assertEqual(len(res["shapes"]), 4)
        self.assertTrue(res["graded"])

    def test_a_single_shape_is_reported_as_ungraded(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=2, seed=8,
                                        shape="128x128x128", sweeps={})
        self.assertFalse(res["graded"])

    def test_the_cell_state_is_reported(self):
        cell = {"n_proposed": 1, "n_distinct_fp": 1, "min_n": 0,
                "outcomes": {"non_functional": 1}, "per_fp": []}
        res = synthesis.synthesize_cell(REPO, "SS", cell=cell, draws=1, seed=0,
                                        shape="128x128x128")
        self.assertEqual(res["state"], coverage.STATE_RETIRED)

    def test_zero_draws_is_honoured(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=0, seed=0,
                                        shape="128x128x128")
        self.assertEqual(res["candidates"], [])

    def test_source_names_the_sampler(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=2, seed=1,
                                        shape="128x128x128")
        self.assertEqual(res["source"], "manifest_sampler")


class LatticeFallbackTests(unittest.TestCase):
    def _synth_none(self, family, **kw):
        return {"candidates": [], "source": "manifest_sampler",
                "dropped": {"no shipped support": 8}, "shapes": [],
                "graded": False, "family": family}

    def _synth_some(self, family, **kw):
        return {"candidates": [{"knobs": {"MacroTile": "64x64x16"},
                                "groups": ("tile",)}],
                "source": "manifest_sampler", "dropped": {}, "shapes": [],
                "graded": False, "family": family}

    def _lattice(self, family, **kw):
        return [{"MacroTile": "96x96x16", "ThreadTile": "6x6"}]

    def test_the_lattice_is_used_only_when_the_sampler_yields_nothing(self):
        out = synthesis.synthesize_or_lattice(
            self._synth_none, self._lattice, "QQ")
        self.assertEqual(out["source"], "lattice")
        self.assertEqual(len(out["candidates"]), 1)

    def test_the_lattice_is_not_used_when_the_sampler_works(self):
        out = synthesis.synthesize_or_lattice(
            self._synth_some, self._lattice, "SS")
        self.assertEqual(out["source"], "manifest_sampler")

    def test_the_fallback_reason_is_kept(self):
        # A run that fell back must be distinguishable from one that did not.
        out = synthesis.synthesize_or_lattice(
            self._synth_none, self._lattice, "QQ")
        self.assertIn("no shipped support", str(out["fallback_reason"]))

    def test_fallback_candidates_have_no_group_attribution(self):
        # The lattice does not say which group it moved, so claiming one would be
        # a fabricated attribution feeding coverage guidance.
        out = synthesis.synthesize_or_lattice(
            self._synth_none, self._lattice, "QQ")
        self.assertIsNone(out["candidates"][0]["groups"])

    def test_neither_source_yields_unavailable(self):
        out = synthesis.synthesize_or_lattice(
            self._synth_none, lambda *a, **k: [], "QQ")
        self.assertEqual(out["source"], "unavailable")
        self.assertEqual(out["candidates"], [])

    def test_only_relevant_kwargs_reach_the_lattice(self):
        seen = {}

        def lattice(family, base_config=None, shape=None, groups=None):
            seen.update(family=family, base_config=base_config, shape=shape,
                        groups=groups)
            return [{"MacroTile": "64x64x16"}]
        synthesis.synthesize_or_lattice(self._synth_none, lattice, "QQ",
                                        base_config={"MacroTile": "64x64x16"},
                                        shape="128x128x128", groups=2,
                                        cell={"x": 1})
        self.assertNotIn("cell", seen)
        self.assertEqual(seen["shape"], "128x128x128")


class KnobSpaceTests(unittest.TestCase):
    """Step 2: the knob space is exhausted at the manifest, not merely narrow."""

    def test_the_sampler_covers_every_legal_knob(self):
        covered = set()
        for knobs in legality.KNOB_GROUPS.values():
            covered |= set(knobs)
        self.assertEqual(covered, {
            "MacroTile", "ThreadTile", "WorkGroup", "VectorWidth",
            "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
            "GlobalSplitU", "DepthU",
        })

    def test_no_group_is_empty(self):
        for name, knobs in legality.KNOB_GROUPS.items():
            self.assertTrue(knobs, name)

    def test_groups_do_not_overlap(self):
        # Overlapping groups would make a "2-group" draw move fewer than two
        # independent things, and the width would be a lie.
        seen = set()
        for knobs in legality.KNOB_GROUPS.values():
            self.assertFalse(seen & set(knobs), f"overlap on {seen & set(knobs)}")
            seen |= set(knobs)

    def test_the_sampler_exceeds_the_lattice_knob_set(self):
        lattice_knobs = {"MacroTile", "ThreadTile", "NLCA", "VectorWidth",
                         "WorkGroupMapping", "GlobalSplitU"}
        covered = {k for knobs in legality.KNOB_GROUPS.values() for k in knobs}
        self.assertTrue(covered - lattice_knobs)

    def test_grvw_is_not_emitted(self):
        # Not a Tensile parameter; BenchmarkStructs printExit()s on unknown names.
        res = synthesis.synthesize_cell(REPO, "SS", draws=6, seed=11,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            self.assertNotIn("grvw", cand["knobs"])
            self.assertNotIn("GlobalReadVectorWidth", cand["knobs"])

    def test_every_family_with_support_yields_a_candidate(self):
        swept = 0
        for family in FAMILY_DTYPES:
            if not legality.shipped_support(REPO, family):
                continue
            res = synthesis.synthesize_cell(REPO, family, draws=3, seed=12,
                                            shape="128x128x128")
            if res["candidates"]:
                swept += 1
        self.assertGreater(swept, 0)


class SweepAcrossFamiliesTests(unittest.TestCase):
    def test_sampling_does_not_raise_for_any_supported_family(self):
        for family in FAMILY_DTYPES:
            if not legality.shipped_support(REPO, family):
                continue
            synthesis.synthesize_cell(REPO, family, draws=1, seed=13,
                                      shape="128x128x128")

    def test_sampling_is_reproducible_for_a_seed(self):
        a = synthesis.synthesize_cell(REPO, "SS", draws=5, seed=99,
                                      shape="128x128x128")
        b = synthesis.synthesize_cell(REPO, "SS", draws=5, seed=99,
                                      shape="128x128x128")
        self.assertEqual([c["knobs"] for c in a["candidates"]],
                         [c["knobs"] for c in b["candidates"]])


class BandResolutionTests(unittest.TestCase):
    """Regression: construction must not reach for the band.

    `ab_audit.arm_record_sets` builds a ConvergenceAgent to manage phases, and
    `coverage.measured_band_pct` calls `arm_record_sets`. So resolving the band
    inside `__init__` is a cycle -- measured_band_pct -> agent -> agent -- and it
    terminates only by exhausting the stack.
    """

    def _agent(self, **kw):
        import agent
        return agent.ConvergenceAgent(
            Path(kw.pop("base", REPO)), scheduler=None, analytics=None, **kw)

    def test_construction_does_not_call_the_audit(self):
        calls = []
        real = coverage.measured_band_pct

        def spy(base_dir):
            calls.append(base_dir)
            return 18.29

        coverage.measured_band_pct = spy
        try:
            self._agent()
        finally:
            coverage.measured_band_pct = real
        self.assertEqual(calls, [])

    def test_a_supplied_band_is_used_without_any_lookup(self):
        calls = []
        real = coverage.measured_band_pct
        coverage.measured_band_pct = lambda b: calls.append(b)
        try:
            a = self._agent(band_pct=12.5)
            self.assertEqual(a.band(), 12.5)
        finally:
            coverage.measured_band_pct = real
        self.assertEqual(calls, [])

    def test_the_band_is_looked_up_at_most_once(self):
        calls = []
        real = coverage.measured_band_pct

        def spy(base_dir):
            calls.append(base_dir)
            return 18.29

        coverage.measured_band_pct = spy
        try:
            a = self._agent()
            self.assertEqual(a.band(), 18.29)
            self.assertEqual(a.band(), 18.29)
        finally:
            coverage.measured_band_pct = real
        self.assertEqual(len(calls), 1)

    def test_a_failing_lookup_yields_no_band_rather_than_raising(self):
        real = coverage.measured_band_pct

        def boom(base_dir):
            raise RuntimeError("no arm data")

        coverage.measured_band_pct = boom
        try:
            self.assertIsNone(self._agent().band())
        finally:
            coverage.measured_band_pct = real

    def test_a_lookup_failure_is_remembered(self):
        calls = []
        real = coverage.measured_band_pct

        def boom(base_dir):
            calls.append(base_dir)
            raise RuntimeError("no arm data")

        coverage.measured_band_pct = boom
        try:
            a = self._agent()
            a.band()
            a.band()
        finally:
            coverage.measured_band_pct = real
        self.assertEqual(len(calls), 1)

    def test_reentrancy_returns_no_band_instead_of_recursing(self):
        # The nested agent is what `arm_record_sets` builds; asking it for the
        # band mid-audit must not start the cycle again.
        a = self._agent()
        a._band_computing = True
        self.assertIsNone(a.band())

    def test_constructing_an_agent_from_the_audit_path_terminates(self):
        # The end-to-end shape of the cycle, with a depth limit standing in for
        # the stack: if __init__ ever reaches the audit again this raises.
        sys.setrecursionlimit(200)
        try:
            self._agent()
        finally:
            sys.setrecursionlimit(1000)


class AgentWiringTests(unittest.TestCase):
    """Hplan.6 step 3 end to end: the sweep must reach the overlay.

    The sampler is stubbed here. Its internals are covered above; what is new and
    easy to get wrong is the wiring -- that the sweep replaces `[shape]`, that
    the ledger's single `shape` column still holds the *cell* so coverage joins
    stay 1:1, and that a retired cell is skipped instead of re-searched.
    """

    DECK = """\
- phase_id: phase_sweep_a
  label: sweep_a
  shapes: ['256x256x256', '512x512x512', '1024x1024x1024']
  config:
    FamilyLabel: SS
    MacroTile: 64x64x16
"""

    WINNERS = {
        "ss_128x128x128": {
            "family": "SS", "dtype": "s", "shape": "128x128x128",
            "fp": "parentfp", "median_gflops": 12.0,
            "config": {"MacroTile": "64x64x16", "ThreadTile": "4x4"},
        }
    }

    SWEEP = ["256x256x256", "512x512x512", "1024x1024x1024"]

    def setUp(self):
        import shutil
        import tempfile

        from analytics import AnalyticsEngine
        from mutator import Mutator
        from registry import SQLiteRegistry

        self.tmp = Path(tempfile.mkdtemp(prefix="oto_p4_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "phases.yaml").write_text(self.DECK)
        self.registry = SQLiteRegistry(self.tmp)
        self.analytics = AnalyticsEngine(self.registry, self.tmp)
        self.mutator = Mutator(self.registry, self.tmp, self.analytics)

    def _agent(self):
        import agent
        return agent.ConvergenceAgent(
            self.tmp, StubGenerator([]), self.analytics, mutator=self.mutator,
            band_pct=18.29)

    def _stub(self, **over):
        result = {"candidates": [{"knobs": {"MacroTile": "64x64x16"},
                                  "groups": ("tile",)}],
                  "source": "manifest_sampler", "dropped": {},
                  "shapes": list(self.SWEEP), "graded": True, "family": "SS"}
        result.update(over)
        return result

    def _overlay_entries(self):
        entries = []
        for p in (self.tmp / "gfx90c_results" / "overlays").glob("*.yaml"):
            entries += ((yaml.safe_load(p.read_text()) or {}).get("phases")
                        or [])
        return entries

    def test_the_sweep_replaces_the_single_shape(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            emitted = a.mutate_and_feed(self.WINNERS)
        self.assertEqual(emitted[0].shapes, self.SWEEP)

    def test_the_overlay_phase_is_flagged_graded(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            a.mutate_and_feed(self.WINNERS)
        entries = self._overlay_entries()
        self.assertTrue(entries, "no overlay phase was written")
        self.assertTrue(all(e.get("graded") for e in entries))
        self.assertTrue(all(len(e.get("shapes") or []) >= 2 for e in entries))

    def test_the_overlay_sweep_matches_the_deck_sweep(self):
        # Asserted against the file rather than the in-memory candidate: the file
        # is what port_tensile actually merges into the run.
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            a.mutate_and_feed(self.WINNERS)
        self.assertEqual(self._overlay_entries()[0]["shapes"], self.SWEEP)

    def test_the_ledger_shape_stays_the_cell_not_the_sweep(self):
        # Coverage joins on (family, shape). Recording the sweep's first shape
        # would silently re-file the candidate into a different cell.
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            emitted = a.mutate_and_feed(self.WINNERS)
        row = self.registry.get_proposal(emitted[0].fingerprint)
        self.assertEqual(row["shape"], "128x128x128")
        self.assertEqual(row["family"], "SS")

    def test_a_lone_shape_is_reported_as_ungraded(self):
        a = self._agent()
        stub = self._stub(shapes=["128x128x128"], graded=False)
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=stub):
            emitted = a.mutate_and_feed(self.WINNERS)
        self.assertEqual(emitted[0].shapes, ["128x128x128"])
        self.assertEqual(a.last_emission_stats["ungraded_cells"],
                         ["ss_128x128x128"])

    def test_a_missing_sweep_does_not_invent_shapes(self):
        a = self._agent()
        stub = self._stub(shapes=[], graded=False)
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=stub):
            emitted = a.mutate_and_feed(self.WINNERS)
        self.assertEqual(emitted[0].shapes, ["128x128x128"])

    def test_a_lattice_fallback_is_reported(self):
        # A run that quietly fell back looks identical to one that did not unless
        # it is surfaced.
        a = self._agent()
        stub = self._stub(source="lattice", fallback_reason="no shipped support")
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=stub):
            a.mutate_and_feed(self.WINNERS)
        self.assertEqual(a.last_emission_stats["lattice_fallback_cells"],
                         ["ss_128x128x128"])

    def test_a_retired_cell_is_skipped(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()), \
             mock.patch.object(type(a), "_cell_coverage_state",
                               return_value=coverage.STATE_RETIRED):
            emitted = a.mutate_and_feed(self.WINNERS)
        self.assertEqual(emitted, [])
        self.assertEqual(a.last_emission_stats["retired_cells"],
                         ["ss_128x128x128"])

    def test_a_retired_cell_is_never_proposed(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()), \
             mock.patch.object(type(a), "_cell_coverage_state",
                               return_value=coverage.STATE_RETIRED):
            a.mutate_and_feed(self.WINNERS)
        self.assertEqual(self.registry.proposed_fps(), set())

    def test_explore_and_replicate_cells_are_sampled(self):
        for state in (coverage.STATE_EXPLORE, coverage.STATE_REPLICATE):
            with self.subTest(state=state):
                a = self._agent()
                with mock.patch.object(Mutator, "sample_cell_synthesized",
                                       return_value=self._stub()) as m, \
                     mock.patch.object(type(a), "_cell_coverage_state",
                                       return_value=state):
                    a.mutate_and_feed(self.WINNERS)
                self.assertEqual(m.call_count, 1)
                self.assertEqual(a.last_emission_stats["retired_cells"], [])

    def test_the_cell_state_is_recorded_on_the_phase(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()), \
             mock.patch.object(type(a), "_cell_coverage_state",
                               return_value=coverage.STATE_REPLICATE):
            a.mutate_and_feed(self.WINNERS)
        self.assertEqual(self._overlay_entries()[0]["coverage_state"],
                         coverage.STATE_REPLICATE)

    def test_the_band_is_passed_to_the_sampler(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()) as m:
            a.mutate_and_feed(self.WINNERS)
        self.assertEqual(m.call_args.kwargs["band_pct"], 18.29)

    def test_the_sweep_is_read_from_the_deck_not_constructed(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()) as m:
            a.mutate_and_feed(self.WINNERS)
        self.assertEqual(m.call_args.kwargs["sweeps"]["SS"], self.SWEEP)

    def test_an_unmeasurable_band_still_emits(self):
        # No band means no guidance, not a failure and not a guess: the sampler
        # is told None and excludes nothing.
        import agent as agent_mod
        real = coverage.measured_band_pct

        def boom(base_dir):
            raise RuntimeError("no arm data")

        coverage.measured_band_pct = boom
        try:
            a = agent_mod.ConvergenceAgent(
                self.tmp, StubGenerator([]), self.analytics, mutator=self.mutator)
            with mock.patch.object(Mutator, "sample_cell_synthesized",
                                   return_value=self._stub()) as m:
                emitted = a.mutate_and_feed(self.WINNERS)
            self.assertTrue(emitted)
            self.assertIsNone(m.call_args.kwargs["band_pct"])
        finally:
            coverage.measured_band_pct = real

    def test_the_band_is_resolved_lazily_and_passed(self):
        # Not supplied at construction, yet the sampler still receives it.
        import agent as agent_mod
        a = agent_mod.ConvergenceAgent(
            self.tmp, StubGenerator([]), self.analytics, mutator=self.mutator)
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()) as m:
            a.mutate_and_feed(self.WINNERS)
        self.assertIsInstance(m.call_args.kwargs["band_pct"], float)


if __name__ == "__main__":
    unittest.main()