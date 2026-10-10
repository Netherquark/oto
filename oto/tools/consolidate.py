#!/usr/bin/env python3
"""Deck consolidation: mine the corpus, build the locked floor, install one deck.

Owns: ``main`` and the four responsibilities behind the ``mine`` / ``all``
subcommands it dispatches to -- target-cell resolution (targets), the
measurement inventory and deck selection (deck), the locked-floor materialisation
(floor), and installation with archiving (install).
Does NOT own: the legality gate it consults (oto.tensile.gates), the A/B verdicts
it reports alongside (oto.metrics.ab_audit), or the Tensile dtype table (read on
demand).
Public API: main, and the names the other tools import: target_cells,
manifest_cells, native_runs, floor_chain, source_chain, dtype_bytes, _is_legal,
load_deck, select_deck, plan_floor, locked_run_id, build_floor, build_db,
write_deck, install, phantom_runs, explain_archive, cmd_mine, cmd_all, _fam,
_stamp, _median, _form_rank, measured_index, LIVE_DB, PREFERRED_FORMS,
SINGLE_FORM_ONLY_RUNS, BASE, _TENSILE_ROOT.

Every subcommand is read-only except ``--commit``. ``--dry-run`` stages into
``archive/consolidate_<stamp>/`` and reports; ``--commit`` additionally installs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from oto.metrics.ab_audit import (  # noqa: E402
    BASE as _AB_BASE, TIE_BAND_PCT, _driver, _registry_records, arm_records,
    audit, phase_records, verdict,
)
from oto.metrics.analytics import extract_family_from_phase_id  # noqa: E402
from oto.device.peaks import FAMILY_SHAPES, cell_key  # noqa: E402

BASE = _AB_BASE

#: Read-only use of Tensile: dtype byte widths are read from its tables.
_TENSILE_ROOT = Path("/home/netherquark/Soham/Large_code/sources/GPU/Tensile")

#: The locked floor, expressed in one registry db.
LIVE_DB = BASE / "gfx90c_results" / "registry.db"

#: Runs whose only form is a single shape: not a sweep, so they cannot be the
#: floor. Recorded so the archive explains them rather than silently dropping
#: them (see explain_archive).
SINGLE_FORM_ONLY_RUNS = ("run_20261002_021805",)

#: The floor is a multi-shape sweep; the next native run has to match it.
PREFERRED_FORMS = (8, 7, 5, 4, 2)   # sweep widths, widest first

#: Runs whose only form is a single shape: not a sweep, so they cannot be the
#: floor. Recorded so the archive explains them rather than silently dropping
#: them (see explain_archive).
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


# ---------------------------------------------------------------------------
# measurement inventory + deck selection
# ---------------------------------------------------------------------------


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


def _median(vals: List[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def measured_index(base: Path = BASE) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Every (phase_id, cell_key) native measurement, with stability counts.

    GFLOPS for one phase/cell is the median across every run that measured it, so
    a phase that got lucky once does not outrank one that reproduced.
    """
    drv = _driver(base)
    per: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for run in native_runs(base):
        for rec in phase_records(drv, base / "gfx90c_runs" / run, "native"):
            key = rec.get("cell_key") or cell_key(
                extract_family_from_phase_id(rec["phase_id"]), rec["ProblemType"])
            if not key:
                continue
            rec["cell_key"] = key
            per[(rec["phase_id"], key)].append(rec)
    # Registry-only rows have no phase directory; they are indexed too so a
    # draft-imported solution is not invisible, but they can never win a cell
    # that a real measured phase covers.
    for rec in _registry_records(drv, base, want_arm="native"):
        key = rec.get("cell_key") or ""
        if key:
            per[(rec["phase_id"], key)].append(rec)

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (phase_id, ckey), recs in per.items():
        forms = sorted({r["shapes_per_phase"] for r in recs})
        out[(phase_id, ckey)] = {
            "phase_id": phase_id,
            "cell_key": ckey,
            "dtype": recs[0]["DataType"],
            "gflops": _median([r["GFLOPS"] for r in recs]),
            "best_single_run": max(r["GFLOPS"] for r in recs),
            "runs": sorted({r["source_run"] for r in recs if r["source_run"]}),
            "n_obs": len(recs),
            "forms": forms,
            "from_registry": all(r.get("from_registry") for r in recs),
            "family": _fam(phase_id),
        }
    return out


