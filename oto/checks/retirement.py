#!/usr/bin/env python3
"""Inspect the registry DB for retirement records and per-cell sample counts.

Owns: this one ad-hoc SQLite inspection of ``<codename>_results/registry.db``.
Does NOT own: any read the rest of oto performs (use ``oto.ledger.registry`` or
``oto.tools.allruns`` for anything the project depends on).
Public API: ``main``.
"""

import argparse
import json
import sqlite3
from pathlib import Path

import oto.device.peaks as _peaks
from oto.runners.paths import results_dir as _results_dir


def main() -> None:
    """Print retirement records and every cell holding >= 3 samples."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-dir", type=Path, default=Path("."),
                    help="repo root")
    args = ap.parse_args()
    conn = sqlite3.connect(_results_dir(args.base_dir, _peaks.CODENAME) / "registry.db")
    cursor = conn.cursor()

    # Check for retirement records
    cursor.execute("SELECT id, data FROM records WHERE record_type = 'retire'")
    print('Retirement records:')
    retire_count = 0
    for row in cursor.fetchall():
        _record_id, data_json = row
        data = json.loads(data_json)
        retire_count += 1
        print(f'  ID {_record_id}: {data}')

    if retire_count == 0:
        print('  No retirement records found')

    # Check sample counts per cell
    cursor.execute("SELECT id, data FROM records WHERE record_type = 'general'")
    cell_sample_counts = {}
    for row in cursor.fetchall():
        _record_id, data_json = row
        data = json.loads(data_json)
        dtype = data.get('dtype', data.get('DataType', 'unknown'))
        shape = data.get('shapes', data.get('ProblemType', 'unknown'))
        fp = data.get('fp', 'unknown')
        key = f"{dtype}_{shape}_{fp}"
        cell_sample_counts[key] = cell_sample_counts.get(key, 0) + 1

    print('\nSample counts per cell (showing cells with >=3 samples):')
    for _key, count in sorted(cell_sample_counts.items()):
        if count >= 3:
            print(f'  {_key}: {count} samples')

    conn.close()


if __name__ == "__main__":
    main()
