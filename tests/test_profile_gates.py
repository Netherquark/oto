"""Refactor 2 Phase 6: gate tests run against a second (synthetic) profile."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dataclasses

from oto.device.loader import load_profile
from oto.tensile.gates.assembly import assembly_class_valid
from oto.tensile.gates.occupancy import ldspad_feasible, occupancy_feasible
from oto.device import loader as _loader


def _synthetic():
    base = load_profile("gfx90c")
    return dataclasses.replace(base, codename="synthetictest", isa=(9, 9, 99),
                               num_cus=64, max_clock_mhz=1500)


def test_second_profile_gates_run():
    """The gates must not crash on a non-gfx90c profile."""
    prof = _synthetic()
    _loader.rebind_profile(prof)
    # A simple config should be evaluated (pass or fail, not crash)
    cfg = {"DataType": "S", "MacroTile": "64x64x8", "ThreadTile": "4x4",
           "VectorWidth": 2, "DepthU": 8, "GlobalSplitU": 1,
           "WorkGroup": "16x16x1", "WorkGroupMapping": 4}
    ok1, _ = assembly_class_valid(cfg, profile=prof)
    ok2, _ = occupancy_feasible(cfg, profile=prof)
    ok3, _ = ldspad_feasible(cfg, profile=prof)
    assert isinstance(ok1, bool)
    assert isinstance(ok2, bool)
    assert isinstance(ok3, bool)
    # restore default
    _loader.rebind_profile(load_profile("gfx90c"))


def test_profile_switching_restores_gfx90c():
    """Switching profiles must not leak state."""
    p1 = load_profile("gfx90c")
    p2 = dataclasses.replace(load_profile("gfx90c"),
                             codename="synthetictest", isa=(9, 9, 99),
                             num_cus=64, max_clock_mhz=1500)
    _loader.rebind_profile(p2)
    assert load_profile("gfx90c").num_cus == 7
    _loader.rebind_profile(p1)
    assert load_profile("gfx90c").num_cus == 7


def test_gfx90c_profile_restored_after_second():
    """After testing with a second profile, restoring gfx90c keeps gates working."""
    from oto.device.loader import load_profile
    p1 = load_profile("gfx90c")
    p2 = dataclasses.replace(load_profile("gfx90c"),
                             codename="synthetictest", isa=(9, 9, 99),
                             num_cus=64, max_clock_mhz=1500)
    _loader.rebind_profile(p2)
    assert p2.num_cus == 64
    _loader.rebind_profile(p1)
    assert p1.num_cus == 7
    # gates still work after restore
    cfg = {"DataType": "S", "MacroTile": "64x64x8", "ThreadTile": "4x4",
           "VectorWidth": 2, "DepthU": 8, "GlobalSplitU": 1,
           "WorkGroup": "16x16x1", "WorkGroupMapping": 4}
    from oto.tensile.gates.assembly import assembly_class_valid
    from oto.tensile.gates.occupancy import ldspad_feasible, occupancy_feasible
    ok1, _ = assembly_class_valid(cfg)
    ok2, _ = occupancy_feasible(cfg)
    ok3, _ = ldspad_feasible(cfg)
    assert isinstance(ok1, bool)
    assert isinstance(ok2, bool)
    assert isinstance(ok3, bool)


import pytest


@pytest.mark.parametrize("synthetic", [False, True])
def test_gates_dont_crash_on_profile(synthetic):
    """Gates evaluate without crashing on any registered profile."""
    from oto.device.loader import load_profile
    from oto.tensile.gates.assembly import assembly_class_valid
    from oto.tensile.gates.occupancy import ldspad_feasible, occupancy_feasible
    prof = load_profile("gfx90c")
    if synthetic:
        prof = dataclasses.replace(prof, codename="synthetictest", isa=(9, 9, 99),
                                   num_cus=64, max_clock_mhz=1500)
    _loader.rebind_profile(prof)
    cfg = {"DataType": "S", "MacroTile": "64x64x8", "ThreadTile": "4x4",
           "VectorWidth": 2, "DepthU": 8, "GlobalSplitU": 1,
           "WorkGroup": "16x16x1", "WorkGroupMapping": 4}
    for fn in (assembly_class_valid, occupancy_feasible, ldspad_feasible):
        ok, _ = fn(cfg, profile=prof)
        assert isinstance(ok, bool)
    _loader.rebind_profile(load_profile("gfx90c"))
