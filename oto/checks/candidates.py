#!/usr/bin/env python3
"""Is this deck Tensile-legal? The four-gate preflight.

Owns: sweeping an EXTERNAL deck (``phases.yaml``, a seed overlay, a candidate
JSON) through the same gates ``CandidateGenerator.validate_config`` applies to a
candidate it just produced, so a deck that would die mid-run with Tensile
``error 4`` / ``error 2`` / ``error 3`` is rejected before any GPU work starts.

Does NOT own: producing candidates (oto.tensile.candidate), the gates themselves
(oto.tensile.gates -- assembly, loads, occupancy), or the ledger (oto.ledger).

Public API: main, load_deck.

The gates run in the orchestrator's own order (illegal knobs, tile divisibility,
assembly class, classic-load divisibility, the LDS footprint, then register-file
occupancy), so a multi-failure config reports the same reason the driver would
have reported. The occupancy gate is a calibrated model, not Tensile's verdict;
``oto check tensile-build`` is the cross-check that asks Tensile itself.

    python3 -m oto check candidates                   # sweep phases.yaml
    python3 -m oto check candidates --family ZZ
    python3 -m oto check candidates --deck other.yaml
    python3 -m oto check candidates --deck <base>/<codename>_results/overlays/phases.seed.overlay.yaml
    python3 -m oto check candidates --quiet          # only print failures
    python3 -m oto check candidates --json > out.json

Exit code 1 if any config fails, so it can gate a pipeline. CPU only: no Tensile
invocation, no GPU.
"""


from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from oto import yamlio

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
for _p in (os.environ.get("TENSILE_ROOT"),):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from oto.device import loader as _loader
from oto.runners.paths import results_dir as _results_dir
from oto.tensile.candidate import CandidateGenerator
from oto.tensile.gates.assembly import assembly_class_valid
from oto.tensile.gates.occupancy import (
    occupancy_feasible,
    occupancy_workgroups_per_cu,
    tile_dims,
)
from oto.tensile.gates.vgpr_model import VGPR_PER_ELEMENT, measured_accvgpr
from oto.tensile.library import shipped_kernel_config


def _divisibility(gen, cfg):
    return gen.validate_config(cfg)


GATES = (
    ("divisibility", _divisibility),
    ("assembly", assembly_class_valid),
    ("occupancy", occupancy_feasible),
)


