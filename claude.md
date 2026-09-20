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

One fact, one canonical home. When information belongs in one owner, update that
owner; do not copy it into several MDs.

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
    `Tensile/AsmCaps.py`) **in that tree**. Run ledgers = `gfx90c_runs/` +
   `gfx90c_results/` **in that tree**. Peak table = that tree's `gfx90c_common.py`.
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
- Do not silently retire/revive/rename/reinterpret phases; the driver's `--phases`
  scoping is the only phase-selector (phase-1 floor stays first-ever-run-only by
  contract).
- Treat telemetry gaps as telemetry gaps; do not invent measurements or use broken
  telemetry as proof of behavior.
- Do not use a mathematically or physically unjustified normalization just because it
  improves presentation. Revalidate derived conclusions when methodology changes.
- Every change to `port_tensile.py` / its modules is PoC'd in `/tmp` and
  tested before landing.
- LLM output is hypothesis input, not architecture authority. HW decides. DB remembers.
- Wait for the two scoped control runs (`--phases 1 31`, then `--phases 20 25`) before
  re-deriving native-vs-spoof verdicts under fixed math.
- **NEVER run full Tensile benchmark runs during code development.** This is not a
  TTY. Full runs are ONLY allowed in a TTY, and ONLY when the USER runs them. During
  agent work: no `Tensile`/`TensileCreateLibrary` full benchmarks, no sustained GPU
  phases, no marathon/deck runs. Code/DB/doc work only. The agent may build, validate,
  test, generate decks, dry-run and inspect results — never launch full runs.
- **`todo.txt` is a USER-ONLY file. The agent never reads, writes, greps, renames,
  or touches it — in any context, for any reason.** (Cross-ref §8.1.) Its contents
  are not part of the agent-visible state; treat its non-existence from the agent
  perspective as required.
- Super-sample / adaptive-repeat policy applies before convergence claims; a cell
  needs ≥2 independent runs AND ≥3 configs tested AND ≤1% movement over the last 2
  independent runs to be considered converged.

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