# The oto tuning campaign — the post-prompt-spam operator playbook

**Class B document.** Read this when you are the operator agent (or supervising it)
running the *tuning campaign* — the multi-day convergence effort that turns a
working best-effort library into a converged one — after
[`operator_runbook.md`](operator_runbook.md)'s best-effort gate has passed. If the
library does not build yet, finish that first. If you are working **on** oto,
this is the wrong file.

This document is the permanent answer to a pattern this project lived through:
the first convergence ran by *spamming a long prompt into an agent session and
re-spamming it until something moved*. Every idea in it that worked is now
code, and every way it failed is now a documented constraint. You are not the
first agent to touch this corpus; ~320 commits separate you from the first.
Use them.

## 0. The two hard rules (inherited, never overridden)

1. **GPU work happens only in the user's TTY.** A desktop/Wayland session can
   be reset by a runaway GEMM. In a display session you do CPU-only work and
   stop. Whitelisted legality probes in a display session are at most 512³
   CUBE BUILDS (Tensile's `NumElementsToValidate` reference check) — never a
   benchmark, never "medium" sizes, and never on someone else's share of the
   GPU.
2. **CPU gates are not measurement.** A proposal that passes
   `oto check candidates` / `validate_config` is legal to try, not competitive.
   Only a TTY benchmark counts as evidence.

(So is the third rule in `claude.md` §5: the GPU belongs to the user; you wait.)

## 1. Why this file exists — the history you are standing on

All of this is why the campaign is shaped the way it is. Read it once; it
never gets re-derived.

| date | what happened | the lesson baked into this file |
|---|---|---|
| Jul 2026 | FOSS grant: a generalisable pipeline for backporting ROCm to obsolete AMD GPUs (gfx90c 5650U, gfx902 2200G). | The deliverable was never "prove GEMM fast"; it is *a repeatable method*. |
| Aug 2026 | GPU characterisation; the "AMD vis-à-vis GPUs" diaries; first-party CDNA/Vega ISA sources studied. | Hardware facts come from primary sources, never model memory. |
| Aug–Sep 2026 | **attempt1**: `run_gfx90c_suite.sh` and helpers, ~9.2K LoC driving Tensile through shell. Found real wins (native SS@1024 native 698 GFLOPS vs spoof floor 608) but systemic breakage: ruler math wrong four ways, telemetry gaps, retirement conflating three tiers. | Shell-era state lived in ~9K LoC of shell and vibes; state must live in a database with append-only law. |
| Sep 2026 | **attempt2**: parallel draft branch; case-by-case triage → telemetry fix ported, draft data imported append-only, draft's acceptance gate rejected. | A faster answer that skips provenance is not an answer. |
| 2026-09-17 | oto born; the tuning loop becomes Python: corpus, ledger, mutator, acceptance report. | Convergence = a measured discipline, not a hope. |
| Oct 2026 | Refactor 1: flat root → `oto/` package; function ≤ 60 LoC, file ≤ 600; suite 9× faster. | Effort goes into the candidate, never into the bookkeeping. |
| Oct 2026 | The fold was found: native "wins" were arm-size artefacts; `agg=winner` is an order statistic; HPA rows were misattributed (typecode vs stamp); sweep-order depressed cells flipped verdicts. | Read verdicts like-for-like only; kernel typecode is ground truth. |
| 2026-11-13 | The library (`best_effort_library_rocmlibs`) passed yolo26 acceptance on the nightly ROCm 7.x stack (person 0.87). | A library that builds but cannot dispatch is not a library. |
| Nov 13–14 2026 | Refactor 2: device-profile machinery (`profiles/<codename>.json`), nightly ROCm 7.x port, CLI front door, `NumElementsToValidate=128`, explicit `profile=` threading, the AF4/4 CC rows adopted. | The device is data, not a code path — and validation is the correctness gate, not a courtesy. |

Three implications you must internalise once and forever:

1. **The prompt-spam era is over.** Every legitimately-repeatable move is code
   or a gate. Anything that still needs an LLM is (a) research synthesis off
   primary sources, (b) candidate ideation **within harness-visible domains**,
   or (c) post-mortem triage judgment. Nothing else.
2. **The corpus is the memory.** Between sessions you remember nothing that the
   artifacts do not contain; rebuild, re-read, re-derive. Never trust context.
3. **Effort is finite and the GPU is precious.** Every candidate proposal must
   be cheap to gate (CPU), expensive to ignore (gate-refused before TTY), and
   costly to repeat (novelty enforced by the ledger).

## 2. The neurosymbolic division of labour

| layer | who does it | examples |
|---|---|---|
| **symbolic** (rules, exact, reproducible) | the gates + Tensile + the ledger | `validate_config` → `ldspad_feasible` → `assembly_class_valid`; the Tensile reference validator (`NumElementsToValidate=128`); the ledger's identical-fingerprint skip (with the `bypass_identity` exception for mutants); the retirement gate |
| **neural** (judgment, synthesis, narrative) | you, within the harness | synthesising candidate families from corpus history; reading the acceptance report; triaging failure classes; writing docs; proposing the next hypothesis class |
| **measure** | the user's TTY only | every kernel's actual performance |

The invariant: **neural proposals may only enter through the symbolic
pipeline.** You never hand a config to the deck that has not passed the gates
and the deck check. You never "know" a kernel is fast; you read the report.

## 3. The persistent operating model

State lives on disk, not in context. Between sessions the campaign carries:

| artefact | what it holds | owner |
|---|---|---|
| `gfx90c_results/analysis/kernel_db.json` | every measured kernel: family, shape, winner, verdict inputs | oto (rebuilt, never edited) |
| `acceptance_report.json` + `acceptance_report.html` | last batch's verdicts: per-cell delta, tie bands, clock coverage, red/orange lists | oto (`AcceptanceReporter`) |
| `cells_resolved.json` / `cells_resolved.full.txt` | per-cell winner map + cfg_gap | `resolve_cells` |
| `regression_matrix.json` | deck vs floor vs all-time | `regression_matrix` |
| `docs/harness_runbook.md` outputs | axis history, empty-phase causes, legal-space coverage | harness tools |
| the seed overlay (`phases.seed.overlay.yaml`) | candidate rows not yet in the deck | `generate_candidates` |
| `incomplete_work.md`, `<codename>_potential_configs.md`, `results.md` | your working notes: decisions, verdicts, retired losers with reason | **you** (docs only) |

Every session: read these before touching anything. A context that disagrees
with the artifacts is wrong, because the artifacts are the record.

### 3.1 The session-start protocol (≈5 minutes)

```bash
python3 -m oto doctor                       # 0 failures, or stop
python3 -m oto verify all                   # evergreen across commits
python3 -m oto.harness.kernel_db --rebuild  # never trust a stale cache
python3 -m oto.harness.resolve_cells --taxonomy
```

Then, in order:
1. The **last acceptance report** — JSON for numbers, HTML for shape
   (`per_cell_verdicts[].{delta_pct, tie, verdict, clock_adjusted,
   native_clock_coverage}`, `red_list`, `orange_list`). Never `winner`-basis
   headlines (order statistics flatter the arm that drew more kernels).
2. The **deck state** — `python3 -m oto check candidates` (0 illegal, or stop);
   `python3 -m oto.tools.deck_review score|legality|flood --cap N`.
3. The **open list** — `incomplete_work.md` plus the device's untried items in
   `potential_configs.md`.

Decide: consultation trigger (§7) → reconnect; otherwise, autonomous work (§4–§6).

### 3.2 The session-end protocol (≈10 minutes)

1. Append to `incomplete_work.md` anything you opened; strike out anything you
   closed (open items only — completed work moves to `changelog.md`/`results.md`).
2. Write the decision context: which cells moved, which retired, which opened.
3. If a silicon fact got resolved, update the device docs (starter/profile → no;
   `<codename>_theoretical_limits.md` or `<codename>_tuning_context.md` → yes, with evidence).
4. Never commit anything you did not measure.

## 4. The campaign phases — where effort goes, in order

### Phase 1 — Study the corpus (CPU only; the slow read that decides everything)

For each family × cell where native is `TIE` or `FLOOR WIN`, before writing a
single candidate:

```bash
python3 -m oto.harness.corpus_census --cell FAM:side
```
— every geometry ever measured there, with counts and floor-best. An empty
cell is data, not a blank.
```bash
python3 -m oto.harness.cell_knob_diff
```
— native winner vs floor winner, knob-by-knob. Where they agree, the gap is
structural; where they diverge, the gap is a knob.

Attribution check (non-negotiable): kernel header typecode is ground truth
(`dtype_to_family`). Never trust a phase stamp; HPA rows stamped `HH` vs `HHH`
are the classic contamination.

Clock coverage: if `native_clock_coverage` or `spoof_clock_coverage` is weak,
the cell's absolute numbers are machine readings, not kernel readings; judge
within-run only (M4). Re-measure in TTY before drawing conclusions.

Like-for-like only: absolute numbers across runs with different SCLK or weak
`*_clock_coverage` are machine readings, not kernel readings; judge verdicts
within-run and like-for-like ([`comparability.md`](comparability.md)) —
`agg=winner` flatters the arm that drew more kernels.

Write the decomposition down: one row per tied/lost cell — `family, cell,
delta, clock_ok, typecode_ok, class`. The classes are in §5.

### Phase 2 — Classify the stragglers (the class catalogue)

| class | detection | route | closes when |
|---|---|---|---|
| **W — ceiling-saturated wall (M1)** | delta tie band, both arms on same wave (per-cell residency arithmetic) | none — record and skip | same wall across ≥2 runs |
| **R — residency-starved small cell (M2)** | ≤30 % waves/SIMD | smaller tiles / `GlobalSplitU` (SS only; structurally illegal on CC/ZZ/HH/HPA) | within-run win above band |
| **C — complex accounting artefact (M3)** | CC/ZZ "stuck" at ~290/22 GFLOPS | none — re-read in BLAS-8 units (×4); they are at 80–97 % of the roof | doc cite, no deck change |
| **K — clock confound (M4)** | weak `*_clock_coverage` | re-run in TTY; pin SCLK only with the user's agreement; within-run verdicts only | strong-coverage batch shows a within-run win |
| **D — depressed cell / sweep-order defect** | family measured back-to-back in one old session (e.g. 2048³ then 256³) | re-measure in the next batch, one family per session | re-run flips the verdict |
| **F — floor-geometry steal (the only legal copy)** | floor winner differs, gfx900-tuned | §4.4 protocol (documented retune; worst cells only) | measured variant passes gates + batch |
| **N — virgin axis** | knob in forward domain, never drawn at the winner geometry (StaggerU trio, `1LDSBuffer`, `DepthULdsDivisor`, `LocalSplitU>1`) | NARROW draws from the mutator, or a targeted trial row (`DECISION_TRIAL_TILES`) | verdict flip or deck retirement with reason |
| **H — contaminated attribution** | stamp ≠ typecode (HH_HPA rows stamped `HH`) | fix attribution at the DB read (never edit the DB), re-derive verdicts | attribution matches across ≥2 independent reads |

Anything unclassifiable: suspect the measurement (K) or the attribution (H)
before the deck.

### Phase 3 — Candidate routes, in priority order

**Route 1 — the machine (default).** `oto tune --budget N --mutations M`:
the convergence loop (harvest winners → mutate ≤2 knobs → re-measure → verdict)
and the DB mutator's NARROW (1–3 knob draws) and WIDE (floor/DB tile donors ×
forward draws) — every mutant gated and novelty-checked before emission. You
supervise: after the batch, rebuild the DB, census, `cell_knob_diff`, read
verdicts, triage empties, decide the deck, hand off.

