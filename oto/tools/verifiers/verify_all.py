#!/usr/bin/env python3
"""Orchestrator for the evergreen verification checks.

Owns: the per-check invocation, the ``--base REF`` parameter (each check takes
the same flag; default HEAD~1, the per-commit evergreen semantic), the
summary and the exit code. Does NOT own: any of the checks.
Public API: main; contract is the exit code (0 clean, 1 findings).

Read-only: each check compares two trees and writes nothing except into a
temporary directory (the worktree is detached and removed at exit).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

CHECKS = [
    ("gate differential", "verify_gates.py"),
    ("method equivalence", "verify_methods.py"),
    ("config writer", "verify_config_render.py"),
    ("report html", "verify_report_render.py"),
    ("ast equivalence", "verify_symbols.py"),
]

ENV = dict(os.environ)
ENV["PYTHONPATH"] = str(ROOT) + os.pathsep + ENV.get("PYTHONPATH", "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--base", default="HEAD~1",
                    help="ref to compare against (default: HEAD~1; pass a specific ref for the legacy-base comparison)")
    ap.add_argument("--limit", type=int, default=None,
                    help="render at most this many phases (config-writer triage)")
    args = ap.parse_args(argv)

    failures = []
    results = []
    for label, script in CHECKS:
        cmd = [sys.executable, str(HERE / script), "--base", args.base]
        if args.limit is not None and script == "verify_config_render.py":
            cmd += ["--limit", str(args.limit)]
        proc = subprocess.run(cmd, cwd=ROOT, env=ENV,
                              capture_output=True, text=True)
        tail = "\n".join(proc.stdout.strip().splitlines()[-6:])
        if not args.json:
            print(tail or "(no output)")
        ok = proc.returncode == 0
        if args.json:
            results.append({"check": label, "script": script, "ok": ok})
        if proc.returncode != 0:
            if not args.json:
                print(f"--- FAILED ({proc.returncode})")
                print("\n".join(proc.stderr.strip().splitlines()[-15:]))
            failures.append(label)
        elif not args.json:
            print("--- OK")

    if args.json:
        print(json.dumps({"ok": not failures, "failed": failures,
                         "checks": results}, indent=2))
        return 1 if failures else 0

    print("\n================ SUMMARY ================")
    for _label, _ in CHECKS:
        print(f"  {'FAIL' if _label in failures else 'OK  '}  {_label}")
    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}")
        return 1
    print("\nALL EQUIVALENCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
