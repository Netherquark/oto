#!/usr/bin/env python3
"""The native-vs-spoof A/B delta: the arithmetic every acceptance number rests on.

Owns: ``compute_native_vs_spoof_delta`` -- per-cell pairing of the native arm
against the recalled gfx900 floor under one of nine aggregation bases, with the
optional telemetry clock correction applied to BOTH arms against ONE shared
reference clock -- and ``cells_not_beating_floor`` (the same pairing, reduced to
the set of cells the port has not yet won). Both grade like-for-like (§R56.3):
``protocol_basis="family"`` admits only records whose invocation form matches
across arms; cross-form evidence is carried as provenance fields, never graded.
Does NOT own: the records it is fed (`oto.metrics.benchmark_analytics`), the clocks (`oto.runners.clock_telemetry`), or the verdict threshold (`oto.metrics.ab_audit`).
Public API: ABDeltaMixin."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import cube_side
from oto.metrics.family_attribution import resolve_cell_family
from oto.metrics.measurement_protocol import SINGLE, protocol_of

#: The coverage floor lives with the engine that aggregates coverage
#: (oto.metrics.benchmark_analytics); imported at call time to keep this module free of a
#: circular import with it.
CLOCK_MIN_COVERAGE = None


def _coverage_floor() -> float:
    """The minimum clock coverage a cell needs before it may be clock-adjusted."""
    from oto.metrics.benchmark_analytics import CLOCK_MIN_COVERAGE
    return CLOCK_MIN_COVERAGE


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


def _collect(records: list[dict[str, Any]],
              sclk_by_gkey: dict[tuple[str, str], float] | None = None,
              sclk_ref: float | None = None
              ) -> dict[tuple[str, int], dict[str, Any]]:
    """Per-cell per-kernel statistics for one arm.

    A workload cell is (family, cube side). Records are grouped by
    (source_run, phase_id, fingerprint) FIRST, and the per-kernel median is
    taken within that group.

    Key rules:
    * Per-kernel median first, THEN cell statistic.
    * Clock-adjusted figures only trusted above coverage floor.
    """
    samples, groups, meta, throttled = _collect_raw_data(records)
    return _compute_cell_stats(samples, groups, meta, throttled, sclk_by_gkey, sclk_ref)

def _collect_raw_data(records):
    """Collect raw samples and group by cell and kernel."""
    samples = defaultdict(list)
    groups = defaultdict(lambda: defaultdict(list))
    meta = {}
    throttled = defaultdict(list)
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
    return samples, groups, meta, throttled

def _compute_cell_stats(samples, groups, meta, throttled,
                         sclk_by_gkey, sclk_ref):
    """Compute per-cell statistics from grouped data."""
    stats = {}
    for key, gs in groups.items():
        kernel_meds = {gk: statistics.median(v) for gk, v in gs.items() if v}
        if not kernel_meds:
            continue

        kernel_meds_clock, n_clock, n_samples_cell = _compute_clock_medians(
            gs, kernel_meds, sclk_by_gkey, sclk_ref)

        coverage = (n_clock / n_samples_cell) if n_samples_cell else 0.0
        clock_ok = coverage >= _coverage_floor()
        if not clock_ok:
            kernel_meds_clock = {}

        winner = max(kernel_meds, key=lambda gk: kernel_meds[gk])
        med = statistics.median(kernel_meds.values())
        src, phase_id, fp = meta[winner]
        runs = sorted({g[0] for g in kernel_meds if g[0]})
        thr = statistics.median(throttled[key]) if throttled[key] else med

        clock_winner = (max(kernel_meds_clock, key=lambda gk: kernel_meds_clock[gk])
                        if kernel_meds_clock else None)

        stats[key] = _build_stat_dict(
            samples[key], kernel_meds, kernel_meds_clock, winner,
            clock_winner, med, thr, src, phase_id, fp, runs,
            coverage, clock_ok, sclk_by_gkey, throttled[key]
        )
    return stats

def _compute_clock_medians(gs, kernel_meds, sclk_by_gkey, sclk_ref):
    """Compute clock-adjusted medians for kernels with clock data."""
    kernel_meds_clock = {}
    n_clock = 0
    n_samples_cell = sum(len(v) for v in gs.values())
    if sclk_by_gkey and sclk_ref:
        for gk, med in kernel_meds.items():
            hz = sclk_by_gkey.get((gk[0], gk[1]))
            if hz and hz > 0:
                kernel_meds_clock[gk] = med * (sclk_ref / hz)
                n_clock += len(gs[gk])
    return kernel_meds_clock, n_clock, n_samples_cell

def _build_stat_dict(samples, kernel_meds, kernel_meds_clock, winner,
                      clock_winner, med, thr, src, phase_id, fp, runs,
                      coverage, clock_ok, sclk_by_gkey, throttled_list):
    """Build the statistics dictionary for a cell."""
    return {
        "best": max(samples),
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
        "throttle_adjusted": bool(throttled_list),
        "n_kernels": len(kernel_meds),
        "n_samples": len(samples),
        "n_runs": len(runs),
        "runs": runs,
        "origin": {
            "gflops": kernel_meds[winner],
            "run_id": src,
            "phase_id": phase_id,
            "fingerprint": fp,
        },
    }


def _stat(stats: dict[str, Any], which: str, agg: str) -> float:
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
    native_key = dict(_NATIVE_KEY.items())
    spoof_key = dict(_SPOOF_KEY.items())
    key = (native_key if which == "native" else spoof_key).get(agg, agg)
    val = stats.get(key, 0.0)
    if not val and key.endswith("_clock"):
        val = stats.get(key[:-6]) or stats["median"]
    return float(val)


class ABDeltaMixin:
    """ABDeltaMixin behaviour, mixed into AnalyticsEngine."""


    def compute_native_vs_spoof_delta(
            self,
            native_records: list[dict[str, Any]],
            spoof_records: list[dict[str, Any]],
            agg: str = "winner",
            tie_band_pct: float = 5.0,
            sclk_by_phase: dict[tuple[str, str], float] | None = None,
            sclk_ref: float | None = None,
            protocol_basis: str = "family",
        ) -> dict[tuple[str, str, str], dict[str, Any]]:
        """per-cell native-vs-spoof pairing; see the module docstring.

        A workload cell is (family/dtype, cube shape) and MUST match on both arms
        — the mapping key cell_key = "FAMILY:SIDE" synthesized from the
        authoritative config identity (never re-derived from phase_id text, so
        HH_HPA/HS_HPA stay distinct).

        ``protocol_basis`` is the like-for-like rule (§R56.3): when set to a
        protocol value (default "family") only records stamped with that
        invocation form admit to the graded pairing, on BOTH arms — the floor is
        family-only by construction, and a native single/partial reading never
        grades against it. "any" reproduces the pre-§R56.3 corpus-wide pairing,
        which is kept for provenance as the `native_best_any_protocol` field
        rather than as a verdict basis.

        Every statistic is derived per-kernel-median-first, so a single lucky
        seed can never decide a verdict. The nine bases and their asymmetry are
        enumerated on ``_stat``; the clock-normalization rules are enumerated on
        ``_collect``.

        Both arms are CORPUS-WIDE, not per-run: every record passed in is a
        candidate, whatever run produced it.
        """
        return _pair_cells(native_records, spoof_records, agg,
                           tie_band_pct, sclk_by_phase, sclk_ref,
                           protocol_basis)

    def cells_not_beating_floor(
            self,
            native_records: list[dict[str, Any]],
            spoof_records: list[dict[str, Any]],
            tie_band_pct: float = 5.0,
            protocol_basis: str = "family",
    ) -> dict[str, dict[str, Any]]:
        """Cells whose native winner has not yet beaten the recalled floor.

        Under ``agg="winner"`` BOTH arms are graded on their best per-kernel
        median, so a cell appears here exactly when the best kernel this port
        has ever measured on it (within ``protocol_basis``, default the
        like-for-like family basis, §R56.3) fails to beat the best kernel the
        gfx900 floor ships by more than the tie band -- i.e. when the cell is a
        TIE or a LOSS in the A/B report.

        This is the campaign's *objective* restated as a set: the point of the
        port is to beat the floor, so a tied cell is unfinished however healthy
        its percentage of the family ceiling looks. Returns ``{}`` when either
        arm is empty (no frozen floor recalled, or no native measurements),
        which the caller must read as "cannot judge" rather than "all good".
        """
        deltas = _pair_cells(native_records, spoof_records, agg="winner",
                             tie_band_pct=tie_band_pct,
                             sclk_by_phase=None, sclk_ref=None,
                             protocol_basis=protocol_basis)
        return {e["cell_key"]: e for e in deltas.values()
                if e.get("verdict") != "WIN"}


def _clock_basis_values(
    nv: dict[str, Any],
    sv: dict[str, Any],
    agg: str,
    sclk_ref: float | None,
) -> tuple[float, float, bool]:
    """(native_val, spoof_val, clock_ok) under the clock-fallback rule.

    Both arms must be clock-covered or NEITHER is adjusted: a half-adjusted
    delta would compare a clock-corrected arm against an unadjusted one, which
    no longer cancels. The fallback is the same basis without the `_clock`
    suffix (winner_clock -> winner, median_clock -> median), so a missing
    telemetry file degrades to the plain comparison instead of silently
    switching to a different statistic.
    """
    native_val = _stat(nv, "native", agg)
    spoof_val = _stat(sv, "spoof", agg)
    clock_ok = bool(nv["clock_ok"] and sv["clock_ok"] and sclk_ref)
    if agg.endswith("_clock") and not clock_ok:
        plain = agg[:-len("_clock")]
        native_val = _stat(nv, "native", plain)
        spoof_val = _stat(sv, "spoof", plain)
    return native_val, spoof_val, clock_ok


def _clock_fields(nv: dict[str, Any], sv: dict[str, Any],
                  sclk_ref: float | None, clock_ok: bool,
                  agg: str) -> dict[str, Any]:
    """The clock-telemetry fields, identical in both bases."""
    return {
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
    }


def _delta_entry(
    fam: str,
    side: str,
    dtype: str,
    nv: dict[str, Any],
    sv: dict[str, Any],
    native_val: float,
    spoof_val: float,
    delta_pct: float,
    tie: bool,
    verdict: str,
    agg: str,
    sclk_ref: float | None,
    clock_ok: bool,
) -> dict[str, Any]:
    """One graded native/spoof pair, as the report dict."""
    entry: dict[str, Any] = {
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
    }
    entry.update(_clock_fields(nv, sv, sclk_ref, clock_ok, agg))
    entry.update({
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
    })
    return entry


def _basis_collects(
        native_records: list[dict[str, Any]],
        spoof_records: list[dict[str, Any]],
        protocol_basis: str,
        sclk_by_phase: dict[tuple[str, str], float] | None,
        sclk_ref: float | None,
) -> tuple[str, dict[tuple[str, int], dict[str, Any]],
           dict[tuple[str, int], dict[str, Any]], Any, Any]:
    """Collect per-cell stats for one pairing under the like-for-like rule.

    Returns ``(basis, native_stats, spoof_stats, any_stats, iso_stats)``.
    With ``protocol_basis`` None/""/"any" both arms are unfiltered — the exact
    pre-§R56.3 numbers — and the provenance stats are the unfiltered ones
    themselves. Otherwise both arms are filtered to that invocation form
    (usually FAMILY, the form the floor is measured under), and two extra
    unfiltered native walks carry provenance: the mixed-basis winner
    (``any_stats``) and the best isolated single-problem reading
    (``iso_stats``).
    """
    if protocol_basis in (None, "", "any"):
        return ("any",
                _collect(native_records, sclk_by_phase, sclk_ref),
                _collect(spoof_records, sclk_by_phase, sclk_ref),
                None, None)
    ns = _collect([r for r in native_records if protocol_of(r) == protocol_basis],
                  sclk_by_phase, sclk_ref)
    ss = _collect([r for r in spoof_records if protocol_of(r) == protocol_basis],
                  sclk_by_phase, sclk_ref)
    any_stats = _collect(native_records, sclk_by_phase, sclk_ref)
    iso_stats = (_collect([r for r in native_records if protocol_of(r) == SINGLE],
                          sclk_by_phase, sclk_ref)
                 if protocol_basis != SINGLE else ns)
    return protocol_basis, ns, ss, any_stats, iso_stats


def _pair_cells(
        native_records: list[dict[str, Any]],
        spoof_records: list[dict[str, Any]],
        agg: str,
        tie_band_pct: float,
        sclk_by_phase: dict[tuple[str, str], float] | None,
        sclk_ref: float | None,
        protocol_basis: str = "family",
    profile=None,
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Pair the two arms per cell and grade each pair.

    Both arms are CORPUS-WIDE, not per-run: every record passed in is a
    candidate, whatever run produced it. A run is allowed to contribute no new
    cells of its own (every phase deduped as
    identical_fp_already_passed) while the historical winners remain the real
    native candidates — so winners, including older winner runs, are picked
    across the whole record set. Grading and its provenance envelopes come
    from :func:`_basis_collects`.

    When a clock basis is asked for but only one arm is clock-covered, NEITHER
    is adjusted (see _clock_basis_values).
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    basis, ns, ss, any_stats, iso_stats = _basis_collects(
        native_records, spoof_records, protocol_basis, sclk_by_phase, sclk_ref)

    deltas: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key in sorted(set(ss) & set(ns)):
        fam, side = key
        sv, nv = ss[key], ns[key]
        native_val, spoof_val, clock_ok = _clock_basis_values(
            nv, sv, agg, sclk_ref)
        if spoof_val <= 0 or native_val <= 0:
            continue
        ratio = native_val / spoof_val
        delta_pct = (ratio - 1.0) * 100.0
        tie = abs(delta_pct) <= tie_band_pct
        verdict = "TIE" if tie else ("WIN" if ratio > 1.0 else "LOSS")
        dtype = _loader.resolve_profile(profile,).family_dtype_char.get(fam, "",)
        entry = _delta_entry(fam, side, dtype, nv, sv, native_val, spoof_val,
                             delta_pct, tie, verdict, agg, sclk_ref, clock_ok)
        entry["basis_protocol"] = basis
        entry["native_best_any_protocol"] = (
            any_stats[key]["best_median"] if any_stats and key in any_stats
            else native_val)
        entry["native_isolated_best"] = (
            iso_stats[key]["best_median"] if iso_stats and key in iso_stats
            else (native_val if basis == SINGLE else 0.0))
        deltas[(dtype, f"{side}x{side}x{side}", f"cell_{fam}_{side}")] = entry
    return deltas
