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

    Handles formats:
    - 1024x1024x1024 (M x N x K)
    - 64x4096x1_K4096 or 64x4096x1 (M x N x B with K)
    - 4x2048x64 (M x N x K or M x N x B)
    """
    result = {"M": 1024, "N": 1024, "B": 1, "K": 1024}
    clean = str(shape_str).strip()
    if not clean:
        return result
    if "_K" in clean:
        shape_part, k_part = clean.split("_K", 1)
        result["K"] = int(k_part)
    else:
        shape_part = clean
    parts = shape_part.split("x")
    if len(parts) == 3:
        result["M"] = int(parts[0])
        result["N"] = int(parts[1])
        result["B"] = int(parts[2])
    elif len(parts) == 4:
        result["M"] = int(parts[0])
        result["N"] = int(parts[1])
        result["B"] = int(parts[2])
        result["K"] = int(parts[3])
    return result


def _illegal_knob(config: Dict[str, Any]) -> Optional[str]:
    """First knob in config that is not in the gfx90c whitelist.

    Whitelist is the union of TENSILE_VALID_PARAMS and the forwarded knobs
    that the generator is allowed to set. Any other knob was either added by
    a buggy producer or leaked from a legacy phase.yaml; reject early with a
    clear message.
    """
    from oto.runners.driver import NOT_A_TENSILE_PARAM, _TENSILE_VALID_PARAMS
    whitelist = set(_TENSILE_VALID_PARAMS)
    whitelist.update({"ContractionPattern", "ScheduleName", "NumBenchmarks",
                      "Exact", "MacroTile", "ThreadTile", "VectorWidth",
                      "DepthU", "GlobalSplitU", "WorkGroupMapping",
                      "WorkGroup", "LocalSplitU", "PrefetchGlobalRead",
                      "PrefetchLocalRead", "NLCA", "NumLoadsCoalescedA",
                      "NumLoadsCoalescedB", "UseSgprForGRO", "InnerUnroll",
                      "MaxOccupancy", "AggressivePerfMode", "FractionalLoad",
                      "NonTemporalA", "NonTemporalB", "AssertFree1ElementMultiple",
                      "AssertFree0ElementMultiple", "LdsPadA", "LdsPadB",
                      "StaggerU", "StaggerUStride"})
    for key in config:
        if key not in whitelist and key not in NOT_A_TENSILE_PARAM:
            return key
    return None


def _assert_size_multiple_disabled(config: Dict[str, Any]) -> bool:
    """Reject AssertSizeMultiple=[1]; Tensile crashes with it."""
    return config.get("AssertSizeMultiple") == [1]


def _tile_divisibility_rejection(config: Dict[str, Any]) -> Optional[str]:
    """Check MacroTile % ThreadTile == 0 for both dimensions."""
    mt = config.get("MacroTile")
    tt = config.get("ThreadTile")
    if not (mt and tt and isinstance(mt, list) and isinstance(tt, list)):
        return None
    if not (len(mt) >= 2 and len(tt) >= 2):
        return None
    try:
        if mt[0] % tt[0] != 0 or mt[1] % tt[1] != 0:
            return f"MacroTile {mt} not divisible by ThreadTile {tt}"
    except (TypeError, ZeroDivisionError):
        return f"MacroTile {mt} / ThreadTile {tt} not integral"
    return None


def estimate_lds_usage(config: Dict[str, Any]) -> float:
    """Estimate LDS per CU in KB for a candidate config."""
    dtype = config.get("DataType", "f32")
    dt_bytes = 2 if dtype in ("f16", "bf16", "h") else (4 if dtype in ("f32", "s", "c") else 8)
    mt = config.get("MacroTile", [64, 64])
    tt = config.get("ThreadTile", [8, 8])
    depth_u = config.get("DepthU", 16)
    vw = config.get("VectorWidth", 1)
    return (mt[0] * mt[1] * depth_u * vw * dt_bytes) / 1024.0


def estimate_occupancy(config: Dict[str, Any]) -> float:
    """Estimate occupancy (waves/CU) for a candidate config."""
    lds_kb = estimate_lds_usage(config)
    vgpr = config.get("VGPRsPerThread", 256)
    sgpr = config.get("SGPRsPerThread", 32)
    wg = config.get("WorkGroup", [64, 4, 1])
    return min(
        LDS_PER_CU_KB * 1024 / (lds_kb * 1024) if lds_kb > 0 else 40,
        256 / (vgpr * wg[0] * wg[1]) if vgpr > 0 else 40,
        65536 / (sgpr * wg[0] * wg[1]) if sgpr > 0 else 40,
    )