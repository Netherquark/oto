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
import statistics
from pathlib import Path
from typing import Dict, List, Any, Optional, Sequence, Tuple, Set
from collections import defaultdict
import re

from gfx90c_common import (
    PEAK_GFLOPS,
    FAMILY_DTYPES,
    FAMILY_SHAPES,
    FAMILY_DTYPE_CHAR,
    REALISTIC_CEILINGS,
    DTYPE_TO_FAMILY,
    cube_side,
    family_from_kernel_name,
    kernel_typecode,
)
from policy import aggregate_cell

# Minimum share of an arm's samples that must carry a real per-phase clock
# before a clock-adjusted statistic is trusted for that cell. Below this the
# clocked subset is not the same population the unadjusted best is drawn from,
# so its max is not comparable and the cell is graded unadjusted instead.
CLOCK_MIN_COVERAGE = 0.5


# Family prefix -> Tensile DataType char (lowercase keys for phase_id parsing).
FAMILY_TO_DTYPE = {
    k.lower(): v for k, v in FAMILY_DTYPE_CHAR.items()
}
# NOTE: 'auto' is deliberately NOT in FAMILY_TO_DTYPE. The auto candidate pool
# names its phases `phase_auto_<n>_<family>_<shape>_<i>`; with 'auto' in the
# token table, extract_family_from_phase_id greedily matched the 4-char 'auto'
# prefix (before 'hh'/'cc'...') and every phase_auto_* phase resolved to family
# 'auto' -> dtype 'S'. That single bug landed HH/CC/DD kernels in the SS cells
# (the §13.2 contamination: 4 S cells "won" by phase_*_hh_* phases, CC/ZZ auto
# phases counted as SS too). The pool prefix is a generator namespace, never a
# family; the family token always follows it.

# Known family prefixes (longest first for greedy matching).
# Note: family tokens are matched against lowercase phase_id segments, so the
# prefix set must be lowercase regardless of the canonical FAMILY_DTYPE_CHAR.
_KNOWN_FAMILIES = sorted(FAMILY_TO_DTYPE.keys(), key=len, reverse=True)


