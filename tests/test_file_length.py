"""File-length guard: no tracked ``*.py`` file exceeds 600 lines.

Run with:  python3 -m pytest tests/test_file_length.py -q

Small files are a reviewability property: a maintainer (or an agent) must be
able to hold a module in working memory. 600 lines is the ceiling this repo
already sketched in `incomplete_work.md`; it was not enforced while there were
five known offenders. This test *ratchets* instead:

* any tracked file over 600 lines that is NOT in ``OFFENDERS`` fails the suite;
* a file in ``OFFENDERS`` that shrinks to <= 600 lines also fails — remove it
  from the list in the same commit (the list may only shrink or stay flat).

Current offenders are grandfathered, not endorsed — each needs a decomposition
commit. `OTO_GUARD_FILES=1` narrows the check to files git reports as
modified/staged (the changed-files path may only pass if the offenders list
and the tree agree, same rules).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIMIT = 600

# Grandfathered offenders, captured 2026-11-13. Each entry is a commitment to
# split the file in a later commit; the list may only shrink.
OFFENDERS = {
    "tests/test_phase1_integration.py",  # 1008 lines
    "tests/test_synthesis_phase4.py",    # 780 lines
    "tests/test_occupancy_gate.py",      # 779 lines
    "tests/test_run_status.py",          # 620 lines
    "oto/metrics/run_status.py",         # 608 lines
}


def _git_files() -> list[str]:
    return subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    ).stdout.split()


def _changed_files() -> list[str]:
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


def test_no_file_over_600_lines():
    files = _git_files()
    if os.environ.get("OTO_GUARD_FILES") == "1":
        changed = set(_changed_files())
        files = [f for f in files if f in changed]

    over = {}
    for rel in files:
        path = REPO / rel
        if not path.exists():
            continue
        n = sum(1 for _ in path.open("rb"))
        if n > LIMIT:
            over[rel] = n

    new_offenders = {f: n for f, n in over.items() if f not in OFFENDERS}
    assert not new_offenders, (
        "File(s) over 600 lines not grandfathered:\n"
        + "\n".join(f"  {f}: {n}" for f, n in sorted(new_offenders.items()))
    )

    shrunk = {f for f in OFFENDERS if f not in over}
    assert not shrunk, (
        "Grandfathered file(s) now <= 600 lines — remove them from OFFENDERS "
        "in the same commit:\n" + "\n".join(f"  {f}" for f in sorted(shrunk))
    )

    print(f"file length ok: {len(files)} files, {len(over)} grandfathered offender(s)")
