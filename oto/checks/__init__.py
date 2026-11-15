"""Operator tools: the standalone check_* / analysis CLIs.

Each module is a self-contained, read-only-by-default diagnostic invoked as a
subcommand. They import the oto package rather than being imported by it.

Owns: nothing at import time — this package holds no logic, only the docstrings
of the modules underneath it.
Does NOT own: the modules themselves (each carries its own), the gates they
call (`oto.tensile.gates`), or the ledger they read (`oto.ledger`).
Public API: none at import time; the public names each module exposes are in
its own docstring, and this package re-exports none of them so importing it has
no side effects.
"""

from __future__ import annotations

__all__ = [
    "candidates",
    "db",
    "library_parity",
    "retirement",
    "tensile_build",
]
