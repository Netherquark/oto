# Candidate deck for the gfx90c Vega-7 port — comprehensive rewrite (2026-10-10)

Previous version: `archive/potential_configs.pre_rewrite_20261010.md` (superseded:
its §13.5/§14 used a 2-flops-per-complex-MAC accounting that the saved complex
brief — and the report's own numbers — disprove; all complex-family ceilings and
the split-complex estimate in that version are wrong).

**What this rewrite changes (and why):**
1. **Complex accounting corrected to BLAS-8.** One complex MAC = four real FMAs
   = 8 BLAS flops (`Tensile/Components/MAC_F32C.py` emits four `_v_mac_f32`,
   `MAC_F64C.py` four `v_fma_f64`; complex brief §1). Under that counting CC's
   honest ceiling is the **FP32 peak (1613 GFLOPS)** and ZZ's is the **FP64 peak
   (101 GFLOPS)** — not a "÷4 wall" of 403/25. The `÷4` applies to *complex-MAC
   throughput*, never to BLAS-8 GFLOPS (complex brief §3). The report's
   `%theo` (CC 7.06→20.28 across k192→2048; ZZ 16.66→24.00 across k128→1024)
   is therefore a **true FMA-issue efficiency**, and the user's complaint about
   CC/ZZ is *honest*: both families are genuinely M3-undertuned with **≈3.5×
   headroom**, not 81–96% of a wall.
2. **Split-complex estimate corrected.** Reported split GFLOPS = (4/3)·R_real
   (3 real GEMMs instead of 4, BLAS-8 credits 8 flops/MAC): CC ≈ (4/3)·1135 ≈
   **1513**; ZZ ≈ (4/3)·95–98 ≈ **127–131**. The old draft's "÷3 → ≈378 / +19%"
   was the same mis-accounting.
3. **Winner configs re-resolved per cell** (38-cell table in §2) — several
   overnight corrections land here: SS:512 VW4 **(WIN +10.4%)**, CC:512 winner is
   **WGM4+NLCA1** (not WGM8), CC:256 native best is a **small MT32x32** tile
   (not MT64x64), SS:4096 → **DU16**, ZZ:512/1024 → DU16+PGR=False,
   HH:256 → MT32x64.

Role | Authority
---|---
M1 | ALU/FP32-pipe saturation (1613 GFLOPS FP32 peak, FP64 1/16 → 101)
M2 | wave-quantization / occupancy starvation (idle SIMD issue)
M3 | memory/occupancy-bound (low FMA-issue %, VGPR/LDS pressure)
M4 | measurement artifact (clock, DVFS, L2 residency, tie bandwidth)

Corpus: **10 executed native runs** (2026-09-20 → 2026-10-09;
`run_20261007` = 0 phases, skipped) + the **locked gfx900 floor chain**
(`gfx900_ref_20260925` + resume → 2 locked runs, 2194 phases each).
`kernel_db.json` folds 11 runsets (10 native + floor); the 2026-10-09 overnight
run (`run_20261009_205427`, ~7 h 41 m, 351 phases + 5 swizzle probes) is folded
through the report verdicts but is not yet in `kernel_db` — rebuild it before the
next grading run (`harness/kernel_db.py --rebuild`).

Evidence machinery (all in `/tmp/opencode` until formalised): `resolve_cells.py`
resolves every cell's native winner from the registry `phases` table + per-run
`configs/*.yaml`, and the floor's best kernel per cell from the locked-floor
rows; full dump `/tmp/opencode/cells_resolved.json` (6129 run yamls, 8480
resolver keys, 1113 registry phases). Ground truth for §2/§3/§4.

---

## 1. Verdict under grading (19 WIN / 18 TIE / 1 LOSS)

Accepted rules: **never copy a floor binary**; a spoof-steal is legal only for
the worst native loser and only as a *config adaptation* compiled natively for
gfx90c (documented §7). Real benchmarks run **only in TTY/overnight**; GUI
sessions get CPU-only legality PoCs (§9).

| | count | cells |
|---|---|---|
| WIN | 19 | CC 192/1024/2048, DD 192/256/512, HH 256/512, HH_HPA 512/4096, HS_HPA 512/4096, SS 256/512, **ZZ 128–1024 (all 5)** |
| TIE | 18 | SS 768/1000/1024/1365/2048/4096, HH 1024/2048/4096, HH_HPA 1024/2048, HS_HPA 1024/2048, DD 768/1024/1365/2048, CC 512 |
| **LOSS** | **1** | **CC:256 (−8.7 %)** — the single sanctioned steal, §7 |

WIN cells carry no action. The meaningful list is CC 192/1024/2048, DD
192/256/512, HH 256/512, HPA 512/4096, SS 256/512, ZZ 128–1024. Of the 19
non-WIN cells, 13 are byte-identical-or-clock-noise ties, 4 are DD M1-wall
ties, 1 is the CC:512 config-delta tie, and exactly 1 (CC:256) is a
configurably-fixable loss (§3).

### The headline correction this rewrite makes

The old report's per-family "ceiling" for the orange bar used the **real-GEMM**
resolution (CC 1118.7 / ZZ 98.6), but CC/ZZ were graded at 7–29 % and the draft
interpreted that as "81 %/96 % of an honest ÷4 ALU wall". That wall is a
**mis-accounting**. BLAS charges 8 flops per complex MAC and Tensile's complex
MAC is exactly 4 real FMAs → the ALU-bound complex GEMM has the *same* BLAS-8
ceiling as its real counterpart (complex brief §2–§3):

| family | theo (BLAS-8, honest ceiling) | realistic acceptance bar | measured best | % theo | % of bar |
|---|---|---|---|---|---|
| CC | 1613 | 1118.7 (SGEMM-class) | 327.0 @2048 | **20.3** | 29.2 |
| ZZ | 101 | 98.6 (DGEMM-class) | 24.2 @1024 | **24.0** | 24.6 |

