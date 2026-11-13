#!/usr/bin/env python3
"""The gfx900 reference floor: build, resume, and recall.

Owns: ``run_gfx900_reference`` (emit one spoof phase per shipped kernel, apply
the audited triage, reuse by content fingerprint, run in a dedicated
``gfx900_ref_*`` run) and the five helpers that decide what the floor already
covers -- ``_latest_reference_run``, ``_reference_floor_runs``,
``_reusable_phase_keys``, ``_chain_phase_sets`` and ``_reference_remaining``.
Does NOT own: the shipped manifest itself (oto.tensile.library), the phase
runner it delegates to (phases.py), or the verdicts it is compared in
(oto.metrics.ab_audit).
Public API: ReferenceMixin.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import oto.device.peaks as _peaks
import oto.tensile.library as tlib
from oto import yamlio
from oto.runners.paths import runs_dir as _runs_dir


def _deck_content_fps(deck: list[dict[str, Any]]) -> dict[str, str]:
    """phase_key -> config fingerprint (undotted keys only)."""
    fps: dict[str, str] = {}
    for p in deck:
        clean = {k: v for k, v in p.items() if not k.startswith("_")}
        fps[tlib.phase_key(p)] = tlib.config_fingerprint(clean)
    return fps


def _rebuild_deck_for_triage(manifest: dict[str, Any],
                            deck: list[dict[str, Any]],
                            rerun_manifest: dict[str, Any]
                            ) -> list[dict[str, Any]]:
    """Rebuild the deck from the shipped manifest, scoped to the audited set.

    A triaged resume exists to re-measure phases whose CONFIG changed.
    Replaying the stored deck would re-run the pre-fix configs verbatim,
    so rebuild the deck from the shipped manifest instead and let the
    content comparison decide what still needs running.
    """
    _fresh = tlib.emit_spoof_phases(manifest)
    # Keep the rebuild inside the audited scope. emit_spoof_phases
    # spans every shipped family (2285 here) while the audited floor
    # covers 1212 of them; intersecting by phase_key refreshes the
    # configs without silently widening the floor with families that
    # were never part of it.
    # Scope comes from the triage manifest, not from the deck we
    # happened to load. The base deck is the newest chain head, which
    # after several resumes only covers the last slice of kernels;
    # the manifest is keyed by phase_key and spans every kernel seen
    # across the whole reference chain.
    _audited = set(rerun_manifest.get("tiers_by_key") or {}) | {
        tlib.phase_key(p) for p in deck}
    return [p for p in _fresh if tlib.phase_key(p) in _audited]


def _filter_resume_deck(
    deck: list[dict[str, Any]],
    rerun_manifest: dict[str, Any],
    reusable_keys: set[str],
    reusable_pids: set[str],
    release_held: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    """Apply triage-then-reuse to the deck -> (phases, n_reuse, n_held).

    A triage manifest is authoritative and outranks reuse: T1 exists
    precisely because the earlier measurement is void, so it must run
    again even though a completed record exists, and T3 must never be
    re-staged. Only T0_KEEP phases remain eligible for reuse.
    Reuse-then-triage ordering would instead drop every T1 phase that
    already has a verdict and quietly run none of them.
    T2 is HELD by default (see incomplete_work.md 4.16): pinned out of
    this run unless the caller explicitly released it.
    """
    phases: list[dict[str, Any]] = []
    n_reuse = 0
    n_held = 0
    for p in deck:
        key = tlib.phase_key(p)
        pid = str(p.get("phase_id", ""))
        if rerun_manifest:
            tier = tlib.tier_for(p, rerun_manifest)
            if tier == tlib.TIER_DROP:
                continue
            if tier == tlib.TIER_HELD and not release_held:
                n_held += 1
                continue
            if tier == tlib.TIER_FIRST or (
                    tier in (tlib.TIER_LAST, tlib.TIER_HELD)):
                phases.append(p)
                continue
        if key in reusable_keys or pid in reusable_pids:
            n_reuse += 1
            continue
        phases.append(p)
    return phases, n_reuse, n_held


class ReferenceMixin:
    """The spoof floor run chain, mixed into TensileDriver."""

    def _resume_chain_ids(self, base: str) -> list[str]:
        """Chain ids for a resume, base first."""
        chain_ids = tlib.reference_chain(self.registry, exclude=self.run_dir.name)
        chain_ids = [r for r in chain_ids
                     if (_runs_dir(self.base_dir, _peaks.CODENAME) / r).is_dir()]
        if base not in chain_ids:
            chain_ids = [base, *chain_ids]
        return chain_ids

    def _resume_deck(self, base: str, base_dir: Path,
                     release_held: bool) -> tuple[list[dict[str, Any]] | None,
                                                  dict[str, Any]]:
        """The phases a resume targets, plus its `resume_of` metadata.

        Returns `(None, {})` when there is nothing to resume, so the caller can
        answer with the `noop` result rather than re-deriving that here.

        Two orderings matter, and getting either backwards wastes an overnight:

        * **The deck is rebuilt from the shipped manifest, not replayed from the
          base run.** A triaged resume exists precisely because the configs
          changed; replaying the stored deck would re-run the pre-fix configs
          verbatim and measure nothing new.
        * **Triage outranks reuse.** T1 exists because the earlier measurement
          is void, so it must run again even though a completed record exists,
          and T3 must never be re-staged. Reuse-then-triage would drop every T1
          phase that already has a verdict and quietly run none of them.
        """
        manifest = tlib.load_shipped_manifest(self.base_dir, refresh=False)

        with open(base_dir / "phases_reference.yaml") as f:
            deck = yamlio.load_yaml_text(f.read()) or []

        # A triaged resume rebuilds the deck from the shipped manifest; the
        # content comparison then decides what still needs running.
        _rm = tlib.load_rerun_manifest(self.base_dir)
        if _rm:
            deck = _rebuild_deck_for_triage(manifest, deck, _rm)

        chain_ids = self._resume_chain_ids(base)

        # Reuse by content, not by phase_id (see _reusable_phase_keys).
        current_fps = _deck_content_fps(deck)
        reusable_keys, reusable_pids = self._reusable_phase_keys(
            chain_ids, current_fps)

        phases, n_reuse, _n_held = _filter_resume_deck(
            deck, _rm, reusable_keys, reusable_pids, release_held)
        if n_reuse:
            pass
        if _rm:
            sum(1 for p in deck
                       if tlib.tier_for(p, _rm) == tlib.TIER_DROP)
        return phases, {"gfx900_resume": True, "resume_of": base}

    def _fresh_deck(self, manifest: dict[str, Any],
                     ref_shapes: list[str] | None,
                     limit: int | None) -> list[dict[str, Any]]:
        """The non-resume floor deck: every shipped phase, filtered.

        Deck-shape filter + family-spread limit. Prefer assembly-legal phases
        so an empty smoke can never be spuriously "completed" (and recalled).
        """
        from oto.tensile.candidate import assembly_class_valid
        phases = tlib.emit_spoof_phases(manifest)

        def _legal(p: dict[str, Any]) -> bool:
            gate = {**p.get("config", {}), "DataType": p.get("dtype"),
                    "label": p.get("label", "")}
            ok, _ = assembly_class_valid(gate)
            return ok

        if ref_shapes:
            wanted = {str(int(s)) for s in ref_shapes}
            kept = []
            for p in phases:
                kept_shapes = [s for s in p.get("shapes", [])
                               if str(int(s.split("x")[0]) if "x" in s else s) in wanted]
                if kept_shapes:
                    p = dict(p)
                    p["shapes"] = kept_shapes
                    kept.append(p)
            phases = kept

        if limit:
            picked: list[dict[str, Any]] = []
            seen_fam = set()
            for p in phases:
                fam = p["label"].split("_")[1]
                if fam in seen_fam:
                    continue
                if not _legal(p):
                    continue
                picked.append(p)
                seen_fam.add(fam)
                if len(picked) >= int(limit):
                    break
            phases = picked
        return phases

    def run_gfx900_reference(self, refresh: bool = False, limit: int | None = None,
                              ref_shapes: list[str] | None = None,
                              resume: bool = False,
                              resume_base: str | None = None,
                              release_held: bool = False,
                              release_drop: bool = False) -> dict[str, Any]:
        """
        One-time benchmark of every shipped gfx900 kernel from the system dat.

        Refreshes the pinned manifest when refresh=True, emits one reference
        phase per shipped kernel, and runs them all in a dedicated
        gfx900_ref_* run (ScheduleName=vega10 -> spoof arm). Once completed,
        future A/B comparisons recall this run -- never re-run -- forever.

        resume=True targets ONLY the phases of the base run's deck that have no
        definite verdict yet. The base is the newest completed non-smoke reference
        run (or resume_base); the completed base phases are reused as-is, and a new
        gfx900_ref_*_resume run is created that records resume_of=<base>, so
        the reference_chain() fixture spans base+resume as one logical floor.
        smoke/limit/ref_shapes are ignored in resume mode.

        release_held=False keeps the audited-but-under-specified T2 kernels pinned
        out of the deck. Pass --release-under-specified to finally measure them.

        Refactor 2: a profile with no spoof_reference runs native-only.
        """
        if not getattr(self, "profile", None) or not getattr(self.profile, "spoof_reference", ""):
            return {"status": "native-only", "phases": []}
        manifest = tlib.load_shipped_manifest(
            self.base_dir, refresh=(not resume and refresh))

        if resume:
            phases, resume_meta = self._get_resume_phases(
                manifest, resume_base, release_held)
            if not phases:
                return {"status": "noop", "run_id": resume_meta.get("resume_of"),
                        "phases_targeted": 0, "phases_executed": 0, "results": 0}
        else:
            phases = self._fresh_deck(manifest, ref_shapes, limit)
            resume_meta = {}

        phases = self._apply_triage(phases, release_held, release_drop)

        if not phases:
            return {"status": "failed", "reason": "no eligible shipped phases emitted"}

        run_id = self._create_reference_run_dir(resume, resume_meta)

        phases_path = self.run_dir / "phases_reference.yaml"
        with open(phases_path, "w") as f:
            yaml.safe_dump(phases, f, default_flow_style=False)

        return self._execute_reference_phases(phases, phases_path, run_id,
                                               limit, resume, resume_meta)

    def _get_resume_phases(self, manifest, resume_base: str | None,
                           release_held: bool) -> tuple:
        """Get phases for resume mode. Returns (phases, resume_meta)."""
        chain_ids = tlib.reference_chain(self.registry, exclude=self.run_dir.name)
        base = resume_base or (chain_ids[0] if chain_ids else None)
        if not base:
            return [], {"status": "failed",
                        "reason": "resume requires an existing completed "
                                  "gfx900 reference run"}
        base_dir = _runs_dir(self.base_dir, _peaks.CODENAME) / base
        base_yaml = base_dir / "phases_reference.yaml"
        if not base_yaml.is_file():
            return [], {"status": "failed", "reason": f"base run deck missing: {base_yaml}"}
        # The deck is not read here: `is_file()` above is the existence check,
        # and `_resume_deck` re-reads it and returns the phase list. This used to
        # `yaml.safe_load` the whole reference deck and throw the result away.
        phases, resume_meta = self._resume_deck(base, base_dir, release_held)
        if not phases:
            return [], {"status": "noop", "run_id": base,
                        "phases_targeted": 0, "phases_executed": 0, "results": 0}
        return phases, {"resume_of": base, "resume_meta": resume_meta}

    def _apply_triage(self, phases, release_held: bool, release_drop: bool):
        """Apply audited re-run triage to phase list."""
        _rerun = tlib.load_rerun_manifest(self.base_dir)
        if _rerun:
            phases = tlib.apply_rerun_tiers(phases, _rerun,
                                            release_held=release_held,
                                            release_drop=release_drop)
        return phases

    def _create_reference_run_dir(self, resume: bool, resume_meta: dict) -> str:
        """Create reference run directory and sync agent."""
        run_id = f"gfx900_ref_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if resume:
            run_id = f"{run_id}_resume"
        prev_run_dir, prev_configs, prev_client = (
            self.run_dir, self.configs_dir, self.client_build_dir
        )
        self.run_dir = self.registry.create_run_dir(run_id)
        self.configs_dir = self.run_dir / "configs"
        self.configs_dir.mkdir(exist_ok=True)
        self.client_build_dir = self.run_dir / "client_build"
        self.client_build_dir.mkdir(exist_ok=True)
        self._sync_agent_run_id()
        return run_id, prev_run_dir, prev_configs, prev_client

    def _execute_reference_phases(self, phases, phases_path: Path, run_id: str,
                                   limit: int | None, resume: bool,
                                   resume_meta: dict) -> dict[str, Any]:
        """Execute reference phases and return result dict."""
        try:
            results = self.run_phases(
                [p["phase_id"] for p in phases],
                opt_in_identical_skip=False,
                phases_path=phases_path
            )
            executed = sum(1 for r in results
                           if isinstance(r, dict) and r.get("status") == "success")
            if self._stop_requested:
                status = "interrupted"
            elif limit is not None and not resume:
                status = "smoke"
            else:
                status = "completed" if executed > 0 else "failed"
            run_meta = {
                "gfx900_reference": True,
                "shipped_kernels": resume_meta.get("manifest", {}).get("total_shipped_kernels", 0),
                "phases_targeted": len(phases),
                "phases_executed": executed,
                "smoke": limit is not None and not resume,
                "source": phases_path.name,
            }
            run_meta.update(resume_meta)
            self.registry.update_run_status(run_id, status, run_meta)
            if status == "smoke":
                pass
            return {"run_id": run_id, "status": status,
                    "phases_targeted": len(phases), "phases_executed": executed,
                    "results": len(results)}
        finally:
            if self._telemetry is not None:
                self._telemetry.stop()
                self._telemetry = None
                self._telemetry_run_id = None
            if hasattr(self, '_run_dir_backup'):
                self.run_dir, self.configs_dir, self.client_build_dir = (
                    self._run_dir_backup, self._configs_dir_backup, self._client_build_dir_backup
                )
            self._sync_agent_run_id()

    def _latest_reference_run(self, exclude: str | None = None) -> str | None:
        """Most recently completed gfx900 reference run (recall floor for A/B)."""
        ref = tlib.latest_reference_run_id(self.registry)
        if ref and exclude and ref == exclude:
            return None
        return ref

    def _reference_floor_runs(self, run_id: Any) -> list[str]:
        """Full resume chain of the recalled reference floor, newest first,
        excluding the candidate run itself when it is a reference run."""
        exclude = str(run_id) if str(run_id).startswith("gfx900_ref_") else None
        chain = tlib.reference_chain(self.registry, exclude=exclude)
        return [r for r in chain
                if (_runs_dir(self.base_dir, _peaks.CODENAME) / r).is_dir()]
    def _reusable_phase_keys(self, run_ids: list[str],
                            current_fps: dict[str, str] | None = None
                            ) -> tuple[set[str], set[str]]:
        """Identities whose prior measurement may be reused.

        Returns (keys, pids):
          keys - content-addressed identities, i.e. tlib.phase_key() (a hash of
                  the shipped solution name). A record may only be reused when it
                  carries a config_fingerprint that still matches the one computed
                  from the phase as it would run now, so changing a knob
                  invalidates exactly the affected measurements instead of
                  silently reusing them.
          pids  - legacy identities, for records predating phase_key (keyed on
                  phase_id as before). Kept so a rollout never *loses* a floor.

        phase_id is deliberately not the primary key: it embeds parser-derived
        knobs, so fixing a parser renamed almost every id and one resume
        re-ran the entire floor.
        """
        current_fps = current_fps or {}
        keys: set[str] = set()
        pids: set[str] = set()
        for rid in run_ids:
            try:
                records = self.registry.read_records(run_id=rid)
            except Exception:
                continue
            for rec in records:
                if not rec.get("phase_id"):
                    continue
                if str(rec.get("status", "")).lower() not in ("completed", "success"):
                    continue
                key = rec.get("phase_key")
                if not key:
                    pids.add(str(rec["phase_id"]))
                    continue
                recorded = rec.get("config_fingerprint")
                if not recorded:
                    # Keyed but pre-dating fingerprints: the config it was measured
                    # under is unknowable, so it cannot be proven to still match.
                    # Re-measuring is the safe direction; stale reuse is not.
                    continue
                if recorded != current_fps.get(str(key)):
                    continue
                keys.add(str(key))
        return keys, pids
    def _chain_phase_sets(self, run_ids: list[str]) -> tuple[set[str], set[str]]:
        """Per-phase verdict sets across the whole reference chain.

        completed:   phases that produced a kernel (status completed/success).
        decided:     phases with any definite verdict (completed/success/failed/
                     skipped_illegal). skipped_illegal is a phase the assembly-class
                     gate refused before Tensile was ever launched: it can never
                     build, so counting it as settled is what stops the
                     completeness gate from retrying it forever.
                     The gap deck - decided = unattempted (never started);
                     the gap deck - completed = what a --resume must still try
                     (unattempted + retried-free failed + started-without-end).
        """
        completed: set[str] = set()
        decided: set[str] = set()
        for rid in run_ids:
            try:
                records = self.registry.read_records(run_id=rid)
            except Exception:
                continue
            for rec in records:
                if not rec.get("phase_id"):
                    continue
                status = str(rec.get("status", "")).lower()
                if status in ("completed", "success"):
                    completed.add(str(rec["phase_id"]))
                    decided.add(str(rec["phase_id"]))
                elif status in ("failed", "skipped_illegal"):
                    decided.add(str(rec["phase_id"]))
        return completed, decided
    def _reference_remaining(self) -> int:
        """Phases the reference floor still owes per audited triage.

        Only T1 blocks. T1 needs re-measurement; T2 held (opt-in, never
        blocks --auto); T3 unbuildable, stays failed. A T1 phase is owed
        until newest record's config_fingerprint matches current phase's.
        """
        chain = tlib.reference_chain(self.registry, exclude=self.run_dir.name)
        if not chain:
            return -1
        # Union of every deck in the chain: after several resumes the newest deck
        # covers only the last slice of kernels, but the floor spans all of them.
        universe: dict[str, dict[str, Any]] = {}
        for rid in chain:
            deck_path = (_runs_dir(self.base_dir, _peaks.CODENAME) / rid
                         / "phases_reference.yaml")
            try:
                for ph in yamlio.load_yaml(deck_path) or []:
                    universe.setdefault(tlib.phase_key(ph), ph)
            except Exception:
                continue
        if not universe:
            return -1
        manifest = tlib.load_rerun_manifest(self.base_dir)
        if not manifest:
            return len(universe) - len(self._chain_phase_sets(chain)[1])

        # Newest completed record per phase_key, with its fingerprint.
        newest: dict[str, str | None] = {}
        for rid in chain:
            try:
                records = self.registry.read_records(run_id=rid)
            except Exception:
                continue
            for rec in records:
                if not rec.get("phase_id"):
                    continue
                key = rec.get("phase_key") or rec["phase_id"]
                if str(rec.get("status", "")).lower() in ("completed", "success"):
                    newest[key] = rec.get("config_fingerprint")
                else:
                    newest.setdefault(key, None)

        remaining = 0
        for key, ph in universe.items():
            tier = tlib.tier_for(ph, manifest)
            if tier == tlib.TIER_DROP:
                continue                      # T3: left failed on purpose
            if tier in (tlib.TIER_LAST, tlib.TIER_HELD):
                continue                      # T2: held / best-effort, never blocks
            if key not in newest:
                remaining += 1                # never measured, or never finished
                continue
            current = tlib.config_fingerprint(
                {k: v for k, v in ph.items() if not k.startswith("_")})
            if newest[key] != current:
                remaining += 1                # stale measurement, pre-fix config
        return remaining
