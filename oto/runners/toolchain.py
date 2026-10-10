#!/usr/bin/env python3
"""Toolchain discovery: the Tensile checkout and the ROCm toolchain.

Owns: resolving the Tensile root (explicit flag -> live env -> .env, with no
fallback) and resolving every ROCm path from native discovery only (explicit env
value that exists, then `hipconfig`, then `shutil.which`). No hardcoded candidate
chains.
Does NOT own: the driver that uses these paths (oto.runners.driver) or the
Tensile subprocess environment (also oto.runners.driver).
Public API: DEFAULT_TENSILE_ROOT, require_tensile_root, hipconfig,
resolve_rocm_paths.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

#: Read once at import time so a caller that wants the .env value does not have
#: to re-read the file. Never a fallback path.
DEFAULT_TENSILE_ROOT = (Path(os.environ["TENSILE_ROOT"])
                        if os.environ.get("TENSILE_ROOT") else None)


def require_tensile_root(explicit: Optional[Path],
                         default: Optional[Path]) -> Path:
    """Resolve the Tensile checkout root from an explicit arg, live env, or .env.

    Args:
        explicit: A ``--tensile-root`` value, which wins over everything.
        default: The value read from the environment at import time.

    Returns:
        The resolved checkout root, validated to contain ``Tensile/bin/Tensile``.

    Raises:
        ValueError: When no root was supplied, or the one supplied is not a
            Tensile checkout. There is deliberately no fallback -- a driver that
            guesses a root shells out to the wrong Tensile and produces a corpus
            that looks like measurements of this device.
    """
    candidate = explicit or default
    if candidate is None:
        raise ValueError(
            "TENSILE_ROOT is not set. Configure it in the repo-root `.env` "
            "(TENSILE_ROOT=<path to Tensile checkout>) or pass --tensile-root."
        )
    resolved = Path(candidate).resolve()
    if not (resolved / "Tensile" / "bin" / "Tensile").exists():
        raise ValueError(f"TENSILE_ROOT {resolved} has no Tensile bin/Tensile; check `.env`.")
    return resolved


def hipconfig() -> Dict[str, str]:
    """Query the native ROCm discovery tool (`hipconfig`) for install paths.

    `hipconfig` is the ROCm-shipped authority for toolchain locations
    (ROCM_PATH, HIP_PATH, HIP_CLANG_PATH). Returns parsed KEY: value pairs.
    """
    hipconfig = shutil.which("hipconfig")
    if not hipconfig:
        return {}
    try:
        out = subprocess.run([hipconfig], capture_output=True, text=True, timeout=30).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return {}
    info: Dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r"([A-Z][A-Z0-9_]*)\s*:\s*(.*)", line.strip())
        if m and m.group(2).strip():
            info[m.group(1)] = m.group(2).strip()
    return info


def resolve_rocm_paths() -> Dict[str, str]:
    """Resolve the ROCm toolchain using native discovery only.

    Order per key: explicit env value (shell or .env) that exists, then native
    discovery (`hipconfig` for roots, `shutil.which` for binaries on PATH).
    No hand-rolled candidate chains.
    """
    hc = hipconfig()

    prefix = os.environ.get("ROCM_PATH", "").strip()
    if not prefix or not os.path.isdir(prefix):
        prefix = hc.get("ROCM_PATH", "")

    bin_dir = os.environ.get("ROCM_BIN", "").strip()
    if not bin_dir or not os.path.isdir(bin_dir):
        cand = str(Path(prefix) / "bin") if prefix else ""
        hipcc = shutil.which("hipcc")
        bin_dir = cand if os.path.isdir(cand) else (os.path.dirname(hipcc) if hipcc else "")

    llvm_bin = os.environ.get("ROCM_LLVM_BIN", "").strip()
    if not llvm_bin or not os.path.isdir(llvm_bin):
        cand = hc.get("HIP_CLANG_PATH", "") or (str(Path(prefix) / "llvm" / "bin") if prefix else "")
        llvm_bin = cand if os.path.isdir(cand) else ""

    assembler = os.environ.get("TENSILE_ASSEMBLER", "").strip()
    if not assembler or not os.path.isfile(assembler):
        cand = str(Path(llvm_bin) / "clang++") if llvm_bin else ""
        assembler = cand if os.path.isfile(cand) else (shutil.which("clang++") or "")

    fallback = os.environ.get("TENSILE_ASSEMBLER_FALLBACK", "").strip()
    if not fallback or not os.path.isfile(fallback):
        fallback = shutil.which("clang++") or ""

    return {
        "ROCM_PATH": prefix,
        "HIP_PATH": hc.get("HIP_PATH", prefix),
        "ROCM_BIN": bin_dir,
        "ROCM_LLVM_BIN": llvm_bin,
        "TENSILE_ASSEMBLER": assembler,
        "TENSILE_ASSEMBLER_FALLBACK": fallback,
    }
