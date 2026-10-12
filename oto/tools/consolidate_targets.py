#!/usr/bin/env python3
"""Which cells a consolidated deck must address.

Owns: ``target_cells`` (every cell the shipped floor covers), ``manifest_cells`` (the cross-check set the shipped gfx900 manifest names) and the ``native_runs`` / ``floor_chain`` / ``source_chain`` run listings those cells are read from.
Does NOT own: the measurement inventory built over them (consolidate_deck) or the locked floor (consolidate_floor).
Public API: target_cells, manifest_cells, native_runs, floor_chain, source_chain, _fam, _stamp."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from oto.device.peaks import FAMILY_SHAPES, cell_key  # noqa: E402
from oto.metrics.ab_audit import BASE as _AB_BASE, _driver  # noqa: E402
from oto.metrics.analytics import extract_family_from_phase_id  # noqa: E402

BASE = _AB_BASE

#: The locked floor, expressed in one registry db.
LIVE_DB = BASE / "gfx90c_results" / "registry.db"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _fam(phase_id: str) -> str:
    """Family label uppercased.

    `extract_family_from_phase_id` returns the phase_id's own spelling ('ss',
    'zz') while FAMILY_SHAPES and cell_key() are upper-case, so comparing them
    raw matches nothing at all.
    """
    return str(extract_family_from_phase_id(phase_id) or "").upper()


# --------------------------------------------------------------------------
# target matrix
# --------------------------------------------------------------------------
def target_cells() -> List[Tuple[str, str, str]]:
    """(family, shape, cell_key) for every cell the shipped floor covers."""
    out = []
    for fam, sides in FAMILY_SHAPES.items():
        for side in sides:
            shape = f"{side}x{side}x{side}"
            key = cell_key(fam, shape)
            if key:
                out.append((fam, shape, key))
    return sorted(out, key=lambda t: (t[0], int(t[1].split("x")[0])))


def manifest_cells() -> set:
    """Cells the shipped gfx900 manifest actually names, as a cross-check.

    The deck is built from FAMILY_SHAPES because that is what the report grades,
    but a family the manifest never shipped would be a silent over-reach, so it
    is worth being able to ask.
    """
    path = BASE / "gfx90c_results" / "gfx900_shipped_manifest.json"
    try:
        fam = json.loads(path.read_text()).get("families", {})
    except Exception:
        return set()
    return set(fam)


# --------------------------------------------------------------------------
# measurement inventory
# --------------------------------------------------------------------------
def native_runs(base: Path = BASE) -> List[str]:
    return sorted(d.name for d in (base / "gfx90c_runs").glob("run_*") if d.is_dir())


def floor_chain(base: Path = BASE) -> List[str]:
    drv = _driver(base)
    return [r for r in drv._reference_floor_runs(None)
            if (base / "gfx90c_runs" / r).is_dir()]


def source_chain(base: Path = BASE) -> List[str]:
    """The original measured floor runs, even after locking.

    ``reference_chain`` resolves to the locked floor once one exists, so feeding
    its result back into the lock would make the pipeline lock its own output and
    converge to a degenerate fixpoint. The locked run records where it came from,
    so the chain is recovered from there instead.
    """
    chain = floor_chain(base)
    if not chain or "_locked_" not in chain[0]:
        return chain
    con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    row = con.execute("SELECT metadata FROM runs WHERE run_id=?",
                      (chain[0],)).fetchone()
    con.close()
    try:
        src = list(json.loads(row[0]).get("source_runs") or [])
    except Exception:
        src = []
    return src or chain
