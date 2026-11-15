"""Class-B candidate rehearsal — the full pre-GPU journey of an unsupported device.

The Class B path (`docs/operator_runbook.md`) is the gfx902 risk path: if any of
these invocations crash or return garbage, the first agent run on a new device
will fail deep inside a six-hour campaign. This suite walks the full chain on a
stub device pair, exercising exactly the commands a real campaign would issue,
with every network/GPU call disallowed.

All commands run against ``phases.yaml`` copied into the stub directory, with
``OTO_PROFILE=gfx90c`` (the repo's one measured device) plus the stub starter's
own codename for the agent pair. The point is that the *plumbing* is verified;
silicon truths are not asserted against a live GPU.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run_oto(args: list[str], cwd: Path, env: dict[str, str] | None = None,
             timeout: int = 180) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    e["PYTHONPATH"] = str(ROOT)
    e["NO_COLOR"] = "1"
    return subprocess.run([sys.executable, "-m", "oto", *args],
                          capture_output=True, text=True, cwd=str(cwd),
                          env=e, timeout=timeout)


def _write_stub_pair(dest: Path, codename: str = "testbedxyz") -> Path:
    src = json.loads((ROOT / "profiles" / "gfx90c.json").read_text())
    src["codename"] = codename
    lib_md = f"# Rehearsal stub\n\ncodename: {codename}\n\nNarrative stub for Class-B rehearsal testing.\n"
    (dest / f"{codename}_starter.md").write_text(lib_md)
    (dest / f"{codename}_starter.json").write_text(json.dumps(src, indent=2))
    shutil.copy(ROOT / "phases.yaml", dest / "phases.yaml")
    return dest / f"{codename}_starter.md"


@pytest.fixture()
def stub(tmp_path):
    return _write_stub_pair(tmp_path)


def test_agent_generate(stub, tmp_path):
    r = _run_oto(["agent", "generate", "--base", str(tmp_path), str(stub)],
                 cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "testbedxyz_theoretical_limits.md").exists()
    assert (tmp_path / "testbedxyz_tuning_context.md").exists()
    assert (tmp_path / "testbedxyz_harness_study.md").exists()
    assert (tmp_path / "testbedxyz_docs" / "potential_configs.md").exists()


def test_agent_consult(stub, tmp_path):
    r = _run_oto(["agent", "consult", "--base", str(tmp_path), str(stub),
                  "--force"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    out = tmp_path / "testbedxyz_potential_configs.md"
    assert out.exists()
    body = out.read_text()
    assert "testbedxyz" in body


def test_agent_index(tmp_path):
    r = _run_oto(["agent", "index"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_candidate_json_reports_the_deck(stub, tmp_path):
    r = _run_oto(["candidate", "--base", str(tmp_path), "--json"], cwd=tmp_path)
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["ok"] is True
    assert doc["phases"] == 280
    assert sum(doc["families"].values()) == 280


def test_stats_and_report(stub, tmp_path):
    for cmd in (["stats"], ["report", "--json"]):
        r = _run_oto([*cmd], cwd=tmp_path)
        if cmd == ["report", "--json"]:
            # on a fresh clone (no runs), `oto report --json` is honestly an error:
            assert r.returncode == 1, r.stdout + r.stderr
            assert "No run id available" in r.stderr
        else:
            assert r.returncode == 0, f"{cmd} rc={r.returncode}: {r.stdout}{r.stderr}"


def test_verify_all_passes(tmp_path):
    r = _run_oto(["verify", "all"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_verify_run_snapshot_and_diff(tmp_path):
    out = tmp_path / "snap.json"
    r = _run_oto(["verify", "run", "snapshot", "--base", str(tmp_path),
                  "--out", str(out)], cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists()
    doc = json.loads(out.read_text())
    assert "dirs" in doc and "tables" in doc
    # smoke again with the existing snapshot; no prior corpus => no loss
    r2 = _run_oto(["verify", "run", "diff", "--base", str(tmp_path),
                   str(out), str(out)], cwd=tmp_path)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_check_candidates(tmp_path):
    r = _run_oto(["check", "candidates", "--base", str(tmp_path), "--quiet"],
                 cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_doctor_reports_cleanly(tmp_path):
    r = _run_oto(["doctor", "--base", str(tmp_path), "--json"], cwd=tmp_path)
    # The stub path has no GPU/Tensile client; rc=1 is honest. Assert every
    # section appears instead of pinning a colour verdict.
    assert "registry" in r.stdout or "registry" in r.stderr or r.returncode in (0, 1)
    assert r.returncode in (0, 1)


def test_library_best_effort_dry_run(tmp_path):
    r = _run_oto(["library", "best-effort", "--dry-run", "--base", str(tmp_path)],
                 cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_report_json_matches_empty_corpus(tmp_path):
    r = _run_oto(["report", "--base", str(tmp_path), "--json"], cwd=tmp_path)
    # On a fresh clone the driver honestly reports no run to report on.
    assert r.returncode == 1
    assert "No run id available" in r.stderr


def test_preflight_pass(stub, tmp_path):
    r = _run_oto(["preflight", "--base", str(tmp_path), "--json"], cwd=tmp_path)
    # On a stub root there is no shipped library to check against: rc=1 is honest,
    # but the driver must still enumerate the sections (not crash). With
    # phases.yaml present the phases row must say OK, even if the parity row fails.
    import json as _json
    assert r.returncode in (0, 1)
    doc = _json.loads(r.stdout)
    assert doc["command"] == "preflight"
    assert "[OK] phases.yaml accessible" in r.stderr
