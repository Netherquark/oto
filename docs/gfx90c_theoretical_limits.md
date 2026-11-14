# gfx90c Theoretical Performance Limits — oto

> Authoritative acceptance-reference for "as close to the gfx90c theoretical limit as
> possible". The per-family peak table (§2) is now derived deterministically from
> hardware facts on every call — see `oto.device.derive` (`python3 -m oto.device.derive`),
> which reproduces exactly the numbers this file records. The limits and the recipe
> both live behind one Python formula: lanes × 2 (FMA) × f(GHz), FP16 = 2× FP32
> (fast F16), FP64 = FP32 / 16 (GCN5), complex families inherit their lane class
> (HGEMM-packed FP16 anti-gates stay FP32). The research narrative and the
> roofline/boundary thresholds (§3) remain first-party-derived and
> measure-anchored as before.

## 0. How this file is used

- **Acceptance sourcing:** every oto family ceiling in `docs/potential_configs.md` /
  `docs/implementation_plan.md` / `docs/shipped_floor_contract.md` derives from the per-family ceilings in §5 —
  the same way `oto.device.loader.current_profile().peak_gflops` is the single peak authority. Squaring a
  family's best median against its §5 ceiling is how "approach the theoretical limit"
  is scored, per (datatype, bound_class).
- **No re-derivation:** never re-derive these ceilings from model memory. Extend only
  with first-party evidence + measured oto data.

## 1. Confirmed architecture facts (verified on this box)

| property | value |
|---|---|
| Device | AMD Ryzen 5 PRO 5650U (Cezanne-U PRO, Zen 3) iGPU = **gfx90c** |
| rocminfo | Name `gfx90c`, Chip ID 0x1638, PCI 1002:1638 rev d2, kfd `gfx_target_version 90012` = ISA (9,0,12) |
| Compute Units | **7** (CU/SIMD-array 8, 7 active) → 28 SIMDs |
| Wavefront | **Wave64** |
| FP32 lanes | 7 CU × 4 SIMD × 16 = **448** |
| Max waves/CU | 40 (10/SIMD); max work-items/CU 2560 |
| Max clock (rocminfo/kfd `max_engine_clk_fcompute`) | **1800 MHz** (DVFS pins at level-2 = 1800 under load) |
| Fast F16 | TRUE |
| L1 | 16 KB/CU (7×16 KB = 112 KB aggregate) |
| L2 | **1024 KB (1 MB)** — rocminfo firmware readout (not 512 KB) |
| LDS | 64 KiB/CU; VGPR 256 KiB/CU → 256 VGPR/SIMD; SGPR 12.5 KiB/CU class |
| Memory | APU UMA; `Coherent Host Access FALSE`; VRAM carve-out 4 GiB, GTT 14.6 GiB |
| HasMFMA / dp4a / packed-BF16 | **FALSE / absent / absent** (see §1.2) |
| SDMA | 1; CP queues 24 |
| Global-load byte cap | **16 B** (`GlobalLoadVectorWidthA * DataType.numBytes() <= 16`) |

- **Element byte widths are `numBytes() == reg * 4`, and complex double is 16 B,
  not 8.** From `Tensile/DataType.py`: `S`=4, `H`=2, `D`=8, `C`=8, `Z`=**16**.
  The 16 B cap therefore bites hardest exactly where it is easiest to get wrong:
  `Z` at `VectorWidth=1` sits *on* the cap, so `VW=2` needs a 32 B global load and
  Tensile rejects the kernel at assembly. Getting `Z` from a "complex is 2× a
  double" intuition gives 8 and silently admits `VW=2`. This is now read from
  `DataType.properties` rather than a hand-kept table — see
  `oto.tensile.gates.vgpr_model.FAMILY_BYTES_PER_ELEMENT` (with the cap itself,
  read from `oto.device.loader.current_profile().global_load_byte_cap`), which
  lists `ZZ: 16` and is locked by
  `tests/test_measurement_integrity.py`
  (`test_complex_double_is_16_bytes`, `test_zz_vector_width_capped_at_one`).
  Worst legal `VectorWidth` per dtype under the cap: S 4, H 8, D 2, C 2, **Z 1**.

