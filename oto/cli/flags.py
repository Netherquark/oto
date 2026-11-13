"""Shared CLI flags for all oto subcommands.

Owns: the one place a global option is declared, so ``--base`` / ``-q`` /
``-v`` / ``--no-input`` / ``--no-color`` mean the same thing on every command.
Does NOT own: what a command does with those values (the dispatcher applies the
output/error policy, and each adapter passes only the flags its backend reads).
Public API: add_global_flags, add_version_flag, add_json_flag, add_dry_run_flag.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from oto._version import __version__


def add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Add the options shared by every subcommand.

    ``--base`` is the one canonical spelling (there is deliberately no
    ``--base-dir`` alias on the new surface). The three verbosity switches are
    policy flags consumed by the dispatcher, not passed through to backends.
    """
    parser.add_argument(
        "--base", dest="base_dir", type=Path, default=None, metavar="PATH",
        help="Project base directory (default: current directory)")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress narration; errors still go to stderr")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show the command being run and full tracebacks on failure")
    parser.add_argument(
        "--no-input", action="store_true",
        help="Never prompt; take documented defaults or fail")
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colour (also honours NO_COLOR)")


def add_version_flag(parser: argparse.ArgumentParser) -> None:
    """Root-only ``--version``; subcommands expose ``oto version`` too."""
    parser.add_argument("--version", action="version", version=f"oto {__version__}")


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    """Machine-readable output for read-only commands.

    Mutating commands deliberately do not get this: their result is a run and a
    log, not a data document. Keeping the flag off them prevents a caller from
    mistaking a progress stream for a machine contract.
    """
    parser.add_argument("--json", action="store_true",
                        help="Emit one JSON document on stdout; silence narration")


def add_dry_run_flag(parser: argparse.ArgumentParser) -> None:
    """For commands that change state: show the plan without executing it."""
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Show what would happen without executing")
