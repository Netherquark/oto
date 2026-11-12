#!/usr/bin/env python3
"""The thermal envelope of one run, read from its telemetry CSV.

Owns: ``read_thermals`` -- the median/peak temperature, power and clock of a run's *busy* samples. It exists so a suspicious clock-adjusted delta can be checked against the envelope it was measured in.
Does NOT own: the per-phase estimate that consumes it (oto.metrics.run_status), or the gates that use it (oto.runners.clocks).
Public API: read_thermals."""

from __future__ import annotations

import os
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ---------------------------------------------------------------------------
# thermals
# ---------------------------------------------------------------------------
def read_thermals(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Temperature/power/clock envelope from one run's telemetry CSV.

    Only gpu-busy samples, matching the filter port_tensile uses for its clock
    normalization: idle samples read the idle clock and a cool die, so folding
    them in would report a cooler run than the one that was actually measured.
    """
    path = run_dir / "logs" / "telemetry.csv"
    if not path.is_file():
        return None
    import csv as _csv

    temp: List[int] = []; power: List[int] = []; sclk: List[int] = []; busy = 0
    try:
        with path.open(newline="") as fh:
            rd = _csv.DictReader(fh)
            if not rd.fieldnames or "phase_id" not in rd.fieldnames:
                return None
            for row in rd:
                try:
                    if int(row.get("gpu_busy_percent") or 0) <= 50:
                        continue
                except (TypeError, ValueError):
                    continue
                busy += 1
                for col, sink in (("temp_mc", temp), ("power_uw", power),
                                  ("sclk_hz", sclk)):
                    try:
                        v = int(row.get(col) or 0)
                    except (TypeError, ValueError):
                        continue
                    if v > 0:
                        sink.append(v)
    except OSError:
        return None
    if not temp and not power and not sclk:
        return None

    def stat(vals: List[int], scale: float, unit: str) -> str:
        if not vals:
            return "n/a"
        s = sorted(vals)
        return (f"{s[0]/scale:.0f}-{s[-1]/scale:.0f}{unit} "
                f"(mean {statistics.mean(s)/scale:.0f}{unit}, "
                f"p95 {s[min(len(s)-1, int(len(s)*0.95))]/scale:.0f}{unit})")

    # Samples above the sustained-clock cap are thermally or power capped, and
    # are the ones that make a throughput number unreproducible. Count them
    # rather than silently averaging them in.
    hot = [t for t in temp if t >= 80_000]
    return {
        "busy_samples": busy,
        "temp": stat(temp, 1e3, "C"),
        "temp_max_c": (max(temp) / 1e3) if temp else None,
        "power": stat(power, 1e6, "W"),
        "sclk": stat(sclk, 1e6, "MHz"),
        "samples_over_80c": len(hot),
        "throttled_frac": (len(hot) / len(temp)) if temp else 0.0,
    }


