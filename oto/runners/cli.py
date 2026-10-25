#!/usr/bin/env python3
"""The argparse stage dispatch: the ``port_tensile.py`` command line.

Owns: ``main`` -- every ``--flag`` the driver accepts and the stage that each one
selects. Each stage is a named function here so the CLI is a routing table, not a
400-line if-chain, and so a flag's effect can be read in one place.
Does NOT own: any stage's behaviour (each belongs to the mixin that implements
it), the plan the ``--auto`` questions produce (oto.runners.auto_prompt), or the
driver wiring (driver.py).
Public API: main.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from typing import Any, Dict, List, Optional

from oto.metrics.analytics import CellAnalytics
from oto.runners import flags
from oto.runners.driver import TensileDriver

#: Stage names/numbers that only read the registry or prior runs and must
#: therefore NOT mint a new run directory. A stage that mints a run for a
#: read-only query pollutes the ledger with an empty run and shifts
#: ``latest_run_id`` away from the run the operator meant.
READ_ONLY_STAGES = {"2", "candidate", "4", "retirement", "5", "analytics",
                    "7", "report", "library", "best-library"}
#: Stages that only validate. An invocation that stops after one of these needs
#: no run directory; creating one would leave a phantom 'started' run behind.
PREFLIGHT_STAGES = {"1", "preflight", "manifest"}

#: Families, longest-first, so ``HH_HPA`` is not matched by the ``HH`` prefix test.
_FAMILY_TOKENS = ("HH_HPA", "HS_HPA", "SS", "DD", "HH", "CC", "ZZ")


def build_parser() -> argparse.ArgumentParser:
    """Build the driver's argument parser; see oto.runners.flags."""
    return flags.build_parser()


# ------------------------------------------------------------- stage handlers

def _ends_after_preflight(args, stage: set) -> bool:
    """True when Stage 1 is the last thing this invocation will do."""
    return (bool(args.preflight or stage & PREFLIGHT_STAGES)
            and not (stage - PREFLIGHT_STAGES))


def _stage_preflight(driver, args, stage) -> Optional[int]:
    """Stage 1: Phase-0 preflight. Returns an exit code, or None to continue.

    ``--preflight`` alone stops here; as a gate for a later stage it returns None
    so the rest of the table still runs.
    """
    if not (args.preflight or stage & PREFLIGHT_STAGES):
        return None
    ok = driver.run_preflight()
    if not ok:
        return 1
    return 0 if _ends_after_preflight(args, stage) else None


def _stage_report(driver, args, stage) -> Optional[int]:
    """Stage 7: regenerate the acceptance report from prior runs."""
    if args.report is None and "7" not in stage and "report" not in stage:
        return None
    result = driver.regenerate_report(args.report if args.report else None,
                                     native_agg=args.native_agg,
                                     protocol_basis=args.protocol_basis)
    return 0 if result else 1


def _stage_best_library(driver, args, stage) -> Optional[int]:
    """Build a best-effort gfx90c TensileLibrary.dat from the full db."""
    if (args.best_library is None and "library" not in stage
            and "best-library" not in stage and "best_library" not in stage):
        return None
    dest = args.best_library if args.best_library else None
    # Default to the across-all-runs view ("any") unless the caller explicitly
    # chose a protocol basis on the command line.
    if "--protocol-basis" in sys.argv or "--protocol_basis" in sys.argv:
        basis = args.protocol_basis
    else:
        basis = "any"
    result = driver.synthesize_best_library(dest, protocol_basis=basis)
    print(f"Best-effort library result: {result}")
    return 0 if result.get("status") != "failed" else 1


def _stage_synthesis(driver, args, stage) -> Optional[int]:
    """Stage 6: emit the family logic files and build the library."""
    if not (args.synthesize or "6" in stage or "synthesis" in stage
            or "build" in stage):
        return None
    result = driver.synthesize_library()
    print(f"Stage 6 Synthesis complete: {result}")
    return 0 if result.get("status") != "failed" else 1


