"""The ``oto`` command tree.

Owns: the parser, the noun/verb groups, the examples-first descriptions, and
the metadata the dispatcher uses (``mutating``, ``read``, ``examples``).
Does NOT own: any command's implementation (```oto.cli.commands``` adapts the
existing backends) or the global output/error policy (```oto.cli.dispatch```).
Public API: build_parser, subparser_for.
"""

from __future__ import annotations

import argparse
from typing import Any

from oto.cli.global_flags import (
    add_dry_run_flag,
    add_global_flags,
    add_json_flag,
    add_version_flag,
)

try:  # rich-argparse is the maintained rich integration for argparse.
    from rich_argparse import RichHelpFormatter as _HelpFormatter
except ImportError:  # pragma: no cover - exercised only on a minimal install
    _HelpFormatter = argparse.RawDescriptionHelpFormatter


def _fmt(*, examples: str = "") -> type[argparse.HelpFormatter]:
    """Use rich help when installed; the examples stay in ``description``.

    Examples live in the description (not the epilog) so they render before
    the options, which is the clig.dev help order: what this command is for,
    one runnable example, then the flag reference.
    """
    if not examples:
        return _HelpFormatter

    class _Examples(_HelpFormatter):  # type: ignore[misc, valid-type]
        pass

    return _Examples


def _add(sub: Any, name: str, summary: str, examples: str = "",
         *, mutating: bool = False, read: bool = False) -> argparse.ArgumentParser:
    """Register one subcommand; returns its parser."""
    description = summary
    if examples:
        description = f"{summary}\n\nExamples:\n{examples}"
    p = sub.add_parser(name, help=summary, description=description,
                       formatter_class=_fmt(examples=examples))
    add_global_flags(p)
    p.set_defaults(command_path=name, mutating=mutating, read=read,
                   examples=examples, summary=summary)
    return p


def _add_scope(p: argparse.ArgumentParser) -> None:
    """Add the target/family/pattern/shape scope flags."""
    p.add_argument("--targets", nargs="+", help="Target IDs or labels")
    p.add_argument("--family", nargs="+", help="Family labels (e.g. SS or CC DD)")
    p.add_argument("--pattern", nargs="+", help="Contraction patterns")
    p.add_argument("--shape", nargs="+", help="Problem shapes")


def _add_run_flags(p: argparse.ArgumentParser) -> None:
    """Add the per-run flags (--force, --live, --tensile-root, dry-run)."""
    add_dry_run_flag(p)
    p.add_argument("--force", action="store_true",
                   help="Run even when an identical fingerprint already passed")
    p.add_argument("--live", choices=("on", "off"), default="on",
                   help="Live TTY status panel (default: on)")
    p.add_argument("--live-interval", type=float, default=30.0, metavar="SECONDS",
                   help="Seconds between live status repaints (default: 30)")
    p.add_argument("--tensile-root", help="Override TENSILE_ROOT for this command")


def build_parser() -> argparse.ArgumentParser:
    """Build the whole ``oto`` command tree."""
    parser = argparse.ArgumentParser(
        prog="oto",
        description="oto — deterministic Tensile tuning for unsupported AMD GPUs",
        formatter_class=_HelpFormatter,
    )
    add_version_flag(parser)
    sub = parser.add_subparsers(dest="command", help="Available commands")
    _add_core(sub)
    _add_stages(sub)
    _add_verify(sub)
    _add_checks(sub)
    _add_library(sub)
    _add_agent(sub)
    _add_setup(sub)
    _add_utility(sub)
    return parser


def _add_core(sub: Any) -> None:
    """Add the core command groups (tune/run/bench/status/report/doctor)."""
    _add_tune(sub)
    _add_run(sub)
    _add_bench(sub)
    _add_status_report(sub)


