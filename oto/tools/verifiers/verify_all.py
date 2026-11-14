#!/usr/bin/env python3
"""Run every Refactor-1 equivalence verification against the pre-refactor tree.

Owns: the verification-suite orchestrator -- the check list
(CHECKS), the subprocess wiring, the summary report and the overall exit code.
Does NOT own: the checks themselves (the six verify_*.py) or the refactor it
audits (the REFACTOR_BASE pin and the equivalence logic live in each script).
Public API: main.

What "no behaviour change" means for this refactor is stated as five executable
checks rather than as an assurance. Each one compares the current tree against
the last commit before the package split (set REFACTOR_BASE), and each one prints
what it compared and how many comparisons agreed.

    python3 verify_all.py

Exit status is non-zero if any check fails. Every check is read-only: it
compares code and renders reports into a temp dir, never touching
<codename>_runs/ or <codename>_results/.

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

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
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
#: Pass the caller's environment through unchanged. It used to do
#: ``ENV.setdefault("TENSILE_ROOT", "")``, which is not a no-op: when the
#: variable was absent from the shell it *injected an empty value*, and
#: ``require_tensile_root`` reads "set but empty" as an error instead of
#: falling back to the repo-root ``.env``. So the one check that needs the
#: Tensile checkout died on the harness's own placeholder, while passing when
#: run directly -- which is exactly the kind of difference that gets a guard
#: ignored. Inject nothing; let each check resolve it the way the driver does.
ENV = dict(os.environ)
# The children are spawned as scripts, so oto/tools/verifiers/ lands on their
# sys.path instead of the repo root (unlike ``python3 -m oto ...``). Put the
# repo root on PYTHONPATH so the checks import the package the same way the
# driver does. Nothing else is injected.
ENV["PYTHONPATH"] = str(ROOT) + os.pathsep + ENV.get("PYTHONPATH", "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if not ENV.get("TENSILE_ROOT") and not (ROOT / ".env").is_file():
        print("NOTE: TENSILE_ROOT is unset and there is no repo-root .env -- "
              "checks that read Tensile's dtype table will not have a checkout "
              "to read. Export it to exercise them fully.")

    failures = []
    results = []
    for label, script in CHECKS:
        proc = subprocess.run([sys.executable, str(HERE / script)],
                              cwd=ROOT, env=ENV,
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