def _occupancy_margin(cfg, profile=None) -> str:
    """Human-readable register-file margin for a legal config.

    occupancy_workgroups_per_cu returns the modelled number of workgroups that
    fit the 64K file; the register-pressure % is the complementary view (how
    much of the file one workgroup's threads consume). Near-boundary configs —
    the ones that PASS today and die tomorrow when Tensile grows one
    instruction — show up here as high pressure %, not just pass/fail.
    """
    wg = occupancy_workgroups_per_cu(cfg, profile=profile,)
    if wg <= 0:
        return "wg/cu=0"
    dims = tile_dims(cfg)
    if not dims:
        return f"wg/cu={wg}"
    mt0, mt1, tt0, tt1 = dims
    ch = str(cfg.get("DataType",) or cfg.get("dtype",) or "").upper()
    r = VGPR_PER_ELEMENT.get(ch,)
    if not r or not tt0 or not tt1:
        return f"wg/cu={wg}"
    acc = measured_accvgpr(tt0, tt1, r)
    threads = (mt0 // tt0) * (mt1 // tt1)
    pct = 100.0 * threads * acc / _loader.resolve_profile(profile,).vgpr_per_cu if threads else 0.0
    return f"wg/cu={wg} acc={acc}vgpr {pct:.0f}% of 64K file"


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
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
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
        from oto.ledger.registry import fingerprint_config
        if fingerprint_config(cfg) != stored:
            problems.append(("fp_stale",
                             f"fp {stored[:12]} is not the hash of the config "
                             f"({fingerprint_config(cfg)[:12]})"))
    return problems


def load_deck(path: Path) -> list:
    """The phase list from a deck (a YAML list) or a seed overlay.

    An overlay is keyed by run metadata with the phases under ``phases``; a
    deck is the bare list. Accepting both is what lets the preflight validate
    the *launch set* (``phases.yaml`` plus the overlay) instead of only the
    committed deck.
    """
    loaded = yamlio.load_yaml(path)
    return loaded.get("phases", []) if isinstance(loaded, dict) else loaded


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=Path, default=BASE / "phases.yaml")
    ap.add_argument("--base-dir", "--base", type=Path, default=BASE)
    ap.add_argument("--family", help="only check this family label")
    ap.add_argument("--floor", action="store_true",
                    help="sweep the shipped gfx900 floor deck (gfx900_shipped_manifest.json "
                         "kernel names rebuilt into configs) instead of --deck")
    ap.add_argument("--quiet", action="store_true", help="print only failures")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    gen = CandidateGenerator(args.base_dir.resolve())

    if args.floor:
        deck, source = _floor_deck(args.base_dir)
        if args.family:
            deck = [d for d in deck if d.get("family", "").upper() == args.family.upper()]
    else:
        source = args.deck
        deck = load_deck(args.deck)

    checked = skipped = 0
    fails: list[tuple[str, list]] = []
    fam_total: Counter = Counter()
    for phase in deck:
        cfg = phase.get("config") or {}
        fam = _fams(cfg) or str(phase.get("family", "")).upper()
        if args.family and fam != args.family.upper():
            skipped += 1
            continue
        checked += 1
        fam_total[fam or "?"] += 1
        bad = check_config(gen, cfg)
        if "phase_id" in phase:
            bad = list(bad) + self_inconsistencies(phase)
        if bad:
            fails.append((phase.get("phase_id") or phase.get("kernel", "?"), bad))
        elif not args.quiet:
            print(f"  ok   {str(phase.get('phase_id') or phase.get('kernel', '?'))[:60]:60} "
                  f"{_occupancy_margin(cfg)}")

    print(f"\n{source}: {checked} checked, {skipped} skipped, {len(fails)} illegal")
    if fam_total:
        print("  per family: " + ", ".join(f"{k}={v}" for k, v in sorted(fam_total.items())))
    for _pid, bad in fails:
        for _name, _why in bad:
            print(f"  FAIL {str(_pid)[:60]:60} [{_name}] {_why}")

    if args.json:
        args.json.write_text(json.dumps(
            {"deck": str(source), "checked": checked, "illegal": len(fails),
             "failures": {str(p): dict(b) for p, b in fails}}, indent=1, default=str))
        print(f"wrote {args.json}")
    return 1 if fails else 0


def _floor_deck(base_dir: Path, profile=None) -> tuple[list[dict], Path]:
    """Rebuild phase-shaped configs for every shipped gfx900 floor kernel.

    The floor's winning configs must be natively gate-legal — both arms emit
    `TensileLibrary_<codename>.co.raw`, and a floor kernel that violates the Model's
    gates would be a proof the Model over-rejects, not an excuse to skip the
    gate. Sweeping the pinned manifest through the same GATES makes that
    explicit instead of assumed.
    """
    manifest_path = _results_dir(base_dir, _loader.resolve_profile(profile,).codename) / "gfx900_shipped_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    deck: list[dict] = []
    for entry in manifest.get("dat_files", [],):
        family = str(entry.get("family", "",)).upper()
        for name in entry.get("kernels", [],):
            try:
                cfg = shipped_kernel_config(name, family, profile=profile,)
            except Exception as exc:  # pragma: no cover — defensive
                deck.append({"phase_id": f"floor-{name[:40]}", "kernel": name,
                             "family": family, "config": {}, "parse_error": str(exc)})
                continue
            cfg["FamilyLabel"] = family
            deck.append({"phase_id": f"floor-{family}-{name}", "kernel": name,
                         "family": family, "config": cfg})
    return deck, manifest_path


if __name__ == "__main__":
    raise SystemExit(main())
