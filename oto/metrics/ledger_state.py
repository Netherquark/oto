#!/usr/bin/env python3
"""Ledger/corpus state for the status report: one read of the registry plus
the reference corpus tally.

Owns: reading the SQLite registry (every run, its status and the chain of
``resume_of`` ancestors, the latest per-phase verdicts), resolving the
reference corpus via the rerun/shipped manifests, folding pre-``phase_key``
records onto their current key, and the per-tier book-keeping
(``_tier_rows``). Also the module-level ``DB_REL`` registry path and the
``ACTIVE_STATES`` in-flight vocabulary.
Does NOT own: the estimate/ETA pricing or the report dict (report_build),
the plan itself (oto.metrics.run_plan), or the renderer (render_status).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import oto.tensile.shipped_manifest as tlib
from oto.metrics.run_plan import RunPlan
from oto.metrics.status_helpers import _parse_ts, bucket
from oto.runners.result_paths import results_rel

#: The registry's path relative to the project root.
DB_REL = Path(results_rel("registry.db"))

#: A run is "in flight" while it is the newest one and has no completed_at.
ACTIVE_STATES = ("started", "interrupted")

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
    # path lives in oto/runners/reference_floor.py.
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
