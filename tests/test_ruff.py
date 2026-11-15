"""Ruff safety net: the repo must stay clean under the pinned rule set in ``ruff.toml``.

Run with:  python3 -m pytest tests/test_ruff.py -q

This test integrates ruff checking into the test suite so the repo never
regresses into undefined names, unused imports, duplicate definitions or the
other defect classes caught by the substantive rules listed in ``ruff.toml``
(pycodestyle, pyflakes, bugbear, pyupgrade, import sorting, comprehensions,
pep8-naming and the resolved return-value rules).

The bar is absolute: ruff exits non-zero on *any* finding, so this gate fails
on the first offender. The pinned ``ruff.toml`` documents the deliberate
trade-offs (notably: complexity, docstring and security-smell rules are out of
scope for this repo; see the header comment there).

Set ``OTO_GUARD_FILES=1`` to check only the Python files git reports as
modified/staged -- the fast path used by the per-commit preflight.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _ls_py_files() -> list[str]:
    files = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    ).stdout.split()
    # Deleted-in-worktree files still appear in the index; the guard walks the
    # tree, so a file that no longer exists must not be in scope.
    return [f for f in files if (REPO / f).is_file()]


def _changed_python_files() -> list[str]:
    """The repo-relative Python files git reports as modified or staged."""
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    ).stdout
    files = []
    for line in out.splitlines():
        path = line[3:].strip()
        if " -> " in path:  # staged rename: take the destination
            path = path.split(" -> ", 1)[1]
        if path.endswith(".py"):
            files.append(path)
    return files


def test_ruff_repo_is_clean():
    files = _ls_py_files()
    if os.environ.get("OTO_GUARD_FILES") == "1":
        changed = set(_changed_python_files())
        files = [f for f in files if f in changed]
        if not files:
            # OTO_GUARD_FILES=1 on a clean tree would check nothing; the full
            # scan keeps the guard meaningful instead of vacuous.
            files = _ls_py_files()

    proc = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            "--config", "ruff.toml",
            *files,
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )

    if proc.returncode != 0:
        if proc.stderr.startswith("Usage:") or "No module named ruff" in proc.stderr:
            raise AssertionError(
                "ruff is not installed for this interpreter: "
                f"{proc.stderr.strip()}\n"
                "Install it (e.g. `python3 -m pip install ruff`) or use the same "
                "interpreter CI uses.",
            )
        raise AssertionError(
            "ruff findings:\n" + proc.stdout + proc.stderr,
        )

    print(f"ruff safe: {len(files)} files, 0 findings under ruff.toml")
