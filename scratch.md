# gfx90c — oto Long-Term Goal & Task Registry (scratch)

**Purpose:** survive session context compaction; enumerate the oto task
registry one-by-one. Source-of-truth owner: `claude.md` MD table. Prior-attempt
task history is NOT copied here — the sanctioned prior conclusions live in
`prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md` (measured results
only; never a pointer into prior working folders).

## Long-Term Goal

Replicate the ROCm `TensileLibrary` function families natively for gfx90c —
performing better than the gfx900 spoof, no more no less. gfx900 spoof = reference
floor, NEVER ceiling. Hardware: gfx90c (9,0,12) Cezanne APU, 7 CU, 448 lanes,
Wave64, no MFMA, single-rate INT8/BF16. FMA-pipe peaks @1800 MHz: FP32 1613, FP16
3226, BF16 1613, INT8 1613, FP64 101 GFlop/s.

**Method (ONE-SHOT, no LLM in the loop):** port_tensile.py runs phases from a
data-only phases.yaml manifest, benchmarks via Tensile's own CLI, persists
`json.dumps` payloads in SQLite `records` (INSERT-only; knowledge_base.md §10),
analyses (ruler-adjusted winner, %-of-peak ceiling,
adaptive repeat), decides the next candidates (harvest wins → mutate
winner-neighbours ≤2 knobs → append to manifest), terminates on convergence (no
RED cells below threshold OR budget exhausted), with cooldowns between GPU
phases. `--auto` loops run→analyse→decide until convergence. Worst case: the USER
manually calls an LLM to ADD candidate configs — that is ALL (a single canned
prompt, ≤5 recipe mutations, dropped into phases.yaml); never an in-loop LLM
consultation.

## Enumerated Task List (execute one-by-one)

- [x] T1 oto ecosystem: scratch.md, incomplete_work.md, adversarial_review.md, README.md, mapping.md, gfx90c_theoretical_limits.md.
- [x] T2 codify port_tensile.py per implementation_plan.md (§The Driver Architecture):
      registry.py / report.py / analytics.py / policy.py / scheduler.py / agent.py
      modules + data-only phases.yaml manifest; `json.dumps` + SQLite `records`
      INSERT-only. Fully verified and unit-tested.
- [x] T3 port the 28-family gfx900 footprint as NATIVE gfx90c phases — family
      decks per dtype+pattern {CC,DD,ZZ,HH,HH_HPA,HS_HPA,SS} × 4 patterns
      (phases.yaml re-derived to 410 phases 2026-09-26: SS 105, DD 44, HH 40,
      HH_HPA 20, HS_HPA 20, CC 32, ZZ 32, legacy auto 117).
- [x] T4 native-vs-spoof verdicts — SUPERSEDED by the dedicated reference floor:
      `--gfx900-reference` (`gfx900_ref_20260925_152942`, 2026-09-25: 2,285-kernel
      deck, 1,073 executed / 116 failed / 1,096 unattempted). The old
      `--phases 1 31` / `--phases 20 25` control-run windows are retired; the floor
      chain resumes via `--gfx900-reference --resume` and `--auto` gates on its
      completion.
- [ ] T5 deterministic candidate loop to convergence: harvest wins → mutate
      winner-neighbours ≤2 knobs → append to manifest; stop when no RED cells or
      budget exhausted.
- [x] T6 retain/verify stat + HTML tooling through the refactor: live chain =
      `analytics.py → report.py → gfx90c_results/acceptance_report.json/.html`
      (the `all_runs_dataset` → `make_results_md` → `make_report` → `results_derived.json`
      → `gfx90c_report.html` chain was superseded).
- [x] T7 single-phase kill ('s'/'q') + Ctrl+C process group termination + finite
      `--phase-timeout` default; retirement = single Tier-2 path
      (`policy.check_retirement_eligibility`), gated on ≥2 independent runs per cell.
- [x] T9 occupancy-as-objective: raise measured CU utilization toward the
      gfx90c_theoretical_limits.md §5 ceilings via right-sized GSU/WGM/MT/TT (objective tuning axis).
- [x] T8 correct peak-table prose: BF16 + INT8 = 1613 single-rate (not 3226), sourced
      from gfx90c_common.PEAK_GFLOPS.

## Docs-ecosystem audit — changelog→live-doc drift (round-1 analysis + round-2 fixes)

**Process (user-mandated, 2026-09-19):** Round-1 = go through `changelog.md`, find major
changes that would need doc-ecosystem reflection; record drift instances (append-only).
Round-2 = fix offenders ONLY after the analysis is fully complete; `changelog.md` fixes
are APPEND (new entry), other live docs state current fact (in-place per claude.md §8.1).

**Round-1 register (ANALYSIS COMPLETE):**

