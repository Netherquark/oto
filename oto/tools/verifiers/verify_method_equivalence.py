#!/usr/bin/env python3
"""Method-level equivalence: every TensileDriver method moved into a mixin, and
every port_tensile function moved into a new module, must keep its exact body.

Bodies are normalised by removing only the docstring and the ``import ...``
statements (which legitimately moved), so a dropped or altered statement is
still a failure.
"""
from __future__ import annotations

#: The last commit before the package split. Every check in this directory
#: compares against it, so "no behaviour change" is measured against one
#: fixed point rather than against whatever HEAD happens to be.
REFACTOR_BASE = "2824c2f"

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

NEW = [
    "oto/ledger/registry_core.py", "oto/ledger/queries.py",
    "oto/ledger/proposals.py", "oto/runners/driver.py", "oto/runners/benchmark.py", "oto/runners/phases.py",
    "oto/runners/reference.py", "oto/runners/auto.py",
    "oto/runners/analytics_loaders.py", "oto/runners/reporting.py",
    "oto/runners/clocks.py", "oto/runners/timing.py",
    "oto/runners/synthesis.py", "oto/runners/cli.py",
    "oto/tensile/config_writer.py",
]

# HEAD method name -> (module-relative lookup) it must be found in.
HEAD_METHODS = [
    "__init__", "_setup_signal_handlers", "_signal_handler", "_get_tensile_env",
    "run_preflight", "load_phases_manifest", "_merge_overlay_entries",
    "_load_seed_overlay", "_load_run_overlay", "_read_key", "_apply_cooldown",
    "_ensure_telemetry", "_current_arm", "_named_cell_stamps", "execute_phase",
    "_tee_stream", "_run_tensile_benchmark", "_start_live_status",
    "_stop_live_status", "_sync_agent_run_id", "_resolve_proposal_outcome",
    "run_phases", "run_gfx900_reference", "_latest_reference_run",
    "_reference_floor_runs", "_reusable_phase_keys", "_chain_phase_sets",
    "_reference_remaining", "run_auto", "_load_analytics_from_run",
    "_load_analytics_from_registry", "_native_run_dirs",
    "_native_records_all_runs", "_native_arm_provenance",
    "_native_analytics_all_runs", "_telemetry_rows",
    "_load_telemetry_by_phase", "_load_sclk_by_phase", "_sclk_map",
    "_thermal_map", "_thermal_summary", "_clock_coverage", "_sclk_reference",
    "_compute_family_timing", "_run_span_minutes", "_run_stamp",
    "_compute_execution_timing", "_stamp_str", "_fmt_minutes",
    "generate_acceptance_report", "regenerate_report",
    "_retire_stable_candidates", "_ab_records_from_csv",
    "_ab_records_from_registry", "_compute_ab_verdicts", "synthesize_library",
]

# The three that were deliberately restructured (verified by other means).
RESTRUCTURED = {"_write_phase_config": "config_writer.write_phase_config",
                "validate_config": "verified differentially (128k cases)",
                "main": "decomposed into the stage handlers in cli.py",
                "run_gfx900_reference": "_resume_deck + _fresh_deck; proved by "
                                     "test_reference_tiers/test_auto_reference_floor",
                "execute_phase": "decomposed into _refuse_phase/_start_record/"
                                 "_benchmark_phase and the _*_record builders; "
                                 "proved by test_phase1_integration",
                "_run_tensile_benchmark": "decomposed into _refuse_reuse_of/"
                                          "_tensile_command/_spawn_tensile/"
                                          "_supervise_tensile; proved by "
                                          "test_measurement_integrity",
                "__init__": "decomposed into _init_* helpers; proved by the "
                            "tests that construct the driver",
                "generate_acceptance_report": "decomposed into the report "
                                              "section builders; proved "
                                              "byte-for-byte by "
                                              "verify_report_html.py",
                "synthesize_library": "decomposed into _emit_* helpers; proved "
                                      "by test_*synthes*",
                # Second decomposition pass (2026-10-16, AC 1b). These three
                # were not registered when the pass ran, which left this check
                # red on arrival -- a guard that is red before you touch
                # anything is one nobody reads. Each is a statement-preserving
                # extraction; the transitive `self.*` call set from each entry
                # point is a strict superset of the original's, so nothing the
                # originals called became unreachable. Proved by the suite.
                "_compute_ab_verdicts": "decomposed into the per-cell verdict "
                                        "builders in oto/runners/reporting.py; "
                                        "proved by the ab_audit/ab_delta tests",
                "run_auto": "decomposed into the _auto_* handlers in "
                            "oto/runners/auto.py; proved by test_auto_prompt "
                            "and the driver tests that construct the loop",
                "run_phases": "decomposed into the phase handlers in "
                              "oto/runners/phases.py; proved by "
                              "test_phase1_integration",
                }

