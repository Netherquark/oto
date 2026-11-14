#!/usr/bin/env python3
"""test_visual_check.py -- the visual/layout regression check.

The check validates the rendered dashboard at desktop and mobile viewports:
- no horizontal overflow
- key sections present
- metric grid has correct column counts

CPU only, requires playwright + chromium.

    python3 -m pytest -q tests/test_visual_check.py
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from oto.runners import result_paths as paths

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# The report of record lives at <base>/<codename>_results/acceptance_report.html
REPORT = BASE / paths.results_rel("acceptance_report.html")


class TestVisualCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REPORT.exists():
            raise unittest.SkipTest(f"Report not found: {REPORT}")

    def test_visual_check_passes(self):
        """The visual/layout check should pass on the current report."""
        result = subprocess.run(
            [sys.executable, "-m", "oto.harness.visual_check", str(REPORT)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"Visual check failed:\n{result.stdout}\n{result.stderr}"
        assert "PASS" in result.stdout


if __name__ == "__main__":
    unittest.main()
