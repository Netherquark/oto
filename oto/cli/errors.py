"""Exit codes, error rewrites, and the traceback file.

Owns: the POSIX exit-code contract (0 ok, 1 failure, 2 usage), the map from a
known failure to a remediation hint, and the durable traceback file for an
unknown failure.
Does NOT own: printing ordinary command output (the dispatcher's stdout/stderr
contract) or logging a run's progress (the run directory owns its logs).
Public API: EXIT_*, OtoError, handle_error, exit_code_for.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

#: Ordered: first match wins. Keep the patterns specific -- a broad "not found"
#: would turn every typo into a registry hint.
ERROR_HINTS: tuple[tuple[str, str], ...] = (
    ("tensile_root is not set",
     "Set TENSILE_ROOT in the environment or repo-root .env. Run 'oto doctor'."),
    ("tensile_root", "Set TENSILE_ROOT in the environment or repo-root .env. Run 'oto doctor'."),
    ("no such file or directory: 'registry.db'",
     "The registry is missing. Run 'oto doctor' and 'oto check db'."),
    ("unable to open database file",
     "The registry is missing or unreadable. Run 'oto doctor'."),
    ("registry", "Run 'oto doctor' and 'oto check db'."),
    ("no gpu", "No GPU detected. Run 'oto doctor'; benchmarks need /dev/kfd."),
    ("gpu not", "No GPU detected. Run 'oto doctor'; benchmarks need /dev/kfd."),
    ("rocminfo", "ROCm discovery failed. Run 'oto doctor'."),
    ("profile", "No device profile matches this codename. Check profiles/<codename>.json."),
    ("module not found", "A dependency is missing. Run 'oto doctor'."),
    ("permission denied", "Permission denied. Check the file/directory owner and mode."),
    ("no space left", "The disk is full; free space, then re-run 'oto status'."),
)

try:
    ISSUE_URL = "https://github.com/Netherquark/oto/issues/new"
except Exception:  # pragma: no cover - constant
    ISSUE_URL = "https://github.com/Netherquark/oto/issues"


class OtoError(Exception):
    """A failure the CLI already knows how to explain."""

    def __init__(self, message: str, hint: str = "", exit_code: int = EXIT_FAIL):
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code


def exit_code_for(exc: BaseException) -> int:
    """Map a known exception to the POSIX status the shell should see."""
    if isinstance(exc, OtoError):
        return exc.exit_code
    if isinstance(exc, KeyboardInterrupt):
        return EXIT_INTERRUPTED
    return EXIT_FAIL


def _hint_for(exc: BaseException) -> str:
    if isinstance(exc, OtoError):
        return exc.hint
    text = str(exc).lower()
    for pattern, hint in ERROR_HINTS:
        if pattern in text:
            return hint
    return ""


def _traceback_path(base: Path | None) -> Path:
    log_dir = (base or Path.cwd()) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return log_dir / f"oto-{stamp}.log"


def _write_traceback(exc: BaseException, base: Path | None) -> Path:
    path = _traceback_path(base)
    body = [
        f"oto traceback — {datetime.now(UTC).isoformat()}",
        f"python: {platform.python_version()} on {platform.platform()}",
        f"argv: {sys.argv!r}",
        "",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "",
        f"Report this at {ISSUE_URL} and attach this file.",
    ]
    path.write_text("\n".join(body))
    return path


def handle_error(exc: BaseException, *, quiet: bool = False,
                 verbose: bool = False, json_mode: bool = False,
                 base: Path | None = None,
                 command: str = "") -> int:
    """Print the error contract and return a POSIX exit code.

    Known failures print ``error:`` + a one-line hint. Unknown failures also
    write a timestamped traceback under ``<base>/logs/``. ``--json`` emits one
    envelope on stdout and keeps stderr quiet; human mode writes only stderr.
    """
    code = exit_code_for(exc)
    hint = _hint_for(exc)
    interrupted = isinstance(exc, KeyboardInterrupt)
    message = "interrupted by user" if interrupted else str(exc) or type(exc).__name__

    log_path: Path | None = None
    if not hint and not interrupted:
        log_path = _write_traceback(exc, base)
        hint = f"traceback saved to {log_path}; report it at {ISSUE_URL}"

    if json_mode:
        payload = {"ok": False,
                   "error": {"code": code, "message": message,
                             "hint": hint, "command": command}}
        if log_path is not None:
            payload["error"]["traceback"] = str(log_path)
        print(json.dumps(payload, indent=2))
        return code

    print(f"error: {message}", file=sys.stderr)
    if hint:
        print(f"hint: {hint}", file=sys.stderr)
    if interrupted:
        print("hint: run 'oto status' to see the run state.", file=sys.stderr)
    if verbose and not interrupted:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return code


def warn(msg: str) -> None:
    """One-line non-fatal diagnostic on stderr (never stdout)."""
    if os.environ.get("OTO_QUIET"):
        return
    print(f"warning: {msg}", file=sys.stderr)
