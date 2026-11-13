#!/usr/bin/env python3
"""The candidate payload dataclass.

Owns: ``CandidateConfig`` -- what a candidate IS, as opposed to how one is
generated (oto.tensile.candidate) or how it reaches the deck
(oto.tensile.candidate_emission). One home, so neither module needs a second
copy that drifts.
Does NOT own: the candidate generator (oto.tensile.candidate), the append
boundary (oto.tensile.candidate_emission), or the ledger that records a
candidate's outcome (oto.ledger.mutator).
Public API: CandidateConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CandidateConfig:
    """Candidate configuration for benchmarking.

    ``fingerprint`` is the content identity of the merged template+knobs dict:
    it is what dedupes a candidate, binds a phase_id, and lets a later run
    decide whether a measurement still describes the config that would run now.
    """

    phase_id: str
    label: str
    dtype: str
    shapes: list[str]
    template: dict[str, Any]
    knobs: dict[str, Any]
    fingerprint: str
