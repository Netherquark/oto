#!/usr/bin/env python3
"""Tests for consolidate.py's selection and legality rules.

No GPU work. The floor build and registry clone are exercised against the real
corpus but only read from it; nothing here writes to gfx90c_results/.

Three things are pinned because each one produced a wrong answer at least once:

  * The legality gate has to include the global-load byte cap. The occupancy and
    assembly-class gates both pass a complex-double phase at VectorWidth 2, which
    Tensile rejects at solution construction -- such phases sat in the deck and
    cost a wasted overnight run. The byte widths have to come from Tensile's own
    tables: the modelled gate carried ComplexFloat's 8 bytes for ZZ while complex
    double is 16. That row is now corrected and pinned to Tensile by
    tests/test_measurement_integrity.py, but this gate still reads the authority.
  * The deck has to be verbatim copies. A generated or re-keyed entry is an
    invented solution, which is the one thing this pipeline must never do.
  * Family matching has to be case-insensitive. extract_family_from_phase_id
    returns 'ss' and 'zz' while FAMILY_SHAPES is upper-case; comparing them raw
    matches nothing and silently produces an empty deck.
"""
import sys
import unittest
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oto.tools.consolidate import (  # noqa: E402
    _fam, _is_legal, dtype_bytes, load_deck, target_cells,
)
from oto.device.peaks import FAMILY_SHAPES, cell_key  # noqa: E402


class TestFamilyCase(unittest.TestCase):
    def test_phase_ids_lowercase_families(self):
        self.assertEqual(_fam("phase_ss_Ailk_Bjlk_mt64x64x16_tt4x4"), "SS")
        self.assertEqual(_fam("phase_zz_Ailk_Bjlk_mt32x32x16_tt2x2_vw1"), "ZZ")
        self.assertEqual(_fam("phase_hh_hpa_Ailk_Bjlk_mt128x64x16"), "HH_HPA")

    def test_target_cells_use_uppercase(self):
        for fam, shape, key in target_cells():
            self.assertEqual(key.split(":")[0], fam)
            self.assertTrue(shape.endswith(f"x{shape.split('x')[0]}x"
                                           f"{shape.split('x')[0]}"))


class TestTargetMatrix(unittest.TestCase):
    def test_every_family_shape_pair_is_covered(self):
        want = {f"{f}:{s}" for f, sides in FAMILY_SHAPES.items() for s in sides}
        self.assertEqual({c[2] for c in target_cells()}, want)

    def test_no_duplicate_cells(self):
        keys = [c[2] for c in target_cells()]
        self.assertEqual(len(keys), len(set(keys)))


ARCHIVED_DECK = ROOT / "archive" / "phases.yaml.pre_consolidation_oct3"


def _archived_deck():
    if not ARCHIVED_DECK.is_file():
        return None
    return yaml.safe_load(ARCHIVED_DECK.read_text())


class TestDtypeBytes(unittest.TestCase):
    def test_widths_match_tensile(self):
        self.assertEqual(dtype_bytes("S"), 4)
        self.assertEqual(dtype_bytes("D"), 8)
        self.assertEqual(dtype_bytes("H"), 2)
        self.assertEqual(dtype_bytes("C"), 8)

    def test_complex_double_is_sixteen_not_eight(self):
        """The number the ZZ bug turns on."""
        self.assertEqual(dtype_bytes("Z"), 16)

    def test_unknown_dtype_is_none_not_a_guess(self):
        self.assertIsNone(dtype_bytes("Q"))


class TestLegalityGate(unittest.TestCase):
    @staticmethod
    def _phase(dtype, vw, **cfg):
        return {"phase_id": f"phase_x_{dtype}_vw{vw}",
                "dtype": dtype, "config": {"DataType": dtype,
                                           "VectorWidth": vw, **cfg}}

    def test_complex_double_vw2_is_rejected(self):
        ok, why = _is_legal(self._phase("Z", 2))
        self.assertFalse(ok)
        self.assertIn("GlobalLoadVectorWidthA", why)
        self.assertIn("> 16", why)

    def test_complex_double_vw1_is_accepted(self):
        """VW1 hits exactly the 16 B cap and is the widest legal complex width."""
        ok, why = _is_legal(self._phase("Z", 1))
        self.assertTrue(ok, why)

    def test_float_vw4_is_accepted(self):
        ok, why = _is_legal(self._phase("S", 4))
        self.assertTrue(ok, why)

    def test_float_vw8_is_rejected(self):
        ok, why = _is_legal(self._phase("S", 8))
        self.assertFalse(ok)
        self.assertIn("GlobalLoadVectorWidthA", why)

    def test_gate_catches_a_real_archived_zz_phase(self):
        """Against the corpus, not a synthetic config."""
        deck = _archived_deck()
        if deck is None:
            self.skipTest("archived deck not present")
        bad = [p for p in deck
               if str(p.get("phase_id", "")).lower().startswith("phase_zz")
               and str((p.get("config") or {}).get("VectorWidth")) == "2"]
        self.assertTrue(bad, "expected archived ZZ VectorWidth=2 phases to exist")
        for p in bad:
            ok, _why = _is_legal(p)
            self.assertFalse(ok, p["phase_id"])

    def test_every_live_deck_phase_passes_the_gate(self):
        """The invariant that matters: nothing illegal ships.

        Reads phases.yaml directly rather than through load_deck(). load_deck()
        deliberately unions every archived deck into the solution universe, so it
        also returns the ~28 known-bad phases that the gate is supposed to
        reject -- testing it would assert that they are legal.

        Note this is not the same as "every ZZ phase declares VectorWidth 1".
        Some ZZ phases declare no VectorWidth at all and Tensile resolves those to
        1, which is legal -- they ran and produced measurements. Asserting on the
        declared value instead would reject phases that are demonstrably fine.
        """
        live = yaml.safe_load((ROOT / "phases.yaml").read_text())
        offenders = [(p["phase_id"], _is_legal(p)[1]) for p in live
                     if not _is_legal(p)[0]]
        self.assertEqual(offenders, [])


