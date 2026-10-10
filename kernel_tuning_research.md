# Kernel tuning research — gfx90c (GCN5 / Vega-class APU)

## How this relates to the project

- This doc is **research only** — hardware model, literature, and Tensile source mechanics. It contains no benchmark numbers of its own; all measured values live in `potential_configs.md` and `knowledge_base.md` and are referenced, never copied.
- Companions: `gfx90c_tuning_guide.md` defines the campaign vocabulary (**M1** scope/axes, **M2** gates, **M3** mechanisms, **M4** measurement rules) and the knob surface; `potential_configs.md` §6 (Groups A/B/C), §7 (steal), §8 (other routes incl. §8.2 split-complex) and §10 (next-run queue) define the ranked experiment groups and the resolution ladder (occupancy/tile levers → split-complex). Section 7 below maps each research finding onto that existing plan; it does not add new experiment cells.
- `gfx90c_theoretical_limits.md` remains the authority for performance ceilings; this doc only explains *why* those ceilings exist.
- Cite conventions: repo files as `path.py:line` against the local Tensile checkout at `TENSILE_ROOT` (per `.env`); web sources inline as `(site, URL)`; full list in **Sources**. Claims I could not fully verify are marked **check**.

---

## 1. Hardware model: GCN5 / GFX9 / gfx90c

