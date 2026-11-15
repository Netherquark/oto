#!/usr/bin/env python3
"""The per-family mutation patterns for the DB-hooked mutator.

Owns: ``DbPatternsMixin`` -- the family-generic mutant generator:
``_forward_draws`` (small random combinations of forward knobs from the
NARROW/WIDE surface), ``_floor_direction`` (the deltas that move a parent
toward the floor winner) and ``_normalize_parent_config``.

The per-family ``_<family>_mutation_pattern`` passes were removed as dead code:
they were never wired into ``synthesize_mutants`` and read a domain shape that
does not exist. ``_joint_domain`` remains the single legality-narrowing seam.

Both draws go through ``_joint_domain``, never through ``forward_domain``
directly: a forward knob's *legal* values depend on the rest of the tile, so
treating the domains as independent axes generates configs the launch boundary
then refuses (``docs/gfx90c/potential_configs.md`` §R23).
Does NOT own: the domains they draw from (`oto.tensile.synthesis.donor_knobs`) or the
mutant synthesis that gates them (`oto.tensile.synthesis.donor_mutator`).
Public API: DbPatternsMixin.
"""

from __future__ import annotations

import contextlib
import random
from typing import Any

from oto.tensile.synthesis.donor_knobs import (
    _FORWARD_DRAWS,
    FORWARD_KNOB_DOMAINS,
    forward_domain,
)
from oto.tensile.synthesis.tile_space import TILE_KNOBS


class DbPatternsMixin:
    """Family-generic mutant patterns, mixed into `oto.tensile.synthesis.donor_mutator.DBMutator`."""

    def _joint_domain(self, family: str | None, knob: str,
                      parent_config: dict[str, Any]) -> tuple[Any, ...]:
        """``forward_domain`` (family, knob) narrowed to the values this tile
        can actually carry.

        The domains in ``db_knobs`` are independent by construction. Tensile's
        legal set for a forward knob is not:

          * ``GlobalLoadVectorWidthA/B`` must be the tile's ``VectorWidth`` or 1
            (SolutionStructs:4583-4596);
          * ``NLCA`` must divide the tile's load count, its vector count and its
            perpendicular extent (SolutionStructs:2058);
          * ``DepthU`` must fit the LDS budget at this MacroTile/ThreadTile;
          * ``StaggerU`` / ``StaggerUMapping`` / ``StaggerUStride`` move as one
            trio (SolutionStructs:3326-3342).

        A draw that ignores that passes every *individual* domain check and is
        then refused at the launch boundary, burning one of ``_FORWARD_DRAWS``.

        Why probe rather than restate: the measured refusal ledger
        (``docs/gfx90c/potential_configs.md`` §R23) contains no per-knob rejections at all --
        every one is one of the couplings above, and each already exists as a
        line in a gate. Probing ``self._gate`` -- the same two CPU-only gates the
        launch boundary runs -- keeps one home for them instead of a second,
        drifting copy here.

        ``parent_config`` must itself be gate-legal (a measured donor, deck
        winner or floor tile). If it is not, every probe fails and the knob is
        skipped rather than offering a value that cannot run.
        """
        base = {**self._template(family), **parent_config}
        return tuple(value for value in forward_domain(family, knob)
                     if self._gate({**base, knob: value}))

    def _forward_draws(self, rng: random.Random,
                       parent_config: dict[str, Any],
                       family: str | None = None) -> list[dict[str, Any]]:
        """Small random combos of forward knobs (the NARROW/WIDE surface).

        Each draw changes 1-3 forward knobs, each to a value the gates admit
        *beside the ones this draw has already picked* -- see ``_joint_domain``.
        The order matters: moving ``DepthU`` changes which ``StaggerUStride``
        values are legal, so a later knob in the same draw must see the earlier
        one instead of a fresh copy of the parent.

        Diagonal combinations (2-3 knobs simultaneously) are preferred over
        single-knob changes to escape local optima faster.
        """
        knobs = list(FORWARD_KNOB_DOMAINS)
        out: list[dict[str, Any]] = []
        for _ in range(_FORWARD_DRAWS):
            n_knobs = rng.randint(1, 3)  # 1-3 knobs per draw
            draw: dict[str, Any] = {}
            for k in rng.sample(knobs, n_knobs):
                domain = self._joint_domain(
                    family, k, {**parent_config, **draw})
                if domain:
                    draw[k] = rng.choice(domain)
            if draw:
                out.append(draw)
        return out

    def _floor_direction(self, parent_config: dict[str, Any],
                         floor: dict[str, Any]) -> dict[str, Any]:
        """Knob deltas that move the parent toward the floor winner.

        Only structural knobs the floor actually carries are copied (in
        config-normalized form); anything the parent already matches is left
        alone.
        """
        norm = self._normalize_tile(floor)
        out: dict[str, Any] = {}
        for k in TILE_KNOBS:
            if norm.get(k) is not None and norm.get(k) != parent_config.get(k):
                out[k] = norm[k]
        return out

    # -- synthesis --------------------------------------------------------

    def _normalize_parent_config(self, parent_config: dict[str, Any]) -> dict[str, Any]:
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
                with contextlib.suppress(TypeError, ValueError):
                    du_str = f"x{int(du)}"
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
                with contextlib.suppress(TypeError, ValueError):
                    out[k] = int(v)
        return out
