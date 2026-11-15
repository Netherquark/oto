#!/usr/bin/env python3
"""Emit the knob-sweep deck: every family's winner tile x one knob change.

Owns: the command line for the knob-sweep deck -- resolving which families,
shapes and sweeps to emit, calling ``CandidateGenerator
.generate_knob_sweep_phases``, and reporting what was refused and why.
Does NOT own: the sweep data (`oto.tensile.family_decks`), the generator that merges
template and knobs (`oto.tensile.candidate_emission`), or the gates that refuse a
candidate (`oto.tensile.gates`).
Public API: main.

Why this exists as a module rather than a CLI stage: ```oto.runners.stage_cli``` stage 2
is deliberately READ_ONLY ("manifest summary only -- no execution, no run
minted"), and a deck generator writes ``phases.yaml``. Putting it here keeps that
contract intact while still giving the run a one-line entry point.

CPU only. Writes ``phases.yaml`` (the candidate manifest) and nothing else. It
never launches a kernel, and it has no Tensile/GPU dependency beyond the gates,
which are pure Python.

    python3 -m `oto.tensile.knob_sweep`                       # dry run, all families
    python3 -m `oto.tensile.knob_sweep` --emit                # append to phases.yaml
    python3 -m `oto.tensile.knob_sweep` --families CC ZZ      # the worst losers first
    python3 -m `oto.tensile.knob_sweep` --shapes 256x256x256 512x512x512
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.device import loader as _loader
from oto.tensile.candidate import CandidateGenerator
from oto.tensile.family_decks import KNOB_SWEEP_BASES, KNOB_SWEEPS


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the knob-sweep CLI parser."""
    ap = argparse.ArgumentParser(
        description="Emit each family's winner tile crossed with the knobs "
                    "the corpus never explicitly set (docs/gfx90c_tuning_guide.md §13 §8.1).",
        epilog="CPU only. Writes phases.yaml; never launches a kernel.")
    ap.add_argument("--families", nargs="+", default=None,
                    choices=sorted(KNOB_SWEEP_BASES),
                    help="families to sweep (default: all)")
    ap.add_argument("--shapes", nargs="+", default=None,
                    help="problem shapes (default: 512/1024 cubes)")
    ap.add_argument("--patterns", nargs="+", default=None,
                    help="contraction patterns (default: Ailk_Bljk)")
    ap.add_argument("--emit", action="store_true",
                    help="append candidates to phases.yaml (default: dry run, "
                         "which validates without writing)")
    ap.add_argument("--baseline", action="store_true",
                    help="also emit each base tile unchanged once per "
                         "(family, shape) as the same-run control (D4)")
    ap.add_argument("--trials", action="store_true",
                    help="also emit the decision-labelled trial tiles "
                         "(DECISION_TRIAL_TILES: D1; D5 adopted 2026-11-14)")
    ap.add_argument("--phases", default="phases.yaml",
                    help="candidate manifest to write (default: ./phases.yaml)")
    return ap


