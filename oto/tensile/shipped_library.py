#!/usr/bin/env python3
"""The shipped gfx900 library: locating it, parsing it, rebuiling a kernel from its name.

Owns: the dat-file discovery under the system ROCm install, the binary `.dat`
parse into shipped kernel solution names, the derived per-family expected-kernel
counts (the acceptance coverage contract), ``shipped_kernel_config`` /
``shipped_kernel_knobs`` (the knob vocabulary rebuilt from a solution name) and
``emit_spoof_phases`` (one reference phase per shipped kernel).

The floor is sourced from the *installed* library, never from hand-authored
baselines: a floor that is not what shipped is not a floor.

Does NOT own: the manifest cache and its refresh policy
(oto.tensile.library), the rerun triage and tier ordering
(oto.tensile.library), or the fingerprint/phase-key identity (also
oto.tensile.library).
Public API: shipped_kernel_config, shipped_kernel_knobs,
emit_spoof_phases, SHIPPED_FAMILIES, CONTRACTION_PATTERNS, find_gfx900_dat_files,
parse_shipped_kernels.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from oto.device import loader as _loader

#: Dat TYPE token (from the shipped filename `TensileLibrary_Type_<TYPE>_...`)
#: maps 1:1 to our family keys for the 7 analysed families.
SHIPPED_FAMILIES = list(_loader.current_profile().family_dtypes.keys())

CONTRACTION_PATTERNS = ["Ailk_Bjlk", "Ailk_Bljk", "Alik_Bjlk", "Alik_Bljk"]


def _resolve_rocm() -> str:
    """Resolve the ROCm prefix for the rocBLAS ``.dat`` search (env first).

    The GPU compile machinery is ROCM_PATH-mandatory (oto.runners.toolchain);
    this helper is only about locating pre-shipped library artifacts, so the
    hipconfig/PATH probe stays as a best-effort fallback for distros that
    install rocBLAS outside ROCM_PATH.
    """
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


def _library_dirs(rocm: str) -> list[Path]:
    """Candidate dirs holding rocBLAS TensileLibrary artifacts."""
    cands = [
        Path(rocm) / "lib" / "rocblas" / "library",
        Path(rocm) / "lib64" / "rocblas" / "library",
        Path(rocm) / "rocblas" / "library",
        Path(rocm) / "lib" / "hipblas" / "library",
    ]
    return [c for c in cands if c.is_dir()]


def _all_rocm_prefixes() -> list[str]:
    """Every installed ROCm prefix that carries a rocBLAS library.

    The primary is whatever the active toolchain resolves (hipconfig/ROCM_PATH);
    secondary installs (/opt/rocm, /opt/rocm-*) are unioned so a family missing
    from one dist (e.g. HPA types folded into HH in newer ROCm) is still sourced
    from the shipped gfx900 library that does ship it. Per-file provenance is
    recorded in the manifest.
    """
    primary = _resolve_rocm()
    prefixes = {p for p in [primary] if p}
    for extra_cand in ["/opt/rocm", *sorted(__import__("glob").glob("/opt/rocm-*"))]:
        if Path(extra_cand).is_dir():
            prefixes.add(extra_cand)
    return sorted(prefixes, key=lambda p: (p == primary, p), reverse=True)


def find_gfx900_dat_files(rocm: str | None = None,
                          arch: str = "gfx900") -> list[Path]:
    """Return every `TensileLibrary_Type_<T>_Contraction_l_*_Cijk_Dijk_<arch>.dat`.

    Skips the lazy TOC (`TensileLibrary_lazy_<arch>.dat`) and non-matching
    artifacts. `.hyp` payloads are matched too (their filenames mirror the
    distributed dat names). ``arch`` defaults to the gfx900 reference the
    project ships; a profile with a different ``spoof_reference`` names its
    own architecture here.
    """
    found: list[Path] = []
    for d in _library_dirs(rocm or _resolve_rocm()):
        found.extend(p for p in sorted(d.rglob(f"TensileLibrary_Type_*_{arch}.dat"))
                     if "_lazy_" not in p.name)
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
# Beta-on-edge element multiple. Not part of any phase config (omitting it lets
# Tensile default it to 1, which its own half/GSU rejects then reject), so the
# legality prior has to read it to inherit a shipped kernel's real setting.
_AF0EM = re.compile(r"(?:^|_)AF0EM(\d+)(?:_|$)")


def parse_shipped_kernels(dat_file: Path) -> set[str]:
    """Extract canonical (deduplicated) solution names from a binary .dat.

    The .dat is a length-prefixed binary blob containing the plain-text kernel
    solution names as substrings. Names carry a one-letter marker prefix
    ('c'/'a'/...) that is stripped so 'cCijk_...' == 'aCijk_...' == 'Cijk_...'.
    """
    try:
        data = dat_file.read_bytes().decode("latin-1", errors="replace")
    except OSError:
        return set()

    kernels: set[str] = set()
    for m in re.finditer(r"(?<![A-Za-z0-9_])[A-Za-z]Cijk[A-Za-z0-9_]+", data):
        tok = m.group(0)
        if "_MT" not in tok or "Dijk" in tok:
            continue
        if not _SOLUTION_NAME.match(tok):
            continue
        # Strip the one-letter marker so 'cCijk_..' == 'aCijk_..' == 'Cijk_..'.
        kernels.add(_CANON.sub("Cijk", tok))
    return kernels


def _parse_kernel_knobs(name: str) -> dict[str, Any]:
    """Parse structural Tensile knobs out of a canonical solution name.

    Sets the knobs `write_phase_config` understands so the spoofed phase
    rebuilds the shipped kernel rather than a generic default. Knobs Tensile
    does not name (NLCA, LDS padding, SWV...) fall back to their defaults —
    the reproduction is structural, faithful in MT/TT/WG/VW/DepthU/GSU.
    """
    knobs: dict[str, Any] = {}
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
    a = _AF0EM.search(name)
    if a:
        knobs["af0em"] = int(a.group(1))
    return knobs


def shipped_kernel_knobs(name: str) -> dict[str, Any]:
    """Public canonical read: structural knobs of one shipped solution name.

    Thin public wrapper over the single `_parse_kernel_knobs` owner, so callers
    (legality prior) never grow a second solution-name parser.
    """
    return _parse_kernel_knobs(name)


def shipped_kernel_config(name: str, family: str,
                          arch: str = "gfx900") -> dict[str, Any]:
    """Public canonical read: phase `config` for one shipped kernel of `family`.

    Resolves `family` to its Tensile DataType char via the shared
    _loader.current_profile().family_dtype_char map rather than each caller re-deriving it. ``arch``
    sets the config's Architecture (the reference floor's ISA).
    """
    return _config_from_kernel(name, _loader.current_profile().family_dtype_char[family], arch)


def _reconcile_knobs(k: dict[str, Any]) -> None:
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


def _config_from_kernel(name: str, dtype: str,
                        arch: str = "gfx900") -> dict[str, Any]:
    """Build the phase `config` dict (Architecture + kernel knobs) for a kernel."""
    k = _parse_kernel_knobs(name)
    _reconcile_knobs(k)
    config: dict[str, Any] = {
        "Architecture": arch,
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


def _short_tag(name: str, k: dict[str, Any]) -> str:
    import hashlib
    return "mt{}-tt{}-vw{}-du{}-gsu{}-{}".format(
        k.get("m0", 0),
        k.get("t0", 0),
        k.get("vw", 0),
        k.get("dup", 0),
        k.get("gsu", 0),
        hashlib.sha1(name.encode()).hexdigest()[:8],
    )


def emit_spoof_phases(manifest: dict[str, Any],
                      arch: str = "gfx900",
                      schedule: str = "vega10") -> list[dict[str, Any]]:
    """Build the one-time spoof reference phase list from the manifest.

    One phase per shipped kernel, per family/pattern, benchmarked at the
    family's canonical deck shapes with ScheduleName=``schedule`` (8 seeds).
    Every phase carries a distinct fp (kernel-derived config) so no phase
    collides with candidates or with any other shipped kernel. ``arch`` is
    the reference architecture (the profile's ``spoof_reference``); for
    this device that is gfx900.
    """
    phases: list[dict[str, Any]] = []
    by_family = manifest.get("families", {})
    for fam in SHIPPED_FAMILIES:
        fam_info = by_family.get(fam)
        if not fam_info:
            continue
        dtype_char = _loader.current_profile().family_dtype_char[fam]
        shapes = [f"{s}x{s}x{s}" for s in _loader.current_profile().family_shapes.get(fam, [])]
        for pattern in CONTRACTION_PATTERNS:
            fam_pattern = f"{fam}_{pattern}"
            entry = fam_info.get(pattern) or fam_info.get(fam_pattern)
            kernels = (entry or {}).get("kernels", [])
            for name in kernels:
                k = _parse_kernel_knobs(name)
                _reconcile_knobs(k)
                config = _config_from_kernel(name, dtype_char, arch)
                tag = _short_tag(name, k)
                phase_id = f"phase_{fam.lower()}_{arch}_{pattern}_{tag}"
                label = f"{arch}_{fam}_{pattern}_{tag}"
                phases.append({
                    "phase_id": phase_id,
                    "label": label,
                    "dtype": dtype_char.lower(),
                    "shapes": shapes,
                    "ScheduleName": schedule,
                    "NumBenchmarks": 8,
                    "config": config,
                    "kernel": name,  # provenance: shipped solution name
                    f"{arch}_reference_source": "+".join(manifest.get("rocm_prefixes", []) or []),
                })
    return phases
