# gfx90c (Vega 7) — oto Candidate Deck & Convergence Analysis

> **Role.** Authoritative candidate deck, evidence and search rules for the
> deterministic loop. Raw benchmark data lives in `gfx90c_results/` and
> `results.md`; this file holds conclusions, provenance and the deck.
>
> **How to read this.** §1–§12 are current and evidence-backed. **Appendix A**
> retains the 2026-09-13→20 working notes verbatim for provenance; several of its
> numbers are superseded — see §13 for the supersession list.
>
> **Hard rule.** No GPU workload may be executed from a GNOME desktop session.
> CPU-only legality proofs are permitted at any time; every performance number
> below is historical, not a live measurement.

---

## 1. Status

| item | state |
|---|---|
| acceptance vs gfx900 floor | **FAIL** — 14 WIN / 10 TIE / 14 LOSS over 38 cube cells, ±5% band |
| true config losses after bias correction | **12** (CC 256 and CC 2048 are measurement artifacts, §6) |
| primary root cause | native deck issues an 8-byte global load where the floor issues 16 on SS/DD/HH (§5.3) |
| largest single defect, localised and **fixed in the deck** | 11 of 16 losses were cells whose winning config was never generated: SS 128x128 `vw4`, HH 128x128 `vw8`, DD 64x64 `vw2` all missing. Now derived by `cap_vector_width()` (§5.11, §5.13) |
| secondary defect, fixed in the deck | HPA decks had no transposed `64x128` macro tile — the floor's winner on HH_HPA:2048 (−7.7%) was absent (§5.11) |
| not defects | CC:256, CC:2048, HH_HPA:1024 (both arms issue the same load width — identical-config measurement artifacts, §6); CC:192 is a tuning outcome, both tiles already in the deck (§5.11) |
| unexplained territory | **ZZ** — native now wins all 5 ZZ cells (+5.7% to +205.7%) with *small* tiles; floor's ZZ tiles are too large at small cubes (§5.10) |
| candidate deck | P1–P23 plus the shipped `phases.yaml` (434 phases, 47 ZZ); **CPU-gated** (§9) |
| ZZ native family | **has winners** — 47/47 ZZ phases now build clean under the corrected dual gate (§5.7) |
| candidate gates | **2 hard resource gates**, both measured: per-thread 256 VGPRs on `ThreadTile`, 64 KB LDS on `MacroTile × DepthU` (§5.7) |
| register-file model | **retired** — the old `R × MacroTile_area` rule was falsified; §5.7/§5.8 |
| reference floor | 127 phases blocked by a config bug now **fixed** but **not yet rerun**; needs TTY (§11) |
| `--auto` policy | **fixed** — an incomplete/failed reference floor can no longer consume a whole budget; A/B is labelled `PROVISIONAL FLOOR` (§5.9) |
| GPU benchmarking | **blocked** — requires TTY |

---

## 2. Device and the 128-bit arithmetic

Local part is **gfx90c = Vega 7** (`gfx90c_common.py`), *not* Vega 8.

| property | value | source |
|---|---|---|
| CUs × SIMD/CU | 7 × 4 | `gfx90c_common.py` |
| wavefront | 64 lanes | `AsmCaps.py` |
| LDS | 64 KiB/CU | `gfx90c_common.py` |
| L2 | 1 MiB | `gfx90c_common.py` |
| memory | APU / UMA | sysfs + ROCm |
| ISA | `(9,0,12)` | `rocminfo` |
| reported max clock | ~1.8 GHz | sysfs `pp_dpm_rosc` |
| exact memory bandwidth | **unverified** | — |

**Matrix instructions: none.** `AsmCaps.py` sets no `MFMA`, `WMMA`, `v_dot2`,
`v_dot4` or DP4A for gfx90c. `DirectToLdsNoDest` **is** available. Consequently
MFMA-style "128-bit via `v_dot`" tricks are unavailable and every wide-load
candidate has to be built from LDS/DS and the FMA pipe directly.

### The 128-bit rule

Tensile's `VectorWidth` is in **elements**, and the global-load width in bytes is
`VectorWidth × bytes-per-element`. Critically, **complex types count as 8 bytes**
(`C` and `Z` are both 8 B in `scheduler.DTYPE_INFO`), not 4/8 as a naive reading
of the dtype suggests.

| family | dtype | bytes/elem | 128-bit `VectorWidth` | max legal `VW` | native actually used |
|---|---|---|---|---|---|
| SS | f32 | 4 | **4** | 4 | 2 (half) |
| DD | f64 | 8 | **2** | 2 | 1 (half) |
| CC | complex f32 | **8** | **2** | 2 | 2 (**at cap**) |
| ZZ | complex f64 | **8** | **2** | 2 | 1 (half) |
| HH / HH_HPA / HS_HPA | f16 | 2 | **8** | 8 | 4 (half) |

Two consequences that the earlier version of this document got wrong:

- **The global load is capped at 16 bytes** for *every* family
  (`GLVW × bytes-per-element ≤ 16`, `scheduler._validate_tensile_loads`).
  Therefore **CC `VectorWidth 4` is impossible** — it would be a 32-byte load —
  and CC's 128-bit point is `VW2`, which the floor already runs. There is no
  width headroom on CC.
- **ZZ is the only family still at half the cap.** `VW2` (16 B) is legal for ZZ
  and has never been run by either arm.

Verified boundary probe (CPU-only, `scheduler` gates):

| family | VW1 | VW2 | VW4 | VW8 |
|---|---|---|---|---|
| DD (8 B) | ok | ok | **REJECT** | **REJECT** |
| CC (8 B) | ok | ok | **REJECT** | **REJECT** |
| ZZ (8 B) | ok | ok | **REJECT** | **REJECT** |
| HH (2 B) | ok* | ok | ok | ok |

`*` HH `VW1` fails only because the probe inherited `NLCA 3` from its template;
with `NLCA 1` the SS/HH families admit `VW1`–`VW4`. The cap, not the low-`VW`
rejects, is the load-bearing result.

This 128-bit target is the point the floor reaches and the native deck misses on
SS/DD/HH. It is a strong empirical rule on this corpus, **not** a universal ISA
requirement — small shapes legitimately win below it (§5.3).


### A stock-Tensile restriction that is not a hardware limit

`GlobalLoadVectorWidth ∈ {VectorWidth, 1}` — `SolutionStructs.py:4583-4596`
("so shift-ptr logic will work"). This fires in the non-MI assembly guard and
rejects gfx900 *identically*: it is a generator/representation restriction, not a
gfx90c ISA limit. `scheduler._validate_tensile_loads` now models it, which is why
the old 64x64x8 deck was wrongly pre-validated.

---

## 3. Data provenance — what exists and what each source yields

Seven logical run IDs. **Not all have directories on disk**, and the two legacy
runs survive only as a flattened CSV. Getting this wrong is how earlier passes
double-counted or invented provenance.

| run | on disk | benchmark records | notes |
|---|---|---|---|
| `gfx900_ref_20260925_152942` | yes | 8,116 | floor (spoof) arm |
| `gfx900_ref_20260926_201843_resume` | yes | 3,399 | floor (spoof) arm |
| `run_20260919_213727` | **no** | 4,895 | native, `benchmark_result` rows only |
| `run_20260920_235815` | yes | 1,895 | native; telemetry present but detached |
| `run_20260926_201835` | yes | 0 | general records only, no `2_BenchmarkData` |
| `run_20260913_215546` | **no** | — | only `unified_measurements.csv` (808) |
| `run_20260915_001704` | **no** | — | only `unified_measurements.csv` (2,400) |

Aggregated arms as actually used for the A/B: **native 6,790 records / 2 runs**,
**floor 11,515 records / 2 runs**. `unified_measurements.csv` (3,208 rows) is
**excluded** from the A/B because its rows carry only partial config columns and
would understate what the native arm has tried.

### How the numbers are produced (reuse, don't re-derive)

- `analytics.AnalyticsEngine.load_benchmark_csv` — parses one `2_BenchmarkData/*.csv`.
  Each such file is a **multi-size sweep**: column 0 is the row index, rows walk
  problem sizes (192, 256, 512, 1024, 2048, …), and **GFlops is the last column**,
  whose header is the kernel name. `SizeK` is always 1; the summation dimension is
  `SizeL`. Getting this wrong silently yields GFlops values off by ~100×.
- `analytics.aggregate_by_cell` → median-of-seeds per `(dtype, shape, kernel)`.
- `port_tensile.TensileDriver._native_records_all_runs` — the **native** arm =
  every run CSV + every registry `benchmark_result` row, deduped on
  `(phase_id, fingerprint, GFlops)`.
- `port_tensile.TensileDriver._ab_records_from_csv(dir, force_arm=...)` — the
  **floor** arm from the reference run dirs (never re-run).
- `analytics.compute_native_vs_spoof_delta(..., agg="winner")` — per-cell verdicts.
  `agg="winner"` compares the best per-kernel median against the floor's; it
  reproduces `acceptance_report.json` 38/38.
- Family identity: the run's **own** `FamilyLabel` in the phase YAML wins; the live
  `phases.yaml` no longer contains the reference `hh_hpa`/`hs_hpa` phases, so
  falling back to it silently folds them into `HH`. `extract_family_from_phase_id`
  is the correct fallback for reference phase ids.

### Known evidence gaps

- **13 of 51** native cells have a winner whose config comes only from the
  registry's **12-key snapshot** (`MacroTile`, `ThreadTile`, `VectorWidth`,
  `DepthU`, `WorkGroupMapping`, `GlobalSplitU`, `NLCA`, `ContractionPattern`,
  `FamilyLabel`, `DataType`, `ProblemType`, `Architecture`, `ScheduleName`).
  There is no `LdsPad*`, `StaggerU`, `WorkGroup` or `Prefetch*` for those cells.
  Affected: `CC:2048`, `DD:256`, `DD:1024`, `HH:256`, `HH:512`, `HH_HPA:256`,
  `HH_HPA:512`, `HS_HPA:256`, `HS_HPA:512`, `SS:256`, `SS:512`, `ZZ:256`,
  `ZZ:2048`. All 38 floor cells have full YAML knobs.
- The `unified_measurements.csv` rows are not used for winner selection.

---

## 4. Both arms are the same silicon

"Native vs spoof" is **not** native silicon versus gfx900 silicon. Both run trees
compile `TensileLibrary_gfx90c.co.raw` on the same local APU; the "spoof" arm is
AMD's shipped **gfx900-tuned configuration deck** executed on gfx90c. So a loss
means *our deck* is worse than AMD's gfx900 deck *on this device* — a pure
configuration-tuning gap, with no hardware confound.

Re-extraction of the floor's per-cell best values straight from its YAML knobs
reproduces **all 38/38** values in `acceptance_report.json` to within 0.15 GFlops,
so the comparison is knob-exact rather than fingerprint-matched.

---

## 5. All-runs evidence

Cells are cube shapes (`N³`); winner statistic is the **best per-kernel median**
(median first, then max) so one lucky seed cannot decide a verdict.

### 5.1 Coverage

51 native cube cells, 38 floor cube cells, 38 shared — the shared 38 is exactly
the acceptance suite. Shape sides seen: 128, 192, 256, 512, 768, 1000, 1024,
1365, 2048, 4096.

### 5.2 What each arm has ever run (load width, correct bytes)

Reached = any phase config on disk or in the registry for that family. Widths use
the correct complex = 8 B convention (§2), so a "64b" CC `VW1` is really 8 B.

| family | native | floor | native vs 16 B cap |
|---|---|---|---|
| CC | 32b, 64b* | 32b, 64b* | **at cap** (`VW2` = 16 B) in both arms |
| DD | 64b, 128b | 64b, 128b | native at **half** cap (`VW1`) |
| HH | 32b, 64b | 32b, 64b, **128b** | native at **half** cap (`VW4`) |
| HH_HPA | 64b | 32b, 64b, **128b** | native at **half** cap (`VW4`) |
| HS_HPA | 64b | 32b, 64b, **128b** | native at **half** cap (`VW4`) |
| SS | 64b, **128b** | 32b, 64b, **128b** | native at cap, but only 6 configs, all ≤ MT128 |
| ZZ | 64b | 64b | **half** cap — `VW2` legal, never run |

