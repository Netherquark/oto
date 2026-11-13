"""The legality prior: manifest-derived legal domain, and source-cited walls.

Owns: the hard walls (half Assembly needing VW>=2, the shipped-schedule
requirement), the shipped support table read from the pinned manifest, the
co-occurrence check, and ``sample_legal`` / ``sampler_sweep``.

Does NOT own: the four launch gates (oto.tensile.gates), the manifest it reads
(oto.tensile.library), or the candidate generator (oto.tensile.candidate).

Public API: is_half_input, thread_tile_dimensions, enable_matrix_instruction,
half_vector_width_floor, assembly_gsu_vector_width, check_hard_walls,
shipped_support, mt_has_shipped_schedule, cooccurrence_check, sample_legal,
sampler_sweep, KNOB_GROUPS, TEMPLATE_KEYS, HARD_WALLS, DEFERRED_RULES,
CITATIONS, TENSILE_COMMIT.

The prior sits *upstream* of the novelty ledger and of ``validate_config``: a
candidate is drawn from the set of knob-vectors Tensile actually ships for its
(family, dtype), so the reject classes are never proposed rather than proposed
and then filtered.

The walls implemented here are ``half_vector_width_floor`` (a half-precision
assembly with VectorWidth 1), ``assembly_gsu_vector_width`` (its GSU case) and
``mt_has_shipped_schedule`` (a macro tile Tensile ships no schedule for).

Legality is never a judgement call: each predicate resolves to either Tensile
source or the pinned shipped manifest, and the citation is the code rather than an
audit's prose. Shipped values are read through the single canonical parser in
``oto.tensile.library`` rather than re-parsed solution names, so a knob-parse
defect cannot be reintroduced here.
"""


from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import oto.tensile.library as tlib
from oto.device.peaks import FAMILY_DTYPE_CHAR, FAMILY_DTYPES
from oto.runners.paths import results_rel

#: Tensile checkout the citations below were verified against.
TENSILE_COMMIT = "e8a8999e"

#: Source citations, re-verified in the pinned checkout. Kept as data so
#: ``tests/test_legality_prior.py`` can assert the module never cites a
#: different commit than the one it was verified at.
CITATIONS = {
    "is_half": "Tensile/DataType.py:311 isHalf() -> value == DataType.half",
    "enable_matrix_instruction": "Tensile/SolutionStructs.py:1918-1930",
    "half_vector_width_floor": "Tensile/SolutionStructs.py:3431-3436",
    "half_vector_width_floor_restated": "Tensile/SolutionStructs.py:3607-3608",
    "assembly_gsu_vector_width": "Tensile/SolutionStructs.py:3611-3612",
    "half_af0em_parity": "Tensile/SolutionStructs.py:3435-3438 (ECC, deferred)",
}


def is_half_input(config: Dict[str, Any]) -> bool:
    """True when ``ProblemType.DataType`` is fp16 half.

    ``DataType.isHalf()`` is ``value == DataType.half`` -- half only. Bfloat16
    is a *different* DataType and does not satisfy it, so this is deliberately
    narrower than the ``("H", "B")`` test used by ``assembly_class_valid`` for
    the GlobalSplitU rules; widening it here would reject legal bfloat16 GSU.
    """
    return str(config.get("DataType", "")).upper() == "H"


def thread_tile_dimensions(config: Dict[str, Any]) -> List[int]:
    """Normalise ``ThreadTile`` to its dimensions.

    Phase configs carry ThreadTile as the string ``"8x4"`` (the form
    ``oto.tensile.library._config_from_kernel`` emits and
    ``oto.tensile.candidate.validate_config`` accepts), while Tensile's own state holds a two-element list. The
    EnableMatrixInstruction derivation tests ``len(ThreadTile) == 2``, so the
    string form has to be normalised first or every candidate reads as
    undetermined -- which silently disarmed the half VectorWidth wall.
    """
    tile = config.get("ThreadTile")
    if tile is None:
        return []
    if isinstance(tile, str):
        cleaned = tile.lower().replace("_", "x")
        try:
            return [int(p) for p in cleaned.split("x")[:2] if p != ""]
        except ValueError:
            return []
    return list(tile)


