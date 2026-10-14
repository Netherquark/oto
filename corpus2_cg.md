# `corpus2.md` — targeted Tensile-knob research, second pass

> **Status: MINED 2026-10-14.** Knob mechanics cross-checked against the pinned
> `e8a8999e` checkout and the gates — all consistent, none new (UseSgprForGRO,
> StaggerU, LSU/GSU legality, NLC divisibility, prefetch tradeoffs, `*Read2`
> "not used yet" already in `knowledge_base.md` §7 / `kernel_tuning_research.md`).
> **No new deck row came out of this file** — its "test PGR 0 first" is already
> covered by `PLAN_BATCH`, and its run-design advice (blocked, reference-kernel
> repeats, 25% warmup) is folded into the run protocol. Deferred items
> (StaggerU×SUS/SUM pairing conditional on SU showing an effect; APM=2 writer
> confirmation) are in `RESEARCH_PROMPT3.md`. Raw below — do not cite; cite the
> homes.

**Scope and provenance.** This is a documentation/source pass, not a GPU experiment. Hardware properties, the 5,757-kernel audit, clock behavior, performance ceilings, and local Tensile v4.44 behavior stated in the research brief are accepted as ground truth. The principal code references below are the live `develop` version of Tensile's `Common.py` and a Debian-packaged TensileLite `Solution.py` from hipBLASLt 7.2.4. Those are useful primary-source implementations, but they are not the project's exact local commit (`e8a8999e`); version-sensitive legality is labelled accordingly. No claim is made that a proposed knob improved this gfx90c without measurement.

## Executive summary

Three findings should determine the 272-candidate plan. **First, prioritize `UseSgprForGRO` on complex-double winners only when `BufferLoad=1` and the kernel avoids unsupported pointer-shift paths:** Tensile says it keeps one VGPR base and converts multiple global-read offsets to SGPRs, reducing VGPR address state but spending scalar registers and potentially exhausting them at high unroll. **Second, treat prefetch controls as resource tradeoffs, not free latency hiding:** `PrefetchGlobalRead` generally adds a second LDS staging buffer plus VGPR buffering, so it is especially risky for the large portion of the corpus whose resident-workgroup count is already LDS-capacity-limited; `PrefetchLocalRead` likewise grows buffered VGPR state. **Third, use dependency-aware screening, not eleven isolated one-knob sweeps:** `UseSgprForGRO` depends on `BufferLoad` and pointer-shift legality; `StaggerU` interacts directly with `WorkGroupMapping`; `NumLoadsCoalesced` is legal only when Tensile's derived load counts divide correctly; and `InnerUnroll` changes loop factorization and resource use. No publication located in this pass quantifies the gain of these exact knobs on gfx90c, so the defensible outcome is a ranked experiment plan rather than an invented expected speedup.

---

## Q1. `UseSgprForGRO`: move address-offset state out of VGPRs

**Direct answer — `VERIFIED` for upstream Tensile's documented intent; `PARTIAL` for exact local v4.44 emitted instructions.** `UseSgprForGRO=1` does **not** move every address into SGPRs. Tensile documents the scheme as **one VGPR base GRO plus multiple SGPR GRO offsets**, with each SGPR holding an offset relative to `GlobalReadOffset+0`. It requires `BufferLoad=1`, does not support `ShiftPtr`, and needs suitable `Assert*ElementMultiple` guarantees or `GlobalReadVectorWidth=1` so pointer shifting can be removed. A 64-bit 2D buffer limit may require four instructions to move the scalar limit and a couple of SGPRs. Tensile's own comment says the conversion is usually a win for VGPR use, but high unroll can exhaust the available SGPR file. Sources: [Tensile `Common.py`, `UseSgprForGRO` comments and parameter declaration](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2345-L2388); [assertion-dependent enabling and address-VGPR reduction](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2474-L2485); [BufferLoad/flat-load differences](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2270-L2388).

**What it costs.** The primary exchange is fewer vector address registers in return for more scalar address offsets and scalar register pressure. There is no evidence in the source that each FMA itself becomes a scalar instruction. Offset calculations or copies can consume scalar instructions, and exhausting SGPRs can defeat the transformation or make a solution infeasible. It is therefore more accurate to describe it as an **address-state and address-instruction trade** than as a direct reduction in the vector FMA issue stream. Tensile's heuristic mode (`-1` in the currently published schema) can fall back when the projected address-load count is too high; the same comments warn that large unrolls may exhaust SGPRs. [Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2345-L2388).

**Interactions and experiment.** The required dependency is explicit: `UseSgprForGRO=1` requires `BufferLoad=1` and no `ShiftPtr`; a matching assertion may be needed for vector widths greater than one. Tensor load count and unroll matter because each independent offset needs scalar state. Consequently, do not test it as a blind independent factor across illegal candidates. Compare `UseSgprForGRO=0` versus `1` on the complex-double winner and a small number of legal alternatives, then inspect emitted ISA and resource metadata: VGPR count, SGPR count, scalar/vector address instructions, and final LDS allocation. A change from 63 VGPR/thread is promising only if scalar pressure and generated instruction count remain acceptable; the supplied corpus has no scratch spills, so a VGPR saving is not by itself evidence of a performance gain.

**Confidence:** `VERIFIED` for the documented one-VGPR-base/many-SGPR-offset design and explicit legality; `PARTIAL` for how many registers/instructions the local v4.44 writer saves on the winning ZZ kernel; no gfx90c speedup measurement found.

## Q2. `StaggerU` on seven CUs: operand-origin staggering and raster order

