"""harness — agentic kernel-tuning harness.

Ground-truth measurement DB, candidate-gap analysis and per-cell winner
resolution for gfx90c kernel tuning, built for future agents (and humans)
doing candidate generation. Read-only over the live run corpus; never
benchmarks, never touches a GPU.

Workflow (see harness/README.md for the full runbook):

    python3 -m harness.kernel_db --base-dir . --rebuild       # (re)build kernel_db.json
    python3 -m harness.regression_matrix --base-dir .         # deck vs all-time vs floor
    python3 -m harness.resolve_cells --base-dir .             # per-cell native+floor winners

All tools import the repo's canonical sources (`gfx90c_common`,
`library_parity`) instead of re-deriving family/shape maps and coverage.
"""

from __future__ import annotations

__all__ = ["kernel_db", "regression_matrix", "resolve_cells"]

__version__ = "1.1.0"