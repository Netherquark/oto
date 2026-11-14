#!/usr/bin/env python3
"""The convergence loop: harvest, mutate, decide, repeat.

Owns: ``ConvergenceAgent`` -- the composition root over the three mixins it
combines: harvest (``oto.ledger.harvest.HarvestMixin``), coverage evidence
(``oto.ledger.agent_coverage.CoverageMixin``) and the mutation loop
(``oto.ledger.agent_mutation.MutateMixin``); the convergence verdict and the
band it grades against, plus the mutation-arm gate that decides whether
novelty is verifiable.
Does NOT own: the ledger-backed mutation (oto.ledger.mutator), the gates that
judge a candidate (oto.tensile.gates), or the phase runner (oto.runners).
Public API: ConvergenceAgent, ConvergenceVerdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oto.device.kernel_vocabulary import cell_key
from oto.ledger.agent_coverage import CoverageMixin
from oto.ledger.agent_mutation import MutateMixin
from oto.ledger.harvest import HarvestMixin
from oto.metrics import cell_coverage as coverage
from oto.metrics.benchmark_analytics import AnalyticsEngine, CellAnalytics
from oto.tensile.candidate import CandidateGenerator


@dataclass
class ConvergenceVerdict:
    """Result of convergence check."""
    converged: bool
    reason: str
    below_ceiling_cells: list[dict[str, Any]]
    iterations: int
    budget_remaining: int


class ConvergenceAgent(HarvestMixin, CoverageMixin, MutateMixin):
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
        band_pct: float | None = None
    ):
        self.base_dir = Path(base_dir)
        self.scheduler = scheduler
        self.analytics = analytics
        self.iteration = 0
        self.harvested_winners: dict[str, dict[str, Any]] = {}
        # Option H Phase 1 (docs/implementation_plan.md Hplan.3 step 8). The ledger
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
        self.run_id: str | None = None
        # Phase 4 (Hplan.6): coverage guidance and multi-shape grading. Both
        # caches are per-run — the deck does not change within a run, and the
        # ledger only grows, so recomputing per cell is pure waste.
        self._shape_sweeps_cache: dict[str, list[str]] | None = None
        self._coverage_cells_cache: dict[tuple[str, str], dict[str, Any]] | None = None
        #: Acceptance band. Supplied by the caller when it already knows it, and
        #: otherwise resolved lazily by `band()` -- never here. `ab_audit`'s
        #: `arm_record_sets` constructs an agent to manage phases, and
        #: `measured_band_pct` reaches `arm_record_sets`, so computing the band in
        #: `__init__` recurses until the stack gives out. A construction-time
        #: audit is also just expensive: every agent paid for a full arm scan.
        self.band_pct: float | None = band_pct
        self._band_resolved: bool = band_pct is not None
        self._band_computing: bool = False
        #: `(iteration, {FAMILY:SIDE -> A/B entry})` of cells that have not yet
        #: beaten the floor; empty means unreadable, and `_floor_losers` caches
        #: the scan per iteration because it walks every run (~90s).
        self._floor_losers_cache: tuple[int, dict[str, Any]] | None = None

    def band(self) -> float | None:
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

    def _floor_losers(self) -> dict[str, Any]:
        """Cells that have not yet beaten the recalled floor, by ``FAMILY:SIDE``.

        The floor is the frozen gfx900 shipped deck; ``cells_not_beating_floor``
        pairs it against every native record under the `winner` basis, so the
        set names the cells where this port's best kernel still fails to beat
        the floor's best. Cached per iteration (the scan is ~90s); an empty
        result means the floor is unavailable and the caller must fall back to
        the ceiling rule rather than conclude that nothing is left to do.
        """
        if (self._floor_losers_cache is not None
                and self._floor_losers_cache[0] == self.iteration):
            return self._floor_losers_cache[1]
        losers: dict[str, Any] = {}
        try:
            from oto.metrics import ab_audit
            native, floor, _chain = ab_audit.arm_record_sets(self.base_dir)
            losers = self.analytics.cells_not_beating_floor(native, floor)
        except Exception as e:
            print(f"[floor] cannot read the reference floor ({e}); mutation "
                  f"targeting falls back to the ceiling rule alone")
        self._floor_losers_cache = (self.iteration, losers)
        return losers

    def _cell_settled(self, winner_info: dict[str, Any]) -> bool:
        """Whether a cell is finished and must NOT be mutated.

        A cell earns a mutation for either of two independent reasons: it is
        still below its family's realistic ceiling, or it has not yet beaten the
        gfx900 floor. The second check runs *after* the ceiling rather than
        instead of it, because the ceilings are measured-empirical snapshots and
        the large cells have moved above their published value. Under the
        ceiling rule alone those cells are marked settled, so the mutation arm
        never proposes for them -- which is exactly what the 2026-10-18 run
        did: all 412 of its candidates went to small cells that already beat the
        floor by 100%+, and the tied large cells received none at all.

        When the floor cannot be read the ceiling rule stands alone, so an
        offline or floor-less corpus behaves exactly as before.
        """
        if winner_info.get("is_below_ceiling") is not False:
            return False
        losers = self._floor_losers()
        if not losers:
            return True
        key = cell_key(winner_info.get("family"), winner_info.get("shape"))
        return key is None or key not in losers

    def _collect_below_ceiling(self, all_analytics: list[CellAnalytics]) -> list[dict[str, Any]]:
        """Collect cells that are below the realistic ceiling."""
        return [
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

    def _check_budget(self, budget_remaining: int, below_ceiling_cells: list) -> ConvergenceVerdict | None:
        """Check if budget is exhausted. Returns verdict if exhausted, None otherwise."""
        if budget_remaining <= 0:
            return ConvergenceVerdict(
                converged=False,
                reason=f"Budget exhausted ({len(below_ceiling_cells)} below-ceiling "
                       "cells remain; convergence not verified)",
                below_ceiling_cells=below_ceiling_cells,
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )
        return None

    def _check_cell_requirements(self, all_analytics: list[CellAnalytics]) -> list[str]:
        """Check cell requirements: >=3 configs, >=6 seeds, CV <= 15%."""
        unconverged_reasons = []
        cells_by_shape: dict[tuple[str, str], list[CellAnalytics]] = {}
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
        return unconverged_reasons

    def converged(
        self,
        all_analytics: list[CellAnalytics],
        budget_remaining: int
    ) -> ConvergenceVerdict:
        """
        Check if the campaign has converged.

        Convergence criteria (ALL MUST HOLD):
        1. No below-ceiling ALU compute cells vs realistic ceilings.
        2. Every cell evaluated with >= 3 distinct configs.
        3. Every cell has >= 2 independent runs (>= 6 seeds).
        4. Stability: coefficient of variation <= 15% per cell.

        Budget exhaustion is a STOP, not convergence.
        """
        if not all_analytics:
            return ConvergenceVerdict(
                converged=False,
                reason="No analytics data available",
                below_ceiling_cells=[],
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        below_ceiling_cells = self._collect_below_ceiling(all_analytics)

        budget_verdict = self._check_budget(budget_remaining, below_ceiling_cells)
        if budget_verdict:
            return budget_verdict

        unconverged_reasons = []
        if below_ceiling_cells:
            unconverged_reasons.append(
                f"{len(below_ceiling_cells)} below-ceiling cells remain")

        unconverged_reasons.extend(self._check_cell_requirements(all_analytics))

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

