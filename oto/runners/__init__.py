"""Execution: the driver and the run loops it dispatches.

Owns: TensileDriver (the composition root -- phase execution, benchmark
invocation, config plumbing), the phase runner and its skip/bypass policy
(phase_runner.py), the gfx900 reference floor (reference_floor.py), the --auto convergence
loop (convergence_loop.py), and the argparse stage dispatch (stage_cli.py).
Does NOT own: candidate legality (`oto.tensile`), verdicts (`oto.metrics`), or
durable state (`oto.ledger`).
Public API: none at import time; this package re-exports
nothing, so importing it has no side effects.
"""
