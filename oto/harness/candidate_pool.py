#!/usr/bin/env python3
"""The candidate loaders and the new module's helpers.

Owns: ``iter_candidates`` (the whole pool generator: wide rows, narrow neighbours, auto rows -- each CPU-gated and fp-novel), the narrow/deck row generators, and the deck/seed fingerprint loaders that make novelty decidable. The numeric ProblemSizes order every emitted row carries is defined once in ``oto.tensile.shape_order`` (``_shape_list`` / ``_merge_shapes`` are its call sites here).
Does NOT own: the row data itself (oto.harness.candidate_rows) or the overlay read/write (oto.harness.candidate_overlay).
Public API: iter_candidates, _strip_not_forwarded, _narrow_row_gen, _deck_rows_by_family, _deck_winner_for, _pattern_for, _shape_list, _merge_shapes, _assertion_failures, _shapes_satisfying_assertions, DROPPED_ASSERTIONS."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import sys
# `yaml` is imported lazily, inside the functions that use it, so that
# importing this module does not pull in the parser.

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = REPO_ROOT / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"

from oto import yamlio  # noqa: E402
from oto.device.peaks import (FAMILY_DTYPES, FAMILY_DTYPE_CHAR,  # noqa: E402
                              FAMILY_SHAPES)
from oto.ledger.registry import fingerprint_config  # noqa: E402
from oto.tensile.candidate import CandidateGenerator  # noqa: E402
from oto.tensile.gates.occupancy import ldspad_feasible  # noqa: E402
from oto.tensile.shape_order import ordered_shapes  # noqa: E402
from oto.tensile.synthesis.db_knobs import (  # noqa: E402
                                            forward_domain)
from oto.harness.candidate_rows import (_NOT_FORWARDED_YET,  # noqa: E402
                                        AUTO_EXPLICIT, DU_VARIANTS,
                                        FAMILY_DTYPE, LADDER,
                                        NARROW_NEIGHBOURS, PATTERNS,
                                        PLAN_BATCH, TARGET_CELLS,
                                        WGM_VARIANTS, _pad_rows)

#: Notes for rows dropped because no target shape satisfied their element-
#: multiple assertions. Appended to by ``_offer_row``; drained by
#: ``iter_candidates`` so a run can report what was pruned and why instead of
#: losing the information.
DROPPED_ASSERTIONS: List[str] = []


def _tile_key(mt: str, tt: str) -> str:
    return f"{mt.lower()}_tt{tt.lower()}"


def _shape_list(sides: Tuple[int, ...]) -> List[str]:
    """Cube shapes for ``sides`` in canonical ascending order.

    A candidate phase carries its ``TARGET_CELLS`` as one ProblemSizes sweep, and
    Tensile runs that sweep in list order, each size's median absorbing the clock
    state the previous size left (``claude.md`` 2.0.3). The deck, ``FAMILY_SHAPES``
    and ``TARGET_CELLS`` are numerically ascending, so a candidate must match --
    a string sort would emit ``1024, 192, 2048, 256, 512`` and poison 256^3
    (`results.md` 13.4).
    """
    return ordered_shapes(f"{s}x{s}x{s}" for s in sides)


def _merge_shapes(existing: List[str], sides: Tuple[int, ...]) -> List[str]:
    """Union ``existing`` with ``sides``, re-ordered numerically.

    Used wherever a config already in the pool picks up another cell's shape; a
    bare ``sorted`` here would re-break an order the new-row path got right.
    """
    return ordered_shapes(set(existing) | {f"{s}x{s}x{s}" for s in sides})


def _label_for(fam: str, pattern: str, knobs: Dict[str, Any]) -> str:
    return (f"{fam}_{pattern}_mt{knobs['MacroTile']}_tt{knobs['ThreadTile']}"
            f"_vw{knobs.get('VectorWidth', 1)}_wgm{knobs.get('WorkGroupMapping', 4)}"
            f"_du{knobs.get('DepthU', 16)}_alu")


def _base_config(fam: str) -> Dict[str, Any]:
    return {
        "Architecture": "the device",
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
    """Read a YAML file with the canonical reader (libyaml + content cache)."""
    try:
        return yamlio.load_yaml_cached(path) or fallback
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


#: The three element-multiple assertions, and the problem dimension each one
#: asserts. Read from Tensile's own `validParameters` doc comments
#: (`Common.py`), which name the dimensions explicitly:
#:
#: * ``AssertFree0ElementMultiple`` -- "Kernel generator will assume that the
#:   FreeIndex[0] size is some multiple ... FreeIndex[0] is usually letter I"
#:   -> **M**. Legal values ``[1,2,4,8,16]``; recommended 16/I8, 8/half, 4/single,
#:   2/double.
#: * ``AssertFree1ElementMultiple`` -- FreeIndex[1] = "J" -> **N**. Same domain.
#: * ``AssertSummationElementMultiple`` -- "will assume that the summation size is
#:   some multiple" -> **K**, and when ``GlobalSplitU>1`` it is applied as
#:   ``ASEM//GSU``, so it must divide by GSU as well. Legal values ``[1..1024]``
#:   powers of two.
#:
#: All three mean "1 indicates no assertion (since all sizes are multiples of 1)".
#:
#: Why this table lives here and not in ``oto/tensile.gates``: the gate families
#: validate a *config*, and these assertions are the one class of Tensile knob
#: that is about a *shape*. There is no way to check them without both, and the
#: gates never see the shape.
_ELEMENT_ASSERTIONS: Tuple[Tuple[str, int, str], ...] = (
    ("AssertFree0ElementMultiple", 0, "M"),
    ("AssertFree1ElementMultiple", 1, "N"),
    ("AssertSummationElementMultiple", 2, "K"),
)


def _assertion_failures(config: Dict[str, Any], side: int) -> List[str]:
    """Which of the config's element-multiple assertions ``side`` violates.

    ``side`` is a cubic size; dims are M, N, K. An absent or non-numeric
    assertion means 1, i.e. no assertion, which every size satisfies.

    Tensile does **not** enforce these: its own comment says the kernel
    generator "will assume that the ... size is some multiple", and for the
    summation case it says outright that this "requires runtime checking to
    ensure the specified summation value meets the requirements". The only
    divisibility Tensile checks is ``AF0EM % GlobalLoadVectorWidthA == 0``
    (``GuaranteeNoPartialA``, enforced in ``oto.tensile.gates.loads``), which is a
    knob-to-knob rule and says nothing about the problem size. So a wrong value
    does not fail loudly -- the kernel drops the M/N predication it needed and
    returns **silently wrong numbers**. That is the whole reason this exists.
    """
    out: List[str] = []
    gsu = int(config.get("GlobalSplitU", 1) or 1)
    for knob, index, label in _ELEMENT_ASSERTIONS:
        raw = config.get(knob, 1)
        try:
            mult = int(raw)
        except (TypeError, ValueError):
            mult = 1
        if mult <= 1:
            continue
        if side % mult:
            out.append(f"{label}={side} not a multiple of {knob}={mult}")
        elif knob == "AssertSummationElementMultiple" and gsu > 1 and mult % gsu:
            out.append(f"{knob}={mult} is not a multiple of GlobalSplitU={gsu}, "
                       f"so ASEM//GSU is not the asserted multiple")
    return out


def _shapes_satisfying_assertions(
        config: Dict[str, Any], sides: Tuple[int, ...]) -> Tuple[Tuple[int, ...], List[str]]:
    """`sides` filtered to the sizes every element-multiple assertion accepts.

    Filtering rather than dropping is deliberate: a row offered across a family
    that spans both 4-divisible and non-divisible sizes is still a good candidate
    for the divisible ones, and a fingerprint is benchmarked once, so silently
    dropping the row would throw away a legitimate measurement.
    """
    kept: List[int] = []
    reasons: List[str] = []
    for side in sides:
        bad = _assertion_failures(config, int(side))
        if bad:
            reasons.append(f"{side}: " + "; ".join(bad))
        else:
            kept.append(int(side))
    return tuple(kept), reasons


def _candidate_phase_id(
    fam: str,
    pattern: str,
    knobs: Dict[str, Any],
    sides: Tuple[int, ...],
    fp: str,
) -> str:
    """The deterministic phase_id for a candidate config."""
    mt = knobs["MacroTile"]
    tt = knobs["ThreadTile"]
    vw = knobs.get("VectorWidth", 1)
    du = knobs.get("DepthU", 16)
    gsu = knobs.get("GlobalSplitU", 1)
    wgm = knobs.get("WorkGroupMapping", 4)
    phase_id = (f"phase_cand_{fam.lower()}_{sides[0]}_{_tile_key(mt, tt)}"
                f"_{pattern}_vw{vw}_du{du}_g{gsu}_w{wgm}")
    return f"{phase_id}_{fp[:8]}"


def _with_depth_u(knobs: Dict[str, Any]) -> Dict[str, Any]:
    """`knobs` with an explicit `DepthU`, taken from the MacroTile string."""
    out = dict(knobs)
    if "DepthU" not in out:
        parts = [int(x) for x in re.split(r"[xX]", str(out.get("MacroTile",
                                                                 "64x64x16")))]
        out["DepthU"] = parts[2] if len(parts) >= 3 else 16
    return out


def _build_row(fam: str, tier: str, pattern: str, knobs: Dict[str, Any],
               sides: Tuple[int, ...], config: Dict[str, Any], fp: str,
               note: str) -> Dict[str, Any]:
    """The pool row for a config that is not in the pool and not already scheduled."""
    row = {
        "phase_id": _candidate_phase_id(fam, pattern, knobs, sides, fp),
        "label": _label_for(fam, pattern, knobs),
        "dtype": FAMILY_DTYPE[fam].lower(),
        "shapes": _shape_list(sides),
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
    return row


def _offer_row(
    sched: CandidateGenerator,
    seen_fp: Set[str],
    pool: Dict[str, Dict[str, Any]],
    fam: str,
    tier: str,
    pattern: str,
    knobs: Dict[str, Any],
    sides: Tuple[int, ...],
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """Validate one candidate config and fold it into the fp-keyed pool.

    Returns the new row the first time a config is seen (None when it is a
    duplicate, illegal, or already scheduled by the deck/seed); a config already
    in the pool gets this cell added to its shape list instead.
    """
    knobs = _with_depth_u(knobs)
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
    # The element-multiple assertions are the one knob class whose correctness
    # depends on the *shape*, so they are checked here -- the only place config
    # and shape are both in scope. See _ELEMENT_ASSERTIONS for why nothing else
    # in the pipeline catches a violation.
    offered = len(sides)
    sides, refused = _shapes_satisfying_assertions(config, sides)
    if not sides:
        DROPPED_ASSERTIONS.append(
            f"{note} [dropped: {refused[0] if refused else 'no shape satisfies'}]"
            .strip())
        return None
    if refused:
        note = (f"{note} [assertion filter: {len(refused)} of {offered} shapes"
                f" refused]").strip()
    fp = _fingerprint(config)
    existing = pool.get(fp)
    if existing is None:
        if fp in seen_fp:
            return None
        row = _build_row(fam, tier, pattern, knobs, sides, config, fp, note)
        pool[fp] = row
        return row
    existing["shapes"] = _merge_shapes(existing["shapes"], sides)
    if note and not existing.get("note"):
        existing["note"] = note
    return None


def _auto_row_gen(offer) -> Iterator[Dict[str, Any]]:
    """The explicit per-family AUTO candidates."""
    for fam, specs in AUTO_EXPLICIT.items():
        for spec_ in specs:
            side = int(spec_["shapes"][0].split("x")[0])
            knobs = {k: v for k, v in spec_.items()
                     if k not in ("shapes", "pattern", "note")}
            row = offer(fam, "auto", spec_["pattern"], knobs, (side,),
                        note=spec_.get("note", ""))
            if row:
                yield row


def _plan_batch_row_gen(offer) -> Iterator[Dict[str, Any]]:
    """Rows from the hand-written PLAN_BATCH plan."""
    for spec_ in PLAN_BATCH:
        fam = spec_["fam"]
        knobs = {k: v for k, v in spec_.items()
                 if k not in ("fam", "pattern", "note")}
        row = offer(fam, "auto", spec_["pattern"], knobs,
                    tuple(TARGET_CELLS[fam]), note=spec_.get("note", ""))
        if row:
            yield row


def iter_candidates() -> Iterator[Dict[str, Any]]:
    """Yield validated, fp-deduped candidate rows (open/free of overlay state).

    A candidate *phase* is one config carrying a SHAPE LIST (like the deck
    rows); a fingerprint is config-level and needs exactly one row, or the
    spread of shapes collapses to the first cell that mentions it.

    Rows pruned because no target shape satisfied their element-multiple
    assertions are recorded in ``DROPPED_ASSERTIONS`` rather than vanishing, so
    a run can report them.
    """
    del DROPPED_ASSERTIONS[:]
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
        return _offer_row(sched, seen_fp, pool, fam, tier, pattern, knobs,
                          sides, note)

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

    yield from _auto_row_gen(_offer)
    yield from _plan_batch_row_gen(_offer)


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
            # GSU>1 is unavailable on CC/ZZ (complex, no MFMA) and on
            # HH_HPA/HS_HPA (f32 accumulate), and is banned on HH by decision.
            # Ask the domain rather than repeating that list here: it used to be
            # a hand-written tuple that could drift from db_knobs silently.
            if knob == "GlobalSplitU" and val not in forward_domain(fam, knob):
                continue
            nbrs = NARROW_NEIGHBOURS[knob].get(val)
            if not nbrs:
                continue
            for nb in nbrs:
                knobs = {**winner, knob: nb}
                fp = _fingerprint({**_base_config(fam), **knobs,
                                   "ContractionPattern":
                                   _pattern_for(fam, knobs.get("MacroTile", ""))})
                if fp in pool:
                    pool[fp]["shapes"] = _merge_shapes(
                        pool[fp]["shapes"], (side,))
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
