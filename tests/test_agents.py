"""Tests for Refactor 2 Phase 4/5: agents + potential_configs_gen."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.agents.meta import run as meta_run
from oto.agents.theoretical_limits import generate as gen_tl
from oto.agents.tuning_context import generate as gen_tc
from oto.device.loader import load_profile
from oto.tools.potential_configs_gen import generate as gen_pc


def test_agent1_generates_doc():
    prof = load_profile("gfx90c")
    doc = gen_tl(prof)
    assert prof.codename in doc
    assert "ALU peaks" in doc
    assert "Realistic ceilings" in doc


def test_agent2_generates_doc():
    prof = load_profile("gfx90c")
    tl = gen_tl(prof)
    doc = gen_tc(prof, tl)
    assert prof.codename in doc
    assert "Family shapes" in doc or "families" in doc.lower()


def test_meta_orchestrates():
    prof = load_profile("gfx90c")
    res = meta_run(prof)
    assert "theoretical_limits" in res
    assert "tuning_context" in res


def test_potential_configs_gen():
    prof = load_profile("gfx90c")
    from pathlib import Path
    doc = gen_pc(prof, Path("."))
    assert prof.codename in doc
