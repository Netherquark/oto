"""py_compile safety net: every tracked ``*.py`` must byte-compile.

Run with:  python3 -m pytest tests/test_py_compile.py -q

This integrates the ``python -m py_compile`` check into the test suite: each
file in scope is compiled with the built-in ``compile()`` (the same front-end
py_compile runs), so a syntax error — an unmatched bracket, a stray token, a
a bad indentation introduced mid-edit — fails here *before* it reaches any
test that would import or exec the file.

The check writes no ``.pyc`` artifacts (unlike a bare ``compileall`` run); the
source text is compiled in memory and discarded. Set ``OTO_GUARD_FILES=1`` to
check only the files git reports as modified/staged — the fast path used by
the per-commit preflight.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _ls_py_files() -> list[str]:
    return subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    ).stdout.split()


def _changed_python_files() -> list[str]:
    """The repo-relative Python files git reports as modified or staged."""
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    ).stdout
    return [
        line[3:].strip()
        for line in out.splitlines()
        if line[3:].strip().endswith(".py")
    ]


def test_every_tracked_file_byte_compiles():
    files = _ls_py_files()
    if os.environ.get("OTO_GUARD_FILES") == "1":
        changed = set(_changed_python_files())
        files = [f for f in files if f in changed]

    if not files:
        # OTO_GUARD_FILES=1 with a clean tree: nothing to check, and that is fine.
        print("py_compile: no Python files in scope (OTO_GUARD_FILES clean tree)")
        return

    failures: list[str] = []
    for rel in files:
        path = REPO / rel
        try:
            source = path.read_text()
        except UnicodeDecodeError as exc:
            failures.append(f"{rel}: cannot decode as utf-8: {exc}")
            continue
        try:
            compile(source, rel, "exec")
        except SyntaxError as exc:
            failures.append(f"{rel}: {exc}")
        except Exception as exc:  # e.g. MemoryError on hostile input; keep the gate loud
            failures.append(f"{rel}: {type(exc).__name__}: {exc}")

    assert not failures, "py_compile failures:\n" + "\n".join(failures)
    print(f"py_compile safe: {len(files)} files, 0 compile errors")
