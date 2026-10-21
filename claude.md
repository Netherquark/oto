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

### 2.0 Operating rules — the ways this repo's budget gets burned

These override any instinct to "check first", and they apply to every task below.

#### 2.0.1 Re-verification is a defect, not diligence

**Read the owner MD, accept the fact, and move on. Do not re-derive it.**

A fact is **settled** when all three hold: it is written in an owner MD (§3); that
MD states its provenance (measured on this box / read from Tensile source /
derived from a cited measurement); and it is not in that owner's "Verification
gaps" section. Anything else — a number in a code comment, a docstring, a chat
transcript, or one you remember — is **not** settled.

Re-checking a settled fact is *waste*. Re-deriving it in code is a *regression*:
it creates a second home for a fact, which §3.1 forbids.

**Constants have exactly one home.** Peaks, family shapes, dtype maps and ceilings:
`oto/device/peaks.py`. Register-file / LDS / occupancy model:
`oto/tensile/gates/vgpr_model.py` + `occupancy.py`. Tensile's own limits: the
Tensile source, cited by file. The repo `.env`: read by `python-dotenv` in
`oto/runners/toolchain.py`. Import or cite these; **never retype them.**

**Verify budget: one action, for staleness, never for doubt.**

```
STALE?   code no longer matches the owner MD -> update the owner MD, then work
SAME?    code matches the owner MD          -> work. Do not re-check the fact.
UNKNOWN? not in any owner MD                -> a real gap: record it in that
                                              owner's "Verification gaps" and
                                              continue the task
```

