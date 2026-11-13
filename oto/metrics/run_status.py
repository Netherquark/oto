#!/usr/bin/env python3
"""Run status: the report builder, the renderers and the live panel.

Owns: ``build_report`` (the whole status dict for a run/plan/chain), the text
renderings of it (``render_compact``, ``render``, ``bar``), and ``LiveStatus``
with ``_PanelStdout`` -- the background-threaded TTY repainter and the stdout
proxy that erases the panel before any other write.
Does NOT own: the plan it prices (oto.metrics.run_plan), the thermal envelope it
cites (oto.metrics.read_thermals), or the driver that starts it
(oto.runners.driver).
Public API: RunPlan / PhaseCost / Estimate (re-exported), build_report, bar,
render_compact, render, LiveStatus, _PanelStdout, fmt_duration, bucket,
_parse_ts, _jittery, read_thermals, main.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import oto.device.peaks as _peaks
import oto.tensile.library as tlib
from oto import yamlio

# Re-exported for the pre-split import surface; the implementations live in
# oto.metrics.read_thermals / oto.metrics.run_plan.
from oto.metrics.read_thermals import read_thermals
from oto.metrics.render_status import (
    LiveStatus,
    _PanelStdout,
    bar,
    main,
    render,
    render_compact,
)
from oto.metrics.run_plan import (
    Estimate,
    PhaseCost,
    RunPlan,
    _reference_unit_count,
    _tuning_unit_count,
)
from oto.runners.paths import results_rel
from oto.runners.paths import runs_dir as _runs_dir

#: The registry's path relative to the project root.
DB_REL = Path(results_rel("registry.db"))

#: A run is "in flight" while it is the newest one and has no completed_at.
ACTIVE_STATES = ("started", "interrupted")

__all__ = [
    "Estimate",
    "LiveStatus",
    "PhaseCost",
    "RunPlan",
    "_PanelStdout",
    "_jittery",
    "_parse_ts",
    "bar",
    "bucket",
    "build_report",
    "fmt_duration",
    "main",
    "read_thermals",
    "render",
    "render_compact",
]

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def fmt_duration(minutes: float | None) -> str:
    """Human duration, coarse on purpose: an ETA to the second is a lie."""
    if minutes is None or minutes != minutes or minutes == float("inf"):
        return "unknown"
    if minutes < 0:
        return "unknown"
    if minutes < 1:
        return f"{minutes * 60:.0f}s"
    if minutes < 90:
        return f"{minutes:.0f}m"
    hours = minutes / 60.0
    if hours < 48:
        return f"{int(hours)}h {int(minutes % 60)}m"
    return f"{int(hours // 24)}d {int(hours % 24)}h"


def _jittery(n: int) -> bool:
    """Too few samples for a stable median."""
    return n < 3


def bucket(status: str, result: str | None) -> str:
    """Map a record's (status, result.status) onto one display bucket.

    `result.status` is NULL for records that never got that far (Tensile
    rejected every solution, or the process died), and those are failures, not
    "unknown" -- counting them as anything else would understate a failed run.
    """
    if status == "completed" and result == "success":
        return "success"
    if status == "skipped" or (status == "failed" and result == "skipped_by_user"):
        return "skipped"
    if status == "failed":
        return "failed"
    if status in ("started", "running"):
        return "active"
    return "other"


# ---------------------------------------------------------------------------
# main report
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# status-report sub-builders
# ---------------------------------------------------------------------------


def _load_ledger(db: Path, run_id: str | None) -> dict[str, Any]:
    """Every run row and its general verdicts, in one read of the registry.

    Returns the per-run indexes, the resolved chain, the chain's latest
    per-phase verdict map, the unkeyed ids, and the chain's first_start / last_event span.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    out: dict[str, Any] = {
        "status_by_run": {}, "started_by_run": {}, "completed_by_run": {},
        "meta_by_run": {}, "row_id": {}, "all_ids": [], "chain": [],
        "latest": {}, "unkeyed": set(), "first_start": None,
        "last_event": None,
    }
    status_by_run, started_by_run, completed_by_run, meta_by_run, row_id = _load_runs_data(conn, out)
    out["all_ids"] = _sort_runs_by_started(status_by_run, started_by_run, row_id)

    if run_id:
        out["chain"] = _build_chain_from_run_id(run_id, meta_by_run, status_by_run)
    else:
        out["chain"] = _build_chain_auto(status_by_run, started_by_run, completed_by_run,
                                         meta_by_run, out["all_ids"])

    _process_chain_records(conn, out["chain"], status_by_run, started_by_run,
                           completed_by_run, meta_by_run, out)

    return out

