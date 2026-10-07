# oto
A deterministic, benchmark-driven autonomous kernel tuning suite designed to generate optimised Tensile libraries for unsupported AMD GPUs

## 1. Interactive Runtime Controls & Shortcuts

During execution the interactive single-key listener is active on `stdin` in
**every** phase of a run: while a benchmark kernel is running, during thermal
cooldown sleep, **and while phases are being skipped** because policy already has
that fingerprint (see `--force` to defeat skipping). Skipping is not a gap in the
key handling — a re-run of an already-passed deck is still interruptible.

| Key Shortcut | Action | Description |
|---|---|---|
| **`s`** | **Skip** | Skips the current running benchmark kernel or skips the remaining thermal cooldown sleep immediately. During a skip there is nothing executing to skip, so it is consumed and has no other effect. |
| **`e`** | **End after iteration** | Lets the current benchmark phase finish naturally, then gracefully ends the run and generates `acceptance_report.json` and `acceptance_report.html` (works during thermal cooldown and while skipping too). |
| **`q`** | **Quit & Report** | Gracefully terminates execution, kills active child process groups, and immediately generates `acceptance_report.json` and `acceptance_report.html` from all data collected so far. During a skip it stops at once and the run is recorded as `interrupted`, not `skipped`. |
| **`Ctrl+C`** | **Interrupt (130)** | Kills all child process groups and exits with status 130 after saving run state. |

---

## 2. Driver Architecture

The Python driver ([port_tensile.py](port_tensile.py)) coordinates all stages deterministically:

```
                  ┌─────────────────────────────────────┐
                  │          phases.yaml (Manifest)     │
                  │   (434 phases: SS 105 · HH 40 ·     │
                  │    HH_HPA 20 · HS_HPA 20 · DD 44 ·  │
                  │    CC 32 · ZZ 47 · AUTO 9 · ? 117)  │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 1: Manifest & Target Match    │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 2: Candidate Generation       │
                  │ (scheduler.py: family decks/mutants)│
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 3: Benchmark Execution        │
                  │ (Parallel clang + setsid + telemetry│
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 4: Adaptive Repeat & Policy   │
                  │ (policy.py: N8 median, CV stability)│
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 5: Analytics & SQLite Ledger  │
                  │ (analytics.py: ceiling utilization) │
                  └──────────────────┬──────────────────┘
                                     │
                   ┌─────────────────┴─────────────────┐
│ CONVERGENCE LOOP (agent.py)       │
                    │ - Gate: >=3 configs, >=2 runs/    │
                    │   >=6 seeds, CV<=15%, 0 RED cells │
                   │ - If unconverged: harvest ->      │
                   │   mutate <=2 knobs -> append      │
                   └─────────────────┬─────────────────┘
                                     │ Converged
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 6: Synthesis / Build          │
                  │ (TensileCreateLibrary + anti-alias) │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │ STAGE 7: Acceptance A/B & HTML Rep  │
                  │ (report.py: native vs spoof A/B)    │
                  └─────────────────────────────────────┘
```

---

## 3. Usage & CLI Commands

### 1. Preflight Verification (Stage 1 Check)
Validate Tensile binary, GPU hardware access, and registry accessibility:
```bash
python3 port_tensile.py --preflight
```

### 2. Semantic Target Filtering & Execution
Run specific mathematical families, contraction patterns, or shapes:
```bash
# Preview matched targets without running benchmarks:
python3 port_tensile.py --family SS --pattern Ailk_Bljk --dry-run

# Run full SS (SGEMM) and HH (HGEMM) families:
python3 port_tensile.py --family SS HH

# Run specific problem shapes across all families:
python3 port_tensile.py --shape 1024x1024x1024 2048x2048x2048

# Run specific contraction patterns:
python3 port_tensile.py --family DD --pattern Ailk_Bjlk Alik_Bljk
```

### 3. Automated HTML & JSON Report Generation
Reports are generated automatically at the end of every run (and on early quit via `'e'`). You can inspect the interactive visual dashboard:
```bash
# View the HTML dashboard in any browser:
xdg-open gfx90c_results/acceptance_report.html
```

