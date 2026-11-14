> **Prior-knowledge layer — sanctioned copy.** Copied verbatim from the frozen prior
> campaign (2026-09-04 → 2026-09-13). This and `archive/prior_research_archive.md` are the
> ONLY prior-campaign materials the attempt2 ecosystem references. Nothing here
> requires opening any other prior folder or file; results/learnings below are the
> "previous results" information base, while machinery mentions describe what was
> retired — not what attempt2 should build or read.

# INSIGHTS_CAVEMAN_ULTRA.md — prior-campaign full autopsy
### What actually happened across 9 days (2026-09-04 → 2026-09-13), what was really learned, and what attempt2 must know before it spends another GPU-minute.

> Plain words, hard numbers. Everything here is traceable in the live repo before
> archive: `run_gfx90c_suite.sh`, `docs/results.md`, `docs/potential_configs.md`,
> `proposed_fixes.md`, `changes_kb.md`, `incomplete_work.md`, `gfx90c_common.py`,
> `auto_retire.py`, `gfx90c_results/experiment_db.jsonl`,
> `gfx90c_results/benchmark_registry.jsonl`, `gfx90c_runs/run_*`. Cite keys:
> **R**=docs/results.md, **PC**=docs/potential_configs.md, **PF**=proposed_fixes.md,
> **CK**=changes_kb.md, **IW**=incomplete_work.md, **GC**=gfx90c_common.py,
> **AR**=auto_retire.py, **S**=run_gfx90c_suite.sh.

---

## 0. Scoreboard (the honest numbers first)

| Claim | Truth found | Evidence |
|---|---|---|
| "The port works" | YES — native gfx90c builds, libraries load, kernels run | Phase-0 gates 10/10 [OK]; end-to-end 48.0 GFlops @256³ on pristine tree |
| "The port beat the spoof" | **NO — parity, not wins** | cleanest same-run A/B: 0 win / 11 tie / 0 loss at ±5% (R §7 Q2) |
| "Candidates A–G improved things" | 4–5 real wins over 21 shared cells; **the real growth was coverage, not tuning** | PC §13.1; R §6.2/6.3 |
| "Later runs went faster" | No. Best FP16/FP32/INT8 came from **era-1 or the first-ever measurement** | R §6.1 |
| "The numbers moved between runs" | ±23–31% thermal/clock envelope on byte-identical configs; **never trust raw cross-run numbers** | R §5/§6, S:245 |
| "The in-tree 9-file patch was the port" | **It died. The port is 3 bookkeeping entries, not support code.** | this doc §3 |
| "The peak table is settled" | It was asserted in 3 conflicting ways; the single-rate claim (1613 for BF16/INT8) is the hardware truth, but the docs still contradict it in 3 places | this doc §2 |
| "~12h budget" | v5+ grew ~5× the era-1 benchmark volume, **40–41% of it re-running known shapes that only got worse/tied** | R §6.5 |

---

## 1. The 9-day arc (what the prior campaign actually was)