def extract_family_from_phase_id(phase_id: str) -> str:
    """Extract multi-letter family key from a phase_id (e.g. 'phase_hh_hpa_...' → 'hh_hpa').

    Matches the longest known family token sequence anywhere on a token boundary,
    so prefix tokens (e.g. 'draft_SS_...', 'draft_HH_HPA_...') still resolve.

    Last resort: a bare single-letter dtype token ('phase_auto_0_S_256...'),
    mapped through FAMILY_DTYPE_CHAR ('S' -> 'ss'). 'auto'/'phase' namespace
    tokens never count as families.
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
    if not best:
        for tok in parts:
            fam = DTYPE_TO_FAMILY.get(tok.upper(), "")
            if fam:
                return fam.lower()
    return best


# Canonical cell families (upper-case, HPA variants separate).
_KNOWN_CELL_FAMILIES = ("SS", "DD", "HH", "CC", "ZZ", "HH_HPA", "HS_HPA")


def _hpa_variant(stamp: str) -> bool:
    """True when a family stamp is an HPA variant ('HH_HPA'/'HS_HPA').

    HPA cells are distinguished by their explicit FamilyLabel/config stamp, and
    by nothing else — their kernel typecode reads 'HH' (leading 'H'), which is
    why typecode resolution must never collapse them into HH.
    """
    return str(stamp).upper().endswith("_HPA")


def resolve_cell_family(rec: Dict[str, Any]) -> str:
    """Cell (family) attribution for one benchmark record — the anti-contamination resolver.

    Precedence (first hit wins), per the §13.2 typecode-filter rule:

      1. kernel typecode of the record's own kernel name (``kernel`` / ``fp`` /
         ``phase_id`` fallback): SB/DB/HB/CB/ZB + HHS/HSS -> family. This is the
         ground truth of what the kernel actually computes, and overrides a
         lying or missing phase-level stamp — the vector that put
         ``phase_auto_1_hh_1024x1024x1024_3`` into the SS:1024 cell was exactly
         a phase_id text ('auto' prefix) overriding the kernel's real family.
      2. the record's explicit ``family`` stamp, UNLESS it contradicts (1);
         HPA stamps are always kept (see _hpa_variant).
      3. family parsed from ``phase_id``.
      4. DataType char via DTYPE_TO_FAMILY.
      5. '' (record is unattributable; callers skip it).
    """
    kernel_name = str(rec.get("kernel") or rec.get("kernel_name")
                      or rec.get("fingerprint") or rec.get("fp") or "")
    tcode_fam = family_from_kernel_name(kernel_name)
    stamp = str(rec.get("family") or rec.get("cell_key", "").split(":")[0] or "").upper()

    if stamp in _KNOWN_CELL_FAMILIES and _hpa_variant(stamp):
        return stamp

    if tcode_fam:
        if stamp in _KNOWN_CELL_FAMILIES and stamp != tcode_fam:
            print(f"[contamination] {str(rec.get('phase_id', ''))} carries "
                  f"family stamp {stamp} but its kernel typecode is "
                  f"{kernel_typecode(kernel_name)} ({tcode_fam}) — attributing "
                  f"to {tcode_fam} (typecode wins)")
            return tcode_fam
        return tcode_fam

    if stamp in _KNOWN_CELL_FAMILIES:
        return stamp

    fam = extract_family_from_phase_id(str(rec.get("phase_id", ""))).upper()
    if fam in _KNOWN_CELL_FAMILIES:
        return fam

    fam = DTYPE_TO_FAMILY.get(str(rec.get("DataType") or rec.get("dtype") or "").upper(), "")
    return fam if fam in _KNOWN_CELL_FAMILIES else ""


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
        seeds: Optional[List[float]] = None
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
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return 0
                return sum(1 for _ in reader)
        except Exception as e:
            print(f"Error counting rows in CSV {csv_path}: {e}")
            return 0

    def read_column(self, csv_path: Path, column: str) -> List[float]:
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
        out: List[float] = []
        if not Path(csv_path).exists():
            return out
        try:
            with open(csv_path, "r") as f:
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

    def winner_freq(self, csv_paths: Sequence[Path]) -> Dict[str, Any]:
        """WinnerFreq summary over one or more benchmark CSVs.

        Returns `{"max": float|None, "positive": bool, "n": int}`. Observed, never
        decisive: a kernel that ran but never won its own internal comparison is
        still functional, which is why `positive` is reported alongside `max`
        rather than folded into an outcome.
        """
        values: List[float] = []
        for path in csv_paths or ():
            values.extend(self.read_column(Path(path), "WinnerFreq"))
        if not values:
            return {"max": None, "positive": False, "n": 0}
        return {"max": max(values), "positive": any(v > 0 for v in values),
                "n": len(values)}

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

    def aggregate_by_cell_typecode(
        self,
        records: List[Dict[str, Any]],
        phase_family: str = ""
    ) -> Dict[Tuple[str, str, str, str], List[float]]:
        """Aggregate benchmark records by (dtype, shape, fp, family) with the
        typecode-first family filter.

        Each record's family is resolved by its OWN kernel typecode
        (``resolve_cell_family``) — the §13.2 rule: SB/DB/HB/CB/ZB decide the
        cell, and HHS/HSS kernels (fp16-family) never land in SS cells. The
        per-phase family (from phase_id text) is the fallback only, never the
        primary signal. Returns cells keyed (dtype, shape, fp, family) so the
        caller's CellAnalytics carries the resolved family, not a text guess.
        """
        cell_map = defaultdict(list)
        for rec in records:
            if not rec.get("family"):
                rec = dict(rec)
                rec["family"] = phase_family
            fam = resolve_cell_family(rec)
            if not fam:
                continue
            shape = rec.get("ProblemType", rec.get("shape", "Unknown"))
            fp = rec.get("fingerprint", rec.get("fp", "unknown"))
            gflops = rec.get("GFLOPS", rec.get("median_gflops", 0.0))
            if gflops > 0:
                dtype = FAMILY_DTYPE_CHAR.get(fam, rec.get("DataType", ""))
                cell_map[(dtype, shape, fp, fam)].append(gflops)
        return cell_map

    def compute_cell_analytics(
        self,
        dtype: str,
        shape: str,
        fp: str,
        seeds: List[float],
        ceiling_gflops: Optional[float] = None,
        red_threshold_pct: float = 50.0,
        family: str = "",
        source_run: str = ""
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

    def compute_native_vs_spoof_delta(
            self,
            native_records: List[Dict[str, Any]],
            spoof_records: List[Dict[str, Any]],
            agg: str = "winner",
            tie_band_pct: float = 5.0,
            sclk_by_phase: Optional[Dict[Tuple[str, str], float]] = None,
            sclk_ref: Optional[float] = None
        ) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
            """per-cell native-vs-spoof pairing.

            A workload cell is (family/dtype, cube shape) and MUST match on
            both arms — the mapping key cell_key = "FAMILY:SIDE" synthesized
            from the authoritative config identity (never re-derived from
            phase_id text, so HH_HPA/HS_HPA stay distinct).

            Every statistic is derived per-kernel-median-first, so a single
            lucky seed can never decide a verdict:

              best_median  the cell's best per-kernel median — the deck winner
              worst_median the cell's worst per-kernel median — the deck's
                           weakest kernel, the input to the "better in every
                           way" (dominance) reading
              floor_best   native median vs floor's best per-kernel median
              strict       native worst vs floor's best per-kernel median
              winner       both arms' best per-kernel median
              median       median of the per-kernel medians in the cell
                           (spoof side under the default; the shipped floor's
                           representative number)
              winner_clock both arms' best per-kernel median, telemetry-adjusted:
                           each kernel's median is scaled by
                           (sclk_ref / sclk_measured) from that phase's own
                           sustained core clock, so a kernel that happened to run
                           cool is not credited with being slow. Falls back to
                           the unadjusted best per-kernel median for any cell
                           lacking clock data, and flags it (clock_adjusted)
                           rather than reporting an adjusted-looking number.
              median_clock same normalization on both arms' median
              throttle     sclk-adjusted feed (GFLOPS_throttle_adjusted stamped
                           at emit time when telemetry is available; falls back
                           to the unadjusted median when no sample was stamped)
              best         max single raw sample — kept for reference only, too
                           seed-noisy to grade on

            The default comparison is ASYMMETRIC on purpose: the native deck is
            a candidate pool graded by its winner (max per-kernel median), while
            the spoof arm is the already-shipped floor graded by its median of
            per-kernel medians. delta_pct is therefore exactly
            native_best_median / spoof_median - 1, and matches the report's
            "Best native median" / "Spoof median" columns term for term.

            Be aware this grades the deck against the floor's TYPICAL kernel,
            not its best one, and the gap is large in some cells (the floor's
            per-kernel medians span a wide range), so a deck that loses to the
            floor's best kernel can still post a large WIN here. Use
            agg='winner' for the strict drop-in-replacement reading.

            Both arms are CORPUS-WIDE, not per-run: every record passed in is a
            candidate, whatever run produced it. A run is allowed to contribute
            no new cells of its own (every phase deduped as
            identical_fp_already_passed) while the historical winners remain the
            real native candidates — so winners, including older winner runs, are
            picked across the whole record set. Each cell also reports which
            run/phase produced its winning kernel (native_winner_*), the runs
            that contributed (native_runs), and whether the throttle feed was
            actually clock-adjusted (throttle_adjusted).

            Args:
                native_records: Records from native runs (deck candidates)
                spoof_records: Records from spoof runs (shipped gfx900 floor)
                sclk_by_phase: (source_run, phase_id) -> sustained core clock in Hz,
                    from that run's telemetry timeline; required by the *_clock bases
                sclk_ref: single corpus-wide reference clock in Hz that every arm is
                    normalized TO (one constant for both arms, so no arm is
                    rescaled in its own favour)
                agg: 'median' | 'best_median' | 'floor_best' | 'strict' | 'winner'
                    | 'winner_clock' | 'median_clock' | 'throttle' | 'best'
                tie_band_pct: Parity band (default ±5%)

            Returns:
                Dict keyed by (dtype, shape, cell_label) to cell stats + winner,
                with n_kernels/n_samples/n_runs provenance for citation.
            """
            # (cell-family resolver is module-level resolve_cell_family — the
            # §13.2 typecode-filter rule applied uniformly, see its docstring)

            def _collect(records: List[Dict[str, Any]],
                         sclk_by_gkey: Optional[Dict[Tuple[str, str], float]] = None,
                         sclk_ref: Optional[float] = None
                         ) -> Dict[Tuple[str, int], Dict[str, Any]]:
                samples: Dict[Tuple[str, int], List[float]] = defaultdict(list)
                # Group key includes the source run: the same (phase_id,
                # fingerprint) is benchmarked by more than one run, and pooling
                # those samples into one "kernel median" would average across
                # runs instead of taking each run's measurement on its own.
                groups: Dict[Tuple[str, int], Dict[Tuple[str, str, str], List[float]]] = defaultdict(lambda: defaultdict(list))
                meta: Dict[Tuple[str, str, str], Tuple[str, str, str]] = {}
                throttled: Dict[Tuple[str, int], List[float]] = defaultdict(list)
                for rec in records:
                    fam = resolve_cell_family(rec)
                    if not fam:
                        continue
                    side = cube_side(rec.get("ProblemType") or rec.get("shape") or "")
                    if not side:
                        continue
                    gf = float(rec.get("GFLOPS") or rec.get("median_gflops") or 0.0)
                    if gf <= 0:
                        continue
                    key = (fam, side)
                    src = str(rec.get("source_run") or rec.get("run_id") or "")
                    phase_id = str(rec.get("phase_id", ""))
                    fp = str(rec.get("fingerprint", ""))
                    gkey = (src, phase_id, fp)
                    samples[key].append(gf)
                    groups[key][gkey].append(gf)
                    meta[gkey] = (src, phase_id, fp)
                    adj = rec.get("GFLOPS_throttle_adjusted")
                    if adj:
                        throttled[key].append(float(adj))
                stats: Dict[Tuple[str, int], Dict[str, Any]] = {}
                for key, gs in groups.items():
                    # Per-kernel median first, THEN the cell statistic. Comparing
                    # raw max samples instead would let a single lucky seed
                    # decide the verdict (seed noise dwarfs real config deltas).
                    kernel_meds = {gk: statistics.median(v) for gk, v in gs.items() if v}
                    if not kernel_meds:
                        continue
                    # Telemetry-normalized twin of the same per-kernel medians:
                    # GFLOPS is linear in core clock, so a kernel measured at
                    # sclk_meas is scaled to the corpus reference clock by
                    # (sclk_ref / sclk_meas). Per-kernel factor => the scaled
                    # median is exactly median * factor, so no seed is re-used.
                    # Only kernels with real per-phase clock data are eligible,
                    # and coverage is reported so an unadjusted number can never
                    # be presented as an adjusted one.
                    #
                    # ASSUMPTION: throughput proportional to core clock. That holds
                    # for ALU-bound kernels but OVER-corrects memory-bound ones
                    # (GFM/GEMM small shapes, whose ceiling is set by mclk/DRAM,
                    # not sclk), so a clock-adjusted delta on a DDR-bound cell is
                    # an extrapolation, not a measurement. Both the adjusted and
                    # the unadjusted statistic are reported per cell for that
                    # reason.
                    kernel_meds_clock: Dict[Tuple[str, str, str], float] = {}
                    n_samples_cell = sum(len(v) for v in gs.values())
                    n_clock = 0
                    if sclk_by_gkey and sclk_ref:
                        for gk, med in kernel_meds.items():
                            hz = sclk_by_gkey.get((gk[0], gk[1]))
                            if hz and hz > 0:
                                kernel_meds_clock[gk] = med * (sclk_ref / hz)
                                n_clock += len(gs[gk])
                    # A clock-adjusted BEST is only meaningful if it is the best
                    # over the same population the unadjusted best is drawn from.
                    # With partial coverage the eligible subset is a different,
                    # unrepresentative sample, and its max can sit far below the
                    # unadjusted max — which would silently make the arm with
                    # worse coverage look slower. So the clock figures are only
                    # trusted above a coverage floor, and the cell is otherwise
                    # graded unadjusted (both arms together, never one-sided).
                    coverage = (n_clock / n_samples_cell) if n_samples_cell else 0.0
                    clock_ok = coverage >= CLOCK_MIN_COVERAGE
                    if not clock_ok:
                        kernel_meds_clock = {}
                    med = statistics.median(kernel_meds.values())
                    winner = max(kernel_meds, key=lambda gk: kernel_meds[gk])
                    src, phase_id, fp = meta[winner]
                    runs = sorted({g[0] for g in kernel_meds if g[0]})
                    thr = statistics.median(throttled[key]) if throttled[key] else med
                    clock_winner = (max(kernel_meds_clock, key=lambda gk: kernel_meds_clock[gk])
                                    if kernel_meds_clock else None)
                    stats[key] = {
                        "best": max(samples[key]),
                        "best_median": kernel_meds[winner],
                        "worst_median": min(kernel_meds.values()),
                        "best_median_clock": (kernel_meds_clock[clock_winner]
                                              if clock_winner else 0.0),
                        "median_clock": (statistics.median(kernel_meds_clock.values())
                                         if kernel_meds_clock else 0.0),
                        "clock_coverage": coverage,
                        "clock_ok": bool(clock_ok),
                        "clock_sclk_hz": (sclk_by_gkey.get((clock_winner[0], clock_winner[1]), 0.0)
                                          if clock_winner else 0.0),
                        "clock_kernels": len(kernel_meds_clock),
                        "median": med,
                        "throttle": thr,
                        "throttle_adjusted": bool(throttled[key]),
                        "n_kernels": len(kernel_meds),
                        "n_samples": len(samples[key]),
                        "n_runs": len(runs),
                        "runs": runs,
                        "origin": {
                            "gflops": kernel_meds[winner],
                            "run_id": src,
                            "phase_id": phase_id,
                            "fingerprint": fp,
                        },
                    }
                return stats

            def _stat(stats: Dict[str, Any], which: str, agg: str) -> float:
                """Resolve one arm's comparison statistic.

                Bases, from lenient to strict. `which` is 'native' or 'spoof'.

                  median      both arms: median of per-kernel medians
                  best_median native: best per-kernel median (deck winner);
                              spoof:  median of per-kernel medians
                  floor_best  native: median of per-kernel medians;
                              spoof:  best per-kernel median (floor winner)
                  strict      native: WORST per-kernel median;
                              spoof:  best per-kernel median
                  winner      both arms: best per-kernel median
                  throttle    sclk-adjusted feed, else median
                  best        max single raw sample (seed-noisy, reference only)

                'floor_best' is the basis for "is a typical native kernel better
                than the best kernel the floor ships" — it cannot be won by
                cherry-picking one lucky config, because the native side is
                graded on its median. 'strict' is the literal "truly better in
                every way" test: the native arm's WORST kernel must still beat
                the floor's BEST kernel, which is per-cell dominance rather
                than an average.
                """
                native_key = {
                    "median": "median",
                    "best_median": "best_median",
                    "floor_best": "median",
                    "strict": "worst_median",
                    "winner": "best_median",
                    "winner_clock": "best_median_clock",
                    "median_clock": "median_clock",
                }.get(agg, agg)
                spoof_key = {
                    "median": "median",
                    "best_median": "median",
                    "floor_best": "best_median",
                    "strict": "best_median",
                    "winner": "best_median",
                    "winner_clock": "best_median_clock",
                    "median_clock": "median_clock",
                }.get(agg, agg)
                key = native_key if which == "native" else spoof_key
                val = stats.get(key, 0.0)
                # A clock basis with no per-phase clock data for this arm falls
                # back to the SAME statistic unadjusted (best per-kernel median),
                # and the cell is flagged via clock_adjusted below — never
                # silently presented as a clock-corrected number.
                if not val and key.endswith("_clock"):
                    val = stats.get(key[:-6]) or stats["median"]
                return float(val)

            ns = _collect(native_records, sclk_by_phase, sclk_ref)
            ss = _collect(spoof_records, sclk_by_phase, sclk_ref)

            deltas: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
            for key in sorted(set(ss) & set(ns)):
                fam, side = key
                sv, nv = ss[key], ns[key]
                native_val = _stat(nv, "native", agg)
                spoof_val = _stat(sv, "spoof", agg)
                # Both arms must be clock-covered or NEITHER is adjusted: a
                # half-adjusted delta would compare a clock-corrected arm against
                # an unadjusted one, which no longer cancels.
                clock_ok = bool(nv["clock_ok"] and sv["clock_ok"] and sclk_ref)
                if agg.endswith("_clock") and not clock_ok:
                    # Fall back to the SAME basis without the clock normalization
                    # (winner_clock -> winner, median_clock -> median), so a
                    # missing telemetry file degrades to the plain comparison
                    # instead of silently switching to a different statistic.
                    plain = agg[:-len("_clock")]
                    native_val = _stat(nv, "native", plain)
                    spoof_val = _stat(sv, "spoof", plain)
                if spoof_val <= 0 or native_val <= 0:
                    continue
                ratio = native_val / spoof_val
                delta_pct = (ratio - 1.0) * 100.0
                tie = abs(delta_pct) <= tie_band_pct
                verdict = "TIE" if tie else ("WIN" if ratio > 1.0 else "LOSS")
                dtype = FAMILY_DTYPE_CHAR.get(fam, "")
                deltas[(dtype, f"{side}x{side}x{side}", f"cell_{fam}_{side}")] = {
                    "native_value": native_val,
                    "spoof_value": spoof_val,
                    "native_median": nv["median"],
                    "spoof_median": sv["median"],
                    "native_best_median": nv["best_median"],
                    "spoof_best_median": sv["best_median"],
                    "native_worst_median": nv["worst_median"],
                    "spoof_worst_median": sv["worst_median"],
                    "native_best": nv["best"],
                    "spoof_best": sv["best"],
                    "native_throttle": nv["throttle"],
                    "spoof_throttle": sv["throttle"],
                    "throttle_adjusted": bool(nv["throttle_adjusted"] and sv["throttle_adjusted"]),
                    "native_best_median_clock": nv["best_median_clock"],
                    "spoof_best_median_clock": sv["best_median_clock"],
                    "native_median_clock": nv["median_clock"],
                    "spoof_median_clock": sv["median_clock"],
                    "native_clock_coverage": nv["clock_coverage"],
                    "spoof_clock_coverage": sv["clock_coverage"],
                    "native_clock_kernels": nv["clock_kernels"],
                    "spoof_clock_kernels": sv["clock_kernels"],
                    "native_clock_sclk_hz": nv["clock_sclk_hz"],
                    "spoof_clock_sclk_hz": sv["clock_sclk_hz"],
                    "sclk_ref_hz": float(sclk_ref or 0.0),
                    # True only when BOTH arms actually had per-phase clock data
                    # for this cell, i.e. the delta really is clock-normalized.
                    "clock_adjusted": bool(clock_ok and agg.endswith("_clock")),
                    "clock_basis": bool(agg.endswith("_clock")),
                    "cell_key": f"{fam}:{side}",
                    "spoof_fp": f"cell_{fam}_{side}",
                    "family": fam,
                    "agg": agg,
                    "delta_pct": delta_pct,
                    "tie": tie,
                    "verdict": verdict,
                    "n_native_kernels": nv["n_kernels"],
                    "n_spoof_kernels": sv["n_kernels"],
                    "n_native_runs": nv["n_runs"],
                    "n_spoof_runs": sv["n_runs"],
                    "native_runs": nv["runs"],
                    "spoof_runs": sv["runs"],
                    "native_winner_run": nv["origin"].get("run_id", ""),
                    "native_winner_phase": nv["origin"].get("phase_id", ""),
                    "native_winner_fp": nv["origin"].get("fingerprint", ""),
                    "spoof_winner_run": sv["origin"].get("run_id", ""),
                    "spoof_winner_phase": sv["origin"].get("phase_id", ""),
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
