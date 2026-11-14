# oto

A deterministic, benchmark-driven autonomous kernel tuning suite that generates
optimised Tensile libraries for unsupported AMD GPUs.

`oto` targets **gfx90c** — the Cezanne-family Ryzen APU iGPU, a Vega-derived GCN
part for which **AMD ships no Tensile library** — and proves every result against
the shipped **gfx900** library it is a port of. The gfx900 library is used *only*
as a reference floor (a baseline to beat and a coverage contract to fill); it is
never the target identity and never a signal the tuner optimises for.

The suite is **run-to-convergence, not run-for-a-winner**. It proposes candidate
kernels, benchmarks them under a repeat-and-cooldown policy, harvests winners into
an append-only SQLite ledger, mutates them, and stops only when a cell has enough
independent evidence to be called converged. Every measurement, verdict and
report is reconstructible from that ledger, which is append-only by contract.

* **Driver CLI:** [`oto`](oto) — a thin wrapper over
  [`oto/runners/`](oto/runners/) (`cli.py` dispatches, `driver.py` wires).
* **The contract:** [`claude.md`](claude.md) — entry contract, process
  guardrails, and file ownership.
* **Hardware ceilings & acceptance bars:**
  [`docs/gfx90c_theoretical_limits.md`](docs/gfx90c_theoretical_limits.md).
* **Live results:** [`docs/results.md`](docs/results.md).

---

## Table of contents

