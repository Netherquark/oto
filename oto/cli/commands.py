"""Adapters from the ``oto`` command tree to existing backends.

Owns: argument translation and the read-command JSON contract (one document on
stdout, no narration). Every adapter is deliberately thin; the work stays in the
owning module.
Does NOT own: the parser (``oto.cli.parser``), the process-wide output policy
(``oto.cli.dispatch``), or any stage's behaviour.
Public API: dispatch, show_help, write_completions.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oto.cli.errors import EXIT_FAIL

#: Stage names that are read-only enough to answer ``--json`` at the stage level.
#: Stage names with a real structured payload for ``--json``. Everything else
#: that is read-only falls back to capturing the stage's own output.
_STRUCTURED_STAGE_JSON = frozenset({"candidate", "2"})


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


def _common_run_argv(args: Any) -> list[str]:
    argv = ["--base-dir", str(base_dir(args))]
    for key, flag in (("targets", "--targets"), ("family", "--family"),
                      ("pattern", "--pattern"), ("shape", "--shape")):
        values = getattr(args, key, None)
        if values:
            argv += [flag, *values]
    if getattr(args, "tensile_root", None):
        argv += ["--tensile-root", str(args.tensile_root)]
    if getattr(args, "live", None):
        argv += ["--live", args.live]
    if getattr(args, "live_interval", None):
        argv += ["--live-interval", str(args.live_interval)]
    if getattr(args, "force", False):
        argv += ["--force"]
    if getattr(args, "dry_run", False):
        argv += ["--dry-run"]
    return argv


# ------------------------------------------------------------------ core

def run_tune(args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main

    argv = _common_run_argv(args)
    if args.budget is not None:
        argv += ["--budget", str(args.budget)]
    if args.mutations is not None:
        argv += ["--mutation-budget", str(args.mutations)]
    if args.resume:
        argv += ["--resume"]
    if args.include_illegal:
        argv += ["--release-illegal"]
    if args.include_underspecified:
        argv += ["--release-under-specified"]
    if args.include_unreproducible:
        argv += ["--release-unreproducible"]
    if args.yes or args.no_input or os.environ.get("OTO_YES"):
        argv += ["--yes"]
    argv += ["--auto"]
    return _call(argv, cli_main)


def run_stages(args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main

    argv = _common_run_argv(args)
    if args.stage:
        argv += ["--stage", *args.stage]
    return _call(argv, cli_main)


def run_bench(args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main

    selectors = bool(args.targets or args.family or args.pattern or args.shape)
    argv = _common_run_argv(args)
    if args.native:
        argv += ["--native"]
    elif selectors or args.dry_run:
        argv += ["--stage", "benchmark"]
    else:
        argv += ["--gfx900-reference"]
        if args.limit is not None:
            argv += ["--limit", str(args.limit)]
        if args.ref_shapes:
            argv += ["--ref-shapes", args.ref_shapes]
        if args.resume:
            argv += ["--resume"]
        if args.refresh:
            argv += ["--refresh"]
    return _call(argv, cli_main)


def run_preflight(args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main

    argv = ["--base-dir", str(base_dir(args)), "--stage", "preflight"]
    if getattr(args, "tensile_root", None):
        argv += ["--tensile-root", str(args.tensile_root)]
    if args.json:
        old = sys.stdout
        sys.stdout = sys.stderr
        try:
            code = _call(argv, cli_main)
        finally:
            sys.stdout = old
        print(json.dumps({"ok": code == 0, "command": "preflight"}))
        return code
    return _call(argv, cli_main)


def run_stage(name: str, args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main
    from oto.tensile.library_parity import load_pipeline_phases

    argv = ["--base-dir", str(base_dir(args)), "--stage", name]
    if getattr(args, "tensile_root", None):
        argv += ["--tensile-root", str(args.tensile_root)]
    if getattr(args, "dry_run", False):
        argv += ["--dry-run"]
    if getattr(args, "json", False):
        if name in _STRUCTURED_STAGE_JSON:
            phases = load_pipeline_phases(str(base_dir(args)))
            fams: dict[str, int] = {}
            for p in phases or []:
                lbl = str(p.get("label") or "")
                fam = "?"
                for f in ("HH_HPA", "HS_HPA", "SS", "DD", "HH", "CC", "ZZ"):
                    if f in lbl:
                        fam = f
                        break
                fams[fam] = fams.get(fam, 0) + 1
            print(json.dumps({
                "ok": True, "stage": name,
                "phases": len(phases or []), "families": fams,
            }, indent=2, default=str))
            return 0
        # Read-only stages with no backend JSON schema: capture the stage's
        # own output and hand it to the caller as one JSON document.
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _call(argv, cli_main)
        print(json.dumps({
            "ok": rc == 0, "stage": name, "output": buf.getvalue(),
        }, indent=2, default=str))
        return rc
    return _call(argv, cli_main)


# ---------------------------------------------------------------- read side

def run_status(args: Any) -> int:
    from oto.metrics.render_status import main as rs_main

    argv = ["--base", str(base_dir(args))]
    if args.run:
        argv += ["--run", args.run]
    if args.plan:
        argv += ["--plan", *args.plan]
    if args.watch:
        argv += ["--watch", str(args.watch)]
    if args.thermals:
        argv += ["--thermals"]
    if args.json:
        argv += ["--json"]
    return int(rs_main(argv) or 0)


def run_report(args: Any, profile=None) -> int:
    """Report subcommand: resolve the run and render its report. ``profile`` selects the device; ambient by default."""
    from oto.device import loader as _loader
    from oto.runners.paths import results_dir as _results_dir
    from oto.runners.stage_cli import main as cli_main

    argv = ["--base-dir", str(base_dir(args)), "--report"]
    if args.run:
        argv += [args.run]
    code = _call_muted(argv, cli_main)
    if not args.json:
        return code
    report = _results_dir(base_dir(args), _loader.resolve_profile(profile).codename) / "acceptance_report.json"
    if report.exists():
        print(report.read_text().rstrip())
        return code
    print(json.dumps({"ok": False, "error": {"code": code,
                                             "message": "report was not emitted"}}))
    return code or EXIT_FAIL


def run_doctor(args: Any) -> int:
    from oto.cli.doctor import run as _run

    return _run(base_dir(args), json_mode=args.json, quiet=args.quiet)


def run_verify_all(args: Any) -> int:
    from oto.tools.verifiers.verify_all import main as va_main

    argv = ["--json"] if args.json else []
    return _call(argv, va_main)


def run_verify_run(args: Any) -> int:
    from oto.tools.corpus_audit import main as vr_main

    argv = ["--base-dir", str(base_dir(args)), args.verify_cmd]
    if args.verify_cmd == "snapshot" and args.out:
        argv += ["--out", args.out]
    elif args.verify_cmd == "diff":
        argv += [args.before, args.after]
    elif args.verify_cmd == "telemetry":
        argv += [args.run_id]
    elif args.verify_cmd == "cheapest":
        if args.family:
            argv += ["--family", args.family]
        argv += ["--n", str(args.n)]
    if args.json:
        argv += ["--json"]
    return _call(argv, vr_main)


def run_check(args: Any) -> int:
    name = args.check_cmd
    base = str(base_dir(args))
    if name == "candidates":
        from oto.checks.deck_legality import main as m
        argv = ["--base-dir", base]
        if args.deck:
            argv += ["--deck", args.deck]
        if args.family:
            argv += ["--family", args.family]
        if args.floor:
            argv += ["--floor"]
        if args.quiet:
            argv += ["--quiet"]
        return _json_file(argv, m) if args.json else _call(argv, m)
    if name == "db":
        from oto.checks.registry_audit import main as m
        argv = ["--base-dir", base] + (["--json"] if args.json else [])
        return _call(argv, m)
    if name == "retirement":
        from oto.checks.retirement import main as m
        argv = ["--base-dir", base] + (["--json"] if args.json else [])
        return _call(argv, m)
    if name == "library-parity":
        from oto.checks.library_parity import main as m
        argv = ["--base-dir", base]
        if args.phases:
            argv += ["--phases", args.phases]
        if args.overlay:
            argv += ["--overlay", *args.overlay]
        if args.run_id:
            argv += ["--run-id", args.run_id]
        if args.no_seed:
            argv += ["--no-seed"]
        if args.quiet:
            argv += ["--quiet"]
        return _json_file(argv, m) if args.json else _call(argv, m)
    if name == "tensile-build":
        from oto.checks.tensile_build import main as m
        argv = ["--base-dir", str(base)]
        for key, flag in (("family", "--family"), ("phase_id", "--phase-id"),
                          ("arch", "--arch"), ("keep", "--keep")):
            if getattr(args, key, None):
                argv += [flag, str(getattr(args, key))]
        if args.timeout != 600:
            argv += ["--timeout", str(args.timeout)]
        if args.jobs != 1:
            argv += ["--jobs", str(args.jobs)]
        if args.compare:
            argv += ["--compare"]
        return _json_file(argv, m) if args.json else _call(argv, m)
    return EXIT_FAIL


def run_library_best_effort(args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main

    argv = ["--base-dir", str(base_dir(args)), "--best-library"]
    if args.dest:
        argv += [args.dest]
    argv += ["--protocol-basis", args.protocol_basis]
    if args.dry_run:
        argv += ["--dry-run"]
    return _call(argv, cli_main)


def run_consolidate(args: Any) -> int:
    from oto.tools.consolidate import main as m

    argv = ["--base-dir", str(base_dir(args)), "all"]
    argv += ["--commit"] if args.commit else ["--dry-run"]
    if args.explain_archive:
        argv += ["--explain-archive"]
    return _call(argv, m)


def run_stats(args: Any) -> int:
    from oto.tools.all_runs import main as m

    argv = ["--base-dir", str(base_dir(args))]
    if args.family:
        argv += ["--family", args.family]
    return _json_file(argv, m) if args.json else _call(argv, m)


def run_chart(args: Any) -> int:
    from oto.tools.chart import main as chart_main

    argv = ["--base", str(base_dir(args))]
    if args.out:
        argv += ["--out", args.out]
    return _call(argv, chart_main)


def run_agent_generate(args: Any) -> int:
    from oto.runners.stage_cli import main as cli_main

    argv = ["--base-dir", str(base_dir(args)), "--generate-device-docs"]
    if args.starter:
        argv += [args.starter]
    if args.dry_run:
        argv += ["--dry-run"]
    return _call(argv, cli_main)


def run_agent_index(args: Any) -> int:
    from oto.docs_index import write_index

    result = write_index()
    path = result if isinstance(result, (str, Path)) else "docs/docs_index.json"
    print(f"regenerated {path}")
    return 0


# ------------------------------------------------------------------ meta

def run_completion(args: Any) -> int:
    print(write_completions(args.shell))
    return 0


def write_completions(shell: str) -> str:
    from oto.cli.parser import build_parser

    parser = build_parser()
    top = _command_names(parser)
    if shell == "bash":
        words = " ".join(sorted(top))
        cases = "\n".join(
            f'        {name}) opts="{_flags(parser, [name])}" ;;'
            for name in sorted(top))
        return (
            "_oto_completions() {\n"
            "    local cur prev cmd\n"
            "    cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
            "    cmd=\"${COMP_WORDS[1]}\"\n"
            "    case \"$cmd\" in\n"
            f"{cases}\n"
            "        *) opts=\"" + words + "\" ;;\n"
            "    esac\n"
            "    COMPREPLY=( $(compgen -W \"$opts\" -- \"$cur\") )\n"
            "}\n"
            "complete -F _oto_completions oto")
    descriptions = "\n".join(
        f"        '{name}:{_summary(parser, name)}'"
        for name in sorted(top))
    return (
        "#compdef oto\n"
        "_oto() {\n"
        "    local -a commands\n"
        "    commands=(\n"
        f"{descriptions}\n"
        "    )\n"
        "    _describe 'command' commands\n"
        "}\n"
        "compdef _oto oto")


def _subparsers(parser: Any) -> Any:
    import argparse
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _command_names(parser: Any) -> list[str]:
    return sorted(_subparsers(parser))


def _summary(parser: Any, name: str) -> str:
    p = _subparsers(parser)[name]
    return (p.description or "").splitlines()[0] or name


def _flags(parser: Any, path: list[str]) -> str:
    current = parser
    for token in path:
        current = _subparsers(current).get(token)
        if current is None:
            return ""
    out = []
    for action in current._actions:
        out.extend(o for o in action.option_strings if o.startswith("--"))
    return " ".join(sorted(set(out)))


def show_help(args: Any, parser: Any) -> int:
    """``oto help [topic]``: same text as ``--help``, paged on a TTY."""
    from oto.cli.parser import subparser_for

    if args.write:
        from oto.cli.docs import write_reference
        path = write_reference(parser, Path(args.write))
        print(f"wrote {path}")
        return 0
    if args.json:
        from oto.cli.docs import command_document
        print(json.dumps(command_document(parser), indent=2))
        return 0
    target = parser
    path = list(args.topic or [])
    try:
        target = subparser_for(parser, path)
    except KeyError:
        print(f"error: no help topic {' '.join(path)!r}", file=sys.stderr)
        print("hint: run 'oto help' for the command list.", file=sys.stderr)
        return 2
    text = target.format_help()
    if len(path) > 1 and path[0] == "verify" and path[1] == "run":
        text = target.format_help()
    _page(text)
    return 0


def _page(text: str) -> None:
    try:
        is_tty = sys.stdout.isatty()
    except Exception:
        is_tty = False
    if not is_tty:
        print(text)
        return
    import pydoc
    pydoc.pager(text)


def dispatch(args: Any, parser: Any) -> int:
    """Route one parsed invocation to its adapter."""
    path = getattr(args, "command", None)
    if not path:
        return _orientation(parser)
    if path == "verify":
        path = f"verify {getattr(args, 'verify_group', '')}"
    elif path == "check":
        path = f"check {getattr(args, 'check_cmd', '')}"
    elif path == "library":
        path = f"library {getattr(args, 'library_cmd', '')}"
    elif path == "agent":
        path = f"agent {getattr(args, 'agent_cmd', '')}"

    handlers: dict[str, Callable[[Any], int]] = {
        "tune": run_tune, "run": run_stages, "bench": run_bench,
        "status": run_status, "report": run_report, "doctor": run_doctor,
        "preflight": run_preflight, "candidate": lambda a: run_stage("candidate", a),
        "retirement": lambda a: run_stage("retirement", a),
        "analytics": lambda a: run_stage("analytics", a),
        "synthesis": lambda a: run_stage("synthesis", a),
        "verify all": run_verify_all, "verify run": run_verify_run,
        "check candidates": run_check, "check db": run_check,
        "check retirement": run_check, "check library-parity": run_check,
        "check tensile-build": run_check,
        "library best-effort": run_library_best_effort,
        "agent generate": run_agent_generate, "agent index": run_agent_index,
        "consolidate": run_consolidate, "stats": run_stats,
        "chart": run_chart, "version": lambda a: print_version(),
        "completion": run_completion, "help": lambda a: show_help(a, parser),
    }
    handler = handlers.get(path)
    if handler is None:
        print(f"error: unrecognised command {path!r}", file=sys.stderr)
        return 2
    return int(handler(args) or 0)


def print_version() -> int:
    from oto.version import __version__
    print(f"oto {__version__}")
    return 0


def _orientation(parser: Any) -> int:
    from oto.version import __version__
    print(f"oto {__version__} — deterministic Tensile tuning for unsupported AMD GPUs")
    print()
    print("Start here:")
    print("  oto doctor                 # is this box ready?")
    print("  oto status                 # what is the current run doing?")
    print("  oto tune --dry-run         # preview the overnight convergence loop")
    print()
    print("Main tasks:")
    print("  oto tune                   # run to convergence")
    print("  oto bench                  # gfx900 reference floor (--native for native-only)")
    print("  oto report                 # regenerate the acceptance report")
    print("  oto help                   # full command list")
    print()
    print("Run 'oto <command> --help' for flags and runnable examples.")
    return 0
