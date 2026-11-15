#!/usr/bin/env python3
"""Shared run-status helpers: timestamp parsing, duration formatting and the
status/result -> display bucket mapping.

Owns: the four primitives ```oto.metrics.ledger_state``` and
```oto.metrics.build_status``` both read (``_parse_ts``, ``fmt_duration``,
``_jittery``, ``bucket``). One home keeps the bucket vocabulary identical to
what the report tallies and prints.
Does NOT own: anything about the registry file, the corpus, or the ETAs.
Public API: the four helpers (private-name functions, module consumers only).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


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
