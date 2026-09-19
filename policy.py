#!/usr/bin/env python3
"""
policy.py — Stage 4: Adaptive Repeat / Convergence & Run Policy

Handles per-cell aggregation, stability gating, adaptive repeat,
retirement logic, and the should_run gating matrix.
"""

import statistics
import math
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class CellAggregation:
    """Result of per-cell N8 median-of-seeds aggregation."""
    median: float
    max_val: float
    spread_ratio: float  # (max - med) / med — measures instability
    num_seeds: int
    cv: float  # coefficient of variation
    top2_gap_pct: float  # gap between top 2 seeds/medians


class StabilityStatus:
    """Stability matrix classification."""
    APPROVED = "approved"
    NEEDS_REPEAT = "needs_repeat"
    NEEDS_SUPER_SAMPLE = "needs_super_sample"
    TIE = "tie"
    NEEDS_2ND_INDEPENDENT_RUN = "needs_2nd_independent_run"
    RETIRE_CANDIDATE = "retire_candidate"


def aggregate_cell(seeds: List[float]) -> CellAggregation:
    """
    Aggregate seed values using N8 median-of-seeds rule (stdlib).

    Args:
        seeds: List of benchmark results (GFLOPS)

    Returns:
        CellAggregation with median, max, spread_ratio, cv, top2_gap_pct
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


def classify_stability(agg: CellAggregation) -> str:
    """
    Classify cell stability based on aggregation metrics.

    Spec: Super-sample if CV > 15% or top-2 gap < 3% or seeds < 3.

    Args:
        agg: CellAggregation from aggregate_cell()

    Returns:
        StabilityStatus constant string
    """
    if agg.num_seeds < 3:
        return StabilityStatus.NEEDS_SUPER_SAMPLE

    if agg.cv > 0.15 or agg.top2_gap_pct < 3.0:
        return StabilityStatus.NEEDS_SUPER_SAMPLE

    return StabilityStatus.APPROVED


def classify_tie(reference_median: float, candidate_median: float, tie_band_pct: float = 5.0) -> bool:
    """
    Classify if two medians are tied (within ±% band).

    Args:
        reference_median: Reference median value
        candidate_median: Candidate median value
        tie_band_pct: ±% band for tie classification (default 5%)

    Returns:
        True if tied, False otherwise
    """
    if reference_median <= 0:
        return False

    delta_pct = abs(candidate_median - reference_median) / reference_median * 100.0
    return delta_pct <= tie_band_pct


def should_repeat(agg: CellAggregation, current_numbench: int) -> Tuple[bool, int]:
    """
    Determine if a cell needs selective repeat and what NumBenchmarks to use.

    Args:
        agg: CellAggregation from aggregate_cell()
        current_numbench: Current NumBenchmarks value

    Returns:
        (should_repeat, suggested_numbench) tuple
    """
    # If CV > 15% or top-2 gap < 3%, recommend super-sample
    if agg.cv > 0.15 or agg.top2_gap_pct < 3.0:
        suggested = min(current_numbench * 2, 9)  # Cap at 9
        return True, suggested

    # If seeds < 3, recommend at least 3
    if agg.num_seeds < 3:
        suggested = max(3, current_numbench)
        return True, suggested

    return False, current_numbench


def should_run(
    phase_id: Any,
    fp: str,
    registry=None,
    phase_scope: Optional[List[Any]] = None,
    opt_in_identical_skip: bool = True
) -> Tuple[bool, str]:
    """
    Evaluate whether a phase/config should run per the policy matrix.

    Order:
      1. Scope check (if phase_scope given)
      2. Tier-1 retirement (fp-less phase retire)
      3. Tier-2 retirement (phase, fp)
      4. Identical-fp skip (if opt_in_identical_skip)

    Args:
        phase_id: Target identifier (e.g. "phase_ss_Ailk_Bjlk_1024x1024x1024")
        fp: Config fingerprint
        registry: SQLiteRegistry instance
        phase_scope: Optional list of scoped target IDs
        opt_in_identical_skip: Whether identical-fp skip is active

    Returns:
        (should_run_bool, reason_str)
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
    cell_records: List[Dict[str, Any]],
    reference_meds: Optional[Dict[str, float]] = None
) -> Tuple[bool, str]:
    """
    Check if a candidate config can be retired.

    Eligibility (strict gate, per informed-convergence scope):
      - ≥3 samples per (phase_id, fp) cell
      - ≥2 independent runs/cell (each run must carry seed data)
      - run-to-run median drift ≤1%

    Args:
        cell_records: List of benchmark records for this cell across runs
        reference_meds: Optional dict mapping (phase_id, fp) to reference
            median; if provided, a cell is only retired when its fingerprint
            is known to the reference set.

    Returns:
        (eligible, reason) tuple
    """
    per_run_meds: Dict[str, List[float]] = {}
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


class RetirementTier:
    """Three-tier retirement classification."""
    TIER1_IDENTICAL_FP = "tier1_identical_fp"  # Identical-fp skip (default on)
    TIER2_DOMINANCE = "tier2_dominance"  # Dominance retirement (≥2 runs/cell)
    TIER3_PEAK_SPOOF = "tier3_peak_spoof"  # Peak/spoof never retires


def classify_retirement_tier(
    is_identical_fp: bool,
    is_peak_or_spoof: bool,
    has_dominance: bool,
    independent_runs: int
) -> Optional[str]:
    """
    Classify retirement tier for a config.

    Args:
        is_identical_fp: True if fingerprint identical to another config
        is_peak_or_spoof: True if this is a peak or spoof reference
        has_dominance: True if this config is dominated by another
        independent_runs: Number of independent runs for this cell

    Returns:
        RetirementTier constant string or None
    """
    if is_peak_or_spoof:
        return RetirementTier.TIER3_PEAK_SPOOF
    if is_identical_fp:
        return RetirementTier.TIER1_IDENTICAL_FP
    if has_dominance and independent_runs >= 2:
        return RetirementTier.TIER2_DOMINANCE
    return None


def apply_d2_4_protection(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Apply D2.4 protection: 3 premature auto-retire records stay as ordinary rows,
    never marked as verdicts.

    The 3 protected records are:
    - p12 387d2577
    - p5 286b940a
    - p6 1570d91a

    Args:
        records: List of registry records

    Returns:
        Filtered records with retirement verdicts removed from protected entries
    """
    protected_fps = {
        "387d2577",  # p12
        "286b940a",  # p5
        "1570d91a",  # p6
    }

    protected = []
    for rec in records:
        fp = rec.get("fp", "")
        if fp in protected_fps and rec.get("action") == "retire":
            rec_copy = rec.copy()
            rec_copy["action"] = None
            rec_copy["d2_4_protected"] = True
            protected.append(rec_copy)
        else:
            protected.append(rec)

    return protected
