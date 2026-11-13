"""Device profile: the single source of truth for device facts.

Owns: the frozen ``DeviceProfile`` dataclass and its nested policy/limits
sub-structures. Every gate, ceiling, shape list and doc generator reads from
this. No device literal may live outside this module and ``profiles/``.

Does NOT own: loading (oto.device.loader), the device constants (profiles/),
or any legality rule (oto.tensile.gates).

Public API: DeviceProfile, AssemblyGatePolicy, TheoreticalLimits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssemblyGatePolicy:
    """Assembly-class legality policy, parameterised by device features."""
    has_mfma: bool = False
    has_dp4a: bool = False
    has_packed_bf16: bool = False
    # complex (Z/C) may use GlobalSplitU only when MFMA is available
    complex_allows_gsu: bool = False
    # half precision may use GlobalSplitU only when MFMA or packed bf16
    half_allows_gsu: bool = False
    # minimum VectorWidth floor for the classic (non-MFMA) path
    vw_floor: int = 1


@dataclass(frozen=True)
class TheoreticalLimits:
    """Memory roofline + boundary thresholds for the acceptance bars."""
    memory_type: str = ""
    bandwidth_gb_s: float = 0.0
    coherent_host_access: bool = False
    # boundary thresholds (elements) per family, derived by agent-1
    boundaries: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceProfile:
    codename: str
    isa: tuple[int, int, int]
    num_cus: int
    simds_per_cu: int
    lanes_per_simd: int
    max_waves_per_cu: int
    max_clock_mhz: int
    lds_per_cu_kb: int
    l2_size_kb: int
    vgpr_per_cu: int
    has_mfma: bool
    has_dp4a: bool
    has_packed_bf16: bool
    global_load_byte_cap: int
    peak_gflops: dict[str, int]
    family_shapes: dict[str, list[int]]
    realistic_ceilings: dict[str, float]
    family_dtype_char: dict[str, str]
    family_dtypes: dict[str, str]
    family_bytes_per_element: dict[str, int]
    assembly_gates: AssemblyGatePolicy
    theoretical: TheoreticalLimits
    # measured VGPR table (re-measured per device)
    measured_vgpr: dict[str, Any] = field(default_factory=dict)
    # spoof reference codename (or None for native-only)
    spoof_reference: str = ""
    # reported->blas8 scaling per family
    reported_to_blas8: dict[str, float] = field(default_factory=dict)
    # theoretical ALU peaks per family (BLAS-8)
    theoretical_peaks_blas8: dict[str, int] = field(default_factory=dict)
    # realistic ceilings in BLAS-8 units
    realistic_ceilings_blas8: dict[str, float] = field(default_factory=dict)
    # graded cell list per family
    family_cells: dict[str, list[int]] = field(default_factory=dict)
    # peak gflops in client-reported units
    theoretical_peaks: dict[str, int] = field(default_factory=dict)
    realistic_ceilings_reported: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        # assembly_gates defaults derived from features if not explicitly set
        pass
