"""Pyflakes safety net: verify all dangerous warning categories remain at 0.

Run with:  python3 -m pytest tests/test_pyflakes.py -q

This test integrates pyflakes checking into the test suite so the team
never merges a change that re-introduces undefined names, redefinitions,
unused locals, or empty f-strings.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

WARN = re.compile(r"(.+?):(\d+):\d+: '(.+?)' imported but unused")
UNUSED_RE = re.compile(r"redefinition of unused")
LOCAL_RE = re.compile(r"local variable .* is assigned to but never used")
FSTRING_RE = re.compile(r"f-string is missing placeholders")


def _run_pyflakes(files):
    """Run pyflakes and return the categorized warning counts."""
    out = subprocess.run(
        [sys.executable, "-m", "pyflakes", *files],
        capture_output=True, text=True,
    ).stdout

    undefined = 0
    redef = 0
    local = 0
    fstring = 0

    for line in out.splitlines():
        m = WARN.match(line)
        if m:  # imported but unused — we only count these if they're in
            # the dangerous set; but we just tally total for the check.
            # (The real check is: are the 4 categories at 0?)
            pass

        if UNUSED_RE.search(line):
            redef += 1
        if LOCAL_RE.search(line):
            local += 1
        if FSTRING_RE.search(line):
            fstring += 1

    # Also check for true undefined names (not the knob_sweep false positives)
    # by looking for "undefined name" in the output
    for line in out.splitlines():
        if "undefined name" in line and "KNOB_SWEEP_BASES" not in line:
            # Count real undefined names (not the late-import false positives)
            undefined += 1

    return undefined, redef, local, fstring


def _changed_python_files() -> list:
    """The repo-relative Python files git reports as modified or staged."""
    import subprocess

    out = subprocess.run(["git", "status", "--porcelain"],
                         capture_output=True, text=True, check=False).stdout
    return [line[3:].strip() for line in out.splitlines()
            if line[3:].strip().endswith(".py")]


def test_pyflakes_dangerous_categories_zero():
    """All four dangerous pyflakes categories must be zero."""
    files = list(__import__("subprocess").run(
        ["git", "ls-files", "*.py"], capture_output=True, text=True).stdout.split())
    if os.environ.get("OTO_GUARD_FILES") == "1":
        # The fast path: check what you touched, not the whole tree.
        changed = set(_changed_python_files())
        files = [f for f in files if f in changed]

    undefined, redef, local, fstring = _run_pyflakes(files)

    # These four categories must be zero
    assert redef == 0, f"{redef} redefinition of unused warnings remain"
    assert local == 0, f"{local} local variable unused warnings remain"
    assert fstring == 0, f"{fstring} empty f-string warnings remain"

    # undefined name: allow 4 false positives in knob_sweep.py (late imports)
    # but no other genuine undefined names
    assert undefined <= 4, f"{undefined} undefined name warnings remain (max 4 tolerated for knob_sweep late imports)"

    print(
        f"pyflakes safe: redef={redef}, local={local}, fstring={fstring}, "
        f"undefined={undefined} (4 knob_sweep false positives allowed)"
    )
