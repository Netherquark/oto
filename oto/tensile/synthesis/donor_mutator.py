#!/usr/bin/env python3
"""DB-hooked candidate synthesis: wide + narrow + direction mutants.

Owns: ``DBMutator`` -- donors read out of the analysis kernel_db.json
(``load_db``, ``_tile_donors``, ``_template``), the three filters a mutant must
survive (``_scheduler``/``ldspad_feasible`` CPU gate + novelty) and the per-family
mutation patterns (``_ss_``, ``_dd_``, ``_cc_``, ``_zz_``) plus the
floor-direction walk that moves a parent toward the shipped winner.
Does NOT own: the forward-knob domains it draws from
(`oto.tensile.synthesis.donor_knobs`), the manifest-driven synthesis
(`oto.tensile.synthesis.pipeline_manifest`), or the ledger that records what it emits
(`oto.ledger.mutator`).

Mutation strategies (moved here from docs/potential_configs.md). Every sore loser
gets novel, valid mutants from three strategy families, with
`bypass_identical_skip=True` so each mutant is measured regardless of prior
history -- novelty is guaranteed by the ledger, not by pass/fail history:
  * NARROW -- single-knob deltas on the forward knobs the manifest sampler
    cannot reach. Each draw changes 1-3 knobs.
  * WIDE -- DB tile donors (per-family measured winners and the floor winner)
    re-combined with forward draws: tile and WorkGroup from the donor, the
    forward knobs from the draw.
  * DIRECTION -- the parent's knobs moved toward the floor winner's knobs
    (structural knobs only; knobs the parent already matches are left alone).
Budget: 5 forward draws per iteration; each mutant is gated through
`validate_config` + `ldspad_feasible` before ledger emission. The campaign's
convergence test lives in `oto.ledger.convergence_agent`.

The value sets are NOT restated here. A knob's per-family draw set is
``db_knobs.forward_domain``; the *jointly* legal subset of it -- GLVW against
VectorWidth, NLCA against the load count, DepthU against the LDS budget, the
StaggerU trio against each other -- is
``db_patterns.DbPatternsMixin._joint_domain``, which probes the gates. The
enumerated lists this docstring used to carry had drifted from the table and
named values the gates refuse (docs/gfx90c_tuning_guide.md §13 §R23).

The four ``_<family>_mutation_pattern`` methods are not called by
``synthesize_mutants``: the family-specific passes were never wired in, so SS/
DD/CC/ZZ get the generic narrow/wide/direction surface. They are kept -- and
kept gate-legal -- pending a decision to wire them (docs/gfx90c_tuning_guide.md §13 §R23).

Public API: DBMutator, FORWARD_KNOB_DOMAINS (re-exported).
"""

from __future__ import annotations

import contextlib
import json
import random
import re
from pathlib import Path
from typing import Any

from oto.device import loader as _loader
from oto.runners.result_paths import results_dir as _results_dir
from oto.tensile.synthesis.donor_knobs import (
    _DEFAULT_PATTERN,
    _DONOR_POOL,
    FORWARD_KNOB_DOMAINS,
)
from oto.tensile.synthesis.donor_patterns import DbPatternsMixin
from oto.tensile.synthesis.tile_space import TILE_KNOBS


