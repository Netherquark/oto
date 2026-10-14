# corpus.md — gfx90c GEMM tuning research (PARTIAL RUN)

> **Status: MINED 2026-10-14.** Computed ridge values are consistent with the
> homes' ridge arithmetic (`potential_configs.md` §1); the ASPLOS-"Tile" /
> 2505.03780 / B200-MI300A caveats are already in the do-not-cite lists
> (`kernel_tuning_research.md`, pass-2 §P.4 notes). **No new deck row came out of
> this file.** Raw below — do not cite; cite the homes.

**Read this first.** This is NOT the full sweep the brief asked for. In this run I made
4 web searches and did no venue-by-venue proceedings sweep, no reading of the shipped
Tensile `Logic/asm_full/vega10|vega20` files, and no census. Everything not listed under
"What I actually checked" is marked UNVERIFIED or NOT DONE. Nothing in §H was re-verified;
§H was used as given. Confidence markers: VERIFIED = read the source text, PARTIAL =
abstract / search excerpt only, UNVERIFIED = not found or not attempted, COMPUTED = my own
arithmetic from §H (no literature behind it).

## 1. Executive summary (what is actually worth acting on)

1. **Q6 physics (COMPUTED, §6 below):** for fp32 the DRAM-level ridge (no L2 reuse) is at
   MT ≈ 154 square, so MT 192/256 are ALU-bound and MT128 reaches ~83% of the ridge.
   fp16 has the same ridge tile (~154). FP64 (ridge T≈19) and complex-double (T≈10) are
   ALU-bound at essentially any tile. **Consequence: the complex-double 24% and FP64 gap
   cannot be a tile-size/bandwidth problem; it is kernel quality or resource limits.**
   Complex-single (ridge T≈77) is bandwidth-limited only at MT ≤ 64.
2. **Complex-double is VGPR-limited, not bandwidth-limited:** at 4 regs/element, accumulators
   alone are 256 regs at TT 8×8 (infeasible with any other live register). Feasible TT is
   ≤ ~6×6 (144 accum regs). The big-tile bias cannot even be expressed for Z. (COMPUTED.)
3. **The "Tile, ASPLOS'20, AMD GPUs" reference in Q12 could not be located.** Do not rely on
   it until its existence is confirmed (§7).
4. **Q4 anti-transfer evidence is real but not about GEMM:** arXiv:2505.03780 reports a
   ≥20% drop up to an order of magnitude when a config tuned on one GPU is run on another —
   measured on Triton **flash attention**, MI250 vs A100, not GEMM/Tensile. PARTIAL.
5. **Wave quantization on 7 CUs (COMPUTED, §5):** at N=128–256 the tail is severe for
   MT ≥ 128 (14–57% machine use under a 1-WG-per-CU idealization); from N≥1024 with MT ≤ 64
   it is <2%. Idealized; it ignores multiple resident WGs per CU.

## 2. What I actually checked (4 searches)

