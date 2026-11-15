#!/usr/bin/env python3
"""The run plan and the cost model that prices it.

Owns: ``RunPlan`` (what the user asked for -- reruns, iterations, mutations, deck), ``PhaseCost`` (observed minutes per decided phase, sampled from completed reference runs), ``Estimate`` (ETA/progress) and the two unit counters that turn a plan into a workload.
Does NOT own: the telemetry it samples (read_thermals), the report it feeds (build_report) or the live panel (render).
Public API: RunPlan, PhaseCost, Estimate, _reference_unit_count, _tuning_unit_count, ACTIVE_STATES."""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import oto.tensile.shipped_floor_manifest as tlib
from oto.metrics.status_helpers import _parse_ts
from oto.runners.result_paths import results_rel

DB_REL = Path(results_rel("registry.db"))

#: A run is "in flight" while it is the newest one and has no completed_at.
#: The path constants live with the module that reads them.
ACTIVE_STATES = ("started", "interrupted")




@dataclass
class RunPlan:
    """What the user asked for. Every field defaults to the --auto defaults.

    The defaults are the module constants in auto_prompt, never literals
    repeated here, so changing a default cannot leave the ETA describing a plan
    the driver will not run.
    """

    rerun_illegal: bool = False
    rerun_underspecified: bool = False
    rerun_unreproducible: bool = False
    iterations: int = 10
    mutations: int = 3
    deck_size: int = 0          # 0 -> read from phases.yaml
    #: minutes per decided phase; None -> measured from comparable runs
    minutes_per_phase: float | None = None

    @classmethod
    def from_auto_prompt_defaults(cls) -> RunPlan:
        """Mirror --auto's own defaults so the ETA cannot describe a plan the
        driver will not run.

        Instantiating AutoPlan() rather than restating its fields: the first
        draft hardcoded rerun_illegal=True while the driver's default is False,
        so a bare `run_status.py` promised work -- and a GPU-time ETA -- that
        `--auto` would never schedule.
        """
        from oto.runners import auto_prompt
        driver = auto_prompt.AutoPlan()
        return cls(rerun_illegal=driver.rerun_illegal,
                   rerun_underspecified=driver.rerun_underspecified,
                   rerun_unreproducible=driver.rerun_unreproducible,
                   iterations=auto_prompt.DEFAULT_ITERATIONS,
                   mutations=auto_prompt.DEFAULT_MUTATIONS)

    @classmethod
    def from_args(cls, pairs: Sequence[str]) -> RunPlan:
        plan = cls.from_auto_prompt_defaults()
        for pair in pairs:
            if "=" not in pair:
                raise SystemExit(f"--plan expects key=value, got {pair!r}")
            key, _, raw = pair.partition("=")
            key = key.strip()
            if key in ("rerun_illegal", "rerun_underspecified",
                       "rerun_unreproducible"):
                setattr(plan, key, raw.strip().lower() in ("1", "y", "yes", "true"))
            elif key in ("iterations", "mutations", "deck_size"):
                try:
                    setattr(plan, key, int(raw))
                except ValueError as exc:
                    raise SystemExit(f"--plan {key} must be an integer, got {raw!r}") from exc
            elif key == "minutes_per_phase":
                try:
                    plan.minutes_per_phase = float(raw)
                except ValueError as exc:
                    raise SystemExit(f"--plan {key} must be a number, got {raw!r}") from exc
            else:
                raise SystemExit(
                    f"unknown --plan key {key!r}; expected one of "
                    "rerun_illegal, rerun_underspecified, rerun_unreproducible, "
                    "iterations, mutations, deck_size, minutes_per_phase")
        return plan




