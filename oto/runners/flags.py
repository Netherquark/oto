#!/usr/bin/env python3
"""The driver's argparse flags, one helper per group.

Owns: the seven `_add_*_flags` helpers that `build_parser` composes. Each helper
takes the parser and adds one coherent group of flags, so a flag's grouping and
its meaning are stated in the same place. Adding a flag that is never read is
caught by tests/test_interactive_keys.py.
Does NOT own: the stage dispatch that reads the parsed flags
(oto.runners.cli), or the --auto plan the answers become
(oto.runners.auto_prompt).
Public API: build_parser.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _add_scope_flags(parser: argparse.ArgumentParser) -> None:
    """Where to run, and what to run.

    Why: `--base-dir` and `--tensile-root` are the only two inputs with no
    sensible default. A guessed Tensile root shells out to the wrong Tensile and
    produces a corpus that looks like measurements of this device, so both are
    required, never inferred.
    """
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Base directory for the project (default: cwd)"
    )
    parser.add_argument(
        "--tensile-root",
        type=Path,
        default=None,
        help="Tensile source tree root"
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        help="Target IDs or labels to execute (e.g., target_ss_Ailk_Bjlk_1024x1024x1024)"
    )
    parser.add_argument(
        "--family",
        nargs="+",
        help="Filter targets by family (e.g., --family SS or --family CC DD HH)"
    )
    parser.add_argument(
        "--pattern",
        nargs="+",
        help="Filter targets by contraction pattern (e.g., --pattern Ailk_Bjlk Ailk_Bljk)"
    )
    parser.add_argument(
        "--shape",
        nargs="+",
        help="Filter targets by problem shape (e.g., --shape 1024x1024x1024 2048x2048x2048)"
    )
    parser.add_argument(
        "--stage",
        nargs="+",
        help="Specific pipeline stage(s) to execute (1..7 or names: preflight, candidate, benchmark, retirement, analytics, synthesis, report)"
    )


def _add_auto_flags(parser: argparse.ArgumentParser) -> None:
    """The --auto loop's flags.

    Why: `--budget` and `--mutation-budget` default to None on purpose. The four
    decisions (including these two) are asked interactively at the start of
    --auto, and a hardcoded default here would pre-answer a question the user
    has not been asked. See claude.md section 5.
    """
    parser.add_argument(
        "--report",
        nargs="?",
        const="",
        default=None,
        help="Regenerate the acceptance report for RUN_ID from the registry (default: latest run)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run Stage 1-7 deterministic auto-convergence loop across all shipped gfx900 families"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="Auto-convergence iterations. Asked interactively at the start of "
             "--auto; default 10 when not a TTY."
    )
    parser.add_argument(
        "--mutation-budget",
        type=int,
        default=None,
        help="Maximum knobs to mutate per candidate. Asked interactively at the "
             "start of --auto; default 3 when not a TTY."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept the default --auto plan (no illegal rerun, no "
             "under-specified rerun, no unreproducible rerun, 10 iterations, "
             "3 mutations) without being asked. For cron/CI."
    )


def _add_reference_flags(parser: argparse.ArgumentParser
                         ) -> argparse._MutuallyExclusiveGroup:
    """The gfx900 reference-floor flags, mutually exclusive with --native.

    Why: asking for the floor and refusing it in the same invocation is a
    contradiction, so argparse rejects the pair rather than the driver guessing
    which one the operator meant.
    """
    ref_group = parser.add_mutually_exclusive_group()
    ref_group.add_argument(
        "--gfx900-reference",
        action="store_true",
        help="One-time benchmark of every shipped gfx900 kernel from the system "
             "TensileLibrary.dat into a dedicated gfx900_ref_* run (recalled forever)"
    )
    ref_group.add_argument(
        "--native",
        action="store_true",
        help="Run auto-convergence without gfx900 reference floor (native-only tuning)"
    )
    return ref_group


def _add_release_flags(parser: argparse.ArgumentParser) -> None:
    """The non-interactive spelling of --auto questions 2 and 3.

    Why: one-directional. A flag can say yes; the prompt (or its absence)
    decides otherwise. Bundling them would let one flag silently release both
    tiers, which claude.md section 5 forbids.
    """
    parser.add_argument(
        "--release-under-specified",
        action="store_true",
        help="Non-interactive equivalent of answering 'yes' to question 2 "
             "(re-measure the UNDER-SPECIFIED reference cells). --auto asks "
             "interactively; this flag exists for cron/CI or when the same choice "
             "is being made repeatedly."
    )
    parser.add_argument(
        "--release-unreproducible",
        action="store_true",
        help="Non-interactive equivalent of answering 'yes' to question 3 "
             "(re-attempt the UNREPRODUCIBLE reference cells). They are dropped "
             "by default because this Tensile build cannot rebuild them. Use "
             "after a Tensile upgrade, where 'unreproducible' may no longer hold."
    )


def _add_reference_run_flags(parser: argparse.ArgumentParser) -> None:
    """Modifiers for the reference-floor run itself (shape, limit, resume)."""
    parser.add_argument(
        "--phase-timeout",
        type=int,
        default=3600,
        help="Per-target timeout in seconds (default: 3600)"
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=30,
        help="Inter-target cooldown in seconds (default: 30)"
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Run Stage 6 (synthesis + anti-alias scan + regression gate)"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run Stage 1 preflight validation checks"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="With --gfx900-reference: re-scan the system dat and re-pin the manifest"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="With --gfx900-reference: benchmark at most N shipped phases, one per "
             "family (smoke test)"
    )
    parser.add_argument(
        "--ref-shapes",
        type=str,
        default=None,
        help="With --gfx900-reference: restrict the deck to these cube sides "
             "(comma-separated, e.g. 256,512) for light runs"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="With --gfx900-reference: only benchmark the reference deck phases "
             "that have no completed verdict yet (continues the newest completed "
             "run; previously-failed phases are attempted once more)"
    )


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    """Per-run behaviour: force, the live status panel, and the dry run."""
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if identical fingerprint already passed"
    )
    parser.add_argument(
        "--live",
        choices=("on", "off"),
        default="on",
        help="Repaint run_status in the TTY while phases execute (default: on). "
             "CPU-only -- reads the registry, no GPU work. Degrades to periodic "
             "plain lines when stdout is not a terminal, so piped logs stay "
             "readable. Use --live off for a quiet transcript."
    )
    parser.add_argument(
        "--live-interval",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="Seconds between live status repaints (default: 30)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matched targets without executing benchmarks"
    )


def _add_agg_flag(parser: argparse.ArgumentParser) -> None:
    """Which statistic the acceptance delta is computed on.

    Why: the nine bases are documented on `oto.metrics.ab_delta._stat`; the
    default (`winner`) is the drop-in-replacement reading, and the native arm
    always spans the whole database so the report may be won by an older run.
    """
    parser.add_argument(
        "--native-agg",
        choices=("median", "best_median", "floor_best", "strict", "winner",
                 "winner_clock", "median_clock", "throttle", "best"),
        default="winner",
        help="Comparison basis that decides the acceptance delta, per "
             "(family, dtype, shape) cell. 'winner' (default) = BEST vs BEST: "
             "each arm's best per-kernel median, the drop-in-replacement "
             "question. 'winner_clock' = the same, telemetry-adjusted: every "
             "kernel's median is scaled by (sclk_ref / sclk_measured) from its "
             "own phase's sustained core clock so a cool-running kernel is not "
             "credited with being slow; needs per-phase telemetry on BOTH arms "
             "and falls back (flagged clock_adjusted=false) where it is "
             "missing. 'floor_best' = floor's best vs the deck's MEDIAN. "
             "'strict' = native WORST vs floor best (per-cell dominance, the "
             "literal 'truly better in every way'). 'best_median' = deck best "
             "vs floor median. 'median'/'median_clock'/'throttle' are "
             "symmetric; 'best' = max single raw sample (seed-noisy, reference "
             "only). All statistics are per-kernel-median-first. The native arm "
             "always spans the whole database, so the report may be won by an "
             "older run."
    )
    parser.add_argument(
        "--protocol-basis",
        choices=("family", "any", "single", "partial"),
        default="family",
        help="The invocation form verdicts admit (§R56.3): 'family' (default) "
             "grades only records measured under the family-wide protocol the "
             "gfx900 floor itself uses -- the like-for-like basis; the "
             "pre-basis mixed winner stays in the payload as "
             "native_best_any_protocol. 'single' pairs only single-problem "
             "records; 'any' reproduces the pre-§R56.3 unfiltered pairing "
             "for reference."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the driver's argument parser.

    Every flag lives in one of the group helpers above, so a flag's grouping and
    its meaning are stated in the same place. Adding a flag that is never read
    is caught by tests/test_interactive_keys.py.

    Returns:
        An ``ArgumentParser`` with every flag the driver accepts.
    """
    parser = argparse.ArgumentParser(
        description="port_tensile.py — oto driver for gfx90c Tensile port"
    )
    _add_scope_flags(parser)
    _add_auto_flags(parser)
    _add_reference_flags(parser)
    _add_release_flags(parser)
    _add_reference_run_flags(parser)
    _add_run_flags(parser)
    _add_agg_flag(parser)
    return parser
