"""DeviceProfile loads and decides device identity; canonical accessor."""

# 'probe_test' is a fabricated probe: an ISA (9,9,99) device that never shipped.
# It exists only to prove the explicit-profile threading seam is load-bearing
# (profile facts flip verdicts, ambient resolution stays out of the way). It is
# NEVER a description of gfx90c or any real silicon that appeared in this tree.
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
    # The committed default is gfx90c by owner decision (this is the distribution
    # target); if the checkout someday ships another default device, this test is
    # the canary, not the invariant -- the invariant lives in the loader.
    assert _loader.DEFAULT_CODENAME == "gfx90c"
    assert _loader.current_profile().codename == _loader.DEFAULT_CODENAME


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
    p2 = dataclasses.replace(p1, codename="probe_test", isa=(9, 9, 99),
                             num_cus=64, max_clock_mhz=1500)
    assert p2.num_cus == 64
    assert p2.max_clock_mhz == 1500
    assert p1.num_cus != p2.num_cus


def test_bound_profile_restores():
    import dataclasses
    probe = dataclasses.replace(
        load_profile("gfx90c"), codename="probe_test", isa=(9, 9, 99), num_cus=64)
    before = _loader.current_profile().codename
    with _loader.bound_profile(probe):
        assert _loader.current_profile().codename == "probe_test"
    assert _loader.current_profile().codename == before


def test_resolve_profile_prefers_explicit():
    import dataclasses
    probe = dataclasses.replace(load_profile("gfx90c"), codename="probe_test")
    assert _loader.resolve_profile(probe).codename == "probe_test"
    # Ambient resolution is whatever the loader resolved; explicit always wins.
    assert _loader.resolve_profile(probe).codename != _loader.current_profile().codename
    assert _loader.resolve_profile(None).codename == _loader.current_profile().codename


def test_resolve_profile_none_is_ambient_not_error():
    assert _loader.resolve_profile() is _loader.current_profile()


def test_ambient_profile_is_loadable_everywhere():
    """Whatever the loader resolved on this machine, it must round-trip.

    The gfx90c anchor tests above use the in-repo profile. The ambient device
    is the detected one (or the committed fallback); its own file must load by
    codename so a gfx902 box whose profile lands can run this file verbatim.
    """
    cur = _loader.current_profile()
    assert isinstance(cur.codename, str) and cur.codename
    assert load_profile(cur.codename).codename == cur.codename
    # The committed default always ships in this repo; if it does not, the tree
    # is broken, not the device.
    assert load_profile(_loader.DEFAULT_CODENAME).codename == _loader.DEFAULT_CODENAME
