"""Unit tests for the best-effort library carve (CPU-only, no Tensile)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oto.tensile.best_library import (
    SHIPPED_CELLS, build_best_library, cell_solution_map, dedupe_configs,
    emit_logic_yaml,
)


def test_shipped_cells_count():
    assert len(SHIPPED_CELLS) == 38


def test_cell_solution_map_family_basis():
    cm, refused, stats = cell_solution_map(Path("."), "family")
    assert len(cm) == 38
    assert refused == []
    assert stats["native_basis_winners"] == 38
    for cell, info in cm.items():
        assert info["chain"] == "native_basis"
        assert info["provenance"]["protocol"] == "family"


def test_dedupe_count():
    cm, _, _ = cell_solution_map(Path("."), "family")
    fams, _ = dedupe_configs(cm)
    total = sum(len(v) for v in fams.values())
    assert total == 19
    assert set(fams) == {"SS", "DD", "HH", "ZZ", "CC", "HH_HPA", "HS_HPA"}


def test_emit_logic_yaml_parity(tmp_path):
    cm, _, _ = cell_solution_map(Path("."), "family")
    logic = tmp_path / "3_LibraryLogic"
    phases, parity = emit_logic_yaml(cm, logic)
    assert parity["parity_ok"] is True
    assert parity["missing"] == [] and parity["extra"] == []
    yamls = sorted(logic.glob("*.yaml"))
    assert len(yamls) == 7
    for y in yamls:
        assert "LibraryType: Matching" in y.read_text()


def test_build_best_library_carve_only(tmp_path):
    res = build_best_library(Path("."), tmp_path / "lib", basis="family",
                             tensile_root=None)
    assert res["status"] == "success"
    assert res["cells"] == 38
    assert res["parity_ok"] is True
    assert (tmp_path / "lib" / "best_effort_library.json").exists()


def test_basis_any_runs():
    cm, refused, stats = cell_solution_map(Path("."), "any")
    assert len(cm) == 38 and refused == []
