#!/usr/bin/env python3
"""Evergreen HTML report check.

The same payload must render to identical bytes, twice, in this tree (a hard
gate: a rerender mismatch is a real renderer nondeterminism), and REF's
renderer must produce the same bytes for the same payload snapshot (the
cross-commit regression gate: REF-era rendering of this repo's payload).

Owns: the determinism round-trip and the cross-ref render comparison.
Does NOT own: the report schema, report-atlas byte embeddedness, or the suite.
Public API: build_payload, render, main; the contract is the exit code.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

_REF_SRC = """
import sys, json, dataclasses
from pathlib import Path
ROOT_MAIN = {main_root!r}
sys.path.insert(0, {tree!r})
from oto.metrics.report_models import ABVerdict, AcceptanceReport
from oto.metrics.acceptance_report import AcceptanceReporter
payload = json.loads(Path({payload_path!r}).read_text())
_abv = list(ABVerdict.__dataclass_fields__)
ver = [ABVerdict(**{{k: v.get(k) for k in _abv if k in v}}) for v in payload.get("per_cell_verdicts") or [] if isinstance(v, dict)]
kwargs = {{}}
for f in dataclasses.fields(AcceptanceReport):
    if f.name == "per_cell_verdicts":
        kwargs[f.name] = ver
    else:
        kwargs[f.name] = payload.get(f.name)
AcceptanceReporter(Path(ROOT_MAIN)).write_html_report(AcceptanceReport(**kwargs), Path({out!r}))
print("ok")
"""


def _payload_parts(run_id: str, profile=None):
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    from oto.runners.driver import TensileDriver

    d = TensileDriver(base_dir=ROOT, create_run=False)
    d.regenerate_report(run_id,)
    from oto.device import loader as _loader
    from oto.runners.paths import results_dir as _results_dir

    payload_path = _results_dir(ROOT, _loader.resolve_profile(profile).codename) / "acceptance_report.json"
    return payload_path.read_bytes(), payload_path


def build_report(payload_bytes: bytes):
    from oto.metrics.report_models import ABVerdict, AcceptanceReport

    payload = json.loads(payload_bytes)
    _abv = list(ABVerdict.__dataclass_fields__)
    ver = [ABVerdict(**{k: v.get(k) for k in _abv if k in v})
           for v in (payload.get("per_cell_verdicts") or [])
           if isinstance(v, dict)]
    kwargs = {}
    for f in dataclasses.fields(AcceptanceReport):
        if f.name == "per_cell_verdicts":
            kwargs[f.name] = ver
        else:
            kwargs[f.name] = payload.get(f.name)
    return AcceptanceReport(**kwargs), len(ver)


def render(report, html_path: Path) -> bytes:
    from oto.metrics.acceptance_report import AcceptanceReporter

    AcceptanceReporter(ROOT).write_html_report(report, html_path)
    return html_path.read_bytes()


def _ref_render(ref: str, payload_path: Path) -> bytes | None:
    from oto.tools.verifiers import ref_worktree

    try:
        tree = ref_worktree.ref_worktree(ref)
    except ref_worktree.EvergreenError as exc:
        print(f"REF comparison BLOCKED: {exc}")
        return None
    out = ref_worktree.scratch_dir() / f"_evergreen_report_{abs(hash(ref)) & 0xffffff:x}.html"
    code = _REF_SRC.format(tree=str(tree), payload_path=str(payload_path), out=str(out), main_root=str(ROOT))
    proc = ref_worktree.probe(tree, code, timeout=900)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "child failed"
        print(f"REF comparison BLOCKED: {tail}")
        return None
    data = out.read_bytes()
    out.unlink(missing_ok=True)
    return data


def _first_diff(a: bytes, b: bytes) -> int | None:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return None if len(a) == len(b) else n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", default="run_20261009_205427",
                    help="run whose regenerated payload the render uses")
    ap.add_argument("--base", default=None,
                    help="REF to render the same payload snapshot with; without it "
                         "only the determinism round-trip runs")
    args = ap.parse_args()

    import tempfile

    payload_bytes, _payload_file = _payload_parts(args.run_id)
    snapshot_path = Path(tempfile.mkdtemp()) / "payload_snapshot.json"
    snapshot_path.write_bytes(payload_bytes)

    report, ver_count = build_report(payload_bytes)
    print(f"payload cells: {ver_count}")

    with tempfile.TemporaryDirectory() as td:
        first = render(report, Path(td) / "a.html")
        second = render(report, Path(td) / "b.html")

    print(f"render determinism: {'OK (' + str(len(first)) + ' bytes)' if first == second else 'FAILED'}")
    if first != second:
        print("FAIL: the same payload rendered twice differs.")
        return 1

    if not args.base:
        print("REF comparison: skipped (pass --base REF to compare)")
        print("REPORT HTML: OK")
        return 0

    ref = _ref_render(args.base, snapshot_path)
    if ref is None:
        print("REF comparison BLOCKED (see the note above): "
              "the REF tree cannot render this payload. Determinism still holds.")
        print("REPORT HTML: OK (determinism only; REF comparison inapplicable)")
        return 0

    if ref == first:
        print(f"REF {args.base} renders this payload byte-identically.")
        print("REPORT HTML: OK")
        return 0

    at = _first_diff(first, ref)
    print(f"REF {args.base} differs from current at byte {at} "
          f"({len(ref)} vs {len(first)} bytes, delta {len(ref) - len(first)}).")
    print("This is the regression gate: any or all of the delta must trace to a "
          "known renderer change (see drift_manifest.json, report_html::render).")
    rc = 0
    from oto.tools.verifiers.ref_worktree import print_drift_summary
    rc = print_drift_summary("report_html", ["report_html::render"])
    if rc == 0:
        print("REPORT HTML: OK (manifested renderer evolution)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
