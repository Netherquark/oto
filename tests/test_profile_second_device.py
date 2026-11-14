"""Second-profile gate tests (Refactor 2, C6.2-C6.4).

Proves the ``DeviceProfile`` seam is load-bearing, not decorative: binding a
*different* profile flips gate inputs and verdicts, and restoring returns
gfx90c's exact constants. The synthetic profile is derived from
``gfx90c.json`` with two fields overridden (halved VGPR file, 8-byte
load cap) so at least one gate flips a verdict while everything else stays
identical to a genuinely different device.

Calibrated constants (``LDS_BUDGET``, ``MAX_LDS_BYTES``, ``ACCVGPR_BUDGET``)
are deliberately NOT profile-rebound: they are calibration results of this
repo, not device facts. Only ``VGPR_PER_CU`` / ``GLOBAL_LOAD_BYTE_CAP`` /
``LDS_PER_CU_KB`` are.
"""
from __future__ import annotations

import dataclasses

import pytest

from oto.device.loader import load_profile
from oto.tensile.gates import loads, occupancy, vgpr_model

SYNTH_FIELDS = {"vgpr_per_cu": 32768, "global_load_byte_cap": 8}


def _synthetic_device():
    base = load_profile("gfx90c")
    return dataclasses.replace(
        base,
        codename="synthetictest",
        isa=(9, 9, 99),
        num_cus=64,
        max_clock_mhz=1500,
        peak_gflops={**base.peak_gflops, "FP32": base.peak_gflops["FP32"] * 7},
        realistic_ceilings={k: v + 1 for k, v in base.realistic_ceilings.items()},
    )


@pytest.fixture(scope="module")
def synthetic_profile():
    return dataclasses.replace(_synthetic_device(), **SYNTH_FIELDS)


@pytest.fixture(scope="module")
def default_profile():
    return load_profile("gfx90c")


def test_synthetic_profile_differs_from_gfx90c():
    p = _synthetic_device()
    assert p.codename == "synthetictest"
    assert p.isa == (9, 9, 99)
    assert p.num_cus == 64
    assert p.num_cus != load_profile("gfx90c").num_cus
    assert p.family_shapes and p.peak_gflops


def test_profiles_round_trip_peaks():
    a, b = load_profile("gfx90c"), _synthetic_device()
    assert a.peak_gflops["FP32"] != b.peak_gflops["FP32"]
    assert a.realistic_ceilings != b.realistic_ceilings


def test_bound_profile_rebinds_downstream_modules(synthetic_profile, default_profile):
    """The gate modules read import-time snapshots; the rebind must reach them."""
    assert occupancy.VGPR_PER_CU == default_profile.vgpr_per_cu
    assert loads.GLOBAL_LOAD_BYTE_CAP == default_profile.global_load_byte_cap
    with vgpr_model.bound_profile(synthetic_profile):
        assert vgpr_model.VGPR_PER_CU == 32768
        assert occupancy.VGPR_PER_CU == 32768
        assert loads.GLOBAL_LOAD_BYTE_CAP == 8
    # A scope exit is a full restore, byte-for-byte back to gfx90c.
    assert vgpr_model.VGPR_PER_CU == default_profile.vgpr_per_cu
    assert occupancy.VGPR_PER_CU == default_profile.vgpr_per_cu
    assert loads.GLOBAL_LOAD_BYTE_CAP == default_profile.global_load_byte_cap


def test_restore_even_on_exception(synthetic_profile, default_profile):
    with pytest.raises(RuntimeError):
        with vgpr_model.bound_profile(synthetic_profile):
            raise RuntimeError("boom")
    assert occupancy.VGPR_PER_CU == default_profile.vgpr_per_cu
    assert loads.GLOBAL_LOAD_BYTE_CAP == default_profile.global_load_byte_cap


def _dd_config() -> dict:
    # WorkGroup sets both the thread count (16x16x2 = 512) and the
    # LocalSplitU the occupancy gate actually models.
    return {
        "MacroTile": "64x64x16",
        "ThreadTile": "4x4",
        "DataType": "D",
        "ProblemType": "Contraction",
        "WorkGroup": [16, 16, 2],
    }


def test_register_file_verdict_follows_the_profile(synthetic_profile):
    cfg = _dd_config()
    ok, _ = occupancy.occupancy_feasible(cfg)
    assert ok is True
    ok2, reason = occupancy.occupancy_feasible(cfg, profile=synthetic_profile)
    assert ok2 is False
    assert "VGPR" in reason or "register" in reason.lower()


def test_load_cap_verdict_follows_the_profile(synthetic_profile):
    # SS element = 4 bytes: VW 4 is exactly legal at the 16 B cap and illegal
    # at the synthetic 8 B cap (bound 1 of the gate's three bounds).
    assert loads.cap_vector_width("SS", "64x64x16", "4x4") == 4
    with vgpr_model.bound_profile(synthetic_profile):
        assert loads.cap_vector_width("SS", "64x64x16", "4x4") == 2
