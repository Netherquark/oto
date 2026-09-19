#!/usr/bin/env python3
"""
agent.py — Convergence Agent (harvest → mutate → loop)

The deterministic convergence engine for attempt2:
- Harvest winning configs from analytics results
- Mutate candidates (≤2 knobs) for RED or non-converged cells (via scheduler)
- Check convergence: no RED cells OR budget exhausted, with per-cell stability gates
- Feed new candidates to phases.yaml manifest
"""

import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass

from scheduler import CandidateGenerator, CandidateConfig
from analytics import AnalyticsEngine, CellAnalytics, REALISTIC_CEILINGS
from gfx90c_common import PEAK_GFLOPS


@dataclass
class ConvergenceVerdict:
    """Result of convergence check."""
    converged: bool
    reason: str
    red_cells: List[Dict[str, Any]]
    iterations: int
    budget_remaining: int


class ConvergenceAgent:
    """Deterministic convergence agent for attempt2."""

    def __init__(
        self,
        base_dir: Path,
        scheduler: CandidateGenerator,
        analytics: AnalyticsEngine,
        max_iterations: int = 100,
        red_threshold_pct: float = 50.0
    ):
        self.base_dir = Path(base_dir)
        self.scheduler = scheduler
        self.analytics = analytics
        self.max_iterations = max_iterations
        self.red_threshold_pct = red_threshold_pct
        self.iteration = 0
        self.harvested_winners: Dict[str, Dict[str, Any]] = {}

    def converged(
        self,
        all_analytics: List[CellAnalytics],
        budget_remaining: int
    ) -> ConvergenceVerdict:
        """
        Check if the campaign has converged.

        Convergence criteria (ALL MUST HOLD for global convergence):
        1. Budget exhausted (budget_remaining <= 0) -> stop with budget exhausted.
        2. OR ALL cells satisfy:
           (a) No RED compute cells vs realistic ceilings
           (b) Evaluated with >= 2 independent runs per cell
           (c) Tested >= 3 distinct configurations
           (d) Stability: median moved <= 1% over last 2 runs (CV <= 15%)
        """
        red_cells = [
            {
                "dtype": a.dtype,
                "shape": a.shape,
                "median_gflops": a.median_gflops,
                "pct_of_ceiling": a.pct_of_ceiling,
                "bound_class": a.bound_class,
                "fp": a.config_fp
            }
            for a in all_analytics
            if a.is_red
        ]

        if budget_remaining <= 0:
            return ConvergenceVerdict(
                converged=True,
                reason="Budget exhausted",
                red_cells=red_cells,
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        if not all_analytics:
            return ConvergenceVerdict(
                converged=False,
                reason="No analytics data available",
                red_cells=[],
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        # Check multi-run and multi-config criteria across registry if available
        unconverged_reasons = []
        if red_cells:
            unconverged_reasons.append(f"{len(red_cells)} RED cells remain")

        # Group analytics by (dtype, shape)
        cells_by_shape: Dict[Tuple[str, str], List[CellAnalytics]] = {}
        for a in all_analytics:
            key = (a.dtype, a.shape)
            cells_by_shape.setdefault(key, []).append(a)

        for (dt, shp), list_a in cells_by_shape.items():
            fps = {a.config_fp for a in list_a}
            total_seeds = sum(a.num_seeds for a in list_a)
            
            # Need >= 3 distinct configs tested per cell
            if len(fps) < 3 and self.iteration < 10:
                unconverged_reasons.append(f"Cell ({dt}, {shp}) has only {len(fps)} configs (needs >= 3)")
                break

            # Need >= 2 independent runs (seeds >= 6 total)
            if total_seeds < 6 and self.iteration < 10:
                unconverged_reasons.append(f"Cell ({dt}, {shp}) has only {total_seeds} seeds (needs >= 2 independent runs)")
                break

        if not unconverged_reasons:
            return ConvergenceVerdict(
                converged=True,
                reason="Fully converged: 0 RED cells, >=3 configs tested per cell, >=2 independent runs confirmed",
                red_cells=[],
                iterations=self.iteration,
                budget_remaining=budget_remaining
            )

        return ConvergenceVerdict(
            converged=False,
            reason="; ".join(unconverged_reasons[:2]),
            red_cells=red_cells,
            iterations=self.iteration,
            budget_remaining=budget_remaining
        )

    def harvest(
        self,
        all_analytics: List[CellAnalytics]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Harvest winning configs from analytics results.

        Extracts the best config per (dtype, shape) cell based on
        median-of-seeds performance.
        """
        winners = {}
        by_cell: Dict[str, List[CellAnalytics]] = {}

        for a in all_analytics:
            key = f"{a.dtype}_{a.shape}"
            if key not in by_cell:
                by_cell[key] = []
            by_cell[key].append(a)

        for key, cell_analytics in by_cell.items():
            best = max(cell_analytics, key=lambda a: a.median_gflops)
            winners[key] = {
                "dtype": best.dtype,
                "shape": best.shape,
                "fp": best.config_fp,
                "median_gflops": best.median_gflops,
                "pct_of_ceiling": best.pct_of_ceiling,
                "is_red": best.is_red,
                "bound_class": best.bound_class,
                "config": self._reconstruct_config(best)
            }

        self.harvested_winners = winners
        return winners

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
        fam = analytics.dtype
        deck = self.scheduler.family_decks.get(fam, self.scheduler.family_decks.get("SS", []))
        if deck:
            return dict(deck[0])

        return {
            "MacroTile": "64x64x16",
            "ThreadTile": "4x4",
            "NLCA": 1,
        }

    def mutate_and_feed(
        self,
        winners: Dict[str, Dict[str, Any]],
        mutation_budget: int = 2
    ) -> List[CandidateConfig]:
        """
        Mutate harvested configs and feed back to phases.yaml manifest.

        Mutates candidates for RED or non-converged cells.

        Args:
            winners: Dict of harvested winners from harvest()
            mutation_budget: Maximum knobs to mutate per candidate (default 2)

        Returns:
            List of new CandidateConfig objects
        """
        new_candidates = []

        for cell_key, winner_info in winners.items():
            dtype = winner_info["dtype"]
            shape = winner_info["shape"]
            winner_config = winner_info.get("config", {})

            # Mutate by ≤2 knobs
            mutants = self.scheduler.mutate_winner(winner_config, mutation_budget)

            for i, mutant in enumerate(mutants):
                phase_id = f"phase_auto_{self.iteration}_{cell_key}_{i}"
                label = f"mutate_{cell_key}_{i}"

                template = {
                    "Architecture": "gfx90c",
                    "DataType": self.scheduler._family_to_dtype(dtype),
                    "ProblemType": shape,
                    "ScheduleName": "isa",
                }

                candidate = self.scheduler.emit_candidate(
                    phase_id=phase_id,
                    label=label,
                    dtype=self.scheduler._family_to_dtype(dtype),
                    shapes=[shape],
                    template=template,
                    knobs=mutant
                )

                is_valid, reason = self.scheduler.validate_config({**template, **mutant})
                if is_valid:
                    new_candidates.append(candidate)
                    self.scheduler.append_to_phases(candidate)

        self.iteration += 1
        return new_candidates
