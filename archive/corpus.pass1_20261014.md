# corpus.md — gfx90c GEMM Tuning Corpus

Target: gfx90c APU (Renoir/Cezanne, Vega-7, Ryzen 5 PRO 5650U, 7 CU, no-MFMA, wave64, ~40-42 GB/s DDR4, 1 MB L2).

## 1. Executive Summary

- **DRAM Ridge vs Tile Size**: DDR4 BW=42 GB/s. FP32 peak=1613 GF/s → ridge AI=38.4 F/B (square MT≈154). Packed FP16 peak=3226 GF/s → ridge AI=76.8 F/B (square MT≈154). MT128 square AI=32 F/B (FP32) / 64 F/B (FP16) sits ~83% of ridge. FP64 peak=101 GF/s → ridge AI=2.4 F/B (square MT≈19.2). Complex-double Z peak=101 GF/s → ridge AI=2.4 F/B (square MT≈9.6). Complex-single C peak=1613 GF/s → ridge AI=38.4 F/B (square MT≈76.8). FP64 and Z cross ridge at small tiles; 21-24% efficiency ceiling not bandwidth-limited; bound by VGPR, issue rate, scheduling, dispatch.
- **Tile Inversion vs L2 thrashing**: dGPU (gfx906, 60 CU, 900 GB/s HBM2) favors small MT (16x16-64x64) for CU occupancy. gfx90c bandwidth-starved: needs data reuse. Extreme MT (128x128+) with multi-WG concurrent execution risks thrashing 1 MB L2 cache, spilling to 42 GB/s DDR4. Optimal: mid-to-large MT (64x64 to 128x128, asymmetric 128x64/128x256) tuned to L2 capacity + resident WG count.
- **Occupancy Capping Mechanics**: Non-MI FMA loops need ILP (unroll DepthU=16-64, TT 4x4-8x8) to hide 4-8 cycle latency. Uncapped occupancy (`MaxOccupancy=40`) triggers VGPR/LDS contention and cache thrashing. Moderate occupancy (8-16 waves/CU = 2-4 waves/SIMD, 2-3 WG/CU) preserves up to 256 VGPRs/thread, avoids scratch spills, protects L2 lines.
- **7-CU Quantization Pathology**: $G = \lceil M/MT \rceil \times \lceil N/NT \rceil$. Tail idle fraction $= (7 - (G \pmod 7))/7$. Severe for small $N \le 256$ with $MT \ge 64$ (14-57% CU utilization). Minor for $N \ge 1024$ ($>98\%$ aggregate utilization). Fix for small $M,N$ + large $K$: `GlobalSplitU` ($S$ chosen so $G \times S$ multiple of 7) or `WorkGroupMapping`.
- **LDS Bandwidth vs Phasing & Capacity**: LDS aggregate bandwidth = 128 B/cycle/CU (32 banks x 4 B), ~8x FP32 demand at TT 4x4; rarely primary bottleneck. Conflict mechanism: wave64 8 temporal phases (8 lanes/phase for `ds_write_b128`; lane sets 0:3+20:23 etc. for `ds_read_b128`). 8-way bank conflict stalls pipeline 8 cycles. `LdsPadA/B` deprecated in Tensile, sets to 0 (non-zero breaks vector alignment). Conflict control via `LocalReadVectorWidth` and layout transpose. Double-buffer LDS capacity $= 2 \times DepthU \times (MT_M + MT_N) \times \text{bytes}$.
- **Complex Bottleneck**: Z (16 B/elem) at TT 8x8 requires 256 accumulator VGPRs alone (4 regs/elem x 64 accumulators) → impossible with live temps. Max feasible TT for Z is $\le 6\times 6$ (144 regs) or 4x8 (128 regs). Tensile assembly enforces `GlobalSplitU=1` for complex types.

---

## 2. Literature Census & Architecture Transfer (§P.2)

- **AMD Literature Coverage**: ~2460 peer-reviewed papers (2016-2026 across ASPLOS, MICRO, ISCA, HPCA, PPoPP, CGO, SC, OSDI, etc.). ~7.5% (170 papers) evaluate AMD. Targets: gfx900, gfx906, gfx90a, gfx942. APUs (gfx90c, gfx1032) $<1\%$.
- **Transferability from Pre-Vega / Vega dGPU**:
  - Direct transfer: wave64 execution model, 4 SIMD/CU topology, 32-bank LDS, 16-lane vector pipes, 8/16 VGPR allocation granules, register pressure / scratch spill penalties.
  - Non-transferable: CDNA MFMA instructions, AGPRs, asynchronous global-to-LDS copy, CDNA3/4 layouts, dGPU HBM2/GDDR memory scaling.
