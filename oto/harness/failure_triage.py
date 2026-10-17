#!/usr/bin/env python3
"""Failed-candidate triage: which phases produced nothing, and why.

Owns: the corpus-wide census of phases that produced no benchmark CSV, and the
reason the run recorded for each -- Tensile's own ``reject:`` lines, a non-empty
stderr, or an empty log -- bucketed per run. This is the "every failed candidate
in every run directory" triage (potential_configs.md §R23), as a tool instead
of a one-off script.

Does NOT own: whether the *gates* should have predicted the failure
(``oto.harness.gate_calibration``), the per-phase M1/M2/M3 failure taxonomy
(potential_configs.md §2), or the run status / telemetry
(``oto.metrics.run_status``).

Public API: main, census, reason_for_phase, measurement_produced.

CPU only, read-only, never benchmarks.

    python3 -m oto.harness.failure_triage                  # all runs
    python3 -m oto.harness.failure_triage --run run_20261017_092909
    python3 -m oto.harness.failure_triage --json out.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

#: Tensile's reject lines in a phase's stdout.log look like
#: "rejecting solution: ..." or "reject: ...".
_REJECT = re.compile(r"reject(?:ing solution)?:?\s*(.+)")


def measurement_produced(phase_dir: Path) -> bool:
    """True when a phase left a non-empty benchmark CSV."""
    data = Path(phase_dir) / "2_BenchmarkData"
    if not data.is_dir():
        return False
    return any(p.stat().st_size > 0 for p in data.glob("*.csv"))


def reason_for_phase(phase_dir: Path) -> str:
    """The recorded reason a phase produced no measurement.

    Prefers Tensile's own ``reject:`` lines (counted, most-common wins), then a
    non-empty stderr, then the stdout tail, then ``"no logs at all"``.
    """
    phase_dir = Path(phase_dir)
    cands: collections.Counter = collections.Counter()
    stderr_first = None
    stdout_tail = None
    for name in ("stdout.log", "stderr.log"):
        log = phase_dir / name
        if not log.is_file():
            continue
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = _REJECT.search(line)
            if m:
                cands[m.group(1).strip()[:70]] += 1
        if name == "stderr.log" and text.strip() and stderr_first is None:
            stderr_first = "stderr non-empty: " + text.strip().splitlines()[0][:60]
        if name == "stdout.log":
            tail = text.strip().splitlines()
            stdout_tail = "stdout tail: " + (tail[-1][:60] if tail else "<empty>")

    if cands:
        return ("tensile reject x%d: %s"
                % (cands.total(), cands.most_common(1)[0][0]))
    if stderr_first is not None:
        return stderr_first
    if stdout_tail is not None:
        return stdout_tail
    return "no logs at all"


def census(base: str = ".", run_filter: Optional[str] = None,
           sample_limit: int = 12) -> Dict[str, Any]:
    """Walk the run corpus and classify every empty phase.

    Args:
        base: Repo root holding ``gfx90c_runs/``.
        run_filter: When given, only this run directory is scanned.
        sample_limit: How many example empty phases to retain.

    Returns:
        ``{"meta": {...}, "runs": [...], "reasons": {reason: count},
        "samples": [(run, phase, reason)]}``.
    """
    runs_dir = Path(base) / "gfx90c_runs"
    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
    if run_filter is not None:
        run_dirs = [d for d in run_dirs if d.name == run_filter]

    meta = {"tool": "harness.failure_triage", "base": str(base),
            "runs_scanned": 0, "phase_dirs": 0, "empty": 0}
    per_run: List[Dict[str, Any]] = []
    reasons: collections.Counter = collections.Counter()
    samples: List[Tuple[str, str, str]] = []

    for run in run_dirs:
        meta["runs_scanned"] += 1
        phases = sorted(d for d in run.iterdir()
                        if d.is_dir() and d.name.startswith("phase"))
        if not phases:
            continue
        empty = [ph for ph in phases if not measurement_produced(ph)]
        per_run.append({"run": run.name, "phases": len(phases),
                        "empty": len(empty)})
        meta["phase_dirs"] += len(phases)
        meta["empty"] += len(empty)

        for ph in empty:
            why = reason_for_phase(ph)
            reasons[why] += 1
            if len(samples) < sample_limit:
                samples.append((run.name, ph.name, why))

    return {"meta": meta, "per_run": per_run, "reasons": dict(reasons),
            "samples": samples}


def _report(result: Dict[str, Any], top: int) -> None:
    meta = result["meta"]
    print(f"runs scanned: {meta['runs_scanned']}")
    print(f"phase dirs: {meta['phase_dirs']}   with no non-empty CSV: {meta['empty']}")

    print()
    print("runs with any empty phase (name, phases, empty):")
    for r in result["per_run"]:
        if r["empty"]:
            print(f"   {r['run']:44} {r['phases']:4} {r['empty']:4}")

    print()
    print("=" * 78)
    print("Why the empty ones are empty (reason histogram):")
    for reason, count in sorted(result["reasons"].items(),
                               key=lambda kv: -kv[1])[:top]:
        print(f"   {count:4}  {reason}")

    if result["samples"]:
        print()
        print("samples:")
        for run, ph, why in result["samples"][:12]:
            print(f"   {run}/{ph}: {why}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=str(_HERE), help="repo root (default: repo)")
    ap.add_argument("--run", default=None,
                    help="restrict to one run directory name")
    ap.add_argument("--top", type=int, default=25,
                    help="reasons to show (default 25)")
    ap.add_argument("--limit", type=int, default=12,
                    help="sample empty phases to retain (default 12)")
    ap.add_argument("--json", type=Path, default=None, help="write the census here")
    args = ap.parse_args(argv)

    result = census(args.base, args.run, args.limit)
    _report(result, args.top)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
