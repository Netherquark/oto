# Class A — Developer Agent Skill

**Entry**: `claude.md` → `docs/agent_reference.md` → `docs/docstrings.md`

## What you do
- Work ON the oto codebase (fix bugs, add features, refactor)
- Run tests, ruff, pyflakes, length gates
- Commit changes with preflight green

## What you read
- `claude.md` (entry contract, invariants, guardrails)
- `docs/agent_reference.md` (harness quick reference)
- `docs/docstrings.md` (docstring convention)
- `docs/harness_runbook.md` (harness guardrails)
- `docs/implementation_plan.md` (live plan)
- `changelog.md` (what landed)
- `incomplete_work.md` (open register)

## What you never need
- Operator starter files (`docs/starter_*.md`)
- `docs/operator_runbook.md` as a procedure
- GPU runs (user-TTY-only)

## Tools you use
- `pytest`, `ruff`, `pyflakes`
- `python3 -m oto.harness.candidate_generator --dry-run`
- `python3 -m oto check candidates --quiet`
- `python3 -m oto.tools.deck_review`
- `python3 -m oto.harness.gate_calibration`
- `python3 -m oto.harness.failure_triage`

## Hard rules
1. No GPU work outside the user's TTY
2. No device literals outside `oto/device/` and `profiles/`
3. No function >60 LOC, no file >600 LOC
4. No /tmp paths in tests
5. Tests must never read from /tmp
6. Single-concern commits, preflight green before commit
