#!/usr/bin/env python3
"""The phase runner: manifest merge, policy filter, identical-fp skip bypass.

Owns: ``load_phases_manifest`` (phases.yaml + the per-run overlay + the seed
overlay), ``run_phases`` (target filtering, the ``should_run`` policy gate, the
identical-fp skip and its two bypasses, the tally and the final run status), and
``_resolve_proposal_outcome`` (writing a measured outcome back to the ledger).
Does NOT own: phase execution (benchmark.py), the reference floor (reference.py)
or the auto loop (auto.py).
Public API: PhaseMixin.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from oto.ledger.registry import fingerprint_config
from oto.metrics.policy import should_run

class PhaseMixin:
    """Deck merge + policy-filtered phase execution, mixed into TensileDriver."""

    def load_phases_manifest(self, phases_path: Optional[Path] = None,
                             include_overlay: bool = True
                             ) -> List[Dict[str, Any]]:
        """Load phases.yaml manifest plus this run's overlay.

        phases.yaml curated deck (never written). Candidates live in per-run
        overlays (phases.<run_id>.overlay.yaml), merged here after curated
        phases, tagged origin: overlay. Overlay keyed on active run; another
        run's overlay isn't applied. Explicit phases_path means caller owns
        deck outright (no merge).
        """
        if phases_path is None:
            phases_path = self.base_dir / "phases.yaml"
            explicit_deck = False
        else:
            explicit_deck = True

        phases: List[Dict[str, Any]] = []
        if phases_path.exists():
            with open(phases_path, "r") as f:
                phases = yaml.safe_load(f) or []

        if explicit_deck or not include_overlay:
            return phases

        run_id = self.run_dir.name if self.run_dir else None
        if run_id:
            overlay = self._load_run_overlay(run_id)
            if overlay:
                merged = self._merge_overlay_entries(
                    phases, overlay, origin_label="overlay", src=run_id)
                if merged:
                    print(f"[overlay] merged {merged} candidate phase(s) from "
                          f"phases.{run_id}.overlay.yaml (phases.yaml untouched)")

        # Persistent seed overlay (proposal D2, potential_configs.md §8): the
        # proven-winner rows and next-phase probes queued for every native run,
        # deliberately NOT in phases.yaml so the curated deck stays exactly as
        # shipped. Same semantics as a per-run overlay (pure measurement-first
        # candidates), except the rows come from the documented seed list instead
        # of a live arm. Like the per-run overlay it is never applied to an
        # explicit phases_path (reference-floor runs keep their own deck).
        if self.run_dir is not None:
            seed = self._load_seed_overlay()
            if seed:
                merged = self._merge_overlay_entries(
                    phases, seed, origin_label="seed_overlay", src="seed")
                if merged:
                    print(f"[overlay] merged {merged} seed phase(s) from "
                          f"phases.seed.overlay.yaml (D2 list, phases.yaml untouched)")
        return phases

    def _merge_overlay_entries(
        self,
        phases: List[Dict[str, Any]],
        entries: List[Dict[str, Any]],
        origin_label: str,
        src: str,
    ) -> int:
        """Append overlay entries to `phases`, keyed on a stable phase_id.

        A phase_id collision (in the deck, a prior overlay layer, or within the
        entries themselves) would make `phases.phase_id UNIQUE` reject the
        overlay row, so the candidate would silently never run -- collisions are
        skipped loudly instead. Every merged row is tagged with `origin` and
        `overlay_run_id` so downstream policy can treat these as measurement-first
        candidates regardless of which overlay they came from.
        """
        seen = {str(p.get("phase_id", "")) for p in phases}
        merged = 0
        for entry in entries:
            entry = dict(entry or {})
            phase_id = str(entry.get("phase_id", ""))
            if not phase_id or phase_id in seen:
                continue
            seen.add(phase_id)
            entry["origin"] = entry.get("origin") or origin_label
            entry.setdefault("overlay_run_id", src)
            phases.append(entry)
            merged += 1
        return merged

    def _load_seed_overlay(self) -> List[Dict[str, Any]]:
        """This project's persistent seed overlay, or [] when there is none.

        `gfx90c_results/overlays/phases.seed.overlay.yaml` is curated by hand /
        by the D2 tooling and applied to every native run. The per-run overlay
        path is not used because the seed is not tied to a single run_id.
        """
        path = self.base_dir / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                payload = yaml.safe_load(f) or {}
            return payload.get("phases", []) or []
        except Exception as e:
            print(f"[overlay] seed overlay unreadable, ignoring: {e}")
            return []

    def _load_run_overlay(self, run_id: str) -> List[Dict[str, Any]]:
        """This run's overlay phases, or [] when there is none.

        Read through the mutator when one exists so overlay parsing has a single
        owner; falls back to the file directly so the overlay is still honoured
        with no ledger-backed mutator.
        """
        path = (self.base_dir / "gfx90c_results" / "overlays"
                / f"phases.{run_id}.overlay.yaml")
        if not path.exists():
            return []
        if self.mutator is not None:
            try:
                return self.mutator.load_overlay(run_id) or []
            except Exception:
                pass
        try:
            with open(path) as f:
                payload = yaml.safe_load(f) or {}
            return payload.get("phases", []) or []
        except Exception as e:
            print(f"[overlay] unreadable, ignoring: {e}")
            return []

    _KEY_POLL_S = 0.2
    def _resolve_proposal_outcome(self, phase: Dict[str, Any],
                                     run_dir: Path) -> Optional[str]:
        """Write a mutated candidate's measured outcome back to the ledger.

        Called after a phase that came from the mutation overlay has actually run.
        Without this the ledger records candidates that are then never resolved:
        they stay `pending` forever, so their `n` never grows, so the cell is
        routed to `replicate` on every later pass. A mutation arm that never
        writes back an outcome is indistinguishable from one that measured
        nothing.

        Only acts when the phase's fingerprint is in the ledger, so curated and
        reference-floor phases are untouched. Returns the outcome written, or
        None when the phase was not a ledger proposal / no mutator is present.
        """
        if self.mutator is None:
            return None
        fp = phase.get("fp")
        if not fp:
            return None
        try:
            if self.registry.get_proposal(fp) is None:
                return None
        except Exception:
            return None

        phase_dir = run_dir / str(phase.get("phase_id", ""))
        try:
            outcome, detail = self.mutator.resolve_phase_dir(
                fp, phase_dir, run_id=self.run_dir.name if self.run_dir else None)
        except Exception as e:
            # A classification failure must not abort a run whose phases have
            # already executed; the candidate simply stays pending.
            print(f"[ledger] could not resolve {fp}: {e}")
            return None
        if outcome and outcome != "pending":
            print(f"[ledger] {fp} -> {outcome} "
                  f"(winner_freq={detail.get('winner_freq')})")
        return None if outcome == "pending" else outcome
    def run_phases(
        self,
        target_ids: Optional[List[str]] = None,
        opt_in_identical_skip: bool = True,
        phases_path: Optional[Path] = None
    ) -> List[Dict[str, Any]]:
        """
        Run a set of targets with policy filtering (Stage 1-4).
        target_ids matches against phase_id, label, or clean target key.
        phases_path overrides the manifest source.
        """
        phases = self.load_phases_manifest(phases_path) if phases_path else self.load_phases_manifest()

        if self.run_dir is None:
            print(f"[plan] {len(phases)} phase(s) in the manifest; no run "
                  f"directory, so this is a dry run and nothing is executed.")
            return []

        phases = self._filter_target_phases(phases, target_ids)
        self._start_live_status()

        results = []
        executed_count = 0
        skipped_count = 0
        refused_count = 0
        try:
            for phase in phases:
                if self._check_stop_requested():
                    break

                phase_id = phase.get("phase_id", "")
                fp = phase.get("fp", fingerprint_config(phase.get("config", {})))

                if not self._should_execute_phase(phase, fp, target_ids, opt_in_identical_skip):
                    skipped_count += 1
                    self._record_skip(phase_id, fp, reason="skipped_by_policy")
                    if self._handle_user_keys_during_skip() == "stop":
                        break
                    continue

                result = self.execute_phase(phase, self.run_dir)
                results.append(result)

                executed_count, refused_count = self._update_counters(
                    result, executed_count, refused_count
                )
                if result.get("status") in ("completed", "failed", "success"):
                    self._resolve_proposal_outcome(phase, self.run_dir)

                if self._finish_after_iteration:
                    print("End-after-iteration requested, halting phase execution")
                    break

            self._finalize_run_status(executed_count, skipped_count, refused_count)
            return results
        finally:
            self._stop_live_status()

    def _filter_target_phases(
        self,
        phases: List[Dict[str, Any]],
        target_ids: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """Filter phases by target_ids if provided."""
        if not target_ids:
            return phases
        keys = {str(k) for k in target_ids}
        def _match_target(p):
            tid = str(p.get("phase_id", ""))
            lbl = str(p.get("label", ""))
            clean = tid.replace("phase_", "")
            return tid in keys or lbl in keys or clean in keys
        return [p for p in phases if _match_target(p)]

    def _check_stop_requested(self) -> bool:
        """Check if stop was requested. Returns True if should break."""
        if self._stop_requested or self._finish_after_iteration:
            print("Stop requested, halting phase execution")
            return True
        return False

    def _should_execute_phase(
        self,
        phase: Dict[str, Any],
        fp: str,
        target_ids: Optional[List[str]],
        opt_in_identical_skip: bool
    ) -> bool:
        """Determine if a phase should be executed."""
        phase_id = phase.get("phase_id", "")

        from_overlay = bool(phase.get("overlay_run_id")) or \
            str(phase.get("origin") or "") in ("overlay", "seed_overlay")
        bypass_identical_skip = (
            from_overlay and self.agent is not None
            and not self.agent.skip_mutation_arm())
        if phase.get("bypass_identical_skip"):
            bypass_identical_skip = True
        if (phase.get("overlay_run_id") == "seed"
                and self.run_dir is not None
                and self.registry.has_run_benchmarked(
                    self.run_dir.name, fp)):
            bypass_identical_skip = False

        allowed, reason = should_run(
            phase_id=phase_id,
            fp=fp,
            registry=self.registry,
            phase_scope=target_ids,
            opt_in_identical_skip=opt_in_identical_skip
            and not bypass_identical_skip
        )
        if bypass_identical_skip and not allowed \
                and reason == "identical_fp_already_passed":
            allowed, reason = True, "bypassed_identical_fp_via_ledger"

        if not allowed:
            print(f"Skipping phase {phase_id} ({reason})")
            return False
        return True

    def _record_skip(self, phase_id: str, fp: str, reason: str) -> None:
        """Record a skipped phase in the registry."""
        self.registry.append_record({
            "run_id": self.run_dir.name,
            "phase_id": phase_id,
            "fp": fp,
            "timestamp": datetime.now().isoformat(),
            "status": "skipped",
            "reason": reason
        }, run_id=self.run_dir.name)

    def _handle_user_keys_during_skip(self) -> str:
        """Handle user key presses during skip. Returns 'stop' if should break."""
        key = self._read_key(block=False)
        if key == 'q':
            print("\n[USER ACTION] 'q' pressed: Quitting run while skipping phases...")
            self._stop_requested = True
            return "stop"
        elif key == 'e':
            print("\n[USER ACTION] 'e' pressed: Ending run after current phase...")
            self._finish_after_iteration = True
            return "stop"
        return "continue"

    def _update_counters(
        self,
        result: Dict[str, Any],
        executed_count: int,
        refused_count: int
    ) -> tuple[int, int]:
        """Update execution counters based on result."""
        if result.get("status") == "skipped_illegal":
            refused_count += 1
        elif result.get("status") not in ("interrupted", "skipped_by_user"):
            executed_count += 1
        return executed_count, refused_count

    def _finalize_run_status(
        self,
        executed_count: int,
        skipped_count: int,
        refused_count: int
    ) -> None:
        """Finalize run status in registry."""
        if self._stop_requested:
            final_status = "interrupted"
        elif executed_count == 0 and (skipped_count + refused_count) > 0:
            final_status = "skipped"
        else:
            final_status = "completed"
        run_meta: Dict[str, Any] = {
            "phases_executed": executed_count,
            "phases_skipped": skipped_count,
        }
        if refused_count:
            run_meta["phases_refused_illegal"] = refused_count
        if self._finish_after_iteration:
            run_meta["end_after_iteration"] = True
        self._last_run_status = final_status
        self.registry.update_run_status(self.run_dir.name, final_status, run_meta)
