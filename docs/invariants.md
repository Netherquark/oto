# oto — developer operating contract (moved from claude.md)

> **Ecosystem: Developer agent (Class A).** Operator agents read
> [`docs/operator_runbook.md`](operator_runbook.md); humans read
> [`docs/getting_started.md`](getting_started.md).

owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d

> Tier 1 on-demand reference. Entry point is `AGENTS.md` (Tier 0).
> Moved here verbatim to keep Tier 0 short; no content deleted.

# Tensile gfx90c — oto Entry Contract

/caveman ultra

## 1. Role

**Two agent classes run this repo.** (A) **Coding agents** improving oto itself:
this file is your entry — read §2 next. (B) **Operator agents** using oto to
produce a best-effort Tensile library for an *unsupported* AMD platform: your
entry is [`docs/operator_runbook.md`](docs/operator_runbook.md), not this
file — though §2.0 below and the `docs/README.md` boundary apply to you
unchanged. (A) optimises the codebase; (B) optimises a device library. Don't
blend them: this file's campaign framing (gfx90c convergence, the shipped-floor
acceptance framework) does not transfer to (B).

USE SUBAGENTS AS LIBERALLY AS POSSIBLE to ensure the main agent's context doesn't
get overpopulated by tangential shit and to parallelise tasks.
This file is the **entrypoint + operating contract** for oto.

oto is an **agentic** system: replicate the shipped
gfx900 Tensile library footprint as NATIVE gfx90c libraries and converge per-cell by
benchmarking. The **acceptance path is deterministic** — Tensile generates, the
compiler validates, the hardware decides, and the driver selects next candidates by
harvest wins → mutate the winner by ≤2 knobs → re-run. The **agent layer proposes,
never decides**: `oto agent consult` (CPU-only starter → gate-legal rows) and
agent-1 / agent-2 draft research docs with ISA-cited prompts; LLM output is
hypothesis input, never a verdict, never an in-loop consultation.

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
`oto/device/loader.py`. Register-file / LDS / occupancy model:
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

Worked examples, all **settled — do not recompute or "fix" them**: `vgpr_per_cu =
65536` (read from Tensile's own kernel writer, confirmed against the device; the
profile field is now `vgpr_per_cu`);
7 CUs on this box; the ±27.8% tie band.

#### 2.0.2 Verdict, ceiling and roofline semantics are decided — apply them

The most expensive failure on this repo is an agent **re-deriving the acceptance
logic instead of applying it**, including arguing with the user about whether a
number is a WIN, a TIE, a ceiling, or a peak.

1. **Do not redefine, re-derive or second-guess** the tie band, the verdict
   thresholds, the realistic ceilings, or the theoretical peaks. Their owner is
   `docs/gfx90c_theoretical_limits.md`; the machine-readable form is `profiles/gfx90c.json`.
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
is already in `docs/gfx90c_theoretical_limits.md` §1–§3 and `oto/device/loader.py`.**
Full Tensile benchmark runs are also not the agent's to launch: only in a TTY, and
only when the USER runs them. Agent work is CPU-only — code, DB and docs, plus the
repo's own CPU-only tools (`python3 -m oto check candidates`, `python3 -m oto stats`,
`python3 -m oto check tensile-build`, `python3 -m oto check library-parity`, the gate/test suite, deck
generation, dry-run, result inspection).

### 2.1 Documents

For every substantive task:

