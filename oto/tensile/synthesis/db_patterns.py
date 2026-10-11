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
                                            _FORWARD_DRAWS, _TILE_KNOBS,
                                            FORWARD_KNOB_DOMAINS)


class DbPatternsMixin:
    """Per-family mutation patterns, mixed into DBMutator."""


    def _forward_draws(self, rng: random.Random) -> List[Dict[str, Any]]:
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
                draw[k] = rng.choice(FORWARD_KNOB_DOMAINS[k])
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

    def _floor_direction(self, parent_config: Dict[str, Any],
                         floor: Dict[str, Any]) -> Dict[str, Any]:
        """Knob deltas that move the parent toward the floor winner.

        Only structural knobs the floor actually carries are copied (in
        config-normalized form); anything the parent already matches is left
        alone.
        """
        norm = self._normalize_tile(floor)
        out: Dict[str, Any] = {}
        for k in _TILE_KNOBS:
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