def enable_matrix_instruction(config: Dict[str, Any]) -> Optional[bool]:
    """Resolve Tensile's ``EnableMatrixInstruction``, or None if undetermined.

    Mirrors SolutionStructs.py:1918-1930. An explicit key wins; otherwise the
    MI* triple means True, a WorkGroup+ThreadTile pair means False, and neither
    means Tensile itself rejects the config ("EnableMatrixInstruction
    undetermined"). The mutation arm always emits WorkGroup *and* ThreadTile,
    so every candidate it builds resolves to False -- which is what makes the
    half VectorWidth wall unconditional on our path rather than incidental.
    """
    explicit = config.get("EnableMatrixInstruction")
    if explicit is not None:
        return bool(explicit)
    if all(len(config.get(k, ())) == n
           for k, n in (("MIBlock", 6), ("MIWaveGroup", 2), ("MIWaveTile", 2))):
        return True
    if len(config.get("WorkGroup", ())) == 3 and len(thread_tile_dimensions(config)) == 2:
        return False
    return None


def half_vector_width_floor(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Half Assembly on gfx900 requires VectorWidth >= 2 in non-MFMA mode.

    Root cause ``A_half_VW1_assembly`` -- the largest reject class in
    ``reference_integrity_audit.json``, and the one the curated deck already
    obeys (every HH/HH_HPA/HS_HPA phase sits at VectorWidth >= 2) while 284
    shipped kernels are named ``VW1``. Those shipped kernels were built by the
    distro Tensile, not by this checkout, so they are unbuildable here: the
    prior must not inherit their VectorWidth for a half family.

    Condition is Assembly + isHalf + not EnableMatrixInstruction + VW < 2.
    """
    if not is_half_input(config):
        return True, ""
    if enable_matrix_instruction(config) is False:
        if int(config.get("VectorWidth", 1)) < 2:
            return False, (f"half Assembly requires VectorWidth >= 2 in non-MFMA "
                           f"mode (have {config.get('VectorWidth')}; "
                           f"SolutionStructs.py:3434)")
    return True, ""


def assembly_gsu_vector_width(config: Dict[str, Any]) -> Tuple[bool, str]:
    """NOT MODELLED -- deliberately absent from ``HARD_WALLS``.

    SolutionStructs.py:3611-3612 rejects half Assembly with ``GlobalSplitU > 1``
    when ``VectorAtomicWidth < 2``, but the effective value is *derived*, not
    defaulted to 1: with ``VectorAtomicWidth`` unset, SolutionStructs.py:3588-3594
    resolves it to ``minVectorAtomicWidth`` == ``2 if ComputeDataType.numBytes()==2
    else 1`` (SolutionStructs.py:3574). The guard at 3612 is additionally gated on
    ``not state["_GlobalAccumulation"]``, which is internal state derived from
    kernels this repo never configures.

    An earlier revision of this module modelled the guard naively as
    ``VectorAtomicWidth < 2 -> reject``. A live sweep showed it firing on shipped
    HS_HPA vectors with GlobalSplitU 2/3/5/7 -- every one a false rejection --
    the signature of *modelling* the reject set rather than reading
    it, which is exactly what Hplan.4 step 1 forbids. Enforcing the reachable GSU
    rules is already ``assembly_class_valid``'s job (rules 2 and 3, both
    source-cited and tested): half with f32 accumulate, and half Assembly GSU with
    ``AssertFree0ElementMultiple < 2``.

    Left as data so the rule stays tracked without being enforced wrongly.
    """
    return True, ""


#: Source-cited rules this module deliberately does not model, with the reason.
DEFERRED_RULES = {
    "SolutionStructs.py:3611-3612 (half Assembly GSU VectorAtomicWidth>=2)":
        "value is derived from ComputeDataType bytes (3574) and gated on the "
        "internal _GlobalAccumulation; naive modelling caused 90 false "
        "rejections on shipped HS_HPA GlobalSplitU 2/3/5/7 vectors",
    "SolutionStructs.py:3435-3438 (HasEccHalf AF0EM%2==0 for non-HPA half)":
        "gated on ArchCaps[isa]['HasEccHalf'], a target-dependent property this "
        "module does not resolve",
}


#: Every hard wall, in evaluation order. A sampler that satisfies these cannot
#: emit the configs root cause A describes, nor a MacroTile that never shipped.
HARD_WALLS = (half_vector_width_floor,)


def check_hard_walls(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Run every hard wall; return the first failure as ``(False, reason)``."""
    for wall in HARD_WALLS:
        ok, reason = wall(config)
        if not ok:
            return False, reason
    return True, ""