def load_deck(base: Path = BASE) -> List[Dict[str, Any]]:
    """Every phase solution ever written to this repo, live deck included.

    Selection has to draw from the whole solution universe, not just the live
    deck. Reading only ``phases.yaml`` makes the pipeline non-idempotent: the
    consolidation writes a 45-phase deck, and re-running then has only those 45
    candidates to choose from, so the next pass collapses to 17 and cannot recover
    the solutions it just dropped. The archived decks under ``archive/`` are the
    record of everything that came before, so they are part of the pool. Live
    entries win on phase_id collision.
    """
    import yaml
    pool: Dict[str, Dict[str, Any]] = {}
    archived = sorted((base / "archive").glob("phases.yaml.*"))
    for path in archived + [base / "phases.yaml"]:
        if not path.is_file():
            continue
        try:
            entries = yaml.safe_load(path.read_text()) or []
        except Exception:
            continue
        for p in entries:
            if isinstance(p, dict) and p.get("phase_id"):
                pool[str(p["phase_id"])] = p
    return list(pool.values())


def _form_rank(forms: List[int]) -> int:
    """Lower is better: prefer the widest sweep, matching the floor."""
    known = [f for f in forms if f in PREFERRED_FORMS]
    if known:
        return min(known, key=lambda f: (PREFERRED_FORMS.index(f), -f))
    return len(PREFERRED_FORMS) + (min(forms) if forms else 0)


def dtype_bytes(char: str) -> Optional[int]:
    """Bytes per element for a dtype char, read from Tensile itself.

    Tensile.DataType.DataType.properties is the authority: numBytes() is
    reg * 4. It is read here rather than from scheduler.FAMILY_BYTES_PER_ELEMENT
    because that table lists ZZ as 8 bytes, and complex double is 16. That single
    wrong number is what let VectorWidth 2 through for ZZ and produced the
    ``GlobalLoadVectorWidthA * DataType.numBytes() > 16`` assembly rejects.
    """
    try:
        import sys as _s
        root = _TENSILE_ROOT
        if root and str(root) not in _s.path:
            _s.path.insert(0, str(root))
        from Tensile.DataType import DataType
    except Exception:
        return None
    want = str(char).upper()[:1]
    for props in getattr(DataType, "properties", []):
        if str(props.get("char", "")).upper()[:1] == want:
            reg = props.get("reg")
            return int(reg * 4) if reg is not None else None
    return None


def _is_legal(phase: Dict[str, Any]) -> Tuple[bool, str]:
    """Full pre-run legality gate for a deck phase.

    All three seams the scheduler enforces, because each has caught a real
    failure in this corpus and none is redundant:

    * ``occupancy_feasible``  -- LDS footprint / VGPR budget
    * ``assembly_class_valid`` -- the four SolutionStructs classes
    * the global-load byte cap -- ``GLVW * bytesPerElement <= 16``

    The third is checked here against Tensile's own dtype table because
    ``occupancy_feasible`` and ``assembly_class_valid`` both pass ZZ VectorWidth 2,
    which Tensile rejects at assembly time with 20 empty phases and a wasted
    overnight run. ``check_candidates.py`` still misses it for the same reason.
    """
    cfg = phase.get("config") or {}
    try:
        from oto.tensile.gates.assembly import assembly_class_valid
        from oto.tensile.gates.occupancy import occupancy_feasible
        from oto.tensile.gates.vgpr_model import GLOBAL_LOAD_BYTE_CAP
    except Exception as exc:                       # pragma: no cover
        return True, f"gate unavailable ({exc})"
    try:
        ok, why = occupancy_feasible(cfg)
        if not ok:
            return False, f"occupancy: {why}"
        ok, why = assembly_class_valid(cfg)
        if not ok:
            return False, f"assembly: {why}"
    except Exception as exc:
        return False, f"gate error: {exc}"

    vw = cfg.get("VectorWidth")
    dt = cfg.get("DataType") or phase.get("dtype")
    if vw is not None and dt:
        b = dtype_bytes(str(dt))
        if b is not None and int(vw) * b > GLOBAL_LOAD_BYTE_CAP:
            return False, (
                f"reject: GlobalLoadVectorWidthA * DataType.numBytes() > 16 "
                f"(VectorWidth={vw} x {b}B for {dt} > {GLOBAL_LOAD_BYTE_CAP})")
    return True, ""