def _run_dry(
    gen: CandidateGenerator,
    args: argparse.Namespace,
    shapes: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Dry-run the sweep; validates without writing the manifest."""
    print("DRY RUN -- nothing written. Pass --emit to append.")
    return _dry_run(gen, args.families or list(KNOB_SWEEP_BASES),
                    args.patterns or ["Ailk_Bljk"], shapes,
                    include_baseline=args.baseline,
                    include_trials=args.trials)


def _run_emit(
    gen: CandidateGenerator,
    args: argparse.Namespace,
    shapes: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Append the sweep candidates to the phases manifest."""
    target = Path(args.phases)
    emitted = gen.generate_knob_sweep_phases(
        families=args.families, patterns=args.patterns, base_shapes=shapes,
        include_baseline=args.baseline, phases_file=target)
    refused: list[str] = []
    if args.trials:
        emitted += gen.generate_decision_trial_phases(
            families=args.families, patterns=args.patterns,
            base_shapes=shapes, phases_file=target)
    return emitted, refused


def _print_summary(emitted: list[dict[str, Any]],
                   refused: list[str],
                   emit: bool) -> int:
    """Print the emit summary; exit 1 when no candidate could be emitted."""
    if not emitted:
        print("ERROR: no candidate could be emitted. Check the refusals above.")
        return 1
    print(f"\nready: {len(emitted)} candidates")
    if refused:
        print(f"{len(refused)} refused by the gates:")
        for _line in refused:
            print(f"  {_line}")
    if not emit:
        print("\nre-run with --emit to append these to phases.yaml")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Emit the knob-sweep deck; exit 0 on success, 1 when nothing could be emitted.

    ``argv`` is the args vector.
    """
    args = _build_arg_parser().parse_args(argv)
    shapes = args.shapes or ["512x512x512", "1024x1024x1024"]
    gen = CandidateGenerator(Path("."))
    print(f"knob-sweep deck: {len(KNOB_SWEEPS)} sweeps x "
          f"{len(args.families or KNOB_SWEEP_BASES)} families x "
          f"{len(shapes)} shapes"
          + (" + baselines" if args.baseline else "")
          + (" + trials" if args.trials else ""))

    if args.emit:
        emitted, refused = _run_emit(gen, args, shapes)
    else:
        emitted, refused = _run_dry(gen, args, shapes)
    return _print_summary(emitted, refused, args.emit)


def _emit_baselines(
    gen: CandidateGenerator,
    families: list[str],
    patterns: list[str],
    shapes: list[str],
profile=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Emit baseline tiles for each family/shape.

    ``profile`` is an optional ``DeviceProfile``; it defaults to the process's ambient profile.
    """
    from oto.tensile.family_decks import KNOB_SWEEP_BASES
    emitted: list[dict[str, Any]] = []
    refused: list[str] = []
    for family in families:
        for base in KNOB_SWEEP_BASES.get(family, [],):
            for pattern in patterns:
                for shape in shapes:
                    template = {
                        "Architecture": _loader.resolve_profile(profile,).codename,
                        "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
                        "FamilyLabel": family,
                    }
                    ok, why = gen.validate_config({**template, **base},)
                    if ok:
                        emitted.append(dict(base))
                    else:
                        refused.append(f"{family}/baseline/{shape}: {why}")
    return emitted, refused


def _emit_sweeps(
    gen: CandidateGenerator,
    families: list[str],
    patterns: list[str],
    shapes: list[str],
profile=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Emit sweep tiles for each family/knob/shape.

    ``profile`` is an optional ``DeviceProfile``; it defaults to the process's ambient profile.
    """
    from oto.tensile.family_decks import KNOB_SWEEP_BASES
    emitted: list[dict[str, Any]] = []
    refused: list[str] = []
    for family in families:
        for base in KNOB_SWEEP_BASES.get(family, [],):
            for pattern in patterns:
                for sweep in KNOB_SWEEPS:
                    if family not in sweep.get("families", [],):
                        continue
                    for value in sweep["values"]:
                        knobs = dict(base)
                        for over_fam, width in sweep.get(
                                "width_override", {},).items():
                            if over_fam == family:
                                knobs["VectorWidth"] = width
                        knobs.update(value)
                        for shape in shapes:
                            template = {
                                "Architecture": _loader.resolve_profile(profile,).codename,
                                "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                                "ContractionPattern": pattern,
                                "ProblemType": shape,
                                "ScheduleName": "isa",
                                "FamilyLabel": family,
                            }
                            ok, why = gen.validate_config({**template, **knobs},)
                            if ok:
                                emitted.append(knobs)
                            else:
                                refused.append(f"{family}/{sweep['knob']}/"
                                               f"{shape}: {why}")
    return emitted, refused


def _emit_trials(
    gen: CandidateGenerator,
    families: list[str],
    patterns: list[str],
    shapes: list[str],
profile=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Emit decision trial tiles.

    ``profile`` is an optional ``DeviceProfile``; it defaults to the process's ambient profile.
    """
    from oto.tensile.family_decks import DECISION_TRIAL_TILES
    emitted: list[dict[str, Any]] = []
    refused: list[str] = []
    for trial in DECISION_TRIAL_TILES:
        family = trial["family"]
        if family not in families:
            continue
        for pattern in patterns:
            for shape in trial.get("shapes", shapes,):
                template = {
                    "Architecture": _loader.resolve_profile(profile,).codename,
                    "DataType": _loader.resolve_profile(profile,).family_dtype_char.get(family, "S",),
                    "ContractionPattern": pattern,
                    "ProblemType": shape,
                    "ScheduleName": "isa",
                    "FamilyLabel": family,
                }
                ok, why = gen.validate_config(
                    {**template, **trial["knobs"]},)
                if ok:
                    emitted.append(dict(trial["knobs"]))
                else:
                    refused.append(f"{family}/trial{trial['decision']}/"
                                   f"{shape}: {why}")
    return emitted, refused


def _dry_run(gen: CandidateGenerator, families: list[str],
             patterns: list[str], shapes: list[str],
             include_baseline: bool = False, include_trials: bool = False
             ) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate sweep combinations without writing the manifest.

    Returns the ``(emitted, refused)`` pair.
    """
    emitted: list[dict[str, Any]] = []
    refused: list[str] = []
    if include_baseline:
        e, r = _emit_baselines(gen, families, patterns, shapes)
        emitted.extend(e)
        refused.extend(r)
    e, r = _emit_sweeps(gen, families, patterns, shapes)
    emitted.extend(e)
    refused.extend(r)
    if include_trials:
        e, r = _emit_trials(gen, families, patterns, shapes)
        emitted.extend(e)
        refused.extend(r)
    return emitted, refused


if __name__ == "__main__":
    raise SystemExit(main())
