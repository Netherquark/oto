#!/usr/bin/env python3
"""The candidate loaders and the new module's helpers.

Owns: ``iter_candidates`` (the whole pool generator: wide rows, narrow neighbours, auto rows -- each CPU-gated and fp-novel), the narrow/deck row generators, and the deck/seed fingerprint loaders that make novelty decidable.
Does NOT own: the row data itself (oto.harness.candidate_rows) or the overlay read/write (oto.harness.candidate_overlay).
Public API: iter_candidates, _strip_not_forwarded, _narrow_row_gen, _deck_rows_by_family, _deck_winner_for, _pattern_for."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = REPO_ROOT / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"

from oto.device.peaks import (FAMILY_DTYPES, FAMILY_DTYPE_CHAR,  # noqa: E402
                              FAMILY_SHAPES)
from oto.ledger.registry import fingerprint_config  # noqa: E402
from oto.tensile.candidate import CandidateGenerator  # noqa: E402
from oto.tensile.gates.occupancy import ldspad_feasible  # noqa: E402
from oto.harness.candidate_rows import (_NOT_FORWARDED_YET,  # noqa: E402
                                        AUTO_EXPLICIT, DU_VARIANTS,
                                        FAMILY_DTYPE, LADDER,
                                        NARROW_NEIGHBOURS, PATTERNS,
                                        PLAN_BATCH, TARGET_CELLS,
                                        WGM_VARIANTS, _pad_rows)


def _tile_key(mt: str, tt: str) -> str:
    return f"{mt.lower()}_tt{tt.lower()}"


def _label_for(fam: str, pattern: str, knobs: Dict[str, Any]) -> str:
    return (f"{fam}_{pattern}_mt{knobs['MacroTile']}_tt{knobs['ThreadTile']}"
            f"_vw{knobs.get('VectorWidth', 1)}_wgm{knobs.get('WorkGroupMapping', 4)}"
            f"_du{knobs.get('DepthU', 16)}_alu")


def _base_config(fam: str) -> Dict[str, Any]:
    return {
        "Architecture": "gfx90c",
        "DataType": FAMILY_DTYPE[fam],
        "FamilyLabel": fam,
        "ScheduleName": "isa",
        "ProblemType": "Contraction",
    }


def _fingerprint(config: Dict[str, Any]) -> str:
    return fingerprint_config(config)


def _load_deck_fps() -> Set[str]:
    fps: Set[str] = set()
    p = REPO_ROOT / "phases.yaml"
    if p.exists():
        for row in __yaml_load(p, fallback=[]):
            if isinstance(row, dict) and row.get("fp"):
                fps.add(row["fp"])
    return fps


def __yaml_load(path: Path, fallback: Any = []) -> Any:
    import yaml
    try:
        with open(path) as f:
            return yaml.safe_load(f) or fallback
    except Exception:
        return fallback


def _load_seed_fps() -> Set[str]:
    """fps already scheduled by the *curated* seed rows (never the generator's
    own previous appends: those are exactly what a re-run must skip deduping
    against, or wide rows colliding with the last append silently vanish)."""
    fps: Set[str] = set()
    payload = __yaml_load(OVERLAY_PATH, fallback={})
    for row in (payload.get("phases", []) or []):
        if not isinstance(row, dict) or not row.get("fp"):
            continue
        if str(row.get("origin", "")).startswith("generated_"):
            continue
        fps.add(row["fp"])
    return fps


def _strip_not_forwarded(config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    dropped = [k for k in _NOT_FORWARDED_YET if k in config]
    return {k: v for k, v in config.items() if k not in _NOT_FORWARDED_YET}, dropped


def iter_candidates() -> Iterator[Dict[str, Any]]:
    """Yield validated, fp-deduped candidate rows (open/free of overlay state).

    A candidate *phase* is one config carrying a SHAPE LIST (like the deck
    rows); a fingerprint is config-level and needs exactly one row, or the
    spread of shapes collapses to the first cell that mentions it.
    """
    sched = CandidateGenerator(REPO_ROOT, registry=None)

    seen_fp: Set[str] = set(_load_deck_fps())
    seen_fp.update(_load_seed_fps())

    # fp -> row, one per config (a row's shapes accumulate from every cell it
    # addresses, so a config is benchmarked once).
    pool: Dict[str, Dict[str, Any]] = {}

    def _offer(
        fam: str,
        tier: str,
        pattern: str,
        knobs: Dict[str, Any],
        sides: Tuple[int, ...],
        note: str = "",
    ) -> Optional[Dict[str, Any]]:
        knobs = dict(knobs)
        if "DepthU" not in knobs:
            mt_parts = [int(x) for x in re.split(r"[xX]",
                        str(knobs.get("MacroTile", "64x64x16")))]
            knobs["DepthU"] = mt_parts[2] if len(mt_parts) >= 3 else 16
        config = {**_base_config(fam), **knobs, "ContractionPattern": pattern}
        config, dropped = _strip_not_forwarded(config)
        if dropped:
            note = (note + f" [stripped {','.join(dropped)}: not forwarded]").strip()
        ok, why = sched.validate_config(config)
        if not ok:
            return None
        pad_ok, _pad_why = ldspad_feasible(config)
        if not pad_ok:
            return None
        fp = _fingerprint(config)
        existing = pool.get(fp)
        if existing is None:
            if fp in seen_fp:
                return None
            side0 = sides[0]; fam_key = fam.lower()
            mt = knobs["MacroTile"]; tt = knobs["ThreadTile"]; vw = knobs.get("VectorWidth", 1)
            du = knobs.get("DepthU", 16); gsu = knobs.get("GlobalSplitU", 1); wgm = knobs.get("WorkGroupMapping", 4)
            prefix = "phase_cand"
            phase_id = (f"{prefix}_{fam_key}_{side0}_{_tile_key(mt, tt)}"
                        f"_{pattern}_vw{vw}_du{du}_g{gsu}_w{wgm}")
            phase_id = f"{phase_id}_{fp[:8]}"
            row = {
                "phase_id": phase_id,
                "label": _label_for(fam, pattern, knobs),
                "dtype": FAMILY_DTYPE[fam].lower(),
                "shapes": sorted(f"{s}x{s}x{s}" for s in sides),
                "ScheduleName": "isa",
                "NumBenchmarks": 8,
                "contraction_pattern": pattern,
                "config": config,
                "fp": fp,
                "origin": "generated_" + tier,
                "tier": tier,
            }
            if note:
                row["note"] = note
            pool[fp] = row
        else:
            existing["shapes"] = sorted(
                set(existing["shapes"]) | {f"{s}x{s}x{s}" for s in sides})
            if note and not existing.get("note"):
                existing["note"] = note
        return pool[fp] if existing is None else None

    for fam in TARGET_CELLS:
        ladder = LADDER.get(fam, [])
        pats = PATTERNS.get(fam, ("Ailk_Bjlk",))[:2]
        sides = tuple(TARGET_CELLS[fam])
        for tile in ladder:
            mt = tile["MacroTile"]; tt = tile["ThreadTile"]
            vw = tile["VectorWidth"]
            du_choices = [tile.get("DepthU", 8)] if "DepthU" in tile else list(DU_VARIANTS)
            gsu_choices = (tile.get("GlobalSplitU", 1) if "GlobalSplitU" in tile
                           else (1, 2, 4) if fam == "SS" else (1,))
            for pat in pats:
                for du in du_choices:
                    for gsu in gsu_choices:
                        knobs = {
                            "MacroTile": mt, "ThreadTile": tt,
                            "VectorWidth": vw, "DepthU": du,
                            "GlobalSplitU": gsu, "WorkGroupMapping": 4,
                            **(tile.get("extra") or {}),
                        }
                        row = _offer(fam, "wide", pat, knobs, sides)
                        if row:
                            yield row
        yield from _narrow_row_gen(sched, fam, sides, seen_fp, pool, _offer)

    for fam, specs in AUTO_EXPLICIT.items():
        for spec_ in specs:
            side = int(spec_["shapes"][0].split("x")[0])
            knobs = {k: v for k, v in spec_.items()
                     if k not in ("shapes", "pattern", "note")}
            row = _offer(fam, "auto", spec_["pattern"], knobs, (side,),
                         note=spec_.get("note", ""))
            if row:
                yield row

    for spec_ in PLAN_BATCH:
        fam = spec_["fam"]
        knobs = {k: v for k, v in spec_.items()
                 if k not in ("fam", "pattern", "note")}
        row = _offer(fam, "auto", spec_["pattern"], knobs,
                     tuple(TARGET_CELLS[fam]),
                     note=spec_.get("note", ""))
        if row:
            yield row


def _narrow_row_gen(sched, fam: str, sides: Tuple[int, ...],
                    seen_fp: Set[str], pool: Dict[str, Dict[str, Any]],
                    offer) -> Iterator[Dict[str, Any]]:
    """1-knob neighbours of each cell's deck winner (falls back to the ladder).

    Yields the neighbours as their own rows, except when the neighbour's fp
    already exists in `pool` (a wide row measures it) — then the cell is added
    to that row's shapes instead so the same config is never benchmarked twice.
    """
    deck = _deck_rows_by_family()
    ladder = LADDER.get(fam, [])
    for side in sides:
        winner = _deck_winner_for(deck, fam, side)
        if winner is None:
            if not ladder:
                continue
            winner = {"MacroTile": ladder[0]["MacroTile"],
                      "ThreadTile": ladder[0]["ThreadTile"],
                      "VectorWidth": ladder[0]["VectorWidth"],
                      "WorkGroupMapping": 4, "GlobalSplitU": 1}
        for knob in NARROW_NEIGHBOURS:
            val = winner.get(knob)
            if knob == "GlobalSplitU" and fam in ("CC", "ZZ", "HH", "HH_HPA",
                                                  "HS_HPA"):
                continue  # GSU>1 illegal on complex/HPA; banned on HH (§13.4)
            nbrs = NARROW_NEIGHBOURS[knob].get(val)
            if not nbrs:
                continue
            for nb in nbrs:
                knobs = {**winner, knob: nb}
                fp = _fingerprint({**_base_config(fam), **knobs,
                                   "ContractionPattern":
                                   _pattern_for(fam, knobs.get("MacroTile", ""))})
                if fp in pool:
                    pool[fp]["shapes"] = sorted(
                        set(pool[fp]["shapes"]) | {f"{side}x{side}x{side}"})
                    continue
                if fp in seen_fp:
                    continue
                row = offer(fam, "narrow",
                            _pattern_for(fam, knobs.get("MacroTile", "")),
                            knobs, (side,))
                if row:
                    yield row


def _deck_rows_by_family() -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in __yaml_load(REPO_ROOT / "phases.yaml", fallback=[]):
        if not isinstance(row, dict):
            continue
        cfg = row.get("config") or {}
        fam = str(cfg.get("FamilyLabel") or row.get("label") or "").upper()
        for f in FAMILY_DTYPE_CHAR:
            if fam.startswith(f):
                fam = f
                break
        if fam in FAMILY_DTYPE_CHAR:
            rows.setdefault(fam, []).append({**row, "config": cfg})
    return rows


def _deck_winner_for(deck: Dict[str, List[Dict[str, Any]]], fam: str,
                     side: int) -> Optional[Dict[str, Any]]:
    shape = f"{side}x{side}x{side}"
    for row in deck.get(fam, []):
        if shape in (row.get("shapes") or []):
            cfg = row.get("config") or {}
            return {
                "MacroTile": cfg.get("MacroTile"),
                "ThreadTile": cfg.get("ThreadTile"),
                "VectorWidth": cfg.get("VectorWidth"),
                "WorkGroupMapping": cfg.get("WorkGroupMapping", 4),
                "GlobalSplitU": cfg.get("GlobalSplitU", 1),
            }
    return None


def _pattern_for(fam: str, mt: str) -> str:
    return PATTERNS.get(fam, ("Ailk_Bjlk",))[0]
