"""Module docstring convention guard: every oto module carries the three clauses.

The convention is documented in docs/docstrings.md. pdoc renders these clauses
as prose; this test keeps them present so the generated reference is useful.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = sorted(ROOT.glob("oto/**/*.py"))
CLAUSES = ("Owns:", "Does NOT own", "Public API")


def test_every_module_docstring_has_three_clauses():
    missing = []
    for path in MODULES:
        doc = ast.get_docstring(ast.parse(path.read_text()))
        if not doc:
            missing.append((path, "no module docstring"))
            continue
        missing.extend((path, clause) for clause in CLAUSES if clause not in doc)
    assert not missing, "modules missing docstring clauses:\n" + "\n".join(
        f"  {p}: {c}" for p, c in missing)
