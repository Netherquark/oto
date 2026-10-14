# Candidate deck for the gfx90c Vega-7 port — rewrite 2 (2026-10-14)

Supersedes `archive/potential_configs.pre_rewrite_20261014.md`. That version's
M1–M4 triage, its BLAS-8 complex accounting, and its per-cell winner table are
still correct and are carried forward. What is **new** here is a corpus-wide
forensics pass over all 5757 emitted kernels plus the knob census, which
overturns the plan's central premise.

**Owns: the candidate deck, the routes to beat the spoof floor, and the search
rules.** Does not own: acceptance bars/ceilings/verdicts (`gfx90c_theoretical_limits.md`
§5), measured evidence (`results.md`), or GCN hardware facts
(`knowledge_base.md`).

---

## 1. Executive — five findings that change the plan

**F1. The spoof floor has ZERO clock telemetry, so no verdict against it can be
clock-corrected.** `gfx90c_results/acceptance_report.json`, run
`run_20261013_214649`: for the only LOSS cell (CC 256³),
`spoof_clock_sclk_hz = 0.0`, `spoof_clock_coverage = 0.0`, `clock_adjusted =
False`. The native arm ran at `native_clock_sclk_hz = 1175 MHz` against a
`sclk_ref_hz = 1800 MHz` reference. The −8.7% is therefore **not a tuning
failure and not evidence about kernels** — it is an un-correctable measurement
asymmetry. The fix is a floor-arm telemetry run, which is the user's TTY job,
not a candidate change. Recorded as a `DECISION REQUIRED` in
`gfx90c_theoretical_limits.md` §6.1; do not silently widen the band.

**F2. Two knobs in the deck have only ever held ONE value, across all runs and
both arms.** `allruns.py` (`--json`), never-exercised-knobs section:
`GlobalSplitU = ['1']`, `StaggerU = ['32']`. Additionally, no winning config in
`cells_resolved.json` sets `PrefetchGlobalRead`, `AggressivePerfMode`,
`MaxOccupancy`, `LocalSplitU`, `BufferLoad`, `InnerUnroll`, `FractionalLoad`,
`UseSgprForGRO`, `LocalRead2A/B`, `GlobalRead2A/B`, `StorePriorityOpt`,
`GlobalLoadVectorWidthA/B` or `NumLoadsCoalescedB`. **Every tuning conclusion
drawn so far is a conclusion about MacroTile × ThreadTile × DepthU ×
VectorWidth × WorkGroupMapping only.** The tile axes are mined out; the other
eleven axes are untouched.

**But "never set" ≠ "never varied".** Tensile fills every absent knob from
`defaultBenchmarkCommonParameters`, so the base already carries `BufferLoad=True`,
`StaggerU=32`, `MaxOccupancy=40`, `AggressivePerfMode=1`, `PrefetchGlobalRead=1`,
`UseSgprForGRO=-1`, `GlobalLoadVectorWidth=-1`, `InnerUnroll=1`,
`FractionalLoad=0`. The experiments are the *non-default* values; a sweep value
equal to the default re-measures the baseline. Verified defaults:
`knowledge_base.md` §7.1; machine-readable `TENSILE_KNOB_DEFAULTS` in
`oto/tensile/decks.py`, enforced by `tests/test_knob_sweep.py`.

**F3. The complex families are the two *narrowest* searches in the deck, which
is exactly backwards.** Measured distinct `(MacroTile, ThreadTile,
VectorWidth)` triples per family (`allruns.py`): SS 49 (16 distinct TT), HH 42
(12), HS_HPA 40, HH_HPA 36, DD 17 (7), **CC 17 (6)**, **ZZ 9 (5)**. CC and ZZ
are the worst performers AND the least searched. For CC the corpus only ever
emits ThreadTiles 2x2, 2x4, 4x2, 4x4, 4x8, 8x4 — and the *widest legal* corner,
**MT128x128x8 at TT8x4 and TT4x8, was never generated at all** (CC's largest
measured MacroTile is 128x64). For ZZ, **MT128x128x8/TT4x4 and MT128x64x8/TT4x4
are legal and were never generated** (the corpus's largest ZZ tiles are
128x32x16 and 32x128x16, both at 2x8).

The narrowness is partly structural, not lazy, and this decides what can be
tried: the legality gate caps the complex accumulator at
`ACCVGPR_BUDGET = 128`, so CC TT6x6 (144 accumulator VGPRs) and TT8x8 (256) are
refused with `Occupancy limit: ThreadTile 6x6 needs 144 accumulator VGPRs`, and
TT6x6 also fails `MacroTile 128x128x8 not divisible by ThreadTile 6x6`. Verified
through `validate_config`. **So the exploit is not a bigger ThreadTile — it is a
bigger MacroTile at the same accumulator width**, which raises arithmetic
intensity without touching the register file.