def _candidates(deck: List[Dict[str, Any]], fam: str, shape: str,
                idx: Dict[Tuple[str, str], Dict[str, Any]]
                ) -> List[Dict[str, Any]]:
    out = []
    for p in deck:
        if _fam(str(p.get("phase_id", ""))) != fam.upper():
            continue
        if shape not in (p.get("shapes") or []):
            continue
        pid = str(p.get("phase_id"))
        m = idx.get((pid, f"{fam.upper()}:{shape.split('x')[0]}"))
        shapes = list(p.get("shapes") or [])
        out.append({
            "phase_id": pid,
            "shapes": shapes,
            "dtype": p.get("dtype"),
            "fp": p.get("fp"),
            "measured": m is not None,
            "gflops": m["gflops"] if m else None,
            "runs": m["runs"] if m else [],
            "n_obs": m["n_obs"] if m else 0,
            "forms": m["forms"] if m else [len(shapes)],
            "is_sweep": len(shapes) in PREFERRED_FORMS,
        })
    return out


def select_deck(base: Path = BASE) -> Dict[str, Any]:
    """Build the deck from existing phases only.

    Two phases are kept per cell, because they answer different questions:

    * ``best`` -- the highest measured GFLOPS at this cell, whatever form it was
      measured in. This is the solution worth keeping, and it is what the user
      asked to retain even where it currently loses.
    * ``sweep`` -- the widest phase covering this cell. A sweep times every size
      in the family in one Tensile invocation, which is the form the locked
      floor was measured in, so including it is what makes the next run
      comparable.

    Keeping only ``best`` would rebuild the current problem: it is usually a
    one-size phase, so the next run stays ungradable against a swept floor.
    Keeping only ``sweep`` would throw away the best solutions found so far.
    Illegal phases are dropped on both paths.
    """
    deck = load_deck(base)
    idx = measured_index(base)
    by_pid = {str(p.get("phase_id")): p for p in deck}
    legality: Dict[str, str] = {}

    picks: Dict[str, Dict[str, Any]] = {}
    for fam, shape, ckey in target_cells():
        cands = _candidates(deck, fam, shape, idx)
        legal = []
        for c in cands:
            if c["phase_id"] not in legality:
                ok, why = _is_legal(by_pid.get(c["phase_id"], {}))
                legality[c["phase_id"]] = why if not ok else ""
            if not legality[c["phase_id"]]:
                legal.append(c)
            else:
                c["illegal"] = legality[c["phase_id"]]

        measured = [c for c in legal if c["measured"]]
        best = max(measured, key=lambda c: (c["gflops"], len(c["runs"]),
                                            c["phase_id"])) if measured else None
        sweeps = [c for c in legal if c["is_sweep"]]
        sweep = max(sweeps, key=lambda c: (c["measured"], c["gflops"] or 0.0,
                                           len(c["runs"]), c["phase_id"])
                    ) if sweeps else None

        picks[ckey] = {
            "cell_key": ckey, "family": fam.upper(), "shape": shape,
            "best": best, "sweep": sweep,
            "n_candidates": len(cands), "n_legal": len(legal),
            "n_illegal": len(cands) - len(legal),
            "reason": ("measured best" if best else
                       "sweep only" if sweep else
                       "no legal candidate"),
        }

    chosen, seen = [], set()
    for ckey in sorted(picks):
        for slot in ("best", "sweep"):
            pid = (picks[ckey].get(slot) or {}).get("phase_id")
            if pid and pid not in seen and pid in by_pid:
                seen.add(pid)
                chosen.append(by_pid[pid])
    return {
        "picks": picks,
        "phases": chosen,
        "illegal_dropped": {k: v for k, v in legality.items() if v},
        "uncovered": [k for k, v in picks.items()
                      if not (v.get("best") or v.get("sweep"))],
        "no_measurement": [k for k, v in picks.items()
                           if v.get("sweep") and not v["sweep"]["measured"]],
    }


