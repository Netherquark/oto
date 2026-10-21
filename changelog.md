# Changelog — Tensile gfx90c port

The SINGLE changelog/evolution log for the project. One fact, one canonical home:
milestone + rationale entries land here; they are never re-created elsewhere.
Prior-campaign conclusions are sourced (never copied) from the two sanctioned
prior MDs: `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

This file records project milestones and the prior-campaign → attempt2 evolution
narrative, NOT the active implementation state (that is `implementation_plan.md`)
and NOT the experimental data (that is `results.md`).

- **2026-10-21 — virgin-knob batch and straggler analysis.** `potential_configs.md`
  gains §R42 (five straggler classes: complex memory/occupancy, small-cell
  residency, noise ties, unmeasured frontier, virgin knobs) with per-class root
  causes and measured evidence, §R43 (8 routes: 3M Karatsuba, non-atomic
  split-K, occupancy tiling, virgin knob sweep, replication, non-temporal loads,
  WGM 2/3, AssertFree extension), §R44 (legality improvements), §R45 (a ~148-row
  candidate batch) and §R46 (5 read-only research questions). The deck now carries
  the R45 batch (LdsPad=1, NLCA=-1, StaggerUMapping=1/2, MaxOccupancy=16/32,
  NonTemporalC=1/2/3, PrefetchGlobalRead=2) — 747 candidates, 754 overlay rows,
  0 illegal. `db_knobs.FORWARD_KNOB_DOMAINS` gains NLCA=-1, PrefetchGlobalRead=2,
  MaxOccupancy, NonTemporalA-D and AssertFree {1,2,4}. `ldspad_feasible` now
  gates PrefetchGlobalRead=2 against a doubled LDS footprint. Pinned by
  `tests/test_generate_candidates.py` (gate-clean over PLAN_BATCH) and
  `tests/test_occupancy_gate.py`.

- **2026-10-20 — the preflight can check the launch set, not just the deck.**
  `check_candidates.py --deck` accepted only a bare phase list, so pointing it
  at a seed overlay crashed on the overlay's top-level `run_id`/`note` keys.
  `load_deck` now accepts both shapes, and the overnight checklist sweeps
  `phases.yaml` and the overlay together. That sweep found 3 long-stale
  gate-illegal rows still sitting in the overlay (CC 128×128 accumulator over
  budget, two patterns; SS 128×128 at LocalSplitU 2 over the LDS budget). All
  three were `skipped_illegal` in `run_20261019_180048` and are no longer
  emitted by the candidate pool, so they were pruned from the seed overlay
  (timestamped backup alongside it). Pinned by
  `tests/test_generate_candidates.py::TestDeckLoader`.

  The documented preflight also constructed the driver with `create_run=True`,
  so every invocation left an empty `started` run in the registry that the next
  launch had to clean up as interrupted. `_ends_after_preflight` now makes a
  preflight-only (or `--stage 1`) invocation read-only; the ledger records only
  real runs. Pinned by
  `tests/test_interactive_keys.py::TestPreflightNeedsNoRunDir`.

- **2026-10-20 — the corpus history is now a tool, and it corrected one stale
  frontier number.** Candidate generation kept re-deriving "has this cell, at
  this geometry, on this axis value, already been measured, and how did it
  score?" with a throwaway script. `oto/harness/corpus_census.py` is that read:
  per `family/typecode`, every structural axis value with its best seed-median
  and every geometry with its row count; `--cell FAM:side`, the same for one
  cell next to the floor's best. It groups by typecode because the HPA blocks
  (`HH/HHS`, `HH/HSS`) share family `HH` but not a geometry history, and
  `resolve_family` maps the deck's `HH_HPA`/`HS_HPA` spellings (and bare
  typecodes) onto that block, so a cell read cannot silently return an empty
  `HH` cell. It ranks on the median, never the best seed. Pinned by
  `tests/test_corpus_census.py` on a synthetic database (median basis, geometry
  collapse, placeholder/zero skip, cube-cell filter, HPA alias resolution,
  CLI/JSON paths). Registered
  in `claude.md` §2.2, `docs/harness_runbook.md` (the census is question 0
  before `deck_review`) and `docs/agent_reference.md`; `oto/README.md`
  regenerated.

  The first corpus read also fixed `gfx90c_theoretical_limits.md` §5.1: its
  "measured best" column was the family best at *any* tile, not at the frontier
  tile, and the HPA entries (1399.9 / 1303.1) were mid-ladder geometries, not
  family bests. The column is now labelled accordingly with the measured HPA
  bests (1447.0 / 1441.2), and the section states that no HPA 256×128 row has
  been measured yet — the §R40 frontier deck carries it. The durable readings
  are `results.md` §15.

- **2026-10-20 — the geometry axis the deck never reached: legality, not
  preference, kept every tile small.** The 18 ties survived §R37's knob sweep
  because that sweep is about knobs; the geometry they sit on was never varied.
  Every tile above 16384 elements in the corpus (140 distinct SS geometries,
  9345 rows, 21 areas) carries ThreadTile 16×8 — 128 accumulators a thread
  against the winner's 64 — so the 30 % drop at 256×128 was a two-factor
  experiment and "big tiles are worse" was read off it. From the emitted code
  objects: SS 256×128/16×8 has 199 VGPR and 1 workgroup resident against the
  winner's 113 and 2, i.e. it lost half its residency by construction, and
  HH's large point kept its residency only because it ran at VW4/VW2 instead of
  the winner's VW8. 256×128 at VW8 was never emitted for any family, and the
  reason is the gate: Tensile's classic load structure pins `MT1 × GLVW` to the
  thread tile's accumulator count times the depth and then needs one tile side
  to be an integer multiple of the other, so a sweep of MT 64…512, ten thread
  tiles, every legal vector width and DepthU 8/16/32 through the real gate
  admits **no** tile above 16384 elements for CC, DD or ZZ and exactly one shape
  for the real families — 256×128 / 128×256 at VW2, or at VW4 under
  `AssertFree1ElementMultiple`, plus 64×512 at DU8 for the 16-bit families. The
  ceiling consequence is `gfx90c_theoretical_limits.md` §5.1 (CC's 1118.7 and
  ZZ's 98.6 bars are unreachable by geometry, and that is a bar decision, not a
  tuning failure); the deck reasoning and the four-outcome reading are
  `potential_configs.md` §R40, the finished axes are §R41. `candidate_rows`
  gains `_FRONTIER` (22 tiles), the assertion axis on 8 measured winners, a
  half-thread-tile control that separates area from register pressure, and
  `WorkGroupMapping` 2/3 on the frontier and on DD's wave-quantisation
  ties: 241 new distinct configs, ≈5 h at the
  measured 78 s per executed phase. Two deck bugs fell out: `TARGET_CELLS` was
  missing DD 768/1024/1365 and HH 4096, so three of DD's four ties and HH's
  largest could never be measured by any generated row, and
  `PATTERNS["HS_HPA"]` restated slot 2 in slot 4, halving that family's pattern
  coverage. Pinned by `tests/test_tile_frontier.py` (the exhaustive sweep, the
  named near misses, the three retired illegal tiles, and the assertion as the
  mechanism). `test_element_assertions.py`'s shipped-row guard also moves from
  `TARGET_CELLS` to each row's emitted shape list, because `_offer_row` filters
  the target sides through `_shapes_satisfying_assertions`; the invariant stays
  the same (every shape a row is measured on must satisfy its assertions) and a
  row that loses a cell to its own assertion must now say so in its note. New
  test file only, no new module, so `claude.md` §2.2 and the runbook §-list are
  unchanged; `docs/agent_reference.md` gains the test row.
- **2026-10-19 — the GPU-loss guard no longer aborts a healthy run.** The
  guard added to stop the void run (`cf18277`) counted *any* phase that wrote
  no CSV, which is the wrong signal: `run_20261018_004835` opened with three
  consecutive empty phases and `run_20261017_092909` with five, yet both went on
  to complete 400+ phases and supply the corpus's A/B. A guard that aborts on
  five of them would have killed a run whose only crime was a deck of
  unbuildable tiles. The discriminator is physical, not statistical: a phase
  that never launched the benchmark client failed at kernel generation
  ("Generating kernel source resulted in error 4") and carries a per-config
  verdict, never evidence about the device; only a phase whose client ran and
  measured nothing means the GPU is gone. The driver prints
  `loading config file .../ClientParameters.ini` immediately before launching
  the client, so that line is the test: present in every one of the 7,087
  phases that produced a measurement and in none of the 951 that did not. The
  void run's own evidence (both saved stdout tails) carried it too, including a
  phase whose log named neither `exited with code 134` nor `hipErrorNoDevice`,
  so the probe markers remain message-only. `_phase_produced_no_measurement`
  now takes the phase id and consults `_client_reached`; `_track_empty_streak`,
  `_client_aborted_at_probe` and a shared `_phase_stdout` reader follow. The
  threshold stays at 5. Pinned by `GpuLossAbortTests` (a client-reached streak
  aborts with or without probe markers; a build-failure streak does not; a lone
  result resets; a refused tile does not count; a deck shorter than the
  threshold still completes). No new module, so `claude.md` §2.2 / runbook /
  agent-reference rows are unchanged.
- **2026-10-19 — the void run is purged from every live store.** The lesson of
  `run_20261019_002432` is already frozen (the GPU-loss guard, next entry); the
  run itself was pure noise and is gone: 1111 `records` and its `runs` row
  deleted from `registry.db` (24754 records / 34 runs remain, the 1137 shared
  `phases` definitions untouched — phase rows are corpus-global, not
  run-scoped), its phantom key dropped from `analysis/kernel_db.json`, its
  486 MB run tree removed, and the top-level
  `gfx90c_results/acceptance_report.{json,html}` regenerated from the last good
  run (`run_20261018_004835`, 20 WIN / 18 TIE / 0 LOSS, "9h 3m") so the
  canonical scoreboard no longer names a run that measured nothing. Verdicts
  were whole-DB and never affected; only the report's timing/label sections had
  been polluted. A 160 KB backstop (the GetHardware abort transcript, the run's
  own report, a 412-entry manifest) is kept out of the tree at
  `gfx90c_results/purge_backup_20261019_155626/` — the run id lives on only in
  this log and in §R34, as history.
- **2026-10-19 — the virgin axes are re-decked, and one of them is closed by
  proof.** `potential_configs.md` rewrite 7 (§R34–§R39) carries the two-cause
  diagnosis of the "zero improvement" night, the honest 18-cell tie table, and
  the new deck. The deck adds `_PROBE_AXES` × `_TIE_WINNERS` in
  `oto/harness/candidate_rows.py`: four forwarded axes that no phase in the
  1137-row registry has ever carried on a winner geometry
  (`UseSgprForGRO=1` and `PrefetchLocalRead=0`, absent entirely;
  `LdsPadA/B=4`, only ever carried by the broken probe generation; and the
  `InnerUnroll=2 + UseSgprForGRO=1` combination), each on the twelve measured
  winner geometries of the tied cells — 46 rows, 0 element-multiple drops, 0
  strips, 0 refusals. `NumLoadsCoalescedA/B` was drafted as the fifth and dropped
  because the gate proved it unreachable: `gates/loads.py::_nlca_stage` needs
  NLCA to divide `numLoads`, and the winner tiles sit at `numLoads = 1` because
  GLVW saturates the 16-B cap, so NLCA>1 fails `NLCA > NumLoads` outright. Also
  recorded: `LocalSplitU` is in neither `FORWARDED_KNOBS` nor
  `NOT_FORWARDED_KNOBS`, so the two `LocalSplitU: 2` rows in `_TIE_ADAPT` are
  silent no-ops — the fourth instance of the placebo class.
- **2026-10-19 — the mutation arm can finally see the cells it exists to fix.**
  Every one of `run_20261018_004835`'s 412 candidates went to a cell that was
  already *below* its family ceiling -- 155 to SS:256, 67 to CC:192, 41 to
  ZZ:128, 39 to HH:256, 37 to DD:192 -- and the 18 cells that only TIE the gfx900
  floor got none at all. The mechanism is one line: `_mutate_cell` returned early
  when `is_below_ceiling is False`, and `is_below_ceiling` is measured against
  `REALISTIC_CEILINGS`, a measured-empirical snapshot the large cells have since
  *passed* (SS:1024 measures 1135 against a published 1118.7), so the cells that
  tie the floor are exactly the cells the arm refuses to touch. Targeting is now
  floor-relative as well: a cell earns a mutation if it is below its ceiling OR
  has not yet beaten the recalled floor, via
  `ABDeltaMixin.cells_not_beating_floor` (`agg="winner"`, so both arms are graded
  on their best per-kernel median) read once per iteration by
  `ConvergenceAgent._floor_losers`. On the live corpus that set is precisely the
  18 TIE cells -- DD/HH/HH_HPA/HS_HPA/SS/CC at 1024-4096, all within +0.1% to
  +4.6% of the floor and inside the report's +/-5% tie band. Two guards keep it
  safe: the floor is only consulted after the ceiling test, and an unreadable
  floor (no frozen reference recalled) leaves the ceiling rule exactly as it was,
  so an offline corpus cannot flood the deck. Pinned by
  `tests/test_mutation_arm.py::FloorRelativeTargetingTests` (a tie is mutated; a
  winner is settled; an unreadable floor keeps the old rule; a below-ceiling cell
  never pays for the corpus-wide scan) and
  `tests/test_ab_audit.py::TestCellsNotBeatingFloor`.
- **2026-10-19 — the overnight run can no longer burn a night on a lost GPU.**
  `run_20261019_002432` measured *nothing*: after its first phase the device
  disappeared from HIP and 413 of 414 clients aborted in
  `Tensile::Client::GetHardware` with `hipErrorNoDevice` (SIGABRT / exit 134) --
  confirmed from the systemd core dumps, whose stack is
  `__cxa_throw -> GetHardware -> main` at `client/main.cpp:273`. 9h47m of budget
  produced one phase of data, and the failure surfaced only as
  "exited with code 134" in each phase's stdout, which nothing acted on. The
  phase loop now stops itself: `PhaseMixin` counts *consecutive executed phases
  that produced no measurement* (`_phase_produced_no_measurement`) and, at
  `ABORT_AFTER_CONSECUTIVE_EMPTY = 5`, prints a diagnostic naming the probe
  abort (`_client_aborted_at_probe`, matching `exited with code 134` /
  `hipErrorNoDevice` in the phase stdout) and halts. Such a run finalizes as
  **failed** with `abort_reason` in its metadata, not as a user *interrupt*. A
  refused tile (`skipped_illegal`) is a decided outcome and never counts, so a
  legal-tile sweep is unaffected. Pinned by `GpuLossAbortTests` (streak aborts;
  a single measured phase resets the streak; a refused tile does not count; a
  deck shorter than the threshold still completes). No new module, so
  `claude.md` §2.2 / runbook / agent-reference rows are unchanged.
- **2026-10-19 — the fourteen residual literature questions folded; the second raw
  file retired.** `gfx90c_gcn5_gemm_residual_14q_caveman_full.md` (the `/caveman full`
  answer pass over the questions the first review left open) is gone. Every verdict is
  *closest-evidence-found, none gfx90c-specific*, and each now sits inline in its owner
  as a durable `[CHECK]` rationale:
  * `kernel_tuning_research.md` — **§3.4** Origami as the closest analytical GEMM
    model (its documented supported-GPU list excludes gfx900/gfx90c) and the 2025
    irregular-batched-GEMM paper as the closest mixed-tile work, plus the Tensile
    Z-order note; **§4** the AMD MI250X/CDNA2 non-temporal experiment (AMD evidence,
    but not GCN5 or GEMM) and the Tensile scoping of `StaggerU` to `TLU=0`,
    large-power-of-two K; **§8.7** the `GlobalSplitUAtomicAdd`/`StreamK`/`StreamKAtomic`
    knob names (existence ≠ performance); **§9.3** the LLVM GFX6–GFX9 VGPR-allocation
    rule (four-register units, encoded ≈ `ceil(vgprs/4)-1`) as corroboration of the
    project's granule-4 model; Sources groups extended.
  * `complex_gemm_research_brief.md` **§5** — oneMKL's illustrative first-order
    `gemm3m` componentwise error bounds, the quantitative form of the Higham caveat.
  * `knowledge_base.md` **§8.3** — AMD-specific measurement methodology (Tensile
    defaults `NumWarmups=0`/`NumBenchmarks=1`, the MI300 ~1 s / ~25 %-warmup example,
    and Primbench adaptive noise reduction), adopted as *procedure*, never as a copied
    count.
  * `potential_configs.md` **§R33** — a closing note recording that the residual pass
    turns four open `[CHECK]`s into cited "closest evidence" statements and **changes
    no route**. No new module, so `claude.md` §2.2 / runbook / agent-reference rows are
    unchanged.
- **2026-10-19 — the GCN5 GEMM literature review folded, section by section, into
  its owners; the raw file retired.** `gfx90c_gcn5_gemm_literature_caveman_full.md`
  (a `/caveman full` external pass over rasterisation/wave quantisation, complex and
  FP64 GEMM, LDS banks/padding, global-load pipeline/cache policy, split-K/Stream-K/
  persistent kernels, small-K GEMM, autotuner search-space design, measurement
  methodology, and handwritten-GCN-asm literature) is gone; each part now has an
  owner:
  * `kernel_tuning_research.md` — **§1** adds "no packed FP32 FMA
    (`V_PK_FMA_F32`)" as a hardware fact; **§3.4 (new)** is rasterisation vs wave
    quantisation (the 9-WG/7-CU tail, the transfer-only Triton/NVIDIA/cache-oblivious
    precedent, the CPU-only grid/tail ranker, mixed-tile caution); **§4** adds
    single-vs-double-buffer, `NonTemporal`, the "`StaggerU` is not a no-op until
    measured" correction, the "unforwarded knob must be verified at the generator"
    rule, and `InnerUnroll`/`DepthU` FP64 ILP; **§5** adds the Higham 3M
    numerical-stability caveat and the non-atomic split-K design; **§8.7 (new)** is
    split-K/Stream-K/persistent; **§9** adds the packed-FP32 do-not-cite row; the
    portability rule and the Sources groups are extended.
  * `complex_gemm_research_brief.md` — **§5** Higham caveat; **§8** register
    blocking under `TT0*TT1*R ≤ 128` (legality filter, not a performance proof) + the
    packed-FP32 correction; **§9** the non-atomic split-K as *new machinery*, not a
    knob; **§11 (new)** complex-double occupancy/ILP + CLBlast `6464`.
  * `tensile_tuning_context.md` **§S** — search-space size ("14–25 configs/cell is a
    small shortlist"; the ZZ 5-geometry cell is the near-duplicate failure end),
    surrogate/Bayesian recorded as *declined by `AI Rollout` policy*, and per-shape
    vs family-wide.
  * `knowledge_base.md` — **§8.3** external measurement corroboration (no universal
    iteration count or ±% band; the project's bands are its own predeclared policy);
    **§8.4** the packed-FP32 do-not-cite row.
  * `gfx90c_tuning_guide.md` **§1.2** — where the tile shape comes from (`96×96/6×6`
    is `WG×TT` arithmetic, and every ladder rung is empirical).
  * `gfx90c_theoretical_limits.md` **§3** — the square-FP32 roofline closed form
    `I = n/6`.
  * `potential_configs.md` **§R33 (new)** — the review's eight-step experiment order
    mapped onto the existing routes, with steps 4 (3M) and 7 (non-atomic split-K /
    Stream-K) marked *not reachable as candidates on this port*. It adds no route.
  * `implementation_plan.md` Completed, and this entry. Registered: no new module
    (the fold is docs-only), so `claude.md` §2.2 / runbook / agent-reference rows are
    unchanged. The review's `[CHECK]`/`[Transfer only]` labels are preserved
    verbatim in the owners.
- **2026-10-18 — the rule-calibration probe, formalised from the throwaway
  `/tmp` scripts.** `oto/harness/rule_calibration.py` applies any candidate
  rule — a `config -> Optional[bool]` predicate — to the corpus and reports the
  decision-rule confusion: false rejections on built phases (must be **0** before
  a rule lands) and empty-phase catches, by family. The `builtin_rules` registry
  ships the two shipped rules as *views* of the gate
  (`occupancy.refuses_workgroup_register_file` / `refuses_lds_reduction_buffer`,
  so a probe cannot drift from the enforcement), the generator-seam `apm2` rule,
  and the **rejected** `nt_budget` candidate (`min(256, 65536//NumThreads)` — 1
  false rejection, kept as the worked counter-example). `--rule module:attr` (or
  `path.py:attr`) probes a rule that is not in the gate yet. Live (ours):
  `workgroup_file` 0 false rejections / 40 caught, `lds_reduction` 0/13, `apm2`
  0/28, `nt_budget` 1/26. Registered in `oto/README.md`, `claude.md` §2.2/§5,
  `docs/harness_runbook.md`, `docs/agent_reference.md`; the `nt_budget` finding
  folded into `kernel_tuning_research.md` §4.
