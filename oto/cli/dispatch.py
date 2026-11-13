"""Top-level dispatcher: routes subcommands to existing main() functions."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from oto._version import __version__
from oto.cli.flags import add_global_flags, add_version_flag

try:
    from rich.argparse import RichHelpFormatter
except ImportError:
    from argparse import RawDescriptionHelpFormatter as RichHelpFormatter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oto",
        description="oto — Tensile tuning for unsupported AMD GPUs",
        formatter_class=RichHelpFormatter,
    )
    add_version_flag(parser)
    sub = parser.add_subparsers(dest="command", help="Available commands")
    _add_core_subcommands(sub)
    _add_bench_subcommands(sub)
    _add_library_subcommands(sub)
    _add_agent_subcommands(sub)
    _add_utility_subcommands(sub)
    return parser


def _add_core_subcommands(sub: Any) -> None:
    p = sub.add_parser("tune", help="Run the convergence loop",
                       epilog="Examples:\n  oto tune --dry-run              # preview without executing\n  oto tune --budget 10 --yes      # accept default plan, no prompts\n  oto tune --resume               # continue from latest run\n  oto tune --include-illegal     # re-measure illegal reference cells")
    add_global_flags(p)
    p.add_argument("--budget", type=int, default=None, help="Auto-convergence iterations")
    p.add_argument("--mutations", type=int, default=None, help="Max mutations per candidate")
    p.add_argument("--resume", action="store_true", help="Resume from latest run")
    p.add_argument("--include-illegal", action="store_true", help="Re-measure illegal reference cells")
    p.add_argument("--include-underspecified", action="store_true", help="Re-measure under-specified cells")
    p.add_argument("--include-unreproducible", action="store_true", help="Re-attempt unreproducible cells")
    p.add_argument("--yes", action="store_true", help="Accept default plan without prompting")
    p.add_argument("--live", choices=["on", "off"], default="on", help="Live status repaint")
    p.set_defaults(func=_run_tune)

    p = sub.add_parser("status", help="Run status, ETA, and live panel",
                       epilog="Examples:\n  oto status                     # one-shot report\n  oto status --watch 30          # refresh every 30s\n  oto status --thermals --json   # machine-readable with thermals")
    add_global_flags(p)
    p.add_argument("--watch", type=float, metavar="SECONDS", help="Refresh every N seconds")
    p.add_argument("--thermals", action="store_true", help="Include thermal envelope")
    p.add_argument("--plan", nargs="*", default=[], help="Project a plan: KEY=VALUE ...")
    p.add_argument("--run", help="run_id to report on (default: newest)")
    p.set_defaults(func=_run_status)

    p = sub.add_parser("doctor", help="Diagnose environment (toolchain, GPU, registry)",
                       epilog="Examples:\n  oto doctor                     # full diagnostic\n  oto doctor --json              # machine-readable")
    add_global_flags(p)
    p.set_defaults(func=_run_doctor)

    p = sub.add_parser("report", help="Regenerate acceptance report")
    add_global_flags(p)
    p.add_argument("--run", help="run_id to report on (default: newest)")
    p.set_defaults(func=_run_report)

    p = sub.add_parser("consolidate", help="Deck consolidation")
    add_global_flags(p)
    p.set_defaults(func=_run_consolidate)

    p = sub.add_parser("stats", help="Cross-run best config per cell")
    add_global_flags(p)
    p.add_argument("--family", help="Filter by family")
    p.set_defaults(func=_run_stats)

    p = sub.add_parser("chart", help="Generate comparison figures")
    add_global_flags(p)
    p.set_defaults(func=_run_chart)

    p = sub.add_parser("version", help="Print version")
    p.set_defaults(func=_run_version)

    p = sub.add_parser("help", help="Show help for a topic")
    p.add_argument("topic", nargs="?", help="Command or topic name")
    p.set_defaults(func=_run_help)


def _add_bench_subcommands(sub: Any) -> None:
    p = sub.add_parser("bench", help="Benchmark phases",
                       epilog="Examples:\n  oto bench --dry-run            # list matched targets\n  oto bench --family SS --shape 1024x1024x1024\n  oto bench --native --limit 5   # native-only smoke test")
    add_global_flags(p)
    p.add_argument("--native", action="store_true", help="Native-only (no reference floor)")
    p.add_argument("--limit", type=int, help="Max phases to benchmark")
    p.add_argument("--ref-shapes", help="Comma-separated cube sides")
    p.add_argument("--resume", action="store_true", help="Resume incomplete reference run")
    p.add_argument("--refresh", action="store_true", help="Re-scan system dat")
    p.add_argument("--targets", nargs="+", help="Target IDs or labels")
    p.add_argument("--family", nargs="+", help="Filter by family")
    p.add_argument("--pattern", nargs="+", help="Filter by contraction pattern")
    p.add_argument("--shape", nargs="+", help="Filter by problem shape")
    p.set_defaults(func=_run_bench)

    p = sub.add_parser("verify", help="Verification commands")
    vsub = p.add_subparsers(dest="verify_cmd")
    vp = vsub.add_parser("all", help="Run all refactor verifiers")
    add_global_flags(vp)
    vp.set_defaults(func=_run_verify_all)
    vp2 = vsub.add_parser("run", help="Corpus snapshot/diff/telemetry")
    add_global_flags(vp2)
    vp2.add_argument("verify_run_cmd", nargs="?", choices=["snapshot", "diff", "telemetry", "cheapest"])
    vp2.add_argument("verify_run_args", nargs=argparse.REMAINDER)
    vp2.set_defaults(func=_run_verify_run)

    p = sub.add_parser("check", help="Diagnostic checks")
    csub = p.add_subparsers(dest="check_cmd")
    for name, help_text in [("candidates", "Deck linter"),
                            ("db", "Registry integrity"),
                            ("retirement", "Retirement assertion"),
                            ("library-parity", "Coverage parity vs shipped gfx900")]:
        cp = csub.add_parser(name, help=help_text)
        add_global_flags(cp)
        cp.set_defaults(func=_run_check, check_name=name)


def _add_library_subcommands(sub: Any) -> None:
    p = sub.add_parser("library", help="Tensile library operations",
                       epilog="Examples:\n  oto library best-effort        # carve best-effort .dat (CPU-only)\n  oto library verify             # coverage parity check\n  oto library build-proof        # build-proof assertion")
    lsub = p.add_subparsers(dest="library_cmd")
    lp = lsub.add_parser("best-effort", help="Carve best-effort .dat (CPU-only)")
    add_global_flags(lp)
    lp.add_argument("--dest", help="Destination directory")
    lp.add_argument("--protocol-basis", choices=["family", "any", "single", "partial"],
                    default="family", help="Protocol basis for carving")
    lp.set_defaults(func=_run_library_best_effort)
    lp2 = lsub.add_parser("verify", help="Coverage parity check")
    add_global_flags(lp2)
    lp2.set_defaults(func=_run_library_verify)
    lp3 = lsub.add_parser("build-proof", help="Build-proof check")
    add_global_flags(lp3)
    lp3.set_defaults(func=_run_library_build_proof)


def _add_agent_subcommands(sub: Any) -> None:
    p = sub.add_parser("agent", help="Agent operations (doc generation, harness study)",
                       epilog="Examples:\n  oto agent generate starter.md  # agent-1 + agent-2 docs\n  oto agent index                # regenerate docs index")
    asub = p.add_subparsers(dest="agent_cmd")
    ap = asub.add_parser("generate", help="Generate device docs (agent-1/agent-2)")
    add_global_flags(ap)
    ap.add_argument("starter", nargs="?", help="Starter file path")
    ap.set_defaults(func=_run_docs_generate)
    ap2 = asub.add_parser("index", help="Regenerate docs index")
    add_global_flags(ap2)
    ap2.set_defaults(func=_run_docs_index)


def _add_utility_subcommands(sub: Any) -> None:
    pass



def _with_argv(argv: list[str], func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run func with sys.argv temporarily set to argv."""
    import sys as _sys
    old = _sys.argv
    _sys.argv = ["oto", *argv]
    try:
        return func(*args, **kwargs)
    finally:
        _sys.argv = old

