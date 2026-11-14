"""Best-effort device ``TensileLibrary.dat`` carved from the full kernel database.

Owns: reading the complete measured corpus (``kernel_db.json``, every run, every
protocol), picking the best family-protocol config per shipped cell (with an
honest fallback chain), deduplicating configs per family, emitting the
per-family library-logic YAMLs in the Tensile-confirmed schema, and driving
``TensileCreateLibrary --merge-files --code-object-version=V4`` to produce
``TensileLibrary.dat`` + ``TensileLibrary_<codename>.co`` under the chosen
destination. Also owns the per-cell provenance manifest and the parity /
anti-alias gates.

Does NOT own: the kernel database (oto.harness.kernel_db), the protocol stamp
(oto.metrics.protocol), the launch gates (oto.tensile.gates), or the Tensile
environment (oto.runners.toolchain).

Public API: ``cell_solution_map``, ``dedupe_configs``, ``emit_logic_yaml``,
``default_best_library_dest``, ``build_best_library``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from oto.device import loader as _loader
from oto.harness.coverage_map import _cell_family
from oto.harness.kernel_db import read_kernel_db
from oto.metrics.protocol import UNKNOWN, protocol_of
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import results_rel
from oto.tensile.library_parity import parity_report
from oto.tensile.synthesis.db import DBMutator


def _tensile_candidates() -> list[str]:
    cands = []
    for var in ("TENSILE_ROOT", "OTO_TENSILE_ROOT"):
        v = os.environ.get(var)
        if v:
            cands.append(v)
    # rocm-libraries super-repo layouts: Tensile may live under these subpaths.
    for base in list(cands):
        for sub in ("", "projects/Tensile", "shared/Tensile",
                    "shared/tensile"):
            p = os.path.join(base, sub) if sub else base
            if os.path.isdir(os.path.join(p, "Tensile", "bin")):
                cands.append(p)
    # try dotenv-loaded value
    try:
        from oto.runners.toolchain import DEFAULT_TENSILE_ROOT
        if DEFAULT_TENSILE_ROOT is not None:
            cands.append(str(DEFAULT_TENSILE_ROOT))
    except Exception:
        pass
    return cands

_TENSILE_CANDIDATES = [c for c in dict.fromkeys(_tensile_candidates())
                       if os.path.isdir(os.path.join(c, "Tensile", "bin"))]

def _shipped_cells(profile=None) -> set[tuple[str, str]]:
    """Shipped cells: ``(family, "SxSxS")`` for every shape in the profile.

    Derived at call time -- never frozen at import.
    """
    return {(f, f"{s}x{s}x{s}")
            for f, ss in _loader.resolve_profile(profile,).family_shapes.items() for s in ss}


def __getattr__(name: str):
    """Lazy ``SHIPPED_CELLS`` for back-compat (ambient profile, call time)."""
    if name == "SHIPPED_CELLS":
        return _shipped_cells()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

#: Default output location, relative to the oto checkout.
DEFAULT_BEST_LIBRARY_SUBDIR = Path(results_rel("best_effort_library"))


def default_best_library_dest(base_dir: Path) -> Path:
    """Return the default destination for ``--best-library``."""
    return Path(base_dir) / DEFAULT_BEST_LIBRARY_SUBDIR


def _expand_tensile_root(root: str) -> list[str]:
    out = []
    for sub in ("", "projects/Tensile", "shared/Tensile",
                    "shared/tensile"):
        p = os.path.join(root, sub) if sub else root
        if os.path.isdir(os.path.join(p, "Tensile", "bin")):
            out.append(p)
    return out or [root]


def _ensure_tensile_importable(tensile_root: Path | None = None) -> None:
    roots = []
    if tensile_root is not None:
        roots += _expand_tensile_root(str(tensile_root))
    for r in _TENSILE_CANDIDATES:
        roots += _expand_tensile_root(r)
    for r in roots:
        if r and r not in sys.path:
            sys.path.insert(0, r)
    _ = __import__("Tensile.SolutionStructs", fromlist=["ProblemType"])


def _best_row(rows: list[dict[str, Any]], basis: str) -> dict[str, Any] | None:
    eligible = []
    for r in rows:
        p = protocol_of(r)
        if basis == "any":
            if p != UNKNOWN:
                eligible.append(r)
        elif p == basis:
            eligible.append(r)
    if not eligible:
        return None
    return max(eligible, key=lambda r: float(r.get("gflops_median") or 0.0))


def _cell_rows_from_db(db: dict[str, Any], basis: str) -> dict[tuple[str, str], dict[str, list[dict[str, Any]]]]:
    pools: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    for run_id, rlist in db.items():
        is_floor = str(run_id).startswith("gfx900_ref")
        for r in rlist:
            fam = _cell_family(r)
            shape = r.get("shape")
            if not fam or not shape:
                continue
            cell = (fam, shape)
            if cell not in _shipped_cells():
                continue
            pool = pools.setdefault(cell, {"native_basis": [], "native_any": [], "floor": []})
            rr = dict(r)
            rr["_run"] = run_id
            if is_floor:
                pool["floor"].append(rr)
            else:
                pool["native_any"].append(rr)
                p = protocol_of(r)
                if basis in ("any", p):
                    pool["native_basis"].append(rr)
    return pools


def _carve_one_cell(cell, pool, mut, sched, ldspad_feasible, basis):
    """Return (info_dict, step_label, refused_flag, refused_entry)."""
    from oto.tensile.decks import FAMILY_DECKS
    fam = cell[0]
    chain = [
        ("native_basis", _best_row(pool["native_basis"], basis)),
        ("native_any", _best_row(pool["native_any"], "any")),
        ("floor", _best_row(pool["floor"], "any")),
    ]
    deck_entry = None
    for cand in FAMILY_DECKS.get(fam, []):
        cfg = {**mut._template(fam), **mut._normalize_tile(cand)}
        ok, _ = sched.validate_config(cfg)
        if ok:
            ok, _ = ldspad_feasible(cfg)
        if ok:
            deck_entry = cand
            break
    chain.append(("deck_fallback", deck_entry))

    for step, row in chain:
        if row is None:
            continue
        cand_cfg = {**mut._template(fam), **mut._normalize_tile(row)}
        ok, _ = sched.validate_config(cand_cfg)
        if ok:
            ok, _ = ldspad_feasible(cand_cfg)
        if ok:
            return cand_cfg, step, row, None

    refused_entry = {"cell": f"{cell[0]}:{cell[1]}", "reason": "no gate-legal candidate in chain"}
    return None, None, None, refused_entry


def _provenance(cell, step, row, basis):
    fam = cell[0]
    prov = {"chain_step": step, "family": fam, "shape": cell[1]}
    if step in ("native_basis", "native_any"):
        prov.update({
            "run": row.get("_run") if isinstance(row, dict) else None,
            "protocol": row.get("protocol"),
            "gflops_median": row.get("gflops_median"),
            "phase": row.get("phase"),
            "n_problems": row.get("n_problems"),
        })
    elif step == "floor":
        prov.update({
            "run": "gfx900_ref (floor)",
            "protocol": row.get("protocol"),
            "gflops_median": row.get("gflops_median"),
            "phase": row.get("phase"),
        })
    else:
        prov.update({"run": "deck fallback", "protocol": "n/a"})
    return prov


def cell_solution_map(base_dir: Path, basis: str = "family",
                      kernel_db_path: Path | None = None, profile=None) -> tuple[
        dict[tuple[str, str], dict[str, Any]],
        list[dict[str, Any]], dict[str, Any]]:
    base_dir = Path(base_dir)
    db_path = Path(kernel_db_path) if kernel_db_path else (
        _results_dir(base_dir, _loader.resolve_profile(profile,).codename) / "analysis" / "kernel_db.json")
    db = read_kernel_db(db_path)
    pools = _cell_rows_from_db(db, basis)

    mut = DBMutator(base_dir, None)
    sched = mut._scheduler()
    from oto.tensile.gates.occupancy import ldspad_feasible

    cell_map: dict[tuple[str, str], dict[str, Any]] = {}
    refused: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "basis": basis, "cells": len(_shipped_cells()),
        "native_basis_winners": 0, "native_any_winners": 0,
        "floor_winners": 0, "deck_fallbacks": 0, "refused": 0,
    }

    for cell in sorted(_shipped_cells(), key=lambda c: (c[0], c[1])):
        pool = pools.get(cell, {"native_basis": [], "native_any": [], "floor": []},)
        cand_cfg, step, row, refused_entry = _carve_one_cell(
            cell, pool, mut, sched, ldspad_feasible, basis)
        if refused_entry is not None:
            refused.append(refused_entry)
            stats["refused"] += 1
            continue
        prov = _provenance(cell, step, row, basis)
        if step == "native_basis":
            stats["native_basis_winners"] += 1
        elif step == "native_any":
            stats["native_any_winners"] += 1
        elif step == "floor":
            stats["floor_winners"] += 1
        else:
            stats["deck_fallbacks"] += 1
        cell_map[cell] = {"config": cand_cfg, "provenance": prov, "chain": step}

    stats["refused"] = len(refused)
    return cell_map, refused, stats


def mut_key(cfg: dict[str, Any]) -> str:
    return DBMutator(".", None)._tile_key(cfg)


def dedupe_configs(cell_map: dict[tuple[str, str], dict[str, Any]]) -> tuple[
        dict[str, list[dict[str, Any]]], dict[str, list[tuple[str, str]]]]:
    families: dict[str, list[dict[str, Any]]] = {}
    cells_by_key: dict[str, list[tuple[str, str]]] = {}
    for cell, info in cell_map.items():
        cfg = info["config"]
        fam = cell[0]
        key = mut_key(cfg)
        bucket = families.setdefault(fam, [])
        if key not in {mut_key(c) for c in bucket}:
            bucket.append(cfg)
        cells_by_key.setdefault(key, []).append(cell)
    return families, cells_by_key


def _problem_type_state(fam: str, tensile_root: Path | None = None, profile=None) -> dict[str, Any]:
    _ensure_tensile_importable(tensile_root)
    from Tensile.LibraryIO import updateProblemDatatypes
    from Tensile.SolutionStructs import ProblemType
    dtype_char = _loader.resolve_profile(profile,).family_dtype_char.get(fam, "S",)
    is_hpa = "HPA" in fam
    is_hs = fam == "HS_HPA"
    pt = ProblemType({
        "OperationType": "GEMM",
        "DataType": dtype_char,
        "TransposeA": False,
        "TransposeB": True,
        "UseBeta": True,
        "Batched": True,
        "HighPrecisionAccumulate": is_hpa,
        **({"DestDataType": "s", "ComputeDataType": "s"} if is_hs else {}),
    })
    state = dict(pt.state)
    updateProblemDatatypes(state)
    return state


def _state_sol(cfg: dict[str, Any]) -> dict[str, Any]:
    sol = dict(cfg)
    mt = [int(x) for x in str(cfg["MacroTile"]).split("x")]
    sol["MacroTile"] = mt[:2]
    sol["ThreadTile"] = [int(x) for x in str(cfg["ThreadTile"]).split("x")]
    if "WorkGroup" in cfg:
        sol["WorkGroup"] = [int(x) for x in str(cfg["WorkGroup"]).split("x")]
    sol["ProblemType"] = "derive"
    sol["KernelLanguage"] = "Assembly"
    return sol


def _emit_one_family(fam, cell_map, families, dest_logic_dir, tensile_root, codename, hint=None):
    sols = families[fam]
    state_sols = [_state_sol(cfg) for cfg in sols]

    table = []
    for cell, info in cell_map.items():
        if cell[0] != fam:
            continue
        cfg = info["config"]
        idx = None
        for i, c in enumerate(sols):
            if mut_key(c) == mut_key(cfg):
                idx = i
                break
        if idx is None:
            continue
        s = int(cell[1].split("x")[0])
        speed = info["provenance"].get("gflops_median")
        table.append([[s, s, s, 1], [idx, round(float(speed or 0.0), 1)]])

    root = {
        "MinimumRequiredVersion": "4.44.0",
        "CustomKernelName": f"{codename}_{fam}_lib",
        "ScheduleName": "isa",
        "ArchitectureName": codename,
        "DeviceNames": [codename],
        "ProblemType": _problem_type_state(fam, tensile_root),
        "Solutions": state_sols,
        "LibraryType": "Matching",
        "Library": {"indexOrder": [2, 3, 1, 0], "table": table,
                    "distance": "Equality"},
    }
    (dest_logic_dir / f"{hint or codename}_{fam}.yaml").write_text(
        yaml.safe_dump(root, sort_keys=False))

    winning_shapes = sorted({cell[1] for cell in cell_map if cell[0] == fam})
    return {
        "phase_id": f"best-library-{fam}",
        "config": {"FamilyLabel": fam},
        "shapes": winning_shapes,
    }


def logic_filename_hint(tensile_root, codename) -> str:
    """Filename prefix the target Tensile will match to select logic files.

    The merge step selects logic files by a substring of the file *stem*
    (``findLogicFiles``), using ``getArchitectureName(architecture)`` -- e.g.
    the ROCm 7.x nightly maps each arch onto an ISA-family token the merge
    step matches against (this device resolves onto the vega10 family). Emitting ``<codename>_<family>.yaml`` then silently selects zero
    files (observed: ``# LibraryLogicFiles: found 0 files``, a "successful"
    TCL run with 0 solution catalogs and no ``TensileLibrary.dat``). Ask the
    very Tensile doing the merge; on any failure fall back to the codename
    (which is what Tensile builds that map an arch to itself expect).
    """
    if not tensile_root:
        return codename
    try:
        root = Path(tensile_root)
        code = ("import sys\n"
                "from Tensile.Common import getArchitectureName\n"
                "print(getArchitectureName(sys.argv[1]) or sys.argv[1])\n")
        env = _tensile_env(root)
        proc = subprocess.run([sys.executable, "-c", code, codename],
                              capture_output=True, text=True, env=env,
                              cwd=str(root), timeout=60)
        hint = (proc.stdout or "").strip()
        return hint or codename
    except Exception:
        return codename


def emit_logic_yaml(cell_map: dict[tuple[str, str], dict[str, Any]],
                    dest_logic_dir: Path,
                    tensile_root: Path | None = None,
                    codename: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if codename is None:
        codename = _default_codename()
    dest_logic_dir = Path(dest_logic_dir)
    dest_logic_dir.mkdir(parents=True, exist_ok=True)
    families, _ = dedupe_configs(cell_map)
    hint = logic_filename_hint(tensile_root, codename)

    phases: list[dict[str, Any]] = []
    for fam in sorted(families):
        phase = _emit_one_family(fam, cell_map, families, dest_logic_dir,
                                 tensile_root, codename, hint)
        phases.append(phase)

    parity = parity_report(phases)
    return phases, parity


def anti_alias_scan(logic_dir: Path, final_lib_dir: Path) -> tuple[bool, list[str]]:
    anti_alias_passed = True
    leak_files: list[str] = []
    for path in list(Path(logic_dir).glob("*.yaml")) + list(Path(final_lib_dir).glob("*")):
        if path.is_file():
            try:
                content = path.read_text(errors="ignore")
                if "gfx900" in content or "vega10" in content:
                    anti_alias_passed = False
                    leak_files.append(str(path))
            except Exception:
                pass
    return anti_alias_passed, leak_files


def _tensile_env(tensile_root: Path) -> dict[str, str]:
    from oto.runners.toolchain import resolve_rocm_paths
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{tensile_root}:{env.get('PYTHONPATH', '')}".strip(":")
    try:
        rocm = resolve_rocm_paths()
        # A user-provided ROCM_PATH (shell or .env) must stay the toolchain
        # root: a half-overridden tree (TheRock compiler + system HIP headers
        # from hipconfig's HIP_PATH=/usr) fails in the device compile.
        user_root = os.environ.get("ROCM_PATH", "").strip()
        if user_root and os.path.isdir(user_root):
            env["ROCM_PATH"] = user_root
            env["HIP_PATH"] = os.environ.get("HIP_PATH", "").strip() or user_root
        else:
            env["ROCM_PATH"] = rocm.get("ROCM_PATH", env.get("ROCM_PATH", ""))
            env["HIP_PATH"] = rocm.get("HIP_PATH", env.get("HIP_PATH", ""))
    except Exception:
        pass
    rocm_for_libs = env.get("ROCM_PATH", "")
    # Prefer the user's own device-library bitcode (TheRock ships it under
    # lib/llvm/amdgcn/bitcode). Fall back to a system ROCm only when the
    # user's tree does not carry it.
    own_bitcode = os.path.join(rocm_for_libs, "lib", "llvm", "amdgcn",
                               "bitcode") if rocm_for_libs else ""
    if own_bitcode and os.path.isdir(own_bitcode):
        env["HIP_DEVICE_LIB_PATH"] = os.environ.get("HIP_DEVICE_LIB_PATH") or own_bitcode
        env["ROCM_DEVICE_LIB_PATH"] = os.environ.get("ROCM_DEVICE_LIB_PATH") or own_bitcode
    else:
        for cand in ("/usr/lib64/rocm/llvm/lib/clang", "/opt/rocm/llvm/lib/clang"):
            if os.path.isdir(cand):
                for ver in sorted(os.listdir(cand), reverse=True):
                    bc = os.path.join(cand, ver, "amdgcn", "bitcode")
                    if os.path.isdir(bc):
                        env.setdefault("HIP_DEVICE_LIB_PATH", bc)
                        env.setdefault("ROCM_DEVICE_LIB_PATH", bc)
                        break
    # user-provided ROCm: ensure its own headers are on the include path so the
    # compiler does not fall back to a mismatched system /usr/include/hip.
    #
    # Never prepend a compiler-default system include. Clang's libstdc++ shim
    # uses ``#include_next <math.h>``; duplicating /usr/include puts the same
    # directory twice in the search path and makes include_next skip the real
    # header ("fatal error: 'math.h' file not found").
    rocm_path = env.get("ROCM_PATH", "")
    inc = os.path.join(rocm_path, "include") if rocm_path else ""
    system_includes = {os.path.realpath("/usr/include"),
                       os.path.realpath("/usr/local/include")}
    if inc and os.path.isdir(inc) and os.path.realpath(inc) not in system_includes:
        env["CPLUS_INCLUDE_PATH"] = inc + (":" + env["CPLUS_INCLUDE_PATH"] if env.get("CPLUS_INCLUDE_PATH") else "")
        env["C_INCLUDE_PATH"] = inc + (":" + env["C_INCLUDE_PATH"] if env.get("C_INCLUDE_PATH") else "")
    if rocm_path:
        device_lib = os.path.join(rocm_path, "lib", "llvm", "amdgcn", "bitcode")
        if os.path.isdir(device_lib):
            env.setdefault("HIP_DEVICE_LIB_PATH", device_lib)
            env.setdefault("ROCM_DEVICE_LIB_PATH", device_lib)
    llvm_bin = env.get("ROCM_LLVM_BIN", "/usr/lib64/rocm/llvm/bin")
    if os.path.isdir(llvm_bin) and llvm_bin not in env.get("PATH", ""):
        env["PATH"] = f"{llvm_bin}:{env.get('PATH', '')}"
    return env


def _default_codename(profile=None) -> str:
    return _loader.resolve_profile(profile,).codename


def _run_tcl(tensile_root, logic_dir, final_lib_dir, codename=None):
    if codename is None:
        codename = _default_codename()
    tensile_root = Path(tensile_root)
    # Tensile resolves LogicPath/OutputPath against its own cwd (tensile_root),
    # so a caller-relative dest silently breaks the merge step.
    logic_dir = Path(logic_dir).resolve()
    final_lib_dir = Path(final_lib_dir).resolve()
    tcl_bin = tensile_root / "Tensile" / "bin" / "TensileCreateLibrary"
    if not tcl_bin.exists():
        return False, True, f"TensileCreateLibrary not found at {tcl_bin}"
    env = _tensile_env(tensile_root)
    cmd = [sys.executable, str(tcl_bin), f"--architecture={codename}",
           "--code-object-version=V4", "--merge-files",
           str(logic_dir), str(final_lib_dir), "HIP"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              cwd=str(tensile_root), timeout=3600)
    except Exception as exc:  # pragma: no cover - defensive
        return True, True, str(exc)
    if proc.returncode != 0:
        # Tensile prints its traceback on stdout, not stderr; capture both or
        # the failure is undiagnosable (observed: empty tcl_error with rc=1).
        tail = (proc.stderr or "") + "\n" + (proc.stdout or "")
        return True, True, tail.strip()[-1500:]
    return True, False, None


def _write_best_manifest(dest: Path, basis: str, cell_map, refused, stats, parity,
                         anti_alias_passed, leak_files, tcl_ran, tcl_failed, tcl_error,
                         logic_hint=None) -> None:
    manifest = {
        "basis": basis,
        "cells": len(cell_map),
        "logic_filename_hint": logic_hint,
        "refused": refused,
        "stats": stats,
        "parity": parity,
        "anti_alias_passed": anti_alias_passed,
        "anti_alias_leaks": leak_files,
        "tcl_ran": tcl_ran,
        "tcl_failed": tcl_failed,
        "tcl_error": tcl_error,
        "per_cell": [
            {"cell": f"{c[0]}:{c[1]}", "chain": info["chain"],
             "provenance": info["provenance"],
             "config": info["config"]}
            for c, info in sorted(cell_map.items())
        ],
    }
    (dest / "best_effort_library.json").write_text(json.dumps(manifest, indent=2, default=str))


def build_best_library(base_dir: Path, dest: Path | None = None,
                       basis: str = "family",
                       tensile_root: Path | None = None,
                       kernel_db_path: Path | None = None,
                       codename: str | None = None) -> dict[str, Any]:
    if codename is None:
        codename = _default_codename()
    base_dir = Path(base_dir)
    dest = Path(dest) if dest is not None else default_best_library_dest(base_dir)
    dest.mkdir(parents=True, exist_ok=True)
    logic_dir = dest / "3_LibraryLogic"
    final_lib_dir = dest / "FinalLibrary"
    logic_dir.mkdir(parents=True, exist_ok=True)
    final_lib_dir.mkdir(parents=True, exist_ok=True)

    hint = logic_filename_hint(tensile_root, codename) if tensile_root else codename
    cell_map, refused, stats = cell_solution_map(base_dir, basis, kernel_db_path)
    _phases, parity = emit_logic_yaml(cell_map, logic_dir, tensile_root, codename)

    anti_alias_passed, leak_files = anti_alias_scan(logic_dir, final_lib_dir)

    tcl_ran = False
    tcl_failed = False
    tcl_error = None
    if tensile_root is not None:
        tcl_ran, tcl_failed, tcl_error = _run_tcl(tensile_root, logic_dir, final_lib_dir, codename)

    _write_best_manifest(dest, basis, cell_map, refused, stats, parity,
                         anti_alias_passed, leak_files, tcl_ran, tcl_failed, tcl_error,
                         logic_hint=hint)

    status = "success"
    if tcl_failed or refused or not parity.get("parity_ok", False):
        status = "partial"
    return {
        "status": status,
        "dest": str(dest),
        "cells": len(cell_map),
        "refused": len(refused),
        "parity_ok": parity.get("parity_ok", False),
        "anti_alias_passed": anti_alias_passed,
        "tcl_ran": tcl_ran,
        "tcl_failed": tcl_failed,
        "tcl_error": tcl_error,
        "library_path": str(final_lib_dir / "library") if (tcl_ran and not tcl_failed) else None,
    }
