#!/usr/bin/env python3
"""Shared verdict worker for the evergreen gate differential.

Owns: emitting (func, config, verdict) tuples for the corpus in this tree,
by resolving the gate symbols through whichever layout the tree carries
(the former ``scheduler.py`` or the ``oto/tensile/gates/*`` package).
Does NOT own: the gate logic (`oto.tensile.gates`.*) or the parent comparison.
Public API: emit.
"""
from __future__ import annotations

import json
import random

#: The gate surface shared by both layouts. Each row: the label, the module
#: attribute in the CURRENT (post-split) tree, and the module attribute in the
#: legacy scheduler.py tree.
_TABLE = [
    ("cap_vector_width", "oto.tensile.candidate", "cap_vector_width",
     ("mod", "cap_vector_width")),
    ("parse_tensile_shape", "oto.tensile.candidate", "parse_tensile_shape",
     ("mod", "parse_tensile_shape")),
    ("assembly_class_valid", "oto.tensile.gates.assembly", "assembly_class_valid",
     ("mod", "assembly_class_valid")),
    ("ldspad_feasible", "oto.tensile.gates.occupancy", "ldspad_feasible",
     ("mod", "ldspad_feasible")),
    ("occupancy_feasible", "oto.tensile.gates.occupancy", "occupancy_feasible",
     ("mod", "occupancy_feasible")),
    ("occupancy_wg", "oto.tensile.gates.occupancy", "occupancy_workgroups_per_cu",
     ("mod", "occupancy_workgroups_per_cu")),
    ("validate_tensile_loads", "oto.tensile.gates.loads", "validate_tensile_loads",
     ("mod.CandidateGenerator", "_validate_tensile_loads")),
    ("depth_u", "oto.tensile.gates.vgpr_model", "depth_u",
     ("mod", "_depth_u")),
    ("assembly_depth_u", "oto.tensile.gates.assembly", "assembly_depth_u",
     ("mod", "_assembly_depth_u")),
    ("tile_dims", "oto.tensile.gates.occupancy", "tile_dims",
     ("mod", "_tile_dims")),
    ("dtype_char", "oto.tensile.gates.occupancy", "dtype_char",
     ("mod", "_dtype_char")),
    ("lds_base", "oto.tensile.gates.vgpr_model", "lds_base_bytes",
     ("mod", "_lds_base_bytes")),
    ("measured_accvgpr", "oto.tensile.gates.vgpr_model", "measured_accvgpr",
     ("mod", "_measured_accvgpr")),
]

FAMILIES = ["SS", "DD", "HH", "HS", "CC", "ZZ", "HH_HPA", "HS_HPA", "S", "D",
            "H", "C", "Z", "I8", "B", "FF", "", "XX"]
MTS = ["128x128x8", "64x64x16", "128x32x16", "256x256x8", "32x32x16", "96x96x16",
       "64x64x8", "128x64x16", "MT128x128x8", "SB_128x128x8", "HB_64x64x16",
       "32x64x8", "16x16x16", "8x8x16", "128x128", "junk", "", "64X64X16"]
TTS = ["8x8", "4x4", "4x8", "8x4", "2x2", "6x6", "2x8", "16x16", "4x6",
       "4X4", "_4_4", "8X8", "3x3", "12x4", "junk", ""]
DEPTHS = [None, 8, 16, 32, 4, 1]
VWS = [None, 1, 2, 4, 8]
NLAS = [None, 1, -1, 2, 4, 8]
GSUS = [None, 1, 2, 4]
STAGGERS = [None, 0, 2, 4, 16, 32, 64, 256, 512]
SUSS = [None, 0, 16, 256, 512, 1024]
SUMS = [None, 0, 1, 4]
PADS = [None, 0, 1, 4]
AF0EM = [None, 1, 2]
SCI = [None, 0, 1, True, False]

REF = "HEAD~1"


