# The oto tuning campaign — the constrained path from backrocm to convergence

**Class B document.** Read this when you are the operator agent (or supervising
it) responsible for turning a working best-effort library into a converged one —
one benchmarked batch at a time — across multiple multi-hour or multi-day
sessions. If the library does not build yet, finish [`operator_runbook.md`](operator_runbook.md)'s
verification matrix first. If you are working **on** oto, this is the wrong file.

This document exists because of three facts about how oto got here, none of
which is negotiable:

1. **This project was built by spamming a prompt into agent sessions and
   re-spamming it until something moved** — the original converge‑gfx90c prompt
   (the "three tildes" block) was run under live GNOME, GPU melting, no TELEM;
   every time, the environment reset nearly cooked the machine, and the only
   reason it converged is that the prompt demanded it converge, not that the
   method was sound.
2. **The project earned its method**, over ~320 commits, by burning every
   shortcut it ever took:
   a broken ruler math that selected wrong GEMV winners (attempt1), an
   acceptance gate that graded baseline-vs-baseline (attempt2 draft), a corpus
   whose "winners" were order statistics (October 2026), a gate that accepted
   self-contradictory knobs, a complex-GEMM bar 4× over-scaled, a run-order bug
   that made one cell "the one loser" for three days, and an illegality
   manifest that shipped poisoned candidates for weeks without anyone noticing
   because nothing validated them.
3. **Every past iteration of that prompt is already encoded in this tree** — in
   `oto/harness/`, in the gates, in the ledger, in `phases.yaml`, in the docs.
   The campaign does not ask you to rediscover; it asks you to execute.

Your job, in one sentence: **propose the highest-quality candidates this
device has ever seen, cheap enough to gate, rare enough to ignore none, and
expensive enough to respect the hours between you and the owner's TTY.**
Everything in this file is in service of that sentence, and nothing in this
file is in service of anything else.

## 0. Read this before anything else

- **GPU happens only in the user's TTY.** A desktop/Wayland session is not a
  tuning environment; it is a monitoring convenience. GPU legs in a display
  session are limited to ≤512³ build/validation probes via Tensile's reference
  validator — never benchmark runs, never "medium" sizes, never anything that
  would make the fan curve uncomfortable while the owner is reading email.
- **CPU gates are not measurement.** A config that passes
  `validate_config` / `ldspad_feasible` is *legal to try*, not competitive.
  Only a TTY benchmark is ground truth. Fourteen rows spent a GPU night to
  discover this distinction; they are not being run again.
- **The owner is the bar.** Adoption of any candidate row, deck change, or
  report-graded verdict belongs to the owner. Your job is evidence, not
  verdicts.
- **The GPU belongs to the owner.** You do not start, schedule, watch, or kill
  anything on the GPU; the user launches what both of you agreed on.

## 1. Why you can do this at all — the history you are not allowed to repeat

Read this once. It never gets re-derived.

