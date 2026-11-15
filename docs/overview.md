# oto — documentation overview

The birds-eye view of the oto documentation ecosystem. Every document in the
repo, what it is for, who reads it, and in what order. The machine-readable
version is [`docs/docs_index.json`](docs_index.json) (regenerated with
`oto agent index`); the human version is this file. The class-tagged registry
that both derive from is [`docs/README.md`](README.md).

## Audiences and entry points

- **Human user:** [`README.md`](../README.md) → [`docs/getting_started.md`](getting_started.md).
- **Class A — developer agents:** `claude.md` → `docs/agent_reference.md` →
  `docs/docstrings.md` → `docs/harness_runbook.md` →
  `docs/implementation_plan.md`.
- **Class B — operator agents:** `docs/operator_runbook.md` →
  `docs/starter_pair.md` → `docs/starter_template.md` →
  `docs/operator_campaign.md` → `docs/gfx902_starter.md` (worked example).

## Core contract

| Doc | Role |
|---|---|
| [`claude.md`](../claude.md) | Entry contract, process guardrails, file-ownership rules. |
| [`docs/implementation_plan.md`](implementation_plan.md) | Design brief: two-loop architecture. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Commit discipline, GPU policy, code-style rules. |
| [`SECURITY.md`](../SECURITY.md) | Security reporting policy. |
| [`docs/audit_register.md`](audit_register.md) | Expert-agent audit register. |

## gfx90c golden case study

`docs/gfx90c_tuning_guide.md`, `docs/gfx90c_results.md`,
`docs/gfx90c_theoretical_limits.md`, `docs/gfx90c_knowledge_base.md`.
Their device-independent twins are `docs/results.md`,
`docs/theoretical_limits.md`, `docs/knowledge_base.md`,
`docs/potential_configs.md` (templates — copy and fill per device).

## Full registry

See [`docs/README.md`](README.md) for the complete class-tagged registry of
every document. Machine-readable: [`docs/docs_index.json`](docs_index.json).

## License

GPL-3.0-or-later — see [`LICENSE`](../LICENSE) and [`NOTICE`](../NOTICE).
Code: GPL-v3. Docs: CC-BY-SA-4.0.