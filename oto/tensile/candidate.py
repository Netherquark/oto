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

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from oto.device.peaks import (FAMILY_DTYPE_CHAR, LDS_PER_CU_KB, NUM_CUS)
from oto.tensile.candidate_config import CandidateConfig
from oto.tensile.candidate_emission import CandidateEmitMixin
from oto.tensile.gates.assembly import assembly_class_valid
from oto.tensile.gates.loads import cap_vector_width, validate_tensile_loads
from oto.tensile.gates.occupancy import (dtype_char, ldspad_feasible,
                                         occupancy_feasible,
                                         occupancy_workgroups_per_cu,
                                         tile_dims)
from oto.tensile.gates.vgpr_model import depth_u

__all__ = [
    "CandidateConfig",
    "CandidateGenerator",
    "assembly_class_valid",
    "cap_vector_width",
    "ldspad_feasible",
    "occupancy_feasible",
    "occupancy_workgroups_per_cu",
    "validate_tensile_loads",
]

# Re-exported, not re-implemented: ``depth_u`` lives with the VGPR model, and
# ``dtype_char``/``tile_dims`` with the occupancy gate that uses them.
_ = (depth_u, dtype_char, tile_dims, FAMILY_DTYPE_CHAR, NUM_CUS)


# Knob neighbour map for single-knob mutations (corpus-wide, kept here so the
# deck and the mutation logic share one authoritative source).
KNOB_NEIGHBOURS: Dict[str, Dict[Any, List[Any]]] = {
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


def _mutants_from_budget(
    winner_config: Dict[str, Any],
    mutation_budget: int,
) -> List[Dict[str, Any]]:
    """Generate all 1-knob and (if budget >= 2) 2-knob mutants from the map."""
    current_knobs = {k: v for k, v in winner_config.items() if k in KNOB_NEIGHBOURS}
    mutants = []
    # Single-knob mutations
    for knob, value in current_knobs.items():
        if knob in KNOB_NEIGHBOURS and value in KNOB_NEIGHBOURS[knob]:
            for neighbour in KNOB_NEIGHBOURS[knob][value]:
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
                if (knob1 in KNOB_NEIGHBOURS and val1 in KNOB_NEIGHBOURS[knob1] and
                    knob2 in KNOB_NEIGHBOURS and val2 in KNOB_NEIGHBOURS[knob2]):
                    for n1 in KNOB_NEIGHBOURS[knob1][val1]:
                        for n2 in KNOB_NEIGHBOURS[knob2][val2]:
                            mutant = winner_config.copy()
                            mutant[knob1] = n1
                            mutant[knob2] = n2
                            mutants.append(mutant)
    return mutants


class CandidateGenerator(CandidateEmitMixin):
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
        """Mutate winner config by ≤2 knobs (neighbour search). Returns list of mutated configs."""
        return _mutants_from_budget(winner_config, mutation_budget)

    # ------------------------------------------------------------------ gates

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Is this candidate legal to launch on gfx90c?

        Why an orchestrator and not a gate: the three gate families each answer
        one question (is the class legal, does the classic load path divide, is
        the register file big enough), and a candidate must satisfy all of them.
        Holding them as one method here means the launch boundary and the append
        boundary ask the same question in the same words -- which is what stopped
        a candidate from being accepted by one seam and refused by the other.

        Note that ``ldspad_feasible`` is deliberately NOT part of this
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
        crash = _non_generative_knob_rejection(config)
        if crash is not None:
            return False, crash
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


def parse_tensile_shape(shape_str: str) -> Dict[str, int]:
    """Parse a Tensile shape string into M, N, B, K (see config_writer).

    Re-exported here for the pre-split import surface; the shape grammar is
    owned by the config writer, which is the only place a shape string is read.

    This used to be a third, hand-rolled copy of the parser, and it was wrong in
    two ways the authoritative one is not: it dropped the ``_B16`` / ``B16_``
    batch suffix, and it replaced the original's regex digit-extraction with
    ``str.split("x")`` -- which raises ``ValueError`` on anything that is not a
    bare shape string, where the original returned the default 1024 cube. It
    read plausibly and was called by no production module, but
    ``verify_config_writer`` and ``verify_gate_differential`` both import it, so
    it quietly became the thing those checks compared the original against, and
    both checks failed for that reason rather than for any real divergence.
    Delegate instead.
    """
    from oto.tensile.config_writer import parse_tensile_shape as _parse

    return _parse(shape_str)


#: Knobs gfx90c has no hardware path for; a candidate carrying any of
#: them is refused before the deck is written.
ILLEGAL_KNOBS = ("SIA", "Fp16AltImpl", "HasMFMA")


def _illegal_knob(config: Dict[str, Any]) -> Optional[str]:
    """The first knob in :data:`ILLEGAL_KNOBS` set to a truthy value, if any."""
    return next((k for k in ILLEGAL_KNOBS
                 if k in config and config[k] not in (False, 0, None)), None)


def _assert_size_multiple_disabled(config: Dict[str, Any]) -> bool:
    """True when AssertSizeMultiple is exactly ``[1]``, which crashes Tensile."""
    asm = config.get("AssertSizeMultiple")
    return isinstance(asm, list) and asm == [1]


def _non_generative_knob_rejection(config: Dict[str, Any]) -> Optional[str]:
    """A knob value Tensile declares legal but its assembly path cannot emit.

    Only ``AggressivePerfMode`` qualifies today. Tensile declares the domain
    [0,1,2] (Common.py:1446) but the priority component is dispatched by exact
    match on the boolean kernel fingerprints
    (Components/Priority.py: ``ConstantPriority.kernel = {"AggressivePerfMode":
    False}``, ``AggressivePriority.kernel = {"AggressivePerfMode": True}``), so 2
    matches neither, ``Priority.find`` returns None and ``MAC_F32C.__call__``
    raises ``TypeError: 'NoneType' object is not callable`` before a kernel
    exists. Measured, not guessed: 0 of 28 APM=2 phases built across all seven
    families (run_20261015_041159, run_20261017_092909), and every one burned a
    GPU slot. The sweep row was withdrawn on 2026-10-15; this rule is what stops
    a hand-written candidate or a mutator from re-drawing it.

    Why the generator seam and not the launch boundary: ``config_writer``
    deliberately forwards any knob value verbatim (its contract test probes
    APM=2 to prove the forwarding, ``test_writer_forwards_sweep_knobs``), so the
    refusal belongs where candidates are drawn, beside
    :func:`_assert_size_multiple_disabled`.
    """
    apm = config.get("AggressivePerfMode")
    if apm is None:
        return None
    try:
        value = int(apm)
    except (TypeError, ValueError):
        return None
    if value in (0, 1):
        return None
    return (f"AggressivePerfMode={value} is non-generative on the assembly path "
            "(Components/Priority.py dispatches only 0/1, so MAC_F32C raises "
            "TypeError); Tensile declares [0,1,2] at Common.py:1446")


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