def _add_tune(sub: Any) -> None:
    """Add the ``tune`` command group."""
    p = _add(sub, "tune", "Run the convergence loop (the overnight job)",
             "  oto tune --dry-run                  # list the plan, no GPU work\n"
             "  oto tune --budget 10 --yes          # accept defaults, no prompts\n"
             "  oto tune --include-illegal --resume # re-measure the illegal tier",
             mutating=True)
    p.add_argument("--budget", type=int, help="Convergence iterations")
    p.add_argument("--mutations", type=int, help="Max mutations per candidate")
    p.add_argument("--resume", action="store_true",
                   help="Resume the reference floor where it stopped")
    p.add_argument("--include-illegal", action="store_true",
                   help="(no-op; the reference floor always re-measures the illegal tier)")
    p.add_argument("--include-underspecified", action="store_true",
                   help="Re-measure the UNDER-SPECIFIED reference cells")
    p.add_argument("--include-unreproducible", action="store_true",
                   help="Re-attempt the UNREPRODUCIBLE reference cells")
    p.add_argument("-y", "--yes", action="store_true",
                   help="Accept the default plan without prompting")
    p.add_argument("--live", choices=("on", "off"), default="on",
                   help="Live TTY status panel (default: on)")
    p.add_argument("--live-interval", type=float, default=30.0, metavar="SECONDS")
    p.add_argument("--tensile-root", help="Override TENSILE_ROOT for this run")
    add_dry_run_flag(p)


def _add_run(sub: Any) -> None:
    """Add the ``run`` command group."""
    p = _add(sub, "run", "Execute an explicit multi-stage selection",
             "  oto run --stage preflight candidate   # two stages, one process\n"
             "  oto run --stage benchmark --family SS --dry-run",
             mutating=True)
    p.add_argument("--stage", nargs="+", default=[],
                   help="preflight, candidate, benchmark, retirement, analytics, synthesis, report")
    _add_scope(p)
    _add_run_flags(p)


def _add_bench(sub: Any) -> None:
    """Add the ``bench`` command group."""
    p = _add(sub, "bench", "Benchmark the reference floor, native loop, or a scope",
             "  oto bench --dry-run                  # list matched manifest targets\n"
             "  oto bench --native --limit 5         # native-only smoke test\n"
             "  oto bench --family SS --shape 1024x1024x1024",
             mutating=True)
    p.add_argument("--native", action="store_true",
                   help="Native-only loop (no gfx900 reference floor)")
    p.add_argument("--limit", type=int, help="Max reference phases (one per family)")
    p.add_argument("--ref-shapes", help="Comma-separated cube sides, e.g. 256,512")
    p.add_argument("--resume", action="store_true", help="Resume the reference floor")
    p.add_argument("--refresh", action="store_true", help="Re-scan the system dat")
    _add_scope(p)
    _add_run_flags(p)


def _add_status_report(sub: Any) -> None:
    """Add the ``status`` and ``report`` command groups."""
    p = _add(sub, "status", "Show run status, ETA, and the live panel",
             "  oto status                      # one-shot report\n"
             "  oto status --watch 30           # refresh every 30 seconds\n"
             "  oto status --thermals --json    # machine-readable with thermals",
             read=True)
    p.add_argument("--watch", type=float, metavar="SECONDS",
                   help="Refresh every N seconds")
    p.add_argument("--thermals", action="store_true", help="Include thermals")
    p.add_argument("--plan", nargs="*", default=[], metavar="KEY=VALUE",
                   help="Project a plan (rerun_illegal=no, iterations=4, ...)")
    p.add_argument("--run", help="run_id to report on (default: newest)")
    add_json_flag(p)

    p = _add(sub, "report", "Regenerate the acceptance report",
             "  oto report                       # newest native run\n"
             "  oto report --run <id> --json     # machine-readable payload",
             read=True)
    p.add_argument("--run", help="run_id to report on (default: newest)")
    add_json_flag(p)

    p = _add(sub, "doctor", "Diagnose the toolchain, GPU, registry, and docs",
             "  oto doctor                       # human checklist with hints\n"
             "  oto doctor --json                # machine-readable verdict",
             read=True)
    add_json_flag(p)


