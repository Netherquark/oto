"""Device-independent resolvers: kernel name -> family, cell identity helpers.

Owns: the canonical workload-cell identity and kernel-name parsing. These are
device-independent (they parse Tensile kernel names, not hardware constants).

Re-exports from oto.device.peaks for backward compatibility; the implementations
live in peaks.py until the full Refactor 2 routing lands.

Public API: kernel_typecode, family_from_kernel_name, dtype_from_kernel_name,
cube_side, cell_key, shipped_cells, shipped_cell_set, kernel_key, DTYPE_TO_FAMILY,
_TYPECODE_TO_FAMILY, _KERNEL_LAYOUT_TOKENS.
"""

from __future__ import annotations

from oto.device.peaks import (
    _KERNEL_LAYOUT_TOKENS,
    _TYPECODE_TO_FAMILY,
    DTYPE_TO_FAMILY,
    cell_key,
    cube_side,
    dtype_from_kernel_name,
    family_from_kernel_name,
    kernel_key,
    kernel_typecode,
    shipped_cell_set,
    shipped_cells,
)

__all__ = [
    "DTYPE_TO_FAMILY", "_KERNEL_LAYOUT_TOKENS", "_TYPECODE_TO_FAMILY",
    "cell_key", "cube_side", "dtype_from_kernel_name",
    "family_from_kernel_name", "kernel_key", "kernel_typecode",
    "shipped_cell_set", "shipped_cells",
]