1. Read `README.md` for repository-level orientation.
2. Read `claude.md` (this file) for the operating contract.
3. Read `docs/invariants.md` for the **current executable plan**.
4. Read `docs/invariants.md` for the shipped-footprint → native-gfx90c replication contract.
5. Read `docs/gfx90c_theoretical_limits.md` for the per-family ceiling/acceptance authority.
6. Read `docs/gfx90c_knowledge_base.md` for the baseline repo/code architecture.
7. Read `docs/changelog.md` for what changed and why (oto evolution).
8. Read `docs/potential_configs.md` for the deck methodology; the gfx90c worked example lives in `docs/gfx90c_tuning_guide.md` §13.
9. Read `docs/gfx90c_results.md` for measured evidence (the oto ledger).
11. Read `docs/gfx90c_tuning_guide.md` §14 (the frozen prior-campaign record; the archive left git) ONLY when
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
| Best config per cell across ALL runs, knob reach per family, never-exercised knobs | `python3 -m oto stats` (`--family ZZ`, `--json > post.json`) |
| What has the corpus already measured on this family/cell, at which geometry or axis value, and how did it score? | `python3 -m oto.harness.corpus_census` (`--family SS`, `--typecode HHS`, `--cell SS:1024`, `--knob DepthU`, `--json out.json`) |
| Does Tensile build every *unmeasured* deck row? (the pre-run sweep) | `python3 -m oto.harness.deck_probe` (`--family CC --limit 10`, `--json out.json`; ~75 s/row, resumable, CPU-only) |
| Does Tensile itself accept this config (builds it, and what did it derive)? | `python3 -m oto.harness.tensile_probe --dtype S --macro 128x128x16 --thread 8x8 --vw 4 --du 16 [--wgm -1] [--extra Knob=Value]` (the legality oracle: Tensile's own verdict + the LDS it allocated) |
| Run the test suite (2m10s serial, 1m27s with `-n auto`, 37s for `-m preflight`) | `python3 -m pytest -q` (`-n auto` to distribute, `-m preflight` for the pre-run subset) |
| Is the repo clean under the tree-walking guards? (pyflakes, ruff, py_compile, 60-line and 600-line rules) | `python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q` (`OTO_GUARD_FILES=1` for changed files only) |
| Carve a best-effort gfx90c `TensileLibrary.dat` (+ `.co`) from the full kernel DB, CPU-only | `python3 -m oto library best-effort` (default `gfx90c_results/best_effort_library/`; `--dest DEST`, `--protocol-basis any` for across-all-runs winners; honours `TENSILE_ROOT`/`ROCM_PATH` from `.env`) |
| What is the *legal* geometry space per cell, what has been measured inside it, and which legal geometry is untried but sits next to a fast one? (the numbers, then the picture) | `python3 -m oto.harness.coverage_map` (`--family SS`, `--cell SS:256`, `--top 12`, `--json out.json`) and `python3 -m oto.harness.coverage_graph` (writes `gfx90c_results/analysis/coverage/*.svg` + an index page) |
| Is a deck / candidate list Tensile-legal? (4 gates, exits 1 if not) | `python3 -m oto check candidates` (`--family ZZ`, `--deck other.yaml`; a seed overlay is accepted too) |
| Where did a phase fail, and what does that error mean? | the phase's `2_BenchmarkData` + `logs/`, then `python3 -m oto.harness.failure_triage` (the reason census) + `docs/gfx90c_tuning_guide.md` §5 (the M1–M5 mechanisms) |
| **Measured** occupancy of what Tensile actually emitted, joined to its GFLOP/s | `python3 -m oto.harness.asm_occupancy` (`--by gflops\|vgpr\|waves\|count`, `--dtype ZZ`, `--binder`, `--check-calibration`) |
| **Predicted** resident-workgroup bounds of a `kernel_db` row | `python3 -m oto.harness.occupancy_bounds` (`--side floor`, `--lds-factor 2`) |
| Emit the never-varied-knob deck (winner tile x one knob change) | `python3 -m oto.tensile.knob_sweep` (`--families CC ZZ`, `--shapes 256x256x256`, `--emit --baseline --trials`) |
| Which knobs has the corpus ever actually varied? | `python3 -m oto stats` (`--json > post.json`; the `never-exercised knobs` block) |
| Is a cell *really* won, or only its best kernel? (A/B recomputed under every basis) | `python3 -m oto.tools.deck_review score` |
| Is this forward-knob domain deck-safe, or does it generate refusals? | `python3 -m oto.tools.deck_review legality` (`--family CC`) |
| Do the launch gates agree with what Tensile actually built? (false rejections / misses) | `python3 -m oto.harness.gate_calibration` (`--population ours`, `--fail-on-false-reject`) |
| Would a *proposed* gate rule add false rejections? (calibrate a rule in isolation, before implementing it) | `python3 -m oto.harness.rule_calibration` (`--rule <builtin\|module:attr>`, `--fail-on-false-reject`) |
| Why did a phase produce no measurement? (empty-phase reason census) | `python3 -m oto.harness.failure_triage` (`--run <id>`) |
| How many configs per cell, and does a top-K cap lose a winner? | `python3 -m oto.tools.deck_review flood` (`--cap 24`) |

`oto.tensile.knob_sweep` is a **dry run by default** and writes `phases.yaml`
only with `--emit`; that keeps the read-only contract of stage 2 intact while
still giving deck generation a one-line entry point. It exists because
`oto stats` proves `GlobalSplitU` and `StaggerU` have only ever held one value
each — see `docs/gfx90c_tuning_guide.md` §13 §8 for the deck it emits and §8.1 for the
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
built and ran; `occupancy_bounds` reads a `kernel_db` row, so its "resident
workgroups per CU" is a prediction about a candidate. Corrections to the first
are measurement-vs-model; corrections to the second are model-vs-model.
`asm_occupancy --check-calibration` verifies the waves-per-SIMD model against
the AMD/ORNL GFX9 table and exits 1 if it stops fitting — run it before
trusting any occupancy number in this repo.

`docs/gfx90c_knowledge_base.md` §8.1/§8.2 records the parsing traps these tools encode
(multi-size sweeps, string tiles, complex-is-8-bytes, family from `FamilyLabel`).
A phase that dies with `Generating kernel source resulted in error 4` is the
**workgroup register-file rule** (`R*MT0*MT1*LocalSplitU >= 65536`): the
accumulators alone fill the 64K file with no VGPR left for operands, so a config
that carries it is now refused before it launches
(`oto.tensile.gates.occupancy.occupancy_feasible`; `docs/gfx90c_tuning_guide.md` §13 §R24
rule 1 / §R27). The gate census must show 0 false rejections — the same rule
refuses 40 of the corpus's empty phases and 0 of its built ones.

## 3. MD ownership — do not duplicate

| File | Sole purpose |
|---|---|
| `claude.md` | Entry contract, routing, authority rules, safety/process guardrails |
| `docs/gfx90c_knowledge_base.md` | Baseline repository/codebase knowledge at the captured state |
| `docs/invariants.md` | **Latest/current executable plan only** — self-contained (driver architecture + bug disposition folded in) |
| `docs/invariants.md` | Shipped gfx900 footprint → native gfx90c replication contract |
| `docs/gfx90c_theoretical_limits.md` | Per-family theoretical & realistic ceilings — the acceptance authority |
| `docs/potential_configs.md` | Deck methodology (device-independent); the gfx90c record lives in `docs/gfx90c_tuning_guide.md` §13 |
| `docs/gfx90c_results.md` | Experimental data, parsed results, comparisons, conclusions |
| `docs/invariants.md` | Tuning/search philosophy (agentic; the model never decides a verdict), hardware truth |

| `docs/incomplete_work.md` | Open-work register (status-keyed) |
| `docs/audit_register.md` | User-run expert-agent audit register (memory leaks, race conditions, logical bugs) + frozen prior baseline |
| `docs/gfx90c_tuning_guide.md` §14 | Frozen prior conclusions (read-only reference; results only) |
| `README.md` | General repository orientation |
| `docs/changelog.md` | Single evolution/milestone log (folds former changes_kb + CHANGELOG + agent logs) |
| `docs/README.md` | The boundary between the MD docs ecosystem and the docstrings |
| `docs/docstrings.md` | The module/function docstring convention (owns/does-not-own/public API) |

| `docs/design_language.md` | Design-language spec for the HTML acceptance report |
| `docs/harness_runbook.md` | Harness runbook (moved from `oto/harness/README.md`) |
| `docs/gfx90c_tuning_guide.md` | Live tuning guidance for gfx90c (current fact only) |
| `docs/research/kernel_tuning.md` | Live research notes on kernel tuning (current fact only) |
| `docs/research/complex_gemm_brief.md` | Live research brief on complex GEMM (current fact only) |

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

- `docs/invariants.md` = authoritative for **what is planned next**.
- `docs/gfx90c_results.md` = authoritative for **what experiments showed**.
- `docs/potential_configs.md` = authoritative for the **deck methodology** (device-independent); `docs/gfx90c_tuning_guide.md` §13 is the **gfx90c record**.
- `docs/gfx90c_theoretical_limits.md` = authoritative for **per-family ceilings/acceptance bars**.
- `docs/invariants.md` = authoritative for **what footprint to replicate**.
- `docs/changelog.md` / `docs/gfx90c_knowledge_base.md` = history / baseline (single evolution log).

Never turn "planned", "proposed", "observed", or "historically true" into
"currently true" without evidence.

## 5. Non-negotiable project guardrails

- **No re-inventing known-solved problems.** If the OS, the Python stdlib, or an
  existing industry-standard library already solves it, use that. Never hand-roll
  a substitute for a standard solution: `.env` → `python-dotenv`
  (`load_dotenv`), toolchain → mandatory `ROCM_PATH` (no fallback; layout-aware derivation of `ROCM_BIN`/`ROCM_LLVM_BIN`, `amdclang++` preferred),
  locking/persistence → stdlib `sqlite3`/`json`, CLI → `argparse`. Do the same for any other standard problem-solution set you come across.
- **Tensile tree is one path** (location from the repo-root `.env` key
  `TENSILE_ROOT`, e.g. `${TENSILE_ROOT:-<checkout>}`). Driver shells out to
   `Tensile/bin/Tensile` and `Tensile/bin/TensileCreateLibrary` **in that tree**.
    Native gfx90c support = a 2-file minimal Tensile patch (`Tensile/Common.py` +
    `Tensile/AsmCaps.py`) **in that tree**. Run ledgers (`gfx90c_runs/`,
    `gfx90c_results/`), the peak table (`oto/device/loader.py`) and the driver modules
    live in the oto base dir (`--base-dir`, default repo root).
   `PYTHONPATH` = `<TENSILE_ROOT>:…`.
   Override only via explicit `--tensile-root` / `TENSILE_ROOT` (same layout).

- **Agentic, with a deterministic acceptance path.** Candidate generation inside the
  driver is deterministic (harvest → mutate ≤2 knobs); no model sits in the
  gate/measure/verdict path. The agent layer (`oto agent consult`, agent-1/agent-2,
  or an out-of-band user-invoked LLM) is add-only and proposes rows for the same
  deterministic pipeline — never an in-loop verdict decision.
- Native `gfx90c` is the target. Do not substitute RDNA/Navi/MFMA assumptions.
  rocminfo_output.txt is the golden reference for hardware decisions.
- Hardware facts come from project evidence (`rocminfo`, source, runtime, logs), not
  model memory. Do NOT re-derive peak rates (File: `oto/device/loader.py`).
- `gfx900` spoof is a reference baseline/floor, never target identity, never a signal.
- Never silently weaken acceptance criteria (subset success ≠ whole-library success;
  one good run ≠ convergence).
- Benchmark claims require benchmark evidence; build success is not performance
  validation. Correctness gates performance claims.
- Avoid redundant experiments; check the registry before adding equivalent work.
- Preserve experiment provenance and historical results. Benchmark data is NEVER
  deleted; all data streams are append-only (canonical law: `docs/gfx90c_knowledge_base.md` §10).
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
- **/tmp-PoC-first default.** Every code change — not only `oto` /
  its modules — is prototyped in `/tmp` and tested there before landing;
  in-tree files are edited only after the PoC passes. Throwaway scripts never
  land in the repo root.
- LLM output is hypothesis input, not architecture authority. HW decides. DB remembers.
- **Every family deck must be able to reach the 16 B global-load cap.** The
  classic path caps a contiguous load at `GLVW * bytesPerElement <= 16`. A tile
  reaching only 8 B leaves ~5-15% on the table for no legal reason, and the
  native deck hardcoded exactly that for SS/HH/DD. `cap_vector_width()` derives
  the width; `tests/test_occupancy_model_vgpr.py::TestGlobalLoadVectorWidthRule` fails if any family deck cannot reach 16 B.
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
     `128x64` / ZZ `64x64`/`128x32` (docs/gfx90c_tuning_guide.md §13 §R24/§R27).
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

After changing code: run the narrowest useful validation first, and keep the
tree-walking guards green (`test_pyflakes` / `test_ruff` / `test_py_compile` /
`test_function_length` / `test_file_length` — `python3 -m pytest tests/test_pyflakes.py tests/test_ruff.py tests/test_py_compile.py tests/test_function_length.py tests/test_file_length.py -q`); then required
acceptance checks from `docs/invariants.md`; update `docs/gfx90c_results.md` from actual
generated data, not hand-edited conclusions; update `docs/changelog.md` only for durable
state changes; update the per-device docs for candidate outcomes (and the methodology if a rule changed); bug disposition
lives in `docs/invariants.md` (Triaged fixes section).

## 7. Experiment loop

`observe → hypothesize → implement/configure → correctness → benchmark → compare → retain/reject → record → repeat`

Do not claim "converged", "optimal", "GTG", or "fully implemented" unless acceptance
checks are demonstrated and remaining gaps are stated.

## 8. Documentation hygiene

### 8.1 Legacy silence & file boundaries

- **Never reference removed machinery.** Anything that has been deleted from the
  codebase — by any name or description — must never reappear in code, configs,
  or docs. Zero occurrences, always.
- **History has exactly two sanctioned homes:** `docs/changelog.md` (append-only) and
  the frozen `prior_*` files. Live docs (this file, `docs/invariants.md`,
  `docs/potential_configs.md`, `knowledge_base*`, `docs/gfx90c_results.md`, `docs/invariants.md`,
  `README.md`, `oto/device/loader.py` comments, etc.) state current fact only. They
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

- "What is this repo?" → `docs/gfx90c_knowledge_base.md`
- "What changed / why?" → `docs/changelog.md`
- "What's next?" → `docs/invariants.md`
- "What footprint do we replicate?" → `docs/invariants.md`
- "What are the ceilings / acceptance bars?" → `docs/gfx90c_theoretical_limits.md`
- "What candidates?" → `docs/potential_configs.md` (methodology) / `docs/gfx90c_tuning_guide.md` §13 (record)
- "What bug / fix status?" → `docs/invariants.md` (Triaged fixes section)
- "What did runs prove?" → `docs/gfx90c_results.md`
- "How does the driver work?" → `docs/invariants.md` (The Driver Architecture)
- "What is the search strategy?" → `docs/invariants.md` (agentic tuning context)
- "What are the frozen prior conclusions?" → `docs/gfx90c_tuning_guide.md` §14 (measured results only), then verify against current sources.

## 10. Final response discipline

End substantive work with only:

**Done:** verified completed work.
**Evidence:** source/run/test proving it.
**Pending:** unproven or unfinished requirements.
**Next:** concrete next action, only when useful.

No optimistic wording unsupported by evidence.
---

## Implementation plan (folded from implementation_plan.md)

## Objective

Produce an optimal Tensile library for the gfx90c iGPU in Ryzen 5 5650U
(Vega 10 window, 7 active Compute Units, wave-64, no MFMA), matching the bar
AMD never shipped. Two standing bars:

1. **Footprint parity** — the 38 (family, shape) cells in
   `docs/invariants.md` must each carry a native gfx90c kernel; the
   floor is the reference library.
2. **Approach the theoretical limit** — the per-family roofs in
   `docs/gfx90c_theoretical_limits.md`. Verdicts compare against that authority,
   medial-of-seeds + clock-normalised.

## How oto is built — two loops, one rule

**The inner loop (the acceptance path) is deterministic, and stays that way.**
manifest → candidate deck → correctness → benchmark → deterministic winner
policy → harvest / mutate ≤2 knobs / tie. Given the deck, the driver is
repeatable: a config either benches green or refuses, and no probabilistic
gate, heuristic tuner, or model sits inside it. Correctness is decided by
Tensile's builds and the hardware, never by a model; verdicts are computed
from medians-of-seeds by policy code. `docs/invariants.md` is the
contract for this loop, and the LLM has no role in it.

**The outer layer (which configs go on the deck) is LLM-assisted and ships
today.** The `oto/agents` package carries exactly this layer:

- **agent-1** (`oto/agents/theoretical_limits.py`) drafts the per-device
  theoretical-limits doc; **agent-2** (`oto/agents/tuning_context.py`) drafts
  the tuning context, with directed prompts that require ISA-manual citations.
- **oto agent consult** (`oto/agents/census_consult.py`, shipped) ingests a
  starter file + a device profile + the local corpus and emits
  `<codename>_docs/potential_configs.md` with gate-legal rows, corpus priors,
  rejection taxa, and a TTY to-do list — CPU-only.
- The directed research corpus (`oto agent generate`) is LLM-drafted, draft
  only; `docs/invariants.md` marks precisely which parts are *shipped*
  vs *design* (the GPU proof, `OTO_AGENT_ALL`, `--full`, `--trials-per-family`
  have no code).

The rule both loops share: **the model proposes, never decides.** Every
proposal — a drafted doc, a suggested config, a research claim — passes the
CPU gates and the GPU measurement before it becomes a verdict. The gfx90c port
itself was built this way (class-A LLM-in-the-loop development with human
review, plus the deterministic driver for everything measured).

## What this is NOT

- **Not autonomous end-to-end, yet.** `oto agent consult` is CPU-only; the
  end-to-end run for a new device (gfx902: agent consult → GPU proof →
  best-effort library) is assembled in design and blocked on the owner's API
  key. Nobody should read this repo as claiming an autonomy that is not built.
- **Not probabilistic at the acceptance boundary.** Inside the driver, given a
  deck, every phase is deterministic by construction. Variance enters as
  measurement noise (handled by seeds, medians, CV gates), never as an
  algorithmic coin flip.
- **Not a fairness contest between libraries.** The reference floor is a
  baseline, not a target to merely match; verdicts against the floor are WIN /
  TIE / LOSS relative to that floor. Above it, the acceptance bar is the
  theoretical roofs.

## Measurement discipline

- Winner = **median-of-seeds** (`NumBenchmarks >= 3`); max is reference only.
- Comparisons = **throttle-adjusted** per (datatype, bound_class); the sclk-ruler
  requires ≥10 samples and median busy>0; missing controls are reported, never
  guessed.
- Retirement is the evidence-gated single Tier-2 path
  (`oto/metrics/cell_policy.check_retirement_eligibility`); the floor is never
  a retirement signal.
- The accepted ceiling set lives in `docs/gfx90c_theoretical_limits.md`; the
  acceptance report carries those ceilings alongside verdicts.

---

## Agentic consult (folded from agentic_consult.md)

## §0. The goal, in one sentence

Given a starter file for a GPU that oto has never seen, plus an LLM API key,
**STATUS: implemented — `oto agent consult`.** CPU-only consult per this spec runs today:
it ingests a starter/profile and emits `<codename>_potential_configs.md` with gate-legal rows,
corpus priors from the local `kernel_db.json`, rejection taxa, and a TTY to-do list. The GPU
proof (Phase C) is blocked on GPU budget; the gfx902 run (Phase D) is blocked on the API key.

oto ingests both and emits a finished `potential_configs.md` — a candidate
deck, ranked, with evidence, and a `phases.yaml` continuation — without a human
in the loop and without benchmarks it does not need.

## §1. The problem as it currently stands

Today `oto agent generate` runs agent-1 (theoretical limits) and agent-2
(tuning context) plus an optional CPU-only harness study and then writes the
three device docs beside the repo root. It does **not** produce the missing
half: the *concrete candidate deck* with evidence and a least-GPU-trial
strategy. The gfx90c campaign got to 19 W / 19 T / 0 L with roughly four dozen
measured cells out of an 1101-row seed, of which only ~280 were ever measured
and ~180 of those were measured cells. Reproducing that ratio for a new device
by replaying the full deck end-to-end wastes most of it. This plan automates
the funnel instead: from profile facts → cheap CPU gate drops → Tensile probe
→ a small GPU shortlist → convergence — and writes the result as the device's
`potential_configs.md`.

`potential_configs.md` is the device-tuned deliverable. Everything else — the
limits doc, the tuning context, the harness study, the report — is scaffolding
for it.

## §2. What the gfx90c campaign actually did (the evidence this plan encodes)

Every stage below existed, in some form, during the gfx90c port. The plan is
not speculative; it is a codification.

1. **Floor discovery from the installed TensileLibrary** — the shipped gfx900
   manifest gave 2,285 kernels across 28 families; the *footprint contract*
   (`docs/invariants.md`) cut to 1,027 candidate rows from the
   floor's own winning config captures. In launchable form the deck was
   ~493 numeric measurements + ~60 builder probes. The lesson: the floor's
   winners are the *easiest-to-vet* starting candidates — the vendor already
   measured them for its own silicon family. Rating unknowns first, then the
   small delta hunt, is where the time goes.
2. **Wave-quantization first** (small cells, 0.25–0.30 residency) — the
   largest-win region in the corpus. Automatable as a family-tag heuristic:
   cells where grid tiles < 14 get the "wavefill" treatment by default.
3. **CPU-side gate pruning** — the launch gates (`validate_config` +
   `ldspad_feasible` + `ldtile` + the vendored `vgpr_model`) drop >90% of the
   raw candidate set before any Tensile probe. The reference flow needs this
   or it dies on weeks of builds that produce nothing.
4. **Tensile oracle probing** — `oto.harness.deck_probe` / `tensile_probe`
   ask Tensile itself whether the remaining configs build (CPU-only). This is
   the big new step the gfx90c work surfaced after adding
   `NumElementsToValidate=128`: Tensile's own CI validator now refuses illegal
   kernels at build time, and "builds or does not build" is nearly free
   evidence compared to a runtime benchmark.
5. **Small-scale benchmark funnel** — the campaign measured ~280 deck + ~60
   floor cells and produced 19 WIN / 19 TIE / 0 LOSS against the gfx900 floor.
   The whole gfx90c campaign is reducible to: ~60 benchmark runs × ~83 s ≈ 1.4
   GPU-hours for the complete corpus study, outputting the entire
   `potential_configs.md` with per-cell winners, ties, losses, and reasons.
6. **Perspectives from the report** — `oto report` ingests the benchmark DB
   and writes the verdict JSON/HTML; the report's family coverage and
   red/orange/tie splits already map directly onto `potential_configs.md`'s
   sections (§R numbers were transcribed from these verdicts hour by hour).
7. **The output format itself is the trick** — `potential_configs.md` is not
   a benchmark dump. It is: the deck's candidate sources named by family with
   fingerprint + tile geometry; one row per (family, shape, config); the
   median-of-seeds velocity; the knob delta between native winner and floor
   winner; a per-family narrative with the one thing that mattered; the
   retrospectives section keyed to RSM/REX rules. None of that structure
   exists in the codebase today. The plan separates "measure" from
   "synthesise potential_configs.md" — the synthesis is templated and owned by
   the agent layer, not the harness.

## §3. What the plan requires of the codebase

### §3.1 `oto/agents/census_consult.py` (implemented)

The orchestration entry: `generate(profile, base_dir, research=None,
harness=None)` returning a dict of synthesised artifacts (which docs and
overlay files were written). Owns: the stage order, the dependency graph,
and the never-return-an-incomplete-result-while-leaving-a-dead-file rule.
Does NOT own: content generation (agents do), stage semantics, scoring.
*(Design — not implemented.)* `OTO_AGENT_ALL` and `--full` do not exist today;
this module ships as `oto agent consult`. If this stage ever lands, §§5–8 would be
a single opt-in today; splitting it into selectable stages is deliberate.

Pipeline:

```
starter file
  → load_profile_from_starter(load_profile=True)          [existing]
  → research_client.make_researcher(starter_text=text)    [existing]
  → agent-1 (theoretical_limits.md), agent-2 (tuning_context.md) [existing]
  → harness study (kernel_db/corpus_census/candidate_rows) [existing]
  → candidate deck (family_decks.build_seed + probe)         [enlarged]
  → deck_pin (fingerprint all candidates)                    [new stage]
  → oracle_filter (Tensile build probe, CPU-only)            [new stage]
  → sweep_size_guesser (GPU-trial count per family)          [new]
  → retune loop (`oto tune` with a narrow deck, TTY)         [existing]
  → report (`oto report`)                                     [existing]
  → potential_configs.md synthesis (the new export)           [new]
```

### §3.2 Stage: candidate pin & oracle filter

Given the emitted deck (be it ~2k rows, or an emptiness-pruned one), annotate
each row with: fingerprint, family, wave-per-CU, and per-family risk class
(grid fill < 0.25 for small cells on 7-CU grids). Drop the rows that
`validate_config` already vetoes — the gfx90c campaign showed those are almost
all catalog-floor rejects. Budget: zero GPU time.

Next, build the remaining rows through Tensile's own kernel writer (M =
`NumElementsToValidate`), record which ones Tensile accepts silently vs
rejects with a real error message. This is `oto run_probes` (new verb or a
`--probe` flag on `oto check tensile-build`). Track the results in the
registry (`mark_phase_probe`); any row Tensile refused goes out without ever
touching the GPU. Track 0-GPU cost; it delays nothing.

