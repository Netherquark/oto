#!/usr/bin/env python3
"""Coverage-grid vocabulary: cell identity and kernel-name parsing.

Owns: the typecode->family resolver (kernel-name parsing), and the canonical
cell identity helpers (``cell_key``, ``kernel_key``, ``cube_side``,
``shipped_cells``, ``shipped_cell_set``) used by every consumer that pairs a
native candidate with its reference-floor kernel. Profile-aware: the dtype-
char tables come from :func:`oto.device.loader.current_profile` at call
time, never from module globals.
Does NOT own: any calibrated constant (see ```oto.tensile.gates```), the
profile dataclass (```oto.device.profile```), or loader/detection.
Public API: blas8_gflops, dtype_to_family, kernel_typecode,
family_from_kernel_name, dtype_from_kernel_name, cube_side, cell_key,
shipped_cells, shipped_cell_set, kernel_key.
"""

from __future__ import annotations

import re

from oto.device.loader import resolve_profile


def blas8_gflops(family: str, reported: float, profile=None) -> float:
    """A client-reported GFLOPS figure in BLAS-8 units (complex x4).

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    return reported * resolve_profile(profile).reported_to_blas8.get(family.upper(), 1.0,)


def dtype_to_family(profile=None) -> dict[str, str]:
    """DataType char -> canonical family (first-wins).

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    out: dict[str, str] = {}
    for fam, ch in resolve_profile(profile).family_dtype_char.items():
        out.setdefault(ch, fam)
    return out


_KERNEL_LAYOUT_TOKENS = frozenset({
    "SN", "SE", "NN", "NT", "TN", "TT", "TC", "NC",
    "BH", "HN", "HT", "GB", "NB",
})

_TYPECODE_TO_FAMILY = {"S": "SS", "D": "DD", "H": "HH", "C": "CC", "Z": "ZZ"}


def kernel_typecode(kernel_name: object) -> str:
    """Raw dtype token of a Tensile kernel name ('' when unparseable)."""
    name = str(kernel_name or "").split("_MT")[0]
    if not name:
        return ""
    for tok in reversed(name.split("_")):
        if not tok:
            continue
        u = tok.upper()
        if u in _KERNEL_LAYOUT_TOKENS:
            continue
        if u[:1] in _TYPECODE_TO_FAMILY:
            return u
        return ""
    return ""


def family_from_kernel_name(kernel_name: object) -> str:
    """Canonical family of a kernel by its typecode ('' when unparseable)."""
    code = kernel_typecode(kernel_name)
    if not code:
        return ""
    return _TYPECODE_TO_FAMILY.get(code[0], "")


def dtype_from_kernel_name(kernel_name: object, profile=None) -> str:
    """Canonical DataType char of a kernel by its typecode ('' when unknown).

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    return resolve_profile(profile).family_dtype_char.get(family_from_kernel_name(kernel_name), "",)


def cube_side(shape: object) -> int | None:
    """Side length N of an 'NxNxN' cube shape string; None for non-cubes."""
    m = re.match(r"\s*(\d+)x(\d+)x(\d+)", str(shape))
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return a if a == b == c else None


def cell_key(family: object, shape: object) -> str | None:
    """Canonical workload-cell key 'FAMILY:SIDE'; None if unreadable."""
    side = cube_side(shape)
    if not side:
        return None
    fam = str(family or "").upper()
    if not fam or fam == "NONE":
        return None
    return f"{fam}:{side}"


def shipped_cells(profile=None) -> dict[str, dict[str, str]]:
    """The device "shape x dtype" coverage grid (the coverage-parity rule).

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    fds = resolve_profile(profile).family_dtype_char
    shapes = resolve_profile(profile).family_shapes
    return {
        f"{fam}:{side}": {
            "family": fam,
            "shape": f"{side}x{side}x{side}",
            "side": str(side),
            "dtype": fds[fam],
        }
        for fam in shapes
        for side in shapes[fam]
    }


def shipped_cell_set() -> set[tuple[str, str]]:
    """The coverage-parity grid as a set of ``(family, "NxNxN")`` tuples."""
    return {(v["family"], v["shape"]) for v in shipped_cells().values()}


def kernel_key(cfg: object) -> str:
    """Canonical kernel-identity key (config knobs) for drill-down citation."""
    if not isinstance(cfg, dict):
        return ""
    parts = []
    parts.extend(f"{k}={cfg[k]}"
                 for k in ("contraction_pattern", "ContractionPattern", "DataType")
                 if cfg.get(k))
    parts.extend(f"{k}={cfg[k]}"
                 for k in ("MacroTile", "MT0", "MT1", "ThreadTile", "TT0", "TT1",
                           "VectorWidth", "DepthU", "GlobalSplitU",
                           "WorkGroupMapping")
                 if cfg.get(k) is not None)
    return "|".join(parts)
