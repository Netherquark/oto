#!/usr/bin/env python3
"""test_report_coverage.py -- the acceptance report's problem-space section.

The section is the report's answer to "how much of the problem space did we
actually search?", so the two things it must get right are pinned here:

* it reads the coverage tool's hand-off file and prints the numbers from it
  (the report never re-derives them -- the legal-space sweep takes minutes);
* it links the figures *relative to the report file*, so the report works from
  the run directory as well as from the canonical location.

CPU only, no GPU, and it uses a tmp tree so the real artefacts are not
touched.

    python3 -m pytest -q tests/test_report_coverage.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.metrics.report_figures import (  # noqa: E402
    coverage_rows, coverage_section, coverage_dir)

ROWS = [
    {"family": "SS", "shape": "256x256x256", "n_legal": 419,
     "n_measured": 54, "unexplored": 365, "pct_unexplored": 87.1,
     "best": 412.05, "peaks": 5, "traps": 2,
     "file": "SS_256x256x256.svg"},
    {"family": "ZZ", "shape": "1024x1024x1024", "n_legal": 52,
     "n_measured": 15, "unexplored": 37, "pct_unexplored": 71.2,
     "best": 24.5, "peaks": 0, "traps": 0,
     "file": "ZZ_1024x1024x1024.svg"},
]


class TestCoverageSection(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.dir = coverage_dir(self.tmp)
        self.dir.mkdir(parents=True)
        (self.dir / "coverage.json").write_text(
            json.dumps({"generated_at": "now", "rows": ROWS}))
        (self.dir / "SS_256x256x256.svg").write_text("<svg/>")

    def test_rows_are_read_from_the_handoff_file(self):
        rows = coverage_rows(self.tmp)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["family"], "SS")
        self.assertEqual(rows[0]["n_legal"], 419)

    def test_no_rows_without_the_handoff_file(self):
        import tempfile

        empty = Path(tempfile.mkdtemp())
        self.assertEqual(coverage_rows(empty), [])

    def test_the_section_states_the_unexplored_share(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        self.assertIn("Problem-space coverage", html)
        # the per-cell share (87% for SS, 71% for ZZ) -- the legal space is
        # the same for every cell of a family, so the ratio is per cell.
        self.assertIn("87%", html)
        self.assertIn("never been", html)
        self.assertIn("run.", html)

    def test_the_section_carries_the_numbers_and_the_figures(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        self.assertIn("419", html)      # legal geometries
        self.assertIn("54", html)       # measured
        self.assertIn("figure-grid", html)
        self.assertIn("SS_256x256x256.svg", html)
        # performance belongs to the family matrix; the coverage table owns
        # only the search numbers.
        self.assertNotIn("412.1", html)

    def test_figure_paths_are_relative_to_the_report(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        self.assertIn('src="analysis/coverage/SS_256x256x256.svg"', html)
        self.assertNotIn(str(self.tmp), html)

    def test_the_figures_are_grouped_by_family(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        # one appendix, then a heading per family: no nested per-family
        # disclosure controls and no second copy of the table.
        self.assertEqual(html.count("<details class=\"figure-appendix\">"), 1)
        self.assertEqual(html.count("class=\"figure-family\""), 2)
        self.assertNotIn("figure-group", html)
        self.assertIn(">SS<", html)
        self.assertIn(">ZZ<", html)
        # the family group row carries the family's own numbers
        self.assertIn("class=\"coverage-group\"", html)
        self.assertIn("1 cell", html)          # SS has one row in the fixture
        self.assertIn("419", html)             # legal geometries, per cell
        self.assertIn("87.1%", html)           # the unexplored share of that cell

    def test_a_family_group_holds_its_own_shapes(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        self.assertIn("256x256x256", html)
        self.assertIn("1024x1024x1024", html)

    def test_the_section_says_what_to_run_when_there_is_nothing(self):
        import tempfile

        html = coverage_section(Path(tempfile.mkdtemp()),
                                Path("acceptance_report.html"))
        self.assertIn("coverage_graph", html)
        self.assertIn("No coverage figures yet", html)


if __name__ == "__main__":
    unittest.main()