### §3.3 Stage: funnel size per family

*(Design — not implemented; `--trials-per-family` exists nowhere in code.)* Each family gets a benchmark budget (`--trials-per-family`, default 8,
overridable by a header line in the starter). The sweep pattern ordered by
expected value is:

1. Wavefill refill: small tiles + GlobalSplitU for <0.25 residency cells (this
   was 3/19 of the gfx90c family).
2. Ceiling search: TILE(SweepStep, 64, family_shapes) ∈ {128x128, 128×64,
   64x64} for the small cubes, 1024+, direct-lookup reuse (nothing new to
   measure there except padding 1 improvement).
3. xf16/native-f16 reuse for the HPA families: 32-bit loads only — HPA unreachable on GCN.

For each trial the funnel records (measure, retune, report); the engine sees
the delta from the *same cell's first measurement* (native vs best-so-far),
so until a measurement lands the loop plans no further cells in that family.

### §3.4 Stage: potential_configs synthesis

`oto/agents/census_consult.py` builds the markdown (CPU-only) from the corpus
and the gate verdicts (implemented):

- §A. Bounds: per-family paragraphs mirroring the gfx90c structure,
  with per-family tile counts, unsupported-vs-accepted verdict, and the
  "why this GPU is different" note (APU/CPU-shared-L2 vs GFX).