1. [Interactive Runtime Controls & Shortcuts](#1-interactive-runtime-controls--shortcuts)
2. [Driver Architecture](#2-driver-architecture)
3. [Usage & CLI Commands](#3-usage--cli-commands)
4. [Repository Layout](#4-repository-layout)
5. [Module Overview](#5-module-overview)
6. [Validation & Analysis Tools (CPU-only)](#6-validation--analysis-tools-cpu-only)
7. [Key Documentation & System Authority](#7-key-documentation--system-authority)
8. [Configuration (`.env`)](#8-configuration-env)

---

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

The Python driver ([`oto`](oto)) coordinates all stages
deterministically. The stage names ("Stage 6", "Stage 7") are the shared
vocabulary used across these docs; the owning package for each stage is shown in
the flowchart and again in the [stage table](#stage--owning-package) below.

```
┌──────────────────────────────────────────────┐
│          phases.yaml (Manifest)              │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 1: Manifest & Target Match             │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 2: Candidate Generation                │
│ (oto/tensile: family decks / mutants)        │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 3: Benchmark Execution                 │
│ (parallel clang + setsid + telemetry)        │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 4: Adaptive Repeat & Policy            │
│ (oto/metrics: N8 median, CV stability)       │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 5: Analytics & SQLite Ledger           │
│ (oto/metrics: ceiling utilization)           │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ CONVERGENCE LOOP (oto/ledger/agent.py)       │
│ - Gate: >=3 configs, >=2 runs, >=6 seeds,    │
│   CV<=15%, 0 RED cells                       │
│ - If unconverged: harvest -> mutate <=2      │
│   knobs -> append                            │
└──────────────────────────────────────────────┘
                       │ Converged
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 6: Synthesis / Build                   │
│ (TensileCreateLibrary + anti-alias)          │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 7: Acceptance A/B & HTML Report        │
│ (oto/metrics: native vs spoof A/B)           │
└──────────────────────────────────────────────┘
```

### Stage → owning package

| Stage | Owns | Package |
|---|---|---|
| Manifest & target match | `phases.yaml` merge, semantic filters | [`oto/runners/phases.py`](oto/runners/phases.py) |
| Candidate generation | family decks, legality gates, mutants | [`oto/tensile/`](oto/tensile/) |
| Benchmark execution | Tensile subprocess, setsid, telemetry | [`oto/runners/benchmark.py`](oto/runners/benchmark.py) |
| Adaptive repeat & policy | median-of-seeds, CV gate, retirement | [`oto/metrics/policy.py`](oto/metrics/policy.py) |
| Analytics & ledger | aggregation, SQLite persistence | [`oto/metrics/analytics.py`](oto/metrics/analytics.py), [`oto/ledger/`](oto/ledger/) |
| Convergence loop | harvest → mutate → decide | [`oto/ledger/agent.py`](oto/ledger/agent.py) |
| Synthesis / build | per-family logic + `TensileCreateLibrary` | [`oto/runners/library_build.py`](oto/runners/library_build.py) |
| Acceptance A/B & report | native-vs-floor verdicts + dashboard | [`oto/metrics/ab_audit.py`](oto/metrics/ab_audit.py), [`oto/metrics/report.py`](oto/metrics/report.py) |

---

## 3. Usage & CLI Commands

### 1. Preflight Verification (Stage 1 Check)
Validate the Tensile binary, GPU hardware access, and registry accessibility:
```bash
python3 -m oto preflight
```

### 2. Semantic Target Filtering & Execution
Run specific mathematical families, contraction patterns, or shapes:
```bash
# Preview the matched manifest targets without running benchmarks:
python3 -m oto bench --family SS --pattern Ailk_Bljk --dry-run

# Benchmark full SS (SGEMM) and HH (HGEMM) families against the reference floor:
python3 -m oto bench --family SS HH

# Run specific problem shapes across all families:
python3 -m oto bench --shape 1024x1024x1024 2048x2048x2048

# Run specific contraction patterns:
python3 -m oto bench --family DD --pattern Ailk_Bjlk Alik_Bljk
```
The seven native families are `SS`, `HH`, `HH_HPA`, `HS_HPA`, `DD`, `ZZ`, `CC`
(the last three are the split/complex classes); each family has its own curated
tile deck under [`oto/tensile/decks.py`](oto/tensile/decks.py).

### 3. Automated HTML & JSON Report Generation
Reports are generated automatically at the end of every run (and on early quit via
`'e'`). Inspect the interactive visual dashboard:
```bash
# View the HTML dashboard in any browser:
xdg-open gfx90c_results/acceptance_report.html
```

### 4. A/B vs the shipped gfx900 floor (Stage 7)
A dedicated `gfx900_ref_*` run benchmarks every shipped gfx900 kernel once (from
the system ROCm `TensileLibrary.dat`), recalled by every later report:
```bash
# 1. Build the reference floor (a full bench pass; --refresh re-scans the dat, --limit N to smoke-test)
python3 -m oto bench --refresh

# 2. Resume an interrupted floor (recalls the whole chain, retries failed once)
python3 -m oto bench --resume

# 3. Any later report recalls the reference floor automatically
python3 -m oto report
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
floor and measured nothing native. The shipped footprint is pinned once at
`gfx90c_results/gfx900_shipped_manifest.json` and supplies the coverage
denominators; provenance (the list of ROCm prefixes scanned) rides in the report
JSON.

### 5. Auto-Convergence Loop
Run the end-to-end deterministic convergence loop across all phase families.

`python3 -m oto tune` **asks first** (on a TTY) and then runs to that plan;
`--yes` accepts the default plan without asking:
```bash
python3 -m oto tune
python3 -m oto tune --yes
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
A/B floor provisional but still tunes, per §3.4.

Outside a TTY (cron, CI) nothing is asked; the defaults are taken and printed.
`--yes` takes them explicitly:
```bash
# Non-interactive, all defaults (no re-measurement, 10 iterations, 3 mutations)
python3 -m oto tune --yes

# Override the numbers the prompt would ask for (defaults are 10 and 3)
python3 -m oto tune --budget 50 --mutations 5

# Non-interactive answer to questions 2 and 3
python3 -m oto tune --yes \
    --include-underspecified --include-unreproducible
```

| Flag | Effect |
|---|---|
| `--yes` | Take the default plan without asking. |
| `--budget N` | Iterations. Overrides the answer to question 4. |
| `--mutations N` | Knobs mutated per candidate. Overrides question 5. |
| `--include-underspecified` | Non-interactive "yes" to question 2 (~1 day of GPU). |
| `--include-unreproducible` | Non-interactive "yes" to question 3. Worth using after a Tensile upgrade, when "unreproducible" may no longer hold. |

Native-only pass, with no reference floor at all (a native-loop sweep, handy as a smoke test):
```bash
python3 -m oto bench --native
```

### 6. Library Synthesis (Stage 6)
Generate and validate the final merged native HIP library with zero `gfx900`
leak anti-alias verification:
```bash
python3 -m oto synthesis
```

---

## 4. Repository Layout

```text
oto/
├── bin/oto                    # repo-root CLI entry — shell wrapper over `python3 -m oto`
├── phases.yaml                # the phase manifest: targets, per-family decks
│
├── oto/                       # the package (see §5 and oto/README.md)
│   ├── device/                # hardware facts: the device profile + cell/kernel vocabulary
│   ├── tensile/               # the Tensile-facing candidate pipeline
│   │   ├── gates/             # assembly / loads / occupancy / VGPR legality gates
│   │   └── synthesis/         # DB-hooked + coverage-guided candidate synthesis
│   ├── ledger/                # append-only registry + mutation/convergence loop
│   ├── metrics/               # aggregation, A/B, verdicts, reports, status
│   ├── runners/               # execution: driver, phases, benchmark, toolchain
│   ├── checks/                # operator diagnostics (the check_*.py backends)
│   ├── tools/                 # offline corpus analysis (all_runs / verify_run / consolidate)
│   └── harness/               # ground-truth candidate machinery for agents
│
├── gfx90c_results/            # registry.db + emitted reports  (data, append-only)
├── gfx90c_runs/               # per-run output directories (telemetry, logs)
├── docs/                      # ecosystem docs + the harness runbook (see §7)
├── plans/                     # tracked implementation & refactor plans (MD)
└── *.md                       # the live MD docs (see §7)
```

`oto/README.md` is a **generated** per-module index (regenerate with
`python3 -m oto.readme_gen`): every entry is the first sentence of that module's
docstring, so it cannot drift from the code. The tables below are the human
orientation layer over it.

---

## 5. Module Overview

### Entry points

| Entry | Purpose |
|---|---|
| [`bin/oto`](bin/oto) | Repo-root CLI entry — a thin shell wrapper over `python3 -m oto` (put `bin/` on `PATH`, or run `./bin/oto` from the repo root). |
| [`python3 -m oto`](oto/__main__.py) | The CLI itself: every `oto <cmd>` subcommand (tune, run, bench, status, report, doctor, preflight, candidate, retirement, analytics, synthesis, verify, check, library, agent, consolidate, stats, chart, version, help, completion). Dispatch: [`oto/cli/dispatch.py`](oto/cli/dispatch.py); full command reference: [docs/cli.md](docs/cli.md). |
| [`bin/` note](#entry-points) | The checks the old root shims exposed (`check candidates`, `check db`, `check retirement`, `check library-parity`, `check tensile-build`) are now `oto check …` / `oto library …` subcommands — see [docs/cli.md](docs/cli.md). |

### `oto/tensile/` — the candidate pipeline

| Module | Purpose |
|---|---|
| [`candidate.py`](oto/tensile/candidate.py) | Candidate generation: the family deck, the sampler, and the append boundary. |
| [`decks.py`](oto/tensile/decks.py) | The curated per-family tile decks — the starting candidates and what kind each is. |
| [`legality.py`](oto/tensile/legality.py) | The legality prior: the manifest-derived legal domain and source-cited walls. |
| [`config_writer.py`](oto/tensile/config_writer.py) | The launch-boundary config writer: the single place a candidate's knobs become Tensile YAML. |
| [`gates/`](oto/tensile/gates/) | The **four-gate preflight** — `assembly.py` (GEMM-class reachability), `loads.py` (classic-path global-load divisibility + 16 B load cap), `occupancy.py` (VGPR + LDS budget), `vgpr_model.py` (the measured VGPR tables). Unknown dtype or unresolvable depth fails **closed**. |
| [`synthesis/`](oto/tensile/synthesis/) | `db.py` (DB-hooked wide/narrow/direction mutants), `manifest.py` (coverage-guided synthesis for one cell), `tile_space.py` (the shared tile/knob vocabulary), `db_knobs.py` / `db_patterns.py` (the mutator's domains and per-family patterns). |
| [`library.py`](oto/tensile/library.py) | The shipped gfx900 manifest: pinning, identity, and the rerun-tier triage. |
| [`library_parity.py`](oto/tensile/library_parity.py) | The coverage-parity rule: what the produced `TensileLibrary` may address. |
| [`shipped_library.py`](oto/tensile/shipped_library.py) | Locating/parsing the system ROCm gfx900 `TensileLibrary.dat` and rebuilding a kernel from its name. |

### `oto/ledger/` — durable state + the convergence state machine

| Module | Purpose |
|---|---|
| [`registry.py`](oto/ledger/registry.py) | Append-only SQLite ledger (`gfx90c_results/registry.db`, WAL mode): records, runs, phases, Option-H proposals. |
| [`registry_core.py`](oto/ledger/registry_core.py) | The ledger engine: connection, schema, transactions, run writes. |
| [`agent.py`](oto/ledger/agent.py) | The deterministic convergence agent: harvest cell winners, generate mutations, check the 4-condition convergence gate. |
| [`harvest.py`](oto/ledger/harvest.py) | Parent selection: which candidate a cell's next mutation starts from. |
| [`mutator.py`](oto/ledger/mutator.py) | The ledger-backed mutation arm: sampling, emission, outcome write-back, overlay. |
| [`proposals.py`](oto/ledger/proposals.py) | The Option-H proposal ledger: emitted candidates and their measured outcomes. |

### `oto/metrics/` — rows → verdicts, reports, status

| Module | Purpose |
|---|---|
| [`policy.py`](oto/metrics/policy.py) | Median-of-seeds aggregation, the CV≤15% stability gate, evidence-gated Tier-2 retirement, and the `should_run` / `should_repeat` gates. |
| [`analytics.py`](oto/metrics/analytics.py) | Stage 5 analytics: CSV loading and per-cell aggregation. |
| [`cell_status.py`](oto/metrics/cell_status.py) | Cell classification: RED (missing) / ORANGE (`<50%` ceiling) / graded coverage. |
| [`ab_audit.py`](oto/metrics/ab_audit.py), [`ab_delta.py`](oto/metrics/ab_delta.py), [`ab_band.py`](oto/metrics/ab_band.py) | Stage 7 A/B: the native-vs-spoof delta arithmetic, the acceptance band, and the audit CLI. |
| [`report.py`](oto/metrics/report.py) | Acceptance report: verdict compute + JSON writer; per-family coverage vs the pinned shipped manifest. |
| [`report_html.py`](oto/metrics/report_html.py), [`report_sections.py`](oto/metrics/report_sections.py), [`report_css.py`](oto/metrics/report_css.py) | The HTML acceptance dashboard (JSON payload → one self-contained file). |
| [`run_status.py`](oto/metrics/run_status.py), [`render_status.py`](oto/metrics/render_status.py) | Run-status text renderings and the live TTY panel. |
| [`telemetry.py`](oto/metrics/telemetry.py) | Per-run CSV sampling of the GPU's clocks and power (non-root `sysfs`). |

### `oto/runners/` — execution

| Module | Purpose |
|---|---|
| [`cli.py`](oto/runners/stage_cli.py) | The driver's stage dispatch — the `--preflight`/`--bench`-style flag routing consumed by [`oto/cli/`](oto/cli/) (`oto <cmd>` itself lives there, in [`oto/cli/dispatch.py`](oto/cli/dispatch.py)). |
| [`driver.py`](oto/runners/driver.py) | The driver composition root: identity, toolchain, wiring. |
| [`phases.py`](oto/runners/phases.py) | The phase runner: manifest merge, policy filter, identical-`fp` skip bypass. |
| [`benchmark.py`](oto/runners/benchmark.py) | The one place a Tensile subprocess is launched. |
| [`reference.py`](oto/runners/reference_floor.py) | The gfx900 reference floor: build, resume, recall. |
| [`auto.py`](oto/runners/auto.py), [`auto_prompt.py`](oto/runners/auto_prompt.py) | The `--auto` convergence loop and the five questions → `AutoPlan`. |
| [`synthesis.py`](oto/runners/library_build.py) | Stage 6: emit per-family library logic and build with `TensileCreateLibrary`. |
| [`toolchain.py`](oto/runners/toolchain.py) | Toolchain discovery: the Tensile checkout and the ROCm toolchain. |
| [`timing.py`](oto/runners/timing.py), [`clocks.py`](oto/runners/clocks.py) | The three numbers conflated as "runtime"; per-phase telemetry clocks and the thermal envelope. |

### `oto/harness/` — ground-truth candidate machinery

| Module | Purpose |
|---|---|
| [`kernel_db.py`](oto/harness/kernel_db.py) | Ground-truth per-kernel-per-shape GFLOPS database. |
| [`regression_matrix.py`](oto/harness/regression_matrix.py) | Deck-vs-floor-vs-all-time cell regression matrix (median basis, per-family shipped grid). |
| [`cell_resolver.py`](oto/harness/cell_resolver.py) | Per-cell native-vs-floor winner resolution over the full knob surface. |
| [`cell_knob_diff.py`](oto/harness/cell_knob_diff.py) | Per-cell winner knob-fingerprint diff (native vs floor). |
| [`occupancy_bounds.py`](oto/harness/occupancy_bounds.py), [`vgpr_measurement.py`](oto/harness/vgpr_measurement.py) | Resident-workgroup audit per cell; measure real per-thread VGPRs from emitted code objects. |
| [`candidate_generator.py`](oto/harness/candidate_generator.py) | The candidate-generator CLI. |

See [`docs/harness_runbook.md`](docs/harness_runbook.md) for the harness workflow,
and [`oto/README.md`](oto/README.md) for the exhaustive per-module index.

---

## 6. Validation & Analysis Tools (CPU-only)

None of these runs a benchmark, so they are safe outside a TTY. Use them to lint a
deck, prove a build, verify the append-only law, and inspect the corpus.

```bash
# Lint a candidate deck. Checks resource legality AND deck self-consistency
# (an id that embeds MT/TT must match its config; fp must be the hash of the
# config actually stored). Exits non-zero on any failure, so it can gate a pipeline.
python3 -m oto check candidates --quiet
python3 -m oto check candidates --family ZZ --json > candidates.json

# Enforcement of the coverage-parity rule: the produced tensilelibrary.dat must
# address EXACTLY the shipped gfx900 cell grid -- no contraction, no extension.
# Exits non-zero on divergence.
python3 -m oto check library-parity --quiet     # deck + seed (+ --run-id's overlay)
python3 -m oto check library-parity --json > parity.json  # machine-readable verdict

# Ground-truth candidate machinery for agents (CPU-only). Builds the per-kernel
# measurement DB and the deck-vs-floor-vs-all-time regression matrix (median
# basis, per-family shipped grid). See docs/harness_runbook.md for the runbook.
python3 -m oto.harness.kernel_db --base-dir . --rebuild
python3 -m oto.harness.regression_matrix --base-dir .

# Ask Tensile itself to generate and compile kernels for every phase, and report
# any reject() reason. Proves solution generation and kernel resource legality --
# it is NOT a complete code-object or library build.
python3 -m oto check tensile-build --jobs 8 --json > build.json
python3 -m oto check tensile-build --family ZZ    # just the ZZ family
python3 -m oto check tensile-build --compare      # cross-check our gate vs Tensile

# Enforce the append-only data law (docs/knowledge_base.md §10). Take a snapshot
# around any run, then diff: a new run dir and more registry rows is clean;
# anything shrunk, removed, rewritten in place, or any lost row exits non-zero.
python3 -m oto verify run snapshot --out before.json
#   ... run the driver ...
python3 -m oto verify run diff before.json after.json

# Is this run's telemetry actually usable? Prints per-phase survival at every
# clock filter (busy -> sclk range -> thermal), so an over-strict filter is
# visible instead of reading as "no clock data".
python3 -m oto verify run telemetry run_20261005_170141

# Cheapest LEGAL phase in the live deck, for a smoke run that costs ~nothing.
# Prints the exact --targets command to drive it.
python3 -m oto verify run cheapest --family ZZ

# Best config per cell across ALL runs, and the knob reach per family.
python3 -m oto stats

# Registry sanity: label contamination and retirement records.
python3 -m oto check db
python3 -m oto check retirement
```

Current state is reported live by each tool: `oto check candidates` prints the
checked/illegal counts it finds, and `oto check tensile-build` prints the pass/fail
counts it computes. Neither is transcribed here (they move when cells are
re-triaged).

---

## 7. Key Documentation & System Authority

| Document | Role |
|---|---|
| [`claude.md`](claude.md) | Entry contract, process guardrails, and file-ownership rules. |
| [`docs/implementation_plan.md`](docs/implementation_plan.md) | The current executable implementation plan. |
| [`docs/shipped_floor_contract.md`](docs/shipped_floor_contract.md) | The shipped `gfx900` footprint → native `gfx90c` replication contract. |
| [`docs/gfx90c_theoretical_limits.md`](docs/gfx90c_theoretical_limits.md) | Hardware ceilings and the acceptance-criteria authority. |
| [`docs/gfx90c_tuning_guide.md`](docs/gfx90c_tuning_guide.md) | The practical knob→effect tuning guide. |
| [`docs/research/kernel_tuning.md`](docs/research/kernel_tuning.md) | GCN hardware model + open research directions. |
| [`docs/research/complex_gemm_brief.md`](docs/research/complex_gemm_brief.md) | The complex/split (CC/ZZ) GEMM research brief. |
| [`docs/search_philosophy.md`](docs/search_philosophy.md) | Objective, gates, and the AI guardrails (canonical philosophy). |
| [`docs/potential_configs.md`](docs/potential_configs.md) | Per-cell candidate evidence and the mutation-strategy catalogue. |
| [`docs/knowledge_base.md`](docs/knowledge_base.md) | Core architecture + the append-only data-preservation law (§10). |
| [`docs/results.md`](docs/results.md) | The live benchmark ledger and frozen ceiling metrics. |
| [`incomplete_work.md`](incomplete_work.md) | The open-work register. |
| [`docs/audit_register.md`](docs/audit_register.md) | The expert-agent audit register and the frozen prior baseline. |
| [`changelog.md`](changelog.md) | The append-only history home. |
| [`docs/README.md`](docs/README.md) | The MD-docs-vs-docstrings boundary, the two agent classes, and the class-tagged registry of owner docs. |
| [`docs/operator_runbook.md`](docs/operator_runbook.md) | **Class B entry** — best-effort Tensile library on an unsupported AMD platform, end to end. |
| [`docs/harness_runbook.md`](docs/harness_runbook.md) | The harness runbook (candidate machinery workflows). |
| [`docs/design_language.md`](docs/design_language.md) | The design-language spec for the HTML acceptance report. |
| `archive/prior_insights.md`, `archive/prior_research_archive.md` | Frozen prior-campaign records (read-only). |

---

## 8. Configuration (`.env`)

Machine-specific locations are read from a `.env` file in the repo root via
`python-dotenv` (`load_dotenv` — precedence: live shell env → `.env`). The ROCm
toolchain is resolved from the **user-provided `ROCM_PATH` only** — like
`TENSILE_ROOT`, it is required and has no fallback; the driver never guesses a
toolchain. `ROCM_BIN` and `ROCM_LLVM_BIN` are derived from `ROCM_PATH` by a
layout-aware probe (`lib/llvm/bin` for TheRock tarballs and system ROCm, the
`_rocm_sdk_core/lib/llvm/bin` wheel layout for TheRock python-sdk venvs,
`lib64/rocm/llvm/bin` for some RPM layouts), and the assembler prefers the
SDK's `amdclang++`. Explicit overrides below win when they point at an
existing path.

| Variable | Default | Purpose |
|---|---|---|
| `TENSILE_ROOT` | required (set in `.env`) | The Tensile checkout root; the driver shells out to `Tensile/bin/Tensile` here. The driver errors out at runtime if unset — there is **no built-in fallback path**. |

Required: `TENSILE_ROOT`, `ROCM_PATH`. Optional overrides: `ROCM_BIN`,
`ROCM_LLVM_BIN`, `TENSILE_ASSEMBLER`, `ROCM_VERSION`, `HIP_PATH`.

See the module docstring of [`oto/runners/toolchain.py`](oto/runners/toolchain.py)
for the resolution order.