- **[MANIFEST] Ground truth (round-3 2026-09-26: re-derived live):** phases.yaml =
  **418 rows** as of 2026-09-27 (SS 105, DD 44, HH 40, HH_HPA 20, HS_HPA 20, CC 32,
  ZZ 40, legacy auto 117 dtype-char mutants) — 410 plus 8 gate-legal ZZ tile
  replacements after the occupancy gate (see `changelog.md`). Round-2's "304 rows
  (ss=52, cc=34, dd=34, zz=32, hh=64, hs=16, auto=72)" is superseded. Distrust any
  other count.
- **A — `.env.example` ships a dead probe-chain schema.** Code reads ONLY `TENSILE_ROOT`,
  `ROCM_PATH`, `ROCM_BIN`, `ROCM_LLVM_BIN`, `TENSILE_ASSEMBLER`,
  `TENSILE_ASSEMBLER_FALLBACK`, `TENSILE_VERBOSE` (changelog "[Native .env] 2026-09-19"
  removed all `*_CANDIDATES` chains), yet `.env.example:8-31` still documents
  `ROCM_PREFIX_CANDIDATES` / `ROCM_BIN_CANDIDATES` / `ROCM_LLVM_BIN_CANDIDATES` /
  `TENSILE_ASSEMBLER_CANDIDATES` / `TENSILE_ASSEMBLER_FALLBACK_CANDIDATES` → round-2 align.
- **B — "Scheduler mirror gap (pending)" now APPLIED.** scheduler.py `_validate_tensile_loads`
  models the `GLVW==VW-or-1` predicate (`:320`; 6 tests + 304/304 sweep pass). Still marked
  "pending/add": `implementation_plan.md:154-156`, `potential_configs.md:86-88` → round-2 flip
  to applied/verified.
- **C — Changelog top HS_HPA entry still says "Fix (pending)" ** (`:39-40`). Fix 2 landed;
  changelog is append-only → round-2 APPEND a new entry ("HS_HPA fixes applied": 16 cells →
  MT64x64x16 + mirror predicate), never edit the old bullet.
- **D — Dead reporting pipeline referenced as live.** No `all_runs_dataset.py`,
  `make_results_md.py`, `make_report.py`, `auto_retire.py` in repo; report.py writes
  `gfx90c_results/acceptance_report.json/.html`. Referenced live: `results.md:5`,
  `knowledge_base.md:105-108,338-340,381,409,416`, `implementation_plan.md:190,440-441,
  447,476,563,572-573`, `scratch.md:44-45` (T6 legacy chain), `analytics.py:9` → round-2 reword.
