"""Device facts: the gfx90c hardware peak table and cell/family vocabulary.

This is the ONLY package in oto that may hold a numeric hardware constant, and
the seam Refactor 2 will use to make the driver device-agnostic.

Owns: the peak GFLOPS table, per-family shape grids, the family <-> Tensile
DataType-char mapping, the realistic acceptance ceilings, the hardware limits
(NUM_CUS, LDS, clock), and the canonical cell/kernel identity helpers.
Does NOT own: any legality rule (oto.tensile.gates), any measurement or
statistics (oto.metrics.*), or the driver's behaviour (oto.runners.*).
Public API: PEAK_GFLOPS, FAMILY_SHAPES, FAMILY_DTYPE_CHAR, FAMILY_DTYPES,
REALISTIC_CEILINGS, THEORETICAL_PEAKS, kernel_typecode,
family_from_kernel_name, dtype_from_kernel_name, cube_side, cell_key,
shipped_cells, shipped_cell_set, kernel_key.
"""