# ---------------------------------------------------------------------------
# observed cost
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# per-phase cost, measured rather than assumed
# ---------------------------------------------------------------------------
class PhaseCost:
    """Observed minutes per decided phase, from comparable completed runs.

    Comparability matters: a reference run decides ~1.3 min/phase while a
    full-deck convergence run that spends 6 h in Tensile's compile step per
    phase is an order of magnitude slower, and averaging the two would
    understate a reference ETA by 10x. So only `gfx900_ref_*` runs feed a
    reference estimate, and the sample size is always reported.
    """

    def __init__(self, db: Path):
        self.db = db

    def sample(self, min_success: int = 20) -> tuple[float | None, int, list[str]]:
        if not self.db.exists():
            return None, 0, []
        rates: list[float] = []
        used: list[str] = []
        try:
            conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True,
                                   timeout=30.0)
            conn.row_factory = sqlite3.Row
            try:
                from oto.device import loader as _loader
                from oto.ledger.registry_queries import like_escape
                _prefix = like_escape(_loader.spoof_prefix())
                rows = conn.execute(
                    "SELECT run_id, started_at, completed_at, status, metadata "
                    "FROM runs WHERE run_id LIKE ? ESCAPE '\\' "
                    "AND completed_at IS NOT NULL AND status = 'completed' "
                    "ORDER BY id DESC", (_prefix + r"\_ref\_%",)).fetchall()
                for row in rows:
                    rid = str(row["run_id"])
                    decided = 0
                    for (data,) in conn.execute(
                            "SELECT data FROM records WHERE run_id = ? "
                            "AND record_type = 'general'", (rid,)):
                        try:
                            o = json.loads(data)
                        except ValueError:
                            continue
                        status = o.get("status")
                        result = (o.get("result") or {}).get("status")
                        if (status == "completed" and result == "success") or (status == "failed" and result != "skipped_by_user"):
                            decided += 1
                    if decided < min_success:
                        continue
                    start, end = _parse_ts(row["started_at"]), _parse_ts(row["completed_at"])
                    if not start or not end or end <= start:
                        continue
                    hours = (end - start).total_seconds() / 3600.0
                    rates.append(hours * 60.0 / decided)
                    used.append(f"{rid}:{hours:.1f}h/{decided}={rates[-1]:.2f}m")
            finally:
                conn.close()
        except sqlite3.Error:
            return None, 0, []
        if not rates:
            return None, 0, []
        return statistics.median(rates), len(rates), used




# ---------------------------------------------------------------------------
# progress estimate
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# the estimate
# ---------------------------------------------------------------------------
@dataclass
class Estimate:
    units: int = 0
    minutes_per_unit: float | None = None
    decided: int = 0
    done_minutes: float = 0.0
    remaining: int = 0
    eta_minutes: float | None = None
    source: str = ""
    breakdown: list[tuple[str, int]] = field(default_factory=list)
    rate_sample: list[str] = field(default_factory=list)

    @property
    def percent(self) -> float | None:
        if not self.units:
            return None
        return 100.0 * min(self.decided, self.units) / self.units

    @property
    def elapsed_minutes(self) -> float:
        return self.done_minutes

    @property
    def rate_per_hour(self) -> float | None:
        if self.minutes_per_unit and self.minutes_per_unit > 0:
            return 60.0 / self.minutes_per_unit
        if self.done_minutes > 0 and self.decided:
            return self.decided / (self.done_minutes / 60.0)
        return None


def _reference_unit_count(plan: RunPlan, manifest: dict[str, Any],
                          corpus: dict[str, str]) -> tuple[int, list[tuple[str, int]]]:
    """How many reference phases this plan will decide.

    Counts only tiers the plan released, over the union of the reference chain's
    phases, so a tier that was re-triaged moves the number instead of the code.
    """
    wanted = {tlib.TIER_FIRST: plan.rerun_illegal,
              tlib.TIER_HELD: plan.rerun_underspecified,
              tlib.TIER_LAST: plan.rerun_underspecified,
              tlib.TIER_DROP: plan.rerun_unreproducible}
    counts: dict[str, int] = {}
    for tier in corpus.values():
        if wanted.get(tier):
            counts[tier] = counts.get(tier, 0) + 1
    label = {tlib.TIER_FIRST: "ILLEGAL", tlib.TIER_HELD: "UNDER-SPECIFIED",
             tlib.TIER_LAST: "UNDER-SPECIFIED (legacy)", tlib.TIER_DROP: "UNREPRODUCIBLE"}
    breakdown = [(label.get(t, t), n) for t, n in sorted(counts.items())]
    return sum(counts.values()), breakdown


def _tuning_unit_count(plan: RunPlan, deck_size: int) -> int:
    """Native tuning work: each iteration re-runs the deck, then mutates.

    Each of the `deck_size` candidates is re-decided once per iteration, and
    each surviving candidate may be retried `mutations` times, so the cost model
    is deck * (1 + mutations) per iteration.

    Mutations are per-candidate, not per-deck: an iteration over a 10-candidate
    deck with 1 mutation is 20 decided phases, not 11. Reading the mutation
    count as a flat deck-wide surcharge would have understated small-deck plans
    by 4x (it computed 40 for a deck that costs 20).
    """
    if plan.iterations <= 0:
        return 0
    per_iteration = max(deck_size, 0) * (1 + max(plan.mutations, 0))
    return per_iteration * plan.iterations


