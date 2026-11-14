#!/usr/bin/env python3
"""Guard the Tensile parameter snapshot used at the launch boundary.

Tensile aborts a phase outright on an unrecognised parameter name
(BenchmarkStructs.checkParametersAreValid -> printExit). The driver therefore
filters fork parameters against `_TENSILE_VALID_PARAMS` before writing a config.
That set is a snapshot, because Tensile is launched as a subprocess and cannot be
imported cheaply at launch time -- so it can silently rot when Tensile is
upgraded.

This test diffs the snapshot against the live Tensile list whenever Tensile is
importable, and separately pins the two behaviours that actually bit us:

  * `GlobalReduceVectorWidth` must never reach a written config. It came from
    reference metadata (`grvw`) and killed all 127 T1 reference reruns.
  * No config the driver writes may contain a non-Tensile parameter name.
"""

import re
import sys
import tempfile
from pathlib import Path

# This file lives in tests/, so the repo root is one level up. Used as the
# import root, as the driver's base_dir, and to locate phases.yaml and
# the runs dir is device-derived; the harness modules are imported flat
# file's parent.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import signal

import yaml

from oto.runners.driver import (
    _TENSILE_VALID_PARAMS,
    DEFAULT_TENSILE_ROOT,
    NOT_A_TENSILE_PARAM,
    TensileDriver,
    _require_tensile_root,
)
from oto.runners.paths import runs_rel
from oto.tensile import config_writer

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def live_tensile_params():
    try:
        root = Path(_require_tensile_root(
            None, DEFAULT_TENSILE_ROOT))
    except SystemExit:
        return None
    sys.path.insert(0, str(root))
    try:
        from Tensile.SolutionStructs import validParameters

        return set(validParameters.keys())
    except Exception as exc:
        print(f"  (live Tensile not importable: {exc})")
        return None


def driver():
    real = signal.signal
    signal.signal = lambda *a, **k: None  # driver installs SIGINT/SIGTERM handlers
    try:
        return TensileDriver(REPO_ROOT, create_run=False)
    finally:
        signal.signal = real


# 1. snapshot vs live Tensile
live = live_tensile_params()
if live is None:
    check("snapshot matches live Tensile", True, "skipped: Tensile not importable")
else:
    missing = sorted(live - set(_TENSILE_VALID_PARAMS))
    extra = sorted(set(_TENSILE_VALID_PARAMS) - live)
    check("snapshot covers every live Tensile param", not missing, f"missing={missing[:12]}")
    check("snapshot has no invented params", not extra, f"extra={extra[:12]}")

# 2. the parameter that actually broke the reference arm
check(
    "GlobalReduceVectorWidth classified as non-Tensile",
    "GlobalReduceVectorWidth" in NOT_A_TENSILE_PARAM,
)
check(
    "GlobalReduceVectorWidth absent from valid set",
    "GlobalReduceVectorWidth" not in _TENSILE_VALID_PARAMS,
)

# 3. end-to-end: no written config may carry a bad name
d = driver()
deck = REPO_ROOT / "phases.yaml"
phases = yaml.safe_load(deck.read_text()) or []
ref_file = REPO_ROOT / runs_rel("")
ref_candidates = sorted(ref_file.glob("*/phases_reference.yaml"))

# `ProblemSizes` is special-cased by Tensile and lives in BenchmarkFinalParameters.
SPECIAL = {"ProblemSizes"}

with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "p.yaml"
    bad_seen = {}
    for p in phases:
        wrote, why = config_writer.write_phase_config(d, out, p)
        if not wrote:
            continue
        names = set(re.findall(r"^\s{4}- (\w+):", out.read_text(), re.MULTILINE)) - SPECIAL
        bad = {n for n in names if n not in _TENSILE_VALID_PARAMS}
        if bad:
            bad_seen[p["phase_id"]] = sorted(bad)
    check(
        f"all {len(phases)} live phases write only valid Tensile params",
        not bad_seen,
        str(list(bad_seen.items())[:3]),
    )

    # reference phases are the ones that carried grvw; cover them explicitly
    checked_ref = 0
    ref_bad = {}
    grvw_leak = []
    for rf in ref_candidates:
        try:
            ref = yaml.safe_load(rf.read_text()) or []
        except Exception:
            continue
        for p in ref:
            wrote, why = config_writer.write_phase_config(d, out, p)
            checked_ref += 1
            if not wrote:
                continue
            txt = out.read_text()
            if "GlobalReduceVectorWidth" in txt:
                grvw_leak.append(p.get("phase_id"))
            names = set(re.findall(r"^\s{4}- (\w+):", txt, re.MULTILINE)) - SPECIAL
            bad = {n for n in names if n not in _TENSILE_VALID_PARAMS}
            if bad:
                ref_bad[p.get("phase_id")] = sorted(bad)
    check(
        f"all {checked_ref} reference phases write only valid Tensile params",
        not ref_bad,
        str(list(ref_bad.items())[:3]),
    )
    check(
        "no reference phase leaks GlobalReduceVectorWidth",
        not grvw_leak,
        f"{len(grvw_leak)} leaked e.g. {grvw_leak[:3]}",
    )

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all tensile-parameter guards passed")
