#!/usr/bin/env python3
"""The locked floor: plan it, materialise it, clone the registry under it.

Owns: ``plan_floor`` (which runs form one logical floor), ``locked_run_id`` (the deterministic id a chain pins to), ``build_floor`` (pool the chain's CSVs into one run dir) and ``build_db`` (clone the live registry and insert the locked-floor run).
Does NOT own: the deck selected for the next native run (consolidate_deck) or the cells the floor must cover (consolidate_targets).
Public API: plan_floor, locked_run_id, build_floor, build_db, PREFERRED_FORMS, SINGLE_FORM_ONLY_RUNS. (``LIVE_DB`` lives in oto.tools.consolidate_targets.)"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from oto.device import loader as _loader
from oto.metrics.ab_audit import BASE as _AB_BASE
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import runs_dir as _runs_dir
from oto.tools.consolidate_targets import source_chain

BASE = _AB_BASE

#: Read-only use of Tensile: dtype byte widths are read from its tables.
#: The floor is a multi-shape sweep; the next native run has to match it.
PREFERRED_FORMS = (8, 7, 5, 4, 2)   # sweep widths, widest first

#: Runs whose only form is a single shape: not a sweep, so they cannot be the
#: floor. Recorded so the archive explains them rather than silently dropping
#: them (see explain_archive).
SINGLE_FORM_ONLY_RUNS = ("run_20261002_021805",)

def plan_floor(base: Path = BASE, profile=None) -> dict[str, Any]:
    """One logical floor run, built from the completed resume chain.

    Per phase, the source run that measured the most distinct shapes wins. That
    prefers a complete sweep over a partial one without ever comparing GFLOPS
    across runs to decide, so the selection cannot be tuned by how fast a run
    happened to be.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    chain = source_chain(base, profile=profile,)
    stats: dict[str, dict[str, Any]] = {}
    for run in chain:
        rd = _runs_dir(base, _loader.resolve_profile(profile,).codename) / run
        for csv in rd.glob("phase_*/2_BenchmarkData/*.csv"):
            pid = csv.parent.parent.name
            try:
                with csv.open() as fh:
                    shapes = {ln.split(",")[1].strip()
                              for ln in fh.readlines()[1:] if ln.count(",") > 3}
            except Exception:
                continue
            s = stats.setdefault(pid, {"pid": pid, "per_run": {}})
            s["per_run"][run] = len(shapes)
    chosen: dict[str, str] = {}
    for pid, s in stats.items():
        chosen[pid] = max(s["per_run"].items(), key=lambda kv: (kv[1], kv[0]))[0]
    return {"chain": chain, "chosen": chosen, "stats": stats,
            "n_phases": len(chosen)}


def locked_run_id(chain: list[str]) -> str:
    """Deterministic id for the locked floor, derived from the chain it locks.

    Timestamping this made the pipeline non-idempotent: every re-run minted a new
    gfx900_ref_locked_* id, so a second locked floor accumulated beside the first
    and the older one became a dead directory that still looked authoritative.
    The content is a pure function of the chain, so the id should be too.
    """
    digest = hashlib.sha256("|".join(chain).encode()).hexdigest()[:10]
    return f"gfx900_ref_locked_{digest}"


def build_floor(base: Path, dest: Path, stamp: str, profile=None) -> dict[str, Any]:
    """Materialise the locked floor as one logical run holding every floor sample.

    Every CSV from every run in the completed chain is copied, with the source run
    appended to the filename so two runs' copies of the same solution coexist. The
    floor arm groups samples by (dtype, shape, config) and takes the median, so
    pooling makes each floor number the median over all seeds ever measured for
    that kernel -- the most robust reading available and symmetric with how the
    native side is judged.

    Picking one run per phase was tried first and is wrong: it silently discarded
    whichever run happened to read high, understating the floor on the affected
    cells (e.g. HH:512). An understated floor flatters the
    native side, which is the one direction a reference must not err in.

    Only ``2_BenchmarkData/*.csv`` is copied -- that is all the floor arm reads --
    so the cost is tens of MB rather than the ~4GB the chain occupies with
    telemetry. CSV contents are copied byte-for-byte; only the name is suffixed.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    plan = plan_floor(base, profile=profile,)
    run_id = locked_run_id(plan["chain"])
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    phases: set = set()
    for run in plan["chain"]:
        for csv in sorted((_runs_dir(base, _loader.resolve_profile(profile,).codename) / run).glob(
                "phase_*/2_BenchmarkData/*.csv")):
            pid = csv.parent.parent.name
            out = dest / pid / "2_BenchmarkData"
            out.mkdir(parents=True, exist_ok=True)
            phases.add(pid)
            # Same solution, same Tensile filename, different run: suffix the
            # source run so the copies accumulate instead of overwriting.
            target = out / f"{csv.stem}__{run}{csv.suffix}"
            if not target.exists():
                shutil.copy2(csv, target)
                copied += 1
    meta = {
        "gfx900_reference": True,
        "smoke": False,
        "locked": True,
        "shipped_kernels": 2285,
        "phases_executed": len(phases),
        "source_runs": plan["chain"],
        "source": ("consolidate.py lock: every chain CSV pooled byte-for-byte; "
                   "floor values are medians over all pooled seeds"),
    }
    return {"run_id": run_id, "dest": dest, "chain": plan["chain"],
            "csvs_copied": copied, "phases": len(phases), "metadata": meta}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
def build_db(base: Path, lock: dict[str, Any], out: Path,
             stamp: str, profile=None) -> dict[str, Any]:
    """Clone the live registry, then add the locked floor run to the clone.

    Cloning rather than rebuilding keeps every historical row, so the consolidated
    database is a superset of the corpus and nothing is lost. The locked floor is
    inserted last, so it is the newest completed gfx900_ref_* row and
    ``reference_chain`` selects it as the head with no resume_of to follow.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{_results_dir(base, _loader.resolve_profile(profile,).codename) / 'registry.db'}?mode=ro",
                          uri=True)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()

    before = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("runs", "phases", "records")}
    now = datetime.now().isoformat()
    # Idempotent rebuild: drop this logical run's own rows before re-inserting.
    # Scoped to the locked run_id, so no other run's history is touched.
    dst.execute("DELETE FROM records WHERE run_id=?", (lock["run_id"],))
    dst.execute("DELETE FROM runs WHERE run_id=?", (lock["run_id"],))
    dst.execute(
        "INSERT INTO runs (run_id,status,metadata,started_at,completed_at) "
        "VALUES (?,?,?,?,?)",
        (lock["run_id"], "completed", json.dumps(lock["metadata"]), now, now))
    run_id = lock["run_id"]
    for pid in sorted(p.name for p in (lock["dest"]).glob("phase_*")):
        shapes = []
        cs = sorted((lock["dest"] / pid / "2_BenchmarkData").glob("*.csv"))
        if cs:
            with cs[0].open() as fh:
                shapes = sorted({ln.split(",")[1].strip()
                                 for ln in fh.readlines()[1:] if ln.count(",") > 3})
        dst.execute(
            "INSERT INTO records (run_id,record_type,data,timestamp) VALUES (?,?,?,?)",
            (run_id, "general", json.dumps({
                "run_id": run_id, "phase_id": pid, "label": pid,
                "dtype": "s", "shapes": shapes, "schedule_name": "vega10",
                "num_benchmarks": 8, "status": "completed", "arm": "spoof",
                "timestamp": now,
            }), now))
    after = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("runs", "phases", "records")}
    dst.commit()
    integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    return {"out": out, "before": before, "after": after, "integrity": integrity}
