#!/usr/bin/env python3
"""Canonical numeric ordering for Tensile problem-shape strings.

Owns: ``shape_parts`` / ``shape_order_key`` / ``ordered_shapes`` /
``is_numerically_ordered`` -- the single definition of the order a phase's
``ProblemSizes`` sweep must be emitted in.

Why this module exists. A Tensile phase's ``ProblemSizes`` is a *sweep*: the
benchmark runner executes the sizes in list order, and each size's median absorbs
the GPU clock state the size before it left behind (``claude.md`` 2.0.3). A phase
measured out of order is therefore not a weaker kernel, it is a *different
measurement*. Sorting the shape **strings** gave the lexicographic order
``1024, 192, 2048, 256, 512``, which put 256^3 immediately after the slowest
2048^3 kernel, throttled it to ~1/3 clock and collapsed its median
(~55 vs ~210 GFLOPS) -- the CC:256 "one loser" (`results.md` 13.4). The deck
(``phases.yaml``), ``FAMILY_SHAPES`` and ``TARGET_CELLS`` are all numerically
ascending, so every producer and every writer must agree on that order.

Does NOT own: which shapes a phase carries (the deck / candidate rows) or the
legality of a shape.
Public API: shape_parts, shape_order_key, ordered_shapes, is_numerically_ordered.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple

__all__ = ["shape_parts", "shape_order_key", "ordered_shapes",
           "is_numerically_ordered"]


def _token(part: Any) -> int:
    try:
        return int(part)
    except (TypeError, ValueError):
        # A non-numeric token (never a real cube side) sorts first and cannot
        # collide with a real side; keeping it comparable beats raising inside
        # a sort key.
        return -1


def shape_parts(shape: Any) -> Tuple[int, ...]:
    """Numeric parts of a shape as a comparable tuple.

    Accepts ``"MxNxBxK"`` / ``"MxNxK"`` strings and already-split sequences
    (Tensile's ``Exact: [...]`` form), so the same key orders both the manifest
    row and the last-mile config.
    """
    if isinstance(shape, (list, tuple)):
        return tuple(_token(v) for v in shape)
    return tuple(_token(p) for p in str(shape).split("x"))


def shape_order_key(shape: Any) -> Tuple[int, ...]:
    """Sort key ordering shapes by their numeric parts, ascending.

    Cubes sort by side; a leading-side mismatch dominates for non-cube shapes,
    exactly as the deck orders them. Deterministic ties (same leading side,
    different tail) fall through to the remaining parts.
    """
    return shape_parts(shape)


def ordered_shapes(shapes: Iterable[Any], *, dedupe: bool = False) -> List[Any]:
    """``shapes`` in canonical ascending numeric order.

    ``dedupe`` removes exact duplicates while preserving the first occurrence;
    it is off by default because callers that need a set already pass one.
    """
    seq = list(shapes)
    if dedupe:
        seen = set()
        uniq: List[Any] = []
        for s in seq:
            if s in seen:
                continue
            seen.add(s)
            uniq.append(s)
        seq = uniq
    return sorted(seq, key=shape_order_key)


def is_numerically_ordered(shapes: Iterable[Any]) -> bool:
    """True when ``shapes`` is already in :func:`ordered_shapes` order."""
    keys = [shape_order_key(s) for s in shapes]
    return keys == sorted(keys)
