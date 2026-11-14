#!/usr/bin/env python3
"""The shipped gfx900 manifest: pinning, identity, and the rerun tier triage.

Owns: the pinned manifest and its refresh policy (``load_shipped_manifest``), the
identity of a phase (``phase_key``, ``config_fingerprint``), the rerun triage and
its ordering (``load_rerun_manifest``, ``tier_for``, ``apply_rerun_tiers``), and
the reference run chain (``latest_reference_run_id``, ``reference_chain``).

A floor is only a floor if it is the same measurement twice: the manifest is
computed from the live dat once, cached, and regenerated only on an explicit
``--refresh`` -- and the config fingerprint is what decides whether a cached
measurement still describes the config that would run now.

Does NOT own: the binary .dat parse and the spoof-phase emitter
(oto.tensile.shipped_floor).
Public API: see ``__all__``.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from oto.runners.result_paths import results_rel

#: Where the pinned shipped manifest is cached, relative to the project root.
MANIFEST_PATH = results_rel("gfx900_shipped_manifest.json")


def manifest_rel(arch: str = "gfx900") -> str:
    """The results-relative cache filename for a reference arch's manifest."""
    return results_rel(f"{arch}_shipped_manifest.json")

# The shipped-library parse and the spoof-phase emitter live in their own module
# so the manifest cache, the tier triage and the identity helpers here are not
# buried under a binary .dat parser.
from oto.tensile.shipped_floor import (
    CONTRACTION_PATTERNS,
    SHIPPED_FAMILIES,
    _all_rocm_prefixes,
    _resolve_rocm,
    emit_spoof_phases,
    find_gfx900_dat_files,
    parse_shipped_kernels,
    shipped_kernel_config,
    shipped_kernel_knobs,
)

__all__ = [
    "CONTRACTION_PATTERNS",
    "MANIFEST_PATH",
    "SHIPPED_FAMILIES",
    "TIER_DROP",
    "TIER_FIRST",
    "TIER_HELD",
    "TIER_KEEP",
    "TIER_LAST",
    "apply_rerun_tiers",
    "config_fingerprint",
    "emit_spoof_phases",
    "find_gfx900_dat_files",
    "latest_reference_run_id",
    "load_rerun_manifest",
    "load_shipped_manifest",
    "manifest_rel",
    "parse_shipped_kernels",
    "phase_key",
    "reference_chain",
    "shipped_kernel_config",
    "shipped_kernel_knobs",
    "tier_for",
]


def _find_shipped_dats(prefix: Path, arch: str = "gfx900") -> list[Path]:
    """Candidate .dat files under one ROCm prefix."""
    return find_gfx900_dat_files(prefix, arch=arch)


def _parse_dat_filename(df: Path) -> tuple[str, str] | None:
    """(family, pattern) from a TensileLibrary dat filename, or None."""
    parts = df.name.split("_")
    try:
        type_idx = parts.index("Type")
        end_t = parts.index("Contraction")
        type_token = "_".join(parts[type_idx + 1:end_t])
        l_idx = parts.index("l")
        end_p = parts.index("Cijk")
        pattern = "_".join(parts[l_idx + 1:end_p])
    except (ValueError, IndexError):
        return None
    if type_token not in SHIPPED_FAMILIES:
        return None
    if pattern not in CONTRACTION_PATTERNS:
        return None
    return type_token, pattern


def _scan_one_dat(
    df: Path,
    fam: str,
    pat: str,
    prefix: Path
) -> dict[str, Any] | None:
    """Parse one .dat -> kernel list + metadata dict, or None if parse fails."""
    kernels = parse_shipped_kernels(df)
    if not kernels:
        return None
    return {
        "family": fam,
        "pattern": pat,
        "rocm_prefix": str(prefix),
        "path": str(df),
        "mtime": df.stat().st_mtime,
        "size": df.stat().st_size,
        "kernels": sorted(kernels),
    }