**Direct answer — `VERIFIED` for the intended mechanism; `UNVERIFIED` for an optimal value on a seven-CU APU.** Tensile documents `StaggerU` as adjusting the starting position in the summation/U dimension. Both A and B start from the adjusted position; positive values spread workgroups over offsets that are multiples of the macro-tile's unroll dimension. The stated motivation is to reduce poor DRAM/cache/TLB behavior when large power-of-two K dimensions make many workgroups begin from similarly aligned positions. Larger staggering values spread accesses over more channels but can reduce L2 reuse. `StaggerU` and `WorkGroupMapping` are explicitly described as interacting controls: mapping sets the assignment/order of output tiles, while staggering changes the initial U-origin used by a tile. [Tensile `Common.py`, `StaggerU`, `StaggerUStride`, and `StaggerUMapping`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662); [kernel-parameter documentation](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html).

`StaggerUStride` is the stride between the stagger increments, in bytes; the upstream source notes 256 bytes as a recommended/default-related scale for GFX8/gfx900/gfx906 channel behavior, and adjusts the stride to an integer multiple of `DepthU * bytesPerElement`. That older hardware rationale is **not** evidence that 256 is optimal for gfx90c. `StaggerUMapping` chooses which workgroup coordinate controls the stagger index: 0 uses `wg0`, 1 uses `wg1`, 2 uses `wg2`, 3 serializes `(wg0,wg1,wg2)` into one index, and 4 is a debug mapping for the maximum permitted offset. [Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662).

**Important source/configuration discrepancy.** Upstream Tensile says `StaggerU` requires `BufferLoad=1` and is ignored when `BufferLoad=0`, whereas the project brief says its candidate gate accepts values with and without `BufferLoad`. Acceptance by a validator is not proof that the emitted kernel uses the offset. On the project's local v4.44 branch, inspect generated ISA or writer logic for a `BufferLoad=0` kernel before spending measurement budget on that combination. If it is ignored, treat those candidates as duplicates. This is a version/path discrepancy, not a reason to disregard the supplied gate's validation result. [Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2650).

**Seven-CU implication.** There is no verified publication from this pass deriving `StaggerU`, `StaggerUStride`, or `StaggerUMapping` for a non-power-of-two CU count on a shared-DDR APU. Do not infer that `StaggerU=7` is desirable: the upstream option values are powers of two, and staggering is an address-offset mechanism, not a direct CU scheduler. Test `StaggerU=0` against a few supported nonzero values, paired with the project's `WorkGroupMapping` values 4 and 8, randomized across large K and several output sizes. Use `StaggerUMapping` only if there is enough time to test whether workgroup coordinates produce distinct, useful offsets. The official parameter docs explain that `WorkGroupMapping` changes traversal to improve cache behavior; they do not supply a seven-CU formula. [Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662), [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html).

**Confidence:** `VERIFIED` mechanism and WGM interaction; `PARTIAL` interpretation for target behavior; `UNVERIFIED` optimal settings for gfx90c/non-power-of-two CUs.

## Q3. `AggressivePerfMode` and `MaxOccupancy`: deliberate occupancy clamps

**Direct answer — no published gfx90c result or principled universal occupancy target was found.** The documented purpose of `MaxOccupancy` is to cap resident workgroups when cache thrashing hurts performance by allocating extra LDS to restrict occupancy. The parameter is expressed as workgroups per CU, 1–40. The TensileLite source computes an occupancy-oriented LDS size from `DeviceLDS // MaxOccupancy` and pads the kernel's LDS allocation so each workgroup consumes at least that per-slot amount. In the supplied target, `DeviceLDS=65536`, so the nominal cap size is `floor(65536/N)` bytes per workgroup for `MaxOccupancy=N`. This implements a maximum of N resident workgroups/CU when other resource limits would otherwise allow more; real LDS usage, alignment, and other constraints can lower residency further. [Tensile parameter declaration and rationale](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2723-L2739); [TensileLite `Solution.py`, occupancy LDS calculation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6228).

The brief states that `AggressivePerfMode=2` imposes a limit of two waves/SIMD through LDS allocation, while mode 1 uses `s_setprio`. I did not find an authoritative public source that clearly documents that exact mode-2 implementation for the project's v4.44 path; retain that behavior as project-reported until checked against the local writer/disassembly. Even accepting it, a two-wave/SIMD cap is unlikely to be a general win when the supplied corpus median is already eight waves/CU, approximately two waves/SIMD. The plausible mechanism for a cap is improved cache locality or reduced interference on a cache-sensitive kernel. The cost is fewer independent waves/workgroups to cover global-memory latency and fewer CTAs available to use the GPU. No cited source demonstrates that the cache benefit outweighs those costs for non-MFMA FMA-loop GEMM on gfx90c.

**Experimental recommendation.** Keep `MaxOccupancy=40` as the control. Test lower caps only on kernels where emitted-code/resource evidence shows several resident workgroups and a credible cache-reuse problem, rather than applying a blanket clamp. Treat `AggressivePerfMode=2` as low priority and a distinct factor from `MaxOccupancy`, since mode 2 may also change scheduling priority or another writer-level behavior. Do not conclude from seven CUs alone that fewer waves are optimal: CU count affects aggregate parallelism and tail shape, but the right resident-wave count also depends on memory latency, instruction-level parallelism, tile duration, cache reuse, and workgroup count. The supplied occupancy audit refutes the premise of globally starved occupancy, and no literature found establishes an exact waves/SIMD target for this part.

