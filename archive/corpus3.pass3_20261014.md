# `corpus3.md` — residual Tensile research, pass 3

**Scope.** Source-first review of only Q-A through Q-F. Hardware facts and project measurements in the research brief are accepted without re-derivation. All Tensile implementation claims below are tied to the pinned [`ROCm/Tensile` commit `e8a8999e`](https://github.com/ROCm/Tensile/tree/e8a8999e); current-upstream behavior is not substituted. `VERIFIED` means the pinned source or cited primary methodology was read; `PARTIAL` means the cited report is incomplete or the conclusion is version-/path-dependent; `REASONING` is a prediction to test, not a result measured on gfx90c.

## Executive summary

Three source findings should change the remaining decisions. **First, `DirectToLdsA/B` cannot help CC/ZZ or FP64 on this commit:** its gfx9-compatible assembly path requires a single 4-byte global load, while C/Z and FP64 elements exceed four bytes even at vector width one; it also refuses `LocalSplitU>1`. Treat it as a possible VGPR-staging reduction only for legal real-data cases, and expect little occupancy change where LDS remains the binding resource. **Second, WGM=7 or 14 is syntactically legal, but WGM is a two-dimensional output-tile traversal block height, not a CU count.** For 256×192 and the large tiles in the winning deck, the output grid is often shorter than 7 in the mapped dimension, so the “match the raster to seven CUs” idea has no established physical basis and may not change traversal at all. **Third, several schema knobs are not useful search dimensions for this FMA-only path:** `StoreRemapVectorWidth` is rejected without matrix instructions; `ScheduleIterAlg` 2/3 is rejected on non-MI assembly; `ScheduleGlobalRead` and `ScheduleLocalWrite` are accepted in schema but no direct use of those names was found in the pinned assembly writer. The code comment says `AggressivePerfMode=2` caps LDS occupancy, but a matching mode-2 implementation was not found in the pinned writer/solution validation, so the cap should be called unconfirmed until a generated LDS allocation proves it.

---

## Q-A. `LocalReadVectorWidth`, `StoreVectorWidth`, `DirectToLdsA/B`

### `LocalReadVectorWidth`

**Resolution — `VERIFIED`.** In `Solution.getSolution`, `LocalReadVectorWidth == -1` resolves to `MIInputPerThread` for a matrix-instruction kernel and to `VectorWidth` otherwise. Since gfx90c in this project has no matrix instructions, the default effective value is the solution’s `VectorWidth`, not an architecture-specific constant. Source: [`SolutionStructs.py` lines 3310–3315](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3310-L3315); schema/domain and semantics in [`Common.py` lines 1165–1174](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L1165-L1174).

The pinned common-parameter comments specify that width 1 cannot be used for half precision and describe wider local reads as particularly relevant to `TransposeLDS` / matrix-instruction scheduling. The special guards that permit `LocalReadVectorWidth > MIInputPerThread` are matrix-instruction-only; gfx90c has no route into those allowances. `TransposeLDS=1` itself is rejected when matrix instructions are disabled, and also requires at least one of `TLUA` or `TLUB` to be false. Sources: [`Common.py` lines 1165–1174](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L1165-L1174); [`SolutionStructs.py` lines 3594–3600 and 4102–4107](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3594-L3600).

**Complex-family prediction — `REASONING`.** Setting `LocalReadVectorWidth=2` when the winner currently derives a larger width is legal to test for the normal non-MI path, provided the effective vector/load geometry remains legal. It does not reduce the accumulator count implied by `ThreadTile`; CC/ZZ accumulators are persistent live state and are a substantial component of register pressure. Narrower reads may change temporary operand packing, offset progression, local-read instruction count, and live ranges. They can therefore lower, preserve, or increase the measured VGPR count; source alone does not support a deterministic “2 saves registers” claim. Inspect emitted VGPR/SGPR counts and local-read ISA before interpreting a timing shift. A move to more numerous narrower LDS reads can also add issue work to an instruction-bound complex loop.

### `StoreVectorWidth`

**Resolution — `VERIFIED`, with a non-MI caveat.** The schema comment says `-1` nominally means `StoreVectorWidth = VectorWidth`, but explicitly states that when `MatrixInstruction == None`, the derived `gwvw` takes precedence. Thus `-1` is not a self-contained promise of an exact store width on this FMA path: the emitted global-store width is the solution’s derived output-width (`gwvw`) after the other layout/store rules run. Source: [`Common.py` lines 1192–1195](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L1192-L1195). The live schema includes widths 1, 2, 3, 4, 6, 8, and 16; legality and the actual selected width must be checked after solution construction rather than inferred from the schema alone.

**Prediction — `REASONING`.** Do not prioritize this knob as a general CC/ZZ arithmetic fix. Store width affects the epilogue, not the four-real-FMA complex MAC core. Test explicit widths only if stores account for a meaningful fraction of kernel time, the writer actually uses the override in the emitted code, or measurements show a large store-address/store-instruction cost. For large output tiles with an issue-bound inner loop, this is a lower-priority axis than `InnerUnroll` or a genuine address-generation reduction.

### `DirectToLdsA/B`

**Mechanism — `VERIFIED`.** The pinned comments say Direct-to-LDS removes the global-to-LDS staging registers (`G2L` VGPRs), can reduce load latency, and replaces the local-write offset with an SGPR. It therefore bypasses *VGPR staging* for operand movement; it does not eliminate the LDS tile or its capacity requirement. A source comment cites a possible 33-VGPR saving for a particular 8×8 ThreadTile with global prefetch, but that is an example for another configuration, not a gfx90c/CC/ZZ measurement. Source: [`Common.py` lines 644–660](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L644-L660).

**Hard constraints — `VERIFIED`.** For this non-MI target, `isDirectToLdsDoable` refuses the choice unless `GlobalLoadVectorWidth × bytesPerElement == 4` bytes; the LDS loads use 4-byte operations. The guard also requires whole-wave workgroups, matching LDS/global-load geometry, rejects `TLU == UnrollMajorLDS`, rejects `LocalSplitU > 1`, and imposes additional restrictions on load coalescing, padding, and prefetch modes. Direct-to-LDS with `TLU=False` is documented to require `TransposeLDS=1`, but the same pinned solution validation restricts `TransposeLDS` to matrix-instruction kernels. Hence the TLU-free form is not a practical non-MI option on this commit. Sources: [`SolutionStructs.py` lines 2358–2415](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L2358-L2415), [`SolutionStructs.py` lines 2430–2484](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L2430-L2484), and [`SolutionStructs.py` lines 4102–4107](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L4102-L4107).

**Datatype consequence — `VERIFIED` from the guard plus the brief’s datatype sizes.** At `GLVW=1`, FP64 inputs are 8 bytes, complex-single inputs are 8 bytes, and complex-double inputs are 16 bytes. Each exceeds the guard’s 4-byte requirement, so `DirectToLdsA/B=True` is not legal for DD, CC, or ZZ in this writer path. FP32 can satisfy the width guard at GLVW=1; packed FP16 can satisfy it at GLVW=2, subject to the remaining guards. This is a hard feasibility result, not a performance prediction.

**Prediction — `REASONING`.** On the legal SS/HH cases, DirectToLDS may help when G2L VGPR staging is material or VGPRs bind occupancy. It should not be expected to improve the 61.7% LDS-capacity-bound portion of the corpus via residency: the LDS tile stays, and DirectToLDS adds alignment/layout restrictions. Since the measured CC/ZZ winners are already issue-bound, it is not a candidate for those families under the pinned 4-byte constraint.

---

## Q-B. Scheduling and persistence

| Knob | Pinned-source finding | Implication for non-MI gfx90c | Confidence |
|---|---|---|---|
| `PersistentKernel` | It exists in `Common.py`, default 0; the assembly writer contains a persistent-loop path (`openPersistentLoop`, final loop control). The project brief says this port does **not forward** the knob to the writer, so the target gate cannot currently exercise it. In upstream Tensile source it is also disabled for Assembly when `GlobalSplitU != 1` or `WorkGroupMapping < 0`. [`Common.py` L1468–1469](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L1468-L1469); [`KernelWriterAssembly.py` L3462–3469](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/KernelWriterAssembly.py#L3462-L3469); [`SolutionStructs.py` L2903–2915](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L2903-L2915). | Not a candidate in this port absent an explicit forwarding change. A true persistent grid would distribute logical tiles across a fixed worker grid and loop through them; it changes the granularity of tail work, but cannot eliminate the final partial assignment. If there are `P` persistent workers, the final round is governed by `G mod P`; only if the implementation launches one worker per CU is `P=7`, so the remainder remains `G mod 7`. | `VERIFIED` upstream path; `VERIFIED` as port limitation from project brief; `REASONING` for load balancing |
| `ScheduleGlobalRead` | Present in schema and referenced by a special-case legality rule, but no direct reference to this parameter was found in the pinned `KernelWriterAssembly.py`. The corresponding writer search for the literal name returned no match. [`SolutionStructs.py` L3968–3970](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3968-L3970). | Treat as parsed/legality-visible but not proven to alter non-MI Assembly code. Verify by comparing generated ISA for paired configurations before assigning it benchmark budget. No confident prediction for complex MAC throughput. | `PARTIAL` |
| `ScheduleLocalWrite` | Used by solution validation around the `1LDSBuffer` constraints; no direct reference to the literal parameter was found in the pinned Assembly writer. [`SolutionStructs.py` L3759–3765](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3759-L3765). | Same rule: do not treat a YAML change as an effective scheduling change until its emitted ISA differs. It is unlikely to fix an issue-bound complex loop if the generated order is unchanged. | `PARTIAL` |
| `ScheduleIterAlg` | For `KernelLanguage=Assembly` with matrix instructions disabled, `SolutionStructs.py` explicitly rejects values 2 and 3, with the message that SIA2/SIA3 only support MatrixInstruction. Modes 0 and 1 survive this particular check. [`SolutionStructs.py` L2865–2869](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L2865-L2869). | The viable space is 0/1, not 0–3. Because a literal writer use for all mode details was not established beyond other special-case paths, only test 0 vs 1 after confirming the emitted instruction ordering. A mode that merely rearranges loads/stores will not necessarily reduce the non-FMA instruction count in complex MACs. | `VERIFIED` rejection of 2/3; `PARTIAL` effect of 0/1 |
| `StorePriorityOpt` | The Assembly writer emits `s_setprio 0` in the corresponding store/prefetch path when enabled; the MAC-generation path also uses `s_setprio 1` while processing MAC instructions for nonzero `AggressivePerfMode`, then resets priority to zero. [`KernelWriterAssembly.py` L7160–7164 and L14886–14888](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/KernelWriterAssembly.py#L7160-L7164). | This is an actual instruction-level scheduling-priority toggle, not a tile-layout change. It could affect arbitration/latency under contention, but has no source-backed reason to reduce the number of complex arithmetic/addressing instructions. Low-priority for an issue-bound kernel unless generated code and A/B timing show a reproducible effect. | `VERIFIED` mechanism; `REASONING` performance |
| `StoreRemapVectorWidth` | The solution validator rejects a nonzero store-remap width when `BufferStore` is false and explicitly rejects it when `EnableMatrixInstruction` is false. [`SolutionStructs.py` L3861–3875](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3861-L3875). | Inert as a candidate for all five non-MI families on gfx90c. Do not spend tuning time on it. | `VERIFIED` |

**Persistent-tail interpretation — `REASONING`.** With an ordinary grid of `G=ceil(M/MT_M)×ceil(N/MT_N)` CTAs, the last wave of CTA dispatch leaves `G mod 7` CUs without another CTA if `G` is not divisible by seven. A persistent launch with `P` workers amortizes this across worker loops; it can reduce load imbalance but not create work or guarantee that the last logical tile round is divisible by seven. Most importantly, the stated port does not pass `PersistentKernel` through, so this is not a tuning knob available to the immediate run.

---

## Q-C. Non-power-of-two `WorkGroupMapping`

**Acceptance — `VERIFIED`.** The pinned live schema declares `WorkGroupMapping = list(range(-1024, 1024+1))`; there is no power-of-two-only domain. The Assembly writer’s blocking (`WorkGroupMappingType == "B"`) path uses `abs(WorkGroupMapping)` and computes a magic divisor for `absWgm`, rather than assuming a power-of-two shift. Values 7 and 14 are therefore syntactically within the declared domain and enter the general mapping code when positive and greater than one. Sources: [`Common.py` L880–894](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L880-L894), [`KernelWriterAssembly.py` L3826–3853](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/KernelWriterAssembly.py#L3826-L3853), [`SolutionStructs.py` L2896–2902](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L2896-L2902). This is source-level acceptance, not a claim that the project’s separate gate will pass them without change.

**What the number means — `VERIFIED`.** WGM is the height of a rectangular traversal block in the output matrix’s J dimension; the traversal advances across I, then wraps to the next J row. The source’s serial mapping formula is `wgSerial = wg0 + (wg1 % WorkGroupMapping) * nwg0`. Therefore WGM=7 is not “one tile per CU for seven CUs”; the hardware scheduler independently distributes the resulting workgroups. WGM=7/14 changes the ordering/raster of output tiles only when the problem’s tile grid is large enough for those block heights to matter. Source: [`Common.py` L880–893](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L880-L893).

**Small cells — `REASONING`, not measured.** For 256×192, `MT=128×128` gives a 2×2 grid (`G=4`); `MT=64×64` gives a 4×3 grid (`G=12`). Both have fewer than seven tile rows in the dimension controlled by the WGM block height. WGM=7 and 14 are thus unlikely to improve CU fill for these examples; in such short grids, they may induce the same or nearly identical traversal as other WGM values above the grid height. WGM=1 remains the natural no-remapping baseline, while 4/8 are already in the project’s deck. A WGM experiment is justified only where generated mapping differs and output-tile order plausibly changes cache locality. There is no verified published rule equating WGM to physical CU count for an APU, and no verified publication found for seven-CU raster design.

**Implementation check.** For any proposed WGM, compare the generated address/remapping instructions or a tiny grid mapping trace for `G` known tiles. Source accepts 7/14; it does not imply those choices reduce the tail or improve performance.

---

## Q-D. `DepthU=32/64`: feasibility and tradeoff

**Direct answer — no universal `DepthU=32` or `64` rejection exists in the pinned schema.** The `DepthU` selection logic checks whether there is at least one loop iteration after dividing `_DepthULds` by `LocalSplitU` and `InnerUnroll`, and continues searching if a candidate fails the derived load-tile rules. After resource calculation, an LDS allocation exceeding `MaxLDS` is explicitly rejected. `LoopUnroll` is formed from `_DepthULds // LocalSplitU` and then divided by `InnerUnroll`; the generator should enforce exact divisibility so integer truncation cannot create a malformed candidate. Sources: [`SolutionStructs.py` L3320–3345](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3320-L3345), [`SolutionStructs.py` L3483–3493](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3483-L3493), [`SolutionStructs.py` L3929–3941](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3929-L3941).

**Necessary candidate-generator rule — `REASONING` based on the source’s integer loop factorization.** Let `DU_lds = DepthU // DepthULdsDivisor`. For this non-MI family, use the exact state-derived `DepthULdsDivisor` from Tensile, normally 1 for the deck in question. Require:

```python
assert DepthU % DepthULdsDivisor == 0
DU_lds = DepthU // DepthULdsDivisor
assert DU_lds % LocalSplitU == 0
assert (DU_lds // LocalSplitU) % InnerUnroll == 0
assert DU_lds // (LocalSplitU * InnerUnroll) >= 1
```

The project’s stricter `DepthU % (LocalSplitU * InnerUnroll) == 0` rule is equivalent when `DepthULdsDivisor=1`. If future candidates can set another divisor, use `DU_lds` rather than silently applying that simplified rule to raw `DepthU`.

### LDS lower-bound arithmetic

For a square tile `MT_M = MT_N = T`, the unpadded single-buffer operand footprint is approximately

\[
L_{AB} \approx DepthU\,(MT_M+MT_N)\,bpe
              = 2\,DepthU\,T\,bpe.
\]

This is a lower-bound filter, not a substitute for Tensile’s exact `LdsNumElements`: LDS padding, layout, reduction scratch, and prefetch buffering can change the final allocation. The pinned source computes a final LDS size and rejects it when it exceeds `MaxLDS`; global prefetch level 1 requires twice the LDS staging space plus VGPR buffering. Sources: [`SolutionStructs.py` L3728–3768 and L3929–3933](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3728-L3768), [`Common.py` L462–470](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L462-L470).

For an illustrative `128×128` macro-tile, one LDS buffer, no padding, and the standard input-element byte widths in the problem brief:

| Family | `bpe` | `DepthU=32` footprint | `DepthU=64` footprint | Implication before padding/prefetch |
|---|---:|---:|---:|---|
| FP32 SS | 4 B | 32 KiB | 64 KiB | 64 already consumes the entire per-workgroup LDS budget; PGR=1 will exceed it |
| FP16 HH | 2 B | 16 KiB | 32 KiB | Both can fit one buffer; PGR=1 moves them to approximately 32/64 KiB |
| FP64 DD | 8 B | 64 KiB | 128 KiB | 32 consumes the whole budget; 64 is impossible at this tile |
| Complex single CC | 8 B | 64 KiB | 128 KiB | Same capacity boundary as DD, though performance is issue-bound for a separate reason |
| Complex double ZZ | 16 B nominal dtype width | 128 KiB | 256 KiB | Neither fits at `128×128` under this arithmetic; obey the project’s stated paired `BYTES_PER_ELEMENT` / `LDS_BUDGET` settings when running its actual legality gate |

For a `64×64` tile, these footprints are half the table values. Thus `DepthU=32` can plausibly fit at `64×64` for SS, HH, DD, CC, and some ZZ byte/budget pairs; `DepthU=64` can fit one buffer at `64×64` for SS and HH, and is at the 64-KiB boundary for DD/CC. Exact generated allocation still wins over this arithmetic. Do not alter the project-owned ZZ `BYTES_PER_ELEMENT`/`LDS_BUDGET` pair under the guise of this sweep.

### VGPR / issue implications

The source does not impose a datatype-wide rule that rejects `DepthU=32/64` solely because a tile’s VGPR estimate is high; the assembly writer builds its VGPR pool and occupancy from emitted state, with resource overflow checks. Deeper `DepthU` can reduce K-loop branch/update frequency and expose more independent work, but it increases operand staging and/or register live ranges depending on prefetch and `InnerUnroll`. It also increases LDS use linearly in the first-order model. On a corpus with median eight waves per CU and no scratch spills, the expected trade is **incremental loop overhead/ILP versus reduced LDS residency and longer live ranges**, not “more depth is always better.” The complex family’s known issue-bound behavior makes `DepthU=32` worth a bounded candidate test on a tile that stays well below the LDS cap; `DepthU=64` should be restricted to small-tile, low-buffering candidates where the generated kernel remains legal. These are `REASONING` candidates, not performance conclusions.

---

## Q-E. Conditional follow-ups

### (i) Only if `StaggerU` demonstrably moves performance

**Condition.** If the current `StaggerU` comparison is statistically indistinguishable from its baseline, do not launch a paired stride/mapping sweep: those factors cannot pay for themselves if the base transformation is ineffective or optimized away. If `StaggerU` changes timings and emitted offsets, then follow with one small interaction check: keep the current `StaggerUMapping` fixed, change `StaggerU: 32→16` with `StaggerUStride: 256→128`, and only afterward consider `StaggerUMapping` alternatives. `WorkGroupMapping` and staggering interact because one changes output-tile order and the other changes the starting summation offsets; the pinned comments say the stride is internally adjusted to a multiple of `DepthU × BPE`. Source: [`Common.py` L645–707 and L892–894](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L645-L707). The named PR #10847 example (gfx1100 WMMA, `StaggerU` 32→16 plus stride 256→128) is **`PARTIAL`** evidence for the pairing only; it does not predict a Vega/ gfx90c win: https://github.com/ROCm/rocm-libraries/pull/10847.

### (ii) `AggressivePerfMode=2` and its alleged two-wave LDS cap

**Status — `UNVERIFIED` in the pinned writer.** `Common.py` comments describe mode 0 as none, mode 1 as adding `s_setprio`, and mode 2 as adding `s_setprio` while modifying LDS to allow only two waves per SIMD. Source: [`Common.py` L1310–1313](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L1310-L1313). However, the pinned `KernelWriterAssembly.py` MAC-generation logic treats `AggressivePerfMode` as a truthy flag (`beAggressive = kernel["AggressivePerfMode"]`) and emits `s_setprio 1` / reset for any nonzero value; no explicit mode-2 branch was found in the relevant writer search. `SolutionStructs.py` also did not expose a mode-2 test in its LDS-occupancy path. Sources: [`KernelWriterAssembly.py` L7079–7146](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/KernelWriterAssembly.py#L7079-L7146), [`SolutionStructs.py` L3728–3768](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/SolutionStructs.py#L3728-L3768).

Do not tell the tuning agent that mode 2 definitely enforces two resident waves per SIMD on this commit. Confirm by generating a pair with `AggressivePerfMode=1/2` and comparing the writer’s allocated LDS (`LdsNumElements`/code-object LDS metadata) and emitted code. If the allocation is identical, the cap comment is stale or implemented outside the searched code path; if it differs, record the exact site/amount before assigning semantics.

### (iii) Read `PrefetchGlobalRead=0/1/2` outcomes on the complex winners

Pinned source states that PGR=1 requires twice the LDS space and VGPRs to buffer data from global memory to LDS; PGR=2 introduces another prefetch stage during the VGPR-to-LDS movement. Source: [`Common.py` L462–470](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L462-L470).

| If the run finds… | Interpretation to test next | What to inspect |
|---|---|---|
| **PGR=0 wins** | Added buffering/dispatch and longer live ranges cost more than the latency overlap. For a complex loop, this is consistent with an issue-bound kernel where extra pipeline work does not raise useful FMA issue rate. | LDS bytes, VGPRs, number of loads/waits and instruction count; ensure PGR=0 is not accidentally using a different legal path. |
| **PGR=1 wins** | One extra stage is sufficient to overlap global reads with inner-loop work; the PGR=2 stage likely adds resource or control overhead with diminishing latency benefit. | Whether the tile remains residency-equivalent after doubled LDS allocation; inspect emitted waits and G2L buffering. |
| **PGR=2 wins** | Longer-look-ahead latency hiding is important for this shape, and its overlap benefit exceeds added buffering/scheduling costs. This is evidence about that shape/clock/cache regime, not a universal PGR=2 rule. | Confirm the kernel remains legal, and correlate timings with LDS/VGPR metadata, load scheduling, clock state, and cache policy. |

All three interpretations are `REASONING` pending the run; none is a literature-derived speedup estimate.

---

## Q-F. Protocol for the 10-hour gfx90c run

This protocol is intentionally specific to the shared-memory, DVFS-sensitive APU. It combines AMD’s Max-Achievable FLOPs guidance with independent benchmarking cautions; neither source supplies a measured noise floor for this exact Ryzen system.

1. **Control and log the clock regime. `VERIFIED` mechanism, `REASONING` setup.** Before each phase, record `power_dpm_force_performance_level`, `pp_dpm_sclk`, GPU temperature, and the best clock telemetry available from `amd-smi`/ROCm-SMI. The kernel driver documents `manual`, `profile_peak`, `pp_dpm_sclk`, and profile modes; `profile_peak` disables clock/power gating and targets the highest clocks, while `manual` controls available DPM levels. Use a supported fixed-state/manual configuration if the APU driver exposes one; otherwise use a documented profile mode and record observed clocks rather than assume it worked. Do not assume a short kernel’s clock can be inferred from one slow polling sample. Sources: [Linux AMDGPU power/thermal controls](https://www.kernel.org/doc/html/latest/gpu/amdgpu/thermal.html), [AMDGPU driver source docs](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/pm/amdgpu_pm.c).

2. **Warm the APU before the measurement window. `VERIFIED` methodology, target-specific schedule `REASONING`.** AMD’s MAF method calls for thermally stable operation, representative nonzero/random-distribution data, cold caches, and a workload long enough to observe steady frequency. Its published experiment used an approximately 1-second large GEMM, with **25% warmup and 75% timed measurement** while the device approached its operating temperature. Use the same 25/75 split for each timed measurement block or each shape-phase, with repeated launches sufficient to make a 150-µs kernel measurable; do not literally use a single 150-µs sample as the 75% window. The MAF text notes frequency polling intervals can be hundreds of milliseconds, so clock logging should be interpreted per phase, not as per-kernel ground truth. Source: [AMD, Measuring Max-Achievable FLOPs, Part 2](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html).

3. **Use a blocked, randomized order with reference interleaves. `REASONING` supported by independent measurement guidance.** Block by datatype/problem-shape so comparisons use identical shapes, allocations, and cache protocols. Randomize the order of candidate configurations within each block rather than running every low-numbered knob choice first. Interleave the same reference kernel at regular intervals and at the beginning/end of blocks; a drifting reference is evidence that the block’s candidate timings share a clock/thermal/environment trend. Keep raw timing samples, report the median and spread, and repeat the full block if the reference trend materially changes. The independent 2026 high-fidelity GPU benchmarking write-up discusses clock, thermals, cache state, synchronization, warmup, and repeated measurements as confounders: https://standardkernel.com/blog/in-pursuit-of-high-fidelity-gpu-kernel-benchmarking/.

4. **Make cache treatment explicit by shape class. `VERIFIED` source guidance, `REASONING` threshold.** For a cold-memory regime, use a rotating data set or `FlushMemorySize` exceeding the relevant cache capacity; Tensile’s own code comments give the flush-count rule `flush_count >= 1 + cache_size / problem_memory_footprint` and warn that one global flush count may not evict data for much smaller shapes. In this project, classify problems by `A+B+C/D` footprint relative to the stated 1-MB L2. For footprints materially below 1 MB, measure cold and warm-L2 variants separately instead of unknowingly mixing them; for large shapes, rotate through buffers large enough to evict L2. Do not call these regimes equivalent. Source: [pinned `Common.py`, flush controls and cache caveats, L88–110](https://github.com/ROCm/Tensile/blob/e8a8999e/Tensile/Common.py#L88-L110); AMD MAF guidance above.

5. **Fix the floor-arm CC:256 telemetry record. `VERIFIED` as a project requirement.** For every timing record, carry `spoof_clock_sclk_hz` and a Boolean/present-missing flag for its coverage, plus the real clock source/value separately. For D1, compare the `CC:256` floor-arm row against the normal reference and the raw trace. Keep telemetry-derived “spoofed” SCLK out of any field presented as an actual measured hardware clock; if coverage is missing or the row’s clock cannot be tied to its trace, tag the record as telemetry-incomplete rather than using it to explain a timing win/loss. This is a measurement-integrity fix from the project’s own problem statement, not a literature claim.

6. **Quantify the local noise floor. `REASONING`, to be measured here.** Do not import a percentage noise floor from a different GPU. Measure the reference kernel repeatedly before and during the run under the same cache and clock conditions, then calculate its median, median absolute deviation (MAD), and block-to-block drift. Retain per-repeat timings for 150-µs to 80-ms kernels; use enough repetitions/queued launches so each timed sample overwhelms host-dispatch and timer granularity, then synchronize consistently. Record GPU temperature and clock snapshots at phase granularity, since the polling cadence cannot resolve each short launch. The reported 19 WIN / 18 TIE / 1 LOSS does not itself estimate noise unless the baseline repeat distribution is available.

### Minimal record schema for this run

`timestamp, phase, problem_id, dtype, shape_MNK, config_id, randomized_position, reference_flag, cache_mode, repeats, raw_times_us, median_us, MAD_us, sclk_source, spoof_clock_sclk_hz, spoof_clock_coverage, observed_sclk_min_median_max, temperature_min_median_max, power_dpm_force_performance_level, LDS_bytes, VGPR/thread, SGPR/thread, scratch_spill_bytes, code_object_id`.

The record keeps launch-time observations and code-object metadata linked, so a candidate cannot be called faster based on a clock excursion or a changed resource allocation alone.

---

## Adoption matrix

| Knob / group | Mechanism verified in pinned source? | Predicted family relevance | Direction / treatment | Confidence |
|---|---|---|---|---|
| `LocalReadVectorWidth` | Yes: `-1 → VectorWidth` for non-MI; no universal VGPR-saving rule | CC/ZZ possible only as an operand temporary/layout test; SS/HH/DD may show local-read instruction changes | Test 2 against default only when effective width changes; compare VGPRs and local-read instruction count | Mechanism `VERIFIED`; gain `REASONING` |
| `StoreVectorWidth` | Partial: nominal `-1 → VectorWidth`, but non-MI derived `gwvw` takes precedence | Likely epilogue-limited shapes, not complex MAC core | Deprioritize until emitted store width demonstrably changes | `VERIFIED` caveat; gain `REASONING` |
| `DirectToLdsA/B` | Yes: guard and staging bypass | SS and HH only under the 4-byte load and layout guards; not DD/CC/ZZ | Consider only legal SS/HH tiles; avoid `LocalSplitU>1`, validate LDS/VGPR delta | `VERIFIED` feasibility; gain `REASONING` |
| `PersistentKernel` | Upstream writer path exists; port forwarding absent per project brief | Any shape with grid imbalance, but currently unavailable | Do not include in current YAML sweep; a separate port change would be required | `VERIFIED` source + brief |
| `ScheduleGlobalRead` | No direct use found in pinned Assembly writer; validation path exists | Unknown on non-MI, including CC/ZZ | ISA-diff preflight; if unchanged, drop | `PARTIAL` |
| `ScheduleLocalWrite` | No direct use found in pinned Assembly writer; validation path exists | Unknown on non-MI; no evidence of complex issue reduction | ISA-diff preflight; if unchanged, drop | `PARTIAL` |
| `ScheduleIterAlg` | Yes: non-MI Assembly rejects 2/3 | All families, but 0/1 effect still needs confirmation | Limit test to 0/1 and inspect generated instruction ordering | `VERIFIED` rejection; `PARTIAL` mechanism effect |
| `StorePriorityOpt` | Yes: emits `s_setprio 0` in writer store path | Potential arbitration/epilogue effect; not a direct complex-MAC reduction | Low-priority A/B | `VERIFIED` mechanism; gain `REASONING` |
| `StoreRemapVectorWidth` | Yes: rejected when matrix instructions disabled | None for this FMA-only path | Remove from candidate list | `VERIFIED` |
| `WorkGroupMapping=7/14` | Yes: domain permits; general integer-divisor raster path | Only grids with enough output-tile rows/columns; unlikely for MT128 on 256×192 | Use only if generated mapping differs and shape grid is large enough | `VERIFIED` legality; gain `REASONING` |
| `DepthU=32/64` | Yes: resource/loop search, not a universal depth cap | SS/HH most feasible at larger tiles; DD/CC only at smaller tiles or low depth; ZZ depends on project-owned byte/budget pair | Start with DU32 on modest tiles and PGR=0; try DU64 only where exact LDS/VGPR metadata fits | `VERIFIED` resource checks; gain `REASONING` |
| `StaggerUStride` / `StaggerUMapping` | Yes: stagger mechanism and mapping documented in pinned schema | Potential cache/DRAM-layout effect; no seven-CU recipe | Conditional follow-up only if StaggerU itself changes timing and emitted offsets | `VERIFIED` mechanism; PR example `PARTIAL` |
| `AggressivePerfMode=2` LDS cap | Comment says cap; explicit mode-2 branch not located in writer/solution validation | Cannot predict without confirming allocation behavior | Treat mode-2 cap as unconfirmed; diff LDS metadata against mode 1 | `UNVERIFIED` cap |
| `PrefetchGlobalRead=0/1/2` | Yes: LDS/VGPR pipeline comments | All types; issue-bound CC/ZZ must prove extra overlap pays for buffering | Interpret the winning mode via LDS, VGPR, load/wait, and instruction deltas | `VERIFIED` mechanism; gain is measured only in run |

---

## Do not cite / unresolved

1. **Do not cite `AggressivePerfMode=2` as a verified two-wave/SIMD cap on this exact commit.** It is documented in `Common.py`, but an explicit cap implementation was not located in the pinned `KernelWriterAssembly.py` or `SolutionStructs.py` path. Compare actual LDS allocation for modes 1 and 2 before repeating the claim.
2. **Do not assert `LocalReadVectorWidth=2` saves VGPRs in CC/ZZ.** The source confirms default resolution and shows how the knob affects the code path, not the target-family allocation delta. Accumulator VGPRs are not eliminated by narrower reads.
3. **Do not claim DirectToLDS helps CC/ZZ or DD.** The pinned non-MI validator’s exact 4-byte global-load guard excludes their 8-/16-byte input elements at minimum width.
4. **Do not claim WGM=7 is a natural optimum for a seven-CU device.** The documented WGM is an output-tile traversal dimension; the number has no direct CU binding.
5. **Do not claim `ScheduleGlobalRead` or `ScheduleLocalWrite` alters the non-MI emitted assembly merely because the parameter exists in `validParameters`.** Their direct use was not found in the pinned assembly writer; require an ISA diff to establish whether they take effect through another path.
6. **No gfx90c-specific measured performance gain was found for WGM=7/14, `LocalReadVectorWidth=2`, `StorePriorityOpt`, or deep `DepthU`.** All direction statements are test priorities, not source-backed speedups.
7. **No independent publication was found that prescribes a WGM for a seven-CU integrated GPU, or a universal number of waves/SIMD for a non-MI GEMM.** Use the project’s own randomized, clock-controlled results rather than citing a universal target.

---

## Concrete changes to the next pass

- Keep `LocalReadVectorWidth=2` as a bounded differential for CC/ZZ only if it changes the emitted width; judge it from VGPR and issue-count differences, not the option value alone.
- Remove `StoreRemapVectorWidth` from the active candidate set for non-MI Assembly: the pinned validator rejects it.
- Do not allocate a CC/ZZ/DD candidate to `DirectToLdsA/B`; it fails the pinned 4-byte load-width rule.
- Restrict `ScheduleIterAlg` candidates to 0 and 1 for this non-MI Assembly gate; 2 and 3 are explicitly refused.
- Treat `ScheduleGlobalRead` and `ScheduleLocalWrite` as no-effect until an emitted-ISA comparison proves otherwise.
- Hold `PersistentKernel` until the local port actually forwards the value; upstream support is not enough.
- Only trial WGM 7/14 when the mapped tile-grid dimension reaches the block height and the resulting mapping differs from the current WGM code.
- Screen `DepthU=32` first on tiles whose unpadded LDS lower bound leaves headroom; reserve `DepthU=64` for small tiles and one-buffer cases.
- Enforce `(_DepthULds // LocalSplitU) % InnerUnroll == 0` in the generator and require at least one inner-loop iteration.
- If `StaggerU` proves effective, try the single cited pairing `StaggerU=16`, `StaggerUStride=128` as a follow-up, then vary mapping only if there is time.
- Do not interpret `AggressivePerfMode=2` as occupancy-capped until mode 1/2 LDS metadata differs.
- Run PGR 0/1/2 with reference-kernel interleaves and log emitted LDS, VGPR, timing, SCLK source/coverage, and temperature for every phase.
- For D1, add `spoof_clock_sclk_hz` coverage as an explicit field and segregate telemetry-incomplete floor-arm records from clock-based conclusions.
