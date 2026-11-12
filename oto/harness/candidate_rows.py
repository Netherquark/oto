#!/usr/bin/env python3
"""The candidate row builders: per-family tile ladders and the auto rows.

Owns: the public entry point to the candidate row data, re-exported from the
three sibling modules so the historical import paths keep working:
``_rows_core`` (ladders + the PLAN_BATCH literal + the pad encoder),
``_rows_frontier`` (tie-adapt / frontier winner blocks) and
``_rows_smallcells`` (small-cell evidence blocks). Import order is fixed and
load-bearing -- the sibling modules mutate ``PLAN_BATCH`` at import time.

Does NOT own: the deck/seed fingerprint sets (candidate_decks), the overlay
read/write (candidate_overlay), or the pruning helpers (candidate_prune).
"""

from __future__ import annotations

from oto.harness._rows_core import (AUTO_EXPLICIT, DU_VARIANTS, FAMILY_DTYPE,  # noqa: F401
                                     LADDER, NARROW_NEIGHBOURS, PATTERNS,
                                     PLAN_BATCH, TARGET_CELLS, WGM_VARIANTS,
                                     _NOT_FORWARDED_YET, _pad_rows)
from oto.harness._rows_frontier import _FRONTIER  # noqa: F401
from oto.harness import _rows_smallcells as _rows_smallcells  # noqa: F401  (import-time rows)

__all__ = [
    "AUTO_EXPLICIT", "DU_VARIANTS", "FAMILY_DTYPE", "LADDER",
    "NARROW_NEIGHBOURS", "PATTERNS", "PLAN_BATCH", "TARGET_CELLS",
    "WGM_VARIANTS", "_NOT_FORWARDED_YET", "_pad_rows", "_FRONTIER",
    "_rows_smallcells",
]