**Confidence:** `VERIFIED` for `MaxOccupancy`'s documented intent and the `DeviceLDS/N` pad calculation in the inspected source; `PARTIAL` for transfer of current-source details to v4.44; `UNVERIFIED` for mode-2 implementation details from public primary-source documentation and for an optimal target occupancy on gfx90c.

## Q4. `LocalSplitU` and `GlobalSplitU`: legality, cost, and seven-CU quantization

**Direct answer — a necessary correction to the premise.** `LocalSplitU` is the third `WorkGroup` dimension; the first two dimensions determine the output tile dimensions (`MacroTile0 = WorkGroup[0] * ThreadTile[0]`, `MacroTile1 = WorkGroup[1] * ThreadTile[1]`). In the inspected Tensile classic-kernel implementation, `LocalSplitU` splits the summation/U dimension **inside a workgroup**. It does not split the MacroTile M extent, and it does not multiply the number of output workgroups. Workgroup threads are `WorkGroup[0] * WorkGroup[1] * LocalSplitU` for the non-MI classic path, subject to wavefront and kernel-family constraints. It can add partial accumulation/reduction work and synchronization while reducing the per-part K work; because it does not increase the output-grid count, it is not a general CU wave-fill lever. [Tensile parameter documentation for `WorkGroup`, `MacroTile`, `DepthU`, and split controls](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html); [TensileLite `Solution.py`, classic workgroup and tile derivation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3840); [LSU legality checks](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5762).

The inspected newer TensileLite source has an explicit TODO/guard limiting `LocalSplitU` to single-precision or Int32 compute types; that would rule it out for complex C/Z and other types. This is **not asserted as the exact local v4.44 legality rule** because the project's own tree is patched and was not independently fetched here. The important action is to verify the local dtype guard before generating any complex `LocalSplitU>1` candidates. The source also checks divisibility relationships including `NumThreads % MacroTile0 == 0` and `(MacroTile0 * MacroTile1) % NumThreads == 0`, plus store/vectorization constraints. [TensileLite `Solution.py`, LSU validation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5762).

`GlobalSplitU` is a different mechanism: it partitions K across separate workgroups, increases the grid by the split factor, and then combines partial output. Tensile documents single-buffer/atomic and multiple-buffer/post-reduction paths; these trade extra workgroup parallelism for atomics or workspace writes and a final reduction. For a multiple-buffer method, workspace traffic scales approximately with `GSU * M * N * bytesPerOutput`, in addition to the partial stores and reduction reads; a single-buffer atomic path instead incurs atomic updates. The precise selected method is kernel/library dependent. [Tensile `Common.py`, GSU modes and workspace/reduction discussion](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2043-L2095).

**Complex restriction: policy, not mathematical impossibility.** Complex GEMM can mathematically form independent K-partial products and reduce them, so complex arithmetic is not inherently incompatible with split K. The inspected TensileLite implementation's supported-type predicate excludes complex, and generic documentation/comments are broader than that actual predicate. The project gate's reported prohibition is therefore a **Tensile implementation/policy restriction** on its Assembly path, unless its local source demonstrates an additional arithmetic-correctness issue. Treat the gate's prohibition as authoritative for tuning; do not try to force an invalid complex GSU candidate. In the inspected current TensileLite code, support is conditionally enabled for single precision, some double paths with `BufferStore`, Int32 destination, and certain assembly half paths with constraints. [TensileLite `Solution.py`, GSU support predicate and half-edge constraint](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5802); [Tensile `Common.py`, generic GSU discussion](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2043-L2095).

### Seven-CU arithmetic

For a square output with dimension N, square output tile T, and K split factor S (normally S=1 for unsupported dtypes), define `G = ceil(N/T)^2 * S`. A simple CU-slot utilization measure is `G / (7 * ceil(G/7))`; the last batch has `G % 7` active CUs, or all seven if the remainder is zero. This measures scheduling quantization only, not tile efficiency, resource occupancy, per-tile duration, reduction cost, or cache behavior.

| N | T | Output tiles `ceil(N/T)^2` | CUs idle in last batch | Last-batch idle fraction | Whole-grid CU-slot utilization |
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

A grid that divides across CU batches well may still lose because its tiles are inefficient or because S>1 adds reduction traffic. For example, GSU can change the slot arithmetic from `G` to `G*S`, but its benefit must exceed partial-sum and reduction overhead. The table therefore does **not** identify the fastest T/S combination. It shows why underfilled grids are a concern for small N and why quantization alone becomes negligible on sufficiently large grids.

**Confidence:** `VERIFIED` for split mechanisms and inspected-source checks; `PARTIAL` for transferring newer TensileLite legality checks to the local v4.44 gate; arithmetic is exact under the stated square-tile/grid assumptions; the time-minimizing combination is `UNVERIFIED` without timing data.

## Q5. `NumLoadsCoalescedA/B`: exact derived-geometry legality

**Direct answer — it changes the load tile's strip-mining/address layout, not `VectorWidth` itself.** Tensile defines `NumLoadsCoalesced` (NLC) as how many per-thread loads are distributed along the coalesced dimension. It affects the division of the tile into coalesced/perpendicular load dimensions and therefore the generated address pattern and register offsets. `VectorWidth`/`GlobalLoadVectorWidthA/B` determines how many contiguous elements are loaded together; NLC is a separate axis, although their derived `NumLoads` and divisibility constraints couple them. Tensile's own documentation describes NLC as the number of loads along the coalesced dimension. The inspected `Solution.py` computes `totalVectors = totalElements / GlobalReadVectorWidth`, then `NumLoads = totalVectors // NumThreads`; its NLC legality path filters using these derived geometry values. [Tensile parameter documentation](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html); [TensileLite `Solution.py`, `NumLoads` and classic load-tile derivation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3923); [NLC divisibility filters](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3950).

