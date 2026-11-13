#!/usr/bin/env python3
"""Inspect the registry DB for retirement records and per-cell samples.

Owns: retirement records and the per-cell sample counts for
``<codename>_results/registry.db``.
Does NOT own: the retirement policy (oto.metrics.policy) or any other registry
read (use ``oto.checks.db`` / ``oto.ledger.registry`` where they belong).
Public API: main.

    oto check retirement            # human view
    oto check retirement --json    # one JSON document
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import oto.device.peaks as _peaks
from oto.runners.paths import results_dir as _results_dir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-dir", "--base", type=Path, default=Path("."),
                    help="repo root")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    db = _results_dir(args.base_dir, _peaks.CODENAME) / "registry.db"
    retirements: list[str] = []
    samples: dict[str, int] = {}
    if db.is_file():
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            retirements.extend(
                str(json.loads(data))
                for _rid, data in conn.execute(
                    "SELECT id, data FROM records WHERE record_type = 'retire'"))
            for _rid, data in conn.execute(
                    "SELECT id, data FROM records WHERE record_type = 'general'"):
                try:
                    d = json.loads(data)
                except Exception:
                    continue
                key = f"{d.get('dtype', d.get('DataType', 'unknown'))}_" \
                      f"{d.get('shapes', d.get('ProblemType', 'unknown'))}_{d.get('fp', 'unknown')}"
                samples[key] = samples.get(key, 0) + 1
        finally:
            conn.close()

    big = {k: v for k, v in samples.items() if v >= 3}
    if args.json:
        print(json.dumps({"registry": str(db), "retirements": retirements,
                          "cells": big, "ok": True}, indent=2, default=str))
        return 0

    print("Retirement records:")
    for rid in retirements:
        print(rid)
    if not retirements:
        print("No retirement records found")
    print("\nSample counts per cell (cells with >=3 samples):")
    for key, count in sorted(big.items()):
        print(f"  {key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
