"""Easy-mode onboarding: walk a human through preparing oto for a first run.

Owns: interactive + non-interactive setup — convergence-mode choice, spoof
GPU (informed mode), ROCm/Tensile discovery, client build orchestration,
``.env`` generation, and the final ``oto doctor`` / ``oto preflight`` gate.
Does NOT own: the toolchain resolution itself (```oto.runners.toolchain```), the
client build (``scripts/build_tensile_client.sh``), or any GPU work — this
module never touches a GPU.

Public API: ``run_setup``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DOTENV_EXAMPLE = REPO / ".env.example"
DOTENV = REPO / ".env"


def _discover_rocm() -> list[Path]:
    """Return complete, full-SDK ROCm prefixes (validated by include/hip marker)."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def _has_compiler(path: Path) -> bool:
        """True when the prefix ships a usable amdclang++."""
        for layout in ("lib/llvm/bin/amdclang++", "llvm/bin/amdclang++",
                       "lib/python*/site-packages/_rocm_sdk_core/lib/llvm/bin/amdclang++",
                       "lib64/rocm/llvm/bin/amdclang++", "bin/amdclang++"):
            for c in path.glob(layout):
                if c.is_file():
                    return True
        return False

    def _add(path: Path) -> None:
        """Record a prefix if it is a full SDK (include/hip marker), once."""
        key = str(path)
        if key in seen:
            return
        if (path.is_dir() and
                (path / "include" / "hip" / "amd_detail" /
                 "amd_warp_functions.h").is_file()):
            seen.add(key)
            candidates.append(path)

    # ... then at the end, sort: complete SDKs (marker + compiler) first


    if os.environ.get("ROCM_PATH"):
        _add(Path(os.environ["ROCM_PATH"]))
    # common locations (never /usr — too easy to misidentify; only the known
    # TheRock layouts and /opt/rocm* are scanned, and each must pass the marker).
    for cand in sorted(Path("/opt").glob("rocm*")):
        _add(cand)
    for cand in Path("/home").glob("*/rocm-nightly-venv"):
        for sub in (Path("lib") / "python3.14" / "site-packages" /
                    "_rocm_sdk_core", Path("dist-7.15.0a20260728")):
            _add(cand / sub)
    for cand in Path("/home").glob("*/dist-*"):
        _add(cand)
    for cand in Path("/home").glob("*/rocm-*"):
        _add(cand)
    # Prefer complete SDKs (include marker + compiler) over partial ones.
    candidates.sort(
        key=lambda p: (_has_compiler(p), len(str(p)), str(p)),
        reverse=True,
    )
    return candidates


def _discover_tensile() -> list[Path]:
    """Return Tensile checkout roots."""
    cands: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        """Record a checkout root if it carries Tensile/bin/Tensile, once."""
        key = str(path)
        if key in seen:
            return
        for sub in ("", "shared/tensile", "projects/Tensile",
                    "shared/Tensile", "Tensile"):
            cand = path / sub if sub else path
            if (cand / "Tensile" / "bin" / "Tensile").is_file():
                seen.add(key)
                cands.append(cand)
                return

    if os.environ.get("TENSILE_ROOT"):
        _add(Path(os.environ["TENSILE_ROOT"]))
    # common dev roots (shallow + one level deeper) so a typical checkout is
    # auto-found without --tensile-root.
    scan_roots = [Path("/home"), Path("/opt"), Path("/tmp")]
    for root in scan_roots:
        if not root.is_dir():
            continue
        for cand in root.glob("*"):
            _add(cand)
            if cand.is_dir():
                for sub in cand.glob("*"):
                    _add(sub)
    return cands


def _say(msg: str = "") -> None:
    """Wizard narration; stdout stays a clean data channel (GNU convention)."""
    print(msg, file=sys.stderr)


def _ask(prompt: str, default: str = "", choices: list[str] | None = None) -> str:
    """Read one answer, respecting OTO_NO_INPUT and POSIX TTY rules.

    Prompts go to stderr so stdout stays a clean data channel (GNU convention).
    Returns the default when stdin is not a TTY or OTO_NO_INPUT is set.
    """
    if os.environ.get("OTO_NO_INPUT") or not sys.stdin.isatty():
        return default
    if choices:
        if default:
            prompt = f"{prompt} [{'/'.join(choices)}] (default: {default}): "
        else:
            prompt = f"{prompt} [{'/'.join(choices)}]: "
    elif default:
        prompt = f"{prompt} (default: {default}): "
    else:
        prompt = f"{prompt}: "
    try:
        sys.stderr.write(prompt)
        sys.stderr.flush()
        ans = sys.stdin.readline().strip()
    except EOFError:
        ans = ""
    return ans or default


