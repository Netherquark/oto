#!/usr/bin/env python3
"""
analytics.py — Stage 5: Analytics & Append-Only Registry

Per-cell analytics, native-vs-spoof deltas, realistic ceiling utilization.
Feeds seeds to Stage 2, verdicts to Stage 6/7.

Key mechanics:
- Per-cell analytics: winner via N8 median-of-seeds, spread ratio, CV, and
  % of family-realistic ceiling (with decode DDR exemption)
- Native-vs-spoof per-cell deltas: every spoof entity vs the best native
  median at the same (dtype, shape); the spoof arm is the recalled gfx900
  shipped reference run (cross-run, never re-run)
- Append-only DB: sqlite3 records INSERT; rows never edited/deleted
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict
import re

from gfx90c_common import (
    PEAK_GFLOPS,
    FAMILY_DTYPES,
    FAMILY_SHAPES,
    FAMILY_DTYPE_CHAR,
    REALISTIC_CEILINGS,
)
from policy import aggregate_cell


# Family prefix -> Tensile DataType char (lowercase keys for phase_id parsing).
FAMILY_TO_DTYPE = {
    k.lower(): v for k, v in FAMILY_DTYPE_CHAR.items()
}
FAMILY_TO_DTYPE["auto"] = "S"

# Known family prefixes (longest first for greedy matching).
# Note: family tokens are matched against lowercase phase_id segments, so the
# prefix set must be lowercase regardless of the canonical FAMILY_DTYPE_CHAR.
_KNOWN_FAMILIES = sorted(FAMILY_TO_DTYPE.keys(), key=len, reverse=True)


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
        is_below_ceiling: bool,
        bound_class: str = "ALU",
        family: str = "",
        cv: float = 0.0
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
        # (unlike a raw [a-z_]+ regex) survives digit-bearing phase ids.
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
            cv=agg.cv
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
        ) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
            """
            Native-vs-spoof deltas: every spoof benchmark entity is measured against
            the BEST native median at the same (dtype, shape).

            A spoof entity is a (dtype, shape, fingerprint) cell of the gfx900 spoof
            library. The native side is the best per-config median for that shape —
            the deck winner — which is the number a shipped deck must beat.

            Args:
                native_records: Records from native ScheduleName="isa" runs
                spoof_records: Records from spoof ScheduleName="vega10" runs
                tie_band_pct: Parity band (default ±5%)

            Returns:
                Dict keyed by (dtype, shape, spoof_fp) to delta info with the spoof
                entity's median vs the best native median.
            """
            native_cell: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
            for rec in native_records:
                dtype = rec.get("DataType", rec.get("dtype", ""))
                shape = rec.get("ProblemType", rec.get("shape", ""))
                fp = rec.get("fingerprint", rec.get("fp", "unknown"))
                gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
                if gflops > 0:
                    native_cell[(dtype, shape, fp)].append(gflops)

            # Best native median per (dtype, shape) — the deck winner to beat.
            best_native: Dict[Tuple[str, str], float] = {}
            for (dtype, shape, _fp), seeds in native_cell.items():
                cell_median = aggregate_cell(seeds).median
                key = (dtype, shape)
                if cell_median > best_native.get(key, 0.0):
                    best_native[key] = cell_median

            spoof_cell: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
            for rec in spoof_records:
                dtype = rec.get("DataType", rec.get("dtype", ""))
                shape = rec.get("ProblemType", rec.get("shape", ""))
                fp = rec.get("fingerprint", rec.get("fp", "unknown"))
                gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
                if gflops > 0:
                    spoof_cell[(dtype, shape, fp)].append(gflops)

            # Per-entity family from the spoof phase_id (HH / HH_HPA / HS_HPA etc).
            fp_family: Dict[str, str] = {}
            for rec in spoof_records:
                fp = rec.get("fingerprint", rec.get("fp"))
                fid = rec.get("phase_id", "")
                if fp and fp not in fp_family:
                    fam = extract_family_from_phase_id(fid)
                    if fam:
                        fp_family[fp] = fam

            deltas = {}
            for (dtype, shape, fp), spoof_seeds in spoof_cell.items():
                native_best = best_native.get((dtype, shape))
                if native_best is None or not spoof_seeds:
                    continue
                spoof_agg = aggregate_cell(spoof_seeds)
                spoof_median = spoof_agg.median

                delta_pct = (
                    ((native_best - spoof_median) / spoof_median * 100.0)
                    if spoof_median > 0 else 0.0
                )

                tie = abs(delta_pct) <= tie_band_pct
                if tie:
                    verdict = "TIE"
                elif delta_pct > 0:
                    verdict = "WIN"
                else:
                    verdict = "LOSS"

                deltas[(dtype, shape, fp)] = {
                    "native_median": native_best,
                    "spoof_median": spoof_median,
                    "spoof_fp": fp,
                    "family": fp_family.get(fp, ""),
                    "delta_pct": delta_pct,
                    "tie": tie,
                    "verdict": verdict,
                }

            return deltas

    def classify_cell_status(
        self,
        all_analytics: List[CellAnalytics],
        red_threshold_pct: float = 50.0
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Classify the gfx900 contract cells (family x deck shape) for the report.

        The contract grid is the shipped gfx900 footprint sampled at each
        family's canonical deck shapes (FAMILY_SHAPES). A cell is:

          RED    — MISSING: no candidate measurement at (family, shape) at all.
          ORANGE — measured but the best candidate median < red_threshold_pct
                   of the family realistic ceiling.
          GREEN  — measured and at/above the threshold.

        A cell's median is the best candidate median across configs at that
        shape — the deck winner the shipped floor must be compared against.
        """
        from collections import defaultdict

        measured: Dict[str, Set[str]] = defaultdict(set)
        best_per_cell: Dict[Tuple[str, str], float] = {}

        # dtype char -> family fallback for analytics rows missing a family tag.
        # setdefault keeps the FIRST family per char, so the ambiguous 'H'
        # (HH / HH_HPA / HS_HPA) resolves to canonical HH; the HPA variants are
        # only ever distinguished by their phase_id family prefix, never by char.
        dtype_to_family = {}
        for family, ch in FAMILY_DTYPE_CHAR.items():
            dtype_to_family.setdefault(ch, family)

        for a in all_analytics:
            fam = str(a.family or "").upper()
            if fam not in FAMILY_SHAPES:
                fam = dtype_to_family.get(str(a.dtype).upper(), "")
            if not fam or fam not in FAMILY_SHAPES:
                continue
            measured[fam].add(a.shape)
            key = (fam, a.shape)
            if a.median_gflops > best_per_cell.get(key, 0.0):
                best_per_cell[key] = a.median_gflops

        def _entry(fam: str, shape: str, status: str, best: float) -> Dict[str, Any]:
            ceiling = REALISTIC_CEILINGS.get(
                fam, PEAK_GFLOPS.get(FAMILY_DTYPES.get(fam, "FP32"), 1613.0)
            )
            pct = (best / ceiling * 100.0) if ceiling > 0 else 0.0
            return {
                "family": fam,
                "shape": shape,
                "status": status,
                "median_gflops": round(best, 1),
                "pct_of_ceiling": round(pct, 1),
            }

        red: List[Dict[str, Any]] = []
        orange: List[Dict[str, Any]] = []
        green: List[Dict[str, Any]] = []

        for fam, sizes in FAMILY_SHAPES.items():
            for s in sizes:
                shape = f"{s}x{s}x{s}"
                best = best_per_cell.get((fam, shape), 0.0)
                if shape not in measured.get(fam, set()):
                    red.append(_entry(fam, shape, "MISSING", best))
                    continue
                entry = _entry(fam, shape, "GREEN", best)
                if entry["pct_of_ceiling"] < red_threshold_pct:
                    entry["status"] = "ORANGE"
                    orange.append(entry)
                else:
                    green.append(entry)

        return {"red": red, "orange": orange, "green": green}