### 4. A/B vs the shipped gfx900 floor (Stage 7)
A dedicated `gfx900_ref_*` run benchmarks every shipped gfx900 kernel once (from
the system ROCm TensileLibrary.dat), recalled by every later report:
```bash
# 1. One-time: benchmark every shipped gfx900 kernel (dedicated gfx900_ref_* run)
python3 port_tensile.py --gfx900-reference          # --refresh to re-scan the dat, --limit N to smoke-test

# 2. Resume an interrupted floor (recalls the whole chain, retries failed once)
python3 port_tensile.py --gfx900-reference --resume

# 3. Any later report recalls the reference floor automatically
python3 port_tensile.py --report
```
The A/B verdict compares the spoof floor vs native by workload cell
`(family, dtype, shape)`: best-of-cell per arm, medians the unit, ±5% tie band.
Gate semantics: **RED = MISSING** contract cell, **ORANGE = measured but < 50% of
the family realistic ceiling** — both block acceptance.

**`--auto` never gates on the floor.** It asks whether to re-measure the
reference corpus (see §3.5), attempts that if you say yes, and then always
proceeds to native tuning. If the floor is incomplete or failed, the run sets
`reference_floor_authoritative = false` and the report is prefixed
`PROVISIONAL FLOOR`, which marks its A/B verdicts as indicative only. This is
deliberate: three consecutive overnight runs spent their entire budget on the
floor and measured nothing native.
The shipped footprint (2,285 kernels, pinned once at
`gfx90c_results/gfx900_shipped_manifest.json`) supplies the coverage
denominators; provenance (list of ROCm prefixes) rides in the report JSON.

### 5. Auto-Convergence Loop
Run the end-to-end deterministic convergence loop across all phase families.

In a terminal, `--auto` **asks first** and then runs to that plan:
```bash
python3 port_tensile.py --auto
```

It opens with the live size of the reference corpus, split by tier, then asks
five questions — re-measure ILLEGAL, re-measure UNDER-SPECIFIED, re-attempt
UNREPRODUCIBLE, how many iterations (default 10), how many mutations per
candidate (default 3):

```
  reference corpus: <N> cells
    <n>  ILLEGAL          measured with a config we got wrong
    <n>  UNDER-SPECIFIED  glvw/grvw left to Tensile's defaults
    <n>  UNREPRODUCIBLE  cannot be rebuilt

  1. Re-measure the <n> ILLEGAL reference cells? [y/N]
  2. Re-measure the <n> UNDER-SPECIFIED reference cells? [y/N]
  3. Re-attempt the <n> UNREPRODUCIBLE reference cells? [y/N]
  4. How many iterations? (default 10):
  5. How many mutations per candidate? (default 3):
```

Every number above is read at runtime by `auto_prompt._read_counts()` from the
audited tiers in `gfx90c_results/reference_rerun_manifest.json`. None is
transcribed here, so re-triaging a cell changes what you are asked without any
doc to update. `test_auto_prompt.py` asserts the banner and the manifest agree
and that the module itself carries no hardcoded corpus count.

The answers become an `AutoPlan` that governs the run. The three corpus tiers
are **classification only** — no tier decides anything on its own, and the driver
never starts a reference run you declined. Answering "no" to all three leaves the
A/B floor provisional but still tunes, per §4.

Outside a TTY (cron, CI) nothing is asked; the defaults are taken and printed.
`--yes` takes them explicitly:
```bash
# Non-interactive, all defaults (no re-measurement, 10 iterations, 3 mutations)
python3 port_tensile.py --auto --yes

# Override the numbers the prompt would ask for (defaults are 10 and 3)
python3 port_tensile.py --auto --budget 50 --mutation-budget 5

# Non-interactive answer to questions 2 and 3
python3 port_tensile.py --auto --yes \
    --release-under-specified --release-unreproducible
```

