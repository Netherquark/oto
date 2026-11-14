"""Shared adapter helpers: argv plumbing and JSON pass-through.

Owns: the process-wide adapter primitives every command-group adapter uses:
the ``--base-dir``/``.env`` path resolution and the subprocess argv shuffle.
Command-group adapters live in their own modules (this one holds no command).
Does NOT own: the command tree (oto.cli.dispatch dispatches over
``oto.cli.commands`` and its sibling adapters) or the process output policy
(oto.cli.dispatch).
Public API: base_dir, _with_argv, _call, _call_muted, _json_file.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def base_dir(args: Any) -> Path:
    return Path(getattr(args, "base_dir", None) or Path.cwd()).resolve()


def _with_argv(argv: list[str], func: Callable[..., Any]) -> Any:
    old = sys.argv
    sys.argv = ["oto", *argv]
    try:
        return func()
    finally:
        sys.argv = old


def _call(argv: list[str], func: Callable[..., Any]) -> int:
    result = _with_argv(argv, func)
    return int(result or 0)


def _call_muted(argv: list[str], func: Callable[..., Any]) -> int:
    """Run a backend whose narration is not the command's data contract."""
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        return int(_with_argv(argv, func) or 0)
    finally:
        sys.stdout = old


def _json_file(argv: list[str], func: Callable[..., Any]) -> int:
    """Run ``func`` with ``--json <tmp>`` and print the file to stdout.

    The backends already own their JSON schema (candidates, parity, build
    proof, all_runs). We only change the destination: temp file -> stdout, so
    callers see one document and no progress text.
    """
    fd, name = tempfile.mkstemp(prefix="oto-", suffix=".json")
    os.close(fd)
    path = Path(name)
    try:
        code = _call_muted([*argv, "--json", str(path)], func)
        if path.exists() and path.stat().st_size:
            print(path.read_text().rstrip())
        elif code:
            return code
        else:
            print(json.dumps({"ok": code == 0, "output": ""}))
        return code
    finally:
        path.unlink(missing_ok=True)
