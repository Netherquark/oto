#!/usr/bin/env python3
"""Unit tests for the ROCm toolchain resolver (oto.runners.toolchain).

The contract: ROCM_PATH is mandatory and user-provided, no fallback to
/usr or hipconfig; bin/llvm/amdclang++ derive from it; explicit env wins.
"""
import pytest

from oto.runners import toolchain


def _sdk_tree(tmp_path):
    prefix = tmp_path / "sdk"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib" / "llvm" / "bin").mkdir(parents=True)
    (prefix / "bin" / "amdclang++").write_text("# archclang shim\n")
    (prefix / "lib" / "llvm" / "bin" / "amdclang++").write_text("# sdk amdclang++\n")
    (prefix / "bin" / "hipcc").write_text("# hipcc shim\n")
    return prefix


def test_missing_rocm_path_raises_with_guidance(monkeypatch):
    monkeypatch.delenv("ROCM_PATH", raising=False)
    with pytest.raises(ValueError, match="ROCM_PATH is not set"):
        toolchain.require_rocm_path()


def test_bad_rocm_path_raises(monkeypatch, tmp_path):
    missing = tmp_path / "nope"
    monkeypatch.setenv("ROCM_PATH", str(missing))
    with pytest.raises(ValueError, match="not a directory"):
        toolchain.require_rocm_path()


def test_resolution_derives_bin_llvm_assembler(monkeypatch, tmp_path):
    prefix = _sdk_tree(tmp_path)
    monkeypatch.delenv("ROCM_BIN", raising=False)
    monkeypatch.delenv("ROCM_LLVM_BIN", raising=False)
    monkeypatch.delenv("TENSILE_ASSEMBLER", raising=False)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    paths = toolchain.resolve_rocm_paths()
    assert paths["ROCM_PATH"] == str(prefix.resolve())
    assert paths["ROCM_BIN"] == str(prefix / "bin")
    assert paths["ROCM_LLVM_BIN"] == str(prefix / "lib" / "llvm" / "bin")
    assert paths["TENSILE_ASSEMBLER"].endswith("llvm/bin/amdclang++")


def test_wheel_layout_detects_site_packages_llvm(monkeypatch, tmp_path):
    prefix = tmp_path / "venv"
    (prefix / "bin").mkdir(parents=True)
    sdk = prefix / "lib" / "python3.14" / "site-packages" / "_rocm_sdk_core"
    (sdk / "bin").mkdir(parents=True)
    (sdk / "lib" / "llvm" / "bin").mkdir(parents=True)
    (sdk / "lib" / "llvm" / "bin" / "amdclang++").write_text("# sdk amdclang++\n")
    monkeypatch.delenv("ROCM_LLVM_BIN", raising=False)
    monkeypatch.delenv("ROCM_BIN", raising=False)
    monkeypatch.delenv("TENSILE_ASSEMBLER", raising=False)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    paths = toolchain.resolve_rocm_paths()
    assert "site-packages" in paths["ROCM_LLVM_BIN"]
    assert paths["ROCM_LLVM_BIN"].endswith("_rocm_sdk_core/lib/llvm/bin")


def test_explicit_env_wins_over_derivation(monkeypatch, tmp_path):
    prefix = _sdk_tree(tmp_path)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    monkeypatch.setenv("ROCM_BIN", str(prefix / "bin"))
    monkeypatch.setenv("ROCM_LLVM_BIN", str(prefix / "lib" / "llvm" / "bin"))
    monkeypatch.setenv("TENSILE_ASSEMBLER", "/custom/amdclang++")
    (prefix / "custom").mkdir()
    (prefix / "custom" / "amdclang++").write_text("# custom\n")
    monkeypatch.setenv("TENSILE_ASSEMBLER", str(prefix / "custom" / "amdclang++"))
    paths = toolchain.resolve_rocm_paths()
    assert paths["TENSILE_ASSEMBLER"].endswith("custom/amdclang++")


def test_no_system_fallback_anywhere(monkeypatch, tmp_path):
    """A resolver with no ROCM_PATH can never answer /usr or /opt/rocm."""
    _sdk_tree(tmp_path)
    monkeypatch.delenv("ROCM_PATH", raising=False)
    with pytest.raises(ValueError):
        toolchain.resolve_rocm_paths()


