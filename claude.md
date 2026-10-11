# Tensile gfx90c — oto Entry Contract

/caveman ultra

## 1. Role

USE SUBAGENTS AS LIBERALLY AS POSSIBLE to ensure the main agent's context doesn't
get overpopulated by tangential shit and to parallelise tasks.
This file is the **entrypoint + operating contract** for oto.

oto is a **one-shot deterministic convergence** attempt: replicate the shipped
gfx900 Tensile library footprint as NATIVE gfx90c libraries and converge per-cell by
benchmarking — with NO LLM consultation in the loop. The driver decides next
candidates deterministically (harvest wins → mutate the winner by ≤2 knobs → re-run).
The worst-case contingency is the USER manually calling an LLM to ADD candidate
configs — that is ALL; it is never an in-loop consultation.

This file does not store benchmark history, repo inventory, hypothesis history, bug
history, or implementation detail owned by another MD. Read owner documents instead.

## 2. Startup sequence

For every substantive task:

1. Read `README.md` for repository-level orientation.
2. Read `claude.md` (this file) for the operating contract.
3. Read `implementation_plan.md` for the **current executable plan**.
4. Read `mapping.md` for the shipped-footprint → native-gfx90c replication contract.
5. Read `gfx90c_theoretical_limits.md` for the per-family ceiling/acceptance authority.
6. Read `knowledge_base.md` for the baseline repo/code architecture.
7. Read `changelog.md` for what changed and why (oto evolution).
8. Read `potential_configs.md` for the candidate deck, decisions, and search rules.
9. Read `results.md` for measured evidence (the oto ledger).
10. Read `incomplete_work.md` / `scratch.md` / `adversarial_review.md` as task/audit registers.
11. Read `prior_INSIGHTS_CAVEMAN_ULTRA.md` and `prior_RESEARCH_ARCHIVE.md` ONLY when
    you need the frozen prior measured conclusions (bests, verdicts, levers).
    These are the sole sanctioned prior material; do not reference other prior
    working docs.
12. Check live repo/source/log/DB state before claiming current status.

Read only the documents relevant to the task when scope is narrow; use the full
sequence when changing strategy, architecture, methodology, or the implementation plan.

### 2.1 Do not re-derive what the tooling already answers

Before hand-parsing a `2_BenchmarkData` CSV, a registry row, or a phase's knobs,
run the canonical tools. They drive oto's own loaders, so they cannot drift from
the pipeline that produced the ledger. **Do not write a new parser.**

| Need | Run |
|---|---|
| Best config per cell across ALL runs, knob reach per family, never-exercised knobs | `python3 allruns.py` (`--family ZZ`, `--json out.json`) |
| Is a deck / candidate list Tensile-legal? (4 gates, exits 1 if not) | `python3 check_candidates.py` (`--family ZZ`, `--deck other.yaml`) |
| Where did a phase fail, and what does that error mean? | the phase's `2_BenchmarkData` + `logs/`, then `potential_configs.md` §5.7 |

`knowledge_base.md` §8.1/§8.2 records the parsing traps these tools encode
(multi-size sweeps, string tiles, complex-is-8-bytes, family from `FamilyLabel`).
A phase dying with `Generating kernel source resulted in error 4` is a
**legality-gate miss, not bad luck** — see `potential_configs.md` §5.7.

## 3. MD ownership — do not duplicate

