# Research corpus: gfx90c GEMM tuning beyond a gfx900-tuned library

> **Status: MINED 2026-10-14.** The durable physics (square-tile ridge ≈154/154/20/
> 77/10, 7-CU tail arithmetic, LDS-bound occupancy) was already folded into
> `potential_configs.md` §1 (F1–F5), `gfx90c_theoretical_limits.md` §7 and
> `kernel_tuning_research.md` §§9.1–9.3 before this mining; the NLC/LSU/GSU
> mechanics live in the gates and research notes. **No new deck row came out of
> this file.** What is raw below stays raw — do not cite it; cite the homes.
> Residual questions it raised (StaggerU×SUS pairing, blocked run design) are in
> `RESEARCH_PROMPT3.md`.

**Research date:** 2026-10-14. **Purpose:** provide a decision-oriented, source-backed corpus for tuning Tensile Assembly GEMM on a 7-CU gfx90c APU. **Execution constraint:** literature/documentation research only; no GPU was used or required.

Confidence labels mean: **VERIFIED** = the cited primary/full source was opened and the claim is visible in it; **PARTIAL** = abstract, summary, indexed source, or indirect architecture transfer; **UNVERIFIED** = I could not confirm the claim. These labels describe source inspection, not universal scientific certainty.

## Executive summary: five findings most likely to change the search

1. **The shipped gfx900/gfx906 tile shapes are not a vote for tiny tiles on this APU.** Tensile's current architecture map explicitly maps `gfx90c` to `vega10` and `gfx906` to `vega20` ([Tensile `Common.py`](https://github.com/ROCm/rocBLAS/blob/develop/library/src/blas3/Tensile/Logic/asm_full/../Common.py) and [current ROCm Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py)). In the actual `vega10` FP32 logic, the first listed candidate is `MT128x016`, `ThreadTile=[4,4]`, `DepthU=16`, `WorkGroup=[32,4,2]`, `VectorWidth=4`, with global prefetch off and local prefetch on; for `vega20` FP64, the first listed candidate is `MT064x064`, `ThreadTile=[4,4]`, `DepthU=4`, `WorkGroup=[16,16,1]`, `VectorWidth=2`, `WorkGroupMapping=8`, `MaxOccupancy=40` ([gfx900 FP32 YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega10/vega10_Cijk_Ailk_Bljk_SB.yaml), [gfx906 FP64 YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega20/vega20_Cijk_Ailk_Bljk_DB.yaml)). The 16×16 FP16/half entries are real too ([gfx906 half YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega20/vega20_Cijk_Ailk_Bljk_HB.yaml)). This is **sampled direct source evidence**, not a complete distribution census. The exact rank-1 solution by runtime shape is selected through the logic table; `SolutionIndex: 0` is the first candidate in a YAML candidate list, not proof that it wins every problem size.

2. **Bigger tiles increase operand reuse, but not without limit.** Under the stated CTA/tile traffic model, square tile arithmetic intensity rises linearly with tile edge: for real inputs, `AI=b/bytes_per_element`; for complex GEMM using 8 conventional FLOPs per complex MAC, `AI=b/2` for complex-single and `AI=b/4` for complex-double. At 42 GB/s and the given arithmetic peaks, the square-tile ridge estimates are roughly 154 for FP32, 154 for packed FP16, 20 for FP64, 77 for complex-single, and 10 for complex-double. Thus an MT128 square remains below the FP32 and packed-FP16 ridge under this model, while FP64 and complex-double cross early. **The ridge is a necessary physics check, not a tile recommendation:** a tile that reaches it can leave most of seven CUs idle, hit VGPR limits, or consume nearly all LDS. The calculation and a resource table are in Q6.

3. **The measured low resident-WG count is plausible, but the data provided cannot distinguish a good high-ILP kernel from an oversized tile.** AMD's GEMM optimization documentation explicitly states that larger per-thread output tiles increase accumulator VGPR use and can lower occupancy; fewer waves can hurt latency hiding, while trying to force VGPR reduction may cause scratch spills ([AMD ROCm GEMM optimization guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html)). The right diagnostic is per-candidate machine code/resource metadata plus issue, memory, scratch, occupancy, and LDS-wait counters. There is no literature-backed universal target such as “two waves/SIMD” for a 7-CU, no-MFMA GEMM. `MaxOccupancy` and `AggressivePerfMode` warrant controlled experiments, not blanket settings.

4. **For a 7-CU grid, wave-quantization loss is severe for small matrices but small as an aggregate tail effect for sufficiently large square GEMMs.** If `G=ceil(M/MT)*ceil(N/NT)` output workgroups exist and each scheduling round covers 7 CUs, launch-level tail utilization is `(G mod 7)/7` active CUs when the remainder is nonzero. Example: a 128×128 output with MT64 has only four workgroups, so at most 4/7 CUs receive work; with MT128 only one CU receives an output block. For 2048×2048, even MT128 produces 256 workgroups and aggregate round utilization is 98.84%. Stream-K specifically attacks output-tile quantization on large GPU arrays, but Tensile's Stream-K path is MFMA-gated in the project; `GlobalSplitU` is the relevant existing knob here. The Stream-K paper reports its own results on its target platforms and does not establish a drop-in solution for this FMA-only APU ([PPoPP 2023 / arXiv](https://arxiv.org/abs/2301.03598)).

5. **Spend the 10-hour tuning budget on a legal, model-pruned, measured candidate set, and fix the measurement protocol first.** The highest-yield path is to (a) stabilize clocks/temperature and benchmark in batches, (b) retain current best candidates as controls, (c) search a low-dimensional, dependency-aware design around output tile size, `ThreadTile`, `DepthU`, vector widths, global prefetch, `LocalSplitU`/`GlobalSplitU` and workgroup mapping, and (d) expand knobs only when counter evidence motivates them. The vendor-published `rocblas-gemm-tune` picks a solution for each listed problem among the installed library's solutions and can emit an override file; it is useful for library-selection baselines, but it is not a substitute for building and measuring new Tensile solutions ([rocBLAS guide](https://rocm.docs.amd.com/projects/rocBLAS/en/develop/how-to/Programmers_Guide.html)). AMD's MAF protocol emphasizes realistic input values, thermal stability, cold caches, and equal distribution of work across compute units; it describes a 1,000 ms run with approximately 25% warmup and 75% measurement as one clock-sampling example ([AMD MAF Part 2](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html)).

---

## §P.2: AMD / GCN coverage census and architecture transfer

### What this review can and cannot count

This is **not a completed year-by-year table-of-contents census across all venues listed in §P.1**. I performed targeted searches and opened primary sources for the directly relevant AMD documentation, logic YAMLs, cost-model papers, performance-portability work, and selected tuning/LLM systems. A truthful fraction of all relevant papers evaluated on AMD **cannot be calculated from this partial set**. Inventing a screened-paper denominator would be worse than leaving the field open. The venue audit below explicitly records this limitation.

### AMD/GPU-family findings

