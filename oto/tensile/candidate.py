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
    "parse_tensile_shape",
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
        """
        Load family decks (native gfx90c tile candidates per family).

        Every entry is one of three kinds, and the comment says which:

          MEASURED  the shipped-gfx900 floor's own winning solution at a named
                    cell, read from that phase's resolved 2_BenchmarkData yaml.
                    These convert known losses directly.
          QUANT     a tile chosen for 7-CU wave quantization. gfx90c has 7 CUs,
                    so ceil(N/MT)^2 tiles spread badly whenever the count is a
                    small power of two: at N=256 a 128x128 tile yields 4 tiles on
                    7 CUs and leaves 3 idle (57% of the machine), while 32x32
                    yields 64 tiles at 91%. This is the "narrower" direction.
          LADDER    a width step either side of an existing deck entry, so the
                    overnight run brackets each tile rather than guessing one
                    width.

        Widths are requested, not assumed: generate_family_phases clamps any
        width the gate rejects down to the widest it accepts, so an entry is
        never silently dropped.
        """
        return {
            # ---- SS: largest gaps in the corpus (768/1000/1024/1365/2048/4096
            # all lose 5.5-15.1%), and SS:256 sits at 25.5% of the FP32 ALU
            # roof. 128x128 + VW4 is the floor's winner everywhere (MEASURED);
            # the QUANT entries attack the 256-cell quantization loss.
            "SS": [
                # MEASURED floor winner, all 7 large cells: 128x128x8/8x8/VW4.
                {"MacroTile": "128x128x8", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
                # MEASURED floor winner at SS:256 -- 32x64x8/4x8/VW4, an
                # anisotropic tile. SS:256 is 25.5% of the 1613 GFLOPS roof, the
                # widest relative gap in the corpus, and the winning tile is
                # neither square nor in the quantisation ladder. It was never
                # generated, so native could not have matched it.
                {"MacroTile": "32x64x8", "ThreadTile": "4x8", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
                # LADDER 64x64x16/4x4/VW4: the 16 B square tile at the smallest
                # square that still has 16 tiles at N=256 (76%).
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
                # QUANT 32x32 at N=256 is 64 tiles / 7 CUs = 91% machine use,
                # the best packing of any tile in the ladder. Also 2x2 threads,
                # which halves VGPR pressure and doubles occupancy headroom.
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
                # QUANT 96x96 is non-power-of-two on purpose: ceil(2048/96)=22,
                # 22^2=484 tiles over 7 CUs quantizes far finer than 128x128's
                # 16^2=256, and at N=1365 it is the only tile in the ladder that
                # does not overshoot.
                {"MacroTile": "96x96x16", "ThreadTile": "6x6", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
                # LADDER bracket the incumbent 128x128 VW2 downward, and the
                # incumbent 64x64 VW2 upward, so both are bracketed by data.
                {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
                {"MacroTile": "128x128x8", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
                # PrefetchGlobalRead stays off at 128x128: it doubles the LDS
                # footprint to 16 KB and the tile is already at the LDS budget.
            ],
            # ---- DD: FP64 is 85-96% of its 101 GFLOPS roof on every cell except
            # DD:192, which is at 20.5% and loses 12.7%. DD is 100% VW1 across
            # all 44 measured phases, so the whole width axis is unexplored.
            "DD": [
                # MEASURED floor winner on DD:192 -- 32x32x8/4x4/VW2, never run
                # natively. DD's deck has 32x32 but at 2x2 threads and VW1.
                {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
                # MEASURED floor winner on DD:768 (a tie) and the 64x64 VW2 the
                # deck has never produced.
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
                # MEASURED floor winner on DD:1024 sits at DepthU 4, not 8 -- a
                # shallow-K variant no deck entry has expressed.
                {"MacroTile": "64x64x4", "ThreadTile": "4x4", "VectorWidth": 2},
                # QUANT DD:192 at 32x32 is 36 tiles / 7 = 86% machine use; 64x64
                # gives only 9 tiles and 64%. Keep both orientations.
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
                # LADDER: DD is at 95% of roof on the big cells, so the only
                # open width is narrower, for the small ones.
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1},
                {"MacroTile": "32x32x8", "ThreadTile": "2x2", "VectorWidth": 1},
            ],
            # ---- HH: loses 10.9-14.6% at 1024/2048/4096 while already at
            # 71-75% of the 3226 GFLOPS packed-FP16 roof -- the widest gap
            # between utilisation and verdict. Floor winner is 128x128x16 VW8.
            "HH": [
                # MEASURED floor winner on 1024/2048/4096. Native has never run
                # VW8 on any HH tile.
                {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 8, "WorkGroupMapping": 4, "PrefetchGlobalRead": False},
                # MEASURED floor winner at HH:256 -- 64x32x16, not 64x64. HH:256
                # is the one HH cell below 50% of roof (23.7%), and 64x32/4x4
                # gives 128 threads against 64x64's 64, which is the axis the
                # quantisation argument below cannot see. An earlier revision of
                # this deck asserted 64x64x16/4x4/VW4 was the measured winner;
                # it was not, and the tile that actually won was never generated.
                {"MacroTile": "64x32x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
                # QUANT HH:256 at 64x64 is 16 tiles / 7 = 76%; at 32x32 it is
                # 64 tiles and 91%, which is the only tile that meaningfully
                # unpacks the 256 square on a 7-CU part.
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 8, "WorkGroupMapping": 4},
                # QUANT 96x96/6x6: 484 tiles at N=2048, and ceil(4096/96)=43 so
                # 43^2 tiles at the top cell -- the finest quantization in the
                # ladder. 6x6 threads cap this family at VW2, which the
                # generator enforces.
                {"MacroTile": "96x96x16", "ThreadTile": "6x6", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
                # LADDER keep the incumbent 128x128 VW4 and the 64x64 VW2 so the
                # 8->4->2 descent is measured rather than assumed monotone.
                {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4, "PrefetchGlobalRead": False},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            ],
            # ---- ZZ: wins all four large cells but at 16.7-23.7% of the 101
            # GFLOPS FP64 roof -- the worst absolute utilization in the corpus.
            # Every ZZ winner is VW1 across 40 measured configs, and 128x64x8 and
            # 64x128x8 are documented as dead (accumulator VGPR overflow).
            "ZZ": [
                # MEASURED-style probe: the floor never wins ZZ above VW1, so VW2
                # is a reach test, not a conversion. 4x4 threads at complex
                # double is TT0*TT1*8 VGPRs -- over the 128 accumulator budget,
                # so the generator's occupancy gate is expected to refuse it.
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "NLCA": 1},
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1},
                # QUANT: ZZ is quantized hardest of all -- 128x128 gives 4 tiles
                # at N=256 and 16 at N=512. 32x32 is the only tile that fills 7
                # CUs. This is the single highest-leverage ZZ change.
                {"MacroTile": "32x32x8", "ThreadTile": "2x2", "NLCA": 1},
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2, "NLCA": 1},
                # MEASURED floor winner at ZZ:192 -- 32x32x8 on 4x4 threads, not
                # the 2x2 this deck had assumed. At complex double 4x4 is
                # TT0*TT1*8 = 128 accumulator VGPRs, exactly on the budget, so
                # it is legal but at the ceiling; this is the measured optimum
                # and was never generated natively.
                {"MacroTile": "32x32x8", "ThreadTile": "4x4", "NLCA": 1},
                # LADDER: exercise DepthU, which no ZZ entry has varied. Complex
                # double LDS is 8 B/elem, so DepthU 8 halves the 16 KB footprint.
                {"MacroTile": "64x64x4", "ThreadTile": "4x4", "NLCA": 1},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
                # MEASURED floor winner at ZZ:128 is 64x64x16/4x4/VW1, and
                # ZZ:512 is the same tile at DepthU 8 plus LdsPadB 1. Pad B is
                # the only ZZ knob with measured support; include it.
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "LdsPadB": 1, "NLCA": 1},
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "LdsPadB": 1, "NLCA": 1},
            ],
            # ---- CC: 2.5-19.7% of the FP32 roof on every cell, and the only
            # family where the floor's winning config was already run natively
            # and still lost. Complex single is 8 B/elem for A and B, so this
            # family is data-movement bound long before it is ALU bound: the
            # lever is tile size and LDS padding, not width (VW2 = 16 B is
            # already the cap).
            "CC": [
                # MEASURED floor winner on CC:192 -- 32x32x8/4x4/VW2, never run.
                {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
                # MEASURED floor winner on CC:256/1024/512 (64x64x8/4x4/VW2).
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
                # MEASURED floor winner on CC:2048 is the same tile with
                # LdsPadA 2, LdsPadB 0 -- asymmetric, and the only CC row in the
                # whole census with a non-zero pad. GFX9 LDS bank =
                # (byte_addr/4) mod 32, so a 128 B-aligned B row collides.
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2, "LdsPadA": 2, "LdsPadB": 0},
                # QUANT: CC is the most quantized family because a 128x128
                # complex tile is 128 KB of A and B. 32x32 is the only tile that
                # gets past 4 tiles at N=256.
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
                {"MacroTile": "16x16x16", "ThreadTile": "2x2", "VectorWidth": 2},
                # LADDER keep the incumbent VW1 tiles: at 8 B CC may genuinely
                # prefer the narrower load, and the overnight run should be able
                # to prove that rather than assume it.
                {"MacroTile": "32x32x16", "ThreadTile": "2x2"},
                {"MacroTile": "64x64x8", "ThreadTile": "4x4"},
            ],
            # ---- HH_HPA: loses 7.7-9.8% at 2048/4096. The floor wins 4096 at
            # 128x64x8 with **8x4** threads and 2048 at the transposed
            # 64x128x8/4x8, both at VW2. The deck has 128x64x16 and 64x128x16 at
            # 4x8 threads and no VW, so it expresses neither floor winner.
            "HH_HPA": [
                # MEASURED floor winner HH_HPA:4096. TT is 8x4, not the deck's
                # 4x8 -- 128/8 x 64/4 = 16x16 threads either way, but the
                # per-thread extents differ, so these are different kernels.
                {"MacroTile": "128x64x8", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 2},
                # MEASURED floor winner HH_HPA:2048, the transposed tile.
                {"MacroTile": "64x128x8", "ThreadTile": "4x8", "NLCA": 1, "VectorWidth": 2},
                # MEASURED floor winner HH_HPA:1024 (a tie): 128x64x16/8x4/VW4.
                {"MacroTile": "128x64x16", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 4},
                # QUANT 96x96 and 32x32 to unpack the 512/1024 squares.
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2},
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 2},
                # LADDER keep the incumbent, and add the asymmetric pad the CC
                # census shows is sometimes decisive.
                {"MacroTile": "64x128x16", "ThreadTile": "4x8", "NLCA": 1},
                {"MacroTile": "128x64x16", "ThreadTile": "4x8", "NLCA": 1, "LdsPadA": 2, "LdsPadB": 0},
            ],
            # ---- HS_HPA: three ties at 83-89% of roof, one win at 512. No
            # losses, so the goal here is depth: the floor's winners are the
            # 128x64x16/8x4/VW4 tile, with LdsPad 4/4 on 2048 specifically.
            "HS_HPA": [
                # MEASURED floor winner on 1024/4096 (ties).
                {"MacroTile": "128x64x16", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 4},
                # MEASURED floor winner on 2048 (tie) is the same tile with
                # LdsPadA 4, LdsPadB 4.
                {"MacroTile": "128x64x16", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 4, "LdsPadA": 4, "LdsPadB": 4},
                # MEASURED floor winner on HS_HPA:512 is 64x64x8/4x4/VW4.
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4},
                # QUANT: mirror the HH_HPA additions so the two HPA families are
                # compared on identical tiles rather than different ones.
                {"MacroTile": "128x64x8", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 2},
                {"MacroTile": "64x128x8", "ThreadTile": "4x8", "NLCA": 1, "VectorWidth": 2},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2},
                # LADDER keep the incumbent tiles.
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
                {"MacroTile": "128x64x16", "ThreadTile": "4x8", "NLCA": 1},
                {"MacroTile": "64x128x16", "ThreadTile": "4x8", "NLCA": 1},
            ],
        }
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


