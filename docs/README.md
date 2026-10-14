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

| File | Kind | Owns |
|---|---|---|
| `claude.md` | **Ecosystem (root)** | The entry contract, routing, authority rules, guardrails |
| `README.md` | Ecosystem | General repository orientation |
| `docs/README.md` | **This file** — the boundary itself |
| `docs/docstrings.md` | Ecosystem | The docstring convention (what a module docstring must contain) |

| `implementation_plan.md` | Ecosystem | The current executable plan only |
| `mapping.md` | Ecosystem | The shipped-footprint replication contract |
| `gfx90c_theoretical_limits.md` | Ecosystem | Per-family ceilings, the acceptance authority |
| `potential_configs.md` | Ecosystem | The candidate deck, decisions, search rules |
| `results.md` | Ecosystem | Measured evidence |
| `knowledge_base.md` | Ecosystem | Architecture knowledge at the captured state |
| `changelog.md` | Ecosystem | Evolution log (append-only) |
| `incomplete_work.md` | Ecosystem | Open-work register |
| `prior_*.md` | Ecosystem (frozen) | Prior conclusions, results only |
| `tensile_tuning_context.md` | Ecosystem | Tuning/search philosophy |
| `adversarial_review.md` | Ecosystem | Audit register |
| `plans/REFACTOR_*.md` | Ecosystem | The refactor plans this package was built against |
| `plans/verify_*.py` | Ecosystem | The executable equivalence proofs for those plans |
| `docs/design_language.md` | Ecosystem | Design-language spec for the HTML acceptance report |
| `docs/harness_runbook.md` | Ecosystem | Harness runbook (moved from `oto/harness/README.md`) |
| `oto/**/*.py` | **Docstrings** | Everything about one function's contract |

## Reading order for a new agent

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

## The docstring convention

`docs/docstrings.md` is the convention itself. Every module in `oto/` follows it:
what it owns, what it deliberately does not own, and the public API a caller
needs. It is enforced by review, not by a linter, because the "does not own"
clause is the part that drifts and only a reader can catch that.
