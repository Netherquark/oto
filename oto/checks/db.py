#!/usr/bin/env python3
"""Inspect the registry DB for label contamination ('auto' / 'Unknown').

Owns: this one ad-hoc SQLite inspection of ``gfx90c_results/registry.db``.
Does NOT own: any read the rest of oto performs (use ``oto.ledger.registry`` or
``oto.tools.allruns`` for anything the project depends on).
Public API: ``main``.
"""

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    """Print sample record keys and every record whose label smells of drift."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-dir", type=Path, default=Path("."),
                    help="repo root")
    args = ap.parse_args()
    conn = sqlite3.connect(Path(args.base_dir) / "gfx90c_results" / "registry.db")
    cursor = conn.cursor()

    # Sample some records to understand structure
    cursor.execute("SELECT id, data FROM records LIMIT 5")
    print('Sample records:')
    for row in cursor.fetchall():
        record_id, data_json = row
        data = json.loads(data_json)
        print(f'\n  ID {record_id}:')
        print(f'    Keys: {list(data.keys())}')
        if 'label' in data:
            print(f'    Label: {data["label"]}')
        if 'phase_id' in data:
            print(f'    Phase ID: {data["phase_id"]}')

    # Check for auto/Unknown labels more thoroughly
    cursor.execute("SELECT id, data FROM records")
    print('\n\nRecords with auto/Unknown in label:')
    for row in cursor.fetchall():
        record_id, data_json = row
        data = json.loads(data_json)
        label = data.get('label', '')
        phase_id = data.get('phase_id', '')
        if 'auto' in label.lower() or 'unknown' in label.lower():
            print(f'  ID {record_id}: phase_id={phase_id}, label={label}')

    conn.close()


if __name__ == "__main__":
    main()
