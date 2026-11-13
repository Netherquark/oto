"""TTY-aware output helpers: colour, width, quiet/verbose.

Owns: the small policy layer between a command and the terminal -- whether
colour is allowed, whether a stream is a TTY, and the stdout/stderr split.
Does NOT own: the rich/tqdm presentation itself (help uses rich-argparse, run
progress uses tqdm); this module only decides whether presentation is allowed.
Public API: is_tty, color_enabled, bold, red, green, yellow, cyan, stderr,
stdout, quiet_check.
"""

from __future__ import annotations

import os
import sys
from typing import Any


def is_tty(stream: Any = None) -> bool:
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def color_enabled(stream: Any = None, no_color: bool = False) -> bool:
    if no_color or os.environ.get("NO_COLOR", ""):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return is_tty(stream)


def _wrap(code: str, text: str, stream: Any = None, no_color: bool = False) -> str:
    if not color_enabled(stream, no_color):
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str, stream: Any = None, no_color: bool = False) -> str:
    return _wrap("1", text, stream, no_color)


def red(text: str, stream: Any = None, no_color: bool = False) -> str:
    return _wrap("31", text, stream, no_color)


def green(text: str, stream: Any = None, no_color: bool = False) -> str:
    return _wrap("32", text, stream, no_color)


def yellow(text: str, stream: Any = None, no_color: bool = False) -> str:
    return _wrap("33", text, stream, no_color)


def cyan(text: str, stream: Any = None, no_color: bool = False) -> str:
    return _wrap("36", text, stream, no_color)


def stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def stdout(msg: str) -> None:
    print(msg)


def quiet_check(quiet: bool, msg: str) -> None:
    if not quiet:
        print(msg)
