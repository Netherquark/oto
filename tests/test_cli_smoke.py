"""Smoke tests for the oto CLI dispatcher."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_CMD = [sys.executable, "-m", "oto"]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        BASE_CMD + list(args),
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )


def test_version():
    r = _run("--version")
    assert r.returncode == 0
    assert "oto" in r.stdout


def test_help():
    r = _run("--help")
    assert r.returncode == 0
    assert "Available commands" in r.stdout


def test_bare_invocation():
    r = _run()
    assert r.returncode == 0
    assert "Start here" in r.stdout


def test_bare_invocation_lists_quick_start():
    r = _run()
    assert r.returncode == 0
    assert "oto doctor" in r.stdout
    assert "oto tune --dry-run" in r.stdout


def _fake_tensile_root(tmp_path: Path) -> Path:
    tensile = tmp_path / "tensile"
    (tensile / "Tensile" / "bin").mkdir(parents=True)
    tb = tensile / "Tensile" / "bin" / "Tensile"
    tb.write_text("#!/bin/sh\necho fake-tensile 0.0.0\n")
    tb.chmod(0o755)
    return tensile


def test_doctor_missing_tensile_client_is_red(tmp_path):
    # A box without a prebuilt Tensile client cannot run a single phase; the
    # doctor must say so instead of letting the campaign die inside every
    # Tensile subprocess.
    env = {**os.environ,
           "TENSILE_ROOT": str(_fake_tensile_root(tmp_path))}
    env.pop("OTO_TENSILE_CLIENT", None)
    r = subprocess.run(
        [*BASE_CMD, "doctor"], capture_output=True, text=True,
        cwd=str(ROOT), env=env, timeout=120)
    assert r.returncode == 1
    assert "Tensile client" in r.stdout
    assert "tensile-client" in r.stdout


def test_doctor_bad_client_override_is_red(tmp_path):
    # Explicit env pointing nowhere is a hard error, never silently replaced.
    root = _fake_tensile_root(tmp_path)
    env = {**os.environ,
           "TENSILE_ROOT": str(root),
           "OTO_TENSILE_CLIENT": str(tmp_path / "wrong-path")}
    r = subprocess.run(
        [*BASE_CMD, "doctor"], capture_output=True, text=True,
        cwd=str(ROOT), env=env, timeout=120)
    assert r.returncode == 1
    assert "OTO_TENSILE_CLIENT" in r.stdout


def test_status():
    r = _run("status")
    assert r.returncode == 0


def test_check_candidates():
    r = _run("check", "candidates")
    assert r.returncode == 0


def test_verify_all_runs():
    # The evergreen five-check matrix requires a REF worktree of HEAD~1 and
    # a ~6k-phase config-writer render; a ~300-second timeout covers it.
    # The verifier's own contract is rc==0 clean; rc==1 is findings. A test
    # that accepts rc==1 asserts nothing about whether the battery is green.
    r = subprocess.run([*BASE_CMD, "verify", "all"],
                      capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert r.returncode == 0, (
        "oto verify all failed\n" + r.stdout + r.stderr)


def test_help_subcommand():
    r = _run("help")
    assert r.returncode == 0
    assert "Available commands" in r.stdout
    assert "tune" in r.stdout


def test_unknown_command():
    r = _run("nonexistent")
    assert r.returncode != 0