def _write_env(rocm: Path, tensile: Path, codename: str, mode: str,
               spoof: str, gpu_targets: str, prefs: dict | None = None) -> Path:
    """Write the repo-root .env. Returns its path."""
    from oto.runners.toolchain import _bin_dir, _llvm_bin

    env = {
        "TENSILE_ROOT": str(tensile),
        "ROCM_PATH": str(rocm),
        "HIP_PATH": str(rocm),
        "ROCM_BIN": _bin_dir(rocm),
        "ROCM_LLVM_BIN": _llvm_bin(rocm),
        "TENSILE_ASSEMBLER": str(Path(_llvm_bin(rocm)) / "amdclang++"),
        "ROCM_VERSION": os.environ.get("ROCM_VERSION", ""),
        "HIP_DEVICE_LIB_PATH": str(rocm / "lib" / "llvm" / "amdgcn" / "bitcode"),
    }
    # GPU targets only drive the client build; record it for the user.
    lines = ["# oto — generated by `oto setup`",
             "# Edit by hand if you need; oto doctor verifies every value.",
             ""]
    for key, val in env.items():
        if val:
            lines.append(f"{key}={val}")
    lines.append("")
    lines.append(f"# convergence mode: {mode}")
    if mode == "informed":
        lines.append(f"# spoof (reference floor): {spoof}")
    lines.append(f"# GPU targets for the client build: {gpu_targets}")
    prefs = prefs or {}
    lines.append(f"# rocm flavour: {prefs.get('flavour', 'python')}")
    lines.append(f"# rocm version policy: {prefs.get('rocm_version_policy', 'nightly')}")
    if prefs.get("rocm_pinned_version"):
        lines.append(f"# rocm pinned version: {prefs['rocm_pinned_version']}")
    lines.append(f"# tensile version policy: {prefs.get('tensile_version_policy', 'pinned')}")
    if prefs.get("tensile_pinned"):
        lines.append(f"# tensile pinned: {prefs['tensile_pinned']}")
    DOTENV.write_text("\n".join(lines) + "\n")
    return DOTENV


def _build_client(rocm: Path, tensile: Path, targets: str, jobs: int,
                   dry_run: bool) -> int:
    """Run the client build script; return its exit code (0 on a dry run)."""
    script = REPO / "scripts" / "build_tensile_client.sh"
    cmd = [str(script), "--rocm-prefix", str(rocm),
           "--tensile-root", str(tensile), "--targets", targets,
           "--jobs", str(jobs)]
    if dry_run:
        cmd.append("--dry-run")
    _say(f"$ {' '.join(cmd)}")
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode


def _step_convergence_mode(args, yes):
    """Ask for (or take) the convergence mode and spoof GPU; return them."""
    mode = getattr(args, "convergence_mode", None) or "blind"
    if not yes and not mode:
        mode = _ask("Convergence mode", "blind", ["blind", "informed"])
    spoof = getattr(args, "spoof", None) or "gfx900"
    if mode == "informed" and not yes:
        spoof = _ask("Spoof (reference floor) GPU codename (community-popular spoof)", "gfx900")
    _say(f"  convergence mode : {mode}" +
          (f"  (spoof: {spoof})" if mode == "informed" else ""))
    _say()
    return mode, spoof


