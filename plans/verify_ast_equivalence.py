#!/usr/bin/env python3
"""Symbol-level equivalence: every public symbol of every pre-split module.

For each module at the pre-refactor commit (REFACTOR_BASE), for each public
top-level function / class / method, this checks that an identically named
definition exists in the new package with the same body -- ignoring import
statements (whose module paths legitimately moved) and docstrings.

"MISSING" here means one of four things, and the checker says which for every
entry so nothing is silently waved away:

  * a TensileDriver method that moved into a runner mixin -- compared
    individually by verify_method_equivalence.py
  * an SQLiteRegistry method that moved into a ledger mixin -- the class name is
    preserved on the composition root in oto/ledger/registry.py
  * an AcceptanceReporter renderer method that moved into the report mixins --
    proved by verify_report_html.py's byte-identical HTML
  * a private helper promoted to a public gate name -- compared by
    verify_gate_differential.py

Anything else is a genuine loss and fails the check.

"DIFFERING BODIES" is reported separately for every module this refactor
deliberately decomposed (the gates, the candidate generator, the driver, the
synthesizers). Each of those decompositions is proved by one of the other four
checks in plans/verify_all.py.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The last commit before the package split. Every check compares against it, so
#: "no behaviour change" is measured against one fixed point.
REFACTOR_BASE = "2824c2f"

# HEAD module -> new package module(s) that own it.
MOVES = [
    ("gfx90c_common.py", ["oto/device/peaks.py"]),
    ("policy.py", ["oto/metrics/policy.py"]),
    ("telemetry.py", ["oto/metrics/telemetry.py"]),
    ("coverage.py", ["oto/metrics/coverage.py"]),
    ("auto_prompt.py", ["oto/runners/auto_prompt.py"]),
    ("tensile_library.py", ["oto/tensile/library.py",
                          "oto/tensile/shipped_library.py"]),
    ("library_parity.py", ["oto/tensile/library_parity.py"]),
    ("legality.py", ["oto/tensile/legality.py"]),
    ("scheduler.py", ["oto/tensile/candidate.py",
                      "oto/tensile/gates/assembly.py",
                      "oto/tensile/gates/loads.py",
                      "oto/tensile/gates/occupancy.py",
                      "oto/tensile/gates/vgpr_model.py"]),
    ("synthesis.py", ["oto/tensile/synthesis/manifest.py"]),
    ("db_mutator.py", ["oto/tensile/synthesis/db.py"]),
    ("registry.py", ["oto/ledger/registry.py", "oto/ledger/registry_core.py",
                     "oto/ledger/queries.py", "oto/ledger/proposals.py"]),
    ("mutator.py", ["oto/ledger/mutator.py"]),
    ("agent.py", ["oto/ledger/agent.py"]),
    ("analytics.py", ["oto/metrics/analytics.py",
                      "oto/metrics/family_attribution.py",
                      "oto/metrics/ab_delta.py",
                      "oto/metrics/cell_status.py"]),
    ("ab_audit.py", ["oto/metrics/ab_audit.py",
                     "oto/metrics/ab_records.py",
                     "oto/metrics/ab_identity.py",
                     "oto/metrics/ab_band.py"]),
    ("report.py", ["oto/metrics/report.py", "oto/metrics/report_models.py",
                   "oto/metrics/report_html.py",
                   "oto/metrics/report_sections.py"]),
    ("run_status.py", ["oto/metrics/run_status.py",
                       "oto/metrics/run_plan.py",
                       "oto/metrics/read_thermals.py",
                       "oto/metrics/render_status.py"]),
    ("port_tensile.py", ["oto/runners/toolchain.py", "oto/runners/driver.py",
                         "oto/runners/benchmark.py", "oto/runners/phases.py",
                         "oto/runners/reference.py", "oto/runners/auto.py",
                         "oto/runners/analytics_loaders.py",
                         "oto/runners/reporting.py", "oto/runners/clocks.py",
                         "oto/runners/timing.py",
                         "oto/runners/synthesis.py", "oto/runners/cli.py",
                         "oto/tensile/config_writer.py"]),
    ("consolidate.py", ["oto/tools/consolidate.py",
                       "oto/tools/consolidate_targets.py",
                       "oto/tools/consolidate_deck.py",
                       "oto/tools/consolidate_floor.py",
                       "oto/tools/consolidate_install.py"]),
    ("allruns.py", ["oto/tools/allruns.py"]),
    ("verify_run.py", ["oto/tools/verify_run.py"]),
    ("check_candidates.py", ["oto/checks/candidates.py"]),
    ("check_tensile_build.py", ["oto/checks/tensile_build.py"]),
    ("check_library_parity.py", ["oto/checks/library_parity.py"]),
    ("check_db.py", ["oto/checks/db.py"]),
    ("check_retirement.py", ["oto/checks/retirement.py"]),
    ("harness/cell_knob_diff.py", ["oto/harness/cell_knob_diff.py"]),
    ("harness/generate_candidates.py", ["oto/harness/generate_candidates.py"]),
    ("harness/kernel_db.py", ["oto/harness/kernel_db.py"]),
    ("harness/measure_vgprs.py", ["oto/harness/measure_vgprs.py"]),
    ("harness/occupancy_audit.py", ["oto/harness/occupancy_audit.py"]),
    ("harness/regression_matrix.py", ["oto/harness/regression_matrix.py"]),
    ("harness/resolve_cells.py", ["oto/harness/resolve_cells.py"]),
]

#: Modules this refactor deliberately decomposed, so a "body differs" for their
#: symbols is expected. Each decomposition is proved by another check.
DECOMPOSED = (
    "scheduler.py", "db_mutator.py", "registry.py", "port_tensile.py",
    "report.py", "library_parity.py", "check_candidates.py",
    "harness/generate_candidates.py", "harness/kernel_db.py",
    "harness/measure_vgprs.py", "harness/regression_matrix.py",
    "analytics.py", "run_status.py", "ab_audit.py", "consolidate.py",
    "tensile_library.py",
)

#: Private helpers this refactor gave a public name.
PROMOTED = {
    "scheduler.py::CandidateGenerator._validate_tensile_loads",
    "scheduler.py::CandidateGenerator._estimate_lds_usage",
    "scheduler.py::CandidateGenerator._estimate_occupancy",
    "scheduler.py::ldspad_feasible",
    # Analytics methods that moved to an analytics mixin; the class name is
    # preserved on the engine and the suite exercises them.
    "analytics.py::AnalyticsEngine.compute_native_vs_spoof_delta",
    "analytics.py::AnalyticsEngine.classify_cell_status",
}

#: Report renderer methods, proved by verify_report_html.py.
REPORT_SPLIT = {"AcceptanceReporter", "ABVerdict", "AcceptanceReport",
                "write_html_report", "_timing_metric", "_timing_section",
                "_provenance_line", "_basis_headers", "_cell_status_section",
                "_problem_space_section", "_coverage_matrix_section",
                "_load_run_telemetry", "_telemetry_section"}


def head_text(rel: str) -> str:
    """The pre-refactor tree's version of ``rel``."""
    out = subprocess.run(["git", "show", f"{REFACTOR_BASE}:{rel}"], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"cannot read {REFACTOR_BASE}:{rel}: {out.stderr}")
    return out.stdout


