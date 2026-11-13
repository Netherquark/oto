#!/usr/bin/env python3
"""The candidate-generator CLI.

Owns: ``main`` -- argparse, the generate/prune/summarise subcommands and the
exit code.
Does NOT own: the rows (oto.harness.candidate_rows), the pool
(oto.harness.candidate_pool) or the overlay I/O
(oto.harness.candidate_overlay).
Public API: main, and the overlay/pool names it re-exports so the tests can
import them from here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from oto.harness.candidate_overlay import (
    OVERLAY_PATH,
    _prune_candidates_from_seed,
    _round_robin_prune,
    _summarise,
    _write_overlay,
)
from oto.harness.candidate_pool import _strip_not_forwarded, iter_candidates
from oto.harness.candidate_rows import TARGET_CELLS, _pad_rows

__all__ = [
    "OVERLAY_PATH",
    "TARGET_CELLS",
    "_pad_rows",
    "_prune_candidates_from_seed",
    "_round_robin_prune",
    "_strip_not_forwarded",
    "_write_overlay",
    "iter_candidates",
    "main",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + count only; do not write the overlay")
    ap.add_argument("--max-fp", type=int, default=None,
                    help="optional cap on emitted candidates (round-robin "
                         "across family/cell buckets); default: no cap "
                         "(emit the whole pool)")
    ap.add_argument("--prune-candidates", action="store_true",
                    help="strip phase_cand_* rows from the seed overlay "
                         "(archive first, keep probe_*/accepted rows); "
                         "overrides all generation")
    args = ap.parse_args()

    if args.prune_candidates:
        _stripped, _kept = _prune_candidates_from_seed(dry_run=args.dry_run)
        return 0

    rows: list[dict[str, Any]] = list(iter_candidates())
    rows = _round_robin_prune(rows, args.max_fp)
    _summarise(rows)
    _write_overlay(rows, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