So CC/ZZ are **not near a wall** — they sit at 20–24 % FMA-issue where the same
deck's SS runs 73.6 % and DD runs 97–99 %. Matching SS-level FMA issue would
give CC ≈ 1187 GFLOPS and ZZ ≈ 95–98 without any algorithm change. The headroom
is **≈3.5× (CC) / ≈4× (ZZ)** and lives in occupancy/register/tile levers
(WGM/NLCA/pads/PGR=0/GLVW/GSU), not in exotic instruction tricks (gfx90c has no
`v_mfma`, no `v_dot*`/dp4a, no `v_pk_fma_bf16` — the exotic paths are closed,
§8.2). **CC/ZZ M3 is now the campaign priority (§6 Group B, §10).**

Percent-of-theoretical values are read from `acceptance_report.json`
`per_family_coverage` (stored ×100: CC 705.53 → 7.06 %, ZZ 2398.99 → 24.00 %).

---

## 2. Per-cell evidence — config-resolved winners (38 cells)

Every cell below is resolved from the registry/`kernel_db` (6129 run yamls,
8480 resolver keys). "WIN/TIE/LOSS" is native-vs-floor; `%` = margin over the
floor's best; `%cel` = share of the family's realistic acceptance bar. The spoof column shows
the floor's winning geometry where the resolver could pin it (HPA floor rows
show `?` — the locked floor corpus has no HPA rows; keep the report's floor
values there, unresolved). Tile notation: `MT{SM}x{SN}x{SK}/TT{TM}x{TN}/VW/DU`,
with `+NLCA1`, `padsA=`, `padsB=`, `PGR=False`, `WGMn` marked when set.

### CC (complex single) — honest ceiling 1613, bar 1118.7
| cell | verdict | native | floor | %cel | native winner | floor |
|---|---|---|---|---|---|---|
| CC:192 | WIN +163.5 | 113.8 | 43.2 | 10 | MT32x32 TT4x4 VW2 DU8 WGM4 | MT64x64 TT4x4 VW2 DU8 |
| CC:256 | **LOSS −8.7** | 193.8 | 212.3 | 17 | MT32x32 TT4x4 VW2 DU8 WGM4 padsA=0 | **MT64x64 TT4x4 VW2 DU8** |
| CC:512 | TIE +3.1 | 318.0 | 308.4 | 28 | MT64x64 TT4x4 VW2 DU8 **WGM4+NLCA1** | MT64x64 VW2 DU8 |
| CC:1024 | WIN +6.9 | 310.9 | 290.8 | 28 | MT64x64 TT4x4 VW2 DU8 **WGM8** | MT64x64 VW2 DU8 |
| CC:2048 | WIN +11.9 | 327.0 | 292.3 | 29 | MT64x64 TT4x4 VW2 DU8 WGM4 | MT64x64 VW2 DU8 |

### DD (complex double) — honest ceiling 101, bar 98.6
| cell | verdict | native | floor | %cel | native winner | floor |
|---|---|---|---|---|---|---|
| DD:192 | WIN +259.3 | 76.1 | 21.2 | 77 | MT32x32 TT2x2 VW2 DU8 | MT64x64 TT4x4 VW1 DU8 |
| DD:256 | WIN +20.2 | 85.7 | 71.3 | 87 | MT32x32 TT2x2 VW1 DU8 +NLCA1 | MT64x64 VW2 DU8 |
| DD:512 | WIN +7.4 | 95.7 | 89.1 | 97 | MT32x32 TT2x2 VW1 DU8 +NLCA1 | MT64x64 VW1 DU8 |
| DD:768 | TIE +1.5 | 93.0 | 91.6 | 94 | MT64x64 TT4x4 VW2 DU8 | MT64x64 VW2 DU8 |
| DD:1024 | TIE +1.2 | 92.9 | 91.7 | 94 | MT64x32 TT4x2 VW1 DU8 +NLCA1 | MT64x64 VW1 DU8 |
| DD:1365 | TIE +2.2 | 89.1 | 87.2 | 90 | MT32x32 TT2x2 VW1 DU16 +NLCA1 | MT64x64 VW1 DU8 |
| DD:2048 | TIE +1.4 | 98.0 | 96.6 | 99 | MT64x64 TT4x4 VW1 DU8 | MT64x64 VW1 DU8 |

### HH (packed FP16) — real ceiling 3226, bar 2461
| cell | verdict | native | floor | %cel | native winner | floor |
|---|---|---|---|---|---|---|
| HH:256 | WIN +277.9 | 763.4 | 202.0 | 31 | **MT32x64** TT4x4 VW4 DU16 | MT32x32 TT4x4 VW4 DU16 |
| HH:512 | WIN +13.5 | 1564.1 | 1378.1 | 64 | MT128x128 TT8x8 VW8 DU16 | MT128x128 VW4 DU16 |
| HH:1024 | TIE +1.3 | 2581.9 | 2548.5 | 105 | MT128x128 TT8x8 VW8 DU16 | same |
| HH:2048 | TIE +3.7 | 2670.9 | 2575.2 | 109 | MT128x128 TT8x8 VW8 DU16 PGR=False NLCA1 padsA=0 | MT128x128 VW8 DU16 |
| HH:4096 | TIE +3.3 | 2749.3 | 2662.0 | 112 | MT128x128 TT8x8 VW8 DU16 PGR=False NLCA1 padsA=0 | MT128x128 VW8 DU16 |

