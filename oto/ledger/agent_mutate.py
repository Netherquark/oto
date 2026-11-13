#!/usr/bin/env python3
"""The mutation arm of the convergence loop.

Owns: mutating one harvested winner, feeding the mutants to the ledger, and
recording the emission statistics -- the part of ``ConvergenceAgent`` that
turns a cell verdict into new candidate phases. Split from :mod:`oto.ledger.agent`
so the verdict/band logic and the mutation plumbing each have one home.
Public API: MutateMixin.
"""

from __future__ import annotations

import random
from typing import Any

import oto.device.peaks as _peaks
from oto.device.peaks import FAMILY_DTYPE_CHAR
from oto.ledger.mutator import Proposal
from oto.metrics import coverage
from oto.tensile.candidate import CandidateConfig


class MutateMixin:
    def _mutate_cell(
        self,
        cell_key: str,
        winner_info: dict[str, Any],
        mutation_budget: int,
        retired_cells: list[str],
        lattice_fallbacks: list[str],
    ) -> tuple[list[CandidateConfig], list[dict[str, Any]], int, list[str]]:
        """Mutate one cell's winner.

        Returns (new_candidates, replayed, rejected_count, ungraded_cells).
        """
        family = str(winner_info.get("family") or "").upper()
        data_type = FAMILY_DTYPE_CHAR.get(
            family, str(winner_info.get("dtype", "S")).upper())
        shape = winner_info["shape"]
        winner_config = winner_info.get("config", {})

        if self._cell_settled(winner_info):
            return [], [], 0, []

        mutants, sweep_shapes, cell_state = self._prepare_mutants(
            cell_key, family, shape, winner_config, mutation_budget,
            retired_cells, lattice_fallbacks
        )

        new_candidates: list[CandidateConfig] = []
        replayed: list[dict[str, Any]] = []
        rejected_non_novel = 0
        ungraded_cells: list[str] = []

        for i, mutant in enumerate(mutants):
            phase_id = f"phase_auto_{self.iteration}_{cell_key}_{i}"
            label = f"mutate_{family.lower() or cell_key}_{i}"

            result = self._process_mutant(
                phase_id, label, family, data_type, shape,
                sweep_shapes, cell_state, mutant, winner_info,
                new_candidates, replayed, ungraded_cells, cell_key
            )
            if result == "rejected_non_novel":
                rejected_non_novel += 1
            elif result == "invalid":
                continue

        return new_candidates, replayed, rejected_non_novel, ungraded_cells

    def mutate_and_feed(
        self,
        winners: dict[str, dict[str, Any]],
        mutation_budget: int = 2
    ) -> list[CandidateConfig]:
        """
        Mutate harvested configs and record them in the proposals ledger.

        Two behaviours changed under Option H Phase 1:
        * Candidates go to the ledger, not to `phases.yaml`.
        * Novelty is checked before emission against ledger/registry fingerprints.
        With no mutator configured, pre-Phase-1 append-to-phases.yaml fallback is preserved.
        """
        new_candidates: list[CandidateConfig] = []
        rejected_non_novel = 0
        replayed: list[dict[str, Any]] = []
        retired_cells: list[str] = []
        settled_cells: list[str] = []
        lattice_fallbacks: list[str] = []
        ungraded_cells: list[str] = []

        for ck, winner_info in winners.items():
            cands, repl, rejected, ungraded = self._mutate_cell(
                ck, winner_info, mutation_budget,
                retired_cells, lattice_fallbacks)
            new_candidates.extend(cands)
            replayed.extend(repl)
            rejected_non_novel += rejected
            ungraded_cells.extend(ungraded)

            if self._cell_settled(winner_info):
                settled_cells.append(ck)

        if self.mutator and replayed:
            self.mutator.write_overlay(replayed, run_id=self.run_id)

        self._record_emission_stats(
            new_candidates, rejected_non_novel, replayed,
            retired_cells, settled_cells, lattice_fallbacks, ungraded_cells
        )

        self.iteration += 1
        return new_candidates

    def _prepare_mutants(
        self,
        cell_key: str,
        family: str,
        shape: str,
        winner_config: dict[str, Any],
        mutation_budget: int,
        retired_cells: list[str],
        lattice_fallbacks: list[str],
    ) -> tuple[list[dict], list[str], str | None]:
        """Prepare mutants and sweep shapes for a cell. Returns (mutants, sweep_shapes, cell_state)."""
        sweep_shapes: list[str] = []
        cell_state = None
        if self.mutator is not None:
            cell_state = self._cell_coverage_state(family, shape)
            if cell_state == coverage.STATE_RETIRED:
                retired_cells.append(cell_key)
                return [], [], cell_state
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
        return mutants, sweep_shapes, cell_state

    def _build_template(self, family: str, data_type: str) -> dict[str, Any]:
        """Build the candidate template."""
        return {
            "Architecture": _peaks.CODENAME,
            "DataType": data_type,
            "ProblemType": "Contraction",
            "ScheduleName": "isa",
            "FamilyLabel": family,
        }

    def _validate_candidate(
        self,
        candidate: CandidateConfig,
        template: dict[str, Any],
        mutant: dict[str, Any],
        winner_info: dict[str, Any],
    ) -> str:
        """Validate candidate and record rejection if invalid. Returns 'invalid' or 'ok'."""
        is_valid, reason = self.scheduler.validate_config({**template, **mutant})
        if not is_valid and self.mutator:
            self.mutator.registry.record_proposal(
                fp=candidate.fingerprint,
                family=winner_info.get("family", ""),
                shape=winner_info.get("shape", ""),
                parent_fp=winner_info.get("fp"),
                iteration=self.iteration,
                run_id=self.run_id,
            )
            self.mutator.resolve(
                candidate.fingerprint,
                "legal_rejected",
                build_class=reason[:200],
            )
            return "invalid"
        return "ok"

    def _check_novelty(self, candidate: CandidateConfig) -> bool:
        """Check if candidate is novel. Returns True if novel, False if rejected."""
        return not (self.mutator and self.mutator.is_novel(candidate.fingerprint) is False)

    def _record_candidate_phase(
        self,
        phase_id: str,
        label: str,
        family: str,
        data_type: str,
        shape: str,
        sweep_shapes: list[str],
        cell_state: str | None,
        candidate: CandidateConfig,
        mutant: dict[str, Any],
        winner_info: dict[str, Any],
        template: dict[str, Any],
        replayed: list[dict[str, Any]],
        ungraded_cells: list[str],
        cell_key: str,
    ) -> None:
        """Record candidate phase in mutator or fallback to scheduler."""
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
            "bypass_identical_skip": True,
        }
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

    def _process_mutant(
        self,
        phase_id: str,
        label: str,
        family: str,
        data_type: str,
        shape: str,
        sweep_shapes: list[str],
        cell_state: str | None,
        mutant: dict[str, Any],
        winner_info: dict[str, Any],
        new_candidates: list[CandidateConfig],
        replayed: list[dict[str, Any]],
        ungraded_cells: list[str],
        cell_key: str,
    ) -> str:
        """Process a single mutant. Returns status: 'ok', 'rejected_non_novel', or 'invalid'."""
        template = self._build_template(family, data_type)
        shapes_for_candidate = sweep_shapes if len(sweep_shapes) >= 2 else [shape]
        candidate = self.scheduler.emit_candidate(
            phase_id=phase_id,
            label=label,
            dtype=data_type.lower(),
            shapes=list(shapes_for_candidate),
            template=template,
            knobs=mutant
        )

        if self._validate_candidate(candidate, template, mutant, winner_info) == "invalid":
            return "invalid"

        if not self._check_novelty(candidate):
            return "rejected_non_novel"

        new_candidates.append(candidate)
        if self.mutator:
            self._record_candidate_phase(
                phase_id, label, family, data_type, shape,
                sweep_shapes, cell_state, candidate, mutant, winner_info,
                template, replayed, ungraded_cells, cell_key
            )
        else:
            self.scheduler.append_to_phases(candidate)
        return "ok"

    def _record_emission_stats(
        self,
        new_candidates: list[CandidateConfig],
        rejected_non_novel: int,
        replayed: list[dict[str, Any]],
        retired_cells: list[str],
        settled_cells: list[str],
        lattice_fallbacks: list[str],
        ungraded_cells: list[str],
    ) -> None:
        """Record emission statistics for this iteration."""
        self.last_emission_stats = {
            "emitted": len(new_candidates),
            "rejected_non_novel": rejected_non_novel,
            "wrote_overlay": bool(self.mutator and replayed),
            "skip_mutation_arm": self.skip_mutation_arm(),
            "retired_cells": retired_cells,
            "settled_cells": sorted(set(settled_cells)),
            "lattice_fallback_cells": lattice_fallbacks,
            "ungraded_cells": sorted(set(ungraded_cells)),
            "graded_cells": len({r["phase_id"] for r in replayed
                                 if len(r.get("shapes") or ()) >= 2}),
            "band_pct": self.band(),
        }
