#!/usr/bin/env python3
"""
test_report_family_case.py -- per_family_coverage must not cross-contaminate.

Regression for the 2026-10-10 "HPA above theoretical limit" scare: the
acceptance report showed HH_HPA and HS_HPA at 230-246% of their 1613 ceiling,
with *identical* bodies. Root cause: CellAnalytics.family is canonical
UPPERCASE ('HH_HPA') after the Oct 9 typecode-first attribution, but
_compute_family_coverage matched `a.family == fam_lower` ('hh_hpa'). The match
silently emptied both HPA buckets, and the dtype fallback (FAMILY_TO_DTYPE
['hh_hpa'] == 'H') then grabbed every packed-FP16 HH cell -- reporting the HH
kernel median (2749.285, correct against HH's 3226 packed ceiling) as HPA
"performance" at 170% of an FP32-rate ceiling that HPA can never exceed.

Run: python3 test_report_family_case.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# This file lives in tests/, so the repo root is one level up. BASE is both the
# import root and the data root, and both are the repo root -- the harness
# modules are imported flat, so they sit beside this file's parent.
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from analytics import CellAnalytics  # noqa: E402
from report import AcceptanceReporter  # noqa: E402


def cell(family: str, shape: str, median: float) -> CellAnalytics:
    """A minimal CellAnalytics row; only family/shape/median are read here."""
    return CellAnalytics(
        dtype="H", shape=shape, config_fp=f"{family}_{shape}",
        median_gflops=median, spread_ratio=0.1, num_seeds=8,
        pct_of_ceiling=90.0, is_below_ceiling=True,
        bound_class="ALU", family=family)


class TestFamilyCoverageCase(unittest.TestCase):

    def setUp(self):
        self.reporter = AcceptanceReporter(Path(tempfile.mkdtemp()))

    def test_hpa_buckets_keep_their_own_kernels(self):
        """HH packed-FP16 medians must never leak into HH_HPA / HS_HPA."""
        analytics = [
            cell("HH", "1024x1024x1024", 2581.94),      # packed FP16
            cell("HH", "4096x4096x4096", 2749.285),     # packed FP16
            cell("HH_HPA", "1024x1024x1024", 1447.0),   # FP32-rate
            cell("HH_HPA", "4096x4096x4096", 1411.05),
            cell("HS_HPA", "4096x4096x4096", 1441.2),
        ]
        cov = self.reporter._compute_family_coverage(analytics)
        self.assertEqual(cov["HH"]["best_median"], 2749.285)
        # HPA must report its own kernels, not the packed HH median.
        self.assertEqual(cov["HH_HPA"]["best_median"], 1447.0)
        self.assertEqual(cov["HS_HPA"]["best_median"], 1441.2)
        # And per-size, 4096 for HH_HPA is its own row, not 2749.285.
        self.assertEqual(cov["HH_HPA"]["by_size"]["4096"]["best_median"], 1411.05)
        self.assertLess(cov["HH_HPA"]["best_median"], cov["HH"]["best_median"])
        self.assertLess(cov["HS_HPA"]["best_median"], cov["HH"]["best_median"])

    def test_hpa_buckets_are_not_identical(self):
        """The symptom: HH_HPA and HS_HPA had byte-identical coverage dicts."""
        analytics = [
            cell("HH", "4096x4096x4096", 2749.285),    # packed FP16, would hijack
            cell("HH_HPA", "4096x4096x4096", 1411.05),
            cell("HS_HPA", "1024x1024x1024", 1429.7),
        ]
        cov = self.reporter._compute_family_coverage(analytics)
        self.assertNotEqual(cov["HH_HPA"], cov["HS_HPA"])
        # Each HPA bucket reports only its own kernels -- never the HH median.
        self.assertEqual(cov["HH_HPA"]["best_median"], 1411.05)
        self.assertEqual(cov["HH_HPA"]["by_size"]["4096"]["best_median"], 1411.05)
        self.assertEqual(cov["HS_HPA"]["best_median"], 1429.7)

    def test_legacy_lowercase_family_still_matches(self):
        """Pre-Oct-9 cells carry lowercase families; they must not be lost."""
        analytics = [cell("hh_hpa", "1024x1024x1024", 1300.0)]
        cov = self.reporter._compute_family_coverage(analytics)
        self.assertEqual(cov["HH_HPA"]["best_median"], 1300.0)


if __name__ == "__main__":
    unittest.main()