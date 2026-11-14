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

from oto.metrics.ab_audit import norm_config, reproducible_band, verdict
from oto.metrics.ab_identity import _CP_RE, _norm_macro_tile


class TestContractionPattern(unittest.TestCase):
    def test_regex_spans_the_underscore(self):
        for name, want in (
            ("Cijk_Ailk_Bljk_SB_MT128x128x16_SN_K1", "Ailk_Bljk"),
            ("Cijk_Ailk_Bjlk_CB_MT128x64x8_SN_K1", "Ailk_Bjlk"),
            ("Cijk_Ailk_Bljk_SB_00", "Ailk_Bljk"),
        ):
            assert _CP_RE.search(name).group(1) == want, name

    def test_transposed_and_nontransposed_do_not_collide(self):
        """The regression: an empty CP lets Bljk pair with Bjlk."""
        bljk = norm_config({}, "Cijk_Ailk_Bljk_SB_MT128x128x16_SN_K1")
        bjlk = norm_config({}, "Cijk_Ailk_Bjlk_CB_MT128x128x16_SN_K1")
        assert bljk != bjlk


class TestMacroTileNormalisation(unittest.TestCase):
    def test_native_spelling_includes_depth(self):
        assert _norm_macro_tile({"MacroTile": "128x128x16"}) == "128x128x16"

    def test_floor_spelling_splits_depth_out(self):
        assert _norm_macro_tile({"MacroTile": [128, 64], "DepthU": 16}) == "128x64x16"

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
        assert native == floor


class TestNormConfigIsConfigIdentity(unittest.TestCase):
    def test_workgroupmapping_variants_stay_distinct(self):
        """gsu/wgm variants emit the same solution name."""
        fp = "Cijk_Ailk_Bljk_SB_MT64x64x16_SN_K1"
        base = {"MacroTile": [64, 64], "ThreadTile": [4, 4],
                "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1,
                "WorkGroupMapping": 4}
        gsu2 = dict(base, GlobalSplitU=2)
        assert norm_config(base, fp) != norm_config(gsu2, fp)

    def test_name_alone_is_not_identity(self):
        """Why pairing cannot key on the solution name."""
        fp = "Cijk_Ailk_Bljk_SB_MT64x64x16_SN_K1"
        a = norm_config({"MacroTile": [64, 64], "ThreadTile": [4, 4],
                         "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 1,
                         "WorkGroupMapping": 4}, fp)
        b = norm_config({"MacroTile": [64, 64], "ThreadTile": [4, 4],
                         "VectorWidth": 2, "DepthU": 16, "GlobalSplitU": 2,
                         "WorkGroupMapping": 4}, fp)
        assert fp == fp
        assert a != b


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
        assert band["protocol_matched"]["n"] == 2
        assert band["protocol_mismatched"]["n"] == 2
        self.assertAlmostEqual(band["protocol_matched"]["median_ratio"], 1.0)

    def test_identical_config_across_forms_is_not_evidence(self):
        """Same config, different invocation form: excluded from the band.

        This is the whole point. A 2x protocol factor measured here must not
        widen or narrow the noise band used to grade real verdicts.
        """
        native = [self._rec(100, 1)]
        floor = [self._rec(50, 8)]
        band = reproducible_band(native, floor)
        assert band["protocol_matched"]["n"] == 0
        assert band["protocol_mismatched"]["n"] == 1

    def test_zero_floor_value_is_skipped(self):
        assert reproducible_band([self._rec(100, 8)], [self._rec(0, 8)])["protocol_matched"]["n"] == 0


class TestVerdict(unittest.TestCase):
    def test_boundary_is_a_tie(self):
        assert verdict(5.0) == "TIE"
        assert verdict(-5.0) == "TIE"
        assert verdict(5.01) == "WIN"
        assert verdict(-5.01) == "LOSS"

    def test_band_is_configurable(self):
        assert verdict(12.0, band_pct=20.2) == "TIE"
        assert verdict(21.0, band_pct=20.2) == "WIN"


def _cell_rec(family, side, gflops, tag, protocol="family"):
    """A minimal benchmark record for one (family, shape) cell.

    Enough of the schema for `ab_delta._collect_raw_data`: a family stamp, a
    cube `ProblemType`, one GFLOPS sample, a distinct (run, phase, fp) so
    the sample forms its own per-kernel group, and the invocation form stamp
    the like-for-like rule (§R56.3) grades on.
    """
    return {
        "family": family,
        "ProblemType": f"{side}x{side}x{side}",
        "GFLOPS": gflops,
        "run_id": f"run_{tag}",
        "phase_id": f"phase_{tag}",
        "fingerprint": f"fp_{tag}",
        "protocol": protocol,
    }


