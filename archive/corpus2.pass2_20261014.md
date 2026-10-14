# `corpus2.md` — Unified Tensile Knob Research, Pass 2

## 0. Scope, provenance, evidence labels

Documentation/source synthesis, **not a GPU experiment**. Target: AMD `gfx90c`, 7 CUs, shared system memory, 1 MiB L2, nominal 64 KiB LDS/CU. Project brief values accepted as inputs: prior audit of 5,757 kernels, clock behavior, performance ceilings, local Tensile v4.44 behavior, and 61.7% LDS-capacity-bound kernels. No knob gain is measured here.

Main inspected code references: live `develop` Tensile `Common.py`; Debian TensileLite `Solution.py` from hipBLASLt 7.2.4. Neither is the exact project commit `e8a8999e`; local-fork legality is marked separately. One source pass made 3 searches and 1 page fetch but could not open `Common.py`, `Solution.py`, or `KernelWriterAssembly.py`; it relied on snippets/wiki/release notes for most questions.

**Evidence labels:** `VERIFIED` = source text inspected; `PARTIAL` = excerpt, release note, other-version implementation, or incomplete source; `UNVERIFIED` = not established for the target/path; `REASONING` = inference. Confidence labels in older drafts are retained where they differ, but should not override specific source limitations below.

## 1. Executive synthesis

1. **Test `UseSgprForGRO` conditionally.** Detailed upstream comments describe one VGPR base plus multiple SGPR global-read offsets, not every address moved to SGPRs. It requires `BufferLoad=1`, disallows `ShiftPtr`, and may require compatible `Assert*ElementMultiple` guarantees or `GlobalReadVectorWidth=1`. Potential VGPR relief trades against SGPR/address-instruction pressure. The earlier draft claims 4–8 VGPRs/thread saved and 8–16 extra SGPRs/wave, but those exact counts and “all uniform addresses move” are not verified for local v4.44. Test on 63-VGPR ZZ first; inspect ISA and resource metadata.
2. **Treat prefetch as a resource trade, not free latency hiding.** `PrefetchGlobalRead` may add a second LDS staging buffer and VGPR state; `PrefetchLocalRead` raises buffered VGPR/live-range demand. A large fraction of the measured corpus is already LDS-capacity-bound. Measure code-object LDS/VGPR allocation and runtime together.
3. **Screen dependencies, not eleven independent factors.** `UseSgprForGRO` depends on `BufferLoad`/pointer-shift legality; `StaggerU` interacts with `WorkGroupMapping`; `NumLoadsCoalescedA/B` depends on Tensile-derived load geometry; `InnerUnroll` changes loop factorization; prefetch affects resource budgets.
4. **Do not infer target optima from 7 CUs alone.** CU-grid quantization matters most for small output grids. `LocalSplitU` partitions summation work inside a workgroup and does not multiply output workgroups. `GlobalSplitU` multiplies the output grid but adds atomics or workspace/reduction traffic.
5. **No defensible speedup percentage exists from these sources.** A former draft projected FP32/FP16 gains of 10–18% and C/Z gains of 20–35%; those forecasts conflict with the later source audit, which found no target-specific ablation. Preserve as an unvalidated historical hypothesis only, not as a forecast or prior.

## 2. Defaults and sources consulted

An obsolete Tensile wiki table (banner dated Dec. 2024) reports these defaults; local v4.44 may differ. “Unset” therefore does not mean “off.”

| Parameter | Wiki default reported in partial pass | Validation note |
|---|---:|---|
| `MaxOccupancy` | `40` | Check local `Common.py` |
| `AggressivePerfMode` | `1` | Check local `Common.py` |
| `InnerUnroll` | `1` | Check local `Common.py` |
| `FractionalLoad` | `0` | Check local `Common.py` |
| `UseSgprForGRO` | `-1` | `-1` may invoke an auto heuristic; exact local choice unknown |
| `NumLoadsCoalescedA/B` | `1` | Check local `Common.py` |
| `PrefetchGlobalRead` | `True` | Three complex winners reportedly set it `False`; confirm explicit YAML vs default |
| `PrefetchLocalRead` | `1` | Check local `Common.py` |
| `LocalRead2A/B` | `True` | Current source comments say relevant paired path “not used yet”; active effect unverified |
| `GlobalRead2A/B` | `True` | Same live-path caveat; wiki default only |
| `StaggerU` | `32` | Check local `Common.py` |
| `StaggerUStride` | `256` | Check local `Common.py`; old rationale is GFX8/gfx900/gfx906, not gfx90c evidence |
| `StaggerUMapping` | `0` | Check local `Common.py` |
| `BufferLoad` | `True` | Check local `Common.py` |
| `NonTemporalA/B` | `0` | Check local `Common.py`; prior PR changes `NonTemporalA 0→3` on gfx1100, semantics not checked |
| `WorkGroupMapping` | `8` | Project reportedly also tests 4/8; 7 was proposed in a draft, not established |
| `1LDSBuffer` | `0` | Wiki default; buffering semantics require local verification |
| `GlobalSplitUAlgorithm` | `SingleBuffer` | Additional knob absent from supplied §H.1 list; whether YAML exposes it is unknown |

### Sources actually consulted in the partial pass