- **2026-10-18 — the unparseable-tile crash fixed; `occupancy_feasible`
  decomposed.** Two robustness gaps left by the gate closure above, both pinned
  by tests:
  * **A placeholder tile no longer crashes a gate.** `loads._load_geometry`
    documented "None when unusable" but called `int()` on a non-numeric
    `MacroTile` (a `"NONE"` fork value), so `validate_tensile_loads` — and hence
    `oto.harness.gate_calibration.audit` — raised `ValueError`. It now fails closed
    to `None`, exactly as `occupancy.tile_dims` already did, and
    `gate_calibration._tile_str`/`read_phase_config` gained the matching guard so
    an unmodellable phase is *excluded* from the census rather than counted
    gate-legal. Regression: `TestUnparseableTileFailsClosed`
    and the two placeholder tests in `tests/test_gate_calibration.py`.
  * **`occupancy_feasible` split back under the 60-line rule.**
    `tests/test_function_length.py` (AC 1b) went red at 85 lines when the two new
    rules landed; they moved into `_workgroup_file_check` /
    `_lds_reduction_check`, and the model narrative into their docstrings. No
    behaviour change: the census is unchanged (3349 phases / 3217 built / 132
    refused, 0 misses, 0 false rejections) and the focused gate suite is green.

- **2026-10-18 — the legality gate is closed, and the tile axes now have
  provable ceilings.** Three calibrated rules retire every remaining native
  empty phase: the workgroup register-file rule, the `LocalSplitU` LDS-reduction
  rule, and a generator-seam refusal of the non-generative `AggressivePerfMode=2`.
  `python3 -m oto.harness.gate_calibration --population ours` goes from 53 misses
  to **0 misses, 0 false rejections** (3349 configs, 3217 built).
  * **`oto/tensile/gates/vgpr_model.py`** — new canonical readers
    `compute_bytes`, `is_hpa`, `local_split_u`, `num_threads` and the tables
    `MAX_LDS_BYTES=65536`, `COMPUTE_BYTES_PER_ELEMENT` (HPA → f32). `local_split_u`
    moved here from `loads.py` (one home), which now aliases it.
  * **`oto/tensile/gates/occupancy.py`** — `occupancy_feasible` enforces two new
    rules: `R*MT0*MT1*LSU >= 65536` (Tensile error 4; ThreadTile cancels, so this
    is a *MacroTile* bound distinct from the per-thread one — 40 empty phases, 0
    built refused) and `LSU*MT0*MT1*computeBytes > 65536` (Tensile `MaxLDS`; 13
    empty, 0 built). Both 0-false-rejection on the native *and* reference
    populations.
  * **`oto/tensile/candidate.py`** — `_non_generative_knob_rejection` refuses
    `AggressivePerfMode ∉ {0,1}` at the generator seam, beside
    `AssertSizeMultiple: [1]` (0/28 built across all seven families;
    `Components/Priority.py` dispatches only the boolean fingerprints, so
    `Priority.find` → `None` → `MAC_F32C` `TypeError`). The writer still forwards
    `AggressivePerfMode=2` verbatim — its contract test proves the forwarding —
    so this is a draw-time refusal, not a launch-boundary one.
  * **Ceilings.** The two register rules plus the LDS budget and the classic-load
    divisibility make the "*wider MacroTile*" route per-dtype: area `< 65536/R`
    (`SS/HH` 65536, `DD` 32768, `CC` 16384, `ZZ` 8192). A brute force over every CC
    tile above 8192 and every ZZ tile above 4096 finds **none legal**; the widest
    legal complex tiles are CC `128x64x8` and ZZ `64x64x8`/`128x32x8`. This retires
    the `potential_configs.md` §8.2 "legal but never generated" headroom list,
    whose four tiles all fill the register file.
  * **Deck hygiene.** `phases.yaml`'s 4 dead `ZZ trialD3` rows (128x128, 128x64)
    are replaced with the widest legal ZZ tiles `128x32x8/4x4` and `32x128x8/4x4`
    (fingerprints recomputed); `check_candidates.py --quiet` is **284 rows, 0
    illegal**. The same dead tiles lived in two further homes and are repaired
    there too: `decks.py`'s CC/ZZ wider rows move to legal tiles (CC `128x64x8`
    at 8x4/4x4 and `64x128x8/4x8`, all VW2; ZZ `128x32x8`/`32x128x8`), the
    narrow SS/HH/ZZ rows are made explicit (VW4/VW8 silently clamped to 2; the
    ZZ VW2 duplicate is unbuildable and removed), and `candidate_rows.py`'s
    `LADDER` (`CC 128x128x8/4x4`, `ZZ 128x64x8/4x2`, `ZZ 64x128x8/2x4`,
    `SS/HH 32x32x16/2x2` at VW4/VW8) and `PLAN_BATCH` (the SS
    `128x128x16/8x8` LSU-2 tie-adapt row, which needs 131072 B of reduction
    buffer) are repaired the same way. `DECISION_TRIAL_TILES` D3 is repointed
    with its rationale, and
    `tests/test_generate_candidates.py::TestEveryDeckRowIsGenerative` pins that
    no deck, ladder or batch row is refused under any contraction pattern.
  * **Tests.** `TestWorkgroupRegisterFile` and `TestLdsReductionBuffer`
    (`tests/test_occupancy_gate.py`), the APM generator-refusal and the
    no-wider-complex-tile brute force (`tests/test_knob_sweep.py`). Focused suite
    green: 130 harness tests + 111 gate/sweep/writer tests.
  * **Docs.** Rewrite 6 of `potential_configs.md` (§R24–§R32: the closed gate, the
    tie taxonomy on `run_20261018_004835` — 20 WIN / 18 TIE / 0 LOSS — the
    four-class straggler tracker, why no steal is now justified, the ceilings, the
    per-cell ledger trace, the winning kernel-type pattern, and the deck rows);
    the two mechanics promoted into `kernel_tuning_research.md` §4; the ceiling
    table added to `gfx90c_tuning_guide.md` §1.1.

- **2026-10-18 — the /tmp calibration and triage machinery formalised into the
  harness.** The two CPU-only scripts that backed the §R23 triage (the gate-vs-
  corpus agreement census and the empty-phase reason census) are now modules, so
  the next gate edit or overnight run can re-run them instead of re-deriving
  them.
  * **`oto/harness/gate_calibration.py`** — for every phase whose launch config is
    on disk, the `(built, gate-legal)` confusion across the native and replayed-
    floor populations, plus the two named work lists: **false rejections** (the
    gate refused a phase Tensile built — the decision rule requires this to be
    0 on our corpus) and **misses** (the gate allowed a phase that produced no
    measurement). The config is reconstructed from the phase's own
    `configs/phase_*.yaml` (the compiled launch truth), with the contraction
    pattern and family label recovered from their canonical homes
    (`config_writer.TRANSPOSE_MAP`, `library_parity.phase_family`) rather than a
    second copy. Reproduces the §R23 calibration exactly: native 2812 / 79 / 46
    with 0 false rejections; the floor population keeps its documented 43. (The
    2026-10-18 rules above then turn those 46 misses into correct refusals, so
    the live census is 3349 / 3217 / 132 — `results.md` §14.2.)
  * **`oto/harness/failure_triage.py`** — the empty-phase reason census (Tensile
    `reject:` lines, non-empty stderr, stdout tail, or no logs), per run and in
    aggregate: 9820 phase dirs, 944 with no non-empty CSV. Same output as the
    retired `/tmp/opencode/triage_all_runs.py`.
  * **Docs.** Both modules are wired into the harness runbook layout,
    `docs/agent_reference.md` (Key Files + Quick Start), and the `claude.md`
    §2.2 tool table; `oto/README.md` is regenerated. The durable Tensile
    mechanics behind §R23 (NumThreads/LSU, the shadowed-WorkGroup rule, the LSU
    LDS reduction, the 16-B cap check order, the APM death) are promoted into
    `kernel_tuning_research.md` §4, with §R23 pointing at that home.
  * Tests: `tests/test_gate_calibration.py` and
    `tests/test_failure_triage.py` pin the reconstruction, the confusion matrix
    and the reason-mining mechanism on synthetic corpora.
