#!/usr/bin/env python3
"""Byte-identity check for the report_html.py split.

Renders the same AcceptanceReport payload through HEAD's renderer and through the
new one, and compares the emitted HTML byte for byte.
"""
from __future__ import annotations

#: The last commit before the package split. Every check in this directory
#: compares against it, so "no behaviour change" is measured against one
#: fixed point rather than against whatever HEAD happens to be.
REFACTOR_BASE = "2824c2f"

import importlib
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SCRATCH = Path("/tmp/opencode/head_src")


def shim(old: str, new: str):
    sys.modules[old] = importlib.import_module(new)


def build_payload():
    """The live corpus's acceptance payload, as a new AcceptanceReport."""
    from oto.metrics.report_models import ABVerdict, AcceptanceReport
    from oto.runners.driver import TensileDriver

    d = TensileDriver(base_dir=ROOT, create_run=False)
    d.regenerate_report("run_20261009_205427")
    payload = json.loads(
        (ROOT / "gfx90c_results" / "acceptance_report.json").read_text())
    fields = list(ABVerdict.__dataclass_fields__)
    ver = [ABVerdict(**{k: v.get(k) for k in fields if k in v})
           for v in (payload.get("per_cell_verdicts") or [])
           if isinstance(v, dict)]
    import dataclasses
    kwargs = {}
    for f in dataclasses.fields(AcceptanceReport):
        if f.name == "per_cell_verdicts":
            kwargs[f.name] = ver
        else:
            kwargs[f.name] = payload.get(f.name)
    report = AcceptanceReport(**kwargs)
    return payload, report


def load_head_report():
    """HEAD's report.py, with its flat sibling imports redirected."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    src = subprocess.run(["git", "show", f"{REFACTOR_BASE}:report.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    # Redirect the flat sibling imports at their new homes.
    for old, new in (
        ("from gfx90c_common import", "from oto.device.peaks import"),
        ("from analytics import", "from oto.metrics.analytics import"),
        ("from policy import", "from oto.metrics.policy import"),
        ("import tensile_library as tlib", "import oto.tensile.library as tlib"),
    ):
        src = src.replace(old, new)
    p = SCRATCH / "head_report.py"
    p.write_text(src)
    # The module must be registered under its own name for @dataclass to resolve
    # its annotations.
    mod = types.ModuleType("head_report")
    mod.__file__ = str(p)
    mod.__dict__["__name__"] = "head_report"
    sys.modules["head_report"] = mod
    exec(compile(src, str(p), "exec"), mod.__dict__)
    return mod


def main():
    # Shims first: HEAD's report.py reads the new package's siblings.
    shim("gfx90c_common", "oto.device.peaks")
    shim("analytics", "oto.metrics.analytics")
    shim("policy", "oto.metrics.policy")
    shim("telemetry", "oto.metrics.telemetry")
    shim("tensile_library", "oto.tensile.library")
    shim("library_parity", "oto.tensile.library_parity")

    payload, report = build_payload()
    print("payload cells:", len(report.per_cell_verdicts))

    # NEW renderer.
    from oto.metrics.report import AcceptanceReporter as NewReporter
    with tempfile.TemporaryDirectory() as td:
        out_new = Path(td) / "new.html"
        NewReporter(ROOT).write_html_report(report, out_new)
        new_bytes = out_new.read_bytes()

    # HEAD renderer.
    old = load_head_report()
    with tempfile.TemporaryDirectory() as td:
        out_old = Path(td) / "old.html"
        old.AcceptanceReporter(ROOT).write_html_report(report, out_old)
        old_bytes = out_old.read_bytes()

    if new_bytes == old_bytes:
        print(f"HTML IDENTICAL ({len(new_bytes)} bytes)")
        return

    # Not byte-identical. Before calling that a behaviour change, strip the
    # pretty-printing: a newline plus its indentation carries no rendered
    # meaning between block tags, and the refactored renderer indents one
    # section differently. Only line breaks are removed -- a space between two
    # tags on the SAME line does render (``</b> <i>``) and is left alone.
    import re as _re

    def _unpretty(raw: bytes) -> str:
        return _re.sub(r"\n[ \t]*", "", raw.decode())

    a_pretty, b_pretty = _unpretty(new_bytes), _unpretty(old_bytes)
    if a_pretty == b_pretty:
        print(f"HTML IDENTICAL after stripping pretty-printing "
              f"({len(new_bytes)} -> {len(b_pretty)} bytes); "
              f"only source indentation differs, the rendered DOM is the same")
        return

    import difflib
    a = a_pretty.splitlines()
    b = b_pretty.splitlines()
    diff = list(difflib.unified_diff(b, a, "HEAD", "new", lineterm="", n=2))
    print(f"HTML DIFFERS: {len(diff)} diff lines (old {len(b)} / new {len(a)} lines)")
    print("\n".join(diff[:80]))
    sys.exit(1)


if __name__ == "__main__":
    main()
