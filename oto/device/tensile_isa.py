#!/usr/bin/env python3
"""Tensile ``CurrentISA`` version triples for the gfx9 family.

Owns: the codename -> Tensile ``CurrentISA`` triple table (``ISA_TRIPLES``)
and the ``isa_triple`` lookup used by the build proof. The only oto module
allowed to hold these triples.
Does NOT own: any other hardware fact (``oto.device.peaks``), device detection
(``oto.device.detect``), or Tensile's own ISA semantics (the triple is opaque
to us).
Public API: ``ISA_TRIPLES``, ``isa_triple``.

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
