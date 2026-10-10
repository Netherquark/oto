#!/usr/bin/env python3
"""The acceptance band: how large a gap has to be before it is real.

Owns: ``reproducible_band`` (cross-arm disagreement on identical configs),
``repeat_dispersion`` (raw repeat spread within one config), ``verdict`` and
``measured_band`` (the band and where each component came from), plus the
percentile helper and the shipped tie band that is only a floor.
Does NOT own: the records the band is measured from (oto.metrics.ab_records) or
the audit that reports it (oto.metrics.ab_audit).
Public API: reproducible_band, repeat_dispersion, verdict, measured_band,
TIE_BAND_PCT, BAND_LO, BAND_HI.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from oto.metrics.ab_identity import _pair_key
from oto.metrics.analytics import extract_family_from_phase_id
from oto.device.peaks import cell_key
from oto.metrics.policy import aggregate_cell

#: The census thresholds; the tie band that supersedes them lives here too.


# Shipped tie band. Reproducible-band measurement supersedes it where the corpus
# supports one; see reproducible_band().
TIE_BAND_PCT = 5.0

# Percentile span reported as the reproducible envelope.
BAND_LO, BAND_HI = 10, 90

def _pct(values: List[float], p: float) -> float:
    return sorted(values)[min(len(values) - 1, int(p / 100.0 * len(values)))]


def reproducible_band(native: List[Dict[str, Any]],
                      floor: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Noise floor implied by configurations measured in *both* arms.

    Keyed on (dtype, shape, fingerprint), so a configuration that appears in the
    native arm and the floor arm at the same cell contributes the ratio of its
    two measurements. Nothing about kernel quality can move that ratio, so its
    spread is pure measurement disagreement plus any real difference between the
    two arms' protocols. Restricted to cells where both sides agree on
    invocation form, because otherwise the spread measures the protocol rather
    than the noise.
    """
    def index(recs):
        out = defaultdict(list)
        for r in recs:
            out[_pair_key(r)].append(r)
        return out

    nidx, fidx = index(native), index(floor)
    matched, mismatched = [], []
    for key, nrecs in nidx.items():
        frecs = fidx.get(key)
        if not frecs:
            continue
        nr = statistics.median([r["GFLOPS"] for r in nrecs])
        fr = statistics.median([r["GFLOPS"] for r in frecs])
        if fr <= 0:
            continue
        ratio = nr / fr
        same_form = (nrecs[0]["shapes_per_phase"] == frecs[0]["shapes_per_phase"])
        (matched if same_form else mismatched).append(ratio)

    def summarise(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"n": 0}
        return {
            "n": len(vals),
            "median_ratio": statistics.median(vals),
            "p10_ratio": _pct(vals, BAND_LO),
            "p90_ratio": _pct(vals, BAND_HI),
            "band_pct": max(abs(1 - _pct(vals, BAND_LO)),
                            abs(_pct(vals, BAND_HI) - 1)) * 100.0,
            "share_within_shipped_band": sum(
                1 for v in vals if abs(v - 1) <= TIE_BAND_PCT / 100.0)
            / len(vals),
        }

    return {"protocol_matched": summarise(matched),
            "protocol_mismatched": summarise(mismatched)}


def repeat_dispersion(recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Spread of repeated measurements of one config under one form.

    Groups by (run, dtype, shape, kernel_key, form) -- everything a legitimate
    repeat is allowed to share -- and reports the distribution of within-group
    coefficient of variation. This is the real noise floor, and it is far above
    the shipped default: repeats of an identical kernel at an identical shape
    reach 36% CV for single-shape phases and 65% for multi-shape ones. A verdict
    whose margin sits inside that tail is not evidence.
    """
    groups: Dict[Tuple[Any, ...], List[float]] = defaultdict(list)
    for r in recs:
        v = r.get("GFLOPS") or 0.0
        if v <= 0:
            continue
        groups[(r.get("source_run"), r["DataType"], r["ProblemType"],
                r.get("kernel_key"), r.get("shapes_per_phase"))].append(v)
    cvs: List[float] = []
    worst: Dict[str, float] = {}
    for key, vals in groups.items():
        if len(vals) < 2:
            continue
        mean = statistics.mean(vals)
        if mean <= 0:
            continue
        cv = statistics.pstdev(vals) / mean * 100.0
        cvs.append(cv)
        form = "single" if key[4] == 1 else "multi"
        worst[form] = max(worst.get(form, 0.0), cv)
    if not cvs:
        return {"n": 0}
    return {
        "n": len(cvs),
        "median_cv_pct": statistics.median(cvs),
        "p90_cv_pct": _pct(cvs, BAND_HI),
        "max_cv_pct": max(cvs),
        "max_cv_single_pct": worst.get("single", 0.0),
        "max_cv_multi_pct": worst.get("multi", 0.0),
    }


def verdict(delta_pct: float, band_pct: float = TIE_BAND_PCT) -> str:
    if delta_pct > band_pct:
        return "WIN"
    if delta_pct < -band_pct:
        return "LOSS"
    return "TIE"


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
