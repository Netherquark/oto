#!/usr/bin/env python3
"""Cell policy: aggregation, the should_run gate, and retirement eligibility.

Owns: ``aggregate_cell`` (the one median/spread definition every consumer shares),
``should_run`` (whether a phase may run, including the identical-fp skip
and its `force` override), and ``check_retirement_eligibility``.

Does NOT own: the run loop (`oto.runners.phase_runner`), the ledger it reads
(`oto.ledger.registry`), or the report it feeds (`oto.metrics.acceptance_report`).

Public API: aggregate_cell, should_run, check_retirement_eligibility.
"""


import statistics
from dataclasses import dataclass
from typing import Any


@dataclass
class CellAggregation:
    """Result of per-cell N8 median-of-seeds aggregation."""
    median: float
    max_val: float
    spread_ratio: float  # (max - med) / med — measures instability
    num_seeds: int
    cv: float  # coefficient of variation
    top2_gap_pct: float  # gap between top 2 seeds/medians


def aggregate_cell(seeds: list[float]) -> CellAggregation:
    """
    Aggregate seed values using N8 median-of-seeds rule (stdlib).

    `seeds` is the list of benchmark results (GFLOPS). Returns a
    ``CellAggregation`` with median, max, spread_ratio, cv and top2_gap_pct.
    """
    if not seeds:
        raise ValueError("Cannot aggregate empty seed list")

    sorted_seeds = sorted(seeds)
    median = float(statistics.median(sorted_seeds))
    max_val = float(max(sorted_seeds))
    spread_ratio = (max_val - median) / median if median > 0 else 0.0

    if len(sorted_seeds) > 1 and median > 0:
        cv = float(statistics.stdev(sorted_seeds) / median)
    else:
        cv = 0.0

    if len(sorted_seeds) >= 2:
        top_val = sorted_seeds[-1]
        second_val = sorted_seeds[-2]
        top2_gap_pct = ((top_val - second_val) / top_val * 100.0) if top_val > 0 else 0.0
    else:
        top2_gap_pct = 0.0

    return CellAggregation(
        median=median,
        max_val=max_val,
        spread_ratio=spread_ratio,
        num_seeds=len(seeds),
        cv=cv,
        top2_gap_pct=top2_gap_pct
    )


def should_run(
    phase_id: Any,
    fp: str,
    registry=None,
    phase_scope: list[Any] | None = None,
    opt_in_identical_skip: bool = True
) -> tuple[bool, str]:
    """
    Evaluate whether a phase/config should run per the policy matrix.

    Order:
      1. Scope check (if phase_scope given)
      2. Tier-1 retirement (fp-less phase retire)
      3. Tier-2 retirement (phase, fp)
      4. Identical-fp skip (if opt_in_identical_skip)

    `phase_id` is the target identifier (e.g.
    "phase_ss_Ailk_Bjlk_1024x1024x1024"); `fp` the config fingerprint;
    `registry` the ``SQLiteRegistry`` instance; `phase_scope` an optional
    list of scoped target IDs; `opt_in_identical_skip` enables the
    identical-fp skip. Returns the ``(should_run, reason)`` tuple.
    """
    p_str = str(phase_id).replace("phase_", "")

    # 1. Scope check
    if phase_scope is not None:
        normalized_scope = [str(p).replace("phase_", "") for p in phase_scope]
        if p_str not in normalized_scope:
            return False, "not_in_phase_scope"

    if registry is None:
        return True, "approved"

    # 2. Tier-1 check: phase-level retirement (fp-less)
    if hasattr(registry, "is_phase_retired") and registry.is_phase_retired(p_str):
        return False, "tier1_phase_retired"

    # 3. Tier-2 check: (phase, fp) retirement
    if hasattr(registry, "is_config_retired") and registry.is_config_retired(p_str, fp):
        return False, "tier2_config_retired"

    # 4. Identical-fp skip
    if opt_in_identical_skip:
        if hasattr(registry, "has_fp_passed") and registry.has_fp_passed(fp):
            return False, "identical_fp_already_passed"

    return True, "approved"


def check_retirement_eligibility(
    cell_records: list[dict[str, Any]],
    reference_meds: dict[str, float] | None = None
) -> tuple[bool, str]:
    """
    Eligibility verdict for retiring a candidate config.

    Eligibility (strict gate, per informed-convergence scope):
      - ≥3 samples per (phase_id, fp) cell
      - ≥2 independent runs/cell (each run must carry seed data)
      - run-to-run median drift ≤1%

    `cell_records` is the list of benchmark records for this cell across
    runs; `reference_meds` optionally maps ``(phase_id, fp)`` to its reference
    median -- when provided, a cell is only retired when its fingerprint is
    known to the reference set. Returns the ``(eligible, reason)`` tuple.
    """
    per_run_meds: dict[str, list[float]] = {}
    samples = 0
    for rec in cell_records:
        run_id = rec.get("run_id", "")
        med = None
        result = rec.get("result")
        if isinstance(result, dict):
            med = result.get("median_gflops") or result.get("median")
        seed_count = rec.get("seed_count") or rec.get("num_seeds")
        if seed_count:
            samples += int(seed_count)
        if med is None and seed_count:
            total = rec.get("total_gflops")
            if total:
                med = float(total) / float(seed_count)
        if med:
            per_run_meds.setdefault(run_id, []).append(float(med))

    if samples < 3:
        return False, f"insufficient samples ({samples}) < 3"
    if len(per_run_meds) < 2:
        return False, f"insufficient independent runs ({len(per_run_meds)}) < 2"

    run_medians = [statistics.median(v) for v in per_run_meds.values() if v]
    if len(run_medians) >= 2:
        lo, hi = min(run_medians), max(run_medians)
        spread = (hi - lo) / lo if lo > 0 else 0.0
        if spread > 0.01:
            return False, f"run drift {spread*100:.2f}% > 1%"

    return True, f"≥3 samples, {len(per_run_meds)} runs, drift within 1%"
