#!/usr/bin/env python3
"""
check_candidates.py — preflight every candidate config through the 4 legality gates.

Complements CandidateGenerator: that class produces candidates and gates
validate_config; this sweeps an EXTERNAL deck (phases.yaml) or a candidate list
through the same 4 gates, so a deck that would die mid-run with
`error 4` / `error 2` / `error 3` is rejected before any GPU work starts.

  1. divisibility        GLVW % mv/pv == 0 and % lpv == 0   (candidate gen)
  2. assembly class      MT/TT/DepthU/Threads/StaggerU/FP16 clamp
  3. LDS                 per-thread LDS in VGPR-equivalent registers
  4. register-file occupancy
                         numWorkGroupsPerCU = (65536 // NumThreads) // vgprs
                         < 1  =>  Tensile error 4  ("Occupancy limit")

Gates 1-3 are CandidateGenerator's. Gate 4 is scheduler.occupancy_feasible — the
model that reproduces every observed gfx90c outcome (see potential_configs.md
§5.7). Gate 4 is why a deck that passes 1-3 can still kill every ZZ phase.

CPU only. No Tensile invocation, no GPU.

Usage:
    python3 check_candidates.py                      # sweep phases.yaml
    python3 check_candidates.py --family ZZ
    python3 check_candidates.py --deck other.yaml
    python3 check_candidates.py --quiet              # only print failures
    python3 check_candidates.py --json out.json
Exit code 1 if any config fails, so it can gate a pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
for _p in (os.environ.get("TENSILE_ROOT"), "/home/netherquark/Soham/Large_code/sources/GPU/Tensile"):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from scheduler import (CandidateGenerator, assembly_class_valid,   # noqa: E402
                       occupancy_feasible, occupancy_workgroups_per_cu)

def _divisibility(gen, cfg):
    return gen.validate_config(cfg)


GATES = (
    ("divisibility", _divisibility),
    ("assembly", assembly_class_valid),
    ("occupancy", occupancy_feasible),
)


def _fams(cfg) -> str:
    return str(cfg.get("FamilyLabel") or "").upper()


def _reason_key(why: str) -> str:
    """validate_config wraps the occupancy failure as "Occupancy limit: <msg>".
    Normalise that away so the same underlying failure is only counted once."""
    return why.replace("Occupancy limit: ", "", 1)


def check_config(gen, cfg) -> list[tuple[str, str]]:
    """Return [(gate, reason)] for every failing gate. Empty == legal."""
    out = []
    seen: set[str] = set()
    for name, fn in GATES:
        ok, why = fn(gen, cfg) if name == "divisibility" else fn(cfg)
        if not ok and _reason_key(why) not in seen:
            # validate_config includes the occupancy gate, so the same failure
            # surfaces under two gate names. Report the specific one.
            seen.add(_reason_key(why))
            out.append((name if name != "divisibility" else _gate_of(why), why))
    return out


def _gate_of(why: str) -> str:
    return "occupancy" if why.startswith("Occupancy limit: ") else "divisibility"


def self_inconsistencies(phase: dict) -> list:
    """Deck bookkeeping that must agree with the config it describes.

    Both checks below caught real bugs that the legality check could not see:
    a config edited to a legal replacement while its phase_id and fp still
    described the old dead one. Nothing in Tensile reads either field, so the
    deck compiled cleanly and still lied about itself.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    problems = []
    cfg = phase.get("config") or {}
    pid = str(phase.get("phase_id", ""))

    # 1. an id that embeds MT/TT must match the config's MT/TT
    if "_mt" in pid and cfg.get("MacroTile") and cfg.get("ThreadTile"):
        want = f"mt{cfg['MacroTile']}_tt{cfg['ThreadTile']}"
        if want not in pid:
            problems.append(("id_config_mismatch",
                             f"phase_id describes {want}, but the config is "
                             f"{cfg['MacroTile']}/{cfg['ThreadTile']}"))

    # 2. the fingerprint must be the hash of the config actually stored
    stored = phase.get("fp")
    if stored:
        from registry import fingerprint_config
        if fingerprint_config(cfg) != stored:
            problems.append(("fp_stale",
                             f"fp {stored[:12]} is not the hash of the config "
                             f"({fingerprint_config(cfg)[:12]})"))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=Path, default=BASE / "phases.yaml")
    ap.add_argument("--base-dir", type=Path, default=BASE)
    ap.add_argument("--family", help="only check this family label")
    ap.add_argument("--quiet", action="store_true", help="print only failures")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    gen = CandidateGenerator(args.base_dir.resolve())
    deck = yaml.safe_load(args.deck.read_text())

    checked = skipped = 0
    fails: list[tuple[str, list]] = []
    fam_total: Counter = Counter()
    for phase in deck:
        cfg = phase.get("config") or {}
        fam = _fams(cfg)
        if args.family and fam != args.family.upper():
            skipped += 1
            continue
        checked += 1
        fam_total[fam or "?"] += 1
        bad = check_config(gen, cfg)
        bad = list(bad) + self_inconsistencies(phase)
        if bad:
            fails.append((phase.get("phase_id", "?"), bad))
        elif not args.quiet:
            wg = occupancy_workgroups_per_cu(cfg)
            print(f"  ok   {phase.get('phase_id','?')[:60]:60} wg/cu={wg}")

    print(f"\n{args.deck}: {checked} checked, {skipped} skipped, {len(fails)} illegal")
    if fam_total:
        print("  per family: " + ", ".join(f"{k}={v}" for k, v in sorted(fam_total.items())))
    for pid, bad in fails:
        for name, why in bad:
            print(f"  FAIL {pid[:60]:60} [{name}] {why}")

    if args.json:
        args.json.write_text(json.dumps(
            {"deck": str(args.deck), "checked": checked, "illegal": len(fails),
             "failures": {p: dict(b) for p, b in fails}}, indent=1, default=str))
        print(f"wrote {args.json}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
