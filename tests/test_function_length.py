#!/usr/bin/env python3
"""test_function_length.py — acceptance criterion 1b of Refactor 1.

"No function over 60 lines" is a documented acceptance criterion
(`incomplete_work.md`, AC 1b). This test is the executable form of it: the rule
used to live only in that register, and the script that enforced it was deleted
with the other untracked `plans/` scripts on 2026-10-14, so nothing stopped a
regression.

The measure is the whole ``def .. end_lineno`` span, which is what the
criterion names. It deliberately does NOT subtract the docstring: the criterion
is "a function too long to follow", and a 59-code-line function with a 30-line
docstring is still a screenful to read. The register's *code-only* column is the
column that should drive which seam to cut; this span is the exit test.

A failure here is a signal to decompose, not to raise the limit. If a function
genuinely cannot be cut, raise the limit in `incomplete_work.md` with the reason
and update this constant to match — never the other way round.

Only the function criterion is enforced here. The file-level criterion (no file
over 600 lines) is tracked in the register but is NOT asserted: at the time of
writing the largest file is already 606 lines, so the test would be red for a
pre-existing reason, and a guard that is red on arrival is ignored instead of
obeyed. Amend the register, fix the file, then add the assertion.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent

#: The acceptance criterion, in one place.
MAX_FUNCTION_LINES = 60


def _functions(only: Optional[List[str]] = None):
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
    """AC 1b: no function in oto/**/*.py spans more than 60 lines."""
    offenders = [
        (path, name, lineno, span)
        for path, name, lineno, span in _functions(changed_python_files or None)
        if span > MAX_FUNCTION_LINES
    ]
    assert not offenders, (
        f"{len(offenders)} function(s) over {MAX_FUNCTION_LINES} lines "
        f"(AC 1b, incomplete_work.md). Decompose them, or amend the criterion "
        f"there with a reason:\n"
        + "\n".join(f"  {span:4d}  {path}:{lineno}  {name}"
                    for path, name, lineno, span in
                    sorted(offenders, reverse=True))
    )
