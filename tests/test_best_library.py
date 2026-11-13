"""Unit tests for the best-effort library carve (CPU-only, no Tensile)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oto.tensile.best_library import (
    SHIPPED_CELLS,
    _tensile_env,
    build_best_library,
    cell_solution_map,
    dedupe_configs,
    default_best_library_dest,
    emit_logic_yaml,
    logic_filename_hint,
)


def test_shipped_cells_count():
    assert len(SHIPPED_CELLS) == 38


def test_cell_solution_map_family_basis():
    cm, refused, stats = cell_solution_map(Path("."), "family")
    assert len(cm) == 38
    assert refused == []
    assert stats["native_basis_winners"] == 38
    for info in cm.values():
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
    _phases, parity = emit_logic_yaml(cm, logic)
    assert parity["parity_ok"] is True
    assert parity["missing"] == []
    assert parity["extra"] == []
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
    cm, refused, _stats = cell_solution_map(Path("."), "any")
    assert len(cm) == 38
    assert refused == []


def test_default_best_library_dest_is_under_gfx90c_results(tmp_path):
    assert default_best_library_dest(tmp_path) == (
        tmp_path / "gfx90c_results" / "best_effort_library")


def test_tensile_env_keeps_system_include_out_of_prepend_path(tmp_path, monkeypatch):
    """A /usr ROCM_PATH must not duplicate /usr/include (breaks include_next)."""
    # Hermetic to the developer's .env: a live ROCM_PATH wins over the
    # resolver mock, so scrub it to test the resolver path.
    monkeypatch.delenv("ROCM_PATH", raising=False)
    monkeypatch.delenv("HIP_PATH", raising=False)
    monkeypatch.delenv("CPLUS_INCLUDE_PATH", raising=False)
    monkeypatch.delenv("C_INCLUDE_PATH", raising=False)
    monkeypatch.setattr(
        "oto.runners.toolchain.resolve_rocm_paths",
        lambda: {"ROCM_PATH": "/usr", "HIP_PATH": "/usr"},
    )
    fake_root = tmp_path / "Tensile"
    fake_root.mkdir()
    env = _tensile_env(fake_root)
    for var in ("CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH"):
        entries = [p for p in env.get(var, "").split(":") if p]
        assert "/usr/include" not in entries


def test_tensile_env_prepends_user_rocm_include(tmp_path, monkeypatch):
    rocm = tmp_path / "rocm"
    inc = rocm / "include"
    inc.mkdir(parents=True)
    (rocm / "lib" / "llvm" / "amdgcn" / "bitcode").mkdir(parents=True)
    monkeypatch.delenv("ROCM_PATH", raising=False)
    monkeypatch.delenv("HIP_PATH", raising=False)
    monkeypatch.delenv("CPLUS_INCLUDE_PATH", raising=False)
    monkeypatch.delenv("C_INCLUDE_PATH", raising=False)
    monkeypatch.setattr(
        "oto.runners.toolchain.resolve_rocm_paths",
        lambda: {"ROCM_PATH": str(rocm), "HIP_PATH": str(rocm)},
    )
    fake_root = tmp_path / "Tensile"
    fake_root.mkdir()
    env = _tensile_env(fake_root)
    assert env["CPLUS_INCLUDE_PATH"].split(":")[0] == str(inc)
    assert env["C_INCLUDE_PATH"].split(":")[0] == str(inc)


def test_logic_filename_hint_falls_back_without_tensile_root():
    assert logic_filename_hint(None, "gfx90c") == "gfx90c"


def test_logic_filename_hint_asks_target_tensile(monkeypatch):
    class _P:
        stdout = "vega10\n"
    monkeypatch.setattr("oto.tensile.best_library.subprocess.run",
                        lambda *a, **k: _P())
    assert logic_filename_hint(Path("FakeTensile-does-not-exist"), "gfx90c") == "vega10"


def test_logic_filename_hint_falls_back_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no tensile")
    monkeypatch.setattr("oto.tensile.best_library.subprocess.run", boom)
    assert logic_filename_hint(Path("FakeTensile-does-not-exist"), "gfx90c") == "gfx90c"


def test_emit_logic_yaml_names_files_for_tensile_selection(tmp_path, monkeypatch):
    """ROCm 7.x maps gfx90c -> vega10; the merge step selects logic files by
    the mapped name as a stem substring, so the YAML filenames must carry it."""
    monkeypatch.setattr("oto.tensile.best_library.logic_filename_hint",
                        lambda root, cn: "vega10")
    cm, _, _ = cell_solution_map(Path("."), "family")
    logic = tmp_path / "3_LibraryLogic"
    emit_logic_yaml(cm, logic, tensile_root=Path("FakeTensile-does-not-exist"))
    names = sorted(p.name for p in logic.glob("*.yaml"))
    assert len(names) == 7
    assert all(n.startswith("vega10_") for n in names)