- ISA oracle (compile-only, clang-19): `v_pk_fma_f16` OK; `v_pk_fma_bf16` **absent on
  all gfx9** (900/90c/906); `v_dot*` **absent on gfx90c** (gfx906+ only);
  `v_fma_mix_f32` **absent on gfx90c**; `v_mfma_*` absent (CDNA-only). Shipped gfx900
  HH_HPA kernels disassemble to plain `v_fma_f32` (HPA = FP32-rate by construction).
- **References (first-party / highly authoritative):** LLVM `AMDGPUUsage.html`
  (gfx90c = amdgpu9.0c, APU, xnack); AMD Ryzen PRO 5650U support page (7 CUs,
  graphics freq 1800 MHz); AMD RX Vega press release + RX Vega 64 spec (FP16 = 2×
  FP32 on every GCN5 part); AMD "Vega Shader ISA" reference (first-party ISA doc);
  ROCm GPU-specs + gpu-arch pages; Tom's Hardware Vega-10 FP64 1:16 analysis.

## 2. Per-family theoretical ALU peaks (FMA-pipe ceilings)

> These numbers are derivable on demand — `python3 -m oto.device.derive` and
> `tests/test_derive.py` re-compute them from `profiles/gfx90c.json`. Identical
> formula: `lanes = num_cus * simds_per_cu * lanes_per_simd`, choose the lane
> class per family (FP32 / FP64+8:16 / FP16 fast-F16 = 2× FP32), multiply by
> `2 * fGHz`. Any edit to this table without a corresponding edit in
> `oto/device/derive.py` is by construction wrong.

BLAS flop accounting: real GEMM 2·M·N·K; complex GEMM 8·M·N·K (4 mul + 4 add);
HGEMM/HPA 2 flops/MAC regardless of accumulate type. Complex MAC = 4 real FMAs
(Tensile expansion) so complex families run at the REAL rate of their lane class.
Tensile DataType codes: **C = complexSingle** (FP32 lane class), **Z =
complexDouble** (FP64 lane class) — matching CBLAS c/z convention.

| Family | Tensile `(Ti,To,Tc)` | op | GFLOPS @1800 | formula (f GHz) | @1900 | @2000 |
|---|---|---|---|---|---|---|
| **SS** | (S,S,S) | SGEMM | **1613** | 1.792·f TF | 1702 | 1792 |
| **DD** | (D,D,D) | DGEMM | **101** | 0.112·f TF | 106 | 112 |
| **HH** | (H,H,H) | HGEMM packed-FP16 acc | **3226** | 3.584·f TF | 3405 | 3584 |
| **HH_HPA** | (H,H,S) | FP16 in/out, FP32 acc | **1613** | 1.792·f TF | 1702 | 1792 |
| **HS_HPA** | (H,S,S) | FP16 in, FP32 out/acc | **1613** | 1.792·f TF | 1702 | 1792 |
| **CC** | (C,C,C) | CGEMM complex single (C) | **1613** | 1.792·f TF | 1702 | 1792 |
| **ZZ** | (Z,Z,Z) | CGEMM complex double (Z) | **101** | 0.112·f TF | 106 | 112 |
| BF16 (not in the 7) | (B,B,S) | BGEMM FP32-emulated | 1613 | 1.792·f TF | 1702 | 1792 |
| INT8 (not in the 7) | (I8,I,I) | IGEMM, no dot | 1613 UPPER bound | 1.792·f TF | 1702 | 1792 |

### 2.1 The four contested questions — resolved

1. **BF16 dual-rate? NO.** No `v_pk_fma_bf16` on any gfx9. BF16 FMA = FP32 FMA with
   operand broadening → **single-rate 1613**.
