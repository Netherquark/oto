#!/usr/bin/env python3
"""The convergence loop: harvest, mutate, decide, repeat.

Owns: ``ConvergenceAgent`` -- the composition root over the convergence verdict
(:class:`ConvergenceMixin`), parent selection (harvest) and the mutation loop
(:class:`MutateLoopMixin`), plus the band it grades against and the mutation-arm
gate that decides whether novelty is verifiable.
Does NOT own: the ledger-backed mutation (oto.ledger.mutator), the gates that
judge a candidate (oto.tensile.gates), or the phase runner (oto.runners).
Public API: ConvergenceAgent, ConvergenceVerdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pathlib import Path

from oto.device.peaks import FAMILY_DTYPE_CHAR
from oto.ledger.agent_coverage import CoverageMixin
from oto.ledger.harvest import HarvestMixin
from oto.ledger.mutator import Mutator, Proposal
from oto.metrics.analytics import AnalyticsEngine, CellAnalytics
import oto.metrics.coverage as coverage
from oto.metrics.coverage import (STATE_REPLICATE, STATE_RETIRED,  # noqa: E402
                                decide_state)
from oto.tensile.candidate import CandidateGenerator, CandidateConfig


@dataclass
class ConvergenceVerdict:
    """Result of convergence check."""
    converged: bool
    reason: str
    below_ceiling_cells: List[Dict[str, Any]]
    iterations: int
    budget_remaining: int


class ConvergenceAgent(HarvestMixin, CoverageMixin):
    """The one-shot convergence loop.

    Harvest a winner, mutate it by at most two knobs, re-measure, repeat until
    the convergence verdict or the budget says stop. Deterministic: the driver
    decides the next candidate with no LLM in the loop.
    """

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
        # DB-hooked synthesis (Option H overhaul, 2026-10-09). The manifest
        # sampler alone decays to a trickle and never touches the wall
        # families; the DB mutator re-combines measured tile donors with the
        # forward-knob space so every iteration emits novel mutants. Built
        # only when a ledger-backed mutator exists (it delegates to it).
        self.db_mutator = None
        if mutator is not None:
            try:
                from db_mutator import DBMutator
                self.db_mutator = DBMutator(self.base_dir, mutator)
            except Exception:
                self.db_mutator = None
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
        settled_cells: List[str] = []
        lattice_fallbacks: List[str] = []
        ungraded_cells: List[str] = []

        for cell_key, winner_info in winners.items():
            family = str(winner_info.get("family") or "").upper()
            data_type = FAMILY_DTYPE_CHAR.get(
                family, str(winner_info.get("dtype", "S")).upper())
            shape = winner_info["shape"]
            winner_config = winner_info.get("config", {})

            # Active-cell filter (Option H overhaul, 2026-10-09). Only mutate
            # cells whose winner is still BELOW the realistic ceiling: a cell at
            # or above the bar has converged, and re-drawing its neighbourhood
            # is how the old arm spent its budget re-measuring noise. Cells
            # with no is_below_ceiling flag (older analytics) are mutated, so
            # the filter never silently starves a cell that lacks the signal.
            if winner_info.get("is_below_ceiling") is False:
                settled_cells.append(cell_key)
                continue

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
                # DB-hooked synthesis first (Option H overhaul): wide (DB tile
                # donors) + narrow (forward knobs) + direction (floor steal),
                # guaranteed novel by construction. Falls back to the manifest
                # sampler when the DB is unavailable.
                if self.db_mutator is not None and self.db_mutator.has_db():
                    mutants = self.db_mutator.synthesize_mutants(
                        family, winner_config, shape,
                        random.Random(f"{self.iteration}:{cell_key}"),
                        n=8)
                    sweep_shapes = self._shape_sweeps().get(family, [shape])
                else:
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
                        # Mutations are never auto-skipped (Option H, user
                        # directive 2026-10-09): the identical-fp skip must not
                        # apply to a mutant, so a mutation is measured even when
                        # an identical config was tested before. Novelty is the
                        # mutator's job (it guarantees a novel fp by
                        # construction), not the runner's skip.
                        "bypass_identical_skip": True,
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
            "settled_cells": sorted(set(settled_cells)),
            "lattice_fallback_cells": lattice_fallbacks,
            "ungraded_cells": sorted(set(ungraded_cells)),
            "graded_cells": len({r["phase_id"] for r in replayed
                                 if len(r.get("shapes") or ()) >= 2}),
            "band_pct": self.band(),
        }

        self.iteration += 1
        return new_candidates