| When | What happened | Why it mattered |
|---|---|---|
| Pre-09-04 | Shipped gfx900 footprint decoded: 28 `.dat`, **3,066 kernels**, `{CC,SS,DD,ZZ,HH,HH_HPA,HS_HPA}×4` op-patterns; SS sink (659 in `Ailk_Bljk`); 459+ size-keys/family | The spec to replicate. stock library is a *defensive static mesh*, not a tuning artefact |
| 09-04 | prior campaign = **9-file in-tree Tensile patch** + v1 suite | Brought the platform up: `SupportedISA (9,0,12)`, `architectureMap gfx90c`, AsmCaps block, `AMDGPU.hpp gfx90c=912`, `PlaceholderLibrary`, Predicates, `HardwareMonitor.cpp`+`ResultFileReporter.cpp` crash-guards, `test_Common.py` |
| 09-04 | v3 bug: `amdclang++` not on PATH, `hipconfig --version` writes to **stderr** → exit 255 | Single most impactful fix: explicit toolchain paths + `ROCM_PATH` (CK §4.4) |
| 09-04 | v4 overnight 9–15; joblib/loky-3.14 `resource_tracker` traces in logs (benign then) | Later became a hard `CpuThreads: 1` requirement (Python 3.14) |
| 09-10 | era-2 probes: GLC probe `.s` triple mismatch (cosmetic); AsmCaps cache vs probe **True/True resolved**; first full 0–15 run PASS | Proved native identity: `HasMFMA False`, `HasGLCModifier True`, `SupportedISA True` |
| 09-10/11 | **v5 candidate sweep wired in (Phases 16–27), originals kept byte-identical, Phase 1/13 removed**; 4 full v5 runs (~185m each); **p20/p25 candC CRASHED every run** | Candidates verdicts in PC §13; bug: `AssertSizeMultiple: [1]` (int, not `[{}]`) |
| 09-11 | Ruler/throttle discovery: cross-run `±23-31%` envelope; old square/max ruler **flipped winner identity on 40 GEMV-class cells** | Rewrote measurement: per-(datatype, bound-class) ruler, median-anchored, no geo-mean fallback |
| 09-11 | Hardware ground truth corrected: FP64 peak **101** (not 202/1610) | The "98%" FP64 story |
| 09-12 | **v7 suite**: run-all + tier-1/2/3, thermal cooldown, adaptive repeats, stage-29 ceiling %-of-peak, flock; 20/25 un-retired after `[{}]` fix; peak table corrected to single-rate BF16/INT8 (1613) | The self-governing suite |
| 09-12 | Three self-terminating suite runs (172433/215546/215800) executed **no benchmark at all** — disposition+H2 gates dead-ended run-all | Exposed the "run everything every time" fallacy |
| 09-13 | Tensile reverted to pristine HEAD; bookkeeping entry-points identified (`SupportedISA`, `architectureMap`, AsmCaps); all phase configs get `HardwareMonitor: False` + `CpuThreads: 1` | prior campaign archived read-only; this file |

Verdict of the prior campaign as a *port*: **YES, carried out cleanly on vanilla Tensile; the port is 3 bookkeeping entries.**
Verdict as a *performance search*: **NO — parity with the spoof, 4–5 single-cell wins, all-time bests from era-1, and ~40% of GPU time re-benchmarking known shapes.**
That contradiction is the single most important thing attempt2 must design around.

---

## 2. The platform book (gfx90c ground truth) — and the PEAK controversy

### 2.1 Identity, settles every "is this arch supported?" question
- gfx90c = ISA `(9,0,12)` = Cezanne "Vega 7": **7 CU × 4 SIMD × 16 = 448 FP32 lanes**, 1 SE, **Wave64** (280 wave slots), LDS 64 KB/CU, L1 16 KB, L2 1 MB shared, coherent-host FALSE, fast-F16 TRUE, **`HasMFMA FALSE`**, max 1800 MHz. (CK §15.10 / MS)
- **Cannotonical invariant (CK §16):`gfx90c → (9,0,12) → gfx90c`.** Do not map it to gfx900 or vega10. Identity is native; nothing else is an "identity".
- All solutions are **VALU vector kernels**; there is no MFMA, no RDNA dual-issue, no WMMA.

### 2.2 The peak table that the codebase disagrees with itself about
Three conflicting answers exist in the tree as of archive:

| Where | FP32 | FP16 | BF16 | INT8 | FP64 |
|---|---|---|---|---|---|
| R §6.4 prose (2026-09-11, hand-written, stale) | 1613 | 3226 | **3226** | **3226** `v_dot4_i32_i8` | 101 |
| S header comment (line ~1017) | 1613 | 3226 | 3226 | 3226 | 101 |
| GC `PEAK_GFLOPS` (current) & S phase-29 `PEAK` | 1613 | 3226 | **1613** | **1613** | 101 |
| `convergence_gaps.txt` (run 085712, pre-correction) | 1613 | 3226 | 3226 | 3226 | 101 |

