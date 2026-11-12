#!/usr/bin/env python3
"""Candidate classification: what a measured candidate turned out to be.

Owns: ``classify_outcome`` (the pure decision -- functional vs non-functional vs
legal-rejected vs legal-slow vs pending, read off a candidate's on-disk CSVs)
and ``_per_cell_medians`` (the per-cell medians it compares against).
Does NOT own: the state that records the outcome (oto.ledger.mutator) or the bars
a candidate is judged against (oto.tensile.synthesis).
Public API: MutatorOutcomesMixin (classify_outcome, _per_cell_medians).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from oto.metrics.analytics import AnalyticsEngine


#: Outcome vocabulary. Terminal values may only be written to a pending row, and
#: the set of them is the classifier's contract with the mutator.
OUTCOME_PENDING = "pending"
OUTCOME_FUNCTIONAL = "functional"
OUTCOME_NON_FUNCTIONAL = "non_functional"
OUTCOME_LEGAL_REJECTED = "legal_rejected"
OUTCOME_LEGAL_SLOW = "legal_slow"

TERMINAL_OUTCOMES = frozenset({
    OUTCOME_FUNCTIONAL,
    OUTCOME_NON_FUNCTIONAL,
    OUTCOME_LEGAL_REJECTED,
    OUTCOME_LEGAL_SLOW,
})


class MutatorOutcomesMixin:
    """Candidate classification, mixed into Mutator."""


def _per_cell_medians(analytics: AnalyticsEngine,
                      records: List[Dict[str, Any]],
                      dtype_override: Optional[str] = None) -> Dict[tuple, float]:
    """Median throughput per `(dtype, shape)` for one phase's records.

    Uses the same `aggregate_by_cell` + `aggregate_cell` path as the report, so
    the per-cell numbers compared against the reference bars are the numbers the
    report itself would show. Re-aggregating here by some cheaper rule would let
    the verdict and the report disagree about the same measurement.

    `dtype_override` is not optional in practice: without it every key comes back
    `(dtype='Unknown', shape)`, no bar ever matches, and `legal_slow` silently
    never fires. The dtype lives in the phase id (or the deck entry for it), not
    in the CSV, exactly as `ab_audit.phase_records` already handles.
    """
    from oto.metrics.policy import aggregate_cell
    out: Dict[tuple, float] = {}
    try:
        cell_map = analytics.aggregate_by_cell(records,
                                               dtype_override=dtype_override)
    except Exception:
        return out
    for (dtype, shape, _fp), seeds in cell_map.items():
        try:
            out[(str(dtype).upper(), str(shape))] = aggregate_cell(seeds).median
        except Exception:
            continue
    return out


def _empty_detail(csv_count: int) -> Dict[str, Any]:
    """The mutable detail dict a verdict carries, in its canonical key order."""
    return {
        "csv_count": csv_count,
        "record_count": 0,
        "row_count": 0,
        "max_gflops": None,
        "median_gflops": None,
        "winner_freq": None,
        "winner_freq_positive": False,
        "slow_bars_applied": 0,
        "slow_unmatched_cells": 0,
        "slow_reference_median": None,
    }


def _load_records(
    analytics: AnalyticsEngine,
    csvs: List[Path]
) -> Tuple[List[Dict[str, Any]], int]:
    """Every loader-accepted record, and the raw row count, across `csvs`."""
    records: List[Dict[str, Any]] = []
    rows = 0
    for csv_path in csvs:
        records.extend(analytics.load_benchmark_csv(csv_path))
        rows += analytics.count_benchmark_rows(csv_path)
    return records, rows


def _median(values: List[float]) -> float:
    """Median of `values`, averaging the two middles on an even count."""
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def _record_winner_freq(analytics: AnalyticsEngine,
                        csvs: List[Path],
                        detail: Dict[str, Any]) -> None:
    """Record WinnerFreq alongside the verdict, as H.3.8 requires.

    It is observed, never decisive: a kernel that ran but never won its own
    internal comparison is still functional. Read through
    `AnalyticsEngine.read_column`/`winner_freq`, the canonical owner of Tensile
    CSV column reading -- a second reader here would be a second set of format
    assumptions, and it fails quietly: a mis-read column yields zeros, which
    reads as "no kernel won".
    """
    freq = analytics.winner_freq(csvs)
    if freq["max"] is not None:
        detail["winner_freq"] = freq["max"]
        detail["winner_freq_positive"] = freq["positive"]
        detail["winner_freq_n"] = freq["n"]


def _apply_slow_bars(analytics: AnalyticsEngine,
                     phase_dir: Path,
                     records: List[Dict[str, Any]],
                     slow_bars: Dict[tuple, Dict[str, Any]],
                     detail: Dict[str, Any]) -> bool:
    """Apply the per-cell reference bars; True when *every* measured cell is slow.

    `slow_bars` are per-cell bars from `coverage.reference_thresholds`, each
    `reference_median * (1 - band/100)`, i.e. "how much slower than the shipped
    floor is too slow, given how noisily this corpus measures".

    A candidate is slow only when *every* measured cell it produced is below its
    bar. That is the same all-or-nothing reading an absolute bar has always had,
    and it is the right one for a multi-shape sweep: a sweep is useful if *any*
    shape is competitive, so one good cell rescues the batch.

    Cells with no reference bar are **not** treated as slow. "The floor never ran
    here" is an absence of evidence, and inferring slowness from it would
    manufacture slow verdicts for exactly the unexplored cells most worth
    exploring. Those cells are counted in `slow_unmatched_cells` instead.
    """
    dtype = None
    try:
        dtype = analytics.extract_dtype_from_phase_id(phase_dir.name)
    except Exception:
        dtype = None
    per_cell = _per_cell_medians(analytics, records, dtype_override=dtype)
    judged: List[tuple] = []
    unmatched = 0
    for cell, med in sorted(per_cell.items()):
        bar = slow_bars.get(cell)
        if not bar or not bar.get("bar_gflops"):
            unmatched += 1
            continue
        judged.append((med, float(bar["bar_gflops"]),
                       float(bar.get("reference_median") or 0.0)))
    detail["slow_bars_applied"] = len(judged)
    detail["slow_unmatched_cells"] = unmatched
    if not judged:
        return False
    # The reference the slowest cell was judged against, for the report.
    detail["slow_reference_median"] = judged[0][2]
    return all(med < bar for med, bar, _ref in judged)


def classify_outcome(
    phase_dir: Path,
    analytics: AnalyticsEngine,
    slow_threshold: Optional[float] = None,
    slow_bars: Optional[Dict[tuple, Dict[str, Any]]] = None,
) -> tuple:
    """Decide what a candidate did, from its on-disk output alone.

    Pure function, CPU-only, no registry access. Returns
    `(outcome, detail)` where detail is a small dict for the ledger/report and
    never for a verdict.

      functional       at least one benchmark record with non-zero throughput
      legal_slow       functional, but materially below how the reference ran
      non_functional   a CSV exists and has rows, all of them non-positive
      legal_rejected   no CSV at all, or CSVs present but with no rows

    The functional/non_functional split is decided *solely* by
    `analytics.load_benchmark_csv`; `count_benchmark_rows` only separates "rows
    the loader dropped" from "no rows", which the loader cannot express.

    **`legal_slow` is relative to the gfx900 reference, never an absolute
    constant.** `slow_threshold` is an absolute GFlops bar, retained for tests,
    but it is the wrong instrument here: cells span 4 to 857 GFlops, so any
    single number either condemns every small cell or none. The per-cell
    `slow_bars` path is owned by `_apply_slow_bars`. With neither bar the
    verdict is `functional`: nothing has been justified as slow.
    """
    phase_dir = Path(phase_dir)
    bench_dir = phase_dir / "2_BenchmarkData"
    csvs = sorted(bench_dir.glob("*.csv")) if bench_dir.exists() else []

    detail = _empty_detail(len(csvs))
    if not csvs:
        return OUTCOME_LEGAL_REJECTED, detail

    records, rows = _load_records(analytics, csvs)
    detail["record_count"] = len(records)
    detail["row_count"] = rows

    if not records:
        # Loader found nothing. Rows present => they were all non-positive.
        return (OUTCOME_NON_FUNCTIONAL if rows else OUTCOME_LEGAL_REJECTED), detail

    values = [float(r.get("GFLOPS", 0.0)) for r in records]
    detail["max_gflops"] = max(values)
    detail["median_gflops"] = _median(values)
    _record_winner_freq(analytics, csvs, detail)

    if slow_threshold is not None and detail["median_gflops"] < slow_threshold:
        return OUTCOME_LEGAL_SLOW, detail

    # Reference-relative slowness, per cell. Evaluated after the absolute bar so
    # a caller supplying both keeps the cheaper, stricter test's behaviour.
    if slow_bars and _apply_slow_bars(analytics, phase_dir, records, slow_bars,
                                      detail):
        return OUTCOME_LEGAL_SLOW, detail

    return OUTCOME_FUNCTIONAL, detail
