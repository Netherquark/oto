#!/usr/bin/env python3
"""test_coverage_graph.py -- the coverage graphs, and what they claim.

The graphs are the project's picture of the *problem space*: the legal
geometry space per cell, the part of it the corpus has measured, and the
peaks and traps inside the measured part. A picture that is wrong is worse
than no picture, so the pieces it is built from are pinned here:

* the projection is honest -- a geometry lands in the bucket its macro-tile
  area and its accumulators-per-thread fall in, and nothing else;
* the colours are the measured values, normalised against the cell's best;
* a peak is a measured bucket whose measured neighbours are all slower, and
  a trap is one whose measured neighbours are all faster;
* the SVG is well-formed enough to render (a viewBox, a size, and no
  unescaped text).

CPU only, no GPU, and it does not sweep the legal space (that is the slow
part): the geometry helpers are exercised on hand-built inputs.

    python3 -m pytest -q tests/test_coverage_graph.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.harness.coverage_graph import (  # noqa: E402
    ACC_BUCKETS, AREA_BUCKETS, _acc_of, _area_of, _bucket, _esc, _extrema,
    _grid, _ramp, _step)


class TestBuckets(unittest.TestCase):
    def test_buckets_are_the_largest_edge_not_above_the_value(self):
        self.assertEqual(_bucket(9216, AREA_BUCKETS), 8192)
        self.assertEqual(_bucket(4096, AREA_BUCKETS), 4096)
        self.assertEqual(_bucket(100, AREA_BUCKETS), None)
        self.assertEqual(_bucket(36, ACC_BUCKETS), 32)
        self.assertEqual(_bucket(64, ACC_BUCKETS), 64)
        self.assertEqual(_bucket(8192, AREA_BUCKETS), 8192)

    def test_area_is_the_macro_tile_product(self):
        self.assertEqual(_area_of(("96x96", "6x6", 2, 16)), 8192)
        self.assertEqual(_area_of(("128x128", "8x8", 4, 8)), 16384)
        self.assertEqual(_area_of(("notatile", "8x8", 4, 8)), None)

    def test_accumulators_count_the_dtype_weight(self):
        # S: 1 VGPR per element, C: 4, Z: 8.
        self.assertEqual(_acc_of(("128x128", "8x8", 4, 8), 1), 64)
        self.assertEqual(_acc_of(("64x64", "4x4", 2, 8), 4), 64)
        self.assertEqual(_acc_of(("32x32", "2x2", 1, 8), 8), 32)


class TestGrid(unittest.TestCase):
    def setUp(self):
        self.legal = [("64x64", "4x4", 2, 8), ("128x128", "8x8", 4, 8),
                      ("32x32", "2x2", 1, 8)]
        self.measured = {("64x64", "4x4", 2, 8): 118.2,
                         ("128x128", "8x8", 4, 8): 346.7}

    def test_the_grid_marks_legal_measured_and_empty(self):
        grid = _grid("SS", self.legal, self.measured)
        self.assertTrue(grid[(4096, 16)]["legal"])       # 64x64 / 16 acc
        self.assertEqual(grid[(4096, 16)]["n_measured"], 1)
        self.assertEqual(grid[(4096, 16)]["value"], 118.2)
        # legal but never measured
        self.assertTrue(grid[(1024, 4)]["legal"])
        self.assertEqual(grid[(1024, 4)]["n_measured"], 0)
        self.assertEqual(grid[(1024, 4)]["value"], 0.0)

    def test_the_value_is_the_best_in_the_bucket(self):
        measured = dict(self.measured)
        measured[("64x64", "4x4", 1, 16)] = 200.0
        grid = _grid("SS", self.legal, measured)
        self.assertEqual(grid[(4096, 16)]["value"], 200.0)
        self.assertEqual(grid[(4096, 16)]["n_measured"], 2)


class TestExtrema(unittest.TestCase):
    def test_a_peak_is_a_bucket_whose_neighbours_are_all_slower(self):
        grid = {(4096, 16): {"legal": True, "value": 100.0, "n_legal": 1,
                             "n_measured": 1},
                (8192, 16): {"legal": True, "value": 50.0, "n_legal": 1,
                             "n_measured": 1},
                (4096, 32): {"legal": True, "value": 40.0, "n_legal": 1,
                             "n_measured": 1}}
        peaks, traps = _extrema(grid)
        self.assertIn((4096, 16), peaks)
        self.assertNotIn((4096, 16), traps)

    def test_a_trap_is_a_bucket_whose_neighbours_are_all_faster(self):
        grid = {(4096, 16): {"legal": True, "value": 10.0, "n_legal": 1,
                             "n_measured": 1},
                (8192, 16): {"legal": True, "value": 90.0, "n_legal": 1,
                             "n_measured": 1},
                (4096, 32): {"legal": True, "value": 80.0, "n_legal": 1,
                             "n_measured": 1}}
        peaks, traps = _extrema(grid)
        self.assertIn((4096, 16), traps)
        self.assertNotIn((4096, 16), peaks)

    def test_an_unmeasured_bucket_is_neither(self):
        grid = {(4096, 16): {"legal": True, "value": 10.0, "n_legal": 1,
                             "n_measured": 0}}
        peaks, traps = _extrema(grid)
        self.assertEqual(peaks, [])
        self.assertEqual(traps, [])

    def test_a_lone_measured_bucket_is_not_called(self):
        """With fewer than two measured neighbours there is nothing to compare."""
        grid = {(4096, 16): {"legal": True, "value": 10.0, "n_legal": 1,
                             "n_measured": 1}}
        peaks, traps = _extrema(grid)
        self.assertEqual(peaks, [])
        self.assertEqual(traps, [])


class TestRendering(unittest.TestCase):
    def test_the_ramp_is_a_colour(self):
        self.assertTrue(_ramp(0.0).startswith("#"))
        self.assertTrue(_ramp(1.0).startswith("#"))
        self.assertTrue(_ramp(-5.0).startswith("#"))
        self.assertTrue(_ramp(9.0).startswith("#"))

    def test_text_is_escaped(self):
        self.assertEqual(_esc("a & b < c"), "a &amp; b &lt; c")

    def test_step_walks_the_bucket_edges(self):
        self.assertEqual(_step(1024, 1), 2048)
        self.assertEqual(_step(2048, -1), 1024)
        self.assertEqual(_step(1024, -1), 1024)   # the edge stays put


if __name__ == "__main__":
    unittest.main()
