#!/usr/bin/env python3
"""The append boundary: how a candidate becomes a launchable phase.

Owns: ``emit_candidate`` (merge template + knobs, fingerprint the result),
``append_candidates_batch`` / ``append_to_phases`` (re-validate every candidate,
resolve phase_id collisions by binding the id to the fingerprint that owns it,
dedupe, and write the deck), ``generate_family_phases`` (build one phase per
(family, pattern, shape, tile), clamping VectorWidth down until the gates accept
it) and ``generate_knob_sweep_phases`` (cross-join a family's winner tile with
the never-varied knob list).
Does NOT own: the deck it draws from (oto.tensile.decks), the gates that refuse a
candidate (oto.tensile.gates), or the config writer
(oto.tensile.config_writer).
Public API: CandidateEmitMixin, generate_knob_sweep_phases.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from oto.tensile.candidate_config import CandidateConfig
from oto.device.peaks import FAMILY_DTYPE_CHAR
from oto.tensile.gates.loads import cap_vector_width
from oto import yamlio  # noqa: E402
from oto.tensile.gates.occupancy import (  # noqa: E402
    occupancy_feasible, occupancy_workgroups_per_cu)


class CandidateEmitMixin:
    """Emission and the append boundary, mixed into CandidateGenerator."""


    def generate_fingerprint(self, config: Dict[str, Any]) -> str:
        """Generate canonical SHA256 fingerprint for a config."""
        canonical = json.dumps(config, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def emit_candidate(
        self,
        phase_id: str,
        label: str,
        dtype: str,
        shapes: List[str],
        template: Dict[str, Any],
        knobs: Dict[str, Any]
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

    def append_candidates_batch(self, candidates: List[CandidateConfig], phases_file: Optional[Path] = None) -> int:
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
            for r in rejected:
                print(f"       - {r}")

        with open(target_yaml, "w") as f:
            yaml.safe_dump(existing_phases, f, sort_keys=False, default_flow_style=False)
        return added

    def _load_existing_phases(self, target_yaml: Path) -> tuple:
        """Load existing phases and build fingerprint/id lookup sets."""
        existing_phases = []
        if target_yaml.exists():
            with open(target_yaml, "r") as f:
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
        rejected: List[str] = []
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

    def append_to_phases(self, candidate: CandidateConfig, phases_file: Optional[Path] = None) -> str:
        """
        Append a single candidate to phases.yaml manifest.
        """
        self.append_candidates_batch([candidate], phases_file)
        return candidate.phase_id
    def generate_family_phases(
        self,
        family: str,
        patterns: List[str],
        base_shapes: List[str]
    ) -> List[CandidateConfig]:
        """Generate native family phases for a dtype/op family."""
        candidates = []
        family_deck = self.family_decks.get(family, [])

        for pattern in patterns:
            for tile_config in family_deck:
                tile_tag = self._build_tile_tag(tile_config)
                tile_key = (tile_config.get("MacroTile"),
                            tile_config.get("ThreadTile"),
                            tile_config.get("VectorWidth"))
                tile_uses = self._count_tile_uses(family_deck, tile_key)

                for shape in base_shapes:
                    template = self._build_family_template(family, pattern, shape)
                    rel = self._validate_tile_config(template, tile_config, family)
                    if rel is None:
                        continue
                    tag = self._build_phase_tag(tile_tag, rel, tile_uses)
                    label = f"{family}_{pattern}_{shape}{tag}"
                    phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"

                    candidate = self.emit_candidate(
                        phase_id=phase_id, label=label,
                        dtype=FAMILY_DTYPE_CHAR.get(family, "S"),
                        shapes=[shape], template=template, knobs=rel
                    )
                    candidates.append(candidate)

        if candidates:
            self.append_candidates_batch(candidates)
        return candidates

    def _build_tile_tag(self, tile_config: Dict[str, Any]) -> str:
        """Build the base tile tag from MT/TT."""
        mt = tile_config.get("MacroTile", "").replace("x", "x")
        tt = tile_config.get("ThreadTile", "").replace("x", "x")
        return f"_mt{mt}_tt{tt}"

    def _count_tile_uses(self, family_deck: List[Dict], tile_key: tuple) -> int:
        """Count how many times this tile key appears in the deck."""
        return sum(1 for e in family_deck if (e.get("MacroTile"),
                e.get("ThreadTile"), e.get("VectorWidth")) == tile_key)

    def _build_family_template(self, family: str, pattern: str, shape: str) -> Dict:
        """Build candidate template for family phases."""
        return {
            "Architecture": "gfx90c",
            "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
            "ContractionPattern": pattern,
            "ProblemType": shape,
            "ScheduleName": "isa",
            "FamilyLabel": family,
        }

    def _validate_tile_config(self, template: Dict, tile_config: Dict, family: str) -> Optional[Dict]:
        """Validate tile config with fallbacks (NLCA, VectorWidth)."""
        is_valid, reason = self.validate_config({**template, **tile_config})
        rel = tile_config

        if not is_valid and tile_config.get("NLCA", 1) > 1:
            rel = {**tile_config, "NLCA": 1}
            is_valid, reason = self.validate_config({**template, **rel})

        if not is_valid and rel.get("VectorWidth"):
            vw = int(rel["VectorWidth"])
            while vw > 1 and not is_valid:
                vw //= 2
                rel = {**rel, "VectorWidth": vw}
                is_valid, reason = self.validate_config({**template, **rel})
            if is_valid:
                self._clamped_widths.append(
                    (family, tile_config.get("MacroTile"),
                     tile_config.get("ThreadTile"),
                     tile_config.get("VectorWidth"), vw))
        if not is_valid:
            return None
        return rel

    def _build_phase_tag(self, tile_tag: str, rel: Dict, tile_uses: int) -> str:
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
    def _sweep_value_tag(value: Dict[str, Any]) -> str:
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
        families: Optional[List[str]] = None,
        patterns: Optional[List[str]] = None,
        base_shapes: Optional[List[str]] = None,
        include_baseline: bool = False,
        phases_file: Optional[Path] = None
    ) -> List[CandidateConfig]:
        """Cross-join each family's winner tile with the never-varied knobs.

        Separate from generate_family_phases: iterates KNOB_SWEEP_BASES x KNOB_SWEEPS.
        width_override on a sweep row is honoured before validation.
        """
        from oto.tensile.decks import KNOB_SWEEP_BASES, KNOB_SWEEPS

        fams = families or list(KNOB_SWEEP_BASES)
        pats = patterns or ["Ailk_Bljk"]
        shapes = base_shapes or ["1024x1024x1024"]
        candidates: List[CandidateConfig] = []
        refused: List[str] = []

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
        for line in refused:
            print(f"[knob-sweep] refused {line}")
        return candidates

    def _emit_baselines(self, candidates, refused, family, pattern, bases,
                         shapes, include_baseline):
        """Emit baseline (unchanged base tile) candidates if requested."""
        if not include_baseline:
            return candidates, refused
        for base in bases:
            for shape in shapes:
                template = self._build_template(family, pattern, shape)
                ok, why = self.validate_config({**template, **base})
                if not ok:
                    refused.append(f"{family}/baseline/{shape}: {why}")
                    continue
                tag = (f"_mt{base.get('MacroTile', '')}"
                       f"_tt{base.get('ThreadTile', '')}_base")
                label = f"{family}_{pattern}_{shape}{tag}"
                phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"
                candidates.append(self.emit_candidate(
                    phase_id=phase_id, label=label,
                    dtype=FAMILY_DTYPE_CHAR.get(family, "S"),
                    shapes=[shape], template=template, knobs=dict(base)
                ))
        return candidates, refused

    def _emit_sweeps(self, candidates, refused, family, pattern, bases, shapes):
        """Emit sweep candidates for all KNOB_SWEEPS."""
        from oto.tensile.decks import KNOB_SWEEPS
        for base in bases:
            for sweep in KNOB_SWEEPS:
                if family not in sweep.get("families", []):
                    continue
                candidates, refused = self._emit_sweep_values(
                    candidates, refused, family, pattern, base, sweep, shapes)
        return candidates, refused

    def _emit_sweep_values(self, candidates, refused, family, pattern, base,
                            sweep, shapes):
        """Emit candidates for one sweep's values."""
        for value in sweep["values"]:
            knobs = dict(base)
            for over_fam, width in sweep.get("width_override", {}).items():
                if over_fam == family:
                    knobs["VectorWidth"] = width
            knobs.update(value)
            for shape in shapes:
                template = self._build_template(family, pattern, shape)
                ok, why = self.validate_config({**template, **knobs})
                if not ok:
                    refused.append(
                        f"{family}/{sweep['knob']}/{shape}: {why}")
                    continue
                tag = (f"_mt{base.get('MacroTile', '')}"
                       f"_tt{base.get('ThreadTile', '')}"
                       f"_sw{self._sweep_value_tag(value)}")
                label = f"{family}_{pattern}_{shape}{tag}"
                phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"
                candidates.append(self.emit_candidate(
                    phase_id=phase_id, label=label,
                    dtype=FAMILY_DTYPE_CHAR.get(family, "S"),
                    shapes=[shape], template=template, knobs=knobs
                ))
        return candidates, refused

    def _build_template(self, family: str, pattern: str, shape: str) -> Dict[str, Any]:
        """Build candidate template."""
        return {
            "Architecture": "gfx90c",
            "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
            "ContractionPattern": pattern,
            "ProblemType": shape,
            "ScheduleName": "isa",
            "FamilyLabel": family,
        }

    def generate_decision_trial_phases(
        self,
        families: Optional[List[str]] = None,
        patterns: Optional[List[str]] = None,
        base_shapes: Optional[List[str]] = None,
        phases_file: Optional[Path] = None
    ) -> List[CandidateConfig]:
        """Emit decision-labelled trial tiles (full tiles, not knob deltas).

        Each DECISION_TRIAL_TILES entry carries its own decision label and
        optionally its own shapes. Tagged _trialD<n> to show which decision.
        """
        from oto.tensile.decks import DECISION_TRIAL_TILES

        pats = patterns or ["Ailk_Bljk"]
        candidates: List[CandidateConfig] = []
        refused: List[str] = []

        for trial in DECISION_TRIAL_TILES:
            family = trial["family"]
            if families and family not in families:
                continue
            dec = trial["decision"]
            knobs = trial["knobs"]
            for pattern in pats:
                for shape in trial.get("shapes", base_shapes or
                                       ["1024x1024x1024"]):
                    template = {
                        "Architecture": "gfx90c",
                        "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
                        "FamilyLabel": family,
                    }
                    ok, why = self.validate_config({**template, **knobs})
                    if not ok:
                        refused.append(f"{family}/trial{dec}/{shape}: {why}")
                        continue
                    tag = (f"_mt{knobs.get('MacroTile', '')}"
                           f"_tt{knobs.get('ThreadTile', '')}"
                           f"_trial{dec}")
                    label = f"{family}_{pattern}_{shape}{tag}"
                    phase_id = (f"phase_{family.lower()}_{pattern}"
                                f"_{shape}{tag}")
                    candidates.append(self.emit_candidate(
                        phase_id=phase_id,
                        label=label,
                        dtype=FAMILY_DTYPE_CHAR.get(family, "S"),
                        shapes=[shape],
                        template=template,
                        knobs=dict(knobs),
                    ))

        if candidates:
            self.append_candidates_batch(candidates, phases_file)
        for line in refused:
            print(f"[trial] refused {line}")
        return candidates

