#!/usr/bin/env python3
"""Per-phase telemetry clocks and the thermal envelope around them.

Owns: the telemetry CSV reader (``_telemetry_rows``), the per-phase median clock
and thermal context (``_load_telemetry_by_phase``), the cached (run, phase) maps
for clocks and thermals, the corpus-wide thermal summary, and the clock-coverage
and reference-clock figures the A/B comparison scales by.
Does NOT own: the telemetry sampler itself (oto.metrics.telemetry), the scaling
it feeds (oto.metrics.analytics.compute_native_vs_spoof_delta), or the report it
appears in (oto.metrics.report).
Public API: ClockMixin. Its tunables are class constants: TELEMETRY_BUSY_PCT,
TELEMETRY_MIN_SAMPLES, SCLK_MIN_HZ, SCLK_MAX_HZ, TELEMETRY_REQUIRE_BUSY,
THERMAL_MAX_C.
"""

from __future__ import annotations

import csv as _csv
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ClockMixin:
    """Telemetry clocks and thermals, mixed into TensileDriver."""

    # Telemetry join: only busy samples count (idle sits at the 400 MHz floor),
    # a phase needs a few samples to be trusted, and readings at or below the
    # idle floor are treated as NO clock measurement rather than a low one.
    # That last part matters: a phase whose only "busy" samples are at the 400 MHz
    # idle clock is not a throttled measurement, and scaling it by ref/idle
    # (4.5x) would let a mediocre kernel win a cell it never earned. Genuinely
    # throttled phases (0.9-1.2 GHz) are real and are kept.
    TELEMETRY_BUSY_PCT = 50
    TELEMETRY_MIN_SAMPLES = 3
    SCLK_MIN_HZ = 800_000_000
    SCLK_MAX_HZ = 2_500_000_000

    # gpu_busy_percent is NOT a usable gate on this machine, so it is off by
    # default and kept for reporting only. Measured on the 2026-10-05 native
    # trial (run_20261005_170141, 1916 phase-tagged samples): exactly ONE
    # exceeded 50%. amdgpu reports 3-8% for short and small kernels, so the
    # gate was measuring "did this kernel saturate the GPU", not "was the GPU
    # running the benchmark" -- and it silently produced zero clock data for
    # exactly the cheap phases a smoke run executes.
    #
    # power_uw does not separate idle from loaded either: idle median 20 W vs
    # clocked median 23 W, idle p95 28 W, clocked min 8 W, and the readings are
    # coarsely quantised. The one discriminator that does work is sclk, which is
    # why SCLK_MIN_HZ exists: idle sits pinned at the 400 MHz floor (1568 of the
    # 1916 samples) and SCLK_MIN_HZ already removes it, leaving 331 usable
    # samples here instead of 1.
    #
    # Measured corpus-wide impact, gate ON vs OFF: 53,860 -> 93,427 usable
    # samples, and phases holding a clock base 3375/3654 (92.4%) -> 4167/4516
    # (92.3%). Coverage RATE is unchanged, so this does not overturn the existing
    # clock-adjusted verdicts -- the gate was never what made most phases
    # clockless. What it does is (a) stabilise every base by ~1.7x more samples
    # and (b) give a base to cheap/small phases, which is the whole point of a
    # smoke run. Historical runs do carry busy>50 samples in bulk, which is why
    # the gate looked reasonable when it was written.
    TELEMETRY_REQUIRE_BUSY = False

    # A busy sample at or above this temperature is discarded from the clock
    # estimate rather than scaled, on the same grounds as SCLK_MIN_HZ: it is "no
    # reliable measurement", not "a slower measurement".
    #
    # This is a validity gate, NOT a second throughput correction. The obvious
    # design -- scale GFLOPS by (temp_ref / temp) after the clock correction --
    # double-counts, because core clock is the channel temperature acts through,
    # and this corpus contradicts it anyway. Across ~17.9k busy samples from the
    # two full reference runs, sustained clock rises with temperature and then
    # plateaus; it never falls off a thermal ceiling:
    #
    #     temp      46-48C  56-58C  64-66C  70-72C  76-78C  80-82C
    #     median     930MHz 1537MHz 1725MHz 1787MHz 1800MHz 1800MHz
    #
    # The clock tracks each kernel's power draw, not the die temperature: the
    # *coldest* bucket holds the *lowest* clock and the hottest is still pinned at
    # the 1800 MHz maximum. A temperature factor fitted to that curve would have
    # a negative slope through the midrange, i.e. it would credit thermally
    # stressed measurements with a speedup. The gate sits above the hottest
    # sample ever recorded (82C), so it is inert on the current corpus and only
    # bites if a future run genuinely thermal-throttles.
    THERMAL_MAX_C = 88.0
    def _telemetry_rows(self, run_dir: Path) -> List[Tuple[str, int, Optional[float]]]:
        """(phase_id, sclk_hz, temp_c) for usable busy samples in one run.

        Only samples taken while the GPU was actually busy are counted: a
        phase's wall window also covers Tensile's compile/idle gaps, where sclk
        sits at the 400 MHz idle floor and the die cools, so folding those in
        understates both the clock the kernel ran at and the temperature it ran
        at. Readings outside [SCLK_MIN_HZ, SCLK_MAX_HZ] are dropped for the same
        reason SCLK_MIN_HZ exists (idle floor => no measurement, not a low one).

        Returns [] when the run has no telemetry, or when its sampler predates
        per-phase tagging (the phase_id column), since those rows cannot be
        attributed to a phase at all.
        """
        import csv

        path = Path(run_dir) / "logs" / "telemetry.csv"
        if not path.is_file():
            return []
        rows: List[Tuple[str, int, Optional[float]]] = []
        try:
            with path.open(newline="") as fh:
                rd = _csv.DictReader(fh)
                if not rd.fieldnames or "phase_id" not in rd.fieldnames:
                    return []
                for row in rd:
                    pid = (row.get("phase_id") or "").strip()
                    if not pid:
                        continue
                    # Read by column name, not position. Some samplers omit
                    # temp_mc, and positional reads would then silently consume
                    # power_uw as the busy percentage -- which reads as a
                    # permanently idle GPU and drops every sample, leaving a
                    # corpus with no clock data and no error to explain it.
                    try:
                        busy = int(row.get("gpu_busy_percent") or 0)
                        if self.TELEMETRY_REQUIRE_BUSY and busy <= self.TELEMETRY_BUSY_PCT:
                            continue
                        hz = int(row.get("sclk_hz") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not (self.SCLK_MIN_HZ <= hz <= self.SCLK_MAX_HZ):
                        continue
                    raw_temp = row.get("temp_mc")
                    if raw_temp in (None, ""):
                        temp_c = None
                    else:
                        try:
                            temp_c = int(raw_temp) / 1000.0
                        except (TypeError, ValueError):
                            temp_c = None
                    rows.append((pid, hz, temp_c))
        except OSError:
            return []
        return rows
    def _load_telemetry_by_phase(self, run_dir: Path) -> Dict[str, Dict[str, Any]]:
        """Per-phase sustained clock plus the thermal context it was taken in.

        Each phase needs >= TELEMETRY_MIN_SAMPLES usable busy samples. Samples at
        or above THERMAL_MAX_C are excluded from the clock estimate (see that
        constant) and counted in `hot_samples`, so a thermally throttled phase
        reports as *unmeasured* rather than as a slow kernel that clock scaling
        would then over-reward.
        """
        hz_by_phase: Dict[str, List[int]] = {}
        temp_by_phase: Dict[str, List[float]] = {}
        hot_by_phase: Dict[str, int] = {}
        for pid, hz, temp_c in self._telemetry_rows(run_dir):
            if temp_c is not None and temp_c >= self.THERMAL_MAX_C:
                hot_by_phase[pid] = hot_by_phase.get(pid, 0) + 1
                continue
            hz_by_phase.setdefault(pid, []).append(hz)
            if temp_c is not None:
                temp_by_phase.setdefault(pid, []).append(temp_c)

        out: Dict[str, Dict[str, Any]] = {}
        for pid, hz in hz_by_phase.items():
            if len(hz) < self.TELEMETRY_MIN_SAMPLES:
                continue
            temps = temp_by_phase.get(pid, [])
            out[pid] = {
                "sclk_hz": statistics.median(hz),
                # temp_c is None when the sampler recorded no temperature. That
                # is reported, not gated on: an unmeasured die temperature is not
                # evidence of a hot die, so the clock estimate still stands. The
                # gate only fires on a temperature that was actually seen and
                # actually high.
                "temp_c": statistics.median(temps) if temps else None,
                "temp_max_c": max(temps) if temps else None,
                "hot_samples": hot_by_phase.get(pid, 0),
            }
        return out
    def _load_sclk_by_phase(self, run_dir: Path) -> Dict[str, float]:
        """Per-phase sustained core clock (Hz) from one run's telemetry timeline.

        A thin projection of _load_telemetry_by_phase, so the existing clock
        consumers -- the (run, phase) map in _sclk_map and the coverage
        accounting -- keep the same {phase_id: hz} shape.
        """
        return {pid: d["sclk_hz"]
                for pid, d in self._load_telemetry_by_phase(run_dir).items()}
    def _sclk_map(self, run_ids: List[str]) -> Dict[Tuple[str, str], float]:
        """(source_run, phase_id) -> sustained sclk across the given runs."""
        if self._sclk_cache is None:
            self._sclk_cache: Dict[Tuple[str, str], float] = {}
        for rid in run_ids:
            if any(k[0] == rid for k in self._sclk_cache):
                continue
            run_dir = self.base_dir / "gfx90c_runs" / rid
            for pid, hz in self._load_sclk_by_phase(run_dir).items():
                self._sclk_cache[(rid, pid)] = hz
        return self._sclk_cache
    def _thermal_map(self, run_ids: List[str]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """(source_run, phase_id) -> thermal context for the same busy samples.

        Shares the parse with _load_sclk_by_phase via _load_telemetry_by_phase, so
        the temperature reported for a phase is the temperature of the exact
        samples its clock estimate came from -- a phase's clock and its thermal
        state can never be attributed to different windows.
        """
        if self._thermal_cache is None:
            self._thermal_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for rid in run_ids:
            if any(k[0] == rid for k in self._thermal_cache):
                continue
            run_dir = self.base_dir / "gfx90c_runs" / rid
            for pid, d in self._load_telemetry_by_phase(run_dir).items():
                self._thermal_cache[(rid, pid)] = d
        return self._thermal_cache
    def _thermal_summary(self, run_ids: List[str]) -> Dict[str, Any]:
        """Corpus-wide thermal envelope for the runs feeding the A/B report.

        Reported, never scaled: see THERMAL_MAX_C for why a temperature factor
        is not applied on top of the clock correction. The point of surfacing
        it is that a reader can see whether a clock-adjusted delta came from a
        thermally stressed window, which the sclk number alone cannot show.
        """
        temps: List[float] = []
        peaks: List[float] = []
        hot_phases: List[str] = []
        for (rid, pid), d in self._thermal_map(run_ids).items():
            if d.get("temp_c") is not None:
                temps.append(float(d["temp_c"]))
            if d.get("temp_max_c") is not None:
                peaks.append(float(d["temp_max_c"]))
            if d.get("hot_samples"):
                hot_phases.append(f"{rid}:{pid}")
        if not temps:
            return {"phases": 0, "temp_c": None, "temp_max_c": None,
                    "hot_phases": 0, "hot_phase_ids": []}
        return {
            "phases": len(temps),
            "temp_c": statistics.median(temps),
            "temp_max_c": max(peaks) if peaks else None,
            "hot_phases": len(hot_phases),
            "hot_phase_ids": sorted(hot_phases)[:10],
        }
    def _clock_coverage(self, records: List[Dict[str, Any]],
                        sclk_by_phase: Dict[Tuple[str, str], float]) -> Tuple[int, int]:
        """(covered_samples, total_samples) for one arm against the clock map."""
        covered = total = 0
        for rec in records:
            gf = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
            if gf <= 0:
                continue
            total += 1
            if sclk_by_phase.get((str(rec.get("source_run") or rec.get("run_id") or ""),
                                  str(rec.get("phase_id", "")))):
                covered += 1
        return covered, total
    def _sclk_reference(self, sclk_by_phase: Dict[Tuple[str, str], float]) -> float:
        """The single corpus-wide clock every arm is normalized TO.

        The highest sustained clock the GPU actually held in this corpus, used as
        one shared constant for both arms. Normalizing each arm to its OWN
        maximum would silently cancel the very clock difference being measured,
        so the reference must be global and the scale factor is reported.
        """
        return max(sclk_by_phase.values()) if sclk_by_phase else 0.0
