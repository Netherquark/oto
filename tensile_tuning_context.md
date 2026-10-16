# Tensile `gfx90c` --- AI Tuning Context

> oto is deterministic and AI-free in the loop. Consultation-based rollouts
> are not used. Hardware facts are ratified below and must NOT be re-derived from
> first principles.

## Scope

- Port native `gfx90c` Tensile libraries replicating the shipped gfx900 footprint,
  performing better than the gfx900 spoof floor. No more, no less.
- oto constraint: **ONE-SHOT deterministic convergence**. No LLM consultations.
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
convergence (no RED cells; budget exhaustion = stop, not pass) → synthesis → acceptance readout
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

## AI Rollout

- Levels 0–2 (traditional / advisor / mutation-generator-with-validation) are the
  ceiling. Levels 3–5 (local evolution, profile-guided, surrogate/Bayesian) are
  EXPLICITLY OUT unless a later attempt elects them after a good baseline + enough
  data. oto does not require them.

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
`gfx90c_tuning_guide.md` §1.1 and the virgin axes in §9.1.

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

## Final Rule

Deterministic loop, HW decides, DB remembers. If the user manually invokes an LLM to
add candidates, the model proposes ≤5; Tensile generates; compiler validates; HW
decides; DB remembers.

## Current State

Port mechanics done; parity not wins (frozen baseline, `prior_*`); the native deck
(`phases.yaml` = 418 phases) plus the dedicated gfx900 reference floor are the
active workflow. Floor `gfx900_ref_20260925_152942`: 1,073/2,285 executed, 1,096
unattempted + 116 failed — continued via `--gfx900-reference --resume`;
`--auto` gates tuning on full floor completion, then converges per-cell verdicts
by workload cell `(family, dtype, shape)`. No LLM consultations in the loop.
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

**Cost model (cheap, no GPU).** Predicted time ≈ `max(flops/peak, bytes/bw) + LDS_conflict_penalty`,
with the conflict factor estimated from stride/DepthU/VectorWidth/bpe/LdsPad. **Use for ordering and
pruning only** — never accept on the model; measurement is the ground truth.

**Measurement hygiene (per allruns.py pass 3 read).** Ban within-the-overlap measurement (a config
whose median comes from a run that overlapped a different invocation) — the 658.2 vs 333.0
multi-shape swing on the same kernel is **real**, not noise, and form-mismatched cells grade
`UNGRADED`. Always destroy the optimizer's draws between iterations; 32 reps per config in
Kernel Tuner is the source-of-truth, versus our 8 seeds which is thin near the band.

## §S.X — Source list (verify each yourself, all live as of the corpus pass)
- arxiv.org/abs/2210.01465 (TEVC 2022), 2407.11488, 2512.04226 (tritonBLAS), 2102.05297,
  2102.04199, 2201.05587, 2604.12891, 2408.11417, 2110.08221, 2102.04199, 1908.05792
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
