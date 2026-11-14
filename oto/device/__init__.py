"""Device facts: the device hardware peak table and cell/family vocabulary.

This is the ONLY package in oto that may hold a numeric hardware constant, and
the seam Refactor 2 will use to make the driver device-agnostic. Refactor 2
adds oto/device/profile.py (DeviceProfile) + oto/device/loader.py.

Owns: the peak GFLOPS table, per-family shape grids, the family <-> Tensile
DataType-char mapping, the realistic acceptance ceilings, the hardware limits
(hardware limits like CU count, LDS and clock), and the canonical cell/kernel identity helpers.
Does NOT own: any legality rule (oto.tensile.gates), any measurement or
statistics (oto.metrics.*), or the driver's behaviour (oto.runners.*).
Public API: none at import time; this package re-exports nothing. The names
the profile facts come from ``profiles/<codename>.json``; runtime access goes through
``oto.device.loader.current_profile()``; cell/kernel identity helpers live in
``oto.device.vocabulary``.
"""
