#!/usr/bin/env python3
"""The legality oracle: ask Tensile itself whether a config builds.

Owns: ``probe_config`` -- run a config through the *real* Tensile pipeline
(the same one the driver uses, minus the GPU) and report what Tensile derived
and decided: the solution count, the reject reason, the LDS allocation it
computed, the register pool it allocated, and our own gate's verdict beside
it.

Does NOT own: the gates (oto.tensile.gates -- this tool *asks* them), the
config materialisation (oto.tensile.config_writer), the Tensile pipeline
(oto.checks.tensile_build), or the corpus-wide agreement census
(oto.harness.gate_calibration -- that one sweeps the corpus; this one answers
about a single config).
Public API: probe_config, probe_phase, main.

Why it exists: the CPU gates are *models* of Tensile, and a model is only as
good as the cases it has been checked against. Whenever a question came up
that the model could not answer -- "does Tensile accept a negative
WorkGroupMapping?", "how much LDS does Tensile allocate for this tile?", "is
TransposeLDS=1 legal without MFMA?" -- the answer had to be written as a
throwaway script that drove Tensile by hand. This is that script, with the
answers in one place.

CPU only: the pipeline builds the kernel source and compiles it (a few
seconds per config), and never launches anything.

    python3 -m oto.harness.tensile_oracle --dtype S --macro 128x128x16 \\
        --thread 8x8 --vw 4 --du 16
    python3 -m oto.harness.tensile_oracle --phase-id phase_cand_ss_... --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

#: The derived fields worth showing: the LDS allocation Tensile computed and
#: the register pools it allocated.
_LDS_FIELDS = ("DepthU", "_DepthULds", "LdsNumElements", "LdsNumElementsAlignedA",
               "LdsNumElementsAlignedB", "LdsOffsetA_Blk", "LdsOffsetB_Blk",
               "LdsPadA", "LdsPadB", "MaxOccupancy", "Reject")


def _phase(config: Dict[str, Any], phase_id: str = "probe_oracle",
           dtype: str = "S") -> Dict[str, Any]:
    """A phase dict the driver can write a Tensile config from.

    The contraction pattern lives on the *phase*, not only in the config: the
    driver reads ``phase["contraction_pattern"]`` (falling back to the label)
    to set the problem type's transpose flags, so a config that only carries
    ``ContractionPattern`` would be probed as a different GEMM.
    """
    return {"phase_id": phase_id, "label": phase_id, "dtype": dtype.lower(),
            "shapes": ["512x512x512"], "config": dict(config),
            "contraction_pattern": config.get("ContractionPattern", "Ailk_Bjlk"),
            "fp": phase_id, "graded": False}


def _capture_derived() -> Tuple[Any, List[Dict[str, Any]]]:
    """Patch Tensile's solution builder to record what it derived.

    Returns:
        (the original function, the recorder list). The caller restores the
        original -- the patch is process-local and short-lived.
    """
    sys.path.insert(0, os.environ.get("TENSILE_ROOT", "") or
                    "/home/netherquark/Soham/Large_code/sources/GPU/Tensile")
    from Tensile.SolutionStructs import Solution

    original = Solution.assignDerivedParameters
    seen: List[Dict[str, Any]] = []

    def wrapper(state: Dict[str, Any]) -> None:
        original(state)
        seen.append({k: state.get(k) for k in _LDS_FIELDS})

    Solution.assignDerivedParameters = staticmethod(wrapper)
    return original, seen


def _launch_gate_verdict(phase: Dict[str, Any]) -> Optional[str]:
    """The launch boundary's own verdict on a phase, or None when it is legal.

    The driver refuses a phase with ``_launch_gate_refusal`` *before* it
    writes a config; the writer itself does not gate. Asking the writer
    whether it wrote the file would therefore report "legal" for a phase the
    run would refuse, so the gate is asked directly here.
    """
    from oto.tensile.config_writer import _launch_gate_refusal

    return _launch_gate_refusal(None, phase)


def probe_phase(phase: Dict[str, Any], base_dir: Optional[Path] = None
                ) -> Dict[str, Any]:
    """Ask Tensile whether a *phase* (a deck row) builds.

    The phase is written exactly the way the run writes it -- through the
    driver's own ``_write_phase_config`` -- so the probe exercises the same
    materialisation the launch boundary will.

    Args:
        phase: The phase dict (phase_id, label, dtype, shapes, config).
        base_dir: The repo root.

    Returns:
        The same dict as :func:`probe_config`.
    """
    from oto.runners.driver import TensileDriver

    base = Path(base_dir or _HERE)
    driver = TensileDriver(base, create_run=False)
    out_dir = Path(tempfile.mkdtemp(prefix="oto-oracle-"))
    config_path = out_dir / f"{phase.get('phase_id', 'probe')}.yaml"
    gate = _launch_gate_verdict(phase)
    if gate:
        return {"config": dict(phase.get("config", {})),
                "wrote": False, "gate_refusal": gate,
                "tensile": {"ok": None, "solutions": 0, "reason": None},
                "derived": None, "lds_bytes": 0}
    wrote, refusal = driver._write_phase_config(config_path, phase)
    if not wrote:
        return {"config": dict(phase.get("config", {})),
                "wrote": False, "gate_refusal": refusal,
                "tensile": {"ok": None, "solutions": 0, "reason": None},
                "derived": None, "lds_bytes": 0}
    return _probe_written(config_path, phase.get("config", {}))


def probe_config(config: Dict[str, Any], base_dir: Optional[Path] = None,
                 shapes: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Ask Tensile what it makes of a config.

    Args:
        config: The Tensile solution dict (the knobs, not the template).
        base_dir: The repo root; the driver and the Tensile tree are found
            from it.
        shapes: The problem shapes for the probe (512^3 by default).

    Returns:
        A dict with our gate's verdict, Tensile's verdict, the derived fields
        Tensile computed, and the register pools it allocated.
    """
    from oto.checks.tensile_build import _init_tensile, probe_phase_config
    from oto.runners.driver import TensileDriver

    base = Path(base_dir or _HERE)
    dtype = str(config.get("DataType", "S"))
    phase = _phase(config, dtype=dtype)
    if shapes:
        phase["shapes"] = list(shapes)

    driver = TensileDriver(base, create_run=False)
    out_dir = Path(tempfile.mkdtemp(prefix="oto-oracle-"))
    phase = _phase(config, dtype=str(config.get("DataType", "S")))
    if shapes:
        phase["shapes"] = list(shapes)
    config_path = out_dir / f"{phase['phase_id']}.yaml"
    gate = _launch_gate_verdict(phase)
    if gate:
        return {"config": dict(config), "wrote": False,
                "gate_refusal": gate,
                "tensile": {"ok": None, "solutions": 0, "reason": None},
                "derived": None, "lds_bytes": 0}
    wrote, refusal = driver._write_phase_config(config_path, phase)
    if not wrote:
        return {"config": dict(config), "wrote": False,
                "gate_refusal": refusal,
                "tensile": {"ok": None, "solutions": 0, "reason": None},
                "derived": None, "lds_bytes": 0}
    return _probe_written(config_path, config)


