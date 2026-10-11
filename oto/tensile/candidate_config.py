#!/usr/bin/env python3
"""The candidate payload dataclass.

Owns: ``CandidateConfig`` -- what a candidate IS, as opposed to how one is
generated (oto.tensile.candidate) or how it reaches the deck
(oto.tensile.candidate_emission). One home, so neither module needs a second
copy that drifts.
Public API: CandidateConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


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
    shapes: List[str]
    template: Dict[str, Any]
    knobs: Dict[str, Any]
    fingerprint: str