2. **INT8 dot? NO.** No `v_dot4_*` before gfx906; no dp4a. INT8 ceiling = FP32-pipe
   bound 1613 GOPS, and a real MAC costs ≥2 integer ops (SDWA/int24 tricks are what
   the shipped gfx900 i8 kernels do) → pragmatic bound ≈ half; measured 881.
3. **FP64 ratio? Exactly 1/16** of FP32 → 100.8 GFLOPS. Empirically vindicated:
   the measured prior FP64 best 98.6 = 98% of 100.8 (a 1/8 or 1/32 part would read
   197% / 49%). `oto.device.loader.current_profile().peak_gflops['FP64']` stores the rounded **101**
   (matches the §2 table); §5 ceilings use the measured 98.6.
4. **Complex real-FMA cost?** An FMA counts once; a complex MAC = 4 real FMAs. CC (C =
   complex single) @ SS rate, ZZ (Z = complex double) @ DD rate, when counting BLAS-8
   flops.

### 2.2 HPA cost

Inputs stay 16-bit (halved LDS/VGPR traffic vs SS) but the pipe computes
`v_fma_f32` → ceiling exactly the **FP32 ceiling 1613** = half of packed HH. Penalty is
the missed dual-issue (`v_fma_mix_f32` absent on gfx90c), not extra per-instruction work.

## 3. Memory roofline (this machine)

| figure | GB/s | provenance |
|---|---|---|
| DDR4-3200 dual-channel theoretical (AMD official max) | **51.2** | 2ch × 8B × 3200 MT/s |
| **Measured-achievable streaming read (this box)** | **≈ 40–42** | FP32 64×4096×1 K=4096 winner: 1311 GFLOPS ⇒ 1.64 ms for 65.5 MB ⇒ 40.2 GB/s (the most "B-streamed-once" GEMV in the dataset; a lower bound, and it cannot exceed DRAM physics) |
| Hard never-exceed | 51.2 | DRAM physics |

- Use **42 GB/s** as the realistic DDR roofline for `t_min` (~82% of 51.2).
- Minimal-traffic bytes (single pass, no reuse) = (M·K + K·N + M·N)·S with S per family
  (SS 4, DD 8, HH/HPA 2, ZZ 8, CC 16, INT8 1). Arithmetic intensity I =
  2·M·N·K/bytes (real) or 8·M·N·K/bytes (complex). **Closed form for a square FP32
  cube `M=N=K=n`: `I = n/6` FLOP/byte** — the roofline model's own worked case
  ([Roofline, UCB/EECS-2008-134](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-134.html));
  with the per-family `S`, the same algebra gives each family's square-flip side
  (the ridges below).
- `t_min = max( 2·M·N·K / P , bytes / BW )` (42 GB/s; P per §2). Apply a ~1.2–1.5
  traffic multiplier before calling a kernel "failed" (real kernels move more than
  minimum traffic).
- **Large squares are NOT DDR-caused:** a 4096³ fp32 square needs only ~1.5 GB/s at
  1000 GFLOPS; 42 GB/s is ample headroom. GEMV/short-K ARE DDR-bound (decode shapes
  best-measured 1002–1036/1199–1311 GFLOPS ≈ 40 GB/s ≈ 81% of FP32 roof).

## 4. Boundary thresholds + shipped-suite classification

Flip condition ALU-bound ⇔ I ≥ P/BW. Ridge (P/BW @1800, BW=42): SS/BF16/HPA 38.4,
HH 76.8, DD/CC 2.4, ZZ 38.4. Square-flip X: ≈230 (SS/HH/HPA), ≈115 (ZZ), ≈29 (DD/CC).

**Consequence:** GEMM squares ≥ ~256³ are ALU-bound for every real family even at
minimum DDR4-3200 bandwidth. DD/CC are ALU-bound for almost ANY shape (pipe is 16×
slower than memory is fast).