| Flag | Effect |
|---|---|
| `--yes` | Take the default plan without asking. |
| `--budget N` | Iterations. Overrides the answer to question 4. |
| `--mutation-budget N` | Knobs mutated per candidate. Overrides question 5. |
| `--release-under-specified` | Non-interactive "yes" to question 2 (~1 day of GPU). |
| `--release-unreproducible` | Non-interactive "yes" to question 3. Worth using after a Tensile upgrade, when "unreproducible" may no longer hold. |

Native-only tuning, with no reference floor at all:
```bash
python3 port_tensile.py --native
```

### 6. Library Synthesis (Stage 6)
Generate and validate the final merged native HIP library with zero `gfx900` leak anti-alias verification:
```bash
python3 port_tensile.py --synthesize
```

---

## 4. Module Overview

| Module | Purpose |
|---|---|
| [`port_tensile.py`](port_tensile.py) | Suite CLI, multi-threaded kernel compilation, subprocess management, continuous telemetry sampling, real-time key listeners (`'s'`/`'e'`/`'q'`), and Stage 6/7 orchestration. |
| [`scheduler.py`](scheduler.py) | Stage 2 candidate generation, family tile decks, legal knob mutation, shape parsing, and the **dual measured resource gate**: `TT0*TT1*dtype_weight <= 128` accumulator VGPRs/thread and `(MT0+MT1)*DepthU*bytesPerElement <= 16384` LDS. Unknown dtype or unresolvable depth fails closed. `cap_vector_width()` derives each family's 16 B global-load-cap variant. |
| [`policy.py`](policy.py) | Median-of-seeds aggregation, CV≤15% stability gating, evidence-gated Tier-2 retirement (`check_retirement_eligibility`), and `should_run`/`should_repeat` policy gates. |
| [`analytics.py`](analytics.py) | Stage 5 analytics, gfx900 contract-cell classification (RED = missing, ORANGE = `<50%` ceiling, GREEN) against realistic ceilings ([gfx90c_theoretical_limits.md §5](gfx90c_theoretical_limits.md#L125)), and per-cell native-vs-spoof deltas (workload cells via `cell_key`). |
| [`agent.py`](agent.py) | Deterministic convergence agent: harvests cell winners, generates candidate mutations, and checks 4-condition convergence. |
| [`registry.py`](registry.py) | Append-only ACID SQLite registry (`gfx90c_results/registry.db`, WAL mode) persisting `json.dumps` payloads. |
| [`report.py`](report.py) | Acceptance report generation, per-family coverage vs the pinned shipped-dat manifest, A/B verdict synthesis (`WIN`, `TIE`, `LOSS`) vs the recalled gfx900 reference floor, and rich HTML dashboard generation. |
| [`tensile_library.py`](tensile_library.py) | System ROCm gfx900 TensileLibrary.dat parser + locator; pins the shipped-kernel manifest (once), emits the 2,285-kernel one-time reference phase list, and chains `gfx900_ref_*` runs (`reference_chain`). |
| [`auto_prompt.py`](auto_prompt.py) | The five `--auto` questions, live corpus counts read from the registry, and the `AutoPlan` they resolve to. Non-TTY defaults are explicit and reported. |
| [`gfx90c_common.py`](gfx90c_common.py) | Single source of truth for hardware constants, theoretical peak tables (`PEAK_GFLOPS`), and the family deck shapes (`FAMILY_SHAPES`). |
| [`verify_run.py`](verify_run.py) | Append-only checker: corpus `snapshot`/`diff` (proves a run only appended, nothing was rewritten or lost), per-run `telemetry` funnel (how many rows survive each clock filter, so a filter cannot silently zero the data), and `cheapest` legal phase for a cheap smoke run. |

---

## 5. Validation Tools (CPU-only, no GPU needed)

None of these runs a benchmark, so they are safe outside a TTY.

```bash
# Lint a candidate deck. Checks resource legality AND deck self-consistency
# (an id that embeds MT/TT must match its config; fp must be the hash of the
# config actually stored). Exits non-zero on any failure, so it can gate a pipeline.
python3 check_candidates.py --quiet
python3 check_candidates.py --family ZZ --json out.json

# Enforcement of the coverage-parity rule (knowledge_base.md §6.1): the produced
# tensilelibrary.dat must address EXACTLY the shipped gfx900 cell grid (38 cells)
# -- no contraction, no extension. Exits non-zero on divergence.
python3 check_library_parity.py --quiet          # deck + seed (+ --run-id's overlay)
python3 check_library_parity.py --json out.json  # machine-readable verdict

# Ground-truth candidate machinery for agents (CPU-only). Builds the per-kernel
# measurement DB and the deck-vs-floor-vs-all-time regression matrix (median
# basis, per-family shipped grid). See harness/README.md for the runbook.
python3 -m harness.kernel_db --base-dir . --rebuild
python3 -m harness.regression_matrix --base-dir .

# Ask Tensile itself to generate and compile kernels for every phase, and report
# any reject() reason. Proves solution generation and kernel resource legality --
# it is NOT a complete code-object or library build.
python3 check_tensile_build.py --jobs 8 --json build.json
python3 check_tensile_build.py --family ZZ          # just the ZZ family
python3 check_tensile_build.py --compare            # cross-check our gate vs Tensile

# Enforce the append-only data law (knowledge_base.md §10). Take a snapshot
# around any run, then diff: a new run dir and more registry rows is clean;
# anything shrunk, removed, rewritten in place, or any lost row exits non-zero.
python3 verify_run.py snapshot --out before.json
#   ... run the driver ...
python3 verify_run.py diff before.json after.json

# Is this run's telemetry actually usable? Prints per-phase survival at every
# clock filter (busy -> sclk range -> thermal), so an over-strict filter is
# visible instead of reading as "no clock data".
python3 verify_run.py telemetry run_20261005_170141

# Cheapest LEGAL phase in the live deck, for a smoke run that costs ~nothing.
# Prints the exact --targets command to drive it.
python3 verify_run.py cheapest --family ZZ
```

Current state: `check_candidates` reports 434 checked, 0 illegal; the last full
`check_tensile_build` run was 434 passed, 0 failed.
---

## 6. Key Documentation & System Authority

* **[claude.md](claude.md)**: Entry contract, process guardrails, and file ownership rules.
* **[implementation_plan.md](implementation_plan.md)**: Current executable implementation plan.
* **[mapping.md](mapping.md)**: Shipped `gfx900` footprint to native `gfx90c` replication contract.
* **[gfx90c_theoretical_limits.md](gfx90c_theoretical_limits.md)**: Hardware ceilings and acceptance criteria authority.
* **[knowledge_base.md](knowledge_base.md)**: Core architecture and append-only data preservation law (§10).
* **[results.md](results.md)**: Live benchmark ledger and frozen ceiling metrics.
* **[incomplete_work.md](incomplete_work.md)**: Open work register and remediation audit records.
* **[adversarial_review.md](adversarial_review.md)**: User-run expert-agent audit register (memory leaks, race conditions, logical bugs) with the frozen prior baseline.

---

## 7. Configuration (`.env`)

Machine-specific locations are read from a `.env` file in the repo root via
`python-dotenv` ([`load_dotenv`](https://github.com/theskumar/python-dotenv) —
industry-standard `.env` loader; precedence: live shell env → `.env`). ROCm
toolchain locations are discovered by native tools only — `hipconfig` for the
install root/HIP paths and `shutil.which` for binaries on `PATH` (this handles
both AMD-installer `/opt/rocm` and Fedora/RHEL RPM `/usr` + `/usr/lib64/rocm`
layouts without any hand-rolled candidate chains). Explicit overrides below win
when they point at an existing path; stale values fall back to native discovery.

| Variable | Default | Purpose |
|---|---|---|
| `TENSILE_ROOT` | required (set in `.env`) | Tensile checkout root; driver shells out to `Tensile/bin/Tensile` here. The driver errors out at runtime if unset — there is no built-in fallback path |

Optional overrides (native discovery otherwise): `ROCM_PATH`, `ROCM_BIN`,
`ROCM_LLVM_BIN`, `TENSILE_ASSEMBLER`, `TENSILE_ASSEMBLER_FALLBACK`.
