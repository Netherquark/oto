"""Agent-facing harness tools: corpus study, candidate proposal, CPU-gate verification.

Owns: the deterministic tool functions an agent can call to study the measured
kernel-db corpus and the candidate pipeline. No GPU, no Tensile subprocess,
no network — everything here is CPU-only and safe to run during doc generation.
Does NOT own: the convergence ledger (oto.ledger), the deck emission
(oto.tensile.candidate), benchmarking, or rendering of the tuning reports.
Public API: study_kernel_db, propose_candidates, verify_candidates,
build_harness_study.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from oto.device.profile import DeviceProfile
from oto.harness.candidate_overlay import _round_robin_prune
from oto.harness.candidate_pool import iter_candidates
from oto.harness.candidate_rows import TARGET_CELLS
from oto.harness.cell_knob_diff import _side, _winner_per_cell
from oto.tensile.gates.loads import validate_tensile_loads
from oto.tensile.gates.occupancy import occupancy_feasible, ldspad_feasible
from oto.runners.paths import results_rel

KERNEL_DB_RELPATH = Path(results_rel("analysis", "kernel_db.json"))

_H_NOTE = ("Proposals are CPU-gate-checked models only. They still need GPU "
           "feedback (benchmark + accept/reject) before any of them can ship.")


def _target_cells() -> set:
    return {(fam, side) for fam, sides in TARGET_CELLS.items() for side in sides}


def study_kernel_db(base_dir) -> Dict[str, Any]:
    """Census of the measured corpus: runs, native rows, per-family counts,
    TARGET_CELLS coverage, and the native winner per (family, side)."""
    path = Path(base_dir) / KERNEL_DB_RELPATH
    if not path.exists():
        return {"present": False, "runs": 0, "rows": 0, "floor_rows": 0,
                "families": {}, "winners": {},
                "covered_cells": 0, "target_cells": len(_target_cells())}
    db = json.loads(path.read_text())
    target = _target_cells()
    native: List[Dict[str, Any]] = []
    floor = 0
    for run_id, rows in db.items():
        if str(run_id).startswith("gfx900_ref"):
            floor += len(rows)
        else:
            native.extend(rows)
    families = Counter(r.get("family") for r in native if r.get("family"))
    present = {(r.get("family"), _side(r.get("shape"))) for r in native}
    present = {cell for cell in present if cell[0] and cell[1] is not None}
    winners = _winner_per_cell(native)
    return {"present": True, "runs": len(db), "rows": len(native),
            "floor_rows": floor,
            "families": dict(sorted(families.items())),
            "winners": {f"{fam}:{side}": {"phase": w.get("phase"),
                                          "gflops_median": w.get("gflops_median")}
                        for (fam, side), w in sorted(winners.items())},
            "covered_cells": len(target & present),
            "target_cells": len(target)}


def propose_candidates(base_dir, limit: int = 16) -> List[Dict[str, Any]]:
    """Gate-verified pool rows (the same generator the seed overlay uses),
    round-robin pruned to ``limit`` so big families can't starve the HPA
    families. CPU-only. The pool is generated from the active profile."""
    pool = list(iter_candidates())
    return _round_robin_prune(pool, limit)


def verify_candidates(rows: List[Dict[str, Any]],
                      profile: Optional[DeviceProfile] = None) -> List[Dict[str, Any]]:
    """Re-check each proposed row against the CPU gates (loads, occupancy,
    ldspad). Independent of the emission-time check; no GPU involved."""
    verified: List[Dict[str, Any]] = []
    for row in rows:
        cfg = row.get("config") or {}
        ok_l, msg_l = validate_tensile_loads(cfg, profile=profile)
        ok_o, msg_o = occupancy_feasible(cfg, profile=profile)
        ok_s, msg_s = ldspad_feasible(cfg, profile=profile)
        verified.append({**row, "verification": {
            "passed": bool(ok_l and ok_o and ok_s),
            "loads": msg_l, "occupancy": msg_o, "ldspad": msg_s}})
    return verified


def _row_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"label": row.get("label"), "tier": row.get("tier"),
            "family": (row.get("config") or {}).get("FamilyLabel"),
            "contraction_pattern": row.get("contraction_pattern"),
            "shapes": row.get("shapes"), "verification": row.get("verification")}


def build_harness_study(base_dir, profile: DeviceProfile,
                        proposal_limit: int = 16) -> Dict[str, Any]:
    """Study the corpus, propose + verify candidates, return the payload plus
    a markdown section the doc generator can embed."""
    try:
        corpus = study_kernel_db(base_dir)
        rows = verify_candidates(propose_candidates(base_dir, limit=proposal_limit),
                                 profile=profile)
        passed = sum(1 for r in rows if r["verification"]["passed"])
        payload: Dict[str, Any] = {"status": "success", "profile": profile.codename,
                                   "corpus": corpus,
                                   "proposed": len(rows), "passed": passed,
                                   "proposals": [_row_summary(r) for r in rows]}
        payload["markdown"] = _study_markdown(profile, payload)
        return payload
    except Exception as exc:  # the agent path must never crash doc generation
        return {"status": "failed", "profile": profile.codename, "error": str(exc),
                "markdown": (f"## Harness study — {profile.codename}\n\n"
                             f"Harness study failed: {exc}\n")}


def _study_markdown(profile: DeviceProfile, payload: Dict[str, Any]) -> str:
    corpus = payload["corpus"]
    lines = [f"## Harness study — {profile.codename}", ""]
    if not corpus["present"]:
        lines.append("- corpus: no kernel_db.json (fresh device — candidates were "
                     "checked against the CPU model only)")
    else:
        lines.append(f"- runs: {corpus['runs']}  native rows: {corpus['rows']}  "
                     f"floor rows: {corpus['floor_rows']}")
        lines.append(f"- TARGET_CELLS coverage: {corpus['covered_cells']}/{corpus['target_cells']}")
        lines.append("- per-family rows: " + ", ".join(
            f"{k}: {v}" for k, v in corpus["families"].items()))
        if corpus["winners"]:
            lines += ["", "### Native winners (by gflops_median)"]
            lines += [f"- {cell}: {w['gflops_median']} GFLOP/s — {w['phase']}"
                      for cell, w in sorted(corpus["winners"].items())]
    lines += ["", "## Proposed candidates",
              f"- proposed: {payload['proposed']}  gate-passed: {payload['passed']}", "",
              "| label | family | tier | gates |", "|---|---|---|---|"]
    for p in payload["proposals"][:20]:
        verdict = "pass" if (p.get("verification") or {}).get("passed") else "fail"
        lines.append(f"| {p.get('label')} | {p.get('family')} | {p.get('tier')} | {verdict} |")
    lines += ["", _H_NOTE, ""]
    return "\n".join(lines)
