#!/usr/bin/env python3
"""
agent.py — Convergence Agent (harvest → mutate → loop)

The deterministic convergence engine for oto:
- Harvest winning configs from analytics results
- Mutate candidates (≤2 knobs) for below-ceiling or non-converged cells (via scheduler)
- Check convergence: no below-ceiling cells AND per-cell stability gates
- Feed new candidates to phases.yaml manifest
"""

import yaml
from pathlib import Path
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

from scheduler import CandidateGenerator, CandidateConfig
from analytics import AnalyticsEngine, CellAnalytics
from gfx90c_common import FAMILY_DTYPE_CHAR


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
        analytics: AnalyticsEngine
    ):
        self.base_dir = Path(base_dir)
        self.scheduler = scheduler
        self.analytics = analytics
        self.iteration = 0
        self.harvested_winners: Dict[str, Dict[str, Any]] = {}

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
        all_analytics: List[CellAnalytics]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Harvest winning configs from analytics results.

        Extracts the best config per (family, shape) cell based on
        median-of-seeds performance. The family tag travels with the winner so
        downstream mutation rebuilds the correct Tensile DataType.
        """
        winners = {}
        by_cell: Dict[str, List[CellAnalytics]] = {}

        for a in all_analytics:
            fam = a.family or a.dtype.lower()
            key = f"{fam}_{a.shape}"
            if key not in by_cell:
                by_cell[key] = []
            by_cell[key].append(a)

        for key, cell_analytics in by_cell.items():
            best = max(cell_analytics, key=lambda a: a.median_gflops)
            winners[key] = {
                "family": best.family,
                "dtype": best.dtype,
                "shape": best.shape,
                "fp": best.config_fp,
                "median_gflops": best.median_gflops,
                "pct_of_ceiling": best.pct_of_ceiling,
                "is_below_ceiling": best.is_below_ceiling,
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
        fam = str(analytics.family or "").upper()
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

        Mutates candidates for below-ceiling or non-converged cells. The winner's
        family tag (not the raw DataType char) selects the Tensile DataType, so
        HH / HH_HPA / HS_HPA winners no longer silently fall back to FP32.

        Args:
            winners: Dict of harvested winners from harvest()
            mutation_budget: Maximum knobs to mutate per candidate (default 2)

        Returns:
            List of new CandidateConfig objects
        """
        new_candidates = []

        for cell_key, winner_info in winners.items():
            family = str(winner_info.get("family") or "").upper()
            data_type = FAMILY_DTYPE_CHAR.get(
                family, str(winner_info.get("dtype", "S")).upper())
            shape = winner_info["shape"]
            winner_config = winner_info.get("config", {})

            # Mutate by ≤2 knobs
            mutants = self.scheduler.mutate_winner(winner_config, mutation_budget)

            for i, mutant in enumerate(mutants):
                phase_id = f"phase_auto_{self.iteration}_{cell_key}_{i}"
                label = f"mutate_{family.lower() or cell_key}_{i}"

                template = {
                    "Architecture": "gfx90c",
                    "DataType": data_type,
                    "ProblemType": "Contraction",
                    "ScheduleName": "isa",
                }

                candidate = self.scheduler.emit_candidate(
                    phase_id=phase_id,
                    label=label,
                    dtype=data_type.lower(),
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