| File | Sole purpose |
|---|---|
| `claude.md` | Entry contract, routing, authority rules, safety/process guardrails |
| `knowledge_base.md` | Baseline repository/codebase knowledge at the captured state |
| `implementation_plan.md` | **Latest/current executable plan only** — self-contained (driver architecture + bug disposition folded in) |
| `mapping.md` | Shipped gfx900 footprint → native gfx90c replication contract |
| `gfx90c_theoretical_limits.md` | Per-family theoretical & realistic ceilings — the acceptance authority |
| `potential_configs.md` | Candidate deck, hypotheses, decisions, convergent-candidate rules |
| `results.md` | Experimental data, parsed results, comparisons, conclusions |
| `tensile_tuning_context.md` | Tuning/search philosophy (one-shot; AI as add-only), hardware truth |
| `scratch.md` | Long-term goal, enumerated task registry, guardrails |
| `incomplete_work.md` | Open-work register (status-keyed) |
| `adversarial_review.md` | User-run expert-agent audit register (memory leaks, race conditions, logical bugs) + frozen prior baseline |
| `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md` | Frozen prior conclusions (read-only reference; results only) |
| `README.md` | General repository orientation |
| `changelog.md` | Single evolution/milestone log (folds former changes_kb + CHANGELOG + agent logs) |
| `docs/README.md` | The boundary between the MD docs ecosystem and the docstrings |
| `docs/docstrings.md` | The module/function docstring convention (owns/does-not-own/public API) |
| `docs/audit.md` | Proposals for whittling the MD tree (not yet applied) |
| `docs/design_language.md` | The visual contract of the HTML acceptance report |
| `plans/REFACTOR_*.md` | The refactor plans + their executable equivalence proofs |

One fact, one canonical home. When information belongs in one owner, update that
owner; do not copy it into several MDs.

### 3.1 The two documentation systems

There are two, and they are not interchangeable:

* **The MD docs ecosystem** (root `*.md` + `docs/`) — higher-level context for
  an agent deciding *what to do*. Author: a human/agent reasoning about the
  project. Lifespan: months. Stated in `docs/README.md`.
* **Docstrings** (inside `oto/**/*.py`) — lower-level context for a maintainer
  reading *one module*. Author: whoever last touched that function. Lifespan:
  days. Convention in `docs/docstrings.md`.

The test is in `docs/README.md`: **if the fact would still be true after the code
were rewritten in another language, it belongs in an MD. If it is a fact about
this function's contract, it belongs in the docstring.**

Three rules that follow from it:

* **The MD tree never quotes a line number.** A line number is a fact about a
  file, and files move. A docstring may cite `file:line` because it is pinned to
  the same commit as the code it describes.
* **The MD tree never restates a code path.** "The driver does X, then Y" is a
  docstring's job; an MD says why X then Y and what evidence made that the order.
* **A docstring never carries a corpus count.** The counts move every time a
  cell is re-triaged; a number transcribed anywhere — MD or docstring — is wrong
  the moment that happens. This is the §5 rule applied to both systems.

## 4. Authority / freshness

When sources disagree, do not silently reconcile them. Precedence for **current
factual state**:

`live repo/source + executable behavior + current DB/logs/results`
→ current owner MDs
→ historical agent logs
→ old summaries/assumptions.

- `implementation_plan.md` = authoritative for **what is planned next**.
- `results.md` = authoritative for **what experiments showed**.
- `potential_configs.md` = authoritative for **candidate deck/decisions**.
- `gfx90c_theoretical_limits.md` = authoritative for **per-family ceilings/acceptance bars**.
- `mapping.md` = authoritative for **what footprint to replicate**.
- `changelog.md` / `knowledge_base.md` = history / baseline (single evolution log).

Never turn "planned", "proposed", "observed", or "historically true" into
"currently true" without evidence.

## 5. Non-negotiable project guardrails

- **No re-inventing known-solved problems.** If the OS, the Python stdlib, or an
  existing industry-standard library already solves it, use that. Never hand-roll
  a substitute for a standard solution: `.env` → `python-dotenv`
  (`load_dotenv`), toolchain/bin discovery → `hipconfig` + `shutil.which`,
  locking/persistence → stdlib `sqlite3`/`json`, CLI → `argparse`. Do the same for any other standard problem-solution set you come across.
