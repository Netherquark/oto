#!/usr/bin/env python3
"""The three numbers that get conflated as "runtime".

Owns: per-family phase timing from registry started->ended pairs
(``_compute_family_timing``), a run's wall-clock span (``_run_span_minutes`` and
``_run_stamp``), and the report's execution-time block that keeps native wall
clock, reference-chain wall clock and busy minutes explicitly separate
(``_compute_execution_timing``).
Does NOT own: the registry rows it reads (oto.ledger.registry) or the report it
is formatted for (oto.metrics.acceptance_report).
Public API: TimingMixin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from oto.metrics.benchmark_analytics import extract_family_from_phase_id


class TimingMixin:
    """Execution-time accounting, mixed into TensileDriver."""

    def _compute_family_timing(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Per-family throughput timing from registry started -> ended pairs."""
        started: dict[str, datetime] = {}
        ended: dict[str, datetime] = {}
        try:
            records = self.registry.read_records(run_id=run_id)
        except Exception:
            return {}
        for rec in records:
            pid = rec.get("phase_id") or ""
            status = str(rec.get("status", "")).lower()
            ts = rec.get("timestamp")
            if not pid or not ts:
                continue
            try:
                t = datetime.fromisoformat(str(ts))
            except ValueError:
                continue
            if status in ("started", "running"):
                started.setdefault(pid, t)
            elif status in ("completed", "success", "failed", "timeout", "interrupted", "aborted"):
                ended.setdefault(pid, t)
        per_fam: dict[str, list[float]] = {}
        for pid, start in started.items():
            end = ended.get(pid)
            if not end or end <= start:
                continue
            fam = (extract_family_from_phase_id(pid) or "unknown").upper()
            per_fam.setdefault(fam, []).append((end - start).total_seconds())
        return {
            fam: {
                "cells": len(durs),
                "mean_sec": round(sum(durs) / len(durs), 1),
                "total_min": round(sum(durs) / 60.0, 1),
            }
            for fam, durs in per_fam.items()
        }
    def _run_span_minutes(self, run_id: str) -> float | None:
        """Wall-clock minutes a run occupied, from its registry row.

        None when the run has no start stamp, or when it is still in flight --
        an open-ended run has no execution time to report yet.
        """
        started = self._run_stamp(run_id, "started_at")
        completed = self._run_stamp(run_id, "completed_at")
        if not started or not completed:
            return None
        try:
            delta = completed - started
        except TypeError:      # naive vs aware datetimes
            return None
        return round(delta.total_seconds() / 60.0, 2)
    def _run_stamp(self, run_id: str, column: str) -> datetime | None:
        row = None
        try:
            row = self.registry.run_row(run_id)
        except Exception:
            return None
        if row is None:
            return None
        try:
            value = row[column]
        except (IndexError, KeyError):
            return None
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
    def _compute_execution_timing(self, run_id: str, family_timing: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execution-time block for the acceptance report.

        Three different numbers get conflated as "runtime", so all three are
        reported explicitly rather than one ambiguous field:

        * native_elapsed_minutes -- wall clock of the run being reported. This
          is the execution time of *one* pass of the deck.
        * chain_elapsed_minutes -- wall clock summed over the gfx900 reference
          chain. A resumed floor is several runs, so its cost is never the head
          run's cost.
        * busy_minutes -- sum of per-phase started->ended spans. Less than wall
          clock because the gap is queueing, config generation and Tensile
          build time; a large gap means the ETA is measuring harness overhead
          rather than the GPU.
        """
        native_min = self._run_span_minutes(run_id)
        chain_runs = list(self._reference_floor_runs(run_id) or [])
        chain_spans = []
        for ref in chain_runs:
            mins = self._run_span_minutes(ref)
            if mins is not None:
                chain_spans.append({"run_id": ref, "elapsed_minutes": mins,
                                    "started_at": self._stamp_str(self._run_stamp(ref, "started_at")),
                                    "completed_at": self._stamp_str(self._run_stamp(ref, "completed_at"))})
        per_family = family_timing or {}
        busy = sum(float(f.get("total_min") or 0.0) for f in per_family.values())
        return {
            "generated_at": datetime.now().isoformat(),
            "native_run": {
                "run_id": run_id,
                "status": getattr(self, "_last_run_status", ""),
                "started_at": self._stamp_str(self._run_stamp(run_id, "started_at")),
                "completed_at": self._stamp_str(self._run_stamp(run_id, "completed_at")),
                "elapsed_minutes": native_min,
                "elapsed_human": self._fmt_minutes(native_min),
                "in_flight": native_min is None and bool(
                    self._run_stamp(run_id, "started_at")),
            },
            "reference_chain": {
                "runs": chain_runs,
                "per_run": chain_spans,
                "elapsed_minutes": round(sum(s["elapsed_minutes"] for s in chain_spans), 2) or None,
                "elapsed_human": self._fmt_minutes(
                    round(sum(s["elapsed_minutes"] for s in chain_spans), 2) or None),
            },
            "phase_busy": {
                "minutes": round(busy, 1),
                "hours": round(busy / 60.0, 2),
                "per_family_minutes": {k: v.get("total_min") for k, v in per_family.items()},
                "note": ("sum of per-phase started->ended spans; less than wall "
                         "clock by config generation, Tensile build and queueing"),
            },
        }
    @staticmethod
    def _stamp_str(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None
    @staticmethod
    def _fmt_minutes(minutes: float | None) -> str:
        if minutes is None:
            return "unknown"
        total = round(minutes)
        days, rem = divmod(total, 24 * 60)
        hours, mins = divmod(rem, 60)
        if days:
            return f"{days}d {hours}h {mins}m"
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"