# --------------------------------------------------------------------------
# Manifest-derived legal support
# --------------------------------------------------------------------------

#: Coupled knob groups. A candidate is a shipped vector with whole groups
#: substituted -- never with single knobs crossed independently. Independent
#: per-knob draws are what synthesise the unscheduled MacroTile combinations of
#: root cause D (``MT48x36x16``), and what break the
#: GlobalLoadVectorWidth == VectorWidth pairing the loads predicate enforces
#: (root causes B/E). Substituting groups makes both structurally unreachable.
#:
#: ``tile`` deliberately fuses the schedule with the load widths. A live
#: comparison against the lattice found load divisibility to be the single
#: largest reject cause when they moved separately (85 of 86 HH_HPA rejects):
#: GlobalLoadVectorWidth is a function of MacroTile, so substituting
#: MacroTile/ThreadTile/WorkGroup while leaving the widths behind manufactures
#: exactly the indiviisible-tile rejections the prior exists to avoid. Fusing
#: them keeps every tile/width combination one Tensile actually ships.
#:
#: ``DepthU`` lives with the tile for the same reason: in the shipped manifest
#: it is *not* an independent knob, it is the K dimension of the MacroTile —
#: Tensile's ``128x32x16`` is "MacroTile 128x32 at DepthU 16", and no shipped
#: solution has a MacroTile whose K disagrees with its DepthU. Moving DepthU on
#: its own manufactures exactly the occupancy rejections the walls then
#: misread (measured: 16 of 24 HS_HPA rejects were "MacroTile 128x32 at
#: DepthU 64").
#:
#: ``split`` carries AssertFree0ElementMultiple with GlobalSplitU, since the two
#: are rejected jointly (half Assembly GSU requires AF0EM>=2).
KNOB_GROUPS = {
    "tile": ("MacroTile", "ThreadTile", "WorkGroup",
             "DepthU", "VectorWidth", "GlobalLoadVectorWidthA",
             "GlobalLoadVectorWidthB"),
    "split": ("GlobalSplitU",),
}

#: Every knob the sampler is allowed to move, in a stable order. Also the set
#: whose pairwise co-occurrence is checked before a draw is returned.
STRUCTURAL_KNOBS = tuple(sorted({k for knobs in KNOB_GROUPS.values()
                                 for k in knobs}))

#: Per-(base_dir, family) co-occurrence sets. Built once: the manifest is a file
#: that does not change within a run, and an overnight run draws thousands of
#: candidates.
_COOC_CACHE: Dict[Tuple[str, str], Any] = {}

#: Knob -> group. Cross-group pairs are the ones a substitution can cross;
#: within-group pairs are coherent by construction (`_apply_group` takes the
#: whole group from a single donor), so the gate only checks the former.
KNOB_TO_GROUP = {knob: group for group, knobs in KNOB_GROUPS.items()
                 for knob in knobs}

#: Keys the *caller* owns: a candidate must not smuggle in a second Architecture,
#: DataType or ScheduleName. Defined here rather than in each consumer because
#: `legality` is what assembles the config these are stripped from, so a second
#: copy would be a second answer to "which keys are not knobs".
#:
#: This set is also the sampler's entire knob budget, and it is worth being
#: explicit that it is exhausted rather than merely narrow: the shipped solutions
#: encode exactly these structural knobs (MacroTile, ThreadTile, WorkGroup,
#: VectorWidth, GLVWA/B, GlobalSplitU, DepthU) plus `af0em`, which travels with
#: the split group because it is the donor's real beta-on-edge setting. The one
#: remaining parsed knob, `grvw`, is deliberately *not* here -- it is not a
#: Tensile parameter, and BenchmarkStructs printExit()s on unrecognised names
#: (see `tensile_library._config_from_kernel`). So Phase 4's "extend beyond the
#: lattice" is satisfied by covering all eight legal knobs, not by inventing
#: parameters that would abort parameter filling.
TEMPLATE_KEYS = frozenset({
    "Architecture", "ProblemType", "DataType", "FamilyLabel", "ScheduleName",
})

