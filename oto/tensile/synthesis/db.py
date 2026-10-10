#!/usr/bin/env python3
"""db_mutator.py — DB-hooked mutator (Option H overhaul, 2026-10-09).

The manifest sampler (`legality.sample_legal`) can only combine gfx900-shipped
knob values across the tile/split groups. It cannot touch the forward knobs
(LdsPadA/B, PGR, PLR, NLCA, WGM, the StaggerU trio, GLVW) and it cannot see
what actually WON on gfx90c. Measured consequences (proposal.md H.1 + the
live registry, 506 proposals over 10 iterations):

  * the arm decays 155 -> 20 mutants/iteration (novelty exhausted);
  * by iteration 9 it emits 21 mutants on 3 families (HH_HPA/HS_HPA/SS) and
    ZERO on the CC/ZZ wall families the campaign exists to fix;
  * no mutant ever carries a forward knob — the exact axes §8.6/§14.5
    identified as the untried levers;
  * 31% of mutants are wasted (legal_rejected + legal_slow).

This module hooks the mutator to the measured `kernel_db.json` so every
iteration synthesises NOVEL mutations:

  * WIDE      — new (MacroTile, ThreadTile, VW, GSU, DepthU, GLVW, WG) combos.
                Tile donors are read from the DB's per-family measured winners
                (what actually won on gfx90c, not just the gfx900 manifest) and
                from the floor winner, then re-combined with forward knobs.
  * NARROW    — single-knob deltas on the forward knobs the manifest sampler
                cannot reach. This is the large, mostly-unmeasured space that
                guarantees novelty across many iterations.
  * DIRECTION — toward the floor winner's knobs when the floor beats native in
                a cell (the §14.5 steal-adapt logic, generalised to every cell).

Every mutant is gated (`validate_config` + `ldspad_defasible`) and novelty-
checked (ledger + already-decided set) before emission, so the loop cannot
re-emit a config it has already measured. Novelty is guaranteed by
construction across the forward-knob space — which is what lets the arm run
for many iterations instead of converging to a trickle.

The class wraps the existing `mutator.Mutator` (composition) for the ledger,
novelty, outcome and overlay behaviour; it only owns synthesis.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from oto.device.peaks import FAMILY_DTYPE_CHAR

#: Forward knobs the manifest sampler cannot reach, with their legal domains.
#: Values are the Tensile-legal value sets (Common.py) intersected with what
#: the gfx90c gates admit. This is the NARROW mutation space.
FORWARD_KNOB_DOMAINS: Dict[str, Tuple[Any, ...]] = {
    "LdsPadA": (0, 1, 2, 4),
    "LdsPadB": (0, 1, 2, 4),
    "PrefetchGlobalRead": (0, 1),
    "PrefetchLocalRead": (0, 1),
    "GlobalLoadVectorWidthA": (1, 2, 4),
    "GlobalLoadVectorWidthB": (1, 2, 4),
    "NLCA": (1, 2, 3),
    "WorkGroupMapping": (1, 4, 8),
    "StaggerU": (0, 8, 16, 32),
    "StaggerUMapping": (0, 1, 2),
    "StaggerUStride": (0, 256, 512),
    "DepthU": (4, 8, 16, 32),
    "GlobalSplitU": (1, 2, 4),
    "AssertFree0ElementMultiple": (1, 2),
}

#: Knobs that make up a "tile donor" (the wide axes the DB carries).
_TILE_KNOBS = ("MacroTile", "ThreadTile", "VectorWidth", "GlobalSplitU",
               "DepthU", "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
               "WorkGroup")

#: Default ContractionPattern per family (matches the deck/first pattern).
_DEFAULT_PATTERN = {
    "SS": "Ailk_Bjlk", "DD": "Ailk_Bjlk", "HH": "Ailk_Bjlk",
    "CC": "Ailk_Bjlk", "ZZ": "Alik_Bjlk",
    "HH_HPA": "Ailk_Bjlk", "HS_HPA": "Ailk_Bjlk",
}

#: How many tile donors / forward draws to try per cell before gating.
_DONOR_POOL = 6
_FORWARD_DRAWS = 5  # increased from 3 to cover more knob combinations


class DBMutator:
    """DB-hooked synthesis on top of the ledger-backed Mutator.

    Parameters
    ----------
    base_dir:
        Repository root; `gfx90c_results/analysis/kernel_db.json` is read
        from here (lazy, once).
    mutator:
        The existing ledger-backed Mutator — owns ledger/novelty/emit/overlay.
    kernel_db_path:
        Override for the analysis DB location (tests).
    """

    def __init__(self, base_dir: Path, mutator,
                 kernel_db_path: Optional[Path] = None):
        self.base_dir = Path(base_dir)
        self.mutator = mutator
        self.kernel_db_path = Path(kernel_db_path) if kernel_db_path else (
            self.base_dir / "gfx90c_results" / "analysis" / "kernel_db.json")
        self._db: Optional[Dict[str, Any]] = None
        self._by_family: Dict[str, List[Dict[str, Any]]] = {}
        self._by_family_cell: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._floor_run: Optional[str] = None
        self._sched = None

    # -- DB loading -------------------------------------------------------

    def load_db(self) -> None:
        """Parse kernel_db.json into per-family and per-(family,cell) maps.

        Only rows with a family and a numeric median participate. The floor run
        (gfx900_ref_*) is kept separate so DIRECTION mutants can aim at it.
        """
        if self._db is not None:
            return
        try:
            raw = json.loads(self.kernel_db_path.read_text())
        except Exception:
            raw = {}
        self._db = raw if isinstance(raw, dict) else {}
        by_family: Dict[str, List[Dict[str, Any]]] = {}
        by_fc: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        floor_run = None
        for run_id, rows in self._db.items():
            if not isinstance(rows, list):
                continue
            is_floor = str(run_id).startswith("gfx900_ref")
            if is_floor and floor_run is None:
                floor_run = run_id
            for r in rows:
                if not isinstance(r, dict):
                    continue
                fam = str(r.get("family") or "").upper()
                shape = str(r.get("shape") or "")
                med = r.get("gflops_median")
                if not fam or not shape or med is None:
                    continue
                try:
                    med = float(med)
                except (TypeError, ValueError):
                    continue
                entry = {**r, "_median": med, "_run": run_id, "_is_floor": is_floor}
                by_family.setdefault(fam, []).append(entry)
                by_fc.setdefault((fam, shape), []).append(entry)
        for fam in by_family:
            by_family[fam].sort(key=lambda e: -e["_median"])
        for key in by_fc:
            by_fc[key].sort(key=lambda e: -e["_median"])
        self._by_family = by_family
        self._by_family_cell = by_fc
        self._floor_run = floor_run

    # -- gating -----------------------------------------------------------

    def _scheduler(self):
        if self._sched is None:
            from oto.tensile.candidate import CandidateGenerator
            self._sched = CandidateGenerator(self.base_dir, registry=None)
        return self._sched

    def _template(self, family: str) -> Dict[str, Any]:
        return {
            "Architecture": "gfx90c",
            "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
            "FamilyLabel": family,
            "ScheduleName": "isa",
            "ProblemType": "Contraction",
            "ContractionPattern": _DEFAULT_PATTERN.get(family, "Ailk_Bjlk"),
        }

    def _gate(self, config: Dict[str, Any]) -> bool:
        """validate_config + ldspad_feasible, the two CPU-only launch gates."""
        from oto.tensile.gates.occupancy import ldspad_defasible
        ok, _why = self._scheduler().validate_config(config)
        if not ok:
            return False
        ok, _why = ldspad_defasible(config)
        return ok

    # -- donors -----------------------------------------------------------

    def _tile_donors(self, family: str, parent_config: Dict[str, Any],
                     rng: random.Random) -> List[Dict[str, Any]]:
        """Wide tile donors for the family: measured winners (DB) first, then
        the floor winner's tile, de-duplicated and excluding the parent's own
        tile so a donor is always a real move."""
        self.load_db()
        parent_tile = self._tile_key(parent_config)
        out: List[Dict[str, Any]] = []
        seen = {parent_tile}

        def _add(entry: Dict[str, Any]) -> None:
            # Normalize the DB's parsed knobs to config-format strings/ints,
            # or the gate validates a shape the writer never sees.
            knobs = self._normalize_tile(entry)
            key = self._tile_key(knobs)
            if key and key not in seen:
                seen.add(key)
                out.append(knobs)

        # Measured winners for this family, best first.
        for entry in self._by_family.get(family, [])[:_DONOR_POOL]:
            _add(entry)
        # The floor winner's tile for this cell (spoof-steal direction).
        floor = self.floor_winner(family, parent_config.get("_shape", ""))
        if floor:
            _add(floor)
        rng.shuffle(out)
        return out

    def _tile_key(self, knobs: Dict[str, Any]) -> Tuple:
        return tuple(str(knobs.get(k)) for k in _TILE_KNOBS)

    @staticmethod
    def _parse_dims(value: Any) -> Optional[List[int]]:
        """Parse a knob value that may be a list, a ``"[a, b]"`` string, or a
        ``"axb"`` string, into a list of ints. None when unparseable."""
        if isinstance(value, (list, tuple)):
            try:
                return [int(x) for x in value]
            except (TypeError, ValueError):
                return None
        if isinstance(value, str):
            s = value.strip()
            if s.startswith("["):
                s = s.strip("[]")
                try:
                    return [int(x) for x in s.split(",") if x.strip()]
                except ValueError:
                    return None
            parts = [p for p in re.split(r"[xX]", s) if p]
            try:
                return [int(p) for p in parts]
            except ValueError:
                return None
        return None

    @classmethod
    def _normalize_tile(cls, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a kernel_db row's parsed knobs to config-format strings.

        The analysis DB stores the structural knobs in Tensile's parsed form —
        MacroTile ``"[128, 128]"`` (a string-encoded list), ThreadTile
        ``"[4, 4]"``, VectorWidth ``'2'`` — while a candidate config carries
        them as ``"64x64x8"`` / ``"4x4"`` strings and ints. Without this
        conversion a donor tile would be validated (and fingerprinted) in a
        shape the writer never sees.
        """
        out: Dict[str, Any] = {}
        mt = cls._parse_dims(entry.get("MacroTile"))
        du = entry.get("DepthU")
        if mt and len(mt) >= 2:
            du_str = ""
            if du is not None:
                try:
                    du_str = f"x{int(du)}"
                except (TypeError, ValueError):
                    pass
            out["MacroTile"] = f"{mt[0]}x{mt[1]}{du_str}"
        tt = cls._parse_dims(entry.get("ThreadTile"))
        if tt and len(tt) >= 2:
            out["ThreadTile"] = f"{tt[0]}x{tt[1]}"
        wg = cls._parse_dims(entry.get("WorkGroup"))
        if wg and len(wg) >= 2:
            out["WorkGroup"] = "x".join(str(x) for x in wg[:3])
        for k in ("VectorWidth", "GlobalSplitU", "DepthU",
                  "GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
                  "WorkGroupMapping"):
            v = entry.get(k)
            if v is None:
                continue
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = v
        return out

    def floor_winner(self, family: str, shape: str) -> Optional[Dict[str, Any]]:
        """The gfx900 floor's winning row for (family, shape), or None."""
        self.load_db()
        if not shape:
            return None
        rows = self._by_family_cell.get((family, shape), [])
        floor_rows = [r for r in rows if r.get("_is_floor")]
        if not floor_rows:
            return None
        return floor_rows[0]

    # -- forward-knob draws ---------------------------------------------

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

    # -- direction -------------------------------------------------------

    # -- direction -------------------------------------------------------

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

    def synthesize_mutants(self, family: str, parent_config: Dict[str, Any],
                          shape: str, rng: random.Random,
                          n: int = 8) -> List[Dict[str, Any]]:
        """Return up to ``n`` novel mutant knob dicts for one cell.

        Wide (DB tile donors x forward draws), narrow (single-knob deltas on
        the parent) and direction (toward the floor winner) mutants are
        generated, gated, and novelty-checked. Returns knob dicts only — the
        caller owns the Architecture/DataType/FamilyLabel template.
        """
        self.load_db()
        parent_config = self._normalize_parent_config(parent_config)
        parent_config = {**parent_config, "_shape": shape}
        cands: List[Tuple[Dict[str, Any], float]] = []

        # NARROW — single-knob deltas on the parent (highest value: these are
        # the axes the manifest sampler cannot touch).
        for knob, values in FORWARD_KNOB_DOMAINS.items():
            cur = parent_config.get(knob)
            for v in values:
                if v == cur:
                    continue
                cands.append(({**parent_config, knob: v}, 1.0))

        # WIDE — donor tiles re-combined with forward draws.
        for donor in self._tile_donors(family, parent_config, rng):
            for draw in self._forward_draws(rng):
                cands.append(({**parent_config, **donor, **draw}, 0.6))

        # DIRECTION — toward the floor winner (spoof-steal).
        floor = self.floor_winner(family, shape)
        if floor:
            direction = self._floor_direction(parent_config, floor)
            if direction:
                cands.append(({**parent_config, **direction}, 0.9))

        out: List[Dict[str, Any]] = []
        seen = set()
        # Highest priority first; stable within a priority by candidate order.
        for knobs, _prio in sorted(cands, key=lambda x: -x[1]):
            cfg = {**self._template(family), **knobs}
            cfg.pop("_shape", None)
            if not self._gate(cfg):
                continue
            from oto.ledger.registry import fingerprint_config
            fp = fingerprint_config(cfg)
            if fp in seen:
                continue
            if not self.mutator.is_novel(fp):
                continue
            seen.add(fp)
            out.append({k: v for k, v in knobs.items() if k != "_shape"})
            if len(out) >= n:
                break
        return out

    # -- convenience for the agent ---------------------------------------

    def has_db(self) -> bool:
        """True iff the analysis DB loaded with at least one family."""
        self.load_db()
        return bool(self._by_family)
