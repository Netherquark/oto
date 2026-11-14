#!/usr/bin/env python3
"""The status report builder: state assembly, ETA pricing and the report dict.

Owns: ``build_report`` and the assembly helpers it consumes
(``_load_ledger_state``, ``_plan_inputs``, ``_timing_inputs``, ``_price_plan``,
``_get_deck_size``, ``_calculate_elapsed``, ``_calculate_chain_span``,
``_build_estimate_dict`` and ``_build_plan_dict``).
Does NOT own: the registry/corpus read path (``oto.metrics.ledger_state``),
the plan it prices (``oto.metrics.run_plan``), or the renderer (render_status).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import oto.tensile.library as tlib
from oto import yamlio
from oto.device import loader as _loader
from oto.metrics._status_common import _jittery
from oto.metrics.ledger_state import (
    DB_REL,
    _load_ledger,
    _resolve_corpus,
    _resolve_latest_tags,
    _tally_chain,
    _tier_rows,
)
from oto.metrics.read_thermals import read_thermals
from oto.metrics.run_plan import (
    Estimate,
    PhaseCost,
    RunPlan,
    _reference_unit_count,
    _tuning_unit_count,
)
from oto.runners.paths import runs_dir as _runs_dir


def _price_plan(plan: RunPlan, minutes: float | None,
                elapsed: float | None, decided: int, units: int,
                breakdown: dict[str, Any], used: int, ref_remaining: int,
                tune_units: int, ref_done: int) -> Estimate:
    """The ETA estimate, with the jitter guard on its rate.

    Jitter check: when decided < 3 the per-phase median is unstable, so the ETA
    is set to None rather than printed as if it meant something. A confident
    number built on three samples is how a run gets budgeted wrongly.
    """
    # Jitter check: too few samples for a stable median ETA.
    # When decided < 3 the per-phase median is unstable and the ETA must
    # carry a visible bogus indicator so the user knows not to trust it.
    jitter = _jittery(decided) if decided is not None else False

    est = Estimate(
        units=units,
        minutes_per_unit=minutes,
        decided=ref_done,
        done_minutes=elapsed or 0.0,
        remaining=ref_remaining + tune_units,
        source=("measured" if plan.minutes_per_phase is None else "override") if minutes else "unknown",
        breakdown=breakdown,
        rate_sample=used,
    )
    if minutes and minutes > 0:
        est.eta_minutes = est.remaining * minutes
    elif elapsed and decided:
        est.eta_minutes = (elapsed / decided) * est.remaining

    # Flag when ETA is based on an unstable median (fewer than 3 decided phases)
    if jitter:
        est.eta_minutes = None  # type: ignore[assignment]
    return est


def _load_ledger_state(base: Path, run_id: str | None) -> dict[str, Any]:
    """Registry + corpus + manifest state the status panel reports from."""
    db = base / DB_REL
    if not db.exists():
        raise SystemExit(f"no registry at {db}")

    ledger = _load_ledger(db, run_id)
    manifest = tlib.load_rerun_manifest(base)
    corpus, tag_to_key = _resolve_corpus(base)
    if tag_to_key:
        _resolve_latest_tags(ledger["latest"], ledger["unkeyed"], tag_to_key)
    tally, decided, stale_ids = _tally_chain(ledger["latest"], ledger["unkeyed"])

    return {
        "db": db,
        "chain": ledger["chain"],
        "status_by_run": ledger["status_by_run"],
        "started_by_run": ledger["started_by_run"],
        "completed_by_run": ledger["completed_by_run"],
        "latest": ledger["latest"],
        "unkeyed": ledger["unkeyed"],
        "first_start": ledger["first_start"],
        "last_event": ledger["last_event"],
        "manifest": manifest,
        "corpus": corpus,
        "tally": tally,
        "decided": decided,
        "stale_ids": stale_ids,
    }


def _plan_inputs(state: dict[str, Any], base: Path,
                 plan: RunPlan) -> dict[str, Any]:
    """Plan scope (units) and the phase-cost rate the ETA is priced from."""
    deck_size = _get_deck_size(base, plan)
    ref_units, breakdown = _reference_unit_count(
        plan, state["manifest"], state["corpus"])
    tune_units = _tuning_unit_count(plan, deck_size)
    rate, n_samples, used = PhaseCost(state["db"]).sample()
    minutes = plan.minutes_per_phase or rate
    return {
        "deck_size": deck_size,
        "ref_units": ref_units,
        "breakdown": breakdown,
        "tune_units": tune_units,
        "rate": rate,
        "minutes": minutes,
        "n_samples": n_samples,
        "used": used,
    }


def _timing_inputs(state: dict[str, Any],
                   now: datetime | None) -> dict[str, float]:
    """Elapsed (head run only) and the chain's wall-clock span."""
    return {
        "elapsed": _calculate_elapsed(state["chain"], state["started_by_run"],
                                      state["completed_by_run"], now),
        "chain_span": _calculate_chain_span(
            state["chain"], state["first_start"], state["last_event"],
            state["started_by_run"], state["completed_by_run"]),
    }


