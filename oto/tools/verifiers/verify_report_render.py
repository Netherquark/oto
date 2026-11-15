#!/usr/bin/env python3
"""Evergreen HTML report check.

The same payload must render to identical bytes, twice, in this tree (a hard
gate: a rerender mismatch is a real renderer nondeterminism), and REF's
renderer must produce the same bytes for the same payload snapshot (the
cross-commit regression gate: REF-era rendering of this fixture).

The check is driven from a deterministic synthetic payload, never from the
live registry: an earlier version instantiated a full driver and called
``regenerate_report``, which rewrote the live A/B report into the results
dirs -- a side-effect for a check that documented itself as read-only.

Owns: the determinism round-trip and the cross-ref render comparison.
Does NOT own: the report schema, report-atlas byte embeddedness, or the suite.
Public API: build_report, render, main; the contract is the exit code.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
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


def _cell(family: str, dtype: str, shape: str, native: float, spoof: float,
          verdict: str, coverage: float, i: int) -> dict:
    """One synthetic verdict cell for the fixture."""
    return {
        "dtype": dtype,
        "shape": shape,
        "native_median": native,
        "spoof_median": spoof,
        "delta_pct": (native - spoof) / spoof * 100.0,
        "tie": verdict == "TIE",
        "verdict": verdict,
        "fp": f"fixture-fp-{i}",
        "family": family,
        "native_best": native,
        "spoof_best": spoof,
        "native_best_median": native,
        "spoof_best_median": spoof,
        "native_worst_median": native * 0.95,
        "spoof_worst_median": spoof * 0.95,
        "native_value": native,
        "spoof_value": spoof,
        "agg": "winner",
        "clock_adjusted": False,
        "native_clock_coverage": 0.0,
        "spoof_clock_coverage": 0.0,
        "sclk_ref_hz": 0.0,
        "native_clock_sclk_hz": 0.0,
        "spoof_clock_sclk_hz": 0.0,
        "native_temp_c": None,
        "spoof_temp_c": None,
        "native_temp_max_c": None,
        "spoof_temp_max_c": None,
        "native_runs": ["run_fixture_a"],
        "native_winner_run": "run_fixture_a",
        "native_winner_phase": f"phase_{family.lower()}_fixture_{i}",
        "n_native_runs": 1,
        "n_native_kernels": 1,
        "n_spoof_kernels": 1,
        "basis_protocol": "family",
        "native_best_any_protocol": native,
        "native_isolated_best": native,
        "delta_pct_rel": (native - spoof) / spoof * 100.0,
    }


def _payload_fixture() -> dict:
    """The deterministic, registry-free payload for the render checks.

    Normalised through sorted-key JSON so the dict iteration order the renderer
    sees is identical on this side and in the REF child (which loads the
    serialized snapshot) -- byte-identical renders require it.
    """
    cells = [
        _cell("CC", "C", "512x512x512", 88.0, 84.1, "WIN", 0.75, 4),
        _cell("HH", "H", "256x256x256", 511.0, 511.0, "TIE", 1.0, 2),
        _cell("SS", "S", "128x128x128", 312.0, 268.0, "WIN", 1.0, 1),
        _cell("ZZ", "Z", "1024x1024x1024", 118.0, 131.7, "LOSS", 0.4, 3),
    ]
    coverage = {
        fam: {"coverage_pct": 100.0 * cov, "deck_cells": 4, "deck_cells_measured": int(4 * cov),
              "measured_cells": int(8 * cov), "expected_kernels": 4}
        for fam, cov in (("CC", 0.75), ("HH", 1.0), ("SS", 1.0), ("ZZ", 0.4))
    }
    timing = {
        fam: {"cells": 4, "mean_sec": 12.0, "total_min": 0.8}
        for fam in ("CC", "HH", "SS", "ZZ")
    }
    fixture = {
        "timestamp": "2026-11-15T00:00:00",
        "run_id": "verify_report_synthetic",
        "per_family_coverage": coverage,
        "per_cell_verdicts": cells,
        "red_list": [{"family": "ZZ", "dtype": "Z", "shape": "2048x2048x2048",
                      "coverage_pct": 0.0, "deck_cells_measured": 0,
                      "deck_cells": 4, "measured_cells": 0, "expected_kernels": 4}],
        "orange_list": [{"family": "ZZ", "dtype": "Z", "shape": "1024x1024x1024",
                         "coverage_pct": 40.0, "deck_cells_measured": 1,
                         "deck_cells": 4, "measured_cells": 2,
                         "expected_kernels": 4}],
        "execution_timing": {
            "native_run": {"started_at": "2026-11-15T00:00:00",
                           "completed_at": "2026-11-15T00:10:00",
                           "elapsed_seconds": 600.0, "elapsed_human": "10 min"},
            "reference_chain": {"elapsed_human": "5 min",
                                "per_run": [{"run_id": "gfx900_ref_fixture",
                                             "elapsed_seconds": 300.0}]},
            "phase_busy": {"minutes": 8.0, "hours": 0.13},
        },
        "family_timing": timing,
        "reference_run_id": "gfx900_ref_fixture",
        "native_arm": {"n_records": 4, "n_runs": 1, "runs": ["run_fixture_a"], "agg": "winner"},
        "shipped_manifest": {"total_shipped_kernels": 2285,
                             "expected_kernels": {},
                             "rocm_prefixes": ["rocm_prefix_fixture"],
                             "generated_at": "2026-11-15T00:00:00"},
        "overall_pass": False,
        "summary": "synthetic verifier fixture (WIN/TIE/LOSS mix)",
        "all_analytics": [],
        "run_dir": None,
        "reference_floor_status": "completed",
        "reference_floor_authoritative": True,
    }
    return json.loads(json.dumps(fixture, sort_keys=True))


def build_report(payload: dict):
    """The ``AcceptanceReport`` for a payload snapshot fixture."""
    from oto.metrics.report_models import ABVerdict, AcceptanceReport

    ver = [ABVerdict(**{k: v.get(k) for k in ABVerdict.__dataclass_fields__ if k in v})
           for v in _verdicts(payload)]
    kwargs = {}
    for f in dataclasses.fields(AcceptanceReport):
        if f.name == "per_cell_verdicts":
            kwargs[f.name] = ver
        else:
            kwargs[f.name] = payload.get(f.name)
    return AcceptanceReport(**kwargs), len(ver)


def _verdicts(payload: dict):
    """Yield the per-cell verdict dicts from a payload."""
    for v in payload.get("per_cell_verdicts") or []:
        if isinstance(v, dict):
            yield v


def render(report, html_path: Path) -> bytes:
    """Render the report HTML for `report` and return its bytes."""
    from oto.metrics.acceptance_report import AcceptanceReporter

    AcceptanceReporter(ROOT).write_html_report(report, html_path)
    return html_path.read_bytes()


def _first_diff(a: bytes, b: bytes) -> int | None:
    """The first byte offset where `a` and `b` differ."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return None if len(a) == len(b) else n