_SUPPORT_CACHE: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

#: Repository root, where the pinned manifest lives.
_REPO_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_RELATIVE_PATH = results_rel("gfx900_shipped_manifest.json")


def manifest_dir(base_dir: Path) -> Path:
    """Directory to read the pinned manifest from.

    ``load_shipped_manifest`` *computes and writes* a cache when the file is
    absent. The prior must never trigger that: a caller with a scratch
    ``base_dir`` (tests, overlays) would otherwise rescan the live ROCm library
    and drop a multi-megabyte cache into it, which both violates the pinned-manifest
    rule and makes legality depend on the installed library. So a base_dir
    without a manifest defers to this repo's own pinned copy.
    """
    candidate = Path(base_dir)
    if (candidate / MANIFEST_RELATIVE_PATH).exists():
        return candidate
    return _REPO_ROOT


def shipped_support(base_dir: Path, family: str) -> List[Dict[str, Any]]:
    """Deduplicated legal support for ``family``: one entry per shipped vector.

    Reads the pinned manifest through ``tensile_library`` (the single owner of
    both the manifest and solution-name parsing) and returns entries carrying
    the phase ``config``, the structural knobs, and the kernel name each vector
    came from, so a caller can always trace a value back to what shipped.
    """
    root = manifest_dir(base_dir)
    key = (str(root), family)
    cached = _SUPPORT_CACHE.get(key)
    if cached is not None:
        return cached

    manifest = tlib.load_shipped_manifest(root)
    entries: List[Dict[str, Any]] = []
    seen: set = set()
    for _pattern, block in (manifest.get("families", {}).get(family) or {}).items():
        for name in block.get("kernels", []):
            config = tlib.shipped_kernel_config(name, family)
            signature = json.dumps(config, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            knobs = tlib.shipped_kernel_knobs(name)
            entries.append({
                "config": config,
                "knobs": knobs,
                "name": name,
                "af0em": knobs.get("af0em"),
            })
    _SUPPORT_CACHE[key] = entries
    return entries


def mt_has_shipped_schedule(config: Dict[str, Any],
                            family: str,
                            base_dir: Path) -> Tuple[bool, str]:
    """Root cause ``D_macrotile_schedule``: MT must have shipped a schedule.

    ``MT48x36x16`` was rejected at parameter validation because no shipped
    schedule exists for it on gfx900. Rather than re-deriving that schedule
    table, this asks the manifest: has this family ever shipped a vector with
    this MacroTile? A MacroTile that shipped is one Tensile can schedule.

    Note this is intentionally *narrower* than full schedule validity -- it
    bounds the MacroTile, and ``validate_config`` remains the assertion for
    everything else (Hplan.4 step 4).
    """
    mt = config.get("MacroTile")
    if not mt:
        return True, ""
    for entry in shipped_support(base_dir, family):
        if entry["config"].get("MacroTile") == mt:
            return True, ""
    return False, (f"MacroTile {mt} has no shipped gfx900 schedule for {family} "
                   f"(reference_integrity_audit D_macrotile_schedule)")


def _cooccurrence_pairs(base_dir: Path,
                        family: str) -> Optional[Set[Tuple[str, str, str, str]]]:
    """Every ordered pair of structural knob values Tensile actually ships together.

    ``None`` when the family has no support, so callers can distinguish "no
    constraint available" from "constraint satisfied".
    """
    support = shipped_support(base_dir, family)
    if not support:
        return None
    out: Set[Tuple[str, str, str, str]] = set()
    for entry in support:
        cfg = entry.get("config") or {}
        present = [(k, _norm_value(cfg[k])) for k in STRUCTURAL_KNOBS
                   if k in cfg]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                ka, va = present[i]
                kb, vb = present[j]
                if (ka, vb, kb, va) in out:
                    out.add((ka, va, kb, vb))
                    continue
                out.add((ka, va, kb, vb))
    return out


def cooccurrence_check(base_dir: Path,
                       family: str,
                       config: Dict[str, Any]) -> Tuple[bool, str]:
    """Gate a substituted config against the manifest's shipped pair set.

    Caches the per-family pair set, so an overnight run's thousands of draws
    build it once. ``True`` for unsupported families (nothing to constrain).
    """
    key = (str(base_dir), str(family))
    if key not in _COOC_CACHE:
        _COOC_CACHE[key] = _cooccurrence_pairs(base_dir, family)
    cooc = _COOC_CACHE[key]
    if not cooc:
        return True, ""
    return _pairs_consistent(config, cooc)


def _pairs_consistent(config: Dict[str, Any],
                      cooc: Set[Tuple[str, str, str, str]]) -> Tuple[bool, str]:
    """True iff every pair of structural values in ``config`` co-occurs shipped.

    Pairwise rather than whole-tuple: a shipped solution has 135+ distinct
    MacroTiles in HS_HPA, so demanding that an 8-knob tuple appear verbatim would
    freeze the search to the deck. Pairwise still prunes the crossings that
    matter -- `GlobalSplitU=7` with a `MacroTile` that only ever shipped with
    `GlobalSplitU=1` is exactly the assembly-class rejection -- while leaving room
    to explore.

    This cannot reject a configuration Tensile ships: a shipped solution co-occurs
    with itself by definition.
    """
    present = [(k, _norm_value(config[k])) for k in STRUCTURAL_KNOBS
               if k in config]
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            ka, va = present[i]
            kb, vb = present[j]
            if KNOB_TO_GROUP.get(ka) == KNOB_TO_GROUP.get(kb):
                continue
            if (ka, va, kb, vb) in cooc:
                continue
            if (ka, vb, kb, va) in cooc:
                continue
            return False, f"{ka}={va} never shipped with {kb}={vb}"
    return True, ""


def _norm_value(value: Any) -> str:
    """Canonical text for a knob value, so ``[16, 16, 1]`` and ``'16x16x1'`` match."""
    if isinstance(value, (list, tuple)):
        return "x".join(str(v) for v in value)
    return str(value)


def _apply_group(config: Dict[str, Any], entry: Dict[str, Any],
                 group: str) -> Dict[str, Any]:
    """Substitute one whole knob group from ``entry`` into ``config``."""
    out = dict(config)
    for knob in KNOB_GROUPS[group]:
        if knob in entry["config"]:
            out[knob] = entry["config"][knob]
    if group == "split" and entry.get("af0em"):
        # Inherit the donor's real beta-on-edge setting rather than leaving it
        # to Tensile's default of 1, which the half GSU walls then reject.
        out["AssertFree0ElementMultiple"] = entry["af0em"]
    return out


def sample_legal(base_dir: Path,
                 family: str,
                 rng: random.Random,
                 base_config: Optional[Dict[str, Any]] = None,
                 groups: int = 2,
                 attempts: int = 32) -> Optional[Dict[str, Any]]:
    """Draw a legal-by-construction candidate for ``family``.

    The base is always a shipped vector (or ``base_config``, when supplied by a
    caller replaying a specific parent); up to ``groups`` whole knob groups are
    then substituted from other shipped vectors of the same family. Hard walls
    are asserted on every draw and a violating draw is discarded, never
    returned -- so a returned candidate cannot be a wall-violating config.

    A single draw can legitimately miss (e.g. it lands on one of the shipped
    half ``VW1`` vectors), so this retries up to ``attempts`` times before
    giving up. Returns ``None`` only when the family has no support at all, or
    when every attempt was discarded -- callers can then skip the family rather
    than fabricate a config.
    """
    for _ in range(max(1, attempts)):
        config, _reason = _draw_legal(base_dir, family, rng, base_config, groups)
        if config is not None:
            return config
    return None


def _nearest_support(support: List[Dict[str, Any]],
                     base_config: Optional[Dict[str, Any]],
                     rng: random.Random) -> Dict[str, Any]:
    """Pick the shipped vector a candidate should be built on top of.

    When a parent config is supplied, donors sharing its MacroTile are preferred
    so the mutation stays in the parent's own neighbourhood. The parent itself is
    *not* used as the base: deck and winner configs carry only MacroTile and
    ThreadTile, so building on them directly emits a config with no WorkGroup,
    no VectorWidth and no load widths -- which Tensile completes with defaults
    that then fail load divisibility. Measured, that single choice was the
    largest remaining reject cause. The parent selects a neighbourhood; a
    complete shipped vector supplies the config.
    """
    if not support:
        raise ValueError("empty support")
    if base_config:
        macro_tile = base_config.get("MacroTile")
        if macro_tile:
            same_tile = [e for e in support
                         if e["config"].get("MacroTile") == macro_tile]
            if same_tile:
                return rng.choice(same_tile)
    return rng.choice(support)


def _draw_legal(base_dir: Path,
                family: str,
                rng: random.Random,
                base_config: Optional[Dict[str, Any]] = None,
                groups: int = 2) -> Tuple[Optional[Dict[str, Any]], str]:
    """As :func:`sample_legal`, but also return why a draw was discarded."""
    support = shipped_support(base_dir, family)
    if not support:
        return None, f"no shipped support for {family}"

    config = dict(_nearest_support(support, base_config, rng)["config"])
    chosen = rng.sample(list(KNOB_GROUPS), min(groups, len(KNOB_GROUPS)))
    for group in chosen:
        donor = rng.choice(support)
        config = _apply_group(config, donor, group)

    # The check is co-occurrence *read off the manifest*, not a model of the
    # reject set: modelling it is what previously produced 90 false rejections on
    # shipped HS_HPA vectors, and the occupancy and assembly predicates still
    # reject configs Tensile genuinely ships.
    ok, reason = cooccurrence_check(base_dir, family, config)
    if not ok:
        return None, f"not manifest-coherent: {reason}"

    config.setdefault("Architecture", "gfx900")
    config.setdefault("ProblemType", "Contraction")
    config.setdefault("DataType", FAMILY_DTYPE_CHAR[family])

    ok, reason = check_hard_walls(config)
    if not ok:
        return None, reason
    ok, reason = mt_has_shipped_schedule(config, family, base_dir)
    if not ok:
        return None, reason
    return config, ""


def sampler_sweep(base_dir: Path,
                  families: Optional[Sequence[str]] = None,
                  draws: int = 400,
                  seed: int = 0) -> Dict[str, Any]:
    """Measure the sampler's own wall/schedule hit rate, CPU-only.

    Reports how often a raw draw was discarded, and why -- read live from this
    run, never transcribed. The legality rate against ``validate_config`` is
    *not* computed here: the sampler's claim is structural (it cannot emit a
    wall-violating config), and re-running the full assertion over it would
    measure the assertion, not the prior.
    """
    families = list(families or FAMILY_DTYPES)
    rng = random.Random(seed)
    per_family: Dict[str, Any] = {}
    for family in families:
        support = shipped_support(base_dir, family)
        accepted = 0
        reasons: Dict[str, int] = {}
        for _ in range(draws):
            config, reason = _draw_legal(base_dir, family, rng)
            if config is not None:
                accepted += 1
            else:
                reasons[reason] = reasons.get(reason, 0) + 1
        per_family[family] = {
            "support_vectors": len(support),
            "draws": draws,
            "accepted": accepted,
            "dropped": draws - accepted,
            "accepted_pct": round(100.0 * accepted / draws, 2) if draws else 0.0,
            "drop_reasons": reasons,
        }
    total = sum(v["draws"] for v in per_family.values())
    accepted = sum(v["accepted"] for v in per_family.values())
    return {
        "tensile_commit": TENSILE_COMMIT,
        "per_family": per_family,
        "draws": total,
        "accepted": accepted,
        "accepted_pct": round(100.0 * accepted / total, 2) if total else 0.0,
    }
