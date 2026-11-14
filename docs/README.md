# oto documentation ecosystem

Two documentation systems live in this repo, and they are **not** the same
thing. Confusing them is the failure mode this file exists to prevent.

```
┌─────────────────────────────────────────────────────────────┐
│  DOCS ECOSYSTEM  (this directory + the root *.md files)     │
│  Higher-level context. For an agent deciding what to do.    │
│  Author: a human/agent reasoning about the PROJECT.          │
│  Lifespan: months. Changes when the plan changes.            │
├─────────────────────────────────────────────────────────────┤
│  DOCSTRINGS  (inside oto/**/*.py)                            │
│  Lower-level context. For a maintainer reading ONE module.   │
│  Author: whoever last touched that function.                 │
│  Lifespan: days. Changes when the code changes.              │
└─────────────────────────────────────────────────────────────┘
```

## Two agent classes

This ecosystem serves two different agent roles. An agent that hasn't picked
one defaults to the wrong entry document. Pick first, then read.

| Class | Who | Entry document | Optimises for |
|---|---|---|---|
| **A — developer** | coding agent working **on** oto | `claude.md` | the codebase itself |
| **B — operator** | agent **using** oto to produce a library for an unsupported platform | `docs/operator_runbook.md` (then [`docs/operator_campaign.md`](operator_campaign.md) for the tuning campaign) | a best-effort library for the target device, then a converged one |

Both classes share: this file's boundary (below), `claude.md`'s invariants
(§2.0), the append-only ledger, the no-GPU-outside-the-user's-TTY rule, and
the registry below (a doc you add or edit is a doc you register). Class B
additionally: the human verification gate (§4 of the runbook) and research
output tagged UNVERIFIED until a human checks it against first-party
sources. The registry's `Class` column marks which audience each document
serves — `dev`, `operator`, or `shared`.

### Who reads what (agent-role map)

| Agent role | Entry doc (read first) | Then | Never needs |
|---|---|---|---|
| Class A — coding agent working **on** oto | `claude.md` | `docs/agent_reference.md` (harness quick reference), `docs/docstrings.md` (docstring convention), `docs/harness_runbook.md` (harness guardrails), `docs/implementation_plan.md` (the live plan) | operator starter files (`docs/starter_*.md`), `docs/operator_runbook.md` §1–§4 as a procedure |
| Class A — reviewer/auditor subagent | `docs/audit_register.md` + `claude.md` §4 (authority) | `changelog.md` (what landed), `git log` | GPU runs; however careful, the GPU is user-TTY-only |
| Class B — operator agent **using** oto on an unsupported platform | `docs/operator_runbook.md` (bring-up) → `docs/operator_campaign.md` (the tuning campaign) | `docs/starter_pair.md` → `docs/starter_template.md` → `docs/gfx902_starter.md` (worked example), then the class-B steps verbatim | anything about developing oto (routers, gate internals, test suite semantics) beyond "the gates exist and refuse bad configs" |
| Class B + API — doc agents (agent-1 / agent-2 / potential_configs meta-agent) | the starter file + `docs/operator_runbook.md` | their outputs are written into `profiles/<cn>.json`, the per-device generated docs (`docs/gfx90c_theoretical_limits.md`, `docs/gfx90c_tuning_guide.md` and their siblings), `docs/potential_configs.md` — generated device docs, registered under this file's registry | the repo's own dev docs as *content* (they describe how oto works, not what this device needs) |
| Any agent, any class | `docs/comparability.md` when touching multi/single-run verdicts | the like-for-like admission rule before trusting any A/B delta | hand-editing `kernel_db.json` / `registry.db` (append-only) |

Class rules that follow from the map: a Class A agent that starts from
`docs/operator_runbook.md` has picked the wrong entry; a Class B agent that
opens `docs/implementation_plan.md` is reading the dev loop, not its own. Both
classes register every doc they add here, with the right `Class` value.

## The boundary, stated as a test

> **If the fact would still be true after the code were rewritten in another
> language, it belongs in the docs ecosystem. If it is a fact about *this*
> function's contract, it belongs in the docstring.**

Corollaries:

* **The docs ecosystem never quotes a line number.** A line number is a fact
  about a file, and files move. A docstring may cite `file:line` because it is
  pinned to the same commit as the code it describes.
* **The docs ecosystem never restates a code path.** "The driver does X, then Y"
  is a docstring's job. The docs ecosystem says *why* X then Y, and what
  evidence made that the order.
