#!/usr/bin/env python3
"""test_function_length.py — no function in oto/**/*.py spans more than 60 lines.

The 60-line rule is a hard acceptance criterion of this repository (see
``docs/gfx90c/gfx90c_knowledge_base.md`` and the guard's own history); this is its executable
form, so a regression fails the suite instead of shipping. The file-level
criterion (no tracked file over 600 lines) is a sibling guard and is asserted
repo-wide by ``tests/test_file_length.py``.

The measure is the whole ``def .. end_lineno`` span, which is what the
criterion names. It deliberately does NOT subtract the docstring: the criterion
is "a function too long to follow", and a 59-code-line function with a 30-line
docstring is still a screenful to read.

A failure here is a signal to decompose, not to raise the limit. If a function
genuinely cannot be cut, raise the limit in this constant with the reason in
the commit message — never the other way round.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The acceptance criterion, in one place.
MAX_FUNCTION_LINES = 60


def _functions(only: list[str] | None = None):
    """Every (file, name, lineno, span) function in the oto package.

    Args:
        only: When given, the repo-relative paths to scan instead of the whole
            tree (the ``OTO_GUARD_FILES=1`` fast path: the guard then checks
            what you touched, not everything).
    """
    if only:
        paths = [REPO / rel for rel in only]
    else:
        paths = sorted((REPO / "oto").rglob("*.py"))
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError as exc:
            raise AssertionError(f"{path} does not parse: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = (node.end_lineno or node.lineno) - node.lineno + 1
                yield path.relative_to(REPO), node.name, node.lineno, span


def test_no_function_exceeds_the_line_limit(changed_python_files):
    """the 60-line rule: no function in oto/**/*.py spans more than 60 lines."""
    offenders = [
        (path, name, lineno, span)
        for path, name, lineno, span in _functions(changed_python_files or None)
        if span > MAX_FUNCTION_LINES
    ]
    assert not offenders, (
        f"{len(offenders)} function(s) over {MAX_FUNCTION_LINES} lines "
        f"(the 60-line rule). Decompose them, or amend the constant "
        f"here with a reason:\n"
        + "\n".join(f"  {span:4d}  {path}:{lineno}  {name}"
                    for path, name, lineno, span in
                    sorted(offenders, reverse=True))
    )
