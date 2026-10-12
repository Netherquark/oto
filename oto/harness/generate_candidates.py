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
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from oto.harness.candidate_overlay import (  # noqa: E402
    OVERLAY_PATH, _prune_candidates_from_seed, _round_robin_prune, _summarise,
    _write_overlay)
from oto.harness.candidate_pool import (__yaml_load,  # noqa: E402
                                        iter_candidates, _narrow_row_gen,
                                        _strip_not_forwarded)
from oto.harness.candidate_rows import (PROBE_CELLS, TARGET_CELLS,  # noqa: E402
                                        _pad_rows)

__all__ = ["main", "iter_candidates", "_round_robin_prune",
           "_strip_not_forwarded", "_write_overlay", "OVERLAY_PATH",
           "PROBE_CELLS", "TARGET_CELLS", "_pad_rows", "_prune_candidates_from_seed"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + count only; do not write the overlay")
    ap.add_argument("--max-fp", type=int, default=300,
                    help="cap total emitted candidates (round-robin across "
                         "family/cell buckets; default 300)")
    ap.add_argument("--with-probes", action="store_true",
                    help="append off-grid probe rows to the seed overlay too "
                         "(breaks the §6.1 parity test until the rule is amended; "
                         "probes are always mirrored regardless)")
    ap.add_argument("--prune-candidates", action="store_true",
                    help="strip phase_cand_* rows from the seed overlay "
                         "(archive first, keep probe_*/accepted rows); "
                         "overrides all generation")
    args = ap.parse_args()

    if args.prune_candidates:
        stripped, kept = _prune_candidates_from_seed(dry_run=args.dry_run)
        print(f"{'[dry-run] would strip' if args.dry_run else 'stripped'} "
              f"{stripped} phase_cand_* rows; {kept} rows kept in "
              f"{OVERLAY_PATH.name}")
        return 0

    rows: List[Dict[str, Any]] = list(iter_candidates())
    rows = _round_robin_prune(rows, args.max_fp)
    probes = [r for r in rows if not r["graded"]]
    grid_rows = [r for r in rows if r["graded"]]
    _summarise(rows)
    written = _write_overlay(grid_rows, probes, dry_run=args.dry_run,
                             with_probes=args.with_probes)
    print(f"{'[dry-run] would append' if args.dry_run else 'appended'} "
          f"{written} candidate(s) to {OVERLAY_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