* **A docstring never carries a rationale that outlives the function.** "We
  chose 7-CU wave quantization because gfx90c has 7 CUs" is project rationale
  and belongs in the docs; "this returns the widest legal VectorWidth" is the
  contract and belongs in the docstring.

## Which file owns what

| File | Class | Kind | Owns |
|---|---|---|---|
| `claude.md` | shared | **Ecosystem (root)** | The entry contract, routing, authority rules, guardrails |
| `README.md` | shared | Ecosystem | General repository orientation |
| `docs/README.md` | shared | **This file** — the boundary and the registry itself |
| `docs/docstrings.md` | dev | Ecosystem | The docstring convention (what a module docstring must contain) |

| `docs/implementation_plan.md` | dev | Ecosystem | The current executable plan only |
| `docs/shipped_floor_contract.md` | shared | Ecosystem | The shipped-footprint replication contract |
| `docs/gfx90c_theoretical_limits.md` | dev | Ecosystem | Per-family ceilings, the acceptance authority |
| `docs/gfx90c_tuning_guide.md` | dev | Ecosystem | The tuning cookbook: legal knob domains (§1.1–§1.2), what wins, the virgin-axis census (§9.1) |
| `docs/research/kernel_tuning.md` | shared | Ecosystem | Research only: hardware model, Tensile source mechanics, unverified-claim register |
| `docs/research/complex_gemm_brief.md` | dev | Ecosystem | Research only: complex (C/Z) GEMM on the pre-MFMA assembly path |
| `docs/potential_configs.md` | dev | Ecosystem | The candidate deck, decisions, search rules |
| `docs/results.md` | dev | Ecosystem | Measured evidence |
| `docs/knowledge_base.md` | dev | Ecosystem | Architecture knowledge at the captured state |
| `changelog.md` | shared | Ecosystem | Evolution log (append-only) |
| `incomplete_work.md` | dev | Ecosystem | Open-work register |
| `archive/prior_insights.md` | dev | Ecosystem (frozen) | Prior conclusions, results only |
| `archive/prior_research_archive.md` | dev | Ecosystem (frozen) | Prior-campaign supporting material |
| `docs/search_philosophy.md` | shared | Ecosystem | Tuning/search philosophy (incl. §S the autotuning strategy cross-check) |
| `docs/audit_register.md` | dev | Ecosystem | Audit register |
| `plans/REFACTOR_*.md` | dev | Ecosystem | The refactor plans this package was built against |
| `plans/test_optimization.md` | dev | Ecosystem | Test-suite optimisation plan |
| `plans/CLI_UX_REWORK.md` | dev | Ecosystem | CLI UX rework plan — one `oto` front, verb-first subcommands, POSIX/GNU/clig.dev |
| `plans/AGENTIC_POTENTIAL_CONFIGS_PLAN.md` | dev | Ecosystem | Automated agentic consult: API key → `docs/potential_configs.md` with fewest GPU legs |
| `plans/RENAME_AND_DOC_CLEANUP_PLAN.md` | dev | Ecosystem | Detailed rename + doc cleanup plan: 40 module renames, 9 test renames, 5.1 device-fact violations, 3 support-module unifications, 4-phase migration order (read-only proposal) |
| `plans/INTUITIVE_NAMING_AND_DOC_SLIMMING_PLAN.md` | dev | Ecosystem | Proposal: intuitive rename + docs slimming pass — 34 module renames, 13 test renames, root/docs/plans ephemera deletion, AI-slop sweep |
| `plans/MASTER_PLAN.md` | dev | Ecosystem | Master plan: full session ledger, open work register, two development models, convergence pipeline, guardrails, verification commands, file map |
| `archive/*.md` | dev | Ecosystem (frozen) | Prior corpus archives — evidence snapshots, not docs |
| `docs/comparability.md` | shared | Ecosystem | Multi/single-run comparability triage — the like-for-like admission rule |
| `docs/design_language.md` | dev | Ecosystem | Design-language spec for the HTML acceptance report |
| `docs/agent_reference.md` | dev | Ecosystem | Agentic kernel-tuning harness quick reference (CPU-only) |
| `docs/cli.md` | shared | Ecosystem | CLI command reference — `oto <cmd>` vocabulary, flags, migration table |
| `docs/docs_index.json` | shared | Ecosystem | Machine-readable docs registry index (generated by `oto/docs_index.py`) |
| `docs/skills/*.md` | shared | Ecosystem | Per-class agent skill definitions (Class A developer, Class B operator) |
| `docs/harness_runbook.md` | dev | Ecosystem | Harness runbook |
| `docs/operator_runbook.md` | operator | Ecosystem | **Class B entry** — best-effort library on an unsupported AMD platform, end to end |
| `docs/operator_campaign.md` | operator | Ecosystem | The persistent autonomous tuning campaign: corpus study → straggler classes → candidate routes → consultation triggers |
| `docs/starter_pair.md` | operator | Ecosystem | The starter Markdown+JSON pair protocol |
| `docs/starter_template.md` | operator | Ecosystem | Zero-spec pair template the operator copies |
| `docs/gfx902_starter.md` | operator | Ecosystem | gfx902 worked starter (public identity + open questions only) |
| `oto/README.md` | dev | Package | The `oto/` package map (regenerate with `python3 -m oto.inventory`) |
| `oto/**/*.py` | dev | **Docstrings** | Everything about one function's contract |

