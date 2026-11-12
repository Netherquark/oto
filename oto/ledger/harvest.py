#!/usr/bin/env python3
"""Parent selection: which candidate a cell's next mutation starts from.

Owns: ``harvest`` (one parent per cell, by lower confidence bound rather than by
raw winner), ``_cell_samples`` (recover a cell's seeds when the CSV did not carry
them) and ``_reconstruct_config`` (rebuild the Tensile config a parent was
measured with).
Does NOT own: the convergence verdict (oto.ledger.agent), the coverage evidence
that guides synthesis (oto.ledger.agent), or the mutation itself
(oto.ledger.mutator).
Public API: HarvestMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from oto import yamlio  # noqa: E402
if TYPE_CHECKING:  # pragma: no cover - typing only
    from oto.metrics.analytics import CellAnalytics


import oto.metrics.coverage as coverage


class HarvestMixin:
    """Parent selection, mixed into ConvergenceAgent."""


    def harvest(
        self,
        all_analytics: List[CellAnalytics],
        parent_by: str = "lcb"
    ) -> Dict[str, Dict[str, Any]]:
        """Harvest one parent config per (family, shape) cell.

        Parent choice by lower confidence bound (Hplan.5); parent_by='median'
        retains old rule. Family tag travels with the winner.
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
                    phases = yamlio.load_yaml_text(f.read()) or []
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
