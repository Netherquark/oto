#!/usr/bin/env python3
"""test_gate_calibration.py — the gate-vs-corpus agreement census.

Pins the mechanism, not a corpus count: a reconstructed phase config is gated
the way the launch boundary gates it, and the (built, gate-legal) confusion is
reported truthfully. The live corpus numbers (0 false rejections on our side) are
the tool's job to report, not this test's to freeze.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.harness import gate_calibration as gc  # noqa: E402


def _phase_yaml(path: Path, macro, tt, du, vw, dtype="s", ta=False, tb=True):
    import yaml
    doc = {
        "BenchmarkProblems": [[
            {"OperationType": "GEMM", "DataType": dtype,
             "TransposeA": ta, "TransposeB": tb, "UseBeta": True, "Batched": True},
            {"BenchmarkCommonParameters": [{"KernelLanguage": ["Assembly"]}],
             "ForkParameters": [
                 {"MacroTile": [list(macro)]},
                 {"ThreadTile": [list(tt)]},
                 {"DepthU": [du]},
                 {"VectorWidth": [vw]},
             ],
             "BenchmarkFinalParameters": [{"ProblemSizes": [{"Exact": [256, 256, 1, 256]}]}]},
        ]],
    }
    path.write_text(yaml.safe_dump(doc))


def _make_corpus(root: Path) -> None:
    # native run
    run = root / "gfx90c_runs" / "run_test"
    run.mkdir(parents=True)
    cfg = run / "configs"
    cfg.mkdir()

    # 1. built + legal (agree)
    ph = run / "phase_built_legal"
    (ph / "2_BenchmarkData").mkdir(parents=True)
    _phase_yaml(cfg / "phase_phase_built_legal.yaml", (64, 64), (4, 4), 8, 2)
    (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")

    # 2. refused + built  (false rejection)
    ph = run / "phase_built_refused"
    (ph / "2_BenchmarkData").mkdir(parents=True)
    _phase_yaml(cfg / "phase_phase_built_refused.yaml", (1024, 1024), (8, 8), 16, 4)
    (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")

    # 3. legal + not built (miss)
    ph = run / "phase_miss"
    ph.mkdir()
    _phase_yaml(cfg / "phase_phase_miss.yaml", (64, 64), (4, 4), 8, 2)

    # 4. refused + not built (agree)
    ph = run / "phase_refused"
    ph.mkdir()
    _phase_yaml(cfg / "phase_phase_refused.yaml", (1024, 1024), (8, 8), 16, 4)

    # reference run
    rref = root / "gfx90c_runs" / "gfx900_ref_test"
    rref.mkdir()
    rcfg = rref / "configs"
    rcfg.mkdir()
    ph = rref / "phase_ref_built"
    (ph / "2_BenchmarkData").mkdir(parents=True)
    _phase_yaml(rcfg / "phase_phase_ref_built.yaml", (64, 64), (4, 4), 8, 2)
    (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")


class TestReadPhaseConfig(unittest.TestCase):
    def test_tiles_become_strings_and_family_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_dir = root / "configs"
            cfg_dir.mkdir()
            _phase_yaml(cfg_dir / "phase_p.yaml", (64, 64), (4, 4), 8, 2)
            cfg = gc.read_phase_config(cfg_dir / "phase_p.yaml", "phase_ss_test")
            self.assertEqual(cfg["MacroTile"], "64x64")
            self.assertEqual(cfg["ThreadTile"], "4x4")
            self.assertEqual(cfg["DataType"], "S")
            self.assertEqual(cfg["FamilyLabel"], "SS")
            self.assertEqual(cfg["ContractionPattern"], "Ailk_Bjlk")

    def test_placeholder_tile_is_excluded_not_a_crash(self):
        """A non-numeric MacroTile is unmodellable -> None, never a ValueError.

        Regression: a phase whose fork carried a ``"NONE"`` placeholder crashed
        ``audit`` inside the loads gate's ``int()``.
        """
        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td) / "configs"
            cfg_dir.mkdir()
            _phase_yaml(cfg_dir / "phase_none.yaml", ("NONE", "NONE"), (4, 4), 8, 2)
            self.assertIsNone(
                gc.read_phase_config(cfg_dir / "phase_none.yaml", "phase_ss_x"))


class TestMeasurementProduced(unittest.TestCase):
    def test_empty_or_missing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            ph = Path(td) / "p"
            ph.mkdir()
            self.assertFalse(gc.measurement_produced(ph))
            (ph / "2_BenchmarkData").mkdir()
            self.assertFalse(gc.measurement_produced(ph))
            (ph / "2_BenchmarkData" / "x.csv").write_text("")
            self.assertFalse(gc.measurement_produced(ph))
            (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")
            self.assertTrue(gc.measurement_produced(ph))


class TestAudit(unittest.TestCase):
    def test_confusion_and_work_lists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            result = gc.audit(str(root))
            ours = result["populations"]["ours"]
            self.assertEqual(ours["phases"], 4)
            self.assertEqual(ours["built"], 2)
            self.assertEqual(ours["confusion"].get("built=True gate=True"), 1)
            self.assertEqual(ours["confusion"].get("built=False gate=False"), 1)
            self.assertEqual(ours["confusion"].get("built=False gate=True"), 1)
            self.assertEqual(ours["confusion"].get("built=True gate=False"), 1)
            self.assertEqual(len(ours["false_rejections"]), 1)
            self.assertEqual(len(ours["misses"]), 1)
            self.assertEqual(ours["false_rejections"][0]["phase"], "phase_built_refused")
            self.assertEqual(ours["misses"][0]["phase"], "phase_miss")

            ref = result["populations"]["reference"]
            self.assertEqual(ref["phases"], 1)
            self.assertEqual(ref["false_rejections"], [])
            self.assertEqual(ref["misses"], [])

    def test_family_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            result = gc.audit(str(root), families=["SS"])
            self.assertEqual(result["meta"]["filtered_out"], 0)
            # the ZZ-ish? none; all phases are SS here
            self.assertEqual(result["populations"]["ours"]["phases"], 4)


class TestPlaceholderTileExcluded(unittest.TestCase):
    def test_unmodellable_phase_is_excluded_from_the_census(self):
        """A phase with a placeholder tile is not counted at all, not 'legal'."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = root / "gfx90c_runs" / "run_test"
            cfg = run / "configs"
            cfg.mkdir(parents=True)
            ph = run / "phase_none"
            (ph / "2_BenchmarkData").mkdir(parents=True)
            _phase_yaml(cfg / "phase_phase_none.yaml", ("NONE", "NONE"), (4, 4), 8, 2)
            (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")
            result = gc.audit(str(root))
            ours = result["populations"]["ours"]
            self.assertEqual(ours["phases"], 0)
            self.assertEqual(ours["built"], 0)
            self.assertEqual(ours["false_rejections"], [])


class TestMain(unittest.TestCase):
    def test_runs_clean_on_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            import io
            buf = io.StringIO()
            import contextlib
            with contextlib.redirect_stdout(buf):
                rc = gc.main(["--base", str(root)])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn("FALSE REJECTION", text)
            self.assertIn("MISS", text)

    def test_fail_on_false_reject_exits_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_corpus(root)
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                rc = gc.main(["--base", str(root), "--fail-on-false-reject"])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
