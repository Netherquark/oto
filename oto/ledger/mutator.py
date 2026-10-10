#!/usr/bin/env python3
"""mutator.py — Option H Phase 1: proposal ledger, outcome, novelty.

Three things live here, in the order the pipeline needs them:

  1. `classify_outcome`  — what a candidate actually did (H.3.8), as a pure
     function over a phase's on-disk CSVs.
  2. `Mutator`            — emits candidates into the ledger, decides novelty,
     and remembers which neighbourhoods have proven unproductive.

What is deliberately NOT here: legality sampling (Phase 2), coverage-guided
parent selection and replication (Phase 3), and synthesis (Phase 4). Phase 1 is
the ledger and the outcome signal; `scheduler.mutate_winner` remains the
sampler until Hplan.6 replaces it.

Two rules this module exists to enforce:

  **One CSV reader.** Every read of a benchmark CSV goes through
  `analytics.AnalyticsEngine` — `load_benchmark_csv` for values,
  `count_benchmark_rows` for shape. Neither indexes the column headed
  `GFlops` to decide anything: in these files that column is a problem index,
  not a throughput. Reading it is what made an entire mutant population look
  zero-yield when it was productive (retracted; see changelog 2026-10-05).

  **The ledger is append-only.** `registry.resolve_proposal` advances
  `pending -> terminal` exactly once and silently no-ops thereafter. There is no
  delete path here or in the registry.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import oto.tensile.legality as legality
from oto.metrics.analytics import AnalyticsEngine
from oto.device.peaks import FAMILY_DTYPE_CHAR

#: Knobs owned by the caller's phase template. The sampler returns only the
#: Re-exported from `legality`, the single owner: this module assembles nothing,
#: it only strips the caller's keys from what `legality` built.
from oto.tensile.legality import TEMPLATE_KEYS  # noqa: E402,F401

#: Candidate draws attempted per cell. The prior replaced a lattice that emitted
#: 59 mutants from one winner, ~25 of which collided on fingerprints; novelty
#: filtering makes an extra draw cost an RNG step rather than a phase, so this is
#: deliberately generous and tunable rather than tuned.
DEFAULT_DRAWS_PER_CELL = 8

# Outcome vocabulary. Terminal values may only be written to a pending row.
OUTCOME_PENDING = "pending"
OUTCOME_FUNCTIONAL = "functional"
OUTCOME_NON_FUNCTIONAL = "non_functional"
OUTCOME_LEGAL_REJECTED = "legal_rejected"
OUTCOME_LEGAL_SLOW = "legal_slow"

TERMINAL_OUTCOMES = frozenset({
    OUTCOME_FUNCTIONAL,
    OUTCOME_NON_FUNCTIONAL,
    OUTCOME_LEGAL_REJECTED,
    OUTCOME_LEGAL_SLOW,
})

ORIGIN_NOVEL = "novel"
ORIGIN_REPLICATE = "replicate"

# Default consecutive-failure count before a neighbourhood is down-weighted.
# Named here (not buried in a call site) because H.3.8 makes it a parameter.
DEFAULT_NEGATIVE_CACHE_K = 3


def _per_cell_medians(analytics: AnalyticsEngine,
                      records: List[Dict[str, Any]],
                      dtype_override: Optional[str] = None) -> Dict[tuple, float]:
    """Median throughput per `(dtype, shape)` for one phase's records.

    Uses the same `aggregate_by_cell` + `aggregate_cell` path as the report, so
    the per-cell numbers compared against the reference bars are the numbers the
    report itself would show. Re-aggregating here by some cheaper rule would let
    the verdict and the report disagree about the same measurement.

    `dtype_override` is not optional in practice: without it every key comes back
    `(dtype='Unknown', shape)`, no bar ever matches, and `legal_slow` silently
    never fires. The dtype lives in the phase id (or the deck entry for it), not
    in the CSV, exactly as `ab_audit.phase_records` already handles.
    """
    from oto.metrics.policy import aggregate_cell
    out: Dict[tuple, float] = {}
    try:
        cell_map = analytics.aggregate_by_cell(records,
                                               dtype_override=dtype_override)
    except Exception:
        return out
    for (dtype, shape, _fp), seeds in cell_map.items():
        try:
            out[(str(dtype).upper(), str(shape))] = aggregate_cell(seeds).median
        except Exception:
            continue
    return out


def classify_outcome(
    phase_dir: Path,
    analytics: AnalyticsEngine,
    slow_threshold: Optional[float] = None,
    slow_bars: Optional[Dict[tuple, Dict[str, Any]]] = None,
) -> tuple:
    """Decide what a candidate did, from its on-disk output alone.

    Pure function, CPU-only, no registry access. Returns
    `(outcome, detail)` where detail is a small dict for the ledger/report and
    never for a verdict.

      functional       at least one benchmark record with non-zero throughput
      legal_slow       functional, but materially below how the reference ran
      non_functional   a CSV exists and has rows, all of them non-positive
      legal_rejected   no CSV at all, or CSVs present but with no rows

    The functional/non_functional split is decided *solely* by
    `analytics.load_benchmark_csv`. `count_benchmark_rows` only distinguishes
    "rows that did not survive the loader" from "no rows", which the loader
    cannot express because it drops non-positive rows by design.

    **`legal_slow` is relative to the gfx900 reference, never an absolute
    constant.** Two bars exist, and neither is a literal:

    * `slow_threshold` — an absolute GFlops bar. Retained for tests and for a
      caller that genuinely wants one, but it is the wrong instrument for real
      use: cells here span 4 to 857 GFlops, so any single absolute number either
      condemns every small cell or none of them.
    * `slow_bars` — per-cell bars from `coverage.reference_thresholds`, each
      `reference_median * (1 - band/100)`, i.e. "how much slower than the
      shipped floor is too slow, given how noisily this corpus measures".

    A candidate is `legal_slow` only when *every* measured cell it produced is
    below its bar. That is the same all-or-nothing reading the absolute bar has
    always had, and it is the right one for a multi-shape sweep: a sweep is
    useful if *any* shape is competitive, so one good cell rescues the batch.

    Cells with no reference bar are **not** treated as slow. "The floor never ran
    here" is an absence of evidence, and inferring slowness from it would
    manufacture `legal_slow` verdicts for exactly the unexplored cells most worth
    exploring. Those cells are counted in `slow_unmatched_cells` instead.

    With neither bar supplied the verdict is `functional`, which is the honest
    answer: nothing has been justified as slow, so nothing is labelled slow.
    """
    phase_dir = Path(phase_dir)
    bench_dir = phase_dir / "2_BenchmarkData"
    csvs = sorted(bench_dir.glob("*.csv")) if bench_dir.exists() else []

    detail = {
        "csv_count": len(csvs),
        "record_count": 0,
        "row_count": 0,
        "max_gflops": None,
        "median_gflops": None,
        "winner_freq": None,
        "winner_freq_positive": False,
        "slow_bars_applied": 0,
        "slow_unmatched_cells": 0,
        "slow_reference_median": None,
    }

    if not csvs:
        return OUTCOME_LEGAL_REJECTED, detail

    records: List[Dict[str, Any]] = []
    rows = 0
    for csv_path in csvs:
        records.extend(analytics.load_benchmark_csv(csv_path))
        rows += analytics.count_benchmark_rows(csv_path)

    detail["record_count"] = len(records)
    detail["row_count"] = rows

    if not records:
        # Loader found nothing. Rows present => they were all non-positive.
        return (OUTCOME_NON_FUNCTIONAL if rows else OUTCOME_LEGAL_REJECTED), detail

    values = [float(r.get("GFLOPS", 0.0)) for r in records]
    values.sort()
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
    detail["max_gflops"] = values[-1]
    detail["median_gflops"] = median

    # WinnerFreq is recorded alongside the verdict, as H.3.8 requires. It is
    # observed, never decisive: a kernel that ran but never won its own
    # internal comparison is still functional. Read through
    # `AnalyticsEngine.read_column`/`winner_freq`, the canonical owner of
    # Tensile CSV column reading -- a second reader here would be a second set of
    # format assumptions, and it fails quietly: a mis-read column yields zeros,
    # which reads as "no kernel won".
    freq = analytics.winner_freq(csvs)
    if freq["max"] is not None:
        detail["winner_freq"] = freq["max"]
        detail["winner_freq_positive"] = freq["positive"]
        detail["winner_freq_n"] = freq["n"]

    if slow_threshold is not None and median < slow_threshold:
        return OUTCOME_LEGAL_SLOW, detail

    # Reference-relative slowness, per cell. Evaluated after the absolute bar so
    # a caller supplying both keeps the cheaper, stricter test's behaviour.
    if slow_bars:
        dtype = None
        try:
            dtype = analytics.extract_dtype_from_phase_id(phase_dir.name)
        except Exception:
            dtype = None
        per_cell = _per_cell_medians(analytics, records, dtype_override=dtype)
        judged: List[tuple] = []
        unmatched = 0
        for cell, med in sorted(per_cell.items()):
            bar = slow_bars.get(cell)
            if not bar or not bar.get("bar_gflops"):
                unmatched += 1
                continue
            judged.append((med, float(bar["bar_gflops"]),
                           float(bar.get("reference_median") or 0.0)))
        detail["slow_bars_applied"] = len(judged)
        detail["slow_unmatched_cells"] = unmatched
        if judged:
            # The reference the slowest cell was judged against, for the report.
            detail["slow_reference_median"] = judged[0][2]
            if all(med < bar for med, bar, _ref in judged):
                return OUTCOME_LEGAL_SLOW, detail

    return OUTCOME_FUNCTIONAL, detail


@dataclass
class Proposal:
    """One emitted candidate, as recorded in the ledger."""

    fp: str
    family: Optional[str] = None
    shape: Optional[str] = None
    parent_fp: Optional[str] = None
    origin: str = ORIGIN_NOVEL
    iteration: Optional[int] = None
    run_id: Optional[str] = None
    outcome: str = OUTCOME_PENDING
    build_class: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)


class Mutator:
    """Ledger-backed mutator for the convergence loop.

    Emits through `registry.record_proposal`, never through
    `scheduler.append_to_phases`. The overlay is how candidates reach the
    runner without touching the curated deck (H.3.7).
    """

    def __init__(
        self,
        registry,
        base_dir: Path,
        analytics: Optional[AnalyticsEngine] = None,
        negative_cache_k: int = DEFAULT_NEGATIVE_CACHE_K,
        slow_threshold: Optional[float] = None,
        seed: int = 0,
        reference_slow: bool = True,
    ):
        self.registry = registry
        self.base_dir = Path(base_dir)
        self.analytics = analytics or AnalyticsEngine(registry, self.base_dir)
        self.negative_cache_k = negative_cache_k
        self.slow_threshold = slow_threshold
        self.seed = seed
        # `legal_slow` bars, resolved lazily from the gfx900 reference chain on
        # first use rather than here. `coverage.reference_thresholds` scans every
        # run directory and registry row (~90s on the live corpus), and
        # `arm_record_sets` constructs a driver, which constructs a Mutator -- so
        # doing it in `__init__` is both expensive and, in that construction path,
        # re-entrant. `reference_slow=False` opts out entirely, which is the
        # right call for tests and for any run that must not touch the corpus.
        self.reference_slow = reference_slow
        self._slow_bars: Optional[Dict[tuple, Dict[str, Any]]] = None
        self._slow_bands: Optional[Dict[str, Any]] = None
        self._consecutive_failures: Dict[str, int] = {}
        # Start from durable history rather than empty: an in-memory counter that
        # resets on every process start under-reports a saturated neighbourhood,
        # which is the same class of bug as a novelty ledger that has been
        # deleted (see `registry.coverage_view` on the empty-table case).
        self.rebuild_negative_cache()

    # -- sampler ------------------------------------------------------

    def sample_candidate(self,
                         family: str,
                         base_config: Optional[Dict[str, Any]] = None,
                         groups: int = 2,
                         seed: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return manifest-legal candidate knobs for ``family``.

        Phase 2 (Hplan.4): the knob values are drawn from what Tensile actually
        ships for this family, so the reject set is never proposed rather than
        proposed and then filtered. Returns only the *knobs* -- the caller owns
        Architecture / ScheduleName / FamilyLabel through its own template.

        ``None`` means the family is not in the manifest or no draw survived the
        hard walls; the caller should skip the cell rather than fall back to the
        lattice, because a lattice draw is exactly what the prior replaces.
        """
        if family not in FAMILY_DTYPE_CHAR:
            return None
        config = legality.sample_legal(
            self.base_dir,
            family,
            random.Random(seed if seed is not None else self.seed),
            base_config=base_config,
            groups=groups,
        )
        if config is None:
            return None
        return {k: v for k, v in config.items() if k not in TEMPLATE_KEYS}

    def sample_cell(self,
                    family: str,
                    base_config: Optional[Dict[str, Any]] = None,
                    groups: int = 2,
                    draws: int = DEFAULT_DRAWS_PER_CELL,
                    seed: Optional[str] = None) -> List[Dict[str, Any]]:
        """Draw up to ``draws`` legal candidates for one cell.

        Duplicates are *not* removed here: the caller checks each against the
        novelty ledger, which is the single owner of fingerprint de-duplication
        (H.3.5). Over-drawing is therefore cheap -- it costs an RNG draw, not a
        phase.
        """
        out: List[Dict[str, Any]] = []
        for i in range(max(0, draws)):
            knobs = self.sample_candidate(
                family,
                base_config=base_config,
                groups=groups,
                seed=None if seed is None else f"{seed}:{i}",
            )
            if knobs is not None:
                out.append(knobs)
        return out

    def sample_cell_synthesized(self,
                     family: str,
                     base_config: Optional[Dict[str, Any]] = None,
                     cell: Optional[Dict[str, Any]] = None,
                     groups: int = 2,
                     draws: int = DEFAULT_DRAWS_PER_CELL,
                     seed: Optional[str] = None,
                     band_pct: Optional[float] = None,
                     shape: Optional[str] = None,
                     sweeps: Optional[Dict[str, List[str]]] = None,
                     ) -> Dict[str, Any]:
        """Phase 4 synthesis for one cell: coverage-guided draws plus a sweep.

        Returns the `synthesis.synthesize_cell` summary rather than a bare knob
        list, because the caller needs two things the sampler cannot decide for
        it: the cell's state (so a retired cell can be skipped) and the shape
        sweep (so the candidate is graded rather than born ungradable —
        `Hplan.1` item 5).

        The ≤2-knob lattice remains the deterministic fallback via
        `synthesis.synthesize_or_lattice`; `sample_cell` above is retained for
        callers that only want knobs.
        """
        import oto.tensile.synthesis.manifest as synthesis

        return synthesis.synthesize_cell(
            self.base_dir, family, base_config=base_config, cell=cell,
            groups=groups, draws=draws, seed=seed, band_pct=band_pct,
            shape=shape, sweeps=sweeps)

    # -- novelty ------------------------------------------------------

    def is_novel(self, fp: str) -> bool:
        """True iff fp is absent from both the ledger and the decided set.

        The mutation arm bypasses the identical-fp skip *because* this is
        structural. If the ledger is missing or unreadable, that bypass is no
        longer justified, so `ledger_available()` exists and the caller must
        check it: a novelty-only ledger over a non-functional search makes a run
        look productive while measuring nothing (Hplan.3 step 11).
        """
        return self.registry.is_novel(fp)

    def ledger_available(self) -> bool:
        """True iff the ledger can actually be consulted.

        Guards the skip-bypass. A missing table means every fp looks novel,
        which is the exact failure mode the ledger exists to prevent.
        """
        try:
            self.registry.outcome_histogram()
            return True
        except Exception:
            return False

    # -- emission -----------------------------------------------------

    def emit(self, proposal: Proposal) -> bool:
        """Record one candidate. Returns False if it was already known.

        Callers check novelty first; this is the durable second half of that
        decision, so the two cannot drift.
        """
        return self.registry.record_proposal(
            fp=proposal.fp,
            family=proposal.family,
            shape=proposal.shape,
            parent_fp=proposal.parent_fp,
            origin=proposal.origin,
            iteration=proposal.iteration,
            run_id=proposal.run_id,
        )

    def emit_candidate_phase(self, proposal: Proposal, phase_id: str,
                             phase_data: Dict[str, Any]) -> bool:
        """Record a candidate and the phase that will run it, atomically.

        Two separate writes would leave a proposal in the ledger with no phase
        that ever ran it, which then reads as `pending` forever: its `n` never
        grows and the cell is routed to `replicate` on every subsequent pass,
        indistinguishable from a config that was measured and found unstable.
        """
        return self.registry.emit_proposal_with_phase(
            fp=proposal.fp,
            family=proposal.family,
            shape=proposal.shape,
            parent_fp=proposal.parent_fp,
            origin=proposal.origin,
            iteration=proposal.iteration,
            run_id=proposal.run_id,
            phase_id=phase_id,
            phase_data=phase_data,
        )

    # -- outcome ------------------------------------------------------

    def resolve(self, fp: str, outcome: str, build_class: Optional[str] = None) -> bool:
        """Write back a candidate's outcome, at most once.

        Also feeds the negative cache, which is the only state that changes what
        gets sampled next. A second write-back is a no-op and does not touch the
        cache, because the first verdict is the one that counts.
        """
        applied = self.registry.resolve_proposal(fp, outcome, build_class)
        if applied:
            self._note_outcome(fp, outcome)
        return applied

    def slow_bars(self) -> Dict[tuple, Dict[str, Any]]:
        """Per-cell `legal_slow` bars derived from the gfx900 reference chain.

        Resolved once, on first use, and cached even when it comes back empty:
        an unmeasurable reference should cost one scan, not one per phase. An
        empty result means "no cell can be judged slow", which is the correct
        outcome for a corpus with no recalled floor rather than a reason to keep
        retrying.
        """
        if self._slow_bars is not None:
            return self._slow_bars
        if not self.reference_slow:
            self._slow_bars = {}
            return self._slow_bars
        try:
            import oto.metrics.coverage as coverage
            resolved = coverage.reference_thresholds(self.base_dir)
            self._slow_bars = dict(resolved.get("bars") or {})
            self._slow_bands = {k: resolved.get(k) for k in
                                ("band_pct", "band_source", "reference_runs",
                                 "available")}
        except Exception:
            self._slow_bars = {}
            self._slow_bands = {"available": False}
        return self._slow_bars

    def slow_threshold_for(self, cell) -> Optional[float]:
        """The bar for one `(dtype, shape)` cell, or None if unjudgeable."""
        if cell is None:
            return None
        bar = self.slow_bars().get((str(cell[0]).upper(), str(cell[1])))
        return float(bar["bar_gflops"]) if bar else None

    def resolve_phase_dir(
        self,
        fp: str,
        phase_dir: Path,
        build_class: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> tuple:
        """Classify a phase's output, persist the evidence, then write the verdict.

        Returns `(outcome, detail)`; outcome is OUTCOME_PENDING when the row was
        already resolved, so the caller can see that nothing was overwritten.

        The observation is appended *before* the verdict is written. If the
        process dies between them the evidence survives and the row stays
        `pending`, which is recoverable; the other order would leave a decided
        verdict with no recorded evidence behind it, which is not.
        """
        outcome, detail = classify_outcome(
            phase_dir, self.analytics, self.slow_threshold,
            slow_bars=self.slow_bars() if self.reference_slow else None,
        )
        try:
            self.registry.append_observation(
                fp=fp, outcome=outcome, detail=detail, run_id=run_id,
                phase_dir=str(phase_dir))
        except Exception:
            # Evidence persistence must not block the verdict. A ledger that
            # cannot record why it decided something is still better than one
            # that never decides anything.
            pass
        if self.resolve(fp, outcome, build_class):
            return outcome, detail
        return OUTCOME_PENDING, detail

    # -- negative cache -----------------------------------------------

    def _note_outcome(self, fp: str, outcome: str) -> None:
        """Track consecutive failures per parent neighbourhood."""
        row = self.registry.get_proposal(fp)
        parent = (row or {}).get("parent_fp")
        if not parent:
            return
        if outcome == OUTCOME_NON_FUNCTIONAL:
            self._consecutive_failures[parent] = self._consecutive_failures.get(parent, 0) + 1
        else:
            self._consecutive_failures[parent] = 0

    def rebuild_negative_cache(self) -> Dict[str, int]:
        """Reconstruct the cache from the durable ledger, and return it.

        The cache used to be a plain in-memory counter, which meant a fresh
        process started with an empty cache: a neighbourhood that had already
        produced k consecutive non-functional children looked untouched, so the
        down-weighting silently switched off at every restart. That is not a
        cache that is "cold" -- it is a cache that reports a state the ledger
        contradicts.

        Rebuilt by replaying the outcome stream in resolution order, because
        `consecutive` is a claim about sequence: two failures then a success is
        not three consecutive failures, and replaying in arbitrary order would
        say otherwise.
        """
        try:
            stream = self.registry._outcome_stream()
        except Exception:
            return self._consecutive_failures
        failures: Dict[str, int] = {}
        for parent_fp, _fp, outcome in stream:
            if outcome == OUTCOME_NON_FUNCTIONAL:
                failures[parent_fp] = failures.get(parent_fp, 0) + 1
            else:
                failures[parent_fp] = 0
        # Only non-zero counters are kept: a parent with zero consecutive
        # failures is not saturated, and `neighbourhood_saturated` reads a
        # missing key the same way, so storing zeros would only inflate the dict.
        self._consecutive_failures = {k: v for k, v in failures.items() if v}
        return dict(self._consecutive_failures)

    def neighbourhood_saturated(self, parent_fp: str) -> bool:
        """True once this parent has produced k consecutive non-functional children.

        Replayed against the archived corpus today this returns False
        everywhere, because every measured mutant row is non-zero — the cache is
        a forward guarantee, not a retrospective cleaner. That test is
        deliberate: it is what stops the cache from firing on data it should not.
        """
        return self._consecutive_failures.get(parent_fp, 0) >= self.negative_cache_k

    def consecutive_failures(self, parent_fp: str) -> int:
        return self._consecutive_failures.get(parent_fp, 0)

    # -- overlay ------------------------------------------------------

    @property
    def overlay_name(self) -> str:
        return "phases.overlay.yaml"

    def write_overlay(self, candidates: Sequence[Dict[str, Any]], run_id: Optional[str] = None) -> Path:
        """Write this run's candidates to a per-run overlay.

        `phases.yaml` is the curated deck and stays that way. An overlay is
        disposable by construction: discarding a bad batch deletes this file and
        nothing else, so no history is edited to undo a mistake.
        """
        import yaml

        if run_id is None:
            run_id = self.registry.latest_run_id() or "unbound"
        target_dir = self.base_dir / "gfx90c_results" / "overlays"
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"phases.{run_id}.overlay.yaml"
        payload = {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "note": (
                "Per-run candidate overlay (Option H H.3.7). Not curated. "
                "phases.yaml is authoritative for the deck; this file exists so "
                "the mutation arm can run without writing to it."
            ),
            "phases": list(candidates),
        }
        with open(path, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)
        return path

    def load_overlay(self, run_id: str) -> List[Dict[str, Any]]:
        """Read back one run's overlay, or [] if there is none."""
        import yaml

        path = self.base_dir / "gfx90c_results" / "overlays" / f"phases.{run_id}.overlay.yaml"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                payload = yaml.safe_load(f) or {}
        except Exception:
            return []
        return payload.get("phases", []) or []