| shape | SS | DD | HH | HH_HPA/HS_HPA | ZZ | CC |
|---|---|---|---|---|---|---|
| 4096³/2048³/1024³/768³/512³/256³/1365³ | ALU | ALU | ALU | ALU | ALU | ALU |
| GEMV 32/64×4096 (K=4096) | **DDR** | ALU | **DDR** | **DDR** | **DDR** | ALU |
| batched 64×2048×16/K16, 64×11008×1 | **DDR** | ALU | **DDR** | **DDR** | **DDR** | ALU |
| GEMV 128×4096 (K=4096) | ALU (I=60 ≥38.4) | ALU | ALU | ALU | — | ALU |

- Mold the DDR-class rule `batch==1 && (M≤128 || K≤64 || N≤64)` to the math at the
  exact SS corner M=128,N=K≥2048 (I=60 vs ridge 38.4 → ALU side).
- At max boost (2.0 GHz) ridges scale ×1.11; no shipped anchor changes class.

## 5. Recommended realistic machine ceilings (oto acceptance bars)

Measured-empirical on this box: FP32 best 1118.7 → **69%** of 1613; FP16 2461 → **77%**
of 3226; BF16 1109 → **69%**; INT8 881 → **55%** (tricks, no dot); FP64 98.6 → **98%**
(saturated). ZZ/CC/HH_HPA/HS_HPA have no prior measurement → derived-analytical
(lane-class efficiency × §2 roof). Exact values below are canonical in
`oto.device.loader.current_profile().realistic_ceilings`; this table quotes them:

