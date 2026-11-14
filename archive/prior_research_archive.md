> **Prior-knowledge layer — sanctioned copy.** Copied verbatim from the frozen prior
> campaign (2026-09-04 → 2026-09-13). This and `archive/prior_insights.md` are
> the ONLY prior-campaign materials the attempt2 ecosystem references. Nothing here
> requires opening any other prior folder or file; results/learnings below are the
> "previous results" information base, while machinery mentions describe what was
> retired — not what attempt2 should build or read.

# RESEARCH_ARCHIVE.md — prior-campaign supporting material
### Companion to INSIGHTS_CAVEMAN_ULTRA.md. Kept here so attempt2 has the raw narrative even after live-repo churn. Cite keys: R=docs/results.md, PC=docs/potential_configs.md, PF=proposed_fixes.md, CK=changes_kb.md, IW=incomplete_work.md, GC=gfx90c_common.py, S=run_gfx90c_suite.sh.

---

## A. How the whole setup evolved over time (the doc bones)

### A.1 Suite version spine (S, CK)
- **v1** (09-04): phases 0–15, era-1 originals, `order00b:9,0,12` yaml quirk.
- **v3**: toolchain crash fix — explicit `amdclang++`/`hipcc`/`rocm-smi`/`python` paths, `ROCM_PATH` export (CK §4.4). The most impactful single fix of prior campaign.
- **v4**: 09-04 overnight runs 9–15; joblib/loky resource_tracker traces first seen (benign while Python 3.13).
- **v5** (09-10/11): candidate sweep wired as Phases 16–27; Phases 1 and 13 removed; originals kept byte-identical; first 4 full runs (~185m each). p20/p25 (candC) crash every run.
- **v6**: (transitional) ruler/throttle work.
- **v7** (09-12): run-all + tier-1/2/3 gates, thermal cooldown, adaptive repeats, 30 s cooldowns, Phase-29 100%-ceiling stage, flock, per-load telemetry, phase-order self-check, `convergence_gaps` with corrected peaks. Current shipping version as archived.
- **(09-13):** pristine Tensile HEAD restored; all 25 phase configs get `HardwareMonitor: False` + `CpuThreads: 1`. Native in-tree gfx90c bookkeeping landed 09-19 (see `changelog.md`).

### A.2 Phase inventory
- **0** sanity gates (10 `[OK]`); **1** baseline (removed at v5); **2** fp32; **3** fp16; **4** GEMV; **5–7** fp32/transpose variants; **9** bf16; **10** fp64; **11** int8; **12** aux; **13–15** (existed in 0–15 era, removed); **16** candA sgemm; **17** candA hgemm; **18** candB GEMV-deeper; **19** candD occupancy; **20** candC run; **21** candF batched/short-K; **22** candE bf16; **23** candE fp64; **24** candE int8; **25** candC re-run; **26** seed-repeat; **27** transpose-ext; **28** synthesis; **29** ceiling %-of-peak; **30** reserved; **31** prepend for synthesis harvest.

### A.3 Doc-ownership split (the CL scheme, baked into the suite's `changes_kb`/`incomplete_work`)
KB=baseline, CK=delta/history, IP=plan, PC=hypotheses/consultations, PF=bug history, RE/docs/results.md=data, AL*=narrative. The three "thou-shalt" laws: never delete benchmark data (S:113-118); append-only registry+DB; phase-number reservation + order self-check at every suite start.

---

## B. Empirical outcomes (statistical truth, with the recency caveat)

