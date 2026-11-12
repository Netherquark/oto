#!/usr/bin/env python3
"""The contraction-pattern vocabulary: one spelling, one meaning.

Owns: ``TRANSPOSE_MAP`` (the four pattern spellings and the transpose flags
they imply) and ``pattern_of`` (the pattern a config or a phase names).

Does NOT own: the per-family pattern lists (the deck's, in
oto.harness.candidate_rows), the problem type the writer emits
(oto.tensile.config_writer), or the load-divisibility rules that read these
flags (oto.tensile.gates.loads).

Why this module exists: one spelling must mean one thing, and the two
readings of it are NOT the same thing.

* ``TRANSPOSE_MAP`` -- the *problem type* flags the writer emits:
  ``TransposeA``/``TransposeB`` (the BLAS-level layout). This map is what
  produced the measured corpus: it reproduces the vendor's gfx900 kernel names
  for the same spelling.
* ``tlu_flags`` -- the *LDS layout* flags Tensile derives for itself
  (``TLUA``/``TLUB``, from the index assignments, SolutionStructs:1099-1100).
  They differ from the transpose flags: the solution built for ``Alik_Bjlk``
  carries ``TransposeA: true, TransposeB: true`` but ``TLUA: false,
  TLUB: true``.

The loads gate needs the second pair (the coalesced-vs-perpendicular geometry
of an operand), the writer needs the first. Both live here, so the two cannot
drift apart again.

Public API: TRANSPOSE_MAP, DEFAULT_PATTERN, DEFAULT_TRANSPOSE, transposes,
tlu_flags, pattern_of.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

#: Pattern spelling -> (TransposeA, TransposeB). ``i``/``j``/``k``/``l`` are
#: the matrix dimensions; "A**i**lk" means A is stored i-major (k contiguous),
#: "A**l**ik" means A is l-major (so A is transposed for the GEMM).
TRANSPOSE_MAP: Dict[str, Tuple[bool, bool]] = {
    "Ailk_Bjlk": (False, True),
    "Alik_Bjlk": (True, True),
    "Ailk_Bljk": (False, False),
    "Alik_Bljk": (True, False),
}

#: The pattern a config that names none is assumed to be (the NT default the
#: writer uses).
DEFAULT_PATTERN = "Ailk_Bjlk"

#: Its transpose flags.
DEFAULT_TRANSPOSE: Tuple[bool, bool] = TRANSPOSE_MAP[DEFAULT_PATTERN]

#: Every spelling, longest first, so "Alik_Bjlk" is found before a prefix.
_SPELLINGS = tuple(sorted(TRANSPOSE_MAP, key=len, reverse=True))


def transposes(pattern: str) -> Tuple[bool, bool]:
    """(TransposeA, TransposeB) for a contraction pattern spelling.

    Args:
        pattern: One of the four spellings (an unknown one falls back to the
            NT default, which is what the writer does).

    Returns:
        The two transpose flags.
    """
    return TRANSPOSE_MAP.get(pattern, DEFAULT_TRANSPOSE)


def tlu_flags(pattern: str) -> Tuple[bool, bool]:
    """(TLUA, TLUB) for a contraction pattern spelling.

    Tensile derives these from the *index assignments*
    (SolutionStructs:1099-1100), not from the problem type's transpose flags:
    an operand is "TLU" when its stride index comes before the unroll index.
    In the spelling, "A**i**lk" is k-contiguous (TLUA False) and
    "B**j**lk" is k-contiguous (TLUB True).

    Args:
        pattern: One of the four spellings.

    Returns:
        The two layout flags. An unknown spelling falls back to the NT
        default, as the writer does.
    """
    return ("Ailk" in pattern, "Bjlk" in pattern)


def pattern_of(config: Dict[str, Any]) -> str:
    """The contraction pattern a config (or its phase label) names.

    Args:
        config: A Tensile solution dict. It may carry ``ContractionPattern``
            directly, or only a label that contains the spelling (the deck's
            labels do: "CC_Ailk_Bljk_512x512x512_...").

    Returns:
        The pattern spelling (the NT default when neither names one).
    """
    named = config.get("ContractionPattern")
    if named:
        text = str(named)
        for spelling in _SPELLINGS:
            if spelling in text:
                return spelling
        return DEFAULT_PATTERN
    label = str(config.get("label", ""))
    for spelling in _SPELLINGS:
        if spelling in label:
            return spelling
    return DEFAULT_PATTERN