| Era | What happened | What it means for you |
|---|---|---|
| Jul 2026 | **FOSS United grant**: *A Generalisable Pipeline for Backporting ROCm to Obsolete AMD Hardware*. gfx90c/gfx902. | The deliverable is a **method**, not a faster GEMM. Every decision serves the method. |
| Jul–Aug 2026 | GPU characterisation; the *AMD vis-à-vis GPUs* diaries; first-party CDNA/Vega ISA PDFs studied. | Hardware facts come from primary sources, never from model memory. |
| Aug–Sep 2026 | **attempt1** — ~9.2 K LoC shell suite. The ruler math was broken four ways (shape tuples never matched; `adj_cells` no-op; missing controls inferred; phantom BF16 ruler). The report crashed. Retirement conflation made 0 benchmark-eligible phases survive gating. | If a script-level hack can teleport a wrong fact across 3 files, so can you. State lives in the database now. |
| Sep 2026 | **attempt2** — parallel draft branch, integrated append-only. Its acceptance gate was rejected (baseline-vs-baseline A/B artifact); the draft's 698.3 GFLOP SS@1024 floor beat was kept — the floor model was right, the gate was wrong. | A faster answer that skips provenance is not an answer; **baseline-vs-source ≠ A/B**. |
| 2026-09-17 | **oto is born**. The tuning loop becomes Python: corpus, ledger, mutator, acceptance report. | Loop > sermon; converge by measurement, not by argument. |
| Oct 10–16 2026 | **Refactor 1**: flat root → `oto/`; ≤60 LoC/function, ≤600 LoC/file; suite split by responsibility; 9× faster suite. | Effort goes into candidates, never into bookkeeping. |
| Oct 14–22 2026 | The failures that made this curriculum what it is:
wide tiles eliminated (MacroTile 256-wide class), `AF0EM` silently wrong,
`StaggerU=0` refused by an inverted gate, `LocalSplitU` shadowed by explicit
`WorkGroup`, `AggressivePerfMode=2` dead, the **Z=8 vs Z=16 gate miss**,
candidates oracle-checked by Tensile's own construction path (`tensile_oracle`/`deck_check`),
`TransposeLDS` unreachable (MFMA path / `UnrollMajorLDS`). | Illegal configs must be refused by **gates**, not by a sad CSV at the end of the night. |
| Oct 21–24 2026 | **The fold was found**: `agg=winner` is an order statistic; three of the "wins" were protocol artefacts; HPA rows were misattributed (typecode vs stamp); the 17.5-point environment band soaks the ±2 %/5 % verdict band; complex families re-scaled to BLAS-8 (CC 80–97 % of roof, not 20 %). | Like-for-like always; kernel typecode is ground truth; if coverage is weak the number is a machine reading. |
| Oct 26–29 2026 | rocm-libraries super-repo port; user-provided ROCm 7.x; `best_effort_library_rocmlibs`; yolo26 person 0.87 on the nightly stack. The 6.4.4 library (`b6ccd448…`) deterministically wedges this stack. | The toolchain is user-provided; nothing from `/usr` leaks. |
| Nov 13–14 2026 | **Refactor 2**: device profiles (`profiles/<codename>.json`), `NumElementsToValidate=128`, explicit `profile=` threading, CC AF4/4 rows adopted as first-class (Option B). | The device is **data**, not a code path; validation is a correctness gate, not an option. |

Three implications, immutable:

1. **Prompt-spam is over.** Everything repeatable is now either code or a gate.
   What remains for you: research synthesis off primary sources, candidate
   synthesis **inside harness-visible domains**, and judgment. Everything else
   is already code.
2. **The corpus is the memory.** Between sessions you remember nothing the
   artifacts do not contain. Rebuild and re-read before deciding.
3. **Effort is finite; the GPU is precious.** Every candidate proposal must be
   cheap to gate and costly to ignore.

## 2. The neurosymbolic division of labour

| Layer | Owner | Examples |
|---|---|---|
| **Symbolic** (exact, reproducible, unchanged) | gates + Tensile + the ledger | `validate_config` → `ldspad_feasible` → `assembly_class_valid` → `occupancy_feasible`; Tensile's own reference validator (`NumElementsToValidate=128`) via the client — the one legality oracle no config gets past; the ledger's identical-fingerprint skip (with the documented mutant exception); the retirement gate |
| **Neural** (judgment, synthesis, narrative) | you, inside the harness | candidate families in corpus space; reading the acceptance report; triaging failure classes; docs; the next hypothesis class |
| **Measure** | the user's TTY only | every kernel's actual performance |

Invariant: **neural proposals enter only via the symbolic pipeline.** You never
hand a config to the deck that has not passed the gates; you never submit
ungated candidates to a bench. You never "know" a kernel is fast; you read a
report.

## 3. The persistent operating model — every session

### 3.1 Session start (≈5 minutes, no exceptions)

