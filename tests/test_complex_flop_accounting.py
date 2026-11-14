#!/usr/bin/env python3
"""The complex families are measured in CLIENT-REPORTED GFLOPS, not BLAS-8.

Tensile's client charges 2 flops per MAC for every dtype, complex included
(``ContractionProblem::flopCount`` = ``2 * DataTypeInfo::packing``, packing is 1
for complexSingle/complexDouble). A complex MAC is executed as four real FMAs
= 8 BLAS flops, so a reported complex GFLOPS is 1/4 of its BLAS-8 value.

These tests pin the factor, the ceilings derived from it, and the corpus
evidence for it, so the complex families can never again be scored against a
bar that is 4x off (the mistake that made CC and ZZ look like 20-24% of their
roof when they run at 80-97% of it).

CPU only, read-only.
"""

from __future__ import annotations

import csv
import glob
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import blas8_gflops
from oto.runners.paths import runs_rel as _runs_rel

RUNS = BASE / _runs_rel("")


class TestFlopFactor(unittest.TestCase):
    """The factor itself: 4x for the two complex families, 1x for the rest."""

    def test_complex_families_carry_the_four_x_factor(self):
        assert _loader.current_profile().reported_to_blas8["CC"] == 4.0
        assert _loader.current_profile().reported_to_blas8["ZZ"] == 4.0

    def test_real_families_are_one_to_one(self):
        for fam in ("SS", "DD", "HH", "HH_HPA", "HS_HPA"):
            assert _loader.current_profile().reported_to_blas8[fam] == 1.0, fam

    def test_helper_converts_only_the_complex_families(self):
        assert blas8_gflops("CC", 322.0) == 1288.0
        assert blas8_gflops("ZZ", 24.5) == 98.0
        assert blas8_gflops("SS", 412.0) == 412.0
        assert blas8_gflops("hh_hpa", 1454.8) == 1454.8


class TestCeilings(unittest.TestCase):
    """The acceptance ceilings are in the unit the measurement arrives in."""

    def test_complex_ceilings_are_the_blas8_values_over_four(self):
        self.assertAlmostEqual(_loader.current_profile().realistic_ceilings["CC"],
                               _loader.current_profile().realistic_ceilings_blas8["CC"] / 4.0, places=9)
        self.assertAlmostEqual(_loader.current_profile().realistic_ceilings["ZZ"],
                               _loader.current_profile().realistic_ceilings_blas8["ZZ"] / 4.0, places=9)
        self.assertAlmostEqual(_loader.current_profile().theoretical_peaks["CC"],
                               _loader.current_profile().theoretical_peaks_blas8["CC"] / 4.0, places=9)
        self.assertAlmostEqual(_loader.current_profile().theoretical_peaks["ZZ"],
                               _loader.current_profile().theoretical_peaks_blas8["ZZ"] / 4.0, places=9)

    def test_real_ceilings_are_untouched(self):
        assert _loader.current_profile().realistic_ceilings["SS"] == 1118.7
        assert _loader.current_profile().realistic_ceilings["DD"] == 98.6
        assert _loader.current_profile().realistic_ceilings["HH"] == 2461.0
        assert _loader.current_profile().theoretical_peaks["SS"] == 1613
        assert _loader.current_profile().theoretical_peaks["HH"] == 3226

    def test_the_complex_roof_is_the_real_roof_over_four(self):
        """CC's roof is the FP32 pipe, ZZ's the FP64 pipe -- both /4."""
        self.assertAlmostEqual(_loader.current_profile().theoretical_peaks["CC"], _loader.current_profile().peak_gflops["FP32"] / 4.0, places=9)
        self.assertAlmostEqual(_loader.current_profile().theoretical_peaks["ZZ"], _loader.current_profile().peak_gflops["FP64"] / 4.0, places=9)

    def test_complex_cells_score_against_the_corrected_bar(self):
        """The measured bests, re-scored: CC/ZZ are at the roof, not at 20%."""
        cases = [("CC", 512, 322.0), ("CC", 2048, 346.7),
                 ("ZZ", 512, 24.3), ("ZZ", 1024, 24.5)]
        for fam, _side, reported in cases:
            pct = reported / _loader.current_profile().theoretical_peaks[fam] * 100.0
            assert pct > 75.0, f"{fam}:{reported} should be near its roof"


class TestCorpusEvidence(unittest.TestCase):
    """The corpus itself carries the proof: TotalFlops == 2*M*N*K, always."""

    def _first_csv(self, pattern):
        hits = sorted(glob.glob(str(RUNS / "run_*" / "*" / "2_BenchmarkData" / pattern)))
        return hits[0] if hits else None

    def test_client_totalflops_is_two_mn_k_for_every_family(self):
        seen = 0
        for pattern in ("*Cijk_Ailk_Bjlk_CB_00.csv", "*Cijk_Alik_Bjlk_ZB_00.csv",
                        "*Cijk_Ailk_Bjlk_SB_00.csv", "*Cijk_Alik_Bljk_DB_00.csv"):
            path = self._first_csv(pattern)
            if not path:
                continue
            with open(path) as handle:
                reader = csv.reader(handle)
                header = [h.strip() for h in next(reader)]
                for raw in reader:
                    row = {h: v.strip() for h, v in zip(header, raw, strict=False)}
                    m = int(row["SizeI"])
                    n = int(row["SizeJ"])
                    k = int(row["SizeL"])       # SizeK is the batch dim (1)
                    total = float(row["TotalFlops"])
                    self.assertAlmostEqual(total, 2.0 * m * n * k, places=3,
                                           msg=f"{path}: TotalFlops != 2*M*N*K")
                    seen += 1
                    break
        if not seen:
            self.skipTest("no benchmark CSV in the corpus to check")

    def test_a_complex_cell_reaches_its_roof_once_converted(self):
        """CC at 512^3: reported 322 -> 1288 BLAS-8 -> 80% of the FP32 roof."""
        reported = 322.0
        blas8 = blas8_gflops("CC", reported)
        self.assertAlmostEqual(blas8, 1288.0, places=6)
        pct = blas8 / _loader.current_profile().peak_gflops["FP32"] * 100.0
        assert pct > 75.0
        assert pct < 90.0


if __name__ == "__main__":
    unittest.main()
