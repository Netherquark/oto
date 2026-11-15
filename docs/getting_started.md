# Getting started with oto

> **Ecosystem: Human.** Agents pick their class first — operators read
> [`docs/operator_runbook.md`](operator_runbook.md), developers read
> [`AGENTS.md`](../AGENTS.md).
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


The full guide to bringing oto up on a box, running a campaign, and
producing a best-effort library. For the birds-eye view of the project
documentation, see [`docs/overview.md`](overview.md). For the philosophy,
see [`README.md`](../README.md).

## 1. Prerequisites

- Linux (Fedora / RHEL / Ubuntu tested), Python ≥ 3.10. Any modern
  distribution with a working ROCm toolchain is expected to work; the
  bring-up steps are distribution-agnostic.
- An AMD GPU oto has never seen (gfx90c, gfx902, …).
- A ROCm 7.x install (TheRock nightly recommended) — Python SDK venv
  or extracted tarball. **Never** the ROCm 6.4.x system install for new
  work; the nightly is what the gfx90c reference was measured against.
- The Tensile checkout (`rocm-libraries/shared/tensile`).
- `cmake ≥ 3.21`, `amdclang++` (from the SDK).
- Optional: an API key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
  `OTO_API_KEY`) for the agent-research phase.

## 2. Easy mode (recommended)

See [`docs/setup.md`](setup.md) for the full question flow, the full-SDK
rule, and troubleshooting. Short version:

```bash
git clone <this repo> && cd oto
python3 -m oto setup --yes          # prepare toolchain + .env + client
python3 -m oto setup                # guided walk
python3 -m oto setup --dry-run      # print the plan only
```

## 3. Manual setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env                # fill TENSILE_ROOT and ROCM_PATH
scripts/build_tensile_client.sh --rocm-prefix <ROCM_PREFIX> \
    --tensile-root <TENSILE_ROOT>
python3 -m oto doctor              # should report 0 FAIL
```

The client needs a *full* SDK prefix. See
[`docs/toolchain_client.md`](toolchain_client.md).

## 4. Bring a new device up from zero

Stage A–D protocol: [`docs/starter_pair.md`](starter_pair.md).
Class B contract, verification matrix, failure modes, never-do:
[`docs/operator_runbook.md`](operator_runbook.md).
Blind/uninformed convergence on gfx902 (worked example):
[`docs/gfx902_blind_convergence.md`](gfx902_blind_convergence.md).

Interactive runtime controls (skip/end/quit) are documented in
[`docs/operator_runbook.md`](operator_runbook.md).

## 5. Verification matrix and failure modes

See [`docs/operator_runbook.md`](operator_runbook.md) §7–§9.

## 6. CLI command reference

See [`docs/cli.md`](cli.md). Easiest entry point:

```bash
python3 -m oto help
python3 -m oto setup --yes
```