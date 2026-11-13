#!/usr/bin/env python3
"""Deck check: does every *unmeasured* deck row actually build in Tensile?

Owns: the pre-run sweep that puts the deck through Tensile's own kernel writer
and reports the rows it refuses.

Does NOT own: the legality gates (oto.tensile.gates), the oracle's probe
(oto.harness.tensile_oracle), the corpus (oto.harness.kernel_db) or the
registry (oto.ledger.registry).
Public API: check, unmeasured_rows, measured_fingerprints, main.

Why: the CPU gates are *models* of Tensile. A model that says "legal" and a
Tensile that says "0 solutions" costs a launch slot and a wasted phase in the
overnight run -- the 2026-10-20 run spent 8 phases on tiles that cannot be
built at all. This is the check that would have caught them, and it runs on
CPU only (it builds kernel sources; it never launches anything).

The rows checked are the ones the corpus has NOT measured: everything already
measured is known to build, and re-probing it would cost hours for no
information.

    python3 -m oto.harness.deck_check                    # every unmeasured row
    python3 -m oto.harness.deck_check --family CC --limit 20
    python3 -m oto.harness.deck_check --json out.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import oto.device.peaks as _peaks
from oto.harness.tensile_oracle import probe_phase
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import results_rel

#: The launch set: the persistent seed overlay.
OVERLAY = Path(results_rel("overlays", "phases.seed.overlay.yaml"))


def measured_fingerprints(base_dir: Path) -> set:
    """The config fingerprints the registry already holds a measurement for.

    Args:
        base_dir: The repo root.

    Returns:
        The set of measured fingerprints.
    """
    db = _results_dir(base_dir, _peaks.CODENAME) / "registry.db"
    if not db.is_file():
        return set()
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT data FROM records WHERE record_type='general'").fetchall()
    finally:
        con.close()
    done: dict[str, bool] = {}
    for (raw,) in rows:
        try:
            record = json.loads(raw)
        except (TypeError, ValueError):
            continue
        fp = record.get("fp")
        if not fp:
            continue
        status = record.get("status")
        if status in ("completed", "success"):
            done[fp] = True
    return set(done)


def unmeasured_rows(base_dir: Path, overlay: Path) -> list[dict[str, Any]]:
    """The overlay rows the corpus has never measured.

    Args:
        base_dir: The repo root.
        overlay: The launch set (the seed overlay).

    Returns:
        The phase dicts, in the overlay's order.
    """
    import yaml

    path = base_dir / overlay
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text()) or {}
    rows = payload.get("phases") if isinstance(payload, dict) else payload
    done = measured_fingerprints(base_dir)
    return [r for r in (rows or []) if isinstance(r, dict)
            and r.get("fp") and r["fp"] not in done]


#: The overlay carries a dtype char; the deck families are two letters.
_DTYPE_FAMILY = {"S": "SS", "D": "DD", "H": "HH", "C": "CC", "Z": "ZZ"}


def _family_of(row: dict[str, Any]) -> str:
    """The deck family of an overlay row."""
    char = str(row.get("dtype", "")).upper()
    return _DTYPE_FAMILY.get(char, char)


def _probed_before(result_path: Path | None) -> set:
    """The phase ids a previous sweep already probed (so a re-run skips them)."""
    if not result_path or not result_path.is_file():
        return set()
    try:
        payload = json.loads(result_path.read_text())
    except (OSError, ValueError):
        return set()
    rows = payload.get("checked", [])
    if not isinstance(rows, list):
        return set()
    return {r.get("phase_id", "") for r in rows if isinstance(r, dict)}


def check(base_dir: Path, overlay: Path, families: Sequence[str] = (),
          limit: int | None = None,
          result_path: Path | None = None) -> dict[str, Any]:
    """Probe every unmeasured row and collect the refusals.

    Args:
        base_dir: The repo root.
        overlay: The launch set.
        families: Only probe these families (all of them when empty).
        limit: Stop after this many rows.

    Returns:
        A summary dict: the rows checked, the refusals (with their reason),
        and the elapsed seconds.
    """
    rows = unmeasured_rows(base_dir, overlay)
    if families:
        wanted = {f.upper() for f in families}
        rows = [r for r in rows
                if _family_of(r) in wanted]
    already = _probed_before(result_path)
    if already:
        rows = [r for r in rows if r.get("phase_id") not in already]
    if limit:
        rows = rows[:limit]
    started = time.time()
    refusals: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    for _index, row in enumerate(rows, 1):
        verdict = probe_phase(row, base_dir)
        if not verdict.get("tensile", {}).get("ok"):
            refusals.append({
                "phase_id": row.get("phase_id", ""),
                "dtype": row.get("dtype", ""),
                "gate_refusal": verdict.get("gate_refusal"),
                "tensile_reason": verdict.get("tensile", {}).get("reason"),
            })
        print(f"[{_index}/{len(rows)}] {row.get('phase_id', '')[:72]} "
              f"{'OK' if verdict.get('tensile', {}).get('ok') else 'REFUSED'}",
              flush=True)
        checked.append({"phase_id": row.get("phase_id", ""),
                        "ok": bool(verdict.get("tensile", {}).get("ok")),
                        "reason": verdict.get("tensile", {}).get("reason")})
    previous, previous_refusals, note = [], [], ""
    if result_path and result_path.is_file():
        try:
            old = json.loads(result_path.read_text())
            previous = old.get("checked", []) if isinstance(old.get("checked"), list) else []
            previous_refusals = old.get("refusals", []) or []
            note = old.get("note", "")
        except (OSError, ValueError):
            pass
    # The refusals accumulate: a sweep that is stopped and resumed must not
    # lose the refusal it already found.
    known = {r.get("phase_id") for r in previous_refusals}
    merged = previous_refusals + [r for r in refusals
                                  if r.get("phase_id") not in known]
    return {"checked": previous + checked, "probed": len(rows),
            "refusals": merged, "seconds": round(time.time() - started, 1),
            "note": note}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", default=None, help="repo root")
    ap.add_argument("--overlay", default=str(OVERLAY), help="the launch set")
    ap.add_argument("--family", action="append", help="limit to a family")
    ap.add_argument("--limit", type=int, default=None, help="stop after N rows")
    ap.add_argument("--json", type=Path, help="write the result here")
    args = ap.parse_args(argv)

    base = Path(args.base_dir or _HERE)
    result_path = (args.json if args.json and args.json.is_absolute()
                   else (base / args.json) if args.json else None)
    result = check(base, Path(args.overlay), args.family or (), args.limit,
                   result_path)
    print(f"\nprobed {result['probed']} unmeasured row(s) in "
          f"{result['seconds']}s -- {len(result['refusals'])} refused by Tensile")
    for _refusal in result["refusals"][:20]:
        print(f"  REFUSED {_refusal['phase_id']}: "
              f"{_refusal['tensile_reason'] or _refusal['gate_refusal']}")
    if args.json:
        out = result_path or (base / args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1))
        print(f"wrote -> {out}")
    return 1 if result["refusals"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
