#!/usr/bin/env python3
"""
test_auto_prompt.py -- the four --auto questions are asked, and the answers bind.

Regression for the behaviour this replaced: the tier machinery decided on its own
which reference cells to re-measure and how long to run, so a run could spend
days of GPU time on a guess nobody approved.

Run: python3 test_auto_prompt.py
"""
from __future__ import annotations

import io
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

# This file lives in tests/, so the repo root is one level up. BASE is both the
# import root and the data root (phases.yaml, gfx90c_results/), and both are the
# repo root -- the harness modules are imported flat, so they sit beside this
# file's parent rather than in a package.
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import auto_prompt  # noqa: E402
from auto_prompt import (DEFAULT_ITERATIONS, DEFAULT_MUTATIONS, AutoPlan,  # noqa: E402
                         ask)


def fake_tty(answers, isatty=True):
    """Patch stdin so `ask` sees a TTY and receives `answers` in order."""
    stream = io.StringIO("\n".join(answers) + "\n")
    stream.isatty = lambda: isatty
    return mock.patch.object(sys, "stdin", stream)


class TestDefaults(unittest.TestCase):
    """The numbers the user asked for: 10 iterations, 3 mutations."""

    def test_default_iterations_is_ten(self):
        self.assertEqual(DEFAULT_ITERATIONS, 10)

    def test_default_mutations_is_three(self):
        self.assertEqual(DEFAULT_MUTATIONS, 3)

    def test_old_values_are_gone(self):
        self.assertNotEqual(DEFAULT_ITERATIONS, 100)
        self.assertNotEqual(DEFAULT_MUTATIONS, 2)

    def test_prompt_asks_five_questions_in_order(self):
        src = (BASE / "auto_prompt.py").read_text()
        order = [m for m in re.findall(r'"\s*([1-5])\. [^"]+"', src)]
        self.assertEqual(order, ["1", "2", "3", "4", "5"],
                         "the questions must be numbered 1-5 in order")

    def test_plan_defaults_match(self):
        p = AutoPlan()
        self.assertEqual((p.iterations, p.mutations), (10, 3))
        self.assertFalse(p.rerun_illegal)
        self.assertFalse(p.rerun_underspecified)
        self.assertFalse(p.rerun_unreproducible)
        self.assertFalse(p.reruns_any_reference)

    def test_cli_no_longer_defaults_to_100(self):
        import port_tensile
        src = (BASE / "port_tensile.py").read_text()
        self.assertIn('"--budget"', src)
        # the argparse default must be None so the prompt owns it
        idx = src.index('"--budget"')
        window = src[idx:idx + 260]
        self.assertIn("default=None", window)
        del port_tensile


class TestNonInteractive(unittest.TestCase):
    def test_no_tty_takes_defaults_and_says_so(self):
        out = io.StringIO()
        with fake_tty([], isatty=False):
            plan = ask(stream=out)
        self.assertTrue(plan.assumed)
        self.assertEqual(plan.iterations, 10)
        self.assertEqual(plan.mutations, 3)
        self.assertFalse(plan.rerun_illegal)
        self.assertIn("Not an interactive terminal", out.getvalue())

    def test_assume_yes_also_takes_defaults(self):
        out = io.StringIO()
        with fake_tty([], isatty=True):
            plan = ask(stream=out, assume_yes=True)
        self.assertTrue(plan.assumed)
        self.assertEqual(plan.iterations, 10)

    def test_noninteractive_does_not_hang(self):
        """A closed stdin must resolve, not block a cron run forever."""
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            plan = ask(stream=out)
        self.assertEqual(plan.iterations, 10)


