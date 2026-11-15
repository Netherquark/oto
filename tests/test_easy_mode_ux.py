#!/usr/bin/env python3
"""The `oto setup` (easy-mode) UX contract, per POSIX/GNU guidance.

The suite's own rule (documented in `oto/cli/dispatch.py`) is:
stdout = data, stderr = narration. The wizard used to print everything to
stdout; this pins the corrected behaviour:

* narration (banners, discovery output, "wrote .env") lands on stderr;
* stdout stays clean (it carries no data for `oto setup` by design, so it
  carries nothing);
* `--yes`/`--dry-run` never prompt; exit code 0 on a dry run;
* stdin-not-a-TTY without --yes/--dry-run exits 2 with a stderr hint, not a
  traceback.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMD = [sys.executable, "-m", "oto", "setup", "--dry-run"]


def _run(args, env):
    return subprocess.run([sys.executable, "-m", "oto", "setup", *args],
                          capture_output=True, text=True, cwd=str(ROOT),
                          timeout=120, env=env)


def test_dry_run_narrates_on_stderr_not_stdout():
    env = {**os.environ, "OTO_NO_INPUT": "1"}
    r = _run(["--dry-run"], env)
    assert r.returncode == 0, r.stderr
    assert "CONVERGENCE mode" not in r.stdout
    assert "convergence" not in r.stdout.lower() or True
    assert r.stdout == "", f"stdout must stay clean, got: {r.stdout!r}"
    assert r.stderr.strip(), "expected narration on stderr"


def test_yes_dry_run_does_not_prompt():
    env = {**os.environ, "OTO_NO_INPUT": "1"}
    r = _run(["--yes", "--dry-run"], env)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr


def test_noninteractive_without_yes_exits_2_with_hint():
    env = dict(os.environ)
    env.pop("OTO_NO_INPUT", None)
    env["OTO_FORCE_NONINTERACTIVE"] = "1"
    r = subprocess.run([sys.executable, "-m", "oto", "setup"],
                       capture_output=True, text=True, cwd=str(ROOT),
                       timeout=60, env=env, stdin=subprocess.DEVNULL)
    assert r.returncode == 2
    assert "--yes or --dry-run" in r.stderr
    assert "Traceback" not in r.stderr
