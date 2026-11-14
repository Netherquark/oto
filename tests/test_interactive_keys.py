#!/usr/bin/env python3
"""Tests for the 's'/'e'/'q' key wiring and the CLI option surface.

No GPU. `_read_key` is exercised against a fake stdin, and `run_phases` is
driven over a deck that every policy gate rejects, which is the state that used
to leave the keys dead (see TestKeysDuringIdenticalFpSkip).

Two things are pinned:

  1. The keys work while phases are being SKIPPED, not only while a Tensile
     process is running. A skip does no GPU work and previously polled no keys
     at all, so a deck whose phases were all already-passed ignored 'q'
     completely.
  2. Every declared --option is actually read somewhere. An option that is
     declared but never consulted is worse than absent: it looks like a working
     knob and silently does nothing.
"""
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# `_read_key` lives in the phase-execution mixin; the skip policy it feeds
# lives in the phase-runner mixin; the option surface lives in the CLI module.
# Patch each where the implementation looks it up.
import oto.runners.benchmark as bench_mod
import oto.runners.driver as pt
import oto.runners.phase_runner as phases_mod
from oto.runners.result_paths import runs_rel

# The parser and the option wiring live in the CLI module; the entrypoint the
# operator actually runs is the repo-root CLI entry (`python3 -m oto`).
DRIVER_SRC = ROOT / "oto" / "runners" / "stage_cli.py"
CLI_ARGS = ["-m", "oto", "tune"]


class FakeStdin:
    """Minimal isatty/select-compatible stdin stub.

    `keys` is consumed one byte per isatty() call, so a test can queue exactly
    the keystrokes it wants delivered and nothing else.
    """

    def __init__(self, keys=(), tty=True):
        self.keys = list(keys)
        self.tty = tty

    def isatty(self):
        return self.tty

    def read(self, _n=1):
        return self.keys.pop(0) if self.keys else ""

    def fileno(self):
        return 0


class TestReadKey(unittest.TestCase):
    def _driver(self):
        return pt.TensileDriver.__new__(pt.TensileDriver)

    def test_returns_empty_when_stdin_is_not_a_tty(self):
        d = self._driver()
        with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(tty=False)):
            with mock.patch.object(bench_mod.time, "sleep") as slept:
                assert d._read_key() == ""
                assert slept.called, "spin-wait loop must not busy-spin"

    def test_block_false_does_not_sleep(self):
        """A skip loop does real work per phase; it must not pay a poll interval."""
        d = self._driver()
        with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(tty=False)):
            with mock.patch.object(bench_mod.time, "sleep") as slept:
                assert d._read_key(block=False) == ""
                slept.assert_not_called()

    def test_reads_and_lowercases_a_key(self):
        d = self._driver()
        with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(keys=["Q"])):
            with mock.patch.object(bench_mod.select, "select", return_value=([0], [], [])):
                assert d._read_key() == "q"

    def test_no_key_ready_returns_empty(self):
        d = self._driver()
        with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(keys=[])):
            with mock.patch.object(bench_mod.select, "select", return_value=([], [], [])):
                assert d._read_key() == ""

    def test_closed_stdin_does_not_raise(self):
        """A detached stdin must not take a running phase down."""
        d = self._driver()
        broken = FakeStdin(keys=["q"])
        broken.fileno = mock.Mock(side_effect=OSError("detached"))
        with mock.patch.object(bench_mod.sys, "stdin", broken):
            with mock.patch.object(bench_mod.select, "select", side_effect=OSError("detached")):
                assert d._read_key() == ""


