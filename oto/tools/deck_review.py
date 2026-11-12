#!/usr/bin/env python3
"""The three questions to settle before decking a candidate or trusting a score.

Owns: read-only decision support for candidate generation:

* ``score``    — is the floor actually beaten? The A/B verdict recomputed under
                 EVERY basis the repo can express, because the headline number
                 grades on `winner` (best per-kernel median), which is an order
                 statistic: the arm that draws more kernels has the higher
                 expected max. A cell can read WIN while its *typical* kernel
                 loses.
* ``legality`` — is a forward-knob domain deck-safe? Every
                 (family, knob, value) draw classified against the launch gates
                 on the tiles that actually ran, as legal / coupled / refused
                 standalone, so a domain is never decked blind and a coupling is
                 never mistaken for a dead value.
* ``flood``    — where is the GPU budget going? The per-cell distinct-config
                 census and what a top-K cap would retain, and whether that cap
                 loses any cell winner.

Does NOT own: the winners themselves (`oto.harness.resolve_cells`), the
acceptance verdicts (`oto.metrics.ab_audit`), the knob domains
(`oto.tensile.synthesis.db_knobs`), or the gates
(`oto.tensile.gates`). It re-implements no aggregation: it drives the repo's own
loaders, so it cannot disagree with the pipeline that produced the ledger.

CPU only. Read-only. Touches no GPU, launches no Tensile run, writes nothing.

    python3 -m oto.tools.deck_review score            # per-basis scoreboard
    python3 -m oto.tools.deck_review legality         # knob-domain draw census
    python3 -m oto.tools.deck_review flood            # per-cell config census
    python3 -m oto.tools.deck_review flood --cap 24   # ... and what K=24 costs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from oto.device.peaks import FAMILY_DTYPE_CHAR  # noqa: E402
from oto.tensile.gates.occupancy import ldspad_feasible  # noqa: E402
from oto.tensile.synthesis.db_knobs import (  # noqa: E402
    FORWARD_KNOB_DOMAINS, forward_domain)

#: The A/B bases, lenient to strict, with what each one actually asks. The
#: names and their meaning live in `oto.metrics.ab_delta._stat`; this is the
#: menu, not a second definition.
BASES: Tuple[Tuple[str, str], ...] = (
    ("winner", "native best-kernel vs spoof best-kernel (the report's basis)"),
    ("median", "typical native vs typical spoof"),
    ("floor_best", "typical native vs spoof's BEST kernel"),
    ("strict", "native's WORST kernel vs spoof's best"),
    ("best", "max single raw sample (seed-noisy; reference only)"),
)


# ---------------------------------------------------------------- score

def _score(base: Path) -> int:
    """The A/B scoreboard under every basis, plus the losers per basis."""
    from oto.metrics import ab_delta
    from oto.metrics.ab_audit import arm_record_sets

    native, floor, _chain = arm_record_sets(base)
    if not native or not floor:
        print("no native/spoof records found -- run a benchmark first")
        return 1

    print(f"native records={len(native)}  spoof records={len(floor)}")
    print(f"{'basis':11}{'cells':>6}{'WIN':>6}{'TIE':>6}{'LOSS':>6}   meaning")
    deltas: Dict[str, Dict[Tuple[str, int], Dict[str, Any]]] = {}
    for basis, meaning in BASES:
        d = ab_delta._pair_cells(native, floor, basis, 2.0, None, None)
        deltas[basis] = d
        c = Counter(v["verdict"] for v in d.values())
        print(f"{basis:11}{len(d):6}{c['WIN']:6}{c['TIE']:6}{c['LOSS']:6}   {meaning}")

    # The losses are the work list, and they only exist on the strict bases.
    worst = deltas["floor_best"]
    losers = sorted(((v["delta_pct"], k)
                     for k, v in worst.items() if v["verdict"] == "LOSS"),
                    key=lambda r: r[0])
    if losers:
        print(f"\nLOSSES on floor_best ({len(losers)}) -- typical native vs spoof's best:")
        for pct, key in losers[:12]:
            v = worst[key]
            fam = key[2].split("_")[1]
            side = key[1].split("x")[0]
            print(f"  {fam + ':' + side:10}{pct:8.1f}%  "
                  f"nat_typ={v['native_median']:8.1f}  "
                  f"spoof_best={v['spoof_best_median']:8.1f}")

    ties = deltas["winner"]
    tied = sorted((v["delta_pct"], k) for k, v in ties.items()
                  if v["verdict"] == "TIE")
    if tied:
        print(f"\nTIEs on winner ({len(tied)}) -- investigate whether they are walls:")
        for pct, key in tied:
            fam = key[2].split("_")[1]
            side = key[1].split("x")[0]
            print(f"  {fam + ':' + side:10}{pct:8.1f}%")
    return 0


# ------------------------------------------------------------- legality

#: How many distinct measured tiles per family to test a draw against. Three is
#: enough to cover the shape of the space (a wide tile, a narrow one, a
#: high-VW one) without turning the census into a sweep.
TILES_PER_FAMILY = 3


def _as_tile_str(value: Any) -> Optional[str]:
    """`"[128, 128]"` (kernel_db) -> `"128x128"` (what the gates parse)."""
    if value is None:
        return None
    parts = [p for p in re.split(r"[\s,\[\]]+", str(value).strip()) if p]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return "x".join(parts)


def _as_tile_list(value: Any) -> Optional[List[int]]:
    """`"[8, 8]"` (kernel_db) -> `[8, 8]` (what `reconcile_tile` parses)."""
    parts = [p for p in re.split(r"[\s,\[\]]+", str(value or "").strip()) if p]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return [int(p) for p in parts]


def _measured_tiles(base: Path, per_family: int) -> Dict[str, List[Dict[str, Any]]]:
    """The distinct MacroTile/ThreadTile/VectorWidth/DepthU combos per family.

    Read from `kernel_db.json` — i.e. the tiles that *actually ran*, not an
    invented grid. This matters: most knob legality is tile-conditional
    (`GLVW` must equal `VectorWidth` or 1), so a census against one invented
    reference tile reports coupling as a dead value and vice versa.

    A tile is **informative** only when the gates already accept it *before* any
    knob is applied. An uninformative tile is skipped, because otherwise the
    verdict reports the tile's own budget overflow as the knob's fault — which
    is how a default value like `StaggerU=0` ends up looking broken on an
    LDS-full `256x256` tile.
    """
    db_path = base / "gfx90c_results" / "analysis" / "kernel_db.json"
    if not db_path.is_file():
        return {}
    try:
        db = json.loads(db_path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(db, dict):
        return {}

    seen: Dict[str, Dict[Tuple[str, ...], Dict[str, Any]]] = {}
    for rows in db.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            fam = str(row.get("family") or "")
            macro = _as_tile_str(row.get("MacroTile"))
            if not fam or not macro:
                continue
            thread = _as_tile_list(row.get("ThreadTile"))
            vw, du = row.get("VectorWidth"), row.get("DepthU")
            key = (macro, str(thread), str(vw), str(du))
            seen.setdefault(fam, {})[key] = {
                "MacroTile": macro,
                "ThreadTile": thread,
                "VectorWidth": int(vw) if str(vw).isdigit() else None,
                "DepthU": int(du) if str(du).isdigit() else None,
            }
    # kernel_db carries no per-tile observation count, so rank on a stable,
    # documented order instead: widest tile first, then deepest, then widest VW.
    def _rank(item: Tuple[Tuple[str, ...], Dict[str, Any]]) -> Tuple[int, int, int]:
        _, t = item
        digits = "".join(ch for ch in str(t["MacroTile"]) if ch.isdigit())
        return (-(int(digits) if digits else 0), -(int(t["DepthU"] or 0)),
                -(int(t["VectorWidth"] or 0)))
    return {fam: [t for _k, t in sorted(tiles.items(), key=_rank)[:per_family]]
            for fam, tiles in seen.items()}


def _family_template(fam: str) -> Dict[str, Any]:
    """The minimal contract template a draw is applied on top of."""
    from oto.tensile.synthesis.db_knobs import _DEFAULT_PATTERN
    return {
        "Architecture": "gfx90c",
        "DataType": FAMILY_DTYPE_CHAR.get(fam, "S"),
        "FamilyLabel": fam,
        "ScheduleName": "isa",
        "ProblemType": "Contraction",
        "ContractionPattern": _DEFAULT_PATTERN.get(fam, "Ailk_Bjlk"),
    }


def _classify_draw(template: Dict[str, Any], tiles: List[Dict[str, Any]],
                   knob: str, value: Any,
                   gate: Callable[[Dict[str, Any]], Tuple[bool, str]],
                   reconcile: Callable[[Dict[str, Any]], Dict[str, Any]],
                   ) -> Tuple[bool, int, str]:
    """`(legal, refusals, first_reason)` for one draw across `tiles`.

    A draw is **legal** when no informative tile refuses it, **coupled** when
    only some do — ordinary tile dependence (`GLVW` must equal `VectorWidth` or
    1; `NLCA` must divide the load count) and not a defect.

    "Refused on every tile" is **not** "dead". Some of those are couplings that
    resolve when a companion knob is drawn alongside: `StaggerU=0` is refused
    because `StaggerUStride` defaults to 256, and is legal the moment
    `StaggerUStride=0` is drawn too. The reason text names the companion, so
    read it — and treat `python3 check_candidates.py` on the real deck, which
    sees every knob at once, as the authority. A value that is genuinely dead
    for this device is one whose reason is a structural class rule ("illegal on
    the device", "no MatrixInstruction").
    """
    refusals: List[str] = []
    for tile in tiles:
        ok, why = gate({**reconcile({**template, **tile}), knob: value})
        if not ok:
            refusals.append(str(why))
    return (not refusals, len(refusals), refusals[0] if refusals else "")


def _report_legality(n_fams: int, legal: int, coupled: Counter,
                     refused: List[Tuple[str, str, Any, str]],
                     skipped: Counter) -> None:
    """Print the census. Split out so `_legality` stays inside the line budget."""
    total = legal + sum(coupled.values()) + len(refused)
    print(f"{n_fams} families x up to {TILES_PER_FAMILY} measured tiles; "
          f"{total} (family, knob, value) draws through "
          f"validate_config + ldspad_feasible")
    print(f"  legal on >=1 tile: {legal}   coupled: {sum(coupled.values())}"
          f"   refused standalone: {len(refused)}")
    if skipped:
        print(f"  no legal measured tile for {', '.join(sorted(skipped))} — "
              f"those rows are template-only verdicts")
    if coupled:
        print("\ncoupled (tile-dependent; ordinary, not a defect):")
        for where, n in coupled.most_common():
            print(f"  {where:52}{n:4}")
    if not refused:
        return
    print("\nrefused standalone — read the reason: it names the knob or rule "
          "responsible,\nand most of these resolve when a companion knob is "
          "drawn with them.\nA value that is genuinely dead for this device "
          "is one whose reason is a\nstructural class rule ('illegal on "
          "gfx90c', 'no MatrixInstruction'):")
    for fam, knob, value, why in refused:
        print(f"  {fam:8}{knob:30}{str(value):6} {why}")


def _legality(base: Path, families: Optional[List[str]]) -> int:
    """Classify each forward-knob draw as legal, coupled, or refused-standalone.

    Draws come from ``census_domain`` (global ∪ family override), not the
    mutator's narrowed ``forward_domain``: a value a family's domain drops for
    draw economy is still classified here, so a structural refusal
    (``GlobalSplitU>1`` on CC/ZZ) is named rather than silently absent.

    The two limits of a one-knob-at-a-time census, and why each is deliberate,
    are in `_classify_draw` and `_measured_tiles`.
    """
    from oto.tensile.candidate import CandidateGenerator
    from oto.tensile.synthesis.db_knobs import _DEFAULT_PATTERN, census_domain
    from oto.tensile.synthesis.tile_space import reconcile_tile

    gen = CandidateGenerator(base)

    def gate(cfg: Dict[str, Any]) -> Tuple[bool, str]:
        ok, why = gen.validate_config(cfg)
        if ok:
            ok, why = ldspad_feasible(cfg)
        return bool(ok), str(why)

    tiles = _measured_tiles(base, TILES_PER_FAMILY)
    fams = families or sorted(_DEFAULT_PATTERN)

    refused: List[Tuple[str, str, Any, str]] = []
    coupled: Counter = Counter()
    skipped: Counter = Counter()
    legal = 0
    for fam in fams:
        template = _family_template(fam)
        # A family with no measured tile still gets swept, on the bare template,
        # and is reported so a reader does not mistake it for a measured verdict.
        candidates = tiles.get(fam) or [{}]
        informative = [t for t in candidates
                       if gate(reconcile_tile({**template, **t}))[0]]
        if not informative:
            skipped[fam] = len(candidates)
            informative = candidates
        for knob in FORWARD_KNOB_DOMAINS:
            for value in census_domain(fam, knob):
                ok, n_bad, why = _classify_draw(
                    template, informative, knob, value, gate, reconcile_tile)
                if ok:
                    legal += 1
                elif n_bad < len(informative):
                    coupled[f"{fam}:{knob}"] += 1
                else:
                    refused.append((fam, knob, value, why))

    _report_legality(len(fams), legal, coupled, refused, skipped)
    return 0


# ----------------------------------------------------------------- flood

def _flood(base: Path, cap: Optional[int]) -> int:
    """Per-cell distinct-config census, and what a top-K cap would cost."""
    db_path = base / "gfx90c_results" / "analysis" / "kernel_db.json"
    try:
        db = json.loads(db_path.read_text())
    except Exception as exc:
        print(f"cannot read {db_path}: {exc}")
        return 1
    if not isinstance(db, dict):
        print(f"{db_path} is not a kernel_db map")
        return 1

    # (family, shape) -> fingerprint -> [medians]
    cells: Dict[Tuple[str, str], Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list))
    for _run, rows in db.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            med = row.get("gflops_median")
            if med is None:
                continue
            fp = row.get("fp") or row.get("kernel") or ""
            cells[(str(row.get("family")), str(row.get("shape")))][fp].append(med)

    if not cells:
        print("no cells in kernel_db.json")
        return 1

    print(f"{'cell':12}{'configs':>8}{'records':>8}{'med/best':>9}")
    total_cfg = 0
    for (fam, shape), fps in sorted(cells.items()):
        n_cfg = len(fps)
        n_rec = sum(len(v) for v in fps.values())
        best = max((max(v) for v in fps.values()), default=0.0)
        med = sorted(max(v) for v in fps.values())[len(fps) // 2]
        total_cfg += n_cfg
        print(f"{fam + ':' + shape.split('x')[0]:12}{n_cfg:8}{n_rec:8}"
              f"{(med / best * 100 if best else 0):9.0f}")
    print(f"{'TOTAL':12}{total_cfg:8}")

    if cap is None:
        return 0

    kept = 0
    lost = 0
    for fps in cells.values():
        ranked = sorted(fps.items(), key=lambda kv: -max(kv[1]))[:cap]
        kept += len(ranked)
        winner = max(fps.items(), key=lambda kv: max(kv[1]))[0]
        if winner not in {fp for fp, _ in ranked}:
            lost += 1
    print(f"\ntop-{cap} cap: retains {kept}/{total_cfg} configs "
          f"({100 * kept / total_cfg:.0f}%), LOSES {lost} of {len(cells)} "
          f"cell winners")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="CPU only, read-only. Run from the repo root.")
    ap.add_argument("command", choices=("score", "legality", "flood"),
                    help="which of the three questions to answer")
    ap.add_argument("--base", type=Path, default=BASE,
                    help="project base dir (default: repo root)")
    ap.add_argument("--family", action="append", default=None,
                    help="restrict legality to one family (repeatable)")
    ap.add_argument("--cap", type=int, default=None,
                    help="for flood: evaluate a top-K per-cell cap")
    args = ap.parse_args(argv)

    if args.command == "score":
        return _score(args.base)
    if args.command == "legality":
        return _legality(args.base, args.family)
    return _flood(args.base, args.cap)


if __name__ == "__main__":
    raise SystemExit(main())