**The hardware truth (why 1613 wins for BF16/INT8):**
- **FP16 3226 is correct and measured.** `v_pk_fma_f16` dual-issues 2×FP16 per VALU op; FP16 hits 2461 @4096³ = **76%** (R §4: ~2.7× FP32 on-card).
- **INT8 has NO dual-rate pipe on gfx90c.** `v_dot4_i32_i8` dp4a is a GFX906/Vega20-era instruction — not present on gfx90c. INT8 runs through packed-int8-at-FP32-rate or worse. Evidence: int8 1024³ = 799 lands beside fp32 1024³ = 835 (GC:100–108). **INT8 peak = 1613, achieved 55%** (881 best).
- **BF16 accumulates through the FP32 pipe on this VALU** — BF16 best 1108 ≈ FP32 best 1119 = **69% of 1613 each**. It does NOT approach the FP16 pipe (R §4 insight 8 / PC §13.2 note 5). **BF16 peak = 1613.**
- **FP64 101** (1/16 rate, VALU-only); 98.6 achieved = **98%** — effectively saturated; FP64 tuning headroom is ~zero.

**Consequence (must fix in attempt2):** every BF16/INT8 "NEEDS NEW CANDIDATE" RED flag computed against 3226 is **~2× inflated**. Under the correct 1613 denominator those cells are 29–66% (BF16) / 30–55% (INT8) of pipe — near or above the realistic ~50% GEMM cap, NOT red. Re-derive the RED list with one consistent `PEAK_GFLOPS`.

**Genuinely unresolved (attempt2 measurement, not assertion):** a *same-run* FP32-vs-BF16-vs-INT8 identical-cube run is still missing. The cross-run datapoints (799-vs-835, 1108-vs-1119) sit inside the ±23–31% thermal envelope, so single-run repetition of those comparisons is weak evidence. My 09-13 attempt to produce it died on the platform (see §7.3).

