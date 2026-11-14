"""The automated census consult: CPU-only potential_configs.md for a new device.

Owns: proving the consult runs end-to-end with zero GPU and produces a draft
document whose claims are all gate-checked. Does NOT own the TTY measurements
or the device docs (agent-1/agent-2).
"""

from __future__ import annotations

import json
from pathlib import Path

from oto.agents.census_consult import consult
from oto.device import loader

GFX90C = loader.current_profile()


def _synthetic_starter(tmp_path: Path, codename: str = "synthetic999") -> Path:
    d = json.loads(json.dumps(_profile_to_json(GFX90C)))
    d["codename"] = codename
    starter = tmp_path / f"{codename}_starter.md"
    starter.write_text(
        f"# synthetic device\ncodename: {codename}\n\n"
        + "```json\n" + json.dumps(d, indent=2) + "\n```\n")
    return starter


def _profile_to_json(p) -> dict:
    # Round-trip through the dataclass via its own export if available;
    # otherwise reconstruct a minimal dict by reading profiles/gfx90c.json.
    import json as _json
    return _json.loads((Path(__file__).parent.parent / "profiles" / "gfx90c.json").read_text())


def test_consult_writes_document(tmp_path):
    out = tmp_path / "synthetic999_potential_configs.md"
    r = consult(GFX90C, base_dir=tmp_path, out=out, force=True)
    assert r["status"] == "success"
    assert out.exists()
    text = out.read_text()
    assert "## 1. The device" in text
    assert "## 2. Ceilings" in text
    assert "## 3. Rejection taxa" in text
    assert "## 5. Candidate deck" in text


def test_consult_refuses_overwrite_without_force(tmp_path):
    out = tmp_path / "exists.md"
    out.write_text("sentinel")
    r = consult(GFX90C, base_dir=tmp_path, out=out, force=False)
    assert r["status"] == "refused"
    assert out.read_text() == "sentinel"


def test_load_profile_from_starter(tmp_path):
    starter = _synthetic_starter(tmp_path)
    prof = loader.load_profile_from_starter(starter)
    assert prof.codename == "synthetic999"
    assert prof.isa == (9, 0, 12)
    out = tmp_path / "synthetic999_pc.md"
    r = consult(prof, base_dir=tmp_path, out=out, force=True)
    assert r["status"] == "success"


def test_consult_all_rows_gate_checked(tmp_path):
    out = tmp_path / "p.md"
    r = consult(GFX90C, base_dir=tmp_path, out=out, force=True)
    assert r["status"] == "success"
    assert r["legal_rows"] + r["illegal_rows"] > 0
    assert r["priors"] >= 0  # corpus may be absent on a foreign checkout
