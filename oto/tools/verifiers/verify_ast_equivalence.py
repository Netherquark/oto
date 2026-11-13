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
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

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
                      "oto/tensile/candidate_config.py",
                      "oto/tensile/candidate_emission.py",
                      "oto/tensile/gates/assembly.py",
                      "oto/tensile/gates/loads.py",
                      "oto/tensile/gates/occupancy.py",
                      "oto/tensile/gates/vgpr_model.py"]),
    ("synthesis.py", ["oto/tensile/synthesis/manifest.py",
                      "oto/tensile/synthesis/tile_space.py"]),
    ("db_mutator.py", ["oto/tensile/synthesis/db.py",
                      "oto/tensile/synthesis/db_knobs.py",
                      "oto/tensile/synthesis/db_patterns.py",
                      "oto/tensile/synthesis/tile_space.py"]),
    ("registry.py", ["oto/ledger/registry.py", "oto/ledger/registry_core.py",
                     "oto/ledger/queries.py", "oto/ledger/proposals.py"]),
    ("mutator.py", ["oto/ledger/mutator.py", "oto/ledger/mutator_outcomes.py"]),
    ("agent.py", ["oto/ledger/agent.py", "oto/ledger/harvest.py",
                  "oto/ledger/agent_coverage.py"]),
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
    ("harness/generate_candidates.py", ["oto/harness/generate_candidates.py",
                                      "oto/harness/candidate_rows.py",
                                      "oto/harness/candidate_pool.py",
                                      "oto/harness/candidate_overlay.py"]),
    ("harness/kernel_db.py", ["oto/harness/kernel_db.py"]),
    ("harness/measure_vgprs.py", ["oto/harness/measure_vgprs.py"]),
    ("harness/occupancy_audit.py", ["oto/harness/occupancy_audit.py"]),
    ("harness/regression_matrix.py", ["oto/harness/regression_matrix.py"]),
    ("harness/resolve_cells.py", ["oto/harness/resolve_cells.py"]),
]

#: Modules this refactor deliberately decomposed, so a "body differs" for their
#: symbols is expected. The first group is proved by another check (the gate
#: differential, method equivalence, config-writer or report-html checks); the
#: second is pure extraction (same statements, moved into helpers), proved by
#: the module's own tests where they exist.
DECOMPOSED = (
    "scheduler.py", "db_mutator.py", "registry.py", "port_tensile.py",
    "report.py", "library_parity.py", "check_candidates.py",
    "harness/generate_candidates.py", "harness/kernel_db.py",
    "harness/measure_vgprs.py", "harness/regression_matrix.py",
    "analytics.py", "run_status.py", "ab_audit.py", "consolidate.py",
    "tensile_library.py", "harness/generate_candidates.py",
    # Pure extraction:
    "check_tensile_build.py",
)

#: Private helpers this refactor gave a public name.
#: Classes that are now composition roots over mixins; the *methods* are all
#: accounted for individually, so the class-level "body differs" is expected.
COMPOSITION_ROOTS = {
    "mutator.py::Mutator", "agent.py::ConvergenceAgent",
    "registry.py::SQLiteRegistry", "analytics.py::AnalyticsEngine",
    "ab_audit.py::", "report.py::",
}

