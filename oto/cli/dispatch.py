"""The ``oto`` process boundary: parse, apply output policy, dispatch, catch.

Owns: the stdout/stderr contract, ``--quiet``/``--verbose``/``--no-input``/
``--no-color`` policy, the top-level exception -> exit-code translation, and
bare-invocation orientation.
Does NOT own: the command tree (```oto.cli.parser```) or any adapter
(```oto.cli.commands```). Keeping this file small is deliberate: every command
gets the same policy because there is only one process boundary.
Public API: main.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from oto.cli import commands
from oto.cli.errors import handle_error
from oto.cli.parser import build_parser


def _apply_environment(args: Any) -> None:
    """Apply the --no-color/--quiet/--verbose/--no-input flags to the environment."""
    if getattr(args, "no_color", False):
        os.environ["NO_COLOR"] = "1"
    if getattr(args, "quiet", False):
        os.environ["OTO_QUIET"] = "1"
    if getattr(args, "verbose", False):
        os.environ["OTO_VERBOSE"] = "1"
    if getattr(args, "no_input", False):
        os.environ["OTO_NO_INPUT"] = "1"


def _verbose(args: Any, parser: Any) -> None:
    """Print the verbose banner for `args` (no-op unless ``--verbose``)."""
    if not getattr(args, "verbose", False):
        return
    command = getattr(args, "command", "") or "oto"
    rest = " ".join(sys.argv[1:])
    print(f"oto: {rest or command}", file=sys.stderr)
    if getattr(args, "base_dir", None):
        print(f"oto: base={args.base_dir}", file=sys.stderr)


def _mutating_stdout(args: Any) -> Any:
    """Return the stream mutating commands should print narration to.

    Data -> stdout, narration -> stderr. Existing backends print progress on
    stdout, so the boundary redirects that stream rather than rewriting every
    print. ``--quiet`` sends the same narration to /dev/null; errors still go
    to stderr through the exception path.
    """
    if not getattr(args, "mutating", False):
        return sys.stdout
    if getattr(args, "quiet", False):
        return open(os.devnull, "w")
    return sys.stderr


def main(argv: list[str] | None = None) -> int:
    """The process boundary: parse, apply output policy, dispatch, catch. Return the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_environment(args)
    _verbose(args, parser)

    if not getattr(args, "command", None):
        return commands.dispatch(args, parser)

    old_stdout = sys.stdout
    replacement = None
    if getattr(args, "mutating", False):
        replacement = _mutating_stdout(args)
        sys.stdout = replacement
    try:
        return commands.dispatch(args, parser)
    except KeyboardInterrupt as exc:
        return handle_error(exc, verbose=getattr(args, "verbose", False),
                            json_mode=getattr(args, "json", False),
                            base=getattr(args, "base_dir", None),
                            command=getattr(args, "command", ""))
    except SystemExit:
        raise
    except BaseException as exc:
        return handle_error(exc, verbose=getattr(args, "verbose", False),
                            json_mode=getattr(args, "json", False),
                            base=getattr(args, "base_dir", None),
                            command=getattr(args, "command", ""))
    finally:
        sys.stdout = old_stdout
        if replacement is not None and replacement is not sys.stderr:
            replacement.close()


if __name__ == "__main__":
    raise SystemExit(main())