**F4. Occupancy is low, but not in the way the deck assumed — and the assumed
direction of the fix is inverted.** Measured from emitted code objects
(`python3 -m oto.harness.asm_occupancy`, 5757 kernels, GFLOP/s joined to 100%):
LDS strictly binds **61.7%**, VGPR strictly binds 22.4%, both cap identically in
15.9%; median 8 waves/CU; **121 kernels (2.1%) at ≤3 waves/CU**; 2810 (48.8%) at
≤3 *resident workgroups*/CU; **zero kernels spill to scratch**. The old deck's
M1/M2/M3 ("ALU saturation", "occupancy starvation", "VGPR pressure") is wrong in
its emphasis. Occupancy is *shape-limited*, not resource-starved, and the
binding constraint is LDS capacity — which is the one thing raising `ThreadTile`
makes worse.

**F5. Complex runs at 20–25% of an achievable ceiling that no tile in the legal
space can reach, and the reason is instruction count.** See §6. CC's best
measured kernel is 360.9 GF/s (MT64x64x8/TT4x4, 79 VGPR, 12 waves/CU) against a
1118.7 bar; ZZ's is 24.7 (MT32x32x8/TT2x2, 63 VGPR, 8 waves/CU) against 98.6.
The corpus's ridge table places the ALU ridge beyond the accumulator cap for Z.
**The gap is not closable by ThreadTile search alone** — which is why the deck
must spend its budget on the un-varied knobs and on the larger-MacroTile /
same-accumulator corner (F3), not on more ThreadTile widths.

---

## 2. Why each tie/loss happens (per family, cause-coded)

Verdicts from `run_20261013_214649`: 19 WIN / 18 TIE / 1 LOSS. Reads as "native
already beats spoof" — and it does. But that is the wrong comparison: the spoof
floor is *also* mediocre on this part (CC 346.7 = 31% of ceiling). The real gap
in every family is **native vs. ceiling**, so §2 codes each family by what
limits it, and §8 targets that.

| family | verdict | best median | % ceiling | limiter | cause |
|---|---|---|---|---|---|
| CC | 3W/1T/1L | 346.7 | 31.0% | **issue rate** | 4 real FMAs/complex-MAC, no complex-FMA opcode, no MFMA; 8 B/elem; ridge past legal TT (§6) |
| ZZ | 5W | 24.4 | 24.7% | **issue rate + VGPR** | 16 B/elem, 4 regs/elem → TT2x2 is the only tile with headroom; ridge at MT≈10, i.e. unreachable |
| HH | 2W/3T | 2749.3 | 111.7% | already at bar | — |
| HH_HPA | 2W/2T | 1447.0 | 129.4% | already at bar | — |
| HS_HPA | 2W/2T | 1441.2 | 128.8% | already at bar | — |
| SS | 2W/6T | 1187.2 | 106.1% | issue rate at high k | — |
| DD | 3W/4T | 98.0 | ~99% | at bar | — |

Cause codes for the 18 ties and 1 loss, individually:

- **CC:256 LOSS** — measurement (F1). Not a kernel deficit. Do not add candidates for it.
- **CC:512 TIE** — real, +3.1%. Winner MT64x64/WGM4+NLCA1; the deck's
  128x128-class tiles were never generated for CC, so this is unexplored space.