def _add_stages(sub: Any) -> None:
    """Add the stage commands (candidate/retirement/analytics/...)."""
    p = _add(sub, "preflight", "the preflight stage: validate the run environment",
             "  oto preflight\n  oto preflight --json",
             read=True)
    p.add_argument("--tensile-root")
    add_json_flag(p)

    p = _add(sub, "candidate", "the candidate stage: print the candidate plan by family",
             "  oto candidate\n  oto candidate --json",
             read=True)
    p.add_argument("--tensile-root")
    add_json_flag(p)

    p = _add(sub, "retirement", "the retirement stage: retire stable cells (registry-only)",
             "  oto retirement --dry-run\n  oto retirement",
             mutating=True)
    p.add_argument("--tensile-root")
    add_dry_run_flag(p)

    p = _add(sub, "analytics", "the analytics stage: analytics summary for a run",
             "  oto analytics\n  oto analytics --stage 5",
             read=True)
    p.add_argument("--tensile-root")
    add_json_flag(p)

    p = _add(sub, "synthesis", "the synthesis/build stage: build and validate the native library",
             "  oto synthesis --dry-run\n  oto synthesis",
             mutating=True)
    p.add_argument("--tensile-root")
    add_dry_run_flag(p)


def _add_verify(sub: Any) -> None:
    """Add the ``verify`` command group."""
    p = sub.add_parser("verify", help="Verification commands",
                       description="Verification commands\n\n"
                                   "Examples:\n  oto verify all\n"
                                   "  oto verify run snapshot --out before.json")
    vsub = p.add_subparsers(dest="verify_group", help="Verification group")

    a = _add(vsub, "all", "Run all equivalence verifiers",
             "  oto verify all\n  oto verify all --base-ref 2824c2f\n  oto verify all --json", read=True)
    a.add_argument("--base-ref", default=None,
                   help="Ref to compare against (default: HEAD~1, the evergreen "
                        "per-commit base; pass a specific ref for the legacy "
                        "comparison)")
    add_json_flag(a)

    r = _add(vsub, "run", "Corpus snapshot/diff/telemetry",
             "  oto verify run snapshot --out before.json\n"
             "  oto verify run diff before.json after.json\n"
             "  oto verify run telemetry <run_id>",
             mutating=False, read=True)
    add_json_flag(r)
    rsub = r.add_subparsers(dest="verify_cmd", help="Corpus operation")

    s = _add(rsub, "snapshot", "Record corpus state as JSON",
             "  oto verify run snapshot --out before.json", read=True)
    s.add_argument("--out", help="Write JSON here instead of stdout")
    add_json_flag(s)

    d = _add(rsub, "diff", "Compare two snapshots; non-zero on data loss",
             "  oto verify run diff before.json after.json", read=True)
    d.add_argument("before")
    d.add_argument("after")
    add_json_flag(d)

    t = _add(rsub, "telemetry", "Per-phase telemetry funnel for one run",
             "  oto verify run telemetry <run_id>", read=True)
    t.add_argument("run_id")
    add_json_flag(t)

    c = _add(rsub, "cheapest", "Cheapest legal phases for a smoke run",
             "  oto verify run cheapest --family ZZ --n 3", read=True)
    c.add_argument("--family", help="Dtype char filter, e.g. ZZ")
    c.add_argument("--n", type=int, default=5, help="Number of phases")
    add_json_flag(c)


