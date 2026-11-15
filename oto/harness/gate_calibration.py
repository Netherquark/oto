#!/usr/bin/env python3
"""Gate calibration: do the launch gates agree with what Tensile actually built?

Owns: the corpus-wide agreement census between the launch gates
(``CandidateGenerator.validate_config`` + ``ldspad_feasible``) and what the runs
actually produced. For every phase whose launch config is on disk it records the
``(built, gate-legal)`` outcome, split into two populations -- native candidates
vs the replayed gfx900 floor -- and surfaces the two work lists that come out of
it:

* **false rejections** -- the gate refused a phase Tensile built (gate too
  strict; the decision rule in ``claude.md`` / docs/gfx90c_tuning_guide.md §13 §R23 is
  that this count is ZERO on our corpus);
* **misses** -- the gate allowed a phase that produced no measurement (gate too
  loose; the work list for a new gate rule).

Does NOT own: the gates themselves (``oto.tensile.gates``), the config the
driver *intended* (the registry -- this reads the compiled launch truth), the
census over the device-truth knob DOMAIN (``oto.tools.deck_review legality``), or
the failure *reason* mining (``oto.harness.failure_triage``).

Public API: main, audit, read_phase_config, measurement_produced.

Why it exists (``claude.md`` §2.0.5, docs/gfx90c_tuning_guide.md §13 §R23): the repo's rule
for landing a gate change -- "only rules with 0 false rejections on the corpus
get implemented" -- was re-derived by hand every time, and a prototype that
measured something else is not a calibration. This is that rule as a tool: run it
after any gate edit and read the ``false-rej`` line.

The config is reconstructed from the phase's own ``configs/phase_*.yaml`` (the
``write_phase_config`` output Tensile received), never the registry intent,
because the gate's whole job is to predict what Tensile is handed. The two maps
the reconstruction needs already have canonical homes and are imported, not
copied: the contraction pattern (``config_writer.TRANSPOSE_MAP``) and the family
label (``library_parity.phase_family``).

CPU only, read-only, never benchmarks.

    python3 -m oto.harness.gate_calibration                  # both populations
    python3 -m oto.harness.gate_calibration --population ours
    python3 -m oto.harness.gate_calibration --json out.json
    python3 -m oto.harness.gate_calibration --fail-on-false-reject
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from oto import yaml_cached as yamlio

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


from oto.device import loader as _loader
from oto.runners.result_paths import runs_dir as _runs_dir
from oto.tensile.config_writer import TRANSPOSE_MAP
from oto.tensile.library_parity import phase_family

#: Transpose pair -> contraction pattern; the inverse of the writer's own map, so
#: the two cannot drift (``config_writer.TRANSPOSE_MAP`` stays the one home).
_PATTERN_BY_TRANSPOSE = {v: k for k, v in TRANSPOSE_MAP.items()}

#: Dtype char -> fallback family label when the phase id carries no family token.
_FAMILY_BY_CHAR = {"S": "SS", "D": "DD", "H": "HH", "Z": "ZZ", "C": "CC"}

#: The sections of a BenchmarkProblems body that carry single-value fork knobs.
_BODY_SECTIONS = ("BenchmarkCommonParameters", "ForkParameters",
                  "BenchmarkFinalParameters")


def _first(value: Any) -> Any:
    """Unwrap one bind level (``[[4, 4]]`` -> ``[4, 4]``), else pass through."""
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _tile_str(value: Any) -> Any:
    """A tile/workgroup list -> the ``"MxN"`` string the gates parse.

    A list whose entries are not integers (e.g. ``["NONE"]``) is returned
    unchanged, so :func:`_tile_parses` can reject it rather than this raising.
    """
    if isinstance(value, (list, tuple)):
        try:
            return "x".join(str(int(x)) for x in value)
        except (TypeError, ValueError):
            return value
    return value


def _tile_parses(value: Any) -> bool:
    """True when a tile is numeric ``MxN[ xD]`` (a dim the gates can model).

    A fork value that is present but not numeric (a placeholder like ``"NONE"``)
    is unmodellable: the gates' ``tile_dims``/``_load_geometry`` would fail
    closed, so this phase must be *excluded* from the census rather than counted
    as gate-legal. Prefixes the gates strip (``MT``/``SB_``/``HB_``/``DB_``) are
    stripped here too, so the two agree on what a tile is.
    """
    clean = str(value).upper()
    for prefix in ("MT", "SB_", "HB_", "DB_"):
        clean = clean.replace(prefix, "")
    parts = re.split(r"[xX]", clean)
    if len(parts) < 2:
        return False
    for part in parts:
        try:
            int(part)
        except ValueError:
            return False
    return True


def read_phase_config(path: Path, phase_id: str) -> dict[str, Any] | None:
    """A gate-ready config from a phase's own ``configs/phase_*.yaml``.

    Returns the config dict ``validate_config`` / ``ldspad_feasible`` expect:
    the fork knobs (tiles as ``"MxN"`` strings), the problem dtype, the
    contraction pattern and the family label. ``None`` when the yaml is missing
    or has no BenchmarkProblems block.
    """
    try:
        doc = yamlio.load_yaml(Path(path))
        pt, body = doc["BenchmarkProblems"][0][0], doc["BenchmarkProblems"][0][1]
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None

    cfg: dict[str, Any] = {}
    for section in _BODY_SECTIONS:
        for entry in (body.get(section) or []):
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if key != "ProblemSizes":
                    cfg[key] = _first(value)
    for key in ("MacroTile", "ThreadTile", "WorkGroup"):
        if cfg.get(key) is not None:
            cfg[key] = _tile_str(cfg.get(key))
    for key in ("MacroTile", "ThreadTile"):
        value = cfg.get(key)
        if value is not None and not _tile_parses(value):
            # Present but unmodellable (e.g. a "NONE" placeholder): the gates
            # cannot judge it, so the census must exclude it, not call it legal.
            return None

    cfg["DataType"] = str(pt.get("DataType", "s")).upper()
    if pt.get("HighPrecisionAccumulate"):
        cfg["HighPrecisionAccumulate"] = True
    cfg["ContractionPattern"] = _PATTERN_BY_TRANSPOSE.get(
        (bool(pt.get("TransposeA")), bool(pt.get("TransposeB"))), "Ailk_Bjlk")
    cfg["FamilyLabel"] = (
        phase_family({"phase_id": phase_id})
        or _FAMILY_BY_CHAR.get(cfg["DataType"], ""))
    cfg.setdefault("KernelLanguage", "Assembly")
    return cfg


def measurement_produced(phase_dir: Path) -> bool:
    """True when a phase left a non-empty benchmark CSV (i.e. Tensile built it)."""
    data = Path(phase_dir) / "2_BenchmarkData"
    if not data.is_dir():
        return False
    return any(p.stat().st_size > 0 for p in data.glob("*.csv"))


def _empty_population() -> dict[str, Any]:
    return {"phases": 0, "built": 0, "confusion": {}, "false_rejections": [],
            "misses": []}


def population_of(run_name: str) -> str:
    """Native candidate vs the replayed gfx900 floor (matching kernel_db).

    Public because the corpus censuses (``gate_calibration``,
    ``rule_calibration``) must split the same way.
    """
    return "reference" if run_name.startswith(f"{_loader.spoof_prefix()}_ref") else "ours"


def audit(base: str = ".", families: Sequence[str] | None = None, profile=None) -> dict[str, Any]:
    """Classify every phase with a launch config against the gates.

    Args:
        base: Repo root holding the runs directory.
        families: When given, keep only phases whose resolved family is listed.

    Returns:
        ``{"meta": {...}, "populations": {"ours"|"reference": {...}}}``; each
        population carries the confusion counts and the two named work lists.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    from oto.tensile.candidate import CandidateGenerator
    from oto.tensile.gates.occupancy import ldspad_feasible

    runs_dir = _runs_dir(base, _loader.resolve_profile(profile,).codename)
    gen = CandidateGenerator(Path(base))
    want = {f.upper() for f in families} if families else None

    populations = {"ours": _empty_population(),
                   "reference": _empty_population()}
    meta = {"tool": "harness.gate_calibration", "base": str(base),
            "runs": 0, "phases": 0, "with_config": 0, "no_config": 0,
            "filtered_out": 0}

    for run in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        meta["runs"] += 1
        pop = populations[population_of(run.name)]
        cfg_dir = run / "configs"
        for phase_dir in sorted(d for d in run.iterdir()
                                if d.is_dir() and d.name.startswith("phase")):
            meta["phases"] += 1
            cfg = read_phase_config(cfg_dir / f"phase_{phase_dir.name}.yaml",
                                    phase_dir.name)
            if cfg is None:
                meta["no_config"] += 1
                continue
            if want is not None and str(cfg.get("FamilyLabel", "",)).upper() not in want:
                meta["filtered_out"] += 1
                continue
            meta["with_config"] += 1

            built = measurement_produced(phase_dir)
            ok, why = gen.validate_config(cfg,)
            if ok:
                ok, why = ldspad_feasible(cfg,)

            pop["phases"] += 1
            pop["built"] += int(built)
            key = f"built={built} gate={bool(ok)}"
            pop["confusion"][key] = pop["confusion"].get(key, 0,) + 1
            if built and not ok:
                pop["false_rejections"].append(
                    {"phase": phase_dir.name, "run": run.name, "reason": why})
            elif not built and ok:
                pop["misses"].append(
                    {"phase": phase_dir.name, "run": run.name, "reason": "no CSV"})
    return {"meta": meta, "populations": populations}


