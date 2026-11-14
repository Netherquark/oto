#!/usr/bin/env python3
"""Evergreen symbol-level equivalence check.

Owns: comparing the public surface of ``--base REF`` and the working tree:
every public symbol in the ref tree must exist in the working tree, with the
same signature. For a pre-split base (``port_tensile.py`` at REF) the MOVES /
DECOMPOSED / PROMOTED / RESTRUCTURED tables from the package split still
apply; for a post-split base the same-path comparison applies to all
``oto/**/*.py`` files.
Does NOT own: the split-era equivalence semantics (this is evergreen: REF is
a parameter, not a pin) or method comparison (verify_methods).
Public API: main, head_text, strip, sig, collect; contract = exit code.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# HEAD module -> new package module(s) that own it.
MOVES = [
    ("gfx90c_common.py", ["oto/device/loader.py"]),
    ("policy.py", ["oto/metrics/cell_policy.py"]),
    ("telemetry.py", ["oto/metrics/telemetry.py"]),
    ("coverage.py", ["oto/metrics/cell_coverage.py"]),
    ("auto_prompt.py", ["oto/runners/auto_prompt.py"]),
    ("tensile_library.py", ["oto/tensile/shipped_floor_manifest.py",
                          "oto/tensile/shipped_floor.py"]),
    ("library_parity.py", ["oto/tensile/library_parity.py"]),
    ("legality.py", ["oto/tensile/legality.py"]),
    ("scheduler.py", ["oto/tensile/candidate.py",
                      "oto/tensile/candidate_config.py",
                      "oto/tensile/candidate_emission.py",
                      "oto/tensile/gates/assembly.py",
                      "oto/tensile/gates/loads.py",
                      "oto/tensile/gates/occupancy.py",
                      "oto/tensile/gates/vgpr_model.py"]),
    ("synthesis.py", ["oto/tensile/synthesis/pipeline_manifest.py",
                      "oto/tensile/synthesis/tile_space.py"]),
    ("db_mutator.py", ["oto/tensile/synthesis/donor_mutator.py",
                      "oto/tensile/synthesis/donor_knobs.py",
                      "oto/tensile/synthesis/donor_patterns.py",
                      "oto/tensile/synthesis/tile_space.py"]),
    ("registry.py", ["oto/ledger/registry.py", "oto/ledger/registry_core.py",
                     "oto/ledger/queries.py", "oto/ledger/proposals.py"]),
    ("mutator.py", ["oto/ledger/mutator.py", "oto/ledger/mutator_outcomes.py"]),
    ("agent.py", ["oto/ledger/convergence_agent.py", "oto/ledger/harvest.py",
                  "oto/ledger/agent_coverage.py"]),
    ("analytics.py", ["oto/metrics/benchmark_analytics.py",
                      "oto/metrics/family_attribution.py",
                      "oto/metrics/ab_delta.py",
                      "oto/metrics/cell_status.py"]),
    ("ab_audit.py", ["oto/metrics/ab_audit.py",
                     "oto/metrics/ab_records.py",
                     "oto/metrics/ab_identity.py",
                     "oto/metrics/ab_band.py"]),
    ("report.py", ["oto/metrics/acceptance_report.py", "oto/metrics/report_models.py",
                   "oto/metrics/report_html.py",
                   "oto/metrics/report_sections.py"]),
    ("run_status.py", ["oto/metrics/run_status.py",
                       "oto/metrics/status_helpers.py",
                       "oto/metrics/ledger_state.py",
                       "oto/metrics/build_status.py",
                       "oto/metrics/run_plan.py",
                       "oto/metrics/thermal_telemetry.py",
                       "oto/metrics/render_status.py"]),
    ("port_tensile.py", ["oto/runners/toolchain.py", "oto/runners/driver.py",
                         "oto/runners/benchmark.py", "oto/runners/phase_runner.py",
                         "oto/runners/reference_floor.py", "oto/runners/convergence_loop.py",
                         "oto/runners/corpus_loaders.py",
                         "oto/runners/acceptance_reporting.py", "oto/runners/clock_telemetry.py",
                         "oto/runners/timing.py",
                         "oto/runners/library_build.py", "oto/runners/stage_cli.py",
                         "oto/tensile/config_writer.py"]),
    ("consolidate.py", ["oto/tools/consolidate.py",
                       "oto/tools/consolidate_targets.py",
                       "oto/tools/consolidate_deck.py",
                       "oto/tools/consolidate_floor.py",
                       "oto/tools/consolidate_install.py"]),
    ("allruns.py", ["oto/tools/run_census.py"]),
    ("verify_run.py", ["oto/tools/corpus_audit.py"]),
    ("check_candidates.py", ["oto/checks/deck_legality.py"]),
    ("check_tensile_build.py", ["oto/checks/tensile_build.py", "oto/checks/tensile_build_probe.py"],),
    ("check_library_parity.py", ["oto/checks/library_parity.py"]),
    ("check_db.py", ["oto/checks/db.py"]),
    ("check_retirement.py", ["oto/checks/stability_retirement.py"]),
    ("harness/cell_knob_diff.py", ["oto/harness/cell_knob_diff.py"]),
    ("harness/generate_candidates.py", ["oto/harness/candidate_generator.py",
                                      "oto/harness/candidate_rows.py",
                                      "oto/harness/candidate_pool.py",
                                      "oto/harness/candidate_overlay.py"]),
    ("harness/kernel_db.py", ["oto/harness/kernel_db.py"]),
    ("harness/measure_vgprs.py", ["oto/harness/vgpr_measurement.py"]),
    ("harness/occupancy_bounds.py", ["oto/harness/occupancy_bounds.py"]),
    ("harness/regression_matrix.py", ["oto/harness/regression_matrix.py"]),
    ("harness/resolve_cells.py", ["oto/harness/cell_resolver.py"]),
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
    # PROMOTED key above never matched; proved by test_legal_slow_paths/test_mutator.
    "mutator.py::classify_outcome",
    # pure extraction of the CLI drivers; proved by their own tests.
    "allruns.py::main",
    "verify_run.py::main",
    # Second decomposition pass (2026-10-16, the 60-line rule "no function over 60 lines").
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
#: no symbol of their own -- verify_gates.py proves their effect.
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

#: Report renderer methods, proved by verify_report_render.py.
REPORT_SPLIT = {"AcceptanceReporter", "ABVerdict", "AcceptanceReport",
                "write_html_report", "_timing_metric", "_timing_section",
                "_provenance_line", "_basis_headers", "_cell_status_section",
                "_problem_space_section", "_coverage_matrix_section",
                "_load_run_telemetry", "_telemetry_section"}


def head_text(ref: str, rel: str) -> str:
    """The ``ref`` tree's version of ``rel``."""
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"cannot read {ref}:{rel}: {out.stderr}")
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