### HH_HPA (FP16-in FP32-acc) — ceiling 1613, bar 1118.7; floor unresolved `?`
| cell | verdict | native | floor | %cel | native winner |
|---|---|---|---|---|---|
| HH_HPA:512 | WIN +103.1 | 792.8 | 390.4 | 71 | MT64x64 TT4x4 VW2 DU16 |
| HH_HPA:1024 | TIE +0.1 | 1447.0 | 1445.5 | 129 | MT64x128 TT4x8 VW4 DU16 +NLCA1 |
| HH_HPA:2048 | TIE −0.8 | 1370.3 | 1381.1 | 122 | MT64x128 TT4x8 VW4 DU16 +NLCA1 |
| HH_HPA:4096 | **WIN +10.4** | 1411.1 | 1277.8 | 126 | MT128x64 TT4x8 VW4 DU16 WG[32,8,1] |

### HS_HPA — ceiling 1613, bar 1118.7; floor unresolved `?`
| cell | verdict | native | floor | %cel | native winner |
|---|---|---|---|---|---|
| HS_HPA:512 | WIN +101.3 | 773.7 | 384.4 | 69 | MT64x128 TT4x8 VW2 DU16 |
| HS_HPA:1024 | TIE +0.1 | 1429.7 | 1428.7 | 128 | MT128x64 TT8x4 VW4 DU16 +NLCA1 |
| HS_HPA:2048 | TIE +3.3 | 1388.9 | 1344.2 | 124 | MT64x128 TT4x8 VW4 DU16 +NLCA1 |
| HS_HPA:4096 | **WIN +15.1** | 1441.2 | 1251.7 | 129 | MT64x64 TT4x4 VW4 DU16 +NLCA1 |

### SS (FP32) — ceiling 1613, bar 1118.7
| cell | verdict | native | floor | %cel | native winner | floor |
|---|---|---|---|---|---|---|
| SS:256 | WIN +231.5 | 412.0 | 124.3 | 37 | MT96x96 TT6x6 VW2 DU16 WGM8 | MT32x32 TT4x4 VW4 DU8 |
| SS:512 | **WIN +10.4** | 854.4 | 773.8 | 76 | MT128x128 TT8x8 VW4 **DU8** +NLCA1 padsB=4 | MT128x128 VW4 DU8 |
| SS:768 | TIE +0.9 | 1105.4 | 1095.9 | 99 | MT128x128 TT8x8 VW4 DU8 +NLCA1 padsB=0 | same |
| SS:1000 | TIE +3.7 | 1107.4 | 1067.7 | 99 | MT128x128 TT8x8 VW4 DU8 | same |
| SS:1024 | TIE +4.6 | 1135.1 | 1084.9 | 101 | MT128x128 TT8x8 VW4 DU8 | same |
| SS:1365 | TIE +3.8 | 1110.0 | 1069.8 | 99 | MT128x128 TT8x8 VW4 DU8 | same |
| SS:2048 | TIE −0.4 | 1146.8 | 1151.3 | 103 | MT128x128 TT8x8 VW4 DU8 | same |
| SS:4096 | TIE +3.4 | 1187.2 | 1148.0 | 106 | MT128x128 TT8x8 VW4 **DU16** | MT128x128 VW4 DU8 |

### ZZ (complex double) — honest ceiling 101, bar 98.6
| cell | verdict | native | floor | %cel | native winner | floor |
|---|---|---|---|---|---|---|
| ZZ:128 | WIN +241.4 | 16.8 | 4.9 | 17 | MT32x32 TT2x2 VW1 DU16 | MT64x64 TT4x4 VW1 DU16 |
| ZZ:192 | WIN +40.6 | 20.8 | 14.8 | 21 | MT32x32 TT2x2 VW1 DU8 padsB=4 | MT64x64 VW1 DU8 |
| ZZ:256 | WIN +25.9 | 21.9 | 17.4 | 22 | MT32x32 TT2x2 VW1 DU8 | MT32x32 VW1 DU8 |
| ZZ:512 | WIN +13.8 | 23.4 | 20.6 | 24 | MT32x32 TT2x2 VW1 **DU16 PGR=False** | MT64x64 VW1 DU8 |
| ZZ:1024 | WIN +7.1 | 24.2 | 22.6 | 25 | MT32x32 TT2x2 VW1 **DU16 PGR=False** | MT64x64 VW1 DU16 |

---

## 3. Anatomy of the ties/losses — why each one is (or isn't) a signal

Re-measured classification (extends the superseded §14.2 with regenerated
numbers; **L**=gfx90c_theoretical_limits.md, **P**=potential_configs.md,
**R**=kernel_tuning_research.md):

1. **Byte-identical or clock-noise ties (13 cells).** SS 768/1000/1024/1365/
   2048/4096, HH 1024/2048/4096, HH_HPA 1024 (+0.1)/2048 (−0.8), HS_HPA 1024
   (+0.1)/2048 (+3.3) → native and floor winners are the same tile (e.g. SS:2048
   both `MT128x128x8/8x8/VW4/DU8`; HH:1024 both `MT128x128x8/8x8/VW8/DU16`).
   `clock_adjusted: False` on every cell; native sclk ran 0.910–1.650 GHz
   depending on the day's DVFS (and the 10-09 overnight ran ~1.175 GHz vs the
   1.8 GHz reference — ~1.53× suppressed). A 3–4 % delta sits inside that
   envelope → **re-measure with clock hygiene (§8.5), do not re-tune.**
2. **M1 real-geometry walls (4 DD cells).** DD 768/1024/1365/2048: both arms at
   90–99 % of the 98.6 bar; DD:1024/1365 native even *changes tile* (64x32/32x32)
   to hold the wall. No safe config mutation moves them (L §5 M1).
3. **CC:512 config-delta tie (+3.1).** The resolver pinned the native winner as
   **WGM4 + NLCA1** — the only CC >512 cell where NLCA earns its keep; the
   within-run "WGM8 > WGM4" observation did **not** survive all-run resolution at
   512 (WGM8 wins only at 1024). This is an M3 family tie, not a wall: CC:512
   still runs 28 % of its honest bar (§1) with ~3.5× headroom — Group B treats it
   as a campaign target, not a closed verdict.
