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
from typing import Any

from oto.device import loader as _loader
from oto.device.profile import DeviceProfile
from oto.harness.candidate_overlay import _round_robin_prune
from oto.harness.candidate_pool import iter_candidates
from oto.harness.candidate_rows import TARGET_CELLS
from oto.harness.cell_knob_diff import _side, _winner_per_cell
from oto.runners.result_paths import results_rel
from oto.tensile.gates.loads import validate_tensile_loads
from oto.tensile.gates.occupancy import ldspad_feasible, occupancy_feasible

KERNEL_DB_RELPATH = Path(results_rel("analysis", "kernel_db.json"))

_H_NOTE = ("Proposals are CPU-gate-checked models only. They still need GPU "
           "feedback (benchmark + accept/reject) before any of them can ship.")


def _target_cells() -> set:
    return {(fam, side) for fam, sides in TARGET_CELLS.items() for side in sides}


def study_kernel_db(base_dir) -> dict[str, Any]:
    """Census of the measured corpus: runs, native rows, per-family counts,
    TARGET_CELLS coverage, and the native winner per (family, side)."""
    path = Path(base_dir) / KERNEL_DB_RELPATH
    if not path.exists():
        return {"present": False, "runs": 0, "rows": 0, "floor_rows": 0,
                "families": {}, "winners": {},
                "covered_cells": 0, "target_cells": len(_target_cells())}
    db = json.loads(path.read_text())
    target = _target_cells()
    native: list[dict[str, Any]] = []
    floor = 0
    _floor_prefix = _loader.spoof_prefix()
    for run_id, rows in db.items():
        if str(run_id).startswith(f"{_floor_prefix}_ref"):
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


def propose_candidates(base_dir, limit: int = 16) -> list[dict[str, Any]]:
    """Gate-verified pool rows (the same generator the seed overlay uses),
    round-robin pruned to ``limit`` so big families can't starve the HPA
    families. CPU-only. The pool is generated from the active profile."""
    pool = list(iter_candidates())
    return _round_robin_prune(pool, limit)


def verify_candidates(rows: list[dict[str, Any]],
                      profile: DeviceProfile | None = None) -> list[dict[str, Any]]:
    """Re-check each proposed row against the CPU gates (loads, occupancy,
    ldspad). Independent of the emission-time check; no GPU involved.
    ``profile`` -- the device profile to tune.
    """
    verified: list[dict[str, Any]] = []
    for row in rows:
        cfg = row.get("config",) or {}
        ok_l, msg_l = validate_tensile_loads(cfg, profile=profile)
        ok_o, msg_o = occupancy_feasible(cfg, profile=profile)
        ok_s, msg_s = ldspad_feasible(cfg, profile=profile)
        verified.append({**row, "verification": {
            "passed": bool(ok_l and ok_o and ok_s),
            "loads": msg_l, "occupancy": msg_o, "ldspad": msg_s}})
    return verified


def _row_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {"label": row.get("label"), "tier": row.get("tier"),
            "family": (row.get("config") or {}).get("FamilyLabel"),
            "contraction_pattern": row.get("contraction_pattern"),
            "shapes": row.get("shapes"), "verification": row.get("verification")}


def build_harness_study(base_dir, profile: DeviceProfile,
                        proposal_limit: int = 16) -> dict[str, Any]:
    """Study the corpus, propose + verify candidates, return the payload plus
    a markdown section the doc generator can embed.
    ``profile`` -- the device profile to tune.
    """
    try:
        corpus = study_kernel_db(base_dir)
        rows = verify_candidates(propose_candidates(base_dir, limit=proposal_limit),
                                 profile=profile)
        passed = sum(1 for r in rows if r["verification"]["passed"])
        payload: dict[str, Any] = {"status": "success", "profile": profile.codename,
                                   "corpus": corpus,
                                   "proposed": len(rows), "passed": passed,
                                   "proposals": [_row_summary(r) for r in rows]}
        payload["markdown"] = _study_markdown(profile, payload)
        return payload
    except Exception as exc:  # the agent path must never crash doc generation
        return {"status": "failed", "profile": profile.codename, "error": str(exc),
                "markdown": (f"## Harness study — {profile.codename}\n\n"
                             f"Harness study failed: {exc}\n")}




