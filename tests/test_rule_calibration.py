#!/usr/bin/env python3
"""test_rule_calibration.py — the candidate-rule probe.

Pins the mechanism: a proposed ``config -> Optional[bool]`` rule is applied to
the corpus and the (would-refuse, built) confusion is reported truthfully, so a
rule that would refuse a phase Tensile built is surfaced as a false rejection.
The live corpus numbers are the tool's to report, not this test's to freeze; the
one cross-module guarantee pinned here is that a *shipped* builtin cannot drift
from the gate it is a view of.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest

from oto.harness import rule_calibration as rc
from oto.tensile.gates.occupancy import occupancy_feasible


def _refuse_all(config):
    return True


def _phase_yaml(path: Path, macro, tt, du, vw, dtype="s"):
    import yaml
    doc = {
        "BenchmarkProblems": [[
            {"OperationType": "GEMM", "DataType": dtype,
             "TransposeA": False, "TransposeB": True, "UseBeta": True,
             "Batched": True},
            {"BenchmarkCommonParameters": [{"KernelLanguage": ["Assembly"]}],
             "ForkParameters": [
                 {"MacroTile": [list(macro)]},
                 {"ThreadTile": [list(tt)]},
                 {"DepthU": [du]},
                 {"VectorWidth": [vw]},
             ],
             "BenchmarkFinalParameters": [
                 {"ProblemSizes": [{"Exact": [256, 256, 1, 256]}]}]},
        ]],
    }
    path.write_text(yaml.safe_dump(doc))


def _make_corpus(root: Path) -> None:
    """One native run (a built + an empty phase) and one reference run."""
    run = root / "gfx90c_runs" / "run_test"
    cfg = run / "configs"
    cfg.mkdir(parents=True)
    ph = run / "phase_built"
    (ph / "2_BenchmarkData").mkdir(parents=True)
    _phase_yaml(cfg / "phase_phase_built.yaml", (64, 64), (4, 4), 8, 2)
    (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")
    (run / "phase_empty").mkdir()
    _phase_yaml(cfg / "phase_phase_empty.yaml", (64, 64), (4, 4), 8, 2)

    rref = root / "gfx90c_runs" / "gfx900_ref_test"
    rcfg = rref / "configs"
    rcfg.mkdir(parents=True)
    ph = rref / "phase_ref_built"
    (ph / "2_BenchmarkData").mkdir(parents=True)
    _phase_yaml(rcfg / "phase_phase_ref_built.yaml", (64, 64), (4, 4), 8, 2)
    (ph / "2_BenchmarkData" / "x.csv").write_text("a,b\n1,2\n")


class TestProbe(unittest.TestCase):
    def test_allow_all_agrees_and_misses(self):
        with tempfile.TemporaryDirectory() as td:
            _make_corpus(Path(td))
            pop = rc.probe(lambda cfg: False, base=td)["populations"]["ours"]
            assert pop["applicable"] == 2
            assert pop["agrees"] == 1
            assert pop["allowed_empty"] == 1
            assert pop["false_rejections"] == []

    def test_refuse_all_splits_built_from_empty(self):
        with tempfile.TemporaryDirectory() as td:
            _make_corpus(Path(td))
            pop = rc.probe(_refuse_all, base=td)["populations"]["ours"]
            assert len(pop["false_rejections"]) == 1
            assert len(pop["catches"]) == 1
            assert pop["false_rejections"][0]["phase"] == "phase_built"
            assert pop["caught_by_family"] == {"SS": 1}

    def test_none_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            _make_corpus(Path(td))
            pop = rc.probe(lambda cfg: None, base=td)["populations"]["ours"]
            assert pop["applicable"] == 0
            assert pop["not_applicable"] == 2
            assert pop["false_rejections"] == []

    def test_reference_population_is_split_out(self):
        with tempfile.TemporaryDirectory() as td:
            _make_corpus(Path(td))
            result = rc.probe(_refuse_all, base=td)
            assert result["populations"]["reference"]["applicable"] == 1
            assert len(result["populations"]["reference"]["false_rejections"]) == 1

    def test_family_filter(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "gfx90c_runs" / "run_test"
            cfg = run / "configs"
            cfg.mkdir(parents=True)
            (run / "phase_dd").mkdir()
            _phase_yaml(cfg / "phase_phase_dd.yaml", (64, 64), (4, 4), 8, 2,
                        dtype="d")
            (run / "phase_ss").mkdir()
            _phase_yaml(cfg / "phase_phase_ss.yaml", (64, 64), (4, 4), 8, 2)
            pop = rc.probe(lambda cfg: None, base=td, families=["DD"]
                           )["populations"]["ours"]
            assert pop["applicable"] + pop["not_applicable"] == 1


class TestBuiltinsMatchTheGate(unittest.TestCase):
    """A shipped builtin is a *view* of the gate, so it cannot drift."""

    def test_workgroup_file_predicate_implies_the_gate_refuses(self):
        rule = rc.builtin_rules()["workgroup_file"]
        fired = 0
        for cfg in ({"DataType": "z", "MacroTile": "128x128x8",
                     "ThreadTile": "4x4"},
                    {"DataType": "z", "MacroTile": "64x64x8",
                     "ThreadTile": "4x4"},
                    {"DataType": "s", "MacroTile": "64x64x8",
                     "ThreadTile": "4x4"},
                    {"DataType": "c", "MacroTile": "128x64x8",
                     "ThreadTile": "4x8"}):
            verdict = rule(cfg)
            assert verdict is not None
            if verdict:
                fired += 1
                assert not occupancy_feasible(cfg)[0]
        assert fired > 0, "no config exercised the rule"

    def test_lds_reduction_predicate_implies_the_gate_refuses(self):
        rule = rc.builtin_rules()["lds_reduction"]
        cfg = {"DataType": "s", "MacroTile": "128x128x8", "ThreadTile": "4x4",
               "WorkGroup": [16, 16, 2]}
        assert rule(cfg)
        assert not occupancy_feasible(cfg)[0]

    def test_apm2_builtin_reads_the_generator_seam_rule(self):
        rule = rc.builtin_rules()["apm2"]
        assert rule({"MacroTile": "64x64x8"}) is None
        assert not rule({"AggressivePerfMode": 1})
        assert rule({"AggressivePerfMode": 2})

    def test_nt_budget_builtin_fires_on_the_phase_that_died(self):
        """The per-thread occupancy limit, after the measured table was fixed.

        It was probed and rejected on 2026-10-18 because it seemed to refuse
        a phase Tensile built (Z tt2x2 at 64x64, 1024 threads, "71 VGPRs").
        That measurement was wrong: the kernel emits **63** VGPRs, which fits
        the 64 a 1024-thread workgroup has. The rule now fires on exactly the
        phases that died with error 4 (SS 256x128 at tt8x4: 77 VGPRs/thread).
        """
        rule = rc.builtin_rules()["nt_budget"]
        # The phase that built: 63 VGPRs/thread over 1024 threads -> fits.
        assert not rule({"DataType": "z", "MacroTile": "64x64x8", "ThreadTile": "2x2"})
        # The phases that died with error 4 in run_20261020_214103.
        assert rule({"DataType": "s", "MacroTile": "256x128x8", "ThreadTile": "8x4"})
        assert rule({"DataType": "s", "MacroTile": "128x256x8", "ThreadTile": "4x8"})
        # The winner geometry: 119 VGPRs/thread over 256 threads -> fits.
        assert not rule({"DataType": "s", "MacroTile": "128x128x8", "ThreadTile": "8x8"})


class TestLoadRule(unittest.TestCase):
    def test_load_from_a_standalone_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mine.py"
            path.write_text("def refuse(cfg):\n    return True\n")
            assert rc.load_rule(f"{path}:refuse")({})

    def test_load_from_an_importable_module(self):
        rule = rc.load_rule("oto.harness.rule_calibration:_refuses_apm2")
        assert rule({"AggressivePerfMode": 2})

    def test_bad_specs_exit(self):
        for spec in ("nocolon", "oto.harness.rule_calibration:no_such_attr",
                     "no_such_module_xyz:refuse"):
            with self.subTest(spec=spec), pytest.raises(SystemExit):
                rc.load_rule(spec)


class TestMain(unittest.TestCase):
    def test_fail_on_false_reject_exits_one(self):
        with tempfile.TemporaryDirectory() as td:
            _make_corpus(Path(td))
            path = Path(td) / "mine.py"
            path.write_text("def refuse(cfg):\n    return True\n")
            with contextlib.redirect_stdout(io.StringIO()):
                code = rc.main(["--base", td, "--rule", f"{path}:refuse",
                                "--fail-on-false-reject"])
            assert code == 1

    def test_clean_builtin_returns_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = rc.main(["--rule", "apm2"])
        assert code == 0


if __name__ == "__main__":
    unittest.main()
