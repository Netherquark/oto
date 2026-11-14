#!/usr/bin/env python3
"""test_donor_mutator.py — the DB-hooked mutator synthesises novel, wide+narrow.

The DB-hooked mutator re-combines measured tile donors with the
wall families; these tests pin the replacement's guarantees:

  * synthesis returns the requested number of mutants for the CC/ZZ wall
    families (the ones the old arm never touched);
  * every mutant is gate-legal (validate_config + ldspad_feasible) and novel
    against the ledger;
  * mutants carry forward knobs (pads/PGR/NLCA/WGM/StaggerU/GLVW) that the
    manifest sampler cannot reach — the large space that guarantees novelty
    across iterations;
  * wide mutants include DB tile donors (measured winners), not just the
    parent's own tile;
  * mutant phase entries carry bypass_identical_skip (no auto-skip on
    mutations).

CPU only; no Tensile, no GPU. A stub mutator owns novelty so the synthesis
logic is exercised without a live registry.
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.tensile.candidate import CandidateGenerator
from oto.tensile.gates.occupancy import ldspad_feasible
from oto.tensile.synthesis.donor_mutator import FORWARD_KNOB_DOMAINS, DBMutator


class _StubMutator:
    """Ledger-backed mutator stand-in: everything novel, ledger available."""

    def __init__(self):
        self.emitted = []

    def is_novel(self, fp):
        return fp not in self.emitted

    def ledger_available(self):
        return True


class TestDBMutatorSynthesis(unittest.TestCase):
    def setUp(self):
        self.mutator = _StubMutator()
        self.db = DBMutator(REPO, self.mutator)
        assert self.db.has_db(), "kernel_db.json must load"
        self.sched = CandidateGenerator(REPO, registry=None)

    def _assert_legal_and_novel(self, family, knobs):
        cfg = {**self.db._template(family), **knobs}
        ok, why = self.sched.validate_config(cfg)
        assert ok, f"{knobs}: {why}"
        ok, why = ldspad_feasible(cfg)
        assert ok, f"{knobs}: {why}"
        from oto.ledger.registry import fingerprint_config
        assert self.mutator.is_novel(fingerprint_config(cfg))

    def test_wall_families_get_mutants(self):
        """CC/ZZ (the wall families the old arm starved) synthesise mutants."""
        for family, parent in (
            ("CC", {"MacroTile": "64x64x8", "ThreadTile": "4x4",
                    "VectorWidth": 2, "GlobalSplitU": 1, "DepthU": 8}),
            ("ZZ", {"MacroTile": "32x32x16", "ThreadTile": "2x2",
                    "VectorWidth": 1, "GlobalSplitU": 1, "DepthU": 16}),
        ):
            mutants = self.db.synthesize_mutants(
                family, parent, "256x256x256", random.Random("t"), n=8)
            assert len(mutants) == 8, family
            for mut in mutants:
                self._assert_legal_and_novel(family, mut)

    def test_mutants_carry_forward_knobs(self):
        """Forward knobs (pads/PGR/NLCA/WGM/StaggerU/GLVW) appear — the axes
        the manifest sampler cannot touch."""
        parent = {"MacroTile": "64x64x8", "ThreadTile": "4x4",
                  "VectorWidth": 2, "GlobalSplitU": 1, "DepthU": 8}
        mutants = self.db.synthesize_mutants(
            "CC", parent, "256x256x256", random.Random("t"), n=8)
        touched = set()
        for mut in mutants:
            for knob in FORWARD_KNOB_DOMAINS:
                if knob in mut:
                    touched.add(knob)
        # The narrow pass draws single-knob deltas across the forward domain,
        # so several *different* forward knobs must be represented in one
        # batch. Which knobs they are is not fixed: the pass visits them in a
        # seeded shuffle (so an axis late in the dict is not starved), so the
        # durable property is the VARIETY, not a particular set.
        assert len(touched) >= 3, f"only {len(touched)} forward knob(s) represented: {sorted(touched)}"

    def test_wide_mutants_use_db_tile_donors(self):
        """Wide mutants include tiles from the DB's measured winners, not just
        the parent's own tile. SS has the richest tile diversity in the DB."""
        parent = {"MacroTile": "128x128x8", "ThreadTile": "8x8",
                  "VectorWidth": 4, "GlobalSplitU": 1, "DepthU": 8}
        # Draw enough that the wide pass (priority 0.6) is reached.
        mutants = self.db.synthesize_mutants(
            "SS", parent, "256x256x256", random.Random("t"), n=40)
        tiles = {mut.get("MacroTile") for mut in mutants}
        # The parent's tile plus at least one donor tile from the DB.
        assert len(tiles) > 1, f"only {tiles}"
        assert "128x128x8" in tiles

    #: The narrow pass scores every single-knob delta at priority 1.0, so a
    #: small `n` is filled by the first knobs in dict order and GlobalSplitU
    #: (13th) is never reached. Measured: at n=24 no mutant carries it at all,
    #: at n=40 SS offers the full {1,2,4}. Use 40, and assert the axis was
    #: actually seen -- otherwise these tests pass vacuously.
    _GSU_N = 40

    def _offered_gsu(self, family, seeds=12):
        """Every GlobalSplitU value the mutator offers this family."""
        parent = {"MacroTile": "64x64x8", "ThreadTile": "4x4",
                  "VectorWidth": 2, "GlobalSplitU": 1, "DepthU": 8}
        offered = set()
        for seed in range(seeds):
            for mut in self.db.synthesize_mutants(
                    family, parent, "256x256x256", random.Random(seed),
                    n=self._GSU_N):
                if "GlobalSplitU" in mut:
                    offered.add(mut["GlobalSplitU"])
        return offered

    def test_gsu_above_one_is_never_offered_where_it_cannot_run(self):
        """The mutator must not spend draws on a knob value that cannot run.

        Tensile (SolutionStructs:3553) allows GlobalSplitU>1 only for single,
        8-bit float, double-with-BufferStore, Assembly-with-half-accumulate,
        `_GlobalAccumulation`, or MFMA. gfx90c has no MFMA, so on complex
        (CC/ZZ) and on half-with-f32-accumulate (HH_HPA/HS_HPA) it is
        structurally impossible. HH is *hardware*-legal but banned by decision,
        because GSU>1 on half Assembly also needs
        AssertFree0ElementMultiple>=2 and the HH deck ships AF0EM=1.

        This is a domain restriction, so it must hold on every path that draws a
        knob -- the narrow single-knob deltas and the wide forward draws alike.
        """
        for family in ("CC", "ZZ", "HH", "HH_HPA", "HS_HPA"):
            with self.subTest(family=family):
                offered = self._offered_gsu(family)
                assert offered - {1} == set(), f"{family} was offered GlobalSplitU {sorted(offered)}, " f"none of which can run on this device"

    def test_the_banned_gsu_test_is_not_vacuous(self):
        """Guard the guard.

        If the axis is never reached, `offered` is empty and the test above
        passes while proving nothing. Pin that the families *do* see a GSU draw,
        so a future change to the sampling budget cannot silently neuter it.
        """
        for family in ("CC", "ZZ", "HH", "HH_HPA", "HS_HPA"):
            with self.subTest(family=family):
                assert self._offered_gsu(family), f"{family} never saw a GlobalSplitU draw at " f"n={self._GSU_N}, so the ban is untested rather than held"

    def test_gsu_axis_survives_where_it_is_legal(self):
        """The restriction must not have sterilised the families that can use it.

        A fix that quietly emptied SS's and DD's GSU axis would pass the ban
        test above while removing the search dimension the run depends on.
        """
        for family in ("SS", "DD"):
            with self.subTest(family=family):
                assert self._offered_gsu(family) - {1}, f"{family} lost its GlobalSplitU axis entirely; the fix " f"should only remove values that cannot run"

    def test_novelty_is_guaranteed_not_remeasured(self):
        """A mutant is never a config the ledger has already decided. Recording
        each emission and re-synthesizing must yield only novel fps — the
        forward-knob space is large enough that the arm never has to repeat."""
        parent = {"MacroTile": "64x64x8", "ThreadTile": "4x4",
                  "VectorWidth": 2, "GlobalSplitU": 1, "DepthU": 8}
        from oto.ledger.registry import fingerprint_config
        seen = set()
        for seed in ("a", "b", "c", "d"):
            for mut in self.db.synthesize_mutants(
                    "CC", parent, "256x256x256", random.Random(seed), n=8):
                cfg = {**self.db._template("CC"), **mut}
                fp = fingerprint_config(cfg)
                assert fp not in seen
                seen.add(fp)
                # Record the emission so the next pass must avoid it.
                self.mutator.emitted.append(fp)
        # 4 seeds x 8 mutants, all distinct.
        assert len(seen) >= 32


