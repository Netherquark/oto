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
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


from oto.metrics.ab_band import (BAND_HI, BAND_LO, TIE_BAND_PCT, measured_band,
                                 repeat_dispersion, reproducible_band, verdict)
from oto.metrics.ab_identity import (AbIdentityMixin, _CP_RE, _driver,
                                     _norm_macro_tile, _pair_key, norm_config)
from oto.metrics.ab_records import (_registry_records, arm_record_sets,
                                    arm_records, phase_records, phase_family)
from oto.metrics.analytics import extract_family_from_phase_id
from oto.device.peaks import cell_key
from oto.metrics.protocol import (FAMILY, PARTIAL, SINGLE, UNKNOWN,
                                  like_for_like, protocol_of)

BASE = Path(__file__).resolve().parents[2]

__all__ = ["BASE", "TIE_BAND_PCT", "BAND_LO", "BAND_HI", "audit", "cell_deltas",
           "measured_band", "verdict", "arm_record_sets", "reproducible_band",
           "repeat_dispersion", "phase_records", "arm_records", "phase_family",
           "norm_config", "protocol_census", "main"]


def cell_deltas(native: List[Dict[str, Any]], floor: List[Dict[str, Any]],
                agg: str = "best_median", base: Optional[Path] = None,
                protocol_basis: str = "family") -> Dict[Tuple[str, str, str], Dict[str, Any]]:
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
        native, floor, agg=agg, protocol_basis=protocol_basis)


def protocol_census(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """The invocation-form census of an arm: counts per stamped protocol.

    The audit prints it next to the graded tally so the exclusion the graded
    basis performs is visible as data, not silently absorbed: under the
    family basis the cells graded are exactly the family-stamped measurements
    and everything else shows up here.
    """
    census: Dict[str, int] = {}
    for rec in records:
        p = protocol_of(rec)
        census[p] = census.get(p, 0) + 1
    return census


def _records_in_basis(records: List[Dict[str, Any]],
                      protocol_basis: str) -> List[Dict[str, Any]]:
    """One arm restricted to the named invocation form ('any' = unfiltered)."""
    if protocol_basis in (None, "", "any"):
        return list(records)
    return [r for r in records if protocol_of(r) == protocol_basis]


def _protocol_matched(n: Optional[Dict[str, Any]],
                      f: Optional[Dict[str, Any]]) -> bool:
    """Whether one cell's two best records were measured in the same form.

    Stamped protocols decide (§R56.3): two records are matched exactly when
    both carry the same known invocation form. Records that carry no stamp
    (legacy syntheses without one) fall back to the count equality the audit
    has always used, and a record that is stamped versus unstamped is
    honestly unmatched -- UNKNOWN can neither be asserted to match nor
    mismatch.
    """
    if not (n and f):
        return False
    n_p, f_p = protocol_of(n), protocol_of(f)
    if n_p != UNKNOWN or f_p != UNKNOWN:
        return like_for_like(n_p, f_p)
    return n.get("shapes_per_phase") == f.get("shapes_per_phase")


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
    slot["protocol_matched"] = _protocol_matched(n, f)
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


def audit(base: Path = BASE, band_pct: Optional[float] = None,
          protocol_basis: str = "family") -> Dict[str, Any]:
    """Classify every cell in both arms.

    ``native`` is the whole native corpus and ``floor`` the recalled gfx900
    reference chain; both come from :func:`arm_record_sets`.
    ``protocol_basis`` is the like-for-like rule (§R56.3, default "family"):
    the cells classified and graded admit only records stamped with that
    invocation form, on both arms -- the form the floor itself is measured
    under. The records the basis excludes are counted, not dropped: the
    result carries a ``protocol_census`` so the exclusion stays legible.
    """
    native, floor, chain = arm_record_sets(base)
    census = {"native": protocol_census(native),
              "spoof": protocol_census(floor)}

    native_b = _records_in_basis(native, protocol_basis)
    floor_b = _records_in_basis(floor, protocol_basis)

    measured_b = measured_band(native_b, floor_b, band_pct)
    band = measured_b["band_pct"]
    # `cross_arm` is recorded in the band payload for the report but is not
    # read here, so it is indexed out of the destructuring rather than bound.
    repeat = measured_b["repeat_dispersion"]

    cells = _best_by_cell(native_b, floor_b)
    for slot in cells.values():
        _grade_slot(slot, band)

    return {
        "protocol_basis": protocol_basis,
        "protocol_census": census,
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
    print(f"basis       : {result.get('protocol_basis', '?')} "
          f"(census native={result.get('protocol_census', {}).get('native')}, "
          f"floor={result.get('protocol_census', {}).get('spoof')})")
    print(f"tie band    : +/-{result['band_pct']:.1f}% "
          f"({result['band_source']}; shipped default "
          f"+/-{result['shipped_band_pct']:.1f}%)")
    cross = rb.get("cross_arm") or {}
    for label, key in (("protocol-matched  ", "protocol_matched"),
                       ("protocol-mismatched", "protocol_mismatched")):
        s = cross.get(key) or {}
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
    ap.add_argument("--protocol-basis", default="family",
                    choices=("family", "any", "single", "partial"),
                    help="the invocation form the graded cells admit "
                         "(§R56.3; default family, the form the floor is "
                         "measured under; 'any' = the legacy unfiltered view)")
    args = ap.parse_args()

    result = audit(base=args.base_dir, band_pct=args.band,
                   protocol_basis=args.protocol_basis)
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
