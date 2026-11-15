"""Tests for scripts/build_tensile_client.sh.

CPU-only by construction: `--dry-run` prints the exact configure/build lines
without touching the filesystem beyond reading a fixture prefix, and every
failure path must be a loud, actionable exit, never a silent fallback.
"""

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "build_tensile_client.sh"


def _make_fake_prefix(root: Path) -> Path:
    prefix = root / "rocm"
    (prefix / "include" / "hip" / "amd_detail").mkdir(parents=True)
    (prefix / "include" / "hip" / "amd_detail" / "amd_warp_functions.h").write_text("// stub\n")
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib" / "llvm" / "bin").mkdir(parents=True)
    for name in ("amdclang", "amdclang++", "clang", "clang++"):
        tool = prefix / "lib" / "llvm" / "bin" / name
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o755)
    (prefix / "lib" / "cmake" / "amd_smi").mkdir(parents=True)
    (prefix / "lib" / "cmake" / "amd_smi" / "amd_smi-config.cmake").write_text("# stub\n")
    (prefix / "lib" / "cmake" / "amd_smi" / "amd_smi-config-version.cmake").write_text("# stub\n")
    return prefix


def _run(args, env=None):
    cmd = ["sh", str(SCRIPT), *args]
    # oto's own `.env` leaks TENSILE_ROOT/ROCM_PATH into os.environ once the
    # package is imported, so this test controls the environment explicitly.
    base = {k: v for k, v in os.environ.items()
            if k not in ("TENSILE_ROOT", "ROCM_PATH", "HIP_PATH")}
    return subprocess.run(cmd, capture_output=True, text=True,
                          env={**base, **(env or {})})


def test_help_works(tmp_path):
    res = _run(["--help"])
    assert res.returncode == 0
    assert "--rocm-prefix" in res.stdout


def test_dry_run_plan(tmp_path):
    prefix = _make_fake_prefix(tmp_path)
    root = tmp_path / "rocm-libraries"
    nextcmake = root / "shared" / "tensile" / "next-cmake"
    nextcmake.mkdir(parents=True)
    (nextcmake / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.21)\n")
    res = _run(["--rocm-prefix", str(prefix), "--tensile-root", str(root),
                "--targets", "gfx90c", "--dry-run"])
    assert res.returncode == 0, res.stdout + res.stderr
    lines = res.stdout
    assert f"CMAKE_PREFIX_PATH={prefix}" in lines
    assert f"amd_smi_DIR={prefix}/lib/cmake/amd_smi" in lines
    assert "GPU_TARGETS=gfx90c" in lines
    assert f"{prefix}/lib/llvm/bin/amdclang++" in lines
    # the actual build never ran (no output directory created)
    assert not (nextcmake / "build").exists()


def test_partial_sdk_rejected(tmp_path):
    prefix = tmp_path / "venvlike"
    (prefix / "include").mkdir(parents=True)
    res = _run(["--rocm-prefix", str(prefix),
                "--tensile-root", str(tmp_path), "--dry-run"])
    assert res.returncode == 1
    assert "full ROCm SDK" in res.stderr or "not a full" in res.stderr


def test_missing_prefix_fails(tmp_path):
    res = _run(["--rocm-prefix", str(tmp_path / "nope"),
                "--tensile-root", str(tmp_path), "--dry-run"])
    assert res.returncode == 1
    assert "not a directory" in res.stderr


def test_am_smi_override_validates(tmp_path):
    prefix = _make_fake_prefix(tmp_path)
    root = tmp_path / "rocm-libraries"
    (root / "shared" / "tensile" / "next-cmake").mkdir(parents=True)
    (root / "shared" / "tensile" / "next-cmake" / "CMakeLists.txt").write_text("cmake\n")
    res = _run(["--rocm-prefix", str(prefix), "--tensile-root", str(root),
                "--amd-smi-dir", str(tmp_path / "nope"), "--dry-run"])
    assert res.returncode == 1
    assert "amd-smi-dir" in res.stderr
    assert "not a directory" in res.stderr


def test_missing_amd_smi_rejected(tmp_path):
    prefix = _make_fake_prefix(tmp_path)
    import shutil
    shutil.rmtree(prefix / "lib" / "cmake" / "amd_smi")
    root = tmp_path / "rocm-libraries"
    (root / "shared" / "tensile" / "next-cmake").mkdir(parents=True)
    (root / "shared" / "tensile" / "next-cmake" / "CMakeLists.txt").write_text("cmake\n")
    res = _run(["--rocm-prefix", str(prefix), "--tensile-root", str(root), "--dry-run"])
    assert res.returncode == 1
    assert "amd_smi" in res.stderr


def test_no_tensile_root_fails(tmp_path):
    prefix = _make_fake_prefix(tmp_path)
    res = _run(["--rocm-prefix", str(prefix), "--dry-run"])
    assert res.returncode == 1
    assert "--tensile-root" in res.stderr
