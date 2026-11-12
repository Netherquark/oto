"""Tests for the agent-facing harness tools (CPU-only)."""

import json
from pathlib import Path
from typing import Any, Dict

import oto.agents.harness_tools as ht
from oto.agents.harness_tools import (study_kernel_db, verify_candidates,
                                       build_harness_study)
from oto.agents.meta import run as meta_run
from oto.device.loader import load_profile


def _row(fam: str, side: int, gflops: float, phase: str = "phase_x") -> Dict[str, Any]:
    return {"family": fam, "shape": f"{side}x{side}x{side}",
            "gflops_median": gflops, "gflops_best": gflops * 1.1,
            "phase": phase, "kernel": phase}


def _pool_row(fam: str, side: int, tier: str, tag: str) -> Dict[str, Any]:
    return {"label": f"{fam}_{side}_{tier}_{tag}", "tier": tier,
            "shapes": [f"{side}x{side}x{side}"],
            "contraction_pattern": "Ailk_Bjlk", "dtype": "s",
            "config": {"FamilyLabel": fam, "Architecture": "gfx90c",
                       "MacroTile": "128x128x8", "ThreadTile": "8x8"}}


def test_study_kernel_db_missing_corpus(tmp_path):
    result = study_kernel_db(tmp_path)
    assert result["present"] is False
    assert result["rows"] == 0 and result["floor_rows"] == 0
    assert result["target_cells"] > 0 and result["covered_cells"] == 0


def test_study_kernel_db_counts_and_winners(tmp_path):
    db = {"native_a": [_row("SS", 256, 100.0, "p_ss_256"),
                       _row("SS", 256, 250.0, "p_ss_256_best"),
                       _row("HH", 256, 80.0, "p_hh_256")],
          "gfx900_ref_x": [_row("DD", 192, 5.0), _row("DD", 192, 6.0)]}
    (tmp_path / "gfx90c_results" / "analysis").mkdir(parents=True)
    (tmp_path / "gfx90c_results" / "analysis" / "kernel_db.json").write_text(
        json.dumps(db))
    result = study_kernel_db(tmp_path)
    assert result["present"] is True
    assert result["runs"] == 2
    assert result["rows"] == 3 and result["floor_rows"] == 2
    assert result["families"] == {"HH": 1, "SS": 2}
    assert result["winners"]["SS:256"]["gflops_median"] == 250.0
    assert result["winners"]["HH:256"]["phase"] == "p_hh_256"
    assert result["covered_cells"] == 2  # (SS,256) and (HH,256)


def test_propose_candidates_round_robin_cap(monkeypatch):
    rows = ([_pool_row("SS", 256, "wide", i) for i in range(10)] +
            [_pool_row("HH", 256, "wide", i) for i in range(10)])
    monkeypatch.setattr(ht, "iter_candidates", lambda: iter(rows))
    out = ht.propose_candidates(Path("."), limit=4)
    assert len(out) == 4
    assert {r["config"]["FamilyLabel"] for r in out} == {"SS", "HH"}


def test_verify_candidates_annotates_gates(monkeypatch):
    outcomes = {0: (True, "ok"), 1: (False, "boom")}
    monkeypatch.setattr(ht, "validate_tensile_loads",
                        lambda cfg, profile=None: outcomes[cfg["n"]])
    monkeypatch.setattr(ht, "occupancy_feasible",
                        lambda cfg, profile=None: (True, "ok"))
    monkeypatch.setattr(ht, "ldspad_feasible",
                        lambda cfg, profile=None: (True, "ok"))
    rows = [{"config": {"n": 0}}, {"config": {"n": 1}}]
    verified = verify_candidates(rows)
    assert verified[0]["verification"]["passed"] is True
    assert verified[1]["verification"]["passed"] is False
    assert verified[1]["verification"]["loads"] == "boom"


def test_build_harness_study_missing_corpus_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(ht, "propose_candidates", lambda base_dir, limit=16: [])
    prof = load_profile("gfx90c")
    result = build_harness_study(tmp_path, prof)
    assert result["status"] == "success"
    assert result["proposed"] == 0 and result["passed"] == 0
    assert "no kernel_db.json" in result["markdown"]
    assert "## Proposed candidates" in result["markdown"]


def test_build_harness_study_failure_is_captured(tmp_path, monkeypatch):
    def boom(base_dir):
        raise RuntimeError("corrupt db")
    monkeypatch.setattr(ht, "study_kernel_db", boom)
    prof = load_profile("gfx90c")
    result = build_harness_study(tmp_path, prof)
    assert result["status"] == "failed"
    assert "corrupt db" in result["error"]
    assert "Harness study failed" in result["markdown"]


def test_meta_run_harness_hook():
    prof = load_profile("gfx90c")
    with_harness = meta_run(prof, harness=lambda: {"marker": 1})
    assert with_harness["harness"] == {"marker": 1}
    without = meta_run(prof)
    assert without["harness"] is None
