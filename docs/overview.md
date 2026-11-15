# oto — documentation overview
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d

The birds-eye view of the oto documentation ecosystem. The machine-readable
version is [`docs/docs_index.json`](docs_index.json) (regenerated with
`oto agent index`); the human version is this file. The class-tagged registry
is [`docs/README.md`](README.md).

## The three ecosystems — who each document is for

Every document in `docs/` (and the root `*.md`) belongs to exactly one of
three ecosystems. If a document tries to serve two, it serves neither.

| Ecosystem | Reader | Entry point | Never needs |
|---|---|---|---|
| **Human** | a person setting up or running oto | [`README.md`](../README.md) → [`docs/getting_started.md`](getting_started.md) | gate internals, docstrings, implementation plan |
| **Operator agent (Class B)** | an LLM/agent converging a device library | [`docs/operator_runbook.md`](operator_runbook.md) | developing oto, docstrings, implementation plan |
| **Developer agent (Class A)** | an LLM/agent changing oto itself | [`AGENTS.md`](../AGENTS.md) → [`docs/invariants.md`](invariants.md) | operator starter files, bring-up procedure |

### Human ecosystem
Vision → setup → bring-up gate → failure modes. No agent-role jargon.
- [`README.md`](../README.md), [`docs/getting_started.md`](getting_started.md),
  [`docs/setup.md`](setup.md), [`docs/toolchain_client.md`](toolchain_client.md),
  [`docs/cli.md`](cli.md), [`CONTRIBUTING.md`](../CONTRIBUTING.md),
  `LICENSE`, `NOTICE`.

### Operator ecosystem (Class B)
Bring-up → starter pair → campaign → verification matrix.
- [`docs/operator_runbook.md`](operator_runbook.md) (contract + matrix),
  [`docs/operator_campaign.md`](operator_campaign.md) (long-form campaign),
  [`docs/starter_pair.md`](starter_pair.md), `docs/starter_template.md` /
  `.json`, `docs/gfx902_starter.md` / `.json` (worked example),
  `docs/gfx902_blind_convergence.md`, `docs/agent_reference.md`,
  `docs/harness_runbook.md`, `docs/setup.md` (shared).

### Developer ecosystem (Class A)
Invariants → docstrings → implementation plan → harness.
- [`AGENTS.md`](../AGENTS.md) (Tier 0), [`docs/invariants.md`](invariants.md)
  (Tier 1, full contract), [`claude.md`](../claude.md) (thin pointer),
  [`docs/implementation_plan.md`](implementation_plan.md),
  [`docs/harness_runbook.md`](harness_runbook.md),
  [`docs/agent_reference.md`](agent_reference.md),
  [`docs/docstrings.md`](docstrings.md),
  [`docs/agentic_consult.md`](agentic_consult.md),
  [`docs/comparability.md`](comparability.md),
  [`docs/shipped_floor_contract.md`](shipped_floor_contract.md),
  [`docs/search_philosophy.md`](search_philosophy.md),
  [`docs/design_language.md`](design_language.md),
  [`docs/documentation_tooling_options.md`](documentation_tooling_options.md),
  [`docs/potential_configs.md`](potential_configs.md),
  [`docs/audit_register.md`](audit_register.md).

### Shared across ecosystems
- `docs/README.md` (registry), `docs/docs_index.json`, `docs/overview.md` (this
  file), `docs/cli.md`, `docs/setup.md`, `docs/toolchain_client.md`.

## Golden case study + templates
`docs/gfx90c_*.md` (golden, do-not-edit) ↔ device-independent twins
`docs/results.md`, `theoretical_limits.md`, `knowledge_base.md`,
`potential_configs.md` (templates — copy and fill per device).

## Full registry
[`docs/README.md`](README.md).