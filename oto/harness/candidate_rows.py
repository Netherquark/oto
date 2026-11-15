#!/usr/bin/env python3
"""The candidate row builders: per-family tile ladders and the auto rows.

Owns: the public entry point to the candidate row data, re-exported from the
three sibling modules so the historical import paths keep working:
``rows_ladders`` (ladders + the PLAN_BATCH literal + the pad encoder),
``rows_frontier`` (tie-adapt / frontier winner blocks) and
``rows_smallcells`` (small-cell evidence blocks). Import order is fixed and
load-bearing -- rows_ladders defines ``PLAN_BATCH``; rows_frontier hangs its
rows off it; rows_smallcells hangs its rows off those. Load order:
``ladders -> frontier -> smallcells``; do not let an import sorter flip it.

Does NOT own: the deck/seed fingerprint sets (``oto.harness.candidate_pool``),
the overlay read/write (``oto.harness.candidate_overlay``), or candidate
 generation (``oto.harness.candidate_generator``).
"""

from __future__ import annotations

# ruff: noqa: I001 -- import order here is load-bearing (see docstring).
from oto.harness import rows_ladders as rows_ladders
from oto.harness import rows_frontier as rows_frontier
from oto.harness import rows_smallcells as rows_smallcells
from oto.harness.rows_frontier import _FRONTIER
from oto.harness.rows_ladders import (
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
                                     "rows_smallcells",
]
