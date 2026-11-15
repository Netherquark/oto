#!/usr/bin/env python3
"""Rule calibration: would a *proposed* gate rule add false rejections?

A candidate rule is any ``config -> Optional[bool]`` predicate: ``True`` means
"would refuse this config", ``False`` "would allow it", ``None`` "not
applicable" (the gates' cannot-model convention). This tool applies one to every
phase whose launch config is on disk and reports the decision-rule confusion:
how many phases Tensile BUILT the rule would wrongly refuse (false rejections --
the docs require **0** before a rule may land, ``claude.md`` §5) and how many
empty (no-measurement) phases it catches, broken down by family.

It formalises the throwaway probes that derived the 2026-10-18 rules (the
workgroup register file, the LSU LDS-reduction buffer) and the ``NumThreads``
budget candidate that was probed and **rejected** (it adds one false rejection).
Ship a candidate here, read ``false-rejections``, then implement it in the gate.

Owns: probing an arbitrary candidate rule against the corpus, and the
``builtin_rules`` registry (the shipped rules as *views* of the gate, plus the
rejected ``nt_budget`` counter-example).

Does NOT own: the implemented rules (```oto.tensile.gates.occupancy``` /
```oto.tensile.gates.loads``` / ```oto.tensile.candidate```), the whole-gate census
```oto.harness.gate_calibration```, or the rule under test -- the caller supplies
it, as a builtin name or ``--rule module:attr``.

Public API: Rule, probe, builtin_rules, load_rule, main.

CPU only, read-only, never benchmarks.

    python3 -m `oto.harness.rule_calibration`                    # every builtin
    python3 -m `oto.harness.rule_calibration` --rule nt_budget
    python3 -m `oto.harness.rule_calibration` --rule myrules.py:refuse_wide --json out.json
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.device import loader as _loader
from oto.harness.gate_calibration import (
    measurement_produced,
    population_of,
    read_phase_config,
)
from oto.runners.result_paths import runs_dir as _runs_dir

#: A candidate rule. ``True`` = would refuse the config, ``False`` = would allow
#: it, ``None`` = not applicable (cannot model; excluded from the census).
Rule = Callable[[dict[str, Any]], bool | None]


def _iter_rows(base: str, families: Sequence[str] | None, profile=None):
    """Yield ``(population, run, family, phase, cfg, built)`` per phase.

    One row per ``phase*`` dir whose ``configs/phase_<name>.yaml`` reconstructs
    and whose resolved family survives ``families``. The reconstruction
    (``read_phase_config``) and the measurement test
    (``measurement_produced``) are imported from ``gate_calibration`` so both
    censuses see exactly the same corpus.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    want = {f.upper() for f in families} if families else None
    runs_dir = _runs_dir(base, _loader.resolve_profile(profile,).codename)
    for run in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        cfg_dir = run / "configs"
        for phase_dir in sorted(d for d in run.iterdir()
                                if d.is_dir() and d.name.startswith("phase")):
            cfg = read_phase_config(cfg_dir / f"phase_{phase_dir.name}.yaml",
                                    phase_dir.name)
            if cfg is None:
                continue
            family = str(cfg.get("FamilyLabel", "",)).upper()
            if want is not None and family not in want:
                continue
            yield (population_of(run.name), run.name, family, phase_dir.name,
                   cfg, measurement_produced(phase_dir))


def _new_population() -> dict[str, Any]:
    """A zeroed confusion-count dict for one population (ours or reference)."""
    return {"applicable": 0, "built": 0, "not_applicable": 0, "agrees": 0,
            "allowed_empty": 0, "false_rejections": [], "catches": [],
            "caught_by_family": {}}


def _classify(pop: dict[str, Any], verdict: bool | None, built: bool,
              row: dict[str, str]) -> None:
    """Bucket one phase: refuse/allow crossed with built/empty."""
    if verdict is None:
        pop["not_applicable"] += 1
        return
    pop["applicable"] += 1
    pop["built"] += int(built)
    if verdict and built:
        pop["false_rejections"].append(row)
    elif verdict:
        pop["catches"].append(row)
        pop["caught_by_family"][row["family"]] = (
            pop["caught_by_family"].get(row["family"], 0) + 1)
    elif built:
        pop["agrees"] += 1
    else:
        pop["allowed_empty"] += 1