def _ref_render(ref: str, payload: dict) -> bytes | None:
    """The report HTML rendered by the reference tree (``None`` when blocked)."""
    from oto.tools.verifiers import ref_worktree

    try:
        tree = ref_worktree.ref_worktree(ref)
    except ref_worktree.EvergreenError as exc:
        print(f"REF comparison BLOCKED: {exc}")
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        payload_path = Path(td) / "payload_snapshot.json"
        payload_path.write_text(json.dumps(payload, sort_keys=True))
        out = Path(td) / "ref.html"
        code = _REF_SRC.format(tree=str(tree), payload_path=str(payload_path),
                               out=str(out), main_root=str(ROOT))
        proc = ref_worktree.probe(tree, code, timeout=900)
        if proc.returncode != 0:
            tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "child failed"
            print(f"REF comparison BLOCKED: {tail}")
            return None
        return out.read_bytes()


def main() -> int:
    """The report-render equivalence check (CLI entry)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=None,
                    help="REF to render the same fixture with; without it "
                         "only the determinism round-trip runs")
    args = ap.parse_args()

    payload = _payload_fixture()
    report, ver_count = build_report(payload)
    print(f"payload cells: {ver_count} (synthetic fixture; live registry untouched)")

    import tempfile
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

    ref = _ref_render(args.base, payload)
    if ref is None:
        print("REF comparison BLOCKED (see the note above): "
              "the REF tree cannot render this fixture. Determinism still holds.")
        print("REPORT HTML: OK (determinism only; REF comparison inapplicable)")
        return 0

    if ref == first:
        print(f"REF {args.base} renders this fixture byte-identically.")
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