def _stage_candidate_plan(driver, args, stage) -> Optional[int]:
    """Stage 2: manifest summary only -- no execution, no run minted."""
    if not ("2" in stage or "candidate" in stage):
        return None
    phases = driver.load_phases_manifest()
    fam_counts: Dict[str, int] = {}
    for p in phases:
        lbl = str(p.get("label", ""))
        fam = "?"
        for f in _FAMILY_TOKENS:
            if f in lbl:
                fam = f
                break
        fam_counts[fam] = fam_counts.get(fam, 0) + 1
    print(f"Candidate plan: {len(phases)} phases in phases.yaml")
    for fam, n in sorted(fam_counts.items()):
        print(f"  {fam}: {n}")
    return 0


def _stage_retirement(driver, args, stage) -> Optional[int]:
    """Stage 4: retirement sweep for stable cells (registry-only)."""
    if not ("4" in stage or "retirement" in stage):
        return None
    driver._retire_stable_candidates()
    return 0


def _stage_analytics(driver, args, stage) -> Optional[int]:
    """Stage 5: per-dtype analytics summary for the latest run (registry-only)."""
    if not ("5" in stage or "analytics" in stage):
        return None
    run_dir = driver.run_dir
    if run_dir is None:
        latest = driver.registry.latest_run_id()
        if latest:
            run_dir = driver.base_dir / "gfx90c_runs" / latest
    analytics = driver._load_analytics_from_run(
        run_dir if run_dir is not None and run_dir.exists() else None)
    if not analytics:
        print("No analytics records available for the latest run.")
        return 1
    by_dtype: Dict[str, List[CellAnalytics]] = {}
    for a in analytics:
        by_dtype.setdefault(a.dtype, []).append(a)
    for dt, lst in sorted(by_dtype.items()):
        med = [a.median_gflops for a in lst]
        below = sum(1 for a in lst if a.is_below_ceiling)
        print(f"[{dt}] cells={len(lst)} best={max(med):.1f} GFLOPS "
               f"median={statistics.median(med):.1f} below_ceiling={below}")
    return 0


def _stage_gfx900_reference(driver, args, stage) -> Optional[int]:
    """The one-time shipped-floor reference benchmark (recalled forever)."""
    if not args.gfx900_reference:
        return None
    ref_shapes = args.ref_shapes.split(",") if args.ref_shapes else None
    result = driver.run_gfx900_reference(refresh=args.refresh, limit=args.limit,
                                        ref_shapes=ref_shapes, resume=args.resume,
                                        release_held=args.release_under_specified)
    print(f"gfx900 reference run: {result}")
    return 0 if result.get("status") in ("completed", "noop") else 1


def _match_family(label: str, fam_filter: List[str]) -> bool:
    """True when a label's family is in the filter.

    Why HH is special-cased: the HPA variants are distinct families with
    distinct cells, so ``--family HH`` must not silently pull in HH_HPA/HS_HPA
    and vice versa.
    """
    for f in fam_filter:
        if f == "HH" and ("HH_HPA" in label or "HS_HPA" in label):
            continue
        if f in label:
            return True
    return False


def _match_shape(shapes: List[str], shape_filter: List[str]) -> bool:
    """True when any wanted shape appears among a phase's shape strings."""
    return any(sh in shapes or any(sh in s for s in shapes)
               for sh in shape_filter)


def _match_targets(driver, args) -> List[Dict[str, Any]]:
    """Filter the manifest by the explicit / family / pattern / shape filters."""
    manifest = driver.load_phases_manifest()
    matched = []

    fam_filter = [f.upper() for f in args.family] if args.family else None
    pat_filter = args.pattern if args.pattern else None
    shape_filter = args.shape if args.shape else None

    target_keys = set(args.targets or [])

    for target in manifest:
        tid = str(target.get("phase_id", target.get("target_id", "")))
        lbl = str(target.get("label", ""))
        shapes = [str(s) for s in target.get("shapes", [])]

        if target_keys:
            clean_tid = tid.replace("phase_", "").replace("target_", "")
            if tid not in target_keys and lbl not in target_keys and clean_tid not in target_keys:
                continue

        if fam_filter and not _match_family(lbl, fam_filter):
            continue
        if pat_filter and not any(pat in lbl for pat in pat_filter):
            continue
        if shape_filter and not _match_shape(shapes, shape_filter):
            continue
        matched.append(target)
    return matched


