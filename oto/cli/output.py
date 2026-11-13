"""TTY-aware output helpers: color, width, quiet/verbose."""

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


def color_enabled(stream: Any = None) -> bool:
    if os.environ.get("NO_COLOR", ""):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return is_tty(stream)


def bold(text: str, stream: Any = None) -> str:
    if not color_enabled(stream):
        return text
    return f"\033[1m{text}\033[0m"


def red(text: str, stream: Any = None) -> str:
    if not color_enabled(stream):
        return text
    return f"\033[31m{text}\033[0m"


def green(text: str, stream: Any = None) -> str:
    if not color_enabled(stream):
        return text
    return f"\033[32m{text}\033[0m"


def yellow(text: str, stream: Any = None) -> str:
    if not color_enabled(stream):
        return text
    return f"\033[33m{text}\033[0m"


def cyan(text: str, stream: Any = None) -> str:
    if not color_enabled(stream):
        return text
    return f"\033[36m{text}\033[0m"


def stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def stdout(msg: str) -> None:
    print(msg)


def quiet_check(quiet: bool, msg: str) -> None:
    if not quiet:
        print(msg)
