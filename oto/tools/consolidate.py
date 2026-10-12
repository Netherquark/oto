#!/usr/bin/env python3
"""Deck consolidation: the CLI that dispatches to the four phases.

Owns: ``main`` and the ``mine`` / ``all`` subcommand wiring. Every subcommand is
read-only except ``--commit``: ``--dry-run`` stages into
``archive/consolidate_<stamp>/`` and reports, ``--commit`` additionally installs.
Does NOT own: which cells the deck must address (consolidate_targets), the
inventory and selection (consolidate_deck), the locked floor
(consolidate_floor) or the install (consolidate_install).
Public API: main, plus the four phase modules' names it re-exports so a caller
imports them from here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from oto.metrics.ab_audit import BASE  # noqa: E402
from oto.tensile.library_parity import parity_report  # noqa: E402
from oto.tools.consolidate_deck import (  # noqa: E402
    _TENSILE_ROOT, _is_legal, dtype_bytes, load_deck, select_deck)
from oto.tools.consolidate_floor import (  # noqa: E402
    build_db, build_floor, locked_run_id)
from oto.tools.consolidate_install import (  # noqa: E402
    explain_archive, install, write_deck)
from oto.tools.consolidate_targets import (  # noqa: E402
    _fam, _stamp, source_chain, target_cells)

__all__ = [
    "main", "_stamp", "select_deck", "load_deck", "_fam", "_is_legal",
    "dtype_bytes", "_TENSILE_ROOT", "target_cells",
    "build_floor", "locked_run_id", "build_db", "install", "write_deck",
    "explain_archive", "source_chain", "parity_report",
]



# --------------------------------------------------------------------------
def cmd_mine(args) -> int:
    sel = select_deck(args.base_dir)
    rows = sorted(sel["picks"].values(),
                  key=lambda c: (c["family"], int(c["shape"].split("x")[0])))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(sel, indent=2, default=str))
    print(f"cells={len(rows)}  phases selected={len(sel['phases'])}  "
          f"uncovered={len(sel['uncovered'])}  "
          f"sweeps never measured={len(sel['no_measurement'])}\n")
    print(f"{'cell':<14} {'best (measured)':<52} {'gflops':>8}  "
          f"{'sweep (protocol-matched)':<52} {'gflops':>8}")
    print("-" * 132)
    for c in rows:
        b, sw = c.get("best") or {}, c.get("sweep") or {}
        bg = f"{b['gflops']:.1f}" if b.get("gflops") else "-"
        sg = f"{sw['gflops']:.1f}" if sw.get("gflops") else "-"
        btag = "" if b.get("measured") else " (unmeasured)"
        print(f"{c['cell_key']:<14} {str(b.get('phase_id'))[:51]:<52} {bg:>8}{btag:<12} "
              f"{str(sw.get('phase_id'))[:51]:<52} {sg:>8}")
    if sel["illegal_dropped"]:
        print(f"\nillegal phases dropped: {len(sel['illegal_dropped'])}")
        for pid, why in list(sel["illegal_dropped"].items())[:5]:
            print(f"  {pid[:60]}: {why[:90]}")
    return 0


def cmd_all(args) -> int:
    base = args.base_dir
    stamp = _stamp()
    stage = base / "archive" / f"consolidate_{stamp}"
    stage.mkdir(parents=True, exist_ok=True)

    sel = select_deck(base)
    lock = build_floor(base, stage / "gfx90c_runs" / locked_run_id(
        source_chain(base)), stamp)
    dbres = build_db(base, lock, stage / "registry.db", stamp)

    staged_deck = write_deck(stage, sel, stamp)
    print(f"staged -> {stage}")
    print(f"  deck file: {staged_deck}")
    print(f"  deck      : {len(sel['phases'])} phases from "
          f"{len(load_deck(base))} existing")
    print(f"  uncovered : {sel['uncovered'] or 'none'}")
    print(f"  sweeps never measured: {len(sel['no_measurement'])} cells")
    print(f"  illegal dropped: {len(sel['illegal_dropped'])}")
    print(f"  floor     : {lock['run_id']}  phases={lock['phases']} "
          f"csvs={lock['csvs_copied']}  chain={lock['chain']}")
    print(f"  registry  : rows {dbres['before']} -> {dbres['after']}  "
          f"integrity={dbres['integrity']}")

    # Coverage-parity rule (knowledge_base.md §6.1): the consolidated deck
    # (which becomes the produced TensileLibrary) must address exactly the
    # shipped gfx900 cell grid. Refuse to install a deck that diverges.
    pr = parity_report(sel["phases"])
    parity_ok = pr["parity_ok"]
    print(f"  library parity: {'OK' if parity_ok else 'FAIL'} "
          f"{pr['deck_cells']}/{pr['shipped_cells']} shipped cells "
          f"({len(pr['missing'])} missing, {len(pr['extra'])} extra)")

    print("\n" + explain_archive(base))
    if not args.commit:
        print("dry run; nothing installed. re-run with --commit")
        return 0 if parity_ok else 1
    if not parity_ok:
        print("REFUSED to install: consolidated deck breaks TensileLibrary "
              "coverage parity vs the shipped gfx900 grid "
              "(knowledge_base.md §6.1). Fix the deck, then re-run --commit.")
        return 1
    install(base, stage, sel, lock, dbres, stamp)
    print(f"installed. live floor = {lock['run_id']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.set_defaults(commit=False)
    ap.add_argument("--base-dir", type=Path, default=BASE)
    sub = ap.add_subparsers(dest="cmd")
    m = sub.add_parser("mine", help="read-only: best existing phase per cell")
    m.add_argument("--json", type=Path)
    m.set_defaults(func=cmd_mine)
    a = sub.add_parser("all", help="build locked floor + consolidated registry + deck")
    a.add_argument("--dry-run", dest="commit", action="store_false",
                   help="explicitly stage without installing (the default)")
    a.add_argument("--commit", action="store_true",
                   help="install; without it the build is staged only")
    a.add_argument("--explain-archive", action="store_true")
    a.set_defaults(func=cmd_all)
    args = ap.parse_args()
    if getattr(args, "explain_archive", False):
        print(explain_archive(args.base_dir))
        return 0
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
