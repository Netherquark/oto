# The oto tuning campaign — a persistent, autonomous operator playbook

**Class B document.** Read this when you are the operator agent (or supervising it)
for a *tuning campaign* — the long, multi-day grind that turns a working
best-effort library into a converged one, one benchmarked batch at a time. If
the library does not build yet, you are one document too far: finish
[`operator_runbook.md`](operator_runbook.md) first. If you are working **on**
oto, this is not your file — read `claude.md`.

This document is the permanent form of the campaign prompt that produced the
gfx90c convergence work. It exists so the operator agent can run *persistently
across many sessions* — each multi-hour or multi-day — without re-deriving the
method from scratch and without paying for unbounded consultations mid-batch.

## 0. The two hard rules (inherited, never overridden)

1. **GPU work happens only in the user's TTY.** A desktop/Wayland session can
   be reset by a runaway GEMM (ring timeout, GPU node exception). In a display
   session you do CPU-only work and stop. If the user explicitly whitelists a
   legality probe in the display session, it is at most a 512²-cube build
   validation (Tensile `NumElementsToValidate`), never a benchmark and never
   "medium" sizes.
2. **CPU gates are not measurement.** A proposal that passes
   `oto check candidates` / `validate_config` is *legal to try*, not
   *competitive*. Only a TTY benchmark decides.
3. **The GPU is shared.** Never schedule, stress, or reset GPU work; the user
   owns the machine between batches. You wait, you do not push.

Per-session GPU budget rule of thumb from the reference campaign: legality
probes are cheap; the 10+ h overnight run is the user's to launch. Nobody
auto-runs the GPU from an agent session.

## 1. The persistent operating model

**State lives on disk, not in context.** Between sessions the campaign carries:

| artefact | what it holds | owner |
|---|---|---|
| `gfx90c_results/analysis/kernel_db.json` (path is historical; on a target device, whatever its runs produced) | every measured kernel: family, shape, winner, verdict inputs | oto (rebuilt, never edited) |
| acceptance report `acceptance_report.json` + `acceptance_report.html` | the last batch's verdicts: per-cell delta vs floor, tie bands, clock coverage, red/orange lists | oto (`AcceptanceReporter`) |
| `cells_resolved.json` / `cells_resolved.full.txt` | the per-cell winner map + cfg_gap | oto (`resolve_cells`) |
| `regression_matrix.json` | deck vs floor vs all-time | oto (`regression_matrix`) |
| `regression_matrix`, census, `failure_triage`, `coverage_map` outputs | axis history, empty-phase causes, legal-space coverage | oto (harness tools) |
| the seed overlay (`phases.seed.overlay.yaml`) | candidate rows not yet in the deck | oto (`generate_candidates`) |
| `incomplete_work.md` + the device's `<codename>_potential_configs.md` / `results.md` | decisions, open questions, verdicts | **you** (docs only) |

Every session reads these before touching anything. Context from a previous
session is never trusted without re-reading the artifacts it produced.

**The consultation budget.** LLM consultations are expensive and slow; oto is
the cheap part. Rule: *do not spend a consultation on a question a CPU tool
can answer*. Between consultations the agent works fully autonomously from
this playbook. Reconnect only at the triggers in §6. Charge the reconnect to
significant progress, never to convenience.

## 2. Session start (≈5 minutes, per session)

```bash
python3 -m oto doctor                        # 0 failures, or stop
python3 -m oto verify all                    # evergreen equivalence across commits
python3 -m oto.harness.kernel_db --rebuild   # NEVER trust a stale cache
python3 -m oto.harness.resolve_cells --taxonomy
```

Then read, in this order:

1. The **last acceptance report** — `acceptance_report.html` for the shape of
   it, `acceptance_report.json` for the numbers (`oto report --json`). Look at
   `per_cell_verdicts[].{delta_pct, tie, verdict, clock_adjusted,
   native_clock_coverage}`, `red_list`, `orange_list` — never `winner`-basis
   headlines (comparability.md rule: order statistics flatter the arm that drew
   more kernels).
2. The **deck state** — `python3 -m oto check candidates` (0 illegal, or stop),
   `python3 -m oto.tools.deck_review score|legality|flood --cap N`.
3. The **unresolved list** — open items in `incomplete_work.md` and the device's
   `potential_configs.md` marked open/untried.

Decide: consultation trigger (§6) → reconnect; otherwise, autonomous work (§3–§5).

## 3. Phase 1 — study the corpus (CPU only)

Goal: a complete, *written* decomposition of every **tied** and **lost** cell
into classes, before touching a deck row. This is the slow read; it is the
difference between converging and decorating.

