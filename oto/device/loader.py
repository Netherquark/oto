"""Device profile loader — the frozen, in-memory view of one GPU.

Owns: reading ``profiles/<codename>.json`` into a frozen ``DeviceProfile``,
resolving the *process* profile (``current_profile``) and scoping swaps
(``rebind_profile`` / ``bound_profile``). The public API surface is one
function per job: load, resolve, rebind, bind.
Does NOT own: the dataclass layout (``oto.device.profile``), the JSON files
themselves, or device auto-detection (``oto.device.device_detect``).
Public API: load_profile, load_profile_from_starter, default_profile,
current_profile, resolve_profile, rebind_profile, bound_profile.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from oto.device.profile import (
    AssemblyGatePolicy,
    DeviceProfile,
    TheoreticalLimits,
)

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"


def _check_sanity(data: dict[str, Any], source: str) -> None:
    """Refuse obviously-unverified profiles (e.g. the starter template left
    unfilled). Fails loudly rather than tuning against invented numbers."""
    problems = []
    codename = str(data.get("codename", ""))
    if not codename or codename.startswith("<"):
        problems.append(f"placeholder codename {codename!r}")
    for key in ("num_cus", "max_clock_mhz", "lds_per_cu_kb", "vgpr_per_cu"):
        try:
            if int(data.get(key, 0)) <= 0:
                problems.append(f"{key} must be > 0")
        except (TypeError, ValueError):
            problems.append(f"{key} must be an integer")
    if not data.get("family_shapes"):
        problems.append("family_shapes is empty")
    if not data.get("peak_gflops"):
        problems.append("peak_gflops is empty")
    if problems:
        raise ValueError(f"Refusing to load unverified profile from {source}: "
                         + "; ".join(problems))


def _to_profile(data: dict[str, Any], source: str = "<profile>") -> DeviceProfile:
    _check_sanity(data, source)
    ag = data.get("assembly_gates", {})
    th = data.get("theoretical", {})
    return DeviceProfile(
        codename=data["codename"],
        isa=tuple(data["isa"]),
        num_cus=data["num_cus"],
        simds_per_cu=data["simds_per_cu"],
        lanes_per_simd=data["lanes_per_simd"],
        max_waves_per_cu=data["max_waves_per_cu"],
        max_clock_mhz=data["max_clock_mhz"],
        lds_per_cu_kb=data["lds_per_cu_kb"],
        l2_size_kb=data["l2_size_kb"],
        vgpr_per_cu=data["vgpr_per_cu"],
        has_mfma=data["has_mfma"],
        has_dp4a=data["has_dp4a"],
        has_packed_bf16=data["has_packed_bf16"],
        global_load_byte_cap=data["global_load_byte_cap"],
        peak_gflops=dict(data["peak_gflops"]),
        family_shapes={k: list(v) for k, v in data["family_shapes"].items()},
        realistic_ceilings=dict(data["realistic_ceilings"]),
        family_dtype_char=dict(data["family_dtype_char"]),
        family_dtypes=dict(data["family_dtypes"]),
        family_bytes_per_element=dict(data["family_bytes_per_element"]),
        assembly_gates=AssemblyGatePolicy(**ag) if ag else AssemblyGatePolicy(),
        theoretical=TheoreticalLimits(
            memory_type=th.get("memory_type", ""),
            bandwidth_gb_s=th.get("bandwidth_gb_s", 0.0),
            coherent_host_access=th.get("coherent_host_access", False),
            boundaries=th.get("boundaries", {}),
            memory_channels=int(th.get("memory_channels", 0) or 0),
            memory_rate_mtps=int(th.get("memory_rate_mtps", 0) or 0),
        ),
        measured_vgpr=data.get("measured_vgpr", {}),
        spoof_reference=data.get("spoof_reference", ""),
        reported_to_blas8=dict(data.get("reported_to_blas8", {})),
        theoretical_peaks_blas8=dict(data.get("theoretical_peaks_blas8", {})),
        realistic_ceilings_blas8=dict(data.get("realistic_ceilings_blas8", {})),
        family_cells={k: list(v) for k, v in data.get("family_cells", {}).items()},
        theoretical_peaks=dict(data.get("theoretical_peaks", {})),
        realistic_ceilings_reported=dict(data.get("realistic_ceilings_reported", {})),
    )


def load_profile(codename: str, profiles_dir: Path | None = None) -> DeviceProfile:
    d = profiles_dir or _PROFILES_DIR
    path = Path(d) / f"{codename}.json"
    if not path.exists():
        raise FileNotFoundError(f"No profile for {codename}: {path}")
    return _to_profile(json.loads(path.read_text()), str(path))


def _codename_from_text(text: str) -> str | None:
    import re
    m = re.search(r"codename:\s*(\S+)", text)
    return m.group(1).strip() if m else None


def load_profile_from_starter(starter_path: Path, profiles_dir: Path | None = None) -> DeviceProfile:
    """Load a device profile from a starter file.

    Precedence:
      1. a fenced ```json block inside the starter;
      2. the Markdown+JSON pair: a ``<stem>.json`` sitting next to ``<stem>.md``
         (the narrative carries ``codename:``; the JSON carries the facts;
         the two codenames must agree);
      3. a bare ``codename:`` line, resolving ``profiles/<codename>.json``.
    """
    text = Path(starter_path).read_text()
    # Try to find a fenced json/yaml block
    import re
    m = re.search(r"```(?:json|yaml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if "codename" in data:
                return _to_profile(data, str(starter_path))
        except json.JSONDecodeError:
            pass
    # Markdown+JSON pair: <starter stem>.json next to the starter
    pair_json = Path(starter_path).with_suffix(".json")
    if pair_json.exists():
        data = json.loads(pair_json.read_text())
        if "codename" not in data:
            raise ValueError(f"Starter pair {pair_json} has no codename: {pair_json}")
        narrative_codename = _codename_from_text(text)
        if narrative_codename and narrative_codename != data["codename"]:
            raise ValueError(
                f"Starter pair mismatch: {starter_path} says codename "
                f"{narrative_codename}, {pair_json} says {data['codename']}")
        return _to_profile(data, str(pair_json))
    # Fall back: treat starter's codename as a profile name
    codename = _codename_from_text(text)
    if codename:
        return load_profile(codename, profiles_dir)
    raise ValueError(f"Cannot derive profile from starter: {starter_path}")


def default_profile():
    """The default profile used as the default when no device is specified."""
    return load_profile("gfx90c")


# ---------------------------------------------------------------------------
# Canonical accessor (C2.5-C2.9): the profile THIS process runs as.
# Resolution order:
#   1. OTO_PROFILE env var -- a codename (resolved from profiles/) or a path
#      to a profile JSON (explicit wins, loudly errors)
#   2. auto-detected codename (rocminfo) when a profile exists for it
#   3. the committed default (gfx90c) -- the project's shipping device
# Cached for the life of the process. Use bound_profile() to scope a change
# (tests, the driver's profile override); rebind_profile() to set it outright.
# ---------------------------------------------------------------------------
OTO_PROFILE_VAR = "OTO_PROFILE"
DEFAULT_CODENAME = "gfx90c"

_CURRENT_PROFILE: DeviceProfile | None = None


def current_profile() -> DeviceProfile:
    """The DeviceProfile this process runs as (cached)."""
    global _CURRENT_PROFILE
    if _CURRENT_PROFILE is None:
        _CURRENT_PROFILE = _resolve_profile()
    return _CURRENT_PROFILE


def resolve_profile(profile: DeviceProfile | None = None) -> DeviceProfile:
    """Return ``profile`` when an explicit profile is passed, else the
    process's current profile.

    The single choke point for "which profile does this call operate on".
    Engines that accept an explicit profile take ``profile: DeviceProfile |
    None = None`` and resolve through here, so an explicit argument always
    wins and ambient resolution stays the boundary default.
    """
    return profile if profile is not None else current_profile()


def spoof_prefix(profile=None) -> str:
    """The reference-floor run-id prefix for the profile's spoof arch.

    Reference runs are named ``<spoof_reference>_ref_...`` (the spoof library's
    arch, not this device's codename). Historically sites hardwired the
    ``gfx900_ref`` literal; on any other floor that split native/floor wrongly.
    Ambient profile by default.
    """
    return (getattr(resolve_profile(profile), "spoof_reference", "") or "gfx900")


def rebind_profile(profile: DeviceProfile) -> None:
    """Make ``profile`` this process's current profile."""
    global _CURRENT_PROFILE
    _CURRENT_PROFILE = profile




@contextlib.contextmanager
def bound_profile(profile: DeviceProfile):
    """Scope :func:`rebind_profile` to the ``with`` block; restore on exit."""
    old = current_profile()
    rebind_profile(profile)
    try:
        yield profile
    finally:
        rebind_profile(old)


def _from_override(spec: str) -> DeviceProfile:
    p = Path(spec)
    if p.is_file():
        return _from_json_path(p)
    return load_profile(spec)


def _from_json_path(p: Path) -> DeviceProfile:
    data = json.loads(p.read_text())
    if "codename" not in data:
        raise ValueError(f"{p} has no 'codename' key")
    return _to_profile(data, str(p))


def _detect() -> str | None:
    try:
        from oto.device.device_detect import detect_codename
        code = detect_codename()
    except Exception:
        return None
    try:
        load_profile(code)
    except (FileNotFoundError, ValueError):
        return None
    return code


def _resolve_profile() -> DeviceProfile:
    override = os.environ.get(OTO_PROFILE_VAR, "").strip()
    if override:
        return _from_override(override)
    detected = _detect()
    if detected:
        return load_profile(detected)
    return load_profile(DEFAULT_CODENAME)
