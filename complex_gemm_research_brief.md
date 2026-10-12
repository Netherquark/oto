# Research Brief — Complex-Precision GEMM on pre-MFMA GCN/Vega (gfx90c)

**Scope.** Complex single/double GEMM (CGEMM/ZGEMM) on the pre-MFMA assembly path
(Tensile → rocBLAS, ROCm < 4.5), targeting an AMD **gfx90c** APU: GCN5.1, 7 CU,
Wave64, 64 KiB LDS/CU, FP64 1/16, **no matrix cores / no dp4a / no packed-BF16**
([ROCm GPU specs](https://rocm.docs.amd.com/en/docs-6.1.5/reference/gpu-arch-specs.html),
[TechPowerUp Renoir](https://www.techpowerup.com/gpu-specs/amd-renoir.g1058),
[LLVM AMDGPUUsage](https://llvm.org/docs/AMDGPUUsage.html)). All external claims are
URL-linked; the first-party gfx90c measurements in §6 come from this repo's
registry, with the live config-resolved per-cell winners in
`potential_configs.md` §3 and `results.md`.

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

## 6. Measured gfx90c complex GEMM (first-party, this repo)
From the project registry (`gfx90c_results/registry.db`; this is a first-party
snapshot — the live config-resolved per-cell winners are in
`potential_configs.md` §3 and `results.md`, and the per-family theoretical
ceiling authority is `gfx90c_theoretical_limits.md`):
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
`v_pk_fma_bf16` (any gfx9), and no `v_mfma_*`
([LLVM AMDGPUUsage](https://llvm.org/docs/AMDGPUUsage.html),
[ROCm specs](https://rocm.docs.amd.com/en/docs-6.1.5/reference/gpu-arch-specs.html)).
So the only real options are algorithmic/occupancy:

- (a) **3M/2M restructuring** to cut GEMM count 25–50%, accepting extra passes
  ([MAGMA](https://www.netlib.org/utk/people/JackDongarra/PAPERS/208_2010_an-improved-magma-gemm-for-fermi-gpus.pdf),
  [arXiv:2609.05419](https://arxiv.org/abs/2609.05419));
- (b) **Ozaki/INT8 emulation** — moot without a fast low-precision engine
  ([arXiv:2508.03984](https://arxiv.org/html/2508.03984v2));
- (c) **occupancy/register tiling** — the demonstrated gfx90c bottleneck, the same
  GSU/WGM/MT/TT levers that lift real GEMMs, are the realistic route from ~20% toward the
  ~69–80% real-family bar (local analysis: `gfx90c_theoretical_limits.md` §7).

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

## 10. Non-temporal loads
`NonTemporalA/B/C/D` lowers to `buffer_load … th:TH_LOAD_NT` — a load-flavor knob,
not a class rule (`oto/tensile/gates/assembly.py`). It is narrow: do **not** use it
on normal tiled A/B (they reuse across K within the 1 MB L2 — NT would flush it); use
it on (a) the C operand read-modify-write, (b) single-K-pass GSU kernels where each
tile is read once. One legality-checked probe row per case is enough to decide.

## Quantitative guidance
- Ceilings (BLAS-8): **CGEMM = FP32 peak ≈ 1613 GFLOPS; ZGEMM = FP64 peak ≈ 101 GFLOPS**
  on gfx90c; complex-MAC rate = GFLOPS/8 (≈202 / ≈12.6 G MAC/s).
- Realistic acceptance bars track the real families: **CGEMM ≈ SGEMM ≈ 1119 GFLOPS;
  ZGEMM ≈ DGEMM ≈ 98.6 GFLOPS**; current first-party complex results (~354 / ~22.5) are
  ~25% of that — the headroom is tuning, not algorithm.
- Split choice: fused **4M** per MAC; consider **3M** only for large-K GEMMs where the
  O(N²) combine is negligible and the three real GEMMs run near their own efficiency.
