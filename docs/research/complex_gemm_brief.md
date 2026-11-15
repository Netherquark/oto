# Research Brief — Complex-Precision GEMM on pre-MFMA GCN/Vega (gfx90c)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


**Scope.** Complex single/double GEMM (CGEMM/ZGEMM) on the pre-MFMA assembly path
(Tensile → rocBLAS, ROCm < 4.5), targeting an AMD **gfx90c** APU: GCN5.1, 7 CU,
Wave64, 64 KiB LDS/CU, FP64 1/16, **no matrix cores / no dp4a / no packed-BF16**
([ROCm GPU specs](https://rocm.docs.amd.com/en/docs-6.1.5/reference/gpu-arch-specs.html),
[TechPowerUp Renoir](https://www.techpowerup.com/gpu-specs/amd-renoir.g1058),
[LLVM AMDGPUUsage](https://llvm.org/docs/AMDGPUUsage.html)). All external claims are
URL-linked; the first-party gfx90c measurements in §6 come from this repo's
registry, with the live config-resolved per-cell winners in
`docs/gfx90c_tuning_guide.md` §13 §3 and `docs/gfx90c_results.md`.

## 1. Tensile's complex MAC is exactly four real FMAs
- `MAC_F32C_Plain` emits **four `_v_mac_f32`** per complex MAC: `Cr += Ar·Br`,
  `Cr += (−Ai·Bi)`, `Ci += Ar·Bi`, `Ci += (±Ai·Br)`. Complex-conjugate signs ride on
  free GCN operand negates, so there are no extra instructions
  ([Tensile MAC_F32C.py](https://github.com/ROCm/Tensile/blob/develop/Tensile/Components/MAC_F32C.py)).
- `FMA_F64C_Plain` emits **four `v_fma_f64`** on packed 64-bit VGPR pairs
  ([Tensile MAC_F64C.py](https://github.com/ROCm/Tensile/blob/develop/Tensile/Components/MAC_F64C.py)).
- The MFMA path is the same count: `numMfmaPerIter *= 4` and the comment "complex mul
  is emulated by 4 mfma insts"
  ([KernelWriter.py](https://github.com/ROCm/Tensile/blob/develop/Tensile/KernelWriter.py),
  [KernelWriterAssembly.py](https://github.com/ROCm/Tensile/blob/develop/Tensile/KernelWriterAssembly.py)).
- rocBLAS has **no host-side 3-GEMM split**: it maps `rocblas_float_complex` →
  `Tensile::DataType::ComplexFloat` and only adds conjugate ops
  ([rocBLAS tensile_host.cpp](https://github.com/ROCm/rocBLAS/blob/develop/library/src/tensile_host.cpp));
  non-MFMA Vega kernels come from the `nonMFMA_legacy` logic
  ([tuning data](https://github.com/ROCm/rocBLAS/tree/develop/library/src/blas3/Tensile/Logic/nonMFMA_legacy)).

## 2. BLAS accounting makes complex GEMM a 4× real GEMM
- BLAS charges **8·M·N·K** flops for CGEMM/ZGEMM vs 2·M·N·K for SGEMM/DGEMM — a 4×
  cost ([rocBLAS Programmer's Guide](https://rocm.docs.amd.com/projects/rocBLAS/en/latest/how-to/Programmers_Guide.html)).
- Hardware models agree: "the performance target of FP32 GEMM and CGEMM is 25% and
  6.25% of FP16" (so complex = ¼ of real), and an MXU doing a p-bit real M×N×K every
  *c* cycles needs **16·c** for the 2p-bit complex version
  ([M3XU, SC'24](https://intra.engr.ucr.edu/~htseng/files/2024SC-M3XU.pdf)).
- CLBlast labels CGEMM/ZGEMM as "complex single-precision **2xFP32** / 2xFP64"
  ([CLBlast](https://arxiv.org/abs/1705.05249)).

## 3. The honest ALU ceiling (and a correction)
Because one complex MAC = four FMAs = 8 BLAS flops = **2 flops per FMA** — exactly the
real-GEMM ratio — an ALU-bound complex GEMM has the *same* BLAS-8 GFLOPS ceiling as its
real counterpart. The "÷4" applies to *complex-MAC throughput*, not to BLAS-8 GFLOPS.
- On gfx90c (7 CU × 4 SIMD × 16 lanes × 2 × 1.8 GHz ≈ **1613 GFLOPS** FP32,
  FP64 = 1/16 ≈ **101 GFLOPS**;
  [ROCm specs](https://rocm.docs.amd.com/en/docs-6.1.5/reference/gpu-arch-specs.html),
  [Vega FP64 1:16](https://www.techpowerup.com/gpu-specs/radeon-rx-vega-64.c2871)):
  **CGEMM ≤ 1613 GFLOPS**, **ZGEMM ≤ 101 GFLOPS** in BLAS-8 terms.
- Complex-MAC throughput = peak/8: **≈202 G MAC/s (CGEMM)**, **≈12.6 G MAC/s (ZGEMM)**.
- Therefore a well-tuned CGEMM *should* match SGEMM GFLOPS; undershoot is an
  implementation (occupancy/register) problem, not a flop-accounting one.

## 4. 3M / 4M / 2M — definitions and instruction counts
- **4M** (expanded): `(ArBr−AiBi) + i(ArBi+AiBr)` = 4 mul + 2 add; with FMA + free
  negate it collapses to **4 instructions** per complex MAC (what Tensile emits).
- **3M** (Gauss/Karatsuba): `m1=ArBr`, `m2=AiBi`, `m3=(Ar+Ai)(Br+Bi)`,
  `Cr=m1−m2`, `Ci=m3−m1−m2` = **3 mul + 5 add = 8 scalar ops** (≈7 with FMA folding)
  per MAC; the pre-adds are 2 ops and the combine is 3 matrix adds
  ([Illinois CS374](https://courses.grainger.illinois.edu/cs374/fa2020/lec_prerec/11/11_3_0_0.pdf),
  [CMU handout](http://www.cs.cmu.edu/afs/cs.cmu.edu/academic/class/15251-f08/Site/Materials/Lectures/Lecture22/lecture22-handout.pdf),
  [John D. Cook](https://www.johndcook.com/blog/2021/06/13/gauss-multiplication)).
- **2M** (Caday, NVIDIA 2026): for integer real/imag, **2 real GEMMs** + quadratic
  pre/post; paired with Ozaki-II it computes a floating-point complex GEMM in "roughly
  twice the time of a real GEMM"
  ([arXiv:2609.05419](https://arxiv.org/abs/2609.05419)).

## 5. Which split wins, and when
- **Per complex MAC, 4M wins.** Karatsuba trades one multiply for extra adds; when mul
  and add share the same issue rate and FMA fuses them, that trade is a loss — 4
  instructions vs ≈7–8
  ([CMU](http://www.cs.cmu.edu/afs/cs.cmu.edu/academic/class/15251-f08/Site/Materials/Lectures/Lecture22/lecture22-handout.pdf)).
- **Per GEMM, 3M can win.** It runs **3 real GEMMs instead of 4**, and the pre/post work
  is only O(MK+KN+MN) — lower-order for large K. MAGMA built complex GEMM on this M3
  scheme and reached **79% of peak CGEMM / 71% ZGEMM on Fermi**
  ([MAGMA/Fermi](https://www.netlib.org/utk/people/JackDongarra/PAPERS/208_2010_an-improved-magma-gemm-for-fermi-gpus.pdf)).
  The cost is extra passes/workspace and 3 kernel launches.
- NPU work treats the choice as configuration-dependent: the Ascend study selects
  between 3M and 4M and reports **83.6% hardware utilization**
  ([MDPI Computers 2026](https://www.mdpi.com/2073-431X/15/7/407)).
- Net: a **fused 4M** kernel is instruction-optimal and traffic-free (why rocBLAS uses
  it); 3M/2M help only when the restructured real GEMMs are themselves efficient and
  the combine is amortized.
- **Numerical-stability caveat (Higham).** The three-multiply form is *not* merely a
  cheaper 4M: Higham's analysis reports up to **25 % arithmetic saving** but **lower
  numerical stability than the conventional four-multiply product**, practically
  useful only in suitable cases ([Higham, SIAM](https://epubs.siam.org/doi/10.1137/0613043)).
  So a 3M experiment must carry a high-precision reference and cancellation-heavy
  inputs, and must report max/relative error against the application's tolerance;
  do not assume the 25 % arithmetic saving becomes a 25 % kernel speedup — extra
  adds, temporaries, registers and traffic can erase it, especially at small K.
- **Quantitative form of the caveat (oneMKL's rounding model).** oneMKL documents
  first-order componentwise bounds for its `gemm3m`, illustrative of the 3M error
  model: `‖Ĉr−Cr‖∞ ≤ 2(n+1)u·‖A‖∞‖B‖∞ + O(u²)` and
  `‖Ĉi−Ci‖∞ ≤ 4(n+4)u·‖A‖∞‖B‖∞ + O(u²)`, with `u` the unit roundoff. These are
  theoretical, not measured gfx90c errors, but they are the reason a 3M experiment
  needs a high-precision reference on cancellation-heavy data
  ([oneMKL gemm3m](https://www.intel.com/content/www/us/en/docs/onemkl/developer-reference-c/2026-0/cblas-gemm3m.html)).

## 6. Measured gfx90c complex GEMM (first-party, this repo)
From the project registry (`gfx90c_results/registry.db`; this is a first-party
snapshot — the live config-resolved per-cell winners are in
`docs/gfx90c_tuning_guide.md` §13 §3 and `docs/gfx90c_results.md`, and the per-family theoretical
ceiling authority is `docs/gfx90c_theoretical_limits.md`):
CGEMM best **353.6 / median 264.4 GFLOPS**; ZGEMM best **22.5 / median 17.4 GFLOPS** —
about **16–22%** of the 1613/101 ceilings, versus the same deck's real-family results
(SGEMM peak 1283.5 ≈ 80%; DGEMM 99.0 ≈ 98%). The complex deck is still undertuned and
some runs were clock-suppressed (~1.175 vs 1.8 GHz), so these are a **floor, not a
ceiling**. For scale, published complex GEMMs sit well below real GEMM: MAGMA's 3M
reached 79%/71% of peak ([MAGMA](https://www.netlib.org/utk/people/JackDongarra/PAPERS/208_2010_an-improved-magma-gemm-for-fermi-gpus.pdf)),
and Ascend's cgemm loses utilization to real/imag unpacking and recombination
([Ascend scientific computing](https://arxiv.org/html/2607.20120v1)).

## 7. 2023–2026 complex GEMM without native complex units
The field reuses low-precision matrix engines; none of it is reachable on gfx90c
(no INT8/tensor engine), so it is context, not a route:

- **M3XU (SC'24):** reuses low-precision MXUs; 2p-bit CGEMM every 16c; **3.51×** over
  conventional vector units ([M3XU](https://intra.engr.ucr.edu/~htseng/files/2024SC-M3XU.pdf)).
- **Ozaki-II complex (2025):** casts complex GEMM onto INT8 modular GEMMs, using
  Karatsuba 3M per modular GEMM; **4.4–6.5× (CGEMM)** and **4.0–5.6× (ZGEMM)** over
  native cuBLAS on B200, with an MI300X/ZGEMM comparison
  ([arXiv:2512.08321](https://arxiv.org/abs/2512.08321)).
- **EmuGEMM (2026):** fused Scheme-II complex kernels beat cuBLAS ZGEMM up to **2.3×
  (Hopper) / 5.5× (Blackwell)** ([arXiv:2606.25453](https://arxiv.org/pdf/2606.25453)).
- **INT8 matrix-engine emulation (2025):** Ozaki-I for FP64/FP32 on INT8 engines
  ([arXiv:2508.03984](https://arxiv.org/html/2508.03984v2)).
- **oneMKL 2024 JIT:** generates CGEMM/ZGEMM microkernels for AVX/AVX2/AVX-512 — the
  no-tensor-core CPU path ([Intel](https://www.intel.com/content/www/us/en/developer/articles/technical/onemkl-improved-small-matrix-performance-using-just-in-time-jit-code.html)).

## 8. Exotic paths against the 4-FMA wall on gfx90c
Instruction-level levers are closed: gfx90c has no `v_dot*`/dp4a (gfx906+), no
`v_pk_fma_bf16` (any gfx9), no `v_mfma_*`, and — the correction that circulates
most often — **no packed/dual-lane FP32 FMA**: Vega lists `V_PK_FMA_F16` (packed
half) and `V_MAD_MIX_F32` (mixed-width) but not `V_PK_FMA_F32`, and
`V_MAD_MIX_F32` is not two independent packed FP32 FMAs
([AMD Vega ISA](https://www.amd.com/content/dam/amd/en/documents/radeon-tech-docs/instruction-set-architectures/vega-shader-instruction-set-architecture.pdf),
[LLVM AMDGPUUsage](https://llvm.org/docs/AMDGPUUsage.html),
[ROCm specs](https://rocm.docs.amd.com/en/docs-6.1.5/reference/gpu-arch-specs.html);
`docs/research/kernel_tuning.md` §1/§9). So the only real options are algorithmic/occupancy:

- (a) **3M/2M restructuring** to cut GEMM count 25–50%, accepting extra passes
  ([MAGMA](https://www.netlib.org/utk/people/JackDongarra/PAPERS/208_2010_an-improved-magma-gemm-for-fermi-gpus.pdf),
  [arXiv:2609.05419](https://arxiv.org/abs/2609.05419)) — with the Higham
  numerical caveat of §5;
- (b) **Ozaki/INT8 emulation** — moot without a fast low-precision engine
  ([arXiv:2508.03984](https://arxiv.org/html/2508.03984v2));
- (c) **occupancy/register tiling** — the demonstrated gfx90c bottleneck, the same
  GSU/WGM/MT/TT levers that lift real GEMMs, are the realistic route from ~20% toward the
  ~69–80% real-family bar (local analysis: `docs/gfx90c_theoretical_limits.md` §7).
  **The register-blocking reference is a trampoline, not an answer:** BLIS
  establishes register-resident output microtiles and operand reuse, but its CPU
  tile dimensions do not prescribe GPU thread tiles, and **no published rule proves
  one tile optimal under this project's per-thread bound `TT0*TT1*R ≤ 128`**
  ([BLIS](https://doi.org/10.1145/2764454)). Complex needs both real and imaginary
  accumulators, so operands, pointers, masks and temporaries consume more registers
  too. Treat the 128 bound as a **legality filter, not a performance proof**:
  enumerate legal configs, reject likely spills, estimate occupancy, benchmark the
  survivors. (`R` is the per-dtype accumulator VGPR weight — `S/H` 1, `D` 2, `C` 4,
  `Z` 8 — so the bound counts logical accumulators; `docs/research/kernel_tuning.md` §4.)

## 9. GlobalSplitU reachability on this port
GSU splits K across workgroups; legality is dtype-locked on the reachable writer
paths (`oto/tensile/gates/assembly.py`, `assembly_class_valid`):

- **complex (C/Z) and HPA GSU>1 is illegal** — there is no MFMA escape, and this
  port never forwards `GlobalSplitUAlgorithm` or a reduction workspace, so only the
  **SingleBuffer-atomic** path is reachable.
- **half-assembly GSU>1 stays illegal** while the deck ships
  `AssertFree0ElementMultiple = 1` (Tensile requires AF0EM≥2 for half GSU).
- **SS is the only GSU-legal family** (ladder {1,2,4}) — and only at small shapes
  (k≤512, M·N-tiles < ~7 waves), where it adds launch + atomic-write overhead.

For the complex families GSU is therefore **not a lever**; the split-complex route
(§4–§5, §8) is the only way to reduce per-GEMM work.

**A non-atomic split-K is a different design, not a reachable knob.** The literature
(CUTLASS, **[Transfer only]**) describes K-partitioned GEMM where each first-stage
workgroup writes its own complex partials to a **workspace** and a **second kernel
reduces them in a fixed order** — the deterministic, race-free counterpart of GSU's
beta-scaled atomic writes. Without a workspace there is no general race-free
cross-workgroup reduction. The cost is scratch writes/reads, a second launch and the
reduction; for small CC/ZZ the fill benefit may not cover it. Tensile's
`GlobalSplitU` is the atomic path; this port forwards neither
`GlobalSplitUAlgorithm` nor a reduction workspace, so a non-atomic fixup is **new
machinery**, not a config ([CUTLASS](https://docs.nvidia.com/cutlass/latest/media/docs/cpp/efficient_gemm.html);
`docs/research/kernel_tuning.md` §5/§8.7).

## 10. Non-temporal loads
`NonTemporalA/B/C/D` lowers to `buffer_load … th:TH_LOAD_NT` — a load-flavor knob,
not a class rule (`oto/tensile/gates/assembly.py`). It is narrow: do **not** use it
on normal tiled A/B (they reuse across K within the 1 MB L2 — NT would flush it); use
it on (a) the C operand read-modify-write, (b) single-K-pass GSU kernels where each
tile is read once. One legality-checked probe row per case is enough to decide.
"Non-temporal" must **not** be assumed to bypass every cache level; inspect the
emitted modifiers ("meaning depends on the emitted ISA cache modifiers",
`docs/research/kernel_tuning.md` §4).

## 11. Complex-double (ZGEMM) occupancy and FP64 ILP
ZGEMM runs on the FP64 VALU at 1/16 rate (§2–§3), so its ceiling is a *pipeline*
ceiling and its levers are concurrency and independent work, not arithmetic tricks.

- **No defensible universal "saturation" wavefront count exists for gfx90c FP64.**
  The concurrency needed to saturate the FP64 pipe depends on dependent-FMA
  latency, independent chains per thread, scheduling, VGPR allocation and memory
  stalls; generic occupancy docs give no gfx90c-specific FP64 saturation curve
  **[CHECK]**. Test thread-tile/accumulator count and unroll depth independently,
  tracking runtime against VGPR/occupancy. If more resident waves stop helping,
  stop chasing occupancy. Do **not** transfer MI50/MI60/CDNA/RDNA/NVIDIA
  thresholds to gfx90c.
- **Register blocking for 1/16-rate FP64.** The accumulator storage floor for real
  FP64 is `TT0*TT1*8` bytes per thread (its outputs alone); actual demand is higher
  (operands + temporaries), and complex-double keeps real *and* imaginary
  accumulators, doubling the logical storage. A larger tile improves reuse/ILP but
  lowers resident waves. Keep the project's measured **32×32** reference winner as
  a reference, not a literature-proven optimum; sweep adjacent legal tiles and
  inspect spills **[CHECK] no published gfx90c FP64 optimal tile found**. Upstream
  `vega10`/`vega20` non-MFMA rank-1 solutions are *implementation* evidence — the
  donors of `docs/gfx90c_tuning_guide.md` §13 §6 Route A — not a published optimum.
- **Complex-double is a standard tuning target, not a solved one.** CLBlast
  supports precision `6464` (complex-double) with its own tunable GEMM parameters
  ([CLBlast](https://github.com/CNugteren/CLBlast/blob/master/doc/tuning.md)), and
  BLIS describes a reusable microkernel framework
  ([BLIS](https://doi.org/10.1145/2764454)) — these establish the problem, not a
  portable tile optimum **[CHECK] no GCN5-specific complex-double tile
  recommendation found**. Tune complex-double independently, carrying both
  accumulators, reduction and temporary traffic, and an error check.
- **`InnerUnroll` / `DepthU` expose FP64 ILP.** More unrolling may reveal
  independent FP64 work and cut loop overhead, at higher VGPR (lower residency).
  Sweep `DepthU`/`InnerUnroll` with `TT0×TT1` fixed, then sweep the tile at the
  selected depths **[CHECK] no publication proves `DepthU` dominates FP64 ILP on
  GCN5**. Mechanics: `docs/research/kernel_tuning.md` §4.

## Quantitative guidance
- Ceilings (BLAS-8): **CGEMM = FP32 peak ≈ 1613 GFLOPS; ZGEMM = FP64 peak ≈ 101 GFLOPS**
  on gfx90c; complex-MAC rate = GFLOPS/8 (≈202 / ≈12.6 G MAC/s).
- Realistic acceptance bars track the real families **in the unit the client
  reports**: **CGEMM ≈ SGEMM ≈ 1119 GFLOPS; ZGEMM ≈ DGEMM ≈ 98.6 GFLOPS** in
  BLAS-8, which is **279.7 / 24.65** in the client's own count (Tensile charges
  2 flops per MAC for complex types, so a reported complex GFLOPS is ¼ of its
  BLAS-8 value -- `ContractionProblem.cpp:1108`). The first-party complex
  results (~346.7 / ~24.5 reported) are therefore **124 % / 99 % of their
  bars** -- the complex families are at 80-97 % of the FMA roof, and the
  "~25 % of the ceiling" reading was the unit error corrected on 2026-10-21
  (`docs/gfx90c_theoretical_limits.md` §5.2). **The headroom is not in the complex
  families at all**; it is in the three small cells (SS:256, HH:256, CC:192).
- Split choice: fused **4M** per MAC; consider **3M** only for large-K GEMMs where the
  O(N²) combine is negligible and the three real GEMMs run near their own efficiency.
