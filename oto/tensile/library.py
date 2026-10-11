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
(oto.tensile.shipped_library).
Public API: see ``__all__``.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from oto.device.peaks import FAMILY_DTYPES, FAMILY_DTYPE_CHAR

#: Where the pinned shipped manifest is cached, relative to the project root.
MANIFEST_PATH = "gfx90c_results/gfx900_shipped_manifest.json"

# The shipped-library parse and the spoof-phase emitter live in their own module
# so the manifest cache, the tier triage and the identity helpers here are not
# buried under a binary .dat parser.
from oto.tensile.shipped_library import (  # noqa: E402
    _all_rocm_prefixes, _CANON, _MT, _resolve_rocm, CONTRACTION_PATTERNS,
    SHIPPED_FAMILIES, emit_spoof_phases, find_gfx900_dat_files,
    parse_shipped_kernels, shipped_kernel_config, shipped_kernel_knobs)

__all__ = [
    "CONTRACTION_PATTERNS", "MANIFEST_PATH", "SHIPPED_FAMILIES", "emit_spoof_phases",
    "find_gfx900_dat_files", "parse_shipped_kernels", "shipped_kernel_config",
    "shipped_kernel_knobs", "load_shipped_manifest", "latest_reference_run_id",
    "phase_key", "config_fingerprint", "load_rerun_manifest", "tier_for",
    "apply_rerun_tiers", "reference_chain", "TIER_KEEP", "TIER_FIRST",
    "TIER_HELD", "TIER_LAST", "TIER_DROP",
]


def _scan_dat_library() -> Dict[str, Any]:
    """Scan every installed gfx900 TensileLibrary into a manifest dict.

    Kernels are unioned per (family, pattern) across all installed ROCm
    prefixes so a family present in only one dist is still fully covered; the
    per-file provenance (prefix, path, mtime) is preserved.
    """
    active_rocm = _resolve_rocm()
    prefixes = _all_rocm_prefixes()
    scanned: List[Dict[str, Any]] = []
    fam_patterns: Dict[str, Dict[str, Set[str]]] = {}
    total_kernels = 0

    for prefix in prefixes:
        for df in find_gfx900_dat_files(prefix):
            parts = df.name.split("_")
            # TensileLibrary_Type_<TYPE>_Contraction_l_<pattern>_Cijk_Dijk_<isa>.dat
            # TYPE (e.g. HH_HPA) and pattern (Ailk_Bljk) are multi-token, so the
            # words between Type..Contraction and l..Cijk are underscore-joined.
            try:
                type_idx = parts.index("Type")
                end_t = parts.index("Contraction")
                type_token = "_".join(parts[type_idx + 1:end_t])
                l_idx = parts.index("l")
                end_p = parts.index("Cijk")
                pattern = "_".join(parts[l_idx + 1:end_p])
            except (ValueError, IndexError):
                continue
            if type_token not in SHIPPED_FAMILIES:
                continue
            if pattern not in CONTRACTION_PATTERNS:
                continue

            kernels = parse_shipped_kernels(df)
            total_kernels += len(kernels)
            scanned.append({
                "family": type_token,
                "pattern": pattern,
                "rocm_prefix": prefix,
                "path": str(df),
                "mtime": df.stat().st_mtime,
                "size": df.stat().st_size,
                "kernels": sorted(kernels),
            })

            fam = fam_patterns.setdefault(type_token, {})
            fam.setdefault(pattern, set()).update(kernels)

    families: Dict[str, Dict[str, Any]] = {}
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

    expected_kernels = {
        fam: sum(fam_info.get(p).get("count", 0) for p in CONTRACTION_PATTERNS)
        for fam, fam_info in families.items()
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "rocm_path": active_rocm,
        "rocm_prefixes": prefixes,
        "dat_files": scanned,
        "families": families,
        "expected_kernels": expected_kernels,
        "total_shipped_kernels": sum(expected_kernels.values()),
    }


