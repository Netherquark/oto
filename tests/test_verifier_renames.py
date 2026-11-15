#!/usr/bin/env python3
"""Evergreen guard: the RENAMES table the symbol equivalence check reads.

``18444bd`` compressed RENAMES to fit the 600-line file budget and silently
dropped two real mappings (``ldspad_gate.py`` -> ``ldspad.py``,
``occupancy_common.py`` -> ``gate_common.py``), after which the split-era
comparison reported whole-module public-API loss. The table now lives in
drift_manifest.json, outside the line budget, and this test pins the two
mappings that were lost and the load-bearing invariant that every target in
the table exists in the working tree.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "oto" / "tools" / "verifiers" / "drift_manifest.json"

# The two mappings 18444bd dropped. Losing either again must fail loudly here.
RESTORED = {
    "oto/tensile/gates/ldspad_gate.py": "oto/tensile/gates/ldspad.py",
    "oto/tensile/gates/occupancy_common.py": "oto/tensile/gates/gate_common.py",
}


def test_renames_table_present_and_nonempty():
    doc = json.loads(MANIFEST.read_text())
    renames = doc.get("renames")
    assert isinstance(renames, dict) and renames, "drift_manifest 'renames' missing/empty"


def test_restored_gates_mappings_present():
    doc = json.loads(MANIFEST.read_text())
    renames = doc["renames"]
    for old, new in RESTORED.items():
        assert renames.get(old) == new


def test_every_rename_target_exists():
    doc = json.loads(MANIFEST.read_text())
    missing = [new for new in doc["renames"].values()
               if not (ROOT / new).exists()]
    assert not missing, f"RENAMES target(s) do not exist: {missing}"
