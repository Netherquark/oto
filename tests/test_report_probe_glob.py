#!/usr/bin/env python3
"""
test_report_probe_glob.py -- _ab_records_from_csv must scan probe_* dirs too.

Regression for the overnight-run report failure of 2026-10-10: commit
d26ac4de added probe_* CSV coverage to _ab_records_from_csv but wrote

    run_dir.glob("phase_*/2_BenchmarkData/*.csv")
        + list(run_dir.glob("probe_*/2_BenchmarkData/*.csv"))

Path.glob returns a generator, not a list, so the concatenation raised
TypeError("unsupported operand type(s) for +: 'map' and 'list'") the first
time a report was regenerated after that commit — which was the overnight
run_20261009_205427 finishing at 04:35 and failing to emit its acceptance
report.

Run: python3 test_report_probe_glob.py
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

from oto.runners.cli import TensileDriver


class _FakeAnalytics:
    """Minimal stand-in: every CSV is empty, so no records and no stamps."""

    def load_benchmark_csv(self, csv_file: Path):
        return []

    def aggregate_by_cell_typecode(self, records, phase_family):
        return {}


def make_driver(tmp: Path) -> TensileDriver:
    """A driver whose only live logic is the CSV glob + record loop."""
    drv = TensileDriver.__new__(TensileDriver)
    drv.run_dir = tmp
    drv.load_phases_manifest = list
    drv.analytics = _FakeAnalytics()
    return drv


def write_csv(run_dir: Path, phase_dir: str) -> Path:
    d = run_dir / phase_dir / "2_BenchmarkData"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "result.csv"
    f.write_text("dummy\n")  # content is opaque to the fake loader
    return f


class TestAbRecordsProbeGlob(unittest.TestCase):

    def test_phase_and_probe_dirs_scan_without_typeerror(self):
        """The overnight-run crash: both glob branches present in one run dir."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            write_csv(run_dir, "phase_t1_abc123")
            write_csv(run_dir, "probe_s1_xyz789")
            drv = make_driver(run_dir)
            # Pre-fix this raised TypeError before the loop body ever ran.
            native, spoof = drv._ab_records_from_csv(run_dir, force_arm="native")
            assert native == []
            assert spoof == []

    def test_probe_only_dir_scans(self):
        """The new capability: a run dir with no phase_* dirs still works."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            write_csv(run_dir, "probe_s1_xyz789")
            drv = make_driver(run_dir)
            native, spoof = drv._ab_records_from_csv(run_dir, force_arm="native")
            assert (native, spoof) == ([], [])

    def test_empty_run_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            drv = make_driver(Path(td))
            native, spoof = drv._ab_records_from_csv(Path(td), force_arm="native")
            assert (native, spoof) == ([], [])


if __name__ == "__main__":
    unittest.main()