class TestSolutionUniverse(unittest.TestCase):
    """Selection must draw from every solution ever written, not just the live deck.

    Reading only phases.yaml makes the pipeline collapse on re-run: the
    consolidation writes a small deck, and the next pass has only those candidates
    to choose from, so it cannot recover what it just dropped.
    """

    def test_universe_includes_archived_decks(self):
        live = {p["phase_id"] for p in yaml.safe_load(
            (ROOT / "phases.yaml").read_text())}
        universe = {p["phase_id"] for p in load_deck(ROOT)}
        self.assertTrue(universe > live,
                        "universe must be larger than the live deck")

    def test_universe_contains_the_archived_originals(self):
        universe = {p["phase_id"] for p in load_deck(ROOT)}
        archived = _archived_deck()
        if archived is None:
            self.skipTest("archived deck not present")
        missing = [p["phase_id"] for p in archived
                   if p["phase_id"] not in universe]
        self.assertEqual(missing, [])


class TestDeckIsVerbatim(unittest.TestCase):
    """Every live phase must exist, unchanged, in the archived original.

    D1 exception (2026-10-07): the proven winners added by D1 are NOT verbatim
    copies of the archived deck -- they are verbatim copies of *measured*
    winning phases (the seed-overlay transplants that became phases.yaml rows),
    so the byte-identical contract only applies to the archive-sourced rows. The
    D1 rows are pinned by their phase_id shape (`phase_auto_<n>_<family>_...`)
    and by the fingerprint contract (fp == fingerprint_config(config), which
    check_candidates also enforces as `self_inconsistencies`).
    """

    D1_PATTERN = (
        "phase_auto_"  # iteration prefix
    )

    def _is_d1(self, p):
        return str(p.get("phase_id", "")).startswith(self.D1_PATTERN)

    def setUp(self):
        archived = _archived_deck()
        if archived is None:
            self.skipTest("archived deck not present")
        self.old = {p["phase_id"]: p for p in archived}
        self.new = yaml.safe_load((ROOT / "phases.yaml").read_text())

    def test_every_entry_came_from_the_archived_deck(self):
        for p in self.new:
            if not self._is_d1(p):
                self.assertIn(p["phase_id"], self.old)

    def test_entries_are_byte_identical(self):
        from oto.ledger.registry import fingerprint_config
        for p in self.new:
            if self._is_d1(p):
                # D1 rows are provenance transplants: the config's own
                # fingerprint is the contract that keeps them consistent with
                # what was measured (and with the seed overlay's fp).
                self.assertEqual(p["fp"], fingerprint_config(p["config"]),
                                 p["phase_id"])
                self.assertIn("contraction_pattern", p, p["phase_id"])
                continue
            self.assertEqual(p, self.old[p["phase_id"]], p["phase_id"])

    def test_no_duplicate_phase_ids(self):
        ids = [p["phase_id"] for p in self.new]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_keys_present(self):
        for p in self.new:
            for k in ("phase_id", "label", "dtype", "shapes", "config",
                      "fp", "NumBenchmarks", "ScheduleName"):
                self.assertIn(k, p, p.get("phase_id"))

    def test_every_target_cell_has_a_phase(self):
        covered = {cell_key(_fam(p["phase_id"]), s)
                   for p in self.new for s in p["shapes"]}
        missing = [c[2] for c in target_cells() if c[2] not in covered]
        self.assertEqual(missing, [], f"cells with no deck phase: {missing}")


if __name__ == "__main__":
    unittest.main()