#!/usr/bin/env python3
"""coverage-guided, tile-legal draws: shape sweeps and MacroTile->ThreadTile
reconciliation.

Two requirements, and the failure each guards against:

* multi-shape family sweeps — a mutant must not be born ungradable;
* ``ThreadTile``/``WorkGroup`` derived from ``MacroTile`` so the
  product constraint holds by construction.
See ``tests/test_synthesis_sampler.py`` for the coverage sampler, and
``tests/test_synthesis_band_wiring.py`` for the band/agent wiring.
"""
import unittest
from pathlib import Path

import oto.tensile.synthesis.pipeline_manifest as synthesis

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
        assert set(sweeps) == {"SS", "ZZ"}

    def test_same_family_shapes_are_unioned(self):
        # Picking one phase's shapes would silently benchmark the mutant over a
        # subset of what the floor was measured over.
        assert synthesis.family_shape_sweeps(DECK)["SS"] == ["256x256x256", "512x512x512", "1024x1024x1024", "768x768x768"]

    def test_sweep_is_deduplicated_order_preserving(self):
        assert len(synthesis.family_shape_sweeps(DECK)["SS"]) == 4

    def test_a_family_without_a_label_is_skipped(self):
        # Not invented under some default family either.
        assert "" not in synthesis.family_shape_sweeps(DECK)
        assert None not in synthesis.family_shape_sweeps(DECK)

    def test_shape_lists_are_normalised_to_text(self):
        sweeps = synthesis.family_shape_sweeps(
            [{"shapes": [[128, 128, 128], [256, 256, 256]],
              "config": {"FamilyLabel": "DD"}}])
        assert sweeps["DD"] == ["128x128x128", "256x256x256"]

    def test_empty_deck_yields_no_sweeps(self):
        assert synthesis.family_shape_sweeps([]) == {}
        assert synthesis.family_shape_sweeps(None) == {}

    def test_a_two_shape_sweep_counts_as_graded(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        assert synthesis.sweep_for_family("ZZ", sweeps)

    def test_a_one_shape_sweep_is_not_graded(self):
        sweeps = {"DD": ["128x128x128"]}
        out = synthesis.sweep_for_family("DD", sweeps,
                                         fallback=["256x256x256"])
        assert out == ["256x256x256"]

    def test_no_sweep_and_no_fallback_stays_single_shape(self):
        # Better than inventing shapes: an ungradable candidate that says so.
        assert synthesis.sweep_for_family("QQ", {}, fallback=None) == []

    def test_fallback_is_used_when_the_family_is_absent(self):
        out = synthesis.sweep_for_family("QQ", synthesis.family_shape_sweeps(DECK),
                                         fallback=["1024x1024x1024"])
        assert out == ["1024x1024x1024"]

    def test_lookup_is_case_insensitive(self):
        sweeps = synthesis.family_shape_sweeps(DECK)
        assert synthesis.sweep_for_family("ss", sweeps) == sweeps["SS"]


class ReconcileTileTests(unittest.TestCase):
    def _tile(self, macro, wg, tt):
        return {"MacroTile": macro, "WorkGroup": wg, "ThreadTile": tt}

    def test_a_consistent_tile_is_untouched(self):
        cfg = self._tile("64x64x16", "16x16x1", "4x4")
        assert synthesis.reconcile_tile(cfg) == cfg

    def test_missing_thread_tile_is_solved_from_workgroup(self):
        out = synthesis.reconcile_tile(
            self._tile("128x64x16", "32x8x1", None))
        assert out["ThreadTile"] == "4x8"

    def test_missing_workgroup_is_solved_from_thread_tile(self):
        out = synthesis.reconcile_tile(
            self._tile("64x32x16", None, "4x4"))
        assert out["WorkGroup"] == "16x8x1"

    def test_a_disagreeing_pair_reconciles_to_the_macrotile(self):
        # Tensile trusts the MacroTile: it has to have a shipped schedule to be
        # valid at all, whereas a ThreadTile that does not tile it is meaningless.
        out = synthesis.reconcile_tile(
            self._tile("64x64x16", "16x16x1", "8x8"))
        assert out["ThreadTile"] == "4x4"

    def test_reconciliation_makes_the_product_hold(self):
        out = synthesis.reconcile_tile(self._tile("64x64x16", "16x16x1", "8x8"))
        assert synthesis.tile_product_holds(out)

    def test_an_unsolved_dimension_never_renders_as_the_string_none(self):
        # Regression: an unsolved dim once formatted as a literal "None", which
        # Tensile rejects at parameter-parse time rather than at our check.
        for wg, tt in (("24x24x1", None), ("32x8x1", None),
                       (None, "8x8"), ("16x16x1", "99x99")):
            out = synthesis.reconcile_tile(
                self._tile("64x64x16", wg, tt))
            for key in ("WorkGroup", "ThreadTile"):
                assert "None" not in out[key], out
                assert all(int(p) >= 1 for p in out[key].split("x"))

    def test_a_non_tileable_pair_is_left_rather_than_guessed(self):
        # 64 % 24 != 0, so there is no integer ThreadTile; inventing one would
        # produce a config that looks reconciled and is not.
        cfg = self._tile("64x64x16", "24x24x1", None)
        assert not synthesis.tile_product_holds(cfg)
        assert not synthesis.tile_product_holds(synthesis.reconcile_tile(cfg))

    def test_a_missing_macrotile_is_a_no_op(self):
        cfg = {"WorkGroup": "16x16x1", "ThreadTile": "4x4"}
        assert synthesis.reconcile_tile(cfg) == cfg

    def test_an_unparseable_macrotile_is_a_no_op(self):
        cfg = self._tile("64", "16x16x1", "4x4")
        assert synthesis.reconcile_tile(cfg) == cfg

    def test_product_check_passes_when_there_is_no_tile_to_check(self):
        assert synthesis.tile_product_holds({"MacroTile": None})

    def test_product_check_fails_when_either_half_is_absent(self):
        assert not synthesis.tile_product_holds({"MacroTile": "64x64x16", "ThreadTile": "4x4"})
        assert not synthesis.tile_product_holds({"MacroTile": "64x64x16", "WorkGroup": "16x16x1"})

    def test_product_check_only_examines_m_and_n(self):
        # K is not part of the constraint Tensile enforces per M/N dimension.
        assert synthesis.tile_product_holds(self._tile("64x64x16", "16x16x4", "4x4"))

    def test_a_zero_dimension_is_treated_as_absent(self):
        # `0x16x1` is not a workgroup. A zero parses to "unset" rather than
        # multiplying out to a spurious zero that trivially matches nothing.
        cfg = self._tile("64x64x16", "0x16x1", "4x4")
        assert not synthesis.tile_product_holds(cfg)