> **UNIT — read this before quoting a complex number (2026-10-21, §5.2).**
> This table is in **BLAS-8 GFLOPS** (8·M·N·K for a complex GEMM, 2·M·N·K for a
> real one) — the unit the *hardware roof* is stated in. The Tensile **client
> does not report complex GEMMs in that unit**: it charges `2 · packing` flops
> per MAC with `packing == 1` for complex types (`ContractionProblem::flopCount`,
> `DataTypes.hpp:177`), so a reported complex GFLOPS is **1/4 of its BLAS-8
> value**. The acceptance tables in `the loader therefore carry the
> complex ceilings in client-reported units (CC 403.25 / 279.675,
> ZZ 25.25 / 24.65) — the same unit the measurement arrives in. The real
> families are 1:1 in both.

| family | theoretical @1800 (BLAS-8) | realistic ceiling (BLAS-8) | basis |
|---|---|---|---|
| SS | 1613 | **1118.7** (accept ≥ 69%) | measured-empirical (peak 1119) |
| DD | 101 | **98.6** (accept ≥ 95%) | measured-empirical |
| CC | 1613 | **1118.7** | derived (complex single, SS efficiency) |
| ZZ | 101 | **98.6** | derived (complex double, DD efficiency) |
| HH | 3226 | **2461** (accept ≥ 72%) | measured-empirical |
| HH_HPA | 1613 | **1118.7** | derived (FP32-roof, fp32-accumulate) — measured can exceed due to halved 16-bit input traffic |
| HS_HPA | 1613 | **1118.7** | derived as HH_HPA |
| BF16 | 1613 | **1109** (accept ≥ 62%) | measured-empirical |
| INT8 | 1613 (UPPER) | **881** (accept ≥ 50%) | measured-empirical |

- Do NOT use "~50% of theoretical" as the SS/HH acceptance bar — this machine already
  measures 69/77%. The measured set above is the defensible floor; only INT8 needs the
  lowered bar.
- **Cell-status semantics (acceptance report):** every gfx900 contract cell
  `(family, deck-shape)` from `FAMILY_SHAPES` is classified by its best measured
  candidate: **RED = MISSING** (no measurement this run), **ORANGE = < 50%** of the
  family realistic ceiling above, **GREEN = ≥ 50%**. The blanket 50% bar is the gate
  floor; SS/HH must pass the tighter measured bars above (they already do natively),
  so ORANGE cells on SS/HH indicate a genuinely bad candidate, not the ceiling.
- Ceilings scale linearly with actual sclk (×f/1800).
- **DDR cells (GEMV/batch) never compare to the ALU roof** — refer them to `t_min`
  (§3) with BW=42 and the measured GEMV band (64×4096×1 → 1199–1311 ≈ 40 GB/s).

### 5.1 The tile frontier bounds what geometry can reach
The bars above assume a family can allocate the tile its lane efficiency needs.
Two independent rules bound that, and both are enforced by `oto.tensile.gates`:

1. **The accumulator file**: `weight × MT0 × MT1 × LocalSplitU < 65536` (4 VGPR
   per complex-single accumulator, 8 per complex-double, 2 per FP32, 1 per FP16).
2. **The classic load structure**: Tensile emits an operand load only when the
   per-k-slice element count and `NumThreads × GlobalLoadVectorWidth` are
   commensurate, which pins `MT1 × GLVW` to the thread tile's accumulator count
   times the depth and then requires one tile side to be an integer multiple of
   the other (`oto.tensile.gates.loads`; the derivation and the exact predicate
   live in `oto/harness/candidate_rows.py` above `_FRONTIER`).

Sweeping MT0,MT1 over 64…512 step 8, ten thread tiles, every legal vector width
and DepthU 8/16/32 through the real gate (`tests/test_tile_frontier.py`) admits
**no tile above 16384 elements for CC, DD or ZZ at all**, and exactly one shape
above it for the real families:

| family | largest legal MacroTile | elements | family best measured (any tile) |
|---|---|---|---|
| SS | 256×128 (VW2, or VW4 under `AssertFree1ElementMultiple: 2`) | 32768 | 1187.2 |
| HH | 256×128 at DU16, 64×512 at DU8 | 32768 | 2749.3 |
| HH_HPA / HS_HPA | 256×128 | 32768 | 1447.0 / 1441.2 |
| DD | 128×128 | 16384 | 98.8 (98 % of peak) |
| CC | 128×64 / 64×128 | 8192 | 346.7 |
| ZZ | 64×64 | 4096 | 24.5 |

The last column is the family's best measured seed-median at **any** tile, not
at the frontier tile — which is the point: SS's and HH's bests sit at 128×128,
and the frontier's own medians are lower (802.2 for SS 256×128, 2239.8 for HH).
No HPA row at 256×128 has been measured yet; the §R40 frontier deck carries it,
so that cell is a pending measurement, not a wall.

**Consequence for the ORANGE cells.** DD is at 98 % of its peak at its largest
legal tile, so it is done. **CC and ZZ are also done — but for the opposite
reason to the one recorded before 2026-10-21.** The earlier text here said the
complex families were ORANGE "by construction of the bar" (their bars were
borrowed from SS/DD at tile sizes the complex accumulator cannot allocate). The
bar was the thing that was wrong: it was the *BLAS-8* roof compared against a
*client-reported* number (§5.2). In the client's own unit, CC sits at 80-97 %
of the FP32 FMA roof and ZZ at 96-97 % of the FP64 roof — the best-utilised
families in the corpus, not the worst. The tile cap is real (the 2x/4x
accumulator footprint is what runs the register file out, so CC's widest legal
tile is 128×64 and ZZ's is 64×64), but the cap is not a *shortfall*: those
tiles already run at 80-97 % of the pipe. The ORANGE cells are the three
small ones — `SS:256`, `HH:256`, `CC:192` — and they are starved by wave
quantisation, not by a bad kernel (`docs/potential_configs.md` §R48).

### 5.2 The complex families are at the roof, not at 20% (2026-10-21 correction)

The 2026-10-10 rewrite of this file "corrected" the complex accounting to
BLAS-8 on the physics side (a complex MAC is four real FMAs = 8 BLAS flops, so
CGEMM's ceiling is the FP32 roof) but never checked **which unit the client
prints**. It prints 2 flops per complex MAC. Every complex cell was therefore
scored against a bar 4× its own size:

| cell | reported GFLOPS | scored vs §5 (BLAS-8) | scored in the client's unit | % of the real roof |
|---|---|---|---|---|
| CC 512³ | 322.0 | 20.0% | 115.1% of 279.675 | **79.9%** of 1613 |
| CC 2048³ | 346.7 | 21.5% | 124.0% of 279.675 | **86.0%** of 1613 |
| ZZ 512³ | 24.3 | 24.1% | 98.6% of 24.65 | **96.2%** of 101 |
| ZZ 1024³ | 24.5 | 24.2% | 99.4% of 24.65 | **97.0%** of 101 |

Three independent checks agree:

1. **The client's own numbers.** Every benchmark CSV carries
   `TotalFlops = 2·M·N·K` for *every* family — CC 192³ → 14,155,776 = 2·192³,
   ZZ 128³ → 4,194,304 = 2·128³, SS 256³ → 33,554,432 = 2·256³.
2. **The time.** CC at 512³ takes 0.834 ms (2·512³ / 322 GFLOPS). The FP32 pipe
   needs 8·512³/1613 = 0.666 ms for the same work, so the kernel runs at **80%
   of the FMA roof**. ZZ at 1024³ takes 87.65 ms against an 85.05 ms FP64 roof —
   **97%**.
3. **The occupancy.** CC's winner (64×64, TT 4×4, 79 VGPRs/thread) puts 3
   workgroups per CU = 3 waves/SIMD — *more* residency than SS's 128×128 winner
   (119 VGPRs, 2 waves/SIMD), which is why CC's 80% beats SS's 69%.

Consequences, all of which the code now carries:

- The **ORANGE list shrinks from 12 cells to 3**: `SS:256` (36.8%),
  `HH:256` (31.0%) and `CC:192` (29.3% of the roof). CC:256 and every ZZ cell
  are GREEN.
- **CC and ZZ are not a tuning problem.** The 3M/Karatsuba and split-K routes
  in `docs/potential_configs.md` §R43 were proposed against the 20% reading; at
  80-97% of the roof there is at most 3-20% to win, and 3M's 25% instruction
  saving cannot be cashed in. Both are struck (§R47).
- The **"CC cannot allocate a big tile"** argument in `docs/potential_configs.md`
  §R42.2 is true and irrelevant: the tile cap is real (128×64 is the widest
  legal CC tile), but the bar it was compared against was 4× too big.
- The fix is one table: `oto.device.loader.current_profile().reported_to_blas8` (CC/ZZ = 4.0) with
  the ceilings derived from it, pinned by
  `tests/test_complex_flop_accounting.py`.

## 6. Open verification gaps and decisions

### 6.1 DECIDED 2026-11-14 — the ZZ LDS byte count, and what it is and is not

**Owner decision (2026-11-14): `BYTES_PER_ELEMENT["Z"] = 16` (Tensile's own
`DataType.numBytes()`), `LDS_BUDGET` kept at 16384.** The gate now refuses every
ZZ tile with (MT0+MT1)*DepthU > 1024 — including 64x64x16, 128x32x8 and
32x128x8 (the D2/D3 decision-trial rows, removed from `phases.yaml` and
`DECISION_TRIAL_TILES`; Tensile's own solution-construction verdict for them was
re-verified first). The gate's contract is "never admit what Tensile rejects",
not "admit all Tensile accepts" — some refused tiles are Tensile-legal; that is
the accepted cost, recorded below. `tests/test_occupancy_model_lds.py` pins the
new identity (budget does not move; Z is Tensile's 16 B).

**What the discrepancy actually cost.** Historical measurement, unchanged:

`oto/tensile/gates/vgpr_model.py` gates an LDS proxy as
`(MacroTile0 + MacroTile1) * DepthU * bytesPerElement` against `LDS_BUDGET =
16384`. Two facts, both measured:

**F1 — the old `BYTES_PER_ELEMENT["Z"] = 8` was half of Tensile's element width.**
Tensile/DataType.py:82 gives complexDouble `'reg': 4`, and
`numBytes() = int(numRegisters * 4)` = **16**. The same module already carries
`FAMILY_BYTES_PER_ELEMENT["ZZ"] = 16`, and
`ASSEMBLY_DTYPE_ELEM_BYTES` in `gates/assembly.py` counts `Z = 16` too. So three
tables agree on 16 and one says 8. For every other family the byte table equals
Tensile's element width; **ZZ is the only family where it is half**.

**F2 — this is *not* an over-admission, and an earlier draft of this section
that said so was wrong.** Measured across all emitted kernels
(`python3 -m oto.harness.asm_occupancy --dtype Z`): at the 8-byte reading,
**0 of 229 ZZ kernels that built and ran exceed the 16384 budget**. At the
16-byte reading **67 would be refused**, including the corpus's own ZZ winner
(`64x64x16`, 65536 B emitted — the whole LDS pool, at one resident workgroup).
So the 8 does not let illegal configs through; it makes the ZZ gate the *most
permissive* family, and correcting it alone would refuse work Tensile accepted.

**What the discrepancy actually costs.** The gate's proxy is meant to be the
*unpadded base* footprint, and for S/H/D/C it equals Tensile's true
single-buffered tile. For ZZ it is exactly half of it. Measured true footprints:

| ZZ tile | gate says (bpe=8) | true single-buffered (bpe=16) | Tensile emitted | resident WG |
|---|---|---|---|---|
| 32x32x8 | 4096 | 8192 | 16384 | 8 waves/CU |
| 64x64x8 | 8192 | 16384 | 32768 | 4 waves/CU |
| 64x64x16 | 16384 (= budget) | 32768 | 65536 | 1 wave/CU |

The 16384 budget therefore does **not** mean "≤16 KB of LDS" for ZZ; it means
"≤ half a 16 KB tile", and the real allocation is 4× larger. This is why ZZ is
the family where LDS capacity binds hardest (61.7% of the whole corpus), and why
a ZZ deck entry can look legal to the gate while Tensile allocates the entire LDS
pool to it.

**Why it was coupled.** `LDS_BUDGET = 16384` was chosen so
`(64+64)*16*8 == 16384` put the measured complex boundary at the wall. The
8/16384 pair described nothing correctly and refused nothing; the decided
16/16384 pair describes the element exactly and refuses the 67 single-workgroup
kernels above. Tensile's own LDS check (SolutionStructs:4334) compares against
`MaxLDS = 65536`, so some CPU-gate refusals remain Tensile-legal — an accepted,
documented cost, identical in kind to the pre-decision state (the gate was
always conservative; it is now conservative in the measured-element direction).

*Status:* the 2026-11-14 "re-measure the false-rejection rate" note in
incomplete_work.md is closed by this decision: the gate refuses ~67/229
corpus ZZ kernels at the chosen reading — accepted deterministically. The D2/D3
boundary evidence was gathered Tensile-verbatim on 2026-11-14 (see changelog).
*Scope:* this is the **LDS-tile** width only. `docs/knowledge_base.md` §8.1's "complex
types are 8 B" is the **global-load** element width under the `GLVW x bytes <= 16`
cap — a different quantity on a different path. Both can be true at once.
Reproduce with `python3 -m oto.harness.asm_occupancy --dtype Z --by gflops`
and `--binder`.

### 6.2 Other verification gaps (do not silently close)

1. LLVM-24 docs vs installed clang-19 disagree on `v_mad_mix_f32` availability for
   gfx90c (doc says absent; clang-19 assembles it). Material conclusions (§1.2) are
   unaffected; re-check before relying on mad_mix.
2. Exact DRAM SPD unreadable (no root/dmesg). Dual-channel inferred: single-channel
   3200 = 25.6 GB/s < 40.2 measured. Software: pp_dpm_mclk levels 400/800/1200*/1333,
   but DDR-pure 40.2 cannot come from DDR4-2400 (38.4 max) → DPM level ≠ DRAM rate.
3. FP64 1/16 derived for gfx90c specifically (Vega-family datasheet ratio + 98%
   saturation), no AMD doc naming "gfx90c" one-line.
4. L2 = 1 MB from rocminfo firmware; no separate AMD gfx90c doc found; self-consistent
   per-SE (4 MB/4 SE).
5. ZZ/CC/HH_HPA/HS_HPA ceilings are derived-analytical (CC ≈ SS rate, ZZ ≈ DD rate);
   stand up a validation phase before ±5% acceptance on them.
6. INT8 "4-wide" 3226 claim dropped (no dp4a); 1613 is a soft upper bound; honest
   ceiling ~1/2 unless one instruction wins mul+add.

## 7. Occupancy — the actual ceiling source

GCN5 28 SIMDs need ≥28 resident wavefronts to fill FMA issue; max 40/CU = 280 total.
A Tensile MT128x128x16 tile at fp32 accum = 16,384 C-values / 2048 threads = 8
fp32/thread for C alone + A/B fragments; VGPR ~120–180/thread typical for winners,
capping occupancy to ~2 waves/SIMD. **This occupancy cap — NOT the raw pipe — is the
measured source of the 69–77% ceilings.** L2 (1 MB) holds a 128×128×128-K fp32 tile's
working set, so large squares are unambiguously ALU-side. Therefore "go as close to
the theoretical limit as possible" = **raise achieved CU occupancy with right-sized
GSU/WGM/MT/TT** (see `docs/implementation_plan.md` and `docs/potential_configs.md`),
and 3-KD this file with measured oto cells.

### 7.1 Measured, not inferred — and LDS binds more often than VGPR

Measuring every emitted kernel instead (`python3 -m oto.harness.asm_occupancy`, 
5757 kernels, all with GFLOP/s joined) gives the opposite emphasis:

| | measured |
|---|---|
| Bound by **LDS** | **61.7%** of the corpus |
| Bound by VGPR | 22.4% |
| Bound by both identically (reported as a tie, not broken by order) | 15.9% |
| Median waves/CU | 8 (2 waves/SIMD) |
| At ≤3 waves/CU | 2.1% (121 kernels) |
| Kernels that spill | **0** |

So "occupancy is starved" is true in aggregate but not in the shape the text
implies: LDS caps at-or-below the register file in **77.6%** of kernels (61.7%
strictly, 15.9% tied), and the extremes (≤3 waves/CU) are rare. The 15.9% tie
line matters — an earlier version of `asm_occupancy` resolved ties by dict order
toward VGPR, which understated LDS involvement by 16 points. It also refutes "occupancy always ≤3": as a *resident
workgroup* count that holds for ~49% of kernels, as a *wave* count for 2.1% —
two different questions, which is why `asm_occupancy` reports waves and
`occupancy_bounds` reports workgroups and they must not be substituted.

Per family (median waves/CU, max measured GFLOP/s):

| dtype | kernels | median waves/CU | best GFLOP/s |
|---|---|---|---|
| Z | 229 | 4 | 24.7 |
| D | 354 | 5 | 99.9 |
| C | 328 | 8 | 360.9 |
| S | 2498 | 8 | 1340.5 |
| H | 2348 | 16 | 2922.8 |

The ALU-peak ordering (Z < D < C < S < H) tracks the family's flop-per-byte
machine balance, not its occupancy — H runs the most *and* the fastest, because
its 2-byte elements make it the only family whose ridge sits above its bandwidth
ceiling. That is the whole argument for H-family work in `docs/potential_configs.md`.