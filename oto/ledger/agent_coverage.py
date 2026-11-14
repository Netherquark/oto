#!/usr/bin/env python3
"""Coverage guidance: what the ledger says about a cell, read once.

Owns: ``_shape_sweeps`` (the deck's sweep, read once per run), ``_cell_coverage``
/ ``_cell_coverage_state`` (this cell's evidence and its state) and
``_load_coverage_cells`` (the cached ``(family, shape) -> evidence`` map the
synthesis guidance is drawn from).
Does NOT own: the state machine itself (oto.metrics.coverage) or the synthesis
that consumes the guidance (oto.tensile.synthesis).
Public API: CoverageMixin.
"""

from __future__ import annotations

from typing import Any

from oto import yaml_cached as yamlio
from oto.metrics import coverage


class CoverageMixin:
    """Coverage guidance, mixed into ConvergenceAgent."""


    def _shape_sweeps(self) -> dict[str, list[str]]:
        """Per-family shape sweeps, read once from the curated deck.

        The deck is the authority on what a *graded* config looks like, so the
        sweep is read from there rather than constructed. Cached because the deck
        does not change within a run and this sits on the per-cell path.
        """
        if self._shape_sweeps_cache is None:
            import oto.tensile.synthesis.manifest as synthesis
            path = self.base_dir / "phases.yaml"
            phases = []
            if path.exists():
                try:
                    with open(path) as f:
                        phases = yamlio.load_yaml_text(f.read()) or []
                except Exception:
                    phases = []
            self._shape_sweeps_cache = synthesis.family_shape_sweeps(phases)
        return self._shape_sweeps_cache

    def _cell_coverage(self, family: str, shape: str) -> dict[str, Any] | None:
        """This cell's coverage evidence from the ledger, or None if unknown."""
        if self._coverage_cells_cache is None:
            self._coverage_cells_cache = self._load_coverage_cells()
        return self._coverage_cells_cache.get((str(family).upper(), str(shape)))

    def _cell_coverage_state(self, family: str, shape: str) -> str | None:
        """The cell's coverage state, or None when the cell is not yet known."""
        cell = self._cell_coverage(family, shape)
        if cell is None:
            return None
        return coverage.decide_state(cell, band_pct=self.band())

    def _load_coverage_cells(self) -> dict[tuple[str, str], dict[str, Any]]:
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
