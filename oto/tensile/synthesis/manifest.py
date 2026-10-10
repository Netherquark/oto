"""Coverage-guided constrained synthesis (Option H Phase 4, `Hplan.6`).

Phase 2 established that a candidate can be *legal by construction* -- knob
groups are substituted whole from shipped vectors, so the reject set is never
proposed. This module adds the three things legal sampling alone does not give:

1. **Direction.** `legality.sample_legal` samples groups uniformly at random. A
   cell that has already produced a wide-spread config at one group learns
   nothing, because the next draw re-rolls the same group with the same
   probability. `choose_groups` conditions the draw on the cell's coverage state.
2. **Grading.** A mutant emitted with `shapes=[shape]` is born ungradable
   against a multi-shape floor (`Hplan.1` item 5): the floor measured five shapes
   per config and the mutant measured one, so no ratio is comparable.
   `family_shape_sweep` emits the family's shipped sweep instead.
3. **The tile product constraint.** `WorkGroup * ThreadTile == MacroTile` is a
   hard Tensile requirement. `reconcile_tile` derives the missing half rather
   than hoping a donor supplied a consistent pair.

Deliberately *not* here: any second CSV reader, fingerprint function, or knob
parser. Every value comes from the canonical owners (`legality`, `tensile_library`,
`analytics`, `registry`) per `implementation_plan.md` `Hplan.2`.
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from oto.tensile import legality
from oto.metrics.coverage import STATE_REPLICATE, STATE_RETIRED, decide_state

#: Knob groups, in a fixed order so a seeded run is reproducible. Sorted by
#: name rather than declared by importance: the draw is uniform over the groups
#: `choose_groups` did not exclude, and an order that encoded a preference would
#: silently bias every uniform draw taken from it.
ALL_GROUPS: Tuple[str, ...] = tuple(sorted(legality.KNOB_GROUPS))

#: Knobs the caller owns and the sampler must never emit (`Architecture`,
#: `DataType`, `ProblemType`, `ScheduleName`, `FamilyLabel`). Re-exported from
#: `legality` so there is one definition, not a second copy to drift.
TEMPLATE_KEYS = legality.TEMPLATE_KEYS

#: A sweep shorter than this is not a sweep. One shape is the defect Hplan.1
#: item 5 describes, so a "multi-shape" candidate of length 1 would reintroduce
#: it while satisfying the word.
MIN_SWEEP_SHAPES = 2


# ---------------------------------------------------------------- sweeps

def family_shape_sweeps(
        phases: Sequence[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """The shape sweep each family is benchmarked over, read from the deck.

    The curated deck is the authority on what a *graded* config looks like: every
    family phase there carries several shapes, and that sweep is what the floor
    was measured over. A mutant measured on one shape has no comparable ratio,
    so it cannot be graded at all -- it is not a weaker candidate, it is an
    unmeasurable one.

    Families are keyed on `config.FamilyLabel`, which is where the deck puts it.
    The sweep is the *union* across a family's phases, order-preserving and
    deduplicated: a family whose deck entries disagree about their shapes is
    being measured inconsistently, and silently picking one of the two would
    paper over that.
    """
    sweeps: Dict[str, List[str]] = {}
    seen: Dict[str, Set[str]] = {}
    for phase in phases or ():
        config = phase.get("config") or {}
        family = str(config.get("FamilyLabel") or "").upper()
        if not family:
            continue
        bucket = sweeps.setdefault(family, [])
        marks = seen.setdefault(family, set())
        for shape in (phase.get("shapes") or ()):
            text = shape if isinstance(shape, str) else "x".join(
                str(int(v)) for v in shape)
            if text and text not in marks:
                marks.add(text)
                bucket.append(text)
    return sweeps


def sweep_for_family(
        family: str,
        sweeps: Dict[str, List[str]],
        fallback: Optional[Sequence[str]] = None,
) -> List[str]:
    """The family's sweep, or `fallback` when the deck has none.

    Falls back rather than failing, and never invents shapes: an empty sweep
    means the candidate stays single-shape and *says so* (the caller records
    `shapes=[shape]`), which is honest. Synthesising a shape list here would
    make a mutant look graded when it was measured on one shape.
    """
    bucket = sweeps.get(str(family).upper()) or []
    if len(bucket) >= MIN_SWEEP_SHAPES:
        return list(bucket)
    if fallback:
        return list(fallback)
    return list(bucket)


# ---------------------------------------------------------------- tile

def reconcile_tile(config: Dict[str, Any]) -> Dict[str, Any]:
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


def _as_int_triple(value: Any) -> Optional[List[Optional[int]]]:
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


def tile_product_holds(config: Dict[str, Any]) -> bool:
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


# ------------------------------------------------------- coverage guidance

def choose_groups(
        cell: Optional[Dict[str, Any]],
        groups: int,
        rng: random.Random,
        band_pct: Optional[float] = None,
) -> List[str]:
    """Pick which knob groups to substitute, given the cell's coverage state.

    Coverage guidance, concretely: a group already observed to produce a
    spread beyond the acceptance band in this cell is **excluded**. Re-drawing it
    is how a run spends its whole budget re-measuring noise it has already shown
    is noise -- and because coverage state is derived from the ledger, this gets
    better as the run proceeds rather than resetting each iteration.

    Two deliberate non-behaviours:

    * A `retired` cell is not excluded here. Retirement is a reporting state
      that the *caller* acts on; a sampler that silently returned nothing for a
      retired cell would make "we stopped searching" and "the sampler failed"
      indistinguishable in the emission stats.
    * A `replicate` cell does not force a re-draw of the offending group. It
      excludes it. Re-drawing the same value to "confirm" the spread is what
      `decide_state` already reported; the useful next step is a different knob,
      or the same config under the replication protocol.
    """
    pool = list(ALL_GROUPS)
    unstable = _unstable_groups(cell, band_pct)
    if unstable:
        remaining = [g for g in pool if g not in unstable]
        # If exclusion would empty the pool, the cell is unstable everywhere and
        # any draw is as good as another; keeping the full pool beats returning
        # nothing and letting the caller report the cell as unexplored.
        if remaining:
            pool = remaining
    take = max(1, min(groups, len(pool)))
    return rng.sample(pool, take)


def _unstable_groups(cell: Optional[Dict[str, Any]],
                     band_pct: Optional[float]) -> Set[str]:
    """Groups whose value co-occurred with a spread beyond the band.

    Attribute attribution is per-config, not per-group: a spread is a property
    of the whole config, so the *drawn* groups are the candidates held
    responsible. When no band was measured, nothing is excluded -- guessing a
    threshold is how a sampler starts avoiding knobs for no reason.
    """
    if not cell or band_pct is None:
        return set()
    limit = float(band_pct) / 100.0
    out: Set[str] = set()
    for entry in cell.get("per_fp", ()):
        if entry.get("spread_ratio", 0.0) <= limit:
            continue
        for group in (entry.get("groups") or ()):
            if group in ALL_GROUPS:
                out.add(group)
    return out


def annotate_drawn_groups(knobs: Dict[str, Any],
                          drawn: Sequence[str]) -> Dict[str, Any]:
    """Record which groups a draw actually changed, for coverage attribution.

    Returned as a sidecar key rather than written into the candidate: a key the
    sampler invented is not a Tensile parameter, and emitting it would abort
    parameter filling exactly as `grvw` once did.
    """
    touched = tuple(g for g in drawn
                    if any(k in knobs for k in legality.KNOB_GROUPS.get(g, ())))
    return {"knobs": knobs, "groups": touched}


# ------------------------------------------------------------- synthesis

def synthesize_cell(
        base_dir,
        family: str,
        base_config: Optional[Dict[str, Any]] = None,
        cell: Optional[Dict[str, Any]] = None,
        groups: int = 2,
        draws: int = 8,
        seed: Optional[str] = None,
        band_pct: Optional[float] = None,
        shape: Optional[str] = None,
        sweeps: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Draw coverage-guided, tile-consistent candidates for one cell.

    Returns a summary dict rather than a bare list, because the caller has to
    make two decisions the sampler cannot make for it: whether the cell was
    retired (and so should be skipped), and which shapes the candidate will be
    benchmarked over. Both are reported here instead of being inferred.

    `fallback_lattice` is the escape hatch `Hplan.6` step 1 requires: when the
    manifest has no support for a family the sampler returns None, and the caller
    falls back to the ≤2-knob lattice. That is a *degradation* in search quality
    and is reported as such (`source: "lattice"`), never silently.
    """
    sweep = sweep_for_family(family, sweeps or {},
                             fallback=[shape] if shape else None)
    graded = len(sweep) >= MIN_SWEEP_SHAPES

    out: List[Dict[str, Any]] = []
    dropped: Dict[str, int] = {}
    rng = random.Random(seed if seed is not None else 0)
    state = decide_state(cell, band_pct=band_pct) if cell else None

    for i in range(max(0, draws)):
        drawn = choose_groups(cell, groups, rng, band_pct=band_pct)
        config, reason = _draw_with_groups(
            base_dir, family, rng, base_config, drawn)
        if config is None:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        config = reconcile_tile(config)
        knobs = {k: v for k, v in config.items() if k not in TEMPLATE_KEYS}
        sidecar = annotate_drawn_groups(knobs, drawn)
        out.append({"knobs": sidecar["knobs"], "groups": sidecar["groups"]})

    return {
        "family": family,
        "state": state,
        "candidates": out,
        "shapes": sweep,
        "graded": graded,
        "source": "manifest_sampler",
        "dropped": dropped,
    }