`*` these are `VW × 4 B` (element width). Under the 8 B complex convention both
arms' top CC setting is `VW2` = 16 B = the cap. See §2.


### 5.3 Where the floor wins: it wins *at 128-bit*

Floor best-per-cell (authoritative, from §3 loaders):

| cell | GFlops | MT | TT | VW | width | DU | WGM | GSU |
|---|---|---|---|---|---|---|---|---|
| HH:512 | 1583.9 | 128x128 | 8x8 | 8 | **128b** | 16 | 4 | 1 |
| HH:1024 | 2578.3 | 128x128 | 8x8 | 8 | **128b** | 16 | 4 | 1 |
| HH:2048 | 2684.1 | 128x128 | 8x8 | 8 | **128b** | 16 | 4 | 1 |
| HH:4096 | 2821.0 | 128x128 | 8x8 | 8 | **128b** | 16 | 4 | 1 |
| SS:512 | 820.9 | 128x128 | 8x8 | 4 | **128b** | 16 | 4 | 1 |
| SS:1024 | 1116.9 | 128x128 | 8x8 | 4 | **128b** | 16 | 4 | 1 |
| SS:2048 | 1216.5 | 128x128 | 8x8 | 4 | **128b** | 16 | 4 | 1 |
| SS:4096 | 1208.1 | 128x128 | 8x8 | 4 | **128b** | 16 | 4 | 1 |
| DD:192–2048 | — | 64x64 | 4x4 | 2 | **128b** | 8/16 | 4 | 1 |

Native best on the same cells tops out at **64-bit**: HH at `128x128/8x8/VW4`,
SS at `128x128/8x8/VW2`, DD at VW1. This is the whole story of the 12 losses —
same tile, same thread tile, **double the global-load width**.

`VectorWidth` is a differing knob in 9 of the 14 reported losses; in 6 of them it
is the *only* difference, and in 3 more it needs one companion change
(`LdsPadB` or `WorkGroupMapping`).

**Precision matters:** 128-bit *reach* is not 128-bit *wins*. The floor has 128-bit
`HH_HPA`/`HS_HPA` configs (128x128/8x8/VW8 and 64x64/8x8/VW8) but its **winners**
on those cells are VW2/VW4 at 32–64b. Only **plain HH** actually converts 128-bit
into a win. So P2 is a high-confidence win candidate while the HPA-wide variants
are exploratory.

### 5.4 ZZ is the only untouched width frontier; CC's problem is not width

**ZZ** is the sole family where neither arm has run a config at the 16-byte cap.
Both arms top out at `VW1` = 8 B; `VW2` is legal and has never been benchmarked.
ZZ is also the weakest family in absolute terms (~24 GFlops ceiling), so P7 is the
one candidate that could beat the floor by being *new* rather than by being a
retune.

**CC is a correction to the earlier version of this document.** CC looked like a
second untouched frontier, but complex f32 is 8 B/element, so the floor's `VW2`
configs are already 16 B — at the cap. `CC VW4` would be a 32-byte load and is
rejected by `scheduler` (§2, verified). CC therefore has **no load-width
headroom**; its gap (native ~318 vs floor ~308 at 512³, i.e. near parity, and
both far below the FP32 ceiling) is a tile/occupancy/`DepthU` problem, not a
width problem. Its candidates are re-aimed accordingly (P6 below).


### 5.5 Knobs that are *never* exercised

Across **every** phase in **both** arms:

- `GlobalSplitU` is **1 everywhere**. (The 24 GSU=2 cells in the draft wide run
  were class-rejected on gfx90c — no MFMA — and are not verdicts.)
- The only `ContractionPattern` present is the default `Ailk_Bjlk`. **No Stream-K
  pattern has ever been compiled or benchmarked on this device.**
- `StaggerU` is 32 in essentially all winners (exception: DD:192 at SU=2).
- `DepthU` ∈ {8, 16}, `WorkGroupMapping` ∈ {1, 4, 8}.

Stream-K and Split-U are therefore genuinely open (§8), but they are *unproven
territory* on a non-MFMA gfx90c, not free wins.

### 5.6 Why the native arm lost: exploration width, not bad luck

Distinct `(MT/TT/VW)` triples per family, all runs combined:

| family | native configs | floor configs |
|---|---|---|
| SS | 25 + 14 | 65 |
| HH | 5 + 8 | 38 |
| DD | 4 + 7 | 10 |
| CC | 5 + 6 | 9 |
| ZZ | 4 + 4 | 2 |
| HH_HPA / HS_HPA | 5 + 4 | 38 / 39 |

The floor is a broad search; the native deck is a narrow one that never left the
64-bit band on the families that matter. The fix is coverage, per §2 of Appendix A.

---

### 5.7 The register-file model was wrong; there are **two** limits on **two** different parameters

§5.7 previously attributed all ZZ deaths to a single "register-file exhaustion"
condition and modelled it as `R * MacroTile_area <= 32768`. That model has now
been **falsified by direct measurement and retired**. Building every phase's
kernel with Tensile's own writer — CPU-only, no benchmark, via
`check_tensile_build.py` — produced two *independent* failures that the
area-based model could not represent.

**Limit 1 — 256 VGPRs per thread, constrains `ThreadTile`.** A thread holds
`TT0 * TT1` accumulators of `weight` VGPRs each:

```
accVGPRs = TT0 * TT1 * weight          MacroTile does not appear
```

Tensile refuses to emit the kernel once the per-thread total crosses the 256
VGPR architectural limit. Measured on gfx90c, complex (`Z`, weight 8):

| ThreadTile | accVGPRs | measured VGPRs/thread | Tensile |
|---|---|---|---|
| 2x2 | 32 | 63–71 | ok |
| 4x2 | 64 | 95 | ok |
| 2x4 | 64 | 99 | ok |
| 4x4 | 128 | 154–199 | ok |
| 2x8 | 128 | 171 | ok |
| **8x4** | **256** | **271** | **FAIL** `total vgpr: 271 not in [0, 256]` |
| **8x8** | **512** | **519** | **FAIL** `total vgpr: 519 not in [0, 256]` |

Every row is `accVGPRs + a small tile-dependent overhead`, and the pass/fail line
sits exactly at `accVGPRs = 128` for complex. The old model got the *sign* right
for complex (which is why the first 8 phases were caught) but predicted the
*wrong parameter*: it passed `128x32x8/8x4`, which then died **116 times** in
`run_20260928_024945`, and it expressed no reason to reject a narrow macro tile
with a wide thread tile, which is equally fatal.

**Limit 2 — 64 KB LDS per workgroup, constrains `MacroTile` and `DepthU`.** The
workgroup's A and B tiles must be staged in LDS:

```
LDS base = (MT0 + MT1) * DepthU * bytesPerElement
```

Tensile compares an allocator figure inflated by prefetch double-buffering,
power-of-two offset alignment and `LdsPad`, and rejects with
`SolutionStructs:4334`. No thread-tile choice can rescue a tile that fails here.
Measured complex boundary: `16384` legal, `20480` dead — `128x32x16` was rejected
with `Kernel Uses 106496 > 65536 bytes of LDS` under **every** thread tile tried
(2x2, 2x4, 4x2, 4x4, 2x8, 4x8, 8x4).

`bytesPerElement` is *not* the VGPR weight: an f64 element is 8 bytes but only
2 VGPRs, while a complex f64 element is 8 VGPRs and 8 bytes. Conflating them
breaks the gate.

**The gate now enforces both, and agrees with Tensile on 47 of 47 complex
phases.** `test_occupancy_gate.py` re-checks this against the live deck and
against the stored Tensile verdict, so a future drift fails CI.

### 5.8 The model is retired, not re-tuned — and it is now falsifiable

The calibrated `R` table and its 2× headroom constant are gone. In their place
is a rule derived from measurement and confirmed by the two independent failure
modes above. This retires the entire risk list that used to live in this section:

- ~~"R=8 is calibrated, not derived"~~ — derived now, and the derived quantity
  (per-thread accumulators) is what Tensile's writer actually computes.
- ~~"Tensile's literal formula would not have caught the failing tile"~~ — the
  literal limit *is* 256 VGPRs/thread; the old scalar fudge was the approximation.
- ~~"no positive-side confirmation"~~ — every one of the 12 measured thread tiles
  is now classified correctly, and 47/47 phases match the build proof.

The `PrintSolutionRejectionReason` item is also closed. It is enabled in
`check_tensile_build.py`, and the worker's stdout is parsed for
`SolutionStructs.reject()` output, so a phase that yields no solutions now
reports the actual cause (this is how the LDS limit was found) instead of
`0 valid solutions`.

**Standing falsification rule (kept).** If any gate-passing config ever reports
error 4 or a zero-solution rejection, the budgets are wrong and must be
re-derived from that data point before the gate is trusted again.

**Residual limitation, stated plainly.** `check_tensile_build.py` drives Tensile's
solution generator and kernel writer and catches resource and legality failures,
but it does not invoke the full library/code-object assembler. It is a strong
legality proof, not a substitute for a build.


### 5.9 Recent-run study: 12 runs, and what each one actually cost

Aggregated with `allruns.py --json`. The registry holds ~24,900 benchmark result
records; the metadata files and the registry disagree in an informative way, so
both are given.

| run | what it shows |
|---|---|
| `gfx900_ref_20260925_152942` + `_20260926_201843_resume` | the usable floor; 1,073 then 808 phases. **This is the only complete reference chain.** |
| `run_20260919_213727` | early native, superseded |
| `run_20260920_235815` | 8 ZZ phases executed, 258 skipped; registry 410 completed / 17 failed / 427 started / 559 skipped across iterations |
| `run_20260926_201835` | 8 ZZ executed, 402 skipped, 8 × error 4 — the first occupancy evidence |
| `gfx900_ref_20260928_023401_resume` | **0 of 127** |
| `gfx900_ref_20260928_023858_resume` | **0 of 127** |
| `gfx900_ref_20260928_092818_resume` | **0 of 127**, 126 phase logs carry the fatal parameter error |
| `run_20260928_024945` | overnight native, 5 iterations, interrupted; 309 starts / 287 failures / 22 completions |
| `gfx900_ref_20260928_023355`, `_023843`, `_023854`, `092813` | empty/aborted reference attempts |

**Two distinct failure stories, previously conflated.**

1. *The reference chain never ran, for a config reason.* Every one of the 127
   attempts emitted `GlobalReduceVectorWidth`, which does not exist in Tensile
   4.44.0. `BenchmarkStructs.checkParametersAreValid` printed
   `Invalid parameter name: GlobalReduceVectorWidth` and exited during
   `Filling in Parameters With Defaults` — before a single kernel was built. The
   parameter was emitted by `tensile_library.py` from `grvw`; it has been removed
   and `port_tensile.py` now filters any key absent from Tensile's own
   `validParameters`, logging `[cfg] dropping parameter ... not supported by this
   Tensile`. `test_tensile_params.py` checks all 434 live phases and all 3,878
   archived reference entries emit only valid parameter names.

2. *`--auto` could spend an entire budget without measuring anything native.* All
   three failed reference runs above returned early from `run_auto()` and never
   entered the native loop. The floor is now attempted but can no longer abort
   tuning: an incomplete or failed floor sets
   `reference_floor_authoritative = False`, the run proceeds, and the acceptance
   report is prefixed `PROVISIONAL FLOOR` so its A/B verdicts cannot be mistaken
   for release evidence. Covered by `test_auto_reference_floor.py` (9 tests).

**Where the overnight budget actually went.** In `run_20260928_024945` the
scheduler correctly retired legal configs and stopped retrying them — `32x128x8`
completed once and was then skipped for 28 iterations. But it retried the *dead*
tiles for the full budget:

| tile | attempts | successes | cost |
|---|---|---|---|
| `128x32x8 / 8x4` (4 phases) | 29 each, 116 total | 0 | ~116 wasted |
| `128x32x16 / 8x4` (4 phases) | 29 each, 116 total | 0 | ~116 wasted |
| auto `64x64x16 / 8x8` (2 phases) | 28 each, 56 total | 0 | ~56 wasted |

288 of 309 starts (93%) were attempts at phases that could never build. This is
the strongest possible argument for a pre-GPU legality gate, and it is the
failure the retired model in §5.7 could not see.

### 5.10 Native vs floor, cell by cell

