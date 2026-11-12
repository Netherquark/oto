"""Device profile loader.

Owns: reading ``profiles/<codename>.json`` into a frozen ``DeviceProfile``.
Does NOT own: the dataclass (oto.device.profile) or the constants.

Public API: load_profile, load_profile_from_starter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from oto.device.profile import (
    AssemblyGatePolicy, DeviceProfile, TheoreticalLimits,
)

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"


def _to_profile(data: Dict[str, Any]) -> DeviceProfile:
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


def load_profile(codename: str, profiles_dir: Optional[Path] = None) -> DeviceProfile:
    d = profiles_dir or _PROFILES_DIR
    path = Path(d) / f"{codename}.json"
    if not path.exists():
        raise FileNotFoundError(f"No profile for {codename}: {path}")
    return _to_profile(json.loads(path.read_text()))


def load_profile_from_starter(starter_path: Path, profiles_dir: Optional[Path] = None) -> DeviceProfile:
    """Load a profile from a starter file's JSON block, or fall back to a named profile."""
    text = Path(starter_path).read_text()
    # Try to find a fenced json/yaml block
    import re
    m = re.search(r"```(?:json|yaml)?\s*\n(.*?)\n```", text, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            if "codename" in data:
                return _to_profile(data)
        except json.JSONDecodeError:
            pass
    # Fall back: treat starter's codename as a profile name
    m2 = re.search(r"codename:\s*(\S+)", text)
    if m2:
        return load_profile(m2.group(1).strip(), profiles_dir)
    raise ValueError(f"Cannot derive profile from starter: {starter_path}")


def default_profile():
    """The gfx90c profile used as the default when no device is specified."""
    return load_profile("gfx90c")