def _resolve_base(args: Any) -> Path:
    from pathlib import Path
    if getattr(args, "base_dir", None):
        return Path(args.base_dir)
    return Path.cwd()


# --- adapter functions (each ~5 lines, calls existing main) ---

def _run_tune(args: Any) -> int:
    from oto.runners.cli import main as cli_main
    argv = ["--base-dir", str(_resolve_base(args))]
    if args.budget is not None:
        argv += ["--budget", str(args.budget)]
    if args.mutations is not None:
        argv += ["--mutation-budget", str(args.mutations)]
    if args.resume:
        argv += ["--resume"]
    if args.include_illegal:
        argv += ["--release-under-specified"]
    if args.include_underspecified:
        argv += ["--release-under-specified"]
    if args.include_unreproducible:
        argv += ["--release-unreproducible"]
    if args.yes:
        argv += ["--yes"]
    if args.live == "off":
        argv += ["--live", "off"]
    argv += ["--auto"]
    return _with_argv(argv, cli_main)


def _run_status(args: Any) -> int:
    from oto.metrics.render_status import main as rs_main
    argv = ["--base", str(_resolve_base(args))]
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
    return rs_main(argv)


def _run_doctor(args: Any) -> int:
    from oto.runners.cli import main as cli_main
    return _with_argv(["--base-dir", str(_resolve_base(args)), "--preflight"], cli_main)


def _run_verify_all(args: Any) -> int:
    from oto.tools.verifiers.verify_all import main as va_main
    return va_main()


def _run_verify_run(args: Any) -> int:
    from oto.tools.verify_run import main as vr_main
    argv = ["--base-dir", str(_resolve_base(args))]
    if args.verify_run_cmd:
        argv += [args.verify_run_cmd]
    if args.verify_run_args:
        argv += args.verify_run_args
    return vr_main(argv)