| Source | Information / caveat |
|---|---|
| [Tensile wiki: Kernel Parameters](https://github.com/ROCm/Tensile/wiki/Kernel-Parameters) | One-line parameter definitions, defaults, `GlobalSplitU`; obsolete Dec-2024 page |
| [Tensile release 4.41.0 / ROCm 6.2.0](https://github.com/ROCm/Tensile/releases/tag/rocm-6.2.0) | `GlobalLoadVectorWidthA/B` added, effective with `GlobalReadVectorWidth=-1`; GSU algorithm falls back to `SingleBuffer` when `GSU=1`; excerpt only |
| [Tensile release 4.37.0 / ROCm 5.6.0](https://github.com/ROCm/Tensile/releases/tag/rocm-5.6.0) | SingleBuffer algorithm for ZGEMM/CGEMM; SingleBuffer + AtomicAdd GSU option; improved SingleBuffer GSU performance; complex VGPR allocation fix; release-note evidence only |
| [rocm-libraries PR #10847](https://github.com/ROCm/rocm-libraries/pull/10847) | gfx1100 WMMA, latency-bound small-N retune: `UseSgprForGRO -1→1`, `StaggerU 32→16`, `StaggerUStride 256→128`, `NonTemporalA 0→3`; snippet was truncated. It shows per-shape vendor tuning on another architecture, not gfx90c results |

## Q1. `UseSgprForGRO`: move global-read-offset state out of VGPRs

### Mechanism and claims

Detailed upstream `Common.py` comments describe **one VGPR base GRO plus multiple SGPR GRO offsets**, each relative to `GlobalReadOffset+0`. This is not the same as moving every address/dimension into SGPRs. The transformation moves address-offset state, not the FMA stream; source does not show each FMA becoming a scalar instruction. Offset calculation/copy instructions may consume SALU slots.

Required/related constraints in inspected upstream source:

- `UseSgprForGRO=1` requires `BufferLoad=1` and does not support `ShiftPtr`.
- For vector widths above one, suitable `Assert*ElementMultiple` guarantees may be needed to remove pointer shifting; `GlobalReadVectorWidth=1` is another noted route.
- A 64-bit 2D buffer limit may require four instructions to move the scalar limit and a couple of SGPRs.
- More independent offsets mean more scalar state. High unroll can exhaust SGPRs; schema value `-1` is heuristic/auto and can fall back when projected address-load count is high.
- `BufferLoad` uses 128-bit V# buffer descriptors held in four SGPRs, according to the earlier draft. Buffer loads accept an SGPR base offset plus VGPR lane index. This descriptor detail is architecture/source-version-sensitive and should be checked in local ISA.

The earlier Gemini draft asserted broader movement of uniform `lda`, `ldb`, `M`, `N`, `K`, and K-step increments; 4–8 VGPRs/thread saved; +8–16 SGPRs/wave used; GCN’s 102-SGPR limit/wave; and SGPR pressure becoming material above 96 SGPRs/wave. It also asserted SALU operates independently of VALU FMA issue except when scalar waits (`s_waitcnt`) intervene. These are retained as **claims from that draft**, not confirmed local-v4.44 measurements. Its statement that wave-uniform offsets are identical across wave64 lanes explains the rationale, but exact moved variables/register deltas depend on generated path.

The partial Claude pass found a related gfx1100 hipBLASLt retune changing `-1` to `1`, stating global-read offsets are wave-uniform and “do not belong in vector” registers; the knob was changed alongside deeper pipelining to make that pipeline fit. No gfx9/gfx90c measurement was found.

### Costs and interactions

Main exchange: fewer vector address registers for more scalar address offsets and possibly more scalar address instructions. Larger `GlobalLoadVectorWidth` means fewer global loads per unroll step and may reduce absolute GRO-register savings; small vector widths with coalesced loads were proposed as more favorable. `NumLoadsCoalesced` interaction was not established in the partial pass. SGPR exhaustion can defeat the optimization or make a solution infeasible. A VGPR reduction from the reported ZZ winner’s 63 VGPR/thread is promising only if SGPRs, instruction count, and occupancy remain acceptable; the supplied audit reports no scratch spills, so VGPR relief alone does not prove a speedup.

### Experiment

Compare `UseSgprForGRO=0` and `1` first on the 63-VGPR complex-double ZZ winner and a few legal CC/ZZ alternatives, with `BufferLoad=1`, legal assertions, and no unsupported `ShiftPtr`. Then consider combinations with PGR/PLR only if the standalone change is useful. Inspect emitted ISA, VGPR/SGPR counts, scalar/vector address instructions, LDS bytes, spill status, and runtime. Confirm whether local auto mode `-1` already selects 0 or 1.

**Confidence:** `VERIFIED` for upstream one-base/many-offset design and cited legality; `PARTIAL` for transfer to local v4.44; exact 4–8 VGPR and 8–16 SGPR deltas are unverified for this target; gfx90c speedup unmeasured.

Sources: [Tensile `Common.py`, UseSgprForGRO declaration/comments](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2345-L2388); [assertion-dependent enabling/address-VGPR reduction](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2474-L2485); [BufferLoad/flat-load differences](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2270-L2388); [PR #10847](https://github.com/ROCm/rocm-libraries/pull/10847).

## Q2. `StaggerU`, `StaggerUStride`, `StaggerUMapping`, and `WorkGroupMapping`

### Source-backed mechanism

Tensile documents `StaggerU` as changing the initial offset in the summation/U dimension. A and B starts are adjusted; positive values distribute workgroups among offsets in multiples of the macro-tile unroll dimension. Motivation: avoid poor DRAM/cache/TLB behavior when many workgroups start from similarly aligned, often power-of-two K addresses. Larger staggering can spread requests across channels but may reduce L2 reuse. `WorkGroupMapping` sets output-tile assignment/traversal; `StaggerU` changes each tile’s initial U origin, so they interact.

`StaggerUStride` is a byte stride between stagger increments. Upstream notes 256 bytes as a recommended/default-related scale for GFX8/gfx900/gfx906 channel behavior and rounds/adjusts the stride to a multiple of `DepthU * bytesPerElement`; that old hardware rationale does not establish gfx90c optimality. `StaggerUMapping` index source: `0→wg0`, `1→wg1`, `2→wg2`, `3→serialize(wg0,wg1,wg2)`, `4→debug mapping for max permitted offset`.

Upstream `Common.py` says `StaggerU` requires `BufferLoad=1` and is ignored with `BufferLoad=0`. The project candidate gate reportedly accepts values either way. Validator acceptance does not prove generated code uses the offset; inspect local v4.44 ISA/writer for `BufferLoad=0`, and deduplicate candidates if they are no-ops.

### Competing target-specific hypotheses (not verified)

An earlier draft claimed workgroup `w` begins at `K=(w * StaggerUStride) mod K`, that `StaggerU=2` or `4` with stride `16` or `32` smooths simultaneous DRAM requests on a 7-CU shared-DDR4 (~42 GB/s) APU, and that `WorkGroupMapping=7` maps grid blocks to the seven physical CUs. It further proposed non-overlapping K slices to maximize A L2 hits and stagger B reads. These are **hypotheses**, not established facts: staggering is an address-offset mechanism, not a direct CU scheduler; the inspected sources provide no seven-CU formula or evidence that WGM=7 maps block IDs directly to physical CUs. The supported upstream option values are powers of two; do not infer `StaggerU=7` is desirable.

The partial pass adds a gfx1100 small-N retune that changed `StaggerU 32→16`, `StaggerUStride 256→128`, alongside other knobs. This supports shape-specific tuning as a possibility, not transfer of those values to gfx90c.

### Experiment

Randomize `StaggerU=0` vs a small supported nonzero subset; pair with current/project `WorkGroupMapping=4` and `8`, test large K and several output sizes. Consider `16/8` with a scaled stride only as additional hypotheses. Defer `StaggerUStride` and `StaggerUMapping` until `StaggerU×WGM` shows measurable impact. Test generated ISA before spending time on `BufferLoad=0` candidates.

**Confidence:** mechanism and interaction `VERIFIED` in upstream source; target-specific cache/bus claims `UNVERIFIED`; optimal gfx90c settings and non-power-of-two-CU behavior `UNVERIFIED`.

Sources: [Tensile `Common.py`, staggering options](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662); [Tensile kernel-parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html); [PR #10847](https://github.com/ROCm/rocm-libraries/pull/10847).

## Q3. `AggressivePerfMode` and `MaxOccupancy`

### `MaxOccupancy` source behavior

Documented purpose: cap resident workgroups/CU when cache thrashing hurts performance, by padding per-workgroup LDS allocation. Parameter range: 1–40 workgroups/CU. The inspected TensileLite `Solution.py` computes an occupancy-oriented LDS size from `DeviceLDS // MaxOccupancy`, then pads kernel LDS to at least that amount. With `DeviceLDS=65536`, nominal reserve is approximately `floor(65536/N)` bytes per workgroup for `MaxOccupancy=N`. Actual residency may be lower due to real LDS usage, alignment, VGPR/SGPR limits, wave limits, and other resources.

**Formula discrepancy preserved:** Gemini draft wrote `max(Kernel LDS, ceil(65536/N))`; inspected code is described in the other pass as `DeviceLDS // N` (floor). Resolve the exact rounding and padding semantics against the project's v4.44 writer. Neither nominal formula replaces actual code-object LDS allocation.

### `AggressivePerfMode=2` hypothesis

One project brief/draft says mode 1 uses `s_setprio`; mode 2 pads LDS above 32 KiB (example 32,769 B), limiting residency to one workgroup/CU because total LDS is 64 KiB, allegedly yielding 2 waves/SIMD or 8 waves/CU. It proposed `MaxOccupancy=8` as the same 8-wave/CU target and claimed this is optimal for non-MI FMA GEMM: at least 2 waves/SIMD allegedly saturate LDS ports at 128 B/clock while preserving VGPR availability and L2 retention. The same draft reasoned that 8×8 thread tiles hold 64 accumulator VGPRs/thread, that this occupancy would enable up to 128 VGPRs/thread without spilling, and that 16 independent vector FMA operations per unroll step provide enough ILP to cover 4-cycle VALU latency without wave switching.

Those mode-2, bandwidth, latency, and optimum claims lack an authoritative inspected source for the local v4.44 path. A two-wave/SIMD cap is not an automatic win when the supplied corpus median is already eight waves/CU, approximately two waves/SIMD. The main plausible case is measured cache thrashing/interference; cost is less parallel work to cover global-memory latency and fewer CTAs. Seven CUs alone do not prove lower occupancy is best.

### VGPR allocation-granule conflict

The briefs disagree about VGPR allocation granularity: one gives 8 for VGPR count ≤96, otherwise 16; another gives 4 on gfx9 wave64. The partial pass did not source either and had an unsourced recollection of 4. Resolve with LLVM AMDGPU `getVGPRAllocGranule` before trusting occupancy arithmetic.

### Experiment

Keep `MaxOccupancy=40` control. Test lower caps only when emitted resources show multiple resident workgroups and there is evidence for cache-reuse trouble. Treat APM mode 2 as a separate, low-priority factor until local writer/disassembly proves its effect. Confirm residency from code-object metadata/runtime rather than assuming `N` is attained.

**Confidence:** documented MaxOccupancy purpose and occupancy-oriented LDS padding `VERIFIED` in inspected source; exact rounding and transfer to v4.44 `PARTIAL`; APM2 path and optimal occupancy `UNVERIFIED`.

Sources: [Tensile `Common.py`, parameter/rationale](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2723-L2739); [TensileLite `Solution.py`, occupancy LDS calculation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6228); [AMD GPU Hardware Basics PDF](https://www.olcf.ornl.gov/wp-content/uploads/2019/10/ORNL_Application_Readiness_Workshop-AMD_GPU_Basics.pdf); [arXiv: GPU Performance Portability needs Autotuning](https://arxiv.org/pdf/2505.03780).

## Q4. `LocalSplitU`, `GlobalSplitU`, and seven-CU grid quantization

### LocalSplitU: mechanism and legality

In the inspected classic Tensile kernel, `LocalSplitU` is `WorkGroup[2]` and partitions the summation/U dimension **inside a workgroup**. It does not split MacroTile M, and it does not increase the output-grid count. `MacroTile0 = WorkGroup[0] * ThreadTile[0]`; `MacroTile1 = WorkGroup[1] * ThreadTile[1]`. For the classic non-MI path, workgroup threads are `WorkGroup[0] * WorkGroup[1] * LocalSplitU`, subject to wavefront/kernel-family constraints. It can reduce per-part K work while adding local partial accumulation/reduction and synchronization. Thus LSU is not a general CU wave-fill lever.

The source-version inspected in TensileLite has a TODO/guard limiting LSU to single precision or Int32 compute, which would rule out complex C/Z and other types; it is **not asserted to be the exact local v4.44 gate**. Verify local dtype guard before generating complex `LocalSplitU>1`. Other legality checks include `NumThreads % MacroTile0 == 0`, `(MacroTile0 * MacroTile1) % NumThreads == 0`, and store/vectorization constraints.

The earlier Gemini draft proposed LSU=2/4 for complex shapes with M,N≤512 as the sole complex intra-workgroup wave-fill option, claiming LDS cost `Mt * Nt * bytesPerElement * LSU`, `s_barrier`, vector additions, and depth/workgroup divisibility (`DepthU % LSU == 0`, total threads multiple of `64 * LSU`). Keep these as prior claims, but the source-described datatype restriction directly conflicts with complex recommendations, and the cost formula is not a substitute for local writer-derived LDS/accumulator allocation. Do not apply LSU to complex unless local v4.44 source and validation accept it.

### GlobalSplitU: mechanism, costs, complex policy conflict

GSU partitions K across separate workgroups; grid size multiplies by split factor, then partial outputs are combined. Modes include SingleBuffer/atomic and MultipleBuffer/workspace plus post-reduction. Multiple-buffer workspace traffic scales approximately with `GSU * M * N * bytesPerOutput`, in addition to partial stores/reduction reads; single-buffer atomic path incurs atomic updates. An older wiki describes a beta-scaling kernel followed by a kernel with global atomics; later releases added `GlobalSplitUAlgorithm` SingleBuffer/MultipleBuffer and a second summation kernel for MultipleBuffer. Release notes say GSU algorithm falls back to SingleBuffer at `GSU=1`.

The current TensileLite support predicate inspected by the source pass excludes complex types from the relevant assembly GSU path. The project gate reportedly rejects `GlobalSplitU>1` for C/Z, so treat that gate as authoritative unless local v4.44 code proves another path. This is a Tensile implementation/policy constraint, not a mathematical impossibility: complex K-partial products can be reduced. However, Tensile 4.37 release notes say “Added SingleBuffer algorithm for ZGEMM/CGEMM” and “SingleBuffer + AtomicAdd option for GlobalSplitU”; the partial draft inferred that complex GSU rejection might depend on `GlobalSplitUAlgorithm`/`AtomicAdd`, and suggested one probe of `GSU=2..4` with `SingleBuffer` (± `AtomicAdd`) if YAML exposes it. This is release-note evidence only, not proof local v4.44 allows it. Never force an invalid candidate. Inspected current code conditionally enables GSU for single precision, some double paths with `BufferStore`, Int32 destination, and certain assembly half paths with constraints.

Source-version refs: [Tensile `Common.py`, GSU modes/workspace discussion](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2043-L2095); [TensileLite GSU support predicate](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5802); [Tensile 4.37.0 release notes](https://github.com/ROCm/Tensile/releases/tag/rocm-5.6.0); [Tensile 4.41.0 release notes](https://github.com/ROCm/Tensile/releases/tag/rocm-6.2.0).

### Seven-CU quantization

For square output dimension `N`, square output tile `T`, split factor `S`, define `G = ceil(N/T)^2 * S`. Slot utilization for one batch per CU is `G / (7 * ceil(G/7))`. Last-batch active CUs are `G % 7`, or seven when remainder is zero; idle CUs are `0` if remainder zero, otherwise `7 - (G % 7)`. This is grid scheduling arithmetic only, not tile efficiency, residency, tile time, cache behavior, or reduction cost.

| N | T | Output tiles `ceil(N/T)^2` | Idle CUs in last batch | Last-batch idle fraction | Whole-grid CU-slot utilization |
|---:|---:|---:|---:|---:|---:|
| 128 | 16 | 64 | 6 | 85.7% | 91.4% |
| 128 | 32 | 16 | 5 | 71.4% | 76.2% |
| 128 | 64 | 4 | 3 | 42.9% | 57.1% |
| 128 | 128 | 1 | 6 | 85.7% | 14.3% |
| 256 | 16 | 256 | 3 | 42.9% | 98.8% |
| 256 | 32 | 64 | 6 | 85.7% | 91.4% |
| 256 | 64 | 16 | 5 | 71.4% | 76.2% |
| 256 | 128 | 4 | 3 | 42.9% | 57.1% |
| 512 | 16 | 1,024 | 5 | 71.4% | 99.5% |
| 512 | 32 | 256 | 3 | 42.9% | 98.8% |
| 512 | 64 | 64 | 6 | 85.7% | 91.4% |
| 512 | 128 | 16 | 5 | 71.4% | 76.2% |
| 1,024 | 16 | 4,096 | 6 | 85.7% | 99.85% |
| 1,024 | 32 | 1,024 | 5 | 71.4% | 99.5% |
| 1,024 | 64 | 256 | 3 | 42.9% | 98.8% |
| 1,024 | 128 | 64 | 6 | 85.7% | 91.4% |
| 2,048 | 16 | 16,384 | 3 | 42.9% | 99.98% |
| 2,048 | 32 | 4,096 | 6 | 85.7% | 99.85% |
| 2,048 | 64 | 1,024 | 5 | 71.4% | 99.5% |
| 2,048 | 128 | 256 | 3 | 42.9% | 98.8% |

A tile/grid that divides evenly can still lose due to inefficient tiles or GSU reduction overhead. Increasing GSU changes arithmetic from `G` to `G*S` workgroups, but only helps if extra K parallelism exceeds atomic/workspace/reduction costs. The table does not choose fastest T or S. LocalSplitU is intentionally absent from the output-grid multiplier.

**Confidence:** split mechanisms and inspected source checks `VERIFIED`; transfer of newer TensileLite legality to local v4.44 `PARTIAL`; best timing configuration `UNVERIFIED`.

## Q5. `NumLoadsCoalescedA/B`: load layout and legality

### Source-derived geometry rule

NLC determines how per-thread loads are partitioned between the coalesced and perpendicular dimensions. It changes tile strip-mining, address pattern, and register offsets; it does **not** itself set `VectorWidth`. `VectorWidth`/`GlobalLoadVectorWidthA/B` determines contiguous elements per load, while derived `NumLoads` and divisibility constraints couple the parameters.

Inspected TensileLite derives `totalVectors = totalElements / GlobalReadVectorWidth`, then `NumLoads = totalVectors // NumThreads`. A fixed positive candidate `k` passes the inspected classic-path NLC filter when it divides `NumLoads`, divides `totalVectorsCoalesced`, and `NumLoads // k` divides `totalElementsPerp`. If `enableGLTrX` is true, the coalesced/perpendicular geometry inputs swap. Required inputs must come from Tensile’s exact TLU/layout, `GlobalReadVectorWidth`, tile, `DepthU`, macro-tile, thread-count, and transpose path. A universal predicate from VW, bytes/element, and contraction-layout name alone is unsupported.

```python
def nlc_is_legal(k, num_loads, total_vectors_coalesced,
                 total_elements_perp, enable_gl_tr_x=False):
    """Mirror inspected TensileLite classic fixed-NLC divisibility filter.

    Inputs are Tensile-derived counts for one operand, not raw tile sizes.
    Caller must use correct TLU/layout and GlobalReadVectorWidth path.
    """
    if enable_gl_tr_x:
        total_vectors_coalesced, total_elements_perp = (
            total_elements_perp, total_vectors_coalesced
        )
    if k <= 0 or num_loads <= 0 or k > num_loads:
        return False
    if num_loads % k != 0:
        return False
    perpendicular_loads = num_loads // k
    return (
        total_vectors_coalesced % k == 0
        and total_elements_perp % perpendicular_loads == 0
    )


def legal_nlc_values(num_loads, total_vectors_coalesced,
                     total_elements_perp, candidates=(1, 2, 4, 8),
                     enable_gl_tr_x=False):
    return [k for k in candidates if nlc_is_legal(
        k, num_loads, total_vectors_coalesced,
        total_elements_perp, enable_gl_tr_x
    )]
```

Separately enforce project-brief byte limits: `VectorWidth * bytesPerElement <= 16` and corresponding global-load-width constraints, plus datatype/layout rules. The project reported `NLCA=2` legal only for selected dtype/VW cells; that is consistent with geometry-dependent legality.

### Earlier, conflicting legality/model claims

The Gemini draft claimed NLC=1 makes each thread issue vector loads (`global_load_dword`/`dwordx4`); NLC=`k>1` combines `k` adjacent threads’ requests into contiguous wider transactions (e.g. two threads loading contiguous 8-byte chunks), followed by register shuffles or cooperative LDS writes. It proposed these “if and only if” rules:

1. `VW * BPE <= 16` bytes.
2. `k * VW * BPE <= 16` bytes for direct-to-register loads, or `<=64` bytes for direct-to-LDS loads.
3. Operand tile extent (`Mt` or `Nt`) divisible by `k * VW`.
4. Workgroup thread count divisible by `k`.

That draft also recommended NLC=2 when `VW*BPE<=8` bytes. These simple predicates and the “adjacent threads combine transactions” wording are **not equivalent to the inspected source-derived divisibility filter**. Preserve them as legacy hypotheses for the exact local `KernelWriterAssembly.py:checkNumLoadsCoalesced` path, not as a universal rule. Exact writer legality wins.

```python
def is_num_loads_coalesced_legal(NLCA, VectorWidth, bytesPerElement,
                                 MacroTileA, WorkGroupSize,
                                 DirectToLds=False):
    """Legacy simple predicate from one draft; not source-universal."""
    if NLCA <= 1:
        return True
    load_bytes_per_thread = VectorWidth * bytesPerElement
    if load_bytes_per_thread > 16:
        return False
    total_coalesced_bytes = NLCA * load_bytes_per_thread
    max_allowed = 64 if DirectToLds else 16
    if total_coalesced_bytes > max_allowed:
        return False
    if MacroTileA % (NLCA * VectorWidth) != 0:
        return False
    if WorkGroupSize % NLCA != 0:
        return False
    return True
```

Sources: [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html); [TensileLite load geometry](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3923); [NLC divisibility checks](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3950); [Tensile benchmarking guide](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/benchmarking.html).

**Confidence:** source-level filter `VERIFIED` for inspected TensileLite; parity with local v4.44 `PARTIAL`; raw-input-only predicates not supported as universal legality.

## Q6. `InnerUnroll`: loop factorization and issue/register pressure

In inspected classic Tensile, `DepthU` is divided by `LocalSplitU`, then the resulting unroll count is divided by `InnerUnroll`. For legal integral configurations:

`DepthU = LoopUnroll * InnerUnroll * LocalSplitU`.

`DepthU` is K-depth represented by an unrolled tile step; `LoopUnroll` is derived; `InnerUnroll` changes the factorization into inner-body work versus loop iterations. It does not increase K tile size independently.

The earlier Gemini description says `DepthU` controls K elements loaded global→LDS per main loop; `LoopUnroll` is derived outer unroll; `InnerUnroll=u` evaluates `u` register-level FMA substeps before LDS pointer updates/branch checks. It claimed `InnerUnroll=2` doubles active LDS-read operand registers, adding `2*(ThreadTile0+ThreadTile1)` VGPRs, eliminating `s_cbranch_vccnz` and pointer arithmetic, and increasing VALU FMA density for issue-bound CC/ZZ where one complex MAC uses four real FMAs. Its adoption table separately gave extra VGPRs as `2*(u-1)*(ThreadTile0+ThreadTile1)`. These register/branch formulas are retained as draft-specific claims; exact local emitted instructions and count are unverified.

A larger inner body can reduce outer loop-control frequency and expose adjacent arithmetic/load work but increase static code size, live ranges, simultaneous values, and register pressure. Prefetch and InnerUnroll are coupled because prefetch keeps future data/address state live. To target fewer non-FMA issue slots on CC/ZZ, inspect disassembly: branch/address-update counts, FMA sequence, VGPR/SGPR use, and timing. Check `DepthU % (LocalSplitU * InnerUnroll) == 0`, as well as all type, edge-tail, vectorization, assertion, and assembly-path legality.

```python
def inner_unroll_is_integral(depth_u, local_split_u, inner_unroll):
    if min(depth_u, local_split_u, inner_unroll) <= 0:
        return False
    divisor = local_split_u * inner_unroll
    return depth_u % divisor == 0 and depth_u // divisor >= 1
```

**Confidence:** source factorization `VERIFIED`; exact assembly scheduling/register formula and any gfx90c gain `PARTIAL`/`UNVERIFIED`.

Sources: [TensileLite loop derivation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6584); [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html); [Tensile `Common.py` assertions/prefetch](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032).

## Q7. `FractionalLoad`: edge/tail handling

Detailed upstream semantics: some workitems may skip the final buffer load, permitting more flexible `DepthU`/vectorization. Mode 1 may need an extra address VGPR on an edge; mode 2 may use a temporary VGPR inside the unroll loop and can save a VGPR when both A and B use the fractional-edge route, at vector-ALU cost. Test where actual K/load-tail divisibility blocks a useful `DepthU` or vector width; dimensions such as 1000/1365 are only examples until exact load geometry is calculated. Non-power-of-two shape alone does not establish a tail. If relevant dimensions meet load/tile assertions and have no fractional tail, source gives no reason to pay extra address or vector-ALU cost; aligned-path overhead elimination remains writer/specialization-dependent.

Earlier draft's mode interpretation, retained but not confirmed for the local path:

- `FractionalLoad=0`: standard vector loads; draft says problem dimensions must be exact multiples of vector load width.
- `FractionalLoad=1`: fractional vector loads; draft claims edge fallback from `dwordx4` to `dwordx2` or `dword`.
- `FractionalLoad=2`: draft says hardware buffer boundary clamping via `BufferLoad` descriptors, with zero-cost boundary protection / no scalar branch overhead.
- It also claims `FractionalLoad=1` has zero runtime cost for divisible multiples of 64/128 when `AssertFree0ElementMultiple` suppresses edge predicates.

These specific emitted-code/zero-cost claims were not measured on gfx90c. `FractionalLoad` default was reported as `0` in the obsolete wiki. Make it a conditional, lower-priority factor.

**Confidence:** parameter semantics `VERIFIED` in inspected source; exact mode-to-ISA mapping and aligned-shape impact `UNVERIFIED` for local v4.44.

Source: [Tensile `Common.py`, FractionalLoad](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2390-L2397); [Tensile issue #2077](https://github.com/ROCm/Tensile/issues/2077).

## Q8. `NonTemporalA/B`: cache/coherence hints

The safe model: a non-temporal hint changes memory/cache/coherence treatment; it does **not** remove required A/B operand traffic. GEMM workgroups still fetch required values; staging into LDS does not itself eliminate global loads. AMD LLVM docs describe GFX6–GFX9 lowering of non-temporal global memory operations to global/buffer/flat forms with cache/coherence modifiers. This establishes that the attribute can affect emitted memory instructions, not that it always bypasses gfx90c L2.

The earlier Gemini draft claimed `NonTemporalA/B=True` adds the SLC bit (example `buffer_load_dword ... slc`), marks lines LRU or bypasses L2 allocation, and thereby protects Matrix C destinations and CPU working sets from A/B eviction in a shared 1 MiB L2. It claimed A/B tiles are immediately staged to LDS and their L2 retention is redundant; it recommended setting both True and pairing with `StaggerU=2/4`. These cache-specific semantics and “eliminates thrashing” result are **not verified by target assembly/measurement**. The partial pass noted PR #10847 changed `NonTemporalA 0→3` on gfx1100; the meaning of cache-policy code `3` was not checked.

Large tensors may stream enough to compete for shared L2, but GEMM can reuse A/B across neighboring output tiles; disabling useful caching may increase DDR traffic. Evaluate `NonTemporalA/B` with current `WorkGroupMapping` on large streaming shapes, inspect exact gfx9 modifiers, and measure. Do not assume zero resource cost means zero performance risk.

**Confidence:** GFX6–GFX9 non-temporal lowering documented `VERIFIED`; exact Tensile-to-modifier mapping `PARTIAL`; L2 bypass semantics and target gain `UNVERIFIED`.

Sources: [LLVM AMDGPU usage](https://rocm.docs.amd.com/projects/llvm-project/en/latest/LLVM/llvm/html/AMDGPUUsage.html); [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html); [PR #10847](https://github.com/ROCm/rocm-libraries/pull/10847).

## Q9. `PrefetchGlobalRead`, `PrefetchLocalRead`, LDS buffering, and `*Read2/*Write2`

### `PrefetchGlobalRead` (PGR)

PGR loads global data for a later K iteration ahead of use. Source comments say this path uses a second LDS buffer and VGPRs to hold data between global load and LDS write. Mode 2 adds a prefetch stage while moving VGPR-held data into LDS. Benefit: overlap global-memory latency with compute. Cost: more VGPR data/address state and typically another LDS staging buffer. The earlier Gemini draft estimated global-read staging VGPRs as `2 * GlobalLoadVectorWidth * NumLoads` for PGR=1 and quoted global-memory latency around 200–300 cycles. Treat those counts/latency as draft assertions until measured on this device.

For current per-workgroup LDS allocation `L`, double buffering roughly gives `2L` before alignment/other allocations; with 64 KiB LDS, plain double buffering fits under the nominal capacity only for `L <= 32 KiB`. Example supplied earlier: 16–25 KiB can become 32–50 KiB, remaining individually under 64 KiB yet allowing fewer resident workgroups. Check exact emitted LDS and reject over-limit candidates. Since the prior audit says 61.7% of kernels are LDS-bound, PGR is high-risk for those.

### `PrefetchLocalRead` (PLR)

PLR buffers LDS-read values into VGPRs ahead of FMA use. Inspected source relates buffered VGPR count to `min(PrefetchLocalRead + 1, LoopIters)`. A one-substep look-ahead was earlier estimated to add `(ThreadTile0+ThreadTile1)` LDS-operand VGPRs; higher look-ahead raises live ranges/pressure. Evaluate with measured latency and register changes, not an assumed LDS bandwidth ceiling. Current brief says LDS bandwidth is oversupplied. A partial draft reports obsolete-wiki default `PrefetchLocalRead=1` and recommends checking whether the three complex winners’ `PrefetchGlobalRead=False` is explicit.

### LDS capacity arithmetic from earlier draft

```python
def calculate_lds_capacity_bytes(Mt, Nt, DepthU,
                                 bytesPerElementA, bytesPerElementB,
                                 LocalRead2=False, LocalSplitU=1):
    """Legacy analytical estimate; verify exact local-writer accounting."""
    buffer_count = 2 if LocalRead2 else 1
    tile_bytes = DepthU * (Mt * bytesPerElementA + Nt * bytesPerElementB)
    base_lds = buffer_count * tile_bytes
    return base_lds * LocalSplitU
```

Formula stated in draft:

`LDSBytes = LDS_Buffer_Count * DepthU * (Mt * BPE_A + Nt * BPE_B)`

with `LDS_Buffer_Count=2` if double-buffered (`LocalRead2A=True` or `1LDSBuffer=False`) and `1` if single-buffered (`1LDSBuffer=True`). This equivalence is **not established for the local branch**, especially because the inspected upstream comments say the `*Read2` implementation is “not used yet.”

Worked FP32 example, `Mt=Nt=64`, `DepthU=32`, 4 B/element:

- Single buffer: `1 * 32 * (64*4 + 64*4) = 16,384 B = 16 KiB`.
- Double buffer: `2 * 32 * (64*4 + 64*4) = 32,768 B = 32 KiB`, nominally at most two such workgroups/CU by LDS capacity.
- `128×128`, same depth, double-buffer: `2 * 32 * (128*4 + 128*4) = 65,536 B = 64 KiB`, consuming full LDS and nominally limiting residency to one workgroup/CU.

This was offered as an explanation for 61.7% LDS-bound kernels, but only if the buffer-count assumptions match emitted code.

### `LocalRead2A/B`, `GlobalRead2A/B`, `LocalWrite2`

`Common.py` comments describe `*Read2` as combining reads into paired instructions, potentially reducing instruction count but constraining immediate offsets and sometimes requiring arithmetic to advance/reset offsets. The same comments reportedly label the path “not used yet.” This does not establish active emitted code in local v4.44. Pairing reads is separate from allocating a second LDS buffer. `LocalRead2A/B=True`, `GlobalRead2A/B=True`, and `1LDSBuffer=0` are obsolete-wiki defaults, not proof of an active path. `LocalWrite2` was also named in the untouched-knob discussion, but no active local code path was verified. Hold these knobs until generated ISA proves implementation.

**Confidence:** PGR/PLR resource trade-offs `VERIFIED` in inspected source; exact v4.44 allocation `PARTIAL`; `*Read2/*Write2` activity `UNVERIFIED`.

Sources: [Tensile `Common.py`, PGR/PLR comments](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032); [Tensile `Common.py`, paired-read/scheduling comments](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2122-L2167); [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html).

## Q10. Search strategy and evidence for possible speedups

### Defensible experiment strategy

The untouched knobs are worth a targeted, dependency-aware screen, not a blind one-factor sweep. Tensile’s benchmark guide explicitly sweeps options such as PGR, NLC, ThreadTile and related parameters; that makes them legitimate tuning variables but gives no gfx90c effect size. Proposed strategy for the 272-candidate / 10-hour measurement window:

1. **Zero-GPU preflight:** run local v4.44 legality checks; build/code-object metadata; remove invalid and duplicate candidates. In particular, verify `StaggerU` no-op behavior with `BufferLoad=0` and verify local dtype gates for LSU/GSU.
2. **High priority:** `UseSgprForGRO` on legal complex-double ZZ and selected CC with buffer loads/assertions; modest `InnerUnroll` screen on issue-bound CC/ZZ; NLC values only after derived divisibility tests; PGR 0/1 with LDS/VGPR deltas.
3. **Blocked/randomized measurements:** shape/dtype as blocks; randomize config order to avoid confounding thermal/DVFS drift with a knob; interleave and repeat reference kernel to estimate local noise; retain known warm/clock protocol, not one timing as ground truth.
4. **Interactions:** `StaggerU × WorkGroupMapping`; `UseSgprForGRO × BufferLoad/GlobalLoadVectorWidth`; `PGR × DepthU/InnerUnroll`; `NLC × VectorWidth × operand layout`; `NonTemporal × WGM` for large streaming cases. Test `FractionalLoad` only on real tails. Keep `MaxOccupancy`/APM2 low priority absent cache/occupancy evidence.
5. **Selection:** use fractional-factorial or D-optimal screening and follow-up coordinate/Bayesian search only after feasibility filtering. A previous draft suggested 16 orthogonal bundles with Bayesian coordinate descent, but explicitly listed only four bundles; keep these examples as candidate bundles, not a complete 16-bundle design.

Suggested bundle examples from prior draft:

- **Register saver:** `UseSgprForGRO=True + BufferLoad=True + GlobalLoadVectorWidth=4` (still subject to legality; the draft’s “4” is not universally optimal).
- **L2 streaming hypothesis:** `NonTemporalA/B=True + StaggerU=4 + WorkGroupMapping=7` (hypothesis; WGM=7 and L2-bypass claims unverified).
- **Loop-overhead:** `InnerUnroll=2 + PrefetchLocalRead=1`.
- **Wave/tail:** `LocalSplitU=2/4 + WorkGroupMapping=7` (unsafe for complex until dtype legality verified; LSU does not multiply output grid).

### Legacy literature sensitivity ranking and expected yield claims

The earlier Gemini draft attributed these sensitivity ranges to autotuning literature, including ASPLOS’20 “Tile” and OSDI’20 “Ansor”:

1. Tile dimensions (`MacroTile0/1`, `ThreadTile0/1`, `DepthU`): 60–70% variance.
2. Addressing/memory interface (`UseSgprForGRO`, `BufferLoad`, `GlobalLoadVectorWidth`, `LocalReadVectorWidth`): 15–20%.
3. Pipeline/cache (`NonTemporalA/B`, `StaggerU`, PGR, PLR): 10–15%.
4. Fine scheduling (`ScheduleIterAlg`, `StorePriorityOpt`): <5%.

No source located in the more targeted pass supports this exact ranking or those percentages for gfx90c. Treat the ranking as **unverified prior-draft content**, not established sensitivity data.

Same draft projected FP32/FP16 speedups of 10–18% from non-temporal hints/GRO relief, and C/Z gains of 20–35% combining GRO, `InnerUnroll=2`, and LSU. Later source audit explicitly found no published ablation of these exact knobs on gfx90c/seven-CU Renoir/Cezanne APU and no basis for a numeric yield. Therefore those projections are retained for provenance but must not be presented as evidence-backed expectations. No exact knob combination is known fastest without timings.

A vendor retune on gfx1100 moved GRO, StaggerU/stride, NonTemporalA and pipeline controls together, weakly supporting joint tuning instead of strict one-at-a-time search. It is one different-architecture example only.

**Confidence:** search dimensions are legitimate `VERIFIED`; exact local-doc transfer `PARTIAL`; target gains/ranking `UNVERIFIED`.

## 3. Legality and analysis helpers

These helpers are analysis aids, not replacements for local v4.44 `SolutionStructs.py`, writer logic, generated ISA, or runtime metadata.

### 3.1 `MaxOccupancy` nominal LDS model

```python
def max_occupancy_lds_floor(max_occupancy, device_lds_bytes=65536):
    """Nominal LDS bytes reserved per workgroup to cap CTAs/CU."""
    if not 1 <= max_occupancy <= 40:
        raise ValueError("MaxOccupancy must be in [1, 40]")
    return device_lds_bytes // max_occupancy


def nominal_resident_workgroups(actual_lds_bytes, max_occupancy,
                                device_lds_bytes=65536):
    """LDS-only upper bound; ignores other resources and allocation rounding."""
    padded_lds = max(actual_lds_bytes,
                     max_occupancy_lds_floor(max_occupancy, device_lds_bytes))
    return min(max_occupancy, device_lds_bytes // padded_lds)
```

Floor division matches description of inspected source. Compare exact local-source round-up/alignment and generated LDS before relying on it; Gemini’s earlier formula used `ceil`.

### 3.2 Seven-CU grid statistics

```python
from math import ceil


def cu_grid_stats(M, N, macro_tile_m, macro_tile_n,
                  cu_count=7, global_split_u=1):
    """Grid-slot utilization only; omits CTA duration and reduction costs."""
    if min(M, N, macro_tile_m, macro_tile_n, cu_count, global_split_u) <= 0:
        raise ValueError("dimensions and split counts must be positive")
    base_grid = ceil(M / macro_tile_m) * ceil(N / macro_tile_n)
    grid = base_grid * global_split_u
    full_batches = grid // cu_count
    tail = grid % cu_count
    batches = full_batches + (1 if tail else 0)
    idle_cus_in_tail = 0 if tail == 0 else cu_count - tail
    return {
        "base_output_tiles": base_grid,
        "workgroups_including_GSU": grid,
        "batches_of_CUs": batches,
        "tail_active_CUs": cu_count if tail == 0 else tail,
        "tail_idle_CUs": idle_cus_in_tail,
        "tail_idle_fraction": idle_cus_in_tail / cu_count,
        "grid_CU_slot_utilization": grid / (cu_count * batches),
    }


def calculate_wave_quantization(M, N, Mt, Nt, GSU, num_cus=7):
    """Legacy equivalent calculation from earlier draft."""
    grid_m = (M + Mt - 1) // Mt
    grid_n = (N + Nt - 1) // Nt
    total_workgroups = grid_m * grid_n * GSU
    passes = (total_workgroups + num_cus - 1) // num_cus
    active_slots = passes * num_cus
    tail_workgroups = total_workgroups % num_cus
    idle_cus_in_tail = (
        (num_cus - tail_workgroups) % num_cus if tail_workgroups != 0 else 0
    )
    return {
        "total_workgroups": total_workgroups,
        "passes": passes,
        "tail_idle_cus": idle_cus_in_tail,
        "efficiency": total_workgroups / active_slots,
    }


def tail_efficiency(M, N, MT, NT, cus=7, resident=1, gsu=1):
    """Tail efficiency assuming equal tile time and `resident` WGs/CU."""
    wgs = ceil(M / MT) * ceil(N / NT) * gsu
    slots = cus * resident
    return wgs / (slots * ceil(wgs / slots))
```

All versions ignore per-tile time, edge inefficiency, resources, launch overhead, cache behavior and GSU reduction cost. LSU is not an output-grid multiplier; GSU is.

### 3.3 Occupancy estimate and unresolved allocation granule

```python
import math


def waves_per_simd(vgpr_per_thread, wg_threads, lds_bytes_per_wg,
                   granule=4, max_waves_simd=10,
                   lds_per_cu=65536, simds=4):
    """Derived estimate only; verify granule and architecture limits first."""
    alloc = math.ceil(vgpr_per_thread / granule) * granule
    by_vgpr = 256 // alloc  # 256 VGPR rows/SIMD = 16,384 regs / 64 lanes
    waves_per_wg = wg_threads // 64
    wg_by_lds = (
        lds_per_cu // lds_bytes_per_wg if lds_bytes_per_wg else 10**9
    )
    wg_by_vgpr = (min(by_vgpr, max_waves_simd) * simds) // waves_per_wg
    wg_by_waves = (max_waves_simd * simds) // waves_per_wg
    return min(wg_by_lds, wg_by_vgpr, wg_by_waves)
```

Pass `granule` explicitly until LLVM `getVGPRAllocGranule` resolves the disagreement (4 vs 8/16). Assumptions include wave64, 4 SIMD/CU, max 10 waves/SIMD and 65,536 B LDS/CU; verify all against actual target/backend.

### 3.4 LDS estimate

See the Q9 `calculate_lds_capacity_bytes` function. It is a legacy formula, not a verified model of `LocalSplitU`, `LocalRead2`, or `1LDSBuffer` in this local code path.

### 3.5 Inner-unroll check

See Q6 `inner_unroll_is_integral`. It checks factorization only; it does not implement all datatype, tail, vectorization, or assembly-path gates.

## 4. Unified adoption matrix

| Knob | Kernel effect / premise | Resource or legality issue | Action and confidence |
|---|---|---|---|
| `UseSgprForGRO` | SGPR GRO offsets plus a VGPR base in inspected upstream path | Requires `BufferLoad=1`, no `ShiftPtr`, assertion/vector-width path; SGPR pressure may rise | Test 0/1 on legal ZZ then CC; inspect ISA/counts. Mechanism verified, gfx90c gain unmeasured |
| `BufferLoad` | Buffer-load descriptors/address/bounds path | Four SGPRs per V# descriptor claimed by earlier draft; pointer/range constraints | Pair with GRO legality, do not blindly toggle. Source path documented; local effects inspect |
| `StaggerU` | Changes initial U/K offset across workgroups | May reduce or harm reuse; ignored without BufferLoad per upstream | Test 0 vs supported nonzero values × WGM 4/8; target optimum unverified |
| `StaggerUStride`, `StaggerUMapping` | Byte stride and workgroup-coordinate selection | Legacy 256 B rationale is older architecture; coordinate mapping needs distinct offsets | Defer until StaggerU benefit shown; gfx90c optimum unverified |
| `WorkGroupMapping` | Reorders output-tile traversal/cache locality | No inherent extra LDS; impacts reuse/order | Baselines 4/8; test with StaggerU. WGM=7 direct-to-CU claim unverified |
| `MaxOccupancy` | Pads LDS per WG to cap residency | Reduces CTAs; exact rounding/alignment matters | Keep 40 control; lower cap only with cache-thrash evidence. Mechanism verified, optimum unknown |
| `AggressivePerfMode` | Proposed mode-2 LDS cap / mode-1 `s_setprio` | Exact mode-2 behavior local v4.44 unverified | Low priority; inspect local writer/disassembly first |
| `LocalSplitU` | Splits summation inside one workgroup | Extra reduction/sync; dtype guard may exclude complex; no grid multiplication | Verify local type/shape legality; do not infer wave-fill or enable for C/Z from draft alone |
| `GlobalSplitU` | Adds K-partial workgroups plus atomic/workspace reduction | More parallelism vs reduction/store/atomic cost; type path differs | Only gate-approved types; optional one probe for complex SingleBuffer if locally supported |
| `GlobalSplitUAlgorithm` | SingleBuffer/atomic vs MultipleBuffer/post-reduction | Wiki/release-note default `SingleBuffer`; YAML support unknown | Check config schema/local gate before probe |
| `NumLoadsCoalescedA/B` | Load-tile coalesced/perpendicular strip-mining/address layout | Derived divisibility with TLU, dimensions, `GlobalReadVectorWidth`, threads and `enableGLTrX` | Generate only from source-derived counts; simple byte predicate is not universal |
| `InnerUnroll` | Refactors `DepthU`; can cut loop control | Larger code/live ranges/VGPR; exact instruction savings unknown | Legal modest screen on CC/ZZ; count branches/address ops and registers |
| `FractionalLoad` | Lets some items skip final buffer load / tail handling | Edge-only address/temp VGPR/vector ALU cost may apply | Target actual load tails; don’t enable globally without measurement |
| `NonTemporalA/B` | Cache/coherence hint on global loads | L2 bypass/LRU meaning for local gfx90c path unverified; can damage useful reuse | Large-streaming exploratory test; inspect exact modifiers |
| `PrefetchGlobalRead` | Future K-tile load/pipeline overlap | Usually extra LDS buffer and VGPRs; LDS-bound kernels at risk | Begin 0/1; include mode 2 only if generated code/resource margin justify |
| `PrefetchLocalRead` | Buffers LDS values in VGPRs ahead of FMA | Higher look-ahead = more live VGPRs | Modest range; record VGPR delta/runtime |
| `LocalRead2A/B`, `GlobalRead2A/B` | Intended paired-read/instruction behavior | Source comments reportedly “not used yet”; wiki defaults don’t prove code effect | Hold until local emitted ISA confirms path |
| `LocalWrite2` | Named as a related unvaried control | No active local behavior verified | Hold until writer/ISA confirms implementation |
| `ScheduleIterAlg`, `StorePriorityOpt` | Fine scheduling controls in earlier sensitivity ranking | Claimed <5% variance, unsupported for target | Low priority; include only after feasibility and higher-impact interactions |

## 5. Prior-draft recommendations retained as hypotheses

One draft’s direct proposed settings were: `UseSgprForGRO=True` across complex-C/Z tiles for claimed 4–8 VGPR/thread relief; `NonTemporalA=True` and `NonTemporalB=True` to set SLC and bypass L2 allocation; `StaggerU=2` or `4` with `StaggerUStride=16` (elsewhere 16/32); `BufferLoad=True` across assembly kernels; `LocalSplitU=2` or `4` for C/Z with `M,N≤512`; `InnerUnroll=2` for complex datatypes; `WorkGroupMapping=7` to align a 2D grid with seven CUs; `AggressivePerfMode=2` for `8×8` thread tiles; `NumLoadsCoalesced=2` when `VW*BPE≤8 B`; and `GlobalLoadVectorWidth=4` in a GRO/register-saver bundle. These remain hypotheses only. Each is gated by the detailed legality, cache, occupancy, and local-source caveats above; LSU-on-complex and direct WGM-to-physical-CU mapping are specifically unverified or contradicted by inspected-source constraints.

## 6. Evidence and exclusion ledger

The following claims appear in one or more drafts, but evidence status conflicts. Preserve for traceability; do not cite as established target results unless separately verified.

1. **ASPLOS 2020 “Tile”**: Gemini draft says verified; claims analytic pruning with GCN inequalities (`LDS ≤64 KiB`, `VGPR≤256`) removes >85% invalid candidate tiles. Another pass says exact-title/source checks did not establish the alleged ASPLOS’20 paper “A Faster Tiling Approach for AMD GPUs” or matching result. The two titles/attributions were not reconciled; require publisher/DOI/full paper before citation.
2. **OSDI 2020 “Ansor” sensitivity ranking**: Gemini draft attributes knob-variance percentages above to Tile/Ansor. No exact ablation ranking for these knobs on gfx90c was verified. Do not cite the percentages as target facts.
3. **arXiv:2507.15277, “A Few Fit Most: Improving Performance Portability of SGEMM on GPUs using Multi-Versioning”**: One draft says it evaluates CLBlast parameter spaces across five GPU architectures (including AMD Vega and NVIDIA), with per-device dynamic ranges 1.8×–13.2× and device-specific tuning requirements. Targeted audit says the abstract describes 142,782 *device/input/parameter performance measurements* across five GPUs, not 142,782 unique kernel configurations; full text/protocol was not audited. Keep those distinctions; details beyond abstract are `PARTIAL`. [Paper](https://arxiv.org/abs/2507.15277).
4. **gfx1151 auto vs `profile_peak` DPM**: Gemini draft calls verified a claim that Linux auto mode held 1100 MHz during intermittent GEMM dispatches, `profile_peak`/manual held 1800+ MHz and improved end-to-end performance 37.8%. Targeted pass did not verify this claim and says it must not be a gfx90c numeric prior.
5. **COSTA / BASS / BEST / GemmLab**: Gemini draft labels these verified and describes COSTA as modeling tensor-contraction data movement and BASS/BEST as predicting GEMM tiles with microbenchmark-trained decision trees. Targeted pass says exact attributions/sources were not established. Require resolvable publisher/DOI/paper before citation.
6. **142,782 interpretation**: measurements across devices/inputs/parameters are not necessarily unique configurations. Exact count/protocol beyond the abstract remains unaudited.
7. **Complex `GlobalSplitU` prohibition**: current inspected TensileLite predicate excludes complex for the relevant assembly path; obsolete/release-note evidence says SingleBuffer ZGEMM/CGEMM and SingleBuffer+AtomicAdd GSU were added. Local v4.44 rejection could be policy/config-specific; probe only if local gate/schema supports it. Do not claim universal hardware impossibility or force invalid configurations.
8. **NLC legality**: detailed derived-count rule and simple byte/tile/thread predicate differ. Use the exact local writer; retain both only to document the discrepancy.
9. **`NonTemporalA/B` L2 behavior**: non-temporal lowering is documented for GFX6–GFX9; exact SLC modifier meaning, bypass/allocation behavior, and cache-line retention for gfx90c remain unverified.
10. **`*Read2/*Write2` active implementation**: obsolete wiki defaults may be true; upstream comments say relevant path “not used yet.” Generated local ISA decides.
11. **VGPR allocation granule**: competing `4` and `8/16` values unresolved; do not trust occupancy estimates before resolving from LLVM AMDGPU backend.
12. **Seven-CU raster algorithm**: no verified paper/source derives a special non-power-of-two-CU mapping for this APU. Grid arithmetic is descriptive only.
13. **Fastest tile/split**: grid quantization alone cannot select fastest tile/split for `128^3`–`2048^3`; it omits tile efficiency, resident-resource count, CTA duration, memory reuse, launch overhead, and reduction cost.
14. **Expected speedups**: no publication located that measures these exact controls/combinations on gfx90c or seven-CU Renoir/Cezanne APU. Any numeric forecast remains unsupported.

## 7. Run plan: consolidated priority order

1. **Preflight** local `Common.py`, `SolutionStructs.py`, writer, YAML schema and generated code objects. Verify defaults, GRO gates, `StaggerU`/BufferLoad behavior, LSU/GSU dtype restrictions, VGPR allocation granule, `MaxOccupancy` rounding, and whether `*Read2/*Write2` are live.
2. **GRO**: `UseSgprForGRO=0/1` on 63-VGPR ZZ with `BufferLoad=1` and required assertions; inspect address instructions, SGPR/VGPR, spills, LDS and runtime. Then selected CC.
3. **NLC**: derive legal candidates from Tensile’s real geometry path; pair candidates with VW, `GlobalLoadVectorWidth`, layout/TLU and operand-specific A/B geometry.
4. **InnerUnroll**: test small legal values on CC/ZZ; compare FMA density, branches, pointer updates, code size, registers and time. Test interaction with PGR only after standalone resource deltas are known.
5. **PGR/PLR**: begin PGR 0/1; consider 2 only with resource margin. Use modest PLR range. Record LDS/VGPR metadata and actual performance; flag LDS-bound candidates.
6. **StaggerU × WGM**: control 0 vs selected nonzero settings, WGM 4/8, large K/multiple outputs. Check ISA; remove no-op variants. Defer stride/mapping refinements until main effect appears.
7. **NonTemporal**: exploratory large-streaming shapes, with exact load modifiers verified; pair with WGM but do not assume L2 bypass or benefit.
8. **FractionalLoad**: only real K/load-tail cases or cases where it unlocks better `DepthU`/vectorization.
9. **Occupancy controls**: `MaxOccupancy=40` baseline; lower values only with cache-thrashing evidence. APM2 low priority until its local code path and actual residency limit are confirmed.
10. **Split U/K**: LSU only when local dtype/shape gates accept and correct K-partition reduction is visible. Never treat LSU as grid multiplier. GSU only on gate-approved types; one complex SingleBuffer/AtomicAdd probe if the local v4.44 schema/code explicitly supports it.
11. **Paired read/write controls and fine scheduling**: hold `*Read2/*Write2`, `ScheduleIterAlg`, `StorePriorityOpt` until higher-priority mechanisms have evidence or local ISA shows these controls are active.
12. **Measurement discipline**: blocked by shape/dtype; randomize candidate order; interleave repeated reference runs to estimate timing noise and thermal/DVFS drift; retain existing warm/clock protocol; report medians/variance and resource metadata. Do not claim speedup before measuring.

## Appendix A. Original bibliography and relevant source links

- Tensile `Common.py`, GRO declaration/comments: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2345-L2388
- Tensile `Common.py`, assertions/address VGPRs: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2474-L2485
- Tensile `Common.py`, BufferLoad/flat-load differences: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2270-L2388
- Tensile `Common.py`, stagger options: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662
- Tensile `Common.py`, MaxOccupancy: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2723-L2739
- Tensile `Common.py`, GSU modes/workspace: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2043-L2095
- Tensile `Common.py`, PGR/PLR: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032
- Tensile `Common.py`, FractionalLoad: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2390-L2397
- Tensile `Common.py`, paired-read comments: https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2122-L2167
- Tensile parameter docs: https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html
- Tensile benchmarking guide: https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/benchmarking.html
- TensileLite classic workgroup/tile derivation: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3840
- TensileLite load geometry: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3923
- TensileLite NLC divisibility checks: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3950
- TensileLite LSU legality: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5762
- TensileLite GSU support predicate: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5802
- TensileLite occupancy LDS calculation: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6228
- TensileLite InnerUnroll/LoopUnroll derivation: https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6584
- LLVM AMDGPU usage / non-temporal lowering: https://rocm.docs.amd.com/projects/llvm-project/en/latest/LLVM/llvm/html/AMDGPUUsage.html
- Tensile wiki, kernel parameters (obsolete Dec-2024): https://github.com/ROCm/Tensile/wiki/Kernel-Parameters
- Tensile 4.37 release notes: https://github.com/ROCm/Tensile/releases/tag/rocm-5.6.0
- Tensile `CHANGELOG.md` at `develop_deprecated`: https://github.com/ROCm/Tensile/blob/develop_deprecated/CHANGELOG.md
- Tensile 4.41 release notes: https://github.com/ROCm/Tensile/releases/tag/rocm-6.2.0
- ROCm PR #10847: https://github.com/ROCm/rocm-libraries/pull/10847
- AMD GPU Hardware Basics: https://www.olcf.ornl.gov/wp-content/uploads/2019/10/ORNL_Application_Readiness_Workshop-AMD_GPU_Basics.pdf
- `GPU Performance Portability needs Autotuning`: https://arxiv.org/pdf/2505.03780
- Tensile issue #2077: https://github.com/ROCm/Tensile/issues/2077
- `A Few Fit Most: Improving Performance Portability of SGEMM on GPUs using Multi-Versioning`: https://arxiv.org/abs/2507.15277
- Gemini draft’s ResearchGate Ansor link: https://www.researchgate.net/publication/342169422_Ansor_Generating_High-Performance_Tensor_Programs_for_Deep_Learning