```bash
python3 -m oto doctor                        # 0 failures or stop
python3 -m oto verify all                    # evergreen, across commits
python3 -m oto.harness.kernel_db --rebuild   # never trust a stale cache
python3 -m oto.harness.resolve_cells --taxonomy
```

Then, in order, all reading from artifacts, none from memory:

1. **The last acceptance report** — `oto report --json` (or the HTML for shape):
   `per_cell_verdicts[].{delta_pct, tie, verdict, clock_adjusted,
   native_clock_coverage}`, `red_list`, `orange_list`, `basis_protocol`. Never
   `agg=winner` headlines — order statistics flatter the arm that draws more
   kernels. Judge only like-for-like (`comparability.md`).
2. **The deck** — `python3 -m oto check candidates` (must be 0 illegal) — plus
   `python3 -m oto.tools.deck_review score|legality|flood --cap N`.
3. **The unresolved list** — `incomplete_work.md` open items and the device's
   untried items in `potential_configs.md` / `results.md`.

Decide **before** touching anything: consult (§7) or extend (§4–§6). If you
cannot say which within the 5 minutes, you have not read enough — read more.

### 3.2 Session end (≈10 minutes)

1. `incomplete_work.md` is the open register: close what closed, add what
   opened. Completed work moves out to `changelog.md` / `results.md`.
2. Record the session in `results.md` if anything was measured; the deck's
   `potential_configs.md` otherwise. One paragraph per batch; no speculation.
3. If a silicon fact got resolved: update `<codename>_theoretical_limits.md` or
   `<codename>_tuning_context.md` with the evidence; if a ceiling moved, it moved
   in that doc, nowhere else.
4. Never claim, never imply, never report a win you did not measure.

### 3.3 State map

| artefact | who writes | who reads |
|---|---|---|
| `kernel_db.json` | `kernel_db --rebuild` | everyone |
| `acceptance_report.{json,html}` | `AcceptanceReporter` | everyone |
| `cells_resolved.{json,full.txt}` | `resolve_cells` | everyone |
| `config_writer` GlobalParameters flow into every phase's YAML | you via the deck/`generate_candidates` | you via the ledger |
| `phases.yaml` (deck) + `phases.seed.overlay.yaml` (overlay) | you (rows) · you (with user sign-off) (deck/overlay) | `oto check candidates` · preflight · the run |
| the registry `gfx90c_results/registry.db` (runs, phases, records, proposals) | runs; `kernel_db --rebuild` | ledger · mutation arm · retirement |
| `potential_configs.md` / `<cn>_potential_configs.md` | you | everyone |
| `incomplete_work.md` / `results.md` / `changelog.md` | you | everyone |

## 4. Phase 1 — Study the corpus (the slow part; decides everything)

For every family × cell where native `TIE` or `FLOOR WIN`, before you propose
anything, narrate its history:

```bash
python3 -m oto.harness.corpus_census --cell FAM:side
```
— exhaustive local history: every geometry ever measured here, counts, floor
best. Empty cell = data, not blank.
```bash
python3 -m oto.harness.cell_knob_diff
```
— native winner vs floor winner knob-by-knob; where the configs agree the gap
is structural; where they diverge, the gap is a knob. Look for `cfg_gap`
in `resolve_cells --taxonomy` output: `identical` / `near` / `retile` /
`no-floor` — it is the mechanical half of the tie taxonomy.

Fact protocol before you believe a number:

- **Attribution.** Kernel header typecode is ground truth (`dtype_to_family`).
  A phase stamp can lie (HPA rows stamped `HH` vs `HHH`).
- **Clock coverage.** Weak `native_clock_coverage` → the cell is machine noise;
  judge within-run only; re-measure before concluding.
- **Protocol.** Like-for-like only (`comparability.md`); verdicts grade one
  protocol at a time.

Write the decomposition down: one row per cell — `family, cell, delta,
{identical|near|retile|no-floor}, clock_ok, typecode_ok, class`. The classes
are §5. If a cell does not land in a class, you do not understand it yet.