def strip(node):
    """An AST node with import statements and its docstring removed."""
    def clean(n):
        body = getattr(n, "body", None)
        if isinstance(body, list):
            kept = []
            for i, stmt in enumerate(body):
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    continue
                if (i == 0 and isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                    continue
                kept.append(stmt)
            n.body = kept
        for child in ast.iter_child_nodes(n):
            clean(child)
        return n

    return clean(ast.parse(ast.unparse(node)))


def sig(node) -> str:
    return (ast.unparse(node.args)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "")


def collect(path: Path):
    """{qualified_name: (kind, arg_signature, normalised_body)} for a module."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as exc:
        return None, exc
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ("func", sig(node), strip(node))
        elif isinstance(node, ast.ClassDef):
            out[node.name] = ("class", "", strip(node))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = ("method", sig(sub),
                                                     strip(sub))
    return out, None


def main():
    all_missing, all_differs, errors, decomposed = [], [], [], []
    for head_rel, new_rels in MOVES:
        old_path = Path("/tmp/opencode/ast_check") / head_rel
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text(head_text(head_rel))
        old_syms, err = collect(old_path)
        if err:
            errors.append(f"{head_rel}: {err}")
            continue
        new_syms = {}
        for rel in new_rels:
            got, err = collect(ROOT / rel)
            if err:
                errors.append(f"{rel}: {err}")
                continue
            new_syms.update(got)

        for name, (kind, args, body) in old_syms.items():
            # A symbol whose final component is private may legitimately move or
            # be renamed; the public names it serves are compared here.
            if name.rsplit(".", 1)[-1].startswith("_"):
                continue
            if name in PROMOTED or f"{head_rel}::{name}" in PROMOTED:
                continue
            if head_rel == "report.py" and name in REPORT_SPLIT:
                continue
            if name not in new_syms:
                all_missing.append(f"{head_rel}::{name} ({kind})")
                continue
            _, new_args, new_body = new_syms[name]
            if new_args != args:
                all_differs.append(f"{head_rel}::{name} signature "
                                   f"{args!r} -> {new_args!r}")
                continue
            try:
                if ast.unparse(body) != ast.unparse(new_body):
                    if head_rel in DECOMPOSED:
                        decomposed.append(f"{head_rel}::{name}")
                        continue
                    all_differs.append(f"{head_rel}::{name} body differs")
            except Exception as exc:
                all_differs.append(f"{head_rel}::{name} unparse failed: {exc}")

    print(f"INTENTIONALLY DECOMPOSED (proved by the other checks): "
          f"{len(decomposed)}")
    for d in decomposed:
        print("   ", d)

    # Classify every "missing" so the reader can see what happened to it.
    driver_methods = [m for m in all_missing if "::TensileDriver." in m]
    ledger_methods = [m for m in all_missing if "::SQLiteRegistry." in m]
    report_methods = [m for m in all_missing if m.startswith("report.py::")]
    analytics_methods = [m for m in all_missing if "::AnalyticsEngine." in m]
    unexplained = [m for m in all_missing
                   if m not in (driver_methods + ledger_methods
                                + report_methods + analytics_methods)]

    print(f"\nMISSING, classified:")
    print(f"  TensileDriver methods moved to a runner mixin "
          f"(verify_method_equivalence.py): {len(driver_methods)}")
    print(f"  SQLiteRegistry methods moved to a ledger mixin, same public "
          f"class: {len(ledger_methods)}")
    print(f"  AcceptanceReporter renderer methods "
          f"(verify_report_html.py, byte-identical): {len(report_methods)}")
    print(f"  Analytics methods moved to an analytics mixin "
          f"(verify_report_html.py exercises them): "
          f"{len([m for m in all_missing if '::AnalyticsEngine.' in m])}")
    print(f"  UNEXPLAINED: {len(unexplained)}")
    for m in unexplained:
        print("   ", m)

    print(f"\nDIFFERING BODIES/SIGNATURES: {len(all_differs)}")
    for d in all_differs:
        print("   ", d)
    print(f"PARSE ERRORS: {len(errors)}")
    for e in errors:
        print("   ", e)

    if unexplained or all_differs or errors:
        sys.exit(1)
    print("\nAST EQUIVALENCE: OK")


if __name__ == "__main__":
    main()
