#!/usr/bin/env python3
"""Tensile ``CurrentISA`` version triples for the gfx9 family.

Tensile's toolchain wants ``(major, minor, stepping)`` to pin the ISA when no
GPU is present. This module is the one place in oto allowed to hold those
triples, together with the codename -> triple lookup used by the build proof.
"""
from __future__ import annotations

#: codename -> Tensile ``CurrentISA`` triple.
ISA_TRIPLES = {
    "gfx900": (9, 0, 0x00),
    "gfx90c": (9, 0, 0x0C),
    "gfx906": (9, 0, 0x06),
}


def isa_triple(codename: str) -> tuple[int, int, int] | None:
    """Return Tensile's ``CurrentISA`` triple for ``codename``, or ``None``."""
    return ISA_TRIPLES.get(codename)
