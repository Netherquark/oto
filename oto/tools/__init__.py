"""Offline analysis tools: corpus consolidation, cross-run reporting, verification.

These are the heavy read-only operators that walk every run directory and the
whole registry. They are intentionally separate from ``oto.checks`` because they
mutate nothing but write reports, and from ``oto.runners`` because they never
launch Tensile.

Owns: nothing at import time — this package holds no logic, only the docstrings
of the modules underneath it.
Does NOT own: the modules themselves (each carries its own), the corpus they
analyse (<codename>_runs/, <codename>_results/), or the checks that gate a deck
(oto.checks).
Public API: none at import time; this package re-exports nothing, so importing
it has no side effects.
"""

from __future__ import annotations

__all__ = [
    "allruns",
    "consolidate",
    "consolidate_deck",
    "consolidate_floor",
    "consolidate_install",
    "consolidate_targets",
    "verify_run",
]