def load_shipped_manifest(base_dir: Path, refresh: bool = False) -> Dict[str, Any]:
    """Return the pinned gfx900 shipped-library manifest (compute-once, pin).

    First load scans the system dat and writes the cache; later loads reuse it
    until refresh=True (--gfx900-reference --refresh). Never touches the live
    dat on report-only paths once pinned.
    """
    manifest_path = Path(base_dir) / MANIFEST_PATH
    if not refresh and manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            pass

    manifest = _scan_dat_library()
    manifest["cache_path"] = str(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def latest_reference_run_id(registry) -> Optional[str]:
    """Return the most recently *completed* gfx900 reference run id, if any."""
    import sqlite3
    try:
        conn = sqlite3.connect(registry.db_path, timeout=30.0)
        try:
            rows = conn.execute(
                "SELECT run_id, status FROM runs WHERE run_id LIKE 'gfx900_ref_%' "
                "ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()
        for run_id, status in rows:
            if status == "completed":
                return run_id
    except Exception:
        return None
    return None


def phase_key(phase: Dict[str, Any]) -> str:
    """Stable identity for a phase, independent of parsed knob values.

    `phase_id` embeds the knobs that `_parse_kernel_knobs` derived, so any fix to
    those parsers renames every phase. Completion was then re-decided from
    scratch: 1073 of 1212 ids changed between two consecutive runs and only 116
    matched, i.e. one resume silently re-ran the whole floor.

    The shipped solution name is the authoritative kernel identity and does not
    depend on our parsing, so hash that instead.
    """
    name = str(phase.get("kernel") or "")
    if not name:
        return "pid_" + hashlib.sha1(str(phase.get("phase_id", "")).encode()).hexdigest()[:12]
    return "k_" + hashlib.sha1(name.encode()).hexdigest()[:12]


def config_fingerprint(phase: Dict[str, Any]) -> str:
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


RERUN_MANIFEST_PATH = "gfx90c_results/reference_rerun_manifest.json"

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


def load_rerun_manifest(base_dir: Path) -> Optional[Dict[str, Any]]:
    """Load the audited re-run triage, or None when absent/unreadable."""
    try:
        with open(Path(base_dir) / RERUN_MANIFEST_PATH) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or "tiers" not in doc:
        return None
    return doc


def tier_for(phase: Dict[str, Any],
             manifest: Optional[Dict[str, Any]]) -> str:
    """Triaged tier of one phase: by phase_key, falling back to phase_id."""
    if not manifest:
        return TIER_KEEP
    by_key: Dict[str, str] = manifest.get("tiers_by_key") or {}
    tiers: Dict[str, str] = manifest.get("tiers") or {}
    return by_key.get(phase_key(phase)) or tiers.get(phase.get("phase_id"), TIER_KEEP)


def apply_rerun_tiers(phases: List[Dict[str, Any]],
                      manifest: Optional[Dict[str, Any]],
                      release_held: bool = False,
                      release_drop: bool = False) -> List[Dict[str, Any]]:
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
    kept: List[Dict[str, Any]] = []
    first: List[Dict[str, Any]] = []
    last: List[Dict[str, Any]] = []
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


def reference_chain(registry, exclude: Optional[str] = None) -> List[str]:
    """
    Newest-first list of completed, non-smoke gfx900_ref_* runs forming ONE
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
            rows = conn.execute(
                "SELECT run_id, status, metadata FROM runs "
                "WHERE run_id LIKE 'gfx900_ref_%' ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    by_id: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for run_id, status, metadata in rows:
        meta: Dict[str, Any] = {}
        if metadata:
            try:
                meta = json.loads(metadata)
            except Exception:
                meta = {}
        by_id[str(run_id)] = (str(status), meta)
    for run_id, (status, meta) in by_id.items():
        if run_id == exclude or status != "completed" or meta.get("smoke"):
            continue
        chain: List[str] = []
        cur: Optional[str] = run_id
        while cur in by_id and cur not in chain:
            cur_status, cur_meta = by_id[cur]
            chain.append(cur)
            nxt = cur_meta.get("resume_of")
            if not nxt:
                break
            cur = str(nxt)
        if chain:
            return chain
    return []