def _run_check(args: Any) -> int:
    name = args.check_name
    base = str(_resolve_base(args))
    if name == "candidates":
        from oto.checks.candidates import main as m
        return _with_argv(["--base-dir", base], m)
    if name == "db":
        from oto.checks.db import main as m
        return _with_argv(["--base-dir", base], m)
    if name == "retirement":
        from oto.checks.retirement import main as m
        return _with_argv(["--base-dir", base], m)
    if name == "library-parity":
        from oto.checks.library_parity import main as m
        return _with_argv(["--base-dir", base], m)
    return 1


def _run_bench(args: Any) -> int:
    from oto.runners.cli import main as cli_main
    argv = ["--base-dir", str(_resolve_base(args))]
    if args.native:
        argv += ["--native"]
    if args.limit:
        argv += ["--limit", str(args.limit)]
    if args.ref_shapes:
        argv += ["--ref-shapes", args.ref_shapes]
    if args.resume:
        argv += ["--resume"]
    if args.refresh:
        argv += ["--refresh"]
    if args.targets:
        argv += ["--targets", *args.targets]
    if args.family:
        argv += ["--family", *args.family]
    if args.pattern:
        argv += ["--pattern", *args.pattern]
    if args.shape:
        argv += ["--shape", *args.shape]
    if args.dry_run:
        argv += ["--dry-run"]
    return _with_argv(argv, cli_main)


def _run_report(args: Any) -> int:
    from oto.runners.cli import main as cli_main
    argv = ["--base-dir", str(_resolve_base(args)), "--report"]
    if args.run:
        argv += [args.run]
    return _with_argv(argv, cli_main)


def _run_library_best_effort(args: Any) -> int:
    from oto.runners.cli import main as cli_main
    argv = ["--base-dir", str(_resolve_base(args)), "--best-library"]
    if args.dest:
        argv += [args.dest]
    argv += ["--protocol-basis", args.protocol_basis]
    return _with_argv(argv, cli_main)


def _run_library_verify(args: Any) -> int:
    from oto.checks.library_parity import main as m
    return _with_argv(["--base-dir", str(_resolve_base(args))], m)


def _run_library_build_proof(args: Any) -> int:
    from oto.checks.tensile_build import main as m
    return _with_argv(["--base-dir", str(_resolve_base(args))], m)


def _run_consolidate(args: Any) -> int:
    from oto.tools.consolidate import main as m
    return _with_argv(["--base-dir", str(_resolve_base(args))], m)


def _run_stats(args: Any) -> int:
    from oto.tools.allruns import main as m
    argv = ["--base-dir", str(_resolve_base(args))]
    if args.family:
        argv += ["--family", args.family]
    if args.json:
        argv += ["--json"]
    return _with_argv(argv, m)


def _run_chart(args: Any) -> int:
    # chart.py runs at module level; exec it
    import runpy
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "oto" / "tools" / "chart.py"), run_name="__main__")
    return 0


def _run_docs_generate(args: Any) -> int:
    from oto.runners.cli import main as cli_main
    argv = ["--base-dir", str(_resolve_base(args)), "--generate-device-docs"]
    if args.starter:
        argv += [args.starter]
    return _with_argv(argv, cli_main)


def _run_docs_index(args: Any) -> int:
    from oto.docs_index import write_index
    write_index()
    print("docs/docs_index.json regenerated")
    return 0


def _run_version(args: Any) -> int:
    print(f"oto {__version__}")
    return 0


def _run_help(args: Any) -> int:
    if args.topic:
        print(f"See: oto {args.topic} --help")
    else:
        print("oto — Tensile tuning for unsupported AMD GPUs")
        print()
        print("Commands:")
        print("  tune      Run the convergence loop")
        print("  bench     Benchmark phases")
        print("  status    Run status, ETA, and live panel")
        print("  report    Regenerate acceptance report")
        print("  doctor    Diagnose environment")
        print("  verify    Verification commands")
        print("  check     Diagnostic checks")
        print("  library   Tensile library operations")
        print("  consolidate  Deck consolidation")
        print("  stats     Cross-run best config per cell")
        print("  chart     Generate comparison figures")
        print("  agent     Agent operations (doc generation, harness study)")
        print("  version   Print version")
        print("  help      Show help for a topic")
        print()
        print("Run 'oto <command> --help' for details.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # Bare invocation: show orientation
        print("oto — Tensile tuning for unsupported AMD GPUs")
        print()
        print("Quick start:")
        print("  oto doctor          # diagnose environment")
        print("  oto status          # run status and ETA")
        print("  oto tune            # run convergence loop")
        print("  oto tune --dry-run  # preview without executing")
        print()
        print("Run 'oto help' for full command list.")
        print("Run 'oto <command> --help' for command details.")
        return 0
    try:
        return args.func(args)
    except Exception as exc:
        from oto.cli.errors import handle_error
        return handle_error(exc, quiet=getattr(args, "quiet", False))