**Route 2 — targeted trial rows.** One hypothesis, one cell family — the
CC:256 `AF0/1EM=4` (D5) pattern, now first-class deck rows (2026-11-14, owner
Option B). Workflow: `python3 -m oto check candidates` green → GPU-validated in
TTY with `NumElementsToValidate` enforced → permanent deck row or retirement
with reason.

**Route 3 — floor-winner steal, with a bounded protocol.** The floor config is
gfx900 silicon; gfx90c differs in CU count, L2, and wave quantization. So:
1. steal only for the **worst** cells in the family (never the leader);
2. **document every changed knob** and why (e.g. StaggerU for the 7-CU raster,
   WGM − I/J swap family, LdsPad — CC never pads in the floor, a blind spot
   shared by Tensile's perf yamls, AF0/1EM←4 from the SGEMM recipe, DepthU);
3. gates green, then TTY-measure at both shapes; verdicts like-for-like. Never
   byte-copy, never "the floor is old so it must be worse".

**Route 4 — virgin axes.** `N` rows from the mutator. Heed the forwarding
caveats: `1LDSBuffer` needs `ScheduleInnerAccuracy ∈ {2,3}` — if the deck
forwards no SIA, the gate refuses it and that is the correct answer, not a bug.

**Route 5 — new cells / ladder rungs / TARGET_CELLS.** Class A territory
(`claude.md`); request with evidence, never hand-edit.

Work only on **active cells** (below ceiling, outside the tie band, not a wall).
Walls and settled cells are skipped without apology and without consultations.

### Phase 4 — After the batch (the autonomous refinement loop)

In order, after every batch:

1. `python3 -m oto.harness.kernel_db --rebuild`
2. regenerate and read the acceptance report; `cell_knob_diff`
3. triage every failed/empty phase (`python3 -m oto.harness.failure_triage`):
   - **gate-miss** — a kernel a gate would have refused: route to Class A with
     evidence; **you never patch gates**;
   - **measurement confound** — clock coverage, attribution, sweep order;
   - **deck-empty** — the row was refused at solution construction: remove it,
     reframe it, or retire it with reason;
   - **floor-selection artefact** — the like-for-like rule caught it; no action.
4. Retired losers get one line in `potential_configs.md` (never re-proposed).
   Winners get winner status + the next knob class to try.
5. Update `incomplete_work.md` and `results.md` with measured evidence only.
6. Carry the next question forward in writing — never into a consultation you
   do not need.

## 5. The overnight run protocol

- Deck state: `python3 -m oto check candidates` = 0 illegal; dry-run the
  generator if you extended the overlay; every candidate gate-green, every trial
  row gate-legal, every virgin row justified in a note.
- Sizing: rows × measured per-phase cost (~83 s on the reference machine);
  peak-family order beats mixed soup unless one cell is the whole point.
- Launch: **the user** runs it. You never start, watch, or kill the GPU. Wait.
- After: §4 Phase 4 loop immediately — stale reports mislead the next session.

## 6. The consultation triggers — when to reconnect, and for what

Reconnect for an agentic consultation only when:

- **T1** — a verdict flips loss → win or win → loss;
- **T2** — three consecutive batches with no cell moving beyond the ±2 % band;
- **T3** — an anomaly you cannot attribute with CPU tools;
- **T4** — a hardware-fact consequence arises (profile field change — Class A,
  you stop first);
- **T5** — the campaign or a major increment completes (post-mortem: docs,
  deck pruning, verification).

**Consultation payload** (write to a file; self-contained; no attachments):
the question; verbatim JSON extracts (`per_cell_verdicts` rows, winner map,
deltas) — never transcribed numbers; ruled-out strata with reasons; what you
need back (ranked routes, a doc edit, or permission for something specific).

**A consultation is not**: a status update, a rubber stamp, a research spree, or
a substitute for `corpus_census`. If a CPU tool can answer it, it is not a
consultation — that is the single most expensive failure mode of this loop, and
it is how the prompt-spam era burned its budget.

**Research beyond the docs**: never spawn it unasked. The research is either in
this ecosystem already (read it), or is a user-approved API-key invocation —
and anything it produces stays UNVERIFIED until a human checks it.

## 7. The prior art you must read — and obey

Before any campaign session beyond corpus study:

[`docs/harness_runbook.md`](harness_runbook.md) (census semantics + the three
pre-deck questions) · [`docs/comparability.md`](comparability.md) (the
like-for-like admission rule) · [`docs/operator_runbook.md`](operator_runbook.md)
(the best-effort contract this campaign extends) · `potential_configs.md`
(R41/R42..: what the corpus has finished with, what is virgin) · `results.md`
§9 (the straggler classes and their machine evidence) · `kernel_tuning_research.md`
(the mechanism model) · `gfx90c_theoretical_limits.md` (the bars) ·
`gfx90c_tuning_guide.md` §5–§12 (measured winners, the M-mechanism fold, today's
toolchain reality) · `knowledge_base.md` §10 (append-only law — the DB is the
record, never edited) · `tensile_tuning_context.md` (search philosophy).

## 8. What you never do

- Benchmark in a display/desktop session; stress the shared GPU; reset anyone.
- Trust `winner`-basis headlines or re-litigate settled numbers without a
  named like-for-like failure.
- Propose a config that has not passed `validate_config` + `ldspad_feasible`
  + (new rows) the deck check (`tensile_oracle` / `deck_check`).
- Byte-copy a floor winner; or steal a winner that is not in this family's
  worst cells.
- Edit `oto/`, `tests/`, the deck, profiles, gates, or the ledger — Class A
  territory; route with evidence.
- Hand-edit `kernel_db.json`, `registry.db`, or the report artifacts; they are
  append-only/rebuilt.
- Re-derive settled facts; spawn research without permission; spend a
  consultation on a CPU-answerable question.
- Claim convergence, or a win, from anything but a TTY benchmark read like-for-like.

## 9. Assignments, one line

`docs/operator_runbook.md` (bring-up) → this file (the campaign) →
[`docs/harness_runbook.md`](harness_runbook.md) → [`docs/comparability.md`](comparability.md) →
the device's starter + generated docs → the artifacts. Found a bug? Stop and
report it — Class B never patches oto. The GPU belongs to the user; the record
belongs to the ledger; the cadence belongs to the console.
