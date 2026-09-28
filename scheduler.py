#!/usr/bin/env python3
"""
scheduler.py — Stage 2: Candidate Generation

Emits candidate configs for benchmarking; occupancy-aware GSU/WGM/MT/TT sizing.
Appends candidates to phases.yaml manifest.
"""

import json
import math
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import hashlib

from gfx90c_common import NUM_CUS, LDS_PER_CU_KB, FAMILY_DTYPE_CHAR, MAX_WAVES_PER_CU


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
        self.base_dir = Path(base_dir)
        self.registry = registry
        self.family_decks = self._load_family_decks()

    def _load_family_decks(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load family decks (native gfx90c tile candidates per family).
        """
        return {
            "SS": [
                {"MacroTile": "96x96x16", "ThreadTile": "6x6", "NLCA": 3, "VectorWidth": 2, "WorkGroupMapping": 4},
                {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            ],
            "DD": [
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1},
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 1},
            ],
            "HH": [
                {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 4, "PrefetchGlobalRead": False},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2},
            ],
            "ZZ": [
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
                {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1},
            ],
            "CC": [
                {"MacroTile": "32x32x16", "ThreadTile": "2x2"},
                {"MacroTile": "64x64x8", "ThreadTile": "4x4"},
            ],
            "HH_HPA": [
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
                {"MacroTile": "128x64x16", "ThreadTile": "4x8", "NLCA": 1},
            ],
            "HS_HPA": [
                {"MacroTile": "64x64x8", "ThreadTile": "4x4", "NLCA": 1},
                {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
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

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate a candidate config for gfx90c legality and constraints.
        """
        illegal_knobs = ["SIA", "Fp16AltImpl", "HasMFMA"]
        for knob in illegal_knobs:
            if knob in config and config[knob] not in [False, 0, None]:
                return False, f"Illegal knob {knob} for gfx90c"

        if "AssertSizeMultiple" in config:
            asm = config["AssertSizeMultiple"]
            if isinstance(asm, list) and asm == [1]:
                return False, "AssertSizeMultiple: [1] causes crashes"

        # MacroTile / ThreadTile divisibility & workgroup size validation
        mt = config.get("MacroTile")
        tt = config.get("ThreadTile")
        if mt and tt:
            try:
                mt_clean = str(mt).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
                mt_parts = [int(p) for p in (mt_clean.split("X") if "X" in mt_clean else mt_clean.split("x"))[:2]]
                tt_clean = str(tt).lower().replace("_", "x")
                tt_parts = [int(p) for p in tt_clean.split("x")[:2]]
                
                if len(mt_parts) == 2 and len(tt_parts) == 2:
                    if tt_parts[0] <= 0 or tt_parts[1] <= 0:
                        return False, f"Invalid ThreadTile dimensions: {tt}"
                    if mt_parts[0] % tt_parts[0] != 0 or mt_parts[1] % tt_parts[1] != 0:
                        return False, f"Indivisible tile: MacroTile {mt} not divisible by ThreadTile {tt}"
                    
                    wg_threads = (mt_parts[0] // tt_parts[0]) * (mt_parts[1] // tt_parts[1])
                    if wg_threads < 64 or wg_threads > 1024 or wg_threads % 64 != 0:
                        return False, f"Invalid WorkGroup thread count: {wg_threads} (must be multiple of 64 in [64, 1024])"
            except (ValueError, IndexError):
                pass

        # Assembly-class validity (GSU/DepthU vs dtype vs AF0EM — SolutionStructs)
        asm_ok, asm_reason = assembly_class_valid(config)
        if not asm_ok:
            return False, f"Assembly class: {asm_reason}"

        # Tensile-faithful global load divisibility validation
        tl_ok, tl_reason = self._validate_tensile_loads(config)
        if not tl_ok:
            return False, f"Tensile load divisibility: {tl_reason}"

        lds_kb_est = self._estimate_lds_usage(config)
        if lds_kb_est > LDS_PER_CU_KB:
            return False, f"LDS overflow: {lds_kb_est:.1f}KB > {LDS_PER_CU_KB}KB"

        # Register-file / occupancy feasibility. This is the gate that catches
        # Tensile's overflowedResources==4 ("Occupancy limit"), which the
        # previous _estimate_occupancy could never fire (it ignored MacroTile
        # and never counted VGPRs). See occupancy_feasible() for the model.
        occ_ok, occ_reason = occupancy_feasible(config)
        if not occ_ok:
            return False, f"Occupancy limit: {occ_reason}"

        return True, "Valid"

    @staticmethod
    def _validate_tensile_loads(config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Faithful port of Tensile SolutionStructs classic-path divisibility:
        setGlobalLoadVectorWidth + setGlobalLoadTileDimClassic.
        Only covers non-MI, FractionalLoad=False, Assembly kernel path.
        """
        DTYPE_INFO = {
            "S":  {"reg": 1,   "bytes": 4,  "isHalf": False, "isInt8": False},
            "D":  {"reg": 2,   "bytes": 8,  "isHalf": False, "isInt8": False},
            "H":  {"reg": 0.5, "bytes": 2,  "isHalf": True,  "isInt8": False},
            "B":  {"reg": 0.5, "bytes": 2,  "isHalf": False, "isInt8": False},
            "Z":  {"reg": 2,   "bytes": 8,  "isHalf": False, "isInt8": False},
            "C":  {"reg": 2,   "bytes": 8,  "isHalf": False, "isInt8": False},
            "I8": {"reg": 0.25,"bytes": 1,  "isHalf": False, "isInt8": True},
        }

        # Parse MT
        mt_raw = config.get("MacroTile", "64x64x16")
        mt_clean = str(mt_raw).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
        mt_parts = [int(x) for x in re.split(r'[xX]', mt_clean)]
        if len(mt_parts) < 2:
            return True, ""
        mt0, mt1 = mt_parts[0], mt_parts[1]
        depthU = int(config.get("DepthU", mt_parts[2])) if len(mt_parts) >= 3 else int(config.get("DepthU", 16))

        # Parse TT
        tt_raw = config.get("ThreadTile", "4x4")
        tt_clean = str(tt_raw).lower().replace("_", "x")
        tt_parts = [int(x) for x in re.split(r'[xX]', tt_clean)]
        if len(tt_parts) < 2:
            return True, ""
        tt0, tt1 = tt_parts[0], tt_parts[1]

        if tt0 <= 0 or tt1 <= 0:
            return True, ""

        # WorkGroup derived from MT/TT
        wg0, wg1 = mt0 // tt0, mt1 // tt1
        NumThreads = wg0 * wg1

        # DataType
        dtype_char = str(config.get("DataType", config.get("dtype", "S"))).upper()
        if dtype_char in ("SS",): dtype_char = "S"
        elif dtype_char in ("DD",): dtype_char = "D"
        elif dtype_char in ("HH",): dtype_char = "H"
        elif dtype_char in ("ZZ",): dtype_char = "Z"
        elif dtype_char in ("CC",): dtype_char = "C"
        elif dtype_char in ("FF",): dtype_char = "S"
        dtype = DTYPE_INFO.get(dtype_char, DTYPE_INFO["S"])

        # VectorWidth default (non-MI)
        vw_user = config.get("VectorWidth")
        if vw_user is None or int(vw_user) < 1:
            vw = int(4.0 / dtype["reg"])
            while (tt0 % vw != 0 or tt1 % vw != 0) and vw > 1:
                vw //= 2
        else:
            vw = int(vw_user)

        if vw < 1:
            return True, ""

        # TT must be multiples of VW (SolutionStructs:3413)
        if tt0 % vw != 0 or tt1 % vw != 0:
            return False, f"TT0={tt0} or TT1={tt1} not multiple of VW={vw}"

        # Half requires VW >= 2 (SolutionStructs:3435)
        if dtype["isHalf"] and vw < 2:
            return False, "VW must be >= 2 for half"

        # GLVW default: max(VW, numElemPerReg) for assembly (SolutionStructs:3451)
        numElemPerReg = math.ceil(1.0 / dtype["reg"]) if dtype["reg"] > 0 else 1
        glvw = max(vw, numElemPerReg)

        # GLVW * bpe <= 16 (SolutionStructs:3460)
        if glvw * dtype["bytes"] > 16:
            return False, f"GLVW {glvw} * bpe {dtype['bytes']} > 16"

        # TLUA/TLUB from pattern (ContractionPattern or label)
        pattern = str(config.get("ContractionPattern", config.get("label", "Ailk_Bjlk")))
        tluA = "Ailk" in pattern
        tluB = "Bjlk" in pattern

        # Per-operand load validation
        for tc, tlu, mt_tc in [("A", tluA, mt0), ("B", tluB, mt1)]:
            if tlu:
                totalElementsCoalesced = mt_tc
                totalElementsPerp = depthU
            else:
                totalElementsCoalesced = depthU
                totalElementsPerp = mt_tc
            totalElements = totalElementsCoalesced * totalElementsPerp

            numThreadGrvw = NumThreads * glvw
            pv = 1
            if totalElements < numThreadGrvw:
                pv = numThreadGrvw // totalElements
                if numThreadGrvw % totalElements != 0:
                    return False, f"{tc}: (NumThreads*glvw)={numThreadGrvw} % totalElements={totalElements} != 0"
                if pv * totalElements != numThreadGrvw:
                    return False, f"{tc}: pv={pv} * totalElements={totalElements} != numThreadGrvw={numThreadGrvw}"
                if glvw < 1 or glvw % pv != 0:
                    return False, f"{tc}: GLVW={glvw} % pv={pv} != 0"
                numLoads = totalElements // (numThreadGrvw // pv)
            else:
                if totalElements % numThreadGrvw != 0:
                    return False, f"{tc}: totalElements={totalElements} % (NumThreads*glvw)={numThreadGrvw} != 0"
                numLoads = totalElements // numThreadGrvw

            # GLVW==VW-or-1: post-pv-reduction shift-ptr guard (SolutionStructs:4583-4596)
            glvw_eff = glvw // pv
            if glvw_eff > 1 and glvw_eff != vw:
                return False, f"{tc}: GLVW={glvw_eff} must be == VectorWidth {vw} or == 1"

            totalVectorsCoalesced = totalElementsCoalesced // glvw

            # NumLoadsCoalesced check (SolutionStructs:2058)
            nlca_key = f"NumLoadsCoalesced{tc}"
            nlca = int(config.get(nlca_key, config.get("NLCA", 1)))

            if nlca == 1:
                found = False
                for n in range(1, numLoads + 1):
                    nlp = numLoads // n
                    if (numLoads % n == 0
                        and totalVectorsCoalesced % n == 0
                        and totalElementsPerp % nlp == 0):
                        found = True
                        break
                if not found:
                    return False, f"{tc}: No valid NumLoadsCoalesced=1 found"
            elif nlca == -1:
                found = False
                for n in range(numLoads, 0, -1):
                    nlp = numLoads // n
                    if (numLoads % n == 0
                        and totalVectorsCoalesced % n == 0
                        and totalElementsPerp % nlp == 0):
                        found = True
                        break
                if not found:
                    return False, f"{tc}: No valid NumLoadsCoalesced=-1 found"
            else:
                if nlca > numLoads:
                    return False, f"{tc}: NLCA={nlca} > NumLoads={numLoads}"
                nlp = numLoads // nlca
                if numLoads % nlca != 0:
                    return False, f"{tc}: NumLoads={numLoads} % NLCA={nlca} != 0"
                if totalVectorsCoalesced % nlca != 0:
                    return False, f"{tc}: totalVectorsCoalesced={totalVectorsCoalesced} % NLCA={nlca} != 0"
                if totalElementsPerp % nlp != 0:
                    return False, f"{tc}: totalElementsPerp={totalElementsPerp} % NumLoadsPerp={nlp} != 0"

            # depthU >= GLVW when !TLU (SolutionStructs:3793)
            if not tlu and depthU < glvw:
                return False, f"{tc}: depthU={depthU} < GLVW={glvw} (TLU=False)"

        return True, ""

    def _estimate_lds_usage(self, config: Dict[str, Any]) -> float:
        """
        Estimate LDS usage in KB for GEMM tile.
        Formula: (MacroTile0 * DepthU + MacroTile1 * DepthU) * elem_size * NLCA
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

    def _estimate_occupancy(self, config: Dict[str, Any]) -> float:
        """Modelled workgroups-per-CU from the register file (gfx90c).

        Delegates to occupancy_feasible()'s model so the number reported here
        and the pass/fail decision can never disagree. The previous version
        inferred threads from ThreadTile via a `64 // tt` heuristic, ignored
        MacroTile and VGPRs entirely, and therefore returned >= 1 for every
        config — which is how all 8 ZZ phases in run_20260926_201835 reached the
        compiler and died there with overflowedResources==4.
        """
        ok, _reason = occupancy_feasible(config)
        if not ok:
            return 0.0
        return float(occupancy_workgroups_per_cu(config))

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
        added = 0
        rejected: List[str] = []
        for cand in candidates:
            merged = {**cand.template, **cand.knobs}
            ok, why = self.validate_config(merged)
            if not ok:
                rejected.append(f"{cand.phase_id}: {why}")
                continue
            if cand.fingerprint not in existing_fps:
                phase_entry = {
                    "phase_id": cand.phase_id,
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
                added += 1

                if self.registry is not None:
                    self.registry.append_phase(cand.phase_id, cand.fingerprint, phase_entry)

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
                for shape in base_shapes:
                    label = f"{family}_{pattern}_{shape}{tile_tag}"
                    phase_id = f"phase_{family.lower()}_{pattern}_{shape}{tile_tag}"

                    template = {
                        "Architecture": "gfx90c",
                        "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
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
                    if not is_valid:
                        continue

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


def parse_tensile_shape(shape_str: str) -> Dict[str, int]:
    """
    Parse Tensile shape string into M, N, B, K components.
    Handles formats:
    - 1024x1024x1024 (M x N x K)
    - 64x4096x1_K4096 or 64x4096x1 (M x N x B with K)
    - 4x2048x64 (M x N x K or M x N x B)
    """
    result = {"M": 1024, "N": 1024, "B": 1, "K": 1024}
    clean = str(shape_str).strip()
    
    # Check for explicit K specification (e.g. _K4096)
    k_match = re.search(r'[_xX]K(\d+)', clean, re.IGNORECASE)
    if k_match:
        result["K"] = int(k_match.group(1))
        clean = re.sub(r'[_xX]K\d+', '', clean, flags=re.IGNORECASE)

    # Check for explicit batch specification (e.g. _B16 or B16_)
    b_match = re.search(r'[_xX]B(\d+)', clean, re.IGNORECASE)
    if b_match:
        result["B"] = int(b_match.group(1))
        clean = re.sub(r'[_xX]B\d+', '', clean, flags=re.IGNORECASE)

    parts = re.findall(r'\d+', clean)
    if len(parts) >= 3:
        result["M"] = int(parts[0])
        result["N"] = int(parts[1])
        # If 3 parts and no explicit K/B, third is K if B was 1
        p3 = int(parts[2])
        if k_match:
            result["B"] = p3
        else:
            result["K"] = p3
    elif len(parts) == 2:
        result["M"] = int(parts[0])
        result["N"] = int(parts[1])

    return result


_ASSEMBLY_DTYPE_ELEM_BYTES = {
    "S": 4, "D": 8, "H": 2, "B": 2, "Z": 16, "C": 8, "I8": 1, "I1": 1,
}


def _assembly_depth_u(config: Dict[str, Any]) -> int:
    """Resolve DepthU: explicit key first, else from the MacroTile string."""
    if config.get("DepthU") is not None:
        return int(config["DepthU"])
    mt = str(config.get("MacroTile", "64x64x16"))
    parts = re.split(r"[xX]", mt.replace("MT", ""))
    if len(parts) >= 3:
        try:
            return int(parts[2])
        except ValueError:
            pass
    return 16


# ---------------------------------------------------------------------------
# Register-file / occupancy feasibility (Tensile overflowedResources==4)
# ---------------------------------------------------------------------------
#
# Tensile source of truth — Tensile/KernelWriterAssembly.py, functionSuffix:
#
#     vgprPerCU = 65536
#     vgprPerThreadPerOccupancy = vgprPerCU // kernel["NumThreads"]
#     numWorkGroupsPerCU = vgprPerThreadPerOccupancy // max(vgpr, agpr)
#     if numWorkGroupsPerCU < 1:
#         self.overflowedResources = 4      # "Occupancy limit"
#
# i.e. error 4 is REGISTER-FILE exhaustion, not LDS. It is only detectable at
# kernel-generation time, which is why it cannot be caught by the divisibility
# or assembly-class gates — those all pass on a config that dies here.
#
# Model. With NumThreads = (MT0/TT0)*(MT1/TT1):
#     acc_vgprs_per_thread = TT0*TT1*R
#     budget               = 65536 // NumThreads
#     acc/budget           = R * MT0 * MT1 / 65536      <- ThreadTile cancels
# so the decision depends only on dtype weight R and MacroTile AREA. R
# additionally absorbs the operand/address/local-read pipeline registers that
# an accumulator-only count misses.
#
# RETIRED: this gate used to model R * MacroTile_area <= 65536/2. That model was
# calibrated against the pass/fail boundary but was structurally wrong, and real
# runs proved it. It predicted complex (Z) 128x64 and 64x128 would fail -- true,
# but for the wrong reason -- while passing complex 128x32, which then died 116
# times in run_20260928_024945. Building every phase's kernel with Tensile's own
# writer (check_tensile_build.py, CPU-only) showed the constraint is the
# per-thread accumulator count TT0*TT1*weight against the 256 VGPR/thread ISA
# limit, and MacroTile is not in the expression at all. Calibration table now
# lives in MEASURED_VGPR below; post-mortem in potential_configs.md.

# Register file is 64K VGPRs per CU, but a single thread is architecturally
# capped at 256 VGPRs. Tensile enforces that cap when generating assembly and
# raises instead of emitting a kernel
# (KernelWriterAssembly: "total vgpr: N not in [0, 256]").
VGPR_PER_CU = 65536
MAX_VGPR_PER_THREAD = 256
# Effective VGPRs consumed per thread-tile element, per dtype char.
VGPR_PER_ELEMENT = {"S": 1, "D": 2, "H": 1, "B": 1, "I8": 1, "C": 4, "Z": 8}
# Accumulator VGPRs budgeted per thread, chosen from measurement (see
# _measured_accvgpr below): 128 keeps the observed worst case (199 VGPRs for
# TT 4x4 complex) under the 256 cap, while the first failing step
# (TT 8x4 complex, 256 accVGPRs -> 271 VGPRs) is excluded.
ACCVGPR_BUDGET = 128
# LDS budget per workgroup, expressed in the *unpadded* base tile footprint
# (MacroTile0 + MacroTile1) * DepthU * bytesPerElement. Tensile's real check
# (SolutionStructs:4334, "Kernel Uses %u > %u bytes of LDS") runs against an
# allocator result inflated by prefetch double-buffering, power-of-two offset
# alignment and LdsPad, so the base is not the number Tensile compares -- but it
# is a sound *upper-bound* proxy in the only direction that matters here.
# Measured complex (Z, 8 B) boundary on gfx90c: 16384 legal, 20480 dead
# (128x32x16 needs 106496 B and is rejected). Deliberately conservative: it may
# refuse a config Tensile would accept, never admits one Tensile refuses.
LDS_BUDGET = 16384
# Bytes per element for the LDS footprint, by dtype char. Note this is NOT
# VGPR_PER_ELEMENT: a f64 element is 8 bytes but only 2 VGPRs, while a complex
# f64 element is 8 VGPRs and 8 bytes.
BYTES_PER_ELEMENT = {"S": 4, "D": 8, "H": 2, "B": 1, "I8": 1, "C": 8, "Z": 8}
# Retained for the workgroup estimate: budget is expressed in accumulators, and
# the register file is shared by every thread in a workgroup.
VGPR_BUDGET = VGPR_PER_CU // 2

# Measured per-thread VGPR totals from Tensile's own kernel writer on gfx90c,
# reported by check_tensile_build.py. (threadtile, accvgpr, observed total).
# Every entry satisfies: total = accvgpr + a small tile-dependent overhead, and
# the pass/fail boundary is exactly accvgpr > 128 for complex.
MEASURED_VGPR = {
    (2, 2): 63, (4, 2): 95, (2, 4): 99, (4, 4): 154,
    (2, 8): 171, (8, 4): 271, (8, 8): 519,
}


def _measured_accvgpr(tt0: int, tt1: int, weight: int) -> int:
    """Accumulator VGPRs per thread for a thread tile and dtype weight."""
    return tt0 * tt1 * weight


def _depth_u(config: Dict[str, Any]) -> int:
    """DepthU (K-dimension tile depth), 0 when it cannot be determined.

    Depth lives in two different places depending on who wrote the config:
    scheduler-generated phases carry it as the third MacroTile field
    ("128x32x16" -> 16) and omit the DepthU key entirely, while explicit configs
    and tests set DepthU directly. Both must resolve, or the LDS gate silently
    computes a footprint 16x too small and waves through 128x32x16.
    """
    for key in ("DepthU", "depth_u"):
        raw = config.get(key)
        try:
            ku = int(raw)
        except (TypeError, ValueError):
            continue
        if ku > 0:
            return ku
    raw_mt = config.get("MacroTile", config.get("macro_tile"))
    if raw_mt:
        parts = str(raw_mt).split("x")
        if len(parts) >= 3:
            try:
                ku = int(parts[2])
            except ValueError:
                return 0
            return ku if ku > 0 else 0
    return 0


def _lds_base_bytes(mt0: int, mt1: int, ch: str) -> int:
    """Unpadded LDS footprint of one workgroup's A and B tiles."""
    bpe = BYTES_PER_ELEMENT.get(ch)
    if bpe is None:
        return 0
    return (mt0 + mt1) * bpe


def _tile_dims(config: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
    """(MT0, MT1, TT0, TT1) from MacroTile/ThreadTile, or None if unusable."""
    mt_raw = config.get("MacroTile")
    tt_raw = config.get("ThreadTile")
    if not mt_raw or not tt_raw:
        return None
    mt_clean = str(mt_raw).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
    tt_clean = str(tt_raw).lower().replace("_", "x")
    try:
        mt_parts = [int(x) for x in re.split(r'[xX]', mt_clean)]
        tt_parts = [int(x) for x in re.split(r'[xX]', tt_clean)]
    except ValueError:
        return None
    if len(mt_parts) < 2 or len(tt_parts) < 2:
        return None
    if mt_parts[0] <= 0 or mt_parts[1] <= 0 or tt_parts[0] <= 0 or tt_parts[1] <= 0:
        return None
    return mt_parts[0], mt_parts[1], tt_parts[0], tt_parts[1]


def _dtype_char(config: Dict[str, Any]) -> str:
    """Dtype char for a config, or "" when it cannot be determined.

    Never guesses a default: a wrong guess would pick the wrong VGPR weight
    (Z is 8, S is 1) and silently admit a config the gate must reject. Callers
    fail closed on "".
    """
    raw = config.get("DataType", config.get("dtype"))
    if raw is None:
        # Label-only configs exist in the auto-generated phases; the label
        # carries the same information, so resolve through it rather than
        # failing closed on a config whose dtype is knowable.
        raw = config.get("FamilyLabel", config.get("family_label"))
    if raw is None:
        return ""
    ch = str(raw).upper()
    return {"SS": "S", "DD": "D", "HH": "H", "ZZ": "Z", "CC": "C", "FF": "S"}.get(ch, ch)


def occupancy_workgroups_per_cu(config: Dict[str, Any]) -> int:
    """Modelled workgroups per CU; 0 when the gate rejects the config.

    Per-thread register demand is fixed by the thread tile (accumulators) and
    shared across the workgroup, so this is the 64K file divided by the
    per-thread cost. 0 means "this config is not launchable", not "zero
    occupancy".
    """
    dims = _tile_dims(config)
    if not dims:
        return 0
    mt0, mt1, tt0, tt1 = dims
    r = VGPR_PER_ELEMENT.get(_dtype_char(config))
    if r is None:
        return 0
    acc = _measured_accvgpr(tt0, tt1, r)
    if acc > ACCVGPR_BUDGET:
        return 0
    ku = _depth_u(config)
    if ku <= 0:
        return 0
    if _lds_base_bytes(mt0, mt1, _dtype_char(config)) * ku > LDS_BUDGET:
        return 0
    return VGPR_PER_CU // acc


def occupancy_feasible(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Register-file gate: reject configs Tensile cannot generate.

    Complements (does not replace) validate_config / _validate_tensile_loads /
    assembly_class_valid: those check divisibility and dtype-class legality,
    which an over-wide thread tile passes.

    The constraint is on **ThreadTile**, not MacroTile. A thread holds
    TT0 x TT1 accumulators, each `weight` VGPRs, so

        accVGPRs = TT0 * TT1 * weight

    and MacroTile only changes how many threads share the file, not the
    per-thread cost. Tensile then refuses to emit a kernel once the per-thread
    total crosses 256 VGPRs. Measured on gfx90c, complex (Z, weight 8):

        TT 2x2 ->  32 accVGPR ->  63-71 VGPRs  ok
        TT 4x2 ->  64 accVGPR ->  95-99 VGPRs  ok
        TT 4x4 -> 128 accVGPR -> 154-199 VGPRs  ok
        TT 8x4 -> 256 accVGPR -> 271 VGPRs     FAIL "not in [0, 256]"
        TT 8x8 -> 512 accVGPR -> 519 VGPRs     FAIL

    An earlier version of this gate modelled MacroTile area instead and was
    wrong in both directions: it passed TT 8x4 complex (the 8 ZZ phases that
    died 116 times each across real runs) and rejected nothing that Tensile
    accepts. See potential_configs.md for the full post-mortem.
    """
    dims = _tile_dims(config)
    if not dims:
        return True, ""                      # nothing to model; other gates own it
    mt0, mt1, tt0, tt1 = dims
    ch = _dtype_char(config)
    r = VGPR_PER_ELEMENT.get(ch)
    if r is None:
        # Fail closed: an unmodelled dtype could be a complex one (Z weights 8),
        # and guessing low would let a config through that then dies as error 4.
        return False, (f"DataType {ch or '<missing>'!r} has no VGPR weight in "
                       f"VGPR_PER_ELEMENT; cannot prove register-file occupancy")
    ku = _depth_u(config)
    acc = _measured_accvgpr(tt0, tt1, r)
    if acc > ACCVGPR_BUDGET:
        observed = MEASURED_VGPR.get((tt0, tt1))
        seen = f"; measured {observed} VGPRs" if observed else ""
        return False, (
            f"ThreadTile {tt0}x{tt1} needs {acc} accumulator VGPRs/thread "
            f"({ch} weight {r}), budget {ACCVGPR_BUDGET}{seen}. Tensile emits "
            f"'total vgpr: N not in [0, {MAX_VGPR_PER_THREAD}]' and refuses the "
            f"kernel. Reduce ThreadTile to {ACCVGPR_BUDGET // r} elements or fewer "
            f"(e.g. {(2, 2) if r >= 8 else (4, 4)} for this dtype)."
        )

    if ku <= 0:
        # Fail closed for the same reason as an unknown dtype weight: a config
        # whose depth cannot be read computes a footprint up to 16x too small,
        # which is exactly how 128x32x16 slipped through an earlier revision.
        return False, (
            "DepthU could not be determined from DepthU or MacroTile; cannot "
            "prove the LDS footprint. Set MacroTile as 'MT0xMT1xDepthU' or set "
            "DepthU explicitly."
        )
    lds = _lds_base_bytes(mt0, mt1, ch) * ku
    if lds > LDS_BUDGET:
        return False, (
            f"MacroTile {mt0}x{mt1} at DepthU {ku} needs a {lds}-byte LDS tile "
            f"footprint for {ch}, budget {LDS_BUDGET}. Prefetch double-buffering "
            f"and offset alignment push the real figure well past 64 KB, so "
            f"Tensile rejects it with 'Kernel Uses N > 65536 bytes of LDS' and "
            f"the phase yields zero solutions. Reduce MacroTile area or DepthU "
            f"(keep (MT0+MT1)*DepthU <= {LDS_BUDGET // BYTES_PER_ELEMENT[ch]})."
        )
    return True, ""


def assembly_class_valid(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (True, "") if config is a legal gfx90c Assembly GEMM class.

    CLASS-BASED validity — single source of truth for both seams (scheduler
    validate_config + port_tensile _write_phase_config). Any cell that falls in
    an illegal class is auto-caught pre-run, never launched on gfx90c. Faithful
    to the Tensile SolutionStructs Assembly rejects reproduced from the 24
    draft-run failures (gfx90c = Assembly-only, FFMA, no MatrixInstruction/MFMA
    escape; Tensile v4.44.0):
      SolutionStructs:3553  "GlobalSplitU only compatible with single, or asm and
                             (half or mixed) precision, or EnableMatrixInstruction"
      SolutionStructs:3616  "Assembly GSU half requires AssertFree0ElementMultiple>=2"
      SolutionStructs:3342  "StaggerUStride < DepthU * BytesPerElement"
    Rules:
      1. GlobalSplitU > 1 on complex (Z/C) — illegal on gfx90c (no MFMA;
         SolutionStructs:3553).
      2. GlobalSplitU > 1 on half with f32 accumulate (HPA / HS_HPA,
         ComputeDataType 's') — illegal (needs half/mixed compute or MFMA;
         SolutionStructs:3553).
      3. GlobalSplitU > 1 on half Assembly — legal only if
         AssertFree0ElementMultiple >= 2 (deck ships AF0EM = 1 -> illegal;
         SolutionStructs:3616).
      4. DepthU * BytesPerElement > StaggerUStride (default 256) — illegal
         (complex DepthU>=32 -> 512 > 256; also LDS > 64KB on gfx90c;
         SolutionStructs:3342).
    """
    dtype_upper = str(config.get("DataType", "S")).upper()
    gsu = int(config.get("GlobalSplitU", 1))
    depth_u = _assembly_depth_u(config)
    is_hpa = bool(config.get("HighPrecisionAccumulate", False)) or (
        "HPA" in str(config.get("FamilyLabel", "")).upper()
        or "HPA" in str(config.get("label", "")).upper()
    )
    is_hs_hpa = is_hpa and dtype_upper in ("H", "B")

    if dtype_upper in ("Z", "C") and gsu > 1:
        return False, (f"GlobalSplitU={gsu} on complex {dtype_upper}: illegal on "
                       "gfx90c (no MatrixInstruction; SolutionStructs:3553)")

    if dtype_upper in ("H", "B") and is_hs_hpa and gsu > 1:
        return False, (f"GlobalSplitU={gsu} on half with f32 accumulate "
                       "(HPA): illegal on gfx90c (needs half/mixed compute or "
                       "MFMA; SolutionStructs:3553)")

    if dtype_upper in ("H", "B") and gsu > 1:
        af0em = int(config.get("AssertFree0ElementMultiple",
                               config.get("AssertFree0Multiple", 1)))
        if af0em < 2:
            return False, (f"GlobalSplitU={gsu} on half Assembly requires "
                           "AssertFree0ElementMultiple>=2 (have "
                           f"{af0em}; SolutionStructs:3616)")

    bpe = _ASSEMBLY_DTYPE_ELEM_BYTES.get(dtype_upper, 4)
    stagger = int(config.get("StaggerUStride", 256))
    if depth_u * bpe > stagger:
        return False, (f"DepthU={depth_u} * {bpe}B = {depth_u*bpe} > "
                       f"StaggerUStride={stagger}: complex DepthU>=32 illegal "
                       "on gfx90c (SolutionStructs:3342)")

    return True, ""
