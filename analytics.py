#!/usr/bin/env python3
"""
analytics.py — Stage 5: Analytics & Append-Only Registry

Per-cell analytics, native-vs-spoof deltas, realistic ceiling utilization,
and RED-list generation. Feeds seeds to Stage 2, verdicts to Stage 6/7.

Key mechanics:
- Load raw records straight from `gfx90c_runs/*.json` (the live native-run ledger, see `results.md` §1)
- Per-cell analytics: winner via N8 median-of-seeds, spread ratio,
  % of family-realistic ceiling (with decode DDR exemption)
- RED-list of under-performing compute cells
- Native-vs-spoof per-cell deltas: same-run only; withhold when no same-run pair
- Append-only DB: sqlite3 records INSERT; rows never edited/deleted
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
import re

from gfx90c_common import PEAK_GFLOPS, FAMILY_DTYPES, THEORETICAL_PEAKS, DDR_ROOFLINE_GBPS
from policy import aggregate_cell, classify_stability


# Realistic ceilings from gfx90c_theoretical_limits.md §5 (empirical, 69-98% of theoretical)
REALISTIC_CEILINGS = {
    "FP32": 1118.7,
    "FP16": 2461.0,
    "BF16": 1108.5,
    "INT8": 881.2,
    "FP64": 98.6,
    "SS": 1118.7,
    "DD": 98.6,
    "HH": 2461.0,
    "ZZ": 98.6,    # complex double (DataType Z) → FP64 rate
    "CC": 1118.7,  # complex single (DataType C) → FP32 rate
    "HH_HPA": 1118.7,
    "HS_HPA": 1118.7,
}

# Family-to-dtype mapping for phase_id parsing
FAMILY_TO_DTYPE = {
    'ss': 'S', 'dd': 'D', 'hh': 'H', 'zz': 'Z',
    'cc': 'C', 'hh_hpa': 'H', 'hs_hpa': 'H', 'auto': 'S'
}

# Known family prefixes (longest first for greedy matching)
_KNOWN_FAMILIES = ['hh_hpa', 'hs_hpa', 'ss', 'dd', 'hh', 'zz', 'cc']


def extract_family_from_phase_id(phase_id: str) -> str:
    """Extract multi-letter family key from a phase_id (e.g. 'phase_hh_hpa_...' → 'hh_hpa').

    Matches the longest known family token sequence anywhere on a token boundary,
    so prefix tokens (e.g. 'draft_SS_...', 'draft_HH_HPA_...') still resolve.
    """
    parts = [p for p in str(phase_id).replace('phase_', '').replace('phase', '').split('_') if p]
    best = ''
    best_len = 0
    for fam in sorted(_KNOWN_FAMILIES, key=len, reverse=True):
        fam_tokens = fam.split('_')
        if len(fam_tokens) <= best_len:
            continue
        for i in range(len(parts) - len(fam_tokens) + 1):
            if parts[i:i + len(fam_tokens)] == fam_tokens:
                best = fam
                best_len = len(fam_tokens)
                break
    return best


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
        is_red: bool,
        bound_class: str = "ALU",
        family: str = ""
    ):
        self.dtype = dtype
        self.shape = shape
        self.config_fp = config_fp
        self.median_gflops = median_gflops
        self.spread_ratio = spread_ratio
        self.num_seeds = num_seeds
        self.pct_of_ceiling = pct_of_ceiling
        self.is_red = is_red
        self.bound_class = bound_class
        self.family = family  # e.g. 'ss', 'hh_hpa', 'hs_hpa', 'cc', 'zz'


class AnalyticsEngine:
    """Stage 5 analytics engine."""

    def __init__(self, registry, base_dir: Path):
        self.registry = registry
        self.base_dir = Path(base_dir)
        self.results_dir = self.base_dir / "gfx90c_results"
        self._phases_cache = None

    def _load_phases_manifest(self) -> List[Dict[str, Any]]:
        """Load and cache phases.yaml manifest."""
        if self._phases_cache is None:
            phases_path = self.base_dir / "phases.yaml"
            if phases_path.exists():
                import yaml
                with open(phases_path, 'r') as f:
                    self._phases_cache = yaml.safe_load(f) or []
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
        # (unlike a raw [a-z_]+ regex) survives digit-bearing suffixes such as
        # 'phase_ss_spoof_baseline_vega10' where the regex silently produced
        # 'unknown' dtypes.
        family = extract_family_from_phase_id(norm_id)
        dtype = FAMILY_TO_DTYPE.get(family)
        if dtype:
            return dtype

        return 'unknown'

    def load_benchmark_csv(self, csv_path: Path) -> List[Dict[str, Any]]:
        """
        Load a Tensile benchmark CSV file, stripping field whitespace
        and extracting per-kernel GFlops measurements.

        Args:
            csv_path: Path to 2_BenchmarkData/*.csv or 00_Final.csv

        Returns:
            List of parsed benchmark records
        """
        records = []
        if not csv_path.exists():
            return records
        try:
            with open(csv_path, "r") as f:
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
        records: List[Dict[str, Any]],
        dtype_override: Optional[str] = None
    ) -> Dict[Tuple[str, str, str], List[float]]:
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

    def compute_cell_analytics(
        self,
        dtype: str,
        shape: str,
        fp: str,
        seeds: List[float],
        ceiling_gflops: Optional[float] = None,
        red_threshold_pct: float = 50.0,
        family: str = ""
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

        Returns:
            CellAnalytics object
        """
        agg = aggregate_cell(seeds)

        # Lookup realistic ceiling first, then peak
        if ceiling_gflops is None:
            ceiling_gflops = REALISTIC_CEILINGS.get(
                family.upper() if family else dtype,
                REALISTIC_CEILINGS.get(dtype, PEAK_GFLOPS.get(dtype, 1613.0))
            )

        pct_of_ceiling = (agg.median / ceiling_gflops) * 100.0 if ceiling_gflops > 0 else 0.0

        # Determine bound class (ALU vs DDR)
        bound_class = self._classify_bound_class(shape, dtype)

        # RED-list: under-performing compute cells
        # DDR cells exempt from ALU-compute RED status
        is_red = (bound_class == "ALU" and pct_of_ceiling < red_threshold_pct)

        return CellAnalytics(
            dtype=dtype,
            shape=shape,
            config_fp=fp,
            median_gflops=agg.median,
            spread_ratio=agg.spread_ratio,
            num_seeds=agg.num_seeds,
            pct_of_ceiling=pct_of_ceiling,
            is_red=is_red,
            bound_class=bound_class,
            family=family
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

    def compute_native_vs_spoof_delta(
        self,
        native_records: List[Dict[str, Any]],
        spoof_records: List[Dict[str, Any]],
        tie_band_pct: float = 5.0
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """
        Compute native-vs-spoof deltas for same-run pairs only.

        Args:
            native_records: Records from native ScheduleName="isa" runs
            spoof_records: Records from spoof ScheduleName="vega10" runs
            tie_band_pct: Parity band (default ±5%)

        Returns:
            Dict mapping (dtype, shape) to delta info
        """
        native_by_cell = defaultdict(list)
        spoof_by_cell = defaultdict(list)

        for rec in native_records:
            dtype = rec.get("DataType", rec.get("dtype", ""))
            shape = rec.get("ProblemType", rec.get("shape", ""))
            gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
            if gflops > 0:
                native_by_cell[(dtype, shape)].append(gflops)

        for rec in spoof_records:
            dtype = rec.get("DataType", rec.get("dtype", ""))
            shape = rec.get("ProblemType", rec.get("shape", ""))
            gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
            if gflops > 0:
                spoof_by_cell[(dtype, shape)].append(gflops)

        deltas = {}
        for key in set(native_by_cell.keys()) & set(spoof_by_cell.keys()):
            native_seeds = native_by_cell[key]
            spoof_seeds = spoof_by_cell[key]

            if native_seeds and spoof_seeds:
                native_agg = aggregate_cell(native_seeds)
                spoof_agg = aggregate_cell(spoof_seeds)

                delta_pct = (
                    ((native_agg.median - spoof_agg.median) / spoof_agg.median * 100.0)
                    if spoof_agg.median > 0 else 0.0
                )

                tie = abs(delta_pct) <= tie_band_pct
                if tie:
                    verdict = "TIE"
                elif delta_pct > 0:
                    verdict = "WIN"
                else:
                    verdict = "LOSS"

                deltas[key] = {
                    "native_median": native_agg.median,
                    "spoof_median": spoof_agg.median,
                    "delta_pct": delta_pct,
                    "tie": tie,
                    "verdict": verdict,
                    "native_seeds": len(native_seeds),
                    "spoof_seeds": len(spoof_seeds)
                }

        return deltas

    def generate_red_list(
        self,
        all_analytics: List[CellAnalytics]
    ) -> List[Dict[str, Any]]:
        """
        Generate RED-list of under-performing compute cells.
        """
        return [
            {
                "dtype": a.dtype,
                "shape": a.shape,
                "fp": a.config_fp,
                "median_gflops": a.median_gflops,
                "pct_of_ceiling": a.pct_of_ceiling,
                "bound_class": a.bound_class
            }
            for a in all_analytics
            if a.is_red
        ]

    def persist_analytics(
        self,
        run_id: str,
        analytics: List[CellAnalytics],
        deltas: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None
    ) -> None:
        """
        Persist analytics results to the append-only registry.
        """
        for a in analytics:
            record = {
                "type": "cell_analytics",
                "run_id": run_id,
                "dtype": a.dtype,
                "shape": a.shape,
                "fp": a.config_fp,
                "median_gflops": a.median_gflops,
                "spread_ratio": a.spread_ratio,
                "num_seeds": a.num_seeds,
                "pct_of_ceiling": a.pct_of_ceiling,
                "is_red": a.is_red,
                "bound_class": a.bound_class
            }
            self.registry.append_record(record, run_id=run_id)

        if deltas:
            for (dtype, shape), delta_info in deltas.items():
                record = {
                    "type": "native_vs_spoof_delta",
                    "run_id": run_id,
                    "dtype": dtype,
                    "shape": shape,
                    **delta_info
                }
                self.registry.append_record(record, run_id=run_id)
