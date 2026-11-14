#!/usr/bin/env python3
"""The measurement inventory and the deck selected from it.

Owns: ``measured_index`` (every measured (phase, cell) with its stability count), ``load_deck`` (the whole solution universe: live deck + archived decks), ``dtype_bytes`` (read from Tensile itself), ``_is_legal`` (the three pre-run gates) and ``select_deck`` (best + sweep phase per target cell).
Does NOT own: the cells it selects for (consolidate_targets) or the installation of what it selected (consolidate_install).
Public API: measured_index, load_deck, dtype_bytes, _is_legal, select_deck, _median, _form_rank, _candidates."""

from __future__ import annotations

import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from oto import yamlio
from oto.device import loader as _loader
from oto.device.vocabulary import cell_key
from oto.metrics.ab_audit import (
    BASE as _AB_BASE,
)
from oto.metrics.ab_identity import _driver
from oto.metrics.ab_records import (
    _registry_records,
    phase_records,
)
from oto.metrics.analytics import extract_family_from_phase_id
from oto.runners.paths import runs_dir as _runs_dir
from oto.tools.consolidate_floor import PREFERRED_FORMS
from oto.tools.consolidate_targets import _fam, native_runs, target_cells

BASE = _AB_BASE

#: Read-only use of Tensile: dtype byte widths are read from its tables.
_TENSILE_ROOT = Path(os.environ.get("TENSILE_ROOT", "")) if os.environ.get("TENSILE_ROOT") else None

def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def measured_index(base: Path = BASE) -> dict[tuple[str, str], dict[str, Any]]:
    """Every (phase_id, cell_key) native measurement, with stability counts.

    GFLOPS for one phase/cell is the median across every run that measured it, so
    a phase that got lucky once does not outrank one that reproduced.
    """
    drv = _driver(base)
    per: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in native_runs(base):
        for rec in phase_records(drv, _runs_dir(base, _loader.current_profile().codename) / run, "native"):
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

    out: dict[tuple[str, str], dict[str, Any]] = {}
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


def load_deck(base: Path = BASE) -> list[dict[str, Any]]:
    """Every phase solution ever written to this repo, live deck included.

    Selection has to draw from the whole solution universe, not just the live
    deck. Reading only ``phases.yaml`` makes the pipeline non-idempotent: the
    consolidation writes a 45-phase deck, and re-running then has only those 45
    candidates to choose from, so the next pass collapses to 17 and cannot recover
    the solutions it just dropped. The archived decks under ``archive/`` are the
    record of everything that came before, so they are part of the pool. Live
    entries win on phase_id collision.
    """
    pool: dict[str, dict[str, Any]] = {}
    archived = sorted((base / "archive").glob("phases.yaml.*"))
    for path in [*archived, base / "phases.yaml"]:
        if not path.is_file():
            continue
        try:
            entries = yamlio.load_yaml(path) or []
        except Exception:
            continue
        for p in entries:
            if isinstance(p, dict) and p.get("phase_id"):
                pool[str(p["phase_id"])] = p
    return list(pool.values())


def _form_rank(forms: list[int]) -> int:
    """Lower is better: prefer the widest sweep, matching the floor."""
    known = [f for f in forms if f in PREFERRED_FORMS]
    if known:
        return min(known, key=lambda f: (PREFERRED_FORMS.index(f), -f))
    return len(PREFERRED_FORMS) + (min(forms) if forms else 0)


def dtype_bytes(char: str) -> int | None:
    """Bytes per element for a dtype char, read from Tensile itself.

    ``Tensile.DataType.DataType.properties`` is the authority: numBytes() is
    reg * 4. It is read here rather than from the modelled tables
    (``oto.device.loader.current_profile().family_bytes_per_element`` and
    ``oto.tensile.gates.loads.LOAD_DTYPE_INFO``) because this gate exists to
    cross-check those models rather than to copy them. The load gate's ``Z`` row
    once carried ComplexFloat's 8 bytes for complex double, which let VectorWidth
    2 through for ZZ and produced the ``GlobalLoadVectorWidthA *
    DataType.numBytes() > 16`` assembly rejects; reading the authority here is
    what catches such a drift instead of inheriting it.
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


def _is_legal(phase: dict[str, Any]) -> tuple[bool, str]:
    """Full pre-run legality gate for a deck phase.

    All three seams the candidate generator enforces, because each has caught a real
    failure in this corpus and none is redundant:

    * ``occupancy_feasible``  -- LDS footprint / VGPR budget
    * ``assembly_class_valid`` -- the four SolutionStructs classes
    * the global-load byte cap -- ``GLVW * bytesPerElement <= 16``

    The third is checked here against Tensile's own dtype table because
    ``occupancy_feasible`` and ``assembly_class_valid`` both pass ZZ VectorWidth 2,
    which Tensile rejects at assembly time with 20 empty phases and a wasted
    overnight run. ``python3 -m oto check candidates`` still misses it for the same reason.
    """
    cfg = phase.get("config") or {}
    try:
        from oto.tensile.gates.assembly import assembly_class_valid
        from oto.tensile.gates.occupancy import occupancy_feasible
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
        if b is not None and int(vw) * b > _loader.current_profile().global_load_byte_cap:
            return False, (
                f"reject: GlobalLoadVectorWidthA * DataType.numBytes() > 16 "
                f"(VectorWidth={vw} x {b}B for {dt} > {_loader.current_profile().global_load_byte_cap})")
    return True, ""


def _candidates(deck: list[dict[str, Any]], fam: str, shape: str,
                idx: dict[tuple[str, str], dict[str, Any]]
                ) -> list[dict[str, Any]]:
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


def select_deck(base: Path = BASE) -> dict[str, Any]:
    """Build deck from existing phases; keep best + sweep per cell. Illegal dropped."""
    deck = load_deck(base)
    idx = measured_index(base)
    by_pid = {str(p.get("phase_id")): p for p in deck}
    legality: dict[str, str] = {}

    picks: dict[str, dict[str, Any]] = {}
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


# --------------------------------------------------------------------------