For each family × cell where native is `TIE` or `FLOOR WIN`:

1. `python3 -m oto.harness.corpus_census --cell FAM:side` — every geometry ever
   measured there, with counts and floor-best. If the corpus is empty for the
   cell, that is data, not blank.
2. `python3 -m oto.harness.cell_knob_diff` — the native winner vs floor winner
   knob-by-knob; where they agree and where they diverge.
3. Attribution check — never trust a phase stamp: attribute via kernel typecode
   (`dtype_to_family`); flag contaminated rows (HPA stamped H/H vs HH).
4. Clock coverage — `native_clock_coverage` / `spoof_clock_coverage`; if either
   is weak, the cell's numbers are machine readings, not kernel readings;
   judge within-run only (M4) and re-measure on TTY before drawing conclusions.
5. The join vs the fold — multi-week-old absolute numbers are not comparable
   across runs with different SCLK; compare like-for-like only
   ([`comparability.md`](comparability.md)).

Write the decomposition down: one row per cell — `family, cell, delta, clock_ok,
typecode_ok, class`. The classes are in §4.

## 4. Phase 2 — decompose the stragglers (the class catalogue)

Each class: how to detect, which route addresses it, what closes it.

- **W — ceiling-saturated ties (M1).** Detect: delta tie band but both arms on
  the same wave (arithmetic: per-cell residency math). Route: *none* — record
  in `results.md` §"walls" and stop tuning this cell. Closing evidence: same
  wall across ≥2 runs.
- **R — residency-starved small cells (M2).** Detect: ≤30 % waves/SIMD, `tt`
  variants high. Route: smaller tiles or GlobalSplitU for wave turnover
  (SS-only; GSU>1 illegal on CC/ZZ/HH/HPA — structural). Closing evidence:
  within-run win above band.
- **C — complex accounting artifacts (M3).** Detect: CC/ZZ cells "stuck" at
  ~290/22 GFLOPS. Route: none — re-read in BLAS-8 units (×4); the cells are at
  80–97 % of the roof. Closing evidence: doc cite, no deck change.
- **K — clock-coverage confounds (M4).** Detect: weak `*_clock_coverage`.
  Route: re-run in TTY; pin SCLK if the user agrees; within-run verdicts only.
  Closing evidence: strong coverage batch with a within-run win.
- **D — depressed-cell / sweep-order defects.** Detect: family of cells measured
  back-to-back in one session in the old run (2048³ then 256³…). Route:
  re-measure in the next batch, one family per session key. Closing evidence:
  clean re-run flips the verdict (e.g. CC:256 reading TIE, −0.74 %).
- **F — floor-geometry steals (the only legal "copy").** Detect: the floor
  winner differs from native's on a large cell, and the floor's config is
  gfx900-tuned. Route: take the floor winner, **and document each changed
  knob and why** (e.g. `LdsPadA/B` for AS, `MaxOccupancy`; `VectorWidth` to the
  16-B cap; `WorkGroupMapping` to CU count). Only for the worst cells of the
  family (never the leader); never byte-copy. Closing evidence: documented
  variant passes gates + batch measurement.
- **N — virgin axes.** Detect: knob exists in the forward domain but was never
  drawn at the winning geometry (StaggerU trio, `1LDSBuffer`, `DepthULdsDivisor`,
  LocalSplitU>1). Route: NARROW draws from the mutator or a targeted trial row
  (`DECISION_TRIAL_TILES`, `oto.tensile.decks`). Closing evidence: verdict flip
  or a deck retirement with reason.

If a cell fits no class, suspect the measurement (K) or the attribution (3
above) before any deck change.

## 5. Phase 3 — candidate routes (in priority order)

1. **Machine-driven narrow/wide tuning (default).** `oto tune --budget N
   --mutations M` — the convergence loop (harvest winners → mutate ≤ 2 knobs →
   re-measure → verdict) and the DB mutator's NARROW (1–3 knob deltas) and WIDE
   (floor/DB tile donors × forward draws) strategies, emitting and gating
   before each phase. You supervise: after each batch, rebuild the DB, run the
   census and `cell_knob_diff`, read the verdicts, triage empty phases
   (`python3 -m oto.harness.failure_triage`), decide the deck, hand off.
2. **Targeted trial rows.** When Phase 3 isolated a *specific* hypothesis (one
   knob family, one cell family — the CC:256/512 `AF0/1EM=4` D5-row pattern),
   emit a `DECISION_TRIAL_TILES`-style row: `python3 -m oto check candidates`
   green, GPU-validated in TTY, then graduated or retired with reason in
   `potential_configs.md`.