- **gfx90c is GCN5 (Vega) with the gfx900 ISA** — LLVM groups `gfx90c` with `gfx900/902/906/909` (LLVM AMDGPUUsage, https://llvm.org/docs/AMDGPUUsage.html); the ongoing ROCm port states gfx900/gfx90c share the same ISA (FOSS United "Season of Commits 2026", https://fossunited.org). Backward compat comes from **code object v2** targeting (reviews.llvm.org/D100126, https://reviews.llvm.org/D100126).
- **Our SKUs**: 8 CU @ up to 2000 MHz (AMD Ryzen 7 5800H official page, https://www.amd.com/en/products/processors/laptop/ryzen/7000-series/amd-ryzen-7-5800h.html); 7 CU SKUs exist (e.g. 5600U @ 1800 MHz, WCCFTech Cezanne table, https://wccftech.com). **check** — exact CU count of the tuning machine should be confirmed from `rocminfo` when benchmarks are next allowed.
- **CU internals** (ORNL AMD GPU Basics, https://www.olcf.ornl.gov/wp-content/uploads/2019/10/ORNL_Application_Readiness_Workshop-AMD_GPU_Basics.pdf; chipsandcheese "GCN", https://chipsandcheese.com/p/gcn-amds-gpu-architecture-modernization):
  - **4 × 16-wide SIMDs**, each with its own **64 KiB VGPR file** (16384 32-bit regs/SIMD, 65536/CU) and a **10-entry scheduler partition** → hardware cap **10 waves/SIMD, 40 waves/CU**.
  - **64 KiB LDS per CU** (one workgroup-facing scratchpad), **32 banks × 4 B = 128 B/cycle**, with hardware conflict-resolution logic that re-schedules same-bank accesses into multiple cycles (rocprofiler-compute pipeline descriptions, https://rocm.docs.amd.com/projects/rocprofiler-compute/en/docs-6.3.0/conceptual/pipeline-descriptions.html).
  - **wave64 only**: LLVM reserves `ENABLE_WAVEFRONT_SIZE32` as 0 on GFX6–9 (LLVM AMDGPUUsage); wave32 is an RDNA invention (Wikipedia RDNA, https://en.wikipedia.org/wiki/RDNA_(microarchitecture)). **Consequence: every kernel is 64-lane; no wave32 trick exists on this APU.**
- **Issue rate**: GCN issues **1 instruction per wave per 4 cycles** (Wikipedia RDNA; Wronski "GCN – two ways of latency hiding and wave occupancy", https://bartwronski.com/2014/03/27/gcn-two-ways-of-latency-hiding-and-wave-occupancy) → a SIMD keeps its issue port busy only with **≥4 resident waves** (feeds §3).
- **Memory**: the APU trades the ~400 GB/s HBM of dGPU Vega for **DDR4 shared with the CPU, ~30–40 GB/s effective** (FOSS United port article) — one to two orders of magnitude below dGPU; `gfx90c_theoretical_limits.md` §roofs is the authority for the resulting ceilings. **FP64 rate 1:16** (TechPowerUp Vega 64 spec, https://www.techpowerup.com/gpu-specs/radeon-vega-64.c3039) — **check**: no first-party doc states the gfx90c iGPU ratio explicitly; Cezanne FP64 is widely reported as 1/16 **check**.
- **Implication for the campaign**: on a bandwidth-poor, wave64, 10-wave-partition machine, the levers that matter are (a) **register-residency quantization** (§3), (b) **LDS conflict/padding** (§2), (c) **access-pattern knobs** (`StaggerU`, `WorkGroupMapping`, §4) — not wave-size or tensor-core tricks.

## 2. LDS bank conflicts and padding — worked example (4 / 8 / 16-B elements)

### 2.1 Model

- **Bank index** = `(byte_address / 4) mod 32`; addresses **128 B apart alias to the same bank** (nod-ai amdgpu_kernel_optimization_guide, https://github.com/nod-ai/shark-ai/blob/main/docs/amdgpu_kernel_optimization_guide.md; CK "Understanding AMD GPU LDS and Bank Conflicts", https://rocm.docs.amd.com/projects/composable_kernel/en/latest/conceptual/ck_tile/hardware/lds_bank_conflicts.html).
- Hardware splits a wave64 LDS instruction into **phases**, phase width depending on instruction width: **32 lanes for b32**, **8 lanes for b128** (CK LDS bank-conflicts doc). A conflict serializes lanes of a phase that hit the same bank into extra cycles.
- **Conflict factor** used below: `max dwords landing on one bank` ÷ `mean dwords per bank over the phase` (1× = conflict-free).
- Assumed access pattern: a **column read of a row-major LDS tile** with `R = 64` elements per row and row stride `(R + p)·e` bytes for pad `p` (elements of the type). **check** — which side (read vs write, TLU vs transpose) dominates in our kernels must be confirmed against the emitted `ds_read` pattern; the *relative* pad ranking below is what the experiment tests.

### 2.2 Worked numbers

Row stride in dwords, and per-lane stride step: `e=4: (64+p)`, `e=8: 2·(64+p)`, `e=16: 4·(64+p)` dwords; all pad-0 strides are multiples of 128 B → **every row starts on the same bank**.

| element size `e` | pad 0 | pad 1 | pad 2 | pad 4 |
|---|---|---|---|---|
| **4 B** (f32)  | **32×** | 1× | 1× | 4× |
| **8 B** (cfloat / f64) | **16×** | 1× | 2× | 4× |
| **16 B** (complex, split halves) | **8×** | 1× | 2× | 4× |

- Arithmetic for the table (all factors identical under the 32-lane and the instruction-width phase models, because the pattern is uniform): `e=4,p=0` → 32 lanes all hit one bank = 32×; `p=1` → stride 65 dwords, step 1 mod 32 → banks 0…31 distinct = 1×; `p=4` → step 4 → each bank hit by 4 lanes = 4×. `e=8,p=0` → each of 2 banks gets 32 dwords vs mean 2 = 16×; `e=16,p=0` → 4 banks × 32 vs mean 4 = 8×.
- **Predictions for Group B (`LdsPad` sweep, potential_configs.md §13.4–§13.6):**
  - **pad 1 is conflict-free for all three element sizes** and should win where the column-read pattern dominates;
  - **pads are non-monotonic** — pad 4 is *worse* than pad 1 everywhere and worse than pad 2 for 4 B — so "more padding" is not a safe prior; a `LdsPad ∈ {0,1,2,4}` grid (not a binary toggle) is required;
  - LDS cost of pad 1 at `R=64` is `(64+1)/64 ≈ 1.6 %` — negligible against `LDS_BUDGET = 16384` B (`scheduler.py`, `ldspad_feasible` gate `scheduler.py:1261`), but `PrefetchGlobalRead=1` doubles the footprint (§4).

### 2.3 What Tensile actually does

- `getLdsNumElements` adds `LdsPad` **per row** when `padInterval = MacroTile` (`Tensile/SolutionStructs.py:2759-2769`, esp. `:2767-2769`).
- **Auto-padding** (`ldsPaddingAuto`, `Tensile/SolutionStructs.py:2788`, hardcoded `numBank = 32` at `:2802`): `LdsPad = -1` resolves to **0 when `TLU` and not `UnrollMajorLDS`, else `VectorWidth`** (`:2812-2817`) — i.e. Tensile only pads when a transpose read is required, mirroring its own comment *"Padding only helps when transpose is required"* (`Tensile/Common.py:1360`).
- Tensile's historical caution: *"in 2016 this didn't seem to help performance, profilers were showing that channel conflicts weren't really hurting"* (`Tensile/Common.py:1358`) — **our context differs**: 2016-era dGPU bandwidth hid LDS stalls behind memory latency; on a DDR-bound APU with 16-B complex elements, VALU-side serialization is more exposed. Hypothesis to test, not a fact.
- **gfx90c constraint**: our kernels are **VALU (non-MI) mode** — `LdsBlockSizePerPad` (periodic/XOR-style padding) is **rejected outright** (`Tensile/SolutionStructs.py:2891-2892` "didn't support LdsBlockSizePerPad in VALU mode yet"; `UnrollMajorLDS` also rejected `:2889-2890`). **Only plain per-row `LdsPadA/B` is available** → the pad grid above is the whole design space.
- The 16 B load cap: `GlobalLoadVectorWidth × numBytes > 16` is rejected (`Tensile/SolutionStructs.py:3461`, also `VWA/VWB` `:3488`, `:3491`) → **16-B loads cap GLVW at 1**, which is why `VectorWidth` bounds are `S4/H8/D2/C2/Z1` (see `gfx90c_theoretical_limits.md` and `gfx90c_tuning_guide.md` knob table — not repeated here).

## 3. Occupancy and wave quantization

### 3.1 The occupancy formula for gfx90c

- Per SIMD: **16384 VGPRs**, wave64 needs `64 × V` (V = regs/thread, allocated in **blocks of 4**, max 256 — LLVM AMDGPUUsage), arch cap **10 waves/SIMD**:

  ```
  waves_per_SIMD = min( 10, floor( 256 / V_rounded ) )       occupancy = 4 × waves_per_SIMD
  ```

  (VGPR file 64 KiB/SIMD: ORNL PDF and GPUOpen "Occupancy explained", https://gpuopen.com/learn/occupancy-explained.)
- **Worked quantization steps**: `V=64 → 4`; `V=68 → 3`; `V=128 → 2`; `V≥256 → 1`. **Four extra registers (`V` 64→68) drop residency 4→3 waves/SIMD — a −25 % cliff with no change in algorithm.** This is *register wave quantization*, the AMD analogue of block/tile quantization (NVIDIA matmul guide, https://docs.nvidia.com/deeplearning/performance/dl-performance-matrix-multiplication/index.html; WaveTune, https://arxiv.org/abs/2604.10187).
- Real kernels from the campaign's measured tables (M3, `knowledge_base.md` / `potential_configs.md` — numbers referenced, not copied): CC `TT4×4` at **79 VGPR → 3 waves/SIMD**, Z `TT4×4` at **167 VGPR → 1 wave/SIMD**. The 1-wave case issues 1 VALU instruction per 4 cycles instead of back-to-back → **≤25 % of peak VALU issue**, independent of cache behavior.

### 3.2 Why ≥4 waves, and when more doesn't help

- GCN's 1-inst/4-cycles-per-wave issue (§1) means **4 waves/SIMD is the issue-saturation point**; below it, the SIMD idles by construction (Wronski 2014, https://bartwronski.com/2014/03/27/gcn-two-ways-of-latency-hiding-and-wave-occupancy).
- Above it, extra occupancy buys **latency hiding**, not ALU throughput: *"ALU-bound workloads don't benefit from higher occupancy"* — GPUOpen "Occupancy explained" (https://gpuopen.com/learn/occupancy-explained) and "Optimizing GPU occupancy … large thread groups" (https://gpuopen.com/learn/optimizing-gpu-occupancy-resource-usage-large-thread-groups).
- **Practical rule for M3**: target `V ≤ 64` (→4 waves) for compute-bound CC/DD/ZZ cells before chasing larger tiles; a macro-tile win that pushes `V` across a 4→3 or 3→2 boundary can be a net loss — this is exactly what the M2 gates are for.

### 3.3 LDS as the second limiter (and the scheduler's model of it)

- Workgroups per CU are also capped by **LDS**: `scheduler.py` uses `LDS_BUDGET = 16384` B/CU and gates candidates through `occupancy_feasible` (`scheduler.py:1186`) and `ldspad_feasible` (`scheduler.py:1261`).
- **Suspected model bug — check**: `BYTES_PER_ELEMENT` (`scheduler.py:1039`) lists `"Z": 8`, but Z (split complex, 2×f64... actually 2×f32×2 = 16 B in this project's convention) is 16 B — contrast `FAMILY_BYTES_PER_ELEMENT` (`scheduler.py:31-36`) which has `ZZ: 16`. If confirmed, `_lds_base_bytes` (`scheduler.py:1106`, consumed at `:1181`/`:1248`) **under-counts ZZ LDS footprint 2×**, making both gates ~2× optimistic for ZZ. Tensile itself computes with `bpe = 16`. Flagged for the owners; not fixed here (docs-only constraint).
- Deliberate occupancy *limiting* exists too: the `MaxOccupancy` knob *"allocates extra lds to artificially limit occupancy"* when cache thrashing hurts (`Tensile/Common.py:983`) — a reminder that more residency is a hypothesis, not a goal.

## 4. Tensile knob mechanics

- Canonical knob reference: `docs/src/conceptual/kernel-parameters.rst` in the Tensile tree (abbreviations `LPA/LPB/GSU/GSUA/PGR/PLR/SU/SUS/WGM/GRVW/NLCA/AF0EM/SCIU/MO/MVN/WS`). Defaults verified in `Tensile/Common.py:1542-1629`: `PrefetchGlobalRead=1` (`:1542`), `PrefetchLocalRead=1` (`:1543`), `StaggerU=32` (`:1597`), `StaggerUStride=256` (`:1598`), `WorkGroupMapping=8` (`:1626`), `MACInstruction=FMA` (`:1628`), `WavefrontSize=64` (`:1629`).
- **`PrefetchGlobalRead`**: `PGR=1` **requires 2× LDS space and VGPRs for buffering** (`Tensile/Common.py:511-513`); `PGR=2` prefetches during the VGPR→LDS copy (`:515-518`). `1LDSBuffer` forces a single LDS buffer even with PGR (`:551-556`) — trades double-buffering for LDS budget. → PGR=0 is simultaneously a **VGPR and LDS** relief valve (feeds §3.3, Group C).
- **`StaggerU` / `StaggerUStride`**: `StaggerU` is the max number of "clicks" of `StaggerUStride` bytes by which workgroups stagger their summation start (`Tensile/Common.py:906-917`); rationale: V20 has **16 channels × 256 B** (`:915`), `StaggerUStride=256` lands each click in a fresh channel (`:928-930`); `StaggerUStride` is internally rounded to a multiple of `DepthU·BPE` (`:933`); **`StaggerU` silently requires `BufferLoad=1`** (`:924`); and *"StaggerU and WorkGroupMapping interact and should be tuned together"* (`:921-922`). **check**: 16-channel count is a dGPU-era comment (gfx803/900/906) — iGPU channel/L2 topology differs.
- **`WorkGroupMapping`**: remaps `wg1` so tiles hit L2 favorably; semantics `wgSerial = wg0 + (wg1 % WorkGroupMapping) * nwg0` (`Tensile/Common.py:980`), *"box width determined by the number of compute units"* (`:975-981`) — **check**: exact formula for 7-CU parts. `WGM=8` is the default (`:1626`) and a proven real lever on this APU (see potential_configs.md §13.x — WGM8 in winners, referenced not copied).
- **`GlobalSplitU`**: `GSU=1` forces `GlobalSplitUAlgorithm=SingleBuffer` (`Tensile/SolutionStructs.py:3530-3532`). For **`GSU>1` the supported-type gate** (`:3543-3553`) accepts single/8-bit/double+BufferStore/int32/asm-half **or `_GlobalAccumulation` set or MFMA** — **complex (`X`) passes only via `_GlobalAccumulation`**, which is set exactly by `GlobalSplitUAlgorithm=MultipleBuffer` (`:2970-2971`). MultipleBuffer semantics: each GSU group writes its own workspace buffer, a post-GSU kernel does the accumulation (`Tensile/Common.py:570-591`) → **2 kernel launches + workspace allocation** per GEMM. The atomic path is excluded for our setup (`:3064`).
- **`StreamK` is unavailable on gfx90c**: rejected unless `MIWaveGroup0×MIWaveGroup1 == 4` (`Tensile/SolutionStructs.py:2976`) — MFMA-only → **all StreamK/StreamK++ literature is background, not an experiment** (§6).
- **MAC plumbing (the complex-GEMM cost)**: `Components/MAC_F32C.py` emits **four `_v_mac_f32` instructions per complex multiply-accumulate** — the real/imag cross terms at `MAC_F32C.py:55` (rr), `:73` (ar), `:90` (ra), `:107` (ai, i.e. the 4-pass loop). The `_v_mac_f32` macro resolves to `v_fmac`/`v_fma`/`v_mac` per `MACInstruction` (`Tensile/KernelWriterAssembly.py:2369-2387`); default is `FMA` (`Common.py:1628`). Note: the campaign doc's older citation (`KernelWriterAssembly.py:14975-14978`) points at the beta/finalSum epilogue, not the MAC loop — **cite `MAC_F32C.py` for the 4× claim**.
- **`NumLoadsCoalescedA/B` (`NLCA/NLCB`)**: coalesces LDS loads (`tuning_docs/tensile_tuning.tex:1430`, `kernel-parameters.rst:449`); `NLCA=3` fuses LDS-load instructions in our kernel population (see potential_configs.md §13.5, referenced for the counts).

## 5. Complex GEMM strategies (including split-complex)

- **Where the 4× comes from**: complex MAC = 4 real FMAs + 2 adds; Tensile's VALU implementation is literally **4 `_v_mac_f32` passes per (a,b,iui)** (`Components/MAC_F32C.py:55/73/90/107`). At the same wave residency this makes CC/ZZ ~4× more VALU-hungry than SS/DD — the mechanism behind the derived CC/ZZ ceilings (see `gfx90c_theoretical_limits.md`, referenced not copied).
- **Data layouts**:
  - **Interleaved complex** (zr,zi adjacent) — what Tensile/rocBLAS problem types use (e.g. `Cijk_Ailk_Bjlk_CB`, rocBLAS programming guide, https://rocm.docs.amd.com/projects/rocblas/).
  - **Split-complex** (SoA real and imaginary planes) — halves contiguous runs, doubles stride; compared head-to-head with interleaved in "Flexible Performant GEMM Kernels on GPUs" (IEEE Computer Society, https://ieeexplore.ieee.org/document/9655458). **check**: whether this Tensile checkout has a native split-complex problem type (Group D escalation in potential_configs.md §13.5–§13.6 assumes decomposition into 4 real-domain GEMMs at the *call* level if not).
- **Algebraic reductions** (do the same FLOPs with fewer multiplies — software "MFMA-for-complex" analogues):
  - **Gauss 3-multiply trick** and **cgemm3m**: cuBLAS documents Gauss complexity reduction giving **up to 25 %** (cuBLAS docs, https://docs.nvidia.com/doc/cuBLAS/). **check** exact figure/page.
  - **BLIS 3m/4m**: Van Zee & Smith, *Implementing Complex GEMM Using a Kernel of Real GEMMs* (TOMS, https://www.cs.utexas.edu/~flame/pubs/blis5_toms_rev2.pdf).
  - **BLIS 1m**: single real-domain GEMM via a special packing (Smith et al., SISC, https://www.cs.utexas.edu/~flame/pubs/blis6_sisc_rev0.pdf; flame/blis, https://github.com/flame/blis) — **check** the exact real-vs-complex constant; **GEMMFIP** surveys these methods on GPUs (arXiv:2302.08417, https://arxiv.org/abs/2302.08417).
  - These reduce **arithmetic, not bytes** — attractive exactly where our CC/DD cells are VALU-bound, less so if the cell is already DRAM-bound on DDR4 (§1).
- **Reduction-path strategy already ranked by the project** (potential_configs.md §13.5): `GSU ∈ {2,4,8}` × `GlobalSplitUAlgorithm=MultipleBuffer` splits K across workgroups with partial results in workspace, then a post-kernel accumulates — mechanically sound for complex (gate §4) at the cost of a **2-kernel launch + workspace traffic**, which matters more on this bandwidth-poor APU than on dGPU. `StreamK` would be the modern answer but is MFMA-gated (§4).
- **Ordering principle** (from §13.5, unchanged): pads → GSU+MultipleBuffer → PGR=0 → NLCA=3 → split-complex; each rung is only entered if the previous stays under the ~2× gap budget.

## 6. SOTA autotuning and cross-SKU porting ("anti-spoofing")

- **Autotuning is the consensus answer to portability**:
  - **Kernel Tuner** (kerneltuner.github.io, https://kerneltuner.github.io; van Werkhoven et al. 2019) — search-based tuning over code variants with cache/surrogate support; the academic reference for "tune on the target, not from paper numbers".
  - *GPU Performance Portability Needs Autotuning* (arXiv:2505.03780, https://arxiv.org/abs/2505.03780) and cross-architecture autotuning (ACM, https://doi.org/10.1145/3797905.3800519) — explicit thesis: **hand-portable "best configs" don't exist**.
  - **WaveTune** (arXiv:2604.10187, https://arxiv.org/abs/2604.10187) — runtime autotuning whose performance model is built on **wave quantization** (§3.1): discrete residency/launch steps make performance profiles piecewise-constant, so tune at the *plateau*, not the cliff edge.
- **Empirical evidence that configs do not transfer across GPUs**: HEP/CMSSW autotuning study (INSPIRE, https://inspirehep.net) — solutions selected on one GPU lose measurable performance on others, motivating per-arch tuning; DevConf 2026 talk *"Warm Starts Over Fresh Runs"* reports **default config 14–31 % slower** and **tuning caches tied to the specific device** — **check** URL/proceedings not yet located.
- **"Anti-spoofing" rules for this project** (distilled; consistent with the campaign docs):
  1. **Never import a `tensile` database tuned on gfx900/1031 dGPU as a winner** — it may *rank* plausible (same ISA, §1) while being wrong on the exact knobs that differ: VGPR-residency cliffs (§3), LDS pad value (§2 — pads are non-monotonic!), and channel/`StaggerU` behavior on shared DDR (§4). Use foreign databases as **priors/orderings only**.
  2. **Rankings transfer better than values**: NT/T layout dominance and macro-tile *scale* tend to port (same ISA); exact `DepthU`, `LdsPad`, `GSU`, `VW` boundaries are per-SKU (per-arch tuning evidence above).
  3. **Validate per device, per session** — M4's rules stand: benchmark **TTY runs only, never from the GUI session**; enforce the **1.175 GHz clock-suppression check** before trusting any delta (see `knowledge_base.md` M4 / `changelog.md`, referenced not copied).
  4. **Warm-start caches must be keyed by device** (DevConf finding) — a cached "best config" from a previous session/machine is evidence, not a result.
  5. **Stream-K literature is background, not applicable here**: StreamK requires MFMA (`SolutionStructs.py:2976`); the transferable ideas are **split-K via `GSU>1`** and **persistent/quantization-aware tile sizing** (Colfax Stream-K/persistent-kernel tutorials, https://colfaxresearch.com; Stream-K++, arXiv:2408.11417, https://arxiv.org/abs/2408.11417).

## 7. Concrete experiments mapped to M1–M4

- All runs below are **already-owned cells** in potential_configs.md §13.4–§13.6 (Groups A–D); this section only supplies the mechanistic hypothesis and the prediction to record *before* measuring (M1 vocabulary, M2 gate names throughout).
- **H1 — `LdsPad ∈ {0,1,2,4}` × NT/T (Group B)**: §2 predicts **pad 1 conflict-free, pad 4 regression, non-monotonic ordering**. Pre-registered prediction: `LdsPad=1` ≥ `2` > `4` ≥ `0` on transpose-heavy (T) cells; near-no-effect on NT cells where Tensile's auto rule picks 0 (`SolutionStructs.py:2812-2815`). Mechanism column: M3-LDS. Gates: `ldspad_feasible` (`scheduler.py:1261`) — mind the ZZ `BYTES_PER_ELEMENT` caveat (§3.3, **check**).
- **H2 — `GSU ∈ {2,4,8}` × `GlobalSplitUAlgorithm=MultipleBuffer` (Group C)**: mechanism = K-split changes per-wave register/tile shape → moves `V` across a §3 quantization boundary *and* adds a 2-kernel + workspace penalty (§4). Prediction: wins only where current `V` sits just above a cliff (e.g. 3-wave kernels); loses on already-4-wave cells. `GSU=1` has been in every winner so far (see potential_configs.md §8.6) — expect this group to be narrow, not a breakthrough.
- **H3 — `PrefetchGlobalRead=0` (Group C)**: frees the double-buffer VGPRs **and** halves LDS footprint (`Common.py:511-513`). Prediction: occupancy step 3→4 waves (`V` 79→≤64 territory, §3.1) at the cost of lost global-read overlap — net win only on memory-latency-insensitive (compute-bound) cells. Mechanism: M3-register.
- **H4 — `NLCA=3` (Group C)**: fuses LDS-load instructions (potential_configs.md §13.5). Mechanism: fewer LDS instructions + reduced LDS port pressure; interacts with H1 (a fused load pattern changes which pad matters — run H4 on top of the H1 winner, not independently).
- **H5 — split-complex decomposition (Group D, last resort)**: only if the ladder stays under ~2× (§13.5). Feasibility **check** (native problem type vs 4× real-domain GEMM call-level decomposition, §5); predicted win condition: CC/DD cells that are VALU-bound by the 4-pass MAC (`MAC_F32C.py`) rather than DRAM-bound (§1 roofline).
- **Reporting discipline**: every result enters M2 tables with its `occupancy_feasible`/`ldspad_feasible` verdict and the measured `V`/residency (§3 formula is the cross-check); the M4 clock/TTY rules gate every timing. One fact, one home: this doc supplies *why*, `potential_configs.md` supplies *what was tried*, `knowledge_base.md` supplies *what won*.

---

## Sources

**Hardware / architecture**
- LLVM AMDGPUUsage (gfx target families, wave32 reserved on GFX6–9, VGPR granularity): https://llvm.org/docs/AMDGPUUsage.html
- HIP docs — Hardware implementation (LDS 32 banks × 4 B, 128 B/cycle): https://rocm.docs.amd.com/projects/HIP/en/latest/understand/hardware_implementation.html
- Composable Kernel — Understanding AMD GPU LDS and Bank Conflicts (bank aliasing, per-instruction phases, XOR swizzle): https://rocm.docs.amd.com/projects/composable_kernel/en/latest/conceptual/ck_tile/hardware/lds_bank_conflicts.html
- ROCm Compute Profiler — Pipeline descriptions (LDS conflict-resolution hardware): https://rocm.docs.amd.com/projects/rocprofiler-compute/en/docs-6.3.0/conceptual/pipeline-descriptions.html
- ORNL — AMD GPU Hardware Basics (CU: 4 SIMD × 64 KiB VGPR file, 64 KiB LDS, 32 banks, gfx9 occupancy): https://www.olcf.ornl.gov/wp-content/uploads/2019/10/ORNL_Application_Readiness_Workshop-AMD_GPU_Basics.pdf
- chipsandcheese — GCN, AMD's GPU Architecture Modernization (10-entry scheduler partition, 64 KB/SIMD register file, 128 B/cycle LDS): https://chipsandcheese.com/p/gcn-amds-gpu-architecture-modernization
- nod-ai amdgpu_kernel_optimization_guide (bank formula `(address/4)%32`, per-instruction phase widths): https://github.com/nod-ai/shark-ai/blob/main/docs/amdgpu_kernel_optimization_guide.md
- Wikipedia — RDNA (microarchitecture) (GCN 1 inst/wave per 4 cycles; wave32 RDNA-only): https://en.wikipedia.org/wiki/RDNA_(microarchitecture)
- Bart Wronski — GCN: two ways of latency hiding and wave occupancy: https://bartwronski.com/2014/03/27/gcn-two-ways-of-latency-hiding-and-wave-occupancy
- AMD Ryzen 7 5800H product page (8 CU, 2000 MHz, DDR4-3200): https://www.amd.com/en/products/processors/laptop/ryzen/7000-series/amd-ryzen-7-5800h.html
- WCCFTech — Cezanne/Barceló spec table (5600U: 7 CU @ 1800 MHz): https://wccftech.com
- TechPowerUp — Radeon RX Vega 64 specs (FP64 1:16, **check** applicability to gfx90c): https://www.techpowerup.com/gpu-specs/radeon-vega-64.c3039
- FOSS United — Season of Commits 2026: Porting ROCm to gfx90c (same ISA as gfx900; HBM ~400 GB/s vs APU DDR4 30–40 GB/s): https://fossunited.org
- LLVM review D100126 (gfx90c code object v2 backwards compatibility): https://reviews.llvm.org/D100126
- GPUOpen — RDNA Architecture whitepaper (32 LDS banks "same as Vega", bank-conflict warning): https://gpuopen.com/download/RDNA_Architecture_public.pdf

**Occupancy / quantization**
- GPUOpen — Occupancy explained: https://gpuopen.com/learn/occupancy-explained
- GPUOpen — Optimizing GPU occupancy and resource usage with large thread groups: https://gpuopen.com/learn/optimizing-gpu-occupancy-resource-usage-large-thread-groups
- ROCm Blogs — Occupancy Math on AMD MI355X (limiter = budget ÷ consumption, floored): https://rocm.blogs.amd.com/software-tools-optimization/occupancy-math-mi355x/README.html
- NVIDIA — Matrix Multiplication Background (tile & wave quantization): https://docs.nvidia.com/deeplearning/performance/dl-performance-matrix-multiplication/index.html
- WaveTune (arXiv:2604.10187): https://arxiv.org/abs/2604.10187

**Complex GEMM**
- "Flexible Performant GEMM Kernels on GPUs" (SplitComplex vs InterleavedComplex): https://ieeexplore.ieee.org/document/9655458
- cuBLAS docs — Gauss / cgemm3m complexity reduction (**check** figure): https://docs.nvidia.com/doc/cuBLAS/
- Van Zee & Smith — Complex GEMM as a kernel of real GEMMs (BLIS 3m/4m, TOMS): https://www.cs.utexas.edu/~flame/pubs/blis5_toms_rev2.pdf
- BLIS 1m (SISC): https://www.cs.utexas.edu/~flame/pubs/blis6_sisc_rev0.pdf ; flame/blis: https://github.com/flame/blis
- GEMMFIP — arXiv:2302.08417: https://arxiv.org/abs/2302.08417
- rocBLAS programming guide (Tensile complex problem types): https://rocm.docs.amd.com/projects/rocblas/
- **First-party companion brief:** `complex_gemm_research_brief.md` (repo root) —
  BLAS-8 accounting, the four-FMA complex MAC (MAC_F32C.py/MAC_F64C.py), 3M/4M
  instruction counts, MAGMA/Fermi + Ozaki routes. The single citation anchor for
  the corrected complex-ceiling frame and the split-complex estimate in
  `potential_configs.md` §1/§8.2

**Autotuning / portability**
- Kernel Tuner: https://kerneltuner.github.io
- GPU Performance Portability Needs Autotuning — arXiv:2505.03780: https://arxiv.org/abs/2505.03780
- Cross-architecture autotuning — ACM DOI 10.1145/3797905.3800519: https://doi.org/10.1145/3797905.3800519
- HEP/CMSSW autotuning study (per-GPU config transfer loss): https://inspirehep.net
- DevConf 2026 — "Warm Starts Over Fresh Runs" (defaults 14–31 % slower; device-keyed caches) — **check** URL
- Colfax — persistent kernels / Stream-K tutorials: https://colfaxresearch.com
- Stream-K++ — arXiv:2408.11417: https://arxiv.org/abs/2408.11417

**Tensile (local checkout at `TENSILE_ROOT`)**
- `Tensile/Common.py:511-519` (PGR cost), `:551-556` (`1LDSBuffer`), `:906-946` (`StaggerU`), `:975-981` (`WorkGroupMapping`), `:983` (`MaxOccupancy`), `:1358/:1360` (`LdsPad` comments), `:1542-1629` (defaults)
- `Tensile/SolutionStructs.py:2759-2769` (`getLdsNumElements`), `:2788-2892` (auto pad / `numBank=32` / VALU-mode rejects), `:2970-2971` (`MultipleBuffer` → `_GlobalAccumulation`), `:2976` (StreamK MI gate), `:3461/:3488/:3491` (16 B cap), `:3530-3553` (GSU gates)
- `Tensile/Components/MAC_F32C.py:55/:73/:90/:107` (4-pass complex MAC)
- `Tensile/KernelWriterAssembly.py:2369-2387` (`_v_mac_f32` macro → `v_fmac/v_fma/v_mac`)
- `Tensile/docs/src/conceptual/kernel-parameters.rst` (official knob reference); `Tensile/tuning_docs/tensile_tuning.tex:1430` (`NLCA` = `NumLoadsCoalescedA`)

**Project files**
- `gfx90c_tuning_guide.md` (M1–M4 vocabulary, knob surface), `potential_configs.md` §6/§7/§8/§10 (experiment groups, steal, split-complex, queue), `gfx90c_theoretical_limits.md` (ceilings), `knowledge_base.md` §7/§10/§11 (data law, measured context), `scheduler.py:31-36/:1039/:1106/:1186/:1261` (gates, LDS/VGPR budgets, `BYTES_PER_ELEMENT` Z issue), `complex_gemm_research_brief.md` (complex-MAC accounting + split routes), `changelog.md`