- **Direct GCN/gfx9 evidence found:** AMD's shipped Tensile logic for `gfx900` (`vega10`) and `gfx906` (`vega20`) and its use of `gfx90c` → `vega10` mapping; ROCm's general AMDGPU optimization guide; AMD's Vega ISA document; modern CK-Tile LDS conflict documentation whose examples include later MI architectures. Relevant URLs are embedded under Q1, Q2, Q9 and Q10.
- **Research with AMD Instinct devices found:** the Instruction Roofline Model (IRM) study evaluates Radeon Instinct MI60 and Instinct MI100 alongside NVIDIA V100 for PIConGPU. Its model tracks instruction throughput and memory transactions; the abstract does not claim a gfx900/gfx90c GEMM study ([IRM, arXiv:2110.08221](https://arxiv.org/abs/2110.08221)). The 2026 microbenchmark-driven model evaluates CDNA3 MI300A and NVIDIA B200, reporting 0.09% and 1.31% mean absolute error on its small validation sets; it models MI300A-specific Infinity Cache, VGPR constraints and occupancy, not Vega's FMA-only path ([arXiv:2605.04178](https://arxiv.org/abs/2605.04178)).
- **AMD / Vega-specific kernel tile research:** the exact title *A Faster Tiling Approach for AMD GPUs* (described in the brief as “Tile”, ASPLOS 2020) did not surface in a way that let me verify a full paper. It is marked UNVERIFIED in Q12 rather than cited as though read. Searches did find many later AMD-tuning resources for CDNA/MI platforms, but those are not Vega research. No robust public census of gfx900, gfx906, or gfx90c-targeted GEMM tuning papers was established here.
- **GFX9 VGPR file-size reconciliation:** the often-repeated “64 KB per CU” statement appears to conflate a **64 KiB VGPR file per SIMD** with the CU aggregate. The public AMD GCN architecture deck labels four vector-register banks/files as “4×64KB”, consistent with 256 KiB per CU ([GCN architecture slides mirror](https://dci.dci-gitlab.cines.fr/webextranet/_downloads/7ce42fb9fb3b40a6ebe4b5ba7d25b657/GCN_Architecture.pdf)). LLVM's official AMDGPU documentation separately specifies the per-work-item VGPR count limits and register allocation behavior for GFX6–GFX9, but does not establish total physical-file bytes in the excerpt surfaced ([LLVM AMDGPU usage](https://llvm.org/docs/AMDGPUUsage.html)). I found **no reliable evidence of a 64-KiB-to-256-KiB per-CU physical-register-file change at GCN→Vega**. The defensible interpretation is that a 64-KiB-per-SIMD quantity was mislabeled as per-CU in secondary accounts; §H's observed 256 KiB per CU is consistent with the 4×64 KiB architecture figure. Confidence: PARTIAL because the accessible deck is a reputable AMD training-slide mirror, not the original publisher-hosted file.
- **LDS bandwidth:** public AMD CK-Tile documentation describes 32 banks × 4 bytes and phase-dependent bank-conflict rules for wide loads/stores; AMD ROCm guides describe same-bank accesses being serialized and explain why the layout matters ([CK-Tile bank-conflict guide](https://rocmdocs.amd.com/projects/composable_kernel/en/latest/conceptual/ck_tile/hardware/lds_bank_conflicts.html), [AMD LDS bank-conflict blog](https://rocm.blogs.amd.com/software-tools-optimization/lds-bank-conflict/README.html)). These settle address phasing more clearly than peer-reviewed papers. I did not find a peer-reviewed, gfx900/gfx906 physical measurement that independently settles the exact per-clock aggregate LDS bandwidth on Vega. §H.3 is accepted as ground truth here.
- **AMD's own tuning stack:** rocBLAS/Tensile is the shipped assembly kernel library and `rocblas-gemm-tune` selects among present solutions for a supplied problem set; hipBLASLt/TensileLite provides a separate, newer tuning path on supported architectures. PyTorch TunableOp can benchmark thousands of rocBLAS/hipBLASLt algorithms for GEMM workloads, with the caveat that improvements over the library default are not guaranteed ([ROCm TunableOp/workload guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/optimization/workload-optimization.html)). No evidence was found of an AMD-disclosed learned tile predictor specifically for gfx900/gfx906/gfx90c non-MFMA GEMM.

### Transferability ledger

| Finding | GCN/gfx9 transfer to gfx90c | Qualification |
|---|---|---|
| Wave64 execution model; no MFMA path in this target | High | Use §H as the hardware truth; do not copy CDNA MFMA conclusions. |
| VGPR pressure controls resident waves; scratch spills are costly | High | Verify each emitted object; the performance cost is shape-dependent. [AMD guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html) |
| 32 banks × 4 B LDS addressing and same-bank conflict mechanism | High at the addressing level | Exact timing/phasing and bank implementation claims still need a Vega-specific source or microbenchmark. [CK-Tile guide](https://rocmdocs.amd.com/projects/composable_kernel/en/latest/conceptual/ck_tile/hardware/lds_bank_conflicts.html) |
| MFMA register/AGPR, `matrix_instr_nonkdim`, asynchronous global-to-LDS, CDNA3/4 layout recipes | Low | These are generation- and instruction-family-specific; this target lacks MFMA. [ROCm GEMM guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html) |
| Cache/channel mapping and `StaggerU` interaction | Potentially high | Tensile comments explicitly say `StaggerU` and `WorkGroupMapping` interact and that `StaggerU` requires `BufferLoad=1`; tune together, not independently. [Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py) |

---

## Q1. Vega/gfx9 tile sizing for a bandwidth-starved APU

**Answer. PARTIAL.** Native AMD logic for `vega10` and `vega20` contains small and medium tiles for some data types, including `MT16×16` FP16 and `MT64×64` FP64. A full distributional statistic across every shipped solution file and problem-size decision table is not established in this review. The APU's gfx90c mapping points at `vega10` logic, not at a separately tuned APU-specific solution set. That means the historical configuration being tested is directly relevant as a baseline, but not evidence that its original winner is optimal for shared DDR and seven CUs.

### Directly inspected solutions

These are **top-listed `SolutionIndex: 0` candidates in the actual logic YAML**, with “rank-1” interpreted cautiously. Tensile's top-level problem-size selection logic can choose other indices for other problem geometries; candidate index 0 must not be read as a universal fastest-kernel claim.

| Logic file / datatype | MacroTile | ThreadTile | DepthU | WorkGroup `[w0,w1,LSU]` | Vector width | BufferLoad | Prefetch global/local | StaggerU | WGM | APM | MaxOccupancy | Source |
|---|---:|---:|---:|---|---:|---|---|---:|---:|---:|---:|---|
| `vega10_Cijk_Ailk_Bljk_SB.yaml` (FP32) | 128×16 | [4,4] | 16 | [32,4,2] | 4 | true | false / true | not recorded in the inspected excerpt | 1 | 1 | 40 | [raw YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega10/vega10_Cijk_Ailk_Bljk_SB.yaml) |
| `vega10_Cijk_Ailk_Bljk_DB.yaml` (FP64) | 64×64 | [4,4] | 8 | [16,16,1] | 2 | false | true / true | not recorded in the inspected excerpt | 8 | 1 | 40 | [raw YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega10/vega10_Cijk_Ailk_Bljk_DB.yaml) |
| `vega10_Cijk_Ailk_Bljk_HB.yaml` (FP16) | 16×16 | [2,2] | 8 | [8,8,1] | 2 | true | true / true | not recorded in the inspected excerpt | 1 | 1 | 40 | [raw YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega10/vega10_Cijk_Ailk_Bljk_HB.yaml) |
| `vega20_Cijk_Ailk_Bljk_DB.yaml` (FP64) | 64×64 | [4,4] | 4 | [16,16,1] | 2 | true | true / true | 32 | 8 | 1 | 40 | [raw YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega20/vega20_Cijk_Ailk_Bljk_DB.yaml) |
| `vega20_Cijk_Ailk_Bljk_HB.yaml` (FP16) | 16×16 | [2,2] | 8 | [8,8,1] | 2 | true | true / true | not recorded in the inspected excerpt | 1 | 1 | 40 | [raw YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega20/vega20_Cijk_Ailk_Bljk_HB.yaml) |
| `vega20_Cijk_Ailk_Bljk_ZB.yaml` (complex double) | 64×64 | [4,4] | 4 | [16,16,1] | 1 | true | true / true | 32 | 8 | 1 | 40 | [raw YAML](https://raw.githubusercontent.com/ROCm/rocBLAS/rocm-5.5.1/library/src/blas3/Tensile/Logic/asm_full/vega20/vega20_Cijk_Ailk_Bljk_ZB.yaml) |

The YAMLs set `LdsPadA=0` and `LdsPadB=0` in these examples. Most inspected candidates set `AggressivePerfMode=1`; all examples shown set `MaxOccupancy=40`. These files include a large number of solution records, and a complete frequency distribution of MT, TT, DepthU, load width, prefetch, LSU, WGM and occupancy was **not computed**. The large Vega10/Vega20 FP32/FP64 YAMLs exceed the browser's full-content limit, so their full contents were not parsed in this environment. This is an explicit limitation, not evidence about distribution tails.

### Hypothesis: should the APU go smaller or larger than MT128×128?

The small-tile tendency in the inspected AMD configs **does not imply** that the APU should tune smaller. The relevant opposing effects are:

- Larger tiles improve operand reuse and per-CTA arithmetic intensity. The APU has far less DRAM bandwidth per unit compute than the HBM2 Vega 20 sibling, so reuse is valuable.
- Larger tiles increase accumulator and address-temporary VGPRs. More registers per thread cap waves per SIMD; if the kernel is already at 8–12 waves/CU, a tile that lowers this further can leave load latency exposed.
- Larger MT decreases the count of independent output workgroups. This effect is acute for only seven CUs, particularly for `M,N≤512`.
- Vega's shipped logic contains shape-specialized candidates, so a single MT statistic is not a faithful summary of the library's behavior.

**Recommendation:** do not “flip the bias” to uniformly small or uniformly large. Put `MT64×64`, `MT128×64`, `MT128×128`, `MT128×256`, and a legal ~192 square tile into the search, alongside TT [2,2], [4,4], [6,6], [8,8] as allowed by workload/type constraints; compare by size and dtype. Prioritize enough output workgroups for seven CUs before enlarging an already bandwidth-efficient large GEMM. On square FP32/FP16, MT128 alone has estimated CTA-level AI below the ridge (Q6), so testing larger/asymmetric tiles for large N is rational; for small N, parallelism/launch cost can dominate. The literature reviewed did not provide a verified statement that AMD deliberately chose smaller Vega tiles *because* HBM bandwidth was abundant, nor a universal rule that Vega should be smaller-tiled than CDNA. CDNA's MFMA-specific configurations are not valid evidence for FMA-only Vega.

Confidence: PARTIAL for config samples (full YAML candidates inspected); UNVERIFIED for the full-library frequency distribution and the claimed universal Vega-vs-CDNA tile-size ordering.

---

## Q2. LDS bank conflicts: capacity and latency

**Answer. VERIFIED for bank-address mechanics in AMD's documentation; PARTIAL for exact gfx90c timing.** For classic 32-bank LDS, bank index is `(byte_address / 4) mod 32`; different addresses mapped to the same bank in a simultaneous request serialize, while same-address access can be broadcast. See [AMD ROCm optimization guide, LDS bank conflicts](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html) and [CK-Tile's detailed phase patterns](https://rocmdocs.amd.com/projects/composable_kernel/en/latest/conceptual/ck_tile/hardware/lds_bank_conflicts.html).

### Phases and access shapes

- `ds_write_b128`: CK documentation describes the 64 lanes as eight groups of eight for conflict checking: lanes 0–7, 8–15, …, 56–63. A wide contiguous store is conflict-free when addresses within each phase map to distinct banks.
- `ds_read_b128`: the conflict-check lane sets differ from stores. The documented groups are 0:3+20:23; 4:7+16:19; 8:11+28:31; 12:15+24:27; and the corresponding four groups for lanes 32–63. A layout that looks linear in lane order can collide under these instruction-specific groups; a transposed or swizzled layout can break collisions.
- For scalar `ds_read_b32` with consecutive 32-bit words, the first 32 consecutive lanes naturally map to distinct banks. The next 32 lanes form another bank cycle. This should not be conflated with the instruction-specific `ds_read_b128` bank-check phases. Vector width, alignment, row stride, and lane-to-element mapping determine conflict status.
- Contiguous 64-lane FP32 reads can still hit LDS banks in two logical cycles/phases rather than necessarily suffering a serialization penalty; a 64-lane contiguous address pattern alone is insufficient to diagnose conflict. Inspect the exact instruction and mapping.

### Is the conflict penalty binding in a Tensile GEMM loop?

AMD's guide states that a k-way conflict serializes requests by degree k; the documentation does not show a Vega GEMM experiment demonstrating that LDS conflicts bind a normal Tensile loop. Per §H.3, aggregate LDS bandwidth is not the limiting roof for non-MI GEMM at ordinary tiles. A conflict can still waste instruction latency and affect an already tightly scheduled inner loop, but no direct Vega-specific measured bank-conflict penalty or evidence that it overrides DRAM/wave constraints was found. Do not spend the tuning budget on `LdsPadA/B` before profiler evidence shows `SQ_WAIT_INST_LDS` or a bank-efficiency problem.

### LDS capacity and double buffering

For an unpadded two-operand tile staged as K-strips, an approximate single-buffer footprint is

`LDS_single ≈ (MT_M + MT_N) × DepthU × bytes_per_element`.

Two staged buffers roughly double the footprint. This omits alignment, padding, barriers, and other allocation terms, so the emitted `GroupSegmentFixedSize` or Tensile-computed LDS use is the source of truth. At 64 KiB/CU, example square footprints are:

| MT | DepthU | FP32 single / double | FP16 single / double | FP64 single / double | Complex-single single / double | Complex-double single / double |
|---:|---:|---:|---:|---:|---:|---:|
| 64 | 32 | 16 / 32 KiB | 8 / 16 KiB | 32 / 64 KiB | 32 / 64 KiB | 64 / 128 KiB |
| 128 | 16 | 16 / 32 KiB | 8 / 16 KiB | 32 / 64 KiB | 32 / 64 KiB | 64 / 128 KiB |
| 128 | 32 | 32 / 64 KiB | 16 / 32 KiB | 64 / 128 KiB | 64 / 128 KiB | 128 / 256 KiB |
| 256 | 16 | 32 / 64 KiB | 16 / 32 KiB | 64 / 128 KiB | 64 / 128 KiB | 128 / 256 KiB |

For example, a 128×128 complex-single tile at DepthU=16 consumes about 32 KiB for one set of A/B strips and 64 KiB for two sets, leaving no room for a second resident workgroup if the allocation reaches the full 64 KiB. Complex-double MT128 is not capacity-feasible at these K depths. These are theoretical strip-storage estimates; Tensile's actual layout may differ.

### `LdsPadA/B`

The inspected shipped examples use zero padding. The exact phrase that Tensile's documentation calls this knob “deprecated” and “probably broken” was not independently verified in the documentation inspected for this corpus. No published Vega result demonstrating a benefit from nonzero `LdsPadA/B` was found. Treat it as low priority unless the generated LDS address pattern clearly has collisions.

Confidence: VERIFIED for bank mapping and documented phase sets; PARTIAL for application of later CK-Tile examples to gfx90c; UNVERIFIED for a Vega-specific measured conflict penalty and the quoted deprecation wording.

---

## Q2b. Deliberately capping occupancy on non-MI GEMM

**Answer. PARTIAL.** A low-occupancy FMA GEMM can be optimal if each wave has enough instruction-level parallelism, operands remain in registers, and the active waves already saturate useful pipelines or memory. A cap can also help if excessive concurrency causes cache thrashing. The Tensile schema itself documents `MaxOccupancy` as a workgroups-per-CU limit used “if cache thrashing is hurting performance,” with extra LDS allocated to artificially limit concurrent groups ([Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py)). This is implementation documentation, not evidence that capping helps a FMA GEMM on gfx90c.

In this project, 24/34 winners already sit at no more than three resident workgroups/CU, with only 8–12 waves/CU according to the stated audit. Therefore, more capping is an experiment for a narrow subset, not a default. A candidate that is already VGPR-bound and latency-sensitive is likely to lose when `MaxOccupancy` consumes more LDS and suppresses active workgroups. An already bandwidth-saturated candidate may tolerate a cap, but the proof should be counters plus paired latency measurements.

Confidence: PARTIAL. No peer-reviewed study tuning Tensile `MaxOccupancy` on gfx90c was found.

---

## Q3. GEMM on integrated GPUs sharing system DDR

**Answer. PARTIAL; quantitative public evidence for Ryzen 4000/5000 APU GEMM was not found.** The Tensile architecture map sends gfx90c to the gfx900/vega10 logic family. This establishes a kernel-selection inheritance path, not that the existing library was tuned on APU shared-memory bandwidth. I did not find an auditable rocBLAS-bench report with controlled clocks and GEMM throughput on Ryzen 5 PRO 5650U specifically, or a peer-reviewed study explicitly stating “APU GEMM is bandwidth-bound at tile sizes a dGPU tuner would never choose.”

The public evidence supports mechanisms rather than a per-APU measured recommendation: AMD's guide explains tile reuse, output-tile quantization, VGPR/occupancy interactions, and the tradeoff between an output tile large enough for reuse and enough workgroups to cover the available CUs ([AMD GEMM guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html)). The target-specific measured bandwidth and clock behavior in §H should drive the actual crossover calculation. Do not substitute MI200/MI300 HBM or cache bandwidth for the target's shared DDR figures.

**Implication:** treat `WorkGroupMapping` and `StaggerU` as possible cache/channel-ordering levers after tile candidates exist. Tensile comments explicitly say they interact; the role of these controls is memory access distribution and cache reuse rather than adding arithmetic reuse to a tile ([Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py)). L2 is only 1 MB per §H, so input reuse across many concurrent CTAs should be assumed cautiously.

Confidence: PARTIAL for generic mechanisms; UNVERIFIED for published gfx90c APU GEMM rates and explicit APU-specific tile statements.

---

## Q4. Anti-transfer: why tuning for another accelerator does not port

**Answer. VERIFIED for the general portability conclusion; PARTIAL for the two specified numerical claims.** The exact user-specified `7%` and “at least 20%, up to an order of magnitude” quote for Ringlein, Parnell and Stoica was not independently located in the paper's accessible abstract. The accessible record identifies the paper as *GPU Performance Portability needs Autotuning* and discusses autotuning/JIT for FlashAttention, more parameter configurations, and up to 230% speedup over vendor-optimized implementations, but the abstract alone does not verify the quoted MI250-to-A100 number ([arXiv:2505.03780](https://arxiv.org/abs/2505.03780)). The full paper must be inspected before those exact values are used as verified.

Hochgraf and Pai's *A Few Fit Most: Improving Performance Portability of SGEMM on GPUs using Multi-Versioning* uses CLBlast GEMM timings to argue that one kernel rarely stays near-optimal across all device/workload environments. It reports that multi-versioning/portability tuning can approach within 10% of the theoretical maximum on its tests and generalize to unseen devices ([arXiv:2507.15277](https://arxiv.org/abs/2507.15277)). The precise “142k tuples, 5 GPUs, dynamic range 1.8×–13.2×” parameters from the brief were not verified from the accessible abstract.

### Three portability questions

- **What fraction of a foreign config space is invalid rather than slow?** No generally applicable published fraction was found. It varies with search-space definition. A high-level tile parameter may compile on both backends; a Tensile solution can be illegal due to wave-size, workgroup, per-thread VGPR, LDS, instruction, vector-width or datatype constraints. The denominator matters: “all configurations considered by CUDA/CUTLASS” is not the same space as “all Tensile `validParameters` combinations.” For this study, filter legality before timing and report invalid count and slow-but-valid count separately.
- **Cost to retune Tensile/rocBLAS in GPU-hours:** no source found that supports a general number. `rocblas-gemm-tune` selects from prebuilt library kernels for a problem list; it need not compile a new full logic search. Full custom Tensile tuning includes candidate generation, assembly generation, compilation, correctness/validation and measurements; actual cost depends on number of shapes and candidates, compile-cache reuse and clock stabilization. Report measured wall time and GPU-busy time for this project rather than importing an unrelated autotuner budget.
- **Transferability metric for GEMM tile shapes:** no verified standard metric emerged. A useful project metric can be defined as `speedup(target shape, candidate tile) / speedup(target shape, target-best tile)`, or rank correlation of per-shape candidate performance across devices, while separately recording legality. This is a suggested local metric, not a published standard.

Other confirmed non-portability evidence includes an older cross-vendor OpenCL GEMM study that tuned NVIDIA Tesla C2050 and ATI Radeon 5870 and explicitly found the resulting kernels not highly portable ([ScienceDirect record](https://www.sciencedirect.com/science/article/pii/S0167819111001335)). This predates Vega and only establishes the broad portability issue.

Confidence: PARTIAL. Use the abstracts for general conclusions, not for the precise numerical claims in the prompt until the full papers are checked.

---

## Q5. Cost models that predict tiles without full measurement

| Model / work | Feature set and intended use | Can it predict Tensile MT/TT/DepthU/WG for gfx90c? | Assessment |
|---|---|---|---|
| **MAESTRO**, Kwon et al., MICRO 2019, [arXiv:1805.02566](https://arxiv.org/abs/1805.02566) | Dataflow directives express temporal/spatial reuse and mapping; the model estimates execution time, energy, NoC/buffer costs and occupancy for DNN layers. Authors report fast exploration of 480M candidate designs in the abstract/full text. | **Not directly.** It is a dataflow/hardware cost model, not a model of Tensile's assembly schedule and exact VGPR/LDS allocation. Could inform reuse and traffic features. | Useful conceptual model for arithmetic intensity and mapping legality; lacks target-specific FMA throughput and the actual emitted-code register count. **VERIFIED** from opened paper. |
| **Microbenchmark-driven model for Blackwell B200 / CDNA3 MI300A**, Jarmusch et al., 2026, [arXiv:2605.04178](https://arxiv.org/abs/2605.04178) | Calibrated instruction and hierarchy parameters; tracks B200 TMA/TMEM/tensor cores and MI300A Infinity Cache, VGPR constraints and occupancy. Abstract reports 1.31% MAE on 21 B200 kernels and 0.09% on 27 MI300A kernels; naive roofline errors exceed 95% on that validation set. | **Architecture cannot be copied.** Methodology can be adapted after microbenchmarking gfx90c's FMA/FP64/packed-FP16 issue rates, global-load latencies, DDR/L2 traffic and VGPR/occupancy constraints. | Best model-design template among the specified works, but low reported error on 48 modern matrix-core kernels is not validation for Vega or a new candidate tile space. **PARTIAL** (abstract inspected). |
| **PPT-GPU**, Arafa et al., IEEE Computer Architecture Letters, [OSTI full text](https://www.osti.gov/servlets/purl/1504654) | Hybrid analytical/discrete-event model incorporating memory hierarchies and instruction latencies; paper reports within 10% error on its sampled workloads/devices, up to 450× faster than GPGPU-Sim. | **Potentially, with a substantial model and calibration effort.** It models runtime at a larger granularity than Tensile search and does not directly give knob optima. | Useful for understanding queueing/latency; heavier than required for 100–1000 candidate configurations. **PARTIAL** (full accepted manuscript is linked; this review only inspected the indexed excerpt). |
| **Instruction Roofline Model for AMD GPUs (IRM)**, Leinhauser et al., [arXiv:2110.08221](https://arxiv.org/abs/2110.08221) | ROCProfiler instruction metrics and memory transactions; demonstrated using MI60, MI100 and V100 for PIConGPU. | **No, not by itself.** It classifies instruction intensity/bottlenecks rather than choosing exact tiles; use its diagnostic model to decide which knob family to search. | Strongly AMD-relevant methodology; not an APU GEMM performance predictor. **VERIFIED for abstract/scope; PARTIAL for full model details**. |
| **Hierarchical roofline / ROCm Compute Profiler** | Multiple memory-level roofs and hardware-limit metrics such as cache bandwidth, LDS, waveslots, VGPR/SGPR and dispatch. Tool docs help attribute an observed kernel to a resource roof. | **Partly.** Can reject impossible/poor candidates and prioritize knobs; roofline alone does not model loop schedules, wave quantization, register reuse or launch overhead precisely enough to select TT/DepthU. | Use as a counter-backed screening layer, then time shortlisted candidates. Official tool docs: [ROCm Compute Profiler](https://rocm.docs.amd.com/projects/rocprofiler-compute/en/latest/). |
| **Classical roofline** (Williams, Waterman, Patterson, 2009, [DOI](https://doi.org/10.1145/1498765.1498785)) | Peak FLOPs, bandwidth and arithmetic intensity. | **Only a first-order lower bound.** In the supplied formulation, CTA input-strip re-fetch and shape quantization must be represented; measured cache reuse can also alter DRAM traffic. | Do not use a minimum-global-traffic intensity as if it were achieved traffic for each tiled CTA. **VERIFIED for reference; analytical use is standard.** |

### Most consequential features for a gfx90c analytical candidate model

Represent these explicitly: dtype and operation-count convention; `MacroTile_M/N`; `ThreadTile`; `DepthU`; workgroup wave count and shape; local split; input operand bytes per K stage; single/double buffering; predicted LDS allocation; accumulator VGPR lower bound and emitted VGPR count when known; per-wave issue throughput for FMA, packed F16 and FP64; observed DRAM bandwidth and L2 hit rate; launch/dispatch overhead; number of output workgroups and tail wave; K-loop count; vectorization/coalescing; edge/tail handling; `BufferLoad`; prefetch settings; scratch spills; and measured clock/thermal state. The model should rank/prune. It should not replace all measurements until calibrated on this GPU and these kernel objects.

Confidence: VERIFIED/PARTIAL by row as stated.

---

## Q6. Roofline for tiled GEMM: explicit ridge table

**Answer.** For a tile of `M_t × N_t`, assuming each CTA loads one A strip and one B strip per K iteration, operand bytes per K element are `(M_t+N_t) × bytes_per_element`. The CTA performs `2 M_t N_t` real FLOPs per K step, so

`AI_real = 2 M_t N_t / ((M_t+N_t) × s)` FLOP/B,

where `s` is bytes per real element. For complex arithmetic counted at eight real FLOPs per complex multiply-accumulate, use

`AI_complex = 8 M_t N_t / ((M_t+N_t) × s_complex)` FLOP/B.

For square tile `b×b`, these reduce to `AI_real=b/s` and `AI_complex=4b/s_complex`. This is tile-staged operand traffic; actual DRAM traffic can differ if inter-CTA cache reuse serves the requests. The standard roofline ridge is `R=P_peak/BW`; with BW=42 GB/s, this table yields the threshold where arithmetic could become the roof under that traffic model.

### Peak/ridge and tile size

| Datatype | Peak convention from §H | `P_peak / 42 GB/s` | Square-tile AI | Approx square edge at ridge | Practical rectangular/square example crossing ridge | Assessment |
|---|---:|---:|---|---:|---|---|
| FP32 | 1613 GFLOP/s | 38.4 FLOP/B | `b/4` | 154 | 128×256 gives 42.7 FLOP/B; 192×192 gives 48 | MT128×128 gives 32 FLOP/B, still below ridge. Larger/asymmetric output tiles are justified for large GEMMs if VGPRs and workgroup count permit. |
| packed FP16 | 3226 GFLOP/s | 76.8 FLOP/B | `b/2` | 154 | 128×192 gives 76.8 FLOP/B; 160×160 gives 80 | MT128×128 gives 64 FLOP/B, slightly below ridge. Tile reuse still matters at large N. |
| FP64 | 101 GFLOP/s | 2.40 FLOP/B | `b/8` | 19.2 | 32×32 gives 4 FLOP/B | The modeled bandwidth ridge is reached by a small tile. Enlarging MT for reuse may be counterproductive if it cuts CTA count or worsens VGPR-limited occupancy. |
| complex single (`C`) | 1613 GFLOP/s in the usual 8-FLOP complex-MAC convention | 38.4 FLOP/B | `b/2` (8 B per complex value) | 76.8 | 64×128 gives 42.7 FLOP/B; 96×96 gives 48 | A ~96-square output tile reaches the modeled ridge; the user-measured 21% of peak likely needs instruction-count, load/store, register and scheduling investigation as well as tile search. |
| complex double (`Z`) | 101 GFLOP/s in the usual 8-FLOP complex-MAC convention | 2.40 FLOP/B | `b/4` (16 B per complex value) | 9.6 | 16×16 gives 4 FLOP/B | Normal legal tiles are above the modeled ridge. The very low observed fraction of peak cannot be fixed by tile size alone if the bottleneck is scalar instruction count/register pressure/dispatch. |

The convention for complex peak is crucial: one complex MAC conventionally counts as 8 FLOPs. Since the implementation expands it across scalar FMA instructions, the peak in that same complex-FLOP accounting is comparable to the stated scalar FP32 or FP64 operation rate. The calculation is dimensionally consistent with Tensile's `flopsPerMac=8` in §H.

### LDS and VGPR feasibility overlays

The following table is a screening approximation, not a generated-code occupancy prediction. `LDS=2bD s` for square tile edge `b` and unroll depth `D`; “double” doubles that staging. For real FP64, the accumulator lower bound assumes two 32-bit VGPRs per 64-bit value. For complex values, the register cost uses the §H convention. Real FP16 register packing can depend on the generated implementation, so a simple logical-element count is conservative only as a rough bound.

| Candidate | Single-buffer LDS | Double-buffer LDS | Accumulator VGPRs/thread lower bound for representative TT | VGPR/occupancy note |
|---|---:|---:|---|---|
| FP32 `MT128×128`, `DepthU=32`, `TT8×8` | 32 KiB | 64 KiB | ~64 | VGPR occupancy plausible but temporary registers add pressure; double-buffering consumes all 64 KiB, typically precluding a second CTA. |
| FP32 `MT128×256`, `DepthU=16`, `TT8×8` | 24 KiB | 48 KiB | ~64 | Crosses the intensity ridge while holding a relatively low LDS footprint; WG shape and available CTA count still matter. |
| FP16 `MT128×192`, `DepthU=32`, `TT8×8` | 20 KiB | 40 KiB | packing-dependent, nominally 64 logical accumulators | Ridge-crossing tile is not LDS-expensive; check packed lane mapping, load vector legality, and register counters. |
| FP64 `MT32×32`, `DepthU=64`, `TT4×4` | 32 KiB | 64 KiB | ~32 | Already above ridge; prefer this scale as one test point before exploring larger MT. |
| Complex-single `MT96×96`, `DepthU=16`, `TT6×6` | 24 KiB | 48 KiB | ~72 | Under the 256-VGPR/thread ceiling before temporaries, but complex pointer/math code can raise register demand substantially. |
| Complex-double `MT16×16`, `DepthU=64`, `TT2×2` | 32 KiB | 64 KiB | ~16 | Above ridge; avoid large `ThreadTile` because each logical accumulator consumes four 32-bit VGPRs under §H. |

With `TT8×8`, accumulator-only storage is approximately 64 VGPRs for FP32, 128 VGPRs for complex-single, 128 VGPRs for FP64 under a two-VGPR double convention, and 256 VGPRs for complex-double. The last case reaches the hard maximum **before** temporaries and is therefore not a viable working design. `TT16×16` is not a sensible general choice for FP64/complex formats under these register conventions. The actual emitter and object metadata must confirm counts.

### Cache blocking rule and practical meaning

The general cache-blocking principle is to choose blocks that exploit reuse at a particular memory level without exceeding that level's effective capacity or reducing parallelism enough to offset the traffic savings. Modern AMD documentation restates the same balance: larger thread tiles raise arithmetic intensity but consume more VGPRs; larger operand blocks consume LDS and can reduce concurrently resident workgroups ([AMD GEMM optimization guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html)). MAESTRO formalizes reuse and resource limits as dataflow cost features ([paper](https://arxiv.org/abs/1805.02566)). I could not independently verify the exact bibliographic details of the brief's “van de Geer & Wolrich PPoPP'95” citation, so it is not used as a confirmed reference here.

**Does the ridge land in Tensile's legal space?** Yes, geometrically for FP32, FP16 and complex-single, through larger or asymmetric MT shapes; a `[8,8]` thread tile with a 2-D workgroup can form shapes such as 128×256, subject to the workgroup-size multiple-of-64/max-1024 rules in §H.3. But ridge attainability is separate from resident waves and grid size. For FP64 and complex-double, legal small tiles already cross the ridge. This strongly implies that the very poor complex performance in the project should not be approached as “simply increase all tiles.”

Confidence: VERIFIED as algebra given §H peaks and traffic model; PARTIAL for actual DRAM-level AI because cache reuse and hardware transactions vary.

---

## Q7. Wave quantization on seven CUs

**Answer. VERIFIED arithmetic, PARTIAL technique transfer.** Define `G=ceil(M/MT_M)×ceil(N/MT_N)`. In each scheduling round, at most seven CUs can host an output workgroup. If `G mod 7 = r != 0`, the final round has `r` CUs doing work and `7-r` idle, so tail-round idle fraction is `(7-r)/7`. If `r=0`, no partial tail exists. Total launch-level utilization under equal-length workgroups is `G / (7 ceil(G/7))`.

For square matrices `N×N` with square `MT=b`:

| N | MT | Grid / workgroups | `G mod 7` | CUs idle in final round | Aggregate scheduling utilization |
|---:|---:|---:|---:|---:|---:|
| 128 | 16 | 8×8 = 64 | 1 | 6/7 = 85.7% | 91.43% |
| 128 | 32 | 4×4 = 16 | 2 | 5/7 = 71.4% | 76.19% |
| 128 | 64 | 2×2 = 4 | 4 | 3/7 = 42.9% | 57.14% |
| 128 | 128 | 1×1 = 1 | 1 | 6/7 = 85.7% | 14.29% |
| 256 | 16 | 16×16 = 256 | 4 | 3/7 = 42.9% | 98.84% |
| 256 | 32 | 8×8 = 64 | 1 | 6/7 = 85.7% | 91.43% |
| 256 | 64 | 4×4 = 16 | 2 | 5/7 = 71.4% | 76.19% |
| 256 | 128 | 2×2 = 4 | 4 | 3/7 = 42.9% | 57.14% |
| 512 | 16 | 32×32 = 1024 | 2 | 5/7 = 71.4% | 99.51% |
| 512 | 32 | 16×16 = 256 | 4 | 3/7 = 42.9% | 98.84% |
| 512 | 64 | 8×8 = 64 | 1 | 6/7 = 85.7% | 91.43% |
| 512 | 128 | 4×4 = 16 | 2 | 5/7 = 71.4% | 76.19% |
| 1024 | 16 | 64×64 = 4096 | 1 | 6/7 = 85.7% | 99.85% |
| 1024 | 32 | 32×32 = 1024 | 2 | 5/7 = 71.4% | 99.51% |
| 1024 | 64 | 16×16 = 256 | 4 | 3/7 = 42.9% | 98.84% |
| 1024 | 128 | 8×8 = 64 | 1 | 6/7 = 85.7% | 91.43% |
| 2048 | 16 | 128×128 = 16384 | 4 | 3/7 = 42.9% | 99.98% |
| 2048 | 32 | 64×64 = 4096 | 1 | 6/7 = 85.7% | 99.85% |
| 2048 | 64 | 32×32 = 1024 | 2 | 5/7 = 71.4% | 99.51% |
| 2048 | 128 | 16×16 = 256 | 4 | 3/7 = 42.9% | 98.84% |

The `tail round` idle fraction can be high for any matrix size; what matters for elapsed time is the aggregate fraction across all rounds. For 2048², the aggregate difference between tested tile sizes is small under a uniform-cost workgroup model, while compute efficiency, VGPRs, LDS and scheduling affect elapsed time. At 128², the grid is too small for MT64/128 and tile-size choice is dominated by how few total output groups remain, not only tail-round quantization.

### Published fixes

- **Stream-K:** rebalances K-loop work among a more uniform number of processing elements and directly targets tile-grid quantization; the paper reports large speedups over CUTLASS/cuBLAS for its tested GPUs and 32,824 problem geometries ([PPoPP 2023 / arXiv:2301.03598](https://arxiv.org/abs/2301.03598)). The project notes its Tensile path is MFMA-gated, so this is design motivation rather than an available gfx90c toggle.
- **Split-K / `GlobalSplitU`:** divides the contracted K work among independently scheduled workgroups but creates partial sums and a reduction/atomic cost. For small M×N and long K, that trade can expose parallelism. It is less compelling when the output grid already substantially exceeds seven workgroups and system DRAM is the bottleneck. See Q15.
- **Hybrid/granular work decomposition:** algorithmically promising; no published result specifically treating a fixed seven-CU Vega APU was found. A workgroup-count arithmetic argument is enough to motivate experiments, but not to nominate a universal tile winner.

**No “best total-time tile” can be selected from quantization arithmetic alone.** For large square workloads all four MT sizes show high aggregate scheduling utilization, and the register/traffic model differs by dtype. For small squares MT16/32 usually leave a larger grid; for large FP32/FP16, tiles above 128 may still save traffic enough to compensate. Measure by matrix size and dtype.

Confidence: VERIFIED arithmetic; PARTIAL on technique transfer; UNVERIFIED for a published seven-CU/non-power-of-two accelerator study.

---

## Q8. Persistent / low-occupancy GEMM, without matrix cores

**Answer. PARTIAL.** “Low occupancy” can describe two very different situations:

1. **Intentionally high-ILP kernel:** a thread owns a large accumulator fragment and reuses loaded values for many FMAs. It has few active waves but each wave performs substantial useful work and may still sustain the relevant arithmetic pipe.
2. **Accidentally resource-starved kernel:** an MT/TT choice raises VGPR use and LDS so high that too few waves/CTAs remain to hide long global-memory or dependency latency, with no compensating reuse or issue efficiency.

AMD's GEMM guide explicitly describes both sides of this trade: a thread tile holds an accumulator array, greater VGPR use reduces occupancy, and forced register reduction can spill to scratch and degrade performance ([AMD guide, register pressure](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html)). Stream-K addresses quantization rather than declaring low occupancy universally optimal ([paper](https://arxiv.org/abs/2301.03598)). The 2026 ISC CUTLASS FP8/1.00 waves-per-SM/14% achieved-occupancy datapoint and the named PERKS SC'23 result were not independently located in a full paper for this review and are left UNVERIFIED.

### Diagnosis needed on gfx90c

For each native object record `VGPR_Count`, LDS group segment size, scratch bytes, workgroup size, and actual resident waves. Then collect available execution counters, including wave occupancy, memory transactions/bandwidth, scratch use, LDS waits and instruction issue. AMD's current GEMM guide demonstrates `rocprofv3` use and notes that occupancy targets must be validated against spills and LDS wait counters ([guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html)).

The project-reported 8–12 waves/CU may be enough for some throughput-saturated FMA kernels, but a low active-wave count by itself neither validates nor invalidates the tile. Given seven CUs, measure per-shape parallelism and pipeline saturation rather than optimizing an occupancy percentage in isolation.

Confidence: PARTIAL; no verified non-MFMA gfx90c occupancy-vs-GEMM study was found.

---

## Q9. Occupancy as a controllable Tensile lever

### `MaxOccupancy`

**Answer. PARTIAL.** Tensile's source documents `MaxOccupancy` as “wg / CU” and says it can allocate extra LDS “if cache thrashing is hurting performance,” to limit occupancy artificially ([Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py)). The project states that all shipped gfx900/gfx906 configurations use 40, meaning no intentional cap. No peer-reviewed paper or practitioner measurement specifically tuning this knob for non-MI gfx9 GEMM was found.

Mechanism: extra LDS reservation reduces the number of resident workgroups without directly reducing arithmetic work. That could lessen L1/L2 contention or alter scheduling when extra concurrent CTAs only fight over a constrained cache. It can also reduce the number of waves capable of hiding global-memory latency and can lower workgroup-level throughput. With only 7 CUs and measured winners already at low occupancy, blanket capping has a high downside risk.

**Test:** compare `MaxOccupancy=40` to a small bracket such as 4, 8, 12 and 20 only on candidates whose existing resource model supports the intended resident-CTA count. Measure emitted LDS allocation and observed workgroups/CU; remember that the integer represents workgroups/CU in this Tensile implementation, not waves/SIMD. Avoid interpreting a setting as a direct wave target.

### `AggressivePerfMode`

**Answer. PARTIAL.** The inspected gfx900/gfx906 YAMLs use mode 1 in the examples. The user's project description reports that mode 2 also modifies LDS so only two waves/SIMD fit, whereas mode 1 inserts `s_setprio`. I did not find a published mode-2 study establishing that exactly two waves/SIMD is optimal for a non-MI FMA GEMM. Because §H.3 says one wave per SIMD only reaches half the LDS bandwidth, the argument for a two-wave minimum applies only to kernels actually limited by LDS traffic. It does not imply that two waves/SIMD is optimal for hiding DRAM latency or for a scalar FMA pipe.

**Test:** retain mode 1 as baseline, compare mode 0 and 2 on selected representative shapes; inspect LDS footprint/occupancy and issue counters. Do not set mode 2 globally from the LDS-bandwidth argument alone.

### `GlobalSplitU` as a parallelism knob

Split-K can create independent workgroups when the output tile grid is too small. A simplified break-even test is

`T_saved_by_more_CU_parallelism > T_extra_partial_store + T_reduction_launch + T_partial_read/reduce + any atomics/contention`.

It is most promising for small M×N, long K, low baseline CTA count. For already large output grids, the added partial sums and reduction are usually pure overhead. See Q15 for data-type/correctness constraints.

### Target occupancy

No evidence-backed universal occupancy target for non-MI GEMM on a 7-CU chip was located. The principled rule is: enough independent waves to hide the measured dominant latency and saturate the active issue/memory pipelines, subject to VGPR/LDS caps. Find this empirical knee per family. A target inherited from a 60-CU gfx906 or from matrix-core kernels is not defensible without direct measurement.

Confidence: PARTIAL for mechanisms and source code; UNVERIFIED for published tuning evidence on the two knobs.

---

## Q10. State of practice for per-architecture rocBLAS/Tensile tuning

**Answer. VERIFIED for vendor tooling; PARTIAL for tuning-time/yield claims.** The official rocBLAS guide documents `rocblas-gemm-tune`, batch `rocblas-bench`, profile logging (`ROCBLAS_LAYER=4`), and applying saved choices through `ROCBLAS_TENSILE_GEMM_OVERRIDE_PATH`. `rocblas-gemm-tune` benchmarks solution choices available in the installed rocBLAS library, and selected indices cannot be ported blindly across library versions/architectures. `ROCBLAS_USE_HIPBLASLT=1` bypasses Tensile overrides when hipBLASLt is forced/default ([current rocBLAS programming guide](https://rocm.docs.amd.com/projects/rocBLAS/en/develop/how-to/Programmers_Guide.html)). The same guide recommends YAML-batched `rocblas-bench` for many shapes, avoiding repeated library-loading overhead.

The separate PyTorch TunableOp path benchmarks algorithms available in rocBLAS and hipBLASLt; AMD's guide says it may try thousands of GEMM algorithms and explicitly warns that performance gains over the default are not guaranteed ([ROCm workload optimization](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/optimization/workload-optimization.html)). The hipBLASLt tuning utility produces benchmark results and logic YAML; that is relevant to supported hipBLASLt/TensileLite hardware, but is not proof that all these kernels are useful for gfx90c without MFMA.

### Practical 10-hour budget

1. **First hour: stabilize and validate instrumentation.** Warm up the GPU, verify clocks at load, ensure representative input toggles, use cold-cache and cache-hot regimes deliberately, and quantify run-to-run variation before comparing candidates. AMD's MAF methodology explains why thermal state, toggle rates and cold caches matter ([source](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html)).
2. **Next 1–2 hours: build legality/cost pruning.** Generate only combinations satisfying §H.3 (workgroup multiple of 64 and ≤1024, TT≤16, vector byte widths≤16, per-thread VGPR≤256, LDS≤64KiB, correct dtype and `MatrixInstruction=[]`). Normalize derived/equivalent configurations so duplicates are not compiled/measured.
3. **Next 5–6 hours: measured sweep with controls.** Use a fractional, dtype-specific set: FP32 and packed FP16 at 128/256/512/1024/2048 square; FP64 at small/medium/large shapes; complex single/double on the worst cells. Prioritize TT, MT, DepthU, vector width, prefetch, `LocalSplitU`, `GlobalSplitU` only where the grid is small, and WGM/StaggerU together. Interleave a baseline candidate through the run to detect thermal drift. Candidate count should be bounded by actual compile-plus-measure throughput; no source supports a fixed “1000 candidates fits in 10 hours” claim for this machine.
4. **Last 1–2 hours: repeat winners, test edge shapes and package the per-shape logic.** Repeat winners in randomized order, inspect object resource metadata, retest correctness/edge conditions, and preserve a small set of robust solutions rather than promoting single-run outliers.

`_fallback` is a separate risk: verify that each workload/architecture/type actually matches the intended Tensile logic rather than silently landing on a generic/fallback implementation. Record selected kernel name/index in the benchmark output. A custom YAML tuning set is not useful if the runtime library routes the actual problem to a different backend.

`mblas-bench` and its “multiple heuristic solutions” pipeline were not verified from an authoritative source in this review. Do not make it a required dependency on that basis. No defensible public GPU-hour/yield figure specific to Tensile custom candidate search was found.

Confidence: VERIFIED for vendor API and override behavior; PARTIAL for the 10-hour schedule (project-specific recommendation).

---

## Q11. Measurement methodology and DVFS on this machine

**Answer. PARTIAL for gfx90c clock control; VERIFIED for AMD's general benchmark controls.** Linux's AMDGPU driver exposes `power_dpm_force_performance_level` options including `auto`, `low`, `high`, `manual`, and `profile_peak`; the kernel source describes `manual` operation using `pp_dpm_mclk`, `pp_dpm_sclk`, and `pp_dpm_pcie` and describes `profile_peak` as a performance profile ([Linux AMDGPU power management source](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/pm/amdgpu_pm.c)). Whether every option is writable/exposed on an APU depends on driver, firmware and platform; this corpus did not verify a gfx90c-specific clock-pinning path. `pp_dpm_sclk` lists states when the driver exposes it; forcing performance level is not the same as guaranteeing a constant sustained clock under thermal/power limits. Record permissions and actual observed state instead of assuming success.

### Protocol

- **Warmup and thermal state:** AMD's MAF benchmark used a 1-second run with approximately 25% warmup / 75% measurement to allow clock stabilization, checked clock progression using `amd-smi`, and recommends a thermally stable device ([MAF Part 2](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html)). The target-specific corpus reports that busy clocks rise with temperature; the exact per-machine clock-temperature relationship in §H should be used.
- **Input initialization:** use representative random/normal values. AMD reports that low-toggle data (all zeroes or small ranges with similar exponents) can inflate clock frequency by more than 50% in its measured case ([MAF Part 2](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html)).
- **Cold vs hot cache:** test both if the workload mix warrants it. For cold-cache runs rotate through tensors beyond cache size or flush caches; do not compare a cold-cache baseline with a hot-cache candidate unintentionally ([MAF Part 2](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html)).
- **150 µs–80 ms kernel range:** for short kernels, batch many invocations to accumulate a stable timing window rather than relying on a single dispatch. For long kernels, several repeat measurements per candidate are usually sufficient to estimate median and spread, but the required count must be set from pilot variance. Keep compile and first-call/JIT/library initialization separate; rocBLAS notes that its first GEMM call may include library initialization unless `rocblas_initialize()` is called after device setup ([rocBLAS guide](https://rocm.docs.amd.com/projects/rocBLAS/en/develop/how-to/Programmers_Guide.html)).
- **Single-machine noise floor:** no universal numeric noise floor was found for a Ryzen 5650U. Derive it from repeated baseline blocks spread across the experiment. Store median, MAD or interquartile range, coefficient of variation, observed core clock, temperature, and run order; reject candidate claims whose observed difference is below the measured control spread.
- **AMD timers:** official rocBLAS guide says `rocblas-bench` uses HIP events to time API calls and ignore `hipStreamSynchronize` overhead, with `ROCBLAS_BENCH_STREAM_SYNC=1` to switch to the older synchronization timing path. YAML batch benchmarking eliminates repeated library-loading overhead ([guide](https://rocm.docs.amd.com/projects/rocBLAS/en/develop/how-to/Programmers_Guide.html)).

The brief's documented gfx1151 `auto` vs `profile_peak` +37.8% result was not independently found as a primary source here; do not copy its quantitative magnitude to gfx90c. The general burst/clock problem is plausible and makes direct clock telemetry mandatory.

Confidence: VERIFIED for AMD's published MAF protocol and Linux driver interface; PARTIAL for gfx90c-specific pinning; UNVERIFIED for the exact gfx1151 +37.8% transfer.

---

## Q12. Classical non-agentic autotuning techniques

The main distinction for a 10-hour GPU budget is whether a method **reduces expensive hardware measurements** or simply orders/relabels them. Search-space constraints, analytic pruning, and an adequately calibrated predictive cost model can remove candidates before execution. Random, grid and brute-force approaches primarily choose which points to try; an early stopping budget may make random search useful, but it does not itself prove that the removed region is poor. Evolutionary search, Bayesian optimisation and bandit methods may reduce measured points by exploiting results, although benefits depend on feature/parameter encoding and noise.

| Technique / source | Search space and hardware | Measurement needs and reported gain | Survives on gfx90c? | Assessment/status |
|---|---|---|---|---|
| **Tile / “A Faster Tiling Approach for AMD GPUs,” reportedly ASPLOS 2020** | Brief identifies AMD tile pruning as closely related to this exact Tensile tile space. | Exact title/full paper and its experimental details were not verified from an accessible primary source. | Unknown until paper/title are verified. | **UNVERIFIED.** Do not cite numerical claims from it yet. |
| **Analytic cache blocking / roofline**; Williams et al. 2009 [DOI](https://doi.org/10.1145/1498765.1498785) | Bound by arithmetic intensity, peak issue rate and memory bandwidth; tile sizes constrain reuse. | No per-candidate timing to compute first-order ceilings; targeted benchmarking remains necessary because of issue/occupancy/tail effects. | Yes, as a pruning/bounding layer. | Reduces the candidate space, does not select exact Tensile settings. |
| **MAESTRO** (MICRO 2019) [paper](https://arxiv.org/abs/1805.02566) | Dataflow/loop mapping for DNN operators over abstract hardware. | Analytical; paper reports searching 480M designs and finding 2.5M valid designs. | Reuse/resource ideas transfer; hardware-specific model is not a direct Tensile tuner. | Useful for traffic, reuse and capacity models. |
| **PPT-GPU** [OSTI manuscript](https://www.osti.gov/servlets/purl/1504654) | Hybrid performance model of GPU instructions and memory hierarchy. | Paper abstract reports within 10% prediction error on selected workloads and up to 450× speed versus GPGPU-Sim. | Method can be calibrated, but model-building overhead is likely high compared with a modest direct sweep. | **PARTIAL.** |
| **Instruction Roofline Model (IRM)** [arXiv](https://arxiv.org/abs/2110.08221) | AMD instruction intensity and memory transactions, demonstrated on MI60/MI100. | Requires profile counters/microbenchmarks; classifies bottleneck more than it searches knobs. | Yes for diagnostic features, not for tile choice directly. | AMD-relevant and non-MFMA conceptually, not gfx90c-tested. |
| **COSTA / FASTEST / BASS / BEST / Pyramid / MagicLine / SeerNN / PlanGen / GemmLab / Charo analytical GEMM / Fugerite et al. “Accelerating GEMM based on dataflow”** | Named in the brief; intended to cover GEMM tile pruning/prediction, cost models or energy/communication analysis. | I did not confirm enough of these exact titles/authors/results from primary sources within this review to provide citation-grade data. | Unresolved by named source. | **UNVERIFIED bibliographic block.** Search exact titles before using a numerical result or claiming a technique is SOTA. |
| **Ansor**, OSDI 2020 [USENIX paper page](https://www.usenix.org/conference/osdi20/presentation/zheng) | Hierarchical tensor-program search; samples a broad schedule space, then evolutionary search and a learned cost model; CPU/ARM/NVIDIA GPU in the paper. | Measures candidates, with model-assisted exploration; reports up to 1.7× versus baselines on GPU in the abstract. | Search-loop idea can transfer, but its generated programs/search space is broader than fixed-source Tensile knob tuning; no AMD evaluation in the cited paper. | Helps with model-guided discrete search, though implementation is not directly reusable. |
| **TVM AutoTVM** [TVM documentation](https://tvm.apache.org/docs/v0.13.0/how_to/tune_with_autotvm/index.html) | Template-defined schedule knobs and measured schedule configurations. | Hardware measurements dominate; ML cost models reduce repeated trials if calibrated. | Yes as a search-design pattern; kernel generator differs. | A good precedent for constrained schedule templates, not a Tensorile implementation. |
| **PyTorch Inductor `max-autotune` / Triton** [ROCm guide](https://rocm.docs.amd.com/en/docs-6.1.1/how-to/llm-fine-tuning-optimization/optimizing-triton-kernel.html) | Static candidate lists over `BLOCK_M/N/K`, stages, warps, and backend variants, selected per shape. | Measures candidate kernels; expanded/exhaustive tuning can take substantial compile time. | Some idea transfers, but Triton's layouts, stages and MFMA choices do not map 1:1 to Tensile knobs. | Useful pattern for per-shape dispatch and fixed candidate lists. |
| **TunableOp / `rocblas-gemm-tune`** [ROCm guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/optimization/workload-optimization.html) | Existing rocBLAS/hipBLASLt algorithms for each problem. | Direct measurement among pre-existing kernels; AMD says thousands may be tried in TunableOp; gains not guaranteed. | `rocblas-gemm-tune` is usable if runtime supports the device/library. hipBLASLt results are backend/hardware-dependent. | High value for baseline selection; does not synthesize arbitrary new Tensile candidates. |
| **Global search: grid vs random** | Enumerate everything or sample broadly. | Grid cost scales with product of knob cardinalities; random search tests broad categories quickly but offers weak certainty in a noisy space. | Yes. | Random/space-filling initialization is a better first use of budget than full grid for this space. |
| **Evolutionary search / bandit** | Mutate legal candidate tuples or allocate extra repeats/candidates to promising families. | Requires measurement; can reuse the results to concentrate budget. | Yes, if configurations are categorical/dependency-aware and correctness-filtered. | Worth a second stage after an initial structured/random sample. |
| **Bayesian optimisation / TPE / SMAC** | Model latency over mixed categorical and integer knobs; propose configurations with high predicted gain or uncertainty. | Does need measured seed data; can reduce number of evaluations if signal exceeds noise. | Yes, with careful discrete/categorical encoding, constraints, and clock controls. | Best candidate for 100–1000 expensive evaluations; compare against random search on held-out shapes. |
| **MCTS / DRL** | Sequential state/action search or policy learning over configurations. | Usually needs many search episodes, strong reward signal or a warmed policy; evaluation overhead may exceed a single discrete sweep. | Technically possible but evidence for benefit in this exact knob-only space is absent. | Deprioritize for a one-night budget. |

**Measurement-reduction answer:** analytic legality/pruning and cost-model ranking are the clearest methods to reduce measured points. A learned model/BO can also reduce them after an initial set of real timings. Random, grid, and direct benchmarking mainly spend the budget on measurements; evolutionary/bandit algorithms change which configs are measured next, and may or may not save points. For Tensile, legality checking should precede any optimizer because many knob dependencies are deterministic.

Confidence: VERIFIED for Ansor, MAESTRO, TVM and AMD tool descriptions; PARTIAL/UNVERIFIED on named methods explicitly called out above.

---

## Q13. Agentic/LLM/RL autotuning of GPU kernels

| System | Search space / measurement loop | Hardware evidence | Implication for this project |
|---|---|---|---|
| **KernelBench** (ICML 2025) [PMLR full paper](https://proceedings.mlr.press/v267/ouyang25a.html) | LLM-generated PyTorch GPU kernels, correctness checks and optional iterative feedback/profiling over 250 workloads. | The paper reports that frontier reasoning models match the PyTorch baseline in fewer than 20% of cases under its speedup criterion, while profiling feedback helps. Main evaluation is CUDA/NVIDIA-centred. | A useful evaluation harness principle: functional correctness and measurable speedup must both pass. It does not show that an LLM can beat a tuned Tensile candidate generator on AMD Vega. |
| **GEAK: Triton Kernel AI Agent** [arXiv:2507.23194](https://arxiv.org/abs/2507.23194) | Reflexion-style iterative generation/optimization; specializes in efficient Triton kernels. | Abstract says benchmarked on AMD MI250 and MI300X; correctness up to 63%, execution speedup up to 2.59× over stated baselines. | Directly relevant as proof LLM-loop systems can run on AMD, but on CDNA/MI rather than gfx90c and not the fixed Tensile source/knob space. |
| **Harness Engineering for LLM-Driven GPU Kernel Generation** (MLSys 2026 preprint) [arXiv:2607.17979](https://arxiv.org/abs/2607.17979) | Harness enforces compilation, correctness, official-aligned timing and artifact archiving; profiler-backed optimization controller with agents. | Abstract reports five contest workloads on NVIDIA Blackwell B200, with workload-specific improvements versus provided baselines. | Strong harness architecture; accelerator and kernel-generation setup are not portable evidence for a 7-CU Vega. |
| **Kernel Forge** [arXiv:2607.24762](https://arxiv.org/abs/2607.24762) | MCTS over kernel-refinement paths with a GUI/harness, PyTorch model inputs and validation/profiling. | Abstract evaluation on NVIDIA DGX Spark GB10; 50 iterations per kernel for reported wins. | MCTS/harness is an experiment design, not evidence it beats Bayesian/random search in a fixed Tensile knob space. |
| **Dr. Kernel** (ICML 2026) [PMLR paper](https://proceedings.mlr.press/v306/liu26fd.html) | RL over Triton kernel generation with KernelGYM, reward-hacking checks and multi-turn training. | Full abstract confirms the method and evaluation harness; precise transferable hardware outcomes are not established in the excerpt inspected. | Interesting training approach; likely too large for a one-night, one-GPU discrete Tensile search unless already trained/modelled. |
| **TileLang / Tile-AI** [GEMM benchmark page](https://tile-ai.github.io/TileOPs.github.io/benchmarks/gemm/) | Higher-level tile-oriented DSL with shape/block/dataflow dimensions, code generation, and benchmark comparisons. | Current benchmark tables include modern accelerator results rather than gfx90c. | A programming abstraction, not an agent by itself. Its `BLOCK_M/N/K`, stages and layout parameters correspond approximately to macro-tile/DepthU/pipeline concepts, but not exactly to Tensile's TT/WG/vector rules. |
| **ROCm Triton/Inductor autotuning** [ROCm guide](https://rocm.docs.amd.com/en/docs-6.1.1/how-to/llm-fine-tuning-optimization/optimizing-triton-kernel.html) | Predefined candidate lists; `BLOCK_M/N/K`, `num_stages`, `num_warps`, matrix instruction dimension and backend options; measure and keep the best per workload. | Officially documented on AMD MI-series platforms; AMD warns exhaustive mode can greatly increase compile time. | More useful as a template for bounded shape-specialized search than as a drop-in Tensile search engine. `num_stages` and MFMA choices are not direct proxies for `PrefetchGlobalRead`/`DepthU` on FMA-only Vega. |
| **Ansor** (OSDI 2020) [USENIX](https://www.usenix.org/conference/osdi20/presentation/zheng) | Hierarchical search, evolutionary refinement and a learned cost model. | Intel/ARM CPU and NVIDIA GPU in published evaluation, not AMD in the paper abstract. | General search design can apply, but the Tensor program-generation model is overkill if the source and knob set are fixed. |

### Honest state of the art for this workload

These methods can be valuable when the task is **generating or substantially rewriting code**, or when an expert loop provides strong profiler-informed hypotheses. In this project the kernel writer is fixed and there is already a small discrete set of live Tensile knobs. The most plausible baseline to beat is **an analytical legality/roofline model plus an initial stratified candidate sweep followed by a measured Bayesian/evolutionary refinement**, not an unconstrained LLM agent repeatedly rewriting kernel source. An LLM is best used to generate hypotheses and explain counter traces; the measurement harness, resource/legality filter, clock control, and correctness test must remain deterministic and independent.

Confidence: VERIFIED for the cited abstracts/official docs; PARTIAL for cross-system comparisons. No published head-to-head experiment was found showing an agent beats analytical pruning + modest measured sweep on gfx90c.

---

## Q14. Search-space design for this fixed-source Tensile problem

**Answer.** Treat the YAML as a constrained mixed discrete optimization problem, not an independent Cartesian product. Tensile's source documents the relation `MacroTile = workgroup dimension × ThreadTile`, the interpretation of `WorkGroup=[w0,w1,LocalSplitU]`, and the interaction of `StaggerU` with workgroup mapping. It also lists `MaxOccupancy` as a real knob ([Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py)). AMD's current guide warns that tile size, VGPRs, LDS and occupancy are architecture-dependent and must be profiled on the actual target ([AMD GEMM guide](https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/develop/patterns/examples/matrix-multiply-optimization.html)).

### Candidate generator principles

1. **Create legality constraints before sampling.** Reject illegal workgroup totals (<64, >1024, or not divisible by 64); TT dimensions >16; vector widths whose `width × bytes_per_element` exceed 16; `MatrixInstruction` other than `[]` for this target; predicted/actual VGPR >256; LDS >64 KiB; invalid datatype/load combinations; and any Tensile-specific validator rejection. Record the reason and count. Do not report an invalid tuple as “slow.”
2. **Generate high-value shape families rather than independent knobs.** Choose output-tile candidates first; derive a WorkGroup shape consistent with the chosen MT and TT; choose `DepthU` from LDS caps and loop-trip count; choose global load widths that obey element-size/byte limits; then choose prefetch/local-read schedules conditioned on buffer and data layout. Couple `StaggerU` with `WorkGroupMapping`; try `BufferLoad` in a separate branch because StaggerU is silently ignored when buffer load is off according to the Tensile source comments. Treat `LocalSplitU` as a separate algorithmic variant due its impact on workgroup reduction.
3. **Use one-factor and interaction tests strategically.** First sweep MT/TT/DepthU and dtype. Then test likely interactions: TT×DepthU, `BufferLoad`×`StaggerU`×WGM, prefetch×DepthU, and local/global split × output-grid size. Do not multiply all knob options across all other knobs before learning which ones move latency.
4. **Store metadata, not only microseconds.** Candidate result record should include legality, build result, correctness, config tuple, emitted VGPR/SVGPR/LDS/scratch, theoretical waves/SIMD, output grid/tail, measured median/spread, clock/temperature, cache mode, and profiler summary.
5. **Select a search algorithm fit to 10²–10³ samples.** Start with a space-filling/random sample stratified by dtype/shape and include baseline candidates. Fit a mixed categorical/integer model (TPE/SMAC or Gaussian-process variant where encoding makes sense); add promising uncertain candidates, keep a random exploration share, and retest top candidates in interleaved batches. Compare the optimizer against a random-search control to verify it saved measurements. Grid search is appropriate only for the tiny initial subspaces; MCTS/DRL has no demonstrated advantage in this fixed-source space.

### Knobs currently untouched, in order of expected value

| Knob | Why it may matter here | First test |
|---|---|---|
| `LocalSplitU` | Alters work distribution and local reduction; possible use for more independent work when tile grid is small, but can add LDS/extra work. | small matrix / longer K, vary 1/2/4 only when legal. |
| `MaxOccupancy` | Explicit LDS-based CTA cap; may help cache contention but can worsen already low wave count. | narrow diagnostic test on measured winners, baseline 40. |
| `AggressivePerfMode` | Mode 0/1/2 scheduling/occupancy behavior, project-specific meaning as in §H. | controlled test against modes 0 and 2; check LDS and clocks. |
| `BufferLoad` | Changes buffer-vs-flat/global load path; interacts with `StaggerU`. | test true/false in a new stratum; rebuild and validate alignment/tail correctness. |
| `FractionalLoad` | Can change overhang handling/load efficiency on non-divisible shapes. | prioritize only if workload includes edge/non-multiple shapes. |
| `UseSgprForGRO` | Address generation pressure can alter SGPR/VGPR use and instructions. | test by representative load path and inspect ISA/object resources. |
| `NumLoadsCoalescedA/B` | Load distribution and coalescing, shape/transpose dependent. | vary only where load geometry changes. |
| `InnerUnroll` | Alters loop instruction schedule/instruction count and dependency chain. | small discrete set with long K; monitor code size/VGPR. |
| `ScheduleGlobalRead`, `ScheduleLocalWrite`, `LocalRead2A/B`, `StorePriorityOpt` | Scheduling / latency hide / resource utilization interactions. | change after counter evidence; test paired settings, not blind Cartesian expansion. |
| `NumElementsPerBatchStore` | Store grouping and efficiency. | lower priority unless store/epilogue metrics are poor. |

Confidence: PARTIAL. This is a reasoned strategy grounded in Tensile source semantics and constrained-search practice, not a claim that any one untuned knob will improve speed.

---

## Q15. Split-K, Stream-K and correctness/cost of extra reductions

### Stream-K

**VERIFIED at paper-record level.** Osama et al., *Stream-K: Work-centric Parallel Decomposition for Dense Matrix-Matrix Multiplication on the GPU*, PPoPP 2023, partitions aggregate loop work rather than assigning only output tiles, addressing quantization and balancing work across processing elements. The abstract reports up to 14× and 6.7× peak speedups in its tested contexts and more consistent performance across 32,824 geometries ([arXiv:2301.03598](https://arxiv.org/abs/2301.03598)). Those figures are architecture-/baseline-specific; the technique is not a Tensile gfx90c option if the available path requires MFMA.

### `GlobalSplitU` break-even

For a split factor `q`, a useful rough cost expression is

`T_split ≈ T_partial_gemm(M,N,K/q) + T_partial_write(q,M,N) + T_reduce(q,M,N) + T_extra_launch/synchronization`.

Split-K pays when the unsplit output tile grid is too small to cover the CUs and K is long enough for each split to contain useful work. In FP32, the partial buffer size is roughly `q×M×N×4` bytes; FP64 uses 8 bytes/element; complex-single 8 bytes/element; complex-double 16 bytes/element. If reduction reads every partial and writes the final result, a lower-order estimate is `(q+1)MN × sizeof(accumulator)` bytes in the reduction pass, plus synchronization/launch cost. Atomics avoid a separate final-buffer read pattern in some designs but add atomic serialization, order-dependent accumulation, and contention; neither path is free on the APU's shared DDR.

- **Large square GEMM:** output grid is already enormous relative to 7 CUs. Split-K generally adds reduction traffic without solving an underfilled grid; test only if profiling shows a serious K-loop/latency issue.
- **Tiny M/N and very large K:** split-K is a plausible fix. A July 2026 rocBLAS issue reports a consumer RDNA FP64 case with tiny output and K around 10⁴–10⁶ running 6–37× slower than a manual split-K variant; this is a single-issue report and is not gfx90c evidence, but it illustrates the small-output/long-K regime ([rocBLAS issue #9163](https://github.com/ROCm/rocm-libraries/issues/9163)).
- **FP64:** partial sums are expensive in bytes, yet if the baseline exposes only a few output workgroups, the extra traffic may be much smaller than the gained parallelism. Compute a cost estimate and measure.
- **FP16 with FP32 accumulation:** partial sums should remain FP32 if the algorithm promises FP32 accumulation; this increases partial-buffer traffic versus half storage. The `AssertFree0ElementMultiple>=2` restriction reported in the brief looks like a Tensile kernel legality/alignment policy for packed half loads, rather than a mathematical impossibility of split-K. Verify the relevant version's validator and emitted reduction before relaxing it.
- **Complex single/double:** split-K mathematics is possible, but reductions must carry full complex accumulators (8/16 bytes per element) and apply alpha/beta correctly. The project's reported restriction against `GlobalSplitU>1` for complex is a Tensile implementation policy until source proves otherwise. I did not verify the exact validator expression in the live Tensile version, so do not bypass it on assumption.

### Seven CUs and non-power-of-two accelerator counts

The Stream-K method targets work quantization generally, but no paper specifically studying a seven-CU Vega APU or a theory stating that non-power-of-two CU counts require a unique power-of-two tile strategy was found. The arithmetic in Q7 shows that tail-round idle fraction is not invariably 3/7: it depends on `G mod 7`. What the 7-CU count changes is the cost of low output-grid concurrency for small and medium shapes. A small `GlobalSplitU` may help in those cases, but on an integrated GPU the partial-sum and reduction bytes come from shared DDR and must be charged explicitly.

Confidence: VERIFIED for Stream-K's stated method and broad reported claims; PARTIAL for split-K cost reasoning; UNVERIFIED for the precise Tensile type-policy causes unless traced in the pinned commit.

---

## Q16. Reproducibility and validity of autotuning results

**Answer. PARTIAL.** Kernel tuning papers often report speedups with geometric means and selected per-workload numbers; variance reporting is inconsistent across the literature. The sources inspected here do not let me classify the full corpus's artifact-review record, and no standard was found that sets one mandatory repeat count for all GPU kernels. Claims close to measurement noise must therefore be revalidated on the specific machine with a documented clock/cache protocol.

### Relevant validity practices

- **AMD's Max-Achievable FLOPs procedure:** realistic data initialization, stable thermal conditions, cold-cache policy, equal distribution of tile work across CUs, and clock measurement. It gives the approximate 25% warmup / 75% measurement example for a one-second run and uses median clock to avoid outlier skew ([AMD MAF Part 2](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html)).
- **rocBLAS timing protocol:** batch shapes in YAML to avoid repeated library-loading costs; use its documented event timing; separate initialization overhead where needed ([rocBLAS guide](https://rocm.docs.amd.com/projects/rocBLAS/en/develop/how-to/Programmers_Guide.html)).
- **LLM benchmark harnesses:** KernelBench explicitly combines functional correctness and speedup over a baseline, and finds that many generated kernels fail to beat the framework baseline ([ICML 2025 KernelBench](https://proceedings.mlr.press/v267/ouyang25a.html)). Harness Engineering similarly separates validation/timing/artifact archiving from generation ([arXiv:2607.17979](https://arxiv.org/abs/2607.17979)). These are good methodological examples but are not a GEMM-autotuning replication study.
- **Portability/overfitting warning:** Hochgraf and Pai find that single-kernel auto-tuning can overfit workload/device conditions and use multi-versioning to preserve per-environment performance ([arXiv:2507.15277](https://arxiv.org/abs/2507.15277)).
- **Artifact evaluation:** I did not assemble a verifiable conference-by-conference artifact badge table for the 2016–2026 proceedings. That is an explicit review gap. Do not treat missing artifact availability as proof that a headline number failed review; likewise, do not treat lack of an artifact badge as proof a result is wrong.

### Recommended benchmark record for this corpus/project

For every configuration preserve: source revision, full YAML tuple, device and driver/ROCm/LLVM versions, kernel symbol, launch dimensions, build status, correctness result, object metadata (VGPR/SGPR/LDS/scratch), median latency and a spread estimate across repeated batches, whether caches were cold or warm, input initialization scheme, observed clock/temperature, benchmark run order, and candidate selection process. Interleave known baseline settings through the full sweep, so thermal drift does not correlate with one candidate family. Report per-shape results as well as aggregates, and separate compile/startup time from steady-state kernel timing.

Confidence: PARTIAL. Primary measurement guidance verified; broad artifact/variance census not performed.

---

## Venue-sweep audit table

**Important audit notice:** the prescribed full ToC sweep for every named venue, year 2016–2026, was not completed. Targeted searches and selected paper/source inspection were conducted. To avoid false precision, the candidate-screened/kept/AMD-relevant counts below are **not represented as counts**. “Not counted” means a reproducible year-by-year screening log was not made; “skipped” means the venue was not actually swept. This does not satisfy the full protocol, and the census/fractional claim remains open.

| Venue / track | Years covered | Candidates screened | Kept | AMD/GCN-relevant | Best found item / reason for status |
|---|---|---:|---:|---:|---|
| ASPLOS | Targeted search only, 2016–2026 not ToC-swept | Not counted | Not counted | Not counted | Exact “Tile” citation from brief not verified. |
| MICRO | Targeted search only | Not counted | Not counted | Not counted | MAESTRO appears in MICRO 2019, [arXiv](https://arxiv.org/abs/1805.02566); not GCN-specific. |
| HPCA | Skipped as a complete ToC sweep | Not counted | Not counted | Not counted | Time/scope; no claim of no relevant papers. |
| ISCA | Targeted search only | Not counted | Not counted | Not counted | No full proceedings census; Fugerite citation not verified. |
| CARR | Skipped | Not counted | Not counted | Not counted | Venue identity/proceedings not sufficiently resolved in this pass. |
| ICCAD | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| DATE | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| FCCM | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | FPGA accelerator literature is adjacent but not swept. |
| ISPASS | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| PPoPP | Targeted search | Not counted | Not counted | Not counted | Stream-K 2023, [arXiv](https://arxiv.org/abs/2301.03598), NVIDIA/CUDA-centered evidence. |
| CGO | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| ICS | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| HPDC | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| IPDPS | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| PACT | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| ICPE | Targeted search only | Not counted | Not counted | Not counted | Measurement methodology is relevant but proceedings were not enumerated. |
| ICPP | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| SC | Targeted search only | Not counted | Not counted | Not counted | Named PERKS result not verified; proceedings not fully swept. |
| EuroSys | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| OSDI | Targeted search | Not counted | Not counted | Not counted | Ansor 2020, [USENIX](https://www.usenix.org/conference/osdi20/presentation/zheng); not AMD-evaluated in the cited abstract. |
| SOSP | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| ATC | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| FAST | Skipped as complete ToC sweep | Not counted | Not counted | Not counted | Named FASTEST citation not verified. |
| SoCC | Skipped | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| HotOS | Skipped | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| VEE | Skipped | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| MLSys | Targeted 2025–2026 work search | Not counted | Not counted | Not counted | GEAK (AMD MI250/MI300X) [arXiv](https://arxiv.org/abs/2507.23194); LLM harness preprint [arXiv](https://arxiv.org/abs/2607.17979), NVIDIA B200. |
| NeurIPS systems/efficiency tracks | Skipped as complete track sweep | Not counted | Not counted | Not counted | No claim of no relevant papers. |
| ICML systems/efficiency tracks | Targeted 2025–2026 search | Not counted | Not counted | Not counted | KernelBench 2025 [PMLR](https://proceedings.mlr.press/v267/ouyang25a.html); Dr. Kernel 2026 [PMLR](https://proceedings.mlr.press/v306/liu26fd.html). |
| ACM TOPLAS | Skipped | Not counted | Not counted | Not counted | Journal search not fully enumerated. |
| ACM TOSEM | Skipped | Not counted | Not counted | Not counted | Journal search not fully enumerated. |
| IEEE TCAD | Skipped | Not counted | Not counted | Not counted | Journal search not fully enumerated. |
| IEEE TPDS | Targeted search only | Not counted | Not counted | Not counted | Older multi-vendor OpenCL GEMM portability study [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0167819111001335), outside the decade range. |
| JPDC | Skipped | Not counted | Not counted | Not counted | Journal search not fully enumerated. |
| Parallel Computing | Skipped | Not counted | Not counted | Not counted | Journal search not fully enumerated. |
| FGCS | Skipped | Not counted | Not counted | Not counted | Journal search not fully enumerated. |
| ACM TACO | Targeted search only | Not counted | Not counted | Not counted | Recent tile-size analytical model in search results [DOI](https://doi.org/10.1145/3806056), but not a full journal sweep. |
| Cross-venue artifact/reproducibility tracks | Not swept venue-by-venue | Not counted | Not counted | Not counted | Harness Engineering and KernelBench are useful practices, but no cross-venue badge census was compiled. |

This table is an audit of what was and was not done, not a negative result that AMD/GCN work does not exist. The requested counts/fraction cannot responsibly be supplied until a year-by-year ToC inventory is actually performed.

---

## Techniques we could adopt: action table

| Technique | Venue + year + URL | Search space | Needs measurement? | Reported gain | Evaluated on AMD? | Transferable to wave64/no-MFMA/7-CU? | Effort here |
|---|---|---|---|---|---|---|---|
| Roofline/AI legality filter | Williams et al., 2009, [DOI](https://doi.org/10.1145/1498765.1498785) | MT/NT sizes vs compute/BW ceilings | No for first-order filter; yes for calibration | Lower-bound/model, not a tuning gain | No device-specific result in cited source | High as screening, low as exact selector | Low |
| MAESTRO reuse/capacity model | MICRO 2019, [arXiv](https://arxiv.org/abs/1805.02566) | Dataflow/reuse/abstract resource constraints | Analytical model; calibrate hardware | Searches 480M abstract designs in reported experiment | Not verified on AMD GPU | Medium for reuse/capacity logic, low for emitted ISA predictions | Medium/high to adapt |
| PPT-GPU modeling | IEEE CAL manuscript, [OSTI](https://www.osti.gov/servlets/purl/1504654) | Memory hierarchy + instruction timing | Yes, model calibration plus validation | Reported within 10% on sampled workloads | Not verified for Vega; general GPU model | Medium conceptually | High |
| AMD Instruction Roofline Model | 2021, [arXiv](https://arxiv.org/abs/2110.08221) | AMD instruction intensity and memory transactions | Yes, profiler counters and microbenchmarks | Bottleneck attribution, no universal tile gain | MI60/MI100 | High for diagnosis, not config generation | Medium |
| Measured constrained sweep | Current project method | Legal YAML combinations over selected active knobs | Yes | Unknown until measured; direct objective | Directly on target | Highest | Low/medium |
| Bayesian/TPE/SMAC refinement | General autotuning technique; TVM/Ansor are precedents | Mixed integer/categorical Tensile knobs | Yes, initial sample and active measurements | Search savings depend on signal/noise | Framework-dependent | High | Medium |
| Evolutionary mutations | Ansor, OSDI 2020, [USENIX](https://www.usenix.org/conference/osdi20/presentation/zheng) | Neighboring schedules/configurations | Yes | Ansor reports up to 1.7× over its GPU baselines | Not in cited Ansor abstract | High as search control | Medium |
| Per-shape library selection | rocBLAS `rocblas-gemm-tune`, [docs](https://rocm.docs.amd.com/projects/rocBLAS/en/develop/how-to/Programmers_Guide.html) | Existing solution indices and problem sizes | Yes, among installed kernels | No fixed gain guarantee | AMD library | High when library path works; cannot build new candidates | Low |
| TunableOp/hipBLASLt tuning | ROCm AI Ecosystem docs, [link](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/optimization/workload-optimization.html) | Existing rocBLAS/hipBLASLt GEMM algorithms | Yes | Up to thousands of algorithms tried; improvements not guaranteed | AMD Instinct ecosystem | Medium; verify gfx90c backend availability and avoid MFMA assumptions | Low if supported |
| Split-K / `GlobalSplitU` | Stream-K PPoPP 2023 as design precedent, [arXiv](https://arxiv.org/abs/2301.03598) | K-split factor and reduction implementation | Yes | Stream-K reports up to 14×/6.7× in its own setups; not GSU/gfx90c results | Stream-K is not gfx90c evidence | High as a design principle; GSU path constrained by Tensile policy | Medium/high, correctness-sensitive |
| LLM agent with profiler feedback | GEAK 2025 [arXiv](https://arxiv.org/abs/2507.23194); KernelBench ICML 2025 [PMLR](https://proceedings.mlr.press/v267/ouyang25a.html) | Usually code-generation/search, plus iterative measurement | Yes, heavily | GEAK abstract up to 2.59× on AMD MI GPUs; KernelBench says frontier models beat baseline in under 20% of cases by its threshold | GEAK yes on MI250/MI300X; KernelBench mainly NVIDIA | Medium as hypothesis/code review aid, low as direct fixed-knob optimizer | Medium/high; likely not first choice |
| RL/MCTS kernel search | Dr. Kernel ICML 2026 [PMLR](https://proceedings.mlr.press/v306/liu26fd.html); Kernel Forge 2026 [arXiv](https://arxiv.org/abs/2607.24762) | Multi-turn code-generation or refinement policies | Yes, many episode timings | System-specific; not a transferable Tensile speedup value | Current cited evidence NVIDIA-centric or unspecified in excerpt | Low/medium; fixed-source space much smaller than code-generation space | High |
| Candidate normalization + legality pruning | Project-specific recommendation; Tensile schema [source](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py) | Constraints, derived parameters, duplicate configurations | No GPU for legality; GPU for ranking | Reduces wasted compile/timing slots; gain to be measured | Directly applicable | Very high | Low |
| Benchmark harness with repeats and thermal telemetry | AMD MAF guide [link](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html) | Timing and environment, not search space | Yes | Not a kernel speedup; increases validity | AMD | Very high | Low |

---

## We could not verify / do not cite

1. A complete year-by-year proceedings ToC sweep across every venue and years 2016–2026, along with a defensible screened/kept/AMD-relevant paper fraction. The table above reports this gap explicitly.
2. The exact full-text details/results of the brief's “Tile: A Faster Tiling Approach for AMD GPUs” paper reportedly at ASPLOS 2020. It must be bibliographically resolved before using it as a primary reference.
3. The full shipped YAML distribution of `MacroTile`, `ThreadTile`, `DepthU`, vector widths, prefetch, `StaggerU`, WGM, APM and occupancy across all gfx900/gfx906 problem files. Direct source examples were inspected, but the largest FP32/FP64 files could not be fully parsed in the available source browser.
4. The precise quoted `MI250-optimal on A100 = ~7% of A100-optimal` and “at least 20%, up to an order of magnitude” numbers from arXiv:2505.03780; the accessible abstract did not verify the exact statement.
5. The precise `142k tuples, 5 GPUs, dynamic range 1.8×–13.2×` numerical description of arXiv:2507.15277; the abstract verifies the general portability-tuning result but not each dataset count/value.
6. A published fraction of foreign kernel configs that fail legality rather than compile slowly, a general GPU-hours figure for full Tensile retuning, and a standard published metric for tile-shape transferability across GPUs.
7. A peer-reviewed Vega/gfx900/gfx906 measurement settling exact LDS bandwidth per clock and directly measuring the bank-conflict penalty inside Tensile GEMM. The source found is AMD documentation and later CK-Tile documentation.
8. The exact Tensile document statement that `LdsPadA/B` is deprecated and “probably broken”, and any measured Vega benefit from nonzero padding.
9. The specified PERKS SC'23 result, the ISC 2026 CUTLASS FP8 1.00 waves/SM / 14% achieved-occupancy datapoint, and any non-MFMA VGPR/occupancy study that directly settles a target waves/SIMD count for a seven-CU gfx90c part.
10. An official or source-backed `mblas-bench` pipeline description matching the brief, including heuristic solution count, expected GPU-hour cost and yield.
11. The exact gfx1151 `auto` vs `profile_peak` +37.8% result as a primary-source, transferable measurement for gfx90c.
12. A verified per-type Tensile source explanation for refusal of `GlobalSplitU>1` for complex and half-assembly cases, including the exact `AssertFree0ElementMultiple>=2` policy in the pinned project commit.
13. A cross-venue artifact-evaluation/reproducibility badge census and a complete variance/error-bar matrix for the autotuning papers named in Q12/Q13.
14. Direct benchmark evidence on Ryzen 4000/5000 APUs giving reproducible GFLOP/s and achieved bandwidth for the requested GEMM families. The corpus-measured rates in §C remain the local ground truth.

---

## What this changes: concrete Tensile knob experiments

1. **`ThreadTile`:** measure `[4,4]`, `[6,6]`, and `[8,8]` where legal; do not assume `[8,8]` is best for complex or FP64 because accumulator VGPR cost grows rapidly.
2. **`WorkGroup`:** include multiple 64-thread-multiple factorizations that produce MT64/128/asymmetric 128×256 or related shapes; for small output grids avoid large tiles that leave most of seven CUs unused.
3. **`DepthU`:** couple it to `MacroTile` and dtype using `LDS ≈ (MT_M+MT_N)×DepthU×bytes_per_element` and staging multiplicity; smaller `DepthU` may restore another resident group.
4. **`VectorWidth` and `GlobalLoadVectorWidthA/B`:** keep the §H byte-width legality guard; search narrower widths for complex/FP64 if the 16-byte cap, register pressure or tail handling makes wide loads unhelpful.
5. **`PrefetchGlobalRead`:** test 0/1/2 (live schema) as an interaction with DepthU, global buffer path and matrix size. The gfx900 FP32 candidate shows that global prefetch off can coexist with a 128×16 tile, so “always prefetch” is not a law.
6. **`PrefetchLocalRead`:** tune separately from global prefetch; confirm that any deeper prefetch's increased register/storage footprint does not erase latency savings.
7. **`BufferLoad`:** test true/false selectively, especially because `StaggerU` depends on it in Tensile's source comments. Do not attribute a StaggerU experiment when the buffer load path silently disables it.
8. **`StaggerU` and `WorkGroupMapping`:** search as a pair on large matrices where the global-memory channel/cache access sequence is likely relevant; do not treat WGM as a substitute for increasing tile reuse.
9. **`LocalSplitU`:** test on small-M/N, long-K cases to create additional local work distribution only when the accumulation/reduction cost is acceptable. Keep it at baseline for large output grids unless profile evidence says otherwise.
10. **`GlobalSplitU`:** test only for underfilled output grids and long K; include partial-buffer bytes, reduction launch and dtype accumulator width in the cost model; do not assume it is legal for complex merely because the maths is definable.
11. **`MaxOccupancy`:** retain 40 as the control; test a few lower settings only after diagnosing cache-thrashing or excess concurrent CTAs. A deliberate cap is not a remedy for a kernel already resident at 8–12 waves/CU without proof.
12. **`AggressivePerfMode`:** measure modes 0/1/2 on a small, representative set; mode 2's occupancy restriction may help or hurt depending on true bottleneck and is not justified solely by LDS bandwidth arithmetic.
13. **`LdsPadA/B`:** leave at 0 unless instruction-specific lane-to-bank analysis or counters demonstrate conflicts. The normal non-MI kernel is not LDS-bandwidth-bound under §H.3.
14. **`InnerUnroll`, `LocalRead2A/B`, `ScheduleGlobalRead`, `ScheduleLocalWrite`, `UseSgprForGRO`, `NumLoadsCoalescedA/B`, `StorePriorityOpt`, `FractionalLoad`:** use a second-stage, evidence-driven ablation rather than multiplying all values into the first sweep; retain object metadata and correctness as part of candidate ranking.
15. **`MacroTileShapeMin/Max`:** include legal medium/large regions rather than clamp the search to MT128 square. The ridge analysis supports testing larger/asymmetric tiles for FP32/packed-FP16 and ~96 square complex-single; resource/grid checks determine whether the candidate is worth measuring.

**Bottom line:** on gfx90c, arithmetic intensity is important, but the tuning objective is the intersection of (i) tile reuse, (ii) seven-CU output-grid parallelism, (iii) wave64 FMA issue/latency hiding, (iv) VGPR/LDS residency and (v) actual shared-DDR/L2 traffic. The literature gives a framework and useful hardware-specific mechanisms; it does not provide a defensible universal “best tile” or a universal waves/SIMD target for this exact part. Measure the constrained candidate set under a stable protocol.
