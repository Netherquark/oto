# oto — agent entry (Tier 0)

owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d

> Identity: coding agents improving oto itself (Class A). Operator agents
> producing a device library read `docs/operator_runbook.md` instead.

## Identity
oto is an agentic GEMM-kernel tuning suite for AMD GPUs. Deterministic
acceptance path: Tensile generates, the compiler validates, the hardware
decides. The agent layer proposes, never decides.

## Hard constraints
- Never edit `oto/`, `tests/`, root shims as a Class B agent.
- GPU work only in the user's TTY; never a display session.
- Append-only ledger; never delete/truncate run artifacts.
- Never strip UNVERIFIED tags or present research as measured fact.
- Never fabricate silicon facts; verify against first-party sources.

## Commands
- `python3 -m pytest -q` — full suite.
- `python3 -m oto setup --yes|--dry-run` — onboarding.
- `python3 -m oto doctor` — honest status.
- `python3 -m oto verify all` — evergreen equivalence checks.

## Commit conventions
Discrete, well-scoped commits; docs updated in the same change; no CI.

## Documentation map (single index)
`docs/README.md` is the class-tagged registry; `docs/docs_index.json` is the
machine version. Do **not** create new `.md` files without a registry row.

| If you change | Update |
|---|---|
| `oto/**/*.py` | module docstring + `docs/cli.md` if flags change |
| `docs/*.md` | `docs/README.md` registry row |
| `tests/` | keep suite green |

## Reading order
1. This file
2. `docs/invariants.md` (full operating contract, moved from claude.md)
3. `docs/README.md` (registry)
4. The owner MD for your task

No feature designs here; see `docs/invariants.md`.