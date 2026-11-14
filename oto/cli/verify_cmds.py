"""The ``oto verify`` adapters.

Owns: argument translation for the verify command tree -- the split-era /
evergreen equivalence orchestrator and the corpus snapshot/diff/telemetry
runner.
Does NOT own: the verifiers themselves (oto.tools.verifiers) or the corpus
tool (oto.tools.corpus_audit).
Public API: run_verify_all, run_verify_run.
"""

from __future__ import annotations

from typing import Any

from oto.cli._adapter import _call, base_dir


def run_verify_all(args: Any) -> int:
    from oto.tools.verifiers.verify_all import main as va_main

    argv = ["--json"] if args.json else []
    if args.base_ref:
        argv += ["--base", args.base_ref]
    return _call(argv, va_main)


def run_verify_run(args: Any) -> int:
    from oto.tools.corpus_audit import main as vr_main

    argv = ["--base-dir", str(base_dir(args)), args.verify_cmd]
    if args.verify_cmd == "snapshot" and args.out:
        argv += ["--out", args.out]
    elif args.verify_cmd == "diff":
        argv += [args.before, args.after]
    elif args.verify_cmd == "telemetry":
        argv += [args.run_id]
    elif args.verify_cmd == "cheapest":
        if args.family:
            argv += ["--family", args.family]
        argv += ["--n", str(args.n)]
    if args.json:
        argv += ["--json"]
    return _call(argv, vr_main)
