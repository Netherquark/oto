#!/usr/bin/env python3
"""Regression test: the reference-floor status write never receives a tuple.

The floor path executes every shipped phase, THEN marks the run completed.
A tuple reaching `registry.update_run_status` voids the whole floor (SQLite
refuses to bind tuples) and leaves the run `started`. This pins the call
contract: `update_run_status` must receive a plain ``str`` run_id.
"""
from unittest import mock

from oto.runners.driver import TensileDriver


class _FakeRegistry:
    def __init__(self):
        self.status_calls = []

    def update_run_status(self, run_id, status, metadata=None):
        self.status_calls.append((run_id, status, metadata))


def _driver_with(results):
    drv = TensileDriver.__new__(TensileDriver)
    drv.registry = _FakeRegistry()
    drv._telemetry = None
    drv._telemetry_run_id = None
    drv._stop_requested = False
    drv.run_phases = mock.Mock(return_value=results)
    drv._sync_agent_run_id = mock.Mock()
    return drv


def test_floor_status_write_gets_plain_str_run_id(tmp_path):
    drv = _driver_with([{"status": "success"}, {"status": "success"}])
    out = drv._execute_reference_phases(
        [{"phase_id": "p"}], tmp_path / "phases_reference.yaml",
        "gfx90c_ref_20260101_000000", None, False, {})
    (run_id, status, _meta), = drv.registry.status_calls
    assert isinstance(run_id, str)
    assert run_id == "gfx90c_ref_20260101_000000"
    assert status == "completed"
    assert out["status"] == "completed"


def test_floor_status_write_failed_when_nothing_measured(tmp_path):
    drv = _driver_with([{"status": "error"}])
    out = drv._execute_reference_phases(
        [{"phase_id": "p"}], tmp_path / "phases_reference.yaml",
        "gfx90c_ref_20260101_000000", None, False, {})
    (run_id, status, _meta), = drv.registry.status_calls
    assert isinstance(run_id, str)
    assert status == "failed"
    assert out["status"] == "failed"


def test_floor_status_write_smoke_not_completed(tmp_path):
    drv = _driver_with([{"status": "success"}])
    out = drv._execute_reference_phases(
        [{"phase_id": "p"}], tmp_path / "phases_reference.yaml",
        "gfx90c_ref_20260101_000000", limit=1, resume=False, resume_meta={})
    (_run_id, status, _meta), = drv.registry.status_calls
    assert status == "smoke"
    assert out["status"] == "smoke"
