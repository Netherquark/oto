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

from oto.metrics.report_figures import coverage_dir, coverage_rows, coverage_section

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
        assert len(rows) == 2
        assert rows[0]["family"] == "SS"
        assert rows[0]["n_legal"] == 419

    def test_no_rows_without_the_handoff_file(self):
        import tempfile

        empty = Path(tempfile.mkdtemp())
        assert coverage_rows(empty) == []

    def test_the_section_states_the_unexplored_share(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        assert "Problem-space coverage" in html
        # the per-cell share (87% for SS, 71% for ZZ) -- the legal space is
        # the same for every cell of a family, so the ratio is per cell.
        assert "87%" in html
        assert "never been" in html
        assert "run." in html

    def test_the_section_carries_the_numbers_and_the_figures(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        assert "419" in html      # legal geometries
        assert "54" in html       # measured
        assert "figure-grid" in html
        assert "SS_256x256x256.svg" in html
        # performance belongs to the family matrix; the coverage table owns
        # only the search numbers.
        assert "412.1" not in html

    def test_figure_paths_are_relative_to_the_report(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        assert 'src="analysis/coverage/SS_256x256x256.svg"' in html
        assert str(self.tmp) not in html

    def test_the_figures_are_grouped_by_family(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        # one appendix, then a heading per family: no nested per-family
        # disclosure controls and no second copy of the table.
        assert html.count('<details class="figure-appendix">') == 1
        assert html.count('class="figure-family"') == 2
        assert "figure-group" not in html
        assert ">SS<" in html
        assert ">ZZ<" in html
        # the family group row carries the family's own numbers
        assert 'class="coverage-group"' in html
        assert "1 cell" in html          # SS has one row in the fixture
        assert "419" in html             # legal geometries, per cell
        assert "87.1%" in html           # the unexplored share of that cell

    def test_a_family_group_holds_its_own_shapes(self):
        html = coverage_section(self.tmp, self.tmp / "gfx90c_results"
                                / "acceptance_report.html")
        assert "256x256x256" in html
        assert "1024x1024x1024" in html

    def test_the_section_says_what_to_run_when_there_is_nothing(self):
        import tempfile

        html = coverage_section(Path(tempfile.mkdtemp()),
                                Path("acceptance_report.html"))
        assert "coverage_graph" in html
        assert "No coverage figures yet" in html


if __name__ == "__main__":
    unittest.main()
