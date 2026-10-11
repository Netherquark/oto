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

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import oto.tensile.library as tlib  # noqa: E402

# Re-exported for the pre-split import surface; the implementations live in
# oto.metrics.read_thermals / oto.metrics.run_plan.
from oto.metrics.read_thermals import read_thermals
from oto.metrics.render_status import (LiveStatus, _PanelStdout, bar,
                                       render, render_compact)
from oto.metrics.run_plan import (Estimate, PhaseCost, RunPlan,
                                  _reference_unit_count, _tuning_unit_count)

#: The registry's path relative to the project root.
DB_REL = Path("gfx90c_results") / "registry.db"

#: A run is "in flight" while it is the newest one and has no completed_at.
ACTIVE_STATES = ("started", "interrupted")

__all__ = ["RunPlan", "PhaseCost", "Estimate", "build_report", "bar",
           "render_compact", "render", "LiveStatus", "_PanelStdout",
           "fmt_duration", "bucket", "_parse_ts", "_jittery",
           "read_thermals", "main"]

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def fmt_duration(minutes: Optional[float]) -> str:
    """Human duration, coarse on purpose: an ETA to the second is a lie."""
    if minutes is None or minutes != minutes or minutes in (float("inf"),):
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


def bucket(status: str, result: Optional[str]) -> str:
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
def build_report(base: Path, run_id: Optional[str],
                 plan: RunPlan,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Build the status report for a run.

    `now` overrides the wall clock used to age a still-running head run. It
    exists so callers (and tests) can pin the clock: a head run with no
    completed_at is aged against real time, so a fixture pinned to a literal
    timestamp silently starts failing once the calendar moves past it.
    Defaults to the system clock, so production behavior is unchanged.
    """
    db = base / DB_REL
    if not db.exists():
        raise SystemExit(f"no registry at {db}")

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, run_id, status, started_at, completed_at, metadata "
            "FROM runs ORDER BY id DESC").fetchall()
        meta_by_run: Dict[str, Dict[str, Any]] = {}
        status_by_run: Dict[str, str] = {}
        started_by_run: Dict[str, Optional[datetime]] = {}
        completed_by_run: Dict[str, Optional[datetime]] = {}
        row_id: Dict[str, int] = {}
        for r in rows:
            rid = str(r["run_id"])
            status_by_run[rid] = str(r["status"])
            started_by_run[rid] = _parse_ts(r["started_at"])
            completed_by_run[rid] = _parse_ts(r["completed_at"])
            row_id[rid] = int(r["id"])
            try:
                meta_by_run[rid] = json.loads(r["metadata"]) if r["metadata"] else {}
            except ValueError:
                meta_by_run[rid] = {}

        # All runs, newest by started_at first (ties fall back to id so the
        # order is total). The default head is the newest run of ANY kind --
        # native tuning runs are the primary workflow now; the gfx900_ref_*
        # floor chain is just one kind of run. Resumes are not always inserted
        # in the order they started, so picking by id would report a stale
        # ancestor as the head.
        all_ids = sorted(
            status_by_run,
            key=lambda r: (started_by_run.get(r) or datetime.min.replace(
                tzinfo=timezone.utc), row_id[r]),
            reverse=True)

        # The chain: newest run, plus its resume_of ancestors.
        if run_id:
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
        else:
            # Precedence, highest first:
            #   1. a run still in flight (no completed_at)
            #   2. the newest *completed* run -- authoritative, not resumable
            #   3. the newest finished-but-interrupted run
            #
            # In flight is decided by completed_at, not by the status label. An
            # interrupted run that never closed is resumable work and belongs at
            # the head; one that did close is history. Treating every
            # 'interrupted' run as active walked straight past the floor locked
            # five days later and stopped on a run that had been closed for
            # eight, so the default view described a stale chain and every tier
            # count and ETA it printed came from the wrong corpus.
            chain = []
            for cand in ([rid for rid in all_ids
                          if completed_by_run.get(rid) is None],
                         [rid for rid in all_ids
                          if status_by_run[rid] == "completed"],
                         [rid for rid in all_ids
                          if status_by_run[rid] in ACTIVE_STATES]):
                if cand:
                    chain = [cand[0]]  # all_ids is newest started_at first
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

        # Latest state per phase across the chain: a phase decided in an
        # ancestor counts even if a resume re-listed it, and a phase re-run in a
        # resume counts once with the newer verdict.
        #
        # Keyed by phase_key, not phase_id. phase_id embeds knobs our parsers
        # derive, so a parser fix renames every phase; the same kernel then
        # appears under two ids and a raw phase_id count exceeds the corpus (it
        # read 2298 decided against a 2285-cell corpus). The records themselves
        # carry the kernel, so hash that -- the same identity the tier manifest
        # and the A/B recall use.
        latest: Dict[str, Tuple[str, Optional[str]]] = {}
        unkeyed: set = set()
        first_start: Optional[datetime] = None
        last_event: Optional[datetime] = None
        for rid in chain:
            st = started_by_run.get(rid)
            if st and (first_start is None or st < first_start):
                first_start = st
            # A run's start is itself an event in the chain's timeline. Without
            # this, a chain whose newest run has not yet written a record ends
            # at the previous run's last record and the span silently shrinks.
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
                        # No identity to key on: count it separately so the
                        # corpus/decided gap stays visible rather than silently
                        # inflating the numerator.
                        unkeyed.add(str(o["phase_id"]))
                        key = "pid:" + str(o["phase_id"])
                latest[str(key)] = (str(o.get("status") or ""),
                                    (o.get("result") or {}).get("status"))
    finally:
        conn.close()

    manifest = tlib.load_rerun_manifest(base)
    shipped = tlib.load_shipped_manifest(base, refresh=False)
    corpus: Dict[str, str] = {}
    #: phase_id trailing tag -> phase_key, for records that predate phase_key
    tag_to_key: Dict[str, str] = {}
    if shipped:
        for phase in tlib.emit_spoof_phases(shipped):
            key = tlib.phase_key(phase)
            corpus[key] = tlib.tier_for(phase, manifest)
            pid = str(phase.get("phase_id") or "")
            if pid:
                tag_to_key[pid.rsplit("-", 1)[-1]] = key

    # Records written before phase_key existed (both 2026-09-25/26 reference
    # runs) still carry the tag in phase_id, and every one of them resolves
    # through the emitted deck. Resolve before tallying: counting first read
    # 2298 decided against a 2285-cell corpus, because 158 phase_ids are
    # pre-fix spellings of keys already counted under their current name.
    if tag_to_key:
        for key in list(latest):
            if not key.startswith("pid:"):
                continue
            tag = key.rsplit("-", 1)[-1]
            if tag in tag_to_key:
                latest[tag_to_key[tag]] = latest.pop(key)
                unkeyed.discard(str(key)[4:])

    tally = {k: 0 for k in ("success", "failed", "skipped", "active", "other")}
    for key, (status, result) in latest.items():
        # An unresolved pid: key has no corpus identity, so it cannot be
        # attributed to a tier. Counting it in the global tally would let a
        # record we cannot place inflate the numerator above the corpus size --
        # the exact failure this tool is meant to rule out. It is surfaced as
        # stale_records instead.
        if key.startswith("pid:"):
            continue
        tally[bucket(status, result)] += 1
    decided = tally["success"] + tally["failed"]
    stale_ids = len(unkeyed)

    deck_size = plan.deck_size
    if not deck_size:
        deck_path = base / "phases.yaml"
        if deck_path.is_file():
            import yaml
            try:
                doc = yaml.safe_load(deck_path.read_text()) or []
                deck_size = len(doc) if isinstance(doc, list) else 0
            except Exception:
                deck_size = 0

    ref_units, breakdown = _reference_unit_count(plan, manifest, corpus)
    tune_units = _tuning_unit_count(plan, deck_size)

    rate, n_samples, used = PhaseCost(db).sample()
    minutes = plan.minutes_per_phase if plan.minutes_per_phase else rate

    # Elapsed is scoped to the head run, not the chain. The chain is three runs
    # and two days old in the current corpus, and reporting "3d elapsed" against
    # a plan the user is starting now makes the rate nonsense. The chain span is
    # reported separately as context.
    head = chain[-1] if chain else ""
    head_start = started_by_run.get(head) if head else None
    head_end = completed_by_run.get(head) if head else None
    if head_start and head_end and head_end >= head_start:
        elapsed = (head_end - head_start).total_seconds() / 60.0
    elif head_start:
        clock = now if now is not None else datetime.now(head_start.tzinfo)
        elapsed = max((clock - head_start).total_seconds() / 60.0, 0.0)
    else:
        elapsed = None
    chain_span = ((last_event - first_start).total_seconds() / 60.0
                  if first_start and last_event and last_event > first_start
                  else None)
    if chain_span is None and first_start and len(chain) > 1:
        # A run with no records at all leaves last_event unset. Fall back to the
        # newest completed_at in the chain so the span is still reported.
        ends = [completed_by_run.get(r) for r in chain]
        ends = [e for e in ends if e]
        if ends:
            newest = max(ends)
            if newest > first_start:
                chain_span = (newest - first_start).total_seconds() / 60.0
    if chain_span is None and len(chain) > 1:
        # Still nothing recorded: bound the span by the chain's own start times,
        # which exist for every run by construction.
        starts = [started_by_run.get(r) for r in chain]
        starts = [s for s in starts if s]
        if starts and max(starts) > min(starts):
            chain_span = ((max(starts) - min(starts)).total_seconds() / 60.0)

    # Progress must be per-tier, not "decided over everything". The chain has
    # already decided the whole corpus, so dividing that by the plan's 111
    # ILLEGAL units would report >100%, and dividing the plan's unit count by
    # the chain's decided count would understate what is left to do. What the
    # user asked is: of the tiers this plan released, how many still owe a
    # verdict. So count decided per tier and subtract within the tier.
    tier_total: Dict[str, int] = {}
    for tier in corpus.values():
        tier_total[tier] = tier_total.get(tier, 0) + 1
    tier_decided: Dict[str, int] = {}
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
    tier_rows: List[Tuple[str, int, int]] = []
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
    ref_remaining = ref_total - ref_done

    # Jitter check: too few samples for a stable median ETA.
    # When decided < 3 the per-phase median is unstable and the ETA must
    # carry a visible bogus indicator so the user knows not to trust it.
    jitter = _jittery(decided) if decided is not None else False

    est = Estimate(
        units=ref_total + tune_units,
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

    thermals = read_thermals(base / "gfx90c_runs" / head) if head else None
    started_live = status_by_run.get(head) == "started"

    return {
        "chain": chain,
        "head": head,
        "head_status": status_by_run.get(head, "unknown"),
        "in_flight": started_live,
        "corpus": len(corpus),
        "tally": tally,
        "decided": decided,
        "tier_rows": tier_rows,
        "ref_total": ref_total,
        "ref_done": ref_done,
        "ref_remaining": ref_remaining,
        "tuning_tracked": False,
        "elapsed_minutes": elapsed,
        "chain_span_minutes": chain_span,
        "stale_records": stale_ids,
        "estimate": {
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
        },
        "plan": {
            "rerun_illegal": plan.rerun_illegal,
            "rerun_underspecified": plan.rerun_underspecified,
            "rerun_unreproducible": plan.rerun_unreproducible,
            "iterations": plan.iterations,
            "mutations": plan.mutations,
        },
        "thermals": thermals,
    }