def _corpus(archs):
    cfgs = []
    for dt in ("S", "D", "H", "Z", "C", "I8", "SS", "HH", "ZZ", "HH_HPA", None):
        for mt in ("128x128x8", "64x64x16", "128x32x16", "256x256x8", "32x32x16",
                   "96x96x16", "128x128", "junk"):
            for tt in ("8x8", "4x4", "8x4", "6x6", "16x16", "12x4"):
                for depth in (None, 16, 8):
                    for vw in (None, 4, 2):
                        c = {"MacroTile": mt, "ThreadTile": tt}
                        if dt is not None:
                            c["DataType"] = dt
                        if depth is not None:
                            c["DepthU"] = depth
                        if vw is not None:
                            c["VectorWidth"] = vw
                        cfgs.append(c)
    random.seed(1234)
    for _ in range(4000):
        c = {
            "MacroTile": random.choice(MTS),
            "ThreadTile": random.choice(TTS),
            "DataType": random.choice(FAMILIES),
            "NLCA": random.choice(NLAS),
            "GlobalSplitU": random.choice(GSUS),
            "LdsPadA": random.choice(PADS),
            "LdsPadB": random.choice(PADS),
            "AssertFree0ElementMultiple": random.choice(AF0EM),
            "StoreCInUnroll": random.choice(SCI),
            "StaggerU": random.choice(STAGGERS),
            "StaggerUStride": random.choice(SUSS),
            "StaggerUMapping": random.choice(SUMS),
            "Architecture": random.choice(archs),
            "label": random.choice(["HH_HPA_sweep", "HS_HPA_sweep", "ss", ""]),
            "FamilyLabel": random.choice(FAMILIES),
        }
        if random.choice([True, False]):
            c["GlobalSplitU"] = 2
        cfgs.append(c)
    return cfgs


def _load_legacy(root):
    """Materialise the legacy scheduler.py once at REF (cached)."""
    # Synthetic gfx90c_common built from the CURRENT profile's values (passed
    # via env by the parent): the REF tree has no oto.* at this commit.
    import json as _json
    import os as _os
    import subprocess
    import types
    from pathlib import Path

    data = _json.loads(_os.environ["OTO_PROFILE_SHIM"])
    shim = types.ModuleType("gfx90c_common")
    shim.NUM_CUS = data["NUM_CUS"]
    shim.LDS_PER_CU_KB = data["LDS_PER_CU_KB"]
    shim.MAX_WAVES_PER_CU = data["MAX_WAVES_PER_CU"]
    shim.FAMILY_DTYPE_CHAR = dict(data["FAMILY_DTYPE_CHAR"])
    import sys
    sys.modules["gfx90c_common"] = shim

    src = subprocess.run(["git", "show", f"{REF}:scheduler.py"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    import tempfile
    mod_path = Path(tempfile.mkdtemp(prefix="oto_gate_ref_")) / \
        f"scheduler_orig_{abs(hash(REF)) & 0xffff:x}.py"
    mod_path.write_text(src)
    import importlib.util
    spec = importlib.util.spec_from_file_location("scheduler_orig", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_table(root):
    """[(label, callable)] — this tree's implementation of the gate surface."""
    import sys
    sys.path.insert(0, str(root))

    has_legacy = (root / "scheduler.py").is_file()
    if has_legacy:
        mod = _load_legacy(root)
        table = []
        for label, _mod_path, _cur_attr, (lspec, lattr) in _TABLE:
            if lspec == "mod.CandidateGenerator":
                table.append((label, getattr(mod.CandidateGenerator, lattr)))
            else:
                table.append((label, getattr(mod, lattr)))
        return table

    import importlib
    return [(label, getattr(importlib.import_module(mod_path), attr))
            for label, mod_path, attr, _legacy in _TABLE]


def _verdict(fn, cfg):
    try:
        res = fn(dict(cfg))
    except Exception as e:
        return ("EXC", type(e).__name__)
    if isinstance(res, (tuple, list)):
        return list(res)
    return res


def emit(out_path: str, ref: str | None = None) -> None:
    global REF
    if ref is not None:
        REF = ref

    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    table = _resolve_table(root)

    import os as _os
    raw = _os.environ.get("OTO_ARCHS", '["gfx90c", "gfx900", null]')
    archs = json.loads(raw)
    corpus = _corpus(archs)

    with open(out_path, "w") as fh:
        for c in corpus:
            fh.writelines(json.dumps(
                    {"f": label, "c": dict(c), "r": _verdict(fn, c)},
                    sort_keys=True) + "\n" for label, fn in table)


if __name__ == "__main__":
    import sys
    emit(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
