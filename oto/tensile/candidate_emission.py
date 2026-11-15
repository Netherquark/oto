#!/usr/bin/env python3
"""The append boundary: how a candidate becomes a launchable phase.

Owns: ``emit_candidate`` (merge template + knobs, fingerprint the result),
``append_candidates_batch`` / ``append_to_phases`` (re-validate every candidate,
resolve phase_id collisions by binding the id to the fingerprint that owns it,
dedupe, and write the deck), ``generate_family_phases`` (build one phase per
(family, pattern, shape, tile), clamping VectorWidth down until the gates accept
it) and ``generate_knob_sweep_phases`` (cross-join a family's winner tile with
the never-varied knob list).
Does NOT own: the deck it draws from (`oto.tensile.family_decks`), the gates that refuse a
candidate (`oto.tensile.gates`), or the config writer
(`oto.tensile.config_writer`).
Public API: CandidateEmitMixin, generate_knob_sweep_phases.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from oto import yaml_cached as yamlio
from oto.device import loader as _loader
from oto.tensile.candidate_config import CandidateConfig


class CandidateEmitMixin:
    """Emission and the append boundary, mixed into CandidateGenerator."""


    def generate_fingerprint(self, config: dict[str, Any]) -> str:
        """Generate canonical SHA256 fingerprint for a config."""
        canonical = json.dumps(config, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def emit_candidate(
        self,
        phase_id: str,
        label: str,
        dtype: str,
        shapes: list[str],
        template: dict[str, Any],
        knobs: dict[str, Any]
    ) -> CandidateConfig:
        """Emit a candidate configuration."""
        full_config = {**template, **knobs}
        fp = self.generate_fingerprint(full_config)

        return CandidateConfig(
            phase_id=phase_id,
            label=label,
            dtype=dtype,
            shapes=shapes,
            template=template,
            knobs=knobs,
            fingerprint=fp
        )

    def append_candidates_batch(self, candidates: list[CandidateConfig], phases_file: Path | None = None) -> int:
        """Append a list of candidates to phases.yaml in a single batch write.

        Every candidate is re-validated here, at the append boundary, not left to
        the caller. Duplicate fingerprints are skipped, and rejections are reported.
        """
        target_yaml = phases_file or (self.base_dir / "phases.yaml")
        existing_phases, existing_fps, existing_ids = self._load_existing_phases(target_yaml)
        added, renamed, rejected = self._process_candidates(
            candidates, existing_phases, existing_fps, existing_ids)

        if renamed:
            print(
                f"[gate] bound {renamed} candidate(s) to a fingerprint-suffixed "
                f"phase_id: the generated id was already owned by a different "
                f"config, which would have silently overwritten its results."
            )
        if rejected:
            print(f"[gate] refused {len(rejected)} illegal candidate(s) before append:")
            for _r in rejected:
                print(f"       - {_r}")

        with open(target_yaml, "w") as f:
            yaml.safe_dump(existing_phases, f, sort_keys=False, default_flow_style=False)
        return added

    def _load_existing_phases(self, target_yaml: Path) -> tuple:
        """Load existing phases and build fingerprint/id lookup sets."""
        existing_phases = []
        if target_yaml.exists():
            with open(target_yaml) as f:
                existing_phases = yamlio.load_yaml_text(f.read()) or []
        existing_fps = {p.get("fp") for p in existing_phases if isinstance(p, dict)}
        existing_ids = {
            p.get("phase_id"): p.get("fp") for p in existing_phases if isinstance(p, dict)
        }
        return existing_phases, existing_fps, existing_ids

    def _process_candidates(self, candidates, existing_phases, existing_fps, existing_ids):
        """Process candidates: validate, check collisions, add to phases."""
        added = 0
        renamed = 0
        rejected: list[str] = []
        for cand in candidates:
            merged = {**cand.template, **cand.knobs}
            ok, why = self.validate_config(merged)
            if not ok:
                rejected.append(f"{cand.phase_id}: {why}")
                continue
            phase_id, renamed_this = self._resolve_phase_id(
                cand, existing_ids, existing_fps)
            if phase_id is None:
                rejected.append(
                    f"{cand.phase_id}: phase_id collision could not be resolved "
                    f"(fp {cand.fingerprint[:12]})"
                )
                continue
            if self._add_phase_entry(cand, phase_id, merged, existing_phases,
                                      existing_fps, existing_ids):
                added += 1
            if renamed_this:
                renamed += 1
        return added, renamed, rejected

    def _resolve_phase_id(self, cand, existing_ids, existing_fps):
        """Resolve phase_id collision by binding to fingerprint."""
        phase_id = cand.phase_id
        renamed_this = False
        if existing_ids.get(phase_id) not in (None, cand.fingerprint):
            phase_id = f"{cand.phase_id}_h{cand.fingerprint[:8]}"
            if existing_ids.get(phase_id) not in (None, cand.fingerprint):
                return None, False
            cand.phase_id = phase_id
            cand.label = f"{cand.label}_h{cand.fingerprint[:8]}"
            renamed_this = True
        return phase_id, renamed_this

    def _add_phase_entry(self, cand, phase_id, merged, existing_phases,
                          existing_fps, existing_ids) -> bool:
        """Add phase entry to lists if fingerprint is new."""
        if cand.fingerprint in existing_fps:
            return False
        phase_entry = {
            "phase_id": phase_id,
            "label": cand.label,
            "dtype": cand.dtype,
            "shapes": cand.shapes,
            "ScheduleName": "isa",
            "NumBenchmarks": 8,
            "config": merged,
            "fp": cand.fingerprint
        }
        existing_phases.append(phase_entry)
        existing_fps.add(cand.fingerprint)
        existing_ids[phase_id] = cand.fingerprint
        if self.registry is not None:
            self.registry.append_phase(phase_id, cand.fingerprint, phase_entry)
        return True

    def append_to_phases(self, candidate: CandidateConfig, phases_file: Path | None = None) -> str:
        """
        Append a single candidate to phases.yaml manifest.
        """
        self.append_candidates_batch([candidate], phases_file)
        return candidate.phase_id
    def generate_family_phases(
        self,
        family: str,
        patterns: list[str],
        base_shapes: list[str], profile=None,
    ) -> list[CandidateConfig]:
        """Generate native family phases for a dtype/op family. ``profile`` -- optional, ambient by default."""
        candidates = []
        family_deck = self.family_decks.get(family, [],)

        for pattern in patterns:
            for tile_config in family_deck:
                tile_tag = self._build_tile_tag(tile_config)
                tile_key = (tile_config.get("MacroTile",),
                            tile_config.get("ThreadTile",),
                            tile_config.get("VectorWidth",))
                tile_uses = self._count_tile_uses(family_deck, tile_key)

                for shape in base_shapes:
                    template = self._build_family_template(family, pattern, shape, profile=profile,)
                    rel = self._validate_tile_config(template, tile_config, family)
                    if rel is None:
                        continue
                    tag = self._build_phase_tag(tile_tag, rel, tile_uses)
                    label = f"{family}_{pattern}_{shape}{tag}"
                    phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"

                    candidate = self.emit_candidate(
                        phase_id=phase_id, label=label,
                        dtype=_loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                        shapes=[shape], template=template, knobs=rel
                    )
                    candidates.append(candidate)

        if candidates:
            self.append_candidates_batch(candidates)
        return candidates

    def _build_tile_tag(self, tile_config: dict[str, Any]) -> str:
        """Build the base tile tag from MT/TT."""
        mt = tile_config.get("MacroTile", "").replace("x", "x")
        tt = tile_config.get("ThreadTile", "").replace("x", "x")
        return f"_mt{mt}_tt{tt}"

    def _count_tile_uses(self, family_deck: list[dict], tile_key: tuple) -> int:
        """Count how many times this tile key appears in the deck."""
        return sum(1 for e in family_deck if (e.get("MacroTile"),
                e.get("ThreadTile"), e.get("VectorWidth")) == tile_key)

    def _build_family_template(self, family: str, pattern: str, shape: str, profile=None) -> dict:
        """Build candidate template for family phases.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        return {
            "Architecture": _loader.resolve_profile(profile,).codename,
            "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
            "ContractionPattern": pattern,
            "ProblemType": shape,
            "ScheduleName": "isa",
            "FamilyLabel": family,
        }

    def _validate_tile_config(self, template: dict, tile_config: dict, family: str) -> dict | None:
        """Validate tile config with fallbacks (NLCA, VectorWidth)."""
        is_valid, _reason = self.validate_config({**template, **tile_config})
        rel = tile_config

        if not is_valid and tile_config.get("NLCA", 1) > 1:
            rel = {**tile_config, "NLCA": 1}
            is_valid, _reason = self.validate_config({**template, **rel})

        if not is_valid and rel.get("VectorWidth"):
            vw = int(rel["VectorWidth"])
            while vw > 1 and not is_valid:
                vw //= 2
                rel = {**rel, "VectorWidth": vw}
                is_valid, _reason = self.validate_config({**template, **rel})
            if is_valid:
                self._clamped_widths.append(
                    (family, tile_config.get("MacroTile"),
                     tile_config.get("ThreadTile"),
                     tile_config.get("VectorWidth"), vw))
        if not is_valid:
            return None
        return rel

    def _build_phase_tag(self, tile_tag: str, rel: dict, tile_uses: int) -> str:
        """Build the phase_id tag with disambiguating knobs."""
        tag = tile_tag
        if tile_uses > 1:
            if rel.get("VectorWidth"):
                tag += f"_vw{rel['VectorWidth']}"
            if rel.get("LdsPadA"):
                tag += f"_pa{rel['LdsPadA']}"
            if rel.get("LdsPadB"):
                tag += f"_pb{rel['LdsPadB']}"
            if rel.get("WorkGroupMapping"):
                tag += f"_wgm{rel['WorkGroupMapping']}"
        return tag

    @staticmethod
    def _sweep_value_tag(value: dict[str, Any]) -> str:
        """A phase_id suffix that names exactly which knob *value* ran.

        Without this, ``PrefetchGlobalRead`` 1 and 2 collapse onto the same
        ``_swPrefetchGlobalRead`` id and get separated only by the
        fingerprint-collision path, which produces ``_h<8 hex>`` ids that a
        reader cannot parse. The key names are included as well as the values,
        because a sweep row can carry two keys (``GlobalLoadVectorWidthA`` and
        ``B``, ``NonTemporalA`` and ``B``) and the knob's *label* is not the
        key that was actually set: naming the row ``NumLoadsCoalescedA`` while
        it sets ``NumLoadsCoalescedB`` would produce a phase_id that lies about
        the config it owns. Booleans render as 1/0 so the id stays path-safe.

        Sorted for determinism, so the same value always yields the same tag.
        Returns the value keys joined, so ``_swUseSgprForGRO1``,
        ``_swMaxOccupancy12`` and ``_swGlobalLoadVectorWidthA2_GlobalLoadVectorWidthB2``.
        """
        parts = []
        for key in sorted(value):
            val = value[key]
            parts.append(f"{key}{1 if val else 0}" if isinstance(val, bool)
                         else f"{key}{val}")
        return "_".join(parts)

    def generate_knob_sweep_phases(
        self,
        families: list[str] | None = None,
        patterns: list[str] | None = None,
        base_shapes: list[str] | None = None,
        include_baseline: bool = False,
        phases_file: Path | None = None
    ) -> list[CandidateConfig]:
        """Cross-join each family's winner tile with the never-varied knobs.

        Separate from generate_family_phases: iterates KNOB_SWEEP_BASES x KNOB_SWEEPS.
        width_override on a sweep row is honoured before validation.
        """
        from oto.tensile.family_decks import KNOB_SWEEP_BASES

        fams = families or list(KNOB_SWEEP_BASES)
        pats = patterns or ["Ailk_Bljk"]
        shapes = base_shapes or ["1024x1024x1024"]
        candidates: list[CandidateConfig] = []
        refused: list[str] = []

        for family in fams:
            bases = KNOB_SWEEP_BASES.get(family, [])
            for pattern in pats:
                candidates, refused = self._emit_baselines(
                    candidates, refused, family, pattern, bases, shapes,
                    include_baseline)
                candidates, refused = self._emit_sweeps(
                    candidates, refused, family, pattern, bases, shapes)

        if candidates:
            self.append_candidates_batch(candidates, phases_file)
        for _line in refused:
            print(f"[knob-sweep] refused {_line}")
        return candidates

    def _emit_baselines(self, candidates, refused, family, pattern, bases,
                         shapes, include_baseline, profile=None):
        """Emit baseline (unchanged base tile) candidates if requested.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        if not include_baseline:
            return candidates, refused
        for base in bases:
            for shape in shapes:
                template = self._build_template(family, pattern, shape, profile=profile,)
                ok, why = self.validate_config({**template, **base},)
                if not ok:
                    refused.append(f"{family}/baseline/{shape}: {why}")
                    continue
                tag = (f"_mt{base.get('MacroTile', '',)}"
                       f"_tt{base.get('ThreadTile', '',)}_base")
                label = f"{family}_{pattern}_{shape}{tag}"
                phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"
                candidates.append(self.emit_candidate(
                    phase_id=phase_id, label=label,
                    dtype=_loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                    shapes=[shape], template=template, knobs=dict(base)
                ))
        return candidates, refused

    def _emit_sweeps(self, candidates, refused, family, pattern, bases, shapes):
        """Emit sweep candidates for all KNOB_SWEEPS."""
        from oto.tensile.family_decks import KNOB_SWEEPS
        for base in bases:
            for sweep in KNOB_SWEEPS:
                if family not in sweep.get("families", []):
                    continue
                candidates, refused = self._emit_sweep_values(
                    candidates, refused, family, pattern, base, sweep, shapes)
        return candidates, refused

    def _emit_sweep_values(self, candidates, refused, family, pattern, base,
                            sweep, shapes, profile=None):
        """Emit candidates for one sweep's values.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        for value in sweep["values"]:
            knobs = dict(base)
            for over_fam, width in sweep.get("width_override", {},).items():
                if over_fam == family:
                    knobs["VectorWidth"] = width
            knobs.update(value)
            for shape in shapes:
                template = self._build_template(family, pattern, shape, profile=profile,)
                ok, why = self.validate_config({**template, **knobs},)
                if not ok:
                    refused.append(
                        f"{family}/{sweep['knob']}/{shape}: {why}")
                    continue
                tag = (f"_mt{base.get('MacroTile', '',)}"
                       f"_tt{base.get('ThreadTile', '',)}"
                       f"_sw{self._sweep_value_tag(value)}")
                label = f"{family}_{pattern}_{shape}{tag}"
                phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"
                candidates.append(self.emit_candidate(
                    phase_id=phase_id, label=label,
                    dtype=_loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                    shapes=[shape], template=template, knobs=knobs
                ))
        return candidates, refused

    def _build_template(self, family: str, pattern: str, shape: str, profile=None) -> dict[str, Any]:
        """Build candidate template.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        return {
            "Architecture": _loader.resolve_profile(profile,).codename,
            "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
            "ContractionPattern": pattern,
            "ProblemType": shape,
            "ScheduleName": "isa",
            "FamilyLabel": family,
        }

    def generate_decision_trial_phases(
        self,
        families: list[str] | None = None,
        patterns: list[str] | None = None,
        base_shapes: list[str] | None = None,
        phases_file: Path | None = None, profile=None,
    ) -> list[CandidateConfig]:
        """Emit decision-labelled trial tiles (full tiles, not knob deltas).
        Each DECISION_TRIAL_TILES entry carries its own decision label and
        optionally its own shapes. Tagged _trialD<n> to show which decision.
        ``profile`` -- optional, ambient by default.
        """
        from oto.tensile.family_decks import DECISION_TRIAL_TILES

        pats = patterns or ["Ailk_Bljk"]
        candidates: list[CandidateConfig] = []
        refused: list[str] = []

        for trial in DECISION_TRIAL_TILES:
            family = trial["family"]
            if families and family not in families:
                continue
            dec = trial["decision"]
            knobs = trial["knobs"]
            for pattern in pats:
                for shape in trial.get("shapes", base_shapes or
                                       ["1024x1024x1024"],):
                    template = {
                        "Architecture": _loader.resolve_profile(profile,).codename,
                        "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
                        "FamilyLabel": family,
                    }
                    ok, why = self.validate_config({**template, **knobs},)
                    if not ok:
                        refused.append(f"{family}/trial{dec}/{shape}: {why}")
                        continue
                    tag = (f"_mt{knobs.get('MacroTile', '',)}"
                           f"_tt{knobs.get('ThreadTile', '',)}"
                           f"_trial{dec}")
                    label = f"{family}_{pattern}_{shape}{tag}"
                    phase_id = (f"phase_{family.lower()}_{pattern}"
                                f"_{shape}{tag}")
                    candidates.append(self.emit_candidate(
                        phase_id=phase_id,
                        label=label,
                        dtype=_loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                        shapes=[shape],
                        template=template,
                        knobs=dict(knobs),
                    ))

        if candidates:
            self.append_candidates_batch(candidates, phases_file)
        for _line in refused:
            print(f"[trial] refused {_line}")
        return candidates