| item | result | confidence |
|---|---|---|
| Stream-K (Osama, Merrill, Cecka, Garland, Owens; PPoPP'23) | Exists. Partitions aggregate inner-loop iterations evenly across processing elements; claims near-perfect utilization independent of tile quantization; peak speedup 14× / 6.7× vs CUTLASS/cuBLAS over 32,824 problem geometries; single tile size per precision. Evaluated on NVIDIA. https://arxiv.org/abs/2301.03598 , https://ppopp23.sigplan.org/details/PPoPP-2023-papers/36/POSTER-Stream-K-Work-centric-Parallel-Decomposition-for-Dense-Matrix-Matrix-Multipl | PARTIAL (abstract + excerpts) |
| Quantization example in Stream-K | A 384×384×128 GEMM as nine 128×128 tiles on a 4-SM GPU caps data-parallel at 75% throughput — same effect as §5. https://ar5iv.labs.arxiv.org/html/2301.03598 | PARTIAL |
| arXiv:2505.03780 (Ringlein, Parnell, Stoica) | Triton flash-attention study; "performance drops by at least 20% and by up to an order of magnitude" when using a config optimized for another GPU. The brief's "~7% of A100-optimal" figure was **not** in anything I read. https://arxiv.org/abs/2505.03780 , https://arxiv.org/pdf/2505.03780 | PARTIAL |
| PPoPP'19 "Coordinated Tiling and Batching" (Li et al.) | Exists; states the tile-size vs thread-level-parallelism trade-off (large tile → reuse, fewer threads). Batched GEMM, ~1.40× avg over prior SOTA. https://ppopp19.sigplan.org/details/PPoPP-2019-papers/32/A-Coordinated-Tiling-and-Batching-Framework-for-Efficient-GEMM-on-GPUs | PARTIAL |
| AMD ROCm GPU spec page (VGPR file column) | The page has an "LDS (KiB)" and "VGPR File (KiB)" table with 64 KiB LDS and values of 64 and 256 KiB appearing for different architectures, but the text I retrieved is flattened and I could **not** map rows to gfx900/gfx906/gfx90c. https://rocm.docs.amd.com/en/docs-6.2.2/reference/gpu-arch-specs.html | PARTIAL / unresolved |
| CK Tile docs "Block GEMM on MI300" | Gives loads-per-output = K(1/TILE_M + 1/TILE_N); documentation, MI300, MFMA. https://rocm.docs.amd.com/projects/composable_kernel/en/develop/_sources/conceptual/ck_tile/hardware/gemm_optimization.rst | PARTIAL |

## 3. §P.2 — AMD/GCN coverage census

**NOT DONE.** No papers were screened systematically, so I have no counts and will not
supply any. Status of the specific sub-questions:
* VGPR file size on gfx9/gfx90c (65536 regs/CU = 256 KB vs "64 KB per CU" folklore):
  **left open.** The ROCm spec table (above) is the likely primary source but my retrieval
  could not map rows. Next step: open the page in a browser and read the gfx900/gfx90c row.
  Note that the "64 KB" folklore is the per-SIMD figure (64 KB × 4 SIMDs = 256 KB/CU), which
  is consistent with §H — this is my reasoning, not a sourced finding. UNVERIFIED.
* LDS bandwidth 128 B/clk on Vega: no paper found. UNVERIFIED.
* AMD-authored GEMM autotuner / learned tile predictor: none found in this run. UNVERIFIED.

## 4. §Q answers

| Q | status | note |
|---|---|---|
| Q1 | NOT DONE | Did not read vega10/vega20 Tensile logic files; the small-tile hypothesis is **untested**. Tentative reasoning only: per §6, a bandwidth-starved part wants *more* reuse (bigger tiles), so AMD's small rank-1 tiles on HBM2 hardware would be unsurprising rather than contradicting a big-tile bias (small tiles buy parallelism, which HBM parts can pay for). UNVERIFIED. |
| Q2 | NOT DONE | |
| Q2b/Q8/Q9 | NOT DONE | Only the PPoPP'19 statement that larger tiles reduce thread-level parallelism (above) bears on this. |
| Q3 | NOT DONE | |
| Q4 | PARTIAL | Only 2505.03780 (flash-attention, not GEMM). Hochgraf & Pai 2507.15277 not opened. |
| Q5 | NOT DONE | MAESTRO, 2605.04178, PPT-GPU, IRM not opened. |
| Q6 | COMPUTED | §6. Literature citations (van de Geer & Wolrich, Hwu) not retrieved. |
| Q7 | COMPUTED | §5. |
| Q10–Q14, Q16 | NOT DONE | |
| Q15 | PARTIAL | Stream-K exists and is NVIDIA-evaluated; no work on non-power-of-two CU counts found (absence not established — I did not search for it). Whether the Tensile complex/half `GlobalSplitU` refusal is fundamental or policy: NOT DONE. |

## 5. Q7 wave quantization on 7 CUs (COMPUTED)

Idealization: one resident WG per CU, equal tile time, tiles = ceil(N/T)². Efficiency =
tiles / (7 · ceil(tiles/7)). With several WGs resident per CU the granularity is finer and
the loss smaller. This does **not** pick the time-minimizing tile — that also needs per-tile
efficiency and the §6 reuse trade-off, which I did not model.

| N | T=16 | T=32 | T=64 | T=128 |
|---|---|---|---|---|
| 128 | 64 tiles, 91% | 16, 76% | 4, 57% | 1, 14% |
| 256 | 256, 99% | 64, 91% | 16, 76% | 4, 57% |
| 512 | 1024, 99% | 256, 99% | 64, 91% | 16, 76% |
| 1024 | 4096, 100% | 1024, 99% | 256, 99% | 64, 91% |
| 2048 | ≈100% | ≈100% | 1024, 99% | 256, 99% |

## 6. Q6 table (COMPUTED from §H; DRAM-level, no L2 reuse)

AI = 2·Mt·Nt/((Mt+Nt)·bytes) per K step for real types; complex counts 8 flop/MAC.
Square tile T=MT. Ridge = peak / 42 GB/s. Accumulator regs for WG 16×16 (TT = MT/16);
fp16 assumes half accumulate (f32 accumulate doubles it). LDS = DepthU 16 × (MT_A+MT_B) ×
bytes, single buffer (double-buffer ×2). Feasible = accum regs ≤ ~200 (leaving headroom of
the 256 cap) and LDS ≤ 64 KB.

| dtype | peak GF/s | ridge F/B | bytes/el | AI at MT 64 / 128 / 192 / 256 | AI/ridge at 64 / 128 / 192 / 256 | accum regs 64 / 128 / 192 / 256 | LDS KB (1 buf) 64 / 128 / 192 / 256 |
|---|---|---|---|---|---|---|---|
| fp32 | 1613 | 38.4 | 4 | 16 / 32 / 48 / 64 | 0.42 / 0.83 / 1.25 / 1.67 | 16 / 64 / 144 / 256✗ | 8 / 16 / 24 / 32 |
| fp16 (packed) | 3226 | 76.8 | 2 | 32 / 64 / 96 / 128 | 0.42 / 0.83 / 1.25 / 1.67 | 8 / 32 / 72 / 128 | 4 / 8 / 12 / 16 |
| fp64 | 101 | 2.4 | 8 | 8 / 16 / 24 / 32 | 3.3 / 6.7 / 10 / 13 | 32 / 128 / 288✗ / 512✗ | 16 / 32 / 48 / 64 |
| complex-single | 1613 | 38.4 | 8 | 32 / 64 / 96 / 128 | 0.83 / 1.67 / 2.5 / 3.3 | 32 / 128 / 288✗ / 512✗ | 16 / 32 / 48 / 64 |
| complex-double | 101 | 2.4 | 16 | 16 / 32 / 48 / 64 | 6.7 / 13 / 20 / 27 | 64 / 256✗ / 576✗ / 1024✗ | 32 / 64 / 96✗ / 128✗ |

Reading: fp32/fp16 sit just below the ridge at MT128 and cross it by MT~160–192, which is
inside Tensile's legal space (TT ≤ 16, VGPR/LDS feasible). Real tuning would need
fractional gains from L2 reuse (1 MB, unquantified here). FP64 and complex-double have
ridges so low that bandwidth never binds; their limit is registers/issue.
Occupancy note: LDS per WG caps resident WGs at floor(64 / LDS KB).

## 7. Venue-sweep audit

All venues listed in §P.1: **NOT SWEPT in this run** (years covered 0, screened 0, kept 0).
Individual papers touched incidentally: PPoPP'19, PPoPP'23 (above).

## 8. Techniques table (partial)

| technique | venue+year+URL | search space | needs measurement? | reported gain | on AMD? | transferable to wave64/no-MFMA/7-CU? | effort |
|---|---|---|---|---|---|---|---|
| Stream-K | PPoPP'23, https://arxiv.org/abs/2301.03598 | decomposition, not knobs | no (heuristic) | up to 14×/6.7× vs CUTLASS/cuBLAS (NVIDIA) | not in what I read | idea yes; MFMA-gated in Tensile per your brief, so not usable as a knob | high (kernel writer change) |
| Coordinated tiling+batching | PPoPP'19, URL above | tile sizes for batched GEMM | partly | ~1.40× avg (batched) | not in what I read | concept only | n/a |
| All others in Q12–Q14 | — | — | — | — | — | NOT DONE | — |

## 9. Could not verify / do not cite

* **"Tile: A Faster Tiling Approach for AMD GPUs, ASPLOS'20":** my search did not find it.
  It may be mis-titled or mis-attributed. Do not cite until located.
* **"~7% of A100-optimal" from 2505.03780:** not found in what I read; the paper is about
  Triton flash attention, not GEMM or Tensile.
* **2605.04178 (B200/MI300A model)** and **"ISC 2026 CUTLASS FP8 14% occupancy"** from the
  brief: not opened; I make no claim about them.
* Every Q marked NOT DONE above.

## 10. What this changes (derived from §6 arithmetic only, not from literature)

* fp32/fp16: bias MacroTile toward 160–192 where VGPR allows (e.g. WG 16×16, TT 10×10 or
  12×12 fp32); MT128 is below the DRAM ridge by ~17%.
* complex-double: cap ThreadTile at ≤ 6×6 (or 4×8); TT 8×8 cannot fit. Do not spend budget
  on larger Z tiles.
* complex-double and FP64: tile size is not the lever (AI/ridge ≥ 6); investigate
  instruction scheduling / VGPR pressure / occupancy knobs (`MaxOccupancy`,
  `PrefetchLocalRead`, `InnerUnroll`) instead.
* complex-single: MT ≥ 128 is above ridge; MT 64 is at 83%.
* small problems (N ≤ 256): avoid MT 128 (≤57% machine use idealized); MT 32–64 or
  `GlobalSplitU` where legal.
* LDS: at MT 256 fp64/C, a single buffer already hits 64 KB at DepthU 16 — use DepthU ≤ 8
  there or MT ≤ 192.