## The quality gates

The developer side of this ecosystem is enforced, not just documented. Five
tree-walking guard tests run in the suite and on every commit; a change that
violates them fails before review:

| Check | Command | Enforces |
|---|---|---|
| Pyflakes | `python3 -m pytest tests/test_pyflakes.py -q` | no undefined names, no redefinitions, no empty f-strings |
| Ruff | `python3 -m pytest tests/test_ruff.py -q` | the pinned rule set in `ruff.toml` (pycodestyle, pyflakes, bugbear, pyupgrade, import sorting, comprehensions, pep8-naming) |
| py_compile | `python3 -m pytest tests/test_py_compile.py -q` | every tracked `.py` byte-compiles |
| File length | `python3 -m pytest tests/test_file_length.py -q` | no tracked file over 600 lines (grandfathered list ratchets down) |
| Function length | `python3 -m pytest tests/test_function_length.py -q` | no function over 60 lines |

```bash
# all four, one shot
python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q

# fast path: only the files git reports as modified/staged
OTO_GUARD_FILES=1 python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q
```

The full scan stays the CI default on purpose (a guard that only looks at what
you touched is not a guard). The py_compile gate additionally covers files no
test imports — an uncompiled-but-tracked script fails here instead of at first
use. Class B (operator) docs deliberately do not carry this section: an
operator consumes the library; the gates guard the library's source.

## Reading order for a new coding agent (class A)

`claude.md` — start at **§2.0 (operating rules)**, then §2.1 (documents) →
`README.md` (orientation) → the owner MD for the task at hand (`claude.md`
section 9 routes you) → the module docstring of the file you are about to edit.
Nothing else. In particular:

* Do **not** read `changelog.md` to find out what the code does now — read the
  module docstring. The changelog is history.
* Do **not** read `incomplete_work.md` to find out whether something works — run
  the test suite. The register is a to-do list, not a status.
* Do **not** read a docstring to find out *why* the project made a choice — that
  is in the ecosystem MD that owns the decision.
* Do **not** re-verify a settled fact just because it looks surprising. If an
  owner MD states it with provenance, it is settled (`claude.md` §2.0.1).

## Reading order for the operator agent (class B)

`docs/operator_runbook.md` — the runbook is the entry point (§0 preconditions
first; after the best-effort library exists, `docs/operator_campaign.md` is the
living procedure for the tuning campaign). Then: `claude.md` **§2.0 only** (the shared invariants) →
[`docs/starter_pair.md`](starter_pair.md) (the pair protocol) →
[`docs/agent_reference.md`](agent_reference.md) (CPU-only harness commands) →
[`plans/REFACTOR_2_UNIVERSAL_GPU.md`](../plans/REFACTOR_2_UNIVERSAL_GPU.md) (implementation context and backlog) → the module
docstring of anything you edit. Do **not** adopt the campaign-specific
framing in `claude.md` (gfx90c convergence, the shipped-floor acceptance
framework): on a new platform there may be no floor library to beat, and
best-effort correctness is the bar that exists everywhere.

## The docstring convention

`docs/docstrings.md` is the convention itself. Every module in `oto/` follows it:
what it owns, what it deliberately does not own, and the public API a caller
needs. It is enforced by review, not by a linter, because the "does not own"
clause is the part that drifts and only a reader can catch that.