- **2026-10-17 — every failed candidate triaged; two live gate misses closed and
  the dead axes pruned out of the deck.** Three sources, all read CPU-only: the
  ledger's rejected proposals, every run directory's empty phases, and the two
  latest live runs in full. Classes and dispositions are `potential_configs.md`
  §R23.
  * **The load gate read ComplexFloat for complexDouble.** `LOAD_DTYPE_INFO["Z"]`
    held 2 registers / 8 B, so `GLVW 2 * 8 = 16 <= 16` read as legal while Tensile
    computed `2 * 16 = 32` and refused the solution — the live
    `phase_cand_zz_128_32x64x8_tt2x4_..._vw2` phase, 0 CSV. It is now 4 / 16
    (Tensile `DataType`, ComplexDouble), and the row's derived `VectorWidth`
    default follows: with `reg=4` an absent width derives 1, which is what every
    ZZ phase that actually built used. `tests/test_measurement_integrity.py` pins
    every row to Tensile's `numBytes()`, so the load gate cannot split from
    `FAMILY_BYTES_PER_ELEMENT` again.
  * **`LocalSplitU` was not in the thread count.** Tensile computes
    `NumThreads = SubGroup0 * SubGroup1 * LocalSplitU` (SolutionStructs:1964) and
    reads LSU from `WorkGroup[2]`; the gate read the tile alone, so the whole
    LSU=2 sweep looked legal. On the 24 live LSU=2 phases the corrected gate
    refuses exactly the 20 that died (`GlobalLoadVectorWidthA 2 % pv 4 != 0`,
    `Kernel Uses 131072 > 65536 bytes of LDS`) and keeps the 4 that built (CC
    `64x64x8/4x4`, HH `128x128x16/8x8`) — and 0 false rejections anywhere else in
    the corpus. The gate reads the value Tensile will receive (an explicit
    `WorkGroup` wins over the knob — see the shadowing bullet below); the sweep's
    families narrow to the two that survive.
  * **`AggressivePerfMode=2` is a dead axis, measured not guessed.** Every family
    and every tile across two runs produced 0 `.hsaco` and 0 CSV, while its mode-1
    control in the same run built 20 (one per target arch): Tensile writes the
    source and then fails to compile it. Removed from `KNOB_SWEEPS` with the
    evidence recorded in `decks.py`; deliberately not a gate, because no tile
    property predicts it.
  * **A knob shadowed by an explicit `WorkGroup`.** `LocalSplitU` is declared
    honoured (R16), but `config_writer._fork_tile` emits an explicit `WorkGroup`
    verbatim and only folds `LocalSplitU` into it when WorkGroup is absent — so
    the deck's two CC steal rows (`WorkGroup: [16,16,1]` beside `LocalSplitU: 2`)
    benchmarked at LSU 1 while their note claimed LSU 2. The gate now reads the
    *emitted* value (WorkGroup's third element wins), and the rows drop the
    explicit WorkGroup so the LSU lands.
  * **Deck hygiene.** 24 rows left `phases.yaml` (14 `swAggressivePerfMode2`, 10
    now-refused `swLocalSplitU2`), 9 left the seed overlay (the ZZ VW2
    candidate, 2 `AggressivePerfMode=2`, 6 `LocalSplitU=2`), and 8 left the
    `PLAN_BATCH` hypotheses (2 APM2, 6 LSU2). `check_candidates.py` reports 0
    illegal and coverage parity is unchanged (38/38 cells), since every removed
    row had a surviving sibling on the same tile and shape. Triaged, measured,
    and deliberately **not** gated: the LSU LDS-reduction term (needs a
    per-family destination element size) and the NumThreads-aware VGPR budget
    (needs a config-exact VGPR table; without one it false-rejects a measured
    kernel — the overreach that killed the previous VGPR model).
- **2026-10-17 — the straggler trace is formalized into the harness: `cfg_gap`
  in `resolve_cells`, the forwarding surface declared as data in `config_writer`,
  and the legality census given the device-truth domain.** The one-off `/tmp`
  trace is retired; each conclusion now has one home.
  * `resolve_cells` emits `cfg_gap` (`identical` / `near` / `retile` /
    `no-floor`) — the mechanical half of the tie taxonomy, derived from the two
    resolved configs and reported in the table, the TSV and the JSON cache. The
    reading stays in `potential_configs.md` §R17, which this corrected:
    `DD:1024` / `DD:1365` are **re-tiles** (native ties on a *different, smaller*
    tile), not the "width/DepthU step" the first reading called them.
  * `config_writer.FORWARDED_KNOBS` / `NOT_FORWARDED_KNOBS` declare the launch
    boundary's surface once, pinned to the fork helpers by
    `tests/test_writer_forwards_sweep_knobs.py`. `candidate_rows._NOT_FORWARDED_YET`
    *is* `NOT_FORWARDED_KNOBS` (4 keys → 16), so a candidate naming
    `1LDSBuffer` / `WaveSeparateGlobalRead*` / `TransposeLDS` /
    `LdsBlockSizePerPad*` is stripped and reported instead of silently
    benchmarking at the default (the §R16 placebo).
  * `db_knobs.census_domain` (global ∪ family override) now feeds
    `deck_review`'s legality census: the mutator's narrowed `forward_domain`
    saves draws, but the census must report a structural refusal even when a
    family domain drops it. This names `GlobalSplitU>1` on CC/ZZ again and fixes
    the pre-existing red
    `test_deck_review::test_structural_refusals_are_reported_with_their_rule`.
  * `tests/test_resolve_cells.py`: a drifted corpus snapshot
    (`CC:512 NumLoadsCoalescedA == 1`) was replaced by the invariant it stood in
    for — the winning phase in the latest run carries no `NLCA` in its
    `ForkParameters`, so the resolver was right and the pin was stale (the
    anti-pattern the same file's provenance test warns against).
  * Docs merge: `docs/README.md` now indexes `gfx90c_tuning_guide.md`,
    `kernel_tuning_research.md` and `complex_gemm_research_brief.md`;
    `kernel_tuning_research.md`'s dangling `archive/corpus4…` pointer is gone
    (the file was retired on the fold); `docs/agent_reference.md` gains the
    straggler-read table, the unreachable-axis stop entry, the declared
    forwarding surface and a repo-local post-run path.
- **2026-10-15 — "THE ONE LOSER" (CC:256) triaged to a candidate-pool
  sweep-order bug, not a kernel deficit; fixed at the producer.** The last
  tracked LOSS cell (CC:256, −8.7 %, `run_20261013_214649`) was not a tuning
  failure and not the documented floor-telemetry gap — that gap is
  `spoof_clock_coverage = 0.0` on *every* cell, so it distinguishes nothing and
  explains no single verdict. Root cause: `oto/harness/candidate_pool.py` sorted
  `ProblemSizes` as **strings**, yielding the lexicographic order
  `1024, 192, 2048, 256, 512`; 256³ ran immediately after the 2048³ kernel and
  its median absorbed the throttled clock (`claude.md` §2.0.3). The same CC
  `MT64x64x8/TT4x4/VW2` tile reads **54–73 GF/s** at the poisoned 256³ position
  vs 310/348 at 1024³/2048³, and **225.3** (peak) / **210.8** (median) measured
  on its own — at or above the floor's 214.9. Fix: the order is defined once in
  `oto.tensile.shape_order` (`ordered_shapes`/`shape_order_key`) and applied at
  **all three** producer sites — the wide-row build, the existing-row merge, and
  `_narrow_row_gen`'s in-place cell merge (a third site the first pass missed) —
  plus a last-mile guard in `config_writer.write_phase_config` that re-imposes the
  canonical order no matter what a producer hands it, and the same numeric key for
  the metadata/display sorts (`ab_records`, `coverage`, `resolve_cells`,
  `report_sections`). Module "Owns" notes updated. The
  defect was generator-wide — **366 of 367** generated candidate rows carried the
  scrambled order; every lexicographic-order phase in the corpus is a
  candidate-pool phase and every numeric-order phase is a deck/auto phase.
  Pinned by `tests/test_generate_candidates.py` (the `TestPoolInvariants` ordering
  invariants, the `TestShapeOrderingHelpers` helper checks, and a crafted
  `TestNarrowRowMerge` regression for the third site) and the new
  `tests/test_shape_order.py` (helper, deck, seed overlay, synthesis sweep, and a
  writer last-mile test that feeds a reversed sweep and asserts a numeric
  `ProblemSizes`). Live seed overlay regenerated
  in numeric order (`generate_candidates --prune-candidates`, mirror
  `gfx90c_results/overlays/phases.candidates.20261015_225451.overlay.yaml`; 372
  rows, 0 non-ascending). Result: `acceptance_report.json` run
  `run_20261015_041159` reads **19 WIN / 19 TIE / 0 LOSS** — CC:256 **TIE**
  (native 210.772 vs floor 214.882, −0.74 %). No verdict band or gate logic
  changed; the floor-telemetry `DECISION REQUIRED` is superseded as a closure
  path for this cell. Docs re-pointed: `results.md` §13.4, `potential_configs.md`
  F1/§2/§9-D1/§10-D1, `gfx90c_tuning_guide.md` §5/§7/§8.
- **2026-10-14 — writer forwarded every sweep knob (run-blocking fix found while
  folding corpus3).** `oto/tensile/config_writer.py::_fork_params` is the only
  path by which candidate knobs reach Tensile (`BenchmarkCommonParameters`
  carries just KernelLanguage/EdgeType/LoopTail), and it silently dropped nine
  sweep knobs — `UseSgprForGRO`, `InnerUnroll`, `NumLoadsCoalescedB`,
  `MaxOccupancy`, `AggressivePerfMode`, `FractionalLoad`, `NonTemporalA/B`,
  `AssertFree1ElementMultiple` — while `bool(PrefetchGlobalRead=2)` collapsed
  to 1 and `WorkGroup[2]` hardcoded `LocalSplitU=1`. ~200 of the 270 emitted
  sweep/trial candidates would have benchmarked Tensile defaults, including the
  AF1EM half of the D4 paired widen (without which Tensile refuses the B-side
  load at solution construction). Fixed: int forwarding for all nine, PGR as
  int, LSU via `WorkGroup[2]`. Guarded by
  `tests/test_writer_forwards_sweep_knobs.py` (19: every `KNOB_SWEEPS` value key
  round-trips into `ForkParameters`). The 310-phase manifest was emitted after
  the fix; `check_candidates.py` + `test_tensile_params.py` pass over it.
- **2026-10-14 — decision trials decked: paired CC widen swept, baseline control,
  D1/D2/D3 trial tiles.** Per the user's "add candidates as trials" instruction,
  every open decision now owns run candidates and the 10h run decides:
  `KNOB_SWEEPS` gains the CC-only paired widen (`GLVW=2` +
  `AssertFree0/1ElementMultiple=2`; `TENSILE_KNOB_DEFAULTS` gains the two AF
  defaults at 1); `generate_knob_sweep_phases(include_baseline)` + `knob_sweep
  --baseline` emits each base tile unchanged as the same-run `_base` control
  (D4); new `DECISION_TRIAL_TILES` + `generate_decision_trial_phases` +
  `knob_sweep --trials` emits D1 (CC steal geometry at 192/256), D2 (ZZ
  LDS-boundary 64x64x16), D3 (§8.2 ZZ 128x128x8 + 128x64x8). A ZZ VW2 D2
  "differentiator" was withdrawn the same day: Tensile's complexDouble
  `numBytes()` is 16, so `GLVWA x 16 > 16` and Tensile refuses the phase at
  solution construction — `consolidate_deck.dtype_bytes` already reads that
  value from Tensile and `test_consolidate.py`'s archived-ZZ gate locks the
  refusal.
  No gate or verdict logic changed. Dry-run: 246 sweep + 14 baselines + 8
  trials = 268, 0 refusals. Tests: `tests/test_knob_sweep.py` 19→26, incl.
  `test_no_emitted_candidate_passes_only_the_lenient_gate`.
  Emit: `python3 -m oto.tensile.knob_sweep --emit --baseline --trials`.
- **2026-10-14 — the harness load gate now models Tensile's shift-ptr `GLVW` rule (the 2026-09-19 "fix (pending)").**
  `loads.validate_tensile_loads` derives `GlobalLoadVectorWidth` but used to ignore
  an explicit `GlobalLoadVectorWidthA/B`, so a `GLVW=2` config passed on a
  `VectorWidth=4` tile and was then dropped by Tensile at solution construction —
  the `must be == VectorWidth … or == 1` refuses the reference rerun recorded as
  hashes `7f866dcf` / `a0edeb30`. The gate now reads the explicit value
  (`loads._glvw_for`) and applies the guard to the pv-reduced effective width
  (`SolutionStructs.py:2010`, `:4584-4596`), **conditioned** on `bufferLoad` and
  `GuaranteeNoPartialA` (`:3292`, `:4177-4183`) so the
  `AssertFree0ElementMultiple` escape hatch is not over-refused — the synthesis
  `FORWARD_KNOB_DOMAINS` explores `GLVW ∈ {1,2,4} × AssertFree0ElementMultiple ∈
  {1,2}`, and a blanket guard would have deleted a legal slice of it. Consequence:
  an unpaired `GLVW=2` is refused for CC/SS/HH/HPA and a no-op for ZZ/DD, so the
  `GlobalLoadVectorWidth` sweep row is removed (deck 12→11 sweeps, 258→244
  candidates); the one realizable widen is the CC-only pair
  `GLVW=2 + AssertFree0ElementMultiple=2` (swept as a trial later the same day —
  see the entry above). Tests:
  `tests/test_occupancy_gate.py::TestGlobalLoadVectorWidthRule` (7).
- **2026-10-10 — kernel_db auto-refresh on run completion (mutations always read fresh).**
  `kernel_db.json` is now rebuilt automatically whenever a run reaches a
  data-producing terminal status, so candidate generation / regression_matrix /
  resolve_cells never read a stale corpus. Hook is the single run-finalisation
  choke point `SQLiteRegistry.update_run_status` (covers the run loop, SIGINT,
  gfx900-reference and `--auto` driver): on `completed`/`interrupted` it calls
  `harness.kernel_db.load_kernel_db(rebuild=True)` best-effort (~4 s, logged to
  stderr, never fails the run), `skipped`/`smoke` produce no corpus so they do
  not. The hard-crash gap (SIGKILL / power loss never reaches the SIGINT
  finaliser) is covered too: `cleanup_stale_runs` — invoked at port_tensile
  startup to terminalise orphaned `started` runs — refreshes once when it
  cleans any. Opt-outs: `OTO_NO_AUTO_KERNEL_DB_REBUILD=1` (seq runners) and
  `SQLiteRegistry(..., auto_rebuild_kernel_db=False)` (tests). Cache writes are
  now atomic (temp + `os.replace`) so a concurrent reader never sees torn JSON.
  The standing "rebuild before the next grading run" item is closed:
  `kernel_db.json` now folds 12 runsets (11 native + locked floor; 21 352 rows),
  including the 2026-10-09 overnight run. Tests:
  `tests/test_registry_kernel_db_auto.py` (status semantics, stale-run cleanup,
  opt-outs, read-only guard, failure-swallow).

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
  **Done 2026-10-14** on the harness gate (`loads.validate_tensile_loads`), with the
  `bufferLoad` / `GuaranteeNoPartialA` condition and explicit-`GLVW` reading the
  original note omitted — see the top entry.
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

## 2026-10-12 — Docs whittling: history archived out of the live docs

Executed the ARCHIVE half of `docs/audit.md` (§1.4, §1.5, §1.6, §1.12,
§2.1, §2.4, §4). The removed narrative is preserved verbatim below; the live
docs now state current fact only. Trimmed copies whose canonical home already
exists were marked as duplicates rather than reproduced twice:
`tensile_tuning_context.md` owns the Objective/strategy/philosophy paragraphs;
`mapping.md` owns the footprint; `oto.metrics.ab_delta` (module docstring,
`_collect`, `_stat`) owns the A/B aggregation bases and clock rules;
`oto.tensile.gates.occupancy.occupancy_feasible` owns the occupancy model;
`oto.tensile.config_writer` owns the launch-boundary gate and the 121-config rc=1
bucket. No code was changed.

Reference repairs made because kept sections pointed at moved anchors: the plan
banner's "self-contained" claim; the plan's `Hplan.10` and "status banner above
Option H" pointers; the plan's Next Move pointer to `incomplete_work.md` §4.9.

### implementation_plan.md

**implementation_plan.md — Objective (pre-trim)**
**Objective**

Produce native `gfx90c` Tensile libraries covering the shipped 28-family × 4-pattern
footprint (2,285 distinct shipped gfx900 kernels = 7 dtype/op families × 4 contraction
patterns; the earlier 3,066 was per-file token counting, see `mapping.md`), converging
per-cell so that each cell's ruler-adjusted median-of-seeds
winner **beats the gfx900-spoof floor** (ties at ±5% = parity, and parity alone is not
the win the campaign is here for). ±5% is the standing success bar, but it is
narrower than the measured repeat noise (CV p90 27.8%, `results.md` §12.3), so a
±5% "parity" is not evidence of indistinguishability — grade with `ab_audit.py`
(±27.8%) when the claim matters. and lands as close to the `gfx90c_theoretical_limits.md`
ceiling for its (family, bound_class) as the machine will give. The whole campaign is
driven by `port_tensile.py --auto` (deterministic harvest → mutate ≤2 knobs → re-run).

Stated goal (from `tensiles_in_system_rocm.txt`): replicate and produce a
`tensilelibrary` that performs all of the shipped functions for gfx90c, performing
**better** than gfx900 spoofing. No more, no less.


**implementation_plan.md — Core Strategy phase counts (pre-trim)**
shipped `gfx900` footprint (28 families, 4 patterns = 418 phases:
SS 105 · DD 44 · HH 40 · HH_HPA 20 · HS_HPA 20 · CC 32 · ZZ 40 · legacy auto 117
— re-derived 2026-09-27: 410 + 8 legal ZZ replacements after the occupancy gate,
see `changelog.md`)

**implementation_plan.md — AI Must Not Decide (duplicate of tensile_tuning_context.md)**
**AI Must Not Decide**

`gfx90c identity / ISA legality / AsmCaps / compiler flags / runtime support /
correctness / measurement / accepted performance` — including in the manual-LLM
contingency. The model only proposes candidate *parameter vectors*; Tensile generates,
the compiler validates, the hardware decides, the DB remembers.


**implementation_plan.md — Correctness Gate (duplicate of tensile_tuning_context.md)**
**Correctness Gate**

Always: generate → correctness → benchmark. Never: benchmark → fast → maybe correct.
Wrong kernel = failed candidate. The validator must reject known-invalid configs
(no `AssertSizeMultiple: [1]`, no `SIA>1`, no Fp16AltImpl, LDS ≤ 64 KB/CU).


**implementation_plan.md — Reward Hacking (duplicate of tensile_tuning_context.md)**
**Reward Hacking**

Independent benchmark + fresh inputs + correctness validation + repeat runs + guard
checks + dtype-specific tolerance. Evaluator stays outside model control. No
max-of-seeds; median-of-seeds is the statistic.


**implementation_plan.md — Frozen baseline (pre-trim)**
**A. Frozen baseline (conclusions sourced from `prior_INSIGHTS_CAVEMAN_ULTRA.md`)**
- Port mechanics **DONE**: pristine Tensile + minimal in-tree gfx90c support
  (3 bookkeeping entries in `Tensile/{Common,AsmCaps}.py`); Phase-0 gates 10/10
  [OK]; anti-alias 0 gfx900 leak; synthesis PASS.
- Performance = **parity, not wins** on the only same-run pair (0 / 11 / 0 at ±5%).
  Candidate suite A–G gave **5W/10T/6L** over 21 shared cells.
- 6 genuinely-new problem cells were produced. Best measurements: FP32 1118.7 @1024³,
  FP16 2492.1 @4096³, BF16 1108.5 @2048³, FP64 98.6 @1024³, INT8 881.2 @2048³.


**implementation_plan.md — Replicated footprint (pre-trim)**
**B. The replicated footprint (mapping contract, see `mapping.md`)**
28 frozen families = 7 dtype/op sets × 4 contraction patterns:
`{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` × `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`
= **2,285 distinct shipped kernels** (459+ distinct size-keys; the old 3,066 was
per-file token counting — see `mapping.md`). No gfx90c library ships anywhere today.
Reproduce the family matrix natively; per-family tile decks come from the mapped
gfx900 top-tiles + the measured prior winners (frozen conclusions); do NOT chase the
1,980-key size tables (defensive mesh, not a tuning result).


**implementation_plan.md — Technical findings 2026-09-19 (pre-trim)**
**Technical findings (2026-09-19)**

- **HS_HPA rejection root-caused.** Guard trace (`PrintSolutionRejectionReason`) +
  source audit (`potential_configs.md` §4): the rejection is stock-Tensile's non-MI
  assembly `GLVW==VW-or-1` generator guard (`SolutionStructs.py:4583-4596`),
  triggered by the pv-reduction in `setGlobalLoadVectorWidth` (`:2010-2047`) —
  isa-independent, not a gfx90c HW/ISA limit, not an assembler failure.
  Guard-legal HS_HPA parameterizations (MT64x64x16/TT4x4/VW4; MT64x64x8/TT4x4/VW2)
  are admitted 1/1 and assemble for gfx90c. HS_HPA tuning resumes on them.
- **Scheduler mirror gap — FIXED (2026-09-19):** `_validate_tensile_loads` now models
  the `GLVW==VW-or-1` predicate (scheduler.py `_validate_tensile_loads`), which the
  64x64x8 deck previously violated; 6 unit tests + 410/410 manifest sweep pass.

**implementation_plan.md — Driver Architecture spec, Stage 1–7 (pre-trim, now oto/runners docstrings)**
**The Driver Architecture**

**Stage 1 — Manifest & Phase Execution (port_tensile.py core)**
**Scope:** Read phases.yaml manifest, execute each phase via Tensile CLI, collect outputs.
**Key files:** phases.yaml (data-only manifest), TensileCreateLibrary/TensileBenchmark CLI.
**Mechanics:** For each manifest row, shell out to Tensile with dtype/shapes/ScheduleName/NumBenchmarks; collect 2_BenchmarkData/*.csv, library, telemetry; persist `json.dumps` payloads via SQLite `records` INSERT (knowledge_base.md §10).

**Stage 2 — Candidate Generation (scheduler.py + oto/ledger/agent.py)**
**Scope:** Emit candidate configs for benchmarking; occupancy-aware GSU/WGM/MT/TT sizing.
**Key files:** potential_configs.md (candidate deck), mapping.md (family decks).
**Mechanics:** From mapping.md family decks + harvested winners, mutate by ≤2 knobs (neighbour search); validate LDS fit on 64KB/CU, 7-CU occupancy ≥ floor, config-valid (no AssertSizeMultiple: [1]), fp unique.

**Stage 3 — Benchmark Execution (Tensile CLI via port_tensile.py)**
**Scope:** Run TensileBenchmark for each phase; detached+killable GPU processes.
**Key files:** TensileBenchmark client, configs/phaseN_*.yaml.
**Mechanics:** Setsid process groups; 's' kills current phase, 'q' quits; Ctrl+C kills in-flight benchmark group; EXIT trap stops telemetry idempotently; finite `--phase-timeout` default.

**Stage 4 — Adaptive Repeat / Convergence (stability gating & retirement)**
**Scope:** Always-on stability/retirement engine; median-of-seeds aggregation; adaptive repeat; retirement gating.
**Key files:** Suite v7 PHASE 26 block, PHASE 29 N8 median aggregation.
**Mechanics:**
- Per-cell aggregate: median-of-seeds (best-of-cell median is the winner metric;
  spread=(max−med)/med reported)
- Stability gate: CV ≤ 15% per cell (enforced in `agent.converged()`); the former
  `should_repeat`/`classify_stability` matrix helpers were removed 2026-09-25
- Tie band: ±5% (parity)
- Retirement: ≥2 independent runs/cell gating via `policy.check_retirement_eligibility`
  (single Tier-2 path); append action=retire records (append-only)

**Stage 5 — Analytics & Append-Only Registry**
**Scope:** APPEND-ONLY data registry; per-cell analytics; native-vs-spoof deltas; feed seeds to Stage 2, verdicts to Stage 6/7.
**Key files:** Suite v7 PHASE 29 block, oto/device/peaks.py (PEAK_GFLOPS), gfx90c_theoretical_limits.md (§5 ceilings).
**Mechanics:**
- Load raw records from 2_BenchmarkData/*.csv via oto/metrics/analytics.py/registry
- Per-cell analytics: winner via N8 median-of-seeds, spread ratio, CV, % of family-realistic ceiling (with decode DDR exemption), and cell-status classification (RED = missing contract cell, ORANGE = measured <50% ceiling, GREEN = at/above)
- Native-vs-spoof per-cell deltas: spoof arm = recalled `gfx900_ref_*` chain
  (cross-run, never re-run; `--resume` continuations fold in); withhold when no reference floor
- Append-only DB: sqlite3 `records` INSERT of `json.dumps` payloads; rows never edited/deleted
- Feed seeds to Stage 2, verdicts to Stage 6/7

**Stage 6 — Synthesis / Build (final HIP library)**
**Scope:** Build final HIP library from certified winners; anti-alias enforcement; regression gate.
**Key files:** Suite v7 PHASE 28 block, TensileCreateLibrary --merge-files.
**Mechanics:**
- Query Stage-5 certified winners from DB (median-of-seeds, ruler-adjusted)
- Group by 7 dtype/op × 4 contraction patterns → emit per-op 3_LibraryLogic/gfx90c_<Op>.yaml
- Schema-validate: len(data)>=9, fields per LibraryIO.py:232-249
- TensileCreateLibrary --architecture=gfx90c --merge-files → FINAL_LIB_DIR
- Anti-alias enforcement: scan every emitted/merged YAML + artifact for gfx900/vega10 tokens; reject build on ANY hit
- Regression gate: count check vs the pinned shipped-dat manifest (`gfx90c_results/gfx900_shipped_manifest.json`, 2,285 kernels re-derived 2026-09-25); FAIL+DB row on mismatch
- FLAG: gate deferred — build must consume only certified winners, never blind-union

**Stage 7 — Acceptance A/B & Final Report**
**Scope:** Per-cell native-vs-spoof A/B vs the recalled gfx900 floor; final per-family acceptance report.
**Key files:** `oto/tensile/library.py` (dat parse + manifest + `reference_chain`), `_compute_ab_verdicts`, oto/metrics/report.py.
**Mechanics:**
- Floor = dedicated `gfx900_ref_*` chain (ScheduleName "vega10"); `--gfx900-reference
  --resume` continues it, retrying failed phases once and reusing decided base phases
- Per-cell verdict = best-of-cell median per arm on `(family, dtype, shape)` (`cell_key`);
  delta_pct=(nat−spoof)/spoof; |Δ|≤5% TIE=parity
- Throttle variance ruled out via spread_ratio=(max−med)/med
- Cross-run pairs withheld; pairs split across base/resume are reconciled via the chain
- Acceptance REPORT: per-family coverage vs the pinned shipped-dat manifest (2,285 kernels); per-cell native-vs-spoof WIN/TIE/LOSS vs the **recalled gfx900 reference floor** (`gfx900_ref_*`, via `oto/tensile/library.py` + `_compute_ab_verdicts`); %-of-§5-ceiling per cell; RED (missing) / ORANGE (<50% ceiling) cell lists; overall PASS/FAIL


**implementation_plan.md — Design spec §1–3 (pre-trim, now oto/runners docstrings)**
**1. Design goal**
A **python driver** (`port_tensile.py`, single process) that:
1. holds a **data-only manifest** of phases — `phases.yaml`. Everything about a phase
   is DATA: id, label, dtype, shapes, `ScheduleName`, config-template, seed count;
2. runs each phase by shelling out to Tensile's existing CLI (client +
   `TensileCreateLibrary`) — the driver **never reimplements** benchmarking, config
   semantics, or result parsing;
3. collects Tensile's own outputs (`2_BenchmarkData/*.csv`, library, telemetry),
   persists **`json.dumps` payloads** via one `registry.append_record()` → SQLite
   `records` INSERT (knowledge_base.md §10);
4. analyses per-cell winner (median-of-seeds), %-of-theoretical (`gfx90c_theoretical_limits.md`),
   native-vs-spoof delta, adaptive-repeat (CV / top-2 gap);
5. **decides the next candidate set deterministically** — harvest wins, mutate
   winner-neighbours by ≤2 knobs, append config rows to `phases.yaml`;
6. terminates on convergence (no RED cells under threshold, or budget spent), with
   cooldowns between GPU phases.

`--auto` = run 2↔5 repeatedly until 6, no human in the loop. Agent harvest/accept
(round-N candidates) and convergence + retirement finalize are two small modules
plugged into the loop, not more hand-scrolled blocks.

**2. Do-not-reinvent rule (verbatim from the user voice)**
> Never solve a known-solved basic problem on our own for zero reason. If the OS, the
> Python stdlib, or Tensile already solves it, use that.

The driver uses only existing solvers:

| Concern | Implementation | Solver that already exists |
|---|---|---|
| Phase list | `phases.yaml` = data | data file |
| Round-trip one phase | `for ph in manifest: run(ph)` | Python |
| Ledger records | `json.dumps(dict)` in SQLite `records.data` | stdlib `json` + `sqlite3` |
| Concurrency safety | one writer process; WAL; INSERT-only `records` | stdlib `sqlite3` |
| Run/skip decisions | `policy.should_run(phase, fp) -> bool` + unit tests | Python |
| Analysis + report | `oto/metrics/analytics.py` / `oto/metrics/report.py` modules | stdlib `csv`, `statistics` |
| Telemetry | python `pathlib` sysfs reads | kernel sysfs |
| Peak authority | `from oto.device.peaks import PEAK_GFLOPS` | existing module |
| CLI | `argparse` + one `port_tensile.yaml` | stdlib `argparse` |
| Manifest order asserts | python `assert`/`pytest` on manifest order | pytest |
| Error trail | top-level try/except → one record | python |

**3. Module list (numbered, ordered)**
1. **Manifest first.** Write `phases.yaml` from the phase table captured in
   `potential_configs.md` / `mapping.md` (mechanical transcription). A test asserts
   manifest order matches the documented order **during migration only**.
2. **`oto/ledger/registry.py`** — one `append_record()` (sqlite3 INSERT), one `read_records()`
   iterator, queries `phase_retired`, `config_retired(phase,fp)`,
   `first_benchmarked(phase,fp)`. Never UPDATE/DELETE `records`. `phases.yaml`
   stays the manifest (a `phases` table is not the source of truth).
3. **`oto/metrics/report.py`** — renders the per-run/per-cell report → `write_report(...)`.
4. **`oto/metrics/analytics.py`** — adaptive CV/top-2 scan, winner synthesis, per-cell delta,
   ceiling util vs `gfx90c_theoretical_limits.md`.
5. **`oto/metrics/policy.py`** — `should_run(phase, fp)` in order: scope check → tier-1 retired
   (fp-less) → tier-2 retired (phase,fp) → identical-fp skip (opt-in). Unit-test the
   matrix (mirror of the prior policy cases).
6. **`scheduler.py` + `oto/ledger/agent.py`** — cooldown latch (first-GPU-phase exempt),
    `--targets`/`--family`/`--pattern`/`--shape` scope, adaptive NumBenchmarks bump,
    **occupancy-aware GSU/WGM sizing**;
   `oto/ledger/agent.py` reads `oto/metrics/report.py` → harvest / mutate (≤2 knobs) / tie → append rows →
   return subset to re-run.
7. **`port_tensile.py`** — preflight (arch, device, tensileness); per-manifest-row run
   Tensile, collect, register, cooldown; at end write report; `--auto` loops 2↔6 until
   convergence or budget. Replaces the special frozen-block handling.
8. **`--arch gfx90c`** is emitted into every Tensile invocation (fixed target — not
    a driver flag); the spoof floor baseline = the dedicated `gfx900_ref_*` chain.
9. **Entrypoint.** The python driver is the only suite entrypoint.
10. **Fold the redundant tooling** — favouring counters and fingerprint helpers
    all become python modules or tests.


**implementation_plan.md — Design spec §5 (pre-trim)**
**5. Phase 5 / 6 / `--auto` mapping**
- **Agent harvest/accept round-N candidates** (`agent.harvest()`): cells with native
  median ≥ spoof median (ruler-adjusted) → incumbent; RED/non-converged cells →
  `candidates.spawn_neighbours(winner, ≤2 knobs, occupancy-aware)` appended to
  `phases.yaml`.
- **Convergence + retirement finalize** (`agent.converged()`): no below-ceiling cells,
  ≥3 configs/cell, ≥2 runs/cell, CV ≤ 15% → write tier-2 retirement records (≥2
  independent runs/cell gating) and stop. Budget exhaustion returns converged=False and
  a FAIL readout, not a pass.
- **`--auto`**: `for _ in range(budget): run(manifest); write_report; if
  agent.converged(): break; agent.feed(manifest)`.


**implementation_plan.md — Design spec §7 (pre-trim)**
**7. Statistics/HTML tooling (oto/metrics/report.py pipeline)**
The reporting surface is `oto/metrics/analytics.py` → `oto/metrics/report.py` → `acceptance_report.json` +
self-contained `acceptance_report.html` (single-file dashboard, Carbon design
language). The driver feeds an append-only data layout (per `knowledge_base.md` §10):
- `gfx90c_runs/run_YYYYMMDD_HHMMSS/` with `configs/phase<N>_*.yaml`,
  `phase<N>_*/2_BenchmarkData/*.csv`, `logs/telemetry.csv` (header-in-file),
- `gfx90c_results/registry.db` (`records` INSERT-only) as the canonical ledger,
- `gfx90c_results/acceptance_report.json/.html` regenerated per run (and on
  `'e'`/`'q'` early exit), plus any jsonl `export` of new rows.
Any module that changes these outputs must be validated by re-running the pipeline
before merging.

**implementation_plan.md — Triaged fixes (pre-trim, 2026-09-27)**
**Triaged fixes (self-contained dispositions)**

**P0 for oto (all four in scope)**
1. **Deterministic driver (`port_tensile.py`)** per the architecture above.
2. **Finite per-phase timeout default** — `--phase-timeout` default is finite
   (generic runaway protection) and per-phase skippable/killable.
3. **Interactive single-phase kill** — 's' skip / 'q' quit exactly one phase, not
   Ctrl+C-the-whole-run.
4. **Auto-retire trust gating** — the 3 existing `retire` records came from a single
   invocation; under 77% winner instability, require **≥2 independent runs** per
   trusted shared cell (incomplete_work §4.6).
5. **Peak-table prose drift** — stale prose still claims BF16/INT8 = 3226. gfx90c is
   single-rate (1613). `oto.device.peaks.PEAK_GFLOPS` is the single source; regenerate
   dependent artifacts.

**Known-fixed states (do not regress)**
| Finding | Correct form |
|---|---|
| Ruler shape strings `"MxNxK"` vs dataset `"MxNxB"+SizeL` | `oto/device/peaks.py` rulers + `bound_class()` |
| `adj_cells()` no-op (dt key not `(dt,cls)`) | keyed `(dt,cls)`; missing = None |
| geo-mean fallback inferring missing rulers | removed; missing reported |
| Phantom `("BF16","DDR")` ruler → nonexistent phase | deleted |
| report dtype `extract_dtype_from_phase_id` | restored via token-based family parse (oto/metrics/report.py; legacy regex produced 'unknown') |
| `AssertSizeMultiple: [1]` crash (scalar int vs dict) | `[{}]`/fixed keys: config-validation gate |
| Toolchain — `hipconfig --version` on stderr | try/except + explicit ROCM_PATH |
| HardwareMonitor `stoi` on APU | `HardwareMonitor: False` in configs |
| Telemetry `.hdr` sidecar, kHz/mW units, parent-dir glob | header-in-CSV, canonical units, `hwmon[0-9]*` |
| joblib/loky vs Python 3.14 resource-tracer | **solve not avoid** (pin/fix parallelism; fallback `CpuThreads: 1` documented) |
| Self-terminating run (no new bench work) | prove the run will execute something before starting |
| Orphaned subprocess fragilities on abrupt breaks | `|| true`, `set +e`-style isolation (python makes it moot) |
| Acceptance native arm scoped to one run → all-zero report | whole-db arm (`_native_records_all_runs` / `_native_analytics_all_runs`); winners may come from an older run |
| A/B delta from max raw sample while columns showed medians | all stats per-kernel-median-first; kernel medians keyed by (run, phase, fp) |
| A/B columns hard-wired to one basis, re-breaking the delta | columns render `native_value`/`spoof_value` (the operands actually divided) under basis-aware headers |
| Occupancy gate unable to fire (no `MacroTile`, no VGPR count) | `oto.tensile.gates.occupancy.occupancy_feasible`; `validate_config` + `_estimate_occupancy` both delegate |

**Open defects (triaged 2026-09-27, resume/candidate evidence)**
1. **`_write_phase_config` early-returns without writing the file.**
   `execute_phase` ignores the return, so Tensile is launched against a config that
   was never written → `FileNotFoundError`, rc=1. This is the entire 121-phase
   rc=1 bucket of `gfx900_ref_20260926_201843_resume` (1,091 configs exist for 1,212
   targets; the 121 missing are exactly the rc=1 set). Fix both ends: treat a
   `None` return as a pre-flight rejection (record a skip, never spawn Tensile), and
   filter assembly-class-illegal configs out of reference-deck generation. Cost
   today: a wasted Tensile launch per phase and an unattributable failure bucket.
2. **ZZ/double native phases die on Occupancy limit — FIXED (preflight gate + deck revision).**
   All 8 executed `run_20260926_201835` phases ended `Generating kernel source resulted in error 4`
   = `overflowedResources == 4` = Occupancy limit (`Tensile/KernelWriterAssembly.py:15422`,
   `functionSuffix`). Distinct from the benign "error 3" note below. Root cause was a
   gate hole, not a bad tile choice: `CandidateGenerator._estimate_occupancy` inferred
   threads from `ThreadTile` with a `64 // tt` heuristic, **ignored `MacroTile`, and
   never counted VGPRs**, so it could never fire.
   Landed: `oto.tensile.gates.occupancy.occupancy_feasible` + `VGPR_PER_ELEMENT` / `VGPR_BUDGET`, wired
   into `validate_config` and `_estimate_occupancy`; fails closed on an unmodelled
   dtype (a wrong guess picks the wrong weight and would re-admit the failure).
   Verified: reproduces all 9 observed pass/fail cases, rejects exactly the 8 dead
   phases and nothing else in the pre-fix 410-phase deck, 18/18 tests
   (`test_occupancy_gate.py`). Deck 410 → 418: dead `128x64x8/8x4` + `64x128x8/4x8`
   replaced by legal `128x32x8/8x4` + `32x128x8/2x8`, plus new-axis `64x64x8/4x2` and
   `128x32x16/8x4`, all × 4 contraction patterns. Full derivation, the calibrated
   weight table, and the pre-fix deck proof live in `potential_configs.md` §5.7 —
   that section is the authoritative home, not this entry. ZZ is now **legal but
   unbenchmarked**: the next real step is a TTY run, not more code.

**CPU-only work queued (no GPU, ordered by value)**
These are the only remaining items that do **not** need a TTY. Everything else in
the route portfolio is measurement-bound (`potential_configs.md` §8.2).

**Status 2026-10-09 — all six items complete:**

1. ✅ **Measure real per-thread VGPRs** — `oto/harness/measure_vgprs.py`
   (llvm-readelf on Tensile's emitted assembly `.o` metadata, corpus-wide,
   CPU-only). Measured medians per (dtype, TT) now in
   `scheduler.MEASURED_VGPR_BY_DTYPE`; invariant test
   (`test_occupancy_gate.py::TestMeasuredRule::test_corpus_measured_totals_agree_with_gate`)
   proves gate-legal ⇔ measured < 256 VGPRs. The occupancy model (§5.7) is now
   measurement-ratified, not calibrated.
2. ✅ **Set `PrintSolutionRejectionReason`** — already present in GlobalParameters
   (`port_tensile.py:1052`).
3. ✅ **Sweep the floor deck through `check_candidates.py`** — `--floor` mode:
   **all 30 per-cell floor winners pass all 4 gates**; whole-deck residue
   1 464/6 855 (21 %) is generator-rule artifacts on non-winners (GLVW/VW,
   assembly) + 72 genuine occupancy-LDS (never-won entries, gfx900-64K-LDS
   kernels the APU rejects).
4. ✅ **Fingerprint-diff native vs floor winners per cell** —
   `oto/harness/cell_knob_diff.py`: 30 cells shared, 22 native / 8 floor
   (SS:512/768/1365/2048, HH:1024/2048/4096, CC:256); CC:256 is the single
   outside-band LOSS and the only sanctioned steal.
5. ✅ **Occupancy margin in `check_candidates.py`** — `_occupancy_margin()`
   prints `wg/cu=N acc=…vgpr …% of 64K file`.
6. ✅ **Audit the 117 legacy auto phases** — 560 `phase_auto_*` dirs total; the
   auto pool wins 13/34 cells natively (38 %), incl. HH:256 763.4 and SS:1024
   1135.1 — **not marginal**; keep them (rename S/Z tokens at hygiene time).

Full write-up: `gfx90c_tuning_guide.md` (the tuning cookbook).

**Known hazards — must never regress**
- **APU wedge at sustained 2048³-style benchmarks** (HW-Exception, exit 134). Rule:
  cooldown + detached+killable GPU processes; no untimed marathon cells.

**Benign warnings (do not spend time on)**
- "Kernel file context manager opened without any kernel files" (MergeFiles: False).
- "error 3" overflowedResources on non-MFMA half kernels (upstream-declared fine).

**implementation_plan.md — Option H plan, banner through Hplan.6 (pre-trim)**
**Option H — Mutator overhaul (formalised, single-shot)**

> **Status: ALL FOUR PHASES LANDED (2026-10-05/06); nothing above is superseded.**
> `Hplan.3` (ledger + outcome), `Hplan.4` (legality), `Hplan.5` (coverage +
> fitness) and `Hplan.6` (synthesis, graded form) are implemented and green:
> - Phase 1: append-only `proposals` table + ledger/novelty API (`oto/ledger/registry.py`),
>   `oto/ledger/mutator.py` (classifier, novelty, negative cache, per-run overlay), the
>   `agent.mutate_and_feed` rewrite that routes candidates to the overlay instead
>   of `phases.yaml`, and `analytics.count_benchmark_rows` as the single owner of
>   CSV shape.
> - Phase 2: `legality.py` manifest-derived legal domains — reject set never
>   proposed (measured legal rate 100%, `proposal.md` §H.7 criterion 3).
> - Phase 3: `coverage.py` per-cell states (none / unstable / retired) +
>   lower-confidence-bound parent selection.
> - Phase 4: `synthesis.py` coverage-guided sampling with graded multi-shape
>   sweeps; the lattice remains only as a *reported* fallback.
>
> Two behaviours deliberately did **not** change, and both would have been easy to
> get wrong:
> - **The identical-fp skip is bypassed for the mutation arm only while the ledger
>   is available *and* the outcome signal is wired** — `ConvergenceAgent.skip_mutation_arm()`
>   flips back on the moment `mutator.ledger_available()` fails, so a missing ledger
>   re-enables the skip instead of silently re-emitting ungraded candidates.
> - **`phases.yaml` stays curated.** Candidates go to the per-run overlay
>   (`mutator.write_overlay`); the runner merges only that run's overlay. Discarding
>   a bad batch deletes a file, not history.
>
> `scheduler.mutate_winner` was still the lattice sampler at Phase 1 — Phase 1
> replaces the loop's memory, not its generator. Phase 2 replaced the sampler with
> manifest-derived legal domains (`legality.sample_legal`), and Phase 4 made
> `synthesis.synthesize_cell` the configured sampler; the pre-Phase-1 path remains
> reachable for tests only.
>
> **Read `proposal.md` §H.1.2a and `changelog.md` (2026-10-05) before implementing Phase 1.**
> The evidence that originally ordered this plan — "mutants produced zero GFlops" — is
> **retracted**; it was an artefact of reading the `GFlops`-headed column, which is a problem
> index rather than a throughput. Through the canonical loader the mutants are productive but
> **ungraded**. The consequence for this plan is concrete: the negative cache's motivation in
> `Hplan.3` step 9 no longer has historical support, so it ships as a *forward* guarantee with
> a test that asserts it does **not** fire on today's corpus, and D5 (single-shape, ungradable)
> is promoted to co-equal status with D6. H.3.8's definition is unchanged and still correct —
> it is the historical justification that was wrong, not the predicate.
>
> Option H is **APPROVED (2026-10-09)** — the user answered §H.10's decision
> question in full ("proposal.md is approved, so Option H is approved"): all four
> phases are implemented and CPU-tested, and the go-ahead for a GPU-backed run of
> the mutation arm is granted. The evidence and design rationale live in
> `proposal.md` (addendum dated 2026-10-05); **this section is the executable
> plan only** and holds no restatement of its numbers — per §3 (one fact, one
> canonical home) and per the never-transcribe-a-count rule (§5), every figure is
> cited to `proposal.md` §H.x and read live by the tools.
> With approval recorded, the supersession table above is **in force** as of
> 2026-10-09 (Hplan.6-sampled mutants go to the per-run overlay, `phases.yaml`
> stays curated). The two unchanged behaviours (ledger-gated skip bypass,
> mutation-free path = plain Stage-3, never `--auto`) are committed alongside.

**Supersession notice (read before Stage 2)**

This section, once approved, **supersedes three parts of this file**:

| location | current text | superseded by |
|---|---|---|
| Stage 2 mechanics; §5 bullet 1; flowchart Stage 2 | "mutate by ≤2 knobs (neighbour search)", "mutate ≤2 knobs" | `Hplan.6` sampling |
| Stage 2 mechanics; §5 bullet 1 | "Emit candidate configs to `phases.yaml`" | `Hplan.3` step 7 — per-run overlay |
| Stage 5 | "Feed seeds to Stage 2" | `Hplan.5` coverage/fitness view |

Until approval, the code and this text remain consistent: `scheduler.mutate_winner`
still does ≤2-knob neighbour search and `agent.mutate_and_feed` still appends to
`phases.yaml`. Do not "fix" the code to match a future plan.

**Hplan.1 Defects this addresses**

D1–D6 as enumerated and evidenced in `proposal.md` §H.2. In plan terms:

1. **`--mutation-budget` does not bound anything.** `scheduler.py:379` consumes it in one
   boolean test (`if mutation_budget >= 2`). It gates two-knob pairs; single-knob mutants
   are emitted unconditionally. The flag's help text ("Maximum knobs to mutate per
   candidate") is therefore misleading.
2. **No novelty memory.** Iteration *n+1* re-proposes fingerprints already emitted.
3. **Output is largely non-functional.** `proposal.md` §H.1.2a measures this at the CSV
   layer with a same-run positive control. The loop has no field distinguishing "ran and
   produced nothing" from "worked".
4. **Mutants are written into the curated deck**, then skipped on the next pass.
5. **Mutants are single-shape**, so they are born ungradable against a multi-shape floor.
6. **Outcome is never recorded**, so the loop cannot learn from failure.

**Hplan.2 Deliverables**

| artefact | kind | owner doc |
|---|---|---|
| `oto/ledger/mutator.py` | new module: legality, novelty, coverage, outcome, synthesis | this section |
| `oto/ledger/registry.py` | `proposals` table + `json_extract` expression index | this section |
| `oto/ledger/agent.py` | `mutate_and_feed` delegates to `oto/ledger/mutator.py`; stops calling `append_to_phases` | this section |
| `scheduler.py` | lattice retained as a fallback sampler; `mutate_winner` unchanged | this section |
| `ab_audit.py` | report `origin` split, per-cell `n`/spread, outcome histogram | this section |
| `tests/test_mutator.py`, `tests/test_proposals_ledger.py` | new tests | this section |

**No new parser.** Every read of a phase's knobs, a CSV, or a fingerprint goes through the
canonical loaders already mandated by `claude.md` §2.1 (`tensile_library`, `analytics`,
`registry`, `allruns.py`, `check_candidates.py`). If a needed value cannot be obtained from
them, that is a defect in one of them — fix it there, do not add a parallel reader.

**Hplan.3 Phase 1 — ledger + outcome (do this first; the rest is worthless without it)**

Rationale: this is the phase that makes the mutator a search rather than a dedup cache,
and it is independently useful even if nothing later is approved.

1. **PoC in `/tmp/opencode/`** (`claude.md` §5): a `proposals` table created against a
   **copy** of the live registry, with INSERT and the single monotonic
   `outcome` write-back, exercised end to end before any repo edit.
2. **Schema** exactly as `proposal.md` §H.3.1, including `origin`, `outcome`, and
   `build_class`. Migration is additive (`CREATE TABLE IF NOT EXISTS`); it must not touch
   the `records` schema or rewrite any existing row.
3. **Append-only discipline** (`knowledge_base.md` §10): rows are never `DELETE`d and never
   rewritten; `outcome` only advances `pending → terminal`. A single monotonic status
   column is not a mutation of history. Enforce with a trigger or an `UPDATE ... WHERE
   outcome='pending'` guard plus a test that a second write-back is a no-op.
4. **Novelty query**: novel iff `fp` absent from **both** `proposals` and the registry's
   decided set. Add the `json_extract(data,'$.fp')` expression index; do **not** change
   `has_fp_passed` semantics, only its cost.
5. **Outcome classifier** (pure function, CPU-only): reads a phase's
   `2_BenchmarkData/*.csv` via the canonical loader `analytics.load_benchmark_csv` and returns
   one of `functional` / `non_functional` / `legal_rejected` / `legal_slow`. `functional` iff
   that loader yields at least one record; `WinnerFreq` recorded alongside.
   **Implementation constraint, non-negotiable:** the predicate must be expressed *in terms of
   the loader*, never by re-reading the CSV and indexing the `GFlops` column. That column is a
   problem index, not a throughput — deriving the predicate from it is precisely the error
   retracted above. If the classifier needs something the loader does not expose (row count, to
   separate "rows present but all zero" from "no rows"), that accessor is added to
   `oto/metrics/analytics.py` as the single owner of CSV shape, not reimplemented here.
6. **Durability regression** (`proposal.md` §H.3.2): on a DB **copy**, delete every native
   row and assert the ledger and novelty still hold. Never run this against the live DB.
7. **Overlay** (step 7 above): candidates route to a per-run overlay the runner reads
   and the curator never sees. `phases.yaml` stays curated and reviewable; discarding a bad
   batch deletes an overlay, never edits history.
8. **Wire the mutation arm** to emit through `oto/ledger/mutator.py`, bypassing
   `opt_in_identical_skip` **only because** novelty is now structural. If this table is
   ever disabled or lost, the skip must be re-enabled for the mutation arm — the bypass is
   a correctness dependency on the ledger, not an optimisation.
9. **Negative cache**: if *k* consecutive candidates from one neighbourhood return
   `non_functional`, down-weight that neighbourhood instead of re-sampling it. *k* is a
   named parameter with a default, not a literal buried in code.
   **The historical justification for this is retracted** (see the status note above): replayed
   against today's corpus the cache correctly never fires, because every measured mutant row is
   non-zero. It therefore ships as a *forward* guarantee, and the test asserts both halves —
   it fires on *k* consecutive `non_functional` outcomes, and it does **not** fire when replayed
   over the archived runs. A test that only checks the first half would pass while the cache
   silently misfires on real data.
10. **Guardrail compliance to assert in tests**: no corpus count is transcribed into code,
    a comment, or a test fixture; counts are read live from the registry/manifest exactly
    as `auto_prompt._read_counts()` already does. No test asserts a literal corpus size.
11. **Revert the skip-bypass claim if phase 1 lands partially.** If the ledger ships
    without outcome, the mutation arm must keep the skip on, because a novelty-only ledger
    over a non-functional search makes the run *look* productive while measuring nothing.

**Phase 1 integration pass — LANDED (2026-10-06)**

The ledger shipped in Phase 1 with every one of the pieces above present and **none of them
reached a run**. Each gap is listed with the failure it produced, because each was silent:

| gap | what it actually did |
|---|---|
| overlay never merged | candidates were emitted and recorded, then never scheduled — the arm reported progress while measuring nothing |
| `run_id` dropped on emission | every proposal had `run_id=NULL`; "which run produced this" was unanswerable |
| proposal + phase = two commits | a crash between them left a permanently-`pending` candidate: its `n` never grows, so the cell is re-routed to `replicate` forever, indistinguishable from genuine instability |
| `resolve_phase_dir` never called | outcomes were never written back, so the ledger only ever grew `pending` rows |
| `WinnerFreq` via a private reader | a second set of Tensile CSV format assumptions; fails as zeros, which reads as "no kernel won" |
| `WinnerFreq` not persisted | H.3.8's evidence requirement was met only in memory, for the life of one process |
| negative cache process-local | every restart reported a saturated neighbourhood as untouched — the cache silently switched off at exactly the moment it was needed |
| `skip_mutation_arm()` never consulted | the bypass was computed on every emission and then ignored by the loop that skips |

**Schema decision — `proposal_observations`.** H.3.8 wants WinnerFreq "recorded alongside the
verdict". It cannot live on the `proposals` row: a proposal's *evidence* is re-observable while
its *verdict* is decided once, so columns there would invite overwriting the basis of a
decision already made. It is a separate append-only table, one row per observation, written
**before** the verdict — a crash between them leaves recoverable evidence and a `pending` row,
whereas the reverse order leaves a decided verdict with nothing behind it.

**Read-only registries.** Found while verifying: `SQLiteRegistry.__init__` ran the additive
schema migration unconditionally, so every `ab_audit` run rewrote the live floor registry's
bytes. No row was touched, but a report had changed its own subject. `SQLiteRegistry(base,
read_only=True)` now skips `_init_db` and every mutating method raises `PermissionError`; the
audit opens the registry read-only. Asserted byte-for-byte.

**Bypass scoping.** The identical-fp bypass applies to **overlay phases only**, and only while
`skip_mutation_arm()` is False. Applying it deck-wide would re-benchmark settled curated phases
every run, which is the opposite of what the skip is for.

**`tests/test_phase1_integration.py`** (53 cases) covers all of it by driving the driver's
`run_phases` loop, not the helpers in isolation — testing `_resolve_proposal_outcome` and
`should_run` directly passes even when the loop calls neither, which is exactly the state
Phase 1 was in. Verified by disabling the merge and the write-back: 2 of the loop tests fail.

**Hplan.4 Phase 2 — legality prior**

1. **Do not model the reject set; read it.** The reject predicates are already documented
   with source citations in `proposal.md` §H.2 and verified against the Tensile checkout
   at `e8a8999e`. Re-verify each one at implementation time and record the commit in the
   module docstring — the audit that seeded them is dated, and one of its five root causes
   was already found to mis-state its own condition.
2. **Sample legal-by-construction**: draw each knob only from values observed for that
   `(family, dtype)` in `gfx90c_results/gfx900_shipped_manifest.json` via the canonical
   parser. This is what removes the ±1-neighbour reject classes structurally rather than
   filtering them afterwards.
3. **Hard walls**: encode the verified half-precision `VectorWidth` floors (including the
   GSU case) and the MT/schedule rejections as named predicates with unit tests. Do not
   encode the audit's prose summary; encode the code.
4. **Keep `validate_config` as an assertion, not the search.** A candidate it rejects is
   recorded `legal_rejected` with its `build_class` so phase 1's negative cache can learn
   from the rejection.
5. **Legality is not the agent's judgement** (`AI Must Not Decide`): every predicate
   traces to Tensile source or the shipped manifest, never to model reasoning.
6. **Report the legal rate** from a CPU-only sampler sweep, with the baseline read live —
   never a transcribed percentage.

**Phase 2 outcome — LANDED (`legality.py`, 2026-10-05)**

| step | status | evidence |
|---|---|---|
| 1 read, don't model | done | every predicate re-read at `e8a8999e`; commit recorded in the module docstring and in `legality.TENSILE_COMMIT` |
| 2 legal-by-construction | done | `shipped_support` / `sample_legal`; knob values come only from the pinned manifest |
| 3 hard walls | done | `half_vector_width_floor`, `mt_has_shipped_schedule`; GSU case recorded in `DEFERRED_RULES` instead of guessed (below) |
| 4 assertion retained | done | `validate_config` still runs per candidate; rejections recorded `legal_rejected` |
| 5 not the agent's judgement | done | each predicate cites Tensile source or the manifest |
| 6 live legal rate | done | below |

**Measured (rerun `/tmp/opencode/legality_compare.py`; both arms same 29 curated
parents, same process, same `validate_config`):**

| family | lattice | prior |
|---|---|---|
| CC | 13% | 100% |
| DD | 58% | 88% |
| HH | 25% | 72% |
| HH_HPA | 24% | 91% |
| HS_HPA | 23% | 79% |
| SS | 55% | 70% |
| ZZ | 32% | 100% |
| **all** | **417 / 1169 = 35.7%** | **198 / 232 = 85.3%** |

The lattice column reproduces the D3 table exactly when re-run live (1169 proposed,
417 legal), which is the cross-check that the prior is measured against the same
reject model D3 was. The prior's residual is dominated by occupancy/register-file
and by load divisibility on the *full problem instance* — gates that need the phase's
sizes, not just the kernel, and which step 4 assigns to the assertion. Driving those
into the sampler would mean re-implementing the assertion, so they were left there.

**Three findings from implementing it, all corrections rather than confirmations:**

1. The audit's `A_half_VW1_assembly` label implied one wall; it is two conditions in
   different places, and the GSU one is *not* enforceable from our config surface. A
   first cut modelled it as `VectorAtomicWidth < 2 -> reject` and a live sweep showed
   it firing on shipped HS_HPA `GlobalSplitU` 2/3/5/7 vectors — 90 false rejections,
   i.e. exactly the "modelling the reject set" failure step 1 forbids. The real value
   is *derived* (`SolutionStructs.py:3574/3588`) and the guard is gated on the internal
   `_GlobalAccumulation`, so it now sits in `DEFERRED_RULES` with its reason. The
   reachable GSU rules were already `assembly_class_valid`'s (rules 2 and 3).
2. The half `VectorWidth` wall was **dead on arrival**. `EnableMatrixInstruction`
   (`:1918-1930`) tests `len(ThreadTile) == 2`, but our configs carry ThreadTile as the
   string `"8x4"`, whose length is 3 — so every candidate read as *undetermined*, the
   `is False` branch never ran, and the sweep reported a suspicious 100% accepted with
   zero drops. Fixed by normalising ThreadTile; the wall then caught the 32 shipped
   half `VW1` vectors. A legal-rate sweep that reports a perfect score is a bug report.
3. GlobalLoadVectorWidth is a function of MacroTile, so `schedule` and `loads` are not
   independent groups — moving them separately manufactured the indivisible-tile
   rejections the prior exists to avoid (85 of 86 HH_HPA rejects). They are now one
   atomic `tile` group. Separately, the base must be a *complete* shipped vector:
   deck/winner configs carry only MacroTile + ThreadTile, and building on those directly
   emitted configs with no WorkGroup, no VectorWidth and no load widths, which was the
   largest remaining reject cause. The parent now selects a neighbourhood (donors
   sharing its MacroTile); a shipped vector supplies the config.

**Hplan.5 Phase 3 — coverage + fitness**

1. Coverage view over `proposals` + `records` per `(family, shape)`: distinct `fp` count,
   sample count `n`, median, spread. Cells are targeted, not enumerated.
2. Three states kept distinct: no candidate → explore; `n = 1` or spread beyond the
   acceptance band → replicate; all-`non_functional` → retired, not "empty" (§H.1.2a).
3. Parent selection by **lower confidence bound**, never raw winner. Today's `harvest()`
   picks the winner, which is how a noise-level win becomes the parent of the next batch.
4. `ab_audit.py` surfaces `n`, spread, and the `novel`/`replicate` split so a replicate's
   value is visible after the fact.

**Phase 3 outcome — LANDED (`coverage.py`, 2026-10-05)**

| step | status | evidence |
|---|---|---|
| 1 coverage view | done | `coverage.coverage_cells`; `registry.all_proposals` + `coverage.samples_by_fingerprint` |
| 2 three states | done | `decide_state`; exactly three states, no fourth ("empty") |
| 3 LCB parent | done | `coverage.select_parent`, `agent.harvest(parent_by="lcb")` |
| 4 ab_audit surfaces it | done | `_proposal_coverage` + `_print_proposal_coverage` |

**Design points worth stating, because each is a place the obvious version is wrong:**

- **The band is read, never written** — and was initially *not read at all*. The
  first `coverage.measured_band_pct()` called `ab_audit.reproducible_band` with one
  argument for a two-argument function, and its `except Exception` turned the
  resulting `TypeError` into `None`. Every cell therefore ran with "no band",
  silently, while this document claimed the band was measured. Fixed by extracting
  `ab_audit.arm_record_sets` + `ab_audit.measured_band`, which are the *same two
  calls `audit()` makes*, so coverage and the audit cannot disagree and
  `_proposal_coverage` can pass the band it already has instead of recursing into
  `audit()`. Measured on the current corpus: **18.29%** (`max(cross-arm 18.29,
  repeat-tail, shipped-floor 5%)`) — the shipped 5% is a floor, not the answer.
  The test that let this through was `assertTrue(value is None or value > 0)`,
  which passes for a function that always raises; it is now four assertions that
  all fail when the read is stubbed back to `None`.
- **Explicit target cells.** `coverage_cells(..., target_cells=...)` emits a cell
  that was targeted but never proposed for, so it can be reported as `STATE_EXPLORE`.
  Deriving cells only from proposals made "we never looked" and "not on the list"
  the same absence — the conflation §H.1.2a is about.
- **`min_n` is the *worst* measured config in the cell, not the mean.** A cell whose
  best config has eight seeds and whose other config has one is not confidently
  measured; averaging that away is how a noise-level win becomes a verdict.
- **Retirement is checked after evidence exists.** `decide_state` returns `explore` for a
  cell with no decided rows before it can ever return `retired`, so "never tried" is
  never recorded as "tried and failed". `legal_rejected` also does not retire a cell: a
  rejected proposal never ran.
- **`n = 1` degrades the bound to the median rather than faking a variance.** Thin
  evidence is reported as thin (`min_n`, state `replicate`); a one-sample LCB that
  claimed precision would be a second definition of confidence.
- **The seeds travel with `CellAnalytics`** (`analytics.compute_cell_analytics` now
  attaches them). An LCB cannot be recovered from a median, a CV and a count, so parent
  selection would otherwise need a second read of every CSV. Hand-built cells without
  seeds degrade to the median rather than raising.
- **`parent_by="median"` remains reachable**, and `selected_by_lcb` /
  `parent_by` / `parent_score` are recorded on every winner, so a run's parent
  policy is visible afterwards and the two rules can be compared on the same data.

**Hplan.6 Phase 4 — synthesis, graded form**

1. Coverage-guided constrained sampling replaces the lattice walk; the lattice remains
   available as a deterministic fallback so behaviour degrades rather than failing.
2. Extend beyond the six knobs the lattice touches, using manifest-legal values only.
3. Emit multi-shape family-sweep candidates so a mutant can be graded (`Hplan.1` item 5).
4. Re-derive `ThreadTile`/`WorkGroup` from `MacroTile` the way `_reconcile_knobs` does, so
   the product constraint holds by construction.

**Status: landed.** `synthesis.py`; 79 tests in `tests/test_synthesis_phase4.py`. Notable
decisions, and what forced them:

- **Item 2 was already satisfied by Phase 2, and the knob budget is exhausted.**
  `legality.KNOB_GROUPS` covers all eight structural knobs the shipped solutions encode
  (`MacroTile`, `ThreadTile`, `WorkGroup`, `VectorWidth`, `GlobalLoadVectorWidthA/B`,
  `GlobalSplitU`, `DepthU`), plus `af0em` riding with the split group. The one remaining
  parsed knob, `grvw`, is deliberately excluded: it is not a Tensile parameter, and
  `BenchmarkStructs` calls `printExit()` on unrecognised names. So "extend beyond the
  lattice's six" is met by covering every legal knob, not by inventing parameters.
- **`TEMPLATE_KEYS` moved to `legality.py`** and is re-exported by `oto/ledger/mutator.py`. It was
  defined in `mutator`, but it names the keys `legality` *assembles*, so the definition
  belongs with the module that produces them; two copies would be two answers to one
  question.
- **The band is resolved lazily via `ConvergenceAgent.band()`, never in `__init__`.**
  `ab_audit.arm_record_sets` constructs an agent to manage phases, and
  `coverage.measured_band_pct` calls `arm_record_sets` — so computing the band at
  construction time is a cycle that ends by exhausting the stack. It was caught by
  `TestMeasuredBand` hanging rather than failing; `BandResolutionTests` now pins it. Note
  that a band of 5.0 on an empty corpus is `TIE_BAND_PCT`, the documented shipped floor,
  not an invented measurement.
- **The ledger's single `shape` column keeps the cell identity; the sweep goes in phase
  data.** Coverage joins on `(family, shape)`, so recording the sweep's first shape would
  re-file the candidate into a different cell and make the coverage joins wrong.
- **`retired` cells are skipped, not sampled.** Every candidate in such a cell was
  non-functional; re-drawing the neighbourhood is what the negative cache exists to stop.
- **Two latent bugs were found by the new tests and fixed.** `reconcile_tile` returned
  early on a *missing* `ThreadTile`/`WorkGroup` — the exact case it exists to solve — and
  an unsolved dimension rendered as the literal string `"None"`, which Tensile would
  reject at parameter-parse time rather than at our own check.
- **The lattice fallback is reported, never silent.** A run that quietly falls back looks
  identical to one that did not. `last_emission_stats` now carries `retired_cells`,
  `lattice_fallback_cells`, `ungraded_cells`, `graded_cells`, and `band_pct`.
- **`DepthU` travels with the tile, and crossing pairs are pruned against the shipped
  manifest.** The shipped manifest stores DepthU as the K component of the MacroTile —
  Tensile's `128x32x16` *is* "MacroTile 128x32 at DepthU 16" — so moving DepthU on its own
  manufactured exactly the occupancy rejections the scheduler's model then misread (16 of
  24 HS_HPA rejects in the first legality measurement). `DepthU` now rides with the `tile`
  group (`KNOB_GROUPS` is `tile`/`split`), and every emitted candidate's *cross-group* knob
  pairs are required to co-occur in some shipped solution (`legality.cooccurrence_check`,
  cached per family). This is co-occurrence read off the manifest, deliberately not a model
  of the reject set — the occupancy/assembly predicates still reject configs Tensile
  genuinely ships (verified: 31/135 shipped HS_HPA, 19/169 SS), which is why they are *not*
  hard walls. Measured consequence: the Phase-4 legal rate went 88% (176/200, HS_HPA 0%,
  HH_HPA declining entirely) to **100% (232/232) with all seven families proposing and zero
  false drops** (`/tmp/opencode/legality_p4.py`). The gate alone cannot reject a config
  Tensile ships — a shipped solution co-occurs with itself.


**implementation_plan.md — Hplan.8 (pre-trim)**
**Hplan.8 Sequencing and PoC gates**

Every phase is CPU-testable; **none requires GPU time**, and none may be validated by
running Tensile (`claude.md` §5: full benchmarks are TTY-and-user-only). Each module is
PoC'd in `/tmp/opencode/` before it lands, and no change lands without a PoC plus a scoped
parity check. Phase order is Phase 1 → 2 → 3 → 4; see `proposal.md` §H.9 for why that order.


**implementation_plan.md — Hplan.10 (pre-trim)**
**Hplan.10 Known gap found while formalising — `--auto` cannot currently disable mutation**

Recorded here because it blocks the "no mutations" run requested alongside this plan, and
because it is defect 1 of `Hplan.1` seen from the CLI.

Today **no flag turns mutation off**:

- `--mutation-budget 0` does **not** disable it. `scheduler.mutate_winner` emits
  single-knob mutants unconditionally; the budget only gates the two-knob block
  (`scheduler.py:379`). Zero yields a one-knob sweep, not no sweep.
- `--budget 1` does **not** avoid it either. The loop body runs the manifest, then
  evaluates convergence, then calls `mutate_and_feed` (`oto/ledger/agent.py:400`) — and only
  *then* increments the iteration counter and re-tests the budget. So a single-iteration
  `--auto` still harvests and mutates. (Since Phase 1 the candidates go to the per-run
  overlay, not `phases.yaml` — the original "polluting the curated deck" wording predates
  that and no longer applies.)
- `--stage` gates only the non-`--auto` branch (`port_tensile.py:3195`); it does not
  constrain `run_auto`.

The safe mutation-free path today is to **omit `--auto` entirely** and run the plain
Stage-3 path (`--stage 3`, or any of the `--family`/`--shape`/`--pattern` selectors),
which executes the deck once, updates run status, and regenerates the acceptance report
without entering the harvest/mutate loop. That is what `command.txt` now contains.

**Resolution (2026-10-05, user): withdrawn, not deferred.** Omitting `--auto` and using
the plain Stage-3 path is the intended and only mutation-free route, so there is no need
to give `--mutation-budget 0` the meaning "emit nothing" and no need to re-gate
`mutate_and_feed` on remaining budget. Those two behavioural changes are **not** planned
and no longer await approval. The defect that remains real is the one below, and Option H
addresses it at the source instead of via a flag.

The substantive gap Option H actually inherits: `--auto`'s only control over mutation
*width* is a flag whose help text overpromises. `mutate_winner`'s ≤2-knob lattice is
replaced by the manifest-legal sampler under `Hplan.6`, which bounds the search by
construction instead of by a flag that does not bound anything. `--mutation-budget` is
retained for compatibility and is expected to keep its current effective meaning (a
lower bound of 1 on knobs touched) until `Hplan.6` lands.

### results.md

**results.md — §9 resume failure triage (pre-trim)**
**9. Resume failure triage (404, `gfx900_ref_20260926_201843_resume`)**

| Bucket | n | rc | Root cause |
|---|---|---|---|
| Tensile `0 valid solutions` | 220 | 255 | Config rejected at solution enumeration. 154 `VectorWidth must be >= 2 for half`, 30 `ThreadTile not multiple of VectorWidth`, 25 GLVWA (VW4/1), 5 `totalElements 768 % (NumThreads*grvw) != 0`, 3 GLVWB, 1 GLVWA(VW8), 2 no reject line |
| Config never written | 121 | 1 | `_write_phase_config` returns early on the assembly-class gate **without writing the file**; `execute_phase` still launches Tensile on the missing path → `FileNotFoundError`. 1,091 configs exist for 1,212 targets; the 121 missing are exactly the rc=1 set |
| User skip (`'s'` keypress) | 63 | −1 | `skipped_by_user`. Not a config/hardware failure |

Family split: HS_HPA 204, SS 106, HH+HH_HPA 94. The doubled `phase_phase_*` config
naming is the consistent convention, not the fault.


**results.md — §10 acceptance-report mechanism (pre-trim)**
**10. Acceptance report — native arm re-armed to the whole database**

**Symptom.** `run_20260926_201835`'s report was uniformly zero: every family
`measured_cells=0 / best_median=0 / coverage=0`, `per_cell_verdicts=[]`, and all 38
deck cells RED/MISSING at 0.0.

**Cause — arm-scope asymmetry.** The spoof arm resolved across the whole reference
chain (1,881 cells), but the native arm read only the reported run. That run
executed only 8 non-duplicate phases (`402` were `identical_fp_already_passed`) and
**all 8 failed** with `Generating kernel source resulted in error 4`, which Tensile
maps to `overflowedResources == 4` = **Occupancy limit** in the ZZ/double assembly
kernel writer. Zero native cells in-run → empty analytics → deterministic zeros.
The real native winners were sitting in older runs the report never consulted.
**Fix.** The native arm is now the **whole database** — every `run_*` dir's CSVs plus
every registry `benchmark_result` row — so winners (including prior older winner runs)
are picked across all history, exactly as the spoof arm already was. Each verdict cites
the run/phase that produced the winning kernel.

**Delta semantics (corrected twice).**

*First bug.* The original code computed `delta_pct` from the cell's **max raw sample**
while the table displayed **medians** — the columns never reconciled (CC 192 displayed
31.4 vs 31.5, a −0.3% ratio, but reported −6.1% from underlying 40.49 vs 43.12). Every
statistic is now **per-kernel-median-first**, so a single lucky seed cannot decide a
verdict. Kernel medians are also keyed by source run, so the same
`(phase_id, fingerprint)` benchmarked by two runs is no longer pooled into one median.

*Second bug.* The two rendered columns were still hard-wired to "Best native median" /
"Spoof median" regardless of the basis in use, so switching basis re-broke the
guarantee. The columns now render `native_value` / `spoof_value` — the two operands
actually divided — under basis-aware headers, so the displayed ratio always equals the
printed delta (verified: 0 mismatches in JSON and in all 38 HTML rows, residual ≤0.44pp
= 1-decimal display rounding).

**Comparison bases** (`--native-agg`), per (family, dtype, shape) cell:

| agg | native vs | Question it answers |
|---|---|---|
| `winner` **(default)** | **best** vs **best** | does the deck's best kernel beat the floor's best kernel? (drop-in replacement) |
| `winner_clock` | best vs best, telemetry-adjusted | same, after normalizing each kernel to a common core clock |
| `median_clock` | median vs median, telemetry-adjusted | central tendency, clock-normalized |
| `floor_best` | native **median** vs floor **best** | can a *typical* native kernel beat the best kernel the floor ships? |
| `strict` | native **worst** vs floor **best** | does *every* native kernel beat the floor's best? (per-cell dominance) |
| `best_median` | native best vs floor **median** | lenient: deck winner vs a typical floor kernel |
| `median` | both medians | symmetric central tendency |
| `throttle` / `best` | sclk-stamped feed / max raw sample | legacy; `best` is seed-noisy, reference only |

**`winner` (best vs best) is the default** — it is the drop-in-replacement question:
you replace one shipped kernel with one native kernel, so the two candidates must be
each arm's best. Every statistic is per-kernel-median-first, so "best" means the best
*kernel* measured over its seeds, not the single luckiest seed.

**Telemetry adjustment (`*_clock` bases).** GFLOPS is linear in core clock, so each
kernel's median is scaled by `sclk_ref / sclk_measured`, where `sclk_measured` is that
phase's own sustained clock and `sclk_ref` is **one shared corpus-wide constant**
(1800 MHz, the highest clock the GPU held in this corpus) so neither arm is rescaled in
its own favour. Two guards make it refuse to lie:

1. **Idle floor is not a measurement.** A phase whose only busy samples sit at the
   400 MHz idle clock is dropped rather than scaled — scaling it by 1800/400 = 4.5x
   let a 20.7 GFLOPS kernel "win" a cell at 93.0 GFLOPS. Genuinely throttled phases
   (0.9-1.2 GHz, 158 of 770 in the resume run) are real and are kept.
2. **Coverage gate (`CLOCK_MIN_COVERAGE = 0.5`), applied symmetrically.** A clock-adjusted
   *best* is only comparable if drawn from the same population as the unadjusted best.
   At 9% coverage (the CC cells) the eligible subset is unrepresentative and its max sat
   52-67% below the unadjusted max, which flipped CC to native wins. Below the gate both
   arms fall back together to the unadjusted twin of the requested basis
   (`winner_clock` -> `winner`, `median_clock` -> `median`) and the cell is reported
   `clock_adjusted: false`.

**The native arm has no usable clock data, so `*_clock` is currently inert.**
`run_20260919_213727` (4,896 of the 6,790 native records) has **no telemetry file at
all**; `run_20260920_235815` has 458 rows, all at the 400 MHz idle clock, 0% busy and
from a sampler that predates per-phase tagging. Native clock coverage is therefore
**0.000 on all 38 cells**, and every `*_clock` run correctly degrades to its unadjusted
twin with a printed warning. The spoof arm is well covered (mean 0.74, 1,719 phases
tagged), so the machinery is real and verified — it simply cannot be applied
symmetrically until native is re-benchmarked by a sampler that tags `phase_id`
(`oto/metrics/telemetry.py` already writes it; `run_20260920_235815`'s file just predates that
change). Adjusting only the spoof arm would deflate the floor and flatter the deck, so
the gate forbids it.

The adjustment was verified against an independent recompute from the raw
`2_BenchmarkData` CSVs plus the telemetry timelines: **38/38 cells match** on both the
raw best per-kernel median and its clock-normalized twin.

**Assumption to keep in mind:** throughput ∝ core clock holds for ALU-bound kernels but
over-corrects memory-bound ones (GFM/GEMM small shapes are limited by mclk/DRAM), so a
clock-adjusted delta on a DDR-bound cell is an extrapolation. Both the adjusted and
unadjusted statistics are emitted per cell for exactly this reason.


**results.md — §11 why the preflight missed it (pre-trim)**
**Why the preflight missed it.** `oto.tensile.gates.occupancy._estimate_occupancy` derived the thread
count from `ThreadTile` via a `64 // tt` heuristic, ignored `MacroTile`, and never
counted VGPRs — so it returned ≥ 1 for every config and could never fire. The gap was
in the gate, not the tile choice.


### incomplete_work.md

**incomplete_work.md — orphan §4.2 mechanism line + §4.3–§4.13 (pre-trim)**
**Mechanism:** `port_tensile.py` + `phases.yaml` manifest + 7 modules (`registry.py`, `report.py`, `analytics.py`, `policy.py`, `scheduler.py`, `agent.py`, `gfx90c_common.py`) fully implemented and unit-tested. `--auto` convergence loop operational with deterministic mutate-≤2-knobs candidate generation.

**4.3 28-family native coverage (RESOLVED — 2026-09-13)**

**Mechanism (T3):** 28-family native coverage generated in `phases.yaml` spanning all 7 families `{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` across 4   contraction patterns `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}` with anchor problem shapes (304 candidate configs: 232 family + 72 auto; re-derived to **418 phases** 2026-09-27: 410 + 8 gate-legal ZZ replacements, see `changelog.md`.)

**4.4 Adaptive-repeat finalize (RESOLVED — 2026-09-13)**

**Mechanism:** Production adaptive repeat logic implemented in `port_tensile.py` (NumBenchmarks doubling for high-spread cells). Telemetry sampler in `telemetry.py` (`SysfsTelemetrySampler`) guarantees gated sample windows. *(2026-09-25: the `policy.py` `should_repeat`/`classify_stability` helpers were removed — stability is now a CV≤15% gate inside `agent.converged()`.)*

**4.5 auto-retire trust gate (RESOLVED — 2026-09-13)**

**Mechanism:** Implemented in `policy.py` (`check_retirement_eligibility`), gated on ≥2 independent runs/cell before emitting retirement decisions. *(2026-09-25: `classify_retirement_tier` and `apply_d2_4_protection` were removed — retirement is now the single Tier-2 path via `check_retirement_eligibility` + `should_run`/`is_config_retired`.)*

**4.6 Peak-table prose drift (RESOLVED — 2026-09-13)**

**Mechanism (T8):** Sourced strictly from `gfx90c_common.PEAK_GFLOPS` (single import point — BF16: 1613, INT8: 1613). All driver headers, analytics, and reports cite single-rate 1613.

**4.7 Synthesis evidence gate (RESOLVED — 2026-09-13)**

**Mechanism:** Implemented in `port_tensile.py` `synthesize_library()`. Emits per-family logic YAMLs, executes `TensileCreateLibrary --merge-files`, runs anti-alias scan rejecting any `gfx900`/`vega10` leaks, and verifies regression against 28 families.

**4.8 Occupancy = performance objective (RESOLVED — 2026-09-13)**

**Mechanism (T9):** `scheduler.py` candidate generator and `agent.py` convergence engine treat right-sized `GSU`/`WGM`/`MT`/`TT` as first-class objective knobs, scored against realistic ceilings in `gfx90c_theoretical_limits.md` §5.

**4.9 Driver Implementation & Remediation (RESOLVED — 2026-09-13)**

**Remediation audit completed and verified across all modules:**
- `port_tensile.py`: Added telemetry sampling (via `telemetry.py` `SysfsTelemetrySampler`, canonical units Hz/µW/mC/% logging to `logs/telemetry.csv`), interactive non-blocking `'s'` skip and `'q'` quit key listeners, fixed subprocess buffer deadlocks by piping to disk logs, fixed `run_ab_test` to query native (`ScheduleName="isa"`) and spoof (`ScheduleName="vega10"`) records separately, and implemented Stage 6 library synthesis with YAML logic generation, anti-alias scanning (`0` gfx900/vega10 leaks), and 2,285-kernel regression check (the earlier 3,066 was per-file token counting).
- `scheduler.py`: Fixed LDS usage calculation to `(M*K + N*K) * elem_size * NLCA / 1024.0`; fixed `parse_tensile_shape` to robustly handle batched (`_B16`) and explicit K (`_K4096`) shapes; improved wave-based occupancy estimation.
- `agent.py`: Upgraded `converged()` to evaluate full multi-condition convergence (≥2 independent runs, ≥3 distinct configs, ≤1% movement, and no RED cells); replaced hardcoded static fallback in `_reconstruct_config` with family-aware defaults.
- `registry.py`: Protected `append_phase` with `INSERT OR IGNORE` and duplicate checking.
- `policy.py` & `analytics.py`: Clean stdlib implementations using realistic ceilings from `gfx90c_theoretical_limits.md` §5.

**4.10 Ctrl+C signal handler + stale-run cleanup (RESOLVED — 2026-09-13)**

**Mechanism:**
- `_signal_handler` now calls `sys.exit(130)` after `os.killpg` + registry `update_run_status(interrupted)`.
- `registry.cleanup_stale_runs()` added (bulk UPDATE `started→interrupted`) and called in `TensileDriver.__init__` before creating new run dir.
- `run_phases()` marks run `interrupted` when `_stop_requested` is set.
- 3 orphaned runs (run_140507, run_141220, run_143006) corrected in live DB.

**4.11 Tensile Top-Level YAML Generator & Pipeline Robustness (RESOLVED — 2026-09-13)**

**Mechanism:**
- `port_tensile.py`: Fixed `_write_phase_config` to derive correct `TransposeA`/`TransposeB` per contraction pattern in label (`Ailk_Bljk` $\to$ NN/FF, `Ailk_Bjlk` $\to$ NT/FT, `Alik_Bljk` $\to$ TN/TF, `Alik_Bjlk` $\to$ TT/TT); mapped `MacroTile0`/`MacroTile1` properly from string representation; dynamically calculated `WorkGroup` tile ratios (`MacroTile0/ThreadTile0`, `MacroTile1/ThreadTile1`, 1); set proper HPA / `HS_HPA` mixed precision flags.
- `scheduler.py`: Added `MacroTile` / `ThreadTile` divisibility check (`MacroTile0 % ThreadTile0 == 0`) and valid thread count constraints ($64 \le \text{threads} \le 1024$, multiple of 64) in `validate_config`.
- `analytics.py`: Added whitespace-stripped parsing and per-kernel GFlops extraction in `load_benchmark_csv` to handle space-padded CSV headers emitted by Tensile.
- Verified across unit tests and live benchmark data (`run_20260913_144805`, `run_20260913_150517`, `run_20260913_151227`).

**4.12 Complete 7-Stage Driver Transition (RESOLVED — 2026-09-13)**

**Mechanism:**
- Abolished reliance on arbitrary numeric phase IDs (0–31); phase identity uses
  semantic filters.
- Replaced CLI execution with semantic filters: `--family` (SS, HH, HH_HPA, HS_HPA, DD, ZZ, CC), `--pattern` (Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk), `--shape`, `--stage`, and `--auto`.
- `phases.yaml` fully populated with 28 native families across 4 contraction patterns (228 clean targets; the live manifest = **418 phases** as of 2026-09-27, see `results.md` §1).
- Added `--dry-run` to inspect matched candidate targets before hardware execution.

**4.13 Parallel Clang Build, Cooldown Key Handling & Early Quit Reports (RESOLVED — 2026-09-13)**

**Mechanism:**
- Multi-threaded assembly compilation enabled by setting `CpuThreads: min(os.cpu_count(), 16)` in generated YAMLs and `make -j`.
- Fixed Tensile `ForkParameters` emission from `MacroTile0`/`MacroTile1` to valid schema `MacroTile: [[M0, M1, DepthU]]` fixing CC/DD configuration parsing.
- Integrated non-blocking `select.select()` listener in `_apply_cooldown()` so `'s'` skips cooldown sleep and `'q'` quits immediately.
- Ensured `acceptance_report.json` and `acceptance_report.html` are generated and persisted to `gfx90c_results/` even on early termination via `'q'` or interruption.

## 2026-10-12 — Docs whittling: `oto/harness/README.md` history archived

`oto/harness/README.md` was moved to `docs/harness_runbook.md` (it is now inside the
documented ecosystem directory). Its `/tmp`-prototyping history and stale counts were
archived here.

# Archived from oto/harness/README.md (moved 2026-10-12)

## Historical note from L1–8 /tmp context (trimmed for changelog)

This content was preserved from the former harness runbook that referenced `/tmp` prototyping history. The original runbook has been relocated to `docs/harness_runbook.md`; CPU-only/benchmarking contract and the ecosystem map are referenced there and in `claude.md`.

- CPU-only, never benchmarks: see `claude.md` §5 (Non-negotiable project guardrails) for the operational constraint.
- Ecosystem: see `docs/README.md` for the MD-docs-vs-docstrings boundary; layout and ownership now point at `oto/README.md` and `docs/harness_runbook.md`.

## 2026-10-12 — docs restoration after the whittling (and one gate-harness fix)

The whittling pass (`7ef4213`) cut load-bearing detail from the human- and
agent-facing docs and replaced it with pointers. This restores it, merging the
pre-whittling content with the refactored structure:

- `README.md` — rebuilt as a self-contained high-level repo overview: a repo
  layout tree, full root-entry-point + per-package module tables, the complete
  validation-tool command set, the `.env` table, and the docs index (no longer a
  pointer chain). All internal links verified to resolve.
- `gfx90c_tuning_guide.md`, `kernel_tuning_research.md`,
  `gfx90c_theoretical_limits.md`, `complex_gemm_research_brief.md`,
  `potential_configs.md`, `knowledge_base.md` — restored to their pre-whittling
  substance as self-contained starter documents for the tuning agent (knob
  mechanics + forwarding surface, measured regime tables, the three byte tables,
  complex-MAC accounting, the occupancy model, mutation strategies, and open
  research directions). Only provably-wrong facts were corrected (e.g. the
  `ZZ` byte width is `16`, not `8`; the occupancy rule is `accVGPR = TT0·TT1·weight`).
- Cross-references re-pointed to the current section numbering — the
  pre-2026-10-10 `potential_configs.md` `§13.x` / `§14.x` / `§8.6` citations no
  longer resolved.
- `oto/harness/occupancy_audit.py` now imports `VGPR_PER_CU` from
  `oto/tensile/gates/vgpr_model.py` instead of re-declaring it (Refactor-1
  acceptance criterion 6: no device-constant scatter).

## 2026-10-12 — off-grid probe tier removed (candidate pool is now strictly in-grid)

The generator's only contract-violating arm was the **off-grid probe tier**
(`PROBE_CELLS`: SS 32/64/128, DD 128, forced DepthU 4, `graded: false`): those
rows addressed (shape, dtype) cells the shipped gfx900 library does not carry,
so they could never ship under the no-contraction / no-extension contract
(`tests/test_library_parity.py`). Per the "no candidates that don't adhere to
the contract at all" decision, the tier is deleted outright:

- `oto/harness/candidate_rows.py` — `PROBE_CELLS` removed.
- `oto/harness/candidate_pool.py` — the probe loop, the second (`probe_pool`)
  sink, the `graded` flag and the `sink`/`graded` params on `_offer` are gone;
  every emitted row is in-grid.
- `oto/harness/candidate_overlay.py` — `_write_overlay` no longer takes probe
  rows or `--with-probes`; the timestamped mirror carries only `phases`.
- `oto/harness/generate_candidates.py` — `--with-probes` and the `PROBE_CELLS`
  re-export removed.
- Tests rewritten (`tests/test_generate_candidates.py`): the probe-specific
  cases are replaced by a hard invariant — every generated row addresses a
  shipped-grid cell — and `_write_overlay` counts only newly-scheduled rows.
- Docs: the `PROBE_CELLS` entry (tuning guide), the A6 off-grid row and the
  §10.3 "mirror only" note (`potential_configs.md`) now state the exclusion.

The legacy in-grid `probe_N1..N5` seed rows and `probe_*` run-dir globs are
unaffected (they are inside the grid).

## 2026-10-12 — seed-pool cap removed (`--max-fp` default = no cap); duplicate CLI deleted

`--max-fp` defaulted to a hand-picked `300` with no derivation, and the same
`main()` (argparse + body) existed in **two** modules — `generate_candidates.py`
*and* `candidate_overlay.py`. The cap silently dropped 58 of the 358 rows the
builders emit (`_round_robin_prune`). It never limited the `--auto` convergence
loop (that is `--budget` iterations / `--mutation-budget` knobs); it only capped
the pre-built seed pool.

- `--max-fp` now defaults to **no cap**: `_round_robin_prune` takes
  `Optional[int]` and returns the pool unchanged when the cap is `None`. The
  whole emitted in-grid pool is seeded; `--max-fp N` remains as an explicit
  opt-in throttle.
- The duplicate CLI is gone: `candidate_overlay.py` keeps only the overlay I/O
  (`_write_overlay` / `_prune_candidates_from_seed` / `_round_robin_prune` /
  `_summarise`); `generate_candidates.py` is the single CLI.
- Also dropped the now-impossible `"probe"` priority key in `_round_robin_prune`
  and the pre-split leftover imports in `candidate_overlay.py`.
- Tests: added a no-cap no-op case. Focused suite
  (`test_generate_candidates.py` + `test_library_parity.py`): 38 passed.
- The dry run now reports the full pool (would append the rows the old cap had
  been dropping); `--max-fp 300` reproduces the old behaviour exactly.