# ------------------------------------------------- gate helpers (module level)
#
# Kept out of CandidateGenerator so a caller can ask "is this single knob
# illegal / does this tile divide" without constructing a generator.

#: Knobs this device has no hardware path for.
ILLEGAL_KNOBS = ("SIA", "Fp16AltImpl", "HasMFMA")


def parse_tensile_shape(shape_str: str) -> Dict[str, int]:
    """Parse a Tensile shape string into M, N, B, K (see config_writer).

    Re-exported here for the pre-split import surface; the shape grammar is
    owned by the config writer, which is the only place a shape string is read.
    """
    from oto.tensile.config_writer import parse_tensile_shape as _parse

    return _parse(shape_str)


def _illegal_knob(config: Dict[str, Any]) -> Optional[str]:
    """The first knob in :data:`ILLEGAL_KNOBS` set to a truthy value, if any."""
    return next((k for k in ILLEGAL_KNOBS
                 if k in config and config[k] not in (False, 0, None)), None)


def _assert_size_multiple_disabled(config: Dict[str, Any]) -> bool:
    """True when AssertSizeMultiple is exactly ``[1]``, which crashes Tensile."""
    asm = config.get("AssertSizeMultiple")
    return isinstance(asm, list) and asm == [1]


def _tile_divisibility_rejection(config: Dict[str, Any]) -> Optional[str]:
    """MacroTile/ThreadTile divisibility and workgroup thread-count legality.

    Why here and not in the loads gate: this is a *shape* property (does the
    tile divide at all), not a load-width property, and a deck entry that fails
    it is malformed rather than unsupported.
    """
    mt = config.get("MacroTile")
    tt = config.get("ThreadTile")
    if not (mt and tt):
        return None
    try:
        mt_clean = str(mt).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
        mt_parts = [int(p) for p in
                    (mt_clean.split("X") if "X" in mt_clean else mt_clean.split("x"))[:2]]
        tt_clean = str(tt).lower().replace("_", "x")
        tt_parts = [int(p) for p in tt_clean.split("x")[:2]]
        if len(mt_parts) == 2 and len(tt_parts) == 2:
            if tt_parts[0] <= 0 or tt_parts[1] <= 0:
                return f"Invalid ThreadTile dimensions: {tt}"
            if mt_parts[0] % tt_parts[0] != 0 or mt_parts[1] % tt_parts[1] != 0:
                return (f"Indivisible tile: MacroTile {mt} not divisible by "
                        f"ThreadTile {tt}")
            wg_threads = ((mt_parts[0] // tt_parts[0])
                          * (mt_parts[1] // tt_parts[1]))
            if wg_threads < 64 or wg_threads > 1024 or wg_threads % 64 != 0:
                return (f"Invalid WorkGroup thread count: {wg_threads} (must "
                        f"be multiple of 64 in [64, 1024])")
    except (ValueError, IndexError):
        pass
    return None


def estimate_lds_usage(config: Dict[str, Any]) -> float:
    """Estimate LDS usage in KB for a GEMM tile.

    Why a separate estimate from the occupancy gate's budget: this is the
    per-CU LDS ceiling (:data:`LDS_PER_CU_KB`), while the gate models the
    per-workgroup footprint against Tensile's allocator. Two different budgets,
    both enforced.

    NOTE: this dtype table disagrees with
    :data:`oto.tensile.gates.vgpr_model.BYTES_PER_ELEMENT` for the complex chars
    (C 16 there is 8). It is left byte-identical on purpose -- changing it would
    change which candidates the per-CU ceiling refuses -- and is recorded in
    incomplete_work.md as a real inconsistency to resolve.
    """
    mt = config.get("MacroTile", "64x64x16")
    dtype = config.get("DataType", "S")
    nlca = int(config.get("NLCA", 1))
    depth_u = int(config.get("DepthU", 16))

    m, n, k = 64, 64, depth_u
    clean_mt = str(mt).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
    parts = clean_mt.split("X") if "X" in clean_mt else clean_mt.split("x")
    if len(parts) >= 2:
        try:
            m = int(parts[0])
            n = int(parts[1])
            if len(parts) >= 3:
                k = int(parts[2])
        except (ValueError, IndexError):
            pass

    dtype_sizes = {
        "S": 4,    # FP32
        "D": 8,    # FP64
        "H": 2,    # FP16
        "B": 2,    # BF16
        "I8": 1,   # INT8
        "Z": 8,    # Complex FP32 (2x4)
        "C": 16,   # Complex FP64 (2x8)
    }
    elem_size = dtype_sizes.get(dtype, 4)

    # Total LDS allocation for A & B buffers with NLCA caching/double-buffering
    total_elements = (m * k + n * k) * nlca
    return (total_elements * elem_size) / 1024.0


def estimate_occupancy(config: Dict[str, Any]) -> float:
    """Modelled workgroups-per-CU from the register file (this device).

    Why it delegates: the previous version inferred threads from ThreadTile via
    a `64 // tt` heuristic, ignored MacroTile and VGPRs entirely, and therefore
    returned >= 1 for every config -- which is how all 8 ZZ phases in
    run_20260926_201835 reached the compiler and died there with
    overflowedResources==4. Delegating to the gate's model means the number
    reported here and the pass/fail decision can never disagree.
    """
    ok, _reason = occupancy_feasible(config)
    if not ok:
        return 0.0
    return float(occupancy_workgroups_per_cu(config))