### 2.3 The realistic roofline
- R §5/R §6.4: "Theoretical ceiling is a loose upper bound; **GEMM datatypes realistically cap near ~50%, not 100%**" (R:350).
- Achieved: FP32 69% / FP16 76% / BF16 69% / INT8 55% / FP64 98%.
- On this APU **DDR4/cache is not the bottleneck for large squares** (they're compute/scheduling-bound near their roofline); small/GEMV cells are DDR-bandwidth/latency-bound, so comparing decode cells against an FMA-pipe peak is meaningless by construction (S phase-29 `is_decode`).

---

## 3. Port anatomy: the 3 bookkeeping entries (why the 9-file patch failed)

### 3.1 Prior campaign's in-tree edits (all 9, all reverted 09-13)
1. `AsmCaps.py` — full `(9,0,12)` cap block
2. `Common.py` — `(9,0,12)` into `SupportedISA` + `gfx90c` into `architectureMap` + hip-version try/except
3. `AMDGPU.hpp` — `gfx90c = 912` enum
4. `PlaceholderLibrary.hpp` — lazy-load enum + glob
5. `Serialization/Predicates.hpp` — `enumCase gfx90c`
6. `HardwareMonitor.cpp` — graceful return (crash guard)
7. `ResultFileReporter.cpp` — `stod` try/catch for freq/power/temp
8. `ClientExecutable.py` — toolchain path join
9. `Tests/unit/test_Common.py` — anti-alias assertions

### 3.2 Why it was wrong as a *strategy* (even though each hunk was individually correct)
- **The C++ `toProcessorId("gfx90c")` → `Processor(0)` fallback is empirically fine.** `Processor` is used only in load-time predicates + hash equality; device and library both collapse to 0 consistently. The `AMDGPU.hpp` enum was never necessary.
- **The `HardwareMonitor`/`ResultFileReporter` C++ guards were fixing an env misconfig:** the client crashed `stoi`'ing empty APU rocm-smi clocks/power/temp. Killing that with config (`HardwareMonitor: False`) is clean; C++ hand-edit was hot-wiring around a metric the APU simply doesn't expose.
- **Forking the tree for every fix guarantees drift** — re-forking for the next hiccup becomes the deliverable.

### 3.3 What gfx90c ACTUALLY needs from Tensile (the whole port):
Unmodified Tensile already derives per-ISA AsmCaps **by test-assembling on the real clang** (`GetAsmCaps`, `IgnoreAsmCapCache`). gfx90c's caps are first-class → zero hand-tuning. It only lacks three **bookkeeping** entries, all in the Python coordinator, none in the assembler/codegen:

1. `supportedISA`: `(9,0,12)` absent → must append to **both** `defaultGlobalParameters` and live `globalParameters`, **because `Tensile.py` calls `restoreDefaultGlobalParameters()` before config-parse** — config-only ISA lands too late.
2. `architectureMap["gfx90c"]`: absent → `getArchitectureName('gfx90c') == None` → `TensileCreateLibrary` **silently drops all gfx90c logic**. This is the one that would ship an empty library while every log looks happy.
3. rolled caps cache: `(9,0,12)` seed from `(9,0,10)` — cache-only; live caps are derived.

### 3.4 THE ordering trap (why "just add it to the YAML" never worked)
Config merge runs **after** `populateCapabilities` (Common.py ~2525 vs ~2485). Code that builds caps tables reads the ISA list before your config exists. The **only** clean insertion point is import-time — exactly what `PYTHONPATH` `sitecustomize.py` gives you (untouched `assignGlobalParameters` is the hook). This single fact explains why every yaml attempt failed and why the shim is not a workaround but the correct port mechanism.

### 3.5 The shim (attempt2 lives on this)
`tensile_gfx90c_port/sitecustomize.py`: append `(9,0,12)` to both ISA lists; set `architectureMap["gfx90c"]`; wrap `getCapabilitiesCache` in **both** `Tensile.AsmCaps` and `Tensile.Common` (Common binds `from .AsmCaps import`). Env: `TENSILE_REPO_ROOT` + shim dir first on `PYTHONPATH` for **every** python call. Verified: Phase-0 gates 10/10 [OK]; tiny FP32 e2e RC=0 (library+client+CSV).

---

## 4. What 64 benchmark-bearing runs actually measured

Dataset: **40 run entries, 19 benchmark-bearing, 3 eras**; 771 benchmark records, 111 config-group cells, 66 unique problem cells (R §1, regenerated 09-13).

### 4.1 All-time bests (and who set them)
| dtype | best | cell | source |
|---|---|---|---|
| FP32 | 1118.7 | 1024³ | era-1/phase27 (R §1) |
| FP16 | 2492.1 | 4096³ | **run #1** `210202` (R §6.1: best FP16 came from the first data-bearing run) |
| BF16 | 1108.5 | 2048³ | era-1 |
| FP64 | 98.6 | 1024³ | phase23 candE |
| INT8 | 881.2 | 2048³ | era-1 |

**Reading:** no later run ever beat the first measurements. The suite was spending GPU time **validating, not improving**.

### 4.2 The winner-instability disease (the reason single runs are untrustworthy)
- **85/111 config-group cells (77%) are multi-winner**, 76 with >5% gap between candidate winners (09-13 registry re-tally).
- 69/84 groups flip winner identity run-to-run; only 15/84 keep one winner (R §3.1).
- Same config, same cell, same day, `±23–31%` raw GFlops (ALU class) vs `±6–19%` DDR (R §5).
- Fixed-context ruler shapes swing `±23-31%` byte-identically (fp32 4096³ 731→960; fp16 4096³ 2004→2461; bf16 2048³ 904→1108).
- **Result:** `CONVERGED_WINNER` in the DB is a median-of-seeds; winner is the max-with-caveats; "winner" without `NumBenchmarks ≥ 3` is a single-sample fluke risk.

### 4.3 Coverage was the real growth — exactly 6 genuinely new problem cells
FP16 1024³; FP32 1x2048 GEMV; FP32 4x2048 GEMV; candF batched/short-K ×3 (4x2048x64, 64x11008x1, 64x2048x16). The often-quoted "35 new records" is the **config-group** count, not new problem cells (R §6.3). **The only axis with confirmed gains in the prior campaign was finding new shapes** (PC §13.2 #1).

### 4.4 Throttle-adjusted verdict on the 49 byte-identical shared cells
Raw best-of-runs: 8 improved / 3 regressed / 38 noise — **wholly inside the thermal envelope**. Ruler-adjusted: **29 improved >5% / 1 regressed / 19 noise** (09-13 re-tally; R §6.1). No config-level regression ever existed — the apparent "regressions" were clock state.

---

## 5. Candidate verdicts (the search outcome, PC §13 / R §6.2)

| Cand | phases | verdict | deltas (throttle-adj, best-of-runs) |
|---|---|---|---|
| A sgemm | 16 | SPLIT → **harvest 2048³ +5.6%**; ties 3072³/4096³ | 2048³ +0.3…+5.6 |
| A hgemm | 17 | **LOSES all** −8/−9% | 2048/3072/4096 all L |
| B GEMV deeper | 18 | **WINS 32x4096x1 (+13.6%) & 64x4096x1 (+21.3%)**, stable across all 4 era-3 runs → **harvest** | 2x/8x/16x ties +1.5..+4.9 |
| C odd/rect+asym | 20/25 | **CRASHED every run** (`AssertSizeMultiple: [1]`); fix `[{}]` landed 09-12, scoped re-test pending | never benchmarked |
| D occupancy | 19 | split: **2048³ +14.1/+20.1% WIN** (harvest), 512/1024 lose −8.6/−19.7 | kill sweep, keep 2048³ |
| E bf16 | 22 | bf16 −13.6% (1024³); 2048³ tie +2.4 | withdraw bf16 claims |
| E fp64 | 23 | 0W/1T/2L; 1024³ ties +0.1 | fp64 has no headroom — stop spending GPU on it |
| E int8 | 24 | **int8 1024³ +18.3% WIN** (flipped from "tie" once rulers fixed — the ruler-fix lesson in one datapoint); 2048³ +3.2 tie | keep int8 1024³ |
| F batched/short-K | 21 | new regimes only (64x11008x1, 4x2048x64, 64x2048x16) | keep cells, harvest best |
| G schedule vars | — | `ScheduleName "isa"` was label-only; **no measured effect** | ignore |
| 26 seed repeat | 26 | re-confirms era-1 winners; variance reference | keep as telemetry |
| 27 transpose-ext | 27 | **1119 @1024³ FP32 new best** | keep |

**Totals over 21 shared cells: 5 wins / 10 ties / 6 losses.** Do not re-sweep losers (PC §13 "Do NOT re-sweep what already failed").

### 5.1 What the levers actually did (measured, sorted by effect)
1. **Finding new (shape) cells** — the only axis with confirmed gains.
2. **FP32 large-square**: winner is MT96x96x16 + NLCA3 (1536→4096³ ≈ 890–960), plus phase-27 MT128...1119@1024³. **Do not "controller-fix" it** (PC §13.2 #2).
3. **GSU only when the grid underfills 7 CUs**: 128x128x2048 prefers GSU1, 512³k at GSU2, 256³k at GSU8; GSU adds reduction overhead (R §4 #5).
4. **NLCA/EPS are access-pattern decisions on large tiles**, as important as VW/PGR; **PGR0 wins large FP16** (bandwidth, not latency).
5. **GEMV FP32 = VW1 + tiny TT** (MT8x32x32/16x32x16); FP16 GEMV prefers MT16x64x32 + TT2_8. Odd shapes → **MT96x96x16 + TT6_6 + NLCA3** (768/1000/1365³).
6. **Transpose**: NT best at 1024³ (873.6); TT best at 256³; LdsPad mostly avoided at large sizes.

---

## 6. The measurement science that had to be invented (and the bugs in it)

### 6.1 Ruler/throttle pipeline (GC `RULER`/`RULER_CLASS`/`throttle_factors`, R §6)
- Every config needs **fixed byte-identical ruler shapes**, one per **datatype × bound-class** (`ALU` vs `DDR`), median-anchored, per-run factor = `median(control)/run-control`.
- A shared cell is only **trusted** when the winning run of BOTH configs carries the matching ruler factor — no factor → **evidence gap, not an inference** (no geo-mean fallback, no cross-datatype max-anchor).
- `bound_class`: DDR iff batch==1 and (M≤128 or K≤64 or N≤64); everything else ALU.
- **The bugs it took three days to find:** phantom `"4096x4096x4096"` ALU shapes (fake ruler medians), geo-mean fallback leaking one DDR factor onto every datatype, `adj_cells` being a no-op. When fixed: **candE_int8 1024³ flipped +0.8% tie → +18.3% win** (PC §13 SUPERSEDED). `RULER_CLASS` deliberately has NO `(BF16,"DDR")`/`(FP16,"DDR")` entry — no such control cell exists in the dataset, and inventing one was rejected (GC:64-78).

### 6.2 Telemetry (v7, S:338+, R §6.1.b)
- One suite-wide sampler, 2 s cadence, tagged per `<phase,label>` window via a small state file, writes `telemetry.csv` **with a header** (the old `.hdr` sidecar "is dead").
- Legacies found: `.hdr` unit bug claimed kHz/mW while writing Hz/W (`TEL_LEGACY_COLS`); FAIL rows read `sclk=1800000000 busy=99` vs PASS rows `sclk=400000000` — a sensor/timing artifact (the wedge signature, not a real 1.8 GHz hold).
- sclk-ruler envelope (±0.0–14.3%) is much tighter than benchmark-ruler (±24.4–55%) — the clock window beats the config proxy, but only 7/40 runs carry it.

### 6.3 Statistics
- Winner = **MEDIAN-of-seeds** (seeds 3/6, `CONVERGED_WINNER_MEDIAN`, spread_ratio); max kept reference-only.
- Adaptive repeats (S:617+): super-sample when winning solution's CV across seeds > `ADAPTIVE_CV_WARN`(15%) or top-2 median gap < `ADAPTIVE_TIE_GAP_PCT`; one capped `_nb<N>` (NumBenchmarks doubled), hard budget per run.
- Tier-3 = theoretical peak is **never** a retirement or a claim (PF §0: "no peak assertion can retire work").

### 6.4 The three-tier model (AR, S)
- **Tier-1** redundant experiment = H2 exact-fingerprint skip, ON by default. An identical `(phase, fp)` with a PASS result is skipped (`h2_no_exact_rerun`); `H2_ALLOW` is the scoped A/B escape hatch; **opt-out `H2_ENFORCE_IDENTICAL_SKIP=0`**.
- **Tier-2** dominated config = `auto_retire.py`: retirement only when a head-to-head rule-adjust comparison shows one config beats another on **every** trusted shared cell (≥2 cells, ≥2 trusted shared), by MARGIN 1.05 on all and strictly on ≥1, with full cell-coverage by the winner; PROTECT set {0,1,2,3,4,9,10,11,13,14,15,26,27,28,29,30,31} never auto-retires rulers/floor/synthesis. Records are `(phase, fp)` keyed, **reversible by deleting the line**, never block a *new* fp.
- **Tier-3** peak/hardware floor — never a signal.

**Prior campaign's auto-retire output (must be revisited):** all three `action=retire` records came from one invocation `auto_retire:20260913_014131` — phase12 fp`387d25771a37e5de` dominated_by `132fa9a088a462df` (5 trusted cells), phase5 fp`286b940a045eee32` by `9673dab626748627` (4), phase6 fp`1570d91a6f069d11` by `d4a675effb0e31b7` (3). Given 77% winner instability and the ±23-31% envelope, a **one-campaign retirement is premature by construction**: require ≥2 *independent runs* per trusted shared cell + CV/quality gates, and treat "independent" as different-run-date evidence, not just different adjacent rows. (This was the plan; it did not yet land. **Attempt2 must.**)

### 6.5 Doc-grade discipline that made this analyzable
- Ownership split (**CL**): KB=baseline, CK=delta/history, IP=plan, PC=hypotheses/consultations, PF=bug history, RE/`docs/results.md`=data, AL*=narrative. Cross-referenced; stale prose is marked SUPERSEDED where remembered.
- **"Never delete benchmark data"** law (S:113-118): old data = the comparison baseline; registry+DB immutable append-only; a violating session is a project-blocking error.
- Phase numbers are reserved (gaps 13-15, 30) and **block order == PHASE_MANIFEST is asserted at every start** (S phase-order self-check) so the file can't silently drift from the intended order.
- flock on every shared jsonl/csv append (advisory pre-autonomy safety).
- Sequential `CpuThreads: 1` is not just crash-avoidance: threading the generator is UNSAFE anyway (tasks share globalParameters state; naive `ParallelMap` races OverwriteGlobalParameters between kernels).

---

## 7. Failure catalog (dead ends, in-order, root cause → outcome)

### 7.1 The era-1→shim flip (§3) — biggest dead end, best lesson
9 in-tree files → reverted → 3-line shim. Root cause: framing the port as "Tensile needs gfx90c support" instead of "Tensile needs 3 bookkeeping entries". **Every line rewritten in the tree was either unnecessary (C++ enum/processor), env-workaround (HardwareMonitor), or replaced by the import-time hook (Common).**

### 7.2 candC `AssertSizeMultiple: [1]` (PC/PF §10)
`AssertSizeMultiple` given a scalar int instead of a dict crashes every Phase 20/25 run (~154 s burned per run, forever). Forks must use `[{}]` / fixed keys. **A config-validation gate that cats every candidate config at import time would have caught this on day 1.**

### 7.3 The platform's GPU hang (new evidence, 09-13 probe, must become suite knowledge)
Attempting a same-run FP32/FP16/BF16/INT8 identical-cube (1024³+2048³) peak measurement through pristine Tensile + shim:
- **FP32: `HW Exception by GPU node-1 ... reason: GPU Hang` → client abort (exit 134) at ~483 s**, after the 2048³ exact. The APU driver wedged under sustained benchmark load.
- **FP16/general: `clientExit=1`, missing `00_Final.csv`** → `shutil.copy` `FileNotFoundError` at `BenchmarkProblems.py:409` — crash-before-results.
This explains the era-3 FAIL cluster (run 085712: p20-27,31, 9 phases) and why the suite evolved **30 s cooldowns, `setsid` process-group kill, `PHASE_TIMEOUT_S`, `SleepPercent`/warmup conventions**. **Attempt2 rule: treat 2048³-sustained runs as hang-risk; always launch GPU phases detached+killable; never let the client own your process tree.**

### 7.4 `HardwareMonitor` `stoi` abort (the C++ crash-guard that became a config line)
Unmodified client: `terminate ... invalid_argument ... stoi` → `ResultFileReporter.cpp:115-123` parsing empty rocm-smi clock/power/temp on an APU. **Fix = config `HardwareMonitor: False` in every phase**, no C++ hunk.

### 7.5 joblib/loky vs Python 3.14
`ValueError: Cannot register ... unknown resource type folder/semlock` kills generator children. `CpuThreads: 1` (config global) forces the safe sequential path (`Parallel.py` sequential fallback at threadCount≤1). See §6.5 for why this is also *correct*, not just crash-safe.

### 7.6 Toolchain traps
- `hipconfig --version` prints to **stderr** → parse it with `2>&1`; `amdclang++` must be on PATH (the v3 crash).
- `validateToolchain` searches ROCM_PATH bins, /opt/rocm/bin, /opt/rocm/lib/llvm/bin, PATH. "Found hipcc in a non-default ROCm location: /usr/bin/hipcc" = harmless noise.
- The GLC shell probe's `.amdgcn_target` triple mismatch is cosmetic only (Python probe + baked cache agree, `HasGLCModifier=True`); PF §6B/6C fix is pending but zero benchmark impact.

### 7.7 Benign log monsters that cost analysis time
- "Generating kernel source resulted in error 3" (12× in phase 4) = `overflowedResources=3` for non-MFMA half kernels → kernel not emitted, phase unaffected ("likely low-performing so likely not worth optimizing", `TensileCreateLibrary.py:94`).
- "Kernel file context manager opened without any kernel files" = cosmetic, fired in every phase under `MergeFiles: False`.

### 7.8 Self-terminating runs (the "wasted days")
`run_20260911_172433 / 215546 / 215800` ran **zero benchmark phases** — the disposition+H2 gates had retired everything, so a "full" run was a no-op costing GPU time+budget (~40%/run re-bench). Lesson: **a run gate must prove it will do something before it starts**.

---

## 8. Warts found while writing this (loose ends attempt2 must reconcile)

1. **Peak table contradicts itself in 3 files** (§2.2) — one `PEAK_GFLOPS` (already single-source in `GC`) must be the ONLY authority; stale prose blocks and the old `convergence_gaps.txt` should be regenerated, not edited by hand.
2. Stale prose "INT8 ≈ 3226 (`v_dot4_i32_i8`, 4-wide)" is **hardware-wrong for gfx90c** (no dp4a) — see §2.2; it's asserting an instruction this chip cannot issue.
3. The 48.0 GFlops @256³ shim-validation number (EnqueuesPerSync 1 / Syncs 1, single bench) is **not comparable to suite numbers** (EnqueuesPerSync 5/Syncs 3, NumBenchmarks 3): same cell measured 421.8 in suite phase-6. **Smoke numbers must never be entered into the DB unlabeled.**
4. Telemetry unit bug (Hz/W vs header kHz/mW) and the FAIL-row `sclk=1800000000/busy=99` artifact — normalize or drop before the sclk ruler is trusted for verdicts.
5. The registry HP "latest status per phase" shows many FAILs for p21-27,31 (run 085712 crash cluster) — those phases DID produce earlier data; status-by-run ≠ status-by-config. Pending a per-config view.
6. A 13824³ cell in a candidate run grinds ~2.5 min/solution — kept only because `PHASE_TIMEOUT_S` (default **0 = off**) can stop it. Attempt2 must set a finite budget; there is no evidence any such cell is in the shipped gfx900 footprint (SS/SP/.. sizes top out far lower).
7. `make_results_md.py`/`make_report.py` both consume `GC.PEAK_GFLOPS` correctly; the stale prose is the only offender — a single CI-ish "regenerate + diff prose" step kills the class of bug entirely.

---

## 9. attempt2 rules (each grounded in a measured fact above)

1. **Port = shim, never a fork.** Three injections, pristine tree. Any future needed injection goes in `sitecustomize.py` (or a sibling siteone, with the suite exporting `PYTHONPATH`+`TENSILE_REPO_ROOT` for EVERY python call).
2. **One peak table.** `gfx90c_common.PEAK_GFLOPS` (FP32 1613 / FP16 3226 / BF16 1613 / INT8 1613 / FP64 101) is the only authority; regenerate every report + RED list from it; purge the 3226-for-BF16/INT8 prose everywhere.
3. **Fix measurement before adding seeds.** Same-run ruler cells, median-of-seeds, ≥3 NumBenchmarks, throttle-adjusted comparisons only. Cross-run raw numbers are triage, never verdicts.
4. **Retire nothing on one campaign.** Require ≥2 independent runs per trusted shared cell + CV/quality gates; revisit the 3 existing retire records under that rule.
5. **Coverage over tuning.** The only measured wins are new-shape cells. Spend GPU on cells that have NO winner (the empty-cell set, Phase 31 fill, candF regimes) before re-solving cells that do.
6. **Keep the roaming line between benchmarks and claims:** a native-vs-spoof (or native B-vs-native A) verdict needs one same-run A/B pair, not best-of-history (R §7 Q2).
7. **Hang-safety as a first-class feature:** `setsid` + process-group kill, 30 s cooldowns, `PHASE_TIMEOUT_S` finite (default off = a bug), and the tiny notation that 2048³-sustained can wedge this APU.
8. **Config gate before GPU:** a validator that cats every generated candidate config (catches `AssertSizeMultiple: [1]`-class errors) and refuses known-bad forks. One minute of CPU per run saves hours of hang-diagnosis.
9. **No re-sweep of losers** (PC §13). Mutate the per-cell winner by a few neighbours; harvest first, then close the loop with one synthetic library; validate ≥1024 elements.
10. **Keep the discipline artifacts** (append-only registry/DB; phase-order self-check; protection sets; doc ownership) — they are what made this retrospective possible at all.

---

## 10. TL;DR (five lines)

- The port is a 3-line import hook; everything else was reverted as env-noise or unnecessary.
- The platform is a 448-lane single-VALU Vega7: single-rate BF16/INT8 (1613), dual-rate FP16 (3226), FP64 98% saturated — and it hangs if you benchmark 2048³ sustained without a kill switch.
- Cross-run numbers lie ±23-31%: the rulers were the real deliverable, and the rulers were buggy for three days.
- Candidates yielded parity + 4-5 wins; the only durable growth was 6 new-shape cells and a pile of methodology.
- attempt2's job is not "port faster", it is "measure honestly, fill empty cells, and prove one same-run win against the spoof floor".