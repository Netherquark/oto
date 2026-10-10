#!/usr/bin/env python3
"""Corpus readers: how the driver loads measurements from every run.

Owns: the three ways the corpus is read -- per-run CSV analytics
(``_load_analytics_from_run``), registry-row analytics for merged/draft runs
(``_load_analytics_from_registry``), and the whole-database union of both
(``_native_run_dirs`` / ``_native_analytics_all_runs`` / ``_native_records_all_runs``
/ ``_native_arm_provenance``). Also the retirement sweep that walks every run's
CSVs and appends ``record_type="retire"`` rows (``_retire_stable_candidates``).
Does NOT own: the aggregation itself (oto.metrics.analytics) or the report these
feed (reporting.py).
Public API: CorpusMixin.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from oto.metrics.analytics import CellAnalytics, extract_family_from_phase_id
from oto.metrics.policy import check_retirement_eligibility


class CorpusMixin:
    """Whole-corpus measurement loading, mixed into TensileDriver."""

    def _load_analytics_from_run(self, run_dir: Optional[Path] = None) -> List[CellAnalytics]:
        """Load CellAnalytics from all run CSVs in a run directory."""
        run_dir = run_dir or self.run_dir
        all_analytics = []
        if not run_dir:
            return all_analytics
        csv_files = (list(run_dir.glob("phase_*/2_BenchmarkData/*.csv"))
                     + list(run_dir.glob("probe_*/2_BenchmarkData/*.csv")))

        for csv_file in csv_files:
            # Extract phase_id and family from CSV file path
            phase_dir = csv_file.parent.parent
            phase_id = phase_dir.name

            # Family + dtype are resolved PER ROW from the kernel typecode
            # (SB/DB/HB/CB/ZB, HHS/HSS -> HH), never from phase_id text alone:
            # the `phase_auto_*` pool used to resolve to family 'auto' -> dtype
            # 'S', which dumped HH/CC/DD kernels into the SS cells (§13.2).
            phase_family = extract_family_from_phase_id(phase_id)
            records = self.analytics.load_benchmark_csv(csv_file)
            cell_map = self.analytics.aggregate_by_cell_typecode(records, phase_family)

            for (cell_dtype, shape, fp, family), seeds in cell_map.items():
                analytics_obj = self.analytics.compute_cell_analytics(
                    dtype=cell_dtype,
                    shape=shape,
                    fp=fp,
                    seeds=seeds,
                    family=family,
                    source_run=run_dir.name
                )
                all_analytics.append(analytics_obj)

        return all_analytics
    def _load_analytics_from_registry(self, run_id: Optional[str] = None) -> List[CellAnalytics]:
        """Load CellAnalytics straight from registry benchmark_result rows.

        For merged / draft-imported runs whose per-seed GFLOPS live only in the
        database (no run_dir CSVs). Mirrors _load_analytics_from_run: per-config
        fingerprint cells aggregated over seed rows, family from phase_id.

        With run_id=None every run in the registry is read (the whole-db native
        corpus). Rows are grouped by (source run, phase_id) so each run's cell
        stays its own candidate rather than being pooled into a cross-run median
        — coverage then takes the best cell, which is the deck winner.
        """
        all_analytics = []
        try:
            records = self.registry.read_records(run_id=run_id, record_type="benchmark_result")
        except Exception:
            return all_analytics
        if not records:
            return all_analytics

        by_phase: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for rec in records:
            src_run = str(rec.get("run_id", "") or "")
            by_phase.setdefault((src_run, str(rec.get("phase_id", ""))), []).append(rec)

        for (src_run, phase_id), phase_records in by_phase.items():
            # Family per-row from the kernel typecode (see aggregate_by_cell_typecode);
            # the phase-level family from phase_id text is the fallback only.
            phase_family = extract_family_from_phase_id(phase_id)
            cell_map = self.analytics.aggregate_by_cell_typecode(
                phase_records, phase_family)
            for (cell_dtype, shape, fp, family), seeds in cell_map.items():
                all_analytics.append(self.analytics.compute_cell_analytics(
                    dtype=cell_dtype, shape=shape, fp=fp, seeds=seeds,
                    family=family, source_run=src_run))

        return all_analytics
    def _native_run_dirs(self) -> List[Path]:
        """Every native run directory on disk.

        gfx90c_runs/gfx900_ref_* is the spoof floor (the shipped gfx900
        reference chain), never a native candidate, so it is excluded.
        """
        runs_dir = self.base_dir / "gfx90c_runs"
        return [d for d in sorted(runs_dir.glob("run_*")) if d.is_dir()]
    def _native_records_all_runs(self) -> List[Dict[str, Any]]:
        """Native arm for the acceptance comparison: the whole database.

        The native-vs-spoof comparison must never be scoped to a single run.
        A run legitimately executes zero new cells (every phase deduped as
        identical_fp_already_passed, as the last run did) while the historical
        winners are still the real native candidates — so winners are picked
        across every run, including prior older winner runs.

        Aggregated corpus:
          * native CSVs under every gfx90c_runs/run_* directory
          * every registry benchmark_result row (draft/merged runs whose GFLOPS
            live only in the db)

        Each record carries source_run/run_id so the report can cite which run
        produced each cell's winning sample. Duplicate (phase, fingerprint,
        GFLOPS) triples — the same measurement present in both a run CSV and a
        registry row — are collapsed so they cannot be double-counted.
        """
        records: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str, float]] = set()

        def _add(rec: Dict[str, Any], src_run: str) -> None:
            gf = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
            if gf <= 0:
                return
            key = (str(rec.get("phase_id", "")), str(rec.get("fingerprint", "")), round(gf, 6))
            if key in seen:
                return
            seen.add(key)
            rec["GFLOPS"] = gf
            rec["source_run"] = src_run
            rec["run_id"] = src_run
            records.append(rec)

        for run_dir in self._native_run_dirs():
            native, _spoof = self._ab_records_from_csv(run_dir, force_arm="native")
            for rec in native:
                _add(rec, run_dir.name)

        try:
            db_records = self.registry.read_records(record_type="benchmark_result")
        except Exception:
            db_records = []
        for rec in db_records:
            if str(rec.get("arm") or "") == "spoof":
                continue
            src_run = str(rec.get("run_id", "") or rec.get("source_run") or "")
            _add({
                "DataType": rec.get("dtype", ""),
                "ProblemType": rec.get("shape", ""),
                "fingerprint": rec.get("fp", ""),
                "GFLOPS": float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0),
                "phase_id": rec.get("phase_id", ""),
                "cell_key": rec.get("cell_key", ""),
                "kernel_key": rec.get("kernel_key", ""),
                "arm": rec.get("arm") or "native",
            }, src_run)

        return records
    def _native_arm_provenance(self, native_records: List[Dict[str, Any]], agg: str) -> Dict[str, Any]:
        """Cite the native arm scope in the report: which runs, how many cells."""
        runs = sorted({str(r.get("source_run") or r.get("run_id") or "") for r in native_records
                       if (r.get("source_run") or r.get("run_id"))})
        return {
            "scope": "whole_db",
            "agg": agg,
            "runs": runs,
            "n_runs": len(runs),
            "n_records": len(native_records),
            "empty": not native_records,
        }
    def _native_analytics_all_runs(self) -> List[CellAnalytics]:
        """CellAnalytics for the whole native corpus (drives coverage/RED/ORANGE).

        Coverage must reflect every native candidate ever measured, not just the
        current run: a run that deduped or failed all of its phases still has to
        be graded against the winners it is being compared on.
        """
        all_analytics: List[CellAnalytics] = []
        for run_dir in self._native_run_dirs():
            all_analytics.extend(self._load_analytics_from_run(run_dir))
        all_analytics.extend(self._load_analytics_from_registry())
        return all_analytics
    def _retire_stable_candidates(self) -> int:
        """
        Evaluate all benchmark cells for retirement eligibility.
        Criteria: ≥3 samples per (phase_id,fp), ≥2 independent runs/cell,
        ≤1% run-to-run median drift. Seeds/medians come from every run dir's
        2_BenchmarkData CSVs (registry completed records carry no medians).
        Appends a record_type="retire" record for each eligible (phase_id,fp).
        Returns number of newly retired records appended.
        """
        # Per (phase_id, fp): {run_dir_name: [gflops...]}
        by_cell: Dict[Tuple[str, str], Dict[str, List[float]]] = {}
        runs_dir = self.base_dir / "gfx90c_runs"
        for run_dir in sorted(runs_dir.glob("run_*")):
            run_name = run_dir.name
            for csv_file in sorted(run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
                phase_dir = csv_file.parent.parent
                phase_id = phase_dir.name
                dtype = self.analytics.extract_dtype_from_phase_id(phase_id)
                records = self.analytics.load_benchmark_csv(csv_file)
                cell_map = self.analytics.aggregate_by_cell(records, dtype_override=dtype)
                for (cell_dtype, shape, fp), seeds in cell_map.items():
                    key = (phase_id, fp)
                    by_cell.setdefault(key, {}).setdefault(run_name, []).extend(seeds)

        retired_count = 0
        for (phase_id, fp), run_seeds in by_cell.items():
            synthetic = []
            for run_name, seeds in run_seeds.items():
                median = float(statistics.median(seeds)) if seeds else 0.0
                synthetic.append({
                    "run_id": run_name,
                    "phase_id": phase_id,
                    "fp": fp,
                    "status": "completed",
                    "result": {"median_gflops": median},
                })
            total_samples = sum(len(s) for s in run_seeds.values())
            # Attach sample count via seed_count for the strict gate
            synthetic[-1]["seed_count"] = total_samples
            if self.registry.is_config_retired(phase_id, fp):
                continue
            eligible, reason = check_retirement_eligibility(synthetic)
            if eligible:
                self.registry.append_record({
                    "type": "retire",
                    "phase_id": phase_id,
                    "fp": fp,
                    "reason": reason,
                    "status": "retired"
                }, run_id=self.run_dir.name)
                retired_count += 1
        return retired_count