def _load_runs_data(conn, out: dict) -> tuple:
    """Load runs data from database into out dict. Returns tuple of dicts."""
    rows = conn.execute(
        "SELECT id, run_id, status, started_at, completed_at, metadata "
        "FROM runs ORDER BY id DESC").fetchall()
    for r in rows:
        rid = str(r["run_id"])
        out["status_by_run"][rid] = str(r["status"])
        out["started_by_run"][rid] = _parse_ts(r["started_at"])
        out["completed_by_run"][rid] = _parse_ts(r["completed_at"])
        out["row_id"][rid] = int(r["id"])
        try:
            out["meta_by_run"][rid] = json.loads(r["metadata"]) if r["metadata"] else {}
        except ValueError:
            out["meta_by_run"][rid] = {}
    return (out["status_by_run"], out["started_by_run"], out["completed_by_run"],
            out["meta_by_run"], out["row_id"])

def _sort_runs_by_started(status_by_run: dict, started_by_run: dict, row_id: dict) -> list:
    """Sort all runs by started_at (newest first), tie-break by row_id."""
    return sorted(
        status_by_run,
        key=lambda r: (started_by_run.get(r) or datetime.min.replace(tzinfo=UTC), row_id[r]),
        reverse=True
    )

def _build_chain_from_run_id(run_id: str, meta_by_run: dict, status_by_run: dict) -> list[str]:
    """Build chain from explicit run_id and its resume_of ancestors."""
    if run_id not in status_by_run:
        raise SystemExit(f"unknown run {run_id!r}")
    chain = [run_id]
    seen = {run_id}
    cur = run_id
    while True:
        parent = (meta_by_run.get(cur) or {}).get("resume_of")
        if not parent or parent in seen:
            break
        seen.add(parent)
        chain.append(str(parent))
        cur = str(parent)
    chain.reverse()
    return chain

def _build_chain_auto(
    status_by_run: dict, started_by_run: dict, completed_by_run: dict,
    meta_by_run: dict, all_ids: list[str]
) -> list[str]:
    """Auto-detect chain: in-flight > completed > interrupted, then ancestors."""
    chain = []
    # Priority: 1) in-flight (no completed_at), 2) completed, 3) interrupted
    for cand in ([rid for rid in all_ids if completed_by_run.get(rid) is None],
                 [rid for rid in all_ids if status_by_run[rid] == "completed"],
                 [rid for rid in all_ids if status_by_run[rid] in ACTIVE_STATES]):
        if cand:
            chain = [cand[0]]
            break
    if not chain and all_ids:
        chain = [all_ids[0]]
    seen = set(chain)
    cur = chain[0] if chain else None
    while cur:
        parent = (meta_by_run.get(cur) or {}).get("resume_of")
        if not parent or parent in seen or parent not in status_by_run:
            break
        seen.add(parent)
        chain.append(str(parent))
        cur = str(parent)
    chain.reverse()
    return chain

def _process_chain_records(
    conn, chain: list[str], status_by_run: dict, started_by_run: dict,
    completed_by_run: dict, meta_by_run: dict, out: dict
) -> None:
    """Process records for all runs in the chain."""
    latest: dict[str, tuple[str, str | None]] = {}
    unkeyed: set = set()
    first_start: datetime | None = None
    last_event: datetime | None = None

    for rid in chain:
        st = started_by_run.get(rid)
        if st and (first_start is None or st < first_start):
            first_start = st
        if st and (last_event is None or st > last_event):
            last_event = st
        for (data, ts) in conn.execute(
                "SELECT data, timestamp FROM records WHERE run_id = ? "
                "AND record_type = 'general'", (rid,)):
            try:
                o = json.loads(data)
            except ValueError:
                continue
            if not o.get("phase_id"):
                continue
            when = _parse_ts(ts)
            if when and (last_event is None or when > last_event):
                last_event = when
            kernel = o.get("kernel") or o.get("solution") or ""
            key = o.get("phase_key")
            if not key:
                if kernel:
                    key = tlib.phase_key({"kernel": kernel})
                else:
                    unkeyed.add(str(o["phase_id"]))
                    key = "pid:" + str(o["phase_id"])
            latest[str(key)] = (str(o.get("status") or ""),
                                (o.get("result") or {}).get("status"))
    out["latest"] = latest
    out["unkeyed"] = unkeyed
    out["first_start"] = first_start
    out["last_event"] = last_event


