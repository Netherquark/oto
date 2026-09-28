#!/usr/bin/env python3
"""
tensile_library.py — System ROCm gfx900 TensileLibrary source of truth

The gfx900 spoof floor is sourced from the *installed* ROCm TensileLibrary
(not from hand-authored YAML baselines). This module:

1. Locates the distributed gfx900 library under the system ROCm install
   (`$ROCM_PATH/lib/rocblas/library/TensileLibrary_Type_*_gfx900.dat` and the
   `TensileLibrary_lazy_gfx900.dat` table-of-contents, with `.hyp` also probed).
2. Parses each per-type binary `.dat` into the set of shipped kernel solution
   names (marker-prefix normalised, deduplicated) per (family, pattern).
3. Derives the per-family *expected kernel* counts (the "900+ cell list")
   that back the acceptance coverage contract — replacing the hardcoded
   3,066-kernel table in report.py.
4. Emits the one-time spoof reference phase configs: every shipped kernel,
   rebuilt structurally from its solution name (MT/TT/WG/VW/DepthU/GSU) with
   ScheduleName=vega10, benchmarked once on gfx90c, then reused as the A/B
   floor for all future runs.

Manifest is pinned after first load: computed from the live dat once, cached
to `gfx90c_results/gfx900_shipped_manifest.json`, and regenerated only with
refresh=True (--gfx900-reference --refresh).
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

from gfx90c_common import FAMILY_DTYPES, FAMILY_SHAPES, FAMILY_DTYPE_CHAR

# Dat TYPE token (from the shipped filename `TensileLibrary_Type_<TYPE>_...`)
# maps 1:1 to our family keys for the 7 analysed families.
SHIPPED_FAMILIES = list(FAMILY_DTYPES.keys())

CONTRACTION_PATTERNS = ["Ailk_Bjlk", "Ailk_Bljk", "Alik_Bjlk", "Alik_Bljk"]

MANIFEST_PATH = "gfx90c_results/gfx900_shipped_manifest.json"


def _resolve_rocm() -> str:
    """Resolve the active ROCm prefix (env -> hipconfig -> /opt/rocm)."""
    prefix = os.environ.get("ROCM_PATH", "").strip()
    if prefix and Path(prefix).is_dir():
        return prefix
    hipconfig = shutil.which("hipconfig")
    if hipconfig:
        try:
            out = subprocess.run([hipconfig], capture_output=True, text=True, timeout=30).stdout or ""
            for line in out.splitlines():
                m = re.match(r"ROCM_PATH\s*:\s*(.*)", line.strip())
                if m and m.group(1).strip() and Path(m.group(1).strip()).is_dir():
                    return m.group(1).strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if Path("/opt/rocm").is_dir():
        return "/opt/rocm"
    return ""


def _library_dirs(rocm: str) -> List[Path]:
    """Candidate dirs holding rocBLAS TensileLibrary artifacts."""
    cands = [
        Path(rocm) / "lib" / "rocblas" / "library",
        Path(rocm) / "lib64" / "rocblas" / "library",
        Path(rocm) / "rocblas" / "library",
        Path(rocm) / "lib" / "hipblas" / "library",
    ]
    return [c for c in cands if c.is_dir()]


def _all_rocm_prefixes() -> List[str]:
    """Every installed ROCm prefix that carries a rocBLAS library.

    The primary is whatever the active toolchain resolves (hipconfig/ROCM_PATH);
    secondary installs (/opt/rocm, /opt/rocm-*) are unioned so a family missing
    from one dist (e.g. HPA types folded into HH in newer ROCm) is still sourced
    from the shipped gfx900 library that does ship it. Per-file provenance is
    recorded in the manifest.
    """
    primary = _resolve_rocm()
    prefixes = {p for p in [primary] if p}
    for extra_cand in ["/opt/rocm"] + sorted(__import__("glob").glob("/opt/rocm-*")):
        if Path(extra_cand).is_dir():
            prefixes.add(extra_cand)
    return sorted(prefixes, key=lambda p: (p == primary, p), reverse=True)


def find_gfx900_dat_files(rocm: Optional[str] = None) -> List[Path]:
    """Return every `TensileLibrary_Type_<T>_Contraction_l_*_Cijk_Dijk_gfx900.dat`.

    Skips the lazy TOC (`TensileLibrary_lazy_gfx900.dat`) and non-gfx900
    artifacts. `.hyp` payloads are matched too (their filenames mirror the
    distributed dat names).
    """
    found: List[Path] = []
    for d in _library_dirs(rocm or _resolve_rocm()):
        for p in sorted(d.rglob("TensileLibrary_Type_*_gfx900.dat")):
            if "_lazy_" not in p.name:
                found.append(p)
    return found


_SOLUTION_NAME = re.compile(r"^[A-Za-z]Cijk(_[A-Za-z0-9_]+)+$")
_CANON = re.compile(r"^[A-Za-z]Cijk")
_MT = re.compile(r"MT(\d+)x(\d+)x(\d+)")
# Shipped names use `TT4_2` (underscore), not `TT4x2`; the old r"TT(\d+)x(\d+)"
# matched nothing in 1212/1212 phases, so ThreadTile was always derived, never read.
_TT = re.compile(r"(?:^|_)TT(\d+)[x_](\d+)(?:_|$)")
_WG = re.compile(r"WG(\d+)_(\d+)_(\d+)")
# `VW(\d+)` is ambiguous: GLVWA/GLVWB/GRVW/LRVW/SVW/VWB all contain "VW", and
# GRVW appears before the real _VW_ token, so it silently yielded the reduce
# width. Anchor to a standalone token.
_VW = re.compile(r"(?:^|_)VW(\d+)(?:_|$)")
_GLVWA = re.compile(r"(?:^|_)GLVWA(\d+)(?:_|$)")
_GLVWB = re.compile(r"(?:^|_)GLVWB(\d+)(?:_|$)")
_GRVW = re.compile(r"(?:^|_)GRVW(\d+)(?:_|$)")
_GSU = re.compile(r"GSU(\d+)")


def parse_shipped_kernels(dat_file: Path) -> Set[str]:
    """Extract canonical (deduplicated) solution names from a binary .dat.

    The .dat is a length-prefixed binary blob containing the plain-text kernel
    solution names as substrings. Names carry a one-letter marker prefix
    ('c'/'a'/...) that is stripped so 'cCijk_...' == 'aCijk_...' == 'Cijk_...'.
    """
    try:
        data = dat_file.read_bytes().decode("latin-1", errors="replace")
    except OSError:
        return set()

    kernels: Set[str] = set()
    for m in re.finditer(r"(?<![A-Za-z0-9_])[A-Za-z]Cijk[A-Za-z0-9_]+", data):
        tok = m.group(0)
        if "_MT" not in tok or "Dijk" in tok:
            continue
        if not _SOLUTION_NAME.match(tok):
            continue
        # Strip the one-letter marker so 'cCijk_..' == 'aCijk_..' == 'Cijk_..'.
        kernels.add(_CANON.sub("Cijk", tok))
    return kernels


def _parse_kernel_knobs(name: str) -> Dict[str, Any]:
    """Parse structural Tensile knobs out of a canonical solution name.

    Sets the knobs `_write_phase_config` understands so the spoofed phase
    rebuilds the shipped kernel rather than a generic default. Knobs Tensile
    does not name (NLCA, LDS padding, SWV...) fall back to their defaults —
    the reproduction is structural, faithful in MT/TT/WG/VW/DepthU/GSU.
    """
    knobs: Dict[str, Any] = {}
    m = _MT.search(name)
    if m:
        knobs["m0"], knobs["m1"], knobs["dup"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
    t = _TT.search(name)
    if t:
        knobs["t0"], knobs["t1"] = int(t.group(1)), int(t.group(2))
    w = _WG.search(name)
    if w:
        knobs["wg"] = [int(w.group(1)), int(w.group(2)), int(w.group(3))]
    v = _VW.search(name)
    if v:
        knobs["vw"] = int(v.group(1))
    for key, rx in (("glvwa", _GLVWA), ("glvwb", _GLVWB), ("grvw", _GRVW)):
        m = rx.search(name)
        if m:
            knobs[key] = int(m.group(1))
    g = _GSU.search(name)
    if g:
        knobs["gsu"] = int(g.group(1))
    return knobs


def _reconcile_knobs(k: Dict[str, Any]) -> None:
    """Make ThreadTile/WorkGroup consistent with the named MacroTile.

    Tensile's SolutionStructs rejects a config unless, per M/N dimension,
    WorkGroup * ThreadTile == MacroTile (and the workgroup size is a multiple
    of WavefrontSize). Shipped names usually omit TT/WG, so their fallback
    defaults (TT 4x4, WG 16x16) break the product. Derive the missing knob
    from the shipped one; when neither is present default WG 16x16 and solve
    for TT.
    """
    if not (k.get("m0") and k.get("m1")):
        return
    mt = [k["m0"], k["m1"]]
    wg = k.get("wg", [None, None])[:2]
    tt = [k.get("t0"), k.get("t1")]

    for i in (0, 1):
        w, t = wg[i], tt[i]
        if w and t and w * t != mt[i]:
            t = None  # trust the named MacroTile
        if w and not t:
            t = mt[i] // w if mt[i] % w == 0 else None
        elif t and not w:
            w = mt[i] // t if mt[i] % t == 0 else None
        elif not w and not t:
            w = 16
            t = mt[i] // w if mt[i] % w == 0 else None
        wg[i], tt[i] = w, t

    if not (wg[0] and wg[1] and tt[0] and tt[1]):
        return  # not reconcilable, leave to Tensile defaults

    if (wg[0] * wg[1]) % 64:
        # not a wave64 multiple: scan smaller square workgroups
        for wg_ref in (8, 4, 2, 1):
            if mt[0] % wg_ref == 0 and mt[1] % wg_ref == 0 \
                    and (wg_ref * wg_ref) % 64 == 0:
                wg[0] = wg[1] = wg_ref
                tt[0], tt[1] = mt[0] // wg_ref, mt[1] // wg_ref
                break
    k["wg"] = [wg[0], wg[1], 1]
    k["t0"], k["t1"] = tt[0], tt[1]


def _config_from_kernel(name: str, dtype: str) -> Dict[str, Any]:
    """Build the phase `config` dict (Architecture + kernel knobs) for a kernel."""
    k = _parse_kernel_knobs(name)
    _reconcile_knobs(k)
    config: Dict[str, Any] = {
        "Architecture": "gfx900",
        "DataType": dtype,
        "ProblemType": "Contraction",
    }
    if k.get("m0") and k.get("m1"):
        config["MacroTile"] = f"{k['m0']}x{k['m1']}x{k.get('dup', 16)}"
    if k.get("t0") and k.get("t1"):
        config["ThreadTile"] = f"{k['t0']}x{k['t1']}"
    if k.get("wg"):
        config["WorkGroup"] = k["wg"]
    if k.get("vw"):
        config["VectorWidth"] = k["vw"]
    if k.get("dup"):
        config["DepthU"] = k["dup"]
    if k.get("gsu"):
        config["GlobalSplitU"] = k["gsu"]
    # Global load/reduce widths ship as explicit solution tokens. Omitting them
    # let Tensile default them, and the default then contradicts the named
    # VectorWidth (SolutionStructs.py:4588/4595 reject glvw != VW and != 1).
    if k.get("glvwa"):
        config["GlobalLoadVectorWidthA"] = k["glvwa"]
    if k.get("glvwb"):
        config["GlobalLoadVectorWidthB"] = k["glvwb"]
    # `grvw` is deliberately dropped. It is not a Tensile parameter (absent
    # from SolutionStructs.validParameters), and BenchmarkStructs calls
    # printExit() on unrecognised names, so emitting it aborted every reference
    # phase at "Filling in Parameters With Defaults" with zero phases executed.
    return config


def _short_tag(name: str, k: Dict[str, Any]) -> str:
    import hashlib
    tail = "mt{}-tt{}-vw{}-du{}-gsu{}-{}".format(
        k.get("m0", 0),
        k.get("t0", 0),
        k.get("vw", 0),
        k.get("dup", 0),
        k.get("gsu", 0),
        hashlib.sha1(name.encode()).hexdigest()[:8],
    )
    return tail


def emit_spoof_phases(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the one-time gfx900 spoof reference phase list from the manifest.

    One phase per shipped kernel, per family/pattern, benchmarked at the
    family's canonical deck shapes with ScheduleName=vega10 (8 seeds). Every
    phase carries a distinct fp (kernel-derived config) so no phase collides
    with candidates or with any other shipped kernel.
    """
    phases: List[Dict[str, Any]] = []
    by_family = manifest.get("families", {})
    for fam in SHIPPED_FAMILIES:
        fam_info = by_family.get(fam)
        if not fam_info:
            continue
        dtype_char = FAMILY_DTYPE_CHAR[fam]
        shapes = [f"{s}x{s}x{s}" for s in FAMILY_SHAPES.get(fam, [])]
        for pattern in CONTRACTION_PATTERNS:
            fam_pattern = f"{fam}_{pattern}"
            entry = fam_info.get(pattern) or fam_info.get(fam_pattern)
            kernels = (entry or {}).get("kernels", [])
            for name in kernels:
                k = _parse_kernel_knobs(name)
                _reconcile_knobs(k)
                config = _config_from_kernel(name, dtype_char)
                tag = _short_tag(name, k)
                phase_id = f"phase_{fam.lower()}_gfx900_{pattern}_{tag}"
                label = f"gfx900_{fam}_{pattern}_{tag}"
                phases.append({
                    "phase_id": phase_id,
                    "label": label,
                    "dtype": dtype_char.lower(),
                    "shapes": shapes,
                    "ScheduleName": "vega10",
                    "NumBenchmarks": 8,
                    "config": config,
                    "kernel": name,  # provenance: shipped solution name
                    "gfx900_reference_source": "+".join(manifest.get("rocm_prefixes", []) or []),
                })
    return phases


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
    from registry import fingerprint_config
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