def parse_tensile_shape(shape_str: str) -> Dict[str, int]:
    """Parse a Tensile shape string into M, N, B, K components.

    Handles ``1024x1024x1024`` (M x N x K), ``64x4096x1_K4096`` /
    ``64x4096x1`` (M x N x B with K) and ``4x2048x64`` (M x N x K or M x N x B).

    Args:
        shape_str: The shape token to parse.

    Returns:
        ``{"M", "N", "B", "K"}``, with 1024/1 defaults for fields the token does
        not carry.
    """
    result = {"M": 1024, "N": 1024, "B": 1, "K": 1024}
    clean = str(shape_str).strip()

    # Explicit K specification (e.g. _K4096)
    k_match = re.search(r'[_xX]K(\d+)', clean, re.IGNORECASE)
    if k_match:
        result["K"] = int(k_match.group(1))
        clean = re.sub(r'[_xX]K\d+', '', clean, flags=re.IGNORECASE)

    # Explicit batch specification (e.g. _B16 or B16_)
    b_match = re.search(r'[_xX]B(\d+)', clean, re.IGNORECASE)
    if b_match:
        result["B"] = int(b_match.group(1))
        clean = re.sub(r'[_xX]B\d+', '', clean, flags=re.IGNORECASE)

    parts = re.findall(r'\d+', clean)
    if len(parts) >= 3:
        result["M"] = int(parts[0])
        result["N"] = int(parts[1])
        # 3 parts and no explicit K/B: the third is K when B was not named.
        p3 = int(parts[2])
        if k_match:
            result["B"] = p3
        else:
            result["K"] = p3
    elif len(parts) == 2:
        result["M"] = int(parts[0])
        result["N"] = int(parts[1])

    return result