def _step_toolchain_prefs(args, yes):
    """Ask the ROCm/Tensile/HIP/clang version policy + ROCm flavour."""
    flavour = getattr(args, "rocm_flavour", None) or "python"
    if not yes:
        flavour = _ask("ROCm flavour", flavour, ["python", "opt"])
    version_policy = getattr(args, "rocm_version_policy", None) or "nightly"
    if not yes:
        version_policy = _ask("ROCm version policy", version_policy,
                              ["nightly", "pinned"])
    pinned = getattr(args, "rocm_pinned_version", None) or ""
    if not yes and version_policy == "pinned":
        pinned = _ask("Pinned ROCm version string", pinned or "7.15.0a20260728")
    tensile_policy = getattr(args, "tensile_version_policy", None) or "pinned"
    if not yes:
        tensile_policy = _ask("Tensile version policy", tensile_policy,
                              ["nightly", "pinned"])
    tensile_pinned = getattr(args, "tensile_pinned", None) or ""
    if not yes and tensile_policy == "pinned":
        tensile_pinned = _ask("Pinned Tensile commit/SHA", tensile_pinned)
    _say(f"  ROCm flavour      : {flavour}")
    _say(f"  ROCm version      : {version_policy}" +
          (f" ({pinned})" if version_policy == "pinned" else ""))
    _say(f"  Tensile version   : {tensile_policy}" +
          (f" ({tensile_pinned})" if tensile_policy == "pinned" else ""))
    _say("  HIP/clang version : taken from the chosen SDK's amdclang++ --version")
    _say()
    return {
        "flavour": flavour,
        "rocm_version_policy": version_policy,
        "rocm_pinned_version": pinned,
        "tensile_version_policy": tensile_policy,
        "tensile_pinned": tensile_pinned,
    }


def _step_rocm_discovery(args, yes, dry_run):
    """Discover ROCm SDKs and let the user pick one; return the prefix or ``None``."""
    rocm_cands = _discover_rocm()
    rocm = None
    if rocm_cands:
        _say("ROCM installs found (full-SDK only):")
        for i, c in enumerate(rocm_cands, 1):
            _say(f"  [{i}] {c}")
        if yes:
            rocm = rocm_cands[0]
        else:
            choice = _ask("Pick ROCm (number, or 'none' to skip)", "1")
            if choice.lower() != "none":
                try:
                    rocm = rocm_cands[int(choice) - 1]
                except (ValueError, IndexError):
                    rocm = rocm_cands[0]
        _say(f"  ROCm prefix: {rocm or '(none — set ROCM_PATH manually)'}")
        _say()
    else:
        _say("No complete ROCm SDK found on this box.")
        _say("  Install TheRock nightly (or ROCm 7.x) and re-run, or pass")
        _say("  --rocm-prefix /path/to/full/sdk.")
        _say()
        if not yes:
            _ask("Press Enter to continue anyway", "")
    if rocm is None and getattr(args, "rocm_prefix", None):
        rocm = Path(args.rocm_prefix)
    if rocm is not None and not (rocm / "include" / "hip" / "amd_detail" /
                                  "amd_warp_functions.h").is_file():
        _say(f"  WARN: {rocm} does not look like a full SDK (missing "
              f"include/hip/amd_detail/amd_warp_functions.h). Build may fail.")
    return rocm


def _step_tensile_discovery(args, yes):
    """Discover Tensile checkouts and let the user pick one; return the root or ``None``."""
    tensile_cands = _discover_tensile()
    tensile = None
    if tensile_cands:
        _say("Tensile checkouts found:")
        for i, c in enumerate(tensile_cands, 1):
            _say(f"  [{i}] {c}")
        if yes:
            tensile = tensile_cands[0]
        else:
            choice = _ask("Pick Tensile (number, or 'none' to skip)", "1")
            if choice.lower() != "none":
                try:
                    tensile = tensile_cands[int(choice) - 1]
                except (ValueError, IndexError):
                    tensile = tensile_cands[0]
        _say(f"  Tensile root: {tensile or '(none)'}")
        _say()
    else:
        _say("No Tensile checkout found under /home or TENSILE_ROOT.")
        _say("  Clone rocm-libraries (shared/tensile) and re-run, or pass")
        _say("  --tensile-root /path/to/rocm-libraries.")
        _say()
        if not yes:
            _ask("Press Enter to continue anyway", "")
    if tensile is None and getattr(args, "tensile_root", None):
        tensile = Path(args.tensile_root)
    return tensile


def _step_gpu_targets(args, yes):
    """Ask for the GPU targets for the client build; return the comma list."""
    targets = getattr(args, "gpu_targets", None) or "gfx90c"
    if not yes:
        targets = _ask("GPU targets for the client build (comma list)", targets)
    _say(f"  GPU targets: {targets}")
    _say()
    return targets