def compare_runs(base_dir, run_a, run_b):
    """Compare two runs kernel_db rows: cells that differ in best GFLOPS."""
    path = Path(base_dir) / KERNEL_DB_RELPATH
    if not path.exists():
        return {"present": False, "error": "no kernel_db.json"}
    db = json.loads(path.read_text())
    rows_a = db.get(run_a, [])
    rows_b = db.get(run_b, [])

    def _best(rows):
        out = {}
        for r in rows:
            cell = (r.get("family"), _side(r.get("shape")))
            if cell[0] and cell[1] is not None:
                gf = r.get("gflops_median") or r.get("gflops_best") or 0.0
                key = str(cell[0]) + ":" + str(cell[1])
                if key not in out or gf > out[key]:
                    out[key] = gf
        return out

    ba, bb = _best(rows_a), _best(rows_b)
    regressions, improvements, unchanged = [], [], []
    for cell in sorted(set(ba) | set(bb)):
        va, vb = ba.get(cell), bb.get(cell)
        if va is None or vb is None:
            continue
        if vb < va * 0.95:
            regressions.append({"cell": cell, "run_a": va, "run_b": vb,
                               "delta_pct": round((vb / va - 1) * 100, 2)})
        elif vb > va * 1.05:
            improvements.append({"cell": cell, "run_a": va, "run_b": vb,
                                "delta_pct": round((vb / va - 1) * 100, 2)})
        else:
            unchanged.append(cell)
    return {"present": True, "run_a": run_a, "run_b": run_b,
            "regressions": regressions, "improvements": improvements,
            "unchanged": len(unchanged), "total_cells": len(set(ba) & set(bb))}


def find_regressions(base_dir, threshold_pct=5.0):
    """Find cells whose best GFLOPS dropped more than threshold_pct vs previous run."""
    path = Path(base_dir) / KERNEL_DB_RELPATH
    if not path.exists():
        return []
    db = json.loads(path.read_text())
    run_ids = sorted(db.keys())
    if len(run_ids) < 2:
        return []
    prev, curr = run_ids[-2], run_ids[-1]
    result = compare_runs(base_dir, prev, curr)
    return [r for r in result.get("regressions", [])
            if abs(r["delta_pct"]) >= threshold_pct]


def export_summary(base_dir, fmt="text"):
    """Export a one-line-per-cell corpus summary. fmt=text or json."""
    corpus = study_kernel_db(base_dir)
    if fmt == "json":
        return json.dumps(corpus, indent=2, sort_keys=True)
    lines = ["# Corpus summary - " + str(corpus.get("runs", 0)) + " runs, " + str(corpus.get("rows", 0)) + " rows"]
    if corpus["present"]:
        lines.append("families: " + str(corpus["families"]))
        lines.append("coverage: " + str(corpus["covered_cells"]) + "/" + str(corpus["target_cells"]))
        for cell, w in sorted(corpus.get("winners", {}).items()):
            lines.append("  " + cell + ": " + str(w.get("gflops_median")) + " GFLOP/s - " + str(w.get("phase")))
    return chr(10).join(lines)


def validate_deck(base_dir):
    """Validate phases.yaml against CPU gates. Returns pass/fail per phase."""
    import yaml as _yaml
    deck_path = Path(base_dir) / "phases.yaml"
    if not deck_path.exists():
        return {"present": False, "error": "no phases.yaml"}
    phases = _yaml.safe_load(deck_path.read_text()) or []
    results = []
    for ph in phases:
        cfg = ph.get("config", {}) or {}
        if not cfg:
            results.append({"phase_id": ph.get("phase_id"), "passed": True,
                            "note": "no config (skipped)"})
            continue
        ok_l, msg_l = validate_tensile_loads(cfg)
        ok_o, msg_o = occupancy_feasible(cfg)
        ok_s, msg_s = ldspad_feasible(cfg)
        results.append({"phase_id": ph.get("phase_id"),
                        "passed": bool(ok_l and ok_o and ok_s),
                        "loads": msg_l, "occupancy": msg_o, "ldspad": msg_s})
    passed = sum(1 for r in results if r["passed"])
    return {"present": True, "total": len(results), "passed": passed,
            "failed": len(results) - passed, "results": results}

def _study_markdown(profile: DeviceProfile, payload: dict[str, Any]) -> str:
    """``profile`` -- the device profile to tune."""
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
        verdict = "pass" if (p.get("verification",) or {}).get("passed",) else "fail"
        lines.append(f"| {p.get('label',)} | {p.get('family',)} | {p.get('tier',)} | {verdict} |")
    lines += ["", _H_NOTE, ""]
    return "\n".join(lines)
