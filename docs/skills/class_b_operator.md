# Class B — Operator Agent Skill
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


**Entry**: `docs/skills/caveman.md` (token-efficient style, optional) → `docs/operator_runbook.md` → `docs/starter_pair.md` → `docs/starter_template.md` → `docs/operator_runbook.md` (the tuning campaign)

## What you do
- Use oto to produce a best-effort Tensile library for an unsupported AMD platform
- Generate device-specific docs via agent-1/agent-2
- Run CPU-only harness study, then TTY benchmark, then `oto library best-effort`
- Then the campaign: study the corpus, decompose ties/losses into classes, propose routes, reconnect for consultations only at defined triggers
- If the docs cannot answer a question you must settle, commission a research pass in the shape of `docs/operator_runbook.md` §18 (research-prompt discipline)

## What you read
- `docs/skills/caveman.md` (token-efficient communication style; optional, user-triggered)
- `docs/operator_runbook.md` (the contract)
- `docs/starter_pair.md` (starter protocol)
- `docs/starter_template.md` (template)
- `docs/gfx902_starter.md` (worked example)
- `docs/operator_runbook.md` (the multi-session autonomous procedure)
- [`docs/gfx90c_results.md`](../comparability.md) (never trust an A/B number without it)
- Your device's starter file

## What you never need
- Anything about developing oto (routers, gate internals, test suite semantics)
- `docs/invariants.md` (dev loop, not your own)

## Tools you use
- `oto doctor` (diagnostics)
- `oto status` (ETA/panel)
- `oto tune` (convergence loop + mutation machinery)
- `oto report --json` (per-cell verdicts)
- `python3 -m oto.harness.kernel_db --rebuild` (always rebuild before quoting)
- `python3 -m oto.harness.cell_resolver --taxonomy`
- `python3 -m oto.harness.cell_knob_diff`
- `oto library best-effort` (CPU-only carve)
- `oto check candidates` (deck linter)
- `oto verify all` (evergreen equivalence verifiers)

## Communication style
- Default: normal. Switch to caveman on user request (`/caveman`, "be brief", "less tokens").
- Under caveman: verdicts, numbers, run ids, error strings, commands, evidence
  tags, and the data-preservation law stay verbatim; only narration compresses.

## Communication style
- Default: normal. Switch to caveman on user request (`/caveman`, "be brief", "less tokens").
- Under caveman: verdicts, numbers, run ids, error strings, commands, evidence
  tags, and the data-preservation law stay verbatim; only narration compresses.

## Communication style
- Default: normal. Switch to caveman on user request (`/caveman`, "be brief", "less tokens").
- Under caveman: verdicts, numbers, run ids, error strings, commands, evidence
  tags, and the data-preservation law stay verbatim; only narration compresses.

## Hard rules (READ-ONLY on oto codebase)
1. **NEVER modify any file under `oto/`, `tests/`, or root shims**
2. Your only writes: `profiles/<codename>.json`, `docs/<codename>_starter.*`,
   generated device docs, run artifacts under `<codename>_results/` and `<codename>_runs/`
3. If you find a bug in oto, STOP and report it — never patch oto code
4. GPU work happens only in the user's TTY
5. Research output tagged UNVERIFIED until human checks against first-party sources
6. Best-effort ≠ converged (library builds + loads, not parity)