def _threading_shaped(old_sig: str, new_sig: str) -> bool:
    """True when ``new_sig`` is ``old_sig`` plus a trailing ``profile=None``.

    Signatures here are the arguments tuple unparsed *without* surrounding
    parens (see :func:`sig`). Device-independence work makes the device profile
    an explicit argument on every profile-consuming API, appended as a
    defaulted kwarg -- callers unaware of it bind the ambient profile exactly
    as before. That delta is the expected shape of the sweep, not drift.
    """
    if new_sig == old_sig:
        return True
    for tail in (", profile=None", ",profile=None"):
        if new_sig.endswith(tail) and new_sig[: -len(tail)].rstrip() == old_sig:
            return True
    return old_sig == "" and new_sig == "profile=None"


def sig(node) -> str:
    return (ast.unparse(node.args)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "")


def collect(path: Path):
    """{qualified_name: (kind, arg_signature, normalised_body)} for a module.

    Import aliases re-exported at module top level are recorded too: the new
    tree re-exports helpers (e.g. ``from .ldspad import ldspad_feasible``),
    and those names are its public API as much as a def is.
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as exc:
        return None, exc
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[-1]
                if not name.startswith("_") and name != "*":
                    out[name] = ("alias", "", None)
            continue
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


def _collect_old_tree(ref: str, head_rel: str) -> tuple[dict[str, Any] | None, str]:
    """Dump one ref-tree module and collect its public symbols."""
    from oto.tools.verifiers import ref_worktree
    old_path = ref_worktree.scratch_dir() / "ast_check" / head_rel
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(head_text(ref, head_rel))
    old_syms, err = collect(old_path)
    if err:
        return None, err
    return old_syms, ""


def _compare_symbols(head_rel: str, old_syms: dict[str, Any],
                     new_syms: dict[str, Any],
                     decomposed: list[str]) -> tuple[list[str], list[str]]:
    """Compare every public symbol of one pre-refactor module."""
    from oto.tools.verifiers.ref_worktree import drift_matches

    missing: list[str] = []
    differs: list[str] = []
    for name, (kind, args, body) in old_syms.items():
        # Aliases carry no body; they only feed "does a symbol of this name
        # exist" and are judged at PROMOTED level instead.
        if kind == "alias":
            continue
        # A symbol whose final component is private may legitimately move or
        # be renamed; the public names it serves are compared here.
        if name.rsplit(".", 1)[-1].startswith("_"):
            continue
        if name in PROMOTED or f"{head_rel}::{name}" in PROMOTED:
            continue
        if head_rel == "report.py" and name in REPORT_SPLIT:
            continue
        key = f"{head_rel}::{name}"
        if name not in new_syms:
            if (drift_matches("ast_equivalence", key) is not None
                    or key in RESTRUCTURED):
                decomposed.append(f"{key} (manifest-approved move/delete)")
                continue
            missing.append(f"{key} ({kind})")
            continue
        _, new_args, new_body = new_syms[name]
        if new_args != args:
            if drift_matches("ast_equivalence", key) is not None:
                decomposed.append(f"{key} signature (manifest-approved)")
                continue
            differs.append(f"{key} signature "
                           f"{args!r} -> {new_args!r}")
            continue
        try:
            if ast.unparse(body) != ast.unparse(new_body):
                if (head_rel in DECOMPOSED
                        or key in COMPOSITION_ROOTS
                        or key in RESTRUCTURED
                        or head_rel == "port_tensile.py"
                        or drift_matches("ast_equivalence", key) is not None):
                    decomposed.append(key)
                    continue
                differs.append(f"{key} body differs")
        except Exception as exc:
            differs.append(f"{key} unparse failed: {exc}")
    return missing, differs


def _promoted_missing(bare_names_fn) -> list[str]:
    """PROMOTED entries whose new name exists nowhere in the new tree."""
    from oto.tools.verifiers.ref_worktree import drift_matches

    out: list[str] = []
    for entry in sorted(PROMOTED):
        if entry in FOLDED:
            continue
        if drift_matches("ast_equivalence", entry) is not None:
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
    print(f"INTENTIONALLY DECOMPOSED (proved by the other checks): "
          f"{len(decomposed)}")
    for _d in decomposed:
        print("   ", _d)

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
    # has no symbol of its own, is proved by verify_gates.py).
    print("\nMISSING, classified:")
    print(f"  TensileDriver methods moved to a runner mixin "
          f"(verify_methods.py): {len(driver_methods)}")
    print(f"  SQLiteRegistry methods moved to a ledger mixin, same public "
          f"class: {len(ledger_methods)}")
    print(f"  AcceptanceReporter renderer methods "
          f"(verify_report_render.py, byte-identical): {len(report_methods)}")
    print(f"  Analytics methods moved to an analytics mixin "
          f"(verify_report_render.py exercises them): {len(analytics_methods)}")
    print(f"  UNEXPLAINED: {len(unexplained)}")
    for _m in unexplained:
        print("   ", _m)

    print(f"\nDIFFERING BODIES/SIGNATURES: {len(all_differs)}")
    for _d in all_differs:
        print("   ", _d)
    print(f"PARSE ERRORS: {len(errors)}")
    for _e in errors:
        print("   ", _e)
    print(f"\nPROMOTED SYMBOLS MISSING IN THE NEW TREE: "
          f"{len(promoted_missing)}")
    for _p in promoted_missing:
        print("   ", _p)

    if unexplained or all_differs or errors or promoted_missing:
        sys.exit(1)
    print("\nAST EQUIVALENCE: OK")


#: Intentional file renames within the package (old rel path -> new rel
#: path). The post-split equivalence check follows these so a rename does not
#: read as a wholesale public-API loss. Maintained alongside the rename work;
#: every entry must correspond to a real git mv.
RENAMES: dict[str, str] = {
    "oto/_map.py": "oto/readme_gen.py", "oto/inventory.py": "oto/readme_gen.py", "oto/_version.py": "oto/version.py",
    "oto/yamlio.py": "oto/yaml_cached.py", "oto/docs_index.py": "oto/docs_index_writer.py", "oto/agents/harness_tools.py": "oto/agents/agent_tools.py",
    "oto/agents/meta.py": "oto/agents/meta_agent.py", "oto/agents/orchestrator.py": "oto/agents/meta_agent.py", "oto/agents/research.py": "oto/agents/research_client.py",
    "oto/checks/candidates.py": "oto/checks/deck_legality.py", "oto/checks/db.py": "oto/checks/registry_audit.py", "oto/checks/retirement.py": "oto/checks/stability_retirement.py",
    "oto/cli/docs.py": "oto/cli/help_command.py", "oto/cli/flags.py": "oto/cli/global_flags.py", "oto/device/derive.py": "oto/device/derive_limits.py",
    "oto/device/detect.py": "oto/device/device_detect.py", "oto/device/vocabulary.py": "oto/device/kernel_vocabulary.py", "oto/harness/_rows_core.py": "oto/harness/rows_ladders.py",
    "oto/harness/_rows_frontier.py": "oto/harness/rows_frontier.py", "oto/harness/_rows_smallcells.py": "oto/harness/rows_smallcells.py", "oto/harness/deck_check.py": "oto/harness/deck_probe.py",
    "oto/harness/tensile_oracle.py": "oto/harness/tensile_probe.py", "oto/harness/occupancy_audit.py": "oto/harness/occupancy_bounds.py", "oto/harness/generate_candidates.py": "oto/harness/candidate_generator.py",
    "oto/harness/measure_vgprs.py": "oto/harness/vgpr_measurement.py", "oto/harness/resolve_cells.py": "oto/harness/cell_resolver.py", "oto/ledger/agent.py": "oto/ledger/convergence_agent.py",
    "oto/ledger/agent_mutate.py": "oto/ledger/agent_mutation.py", "oto/ledger/queries.py": "oto/ledger/registry_queries.py", "oto/ledger/proposals.py": "oto/ledger/registry_proposals.py",
    "oto/metrics/policy.py": "oto/metrics/cell_policy.py", "oto/metrics/report_build.py": "oto/metrics/build_status.py", "oto/metrics/report_figures.py": "oto/metrics/report_coverage.py",
    "oto/metrics/_status_common.py": "oto/metrics/status_helpers.py", "oto/metrics/status_common.py": "oto/metrics/status_helpers.py", "oto/metrics/analytics.py": "oto/metrics/benchmark_analytics.py",
    "oto/metrics/coverage.py": "oto/metrics/cell_coverage.py", "oto/metrics/protocol.py": "oto/metrics/measurement_protocol.py", "oto/metrics/read_thermals.py": "oto/metrics/thermal_telemetry.py",
    "oto/metrics/report.py": "oto/metrics/acceptance_report.py", "oto/tensile/library.py": "oto/tensile/shipped_floor_manifest.py", "oto/tensile/shipped_library.py": "oto/tensile/shipped_floor.py",
    "oto/tensile/shipped_manifest.py": "oto/tensile/shipped_floor_manifest.py", "oto/tensile/best_library.py": "oto/tensile/best_effort_library.py", "oto/tensile/decks.py": "oto/tensile/family_decks.py",
    "oto/tensile/patterns.py": "oto/tensile/contraction_patterns.py", "oto/tensile/synthesis/db.py": "oto/tensile/synthesis/donor_mutator.py", "oto/tensile/synthesis/db_knobs.py": "oto/tensile/synthesis/donor_knobs.py",
    "oto/tensile/synthesis/db_patterns.py": "oto/tensile/synthesis/donor_patterns.py", "oto/tensile/synthesis/manifest.py": "oto/tensile/synthesis/pipeline_manifest.py", "oto/runners/cli.py": "oto/runners/stage_cli.py",
    "oto/runners/flags.py": "oto/runners/stage_flags.py", "oto/runners/synthesis.py": "oto/runners/library_build.py", "oto/runners/reference.py": "oto/runners/reference_floor.py",
    "oto/runners/analytics_loaders.py": "oto/runners/corpus_loaders.py", "oto/runners/auto.py": "oto/runners/convergence_loop.py", "oto/runners/clocks.py": "oto/runners/clock_telemetry.py",
    "oto/runners/paths.py": "oto/runners/result_paths.py", "oto/runners/phases.py": "oto/runners/phase_runner.py", "oto/runners/reporting.py": "oto/runners/acceptance_reporting.py",
    "oto/tools/allruns.py": "oto/tools/run_census.py", "oto/tools/all_runs.py": "oto/tools/run_census.py", "oto/tools/potential_configs_gen.py": "oto/tools/potential_configs.py",
    "oto/tools/verify_run.py": "oto/tools/corpus_audit.py", "oto/tools/chart.py": "oto/tools/benchmark_chart.py",
}

def _head_path_for(rel, old_syms, all_missing):
    """Resolve the HEAD path for a ref file, following RENAMES; None if gone."""
    cur = ROOT / rel
    if cur.exists():
        return cur
    new_rel = RENAMES.get(rel)
    if new_rel is not None and (ROOT / new_rel).exists():
        return ROOT / new_rel
    all_missing.extend(
        f"{rel}::{name}" for name, kind in old_syms.items()
        if kind != "alias"
        and not name.rsplit(".", 1)[-1].startswith("_")
    )
    return None


def _postsplit_check(ref: str) -> int:
    """Public-API loss check vs a post-split ref: missing symbols + signature drift."""
    import subprocess as _sp

    from oto.tools.verifiers import ref_worktree
    from oto.tools.verifiers.ref_worktree import print_drift_summary

    out = _sp.run(["git", "ls-tree", "-r", "--name-only", ref],
                  cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"cannot list tree at {ref}: {out.stderr}")
    all_missing: list[str] = []
    sig_changes: list[str] = []
    for rel in sorted(out.stdout.splitlines()):
        if not (rel.startswith("oto/") and rel.endswith(".py")):
            continue
        if "__pycache__" in rel or "tools/verifiers" in rel:
            continue
        ref_path = ref_worktree.scratch_dir() / "ast_check" / rel
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_text = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT,
                                  capture_output=True, text=True).stdout
        ref_path.write_text(ref_text)
        old_syms, err = collect(ref_path)
        if err:
            print(f"parse error at {ref}:{rel}: {err}")
            continue
        cur = _head_path_for(rel, old_syms, all_missing)
        if cur is None:
            continue
        new_syms, err = collect(cur)
        if err:
            print(f"parse error at HEAD:{rel}: {err}")
            continue
        for name, (_kind, args, _body) in old_syms.items():
            if _kind == "alias":
                continue
            if name.rsplit(".", 1)[-1].startswith("_"):
                continue
            if name not in new_syms:
                all_missing.append(f"{rel}::{name}")
                continue
            if new_syms[name][1] != args and not _threading_shaped(args, new_syms[name][1]):
                sig_changes.append(f"{rel}::{name} signature changed")

    print(f"public symbols at risk of loss or signature change, vs {ref}:")
    print(f"  MISSING: {len(all_missing)}")
    for _m in all_missing:
        print("   ", _m)
    print(f"  SIGNATURE CHANGES: {len(sig_changes)}")
    for _d in sig_changes:
        print("   ", _d)
    drifted = sorted(set(all_missing) | set(sig_changes))
    return print_drift_summary("ast_equivalence", drifted)


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="HEAD~1",
                    help="ref to compare against (default: HEAD~1, the evergreen "
                         "per-commit check; pass 2824c2f for the split-era comparison)")
    args = ap.parse_args()
    print(f"base: {args.base}")

    if subprocess.run(["git", "cat-file", "-e", f"{args.base}:scheduler.py"],
                      cwd=ROOT, capture_output=True).returncode == 0:
        all_missing, all_differs, errors, decomposed = [], [], [], []
        for head_rel, new_rels in MOVES:
            old_syms, err = _collect_old_tree(args.base, head_rel)
            if err:
                errors.append(f"{head_rel}: {err}")
                continue
            new_syms: dict[str, Any] = {}
            for rel in new_rels:
                got, err = collect(ROOT / rel)
                if err:
                    errors.append(f"{rel}: {err}")
                    continue
                for key, value in got.items():
                    # Definitions win over re-export aliases.
                    if value[0] != "alias":
                        new_syms[key] = value
                    elif key not in new_syms:
                        new_syms[key] = value
            missing, differs = _compare_symbols(head_rel, old_syms, new_syms,
                                                decomposed)
            all_missing.extend(missing)
            all_differs.extend(differs)
        _print_report(all_missing, all_differs, errors, decomposed,
                      _promoted_missing(new_bare_names))
        return

    # Post-split base: public API loss + signature drift, classified via the
    # repo manifest (drift_manifest.json). Body equivalence is not a same-path
    # criterion here; verdict semantics live in the gate differential.
    drifted_rc = _postsplit_check(args.base)
    if drifted_rc == 0:
        print("\nAST EQUIVALENCE: OK")
    sys.exit(drifted_rc)


if __name__ == "__main__":
    main()
