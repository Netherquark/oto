#!/usr/bin/env python3
"""The acceptance report: verdicts, arms, and the emitted JSON.

Owns: ``generate_acceptance_report`` / ``regenerate_report`` (whole-corpus
analytics + family/execution timing + A/B verdicts + provenance -> the reporter's
payload, written into the run dir and the canonical base-dir location), and the
two record builders that make the arms comparable (``_ab_records_from_csv`` /
``_ab_records_from_registry``) plus ``_compute_ab_verdicts``, which pairs them.
Does NOT own: the verdict model (oto.metrics.report / oto.metrics.ab_audit), the
clocks verdicts are scaled by (clocks.py), or the corpus readers
(analytics_loaders.py).
Public API: ReportingMixin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from oto.device.peaks import cell_key, kernel_key
from oto.metrics.analytics import extract_family_from_phase_id
from oto.metrics.policy import aggregate_cell
from oto.metrics.report import ABVerdict


class ReportingMixin:
    """Acceptance report assembly, mixed into TensileDriver."""

    def _ab_records_from_csv(self, run_dir: Optional[Path] = None, force_arm: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build native/spoof per-cell record lists from a run's CSVs.

        Each phase's ScheduleName (arm) is resolved from the phase config
        (architecture) since registry records carry no GFLOPS/medians.
        force_arm ('native'|'spoof') overrides arm discrimination — used to
        classify an entire run as one arm (e.g. the recalled gfx900 reference
        run is entirely the spoof floor).
        Returns (native_records, spoof_records) with per-cell medians.
        """
        native_records: List[Dict[str, Any]] = []
        spoof_records: List[Dict[str, Any]] = []
        run_dir = run_dir or self.run_dir
        if not run_dir:
            return native_records, spoof_records

        # Load the manifest once; per-phase lookups below must not re-parse
        # phases.yaml (9k lines) for every CSV.
        phases_by_id = {str(p.get("phase_id", "")): p
                        for p in self.load_phases_manifest()}

        for csv_file in sorted(list(run_dir.glob("phase_*/2_BenchmarkData/*.csv"))
                               + list(run_dir.glob("probe_*/2_BenchmarkData/*.csv"))):
            phase_id = csv_file.parent.parent.name
            # Resolve arm: config Architecture gfx900 == spoof, else native
            phase = phases_by_id.get(phase_id)
            arch = ""
            if phase:
                arch = str(phase.get("config", {}).get("Architecture", ""))
            is_spoof = "gfx900" in arch
            if force_arm == "native":
                is_spoof = False
            elif force_arm == "spoof":
                is_spoof = True
            # Family/dtype per row from the kernel typecode (ground truth), with
            # the phase-level family from phase_id text as fallback — never the
            # reverse. This is the fix for the phase_auto_* pool resolving to
            # family 'auto' -> dtype 'S' and dumping HH/CC/DD kernels into SS
            # cells (§13.2).
            phase_family = extract_family_from_phase_id(phase_id)
            records = self.analytics.load_benchmark_csv(csv_file)
            cell_map = self.analytics.aggregate_by_cell_typecode(records, phase_family)
            for (cell_dtype, shape, fp, family), seeds in cell_map.items():
                agg = aggregate_cell(seeds)
                rec = {
                    "DataType": cell_dtype,
                    "ProblemType": shape,
                    "fingerprint": fp,
                    "GFLOPS": agg.median,
                    "phase_id": phase_id,
                    "family": family,
                }
                rec.update(self._named_cell_stamps(
                    phase or {"config": {}, "shapes": [shape], "family": family.lower()},
                    arm="spoof" if is_spoof else "native"))
                if is_spoof:
                    spoof_records.append(rec)
                else:
                    native_records.append(rec)
        return native_records, spoof_records
    def _ab_records_from_registry(self, run_id: str, force_arm: str = "native") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build native/spoof per-cell records from registry benchmark_result rows.

        Used for merged / draft-imported runs whose GFLOPS live only in the
        database (no run_dir CSVs). The arm must be explicit: the recalled
        gfx900 reference run is entirely the spoof floor, the candidate run
        entirely native.
        """
        native_records: List[Dict[str, Any]] = []
        spoof_records: List[Dict[str, Any]] = []
        try:
            records = self.registry.read_records(run_id=run_id, record_type="benchmark_result")
        except Exception:
            return native_records, spoof_records
        for rec in records:
            gflops = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
            if gflops <= 0:
                continue
            is_spoof = force_arm == "spoof"
            norm = {
                "DataType": rec.get("dtype", ""),
                "ProblemType": rec.get("shape", ""),
                "fingerprint": rec.get("fp", ""),
                "GFLOPS": gflops,
                "phase_id": rec.get("phase_id", ""),
            }
            norm["cell_key"] = rec.get("cell_key", cell_key(
                rec.get("config", {}).get("FamilyLabel", ""), rec.get("shape", "")))
            norm["kernel_key"] = rec.get("kernel_key", kernel_key(rec.get("config") or {}))
            norm["arm"] = rec.get("arm", "spoof" if is_spoof else "native")
            if is_spoof:
                spoof_records.append(norm)
            else:
                native_records.append(norm)
        return native_records, spoof_records
    def _compute_ab_verdicts(self, run_id: str, run_dir: Optional[Path] = None,
                              agg: str = "winner") -> List[Any]:
        """Compute native-vs-spoof A/B verdicts for a run.

        Native arm = the WHOLE database (every run's CSVs + every registry
        benchmark_result row), not just the run being reported: a run may
        execute zero new cells of its own (all phases deduped as
        identical_fp_already_passed, or all failed) while the historical
        winners are still the native candidates it is being graded against.
        Winners are therefore picked across the entire db, including prior
        older winner runs, and each verdict cites the run that produced the
        winning sample.

        Spoof arm = the latest completed gfx900 reference run (the
        once-benchmarked shipped floor), recalled from disk — never re-run.
        Every spoof entity is compared against the best native value at the
        same (dtype, shape): deck-winner vs floor. Falls back to same-run
        records when no reference run exists (legacy merged/draft data).

        agg: comparison basis (see analytics.compute_native_vs_spoof_delta;
        default 'floor_best' = floor's best per-kernel median vs the deck's
        median, the "is a typical native kernel better than the floor's best"
        question).
        """
        self._sclk_cache = None
        self._thermal_cache = None
        self._native_arm_records = self._native_records_all_runs()
        native_records = self._native_arm_records
        if not native_records and run_dir is not None:
            native_records, _spoof = self._ab_records_from_csv(run_dir, force_arm="native")
        if not native_records:
            native_records, _spoof = self._ab_records_from_registry(run_id, force_arm="native")

        # Spoof floor = recalled completed reference run chain (never re-run).
        self._last_ab_reference_run_id = None
        ref_run_ids = self._reference_floor_runs(run_id)
        spoof_records: List[Dict[str, Any]] = []
        for ref in ref_run_ids:
            ref_dir = self.base_dir / "gfx90c_runs" / ref
            if ref_dir.is_dir():
                _ref_native, ref_records = self._ab_records_from_csv(ref_dir, force_arm="spoof")
                for rec in ref_records:
                    rec["source_run"] = ref
                spoof_records.extend(ref_records)
        if ref_run_ids:
            self._last_ab_reference_run_id = ref_run_ids[0]
        if not spoof_records:
            print("[ab] no completed gfx900 reference floor found — A/B verdicts "
                  "deferred. Establish it with `--gfx900-reference` (or --auto, "
                  "which runs it automatically).")
            return []

        # Telemetry clocks for BOTH arms, keyed (source_run, phase_id), plus one
        # shared reference clock. Native runs are loaded too, so a future native
        # run with phase-tagged telemetry is adjusted automatically.
        native_runs = [str(r.get("source_run") or "") for r in native_records]
        clock_runs = sorted({r for r in native_runs if r} | set(ref_run_ids))
        sclk_by_phase = self._sclk_map(clock_runs)
        sclk_ref = self._sclk_reference(sclk_by_phase)
        native_cov = self._clock_coverage(native_records, sclk_by_phase)
        spoof_cov = self._clock_coverage(spoof_records, sclk_by_phase)
        thermal = self._thermal_summary(clock_runs)
        self._sclk_info = {
            "sclk_ref_hz": sclk_ref,
            "native_coverage": native_cov,
            "spoof_coverage": spoof_cov,
            "phases": len(sclk_by_phase),
            "thermal": thermal,
            "thermal_max_c_gate": self.THERMAL_MAX_C,
        }
        if thermal["hot_phases"]:
            print("[report] WARNING: "
                  f"{thermal['hot_phases']} phase(s) hit or exceeded the "
                  f"{self.THERMAL_MAX_C:.0f}C telemetry validity gate. Those "
                  "samples were dropped from the clock estimate rather than "
                  "scaled, so the phases show as UNMEASURED (and their cells "
                  "fall back to unadjusted grading below the coverage floor) "
                  "instead of as slow kernels. Affected: "
                  + ", ".join(thermal["hot_phase_ids"][:5]))
        if agg.endswith("_clock") and native_cov[1] == 0:
            print("[report] WARNING: --native-agg "
                  f"{agg!r} requires per-phase telemetry clocks, but the NATIVE arm "
                  f"has none ({native_cov[0]}/{native_cov[1]} samples covered across "
                  f"{len(native_runs)} run(s); the largest native run has no telemetry "
                  "at all). Cells will fall back to UNADJUSTED best-vs-best and are "
                  "flagged clock_adjusted=false — these numbers are NOT "
                  "telemetry-adjusted.")
        deltas = self.analytics.compute_native_vs_spoof_delta(
            native_records, spoof_records, agg=agg,
            sclk_by_phase=sclk_by_phase, sclk_ref=sclk_ref)

        thermal_by_phase = self._thermal_map(clock_runs)

        def _temp(run: str, phase: str) -> Tuple[Optional[float], Optional[float]]:
            d = thermal_by_phase.get((str(run or ""), str(phase or ""))) or {}
            return d.get("temp_c"), d.get("temp_max_c")

        verdicts = []
        for (dtype, shape, fp), d in deltas.items():
            n_temp, n_temp_max = _temp(d.get("native_winner_run", ""),
                                       d.get("native_winner_phase", ""))
            s_temp, s_temp_max = _temp(d.get("spoof_winner_run", ""),
                                       d.get("spoof_winner_phase", ""))
            verdicts.append(ABVerdict(
                dtype=dtype,
                shape=shape,
                native_median=d["native_median"],
                spoof_median=d["spoof_median"],
                delta_pct=d["delta_pct"],
                tie=d["tie"],
                verdict=d["verdict"],
                fp=d.get("spoof_fp", fp),
                family=d.get("family", ""),
                native_best=d.get("native_best", 0.0),
                spoof_best=d.get("spoof_best", 0.0),
                native_best_median=d.get("native_best_median", 0.0),
                spoof_best_median=d.get("spoof_best_median", 0.0),
                native_worst_median=d.get("native_worst_median", 0.0),
                spoof_worst_median=d.get("spoof_worst_median", 0.0),
                native_value=d.get("native_value", d.get("native_best_median", 0.0)),
                spoof_value=d.get("spoof_value", d.get("spoof_median", 0.0)),
                agg=d.get("agg", agg),
                native_runs=d.get("native_runs", []),
                native_winner_run=d.get("native_winner_run", ""),
                native_winner_phase=d.get("native_winner_phase", ""),
                n_native_runs=d.get("n_native_runs", 0),
                n_native_kernels=d.get("n_native_kernels", 0),
                n_spoof_kernels=d.get("n_spoof_kernels", 0),
                clock_adjusted=d.get("clock_adjusted", False),
                native_clock_coverage=d.get("native_clock_coverage", 0.0),
                spoof_clock_coverage=d.get("spoof_clock_coverage", 0.0),
                sclk_ref_hz=d.get("sclk_ref_hz", 0.0),
                native_clock_sclk_hz=d.get("native_clock_sclk_hz", 0.0),
                spoof_clock_sclk_hz=d.get("spoof_clock_sclk_hz", 0.0),
                native_temp_c=n_temp,
                spoof_temp_c=s_temp,
                native_temp_max_c=n_temp_max,
                spoof_temp_max_c=s_temp_max,
            ))
        return verdicts
    def generate_acceptance_report(self, run_dir: Optional[Path] = None, run_id: Optional[str] = None,
                                    native_agg: str = "winner") -> Optional[Dict[str, Any]]:
        """
        Generate the acceptance report (JSON + HTML) from run data.
        Installed in run_auto, the --targets path, and the SIGINT handler so a
        report is always emitted even on interrupt (missing-report bug fix).

        Analytics come from the WHOLE native corpus — every run's
        2_BenchmarkData CSVs plus every registry benchmark_result row — because
        the report grades the deck's winners, not one run's fresh output: a run
        whose phases were all deduped (identical_fp_already_passed) or all
        failed must still be reported against the historical winners, exactly
        as the spoof arm already is via the reference chain. Reports are written
        into the run dir (when one exists) plus the canonical
        base_dir/gfx90c_results/ location.

        native_agg: which cell statistic picks the winner on both arms —
        'best' | 'median' | 'throttle'.
        """
        try:
            if run_dir is None:
                run_dir = self.run_dir
            if run_id is None:
                # arm="native": the subject of the A/B must be a native run. See
                # registry.latest_run_id -- the newest row overall is usually the
                # gfx900 floor, which would be scored against itself.
                run_id = (run_dir.name if run_dir is not None
                          else self.registry.latest_run_id(arm="native"))
            if not run_id:
                print("Report generation: no run_id available")
                return None

            all_analytics = self._native_analytics_all_runs()
            if not all_analytics:
                # Degenerate: nothing measured anywhere. Say so loudly rather
                # than emitting a clean-looking all-zero grid.
                all_analytics = (self._load_analytics_from_run(run_dir)
                                 or self._load_analytics_from_registry(run_id))

            cell_status = self.analytics.classify_cell_status(all_analytics)
            red_list = cell_status["red"]
            family_timing = self._compute_family_timing(run_id)
            for ref_run in self._reference_floor_runs(run_id):
                # Coverage matrix & execution time are derived from the gfx900
                # shipped floor machinery: reference-run timings are authoritative
                # for the shipped contract; the candidate run fills in families
                # the floor did not cover. Chain runs (base + resume) merge.
                ref_timing = self._compute_family_timing(ref_run)
                family_timing = {**family_timing, **{f: t for f, t in ref_timing.items()}}

            execution_timing = self._compute_execution_timing(run_id, family_timing)

            # Must precede provenance: this is what populates _native_arm_records.
            ab_verdicts = self._compute_ab_verdicts(run_id, run_dir, agg=native_agg)
            native_arm = self._native_arm_provenance(self._native_arm_records, native_agg)
            if native_arm["empty"]:
                print("[report] WARNING: native arm is EMPTY across the whole database — "
                      "every coverage/RED number below is 0 because nothing was ever "
                      "measured, not because the hardware is slow.")
            elif ab_verdicts:
                wins = sum(1 for v in ab_verdicts if v.verdict == "WIN")
                ties = sum(1 for v in ab_verdicts if v.verdict == "TIE")
                losses = sum(1 for v in ab_verdicts if v.verdict == "LOSS")
                print(f"[report] native arm: {native_arm['n_records']} cells from "
                      f"{native_arm['n_runs']} run(s), agg={native_agg} -> "
                      f"{wins} WIN / {ties} TIE / {losses} LOSS")

            report = self.reporter.generate_acceptance_report(
                run_id=run_id,
                ab_verdicts=ab_verdicts,
                all_analytics=all_analytics,
                red_list=red_list,
                orange_list=cell_status["orange"],
                family_timing=family_timing,
                execution_timing=execution_timing,
                reference_run_id=self._last_ab_reference_run_id,
                native_arm=native_arm,
                reference_floor_status=getattr(
                    self, "_reference_floor_status", "not attempted"),
                reference_floor_authoritative=getattr(
                    self, "_reference_floor_authoritative", True),
            )
            if run_dir is not None:
                report_out = run_dir / "acceptance_report.json"
                self.reporter.write_report(report, report_out)
                print(f"Report emitted to: {report_out}")
            if self.reporter.base_dir:
                try:
                    self.reporter.write_report(report, self.reporter.base_dir / "gfx90c_results" / "acceptance_report.json")
                except Exception:
                    pass
            return {"cells": len(all_analytics), "red": len(red_list),
                    "ab": len(ab_verdicts), "run_id": run_id,
                    "native_runs": native_arm["runs"],
                    "overall_pass": report.overall_pass, "summary": report.summary}
        except Exception as e:
            print(f"Report generation error: {e}")
            return None
    def regenerate_report(self, run_id: Optional[str] = None,
                          native_agg: str = "winner") -> Optional[Dict[str, Any]]:
        """Regenerate the acceptance report for a run from the registry.

        With no run_id, uses the most recently registered run. Reports land in
        base_dir/gfx90c_results/acceptance_report.{json,html}. The native arm
        spans the whole database, so the report may legitimately be won by
        cells from an older run than run_id.
        """
        if run_id is None:
            run_id = self.registry.latest_run_id(arm="native")
        if not run_id:
            print("No run id available to regenerate a report")
            return None

        run_dir = self.base_dir / "gfx90c_runs" / run_id
        if not run_dir.exists():
            run_dir = None
        print(f"Regenerating acceptance report for run {run_id}")
        return self.generate_acceptance_report(run_dir=run_dir, run_id=run_id,
                                              native_agg=native_agg)
