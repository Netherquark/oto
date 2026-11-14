#!/usr/bin/env python3
"""The candidate row builders: per-family tile ladders and the auto rows.

Owns: the public entry point to the candidate row data, re-exported from the
three sibling modules so the historical import paths keep working:
``_rows_core`` (ladders + the PLAN_BATCH literal + the pad encoder),
``_rows_frontier`` (tie-adapt / frontier winner blocks) and
``_rows_smallcells`` (small-cell evidence blocks). Import order is fixed and
load-bearing -- the sibling modules mutate ``PLAN_BATCH`` at import time.

Does NOT own: the deck/seed fingerprint sets (``oto.harness.candidate_pool``),
the overlay read/write (``oto.harness.candidate_overlay``), or candidate
 generation (``oto.harness.generate_candidates``).
"""

from __future__ import annotations

from oto.harness import _rows_smallcells as _rows_smallcells
from oto.harness._rows_core import (
                                     _NOT_FORWARDED_YET,
                                     AUTO_EXPLICIT,
                                     DU_VARIANTS,
                                     FAMILY_DTYPE,
                                     LADDER,
                                     NARROW_NEIGHBOURS,
                                     PATTERNS,
                                     PLAN_BATCH,
                                     TARGET_CELLS,
                                     WGM_VARIANTS,
                                     _pad_rows,
)
from oto.harness._rows_frontier import _FRONTIER

__all__ = [
                                     "AUTO_EXPLICIT",
                                     "DU_VARIANTS",
                                     "FAMILY_DTYPE",
                                     "LADDER",
                                     "NARROW_NEIGHBOURS",
                                     "PATTERNS",
                                     "PLAN_BATCH",
                                     "TARGET_CELLS",
                                     "WGM_VARIANTS",
                                     "_FRONTIER",
                                     "_NOT_FORWARDED_YET",
                                     "_pad_rows",
                                     "_rows_smallcells",
]
