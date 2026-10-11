#!/usr/bin/env python3
"""The native-vs-spoof A/B delta: the arithmetic every acceptance number rests on.

Owns: ``compute_native_vs_spoof_delta`` -- per-cell pairing of the native arm against the recalled gfx900 floor under one of nine aggregation bases, with the optional telemetry clock correction applied to BOTH arms against ONE shared reference clock.
Does NOT own: the records it is fed (oto.metrics.analytics), the clocks (oto.runners.clocks), or the verdict threshold (oto.metrics.ab_audit).
Public API: ABDeltaMixin."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from oto.device.peaks import (FAMILY_DTYPE_CHAR, FAMILY_DTYPES,
                              REALISTIC_CEILINGS, cell_key, cube_side)
from oto.metrics.family_attribution import resolve_cell_family

#: The coverage floor lives with the engine that aggregates coverage
#: (oto.metrics.analytics); imported at call time to keep this module free of a
#: circular import with it.
CLOCK_MIN_COVERAGE = None


def _coverage_floor() -> float:
    """The minimum clock coverage a cell needs before it may be clock-adjusted."""
    from oto.metrics.analytics import CLOCK_MIN_COVERAGE as floor
    return floor


#: Aggation-basis resolution: which per-kernel statistic each arm is graded on.
#: `native` is the deck side, `spoof` the shipped-floor side.
_NATIVE_KEY = {
    "median": "median", "best_median": "best_median", "floor_best": "median",
    "strict": "worst_median", "winner": "best_median",
    "winner_clock": "best_median_clock", "median_clock": "median_clock",
}
_SPOOF_KEY = {
    "median": "median", "best_median": "median", "floor_best": "best_median",
    "strict": "best_median", "winner": "best_median",
    "winner_clock": "best_median_clock", "median_clock": "median_clock",
}


def _collect(records: List[Dict[str, Any]],
              sclk_by_gkey: Optional[Dict[Tuple[str, str], float]] = None,
              sclk_ref: Optional[float] = None
              ) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """Per-cell per-kernel statistics for one arm.

    A workload cell is (family, cube side). Records are grouped by
    (source_run, phase_id, fingerprint) FIRST, and the per-kernel median is
    taken within that group, because the same (phase_id, fingerprint) is
    benchmarked by more than one run and pooling those samples would average
    across runs instead of taking each run's measurement on its own.

    Two non-obvious rules live here:

    * **Per-kernel median first, THEN the cell statistic.** Comparing raw max
      samples instead would let a single lucky seed decide the verdict, and
      seed noise dwarfs real config deltas.
    * **A clock-adjusted figure is only trusted above a coverage floor.** With
      partial coverage the eligible subset is a different, unrepresentative
      sample, and its max can sit far below the unadjusted max -- which would
      silently make the arm with worse coverage look slower. So the clock
      figures are dropped for the whole cell when coverage is thin, and the
      cell is graded unadjusted (both arms together, never one-sided).

    ASSUMPTION (reported, not hidden): throughput proportional to core clock.
    That holds for ALU-bound kernels but OVER-corrects memory-bound ones
    (GFM/GEMM small shapes, whose ceiling is set by mclk/DRAM, not sclk), so a
    clock-adjusted delta on a DDR-bound cell is an extrapolation, not a
    measurement. Both the adjusted and the unadjusted statistic are reported.
    """
    samples: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    # Group key includes the source run: the same (phase_id,
    # fingerprint) is benchmarked by more than one run, and pooling
    # those samples into one "kernel median" would average across
    # runs instead of taking each run's measurement on its own.
    groups: Dict[Tuple[str, int], Dict[Tuple[str, str, str], List[float]]] = defaultdict(lambda: defaultdict(list))
    meta: Dict[Tuple[str, str, str], Tuple[str, str, str]] = {}
    throttled: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    for rec in records:
        fam = resolve_cell_family(rec)
        if not fam:
            continue
        side = cube_side(rec.get("ProblemType") or rec.get("shape") or "")
        if not side:
            continue
        gf = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
        if gf <= 0:
            continue
        key = (fam, side)
        src = str(rec.get("source_run") or rec.get("run_id") or "")
        phase_id = str(rec.get("phase_id", ""))
        fp = str(rec.get("fingerprint", ""))
        gkey = (src, phase_id, fp)
        samples[key].append(gf)
        groups[key][gkey].append(gf)
        meta[gkey] = (src, phase_id, fp)
        adj = rec.get("GFLOPS_throttle_adjusted")
        if adj:
            throttled[key].append(float(adj))
    stats: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for key, gs in groups.items():
        # Per-kernel median first, THEN the cell statistic. Comparing
        # raw max samples instead would let a single lucky seed
        # decide the verdict (seed noise dwarfs real config deltas).
        kernel_meds = {gk: statistics.median(v) for gk, v in gs.items() if v}
        if not kernel_meds:
            continue
        # Telemetry-normalized twin of the same per-kernel medians:
        # GFLOPS is linear in core clock, so a kernel measured at
        # sclk_meas is scaled to the corpus reference clock by
        # (sclk_ref / sclk_meas). Per-kernel factor => the scaled
        # median is exactly median * factor, so no seed is re-used.
        # Only kernels with real per-phase clock data are eligible,
        # and coverage is reported so an unadjusted number can never
        # be presented as an adjusted one.
        kernel_meds_clock: Dict[Tuple[str, str, str], float] = {}
        n_samples_cell = sum(len(v) for v in gs.values())
        n_clock = 0
        if sclk_by_gkey and sclk_ref:
            for gk, med in kernel_meds.items():
                hz = sclk_by_gkey.get((gk[0], gk[1]))
                if hz and hz > 0:
                    kernel_meds_clock[gk] = med * (sclk_ref / hz)
                    n_clock += len(gs[gk])
        # A clock-adjusted BEST is only meaningful if it is the best
        # over the same population the unadjusted best is drawn from.
        # With partial coverage the eligible subset is a different,
        # unrepresentative sample, and its max can sit far below the
        # unadjusted max — which would silently make the arm with
        # worse coverage look slower. So the clock figures are only
        # trusted above a coverage floor, and the cell is otherwise
        # graded unadjusted (both arms together, never one-sided).
        coverage = (n_clock / n_samples_cell) if n_samples_cell else 0.0
        clock_ok = coverage >= _coverage_floor()
        if not clock_ok:
            kernel_meds_clock = {}
        med = statistics.median(kernel_meds.values())
        winner = max(kernel_meds, key=lambda gk: kernel_meds[gk])
        src, phase_id, fp = meta[winner]
        runs = sorted({g[0] for g in kernel_meds if g[0]})
        thr = statistics.median(throttled[key]) if throttled[key] else med
        clock_winner = (max(kernel_meds_clock, key=lambda gk: kernel_meds_clock[gk])
                        if kernel_meds_clock else None)
        stats[key] = {
            "best": max(samples[key]),
            "best_median": kernel_meds[winner],
            "worst_median": min(kernel_meds.values()),
            "best_median_clock": (kernel_meds_clock[clock_winner]
                                  if clock_winner else 0.0),
            "median_clock": (statistics.median(kernel_meds_clock.values())
                             if kernel_meds_clock else 0.0),
            "clock_coverage": coverage,
            "clock_ok": bool(clock_ok),
            "clock_sclk_hz": (sclk_by_gkey.get((clock_winner[0], clock_winner[1]), 0.0)
                              if clock_winner else 0.0),
            "clock_kernels": len(kernel_meds_clock),
            "median": med,
            "throttle": thr,
            "throttle_adjusted": bool(throttled[key]),
            "n_kernels": len(kernel_meds),
            "n_samples": len(samples[key]),
            "n_runs": len(runs),
            "runs": runs,
            "origin": {
                "gflops": kernel_meds[winner],
                "run_id": src,
                "phase_id": phase_id,
                "fingerprint": fp,
            },
        }
    return stats


def _stat(stats: Dict[str, Any], which: str, agg: str) -> float:
    """Resolve one arm's comparison statistic.

    Bases, from lenient to strict. `which` is 'native' or 'spoof'.

      median      both arms: median of per-kernel medians
      best_median native: best per-kernel median (deck winner);
                  spoof:  median of per-kernel medians
      floor_best  native: median of per-kernel medians;
                  spoof:  best per-kernel median (floor winner)
      strict      native: WORST per-kernel median;
                  spoof:  best per-kernel median
      winner      both arms: best per-kernel median
      throttle    sclk-adjusted feed, else median
      best        max single raw sample (seed-noisy, reference only)

    'floor_best' is the basis for "is a typical native kernel better
    than the best kernel the floor ships" — it cannot be won by
    cherry-picking one lucky config, because the native side is graded
    on its median. 'strict' is the literal "truly better in every way"
    test: the native arm's WORST kernel must still beat the floor's
    BEST kernel, which is per-cell dominance rather than an average.

    A clock basis with no per-phase clock data for this arm falls back
    to the SAME statistic unadjusted (best per-kernel median), and the
    cell is flagged via clock_adjusted below — never silently presented
    as a clock-corrected number.
    """
    native_key = {k: v for k, v in _NATIVE_KEY.items()}
    spoof_key = {k: v for k, v in _SPOOF_KEY.items()}
    key = (native_key if which == "native" else spoof_key).get(agg, agg)
    val = stats.get(key, 0.0)
    if not val and key.endswith("_clock"):
        val = stats.get(key[:-6]) or stats["median"]
    return float(val)


class ABDeltaMixin:
    """ABDeltaMixin behaviour, mixed into AnalyticsEngine."""


    def compute_native_vs_spoof_delta(
            self,
            native_records: List[Dict[str, Any]],
            spoof_records: List[Dict[str, Any]],
            agg: str = "winner",
            tie_band_pct: float = 5.0,
            sclk_by_phase: Optional[Dict[Tuple[str, str], float]] = None,
            sclk_ref: Optional[float] = None
        ) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
        """per-cell native-vs-spoof pairing; see the module docstring.

        A workload cell is (family/dtype, cube shape) and MUST match on both arms
        — the mapping key cell_key = "FAMILY:SIDE" synthesized from the
        authoritative config identity (never re-derived from phase_id text, so
        HH_HPA/HS_HPA stay distinct).

        Every statistic is derived per-kernel-median-first, so a single lucky
        seed can never decide a verdict. The nine bases and their asymmetry are
        enumerated on ``_stat``; the clock-normalization rules are enumerated on
        ``_collect``.

        Both arms are CORPUS-WIDE, not per-run: every record passed in is a
        candidate, whatever run produced it.
        """
        return _pair_cells(native_records, spoof_records, agg,
                           tie_band_pct, sclk_by_phase, sclk_ref)


def _pair_cells(
        native_records: List[Dict[str, Any]],
        spoof_records: List[Dict[str, Any]],
        agg: str,
        tie_band_pct: float,
        sclk_by_phase: Optional[Dict[Tuple[str, str], float]],
        sclk_ref: Optional[float],
    ) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """Pair the two arms per cell and grade each pair.

    Both arms are CORPUS-WIDE, not per-run: every record passed in is a
    candidate, whatever run produced it. A run is allowed to contribute no new
    cells of its own (every phase deduped as
    identical_fp_already_passed) while the historical winners remain the real
    native candidates — so winners, including older winner runs, are picked
    across the whole record set.

    When a clock basis is asked for but only one arm is clock-covered, NEITHER
    is adjusted: a half-adjusted delta would compare a clock-corrected arm
    against an unadjusted one, which no longer cancels. The fallback is the
    same basis without the `_clock` suffix (winner_clock -> winner), so a
    missing telemetry file degrades to the plain comparison instead of
    silently switching statistic.
    """
    ns = _collect(native_records, sclk_by_phase, sclk_ref)
    ss = _collect(spoof_records, sclk_by_phase, sclk_ref)

    deltas: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for key in sorted(set(ss) & set(ns)):
        fam, side = key
        sv, nv = ss[key], ns[key]
        native_val = _stat(nv, "native", agg)
        spoof_val = _stat(sv, "spoof", agg)
        # Both arms must be clock-covered or NEITHER is adjusted: a
        # half-adjusted delta would compare a clock-corrected arm against
        # an unadjusted one, which no longer cancels.
        clock_ok = bool(nv["clock_ok"] and sv["clock_ok"] and sclk_ref)
        if agg.endswith("_clock") and not clock_ok:
            # Fall back to the SAME basis without the clock normalization
            # (winner_clock -> winner, median_clock -> median), so a
            # missing telemetry file degrades to the plain comparison
            # instead of silently switching to a different statistic.
            plain = agg[:-len("_clock")]
            native_val = _stat(nv, "native", plain)
            spoof_val = _stat(sv, "spoof", plain)
        if spoof_val <= 0 or native_val <= 0:
            continue
        ratio = native_val / spoof_val
        delta_pct = (ratio - 1.0) * 100.0
        tie = abs(delta_pct) <= tie_band_pct
        verdict = "TIE" if tie else ("WIN" if ratio > 1.0 else "LOSS")
        dtype = FAMILY_DTYPE_CHAR.get(fam, "")
        deltas[(dtype, f"{side}x{side}x{side}", f"cell_{fam}_{side}")] = {
            "native_value": native_val,
            "spoof_value": spoof_val,
            "native_median": nv["median"],
            "spoof_median": sv["median"],
            "native_best_median": nv["best_median"],
            "spoof_best_median": sv["best_median"],
            "native_worst_median": nv["worst_median"],
            "spoof_worst_median": sv["worst_median"],
            "native_best": nv["best"],
            "spoof_best": sv["best"],
            "native_throttle": nv["throttle"],
            "spoof_throttle": sv["throttle"],
            "throttle_adjusted": bool(nv["throttle_adjusted"] and sv["throttle_adjusted"]),
            "native_best_median_clock": nv["best_median_clock"],
            "spoof_best_median_clock": sv["best_median_clock"],
            "native_median_clock": nv["median_clock"],
            "spoof_median_clock": sv["median_clock"],
            "native_clock_coverage": nv["clock_coverage"],
            "spoof_clock_coverage": sv["clock_coverage"],
            "native_clock_kernels": nv["clock_kernels"],
            "spoof_clock_kernels": sv["clock_kernels"],
            "native_clock_sclk_hz": nv["clock_sclk_hz"],
            "spoof_clock_sclk_hz": sv["clock_sclk_hz"],
            "sclk_ref_hz": float(sclk_ref or 0.0),
            # True only when BOTH arms actually had per-phase clock data
            # for this cell, i.e. the delta really is clock-normalized.
            "clock_adjusted": bool(clock_ok and agg.endswith("_clock")),
            "clock_basis": bool(agg.endswith("_clock")),
            "cell_key": f"{fam}:{side}",
            "spoof_fp": f"cell_{fam}_{side}",
            "family": fam,
            "agg": agg,
            "delta_pct": delta_pct,
            "tie": tie,
            "verdict": verdict,
            "n_native_kernels": nv["n_kernels"],
            "n_spoof_kernels": sv["n_kernels"],
            "n_native_runs": nv["n_runs"],
            "n_spoof_runs": sv["n_runs"],
            "native_runs": nv["runs"],
            "spoof_runs": sv["runs"],
            "native_winner_run": nv["origin"].get("run_id", ""),
            "native_winner_phase": nv["origin"].get("phase_id", ""),
            "native_winner_fp": nv["origin"].get("fingerprint", ""),
            "spoof_winner_run": sv["origin"].get("run_id", ""),
            "spoof_winner_phase": sv["origin"].get("phase_id", ""),
        }
    return deltas
