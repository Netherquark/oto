"""Refactor 2 Phase 1: DeviceProfile reproduces gfx90c constants exactly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.device import peaks as p
from oto.device.loader import load_profile
from oto.tensile.gates.vgpr_model import FAMILY_BYTES_PER_ELEMENT


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


def test_profile_reproduces_peaks():
    prof = load_profile("gfx90c")
    assert dict(prof.peak_gflops) == dict(p.PEAK_GFLOPS)
    assert {k: list(v) for k, v in prof.family_shapes.items()} == {k: list(v) for k, v in p.FAMILY_SHAPES.items()}
    assert {k: list(v) for k, v in prof.family_cells.items()} == {k: list(v) for k, v in p.FAMILY_CELLS.items()}
    assert dict(prof.family_dtype_char) == dict(p.FAMILY_DTYPE_CHAR)
    assert dict(prof.family_dtypes) == dict(p.FAMILY_DTYPES)
    assert dict(prof.realistic_ceilings) == dict(p.REALISTIC_CEILINGS)
    assert dict(prof.realistic_ceilings_blas8) == dict(p.REALISTIC_CEILINGS_BLAS8)
    assert dict(prof.reported_to_blas8) == dict(p.REPORTED_TO_BLAS8)
    assert dict(prof.theoretical_peaks) == dict(p.THEORETICAL_PEAKS)
    assert dict(prof.theoretical_peaks_blas8) == dict(p.THEORETICAL_PEAKS_BLAS8)
    assert dict(prof.family_bytes_per_element) == dict(FAMILY_BYTES_PER_ELEMENT)


def test_profile_loader_missing_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_profile("gfx9999")