- **E — knowledge_base_final.md: NOT docs-ecosystem — RESOLVED 2026-09-20 by user directive.**
  It is the user's agent-context knowledge base (fed to config-gen / adversarial agents),
  deliberately OUTSIDE the docs governance ecosystem → **no `claude.md` §3 owner-table
  registration** (user vetoed E's registration half 2026-09-20). Not a hygiene offender.
- **F — results.md §1 ledger vs live DB.** "3 benchmark runs ... 96 valid ... phases 20,25,31"
  (results.md:26) vs `gfx90c_results/registry.db` = 1 run (run_20260915_001704 interrupted,
  phases_executed=1, 1652 records); root `registry.db` has no tables → round-2 verify + refresh.
- **G — Count drift vs the 304 manifest:** `implementation_plan.md:29` "230 targets",
  `potential_configs.md:233` "All 230 phases.yaml contraction entries", `incomplete_work.md:31`
  "240 candidate configs", `incomplete_work.md:84` "228 clean targets" → round-2 reconcile to
  304 / (232 family + 72 auto).
- **H — CpuThreads wording stale.** Code default = `min(os.cpu_count() or 8, 16)`
  (`port_tensile.py:704`; changelog "[Multi-Threaded Compilation] 2026-09-13"); 
  `implementation_plan.md:107-110` + `scratch.md:74-75` still say driver "falls back to
  sequential `CpuThreads: 1` while unfixed" → round-2 update the worked/unfixed framing.
- **I — README:136 / results.md:5 'q'-only auth phrasing.** `README:106` §3 says early-quit
  via `'q'` (acceptance_report written on `'e'`/`'q'`/Ctrl+C); README §1 table already has `'e'`
  → round-2 make §3 consistent with §1.
- **Clean (verified, do not reflag):** README arch counts = manifest; no shim/sitecustomize/
  legacy-suite greps in live docs; `_DEFAULT_TENSILE_ROOT` gone everywhere; `.env` gitignored;
  claude.md/kb/impl-plan `.env` path wording current (2026-09-19).

**Round-2 FIX task list (run only after analysis fully complete):**
- [x] F1 `.env.example` — DONE: `*_CANDIDATES` block dropped; native discovery
      (hipconfig + shutil.which) is documented with the live vars only (verified
      2026-09-26).
- [x] F2 `implementation_plan.md:154-156` + `potential_configs.md:86-88` — DONE:
      both say "Scheduler mirror gap — FIXED" (verified 2026-09-26).
- [x] F3 `changelog.md` — DONE: covered by the round-3 append entry
      "[Named workload cells + reference-floor A/B ...[...]]" 2026-09-26
      (HS_HPA mirror predicate + HPA case sensitivity land there).
- [ ] F4 Dead-pipeline rewording: results.md:5, knowledge_base.md (4 sites), implementation_plan.md
      (6 sites), scratch.md:44-45, analytics.py:9 → report.py acceptance_report pipeline.
- [x] F5 knowledge_base_final.md — CANCELLED 2026-09-20 (user: it is agent-context, not
      docs-ecosystem; do NOT register in claude.md §3). HS_HPA framing left to the file owner.
      framing (or freeze as of 2026-09-15 and note supersession).
- [ ] F6 results.md §1 — refresh run ledger to match gfx90c_results/registry.db facts.
- [ ] F7 Count reconciliation: 230/240/228 → 304 (232 family + 72 auto) in the cited docs.
- [ ] F8 CpuThreads framing update (implementation_plan.md E + scratch carryover).
- [ ] F9 README:106 §3 early-quit word consistency with §1 ('e').
- [x] F10 re-run live-doc hygiene grep (shim/legacy/CANDIDATES/hardcoded paths) at the end --
      DONE 2026-09-20: CLEAN (only append-only changelog history + frozen-source names;
      zero live cites of dead tools, zero CANDIDATES blocks, zero hardcoded paths).

## Fixed-state carried in (don't re-break)

- Ruler: bound-class median-anchored; missing controls → reported not inferred;
  no cross-dtype geo-mean leakage.
- Toolchain: AssertSizeMultiple fix reachable (phases 20/25 un-retired);
  16/17/19/22/23/24 H2-gated by PASS fingerprint.
- Telemetry: continuous whole-run sampler, header-in-CSV, `hwmon[0-9]*`,
  `power1_input` → `power1_average` fallback, Hz/µW/mC/%.
- Retirement: evidence-only single Tier-2 path via `policy.check_retirement_eligibility`
  (the 3-tier split + auto_retire.py script moved out; ≥2-run gate per cell).
- JSON: `json.dumps` is the only serializer across all four writers; no printf-JSON
  (prior §5.1 corruption lesson).

## Carryover OPEN items

- Reference floor completion: `gfx900_ref_20260925_152942` at 1,073/2,285 — resume
  the remaining 1,096 unattempted + 116 failed (1,212 phases) via
  `--gfx900-reference --resume`; `--auto` gates tuning on it. (The two scoped
  control runs `--phases 1 31` / `--phases 20 25` are superseded by the floor.)
- No out-of-footprint cells are ever scheduled; a finite `--phase-timeout` default
  still ships as generic runaway protection (implementation_plan.md §E).
- CU occupancy ≤3 in light phases = the performance headroom to claim (T9): raise it
  toward the §5 ceilings with right-sized GSU/WGM/MT/TT — objective, not hazard.
- Interactive single-phase kill ('s'/'q') end-to-end in the oto driver — RESOLVED (T7).
- CpuThreads parallelism — RESOLVED: default `min(os.cpu_count(), 16)` landed
  2026-09-13 (changelog "[Multi-Threaded Compilation]").
- Auto-retire trust gating — RESOLVED: single Tier-2 path, ≥2-run gate (T7).
- Peak-table prose 3226 for BF16/INT8 — RESOLVED (T8; single-rate 1613).

## Frozen prior conclusions (pointer to the two sanctioned MDs)

- Port mechanics DONE; performance = parity (0/11/0, ±5%); candidate suite 5W/10T/6L
  over 21 shared cells; only 6 new problem cells. Bests: FP32 1118.7@1024³, FP16
  2492.1@4096³, BF16 1108.5@2048³, FP64 98.6@1024³, INT8 881.2@2048³. Full detail:
  `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`. OPEN items carried
  via incomplete_work.md.

## Green light (already granted)

- refactor SUITE per implementation_plan.md (§The Driver Architecture) after user
  approval.
- `--auto` after the refactor lands and T4 completes.
- docs update as per tensiles_in_system_rocm.txt goal ("replicate ROCm
  TensileLibrary function families for gfx90c, performing better than gfx900
  spoof, no more no less").

## Guardrails (user-voice, keep exact)

- /caveman ultra responses. No root-folder pollution → throwaway scripts = /tmp.
- Ask before deleting files. Never delete benchmark data (changelog §0).
- 3 retirement kinds STARKLY different: redundant-exp vs dominated-sol vs
  theoretical-peak. Fix, no conflation.
- gfx900 = reference floor. Whole-library target. No "retire" for
  proximity-to-ceiling.
- Telemetry half-baked = complaint; implement properly or declare gap.

## Hypothesis-vs-authority gates (claude.md, keep exact)

- LLM output is hypothesis input, not authority; correctness gates performance.
- Avoid redundant experiments.
- Never silently weaken acceptance criteria.
- PoC in /tmp before touching the driver / port machinery (append-only data stays
  in `knowledge_base.md` §10).