#!/usr/bin/env python3
"""Regenerate oto/README.md from the module docstrings themselves.

Owns: ``main`` -- it reads every module's docstring and writes oto/README.md,
so the inventory cannot drift from the docstrings it describes.
Does NOT own: the module docstrings it reads (each module owns its own) or the
package layout it walks (the ``oto/`` tree itself).
Public API: main.

A hand-maintained inventory is a stale inventory. This reads each module's
docstring and writes the file that describes it.

Run from the repo root:

    python3 -m oto.readme_gen
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The prose each package owns, in reading order.
PACKAGES = [
    ("device", "oto/device/ — hardware facts"),
    ("tensile", "oto/tensile/ — the Tensile-facing candidate pipeline"),
    ("ledger", "oto/ledger/ — durable state + the mutation/convergence state machine"),
    ("metrics", "oto/metrics/ — turning benchmark rows into verdicts, reports and status"),
    ("runners", "oto/runners/ — execution"),
    ("checks", "oto/checks/ — operator diagnostics"),
    ("tools", "oto/tools/ — offline corpus analysis"),
    ("harness", "oto/harness/ — the analysis harness"),
]

#: Modules that are plumbing rather than responsibility.
SKIP = {"__init__.py", "_map.py"}


def _first_sentence(text: str) -> str:
    """The first sentence of a docstring's first paragraph."""
    paragraph = text.strip().split("\n\n")[0]
    return " ".join(paragraph.split())


def _has_modules(directory: Path) -> bool:
    """True when a directory holds at least one real module (not plumbing).

    Stray data directories (a ``<codename>_results/`` or ``<codename>_runs/`` created by
    running a tool with a relative base path) must not get a heading with no
    entries under it.
    """
    return any(p.name not in SKIP for p in directory.rglob("*.py"))


def _summary(path: Path) -> str:
    """A module's one-line summary, from its docstring or leading comment."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree)
    if doc:
        return _first_sentence(doc)
    # No docstring: fall back to the leading comment block.
    for line in path.read_text().splitlines():
        if line.strip().startswith("#"):
            return _first_sentence(line.lstrip("# "))
        if line.strip():
            break
    return ""


def _entry(path: Path) -> str:
    """One bullet line, marking a missing docstring loudly."""
    summary = _summary(path) or "**(no docstring yet)**"
    return f"* ``{path.relative_to(HERE)}`` — {summary}\n"


def _emit_tree(out: list[str], directory: Path, level: int) -> None:
    """Emit ``directory``'s modules, then recurse into every real sub-package.

    ``level`` is the ATX heading level (number of ``#``) for a *child*
    directory; the heading for ``directory`` itself is written by the caller.
    A "real" sub-package is one ``_has_modules`` accepts, so stray data
    directories get no empty heading.
    """
    out.extend(_entry(path)
               for path in sorted(directory.glob("*.py"))
               if path.name not in SKIP)
    for nested in sorted(p for p in directory.iterdir()
                         if p.is_dir() and not p.name.startswith("__")
                         and _has_modules(p)):
        out.append(f"\n{'#' * level} ``{nested.relative_to(HERE)}/``\n\n")
        _emit_tree(out, nested, level + 1)


def render() -> str:
    """The README content generated from the live docstrings, without writing."""
    out = ["# The ``oto/`` package map\n",
           "\n",
           "Generated. Regenerate with ``python3 -m oto.readme_gen``.\n",
           "\n",
           "Each entry is the first sentence of that module's docstring, so the\n",
           "only way to make this file stale is to delete the docstring. Line\n",
           "counts are never quoted here -- they go wrong the day a file moves.\n",
           "\n"]
    root_modules = [path for path in sorted(HERE.glob("*.py"))
                     if path.name not in SKIP]
    if root_modules:
        out.append("## oto/ -- the package root\n\n")
        out.extend(_entry(path) for path in root_modules)
        out.append("\n")
    for sub, title in PACKAGES:
        base = HERE / sub
        if not base.is_dir():
            continue
        out.append(f"## {title}\n\n")
        _emit_tree(out, base, level=3)
        out.append("\n")
    return "".join(out)


def main() -> int:
    HERE.joinpath("README.md").write_text(render())
    print(f"wrote {HERE / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