def build_report(base: Path, run_id: str | None,
                 plan: RunPlan,
                 now: datetime | None = None, profile=None) -> dict[str, Any]:
    """Build the status report for a run.

    `now` overrides the wall clock used to age a still-running head run.
    """
    state = _load_ledger_state(base, run_id)
    chain = state["chain"]
    pin = _plan_inputs(state, base, plan)
    timing = _timing_inputs(state, now)

    tier_rows, ref_done, ref_total, ref_remaining = _tier_rows(
        state["corpus"], state["latest"], plan)
    est = _price_plan(plan, pin["minutes"], timing["elapsed"], state["decided"],
                      ref_total + pin["tune_units"], pin["breakdown"],
                      pin["used"], ref_remaining, pin["tune_units"], ref_done)

    thermals = read_thermals(_runs_dir(base, _loader.resolve_profile(profile,).codename) / (chain[-1] if chain else "")) if chain else None
    started_live = state["status_by_run"].get(chain[-1] if chain else "",) == "started"

    return {
        "chain": chain,
        "head": chain[-1] if chain else "",
        "head_status": state["status_by_run"].get(chain[-1] if chain else "", "unknown",),
        "in_flight": started_live,
        "corpus": len(state["corpus"]),
        "tally": state["tally"],
        "decided": state["decided"],
        "tier_rows": tier_rows,
        "ref_total": ref_total,
        "ref_done": ref_done,
        "ref_remaining": ref_remaining,
        "tuning_tracked": False,
        "elapsed_minutes": timing["elapsed"],
        "chain_span_minutes": timing["chain_span"],
        "stale_records": state["stale_ids"],
        "estimate": _build_estimate_dict(est, pin["breakdown"],
                                         pin["tune_units"], pin["deck_size"],
                                         pin["rate"], pin["n_samples"]),
        "plan": _build_plan_dict(plan),
        "thermals": thermals,
    }


def _get_deck_size(base: Path, plan: RunPlan) -> int:
    """Get deck size from plan or phases.yaml."""
    deck_size = plan.deck_size
    if not deck_size:
        deck_path = base / "phases.yaml"
        if deck_path.is_file():
            try:
                doc = yamlio.load_yaml(deck_path) or []
                deck_size = len(doc) if isinstance(doc, list) else 0
            except Exception:
                deck_size = 0
    return deck_size

def _calculate_elapsed(
    chain: list[str],
    started_by_run: dict,
    completed_by_run: dict,
    now: datetime | None
) -> float | None:
    """Calculate elapsed minutes for the head run."""
    head = chain[-1] if chain else ""
    head_start = started_by_run.get(head) if head else None
    head_end = completed_by_run.get(head) if head else None
    if head_start and head_end and head_end >= head_start:
        return (head_end - head_start).total_seconds() / 60.0
    if head_start:
        clock = now if now is not None else datetime.now(head_start.tzinfo)
        return max((clock - head_start).total_seconds() / 60.0, 0.0)
    return None

def _calculate_chain_span(
    chain: list[str],
    first_start: datetime | None,
    last_event: datetime | None,
    started_by_run: dict,
    completed_by_run: dict
) -> float | None:
    """Calculate chain span in minutes with multiple fallbacks."""
    if first_start and last_event and last_event > first_start:
        return (last_event - first_start).total_seconds() / 60.0
    if first_start and len(chain) > 1:
        ends = [completed_by_run.get(r) for r in chain]
        ends = [e for e in ends if e]
        if ends:
            newest = max(ends)
            if newest > first_start:
                return (newest - first_start).total_seconds() / 60.0
    if len(chain) > 1:
        starts = [started_by_run.get(r) for r in chain]
        starts = [s for s in starts if s]
        if starts and max(starts) > min(starts):
            return ((max(starts) - min(starts)).total_seconds() / 60.0)
    return None

def _build_estimate_dict(est, breakdown, tune_units, deck_size, rate, n_samples) -> dict:
    """Build the estimate dictionary."""
    return {
        "units": est.units,
        "decided": est.decided,
        "remaining": est.remaining,
        "percent": est.percent,
        "minutes_per_unit": est.minutes_per_unit,
        "rate_per_hour": est.rate_per_hour,
        "eta_minutes": est.eta_minutes,
        "source": est.source,
        "breakdown": breakdown,
        "tuning_units": tune_units,
        "deck_size": deck_size,
        "rate_sample": est.rate_sample,
        "rate_sample_n": n_samples,
    }

def _build_plan_dict(plan: RunPlan) -> dict:
    """Build the plan dictionary."""
    return {
        "rerun_illegal": plan.rerun_illegal,
        "rerun_underspecified": plan.rerun_underspecified,
        "rerun_unreproducible": plan.rerun_unreproducible,
        "iterations": plan.iterations,
        "mutations": plan.mutations,
    }
