#!/usr/bin/env python3
"""_write_phase_config equivalence.

The config writer is the one method that was genuinely restructured, so it gets
its own differential: for every phase in the live deck (and the reference decks),
the OLD implementation and the NEW one must agree on (ok, reason) AND on the
exact YAML bytes written.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

#: The last commit before the package split; every check compares against it.
REFACTOR_BASE = "2824c2f"

SRC = subprocess.run(["git", "show", f"{REFACTOR_BASE}:port_tensile.py"], cwd=ROOT,
                     capture_output=True, text=True, check=True).stdout


#: Redirects the pre-refactor module's flat sibling imports at their new homes
#: so it can be executed against the current tree.
LIFT = {
    "from scheduler import (parse_tensile_shape, assembly_class_valid,\n"
    "                               occupancy_feasible, ldspad_feasible)":
        "from oto.tensile.candidate import parse_tensile_shape\n"
    "        from oto.tensile.gates.assembly import assembly_class_valid\n"
    "        from oto.tensile.gates.occupancy import (ldspad_feasible,\n"
    "                                             occupancy_feasible)",
    "from scheduler import assembly_class_valid":
        "from oto.tensile.gates.assembly import assembly_class_valid",
    "from run_status import LiveStatus, RunPlan":
        "from oto.metrics.run_status import LiveStatus, RunPlan",
    "from auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS":
        "from oto.runners.auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS",
    "from auto_prompt import AutoPlan, ask":
        "from oto.runners.auto_prompt import AutoPlan, ask",
    "from library_parity import load_pipeline_phases, parity_report":
        "from oto.tensile.library_parity import load_pipeline_phases, parity_report",
    "from analytics import extract_family_from_phase_id":
        "from oto.metrics.analytics import extract_family_from_phase_id",
    "from policy import check_retirement_eligibility":
        "from oto.metrics.policy import check_retirement_eligibility",
    "from report import ABVerdict":
        "from oto.metrics.report import ABVerdict",
}


def lift(src: str) -> str:
    """Rewrite a pre-refactor source's flat imports to their new module paths."""
    for old_text, new_text in LIFT.items():
        src = src.replace(old_text, new_text)
    return src


def load_old():
    """The HEAD port_tensile module, with the flat imports redirected."""
    import types
    for name in ("registry", "scheduler", "analytics", "gfx90c_common",
                 "policy", "agent", "mutator", "report", "telemetry",
                 "library_parity"):
        if name in sys.modules:
            del sys.modules[name]
    import oto.device.peaks as peaks
    fake = types.ModuleType("gfx90c_common")
    for attr in dir(peaks):
        if not attr.startswith("_"):
            setattr(fake, attr, getattr(peaks, attr))
    sys.modules["gfx90c_common"] = fake
    shims = {}
    for old, new in (("registry", "oto.ledger.registry"),
                     ("scheduler", "oto.tensile.candidate"),
                     ("analytics", "oto.metrics.analytics"),
                     ("policy", "oto.metrics.policy"),
                     ("agent", "oto.ledger.agent"),
                     ("mutator", "oto.ledger.mutator"),
                     ("report", "oto.metrics.report"),
                     ("telemetry", "oto.metrics.telemetry"),
                     ("library_parity", "oto.tensile.library_parity")):
        shims[old] = importlib.import_module(new)
        sys.modules[old] = shims[old]
    sys.modules["auto_prompt"] = importlib.import_module("oto.runners.auto_prompt")
    sys.modules["tensile_library"] = importlib.import_module("oto.tensile.library")
    sys.modules["run_status"] = importlib.import_module("oto.metrics.run_status")
    sys.modules["port_tensile"] = importlib.import_module("oto.runners.cli")
    mod = types.ModuleType("old_port_tensile")
    mod.__file__ = str(ROOT / "port_tensile.py")
    mod.__dict__["__name__"] = "old_port_tensile"
    SRC2 = lift(SRC)
    exec(compile(SRC2, str(ROOT / "port_tensile.py"), "exec"), mod.__dict__)
    return mod


import importlib  # noqa: E402

old = load_old()
from oto.tensile import config_writer  # noqa: E402
from oto.runners.driver import TensileDriver  # noqa: E402


class _Stub:
    pass


def phases_from(path):
    phases = []
    for f in sorted(Path(path).glob("*/phases_reference.yaml")):
        try:
            phases.extend(yaml.safe_load(f.read_text()) or [])
        except Exception:
            continue
    return phases


all_phases = yaml.safe_load((ROOT / "phases.yaml").read_text()) or []
all_phases += phases_from(ROOT / "gfx90c_runs")
all_phases += phases_from(ROOT / "gfx90c_results" / "gfx900_ref_locked_52149f315d")
print(f"phases under test: {len(all_phases)}")

d = _Stub()
mismatch = []
n_ok = n_refused = 0
with tempfile.TemporaryDirectory() as td:
    a_path = Path(td) / "a.yaml"
    b_path = Path(td) / "b.yaml"
    for p in all_phases:
        ro, rr = old.TensileDriver._write_phase_config(d, a_path, p)
        rn, rn_reason = config_writer.write_phase_config(d, b_path, p)
        if (ro, rr) != (rn, rn_reason):
            mismatch.append((p.get("phase_id"), (ro, rr), (rn, rn_reason)))
            continue
        if ro and a_path.read_bytes() != b_path.read_bytes():
            mismatch.append((p.get("phase_id"), "YAML DIFFERS",
                             (a_path.read_text()[:120], b_path.read_text()[:120])))
            continue
        if ro:
            n_ok += 1
        else:
            n_refused += 1

print(f"written: {n_ok}, refused: {n_refused}")
print(f"mismatches: {len(mismatch)}")
for m in mismatch[:6]:
    print("  ", m)
if mismatch:
    sys.exit(1)
print("CONFIG WRITER EQUIVALENCE: OK")