def _step_client_build(rocm, tensile, targets, args, dry_run):
    """Build the Tensile client when missing; return whether it is usable."""
    client_ok = False
    if rocm is not None and tensile is not None:
        client = tensile / "build" / "client" / "tensile-client"
        if client.is_file():
            _say(f"  Tensile client already built: {client}")
            client_ok = True
        elif getattr(args, "build_client", True) and not getattr(args, "skip_build", False):
            _say("  Building the Tensile client (CPU-only, 2-5 minutes)...")
            rc = _build_client(rocm, tensile, targets,
                               jobs=getattr(args, "jobs", 4) or 4,
                               dry_run=dry_run)
            client_ok = (rc == 0)
            if not client_ok and not dry_run:
                _say("  !! client build FAILED — see the log above. "
                      "Fix the toolchain, then re-run `oto setup`.")
        else:
            _say("  (skipping client build; run scripts/build_tensile_client.sh later)")
    else:
        _say("  (no ROCm/Tensile prefix — skipping client build)")
    _say()
    return client_ok


def _step_write_env(rocm, tensile, args, mode, spoof, targets, dry_run, prefs=None):
    """Write the repo-root ``.env`` from the discovered prefixes."""
    if rocm is None or tensile is None:
        _say("  skipping .env (no ROCm/Tensile prefix)")
        _say()
        return
    if dry_run:
        _say("  DRY RUN: would write .env with ROCM_PATH=" + str(rocm) +
              " TENSILE_ROOT=" + str(tensile))
        _say()
        return
    codename = getattr(args, "codename", "gfx90c")
    if DOTENV.exists() and not getattr(args, "force", False):
        ans = _ask(f".env exists ({DOTENV}). Overwrite?", "no", ["yes", "no"])
        if ans.lower() not in ("yes", "y"):
            _say("  keeping existing .env")
            _say()
            return
    _write_env(rocm, tensile, codename, mode, spoof, targets, prefs=prefs or {})
    _say(f"  wrote {DOTENV}")
    _say()


def _step_verify(dry_run):
    """Run ``oto doctor`` and the deck sanity check (unless this is a dry run)."""
    if dry_run:
        return
    _say("  Running oto doctor...")
    subprocess.run([sys.executable, "-m", "oto", "doctor"], check=False)
    _say()
    _say("  Running oto check candidates --quiet (deck sanity)...")
    subprocess.run([sys.executable, "-m", "oto", "check", "candidates",
                    "--quiet"], check=False)
    _say()


def _step_next_steps():
    """Print the post-setup next steps."""
    _say("=" * 72)
    _say("  Setup finished.")
    _say("=" * 72)
    _say()
    _say("  Next steps:")
    _say("   1. Read docs/operator/starter_pair.md and fill docs/<codename>_starter.{md,json}")
    _say("   2. Verify the starter pair against first-party sources")
    _say("   3. oto agent consult docs/<codename>_starter.md   # CPU-only deck draft")
    _say("   4. oto doctor   # should report 0 FAIL")
    _say("   5. (TTY, on the target silicon) oto tune")
    _say()
    _say("  Convenience:  oto setup --yes --convergence-mode blind  (non-interactive)")
    _say("                oto setup --dry-run  (print the plan only)")


def run_setup(args: Any) -> int:
    """The easy-mode setup wizard: fresh clone to a runnable convergence box (CLI entry)."""
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    # POSIX: interactive setup requires a TTY unless --yes/--dry-run.
    if not yes and not dry_run and not sys.stdin.isatty():
        sys.stderr.write("oto setup: stdin is not a TTY; pass --yes or --dry-run.\n")
        return 2

    _say("=" * 72)
    _say("  oto easy-mode setup")
    _say("  Walks you from a fresh clone to a runnable convergence box.")
    _say("=" * 72)
    _say()

    mode, spoof = _step_convergence_mode(args, yes)
    prefs = _step_toolchain_prefs(args, yes)
    rocm = _step_rocm_discovery(args, yes, dry_run)
    tensile = _step_tensile_discovery(args, yes)
    targets = _step_gpu_targets(args, yes)
    _step_client_build(rocm, tensile, targets, args, dry_run)
    _step_write_env(rocm, tensile, args, mode, spoof, targets, dry_run, prefs=prefs)
    _step_verify(dry_run)
    _step_next_steps()
    if (rocm is None or tensile is None) and not dry_run:
        return 1
    return 0