4. **The one loss — CC:256 (−8.7 %).** The floor wins **212.3 with a large
   MT64x64x8 tile**; native's best at 256 is a **small MT32x32x8** (193.8, from
   the 1024-named auto pool phase `phase_auto_0_CC_1024x1024x1024_0` beating all
   native 64x64 `Alik_Bjlk` attempts, which topped out at 188.1 pre-overnight).
   So this isn't an occupancy wall (native and floor both run ~3 wg/CU) — it is a
   **tile-geometry choice** the floor got right and the native deck did not.
   Sanctioned steal: §7.
5. **The small-shape M2 row is NOT a verdict loss.** SS/HH/HPA k≤512 WIN vs their
   spoofs (SS:256 +231 %, HH:256 +278 %, HPA:512 +103 %): the floor is weaker at
   those shapes. Their 20–50 %-of-theoretical readings are M2 wave-quantization
   (deck idles at 12–30 % residency, P §14.3), a **coverage target**, not a
   verdict gap — Group A (decked 2026-10-09) hunts it.

**The user-complaint reconciliation:** the report's %theo for CC (7.06–20.28)
and ZZ (16.66–24.00) match the complaint numbers exactly and are *honest*. CC/ZZ
are genuinely ~3.5× undertuned — the fix is occupancy/tile levers (Group B) and
algorithmic routes (§8.2), not a re-calibrated ruler.

---

## 4. Per-family deep triage (hardware-verified)

Data: regenerated `per_family_coverage` (typecode-correct) + per-cell resolved
winners. **Best configs = kernel-type patterns** (R §6, confirmed on the
10-run corpus):

