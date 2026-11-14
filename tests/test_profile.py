"""DeviceProfile loads and decides device identity; canonical accessor."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from oto.device import loader as _loader
from oto.device.loader import load_profile


def test_gfx90c_profile_loads():
    prof = load_profile("gfx90c")
    assert prof.codename == "gfx90c"
    assert prof.isa == (9, 0, 12)
    assert prof.num_cus == 7
    assert prof.max_clock_mhz == 1800
    assert prof.lds_per_cu_kb == 64
    assert prof.vgpr_per_cu == 65536
    assert prof.has_mfma is False
    assert prof.has_dp4a is False
    assert prof.global_load_byte_cap == 16
    assert prof.spoof_reference == "gfx900"


def test_current_profile_defaults_to_the_committed_device():
    assert _loader.current_profile().codename == "gfx90c"


def test_profile_tables_consistent():
    prof = load_profile("gfx90c")
    for fam in prof.family_shapes:
        assert fam in prof.family_dtype_char
        assert fam in prof.family_dtypes
        assert fam in prof.realistic_ceilings
        assert fam in prof.family_bytes_per_element
    assert prof.isa == (9, 0, 12)


def test_profile_loader_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_profile("gfx9999")


def test_synthetic_profile_differs():
    import dataclasses
    p1 = load_profile("gfx90c")
    p2 = dataclasses.replace(p1, codename="synthetictest", isa=(9, 9, 99),
                             num_cus=64, max_clock_mhz=1500)
    assert p2.num_cus == 64
    assert p2.max_clock_mhz == 1500
    assert p1.num_cus != p2.num_cus


def test_bound_profile_restores():
    p1 = load_profile("gfx90c")
    synthetic = __import__("dataclasses").replace(
        p1, codename="synthetictest", isa=(9, 9, 99), num_cus=64)
    with _loader.bound_profile(synthetic):
        assert _loader.current_profile().codename == "synthetictest"
    assert _loader.current_profile().codename == "gfx90c"


def test_resolve_profile_prefers_explicit():
    import dataclasses
    synthetic = dataclasses.replace(load_profile("gfx90c"), codename="synthetictest")
    assert _loader.resolve_profile(synthetic).codename == "synthetictest"
    # Ambient default is gfx90c on this machine; explicit always wins.
    assert _loader.resolve_profile(None).codename == "gfx90c"


def test_resolve_profile_none_is_ambient_not_error():
    assert _loader.resolve_profile() is _loader.current_profile()
