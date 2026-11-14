"""harness — agentic kernel-tuning harness.

Ground-truth measurement DB, candidate-gap analysis and per-cell winner
resolution for the device kernel tuning, built for future agents (and humans)
doing candidate generation. Read-only over the live run corpus; never
benchmarks, never touches a GPU.

Workflow (see ``docs/harness_runbook.md`` for the full runbook):

    python3 -m oto.harness.kernel_db --base-dir . --rebuild   # (re)build kernel_db.json
    python3 -m oto.harness.regression_matrix --base-dir .    # deck vs all-time vs floor
    python3 -m oto.harness.cell_resolver --base-dir .        # per-cell native+floor winners

Owns: nothing at import time — this package holds no logic, only the docstrings
of the modules underneath it.
Does NOT own: the modules themselves (each carries its own), the run corpus
they read (<codename>_runs/), or the acceptance report they cite
(oto.metrics.acceptance_report).
Public API: none at import time; the module names live in ``__all__``, and the
public names each one exposes are in its own docstring.

All tools import the repo's canonical sources (`oto.device.loader` and `oto.device.kernel_vocabulary`,
`oto.tensile.library_parity`) instead of re-deriving family/shape maps and
coverage.
"""

from __future__ import annotations

__all__ = [
    "asm_occupancy",
    "candidate_generator",
    "candidate_overlay",
    "candidate_pool",
    "candidate_rows",
    "cell_knob_diff",
    "cell_resolver",
    "corpus_census",
    "coverage_graph",
    "coverage_map",
    "deck_probe",
    "failure_triage",
    "gate_calibration",
    "kernel_db",
    "occupancy_bounds",
    "regression_matrix",
    "rule_calibration",
    "tensile_probe",
    "vgpr_measurement",
    "visual_check",
]

__version__ = "1.1.0"
