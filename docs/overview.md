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
| **Human** | a person setting up or running oto | [`README.md`](../README.md) → [`docs/human/getting_started.md`](human/getting_started.md) | gate internals, docstrings, implementation plan |
| **Operator agent (Class B)** | an LLM/agent converging a device library | [`docs/operator/operator_runbook.md`](operator/operator_runbook.md) | developing oto, docstrings, implementation plan |
| **Developer agent (Class A)** | an LLM/agent changing oto itself | [`AGENTS.md`](../AGENTS.md) → [`docs/developer/invariants.md`](developer/invariants.md) | operator starter files, bring-up procedure |

### Human ecosystem
Vision → setup → bring-up gate → failure modes. No agent-role jargon.
- [`README.md`](../README.md), [`docs/human/getting_started.md`](human/getting_started.md),
  [`docs/human/toolchain_client.md`](human/toolchain_client.md),
  [`docs/cli.md`](cli.md), [`CONTRIBUTING.md`](../CONTRIBUTING.md),
  `LICENSE`, `NOTICE`.

### Operator ecosystem (Class B)
Bring-up → starter pair → campaign → verification matrix.
- [`docs/operator/operator_runbook.md`](operator/operator_runbook.md) (contract + matrix),
  [`docs/operator/starter_pair.md`](operator/starter_pair.md), `docs/operator/starter_template.md` /
  `.json`, `docs/operator/gfx902_starter.md` / `.json` (worked example),
  `docs/developer/harness_runbook.md`,
  `docs/human/getting_started.md` (shared).

### Developer ecosystem (Class A)
Invariants → docstrings → implementation plan → harness.
- [`AGENTS.md`](../AGENTS.md) (Tier 0), [`docs/developer/invariants.md`](developer/invariants.md)
  (Tier 1, full contract), [`claude.md`](../claude.md) (thin pointer),
  [`docs/developer/harness_runbook.md`](developer/harness_runbook.md),
  [`docs/developer/docstrings.md`](developer/docstrings.md),
  [`docs/developer/audit_register.md`](developer/audit_register.md),
  [`docs/developer/design_language.md`](developer/design_language.md),
  [`docs/gfx90c/gfx90c_results.md`](gfx90c/gfx90c_results.md),
  [`docs/gfx90c/potential_configs.md`](gfx90c/potential_configs.md).

### Shared across ecosystems
- `docs/README.md` (registry), `docs/docs_index.json`, `docs/overview.md` (this
  file), `docs/cli.md`, `docs/human/getting_started.md`, `docs/human/toolchain_client.md`.

## Golden case study + templates
`docs/gfx90c/gfx90c_*.md` (golden, do-not-edit) ↔ device-independent twins
`docs/gfx90c/results.md`, `theoretical_limits.md`, `knowledge_base.md`,
`potential_configs.md` (templates — copy and fill per device).

## Layout

```
docs/
  README.md  overview.md  cli.md  docs_index.json   # registry + bird's-eye (top level)
  changelog.md  incomplete_work.md                  # evolution log + open register (top level)
  human/       getting_started.md  toolchain_client.md   # people, not agents
  operator/    operator_runbook.md  starter_*.md  gfx902_starter.*   # Class B brings a device up
  developer/   invariants.md  harness_runbook.md  docstrings.md  audit_register.md  design_language.md
  gfx90c/      gfx90c_*.md  results.md  theoretical_limits.md  knowledge_base.md  potential_configs.md
  research/    kernel_tuning.md  complex_gemm_brief.md    # research only, evidence-tagged
  skills/      caveman.md  class_a_developer.md  class_b_operator.md
```

## Full registry
[`docs/README.md`](README.md).