- **Tensile tree is one path** (location from the repo-root `.env` key
  `TENSILE_ROOT`, e.g. `${TENSILE_ROOT:-<checkout>}`). Driver shells out to
   `Tensile/bin/Tensile` and `Tensile/bin/TensileCreateLibrary` **in that tree**.
    Native gfx90c support = a 2-file minimal Tensile patch (`Tensile/Common.py` +
    `Tensile/AsmCaps.py`) **in that tree**. Run ledgers (`gfx90c_runs/`,
    `gfx90c_results/`), the peak table (`gfx90c_common.py`) and the driver modules
    live in the oto base dir (`--base-dir`, default repo root).
   `PYTHONPATH` = `<TENSILE_ROOT>:…`.
   Override only via explicit `--tensile-root` / `TENSILE_ROOT` (same layout).

- **One-shot, deterministic.** No LLM consultation in the loop. Candidate generation
  is deterministic (harvest → mutate ≤2 knobs). The ONLY exception is the user
  manually invoking an LLM to add candidate configs; that is out-of-band and add-only.
- Native `gfx90c` is the target. Do not substitute RDNA/Navi/MFMA assumptions.
  rocminfo_output.txt is the golden reference for hardware decisions.
- Hardware facts come from project evidence (`rocminfo`, source, runtime, logs), not
  model memory. Do NOT re-derive peak rates (File: `gfx90c_common.py`).
- `gfx900` spoof is a reference baseline/floor, never target identity, never a signal.
- Never silently weaken acceptance criteria (subset success ≠ whole-library success;
  one good run ≠ convergence).
- Benchmark claims require benchmark evidence; build success is not performance
  validation. Correctness gates performance claims.
- Avoid redundant experiments; check the registry before adding equivalent work.
- Preserve experiment provenance and historical results. Benchmark data is NEVER
  deleted; all data streams are append-only (canonical law: `knowledge_base.md` §10).
- **Ask before deleting/replacing files or materially changing existing experiments.**
- Do not overwrite existing tests/results merely to make a cleaner implementation.
- Do not silently retire/revive/rename/reinterpret phases; the driver's
  `--targets`/`--family`/`--pattern`/`--shape` scoping is the only phase-selector.
  The spoof floor lives in a dedicated `gfx900_ref_*` run chain (base +
  `--resume` continuations), never as a phase-1 slot of the native deck.
- Treat telemetry gaps as telemetry gaps; do not invent measurements or use broken
  telemetry as proof of behavior.
- Do not use a mathematically or physically unjustified normalization just because it
  improves presentation. Revalidate derived conclusions when methodology changes.
- **/tmp-PoC-first default.** Every code change — not only `port_tensile.py` /
  its modules — is prototyped in `/tmp` and tested there before landing;
  in-tree files are edited only after the PoC passes. Throwaway scripts never
  land in the repo root.
- LLM output is hypothesis input, not architecture authority. HW decides. DB remembers.
- **Every family deck must be able to reach the 16 B global-load cap.** The
  classic path caps a contiguous load at `GLVW * bytesPerElement <= 16`. A tile
  reaching only 8 B leaves ~5-15% on the table for no legal reason, and the
  native deck hardcoded exactly that for SS/HH/DD. `cap_vector_width()` derives
  the width; `test_occupancy_gate.py` fails if any family deck cannot reach 16 B.
  Do not re-add a hand-picked narrower width as the only option.
