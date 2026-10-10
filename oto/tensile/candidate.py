#!/usr/bin/env python3
"""Candidate generation: the family deck, the sampler, and the append boundary.

Owns: ``CandidateGenerator`` -- the curated family tile decks, the neighbour
search over a harvested winner, the fingerprint identity, the append boundary
that refuses an illegal candidate before it becomes a launchable phase, and
``validate_config``, the single orchestrator over the three gate families.
Does NOT own: the gates themselves (oto.tensile.gates), the launch-boundary
config writer (oto.tensile.config_writer), or the run loop (oto.runners).
Public API: CandidateConfig, CandidateGenerator, cap_vector_width,
validate_tensile_loads. The three gates are re-exported here so the historical
flat import surface (``from oto.tensile.candidate import occupancy_feasible``)
keeps working; oto.tensile.gates is their only home.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from oto.device.peaks import (FAMILY_DTYPE_CHAR, LDS_PER_CU_KB, NUM_CUS)
from oto.tensile.gates.assembly import assembly_class_valid
from oto.tensile.gates.loads import cap_vector_width, validate_tensile_loads
from oto.tensile.gates.occupancy import (dtype_char, ldspad_defasible,
                                         occupancy_feasible,
                                         occupancy_workgroups_per_cu,
                                         tile_dims)
from oto.tensile.gates.vgpr_model import depth_u

__all__ = [
    "CandidateConfig",
    "CandidateGenerator",
    "assembly_class_valid",
    "cap_vector_width",
    "ldspad_defasible",
    "occupancy_feasible",
    "occupancy_workgroups_per_cu",
    "validate_tensile_loads",
]

# Re-exported, not re-implemented: ``depth_u`` lives with the VGPR model, and
# ``dtype_char``/``tile_dims`` with the occupancy gate that uses them.
_ = (depth_u, dtype_char, tile_dims, FAMILY_DTYPE_CHAR, NUM_CUS)


@dataclass
class CandidateConfig:
    """Candidate configuration for benchmarking."""

    phase_id: str
    label: str
    dtype: str
    shapes: List[str]
    template: Dict[str, Any]
    knobs: Dict[str, Any]
    fingerprint: str


class CandidateGenerator:
    """Stage 2 candidate generation engine."""

    def __init__(self, base_dir: Path, registry=None):
        """Set up the generator.

        Args:
            base_dir: Project base directory (phases.yaml lives here).
            registry: Optional ledger. A caller that only wants the curated
                deck (dry runs, checks) must not be forced to open the DB.
        """
        self.base_dir = Path(base_dir)
        self.registry = registry
        self.family_decks = self._load_family_decks()
        #: (family, MacroTile, ThreadTile, requested_vw, emitted_vw) for every
        #: phase whose VectorWidth the generator had to clamp down to pass
        #: validate_config. Populated by generate_family_phases; reported so a
        #: deck entry that is silently narrower than intended is visible rather
        #: than inferred from a missing phase.
        self._clamped_widths: List[Tuple[str, Any, Any, Any, int]] = []

    def _load_family_decks(self) -> Dict[str, List[Dict[str, Any]]]:
        """The curated family deck for this device.

        The data lives in oto.tensile.decks so the generator and the deck can
        be read separately: the deck is a table of measured/quant/ladder
        candidates, and the generator is the code that clamps and emits them.
        Every entry is annotated in that module with which kind it is.
        """
        from oto.tensile.decks import FAMILY_DECKS

        return FAMILY_DECKS

    def mutate_winner(
        self,
        winner_config: Dict[str, Any],
        mutation_budget: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Mutate a winner config by ≤2 knobs (neighbour search).

        Args:
            winner_config: Current winner configuration
            mutation_budget: Maximum number of knobs to mutate (default 2)

        Returns:
            List of mutated configurations
        """
        knob_neighbours = {
            "MacroTile": {
                "96x96x16": ["128x128x16", "64x64x16"],
                "128x128x16": ["96x96x16", "64x64x16"],
                "64x64x16": ["96x96x16", "128x128x16", "32x32x16"],
                "32x32x16": ["64x64x16"],
            },
            "ThreadTile": {
                "6x6": ["8x8", "4x4"],
                "8x8": ["6x6", "4x4"],
                "4x4": ["6x6", "8x8", "2x2"],
                "2x2": ["4x4"],
            },
            "NLCA": {
                3: [1, 2],
                1: [2, 3],
                2: [1, 3],
            },
            "VectorWidth": {
                2: [1, 4],
                1: [2],
                4: [2],
            },
            "WorkGroupMapping": {
                4: [8, 1],
                8: [4, 1],
                1: [4, 8],
            },
            "GlobalSplitU": {
                1: [2, 4],
                2: [1, 4],
                4: [1, 2],
            },
        }

        mutants = []
        current_knobs = {k: v for k, v in winner_config.items() if k in knob_neighbours}

        # Single-knob mutations
        for knob, value in current_knobs.items():
            if knob in knob_neighbours and value in knob_neighbours[knob]:
                for neighbour in knob_neighbours[knob][value]:
                    mutant = winner_config.copy()
                    mutant[knob] = neighbour
                    mutants.append(mutant)

        # Two-knob mutations (if budget allows)
        if mutation_budget >= 2:
            knob_list = list(current_knobs.items())
            for i in range(len(knob_list)):
                for j in range(i + 1, len(knob_list)):
                    knob1, val1 = knob_list[i]
                    knob2, val2 = knob_list[j]

                    if (knob1 in knob_neighbours and val1 in knob_neighbours[knob1] and
                        knob2 in knob_neighbours and val2 in knob_neighbours[knob2]):

                        for n1 in knob_neighbours[knob1][val1]:
                            for n2 in knob_neighbours[knob2][val2]:
                                mutant = winner_config.copy()
                                mutant[knob1] = n1
                                mutant[knob2] = n2
                                mutants.append(mutant)

        return mutants
    # ------------------------------------------------------------------ gates

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Is this candidate legal to launch on gfx90c?

        Why an orchestrator and not a gate: the three gate families each answer
        one question (is the class legal, does the classic load path divide, is
        the register file big enough), and a candidate must satisfy all of them.
        Holding them as one method here means the launch boundary and the append
        boundary ask the same question in the same words -- which is what stopped
        a candidate from being accepted by one seam and refused by the other.

        Note that ``ldspad_defasible`` is deliberately NOT part of this
        orchestrator: it guards the *forwarded* knobs at the launch boundary and
        is called there, because a candidate drawn from the ledger may carry a
        pad the generator has no opinion about. Adding it here would refuse
        candidates the append boundary used to accept.

        Args:
            config: A merged template+knobs Tensile solution dict.

        Returns:
            ``(True, "Valid")`` or ``(False, reason)``.
        """
        knob = _illegal_knob(config)
        if knob is not None:
            return False, f"Illegal knob {knob} for gfx90c"
        if _assert_size_multiple_disabled(config):
            return False, "AssertSizeMultiple: [1] causes crashes"
        reason = _tile_divisibility_rejection(config)
        if reason:
            return False, reason

        # Assembly class, then classic-path load divisibility, then the two
        # resource models. The order is the historical one and matters only for
        # which reason a multi-failure config reports; keep it stable so an
        # operator's grep keeps matching.
        ok, why = assembly_class_valid(config)
        if not ok:
            return False, f"Assembly class: {why}"

        ok, why = validate_tensile_loads(config)
        if not ok:
            return False, f"Tensile load divisibility: {why}"

        lds_kb_est = estimate_lds_usage(config)
        if lds_kb_est > LDS_PER_CU_KB:
            return False, f"LDS overflow: {lds_kb_est:.1f}KB > {LDS_PER_CU_KB}KB"

        # Register-file / occupancy feasibility. This is the gate that catches
        # Tensile's overflowedResources==4 ("Occupancy limit"), which the
        # previous _estimate_occupancy could never fire. See occupancy_feasible.
        ok, why = occupancy_feasible(config)
        if not ok:
            return False, f"Occupancy limit: {why}"

        return True, "Valid"

    # ------------------------------------------------------------ identity

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
        """
        Append a list of candidates to phases.yaml in a single batch write.

        Every candidate is re-validated here, at the append boundary, not left to
        the caller. This is the last point before a config becomes a launchable
        phase, and it used to trust its input: a caller that skipped validation
        could inject a config that dies mid-run as Tensile "error 4"
        (overflowedResources=4, Occupancy limit) — the exact failure that killed
        all 8 native ZZ phases. Validation is CPU-only, so refusing here costs
        nothing and never touches the GPU. Duplicate fingerprints are still
        skipped, and rejections are counted and reported.
        """
        target_yaml = phases_file or (self.base_dir / "phases.yaml")
        existing_phases = []
        if target_yaml.exists():
            with open(target_yaml, "r") as f:
                existing_phases = yaml.safe_load(f) or []

        existing_fps = {p.get("fp") for p in existing_phases if isinstance(p, dict)}
        existing_ids = {
            p.get("phase_id"): p.get("fp") for p in existing_phases if isinstance(p, dict)
        }
        added = 0
        renamed = 0
        rejected: List[str] = []
        for cand in candidates:
            merged = {**cand.template, **cand.knobs}
            ok, why = self.validate_config(merged)
            if not ok:
                rejected.append(f"{cand.phase_id}: {why}")
                continue
            # A phase_id already bound to a DIFFERENT fingerprint means two configs
            # would share one output directory, and the second would silently
            # overwrite the first's results. phase_id is built from MT/TT (plus, on
            # a repeated tile, the width/pad/mapping tags), which cannot capture
            # every knob -- a deck entry that leaves VectorWidth unset and a sibling
            # that sets it to 2 both land on `..._mt32x32x16_tt2x2` with different
            # configs. Rather than drop a legal candidate or silently corrupt the
            # corpus, bind the id to the fingerprint that owns it.
            phase_id = cand.phase_id
            renamed_this = False
            if existing_ids.get(phase_id) not in (None, cand.fingerprint):
                phase_id = f"{cand.phase_id}_h{cand.fingerprint[:8]}"
                if existing_ids.get(phase_id) not in (None, cand.fingerprint):
                    rejected.append(
                        f"{cand.phase_id}: phase_id collision could not be resolved "
                        f"(fp {cand.fingerprint[:12]})"
                    )
                    continue
                cand.phase_id = phase_id
                cand.label = f"{cand.label}_h{cand.fingerprint[:8]}"
                renamed_this = True
            if cand.fingerprint not in existing_fps:
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
                added += 1
                if renamed_this:
                    renamed += 1

                if self.registry is not None:
                    self.registry.append_phase(phase_id, cand.fingerprint, phase_entry)

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
                # Include the tile variant in the identity so distinct tiles in a
                # family deck never share a phase_id (shared ids previously caused
                # silent overwrite of configs/output dirs).
                mt = tile_config.get("MacroTile", "").replace("x", "x")
                tt = tile_config.get("ThreadTile", "").replace("x", "x")
                tile_tag = f"_mt{mt}_tt{tt}"
                # ...and when a family deck repeats the same MT/TT (optionally at
                # different widths) it must also carry the knobs that actually
                # differ, otherwise two configs land on one phase_id and one
                # silently overwrites the other's output directory. MT/TT alone is
                # not unique: 64x64x8/4x4 appears both plain and with LdsPadA=2, and
                # 64x64x16/4x4 appears at both VW2 and VW4. Only disambiguated when
                # the tile actually repeats, so every unique-tile entry keeps its
                # historical phase_id and its already-benchmarked run dir.
                tile_key = (
                    tile_config.get("MacroTile"),
                    tile_config.get("ThreadTile"),
                    tile_config.get("VectorWidth"),
                )
                tile_uses = sum(
                    1 for e in family_deck
                    if (
                        e.get("MacroTile"),
                        e.get("ThreadTile"),
                        e.get("VectorWidth"),
                    ) == tile_key
                )
                for shape in base_shapes:
                    template = {
                        "Architecture": "gfx90c",
                        "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
                        # FamilyLabel is the workload-cell identity the driver
                        # stamps each record with (cell_key = FAMILY:SIDE). A
                        # generated phase without it gets cell_key None, is
                        # recorded with no cell stamp, and analytics cannot group
                        # it into any acceptance cell -- the run burns its full
                        # duration and the report shows no new coverage. It also
                        # has to be the real family name, not the dtype: H
                        # covers both HH and HH_HPA, so DataType cannot
                        # disambiguate the HPA variants.
                        "FamilyLabel": family,
                    }

                    is_valid, reason = self.validate_config({**template, **tile_config})
                    rel = tile_config
                    if not is_valid and tile_config.get("NLCA", 1) > 1:
                        # NLCA as configured is not Tensile-valid for this pattern
                        # (e.g. NLCA=3 on a TLU side whose coalesced vector count is
                        # not a multiple of 3, or where NLCA exceeds NumLoads).
                        # Fall back to NLCA=1 (Tensile auto search) so the generated
                        # phase is always runnable.
                        rel = {**tile_config, "NLCA": 1}
                        is_valid, reason = self.validate_config({**template, **rel})
                    if not is_valid and rel.get("VectorWidth"):
                        # Width rejected for this tile. Do not drop the phase: step
                        # the width down to the widest value the gate actually
                        # accepts and emit that. The gate is the only legality
                        # oracle (see cap_vector_width), and the usual causes are
                        # structural rather than fatal -- a TLU contraction side
                        # forces the post-reduction GLVW, so the `GLVW == VW or 1`
                        # guard caps HH_HPA 128x64x8/8x4 at VW2 even though the
                        # divisibility bound allows 4. Emitting the clamped width
                        # keeps the tile in the search instead of silently losing
                        # it, which is how a whole family of candidates went
                        # missing from the deck before.
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
                        continue

                    # Build the id from the knobs that were actually EMITTED, not
                    # from the deck request, so a clamped width is named for what
                    # will actually run. Only disambiguated when the tile repeats,
                    # which preserves historical ids for unique tiles.
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
                    label = f"{family}_{pattern}_{shape}{tag}"
                    phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tag}"

                    candidate = self.emit_candidate(
                        phase_id=phase_id,
                        label=label,
                        dtype=FAMILY_DTYPE_CHAR.get(family, "S"),
                        shapes=[shape],
                        template=template,
                        knobs=rel
                    )
                    candidates.append(candidate)

        if candidates:
            self.append_candidates_batch(candidates)

        return candidates

# ------------------------------------------------- gate helpers (module level)
#
# Kept out of CandidateGenerator so a caller can ask "is this single knob
# illegal / does this tile divide" without constructing a generator.

#: Knobs gfx90c has no hardware path for.
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
    """Modelled workgroups-per-CU from the register file (gfx90c).

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
