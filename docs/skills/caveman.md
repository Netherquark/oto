# Caveman — token-efficient communication for oto agents
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


**Entry**: `vendor/caveman/skills/caveman/SKILL.md` (git submodule, upstream:
[JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman), Apache-2.0).
This file is a pointer; the upstream skill is the single source of truth.

## What it is

Caveman mode cuts token burn ~75% by speaking terse while keeping full
technical accuracy. It is a *communication style*, not a content change:
numbers, citations, error messages, code blocks, and verdicts stay exact;
only filler dies.

Use when:
- The user says "caveman mode", "talk like caveman", "use caveman",
  "less tokens", "be brief", or invokes `/caveman`.
- Token efficiency is requested or the conversation is getting long.
- An operator agent is producing a long run report and the user wants
  the headline + numbers, not the narration.

Intensity levels: `lite`, `full` (default), `ultra`, `wenyan-lite`,
`wenyan-full`, `wenyan-ultra`. Switch with `/caveman <level>`.

## oto-specific notes (read before using)

- **Never compress verdicts, numbers, or evidence.** `20 WIN / 18 TIE / 0 LOSS`
  stays verbatim; run ids, cell ids, GFLOPS, file:line citations stay exact.
- **Never compress the UNVERIFIED tag.** Every researched fact stays tagged.
- **Report tables stay tabular.** Caveman prose around them, not inside them.
- **Repo claims stay honest.** "Not autonomous end-to-end, yet" stays that
  sentence even under ultra — do not let compression drop the "yet".
- **Never compress code or command lines.** `python3 -m oto tune --budget 10`
  is not "py tune 10"; commands are exact.
- **Error strings are sacred.** Quote them verbatim, even under ultra.
- **The data-preservation law (`docs/gfx90c_knowledge_base.md` §10) is never
  compressed.** It is a contract, not prose.

## Auto-Clarity

Drop caveman when:
- Security warnings
- Irreversible action confirmations
- Multi-step sequences where fragment order or omitted conjunctions risk misread
- Compression itself creates technical ambiguity
- User asks to clarify or repeats question

Resume caveman after the clear part is done.

## Boundaries

Code/commits/PRs: write normal (never caveman commits). "stop caveman" or
"normal mode": revert. Level persists until changed or session end.

## What you read

- [`vendor/caveman/skills/caveman/SKILL.md`](../../vendor/caveman/skills/caveman/SKILL.md) — the upstream skill (single source of truth).
- [`vendor/caveman/skills/caveman/README.md`](../../vendor/caveman/skills/caveman/README.md) — upstream reference.
- [`docs/skills/class_b_operator.md`](class_b_operator.md) — the operator's job.

## What you never need

- Anything about developing oto (routers, gate internals, test suite semantics)
- `docs/invariants.md` (dev loop, not your own)

## Hard rules

1. NEVER modify any file under `oto/`, `tests/`, or root shims
2. Your only writes: `profiles/<codename>.json`, `docs/<codename>_starter.*`,
   generated device docs, run artifacts under `<codename>_results/` and `<codename>_runs/`
3. If you find a bug in oto, STOP and report it — never patch oto code
4. GPU work happens only in the user's TTY
5. Research output tagged UNVERIFIED until human checks against first-party sources
6. Best-effort ≠ converged (library builds + loads, not parity)
7. **Caveman is a communication style, not a license.** Verdicts, numbers,
   evidence tags, error strings, commands, and the data-preservation law
   stay verbatim under every intensity level. Only narration gets compressed.