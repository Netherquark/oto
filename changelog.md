# Changelog — Tensile gfx90c port

The SINGLE changelog/evolution log for the project. One fact, one canonical home:
milestone + rationale entries land here; they are never re-created elsewhere.
Prior-campaign conclusions are sourced (never copied) from the two sanctioned
prior MDs: `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

This file records project milestones and the prior-campaign → attempt2 evolution
narrative, NOT the active implementation state (that is `implementation_plan.md`)
and NOT the experimental data (that is `results.md`).

- **2026-10-10 — agentic harness: `harness/resolve_cells.py` formalised (repo-homed).**
  The per-cell winner resolver that generated potential_configs.md §2's evidence
  table was polished out of `/tmp/opencode/resolve_cells.py` + verdicts dump and
  integrated as `harness/resolve_cells.py` (read-only CPU tool; `--base-dir`,
  `--json/--text/--tsv`, module-style like kernel_db/regression_matrix). Additions
  over the ad-hoc version: winner-run-first phase-config resolution (winner run's
  `configs/*.yaml` → registry `phases` → any-run yaml → kernel_db row — no more
  reliance on alphabetic glob order), floor winners under the standing
  median-primary `_best` predicate, per-cell % of ceiling + % of theoretical,
  provenance metadata, and stable caches committed at
  `gfx90c_results/analysis/cells_resolved.{json,full.txt}` (byte-identical
  winners/values/knob surface to the §2 table: 6129 yamls / 8480 keys / 1113
  phases / 38 cells). `harness/__init__.py` → v1.1.0 with resolve_cells in
  `__all__`; README workflow gains a "resolve per-cell winners" step;
  `tests/test_resolve_cells.py` guards deck parity, report agreement, winner
  resolution and HPA-floor tolerance. potential_configs.md's "evidence machinery
  in /tmp until formalised" note now points at the repo-homed tool + caches.

- **2026-10-10 — potential_configs.md comprehensive rewrite: BLAS-8 complex frame, resolver-final winners, priority re-sequence.**
  The candidate-deck document was rewritten end-to-end (old 1429-line version
  archived at `archive/potential_configs.pre_rewrite_20261010.md`). Three
  load-bearing changes: **(1) Complex accounting corrected to BLAS-8.** The old
  file's "÷4 ALU wall" (CC 403.25 / ZZ 25.25, "81%/96% of wall") counted 2 flops
  per complex MAC, but Tensile's complex MAC is four real FMAs = 8 BLAS flops
  (`MAC_F32C.py`/`MAC_F64C.py`). Under BLAS-8 the honest ceilings are the FP32
  peak (CC 1613) and FP64 peak (ZZ 101); the user's CC/ZZ complaint numbers are
  correct and CC/ZZ are genuinely M3-undertuned at 20–24 % theo with ~3.5–4×
  in-deck headroom (→ SS/DD-class issue ≈ CC 1187 / ZZ 95–98) — not near a wall.
  **(2) Split-complex corrected:** reported split = (4/3)·R_real → CC ≈1513,
  ZZ ≈127–131 (was "÷3 → ≈378"). 3M wins the GEMM count (4→3) with an
  O(MN+MK+KN) combine, not the per-MAC instruction count. **(3) Winner configs
  re-resolved per cell** from the registry (`resolve_cells.py`: 6129 yamls, 8480
  keys) — 19 WIN / 18 TIE / 1 LOSS confirmed; corrections incl. CC:512 winner
  WGM4+NLCA1 (not WGM8), CC:256 native best = small MT32x32 (193.8) vs floor
  MT64x64 (212.3, sanctioned steal §7, bar ≥214), SS:512 VW4 landed (WIN +10.4),
  SS:4096 = DU16, ZZ:512/1024 = DU16+PGR=False, HH:256 = MT32x64. Corpus line
  fixed: 10 native runs + 2 locked floor runs (kernel_db 11 runsets; overnight
  20261009 folded via report verdicts only). Research anchors updated:
  `kernel_tuning_research.md` Sources now point to `complex_gemm_research_brief.md`
  (the citation anchor for §1/§8.2). `command.txt` re-sequenced: CC/ZZ M3 campaign
  first, then CC:256 steal, SS GSU, HH alternates, DD GSU, WGM probe, split-complex
  escalation. Any later doc quoting "81–96% of an ALU wall" for CC/ZZ, "WGM8 is
  the CC lever", "≈378 split", the ÷4 ceilings, or an "8 native runs" corpus is
  stale — see the rewrite's §1/§2/§3.
- **2026-10-10 — Overnight-run triage: report crash + false "HPA above ceiling".**
  Fixes from the first post-overnight triage after the DB-hooked overnight run
  (`run_20261009_205427`, ~7 h 41 m, 351 phases + 5 swizzle probes): (1) **report
  generation crash** — `_ab_records_from_csv` concatenated a `Path.glob`
  generator with a `list` when the probe_* 2_BenchmarkData scan was added
  (`TypeError` at 04:35; report now regenerates: 19 WIN / 18 TIE / 1 LOSS,
  7333 cells, 8 runs); regression test `tests/test_report_probe_glob.py`.
  (2) **false HPA anomaly** — the acceptance report showed HH_HPA/HS_HPA at
  230-246% of their FP32-rate 1613 ceiling with byte-identical bodies. Root
  cause: `_compute_family_coverage` matched `a.family == fam_lower`, but the
  Oct 9 typecode-first attribution stores the family UPPERCASE, so both HPA
  buckets fell through to the dtype fallback ('H') and reported the **packed-FP16
  HH** kernel median (2749.285, healthy at 85% of HH's real 3226 ceiling) as HPA
  "performance" — physically impossible for `v_fma_f32`. Match is now
  case-insensitive: HH_HPA 1447.0 (89.7%), HS_HPA 1441.2 (89.3%); regression
  tests `tests/test_report_family_case.py`. (3) **main-transcript capture** —
  the harness writes no main log by design (`logs/telemetry.csv` + per-phase
  logs only); `command.txt` now shows the piped invocation
  (`… --live off | tee overnight_$(date +%Y%m%d_%H%M).log`).
- **2026-10-09 (night #2) — DB-hooked mutator overhaul, Group C swizzle complete, 10+ h overnight sizing, proposal rewrite.**
  The Option H mutator overhaul landed: `db_mutator.py` hooks synthesis to
  `kernel_db.json`, emitting wide + narrow + direction mutants for every active
  (below-ceiling) cell. Mutants carry `bypass_identical_skip` (the auto-skip
  never applies to a mutation) and are novelty-checked before emission, so the
  arm never re-measures a tried config and never decays to a trickle. The
  Group C (LdsPad/Swizzle) status is now fully implemented: the backwards
  `StaggerUStride` gate in `scheduler.py` was fixed, the trio is forwarded in
  `_write_phase_config`, and 9 swizzle probe rows are in the seed overlay
  (phases.seed.overlay.yaml: 5 curated + 290 in-grid with CC/ZZ pads, PGR/PLR/GLVW/NLCA,
  SS GSU4 wave-fill, HH:256/DD:256 targets, Group C swizzle probes). The planned
  overnight run is ~15-20 h packed (iteration 1 = deck 40 + seed 295 = 335 phases
  ≈ 6.5 h; 10 iterations → ~15-20 h total). The proposal was rewritten with
  old-mutation evidence from archives, backups, registries (H addendum: decay
  171→20/iter, CC+ZZ = 93/522 mutants, 30 % wasted, zero forward knobs on mutants,
  last auto run starved CC/ZZ entirely) and the new DB mutator design replacing
  the stubby manifest-only sampler. The `proposal.md` addendum (Option H2) and
  `gfx90c_tuning_guide.md` §9/§10 have been updated accordingly. Seed overlay
  rebuilt: prune 277 → archive → regenerate 295 rows (5 curated + 290 in-grid).
- **2026-10-09 — Cross-contamination eliminated, measurement hygiene + Group C land, tuning cookbook formalized.**
  Closes `potential_configs.md` §13.2/§13.4 Groups C+D and the entire CPU-only queue
  (`implementation_plan.md`): (1) **typecode-first cell attribution** — root cause of §13.2 was
  `FAMILY_TO_DTYPE["auto"] = "S"` in `analytics.py` (the greedy 4-char `phase_auto_*` id match →
  family `'auto'` → dtype `'S'` dumped HH/CC/DD kernels into SS cells; SS:1024 reported **2142.55**
  was honest **1135.1**). Removed; `gfx90c_common.kernel_typecode()`/`family_from_kernel_name()` are
  now the single resolvers (layout-suffix-aware: `HHS_BH`→HH, never SS; `ZB_GB`→ZZ), with
  `resolve_cell_family()` (typecode wins over a contradicting stamp; HPA stamps preserved) +
  `aggregate_by_cell_typecode()`; kernel_db and both port_tensile loaders consume it per row.
  Rebuilt `kernel_db.json` (folds `run_20261008_005217`+`run_20261008_030033`; 19 608 rows):
  **0 family↔typecode disagreements, 0 HH-ish kernels in any SS cell**. 28 new tests
  (`tests/test_cell_attribution.py`). (2) **Group C forwarding** — `_write_phase_config` forwards
  LdsPadA/B, AssertFree0ElementMultiple, StaggerUStride, StoreCInUnroll behind the CPU-only
  `scheduler.ldspad_feasible` gate (padded-LDS ≤ 16 384 B/WG, StaggerUStride < DepthU·bpe,
  AF0EM ≥ 1); generator `_FORWARDED` keeps them on candidates (was silently stripped — 167/167
  reference kernels carried pads). (3) **Floor winner gate-legality proven** — `check_candidates.py
  --floor` + `--quiet`: all **30/30 per-cell floor winners pass all 4 gates natively** (whole-deck
  residue 1 464/6 855 = GLVW/VW/assembly generator-rule artifacts + 72 genuine occupancy-LDS on
  non-winners); new occupancy-margin output `wg/cu=N acc=…%.` (4) **VGPR model measurement-ratified**
  — `harness/measure_vgprs.py` reads real totals from Tensile-emitted objects (1144 scanned, 605
  mapped); invariant gate-legal ⇔ measured < 256 holds for every (dtype, TT); table in
  `scheduler.MEASURED_VGPR_BY_DTYPE`. (5) **cell_knob_diff** — `harness/cell_knob_diff.py`: 30 shared
  cells, 22 native / 8 floor; CC:256 188.1 vs 214.0 is the single outside-±2 % LOSS and the only
  sanctioned steal (Group B). (6) **auto-pool audit** — 560 `phase_auto_*` dirs; the pool wins
  13/34 cells natively (38 %), NOT marginal; legacy `phase_auto_0_{S,Z}_*` (117) wins 10 via
  typecode attribution. (7) **`--prune-candidates`** on the generator (archives then strips
  `phase_cand_*` from the seed overlay; keeps `probe_*`). (8) New canonical doc
  **`gfx90c_tuning_guide.md`** (caveman, full) formalizes the knob surface, M1–M4, measured
  patterns, floor legality, knob deltas and the overnight-run rules; acceptance bar unchanged
  (`gfx90c_theoretical_limits.md` §5). (9) **Option H APPROVED** — user decision on `proposal.md`
  §H.10: all four phases landed; go-ahead for GPU-backed mutation-arm runs (unchanged behaviours
  and `--auto` semantics per Hplan.10 stand). (10) **CC/ZZ "closed as model" closure REJECTED →
  REOPENED as deficit-worthy** (`potential_configs.md` §8.6/§13.5): the ≈20 %-of-roof "cap" did
  not survive a Tensile-suite read — the complex MAC loop is exactly 4 `v_mac_f32`
  (`KernelWriterAssembly.py:14975-14978`), so the shortfall is memory/occupancy, and all 90 gfx900
  complex ships sit on a 4-variable corner (MT/TT/VW/WGM) with GSU=1, LdsPad=0, PGR=1, GRVW=VW —
  never sampling the pad/GSU/PGR axes other families ship. Ranked resolution plan tabled
  (pads {1,2,4} → GSU>1 MultipleBuffer → PGR=0 → NLCA=3 → split-complex fallback); walls stay
  open until those probes land in a TTY run. Suite: **669 passed / 1 skipped / 27 subtests**
  (full run, 540.97 s).

- **2026-10-09 (night) — beat-the-spoof batch implemented + decked; overnight-ready pool regenerated.**
  Implements `potential_configs.md` §14.5 items 1–5 as *emitted* candidates so the overnight
  `--auto` run benchmarks every decided config in one pass. (1) **Generator fixes** — SS wide tier
  now sweeps GlobalSplitU {1,2,4} (Group A wave-fill: SS:256/512 GSU{2,4} + 64x64 alternates,
  incl. the §14.5 item-1 SS:512 VW4+GSU2 correction); **HH is pinned to GSU=1 everywhere** — the
  wide-tier `(1,2)` leak and the narrow-tier GSU neighbours are both closed (the §13.4 HH GSU2
  ban is now structural and test-locked); `TARGET_CELLS` grew **DD:256** and **HH:256** (§14.5
  Group A: DD:192/256 GSU probes, HH:256/512 64x64 alternates only). (2) **PLAN_BATCH (29 rows,
  tier `auto`, all gate-verified)** — Group C pads `LdsPadA/B ∈ {1,2,4}` on the CC `64x64x8/4x4/
  VW2/DU8` (the §8.6 S3 steal tile) and ZZ `32x32x8/2x2/VW1/DU8` winner geometries; CC steal-adapt
  variants (WGM8, WGM8+padA2, PGR=0, padA2+PGR=0, GLVW=1, all-three); PGR=0 residency rows on
  SS/HH wide tiles + ZZ winners (dual LDS+VGPR relief, §14.3); single-buffer LDS (PLR=0) reserve
  on the wide SS tile (§14.5 item 5); NLCA=3 rows on the only 3-load tile in the ladder
  (96x96x16/6x6/VW2, SS and HH). (3) **Two decided levers gate-refused → documented supersessions**
  (§8.6/§13.5 dated markers): **complex GSU>1** is not deckable — Tensile passes complex only via
  `_GlobalAccumulation` (SolutionStructs:3543-3553) and the local gate refuses it (`scheduler:
  1379-1382`), so the "MultipleBuffer wave-fill" rung-2 row is withdrawn (complex ladder is now
  pads → PGR=0 → NLCA → split-complex); **NLCA=3 needs NumLoads=3 side-wise** (128-width VW4 has
  NumLoads=1) — scoped to the 96x96 tile. Also corrected the `v_mac_f32` citation home to
  `MAC_F32C.py:55/73/90/107` (research doc §5; `KernelWriterAssembly.py:14975-14978` is the beta
  epilogue). (4) **Seed overlay rebuilt** by prune-then-regenerate (2026-10-09 16:24 mirror): 5
  curated + 290 in-grid candidates = **295 rows, all fps unique, zero GSU>1 on any banned family,
  parity + deck-legality green**; `command.txt`/guide §9-§10 updated for the new pool. (5) **6 new
  regression tests** (`TestBeatTheSpoofInvariants`: banned-GSU, SS-GSU4, pad/PGR/NLCA/WGM8 rows,
  HH/DD:256 span, knob-variant phase-id uniqueness); phase-ids now carry an fp tail so pad/PGR/NLCA
  variants can never collide. `kernel_tuning_research.md` (background subagent) landed in the docs
  ecosystem (§14.6 pointers + §8.6 citation already aligned). Suite: **675 passed / 1 skipped /
  27 subtests** (full run, 720.67 s).

- **2026-10-09 (evening) — beat-the-spoof analysis pass: verdict anatomy, occupancy audit, all-around plan.**
  (1) **Native-vs-floor verdict anatomy** (`harness/cell_knob_diff.py` on the rebuild): the |Δ| ≤ 2 %
  band tally is **17 native / 8 tie / 5 loss** — SS:512 (+3.8), SS:1365 (+3.2), HH:1024 (+4.0),
  HH:2048 (+6.6), CC:256 (+13.8). Dissected into four classes (`potential_configs.md` §14.1/§14.2):
  two clock artifacts (SS:1365, HH:1024 — native medians from the 1.175 GHz-suppressed
  `run_20261008_030033`, nothing clock-normalized), one same-kernel cross-run noise row (HH:2048,
  byte-identical kernel both arms), one suboptimal VW2 pick (SS:512 vs floor VW4 on the same tile),
  and one real direction+residency deficit (CC:256 — the sanctioned steal). The old §13.6 "single
  outside-band LOSS" phrase gets a dated supersession marker. (2) **The "occupancy ≤3" investigation**
  (**new `harness/occupancy_audit.py`**): 25/34 cells genuinely sit at ≤3 resident wg/CU (median 3,
  min 2, max 10; 8–24 of 40 wave slots) — physical, not a model bug; **VGPR file binds 21 cells**,
  LDS 13. The spoof floor is equally non-resident (26/30 ≤3), so occupancy is *not* where the floor
  wins; and a single-buffer LDS probe barely moves the count (VGPR becomes the wall for 33/34 cells)
  → **residency levers must free VGPRs (GSU > PGR=0/GLVW ↓ > TT ↓ > LDS-side)**, which re-derives
  the M2 wave-fill agenda with numbers behind it. (3) **All-around plan** (`potential_configs.md`
  §14.5): clock-pinned head-to-head re-measurement as the M4 prerequisite, SS:512 VW4@same-tile+GSU2,
  Group A wave-fill (SS/HH/DD small squares), the CC:256 gfx900→gfx90c steal-adapt with adaptation
  documentation (tile ports; LdsPadA=2 + WGM8/4 + GSU2 + PGR0), and the ranked Group C probe order.
  (4) **Web-research pass** landed `kernel_tuning_research.md` (GCN5/gfx90c model, LDS bank math,
  occupancy theory, Tensile knobs, complex-GEMM incl. split-complex, SOTA cross-SKU porting — all
  URL-cited), cross-referenced from §14.6.

- **2026-10-08 — overnight-run deep triage: why the ceiling "didn't move" (potential_configs.md §13).**
  `run_20261008_030033` (6h 9m, PROVISIONAL FLOOR, 22 WIN / 15 TIE / 1 LOSS) dissected per
  dtype/family/shape against the locked gfx900 floor, `kernel_db.json`, and the occupancy model.
  Finding: ties are mostly **walls, not tuning failures** — (M1) SS/HH/DD/HPA large-squares sit at
  the realistic ceilings (SS 768+ 93–102 % of 1118.7; HH 1024+ 96–108 % of 2461; DD 768+ 90–98 %
  of 98.6; HPA *above* its derived bar), native and spoof within ±5 % (SS:768 -0.5 %, DD:2048
  +0.4 %, H:4096 +0.1 %); (M2) the 192/256/512 small cells are **wave-quantization-starved**
  (36–64 waves on 28 SIMDs = 13–23 % residency — real headroom via GSU/wave-fill, e.g. SS:256 412
  vs 1135@1024 is exactly the residency gap); (M3) CC/ZZ cap at **290–318 / 21–24 GFlops at
  91–1463 % residency** — a Tensile complex-codegen wall (4–6 instr/MAC, 2× reg footprint, 2–4×
  LDS bank-conflict amplification on 8/16-B elements) that the gfx900 ships hit too, so no
  tile/pattern mutation crosses it: the only lever with a mechanism is `LdsPadA/B` + swizzle, the
  knobs `_write_phase_config` currently strips silently — flagged as Group C candidate;
  (M4) the run measured at **1.175 GHz vs 1.8 GHz reference (≈1.53× suppressed,
  native_clock_coverage 0.53)** so its absolute numbers are flat by construction and its verdict
  deltas vs the full-clock floor are not comparable (its wins are within-run-relative only).
  §13.2 exposes report-level contamination: 4 S cells "won" by `phase_*_hh_*` phases
  (honest SS = ties at the ~1100 plateau), `H 512`/`H 256` values referenced from non-matching
  phases and from the two runs missing from `kernel_db.json` (fold via `--rebuild`), giving a
  fair re-tally ≈ **18 WIN / 19 TIE / 1 LOSS** (CC:256 -11.4 % the sole honest loss). §13.3
  pattern wins (NT everywhere; VW pinned to the 16-B load cap; WGM8 is a real CC lever;
  GSU unused in all winners). §13.4 candidate plan: Group A wave-fill (SS/HH/DD 192–512 via
  GSU{2,4}), Group B CC:256 = sanctioned spoof-steal (`Ailk_Bjlk`+WGM4/8, wave-fill alternates),
  Group C LdsPad/Swizzle forwarding + legality gate for CC/ZZ, Group D hygiene (kernel_db
  rebuild, typecode-filtered cell derivation, clock-normalisation). §13.5 records the CC/ZZ
  ceiling-model caveat (derived ceilings don't subtract the complex codegen cap → permanent
  orange regardless of deck). Doc-only change; no code touched.

- **2026-10-08 — Generated seed candidate pool (proposal D4) implemented + triage of the short run.**
  Triage of `run_20261008_005217` (~22 min, 16 phases, 0 proposals): the executed command was the
  manual one-shot `--stage 3` (`command.txt:19`), not the overnight `--auto` loop (`command.txt:53`);
  the auto arm also collapses on iteration 1 with "No valid mutations generated, stopping" — the
  native arm had no novel candidates left. Root gap: not enough proposals, not the deck. Fix =
  `harness/generate_candidates.py`, which emits a **287-row config→shapes candidate pool**
  (one row per config; fp is shape-independent and a row carries ALL of its family's in-grid target
  cells, matching deck semantics): wide (252, ladder tiles × patterns × DepthU 8/16 × GSU × WGM 4),
  narrow (24, 1-knob neighbours of each cell's deck winner, merged onto the wide row that already
  measures the fp), auto (2 explicit evidence rows N6/N7 — N6 fingerprint-identical to a wide row),
  probe (10, off-grid SS 32/64/128 + DD 128 at forced DepthU 4, `graded: false`, structurally disjoint).
  Parity-safe placement: only the **277 in-grid rows** land in `phases.seed.overlay.yaml` (282 total
  with N1–N5); the 10 probes live in the timestamped mirror only (`--with-probes` opts them into the
  seed and breaks `test_seed_only_extends_within_grid` until the rule is amended). Verified CPU-side:
  unique phase_ids + fps, zero deck/curated-seed fp collisions, full cell coverage, per-row dtype/label/
  ScheduleName/NumBenchmarks, and all 277 rows pass the real launch-boundary `_write_phase_config`
  (both CPU gates, 0 refusals). `tests/test_generate_candidates.py` (14) + `tests/test_library_parity.py`
  (17) green. Mirror: `gfx90c_results/overlays/phases.candidates.20261008_024733.overlay.yaml`.
  Overnight budget note: deck (40) + seed (282) measure once per run before the loop mutates.
  Open: ceiling model still %-of-roof for CC/ZZ (§8.6); the three analytics feed gaps
  (`probe_*` globs ×3, dtype-from-config, `_write_phase_config` forwarding of LdsPadA/B,
  AssertFree0ElementMultiple, StaggerUStride, StoreCInUnroll) are still unimplemented.

- **2026-10-08 — Coverage-parity rule formalised + ad-hoc /tmp machinery integrated as `harness/`.**
  The produced `tensilelibrary.dat` must map EXACTLY to the shipped gfx900 grid in (shape, dtype)
  cells — no contraction, no extension — canonicalised once in `knowledge_base.md` §6.1, with
  mechanical enforcement only (the rule has one home): `check_library_parity.py` CLI (deck + seed +
  `--run-id` overlay vs `gfx90c_common.shipped_cells()`, exit 1 on divergence), a `run_preflight`
  parity verdict, a `consolidate.py all --commit` refusal gate, and `tests/test_library_parity.py`
  (17 passed) pinning the committed deck + seed overlay to 38/38. The measurement machinery built
  ad-hoc in `/tmp` now lives repo-homed: `harness/kernel_db.py` + `harness/regression_matrix.py`
  (median basis, per-family 38-cell grid; `kernel_db.json` rebuild verifiably identical to the §12
  snapshot). §12/doc numbers re-based to the per-family grid: **9 losses vs floor (8/9 config
  identical, S:512 the only real knob diff), 16 wins, 13 ties**, and **one material median
  finding** — HH_HPA:4096's stranded iteration-9 overlay winner (`phase_auto_1_hh_hpa_2048x2048x2048_4`,
  −4.0% at the median) to be shipped as probe N7. Verified vs the full deck: parity CLI PASS 38/38,
  `kernel_db.json` row-for-row identical to the published §12 corpus.
- **2026-10-07 — D1 deck bootstrap implemented; all-run regression list = 0 material median regressions (dtype view; 1 per-family carry-over, in the body).**
  The 11 provenance winners from §8.4 + the seed overlay's proven rows (CC 192/256, HH_HPA 512,
  HS_HPA 512, and the `phase_auto_{0,2}_*` rows) are appended to `phases.yaml` — deck now **40 rows** —
  each with `fp = fingerprint_config(config)` and `contraction_pattern`, so they re-benchmark once
  next run (the measure-once bootstrap that makes the next overnight productive instead of the
  run-20261007-012721 silent no-op: 29 records, all `identical_fp_already_passed`, 0 proposals →
  empty harvest → "No valid mutations generated, stopping"). The seed overlay is trimmed from 16 rows
  to **5 probes (N1–N5)**; the iteration-9 tail (23 proposals, 21 accepted, stranded in
  `phases.run_20261006_122020.overlay.yaml`) stays accounted under decision D2, not lost.
  `TestDeckIsVerbatim` now exempts D1 rows (`phase_auto_*`) from byte-verbatim and pins them on
  `fp == fingerprint_config(config)` + `contraction_pattern`. Verified: `test_consolidate` 20 passed,
  `test_phase1_integration` 57 passed; full suite 603 passed/1 skipped/27 subtests (as documented).

  **Programmatic all-run regression list** (`gfx90c_results/analysis/regression_matrix.json`, §12 of
  `potential_configs.md`, regenerated by the repo-homed `harness/` tools): per-cell (family, shape) of the
  shipped grid (38 cells) deck-issued best-median vs all-time best-median across every native run + the
  gfx900 floor. Result: **38 cells, 1 material median finding** — the deck ships the median-best kernel for
  every cell except **HH_HPA:4096**, where the stranded iteration-9 overlay candidate
  `phase_auto_1_hh_hpa_2048x2048x2048_4` runs −4.0% above the shipped kernel at the median (1411 vs 1355)
  and should be shipped as a D-row (probe N7); the §8.4 reuse-loss hole is closed bar that one carry-over.
  Residual vs floor (>2%, median): **C:256 (−12.1%), H:1024 (−7.0%), S:1365 (−6.9%), H:2048 (−6.2%),
  S:768 (−4.4%), S:1000 (−4.2%), C:1024 (−3.9%), S:512 (−3.7%), S:2048 (−2.0%)** — of which **8/9
  benchmark the identical config the deck already ships** (the residual is cross-run variance, not a
  missing knob) and only **S:512** differs (deck VW2 771.9 vs floor **VW4 801.6**), the one knobs-level
  target on the board.
  H:256 "LOSS" reconciled as a basis flip: floor `MT128x128/8x8/VW2/DU8` best-seed 303.6 has median
  171.3 (below the deck's 206.5); by median the deck wins +2.5%, by tail it "loses −31%". Occupancy:
  45/45 deck+seed rows pass `occupancy_feasible` (wg/CU 512–8192, register-file metric).
- **2026-10-07 — Persistent seed overlay (D2b) lands; mutation arm no longer self-cancels.**
  A 2026-10-07 auto run executed *zero* phases: the deck's 29 rows are all `identical_fp_already_passed`,
  the mutation arm only harvests winners from the current run's CSVs, so 0 measurements → empty
  harvest → no mutations → stop at iteration 1. The root cause is the skip/harvest contract, not a
  bug, but it meant the arm could never bootstrap a deck it had already passed. Fix: a static,
  run-independent seed overlay (`gfx90c_results/overlays/phases.seed.overlay.yaml`) merged by
  `load_phases_manifest` every run, tagged `origin=seed_overlay`/`overlay_run_id=seed`, with
  `phases.yaml` provably untouched. It carries 16 rows — the 11 measured all-time winners (with
  their full shape grids) plus probes N1–N5 — so a fresh run re-benchmarks each proven winner once
  against the live GPU instead of skipping it. Two planned probes were dropped during validation:
  they were fingerprint-identical to existing winners (same MT/tt/vw/du, different shapes) and
  added no signal. `run_phases` gives seed rows *measure-once-per-run* semantics: `has_run_benchmarked(run_id, fp)`
  (new on `registry`, and the identical-fp method whose body had been accidentally deleted during
  scoping was restored) gates the iteration-1 bypass off for the rest of the run, so a static seed
  never re-fires every iteration — verified 16/16 + curated each executed exactly once across 3
  iterations in a stubbed-executor harness. Four tests added; full suite 585 passed, 1 skipped,
  27 subtests.
- **2026-10-06 — `legal_slow` is reference-derived, and the Phase-4 legal rate hit 100%.**
  The legality verdict is now measured the way the gfx900/spoof reference actually ran:
  `ab_audit.cell_deltas()` exposes the spoiled reference median per cell, and
  `coverage.reference_thresholds()` (cached, re-entrancy-guarded) computes the band once and
  gives every cell a bar of `reference_median * (1 - band/100)`. `classify_outcome` reports
  `legal_slow` only when **every** measured cell in a sweep is below its bar (ties are not
  slowness; one competitive shape rescues a sweep), unmatched cells are never slow, and
  zero-throughput is `non_functional`, not slow. Two implementation details that mattered:
  the per-cell bars must be built lazily (the band itself can only come from
  `ConvergenceAgent.band()`, see the Phase-4 entry), and the dtype must be resolved from the
  phase id for the cell keys — an unresolved dtype silently mutes the whole verdict.
  `tests/test_legal_slow.py` pins it, 28 tests.

  Second finding: **the registry WAL is part of the ledger.** Copying `registry.db` alone
  after an un-checkpointed write loses the newest rows (`-wal` must travel, or
  `PRAGMA wal_checkpoint(TRUNCATE)` first) — demonstrated by `tests/test_ledger_durability.py`
  (9 tests) with an `early`/`late` write split across a copy+restore.

  Third: **an 88% legal rate was hiding a structural bug, and the fix is manifest reading,
  not a reject-set model.** The sampler crossed `DepthU`/`GlobalSplitU` onto incompatible
  tiles. The shipped manifest stores DepthU as the K component of the MacroTile
  (`128x32x16` *is* "MacroTile 128x32, DepthU 16"), so `DepthU` now rides with the `tile`
  group, and `legality.cooccurrence_check` rejects every cross-group knob pair that never
  ships together (read off the manifest, cached, deliberately *not* the occupancy/assembly
  predicates — those still reject shipped configs: 31/135 HS_HPA, 19/169 SS). Measured:
  legal rate 88% (176/200, HS_HPA 0%, HH_HPA entirely declining) → **100% (232/232), all
  seven families proposing, zero false drops.** The gate cannot reject a shipped config —
  a shipped solution co-occurs with itself.

  The overnight command now exists: `python3 port_tensile.py --auto --yes --budget 10
  --mutation-budget 2 --live off` (appended to `command.txt`).

- **2026-10-06** — **Option H Phase 4 landed: coverage-guided synthesis, graded candidates.**
  New `synthesis.py`, plus the agent/mutator wiring to use it. `Hplan.6`'s four items: coverage
  state now directs which knob groups a draw may touch; the lattice remains as a reported
  fallback; candidates carry the family's shape sweep so a mutant is gradable at all
  (`Hplan.1` item 5); and `ThreadTile`/`WorkGroup` are re-derived from `MacroTile`.

  Two findings worth keeping. First, `Hplan.6` item 2 ("extend beyond the lattice's six
  knobs") was **already satisfied by Phase 2**, and is now exhausted rather than merely
  satisfied: all eight structural knobs the shipped solutions encode are covered. The ninth
  parsed knob, `grvw`, is excluded on purpose — it is not a Tensile parameter, and
  `BenchmarkStructs` calls `printExit()` on unrecognised names. A knob invented to look like
  progress would have aborted parameter filling instead.

  Second, and more important: **the acceptance band cannot be computed in
  `ConvergenceAgent.__init__`.** `ab_audit.arm_record_sets` builds an agent to manage phases,
  and `coverage.measured_band_pct` calls `arm_record_sets`, so doing it at construction time is
  `measured_band_pct → agent → agent → …` and terminates only by exhausting the stack. This
  presented as `TestMeasuredBand` *hanging* rather than failing, and it cost real time to
  diagnose — the traceback was the only evidence. It is now `ConvergenceAgent.band()`,
  resolved lazily, at most once, with a re-entrancy guard, and `BandResolutionTests` pins it.
  The related question of "is 5.0 a real measurement?" has a clean answer: it is
  `TIE_BAND_PCT`, the documented shipped floor, chosen by `measured_band`'s `max(...)`, so on
  an empty corpus the band is the floor and says so via `band_source`.

  Two latent bugs surfaced by the new tests and fixed: `reconcile_tile` returned early when
  `ThreadTile` or `WorkGroup` was **missing** — precisely the case it exists to solve — and an
  unsolved dimension rendered as the literal string `"None"`, which Tensile rejects at
  parameter-parse time rather than at our own check.

  Design choice worth recording: **the ledger's single `shape` column keeps the cell identity,
  and the sweep lives in phase data.** Coverage joins on `(family, shape)`, so storing the
  sweep's first shape would re-file the candidate into a different cell and quietly corrupt
  every coverage join.

- **2026-10-06** — **Option H Phase 1 integration closed: the ledger now actually runs.**
  Phase 1 shipped every piece of Hplan.3 and reached a run with none of them wired. Each gap
  failed silently, which is why none of it was visible from the tests: the per-run overlay was
  written and never merged into the deck, so candidates were emitted, recorded, and never
  scheduled; `run_id` was dropped on emission; the proposal row and its phase were two commits,
  so a crash between them left a permanently-`pending` candidate whose `n` never grows and
  which is therefore re-routed to `replicate` on every later pass, indistinguishable from
  genuine instability; `resolve_phase_dir` was never called by the driver, so the ledger only
  ever accumulated `pending` rows; `WinnerFreq` was parsed by a private CSV reader whose failure
  mode is zeros, which reads as "no kernel won"; the negative cache was process-local, so every
  restart reported a saturated neighbourhood as untouched — it switched off exactly when needed;
  and `skip_mutation_arm()` was computed on every emission and then ignored by the loop that
  performs the skip.

  `load_phases_manifest` now merges this run's overlay (tagged `origin: overlay`), keyed on the
  active run and suppressed for an explicit deck so `--gfx900-reference`'s spoof floor can never
  absorb native candidates. Proposal and phase are inserted in one transaction
  (`emit_proposal_with_phase`). `run_phases` calls the outcome write-back for phases that
  actually launched, so a phase that never ran is not classified as `non_functional` for having
  produced no output. WinnerFreq is read through `analytics.read_column`/`winner_freq` — the
  single owner of Tensile column parsing — and persisted to a new append-only
  `proposal_observations` table, written before the verdict so a crash leaves recoverable
  evidence rather than a decision with no basis. WinnerFreq lives outside the `proposals` row
  deliberately: evidence is re-observable, verdicts are decided once, and columns there would
  invite overwriting the basis of an already-made decision. The negative cache is rebuilt from
  the ledger's resolution order at construction, because `consecutive` is a claim about
  sequence. The identical-fp bypass is scoped to overlay phases only, so it cannot re-benchmark
  settled curated phases.

  Also fixed: `SQLiteRegistry.__init__` ran the additive schema migration unconditionally, so
  every `ab_audit` run rewrote the live floor registry's bytes — schema only, no row touched,
  but a report had changed its own subject. `SQLiteRegistry(base, read_only=True)` skips the
  migration and every mutating method raises `PermissionError`; the audit now reads read-only.
  New `tests/test_phase1_integration.py` (53 cases) drives the driver's loop rather than the
  helpers, since testing the helpers in isolation passes even when the loop calls neither.

- **2026-10-05** — **Option H Phase 3 landed: cell coverage, three distinct states, and LCB
  parent selection.** New `coverage.py` reports per `(family, shape)` evidence (distinct
  fingerprints, `min_n`, median, spread) and classifies each cell as `explore`,
  `replicate` or `retired`. `agent.harvest` now picks a parent by **lower confidence
  bound** instead of raw winner, which closes the path by which a noise-level win becomes
  the parent of the next batch: a config whose median is high because one seed landed well
  now ranks below a merely-good one. `CellAnalytics` carries its seeds (an LCB is not
  recoverable from a median, a CV and a count), `ab_audit.py` prints `n`, spread and the
  novel/replicate split, and `registry.all_proposals` exposes the ordered ledger.

  The states are kept deliberately distinct: retirement is only reachable once decided
  evidence exists, so "never tried" is never recorded as "tried and failed" (§H.1.2a), and
  `legal_rejected` does not retire a cell because a rejected proposal never ran. `min_n` is
  the *worst* measured config in a cell rather than the mean, since averaging that away is
  how thin evidence becomes a verdict. The acceptance band is read from
  `ab_audit.reproducible_band` and returns `None` when it cannot be measured, rather than
  falling back to a literal — the same failure mode as the retracted `GFlops` figure. A
  single sample degrades the bound to its median instead of claiming precision; thin
  evidence is reported as thin. `parent_by="median"` stays reachable and
  `selected_by_lcb` / `parent_by` / `parent_score` are recorded per winner so the two
  policies stay comparable on the same data.

  **Defect found and fixed during the phase.** `coverage.measured_band_pct()` never
  actually read a band: it called `ab_audit.reproducible_band()` with one argument for
  a two-argument function, and a bare `except Exception` converted the `TypeError`
  into `None`. Every cell therefore evaluated with no band at all, while the plan and
  changelog asserted the band was measured from the corpus. `ab_audit` now exposes
  `arm_record_sets()` and `measured_band()` — the exact two calls `audit()` makes —
  so coverage reads one canonical band, the audit passes its band into the coverage
  report instead of recursing into itself, and the two cannot disagree. Measured on
  the current corpus the band is **18.29%**, against a shipped floor of 5%. The test
  that missed it (`assertTrue(value is None or value > 0)`) passed for a function
  that always raises; it is replaced by four assertions, all of which fail when the
  read is stubbed back to `None`. Also added explicit `target_cells`, so a cell that
  was targeted but never proposed for is reported as `explore` rather than vanishing.

- **2026-10-05** — **Option H Phase 2 landed: manifest-derived legality prior, measured live
  at 35.7% -> 85.3% legal.** New `legality.py` replaces the ≤2-knob lattice in
  `agent.mutate_and_feed` with a prior that draws knob values only from what Tensile ships
  for that family, so the reject classes are never proposed. Measured on the same 29 curated
  parents, same process, same `validate_config`: lattice 417/1169 legal, prior 198/232. The
  lattice figure reproduces the D3 table when re-run, which is the cross-check that both
  arms share one reject model. Hard walls encode the half `VectorWidth` floor and the
  no-schedule MacroTile case; `validate_config` stays an assertion per Hplan.4 step 4, so
  the residual (occupancy, and load divisibility on the full problem instance) is recorded
  `legal_rejected` rather than searched away. `tensile_library` gained public
  `shipped_kernel_config` / `shipped_kernel_knobs` wrappers and an `AF0EM` field so the prior
  reads solution names through the single existing parser; `_config_from_kernel` is unchanged
  so the pinned reference build is untouched.

  Three corrections came out of implementing it, and none of them are confirmations:
  (a) the audit's `A_half_VW1_assembly` is two conditions in different places, and the GSU
  half is not enforceable from our config surface — a first cut that modelled it produced 90
  false rejections on shipped HS_HPA `GlobalSplitU` 2/3/5/7 vectors, so it is now recorded in
  `legality.DEFERRED_RULES` with its reason rather than enforced wrongly; (b) the half
  `VectorWidth` wall was **dead on arrival** because `EnableMatrixInstruction` tests
  `len(ThreadTile) == 2` while our configs carry ThreadTile as the string `"8x4"` — every
  candidate read as undetermined and the sweep reported a perfect 100% accepted, which is
  how the bug surfaced; (c) GlobalLoadVectorWidth is a function of MacroTile, so schedule and
  loads had to become one atomic group, and the base had to be a complete shipped vector
  rather than the partial deck config.

- **2026-10-05** — **Option H Phase 1 landed: append-only `proposals` ledger, outcome
  classification, and a mutation arm that stops writing to `phases.yaml`.** New `mutator.py`
  (classifier, novelty, negative cache, per-run overlay); `registry.py` gains the `proposals`
  table plus `record_proposal` / `resolve_proposal` / `is_novel` / `coverage_view`, created
  additively so an existing registry picks it up on next open without rewriting a row;
  `agent.mutate_and_feed` now emits to a per-run overlay (`gfx90c_results/overlays/`) and
  refuses to re-propose a known fingerprint, which is the first time D2 and D4 are actually
  closed rather than described. `analytics.count_benchmark_rows` was added because the
  classifier must distinguish "rows that produced nothing" from "no rows" and the value-loader
  drops non-positive rows by design — CSV shape now has one owner, as does CSV values.
  Two guards are load-bearing and tested: `ConvergenceAgent.skip_mutation_arm()` returns True
  when the ledger is missing **or** when it exists without an outcome signal, so the
  identical-fp bypass cannot be unlocked by a novelty-only ledger (Hplan.3 steps 8 and 11).
  `resolve_proposal` advances `pending → terminal` exactly once and silently no-ops after,
  and the registry exposes no delete method, so append-only holds by interface rather than by
  caller discipline. `scheduler.mutate_winner` is unchanged — Phase 1 fixes the loop's memory,
  not its generator. No GPU work, no full Tensile benchmark, `phases.yaml` untouched, and the
  live `registry.db` byte-identical after the run (verified by sha256). Suite: 317 tests,
  1 skipped, exit 0.

- **2026-10-05** — **RETRACTED: the "mutants produced zero GFlops" finding was an artefact
  of the wrong CSV column.** `proposal.md` §H.1.2a reported 2,480 mutant benchmark rows with
  0 non-zero GFLOPs, and the whole Option H priority list was ordered on it. The count was
  read from the column *headed* `GFlops`, which in these CSVs is a **problem index**, not a
  throughput — it reads `0,1,2,3` across a four-shape file and `0` in any single-shape file.
  Real throughput is in the trailing `Cijk_…` kernel column, which is what the canonical
  loader `analytics.load_benchmark_csv` reads. Re-measured through that loader the sign
  flips: **2,960 rows, 2,960 non-zero, 370 of 374 dirs productive.** The mutants were never
  broken. What is true, and what D5 already said, is that they are **ungraded**: keying both
  populations by (kernel class, shape) leaves exactly **one** like-for-like cell out of 14,
  and in that cell the mutants are *better* (6.89 vs 4.36 median). Two defects survive —
  outcome is never recorded (D6) and every mutant is single-shape (D5) — and the second is
  now co-equal with the first, since an unmeasurable result is not a search result.
  **Why a same-run positive control did not catch it:** the control (`phase_zz_*`) is
  non-zero under *both* readings, so the control passed while the measurement was wrong.
  Lesson recorded in `proposal.md` §H.8 and §H.11: prefer the canonical loader over a column
  name, and key comparative claims by (class, shape), not raw yield. Every affected claim in
  §H.0, §H.1.2a, D3/D6, §H.3, §H.3.4, §H.3.8, §H.4, §H.7.10-11, §H.8 and §H.11 has been
  corrected in place; the original figures are quoted only inside the correction notices.

- **2026-10-05** — **`--auto` cannot express "no mutations".** Found while formalising
  the Option H mutator plan. Three independent traps: `--mutation-budget 0` still emits
  single-knob mutants (the budget gates only the two-knob block in
  `scheduler.mutate_winner`); `--budget 1` still harvests and mutates, because
  `run_auto` calls `mutate_and_feed` before incrementing the iteration counter
  (`port_tensile.py`), so a single-iteration run appends candidates to the curated
  `phases.yaml`; and `--stage` gates only the non-`--auto` branch. The mutation-free
  path is therefore to omit `--auto` and use the plain Stage-3 route, which is what
  `command.txt` now records. **Resolution:** the user confirmed omitting `--auto` is the
  intended route, so the proposed `--mutation-budget 0` = "emit nothing" fix is
  **withdrawn** — `--auto` semantics stay as they are. The overpromising flag text is
  still wrong and Option H fixes the underlying width problem in `scheduler.mutate_winner`
  by construction rather than by flag (`implementation_plan.md` §Option H, `Hplan.10`).

- **2026-10-05** — **`s`/`e`/`q` were dead while phases were skipped, and stdin had
  two competing readers.** A phase that policy skips (identical `fp` already
  passed) does no GPU work, and that code path polled no keys at all — so a
  re-run or `--resume` of an already-passed deck ignored `q` completely until
  some phase actually launched, which for a fully-skipped deck is never. The
  keys are documented as run-wide, so the gap was a contract violation, not a
  missing feature. Root cause was structural: the `select`+`read(1)` poll was
  copy-pasted into the cooldown latch and the Tensile wait loop and simply
  omitted from the third context.
  - stdin now has a single owner, `TensileDriver._read_key()`, used by all three
    call sites. Two pollers on one fd race for the same byte, so the keys could
    mean one thing in one place and something else in another.
  - `block=False` for the skip path: a spin-wait loop must not busy-spin off a
    TTY, but a skip loop already does real work per phase and must not pay 0.2 s
    × N phases to discover there are no keys.
  - A user-quit during skips is now filed as `interrupted`, not `skipped`.
    `skipped` asserts the corpus already had those measurements, which is a
    different statement from "the operator stopped it".
  - **CLI option audit (one pass, all 29 `--` options): no dead options.** The
    only candidate, `--release-unreproducible`, is a false positive from a
    `getattr(args, ...)` read and is genuinely wired — it sets
    `plan.rerun_unreproducible`, consumed as `release_drop`. Both `--release-*`
    flags reach the plan correctly. What was missing was a check that this stays
    true, so `tests/test_interactive_keys.py` now fails if any option is declared
    and never consulted, and if any option is absent from `--help`.
  - README §1's stated contract said the keys were active "during active
    benchmarking and thermal cooldown sleep" — the incomplete contract that let
    this ship. It now names the skip path explicitly.
  Covered by `tests/test_interactive_keys.py` (12 tests). The regression is
  load-bearing: reverting the skip branch to a bare `continue` fails 3 of them.

- **2026-10-05** — **`verify_run.py`: the append-only law finally has a checker.**
  Verifying the trial needed shell one-liners in `/tmp`, which is the same
  scratch-the-answer-away pattern `run_status.py` was built to end. The law
  (`knowledge_base.md` §10) makes overwriting benchmark data project-blocking,
  and nothing could *check* it: `registry.config_fingerprint` and
  `scheduler.generate_fingerprint` hash kernel CONFIGS, and consolidate's
  `PRAGMA integrity_check` only proves the SQLite file is intact — none of them
  notice a phase's CSVs being rewritten. Three subcommands, CPU-only, no gate
  arithmetic reimplemented (the clock funnel reads through `TensileDriver`'s own
  loaders, so it cannot disagree with the pipeline that made the verdict):
  - `snapshot` / `diff` — per-run-directory file counts and bytes plus registry
    row counts. A new run dir and more rows is additive; anything shrunk,
    removed, rewritten in place, or any lost row exits non-zero. Snapshotting
    twice over the current corpus is clean (13 run dirs, 41 runs / 612 phases /
    49,540 records). A missing table reports as unknown, never as zero.
  - `telemetry <run_id>` — the per-phase funnel (rows → busy → sclk range →
    thermal), so a filter that discards everything is visible instead of reading
    as "the run measured nothing". That is precisely the shape of the busy-gate
    defect above, which was invisible until counted by hand.
  - `cheapest --family ZZ` — cheapest *legal* live-deck phase, with the exact
    `--targets` command to drive it. Legality comes from `consolidate._is_legal`
    because sorting by volume alone returns configs Tensile rejects at assembly.
    It reads the LIVE `phases.yaml`, not `load_deck()`'s 1644-phase universe, so
    the suggested target is always one the driver can resolve — verified by
    dry-running the tool's own suggestion back through `port_tensile`.
  Covered by `tests/test_verify_run.py` (18 tests); the failure paths get as much
  attention as the happy one, since a checker that cannot fail is worse than none.

- **2026-10-05** — **First native run on the locked deck: `run_20261005_170141`.
  It validated phase-resolved telemetry, confirmed the ZZ fix end to end, and
  exposed that the telemetry clock gate was throwing the data away.** One phase,
  `phase_zz_Ailk_Bjlk_mt32x32x16_tt2x2_vw1_wgm4_alu` — deliberately the cheapest
  legal cell in the deck (128³ primary, ZZ, `vw1`), because it is the config the
  ZZ=16 fix exists to make legal.
  - *The fix holds under real compilation.* The phase assembled and produced all
    5 shapes × 8 seeds (128³…1024³, medians 4.5 / 20.6 / 20.3 / 19.0 / 22.4
    GFLOPS). Under the old `ZZ = 8` table this phase's `VectorWidth=1` was not
    the thing that broke, but its siblings at `vw2` were rejected at assembly with
    `GlobalLoadVectorWidthA * DataType.numBytes() > 16`; nothing dead now ships.
  - *Phase-resolved telemetry works.* 1,916 of 1,950 rows carry `phase_id` (the
    34 without it are pre-phase startup), giving a real per-phase clock base of
    **1787 MHz @ 76 °C median, 82 °C max** — the first phase-owned clock in the
    project. `WinnerFreq`/`Power`/`Temperature` were 0 in all 40 benchmark rows,
    reconfirming that `logs/telemetry.csv` is the only clock source.
  - *`gpu_busy_percent` is not a usable gate, and had been silently deleting the
    evidence.* Clock bases are built from `busy > 50%` samples; that filter kept
    **1 of 1,916**. amdgpu reports 3–8% for short and small kernels, so the gate
    measured saturation, not activity. `power_uw` is no substitute (idle median
    20 W vs clocked 23 W, idle p95 28 W, quantised). The gate is now **off by
    default** (`TELEMETRY_REQUIRE_BUSY = False`) and retained for reporting only:
    `sclk` is the discriminator that works, and `SCLK_MIN_HZ` already removes the
    400 MHz idle floor. Corpus impact measured, not assumed: 53,860 → 93,427
    usable samples, phase coverage 3375/3654 (92.4%) → 4167/4516 (92.3%), i.e.
    bases get ~1.7× more samples and cheap phases become measurable, while the
    coverage *rate* — and so every existing clock-adjusted verdict — is unchanged.
  - *Nothing pre-existing was touched.* Every run directory fingerprint is
    byte-identical before and after except the new one; the registry went 40 → 41
    runs and 49,538 → 49,540 records with the old rows intact.
  - *What a cheap run still cannot do:* settle form-vs-thermal. That needs the
    same kernel in both invocation forms on the same cell, which is the exact
    comparison the certainty tiers refuse to grade. Plumbed, not answered.

- **2026-10-05** — **The "~2× invocation-form swing" is real, and grading no longer
  depends on it.** The long-standing caveat — identical config at 658.2 GFLOPS
  multi-shape vs 333.0 GFLOPS single-shape at `1000³`, larger than every graded
  effect — survived an attempt to retract it, which is itself the useful part:
  a live-tree-only search missed `archive/gfx90c_runs/run_20261002_021805` and
  `logs/telemetry.csv`, and both halves of the claim are genuine measurements.
  Verified from raw per-seed rows: the single-shape phase median is 313.0 (max
  seed 333.0), the multi-shape phase median 624.5 (max seed 658.2), **2.00×**,
  with 2 of 3 derived Tensile solution sets byte-identical between them and
  identical `LDA/LDB/LDC/LDD` and `TotalFlops=2e9`. Clock is ruled out: busy-only
  core-clock medians are 1587 MHz vs 1650 MHz (4–8%) against a 2× gap.
  The same gap reproduces inside one run (`Cijk_Ailk_Bjlk_SB_MT96x96x16_SN_K1` at
  `1000³`: 394.3 vs 855.1 = 2.38×) with identical parameters, but it cannot be
  attributed to form, because form is confounded with generator (single-shape is
  94% Tensile AutoTuner, multi-shape is entirely deck sweeps) *and* with the
  run's time window (`phase_ss_*` 00:00–06:44 vs `phase_auto_*` 06:58–09:28), and
  it inverts sign across sizes (0.25× at 256³, 1.00× at 4096³). Three changes
  follow:
  - *Certainty no longer rests on shape count alone.* `ab_audit.py` gained
    `phase_family()` (`auto` vs `deck` — keyed on the generator, not the raw
    prefix, since the live deck's `phase_<cell>_*` and the floor's `phase_ss_*`
    are the same sweep generator) and grades `certain` only on same form **and**
    same generator **and** a margin beyond noise. Otherwise:
    `form_mismatch`, `generator_mismatch`, `within_noise`, `missing`.
  - *The ±5% tie band was unsupportable and is no longer used.* Repeat spread of
    one identical kernel under one identical form (n=1495 groups): median CV 8.1%,
    p90 27.8%, worst single-shape 36.1%, worst multi-shape 75.0%. Grading now uses
    `max(cross-arm band, repeat p90) = ±27.8%`, computed from data every run.
  - *The six "certain losses" were an artifact of the old band.* At −14.5% to
    −16.1% they sat entirely inside the repeat tail; the audit now reads
    **8 WIN / 30 TIE / 0 LOSS**, and every surviving win is far outside the band.
  Instrumentation gap recorded for the next native run: all 8113 Tensile CSVs have
  `WinnerFreq`/`WinnerPower`/`WinnerTemperature` = 0 in every cell, so clocks live
  only in per-run `logs/telemetry.csv`, whose historical files predate the `phase`
  column. `telemetry.py` now samples at 10 Hz with per-phase attribution, making
  the form-vs-thermal question answerable by measurement for the first time.

- **2026-10-05** — **Measurement paths made non-destructive, and the ZZ width
  bug was found a second time in a second place.** A sweep for write paths that
  could destroy prior measurements turned up four, plus a duplicate of the same
  wrong constant:
  - *`scheduler.FAMILY_BYTES_PER_ELEMENT["ZZ"] = 8` had been fixed, but the same
    number was hardcoded a second time in `allruns.py` (`DTYPE_BYTES["Z"] = 8`)* —
    the "one fact, one canonical home" rule violated by the byte table itself. It
    now reads widths through `consolidate.dtype_bytes()`, and
    `tests/test_measurement_integrity.py` asserts the two tables agree for every
    family, so a future drift fails a test instead of quietly understating a
    width. `allruns.py` had also mapped `HS`/`HS_HPA` to `H` (2 B) while
    `scheduler` mapped them to `S` (4 B); both now use the widest loaded operand,
    matching `scheduler.cap_vector_width`.
  - *Re-running a run directory silently reused it.* `create_run_dir()` now
    refuses a populated `run_id` unless `allow_existing=True`, and the DB
    checkpoint upserts on conflict instead of colliding on `UNIQUE(run_id)` —
    deliberate continuation works, accidental reuse cannot start.
  - *`consolidate.install()` overwrote the live floor lock.* It now moves the old
    lock into `archive/gfx90c_runs/superseded_locks/` with a timestamped suffix
    before writing the new one; there is no `rmtree` left on that path.
  - *A phase rerun would overwrite `2_BenchmarkData/*.csv`.*
    `TensileDriver._run_tensile_benchmark()` now raises `FileExistsError` before
    launching if a phase already has results.
  - *`telemetry.py` would append 9-column rows to a legacy 8-column file,* making
    the CSV unreadable to older readers. It now compares the header and starts a
    `telemetry.<n>.csv` sidecar on mismatch.
  Regression coverage for all of the above lives in
  `tests/test_measurement_integrity.py` (17 tests); the full suite is 211 tests.

- **2026-10-03** — **Corpus consolidated; the gfx900 floor is locked, the deck is
  reduced to 29 phases, and the legality gate no longer ships dead ZZ configs.**
  Four defects surfaced while building the lock, each of which had been silently
  shaping results:
  - *The global-load byte cap was not enforced anywhere CPU-side.*
    `occupancy_feasible()` and `assembly_class_valid()` both pass a
    complex-double phase at `VectorWidth=2`, and Tensile rejects it at assembly
    with `GlobalLoadVectorWidthA * DataType.numBytes() > 16` — 16 bytes for `Z`,
    because complex double is 16 B, not 8. The cause was
    `scheduler.FAMILY_BYTES_PER_ELEMENT["ZZ"] = 8`, one number wrong, and
    `check_candidates.py` inherited it. 28 archived phases are affected and one
    whole overnight run was spent proving it. `consolidate._is_legal()` now runs
    all three gates and reads byte widths from `Tensile.DataType.properties`
    (`numBytes() == reg * 4`) rather than from a hand-maintained table.
  - *Selecting the floor by best-single-CSV-per-phase understated it.* Choosing
    one source run per phase gave a floor below the chain best on 17 of 38 cells,
    by up to 11.9%. A lower floor flatters the native arm, so the bias pointed
    the wrong way. The lock now pools **every** CSV from the chain (3802 files,
    2194 phases) and lets the canonical aggregator take the median.
  - *The pipeline was not idempotent.* The locked floor was named from a
    timestamp, so every re-run minted a new `gfx900_ref_locked_*` id and left the
    previous one behind looking authoritative; and the DB insert appended a
    duplicate row. The id is now `sha256(chain)[:10]` and the insert is scoped
    `DELETE`-then-reinsert for that one `run_id`. Re-running `all --commit`
    twice leaves row counts identical.
  - *Selection read the live deck as its candidate pool.* After a consolidation
    the deck *is* the output, so the next pass had only the survivors to choose
    from and collapsed 45 → 17. `load_deck()` now unions every `archive/phases.yaml.*`
    with the live deck, so the universe is all 1644 solutions ever written and
    re-running reproduces the same 29.
  Locked floor: `gfx900_ref_locked_52149f315d`, from the 3-run chain
  `20260929_164544_resume → 20260926_201843_resume → 20260925_152942`.
  Deck: 29 phases covering 38/38 target cells, every entry a verbatim copy of an
  archived phase, every cell's best *measured* solution retained, including the
  six current losses. `run_20261002_021805` (1168 single-shape phases, 0
  multi-shape) moved to `archive/gfx90c_runs/` — out of the live loader path but
  preserved, since its configs are deck priors. Nothing was deleted; 25
  empty/no-record phantom run dirs were moved aside and their registry rows left
  in place.
- **2026-10-02** — `family_timing` was computed on every report and then
  **never written** — the whole per-family cost block was dropped on the floor.
  The report now carries an `execution_timing` block (native run wall clock,
  reference-chain wall clock, phase-busy time) and `family_timing`, in the JSON,
  the HTML, and the one-line summary. Native run and chain are separate numbers
  on purpose: the floor is a 3-run chain, so one combined "runtime" would
  understate it. Measured on the current corpus: native `1d 19h 39m`, chain
  `3d 20h 34m`.
- **2026-10-02** — `run_status.py` wired into the TTY via `LiveStatus`, on by
  default (`--live off` to disable, `--live-interval` to tune). A background
  thread repaints a compact panel so it keeps advancing while a phase blocks,
  and stdout is wrapped so the run's own prints clear the panel first. Degrades
  to plain appended lines when stdout is not a terminal, so piped logs stay
  readable. `build_report` raises `SystemExit` when the registry is absent —
  not an `Exception` — so the first run of a fresh tree would have died in the
  panel's first frame; the panel now catches `BaseException`.

## [Acceptance best-vs-best default + telemetry-adjusted bases] 2026-09-27

- **All-zero acceptance report FIXED (arm-scope asymmetry).** The spoof arm resolved
  across the whole gfx900 reference chain (1,881 completed cells) while the native arm
  read only the reported run. `run_20260926_201835` executed 8 non-duplicate phases
  (402 were `identical_fp_already_passed`) and all 8 died on
  `Generating kernel source resulted in error 4` = `overflowedResources == 4` =
  **Occupancy limit** in the ZZ/double assembly writer → 0 native cells → every family
  `measured_cells=0`, `per_cell_verdicts=[]`, all 38 deck cells RED/MISSING at 0.0.
  The zeros were deterministic, not random.
- **Native arm is now whole-db.** `port_tensile._native_records_all_runs()` aggregates
  every `gfx90c_runs/run_*` dir's CSVs plus every registry `benchmark_result` row
  (deduped on phase/fingerprint/GFLOPS), each stamped with `source_run`;
  `_native_analytics_all_runs()` does the same for coverage/RED/ORANGE. Winners —
  including prior older winner runs — are picked across all history, matching how the
  spoof arm already worked. `gfx900_ref_*` is never admitted as native.
- **Delta-semantics bug FIXED (columns did not reconcile with the percentage).**
  `delta_pct` was computed from the cell's **max raw sample** on both arms while the
  report's "Best native median" / "Spoof median" columns displayed **medians**, so the
  displayed ratio never matched the printed delta (CC 192: displayed 31.4 vs 31.5 =
  −0.3%, reported −6.1% from underlying 40.49 vs 43.12). All statistics are now
  **per-kernel-median-first** so one lucky seed cannot decide a verdict, and the
  default `best_median` is exactly `native_best_median / spoof_median - 1` — the deck
  winner's per-kernel median vs the floor's median of per-kernel medians, term for
  term with the two displayed columns.
- **Kernel medians are keyed by source run.** The same `(phase_id, fingerprint)`
  benchmarked by two runs was pooled into a single "kernel median", averaging across
  runs; it is now one median per (run, phase, fingerprint).
- **Rendered columns can no longer disagree with the delta (second delta bug).** The
  two A/B columns were hard-wired to "Best native median" / "Spoof median" regardless of
  the basis in use, so switching basis silently re-broke the guarantee fixed above. They
  now render `native_value` / `spoof_value` — the operands actually divided — under
  basis-aware headers (`report._BASIS_HEADERS`). Verified 0 mismatches in JSON and in all
  38 HTML rows (residual ≤0.44pp = 1-decimal display rounding).
- **Default comparison basis is now `winner` = BEST vs BEST** (both arms' best
  per-kernel median), the drop-in-replacement question: replacing shipped kernel X with
  native X' compares the two arms' best candidates. `winner_clock` / `median_clock` add
  telemetry adjustment; `floor_best`, `strict`, `best_median`, `median`, `throttle`,
  `best` remain selectable. All statistics are per-kernel-median-first, so "best" means
  the best *kernel* over its seeds, never the single luckiest seed.
- **Telemetry-adjusted bases implemented and independently verified.** Each kernel's
  median is scaled by `sclk_ref / sclk_measured` from its own phase's sustained clock,
  with ONE shared corpus-wide `sclk_ref` (1800 MHz) so neither arm is rescaled in its
  own favour. Per-phase clock comes from `logs/telemetry.csv` (busy-filtered median,
  >= 3 samples, idle floor excluded). Verified against an independent recompute from the
  raw benchmark CSVs + telemetry: 38/38 cells match on both the raw best and its
  normalized twin.
- **Two guards stop the clock adjustment from producing confident nonsense.**
  (1) A phase whose only busy samples sit at the 400 MHz idle clock is dropped, not
  scaled — scaling it 4.5x let a 20.7 GFLOPS kernel "win" a cell at 93.0 GFLOPS;
  genuinely throttled phases (0.9-1.2 GHz) are kept. (2) `CLOCK_MIN_COVERAGE = 0.5`
  gate, applied SYMMETRICALLY: a clock-adjusted best is only comparable if drawn from
  the same population as the unadjusted best, and at 9% coverage (CC cells) the eligible
  subset's max sat 52-67% low, flipping CC to native wins. Below the gate both arms fall
  back together to the unadjusted twin (`winner_clock` -> `winner`) and report
  `clock_adjusted: false`.
- **The native arm has no clock data, so `*_clock` is honestly inert today.**
  `run_20260919_213727` (4,896 of 6,790 native records) has no telemetry file;
  `run_20260920_235815` has 458 all-idle rows and predates `phase_id` tagging. Native
  clock coverage is 0.000 on all 38 cells, so every `*_clock` run degrades to its
  unadjusted twin with a printed warning. The spoof arm is well covered (mean 0.74,
  1,719 tagged phases), so the machinery is real but cannot be applied symmetrically
  until native is re-benchmarked with the phase-tagging sampler. Adjusting only the
  spoof arm would deflate the floor and flatter the deck.
- **Winner provenance in the report.** `analytics.compute_native_vs_spoof_delta` now
  reports `native_winner_run`/`native_winner_phase`/`native_runs`/`n_native_runs` per
  cell; `ABVerdict` + the JSON/HTML carry them, and the HTML provenance line states the
  native arm scope. An empty native arm now prints a loud warning and the summary says
  so, instead of rendering a clean-looking all-zero grid.
- **Measured result on the new default (best vs best): 14 WIN / 10 TIE / 14 LOSS.**
  Native arm = 6,790 cells from 2 runs (`run_20260919_213727`, `run_20260920_235815`);
  coverage **100% of deck cells in all 7 families** (was 0%), **0 RED / 13 ORANGE /
  25 GREEN**. Losses are modest and cluster at large shapes (HH:4096 −14.5%,
  HH:2048 −14.6%, SS:2048 −15.1%); wins are large (HH:256 +272%, SS:256 +227%,
  HH_HPA:512 +188%) but are partly a pool-size artifact, since the floor's best is a max
  over ~303 kernels/cell vs the deck's ~75. On stricter bases the deck fares worse:
  `floor_best` 3/7/28, `strict` (per-cell dominance) **0/0/38**, `median` 23/7/8.
  `overall_pass=False`.
  **Caveat:** the basis is pool-size biased against the deck — the floor averages 303
  candidate kernels per cell vs the deck's 75 (larger in 35/38 cells), so a `max` over
  the floor is biased upward. Part of the 28 losses is that asymmetry, not kernel
  quality. The decisive artifact remains a per-fingerprint pairing (native X' vs shipped
  X), which per-cell rollups cannot express. Per-cell numbers in `results.md` §10.
- **Reference floor chain complete.** `gfx900_ref_20260926_201843_resume`: 1,212
  targeted, 808 completed, 404 failed → chain **1,881 completed / 404 unique failed =
  2,285 decided, 0 undecided**. 116 base failures retried and failed again; 288 new.
- **Open (not fixed here).** `_write_phase_config` still returns early on the
  assembly-class gate without writing the config, so `execute_phase` launches Tensile
  against a missing path — the 121 rc=1 bucket. Reference-deck generation should
  pre-filter those configs. Tracked in `implementation_plan.md`.

## [Named workload cells + reference-floor A/B fix + HPA case-sensitivity] 2026-09-26

- **A/B floor binding bug FIXED (`ccd7fed`).** `port_tensile.py` `_compute_ab_verdicts`
  bound the spoof floor from the wrong tuple slot (`ref_records, _ = _ab_records_from_csv(
  ref_dir, force_arm="spoof")` puts all records in the second element), silently dropping
  the floor → "0 WIN / 0 TIE / 0 LOSS" reports. Corrected; the same run now yields
  **30 per-cell verdicts (18 WIN / 9 TIE / 3 LOSS)**.
- **Workload-cell naming (fix.md applied, `ccd7fed`).** Every measured row is stamped
  `arm` + `cell_key` (`"<FAMILY>:<SHAPE>"`) + `kernel_key` via `gfx90c_common`
  `cell_key()`/`kernel_key()`/`shape_side()`; `analytics.compute_native_vs_spoof_delta`
  now pairs by workload cell `(family, dtype, shape)` on BOTH arms (best-of-cell median,
  ±5% tie) instead of spoof-per-fingerprint vs native-per-cell.
- **Live DB stamped (`ccd7fed`).** `gfx90c_results/registry.db` backfilled — 3,369
  measured rows carry `cell_key`/`arm`/`kernel_key`; pre-backfill backup at
  `backups/2026-09-26_impl/registry.db`. Added `idx_cell_key` index — NOTE:
  `registry.py` does not create it, so a fresh DB lacks the index.
- **HPA case-sensitivity FIXED (`58245c8`).** `_write_phase_config` matched
  `"HPA"/"HS_HPA"` case-sensitively, so lowercase agent mutants (`mutate_hh_hpa_…`,
  `mutate_hs_hpa_…`) ran as plain FP16 without `HighPrecisionAccumulate`/
  `DestDataType`. Now uppercases + consults `FamilyLabel` (consistent with
  `assembly_class_valid`); `agent.mutate_and_feed` stamps `FamilyLabel` on mutants.
  Verified against all 6 label shapes (deck / reference / mutant). Closes the
  round-2 HS_HPA pending item: HS_HPA 16 cells run at MT64x64x16 with the
  `GLVW==VW-or-1` mirror predicate.
- **Analytics cleanup (`58245c8`).** `analytics.py` dropped unused
  `cell_key`/`kernel_key` imports.
- **Corrections to earlier entries (append-only).** The "Shim removed:" bullet's
  "deleted" claim is technically inaccurate — `tensile_gfx90c_port/` source is gone
  from git, but shim-era `__pycache__` `.pyc` residue remains on disk (untracked;
  scheduled for cleanup). The bottom "Upstream baseline" section's "pristine HEAD,
  shim-only" wording is fully superseded by the native 2-file `Common.py` +
  `AsmCaps.py` patch entry.

## [Graceful gfx900-reference resume + completeness gate] 2026-09-26

- **Reference runs are now resumable.** `tensile_library.reference_chain()`
  returns the newest completed, non-smoke `gfx900_ref_*` run plus its
  `resume_of` ancestors as one logical floor; `port_tensile` `--gfx900-reference
  --resume` creates `gfx900_ref_<ts>_resume` targeting ONLY the base deck's
  phases with no completed verdict (unattempted + failed-again once), reusing
  the completed base phases as-is (`_chain_phase_sets()` distinguishes
  completed vs decided). A/B verdicts (`_compute_ab_verdicts`) and family
  timings now recall the WHOLE chain, not the newest run alone, so cells split
  across base and resume are never lost.
- **`--auto` completeness gate.** If a completed reference run exists but the
  deck has undecided phases, `run_auto` now resumes it first and refuses to
  proceed with ANY tuning until `_reference_remaining() == 0` (every shipped
  phase has a verdict — completed, or enumerated-invalid `failed`). Previously
  a truncated (47%) run was silently recalled as the floor and the remaining
  ~1096 phases were permanently dropped. `--gfx900-reference --resume` alone
  returns `noop` when the deck is already complete.

## [Run-wide telemetry + gpu_busy_percent path + peak-table reconciliation] 2026-09-25

- **Telemetry is now run-wide, not per-phase.** `telemetry.py` `TelemetrySampler`
  gained `set_phase()` + a `phase_id` column and a restart-safe `start()` (header
  written only when missing; never truncates). `port_tensile.TensileDriver` keeps
  one sampler per run dir via `_ensure_telemetry()`, tagging every row with the
  active phase in `execute_phase` and clearing the tag in its `finally`. Previously
  each phase created a fresh sampler whose `start()` truncated `telemetry.csv`, so
  a ~9.5h run kept only the last (~46s, itself an idle failed-at-compile ZZ phase)
  window — the root cause of "telemetry only measured for ~40 seconds".
  `run_gfx900_reference` stops the sampler on its run-dir swap. `report.py` reads
  the CSV by column name (`csv.DictReader`), so the extra column is transparent.
- **gpu_busy_percent path hardened.** Primary discovery now requires the candidate
  card dir to actually expose `gpu_busy_percent` (rejects connector dirs like
  `card1-DP-1/device`, which symlink to the card node and have no busy file); the
  `/sys/class/hwmon` fallback no longer appends `/device` (double-suffix never
  resolved → busy would always read 0 if the fallback ever fired), and a sampler
  that cannot find the busy file prints a one-time warning instead of silently
  logging zeros. The surviving run's busy=0 was *correct* data — its last phase
  failed during compilation (GPU never woke; sclk pinned 400 MHz).
- **Peak/ceiling tables reconciled** (`gfx90c_common.py` is the single authority;
  `gfx90c_theoretical_limits.md` §5 now quotes its exact values). Added the missing
  BF16 `1109` and INT8 `881` entries to `REALISTIC_CEILINGS`; §5 updates 1119→1118.7
  (SS/CC/HH_HPA/HS_HPA), ~98→98.6 (ZZ); §2.1 notes `PEAK_GFLOPS['FP64']` stores the
  rounded 101 (vs derived 100.8). Removed the stale "(replaced by …)" comment in
  `gfx90c_common.py`.

## [Shipped-dat gfx900 reference floor + red/orange cell semantics] 2026-09-25

- **New `tensile_library.py`.** Parses the system ROCm `TensileLibrary_*_gfx900.dat`
  binaries directly (msgpack length-prefixed solution names, marker-canonicalized
  `Cijk_...`), unions every installed ROCm prefix (`/usr` + `/opt/rocm`), emits one
  spoof phase per shipped kernel with its MT/WG/VW/DepthU/GSU knobs, and pins the
  result once at `gfx90c_results/gfx900_shipped_manifest.json` (pin-on-first-load,
  `refresh=True` re-scans). Live expected counts: SS 959, DD 96, HH 223, CC 64,
  ZZ 26, HH_HPA 424, HS_HPA 493 → **2,285** distinct shipped kernels (the old 3,066
  was per-file token counting). Config generation validated on all families
  (2,164/2,285 assembly-legal under the class gate).
- **One-time reference run (`--gfx900-reference`).** Benchmarks every shipped
  gfx900 kernel once (ScheduleName `vega10`, `FAMILY_SHAPES` deck) into a dedicated
  `gfx900_ref_*` run; later A/B `_compute_ab_verdicts` *recalls* it forever instead
  of re-running per-run baselines. The 8 hand-authored `*_baseline_*` phases were
  removed from `phases.yaml`; `run_auto` now just checks the reference run exists.
- **RED = MISSING, ORANGE = <50%.** `analytics.classify_cell_status` classifies each
  gfx900 contract cell `(family, deck-shape)` from `FAMILY_SHAPES` (38 cells):
  RED if unmeasured this run, ORANGE if best measured candidate is below the
  family realistic ceiling threshold, else GREEN. `report.py` gate/summary/JSON/HTML
  reworked to these semantics, with per-family coverage denominators now derived
  from the pinned manifest and the reference-run provenance embedded in the report.
- **Perf fix.** `_ab_records_from_csv` re-parsed the 9k-line `phases.yaml` per CSV
  (hundreds of parses per report); it now builds a phase-id → phase dict once
  (~120s → ~1s per report regeneration).

## [Cruft audit + convergence contract + CLI stage dispatch] 2026-09-25

- **Convergence contract fixed (`agent.converged()`).** Removed the `iteration < 10`
  bypass; budget exhaustion is now a STOP that returns `converged=False` (never
  reported as a pass), and a CV ≤ 15% per-cell stability gate was added via the new
  `CellAnalytics.cv` field. Criteria: no below-ceiling cells, ≥3 configs/cell, ≥2
  independent runs/cell.
- **Mutation family loss fixed (`agent.mutate_and_feed`).** Winners now harvest their
  `.family` token, mutation derives the Tensile DataType from `FAMILY_DTYPE_CHAR`
  instead of raw dtype char, so HH / HH_HPA / HS_HPA winners no longer silently fall
  back to FP32. Harvest/emit now carry `is_below_ceiling`; agent construction dropped
  the unused `max_iterations`/`red_threshold_pct` kwargs (driver updated).
- **Single-path retirement.** Removed dead `classify_retirement_tier`,
  `apply_d2_4_protection`, `classify_tie`, `should_repeat`, `classify_stability`
  (policy.py) and registry `append_records`/`get_run_info`/`get_latest_run_dir`/
  `has_phase_passed`; retirement is the single Tier-2 path via
  `check_retirement_eligibility` + `should_run`/`is_config_retired`.
- **`--stage 1-7` dispatch + bugs.** `create_run` now recognizes stage `"7"` (the old
  `"report" in args.stage` never matched the number, minting stray runs); read-only
  stages 2/4/5/7 no longer create runs; stages 1-5 have explicit handlers (preflight /
  candidate plan / benchmark / retirement sweep / analytics summary).
- **`--force` no longer a no-op.** Wired as `opt_in_identical_skip=False` through
  `run_auto` (flag was previously parsed but never read).
- **RED semantics rename.** `is_red` → `is_below_ceiling` (report RED = missing
  contract cell stays untouched); `Red` → `below_ceiling` in harvest/convergence.
- **Coverage metric fixed.** `_compute_family_coverage` denominator is now the
  contract deck (`FAMILY_SHAPES[family]`, coverage = deck cells measured); the
  shipped-kernel footprint moves to informational `footprint_pct` in the report.
- **Centralized maps.** `REALISTIC_CEILINGS` (SS 1118.7 / DD 98.6 / HH 2461.0 /
  ZZ 98.6 / CC 1118.7 / HH_HPA 1118.7 / HS_HPA 1118.7) and `FAMILY_DTYPE_CHAR` are
  now both canonical in `gfx90c_common.py`; `tensile_library.py`, `analytics.py`,
  `scheduler.py`, `report.py`, `agent.py` import them (family decks use
  `MAX_WAVES_PER_CU` instead of a hardcoded 40).
- **Dead code / imports / state removed.** Local unreferenced `TelemetrySampler`
  class + `termios`/`tty`/`Set`/`PEAK_GFLOPS` imports in `port_tensile.py`;
  `MANIFEST_KEY`/`expected_kernels_from_manifest` (tensile_library.py);
  `persist_analytics`, `THEORETICAL_PEAKS`/`DDR_ROOFLINE_GBPS` deps (analytics.py);
  `compute_ab_verdict`, `_family_to_dtype`/`mapping_path` (report.py);
  `classify_bound_class` (scheduler.py); orphan
  `tools/__pycache__/merge_draft_gfx90c.cpython-314.pyc`.
- **Regression caught & fixed during the audit.** `_KNOWN_FAMILIES` (analytics) lost
  its lowercasing when re-derived from `FAMILY_DTYPE_CHAR`, breaking every
  `extract_family_from_phase_id` match, and the `dtype_to_family` fallback collapsed
  the ambiguous `'H'` char to `HS_HPA`. Both fixed (lowercase prefix set; first-wins
  char map → `'H'` = HH). Regenerated report identical to baseline: `Acceptance FAIL:
  0 WIN / 0 TIE / 0 LOSS, 0 RED (missing) / 15 ORANGE (<50% ceiling)`.
- **Docs sweep.** Replaced stale 3,066 pip-count references with the live 2,285
  manifest split in `implementation_plan.md`, `knowledge_base.md`,
  `knowledge_base_final.md`, `incomplete_work.md`; updated RED-list/RED-cell
  terminology and dead-helper mechanism claims; expanded the `gfx90c_common.py`
  single-source-of-truth row.

## [Assembly-class gate + 295-phase deck + draft-merge tooling] 2026-09-20

- **Class-based Assembly gate (`scheduler.assembly_class_valid`).** Faithful to
  the Tensile SolutionStructs rejects reproduced from the 24 draft-run failures:
  GSU>1 on complex, GSU>1 on half+f32-accum (HPA), GSU>1 on half without
  `AssertFree0ElementMultiple>=2`, and `DepthU * BytesPerElement > StaggerUStride`
  (complex DU>=32) are all illegal on gfx90c (no MFMA). Wired at BOTH seams:
  `scheduler.validate_config` (mirror gate) and `port_tensile._write_phase_config`
  (autoskip — illegal cells never written to the Tensile deck). Class-based, so
  ANY future same-class cell is caught pre-run, not just the 24 triaged. The
  loky/semlock ValueError from the draft re-runs was benign stderr noise
  (joblib>=1.5.2 is cosmetic only); the 24 were solution-validity rejects.
- **331 → 295 phases.** Regenerated `phases.yaml` through the new gate: the 36
  GSU-2/4/8 cells on HH/HH_HPA/HS_HPA dropped (HH 56→40, HH_HPA 32→20,
  HS_HPA 28→20). 0 illegal cells, 0 fp/phase_id dups, 0 validate_config fails.
- **CASE3 merge tool (`tools/merge_draft_gfx90c.py`).** Append-only import of the
  draft run's 4962 benchmark records under the MAIN fp scheme (FamilyLabel-tagged;
  draft target_id fps were NOT portable). `.bak`-first on both registries, no
  dedup/deletion/id-reuse, retirement left to the codebase's 3-tier gate
  (policy.py:240). Dry-run reports exactly 2 retirement-eligible fps — the two
  A/B baselines (48 samples each, 2 independent runs); everything else needs a
  2nd shell from our deck. run2 added nothing new beyond the baseline 2nd shells
  + 6 auto SS@1024 cells (3 samples each, single run — reference only).
- **CASE3 import applied (run1 only).** `--runs run1` (default), run2 skipped per
  decision — its only value was the baseline 2nd shells, and the codebase gate
  can reach retirement later with 2 independent runs. Executed 2026-09-20: 445
  phase entries (baseline baselines_ss_native/spoof + 443 wide cells) + **4896
  benchmark records** appended from run_20260919_213727. Registers run1 in the
  `runs` table (completed). Backups: `backups/main_registry.db.bak` +
  `backups/draft_registry.db.bak` (draft DB untouched — read-only). Retirement
  gate re-run post-import: 0 forced retirements (no fp has ≥2 runs yet —
  baselines are single-run in main, eligible only after their 2nd shell).
  Note: first apply attempt had a phase-dedup bug that dropped the per-sample
  records after the 1st per phase (4896→445); fixed (dedup phases only, records
  always appended) and re-applied cleanly from pristine main DB. Backups use
  distinct `main_`/`draft_` tags (initial name collision would clobber main's .bak).
- **WIN/LOSS classification from merged run1** (`potential_configs.md` §6.2–§6.5).
  Empirical per-cell class vs our carried incumbents: **24 WIN cells** (draft
  best-median beats incumbent — hh 1024³ +99%, hh 2048³ +85%, hs_hpa 2048³ +70%,
  dd 512³ +68%, ss 1024³ +66%, cc 512³ +65% top margins) and **5 LOSS cells**
  (cc 256³ −23%, hh_hpa 1024³ −21%, ss 2048³ −17%, zz all RED ~23% of 98.6
  ceiling, ss 256³ parity). Next-run policy: WINs get a 2≥-shell then ≤2-knob
  mutations (per-cell table §6.2); LOSSes never re-run their fp — replaced by
  fresh structural candidates proposed in §6.3 (MT128/TT8/DUs/GSU-1, class-gated).
  Spend order §6.5: WIN shells → WIN mutations → new-wide-for-LOSS → GSU-1@4096 SS.
- **Next-increment proposal (`potential_configs.md` §6).** Wider-for-LOSS (CC/ZZ
  structural, HS_HPA admitted parms, SS GSU-1@4096), narrower-for-WIN (DD closed,
  SS/HH no double-spend), 2≥-shell-first spend order, strategy-scoped retirement.

## [Wide gfx90c candidate deck (331 phases) + --auto baseline-anchored one-command integration] 2026-09-20

- **Wide deck replaces the 304-phase manifest.** `phases.yaml` regenerated from
  `/tmp/opencode/gen_wide_deck.py`: 331 phases (SS 105, HH 56, DD 44, HH_HPA 32,
  CC 32, ZZ 32, HS_HPA 28, + 2 ss A/B baselines), every config passing the
  scheduler mirror (`validate_config` + `_validate_tensile_loads` GLVW guard) and
  per-shape M/N≥MT, K≥DepthU exact-size blockers — 0 invalid of 331.
  Structure: one phase per (family × contraction-pattern × config) bundling ALL
  family shapes, plus shape-matched underfill-GSU phases (small squares only, so
  GSU2/8 is not misapplied to large ALU squares) and DDR/GEMV phases.
- **fp-collision fix:** prior HH_HPA vs HS_HPA phases shared identical configs →
  identical sha256 fp → policy `has_fp_passed` identical-fp skip would drop the
  second family on re-runs. New deck keeps `FamilyLabel` (SS/HH_HPA/HS_HPA) in the
  fp input; all 331 phase_id/fp/config triples are unique.
- **Anchored `--auto`:** `run_auto` now runs Phase-0 preflight (non-fatal), then
  the spoof/native baseline A/B pair first as the anchor, then all manifest phases
  in order, then the convergent harvest/mutate loop — single overnight command.
- **A/B verdict pipeline fixed (was producing 0 verdicts):** completed/recovery
  records now carry `schedule_name`/`dtype`/`shapes`/`num_benchmarks` so arms
  resolve; `run_ab_test` now sources per-cell medians from `2_BenchmarkData` CSVs
  (which hold GFLOPS) grouped by arm instead of from registry records (which never
  carried GFLOPS). Verified with a fabricated 1:1 native/spoof cell set (WIN).
- **Accounting + telemetry fixes:** `phases_executed` counts only real executions
  (interrupted/skipped-by-user excluded) and reports `phases_skipped`; inline
  buggy sampler replaced by `telemetry.py`'s `/sys/class/drm/cardN/device`
  discovery (old `hwmon_dir.parent.parent` resolved to `/sys/class`).
- **Breaking CLI:** `--phases` removed (was an alias for `--targets`; the historic
  numeric `--phases 1 31 25` matched nothing). Use `--targets` explicitly.

## [HS_HPA fixes applied: manifest re-parameterized + scheduler mirror models the GLVW guard] 2026-09-19

- **Fix 1 (manifest):** the 16 `hs_hpa` phases in `phases.yaml` are re-parameterized
  from the rejected MT64x64x8/TT4x4/VW4 deck to the guard-legal MT64x64x16/TT4x4/VW4/
  DU16 parameterization (admitted `1/1 after SolutionStructs`, assembles for gfx90c).
  The accepted deck previously logged `Your parameters resulted in 0 valid solutions`
  on every pass (12 signalled, 0 valid); with Fix 1 all 16 `hs_hpa` cells are guard-legal.
- **Fix 2 (scheduler mirror):** `_validate_tensile_loads` (scheduler.py) now models the
  stock-Tensile non-MI assembly `GLVW==VW-or-1` predicate (`SolutionStructs.py:4583-4596`)
  that rejected the old deck — the mirror no longer pre-validates decks the guard rejects.
  Verified by 6 unit tests + a 304/304 phases.yaml sweep.
- Resolves the "Fix (pending)" bullet in the prior HS_HPA root-cause entry above.

## [Legacy-silence clauses enforced] 2026-09-19

- `claude.md` §8.1 written: removed machinery is **never** named in code or docs;
  history's only sanctioned homes are `changelog.md` + frozen `prior_*`; `todo.txt`
  is **USER-ONLY** (agent never reads/touches it).
- Scrub pass: `implementation_plan.md` stale references to removed launcher
  machinery reworded (entrypoint-only wording); live docs grep-clean.

## [HS_HPA rejection root-caused: Tensile GLVW==VW-or-1 generator guard; guard-legal configs found] 2026-09-19

- **Exact rejection isolated** (driver scratch `/tmp/opencode/e2e_hpa` +
  `PrintSolutionRejectionReason`): stock Tensile non-MI assembly guard
  `GlobalLoadVectorWidth{X} must be == VectorWidth or == 1`
  (`SolutionStructs.py:4583-4596`; source comment: "Restrict GRVW/VW combos so
  shift-ptr logic will work"). Fires when `setGlobalLoadVectorWidth`
  (`:2010-2047`) pv-reduces GLVW 4→2 for 64x64x8/TT4x4/VW4 tabs
  (totalElements 512 < NumThreads·GLVW = 1024, pv=2). The predicate is
  **isa-independent** (rejects gfx900 identically) — a generator/representation
  restriction, NOT a gfx90c HW/ISA limit and NOT an assembler failure.
- **Same HS_HPA intent admitted by stock Tensile on native gfx90c:**
  - MT64x64x16/TT4x4/VW4/DU16 → `1/1 after SolutionStructs`; gfx90c kernel
    assembles (`Kernels.so-000-gfx90c.hsaco`, `TensileLibrary_gfx90c.co`).
  - MT64x64x8/TT4x4/VW2/DU8 → `1/1 after SolutionStructs` and `1/1 after
    KernelWriter`.
- The 0-solution HS_HPA registry records are a parameterization collision with a
  Tensile generator guard (not a hardware incapacity); HS_HPA tuning resumes on the
  two guard-legal parameterizations.
- **Fix (pending):** scheduler `_validate_tensile_loads` lacks the `GLVW==VW-or-1`
  predicate under which the 64x64x8 deck fails — add it to the mirror.
- Docs updated: `potential_configs.md` §4 + §5.3 item 7, `implementation_plan.md`
  technical findings.

## [Native .env + toolchain resolution (industry standard) — custom chains removed] 2026-09-19

- **`.env` loading → `python-dotenv` `load_dotenv()`** (industry standard; never
  overrides live env). The hand-rolled `_load_dotenv` parser and the
  `*_CANDIDATES`/`_first_existing_*` probe chains are gone from
  `port_tensile.py`; `requirements.txt` adds `python-dotenv`.
- **ROCm discovery → native tools only:** `hipconfig` (ROCM_PATH/HIP_PATH/
  HIP_CLANG_PATH) + `shutil.which` for binaries on PATH. `.env` and README §6
  slimmed to `TENSILE_ROOT` + optional overrides; no candidate chains.
- **Guardrail added to `claude.md` §5:** never re-invent known-solved problems —
  OS/stdlib/industry-standard library wins (`.env`→python-dotenv,
  discovery→`hipconfig`+`shutil.which`, locks/DB→stdlib, CLI→`argparse`).
- **Validated:** Phase-0 preflight 4/4 and a suite-exact ActiveE2E
  (`phase_ss_Ailk_Bjlk_256x256x256_mt96x96x16_tt6x6`, rc=0, Actual Solutions 1/1,
  `TensileLibrary_gfx90c.co` + `Kernels.so-000-gfx90c.hsaco`) with the native
  resolution (scratch `/tmp/opencode/e2e_b`, isolated).

## [Docs ecosystem governance: shim & legacy-suite silence, todo.txt user-only] 2026-09-19

- **Rule codified in `claude.md` §8.1:** the import-time shim no longer exists and
  is never mentioned in code, docs, or prose; its history lives only in this
  changelog and the frozen `prior_*` files. The prior-campaign shell suite
  (`run_gfx90c_suite.sh`) is referenced only inside `prior_*`.
- **`todo.txt` is a user-only file:** the agent never reads, writes, or touches it.
- **`claude.md` native-support wording aligned** to "2-file minimal Tensile patch"
  (`Tensile/Common.py` + `Tensile/AsmCaps.py`).

## [Distro-agnostic ROCm toolchain resolution] 2026-09-19

- **`.env` fleshed out for both install styles:** ROCm paths are now probed via
  `*_CANDIDATES` ':'-chains (`ROCM_PREFIX_*`, `ROCM_BIN_*`,
  `ROCM_LLVM_BIN_*`, `TENSILE_ASSEMBLER_*`, `TENSILE_ASSEMBLER_FALLBACK_*`);
  first existing entry wins, so AMD-installer (`/opt/rocm`) and Fedora-RPM
  (`/usr/bin` + `/usr/lib64/rocm`) hosts both work from one `.env`.
- **`port_tensile.py`:** new `_first_existing_dir` / `_first_existing_file` /
  `_resolve_rocm_paths()` used by `_get_tensile_env` (PATH injection + subprocess
  `ROCM_PATH`/`HIP_PATH`) and the `--assembler` selection. Explicit env values
  still win when they point at existing paths; stale values fall back to the chain.
  Verified on live host plus synthetic AMD-only and Fedora-only scenarios
  (`/tmp/opencode/test_rocm_probe.py`).
- **README §6 rewritten** for the candidate-chain schema + fixed the residual
  "28-family coverage metrics" wording on the `report.py` row.

## [Repo relocation & report/driver hygiene] 2026-09-19

- **`file:///` references removed:** docs previously pointed at the dead
  `GPU/backrocm/porting_tensile/attempt2` path; README links now relative.
- **Hardcoded locations → `.env`:** `port_tensile.py` loads `TENSILE_ROOT`,
  `ROCM_*`, `HIP_*`, `TENSILE_ASSEMBLER(_FALLBACK)` from `.env` (shell env >
  `.env` > defaults). `.env` created in repo root.
- **Early-quit key `'e'`:** ends the run cleanly after the current phase /
  iteration (run stays `completed`, metadata `end_after_iteration: true`).
- **Verbose logs:** Tensile stdout/stderr are teed live to console (prefixed
  `[tensile]`) and to `logs/.../stdout.log`/`stderr.log`; `TENSILE_VERBOSE=1`
  appends `--verbose` (Tensile PrintLevel 3).
- **Acceptance report HTML de-hardcoded:** Problem space / coverage matrix /
  telemetry sections are now data-derived (cell analytics, registry
  started→completed timing, `logs/telemetry.csv` medians/peaks). Fabricated
  VRAM / SCLK / MCLK / GPU-busy rows dropped (sensors unavailable on this APU).
- **Report dtype fix:** `extract_dtype_from_phase_id` now uses the token family
  parser (was a regex that returned `'unknown'` for `phase_ss_spoof_baseline_vega10`);
  `'auto'` family mapped to `'S'`. The 67 red cells previously logged as
  dtype `unknown` now resolve to real dtypes.

## [Native gfx90c support replaces the import-time shim] 2026-09-19

- **Root cause of the shim:** Tensile's `populateCapabilities` runs before config
  merge, so a config-parse-time ISA injection is too late; 2026-08–09 proved the only
  shim-compatible hook was import time (`tensile_gfx90c_port/sitecustomize.py` on
  `PYTHONPATH`, 3 injections: `SupportedISA`, `architectureMap`, `getCapabilitiesCache`
  seeded from gfx90 just so gfx90c was not probed-and-rejected).
- **Replaced by real in-tree support** on Tensile latest `develop_deprecated` HEAD
  (verified equal to `origin/develop_deprecated`, `e8a8999e`): 3 minimal bookkeeping
  entries in `Tensile/Common.py` (`SupportedISA` `(9,0,12)`; `architectureMap`
  `gfx90c`/`:xnack+`/`:xnack-`) plus `Tensile/AsmCaps.py`, a first-class `(9,0,12)`
  capability entry written from scratch from LLVM `FeatureISAVersion9_0_C`
  (`HasMadMixInsts`; no MFMA / dot / dl-insts / VOP2-fmac / WMMA / kernarg-preload).
  No cloning or deriving from any other ISA.
- **Validated:** written caps == real assembler-derived gfx90c caps (0 mismatches,
  ROCm 6.4); roundtrip `gfxName((9,0,12))`/`gfxArch('gfx90c')`; `GetArchCaps((9,0,12))`
  needs no change. End-to-end with the driver's own known-good config from
  `phases.yaml` (`phase_ss_Ailk_Bjlk_256x256x256_mt64x64x16_tt4x4_3`): native
  `# Detected GPU 0: gfx90c`, "Actual Solutions: 1 / 1", kernel built, loaded
  `TensileLibrary_gfx90c.co` / `Kernels.so-000-gfx90c.hsaco`, benchmarked 434 GFlops
  @ 256³, exit 0.
- **Shim removed:** `tensile_gfx90c_port/` deleted; `port_tensile.py`
  `_get_tensile_env`/`run_preflight` stripped of shim wiring and `TENSILE_REPO_ROOT`;
  grep-clean across driver modules. Phase-0 preflight passes 4/4 shim-free.
- **Docs updated** (knowledge_base §2/§3, README preflight, mapping, claude.md tree
  + PYTHONPATH, implementation_plan) to describe native support. The "pristine HEAD,
  shim-only" wording in the `Upstream baseline` section above is **superseded** by
  this entry.

## [Phases.yaml Fixes, Telemetry v2 & Client/Bench Split PoC] 2026-09-14

- **`phases.yaml` — 48 Invalid Entries Repaired:** Reconciled NLCA and DepthU divisibility rules via in-place fixes (NLCA 3→1 ×46, DepthU 4→16 ×2); verified all 230 contraction entries pass `_validate_tensile_loads`. Archived backup at `archive/phases_20260914_prefix.yaml`.
- **`telemetry.py` — Minimal Non-Root Sysfs Telemetry:** Extracted sampler into dedicated clean module reading world-readable sysfs (`0644`), correctly resolving `mclk_hz` via `pp_dpm_mclk` parsing (resolving dead 0 mclk bug) and supporting APUs (`power1_input` fallback).
- **Client/Bench Split PoC:** Verified Tensile `--prebuilt-client` mechanism in `/tmp`, eliminating redundant per-phase CMake host client rebuilds.

---


- **`port_tensile.py` — Completion Record Recovery:** Added `end_record_logged` flag + finally-block recovery logging. If Tensile phase completes successfully but normal logging path is interrupted (e.g., Ctrl+C during final processing), the finally block ensures completion record is persisted to registry.
- **Root Cause:** Run 213103 completed phase (PASS in stdout.log, CSVs generated) but only "started" record existed in DB — no "completed" record. Normal logging path may have been interrupted before `append_record()` call.
- **Fix Mechanism:** Flag tracks successful `append_record()` call; finally block checks if result exists but flag is False, then logs completion record with appropriate status.

---

## [Immediate Keypress Listeners + MacroTile Format Fix] 2026-09-13

- **`port_tensile.py` — Raw Mode Keypress Listeners:** Added `tty.setraw()` to both cooldown and phase execution key listeners for immediate 's'/'q' detection without requiring Enter press. Terminal settings restored in finally blocks.
- **`port_tensile.py` — MacroTile Format Fix:** Corrected Tensile MacroTile schema from invalid `[[M0, M1, DepthU]]` to valid `[[M0, M1]]` format. DepthU now emitted as separate ForkParameter. Fixes "Invalid parameter value: MacroTile = [64, 64, 8]" error causing CC/DD phase failures.
- **Root Cause:** Tensile expects 2D array for MacroTile dimensions only; DepthU is a separate parameter, not third array element.

---

## [Report Generation Coverage Fix for Failed Phases] 2026-09-13

- **`report.py` — Family Coverage Detection:** Enhanced `_compute_family_coverage()` dtype matching to properly detect family-specific cells (CC/DD/ZZ) when phases fail during execution, ensuring accurate coverage statistics even when benchmark CSVs are missing due to configuration errors.
- **Root Cause:** Previous implementation only matched dtype (FP64/FP32) but not family names (CC/DD), causing coverage reports to show 0 cells for CC/DD families despite phase execution attempts.
- **Impact:** Reports now correctly reflect attempted phase execution even when Tensile configuration errors prevent CSV generation.

---

## [Multi-Threaded Compilation, MacroTile Schema Fix, Cooldown Key Controls & Immediate Reporting] 2026-09-13

- **`port_tensile.py` — Multi-Threaded Clang Compilation:** Set `CpuThreads` dynamically based on available CPU cores (`min(os.cpu_count(), 16)` instead of forced single-thread `1`), accelerating clang assembly build times.
- **`port_tensile.py` — MacroTile Tensile Schema Fix:** Corrected `ForkParameters` emission from invalid `MacroTile0`/`MacroTile1` keys to valid Tensile top-level list `MacroTile: [[M0, M1, DepthU]]` (resolving the `Invalid parameter name: MacroTile0` error in CC/DD runs).
- **`port_tensile.py` — MacroTile0/MacroTile1 Removal:** Added explicit removal of deprecated `MacroTile0`/`MacroTile1` keys from `fork_params` before YAML emission, ensuring Tensile only receives valid `MacroTile: [[M0, M1, DepthU]]` format.
- **`port_tensile.py` — Real-Time Cooldown Key Listeners:** Updated `_apply_cooldown()` to listen for `'s'` (skip cooldown immediately) and `'q'` (gracefully quit run) during thermal sleep.
- **`port_tensile.py` — Immediate Report Generation on Quit:** Ensured `acceptance_report.json` and `acceptance_report.html` are automatically generated and written to `gfx90c_results/` even on early termination via `'q'` or interruption.
- **`README.md` — Usage Documentation:** Added complete documentation for keyboard controls (`s`, `q`), semantic CLI filters (`--family`, `--pattern`, `--shape`), and HTML visual dashboard inspection.

---

## [HTML Dashboard Generator Porting & Integration] 2026-09-13

- **`report.py` — Automated HTML Dashboard:** Ported and unified the attempt1 analytics dashboard generator (`make_report.py`) directly into `AcceptanceReporter.write_html_report()`.
- **Key Features:** Emits dependency-free, responsive dark-mode HTML dashboard (`gfx90c_results/acceptance_report.html`) containing 28-family footprint progress, realistic GEMM ceiling progress bars, per-cell A/B head-to-head comparison cards, and RED-list tracker.
- **Verification:** Tested in `/tmp` POC then integrated into `report.py` and validated with live data.

---

## [Complete 7-Stage Driver Transition & Semantic Target Interface] 2026-09-13

- **`port_tensile.py` — Semantic Target Filtering:** Replaced arbitrary numeric phase arguments with first-class semantic CLI flags: `--family` (`{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}`), `--pattern` (`{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`), `--shape`, `--stage` (`1..7`), and `--targets`.
- **`phases.yaml` — 28 Native Families Populated:** Manifest completely populated with 228 clean targets spanning all 28 mathematical contraction families with anchor problem shapes.
- **Dry-run validation:** Added `--dry-run` to query and verify target matching without triggering GPU execution.

---

## [Tensile YAML Generator Fix, Candidate Tile Validation & CSV Resilience] 2026-09-13

- **`port_tensile.py` — `_write_phase_config` fixed:** Corrected `TransposeA`/`TransposeB` derivation from contraction pattern labels (`Ailk_Bljk` $\to$ NN/FF, `Ailk_Bjlk` $\to$ NT/FT, `Alik_Bljk` $\to$ TN/TF, `Alik_Bjlk` $\to$ TT/TT); fixed `MacroTile0`/`MacroTile1` mapping from string representation; calculated `WorkGroup` dynamic tile ratios; enabled `HighPrecisionAccumulate` and mixed precision `DestDataType`/`ComputeDataType` for HPA families.
- **`scheduler.py` — candidate tile divisibility & workgroup validation:** Added validation check in `validate_config` ensuring `MacroTile` dimensions are strictly divisible by `ThreadTile` dimensions (`MacroTile0 % ThreadTile0 == 0`) and workgroup thread count is a multiple of 64 within $[64, 1024]$.
- **`analytics.py` — CSV header whitespace resilience:** Updated `load_benchmark_csv` with whitespace-stripped fieldname parsing and robust per-kernel GFlops metric extraction for space-padded Tensile CSVs.
- **Verification:** Unit tests passing 100%; benchmark CSV parser validated against 96 real kernel measurements (`run_144805`, `run_150517`, `run_151227`) showing peak 928.0 GFlops at $1365^3$.

---

## [Ctrl+C signal handler + stale-run cleanup + run status fix] 2026-09-13

- **`port_tensile.py` — Ctrl+C signal handler fixed:** `_signal_handler` now calls
  `sys.exit(130)` after killing the child process group via `os.killpg`. Previously the
  handler only set `_stop_requested=True`; the driver continued running normally after
  killing the subprocess instead of terminating. Exit code 130 = standard shell Ctrl+C.
  Run status is written to registry as `interrupted` before exit.
- **`registry.py` — `cleanup_stale_runs()` added:** bulk-UPDATE of any `status=started`
  rows to `interrupted` on driver init. Cleans up 3 orphaned runs from this session
  (run_140507, run_141220, run_143006 all set to `interrupted`). Non-destructive: only
  updates status column, does not touch records.
- **`port_tensile.py` — run status semantics:** `run_phases()` now marks run as
  `interrupted` if `_stop_requested` is True at completion, instead of always writing
  `completed`. The `run_auto()` path unchanged (it also sets `_stop_requested` on budget
  exhaustion, which is expected termination — status remains `completed`).
- **Root cause of HipClangVersion failures clarified:** `ValueError: invalid literal for
  int() with base 10: '<unknown>'` in runs 143115–144714 was a pre-symlink race: the
  `/opt/rocm/share/hip/version` symlink did not exist at run time. Symlink was created
  during the session; run_144805 succeeds with `HipClangVersion=6.4.43484`. Code not
  modified; environment is now stable.

---

## [attempt2 driver full remediation & adversarial review fixes] 2026-09-13

- **Full adversarial review remediation across the driver ecosystem:**
  - `port_tensile.py`: Fixed Stage 7 A/B test logic error (no longer passing identical datasets for native and spoof arms); added background continuous sysfs telemetry sampler (`TelemetrySampler` reading `hwmon[0-9]*`, logging canonical `Hz/µW/mC/%` with header-in-CSV); added interactive non-blocking `'s'` skip and `'q'` quit key listeners during phase execution; replaced Stage 6 stub with real YAML logic generator, `TensileCreateLibrary` runner, anti-alias scanner (0 gfx900/vega10 leaks), and 3,066 kernel regression check; eliminated subprocess pipe buffer deadlocks by logging to disk.
  - `scheduler.py`: Corrected GEMM LDS memory estimation to `(M*K + N*K) * elem_size * NLCA / 1024.0`; made `parse_tensile_shape` robust to batch (`_B16`) and explicit K (`_K4096`) shapes; improved wave-based CU occupancy estimation.
  - `agent.py`: Upgraded `converged()` to enforce the full 4-condition convergence standard (≥2 independent runs, ≥3 configs tested, ≤1% movement, and no RED cells); replaced hardcoded FP32 candidate reconstruction fallback with family-aware defaults.
  - `registry.py`: Protected `append_phase()` with `INSERT OR IGNORE` and transaction deduplication to avoid SQLite uniqueness conflicts.
- **Verification:** Unit tests and module import validations pass 100%.

---

## [attempt2 spec drift cleanup + Tensile bulk purge] 2026-09-13

**Spec drifts fixed (SD-1 through SD-7) — all imports now correct:**
- `port_tensile.py`: removed `import fcntl`; fixed docstring (flock→sqlite3 INSERT);
  `AppendOnlyRegistry` → `SQLiteRegistry`; `CandidateGenerator` now receives registry;
  `_extract_phase_number` uses regex `phase_(\d+)` (not naive split); `import re` added.
- `agent.py`: `from scheduler_fixed import` → `from scheduler import`.
- `report.py`: `from policy_fixed import` → `from policy import`.
- `scheduler.py`: `registry` param now optional (`=None`); `append_to_phases` raises
  `RuntimeError` if called without registry instead of silent crash.
- `analytics.py`: stale `fcntl.flock` docstring updated to `sqlite3 records INSERT`.
- All 7 modules import cleanly; `port_tensile.py --help` passes.

**Bulk cleanup — 35.5 GB freed from Tensile working dir:**
- `gfx90c_runs/` (34 GB), `gfx90c_results/` (1.5 GB), `build_tmp/` (75 MB) deleted.
- attempt1 SHA256-verified as complete frozen backup before deletion. Untouched.
- `/tmp/opencode/` retained by user request; purged on next reboot.

**Source of truth confirmed:** PEAK_GFLOPS values match between Tensile and attempt2 mirrors.

---

## [attempt2 persistence: SQLite approved] 2026-09-13

- **Approved change:** ledger write path is stdlib `sqlite3`
  (`gfx90c_results/registry.db`, WAL). `records` = INSERT-only `json.dumps`
  payloads. Replaces `fcntl.flock` + JSONL **as the write path**.
- **Unchanged:** append-only evidence law (`knowledge_base.md` §10); `phases.yaml`
  remains the data-only manifest; harvest still appends YAML rows; stats pipeline
  still consumes run-dir CSV (jsonl export optional until pipeline reads SQLite);
  legacy jsonl files stay on disk, never rewritten.
- **`runs` table:** operational checkpoint (status UPDATE allowed). Not evidence.
- **Retracted:** previous `[attempt2 v1 fixes implementation]` block. That entry
  claimed policy/scheduler/report/agent/driver "fixes" had landed. They had not
  (broken imports, Tensile stub, harvest inverted, RED vs 50% PEAK, YAML
  abolished in the "fixed" driver). Unapproved drifts live in
  `incomplete_work.md` §4.9 / `adversarial_review.md` §6. Do not treat
  `/tmp/opencode/*_fixed.py` as the spec.

## [attempt2 stage approval] 2026-09-13

- **All 7 driver stages approved by user:** Stage 1 (Manifest & Phase Execution), Stage 2 (Candidate Generation), Stage 3 (Benchmark Execution), Stage 4 (Adaptive Repeat / Convergence), Stage 5 (Analytics & Append-Only Registry), Stage 6 (Synthesis / Build), Stage 7 (Acceptance A/B & Final Report).
- **ASCII flowchart added to implementation_plan.md:** Visual representation of stage flow and convergence loops, including the convergence check loop (harvest → mutate ≤2 knobs → loop back to Stage 2) and --auto mode budget-controlled loop.
- **Stage specs now authoritative:** implementation_plan.md Driver Architecture section is the single source for all stage mechanics, scope, key files, and convergence logic.

## [attempt2 consolidation] 2026-09-13

- **Stage specs consolidated into implementation_plan.md:** Previous agent's Stage 4/6/7 functional specs (adaptive repeat/convergence, synthesis/build, acceptance A/B) integrated into Driver Architecture section. Stage 5 (analytics/registry) mechanics added. D2.4 decision recorded: 3 premature auto-retire records (p12 387d2577, p5 286b940a, p6 1570d91a) stay as ordinary rows awaiting ≥2-run corroboration, never marked as verdicts.
- **Core strategy and AI constraints added to implementation_plan.md:** One-shot deterministic convergence flow, AI Must Not Decide rules, Correctness Gate, Reward Hacking prevention, Manual-LLM contingency (user-invoked, add-only, ≤5 candidates). Content consolidated from separate tuning context MD.
- **README.md streamlined:** Removed duplicated hardware/target specifications (now in knowledge_base.md only). Kept orientation, philosophy, goal statement, and file locations.
- **todo.txt removed:** Task list content already in scratch.md; eliminated redundancy.
- **benchmark-retirement-sensor-logging-fixes.json retained:** 19MB session log kept for reference (user declined deletion).
- **tensile_tuning_context.md retained:** Tuning philosophy content consolidated into implementation_plan.md; original file kept for reference (user declined deletion).

## [attempt2 init] 2026-09-13

- New ecosystem folder created at `porting_tensile/attempt2/`; prior-campaign
  conclusions absorbed into `prior_INSIGHTS_CAVEMAN_ULTRA.md` /
  `prior_RESEARCH_ARCHIVE.md` (the ONLY sanctioned prior material, appended no-data-
  deletion).
- **One-shot deterministic convergence contract** authored: no LLM consultation in
  the loop; deterministic harvest → mutate ≤2 knobs → re-run until convergence.
  The ONLY exception is the user manually invoking an LLM to ADD candidate configs
  — add-only, out-of-band, never in the loop.
- **Contract sharpened (2026-09-13, user directive):** attempt2 exists to **beat the
  gfx900 spoof baseline across the entire shipped kernel suite** AND approach the
  gfx90c theoretical limit as closely as possible. The theoretical limit is fixed by
  `gfx90c_theoretical_limits.md` (rocminfo + first-party cross-checked; see that file).
- **Driver architecture folded into `implementation_plan.md`** (single self-contained
  plan): `port_tensile.py` + `phases.yaml` manifest, `json.dumps` state,
  `fcntl.flock` locking, `argparse`, single-source PEAK.
- **Every code change PoC'd in `/tmp/opencode/` until fully functional** before it
  lands anywhere near the live driver (enforced in `implementation_plan.md`).
- **No `changes_kb.md`** — absorbed here. **No `proposed_fixes.md` / `refactor_suite.md`
  / `CHANGELOG.md` / agent-log MDs** — absorbed into `implementation_plan.md` /
  `changelog.md`. Ecosystem is the lean single-owner set registered in `claude.md`.
- Peak table corrected everywhere to single-rate **1613** for BF16 and INT8 (NO
  RDNA-style 3226 assumption); single source `gfx90c_common.PEAK_GFLOPS`.
- `PHASE_TIMEOUT_S` default planned as finite (runaway protection), not unbounded.
- Interactive single-phase kill ('s' skip / 'q' quit — one phase, not the whole run)
  planned for the driver.
- Stats/HTML pipeline retained and carried forward (`all_runs_dataset.py` →
  `make_results_md.py` → `make_report.py` → `gfx90c_report.html`).

## Prior campaign 2026-09-04 .. 2026-09-13 (frozen conclusions)

- Port mechanics proven YES: 3-injection shim, Phase-0 gates 10/10, anti-alias
  0 gfx900 leak, synthesis PASS.
- Performance = **parity, not wins** on the only same-run head-to-head
  (0 win / 11 tie / 0 loss at ±5% vs the gfx900 spoof).
- Candidate suite A–G brought to **5W / 10T / 6L** over 21 shared cells
  (B GEMV 32/64×4096 +8.1/+13.6% & +17.8/+21.3%; D 2048³ +14.1/+20.1%; E int8 1024³
  +18.3%; A sgemm 2048³ stable; F = 3 new cells; C crashed every run until the
  `[{}]` fix).
- Only 6 genuinely-new problem cells produced; ~40% of prior runtime went to
  re-benchmarking known shapes.
- Best measured: FP32 1118.7 @1024³, FP16 2492.1 @4096³, BF16 1108.5 @2048³,
  INT8 881.2 @2048³, FP64 98.6 @1024³ (98% of the 101 pipe — saturated).
- Four ruler bugs found and fixed; three-tier retirement scheme in place;
  telemetry fixed to the sysfs contract; toolchain-stderr fix landed (the single most
  impactful prior change).
- Summary only here — the full conclusion detail lives in
  `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

---

## Prior-campaign evolution (the WHY layer)

### The port mechanism flipped

- Baseline started as a **9-file in-tree patch**; worked, but forked-the-tree drift.
  Replaced by the **3-injection Python shim**
  (`tensile_gfx90c_port/sitecustomize.py` on `PYTHONPATH`): tree stays pristine, the
  whole delta is one import-time file. The shim is the ONLY port mechanism.

### Suite evolution (driver generations)

- The driver suite iterated through several generations during the prior campaign;
  the last shell generation is frozen and inherited as the attempt2 baseline for
  migration parity (new driver paradigm — the attempt2 python driver replaces it).

### Ruler bugs (all four closed prior)

- Ruler normalization was wrong in four ways: max-anchored squares, cross-dtype
  geo-mean leaking the DDR factor, a dtype-string key no-op, and missing rulers
  fabricated as 1.0. Fixed to bound-class medians, `(dt,cls)` keyed, missing →
  **reported, never inferred**. The ruler/throttle discipline only became trustworthy
  once all four were closed.

### Retirement

- Three-tier retirement introduced. Tier-1 = identical-fp skip (default on; opts out
  via a config flag; `--phases` scoped). Tier-2 = dominance retirement by
  `auto_retire.py` (attempt2 gates on ≥2 independent runs/cell after a premature
  3-record emission). Tier-3 = peak/spoof never retires anything.

### Telemetry

- Fixed to the sysfs contract; `logs/telemetry.csv` carries its header in-file
  (self-describing; canonical Hz/µW/mC/%, `hwmon[0-9]*`, `power1_input` →
  `power1_average` fallback). Continuous whole-run sampler, 2 s cadence.

### The single most impactful fix

- **Toolchain stderr fix** — the single most impactful change of the prior campaign:
  tool stderr kept out of machine-readable outputs made the append-only result stream
  trustworthy. Every downstream pipeline depends on it.

---

## 2026-09-28 — Occupancy preflight gate; ZZ dead tiles replaced

**Why.** All 8 executed native ZZ phases (`run_20260926_201835`) ended
`Generating kernel source resulted in error 4` = `overflowedResources == 4`
= Tensile's *Occupancy limit* (register-file exhaustion, `KernelWriterAssembly.py:15422`),
not a launch failure and not the benign "error 3". They died because the
legality preflight **could not detect this class of failure at all**:
`_estimate_occupancy` inferred the thread count from `ThreadTile` via a
`64 // tt` heuristic, ignored `MacroTile` entirely, and never counted VGPRs —
so it returned ≥ 1 for every config and never fired.

**What changed.**

- `scheduler.py`: added `VGPR_PER_ELEMENT`, `VGPR_BUDGET`, `_tile_dims`,
  `_dtype_char`, `occupancy_workgroups_per_cu`, `occupancy_feasible`.
  `validate_config` and `_estimate_occupancy` both delegate to the one model, so
  there is a single source of truth. The gate **fails closed** on a dtype with no
  VGPR weight: a low guess (S=1) would re-admit a failure that a high guess (Z=8)
  catches.
- `phases.yaml`: 410 → 418. Removed the 8 dead phases (`MT 128x64x8/8x4` and
  `MT 64x128x8/4x8` × 4 contraction patterns); added 16 legal ones:
  `128x32x8/8x4` and `32x128x8/2x8` as same-aspect replacements, plus `64x64x8/4x2`
  (thread count never varied for ZZ) and `128x32x16/8x4` (deeper K). Phase IDs and
  SHA-256 fingerprints regenerated; uniqueness asserted. The pre-fix deck is kept at
  `archive/phases.yaml.pre-occupancy-gate.bak` as regression evidence.
- New `check_candidates.py`: sweeps any deck through the 4 gates
  (divisibility, assembly-class, LDS, occupancy), exits 1 on any illegal config,
  so an illegal deck can be caught before a GPU run instead of mid-run.
- New `allruns.py`: all-runs pattern analysis over the whole DB, driving oto's own
  loaders (`_native_records_all_runs`, `_ab_records_from_csv`,
  `compute_native_vs_spoof_delta` winner semantics) so it cannot drift from the
  pipeline that produced the ledger.
- New `test_occupancy_gate.py`: 18 tests, incl. the calibration matrix, the
  ThreadTile-cancels identity, fail-closed dtype behaviour, the shipped deck being
  legal, and the pre-fix deck still failing exactly 8.

**Verification (CPU only, no Tensile launch, no GPU).** 18/18 tests pass;
`check_candidates.py` reports 0 illegal across all 418 shipped phases and exactly 8
illegal against the archived pre-fix deck.

**Honest limits.** The weights are **calibrated, not derived**: `R=8` for ZZ is the
smallest value reproducing every observed outcome, and the gate demands 2× headroom
because the raw accumulator-only count predicts `numWorkGroupsPerCU == 1` for the
tile that actually died (pinned in `test_raw_tensile_model_would_have_missed_the_failure`).
It reproduces all 9 observed cases and has zero false positives over 410 phases, but
it is a model, not a register allocator. ZZ is now **legal but unbenchmarked** — the
next step for the family is a TTY run, not more code.

---

## 2026-10-05 — Native arm flushed from registry; `run_status` default-head fix

### Native registry rows removed (user-authorised, backed up first)

The live registry was flushed of **native** rows only, so the deck would measure every
candidate instead of skipping all 29 as `identical_fp_already_passed`.

- **Backup (verified before the write):** `gfx90c_results/backups/registry.db.pre-native-flush.20261005_182448`
  — `PRAGMA integrity_check: ok`, 42 runs / 49,540 records / 612 phases, byte-identical
  row counts to origin. All 33 native runs are recoverable from it.
- **Deleted:** 35,729 records + 33 run rows (`run_*`). **Untouched:** all 9
  `gfx900_ref_*` floor runs (13,811 records), including `gfx900_ref_locked_52149f315d`
  with its 2,194 pooled phase records. `phases` (612 `draft_*` catalog rows) kept —
  it is a config catalogue, not measurements, and `should_run` never reads it.
- **Result:** `should_run` now returns approved for **29/29** deck phases under
  *default* policy; `reference_chain()` still resolves to the locked floor.
  `--force` is no longer required.

**Scope was chosen from evidence, not assumption.** Floor runs also carry `fp` and
`completed` records, so a native-only flush would not have worked had any deck
fingerprint been decided by a reference run. Checked first: **0 of 29** were
floor-decided, all 29 were native-only. There were also **0 `retire` records**, which
`is_phase_retired`/`is_config_retired` consult, so no second gate remained.

**Nothing was actually lost.** `ab_audit.py` reads `2_BenchmarkData` CSVs from disk,
not the registry, and still reports the identical 8 WIN / 30 TIE verdict against the
same 6 on-disk `run_*` directories. Only registry rows were removed.

### `run_status.py` default head: a closed interrupted run was outranking the floor

The default view headlined `gfx900_ref_20260928_155422_resume` — **interrupted, and
closed 8 days earlier** — while skipping the floor locked 5 days later. Every tier
count and ETA it printed came from the wrong corpus; a 25 h ETA derived from it was
wrong. `reference_chain()` (what `--auto` actually gates on) was never affected.

Cause: `ACTIVE_STATES = ("started", "interrupted")` treats *any* interrupted run as
active, and the selection took the newest-first match, so the scan walked past the
completed floor.

Fix — in flight is decided by `completed_at`, not the status label: prefer (1) a run
with no `completed_at` (live, resumable), then (2) the newest **completed** chain, then
(3) the newest finished-but-interrupted run.

The status label alone was the wrong axis: `test_chain_follows_resume_of` pins the
contract that an interrupted run which *never closed* stays at the head. Both
directions are now pinned by new tests, and the fix was verified load-bearing (reverting
it fails `test_closed_interrupted_run_does_not_outrank_newer_floor`).

**Verification.** `test_run_status`: 41/41. Full suite: **247 tests, OK (skipped=1)**.

---

## Session / consultation record

- **Prior campaign consumed 3 of 6 in-session LLM consultations.**
- **attempt2 consumes 0 by design.** The deterministic pipeline replaces the
  prior candidate-sweep loop entirely; a consultation would only be sanctioned to
  break a coverage deadlock — as a USER-invoked, add-only candidate injection (single
  canned prompt, ≤5 recipe mutations constrained to known-valid gfx90c knobs, dropped
  into `phases.yaml`). Never automatic; never in the loop.

## Upstream baseline

- The live Tensile repo remains at pristine HEAD, read-only, only the gfx90c shim
  applied. No upstream release entries are mirrored here.