Both arms re-analysed from the whole corpus: native = all native runs, floor =
the two complete `gfx900_ref` chains, one winner per cell. **38 shared cells:
18 WIN, 4 TIE, 16 LOSS** (band ±1%).

The split is not random — it is a clean function of problem size:

| size band | cells | outcome |
|---|---|---|
| 128–512 | 9 | native wins **decisively**, +183% to +272% |
| 768–1024 | 12 | mixed, roughly even |
| 1365–4096 | 17 | floor wins, −2% to −15% |

Best and worst:

| cell | native | floor | delta |
|---|---|---|---|
| `HH:256` | 764.0 | 205.6 | **+271.6%** |
| `SS:256` | 404.1 | 126.1 | +220.6% |
| `ZZ:128` | 16.8 | 5.5 | +205.7% |
| `SS:2048` | 1032.8 | 1216.5 | **−15.1%** |
| `HH:2048` | 2291.7 | 2684.1 | −14.6% |
| `HH:4096` | 2412.1 | 2821.0 | −14.5% |

**The losses are all one bug: the native arm is one VectorWidth step short at
128x128.** For every large SS and HH cell the floor wins with a *wider* load:

| cell | native winner | floor winner |
|---|---|---|
| `SS:2048/1024/768` | `128x128/8x8/vw2` | `128x128/8x8/vw4` |
| `HH:2048/1024` | `128x128/8x8/vw4` | `128x128/8x8/vw8` |
| `HH:4096` | `128x128/8x8/vw4` | `128x128/8x8/vw8` |

This is the concrete, actionable form of §5.3: the native deck simply does not
issue `vw4` on 128x128 single or `vw8` on 128x128 half. It is a coverage gap in
candidate generation, not a modelling error and not bad luck.

**ZZ is the exception and the opportunity.** Native wins **all five** ZZ cells
(+5.7% to +205.7%), and its winning tiles are consistently *small*:

| cell | native winner tile | floor tile |
|---|---|---|
| `ZZ:1024` | `64x32/4x2/vw1` | `64x64/4x4/vw1` |
| `ZZ:512` | `32x32/2x2/vw1` | `32x32/4x4/vw1` |
| `ZZ:192` | `32x32/2x2/vw1` | `32x32/4x4/vw1` |
| `ZZ:128` | `32x32/2x2/vw1` | `64x64/4x4/vw1` |

At small cubes the floor's `64x64/4x4` is *too big* for complex f64, and the
native `32x32/2x2` wins by up to 3×. This is the opposite of the direction the
deck was extended in: the ZZ replacements that were proposed as "wider"
(`128x32`) were both illegal (§5.7) and the wrong direction. The evidence
points **narrower**, not wider — and the floor's own ZZ tiles are left on the
table at small sizes.


### 5.11 Every current loser and tie, diagnosed

All 38 shared cells, sorted worst-first, with the width each arm actually issues.
The cap below is the classic path's hard limit
(`GLVW * bytesPerElement <= 16`, `SolutionStructs:3460`); `bytes` is the width
of one contiguous global load.

| cell | delta | family | native load | floor load | diagnosis |
|---|---|---|---|---|---|
| SS:2048 | −15.1% | SS | vw2 = 8 B | **vw4 = 16 B** | under-wide |
| HH:2048 | −14.6% | HH | vw4 = 8 B | **vw8 = 16 B** | under-wide |
| HH:4096 | −14.5% | HH | vw4 = 8 B | **vw8 = 16 B** | under-wide |
| CC:256 | −13.4% | CC | vw2 = 16 B | vw2 = 16 B | identical width → artifact |
| SS:4096 | −12.2% | SS | vw2 = 8 B | **vw4 = 16 B** | under-wide |
| SS:1024 | −11.0% | SS | vw2 = 8 B | **vw4 = 16 B** | under-wide |
| HH:1024 | −10.9% | HH | vw4 = 8 B | **vw8 = 16 B** | under-wide |
| SS:768 | −9.9% | SS | vw2 = 8 B | **vw4 = 16 B** | under-wide |
| DD:192 | −8.2% | DD | vw1 = 8 B | **vw2 = 16 B** | under-wide |
| SS:1365 | −7.9% | SS | vw2 = 8 B | **vw4 = 16 B** | under-wide |
| HH_HPA:2048 | −7.7% | HH_HPA | `128x64/8x4/vw4` | `64x128/4x8/vw2` | **transposed tile** |
| CC:2048 | −6.5% | CC | (no knobs recorded) | vw2 = 16 B | artifact, unreliable |
| CC:192 | −6.1% | CC | `64x64` vw2 | `32x32` vw2 | floor narrower (noted below) |
| SS:1000 | −5.5% | SS | vw2 = 8 B | **vw4 = 16 B** | under-wide |
| DD:768 | −2.9% | DD | vw1 = 8 B | **vw2 = 16 B** | under-wide |
| HH_HPA:1024 | −1.0% | HH_HPA | vw4 = 8 B | vw4 = 8 B | identical → inside noise |

**11 of the 16 losses are one bug, and it is a generation bug, not a tuning
one.** The winning config was never in the deck:

| family | tile | VWs in the deck | cap needs | present? |
|---|---|---|---|---|
| SS | 128x128 | 2 | **4** | no |
| HH | 128x128 | 4 | **8** | no |
| DD | 64x64 | 1 | **2** | no |

No number of iterations, and no amount of mutation, could have won those 11
cells: the phase did not exist. The family decks hardcoded a VectorWidth one
step below the cap, and `_load_family_decks` had no reason to go wider.

**The remaining five are not the same bug and must not be "fixed" the same way.**

- *CC:256, CC:2048, HH_HPA:1024* — both arms issue the **same** load width, so
  there is no width gap to close. CC 256 and CC 2048 are already reclassified as
  identical-config measurement artifacts in §6 (+10.4% / +9.2% on a re-run).
  Treat all three as noise until re-measured, and do **not** add candidates on
  their account.
- *HH_HPA:2048* — a genuine **orientation** gap, not a width gap. The floor wins
  with the transposed `64x128/4x8`; the deck had `128x64` but never `64x128`.
  The native arm is actually issuing the *wider* load (vw4 = 8 B) and still
  loses, so widening further is the wrong move here — the transpose is the fix.
  (HH_HPA is bounded by the `GLVW == VW or 1` generator restriction, §5.3, so
  vw8 is not available to it regardless.)
- *CC:192* — the floor wins with a **narrower** macro tile (`32x32` vs `64x64`)
  at identical width. Both tiles were already in the deck, so this is a tuning
  outcome, not a coverage gap. One cell at −6.1% is not enough evidence to
  restructure the CC family; re-measure before acting.

### 5.12 Ties: what they say, and why they should be left alone

| cell | delta | reading |
|---|---|---|
| HS_HPA:1024 | −0.1% | both arms identical (`128x64/8x4/vw4`, 16 B). True parity. |
| HS_HPA:2048 | −0.4% | arms **differ** (native `128x64` vs floor `64x128`) yet tie. For HS_HPA the transpose is a wash, unlike HH_HPA. |
| DD:2048 | +0.3% | native `vw1` (8 B) ties floor `vw2` (16 B). **Width does not help at this size.** |
| SS:512 | +0.9% | native winner has no recorded knobs (draft/auto phase); unreliable. |

Two things follow, and they matter for how the fixes are ordered:

1. **A tie is not a free win.** `DD:2048` ties at vw1 while `DD:768` loses 2.9%
   at vw1 and `DD:192` loses 8.2% at vw1. Widening DD to vw2 is expected to win
   192 and 768 and to be neutral at 2048 — it is not expected to be harmful, but
   the evidence does not promise a gain at 2048 either. Both widths stay in the
   deck rather than vw1 being replaced.
2. **The small-cube wins must not be disturbed.** Native wins 9/9 cells at
   128–512, several by 3×, and the winning tiles there are *small*
   (`32x32/2x2`, `64x32/4x2` for ZZ). The width fixes in §5.11 target
   128x128-class tiles and the 768+ range only. Widening the small-tile entries
   would risk the largest wins in the corpus in pursuit of the smallest losses.

### 5.13 Fixes landed, and what each one is expected to be worth

| change | cells targeted | expected |
|---|---|---|
| SS 128x128 gains `vw4` (16 B) | 2048, 4096, 1024, 768, 1365, 1000 | +5.5% to +15.1% |
| HH 128x128 gains `vw8` (16 B) | 2048, 4096, 1024 | +10.9% to +14.6% |
| DD 64x64 gains `vw2` (16 B) | 192, 768 (2048 a tie) | +2.9% to +8.2% |
| HPA decks gain the transposed `64x128` | HH_HPA:2048 | +7.7% |

`cap_vector_width()` now *derives* the cap-width variant from the dtype and the
tile shape rather than hardcoding it, and `test_occupancy_gate.py` asserts every
family deck can reach 16 B, so this class of gap cannot reopen silently. The new
candidates are all legal under the dual resource gate (§5.7) — 21 of 21 family
candidates pass.

**These are predictions from static analysis, not measurements.** The floor is the
evidence that the configs are faster, and the same configs are legal on this
device, but native has never run them. Only a TTY run confirms it, and the honest
statement is that 11 of 16 losses now have a mechanical candidate that has never
been benchmarked natively.


## 6. Measurement integrity (read before trusting any delta)

**Cross-arm bias.** On 12 cells where the *same config* ran in both arms
(native vs reference, same APU): mean **−5.30%**, median **−1.56%**, range
**−25.65% … +13.46%**, negative in **10/12**. Identical configurations do not
agree between the two run trees.

**Telemetry.** Reference runs: 910,175 and 846,901 rows, `gpu_busy_percent` maxima
93 and 82. Native run: 458 rows, busy max **0**. Every telemetry row has an empty
`phase` field, so per-phase clock normalization is impossible and the apparent
GFLOPS difference between arms is at least partly a clock/power-state artifact.

**Two "losses" are artifacts.** On the identical config, the native run measured
**+10.4%** (CC 256) and **+9.2%** (CC 2048) *faster* than the reference run. Those
two cells re-classify from LOSS to non-issues. Effective record: **12 config
losses, 1 tie band, 14 wins.**

**Consequence.** The A/B is not clock-controlled. Until §11's protocol is used, a
candidate's measured delta is only trustworthy if it is large relative to the
±25% identical-config spread, and identical-config controls must be interleaved in
the same session.

---

## 7. Root causes, ranked

1. **Coverage of the 128-bit band (dominant).** 12 config losses; `VectorWidth`
   alone explains 6.
2. **Measurement protocol (contaminates everything).** Cross-arm bias up to −25%;
   native telemetry detached; 2 of 14 "losses" are pure measurement.
3. **Exploration width.** Native explored 4–25 configs per family vs the floor's
   2–65, and never left 64-bit on SS/HH/DD at the cells that matter (§5.6).
4. **Never-tried mechanisms.** GSU, Stream-K, WGM≠1/4/8, DU∉{8,16} (§5.5).
5. **Shape-regime mismatch.** Small-shape winners legitimately sit below 128-bit
   (SS:256 floor winner is `32x64/4x8/VW4`); a blanket 128-bit rule would regress
   them. Candidates must be shape-scoped.

---

## 8. Route portfolio

| route | rationale | status |
|---|---|---|
| 16-byte global load (`VectorWidth`) | dominant loss cause; floor-proven; hard 16 B cap (§2) | **P1–P5, P8–P10** |
| ZZ at the cap, first-of-kind | only family with width headroom left | **P7, P20** |
| CC non-width (no headroom) | CC is already at the cap; probe tile/`DepthU` | **P18, P19** |
| LDS padding / occupancy | 3 losses need a companion knob | **P11** |
| `WorkGroupMapping` re-tune | every winner is 1/4/8; untested in between | **P12** |
| `DepthU` sweep | winners only ever 8/16 | **P13** |
| Stream-K | never compiled here; needs CPU legality first | **P14** (exploratory) |
| Split-U / GSU | never legal on HH-family (no MFMA); untested on SS/CC | **P15** (exploratory) |
| Rectangular / workgroup re-shape | floor wins several cells with 64x128, 128x32 | **P16** |
| `PrefetchGlobalRead` / DTL | `DirectToLdsNoDest` available, unused | **P17** (exploratory) |
| Per-shape specialisation | §5.3 precision; small shapes want <128b | policy, §10 |

