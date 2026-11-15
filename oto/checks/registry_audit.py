#!/usr/bin/env python3
"""Inspect the registry DB for label contamination ('auto' / 'Unknown').

Owns: this one ad-hoc SQLite inspection of ``<codename>_results/registry.db``.
Does NOT own: any read the rest of oto performs (use ```oto.ledger.registry``` or
```oto.tools.run_census``` for anything the project depends on).
Public API: main.

    oto check db            # human inspector
    oto check db --json    # one JSON document

Exit code is 1 when contamination is found (the check is a gate), 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from oto.device import loader as _loader
from oto.runners.result_paths import results_dir as _results_dir


def _base(args) -> Path:
    """The base directory the audit reads."""
    return args.base_dir


def _load_labels(db: Path) -> tuple[list[str], int]:
    """The ids of records with auto/Unknown labels, and the total record count."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        bad: list[str] = []
        for rid, data in conn.execute("SELECT id, data FROM records"):
            try:
                label = str(json.loads(data).get("label", ""))
            except Exception:
                continue
            if "auto" in label.lower() or "unknown" in label.lower():
                bad.append(str(rid))
        total = int(conn.execute("SELECT count(*) FROM records").fetchone()[0])
    finally:
        conn.close()
    return bad, total


def main(profile=None) -> int:
    """Inspect the registry DB for label contamination (CLI entry). ``profile`` selects the device; ambient by default."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-dir", "--base", type=Path, default=Path("."),
                    help="repo root")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    db = _results_dir(args.base_dir, _loader.resolve_profile(profile,).codename) / "registry.db"
    bad, total = ([], 0)
    db_ok = db.is_file()
    integrity_ok = False
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True) if db_ok else None
    if conn is not None:
        try:
            integrity_ok = (conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
        finally:
            conn.close()
    if db_ok:
        bad, total = _load_labels(db)

    if args.json:
        print(json.dumps({
            "registry": str(db),
            "db_ok": db_ok,
            "integrity": integrity_ok if db_ok else False,
            "total_records": total,
            "contaminated": bad,
            "ok": db_ok and integrity_ok and not bad,
        }, indent=2, default=str))
        return 1 if (db_ok and (bad or not integrity_ok)) else 0

    if not db_ok:
        print(f"registry missing: {db}")
        return 1
    print(f"registry: {db}")
    print(f"integrity: {'ok' if integrity_ok else 'FAIL'}")
    if not integrity_ok:
        return 1
    print(f"records: {total}")
    if bad:
        print("contaminated records:")
        for rid in bad:
            print(f"  - id={rid}")
        return 1
    print("no auto/Unknown labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
