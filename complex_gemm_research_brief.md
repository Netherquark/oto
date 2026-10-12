# Research Brief — Complex-Precision GEMM on pre-MFMA GCN/Vega (gfx90c)

**Scope.** Complex single/double GEMM (CGEMM/ZGEMM) on the pre-MFMA assembly path
(Tensile → rocBLAS, ROCm < 4.5), targeting an AMD **gfx90c** APU: GCN5.1, 7 CU,
Wave64, 64 KiB LDS/CU, FP64 1/16, **no matrix cores / no dp4a / no packed-BF16**
([ROCm GPU specs](https://rocm.docs.amd.com/en/docs-6.1.5/reference/gpu-arch-specs.html),
[TechPowerUp Renoir](https://www.techpowerup.com/gpu-specs/amd-renoir.g1058),
[LLVM AMDGPUUsage](https://llvm.org/docs/AMDGPUUsage.html)). All external claims are
URL-linked; first-party measured numbers live in `results.md`.

## 1. Complex-MAC instruction counts — moved to code

Tensile's complex-MAC emission (four real FMAs per complex MAC), the BLAS-8
accounting that gives an ALU-bound complex GEMM the same ceiling as its real
counterpart, and the 4M/3M/2M instruction counts are documented in
`oto/tensile/gates/assembly.py`.

## 2. Measured gfx90c complex GEMM — moved to evidence

First-party CGEMM/ZGEMM measurements and the real-family comparison live in
`results.md`.

## 3. 2023–2026 complex GEMM without native complex units

The field reuses low-precision matrix engines; none of it is reachable on gfx90c
(no INT8/tensor engine), so it is context, not a route:

- **M3XU (SC'24):** 2p-bit CGEMM every 16c; **3.51×** over conventional vector
  units ([M3XU](https://intra.engr.ucr.edu/~htseng/files/2024SC-M3XU.pdf)).
- **Ozaki-II complex (2025):** casts complex GEMM onto INT8 modular GEMMs
  (Karatsuba 3M per modular GEMM); **4.4–6.5× CGEMM / 4.0–5.6× ZGEMM** over
  cuBLAS on B200 ([arXiv:2512.08321](https://arxiv.org/abs/2512.08321)).
- **EmuGEMM (2026):** fused complex kernels beat cuBLAS ZGEMM up to **2.3×
  (Hopper) / 5.5× (Blackwell)** ([arXiv:2606.25453](https://arxiv.org/pdf/2606.25453)).
- **INT8 matrix-engine emulation (2025):** Ozaki-I for FP64/FP32 on INT8 engines
  ([arXiv:2508.03984](https://arxiv.org/html/2508.03984v2)).
- **oneMKL 2024 JIT:** CGEMM/ZGEMM microkernels for AVX/AVX2/AVX-512 — the
  no-tensor-core CPU path ([Intel](https://www.intel.com/content/www/us/en/developer/articles/technical/onemkl-improved-small-matrix-performance-using-just-in-time-jit-code.html)).

## 4. Exotic paths against the 4-FMA wall on gfx90c

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
- (c) **occupancy/register tiling** — the demonstrated gfx90c bottleneck; the
  same GSU/WGM/MT/TT levers that lift real GEMMs are the realistic route from
  ~20% toward the ~69–80% real-family bar (local analysis:
  `gfx90c_theoretical_limits.md` §7).

## Quantitative guidance

Ceilings and split accounting: `oto/tensile/gates/assembly.py`; realistic
acceptance bars and current first-party results: `results.md`. Split choice:
fused **4M** per MAC; consider **3M** only for large-K GEMMs where the O(N²)
combine is negligible and the three real GEMMs run near their own efficiency.
