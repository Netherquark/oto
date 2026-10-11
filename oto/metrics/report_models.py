#!/usr/bin/env python3
"""The report's two payload dataclasses.

Owns: ``ABVerdict`` (one native-vs-spoof comparison) and ``AcceptanceReport``
(the whole report's payload). Nothing else in the metrics package defines a
report payload.
Does NOT own: any format (report.py computes, report_html.py renders).
Public API: ABVerdict, AcceptanceReport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    # double-count (see port_tensile.THERMAL_MAX_C).
    native_temp_c: Optional[float] = None  # median die temp, winning native phase
    spoof_temp_c: Optional[float] = None
    native_temp_max_c: Optional[float] = None
    spoof_temp_max_c: Optional[float] = None
    native_runs: List[str] = field(default_factory=list)
    native_winner_run: str = ""  # run that produced this cell's best native sample
    native_winner_phase: str = ""
    n_native_runs: int = 0
    n_native_kernels: int = 0
    n_spoof_kernels: int = 0


@dataclass
class AcceptanceReport:
    """Final acceptance report."""
    timestamp: str
    run_id: str
    per_family_coverage: Dict[str, Dict[str, Any]]
    per_cell_verdicts: List[ABVerdict]
    red_list: List[Dict[str, Any]]
    overall_pass: bool
    summary: str
    all_analytics: List[CellAnalytics] = field(default_factory=list)
    run_dir: Optional[str] = None
    family_timing: Optional[Dict[str, Dict[str, Any]]] = None
    # Execution time. family_timing is per-family phase cost; this is the
    # wall-clock cost of the run and of the reference chain, which are
    # different numbers for a resumed floor and must not be conflated.
    execution_timing: Optional[Dict[str, Any]] = None
    orange_list: List[Dict[str, Any]] = field(default_factory=list)
    reference_run_id: Optional[str] = None
    shipped_manifest: Optional[Dict[str, Any]] = None
    native_arm: Optional[Dict[str, Any]] = None
    # Provenance of the A/B floor. A floor that never finished is not evidence,
    # so the report must say so rather than letting its verdicts read as final.
    reference_floor_status: str = "not attempted"
    reference_floor_authoritative: bool = True

