# oto — documentation overview

The birds-eye view of the oto documentation ecosystem. Every document in the
repo, what it is for, who reads it, and in what order. The machine-readable
version is [`docs/docs_index.json`](docs_index.json) (regenerated with
`oto agent index`); the human version is this file. The class-tagged registry
that both derive from is [`docs/README.md`](README.md).

## Audiences

- **Class A — developer agents** (working *on* oto): `claude.md` →
  `docs/agent_reference.md` → `docs/docstrings.md` →
  `docs/harness_runbook.md` → `docs/implementation_plan.md`.
- **Class B — operator agents** (producing a best-effort library for an
  unsupported AMD platform): `docs/operator_runbook.md` →
  `docs/starter_pair.md` → `docs/starter_template.md` →
  `docs/operator_campaign.md` → `docs/gfx902_starter.md` (worked example).

## The core contract

| Doc | Role |
|---|---|
| [`claude.md`](../claude.md) | Entry contract, process guardrails, file-ownership rules. The single source of invariants. |
| [`docs/implementation_plan.md`](implementation_plan.md) | The design brief: the two-loop architecture (deterministic acceptance path + LLM-assisted outer layer) and the rule that the model never decides a verdict. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Commit discipline, GPU policy, code-style rules. |
| [`SECURITY.md`](../SECURITY.md) | Security reporting policy. |
| [`docs/audit_register.md`](audit_register.md) | The expert-agent audit register and the frozen prior baseline. |

## The gfx90c golden case study (the worked example)

| Doc | Role |
|---|---|
| [`docs/gfx90c_tuning_guide.md`](gfx90c_tuning_guide.md) | The practical knob→effect tuning guide; carries the full bring-up case study in §13 (the absorbed `potential_configs.md`), the prior-campaign autopsy in §14, and the corpus-pass audit trail in §15. |
| [`docs/gfx90c_results.md`](gfx90c_results.md) | The live benchmark ledger and frozen ceiling metrics (gfx90c). |
| [`docs/gfx90c_theoretical_limits.md`](gfx90c_theoretical_limits.md) | Hardware ceilings and the acceptance-criteria authority (gfx90c). |
| [`docs/gfx90c_knowledge_base.md`](gfx90c_knowledge_base.md) | Core architecture + the append-only data-preservation law (§10) (gfx90c). |

These four are the **gfx90c-specific docs**. Their device-independent twins are
the `docs/results.md`, `docs/theoretical_limits.md`, `docs/knowledge_base.md`
templates, which the agent populates per device.

## The device-independent methodology

| Doc | Role |
|---|---|
| [`docs/potential_configs.md`](potential_configs.md) | Candidate-deck methodology (device-independent); the gfx90c worked example is `docs/gfx90c_tuning_guide.md` §13. |
| [`docs/results.md`](results.md) | Measured-evidence template — populated by the agent per device. |
| [`docs/theoretical_limits.md`](theoretical_limits.md) | Ceilings/limits template — populated by the agent per device. |
| [`docs/knowledge_base.md`](knowledge_base.md) | Knowledge-base template — populated by the agent per device. |

## Bring-up (new device, class B)

| Doc | Role |
|---|---|
| [`docs/starter_pair.md`](starter_pair.md) | The Markdown+JSON starter-pair protocol (Stage A–D). |
| [`docs/starter_template.md`](starter_template.md) | Blank template for a new device. |
| [`docs/gfx902_starter.md`](gfx902_starter.md) + [`.json`](gfx902_starter.json) | Worked example (gfx902 public identity + open questions only). |
| [`docs/operator_runbook.md`](operator_runbook.md) | Class B runbook: best-effort Tensile library on an unsupported AMD platform, end to end. |
| [`docs/operator_campaign.md`](operator_campaign.md) | The multi-session tuning campaign; §18 is the research-prompt discipline. |
| [`docs/setup.md`](setup.md) | Easy-mode onboarding: questions + auto-detect + `.env` + client build + doctor. |

## Research & philosophy

| Doc | Role |
|---|---|
| [`docs/search_philosophy.md`](search_philosophy.md) | Objective, gates, and the agentic guardrails (canonical philosophy). |
| [`docs/research/kernel_tuning.md`](research/kernel_tuning.md) | GCN hardware model + open research directions. |
| [`docs/research/complex_gemm_brief.md`](research/complex_gemm_brief.md) | Complex (CC/ZZ) GEMM research brief. |
| [`docs/comparability.md`](comparability.md) | Multi/single-run comparability triage — the like-for-like admission rule. |
| [`docs/shipped_floor_contract.md`](shipped_floor_contract.md) | The shipped `gfx900` footprint → native replication contract. |

## Harness, tools, and reference

| Doc | Role |
|---|---|
| [`docs/harness_runbook.md`](harness_runbook.md) | The harness runbook (candidate machinery workflows). |
| [`docs/agent_reference.md`](agent_reference.md) | Agentic kernel-tuning harness quick reference (CPU-only). |
| [`docs/agentic_consult.md`](agentic_consult.md) | Automated agentic consult design (CPU-only). |
| [`docs/design_language.md`](design_language.md) | Design-language spec for the HTML acceptance report. |
| [`docs/cli.md`](cli.md) | CLI command reference — `oto <cmd>` vocabulary, flags, migration table. |
| [`docs/toolchain_client.md`](toolchain_client.md) | Toolchain + client contract: layout detection, `oto doctor`, `scripts/build_tensile_client.sh`. |
| [`docs/docstrings.md`](docstrings.md) | Docstring convention for the package. |
| [`docs/documentation_tooling_options.md`](documentation_tooling_options.md) | Decision support for documentation rendering tools. |

## Skills

| Doc | Role |
|---|---|
| [`docs/skills/class_a_developer.md`](skills/class_a_developer.md) | Class A developer agent skill. |
| [`docs/skills/class_b_operator.md`](skills/class_b_operator.md) | Class B operator agent skill. |
| [`docs/skills/caveman.md`](skills/caveman.md) | Token-efficient communication style (optional). Single source of truth: `vendor/caveman/skills/caveman/SKILL.md`. |
| [`vendor/caveman/`](../vendor/caveman/) | Git submodule: [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) (Apache-2.0). Provides the caveman skill, CLI, and the `caveman-compress` tool. |

## Entry points

| Entry | Purpose |
|---|---|
| [`README.md`](../README.md) | This repo's front door: vision, philosophy, quick start. |
| [`docs/getting_started.md`](getting_started.md) | Full guide: prerequisites, setup, bring-up, failure modes. |
| [`docs/overview.md`](overview.md) | This file — the birds-eye view of the documentation. |
| [`claude.md`](../claude.md) | Entry contract, process guardrails, file-ownership rules. |
| [`docs/README.md`](README.md) | Class-tagged registry of owner docs (machine-readable via `docs/docs_index.json`). |
| [`incomplete_work.md`](../incomplete_work.md) | The open-work register (owner-gated items only). |
| [`changelog.md`](../changelog.md) | The append-only history home. |

## License

GPL-3.0-or-later — see [`LICENSE`](../LICENSE) and [`NOTICE`](../NOTICE).
Code: GPL-v3. Docs: CC-BY-SA-4.0.