**Rule caveat.** There is no reliable universal legality predicate using only `VectorWidth`, bytes per element, and the name of the contraction layout: Tensile's NLC selection also depends on tile elements, global-read vector width, threads, `DepthU`, macro-tile size, transpose/layout orientation, and the `enableGLTrX` path. The complete rule can be tested in Python once the same derived values used by Tensile are available. In the source version inspected, a fixed positive `k` is legal when it divides `NumLoads`, divides `totalVectorsCoalesced`, and the perpendicular count `NumLoads // k` divides `totalElementsPerp`; the latter two geometry inputs swap when `enableGLTrX` is enabled.

```python
def nlc_is_legal(k, num_loads, total_vectors_coalesced,
                 total_elements_perp, enable_gl_tr_x=False):
    """Mirror Tensile's classic fixed-NLC divisibility filter.

    Inputs must be Tensile's derived counts for one operand, not raw
    tile sizes. The caller must construct them using the correct TLU/layout
    and GlobalReadVectorWidth path.
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

Separately enforce Tensile's vector-width byte limit supplied in the project brief (`VectorWidth * bytesPerElement <= 16` and the corresponding global-load-width constraint), along with datatype/layout rules. The supplied validation observations (NLCA=2 for only selected dtype/VW cells) are consistent with NLC legality being geometry-dependent; they are not enough to derive NLC from VW alone. See [Tensile parameter definitions](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html) and [Tensile benchmarking examples sweeping NLC with other parameters](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/benchmarking.html).

**Confidence:** `VERIFIED` for source-level divisibility filters in the inspected TensileLite version; `PARTIAL` for direct source-version equivalence to the local v4.44 fork; a raw-input-only rule is **not supported** by the inspected source.

## Q6. `InnerUnroll`: loop factorization and pressure tradeoff

**Direct answer — `VERIFIED` for factorization; `PARTIAL` for exact local instruction scheduling.** In the inspected Tensile classic path, `DepthU` is divided by `LocalSplitU`, and the resulting unroll count is divided by `InnerUnroll`; the effective relationship is `DepthU = LoopUnroll * InnerUnroll * LocalSplitU` for legal integral configurations. `DepthU` is the K-depth represented by an unrolled tile step; `LoopUnroll` is derived; `InnerUnroll` changes how that total is factored into inner unrolling versus loop iterations. It is not an independent way to increase the K tile without consequences. [TensileLite `Solution.py`, `LoopUnroll`/`InnerUnroll` derivation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6584); [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html).

A larger `InnerUnroll` can reduce the frequency of outer loop-control operations and expose more adjacent arithmetic/load work in one body, but increases static instruction body size and can extend value lifetimes or raise register pressure. Those effects are plausible from the loop factorization; no measured gfx90c ablation quantifying them was found. Global prefetch and inner-unroll are not independent: prefetch holds future data/address state live, while a larger inner body can increase simultaneous live values. If the objective for CC/ZZ is fewer non-FMA issue slots, inspect disassembly to determine whether loop branches/address-update instructions actually decline and whether the FMA sequence is preserved; do not assume a larger `InnerUnroll` reduces all non-FMA instructions. Check exact divisibility (`DepthU % (LocalSplitU * InnerUnroll) == 0`) and any tail/assertion constraints before compiling. [TensileLite derivation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6584); [Tensile `Common.py`, assertions and prefetch options](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032).

**Confidence:** `VERIFIED` for the derivation in inspected source; `PARTIAL` for the precise local assembly scheduling effect and any performance gain.

## Q7. `FractionalLoad`: partial workitem participation in a buffer load

**Direct answer — `VERIFIED` for the mechanism; no gfx90c cost curve found.** Tensile describes `FractionalLoad` as permitting some workitems not to participate in the final buffer load, allowing more flexible choices of `DepthU`. The documented modes trade additional address/temporary state and vector arithmetic: mode 1 can require an additional address VGPR for an edge; mode 2 can use a temporary VGPR inside the unroll loop and can save a VGPR when both A and B take the fractional-edge route, at the cost of vector ALU instructions. [Tensile `Common.py`, `FractionalLoad`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2390-L2397).

**Which shapes?** Evaluate it where K-tail/divisibility restrictions prevent a useful `DepthU` or vectorized load choice, especially if the problem size is not divisible by the load/tile grouping. Non-power-of-two dimensions alone do not prove it helps; a size can be divisible by the actual `DepthU` and load geometry. For shapes whose relevant dimensions satisfy the same divisibility assertions and have no fractional tail, the source gives no reason to pay extra address or vector-ALU cost. Whether the writer eliminates all extra path cost when the shape is aligned is version- and specialization-dependent; this was not measured here. Make this a lower-priority conditional factor for the 1000/1365-like cases after computing their exact K/load-tail status, not a global default.

**Confidence:** `VERIFIED` for stated source semantics; `UNVERIFIED` for exact aligned-shape overhead or benefit on the local gfx90c kernels.

## Q8. `NonTemporalA/B`: cache hints and what they can actually save

**Direct answer — do not model the knob as removing operand traffic.** A GEMM workgroup still needs the A and B values required for its K iterations; staging through LDS does not by itself eliminate global loads. A non-temporal hint can affect cache/coherence/allocation treatment of those requests, and may help avoid retaining streaming lines that have little reuse, but its effect depends on the memory instruction and cache modifiers emitted for the architecture. It does not eliminate the necessary operand bytes from the memory hierarchy.

AMD's LLVM AMDGPU backend documentation says GFX6–GFX9 non-temporal global memory operations are lowered to global/buffer/flat load/store forms with cache/coherence modifiers; this is a primary indication that the attribute changes the memory operation, but **it is not sufficient evidence that `NonTemporalA/B` always bypasses the gfx90c L2**. Check the exact Tensile v4.44 emitted instruction and modifiers for each tested solution. [LLVM AMDGPU usage: memory operation and non-temporal lowering](https://rocm.docs.amd.com/projects/llvm-project/en/latest/LLVM/llvm/html/AMDGPUUsage.html).

No measured result specifically showing an APU GEMM benefit from these knobs was verified. Large tensors may stream enough data to compete with the shared 1 MB L2, but GEMM also reuses operand tiles across adjacent output workgroups; disabling useful caching can increase DDR traffic. `WorkGroupMapping` exists in Tensile to influence workgroup traversal/cache locality, so evaluate `NonTemporalA/B` jointly with the current WGM values on large shapes rather than declaring them universally complementary. [Tensile kernel-parameter documentation](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html).

**Confidence:** `VERIFIED` that AMD documents a GFX6–GFX9 non-temporal lowering path; `PARTIAL` about exact Tensile-to-modifier mapping; `UNVERIFIED` for L2 bypass semantics and any measured gfx90c APU GEMM gain.

## Q9. Global/local prefetch and the `*Read2` / `*Write2` controls

### `PrefetchGlobalRead`

**Direct answer — resource-bearing pipeline transformation.** Tensile documents `PrefetchGlobalRead=1` as loading global data for a later K iteration ahead of its use. The source comments state that this path uses a second LDS buffer and VGPRs to hold data between global load and LDS write. Mode 2 adds another prefetch stage while moving VGPR-held data into LDS. It can overlap memory latency with useful work, at a cost in registers and LDS allocation. [Tensile `Common.py`, PGR/PLR buffer comments](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032); [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html).

For a current allocation `L` bytes per workgroup, doubling the buffer count approximately changes the allocation to `2L` before alignment/other allocations. The absolute 64 KiB legality threshold means a simple double buffer fits only when `L <= 32 KiB`; 16–25 KiB current allocations become roughly 32–50 KiB, still under the absolute limit but with materially fewer workgroups fitting. A kernel already bound by LDS capacity can thus lose residency even where the double-buffered solution remains legal. Compute the exact writer-emitted LDS allocation, not just the mathematical tile footprint, and reject candidates exceeding the per-workgroup limit. For each live candidate, compare generated `LDS` and VGPR metadata alongside runtime.

### `PrefetchLocalRead`

The source describes PLR as buffering local-read data into VGPRs; the buffered VGPR count is related to `min(PrefetchLocalRead + 1, LoopIters)`. Larger look-ahead can cover LDS-read latency but increases VGPR use and live ranges. Since LDS bandwidth is accepted as oversupplied in the supplied hardware brief, this factor should be judged on latency/dispatch overlap and register effects, not on a presumed LDS-throughput ceiling. [Tensile `Common.py`](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032).

### `LocalRead2A/B`, `GlobalRead2A/B`

The upstream `Common.py` comments describe these `*Read2` controls as combining multiple reads into an instruction, with an instruction-count benefit but more constrained immediate-offset encoding and possible arithmetic to advance/reset offsets. Critically, that same source labels the implementation **“not used yet.”** The available documentation therefore does not establish that these switches change emitted code in the local v4.44 assembly path. Do not spend a material part of the 10-hour run assuming instruction-count reduction: first verify the local kernel writer has an active generation path and inspect the emitted ISA. Combining loads into a paired instruction is not the same thing as allocating a second LDS buffer; the documented double-buffer capacity cost belongs to the prefetch path. [Tensile `Common.py`, `GlobalRead2A/B`, `LocalRead2A/B` and related scheduling parameters](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2122-L2167).

**Confidence:** `VERIFIED` for PGR/PLR resource tradeoffs in inspected source; `PARTIAL` for exact emitted allocation in local v4.44; `UNVERIFIED` that `*Read2` controls are active in this local path.

## Q10. Are the untouched knobs worth the 10-hour budget?

**Direct answer — yes as a targeted, dependency-aware screen; no defensible numeric yield can be assigned.** There is no verified published ablation ranking these exact Tensile controls on gfx90c, and no source found that supports a percentage expected speedup from them. Tensile's own benchmarking guide explicitly demonstrates sweeping parameters such as `PrefetchGlobalRead`, `NumLoadsCoalescedA/B`, `ThreadTile`, and related controls in multi-stage benchmark configurations, which confirms they are legitimate empirical search dimensions. It does not establish their expected effect size on the target. [Tensile benchmarking guide](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/benchmarking.html).

Because the tile search has already measured 5,757 kernels and the additional knobs are untouched, a new screen has informational value. A naïve one-knob-at-a-time sweep, however, misses interactions and can misclassify an option whose behavior is conditional on another. The dependencies that are explicitly documented are material: `UseSgprForGRO` depends on `BufferLoad` and pointer-shift/assertion legality; `StaggerU` interacts with `WorkGroupMapping` and may be ignored without buffer loads; `NumLoadsCoalesced` legality depends on the load geometry; `PrefetchGlobalRead` changes LDS and VGPR use; and `InnerUnroll` changes loop factorization. A fractional-factorial or D-optimal screening design that deliberately includes these interactions is better suited to a few hundred candidates than treating all factors independently.

**Recommended use of the 10-hour run:**

1. **Preflight at zero GPU cost:** use the local v4.44 legality checks and emitted code-object metadata to remove invalid combinations and duplicate candidates (especially StaggerU values that have no effect on `BufferLoad=0` if local behavior matches upstream).
2. **High-priority screen:** test `UseSgprForGRO` on complex-double and selected complex-single candidates with `BufferLoad=1` and legal assertions; test a small set of `InnerUnroll` values on issue-bound CC/ZZ; sweep `NumLoadsCoalescedA/B` only over values passing the exact load-geometry predicate; compare `PrefetchGlobalRead` modes while recording the LDS/VGPR delta.
3. **Block and randomize measurements:** keep each shape/dtype as a block; randomize config order so thermal/DVFS drift is not confounded with one knob; interleave a known reference solution and repeat it often enough to estimate this box's local noise floor. Use the corpus' known warm/clock protocol rather than treating one timing as ground truth.
4. **Spend the remaining budget on interactions and candidates with a physical rationale:** `StaggerU × WorkGroupMapping`; `UseSgprForGRO × BufferLoad/GlobalLoadVectorWidth`; `PrefetchGlobalRead × DepthU/InnerUnroll`; and `NLC × VectorWidth × operand layout`. Evaluate `FractionalLoad` primarily for true K/load tails and `NonTemporalA/B` primarily on large streaming cases. Keep `MaxOccupancy` and mode 2 low priority because the supplied corpus does not show a general occupancy starvation problem and source supports cache-thrashing mitigation as the primary justification for the cap.

**Honest expected yield:** a few shape-specific improvements are plausible, particularly where address VGPRs/instructions or loop overhead matter, but **no numeric yield is evidence-backed**. Broad gains are less certain because the current corpus reports no spills and no global occupancy famine; some candidate knobs may be no-ops in this kernel path, while others can trade one scarce resource for another. The most valuable result of a well-designed screen may be eliminating low-value controls and establishing which mechanisms are actually active on this local writer.

**Confidence:** `VERIFIED` that Tensile's own workflow treats these as tunable parameters; `PARTIAL` that the cited latest docs exactly match the local 4.44 fork; `UNVERIFIED` any numeric speedup forecast for the targeted device.

---

## Legality and quantization rules the project can implement

This section collects reusable rules with source provenance. It intentionally separates **exact tests on Tensile-derived variables** from rules that require kernel-writer-specific inputs.

### 1. NLC legality

Use the `nlc_is_legal` helper in Q5. Its inputs (`num_loads`, `total_vectors_coalesced`, `total_elements_perp`) need to be calculated by the same code path as Tensile; computing them from `VectorWidth` and bytes/element alone omits the thread-tile, workgroup, depth, and transpose/layout details. Source: [TensileLite `Solution.py` load geometry](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3923) and [NLC divisibility checks](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3950).

### 2. `MaxOccupancy` LDS cap

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

The source performs architecture-capacity-based LDS padding, then applies allocation rules; the helper is a **nominal model**, not a replacement for actual emitted `LDS` and the target runtime's resource allocations. Sources: [Tensile parameter comment](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2723-L2739); [occupancy-oriented LDS code](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6228).

### 3. Seven-CU output-grid quantization

```python
from math import ceil