Worked examples, all **settled — do not recompute or "fix" them**: `VGPR_PER_CU =
65536` (read from Tensile's own kernel writer, confirmed against the device);
7 CUs on this box; the ±27.8% tie band.

#### 2.0.2 Verdict, ceiling and roofline semantics are decided — apply them

The most expensive failure on this repo is an agent **re-deriving the acceptance
logic instead of applying it**, including arguing with the user about whether a
number is a WIN, a TIE, a ceiling, or a peak.

1. **Do not redefine, re-derive or second-guess** the tie band, the verdict
   thresholds, the realistic ceilings, or the theoretical peaks. Their owner is
   `gfx90c_theoretical_limits.md`; the machine-readable form is `peaks.py`.
   Apply them.
2. **Never present an alternative acceptance framework as a finding.** If you
   believe one is wrong, it goes in the owner MD as a dated, evidence-backed
   proposal with a **`DECISION REQUIRED`** marker, and nothing else. You do not
   get to relabel live cells on the strength of your own reasoning.
3. **The user owns the framework.** A user instruction overrides this file; this
   file overrides an agent's preference; an agent's preference overrides nothing.
4. **One argument, once, in writing, then stop.** Repeating it in chat is not
   diligence, it is the failure mode.

Vocabulary, stated once so it does not get re-litigated: **theoretical peak** =
BLAS flop count at 1800 MHz on the FMA pipe. **Realistic ceiling** = the
acceptance bar, measured-empirical where possible. **WIN/TIE/LOSS** = the A/B
verdict vs the gfx900 floor, graded at the measured noise floor. **RED/ORANGE/
GREEN** = missing / <50% of ceiling / ≥50% of ceiling. **The floor** = the shipped
gfx900 footprint run on this hardware; never a target identity. A ceiling
utilisation over 100% is a known recorded state (a derived ceiling later
out-measured), not an error to re-litigate.

#### 2.0.3 Never poison the corpus

**A benchmark number measured under the wrong conditions is worse than no number**,
because it is stored, it is aggregated, and the next agent cannot tell it from a
good one. Tensile sweeps `ProblemSizes` in deck order and each size's median
absorbs the GPU's clock state at that moment. Two CC-family phase groups measured
the *same* shapes with the *same* configs: 57 phases with 256³ in position 2
median **148.2**; 143 phases with 256³ in position 4 (right after the ~81 ms 2048³
run) median **48.8**. The distributions do not overlap. The 150 µs kernel was
entirely measured at ~⅓ clock.

1. **Never add a candidate to a phase whose `ProblemSizes` order differs from the
   group's.** If the order must change, that is a **new phase**.
2. **Never compare across sweep positions.** A cell's identity is
   `(size, sweep order, position)` — not `(size, config)`.
3. **Never trust a cheap, small kernel's median after a big one.** Small kernels
   (≲1 ms) inherit the clock state left by the previous size. The smallest shapes
   are the most position-sensitive, not the least.
4. **`clock_adjusted: false` means the Δ% is raw.** Check the field before quoting
   a delta; if it is false, say so.
5. **A suspicious result is a bug report, not a win.** If one phase group of an
   otherwise identical family reads 3× low, suspect the sweep and say which you
   suspect, with the evidence.

#### 2.0.4 Subagents: fully briefed

**Why:** if the session's usage runs out, the **main context survives and the
subagent's work is lost**. A subagent is not free scratch space — anything worth
keeping must end up in the main context, as a file the main agent wrote or as text
it pasted back.

1. **No open-ended subagent.** Never write "explore the repo" or "research this
   topic". A prompt must name the exact files to read, the question(s), the output
   shape, and what to do if the answer is "not found".
2. **Inline the context it cannot read for itself** — the ground truth it must
   accept without re-verifying, the constraints it must not violate, and the
   vocabulary from §2.0.2. Do not make it re-derive hardware facts; hand it the
   constants.
3. **Constrain the blast radius.** Every analysis/research subagent prompt states
   the prohibitions by name: no `Tensile`, no `TensileCreateLibrary`, **no GPU
   execution of any kind**, no writing into the repo, scratch to `/tmp` only.
4. **Ask for a response, not a file.** The subagent returns its answer in the
   response text; the main agent decides what to persist. A subagent that writes
   into the repo has produced work that can vanish silently.
5. **Prefer many small briefed subagents over one big open one.**
6. **Never spawn a subagent to decide a framework question.** Framing, verdicts
   and ceilings are main-context decisions. Subagents gather evidence.

Briefing template — a prompt that does not fill in every field is not ready to send:

```
TASK: <one sentence, one deliverable>
CONTEXT: <what the project is, in 3 lines the subagent cannot look up>
GROUND TRUTH (accept these, do not re-verify):
  - <constant / settled fact>  [<owner MD>]
  - <constant / settled fact>  [<owner MD>]
QUESTION(S): <numbered, each answerable without judgement>
OUTPUT: <exact table columns, or numbered findings with file:line citations>
IF NOT FOUND: say "not found" and list what you did read. Do not guess.
HARD PROHIBITIONS:
  - Do NOT run Tensile, TensileCreateLibrary, rocblas-bench.
  - Do NOT execute ANY GPU code. No HIP/C++ programs, no kernel launches,
    no device queries, no microbenchmarks. Read-only + CPU-only.
  - Do NOT write any file into the repo. Scratch to /tmp only.
DO NOT: change acceptance logic, propose new verdict bands, or re-derive the
  numbers in GROUND TRUTH.
```

#### 2.0.5 Use the harness's tooling first; formalise what you prototype.

The repo already owns the loaders, so an agent that writes its own parser gets
numbers that disagree with the ledger and nobody can tell why. The rule is a
three-step loop, not a prohibition:

1. **Look in the harness first.** §2.2's tool table is the index. If a tool
   answers the question, use it — do not re-derive its numbers in a shell
   one-liner, and do not re-parse a format a loader already handles.
2. **Prototype in `/tmp/opencode` when the tool genuinely does not exist.** This
   is expected and fine. What is not fine is stopping there: a measurement that
   lives only in `/tmp` is lost work, and the next agent repeats it.
3. **Land it in the harness once it is functional and useful.** Concretely: a
   module under `oto/` with the §3 ownership docstring (Owns / Does NOT own /
   Public API), constants imported from their one home rather than retyped, a
   CLI reachable as `python3 -m oto.…`, a test that pins its model, and a §2.2
   table row so the next agent finds it. If the prototype overlaps an existing
   module, extend the existing one and record what changed coverage.

Never prototype into the repo tree "to try it live", and never let a `/tmp`
number reach a doc, a deck or a verdict before the repo tool that produces it is
landed.

#### 2.0.6 Never execute GPU code.

The agent machine is the user's **live GNOME desktop session**; a badly-behaved
or runaway kernel hangs the GPU and takes that session with it. This has already
happened — a 2 GB streaming read/write probe hung the GPU and crashed the session.
The word "low-cost proof of concept" is **not** an exception and "just to check
legality" is **not** an exception: the failure mode is a *hang*, not a slowdown, so
there is no size at which it becomes safe. Exhaustively banned: no `Tensile`, no
`TensileCreateLibrary`, no `rocblas-bench`, no `rocprof`, no `hipcc`-compiled
program, no `hipDeviceProp_t`/`rocminfo`-style device query written for this
purpose, no `amdgpu_top` sampling under load, no FMA/latency/bandwidth
microbenchmark of any size. **Everything the agent needs to know about the device
is already in `gfx90c_theoretical_limits.md` §1–§3 and `oto/device/peaks.py`.**
Full Tensile benchmark runs are also not the agent's to launch: only in a TTY, and
only when the USER runs them. Agent work is CPU-only — code, DB and docs, plus the
repo's own CPU-only tools (`check_candidates.py`, `allruns.py`,
`check_tensile_build.py`, `check_library_parity.py`, the gate/test suite, deck
generation, dry-run, result inspection).