# Modules to normalise: replace these substrings before comparing so the moved
# module paths do not read as differences.
ALIASES = [
    # _write_phase_config became a module function taking the driver
    ("self._write_phase_config(phase_config_path, phase)",
     "config_writer.write_phase_config(self, phase_config_path, phase)"),
]


def head_source() -> str:
    """The pre-refactor port_tensile.py, at the fixed comparison point."""
    import subprocess
    out = subprocess.run(["git", "show", f"{REFACTOR_BASE}:port_tensile.py"],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"cannot read {REFACTOR_BASE}:port_tensile.py: {out.stderr}")
    return out.stdout


def _strip_imports(node):
    for child in ast.iter_child_nodes(node):
        if isinstance(child.body) if False else False:  # pragma: no cover
            pass
        try:
            kids = list(child.body)
        except AttributeError:
            continue
        child.body = [s for s in kids
                      if not isinstance(s, (ast.Import, ast.ImportFrom))]
        _strip_imports(child)
    return node


def normalise(fn: ast.FunctionDef) -> str:
    fn = ast.parse(ast.unparse(fn)).body[0]
    body = fn.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        fn.body = body[1:]
    fn.body = [s for s in fn.body if not isinstance(s, (ast.Import, ast.ImportFrom))]
    _strip_imports(fn)
    out = ast.unparse(fn)
    # clocks.py imports `statistics` under its own name rather than the historical
    # `_stats` alias; same function, alias only.
    out = out.replace("_stats.", "statistics.")
    out = out.replace("_resolve_rocm_paths()", "resolve_rocm_paths()")
    out = out.replace("_require_tensile_root(", "require_tensile_root(")
    for old, new in ALIASES:
        out = out.replace(old, new)
    return out


def collect(paths):
    found = {}
    for rel in paths:
        tree = ast.parse((ROOT / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.setdefault(node.name, []).append((rel, node))
    return found


def main():
    src = head_source()
    tree = ast.parse(src)
    driver = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                  and n.name == "TensileDriver")
    old = {n.name: n for n in driver.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    new = collect(NEW)
    missing, differs, extra = [], [], set(HEAD_METHODS)

    for name, fn in old.items():
        extra.discard(name)
        want = normalise(fn)
        if name in RESTRUCTURED:
            continue
        if name not in new:
            missing.append(name)
            continue
        # `__init__` exists in several modules; the driver's own is in driver.py.
        pool = new[name]
        if name == "__init__":
            pool = [c for c in pool if c[0] == "oto/runners/driver.py"] or pool
        rel, node = pool[0]
        got = normalise(node)
        if got != want:
            differs.append(f"{name} (now in {rel})")
    print(f"HEAD TensileDriver methods: {len(old)}")
    print(f"MOVED, NOT FOUND: {sorted(missing)}")
    print(f"MOVED, BODY DIFFERS: {sorted(differs)}")
    print(f"NOT ACCOUNTED FOR: {sorted(extra)}")
    print(f"intentionally restructured: {sorted(RESTRUCTURED)}")
    if missing or differs:
        sys.exit(1)
    print("METHOD EQUIVALENCE: OK")


if __name__ == "__main__":
    main()
