"""Coverage-guided candidate synthesis for one cell.

Owns: ``family_shape_sweeps`` (the sweep read from the deck -- the deck is the
authority on what a graded config looks like), ``choose_groups`` /
``_unstable_groups``, and ``synthesize_cell`` / ``synthesize_or_lattice``. The
tile/group vocabulary and the tile reconciliation it draws in
(``reconcile_tile`` / ``tile_product_holds`` / ``ALL_GROUPS`` /
``TEMPLATE_KEYS``) live in oto.tensile.synthesis.tile_space and are re-exported
here unchanged, so the public names do not move.

Does NOT own: the legality prior it draws inside (oto.tensile.legality), the
ledger that records the drawn candidate (oto.ledger.mutator), the DB-hooked
synthesis (oto.tensile.synthesis.donor_mutator), or the tile/group vocabulary itself
(oto.tensile.synthesis.tile_space).

Public API: family_shape_sweeps, sweep_for_family, reconcile_tile,
tile_product_holds, choose_groups, annotate_drawn_groups, synthesize_cell,
synthesize_or_lattice, ALL_GROUPS, TEMPLATE_KEYS, MIN_SWEEP_SHAPES.

The prior phase established that a candidate can be *legal by construction* --
knob groups are substituted whole from shipped vectors, so the reject set is
never proposed. This module adds the three things legal sampling alone does not
give:

1. **Direction.** Legal sampling draws groups uniformly at random, so a cell that
   already produced a wide-spread config at one group learns nothing.
   ``choose_groups`` conditions the draw on the cell's coverage state.
2. **Grading.** A mutant emitted with ``shapes=[shape]`` is born ungradable
   against a multi-shape floor: the floor measured the family sweep and the mutant
   measured one shape, so no ratio is comparable. ``family_shape_sweeps`` emits
   the family's shipped sweep instead.
3. **The tile product constraint.** ``WorkGroup * ThreadTile == MacroTile`` is a
   hard Tensile requirement, so ``reconcile_tile`` derives the missing half
   rather than hoping a donor supplied a consistent pair.

Deliberately *not* here: any second CSV reader, fingerprint function or knob
parser. Every value comes from the canonical owners (``legality``, ``library``,
``analytics``, ``registry``).
"""


from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from oto.device import loader as _loader
from oto.metrics.cell_coverage import decide_state
from oto.tensile import legality

# ALL_GROUPS / TEMPLATE_KEYS / reconcile_tile / tile_product_holds are imported
# from tile_space and re-exported here so their public names do not move with the
# extraction; tile_product_holds is re-exported only (used by callers/tests).
from oto.tensile.synthesis.tile_space import (
    ALL_GROUPS,
    TEMPLATE_KEYS,
    reconcile_tile,
    tile_product_holds,
)

__all__ = [
    "ALL_GROUPS",
    "MIN_SWEEP_SHAPES",
    "TEMPLATE_KEYS",
    "annotate_drawn_groups",
    "choose_groups",
    "family_shape_sweeps",
    "reconcile_tile",
    "sweep_for_family",
    "synthesize_cell",
    "synthesize_or_lattice",
    "tile_product_holds",
]

#: A sweep shorter than this is not a sweep. One shape is the defect Hplan.1
#: item 5 describes, so a "multi-shape" candidate of length 1 would reintroduce
#: it while satisfying the word.
MIN_SWEEP_SHAPES = 2


# ---------------------------------------------------------------- sweeps

def family_shape_sweeps(
        phases: Sequence[dict[str, Any]],
) -> dict[str, list[str]]:
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
    sweeps: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
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
        sweeps: dict[str, list[str]],
        fallback: Sequence[str] | None = None,
) -> list[str]:
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


# ------------------------------------------------------- coverage guidance

def choose_groups(
        cell: dict[str, Any] | None,
        groups: int,
        rng: random.Random,
        band_pct: float | None = None,
) -> list[str]:
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


def _unstable_groups(cell: dict[str, Any] | None,
                     band_pct: float | None) -> set[str]:
    """Groups whose value co-occurred with a spread beyond the band.

    Attribute attribution is per-config, not per-group: a spread is a property
    of the whole config, so the *drawn* groups are the candidates held
    responsible. When no band was measured, nothing is excluded -- guessing a
    threshold is how a sampler starts avoiding knobs for no reason.
    """
    if not cell or band_pct is None:
        return set()
    limit = float(band_pct) / 100.0
    out: set[str] = set()
    for entry in cell.get("per_fp", ()):
        if entry.get("spread_ratio", 0.0) <= limit:
            continue
        for group in (entry.get("groups") or ()):
            if group in ALL_GROUPS:
                out.add(group)
    return out


def annotate_drawn_groups(knobs: dict[str, Any],
                          drawn: Sequence[str]) -> dict[str, Any]:
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
        base_config: dict[str, Any] | None = None,
        cell: dict[str, Any] | None = None,
        groups: int = 2,
        draws: int = 8,
        seed: str | None = None,
        band_pct: float | None = None,
        shape: str | None = None,
        sweeps: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Draw coverage-guided, tile-consistent candidates for one cell.

    Returns a summary dict rather than a bare list, because the caller has to
    make two decisions the sampler cannot make for it: whether the cell was
    retired (and so should be skipped), and which shapes the candidate will be
    benchmarked over. Both are reported here instead of being inferred.

    The ``sweep_for_family(..., fallback=[shape])`` escape hatch `Hplan.6` step 1 requires: when the
    manifest has no support for a family the sampler returns None, and the caller
    falls back to the ≤2-knob lattice. That is a *degradation* in search quality
    and is reported as such (`source: "lattice"`), never silently.
    """
    sweep = sweep_for_family(family, sweeps or {},
                             fallback=[shape] if shape else None)
    graded = len(sweep) >= MIN_SWEEP_SHAPES

    out: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    rng = random.Random(seed if seed is not None else 0)
    state = decide_state(cell, band_pct=band_pct) if cell else None

    for _i in range(max(0, draws)):
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
        base_config: dict[str, Any] | None,
        groups: Sequence[str],
profile=None,
) -> tuple[dict[str, Any] | None, str]:
    """One draw with a *specific* set of groups, hard-walled before return.

    Wraps `legality`'s own machinery rather than re-implementing substitution, so
    a change to what counts as a hard wall lands here too. `sample_legal` picks
    its own groups, which is exactly what coverage guidance needs to override.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
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
    config.setdefault("DataType", _loader.resolve_profile(profile,).family_dtype_char[family])

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
) -> dict[str, Any]:
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