- **DD 768/1024/1365/2048 TIE** — all ≤2.2%. DD's best measured kernel is
  99.9 GF/s at MT32x32x8/**TT2x2**, 35 VGPR, **28 waves/CU** — the highest
  occupancy in the corpus. DD is at its 98.6 bar already; residual gap is
  issue rate.
- **HH 1024/2048/4096 TIE** — +1.3 to +3.7%. HH's best is 2922.8 at
  MT128x128x16/TT8x8, 63 VGPR, 16 waves/CU. HH already exceeds its 2461 bar.
- **HH_HPA / HS_HPA 1024/2048 TIE** — −0.8% to +3.3%. At bar.
- **SS 768/1000/1024/1365/2048/4096 TIE** — +0.9% to +4.6%. SS's best measured
  is 1340.5 at MT128x128x8/TT8x8, 111 VGPR, 8 waves/CU; SS:4096 already exceeds
  its 1118.7 bar. **The residual SS gap is entirely in the small-shape rows**
  (k=32: 276.1 = 24.7%; k=192: 341.8 = 30.6%), which is wave quantization, not
  issue rate.

---

## 3. Occupancy — settled, and it is not the deck's problem

`python3 -m oto.harness.asm_occupancy --check-calibration` exits 0 (10/10 rows
of the AMD/ORNL GFX9 VGPR→waves/SIMD table reproduced, granule 4). The corpus
wide numbers above are from that model. Three consequences:

1. **There is no occupancy-starvation problem to fix.** Only 2.1% of kernels run
   at ≤3 waves/CU. The 48.8% figure the user noticed is *resident workgroups*,
   which is a different axis (a 1024-thread workgroup is 16 waves, so it reads
   as "1 workgroup" while occupying 16 of 40 wave slots). Both numbers are in
   `gfx90c_theoretical_limits.md` §7.1.
2. **LDS capacity, not VGPR, is what caps residency** for 61.7% of kernels —
   which is why the `LDS_BUDGET` entry (§10) matters and why `LdsPad`/
   LDS-layout angles are deprioritised: bandwidth is ~8× oversupplied at
   TT4x4 FP32 (`knowledge_base.md` §1 rate card), but *capacity* still decides how many
   workgroups fit, and `LdsPad` spends that capacity.
3. **No kernel spills.** Zero kernels carry a private segment. So there is no
   scratch-spill tax to recover, and `MinVgprNumber`/`MaxVgprNumber` tuning has
   no measured motivation.

---

## 4. Kernel-type patterns across all runs (the high-level answer)

From the 5757-kernel table, ranked by best measured GFLOP/s per family:

| family | best tile | TT | VGPR | waves/CU | LDS | best GF/s |
|---|---|---|---|---|---|---|
| H | 128x128x16 | 8x8 | 63 | 16 | 16384 | 2922.8 |
| S | 128x128x8 | 8x8 | 111 | 8 | 16384 | 1340.5 |
| D | 32x32x8 | 2x2 | 35 | 28 | 8192 | 99.9 |
| C | 64x64x8 | 4x4 | 79 | 12 | 16384 | 360.9 |
| Z | 32x32x8 | 2x2 | 63 | 8 | 24960 | 24.7 |

The pattern, stated as a rule: **the winning ThreadTile area scales inversely
with bytes-per-element.** 2 B → 8x8; 4 B → 4x4–8x8; 8 B → 4x4; 16 B → 2x2. That
is the accumulator register budget: `TT_area × bytesPerElement` must stay under
~64 accumulator VGPRs to leave room for A/B fragments and addressing. Every
family's winner sits at the largest TT satisfying that rule. **This is why CC
and ZZ are stuck: their rule-implied TT (4x4 and 2x2) is already the winner, and
the next step up breaks the register file.**

Second pattern — **waves/CU does not predict GFLOP/s.** D wins at 28 waves/CU
and H at 16, but C's 12 beats Z's 8 despite occupancy close to 2/3rds. What
predicts GFLOP/s is `bytesPerElement` × `flopsPerMac`, i.e. how much work each
FMA issue buys, which is fixed per family and not a knob.

Third — **LDS at the winner is always ≈16–25 KB, never 64 KB.** The winners
operate at 1/4 to 1/3 of the 64 KB LDS budget, i.e. 2–4 resident workgroups.
That is the architectural sweet spot for this part.

Fourth — **`WorkGroupMapping` is 4 or 8 at every winner, never 1.** WGM≥4 is
what keeps neighbouring CUs on the same matrix B slice, which matters because
L2 is 1 MB shared. No winner uses WGM 2 or 16.

---

## 5. Physics — why complex cannot reach its ceiling, and what that implies

Ridge for a tiled kernel (not the minimum-traffic figure the previous roofline
used):

```
AI = flopsPerMac · MT0·MT1 / ((MT0 + MT1) · bytesPerElement)
```

| family | bytes/elem | peak | ridge (F/B) | square MT at ridge | legal TT at that MT |
|---|---|---|---|---|---|
| S | 4 | 1613 | 38.4 | 154 | 8x8 ✓ |
| H | 2 | 3226 | 76.8 | 154 | 8x8 ✓ |
| D | 8 | 101 | 2.4 | 19 | 2x2 ✓ (already ALU-bound at MT≥32) |
| C | 8 | 1613 | 38.4 | 77 | 4x4 ✓ (MT77 needs MT≥96 to cross) |
| Z | 16 | 101 | 2.4 | 9.6 | 2x2 ✓ (ALU-bound everywhere) |

Two families are already past their ridge and still at 20–25% of ceiling: that
is the proof that **complex is issue-bound, not bandwidth-bound**. The
instruction-count argument: one complex MAC is four real FMAs and there is no
complex-FMA or MFMA opcode on gfx90c. Complex-MAC *throughput* is ÷4 relative to
a real MAC, but BLAS-8 accounting credits 8 flops per complex MAC, so the BLAS
ceiling is unchanged (`oto/tensile/gates/assembly.py`). Reaching it needs the
FMA pipe issuing every cycle, which needs the issue slots not spent on
addressing, LDS reads and loop overhead.

**Implication for the deck:** for C and Z the only levers that reduce
non-FMA issue slots are (a) more coalesced loads (`NumLoadsCoalescedA/B`),
(b) longer unroll (`InnerUnroll`, `DepthU`), (c) `UseSgprForGRO` — moving
global-read addresses from VGPR to SGPR frees registers, which is the scarce
resource for Z. Tiles are exhausted.

---

## 6. The routes (steal + alternatives)

### Route A — Spoof-steal, restricted to the two worst losers, with a port record

Sanctioned per the user's own caveat: **only CC and ZZ**, only the worst cells,
and each stolen config must be documented as derived-from-gfx900 with its
adaptation. gfx900 floor configs used verbatim (~1100 phases of the locked
chain) were tuned for a 56-CU HBM part; the three that must be adapted are
tile size (HBM-optimal tiles overshoot a 1 MB L2), `WorkGroupMapping` (tuned
for 56-CU raster order, not 7), and `GlobalSplitU` (a dGPU never needed it).

Restriction: **only MT64x64 and smaller may be stolen.** gfx900's rank-1
solutions cluster at MT 64x64 and below, and those are also the correct class for
a 1 MB L2. An MT128x128 gfx900 tile would be stealing a config tuned for a part
with ~16× the L2. **AMD's shipped library is not uniformly small-tiled** — the
same vega10 tree holds MT128×16 (FP32), MT064×064 (FP64) and MT016×016 (FP16) —
so "AMD prefers small tiles" is not a supportable generalisation; only the
*rank-1* rows are small, and those are the ones that transfer
(`kernel_tuning_research.md` §9.1).

**The port record.** AMD's own rank-1 solutions for the sibling Vega parts
(gfx906/gfx900, wave64, 64 KB LDS/CU — the same data-path shape as this part with
60 CUs and ~900 GB/s HBM2 instead of 7 and 42 GB/s), from
`kernel_tuning_research.md` §9.1:

| source family | rank-1 tile | TT | DU | WorkGroup | VW | BufferLoad | PGR | PLR | APM | MaxOcc |
|---|---|---|---|---|---|---|---|---|---|---|
| FP32 (`vega10…SB`) | 128x016 | 4x4 | 16 | 32x4x2 | 4 | 1 | 0 | 1 | 1 | 40 |
| FP64 (`vega20…DB`) | 064x064 | 4x4 | 4 | 16x16x1 | 2 | — | — | — | 1 | 40 |
| FP16 (`vega20…HB`) | 016x016 | 2x2 | 8 | 8x8x1 | 2 | — | — | — | — | 40 |

What transfers, and what must be re-derived for gfx90c:

| knob | AMD's gfx900 choice | keep / adapt for gfx90c | why |
|---|---|---|---|
| `ThreadTile` | 4x4 (FP64), 2x2 (FP16) | **keep** — matches this part's own measured winners (DD 2x2, ZZ 2x2) | accumulator register budget is a function of bytes-per-element, which is identical |
| `DepthU` | 4 (FP64), 8 (FP16) | **adapt down** — 16 (FP32's) would need 2× the LDS on a part with 1/60th the bandwidth | LDS capacity is the binding constraint here (61.7% of the corpus) |
| `WorkGroup` / `LocalSplitU` | `32x4x2` = LSU 2 on FP32 | **keep the LSU shape** — AMD itself splits the M extent | LSU is the one wave-fill knob legal for this part's complex families; `GlobalSplitU` is not (§8.1) |
| `StaggerU` | 32 | **re-sweep** 0/8/16 — 32 was chosen for a 56-CU raster | §8.1 sweeps it |
| `WorkGroupMapping` | (not overridden) | **re-sweep** 4/8 — this part's winners use 4 or 8 | 7 CUs with 1 MB L2 wants neighbours on the same B slice |
| `MaxOccupancy` | 40 (uncapped) | **re-sweep** 8/12/20 | 100% of shipped AMD uses 40; on 7 CUs wave count is scarcer |
| `AggressivePerfMode` | 1 | **re-sweep** 1/2 | mode 2 *may* cap LDS (comment says 2 waves/SIMD; branch unconfirmed at pinned commit — corpus3 Q-E ii), and 2 waves/SIMD is this part's measured median |
| `BufferLoad` | 1 (FP32) | **keep** | gates the StaggerU path |

The concrete stolen cells are the deck entries in §8.2 — the ones that exist only
because the floor won there and native never generated the tile.

### Route B — Pick up the ten knobs the corpus never *explicitly set* (highest yield, no steal)

§F2. **"No winner sets knob X" is not "knob X has never been varied."** Tensile
fills every absent knob from `defaultBenchmarkCommonParameters`, so several of
these are already active at a fixed value, and only their *non-default* values are
experiments. The verified default for each is in `knowledge_base.md` §7.1;
`TENSILE_KNOB_DEFAULTS` in `oto/tensile/decks.py` is the machine-readable copy, and
`tests/test_knob_sweep.py` refuses a sweep row that offers no non-default value.
Concretely, per family, with the reason:

| knob | who | why |
|---|---|---|
| `NumLoadsCoalescedA/B` | C, Z | default 1; one phase in the entire corpus sets NLCA. |
| `UseSgprForGRO` | Z | default `-1` (auto). Z is VGPR-bound at TT2x2 (63 VGPR); moving GRO offsets to SGPR buys VGPR. Requires `BufferLoad=1`, which is the default. |
| `PrefetchGlobalRead` | S, C | default 1. The corpus has both `None` and explicit `False`; the experiments are 0 and 2, with 1 as the control. |
| `AggressivePerfMode` | all | default 1. Mode 2 is *described as* a 2-waves/SIMD LDS cap, but the explicit branch is unconfirmed at the pinned commit (corpus3 Q-E ii) — the row tests whether mode 2 differs at all; `gfx90c_theoretical_limits.md` §7 puts the corpus median at 8 waves/CU = 2 waves/SIMD, so a real cap would be a free experiment in that direction. |
| `MaxOccupancy` | all | default 40 (uncapped). Lower values pad per-workgroup LDS to `DeviceLDS // N` (floor) — a pure occupancy clamp. |
| `LocalSplitU` | S, H at small k | default 1. Splits the MTA M extent across waves without a reduction kernel. `validate_config` accepts it for every family, so it is legal for complex on this gate. |
| `FractionalLoad` | S, C at 2048 | default 0; the only knob that changes the load shape for the non-divisible tails. |
| `GlobalSplitU` | S at k≤192, D at small k | default 1. **7-CU wave quantization**: `G = ceil(M/MT)·ceil(N/NT)`; at N=256, MT128 → 4 tiles on 7 CUs = 57% utilisation, MT32 → 64 tiles = 91%. GSU multiplies G, so it is the correct fix for the small-shape rows. |
| `InnerUnroll` | C, Z | default 1; directly reduces the fraction of issue slots spent on loop control. |

`BufferLoad` was on this list and is **not** a deck entry: its default is already
`True`, so sweeping `BufferLoad: True` re-measures the baseline. An explicit `False`
is the only real change and it also kills the `StaggerU` path, which confounds it.
Recorded, not swept.

`GlobalLoadVectorWidthA/B` is **not** a deck entry as an unpaired row (§9 D4):
unpaired, the only values Tensile will build are `1` and `== VectorWidth` (the pv
reduction also cancels a widen on most tiles). A *paired* widen — `GLVW=2` with
`AssertFree0/1ElementMultiple=2` — is legal for CC only, and *is* swept as a
trial (added 2026-10-14). See §8.1.

### Route C — Wave-quantisation ladder (small shapes only)

`GlobalSplitU` × tile-size pairs chosen so `G·S` lands near a multiple of 7.
Enumerate: for each cell, for `MT ∈ {16,32,64}` and `S ∈ {1,…,7}`, keep the pairs
where `G·S mod 7` is 0 or 1. This is a *narrow* route — few candidates, all in
the quantisation-optimal band.

**The arithmetic** (`G = ceil(M/MT) × ceil(N/NT)` tiles on 7 CUs; utilisation =
`G / (7 × ceil(G/7))`):

| problem | MT | G | G mod 7 | aggregate utilisation |
|---|---|---|---|---|
| 128x128 | 16x16 | 64 | 1 | 91.4% |
| 128x128 | 32x32 | 16 | 2 | 76.2% |
| 128x128 | 64x64 | 4 | 4 | 57.1% |
| 128x128 | 128x128 | 1 | 1 | 14.3% |
| 256x256 | 32x32 | 64 | 1 | 91.4% |
| 256x256 | 64x64 | 16 | 2 | 76.2% |
| 256x256 | 128x128 | 4 | 4 | 57.1% |
| 512x512 | 64x64 | 64 | 1 | 91.4% |
| 512x512 | 128x128 | 16 | 2 | 76.2% |
| 1024x1024 | 64x64 | 256 | 4 | 98.8% |
| 1024x1024 | 128x128 | 64 | 1 | 91.4% |
| 2048x2048 | 128x128 | 256 | 4 | 98.8% |

Three things this table settles, and they are counter-intuitive:

1. **MT128x128 at 256³ runs 4 tiles on 7 CUs = 57% of the machine**, while MT32x32
   runs 64 = 91%. The tail is not a rounding error at small N; it is a 34-point
   swing.
2. **The penalty vanishes by N ≥ 1024** (98.8% at MT64x64), so Route C applies to
   the small-shape rows only. Spending the budget on quantisation for 1024³+ is
   wasted.
3. **A bigger tile is *worse* for utilisation at small N but *better* for
   arithmetic intensity** — these pull in opposite directions, which is why the
   small-shape rows (SS k=32 at 24.7% of ceiling, SS k=192 at 30.6%) are hard and
   why `LocalSplitU` is the interesting knob: it fills waves **without** shrinking
   the tile, so it does not pay the arithmetic-intensity cost that MT16x16 does.

Route C is legal **only for SS and DD** (±8.1). For CC/ZZ/HH/HPA the equivalent
fix is `LocalSplitU`, or nothing.

### Route D — LDS-capacity ladder for Z

Z is the only family where the winner already uses ~25 KB LDS and still binds
LDS. Drop `DepthU` 16→8 and 8→4 to free capacity for a second resident
workgroup, and/or `LdsPad` 0 (deprecated, never spent). Z's LDS at the winner is
24960 B — 38% of the CU — so one more workgroup costs the remaining 62%.

### Route E — Split-complex (the "3 real GEMMs" route)

Carried forward from the previous rewrite and still unmeasured. Reported split
GFLOPS = (4/3)·R_real for CC (3 real GEMMs under BLAS-8), ≈1513; and
(4/3)·95–98 ≈ 127–131 for ZZ. This is the only route that can *beat* the
1613/101 BLAS ceiling rather than approach it, because it removes the
complex-MAC instruction penalty entirely. It needs a harness change (a
decomposed call sequence, not a Tensile solution), so it is a separate work
item, not a deck entry. **Unmeasured — treat as hypothesis.**

### Route F — Persistent-kernel / fixed-grid route

gfx90c has 7 CUs. A fixed 7-workgroup grid eliminates tail-wave idle by
construction. Tensile cannot express this (`WorkGroup` sizes the grid, not the
occupancy), so this is a conceptual route for the kernel-writer, not a deck
entry. Listed so it is not re-proposed as a knob.

---

## 7. What to stop doing

Ceasing: **ThreadTile** width ladders for C and Z (F3/F5 — the accumulator cap
makes every wider tile illegal, so they are pure rejects); `LdsPad`/LDS-layout
work (`knowledge_base.md` §1 rate card — bandwidth ~8× oversupplied, and LDS *capacity*
is better spent on residency); any `-mllvm -amdgpu-*` or compiler-flag proposal
(no-op: Tensile emits ISA text to the assembler for ~93% of the shipped
library); `MaxOccupancy`/`AggressivePerfMode` *assumptions* without a
measurement (§F2 — never swept).

Now *starting*: MacroTile ladders for C and Z at the **existing** accumulator
width (F3). That is the opposite direction to a ThreadTile ladder and it is the
one the physics asks for.

---

## 8. The concrete deck additions

Every entry below was checked through `validate_config` (CPU-only) and reported
`Valid`; the rejections found along the way are recorded so they are not
re-proposed. Entries land in `oto/tensile/decks.py` `FAMILY_DECKS`, which is
where the generator reads them.

### 8.1 Legality matrix for the un-varied knobs (measured, 2026-10-14)

Each surviving sweep entry was checked as `the family's current winner tile +
the one knob change`, with the row's `width_override` applied where it has one
(NLCA needs it). Result: **every emitted cell is legal — 69/69 row×family
cells.** The ✗ cells below are knob/family pairs the deck deliberately does not
name, and each is a real, measured refusal.

| knob | CC | ZZ | SS | HH | DD | HH_HPA | HS_HPA |
|---|---|---|---|---|---|---|---|
| `NumLoadsCoalescedA/B=2` | ✓(vw1) | ✗ | ✓(vw1) | ✓(vw2) | ✗ | ✗ | ✗ |
| `UseSgprForGRO` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `PrefetchGlobalRead` 1 / 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `AggressivePerfMode` 1 / 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `MaxOccupancy` 8 / 12 / 20 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `LocalSplitU=2` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `StaggerU` 0/2/4/8/16/32 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `FractionalLoad=1` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `InnerUnroll=2` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `NonTemporalA/B` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GlobalSplitU=2/4` | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ |
| `GLVW=2` + `AF0/1EM=2` (paired) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

Two hard results worth stating plainly:

- **`GlobalSplitU` > 1 is illegal for every half and complex family on this
  repo's gate** — `Assembly class: GlobalSplitU=2 on complex C: illegal`, and
  the same for `half Assembly` and `half with f32 acc`. Only SS and DD may
  split K. This kills the wave-quantisation fix for HH/HPA at every small
  shape, and it means Route C applies to SS and DD only.
- **`NumLoadsCoalesced=2` needs the right width**: legal at CC vw1 (not vw2),
  SS vw1/vw2 (not vw4), HH vw2, and never for ZZ/DD/HPA. The rule is
  `NLCA ≤ NumLoads` where `NumLoads` comes from the width, so the deck entries
  pair the width with the coalesce count rather than assuming both.
- `StaggerU` is legal at *every* value with and without `BufferLoad`, so it is
  free to sweep — and it is currently pinned at 32 corpus-wide (§F2).

Two caveats that are **not** in this matrix:

- **`BufferLoad` is not a deck entry.** Its Tensile default is already `True`
  (`knowledge_base.md` §7.1), so `BufferLoad=True` re-measures the baseline. It
  was removed from `KNOB_SWEEPS` on 2026-10-14.
- **`GlobalLoadVectorWidth` is no longer a deck entry (§9 D4, resolved 2026-10-14).**
  The gate models Tensile's *whole* rule, not just its first half: `GLVW !=
  VectorWidth and != 1` is refused **only when** `not bufferLoad or not
  GuaranteeNoPartialA`, where `GuaranteeNoPartialA` is
  `AssertFree0ElementMultiple % GLVW_A == 0` on a `TLUA` operand
  (`SolutionStructs.py:4584-4596` and `:4177-4183`), and `bufferLoad` is true only
  for a `KernelLanguage: Assembly` kernel. That is the branch the reference-rerun
  hashes `7f866dcf` / `a0edeb30` died on. With the default
  `AssertFree0ElementMultiple=1`, an *unpaired* `GLVW=2` is **refused** for
  CC/SS/HH/HPA and a **no-op** for ZZ (the pv reduction cancels it back to 1) and
  DD (already the derived default) — so the row was removed.
  
  The widen **is** realizable as a *pair*: `AssertFree0ElementMultiple=2` lifts
  `GuaranteeNoPartialA`, and where the pv reduction does not cancel it that is a
  real 8 B → 16 B load. Measured on the gate, that is **CC only** (VW1, pv=1); ZZ
  pv-cancels it, and for SS/HH/HPA (VW4) the pair is a *narrow*, not a widen. The
  paired CC row is swept as a trial (added 2026-10-14, §9 D4). Home:
  `oto/tensile/gates/loads.py` `_glvw_for` + `_Operand._restriction_active`,
  `tests/test_occupancy_gate.py::TestGlobalLoadVectorWidthRule`.

### 8.2 Tiles that are legal but were never generated (the real CC/ZZ headroom)

| family | MacroTile | ThreadTile | VW | why this corner |
|---|---|---|---|---|
| CC | 128x128x8 | 8x4 | 1 | widest legal accumulator (128 VGPR); AI 64 F/B = 167% of ridge; never generated |
| CC | 128x128x8 | 4x8 | 1 | transposed form of the above; never generated |
| CC | 128x96x8 | 8x4 | 1 | between the measured 128x64 and the unmeasured 128x128 |
| ZZ | 128x128x8 | 4x4 | 1 | AI 32 F/B = 13× ridge; never generated |
| ZZ | 128x64x8 | 4x4 | 1 | asymmetric, never generated |
| ZZ | 64x64x16 | 4x4 | 1 | longer unroll at the same width; never generated |
| DD | 128x128x8 | 8x8 | 1 | DD TT8x8 is legal (unlike CC); AI far past its 2.4 F/B ridge |
| DD | 64x128x16 | 4x8 | 1 | legal and never generated |

`StaggerU` 32 is the current constant; the sweep adds 0/8/16 to test whether the
7-CU geometry wants a different raster.

### 8.3 Route E and Route F are not deck entries

Route E (split-complex, 3 real GEMMs) and Route F (persistent fixed grid)
cannot be expressed as Tensile solution knobs — E needs a decomposed call
sequence in the harness, F needs a kernel-writer change. They are recorded in
§6 so they are not re-proposed as knobs, and are tracked as separate work items
(`incomplete_work.md`), not as deck rows.

---

## Sources

All numbers in §1–§8 are reproduced by repo tooling, which is the citation:
`allruns.py` (knob census, tile triples), `oto.harness.asm_occupancy` (5757-kernel
measured occupancy + GFLOP/s join), `oto.harness.resolve_cells` (per-cell
winners), `oto.harness.occupancy_audit` (predicted residency), `validate_config`
(§8.1's legality matrix), and `gfx90c_results/acceptance_report.json` run
`run_20261013_214649`.
Architecture/ridge facts: `knowledge_base.md`, `gfx90c_theoretical_limits.md`.
Anti-transfer: arXiv:2505.03780, arXiv:2507.15277 (`kernel_tuning_research.md` §6).

---

## 9. Open decisions (user-owned; do not act on these silently)

**D1 — CC:256's LOSS is a measurement artifact (§F1).** The floor arm carries no
telemetry (`spoof_clock_coverage = 0.0`), so `clock_adjusted = False` on every
cell and no correction is possible. The native arm ran at 1175 MHz against an
1800 MHz reference. Resolving this requires a floor-arm telemetry re-run, which
is a TTY job. Do not close it by widening a band; the verdict logic is not ours
to change.

**D2 — `BYTES_PER_ELEMENT["Z"]` vs `LDS_BUDGET`** (full record and measurement in
`gfx90c_theoretical_limits.md` §6.1). Tensile's complexDouble is `'reg': 4` so
`numBytes() = 16`, and the same module already has `FAMILY_BYTES_PER_ELEMENT
["ZZ"] = 16` — three tables in one file say 16, one says 8, and ZZ is the only
family where the gate's byte count is half of Tensile's element width.

The 8 is **not** an over-admission: measured, 0 of 229 ZZ kernels that built and
ran exceed the 16384 budget at that reading, so the gate never wrongly let a ZZ
config through. What it does is understate ZZ's real LDS pressure by 2× on the
base footprint (the gate says 16384 where Tensile allocates 65536 for a 64x64x16
tile). Correcting the bytes alone refuses **67 of those 229** kernels, so the
baseline `"Z": 16` with budget 32768 must be decided as a pair.

**D3 — should the ZZ deck's 24.9 KB LDS winners be re-checked against the
`LDS_BUDGET` gate after D2?** If D2 lands, ZZ's own winners (24960 B base,
65536 B emitted) move above the budget. The deck generator refuses candidates the
append boundary judges illegal, so this can silently empty the ZZ deck. Resolve
with D2.

**D4 — the sweep deck's baseline and the paired widen (resolved 2026-10-14; D1–D3
trial tiles added the same day).**

*Baseline: explicit control, opt-in.* `generate_knob_sweep_phases` gains
`include_baseline`, and `knob_sweep` gains `--baseline`: the base tile is emitted
unchanged once per (family, pattern, shape), tagged `_base`, so every knob delta
has a same-run control. Default off (the implicit default-as-control rows
`PrefetchGlobalRead=1` / `AggressivePerfMode=1` still exist); the run book (§10)
passes `--baseline`.

*Paired CC widen: added as a trial row.* `GLVW=2` **with**
`AssertFree0/1ElementMultiple=2` is a real 8 B → 16 B load and is legal for CC only
(VW1, pv=1); ZZ pv-cancels it and for SS/HH/HPA it is a narrow. CC is the worst
family (31% of its ceiling) and issue-bound. It is a `KNOB_SWEEPS` row
(`GlobalLoadVectorWidth`, CC-only) — not a clean one-knob change
(`AssertFree0ElementMultiple=2` asserts `M % 2 == 0` and reaches other Tensile
paths), so it is labelled a trial and the run judges it. §8.1 matrix +1 (69/69).

*D1–D3 trials: `DECISION_TRIAL_TILES` + `--trials`.* Three decisions are not knob
changes, so they own tiles instead of rows (emitted unchanged, tagged
`_trialD<n>`; `generate_decision_trial_phases`):
- **D1** — CC `64x64x8/4x4/VW2` (the steal geometry) at `192`/`256`, the shallow
  cells the LOSS cell owns. The candidate re-measures; the floor-arm telemetry
  re-run (TTY) closes it.
- **D2** — ZZ `32x32x16/2x2/VW2` (the differentiator: legal at the 8-byte reading,
  refused at 16) and ZZ `64x64x16/4x4/VW1` (the LDS-boundary tile). If VW2 builds
  and runs, the 8-byte reading is behaviourally sound.
- **D3** — ZZ `128x128x8/4x4` and `128x64x8/4x4` (§8.2, never generated): the deck
  stays non-empty under either D2 reading.

No gate or verdict logic changed for any of this; the trials are *candidates*,
and the run decides. Dry-run: 246 sweep + 14 baselines + 10 trials = 270, 0 refusals.

*Resolved earlier (2026-10-14):* `GLVW=2` is not merely "maybe refused" — the gate now
models Tensile's shift-ptr rule in full, including the `GuaranteeNoPartialA`
escape hatch, so an *unpaired* `GLVW=2` is refused for CC/SS/HH/HPA and a no-op for
ZZ/DD. The unpaired row was removed. See §8.1 and
`oto/tensile/gates/loads.py::_glvw_for`.

---

## 10. GUI-safe prep for the 10h+ overnight run

Constraints: full Tensile benchmark runs are TTY-only and the user's to
launch. Agent work is CPU-only — deck generation, dry-run, gate checks.

1. **Deck** — `oto/tensile/decks.py` `FAMILY_DECKS` gains the §8.2 tiles and the
   §8.1 knob sweeps. Every entry is gated by `validate_config` at the append
   boundary, so an illegal row costs a rejection, never a crashed run.
   Emit with trials and controls:
   `python3 -m oto.tensile.knob_sweep --emit --baseline --trials`
   (dry-run default; 246 sweep + 14 baselines + 10 trials = 270, 0 refusals).
2. **Dry-run** — `python3 -m oto.tensile.candidate --dry-run` (or
   `check_candidates.py --deck <deck>.yaml`) to confirm the phase count and that
   no entry is silently dropped.
3. **Legality PoC only** — verify the new ZZ deck is non-empty after D2 lands
   (§9, D3). This is the one interaction that can empty a family.
4. **Clock hygiene** — pin the sclk level via sysfs
   (`power_dpm_force_performance_level` = `manual`, then `pp_dpm_sclk`), 25%
   warmup, L2 flush between repeats for memory-bound shapes, log median clock +
   temperature per phase, and interleave a reference kernel to detect drift.
   Full protocol: `knowledge_base.md` §8.3. Without this the run repeats the F1
   artifact.
5. **Budget split** — the never-varied knobs (§8.1) are the high-yield spend;
   tile ladders (§8.2) are the second; Route E is a separate work item and gets
   no time here.
6. **Post-run read guide (corpus3 Q-E iii).** PGR 0/1/2 is measured on the
   complex winners in this run — read the winner through LDS bytes, VGPRs and
   load/wait counts, not the mode number: **0 wins** = buffering costs exceed
   overlap (consistent with issue-bound); **1 wins** = one stage suffices;
   **2 wins** = look-ahead matters on that shape (not a universal PGR=2 rule).
   APM 1-vs-2 is read through the LDS allocation diff first (cap unconfirmed).

The pass-3 brief (Q-A…Q-F) is folded; residual follow-ups are §9.4 of
`kernel_tuning_research.md` and the protocol deltas are `knowledge_base.md`
§8.3. The prompts themselves are archived at `archive/RESEARCH_PROMPT*.md`.