3. **Floor-winner steal (retune).** Per class F — worst cells only, documented
   deltas, gate-green, TTY-measured.
4. **Virgin axes.** Class N rows; watch for blocked-by-forwarding caveats
   (e.g. `ScheduleInnerAccuracy 2/3` is required by `1LDSBuffer` — the gate may
   be right, not the deck).
5. **New cells/geometry rungs.** Bigger deck changes — `TARGET_CELLS`,
   ladders — are Class A (`claude.md`); request, do not hand-edit as Class B.

Work **only on active cells** (below their ceiling, outside the tie band,
not a wall). Walls and settled cells are skipped without apology.

## 6. Phase 4 — the consultation triggers (when to reconnect)

Reconnect for an agentic consultation only when:

- **T1** — a verdict flips loss → win or win → loss (the campaign moved; the
  plan may need an edit);
- **T2** — three consecutive batches with no cell moving beyond the ±2 % band
  (the current strategy has stopped paying off);
- **T3** — an anomaly you cannot attribute with CPU tools (conflicts with the
  docs, impossible hardware readings, a verdict no route explains);
- **T4** — a hardware-fact consequence arises (a profile field needs changing —
  Class A territory anyway; you stop first);
- **T5** — the campaign or a major increment completes (post-mortem
  consultation: tighten docs, prune the deck, promote results).

**Consultation payload** (write it to a file first — self-contained, no
attachments): the question; verbatim JSON extracts of the relevant verdicts
and census (`per_cell_verdicts` rows, winner map, deltas), never transcribed
numbers; the stratification you ruled out and why; what you need from the
consultation (ranked routes, a doc edit, or permission for something).

**What a consultation is not**: a status check, a rubber stamp on a winner, a
research spree. Research beyond the docs ecosystem is allowed only with the
user's key and permission; the research doc's claims stay UNVERIFIED until a
human checks them.

## 7. Phase 5 — autonomous refinement between batches (the loop)

Per batch, in order:

1. TTY: user launches the overnight/budget run (`oto tune --budget ...`); you
   do **not** launch GPU work.
2. After the batch: `python3 -m oto.harness.kernel_db --rebuild`; regenerate
   and read `acceptance_report.json` (`oto report --json` or the HTML);
   `python3 -m oto.harness.cell_knob_diff`.
3. Triage every failed/empty phase (`python3 -m oto.harness.failure_triage`)
   into: gate-miss (route to Class A with evidence — never patch gates as
   Class B), measurement confound, deck-empty (row refused — remove/reframe),
   or floor-selection artifact.
4. Retired losers get a one-line reason in `potential_configs.md` (retired,
   never re-proposed); winners get their winner status + the next knob class
   to try.
5. Update `incomplete_work.md` (open items only), the device's docs if a
   silicon fact got resolved, and `results.md` with measured evidence.
6. Carry the next batch's question into the next session — never into a
   consultation you don't need.

## 8. Phase 6 — the 10+ h overnight run

- Deck state: `python3 -m oto check candidates` = 0 illegal; dry-run the
  generator if you extended the overlay; every candidate row gate-green.
- Sizing: rows × measured cost per phase (e.g. ~83 s/phase on the reference
  machine); prefer one big family-blocked batch over mixed-family soup (TTY
  sweep-order depresses the tail).
- Launch: in the user's TTY with `oto tune --budget` / the agreed driver
  incantation; you may not start it, watch it, or kill it.
- After: the §7 loop, immediately — stale reports mislead the next session.

## 9. Reading order, one line

`docs/operator_runbook.md` (preconditions + verification) → this file →
[`docs/harness_runbook.md`](harness_runbook.md) (census/deck semantics + the
three pre-deck questions) → [`docs/comparability.md`](comparability.md)
(before trusting any A/B number) → [`agent_reference.md`](agent_reference.md)
(command card) → the target device's starter + generated docs → the artifacts
itself. The research is already done — use it; spawn no new research without
the user's permission and key.

## 10. What you never do

- Benchmark in a display/desktop session; ever.
- Treat a CPU-gate pass as a measured win; or quote `winner`-basis headlines.
- Byte-copy a floor winner to the target device without documented retuning
  (the AB rule: documented or not attempted).
- Edit `oto/`, `tests/`, the deck, or gates — route to Class A with evidence.
- Hand-edit `kernel_db.json`, the registry, or the report artifacts; they are
  append-only/rebuilt.
- Re-derive settled facts, re-litigate the fold without like-for-like rules,
  or mark UNVERIFIED research as measured.
- Spend a consultation on a question a CPU tool answers — that is the most
  common failure mode of this loop, and the most expensive.
