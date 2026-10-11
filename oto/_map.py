#!/usr/bin/env python3
"""Regenerate oto/README.md from the module docstrings themselves.

A hand-maintained inventory is a stale inventory. This reads each module's
docstring and writes the file that describes it.

Run from the repo root:

    python3 oto/_map.py
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


def main() -> int:
    out = ["# The ``oto/`` package map\n",
           "\n",
           "Generated. Regenerate with ``python3 oto/_map.py``.\n",
           "\n",
           "Each entry is the first sentence of that module's docstring, so the\n",
           "only way to make this file stale is to delete the docstring. Line\n",
           "counts are never quoted here -- they go wrong the day a file moves.\n",
           "\n"]
    for sub, title in PACKAGES:
        if sub:
            base = HERE / sub
            if not base.is_dir():
                continue
            out.append(f"## {title}\n\n")
            for path in sorted(base.glob("*.py")):
                if path.name not in SKIP:
                    out.append(_entry(path))
            for nested in sorted(p for p in base.iterdir() if p.is_dir()
                                 and not p.name.startswith("__")):
                out.append(f"\n### ``{nested.relative_to(HERE)}/``\n\n")
                for path in sorted(nested.glob("*.py")):
                    if path.name not in SKIP:
                        out.append(_entry(path))
                for deeper in sorted(p for p in nested.iterdir() if p.is_dir()
                                     and not p.name.startswith("__")):
                    out.append(f"\n#### ``{deeper.relative_to(HERE)}/``\n\n")
                    for path in sorted(deeper.glob("*.py")):
                        if path.name not in SKIP:
                            out.append(_entry(path))
            out.append("\n")
            continue

        # The package root: oto/*.py, then every sub-package at top level under
        # its own heading, in the order PACKAGES gives.
        out.append(f"## {title}\n\n")
        for path in sorted(HERE.glob("*.py")):
            if path.name not in SKIP:
                out.append(_entry(path))
        out.append("\n")
        for sub_pkg, pkg_title in PACKAGES:
            if not sub_pkg:
                continue
            pkg = HERE / sub_pkg
            if not pkg.is_dir():
                continue
            out.append(f"### {pkg_title}\n\n")
            for path in sorted(pkg.glob("*.py")):
                if path.name not in SKIP:
                    out.append(_entry(path))
            for nested in sorted(p for p in pkg.iterdir() if p.is_dir()
                                 and not p.name.startswith("__")):
                out.append(f"#### ``{nested.relative_to(HERE)}/``\n\n")
                for path in sorted(nested.glob("*.py")):
                    if path.name not in SKIP:
                        out.append(_entry(path))
                for deeper in sorted(p for p in nested.iterdir() if p.is_dir()
                                     and not p.name.startswith("__")):
                    out.append(f"##### ``{deeper.relative_to(HERE)}/``\n\n")
                    for path in sorted(deeper.glob("*.py")):
                        if path.name not in SKIP:
                            out.append(_entry(path))
            out.append("\n")
    HERE.joinpath("README.md").write_text("".join(out))
    print(f"wrote {HERE / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
