#!/usr/bin/env python3
"""
test_registry_kernel_db_auto.py — automatic kernel_db refresh on run completion.

The analysis cache (`kernel_db.json`) must be fresh for the next
mutation whenever a run finishes. `SQLiteRegistry.update_run_status` is the
single choke point every run-finalisation path goes through (run loop, SIGINT,
gfx900-reference, --auto driver), so the rebuild hooks there:

  * `completed` / `interrupted` (data may have landed) -> rebuild fires;
  * `skipped` (no benchmark data) -> no rebuild;
  * read_only registry -> still raises before any rebuild;
  * opt-out: constructor flag and OTO_NO_AUTO_KERNEL_DB_REBUILD=1;
  * a failing rebuild is logged and swallowed — it must never fail a run.

Run: python3 -m pytest -q tests/test_registry_kernel_db_auto.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import oto.harness.kernel_db as kernel_db_mod
from oto.ledger.registry import SQLiteRegistry
from oto.runners.paths import results_rel


@pytest.fixture(autouse=True)
def _no_env_optout(monkeypatch):
    """Ambient env must not silently disable the hook under test."""
    monkeypatch.delenv("OTO_NO_AUTO_KERNEL_DB_REBUILD", raising=False)


def _cache(base: Path) -> Path:
    return base / results_rel("analysis", "kernel_db.json")


def test_completed_triggers_rebuild(tmp_path):
    reg = SQLiteRegistry(tmp_path)
    reg.create_run_dir("run_test_auto")
    reg.update_run_status("run_test_auto", "completed", {"phases_executed": 2})
    assert _cache(tmp_path).is_file(), "completed must refresh kernel_db.json"


def test_interrupted_triggers_rebuild(tmp_path):
    reg = SQLiteRegistry(tmp_path)
    reg.create_run_dir("run_test_int")
    reg.update_run_status("run_test_int", "interrupted", {})
    assert _cache(tmp_path).is_file(), "interrupted (partial data) must refresh"


def test_skipped_does_not_rebuild(tmp_path):
    reg = SQLiteRegistry(tmp_path)
    reg.create_run_dir("run_test_skip")
    reg.update_run_status("run_test_skip", "skipped", {"phases_executed": 0})
    assert not _cache(tmp_path).exists(), "skipped produces no corpus to fold"


def test_constructor_flag_disables_rebuild(tmp_path):
    reg = SQLiteRegistry(tmp_path, auto_rebuild_kernel_db=False)
    reg.create_run_dir("run_test_flag")
    reg.update_run_status("run_test_flag", "completed", {})
    assert not _cache(tmp_path).exists()


def test_env_optout_disables_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_NO_AUTO_KERNEL_DB_REBUILD", "1")
    reg = SQLiteRegistry(tmp_path)
    reg.create_run_dir("run_test_env")
    reg.update_run_status("run_test_env", "completed", {})
    assert not _cache(tmp_path).exists()


def test_read_only_still_refuses_before_rebuild(tmp_path):
    # Seed a writable registry + a cache marker, then reopen read_only.
    SQLiteRegistry(tmp_path).create_run_dir("run_test_ro")
    ro = SQLiteRegistry(tmp_path, read_only=True)
    with pytest.raises(PermissionError):
        ro.update_run_status("run_test_ro", "completed", {})


def test_rebuild_failure_is_swallowed(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("simulated rebuild failure")

    monkeypatch.setattr(kernel_db_mod, "load_kernel_db", _boom)
    reg = SQLiteRegistry(tmp_path)
    reg.create_run_dir("run_test_boom")
    # Must not raise: a cache refresh never fails a run finalisation.
    reg.update_run_status("run_test_boom", "completed", {})
    assert reg.run_row("run_test_boom")["status"] == "completed"
    assert not _cache(tmp_path).exists()


def test_cleanup_stale_runs_refreshes_cache(tmp_path):
    # A hard-crashed run: dir + 'started' row, no SIGINT finaliser.
    reg = SQLiteRegistry(tmp_path)
    reg.create_run_dir("run_test_crash")
    assert reg.run_row("run_test_crash")["status"] == "started"
    cleaned = reg.cleanup_stale_runs()
    assert cleaned == 1
    assert _cache(tmp_path).is_file(), "orphaned run data must be folded in"


def test_cleanup_with_nothing_to_do_does_not_rebuild(tmp_path):
    reg = SQLiteRegistry(tmp_path)
    assert reg.cleanup_stale_runs() == 0
    assert not _cache(tmp_path).exists()