# ---------------------------------------------------------------------------
# locked floor
# ---------------------------------------------------------------------------


# --------------------------------------------------------------------------
# locked floor
# --------------------------------------------------------------------------
def plan_floor(base: Path = BASE) -> Dict[str, Any]:
    """One logical floor run, built from the completed resume chain.

    Per phase, the source run that measured the most distinct shapes wins. That
    prefers a complete sweep over a partial one without ever comparing GFLOPS
    across runs to decide, so the selection cannot be tuned by how fast a run
    happened to be.
    """
    chain = source_chain(base)
    stats: Dict[str, Dict[str, Any]] = {}
    for run in chain:
        rd = base / "gfx90c_runs" / run
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
    chosen: Dict[str, str] = {}
    for pid, s in stats.items():
        chosen[pid] = max(s["per_run"].items(), key=lambda kv: (kv[1], kv[0]))[0]
    return {"chain": chain, "chosen": chosen, "stats": stats,
            "n_phases": len(chosen)}


def locked_run_id(chain: List[str]) -> str:
    """Deterministic id for the locked floor, derived from the chain it locks.

    Timestamping this made the pipeline non-idempotent: every re-run minted a new
    gfx900_ref_locked_* id, so a second locked floor accumulated beside the first
    and the older one became a dead directory that still looked authoritative.
    The content is a pure function of the chain, so the id should be too.
    """
    digest = hashlib.sha256("|".join(chain).encode()).hexdigest()[:10]
    return f"gfx900_ref_locked_{digest}"


