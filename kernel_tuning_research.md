# Kernel tuning research — gfx90c (GCN5 / Vega-class APU)

## How this relates to the project

- This doc is **research only** — hardware model, literature, and Tensile source mechanics. It contains no benchmark numbers of its own; all measured values live in `potential_configs.md` and `knowledge_base.md` and are referenced, never copied.
- Companions: `gfx90c_tuning_guide.md` defines the campaign vocabulary (**M1** scope/axes, **M2** gates, **M3** mechanisms, **M4** measurement rules) and the knob surface; `potential_configs.md` §8 (Groups A/B/C), §9 (steal), §10 (other routes incl. §10.2 split-complex) and §12 (next-run queue) define the ranked experiment groups and the resolution ladder (occupancy/tile levers → split-complex). Section 7 below maps each research finding onto that existing plan; §8 lists the **open research directions** — the questions these mechanics do not settle — as falsifiable probes, not new experiment cells.
- `gfx90c_theoretical_limits.md` remains the authority for performance ceilings; this doc only explains *why* those ceilings exist.
- Cite conventions: repo files as `path.py:line` against the local Tensile checkout at `TENSILE_ROOT` (per `.env`); web sources inline as `(site, URL)`; full list in **Sources**. Claims I could not fully verify are marked **check**.
- **The 2026-10-16 primary-source pass** (Tensile's `validParameters` / `defaultSolution` / shipped `Perf/*.yaml` read directly, plus the external autotuning literature) had its conclusions promoted once each into their owners — `gfx90c_tuning_guide.md` §1.1 (the legal knob domains) and §9.1 (the virgin axes), and `tensile_tuning_context.md` (the search order). Its raw file was retired on that fold (`docs/README.md`), so the owners are the durable record.

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
- **Predictions for Group B (`LdsPad` sweep, potential_configs.md §8):**
  - **pad 1 is conflict-free for all three element sizes** and should win where the column-read pattern dominates;
  - **pads are non-monotonic** — pad 4 is *worse* than pad 1 everywhere and worse than pad 2 for 4 B — so "more padding" is not a safe prior; a `LdsPad ∈ {0,1,2,4}` grid (not a binary toggle) is required;
  - LDS cost of pad 1 at `R=64` is `(64+1)/64 ≈ 1.6 %` — negligible against `LDS_BUDGET = 16384` B (`oto/tensile/gates/vgpr_model.py`, `ldspad_feasible` gate in `oto/tensile/gates/occupancy.py`), but `PrefetchGlobalRead=1` doubles the footprint (§4).

### 2.3 What Tensile actually does

- `getLdsNumElements` adds `LdsPad` **per row** when `padInterval = MacroTile`
  (`Tensile/SolutionStructs.py:2759-2769`, esp. `:2767-2769`).
- **Auto-padding** (`ldsPaddingAuto`, `Tensile/SolutionStructs.py:2788`, hardcoded
  `numBank = 32` at `:2802`): `LdsPad = -1` resolves to **0 when `TLU` and not
  `UnrollMajorLDS`, else `VectorWidth`** (`:2812-2817`) — i.e. Tensile only pads
  when a transpose read is required, mirroring its own comment *"Padding only
  helps when transpose is required"* (`Tensile/Common.py:1360`).
- Tensile's historical caution: *"in 2016 this didn't seem to help performance,
  profilers were showing that channel conflicts weren't really hurting"*
  (`Tensile/Common.py:1358`) — **our context differs**: 2016-era dGPU bandwidth
  hid LDS stalls behind memory latency; on a DDR-bound APU with 16-B complex
  elements, VALU-side serialization is more exposed. Hypothesis to test, not a fact.
- **gfx90c constraint**: our kernels are **VALU (non-MI) mode** —
  `LdsBlockSizePerPad` (periodic/XOR-style padding) is **rejected outright**
  (`Tensile/SolutionStructs.py:2891-2892` "didn't support LdsBlockSizePerPad in
  VALU mode yet"; `UnrollMajorLDS` also rejected `:2889-2890`). **Only plain
  per-row `LdsPadA/B` is available** → the pad grid above is the whole design space.
- The 16 B load cap: `GlobalLoadVectorWidth × numBytes > 16` is rejected
  (`Tensile/SolutionStructs.py:3461`, also `VWA/VWB` `:3488`, `:3491`) → **16-B
  loads cap GLVW at 1**, which is why `VectorWidth` bounds are `S4/H8/D2/C2/Z1`
  (see `gfx90c_theoretical_limits.md` §1 and `gfx90c_tuning_guide.md` knob table —
  not repeated here).
- **The code contracts that enforce the above on this port**: the per-row pad
  accounting and the padded-LDS footprint gate are `occupancy.ldspad_feasible`
  (`oto/tensile/gates/occupancy.py`); the load-cap / GLVW divisibility (including
  the shift-ptr `GLVW == VectorWidth or 1` guard, with its `GuaranteeNoPartialA`
  escape hatch, and `cap_vector_width`, which returns the widest `VectorWidth`
  satisfying `VW·bytesPerElement ≤ 16` *and* `TT % VW == 0` *and* `VW ≤ MT/TT`) is
  `loads.validate_tensile_loads` / `loads.cap_vector_width`
  (`oto/tensile/gates/loads.py`); the class rules are
  `assembly.assembly_class_valid` (`oto/tensile/gates/assembly.py`); and the
  knob-forwarding surface is the module docstring + `FORWARDED_GROUP_C_KNOBS`
  of `oto/tensile/config_writer.py`. The paragraphs above are the *bank-conflict*
  rationale; the modules are the executable restatement.

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

### 3.3 LDS as the second limiter (and the model's three byte tables)

- Workgroups per CU are also capped by **LDS**: the model uses
  `LDS_BUDGET = 16384` B/CU and gates candidates through `occupancy_feasible`
  (register-file + LDS footprint, `oto/tensile/gates/occupancy.py`) and
  `ldspad_feasible` (padded footprint + swizzle domains, same module). The
  footprint wall is `(MT0 + MT1) · DepthU · bytesPerElement ≤ LDS_BUDGET`.
- **Why 16384 and why `Z` counts 8, not 16**: the module carries **three
  deliberately distinct byte tables**, and conflating them is the trap:
  - `FAMILY_BYTES_PER_ELEMENT` (`oto/tensile/gates/vgpr_model.py`) — the
    **element / global-load width** used for the 16-B cap. `ZZ = 16`. Test-locked.
  - `BYTES_PER_ELEMENT` (same module) — the **LDS footprint** table. Here
    `Z = 8` is deliberate and distinct from the 16-B element width, and it is
    calibrated: the footprint wall is `(MT0+MT1)·DepthU·bpe`, so
    `(64+64)·16·8 == 16384 == LDS_BUDGET` sits exactly on the measured complex
    boundary (16384 B/WG legal; 20480 B/WG dead; `128x32x16` needs 106496 B and
    Tensile rejects it). The lock is
    `tests/test_occupancy_gate.py::TestLdsGate::test_budget_sits_at_measured_boundary`.
  - `ASSEMBLY_DTYPE_ELEM_BYTES` (`oto/tensile/gates/assembly.py`) — the
    **assembly class** rule, which counts the *element*: `Z = 16`.
  - The older note here — "suspected 2× LDS under-count of ZZ, `scheduler.py`
    lists `Z: 8`" — is **retired**: the pre-split `scheduler.py` is gone (now
    `oto/tensile/gates/*`), and the `8` is intentional and test-locked, so it is
    not a bug. The real footprint bound is the `(MT0+MT1)·DepthU·bpe` wall above.
- Deliberate occupancy *limiting* exists too: the `MaxOccupancy` knob
  *"allocates extra lds to artificially limit occupancy"* when cache thrashing
  hurts (`Tensile/Common.py:983`) — a reminder that more residency is a
  hypothesis, not a goal.

## 4. Tensile knob mechanics

- Canonical knob reference: `docs/src/conceptual/kernel-parameters.rst` in the
  Tensile tree (abbreviations `LPA/LPB/GSU/GSUA/PGR/PLR/SU/SUS/WGM/GRVW/NLCA/AF0EM/SCIU/MO/MVN/WS`).
  Defaults verified in `Tensile/Common.py:1542-1629`: `PrefetchGlobalRead=1`
  (`:1542`), `PrefetchLocalRead=1` (`:1543`), `StaggerU=32` (`:1597`),
  `StaggerUStride=256` (`:1598`), `WorkGroupMapping=8` (`:1626`),
  `MACInstruction=FMA` (`:1628`), `WavefrontSize=64` (`:1629`).
- **`PrefetchGlobalRead`**: `PGR=1` **requires 2× LDS space and VGPRs for
  buffering** (`Tensile/Common.py:511-513`); `PGR=2` prefetches during the
  VGPR→LDS copy (`:515-518`). `1LDSBuffer` forces a single LDS buffer even with
  PGR (`:551-556`) — trades double-buffering for LDS budget. → PGR=0 is
  simultaneously a **VGPR and LDS** relief valve (feeds §3.3, Group C).
- **`StaggerU` / `StaggerUStride`**: `StaggerU` is the max number of "clicks" of
  `StaggerUStride` bytes by which workgroups stagger their summation start
  (`Tensile/Common.py:906-917`); rationale: V20 has **16 channels × 256 B**
  (`:915`), `StaggerUStride=256` lands each click in a fresh channel (`:928-930`);
  `StaggerUStride` is internally rounded to a multiple of `DepthU·BPE` (`:933`);
  **`StaggerU` silently requires `BufferLoad=1`** (`:924`); and *"StaggerU and
  WorkGroupMapping interact and should be tuned together"* (`:921-922`).
  **check**: 16-channel count is a dGPU-era comment (gfx803/900/906) — iGPU
  channel/L2 topology differs. On this port the trio is forwarded **coupled**
  (`StaggerU`, `StaggerUMapping`, `StaggerUStride` in `FORWARDED_GROUP_C_KNOBS`)
  and bounded by `occupancy._swizzle_feasible`.
- **`WorkGroupMapping`**: remaps `wg1` so tiles hit L2 favorably; semantics
  `wgSerial = wg0 + (wg1 % WorkGroupMapping) * nwg0` (`Tensile/Common.py:980`),
  *"box width determined by the number of compute units"* (`:975-981`) —
  **check**: exact formula for 7-CU parts. `WGM=8` is the default (`:1626`) and a
  proven real lever on this APU (see potential_configs.md §3 — WGM8 in
  winners, referenced not copied).
- **`GlobalSplitU`**: `GSU=1` forces `GlobalSplitUAlgorithm=SingleBuffer`
  (`Tensile/SolutionStructs.py:3530-3532`). For **`GSU>1` the supported-type
  gate** (`:3543-3553`) accepts single/8-bit/double+BufferStore/int32/asm-half
  **or `_GlobalAccumulation` set or MFMA** — **complex (`X`) passes only via
  `_GlobalAccumulation`**, which is set exactly by
  `GlobalSplitUAlgorithm=MultipleBuffer` (`:2970-2971`). MultipleBuffer
  semantics: each GSU group writes its own workspace buffer, a post-GSU kernel
  does the accumulation (`Tensile/Common.py:570-591`) → **2 kernel launches +
  workspace allocation** per GEMM. The atomic path is excluded for our setup
  (`:3064`). **On this port only the SingleBuffer-atomic path is reachable** —
  `oto/tensile/config_writer.py` never forwards `GlobalSplitUAlgorithm` or a
  reduction workspace, and `assembly._gsu_rejection` refuses complex GSU>1 and
  half-with-f32-accumulate GSU>1 — so **SS is the only GSU-legal family**
  (ladder `{1,2,4}`); the "MultipleBuffer wave-fill" lever is withdrawn here.
- **`LocalSplitU` / `NumThreads` (the load path's real thread count).** Tensile has
  no standalone `LocalSplitU` key: it reads the workgroup's third element
  (`SolutionStructs.py:1958`) and computes `NumThreads = SubGroup0 * SubGroup1 *
  LocalSplitU` (`:1964`). Two consequences that bit this port:
  1. **Shadowing.** `config_writer._fork_tile` emits an explicit `WorkGroup`
     verbatim and only folds `LocalSplitU` in when WorkGroup is absent, so
     `WorkGroup: [16,16,1]` beside `LocalSplitU: 2` benchmarks at LSU 1 while
     the note claims LSU 2. The gate therefore models the *emitted* value
     (`loads._local_split_u`: WorkGroup's third element wins). A knob shadowed
     by an explicit WorkGroup is the same failure mode as a not-forwarded knob
     (silent no-op) -- `NOT_FORWARDED_KNOBS`/`_DEPRECATED_KEYS` is the
     analogous report surface.
  2. **LDS footprint.** `ldsNumElementsReduction = multiplier * LSU * MT0 * MT1`
     (`SolutionStructs.py:4104-4108`), `multiplier = ComputeBytes // LoadBytes`,
     so in bytes it simplifies to `LSU * MT0 * MT1 * ComputeDataType.numBytes()`
     (the multiplier cancels the load element size); `MaxLDS = 65536` (`:4334`).
     This is the rule behind the `131072 > 65536` rejects. **Gated** since
     2026-10-18 (`occupancy.occupancy_feasible`, table
     `vgpr_model.COMPUTE_BYTES_PER_ELEMENT`, HPA → f32 4 B): 0 false rejections,
     13 empty phases caught. It is the *compute* dtype that scales the buffer,
     not the destination.
- **The workgroup register file (Tensile's second, independent VGPR bound).**
  `KernelWriterAssembly.functionSuffix` computes
  `vgprPerThreadPerOccupancy = 65536 // NumThreads` and sets
  `overflowedResources = 4` ("resulting in error 4") when
  `numWorkGroupsPerCU = vgprPerThreadPerOccupancy // max(vgpr, agpr) < 1`. The
  accumulator set is always allocated, so `TT0*TT1*R` is a sound lower bound on
  `vgprPool.size()`; substituting `NumThreads = (MT0/TT0)*(MT1/TT1)*LSU` makes the
  workgroup accumulator total `R * MT0 * MT1 * LSU` — **ThreadTile cancels**. The
  rule `R * MT0 * MT1 * LSU >= 65536` is therefore a *MacroTile* constraint,
  distinct from the per-thread `TT0*TT1*R <= 128` bound (**both** are enforced).
  The boundary is `>=`, not `>`, because an accumulator set that exactly fills the
  file leaves no VGPR for operands. **Gated** since 2026-10-18: 0 false rejections,
  40 empty phases caught, on both the native and the reference populations. It is
  the constraint the retired `R*MTarea <= 65536/2` area model was reaching for,
  with the right threshold (65536) and the right boundary (`>=`) —
  potential_configs.md §R24/§R27.
- **The `NumThreads`-aware per-thread budget is a trap (probed, rejected).** The
  obvious next rule is a per-thread VGPR ceiling `min(256, 65536 // NumThreads)`.
  Probed against the corpus (`oto.harness.rule_calibration --rule nt_budget`,
  2026-10-18) it would refuse **1 phase Tensile built** — complex `Z` tt2x2 at
  64x64, `NumThreads = 1024` → budget 64 against a measured 71 VGPRs — so it
  adds a false rejection and must not land. It is kept in the harness as the
  worked counter-example that a rule is calibrated *in isolation, before it
  becomes a gate*. The shipped workgroup rule is sound precisely because it
  stops at the accumulator *lower bound* (`R*MT0*MT1*LSU`) rather than the
  measured total.
- **The 16-B global-load cap check runs early.** `SolutionStructs.py:3459-3461`
  (`GLVW * numBytes() > 16`) is evaluated *before* `setGlobalLoadVectorWidth`
  reduces pv (`:2010`), so a ZZ tile at `VectorWidth=2` is refused on the cap
  (`2 * 16 = 32`) even though the pv-reduced width would have fit. This is why
  `LOAD_DTYPE_INFO["Z"]` must carry ComplexDouble's 4 registers / 16 bytes, not
  ComplexFloat's 2 / 8 -- the load gate and `vgpr_model.FAMILY_BYTES_PER_ELEMENT`
  are separate homes (the load half is 16 B, the LDS half stays 8 B).
- **`AggressivePerfMode=2` builds nothing** (measured, then traced): across two
  runs, every family and every tile produced 0 `.hsaco` and 0 CSV while the
  mode-1 control in the same run built 20 (one per target arch). The cause is in
  `Components/Priority.py`: the priority component is dispatched by exact match on
  the boolean kernel fingerprints `{False}` / `{True}`, so 2 matches neither,
  `Priority.find` returns `None`, and `MAC_F32C.__call__` raises
  `TypeError: 'NoneType' object is not callable` before a kernel exists.
  **Refused** at the generator seam since 2026-10-18
  (`candidate._non_generative_knob_rejection`) — every family, 0/28 built. The
  *writer* still forwards any value (its contract test probes APM=2 to prove the
  forwarding), so this is a draw-time refusal, beside `AssertSizeMultiple: [1]`;
  recorded in `oto/tensile/decks.py` and out of the sweep (potential_configs.md
  §R24).
- **`StreamK` is unavailable on gfx90c**: rejected unless
  `MIWaveGroup0×MIWaveGroup1 == 4` (`Tensile/SolutionStructs.py:2976`) —
  MFMA-only → **all StreamK/StreamK++ literature is background, not an experiment**
  (§6).
- **MAC plumbing (the complex-GEMM cost)**: `Components/MAC_F32C.py` emits
  **four `_v_mac_f32` instructions per complex multiply-accumulate** — the
  real/imag cross terms at `MAC_F32C.py:55` (rr), `:73` (ar), `:90` (ra),
  `:107` (ai, i.e. the 4-pass loop). The `_v_mac_f32` macro resolves to
  `v_fmac`/`v_fma`/`v_mac` per `MACInstruction`
  (`Tensile/KernelWriterAssembly.py:2369-2387`); default is `FMA`
  (`Common.py:1628`). Note: the campaign doc's older citation
  (`KernelWriterAssembly.py:14975-14978`) points at the beta/finalSum epilogue,
  not the MAC loop — **cite `MAC_F32C.py` for the 4× claim**.
- **`NumLoadsCoalescedA/B` (`NLCA/NLCB`)**: coalesces LDS loads
  (`tuning_docs/tensile_tuning.tex:1430`, `kernel-parameters.rst:449`);
  `NLCA=3` fuses LDS-load instructions in our kernel population (see
  potential_configs.md §7, referenced for the counts). On this port NLCA is
  also the shared alias for `NumLoadsCoalescedA` in
  `oto/tensile/gates/loads.py:_nlca_for`.
- **Enforcement/module pointers**: the forwarded set is
  `FORWARDED_GROUP_C_KNOBS` and the write path `_fork_params`
  (`oto/tensile/config_writer.py`); the class rules are
  `assembly.assembly_class_valid`; the load/GLVW divisibility is
  `loads.validate_tensile_loads`; the LDS/swizzle legality is
  `occupancy.ldspad_feasible` (all `oto/tensile/gates/*`). Tensile's canonical
  knob reference remains `docs/src/conceptual/kernel-parameters.rst` in the
  `TENSILE_ROOT` tree.

## 5. Complex GEMM strategies (including split-complex)

- **Where the 4× comes from**: complex MAC = 4 real FMAs + 2 adds; Tensile's VALU implementation is literally **4 `_v_mac_f32` passes per (a,b,iui)** (`Components/MAC_F32C.py:55/73/90/107`). At the same wave residency this makes CC/ZZ ~4× more VALU-hungry than SS/DD — the mechanism behind the derived CC/ZZ ceilings (see `gfx90c_theoretical_limits.md`, referenced not copied).
- **Data layouts**:
  - **Interleaved complex** (zr,zi adjacent) — what Tensile/rocBLAS problem types use (e.g. `Cijk_Ailk_Bjlk_CB`, rocBLAS programming guide, https://rocm.docs.amd.com/projects/rocblas/).
  - **Split-complex** (SoA real and imaginary planes) — halves contiguous runs, doubles stride; compared head-to-head with interleaved in "Flexible Performant GEMM Kernels on GPUs" (IEEE Computer Society, https://ieeexplore.ieee.org/document/9655458). **check**: whether this Tensile checkout has a native split-complex problem type (Group D escalation in potential_configs.md §10.2 assumes decomposition into 4 real-domain GEMMs at the *call* level if not).
- **Algebraic reductions** (do the same FLOPs with fewer multiplies — software "MFMA-for-complex" analogues):
  - **Gauss 3-multiply trick** and **cgemm3m**: cuBLAS documents Gauss complexity reduction giving **up to 25 %** (cuBLAS docs, https://docs.nvidia.com/doc/cuBLAS/). **check** exact figure/page.
  - **BLIS 3m/4m**: Van Zee & Smith, *Implementing Complex GEMM Using a Kernel of Real GEMMs* (TOMS, https://www.cs.utexas.edu/~flame/pubs/blis5_toms_rev2.pdf).
  - **BLIS 1m**: single real-domain GEMM via a special packing (Smith et al., SISC, https://www.cs.utexas.edu/~flame/pubs/blis6_sisc_rev0.pdf; flame/blis, https://github.com/flame/blis) — **check** the exact real-vs-complex constant; **GEMMFIP** surveys these methods on GPUs (arXiv:2302.08417, https://arxiv.org/abs/2302.08417).
  - These reduce **arithmetic, not bytes** — attractive exactly where our CC/DD cells are VALU-bound, less so if the cell is already DRAM-bound on DDR4 (§1).
- **Reduction-path strategy already ranked by the project** (potential_configs.md §10.1): `GSU ∈ {2,4,8}` × `GlobalSplitUAlgorithm=MultipleBuffer` splits K across workgroups with partial results in workspace, then a post-kernel accumulates — mechanically sound for complex (gate §4) at the cost of a **2-kernel launch + workspace traffic**, which matters more on this bandwidth-poor APU than on dGPU. `StreamK` would be the modern answer but is MFMA-gated (§4).
- **Ordering principle** (from §7, unchanged): pads → GSU+MultipleBuffer → PGR=0 → NLCA=3 → split-complex; each rung is only entered if the previous stays under the ~2× gap budget.

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

- All runs below are **already-owned cells** in potential_configs.md §8 (Groups A–D); this section only supplies the mechanistic hypothesis and the prediction to record *before* measuring (M1 vocabulary, M2 gate names throughout).
- **H1 — `LdsPad ∈ {0,1,2,4}` × NT/T (Group B)**: §2 predicts **pad 1 conflict-free, pad 4 regression, non-monotonic ordering**. Pre-registered prediction: `LdsPad=1` ≥ `2` > `4` ≥ `0` on transpose-heavy (T) cells; near-no-effect on NT cells where Tensile's auto rule picks 0 (`SolutionStructs.py:2812-2815`). Mechanism column: M3-LDS. Gates: `ldspad_feasible` (`oto/tensile/gates/occupancy.py`) — mind the padded-footprint bound and the intentional `BYTES_PER_ELEMENT["Z"]=8` LDS table (§3.3).
- **H2 — `GSU ∈ {2,4,8}` × `GlobalSplitUAlgorithm=MultipleBuffer` (Group C)**: mechanism = K-split changes per-wave register/tile shape → moves `V` across a §3 quantization boundary *and* adds a 2-kernel + workspace penalty (§4). Prediction: wins only where current `V` sits just above a cliff (e.g. 3-wave kernels); loses on already-4-wave cells. `GSU=1` has been in every winner so far (see potential_configs.md §6) — expect this group to be narrow, not a breakthrough.
- **H3 — `PrefetchGlobalRead=0` (Group C)**: frees the double-buffer VGPRs **and** halves LDS footprint (`Common.py:511-513`). Prediction: occupancy step 3→4 waves (`V` 79→≤64 territory, §3.1) at the cost of lost global-read overlap — net win only on memory-latency-insensitive (compute-bound) cells. Mechanism: M3-register.
- **H4 — `NLCA=3` (Group C)**: fuses LDS-load instructions (potential_configs.md §7). Mechanism: fewer LDS instructions + reduced LDS port pressure; interacts with H1 (a fused load pattern changes which pad matters — run H4 on top of the H1 winner, not independently).
- **H5 — split-complex decomposition (Group D, last resort)**: only if the ladder stays under ~2× (§7). Feasibility **check** (native problem type vs 4× real-domain GEMM call-level decomposition, §5); predicted win condition: CC/DD cells that are VALU-bound by the 4-pass MAC (`MAC_F32C.py`) rather than DRAM-bound (§1 roofline).
- **Reporting discipline**: every result enters M2 tables with its `occupancy_feasible`/`ldspad_feasible` verdict and the measured `V`/residency (§3 formula is the cross-check); the M4 clock/TTY rules gate every timing. One fact, one home: this doc supplies *why*, `potential_configs.md` supplies *what was tried*, `knowledge_base.md` supplies *what won*.

## 8. Open research directions

This section is the doc's **to-do list**: the questions §1–§7 raise and do not
settle. Each item is written as a falsifiable probe — a prediction, the
observation that would close it, and where the answer would be recorded. They
are ordered by information value; all are CPU-only until a TTY benchmark is
sanctioned (M4). A direction is *closed* only when it has a pre-registered
prediction, a gate verdict, a TTY measurement, and a `kernel_db.json` entry
(§7 reporting discipline; the loop is written out in `gfx90c_tuning_guide.md` §11).

### 8.1 LDS bank conflicts and padding

- **Which side dominates?** §2.1 assumes a column read of a row-major LDS tile,
  but never verified whether read or write, TLU or transpose, emits the
  conflicting `ds_read`/`ds_write` pattern in our kernels. Probe: dump the
  emitted assembly for a T-cell winner and count `ds_read`/`ds_write` widths and
  strides. Prediction to test: the pad ranking holds only if the transpose-read
  side dominates. **check** until the dump exists.
- **Does the phase-width model matter here?** The §2.2 table is identical under
  the 32-lane/b32 and 8-lane/b128 phase models *because the pattern is uniform*;
  a non-uniform access pattern would separate them. Probe: a microbenchmark over
  `ds_read_b32` vs `ds_read_b128` at pad 0/1.
- **Is the pad grid the whole design space?** §2.3 shows `LdsBlockSizePerPad`
  (periodic/XOR swizzle) is rejected in VALU mode, so only scalar per-row
  `LdsPadA/B` exists. Open: whether Tensile's periodic padding could be mimicked
  by a non-uniform per-row scheme at all — currently **no forwarding path**, so
  the `{0,1,2,4}` grid is the confound-free design space. Do not assume a richer
  swizzle is reachable without first checking `config_writer`'s forwarded set.
- **Pad × `PrefetchLocalRead` interaction** — pads change the LDS row stride that
  `PLR` reads; §2 never crossed the two. Same for pad × `PGR` (§4: PGR=1 doubles
  the footprint, so a pad that fits at PGR=0 may not at PGR=1).

### 8.2 Occupancy and wave quantization

- **Is 1-instruction-per-4-cycles-per-wave the right model for gfx90c FMA?** §3.2
  derives the ≥4-wave rule from a GCN1-era source. Probe: a VALU-bound
  microbenchmark holding `V` constant and varying resident waves. If gfx90c
  dual-issues independent `v_fma` on the same SIMD, the saturation point moves
  and the "target `V ≤ 64`" rule needs restating.
- **What binds per cell — VGPR or LDS?** §3.3 gives both limiters but no per-cell
  verdict. `python3 -m oto.harness.occupancy_audit` (see
  `potential_configs.md` §5) is the tool; the open question is which cells
  are LDS-bound at the current winner geometry (candidates for a smaller
  `DepthU`/`MacroTile`) versus VGPR-bound (candidates for `PGR=0`).
- **Does the complex `V` regression come from accumulators or the LDS path?**
  Measured `Z` `TT4×4` = 167 VGPR vs `S` `TT4×4` = 47 (§3.1/§6): the weight-8
  accumulator explains 128 of it; the remaining ~39 is the unexplained slice
  worth attributing before spending a run.

### 8.3 Complex GEMM strategies

- **Is there a native split-complex problem type in this Tensile checkout?**
  §5 lists split-complex as the last-resort ladder rung (Group D) but leaves the
  feasibility **check** open. Probe: grep the problem-type registry for a
  split-complex `OperationType`/layout before assuming call-level decomposition
  into four real GEMMs.
- **Would 3M (Gauss) actually help here?** §5 says 3M reduces arithmetic, not
  bytes; the complex wall (§5, `potential_configs.md` §3) is diagnosed as
  memory/occupancy, so 3M's expected win is *conditional* on the wall being
  VALU-side. Probe: only after pads/PGR/NLCA land, compare the residual gap to
  the 3M instruction-count saving.
- **Is the complex wall memory-bound or issue-bound?** CC ≈ 290–318 vs a 1613
  theoretical; ZZ ≈ 21–24 vs 101. The four-`v_mac_f32` MAC is irreducible (§4),
  so the shortfall is claimed to be memory/occupancy. The falsifier: a
  compute-only complex microbench at the same `V` that still misses the roof.

### 8.4 APU memory topology and `StaggerU`

- **Does the dGPU channel model transfer?** §4 flags the "16 channels × 256 B"
  `StaggerU` rationale as a gfx803/900/906-era comment **check**. The APU has a
  different L2/channel topology, and `StaggerUStride=256` landing in a "fresh
  channel" may be false here. Probe: sweep `StaggerUStride` on one cell, judge
  within-run, and record the winner's delta in `kernel_db.json`; if no stride
  moves the measured time (beyond the ±2 % tie band), the channel model does not
  apply.
- **Where is the L2/DRAM boundary?** §3 uses a 42 GB/s effective roofline from
  one GEMV anchor. Open: whether the same number holds for the decode/batched
  shapes (the shipped-suite classification in `gfx90c_theoretical_limits.md` §4
  assumes it does).

### 8.5 Tensile mechanics under the pinned checkout

- Every `Tensile/*.py:line` citation here is against the pinned checkout
  (`occupancy.py` names commit `e8a8999e`). Open: whether any cited knob's
  semantics changed in that pin (the backwards `StaggerUStride` gate was one such
  drift, fixed 2026-10-09) — re-verify a line before trusting a paragraph that
  depends on it.
- **`2M` (Caday) and the unused reduction algorithms**: named in
  `gates/assembly.py`'s accounting but with no forwarding path. Open whether any
  is expressible here at all; until then they are background, like StreamK.

### 8.6 Measurement integrity and cross-SKU porting

- **Clock suppression**: the newest run measured at 1.175 GHz
  (`native_clock_coverage: 0.53`, ≈1.53× slow; `knowledge_base.md` M4). Open:
  whether pinning sclk (~1400 MHz) reproduces within-run *rankings*, not just
  within-run *deltas* — the portability question behind §6's "rankings transfer
  better than values".
- **Device-keyed warm starts**: §6 cites the DevConf finding that caches must be
  keyed by device **check**. Open: whether a gfx900/gfx90c cache keyed only by ISA
  is safe given the LDS-pad and clock cliffs this doc documents — evidence says
  no; the experiment is a replay of a foreign winner on this box under M4 rules.

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
  `potential_configs.md` §1/§10.2

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
- `gfx90c_tuning_guide.md` (M1–M4 vocabulary, knob surface), `potential_configs.md` §8/§9/§10/§12 (experiment groups, steal, split-complex, queue), `gfx90c_theoretical_limits.md` (ceilings), `knowledge_base.md` §7/§10/§11 (data law, measured context), `oto/tensile/gates/vgpr_model.py` + `oto/tensile/gates/occupancy.py` (gates, LDS/VGPR budgets, the three byte tables), `oto/tensile/gates/loads.py` + `oto/tensile/gates/assembly.py` (load divisibility / 16-B cap / class rules), `oto/tensile/config_writer.py` (`FORWARDED_GROUP_C_KNOBS`), `complex_gemm_research_brief.md` (complex-MAC accounting + split routes), `changelog.md`

**Pass-2 Tensile-source anchors.** The per-knob upstream URLs (Tensile `Common.py`
line ranges, Debian TensileLite `Solution.py`, PR #10847, release notes) are in the
raw pass-2 corpus: `archive/corpus2.pass2_20261014.md` Appendix A. Those links point
at upstream `develop` and version-drift; the authoritative anchors for *this*
project are the pinned local files, cited inline in §9.2/§9.3 and
`knowledge_base.md` §7.1–§7.2 (`Tensile/Common.py`, `Tensile/SolutionStructs.py`).


## 9. Do not cite — unverified claims (folded from `archive/corpus.pass1_20261014.md` §4, 2026-10-14)

`corpus.md` carried a list of claims its author could not confirm. That list is
now here, because a "do not cite" list is research content and must live with the
research, and because `corpus.md` is being reduced to a pointer. **Citing an entry
here is a defect.** Each row states what was actually found, so a future search
does not repeat the work.

| Claim that circulates | What is actually known |
|---|---|
| *"Tile: A Faster Tiling Approach for AMD GPUs"* (ASPLOS'20) | Not located in ACM DL or IEEE Xplore under that or a near title. The project's own tile search is AMD-specific enough that this paper would be the primary reference if it exists. **Do not cite.** |
| "MI250-optimal config on A100 drops to ~7% of A100-optimal" | The 7% is not in arXiv:2505.03780. The paper evaluates Triton flash-attention kernels across SKUs and reports **>=20%, up to an order of magnitude**. Cite the paper's own figure. |
| "142k CLBlast tuples, 5 GPUs, per-device dynamic range 1.8x-13.2x" | The parameterised statistics are not verifiable from arXiv:2507.15277's abstract. The paper's qualitative thesis — that per-device tuning is required — is citable. |
| "ISC 2026 CUTLASS FP8: 1.00 waves/SM, 14% achieved occupancy" | Datapoint not located in accessible proceedings. |
| "PERKS (SC'23) gives 1.15x-1.4x on gfx90c" | PERKS is dGPU/NVIDIA persistent-kernel work. **No gfx90c APU data exists for it.** Cite it as a technique, never as a gfx90c measurement. |
| "gfx1151 `auto` DPM pinned at 1100 MHz; `profile_peak` gave +37.8%" | No primary source verified for gfx90c. It illustrates the DVFS mechanism and nothing more; `knowledge_base.md` §8.3 is the project's own protocol. |
| COSTA, FASTEST, BASS, BEST, Pyramid, MagicLine, SeerNN, PlanGen, GemmLab, Charo analytical GEMM, Fugerite et al. | Bibliographic ghosts **in this corpus**: none could be verified to exist as cited. Treat as folklore until independently located. |
| A universal "2 waves/SIMD is the right occupancy target" | Not a law. The project's own measurement puts the corpus **median** at 2 waves/SIMD (`gfx90c_theoretical_limits.md` §7.1), which is a description of what happened, not a target. |
| "AMD's shipped Vega solutions are systematically small-tiled" | **Resolved, and the answer is no.** AMD's shipped vega10/vega20 solution files contain MT128x16 (FP32), MT064x064 (FP64), MT016x016 (FP16) *in the same library* — there is no uniform small- or large-tile bias. AMD's *rank-1* solutions are small (see `potential_configs.md` §6 Route A), but the library spans three orders of tile area, so "AMD prefers small tiles" is not a supportable generalisation. |

### 9.1 What `corpus.md` contributed that this file did not have

Kept because it is the only recorded evidence, and it is AMD's own tuning for the
sibling part — the ground truth for the spoof-steal route:

| family | shipped file | rank-1 MacroTile | ThreadTile | DepthU | WorkGroup | VW | BufferLoad | PGR | PLR | APM | MaxOcc |
|---|---|---|---|---|---|---|---|---|---|---|---|
| FP32 | `vega10_Cijk_Ailk_Bljk_SB.yaml` | 128x016 | 4x4 | 16 | 32x4x2 | 4 | 1 | 0 | 1 | 1 | 40 |
| FP64 | `vega20_Cijk_Ailk_Bljk_DB.yaml` | 064x064 | 4x4 | 4 | 16x16x1 | 2 | - | - | - | 1 | 40 |
| FP16 | `vega20_Cijk_Ailk_Bljk_HB.yaml` | 016x016 | 2x2 | 8 | 8x8x1 | 2 | - | - | - | - | 40 |

Read the pattern, not the numbers. AMD's own FP64 rank-1 uses the **smallest**
accumulator (TT4x4) on a **mid-size** tile with **DepthU 4** and `StaggerU 32`.
That is the same shape as the project's own measured DD winner (32x32x8/TT2x2,
28 waves/CU) — two independent tunings of different hardware agreeing on
"small accumulator, mid tile". The FP32 rank-1's `DepthU 16` with `WG 32x4x2`
(a `LocalSplitU 2` workgroup) is also notable: **AMD itself uses LocalSplitU**,
which is the one wave-fill knob legal for this project's complex families
(`potential_configs.md` §8.1).

### 9.2 Pass-2 additions (`corpus2.md`, folded 2026-10-14)

`corpus2.md` answered a narrower brief (the eleven Tensile knobs the corpus
never *explicitly* set).
Its ledger rows that §9 above did not already carry:| Claim that circulates | What is actually known |
|---|---|
| ASPLOS'20 *"Tile"* prunes >85% of invalid candidate tiles via GCN inequalities (`LDS ≤ 64 KiB`, `VGPR ≤ 256`) | The paper's existence is unresolved (§9), so the pruning figure is unattributable. The *constraints* are real and already in the project's gates; the 85% is not citable. |
| OSDI'20 *Ansor* supplies a knob-sensitivity ranking (tile 60–70%, addressing 15–20%, pipeline 10–15%, fine scheduling <5%) | This ranking is not an Ansor result and no ablation of *these* knobs on gfx90c was located. Do not present it as measured sensitivity. |
| "142,782 CLBlast configurations on 5 GPUs" (arXiv:2507.15277) | The abstract's 142,782 are *device × input × parameter performance measurements*, not unique configurations. Cite the distinction. |
| A complex `GlobalSplitU>1` is impossible on gfx90c | It is a **Tensile assembly-path policy**, not a hardware limit; complex K-partials are mathematically reducible. The local gate (`potential_configs.md` §8.1) refuses it for C/Z, and that gate is authoritative — but do not state it as a hardware fact. |
| `NumLoadsCoalescedA/B` follows a simple byte/tile/thread predicate | The inspected path is a **derived-divisibility filter** over Tensile's own counts (`totalVectors`, `NumLoads`, `totalElementsPerp`, `enableGLTrX`), not a byte rule. A raw-input predicate under-approximates legality. |
| `LocalRead2A/B`, `GlobalRead2A/B`, `1LDSBuffer` have active effect | Upstream `Common.py` comments mark the paired-read path **"not used yet"**. The wiki defaults (`True`, `0`) do not prove emitted code; hold until local ISA confirms. |
| `NonTemporalA/B` bypasses L2 and eliminates thrashing | Non-temporal lowering is documented for GFX6–GFX9; the exact SLC modifier meaning and any gfx90c gain are unverified. Disabling useful reuse may *raise* DDR traffic. |
| A seven-CU raster / `WorkGroupMapping=7` maps block IDs to physical CUs | No source derives a non-power-of-two-CU mapping. Grid arithmetic (utilization, tail idle) is descriptive only — it cannot pick the fastest tile or split. |

### 9.3 Resolved by the project's own measurement (supersedes pass-2 caveats)

- **VGPR allocation granule.** The pass-2 sweep (`archive/corpus2.pass2_20261014.md` §3.3/§6) kept "4 vs 8/16" open and told
  readers to pass `granule` explicitly. The project closed it: granule **4** fits
  all ten rows of the AMD/ORNL GFX9 table, and
  `python3 -m oto.harness.asm_occupancy --check-calibration` reports **10/10**.
  Granule 8/16 mispredicts V = 28/36/84. `oto/harness/asm_occupancy.py` is the
  home; do not re-open.
- **Occupancy is not the problem it was framed as.** `corpus2.md` inherited the
  "low occupancy" framing. Measured over 5,757 emitted kernels: **LDS capacity
  binds 61.7%**, VGPR 22.4%, and only 2.1% run at ≤3 waves/CU
  (`gfx90c_theoretical_limits.md` §7.1).
- **`MaxOccupancy` rounding.** Confirmed floor (`DeviceLDS // N`) — see
  `knowledge_base.md` §7.2.
- **The knob "defaults" table.** The pass-2 sweep (`archive/corpus2.pass2_20261014.md` §2) reported wiki defaults with a
  "check local `Common.py`" caveat for each. Verified against the pinned checkout
  and recorded in `knowledge_base.md` §7.1.

### 9.4 Pass-3 follow-ups (`corpus3.md`, folded 2026-10-14) — post-run, not decked

`corpus3.md` (raw: `archive/corpus3.pass3_20261014.md`) answered the residual
brief. Nothing below is in the 310-phase run; each is a bounded trial for the
pass *after* it, gated on the run's evidence:

- **`DepthU=32` screen.** Legal space per corpus3 Q-D's lower bound
  (`2·DepthU·T·bpe` + padding + prefetch): DU32 fits one buffer at 64×64 for
  SS/HH/DD/CC, ZZ only under the project byte/budget pair; DU64 only
  small-tile/one-buffer SS/HH. Gate on exact LDS/VGPR metadata, start PGR=0,
  enforce `(DU_lds // LSU) % InnerUnroll == 0` with ≥1 iteration.
- **`LocalReadVectorWidth=2` bounded differential** (CC/ZZ only, and only if it
  changes the emitted width). Judge from VGPR/issue deltas, never the option value.
- **`StaggerU=16 + StaggerUStride=128` pairing** — only if StaggerU itself moves
  timings and emitted offsets in this run; mapping variants after that, if time.
- **Gate-hardening** (refuse instead of silently defaulting): `DirectToLdsA/B=True`
  failing the 4-byte guard, `ScheduleIterAlg ∈ {2,3}`, nonzero
  `StoreRemapVectorWidth` on non-MI. The writer forwards correctly since
  2026-10-14; these refusals belong in `validate_config` next.
- **Do-not-propose additions**: `StoreRemapVectorWidth` (refused w/o MI),
  `ScheduleGlobalRead`/`ScheduleLocalWrite` (no pinned writer use — ISA-diff
  preflight first), `PersistentKernel` (unforwarded), `DirectToLds` on CC/ZZ/DD,
  WGM=7/14 on short grids. Homes: `knowledge_base.md` §7.2 + §8.4.