def _draw_with_groups(
        base_dir,
        family: str,
        rng: random.Random,
        base_config: Optional[Dict[str, Any]],
        groups: Sequence[str],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """One draw with a *specific* set of groups, hard-walled before return.

    Wraps `legality`'s own machinery rather than re-implementing substitution, so
    a change to what counts as a hard wall lands here too. `sample_legal` picks
    its own groups, which is exactly what coverage guidance needs to override.
    """
    support = legality.shipped_support(base_dir, family)
    if not support:
        return None, f"no shipped support for {family}"
    config = dict(legality._nearest_support(support, base_config, rng)["config"])
    for group in groups:
        donor = rng.choice(support)
        config = legality._apply_group(config, donor, group)
    ok, reason = legality.cooccurrence_check(base_dir, family, config)
    if not ok:
        return None, f"not manifest-coherent: {reason}"
    config.setdefault("Architecture", "gfx900")
    config.setdefault("ProblemType", "Contraction")
    config.setdefault("DataType", legality.FAMILY_DTYPE_CHAR[family])

    ok, reason = legality.check_hard_walls(config)
    if not ok:
        return None, reason
    ok, reason = legality.mt_has_shipped_schedule(config, family, base_dir)
    if not ok:
        return None, reason
    return config, ""


def synthesize_or_lattice(
        synthesize_fn,
        lattice_fn,
        family: str,
        **kwargs,
) -> Dict[str, Any]:
    """Run the constrained sampler, fall back to the lattice when it yields none.

    The fallback is what makes `Hplan.6` step 1's "degrades rather than fails"
    true. It is reported in `source` so a run that spent an iteration on the
    lattice is visible afterwards rather than being counted as prior-guided work.
    """
    result = synthesize_fn(family=family, **kwargs)
    if result.get("candidates"):
        return result
    lattice = lattice_fn(family, **{
        k: v for k, v in kwargs.items()
        if k in ("base_config", "shape", "groups")})
    if not lattice:
        return {**result, "source": "unavailable",
                "fallback_reason": "no sampler or lattice candidate"}
    return {
        **result,
        "candidates": [{"knobs": knobs, "groups": None} for knobs in lattice],
        "source": "lattice",
        "fallback_reason": result.get("dropped") or "sampler yielded none",
    }