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

The Python driver ([port_tensile.py](port_tensile.py)) coordinates all stages
deterministically. The stage names ("Stage 6", "Stage 7") are the shared
vocabulary these docs use; per-stage module attribution is a code fact and
lives in the module docstrings of [`oto/runners/`](oto/runners/).

```
┌──────────────────────────────────────────────┐
│         phases.yaml (Manifest)               │
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
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 3: Benchmark Execution                 │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 4: Adaptive Repeat & Policy            │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 5: Analytics & SQLite Ledger           │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ CONVERGENCE LOOP                             │
│ - Gate: >=3 configs, >=2 runs, >=6 seeds,    │
│   CV<=15%, 0 RED cells                       │
│ - If unconverged: harvest -> mutate <=2      │
│   knobs -> append                            │
└──────────────────────────────────────────────┘
                       │ Converged
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 6: Synthesis / Build                   │
└──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ STAGE 7: Acceptance A/B & HTML Report        │
└──────────────────────────────────────────────┘
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

The package map is generated, not hand-maintained: every module states its own
ownership (owns / does-not-own / public API) in its docstring, and
[`oto/README.md`](oto/README.md) is the generated index of them. There is no
hand-kept module table here — it went stale the moment the package split; no
corpus count is transcribed here (counts move when cells are re-triaged).

---

## 5. Validation Tools (CPU-only, no GPU needed)

None of these runs a benchmark, so they are safe outside a TTY. Each tool
documents its own exit contract in its module docstring (see
[`oto/checks/`](oto/checks/) and [`oto/tools/`](oto/tools/), indexed in
[`oto/README.md`](oto/README.md)); this section is a pointer, not a copy. The
two operator entry points, and the live flag list, are answered by argparse at
runtime:

```bash
python3 port_tensile.py --help
python3 check_candidates.py --help
```

Current state is reported live by each tool (checked/illegal counts, pass/fail
counts); no count is transcribed here. No corpus count appears in prose (the
live tools / `results.md` report current state).

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

`.env` key table: see the module docstrings of [`oto/runners/toolchain.py`](oto/runners/toolchain.py) (`TENSILE_ROOT` required with no fallback; native ROCm discovery only, no hardcoded candidate chains).