- **VGPR File Architecture Truth**: Each SIMD has 64 KB VGPR (1024 regs x 64 lanes). 4 SIMDs/CU = **65,536 32-bit registers = 256 KB per CU**. Folklore "64 KB per CU" was per-SIMD number.
- **LDS Bandwidth Truth**: 32 physical banks x 4 bytes = 128 B/cycle aggregate per CU via two 64 B/cycle ports. Requires $\ge 2$ active waves/SIMD ($\ge 8$ waves/CU) executing LDS ops to saturate.
- **Shipped Tensile Logic Mapping**: `Common.py` maps `gfx90c` $\to$ `vega10` (`gfx900`), and `gfx906` $\to$ `vega20`. Shipped `vega10`/`vega20` logic contains diverse MT (128x16 FP32, 64x64 FP64, 16x16 FP16). Shipped choices reflect dGPU profiling, not APU DDR4 tuning.

---

## 3. Q-by-Q Findings (§Q)

### Q1. Vega/gfx9 Tile Sizing
- Shipped `vega10_Cijk_Ailk_Bljk_SB.yaml` (FP32): first candidate `MT128x016`, `TT=[4,4]`, `DepthU=16`, `WG=[32,4,2]`, `VectorWidth=4`, `BufferLoad=1`, `PGR=0`, `PLR=1`, `APM=1`, `MaxOccupancy=40`.
- Shipped `vega20_Cijk_Ailk_Bljk_DB.yaml` (FP64): `MT064x064`, `TT=[4,4]`, `DepthU=4`, `WG=[16,16,1]`, `VectorWidth=2`, `StaggerU=32`, `WGM=8`, `APM=1`, `MaxOccupancy=40`.
- Shipped `vega20_Cijk_Ailk_Bljk_HB.yaml` (FP16): `MT016x016`, `TT=[2,2]`, `DepthU=8`, `WG=[8,8,1]`, `VectorWidth=2`.
- Strategy: No uniform small/large bias. Search space: `MT64x64`, `MT128x64`, `MT128x128`, `MT128x256`, ~192 square; TT `[4,4]`, `[6,6]`, `[8,8]`. Prioritize WG count for 7 CUs on small $N$; prioritize cache reuse on large $N$.

### Q2. LDS Bank Conflicts & Capacity
- Bank index $= (\text{byte\_address} / 4) \pmod{32}$.
- `ds_write_b128`: 8 groups of 8 lanes (0-7, 8-15, ..., 56-63). Conflict-free if phase addresses hit distinct banks.
- `ds_read_b128`: lane groups 0:3+20:23; 4:7+16:19; 8:11+28:31; 12:15+24:27; plus 32-63 mirror.
- Capacity: $LDS = \text{buffers} \times DepthU \times (MT_M + MT_N) \times \text{bytes}$. Single 64 KB limit/CU.
- `LdsPadA/B`: Deprecated in Tensile; non-zero values break 16-byte vector alignments. Set `LdsPadA=0, LdsPadB=0`. Rely on `LocalReadVectorWidth` and LDS transposition.

### Q2b & Q8. Occupancy Capping Mechanics
- Non-MI FMA GEMM uses deep unrolling (`DepthU=16-64`) and large TT ($8\times 8 = 16$ vector FMAs, latency 4 cycles) to hide latency via ILP inside single wave.
- High occupancy (>4 waves/SIMD, >16 waves/CU) divides 256 KB VGPR pool, causing register spills to scratch memory and L2 thrashing.
- Capping at 2-4 waves/SIMD (8-16 waves/CU) allows up to 256 VGPRs/thread, fits accumulator array in registers, retains L2 working set.
- Persistent kernels (fixed 7 or 14 WGs) eliminate tail-wave idle time entirely via global work queue.

### Q3. Integrated APU Operating Regime
- Ryzen 5 5650U: DDR4-3200 dual-channel theoretical 51.2 GB/s, empirical sustained streaming read 40-42 GB/s.
- Compute: FP32 peak 1613 GF/s (achieved 1.15-1.22 TF/s = 71-75%). Packed FP16 peak 3226 GF/s (achieved 2.65-2.75 TF/s = 82-85%).
- 1 MB L2 cache is primary reuse shield. When tile working sets exceed 1 MB, performance falls off cliff to 42 GB/s DRAM bus. `WorkGroupMapping=8..16` preserves matrix B slices in L2 across neighboring CUs.

