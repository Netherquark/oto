#!/usr/bin/env python3
"""Tensile ``CurrentISA`` version triples for the gfx9 family.

Owns: the codename -> Tensile ``CurrentISA`` triple table (``ISA_TRIPLES``)
and the ``isa_triple`` lookup used by the CPU-only build proof. The only oto
module allowed to hold these triples.
Does NOT own: any other hardware fact (``oto.device.loader``), device detection
(``oto.device.device_detect``), or Tensile's own ISA semantics (the triple is opaque
to us).
Public API: ``ISA_TRIPLES``, ``isa_triple``.
"""
from __future__ import annotations

#: codename -> Tensile ``CurrentISA`` triple. Device-independent: the triple is
#: a toolchain fact (LLVM/Tensile ISA version), not a measurement, so new arches
#: are added from the public ISA-version documentation, never from probing.
ISA_TRIPLES = {
    "gfx900": (9, 0, 0x00),
    "gfx90c": (9, 0, 0x0C),
    "gfx902": (9, 0, 0x02),
    "gfx906": (9, 0, 0x06),
}


def isa_triple(codename: str) -> tuple[int, int, int] | None:
    """Return Tensile's ``CurrentISA`` triple for ``codename``, or ``None``."""
    return ISA_TRIPLES.get(codename)
