"""Shared CLI flags for all oto subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Add flags shared by every subcommand."""
    parser.add_argument("--base", "--base-dir", dest="base_dir", type=Path,
                        default=None, help="Base directory (default: cwd)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-essential output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose stderr output")
    parser.add_argument("--no-input", action="store_true", help="Never prompt; fail if input required")


def add_version_flag(parser: argparse.ArgumentParser) -> None:
    from oto._version import __version__
    parser.add_argument("--version", action="version", version=f"oto {__version__}")
