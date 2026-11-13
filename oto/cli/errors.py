"""Exit codes and error handling for the oto CLI."""

from __future__ import annotations

import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

ERROR_HINTS: dict[str, str] = {
    "TENSILE_ROOT": "Set TENSILE_ROOT in .env or environment. Run 'oto doctor' for diagnostics.",
    "registry": "Run 'oto check db' or pass --base <path>.",
    "GPU": "GPU not detected. Run 'oto doctor' to check hardware.",
    "profile": "No profile for codename. Check profiles/ directory.",
}


class OtoError(Exception):
    """Base exception for oto CLI errors."""

    def __init__(self, message: str, hint: str = "", exit_code: int = EXIT_FAIL):
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code


def handle_error(exc: Exception, quiet: bool = False) -> int:
    """Print an error to stderr and return an exit code."""
    if isinstance(exc, OtoError):
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        return exc.exit_code
    # Unknown error — save traceback
    import traceback
    tb = traceback.format_exc()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "oto-error.log"
    log_path.write_text(tb)
    print(f"error: {exc}", file=sys.stderr)
    print(f"traceback saved to {log_path}", file=sys.stderr)
    return EXIT_FAIL
