#!/usr/bin/env python3
"""Stage 7 acceptance A/B audit, and the CLI that prints it.

Owns: ``audit`` (classify every cell in both arms with a certainty grade),
``cell_deltas`` (the canonical per-cell pairing), ``_proposal_coverage``
(Option-H Phase-3 coverage from the ledger), ``print_report`` and ``main``.
Does NOT own: the record loading (oto.metrics.ab_records), the identity
(oto.metrics.ab_identity), the band (oto.metrics.ab_band), or the report layout
(oto.metrics.report).
Public API: BASE, TIE_BAND_PCT, BAND_LO, BAND_HI, audit, cell_deltas,
measured_band, verdict, arm_record_sets, reproducible_band, repeat_dispersion,
phase_records, arm_records, phase_family, norm_config, main (re-exports).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from oto.metrics.ab_band import (BAND_HI, BAND_LO, TIE_BAND_PCT, measured_band,
                                 repeat_dispersion, reproducible_band, verdict)
from oto.metrics.ab_identity import (AbIdentityMixin, _CP_RE, _driver,
                                     _norm_macro_tile, _pair_key, norm_config)
from oto.metrics.ab_records import (_registry_records, arm_record_sets,
                                    arm_records, phase_records, phase_family)
from oto.metrics.analytics import extract_family_from_phase_id
from oto.device.peaks import cell_key
from oto.metrics.policy import aggregate_cell

BASE = Path(__file__).resolve().parents[2]

__all__ = ["BASE", "TIE_BAND_PCT", "BAND_LO", "BAND_HI", "audit", "cell_deltas",
           "measured_band", "verdict", "arm_record_sets", "reproducible_band",
           "repeat_dispersion", "phase_records", "arm_records", "phase_family",
           "norm_config", "main"]


def phase_family(phase_id: str) -> str:
    """Which Tensile generator produced a phase: ``auto``, ``deck`` or ``unknown``.

    The distinction that matters is Tensile's AutoTuner versus a deck-driven
    sweep. Everything named ``phase_auto_*`` is AutoTuner; every other phase is
    a deck sweep, whichever prefix the deck happened to use (``phase_ss_*`` for
    the floor's pooled phases, ``phase_<cell>_*`` for the live deck). Keying on
    the raw prefix instead would call those two the same generator by accident
    and the floor's deck sweeps an unknown one.

    Invocation form and generator are confounded: the single-shape population
    is overwhelmingly ``auto`` while the multi-shape population is entirely
    deck sweeps, and the two executed in disjoint halves of the same run, so
    thermal state is confounded on top of that.
    """
    pid = phase_id or ""
    if not pid:
        return "unknown"
    return "auto" if pid.startswith("phase_auto") else "deck"

def cell_deltas(native: List[Dict[str, Any]], floor: List[Dict[str, Any]],
                agg: str = "best_median",
                base: Optional[Path] = None) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """Canonical per-cell native-vs-floor pairing, from already-loaded records.

    Split out from `arm_record_sets` so a caller that needs the band *and* the
    per-cell reference numbers scans the corpus once rather than twice -- the
    scan walks every run directory and every registry row, so paying it twice for
    one decision is not a rounding error.

    `agg='best_median'` is the report's default asymmetric basis, under which the
    floor side is the *median* of its per-kernel medians. That is the number
    "how the reference ran" means everywhere else in this codebase, which is why
    the slowness bar is derived from this call rather than from a second,
    hand-rolled per-cell statistic that could quietly disagree with the report.
    """
    return _driver(Path(base) if base else BASE).analytics.compute_native_vs_spoof_delta(
        native, floor, agg=agg)


def measured_band(native: List[Dict[str, Any]], floor: List[Dict[str, Any]],
                  band_pct: Optional[float] = None) -> Dict[str, Any]:
    """The acceptance band, and where each component of it came from.

    Two independent estimates of the same thing: cross-arm disagreement on
    identical configs, and raw repeat spread. The shipped 5% is only a floor.
    Never grade inside the repeat tail. An explicit `band_pct` overrides, and
    that is recorded rather than silently substituted.
    """
    cross = reproducible_band(native, floor)
    repeat = repeat_dispersion(native + floor)
    cross_pct = cross["protocol_matched"].get("band_pct") or 0.0
    repeat_pct = repeat.get("p90_cv_pct") or 0.0
    if band_pct is None:
        band = max(cross_pct, repeat_pct, TIE_BAND_PCT)
        source = ("max(cross-arm, repeat-tail, shipped-floor)"
                  if band > TIE_BAND_PCT else "shipped-floor")
    else:
        band = float(band_pct)
        source = "caller-supplied"
    return {"band_pct": band, "band_source": source, "cross_arm": cross,
            "repeat_dispersion": repeat}


def _best_by_cell(
    native: List[Dict[str, Any]],
    floor: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Best GFLOPS record per cell_key, per arm."""
    cells: Dict[str, Dict[str, Any]] = {}
    for recs, side in ((native, "native"), (floor, "spoof")):
        for r in recs:
            key = r.get("cell_key") or cell_key(
                extract_family_from_phase_id(r["phase_id"]), r["ProblemType"])
            if not key:
                continue
            slot = cells.setdefault(key, {"cell_key": key})
            best = slot.get(side)
            if best is None or r["GFLOPS"] > best["GFLOPS"]:
                slot[side] = r
    return cells


def _grade_slot(slot: Dict[str, Any], band: float) -> None:
    """Fill one cell's verdict, provenance and certainty fields in place."""
    n, f = slot.get("native"), slot.get("spoof")
    slot["native_value"] = n["GFLOPS"] if n else None
    slot["spoof_value"] = f["GFLOPS"] if f else None
    if n and f and f["GFLOPS"] > 0:
        slot["delta_pct"] = (n["GFLOPS"] / f["GFLOPS"] - 1) * 100.0
        slot["verdict"] = verdict(slot["delta_pct"], band)
    else:
        slot["delta_pct"] = None
        slot["verdict"] = "UNGRADED"
    slot["protocol_matched"] = bool(
        n and f and n["shapes_per_phase"] == f["shapes_per_phase"])
    slot["native_family"] = n.get("phase_family") if n else None
    slot["spoof_family"] = f.get("phase_family") if f else None
    # Same form is necessary but not sufficient: auto-generated and
    # deck-generated phases are different benchmark procedures. This is a
    # veto, not a confirmation -- "other" is a catch-all for unknown
    # provenance, so an other/other match is reported as
    # provenance_known=False rather than treated as evidence.
    slot["provenance_matched"] = bool(
        slot["protocol_matched"]
        and n.get("phase_family") and f.get("phase_family")
        and n["phase_family"] == f["phase_family"])
    slot["provenance_known"] = bool(
        n and f and n.get("phase_family") not in (None, "", "unknown")
        and f.get("phase_family") not in (None, "", "unknown"))
    slot["native_run"] = n["source_run"] if n else None
    slot["spoof_run"] = f["source_run"] if f else None
    # Certainty is separate from the verdict, and a comparison across
    # different invocation forms produces a number that is not evidence: the
    # band measurement shows those ratios scatter over +/-180%, because form
    # is confounded with both the Tensile generator and the wall-clock
    # window the phase ran in. Within a matched provenance the margin still
    # has to clear the measured repeat tail before it means anything.
    if slot["verdict"] == "UNGRADED":
        slot["certainty"] = "missing"
    elif not slot["protocol_matched"]:
        slot["certainty"] = "form_mismatch"
    elif not slot["provenance_matched"]:
        slot["certainty"] = "generator_mismatch"
    elif abs(slot["delta_pct"] or 0.0) <= band:
        slot["certainty"] = "within_noise"
    else:
        slot["certainty"] = "certain"


def _summary_counts(cells: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """The graded tally, the certainty split and the three mismatch counts."""
    graded = [c for c in cells.values() if c["verdict"] != "UNGRADED"]
    tally: Dict[str, int] = defaultdict(int)
    certain: Dict[str, int] = defaultdict(int)
    for c in graded:
        tally[c["verdict"]] += 1
        if c["certainty"] == "certain":
            certain[c["verdict"]] += 1
    return {
        "tally": dict(tally),
        "tally_certain": dict(certain),
        "tally_certainty": dict(Counter(
            c["certainty"] for c in cells.values())),
        "ungraded": sum(1 for c in cells.values() if c["verdict"] == "UNGRADED"),
        "provenance_mismatched_cells": sum(
            1 for c in cells.values()
            if c["protocol_matched"] and not c["provenance_matched"]),
        "provenance_unknown_cells": sum(
            1 for c in cells.values()
            if c["protocol_matched"] and not c["provenance_known"]),
        "protocol_mismatched_cells": sum(
            1 for c in cells.values() if not c["protocol_matched"]),
    }


def audit(base: Path = BASE, band_pct: Optional[float] = None) -> Dict[str, Any]:
    """Classify every cell in both arms.

    ``native`` is the whole native corpus and ``floor`` the recalled gfx900
    reference chain; both come from :func:`arm_record_sets`.
    """
    native, floor, chain = arm_record_sets(base)

    measured_b = measured_band(native, floor, band_pct)
    band = measured_b["band_pct"]
    cross, repeat = measured_b["cross_arm"], measured_b["repeat_dispersion"]

    cells = _best_by_cell(native, floor)
    for slot in cells.values():
        _grade_slot(slot, band)

    return {
        "floor_chain": chain,
        "band_pct": band,
        "band_source": measured_b["band_source"],
        "shipped_band_pct": TIE_BAND_PCT,
        "reproducible_band": measured_b,
        "repeat_dispersion": repeat,
        "proposal_coverage": _proposal_coverage(base, band),
        **_summary_counts(cells),
        "n_cells": len(cells),
        "cells": [cells[k] for k in sorted(cells)],
    }

def _proposal_coverage(base: Path, band_pct: Optional[float] = None) -> Dict[str, Any]:
    """Option H Phase 3 coverage: `n`, spread, and the novel/replicate split.

    Read from the ledger rather than recomputed from the run directories, because
    the ledger is the only place a proposal's *origin* is recorded. A cell whose
    evidence is one seed is reported as `replicate`, which is what makes a
    replicate's value visible after the fact instead of only at selection time.

    `band_pct` is the band `audit` already computed and is passed in deliberately:
    recomputing it here would mean a second, possibly different, corpus sweep -- and
    calling `ab_audit.audit()` from inside `audit()` would recurse.

    Returns a zeroed summary rather than raising when the `proposals` table is
    absent (pre-Phase-1 registries), so this stays additive on an older DB.
    """
    try:
        from oto.metrics.coverage import coverage_from_registry
        from oto.ledger.registry import SQLiteRegistry
        db = base / "gfx90c_results" / "registry.db"
        if not db.exists():
            return {"available": False, "reason": "no registry.db"}
        reg = SQLiteRegistry(base, read_only=True)
        summary = coverage_from_registry(
            reg, band_pct=band_pct, base_dir=base)
        origins: Dict[str, int] = {}
        for row in reg.all_proposals():
            key = str(row.get("origin") or "?")
            origins[key] = origins.get(key, 0) + 1
        return {
            "available": True,
            "band_pct": summary["band_pct"],
            "tally": summary["tally"],
            "origins": origins,
            "n_cells": len(summary["cells"]),
            "cells": [
                {
                    "family": c["family"],
                    "shape": c["shape"],
                    "state": c["state"],
                    "n_distinct_fp": c["n_distinct_fp"],
                    "min_n": c["min_n"],
                    "best_median": c["best_median"],
                    "max_spread_ratio": c["max_spread_ratio"],
                    "parent_fp": c["parent_fp"],
                    "parent_lcb": c["parent_lcb"],
                }
                for c in summary["cells"]
            ],
        }
    except Exception as exc:  # additive: never fail the audit on coverage
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

def _fmt_table(rows: List[List[str]], headers: List[str]) -> str:
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "-" * len(line)]
    for r in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def _print_proposal_coverage(cov: Dict[str, Any]) -> None:
    """Print `n`, spread and the novel/replicate split per mutated cell."""
    if not cov.get("available"):
        print(f"proposal coverage: unavailable ({cov.get('reason', 'unknown')})")
        return
    tally = cov.get("tally") or {}
    origins = cov.get("origins") or {}
    band = cov.get("band_pct")
    band_txt = f"{band:.1f}%" if band else "unmeasured"
    print(f"\nproposal coverage: cells={cov.get('n_cells', 0)}  "
          f"explore={tally.get('explore', 0)}  replicate={tally.get('replicate', 0)}  "
          f"retired={tally.get('retired', 0)}  "
          f"origin novel={origins.get('novel', 0)} replicate={origins.get('replicate', 0)}"
          f"  band={band_txt}")
    cells = cov.get("cells") or []
    if cells:
        print(_fmt_table(
            [[c["family"], c["shape"], c["state"], c["n_distinct_fp"],
              c["min_n"], f"{c['max_spread_ratio']:.3f}",
              (c["parent_fp"] or "-")[:12]]
             for c in cells],
            ["family", "shape", "state", "n_fp", "min_n", "spread", "parent"]))


def print_report(result: Dict[str, Any]) -> None:
    rb = result["reproducible_band"]
    print(f"floor chain : {result['floor_chain']}")
    print(f"tie band    : +/-{result['band_pct']:.1f}% "
          f"({result['band_source']}; shipped default "
          f"+/-{result['shipped_band_pct']:.1f}%)")
    for label, key in (("protocol-matched  ", "protocol_matched"),
                       ("protocol-mismatched", "protocol_mismatched")):
        s = rb[key]
        if not s.get("n"):
            print(f"{label}: no shared configurations")
            continue
        print(f"{label}: n={s['n']:4}  median={s['median_ratio']:.3f}  "
              f"p10={s['p10_ratio']:.3f}  p90={s['p90_ratio']:.3f}  "
              f"band=+/-{s['band_pct']:.1f}%  "
              f"within shipped band={s['share_within_shipped_band']*100:.1f}%")
    rd = result.get("repeat_dispersion") or {}
    if rd.get("n"):
        print(f"repeat spread: n={rd['n']:4}  median CV="
              f"{rd['median_cv_pct']:.1f}%  p90 CV={rd['p90_cv_pct']:.1f}%  "
              f"worst single={rd['max_cv_single_pct']:.1f}%  "
              f"worst multi={rd['max_cv_multi_pct']:.1f}%")
    _print_proposal_coverage(result.get("proposal_coverage") or {})
    print(f"\ncells={result['n_cells']}  {result['tally']}  "
          f"ungraded={result['ungraded']}  "
          f"protocol-mismatched={result['protocol_mismatched_cells']}  "
          f"generator-mismatched={result['provenance_mismatched_cells']}  "
          f"generator-unknown={result['provenance_unknown_cells']}")
    print(f"certainty: {result['tally_certainty']}")
    print(f"certain (same form + same generator + margin beyond noise): "
          f"{result['tally_certain']}\n")

    rows = []
    for c in result["cells"]:
        nv = c["native_value"]
        fv = c["spoof_value"]
        d = c["delta_pct"]
        rows.append([
            c["cell_key"],
            c["verdict"],
            c["certainty"],
            f"{nv:.2f}" if nv else "-",
            f"{fv:.2f}" if fv else "-",
            f"{d:+.2f}" if d is not None else "-",
            "yes" if c["protocol_matched"] else "NO",
            f"{c.get('native_family') or '-'}/{c.get('spoof_family') or '-'}",
            str(c["native_run"] or "-")[:22],
            str(c["spoof_run"] or "-")[:24],
        ])
    print(_fmt_table(rows, ["cell", "verdict", "certainty", "native", "spoof",
                            "delta%", "matched", "families", "native_run",
                            "spoof_run"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", type=Path, default=BASE)
    ap.add_argument("--json", type=Path, help="also write machine-readable output here")
    ap.add_argument("--arm-classes", action="store_true",
                    help="print the reproducible band per invocation form only")
    ap.add_argument("--band", type=float, default=None,
                    help=f"override the tie band (default: measured, else "
                         f"+/-{TIE_BAND_PCT})")
    args = ap.parse_args()

    result = audit(base=args.base_dir, band_pct=args.band)
    if args.arm_classes:
        print(json.dumps(result["reproducible_band"], indent=2))
    else:
        print_report(result)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, default=str))
        print(f"\njson -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
