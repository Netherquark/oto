#!/usr/bin/env python3
"""Option H Phase 4 (``Hplan.6``): coverage-guided constrained synthesis.

Step 1 — coverage-guided sampling replaces the lattice walk, and the lattice
remains a deterministic fallback so behaviour degrades rather than fails; and
step 2 — the sampler only proposes manifest-legal values for the extended
knobs. See ``tests/test_synthesis_sweep.py`` and
``tests/test_synthesis_band_wiring.py``.
"""
import collections
import random
import unittest
from pathlib import Path

import oto.metrics.coverage as coverage
import oto.tensile.legality as legality
import oto.tensile.synthesis.manifest as synthesis
from oto.device import loader as _loader

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

class CoverageGuidanceTests(unittest.TestCase):
    def _cell(self, groups, spread=0.9):
        return {"per_fp": [{"fp": "a", "spread_ratio": spread, "groups": groups}]}

    def test_an_unstable_group_is_excluded(self):
        cell = self._cell(["split"])
        picks = collections.Counter()
        rng = random.Random(0)
        for _ in range(400):
            picks.update(synthesis.choose_groups(cell, 2, rng, band_pct=10.0))
        assert picks["split"] == 0
        assert picks["tile"] > 0

    def test_without_a_band_nothing_is_excluded(self):
        # Guessing a threshold is how a sampler starts avoiding knobs for no
        # reason at all.
        cell = self._cell(["split"])
        picks = collections.Counter()
        rng = random.Random(0)
        for _ in range(400):
            picks.update(synthesis.choose_groups(cell, 2, rng, band_pct=None))
        assert picks["split"] > 0

    def test_a_stable_config_does_not_exclude_its_groups(self):
        cell = self._cell(["split"], spread=0.01)
        picks = collections.Counter()
        rng = random.Random(0)
        for _ in range(400):
            picks.update(synthesis.choose_groups(cell, 2, rng, band_pct=10.0))
        assert picks["split"] > 0

    def test_an_unknown_group_name_is_ignored(self):
        cell = self._cell(["not_a_group"])
        picks = synthesis.choose_groups(cell, 2, random.Random(0), band_pct=10.0)
        assert set(picks) <= set(synthesis.ALL_GROUPS)

    def test_no_cell_means_no_guidance(self):
        picks = synthesis.choose_groups(None, 2, random.Random(0), band_pct=10.0)
        assert set(picks) <= set(synthesis.ALL_GROUPS)

    def test_excluding_everything_still_returns_a_draw(self):
        # A cell unstable in every group is unstable everywhere; returning
        # nothing would let the caller report it as unexplored.
        cell = self._cell(list(synthesis.ALL_GROUPS))
        picks = synthesis.choose_groups(cell, 2, random.Random(0), band_pct=1.0)
        assert picks

    def test_the_requested_width_is_honoured(self):
        for n in (1, 2, 3):
            picks = synthesis.choose_groups(None, n, random.Random(1),
                                            band_pct=10.0)
            assert len(picks) == min(n, len(synthesis.ALL_GROUPS))

    def test_draws_are_reproducible_for_a_seed(self):
        a = synthesis.choose_groups(self._cell(["split"]), 2,
                                    random.Random(5), band_pct=10.0)
        b = synthesis.choose_groups(self._cell(["split"]), 2,
                                    random.Random(5), band_pct=10.0)
        assert sorted(a) == sorted(b)

    def test_unknown_groups_never_appear(self):
        for seed in range(20):
            picks = synthesis.choose_groups(None, 3, random.Random(seed),
                                            band_pct=10.0)
            assert set(picks) <= set(legality.KNOB_GROUPS)