### 2.1 Documents

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
11. Read `prior_INSIGHTS_CAVEMAN_ULTRA.md` and `prior_RESEARCH_ARCHIVE.md` ONLY when
    you need the frozen prior measured conclusions (bests, verdicts, levers).
    These are the sole sanctioned prior material; do not reference other prior
    working docs.
12. Check live repo/source/log/DB state before claiming current status.

Read only the documents relevant to the task when scope is narrow; use the full
sequence when changing strategy, architecture, methodology, or the implementation plan.

### 2.2 Do not re-derive what the tooling already answers

Before hand-parsing a `2_BenchmarkData` CSV, a registry row, or a phase's knobs,
run the canonical tools. They drive oto's own loaders, so they cannot drift from
the pipeline that produced the ledger. **Do not write a new parser.**

| Need | Run |
|---|---|
| Best config per cell across ALL runs, knob reach per family, never-exercised knobs | `python3 allruns.py` (`--family ZZ`, `--json out.json`) |
| What has the corpus already measured on this family/cell, at which geometry or axis value, and how did it score? | `python3 -m oto.harness.corpus_census` (`--family SS`, `--typecode HHS`, `--cell SS:1024`, `--knob DepthU`, `--json out.json`) |
| How much of the problem space has been explored, and where are the peaks and the traps? (the graphs) | `python3 -m oto.harness.coverage_graph` (`--family SS`, `--cell HH:256`; writes `gfx90c_results/analysis/coverage/*.svg` + an index page) |
| Does Tensile build every *unmeasured* deck row? (the pre-run sweep) | `python3 -m oto.harness.deck_check` (`--family CC --limit 10`, `--json out.json`; ~75 s/row, resumable, CPU-only) |
| Does Tensile itself accept this config (builds it, and what did it derive)? | `python3 -m oto.harness.tensile_oracle --dtype S --macro 128x128x16 --thread 8x8 --vw 4 --du 16 [--wgm -1] [--extra Knob=Value]` (the legality oracle: Tensile's own verdict + the LDS it allocated) |
| Run the test suite (2m10s serial, 1m27s with `-n auto`, 36s for `-m preflight`) | `python3 -m pytest -q` (`-n auto` to distribute, `-m preflight` for the pre-run subset) |
| What is the *legal* geometry space per cell, what has been measured inside it, and which legal geometry is untried but sits next to a fast one? | `python3 -m oto.harness.coverage_map` (`--family SS`, `--cell SS:256`, `--top 12`, `--json out.json`) |
| Is a deck / candidate list Tensile-legal? (4 gates, exits 1 if not) | `python3 check_candidates.py` (`--family ZZ`, `--deck other.yaml`; a seed overlay is accepted too) |
| Where did a phase fail, and what does that error mean? | the phase's `2_BenchmarkData` + `logs/`, then `python3 -m oto.harness.failure_triage` (the reason census) + `gfx90c_tuning_guide.md` §5 (the M1–M5 mechanisms) |
| **Measured** occupancy of what Tensile actually emitted, joined to its GFLOP/s | `python3 -m oto.harness.asm_occupancy` (`--by gflops\|vgpr\|waves\|count`, `--dtype ZZ`, `--binder`, `--check-calibration`) |
| **Predicted** resident-workgroup bounds of a `kernel_db` row | `python3 -m oto.harness.occupancy_audit` (`--side floor`, `--lds-factor 2`) |
| Emit the never-varied-knob deck (winner tile x one knob change) | `python3 -m oto.tensile.knob_sweep` (`--families CC ZZ`, `--shapes 256x256x256`, `--emit --baseline --trials`) |
| Which knobs has the corpus ever actually varied? | `python3 allruns.py` (`--json out.json`; the `never-exercised knobs` block) |
| Is a cell *really* won, or only its best kernel? (A/B recomputed under every basis) | `python3 -m oto.tools.deck_review score` |
| Is this forward-knob domain deck-safe, or does it generate refusals? | `python3 -m oto.tools.deck_review legality` (`--family CC`) |
| Do the launch gates agree with what Tensile actually built? (false rejections / misses) | `python3 -m oto.harness.gate_calibration` (`--population ours`, `--fail-on-false-reject`) |
| Would a *proposed* gate rule add false rejections? (calibrate a rule in isolation, before implementing it) | `python3 -m oto.harness.rule_calibration` (`--rule <builtin\|module:attr>`, `--fail-on-false-reject`) |
| Why did a phase produce no measurement? (empty-phase reason census) | `python3 -m oto.harness.failure_triage` (`--run <id>`) |
| How many configs per cell, and does a top-K cap lose a winner? | `python3 -m oto.tools.deck_review flood` (`--cap 24`) |

`oto.tensile.knob_sweep` is a **dry run by default** and writes `phases.yaml`
only with `--emit`; that keeps the read-only contract of stage 2 intact while
still giving deck generation a one-line entry point. It exists because
`allruns.py` proves `GlobalSplitU` and `StaggerU` have only ever held one value
each — see `potential_configs.md` §8 for the deck it emits and §8.1 for the
measured legality matrix behind it.

`oto.tools.deck_review` is the pre-deck gate for **candidate generation** and the
one tool that stops a second, divergent opinion forming. `score` exists because
the acceptance report's basis is *best per-kernel median* — an order statistic,
so the arm that draws more kernels has the higher expected max; read `median`
and `floor_best`, not `winner`. `legality` exists because a refused draw costs
one of the mutator's five draws per iteration. All three are CPU-only and
read-only; `docs/harness_runbook.md` explains what each one is for.

The two occupancy tools answer different questions and are not interchangeable:
`asm_occupancy` reads the emitted `.s` (`amdhsa_next_free_vgpr`,
`group_segment_fixed_size`), so its "waves per CU" is a fact about a kernel that
built and ran; `occupancy_audit` reads a `kernel_db` row, so its "resident
workgroups per CU" is a prediction about a candidate. Corrections to the first
are measurement-vs-model; corrections to the second are model-vs-model.
`asm_occupancy --check-calibration` verifies the waves-per-SIMD model against
the AMD/ORNL GFX9 table and exits 1 if it stops fitting — run it before
trusting any occupancy number in this repo.

`knowledge_base.md` §8.1/§8.2 records the parsing traps these tools encode
(multi-size sweeps, string tiles, complex-is-8-bytes, family from `FamilyLabel`).
A phase that dies with `Generating kernel source resulted in error 4` is the
**workgroup register-file rule** (`R*MT0*MT1*LocalSplitU >= 65536`): the
accumulators alone fill the 64K file with no VGPR left for operands, so a config
that carries it is now refused before it launches
(`oto.tensile.gates.occupancy.occupancy_feasible`; `potential_configs.md` §R24
rule 1 / §R27). The gate census must show 0 false rejections — the same rule
refuses 40 of the corpus's empty phases and 0 of its built ones.

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

| `incomplete_work.md` | Open-work register (status-keyed) |
| `adversarial_review.md` | User-run expert-agent audit register (memory leaks, race conditions, logical bugs) + frozen prior baseline |
| `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md` | Frozen prior conclusions (read-only reference; results only) |
| `README.md` | General repository orientation |
| `changelog.md` | Single evolution/milestone log (folds former changes_kb + CHANGELOG + agent logs) |
| `docs/README.md` | The boundary between the MD docs ecosystem and the docstrings |
| `docs/docstrings.md` | The module/function docstring convention (owns/does-not-own/public API) |

| `docs/design_language.md` | Design-language spec for the HTML acceptance report |
| `docs/harness_runbook.md` | Harness runbook (moved from `oto/harness/README.md`) |
| `gfx90c_tuning_guide.md` | Live tuning guidance for gfx90c (current fact only) |
| `kernel_tuning_research.md` | Live research notes on kernel tuning (current fact only) |
| `complex_gemm_research_brief.md` | Live research brief on complex GEMM (current fact only) |
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
    `gfx90c_results/`), the peak table (`oto/device/peaks.py`) and the driver modules
    live in the oto base dir (`--base-dir`, default repo root).
   `PYTHONPATH` = `<TENSILE_ROOT>:…`.
   Override only via explicit `--tensile-root` / `TENSILE_ROOT` (same layout).

