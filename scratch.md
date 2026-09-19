# gfx90c — attempt2 Long-Term Goal & Task Registry (scratch)

**Purpose:** survive session context compaction; enumerate the attempt2 task
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

- [x] T1 attempt2 ecosystem: scratch.md, incomplete_work.md, adversarial_review.md, README.md, mapping.md, gfx90c_theoretical_limits.md.
- [x] T2 codify port_tensile.py per implementation_plan.md (§The Driver Architecture):
      registry.py / report.py / analytics.py / policy.py / scheduler.py / agent.py
      modules + data-only phases.yaml manifest; `json.dumps` + SQLite `records`
      INSERT-only. Fully verified and unit-tested.
- [x] T3 port the 28-family gfx900 footprint as NATIVE gfx90c phases — family
      decks per dtype+pattern {CC,DD,ZZ,HH,HH_HPA,HS_HPA,SS} × 4 patterns (240 candidate configs in phases.yaml).
- [ ] T4 run the two scoped control runs under FIXED math — `--phases 1 31`
      (COMPLETED: run_20260913_135333) then `--phases 20 25` (~2h); re-derive native-vs-spoof verdicts
      (ruler-adjusted, median-of-seeds, ties = parity) before full suite.
- [ ] T5 deterministic candidate loop to convergence: harvest wins → mutate
      winner-neighbours ≤2 knobs → append to manifest; stop when no RED cells or
      budget exhausted.
- [x] T6 retain/verify stats + HTML tooling through the refactor: all_runs_dataset
      → make_results_md → make_report → results_derived.json → gfx90c_report.html.
- [x] T7 single-phase kill ('s'/'q') + Ctrl+C process group termination + finite default PHASE_TIMEOUT_S;
      auto_retire emits retires only after ≥2 independent runs per cell.
- [x] T9 occupancy-as-objective: raise measured CU utilization toward the
      gfx90c_theoretical_limits.md §5 ceilings via right-sized GSU/WGM/MT/TT (objective tuning axis).
- [x] T8 correct peak-table prose: BF16 + INT8 = 1613 single-rate (not 3226), sourced
      from gfx90c_common.PEAK_GFLOPS.

## Fixed-state carried in (don't re-break)

- Ruler: bound-class median-anchored; missing controls → reported not inferred;
  no cross-dtype geo-mean leakage.
- Toolchain: AssertSizeMultiple fix reachable (phases 20/25 un-retired);
  16/17/19/22/23/24 H2-gated by PASS fingerprint.
- Telemetry: continuous whole-run sampler, header-in-CSV, `hwmon[0-9]*`,
  `power1_input` → `power1_average` fallback, Hz/µW/mC/%.
- Retirement: 3-tier, no hardcoded list, evidence-only; auto_retire.py idempotent
  (retirement logic moves into policy.py/agent.py; ≥2-run gate pending T7).
- JSON: `json.dumps` is the only serializer across all four writers; no printf-JSON
  (prior §5.1 corruption lesson).

## Carryover OPEN items (try again in attempt2)

- Two scoped control runs (`--phases 1 31`, `--phases 20 25`) — verdicts may move
  under fixed math.
- No out-of-footprint cells are ever scheduled; a finite `PHASE_TIMEOUT_S` default
  still ships as generic runaway protection (implementation_plan.md §E).
- CU occupancy ≤3 in light phases = the performance headroom to claim (T9): raise it
  toward the §5 ceilings with right-sized GSU/WGM/MT/TT — objective, not hazard.
- `CpuThreads: 1`: joblib/loky-vs-3.14 root-cause to SOLVE (pin/version fix), fallback
  sequential documented until solved — not dogmatic "mandatory".
- Interactive single-phase kill ('s'/'q') end-to-end in the attempt2 driver.
- 3 prior auto-retire records need ≥2-independent-run gating before trust.
- Peak-table prose still cites 3226 for BF16/INT8 → T8.

## Prior-attempt conclusions (frozen, pointer to the two sanctioned MDs)

- Port mechanics DONE; performance = parity (0/11/0, ±5%); candidate suite 5W/10T/6L
  over 21 shared cells; only 6 new problem cells. Bests: FP32 1118.7@1024³, FP16
  2492.1@4096³, BF16 1108.5@2048³, FP64 98.6@1024³, INT8 881.2@2048³. Full detail:
  `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`. OPEN items carried
  via incomplete_work.md (attempt2).

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