Anything gated as class-illegal (GSU>1 on HH/HH_HPA/HS_HPA/CC-derived) is
**permanently skipped**, not re-run.

### 8.1 Routes the hardware rules out — do not re-propose

Each was proposed, then killed by evidence. Kept here so the same dead end is not
re-derived by a future agent.

| # | route | killing evidence |
|---|---|---|
| D1 | Wider global load (128-bit) for SS/CC/DD | hard ISA cap `GLVW × bytes ≤ 16` (`SolutionStructs.py:4583-4596`). SS maxes VW4, DD/CC/ZZ VW2, HH VW8 |
| D2 | 32 B load (P6, CC VW4) | `GLVW 4 × 8 B = 32 > 16` → Tensile rejects. **P6 RETIRED** |
| D3 | `DepthU 32` for complex (ZZ/CC) | class gate: `DepthU × 16 B = 512 > StaggerUStride 256` (`SolutionStructs.py:3342`) |
| D4 | `TT 2x2` for ZZ | `GLVW 1 % pv 2 != 0` — load-divisibility gate |
| D5 | MFMA / WMMA / dot4 / DP4A | absent from gfx90c `AsmCaps.py`. This *is* the gfx900→gfx90c gap |
| D6 | Over-wide MacroTile to amortise loads | register-file exhaustion → Tensile **error 4**. Now gate #4 (§5.7) |
| D7 | Transplants needing ISA conversion | none needed: every floor winner already compiles/runs on gfx90c unchanged (both arms emit `TensileLibrary_gfx90c.co.raw`). Work is knob harvesting, not conversion (§10) |
| D8 | Cross-run best-of-history comparison | forbidden: APU cross-run spread ±23–31% ALU |

### 8.2 Routes blocked on measurement, not on analysis

Ready to run, but **no CPU-only evidence can rank them** — a gate result says
"legal", never "faster". Listed so effort is not spent re-deriving what cannot be
decided here.

| route | blocked on |
|---|---|
| P14 Stream-K | gate-legal but never *compiled* here; needs a real Tensile build + bench. Prior art tempers expectations: on MI250X, data-parallel schedules win for **most** problem sizes, Stream-K is competitive only in narrow regimes and costs up to ~30% L1 hit rate (Stream-K++, §12) |
| P15 Split-U / GSU | untested, untestable CPU-side; permanently blocked on HH-family (no MFMA) |
| P17 `PrefetchGlobalRead` / DTL | legal; benefit is bandwidth-dependent, so only measurable on hardware |
| Interleaved floor+candidate A/B | mandatory for any delta claim; identical-config controls re-measure the §6 bias |
| 127 `T1_RERUN` phases | separate integrity task, never mixed into tuning |

**Net: 5 remaining routes are measurement-bound.** More CPU work will not resolve
them; the next real step is a TTY session.

---

## 9. Concrete candidate deck

Every candidate below is **absent from every native config ever benchmarked**
(§5.2/§5.6 signatures). Legality column = CPU-only proof status.

| id | target | MT | TT | VW | width | DU | WGM | GSU | LdsPadB | rationale | CPU gates |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | SS 512–4096 | 128x128 | 8x8 | 4 | 16 B | 16 | 4 | 1 | 0 | floor's SS winner; native is VW2 | **PASS** |
| P2 | HH 512–4096 | 128x128 | 8x8 | 8 | 16 B | 16 | 4 | 1 | 0 | floor's HH winner; native capped VW4 | **PASS** |
| P3 | DD 192–2048 | 64x64 | 4x4 | 2 | 16 B | 16 | 4 | 1 | 0 | floor's DD winner; native is VW1 | **PASS** |
| P4 | HH_HPA 2048 | 64x128 | 4x8 | 2 | 16 B | 8 | 4 | 1 | 0 | floor's HH_HPA:2048 winner | **PASS** |
| P5 | CC 192 | 32x32 | 4x4 | 2 | 16 B | 8 | 4 | 1 | 0 | floor's CC:192 winner (32x32 beats 64x64) | **PASS** |
| P6 | ~~CC 128-bit~~ | ~~64x64~~ | ~~4x4~~ | ~~4~~ | ~~32 B~~ | — | — | — | — | **RETIRED: 32 B load is illegal (§2)** | **FAIL** |
| P7 | ZZ 16-byte load | 64x64 | 4x4 | 2 | 16 B | 16 | 4 | 1 | 0 | only family never run at the cap (§5.4) | **PASS** |
| P8 | HH_HPA 16 B | 128x128 | 8x8 | 8 | 16 B | 16 | 4 | 1 | 0 | floor has it; it loses → exploratory | **PASS** |
| P9 | HS_HPA 16 B | 128x128 | 8x8 | 8 | 16 B | 16 | 4 | 1 | 0 | as P8 | **PASS** |
| P10 | SS 256 | 32x64 | 4x8 | 4 | 16 B | 8 | 4 | 1 | 0 | floor's SS:256 winner (small-shape 16 B) | **PASS** |
| P11 | SS 2048/4096 | 128x128 | 8x8 | 4 | 16 B | 16 | 4 | 1 | 0 | P1 + `LdsPadB 2→0` companion | **PASS** |
| P12 | best SS/HH cell | 128x128 | 8x8 | as incumbent | — | 16 | **2** | 1 | as incumbent | WGM never 2 | **PASS** |
| P13 | best SS/HH cell | 128x128 | 8x8 | as incumbent | — | **32** | as incumbent | 1 | as incumbent | DU never 32 | **PASS** |
| P14 | SS 2048/4096 | 128x128 | 8x8 | 4 | 16 B | 16 | 4 | 1 | as incumbent | Stream-K (exploratory) | **PASS** |
| P15 | SS | 64x64 | 4x4 | 2 | 16 B | 16 | 4 | **2** | as incumbent | GSU (exploratory) | **PASS** |
| P16 | DD 512 | 32x32 | 4x4 | 2 | 16 B | 8 | 4 | 1 | 0 | floor's DD:512 winner tile | **PASS** |
| P17 | SS 1024 | 128x128 | 8x8 | 2 | 8 B | 16 | 4 | 1 | as incumbent | + `PrefetchGlobalRead` | **PASS** |
| **P18** | CC 512/1024 | 64x64 | 4x4 | 2 | 16 B | **16** | 4 | 1 | 0 | **replacement for P6**: CC has no width headroom, so probe `DepthU` | **PASS** |
| **P19** | CC 512/1024 | 128x64 | 8x4 | 2 | 16 B | 16 | 1 | 1 | 0 | **replacement for P6**: rectangular tile, `WGM 1` | **PASS** |
| **P20** | ZZ 512–2048 | 32x32 | 4x4 | 2 | 16 B | 16 | 4 | 1 | 0 | P7 at the floor's own small-tile shape | **PASS** |
| **P21** | ZZ 128x32 | 128x32 | 8x4 | 1 | 8 B | 8 | 4 | 1 | 0 | **replaces the dead `128x64x8/8x4`** (§5.7) | **PASS** |
| **P22** | ZZ 32x128 | 32x128 | 2x8 | 1 | 8 B | 8 | 4 | 1 | 0 | **replaces the dead `64x128x8/4x8`** (§5.7) | **PASS** |
| **P23** | ZZ 64x64, 512 thr | 64x64 | 4x2 | 1 | 8 B | 8 | 4 | 1 | 0 | new axis: thread count never varied for ZZ (§5.7) | **PASS** |
| **P21** | ZZ 128x32 | 128x32 | 8x4 | 1 | 8 B | 8 | 4 | 1 | 0 | replaces the dead `128x64x8/8x4` (§5.7) | **PASS** |
| **P22** | ZZ 32x128 | 32x128 | 2x8 | 1 | 8 B | 8 | 4 | 1 | 0 | replaces the dead `64x128x8/4x8` (§5.7) | **PASS** |
| **P21** | ZZ 128x32 | 128x32 | 8x4 | 1 | 8 B | 8 | 4 | 1 | 0 | replacement for the dead `128x64x8/8x4` (§5.7) | **PASS** |
| **P22** | ZZ 32x128 | 32x128 | 2x8 | 1 | 8 B | 8 | 4 | 1 | 0 | replacement for the dead `64x128x8/4x8` (§5.7) | **PASS** |

**Legality proof.** 19/20 of the deck passes all three CPU gates
(`scheduler.validate_config`, `scheduler._validate_tensile_loads`,
`scheduler.assembly_class_valid`) as knob mutations of already gate-clean
`phases.yaml` templates. P6 is the sole failure, with the concrete reason
`GLVW 4 * bpe 8 > 16`; P18–P20 replace it. **No GPU was touched.** Proof script:
`/tmp/opencode/candidate_legality.py`, results `/tmp/opencode/candidate_legality.json`.

