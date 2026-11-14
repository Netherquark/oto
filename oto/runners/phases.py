#!/usr/bin/env python3
"""The phase runner: manifest merge, policy filter, identical-fp skip bypass.

Owns: ``load_phases_manifest`` (phases.yaml + the per-run overlay + the seed
overlay), ``run_phases`` (target filtering, the ``should_run`` policy gate, the
identical-fp skip and its two bypasses, the tally, the GPU-loss abort and the
final run status), and ``_resolve_proposal_outcome`` (writing a measured outcome
back to the ledger).
Does NOT own: phase execution (benchmark.py), the reference floor (reference.py)
or the auto loop (auto.py).
Public API: PhaseMixin.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from oto import yamlio
from oto.device import loader as _loader
from oto.ledger.registry import fingerprint_config
from oto.metrics.cell_policy import should_run
from oto.runners.paths import results_dir as _results_dir

#: Consecutive executed phases that *launched the client and measured nothing*
#: before the harness declares the GPU lost and aborts the run. The 2026-10-19
#: overnight run lost the device after its first phase and burned 9h47m emitting
#: 413 void phases whose client aborted in ``Tensile::Client::GetHardware`` with
#: ``hipErrorNoDevice`` -- a whole night of budget for nothing, which is exactly
#: what this guard exists to prevent.
ABORT_AFTER_CONSECUTIVE_EMPTY = 5

#: Tensile prints this from its driver immediately before handing a phase's
#: config to the benchmark client, so its presence means the client *ran*. A
#: phase without it died at kernel generation and carries a per-config verdict
#: ("Generating kernel source resulted in error 4"), never evidence about the
#: device: run_20261018_004835 opened with three such phases, run_20261017_092909
#: with five, and both went on to complete. Census over all 10,232 phase dirs:
#: the marker is present in every phase that produced a measurement and in none
#: of the 951 that did not -- the only client-reached-and-empty phases on record
#: are the void run's.
_CLIENT_INVOCATION_MARKERS = ("loading config file",)

#: Signatures of a client-side abort at the hardware probe (SIGABRT, exit 134)
#: rather than a per-tile refusal. Tensile prints "exited with code 134" into the
#: phase's stdout.log; the core dump carries the ``hipErrorNoDevice`` text. Not
#: reliable enough to *decide* the abort -- one of the void run's client-reached
#: phases named neither -- so it only sharpens the abort message.
_CLIENT_ABORT_MARKERS = ("exited with code 134", "hipErrorNoDevice")


class PhaseMixin:
    """Deck merge + policy-filtered phase execution, mixed into TensileDriver."""

    def load_phases_manifest(self, phases_path: Path | None = None,
                             include_overlay: bool = True
                             ) -> list[dict[str, Any]]:
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

        phases: list[dict[str, Any]] = []
        if phases_path.exists():
            with open(phases_path) as f:
                phases = yamlio.load_yaml_text(f.read()) or []

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

        # Persistent seed overlay (proposal D2, docs/potential_configs.md §8): the
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
        phases: list[dict[str, Any]],
        entries: list[dict[str, Any]],
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

    def _load_seed_overlay(self, profile=None) -> list[dict[str, Any]]:
        """This project's persistent seed overlay, or [] when there is none.

        `<codename>_results/overlays/phases.seed.overlay.yaml` is curated by hand /
        by the D2 tooling and applied to every native run. The per-run overlay
        path is not used because the seed is not tied to a single run_id.
        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        path = _results_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / "overlays" / "phases.seed.overlay.yaml"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                payload = yamlio.load_yaml_text(f.read()) or {}
            return payload.get("phases", [],) or []
        except Exception as e:
            print(f"[overlay] seed overlay unreadable, ignoring: {e}")
            return []

    def _load_run_overlay(self, run_id: str, profile=None) -> list[dict[str, Any]]:
        """This run's overlay phases, or [] when there is none.

        Read through the mutator when one exists so overlay parsing has a single
        owner; falls back to the file directly so the overlay is still honoured
        with no ledger-backed mutator.
        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        path = (_results_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / "overlays"
                / f"phases.{run_id}.overlay.yaml")
        if not path.exists():
            return []
        if self.mutator is not None:
            try:
                return self.mutator.load_overlay(run_id,) or []
            except Exception:
                pass
        try:
            with open(path) as f:
                payload = yamlio.load_yaml_text(f.read()) or {}
            return payload.get("phases", [],) or []
        except Exception as e:
            print(f"[overlay] unreadable, ignoring: {e}")
            return []

    _KEY_POLL_S = 0.2
    def _resolve_proposal_outcome(self, phase: dict[str, Any],
                                     run_dir: Path) -> str | None:
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
            outcome, _detail = self.mutator.resolve_phase_dir(
                fp, phase_dir, run_id=self.run_dir.name if self.run_dir else None)
        except Exception as e:
            # A classification failure must not abort a run whose phases have
            # already executed; the candidate simply stays pending.
            print(f"[ledger] could not resolve {fp}: {e}")
            return None
        if outcome and outcome != "pending":
            print(f"[ledger] {fp} -> {outcome} "
                  f"(winner_freq={_detail.get('winner_freq')})")
        return None if outcome == "pending" else outcome
    def run_phases(
        self,
        target_ids: list[str] | None = None,
        opt_in_identical_skip: bool = True,
        phases_path: Path | None = None
    ) -> list[dict[str, Any]]:
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
        try:
            results, tally = self._execute_phase_loop(
                phases, target_ids, opt_in_identical_skip)
            self._finalize_run_status(*tally)
            return results
        finally:
            self._stop_live_status()

    def _execute_phase_loop(
        self,
        phases: list[dict[str, Any]],
        target_ids: list[str] | None,
        opt_in_identical_skip: bool
    ) -> tuple[list[dict[str, Any]], tuple[int, int, int]]:
        """Walk the deck; return ``(results, (executed, skipped, refused))``.

        Halts early on a user stop, an end-after-iteration request, or the
        GPU-loss guard: consecutive phases that measure nothing mean the device
        is gone, and continuing would spend the budget on void phases.
        """
        results: list[dict[str, Any]] = []
        executed_count = skipped_count = refused_count = empty_streak = 0
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
            # Repaint the live panel the moment a phase lands, so the
            # "decided" count moves when the work moves rather than up to
            # an interval later. The panel is optional (no TTY, no panel),
            # and the refresh is a no-op when it is not running.
            panel = getattr(self, "_live_status", None)
            if panel is not None:
                panel.refresh()

            executed_count, refused_count = self._update_counters(
                result, executed_count, refused_count)
            if result.get("status") in ("completed", "failed", "success"):
                self._resolve_proposal_outcome(phase, self.run_dir)

            empty_streak = self._track_empty_streak(result, phase_id, empty_streak)
            if empty_streak is None:
                break

            if self._finish_after_iteration:
                print("End-after-iteration requested, halting phase execution")
                break
        return results, (executed_count, skipped_count, refused_count)

    def _track_empty_streak(
        self,
        result: dict[str, Any],
        phase_id: str,
        empty_streak: int
    ) -> int | None:
        """Advance the no-measurement streak; abort and return None when full."""
        empty_streak = (empty_streak + 1
                        if self._phase_produced_no_measurement(result, phase_id)
                        else 0)
        if empty_streak >= ABORT_AFTER_CONSECUTIVE_EMPTY:
            self._abort_run(phase_id, empty_streak)
            return None
        return empty_streak

    def _phase_produced_no_measurement(self, result: dict[str, Any],
                                       phase_id: str) -> bool:
        """True when the client ran a phase and measured nothing.

        Deliberately narrow, because the loop aborts on a streak of these: the
        only claim a phase makes about *the device* is that its client ran and
        left no benchmark CSV. A Tensile refusal (``skipped_illegal``) is a
        decided outcome, and a phase that never launched the client failed to
        build -- a per-config verdict, not a lost GPU.
        """
        if result.get("status") in ("skipped_illegal", "skipped_by_user"):
            return False
        if result.get("csv_count"):
            return False
        return self._client_reached(phase_id)

    def _abort_run(self, phase_id: str, streak: int) -> None:
        """Stop the run when consecutive client-run phases measure nothing.

        Refusing to continue is the point: without this the loop happily spends
        hours writing phases whose client never reaches the GPU. The run is
        marked *failed* (not *interrupted*), because this is a broken run, not a
        user stop.
        """
        note = (f"{streak} consecutive phases produced no measurement; the last "
                f"was {phase_id}")
        if self._client_aborted_at_probe(phase_id):
            note += (" -- the client aborted at the hardware probe "
                     "(SIGABRT / hipErrorNoDevice: the GPU is no longer visible "
                     "to HIP, e.g. a lost /dev/kfd or a driver-level reset)")
        print(f"\n[ABORT] {note}")
        print("[ABORT] halting the run instead of burning the remaining budget "
              "on void phases")
        self._abort_note = note
        self._stop_requested = True

    def _client_reached(self, phase_id: str) -> bool:
        """Whether a phase's log shows Tensile launched the benchmark client."""
        text = self._phase_stdout(phase_id)
        return any(marker in text for marker in _CLIENT_INVOCATION_MARKERS)

    def _client_aborted_at_probe(self, phase_id: str) -> bool:
        """Whether a phase's log records a client abort at the hardware probe."""
        text = self._phase_stdout(phase_id)
        return any(marker in text for marker in _CLIENT_ABORT_MARKERS)

    def _phase_stdout(self, phase_id: str) -> str:
        """A phase's Tensile stdout, or ``""`` when there is none to read."""
        if self.run_dir is None:
            return ""
        try:
            return (self.run_dir / phase_id / "stdout.log").read_text(
                errors="ignore")
        except OSError:
            return ""

    def _filter_target_phases(
        self,
        phases: list[dict[str, Any]],
        target_ids: list[str] | None
    ) -> list[dict[str, Any]]:
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
        phase: dict[str, Any],
        fp: str,
        target_ids: list[str] | None,
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
        if key == 'e':
            print("\n[USER ACTION] 'e' pressed: Ending run after current phase...")
            self._finish_after_iteration = True
            return "stop"
        return "continue"

    def _update_counters(
        self,
        result: dict[str, Any],
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
        # `_abort_note` is initialised in `_init_state`; read it via getattr so
        # drivers assembled field-by-field (tests, embedding) cannot AttributeError.
        abort_note = getattr(self, "_abort_note", None)
        if abort_note:
            final_status = "failed"
        elif self._stop_requested:
            final_status = "interrupted"
        elif executed_count == 0 and (skipped_count + refused_count) > 0:
            final_status = "skipped"
        else:
            final_status = "completed"
        run_meta: dict[str, Any] = {
            "phases_executed": executed_count,
            "phases_skipped": skipped_count,
        }
        if refused_count:
            run_meta["phases_refused_illegal"] = refused_count
        if abort_note:
            run_meta["abort_reason"] = abort_note
        if self._finish_after_iteration:
            run_meta["end_after_iteration"] = True
        self._last_run_status = final_status
        self.registry.update_run_status(self.run_dir.name, final_status, run_meta)