def cu_grid_stats(M, N, macro_tile_m, macro_tile_n,
                  cu_count=7, global_split_u=1):
    """Grid-slot utilization only; does not model per-CTA time or reduction cost."""
    if min(M, N, macro_tile_m, macro_tile_n, cu_count, global_split_u) <= 0:
        raise ValueError("dimensions and split counts must be positive")
    base_grid = ceil(M / macro_tile_m) * ceil(N / macro_tile_n)
    grid = base_grid * global_split_u
    full_batches = grid // cu_count
    tail = grid % cu_count
    batches = full_batches + (1 if tail else 0)
    idle_cus_in_tail = 0 if tail == 0 else cu_count - tail
    slot_utilization = grid / (cu_count * batches)
    return {
        "base_output_tiles": base_grid,
        "workgroups_including_GSU": grid,
        "batches_of_CUs": batches,
        "tail_active_CUs": cu_count if tail == 0 else tail,
        "tail_idle_CUs": idle_cus_in_tail,
        "tail_idle_fraction": idle_cus_in_tail / cu_count,
        "grid_CU_slot_utilization": slot_utilization,
    }
```

`LocalSplitU` is intentionally absent from the output-grid multiplier: it changes workgroup internals, not the count of output-tile workgroups. `GlobalSplitU` multiplies that count but adds partial-sum/reduction cost. This calculation can quantify a tail, not pick the fastest tile/split combo without per-candidate timings.

### 4. `InnerUnroll` divisibility precheck

```python
def inner_unroll_is_integral(depth_u, local_split_u, inner_unroll):
    if min(depth_u, local_split_u, inner_unroll) <= 0:
        return False
    divisor = local_split_u * inner_unroll
    return depth_u % divisor == 0 and depth_u // divisor >= 1