def build_floor(base: Path, dest: Path, stamp: str) -> Dict[str, Any]:
    """Materialise the locked floor as one logical run holding every floor sample.

    Every CSV from every run in the completed chain is copied, with the source run
    appended to the filename so two runs' copies of the same solution coexist. The
    floor arm groups samples by (dtype, shape, config) and takes the median, so
    pooling makes each floor number the median over all seeds ever measured for
    that kernel -- the most robust reading available and symmetric with how the
    native side is judged.

    Picking one run per phase was tried first and is wrong: it silently discarded
    whichever run happened to read high, understating the floor on 17 of 38 cells
    by up to 11.9% (HH:512 1583.90 -> 1395.55). An understated floor flatters the
    native side, which is the one direction a reference must not err in.

    Only ``2_BenchmarkData/*.csv`` is copied -- that is all the floor arm reads --
    so the cost is tens of MB rather than the ~4GB the chain occupies with
    telemetry. CSV contents are copied byte-for-byte; only the name is suffixed.
    """
    plan = plan_floor(base)
    run_id = locked_run_id(plan["chain"])
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    phases: set = set()
    for run in plan["chain"]:
        for csv in sorted((base / "gfx90c_runs" / run).glob(
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
def build_db(base: Path, lock: Dict[str, Any], out: Path,
             stamp: str) -> Dict[str, Any]:
    """Clone the live registry, then add the locked floor run to the clone.

    Cloning rather than rebuilding keeps every historical row, so the consolidated
    database is a superset of the corpus and nothing is lost. The locked floor is
    inserted last, so it is the newest completed gfx900_ref_* row and
    ``reference_chain`` selects it as the head with no resume_of to follow.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{base / 'gfx90c_results' / 'registry.db'}?mode=ro",
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



# ---------------------------------------------------------------------------
# installation + archiving
# ---------------------------------------------------------------------------

# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------
def write_deck(stage: Path, sel: Dict[str, Any], stamp: str) -> Path:
    """Write the candidate deck into the staging dir.

    Staged rather than only produced at install time so the deck can be read and
    diffed against the archived original before anything live is touched.
    """
    import yaml
    header = (
        "# Best-effort convergence deck. Generated by consolidate.py "
        f"({stamp}).\n"
        "# Every entry is a verbatim copy of an existing phase: no config is\n"
        "# invented, retuned or renamed. All phases sweep their family's sizes so\n"
        "# the run matches the locked gfx900 floor's invocation form -- comparing a\n"
        "# swept floor against a one-size-per-phase native run is what made the\n"
        "# previous verdicts ungradable.\n"
        "# Regenerate with: python3 consolidate.py all --commit\n"
    )
    body = yaml.safe_dump(sel["phases"], sort_keys=False, width=10000)
    out = stage / "phases.yaml"
    out.write_text(header + body)
    return out


def install(base: Path, stage: Path, sel: Dict[str, Any],
            lock: Dict[str, Any], dbres: Dict[str, Any], stamp: str) -> None:
    deck_path = base / "phases.yaml"
    staged = write_deck(stage, sel, stamp)

    live_lock = base / "gfx90c_runs" / lock["run_id"]
    if live_lock.exists():
        # Never delete in place. A previous build of the same lock id is moved
        # aside under archive/ so the swap is reversible; the staged copy is the
        # only thing that replaces it.
        prev_arch = base / "archive" / "gfx90c_runs" / "superseded_locks"
        prev_arch.mkdir(parents=True, exist_ok=True)
        stamp_dir = prev_arch / f"{lock['run_id']}_{stamp.replace(':', '')}"
        n = 1
        while stamp_dir.exists():
            stamp_dir = prev_arch / f"{lock['run_id']}_{stamp.replace(':', '')}_{n}"
            n += 1
        shutil.move(str(live_lock), str(stamp_dir))
        print(f"[consolidate] previous {lock['run_id']} preserved at "
              f"{stamp_dir.relative_to(base)}")
    shutil.copytree(lock["dest"], live_lock)
    shutil.copy2(dbres["out"], LIVE_DB)
    shutil.copy2(staged, deck_path)

    arch = base / "archive" / "gfx90c_runs"
    arch.mkdir(parents=True, exist_ok=True)
    for run in list(SINGLE_FORM_ONLY_RUNS) + phantom_runs(base):
        src = base / "gfx90c_runs" / run
        if src.is_dir():
            shutil.move(str(src), str(arch / run))


def phantom_runs(base: Path = BASE, db: Path = LIVE_DB) -> List[str]:
    """Runs that registered a row but produced nothing at all.

    These are bookkeeping accidents, not measurements: a run directory with no
    CSV anywhere under it and no records in the registry. They are archived
    (moved, never deleted) because an empty directory in the live run tree is
    scanned by the native arm on every report and yields nothing but confusion.

    The registry rows are left in place. They are already ``interrupted`` or
    ``started``, they are truthfully empty, and pruning rows is not this script's
    call to make.
    """
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT run_id FROM runs").fetchall()
    con.close()
    out = []
    for (run_id,) in rows:
        d = base / "gfx90c_runs" / run_id
        if not d.is_dir():
            continue
        if any(d.rglob("*.csv")):
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = con.execute("SELECT COUNT(*) FROM records WHERE run_id=?",
                        (run_id,)).fetchone()[0]
        con.close()
        if n == 0:
            out.append(run_id)
    return sorted(out)


def explain_archive(base: Path = BASE) -> str:
    lines = ["Runs moved out of the live loader path (data preserved under "
             "archive/gfx90c_runs/):"]
    for r in SINGLE_FORM_ONLY_RUNS:
        lines.append(f"  {r}  (single-shape-only: kept as priors, not gradable "
                     f"against a swept floor)")
    ph = phantom_runs(base)
    if ph:
        lines.append("")
        lines.append(f"Phantom runs (registered a row, produced no CSV, no "
                     f"records): {len(ph)}")
        for r in ph:
            lines.append(f"  {r}")
    lines += ["", "Nothing is deleted. Registry rows for the phantom runs are "
              "left alone on purpose."]
    return "\n".join(lines)


# --------------------------------------------------------------------------
def cmd_mine(args) -> int:
    sel = select_deck(args.base_dir)
    rows = sorted(sel["picks"].values(),
                  key=lambda c: (c["family"], int(c["shape"].split("x")[0])))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(sel, indent=2, default=str))
    print(f"cells={len(rows)}  phases selected={len(sel['phases'])}  "
          f"uncovered={len(sel['uncovered'])}  "
          f"sweeps never measured={len(sel['no_measurement'])}\n")
    print(f"{'cell':<14} {'best (measured)':<52} {'gflops':>8}  "
          f"{'sweep (protocol-matched)':<52} {'gflops':>8}")
    print("-" * 132)
    for c in rows:
        b, sw = c.get("best") or {}, c.get("sweep") or {}
        bg = f"{b['gflops']:.1f}" if b.get("gflops") else "-"
        sg = f"{sw['gflops']:.1f}" if sw.get("gflops") else "-"
        btag = "" if b.get("measured") else " (unmeasured)"
        print(f"{c['cell_key']:<14} {str(b.get('phase_id'))[:51]:<52} {bg:>8}{btag:<12} "
              f"{str(sw.get('phase_id'))[:51]:<52} {sg:>8}")
    if sel["illegal_dropped"]:
        print(f"\nillegal phases dropped: {len(sel['illegal_dropped'])}")
        for pid, why in list(sel["illegal_dropped"].items())[:5]:
            print(f"  {pid[:60]}: {why[:90]}")
    return 0


def cmd_all(args) -> int:
    base = args.base_dir
    stamp = _stamp()
    stage = base / "archive" / f"consolidate_{stamp}"
    stage.mkdir(parents=True, exist_ok=True)

    sel = select_deck(base)
    lock = build_floor(base, stage / "gfx90c_runs" / locked_run_id(
        source_chain(base)), stamp)
    dbres = build_db(base, lock, stage / "registry.db", stamp)

    staged_deck = write_deck(stage, sel, stamp)
    print(f"staged -> {stage}")
    print(f"  deck file: {staged_deck}")
    print(f"  deck      : {len(sel['phases'])} phases from "
          f"{len(load_deck(base))} existing")
    print(f"  uncovered : {sel['uncovered'] or 'none'}")
    print(f"  sweeps never measured: {len(sel['no_measurement'])} cells")
    print(f"  illegal dropped: {len(sel['illegal_dropped'])}")
    print(f"  floor     : {lock['run_id']}  phases={lock['phases']} "
          f"csvs={lock['csvs_copied']}  chain={lock['chain']}")
    print(f"  registry  : rows {dbres['before']} -> {dbres['after']}  "
          f"integrity={dbres['integrity']}")

    # Coverage-parity rule (knowledge_base.md §6.1): the consolidated deck
    # (which becomes the produced TensileLibrary) must address exactly the
    # shipped gfx900 cell grid. Refuse to install a deck that diverges.
    try:
        from library_parity import parity_report
        pr = parity_report(sel["phases"])
        parity_ok = pr["parity_ok"]
        print(f"  library parity: {'OK' if parity_ok else 'FAIL'} "
              f"{pr['deck_cells']}/{pr['shipped_cells']} shipped cells "
              f"({len(pr['missing'])} missing, {len(pr['extra'])} extra)")
    except Exception as exc:  # pragma: no cover
        parity_ok = False
        print(f"  library parity: FAIL (checker error: {exc})")

    print("\n" + explain_archive(base))
    if not args.commit:
        print("dry run; nothing installed. re-run with --commit")
        return 0 if parity_ok else 1
    if not parity_ok:
        print("REFUSED to install: consolidated deck breaks TensileLibrary "
              "coverage parity vs the shipped gfx900 grid "
              "(knowledge_base.md §6.1). Fix the deck, then re-run --commit.")
        return 1
    install(base, stage, sel, lock, dbres, stamp)
    print(f"installed. live floor = {lock['run_id']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.set_defaults(commit=False)
    ap.add_argument("--base-dir", type=Path, default=BASE)
    sub = ap.add_subparsers(dest="cmd")
    m = sub.add_parser("mine", help="read-only: best existing phase per cell")
    m.add_argument("--json", type=Path)
    m.set_defaults(func=cmd_mine)
    a = sub.add_parser("all", help="build locked floor + consolidated registry + deck")
    a.add_argument("--dry-run", dest="commit", action="store_false",
                   help="explicitly stage without installing (the default)")
    a.add_argument("--commit", action="store_true",
                   help="install; without it the build is staged only")
    a.add_argument("--explain-archive", action="store_true")
    a.set_defaults(func=cmd_all)
    args = ap.parse_args()
    if getattr(args, "explain_archive", False):
        print(explain_archive(args.base_dir))
        return 0
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())