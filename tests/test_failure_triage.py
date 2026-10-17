#!/usr/bin/env python3
"""test_failure_triage.py — the empty-phase reason census.

Pins the reason-mining mechanism on a synthetic run corpus, not a corpus count.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.harness import failure_triage as ft  # noqa: E402


def _make_corpus(root: Path) -> None:
    run = root / "gfx90c_runs" / "run_test"
    run.mkdir(parents=True)

    # built phase
    ph = run / "phase_built"
    (ph / "2_BenchmarkData").mkdir(parents=True)
    (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")

    # empty phase with a Tensile reject line
    ph = run / "phase_empty_reject"
    ph.mkdir()
    (ph / "stdout.log").write_text("noise\nreject: GLVW 2 * bpe 8 > 16\ndone\n")

    # empty phase with a non-empty stderr and no reject line
    ph = run / "phase_empty_stderr"
    ph.mkdir()
    (ph / "stderr.log").write_text("Traceback (most recent call last):\n  boom\n")

    # empty phase with no logs at all
    ph = run / "phase_empty_nolog"
    ph.mkdir()


class TestMeasurementProduced(unittest.TestCase):
    def test(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            run = root / "gfx90c_runs" / "run_test"
            self.assertTrue(ft.measurement_produced(run / "phase_built"))
            self.assertFalse(ft.measurement_produced(run / "phase_empty_reject"))


class TestReasonForPhase(unittest.TestCase):
    def test_tensile_reject_wins(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            run = root / "gfx90c_runs" / "run_test"
            r = ft.reason_for_phase(run / "phase_empty_reject")
            self.assertTrue(r.startswith("tensile reject x1:"))
            self.assertIn("GLVW 2 * bpe 8 > 16", r)

    def test_stderr_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            run = root / "gfx90c_runs" / "run_test"
            r = ft.reason_for_phase(run / "phase_empty_stderr")
            self.assertTrue(r.startswith("stderr non-empty:"))

    def test_no_logs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            run = root / "gfx90c_runs" / "run_test"
            r = ft.reason_for_phase(run / "phase_empty_nolog")
            self.assertEqual(r, "no logs at all")


class TestCensus(unittest.TestCase):
    def test_totals_and_histogram(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            result = ft.census(str(root))
            self.assertEqual(result["meta"]["phase_dirs"], 4)
            self.assertEqual(result["meta"]["empty"], 3)
            self.assertEqual(result["meta"]["runs_scanned"], 1)
            self.assertEqual(len(result["per_run"]), 1)
            self.assertEqual(result["per_run"][0]["empty"], 3)
            # two distinct reasons (reject, stderr) + no-logs
            self.assertEqual(sum(result["reasons"].values()), 3)

    def test_run_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            result = ft.census(str(root), run_filter="no_such_run")
            self.assertEqual(result["meta"]["phase_dirs"], 0)
            self.assertEqual(result["meta"]["empty"], 0)


class TestMain(unittest.TestCase):
    def test_runs_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ft.main(["--base", str(root)])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn("phase dirs: 4", text)
            self.assertIn("with no non-empty CSV: 3", text)


if __name__ == "__main__":
    unittest.main()
