#!/usr/bin/env python3
"""The per-family mutation patterns for the DB-hooked mutator.

Owns: ``DbPatternsMixin`` -- one ``_<family>_mutation_pattern`` per family, each
documented with the failure mode it is designed to attack:

  * ``SS`` wave coverage / occupancy
  * ``DD`` register pressure / VGPR
  * ``CC`` total-elements divisibility / LDS pad
  * ``ZZ`` low ceilings / vector width / thread tile

plus ``_forward_draws`` (small random combinations of forward knobs from the
NARROW/WIDE surface) and ``_floor_direction`` (the deltas that move a parent
toward the floor winner).
Does NOT own: the domains they draw from (oto.tensile.synthesis.db_knobs) or the
mutant synthesis that gates them (oto.tensile.synthesis.db).
Public API: DbPatternsMixin.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from oto.tensile.synthesis.db_knobs import (_DEFAULT_PATTERN, _DONOR_POOL,
                                            _FORWARD_DRAWS,
                                            FORWARD_KNOB_DOMAINS,
                                            forward_domain)
from oto.tensile.synthesis.tile_space import TILE_KNOBS


class DbPatternsMixin:
    """Per-family mutation patterns, mixed into DBMutator."""


    def _forward_draws(self, rng: random.Random,
                        family: Optional[str] = None) -> List[Dict[str, Any]]:
        """Small random combos of forward knobs (the NARROW/WIDE surface).

        Each draw changes 1-3 forward knobs to a legal value, so a donor tile
        re-combined with a forward draw is a genuinely new config, not a
        re-measure of a shipped vector. Increased from 3 to 5 draws per
        iteration to cover more of the forward-knob space.

        Diagonal combinations (2-3 knobs simultaneously) are preferred over
        single-knob changes to escape local optima faster.
        """
        knobs = list(FORWARD_KNOB_DOMAINS)
        out: List[Dict[str, Any]] = []
        for _ in range(_FORWARD_DRAWS):
            n_knobs = rng.randint(1, 3)  # 1-3 knobs per draw
            draw: Dict[str, Any] = {}
            for k in rng.sample(knobs, n_knobs):
                draw[k] = rng.choice(forward_domain(family, k))
            out.append(draw)
        return out

    # -- family-specific mutation patterns -------------------------------

    def _ss_mutation_pattern(self, parent_config: Dict[str, Any],
                             rng: random.Random) -> List[Dict[str, Any]]:
        """SS-family-specific mutations targeting sore losers.

        SS family suffers from wave-quantization and occupancy starvation.
        These patterns target the exact knobs that improve wave coverage:
        NLCA, WGM, GSU, StaggerU, LdsPad, GLVW.
        """
        patterns: List[Dict[str, Any]] = []
        knobs = list(FORWARD_KNOB_DOMAINS)

        # Pattern 1: NLCA toggle (1→3 or 3→1) + LdsPad increase
        for nlca_val in [1, 3]:
            for lspad_val in [2, 4]:
                d = {}
                for k in rng.sample(knobs, rng.randint(1, 2)):
                    if k == "NLCA":
                        d["NLCA"] = nlca_val
                    elif k == "LdsPadA":
                        d["LdsPadA"] = lspad_val
                    elif k == "LdsPadB":
                        d["LdsPadB"] = lspad_val
                    elif k == "GSU":
                        d["GSU"] = rng.choice(FORWARD_KNOB_DOMAINS["GSU"])
                    elif k == "GlobalLoadVectorWidthA":
                        d["GlobalLoadVectorWidthA"] = rng.choice(
                            FORWARD_KNOB_DOMAINS["GlobalLoadVectorWidthA"])
                if d:
                    patterns.append(d)

        # Pattern 2: WGM change + GSU double
        for wgm_val in [4, 8]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 2)):
                if k == "WorkGroupMapping":
                    d["WorkGroupMapping"] = rng.choice(
                        FORWARD_KNOB_DOMAINS["WorkGroupMapping"])
                elif k == "GSU":
                    d["GSU"] = wgm_val // 32  # GSU=1,2,4 maps to wgm 32,64,128
                elif k == "StaggerU":
                    d["StaggerU"] = rng.choice(FORWARD_KNOB_DOMAINS["StaggerU"])
            if d:
                patterns.append(d)

        # Pattern 3: GLVW quadruple + StaggerU stride
        for glvw_val in [1, 2, 4]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 2)):
                if k == "GlobalLoadVectorWidthA":
                    d["GlobalLoadVectorWidthA"] = glvw_val
                elif k == "StaggerUStride":
                    d["StaggerUStride"] = rng.choice(
                        FORWARD_KNOB_DOMAINS["StaggerUStride"])
            if d:
                patterns.append(d)

        return patterns

    def _dd_mutation_pattern(self, parent_config: Dict[str, Any],
                             rng: random.Random) -> List[Dict[str, Any]]:
        """DD-family-specific mutations targeting sore losers.

        DD family suffers from register pressure and VGPR bottlenecks.
        These patterns target DepthU, GLVW, and GSU to improve occupancy.
        """
        patterns: List[Dict[str, Any]] = []
        knobs = list(FORWARD_KNOB_DOMAINS)

        # Pattern 1: DepthU increase + GLVW change
        for depthu_val in [8, 16, 32]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 2)):
                if k == "DepthU":
                    d["DepthU"] = depthu_val
                elif k == "GlobalLoadVectorWidthA":
                    d["GlobalLoadVectorWidthA"] = rng.choice(
                        FORWARD_KNOB_DOMAINS["GlobalLoadVectorWidthA"])
                elif k == "GlobalLoadVectorWidthB":
                    d["GlobalLoadVectorWidthB"] = rng.choice(
                        FORWARD_KNOB_DOMAINS["GlobalLoadVectorWidthB"])
            if d:
                patterns.append(d)

        # Pattern 2: GSU double + NLCA change
        for gsu_val in [2, 4]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 2)):
                if k == "GSU":
                    d["GSU"] = gsu_val
                elif k == "NLCA":
                    d["NLCA"] = rng.choice(FORWARD_KNOB_DOMAINS["NLCA"])
            if d:
                patterns.append(d)

        # Pattern 3: GLVW quadruple alone
        for glvw_val in [1, 2, 4]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 1)):
                if k == "GlobalLoadVectorWidthA":
                    d["GlobalLoadVectorWidthA"] = glvw_val
            if d:
                patterns.append(d)

        return patterns

    def _cc_mutation_pattern(self, parent_config: Dict[str, Any],
                             rng: random.Random) -> List[Dict[str, Any]]:
        """CC-family-specific mutations targeting sore losers.

        CC family suffers from total-elements divisibility and LDS padding.
        These patterns target LdsPad, MacroTile, and NLCA to fix the
        totalElements 768 % (NumThreads*grvw) ≠ 0 issue.
        """
        patterns: List[Dict[str, Any]] = []
        knobs = list(FORWARD_KNOB_DOMAINS)

        # Pattern 1: LdsPad combination + NLCA change
        for lspad_a_val in [1, 2, 4]:
            for lspad_b_val in [0, 1, 2]:
                for nlca_val in [1, 2, 3]:
                    d = {}
                    for k in rng.sample(knobs, rng.randint(1, 3)):
                        if k == "LdsPadA":
                            d["LdsPadA"] = lspad_a_val
                        elif k == "LdsPadB":
                            d["LdsPadB"] = lspad_b_val
                        elif k == "NLCA":
                            d["NLCA"] = nlca_val
                    if d:
                        patterns.append(d)

        # Pattern 2: MacroTile change + GlobalSplitU
        for mt_val in ["32x32x16", "64x64x16", "96x96x16"]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 2)):
                if k == "GlobalSplitU":
                    d["GlobalSplitU"] = rng.choice(
                        FORWARD_KNOB_DOMAINS["GlobalSplitU"])
            if d:
                patterns.append(d)

        # Pattern 3: NLCA triple toggle
        for nlca_val in [1, 2, 3]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 1)):
                if k == "NLCA":
                    d["NLCA"] = nlca_val
            if d:
                patterns.append(d)

        return patterns

    def _zz_mutation_pattern(self, parent_config: Dict[str, Any],
                             rng: random.Random) -> List[Dict[str, Any]]:
        """ZZ-family-specific mutations targeting sore losers.

        ZZ family (complex double) has the lowest ceilings and requires
        different VW/ThreadTile/MacroTile combinations.
        """
        patterns: List[Dict[str, Any]] = []
        knobs = list(FORWARD_KNOB_DOMAINS)

        # Pattern 1: VW change + DepthU
        for vw_val in [1, 2]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 2)):
                if k == "VectorWidth":
                    d["VectorWidth"] = vw_val
                elif k == "DepthU":
                    d["DepthU"] = rng.choice(FORWARD_KNOB_DOMAINS["DepthU"])
            if d:
                patterns.append(d)

        # Pattern 2: GlobalLoadVectorWidthA/B change
        for glvwa_val in [1, 2, 4]:
            for glvwb_val in [1, 2, 4]:
                d = {}
                for k in rng.sample(knobs, rng.randint(1, 2)):
                    if k == "GlobalLoadVectorWidthA":
                        d["GlobalLoadVectorWidthA"] = glvwa_val
                    elif k == "GlobalLoadVectorWidthB":
                        d["GlobalLoadVectorWidthB"] = glvwb_val
                if d:
                    patterns.append(d)

        # Pattern 3: StaggerU stride change
        for stride_val in [256, 512]:
            d = {}
            for k in rng.sample(knobs, rng.randint(1, 1)):
                if k == "StaggerUStride":
                    d["StaggerUStride"] = stride_val
            if d:
                patterns.append(d)

        return patterns

    def _floor_direction(self, parent_config: Dict[str, Any],
                         floor: Dict[str, Any]) -> Dict[str, Any]:
        """Knob deltas that move the parent toward the floor winner.

        Only structural knobs the floor actually carries are copied (in
        config-normalized form); anything the parent already matches is left
        alone.
        """
        norm = self._normalize_tile(floor)
        out: Dict[str, Any] = {}
        for k in TILE_KNOBS:
            if norm.get(k) is not None and norm.get(k) != parent_config.get(k):
                out[k] = norm[k]
        return out

    # -- synthesis --------------------------------------------------------

    def _normalize_parent_config(self, parent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize tile knobs in parent_config from DB format to config format.

        The kernel_db stores tile knobs as lists (e.g. MacroTile=[64, 64]),
        but candidate configs expect strings (e.g. MacroTile="64x64"). This
        method converts the tile format so that downstream validate_config works.
        """
        out = dict(parent_config)
        # Normalize MacroTile
        mt = self._parse_dims(out.get("MacroTile"))
        if mt and len(mt) >= 2:
            du = out.get("DepthU")
            du_str = ""
            if du is not None:
                try:
                    du_str = f"x{int(du)}"
                except (TypeError, ValueError):
                    pass
            out["MacroTile"] = f"{mt[0]}x{mt[1]}{du_str}"
        # Normalize ThreadTile
        tt = self._parse_dims(out.get("ThreadTile"))
        if tt and len(tt) >= 2:
            out["ThreadTile"] = f"{tt[0]}x{tt[1]}"
        # Normalize WorkGroup
        wg = self._parse_dims(out.get("WorkGroup"))
        if wg and len(wg) >= 2:
            out["WorkGroup"] = "x".join(str(x) for x in wg[:3])
        # Ensure other knobs are int where expected
        for k in ("VectorWidth", "GlobalSplitU", "DepthU",
                  "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
                  "WorkGroupMapping"):
            v = out.get(k)
            if v is not None:
                try:
                    out[k] = int(v)
                except (TypeError, ValueError):
                    pass
        return out
