#!/usr/bin/env python3
"""The acceptance report: verdicts, arms, and the emitted JSON.

Owns: ``generate_acceptance_report`` / ``regenerate_report`` (whole-corpus
analytics + family/execution timing + A/B verdicts + provenance -> the reporter's
payload, written into the run dir and the canonical base-dir location), and the
two record builders that make the arms comparable (``_ab_records_from_csv`` /
``_ab_records_from_registry``) plus ``_compute_ab_verdicts``, which pairs them.
Does NOT own: the verdict model (oto.metrics.acceptance_report / oto.metrics.ab_audit), the
clocks verdicts are scaled by (clocks.py), or the corpus readers
(analytics_loaders.py).
Public API: ReportingMixin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import cell_key, kernel_key
from oto.metrics.acceptance_report import ABVerdict
from oto.metrics.benchmark_analytics import extract_family_from_phase_id
from oto.metrics.cell_policy import aggregate_cell
from oto.metrics.measurement_protocol import UNKNOWN, classify
from oto.runners.result_paths import results_dir as _results_dir
from oto.runners.result_paths import runs_dir as _runs_dir
from oto.tensile.shape_order import ordered_shapes


class ReportingMixin:
    """Acceptance report assembly, mixed into TensileDriver."""

    def _ab_records_from_csv(self, run_dir: Path | None = None, force_arm: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build native/spoof per-cell record lists from a run's CSVs.

        Each phase's ScheduleName (arm) is resolved from the phase config
        (architecture) since registry records carry no GFLOPS/medians.
        force_arm ('native'|'spoof') overrides arm discrimination — used to
        classify an entire run as one arm (e.g. the recalled gfx900 reference
        run is entirely the spoof floor).
        Returns (native_records, spoof_records) with per-cell medians and the
        per-phase invocation-form stamp (§R56.3).
        """
        native_records: list[dict[str, Any]] = []
        spoof_records: list[dict[str, Any]] = []
        run_dir = run_dir or self.run_dir
        if not run_dir:
            return native_records, spoof_records

        # Load the manifest once; per-phase lookups below must not re-parse
        # phases.yaml (9k lines) for every CSV.
        phases_by_id = {str(p.get("phase_id", "")): p
                        for p in self.load_phases_manifest()}

        phase_csvs: dict[str, list[Path]] = {}
        for csv_file in sorted(list(run_dir.glob("phase_*/2_BenchmarkData/*.csv"))
                               + list(run_dir.glob("probe_*/2_BenchmarkData/*.csv"))):
            phase_csvs.setdefault(csv_file.parent.parent.name, []).append(csv_file)

        for phase_id, csv_files in sorted(phase_csvs.items()):
            phase = phases_by_id.get(phase_id)
            is_spoof = self._phase_arm(phase_id, phase, force_arm)
            out_recs = self._phase_cell_records(phase_id, csv_files, phase,
                                                is_spoof)
            if is_spoof:
                spoof_records.extend(out_recs)
            else:
                native_records.extend(out_recs)
        return native_records, spoof_records

    def _phase_arm(self, phase_id: str, phase: dict[str, Any] | None,
                   force_arm: str | None) -> bool:
        """Resolve one phase's arm: config Architecture gfx900 == spoof.

        force_arm ('native'|'spoof') overrides arm discrimination — used to
        classify an entire run as one arm (e.g. the recalled gfx900 reference
        run is entirely the spoof floor).
        """
        arch = str((phase or {}).get("config", {}).get("Architecture", ""))
        # Profile-aware spoof reference: a device whose
        # spoof_reference differs from gfx900 must still be classified by its
        # own reference arch, not the hardcoded gfx900 literal. Falls back to
        # "gfx900" for legacy data / profiles without a spoof_reference.
        try:
            spoof_ref = (getattr(self, "profile", None) and
                         getattr(self.profile, "spoof_reference", "")) or "gfx900"
        except Exception:
            spoof_ref = "gfx900"
        is_spoof = spoof_ref in arch
        if force_arm == "native":
            return False
        if force_arm == "spoof":
            return True
        return is_spoof

    def _phase_cell_records(self, phase_id: str, csv_files: list[Path],
                            phase: dict[str, Any] | None,
                            is_spoof: bool) -> list[dict[str, Any]]:
        """One phase's merged per-cell records with its invocation-form stamp.

        Family/dtype per row from the kernel typecode (ground truth), with the
        phase-level family from phase_id text as fallback — never the
        reverse: this is the fix for the phase_auto_* pool resolving to
        family 'auto' -> dtype 'S' and dumping HH/CC/DD kernels into SS
        cells (§13.2). The seed lists of the phase's CSVs merge first (one
        phase carries ONE invocation form), and the classifier runs once;
        every record the phase produced shares its stamp (§R56.3).
        """
        phase_family = extract_family_from_phase_id(phase_id)
        cell_map: dict[tuple[str, str, str, str], Any] = {}
        for csv_file in csv_files:
            cm = self.analytics.aggregate_by_cell_typecode(
                self.analytics.load_benchmark_csv(csv_file), phase_family)
            for map_key, seeds in (cm or {}).items():
                cell_map.setdefault(map_key, []).extend(seeds)
        if not cell_map:
            return []
        measured = ordered_shapes(
            {shape for (_d, shape, _f, _fam) in cell_map})
        declared = [str(s) for s in (phase or {}).get("shapes", []) or []]
        protocol = classify(phase_family, measured, declared)
        arm = "spoof" if is_spoof else "native"
        out: list[dict[str, Any]] = []
        for (cell_dtype, shape, fp, family), seeds in cell_map.items():
            agg = aggregate_cell(seeds)
            rec = {
                "DataType": cell_dtype,
                "ProblemType": shape,
                "fingerprint": fp,
                "GFLOPS": agg.median,
                "phase_id": phase_id,
                "family": family,
                "shapes": measured,
                "shapes_per_phase": len(measured),
                "declared_shapes": declared,
                "protocol": protocol,
            }
            rec.update(self._named_cell_stamps(
                phase or {"config": {}, "shapes": [shape],
                          "family": family.lower()},
                arm=arm))
            out.append(rec)
        return out
    def _ab_records_from_registry(self, run_id: str, force_arm: str = "native") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build native/spoof per-cell records from registry benchmark_result rows.

        Used for merged / draft-imported runs whose GFLOPS live only in the
        database (no run_dir CSVs). The arm must be explicit: the recalled
        gfx900 reference run is entirely the spoof floor, the candidate run
        entirely native.
        """
        native_records: list[dict[str, Any]] = []
        spoof_records: list[dict[str, Any]] = []
        # Registry read failures are bugs, not "no arm data" — they must surface,
        # not masquerade as an empty corpus: a silently empty arm A/B grades
        # against nothing and the report then carries a meaningless verdict.
        records = self.registry.read_records(run_id=run_id, record_type="benchmark_result")
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
                "shapes": [rec.get("shape", "")] if rec.get("shape") else [],
                "shapes_per_phase": 0,   # 0 == unknown, never asserted either way
                "protocol": UNKNOWN,     # registry rows carry no shape list
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
    def _compute_ab_verdicts(self, run_id: str, run_dir: Path | None = None,
                              agg: str = "winner",
                              protocol_basis: str = "family") -> list[Any]:
        """Compute native-vs-spoof A/B verdicts for a run.

        Native arm = the WHOLE database (every run's CSVs + every registry
        benchmark_result row). Spoof arm = the latest completed gfx900 reference run.
        ``protocol_basis`` is the like-for-like rule (§R56.3): the graded
        pairing admits only records stamped with that invocation form; the
        pre-basis mixed winner stays visible per verdict as
        ``native_best_any_protocol``.
        """
        self._sclk_cache = None
        self._thermal_cache = None
        native_records = self._load_native_records(run_id, run_dir)

        spoof_records, ref_run_ids = self._load_spoof_records(run_id)
        if not spoof_records:
            print("[ab] no completed gfx900 reference floor found -- A/B verdicts "
                  "deferred. Establish it with `--gfx900-reference` (or --auto, "
                  "which runs it automatically).")
            return []

        self._last_ab_reference_run_id = ref_run_ids[0] if ref_run_ids else None
        sclk_by_phase, sclk_ref = self._compute_sclk_data(native_records, spoof_records, ref_run_ids)
        native_cov, spoof_cov = self._clock_coverage(native_records, sclk_by_phase),                                 self._clock_coverage(spoof_records, sclk_by_phase)

        thermal = self._thermal_summary(ref_run_ids)
        self._build_sclk_info(sclk_by_phase, sclk_ref, native_cov, spoof_cov, thermal)
        self._log_thermal_and_clock_warnings(thermal, native_cov, agg)

        deltas = self.analytics.compute_native_vs_spoof_delta(
            native_records, spoof_records, agg=agg,
            sclk_by_phase=sclk_by_phase, sclk_ref=sclk_ref,
            protocol_basis=protocol_basis)
        thermal_by_phase = self._thermal_map(ref_run_ids)

        return self._build_verdicts(deltas, thermal_by_phase, agg)

    def _load_native_records(self, run_id: str, run_dir: Path | None) -> list[dict]:
        """Load native records from all runs."""
        self._native_arm_records = self._native_records_all_runs()
        native_records = self._native_arm_records
        if not native_records and run_dir is not None:
            native_records, _ = self._ab_records_from_csv(run_dir, force_arm="native")
        if not native_records:
            native_records, _ = self._ab_records_from_registry(run_id, force_arm="native")
        return native_records

    def _load_spoof_records(self, run_id: str, profile=None) -> tuple:
        """Load spoof records from reference floor runs.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        ref_run_ids = self._reference_floor_runs(run_id,)
        spoof_records: list[dict[str, Any]] = []
        for ref in ref_run_ids:
            ref_dir = _runs_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / ref
            if ref_dir.is_dir():
                _, ref_records = self._ab_records_from_csv(ref_dir, force_arm="spoof")
                for rec in ref_records:
                    rec["source_run"] = ref
                spoof_records.extend(ref_records)
        return spoof_records, ref_run_ids

    def _compute_sclk_data(self, native_records, spoof_records, ref_run_ids):
        """Compute SCLK data for both arms."""
        native_runs = [str(r.get("source_run") or "") for r in native_records]
        clock_runs = sorted({r for r in native_runs if r} | set(ref_run_ids))
        sclk_by_phase = self._sclk_map(clock_runs)
        sclk_ref = self._sclk_reference(sclk_by_phase)
        return sclk_by_phase, sclk_ref

    def _build_sclk_info(self, sclk_by_phase, sclk_ref, native_cov, spoof_cov, thermal):
        """Build and store SCLK info dict."""
        self._sclk_info = {
            "sclk_ref_hz": sclk_ref,
            "native_coverage": native_cov,
            "spoof_coverage": spoof_cov,
            "phases": len(sclk_by_phase),
            "thermal": thermal,
            "thermal_max_c_gate": self.THERMAL_MAX_C,
        }

    def _log_thermal_and_clock_warnings(self, thermal, native_cov, agg):
        """Log thermal and clock adjustment warnings."""
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
                  f"{len(native_cov[2]) if len(native_cov) > 2 else 0} run(s); the largest native run has no telemetry "
                  "at all). Cells will fall back to UNADJUSTED best-vs-best and are "
                  "flagged clock_adjusted=false -- these numbers are NOT "
                  "telemetry-adjusted.")

    def _build_verdicts(self, deltas, thermal_by_phase, agg):
        """Build ABVerdict objects from deltas."""
        def _temp(run: str, phase: str) -> tuple[float | None, float | None]:
            d = thermal_by_phase.get((str(run or ""), str(phase or ""))) or {}
            return d.get("temp_c"), d.get("temp_max_c")

        verdicts = []
        for (dtype, shape, fp), d in deltas.items():
            n_temp, n_temp_max = _temp(d.get("native_winner_run", ""),
                                       d.get("native_winner_phase", ""))
            s_temp, s_temp_max = _temp(d.get("spoof_winner_run", ""),
                                       d.get("spoof_winner_phase", ""))
            verdicts.append(ABVerdict(
                dtype=dtype, shape=shape,
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
                basis_protocol=d.get("basis_protocol", "family"),
                native_best_any_protocol=d.get("native_best_any_protocol", 0.0),
                native_isolated_best=d.get("native_isolated_best", 0.0),
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
    def _report_inputs(self, run_id: str, protocol_basis: str = "family"):
        """The analytics-derived inputs the report is generated from.

        The analytics basis is like-for-like (§R56.3): only phases measured
        under ``protocol_basis`` drive the RED/ORANGE coverage classification.
        The degenerate fallback keeps its unfiltered walk so that an empty
        like-for-like corpus still reports "nothing measured" loudly, but the
        per-call fallback hides nothing: its analytics phase count is what the
        provenance prints.
        """
        all_analytics = self._native_analytics_all_runs(
            protocol_basis=protocol_basis)
        if not all_analytics:
            # Degenerate: nothing measured anywhere. Say so loudly rather
            # than emitting a clean-looking all-zero grid.
            all_analytics = (self._load_analytics_from_run(self.run_dir)
                             or self._load_analytics_from_registry(run_id))
        cell_status = self.analytics.classify_cell_status(all_analytics)
        family_timing = self._merged_family_timing(run_id)
        execution_timing = self._compute_execution_timing(run_id, family_timing)
        return all_analytics, cell_status, family_timing, execution_timing

    def _merged_family_timing(self, run_id: Path):
        """Candidate-run timing merged with every reference chain run's timing.

        Coverage matrix & execution time are derived from the gfx900 shipped
        floor machinery: reference-run timings are authoritative for the
        shipped contract; the candidate run fills in families the floor did
        not cover. Chain runs (base + resume) merge.
        """
        family_timing = self._compute_family_timing(run_id)
        for ref_run in self._reference_floor_runs(run_id):
            ref_timing = self._compute_family_timing(ref_run)
            family_timing = {**family_timing, **dict(ref_timing.items())}
        return family_timing

    def _report_native_arm(self, ab_verdicts, native_agg: str,
                           protocol_basis: str = "family"):
        """Provenance summary + the empty-arm warning.

        Must precede provenance: this is what populates _native_arm_records.
        """
        native_arm = self._native_arm_provenance(self._native_arm_records,
                                                 native_agg,
                                                 protocol_basis=protocol_basis)
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
        return native_arm

    def _emit_report(self, run_id: str, run_dir: Path | None, report,
                     ab_verdicts, native_arm, all_analytics, red_list, profile=None):
        """Write the JSON report(s) and return the result summary.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        if run_dir is not None:
            report_out = run_dir / "acceptance_report.json"
            self.reporter.write_report(report, report_out,)
            print(f"Report emitted to: {report_out}")
        if self.reporter.base_dir:
            # The canonical results-dir report is what `--json` reads later.
            # A failed write here must be a loud error, not a stale file that
            # a downstream consumer will silently trust.
            self.reporter.write_report(
                report,
                _results_dir(self.reporter.base_dir, _loader.resolve_profile(profile,).codename) / "acceptance_report.json",)
        return {"cells": len(all_analytics), "red": len(red_list),
                "ab": len(ab_verdicts), "run_id": run_id,
                "native_runs": native_arm["runs"],
                "overall_pass": report.overall_pass, "summary": report.summary}

    def _report_run_id(self, run_id: str | None,
                       run_dir: Path | None) -> str | None:
        """Resolve the run the report is about (never a floor run).

        arm="native": the subject of the A/B must be a native run. See
        registry.latest_run_id -- the newest row overall is usually the
        gfx900 floor, which would be scored against itself.
        """
        if run_id is not None:
            return run_id
        return (run_dir.name if run_dir is not None
                else self.registry.latest_run_id(arm="native"))

    def _report_payload(self, run_id: str, ab_verdicts, native_arm,
                        all_analytics, cell_status, family_timing,
                        execution_timing) -> Any:
        """Assemble the reporter's payload dataclass for one report."""
        return self.reporter.generate_acceptance_report(
            run_id=run_id,
            ab_verdicts=ab_verdicts,
            all_analytics=all_analytics,
            red_list=cell_status["red"],
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

    def generate_acceptance_report(self, run_dir: Path | None = None, run_id: str | None = None,
                                    native_agg: str = "winner",
                                    protocol_basis: str = "family") -> dict[str, Any] | None:
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
        base_dir/<codename>_results/ location.

        native_agg: which cell statistic picks the winner on both arms —
        'best' | 'median' | 'throttle'.

        protocol_basis: the like-for-like rule (§R56.3, default "family"):
        verdicts pair only records measured under the named invocation form;
        cross-form readings remain in the payload as provenance fields, never
        as a graded basis. "any" reproduces the pre-§R56.3 pairing.
        """
        try:
            if run_dir is None:
                run_dir = self.run_dir
            run_id = self._report_run_id(run_id, run_dir)
            if not run_id:
                print("Report generation: no run_id available")
                return None

            all_analytics, cell_status, family_timing, execution_timing = \
                self._report_inputs(run_id, protocol_basis=protocol_basis)

            # Must precede provenance: this is what populates _native_arm_records.
            ab_verdicts = self._compute_ab_verdicts(run_id, run_dir, agg=native_agg,
                                                    protocol_basis=protocol_basis)
            native_arm = self._report_native_arm(ab_verdicts, native_agg,
                                                 protocol_basis=protocol_basis)

            report = self._report_payload(
                run_id, ab_verdicts, native_arm, all_analytics, cell_status,
                family_timing, execution_timing)
            return self._emit_report(run_id, run_dir, report, ab_verdicts,
                                     native_arm, all_analytics,
                                     cell_status["red"])
        except Exception as e:
            raise RuntimeError(f"Report generation failed: {e}") from e
    def regenerate_report(self, run_id: str | None = None,
                          native_agg: str = "winner",
                          protocol_basis: str = "family", profile=None) -> dict[str, Any] | None:
        """Regenerate the acceptance report for a run from the registry.

        With no run_id, uses the most recently registered run. Reports land in
        base_dir/<codename>_results/acceptance_report.{json,html}. The native arm
        spans the whole database, so the report may legitimately be won by
        cells from an older run than run_id.
        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        if run_id is None:
            run_id = self.registry.latest_run_id(arm="native")
        if not run_id:
            print("No run id available to regenerate a report")
            return None

        run_dir = _runs_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / run_id
        if not run_dir.exists():
            run_dir = None
        print(f"Regenerating acceptance report for run {run_id}")
        return self.generate_acceptance_report(run_dir=run_dir, run_id=run_id,
                                              native_agg=native_agg,
                                              protocol_basis=protocol_basis,)