def probe(rule: Rule, name: str = "rule", base: str = ".",
          families: Sequence[str] | None = None) -> dict[str, Any]:
    """Apply one candidate rule to the corpus and count the confusion.

    `rule` is a ``config -> Optional[bool]`` (``True`` = would refuse);
    `name` labels the report / JSON; `base` is the repo root holding the
    runs directory; `families` keeps only phases whose resolved family is
    listed.

    Returns ``{"meta": {...}, "populations": {"ours"|"reference": {...}}}``;
    each population carries ``applicable``/``built``/``not_applicable``, the
    ``false_rejections`` (would-refuse + built) and ``catches``
    (would-refuse + empty) work lists, the ``agrees``/``allowed_empty``
    counts, and ``caught_by_family``.
    """
    populations = {"ours": _new_population(), "reference": _new_population()}
    meta = {"tool": "harness.rule_calibration", "rule": name, "base": str(base),
            "runs": 0, "with_config": 0}
    seen = set()
    for pop_name, run_name, family, phase, cfg, built in _iter_rows(base, families):
        if run_name not in seen:
            seen.add(run_name)
            meta["runs"] += 1
        meta["with_config"] += 1
        row = {"run": run_name, "phase": phase, "family": family}
        _classify(populations[pop_name], rule(cfg), built, row)
    return {"meta": meta, "populations": populations}


def _refuses_apm2(config: dict[str, Any]) -> bool | None:
    """The generator-seam rule: ``AggressivePerfMode`` outside {0, 1}.

    ``None`` when the knob is absent (the rule does not apply) or unreadable,
    matching ``candidate._non_generative_knob_rejection``.
    """
    apm = config.get("AggressivePerfMode")
    if apm is None:
        return None
    try:
        return int(apm) not in (0, 1)
    except (TypeError, ValueError):
        return None


def _refuses_nt_budget(config: dict[str, Any]) -> bool | None:
    """ADOPTED 2026-10-21: the per-thread occupancy limit (Tensile's error 4).

    ``min(256, 65536 // NumThreads)`` is the budget the EMITTED per-thread
    VGPRs must fit. This was probed and REJECTED on 2026-10-18 because it
    would refuse one phase Tensile built (complex ``Z`` tt2x2 at 64x64,
    NumThreads 1024 -> budget 64 against a "measured 71 VGPRs") -- the 71 was
    wrong: that kernel emits **63** VGPRs (read out of its own code object),
    which fits. With the measured table corrected the rule refuses exactly the
    phases that die: SS 256x128 at tt8x4 (77 VGPRs/thread over 1024
    threads), the 8 phases of run_20261020_214103 that errored out.

    The rule is now a *view* of the shipped gate
    (``gates/occupancy.refuses_per_thread_occupancy_limit``), so the probe and
    the gate cannot drift.
    """
    from oto.tensile.gates.occupancy import refuses_per_thread_occupancy_limit

    return refuses_per_thread_occupancy_limit(config)


def builtin_rules() -> dict[str, Rule]:
    """The rules this project calibrated, as probe-ready predicates.

    ``workgroup_file`` and ``lds_reduction`` are *views* of the shipped gate:
    they call ``occupancy``'s own predicate helpers, so a drift between the rule
    a future agent probes and the rule the gate enforces is impossible.
    ``apm2`` is the generator-seam rule. ``nt_budget`` is the per-thread
    occupancy limit, adopted 2026-10-21 after the measured VGPR table was
    corrected (see ``_refuses_nt_budget``).
    """
    from oto.tensile.gates.occupancy import (
        refuses_lds_reduction_buffer,
        refuses_workgroup_register_file,
    )

    return {"workgroup_file": refuses_workgroup_register_file,
            "lds_reduction": refuses_lds_reduction_buffer,
            "apm2": _refuses_apm2,
            "nt_budget": _refuses_nt_budget}


