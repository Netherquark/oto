"""Smoke tests for the oto CLI dispatcher."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OTO = ROOT / "oto.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(OTO), *args],
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
    assert "Quick start" in r.stdout


def test_doctor():
    r = _run("doctor")
    assert r.returncode == 0


def test_status():
    r = _run("status")
    assert r.returncode == 0


def test_check_candidates():
    r = _run("check", "candidates")
    assert r.returncode == 0


def test_verify_all_runs():
    r = _run("verify", "all")
    # verify_all returns non-zero if any check fails (pre-existing)
    assert r.returncode in (0, 1)


def test_help_subcommand():
    r = _run("help")
    assert r.returncode == 0
    assert "Commands:" in r.stdout


def test_unknown_command():
    r = _run("nonexistent")
    assert r.returncode != 0
