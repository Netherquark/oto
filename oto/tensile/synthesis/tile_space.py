#!/usr/bin/env python3
"""The one home for the tile and knob-group vocabulary the synthesisers share.

Owns: the tile axis names (``TILE_KNOBS``), the knob-group vocabulary
(``ALL_GROUPS`` / ``TEMPLATE_KEYS``, derived once from oto.tensile.legality), and
the tile-reconciliation rules (``_as_int_triple``, ``reconcile_tile``,
``tile_product_holds``) that make ``WorkGroup * ThreadTile == MacroTile`` hold by
construction.
Does NOT own: the legal prior itself (oto.tensile.legality), the coverage-guided
sampler that draws whole groups (oto.tensile.synthesis.manifest), or the
DB-hooked donor/forward-knob mutator (oto.tensile.synthesis.donor_mutator, which imports
``TILE_KNOBS`` from here so the two never disagree on what a tile is).
Public API: TILE_KNOBS, ALL_GROUPS, TEMPLATE_KEYS, reconcile_tile,
tile_product_holds.
"""

from __future__ import annotations

from typing import Any

from oto.tensile import legality

#: The tile axes a donor tile is keyed on. Values are the config-format keys a
#: candidate carries, so the DB-hooked mutator and the manifest sampler agree on
#: what makes two tiles "the same tile".
TILE_KNOBS: tuple[str, ...] = ("MacroTile", "ThreadTile", "VectorWidth",
                               "GlobalSplitU", "DepthU", "GlobalLoadVectorWidthA",
                               "GlobalLoadVectorWidthB", "WorkGroup")

#: Knob groups, in a fixed order so a seeded run is reproducible. Sorted by
#: name rather than declared by importance: the draw is uniform over the groups
#: ``choose_groups`` did not exclude, and an order that encoded a preference
#: would silently bias every uniform draw taken from it.
ALL_GROUPS: tuple[str, ...] = tuple(sorted(legality.KNOB_GROUPS))

#: Knobs the caller owns and the sampler must never emit (``Architecture``,
#: ``DataType``, ``ProblemType``, ``ScheduleName``, ``FamilyLabel``). Re-exported
#: from ``legality`` so there is one definition, not a second copy to drift.
TEMPLATE_KEYS = legality.TEMPLATE_KEYS


# ---------------------------------------------------------------- tile

def reconcile_tile(config: dict[str, Any]) -> dict[str, Any]:
    """Make `WorkGroup * ThreadTile == MacroTile` hold by construction.

    Tensile rejects a config unless, per M/N dimension, the product equals the
    MacroTile and the workgroup size is a multiple of the wavefront size. Whole
    group substitution from a shipped donor already satisfies this, so this
    function is a *check* in the normal path rather than a repair: it returns
    the config unchanged when the product holds, and only solves for a missing
    half otherwise.

    The MacroTile is trusted over the ThreadTile when the two disagree, matching
    `tensile_library._reconcile_knobs`: a MacroTile with no shipped schedule is
    rejected downstream by `mt_has_shipped_schedule`, whereas a ThreadTile that
    does not tile it is not independently meaningful.
    """
    out = dict(config)
    macro = out.get("MacroTile")
    if not isinstance(macro, str) or "x" not in macro:
        return out

    dims = macro.split("x")
    # A missing half is the case this function exists to solve, so an absent or
    # unusable value becomes "unset" rather than a reason to give up.
    wg = _as_int_triple(out.get("WorkGroup")) or [None, None, None]
    tt = _as_int_triple(out.get("ThreadTile")) or [None, None, None]
    if not any(wg) and not any(tt):
        return out

    mt_m = int(dims[0]) if dims[0].isdigit() else None
    mt_n = int(dims[1]) if len(dims) > 1 and dims[1].isdigit() else None

    for i, mt in ((0, mt_m), (1, mt_n)):
        if not mt:
            continue
        w, t = wg[i], tt[i]
        if w and t and w * t == mt:
            continue
        if w and not t and mt % w == 0:
            tt[i] = mt // w
        elif t and not w and mt % t == 0:
            wg[i] = mt // t
        elif w and t and w * t != mt:
            # Neither is missing: they disagree. Trust the MacroTile and re-solve.
            if mt % w == 0:
                tt[i] = mt // w
            elif mt % t == 0:
                wg[i] = mt // t

    # An unsolved dimension renders as 1, never `None`: a literal "None" in the
    # manifest fails parameter parsing at Tensile load time, which is a far worse
    # outcome than the default it stands in for.
    out["WorkGroup"] = f"{wg[0] or 1}x{wg[1] or 1}x{wg[2] or 1}"
    out["ThreadTile"] = f"{tt[0] or 1}x{tt[1] or 1}"
    return out

def _as_int_triple(value: Any) -> list[int | None] | None:
    """Parse `WxHxD` / `WxH` into `[m, n, k]`, or None if unusable."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = list(value) + [1] * (3 - len(value))
    elif isinstance(value, str) and "x" in value:
        try:
            parts = [int(p) for p in value.lower().split("x")]
        except ValueError:
            return None
        parts += [1] * (3 - len(parts))
    else:
        return None
    parts = parts[:3]
    return [p if isinstance(p, int) and p > 0 else None for p in parts]

def tile_product_holds(config: dict[str, Any]) -> bool:
    """True iff `WorkGroup * ThreadTile == MacroTile` per M/N dimension."""
    macro = config.get("MacroTile")
    if not isinstance(macro, str) or "x" not in macro:
        return True          # nothing to check; not a tile violation
    dims = macro.split("x")
    wg = _as_int_triple(config.get("WorkGroup"))
    tt = _as_int_triple(config.get("ThreadTile"))
    if not wg or not tt:
        return False
    for i in (0, 1):
        if i >= len(dims) or not dims[i].isdigit():
            continue
        w, t, mt = wg[i], tt[i], int(dims[i])
        if not w or not t or w * t != mt:
            return False
    return True