#: One deck-realistic parent per family: the tile shape the family's shipped
#: winners actually use (MacroTile x ThreadTile x VectorWidth, DepthU).
PARENTS = {
    "SS": {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 4,
           "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
           "GlobalLoadVectorWidthA": 4, "GlobalLoadVectorWidthB": 4},
    "DD": {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
           "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
           "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2},
    "CC": {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2,
           "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
           "GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2},
    "ZZ": {"MacroTile": "32x32x8", "ThreadTile": "2x2", "VectorWidth": 1,
           "DepthU": 8, "GlobalSplitU": 1, "WorkGroupMapping": 4,
           "GlobalLoadVectorWidthA": 1, "GlobalLoadVectorWidthB": 1},
    "HH": {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 8,
           "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 4,
           "GlobalLoadVectorWidthA": 8, "GlobalLoadVectorWidthB": 8},
    "HH_HPA": {"MacroTile": "64x128x16", "ThreadTile": "4x8", "VectorWidth": 4,
               "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 4,
               "GlobalLoadVectorWidthA": 4, "GlobalLoadVectorWidthB": 4},
    "HS_HPA": {"MacroTile": "128x64x16", "ThreadTile": "8x4", "VectorWidth": 4,
               "DepthU": 16, "GlobalSplitU": 1, "WorkGroupMapping": 4,
               "GlobalLoadVectorWidthA": 4, "GlobalLoadVectorWidthB": 4},
}


class TestDrawsAreJointlyLegal(unittest.TestCase):
    """Every draw is gate-clean *before* it is offered, not filtered after.

    Triage of the campaign ledger (docs/potential_configs.md §R23): every candidate
    the launch boundary ever refused was a *joint* violation -- a forward-knob
    value that is legal on its own but not beside the rest of the tile
    (GlobalLoadVectorWidth outside {VectorWidth, 1}, an LDS-budget overrun, an
    illegal GlobalSplitU class, an NLCA above the tile's load count). The
    domains are independent by construction; Tensile's legal set is not.

    So the samplers must draw the joint subset. These tests pin that, and pin
    that the joint filter removes only what the gates refuse.
    """

    def setUp(self):
        self.mutator = _StubMutator()
        self.db = DBMutator(REPO, self.mutator)
        self.sched = CandidateGenerator(REPO, registry=None)

    def _assert_legal(self, family, parent, draw):
        cfg = {**self.db._template(family), **parent, **draw}
        ok, why = self.sched.validate_config(cfg)
        assert ok, f"{family} {draw}: {why}"
        ok, why = ldspad_feasible(cfg)
        assert ok, f"{family} {draw}: {why}"

    def test_forward_draws_are_jointly_legal(self):
        """No wide-forward draw is a config the launch boundary would refuse."""
        for family, parent in PARENTS.items():
            with self.subTest(family=family):
                for seed in range(40):
                    for draw in self.db._forward_draws(
                            random.Random(seed), parent, family):
                        self._assert_legal(family, parent, draw)

    def test_joint_domain_is_a_subset_of_the_forward_domain(self):
        """The filter narrows; it never invents a value the family may not draw."""
        from oto.tensile.synthesis.donor_knobs import (
            FORWARD_KNOB_DOMAINS,
            forward_domain,
        )
        for family, parent in PARENTS.items():
            for knob in FORWARD_KNOB_DOMAINS:
                with self.subTest(family=family, knob=knob):
                    joint = set(self.db._joint_domain(family, knob, parent))
                    assert joint <= set(forward_domain(family, knob))

    def test_joint_domain_pins_the_measured_couplings(self):
        """The three couplings the ledger actually refused, pinned by value.

        Each of these is a value the *naive* independent draw still offers:
        the assertion is only meaningful because the full domain is wider.
        """
        from oto.tensile.synthesis.donor_knobs import forward_domain

        # GlobalLoadVectorWidth must be the tile's VectorWidth or 1
        # (SolutionStructs:4583-4596): 2 is offered by the SS domain and
        # refused beside VectorWidth 4.
        assert 2 in forward_domain("SS", "GlobalLoadVectorWidthA")
        assert self.db._joint_domain("SS", "GlobalLoadVectorWidthA", PARENTS["SS"]) == (1, 4)

        # NLCA must divide the tile's load count (SolutionStructs:2058). A
        # 128x128x8 tile at ThreadTile 8x8 / VectorWidth 4 has exactly one
        # load per operand, so {2,3} -- two thirds of the domain -- is refused.
        # -1 is Tensile's "least coalesced" value (Common.py:1323 allows
        # range(-1, 65)) and is legal here: with one load it degenerates to
        # the same single load.
        assert forward_domain("SS", "NLCA") == (-1, 1, 2, 3)
        assert self.db._joint_domain("SS", "NLCA", PARENTS["SS"]) == (-1, 1)

        # The StaggerU trio moves as one (SolutionStructs:3326-3342): the
        # parent's absent StaggerU means Tensile's default 32 ("stagger on"),
        # so StaggerUStride=0 -- in the domain -- is refused.
        assert 0 in forward_domain("CC", "StaggerUStride")
        assert 0 not in self.db._joint_domain("CC", "StaggerUStride", PARENTS["CC"])

    def test_the_joint_filter_did_not_sterilise_the_coupled_axes(self):
        """Guard the guard, as the GlobalSplitU ban tests do.

        A filter that emptied GLVW or DepthU for every family would pass the
        legality tests above while removing search dimensions the run depends
        on. Pin that both still vary for the families the ledger refused.
        """
        for family in ("SS", "HH", "HH_HPA"):
            for knob in ("GlobalLoadVectorWidthA", "DepthU"):
                with self.subTest(family=family, knob=knob):
                    assert len(self.db._joint_domain(family, knob, PARENTS[family])) > 1, f"{family} lost its {knob} axis entirely"

    def test_a_wide_draw_never_lands_on_a_refused_config(self):
        """End-to-end: the synthesiser's whole output is legal, by construction
        and not merely by the ``_gate`` filter that follows it."""
        for family, parent in PARENTS.items():
            with self.subTest(family=family):
                mutants = self.db.synthesize_mutants(
                    family, parent, "256x256x256", random.Random("t"), n=8)
                assert len(mutants) == 8, family
                for mut in mutants:
                    self._assert_legal(family, parent, mut)


if __name__ == "__main__":
    unittest.main()
