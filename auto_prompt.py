#!/usr/bin/env python3
"""
auto_prompt.py -- the questions every --auto run must ask first.

The T1/T2/T3 tier machinery decided, without asking, what a re-run would cost:
which reference cells got re-measured, how long the loop ran, and how much it was
allowed to mutate. That was three days of GPU time spent on a guess. The tiers
are still the correct *classification* of the reference corpus, but the decision
now belongs to the person who owns the GPU.

This module asks the questions and returns a plan. It is deliberately
dependency-free and never imports Tensile, so it is safe to unit-test.

    1. re-measure the 127 ILLEGAL cells   (measured with a config we got wrong)
    2. re-measure the 1881 UNDER-SPECIFIED cells (glvw/grvw left to defaults)
    3. re-attempt the 277 UNREPRODUCIBLE cells (this Tensile cannot rebuild them)
    4. how many ITERATIONS               (default 10)
    5. how many MUTATIONS per candidate  (default 3)

Non-interactive runs (cron, CI, no TTY) take documented defaults and say so.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Re-measure the cells that previously ran with a config our own extractors got
#: wrong. These measurements are the ones everything downstream trusts.
QUESTION_ILLEGAL = "rerun_illegal"

#: Re-measure fully-audited but under-specified cells. Costly (a ~1 day GPU
#: re-measurement) and it fixes no known correctness problem, which is exactly
#: why it must be a question rather than a default.
QUESTION_UNDERSPEC = "rerun_underspecified"

#: Re-attempt the cells current Tensile cannot rebuild at all. These were dropped
#: outright on the reasoning that re-running only reproduces the failure -- a
#: reasonable default, but "cannot rebuild" is a statement about *this* Tensile
#: build, not a permanent property of the cell, and a version bump could change
#: it. Cheap to ask, so it is a question rather than a hardcoded drop.
QUESTION_UNREPRODUCIBLE = "rerun_unreproducible"

DEFAULT_ITERATIONS = 10
DEFAULT_MUTATIONS = 3


@dataclass
class AutoPlan:
    """The four answers, resolved. This is what --auto executes."""

    rerun_illegal: bool = False
    rerun_underspecified: bool = False
    rerun_unreproducible: bool = False
    iterations: int = DEFAULT_ITERATIONS
    mutations: int = DEFAULT_MUTATIONS
    #: True when no human was asked (no TTY / --yes). Reported, never hidden.
    assumed: bool = False
    counts: Dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        yn = lambda b: "yes" if b else "no"  # noqa: E731
        return (f"iterations={self.iterations} mutations={self.mutations} "
                f"rerun_illegal={yn(self.rerun_illegal)} "
                f"rerun_underspecified={yn(self.rerun_underspecified)} "
                f"rerun_unreproducible={yn(self.rerun_unreproducible)}"
                + ("  (defaults, non-interactive)" if self.assumed else ""))

    @property
    def reruns_any_reference(self) -> bool:
        """True when the user asked for any reference re-measurement at all."""
        return (self.rerun_illegal or self.rerun_underspecified
                or self.rerun_unreproducible)


def _read_counts(base_dir: Any = None) -> Dict[str, int]:
    """Live counts of each reference tier, best effort.

    A failure here must not stop the run: the counts are only used to phrase the
    question ("re-measure the 127 ..."), and a wrong-but-plausible number is far
    better than refusing to start.
    """
    from pathlib import Path
    import yaml
    from collections import Counter

    import tensile_library as tlib

    base = Path(base_dir or ".")
    counts = {"illegal": 0, "underspecified": 0, "unreproducible": 0}
    try:
        import sqlite3
        db = sqlite3.connect(base / "gfx90c_results" / "registry.db")
        chain = [r[0] for r in db.execute(
            "select run_id from runs where run_id like 'gfx900_ref%' order by run_id")]
    except Exception:
        return counts

    universe: Dict[str, Any] = {}
    for rid in chain:
        p = base / "gfx90c_runs" / rid / "phases_reference.yaml"
        try:
            for ph in yaml.safe_load(p.read_text()) or []:
                universe.setdefault(tlib.phase_key(ph), ph)
        except Exception:
            continue
    if not universe:
        return counts

    try:
        manifest = tlib.load_rerun_manifest(base)
    except Exception:
        manifest = None
    seen = Counter(tlib.tier_for(ph, manifest) for ph in universe.values())
    counts["illegal"] = seen.get(tlib.TIER_FIRST, 0)
    counts["underspecified"] = seen.get(tlib.TIER_HELD, 0) + seen.get(tlib.TIER_LAST, 0)
    counts["unreproducible"] = seen.get(tlib.TIER_DROP, 0)
    counts["total"] = len(universe)
    return counts


def _read(prompt: str, out: Any) -> str:
    """Show `prompt` on `out` and read one line.

    Not `input()`: the prompt is written to the caller's stream rather than
    real stdout, so the whole interaction is capturable in a test and shows up
    in a redirected log.
    """
    print(prompt, end="", file=out, flush=True)
    try:
        return sys.stdin.readline().strip()
    except (EOFError, AttributeError):
        return ""


def _ask_yes_no(question: str, default: bool, out: Any, say: Any = print) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = _read(f"{question} {suffix} ", out).lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def _ask_int(question: str, default: int, out: Any,
             say: Any = print) -> int:
    while True:
        raw = _read(f"{question} (default {default}): ", out)
        if raw == "":
            return default
        try:
            value = int(raw)
        except ValueError:
            say(f"  '{raw}' is not a number.")
            continue
        if value < 1:
            say("  must be at least 1.")
            continue
        return value


def ask(base_dir: Any = None,
        stream: Any = None,
        assume_yes: bool = False) -> AutoPlan:
    """Ask the user and return the resolved plan.

    assume_yes: take defaults without asking (cron, CI, --yes).
    stream:     where the banner goes; defaults to stdout.
    """
    out = stream or sys.stdout
    counts = _read_counts(base_dir)
    illegal = counts.get("illegal", 0)
    under = counts.get("underspecified", 0)
    unrep = counts.get("unreproducible", 0)

    def say(msg: str = "") -> None:
        print(msg, file=out)

    say("=" * 72)
    say("About to start an --auto run. Five decisions, and they are yours:")
    say("=" * 72)
    say(f"  reference corpus: {counts.get('total', 0)} cells")
    say(f"    {illegal:>5}  ILLEGAL          measured with a config we got wrong")
    say(f"    {under:>5}  UNDER-SPECIFIED  glvw/grvw left to Tensile's defaults")
    say(f"    {counts.get('unreproducible', 0):>5}  UNREPRODUCIBLE  cannot be rebuilt")
    say()

    interactive = sys.stdin is not None and sys.stdin.isatty() and not assume_yes
    if not interactive:
        say("Not an interactive terminal -- taking defaults.")
        say("  Use --yes to accept defaults explicitly, or run in a TTY to be asked.")
        say(f"  Default plan: {AutoPlan(counts=counts).summary()}")
        say()
        return AutoPlan(assumed=True, counts=counts)

    say("The ILLEGAL cells are the reference measurements everything else is")
    say("graded against. Skipping them leaves the A/B floor provisional.")
    say("The UNDER-SPECIFIED cells are correct but loose; re-measuring them costs")
    say("roughly a day of GPU time and fixes no known bug.")
    say("The UNREPRODUCIBLE cells cannot be rebuilt by this Tensile build, so")
    say("re-running them only reproduces the failure -- unless Tensile has moved on.")
    say()
    plan = AutoPlan(counts=counts)
    plan.rerun_illegal = _ask_yes_no(
        f"  1. Re-measure the {illegal} ILLEGAL reference cells?", False, out, say)
    plan.rerun_underspecified = _ask_yes_no(
        f"  2. Re-measure the {under} UNDER-SPECIFIED reference cells?", False, out, say)
    plan.rerun_unreproducible = _ask_yes_no(
        f"  3. Re-attempt the {unrep} UNREPRODUCIBLE reference cells?",
        False, out, say)
    plan.iterations = _ask_int("  4. How many iterations?", DEFAULT_ITERATIONS, out, say)
    plan.mutations = _ask_int(
        "  5. How many mutations per candidate?", DEFAULT_MUTATIONS, out, say)
    say()
    say(f"Plan: {plan.summary()}")
    say()
    return plan
