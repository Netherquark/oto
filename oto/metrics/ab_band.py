#!/usr/bin/env python3
"""The acceptance band: how large a gap has to be before it is real.

Owns: ``reproducible_band`` (cross-arm disagreement on identical configs),
``repeat_dispersion`` (raw repeat spread within one config), ``verdict`` and
``measured_band`` (the band and where each component came from), plus the
percentile helper and the shipped tie band that is only a floor.
Does NOT own: the records the band is measured from (`oto.metrics.ab_records`) or
the audit that reports it (`oto.metrics.ab_audit`).
Public API: reproducible_band, repeat_dispersion, verdict, measured_band,
TIE_BAND_PCT, BAND_LO, BAND_HI.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from oto.metrics.ab_identity import _pair_key
from oto.metrics.measurement_protocol import SINGLE, UNKNOWN


def _form_key(rec: dict[str, Any]) -> Any:
    """The group form: the stamped protocol, else the legacy count.

    UNKNOWN stamps group together (they are the same honest absence of
    information), which is the pre-§R56.3 behavior for count==0 rows.
    """
    p = rec.get("protocol")
    if p is None:
        return rec.get("shapes_per_phase")
    return p if p != UNKNOWN else rec.get("shapes_per_phase")

#: The census thresholds; the tie band that supersedes them lives here too.


# Shipped tie band. Reproducible-band measurement supersedes it where the corpus
# supports one; see reproducible_band().
TIE_BAND_PCT = 5.0

# Percentile span reported as the reproducible envelope.
BAND_LO, BAND_HI = 10, 90

def _pct(values: list[float], p: float) -> float:
    """The `p`-th percentile (nearest-rank) of `values`."""
    return sorted(values)[min(len(values) - 1, int(p / 100.0 * len(values)))]


def _same_form(nrec: dict[str, Any], frec: dict[str, Any]) -> bool:
    """Do two records' invocations have the same form (§R56.3)?

    Stamped protocols decide when either side carries one (the canonical
    classifier); a call whose records carry only the older
    ``shapes_per_phase`` count falls back to count equality. A stamp versus
    UNKNOWN is honestly not same-form -- UNKNOWN can neither be asserted to
    match nor mismatch.
    """
    n_p, f_p = nrec.get("protocol"), frec.get("protocol")
    if n_p is not None or f_p is not None:
        return n_p == f_p
    return nrec.get("shapes_per_phase") == frec.get("shapes_per_phase")


def reproducible_band(native: list[dict[str, Any]],
                      floor: list[dict[str, Any]]) -> dict[str, Any]:
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
        """Group records by pair key."""
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
        same_form = _same_form(nrecs[0], frecs[0])
        (matched if same_form else mismatched).append(ratio)

    def summarise(vals: list[float]) -> dict[str, Any]:
        """Summarise a list of arm ratios into band stats."""
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


def repeat_dispersion(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread of repeated measurements of one config under one form.

    Groups by (run, dtype, shape, kernel_key, form) -- everything a legitimate
    repeat is allowed to share -- and reports the distribution of within-group
    coefficient of variation. This is the real noise floor, and it is far above
    the shipped default: repeats of an identical kernel at an identical shape
    can reach a CV comparable to the gap being judged. A verdict whose margin
    sits inside that tail is not evidence. The form key is the stamped
    protocol (§R56.3) falling back to the older shapes_per_phase count.
    """
    groups: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for r in recs:
        v = r.get("GFLOPS") or 0.0
        if v <= 0:
            continue
        groups[(r.get("source_run"),
                r.get("DataType") or r.get("dtype") or "",
                r.get("ProblemType") or r.get("shape") or "",
                r.get("kernel_key"), _form_key(r))].append(v)
    cvs: list[float] = []
    worst: dict[str, float] = {}
    for key, vals in groups.items():
        if len(vals) < 2:
            continue
        mean = statistics.mean(vals)
        if mean <= 0:
            continue
        cv = statistics.pstdev(vals) / mean * 100.0
        cvs.append(cv)
        form = "single" if key[4] in (SINGLE, 1) else "multi"
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
    """WIN / LOSS / TIE for `delta_pct` measured against `band_pct`."""
    if delta_pct > band_pct:
        return "WIN"
    if delta_pct < -band_pct:
        return "LOSS"
    return "TIE"


def measured_band(native: list[dict[str, Any]], floor: list[dict[str, Any]],
                  band_pct: float | None = None) -> dict[str, Any]:
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