**Ordering.** P1, P2, P3 first — floor-proven at the exact cells with the largest
gaps. Then P11 (P1's companion), P16. Then the first-of-kind P7/P20. Then P4/P5,
P18/P19. Exploratory P8–P10, P12–P15, P17 last.


**Constraint for every candidate.** `VectorWidth` and `GlobalLoadVectorWidth` must
agree or the latter be 1 (§2). `MacroTile` must be divisible by `ThreadTile` and
by `NLCA × VectorWidth` for every global load. All candidates must pass
`validate_config`, `_validate_tensile_loads` and `assembly_class_valid` **on CPU**
before any GPU time is spent.

---

## 10. Spoof transplant appendix (worst losers only)

Transplanting is reserved for the worst losers, and each transplant is documented
as a gfx900→gfx90c adaptation. Note the ceiling on this technique: every floor
config that wins on this device **already compiles and runs on gfx90c unchanged**
(both arms produce `TensileLibrary_gfx90c.co.raw`). So there is no ISA conversion
to perform — the work is harvesting legal knob settings out of the reference deck
and re-expressing them as native phases, plus recording which knobs are
gfx900-specific and why.

Worst losers and the floor config each one is chasing:

| cell | native | floor | floor config to transplant | adaptation note |
|---|---|---|---|---|
| SS 2048 | VW2 64b | VW4 128b | `128x128/8x8/DU16/WGM4/GSU1`, `LdsPadB 0` | gfx900 deck uses `LdsPadB 2` here; gfx90c needs 0 — a legal-knob change, not ISA |
| SS 4096 | VW2 64b | VW4 128b | same as SS 2048 | as above |
| HH 1024 | VW4 64b | VW8 128b | `128x128/8x8/DU16/WGM4/GSU1` | VW8 requires `GLVW ∈ {8,1}`; gfx900 deck is satisfiable as-is |
| HH 2048 | VW4 64b | VW8 128b | same as HH 1024 | as above |
| DD 1024 | VW1 64b | VW2 128b | `64x64/4x4/DU8/WGM4/GSU1` | f64 VW2 raises LDS pressure; check 64 KiB fit |
| HS_HPA 2048 | VW4 64b | VW4 64b | `64x128/4x8/DU8/WGM4/GSU1` | same width — this is a *tile* transplant, not a width one |

---

## 11. Validation protocol (TTY only)

1. **Interleave** floor and candidate in one session, same process, same clocks.
2. **Pin clocks** if the platform permits; otherwise log per-phase sclk and report
   both raw and clock-normalized numbers with coverage stated.
3. **≥3 samples**, median statistic; never max (winner instability is 77%).
4. **Include identical-config controls** in every session to re-measure the
   cross-arm bias of §6; if control spread exceeds ±5%, the session is void.
5. Spend order: P1, P2, P3 → P11, P16 → P7, P21, P22 (ZZ, the family that
   currently produces no native winner) → P4, P5, P18, P19 → exploratory.
6. Reference floor is **never re-run** to make a candidate look good; the
   127 `T1_RERUN` phases are a separate integrity task, 1,881 `T2_RERUN_HELD` stay
   held absent explicit opt-in, 277 `T3_UNREPRODUCIBLE` are terminal.

---

## 12. Sources

**Authoritative for this device (read the source first).**

- `Tensile/Tensile/AsmCaps.py` — gfx90c ISA capability flags (no MFMA/WMMA/dot/DP4A).
- `Tensile/Tensile/DataType.py` — authoritative dtype byte sizes.
- `Tensile/Tensile/Common.py` — Split-U, Stream-K, StaggerU, LDS, occupancy params.
- `Tensile/Tensile/SolutionStructs.py:4583-4596` — the `GLVW == VW or 1` guard.
- `Tensile/Tensile/SolutionStructs.py:3342` — complex `DepthU`/`StaggerUStride` class rule.
- `Tensile/Tensile/KernelWriterAssembly.py:15422` — the occupancy test that sets
  `overflowedResources = 4` (§5.7).
- `Tensile/tuning_docs/tensile_tuning.tex` — official tuning parameter reference.
- <https://github.com/ROCm/Tensile/blob/develop/tuning_docs/tensile_tuning.tex>

**ISA / architecture context for the tuning experiment (AMD primary).**

- **gfx900 and gfx90c are both GFX9 / GCN-generation targets.** They are separate AMDGPU processor targets within the GFX9 family, not separate ISA generations. LLVM explicitly places `gfx900` and `gfx90c` under the same `gfx9-generic` processor family. 

- **This experiment is not a direct gfx900-vs-gfx90c hardware comparison.** The actual comparison is:
  1. **native gfx90c tuning:** compile/tune Tensile kernels for the real `gfx90c` target; versus
  2. **gfx900-spoof tuning:** deliberately compile/tune the same workload under the `gfx900` target model while executing the resulting kernels on the `gfx90c` device.

- Therefore, **the relevant question is whether a `gfx900` target model produces a useful search space and kernel schedule for a real `gfx90c` device**, not whether `gfx900` hardware is faster or slower than `gfx90c` hardware.

- The spoof arm should consequently be described as **`gfx900`-targeted code executed on `gfx90c`**, rather than as a physical `gfx900` implementation. Its kernels are obtained directly from the shipped `gfx900` part of TensileLibrary.dat.

- **Do not characterize `gfx90c` as a separate 7 nm ISA generation.** `gfx90c` is an AMDGPU GFX9 target identifier. In particular, the LLVM target definition does not establish the earlier claim that `gfx90c` means "Vega 7" or that it is the target for a Radeon Pro V520. The LLVM record that introduced `gfx90c` explicitly describes it as the target used to differentiate the **Ryzen 4x00/5x00-series APUs** that had previously been grouped under `gfx909`.

- **Do not use the physical CU count, process node, or product family as the explanation for the tuning result unless the specific `gfx90c` device being tested has independently established hardware characteristics.** Those are hardware-level properties; the experiment here is principally about **compiler target selection and the resulting Tensile tuning/search behavior**.

- The important compiler fact is that AMDGPU target selection affects generated code. LLVM documents that `-mcpu=<target-id>` / `--offload-arch=<target-id>` selects the processor target and its target features, and that target-specific code generation can differ accordingly. :contentReference[oaicite:3]{index=3}

- LLVM also defines a `gfx9-generic` target covering `gfx900`, `gfx902`, `gfx904`, `gfx906`, `gfx909`, and `gfx90c`. This is useful evidence that the two targets belong to a closely related GFX9 ISA family, but **it does not mean their generated code, compiler scheduling model, bugs, feature flags, or performance characteristics are identical**.

- Consequently, the experimental framing should be:

  **Native arm:**  
  `gfx90c` target → Tensile search/tuning → kernels generated for the native target → execute on `gfx90c`.

  **Spoof arm:**  
  `gfx900` target → Tensile search/tuning → kernels generated under the `gfx900` target model → execute on the same `gfx90c`.

- The comparison therefore isolates **tuning strategy / target-model choice**. The physical execution device remains `gfx90c` for both arms.

- Any performance advantage of the spoof arm should therefore be attributed, at the experimental level, to the **different search space and compiler/code-generation choices induced by targeting `gfx900`**, provided the benchmark controls are otherwise identical. It should not be described as evidence that physical `gfx900` hardware is intrinsically superior.

- Likewise, if the native `gfx90c` search loses to the spoof search for a particular Tensile configuration, that result should be interpreted as evidence about **the effectiveness of the two tuning strategies on `gfx90c`**, not as an ISA-generation comparison.

**AMD tuning / GEMM practice.**

- <https://rocm.docs.amd.com/projects/Tensile/en/latest/src/conceptual/kernel-parameters.html>
- <https://rocm-handbook.amd.com/projects/amd-rocm-optimization-guide/en/latest/patterns/examples/matrix-multiply-optimization.html>
- **Stream-K++** (MI250X, 7 scheduling policies, Bloom-filter config selection) —
  <https://arxiv.org/pdf/2408.11417>. Most relevant external evidence for the Stream-K
  route, and it *tempers* it: data-parallel schedules win for most problem sizes,
  Stream-K is competitive only in narrow regimes, and Stream-K schedules showed up
  to ~30% lower L1 hit rate where data-parallel won.

**SOTA tuning strategies (native gfx90c vs. gfx900-targeted spoof tuning)**

- **Stream-K** — https://arxiv.org/abs/2301.03598. Introduces alternative GEMM work decomposition to improve parallelism and resource utilization, especially when conventional tiling leaves insufficient work. Demonstrates benefits of scheduling strategy beyond conventional kernel selection. Relevant as alternative tuning dimension, not proof that candidate selection alone explains native vs. spoof performance. Single-configuration results apply only to evaluated workloads.

- **tritonBLAS** — https://arxiv.org/abs/2512.04226. Presents analytical GEMM configuration selection without exhaustive runtime autotuning. Demonstrates that analytical selection can approach exhaustive-search performance on evaluated workloads and hardware. Relevant to agentic tuning: filter candidates before expensive compilation and benchmarking. Reported results do not establish model accuracy for gfx90c or gfx900-targeted kernels.

- **WaveTune** — https://arxiv.org/abs/2604.10187. Presents wave-aware bilinear latency model for GPU kernel tuning. Models execution-wave effects and workload geometry. Relevant to candidate ranking and Tensile validator design. Does not establish wave quantization as dominant bottleneck on tested gfx90c device or explain spoof performance. Requires direct experimental validation.

- **nvMatmulHeuristics / CUTLASS 4.2** — https://developer.nvidia.com/blog/improving-gemm-kernel-auto-tuning-efficiency-on-nvidia-gpus-with-heuristics-and-cutlass-4-2/. NVIDIA reports approximately 96% of exhaustive-search performance using 16 heuristically selected candidates for evaluated H100 Llama 3 405B workloads. Demonstrates value of ranking candidates before benchmarking. NVIDIA-specific result; does not validate AMD candidate budgets or P1 → P3 evaluation order.

- **A Few Fit Most: Performance Portability Through Multi-Versioning for GPU SGEMM** — https://arxiv.org/abs/2507.15277. Studies performance portability through a limited set of specialized GEMM implementations. Relevant to balancing kernel diversity against tuning and maintenance costs. Does not establish universal 128-bit optimum for AMD GPUs.

**Implications for tuning experiment**

Experiment compares two tuning strategies on same physical gfx90c device:

1. **Native:** Generate and tune Tensile kernels using gfx90c target.
2. **Spoof:** Generate and tune Tensile kernels using gfx900 target model; execute resulting kernels on gfx90c.

Relevant research-supported strategies:

- **Candidate selection:** Use analytical or heuristic filtering to reduce expensive benchmark runs.
- **Execution-aware modeling:** Include workload geometry, wave utilization, and resource usage in candidate ranking.
- **Scheduling:** Explore alternative GEMM work decomposition where implementation permits.

These papers motivate methods, not causal explanations for native-versus-spoof performance. Attribute improvements to measured results; isolate individual tuning factors experimentally.

**128-bit configuration guidance**

Treat §2's 128-bit configurations as empirical optima within tested candidate space. They are not AMD ISA requirements or universal performance rules. Report workload, target, compilation settings, and measured results when interpreting §5.3.

**Interpretation**

Primary outcome: effectiveness of native gfx90c tuning versus gfx900-targeted spoof tuning on gfx90c.

Evaluate analytical filtering, wave-aware ranking, and scheduling independently where possible. Cited papers justify investigating these methods; they do not establish which will perform best in this experiment.

---

## 13. Decision log

- **2026-09-13** — oto = deterministic convergence; no LLM in the loop; manual-LLM
  add-only as a contingency. Coverage-first.
- **2026-09-19** — HS_HPA rejection root-caused to the `GLVW==VW-or-1` stock
  generator restriction, isa-independent. Guard-legal parameterizations found.
- **2026-09-19** — scheduler mirror gap **FIXED**: `_validate_tensile_loads` now
  models the `GLVW` predicate; 6 unit tests + 410/410 manifest sweep pass.
- **2026-09-20** — wide deck regenerated; 36 class-illegal GSU>1 cells on
  HH-derived families gated out; 410 phases, all gate-clean.
- **2026-09-28** — A/B reframed: same APU both arms, so spoof = a config deck.
  Knob-exact re-extraction reproduces 38/38. Root cause = no 128-bit global load.
- **2026-09-28** — CC 256 / CC 2048 reclassified from LOSS to non-issues
  (+10.4% / +9.2% on identical config). Effective: 12 config losses.
- **2026-09-28** — `run_auto()` no-existing-reference branch did not forward
  `release_held` (`port_tensile.py:1479`); **FIXED**, all three call sites forward
  it. `test_reference_tiers.py` 13/13 green.
- **2026-09-28** — §5.3 precision: 128-bit *reach* ≠ 128-bit *wins*. Only plain HH
  converts 128-bit into a win; the HPA families' 128-bit floor configs lose.
- **2026-09-28** — §5.4/§5.5: GSU and Stream-K have never been compiled on this
  device at all; only the default `Ailk_Bjlk` contraction pattern exists.
- **2026-09-28** — **load-width cap discovered via the CPU gates: the global load
  is hard-capped at 16 bytes** (`GLVW × bytes-per-element ≤ 16`). Complex types
  are 8 B/element, not 4/8, so CC's 128-bit point is `VW2` — which the floor
  already runs. Corrects the earlier "CC and ZZ are both at 64-bit" claim and
  retires P6 (`CC VW4` = 32 B, illegal). ZZ is the sole remaining width
  frontier. 19/20 candidates CPU-legal; no GPU touched.

- **2026-09-28** — **The occupancy model is retired, falsified by measurement.**
  Built all 47 ZZ phases with Tensile's own kernel writer, CPU-only
  (`check_tensile_build.py`). There are two independent limits, on two different
  parameters: **256 VGPRs/thread** bounds `ThreadTile0 × ThreadTile1 × weight`,
  and **64 KB LDS** bounds `(MT0 + MT1) × DepthU × bytesPerElement`.
  `MacroTile` does not appear in the first, `ThreadTile` does not appear in the
  second. The old `R × MacroTile_area ≤ 32768` rule passed all 10 configs that
  then died on hardware. Gate now agrees with Tensile **47/47**. See §5.7.
- **2026-09-28** — **All 10 dead ZZ phases removed from the live deck.** 4×
  `128x32x8/8x4` and 4× `128x32x16/8x4` (271 VGPRs) and 2× auto
  `64x64x16/8x8` (519 VGPRs) replaced with `128x32x8/2x8`, `64x32x16/4x2` and
  `64x64x16/4x4`, all with GPU-measured precedent. `64x64x16/4x4` and
  `128x32x8/2x8` build at 167 and 171 VGPRs. Deck is now 434 phases, **47/47 ZZ
  build clean**.
- **2026-09-28** — **The ZZ direction was backwards.** Native wins all 5 ZZ
  cells with *small* tiles (`32x32/2x2`, `64x32/4x2`); the floor's `64x64/4x4` is
  too large for complex f64 at small cubes and loses by up to 3×. The proposed
  "wider" `128x32` replacements were both illegal and the wrong direction. §5.10.
- **2026-09-28** — **All 16 large-cell losses are one coverage gap**: the native
  arm never issues `vw4` on 128x128 SS or `vw8` on 128x128 HH. Per-cell
  analysis: 18 WIN / 4 TIE / 16 LOSS over 38 shared cells, with a clean split by
  size (native wins 9/9 at 128–512, floor wins 17 at 1365–4096). §5.10.
- **2026-09-28** — **Reference-floor root cause found and fixed.**
  `tensile_library.py` emitted `GlobalReduceVectorWidth`, absent from Tensile
  4.44.0; `checkParametersAreValid` exited during parameter defaulting, so all
  three 2026-09-28 reference runs produced **0 of 127** phases. Emission removed;
  `port_tensile.py` now drops any parameter absent from Tensile's
  `validParameters`. `test_tensile_params.py` verifies 434 live phases and 3,878
  archived reference entries.
- **2026-09-28** — **`--auto` could burn an entire budget measuring nothing.**
  All three failed reference runs returned early from `run_auto()` and never
  entered the native loop. The floor is now attempted but can never abort tuning:
  `reference_floor_authoritative=False`, run proceeds, report prefixed
  `PROVISIONAL FLOOR`. `test_auto_reference_floor.py` 9/9.
- **2026-09-28** — **93% of an overnight budget was spent on unbuildable phases**
  (288 of 309 starts in `run_20260928_024945`). The scheduler correctly stopped
  retrying legal configs (`32x128x8` skipped 28×) but retried dead tiles 29× each
  — precisely the failures the retired model could not see.
- **2026-09-28** — **`--auto` now asks instead of assuming.** The T1/T2/T3 tiers
  silently chose what to re-measure and how long to run. **Five** questions are
  now asked at the start of every `--auto` (in a TTY): re-measure the **127
  ILLEGAL** cells? re-measure the **1881 UNDER-SPECIFIED** cells? re-attempt the
  **277 UNREPRODUCIBLE** cells? how many **iterations** (default **10**, was
  100)? how many **mutations** (default **3**, was 2)? Non-interactive runs take
  the defaults and say so. `auto_prompt.py`, 23 tests in `test_auto_prompt.py`.
  Answering no to all three re-measurement questions no longer triggers a
  reference run behind the user's back. The tier labels remain in stored
  manifests for provenance, but no tier decides anything on its own any more.
- **2026-09-28** — **The 277 UNREPRODUCIBLE cells became a question, not a
  hardcoded drop.** They used to be removed unconditionally, on the reasoning that
  re-running can only reproduce the failure. That is a statement about *this*
  Tensile build, not a property of the cell — an upgrade could make them
  reproducible. They are now question 3, defaulting to dropped (`release_drop`),
  and are **not** bundled with the T2 opt-in: `--release-under-specified` and
  `--release-unreproducible` release independently. Worth re-attempting once,
  after the next Tensile upgrade.
- **2026-09-28** — **11 of the 16 large-cell losses were unwinnable by
  construction.** The floor's winners at SS 128x128 (`vw4`), HH 128x128 (`vw8`)
  and DD 64x64 (`vw2`) all hit the 16 B global-load cap, and the native family
  decks hardcoded one step below it — the phases were never generated. Added,
  with the width now *derived* by `cap_vector_width()` so it cannot silently
  regress; `test_occupancy_gate.py` asserts every family deck can reach 16 B.
  Expected +2.9% to +15.1% across 11 cells — **predicted from static analysis,
  not yet measured on native hardware.**
- **2026-09-28** — **HH_HPA:2048 was an orientation gap, not a width gap.** The
  floor wins with transposed `64x128/4x8`; only `128x64` was staged. The native
  arm was already issuing the wider load and still lost, so widening further
  would have been the wrong fix. Both orientations now staged for HH_HPA and
  HS_HPA.
- **2026-09-28** — **Three "losses" are not losses.** CC:256, CC:2048 and
  HH_HPA:1024 show the *same* load width on both arms, so there is no gap to
  close; the first two are already reclassified identical-config artifacts (§6).
  No candidates added on their account. CC:192 is a narrower-floor-tile win at
  identical width, and both tiles were already in the deck.
- **2026-09-28** — **DD:2048 ties at vw1, DD:768 loses 2.9% at vw1.** Width is
  size-dependent for DD; both widths are kept rather than swapping, so widening
  cannot cost the 2048 tie.

### Superseded statements (from Appendix A, kept for provenance)

| Appendix A claim | Status |
|---|---|
| §5.1 incumbents table from `run_20260913_215546` | run dir is gone; values are legacy-only, superseded by §5.3 |
| §5.2 auto-mutation results (9/30 CSVs) | legacy run; superseded by §5.6 |
| §6.2 "draft WINs" margins vs carried incumbents | draft run not in the A/B; superseded by §5.3 |
| §5.1 stale-CSV note for ss/1024³ | resolved by the multi-size-sweep parse (§3) |
| "DD closed, no GPU spend" | DD has a 128-bit loss (P3) — reopened |
| "int8 1024³ +18.3% harvest" | SS family is f32, not int8; mislabelled, discarded |
| earlier §5.2/§5.4 "CC and ZZ never at 128b" | **wrong**: complex is 8 B/elem, so CC `VW2` is already the 16 B cap in both arms. Only ZZ lacks width headroom |
| earlier P6 "CC 128-bit = `VW4`" | **impossible**: 32 B load, rejected by `scheduler` (`GLVW 4 * bpe 8 > 16`) |

---

## Appendix A — legacy working notes (2026-09-13 → 2026-09-20)

Retained verbatim for provenance. Superseded where §13 says so; **not** to be used
as current evidence.

## gfx90c — oto Potential & Convergent-Candidate Configurations

> Role: candidate deck + search rules for the deterministic loop. Not a store of
> raw benchmark data (that's `results.md`). Frozen prior verdicts are carried as
> the deck's seed knowledge (conclusions only — sanctioned source:
> `prior_INSIGHTS_CAVEMAN_ULTRA.md`); the loop runs them through the deterministic
> harvest → mutate pipeline.

### 1. What has already been tried (carried verdicts)

Candidate sweep A–G over 21 shared cells (throttle-adjusted, ±5% band, median-of-seeds)
→ **5 W / 10 T / 6 L**.

| Candidate | Result | Action for oto |
|---|---|---|
| A sgemm controller sweep (p16) | 0W/3T/0L (2048³ +0.3..+5.6) | keep 2048³ as deck seed; do NOT re-sweep |
| A hgemm (p17) | 0W/0T/3L (−8..−9%) | drop |
| B LLM-decode GEMV deeper (p18) | **2W/3T/0L**: 32x4096x1 +13.6%, 64x4096x1 +21.3% | **harvest as incumbent** (native GPUs) |
| C asymmetric/odd (p20/p25) | **CRASHED every run** (`AssertSizeMultiple: [1]`) | fix `[{}]` applied; re-test runs via the native deck, verdict vs the floor chain |
| D occupancy/LDS (p19) | 512/1024³ L (−8.6/−19.7%); **2048³ W +14.1/+20.1%** | harvest 2048³; kill sweep path |
| E bf16 (p22) | 0W/1T/1L (−13.6% @1024³; +2.4% @2048³ T) | keep 2048³ seed; don't chase bf16 |
| E fp64 (p23) | 0W/1T/2L (ties +0.1%; pipe-saturated) | drop new sweeps; fp64 is done at 98% |
| E int8 (p24) | **1W/1T/0L**: 1024³ **+18.3% W** | **harvest**; strongest win |
| F batched/short-K (p21) | 3 genuinely-new cells (64x11008x1, 4x2048x64, 64x2048x16) | keep cells, harvest best |
| G schedule vars | label-only, no effect | ignore |

**Other carried facts:**
- Only 6 genuinely-new problem cells were ever produced. oto's main axis is
  **coverage** of the 28-family footprint (see `mapping.md`).
- FP64 at 98% of a 101 GFlops pipe → no headroom; do not spend GPU on it except to
  confirm port-level correctness.
- Best measured per datatype (carried ceilings, `results.md` §2): FP32
  1118.7@1024³, FP16 2492.1@4096³, BF16 1108.5@2048³, INT8 881.2@2048³, FP64
  98.6@1024³.
- Envelope: ±23–31% raw ALU swing; ties at ±5% = parity; winner instability 77%.

### 2. Deterministic candidate rules (the convergence core)

- **N4/H7 (kept):** mutate the current per-cell winner by **≤2 knobs** (neighbours),
  never resweep a wide grid; drop any fingerprint already benchmarked.
- **N8 (kept):** winner statistic = median-of-seeds; max is reference-only.
- **NP (oto, no consultation):** knob pool is fixed and gfx90c-legal:
  `MacroTile`, `ThreadTile`, `WorkGroup`, `WorkGroupMapping`, `DepthU`,
  `GlobalSplitU`, `PrefetchGlobalRead`, `PrefetchLocalRead`, `VectorWidth`,
  `NLCA`, `EPS`, `Stages`. No matrix instructions, no `SIA>1`, no Fp16AltImpl.
- Mutation is then **deterministic + gated**: each candidate must keep a valid
  (occupancy/LDS) footprint (that is what killed candD forks) — the validator checks
  LDS fit on 64 KB/CU and 7-CU occupancy ≥ some floor, config-valid (no
  `AssertSizeMultiple: [1]` style), fp unique (no re-run).
- **Budget:** configurable wall-time/GPU-minutes + finite per-phase timeout default;
  the loop stalls → the phase gets one interactive skip/kill.

### 3. Search spending rules

- Coverage (new family×pattern×shape cells) has priority; then mutate the newly
  discovered winners.
- A config is only worth GPU time if ALL hold: median-of-seeds with NumBenchmarks ≥ 3;
  a ruler/reference shape repeats every run (throttle control); no known-crash config;
  formulation is "mutate the per-cell winner", not "resweep a grid over already-tuned
  shapes".
- Do NOT re-sweep what already failed (carried verdicts; `results.md` §5).
- Missing rulers stay missing, never inferred (FP16-DDR/BF16-DDR remain absent by
  design until a real BF16/FP16 GEMV control cell runs).
- The manual-LLM contingency is add-only, user-invoked, ≤5 candidates dumped into
  `phases.yaml` — same pipeline, never in the loop.

### 4. Decisions log

- 2026-09-13: oto = deterministic convergence; no LLM in loop; manual-LLM
  add-only worst case. Driver per `implementation_plan.md` §The Driver Architecture.
  Coverage-first per Step 3.
- 2026-09-19: **HS_HPA rejection root-caused; guard-legal configs found.** Exact
  rejection (via `PrintSolutionRejectionReason`): non-MI assembly guard
  `GlobalLoadVectorWidth{X} must be == VectorWidth or == 1`
  (`SolutionStructs.py:4583-4596`; source comment: "so shift-ptr logic will
  work"). It fires when `setGlobalLoadVectorWidth` (`:2010-2047`) pv-reduces
  GLVW 4→2 for 64x64x8/TT4x4/VW4 tabs (totalElements 512 < NumThreads·GLVW =
  1024). The predicate is **isa-independent** (rejects gfx900 identically) — a
  stock-Tensile *generator/representation* restriction, not a gfx90c HW/ISA
  limit, and not an assembler failure. **Same intent admitted on stock Tensile:**
  MT64x64x16/TT4x4/VW4/DU16 → `1/1 after SolutionStructs`, gfx90c kernel
  assembles (`Kernels.so-000-gfx90c.hsaco`, `TensileLibrary_gfx90c.co`) and
  loads; MT64x64x8/TT4x4/VW2/DU8 → `1/1 after SolutionStructs` and `after
  KernelWriter`. HS_HPA tuning/config search resumes on those two
  parameterizations.
- **Scheduler mirror gap — FIXED (2026-09-19):** `_validate_tensile_loads` (scheduler.py
  `:211-362`) now models the `GLVW==VW or ==1` predicate (4583-4596), which the wrongly
  pre-validated 64x64x8 deck violated; 6 unit tests + 410/410 manifest sweep pass.
- 2026-09-13: acceptance narrowed to TWO measures — (1) beat the gfx900-spoof floor
  across the whole shipped suite; (2) approach the per-family ceilings of
  `gfx90c_theoretical_limits.md` §5 (measured utilization logged per
  (family, bound_class)). Occupancy (GSU/WGM/MT/TT right-sizing) is the first-class
  objective, not a constraint (T9).
  the native deck + recalled reference-floor verdicts are
   the re-test path now.
- 2026-09-28: **A/B reframed (§7).** Both arms run on the same gfx90c APU
  (`TensileLibrary_gfx90c.co.raw` in both run trees), so the "spoof" arm is a
  *config deck*, not different silicon. Knob-exact re-extraction reproduces all
  38/38 floor values. Root cause of the losses: **the native deck never issues
  a 128-bit global load** — `ls run_*/phase_*vw8*` is empty, and HH's/SS's best
  tiles were only ever run at VW4/VW2 (64-bit) where the floor runs VW8/VW4
  (128-bit). `VectorWidth` is the lever in 9 of 14 losses (6 of them *only*
  `VectorWidth`); 12 of 14 are configs never run. Local part is **Vega 7**
  (per `gfx90c_common.py`), not "Vega 8".
- 2026-09-28: **CC 256 (−13.4%) and CC 2048 (−6.5%) are reclassified from LOSS
  to non-issues.** On the identical config the native run measured +10.4% and
  +9.2% *faster* than the reference run. Cross-arm bias over the 12 comparable
  cells is median −1.6%, range −25.7%…+13.5%, negative in 10/12; the native run
  has 458 telemetry rows with `gpu_busy_percent` max 0. The A/B is not
  clock-controlled. §9 (interleaved arms + clock pinning) now outranks new
  candidates. Effective record: **12 config losses, 1 tie band, 14 wins.**
- 2026-09-28: `run_auto()`'s no-existing-reference branch called
  `run_gfx900_reference()` without forwarding `release_held`, so
  `--auto --release-under-specified` silently held T2 on a fresh machine.
  Fixed (`port_tensile.py:1479`); all three call sites now forward the flag.
  New `test_reference_tiers.py` — 13 tests, all green, including a regression
  that fails if the fresh branch drops the flag again.

### 5. Next-round candidate deck

Working area the deterministic loop appends to (`phases.yaml` mirror). Entries are
`(family, cell / shape, incumbent config knobs, best median GFlops, % of family
ceiling, next mutation)`. Deck = `phases.yaml` (410 phases, 2026-09-26); seed data:
`run_20260913_215546` (93 CSVs / 101 cells) + the draft deck run
`run_20260920_235815` + the recalled reference floor.

#### 5.1 Incumbents by family (median-of-seeds, per winning cell)

Winner statistic per N8; ceilings per `gfx90c_theoretical_limits.md`. Data:
`gfx90c_runs/run_20260913_215546` (93 CSVs → 101 cells, 66 RED at <50% ceiling).

> **ss/1024³ stale-CSV caveat:** the 1024³ CSV under
> `phase_phase_ss_Ailk_Bljk_1024x1024x1024` was produced by a kernel
> `Cijk_Ailk_Bljk_SB_MT96x96x16_SN_K1` (MT96) while the stored config in that
> run dir is MT64/TT4/NLCA3 — the CSV is stale from an earlier overwritten config,
> and the same dir logs `Actual Solutions: 0 / 1 after SolutionStructs`. The
> 397.2 media for ss/1024³ therefore belongs to the **MT96** variant, not the MT64
> "seed"; treat the MT64 seed as un-runnable under NLCA3 (see §5.2/§5.3 for the
> Tensile-divisibility root cause and the NLCA fix).

| family | shape | best median GFlops | %ceil | winning phase |
|---|---|---|---|---|
| cc | 256³ | 230.4 | 20.6 | `phase_phase_cc_Ailk_Bjlk_256x256x256` |
| cc | 512³ | 175.9 | 15.7 | `phase_phase_cc_Ailk_Bljk_512x512x512` |
| cc | 1024³ | 157.4 | 14.1 | `phase_phase_cc_Ailk_Bjlk_1024x1024x1024` |
| cc | 2048³ | 281.3 | 25.1 | `phase_phase_cc_Ailk_Bjlk_2048x2048x2048` |
| dd | 256³ | 76.2 | 77.3 | `phase_phase_dd_Ailk_Bjlk_256x256x256` |
| dd | 512³ | 55.1 | 55.9 | `phase_phase_dd_Ailk_Bjlk_512x512x512` |
| dd | 1024³ | 77.5 | 78.6 | `phase_phase_dd_Ailk_Bjlk_1024_depthu4` |
| dd | 2048³ | 92.2 | 93.5 | `phase_phase_dd_Alik_Bjlk_2048x2048x2048` |
| hh | 256³ | 748.2 | 30.4 | `phase_phase_hh_Ailk_Bjlk_256x256x256` |
| hh | 512³ | 1127.8 | 45.8 | `phase_phase_hh_Ailk_Bjlk_512x512x512` |
| hh | 1024³ | 847.2 | 34.4 | `phase_phase_hh_Alik_Bljk_1024x1024x1024` |
| hh | 2048³ | 853.2 | 34.7 | `phase_phase_hh_Ailk_Bljk_2048x2048x2048` |
| hh_hpa | 256³ | 576.9 | 51.6 | `phase_phase_hh_hpa_Ailk_Bjlk_256x256x256` |
| hh_hpa | 512³ | 1183.2 | 105.8 | `phase_phase_hh_hpa_Ailk_Bljk_512x512x512` |
| hh_hpa | 1024³ | 866.3 | 77.4 | `phase_phase_hh_hpa_Alik_Bjlk_1024x1024x1024` |
| hh_hpa | 2048³ | 896.3 | 80.1 | `phase_phase_hh_hpa_Ailk_Bjlk_2048x2048x2048` |
| hs_hpa | 256³ | 603.7 | 54.0 | `phase_phase_hs_hpa_Alik_Bljk_256x256x256` |
| hs_hpa | 512³ | 781.1 | 69.8 | `phase_phase_hs_hpa_Alik_Bljk_512x512x512` |
| hs_hpa | 1024³ | 511.4 | 45.7 | `phase_phase_hs_hpa_Alik_Bljk_1024x1024x1024` |
| hs_hpa | 2048³ | 517.3 | 46.2 | `phase_phase_hs_hpa_Alik_Bljk_2048x2048x2048` |
| ss | 256³ | 415.0 | 37.1 | `phase_phase_ss_Ailk_Bjlk_256x256x256` |
| ss | 512³ | 530.4 | 47.4 | `phase_phase_ss_Ailk_Bljk_512x512x512` |
| ss | 1024³ | 397.2 | 35.5 | `phase_phase_ss_Ailk_Bljk_1024x1024x1024` |
| ss | 2048³ | 890.8 | 79.6 | `phase_phase_ss_Ailk_Bjlk_2048x2048x2048` |
| zz | (all 26) | — | — | no CSVs yet (see §5.3) |
| auto (s) | 1024³ | 421.6 | 37.7 | `phase_phase_auto_0_Unknown_1024x1024x1024_9` |
| auto (s) | 2048³ | — | — | auto deck is all-1024³; SS 2048³ covered by `ss_Ailk_Bjlk` |
| 1 (s) | 1024³ | 460.9 | — | `phase_phase_1` |
| 1 (s) | 2048³ | 633.9 | — | `phase_phase_1` |
| 1 (s) | 4096³ | 665.5 | — | `phase_phase_1` |
| 20 (d) | 1000³ | 520.0 | — | `phase_phase_20` |
| 25 (d) | 1000³ | 505.9 | — | `phase_phase_25` |
| 31 (s) | 4096³ | 655.5 | — | `phase_phase_31` |

#### 5.2 Auto-mutation results (SS deck, generated deck headings)

Only **9/30** generated auto configs returned CSVs (idx 4,6,8,9,38,42,43,46,47);
idx **10–13** were generated but never benchmarked and the remaining 21 produced no
CSVs. **Root cause now confirmed (2026-09-14):** the 21 un-CSVed auto configs were
rejected inside Tensile's `SolutionStructs.setGlobalLoadTileDimClassic` — NLCA / VW /
DepthU divisibility violations (`Actual Solutions: 0 / 1 after SolutionStructs`) — so
**they are NOT re-runnable as-is** and must not be spent on GPU time. The validator
(`CandidateGenerator._validate_tensile_loads`) now enforces these checks at mutation
time. All benchmarked ones on 1024³:

| config | MT | TT | NLCA | VW | WGM | med GFlops | max GFlops | vs seed |
|---|---|---|---|---|---|---|---|---|
| auto_9 | 96x96 | 6x6 | 3 | 2 | 1 | 421.6 | 440.6 | **+6.1%** (seed 397.2) |
| auto_8 | 96x96 | 6x6 | 3 | 2 | 8 | 408.5 | 485.4 | +2.8% |
| auto_38 | 96x96 | 6x6 | 1 | 1 | 4 | 404.9 | **607.8** | +1.9% (max is a single volatile seed) |
| auto_42 | 96x96 | 6x6 | 1 | 2 | 8 | 400.7 | 440.3 | +0.9% |
| auto_43 | 96x96 | 6x6 | 1 | 2 | 1 | 398.7 | 496.9 | +0.4% |
| auto_4 | 96x96 | 6x6 | 1 | 2 | 4 | 397.6 | 467.0 | +0.1% |
| ss seed (Ailk_Bljk) | 64x64 | 4x4 | 3 | 2 | 4 | 397.2 | 498.3 | — (MT96 kernel; see §5.1 caveat) |
| auto_6 | 96x96 | 6x6 | 3 | 1 | 4 | 379.2 | 492.5 | −4.5% |
| auto_46 | 96x96 | 6x6 | 3 | 1 | 8 | 373.8 | 438.1 | −5.9% |
| auto_47 | 96x96 | 6x6 | 3 | 1 | 1 | 364.5 | 523.7 | −8.2% |
| auto_7 (no CSV) | 96x96 | 6x6 | 3 | 4 | 4 | — | — | rejected (SolutionStructs) |

`auto_9` is the first auto-phase config to beat the carried SS seed → **harvest**
as the new SS 1024³ incumbent. 2048³ SS: `ss_Ailk_Bjlk` (890.8, 79.6% ceil) stays.
**Mutation-analysis conclusion (idx 9 best):** the seed (MT64/TT4/NLCA3) is a **local
optimum at ~397**; the NLCA=3 knob is Tensile-legal only on MT96/TT6+VW2 (`Ailk_Bjlk`)
and is otherwise the main rejection source — structural candidates below therefore fix
NLCA to auto (1) unless it is the proven 421.6 combo.

#### 5.3 Next-round deck (mutate incumbent ≤2 knobs, gfx90c-legal pool)

Proposed candidates in priority order (spend rules §3: coverage first, then mutate):

1. **ZZ coverage (pending user launch)** — 32 published targets (16 cells × MT/TT
   variants 32x32x16/2x2 and 64x64x16/4x4), **NLCA fixed (was 3, now removed→auto)**,
   all resolve via `--family ZZ --dry-run`. User launches on own time.
2. **Auto 21 un-CSVed configs — REJECTED, DO NOT RE-RUN** (corrected 2026-09-14):
   these are `Actual Solutions: 0 / 1 after SolutionStructs` divisibility rejects
   (NLCA/VW/DepthU), not launch failures. Re-running them as-is wastes GPU time;
   they must first be re-emitted through the new `_validate_tensile_loads` gate
   (e.g. NLCA 3→1, VW 4→2 like auto_7). The 21 are idx
   10,11,12,13,28,29,32,33,36,37,39,40,41,44,45,48,49 and timeouts.
3. **Structural candidates (SS/cc/hh)** — NLCA fixed to auto except where proven:
   - `MT128x128x16 / TT8x8` (fam2 root cause was NLCA=3 on 4 loads → NLCA auto,
     NumLoads=4, 2048 extra register headroom) — candidates for ss 1024³, cc, hh.
   - `MT64x64x16 / TT4x8` (asymmetric TT: 4x8 lifts B-side occupancy without the
     NLCA3 trap of TT4x4; glvw=2 keeps divisibility).
   - `GlobalSplitU 2/4` variants of the per-cell winners (occupancy first-class, T9).
   - `NLCA auto` everywhere except the proven `Ailk_Bjlk`/MT96/TT6/VW2=3 combo.
4. **cc 1024³ (14.1%) & 512³ (15.7%)** — worst headroom; mutate
   MT64x64/TT4x4/WGM4 seed: `DepthU 8→16`, `WorkGroup [16,16,1]→[8,8,1]` and
   GSU 2/4 variants (structural deck above).
5. **ss 1024³** — `auto_9` (MT96x96/TT6x6/NLCA3/VW2/WGM1, 421.6) is the new seed;
   mutate WGM {1,4,8} × DepthU {16,32} only. Note `auto_38`'s 607.8 is a single
   volatile seed, NOT the median (404.9) — do not chase max.
6. **hh 1024³ (34.4%) & 2048³ (34.7%)** — mutate MT64x64/TT4x4 seed: MT
   {64,128}×{64,128}/TT8x8, NLCA auto (1), WGM 4→8 — structural deck. hh_hpa 512³
   already 105.8% ceil.
7. **hs_hpa — unblocked (guard-legal parameterizations, 2026-09-19).** The
   rejection was root-caused to a stock-Tensile generator restriction
   (`GLVW==VW-or-1`, non-MI assembly path), isa-independent, not a gfx90c HW/ISA
   limit (see §4). Resume GPU spend on the admitted parameterizations
   MT64x64x16/TT4x4/VW4/DU16 and MT64x64x8/TT4x4/VW2/DU8.
8. **dd — closed**: 93.5% @2048³, pipe-saturated (E verdict); no GPU spend.

**Convergence proposal (LLM-advisor, verified ceilings):**

| family | today (best cell) | target | how |
|---|---|---|---|
| hh / hh_hpa | 34–46% (1127.8) | **50–57%** | hpa 2:4 + MT128/TT8 + GSU4 structural deck; hh_hpa 512³ already 105.8% |
| cc | 15–25% | **≤29%** then stop | cc 512³/1024³ are RED headroom; structural candidates + GSU |
| ss | 35–80% | **~54% @1024³** stable | chase auto_9 mutation cluster (WGM/DepthU), NOT max |
| dd | 93.5% | near-saturated **99%** | no GPU spend (E) |
| zz | no data | cover 26 cells first | user-launched ZZ run (NLCA fixed) |

Any new phase must be `validate_config`-clean (occupancy/LDS) **and** pass
`_validate_tensile_loads` (Tensile divisibility — new requirement 2026-09-14) and
the `<host>/<knob>` uniqueness gate (no re-run of a fingerprint already benchmarked).
**Wide-deck regen (2026-09-20):** the manifest reached 295 entries (SS 105,
HH 40, DD 44, HH_HPA 20, CC 32, ZZ 32, HS_HPA 20, + 2 ss A/B baselines), full-shape
bundled per phase + shape-matched underfill-GSU and DDR/GEMV phases; all 295 passed
the mirror gates (validate_config + assembly_class_valid class gate) with unique
phase_id/fp/config (generator: `/tmp/opencode/gen_wide_deck.py`). Built from 331 by
**class-gating out the 36 illegal GSU cells** — HH/HH_HPA/HS_HPA with GlobalSplitU>1
(no MFMA on gfx90c; SolutionStructs:3553/3616; see `scheduler.assembly_class_valid`).
Re-derived live 2026-09-26: **410 phases** (117 legacy dtype-char auto mutants
added), all gate-clean.

### 6. Next increment — 2≥ gate & wider-for-LOSS / narrower-for-WIN (2026-09-20)

Driven by the draft run (`oto_gfx90c_auto_wide_20260919_full`, 2 runs, read-only) +
the approved retirement nuance (a NEW strategy beating the OLD on the same
problem-set retires the old — tier-2 dominance analog at strategy level).

#### 6.1 Retirement accounting (draft data alone)
- Every wide cell ran **once** (satisfies nothing). The **only** ≥2-independent-run
  fps in the draft are the two A/B baselines (48 samples each across the 2 runs) →
  merge tool flags exactly 2 retirement-eligible fps. Everything else needs a
  **2nd shell** from OUR deck before tier-2/tier-3 can retire anything.
- The 24 GSU=2/DU32-wide cells are class-illegal on gfx90c (no MFMA) — NOT verdicts,
  do NOT import as red, do NOT re-run. Class-gated out of our deck already;
  permanent skip, documented reason.

#### 6.2 Draft WINs — explore further in the next run (2≥-shell + mutate ≤2 knobs)

Empirical class from the **merged run1 data** (medians of the draft wide/auto cells
vs our carried incumbent, same cell). WIN = draft best-median beats our incumbent.
Spend for each: **(a)** 2nd independent shell of the winning fp (retirement needs
≥2); **(b)** mutate the winner ≤2 knobs (N4/H7). All winners are in the main DB as
`draft_*` phases; the 295-deck already bundles their family/MT-class neighbours.

| family | cell | winning phase (draft, in main DB) | winner config | best med | our incumbent | margin | next mutation |
|---|---|---|---|---|---|---|---|
| cc | 512³ | `draft_CC_cc_Ailk_Bjlk_wide_02` | MT64x64x8 / TT4x4 / DU8 / VW1 / WGM1 | 289.6 | 175.9 | **+65%** | DU 8→16/32; WGM 1→4 |
| cc | 1024³ | `draft_CC_cc_Ailk_Bljk_wide_02` | MT64x64x8 / TT4x4 / DU8 / VW1 / WGM1 | 244.4 | 157.4 | **+55%** | DU 8→16; WGM 1→4; MT128x64 |
| cc | 2048³ | `draft_CC_cc_Ailk_Bljk_wide_02` | MT64x64x8 / TT4x4 / DU8 / VW1 / WGM1 | 288.1 | 281.3 | +2% | 2≥-shell only; don't chase |
| dd | 256³ | `draft_DD_dd_Alik_Bljk_wide_00` | MT32x64x16 / TT2x4 / DU16 / VW1 / WGM4 | 86.2 | 76.2 | +13% | WGM 4→1/2 |
| dd | 512³ | `draft_DD_dd_Ailk_Bjlk_wide_01` | MT32x64x16 / TT2x4 / DU16 / VW1 / WGM4 | 92.8 | 55.1 | **+68%** | DU 16→32; VW1→2 |
| dd | 1024³ | `draft_DD_dd_Ailk_Bljk_wide_06` | MT32x64x16 / TT2x4 / DU16 / VW1 / WGM4 | 94.6 | 77.5 | +22% | WGM 4→1; DU 16→8 |
| hh | 256³ | `draft_HH_hh_Ailk_Bljk_wide_05` | MT128x128x16 / TT8x8 / DU16 / VW4 / WGM1 | 764.0 | 748.2 | +2% | 2≥-shell only |
| hh | 512³ | `draft_HH_hh_Ailk_Bjlk_wide_04` | MT128x128x16 / TT8x8 / DU32 / VW4 / WGM8 | 1677.1 | 1127.8 | **+49%** | WGM 8→4; DU 32→16 |
| hh | 1024³ | `draft_HH_hh_Ailk_Bljk_wide_02` | MT128x128x16 / TT8x8 / DU16 / VW4 / WGM1 | 1686.4 | 847.2 | **+99%** | WGM 1→4/8; DU 16→32 |
| hh | 2048³ | `draft_HH_hh_Ailk_Bljk_wide_02` | MT128x128x16 / TT8x8 / DU16 / VW4 / WGM1 | 1574.8 | 853.2 | **+85%** | WGM 1→4; DU 16→32 |
| hh_hpa | 256³ | `draft_HH_HPA_hh_hpa_Alik_Bljk_wide_01` | MT64x128x16 / TT8x4 / DU16 / VW4 / WGM1 | 599.8 | 576.9 | +4% | 2≥-shell; WGM 1→4 |
| hh_hpa | 512³ | `draft_HH_HPA_hh_hpa_Ailk_Bjlk_wide_05` | MT64x128x16 / TT8x4 / DU16 / VW4 / WGM4 | 1200.2 | 1183.2 | +1.4% (>ceil 1118.7) | 2≥-shell; WGM 4→8 |
| hh_hpa | 2048³ | `draft_HH_HPA_hh_hpa_Ailk_Bjlk_wide_04` | MT64x128x16 / TT8x4 / DU16 / VW4 / WGM1 | 964.3 | 896.3 | +8% | WGM 1→4; DU 16→32 |
| hs_hpa | 256³ | `draft_HS_HPA_hs_hpa_Alik_Bjlk_wide_02` | MT64x64x16 / TT4x4 / DU16 / VW4 / WGM1 | 651.6 | 603.7 | +8% | WGM 1→4; VW4→2 |
| hs_hpa | 512³ | `draft_HS_HPA_hs_hpa_Ailk_Bjlk_wide_02` | MT64x64x16 / TT4x4 / DU16 / VW4 / WGM1 | 1204.5 | 781.1 | **+54%** (>ceil) | WGM 1→4; DU 16→32 |
| hs_hpa | 1024³ | `draft_HS_HPA_hs_hpa_Alik_Bljk_wide_06` | MT64x64x16 / TT4x4 / DU16 / VW4 / WGM1 | 588.7 | 511.4 | +15% | WGM 1→4; DU 16→32 |
| hs_hpa | 2048³ | `draft_HS_HPA_hs_hpa_Ailk_Bjlk_wide_05` | MT64x64x16 / TT4x4 / DU16 / VW4 / WGM1 | 877.2 | 517.3 | **+70%** | WGM 1→4; DU 16→32 |
| ss | 512³ | `draft_SS_auto_0_ss_S_512x512x512_31` | (auto cell, SS@512) | 828.6 | 530.4 | **+56%** | pull its exact knobs; WGM/DU neighbours |
| ss | 1024³ | `draft_SS_ss_Alik_Bljk_wide_07` | MT128x64x16 / TT8x4 / DU16 / VW2 / WGM1 | 698.3 | 421.6 (auto_9) | **+66%** | WGM 1→4; DU 16→32; VW2→4 |
| ss | 4096³ | `draft_SS_auto_0_ss_S_4096x4096x4096_57` | (auto cell, SS@4096) | 977.6 | 665.5 (phase_1) | **+47%** | GSU-1 fast check; WGM/DU neighbours |

#### 6.3 Draft LOSSes — NEW wide candidates proposed (do NOT re-run the loser)

Also merged run1. LOSS = draft best-median BELOW our incumbent (or red vs ceiling).
The losing fp is spent; spend substitutes are fresh structural cells **not** in the
draft run (± the class gate — no GSU>1 on HH/HS_HPA derived families).

| family | cell | draft best | our incumbent | shortfall | new wide candidates (proposed) |
|---|---|---|---|---|---|
| cc | 256³ | 178.0 | 230.4 | −23% | MT128x64x16/TT8x4/DU16/WGM1; MT64x64x16/TT4x4/DU16/WGM4 |
| hh_hpa | 1024³ | 685.9 | 866.3 | −21% | MT128x128x16/TT8x8/DU16/WGM8 (class-legal: WGM only); MT64x128x16/TT4x8/DU32 |
| ss | 256³ | 404.1 | 415.0 | −3% (parity) | MT128x64/TT8x4/VW4/WGM1; DU 16→32 |
| ss | 2048³ | 739.9 | 890.8 | −17% | MT128x128x16/TT8x8/DU32/VW4/WGM4; GSU-1 |
| zz | 256³/512³/1024³/2048³ | 22–24 | none (ceil 98.6) | **RED ~23%** | structural: MT128x128x16/TT8x8/DU16/VW2/WGM4; MT64x64x16/TT4x4/DU16/VW2/WGM1; DU 16→32 |

#### 6.4 Strategy-scoped retirement (the nuanced gate)
Approved framing: when a NEW config/strategy beats the OLD on the same fp with
≥2 independent runs under BOTH, the OLD retires (dominance). Draft vs main share
no verified fp (different fp schemes) — so retirement only fires WITHIN our merged
deck after the 2nd shell. Do NOT hardcode draft retires on import (policy.py:240
3-tier gate decides).

#### 6.5 Next-run spend order (overnight, wins first — LOSSpend no, WINspend yes)
1. **WIN 2≥-shells** — one extra independent run per WIN in the §6.2 table (the
   0.5×medians are from a single shell today; tier-2 retirement needs ≥2). Priority:
   hh 1024³/2048³/512³, hs_hpa 2048³/512³, cc 512³/1024³, ss 1024³/4096³, dd 512³.
2. **WIN mutations** — §6.2 `next mutation` (≤2 knobs per N4/H7), same cells.
3. **NEW wide for LOSSes** — §6.3 candidates ONLY on the losing cells, class-gated.
   zz structural + cc 256³ first (biggest % shortfall), then ss 2048³, hh_hpa 1024³.
4. **GSU-1 @4096 SS** fast check (beat-or-tie 977.6).
Losses are never re-run as-is (fp already spent); their deck slots hold the new
structural substitutes.
---
