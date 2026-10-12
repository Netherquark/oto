#!/usr/bin/env python3
"""The run-status text renderings and the live TTY panel.

Owns: ``bar`` / ``render_compact`` / ``render`` (the three text renderings of the
same report dict), ``LiveStatus`` (the background-threaded repainter that keeps a
TTY current) and ``_PanelStdout`` (the stdout proxy that erases the panel before
any other write, so a print does not leave half a panel on screen).
Does NOT own: the report dict itself (oto.metrics.run_status) or the plan it
prices (oto.metrics.run_plan).
Public API: bar, render_compact, render, LiveStatus, _PanelStdout.

``LiveStatus`` repaints a compact panel into the terminal while a run executes;
its four non-obvious mechanics:

- A background thread repaints, because the main loop is blocked inside
  ``execute_phase`` for minutes at a time -- a caller-driven pump would freeze.
- stdout is wrapped in ``_PanelStdout``, which erases the panel before any
  other write; without it the run's own ``Skipping phase ...`` lines land under
  the panel and the next repaint shreds them.
- A non-TTY (piped log, CI) gets appended plain lines, never ANSI, so logs stay
  readable.
- The panel catches ``BaseException``: ``build_report`` raises ``SystemExit``
  when the registry does not exist (exactly the state a first run starts in),
  and ``SystemExit`` is not an ``Exception``. A status display must never be
  the reason a run dies.

Flags: ``--live on|off`` (default on), ``--live-interval SECONDS`` (default 15);
``python3 -m oto.metrics.run_status --watch`` remains the standalone full-panel
view.
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

# Imported lazily by `main`: the report module imports this one for the
# render names it re-exports, so a top-level import would be circular.
from oto.metrics.read_thermals import read_thermals
from oto.metrics.run_plan import RunPlan, fmt_duration  # noqa: F401

__all__ = ["bar", "render_compact", "render", "LiveStatus", "_PanelStdout"]


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
            from oto.metrics.run_status import build_report

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
    """The run-status CLI: ``--plan``, ``--watch``, ``--thermals``, ``--json``."""
    from oto.metrics.run_status import build_report

    return _main(argv, build_report)


def _main(argv, build_report) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n"
               "  python3 run_status.py\n"
               "  python3 run_status.py --plan rerun_illegal=no "
               "rerun_underspecified=yes iterations=4 --thermals\n")
    ap.add_argument("--base", default=str(Path(__file__).resolve().parents[2]),
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
