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

from gfx90c_common import NUM_CUS, LDS_PER_CU_KB, PEAK_GFLOPS


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
        self.mapping_path = self.base_dir / "mapping.md"
        self.registry = registry
        self.family_decks = self._load_family_decks()

    def _load_family_decks(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load family decks from mapping.md §1 & §3.
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

        occupancy = self._estimate_occupancy(config)
        if occupancy < 1:
            return False, f"Occupancy too low: {occupancy}"

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
        """Estimate CU occupancy considering workgroup size and VGPR limit."""
        wg = config.get("WorkGroupMapping", 4)
        tt = config.get("ThreadTile", "4x4")
        
        # Estimate threads per workgroup from MacroTile / ThreadTile
        m_threads, n_threads = 16, 16
        if isinstance(tt, str):
            clean_tt = tt.replace("_", "x").lower()
            parts = clean_tt.split("x")
            if len(parts) >= 2:
                try:
                    tt_m = max(1, int(parts[0]))
                    tt_n = max(1, int(parts[1]))
                    # Rough estimate
                    m_threads = max(4, 64 // tt_m)
                    n_threads = max(4, 64 // tt_n)
                except ValueError:
                    pass
        
        threads_per_wg = m_threads * n_threads
        waves_per_wg = max(1, threads_per_wg // 64)
        
        # Max waves per CU is 40 on gfx90c
        max_wgs_by_waves = max(1, 40 // waves_per_wg)
        return min(max_wgs_by_waves, NUM_CUS)

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
        """
        target_yaml = phases_file or (self.base_dir / "phases.yaml")
        existing_phases = []
        if target_yaml.exists():
            with open(target_yaml, "r") as f:
                existing_phases = yaml.safe_load(f) or []

        existing_fps = {p.get("fp") for p in existing_phases if isinstance(p, dict)}
        added = 0
        for cand in candidates:
            if cand.fingerprint not in existing_fps:
                phase_entry = {
                    "phase_id": cand.phase_id,
                    "label": cand.label,
                    "dtype": cand.dtype,
                    "shapes": cand.shapes,
                    "ScheduleName": "isa",
                    "NumBenchmarks": 8,
                    "config": {**cand.template, **cand.knobs},
                    "fp": cand.fingerprint
                }
                existing_phases.append(phase_entry)
                existing_fps.add(cand.fingerprint)
                added += 1

                if self.registry is not None:
                    self.registry.append_phase(cand.phase_id, cand.fingerprint, phase_entry)

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
                        "DataType": self._family_to_dtype(family),
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
                        dtype=self._family_to_dtype(family),
                        shapes=[shape],
                        template=template,
                        knobs=rel
                    )
                    candidates.append(candidate)

        if candidates:
            self.append_candidates_batch(candidates)

        return candidates

    def _family_to_dtype(self, family: str) -> str:
        """Map family name to Tensile DataType string."""
        mapping = {
            "SS": "S",
            "DD": "D",
            "HH": "H",
            "ZZ": "Z",
            "CC": "C",
            "HH_HPA": "H",
            "HS_HPA": "H",
        }
        return mapping.get(family, "S")


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


def classify_bound_class(shape_str: str, dtype: str) -> str:
    """Classify a cell as ALU-bound or DDR-bound."""
    shape = parse_tensile_shape(shape_str)
    if shape["M"] <= 128 or shape["N"] <= 64 or shape["K"] <= 64:
        return "DDR"
    return "ALU"


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
