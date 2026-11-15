"""pdoc renders the whole package without error.

Guards against docstrings that break pdoc's parser (unmatched fences,
invalid RST-ish directives) and against module docstring drift that would
make the generated reference misleading.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
pdoc = pytest.importorskip("pdoc")


def test_pdoc_renders_package(tmp_path):
    site = tmp_path / "site"
    result = subprocess.run(
        [sys.executable, "-m", "pdoc", "oto", "--output-dir", str(site)],
        cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, (
        "pdoc failed:\n" + result.stdout + "\n" + result.stderr)
    assert (site / "index.html").is_file()