#!/usr/bin/env python3
"""Shared helpers for the occupancy-gate regression tests.

Owns: the repo-root path/``sys.path`` bootstrap (``BASE``), the gfx90c
ground-truth table Tensile's kernel writer reported for complex (Z, weight 8)
thread tiles (``OBSERVED``), and the ``cfg`` synthetic-config builder shared by
every occupancy-gate test class. Importing this module puts the repo root on
``sys.path`` (and honours ``TENSILE_ROOT`` for the Tensile source tree).
Does NOT own: any test assertions and no gate model logic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# This file lives in tests/, so the repo root is one level up. BASE is both the
# import root and the data root (phases.yaml) and the cwd used to shell out to
# `oto check candidates`, and all three resolve via module invocation.
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
for _p in (os.environ.get("TENSILE_ROOT"), "/home/netherquark/Soham/Large_code/sources/GPU/Tensile"):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)


# Ground truth: per-thread VGPR totals Tensile's kernel writer reported on
# gfx90c for complex (Z, weight 8) thread tiles.
OBSERVED = {
    (2, 2): 63,   # 32x32x8 and 32x32x16
    (4, 2): 95,   # 64x64x8
    (2, 4): 99,   # 32x64x8
    (4, 4): 154,  # 64x64x8
    (2, 8): 171,  # 32x128x8
    (8, 4): 271,  # 128x32x8  -- FAILED for real
    (8, 8): 519,  # 64x64x16  -- FAILED for real
}


def cfg(dtype, macro, thread, **kw):
    """Config helper. DepthU mirrors the MacroTile depth unless overridden, so
    a test cannot accidentally assert on a shallower tile than it names."""
    parts = str(macro).split("x")
    depth = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 8
    c = {"DataType": dtype, "FamilyLabel": dtype, "MacroTile": macro,
         "ThreadTile": thread, "VectorWidth": 1, "DepthU": depth,
         "WorkGroupMapping": 4, "GlobalSplitU": 1, "StaggerU": 32,
         "ContractionPattern": "Ailk_Bjlk", "LdsPadB": 0}
    c.update(kw)
    return c
