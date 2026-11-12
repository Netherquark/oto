"""Comparability of the kernel DB across runs and invocation forms.

Owns: the like-for-like (`protocol='family'`) admission rule used by the
regression matrix, the floor-run discovery used by the occupancy audit, and
the per-side corpus counts in the generated study doc.

These guard the multi-run comparability contract: probe/single-problem rows
measure 2-4x inflated against the deck protocol and must not win an
all-time cell, and the floor arm must never reference a hardcoded run id.
"""

from __future__ import annotations

import json

from oto.device import loader
from oto.harness import occupancy_audit, regression_matrix
from oto.tools.potential_configs_gen import generate


def _row(protocol: str = "family", gflops: float = 100.0) -> dict:
    return {"phase": "phase_probe_ss", "kernel": "sb_8x8",
            "shape": "256x256x256", "gflops_median": gflops,
            "gflops_best": gflops, "n_seeds": 3, "family": "SS",
            "protocol": protocol, "dtype": "S",
            "MacroTile": "128x128", "ThreadTile": "8x8",
            "VectorWidth": 4, "DepthU": 8}


def test_floor_rows_prefers_locked() -> None:
    db = {"run_aaa": [1, 2], "gfx900_ref_1": [3],
          "gfx900_ref_locked_x": [4, 5]}
    rows, chosen = occupancy_audit._floor_rows(db)
    assert rows == [4, 5]
    assert chosen == ["gfx900_ref_locked_x"]


def test_floor_rows_falls_back_to_any_ref() -> None:
    db = {"run_aaa": [1], "gfx900_ref_7": [9, 8]}
    rows, chosen = occupancy_audit._floor_rows(db)
    assert rows == [9, 8]
    assert chosen == ["gfx900_ref_7"]


def test_floor_rows_empty_when_no_ref_keys() -> None:
    rows, chosen = occupancy_audit._floor_rows({"run_aaa": [1]})
    assert rows == []
    assert chosen == []


def test_split_native_spoof_tags_runs() -> None:
    db = {"run_a1b2": [{"x": 1}], "gfx900_ref_locked_x": [{"x": 2}],
          "run_c3d4": [{"x": 3}]}
    native, spoof = regression_matrix._split_native_spoof(db)
    assert {r["run"] for r in native} == {"run_a1b2", "run_c3d4"}
    assert [r["run"] for r in spoof] == ["gfx900_ref_locked_x"]


def test_filter_protocol_family_only_by_default() -> None:
    rows = [_row("family"), _row("single"), _row("unknown")]
    kept, dropped = regression_matrix._filter_protocol(rows, any_protocol=False)
    assert [r["protocol"] for r in kept] == ["family"]
    assert dropped == 2


def test_filter_protocol_any_admits_all() -> None:
    rows = [_row("family"), _row("single")]
    kept, dropped = regression_matrix._filter_protocol(rows, any_protocol=True)
    assert len(kept) == 2
    assert dropped == 0


def test_filter_protocol_missing_stamp_dropped() -> None:
    row = _row("family")
    del row["protocol"]
    kept, dropped = regression_matrix._filter_protocol([row], any_protocol=False)
    assert kept == []
    assert dropped == 1


def test_generate_reports_per_side_counts(tmp_path) -> None:
    analysis = tmp_path / "gfx90c_results" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "kernel_db.json").write_text(json.dumps({
        "run_a1": [_row(), _row()],
        "gfx900_ref_locked_x": [_row()],
    }))
    profile = loader.load_profile("gfx90c")
    out = generate(profile, tmp_path)
    assert "- native rows: 2" in out
    assert "- floor rows: 1" in out