class TestKeysDuringIdenticalFpSkip(unittest.TestCase):
    """The bug: a deck that policy skips entirely ignored the run-wide keys."""

    def _driver_with_skips(self, run_dir):
        d = pt.TensileDriver.__new__(pt.TensileDriver)
        d.run_dir = run_dir
        d.base_dir = run_dir.parent.parent
        d._stop_requested = False
        d._finish_after_iteration = False
        d._last_run_status = None
        d._live_status = None
        d.registry = mock.Mock()
        d._start_live_status = lambda *a, **k: None
        d._stop_live_status = lambda *a, **k: None
        return d

    def _phases(self, n=5):
        return [{"phase_id": f"phase_{i}", "label": f"p{i}",
                 "fp": "deadbeef", "config": {"DataType": "S"}}
                for i in range(n)]

    def _run(self, d, phases):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "phases.yaml"
            import yaml
            deck.write_text(yaml.safe_dump(phases))
            run_dir = Path(td) / runs_rel("run_x")
            run_dir.mkdir(parents=True)
            d.run_dir = run_dir
            d.base_dir = Path(td)
            # Policy rejects every phase -> the all-skipped path.
            with mock.patch.object(phases_mod, "should_run",
                                   return_value=(False, "identical fp already passed")):
                return d.run_phases(phases_path=deck)

    def test_q_stops_a_fully_skipped_deck(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / runs_rel("run_x")
            run_dir.mkdir(parents=True)
            d = self._driver_with_skips(run_dir)
            # 'q' delivered on the first skip; every later phase must not run.
            with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(keys=["q"])):
                with mock.patch.object(bench_mod.select, "select",
                                       return_value=([0], [], [])):
                    self._run(d, self._phases(5))
            assert d._stop_requested, "'q' was ignored during skips"
            assert d.registry.append_record.call_count == 1, "run must stop at the first skip, not drain the deck"

    def test_e_stops_a_fully_skipped_deck(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / runs_rel("run_x")
            run_dir.mkdir(parents=True)
            d = self._driver_with_skips(run_dir)
            with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(keys=["e"])):
                with mock.patch.object(bench_mod.select, "select",
                                       return_value=([0], [], [])):
                    self._run(d, self._phases(5))
            assert d._finish_after_iteration, "'e' was ignored during skips"
            assert d.registry.append_record.call_count == 1

    def test_unrelated_keys_do_not_stop_the_run(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / runs_rel("run_x")
            run_dir.mkdir(parents=True)
            d = self._driver_with_skips(run_dir)
            # 's' has nothing to skip here; the deck must still drain.
            with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(keys=["s"])):
                with mock.patch.object(bench_mod.select, "select",
                                       return_value=([0], [], [])):
                    self._run(d, self._phases(3))
            assert not d._stop_requested
            assert not d._finish_after_iteration
            assert d.registry.append_record.call_count == 3

    def test_user_quit_is_reported_as_interrupted_not_skipped(self):
        """A run the operator stopped must not be filed as 'skipped'.

        'skipped' means the corpus already had these measurements, which is a
        completely different statement from 'the operator stopped it'.
        """
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / runs_rel("run_x")
            run_dir.mkdir(parents=True)
            d = self._driver_with_skips(run_dir)
            with mock.patch.object(bench_mod.sys, "stdin", FakeStdin(keys=["q"])):
                with mock.patch.object(bench_mod.select, "select",
                                       return_value=([0], [], [])):
                    self._run(d, self._phases(5))
            assert d._last_run_status == "interrupted"


class TestCliOptionSurface(unittest.TestCase):
    """Every declared --option must be consulted somewhere in main()'s wiring."""

    def _declared_and_read(self):
        src = DRIVER_SRC.read_text()
        tree = ast.parse(src)
        declared = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument":
                for a in n.args:
                    if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                            and a.value.startswith("--")):
                        declared.add(a.value[2:].replace("-", "_"))
        read = set()
        for n in ast.walk(tree):
            # args.X and args.X.Y
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                    and n.value.id == "args":
                read.add(n.attr)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) \
                    and isinstance(n.value.value, ast.Name) \
                    and n.value.value.id == "args":
                read.add(n.value.attr)
            # getattr(args, "x", ...) -- used for the release-* flags
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "getattr" \
                    and n.args and isinstance(n.args[0], ast.Name) \
                    and n.args[0].id == "args" and len(n.args) > 1 \
                    and isinstance(n.args[1], ast.Constant):
                read.add(n.args[1].value)
        return declared, read

    def test_no_option_is_declared_but_never_read(self):
        declared, read = self._declared_and_read()
        dead = sorted(declared - read)
        assert dead == [], f"declared but never consulted: {dead}. An option that " f"does nothing still looks like a working knob."

    def test_options_actually_reach_the_parser(self):
        """--help must list the options; catches a flag added outside argparse."""
        res = subprocess.run(
            [sys.executable, *CLI_ARGS, "--help"],
            capture_output=True, text=True, timeout=180)
        assert res.returncode == 0, res.stderr
        declared, _ = self._declared_and_read()
        missing = [d for d in sorted(declared) if f"--{d.replace('_', '-')}" not in res.stdout]
        assert missing == [], f"in parser but absent from --help: {missing}"

    def test_force_is_the_documented_way_to_defeat_identical_fp_skip(self):
        """--force must reach run_phases as opt_in_identical_skip=False.

        This is the user-facing escape from the skip path the keys now work in,
        so a silent wiring break here would make the deck unrunnable-in-practice.
        """
        src = DRIVER_SRC.read_text()
        assert "opt_in_identical_skip=not args.force" in src


class TestPreflightNeedsNoRunDir(unittest.TestCase):
    """A preflight-only invocation must not leave a phantom 'started' run.

    The driver creates its run directory in ``__init__``; before this predicate
    existed, every documented ``--preflight`` left an empty run behind that the
    next launch then had to clean up as 'interrupted'.
    """

    @staticmethod
    def _ends(preflight, stage):
        from oto.runners.stage_cli import _ends_after_preflight
        return _ends_after_preflight(mock.Mock(preflight=preflight), set(stage))

    def test_preflight_alone_and_stage_1_stop_without_a_run(self):
        assert self._ends(True, ())
        assert self._ends(True, ("1",))
        assert self._ends(False, ("1",))

    def test_a_stage_that_needs_a_run_is_not_preflight_only(self):
        assert not self._ends(True, ("3",))
        assert not self._ends(False, ("3",))
        assert not self._ends(True, ("preflight", "2"))


if __name__ == "__main__":
    unittest.main()
