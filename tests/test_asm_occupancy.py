#!/usr/bin/env python3
"""
test_asm_occupancy.py — the measured-occupancy model.

Regression guards for the module that reads Tensile's emitted code objects and
turns them into resident-wave occupancy:

  * the VGPR-per-thread -> waves-per-SIMD function reproduces the AMD/ORNL GFX9
    table exactly, so a granule or file-size edit cannot silently change it;
  * the resource binder never claims LDS when none was measured, and never
    claims waveslots when the register file is what bound;
  * the Tensile result CSV column trap is defeated (GFLOP/s is the LAST field,
    not field 0 -- the header's field 0 is the literal string "GFlops");
  * the dtype fact table agrees with Tensile's own DataType: complex double is
    16 bytes and 8 flops-per-MAC, not 8 bytes.

Run: python3 -m pytest -q tests/test_asm_occupancy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.device.peaks import (
    LDS_PER_CU_KB,
    MAX_WAVES_PER_CU,
    NUM_SIMDS_PER_CU,
)
from oto.harness import asm_occupancy as ao

# The AMD/ORNL GFX9 table, VGPR/thread -> waves/SIMD. Reproduced here rather
# than imported because it is the oracle this module is calibrated against.
ORNL_TABLE = {24: 10, 28: 9, 32: 8, 36: 7, 40: 6,
              48: 5, 64: 4, 84: 3, 128: 2, 256: 1}


@pytest.mark.parametrize(("vgprs", "expected"), sorted(ORNL_TABLE.items()))
def test_waves_per_simd_matches_the_hardware_table(vgprs, expected):
    assert ao.waves_per_simd(vgprs) == expected


def test_granule_four_not_eight():
    """Granule 8 mispredicts V=28, 36 and 84; granule 4 does not.

    If this fails, someone "corrected" VGPR_GRANULE to the older 8/16 model.
    """
    assert ao.VGPR_GRANULE == 4
    for value in ORNL_TABLE:
        aligned_4 = -(-value // 4) * 4
        assert ao.SIMD_VGPR // (64 * aligned_4) == ORNL_TABLE[value]
        aligned_8 = -(-value // 8) * 8
        if ao.SIMD_VGPR // (64 * aligned_8) != ORNL_TABLE[value]:
            # the 8-granule model must fail somewhere, or the oracle is weak
            assert value in (28, 36, 84)


def test_waves_never_exceed_the_simd_cap():
    assert ao.waves_per_simd(8) == ao.WAVES_PER_SIMD_MAX
    assert ao.waves_per_simd(256) == 1
    assert ao.waves_per_simd(0) == 0


def test_zero_vgpr_is_not_zero_occupancy_signal():
    """0 must mean "not measured", so nobody plots it as a dead kernel."""
    assert ao.waves_per_simd(0) == 0


def test_binder_picks_the_smallest_bound():
    # 119 VGPRs -> 2 waves/SIMD = 8/CU; 8 KB LDS with 256 threads allows
    # 8 wg x 4 waves = 32/CU. The register file is what bound.
    binder, waves = ao.binding_resource(119, 8192, 256)
    assert binder == "VGPR"
    assert waves == 8
    # 40 VGPRs -> 6 waves/SIMD = 24/CU; a 65536 B tile allows one 4-wave
    # workgroup, so LDS is what bound.
    binder, waves = ao.binding_resource(40, 65536, 256)
    assert binder == "LDS"
    assert waves == 4


def test_tied_bounds_are_reported_not_broken_by_declaration_order():
    """Both resources cap identically -> say so; 15.9% of this corpus does."""
    # 29 VGPRs align to 32 -> 8 waves/SIMD = 32/CU; 8 KB LDS with 256 threads
    # = 8 wg x 4 waves = 32/CU. A tie.
    assert ao.binding_resource(29, 8192, 256)[0] == "LDS+VGPR"
    # 16 KB LDS with 256 threads = 4 wg x 4 waves = 16/CU, and 48 VGPRs ->
    # 5 waves/SIMD = 20/CU, so LDS caps below VGPR: still a real LDS bind.
    assert ao.binding_resource(48, 16384, 256)[0] == "LDS"


def test_unmeasured_lds_never_claims_lds_binding():
    binder, waves = ao.binding_resource(47, 0, 0)
    assert binder == "VGPR"
    # 47 VGPRs align to 48 at granule 4 -> 16384/(64*48) = 5 waves/SIMD = 20/CU
    assert waves == ao.waves_per_simd(47) * NUM_SIMDS_PER_CU == 20


def test_dtype_facts_agree_with_tensile_datatypes():
    """Complex double is 4 registers = 16 bytes and 8 flops/MAC."""
    assert ao._DTYPE_FACTS["Z"] == (16, 8)
    assert ao._DTYPE_FACTS["C"] == (8, 8)
    assert ao._DTYPE_FACTS["D"] == (8, 2)
    assert ao._DTYPE_FACTS["H"] == (2, 2)


def test_corpus_parses_when_present():
    """Guard the emitted-kernel reader against a missing or empty corpus."""
    rows = ao.measure_corpus(BASE / "gfx90c_runs")
    if not rows:
        pytest.skip("no gfx90c_runs corpus on this checkout")
    # every row that has a GFLOP/s number must have consumed the real field
    gfloated = [r for r in rows if r["gflops"] is not None]
    assert gfloated, "the CSV reader is reading the misaligned field 0"
    assert max(r["gflops"] for r in gfloated) > 1000, (
        "max corpus GFLOP/s under 1000: the result CSV column trap has "
        "regressed (GFLOP/s is the LAST field of a row, not field 0)")
    # no kernel in this corpus spills: scratch is 0 everywhere
    assert not [r for r in rows if r["scratch"]]


def test_corpus_occupancy_is_not_pathologically_low():
    """The corpus is not uniformly occupancy-starved; if this fails, the model
    or the assumptions behind MAX_WAVES_PER_CU changed."""
    rows = ao.measure_corpus(BASE / "gfx90c_runs")
    if not rows:
        pytest.skip("no gfx90c_runs corpus on this checkout")
    low = [r for r in rows if r["waves_per_cu"] <= 3]
    fraction = len(low) / len(rows)
    assert fraction < 0.25, (
        f"{len(low)}/{len(rows)} kernels at <=3 waves/CU: the granule, the "
        "SIMD file size, or MAX_WAVES_PER_CU is wrong")


def test_lds_and_caps_are_sourced_from_one_home():
    assert ao.LDS_PER_CU == LDS_PER_CU_KB * 1024
    assert ao.WAVES_PER_SIMD_MAX == MAX_WAVES_PER_CU // NUM_SIMDS_PER_CU
    assert ao.SIMD_VGPR * NUM_SIMDS_PER_CU == ao.VGPR_PER_CU