def _build_fam_patterns(scanned: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    """Aggregate kernels by family and pattern from scanned dat entries."""
    fam_patterns: dict[str, dict[str, set[str]]] = {}
    for s in scanned:
        fam = fam_patterns.setdefault(s["family"], {})
        fam.setdefault(s["pattern"], set()).update(s["kernels"])
    return fam_patterns


def _build_families(
    fam_patterns: dict[str, dict[str, set[str]]],
    scanned: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-family per-pattern kernel lists and source prefixes.

    `scanned` supplies the rocm prefixes each (family, pattern) was found under,
    so one account can share a kernel that lives in several ROCm installs.
    """
    families: dict[str, dict[str, Any]] = {}
    for fam, pats in fam_patterns.items():
        fam_info = {}
        for pattern in CONTRACTION_PATTERNS:
            kernels = sorted(pats.get(pattern, set()))
            sources = sorted({s["rocm_prefix"] for s in scanned
                              if s["family"] == fam and s["pattern"] == pattern})
            fam_info[pattern] = {
                "kernels": kernels,
                "count": len(kernels),
                "sources": sources,
            }
        families[fam] = fam_info
    return families


def _scan_dat_library(arch: str = "gfx900") -> dict[str, Any]:
    """Scan the installed TensileLibrary of reference `arch` into a manifest."""
    active_rocm = _resolve_rocm()
    prefixes = _all_rocm_prefixes()
    scanned: list[dict[str, Any]] = []
    total_kernels = 0
    for prefix in prefixes:
        for df in _find_shipped_dats(prefix, arch):
            parsed = _parse_dat_filename(df)
            if not parsed:
                continue
            fam, pat = parsed
            entry = _scan_one_dat(df, fam, pat, prefix)
            if not entry:
                continue
            total_kernels += len(entry["kernels"])
            scanned.append(entry)
    fam_patterns = _build_fam_patterns(scanned)
    families = _build_families(fam_patterns, scanned)
    expected_kernels = {
        fam: sum(fam_info.get(p).get("count", 0) for p in CONTRACTION_PATTERNS)
        for fam, fam_info in families.items()
    }
    return {
        "generated_at": datetime.now().isoformat(),
        "spoof_reference": arch,
        "rocm_path": active_rocm,
        "rocm_prefixes": prefixes,
        "dat_files": scanned,
        "families": families,
        "expected_kernels": expected_kernels,
        "total_shipped_kernels": sum(expected_kernels.values()),
    }


def load_shipped_manifest(base_dir: Path, refresh: bool = False,
                          arch: str = "gfx900") -> dict[str, Any]:
    """Return the pinned shipped-library manifest for `arch` (compute-once, pin).

    First load scans the system dat and writes the cache; later loads reuse it
    until refresh=True (the --reference refresh flag). Never touches the live
    dat on report-only paths once pinned. The cache filename and the scan are
    arch-scoped, so a second reference arch gets its own manifest.
    """
    manifest_path = Path(base_dir) / manifest_rel(arch)
    if not refresh and manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            pass

    manifest = _scan_dat_library(arch)
    manifest["cache_path"] = str(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def latest_reference_run_id(registry, arch: str = "gfx900") -> str | None:
    """Return the most recently *completed, non-smoke* `arch` reference run id.

    Smoke floors are bring-up runs (`--limit`), never a floor: a smoke run
    force-completed must not be recalled as the A/B reference."""
    import sqlite3
    try:
        conn = sqlite3.connect(registry.db_path, timeout=30.0)
        try:
            esc = (arch.replace("\\", "\\\\")
                   .replace("%", "\\%").replace("_", "\\_"))
            rows = conn.execute(
                "SELECT run_id, status, metadata FROM runs "
                "WHERE run_id LIKE ? ESCAPE '\\' ORDER BY id DESC",
                (esc + r"\_ref\_%",)
            ).fetchall()
        finally:
            conn.close()
        for run_id, status, metadata in rows:
            if status != "completed":
                continue
            try:
                smoke = bool(json.loads(metadata or "{}").get("smoke"))
            except Exception:
                smoke = False
            if not smoke:
                return run_id
    except Exception:
        return None
    return None


def phase_key(phase: dict[str, Any]) -> str:
    """Stable identity for a phase, independent of parsed knob values.

    `phase_id` embeds the knobs that `_parse_kernel_knobs` derived, so any fix to
    those parsers renames every phase. Completion was then re-decided from
    scratch: almost every id changed between two consecutive runs, so one resume
    silently re-ran the whole floor.

    The shipped solution name is the authoritative kernel identity and does not
    depend on our parsing, so hash that instead.
    """
    name = str(phase.get("kernel") or "")
    if not name:
        return "pid_" + hashlib.sha1(str(phase.get("phase_id", "")).encode()).hexdigest()[:12]
    return "k_" + hashlib.sha1(name.encode()).hexdigest()[:12]


def config_fingerprint(phase: dict[str, Any]) -> str:
    """Content hash of everything that determines the measured kernel.

    A prior measurement may only be reused when this matches the value recorded
    with that measurement. Closes the phase_id hole: a fixed parser (or any knob
    change) now invalidates exactly the affected measurements instead of
    silently reusing them under a stale id.

    The config half reuses registry.fingerprint_config (the existing `fp` field)
    so there is a single notion of config identity; the phase-level half adds the
    things that are not in the config dict but still change what gets measured.
    """
    from oto.ledger.registry import fingerprint_config
    cfg = dict(phase.get("config") or {})
    material = {
        "config_fp": fingerprint_config(cfg),
        "dtype": phase.get("dtype"),
        "ScheduleName": phase.get("ScheduleName"),
        "NumBenchmarks": phase.get("NumBenchmarks"),
        "shapes": phase.get("shapes"),
        "kernel": phase.get("kernel"),
    }
    blob = json.dumps(material, sort_keys=True, default=str)
    return "fp_" + hashlib.sha1(blob.encode()).hexdigest()[:16]


RERUN_MANIFEST_PATH = results_rel("reference_rerun_manifest.json")

# ---------------------------------------------------------------------------
# Reference-cell classification.
#
# These tiers only *classify* the reference corpus. They never decide anything.
# Whether to re-measure each class is asked at the start of every --auto run
# (see auto_prompt.py); the four answers become an AutoPlan, and that plan is
# the only thing that governs a run. The names below are the historical T1/T2/T3
# labels, kept because they appear in the stored manifest and in every run
# directory on disk -- renaming the constants would silently invalidate the
# triage that has already been audited.
#
#   TIER_FIRST  "T1_RERUN"           ILLEGAL
#       These cells were measured with a config our own extractors got wrong
#       (GlobalReduceVectorWidth, glvw/grvw handling), so the measurement does
#       not describe the kernel it claims to. Nothing downstream can be trusted
#       while they stand. Cheap: 127 cells.
#
#   TIER_HELD   "T2_RERUN_HELD"      UNDER-SPECIFIED
#       Correct but loose: glvw/grvw were left to Tensile's defaults, so the
#       config is not pinned and a rebuild may not reproduce it. No known
#       correctness problem, and re-measuring all of them is a ~1 day GPU job.
#       Default answer is therefore no, and it is a question rather than a
#       policy because the cost is the user's to judge.
#
#   TIER_LAST   "T2_RERUN_LAST"      UNDER-SPECIFIED, older manifest spelling
#   TIER_DROP   "T3_UNREPRODUCIBLE"  UNREPRODUCIBLE
#       Current Tensile cannot derive these kernels at all. Re-running them just
#       reproduces the failure, so they are left failed on purpose and are never
#       staged.
#
#   TIER_KEEP   "T0_KEEP"            FINE
#       Config and measurement agree. Leave alone.
# ---------------------------------------------------------------------------
TIER_DROP = "T3_UNREPRODUCIBLE"   # UNREPRODUCIBLE: never re-run
TIER_FIRST = "T1_RERUN"           # ILLEGAL: fix the measurement
TIER_LAST = "T2_RERUN_LAST"       # UNDER-SPECIFIED (older manifest spelling)
TIER_KEEP = "T0_KEEP"            # FINE: leave the existing measurement alone
TIER_HELD = "T2_RERUN_HELD"       # UNDER-SPECIFIED: a question, not a default
#: Under-specified under either manifest spelling.
UNDERSPECIFIED_TIERS = (TIER_HELD, TIER_LAST)
#: Classes never staged by default and which never block a run.
UNRUNNABLE_TIERS = (TIER_HELD, TIER_DROP)


def load_rerun_manifest(base_dir: Path) -> dict[str, Any] | None:
    """Load the audited re-run triage, or None when absent/unreadable."""
    try:
        with open(Path(base_dir) / RERUN_MANIFEST_PATH) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or "tiers" not in doc:
        return None
    return doc


def tier_for(phase: dict[str, Any],
             manifest: dict[str, Any] | None) -> str:
    """Triaged tier of one phase: by phase_key, falling back to phase_id."""
    if not manifest:
        return TIER_KEEP
    by_key: dict[str, str] = manifest.get("tiers_by_key") or {}
    tiers: dict[str, str] = manifest.get("tiers") or {}
    return by_key.get(phase_key(phase)) or tiers.get(phase.get("phase_id"), TIER_KEEP)


def apply_rerun_tiers(phases: list[dict[str, Any]],
                      manifest: dict[str, Any] | None,
                      release_held: bool = False,
                      release_drop: bool = False) -> list[dict[str, Any]]:
    """Order a deck by the audited triage.

    T3 phases are dropped outright (the user wants them left failed rather than
    retried forever). T1 is hoisted to the front and T2 pushed to the very back,
    so the fragile re-measurements only run once everything else is settled and
    a failure there cannot mask a real regression in T1.

    TIER_HELD phases are pinned: with release_held=False (the default) they are
    neither staged nor ordered — they are skipped exactly like T3, because the
    whole point of the pin is to stop a ~1-day re-measurement that fixes nothing.
    release_held=True is the explicit opt-in that finally stages them, at the
    very back of the deck.

    TIER_DROP (unreproducible) phases used to be removed unconditionally, on the
    reasoning that re-running only reproduces the failure. That is a judgement
    about *this* Tensile build, not a property of the cell, so it is now a
    question like the other two: release_drop=True stages them at the very back
    (after the held tier), release_drop=False keeps the historical drop.

    Lookup is by phase_key (hash of the shipped solution name) first and by
    phase_id only as a fallback: a triaged resume rebuilds the deck, and the
    rebuilt phase_ids differ from the audited ones precisely because the config
    fixes landed.
    """
    if not manifest:
        return phases
    kept: list[dict[str, Any]] = []
    first: list[dict[str, Any]] = []
    last: list[dict[str, Any]] = []
    for ph in phases:
        tier = tier_for(ph, manifest)
        if tier == TIER_DROP and not release_drop:
            continue
        if tier in (TIER_HELD, TIER_DROP):
            if tier == TIER_DROP:
                if release_drop:
                    last.append(ph)
            elif release_held:
                last.append(ph)
            continue
        if tier == TIER_FIRST:
            first.append(ph)
        elif tier == TIER_LAST:
            last.append(ph)
        else:
            kept.append(ph)
    return first + kept + last


def reference_chain(registry, exclude: str | None = None,
                    arch: str = "gfx900") -> list[str]:
    """
    Newest-first list of completed, non-smoke `arch`_ref_* runs forming ONE
    logical reference floor (a --resume run links to its base via
    metadata.resume_of, so the whole chain is recalled together).
    Only the newest chain head is returned; ancestors are walked back through
    resume_of pointers. Runs that are smokes, truncated ('interrupted') or the
    excluded id never appear. Determined per-phase coverage = union over the
    chain, which is what A/B recall and --auto's completeness gate use.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(registry.db_path, timeout=30.0)
        try:
            esc = (arch.replace("\\", "\\\\")
                   .replace("%", "\\%").replace("_", "\\_"))
            rows = conn.execute(
                "SELECT run_id, status, metadata FROM runs "
                "WHERE run_id LIKE ? ESCAPE '\\' ORDER BY id DESC",
                (esc + r"\_ref\_%",)
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for run_id, status, metadata in rows:
        meta: dict[str, Any] = {}
        if metadata:
            try:
                meta = json.loads(metadata)
            except Exception:
                meta = {}
        by_id[str(run_id)] = (str(status), meta)
    for run_id, (status, meta) in by_id.items():
        if run_id == exclude or status != "completed" or meta.get("smoke"):
            continue
        chain: list[str] = []
        cur: str | None = run_id
        while cur in by_id and cur not in chain:
            _cur_status, cur_meta = by_id[cur]
            chain.append(cur)
            nxt = cur_meta.get("resume_of")
            if not nxt:
                break
            cur = str(nxt)
        if chain:
            return chain
    return []
