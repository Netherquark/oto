#!/usr/bin/env python3
"""Unit tests for the download-on-request path in `oto setup`.

Easy mode must not download anything it was not asked to fetch. These pin
that behaviour: candidates installed on request only, dry-run prints the
exact commands instead of executing them, and without opt-in (a TTY-less
``--yes`` run with no flags) nothing is downloaded and the setup explains
how to opt in.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import oto.runners.onboarding as ob


def _args(**over):
    args = types.SimpleNamespace(
        yes=True,
        dry_run=True,
        convergence_mode="blind",
        spoof=None,
        rocm_flavour="python",
        rocm_version_policy="nightly",
        rocm_pinned_version="",
        tensile_version_policy="pinned",
        tensile_pinned="deadbeef",
        download_rocm=None,
        download_torch=False,
        download_tensile=None,
        rocm_venv="~/should-not-be-created",
        tensile_dest="~/should-not-be-created",
        rocm_prefix=None,
        tensile_root=None,
        gpu_targets="gfx90c",
        jobs=1,
        skip_build=True,
        build_client=False,
        write_env=False,
        codename="gfx90c",
        force=False,
    )
    for key, value in over.items():
        setattr(args, key, value)
    return args


@pytest.fixture
def empty_box(monkeypatch):
    """Simulate a machine with no ROCm SDK and no Tensile checkout."""
    monkeypatch.setattr(ob, "_discover_rocm", lambda: [])
    monkeypatch.setattr(ob, "_discover_tensile", lambda: [])
    monkeypatch.setattr(ob, "_interactive", lambda: False)


def test_dry_run_download_rocm_prints_commands_no_execution(empty_box, capsys, tmp_path):
    venv = tmp_path / "rocm-venv"
    args = _args(download_rocm="python", download_torch=True, rocm_venv=str(venv))
    rc = ob.run_setup(args)
    out = capsys.readouterr().err
    assert rc == 0
    assert "rocm.nightlies.amd.com/whl-multi-arch/" in out
    assert "rocm[libraries,device-gfx90c]" in out
    assert "torch[device-gfx90c]==2.12.0" in out
    assert "Pass --download-tensile" in out  # tensile leg carried the hint
    assert "dry-run: nothing was installed" in out
    assert not venv.exists(), "dry-run created a venv"


def test_dry_run_download_tensile_prints_clone_no_execution(empty_box, capsys, tmp_path):
    dest = tmp_path / "rocm-libraries"
    args = _args(download_tensile="clone", tensile_dest=str(dest))
    rc = ob.run_setup(args)
    out = capsys.readouterr().err
    assert rc == 0
    assert "git clone --depth 1 --filter=blob:none --sparse" in out
    assert "github.com/ROCm/rocm-libraries" in out
    assert "sparse-checkout set shared/tensile" in out
    assert "dry-run: nothing was cloned" in out
    assert not dest.exists(), "dry-run cloned a repository"


def test_yes_mode_without_flags_prints_hint_and_downloads_nothing(empty_box, capsys):
    args = _args()
    rc = ob.run_setup(args)
    out = capsys.readouterr().err
    assert rc == 0
    assert "--download-rocm" in out
    assert "--download-tensile" in out
    assert "Nothing was downloaded." in out
    assert "rocm[libraries" not in out  # no commands echoed when not requested


def test_torch_install_prints_all_packages(empty_box, capsys, tmp_path):
    venv = tmp_path / "rocm-venv"
    args = _args(download_rocm="python", download_torch=True, rocm_venv=str(venv))
    rc = ob.run_setup(args)
    out = capsys.readouterr().err
    assert rc == 0
    assert "torchvision[device-gfx90c]==0.27.0" in out
    assert "torchaudio==2.11.0" in out
