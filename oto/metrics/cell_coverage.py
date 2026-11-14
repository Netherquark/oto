"""Coverage: cell evidence, cell states, and fitness for parent selection.

Owns: ``coverage_cells`` (descriptive evidence, never deciding what to run),
``decide_state`` (the three states, distinct because collapsing them is the
defect), ``lower_confidence_bound`` / ``select_parent``, the ledger-wide view,
and the acceptance band / per-cell slow bars read from the reference chain
rather than defaulted.

Does NOT own: the A/B arithmetic (oto.metrics.ab_delta), the report layout
(oto.metrics.acceptance_report), or the harnesses that read the band.

Public API: coverage_cells, decide_state, CELL_STATES, STATE_EXPLORE,
STATE_REPLICATE, STATE_RETIRED, lower_confidence_bound, select_parent,
coverage_from_registry, coverage_summary, samples_by_fingerprint,
measured_band_pct, slow_bar, reference_thresholds.

``coverage_cells`` is deliberately descriptive: it reports a cell's distinct
fingerprints, sample count, median and spread and never decides what to run.
``decide_state`` keeps the three states distinct because a cell with no candidate
is not a cell with a dead candidate, and a retired cell is not an empty one.

Parent choice is the lower confidence bound rather than the raw winner, so a
cell with thin evidence is preferred over a cell whose single lucky seed is ahead.

The acceptance band is *read*, never transcribed: it comes from the reference
chain, which measures it from cross-arm disagreement on identical configs plus
raw repeat spread. A caller that does not supply one gets the measured value
rather than a hardcoded percentage.
"""


from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from typing import Any

from oto.tensile.shape_order import shape_order_key

# Three cell states. The names are the specification; there is deliberately no
# fourth ("empty") state, because "nothing has been tried" and "everything tried
# failed" demand opposite actions (§H.1.2a).
STATE_EXPLORE = "explore"
STATE_REPLICATE = "replicate"
STATE_RETIRED = "retired"
CELL_STATES = frozenset({STATE_EXPLORE, STATE_REPLICATE, STATE_RETIRED})

#: Sample count at or below which a measurement is not yet a measurement, and so
#: asks for a replicate rather than a verdict. `n = 1` has no variance to
#: inspect, which is the whole point: a single seed cannot separate a win from
#: noise.
MIN_SAMPLES_FOR_VERDICT = 2


#: Populated on first call and reused. `arm_record_sets` walks every run
#: directory and every registry row, which costs ~90s on the live corpus -- fine
#: once, ruinous per phase. The key includes the band, so an explicit override
#: never poisons a later default lookup.
_REFERENCE_CACHE: dict[tuple[str, float | None], dict[str, Any]] = {}
_REFERENCE_BUILDING = False


def reference_thresholds(base_dir=None,
                         band_pct: float | None = None) -> dict[str, Any]:
    """Acceptance band and per-cell slow bars from reference scan.

    Band = how far two runs of one config disagree; bars = how far a candidate
    may fall below reference before it's a real regression.
    Bar = reference_median * (1 - band/100) per cell.
    Relative (not absolute) so ZZ/SS_HPA differ by orders of magnitude.
    Band subtracted so ties aren't slowness; without this, fires on noise.
    Cells reference never ran have no bar, reported in unmatched_cells.
    """
    global _REFERENCE_BUILDING

    key = (str(base_dir or ""), band_pct)
    if key in _REFERENCE_CACHE:
        return _REFERENCE_CACHE[key]
    if _REFERENCE_BUILDING:
        # Re-entered from inside `arm_record_sets`, which constructs a driver,
        # which constructs a Mutator. Answering with an empty result breaks the
        # cycle; the alternative is unbounded recursion.
        return {"band_pct": None, "bars": {}, "unmatched_cells": (),
                "band_source": "re-entrant", "available": False}

    _REFERENCE_BUILDING = True
    try:
        from pathlib import Path as _Path

        from oto.metrics import ab_audit
        base = _Path(base_dir) if base_dir else ab_audit.BASE
        native, floor, chain = ab_audit.arm_record_sets(base)
        band = ab_audit.measured_band(native, floor, band_pct)
        frac = max(0.0, float(band["band_pct"])) / 100.0

        deltas = ab_audit.cell_deltas(native, floor, agg="best_median", base=base)
        bars: dict[tuple[str, str], dict[str, Any]] = {}
        for (dtype, shape, _label), d in deltas.items():
            ref = float(d.get("spoof_median") or 0.0)
            if ref <= 0:
                continue
            bars[(str(dtype).upper(), str(shape))] = {
                "bar_gflops": ref * (1.0 - frac),
                "reference_median": ref,
                "n_kernels": d.get("n_spoof_kernels", 0),
                "band_pct": band["band_pct"],
            }
        out = {
            "band_pct": band["band_pct"],
            "band_source": band["band_source"],
            "bars": bars,
            "reference_runs": len(chain),
            "available": bool(bars),
        }
    except Exception:
        out = {"band_pct": None, "bars": {}, "unmatched_cells": (),
               "band_source": "unavailable", "available": False}
    finally:
        _REFERENCE_BUILDING = False

    _REFERENCE_CACHE[key] = out
    return out