- **Two measured resource limits gate every candidate, on two different
  parameters** (both derived from Tensile's own kernel writer, not guessed):
  `ThreadTile0 x ThreadTile1 x dtype_weight <= 128` accumulator VGPRs per thread
  (the hardware cap is 256/thread), and
  `(MT0 + MT1) x DepthU x bytesPerElement <= 16384` for the LDS tile footprint.
  Neither is a tuning knob and neither may be relaxed to admit a candidate: the
  2026-09-28 overnight run spent 288 of 309 attempts on phases that could never
  build. `bytesPerElement` is NOT the VGPR weight (f64 = 8 bytes but 2 VGPRs).
- The native-vs-spoof A/B floor is the dedicated `gfx900_ref_*` run chain (recalled,
  never re-run). `--auto` auto-resumes an incomplete floor, but it **always
  proceeds to native tuning** — the floor is attempted, never a gate. If the floor
  is incomplete or failed, the run sets `reference_floor_authoritative = False`
  and the acceptance report is prefixed `PROVISIONAL FLOOR`; its A/B verdicts are
  indicative only and must not gate a release. Rationale: three consecutive
  overnight runs spent their entire budget on the floor and measured nothing
  native. Verdicts are authoritative **only** when all mandatory (T1) phases are
  decided.
- **`--auto` ASKS before it runs; the tiers only classify.** In a TTY every
  `--auto` asks five questions (see `auto_prompt.py`): (1) re-measure the
  ILLEGAL reference cells? (2) re-measure the UNDER-SPECIFIED cells? (3)
  re-attempt the UNREPRODUCIBLE cells? (4) how many iterations (default
  **10**)? (5) how many mutations per candidate (default **3**)? The answers
  become an `AutoPlan`, and that plan — not a hardcoded default, not a tier —
  governs the run. Non-interactive invocations take the defaults and print that
  they did. The agent must not add a default that pre-answers these, and must
  not start a reference run the user declined.
- **Never write a corpus count down — anywhere.** The tier sizes printed in the
  banner and the counts in those three questions are read live by
  `auto_prompt._read_counts()` from the audited manifest. A number transcribed
  into a docstring, a README transcript, a test, or a comment is wrong the
  moment a cell is re-triaged, and one shown in a question the user is answering
  is worse than showing none. `test_auto_prompt.py` and
  `test_reference_tiers.py` both assert structure and live agreement, never a
  literal corpus size. Cite the *date and decision* in prose instead
  ("16 SS cells re-triaged on 2026-09-28"), never the resulting totals.
- **Every tier decision is a question; nothing is hardcoded.** T2 is pinned via
  `release_held`, T3 was formerly *dropped unconditionally* on the reasoning that
  re-running only reproduces the failure. That is a judgement about *this*
  Tensile build, not a property of the cell, so T3 is now question 3 with
  `release_drop`, defaulting to dropped. Do not reintroduce an unconditional
  drop, and do not bundle a T3 opt-in with a T2 opt-in — they release
  independently (`--release-under-specified` / `--release-unreproducible`).
- **NEVER run full Tensile benchmark runs during code development.** This is not a
  TTY. Full runs are ONLY allowed in a TTY, and ONLY when the USER runs them. During
  agent work: no `Tensile`/`TensileCreateLibrary` full benchmarks, no sustained GPU
  phases, no marathon/deck runs. Code/DB/doc work only. The agent may build, validate,
  test, generate decks, dry-run and inspect results — never launch full runs.
- **`todo.txt` is a USER-ONLY file. The agent never reads, writes, greps, renames,
  touches, or commits it — in any context, for any reason.** (Cross-ref above
  and the commit-discipline rule below.) Its contents are not part of the
  agent-visible state; treat its non-existence from the agent perspective as
  required. Do not access, modify, or reference todo.txt during agent execution.
- **Commit discipline — never pollute the pristine repo.** The agent never
  commits or stages a file that is not already tracked unless the user
  explicitly sanctions it. `git add -A` / `git add .` are strictly forbidden.
  Stage explicit paths only. The user working files `proposal.md`, `todo.txt`,
  and `command.txt` are intentionally untracked (and NOT in `.gitignore`), so a
  blanket add would sweep them into a commit. Before committing, verify
  `git status --porcelain` shows no untracked user file staged. Never add
  random untracked files, proposal.md, todo.txt, or command.txt to the repo.
- Convergence claims need the agent gate: ≥3 distinct configs tested, ≥2 independent
  runs (≥6 seeds), CV ≤ 15% per cell, and 0 RED contract cells. The ≤1% run-to-run
  drift bar applies to retirement eligibility, not to convergence.
  `command.txt` are intentionally untracked (and NOT in `.gitignore`), so a
  blanket add would sweep them into a commit. Before committing, verify
  `git status --porcelain` shows no untracked user file staged.
- Convergence claims need the agent gate: ≥3 distinct configs tested, ≥2 independent
  runs (≥6 seeds), CV ≤ 15% per cell, and 0 RED contract cells. The ≤1% run-to-run
  drift bar applies to retirement eligibility, not to convergence.

## 6. Change discipline

Before changing code: inspect current diff/status; identify affected owner MDs; check
existing experiments/results/config fingerprints; preserve prior behavior unless the
change is explicitly intended; record rationale in the owning document.

After changing code: run the narrowest useful validation first; then required
acceptance checks from `implementation_plan.md`; update `results.md` from actual
generated data, not hand-edited conclusions; update `changelog.md` only for durable
state changes; update `potential_configs.md` for candidate outcomes; bug disposition
lives in `implementation_plan.md` (Triaged fixes section).

## 7. Experiment loop

`observe → hypothesize → implement/configure → correctness → benchmark → compare → retain/reject → record → repeat`

Do not claim "converged", "optimal", "GTG", or "fully implemented" unless acceptance
checks are demonstrated and remaining gaps are stated.

## 8. Documentation hygiene

### 8.1 Legacy silence & file boundaries

- **Never reference removed machinery.** Anything that has been deleted from the
  codebase — by any name or description — must never reappear in code, configs,
  or docs. Zero occurrences, always.
- **History has exactly two sanctioned homes:** `changelog.md` (append-only) and
  the frozen `prior_*` files. Live docs (this file, `implementation_plan.md`,
  `potential_configs.md`, `knowledge_base*`, `results.md`, `mapping.md`,
  `README.md`, `gfx90c_common.py` comments, etc.) state current fact only. They
  may point at `prior_*` for conclusions, but must never re-narrate the past.
- **`todo.txt` is a USER-ONLY file.** The agent never reads, writes, greps,
  renames, or touches it — in any context, for any reason.
- One fact, one canonical home. Fix stale docs in the owner + dependent generated
  artifacts; do not create competing summaries. Do not inflate this file with project
  history that belongs elsewhere.
- **When you move code, its docstring moves with it** — in the same commit. A
  module that moved without its docstring is a module whose "owns" clause is now
  describing someone else's code. The `Does NOT own` clause that names it is then
  wrong too, and only the next reader finds out.
- **A docstring is not the place for a decision.** If you find yourself writing
  "we chose X because Y" in a docstring, ask whether Y is still true after the
  code is rewritten in another language. If it is, it belongs in the owner MD;
  if not, it is a contract and keep one line of it, not a paragraph.

## 9. Task routing

- "What is this repo?" → `knowledge_base.md`
- "What changed / why?" → `changelog.md`
- "What's next?" → `implementation_plan.md`
- "What footprint do we replicate?" → `mapping.md`
- "What are the ceilings / acceptance bars?" → `gfx90c_theoretical_limits.md`
- "What candidates?" → `potential_configs.md`
- "What bug / fix status?" → `implementation_plan.md` (Triaged fixes section)
- "What did runs prove?" → `results.md`
- "How does the driver work?" → `implementation_plan.md` (The Driver Architecture)
- "What is the search strategy?" → AI tuning context MD
- "What are the frozen prior conclusions?" → `prior_INSIGHTS_CAVEMAN_ULTRA.md` /
  `prior_RESEARCH_ARCHIVE.md` (measured results only), then verify against current sources.

## 10. Final response discipline

End substantive work with only:

**Done:** verified completed work.
**Evidence:** source/run/test proving it.
**Pending:** unproven or unfinished requirements.
**Next:** concrete next action, only when useful.

No optimistic wording unsupported by evidence.