def _add_checks(sub: Any) -> None:
    """Add the ``check`` command group."""
    p = sub.add_parser("check", help="Diagnostic assertions",
                       description="Diagnostic assertions (read-only)\n\n"
                                   "Examples:\n  oto check candidates --quiet\n"
                                   "  oto check db --json")
    csub = p.add_subparsers(dest="check_cmd", help="Check name")

    c = _add(csub, "candidates", "Deck linter: four-gate legality",
             "  oto check candidates --quiet\n"
             "  oto check candidates --deck phases.yaml --json", read=True)
    c.add_argument("--deck", help="Deck or overlay YAML (default: phases.yaml)")
    c.add_argument("--family", help="Only this family label")
    c.add_argument("--floor", action="store_true",
                   help="Sweep the shipped gfx900 floor manifest")
    add_json_flag(c)

    d = _add(csub, "db", "Registry integrity and label contamination",
             "  oto check db\n  oto check db --json", read=True)
    add_json_flag(d)

    r = _add(csub, "retirement", "Retirement records and per-cell samples",
             "  oto check retirement\n  oto check retirement --json", read=True)
    add_json_flag(r)

    lp = _add(csub, "library-parity", "Coverage parity vs the shipped gfx900 grid",
              "  oto check library-parity --quiet\n"
              "  oto check library-parity --json", read=True)
    lp.add_argument("--phases", help="Explicit deck file; implies no overlays")
    lp.add_argument("--overlay", nargs="+", help="Extra overlay YAML(s)")
    lp.add_argument("--run-id", help="Fold in this run's overlay")
    lp.add_argument("--no-seed", action="store_true", help="Skip the seed overlay")
    add_json_flag(lp)

    tb = _add(csub, "tensile-build", "CPU-only Tensile build proof",
              "  oto check tensile-build --family ZZ --jobs 8\n"
              "  oto check tensile-build --json", read=True)
    tb.add_argument("--family", help="Only this FamilyLabel")
    tb.add_argument("--phase-id", help="Only this phase id")
    tb.add_argument("--arch", help="Tensile arch (default: profile codename)")
    tb.add_argument("--timeout", type=int, default=600, help="Seconds per phase")
    tb.add_argument("--jobs", type=int, default=1, help="Parallel phases")
    tb.add_argument("--compare", action="store_true",
                    help="Cross-check oto's occupancy model against Tensile")
    tb.add_argument("--keep", help="Keep build artifacts here")
    add_json_flag(tb)


def _add_library(sub: Any) -> None:
    """Add the ``library`` command group."""
    p = sub.add_parser("library", help="Tensile library operations",
                       description="Tensile library operations\n\n"
                                   "Examples:\n  oto library best-effort\n"
                                   "  oto library best-effort --protocol-basis any")
    lsub = p.add_subparsers(dest="library_cmd", help="Library operation")
    b = _add(lsub, "best-effort", "Carve the best-effort .dat (CPU-only)",
             "  oto library best-effort --dry-run\n"
             "  oto library best-effort --dest out/ --protocol-basis any",
             mutating=True)
    b.add_argument("--dest", help="Destination directory")
    b.add_argument("--protocol-basis", choices=("family", "any", "single", "partial"),
                   default=None,
                   help="Protocol basis for carving (default: 'any', the across-all-runs view)")
    add_dry_run_flag(b)


def _add_agent(sub: Any) -> None:
    """Add the ``agent`` command group."""
    p = sub.add_parser("agent", help="Operator-agent operations",
                       description="Operator-agent operations\n\n"
                                   "Examples:\n  oto agent generate docs/starter.md\n"
                                   "  oto agent index")
    asub = p.add_subparsers(dest="agent_cmd", help="Agent operation")
    g = _add(asub, "generate", "Generate device docs (agent-1 + agent-2)",
             "  oto agent generate docs/operator/gfx902_starter.md --dry-run\n"
             "  oto agent generate docs/operator/gfx902_starter.md",
             mutating=True)
    g.add_argument("starter", nargs="?", help="Starter Markdown file")
    add_dry_run_flag(g)
    _add(asub, "index", "Regenerate docs/docs_index.json",
         "  oto agent index", mutating=True)
    c = _add(asub, "consult", "Draft <codename>_potential_configs.md (CPU-only census consult)",
             "  oto agent consult docs/operator/gfx902_starter.md\n"
             "  oto agent consult --out my_device.md",
             mutating=True)
    c.add_argument("starter", nargs="?", help="Starter Markdown file (default: ambient profile)")
    c.add_argument("--out", help="Output path (default: <codename>_potential_configs.md in base dir)")
    c.add_argument("--force", action="store_true",
                   help="Overwrite an existing output file")
    c.add_argument("--with-docs", action="store_true",
                   help="Also generate the agent-1/agent-2 device docs beside the consult output")