class TestInteractiveAnswers(unittest.TestCase):
    def _ask(self, answers):
        out = io.StringIO()
        with fake_tty(answers, isatty=True):
            plan = ask(stream=out)
        return plan, out.getvalue()

    def test_yes_to_all_three_remeasurements(self):
        plan, _ = self._ask(["y", "y", "n", "", ""])
        self.assertTrue(plan.rerun_illegal)
        self.assertTrue(plan.rerun_underspecified)
        self.assertTrue(plan.reruns_any_reference)
        self.assertEqual((plan.iterations, plan.mutations), (10, 3))
        self.assertFalse(plan.assumed)

    def test_no_to_all_three_remeasurements(self):
        plan, _ = self._ask(["n", "n", "n", "", ""])
        self.assertFalse(plan.rerun_illegal)
        self.assertFalse(plan.rerun_underspecified)

    def test_unreproducible_question_is_asked_and_default_is_no(self):
        plan, text = self._ask(["n", "n", "n", "", ""])
        self.assertFalse(plan.rerun_unreproducible)
        self.assertIn("UNREPRODUCIBLE", text)
        self.assertIn("3. Re-attempt the", text)

    def test_unreproducible_can_be_accepted_alone(self):
        plan, _ = self._ask(["n", "n", "y", "", ""])
        self.assertFalse(plan.rerun_illegal)
        self.assertFalse(plan.rerun_underspecified)
        self.assertTrue(plan.rerun_unreproducible)
        self.assertTrue(plan.reruns_any_reference)

    def test_reruns_any_reference_is_false_for_all_no(self):
        plan, _ = self._ask(["n", "n", "n", "", ""])
        self.assertFalse(plan.reruns_any_reference)

    def test_answers_are_independent(self):
        plan, _ = self._ask(["y", "n", "n", "", ""])
        self.assertTrue(plan.rerun_illegal)
        self.assertFalse(plan.rerun_underspecified)

    def test_explicit_numbers(self):
        plan, _ = self._ask(["n", "n", "n", "4", "1"])
        self.assertEqual(plan.iterations, 4)
        self.assertEqual(plan.mutations, 1)

    def test_blank_uses_default(self):
        plan, _ = self._ask(["n", "n", "n", "", ""])
        self.assertEqual(plan.iterations, DEFAULT_ITERATIONS)
        self.assertEqual(plan.mutations, DEFAULT_MUTATIONS)

    def test_long_spelled_yes(self):
        plan, _ = self._ask(["YES", "Yes", "no", "", ""])
        self.assertTrue(plan.rerun_illegal)
        self.assertTrue(plan.rerun_underspecified)

    def test_invalid_number_is_re_asked(self):
        plan, _ = self._ask(["n", "n", "n", "abc", "0", "-3", "7", "2"])
        self.assertEqual(plan.iterations, 7)
        self.assertEqual(plan.mutations, 2)

    def test_banner_shows_live_counts(self):
        _, text = self._ask(["n", "n", "n", "", ""])
        self.assertIn("ILLEGAL", text)
        self.assertIn("UNDER-SPECIFIED", text)
        self.assertIn("UNREPRODUCIBLE", text)
        # all five questions must actually be posed
        for q in ("Re-measure", "iterations", "mutations"):
            self.assertIn(q, text)

    def test_plan_echoed_before_the_run_starts(self):
        _, text = self._ask(["y", "n", "n", "6", "1"])
        self.assertIn("Plan: iterations=6 mutations=1", text)


class TestCountReading(unittest.TestCase):
    def test_counts_match_the_audited_manifest(self):
        """The prompt's numbers must be derived, never transcribed.

        Recomputed here from the same inputs _read_counts uses, so a
        re-triaged cell changes both sides together instead of one of them
        going stale. Deliberately asserts no literal count: the point of this
        test is that nothing in the codebase pins the corpus size.
        """
        import json
        import tensile_library as tlib

        counts = auto_prompt._read_counts(BASE)
        manifest = tlib.load_rerun_manifest(BASE)
        shipped = json.load(
            open(BASE / "gfx90c_results" / "gfx900_shipped_manifest.json"))

        expected = {"illegal": 0, "underspecified": 0, "unreproducible": 0}
        for fam, pats in shipped["families"].items():
            for pat, dt in pats.items():
                for name in dt["kernels"]:
                    tier = tlib.tier_for(
                        {"kernel": tlib._CANON.sub("Cijk", name)}, manifest)
                    if tier == tlib.TIER_FIRST:
                        expected["illegal"] += 1
                    elif tier in tlib.UNDERSPECIFIED_TIERS:
                        expected["underspecified"] += 1
                    elif tier == tlib.TIER_DROP:
                        expected["unreproducible"] += 1

        for tier in ("illegal", "underspecified", "unreproducible"):
            self.assertEqual(counts[tier], expected[tier],
                             f"{tier} count drifted from the audited tiers")
        self.assertEqual(counts["total"],
                         sum(expected.values()),
                         "every shipped cell must land in exactly one tier")

    def test_no_hardcoded_corpus_counts_in_the_prompt_source(self):
        """A transcribed count in the prompt module is a bug, not a comment.

        The banner and the three questions are phrased from _read_counts. This
        keeps the module free of the corpus size so the two cannot diverge.
        """
        src = (BASE / "auto_prompt.py").read_text()
        body = src.split('"""', 2)[-1]  # drop the module docstring
        for literal in ("2285", "1881"):
            self.assertNotIn(
                literal, body,
                f"{literal} is hardcoded in auto_prompt.py; counts must be read live")

    def test_missing_db_yields_zeros_not_a_crash(self):
        counts = auto_prompt._read_counts(Path("/tmp/opencode/does-not-exist"))
        self.assertEqual(counts["illegal"], 0)
        self.assertEqual(counts["underspecified"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
