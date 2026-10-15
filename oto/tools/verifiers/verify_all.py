#!/usr/bin/env python3
"""Run every Refactor-1 equivalence verification against the pre-refactor tree.

What "no behaviour change" means for this refactor is stated as five executable
checks rather than as an assurance. Each one compares the current tree against
the last commit before the package split (set REFACTOR_BASE), and each one prints
what it compared and how many comparisons agreed.

    python3 verify_all.py

Exit status is non-zero if any check fails. Every check is read-only: it
compares code and renders reports into a temp dir, never touching
gfx90c_runs/ or gfx90c_results/.

Checks:
  1. verify_gate_differential.py   every scheduler gate/function over an
                                   exhaustive config corpus (128k comparisons)
  2. verify_method_equivalence.py  all 57 TensileDriver methods that moved into a
                                   mixin, by AST body
  3. verify_config_writer.py       6037 live phases, old vs new config writer:
                                   (ok, reason) AND the exact YAML bytes
  4. verify_report_html.py         the rendered dashboard, byte for byte
  5. verify_ast_equivalence.py     every public symbol of every pre-split module
                                   still exists with the same body
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

CHECKS = [
    ("gate differential", "verify_gate_differential.py"),
    ("method equivalence", "verify_method_equivalence.py"),
    ("config writer", "verify_config_writer.py"),
    ("report html", "verify_report_html.py"),
    ("ast equivalence", "verify_ast_equivalence.py"),
]

#: Tensile is not needed for #1/#3's gate logic but IS needed for the dtype table
#: the report and config checks read.
ENV = dict(os.environ)
ENV.setdefault("TENSILE_ROOT", "")


def main() -> int:
    if not ENV.get("TENSILE_ROOT"):
        print("NOTE: TENSILE_ROOT is unset -- checks that read Tensile's dtype "
              "table will report fewer records. Export it to exercise them "
              "fully.")

    failures = []
    for label, script in CHECKS:
        print(f"\n=== {label} ({script})")
        proc = subprocess.run([sys.executable, str(HERE / script)],
                              cwd=ROOT, env=ENV,
                              capture_output=True, text=True)
        tail = "\n".join(proc.stdout.strip().splitlines()[-6:])
        print(tail or "(no output)")
        if proc.returncode != 0:
            print(f"--- FAILED ({proc.returncode})")
            print("\n".join(proc.stderr.strip().splitlines()[-15:]))
            failures.append(label)
        else:
            print(f"--- OK")

    print("\n================ SUMMARY ================")
    for label, _ in CHECKS:
        print(f"  {'FAIL' if label in failures else 'OK  '}  {label}")
    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}")
        return 1
    print("\nALL EQUIVALENCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
