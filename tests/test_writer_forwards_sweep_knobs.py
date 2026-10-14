#!/usr/bin/env python3
"""Every knob the sweep deck sets must reach the Tensile YAML it benchmarks.

Owns: the fork round-trip -- a candidate knob that ``_fork_params`` drops (or
casts wrong) benchmarks at the Tensile default while the manifest claims the
treatment ran. Three such silent drops were found while preparing the
2026-10-14 run: ``PrefetchGlobalRead=2`` collapsed to 1 via ``bool()``,
``LocalSplitU`` was hardcoded to ``WorkGroup[2]=1``, and nine sweep knobs
(``UseSgprForGRO``, ``InnerUnroll``, ``NumLoadsCoalescedB``, ``MaxOccupancy``,
``AggressivePerfMode``, ``FractionalLoad``, ``NonTemporalA/B``,
``AssertFree1ElementMultiple``) never reached ``ForkParameters`` at all --
including the AF1EM half of the D4 paired widen, without which Tensile refuses
the B-side load at solution construction.

Run: python3 -m pytest -q tests/test_writer_forwards_sweep_knobs.py
"""
from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest
import yaml

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.runners.driver import TensileDriver  # noqa: E402
from oto.tensile import config_writer  # noqa: E402
from oto.tensile.decks import KNOB_SWEEP_BASES, KNOB_SWEEPS  # noqa: E402

CC_BASE = dict(KNOB_SWEEP_BASES["CC"][0])


def _driver():
    real = signal.signal
    signal.signal = lambda *a, **k: None
    try:
        return TensileDriver(BASE, create_run=False)
    finally:
        signal.signal = real


@pytest.fixture(scope="module")
def driver():
    return _driver()


def _phase(knobs):
    config = {"Architecture": "gfx90c", "DataType": "C",
              "ContractionPattern": "Ailk_Bljk",
              "ProblemType": "1024x1024x1024", "ScheduleName": "isa",
              "FamilyLabel": "CC", **CC_BASE, **knobs}
    return {"phase_id": "phase_probe", "label": "CC_Ailk_Bljk_probe",
            "dtype": "C", "shapes": ["1024x1024x1024"],
            "ScheduleName": "isa", "NumBenchmarks": 8, "config": config}


def _fork(driver, knobs, tmp_path):
    out = tmp_path / "p.yaml"
    wrote, why = config_writer.write_phase_config(driver, out, _phase(knobs))
    assert wrote, f"launch gate refused the probe: {why}"
    doc = yaml.safe_load(out.read_text())
    fork = {}
    for entry in doc["BenchmarkProblems"][0][1]["ForkParameters"]:
        fork.update(entry)
    # YAML single-element lists unwrap to scalars; normalise for comparison.
    return {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
            for k, v in fork.items()}


@pytest.mark.parametrize("key,value", [
    ("UseSgprForGRO", True),
    ("InnerUnroll", 2),
    ("PrefetchGlobalRead", 2),
    ("NumLoadsCoalescedA", 2),
    ("NumLoadsCoalescedB", 2),
    ("MaxOccupancy", 12),
    ("AggressivePerfMode", 2),
    ("FractionalLoad", 1),
    ("NonTemporalA", True),
    ("NonTemporalB", True),
    ("GlobalLoadVectorWidthA", 2),
    ("GlobalLoadVectorWidthB", 2),
    ("AssertFree0ElementMultiple", 2),
    ("AssertFree1ElementMultiple", 2),
    ("StaggerU", 8),
    ("GlobalSplitU", 1),
])
def test_sweep_knob_reaches_fork(driver, tmp_path, key, value):
    """Each knob the deck sets must arrive in ForkParameters at its value."""
    fork = _fork(driver, {key: value}, tmp_path)
    assert key in fork, f"{key} dropped by _fork_params (benchmarks at default)"
    assert fork[key] == (int(value) if isinstance(value, bool) else value), \
        f"{key} cast wrong: {fork[key]!r}"


def test_prefetch_global_read_2_is_not_collapsed_to_1(driver, tmp_path):
    """Regression: bool(2) is True, which Tensile reads as PGR=1."""
    fork = _fork(driver, {"PrefetchGlobalRead": 2}, tmp_path)
    assert fork["PrefetchGlobalRead"] == 2


def test_local_split_u_rides_workgroup_index_2(driver, tmp_path):
    """Tensile has no standalone LocalSplitU key; WorkGroup[2] carries it."""
    fork = _fork(driver, {"LocalSplitU": 2}, tmp_path)
    wg = fork["WorkGroup"]
    wg = wg[0] if isinstance(wg, list) and wg and isinstance(wg[0], list) else wg
    assert list(wg)[2] == 2, f"LSU lost: WorkGroup={wg!r}"


def test_every_sweep_value_key_is_forwarded(driver, tmp_path):
    """Blanket guard: no KNOB_SWEEPS value key may silently default."""
    probes = {
        "UseSgprForGRO": True, "InnerUnroll": 2, "PrefetchGlobalRead": 1,
        "NumLoadsCoalescedA": 2, "NumLoadsCoalescedB": 2, "MaxOccupancy": 12,
        "AggressivePerfMode": 2, "GlobalSplitU": 1, "LocalSplitU": 2,
        "StaggerU": 8, "FractionalLoad": 1, "NonTemporalA": True,
        "NonTemporalB": True, "GlobalLoadVectorWidthA": 2,
        "GlobalLoadVectorWidthB": 2, "AssertFree0ElementMultiple": 2,
        "AssertFree1ElementMultiple": 2,
    }
    keys = {k for sweep in KNOB_SWEEPS for value in sweep["values"]
            for k in value} | {"LocalSplitU"}
    assert set(probes) >= keys, \
        f"new sweep key needs a probe value: {sorted(keys - set(probes))}"
    for key in sorted(keys):
        probe = {k: probes[k] for k in probes
                 if k in ("GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
                          "AssertFree0ElementMultiple",
                          "AssertFree1ElementMultiple")} \
            if key in ("GlobalLoadVectorWidthA", "GlobalLoadVectorWidthB",
                       "AssertFree0ElementMultiple",
                       "AssertFree1ElementMultiple") else {key: probes[key]}
        fork = _fork(driver, probe, tmp_path)
        if key == "LocalSplitU":
            wg = fork["WorkGroup"]
            wg = wg[0] if isinstance(wg, list) and wg \
                and isinstance(wg[0], list) else wg
            assert list(wg)[2] == 2, f"LSU lost: WorkGroup={wg!r}"
        else:
            assert key in fork, f"{key} silently dropped by _fork_params"