class SynthesisDrawTests(unittest.TestCase):
    def test_candidates_are_wall_clean(self):
        # Structural legality, asserted without validate_config: leaning on the
        # assertion the sampler is supposed to precede passes for the wrong reason.
        res = synthesis.synthesize_cell(
            REPO, "SS", base_config={"MacroTile": "64x64x16"},
            groups=2, draws=8, seed=3, shape="128x128x128")
        assert res["candidates"]
        for cand in res["candidates"]:
            cfg = {"Architecture": "gfx90c", "DataType": "S",
                   "ProblemType": "Contraction", **cand["knobs"]}
            ok, reason = legality.check_hard_walls(cfg)
            assert ok, f"{reason}: {cfg}"

    def test_every_candidate_tiles(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=8, seed=4,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            assert synthesis.tile_product_holds(cand["knobs"]), cand["knobs"]

    def test_template_keys_are_never_emitted(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=6, seed=5,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            assert not set(cand["knobs"]) & set(synthesis.TEMPLATE_KEYS)

    def test_drawn_groups_are_reported(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=6, seed=6,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            assert set(cand["groups"]) <= set(synthesis.ALL_GROUPS)

    def test_a_family_with_no_support_yields_nothing_and_says_why(self):
        res = synthesis.synthesize_cell(REPO, "QQ", draws=4, seed=0,
                                        shape="128x128x128")
        assert res["candidates"] == []
        assert "QQ" in " ".join(res["dropped"])

    def test_the_sweep_is_reported_and_flagged_graded(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        res = synthesis.synthesize_cell(REPO, "SS", draws=2, seed=7,
                                        shape="128x128x128", sweeps=sweeps)
        assert len(res["shapes"]) == 4
        assert res["graded"]

    def test_a_single_shape_is_reported_as_ungraded(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=2, seed=8,
                                        shape="128x128x128", sweeps={})
        assert not res["graded"]

    def test_the_cell_state_is_reported(self):
        cell = {"n_proposed": 1, "n_distinct_fp": 1, "min_n": 0,
                "outcomes": {"non_functional": 1}, "per_fp": []}
        res = synthesis.synthesize_cell(REPO, "SS", cell=cell, draws=1, seed=0,
                                        shape="128x128x128")
        assert res["state"] == coverage.STATE_RETIRED

    def test_zero_draws_is_honoured(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=0, seed=0,
                                        shape="128x128x128")
        assert res["candidates"] == []

    def test_source_names_the_sampler(self):
        res = synthesis.synthesize_cell(REPO, "SS", draws=2, seed=1,
                                        shape="128x128x128")
        assert res["source"] == "manifest_sampler"


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
        assert out["source"] == "lattice"
        assert len(out["candidates"]) == 1

    def test_the_lattice_is_not_used_when_the_sampler_works(self):
        out = synthesis.synthesize_or_lattice(
            self._synth_some, self._lattice, "SS")
        assert out["source"] == "manifest_sampler"

    def test_the_fallback_reason_is_kept(self):
        # A run that fell back must be distinguishable from one that did not.
        out = synthesis.synthesize_or_lattice(
            self._synth_none, self._lattice, "QQ")
        assert "no shipped support" in str(out["fallback_reason"])

    def test_fallback_candidates_have_no_group_attribution(self):
        # The lattice does not say which group it moved, so claiming one would be
        # a fabricated attribution feeding coverage guidance.
        out = synthesis.synthesize_or_lattice(
            self._synth_none, self._lattice, "QQ")
        assert out["candidates"][0]["groups"] is None

    def test_neither_source_yields_unavailable(self):
        out = synthesis.synthesize_or_lattice(
            self._synth_none, lambda *a, **k: [], "QQ")
        assert out["source"] == "unavailable"
        assert out["candidates"] == []

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
        assert "cell" not in seen
        assert seen["shape"] == "128x128x128"


class KnobSpaceTests(unittest.TestCase):
    """Step 2: the knob space is exhausted at the manifest, not merely narrow."""

    def test_the_sampler_covers_every_legal_knob(self):
        covered = set()
        for knobs in legality.KNOB_GROUPS.values():
            covered |= set(knobs)
        assert covered == {"MacroTile", "ThreadTile", "WorkGroup", "VectorWidth", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB", "GlobalSplitU", "DepthU"}

    def test_no_group_is_empty(self):
        for name, knobs in legality.KNOB_GROUPS.items():
            assert knobs, name

    def test_groups_do_not_overlap(self):
        # Overlapping groups would make a "2-group" draw move fewer than two
        # independent things, and the width would be a lie.
        seen = set()
        for knobs in legality.KNOB_GROUPS.values():
            assert not seen & set(knobs), f"overlap on {seen & set(knobs)}"
            seen |= set(knobs)

    def test_the_sampler_exceeds_the_lattice_knob_set(self):
        lattice_knobs = {"MacroTile", "ThreadTile", "NLCA", "VectorWidth",
                         "WorkGroupMapping", "GlobalSplitU"}
        covered = {k for knobs in legality.KNOB_GROUPS.values() for k in knobs}
        assert covered - lattice_knobs

    def test_grvw_is_not_emitted(self):
        # Not a Tensile parameter; BenchmarkStructs printExit()s on unknown names.
        res = synthesis.synthesize_cell(REPO, "SS", draws=6, seed=11,
                                        shape="128x128x128")
        for cand in res["candidates"]:
            assert "grvw" not in cand["knobs"]
            assert "GlobalReadVectorWidth" not in cand["knobs"]

    def test_every_family_with_support_yields_a_candidate(self):
        swept = 0
        for family in _loader.current_profile().family_dtypes:
            if not legality.shipped_support(REPO, family):
                continue
            res = synthesis.synthesize_cell(REPO, family, draws=3, seed=12,
                                            shape="128x128x128")
            if res["candidates"]:
                swept += 1
        assert swept > 0


class SweepAcrossFamiliesTests(unittest.TestCase):
    def test_sampling_does_not_raise_for_any_supported_family(self):
        for family in _loader.current_profile().family_dtypes:
            if not legality.shipped_support(REPO, family):
                continue
            synthesis.synthesize_cell(REPO, family, draws=1, seed=13,
                                      shape="128x128x128")

    def test_sampling_is_reproducible_for_a_seed(self):
        a = synthesis.synthesize_cell(REPO, "SS", draws=5, seed=99,
                                      shape="128x128x128")
        b = synthesis.synthesize_cell(REPO, "SS", draws=5, seed=99,
                                      shape="128x128x128")
        assert [c["knobs"] for c in a["candidates"]] == [c["knobs"] for c in b["candidates"]]
