#: The last commit before the package split. Every check in this directory
#: compares against it, so "no behaviour change" is measured against one
#: fixed point rather than against whatever HEAD happens to be.
REFACTOR_BASE = "2824c2f"

#!/usr/bin/env python3
"""Differential check: every scheduler.py symbol must behave identically
after the oto.tensile.candidate / oto.tensile.gates split.

Runs the ORIGINAL module (from HEAD, stubbed with the flat import) and the NEW
package side by side over an exhaustive config corpus and asserts equal
results, including exact reason strings.
"""
import importlib.util
import itertools
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ORIG = Path("/tmp/opencode/scheduler_orig.py")

# Load the original scheduler.py as module "scheduler_orig", with its
# `from gfx90c_common import ...` redirected at the new peaks module.
import types
import subprocess

# Create the original scheduler.py file
if not ORIG.parent.exists():
    ORIG.parent.mkdir(parents=True, exist_ok=True)

src = subprocess.run(["git", "show", f"{REFACTOR_BASE}:scheduler.py"], cwd=ROOT,
                     capture_output=True, text=True, check=True).stdout
ORIG.write_text(src)

fake_pkg = types.ModuleType("gfx90c_common")
import oto.device.peaks as peaks
for name in ("NUM_CUS", "LDS_PER_CU_KB", "FAMILY_DTYPE_CHAR",
             "MAX_WAVES_PER_CU", "FAMILY_DTYPES", "FAMILY_SHAPES",
             "PEAK_GFLOPS", "REALISTIC_CEILINGS", "THEORETICAL_PEAKS",
             "DTYPE_TO_FAMILY", "kernel_typecode", "family_from_kernel_name",
             "dtype_from_kernel_name", "cube_side", "cell_key",
             "shipped_cells", "shipped_cell_set", "kernel_key",
             "NUM_SIMDS_PER_CU", "LANES_PER_SIMD", "MAX_CLOCK_MHZ",
             "L2_SIZE_KB"):
    setattr(fake_pkg, name, getattr(peaks, name))
sys.modules["gfx90c_common"] = fake_pkg

spec = importlib.util.spec_from_file_location("scheduler_orig", ORIG)
sched_orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sched_orig)

from oto.tensile import candidate as new
from oto.tensile.gates import assembly as gasm
from oto.tensile.gates import loads as gloads
from oto.tensile.gates import occupancy as gocc
from oto.tensile.gates import vgpr_model as gv

fails = []


def check(label, a, b):
    if a != b:
        fails.append((label, a, b))


FUNCS = [
    ("cap_vector_width", sched_orig.cap_vector_width, new.cap_vector_width),
    ("parse_tensile_shape", sched_orig.parse_tensile_shape, new.parse_tensile_shape),
    ("assembly_class_valid", sched_orig.assembly_class_valid, gasm.assembly_class_valid),
    ("ldspad_feasible", sched_orig.ldspad_feasible, gocc.ldspad_feasible),
    ("occupancy_feasible", sched_orig.occupancy_feasible, gocc.occupancy_feasible),
    ("occupancy_wg", sched_orig.occupancy_workgroups_per_cu, gocc.occupancy_workgroups_per_cu),
    ("validate_tensile_loads", sched_orig.CandidateGenerator._validate_tensile_loads, gloads.validate_tensile_loads),
    ("depth_u", sched_orig._depth_u, gv.depth_u),
    ("assembly_depth_u", sched_orig._assembly_depth_u, gasm.assembly_depth_u),
    ("tile_dims", sched_orig._tile_dims, gocc.tile_dims),
    ("dtype_char", sched_orig._dtype_char, gocc.dtype_char),
    ("lds_base", sched_orig._lds_base_bytes, gv.lds_base_bytes),
    ("measured_accvgpr", sched_orig._measured_accvgpr, gv.measured_accvgpr),
]

# ---- corpus ----------------------------------------------------------------
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
ARCHS = ["gfx90c", "gfx900", None]

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

print(f"corpus: {len(cfgs)} base configs")

count = 0
for c in cfgs:
    for name, fo, fn in FUNCS:
        try:
            ro = fo(dict(c))
        except Exception as e:  # noqa: BLE001
            ro = ("EXC", type(e).__name__)
        try:
            rn = fn(dict(c))
        except Exception as e:  # noqa: BLE001
            rn = ("EXC", type(e).__name__)
        check(f"{name}:{c}", ro, rn)
        count += 1

# validate_config / estimate_* on the same corpus
gen_orig = sched_orig.CandidateGenerator.__new__(sched_orig.CandidateGenerator)
gen_new = new.CandidateGenerator.__new__(new.CandidateGenerator)
for c in cfgs:
    for label, fo, fn in (
        ("validate_config", gen_orig.validate_config, gen_new.validate_config),
        ("estimate_lds", gen_orig._estimate_lds_usage, new.estimate_lds_usage),
        ("estimate_occ", gen_orig._estimate_occupancy, new.estimate_occupancy),
    ):
        try:
            ro = fo(dict(c))
        except Exception as e:  # noqa: BLE001
            ro = ("EXC", type(e).__name__)
        try:
            rn = fn(dict(c))
        except Exception as e:  # noqa: BLE001
            rn = ("EXC", type(e).__name__)
        check(f"{label}:{c}", ro, rn)
        count += 1

# ---- targeted knob sweeps (pad / stagger / af0em / sci / arch) ---------------
import random
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
        "Architecture": random.choice(ARCHS),
        "label": random.choice(["HH_HPA_sweep", "HS_HPA_sweep", "ss", ""]),
        "FamilyLabel": random.choice(FAMILIES),
    }
    if random.choice([True, False]):
        c["GlobalSplitU"] = 2
    for name, fo, fn in FUNCS:
        try:
            ro = fo(dict(c))
        except Exception as e:  # noqa: BLE001
            ro = ("EXC", type(e).__name__)
        try:
            rn = fn(dict(c))
        except Exception as e:  # noqa: BLE001
            rn = ("EXC", type(e).__name__)
        check(f"KNOB {name}:{c}", ro, rn)
        count += 1

print(f"differential comparisons: {count}")
if fails:
    print(f"FAILURES: {len(fails)}")
    for label, a, b in fails[:12]:
        print("  ", label)
        print("     orig:", a)
        print("     new :", b)
    sys.exit(1)
print("ALL EQUAL")
