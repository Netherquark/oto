"""Everything Tensile-facing: the candidate pipeline and its CPU legality gates.

Submodules:
  oto.tensile.shipped_floor_manifest, shipped_library
                            kernel-name parsing, the shipped gfx900 manifest
                            and the rerun tier triage
  oto.tensile.candidate    candidate generation / the curated deck / the gate
                            orchestrator; candidate_config and
                            candidate_emission carry the payload and the
                            append boundary; decks carries the tile table
  oto.tensile.config_writer  the launch-boundary config writer
  oto.tensile.gates         the three CPU legality gate families (imported by,
                            never interleaved with, the candidate generator)
  oto.tensile.legality      the manifest-derived legal prior
  oto.tensile.library_parity  the coverage-parity rule
  oto.tensile.synthesis     coverage-guided candidate synthesis (manifest + db)

Owns: nothing at import time — this package holds no logic, only the docstrings
of the modules underneath it.
Does NOT own: the modules themselves (each carries its own), the ledger that
records their output (oto.ledger), or the run loop that schedules it
(oto.runners).
Public API: none at import time; this package re-exports nothing, so importing
it has no side effects.
"""

from __future__ import annotations

__all__ = [
    "candidate",
    "candidate_config",
    "candidate_emission",
    "config_writer",
    "decks",
    "legality",
    "library",
    "library_parity",
    "shipped_library",
]
