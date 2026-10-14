#!/usr/bin/env python3
"""Emit the knob-sweep deck: every family's winner tile x one knob change.

Owns: the command line for the knob-sweep deck -- resolving which families,
shapes and sweeps to emit, calling ``CandidateGenerator
.generate_knob_sweep_phases``, and reporting what was refused and why.
Does NOT own: the sweep data (oto.tensile.decks), the generator that merges
template and knobs (oto.tensile.candidate_emission), or the gates that refuse a
candidate (oto.tensile.gates).
Public API: main.

Why this exists as a module rather than a CLI stage: ``oto.runners.cli`` stage 2
is deliberately READ_ONLY ("manifest summary only -- no execution, no run
minted"), and a deck generator writes ``phases.yaml``. Putting it here keeps that
contract intact while still giving the run a one-line entry point.

CPU only. Writes ``phases.yaml`` (the candidate manifest) and nothing else. It
never launches a kernel, and it has no Tensile/GPU dependency beyond the gates,
which are pure Python.

    python3 -m oto.tensile.knob_sweep                       # dry run, all families
    python3 -m oto.tensile.knob_sweep --emit                # append to phases.yaml
    python3 -m oto.tensile.knob_sweep --families CC ZZ      # the worst losers first
    python3 -m oto.tensile.knob_sweep --shapes 256x256x256 512x512x512
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.tensile.candidate import CandidateGenerator  # noqa: E402
from oto.tensile.decks import KNOB_SWEEPS, KNOB_SWEEP_BASES  # noqa: E402


def main(argv: List[str] | None = None) -> int:
    """Emit knob-sweep deck. argv: args vector. Returns: 0 success, 1 no candidates."""
    ap = argparse.ArgumentParser(
        description="Emit each family's winner tile crossed with the knobs "
                    "the corpus never explicitly set (potential_configs.md §8.1).",
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
                         "(DECISION_TRIAL_TILES: D1/D2/D3)")
    ap.add_argument("--phases", default="phases.yaml",
                    help="candidate manifest to write (default: ./phases.yaml)")
    args = ap.parse_args(argv)
    shapes = args.shapes or ["512x512x512", "1024x1024x1024"]; gen = CandidateGenerator(Path("."))
    print(f"knob-sweep deck: {len(KNOB_SWEEPS)} sweeps x "
          f"{len(args.families or KNOB_SWEEP_BASES)} families x "
          f"{len(shapes)} shapes"
          + (" + baselines" if args.baseline else "")
          + (" + trials" if args.trials else ""))
    if not args.emit:
        print("DRY RUN -- nothing written. Pass --emit to append.")
    if not args.emit:
        # Validate without writing: the generator's sweep method always appends,
        # so a dry run pre-checks each combination through the same gate and
        # reports the same refusals. This keeps `--emit` the only thing that can
        # change the manifest.
        emitted, refused = _dry_run(gen, args.families or list(KNOB_SWEEP_BASES),
                                    args.patterns or ["Ailk_Bljk"], shapes,
                                    include_baseline=args.baseline,
                                    include_trials=args.trials)
    else:
        target = Path(args.phases)
        emitted = gen.generate_knob_sweep_phases(
            families=args.families, patterns=args.patterns, base_shapes=shapes,
            include_baseline=args.baseline, phases_file=target)
        refused = []
        if args.trials:
            emitted += gen.generate_decision_trial_phases(
                families=args.families, patterns=args.patterns,
                base_shapes=shapes, phases_file=target)
    if not emitted:
        print("ERROR: no candidate could be emitted. Check the refusals above.")
        return 1

    print(f"\nready: {len(emitted)} candidates")
    if refused:
        print(f"{len(refused)} refused by the gates:")
        for line in refused:
            print(f"  {line}")
    if not args.emit:
        print("\nre-run with --emit to append these to phases.yaml")
    return 0


def _dry_run(gen: CandidateGenerator, families: List[str],
             patterns: List[str], shapes: List[str],
             include_baseline: bool = False, include_trials: bool = False
             ) -> tuple[List[Dict[str, Any]], List[str]]:
    """Validate sweep combinations without writing manifest. Returns: (emitted, refused)."""
    from oto.device.peaks import FAMILY_DTYPE_CHAR
    from oto.tensile.decks import DECISION_TRIAL_TILES, KNOB_SWEEPS, KNOB_SWEEP_BASES
    emitted: List[Dict[str, Any]] = []
    refused: List[str] = []
    for family in families:
        for base in KNOB_SWEEP_BASES.get(family, []):
            for pattern in patterns:
                for shape in shapes:
                    template = {
                        "Architecture": "gfx90c",
                        "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
                        "FamilyLabel": family,
                    }
                    if include_baseline:
                        ok, why = gen.validate_config({**template, **base})
                        if ok:
                            emitted.append(dict(base))
                        else:
                            refused.append(f"{family}/baseline/{shape}: {why}")
                for sweep in KNOB_SWEEPS:
                    if family not in sweep.get("families", []):
                        continue
                    for value in sweep["values"]:
                        knobs = dict(base)
                        for over_fam, width in sweep.get(
                                "width_override", {}).items():
                            if over_fam == family:
                                knobs["VectorWidth"] = width
                        knobs.update(value)
                        for shape in shapes:
                            template = {
                                "Architecture": "gfx90c",
                                "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
                                "ContractionPattern": pattern,
                                "ProblemType": shape,
                                "ScheduleName": "isa",
                                "FamilyLabel": family,
                            }
                            ok, why = gen.validate_config({**template, **knobs})
                            if ok:
                                emitted.append(knobs)
                            else:
                                refused.append(f"{family}/{sweep['knob']}/"
                                               f"{shape}: {why}")
    if include_trials:
        for trial in DECISION_TRIAL_TILES:
            family = trial["family"]
            if family not in families:
                continue
            for pattern in patterns:
                for shape in trial.get("shapes", shapes):
                    template = {
                        "Architecture": "gfx90c",
                        "DataType": FAMILY_DTYPE_CHAR.get(family, "S"),
                        "ContractionPattern": pattern,
                        "ProblemType": shape,
                        "ScheduleName": "isa",
                        "FamilyLabel": family,
                    }
                    ok, why = gen.validate_config(
                        {**template, **trial["knobs"]})
                    if ok:
                        emitted.append(dict(trial["knobs"]))
                    else:
                        refused.append(f"{family}/trial{trial['decision']}/"
                                       f"{shape}: {why}")
    return emitted, refused


if __name__ == "__main__":
    raise SystemExit(main())