def _report(name: str, pop: dict[str, Any], limit: int) -> None:
    conf = pop["confusion"]
    print(f"\n{name}   phases={pop['phases']}  built={pop['built']}")
    cells = [
        (True, True, "agree: Tensile built it, gate allowed it"),
        (False, False, "agree: no measurement, gate refused it"),
        (False, True, "MISS: no measurement, gate allowed it (work list)"),
        (True, False, "FALSE REJECTION: Tensile built it, gate refused it"),
    ]
    for built, ok, label in cells:
        n = conf.get(f"built={built} gate={ok}", 0)
        flag = ""
        if built and not ok:
            flag = "  <-- the decision rule: must be 0" if n else "  ok"
        print(f"  {n:6}  {label}{flag}")

    for tag, rows in (("misses", pop["misses"]),
                      ("false rejections", pop["false_rejections"])):
        if not rows:
            continue
        print(f"  {tag} ({len(rows)}):")
        for r in rows[:limit]:
            print(f"    {r['run']}/{r['phase'][:56]:56} {r['reason'][:48]}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", "--base-dir", dest="base", default=str(_HERE), help="repo root (default: repo)")
    ap.add_argument("--population", choices=("ours", "reference", "all"),
                    default="all", help="which corpus population to report")
    ap.add_argument("--family", action="append", default=None,
                    help="restrict to a family label (repeatable)")
    ap.add_argument("--limit", type=int, default=8,
                    help="rows to show from each work list (default 8)")
    ap.add_argument("--json", type=Path, default=None, help="write the census here")
    ap.add_argument("--fail-on-false-reject", action="store_true",
                    help="exit 1 when the 'ours' population has a false rejection")
    args = ap.parse_args(argv)

    result = audit(args.base, args.family)
    meta = result["meta"]
    print(f"gate calibration -- {meta['base']}")
    print(f"  {meta['runs']} runs, {meta['phases']} phases, "
          f"{meta['with_config']} with a launch config "
          f"({meta['no_config']} without"
          + (f", {meta['filtered_out']} filtered by --family"
             if meta["filtered_out"] else "") + ")")

    shown = (("ours", "reference") if args.population == "all"
             else (args.population,))
    labels = {"ours": "OURS (native candidates)",
              "reference": "REFERENCE (gfx900 replay)"}
    for pop_name in shown:
        _report(labels[pop_name], result["populations"][pop_name], args.limit)

    if args.json:
        args.json.write_text(json.dumps(result, indent=1))

    if args.fail_on_false_reject and result["populations"]["ours"]["false_rejections"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