def test_rocversion_passes_through_when_set(monkeypatch, tmp_path):
    prefix = _sdk_tree(tmp_path)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    monkeypatch.setenv("ROCM_VERSION", "7.15.0a20260728")
    paths = toolchain.resolve_rocm_paths()
    assert paths["ROCM_VERSION"] == "7.15.0a20260728"


def test_compilers_probe_sdk_amdclang_over_hipcc(monkeypatch, tmp_path):
    """The SDK's amdclang is Tensile's native default and is preferred; hipcc
    is only ever a fallback for trees that ship no clang."""
    prefix = _sdk_tree(tmp_path)
    (prefix / "lib" / "llvm" / "bin" / "amdclang").write_text("# sdk amdclang\n")
    monkeypatch.delenv("TENSILE_CXX_COMPILER", raising=False)
    monkeypatch.delenv("TENSILE_C_COMPILER", raising=False)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    paths = toolchain.resolve_rocm_paths()
    assert paths["TENSILE_CXX_COMPILER"].endswith("llvm/bin/amdclang++")
    assert paths["TENSILE_C_COMPILER"].endswith("llvm/bin/amdclang")


def test_compilers_fall_back_to_bare_hipcc_when_tree_has_no_clang(monkeypatch, tmp_path):
    prefix = tmp_path / "distro"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "hipcc").write_text("# hipcc shim\n")
    monkeypatch.delenv("TENSILE_CXX_COMPILER", raising=False)
    monkeypatch.delenv("TENSILE_C_COMPILER", raising=False)
    monkeypatch.delenv("ROCM_LLVM_BIN", raising=False)
    monkeypatch.delenv("ROCM_BIN", raising=False)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    paths = toolchain.resolve_rocm_paths()
    assert paths["TENSILE_CXX_COMPILER"] == "hipcc"
    assert paths["TENSILE_C_COMPILER"] == "hipcc"


def test_explicit_compiler_env_wins(monkeypatch, tmp_path):
    prefix = _sdk_tree(tmp_path)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    monkeypatch.setenv("TENSILE_CXX_COMPILER", "my-cxx-shim")  # bare name passthrough
    monkeypatch.setenv("TENSILE_C_COMPILER", str(prefix / "bin" / "hipcc"))
    paths = toolchain.resolve_rocm_paths()
    assert paths["TENSILE_CXX_COMPILER"] == "my-cxx-shim"
    assert paths["TENSILE_C_COMPILER"] == str(prefix / "bin" / "hipcc")


def test_explicit_compiler_env_missing_path_raises(monkeypatch, tmp_path):
    prefix = _sdk_tree(tmp_path)
    monkeypatch.setenv("ROCM_PATH", str(prefix))
    monkeypatch.setenv("TENSILE_CXX_COMPILER", "/nonexistent/amdclang++")
    with pytest.raises(ValueError, match="TENSILE_CXX_COMPILER"):
        toolchain.resolve_rocm_paths()


def test_get_tensile_env_points_at_user_include(tmp_path, monkeypatch):
    """Tensile shells out to amdclang++ with no -I for HIP; the subprocess
    environment must carry the user-provided ROCm's include directory so
    #include <hip/...> never resolves to /usr/include/hip.
    """
    import oto.runners.driver as pt

    prefix = tmp_path / "sdk"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib" / "llvm" / "bin").mkdir(parents=True)
    (prefix / "include" / "hip" / "amd_detail").mkdir(parents=True)
    (prefix / "lib" / "llvm" / "bin" / "amdclang++").write_text("# amdclang++\n")
    monkeypatch.delenv("ROCM_BIN", raising=False)
    monkeypatch.delenv("ROCM_LLVM_BIN", raising=False)
    monkeypatch.delenv("TENSILE_ASSEMBLER", raising=False)
    monkeypatch.delenv("CPLUS_INCLUDE_PATH", raising=False)
    monkeypatch.delenv("C_INCLUDE_PATH", raising=False)
    monkeypatch.setenv("ROCM_PATH", str(prefix))

    class _Stub(pt.TensileDriver):
        pass

    drv = _Stub.__new__(_Stub)
    drv.tensile_root = prefix
    env = pt.TensileDriver._get_tensile_env(drv)
    assert str(prefix / "include") in env["CPLUS_INCLUDE_PATH"].split(":")
    assert str(prefix / "include") in env["C_INCLUDE_PATH"].split(":")