class TestCellsNotBeatingFloor(unittest.TestCase):
    """The campaign objective, reduced to a set: which cells have not yet won.

    `ConvergenceAgent._cell_settled` reads this so a cell that only TIES the
    gfx900 floor stays mutable even after it climbs above its family's
    published realistic ceiling. Without it the tied large cells are marked
    settled and the mutation arm never proposes for them -- which is what the
    2026-10-18 run did with all 412 of its candidates.
    """

    def setUp(self):
        import shutil
        import tempfile

        from oto.ledger.registry import SQLiteRegistry
        from oto.metrics.benchmark_analytics import AnalyticsEngine
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_abdelta_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.engine = AnalyticsEngine(SQLiteRegistry(self.tmp), self.tmp)

    def test_a_tie_is_reported_and_a_win_is_not(self):
        floor = [_cell_rec("SS", 128, 100.0, "f_ss"),
                 _cell_rec("CC", 128, 200.0, "f_cc")]
        native = [_cell_rec("SS", 128, 101.0, "n_ss"),
                  _cell_rec("CC", 128, 260.0, "n_cc")]
        losers = self.engine.cells_not_beating_floor(native, floor)
        assert set(losers) == {"SS:128"}
        assert losers["SS:128"]["verdict"] == "TIE"
        assert losers["SS:128"]["family"] == "SS"

    def test_a_loss_is_reported(self):
        losers = self.engine.cells_not_beating_floor(
            [_cell_rec("SS", 128, 80.0, "n_ss")],
            [_cell_rec("SS", 128, 100.0, "f_ss")])
        assert losers["SS:128"]["verdict"] == "LOSS"

    def test_no_floor_yields_the_empty_set(self):
        """Empty must read as "cannot judge", never as "everything won"."""
        assert self.engine.cells_not_beating_floor([_cell_rec("SS", 128, 100.0, "n_ss")], []) == {}


class TestLikeForLikeBasis(unittest.TestCase):
    """The like-for-like rule (§R56.3): a graded pairing matches forms.

    The corpus measured the same configs 2-4x faster under one-problem
    invocations than the family-wide protocol, so a delta pairing a native
    single-problem phase against the family-protocol floor measures the
    protocol. Under the default family basis those singles must never decide
    a verdict -- but they stay in the payload as provenance, and the old
    mixed basis is available exactly as 'any'.
    """

    def setUp(self):
        import shutil
        import tempfile

        from oto.ledger.registry import SQLiteRegistry
        from oto.metrics.benchmark_analytics import AnalyticsEngine
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_l4l_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.engine = AnalyticsEngine(SQLiteRegistry(self.tmp), self.tmp)

    def test_single_problem_inflation_never_wins(self):
        """The single-problem reading (SS:256 at 412 vs floor 124) cannot win.

        Same-config A/B evidence: the iso single read 412.1, its family twin
        98.5-129.9, floor 124.1. A single-problem phase "winning" is the
        protocol artefact; the graded verdict must come from the family
        reading.
        """
        single = _cell_rec("SS", 256, 412.1, "n_iso", protocol="single")
        family_k = _cell_rec("SS", 256, 98.5, "n_fam", protocol="family")
        floor = [_cell_rec("SS", 256, 124.1, "f_ss")]
        deltas = self.engine.compute_native_vs_spoof_delta(
            [single, family_k], floor, agg="winner")
        entry = deltas[("S", "256x256x256", "cell_SS_256")]
        assert entry["basis_protocol"] == "family"
        # 98.5/124.1 = 0.794 -> LOSS outside the 5% band: the like-for-like
        # grading is honest even when it is unflattering.
        assert entry["verdict"] == "LOSS"
        assert entry["native_value"] == 98.5
        # The mixed and isolated numbers stay visible, never graded.
        assert entry["native_best_any_protocol"] == 412.1
        assert entry["native_isolated_best"] == 412.1

    def test_partial_phase_never_grades(self):
        """A trio/partial container is excluded from the graded basis."""
        trio = _cell_rec("DD", 192, 77.8, "n_trio", protocol="partial")
        native = [_cell_rec("DD", 192, 21.0, "n_fam"), trio]
        deltas = self.engine.compute_native_vs_spoof_delta(
            native, [_cell_rec("DD", 192, 21.4, "f_dd")], agg="winner")
        entry = deltas[("D", "192x192x192", "cell_DD_192")]
        assert entry["native_value"] == 21.0
        assert entry["native_best_any_protocol"] == 77.8

    def test_any_basis_reproduces_the_mixed_pairing(self):
        """protocol_basis='any' grades exactly like the pre-§R56.3 report."""
        single = _cell_rec("SS", 256, 412.1, "n_iso", protocol="single")
        family_k = _cell_rec("SS", 256, 98.5, "n_fam")
        deltas = self.engine.compute_native_vs_spoof_delta(
            [single, family_k], [_cell_rec("SS", 256, 124.1, "f_ss")],
            agg="winner", protocol_basis="any")
        entry = deltas[("S", "256x256x256", "cell_SS_256")]
        assert entry["basis_protocol"] == "any"
        assert entry["verdict"] == "WIN"
        assert entry["native_value"] == 412.1

    def test_unstamped_native_never_enters_the_family_basis(self):
        """A record without a stamp is UNKNOWN, and UNKNOWN cannot grade."""
        unstamped = _cell_rec("SS", 256, 5000.0, "n_old")
        del unstamped["protocol"]
        deltas = self.engine.compute_native_vs_spoof_delta(
            [unstamped], [_cell_rec("SS", 256, 124.1, "f_ss")], agg="winner")
        assert deltas == {}


if __name__ == "__main__":
    unittest.main()