### B.1 Frames
- 40 run entries, 19 benchmark-bearing, 3 eras; 771 benchmark records (09-13 regenerated), 111 config-group cells, 66 unique problem cells; 85/111 (77%) config-groups are multi-winner; 76/111 have >5% gap between their candidate winners.
- 49 byte-identical shared cells across the A–F sweep: **raw best-of-runs** 8 improved / 3 regressed / 38 noise (inside ±23–31% envelope); **throttle-adjusted** 29 improved / 1 regressed / 19 noise.
- Cross-run raw deltas for byte-identical configs: ALU class ±23–31%; DDR class ±6–19%. Same-config SGEMM 2048³ swings 695→818; HGEMM 2002→2344.
- Winner identity flips between runs in 69/84 shared-coverage groups; only 15/84 keep a single winner.
- **Recency caveat:** the R/registry counts regenerated 09-13 (771/111/66) supersede the older §6/§5 frames (540 records/55 cells, 09-11). Where a count changed it is the regeneration, not the conclusions.

### B.2 All-time bests (R §1/§6.1)
FP32 1118.7 @1024³; FP16 2492.1 @4096³ (from run #1, 210202); BF16 1108.5 @2048³; FP64 98.6 @1024³; INT8 881.2 @2048³. Best FP16/FP32/INT8 all from era-1/first measurements — later validation spending never improved them.

### B.3 Roofline vs reality
- Realistic GEMM cap ~50% of theoretical ceiling, not 100% (R:350). Achieved: FP32 69%, FP16 76%, BF16 69%, INT8 55%, FP64 98%.
- DDR-bound cells (batch==1, M≤128 or K≤64 or N≤64) must be judged by bandwidth rulers, not the FMA peak (S:3745, GC:40-48).

---

## C. Tooling / machinery evolution (the guardrails)

### C.1 Ruler/throttle pipeline (GC:58-180, R §6.1)
- Per (datatype × bound-class) fixed ruler shapes, byte-identical control; `throttle_factors = median(control)/run-control`; only shared cells with a matching ruler factor on BOTH runs are "trusted".
- Iterations: max-anchor → cross-datatype geo-mean (leaked DDR factor) → per-class median (final). No geo-mean fallback; no fabricated rulers (GC:64-78).
- Bugs found along the way: phantom 4096⁴ ALU shapes; geo-mean fallback; `adj_cells` no-op. Fixed → candE_int8 1024³ flips from "tie" to +18.3% WIN.

### C.2 Telemetry (S:338+, R §6.1.b, PF §9)
- Single suite-wide sampler, 2 s cadence, window labels via tiny state file, header-bearing `telemetry.csv` (old `.hdr` superseded). 7/40 runs carry telemetry (~35,061 samples).
- Legacies: unit bug (Hz/W written, kHz/mW header), FAIL rows `sclk=1800000000 busy=99` vs PASS `sclk=400000000` artifact. sclk ruler ±0.0–14.3% vs benchmark ruler ±24.4–55%.

### C.3 Tier model + auto_retire (AR, S:177, S:523-624)
- Tier-1: H2 identical-fp skip (default on; `H2_ENFORCE_IDENTICAL_SKIP=0` opts out; `H2_ALLOW` scoped).
- Tier-2: dominance retirement by `auto_retire.py` (MARGIN 1.05, ≥2 trusted shared cells, strict+weak conditions, full cell-coverage, PROTECT set spares rulers/spoof/synthesis). Records reversible by line deletion.
- Tier-3: peak never retires anything.
- prior campaign wrote 3 retire records in one invocation `auto_retire:20260913_014131` (phase12→132fa9a088a462df, phase5→9673dab626748627, phase6→d4a675effb0e31b7). Premature per the ≤77%-stable winners; attempt2 must require ≥2 independent runs per trusted cell.

### C.4 Adaptive repeats (S:617+)
CV>15% across seeds, or top-2 median gap < 0.005, triggers one capped `_nb` super-sample (NumBenchmarks doubled), hard budget per run, all rows registered (never deleted).

### C.5 Crash/hang guardrails (evolved reaction to §D failures)
30 s cooldowns; `setsid` process-group kill; `PHASE_TIMEOUT_S` (default 0 = OFF — attempt2 must set finite); `SleepPercent` warmup; detached GPU phases; throwaway scripts confined to /tmp; controlled GPU experiments require explicit user go-ahead.

### C.6 Operational facts of the machine
- `/` at 100% (~7.8G free) during archive → only text writes possible; raw 34G of run data stays in live repo (gfx90c_runs/), archive excludes build binaries (829MB→excluded, 1.2G archived, 6,944 files).
- Concurrency: lock on every append; sequential `CpuThreads: 1` because the generator shares globalParameters state (ParallelMap races OverwriteGlobalParameters between kernels).

---

## D. Failed experiments catalog (each: symptom → root cause → outcome)

1. **v3 toolchain crash** — exit 255 / empty isa → `hipconfig --version` writes stderr; paths absent. Fix: explicit toolchain env. Outcome: build stable.
2. **9-file in-tree patch sacrificed** — worked, but forked-the-tree drift; the port is bookkeeping, not support. Outcome: pristine HEAD restored; the port is now 3 bookkeeping entries in `Common.py`/`AsmCaps.py` (09-19).
3. **candC crash** — `AssertSizeMultiple: [1]` int vs dict every run → `[{}]` fix 09-12, scoped `H2_ALLOW="20 25"` re-test pending.
4. **Act: GPU Hang (runtime evidence, 09-13 probe)** — FP32 2048³ benchmark: `HW Exception reason :GPU Hang`, client abort, exit 134 after ~483 s; FP16/gen: missing `00_Final.csv` → `shutil.copy` FileNotFoundError at BenchmarkProblems.py:409. Explains era-3 FAIL cluster (run 085712 p20-27,31). Outcome: sustained 2048³ = hang risk; always detached+killable.
5. **HardwareMonitor stoi abort** — empty APU clocks/power/temp → fixed by `HardwareMonitor: False` config (C++ guards reverted).
6. **joblib/loky vs Python 3.14** — `unknown resource type` kills children → `CpuThreads: 1` global (also correctness, see C.6).
7. **order00b yaml quirk** — benign; superseded.
8. **GLC shell-probe triple mismatch** — `.amdgcn_target` cosmetic; Python probe + baked caps agree (`HasGLCModifier True`). PF §6B/6C zero benchmark impact.
9. **Self-terminating runs** — 172433/215546/215800 executed zero benchmarks (everything retired by gates). Outcome: run-all gate must prove it will run *something*.
10. **Peak-context polarity issues** — canonical DCOT and a manufactured 13824³ runaway (2.5 min/solution) both handled by phase markup + timeout (D-cat conventions). 13824³ not in shipped gfx900 footprint sizes.
11. **Spoof/ven-van mis-map drift** — the nominal 9-ISA family parity achieved in era-1 but raw counts drift; requires periodic re-assert. (x9, x8.)
12. **The benchmark volume explosion** — v5 ~5× era-1 work, 40–41% re-benchmarking known shapes (worse or tie). Attempt2: coverage-first scheduling.

---

## E. What attempt2 should preserve vs throw away

| Keep (proven) | Throw (dead end) |
|---|---|
| Native in-tree bookkeeping patch as THE port | 9-file in-tree patch |
| `GC.PEAK_GFLOPS` as single peak authority | 3226-for-BF16/INT8 prose in R §6.4, S header, old convergence_gaps |
| Ruler/throttle with per-class median-mean | max-anchor, geo-mean fallback, `adj_cells` no-op |
| Tier gates + PROTECT + reversible retire | one-campaign auto-retire (needs ≥2 independent runs) |
| Append-only registry/DB + order self-check | self-terminating run-all without "will it run" proof |
| Empty-cell fill / Phase 31 synthesis harvest | re-sweeping losers (PC §13), GEMV/batc odd-49 config noise |
| Same-run A/B for every verdict (R §7 Q2) | best-of-history comparisons (thermal envelope) |
| Detached+killable GPU, finite PHASE_TIMEOUT_S | untimed 2048³-sustained benchmarks |
| `CpuThreads: 1` sequential correctness | lock-free parallel generator writes |