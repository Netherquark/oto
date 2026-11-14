"""The deterministic limits derivation must equal the shipped profile.

Serves as the no-error contract for ``oto.device.derive`` — every ceiling in
``oto.device.loader.current_profile().theoretical_peaks_blas8`` and
``peak_gflops`` is re-derived from the hardware facts and compared
exactly. If the profile ever disagrees with the formula, the derivation is
what the limits doc says and the profile is what needs a reason recorded
next to it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import replace

import pytest

from oto.device import derive
from oto.device import loader as _loader
from oto.device.derive import (
    derive_lane_classes,
    derive_peak_gflops,
    derive_theoretical_peaks_blas8,
    lanes,
)

GFX90C = _loader.load_profile("gfx90c")


def test_lanes_from_hardware_facts():
    assert lanes(GFX90C) == GFX90C.num_cus * GFX90C.simds_per_cu * GFX90C.lanes_per_simd
    assert lanes(GFX90C) == 7 * 4 * 16 == 448


def test_lane_class_formula_exact():
    classes = derive_lane_classes(GFX90C)
    # FP32: 2 flops/FMA x 448 lanes x 1.8 GHz = 1612.8 GFLOPS -> 1613
    assert classes["FP32"] == 1613
    # FP16 fast F16 x2; FP64 = FP32 / 16 (GCN5 rate)
    assert classes["FP16"] == 3226
    assert classes["FP64"] == 101
    assert classes["BF16"] == 1613
    assert classes["INT8"] == 1613


def test_derived_peaks_equal_profile_blas8():
    """Every family peak in the profile equals the formula's output."""
    derived = derive_theoretical_peaks_blas8(GFX90C)
    stored = dict(GFX90C.theoretical_peaks_blas8)
    assert derived == stored, (
        f"derived {derived} != stored {stored}: either the profile or the "
        "formula is wrong; one of them is — fix whichever has no reason")


def test_derived_lane_class_peaks_equal_profile():
    derived = derive_peak_gflops(GFX90C)
    stored = dict(GFX90C.peak_gflops)
    assert derived == stored


def test_rounding_is_floor_half_up():
    classes = derive_lane_classes(GFX90C)
    # 448 * 2 * 1.8 = 1612.8; if anyone "simplifies" to int(fp32) it drifts
    assert classes["FP32"] - 2 * lanes(GFX90C) * GFX90C.max_clock_mhz // 1000 >= 1


def test_complex_family_equals_real_lane_class():
    derived = derive_theoretical_peaks_blas8(GFX90C)
    assert derived["CC"] == derived["SS"]
    assert derived["ZZ"] == derived["DD"]


def test_hpa_equals_fp32_roof():
    derived = derive_theoretical_peaks_blas8(GFX90C)
    assert derived["HH_HPA"] == derived["SS"]
    assert derived["HS_HPA"] == derived["SS"]


def test_hgemm_is_exactly_double_fp32():
    derived = derive_theoretical_peaks_blas8(GFX90C)
    assert derived["HH"] == 2 * derived["SS"]


def test_probe_device_derives_from_its_own_facts():
    """A hypothetical 8-CU part at 1500 MHz must derive its own numbers."""
    probe = replace(GFX90C, codename="probe_test", num_cus=8, max_clock_mhz=1500)
    classes = derive_lane_classes(probe)
    assert classes["FP32"] == int(8 * 4 * 16 * 2 * 1.5 + 0.5) == 1536
    assert classes["FP64"] == int(8 * 4 * 16 * 2 * 1.5 / 16 + 0.5) == 96
    derived = derive_theoretical_peaks_blas8(probe)
    # Profile tables must not be consulted for numbers; family peaks follow lanes
    assert derived["SS"] == classes["FP32"]
    assert derived["DD"] == classes["FP64"]
    assert derived["HH"] == 2 * derived["SS"]


def test_derive_module_cli_prints_and_exits_zero():
    import subprocess

    r = subprocess.run([sys.executable, "-m", "oto.device.derive"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "codename=gfx90c" in r.stdout
    assert '"SS": 1613' in r.stdout


def test_bandwidth_from_spec():
    assert derive.derive_bandwidth_gb_s(GFX90C) == 51.2


def test_bandwidth_refuses_guessing():
    import dataclasses
    zeroed = dataclasses.replace(
        GFX90C,
        theoretical=dataclasses.replace(
            GFX90C.theoretical, memory_channels=0, memory_rate_mtps=0))
    with pytest.raises(ValueError, match="memory_channels"):
        derive.derive_bandwidth_gb_s(zeroed)


def test_bandwidth_refuses_unknown_memory():
    import dataclasses
    bad = dataclasses.replace(
        GFX90C, theoretical=dataclasses.replace(GFX90C.theoretical,
                                                 memory_type="LPDDR9"))
    with pytest.raises(ValueError, match="memory_type"):
        derive.derive_bandwidth_gb_s(bad)


def test_machine_balance_is_peak_over_bandwidth():
    balance = derive.derive_machine_balance(GFX90C)
    bw = derive.derive_bandwidth_gb_s(GFX90C)
    for fam, v in balance.items():
        assert abs(v - GFX90C.theoretical_peaks_blas8[fam] / bw) < 1e-10, fam


def test_machine_balance_keys_are_family_keys():
    assert set(derive.derive_machine_balance(GFX90C)) == set(
        GFX90C.theoretical_peaks_blas8)
