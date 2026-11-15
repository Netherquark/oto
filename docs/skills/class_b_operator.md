# Class B — Operator Agent Skill
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


**Entry**: `docs/skills/caveman.md` (token efficiency, read first) → `docs/operator_runbook.md` → `docs/starter_pair.md` → `docs/starter_template.md`

## What you do
- Use oto to produce a best-effort Tensile library for an unsupported AMD platform
- Generate device-specific docs via agent-1/agent-2
- Run CPU-only harness study, then TTY benchmark, then `oto library best-effort`
- Then the campaign: study the corpus, decompose ties/losses into classes, propose routes, reconnect for consultations only at defined triggers
- If the docs cannot answer a question you must settle, commission a research pass in the shape of `docs/operator_runbook.md` §18 (research-prompt discipline)

## What you read
- `docs/operator_runbook.md` (the contract)
- `docs/starter_pair.md` (starter protocol)
- `docs/starter_template.md` (template)
- `docs/gfx902_starter.md` (worked example)
- [`docs/gfx90c_results.md`](../gfx90c_results.md) (never trust an A/B number without it)
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

## Token economy (default behaviour)

Routine narration burns tokens; a whole campaign is thousands of them. Default
to the `caveman` **lite** register for prose between tool calls and in
mid-run status reports. Switch on request: `/caveman full|ultra`, off:
"stop caveman" / "normal mode". Levels and the upstream skill live at
`vendor/caveman/skills/caveman/SKILL.md`; the integration notes for oto live
in `docs/skills/caveman.md`.

**Never compressed, under any level — these are contract, not prose:**

- verdicts, numbers, run ids, cell ids, GFLOP/s, file:line citations
- commands and command lines (`python3 -m oto tune --budget 10` is not `tune 10`)
- error strings (quote verbatim)
- `UNVERIFIED` tags and their fill-in sentences
- the data-preservation law (`docs/gfx90c_knowledge_base.md` §10)

Silence is not success: if a check produces no output, say so (`no output — did not verify`), never infer a pass from quiet.

## Hard rules (READ-ONLY on oto codebase)
1. **NEVER modify any file under `oto/`, `tests/`, or root shims**
2. Your only writes: `profiles/<codename>.json`, `docs/<codename>_starter.*`,
   generated device docs, run artifacts under `<codename>_results/` and `<codename>_runs/`
3. If you find a bug in oto, STOP and report it — never patch oto code
4. GPU work happens only in the user's TTY
5. Research output tagged UNVERIFIED until human checks against first-party sources
6. Best-effort ≠ converged (library builds + loads, not parity)
