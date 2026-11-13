# Class B — Operator Agent Skill

**Entry**: `docs/operator_runbook.md` → `docs/starter_pair.md` → `docs/starter_template.md`

## What you do
- Use oto to produce a best-effort Tensile library for an unsupported AMD platform
- Generate device-specific docs via agent-1/agent-2
- Run CPU-only harness study, then TTY benchmark, then `oto library best-effort`

## What you read
- `docs/operator_runbook.md` (the contract)
- `docs/starter_pair.md` (starter protocol)
- `docs/starter_template.md` (template)
- `docs/gfx902_starter.md` (worked example)
- Your device's starter file

## What you never need
- Anything about developing oto (routers, gate internals, test suite semantics)
- `implementation_plan.md` (dev loop, not your own)

## Tools you use
- `oto doctor` (diagnostics)
- `oto status` (ETA/panel)
- `oto tune` (convergence loop)
- `oto library best-effort` (CPU-only carve)
- `oto check candidates` (deck linter)
- `oto verify all` (refactor verifiers)

## Hard rules (READ-ONLY on oto codebase)
1. **NEVER modify any file under `oto/`, `tests/`, or root shims**
2. Your only writes: `profiles/<codename>.json`, `docs/<codename>_starter.*`,
   generated device docs, run artifacts under `<codename>_results/` and `<codename>_runs/`
3. If you find a bug in oto, STOP and report it — never patch oto code
4. GPU work happens only in the user's TTY
5. Research output tagged UNVERIFIED until human checks against first-party sources
6. Best-effort ≠ converged (library builds + loads, not parity)
