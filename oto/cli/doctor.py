"""``oto doctor``: one checklist for "why doesn't it work on this box?".

Owns: the diagnostic probes (Python/venv, ``.env``, TENSILE_ROOT, ROCm
toolchain, GPU, registry/DB health, coverage parity, docs registry) and the
per-line remediation hint.
Does NOT own: fixing any of them (the hint names the command that owns the fix),
the checks themselves where an owning module already exists (parity, docs
index), or the normal run path.
Public API: run.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oto.cli import output

FAIL = "FAIL"
WARN = "WARN"
OK = "OK"


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str = ""
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"group": self.group, "name": self.name,
                "status": self.status, "detail": self.detail,
                "hint": self.hint}


def _ok(group: str, name: str, detail: str = "") -> Check:
    return Check(group, name, OK, detail)


def _warn(group: str, name: str, detail: str, hint: str = "") -> Check:
    return Check(group, name, WARN, detail, hint)


def _fail(group: str, name: str, detail: str, hint: str = "") -> Check:
    return Check(group, name, FAIL, detail, hint)


def _safe(group: str, name: str, fn: Any, hint: str = "") -> Check:
    try:
        return fn()
    except Exception as exc:  # a doctor probe must never crash the doctor
        return _fail(group, name, f"{type(exc).__name__}: {exc}", hint)


# ------------------------------------------------------------------ probes

def _python() -> Check:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if (v.major, v.minor) < (3, 10):
        return _fail("toolchain", "Python >= 3.10", detail,
                     "Install Python 3.10+ and re-run 'oto doctor'.")
    return _ok("toolchain", "Python >= 3.10", detail)


def _venv() -> Check:
    active = sys.prefix != sys.base_prefix or bool(os.environ.get("VIRTUAL_ENV"))
    detail = sys.prefix
    if active:
        return _ok("toolchain", "Virtual environment", detail)
    return _warn("toolchain", "Virtual environment",
                 "not active; the interpreter may miss rocm/tensile packages",
                 "Activate the project venv before running GPU commands.")


def _dependencies() -> Check:
    missing = []
    for mod in ("yaml", "dotenv", "rich", "tqdm"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        return _fail("toolchain", "Python dependencies",
                     "missing: " + ", ".join(missing),
                     "Install requirements: python3 -m pip install -r requirements.txt")
    return _ok("toolchain", "Python dependencies", "yaml, dotenv, rich, tqdm")


def _dotenv() -> Check:
    from oto.runners.toolchain import DOTENV_PATH
    if DOTENV_PATH.is_file():
        return _ok("toolchain", ".env", str(DOTENV_PATH))
    return _warn("toolchain", ".env", f"not found at {DOTENV_PATH}",
                 "Copy .env.example to .env and set TENSILE_ROOT.")


def _tensile_root() -> Check:
    from oto.runners.toolchain import (
        DEFAULT_TENSILE_ROOT,
        DOTENV_PATH,
        require_tensile_root,
    )
    candidate = os.environ.get("TENSILE_ROOT") or DEFAULT_TENSILE_ROOT
    if not candidate:
        return _fail("toolchain", "TENSILE_ROOT", "not set",
                     f"Set TENSILE_ROOT in {DOTENV_PATH} or the environment; "
                     "see .env.example and 'oto doctor'.")
    try:
        resolved = require_tensile_root(None, DEFAULT_TENSILE_ROOT)
    except Exception as exc:
        return _fail("toolchain", "TENSILE_ROOT", str(exc),
                     "Point TENSILE_ROOT at a Tensile checkout or a "
                     "rocm-libraries root containing shared/tensile.")
    return _ok("toolchain", "TENSILE_ROOT", str(resolved))


def _rocm() -> Check:
    from oto.runners.toolchain import resolve_rocm_paths
    paths = resolve_rocm_paths()
    missing = [k for k in ("ROCM_PATH", "ROCM_LLVM_BIN", "TENSILE_ASSEMBLER")
               if not paths.get(k)]
    if missing:
        return _fail("toolchain", "ROCm toolchain",
                     "unresolved: " + ", ".join(missing),
                     "Install ROCm or set ROCM_PATH/ROCM_LLVM_BIN explicitly "
                     "in .env; then run 'oto doctor' again.")
    asm = Path(paths["TENSILE_ASSEMBLER"])
    if not asm.is_file():
        return _fail("toolchain", "ROCm assembler", str(asm),
                     "The assembler path does not exist; fix TENSILE_ASSEMBLER.")
    return _ok("toolchain", "ROCm toolchain",
               f"{paths['ROCM_PATH']} (assembler {asm.name})")


def _gpu() -> Check:
    if Path("/dev/kfd").exists() and Path("/dev/dri").exists():
        return _ok("gpu", "GPU device nodes", "/dev/kfd + /dev/dri present")
    rocminfo = shutil.which("rocminfo")
    if not rocminfo:
        return _fail("gpu", "GPU", "no /dev/kfd and no rocminfo",
                     "Benchmarks need a working AMD GPU and ROCm. See 'oto doctor'.")
    ok = subprocess_probe([rocminfo], "gfx")
    if ok:
        return _warn("gpu", "GPU device nodes",
                     "rocminfo sees a GPU but /dev/kfd or /dev/dri is absent",
                     "Check container device passthrough (--device /dev/kfd).")
    return _fail("gpu", "GPU", "rocminfo found no GPU",
                 "Benchmarks need a working AMD GPU; CPU-only checks still run.")


def subprocess_probe(argv: list[str], needle: str) -> bool:
    import subprocess
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    return needle in (proc.stdout or "")


def _profile(base: Path) -> Check:
    import oto.device.peaks as peaks
    path = base / "profiles" / f"{peaks.CODENAME}.json"
    if path.is_file():
        return _ok("toolchain", "Device profile", str(path))
    return _fail("toolchain", "Device profile", f"missing {path}",
                 f"Add profiles/{peaks.CODENAME}.json (see profiles/gfx90c.json).")


def _registry(base: Path) -> list[Check]:
    import oto.device.peaks as peaks
    from oto.runners.paths import results_dir
    results = results_dir(base, peaks.CODENAME)
    db = results / "registry.db"
    out = [_ok("registry", "Results directory", str(results))
           if results.is_dir() else
           _warn("registry", "Results directory", f"missing {results}",
                 "It is created by the first run; 'oto status' will be empty.")]
    if not db.is_file():
        out.append(_fail("registry", "Registry DB", f"missing {db}",
                         "Run a first 'oto benchmark' or restore the corpus; "
                         "then run 'oto check db'."))
        return out
    out.append(_db_health(db))
    out.append(_db_labels(db))
    out.append(_run_health(db))
    return out


def _db_health(db: Path) -> Check:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            records = conn.execute("SELECT count(*) FROM records").fetchone()[0]
            runs = conn.execute("SELECT count(*) FROM runs").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _fail("registry", "Registry DB health", str(exc),
                     "The registry is unreadable. Restore it from backup; "
                     "do not hand-edit it (the ledger is append-only).")
    if not integrity or integrity[0] != "ok":
        return _fail("registry", "Registry DB health", f"integrity={integrity}",
                     "Restore the registry from backup; run 'oto check db'.")
    required = {"records", "runs", "phases"}
    missing = required - tables
    if missing:
        return _fail("registry", "Registry DB schema",
                     "missing tables: " + ", ".join(sorted(missing)),
                     "The schema is created on first use; restore or re-run.")
    return _ok("registry", "Registry DB health",
               f"integrity ok; {records} records, {runs} runs")


def _db_labels(db: Path) -> Check:
    bad = []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for rid, data in conn.execute("SELECT id, data FROM records"):
                try:
                    label = str(json.loads(data).get("label", ""))
                except Exception:
                    continue
                if "auto" in label.lower() or "unknown" in label.lower():
                    bad.append(rid)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _fail("registry", "Registry labels", str(exc),
                     "Run 'oto check db' for the detailed inspector.")
    if bad:
        return _fail("registry", "Registry labels",
                     f"{len(bad)} record(s) carry auto/Unknown labels",
                     "Run 'oto check db' to inspect; do not rewrite history.")
    return _ok("registry", "Registry labels", "no auto/Unknown contamination")


def _run_health(db: Path) -> Check:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT run_id, status FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _warn("registry", "Latest run", str(exc),
                     "Run 'oto status' for a readable view.")
    if not row:
        return _warn("registry", "Latest run", "no runs recorded",
                     "Start with 'oto tune' (or 'oto bench').")
    run_id, status = row
    if status in ("completed", "interrupted"):
        return _ok("registry", "Latest run", f"{run_id} ({status})")
    return _warn("registry", "Latest run", f"{run_id} ({status})",
                 "A run that never finished can block a naive resume; "
                 "inspect it with 'oto status'.")


def _coverage(base: Path) -> Check:
    phases = base / "phases.yaml"
    if not phases.is_file():
        return _fail("corpus", "phases.yaml", f"missing {phases}",
                     "Restore phases.yaml from the repository.")
    try:
        from oto.tensile.library_parity import load_pipeline_phases, parity_report
        report = parity_report(load_pipeline_phases(base))
    except Exception as exc:
        return _fail("corpus", "Coverage parity", f"{type(exc).__name__}: {exc}",
                     "Run 'oto check library-parity' for the detailed report.")
    detail = (f"{report['deck_cells']}/{report['shipped_cells']} shipped cells "
              f"({len(report['missing'])} missing, {len(report['extra'])} extra)")
    if report["parity_ok"]:
        return _ok("corpus", "Coverage parity", detail)
    return _fail("corpus", "Coverage parity", detail,
                 "Run 'oto check library-parity' and fix missing/extra cells.")


def _docs(base: Path) -> list[Check]:
    registry = base / "docs" / "README.md"
    index = base / "docs" / "docs_index.json"
    out = []
    out.append(_ok("docs", "Docs registry", str(registry))
               if registry.is_file() else
               _fail("docs", "Docs registry", f"missing {registry}",
                     "Restore docs/README.md; every tracked .md must be registered."))
    if not index.is_file():
        out.append(_warn("docs", "Docs index", f"missing {index}",
                         "Run 'oto agent index' to regenerate it."))
        return out
    try:
        data = json.loads(index.read_text())
        total = int(data.get("total", 0))
    except Exception as exc:
        out.append(_fail("docs", "Docs index", f"{type(exc).__name__}: {exc}",
                         "Run 'oto agent index' to regenerate it."))
        return out
    out.append(_ok("docs", "Docs index", f"{total} documents")
               if total else
               _warn("docs", "Docs index", "index contains no documents",
                     "Run 'oto agent index'."))
    return out


# ------------------------------------------------------------------ render

def _all_checks(base: Path) -> list[Check]:
    checks: list[Check] = [
        _safe("toolchain", "Python >= 3.10", _python),
        _safe("toolchain", "Virtual environment", _venv),
        _safe("toolchain", "Python dependencies", _dependencies),
        _safe("toolchain", ".env", _dotenv),
        _safe("toolchain", "TENSILE_ROOT", _tensile_root),
        _safe("toolchain", "ROCm toolchain", _rocm),
        _safe("gpu", "GPU", _gpu),
        _safe("toolchain", "Device profile", lambda: _profile(base)),
    ]
    checks.extend(_registry(base))
    checks.append(_coverage(base))
    checks.extend(_docs(base))
    return checks


def _registry_one(base: Path) -> list[Check]:
    return _registry(base)


def _docs_one(base: Path) -> list[Check]:
    return _docs(base)


def _flatten(items: list[Any]) -> list[Check]:
    out: list[Check] = []
    for item in items:
        if isinstance(item, Check):
            out.append(item)
        elif isinstance(item, (list, tuple)):
            out.extend(_flatten(list(item)))
        elif item is not None:
            out.append(item)
    return out


def _label(check: Check, quiet: bool) -> str:
    status = check.status
    if status == OK:
        return output.green("[ OK ]")
    if status == WARN:
        return output.yellow("[WARN]")
    return output.red("[FAIL]")


def run(base: Path, *, json_mode: bool = False, quiet: bool = False) -> int:
    """Run every probe and return 0 unless a probe FAILed."""
    checks = _flatten(_all_checks(base))
    failed = sum(1 for c in checks if c.status == FAIL)
    warned = sum(1 for c in checks if c.status == WARN)
    if json_mode:
        print(json.dumps({"ok": failed == 0,
                          "summary": {"ok": len(checks) - failed - warned,
                                      "warn": warned, "fail": failed},
                          "base": str(base),
                          "checks": [c.as_dict() for c in checks]}, indent=2))
        return 1 if failed else 0

    print(f"oto doctor — {base}")
    last_group = None
    for check in checks:
        if check.group != last_group:
            print(f"\n{output.bold(check.group)}")
            last_group = check.group
        if quiet and check.status == OK:
            continue
        line = f"  {_label(check, quiet)} {check.name}"
        if check.detail:
            line += f": {check.detail}"
        print(line)
        if check.hint and check.status != OK:
            print(f"         hint: {check.hint}")
    summary = f"\n{len(checks) - failed - warned} ok, {warned} warning(s), {failed} failure(s)"
    print(output.green(summary) if failed == 0 else output.red(summary))
    if failed:
        print("hint: fix the FAIL lines above; 'oto help <command>' explains each next step.")
    return 1 if failed else 0