### The historical pattern inventory — read this before proposing candidates

What has actually won on this part, per the corpus:

- **SS** — wins on bigger tiles at this APU's wave-quantization (the 192/256/
  512 residency starvation is the binding constraint; the `resolve_cells --taxonomy`
  output names these `R`-class cells — see §5). GlobalSplitU=2/4 matters on small
  squares; `LdsPadA=2` is a real difference maker in the CC/ZZ space (a blind
  spot shared by Tensile's perf yamls); `WGM 2/3/-1/-4` was unexplored before
  the R47 batch.
- **HH/HH_HPA** — 91% of the legal space unexplored at 512³-class cells; the
  HPA band had headroom.
- **CC/ZZ** — at 80–97 % of the FMA roof in BLAS-8 units; nothing to fix in the
  deck, everything to fix in the *report*; `U`/`P` bytes are the truth.
- **DD** — floor parity through the floor itself (`retile`-class, not a deck gap);
  1024/1365 are re-tiles on a smaller winner.
- **Winners never come from the floor unchanged** — they come from native
  configs re-tuned for this part's 7 CUs, 1 MiB L2, 40-slot/SIMD waves.

## 5. Phase 2 — Decompose the straggler list into its classes

One class at a time; address each in its own sequence, never all at once.

| class | detect | route | closed by |
|---|---|---|---|
| **W — ceiling-saturated wall (M1)** | tie band, both arms on the same wave (per-cell residency arithmetic) | none — record and skip | ≥2 runs same wall |
| **R — residency-starved small cell (M2)** | ≤30 % waves per SIMD (e.g. `SS:256`, `HH:256`, `DD:192`, `ZZ:128`) | smaller tiles / `GlobalSplitU` (SS only; structurally forbidden on CC/ZZ/HH/HPA) | within-run win vs band |
| **C — complex accounting artefact (M3)** | CC/ZZ pinned at ~290/22 GFLOPS | none — re-read in BLAS-8 units (×4 — the roof is 80–97 %, not 20–24 %) | doc correction, no deck change |
| **K — clock confound (M4)** | weak `*_clock_coverage` | re-run with the user; within-run only; pin SCLK only with explicit permission | strong-coverage batch + within-run win |
| **D — depressed-cell / sweep-order defect** | family back-to-back in one old run (2048³ ahead of 256³ …) | re-measure; one family per session | flipped verdict on the re-run |
| **F — floor-geometry steal (worst cells only)** | floor winner beats native winner at the *worst* native cell of the family; gfx900-tuned | §4.4 protocol: documented retune, gate-green, TTY-measured | measured variant on both shapes |
| **N — virgin axis** | axis in forward domain, never drawn at the winner geometry (StaggerU trio, `1LDSBuffer`, `DepthULdsDivisor`, `LocalSplitU>1`, `GLVW` wandering) | mutator NARROW or a trial row (`DECISION_TRIAL_TILES`) | verdict flip or retired row with reason |
| **H — contaminated attribution** | stamp ≠ typecode | fix attribution at the DB read (`dtype_to_family`); never edit the DB | independent reads agree |

If a cell fits no class: suspect K or H, then the deck — never the "ceiling".

## 6. Candidate routes, in priority order

**Route 1 — the machine (default).** `oto tune --budget N --mutations M` — the
convergence loop: harvest winners → mutate ≤2 knobs → re-measure → verdict. The
DB-hooked mutator emits NARROW (1–3 forward-knob deltas), WIDE (floor/DB tile
donors × forward draws) and DIRECTION (parent → floor winner) with `bypass`
enabled and novelty enforced by the ledger; every mutant is gated and novelty-
checked before emission. You **supervise** it: you do not hand-describe the
tiles; you keep the run legal and the harness fed (census, kernel_db rebuild,
run-start, run-stop). This is where 90 % of the campaign's tokens should go.

**Route 2 — targeted trial rows.** One hypothesis, one family, one shape — the
CC:256 `AF0/1EM=4` (D5) pattern, now permanent deck content (2026-11-14, owner
Option B). The workflow:

```bash
python3 -m oto check candidates      # row must be 0 illegal
# TTY: the phase benchmarks via the 7.x client with NumElementsToValidate=128
# THERE IS NO OTHER BAR — not your confidence, not the gate, not the tune guide
```
Gates preflight → TTY → measure → graduate or retire with reason. The row class
starts as `_trialD<n>` via `DECISION_TRIAL_TILES` (`oto/tensile/decks.py`) and
ends, if the owner agrees, as a permanent deck row.

**Route 3 — floor-winner steal, bounded and documented.** This is where the
gfx900 floor configurations enter the deck. The constraints that make a steal
*legal* here are the same constraints that made the attempt1 machine fail:

1. **Worst cells only.** Steal is for the family's weakest performable cells,
   never the leader (the floor winner for a cell both arms flood is a copy, not a
   candidate).
2. **Document every changed knob and why.** The gfx900 floor winner is 56-CU,
   HBM2, 2048-barrel-tuned silicon; the gfx90c part is 7-CU, DDR4-shared, wave-
   quantization-starved. The differences that matter: `StaggerU` (32 was a
   56-CU raster choice), `WorkGroupMapping` (7 CUs want the negative I/J-swap
   family), `LdsPadA/B` (CC never pads in the floor — a blind spot shared by
   Tensile's own perf yamls), `VectorWidth` (16-B cap on this part), LDS pressure
   (16 KiB LDS/WG, not 64 KiB). Every adaptation gets a row in
   `potential_configs.md` §steal with the reason before it is decked.
3. **No byte copies.** Verify `AF0/1EM` (assertion only holds when 4-divisible;
   verify free dims of the target cells), verify wave quantization, verify
   residency math (`accVGPR` against the per-thread budget in
   `oto/tensile/gates/occupancy.py`), verify LDS with `ldspad_feasible`, verify
   load-divisibility with `validate_tensile_loads`, verify solution-construction
   legality with `python3 -m oto.harness.tensile_oracle` for new rows, and verify
   end-to-end with the client before you benchmark in TTY.
4. **Measured only.** A steal that gates green and fails benchmarking is a
   hypothesis honestly reported, not a failure to lament.

**Route 4 — virgin axes from the forward domain.** From `FORWARD_KNOB_DOMAINS`
in `oto/tensile/synthesis/db_knobs.py`: `N` rows on the winner geometries. Notable cases that remain open: `StaggerU=0` (now legal — the gate
had it inverted; it was never run), `1LDSBuffer` (blocked by missing
`ScheduleInnerAccuracy ∈ {2,3}` forwarding — the gate is the truth, not a bug),
`DepthULdsDivisor` (same SIA constraint), `WaveSeparateGlobalReadA/B` (never
sampled). Consult the deck's `NOT_FORWARDED_KNOBS`
(`oto/tensile/knob_surface.py`) before adding any.

**Route 5 — new cells / ladder rungs.** `TARGET_CELLS`, `LADDER` — Class A
(`claude.md`) content; request with evidence, never hand-edit.

**The active-cell rule.** Everything else is scaffolding. Work only on active
cells (below ceiling, outside the tie band, not a wall). Walls and settled cells
are skipped; settled means the verdict is within-band for ≥2 runs.

## 7. Consultation triggers — when to reconnect, and for what

Reconnect for an agentic consultation only when one of these is true:

- **T1** — a verdict flips loss → win or win → loss;
- **T2** — three consecutive batches with no cell moving beyond the ±2 % band;
- **T3** — an anomaly you cannot attribute with the CPU tools;
- **T4** — a hardware-fact consequence arises (a profile field needs changing —
  Class A territory; you stop before involving the owner);
- **T5** — campaign completion / a major increment (post-mortem: docs tightened,
  deck pruned, verification matrices refreshed).

**Payload** (always written to a file, self-contained, no attachments):

```
q:        the one-line question / decision the consultation exists for
evidence: verbatim JSON excerpts (never transcribed), `basis_protocol=family`
ruled_out: strata you excluded and why
needs:    ranked routes, or a doc edit, or permission (list exactly what)
```

**A consultation is not**: a status check, a rubber stamp, a research spree, or
a substitute for `corpus_census`/`resolve_cells`. If a CPU tool can answer it, it
is not a consultation — that is the single most common, most expensive failure
mode this campaign exists to prevent.

**Research is never spawned on your initiative.** The research is in the docs
already (`kernel_tuning_research.md`, `gfx90c_tuning_guide.md`,
`tensile_tuning_context.md`, `complex_gemm_research_brief.md`,
`results.md`/`potential_configs.md` history); an agentic web-research consult
runs only with the user's explicit key + permission, and its output stays
UNVERIFIED until a human checks it.

## 8. After the batch — the autonomous refinement loop

After every TTY batch (and before the next one is scheduled):

1. `python3 -m oto.harness.kernel_db --rebuild`
2. `oto report` → read like-for-like; `cell_knob_diff` for the winners-moved list
3. `python3 -m oto.harness.failure_triage` — classify every empty phase:
   **gate-miss** → Class A with evidence (you never patch gates, the deck
   or profiles); **measurement confound** → K-class retriage;
   **deck-empty** → refused row: remove, reframe, or retire with the Tensile
   reason recorded; **floor-selection artefact** → no action.
4. Retired losers get one line in `potential_configs.md` (never re-proposed);
   winners get their status + the knob class the next session probes.
5. `incomplete_work.md` + `results.md` — every number measured, every verdict
   cited, every retirement named.
6. The next session's question rides in the docs, never into a consultation
   you do not need.

## 9. The overnight run — 10+ h

- **Deck state first**: `python3 -m oto check candidates` = 0 illegal; dry-run
  the generator (`generate_candidates --dry-run`) if you extended the overlay;
  every row gate-green and every virgin row justified in a note.
- **Sizing**: rows × measured per-phase cost (~83 s on the reference machine);
  one family-blocked batch beats mixed soup (sweep-order depresses the tail).
- **Launch**: the user. You do not start, watch, or kill.
- **After**: §8 loop immediately — stale reports mislead the next session.

## 10. The operator's never-do list

- Never benchmark in a display/desktop session.
- Never trust `agg=winner` headlines or re-litigate settled numbers without a
  named like-for-like failure; the ±2 % band is the tightest band that means
  anything — anything tighter is precision you do not have.
- Never propose a config that has not passed `validate_config` +
  `ldspad_feasible` (+ the deck check / oracle for new rows).
- Never byte-copy a floor winner; never steal for cells that are already won;
  never treat a floor config as a substitute for thinking about *why* it wins.
- Never edit `oto/`, `tests/`, the deck, profiles, gates, or the ledger —
  route to Class A with evidence.
- Never hand-edit `kernel_db.json`, `registry.db`, or the report artifacts;
  they are append-only/rebuilt.
- Never re-derive settled facts; never spend a consultation on a question a CPU
  tool answers; never spawn research; never present a CPU-gated proposal as a
  win.

## 11. Reading order, one line

`claude.md` §1 (role) → `docs/operator_runbook.md` (bring-up and the best-effort
gate) → this file → `docs/harness_runbook.md` (census semantics + the three
pre-deck questions) → `docs/comparability.md` (before you trust any A/B number)
→ the device's starter + generated docs (`<cn>_theoretical_limits.md`,
`<cn>_tuning_context.md`, `<cn>_harness_study.md`) → the artifacts themselves
(report JSON, census output, `resolve_cells` table, ledger). The research is
already done — read it. The gates are already written — use them. The ledger
already remembers — trust it once you have rebuilt it.
