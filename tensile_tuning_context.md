# Tensile `gfx90c` --- AI Tuning Context (attempt2, one-shot)

> Updated 2026-09-13 for attempt2. The architecture that used consultations is
> RETIRED. attempt2 is deterministic and AI-free in the loop. Hardware facts are
> ratified below and must NOT be re-derived from first principles.

## Scope

- Port native `gfx90c` Tensile libraries replicating the shipped gfx900 footprint,
  performing better than the gfx900 spoof floor. No more, no less.
- attempt2 constraint: **ONE-SHOT deterministic convergence**. No LLM consultations.
  Deterministic harvest → mutate(≤2 knobs) → re-run until convergence or budget.
- Manual-LLM contingency: **user-invoked, add-only, worst case only**. A single canned
  prompt producing ≤5 candidate recipe mutations, dumped into `phases.yaml`, flows
  through the same deterministic pipeline. Never an in-loop consultation.

## Core Strategy

```
shipped gfx900 footprint (28 families, 4 patterns)
    ↓ translate decks (mapping.md) — never copy ISA900 kernels
native gfx90c family phases
    ↓ correctness (compiler + client + anti-alias)
HW benchmark (median-of-seeds, ruler-adjusted)
    ↓
deterministic evaluate → harvest wins / mutate ≤2 knobs / tie
    ↓
convergence (no RED cells) → synthesis → acceptance readout
```

## AI Must Not Decide

`gfx90c identity / ISA legality / AsmCaps / compiler flags / runtime support /
correctness / measurement / accepted performance` — including in the manual-LLM
contingency. The model only proposes candidate *parameter vectors*; Tensile generates,
the compiler validates, the hardware decides, the DB remembers.

## Correctness Gate

Always: generate → correctness → benchmark. Never: benchmark → fast → maybe correct.
Wrong kernel = failed candidate. The validator must reject known-invalid configs
(no `AssertSizeMultiple: [1]`, no `SIA>1`, no Fp16AltImpl, LDS ≤ 64 KB/CU).

## Reward Hacking

Independent benchmark + fresh inputs + correctness validation + repeat runs + guard
checks + dtype-specific tolerance. Evaluator stays outside model control. No
max-of-seeds; median-of-seeds is the statistic.

## AI Rollout (attempt2)

- Levels 0–2 (traditional / advisor / mutation-generator-with-validation) are the
  ceiling. Levels 3–5 (local evolution, profile-guided, surrogate/Bayesian) are
  EXPLICITLY OUT unless a later attempt elects them after a good baseline + enough
  data. attempt2 does not require them.

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

## Final Rule

Deterministic loop, HW decides, DB remembers. If the user manually invokes an LLM to
add candidates, the model proposes ≤5; Tensile generates; compiler validates; HW
decides; DB remembers.

## Current State (2026-09-13)

Prior campaign: port mechanics done; parity not wins; candidate deck harvested; 2
control runs pending (`--phases 1 31`, then `--phases 20 25`); attempt2 driver +
ecosystem scaffolded. Consultations consumed in the prior campaign: 3/6 — the
remaining ceremonies are retired by the one-shot contract.