### Q4. Anti-Transfer & Portability
- Tuning across GPUs fails non-trivially.
- arXiv:2505.03780 (Ringlein et al.): FlashAttention kernels tuned for one GPU lose $\ge 20\%$ up to an order of magnitude on another (e.g. MI250 vs A100).
- arXiv:2507.15277 (Hochgraf & Pai): SGEMM across 5 GPUs shows dynamic performance ranges of 1.8x to 13.2x; multi-versioning needed.
- Up to 65% of foreign configs physically illegal on gfx90c (LDS $>64$ KB, VGPR $>256$, WG size $>1024$, non-wave64 vector widths).

### Q5. Performance Models
- **MAESTRO** (MICRO'19, arXiv:1805.02566): Analyzes spatial/temporal reuse and buffer traffic. Excellent for L2/DRAM cache blocking limits; lacks GCN FMA pipeline/VGPR emitter precision.
- **Microbenchmark-Driven Model** (arXiv:2605.04178): Calibrated pipeline parameters achieve $<1.5\%$ MAE on MI300A/B200. Methodology adapts to gfx90c once FMA/FP64/packed-F16 latency and DDR bandwidth calibrated.
- **PPT-GPU** (IEEE CAL): Hybrid analytical/discrete event, $<10\%$ error, but excessive calibration overhead for discrete knob space.
- **Instruction Roofline Model (IRM)** (arXiv:2110.08221): MI60/MI100 instruction and transaction tracking. Diagnostic tool for bottleneck classification.
- **Key Features for gfx90c Model**: VGPR granularity (8 regs if $\le 96$, 16 if $>96$), SIMD wave limits (4 SIMDs/CU, max 10 waves/SIMD), 1 MB L2 cache ceiling, 42 GB/s DDR bandwidth, 7-CU tail quantization.

### Q6. Analytical Roofline & Datatype Ridge Table

Tile AI:
$$\text{AI}_{\text{real}} = \frac{2 M_t N_t}{(M_t + N_t) \times \text{bytes}} \quad (\text{Square: } \frac{b}{\text{bytes}})$$
$$\text{AI}_{\text{complex}} = \frac{8 M_t N_t}{(M_t + N_t) \times \text{bytes}_{\text{complex}}} \quad (\text{Square: } \frac{4b}{\text{bytes}_{\text{complex}}})$$

Hardware Ridge $= P_{\text{peak}} / 42 \text{ GB/s}$:

| Datatype | Bytes/elem | Peak (GF/s) | Ridge (F/B) | Square MT at Ridge | AI at MT 64 / 128 / 192 / 256 | AI / Ridge at 64 / 128 / 192 / 256 | Accum VGPRs (WG 16x16) 64 / 128 / 192 / 256 | LDS (1 buf, DepthU=16) 64 / 128 / 192 / 256 | Feasibility & Bottleneck |
|---|---:|---:|---:|---:|---|---|---|---|---|
| **FP32** | 4 | 1613 | 38.4 | 154 | 16 / 32 / 48 / 64 | 0.42 / 0.83 / 1.25 / 1.67 | 16 / 64 / 144 / 256 (cap) | 8 / 16 / 24 / 32 KB | MT128 below ridge (83%); MT192 crosses. Feasible. |
| **FP16 (packed)** | 2 | 3226 | 76.8 | 154 | 32 / 64 / 96 / 128 | 0.42 / 0.83 / 1.25 / 1.67 | 8 / 32 / 72 / 128 | 4 / 8 / 12 / 16 KB | Same ridge tile. ALU-bound at MT192+. |
| **FP64** | 8 | 101 | 2.4 | 19.2 | 8 / 16 / 24 / 32 | 3.3 / 6.7 / 10 / 13 | 32 / 128 / 288 (ILLEGAL) / 512 (ILLEGAL) | 16 / 32 / 48 / 64 KB | ALU-bound at all MT $\ge 32$. Capped by issue rate/VGPRs. |
| **Complex-C** | 8 | 1613 | 38.4 | 76.8 | 32 / 64 / 96 / 128 | 0.83 / 1.67 / 2.5 / 3.3 | 32 / 128 / 288 (ILLEGAL) / 512 (ILLEGAL) | 16 / 32 / 48 / 64 KB | Ridge at MT77. MT $\ge 128$ crosses ridge. VGPR critical. |
| **Complex-Z** | 16 | 101 | 2.4 | 9.6 | 16 / 32 / 48 / 64 | 6.7 / 13 / 20 / 27 | 64 / 256 (cap) / 576 (ILLEGAL) / 1024 (ILLEGAL) | 32 / 64 / 96 (ILLEGAL) / 128 (ILLEGAL) | ALU-bound everywhere. TT $\le 6\times 6$ mandatory. |

### Q7. Wave Quantization on 7 CUs
- $G = \text{tiles} = \lceil M/MT \rceil \times \lceil N/NT \rceil$. Full passes $= \lfloor G / 7 \rfloor$, tail $= G \pmod 7$.
- Utilization $= G / (7 \times \lceil G/7 \rceil)$.

| Problem Size | Tile (MT) | Workgroups (G) | G mod 7 | Tail Idle CUs | Tail CU Util | Aggregate Util |
|---|---|---|---|---|---|---|
| **128x128** | 16x16 | 64 | 1 | 6 | 14.3% | 91.4% |
| 128x128 | 32x32 | 16 | 2 | 5 | 28.6% | 76.2% |
| 128x128 | 64x64 | 4 | 4 | 3 | 57.1% | 57.1% |
| 128x128 | 128x128 | 1 | 1 | 6 | 14.3% | 14.3% |
| **256x256** | 32x32 | 64 | 1 | 6 | 14.3% | 91.4% |
| 256x256 | 64x64 | 16 | 2 | 5 | 28.6% | 76.2% |
| 256x256 | 128x128 | 4 | 4 | 3 | 57.1% | 57.1% |
| **512x512** | 64x64 | 64 | 1 | 6 | 14.3% | 91.4% |
| 512x512 | 128x128 | 16 | 2 | 5 | 28.6% | 76.2% |
| **1024x1024**| 64x64 | 256 | 4 | 3 | 57.1% | 98.8% |
| 1024x1024| 128x128 | 64 | 1 | 6 | 14.3% | 91.4% |
| **2048x2048**| 128x128 | 256 | 4 | 3 | 57.1% | 98.8% |

Mitigation:
- Small shapes ($N \le 256$): use MT32x32 or MT64x64; or `GlobalSplitU` ($S$ chosen so $G \times S$ multiple of 7).
- Large shapes ($N \ge 1024$): tail penalty $<2\%$; optimize for arithmetic intensity and L2 retention.

### Q9. Tensile Control Levers
- **`MaxOccupancy` (1..40)**: Allocates extra LDS: $\max(\text{LDS}, 65536 / \text{MaxOccupancy})$. Artificial cap on WGs/CU. Default 40 = uncapped. Value 10 limits CU to 10 waves (2-3 WGs), guarding L2 and VGPRs. Test 4, 8, 12, 20 vs 40.
- **`AggressivePerfMode` (0, 1, 2)**:
  - 0: standard scheduling.
  - 1: inserts `s_setprio` instructions prioritizing memory reads over background scalar ops.
  - 2: modifies internal LDS allocation to restrict SIMD to max 2 waves (8 waves/CU).
- **`GlobalSplitU`**: Splits K loop across $S$ workgroups. Partial sums accumulated in global buffer, reduced by secondary kernel. Crucial for small $M,N$ with large $K$.

### Q10. Tuning Pipeline
- Protocol:
  1. Profile target shapes via `ROCBLAS_LAYER=4`.
  2. Baseline library selection via `rocblas-gemm-tune` (emits override YAML).
  3. Filter parameter space using analytical legality checks.
  4. 10-hour search: Bayesian/evolutionary search over legal space. 25% warmup, cold L2 flush, $\ge 100$ iterations.
  5. Deploy via `ROCBLAS_TENSILE_GEMM_OVERRIDE_PATH`. Note: `ROCBLAS_USE_HIPBLASLT=1` bypasses Tensile overrides.

### Q11. DVFS & APU Measurement Controls
- Thermal/Clock: Idle GPU drops to 400 MHz; boost scales to 1800 MHz at steady-state junction temp (76-78°C). Cold chip benchmarks invalid.
- Linux sysfs clock pinning:
  ```bash
  echo "manual" > /sys/class/drm/card0/device/power_dpm_force_performance_level
  echo "7" > /sys/class/drm/card0/device/pp_dpm_sclk
  ```
- Protocol controls:
  - 25% warmup iterations to reach thermal equilibrium.
  - Realistic data initialization (all-zero or low-toggle data inflates clocks $>50\%$).
  - Cold L2 flush between iterations for memory-bound shapes.
  - Batching short kernels (150 µs - 80 ms) to reduce dispatch overhead. CV threshold $<1.5\%$.
  - Record median clock, temp, and run order to detect thermal throttling.

### Q12 & Q13. Autotuning Techniques Comparison

| Technique | Venue/Year | Search Space | Hardware Run? | Speedup | AMD Evaluated? | Transfer to gfx90c? | Effort |
|---|---|---|---|---|---|---|---|
| **Legality/Roofline Pruning** | Williams'09 / Project | MT/TT/LDS/VGPR/WG | No | N/A (prunes $\approx 65\%$) | Yes (Direct) | **Highest** | Low |
| **Bayesian / TPE / SMAC** | OpenTuner / Ansor | Discrete Tensile YAML | Yes | 1.3x - 2.1x | Yes | **High** | Low/Med |
| **Evolutionary Search** | Ansor (OSDI'20) | Schedule mutations | Yes | Up to 1.7x | Yes (dGPU) | **High** | Medium |
| **Cost Model Guided** | MAESTRO (MICRO'19) | Tile reuse / capacity | No | N/A (pruning) | Yes | **High** (L2 bounds) | Medium |
| **Stream-K Work Distribution**| PPoPP'23 | Work-centric loop split| Yes | Up to 14x (NV) | No (MFMA-gated) | **No** (Tensile gates to MFMA)| High |
| **Persistent Kernels** | PERKS (SC'23) | Fixed 7/14 WG grid | Yes | 1.15x - 1.4x | Yes | **High** (concept) | High |
| **LLM Kernel Generation** | GEAK / KernelBench | Code gen / reflex loop | Yes | 1.1x - 2.59x | MI250/300X only | **Low** (breaks GCN asm) | High |
| **RL / MCTS Search** | Dr. Kernel / Forge '26 | Token / AST action | Yes | System-specific | NVIDIA-centric | **Low** (overkill for fixed knobs)| High |

### Q14. Search Space & Knob Ranking

Legality Rules:
1. $WG_0 \times WG_1 \in [64, 1024]$ and $(WG_0 \times WG_1) \pmod{64} == 0$.
2. $TT_0 \le 16, TT_1 \le 16$.
3. $MT_0 = WG_0 \times TT_0, MT_1 = WG_1 \times TT_1$.
4. $\text{VectorWidth} \times \text{bytesPerElement} \le 16$.
5. $LDS \le 65536 \text{ Bytes}$.
6. $VGPR \le 256$.
7. $\text{MatrixInstruction} = []$ (mandatory on gfx90c).

Knob Sensitivity Ranking:
- **Tier 1 (Critical)**: `MacroTile0/1`, `ThreadTile0/1`, `DepthU`, `GlobalSplitU`, `GlobalLoadVectorWidthA/B`, `WorkGroupMapping`.
- **Tier 2 (Moderate)**: `PrefetchGlobalRead` (0/1/2), `PrefetchLocalRead` (0/1), `LocalReadVectorWidth`, `AggressivePerfMode` (0/1/2), `MaxOccupancy` (4..40), `BufferLoad` (true/false, gates `StaggerU`), `StaggerU` (pair with WGM).
- **Tier 3 (Algorithmic / Shape-Specific)**: `LocalSplitU` (small M,N, long K), `InnerUnroll`, `FractionalLoad`, `UseSgprForGRO`, `NumLoadsCoalescedA/B`.
- **Tier 4 (Inactive / Deprecated)**: `LdsPadA/B` (keep 0), `StorePriorityOpt`.

### Q15. Split-K, Stream-K & Reduction Overheads
- Split-K cost model:
  $$T_{\text{split}} \approx T_{\text{gemm}}(M,N,K/q) + T_{\text{write\_partial}}(q,M,N) + T_{\text{reduce}}(q,M,N) + T_{\text{launch}}$$
- Intermediate buffer sizes: FP32 $= 4qMN$ B; FP64 $= 8qMN$ B; C $= 8qMN$ B; Z $= 16qMN$ B.
- Break-even: Large square GEMMs already saturate 7 CUs; Split-K is pure reduction overhead. Profitable only when $M,N \le 128$ and $K \ge 2048$.
- Tensile Constraints:
  - Stream-K disabled on non-MFMA targets.
  - `GlobalSplitU > 1` disabled for Complex types (C and Z) in Tensile assembly generator due to multi-register accumulation complexity.
  - FP16 with FP32 accumulation requires `AssertFree0ElementMultiple >= 2` for packed vector alignment.

### Q16. Reproducibility & Benchmark Standards
- Mandatory logging parameters: git commit, exact YAML tuple, ROCm/LLVM versions, kernel symbol, launch grid, build status, verification pass, object metadata (VGPR, SGPR, LDS, scratch bytes), median latency, MAD / CV, cache state (cold vs hot), clock frequency, ASIC temperature, execution timestamp.
- Interleave baseline reference kernels every $N$ runs to detect thermal throttling and system drift.

---

## 4. Unverified Claims & Citations Excluded (§Do Not Cite)

1. **"Tile: A Faster Tiling Approach for AMD GPUs" (ASPLOS'20)**: Title and paper could not be found or verified in ACM/IEEE digital libraries. Do not cite.
2. **"MI250-optimal on A100 = ~7% of A100-optimal"**: Quoted 7% figure not found in arXiv:2505.03780 (paper evaluates Triton flash-attention, reports $\ge 20\%$ to order-of-magnitude drop).
3. **"142k tuples, 5 GPUs, dynamic range 1.8x-13.2x"**: Parameterized stats for arXiv:2507.15277 unverified in abstract.
4. **"ISC 2026 CUTLASS FP8 1.00 waves/SM / 14% occupancy"**: Datapoint not located in accessible proceedings.
5. **"PERKS (SC'23) 1.15x-1.4x speedup on gfx90c"**: PERKS evaluated on dGPUs/NVIDIA; no gfx90c APU data.
6. **"gfx1151 `auto` vs `profile_peak` +37.8%"**: Not primary source verified for gfx90c.
7. **Bibliographic ghost entries**: *COSTA, FASTEST, BASS, BEST, Pyramid, MagicLine, SeerNN, PlanGen, GemmLab, Charo analytical GEMM, Fugerite et al.*: unverified.
8. **Universal "2 waves/SIMD" rule**: Not a universal law; varies with ILP vs memory latency.

---

## 5. Concrete Action Plan for gfx90c

1. **Tile Selection**:
   - FP32 / Packed FP16: MT 64x64, 128x64, 128x128, 128x256; TT `[4,4]`, `[6,6]`, `[8,8]`. Cross ridge without exceeding 1 MB L2.
   - FP64: MT 32x32, 64x64; TT `[4,4]`. Already ALU-bound; do not enlarge MT at cost of occupancy.
   - Complex Z: Cap TT at $\le 6\times 6$ or $4\times 8$ (max 144 accum VGPRs). MT 32x32 or 64x64.
   - Complex C: MT 64x64 or 96x96; TT `[4,4]` or `[6,6]`.
2. **Loop & Memory Knobs**:
   - DepthU: 16 to 64. Ensure double-buffer LDS $\le 32$ KB to allow 2 WGs/CU.
   - VectorWidth: GlobalLoadVectorWidth=4 (16 B reads) for FP32/FP16; 2 for FP64/C; 1 for Z.
   - Prefetch: `PGR=1`, `PLR=1` as baseline; test `PGR=0` with large tiles.
   - `BufferLoad=1` paired with `StaggerU=32` and `WorkGroupMapping=7..14`.
   - `LdsPadA=0, LdsPadB=0`.
3. **Occupancy & Grid Tuning**:
   - Occupancy: `MaxOccupancy=40` (control) vs `8..12` (to prevent L2 thrash). `AggressivePerfMode=1` default, test 2.
   - Wave Quantization: For $M,N \le 128$ and large $K$, set `GlobalSplitU` to round total WGs to multiple of 7.
4. **Execution Protocol**:
   - Pin sysfs clocks (`manual`, level 7).
   - 25% warmup, cold cache flush, 100 repeats, CV $<1.5\%$.
   - Search: Prune illegal tuples analytically $\to$ Latin Hypercube / random sample (100 pts) $\to$ Bayesian Optimization (TPE) over top performers.