- §B. Per-family coverage: the exact tile shape that won and the
  per-cell native-vs-floor delta — no screenshots, just numbers.
- §C. Unsupported: the family's tile/lattice rejection evidence. Zero claims
  without proof, or the section does not exist.
- §D. Winners: the six bullets per family that matter, each with a proof
  pointer (run id + report path).
- §E. Wasted time: what we measured that nothing needed; catalogue of
  dead avenues (split-complex? DB? GSU?) tied to the probe results.
- §F. Open work: what is still unknown, with the guessing game called out
  (if you guess, say so).

The export is byte-compiled, not generated by str.join — isinstance checks +
assert all placeholders resolved before write. The `oto library best-effort`
output (.dat path + manifest) is appended at §H.

### §3.5 `oto doctor`

*(Design — not implemented; doctor has no `research_key`/`deck_ready`/`probe_complete` rows.)* New checks: `research_key` (source: starter|env|missing — never prints the
key), `deck_ready`, `probe_complete`. Log file always exists at
`oto_<phase>.log` under the run dir — gitignored with the rest of runtime
logs.

## §4. The API key contract

The starter file carries the key in a single line:

```
api_key: <value>
```

If the value begins with `$`, it is expanded against the environment
(`api_key: $OUTSOMEKEY`). If the environment has it already (OTO_API_KEY,
ANTHROPIC_API_KEY, OPENAI_API_KEY), the starter line is irrelevant. If both
are absent, the campaign proceeds with empty research (the doc agents emit the
warning header: "UNVERIFIED — key absent; no claims beyond first-party
documents" at the top of every generated doc). Keys are never:

- printed (log only last 4 chars + "<redacted>");
- written to any file, nor serialized into any doc;
- committed to the repo (the starter files are user-local; the starter parser
  never writes api_key into anything derived).

*(Design — not implemented.)* Doctor does not report `research_key` today; `tests/test_research_key.py` does not exist. Both are design placeholders.

## §5. What the operator does

```
# 1. starter file
cat > my_gpu_starter.md <<'START'
codename: gfx10xx
isa: [10,0,0]
num_cus: 4
...
api_key: $MY_KEY
START

# 2. one command, from repo root, GPU in TTY
python3 -m oto agent consult my_gpu_starter.md

# 3. read the report, commit the doc, done
oto report
```

Files emitted:

- `<codename>_theoretical_limits.md` — agent-1 output
- `<codename>_tuning_context.md` — agent-2 output
- `<codename>_harness_study.md` — CPU-only harness study
- `potential_configs.md` — the deliverable
- `<codename>_results/` — probe logs, report HTML, best-effort `.dat`

## §6. The acceptance test

Plan is done when a fresh Ryzen AI 9 HX 370 iGPU profile generated by this
flow, fed through an isolated TTY campaign, produces a deck with outcomes
within 2 WIN of the gfx90c reference deck (the LASSO-TLU deck: the parent
family's fundamental tile axis that does not move on any GCN5-class part,
measured end-to-end on this part). That is a real benchmark comparison with
real nulls, not a paper claim.

If it produces 12 WIN / 14 TIE / 12 LOSS against that baseline, the flow is
correct; the LOSS column just becomes the family retry list for the next
campaign.

## §7. What deliberately stays out

- The GPU benchmark pass itself (`oto tune`) is not automated here. It is the
  one step an operator must drive, because TTY/GPU discipline is a human
  contract, not a loop invariant.
- The API research corpus is never trusted. Agent-1/agent-2 drafts are
  UNVERIFIED; only first-party sources (vendor datasheets, ISA manuals,
  Tensile source) close a claim. The pipeline forces that with the same rule
  as the compile gate: unverified-by-first-party goes out unmarked, never as
  fact.
- Fresh-deck legality is always re-proved on the target, never transcribed
  from gfx90c. The 7-CU restriction is a GCN5 position, not a law.

## §8. Where this touches the tree

| Path | Role |
|---|---|
| `oto/agents/census_consult.py` | implemented — the consult engine (CPU-only) |
| `oto/cli/commands.py`, `oto/cli/parser.py` | `oto agent consult` verb (with `--with-docs`) |
| `oto/harness/deck_probe.py` | optional probe stage (not yet wired to the consult) |
| `oto/runners/library_build.py` | `--with-docs` path also emits agent-1/agent-2 docs beside the consult |
| `tests/test_census_consult.py` | the acceptance test (synthetic profile, zero GPU) |
| `docs/operator_runbook.md` | a pointer to this file as the Class B entry for new-device docs |

---

## search_philosophy (folded from search_philosophy.md)

## Scope

- Port native `gfx90c` Tensile libraries replicating the shipped gfx900 footprint,
  performing better than the gfx900 spoof floor. No more, no less.
- oto constraint: **deterministic acceptance loop**. No model sits in the
  gate / measure / verdict path: harvest → mutate(≤2 knobs) → re-run until
  convergence or budget.
- The agent layer is LLM-in-the-loop by design and ships today
  (`oto agent consult` — CPU-only, starter + profile + local corpus →
  gate-legal rows; `oto agent generate` — agent-1/agent-2 docs). It is add-only:
  an LLM-proposed candidate set — synthesised by the consult stage or injected
  out-of-band by the user — flows through the same deterministic pipeline.
  Never a verdict, never a gate, never a measurement decision.

## Core Strategy

```
(the `phases.yaml` deck is either the shipped seed or an agent-synthesised deck
 from `oto agent consult`; either way the loop below is deterministic)

shipped gfx900 footprint (28 families, 4 patterns)
    ↓ translate decks (docs/invariants.md) — never copy ISA900 kernels
native gfx90c family phases
    ↓ correctness (compiler + client + anti-alias)
HW benchmark (median-of-seeds, ruler-adjusted)
    ↓
deterministic evaluate → harvest wins / mutate ≤2 knobs / tie
    ↓
convergence (no RED cells; budget exhaustion = stop, not pass) → synthesis → acceptance readout
```

## The model never decides

`gfx90c identity / ISA legality / AsmCaps / compiler flags / runtime support /
correctness / measurement / accepted performance` — including in the agentic
consult and in any out-of-band user-invoked LLM call. The model only proposes
candidate *parameter vectors*, research drafts, and deck rows; Tensile generates,
the compiler validates, the hardware decides, the DB remembers.

## Correctness Gate

Always: generate → correctness → benchmark. Never: benchmark → fast → maybe correct.
Wrong kernel = failed candidate. The validator must reject known-invalid configs
(no `AssertSizeMultiple: [1]`, no `SIA>1`, no Fp16AltImpl, LDS ≤ 64 KB/CU).

## Reward Hacking

Independent benchmark + fresh inputs + correctness validation + repeat runs + guard
checks + dtype-specific tolerance. Evaluator stays outside model control. No
max-of-seeds; median-of-seeds is the statistic.

## Search strategy — no surrogate in the loop

- Levels 0–2 (traditional / advisor / mutation-generator-with-validation) are the
  ceiling *inside the driver*. Levels 3–5 (local evolution, profile-guided,
  surrogate/Bayesian) are EXPLICITLY OUT of the driver's loop unless a later
  attempt elects them after a good baseline + enough data. The agentic outer
  layer is not a search surrogate — it proposes a shortlist and the
  deterministic loop decides; oto does not require it.

## Hardware Ground Truth --- Do NOT Re-Derive From First Principles

| Fact | Value |
|---|---|
| ISA | gfx90c = (9,0,12), GFX9/GCN5 Cezanne, NOT RDNA |
| CUs / lanes | 7 CU × 4 SIMD × 16 = 448 FP32 lanes, Wave64 |
| MFMA | FALSE (no v_mfma) → ScheduleIterAlg only 0/1, no microtile forms |
| LDS | 64 KB/CU; L1 16 KB, L2 1 MB shared |
| FP64 | VALU-only 1/16 rate => peak 101 |
| FP16 | dual-issue packed `v_pk_fma_f16` => peak 3226 |
| BF16 | single-rate (≈ FP32 FMA) => peak 1613 |
| INT8 | single-rate `v_dot4_i32_i8`, NO dp4a dual-rate => peak 1613 |
| Clock | 1800 MHz max (PEAK table basis) |

Ratified measured ceiling util: FP32 69%, FP16 77%, BF16 69%, INT8 55%, FP64 98%.

## Search order — what to try, and in what order

The `Core Strategy` above says *that* the loop mutates ≤2 knobs; it does not say
*which* knobs first. This section does, and it is the one place that owns the
ordering. It is the conclusion of the external autotuning literature applied to
7 CUs / 64 KiB LDS / 1 MiB L2 / no MFMA; the per-knob legal domains live in
`docs/gfx90c_tuning_guide.md` §1.1 and the virgin axes in §9.1.

**Stage 0 — analytic pre-filter, zero GPU cost.** A draw that fails any of these
is a guaranteed refusal, and every refusal costs one of the mutator's five draws
per iteration. `python3 -m oto.tools.deck_review legality` proves the domains
against the real gates rather than trusting this list.

1. `grid = ⌈M/MT0⌉·⌈N/MT1⌉ ≥ 14` for ≥2 WG/CU on 7 CUs; else force `GSU ≥ ⌈14/grid⌉`,
   capped at what the family allows (**not** CC/ZZ — gate-refused on this port).
2. `LDS = 2·(MT0+MT1)·DU·bpeAB + pad_bytes ≤ 32768` for 2 WG/CU, `≤ 65536` for 1.
3. `VGPR ≤ 256` — the existing `oto.tensile.gates.vgpr_model` model.
4. `GLVW × bpe ≤ 16` and `GLVW ∈ {1, VectorWidth}`.
5. `MT0·MT1/(WG0·WG1) = TT0·TT1` and workgroup size ≡ 0 mod 32.

**Stage 1 — coarse grid over the floor's own axes**, anchored on Tensile's
`Perf/*.yaml` envelope but **re-centred for 7 CUs**: at 256³/512³ drop
`128×128`/`128×256` entirely (4 tiles = 6 of 7 CUs idle); at ≥1024³ keep them.

**Stage 2 — virgin axes, one at a time, from the incumbent**, highest
verified payoff-to-risk first:

```
AssertFree{0,1}ElementMultiple (4 or 8; legality-gated)
  → LdsPad{A,B} ∈ {0,1,2,4}
  → NLCA/NLCB ∈ {1,2,4}
  → SIA{2,3} × 1LDSBuffer{−1,1} × DepthULdsDivisor{1,2,4}
  → WorkGroupMapping ∈ {1,2,3,4,−1,−4} + StaggerU{0,32} × StaggerUMapping{0,1}
  → NonTemporal{A,B} ∈ {0,1,2}
  → FractionalLoad ∈ {0,1,2}
  → StoreCInUnroll × StoreRemapVectorWidth
```

**Stage 3 — local refinement** by first-improvement hill climbing, ≤2 *co-dependent*
knobs per move. The coupled clusters are `LdsPad↔NLCA↔DepthU` and
`SIA↔1LDSBuffer↔PrefetchLocalRead↔EPS`: single-axis moves through a coupled pair
land in rejection valleys that look like walls.

**Why this order and not a random sweep.** The transferable result from the
autotuning literature is that a *budget-tiered* algorithm — coarse-to-fine, with
an analytic pre-filter ahead of the search — beats uniform random search at every
budget, and that the gap widens as the budget shrinks. At 7 CUs the per-config
cost is high and the budget is a single overnight run, so the pre-filter is
worth more here than on a large discrete part. Analytic/constructed schedules
beat search outright when the space is huge, which is why Stage 0 exists at all.

**What is NOT VERIFIED.** No published study measures "MLP-style tuning vs the
vendor floor on a 7-CU Vega APU". What *is* first-party: AMD's `rocblas-gemm-tune`
uses Tensile to *heuristically search* kernel parameters — this technique is
vendor-sanctioned; and AMD's own workload guide states plainly that **there is
no guarantee a tuned workload beats the default GEMM algorithm**. Treat the
floor's wins as the bar to clear, not as a ceiling we are entitled to.

**Cost model, if one is built.** Predicted time ≈
`max(flops/peak, bytes/bw) + LDS_conflict_penalty`, with the penalty from a bank
conflict factor as a function of `(stride, DepthU, VectorWidth, bpe, LdsPad)`.
Use it only to **rank and prune** — never to accept. The measurement is the
ground truth, and a surrogate that disagrees with it is a bug, not a finding.

## §3.6 State machine and resumability (folded from agentic_consult.md)

The consultation is a state machine, not a script: `intake → research → gate →
carve → synth → dryrun → tty → report → publish`. Each stage writes and reads a
JSON checkpoint under `<results>/consult/`; a stage that cannot produce its
checkpoint refuses to advance rather than leaving a half-written artefact
behind. The ledger is the source of truth; partial progress is resumable by
construction. M1 (scaffolding `oto/agents/auto_consult.py`), M2 (research
plumbing over `oto.agents.research_client`), M3 (census bridge), M4 (dry-run
gate), M5 (TTY driver — the human starts `oto tune`; no automation around the
GPU), M6 (publish via `oto report --json` → `oto.tools.potential_configs`,
human reads), M7 (rehearsal suite on a stub device).

## §3.7 Failure modes (folded from agentic_consult.md)

| Failure | Caught by | Outcome |
|---|---|---|
| API key absent | M2 | stages no-op; stops at the research gate |
| Research invents facts | human gate (P3) | unsigned JSON → no profile → no run |
| Deck illegal | `check candidates` (M4) | refused before TTY |
| GPU absent | `oto doctor` (A4) | refused before TTY |
| Agent wanders | deterministic gates + `_writing()` ledger lock | every action is gated |
| Budget burned | `--budget` hard ceiling | valid terminal: "budget exhausted" |
| Report lies | `report --json` from the ledger only | impossible by construction |

**What stays human, always:** signing the starter JSON; starting any GPU run;
adopting rows into `phases.yaml`; claiming performance (numbers live in
`docs/<codename>_results.md`, written from the ledger).

## §3.8 Open decisions for the owner (folded from agentic_consult.md)

1. Whether M6's publish step may auto-adopt CC-style "AF4/4" rows into the deck
   at a target visit (today: never — deck changes are per-commit review).
2. Whether the session gets a `--yes` non-interactive mode at all (today: no —
   every stage pauses for the human).
3. Whether `kernel_db` is shared across devices in this program (today:
   per-device `<results>/analysis/kernel_db.json`; the harness tolerates both,
   but cross-device sharing is an unmeasured optimisation).

## Final Rule

Deterministic loop, HW decides, DB remembers. If the agent layer proposes
candidates (`oto agent consult`, or an out-of-band user-invoked LLM), the model
proposes; Tensile generates; compiler validates; HW decides; DB remembers.

## Current State

Port mechanics done; parity not wins (frozen baseline, `prior_*`); the native deck
(`phases.yaml` = 418 phases) plus the dedicated gfx900 reference floor are the
active workflow. Floor `gfx900_ref_20260925_152942`: 1,073/2,285 executed, 1,096
unattempted + 116 failed — continued via `oto bench --resume`;
`oto tune` gates tuning on full floor completion, then converges per-cell verdicts
by workload cell `(family, dtype, shape)`. No model sits in the gate/measure/verdict
path; the agentic layer proposes research and candidates, the deterministic loop decides.
---

## §S — SOTA autotuning strategy cross-check (corpus4-derived, durable facts now live here)

Verified facts from the external GEMM autotuning literature, applied to a 7-CU / 64 KiB-LDS / 1 MiB-L2 / Wave64 / no-MFMA target:

1. **Budget-tiered search.** Kernel Tuner study (Tavecchio et al., TEVC 2022; 26 spaces × 9 GPUs
   × 16 optimisers, GEMM in OpenCL on AMD MI50): **≤ 200 evaluations → dual annealing** wins (SMAC
   "did not even beat random sampling for GEMM" at low budgets); **200–800 evals → first-improvement
   local search + SA**. At ~120 sec per evaluation, a 10h run ≈ 300 evals ⇒ low-to-medium tier,
   so the loop is **analytic pre-filter → hill-climb the surviving footprint → draw diagonals
   last**, never a surrogate model in the inner loop.
2. **AMD gains ~5× more from autotuning than NVIDIA** (~10× vs 2×; arXiv 2407.11488). Vendor-tuned
   configs do *not* transfer across vendors — which is why SS pads, DD/HH_HPA/HS_HPA never pad
   must be honoured as asymmetric rather than averaged over.
3. **Analytic / constructed schedules beat search when the space is huge.** ROLLER + tritonBLAS:
   `LDS capacity fixes the CU tile` (`(tM + tN) × tK × elem ≤ LDS`), `VGPR budget fixes the warp
   tile`, **94.7 % selection efficiency** at **50–80 μs** tile selection (5-6 orders of magnitude
   faster than Triton autotuning's 10-50s / 75 configs). Use as the Stage-0 pre-filter; keep
   measurement as the ground truth.
4. **Vendor-sanctioned templated search.** Bolt + `rocblas-gemm-tune` use Tensile to heuristically
   search — the exact technique here. AMD's workload guide confirms `mfma_16x16` > `mfma_32x32`
   on MI300X and explicitly states *"there is no guarantee that the workload being tuned will be
   able to outperform the default GEMM algorithm"* — the floor is the bar, not a ceiling.
5. **SplitK / K-split is the dominant lever for large-K-small-MN** (hipBLASLt blog,
   Stream-K++). StreamK and GSU>1 are mutually exclusive; we picked GSU.
6. **Subzero samples matter.** Profile GPU counters (bank conflict rate, LDS bandwidth, TCE/L2
   stall) *during* the search to disambiguate *why* a config lost — the rationale behind the
   counter regression in Stage 0/1.
7. **Search-space size is implementation-dependent; there is no universal `10²/10³/10⁴` rule.**
   CLBlast describes the GEMM space as too large for exhaustive search and stages its tuning
   (small initial set → a random fraction of a much larger space); Kernel Tuner, ATLAS,
   Ansor/AutoTVM and Triton all pick by measurement over a curated set. Consequence for this
   repo: **14–25 configs/cell is a *small shortlist*** — sensible after strong legality/resource
   pruning, risky when the candidates are near-duplicates. The corpus's ZZ cell (5 distinct
   geometries, and the family furthest from ceiling) is the near-duplicate end of that scale
   (`docs/gfx90c_tuning_guide.md` §13 §R28/§R33).
8. **Surrogate / Bayesian / bandit selection is published for GPU kernels** (rough, discrete,
   constrained spaces, expensive evaluations — Willemsen et al.; KernelTuner's multiple
   optimisers; Ansor's learned cost model). It is **explicitly OUT of this project's contract**:
   the search strategy caps at Levels 0–2 and requires deterministic ≤2-knob mutation, so record this
   as an external recommendation the project has *declined*, not a route. The transferable part
   that *is* adopted is the literature's insistence on **mechanism-diverse exploration (WGM,
   buffers, LDS layout, depth) rather than ±1-knob hill-climbing alone** — which is why Stage 2
   sweeps virgin axes one mechanism at a time.
9. **Per-shape tuning is established practice, not a guaranteed gain.** CLBlast tunes on the
   actual dimensions; Triton uses shape-keyed autotune. Specialise only where grid quantisation,
   edge waste, K length or cache reuse differ materially (gfx90c: the small-shape band,
   `docs/gfx90c_tuning_guide.md` §13 §R29); keep the family-wide config as baseline/fallback and retain a
   specialisation only when the gain repeats outside the tie band.

**Cost model (cheap, no GPU).** Predicted time ≈ `max(flops/peak, bytes/bw) + LDS_conflict_penalty`,
with the conflict factor estimated from stride/DepthU/VectorWidth/bpe/LdsPad. **Use for ordering and
pruning only** — never accept on the model; measurement is the ground truth.

**Measurement hygiene (per the run-census read).** Ban within-the-overlap measurement (a config
whose median comes from a run that overlapped a different invocation) — the 658.2 vs 333.0
multi-shape swing on the same kernel is **real**, not noise, and form-mismatched cells grade
`UNGRADED`. Always destroy the optimizer's draws between iterations; 32 reps per config in
Kernel Tuner is the source-of-truth, versus our 8 seeds which is thin near the band.

## §S.X — Source list (verify each yourself, all live as of the corpus pass)
- arxiv.org/abs/2210.01465 (TEVC 2022), 2407.11488, 2512.04226 (tritonBLAS), 2102.05297,
  2102.04199, 2201.05587, 2604.12891, 2408.11417, 2110.08221, 2102.04199, 1908.05792
- Autotuner design, folded 2026-10-19 (§S 7–9): CLBlast (github.com/CNugteren/CLBlast,
  doc/tuning.md), Kernel Tuner (doi.org/10.1016/j.future.2018.08.004), ATLAS
  (sciencedirect S0167819100000879), Ansor (arxiv.org/abs/2006.06762), Triton GEMM tutorial
  (triton-lang.org), Willemsen Bayesian (arxiv.org/abs/2111.14991), Stream-K
  (arxiv.org/abs/2301.03598), CUTLASS efficient-GEMM + measurement methodology (docs.nvidia.com/cutlass),
  Roofline (eecs.berkeley.edu EECS-2008-134)
- rocm.blogs.amd.com artificial-intelligence/gemm_blog, software-tools-optimization/hipblaslt
  (SplitK), software-tools-optimization/lds-bank-conflict (padding vs XOR)
- rocm.docs.amd.com projects/ai-ecosystem (workload), rocprofiler-compute pipeline descriptions
- tvm.apache.org/2021/03/03/intro-auto-scheduler, docs/deep_dive/tensor_ir/tutorials/meta_schedule
- usenix.org/conference/osdi22/presentation/zhu, arxiv.org/abs/2408.11417 (Stream-K++),
  arxiv.org/abs/2102.05297 (counters), github.com/AMD-AGI/GEAK (methodology card)
- rocmdocs.amd.com/projects/composable_kernel (LDS bank model, 32 banks × 4 B)
- seb-v.github.io/optimization/update/2025/01/20 (FP32 matmul +60% over rocBLAS, the
  contribution ladder: reg tiling → double-buffer GMEM → LDS pad + -mcumode → VGPR/bank
  register placement → inner unroll → SGPR batched addressing)

---

## shipped_floor_contract (folded from shipped_floor_contract.md)

## 1. What the shipped gfx900 library actually is

28 frozen family libraries (+1 lazy placeholder), **2,285 shipped kernels** (live-derived, see `expected_kernels` in the manifest), all mapped onto a
**defensive static mesh** for arbitrary problem shapes, NOT a per-shape tuning result.

| Family | dtype/op set | kernels |
|---|---|---|
| CC | complex | 64 |
| DD | double (U-tiles) | 96 |
| ZZ | small/edge | 26 |
| HH | FP16 (packed) | 223 |
| HH_HPA | FP16 HPA | 424 |
| HS_HPA | FP16 scalar-acc | 493 |
| SS | single 32-bit (big tiles, deep K) | 959 |
| **Σ** | | **2,285** |

Each family = 4 contraction patterns: `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`
(SS `Ailk_Bljk` per-pattern sub-totals are historical — pre-manifest token-count era;
authoritative per-family totals live in the pinned manifest). Top global tiles:
`MT64x64x16` 336, `MT64x64x8` 208, `MT128x64x16` 157, `MT32x32x16` 150, SS heads
`MT128x64x16/MT64x64x16/MT128x64x8`. DD heads `MT64x64x8/MT32x32x8`; HH heads
`MT64x64x16/MT128x64x16`; HPA heads `MT64x64x16/MT64x64x8`; HS heads `MT64x64x8/MT64x64x16`.

gfx900 kernels are **not loadable on gfx90c** (arch-mismatch; ISA900 spoof-builds
mislabel every metric). Native `--arch gfx90c` is supported.

## 2. Replication contract (what oto must produce)

**Reproduce the family matrix natively; let Tensile pick native tiles per family/cell.**
Do NOT chase the 1,980-key size tables — those document the defensive mesh. Anchor the
workload cells (shapes 256³/512³/1024³/2048³ + the suite problem cells) and
emit per-family tile decks from:

1. the mapped gfx900 top-tiles above (translated, never copied: `_ISA900_` kernels are
   not runnable), and
2. the measured frozen prior winners (below) — the only datapoints
   already gfx90c-native (frozen prior conclusions, per `docs/gfx90c_tuning_guide.md` §14 (`archive/prior_insights.md`, untracked)).

The spoof floor for A/B is the **shipped footprint itself**: `oto bench`
benchmarks every shipped kernel once (ScheduleName `vega10`, at the family deck shapes
from `FAMILY_SHAPES`) into a permanent `gfx900_ref_*` **chain** — an interrupted floor
is continued via `oto bench --resume` (retries failed phases once, reuses
decided base phases) — recalled — never re-run — by every later acceptance report.
Expected coverage denominators now come from that pinned manifest, not this (historical) table.

## 3. Native kernel levers that moved the needle (measured, frozen prior)

| Regime | Winner config (native, verified) |
|---|---|
| FP32 large square 1536–4096³ | `SB_MT96x96x16_SN_NLCA3_TT6_6_VW2_VWB2_WG16_16_1_WGM4` (~890-960; 1118.7 @1024³ w/ MT128x128x16 p27) |
| FP32 odd 768³/1000³/1365³ | `SB_MT96x96x16_AMAS3_VW2_NLCA3_TT6_6_WG16_16_1_WGM4` |
| FP32 GEMV decode M1-64 | `SB_MT8x32x32/MT16x32x16/MT32x64x32 + TT1_4/TT2_4/TT4_8 + VW1/VW2 + WG8_8_4_WGM8` |
| FP32 GEMV deeper M32/64 N=K≥2048 | candB `MT32x64x32`; **32x4096x1 +8.1/+13.6%**, **64x4096x1 +17.8/+21.3%** (harvested) |
| FP16 large square | `HB_MT128x128x16_SN_EPS0_NLCA1_PGR0_TT8_8_VW4_VWB4_WG16_16_1` (2492.1 best) |
| FP16 GEMV | `HB_MT16x64x32/SB_MT64x64x16 ... TT2_8/TT4_4`; 64x4096x4096 = 1016 |
| BF16 | `BBS_BH_MT128x64x8/MT128x128x16 ... EPS1_PGR1` (1108.5 best, single-rate) |
| FP64 | `DB_MT32x32x16_AMAS3` / `DB_MT64x64x8` (98.6 = 98% of pipe; saturated) |
| INT8 | `I8II_BH_MT128x128x16_SN_TT8_8_WGM1` (881.2 best; 1024³ INT8 = **+18.3% win** vs spoof) |
| Batched / short-K | candF regimes: 64x11008x1, 4x2048x64, 64x2048x16 (first-ever data) |
| Grid underfill fix | GSU only when grid underfills 7 CUs: 256³→GSU8, 512³→GSU2, 128x128x2048→GSU1 |
| Label-only (ignore) | `ScheduleName: "isa"` vs `"vega10"` — verdict G, no measured effect |

Ruler/floor numbers (single-rate; ceiling authority `docs/gfx90c_theoretical_limits.md`):
FP32 1613, FP16 3226, BF16 1613, INT8 1613, FP64 101.

## 4. Enforcement (how the contract is kept)

- Family coverage = the mapped matrix; each emitted phase is native `isa`, name =
  `phase<N>_<family>_<pattern>` (or collides into existing phase labels by purpose).
- Per-cell verdict uses **throttle-adjusted median-of-seeds**. The tie band is a
  *policy* choice, not a measured fact: the corpus-measured noise floor is ±27.8%
  (repeat CV p90, `ab_audit.repeat_dispersion`), so a ±5% tie band reports
  sub-noise differences as if they were parity. `ab_audit.py` grades at ±27.8%.
  See `docs/gfx90c_results.md` §12.3.
- Peaks are never a signal; gfx900 spoof is a floor; `SPOOF floor is never re-rolled`
  (dedicated `gfx900_ref_*` chain; `--resume` only, no partial re-runs).
- **Retire only on sampling-gated evidence** (≥2 independent runs/cell + CV gates),
  never on a single N=1 run.
- No re-sweep of already-failed cells (potential_configs verdicts carried).

## 5. Concrete next actions (registered in docs/invariants.md Steps 3-6)

1. Emit native family decks in `phases.yaml` (Step 3).
2. Deterministic `--auto` loop drives coverage + convergence (Step 4).
3. Synthesis + anti-alias + whole-library readout (Step 6).
