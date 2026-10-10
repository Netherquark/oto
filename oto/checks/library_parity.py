#!/usr/bin/env python3
"""CPU-only enforcement of the TensileLibrary coverage-parity rule.

The rule (stated once, `knowledge_base.md` §6.1): the `tensilelibrary.dat`
this pipeline produces must address **exactly** the same (family, shape)
cells the shipped gfx900 TensileLibrary addresses — the canonical contract
grid `gfx90c_common.shipped_cells()` (38 cells over the 7 families). No
contraction, no extension.

This tool grades a manifest (phases.yaml + any overlays) against that grid:

    python3 check_library_parity.py                     # deck + seed overlay
    python3 check_library_parity.py --run-id <run>      # + that run's overlay
    python3 check_library_parity.py --phases deck.yaml --no-seed
    python3 check_library_parity.py --json parity.json

Exit code 0 = parity holds (deck == shipped grid, no missing/extra cells).
Exit code 1 = divergence: prints the missing (contraction) and extra
(extension) cells. The other enforcement points are `port_tensile --preflight`
(non-fatal check) and `consolidate.py all --commit` (refuses to install a
deck that breaks parity). Pipeline insertions must never ship a cell the
shipped library does not address — candidate probes stay inside the grid.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from oto.device.peaks import shipped_cells
from oto.tensile.library_parity import load_pipeline_phases, parity_report, phases_cells

DEFAULT_BASE = Path(__file__).resolve().parents[2]


def _load_manifests(args) -> list:
    if args.phases:
        return yaml.safe_load(Path(args.phases).read_text()) or []

    merged = load_pipeline_phases(args.base_dir, run_id=args.run_id,
                                  include_seed=not args.no_seed)

    for extra in args.overlay or ():
        doc = yaml.safe_load(Path(extra).read_text())
        entries = doc.get("phases") if isinstance(doc, dict) else None
        if isinstance(entries, dict):
            entries = list(entries.values())
        seen = {p.get("phase_id") for p in merged}
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("phase_id") not in seen:
                merged.append(entry)
                seen.add(entry.get("phase_id"))
    return merged


def _fmt_cells(cells) -> str:
    grid = shipped_cells()
    from oto.device.peaks import FAMILY_DTYPE_CHAR
    parts = []
    for family, shape in cells:
        info = grid.get(f"{family}:{shape.split('x')[0]}")
        dtype = (info or {}).get("dtype") or FAMILY_DTYPE_CHAR.get(family, "?")
        parts.append(f"{family}:{shape.split('x')[0]} (dtype {dtype} {shape})")
    return "\n".join(f"    {p}" for p in parts)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--phases", type=Path, default=None,
                    help="explicit phase file; implies no overlays are merged")
    ap.add_argument("--overlay", type=Path, nargs="*", default=None,
                    help="extra overlay yaml(s) to fold in")
    ap.add_argument("--run-id", default=None,
                    help="also fold in gfx90c_results/overlays/phases.<run-id>.overlay.yaml")
    ap.add_argument("--no-seed", action="store_true",
                    help="skip the seed overlay when reading the default manifest")
    ap.add_argument("--json", type=Path, default=None, help="write report JSON")
    ap.add_argument("--quiet", action="store_true", help="summary line only")
    args = ap.parse_args()

    if args.phases and (args.run_id or args.no_seed):
        ap.error("--phases implies no overlay merging; drop --run-id/--no-seed")

    phases = _load_manifests(args)
    report = parity_report(phases)
    report["manifest_phases"] = len(phases)
    report["covered"] = sorted(phases_cells(phases))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2))

    if args.quiet:
        status = "OK" if report["parity_ok"] else "DIVERGENT"
        print(f"coverage-parity: {status} "
              f"{report['deck_cells']}/{report['shipped_cells']} shipped cells "
              f"({len(report['missing'])} missing, {len(report['extra'])} extra)")
    else:
        print("Coverage-parity check vs shipped gfx900 TensileLibrary")
        print(f"  manifest phases : {len(phases)}")
        print(f"  shipped cells   : {report['shipped_cells']}")
        print(f"  deck cells      : {report['deck_cells']}")
        print(f"  missing (contraction): {len(report['missing'])}")
        if report["missing"]:
            print(_fmt_cells(report["missing"]))
        print(f"  extra  (extension):  {len(report['extra'])}")
        if report["extra"]:
            print(_fmt_cells(report["extra"]))
        if report["non_cube_shapes"]:
            print(f"  non-cell shapes (GEMV probes, excluded from parity): "
                  f"{len(report['non_cube_shapes'])}")
            if not args.quiet:
                for s in report["non_cube_shapes"][:8]:
                    print(f"    {s}")
        if report["unresolved_families"]:
            print(f"  unresolved families: {report['unresolved_families']}")
        print()
        print("PASS: deck maps exactly to the shipped cell grid"
              if report["parity_ok"]
              else "FAIL: deck diverges from the shipped cell grid — "
                   "fix missing (add coverage) and/or extra (revert extension) cells")

    return 0 if report["parity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())