def _resolve_corpus(base: Path, arch: str = "gfx900"
                     ) -> tuple[dict[str, str], dict[str, str]]:
    """The phase_key -> tier map for the reference corpus, and its tag map.

    The tag map resolves records written before `phase_key` existed (both
    2026-09-25/26 reference runs) to the name they are now spelled with.
    Resolving before tallying matters: counting first read 2298 decided
    against a 2285-cell corpus, because 158 phase_ids are pre-fix spellings
    of keys already counted under their current name.
    """
    manifest = tlib.load_rerun_manifest(base)
    corpus: dict[str, str] = {}
    #: phase_id trailing tag -> phase_key, for records that predate phase_key
    tag_to_key: dict[str, str] = {}
    shipped = tlib.load_shipped_manifest(base, refresh=False)
    if not shipped:
        return corpus, tag_to_key
    # The reference corpus naming convention is <arch>_ref_*; only the
    # gfx900 corpus exists today, hence the default. The profile-driven
    # path lives in oto/runners/reference.py.
    for phase in tlib.emit_spoof_phases(shipped, arch=arch):
        key = tlib.phase_key(phase)
        corpus[key] = tlib.tier_for(phase, manifest)
        pid = str(phase.get("phase_id") or "")
        if pid:
            tag_to_key[pid.rsplit("-", 1)[-1]] = key
    return corpus, tag_to_key


def _resolve_latest_tags(latest: dict[str, Any], unkeyed: set,
                         tag_to_key: dict[str, str]) -> None:
    """Fold pre-phase_key records onto their current key, in place.

    Also drops the folded ids from `unkeyed`: they are no longer stale, they
    are accounted for under the key they were resolved to.
    """
    for key in list(latest):
        if not key.startswith("pid:"):
            continue
        tag = key.rsplit("-", 1)[-1]
        if tag in tag_to_key:
            latest[tag_to_key[tag]] = latest.pop(key)
            unkeyed.discard(str(key)[4:])


def _tally_chain(latest: dict[str, tuple[str, str | None]],
                 unkeyed: set) -> tuple[dict[str, int], int, int]:
    """Bucket the chain's per-phase verdicts; count what is decided.

    An unresolved pid is skipped, not counted as decided: it has no corpus
    identity, so counting it would let a record that cannot be placed inflate
    the numerator above the corpus size -- the exact failure this tool is
    meant to rule out. It is surfaced as `stale_records` instead.
    """
    tally = dict.fromkeys(("success", "failed", "skipped", "active", "other"), 0)
    for key, (status, result) in latest.items():
        if key.startswith("pid:"):
            continue
        tally[bucket(status, result)] += 1
    decided = tally["success"] + tally["failed"]
    stale_ids = len(unkeyed)
    return tally, decided, stale_ids


def _tier_rows(corpus: dict[str, str],
               latest: dict[str, tuple[str, str | None]],
               plan: RunPlan
               ) -> tuple[list[tuple[str, int, int]], int, int, int]:
    """Per-tier (label, done, total) rows, and the plan's released counts.

    Progress is per-tier, not "decided over everything": the chain has already
    decided the whole corpus, so dividing that by the plan's released units
    would report >100%. What the user asked is: of the tiers this plan
    released, how many still owe a verdict. So count decided per tier and
    subtract within the tier.

    Returns:
        ``(tier_rows, ref_done, ref_total, ref_remaining)``.
    """
    tier_total: dict[str, int] = {}
    for tier in corpus.values():
        tier_total[tier] = tier_total.get(tier, 0) + 1
    tier_decided: dict[str, int] = {}
    for key, (status, result) in latest.items():
        tier = corpus.get(key)
        if not tier:
            continue
        if bucket(status, result) in ("success", "failed"):
            tier_decided[tier] = tier_decided.get(tier, 0) + 1

    released = {tier for tier, on in (
        (tlib.TIER_FIRST, plan.rerun_illegal),
        (tlib.TIER_HELD, plan.rerun_underspecified),
        (tlib.TIER_LAST, plan.rerun_underspecified),
        (tlib.TIER_DROP, plan.rerun_unreproducible)) if on}
    ref_total = 0
    ref_done = 0
    tier_rows: list[tuple[str, int, int]] = []
    label = {tlib.TIER_FIRST: "ILLEGAL", tlib.TIER_HELD: "UNDER-SPECIFIED",
             tlib.TIER_LAST: "UNDER-SPECIFIED (legacy)",
             tlib.TIER_DROP: "UNREPRODUCIBLE"}
    for tier in (tlib.TIER_FIRST, tlib.TIER_HELD, tlib.TIER_LAST, tlib.TIER_DROP):
        total = tier_total.get(tier, 0)
        if not total:
            continue
        done = min(tier_decided.get(tier, 0), total)
        tier_rows.append((label.get(tier, tier), done, total))
        if tier in released:
            ref_total += total
            ref_done += done
    return tier_rows, ref_done, ref_total, ref_total - ref_done


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
                 now: datetime | None = None) -> dict[str, Any]:
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

    thermals = read_thermals(_runs_dir(base, _peaks.CODENAME) / (chain[-1] if chain else "")) if chain else None
    started_live = state["status_by_run"].get(chain[-1] if chain else "") == "started"

    return {
        "chain": chain,
        "head": chain[-1] if chain else "",
        "head_status": state["status_by_run"].get(chain[-1] if chain else "", "unknown"),
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