def slow_bar(cell, base_dir=None, band_pct: float | None = None):
    """The `legal_slow` bar for one `(dtype, shape)` cell, or None.

    None means "no reference ran here", which the classifier reads as *cannot
    judge* rather than *slow*.
    """
    if cell is None:
        return None
    try:
        dtype, shape = cell[0], cell[1]
    except (TypeError, IndexError, KeyError):
        return None
    bars = reference_thresholds(base_dir, band_pct)["bars"]
    return bars.get((str(dtype).upper(), str(shape)))


def measured_band_pct(base_dir=None) -> float | None:
    """Read the measured acceptance band, or None if it cannot be measured.

    Reads `ab_audit`'s canonical band on the corpus rather than taking a literal.
    `ab_audit.arm_record_sets` + `ab_audit.measured_band` are the same two calls
    `ab_audit.audit` makes, so coverage and the audit cannot grade against two
    different bands, and neither recomputes its own record subset.

    Returns None rather than a default when nothing can be measured, because a
    band invented from nothing is exactly the number this project has already had
    to retract once. A caller that already holds the band (the audit does) should
    pass it in rather than paying for a second computation.
    """
    return reference_thresholds(base_dir).get("band_pct")


def coverage_cells(
    proposals: Sequence[dict[str, Any]],
    samples_by_fp: dict[str, list[float]],
    target_cells: Iterable[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Per (family, shape) evidence: distinct fps, n, median, spread.
    spread_ratio = (max - median)/median, matching policy.aggregate_cell.
    n counts samples per fp; cell reports min n (worst-measured config).
    target_cells = plan's intended (family, shape) pairs, included even with
    zero proposals (STATE_EXPLORE).
    """
    by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    for family, shape in (target_cells or ()):
        by_cell.setdefault((str(family), str(shape)), {"family": str(family), "shape": str(shape), "fingerprints": set(), "n_proposed": 0, "outcomes": {}})
    for row in proposals:
        family = str(row.get("family") or "?")
        shape = str(row.get("shape") or "?")
        key = (family, shape)
        entry = by_cell.setdefault(key, {
            "family": family,
            "shape": shape,
            "fingerprints": set(),
            "n_proposed": 0,
            "outcomes": {},
        })
        entry["n_proposed"] += 1
        entry["fingerprints"].add(row.get("fp"))
        outcome = str(row.get("outcome") or "pending")
        entry["outcomes"][outcome] = entry["outcomes"].get(outcome, 0) + 1
    cells: list[dict[str, Any]] = []
    for (family, shape), entry in by_cell.items():
        fps = [fp for fp in entry["fingerprints"] if fp]
        per_fp: dict[str, dict[str, Any]] = {}
        for fp in fps:
            samples = [g for g in samples_by_fp.get(fp, []) if g and g > 0]
            if not samples:
                continue
            median = float(statistics.median(samples))
            per_fp[fp] = {
                "fp": fp,
                "n": len(samples),
                "median": median,
                "spread_ratio": (max(samples) - median) / median if median > 0 else 0.0,
                "lcb": lower_confidence_bound(samples),
            }
        measured = list(per_fp.values())
        cells.append({
            "family": family,
            "shape": shape,
            "n_distinct_fp": len(fps),
            "n_proposed": entry["n_proposed"],
            "n_measured": len(measured),
            "outcomes": dict(entry["outcomes"]),
            "min_n": min((m["n"] for m in measured), default=0),
            "best_median": max((m["median"] for m in measured), default=0.0),
            "max_spread_ratio": max((m["spread_ratio"] for m in measured), default=0.0),
            "per_fp": measured,
        })
    cells.sort(key=lambda c: (c["family"], shape_order_key(c["shape"])))
    return cells


def decide_state(cell: dict[str, Any],
                 band_pct: float | None = None) -> str:
    """Classify a cell into exactly one of the three states.

    Order matters. Retirement is checked *after* evidence exists, because a cell
    with no proposal rows is unexplored, and "we have never looked" must not be
    recorded as "we looked and it does not work" (§H.1.2a).
    """
    outcomes = cell.get("outcomes") or {}
    decided = {k: v for k, v in outcomes.items() if k != "pending"}

    if cell.get("n_proposed", 0) == 0 or cell.get("n_distinct_fp", 0) == 0:
        return STATE_EXPLORE

    # All measured candidates failed: retired, and distinct from "empty".
    if decided and sum(decided.values()) == sum(outcomes.values()) \
            and set(decided) <= {"non_functional"}:
        return STATE_RETIRED

    # Evidence too thin to conclude, or unstable beyond the band: replicate.
    if cell.get("min_n", 0) < MIN_SAMPLES_FOR_VERDICT:
        return STATE_REPLICATE

    if band_pct is not None:
        limit = float(band_pct) / 100.0
        for entry in cell.get("per_fp", []):
            if entry.get("spread_ratio", 0.0) > limit:
                return STATE_REPLICATE

    return STATE_EXPLORE


def lower_confidence_bound(samples: Sequence[float], z: float = 1.96) -> float:
    """Normal-approximation lower confidence bound on the median.

    `n = 1` returns the sample itself: with one observation there is no variance
    to estimate, so the bound is the value and the *thinness* is what
    `decide_state` reports, not something the bound should fake. Cells needing
    more samples are routed to `replicate` by state, and parent selection
    prefers a well-measured config over a lucky one.
    """
    values = [float(g) for g in samples if g and g > 0]
    if not values:
        return 0.0
    median = float(statistics.median(values))
    if len(values) < 2:
        return median
    return median - z * statistics.stdev(values) / (len(values) ** 0.5)


def select_parent(cell: dict[str, Any],
                  fallback: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Choose the parent for the next batch by LCB, never by raw winner.

    Lower-confidence-bound parent selection. `harvest()` today takes ``max(median_gflops)``, which is how
    a noise-level win becomes the parent of the next batch: a config whose median
    is high because of one lucky seed outranks a config that is merely good.
    Ranking by the lower bound inverts exactly that case.
    """
    measured = [e for e in cell.get("per_fp", []) if e.get("n", 0) > 0]
    if not measured:
        return fallback
    return max(measured, key=lambda e: (e.get("lcb", 0.0), e.get("n", 0)))


def samples_by_fingerprint(records: Iterable[dict[str, Any]]) -> dict[str, list[float]]:
    """Group benchmark records into `fp -> [GFLOPS]`, via the canonical column.

    Reads `GFLOPS` / `median_gflops` exactly as `AnalyticsEngine.aggregate_by_cell`
    does, and keeps only positive values, so coverage's notion of a sample agrees
    with analytics' rather than being a third definition.
    """
    out: dict[str, list[float]] = {}
    for rec in records:
        fp = rec.get("fingerprint", rec.get("fp"))
        if not fp:
            continue
        gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
        try:
            value = float(gflops)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out.setdefault(str(fp), []).append(value)
    return out


def coverage_from_registry(registry, band_pct: float | None = None,
                           base_dir=None,
                           target_cells: Iterable[tuple[str, str]] | None = None,
                           ) -> dict[str, Any]:
    """Build the coverage summary straight from a registry.

    Keeps the two join keys explicit: proposals carry `(family, shape)`, records
    carry `fp` plus a measurement. The join is `proposals.fp -> records.fp`, which
    is the only identity both tables share.

    Pass `band_pct` when the caller already has it; otherwise it is read from
    `ab_audit`.
    """
    if band_pct is None:
        band_pct = measured_band_pct(base_dir)
    proposals = registry.all_proposals()
    records = registry.read_records(record_type="benchmark_result")
    return coverage_summary(proposals, samples_by_fingerprint(records),
                            band_pct=band_pct, target_cells=target_cells)


def coverage_summary(
    proposals: Sequence[dict[str, Any]],
    samples_by_fp: dict[str, list[float]],
    band_pct: float | None = None,
    target_cells: Iterable[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Cells with their state and chosen parent, for reporting and tests."""
    cells = coverage_cells(proposals, samples_by_fp,
                           target_cells=target_cells)
    tally: dict[str, int] = dict.fromkeys(sorted(CELL_STATES), 0)
    out: list[dict[str, Any]] = []
    for cell in cells:
        state = decide_state(cell, band_pct=band_pct)
        tally[state] = tally.get(state, 0) + 1
        row = dict(cell)
        row["state"] = state
        parent = select_parent(cell)
        row["parent_fp"] = parent["fp"] if parent else None
        row["parent_lcb"] = parent.get("lcb") if parent else None
        row["parent_median"] = parent.get("median") if parent else None
        out.append(row)
    return {"band_pct": band_pct, "tally": tally, "cells": out}
