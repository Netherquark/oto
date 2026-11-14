#!/usr/bin/env python3
"""The five --auto questions, and the AutoPlan their answers bind.

Owns: ``ask`` (the TTY prompt, five questions, in answer order), ``AutoPlan``,
the non-TTY defaults, and ``_read_counts`` (tier counts read live from the audited
manifest -- never transcribed).

Does NOT own: what the plan does (oto.runners.auto) or the tier manifest it reads
(oto.tensile.library).

Public API: AutoPlan, ask, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS, _read_counts.

The tier machinery used to decide, without asking, what a re-run would cost:
which reference cells got re-measured, how long the loop ran and how much it was
allowed to mutate. The tiers remain the correct *classification* of the reference
corpus; the decision now belongs to the person who owns the GPU.

    1. re-measure the ILLEGAL cells        (measured with a config we got wrong)
    2. re-measure the UNDER-SPECIFIED cells (glvw/grvw left to defaults)
    3. re-attempt the UNREPRODUCIBLE cells (this Tensile cannot rebuild them)
    4. how many ITERATIONS               (default 10)
    5. how many MUTATIONS per candidate  (default 3)

Every count in the banner and in the questions is read live by ``_read_counts``
from the audited tiers; none of them is written down here. A number transcribed
into a docstring is wrong the moment a cell is re-triaged, and a stale number in
a question the user is answering is worse than no number. Non-interactive runs
(cron, CI, no TTY) take the documented defaults and say so.
"""


from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from oto import yamlio
from oto.device import loader as _loader
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import runs_dir as _runs_dir

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
    counts: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        def yn(b):
            return "yes" if b else "no"
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


def _read_counts(base_dir: Any = None, profile=None) -> dict[str, int]:
    """Live counts of each reference tier, best effort.

    Nothing here is cached or transcribed: the universe is the union of every
    reference chain's phase list, and each phase is classified by `tier_for`
    against the audited manifest. Re-triaging a cell changes the number printed
    in the question on the next run, with no code or doc to update.

    A failure here must not stop the run: the counts are only used to phrase the
    question ("re-measure the N ILLEGAL ..."), and a wrong-but-plausible number
    is far better than refusing to start.
    """
    from collections import Counter
    from pathlib import Path

    import oto.tensile.library as tlib

    base = Path(base_dir or ".")
    counts = {"illegal": 0, "underspecified": 0, "unreproducible": 0}
    try:
        import sqlite3
        db = sqlite3.connect(_results_dir(base, _loader.resolve_profile(profile,).codename) / "registry.db")
        chain = [r[0] for r in db.execute(
            "select run_id from runs where run_id like 'gfx900_ref%' order by run_id")]
    except Exception:
        return counts

    universe: dict[str, Any] = {}
    for rid in chain:
        p = _runs_dir(base, _loader.resolve_profile(profile,).codename) / rid / "phases_reference.yaml"
        try:
            for ph in yamlio.load_yaml(p) or []:
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
    counts["illegal"] = seen.get(tlib.TIER_FIRST, 0,)
    counts["underspecified"] = seen.get(tlib.TIER_HELD, 0,) + seen.get(tlib.TIER_LAST, 0,)
    counts["unreproducible"] = seen.get(tlib.TIER_DROP, 0,)
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

    import os
    assume_yes = (assume_yes or bool(os.environ.get("OTO_YES"))
                  or bool(os.environ.get("OTO_NO_INPUT")))
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
