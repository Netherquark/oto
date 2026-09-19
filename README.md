# oto
A deterministic, benchmark-driven autonomous kernel tuning suite designed to generate optimised Tensile libraries for unsupported AMD GPUs

## 1. Interactive Runtime Controls & Shortcuts

During execution (both active benchmarking and thermal cooldown sleep), interactive single-key listeners are active on `stdin`:

| Key Shortcut | Action | Description |
|---|---|---|
| **`s`** | **Skip** | Skips the current running benchmark kernel or skips the remaining thermal cooldown sleep immediately. |
| **`q`** | **Quit & Report** | Gracefully terminates execution, kills active child process groups, and immediately generates `acceptance_report.json` and `acceptance_report.html` from all data collected so far. |
| **`Ctrl+C`** | **Interrupt (130)** | Kills all child process groups and exits with status 130 after saving run state. |

---

## 2. Driver Architecture

The Python driver ([port_tensile.py](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/port_tensile.py)) coordinates all stages deterministically:

```
                  ┌─────────────────────────────────────┐
                  │          phases.yaml (Manifest)     │
                   │   (28 families × 4 patterns = 230)  │
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
                   │ - Check: >=2 runs, >=3 configs,   │
                   │   <=1% delta, 0 RED cells         │
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
Validate Tensile binary, Python 3-injection shim, GPU hardware access, and registry accessibility:
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
Reports are generated automatically at the end of every run (and on early quit via `'q'`). You can inspect the interactive visual dashboard:
```bash
# View the HTML dashboard in any browser:
xdg-open gfx90c_results/acceptance_report.html
```

### 4. Same-Run A/B Comparison (Stage 7)
Run head-to-head comparison between spoof baseline and native kernels with thermal cooldowns:
```bash
python3 port_tensile.py --ab target_spoof target_native
```

### 5. Auto-Convergence Loop
Run end-to-end deterministic convergence loop across all 28 families with budget control:
```bash
python3 port_tensile.py --auto --budget 50 --mutation-budget 2
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
| [`port_tensile.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/port_tensile.py) | Suite CLI, multi-threaded kernel compilation, subprocess management, continuous telemetry sampling, real-time key listeners (`'s'`/`'q'`), and Stage 6/7 orchestration. |
| [`scheduler.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/scheduler.py) | Stage 2 candidate generation, family tile decks, legal knob mutation (`≤2` knobs), GEMM LDS estimation `(M*K + N*K)*elem_size*NLCA`, tile divisibility, and shape parsing. |
| [`policy.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/policy.py) | N8 median-of-seeds aggregation, CV stability classification, 3-tier retirement model, and `should_run` policy gate matrix. |
| [`analytics.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/analytics.py) | Stage 5 analytics, RED compute cell classification against realistic ceilings ([gfx90c_theoretical_limits.md §5](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/gfx90c_theoretical_limits.md#L125)), and native-vs-spoof delta calculations. |
| [`agent.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/agent.py) | Deterministic convergence agent: harvests cell winners, generates candidate mutations, and checks 4-condition convergence. |
| [`registry.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/registry.py) | Append-only ACID SQLite registry (`gfx90c_results/registry.db`, WAL mode) persisting `json.dumps` payloads. |
| [`report.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/report.py) | Acceptance report generation, 28-family coverage metrics, same-run A/B verdict synthesis (`WIN`, `TIE`, `LOSS`), and rich HTML dashboard generation. |
| [`gfx90c_common.py`](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/gfx90c_common.py) | Single source of truth for hardware constants and theoretical peak tables (`PEAK_GFLOPS`). |

---

## 5. Key Documentation & System Authority

* **[claude.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/claude.md)**: Entry contract, process guardrails, and file ownership rules.
* **[implementation_plan.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/implementation_plan.md)**: Current executable implementation plan.
* **[mapping.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/mapping.md)**: Shipped `gfx900` footprint to native `gfx90c` replication contract.
* **[gfx90c_theoretical_limits.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/gfx90c_theoretical_limits.md)**: Hardware ceilings and acceptance criteria authority.
* **[knowledge_base.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/knowledge_base.md)**: Core architecture and append-only data preservation law (§10).
* **[results.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/results.md)**: Live benchmark ledger and historical ceiling metrics.
* **[incomplete_work.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/incomplete_work.md)**: Open work register and remediation audit records.
* **[adversarial_review.md](file:///home/netherquark/Soham/Large_code/sources/GPU/backrocm/porting_tensile/attempt2/adversarial_review.md)**: System quality baseline, failure mode audits, and anti-regression checklists.
