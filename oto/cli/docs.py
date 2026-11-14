"""Machine-readable and Markdown views of the command tree.

Owns: the JSON document behind ``oto help --json`` and the Markdown reference
behind ``oto help --write``. Keeping both derived from the live parser is what
stops ``docs/cli.md`` from advertising a command that no longer exists.
Does NOT own: the parser itself (``oto.cli.parser``) or help paging.
Public API: command_document, write_reference.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from oto._version import __version__

MIGRATION = (
    ("python3 port_tensile.py --auto", "oto tune"),
    ("python3 port_tensile.py --auto --budget 10 --yes", "oto tune --budget 10 --yes"),
    ("python3 port_tensile.py --preflight", "oto preflight  (or oto doctor)"),
    ("python3 port_tensile.py --report", "oto report"),
    ("python3 port_tensile.py --best-library", "oto library best-effort"),
    ("python3 port_tensile.py --generate-device-docs", "oto agent generate"),
    ("python3 port_tensile.py --gfx900-reference", "oto bench"),
    ("python3 port_tensile.py --native", "oto bench --native"),
    ("python3 all_runs.py", "oto stats"),
    ("python3 check_candidates.py", "oto check candidates"),
    ("python3 check_db.py", "oto check db"),
    ("python3 check_retirement.py", "oto check retirement"),
    ("python3 check_library_parity.py", "oto check library-parity"),
    ("python3 check_tensile_build.py", "oto check tensile-build"),
    ("python3 consolidate.py", "oto consolidate"),
    ("python3 chart.py", "oto chart"),
    ("python3 verify_all.py", "oto verify all"),
    ("python3 corpus_audit.py snapshot", "oto verify run snapshot"),
    ("python3 -m oto.metrics.render_status", "oto status"),
)


def _subparsers(parser: Any) -> dict[str, Any]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _flags(parser: Any) -> list[dict[str, Any]]:
    out = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        names = [o for o in action.option_strings if o != "-h"]
        if not names:
            continue
        out.append({
            "flags": names,
            "dest": action.dest,
            "help": action.help or "",
            "default": action.default if action.default not in (None, False) else None,
            "choices": list(action.choices) if action.choices else None,
        })
    return out


def _node(parser: Any, name: str, path: str) -> dict[str, Any]:
    summary = ((parser.description or "").splitlines() or [name])[0]
    examples = [line.strip() for line in (parser.description or "").splitlines()
                if line.strip().startswith("oto ")]
    return {
        "name": name,
        "path": path,
        "summary": summary,
        "examples": examples,
        "flags": _flags(parser),
        "commands": [_node(child, child_name, f"{path} {child_name}".strip())
                     for child_name, child in sorted(_subparsers(parser).items())],
    }


def command_document(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """The complete command tree as one JSON-serialisable document."""
    return {
        "name": "oto",
        "version": __version__,
        "description": parser.description,
        "flags": _flags(parser),
        "commands": [_node(child, name, name)
                     for name, child in sorted(_subparsers(parser).items())],
    }


def _flag_line(flag: dict[str, Any]) -> str:
    names = ", ".join(f"`{n}`" for n in flag["flags"])
    extra = ""
    if flag.get("choices"):
        extra = " {" + ",".join(flag["choices"]) + "}"
    default = flag.get("default")
    if default not in (None, False, ""):
        extra += f" (default: `{default}`)"
    return f"- {names}{extra} — {flag['help']}"


def _render_node(node: dict[str, Any], level: int = 3) -> list[str]:
    heading = "#" * level
    out = [f"{heading} `oto {node['path']}`", "", node["summary"], ""]
    if node["examples"]:
        out += ["```bash", *node["examples"], "```", ""]
    flags = [f for f in node["flags"] if f["dest"] != "help"
             and "--version" not in f["flags"]]
    if flags:
        out += ["Flags:", "", *[_flag_line(f) for f in flags], ""]
    for child in node["commands"]:
        out += _render_node(child, level + 1)
    return out


def write_reference(parser: argparse.ArgumentParser, path: Path) -> Path:
    """Write the Markdown command reference derived from ``parser``."""
    doc = command_document(parser)
    lines = [
        "# oto CLI command reference",
        "",
        f"Generated from `oto help --json` for oto {doc['version']}. Do not hand-edit;",
        "run `oto help --write docs/cli.md` after changing the command tree.",
        "",
        "`oto` is the single front door. It is verb-first and noun-scoped: at most",
        "two levels, stdout carries data, stderr carries narration, and read",
        "commands have `--json`.",
        "",
        "## Quick start",
        "",
        "```bash",
        "oto doctor                     # is this box ready?",
        "oto status                     # what is the current run doing?",
        "oto tune --dry-run             # preview the overnight loop",
        "oto tune --budget 10 --yes     # run it non-interactively",
        "```",
        "",
        "The repository-local entry point is `bin/oto`; add `bin/` to `PATH` to",
        "type `oto`. `python3 -m oto` is the same dispatcher.",
        "",
        "## Global conventions",
        "",
        "- `--base PATH` — project directory (default: current directory).",
        "- `-q/--quiet` — suppress narration; errors still go to stderr.",
        "- `-v/--verbose` — show the command line and full tracebacks.",
        "- `--no-input` — never prompt; take documented defaults or fail.",
        "- `--no-color` / `NO_COLOR` — disable ANSI colour.",
        "- `--json` — read commands only: one JSON document on stdout.",
        "- `-n/--dry-run` — state-changing commands: print the plan, change nothing.",
        "- Exit codes: `0` ok, `1` failure, `2` usage error, `130` interrupted.",
        "",
        "## Commands",
        "",
    ]
    for child in doc["commands"]:
        lines += _render_node(child)
    lines += [
        "## Migration from the old scripts",
        "",
        "There are no compatibility shims and no aliases. This is the clean break.",
        "",
        "| Old command | New command |",
        "|---|---|",
        *[f"| `{old}` | `{new}` |" for old, new in MIGRATION],
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path
