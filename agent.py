#!/usr/bin/env python3
"""
agent.py — Convergence Agent (harvest → mutate → loop)

The deterministic convergence engine for oto:
- Harvest winning configs from analytics results
- Mutate candidates (≤2 knobs) for below-ceiling or non-converged cells (via scheduler)
- Check convergence: no below-ceiling cells AND per-cell stability gates
- Record candidates in the append-only proposals ledger and route them to a
  per-run overlay (Option H Phase 1). Before Phase 1 these were appended to
  `phases.yaml`; see mutate_and_feed for the fallback that still can do that.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

import coverage
from scheduler import CandidateGenerator, CandidateConfig
from analytics import AnalyticsEngine, CellAnalytics
from gfx90c_common import FAMILY_DTYPE_CHAR
from mutator import Mutator, Proposal


@dataclass
class ConvergenceVerdict:
    """Result of convergence check."""
    converged: bool
    reason: str
    below_ceiling_cells: List[Dict[str, Any]]
    iterations: int
    budget_remaining: int


class ConvergenceAgent:
    """Deterministic convergence agent for oto."""

    def __init__(
        self,
        base_dir: Path,
        scheduler: CandidateGenerator,
        analytics: AnalyticsEngine,
        mutator=None,
        band_pct: Optional[float] = None
    ):
        self.base_dir = Path(base_dir)
        self.scheduler = scheduler
        self.analytics = analytics
        self.iteration = 0
        self.harvested_winners: Dict[str, Dict[str, Any]] = {}
        # Option H Phase 1 (implementation_plan.md Hplan.3 step 8). The ledger
        # is what makes bypassing the identical-fp skip correct, so its absence
        # is not a soft degradation -- it flips `skip_mutation_arm` back on.
        self.mutator = mutator
        self.ledger_enabled = bool(mutator and mutator.ledger_available())
        # Outcome feedback (H.3.8) is a separate capability from novelty. Kept as
        # its own flag so Hplan.3 step 11 ("revert the skip-bypass claim if phase 1
        # lands partially") is a one-line change rather than an audit.
        self.has_outcome_signal = bool(mutator) and callable(
            getattr(mutator, "resolve_phase_dir", None))
        # Which run this agent is emitting into. Without it every proposal lands
        # in the ledger with run_id=NULL, so "which run produced this candidate"
        # cannot be answered after the fact and the ledger cannot be scoped per
        # run. Set by the driver once its run dir exists.
        self.run_id: Optional[str] = None
        # Phase 4 (Hplan.6): coverage guidance and multi-shape grading. Both
        # caches are per-run — the deck does not change within a run, and the
        # ledger only grows, so recomputing per cell is pure waste.
        self._shape_sweeps_cache: Optional[Dict[str, List[str]]] = None
        self._coverage_cells_cache: Optional[
            Dict[Tuple[str, str], Dict[str, Any]]] = None
        #: Acceptance band. Supplied by the caller when it already knows it, and
        #: otherwise resolved lazily by `band()` -- never here. `ab_audit`'s
        #: `arm_record_sets` constructs an agent to manage phases, and
        #: `measured_band_pct` reaches `arm_record_sets`, so computing the band in
        #: `__init__` recurses until the stack gives out. A construction-time
        #: audit is also just expensive: every agent paid for a full arm scan.
        self.band_pct: Optional[float] = band_pct
        self._band_resolved: bool = band_pct is not None
        self._band_computing: bool = False

    def band(self) -> Optional[float]:
        """The measured acceptance band, computed at most once, or None.

        None means "no band available", which coverage reads as *no lower bound*
        -- synthesis then excludes nothing rather than guessing a threshold.
        """
        if self._band_resolved:
            return self.band_pct
        if self._band_computing:
            # Re-entered from inside `measured_band_pct` itself; the only safe
            # answer is the one we already know, which is: none yet.
            return None
        self._band_computing = True
        try:
            self.band_pct = coverage.measured_band_pct(self.base_dir)
        except Exception:
            self.band_pct = None
        finally:
            self._band_computing = False
            self._band_resolved = True
        return self.band_pct

    def skip_mutation_arm(self) -> bool:
        """Whether the mutation arm must honour the identical-fp skip.

        False only when the ledger is present *and* the outcome signal exists.
        Hplan.3 step 8 is explicit that the bypass is a correctness dependency on
        the ledger, not an optimisation: with no ledger, novelty cannot be
        established and every candidate looks novel. Step 11 adds the outcome
        requirement, because a novelty-only ledger over a non-functional search
        makes the run look productive while measuring nothing.

        The ledger probe is deliberately re-run on every call rather than cached
        in `self.ledger_enabled`. That flag is a construction-time snapshot; the
        table can be dropped or the DB swapped underneath a live agent, and a
        stale True would keep authorising a bypass whose justification is gone.
        """
        if not self.mutator:
            return True
        if not self.mutator.ledger_available():
            return True
        return not self.has_outcome_signal

    def converged(
        self,
        all_analytics: List[CellAnalytics],
        budget_remaining: int
    ) -> ConvergenceVerdict:
        """
        Check if the campaign has converged.

        Convergence criteria (ALL MUST HOLD for convergence):
        1. No below-ceiling ALU compute cells vs realistic ceilings.
        2. Every cell evaluated with >= 3 distinct configs.
        3. Every cell has >= 2 independent runs (>= 6 seeds).
        4. Stability: coefficient of variation <= 15% per cell.

        Budget exhaustion is a STOP, not convergence: unmet criteria (or no
        data) is never reported as converged.
        """
        below_ceiling_cells = [
            {
                "dtype": a.dtype,
                "shape": a.shape,
                "median_gflops": a.median_gflops,
                "pct_of_ceiling": a.pct_of_ceiling,
                "bound_class": a.bound_class,
                "fp": a.config_fp
            }
            for a in all_analytics
            if a.is_below_ceiling
        ]

        if not all_analytics:
            return ConvergenceVerdict(
                converged=False,
                reason="No analytics data available",
                below_ceiling_cells=[],
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        if budget_remaining <= 0:
            return ConvergenceVerdict(
                converged=False,
                reason=f"Budget exhausted ({len(below_ceiling_cells)} below-ceiling "
                       "cells remain; convergence not verified)",
                below_ceiling_cells=below_ceiling_cells,
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        unconverged_reasons = []
        if below_ceiling_cells:
            unconverged_reasons.append(
                f"{len(below_ceiling_cells)} below-ceiling cells remain")

        # Group analytics by (dtype, shape)
        cells_by_shape: Dict[Tuple[str, str], List[CellAnalytics]] = {}
        for a in all_analytics:
            key = (a.dtype, a.shape)
            cells_by_shape.setdefault(key, []).append(a)

        for (dt, shp), list_a in cells_by_shape.items():
            fps = {a.config_fp for a in list_a}
            total_seeds = sum(a.num_seeds for a in list_a)

            if len(fps) < 3:
                unconverged_reasons.append(
                    f"Cell ({dt}, {shp}) has only {len(fps)} configs (needs >= 3)")
                break

            if total_seeds < 6:
                unconverged_reasons.append(
                    f"Cell ({dt}, {shp}) has only {total_seeds} seeds "
                    "(needs >= 2 independent runs)")
                break

            if any(a.cv > 0.15 for a in list_a):
                worst = max(a.cv for a in list_a)
                unconverged_reasons.append(
                    f"Cell ({dt}, {shp}) CV {worst*100:.1f}% > 15% (unstable)")
                break

        if not unconverged_reasons:
            return ConvergenceVerdict(
                converged=True,
                reason="Fully converged: 0 below-ceiling cells, >=3 configs per cell, "
                       ">=2 independent runs, CV <= 15%",
                below_ceiling_cells=[],
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        return ConvergenceVerdict(
            converged=False,
            reason="; ".join(unconverged_reasons[:2]),
            below_ceiling_cells=below_ceiling_cells,
            iterations=self.iteration,
            budget_remaining=budget_remaining
        )

    def harvest(
        self,
        all_analytics: List[CellAnalytics],
        parent_by: str = "lcb"
    ) -> Dict[str, Dict[str, Any]]:
        """
        Harvest one parent config per (family, shape) cell.

        **Parent choice is by lower confidence bound, not raw winner**
        (`Hplan.5` step 3). `max(median_gflops)` is how a noise-level win becomes
        the parent of the next batch: a config whose median is high because one
        seed landed well outranks a config that is merely good. The LCB ranks by
        the lower bound, which demotes exactly that config. `parent_by="median"`
        remains available so the old rule can be compared, and the choice is
        recorded on every winner so a run's parent policy is visible after the
        fact.

        The family tag travels with the winner so downstream mutation rebuilds the
        correct Tensile DataType.
        """
        if parent_by not in ("lcb", "median"):
            raise ValueError(f"parent_by must be 'lcb' or 'median', got {parent_by!r}")

        winners = {}
        by_cell: Dict[str, List[CellAnalytics]] = {}

        for a in all_analytics:
            fam = a.family or a.dtype.lower()
            key = f"{fam}_{a.shape}"
            if key not in by_cell:
                by_cell[key] = []
            by_cell[key].append(a)

        for key, cell_analytics in by_cell.items():
            if parent_by == "median":
                best = max(cell_analytics, key=lambda a: a.median_gflops)
                score = best.median_gflops
            else:
                scored = [
                    (a, coverage.lower_confidence_bound(
                        a.seeds or self._cell_samples(a)))
                    for a in cell_analytics
                ]
                # Ties break on sample count, then on median: a well-measured
                # config is preferred over a lucky one even at equal bound.
                best, score = max(
                    scored,
                    key=lambda pair: (pair[1], pair[0].num_seeds,
                                      pair[0].median_gflops),
                )
            by_median = max(cell_analytics, key=lambda a: a.median_gflops)
            winners[key] = {
                "family": best.family,
                "dtype": best.dtype,
                "shape": best.shape,
                "fp": best.config_fp,
                "median_gflops": best.median_gflops,
                "pct_of_ceiling": best.pct_of_ceiling,
                "is_below_ceiling": best.is_below_ceiling,
                "bound_class": best.bound_class,
                "parent_score": score,
                "parent_by": parent_by,
                "n_seeds": best.num_seeds,
                "selected_by_lcb": best.config_fp != by_median.config_fp,
                "config": self._reconstruct_config(best)
            }

        self.harvested_winners = winners
        return winners

    def _cell_samples(self, analytics: CellAnalytics) -> List[float]:
        """Recover a cell's seed values when a caller built it without them.

        `compute_cell_analytics` attaches the seeds, so this is a fallback for
        cells assembled by hand. Returns an empty list rather than guessing,
        which degrades the LCB to the median instead of inventing a variance.
        """
        seed_reader = getattr(self.analytics, "seed_values", None)
        if seed_reader is None:
            return []
        try:
            return seed_reader(fingerprint=analytics.config_fp,
                               shape=analytics.shape)
        except Exception:
            return []

    def _reconstruct_config(self, analytics: CellAnalytics) -> Dict[str, Any]:
        """
        Reconstruct a Tensile config from registry, phases.yaml, or family-specific deck.
        """
        # 1. Search phases.yaml
        phases_path = self.base_dir / "phases.yaml"
        if phases_path.exists():
            try:
                with open(phases_path, "r") as f:
                    phases = yaml.safe_load(f) or []
                for p in phases:
                    if isinstance(p, dict) and p.get("fp") == analytics.config_fp:
                        return p.get("config", {})
            except Exception:
                pass

        # 2. Search SQLite records
        if hasattr(self.analytics, "registry") and self.analytics.registry is not None:
            records = self.analytics.registry.read_records()
            for r in records:
                if r.get("fp") == analytics.config_fp and "config" in r:
                    return r["config"]

        # 3. Family-aware default fallback tile from scheduler family decks
        fam = str(analytics.family or "").upper()
        deck = self.scheduler.family_decks.get(fam, self.scheduler.family_decks.get("SS", []))
        if deck:
            return dict(deck[0])

        return {
            "MacroTile": "64x64x16",
            "ThreadTile": "4x4",
            "NLCA": 1,
        }

    def _shape_sweeps(self) -> Dict[str, List[str]]:
        """Per-family shape sweeps, read once from the curated deck.

        The deck is the authority on what a *graded* config looks like, so the
        sweep is read from there rather than constructed. Cached because the deck
        does not change within a run and this sits on the per-cell path.
        """
        if self._shape_sweeps_cache is None:
            import synthesis
            path = self.base_dir / "phases.yaml"
            phases = []
            if path.exists():
                try:
                    with open(path) as f:
                        phases = yaml.safe_load(f) or []
                except Exception:
                    phases = []
            self._shape_sweeps_cache = synthesis.family_shape_sweeps(phases)
        return self._shape_sweeps_cache

    def _cell_coverage(self, family: str, shape: str) -> Optional[Dict[str, Any]]:
        """This cell's coverage evidence from the ledger, or None if unknown."""
        if self._coverage_cells_cache is None:
            self._coverage_cells_cache = self._load_coverage_cells()
        return self._coverage_cells_cache.get((str(family).upper(), str(shape)))

    def _cell_coverage_state(self, family: str, shape: str) -> Optional[str]:
        """The cell's coverage state, or None when the cell is not yet known."""
        cell = self._cell_coverage(family, shape)
        if cell is None:
            return None
        return coverage.decide_state(cell, band_pct=self.band())

    def _load_coverage_cells(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """Coverage evidence keyed by `(family, shape)`, for synthesis guidance.

        Failures yield an empty map, which means "no guidance available" and every
        cell stays `explore`. Guessing coverage from partial data would be worse
        than having none: an unknown cell must be searched, not retired.
        """
        if self.mutator is None:
            return {}
        try:
            reg = self.mutator.registry
            summary = coverage.coverage_summary(
                reg.all_proposals(),
                coverage.samples_by_fingerprint(
                    reg.read_records(record_type="benchmark_result")),
                band_pct=self.band(),
            )
        except Exception:
            return {}
        return {(c["family"], c["shape"]): c for c in summary["cells"]}

    def mutate_and_feed(
        self,
        winners: Dict[str, Dict[str, Any]],
        mutation_budget: int = 2
    ) -> List[CandidateConfig]:
        """
        Mutate harvested configs and record them in the proposals ledger.

        Two behaviours changed under Option H Phase 1, and both are the point of
        the phase:

        * **Candidates go to the ledger, not to `phases.yaml`.** The curated deck
          was previously appended to on every iteration and the mutants then
          skipped themselves on the next pass (defect D4). They now go to a
          per-run overlay via `mutator.write_overlay`, which `phases.yaml` is
          never asked about.
        * **Novelty is checked before emission.** A candidate whose fingerprint is
          already in the ledger or already decided by the registry is dropped,
          which is what stops iteration n+1 from re-proposing iteration n
          (defect D2).

        With no mutator configured this keeps the old append-to-phases.yaml
        behaviour, so the pre-Phase-1 path stays reachable for comparison. That
        fallback is not the default and should not become one.

        Args:
            winners: Dict of harvested winners from harvest()
            mutation_budget: Maximum knobs to mutate per candidate (default 2)

        Returns:
            List of emitted CandidateConfig objects
        """
        new_candidates: List[CandidateConfig] = []
        rejected_non_novel = 0
        replayed: List[Dict[str, Any]] = []
        retired_cells: List[str] = []
        lattice_fallbacks: List[str] = []
        ungraded_cells: List[str] = []

        for cell_key, winner_info in winners.items():
            family = str(winner_info.get("family") or "").upper()
            data_type = FAMILY_DTYPE_CHAR.get(
                family, str(winner_info.get("dtype", "S")).upper())
            shape = winner_info["shape"]
            winner_config = winner_info.get("config", {})

            # Sampler. Phase 4 (Hplan.6): coverage-guided constrained synthesis.
            # The prior (Phase 2) makes draws legal by construction; this adds
            # direction from the cell's coverage state and, critically, the shape
            # sweep that makes the candidate gradable (Hplan.1 item 5).
            #
            # A `retired` cell is skipped rather than sampled: every candidate in
            # it was non-functional, and re-drawing the same neighbourhood is what
            # the negative cache exists to stop.
            sweep_shapes: List[str] = []
            cell_state = None
            if self.mutator is not None:
                cell_state = self._cell_coverage_state(family, shape)
                if cell_state == coverage.STATE_RETIRED:
                    retired_cells.append(cell_key)
                    continue
                synth = self.mutator.sample_cell_synthesized(
                    family,
                    base_config=winner_config,
                    cell=self._cell_coverage(family, shape),
                    groups=mutation_budget,
                    seed=f"{self.iteration}:{cell_key}",
                    band_pct=self.band(),
                    shape=shape,
                    sweeps=self._shape_sweeps(),
                )
                sweep_shapes = synth.get("shapes") or []
                if synth.get("source") == "lattice":
                    lattice_fallbacks.append(cell_key)
                mutants = [c["knobs"] for c in synth.get("candidates", [])]
            else:
                mutants = self.scheduler.mutate_winner(winner_config, mutation_budget)

            for i, mutant in enumerate(mutants):
                phase_id = f"phase_auto_{self.iteration}_{cell_key}_{i}"
                label = f"mutate_{family.lower() or cell_key}_{i}"

                template = {
                    "Architecture": "gfx90c",
                    "DataType": data_type,
                    "ProblemType": "Contraction",
                    "ScheduleName": "isa",
                    "FamilyLabel": family,
                }

                shapes_for_candidate = (sweep_shapes
                                        if len(sweep_shapes) >= 2
                                        else [shape])
                candidate = self.scheduler.emit_candidate(
                    phase_id=phase_id,
                    label=label,
                    dtype=data_type.lower(),
                    shapes=list(shapes_for_candidate),
                    template=template,
                    knobs=mutant
                )

                # Keep validate_config as an assertion, not the search
                # (Hplan.4 step 4): a rejection is recorded with its reason
                # rather than silently dropped, so the ledger learns it too.
                is_valid, reason = self.scheduler.validate_config({**template, **mutant})
                if not is_valid:
                    if self.mutator:
                        self.mutator.registry.record_proposal(
                            fp=candidate.fingerprint,
                            family=family,
                            shape=shape,
                            parent_fp=winner_info.get("fp"),
                            iteration=self.iteration,
                            run_id=self.run_id,
                        )
                        self.mutator.resolve(
                            candidate.fingerprint,
                            "legal_rejected",
                            build_class=reason[:200],
                        )
                    continue

                if self.mutator and self.mutator.is_novel(candidate.fingerprint) is False:
                    rejected_non_novel += 1
                    continue

                new_candidates.append(candidate)
                if self.mutator:
                    # The family sweep, not [shape]. A mutant measured on one
                    # shape has no comparable ratio against a floor measured on
                    # several, so it is born ungradable (Hplan.1 item 5). Falls
                    # back to the single shape when the deck has no sweep, and
                    # records that in `ungraded_cells` rather than pretending.
                    shapes = sweep_shapes if len(sweep_shapes) >= 2 else [shape]
                    if len(shapes) < 2:
                        ungraded_cells.append(cell_key)
                    phase_entry = {
                        "phase_id": phase_id,
                        "fp": candidate.fingerprint,
                        "label": label,
                        "dtype": data_type.lower(),
                        "shapes": list(shapes),
                        "config": {**template, **mutant},
                        "origin": "novel",
                        "graded": len(shapes) >= 2,
                        "coverage_state": cell_state,
                    }
                    # One transaction for the ledger row and the phase. Two
                    # writes would let a crash leave a proposal with no phase
                    # that ever ran it -- permanently `pending`, so its `n`
                    # never grows and the cell is re-routed to `replicate`
                    # forever, indistinguishable from genuine instability.
                    self.mutator.emit_candidate_phase(
                        Proposal(
                            fp=candidate.fingerprint,
                            family=family,
                            shape=shape,
                            parent_fp=winner_info.get("fp"),
                            iteration=self.iteration,
                            run_id=self.run_id,
                        ),
                        phase_id=phase_id,
                        phase_data=phase_entry,
                    )
                    replayed.append(phase_entry)
                else:
                    # Pre-Phase-1 fallback. Retained only so the old path stays
                    # testable; note it writes to the curated deck.
                    self.scheduler.append_to_phases(candidate)

        if self.mutator and replayed:
            # Bound to this agent's run explicitly. Left implicit, the overlay
            # is keyed on `latest_run_id()`, which during a reference run is a
            # gfx900 floor run -- so the candidates would be written to an
            # overlay that `load_phases_manifest` never applies, and the arm
            # would emit into nothing.
            self.mutator.write_overlay(replayed, run_id=self.run_id)

        self.last_emission_stats = {
            "emitted": len(new_candidates),
            "rejected_non_novel": rejected_non_novel,
            "wrote_overlay": bool(self.mutator and replayed),
            "skip_mutation_arm": self.skip_mutation_arm(),
            # Phase 4 observability. A run that quietly fell back to the lattice,
            # or that emitted mutants with no shape sweep, looks identical to one
            # that did neither unless it is reported.
            "retired_cells": retired_cells,
            "lattice_fallback_cells": lattice_fallbacks,
            "ungraded_cells": sorted(set(ungraded_cells)),
            "graded_cells": len({r["phase_id"] for r in replayed
                                 if len(r.get("shapes") or ()) >= 2}),
            "band_pct": self.band(),
        }

        self.iteration += 1
        return new_candidates