def _stage_benchmark(driver, args) -> Optional[int]:
    """Stage 3: execute the matched targets, then emit the acceptance report."""
    matched = _match_targets(driver, args)

    if args.dry_run:
        print(f"Matched {len(matched)} targets in manifest:")
        for t in matched:
            print(f"  - {t.get('phase_id')}: {t.get('label')} (shapes: {t.get('shapes')})")
        return 0

    print(f"Executing {len(matched)} matched targets across Stage 3 benchmark...")
    results = []
    executed_count = 0
    for target in matched:
        if driver._stop_requested or driver._finish_after_iteration:
            break
        res = driver.execute_phase(target, driver.run_dir)
        results.append(res)
        if res.get("status") not in ("interrupted", "skipped_by_user"):
            executed_count += 1
        if driver._finish_after_iteration:
            print("End-after-iteration requested, halting target execution")
            break

    final_status = "interrupted" if driver._stop_requested else "completed"
    run_meta: Dict[str, Any] = {"targets_executed": executed_count}
    if driver._finish_after_iteration:
        run_meta["end_after_iteration"] = True
    driver.registry.update_run_status(driver.run_dir.name, final_status, run_meta)
    print(f"Completed {executed_count} targets (run status: {final_status})")

    driver.generate_acceptance_report()
    return 0


def _stage_native(driver, args) -> Optional[int]:
    """The native-only auto loop (no reference floor)."""
    result = driver.run_auto(args.budget, args.mutation_budget,
                            opt_in_identical_skip=not args.force,
                            release_held=args.release_under_specified,
                            skip_reference=True)
    print(f"Native-only auto loop complete: {result}")
    return 0 if result.get("converged") else 1


def _stage_auto(driver, args) -> Optional[int]:
    """The --auto loop, after asking the user the four questions.

    Why the plan owns the decisions: the four answers (re-measure illegal?
    re-measure under-specified? iterations? mutations?) are the user's, not a
    default's. CLI flags take precedence only over the *numeric* half; the plan
    owns the release decisions, and the --release-* flags are a one-directional
    non-interactive spelling of questions 2 and 3 -- a flag can say yes, the
    prompt (or its absence) decides otherwise.
    """
    from oto.runners.auto_prompt import ask

    cli_budget = args.budget
    cli_mut_budget = args.mutation_budget

    plan = ask(base_dir=driver.base_dir, assume_yes=args.yes)

    if cli_budget is not None:
        plan.iterations = cli_budget
    if cli_mut_budget is not None:
        plan.mutations = cli_mut_budget

    if args.release_under_specified:
        plan.rerun_underspecified = True
    if getattr(args, "release_unreproducible", False):
        plan.rerun_unreproducible = True
    result = driver.run_auto(plan=plan,
                            budget=plan.iterations,
                            mutation_budget=plan.mutations,
                            opt_in_identical_skip=not args.force,
                            release_held=args.release_under_specified)
    print(f"7-Stage Auto loop complete: {result}")
    return 0 if result.get("converged") else 1


# ------------------------------------------------------------------- main

def main() -> int:
    """Parse the command line, build the driver, and dispatch one stage.

    Returns:
        A process exit code (0 = success).
    """
    parser = build_parser()
    args = parser.parse_args()

    stage = set(args.stage or [])
    report_only = (args.report is not None or args.best_library is not None
                   or bool(stage & READ_ONLY_STAGES))
    preflight_only = _ends_after_preflight(args, stage)

    driver = TensileDriver(
        base_dir=args.base_dir,
        phase_timeout_s=args.phase_timeout,
        tensile_root=args.tensile_root,
        cooldown_s=args.cooldown,
        create_run=not (args.dry_run or report_only or args.gfx900_reference
                        or preflight_only)
    )
    driver._live_interval = max(float(args.live_interval), 1.0)
    driver._live_enabled = (args.live == "on")

    # A table, in stage order. Each handler declares the flags it owns and
    # returns None to fall through, so a new flag cannot be declared without
    # being consulted somewhere (guarded by test_interactive_keys.py).
    for handler in (_stage_preflight, _stage_report, _stage_best_library,
                    _stage_synthesis, _stage_candidate_plan, _stage_retirement,
                    _stage_analytics, _stage_gfx900_reference):
        code = handler(driver, args, stage)
        if code is not None:
            return code

    if (args.targets or args.family or args.pattern or args.shape
            or "3" in stage or "benchmark" in stage):
        return _stage_benchmark(driver, args)
    if args.native:
        return _stage_native(driver, args)
    if args.auto:
        return _stage_auto(driver, args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
