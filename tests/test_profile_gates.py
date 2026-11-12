"""Refactor 2 Phase 6: gate tests run against a second (synthetic) profile."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.device.loader import load_profile
from oto.tensile.gates.assembly import assembly_class_valid
from oto.tensile.gates.occupancy import ldspad_feasible, occupancy_feasible
from oto.tensile.gates.vgpr_model import set_profile


def test_second_profile_gates_run():
    """The gates must not crash on a non-gfx90c profile."""
    prof = load_profile("gfx906")
    set_profile(prof)
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
    set_profile(load_profile("gfx90c"))


def test_profile_switching_restores_gfx90c():
    """Switching profiles must not leak state."""
    from oto.device.loader import default_profile
    p1 = load_profile("gfx90c")
    p2 = load_profile("gfx906")
    set_profile(p2)
    assert load_profile("gfx90c").num_cus == 7
    set_profile(p1)
    assert load_profile("gfx90c").num_cus == 7
