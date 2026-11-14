#!/usr/bin/env python3
"""The report's two payload dataclasses.

Owns: ``ABVerdict`` (one native-vs-spoof comparison) and ``AcceptanceReport``
(the whole report's payload). Nothing else in the metrics package defines a
report payload.
Does NOT own: any format (report.py computes, report_html.py renders).
Public API: ABVerdict, AcceptanceReport.

``execution_timing`` is three distinct numbers, never collapsed into one
"runtime":

- ``native_run.elapsed_minutes`` -- wall clock of the run being reported (one
  pass of the deck).
- ``reference_chain.elapsed_minutes`` -- wall clock summed over the gfx900
  reference chain.
- ``phase_busy.minutes`` -- sum of per-phase ``started`` -> ``ended`` spans.

The first two are separate because the floor is usually a *resumed* chain: the
head run's cost is a fraction of the floor's total, so one combined figure
would understate the floor by however many resumes it took. ``phase_busy`` sits
below wall clock by config generation, Tensile build and queueing; a large gap
means an ETA is timing harness overhead, not the GPU. A run still in flight has
no execution time yet: it reports ``elapsed_minutes: null`` and
``in_flight: true`` rather than ``0.0``, so "not finished yet" is never read as
"instant".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from oto.metrics.analytics import CellAnalytics


@dataclass
class ABVerdict:
    """Result of native-vs-shipped-floor A/B comparison."""
    dtype: str
    shape: str
    native_median: float
    spoof_median: float
    delta_pct: float
    tie: bool
    verdict: str  # "WIN", "TIE", "LOSS"
    fp: str = ""  # spoof entity fingerprint (config) being compared
    family: str = ""  # family from the spoof phase (SS/DD/HH/HH_HPA/HS_HPA/CC/ZZ)
    native_best: float = 0.0
    spoof_best: float = 0.0
    native_best_median: float = 0.0  # deck winner's per-kernel median
    spoof_best_median: float = 0.0
    native_worst_median: float = 0.0  # deck's weakest kernel (dominance basis)
    spoof_worst_median: float = 0.0
    native_value: float = 0.0  # the two operands actually compared
    spoof_value: float = 0.0
    agg: str = ""  # comparison basis these operands came from
    clock_adjusted: bool = False  # both arms really had per-phase clock data
    native_clock_coverage: float = 0.0  # fraction of native samples clocked
    spoof_clock_coverage: float = 0.0
    sclk_ref_hz: float = 0.0  # shared reference clock both arms normalized TO
    native_clock_sclk_hz: float = 0.0  # clock the winning native kernel ran at
    spoof_clock_sclk_hz: float = 0.0
    # Thermal context for the same busy samples the clocks came from. Reported
    # alongside the clock, never folded into it: core clock is the channel
    # temperature acts through, so a second temperature factor would
    # double-count (see ``oto.runners.clocks`` -- ``ClockMixin.THERMAL_MAX_C = 88.0``).
    native_temp_c: float | None = None  # median die temp, winning native phase
    spoof_temp_c: float | None = None
    native_temp_max_c: float | None = None
    spoof_temp_max_c: float | None = None
    native_runs: list[str] = field(default_factory=list)
    native_winner_run: str = ""  # run that produced this cell's best native sample
    native_winner_phase: str = ""
    n_native_runs: int = 0
    n_native_kernels: int = 0
    n_spoof_kernels: int = 0
    # Like-for-like provenance (§R56.3). The verdict is graded inside one
    # invocation form (basis_protocol, default "family"): both arms measured
    # under the family-wide protocol the floor uses. The two companion numbers
    # keep everything the pre-§R56.3 reports printed still visible: the old
    # protocol-mixed winner and the best isolated single-problem reading.
    basis_protocol: str = "family"
    native_best_any_protocol: float = 0.0  # pre-§R56.3 mixed-basis winner
    native_isolated_best: float = 0.0      # best 1-problem reading


@dataclass
class AcceptanceReport:
    """Final acceptance report."""
    timestamp: str
    run_id: str
    per_family_coverage: dict[str, dict[str, Any]]
    per_cell_verdicts: list[ABVerdict]
    red_list: list[dict[str, Any]]
    overall_pass: bool
    summary: str
    all_analytics: list[CellAnalytics] = field(default_factory=list)
    run_dir: str | None = None
    family_timing: dict[str, dict[str, Any]] | None = None
    # Execution time. family_timing is per-family phase cost; this is the
    # wall-clock cost of the run and of the reference chain, which are
    # different numbers for a resumed floor and must not be conflated.
    execution_timing: dict[str, Any] | None = None
    orange_list: list[dict[str, Any]] = field(default_factory=list)
    reference_run_id: str | None = None
    shipped_manifest: dict[str, Any] | None = None
    native_arm: dict[str, Any] | None = None
    # Provenance of the A/B floor. A floor that never finished is not evidence,
    # so the report must say so rather than letting its verdicts read as final.
    reference_floor_status: str = "not attempted"
    reference_floor_authoritative: bool = True