class DBMutator(DbPatternsMixin):

    """DB-hooked synthesis on top of the ledger-backed Mutator.

    Parameters
    ----------
    base_dir:
        Repository root; `<codename>_results/analysis/kernel_db.json` is read
        from here (lazy, once).
    mutator:
        The existing ledger-backed Mutator — owns ledger/novelty/emit/overlay.
    kernel_db_path:
        Override for the analysis DB location (tests).
    """

    def __init__(self, base_dir: Path, mutator,
                 kernel_db_path: Path | None = None, profile=None):
        """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
        self.base_dir = Path(base_dir)
        self.mutator = mutator
        self.kernel_db_path = Path(kernel_db_path) if kernel_db_path else (
            _results_dir(self.base_dir, _loader.resolve_profile(profile,).codename) / "analysis" / "kernel_db.json")
        self._db: dict[str, Any] | None = None
        self._by_family: dict[str, list[dict[str, Any]]] = {}
        self._by_family_cell: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._floor_run: str | None = None
        self._spoof_prefix = (getattr(_loader.resolve_profile(profile), "spoof_reference", "")
                              or "gfx900")
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
        by_family: dict[str, list[dict[str, Any]]] = {}
        by_fc: dict[tuple[str, str], list[dict[str, Any]]] = {}
        floor_run = None
        for run_id, rows in self._db.items():
            if not isinstance(rows, list):
                continue
            is_floor = str(run_id).startswith(f"{self._spoof_prefix}_ref")
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

    def _template(self, family: str, profile=None) -> dict[str, Any]:
        """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
        return {
            "Architecture": _loader.resolve_profile(profile,).codename,
            "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
            "FamilyLabel": family,
            "ScheduleName": "isa",
            "ProblemType": "Contraction",
            "ContractionPattern": _DEFAULT_PATTERN.get(family, "Ailk_Bjlk",),
        }

    def _gate(self, config: dict[str, Any]) -> bool:
        """validate_config + ldspad_feasible, the two CPU-only launch gates."""
        from oto.tensile.gates.occupancy import ldspad_feasible
        ok, _why = self._scheduler().validate_config(config)
        if not ok:
            return False
        ok, _why = ldspad_feasible(config)
        return ok

    # -- donors -----------------------------------------------------------

    def _tile_donors(self, family: str, parent_config: dict[str, Any],
                     rng: random.Random) -> list[dict[str, Any]]:
        """Wide tile donors for the family: measured winners (DB) first, then
        the floor winner's tile, de-duplicated and excluding the parent's own
        tile so a donor is always a real move."""
        self.load_db()
        parent_tile = self._tile_key(parent_config)
        out: list[dict[str, Any]] = []
        seen = {parent_tile}

        def _add(entry: dict[str, Any]) -> None:
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

    def _tile_key(self, knobs: dict[str, Any]) -> tuple:
        return tuple(str(knobs.get(k)) for k in TILE_KNOBS)

    @staticmethod
    def _parse_dims(value: Any) -> list[int] | None:
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
    def _normalize_tile(cls, entry: dict[str, Any]) -> dict[str, Any]:
        """Convert a kernel_db row's parsed knobs to config-format strings.

        The analysis DB stores the structural knobs in Tensile's parsed form —
        MacroTile ``"[128, 128]"`` (a string-encoded list), ThreadTile
        ``"[4, 4]"``, VectorWidth ``'2'`` — while a candidate config carries
        them as ``"64x64x8"`` / ``"4x4"`` strings and ints. Without this
        conversion a donor tile would be validated (and fingerprinted) in a
        shape the writer never sees.
        """
        out: dict[str, Any] = {}
        mt = cls._parse_dims(entry.get("MacroTile"))
        du = entry.get("DepthU")
        if mt and len(mt) >= 2:
            du_str = ""
            if du is not None:
                with contextlib.suppress(TypeError, ValueError):
                    du_str = f"x{int(du)}"
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

    def floor_winner(self, family: str, shape: str) -> dict[str, Any] | None:
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

    def _narrow_mutants(self, family: str, parent_config: dict[str, Any],
                        rng: random.Random, limit: int | None = None
                        ) -> list[tuple[dict[str, Any], float]]:
        """Single-knob deltas on the parent's forward knobs (priority 1.0).

        These are the axes the manifest sampler cannot touch, so they are the
        highest-value mutants. Drawn through ``_joint_domain``, not
        ``forward_domain``: the per-family overrides narrow a knob on its own,
        but Tensile's legal set is joint (GLVW against VectorWidth, NLCA against
        the tile's load count, DepthU against the LDS budget, the StaggerU trio
        against each other). Reading the flat domains here is what let the
        mutator offer GLVW=2 beside VectorWidth 4, or NLCA=3 to a tile with one
        load -- refuses the launch boundary then absorbed one draw at a time
        (docs/gfx90c_tuning_guide.md §13 §R23).

        The knobs are visited in a **seeded shuffle**, round-robin over their
        legal values, and the pass is capped at ``limit`` candidates. All three
        matter: in dict order the first few knobs eat the whole budget, so an
        axis late in the dict is never drawn at all -- when the 2026-10-21
        batch added ten knobs (pads, asserts, non-temporal, MaxOccupancy), the
        *GlobalSplitU* axis (the wave-fill lever the small cells need) went
        undrawn and the mutator spent its whole budget on pads. The shuffle
        keeps the run reproducible while spreading the budget over the axes,
        and the cap leaves room for the wide (tile-donor) pass.
        """
        per_knob: list[tuple[str, list[Any]]] = []
        knobs = list(FORWARD_KNOB_DOMAINS)
        rng.shuffle(knobs)
        for knob in knobs:
            values = [v for v in self._joint_domain(family, knob, parent_config)
                      if v != parent_config.get(knob)]
            if values:
                per_knob.append((knob, values))
        out: list[tuple[dict[str, Any], float]] = []
        depth = max((len(v) for _k, v in per_knob), default=0)
        for i in range(depth):
            for knob, values in per_knob:
                if i < len(values):
                    out.append(({**parent_config, knob: values[i]}, 1.0))
                    if limit is not None and len(out) >= limit:
                        return out
        return out

    def _wide_mutants(self, family: str, parent_config: dict[str, Any],
                      rng: random.Random
                      ) -> list[tuple[dict[str, Any], float]]:
        """Donor tiles re-combined with forward draws (priority 0.6).

        The draws are validated against the *donor* tile -- the tile they land
        on -- rather than the parent's, so a donor that moves DepthU also moves
        which StaggerUStride values are legal.
        """
        out: list[tuple[dict[str, Any], float]] = []
        for donor in self._tile_donors(family, parent_config, rng):
            base = {**parent_config, **donor}
            out.extend(({**parent_config, **donor, **draw}, 0.6)
                       for draw in self._forward_draws(rng, base, family))
        return out

    def synthesize_mutants(self, family: str, parent_config: dict[str, Any],
                          shape: str, rng: random.Random,
                          n: int = 8) -> list[dict[str, Any]]:
        """Return up to ``n`` novel mutant knob dicts for one cell.

        Wide (DB tile donors x forward draws), narrow (single-knob deltas on
        the parent) and direction (toward the floor winner) mutants are
        generated, gated, and novelty-checked. Returns knob dicts only — the
        caller owns the Architecture/DataType/FamilyLabel template.
        """
        self.load_db()
        parent_config = self._normalize_parent_config(parent_config)
        parent_config = {**parent_config, "_shape": shape}

        # Priority order: narrow (1.0) > direction (0.9) > wide (0.6). The sort
        # below is stable, so the order within a priority is the order below.
        cands: list[tuple[dict[str, Any], float]] = []
        # The narrow pass may take at most half the budget: the wide pass
        # (DB tile donors) is the only one that moves the *geometry*, and a
        # mutator that never changes the tile cannot leave a local minimum.
        # The rest of the narrow candidates are kept as a TOP-UP (priority
        # 0.55, below the wide pass) for the families whose DB has no donor
        # tile -- otherwise the HPA columns would return fewer mutants than
        # the budget asks for.
        narrow = self._narrow_mutants(family, parent_config, rng)
        primary = max(1, n // 2)
        cands.extend((knobs, 1.0) for knobs, _p in narrow[:primary])
        cands.extend((knobs, 0.55) for knobs, _p in narrow[primary:])

        floor = self.floor_winner(family, shape)
        if floor:
            direction = self._floor_direction(parent_config, floor)
            if direction:
                cands.append(({**parent_config, **direction}, 0.9))

        cands.extend(self._wide_mutants(family, parent_config, rng))

        out: list[dict[str, Any]] = []
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
