"""Candidate synthesis: coverage-guided, tile-legal candidate draws.

Two synthesizers share one tile vocabulary:

  pipeline_manifest.py   coverage-guided manifest draws (sample_legal / synthesize_cell)
  donor_mutator.py       DB-hooked wide+narrow+direction mutants (DBMutator)
  tile_space.py the shared tile/group vocabulary + tile reconciliation, imported
                by both so neither can drift from the other's notion of a tile.

Owns: turning measured coverage evidence into tile-consistent candidate knobs.
Does NOT own: the gates that judge those knobs (`oto.tensile.gates`), the ledger
that records them (`oto.ledger`), or the run loop that schedules them
(`oto.runners`).
Public API: none at import time; the public names
of each module live in its own docstring, and this package re-exports none of
them at import time.
"""
