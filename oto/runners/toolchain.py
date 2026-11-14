#!/usr/bin/env python3
"""Toolchain discovery: the Tensile checkout and the ROCm toolchain.

Owns: resolving the Tensile root (explicit flag -> live env -> repo `.env`, with
no fallback) and resolving the ROCm toolchain from the user-provided `ROCM_PATH`
(explicit flag/env/.env only, no fallback -- the same contract as TENSILE_ROOT):
``ROCM_BIN`` and ``ROCM_LLVM_BIN`` derive from it when not set, the assembler is
preferred as the SDK's ``amdclang++`` (system ROCm: ``lib/llvm/bin``; TheRock
python-sdk: ``lib/python*/site-packages/_rocm_sdk_core/lib/llvm/bin``; TheRock
tarball: ``llvm/bin``). ``hipconfig`` is kept for compatibility but is no longer
consulted by the resolver. Also owns reading the repo-root `.env` via
`python-dotenv`, so no other module hand-parses it.
Does NOT own: the driver that uses these paths (oto.runners.driver) or the
Tensile subprocess environment (also oto.runners.driver).
Public API: REPO_ROOT, DOTENV_PATH, DEFAULT_TENSILE_ROOT, require_tensile_root,
require_rocm_path, hipconfig, resolve_rocm_paths.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

#: Repo root, the directory that owns `.env`. `.env` is repo configuration, not
#: a package resource, so it is addressed by path rather than by importlib.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Repo-root `.env`, or None when the repo ships without one (a fresh clone).
DOTENV_PATH = REPO_ROOT / ".env"

load_dotenv(dotenv_path=DOTENV_PATH, override=False)

#: Read once at import time so a caller that wants the .env value does not have
#: to re-read the file. Never a fallback path.
DEFAULT_TENSILE_ROOT = (Path(os.environ["TENSILE_ROOT"])
                        if os.environ.get("TENSILE_ROOT") else None)


def require_tensile_root(explicit: Path | None,
                         default: Path | None) -> Path:
    """Resolve the Tensile checkout root from an explicit arg, live env, or .env.

    Precedence, highest first: the explicit ``--tensile-root`` value; the live
    process environment; the repo-root ``.env``. The live environment wins over
    `.env` because a caller who exported a value meant it.

    Args:
        explicit: A ``--tensile-root`` value, which wins over everything.
        default: The value read from the environment at import time, which
            already includes anything ``.env`` contributed.

    Returns:
        The resolved checkout root, validated to contain ``Tensile/bin/Tensile``.

    Raises:
        ValueError: When no root was supplied, or the one supplied is not a
            Tensile checkout. There is deliberately no fallback -- a driver that
            guesses a root shells out to the wrong Tensile and produces a corpus
            that looks like measurements of this device.
    """
    candidate = explicit or default or os.environ.get("TENSILE_ROOT")
    if not candidate:
        raise ValueError(
            "TENSILE_ROOT is not set. Configure it in the repo-root `.env` "
            "(TENSILE_ROOT=<path to Tensile checkout or rocm-libraries root>), "
            "export it, or pass --tensile-root."
        )
    resolved = Path(candidate).resolve()
    # Support both the standalone Tensile checkout and the rocm-libraries
    # super-repo layout, where Tensile lives under projects/ or shared/
    # (the super repo spells it "shared/tensile", all lowercase).
    if not (resolved / "Tensile" / "bin" / "Tensile").exists():
        for sub in ("projects/Tensile", "shared/Tensile", "shared/tensile",
                    "Tensile"):
            alt = resolved / sub
            if (alt / "Tensile" / "bin" / "Tensile").exists():
                resolved = alt
                break
    if not (resolved / "Tensile" / "bin" / "Tensile").exists():
        raise ValueError(
            f"TENSILE_ROOT {resolved} has no Tensile/bin/Tensile. Fix the "
            f"value in {DOTENV_PATH}, export it, or pass --tensile-root."
        )
    return resolved


def hipconfig() -> dict[str, str]:
    """Query the native ROCm discovery tool (`hipconfig`) for install paths.

    Kept for compatibility. The resolver no longer consults it (the tooling
    must not silently fall through to `/usr`/`hipconfig` when the user set
    `ROCM_PATH`); use it only as an optional cross-check.
    """
    hipconfig = shutil.which("hipconfig")
    if not hipconfig:
        return {}
    try:
        out = subprocess.run([hipconfig], capture_output=True, text=True, timeout=30).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return {}
    info: dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r"([A-Z][A-Z0-9_]*)\s*:\s*(.*)", line.strip())
        if m and m.group(2).strip():
            info[m.group(1)] = m.group(2).strip()
    return info


def require_rocm_path() -> Path:
    """Resolve the user-provided ROCm root: explicit `ROCM_PATH`, or fail loudly.

    Order: the live process environment first (a caller that exported a value
    meant it), then the repo-root `.env`. There is deliberately no fallback:
    a driver that guesses a ROCm shells hipcc at whatever `/usr` carries and
    produces a corpus that measures the wrong toolchain.
    """
    prefix = os.environ.get("ROCM_PATH", "").strip()
    if not prefix:
        raise ValueError(
            "ROCM_PATH is not set. Point it at your ROCm install in the "
            "repo-root `.env` (e.g. ROCM_PATH=/opt/rocm or "
            ".../rocm-nightly-venv/lib/python3.14/site-packages/"
            "_rocm_sdk_core), export it, or pass it inline. There is no "
            "fallback."
        )
    cand = Path(prefix).resolve()
    if not cand.is_dir():
        raise ValueError(f"ROCM_PATH {prefix!r} (from env/.env) is not a directory.")
    return cand


def _wheel_layout_llvms(prefix: Path) -> list[Path]:
    """`lib/llvm/bin` inside a python-sdk install: `_rocm_sdk_core/lib/llvm/bin`."""
    bins: list[Path] = []
    direct = prefix / "lib" / "llvm" / "bin"
    if direct.is_dir():
        bins.append(direct)
    bins.extend(sdk for sdk in prefix.glob(
        "lib/python*/site-packages/_rocm_sdk_core/lib/llvm/bin") if sdk.is_dir())
    return bins


def _llvm_bin(prefix: Path) -> str:
    """Derive ROCM_LLVM_BIN: explicit env, else the layout-aware probe order;
    an explicit env that points nowhere is a hard error, never a silent skip."""
    explicit = os.environ.get("ROCM_LLVM_BIN", "").strip()
    if explicit:
        if Path(explicit).is_dir():
            return explicit
        raise ValueError(
            f"ROCM_LLVM_BIN={explicit!r} is set in the environment/.env but is "
            f"not a directory (expected a directory in the layout defined by "
            ".env.example). Fix the value; there is no fallback.")
    for cand in (prefix / "lib" / "llvm" / "bin",
                 prefix / "llvm" / "bin",
                 prefix / "lib64" / "rocm" / "llvm" / "bin",
                 *_wheel_layout_llvms(prefix)):
        if cand.is_dir():
            return str(cand)
    return ""


def _bin_dir(prefix: Path) -> str:
    """Resolve ROCM_BIN: explicit env wins; must exist; else prefix/bin."""
    explicit = os.environ.get("ROCM_BIN", "").strip()
    if explicit:
        if Path(explicit).is_dir():
            return explicit
        raise ValueError(
            f"ROCM_BIN={explicit!r} is set in the environment/.env but is not "
            f"a directory. Fix the value; there is no fallback.")
    candidate = str(prefix / "bin")
    if not os.path.isdir(candidate):
        raise ValueError(
            f"ROCM_BIN could not be derived: {candidate} (derived from "
            f"ROCM_PATH={prefix}) is not a directory, and ROCM_BIN is not set. "
            "Set ROCM_BIN explicitly or fix ROCM_PATH.")
    return candidate


def _assembler(prefix: Path, llvm_bin: str) -> str:
    """Prefer the SDK's `amdclang++` (Tensile's native default), else `clang++`.

    An explicit TENSILE_ASSEMBLER pointing at a non-file is a hard error;
    nothing silently picks another compiler."""
    explicit = os.environ.get("TENSILE_ASSEMBLER", "").strip()
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise ValueError(
            f"TENSILE_ASSEMBLER={explicit!r} is set in the environment/.env but "
            "is not a file. Fix the value; there is no fallback.")
    candidates = []
    if llvm_bin:
        candidates += [Path(llvm_bin) / "amdclang++", Path(llvm_bin) / "clang++"]
    candidates += [prefix / "bin" / "amdclang++", prefix / "bin" / "clang++"]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    raise ValueError(
        f"No usable assembler under ROCM_PATH {prefix} or ROCM_LLVM_BIN "
        f"{llvm_bin!r} (looked for amdclang++ then clang++). Set "
        "TENSILE_ASSEMBLER in the repo-root `.env` or export it."
    )


def resolve_rocm_paths() -> dict[str, str]:
    """Resolve the ROCm toolchain from the user-provided `ROCM_PATH` only.

    Disposition per key: explicit env value wins; otherwise derived from
    `ROCM_PATH` (see `require_rocm_path` / `_llvm_bin` / `_assembler`). No
    `hipconfig` fallback, no `/usr` escape hatch -- a user who needs a
    different toolchain points `ROCM_PATH` at it. Every path this returns
    must exist; a dangling path raises with the .env context spelled out.
    """
    prefix = require_rocm_path()
    bin_dir = _bin_dir(prefix)
    llvm_bin = _llvm_bin(prefix)
    assembler = _assembler(prefix, llvm_bin)
    paths = {
        "ROCM_PATH": str(prefix),
        "HIP_PATH": os.environ.get("HIP_PATH", str(prefix)).strip() or str(prefix),
        "ROCM_BIN": bin_dir,
        "ROCM_LLVM_BIN": llvm_bin,
        "TENSILE_ASSEMBLER": assembler,
        "TENSILE_ASSEMBLER_FALLBACK": assembler,
    }
    # HIP_DEVICE_LIB_PATH must point at the user's own bitcode directory, or
    # stay unset; never silently fall back to a system tree.
    bitcode_dir = Path(prefix) / "lib" / "llvm" / "amdgcn" / "bitcode"
    if not bitcode_dir.is_dir():
        bitcode_dir = Path(prefix) / "amdgcn" / "bitcode"
    if bitcode_dir.is_dir():
        paths["HIP_DEVICE_LIB_PATH"] = str(bitcode_dir)
    version = os.environ.get("ROCM_VERSION", "").strip()
    if version:
        paths["ROCM_VERSION"] = version
    return paths