def _probe_written(config_path: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    """Run Tensile over a written config and report what it decided."""
    from oto.checks.tensile_build import _init_tensile, probe_phase_config

    _init_tensile()
    original, seen = _capture_derived()
    try:
        probe = probe_phase_config(config_path)
    finally:
        from Tensile.SolutionStructs import Solution
        Solution.assignDerivedParameters = original
    result: Dict[str, Any] = {
        "config": dict(config),
        "wrote": True,
        "gate_refusal": None,
        "tensile": {"ok": probe.get("ok"),
                    "solutions": probe.get("solutions"),
                    "reason": probe.get("reason")},
        "derived": None,
        "lds_bytes": 0,
    }
    if seen:
        result["derived"] = seen[-1]
        result["lds_bytes"] = _lds_bytes(seen[-1])
    return result


def _lds_bytes(state: Dict[str, Any]) -> int:
    """The LDS allocation Tensile derived, in bytes."""
    elements = state.get("LdsNumElements") or 0
    per_element = 4
    dest = state.get("DestDataType")
    if dest is not None:
        try:
            from Tensile.DataType import DataType

            per_element = DataType(dest).numBytes()
        except Exception:  # noqa: BLE001 -- the byte count is a convenience
            pass
    return elements * per_element


def _config_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    """The config dict the CLI describes."""
    config: Dict[str, Any] = {
        "Architecture": "the device",
        "DataType": args.dtype,
        "FamilyLabel": args.family or args.dtype,
        "ScheduleName": "isa",
        "ProblemType": "Contraction",
        "ContractionPattern": args.pattern,
        "MacroTile": args.macro,
        "ThreadTile": args.thread,
        "VectorWidth": args.vw,
        "DepthU": args.du,
    }
    if args.wgm is not None:
        config["WorkGroupMapping"] = args.wgm
    for item in args.extra or []:
        key, _, value = item.partition("=")
        try:
            config[key] = int(value)
        except ValueError:
            config[key] = value
    return config


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dtype", default="S", help="Tensile DataType char (S/D/H/C/Z)")
    ap.add_argument("--family", default=None, help="FamilyLabel (defaults to the dtype)")
    ap.add_argument("--macro", default="128x128x8", help="MacroTile, e.g. 128x128x16")
    ap.add_argument("--thread", default="8x8", help="ThreadTile, e.g. 8x8")
    ap.add_argument("--vw", type=int, default=4, help="VectorWidth")
    ap.add_argument("--du", type=int, default=8, help="DepthU")
    ap.add_argument("--pattern", default="Ailk_Bjlk", help="ContractionPattern")
    ap.add_argument("--wgm", type=int, default=None, help="WorkGroupMapping")
    ap.add_argument("--extra", action="append",
                    help="another knob, KEY=VALUE (repeatable)")
    ap.add_argument("--phase-id", default=None,
                    help="probe a deck row by phase_id instead of describing one")
    ap.add_argument("--json", type=Path, help="write the verdict here")
    args = ap.parse_args(argv)

    if args.phase_id:
        import yaml

        deck = yaml.safe_load((_HERE / "phases.yaml").read_text()) or []
        row = next((p for p in deck if p.get("phase_id") == args.phase_id), None)
        if row is None:
            print(f"no deck row named {args.phase_id!r}")
            return 1
        config = row.get("config", {})
    else:
        config = _config_from_args(args)

    result = probe_config(config)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, default=str))
    tensile = result["tensile"]
    print(f"config      {config.get('DataType')} {config.get('MacroTile')} "
          f"tt{config.get('ThreadTile')} vw{config.get('VectorWidth')} "
          f"du{config.get('DepthU')}"
          + (f" wgm{config.get('WorkGroupMapping')}" if config.get("WorkGroupMapping") else ""))
    print(f"our gate    {'LEGAL' if not result.get('gate_refusal') else 'REFUSED'}"
          + (f" -- {result['gate_refusal']}" if result.get("gate_refusal") else ""))
    print(f"Tensile     {'BUILDS' if tensile.get('ok') else 'REFUSES'}"
          f"  ({tensile.get('solutions')} solution(s))"
          + (f"  -- {tensile.get('reason')}" if tensile.get("reason") else ""))
    derived = result.get("derived") or {}
    if derived:
        print(f"LDS         {derived.get('LdsNumElements')} elements "
              f"= {result.get('lds_bytes')} bytes"
              f"  (A {derived.get('LdsNumElementsAlignedA')}, "
              f"B {derived.get('LdsNumElementsAlignedB')}, "
              f"blk {derived.get('LdsOffsetA_Blk')}/{derived.get('LdsOffsetB_Blk')})")
        print(f"derived     depth {derived.get('DepthU')} (lds {derived.get('_DepthULds')}), "
              f"pads {derived.get('LdsPadA')}/{derived.get('LdsPadB')}, "
              f"maxOccupancy {derived.get('MaxOccupancy')}")
    if derived.get("Reject"):
        print(f"reject      {derived['Reject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