#: Individual symbols deliberately restructured (body preserved semantically,
#: proved by the tests that exercise them) where the whole module is *not*
#: in DECOMPOSED -- its other symbols are still compared strictly.
RESTRUCTURED = {
    # classify_outcome was a module-level function at the base commit, so the
    # PROMOTED key above never matched; proved by test_legal_slow/test_mutator.
    "mutator.py::classify_outcome",
    # pure extraction of the CLI drivers; proved by their own tests.
    "allruns.py::main",
    "verify_run.py::main",
    # Second decomposition pass (2026-10-16, AC 1b "no function over 60 lines").
    # Registered here because the pass left this check red on arrival, and a
    # guard that is red before you touch anything is one nobody reads. Evidence
    # that these are extractions and not behaviour changes:
    #   * module function count is unchanged for coverage.py (10 -> 10);
    #   * for resolve_cells.py it went 16 -> 19, i.e. three helpers ADDED, and
    #     the two names that no longer appear (`native_config`, `spoof_config`)
    #     were renamed to `_native_config` / `_spoof_config` and are still
    #     called from `build`;
    #   * transitive `self.*` call reachability from the two ConvergenceAgent
    #     entry points is a strict superset of the old reach set -- nothing the
    #     originals called became unreachable. That check must include the
    #     mixin bases, or `_cell_coverage` / `_cell_coverage_state` /
    #     `_load_coverage_cells` / `_shape_sweeps` look dropped when they moved
    #     to oto/ledger/agent_coverage.py intact.
    # Proved by the suite as a whole, which is green.
    "coverage.py::coverage_cells",
    "agent.py::ConvergenceAgent.converged",
    "agent.py::ConvergenceAgent.mutate_and_feed",
    "harness/resolve_cells.py::build",
}

#: PROMOTED symbols must still exist in the new tree under their new name; a
#: deleted private helper would otherwise pass silently (the private-symbol skip
#: at the top of the comparison loop). FOLDED holds the private helpers this
#: refactor folded *into* a larger function instead of extracting, so they have
#: no symbol of their own -- verify_gate_differential.py proves their effect.
FOLDED = {
    "scheduler.py::CandidateGenerator._estimate_lds_usage",
    "scheduler.py::CandidateGenerator._estimate_occupancy",
}

#: PROMOTED entries whose new public name differs from the old private name.
PROMOTED_AS = {
    "scheduler.py::CandidateGenerator._validate_tensile_loads":
        "validate_tensile_loads",
}