def _import_file(path: Path) -> Any:
    """Import a standalone ``.py`` file as a module (for ``--rule path.py:attr``)."""
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rule(spec: str) -> Rule:
    """Load a candidate rule from ``module:attr`` or ``path.py:attr``.

    Raises ``SystemExit`` when ``spec`` is not ``...:attr``, the module
    cannot be imported, or the attribute is not callable.
    """
    if ":" not in spec:
        raise SystemExit(
            f"--rule must be a builtin name or module:attr (got {spec!r}); "
            f"builtins: {', '.join(builtin_rules())}")
    mod_part, attr = spec.rsplit(":", 1)
    path = Path(mod_part)
    try:
        module = _import_file(path) if path.suffix == ".py" and path.exists() \
            else importlib.import_module(mod_part)
    except (ImportError, OSError, SyntaxError) as exc:
        raise SystemExit(f"--rule {spec}: cannot import {mod_part!r}: {exc}") from exc
    rule = getattr(module, attr, None)
    if not callable(rule):
        raise SystemExit(f"{spec}: no callable {attr!r}")
    return rule


def _resolve_rules(specs: Sequence[str] | None) -> dict[str, Rule]:
    """Map each requested rule spec to its builtin or loaded rule."""
    builtins = builtin_rules()
    if not specs:
        return builtins
    return {s: builtins[s] if s in builtins else load_rule(s) for s in specs}


def _report(label: str, pop: dict[str, Any], limit: int) -> None:
    """Print one population's confusion table and its first `limit` false rejections."""
    n_fr = len(pop["false_rejections"])
    flag = "  ok" if n_fr == 0 else "  <-- the decision rule: must be 0"
    print(f"  {label}   applicable={pop['applicable']}  built={pop['built']}  "
          f"not-applicable={pop['not_applicable']}")
    print(f"    would-refuse BUILT (FALSE REJECTION): {n_fr:6}{flag}")
    print(f"    would-refuse empty (caught)         : {len(pop['catches']):6}")
    print(f"    would-allow  built (agree)          : {pop['agrees']:6}")
    print(f"    would-allow  empty (missed)         : {pop['allowed_empty']:6}")
    if pop["caught_by_family"]:
        fams = ", ".join(f"{k} {v}"
                         for k, v in sorted(pop["caught_by_family"].items()))
        print(f"    caught by family: {fams}")
    for _r in pop["false_rejections"][:limit]:
        print(f"    FALSE REJECTION: {_r['run']}/{_r['phase']} ({_r['family']})")


def main(argv: Sequence[str] | None = None) -> int:
    """Probe candidate legality rules against the corpus (CLI entry)."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rule", action="append", default=None,
                    help="builtin name or module:attr (repeatable; default: all "
                         "builtins)")
    ap.add_argument("--base", "--base-dir", dest="base", default=str(_HERE), help="repo root (default: repo)")
    ap.add_argument("--family", action="append", default=None,
                    help="restrict to a family label (repeatable)")
    ap.add_argument("--limit", type=int, default=8,
                    help="false rejections to show per rule (default 8)")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the census here (all probed rules)")
    ap.add_argument("--fail-on-false-reject", action="store_true",
                    help="exit 1 if any probed rule has a false rejection")
    args = ap.parse_args(argv)

    rules = _resolve_rules(args.rule)
    results = {name: probe(rule, name=name, base=args.base, families=args.family)
               for name, rule in rules.items()}

    first = next(iter(results.values()))["meta"]
    print(f"rule calibration -- {first['base']}")
    print(f"  {first['runs']} runs, {first['with_config']} phases with a launch "
          f"config" + (f", families={','.join(args.family)}" if args.family else ""))
    for name, result in results.items():
        print(f"\nrule: {name}")
        _report("OURS (native candidates)", result["populations"]["ours"],
                args.limit)
        _report("REFERENCE (gfx900 replay)", result["populations"]["reference"],
                args.limit)

    if args.json:
        args.json.write_text(json.dumps(results, indent=1))

    if args.fail_on_false_reject and any(
            r["populations"]["ours"]["false_rejections"] for r in results.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
