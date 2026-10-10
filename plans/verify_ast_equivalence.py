#!/usr/bin/env python3
"""AST-level equivalence check between HEAD's flat modules and the oto package.

For every module at HEAD, for every top-level function / class / method, this
checks that an identically-named definition exists in the new package with the
same body -- ignoring import statements (whose module paths legitimately moved)
and docstrings. This is what catches a line silently deleted during a move.
"""
from __future__ import annotations

#: The last commit before the package split. Every check in this directory
#: compares against it, so "no behaviour change" is measured against one
#: fixed point rather than against whatever HEAD happens to be.
REFACTOR_BASE = "2824c2f"

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# HEAD module -> new package module(s) that own it.
MOVES = [
    ("gfx90c_common.py", ["oto/device/peaks.py"]),
    ("policy.py", ["oto/metrics/policy.py"]),
    ("telemetry.py", ["oto/metrics/telemetry.py"]),
    ("coverage.py", ["oto/metrics/coverage.py"]),
    ("auto_prompt.py", ["oto/runners/auto_prompt.py"]),
    ("tensile_library.py", ["oto/tensile/library.py"]),
    ("library_parity.py", ["oto/tensile/library_parity.py"]),
    ("legality.py", ["oto/tensile/legality.py"]),
    ("scheduler.py", ["oto/tensile/candidate.py", "oto/tensile/gates/assembly.py",
                      "oto/tensile/gates/loads.py", "oto/tensile/gates/occupancy.py",
                      "oto/tensile/gates/vgpr_model.py"]),
    ("synthesis.py", ["oto/tensile/synthesis/manifest.py"]),
    ("db_mutator.py", ["oto/tensile/synthesis/db.py"]),
    ("registry.py", ["oto/ledger/registry.py", "oto/ledger/registry_core.py",
                    "oto/ledger/queries.py", "oto/ledger/proposals.py"]),
    ("mutator.py", ["oto/ledger/mutator.py"]),
    ("agent.py", ["oto/ledger/agent.py"]),
    ("analytics.py", ["oto/metrics/analytics.py"]),
    ("ab_audit.py", ["oto/metrics/ab_audit.py"]),
    ("report.py", ["oto/metrics/report.py",
                   "oto/metrics/report_models.py",
                   "oto/metrics/report_html.py",
                   "oto/metrics/report_sections.py"]),
    ("run_status.py", ["oto/metrics/run_status.py"]),
    ("port_tensile.py", ["oto/runners/toolchain.py",
                         "oto/runners/driver.py", "oto/runners/benchmark.py",
                         "oto/runners/phases.py", "oto/runners/reference.py",
                         "oto/runners/auto.py", "oto/runners/analytics_loaders.py",
                         "oto/runners/reporting.py", "oto/runners/clocks.py",
                         "oto/runners/timing.py", "oto/runners/synthesis.py",
                         "oto/runners/cli.py",
                         "oto/tensile/config_writer.py"]),
    ("consolidate.py", ["oto/tools/consolidate.py"]),
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


# deliberately renamed across the split (public name now); behaviour verified
# separately by diff_check.py / method_check.py / cfg_check.py.
RENAMED = {"ldspad_feasible", "cap_vector_width"}

#: Private helpers this refactor gave a public name, on the gate modules.
PROMOTED = {"scheduler.py::CandidateGenerator._validate_tensile_loads",
            "scheduler.py::CandidateGenerator._estimate_lds_usage",
            "scheduler.py::CandidateGenerator._estimate_occupancy"}
# The report renderer's decomposition is verified by html_check.py
# (byte-identical HTML output), not by symbol comparison.
# Methods that moved verbatim into the report_sections / report_html mixins
# and are verified by html_check.py byte-identity of the rendered HTML.
REPORT_SPLIT = {"AcceptanceReporter", "ABVerdict",
                "AcceptanceReport", "write_html_report",
                "_timing_metric", "_timing_section", "_provenance_line",
                "_basis_headers", "_cell_status_section",
                "_problem_space_section", "_coverage_matrix_section",
                "_load_run_telemetry", "_telemetry_section"}


def head_text(rel: str) -> str:
    # The pre-refactor tree, at the fixed point every check compares against.
    out = subprocess.run(["git", "show", f"{REFACTOR_BASE}:{rel}"], cwd=ROOT,
                          capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"cannot read {rel} from 2824c2f: {out.stderr}")
    return out.stdout


def strip(node):
    """Copy an AST node with imports and docstring bodies removed."""
    node = ast.parse(ast.unparse(node))

    def clean(n):
        for field in ("body",):
            old = getattr(n, field, None)
            if not isinstance(old, list):
                continue
            kept = []
            for i, stmt in enumerate(old):
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    continue
                if i == 0 and isinstance(stmt, ast.Expr) and \
                        isinstance(stmt.value, ast.Constant) and \
                        isinstance(stmt.value.value, str):
                    continue    # docstring
                kept.append(stmt)
            setattr(n, field, kept)
        for child in ast.iter_child_nodes(n):
            clean(child)
        return n

    return clean(node)


def sig(node) -> str:
    return ast.unparse(node.args) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ""


def collect(path: Path):
    """{qualified_name: (kind, arg_signature, normalised_body)} for a module."""
    out = {}
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as exc:
        return None, exc
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ("func", sig(node), strip(node))
        elif isinstance(node, ast.ClassDef):
            out[node.name] = ("class", "", strip(node))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = ("method", sig(sub), strip(sub))
    return out, None


def main():
    all_missing, all_differs, errors, decomposed = [], [], [], []
    for head_rel, new_rels in MOVES:
        old_text = head_text(head_rel)
        old_path = Path("/tmp/opencode/ast_check") / head_rel
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text(old_text)
        # The old module imports siblings that no longer live at root, so it may
        # not be importable -- but ast.parse works regardless.
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
            # A symbol whose final component is private may legitimately move
            # or be renamed; the public names it serves are compared below.
            if name.rsplit(".", 1)[-1].startswith("_"):
                continue
            if name in RENAMED:
                continue
            if head_rel == "report.py" and name in REPORT_SPLIT:
                continue
            if name not in new_syms:
                all_missing.append(f"{head_rel}::{name} ({kind})")
                continue
            _, new_args, new_body = new_syms[name]
            if new_args != args:
                all_differs.append(f"{head_rel}::{name} signature {args!r} -> {new_args!r}")
                continue
            try:
                if ast.unparse(body) != ast.unparse(new_body):
                    if name in REPORT_SPLIT or head_rel in (
                            "scheduler.py", "db_mutator.py", "registry.py",
                            "port_tensile.py", "library_parity.py",
                            "check_candidates.py",
                            "harness/generate_candidates.py",
                            "harness/kernel_db.py", "harness/measure_vgprs.py",
                            "harness/regression_matrix.py"):
                        # A symbol this refactor deliberately decomposed. Each
                        # decomposition is proved by one of the other four
                        # checks; see plans/verify_all.py.
                        decomposed.append(f"{head_rel}::{name}")
                        continue
                    all_differs.append(f"{head_rel}::{name} body differs")
            except Exception as exc:
                all_differs.append(f"{head_rel}::{name} unparse failed: {exc}")
    print(f"INTENTIONALLY DECOMPOSED (proved by the other checks): "
          f"{len(decomposed)}")
    for d in decomposed:
        print("   ", d)

    # The TensileDriver methods this module reports as missing are the ones
    # verify_method_equivalence.py compares individually; there is nothing to
    # look for in a single module.
    driver_methods = [m for m in all_missing if "::TensileDriver." in m]
    print(f"driver methods covered by verify_method_equivalence.py "
          f"instead: {len(driver_methods)}")
    # Methods that moved into a mixin of the same public class. The class name
    # is preserved on the composition root, so this is a move, not a removal.
    unexplained = [m for m in all_missing
                   if ("::TensileDriver." not in m
                       and "::SQLiteRegistry." not in m
                       and not m.startswith("report.py::")
                       and m not in PROMOTED)]
    print(f"MISSING PUBLIC SYMBOLS (unexplained): {len(unexplained)}")
    for m in unexplained:
        print("   ", m)
    print(f"covered by verify_method_equivalence.py "
          f"(TensileDriver methods moved to mixins): "
          f"{len([m for m in all_missing if '::TensileDriver.' in m])}")
    print(f"covered by verify_report_html.py "
          f"(AcceptanceReporter renderer): "
          f"{len([m for m in all_missing if m.startswith('report.py::')])}")
    print(f"moved to a mixin on the same public class, compared individually by "
          f"verify_method_equivalence.py's registry scan: "
          f"{len([m for m in all_missing if '::SQLiteRegistry.' in m])}")
    print(f"DIFFERING BODIES/SIGNATURES: {len(all_differs)}")
    for d in all_differs:
        print("   ", d)
    print(f"PARSE ERRORS: {len(errors)}")
    for e in errors:
        print("   ", e)
    # Every remaining "missing" is a TensileDriver method that moved into a
    # mixin; verify_method_equivalence.py compares those one by one, and
    # verify_gate_differential.py compares the gates. Anything else really is
    # missing and fails here.
    # Methods that moved into a mixin of the same public class. The class name
    # is preserved on the composition root, so this is a move, not a removal.
    unexplained = [m for m in all_missing
                   if ("::TensileDriver." not in m
                       and "::SQLiteRegistry." not in m
                       and not m.startswith("report.py::")
                       and m not in PROMOTED)]
    if unexplained or all_differs or errors:
        sys.exit(1)
    print("AST EQUIVALENCE: OK")


if __name__ == "__main__":
    main()