- **One-shot, deterministic.** No LLM consultation in the loop. Candidate generation
  is deterministic (harvest → mutate ≤2 knobs). The ONLY exception is the user
  manually invoking an LLM to add candidate configs; that is out-of-band and add-only.
- Native `gfx90c` is the target. Do not substitute RDNA/Navi/MFMA assumptions.
  rocminfo_output.txt is the golden reference for hardware decisions.
- Hardware facts come from project evidence (`rocminfo`, source, runtime, logs), not
  model memory. Do NOT re-derive peak rates (File: `oto/device/peaks.py`).
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
- **Four calibrated resource limits gate every candidate** (all derived from
  Tensile's own source, not guessed). The launch boundary runs them in
  `validate_config`; `python3 -m oto.harness.gate_calibration --population ours`
  proves **0 false rejections** on the corpus:
  1. `ThreadTile0 x ThreadTile1 x dtype_weight <= 128` accumulator VGPRs per
     thread (the hardware cap is 256/thread).
  2. `(MT0 + MT1) x DepthU x bytesPerElement <= 16384` for the LDS tile
     footprint.
  3. `dtype_weight x MT0 x MT1 x LocalSplitU < 65536` — the *workgroup register
     file* (Tensile error 4). ThreadTile cancels, so this caps MacroTile **area**
     at `65536/weight` and is what makes the widest legal complex tiles CC
     `128x64` / ZZ `64x64`/`128x32` (potential_configs.md §R24/§R27).
  4. `LocalSplitU x MT0 x MT1 x computeBytes <= 65536` — the LDS reduction buffer
     (only when `LocalSplitU > 1`; Tensile `MaxLDS`, `SolutionStructs:4108,4334`).
  None is a tuning knob and none may be relaxed to admit a candidate: the
  2026-09-28 overnight run spent 288 of 309 attempts on phases that could never
  build. `bytesPerElement` is NOT the VGPR weight (f64 = 8 bytes but 2 VGPRs).
  A fifth, generator-seam rule (`candidate._non_generative_knob_rejection`)
  refuses `AggressivePerfMode` outside {0,1}, which the assembly path cannot
  emit. **Before any new rule lands it must be probed in isolation with
  `python3 -m oto.harness.rule_calibration --rule <module:attr>` and show 0
  false rejections**, then confirmed in situ with `gate_calibration`; a rule
  that refuses even one built phase is not allowed to ship (the `nt_budget`
  builtin is the worked counter-example — 1 false rejection, rejected).
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
  `--auto` asks five questions (see `oto/runners/auto_prompt.py`): (1) re-measure the
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
- The operating rules in **§2.0** are guardrails, not advice.
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
  `README.md`, `oto/device/peaks.py` comments, etc.) state current fact only. They
  may point at `prior_*` for conclusions, but must never re-narrate the past.
- **`todo.txt` is a USER-ONLY file** (restated here).
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