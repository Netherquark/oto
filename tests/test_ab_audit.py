#!/usr/bin/env python3
"""Tests for ab_audit's cross-arm identity and certainty rules.

No GPU work and no corpus reads: these exercise the pure functions that decide
whether two measurements are comparable at all, which is where the corpus
analysis is easy to get quietly wrong.

The bug this file exists for, from the first version of the audit: a floor phase
and a native phase running the same kernel were scored as different kernels, and
two genuinely different kernels were scored as the same one. Both happened at
once, for the same reason -- the identity was built from whatever each side
happened to spell the config differently.

  * Contraction patterns contain an underscore (``Ailk_Bljk``). A character
    class without ``_`` fails to match, so ``CP=`` came out empty on both arms
    and ``Ailk_Bljk`` native paired against ``Ailk_Bjlk`` floor.
  * ``MacroTile`` is written ``128x128x16`` by native phases and
    ``[128, 64]`` + ``DepthU: 16`` by floor phases. Compared verbatim, a config
    never matches itself across arms.

The consequences were invisible in the totals and obvious in them: the audit
reported a reproducible band of +/-30% where the truth is +/-20%, and it
inverted the central conclusion, reporting native/floor as 0.979 when the
matched median is 1.0005.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ab_audit import (  # noqa: E402
    _CP_RE, _norm_macro_tile, norm_config, reproducible_band, verdict,
)


class TestContractionPattern(unittest.TestCase):
    def test_regex_spans_the_underscore(self):
        for name, want in (
            ("Cijk_Ailk_Bljk_SB_MT128x128x16_SN_K1", "Ailk_Bljk"),
            ("Cijk_Ailk_Bjlk_CB_MT128x64x8_SN_K1", "Ailk_Bjlk"),
            ("Cijk_Ailk_Bljk_SB_00", "Ailk_Bljk"),
        ):
            self.assertEqual(_CP_RE.search(name).group(1), want, name)

    def test_transposed_and_nontransposed_do_not_collide(self):
        """The regression: an empty CP lets Bljk pair with Bjlk."""
        bljk = norm_config({}, "Cijk_Ailk_Bljk_SB_MT128x128x16_SN_K1")
        bjlk = norm_config({}, "Cijk_Ailk_Bjlk_CB_MT128x128x16_SN_K1")
        self.assertNotEqual(bljk, bjlk)


class TestMacroTileNormalisation(unittest.TestCase):
    def test_native_spelling_includes_depth(self):
        self.assertEqual(
            _norm_macro_tile({"MacroTile": "128x128x16"}), "128x128x16")

    def test_floor_spelling_splits_depth_out(self):
        self.assertEqual(
            _norm_macro_tile({"MacroTile": [128, 64], "DepthU": 16}),
            "128x64x16")

    def test_both_spellings_agree(self):
        """Same kernel, two writers, one identity."""
        native = norm_config(
            {"MacroTile": "128x128x16", "ThreadTile": [8, 8],
             "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1,
             "WorkGroupMapping": 4},
            "Cijk_Ailk_Bljk_SB_MT128x128x16_SN_K1")
        floor = norm_config(
            {"MacroTile": [128, 128], "ThreadTile": [8, 8],
             "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1,
             "WorkGroupMapping": 4},
            "Cijk_Ailk_Bljk_SB_MT128x128x16_SN_K1")
        self.assertEqual(native, floor)


class TestNormConfigIsConfigIdentity(unittest.TestCase):
    def test_workgroupmapping_variants_stay_distinct(self):
        """gsu/wgm variants emit the same solution name."""
        fp = "Cijk_Ailk_Bljk_SB_MT64x64x16_SN_K1"
        base = {"MacroTile": [64, 64], "ThreadTile": [4, 4],
                "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1,
                "WorkGroupMapping": 4}
        gsu2 = dict(base, GlobalSplitU=2)
        self.assertNotEqual(norm_config(base, fp), norm_config(gsu2, fp))

    def test_name_alone_is_not_identity(self):
        """Why pairing cannot key on the solution name."""
        fp = "Cijk_Ailk_Bljk_SB_MT64x64x16_SN_K1"
        a = norm_config({"MacroTile": [64, 64], "ThreadTile": [4, 4],
                         "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1,
                         "WorkGroupMapping": 4}, fp)
        b = norm_config({"MacroTile": [64, 64], "ThreadTile": [4, 4],
                         "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 2,
                         "WorkGroupMapping": 4}, fp)
        self.assertEqual(fp, fp)
        self.assertNotEqual(a, b)


class TestReproducibleBand(unittest.TestCase):
    """The band is what decides WIN vs TIE, so its inputs are pinned here."""

    @staticmethod
    def _rec(fg, forms, cfg="cfg", dtype="S", shape="1024x1024x1024"):
        return {"DataType": dtype, "ProblemType": shape, "fingerprint": "k",
                "norm_config": cfg, "GFLOPS": float(fg),
                "shapes_per_phase": forms}

    def test_matched_pairs_split_by_invocation_form(self):
        native = [self._rec(100, 8, "a"), self._rec(200, 8, "b"),
                  self._rec(400, 1, "c"), self._rec(800, 1, "d")]
        floor = [self._rec(100, 8, "a"), self._rec(200, 8, "b"),
                 self._rec(100, 8, "c"), self._rec(100, 8, "d")]
        band = reproducible_band(native, floor)
        self.assertEqual(band["protocol_matched"]["n"], 2)
        self.assertEqual(band["protocol_mismatched"]["n"], 2)
        self.assertAlmostEqual(band["protocol_matched"]["median_ratio"], 1.0)

    def test_identical_config_across_forms_is_not_evidence(self):
        """Same config, different invocation form: excluded from the band.

        This is the whole point. A 2x protocol factor measured here must not
        widen or narrow the noise band used to grade real verdicts.
        """
        native = [self._rec(100, 1)]
        floor = [self._rec(50, 8)]
        band = reproducible_band(native, floor)
        self.assertEqual(band["protocol_matched"]["n"], 0)
        self.assertEqual(band["protocol_mismatched"]["n"], 1)

    def test_zero_floor_value_is_skipped(self):
        self.assertEqual(
            reproducible_band([self._rec(100, 8)], [self._rec(0, 8)])
            ["protocol_matched"]["n"], 0)


class TestVerdict(unittest.TestCase):
    def test_boundary_is_a_tie(self):
        self.assertEqual(verdict(5.0), "TIE")
        self.assertEqual(verdict(-5.0), "TIE")
        self.assertEqual(verdict(5.01), "WIN")
        self.assertEqual(verdict(-5.01), "LOSS")

    def test_band_is_configurable(self):
        self.assertEqual(verdict(12.0, band_pct=20.2), "TIE")
        self.assertEqual(verdict(21.0, band_pct=20.2), "WIN")


if __name__ == "__main__":
    unittest.main()