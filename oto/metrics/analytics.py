#!/usr/bin/env python3
"""Stage 5 analytics: CSV loading and per-cell aggregation.

Owns: ``AnalyticsEngine`` -- the composition root over the family-attribution
helpers (family_attribution), the A/B delta (ab_delta) and the cell-coverage
classification (cell_status), plus the CSV seam itself: reading a benchmark CSV
(the multi-size sweep trap, the string-tile trap, the
complex-is-8-bytes trap per docs/knowledge_base.md §8.1) and aggregating rows into
per-cell seed lists.
Does NOT own: the verdict threshold (oto.metrics.ab_audit), the report layout
(oto.metrics.report), or the ceiling tables (`oto.device.loader.current_profile()`).
Public API: AnalyticsEngine, CellAnalytics, extract_family_from_phase_id,
resolve_cell_family, FAMILY_TO_DTYPE (re-exported), CLOCK_MIN_COVERAGE.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from oto import yaml_cached as yamlio
from oto.device import loader as _loader

# `yaml` is imported lazily, inside the functions that use it, so that
# importing this module does not pull in the parser.
from oto.metrics.ab_delta import ABDeltaMixin
from oto.metrics.cell_policy import aggregate_cell
from oto.metrics.cell_status import CellStatusMixin
from oto.metrics.family_attribution import (
    extract_family_from_phase_id,
    family_to_dtype,
    resolve_cell_family,
)
from oto.runners.paths import results_dir as _results_dir

__all__ = [
    "CLOCK_MIN_COVERAGE",
    "AnalyticsEngine",
    "CellAnalytics",
    "extract_family_from_phase_id",
    "resolve_cell_family",
]

# Minimum share of an arm's samples that must carry a real per-phase clock
# before a clock-adjusted statistic is trusted for that cell. Below this the
# clocked subset is not the same population the unadjusted best is drawn from,
# so its max is not comparable and the cell is graded unadjusted instead.
CLOCK_MIN_COVERAGE = 0.5


# `FAMILY_TO_DTYPE` (family prefix -> Tensile DataType char, lowercased keys for
# phase_id parsing) is owned by `oto.metrics.family_attribution` and re-exported
# lazily below via `__getattr__`. It used to be rebuilt here from the profile's
# family_dtype_char at import time, freezing the device facts; do not
# reintroduce it as an import-time value -- extend the owner.


def __getattr__(name: str):
    """Lazy ``FAMILY_TO_DTYPE`` re-export (ambient profile, call time)."""
    if name == "FAMILY_TO_DTYPE":
        return family_to_dtype()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class CellAnalytics:
    """Per-cell analytics result."""

    def __init__(
        self,
        dtype: str,
        shape: str,
        config_fp: str,
        median_gflops: float,
        spread_ratio: float,
        num_seeds: int,
        pct_of_ceiling: float,
        is_below_ceiling: bool,
        bound_class: str = "ALU",
        family: str = "",
        cv: float = 0.0,
        source_run: str = "",
        seeds: list[float] | None = None
    ):
        self.dtype = dtype
        self.shape = shape
        self.config_fp = config_fp
        self.median_gflops = median_gflops
        self.spread_ratio = spread_ratio
        self.num_seeds = num_seeds
        self.pct_of_ceiling = pct_of_ceiling
        self.is_below_ceiling = is_below_ceiling
        self.bound_class = bound_class
        self.family = family  # e.g. 'ss', 'hh_hpa', 'hs_hpa', 'cc', 'zz'
        self.cv = cv  # coefficient of variation across seeds (stability gate)
        self.source_run = source_run  # run that produced this cell (whole-db corpora)
        # The seeds themselves travel with the cell. An LCB cannot be recovered
        # from a median, a CV and a count, so parent selection needs the samples;
        # keeping them here avoids a second read of every CSV just to pick a
        # parent (`Hplan.5` step 3).
        self.seeds = list(seeds) if seeds else []


class AnalyticsEngine(CellStatusMixin, ABDeltaMixin):
    """Stage 5 analytics engine."""

    def __init__(self, registry, base_dir: Path, profile=None):
        """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
        self.registry = registry
        self.base_dir = Path(base_dir)
        self.results_dir = _results_dir(self.base_dir, _loader.resolve_profile(profile,).codename)
        self._phases_cache = None

    def _load_phases_manifest(self) -> list[dict[str, Any]]:
        """Load and cache phases.yaml manifest."""
        if self._phases_cache is None:
            phases_path = self.base_dir / "phases.yaml"
            if phases_path.exists():
                with open(phases_path) as f:
                    self._phases_cache = yamlio.load_yaml_text(f.read()) or []
            else:
                self._phases_cache = []
        return self._phases_cache

    def extract_dtype_from_phase_id(self, phase_id: str) -> str:
        """
        Extract dtype from phase_id by looking up in phases.yaml.
        Falls back to family naming convention if not found.

        Args:
            phase_id: Phase identifier (e.g., "phase_ss_Ailk_Bjlk_1024x1024x1024")

        Returns:
            Dtype string (e.g., "S", "D", "H", etc.)
        """
        # Look up in phases.yaml first (normalize historical double prefix e.g. phase_phase_ss_...)
        phases = self._load_phases_manifest()
        norm_id = re.sub(r'^(phase_)+', 'phase_', str(phase_id))
        for phase in phases:
            if phase.get('phase_id') == norm_id:
                dtype = phase.get('dtype')
                if dtype:
                    return dtype

        # Fallback: parse from phase_id via family prefix. Token-based parse
        # (unlike a raw [a-z_]+ regex) survives digit-bearing phase ids.
        family = extract_family_from_phase_id(norm_id)
        dtype = family_to_dtype().get(family)
        if dtype:
            return dtype

        return 'unknown'

    def count_benchmark_rows(self, csv_path: Path) -> int:
        """
        Count raw data rows in a benchmark CSV, ignoring their values.

        Exists because the outcome classifier must distinguish "CSV present with
        rows but every row non-functional" from "no rows at all", and that
        distinction cannot be recovered from load_benchmark_csv -- that loader
        drops non-positive-GFlops rows by design, so both cases return []. This
        is the single owner of CSV *shape*; load_benchmark_csv remains the
        single owner of CSV *values*, and neither re-implements the other.

        Do not read throughput from the column headed "GFlops" to answer this
        question. In these CSVs that column is a problem index (0,1,2,3 across a
        multi-shape file, 0 in a single-shape file); real throughput is in the
        trailing kernel column and load_benchmark_csv already reads it. Reading
        the wrong column is what made a whole mutant population look
        zero-yield when it was not.

        Args:
            csv_path: Path to 2_BenchmarkData/*.csv or 00_Final.csv

        Returns:
            Number of data rows (0 for a missing/header-only file)
        """
        if not csv_path.exists():
            return 0
        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return 0
                return sum(1 for _ in reader)
        except Exception as e:
            print(f"Error counting rows in CSV {csv_path}: {e}")
            return 0

    def read_column(self, csv_path: Path, column: str) -> list[float]:
        """Every value of one named column, as floats, unfiltered.

        The single canonical place a raw named column is read. `WinnerFreq` is the
        only current caller, but the reason it lives here rather than in the
        mutator is that stripping field whitespace and tolerating a missing or
        ragged column is a property of Tensile's CSV format, not of the mutation
        ledger. A second reader is a second set of format assumptions, and the
        failure mode is quiet: a wrong column read yields zeros, which looks like
        "no kernel won", which looks like a working kernel that merely lost.

        Values that cannot be parsed as floats are skipped rather than coerced to
        0.0, so a corrupt row cannot be reported as a measured zero.
        """
        out: list[float] = []
        if not Path(csv_path).exists():
            return out
        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return out
                reader.fieldnames = [h.strip() if h else h
                                     for h in reader.fieldnames]
                for row in reader:
                    raw = row.get(column)
                    if raw is None:
                        continue
                    try:
                        out.append(float(str(raw).strip()))
                    except (TypeError, ValueError):
                        continue
        except Exception:
            return out
        return out

    def winner_freq(self, csv_paths: Sequence[Path]) -> dict[str, Any]:
        """WinnerFreq summary over one or more benchmark CSVs.

        Returns `{"max": float|None, "positive": bool, "n": int}`. Observed, never
        decisive: a kernel that ran but never won its own internal comparison is
        still functional, which is why `positive` is reported alongside `max`
        rather than folded into an outcome.
        """
        values: list[float] = []
        for path in csv_paths or ():
            values.extend(self.read_column(Path(path), "WinnerFreq"))
        if not values:
            return {"max": None, "positive": False, "n": 0}
        return {"max": max(values), "positive": any(v > 0 for v in values),
                "n": len(values)}

    def load_benchmark_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        """Load a Tensile benchmark CSV; strip whitespace, extract GFlops."""
        records = []
        if not csv_path.exists():
            return records
        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return records
                reader.fieldnames = [h.strip() for h in reader.fieldnames]
                raw_rows = list(reader)

            kern_cols = [h for h in reader.fieldnames if "Cijk" in h or "MT" in h]

            for row in raw_rows:
                clean_row = {k.strip(): v.strip() for k, v in row.items() if k and v}
                size_i = clean_row.get("SizeI", "1024")
                size_j = clean_row.get("SizeJ", "1024")
                size_l = clean_row.get("SizeL", "1024")
                shape_str = f"{size_i}x{size_j}x{size_l}"

                # If Tensile kernel column exists, extract each kernel's GFlops
                if kern_cols:
                    for kc in kern_cols:
                        try:
                            gf = float(clean_row.get(kc, 0.0))
                            if gf > 0:
                                rec = dict(clean_row)
                                rec["GFLOPS"] = gf
                                rec["shape"] = shape_str
                                rec["ProblemType"] = shape_str
                                rec["kernel"] = kc
                                rec["fingerprint"] = kc
                                records.append(rec)
                        except (ValueError, TypeError):
                            pass
                else:
                    gflops_val = 0.0
                    for k_cand in ["GFLOPS", "GFlops", "gflops"]:
                        if k_cand in clean_row:
                            try:
                                gflops_val = float(clean_row[k_cand])
                                break
                            except (ValueError, TypeError):
                                pass
                    if gflops_val > 0:
                        clean_row["GFLOPS"] = gflops_val
                        clean_row["shape"] = shape_str
                        clean_row["ProblemType"] = shape_str
                        records.append(clean_row)
        except Exception as e:
            print(f"Error reading CSV {csv_path}: {e}")
        return records

    def aggregate_by_cell(
        self,
        records: list[dict[str, Any]],
        dtype_override: str | None = None
    ) -> dict[tuple[str, str, str], list[float]]:
        """
        Aggregate benchmark records by (dtype, shape, config_fp).

        Args:
            records: List of benchmark records
            dtype_override: Optional dtype to use instead of extracting from records

        Returns:
            Dict mapping (dtype, shape, fp) to list of GFLOPS values
        """
        cell_map = defaultdict(list)
        for rec in records:
            dtype = dtype_override or rec.get("DataType", rec.get("dtype", "Unknown"))
            shape = rec.get("ProblemType", rec.get("shape", "Unknown"))
            fp = rec.get("fingerprint", rec.get("fp", "unknown"))
            gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
            if gflops > 0:
                cell_map[(dtype, shape, fp)].append(gflops)
        return cell_map

    def aggregate_by_cell_typecode(
        self,
        records: list[dict[str, Any]],
        phase_family: str = "",
    profile=None,
    ) -> dict[tuple[str, str, str, str], list[float]]:
        """Aggregate benchmark records by (dtype, shape, fp, family) with the
        typecode-first family filter.

        Each record's family is resolved by its OWN kernel typecode
        (``resolve_cell_family``) — the §13.2 rule: SB/DB/HB/CB/ZB decide the
        cell, and HHS/HSS kernels (fp16-family) never land in SS cells. The
        per-phase family (from phase_id text) is the fallback only, never the
        primary signal. Returns cells keyed (dtype, shape, fp, family) so the
        caller's CellAnalytics carries the resolved family, not a text guess.
        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        cell_map = defaultdict(list)
        for rec in records:
            if not rec.get("family",):
                rec = dict(rec)
                rec["family"] = phase_family
            fam = resolve_cell_family(rec)
            if not fam:
                continue
            shape = rec.get("ProblemType", rec.get("shape", "Unknown",),)
            fp = rec.get("fingerprint", rec.get("fp", "unknown",),)
            gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0,),)
            if gflops > 0:
                dtype = _loader.resolve_profile(profile,).family_dtype_char.get(fam, rec.get("DataType", "",),)
                cell_map[(dtype, shape, fp, fam)].append(gflops)
        return cell_map

    def compute_cell_analytics(
        self,
        dtype: str,
        shape: str,
        fp: str,
        seeds: list[float],
        ceiling_gflops: float | None = None,
        red_threshold_pct: float = 50.0,
        family: str = "",
        source_run: str = "",
    profile=None,
    ) -> CellAnalytics:
        """
        Compute analytics for a single cell vs realistic ceiling.

        Args:
            dtype: Data type (FP32, FP16, etc. or SS, HH, etc.)
            shape: Problem shape (e.g., "1024x1024x1024")
            fp: Config fingerprint
            seeds: List of GFLOPS seed values
            ceiling_gflops: Optional ceiling for % calculation
            red_threshold_pct: Threshold below which ALU compute cell is RED
            family: Multi-letter family prefix (e.g. 'ss', 'hh_hpa', 'cc')

        Returns: CellAnalytics object. ``profile`` -- optional, ambient by default.
        """
        agg = aggregate_cell(seeds)

        # Lookup realistic ceiling first, then peak
        if ceiling_gflops is None:
            ceiling_gflops = _loader.resolve_profile(profile,).realistic_ceilings.get(
                family.upper() if family else dtype,
                _loader.resolve_profile(profile,).realistic_ceilings.get(dtype, _loader.resolve_profile(profile,).peak_gflops.get(dtype, 1613.0,),)
            ,)

        pct_of_ceiling = (agg.median / ceiling_gflops) * 100.0 if ceiling_gflops > 0 else 0.0

        # Determine bound class (ALU vs DDR)
        bound_class = self._classify_bound_class(shape, dtype)

        # Below-ceiling flag: DDR cells are exempt from ALU-compute classification
        # (not to be confused with the report's RED = missing contract cell).
        is_below_ceiling = (bound_class == "ALU" and pct_of_ceiling < red_threshold_pct)

        return CellAnalytics(
            dtype=dtype,
            shape=shape,
            config_fp=fp,
            median_gflops=agg.median,
            spread_ratio=agg.spread_ratio,
            num_seeds=agg.num_seeds,
            pct_of_ceiling=pct_of_ceiling,
            is_below_ceiling=is_below_ceiling,
            bound_class=bound_class,
            family=family,
            cv=agg.cv,
            source_run=source_run,
            seeds=list(seeds)
        )

    def _classify_bound_class(self, shape: str, dtype: str) -> str:
        """
        Classify a cell as ALU-bound or DDR-bound.

        GEMV / memory-bound / decode shapes (M≤128 or N≤64 or K≤64) are DDR-bound.
        """
        parts = shape.lower().split("x")
        if len(parts) >= 2:
            try:
                m = int(parts[0])
                n = int(parts[1])
                k = int(parts[2]) if len(parts) >= 3 else 1024
                if m <= 128 or n <= 64 or k <= 64:
                    return "DDR"
            except ValueError:
                pass
        return "ALU"
