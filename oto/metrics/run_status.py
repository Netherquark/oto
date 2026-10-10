#!/usr/bin/env python3
"""Run status: the cost/ETA report, its text rendering, and the live panel.

Owns: ``build_report`` (the whole status dict for a run/plan/chain), the text
renderings of it (``render_compact``, ``render``, ``bar``), and ``LiveStatus``
(the background-threaded TTY repainter) with ``_PanelStdout``, the stdout proxy
that erases the panel before any other write.
Does NOT own: the plan it prices (oto.metrics.run_plan), the thermal envelope
it cites (oto.metrics.read_thermals), or the driver that starts it
(oto.runners.driver).
Public API: RunPlan (re-exported), PhaseCost (re-exported), Estimate
(re-exported), build_report, bar, render_compact, render, LiveStatus,
_PanelStdout, fmt_duration, bucket, _parse_ts, _jittery.
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import oto.tensile.library as tlib  # noqa: E402

# Re-exported for the pre-split import surface; the implementations live in
# oto.metrics.read_thermals / oto.metrics.run_plan.
from oto.metrics.read_thermals import read_thermals
from oto.metrics.run_plan import (PhaseCost, RunPlan, Estimate,
                                  _reference_unit_count, _tuning_unit_count)

#: The registry's path relative to the project root.
DB_REL = Path("gfx90c_results") / "registry.db"

#: A run is "in flight" while it is the newest one and has no completed_at.
ACTIVE_STATES = ("started", "interrupted")

__all__ = ["RunPlan", "PhaseCost", "Estimate", "build_report", "bar",
           "render_compact", "render", "LiveStatus", "_PanelStdout",
           "fmt_duration", "bucket", "_parse_ts", "_jittery",
           "read_thermals"]



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


def bar(pct: float, width: int = 24) -> str:
    filled = int(round(width * max(0.0, min(100.0, pct)) / 100.0))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def render_compact(rep: Dict[str, Any]) -> str:
    """Few-line panel for a live in-place TTY repaint.

    The full render() is ~35 lines. Repainting that under a running benchmark
    would scroll the run log away and overflow a short terminal, so the live
    view keeps only what changes while you watch it: state, progress, elapsed,
    ETA and the outcome tally.
    """
    est = rep["estimate"]
    tally = rep["tally"]
    lines: List[str] = []
    state = rep["head_status"].upper() + ("  (in flight)" if rep["in_flight"] else "")
    head = rep["head"] or "none"
    lines.append(f"  {head}  [{state}]")
    decided = f"{rep['decided']}/{rep['corpus']}" if rep["corpus"] else str(rep["decided"])
    lines.append(f"    decided   {decided}  "
                 f"success {tally.get('success', 0)}  failed {tally.get('failed', 0)}  "
                 f"skipped {tally.get('skipped', 0)}")
    pct = est["percent"]
    if pct is not None:
        lines.append(f"    progress  {bar(pct, 20)} {pct:5.1f}%   "
                     f"remaining {est['remaining']} units")
    else:
        lines.append(f"    progress  {bar(0.0, 20)}   0.0%   "
                     f"remaining {est['remaining']} units")
    eta = (fmt_duration(est["eta_minutes"]) if est["eta_minutes"] is not None
           else "unknown")
    lines.append(f"    elapsed   {fmt_duration(rep['elapsed_minutes'])}"
                 f"   ETA {eta}")
    th = rep.get("thermals")
    if th and th.get("temp"):
        lines.append(f"    thermals  {th['temp']}  {th['power']}  {th['sclk']}")
    return "\n".join(lines)


class LiveStatus:
    """Repaints run_status into a TTY while a benchmark runs.

    Two things make this safe inside a long run:

    * A background thread owns repainting, so the panel keeps advancing while
      `execute_phase` blocks on Tensile -- the main loop is where progress
      actually happens, so a caller-driven pump would freeze for minutes at a
      time.
    * stdout is wrapped in _PanelStdout, which erases the panel before any other
      write. Without that, the run's own "Skipping phase ..." lines land *under*
      the panel and the next repaint shreds them.

    When stdout is not a TTY (a piped log, CI) it degrades to appending the
    panel on an interval rather than repainting in place.
    """

    def __init__(self, base: Path, run_id: Optional[str] = None,
                 plan: Optional[RunPlan] = None, interval: float = 15.0,
                 compact: bool = True, show_thermals: bool = False,
                 stream=None):
        self.base = Path(base)
        self.run_id = run_id
        self.plan = plan or RunPlan(rerun_illegal=True)
        self.interval = max(interval, 1.0)
        self.compact = compact
        self.show_thermals = show_thermals
        self.stream = stream or sys.stdout
        self._lock = threading.RLock()
        self._painted = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._orig_stdout = None
        self._isatty = False
        self.errors = 0

    # -- painting ----------------------------------------------------------
    def _erase(self) -> None:
        """Erase the panel and leave the cursor where it started."""
        if not self._painted or not self._isatty:
            self._painted = 0
            return
        # Move up over the painted block, then clear downward. \x1b[J clears
        # from the cursor to the end of the screen, so one sequence is enough.
        self.stream.write(f"\x1b[{self._painted}A\x1b[J")
        self.stream.flush()
        self._painted = 0

    def _paint(self) -> None:
        if self._stop.is_set():
            return
        try:
            rep = build_report(self.base, self.run_id, self.plan)
        except BaseException:
            # A status display must never take the run down with it.
            # SystemExit matters here: build_report raises it when there is no
            # registry yet, which is exactly the state a first run starts in,
            # and it is not an Exception subclass.
            self.errors += 1
            return
        if self.compact:
            rep["_compact"] = True
        try:
            text = render(rep, self.show_thermals)
        except Exception:
            self.errors += 1
            return
        with self._lock:
            self._erase()
            self.stream.write(text + "\n")
            self.stream.flush()
            if self._isatty:
                self._painted = text.count("\n") + 1

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._paint()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "LiveStatus":
        self._isatty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._thread = threading.Thread(target=self._loop, name="run-status",
                                        daemon=True)
        self._thread.start()
        if self._isatty:
            # Route the run's own prints through the eraser. Assigned only for
            # a real terminal: wrapping a log file would rewrite it.
            self._orig_stdout = sys.stdout
            sys.stdout = _PanelStdout(self._orig_stdout, self)
        return self

    def refresh(self) -> None:
        """Force one repaint now (used at start/stop for an immediate frame)."""
        self._paint()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._orig_stdout is not None:
            sys.stdout = self._orig_stdout
            self._orig_stdout = None
        with self._lock:
            self._erase()
            self.stream.flush()

    def __enter__(self) -> "LiveStatus":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


class _PanelStdout:
    """stdout proxy that lifts the live panel out of the way before writing."""

    def __init__(self, real, panel: LiveStatus):
        self._real = real
        self._panel = panel

    def write(self, text: str) -> int:
        if text:
            with self._panel._lock:
                self._panel._erase()
                n = self._real.write(text)
                self._real.flush()
            return n
        return 0

    def flush(self) -> None:
        self._real.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._real, "isatty", lambda: False)())

    def __getattr__(self, name):
        return getattr(self._real, name)


def render(rep: Dict[str, Any], show_thermals: bool) -> str:
    out: List[str] = []
    est = rep["estimate"]
    tally = rep["tally"]
    plan = rep["plan"]
    chain = rep["chain"]

    if rep.get("_compact"):
        return render_compact(rep)
    out.append("=" * 72)
    state = rep["head_status"].upper()
    if rep["in_flight"]:
        state += "  (in flight)"
    out.append(f"RUN  {rep['head'] or 'none'}  [{state}]")
    if len(chain) > 1:
        out.append(f"     chain: {' + '.join(chain)}")
    out.append("=" * 72)

    if rep["corpus"]:
        out.append(f"  reference corpus      {rep['corpus']} cells")
    out.append(f"  decided so far        {rep['decided']}")
    for key in ("success", "failed", "skipped", "active"):
        if tally.get(key):
            out.append(f"    {key:<20}{tally[key]}")

    out.append("")
    out.append("  TIERS  (decided / total, from the chain)")
    for label, done, total in rep.get("tier_rows", []):
        pct = (100.0 * done / total) if total else 0.0
        out.append(f"    {label:<22}{bar(pct, 16)} {done}/{total}")

    ref_left = rep["ref_remaining"]
    out.append("")
    out.append("  PLAN  (what this run still has to do)")
    if not est["units"]:
        out.append("    nothing selected -- pass --plan to project a run")
    else:
        out.append(f"    reference remaining  {ref_left}")
        if est["tuning_units"]:
            out.append(f"    tuning               {est['tuning_units']}"
                       f"  ({plan['iterations']} iter x"
                       f" ({est['deck_size']} deck + {plan['mutations']} mut))")
        pct = est["percent"]
        if pct is not None:
            out.append(f"    progress             {bar(pct)} {pct:5.1f}%"
                       f"  (reference only)")
        out.append(f"    total remaining      {est['remaining']} units")
        if est["tuning_units"] and not rep.get("tuning_tracked"):
            out.append("    note                 tuning progress is not in this"
                       " chain, so the % counts reference work only and the"
                       " ETA is an upper bound")

    if est["minutes_per_unit"]:
        out.append(f"  cost per unit         {est['minutes_per_unit']:.2f} min"
                   f"  ({est['source']}, {est['rate_per_hour']:.1f}/h)")
    if est["rate_sample_n"]:
        out.append(f"    sampled from {est['rate_sample_n']} completed ref run(s):"
                   f" {', '.join(est['rate_sample'])}")
    elif est["units"]:
        out.append("    no comparable run to learn a rate from;"
                   " ETA is unestimated until one completes")

    out.append("")
    out.append(f"  elapsed (this run)    {fmt_duration(rep['elapsed_minutes'])}")
    if rep.get("chain_span_minutes") and len(chain) > 1:
        out.append(f"  chain span            {fmt_duration(rep['chain_span_minutes'])}"
                   f" across {len(chain)} runs")
    if est["eta_minutes"] is not None:
        out.append(f"  ETA                   {fmt_duration(est['eta_minutes'])}"
                   f"  (at {est['minutes_per_unit'] or 0:.2f} min/unit)")
    elif est["units"]:
        out.append("  ETA                   unknown (no rate yet)")
    if rep.get("stale_records"):
        out.append(f"  unkeyable records     {rep['stale_records']}"
                   " (no phase_key; excluded from progress)")

    if show_thermals and rep.get("thermals"):
        th = rep["thermals"]
        out.append("")
        out.append(f"  thermals              {th['busy_samples']} busy samples"
                   f"  (gpu_busy > 50%)")
        out.append(f"    edge temp           {th['temp']}")
        out.append(f"    power               {th['power']}")
        out.append(f"    sclk                {th['sclk']}")
        if th["throttled_frac"] > 0:
            out.append(f"    >=80C               {th['samples_over_80c']} samples"
                       f" ({100 * th['throttled_frac']:.1f}%)"
                       " -- thermal/power limited; throughput here is not")
            out.append("                        directly comparable to a cool run")
    elif show_thermals:
        out.append("")
        out.append("  thermals              no per-phase telemetry for this run")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n"
               "  python3 run_status.py\n"
               "  python3 run_status.py --plan rerun_illegal=no "
               "rerun_underspecified=yes iterations=4 --thermals\n")
    ap.add_argument("--base", default=str(ROOT),
                    help="repository root (default: this file's directory)")
    ap.add_argument("--run", help="run_id to report on (default: newest run)")
    ap.add_argument("--plan", nargs="*", default=[],
                    metavar="KEY=VALUE",
                    help="project a plan: rerun_illegal, rerun_underspecified, "
                         "rerun_unreproducible, iterations, mutations, "
                         "deck_size, minutes_per_phase")
    ap.add_argument("--watch", type=float, metavar="SECONDS",
                    help="refresh every SECONDS until interrupted")
    ap.add_argument("--thermals", action="store_true",
                    help="include the temperature/power/clock envelope")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    base = Path(args.base).resolve()
    plan = RunPlan.from_args(args.plan)

    def once() -> int:
        try:
            rep = build_report(base, args.run, plan)
        except SystemExit:
            raise
        except sqlite3.Error as e:
            print(f"registry error: {e}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(rep, indent=2, default=str))
        else:
            print(render(rep, args.thermals))
        return 0

    if not args.watch:
        return once()
    try:
        while True:
            if not args.json:
                os.system("clear" if os.name != "nt" else "cls")
            once()
            print()
            time.sleep(max(args.watch, 1.0))
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
