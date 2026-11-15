#!/usr/bin/env python3
"""Shared machinery for the evergreen verification checks.

Owns: materialising another ref of this repo as a detached ``git worktree``
(the other tree, byte-for-byte, as its own checkout -- no exec shims, no
renamed modules) and running a Python probe inside it with that tree's root
on ``PYTHONPATH``. The contract is what comes back: the probe's stdout (or
byte artefacts it writes) versus the same probe run against this tree.
Does NOT own: any GPU work, any GPU-environment probe, or the equivalence
semantics (those live in each check).
Public API: ref_worktree, probe, read_tree_file.
"""
from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class EvergreenError(Exception):
    pass


_SCRATCH_DIR: Path | None = None


def scratch_dir() -> Path:
    """A process-lifetime scratch directory for verifier artifacts.

    Created lazily under the system temp root, removed at process exit.
    Verifiers write candidate-side byte artefacts here; nothing else owns it.
    """
    global _SCRATCH_DIR
    if _SCRATCH_DIR is None:
        d = Path(tempfile.mkdtemp(prefix="oto_evergreen_scratch_"))
        atexit.register(shutil.rmtree, d, True)
        _SCRATCH_DIR = d
    return _SCRATCH_DIR


def ref_worktree(ref: str) -> Path:
    """Materialise ``ref`` as a detached worktree in a temp dir.

    Raises EvergreenError when the ref is unresolvable. The worktree is
    registered for cleanup at process exit (``git worktree remove --force``);
    cleanup failures are reported, never raised during comparison.
    """
    probe = subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"],
                           cwd=ROOT, capture_output=True)
    if probe.returncode != 0:
        raise EvergreenError(f"unresolvable ref: {ref}")
    tmp = Path(tempfile.mkdtemp(prefix="oto_evergreen_"))
    wt = tmp / "tree"
    result = subprocess.run(["git", "worktree", "add", "--detach", str(wt), ref],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise EvergreenError(f"git worktree add failed: {result.stderr.strip()}")

    def _cleanup():
        try:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=ROOT, capture_output=True)
        except Exception:
            pass
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    atexit.register(_cleanup)
    return wt


def probe(tree: Path, code: str, *, env_extra: dict | None = None,
          timeout: int = 900) -> subprocess.CompletedProcess:
    """Run ``code`` against ``tree`` with the tree's root as the only PYTHONPATH entry.

    The probe is the REF comparison: the child must import the tree's own code,
    never the parent's ``oto`` (its leak would make REF comparisons compare HEAD
    against HEAD and always report byte-identical). Third-party deps still come
    from the interpreter's ordinary path (stdlib + site-packages), untouched by
    PYTHONPATH.
    """
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tree)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, "-c", code],
                          cwd=str(tree), env=env, capture_output=True,
                          text=True, timeout=timeout)


def read_tree_file(ref: str, rel: str) -> str | None:
    out = subprocess.run(["git", "show", f"{ref}:{rel}"],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return out.stdout


# ---------------------------------------------------------------------------
# Drift manifest: content-addressed, never commit-addressed.
# ---------------------------------------------------------------------------
import json as _json

_MANIFEST_PATH = Path(__file__).resolve().parent / "drift_manifest.json"


def load_manifest() -> dict:
    try:
        return _json.loads(_MANIFEST_PATH.read_text())
    except Exception:
        return {"description": ""}


def drift_matches(check: str, key: str) -> str | None:
    """The reason recorded for ``key``'s intentional drift, or None."""
    entries = load_manifest().get(check, [])
    for entry in entries:
        if isinstance(entry, dict) and entry.get("key") == key:
            return entry.get("reason", "(reason unrecorded)")
        # Tolerate legacy string entries: "symbol :: reason"
        if isinstance(entry, str) and " :: " in entry:
            head, reason = entry.split(" :: ", 1)
            if head.strip() == key:
                return reason.strip()
    return None


def print_drift_summary(check: str, drifted: list[str]) -> int:
    """Print the drift classification; return 1 when any drift is unmanifested."""
    manifest_hits, unexplained = [], []
    for key in drifted:
        reason = drift_matches(check, key)
        if reason is not None:
            manifest_hits.append((key, reason))
        else:
            unexplained.append(key)
    if manifest_hits:
        print(f"MANIFESTED DRIFT ({len(manifest_hits)}) -- approved, recorded in drift_manifest.json:")
        for key, reason in manifest_hits:
            print(f"   {key}\n      reason: {reason}")
    if unexplained:
        print(f"UNMANIFESTED DRIFT ({len(unexplained)}) -- any of these is a regression:")
        for key in unexplained:
            print(f"   {key}")
    return 1 if unexplained else 0


def gate_attested(check: str, base: str, function_name: str) -> bool:
    """True when drift_manifest attests ``function_name`` for ``base``."""
    for entry in load_manifest().get(check, []) or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("base") == base and entry.get("key") == function_name:
            return True
    return False
