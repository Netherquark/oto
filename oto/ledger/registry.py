#!/usr/bin/env python3
"""The ledger: append-only records, runs, phases and the Option-H proposals.

Owns: ``SQLiteRegistry`` -- the composition root over three single
responsibility mixins: the engine (registry_core), the read side (queries) and
the proposal ledger (proposals). It owns nothing itself but the ``__init__``
signature and the base-dir/resolution behaviour, so
``SQLiteRegistry(base_dir, read_only=...)`` keeps working for every caller.
Does NOT own: how a migration is mutated (oto.ledger.mutator), how a phase is
run (oto.runners), or how a row is graded (oto.metrics).
Public API: SQLiteRegistry, fingerprint_config.
"""

from oto.ledger.registry_core import RegistryCore, fingerprint_config
from oto.ledger.registry_proposals import ProposalMixin
from oto.ledger.registry_queries import QueryMixin

__all__ = ["SQLiteRegistry", "fingerprint_config"]


class SQLiteRegistry(RegistryCore, QueryMixin, ProposalMixin):
    """SQLite-based append-only registry with ACID guarantees.

    One mixin per responsibility; see each module's docstring for what it owns.
    """