# Tiers, in the order they must execute.
TIER_DROP = "T3_UNREPRODUCIBLE"   # never re-run: current Tensile cannot derive them
TIER_FIRST = "T1_RERUN"           # fixed synthesis bugs -> run first
TIER_LAST = "T2_RERUN_LAST"      # measured under under-specified glvw -> run last
TIER_KEEP = "T0_KEEP"            # leave the existing measurement alone
# Designed + fully audited, but deliberately PINNED OUT of every default run.
# These kernels are not wrong, they are merely under-specified (glvw/grvw were
# left to Tensile's defaults), so re-measuring 1881 of them costs ~1 day of GPU
# time for no correctness gain. The tier, the shipped-config rebuild, the
# fingerprint machinery and the ordering are all landed and tested; only the
# "actually stage them" decision is withheld. Release with
# --release-under-specified (or TIER_LAST in a hand-edited manifest).
# Tracked as PENDING in incomplete_work.md section 4.16.
TIER_HELD = "T2_RERUN_HELD"       # pinned: not staged, does not block, needs opt-in
#: Tiers that are not staged and never block, split by whether an opt-in releases them.
PINNED_TIERS = (TIER_HELD, TIER_DROP)


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
                      release_held: bool = False) -> List[Dict[str, Any]]:
    """Order a deck by the audited triage.

    T3 phases are dropped outright (the user wants them left failed rather than
    retried forever). T1 is hoisted to the front and T2 pushed to the very back,
    so the fragile re-measurements only run once everything else is settled and
    a failure there cannot mask a real regression in T1.

    TIER_HELD phases are pinned: with release_held=False (the default, and the
    only thing --auto does) they are neither staged nor ordered — they are
    skipped exactly like T3, because the whole point of the pin is to stop a
    ~1-day re-measurement that fixes nothing. release_held=True is the explicit
    opt-in that finally stages them, at the very back of the deck.

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
        if tier == TIER_DROP:
            continue
        if tier == TIER_HELD:
            if release_held:
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