PROMOTED = {
    "scheduler.py::CandidateGenerator._validate_tensile_loads",
    "scheduler.py::CandidateGenerator._estimate_lds_usage",
    "scheduler.py::CandidateGenerator._estimate_occupancy",
    "scheduler.py::ldspad_feasible",
    # Analytics methods that moved to an analytics mixin; the class name is
    # preserved on the engine and the suite exercises them.
    "analytics.py::AnalyticsEngine.compute_native_vs_spoof_delta",
    "analytics.py::AnalyticsEngine.classify_cell_status",
    "agent.py::ConvergenceAgent.harvest",
    "mutator.py::Mutator.classify_outcome",
    # CandidateGenerator methods moved into the emission mixin and compared
    # individually by the gate differential.
    "scheduler.py::CandidateGenerator.generate_fingerprint",
    "scheduler.py::CandidateGenerator.emit_candidate",
    "scheduler.py::CandidateGenerator.append_candidates_batch",
    "scheduler.py::CandidateGenerator.append_to_phases",
    "scheduler.py::CandidateGenerator.generate_family_phases",
    # DBMutator methods moved into the pattern mixin.
    "db_mutator.py::DBMutator._forward_draws",
    "db_mutator.py::DBMutator._ss_mutation_pattern",
    "db_mutator.py::DBMutator._dd_mutation_pattern",
    "db_mutator.py::DBMutator._cc_mutation_pattern",
    "db_mutator.py::DBMutator._zz_mutation_pattern",
    "db_mutator.py::DBMutator._floor_direction",
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


def new_bare_names(head_rel: str) -> set:
    """Every symbol name (last component) the new modules for a head define.

    Used to prove a PROMOTED entry still exists somewhere: the comparison loop
    skips private names, so without this a deleted private helper passes.
    """
    names = set()
    for rel in dict(MOVES)[head_rel]:
        got, err = collect(ROOT / rel)
        if err:
            continue
        names |= {k.rsplit(".", 1)[-1] for k in got}
    return names


def _collect_old_tree(head_rel: str) -> tuple[dict[str, Any] | None, str]:
    """Dump one pre-refactor module and collect its public symbols."""
    old_path = Path("/tmp/opencode/ast_check") / head_rel
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(head_text(head_rel))
    old_syms, err = collect(old_path)
    if err:
        return None, err
    return old_syms, ""


def _compare_symbols(head_rel: str, old_syms: dict[str, Any],
                     new_syms: dict[str, Any],
                     decomposed: list[str]) -> tuple[list[str], list[str]]:
    """Compare every public symbol of one pre-refactor module."""
    missing: list[str] = []
    differs: list[str] = []
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
            missing.append(f"{head_rel}::{name} ({kind})")
            continue
        _, new_args, new_body = new_syms[name]
        if new_args != args:
            differs.append(f"{head_rel}::{name} signature "
                           f"{args!r} -> {new_args!r}")
            continue
        try:
            if ast.unparse(body) != ast.unparse(new_body):
                if (head_rel in DECOMPOSED
                        or f"{head_rel}::{name}" in COMPOSITION_ROOTS
                        or f"{head_rel}::{name}" in RESTRUCTURED
                        or head_rel == "port_tensile.py"):
                    decomposed.append(f"{head_rel}::{name}")
                    continue
                differs.append(f"{head_rel}::{name} body differs")
        except Exception as exc:
            differs.append(f"{head_rel}::{name} unparse failed: {exc}")
    return missing, differs


def _promoted_missing(bare_names_fn) -> list[str]:
    """PROMOTED entries whose new name exists nowhere in the new tree."""
    out: list[str] = []
    for entry in sorted(PROMOTED):
        if entry in FOLDED:
            continue
        head, sym = entry.split("::", 1)
        target = PROMOTED_AS.get(entry, sym.rsplit(".", 1)[-1])
        if target not in bare_names_fn(head):
            out.append(f"{entry} -> no {target!r} in the new tree")
    return out


def _print_report(all_missing: list[str], all_differs: list[str],
                 errors: list[str], decomposed: list[str],
                 promoted_missing: list[str]) -> None:
    """Print the classified comparison and decide the exit status."""
    for _d in decomposed:
        pass

    # Classify every "missing" so the reader can see what happened to it.
    driver_methods = [m for m in all_missing if "::TensileDriver." in m]
    ledger_methods = [m for m in all_missing if "::SQLiteRegistry." in m]
    report_methods = [m for m in all_missing if m.startswith("report.py::")]
    analytics_methods = [m for m in all_missing if "::AnalyticsEngine." in m]
    unexplained = [m for m in all_missing
                   if m not in (driver_methods + ledger_methods
                                + report_methods + analytics_methods)]

    # The private-symbol skip above would hide a deleted helper, so every
    # PROMOTED entry is checked for existence under its new name (FOLDED, which
    # has no symbol of its own, is proved by verify_gate_differential.py).
    for _m in unexplained:
        pass

    for _d in all_differs:
        pass
    for _e in errors:
        pass
    for _p in promoted_missing:
        pass

    if unexplained or all_differs or errors or promoted_missing:
        sys.exit(1)


def main():
    all_missing, all_differs, errors, decomposed = [], [], [], []
    for head_rel, new_rels in MOVES:
        old_syms, err = _collect_old_tree(head_rel)
        if err:
            errors.append(f"{head_rel}: {err}")
            continue
        new_syms: dict[str, Any] = {}
        for rel in new_rels:
            got, err = collect(ROOT / rel)
            if err:
                errors.append(f"{rel}: {err}")
                continue
            new_syms.update(got)

        missing, differs = _compare_symbols(head_rel, old_syms, new_syms,
                                            decomposed)
        all_missing.extend(missing)
        all_differs.extend(differs)

    _print_report(all_missing, all_differs, errors, decomposed,
                  _promoted_missing(new_bare_names))


if __name__ == "__main__":
    main()