def _add_setup(sub: Any) -> None:
    """Add the ``setup`` command group."""
    p = _add(sub, "setup", "Easy-mode onboarding: prepare oto for a new device",
             "  oto setup\n"
             "  oto setup --yes --convergence-mode blind\n"
             "  oto setup --dry-run",
             mutating=True)
    p.add_argument("--yes", "-y", action="store_true",
                   help="Non-interactive: take defaults, never prompt")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan and the .env it would write; no writes")
    p.add_argument("--force", action="store_true",
                   help="Overwrite an existing .env")
    p.add_argument("--convergence-mode", choices=("blind", "informed"),
                   help="Convergence mode (default: blind)")
    p.add_argument("--spoof", help="Spoof (reference floor) GPU codename (informed mode)")
    p.add_argument("--rocm-prefix", help="ROCM install prefix (auto-detected if omitted)")
    p.add_argument("--tensile-root", help="Tensile checkout root (auto-detected if omitted)")
    p.add_argument("--gpu-targets", help="GPU targets for the client build (comma list)")
    p.add_argument("--jobs", type=int, default=4, help="Parallel build jobs")
    p.add_argument("--skip-build", action="store_true",
                   help="Do not build the Tensile client")
    p.add_argument("--build-client", action="store_true", default=True,
                   help="Build the Tensile client if missing (default: on)")
    p.add_argument("--write-env", action="store_true",
                   help="Write the .env file (default: ask)")
    p.add_argument("--codename", default="gfx90c",
                   help="Target codename written into .env hints (default: gfx90c)")


def _add_utility(sub: Any) -> None:
    """Add the utility commands (consolidate/stats/chart/...)."""
    p = _add(sub, "consolidate", "Consolidate the floor into a locked deck",
             "  oto consolidate --dry-run        # stage only (default)\n"
             "  oto consolidate --commit         # install after parity passes",
             mutating=True)
    p.add_argument("--commit", action="store_true",
                   help="Install the consolidated deck (default: stage only)")
    p.add_argument("--explain-archive", action="store_true",
                   help="Explain which runs the archive keeps")
    add_dry_run_flag(p)

    p = _add(sub, "stats", "Cross-run best config per cell",
             "  oto stats\n  oto stats --family ZZ --json", read=True)
    p.add_argument("--family", help="Filter to one family label")
    add_json_flag(p)

    p = _add(sub, "chart", "Generate the native-vs-floor comparison figure",
             "  oto chart\n  oto chart --out my_chart.png",
             mutating=True)
    p.add_argument("--out", help="Output PNG path")

    p = _add(sub, "version", "Print the version", "  oto version")
    p = _add(sub, "help", "Show help for a topic",
             "  oto help\n  oto help tune\n  oto help --json")
    p.add_argument("topic", nargs="*", help="Command path, e.g. verify run")
    add_json_flag(p)
    p.add_argument("--write", nargs="?", const="docs/cli.md", metavar="PATH",
                   help="Regenerate the Markdown command reference")

    p = _add(sub, "completion", "Generate shell completions",
             "  oto completion bash\n  oto completion zsh > _oto")
    p.add_argument("shell", choices=("bash", "zsh"), help="Shell type")


def subparser_for(parser: argparse.ArgumentParser, path: list[str]) -> argparse.ArgumentParser:
    """Resolve ``["verify", "run", "snapshot"]`` to its parser.

    The help command uses this so ``oto help verify run`` pages the same text
    as ``oto verify run --help`` instead of printing a pointer.
    """
    current = parser
    for token in path:
        subs = [a for a in current._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            raise KeyError(token)
        choices = subs[0].choices
        if token not in choices:
            raise KeyError(token)
        current = choices[token]
    return current