### SS (FP32) — 13 shapes, k=32..4096
| k | cells | GFLOPS | %theo(1613) | winner |
|---|---|---|---|---|
| 32 | 38 | 205.0 | 12.7 | MT96x96/6x6/VW2/DU16 |
| 64 | 55 | 232.9 | 14.4 | MT96x96/6x6/VW2/DU16 |
| 128 | 73 | 276.3 | 17.1 | MT96x96/6x6/VW2/DU16 |
| 192 | 83 | 540.9 | 33.5 | MT128x128/8x8/VW4/DU8 |
| 256 | 82 | 412.0 | 25.5 | MT96x96/6x6/VW2/DU16 |
| 512 | 94 | 854.4 | 53.0 | MT128x128/8x8/VW4/DU8 +NLCA1 padsB=4 |
| 768 | 95 | 1105.4 | 68.5 | MT128x128/8x8/VW4/DU8 |
| 1000 | 95 | 1107.4 | 68.7 | MT128x128/8x8/VW4/DU8 |
| 1024 | 95 | 1135.1 | 70.4 | MT128x128/8x8/VW4/DU8 |
| 1365 | 95 | 1110.0 | 68.8 | MT128x128/8x8/VW4/DU8 |
| 2048 | 95 | 1146.8 | 71.1 | MT128x128/8x8/VW4/DU8 |
| 4096 | 95 | 1187.2 | 73.6 | MT128x128/8x8/VW4/**DU16** |

**Read:** SS ≥768 is done (73.6 % of the FP32 pipe ≈ the practical SGEMM wall
for 1-MB L2 + DDR4; the floor is identical-kernel and identical-speed → TIE).
The front of the family is **k≤512 (M2)**: 12–25 % theo, 12–30 % residency.
**SS:512 VW4 correction landed** in the 10-09 overnight (854.4, +10.4 % vs the
VW4-armed floor) — the last knob-level deficit is closed. Remaining: GSU
wave-fill (Group A1/A2, decked), SS:4096 DU16 (already the winner).

### HH (packed FP16)
| k | cells | GFLOPS | %theo(3226) | winner |
|---|---|---|---|---|
| 256 | 140 | 763.4 | 23.7 | MT32x64/4x4/VW4/DU16 |
| 512 | 184 | 1564.1 | 48.5 | MT128x128/8x8/VW8/DU16 (floor VW4; WIN) |
| 1024 | 187 | 2581.9 | 80.0 | MT128x128/8x8/VW8/DU16 |
| 2048 | 187 | 2670.9 | 82.8 | same +PGR=False/NLCA1/padsA=0 |
| 4096 | 125 | 2749.3 | 85.2 | same |

**Read:** HH ≥1024 is done (v_pk_fma_f16 at the 2× packed wall). HH:256/512 are
M2; **HH GSU>1 stays banned** (Free0Multiple blocks half the versions) → levers:
smaller tiles (decked 64x64/64x32 alternates), VW rules, and the already-landed
MT32x64 at 256. HH_k≥512 VW8 beats the floor's VW4 — a native pattern win.

### HH_HPA / HS_HPA (FP16-in, FP32-acc)
| k | HPA | HS | %theo(1613) | winner |
|---|---|---|---|---|
| 512 | 792.8 | 773.7 | 49.1/48.0 | MT64x64/4x4/VW2/DU16 (HPA), MT64x128/4x8/VW2/DU16 (HS) |
| 1024 | 1447.0 | 1429.7 | 89.7/88.6 | MT64x128/4x8/VW4/DU16, MT128x64/8x4/VW4/DU16 |
| 2048 | 1370.3 | 1388.9 | 85.0/86.1 | MT64x128/4x8/VW4/DU16 |
| 4096 | 1411.1 | 1441.2 | 87.5/89.3 | MT128x64/4x8/VW4/DU16/WGM32x8 (HPA), MT64x64/4x4/VW4/DU16 (HS) |

**Read:** HPA runs the FP32 pipe (~1 ALU op per packed pair after unpack/cvt),
so ~89 % of 1613 ≈ 1440 GFLOPS is the practical HPA wall; both families sit on
it at k≥1024. k=512 is the M2 row (+103 % vs a floor that only managed
384–390). No lever left at k≥1024; k=512 wants the same treatment as SS/HH
small. Floor values unresolved by the resolver (`?`), keep the report's numbers.

### DD (FP64) — 7 shapes
| k | cells | GFLOPS | %theo(101) | winner |
|---|---|---|---|---|
| 192 | 140 | 76.1 | 75.3 | MT32x32/2x2/VW2/DU8 |
| 256 | 140 | 85.7 | 84.9 | MT32x32/2x2/VW1/DU8 +NLCA1 |
| 512 | 140 | 95.7 | 94.8 | MT32x32/2x2/VW1/DU8 +NLCA1 |
| 768 | 116 | 93.0 | 92.1 | MT64x64/4x4/VW2/DU8 |
| 1024 | 140 | 92.9 | 92.0 | MT64x32/4x2/VW1/DU8 +NLCA1 |
| 1365 | 140 | 89.1 | 88.2 | MT32x32/2x2/VW1/DU16 +NLCA1 |
| 2048 | 140 | 98.0 | 97.0 | MT64x64/4x4/VW1/DU8 |

**Read:** DD ≥512 is a real M1 wall at 92–99 % of the DGEMM bar (98 % @2048) —
already past the realistic acceptance bar. Small DD (192/256) WINs handily. No
knob left; DD GSU{2,4} appears in Group A as the only untested small-shape wave
lever, but the bars here are essentially closed.

### CC — the M3 campaign (§6 Group B = this family + ZZ)
| k | cells | GFLOPS | %theo(1613) | %bar(1118.7) | winner |
|---|---|---|---|---|---|
| 192 | 144 | 113.8 | 7.06 | 10.2 | MT32x32/4x4/VW2/DU8 WGM4 |
| 256 | 143 | 193.8 | 12.01 | 17.3 | MT32x32/4x4/VW2/DU8 WGM4 padsA=0 (**LOSS**, §7) |
| 512 | 143 | 318.0 | 19.71 | 28.4 | MT64x64/4x4/VW2/DU8 WGM4+NLCA1 |
| 1024 | 146 | 310.9 | 19.27 | 27.8 | MT64x64/4x4/VW2/DU8 WGM8 |
| 2048 | 147 | 327.0 | 20.28 | 29.2 | MT64x64/4x4/VW2/DU8 WGM4 |

**Read (corrected):** CC is **not** at 77–81 % of a ÷4 wall — it runs
**20.3 % of the honest FP32 ceiling** at k2048. That is genuine M3: 3 wg/CU,
VGPR-bound, idle FMA issue. Headroom ≈ 3.5× to the SS-family 73.6 % issue rate
(→ ~1187 GFLOPS in-deck at current configs, no algorithm change). In-deck levers
for the campaign: **WGMs {4,8} × NLCA {0,1} cross (512 already shows
WGM4+NLCA1 > plain WGM4), pads {1,2,4}, PGR=0 / GLVW=1 (register pressure),
LdsPadA=2, GSU is banned for complex.** Above that: split-complex (§8.2).

### ZZ — same M3 frame at FP64
| k | cells | GFLOPS | %theo(101) | %bar(98.6) | winner |
|---|---|---|---|---|---|
| 128 | 136 | 16.8 | 16.66 | 17.0 | MT32x32/2x2/VW1/DU16 |
| 192 | 129 | 20.8 | 20.56 | 21.1 | MT32x32/2x2/VW1/DU8 padsB=4 |
| 256 | 129 | 21.9 | 21.71 | 22.2 | MT32x32/2x2/VW1/DU8 |
| 512 | 129 | 23.4 | 23.22 | 23.8 | MT32x32/2x2/VW1/DU16 +PGR=False |
| 1024 | 129 | 24.2 | 24.00 | 24.6 | MT32x32/2x2/VW1/DU16 +PGR=False |

**Read (corrected):** ZZ at 24.0 % theo is **not** 96 % optimal — the honest
ceiling is 101 (FP64 peak) and ZZ sits at ¼ of it. ZZ's absolute numbers are low
because each complex MAC = 4 `v_fma_f64` on a 1/16-FP64 part, but the *same*
deck's DD hits 97–98 % of its 98.6 bar with the identical MT32x32/2x2/VW1/DU8
geometry. **ZZ has ≈4× in-deck headroom** (→ 95–98 with DD-level issue) and is
the second Group B target. DU16+PGR=False is already the winner at 512/1024 —
keep, and sweep DU8/DU16 × padsB {1,2,4} × GLVW at the small cells.

---

## 5. Kernel-type patterns — which kernel types actually win (10-run sweep)

Verified across all runs (kernel_db + resolver, typecode-filtered,
median-of-seeds):

1. **Direction: `Ailk_Bjlk` (NT) dominates every family's large cells.** The
   exceptions are the small CC/ZZ cells (32x32 tiles run Alik) — and that
   geometry gap is exactly what CC:256 exposes (§7). HPA winners at 4096 switch
   to `MT128x64/4x8` + WG[32,8,1] — still Ailk.
2. **One tile per family per size regime; tile ∝ 1/element-size**: S/H 128
   (96 at 256), C/D 64 (32 at small), Z 32.
3. **VW pinned at the 16-B hardware cap** (S:4, H:8, C:2, D:1, Z:1, HPA:4).
   The SS:512 VW2 anomaly is **closed**: VW4 landed (854.4, WIN +10.4).
4. **DU8 per K-slice; DU16 for H + SS:4096 + small D/Z** — bigger K-slice hides
   reloads where the block is small.
5. **WGM4 default; WGM8 wins only at CC:1024 and SS:256 (96-tile).** CC:512's
   resolved winner is **WGM4+NLCA1** — "WGM8 is the CC lever" was a within-run
   artifact that all-run resolution rejected.
6. **GSU1 everywhere native** — the untested wave-fill axis (Group A; SS decked
   to GSU{1,2,4}, HH/complex/HPA banned by `assembly_class_valid` gates,
   scheduler.py:1408–1457).
7. **PGR=False lands on big blocks** (ZZ 512/1024, HH 2048/4096); **NLCA1 lands
   on C/Z/HPA/HH-2048**; **pads appear on the M3 front** (CC:256 padsA=0, ZZ:192
   padsB=4, SS:512 padsB=4) — the axis complex never got (gfx900 corpus shipped
   0-pad everywhere). Group C forwards pads/PGR/GLVW (decked).

---

## 6. Candidate deck — wide + narrow, ranked (CPU-gated; TTY-only benchmarks)

Bans honored (do not re-propose): **HH GSU>1**, **SS `96x96x8/6x6/VW2`**
(banned by prior campaign), **complex/HPA GSU>1** (workspace/
`GlobalSplitUAlgorithm` never forwarded; refused `scheduler.py:1408–1457`),
**DirectToVgpr** (not forwarded), **NLCA=3 on 128-width VW4 tiles**
(NumLoads=1 there; only the 96x96x16/6x6/VW2 tile has NumLoads=3).

### 6.1 Group A — wave-fill the M2 small-shape row (decked 2026-10-09)
The k≤512 SS/HH/HPA cells sit at 12–30 % residency (25/34 cells ≤3 wg/CU,
VGPR-bound for wide tiles, LDS-bound for the rest). Residency levers in binding
order:

| candidate | cells | config | status |
|---|---|---|---|
| A1 | SS 256/512 | `MT128x128x8/8x8/VW4/DU8` **GSU{2,4}** | ✅ DECKED |
| A2 | SS 512 | GSU2 on the VW4 winner (854.4) | ✅ DECKED (needs the VW4 base, not VW2) |
| A3 | SS 256 | `MT64x64x8/4x4/VW4/DU8` + `MT96x96x8/6x6/VW4/DU8` GSU2 | ✅ DECKED |
| A4 | HH 256/512 | `MT64x64x16/4x4/VW8/DU16`, `MT64x32x16/4x4/VW8/DU16` | ✅ DECKED (GSU banned) |
| A5 | DD 192/256 | `MT32x32x8/2x2/VW1/DU8` GSU{2,4} | ✅ DECKED |
| A6 | SS 32/64/128 | 96x96 CANDIDATE v2 (GSU2 + DU16) — legality re-gated | 🔬 probe (kept out of seed; `--with-probes`) |
| A7 | wide tiles | **PGR=0** (frees ~8–16 VGPR/thread → +1 wave/SIMD) | ✅ DECKED |
| A8 | wide tiles | **GLVW=1** (32→48 VGPR, 5 waves/SIMD) | ✅ DECKED (partial) |

Wave table for gfx90c (R §1: ≤24→10, 28→9, 32→8, 36→7, 40→6, 48→5, 64→4,
84→3, 128→2, 256→1 waves/SIMD; target ≥4 = ≤64 VGPR, prefer 5–8 = ≤32–48):
the 96x96/6x6 winner (36 accumulators ≈ 84 VGPR) sits at 3 waves/SIMD = 30 %
residency — exactly the M2 cell. **Every M2 fix that stays ≤48 VGPR buys 5
waves/SIMD.** (Caveat: occupancy ≠ speed on ALU-dense loops — these targets
only make sense at k≤512 where latency-hiding is the binding constraint.)

### 6.2 Group B — CC/ZZ M3 campaign (**top priority, new after this rewrite**)
CC 512–2048 + ZZ all-k run 20–24 % of honest theo with **≈3.5–4× in-deck
headroom** (§1/§4). Target: SS/DD-class FMA issue without algorithm change →
CC toward 700–1000, ZZ toward 60–90. Ladders, CPU-gated, TTY-only:

| candidate | cells | config | status |
|---|---|---|---|
| B1 | CC 512/1024/2048 | **WGM {4,8} × NLCA {0,1}** cross on the MT64x64/4x4/VW2/DU8 body (512: expect WGM4+NLCA1 to confirm; 1024: WGM8 shelf) | 🔬 NEW |
| B2 | CC 512/1024/2048 | **LdsPadA {1,2,4} + LdsPadB {0,1,2}** (LdsPadA=2 on the steal block, §7) | 🔬 NEW |
| B3 | CC 512/1024/2048 | **PGR=0 + GLVW=1** (register-pressure; 3→4-5 wg/CU at 128-VGPR bodies) | 🔬 NEW |
| B4 | CC 256 | **steal block §7** (Ailk_Bjlk MT64x64x8 native + WGM8/LdsPadA=2/PGR0/GLVW1) | 🔬 NEW (bar ≥214) |
| B5 | ZZ all-k | **DU8 vs DU16 × padsB {1,2,4} × GLVW {1}** on the MT32x32/2x2/VW1 body; keep PGR=False at 512/1024 | 🔬 NEW |
| B6 | CC/ZZ | **WGM {2,4,8} sweep at 512–2048** (L2-rasterization, §8.3) | 🔬 NEW |

### 6.3 Group C — swizzle / StaggerU (complete)
StaggerU/StaggerUMapping/StaggerUStride probes shipped in the 10-09 seed (5
swizzle probes, no verdict change on any covered cell). Closed: LDS-bank-swizzle
does not move a 1-MB-L2-bound iGPU deck. Any future row needs a count.
Keep the boundary probe rows out of the seed (parity: every overlay row must pin
to the shipped grid).

---

## 7. Spoof-steal route — CC:256 (the only sanctioned steal)

**Why this is the one cell:** it is the only true vs-spoof LOSS (−8.7 %).
Native's resolved best at 256 is a **small MT32x32x8 tile** (193.8,
`phase_auto_0_CC_1024x1024x1024_0` — a 1024-named auto-pool phase that wins the
256 cell; verified in the 10-09 overnight). Native 64×64 `Alik_Bjlk` attempts
stall at 188.1. The floor runs **212.3 with a larger MT64x64x8 tile**. So the
floor's edge is *tile geometry + direction*, not code-object magic — and that
geometry is trivially re-derivable for gfx90c.

**Steal (allowed): adapt the floor's winning *config* to a native gfx90c
compile.** Never reuse the floor binary or the floor's code object.

1. **Tile/direction:** `Ailk_Bjlk` (NT) **MT64x64x8 / TT4x4 / VW2 / DU8** — the
   exact geometry the floor wins with, but as a fresh native YAML in the deck
   (floor YAML is MT64x64/4x4/VW2/DU8; the native winner pattern for CC ≥512 is
   the same body, so the pieces exist in-deck).
2. **Knobs the floor never had** (this is the "tweaked to suit gfx90c" part):
   **WGM8** (native-verified at CC:1024 + SS:256), **LdsPadA=2** (1-MB-L2 vs
   gfx900's 4-MB — the floor's 0-pad default bank-conflicts at 64×64 on this
   part), **PGR=0 / GLVW=1** (register-pressure; gfx90c has 64 KiB VGPR/SIMD —
   pushing to 4–5 wg/CU at 128 VGPR), **NLCA1** variant (the CC:512 winner).
3. **Why not port the floor's 128×128 complex tiles:** gfx900 relied on 4-MB-L2
   rasterization; gfx90c's 1 MB does not hold 128-wide complex A+B+C working
   sets (R §5 finding 16a–b). The 64×64 big-tile direction is the *safe* one.
4. **Legality + success bar:** all rows go through `check_candidates.py` /
   `scheduler` gates (assembly class, occupancy, LDS-fit) as CPU-only PoCs from
   GNOME; TTY benchmark inside the same pinned-clock A/B as the other cells.
   **Success = ≥214 native** (floor 212.3 + band edge). Anything ≥214 retires
   the only LOSS on the board; a miss teaches whether it was direction or clock.

The steal block is **B4** in §6.2. If it lands, expect the same Ailk_Bjlk
64×64 body to re-audit CC:512/1024/2048 (those are already 64×64 — the 
direction cross is their remaining un-tested axis).

---

## 8. Other routes

### 8.1 GlobalSplitU wave-fill — SS only (and only at small shapes)
GSU splits K across workgroups for wave-fill (M2). Legality is dtype-locked
(`scheduler.assembly_class_valid:1408–1457`): **complex/HPA GSU>1 illegal** (no
MFMA on the reachable writer paths; this port never forwards
`GlobalSplitUAlgorithm`/workspace, so only SingleBuffer-atomic is reachable),
**HH GSU>1 banned** (AF0EM≥2 not shipped). **SS is the only GSU-legal family**
(ladder {1,2,4}). Use it only where M·N-tiles < ~7 waves (k≤512): GSU adds
launch + atomic-write overhead and on ALU-saturated ≥768 cells it would *cost*.
Watch atomic SingleBuffer drift on the shared DDR4 bus — a GSU regression vs
GSU1 points at that mechanism, not the tiling.

### 8.2 Split-complex (the route past the 4-FMA MAC) — corrected quantification
Complex GEMM on gfx90c has no instruction-level escape hatches (no `v_mfma`,
no `v_dot*`/dp4a, no `v_pk_fma_bf16` — R §3/§8.2, complex brief §8). The four
real FMAs per complex MAC are irreducible **per MAC**, but the *GEMM count* is
not: decompose CGEMM into **3 real GEMMs + a combine pass** (Gauss/Karatsuba:
R = ReA·ReB, I = ImA·ImB, P = (ReA+ImA)(ReB+ImB); Re(C) = R−I, Im(C) = P−R−I) —
the rocBLAS-pre-MFMA / MAGMA strategy (references: complex brief §4–§5, with
MAGMA at 79 % CGEMM / 71 % ZGEMM peak on Fermi; BLIS 3m/4m: Van Zee & Smith
TOMS; rocBLAS ships only the fused 4M path —
[complex_gemm_research_brief.md](complex_gemm_research_brief.md)).

**Corrected math — reported split GFLOPS = (4/3)·R_real.** Three real GEMMs run
at the real-family reported rate R_real, and the deck still *counts* 8
flops/complex-MAC:

- CC: R_real = SS-class ≈ **1135** (SS:1024) → split CC ≈ **1513** —
  **4.6× over native 327** (and 4.9× over 310.9 at 1024).
- ZZ: R_real = DD-class ≈ **95–98** → split ZZ ≈ **127–131** —
  **5.3–5.4× over native 24.2**.

**Honesty guards (from the brief):** 3M is **not** cheaper per MAC — it is 3 mul
+ ~5 add ≈ **7–8 ops** vs 4M's 4 fused instructions; it wins **per GEMM** (4→3)
because the combine is only O(MN+MK+KN) and amortizes at large K. The 2M/Caday
and Ozaki/INT8 routes are moot without an INT8/matrix engine on gfx90c. And the
traffic story matters: 3 real GEMMs read A/B in 3 passes — on this part's ~30–
40 GB/s DDR4 the win is real only **for K-large cells** where the combine is
negligible and the GEMMs are FMA-bound, not LDS/DDR-bound.

**Concretely (Phase-0, CPU-only legality):** a client-side split wrapper
(cgemm3m/`zgemm3m`-style caller) + 3 native real GEMMs; legality PoC runs in
GNOME (no GPU stress — it is 3 SS/DD kernels the deck already ships, legality is
per-kernel, already gated). TTY benchmark at CC:1024/2048 + ZZ:512/1024. Priority
**after** the Group B occupancy campaign saturates (the split's ceiling assumes
real kernels at real-family efficiency — raising CC/ZZ native issue from 20 % →
50–70 % first makes the split's 1513 an *additive* prize, not a fix for a
broken pipe).

### 8.3 L2-rasterized WorkGroupMapping (1-MB L2 retune)
gfx900's 4-MB L2 ignored rasterization; gfx90c's 1 MB makes WGM the difference
between L2 hits and DDR round-trips (R §5 finding 16b). CC/ZZ already ship WGM
{4,8}; probe WGM {2,8,16} on the wide SS/HH tiles at 768–4096 — the 1-MB L2
(A+B+C working sets: 128×128×8×2 ≈ 256 KB + C 64 KB) fits, but the *order*
tiles are visited decides reuse. B6 covers the complex side; keep SS/HH probes
in the timestamped mirror (`--with-probes`), not the seed.

### 8.4 Non-temporal loads (new; narrow)
`NonTemporalA/B/C/D` lowers to `buffer_load … th:TH_LOAD_NT` (R §4 finding 11).
Do **not** use on normal tiled A/B (they reuse across K within 1 MB L2 — NT
would flush it); use on (a) the C operand read-modify-write, (b) the
single-K-pass GSU kernels where each tile is read once. One legality-checked
probe row per case is enough to decide.

### 8.5 Measurement hygiene — the prerequisite for trusting ANY delta (M4)
Set by the report: `clock_adjusted: False` on every cell; native sclk
0.910–1.650 GHz across runs; the 10-09 overnight measured **~1.175 GHz vs the
1.8 GHz reference (~1.53× suppressed)** — within-run deltas are safe, cross-run
deltas are not. CUTLASS-grade methodology for the iGPU (complex brief / R §6):
fixed-frequency / zero-fill runs, warm-up until clocks settle (~3 s), ≥1000
profile iterations on small kernels, **buffer rotation ≥2× L2** to defeat false
L2 hits, cooldown between tests, `rocm-smi` watch on sclk/temp. **First TTY
move after any new deck: a same-run, pinned-clock A/B of the shared cells** —
most "ties" are clock noise and should re-resolve to WINs without any knob.

---

## 9. GUI-safe plan (GNOME constraints)

Everything in §6–§8 ships as **CPU-only legality PoCs** from GNOME; real
performance runs live in TTY/overnight. Concretely:

1. `check_candidates.py` / `scheduler` gates accept/reject every row in §6/§7
   (assembly-class, occupancy, LDS-fit) — run them; report the pass/fail table.
2. `port_tensile.py` compiles nothing GPU-heating in GUI sessions: legality PoCs
   are config validation + `Tensile` dry-run, no 2_BenchmarkData under a live
   desktop.
3. No sustained stress: no multi-hour loops, no concurrent desktop 3D; `rocm-smi`
   stays ≤70 °C; any ring-timeout/reset aborts the PoC and returns to the
   harness with a `SKIP` not a verdict.
4. Real benchmarks (the A/Bs, Groups A/B/C, steal block) are `command.txt`
   TTY/overnight items only; overnight runs use the piped invocation
   (`… --live off | tee overnight_$(date +%Y%m%d_%H%M).log`).

---

## 10. Next overnight queue (re-sequenced; CC/ZZ M3 first)

1. **CC/ZZ M3 campaign (§6.2 Group B) — highest value.** CC 512–2048 + ZZ
   all-k: WGM{4,8}×NLCA{0,1} cross, LdsPadA{1,2,4}/LdsPadB{0,1,2}, PGR=0/GLVW=1,
   DU8×DU16×padsB ladders. Target: CC 327→700+, ZZ 24.2→60+ (SS/DD-class issue,
   not the split — that comes after).
2. **CC:256 steal block (§7, B4):** native `Ailk_Bjlk` MT64x64x8/4x4/VW2/DU8 +
   WGM8 + LdsPadA=2 + PGR=0/GLVW=1 (+NLCA1 variant). **Bar ≥214.** Never reuse
   the floor binary.
3. **SS GSU{1,2,4} on the VW4 winners (A1/A2) + HH 64x64/64x32 alternates (A4) +
   DD GSU{2,4} (A5).**
4. **WGM probe on wide SS/HH tiles (768–4096, §8.3); NT probes (§8.4).**
5. **Split-complex Phase-0 legality + first large-K TTY benchmark (§8.2)** once
   Group B is measured — the (4/3)·R_real ≈ 1513/127–131 readout is the
   campaign's escalation prize.
6. **Clock hygiene first:** same-run pinned-clock A/B of the 30 shared cells
   before trusting any ±4 % delta (§8.5). Rebuild `kernel_db.json` after the run.

---

## Sources (all real; full lists in `kernel_tuning_research.md` Sources and
`complex_gemm_research_brief.md`)

- [complex_gemm_research_brief.md](complex_gemm_research_brief.md) — BLAS-8
  accounting, 4-FMA MAC (Tensile
  [MAC_F32C.py](https://github.com/ROCm/Tensile/blob/develop/Tensile/Components/MAC_F32C.py)
  /
  [MAC_F64C.py](https://github.com/ROCm/Tensile/blob/develop/Tensile/Components/MAC_F64C.py)),
  3M/4M instruction counts, MAGMA/Fermi, Ozaki-II, M3XU. **The citation for §1
  and §8.2.**
- Hardware ceilings: `gfx90c_theoretical_limits.md`; occupancy/issue:
  `kernel_tuning_research.md` §1–§3 (GCN5 wave64, 4×SIMD-per-CU, 10 waves/SIMD,
  DDR4 ~30–40 GB/s, FP64 1/16).
- Local Tensile/knob ground truth: `kernel_tuning_research.md` Sources
  (`Common.py`, `SolutionStructs.py`, `KernelWriterAssembly.py`, tuning docs);
  scheduler gates: `scheduler.py:1408–1457`.