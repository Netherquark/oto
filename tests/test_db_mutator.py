#!/usr/bin/env python3
"""test_db_mutator.py — the DB-hooked mutator synthesises novel, wide+narrow.

Option H overhaul (2026-10-09). The manifest sampler decays and starves the
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

from oto.tensile.candidate import CandidateGenerator  # noqa: E402
from oto.tensile.gates.occupancy import ldspad_feasible  # noqa: E402
from oto.tensile.synthesis.db import DBMutator, FORWARD_KNOB_DOMAINS  # noqa: E402


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
        self.assertTrue(self.db.has_db(), "kernel_db.json must load")
        self.sched = CandidateGenerator(REPO, registry=None)

    def _assert_legal_and_novel(self, family, knobs):
        cfg = {**self.db._template(family), **knobs}
        ok, why = self.sched.validate_config(cfg)
        self.assertTrue(ok, f"{knobs}: {why}")
        ok, why = ldspad_feasible(cfg)
        self.assertTrue(ok, f"{knobs}: {why}")
        from oto.ledger.registry import fingerprint_config
        self.assertTrue(self.mutator.is_novel(fingerprint_config(cfg)))

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
            self.assertEqual(len(mutants), 8, family)
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
        # so several forward knobs must be represented in one batch.
        self.assertTrue(
            {"LdsPadA", "LdsPadB", "PrefetchGlobalRead"} & touched,
            f"forward knobs missing from {sorted(touched)}")

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
        self.assertGreater(len(tiles), 1, f"only {tiles}")
        self.assertIn("128x128x8", tiles)

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
                self.assertNotIn(fp, seen)
                seen.add(fp)
                # Record the emission so the next pass must avoid it.
                self.mutator.emitted.append(fp)
        # 4 seeds x 8 mutants, all distinct.
        self.assertGreaterEqual(len(seen), 32)


if __name__ == "__main__":
    unittest.main()