```

This mirrors the inspected source's loop-factorization requirement, but is only a first-pass shape rule. It does not replace all type, edge-tail, vectorization, or assembly-path checks in the target's v4.44 `SolutionStructs.py`. Source: [TensileLite `Solution.py`](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6584).

---

## Techniques we could adopt

| knob / technique | source | what it changes in the emitted kernel | register/LDS cost | expected direction to test | confidence |
|---|---|---|---|---|---|
| `UseSgprForGRO` | [Tensile `Common.py` lines 2345–2388](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2345-L2388) | Uses a VGPR base plus SGPR offsets for buffer-load addresses | VGPR address state falls; SGPR count and scalar address setup can rise | Test `1` against `0` on legal ZZ/CC candidates with `BufferLoad=1`; check assertions and scalar pressure | `VERIFIED` mechanism; gain unmeasured |
| `BufferLoad` (dependency factor) | [Tensile `Common.py` lines 2270–2388](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2270-L2388) | Changes flat/global address path to buffer-load offsets and edge handling | Can reduce address VGPR use; 32-bit buffer bounds and ShiftPtr constraints apply | Treat as a paired legality factor for `UseSgprForGRO`, not an unrelated global sweep | `VERIFIED` |
| `StaggerU` | [Tensile `Common.py` lines 2609–2662](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662) | Changes K/U starting offsets across workgroups to spread aligned accesses | Usually little direct LDS/VGPR cost; can reduce L2 reuse or add address setup | Compare 0 with a small subset of nonzero values on large K; pair with WGM | `VERIFIED` mechanism; gfx90c value unknown |
| `StaggerUStride`, `StaggerUMapping` | [same source](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2609-L2662) | Sets byte step and workgroup-coordinate source for staggering | Address offset math; cache reuse and memory channel behavior may change | Defer until `StaggerU × WorkGroupMapping` main test indicates effect | `PARTIAL` on target relevance |
| `WorkGroupMapping` (pairing factor) | [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html) | Reorders workgroup traversal to influence tile/cache locality | No inherent extra LDS buffer; may change reuse | Retain current 4/8 baseline and test with `StaggerU=0/nonzero` | `VERIFIED` rationale; target optimum unmeasured |
| `MaxOccupancy` | [Tensile parameter docs/source](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2723-L2739) | Pads per-WG LDS allocation to cap concurrent workgroups/CU | More LDS reserved per WG, fewer CTAs can reside | Keep 40 as control; test a lower cap only where cache-thrashing evidence exists | `VERIFIED` mechanism; no target benefit established |
| `AggressivePerfMode` | [parameter schema](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py) | Modes can change priority/occupancy handling as described by the project; mode-2 details need local-source confirmation | A mode-2 LDS cap limits resident waves; any priority effects are writer-specific | Low-priority experiment; compare only on kernels whose measured residency exceeds the alleged two-wave cap | `PARTIAL` |
| `LocalSplitU` | [Tensile parameter docs](https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html), [LSU legality source](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L5762) | Splits the K/U work inside a workgroup | Extra internal partial-sum/reduction and threads; may change LDS/register requirements | Do not treat as multiplying the output grid; verify local dtype gate before attempting complex | `VERIFIED` semantics; v4.44 type gate partial |
| `GlobalSplitU` | [Tensile `Common.py` lines 2043–2095](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2043-L2095) | Creates separate K-partial workgroups and reduction/atomic combine | Workspace/partial stores and extra reduction or atomic traffic | Only test on gate-approved SS/DD cells where short output grids justify extra K parallelism | `VERIFIED` general mechanism; local type legality given by brief |
| `NumLoadsCoalescedA/B` | [TensileLite load geometry](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L3950) | Changes coalesced vs perpendicular distribution of a thread's loads | Changes address/register layout; not itself a vector-width setting | Generate only source-legal NLC candidates; compare paired values by layout/VW | `VERIFIED` legality structure |
| `InnerUnroll` | [TensileLite loop derivation](https://sources.debian.org/src/hipblaslt/7.2.4%2Bdfsg-1~exp1/tensilelite/Tensile/SolutionStructs/Solution.py/#L6584) | Changes factorization of `DepthU` into inner body and loop trip count | Bigger inner body can increase live ranges/code size; can reduce loop-control frequency | Prioritize a modest legal screen on CC/ZZ; inspect non-FMA slots and VGPR/SGPR counts | `PARTIAL` on exact assembly effects |
| `FractionalLoad` | [Tensile `Common.py` lines 2390–2397](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2390-L2397) | Allows partial participation in final buffer load/tail path | Depending on mode, extra address or temporary VGPR and vector ALU | Test on real K/load tails; do not enable globally on aligned cases without evidence | `VERIFIED` semantics |
| `NonTemporalA/B` | [LLVM AMDGPU usage](https://rocm.docs.amd.com/projects/llvm-project/en/latest/LLVM/llvm/html/AMDGPUUsage.html) | Changes non-temporal/cache-coherence treatment of global loads | No direct LDS reduction; cache reuse and system-memory traffic can move either way | Test only for large streaming inputs; inspect exact gfx9 instruction modifiers | `PARTIAL` |
| `PrefetchGlobalRead` | [Tensile `Common.py` lines 1950–2032](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032) | Loads the next K tile ahead; higher mode adds pipeline work | Typically another LDS buffer plus VGPR data/address state | Test 0/1 first; include 2 only if generated code and resource margins justify it | `VERIFIED` tradeoff |
| `PrefetchLocalRead` | [same source](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L1950-L2032) | Buffers LDS-read values ahead in VGPRs | More buffered VGPRs as lookahead rises | Sweep conservatively, record VGPR delta and latency; avoid blind large PLR on register-heavy cells | `VERIFIED` mechanism |
| `LocalRead2A/B`, `GlobalRead2A/B` | [Tensile `Common.py` comments](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py#L2122-L2167) | Intended paired-read instruction grouping / scheduling | Could reduce instruction count but offsets become more constrained; source says “not used yet” | Verify local writer support before allocating GPU budget | `UNVERIFIED` for target path |

---

## Not verified / do not cite as established

1. **No numeric speedup for any of the untouched controls on gfx90c.** No full-text benchmark or open result was found that measures `UseSgprForGRO`, `StaggerU`, `MaxOccupancy`, `AggressivePerfMode`, `InnerUnroll`, or these exact combinations on a seven-CU Renoir/Cezanne APU.
2. **Exact `AggressivePerfMode=2` public implementation in the local v4.44 path.** The two-wave/SIMD LDS-cap behavior is supplied by the project brief, but I did not independently trace that precise mode through the project's patched writer and emitted code.
3. **`LocalSplitU` exact legality on the project commit.** The inspected TensileLite implementation rejects non-single/non-Int32 compute types, but it is newer than local Tensile v4.44. Do not assume complex LSU is legal; inspect local `SolutionStructs.py` and generated code first.
4. **`StaggerU` with `BufferLoad=0`.** Upstream source says the setting is ignored without buffer loads; the project gate's validation allows it. The emitted local assembly decides whether those are true experiments or duplicates.
5. **L2 bypass for `NonTemporalA/B` on gfx90c.** LLVM documentation supports GFX6–GFX9 lowering for non-temporal memory operations, but the exact Tensile modifier mapping and L2 allocation/retention semantics for the local path were not verified from target assembly or a Vega-class measurement.
6. **A universal NLC rule from only VW, element size, and contraction layout.** Tensile's actual rule depends on derived counts for vector loads, threads, tile shape, and orientation. The supplied helper is exact only when fed Tensile's derived values.
7. **That `*Read2` knobs are live in local v4.44.** Current upstream comments say the relevant paired instruction path is “not used yet”; confirm the branch before testing.
8. **A unique fastest tile/split for 128³–2048³ based on wave quantization alone.** The arithmetic table only quantifies batch fill. It omits per-tile efficiency, LDS/VGPR residency, tile work, cache behavior, launch overhead, and split-reduction cost.
9. **The precise “gfx1151 `auto` DPM vs `profile_peak` improved end-to-end by 37.8%” claim.** It remains unverified in this targeted pass; do not use it as a numeric prior for gfx90c.
10. **The alleged ASPLOS'20 paper “A Faster Tiling Approach for AMD GPUs” and the exact COSTA/BASS/BEST/GemmLab attributions from pass 1.** Exact-title/source checks in the earlier pass did not establish a primary publication and matching result for those names. They should not be cited as confirmed techniques without a resolvable publisher page, DOI, or paper PDF.
11. **The 142,782 figure from arXiv:2507.15277.** The abstract-level source describes 142,782 device/input/parameter performance measurements across five GPUs, not 142,782 unique kernel configurations. The paper page is here: [A Few Fit Most: Improving Performance Portability of SGEMM on GPUs using Multi-Versioning](https://arxiv.org/abs/2507.15277). The full text was not audited in this pass, so any exact experiment/protocol statement beyond its abstract should be marked `PARTIAL`.
12. **A published paper addressing seven-CU/non-power-of-two CU raster order specifically.** No such paper was verified. Use the arithmetic helper above and target measurements rather than attributing a special algorithm to prior work.

## What this changes in the next candidate run

- **`UseSgprForGRO`: test `1` for legal complex-double candidates first**, with `BufferLoad=1`, supported assertions, and ISA/resource inspection; keep `0` as the paired baseline.
- **`BufferLoad`: treat as a dependency of `UseSgprForGRO`**, not an unstructured independent toggle. Confirm pointer-shift and range legality.
- **`InnerUnroll`: add a small legal screen for CC/ZZ**, measuring actual branch/address-update instructions alongside VGPR and SGPR counts.
- **`PrefetchGlobalRead`: start with `0` versus `1`**, recording actual LDS/VGPR changes; do not assume latency hiding is free when 61.7% of kernels are LDS-capacity-bound.
- **`PrefetchLocalRead`: use a modest range**, since increasing it retains more values in VGPRs.
- **`NumLoadsCoalescedA/B`: generate candidates from Tensile's derived divisibility checks**, then pair NLC changes with `VectorWidth` and layout instead of broad blind enumeration.
- **`StaggerU`: test `0` against a few nonzero values and pair with `WorkGroupMapping=4/8`** on large-K cases; eliminate no-op `BufferLoad=0` variants if the local writer matches upstream behavior.
- **`StaggerUStride` and `StaggerUMapping`: defer until `StaggerU` itself shows a measurable effect**; the gfx900/gfx906 stride rationale is not a gfx90c result.
- **`FractionalLoad`: reserve for dimensions with actual K/load tails** or for a measured trade that enables a better `DepthU`.
- **`NonTemporalA/B`: keep exploratory and large-shape-specific**, and inspect the emitted load modifiers before interpreting the outcome as L2 bypass.
- **`MaxOccupancy`: retain 40 as control; test a cap only where cache-thrashing evidence exists.** A seven-CU part alone does not prove that capping helps.
- **`AggressivePerfMode=2`: low priority** until the local writer confirms the mode-2 path and candidate kernels have more than two waves/SIMD available to cap.
- **`LocalSplitU`: do not treat as output-grid wave fill; verify the v4.44 compute-type guard before generating complex candidates.**
- **`GlobalSplitU`: test only the types the gate accepts**, and measure the extra partial-sum / reduction cost instead of evaluating grid fill in isolation.
- **`GlobalRead2A/B` and `LocalRead2A/B`: hold until generated ISA proves the switches are implemented in the local branch.**
- **Design the 272-candidate run as a randomized, blocked, dependency-aware screening experiment**, reserving repeats of a reference kernel to track the box's noise and thermal drift. Do not promise a speedup percentage before measuring it.
