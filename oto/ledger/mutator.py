#!/usr/bin/env python3
"""The ledger-backed mutation arm: sampling, emission, outcome write-back, overlay.

Owns: ``Mutator`` -- the composition root over the outcome classifier
(:class:`MutatorOutcomesMixin`), plus its own sampling, emission, outcome
write-back, negative cache and per-run overlay read/write.
Does NOT own: the convergence loop that drives it (oto.ledger.convergence_agent), the
candidate sampler that produces knobs (oto.tensile.synthesis), or the registry
it writes to (oto.ledger.registry).
Public API: Mutator, Proposal, classify_outcome (re-exported).
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from oto import yaml_cached as yamlio

# `yaml` is imported lazily, inside the functions that use it, so that
# importing this module does not pull in the parser.
from oto.device import loader as _loader
from oto.ledger.mutator_outcomes import (
    OUTCOME_FUNCTIONAL,
    OUTCOME_LEGAL_REJECTED,
    OUTCOME_LEGAL_SLOW,
    OUTCOME_NON_FUNCTIONAL,
    OUTCOME_PENDING,
    TERMINAL_OUTCOMES,
    MutatorOutcomesMixin,
    classify_outcome,
)
from oto.metrics.benchmark_analytics import AnalyticsEngine
from oto.tensile.legality import TEMPLATE_KEYS

__all__ = [
    "DEFAULT_DRAWS_PER_CELL",
    "DEFAULT_NEGATIVE_CACHE_K",
    "ORIGIN_NOVEL",
    "ORIGIN_REPLICATE",
    "OUTCOME_FUNCTIONAL",
    "OUTCOME_LEGAL_REJECTED",
    "OUTCOME_LEGAL_SLOW",
    "OUTCOME_NON_FUNCTIONAL",
    "OUTCOME_PENDING",
    "TERMINAL_OUTCOMES",
    "Mutator",
    "Proposal",
    "classify_outcome",
]

#: `legality` is the single owner of TEMPLATE_KEYS (imported above): this module
#: assembles nothing, it only strips the caller's keys from what `legality`
#: built. The import used to appear twice -- once here and once in the header --
#: and the duplicate carried a `noqa: F401` that is no longer needed, because the
#: name is genuinely used.
from oto.runners.result_paths import results_dir as _results_dir
from oto.tensile import legality

#: Candidate draws attempted per cell. The prior replaced a lattice that emitted
#: 59 mutants from one winner, ~25 of which collided on fingerprints; novelty
#: filtering makes an extra draw cost an RNG step rather than a phase, so this
#: is deliberately generous and tunable rather than tuned.
DEFAULT_DRAWS_PER_CELL = 8

#: Where a candidate came from: a novel draw or a replicate of a shipped config.
ORIGIN_NOVEL = "novel"
ORIGIN_REPLICATE = "replicate"

#: Default consecutive-failure count before a neighbourhood is down-weighted.
#: Named here (not buried in a call site) because H.3.8 makes it a parameter.
DEFAULT_NEGATIVE_CACHE_K = 3


@dataclass
class Proposal:
    """One emitted candidate, as recorded in the ledger."""

    fp: str
    family: str | None = None
    shape: str | None = None
    parent_fp: str | None = None
    origin: str = ORIGIN_NOVEL
    iteration: int | None = None
    run_id: str | None = None
    outcome: str = OUTCOME_PENDING
    build_class: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class Mutator(MutatorOutcomesMixin):
    """Ledger-backed mutator for the convergence loop.

    Emits through `registry.record_proposal`, never through
    `scheduler.append_to_phases`. The overlay is how candidates reach the
    runner without touching the curated deck (H.3.7).
    """

    def __init__(
        self,
        registry,
        base_dir: Path,
        analytics: AnalyticsEngine | None = None,
        negative_cache_k: int = DEFAULT_NEGATIVE_CACHE_K,
        slow_threshold: float | None = None,
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
        self._slow_bars: dict[tuple, dict[str, Any]] | None = None
        self._slow_bands: dict[str, Any] | None = None
        self._consecutive_failures: dict[str, int] = {}
        # Start from durable history rather than empty: an in-memory counter that
        # resets on every process start under-reports a saturated neighbourhood,
        # which is the same class of bug as a novelty ledger that has been
        # deleted (see `registry.coverage_view` on the empty-table case).
        self.rebuild_negative_cache()

    # -- sampler ------------------------------------------------------

    def sample_candidate(self,
                         family: str,
                         base_config: dict[str, Any] | None = None,
                         groups: int = 2,
                         seed: str | None = None, profile=None) -> dict[str, Any] | None:
        """Return manifest-legal candidate knobs for ``family``.

        The knob values are drawn from what Tensile actually
        ships for this family, so the reject set is never proposed rather than
        proposed and then filtered. Returns only the *knobs* -- the caller owns
        Architecture / ScheduleName / FamilyLabel through its own template.

        ``None`` means the family is not in the manifest or no draw survived the
        hard walls; the caller should skip the cell rather than fall back to the
        lattice, because a lattice draw is exactly what the prior replaces.
        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        if family not in _loader.resolve_profile(profile,).family_dtype_char:
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
                    base_config: dict[str, Any] | None = None,
                    groups: int = 2,
                    draws: int = DEFAULT_DRAWS_PER_CELL,
                    seed: str | None = None) -> list[dict[str, Any]]:
        """Draw up to ``draws`` legal candidates for one cell.

        Duplicates are *not* removed here: the caller checks each against the
        novelty ledger, which is the single owner of fingerprint de-duplication
        . Over-drawing is therefore cheap -- it costs an RNG draw, not a
        phase.
        """
        out: list[dict[str, Any]] = []
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
                     base_config: dict[str, Any] | None = None,
                     cell: dict[str, Any] | None = None,
                     groups: int = 2,
                     draws: int = DEFAULT_DRAWS_PER_CELL,
                     seed: str | None = None,
                     band_pct: float | None = None,
                     shape: str | None = None,
                     sweeps: dict[str, list[str]] | None = None,
                     ) -> dict[str, Any]:
        """Coverage-guided synthesis for one cell: draws plus a shape sweep.

        Returns the `synthesis.synthesize_cell` summary rather than a bare knob
        list, because the caller needs two things the sampler cannot decide for
        it: the cell's state (so a retired cell can be skipped) and the shape
        sweep (so the candidate is graded rather than born ungradable —
        the design's gradeability rule).

        The ≤2-knob lattice remains the deterministic fallback via
        `synthesis.synthesize_or_lattice`; `sample_cell` above is retained for
        callers that only want knobs.
        """
        import oto.tensile.synthesis.pipeline_manifest as synthesis

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
        look productive while measuring nothing.
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
                             phase_data: dict[str, Any]) -> bool:
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

    def resolve(self, fp: str, outcome: str, build_class: str | None = None) -> bool:
        """Write back a candidate's outcome, at most once.

        Also feeds the negative cache, which is the only state that changes what
        gets sampled next. A second write-back is a no-op and does not touch the
        cache, because the first verdict is the one that counts.
        """
        applied = self.registry.resolve_proposal(fp, outcome, build_class)
        if applied:
            self._note_outcome(fp, outcome)
        return applied

    def slow_bars(self) -> dict[tuple, dict[str, Any]]:
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
            from oto.metrics import cell_coverage as coverage
            resolved = coverage.reference_thresholds(self.base_dir)
            self._slow_bars = dict(resolved.get("bars") or {})
            self._slow_bands = {k: resolved.get(k) for k in
                                ("band_pct", "band_source", "reference_runs",
                                 "available")}
        except Exception:
            self._slow_bars = {}
            self._slow_bands = {"available": False}
        return self._slow_bars

    def slow_threshold_for(self, cell) -> float | None:
        """The bar for one `(dtype, shape)` cell, or None if unjudgeable."""
        if cell is None:
            return None
        bar = self.slow_bars().get((str(cell[0]).upper(), str(cell[1])))
        return float(bar["bar_gflops"]) if bar else None

    def resolve_phase_dir(
        self,
        fp: str,
        phase_dir: Path,
        build_class: str | None = None,
        run_id: str | None = None,
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

    def rebuild_negative_cache(self) -> dict[str, int]:
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
        failures: dict[str, int] = {}
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

    def write_overlay(self, candidates: Sequence[dict[str, Any]], run_id: str | None = None, profile=None) -> Path:
        """Write this run's candidates to a per-run overlay.

        `phases.yaml` is the curated deck and stays that way. An overlay is
        disposable by construction: discarding a bad batch deletes this file and
        nothing else, so no history is edited to undo a mistake.
        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        import yaml

        if run_id is None:
            run_id = self.registry.latest_run_id() or "unbound"
        target_dir = _results_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / "overlays"
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"phases.{run_id}.overlay.yaml"
        payload = {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "note": (
                "Per-run candidate overlay. Not curated. "
                "phases.yaml is authoritative for the deck; this file exists so "
                "the mutation arm can run without writing to it."
            ),
            "phases": list(candidates),
        }
        with open(path, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)
        return path

    def load_overlay(self, run_id: str, profile=None) -> list[dict[str, Any]]:
        """Read back one run's overlay, or [] if there is none.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """

        path = _results_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / "overlays" / f"phases.{run_id}.overlay.yaml"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                payload = yamlio.load_yaml_text(f.read()) or {}
        except Exception:
            return []
        return payload.get("phases", [],) or []
