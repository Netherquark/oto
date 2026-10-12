#!/usr/bin/env python3
"""The candidate loaders and the new module's helpers.

Owns: ``iter_candidates`` (the whole pool generator: wide rows, narrow neighbours, auto rows, probes -- each CPU-gated and fp-novel), the narrow/deck row generators, and the deck/seed fingerprint loaders that make novelty decidable.
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
                                        PLAN_BATCH, PROBE_CELLS, TARGET_CELLS,
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

    # fp -> row, one per config. Two sinks so off-grid (graded False) rows are
    # keyed separately and never lose their off-grid shapes to an in-grid row.
    pool: Dict[str, Dict[str, Any]] = {}
    probe_pool: Dict[str, Dict[str, Any]] = {}

    def _offer(
        fam: str,
        tier: str,
        pattern: str,
        knobs: Dict[str, Any],
        sides: Tuple[int, ...],
        graded: bool,
        note: str = "",
        sink: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        sink = sink if sink is not None else pool
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
        # Group C gate: pads/swizzle/AF0EM must also survive ldspad_feasible,
        # or the row would be refused at the launch boundary after consuming a
        # generation slot. Same CPU-only gate the writer applies.
        pad_ok, _pad_why = ldspad_feasible(config)
        if not pad_ok:
            return None
        fp = _fingerprint(config)
        existing = sink.get(fp)
        if existing is None:
            if fp in seen_fp:
                # Already scheduled by the deck or seed this run. The deck row
                # carries its own shapes, so re-offering adds nothing.
                return None
            side0 = sides[0]
            fam_key = fam.lower()
            mt = knobs["MacroTile"]
            tt = knobs["ThreadTile"]
            vw = knobs.get("VectorWidth", 1)
            du = knobs.get("DepthU", 16)
            gsu = knobs.get("GlobalSplitU", 1)
            wgm = knobs.get("WorkGroupMapping", 4)
            prefix = "probe_C" if not graded else "phase_cand"
            phase_id = (f"{prefix}_{fam_key}_{side0}_{_tile_key(mt, tt)}"
                        f"_{pattern}_vw{vw}_du{du}_g{gsu}_w{wgm}")
            # Two configs can share every id-encoded knob (e.g. the 2026-10-09
            # pad / PGR / NLCA variants of the same tile), so pin uniqueness to
            # the fingerprint tail. The prefix stays knob-decodeable.
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
                "graded": graded,
                "tier": tier,
            }
            if note:
                row["note"] = note
            sink[fp] = row
        else:
            existing["shapes"] = sorted(
                set(existing["shapes"]) | {f"{s}x{s}x{s}" for s in sides})
            if note and not existing.get("note"):
                existing["note"] = note
        return sink[fp] if existing is None else None

    # --- wide tier: ladder tiles x patterns x DU/GSU, one row per config ---
    # A config is shape-agnostic, so it spans every in-grid target cell of its
    # family (matching deck semantics: one phase, many exact sizes).
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
                        row = _offer(fam, "wide", pat, knobs, sides, graded=True)
                        if row:
                            yield row
        # narrow-tier neighbours attach their cell to whatever config wins it
        yield from _narrow_row_gen(sched, fam, sides, seen_fp, pool, _offer)

    # --- auto tier: explicit evidence-derived rows ---------------------------
    for fam, specs in AUTO_EXPLICIT.items():
        for spec_ in specs:
            side = int(spec_["shapes"][0].split("x")[0])
            knobs = {k: v for k, v in spec_.items()
                     if k not in ("shapes", "pattern", "note")}
            row = _offer(fam, "auto", spec_["pattern"], knobs, (side,),
                         graded=True, note=spec_.get("note", ""))
            if row:
                yield row

    # --- auto tier: 2026-10-09 beat-the-spoof batch (PLAN_BATCH) ----------
    # Configs span the family's full TARGET_CELLS like the wide tier; every row
    # carries a knob (pads / PGR / PLR / GLVW / NLCA / WGM8) no other tier
    # emits, so fp-dedupe never collapses them into a wide row.
    for spec_ in PLAN_BATCH:
        fam = spec_["fam"]
        knobs = {k: v for k, v in spec_.items()
                 if k not in ("fam", "pattern", "note")}
        row = _offer(fam, "auto", spec_["pattern"], knobs,
                     tuple(TARGET_CELLS[fam]), graded=True,
                     note=spec_.get("note", ""))
        if row:
            yield row

    # --- probe tier: off-grid cells (graded False, kept in a separate pool) ---
    # DepthU is forced to 4 and the DD 64x64x4 / 64x128x4 tiles are excluded so
    # probe configs are structurally disjoint from the in-grid pool: the wide
    # tier only ever emits DepthU 8/16, and the two DD tiles the ladder fixes at
    # DepthU 4 are the only du-4 in-grid rows.
    for fam in PROBE_CELLS:
        ladder = LADDER.get(fam, [])
        if fam == "DD":
            ladder = [t for t in ladder
                      if t.get("MacroTile") not in ("64x64x4", "64x128x4")]
        pat = PATTERNS.get(fam, ("Ailk_Bjlk",))[0]
        sides = tuple(PROBE_CELLS[fam])
        for tile in ladder:
            knobs = {
                "MacroTile": tile["MacroTile"],
                "ThreadTile": tile["ThreadTile"],
                "VectorWidth": tile["VectorWidth"],
                "DepthU": 4,
                "GlobalSplitU": 1,
                "WorkGroupMapping": 4,
            }
            row = _offer(
                fam, "probe", pat, knobs, sides, graded=False,
                note=("off-grid probe: "
                      + f"{'/'.join(str(s) for s in sides)} not in FAMILY_SHAPES; "
                      "measurable, never shipped"),
                sink=probe_pool)
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
                            knobs, (side,), graded=True)
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
