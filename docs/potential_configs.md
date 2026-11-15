# Candidate deck for the gfx90c Vega-7 port — rewrite 8 (2026-10-23)

Supersedes rewrite 7 (R34–R49, kept below for history). **What is new here:** the
grade-6 acceptance report's headline wins are re-read against the *measurement
protocol* and three of them are measurement artefacts (§R50). Every phase in the
corpus that holds the four ORANGE cells' "winning" numbers was run under a
**single-problem invocation**, while the whole floor arm was measured under the
**family-protocol invocation** (one client process, 5–8 problem sizes); the same
config under the two protocols differs by 2.1–4.2×, and run_20261008_005217
reproves it same-config-same-client in one night (HH:256's 32x64x16/4x4/VW4/DU16:
763.4 single-problem vs 188.9–206.5 family across three other runs). §R50 regrades
the whole table like-for-like: 22 WIN / 16 TIE / 0 LOSS, and moves the honest
straggler list to SS:256 **11.6 %**, HH:256 **8.4 %**, CC:192 **16.1 %**,
DD:192 **21.3 %** (never previously flagged), ZZ:128 27.8 %, HH_HPA:512 39.4 %,
HS_HPA:512 38.2 % of bar. §R51 types the straggler classes and what each class's
work actually is; §R52 closes the tie list (all twelve ties are ≥90 %-of-roof
ties, config work exhausted); §R53 records which kernel types have won, per
family, across all 30 native runs; §R54 is the cover-map reading and the R50 deck
now committed to the repo (iso calibration, HPA 512-band push, micro-cube knobs -
52 new phases, 0 gate refusals, 0 Tensile refusals); §R55 spec's the overnight
TTY run; §R56 closes the failed-candidate triage: gate calibration is now 0
misses / 0 false-rejections over 5662 native phases and every historical failure
class maps to a rule that exists today.

Rewrite-7 content stands: the honest tie table (§R36), the virgin-knob batch
(§R37), the supra-16384 frontier (§R40), the finished axes (§R41), the ORANGE
geometry batches and their results (§R44–R49).

The pre-rewrite-7 findings stand: gate closed (§R24); no steal was justified
under the *progress* reading (§R26) — §R54.3 now documents the steal *decision*
post-regrade; the ledger trace is §R28; the GCN5 literature map is §R33.

**Owns:** the candidate deck, the routes, the search rules, and the reading of the
gates. Does not own: ceilings and verdict bars
(`docs/gfx90c_theoretical_limits.md` §5), measured evidence (`docs/results.md`), hardware
facts (`docs/gfx90c_theoretical_limits.md` §1–§3), the per-cell winners
(`gfx90c_results/analysis/cells_resolved.full.txt`), or the durable Tensile
mechanics (`docs/research/kernel_tuning.md` §4).

---

## R40 — the geometry axis was never tested, and legality is why

**The corpus has never measured a large tile and a small thread tile at the same
time.** 140 distinct SS geometries, 9345 rows, 21 tile areas — and *every* tile
above 16384 elements carries ThreadTile 16×8: 128 accumulators a thread against
the winner's 64. The 30 % drop at 256×128 (802 vs 1187 GFLOPS) is a two-factor
experiment, and "big tiles are worse" was read off it. Read off the emitted code
objects, the confound is the whole effect:

| config | VGPR | LDS/group | residency |
|---|---|---|---|
| SS 128×128 TT8×8 DU8 (winner) | 113 | 16384 | 2 groups × 4 waves = **8 waves** |
| SS 256×128 TT16×8 DU8 | 199 | 28736 | 1 group × 4 waves = **4 waves** |
| HH 128×128 TT8×8 DU16 (winner) | 63 | 24832 | 2 groups × 4 waves = **8 waves** |
| HH 256×128 TT16×8 DU8 | 105 | 14336 | 2 groups × 4 waves = 8 waves |

So SS's only large-tile point lost half its residency by construction, and HH's
kept its residency but ran at VW4/VW2 (8 or 4 B) instead of the winner's VW8
(16 B, the load cap). **256×128 at VW8 had never been emitted for any family**,
and the reason is not the deck: it is illegal. `gates/loads.py` refuses it, and
so does every other large tile — see §5.1 of `docs/gfx90c_theoretical_limits.md` for
the resulting per-family area cap. Above 16384 elements the gate admits exactly

* SS: 256×128 and 128×256 (VW2 outright, VW4 under `AssertFree1ElementMultiple`),
* HH / HH_HPA / HS_HPA: the same pair at DU16, plus 64×512 / 512×64 at DU8,
* CC, DD, ZZ: **nothing**.

**So the frontier is 22 tiles, not a sample of a big space**, and the whole
remaining geometry question fits in it. `_FRONTIER` emits them; 241 new
configs of deck in total:

| block | rows | what it answers |
|---|---|---|
| frontier, 22 tiles × 4 patterns | 88 | is 32768 elements better than 16384 at 64 accumulators a thread? |
| `AssertFree0/1ElementMultiple` ∈ {2,4,8} on 8 measured winners × 4 patterns | 93 | it appears in 37 of 7622 emitted configs: what does `GuaranteeNoPartial` (the dropped free-dimension predication) buy on geometry already known to be good? |
| the frontier at half the thread tile (256×128 / 8×4, 32 accumulators) × 4 patterns | 16 | separates "the area is bad" from "the registers ran out" — same area, half the pressure |
| `WorkGroupMapping` 2 and 3 on the frontier, and on DD's winner | 44 | 1 and 8 both lose to 4; the middle was never emitted, and the tile order changes at 2× area. DD's four ties are wave quantisation on 768/1000/1365, the one cell class a raster knob can still move |

**How to read the result.** It is a designed experiment, so each outcome has one
reading, and three of the four are informative:

| 256×128/8×8 | 256×128/8×4 | conclusion |
|---|---|---|
| beats 128×128 | — | the area wall was register pressure; re-open every family's area ladder |
| loses | beats 128×128 | same: pressure, not area |
| loses | loses | 16384 is a real optimum for this part, and the 18 ties are noise (§R38, §R36) — stop looking at geometry |
| ties | ties | inside the ±16.45 % band; needs replication, not another geometry |

**Two deck bugs found while building it, both fixed here.** `TARGET_CELLS` was
missing DD 768/1024/1365 and HH 4096, so *no generated row could ever be measured
on those tie cells* — three of the four `DD` ties and one `HH` tie were
unreachable by construction. And `PATTERNS["HS_HPA"]` restated `Alik_Bljk` in
slot 4, so the family covered three of the four contraction patterns.

**Budget.** 241 distinct new configs at the measured 78 s per executed phase is
≈5 h. `--budget 10` stays, so the run simply exits when the deck is exhausted;
padding it to 10 h would mean re-measuring the axes §R41 has closed.

---

## R41 — axes the corpus has finished with

Each row is a knob or an axis that a previous plan expected to pay, and the
measurement that ends it. Re-emitting any of these costs a night and cannot win.
The empirical read behind each row is `python3 -m oto.harness.corpus_census`
(`docs/results.md` §15); re-run it before re-opening one.

| axis | best found | the number that closes it |
|---|---|---|
| `LdsPadA`/`LdsPadB` | 0/0, every family | non-zero pad always loses: CC 346.7→313.4, HH 2749→2240, DD 98.8→97.9 |
| `GlobalSplitU` | 1, every cell | SS:1024 G1 1135 / G2 936 / G4 740; DD:2048 99 / 95 / 95 |
| `StaggerU` | 32 | 32 in 7532 of 7622 configs; 0/8/16 measured and lost |
| `NumLoadsCoalesced` | 1 | closed by proof, `gates/loads.py::_nlca_stage` |
| `WorkGroupMapping` 1 / 8 / −4 | 4 | 4 beats 1 (92 rows), 8 (80) and −4 (2) by 8–20 % in every cell; **2 and 3 are untried and are in the §R40 deck** |
| ZZ tile geometry | 32×32×8 | flat 24–25 GFLOPS across 17 distinct geometries, 23.1–24.5 — no tie cell to win (§5.1) |
| DD tile geometry | 64×64 / 128×128 | 98.8 GFLOPS = 98 % of the FP64 peak; its 4 ties are wave quantisation, and the deck carries 32×64 / 48×64 / 64×48 for them |
| CC tile geometry | 64×64 | no legal tile above 8192 elements (§5.1), and 128×64 / 64×128 both measure worse than 64×64 |

Unchanged and still open, deliberately: the knobs the launch boundary does not
forward (`1LDSBuffer`, `DepthULdsDivisor`, `TransposeLDS`, `LocalSplitU`) stay
§R16/§R20 — a deck row carrying one is a silent no-op, so none is emitted. The
38 pending proposals and the `tie_band_pct = 5.0` decision are §R36/§R38.

---

## R34 — the overnight run failed twice, and both causes are now fixed

**Cause 1: it measured nothing, and the driver called that `completed`.**
`run_20261019_002432` (since purged from the registry and run tree; only its
abort transcript survives, under `gfx90c_results/purge_backup_*/`) ran 9 h 47 m,
produced 409 phase directories, one partial
result CSV and **413 core dumps**, and was filed `status=completed`. The cores
backtrace `#6 __cxa_throw → #7 Tensile::Client::GetHardware → #8 main`, and the
core strings carry `Error 100(hipErrorNoDevice)` at
`Tensile/Source/client/main.cpp:273`. Telemetry agrees: `gpu_busy_percent = 0`
for every phase after the first. The GPU is healthy now (`rocm-smi`: gfx90c,
68 °C, 24 W) and both probe configs re-ran at `exit=0` against the same built
client, so this is the documented "do not launch under the full GNOME/Wayland
compositor" failure, not a hardware fault.

The driver had no way to notice. **Fixed** in `oto/runners/phase_runner.py`
(`cf18277`): `ABORT_AFTER_CONSECUTIVE_EMPTY = 5`, a refused tile
(`skipped_illegal` / `skipped_by_user`) does **not** count toward the streak, and
an aborted run finalises as **`failed`** with an `abort_reason` rather than as
`interrupted`. The streak counts only phases whose client actually ran: a tile
that never launched the client failed at kernel generation and carries a
per-config verdict, not evidence that the device is gone. Tensile's
`loading config file .../ClientParameters.ini` line is the signal — present in
every phase that produced a measurement and in none of the 951 that did not,
corpus-wide — so the void run's GPU loss still trips it while
run_20261018_004835's three and run_20261017_092909's five consecutive
unbuildable tiles do not. Pinned by
`tests/test_phase1_readonly_gpu.py::GpuLossAbortTests`.

**Cause 2: the mutation arm cannot see the cells it exists to fix.** Of that
run's 412 candidates, every single one went to a small cell that already beat the
floor — SS:256 **155**, CC:192 67, ZZ:128 41, HH:256 39, DD:192 37,
HH_HPA:512 35, HS_HPA:512 33, HH_HPA:4096 1. None went to any cell that ties.

The mechanism is one line. `_mutate_cell` returned early when
`winner_info["is_below_ceiling"] is False`, and `is_below_ceiling`
(`oto/metrics/benchmark_analytics.py`) is measured against `REALISTIC_CEILINGS`
(`oto/device/loader.py` and `oto/device/kernel_vocabulary.py`), a measured-empirical snapshot the large cells have since
*passed*: SS publishes 1118.7 and measures **1135.1**. So the cells that tie the
floor are exactly the cells the arm refuses to touch, and the budget recirculates
into the small cells forever.

**Fixed** in `oto/ledger/convergence_agent.py` + `oto/metrics/ab_delta.py` (`c2ab21f`).
`ABDeltaMixin.cells_not_beating_floor` reduces the A/B pairing to the set of
cells whose winner has not beaten the recalled floor (`agg="winner"`, so both
arms are graded on their best per-kernel median); `ConvergenceAgent._floor_losers`
reads it at most once per iteration and `_cell_settled` now returns "settled"
only when a cell is at/above its ceiling **and** has beaten the floor. Two guards
keep it honest: the floor is never consulted for a below-ceiling cell, and an
unreadable floor (no frozen reference recalled) leaves the ceiling rule exactly
as it was, so an offline corpus cannot flood the deck. On the live corpus the set
is precisely the 18 TIE cells of §R36 — not one WIN, not one LOSS.

---

## R35 — every virgin-axis reading taken before 2026-10-17 is void

The plan's pessimism about the "virgin axes" (StaggerU, NonTemporal, MaxOccupancy,
InnerUnroll, PGR, SgprForGRO, LdsPad) rests on a probe generation that cannot
support it. The `sw*` rows in `phases.yaml` — the only place those knobs were
ever set outside `_TIE_ADAPT` — carry **three** knobs (`MacroTile`, `ThreadTile`,
`VectorWidth`) and are built on `ContractionPattern: Ailk_Bljk` at
`VectorWidth: 1`. They ran once, in `run_20261015_041159` (28 phase dirs), and
never again.

Measured against their **own same-run winner**, they are not probes at all:

| cell | best non-probe in the run | best `sw*` probe | ratio |
|---|---|---|---|
| CC:1024 | 309.6 | 172.9 (`swNonTemporalA1`) | 0.56 |
| SS:1024 | 1080.3 | 518.8 | 0.48 |

All 15–17 probes in that run land in **0.36–0.56**. A uniform ~2× loss across
`MaxOccupancy`, `InnerUnroll`, `StaggerU`, `StaggerUStride`, `UseSgprForGRO`,
`PGR`, `LdsPadA`, `FractionalLoad`, `AggressivePerfMode` and
`AssertFree0ElementMultiple` is not fifteen independent knob effects; it is one
bad base — the wrong contraction pattern at half the vector width. **Every
negative conclusion carried from that generation is void**, and the "we already
tried the virgin axes" line of reasoning is withdrawn.

The 2026-10-17 `_TIE_ADAPT` batch is *not* in this class: it sits on the measured
winner geometry, and each of its knobs was re-verified against
`_fork_list_for_phase` (not inferred from the batch comment) to confirm it
reaches Tensile. Those probes measure 0.83–0.98 — real, and real near-misses.

One row class *is* a no-op and is now recorded as such: `LocalSplitU` appears in
neither `config_writer.FORWARDED_KNOBS` nor `NOT_FORWARDED_KNOBS`, so the harness
strips nothing, the writer never forks it, and the two `LocalSplitU: 2` rows in
`_TIE_ADAPT` benchmarked the plain base tile under a name claiming otherwise.
It is a fourth instance of the placebo class the `FORWARDED_KNOBS` docstring
names, and `LocalSplitU` belongs in `NOT_FORWARDED_KNOBS` when someone next
touches that tuple.

---

## R36 — the 18 tie cells, band-honest

`_floor_losers()` on the live corpus, in full. Band: the report's `tie_band_pct`
is ±5.0 %, and the corpus's own reproducibility band is **±16.45 %**
(`coverage.reference_thresholds`, source `max(cross-arm, repeat-tail,
shipped-floor)`).

| cell | verdict | native | floor | delta | |
|---|---|---|---|---|---|
| SS:1024 | TIE | 1135.1 | 1084.9 | **+4.6 %** | replicate |
| CC:512 | TIE | 322.0 | 308.4 | **+4.4 %** | replicate |
| SS:1365 | TIE | 1110.0 | 1069.8 | **+3.8 %** | replicate |
| SS:1000 | TIE | 1107.4 | 1067.7 | **+3.7 %** | replicate |
| HH:2048 | TIE | 2670.9 | 2575.2 | **+3.7 %** | replicate |
| SS:4096 | TIE | 1187.2 | 1148.0 | **+3.4 %** | replicate |
| HH:4096 | TIE | 2749.3 | 2662.0 | **+3.3 %** | replicate |
| HS_HPA:2048 | TIE | 1388.9 | 1344.2 | **+3.3 %** | replicate |
| DD:2048 | TIE | 98.8 | 96.6 | +2.3 % | real gain |
| DD:1365 | TIE | 89.1 | 87.2 | +2.2 % | real gain |
| DD:768 | TIE | 93.0 | 91.6 | +1.5 % | real gain |
| HH:1024 | TIE | 2581.9 | 2548.5 | +1.3 % | real gain |
| DD:1024 | TIE | 92.9 | 91.7 | +1.2 % | real gain |
| SS:2048 | TIE | 1164.0 | 1151.3 | +1.1 % | real gain |
| SS:768 | TIE | 1108.2 | 1095.9 | +1.1 % | real gain |
| HH_HPA:1024 | TIE | 1447.0 | 1445.5 | +0.1 % | real gain |
| HS_HPA:1024 | TIE | 1429.7 | 1428.7 | +0.1 % | real gain |
| HH_HPA:2048 | TIE | 1380.7 | 1381.1 | **−0.0 %** | real gain |

This table is the most important artefact in the rewrite, because it splits the
problem in two. **Eight cells sit at +3.3…+4.6 %**, i.e. *already beating the
floor* by a margin the ±5 % acceptance band cannot resolve — and a single-knob
toggle on their winner geometry moves ±2–3 %, which is smaller than the ±16.45 %
reproducibility band. For those eight the honest lever is **replication, not
geometry**: more seeds on the same config, which shrinks the band rather than
the delta. The remaining ten are at +0.1…+2.3 % (HH_HPA:2048 is a dead heat at
−0.0 %), and those need a **real gain**, which is what §R37 is for. Nothing in
the port is *losing* to the floor — there are zero LOSS verdicts.

---

## R37 — the deck for the tied cells: the never-co-varied forwarded axes

`_TIE_ADAPT` (§ below, still in the deck) has already spent the obvious knobs on
these exact winner geometries, and §R35 shows those probes were real and lost by
1.9–3.2 %. Re-running them is dead budget. What remains are the forwarded knobs
that **no phase in the 1137-row registry has ever carried on a winner geometry**.
Four axes, twelve measured-winner bases, all in `oto/harness/candidate_rows.py`:

| axis | why it is the one to spend on |
|---|---|
| `UseSgprForGRO: 1` | **0 of 1137** phases ever set it |
| `PrefetchLocalRead: 0` | **0 of 1137** phases ever set it; LDS read-prefetch relief on the DepthU-16 tiles |
| `LdsPadA: 4, LdsPadB: 4` | only ever carried by the broken §R35 generation; pad both LDS rows to 8 B |
| `InnerUnroll: 2 + UseSgprForGRO: 1` | the 2-knob combination, since every single knob here loses |

**`NumLoadsCoalescedA/B` is closed, and the closure is a proof.** It looked like
the most promising virgin axis — it was carried only as the constant `NLCA=1` in
CC/DD/HH_HPA and never co-varied with any tile — but `gates/loads.py::_nlca_stage`
implements Tensile's joint rule (`SolutionStructs:2058`): NLCA must divide
`numLoads`, divide `totalVectorsCoalesced`, and leave `totalElementsPerp`
divisible by `numLoads // NLCA`. On the winner tiles GLVW saturates the 16-byte
cap, so `numLoads = 1` and NLCA>1 fails `NLCA > NumLoads` outright — on exactly
the geometries a 7-CU part would want re-tuned. The deck asked for it (25 rows
were gate-refused by
`test_candidate_generator.py::test_plan_batch_is_gate_clean`) and the gate said
no, which is the gate working. The axis reopens only if GLVW is ever lowered.

Bases are the per-cell measured winners, so each row lands on the geometry that
actually ties:

| family | pattern | tile | tt | vw | du | cells |
|---|---|---|---|---|---|---|
| SS | Ailk_Bjlk | 128x128x8 | 8x8 | 4 | 8 | 768 / 1000 / 1024 / 1365 |
| SS | Ailk_Bjlk | 128x128x16 | 8x8 | 4 | 16 | 2048 / 4096 |
| CC | Ailk_Bjlk | 64x64x8 | 4x4 | 2 | 8 | 512 / 1024 / 2048 |
| DD | Ailk_Bjlk | 64x64x8 | 4x4 | 2 | 8 | 768 |
| DD | Alik_Bjlk | 64x32x8 | 4x2 | 1 | 8 | 1024 |
| DD | Ailk_Bjlk | 32x32x16 | 2x2 | 1 | 16 | 1365 |
| DD | Alik_Bljk | 64x64x8 | 4x4 | 2 | 8 | 2048 |
| HH | Ailk_Bjlk | 128x128x16 | 8x8 | 8 | 16 | 1024 / 2048 / 4096 |
| HH_HPA | Ailk_Bjlk | 64x128x16 | 4x8 | 4 | 16 | 1024 |
| HH_HPA | Ailk_Bjlk | 128x64x8 | 8x4 | 2 | 8 | 2048 |
| HS_HPA | Ailk_Bjlk | 128x64x16 | 8x4 | 4 | 16 | 1024 |
| HS_HPA | Alik_Bjlk | 64x128x16 | 4x8 | 4 | 16 | 2048 |

48 rows offered, 46 novel after fp-dedupe (the remainder are configs the pool
already measured), 0 element-multiple drops, 0 strips, 0 refusals. Cost: well
under 2 h of a 10 h night, because every row arms its family's shape list and a
family has ≤ 8 target sizes. `GlobalLoadVectorWidth` is deliberately left
implicit, as in `_TIE_ADAPT`: Tensile defaults it to `VectorWidth`, which is what
every measured winner recorded.

**What is still unreachable, and what it would cost** (unchanged from §R20): the
`NOT_FORWARDED_KNOBS` surface — `1LDSBuffer`, `TransposeLDS`, `UnrollMajorLDS*`,
`WaveSeparateGlobalRead*`, `ThreadSeparateGlobalRead*`, `DirectToVgpr*`,
`LdsBlockSizePerPad*`, `DepthULdsDivisor`, `PersistentKernel`. Each needs a
launch-boundary change before it can be tested at all. On a 7-CU part
`1LDSBuffer` and `DepthULdsDivisor` are the two that plausibly matter, because
both buy LDS back on the deep tiles; that is the next structural job, not a deck
row.

---

## R38 — what this deck cannot fix, and how to read the next A/B

**It cannot resolve a tie that is inside the noise.** Eight of the eighteen ties
are +3.3…+4.6 % over the floor while the corpus's own reproducibility band is
±16.45 %. No candidate can be *shown* to convert those; the correct next step is
to replicate the current winner on those cells until the band at that cell is
below its delta, then re-grade. A run that adds geometry to them will report
movement that means nothing.

**The tie band is a policy knob, not a measurement.** The verdict uses ±5.0 %
(`compute_native_vs_spoof_delta`'s default) while the measured band is 16.45 %.
Any claim that the port does or does not "beat the floor all around" has to say
which of the two it means. With `tie_band_pct = 5.0`, the honest current
statement is: **20 WIN, 18 TIE, 0 LOSS**, and the eight replicable ties are
probably wins already.

**The mutation arm fixed in §R34 changes the *economy* of the next run, not its
verdict.** Candidates will now flow to the tied cells for the first time. Expect
most to land at 0.83–0.98 like every other single-knob probe on these geometries;
the value is that it can no longer spend a night on SS:256.

---

## R39 — the overnight run: preflight and post-run

CPU-only, safe under GNOME (the legality proof is `--dry-run`):

```bash
python3 -m oto.harness.candidate_generator --dry-run   # 0 drops, 0 strips, 0 refusals
python3 -m pytest -q tests/test_phase1_readonly_gpu.py tests/test_mutation_arm.py \
    tests/test_ab_audit.py tests/test_function_length.py tests/test_pyflakes.py
```

TTY only, never from a GNOME/Wayland session (§R34 cause 1):

```bash
# 1. confirm the GPU is actually there, and say so in the transcript
rocm-smi --showtemp --showpower
# 2. the run
python3 -m oto tune --budget <N>
# 3. FIRST THING after it returns -- the guard files the run failed if the GPU left
sqlite3 gfx90c_results/registry.db \
  "SELECT run_id,status,metadata FROM runs ORDER BY rowid DESC LIMIT 3;"
ls gfx90c_runs/<new_run>/core.* 2>/dev/null | wc -l     # must be 0, was 413
# 4. only then read the A/B
python3 -m oto.metrics.ab_audit
```

If step 3 shows `status=failed` with an `abort_reason`, stop: the night bought
nothing and the config must not be re-used. If it shows `completed` with 0 cores,
the §R36 table is the scoreboard, split into its replicate and real-gain halves.

---

## R24 — the latest A/B, and the gate is now closed

**Scoreboard.** `gfx90c_results/acceptance_report.json` (2026-10-18T09:53):
`run_20261018_004835` vs the locked floor `gfx900_ref_locked_52149f315d` →
**20 WIN / 18 TIE / 0 LOSS**, 0 RED / 12 ORANGE, 9 h 03 m. The report is
*provisional*: the gfx900 reference chain did not finish and the user declined a
re-measurement, so the verdicts are indicative. `CC:256` upgraded TIE → **WIN
(+7.8 %)** since `run_20261017_092909` — that is the CC steal (R8) landing.

**The gate is closed.** `python3 -m oto.harness.gate_calibration --population ours`:

| revision | phases | built | gate-refused | agreed | MISS | FALSE REJECTION |
|---|---|---|---|---|---|---|
| rewrite 5 | 3349 | 3217 | 79 | 79 | **53** | 0 |
| **now** | 3349 | 3217 | 132 | **132** | **0** | **0** |

Every native phase Tensile built, the gate allows; every phase the gate refuses,
Tensile did not build. **0 misses, 0 false rejections** on our population
(3349 phases / 3217 built). The reference population (4568 phases / 3870 built)
keeps its pre-existing **43 false rejections** — *all* of them the **LDS
tile-footprint proxy** (`LDS_BUDGET = 16384`, `(MT0+MT1)*DepthU <= 2048`) firing
on large-DepthU gfx900 kernels (SS 29, DD 12, HH 1, HS_HPA 1; DepthU 16/32/64),
a reference-only story unrelated to the rules below. **Each of the three new
rules adds 0 false rejections to both populations.** They are:

**(1) The workgroup register file** (`occupancy_feasible`). Tensile's
`KernelWriterAssembly.functionSuffix` sets `overflowedResources = 4` when

```
vgprPerThreadPerOccupancy = 65536 // NumThreads
numWorkGroupsPerCU        = vgprPerThreadPerOccupancy // max(vgpr, agpr)
if numWorkGroupsPerCU < 1:  overflowedResources = 4     # "resulted in error 4"
```

The accumulator set is always allocated, so it is a *sound lower bound* on
`vgprPool.size()`; with `NumThreads = (MT0/TT0)*(MT1/TT1)*LSU` the accumulator
count per workgroup is exactly `weight * MT0 * MT1 * LocalSplitU`, so
**ThreadTile cancels**. The rule:

```
weight * MT0 * MT1 * LocalSplitU >= 65536   ->   refuse
```

with `>=` (not `>`): an accumulator set that exactly fills the file leaves no
VGPR for operands or addresses, so Tensile must overflow. Catches
`C 128x128x8/tt4x4` (12 phases), `Z 128x128x8/tt4x4` (6), `Z 128x64x8/tt4x4`
(14), `Z 64x128x8/4x8` (8) — **40 empty phases, 0 built refused**. It is also the
constraint the *retired* area model (`R*MTarea <= 65536/2`) was reaching for,
with the wrong threshold (32768, not 65536) and the wrong boundary (`>`, not
`>=`); §R27 is what that buys.

**(2) The LSU LDS reduction** (`occupancy_feasible`). `LocalSplitU > 1` makes
Tensile allocate a reduction buffer of `multiplier * LSU * MT0 * MT1` elements
(SolutionStructs:4108), `multiplier = ComputeBytes // LoadBytes`, so in bytes it
is exactly `LSU * MT0 * MT1 * ComputeDataType.numBytes()`; :4334 refuses past
`MaxLDS = 65536`:

```
LocalSplitU > 1 and LSU * MT0 * MT1 * ComputeBytes > 65536   ->   refuse
```

This is the `Kernel Uses 131072 > 65536 bytes of LDS` class (13 phases, 0 built
refused). R23 deferred it pending a "destination element size table"; it is the
*compute* dtype that matters (`ComputeDataType.numBytes()`, table at
`vgpr_model.COMPUTE_BYTES_PER_ELEMENT`, HPA → f32 4 B), not the destination's.

**(3) `AggressivePerfMode = 2` is non-generative** (`candidate.py`, the
*generator* seam). Tensile declares the domain `[0,1,2]` (Common.py:1446) but
`Components/Priority.py` dispatches the priority component by exact match on the
boolean fingerprints `{False}` / `{True}`, so 2 matches neither, `Priority.find`
returns `None`, and `MAC_F32C.__call__` raises `TypeError: 'NoneType' object is
not callable` before a kernel exists. Measured: **0 of 28 built**, across all
seven families. Refused at the *generator* seam, not the writer: the writer's
contract test probes APM=2 to prove the *forwarding*, so the writer keeps
forwarding any value and the *drawer* refuses the dead one — the same split as
`AssertSizeMultiple: [1]`.

R23's second deferred item — the **NumThreads-aware VGPR budget** — is rule (1),
and it resolved *differently* than R23 expected. R23 wanted a config-exact VGPR
table because the *measured-total* form cost one false rejection on a measured
kernel. It does not need one: the accumulator form carries no measured table,
which is what removes the overreach.

## R25 — the tie taxonomy on run_20261018_004835 (20 WIN / 18 TIE / 0 LOSS)

`cell_resolver` is regenerated against the latest run. The 18 ties, with the
mechanical native-vs-floor gap `cfg_gap` and the measured margin (`Δ %` = native
over floor):

| cell | `cfg_gap` | Δ % | native winner | floor winner |
|---|---|---|---|---|
| CC:512 | identical | +4.4 | `64x64x8 / 4x4 / VW2 / DU8` | same |
| DD:768 | identical | +1.5 | `64x64x8 / 4x4 / VW2 / DU8` | same |
| DD:1024 | **retile** | +1.2 | `64x32x8 / 4x2 / VW1 / DU8` | `64x64x8 / 4x4 / VW2 / DU8` |
| DD:1365 | **retile** | +2.2 | `32x32x8 / 2x2 / VW1 / DU16` | `64x64x8 / 4x4 / VW1 / DU8` |
| DD:2048 | near | +2.3 | `64x64x8 / 4x4 / **VW2** / DU8` | `64x64x8 / 4x4 / VW1 / DU8` |
| HH:1024 | identical | +1.3 | `128x128x16 / 8x8 / VW8 / DU16` | same |
| HH:2048 | identical | +3.7 | same + `PGR=0 NLCA=1 LdsPadA=0` | same |
| HH:4096 | identical | +3.3 | same + `PGR=0 NLCA=1 LdsPadA=0` | same |
| HH_HPA:1024 | no-floor | +0.1 | `64x128x16 / 4x8 / VW4 / DU16` | — |
| HH_HPA:2048 | no-floor | −0.0 | `64x128x16 / 4x8 / VW4 / DU16` | — |
| HS_HPA:1024 | no-floor | +0.1 | `128x64x16 / 8x4 / VW4 / DU16` | — |
| HS_HPA:2048 | no-floor | +3.3 | `64x128x16 / 4x8 / VW4 / DU16` | — |
| SS:768 | identical | +1.1 | `128x128x8 / 8x8 / VW4 / DU8` | same |
| SS:1000 | identical | +3.7 | same | same |
| SS:1024 | identical | +4.6 | same | same |
| SS:1365 | identical | +3.8 | same | same |
| SS:2048 | near | +1.1 | `128x128x**16** / 8x8 / VW4` | `128x128x**8** / 8x8 / VW4` |
| SS:4096 | near | +3.4 | `128x128x**16**` | `128x128x**8**` |

Readings:

* **(a) identical — 13 of 18.** The native winner *is* the floor's tile
  (`CC:512`, `DD:768`, `HH:1024/2048/4096`, `SS:768/1000/1024/1365`). This is the
  "unedited steal" reading, and it is correct: on `HH` the only difference is
  `PGR=0 NLCA=1 LdsPadA=0` — knobs that did not move the needle.
* **(b) near — 4.** The floor's tile with one `VectorWidth` or `DepthU` step
  (`DD:2048` VW 2-vs-1; `SS:2048/4096` DU 16-vs-8). The lever is a width/depth
  probe, not a tile probe.
* **(b′) retile — 2.** `DD:1024` and `DD:1365` tie on a *smaller, different* tile
  than the floor's. The lever is a **tile** probe.
* **(c) no-floor — 4.** `HH_HPA:1024/2048`, `HS_HPA:1024/2048`: the gfx900 chain
  ships no HPA kernel, so there is nothing to beat; native is at 123–129 % of the
  family ceiling. Not a deficit, not a target.

`DD:2048` native already sits at **100.2 % of the realistic DD ceiling** (floor
96.6 % of median) — DD's big shapes are closed by physics, not by a kernel gap.
The acceptance report uses the shipped tie band, `ab_band.TIE_BAND_PCT = 5 %`;
this run brackets it exactly — the largest tie is `SS:1024` at +4.6 %, the
smallest win `CC:256` at +7.8 %.

## R26 — the straggler class tracker

The "laundry list" is four classes, not one, and each has its own lever. The
magnitudes are the `Δ %` column above.

| class | cells | the lever | best-possible margin |
|---|---|---|---|
| **C1 — same-geometry ties** | `CC:512`, `DD:768`, `HH:1024/2048/4096`, `SS:768/1000/1024/1365` | non-tile knobs on the winner geometry | ≤ +4.6 % |
| **C2 — near ties (VW/DU)** | `DD:2048`, `SS:2048`, `SS:4096` | a `VectorWidth` / `DepthU` step | ≤ +3.4 % |
| **C3 — retiles** | `DD:1024`, `DD:1365` | a tile probe (native is on a *smaller* tile) | ≤ +2.2 % |
| **C4 — no-floor HPA** | `HH_HPA:1024/2048`, `HS_HPA:1024/2048` | none — nothing to beat | ~0 |

Per class, the four route kinds:

* **wide** — *closed for the complex families* (§R27): no CC tile with area >
  8192 and no ZZ tile with area > 4096 is legal. Still open for `SS`/`HH` (area
  up to 256×256), but those cells already sit at 99–112 % of ceiling with the
  floor's own 128×128 tile, so a wider tile is an LDS-bound bet with little
  headroom.
* **narrow** — open everywhere, and *proven* by C3: at `DD:1024/1365` a
  *smaller* tile ties, and `DD:192/256/512` **win** with `32x32` (+267 %/+20 %/
  +7 %). Narrow is the lever for the 7-CU occupancy cliff.
* **steal** — **no steal is in this run, and none is justified.** There are 0
  LOSS cells; the ties are byte-identical floor tiles (i.e. already stolen); and
  the one steal that had content — `CC:256` (R8) — has already landed as a WIN.
  Stealing a gfx900 config *adds nothing* where the gfx900 config is already what
  native ships, which is every tie. The steal route stays closed until a native
  LOSS appears, and then only for that cell.
* **novel** — R18's routes A–I applied to the winner geometry: the `PLAN_BATCH`
  rows. These are the only levers left for C1/C2.

`DD` is the **only family whose winner tile changes by shape** (`32x32` at
192–512, `64x64` at 768–2048, `64x32`/`32x32` retiles at 1024/1365). That is the
signature of a tile-sensitive family; the right lever is a tile probe, and the C3
cells are exactly where it has not been run.

The **CC:256 steal port record** — the "bit-by-bit gfx900 → gfx90c adaptation"
requirement — is §R8 above: only `MacroTile 64x64`, `WorkGroup 16x16x1` and
`GLVW 2/2` were taken verbatim (all three are self-consistent consequences of
MT/TT/VW, not vendor magic numbers), and `StaggerU`, `WGM`, `LdsPad`,
`AssertFree*ElementMultiple`, `PGR` and `LSU` were all re-swept because the source
part has 60 CUs and HBM2, not 7 CU and DDR4. It is the template for a future
steal, and the reason none is run now.

## R27 — the tile axes now have provable ceilings

Three CPU-only constraints bound every tile. All three are calibrated
zero-false-rejection on the corpus, so "illegal" here means Tensile will not
build it:

1. **Workgroup register file** (§R24 rule 1): `weight * MT0 * MT1 * LSU < 65536`.
   With the per-dtype accumulator weight `R` (`S/H` 1, `D` 2, `C` 4, `Z` 8) the
   ceiling is `MT0*MT1 < 65536 / R`: `SS/HH` 65536, `DD` 32768, `CC` 16384,
   `ZZ` 8192.
2. **LDS tile budget** (`occupancy_feasible`): `(MT0+MT1) * DepthU *
   bytes(LDS row) <= 16384`.
3. **Classic-load divisibility** (`validate_tensile_loads`): `MT0*DU` and `MT1*DU`
   must divide by `NumThreads * GLVW`.

**Consequence (brute force, pinned by
`test_no_legal_complex_tile_is_wider_than_the_measured_max`):** over every CC tile
with area > 8192 and every ZZ tile with area > 4096, at every thread tile that
survives the per-thread budget, **not one is legal**. So:

| family | widest legal MacroTile | widest ever *emitted* |
|---|---|---|
| CC | `128x64x8` (or `64x128x8`) | `128x64x8`, but at VW1 — never VW2 |
| ZZ | `64x64x8` / `128x32x8` / `32x128x8` | `128x32x8`, but at tt2x8 — never tt4x4 |

This **retires §8.2** ("Tiles that are legal but were never generated"): its four
"headroom" tiles — `ZZ 128x128x8`, `ZZ 128x64x8`, `CC 128x128x8`, `CC 128x96x8` —
are all **illegal**, and the claim that they were "legal" was wrong. The old gate
read the *per-thread* budget (`TT0*TT1*R <= 128`), which those tiles pass (128
exactly), and not the *workgroup* budget, which they fill (65536). The
`128x96x8/8x4` row additionally fails divisibility
(`totalElements 1024 % (NumThreads*glvw) 768 != 0`).

The legal-wide rows now in the deck are in §R30.

## R28 — the ledger trace: what was tried, per cell

Search breadth from the registry's own generation log (`phases`) — distinct
`(MacroTile, ThreadTile, VectorWidth, DepthU)` geometries per cell — plus the
proposal ledger's outcomes for the tie cells:

| family | generation attempts | distinct geoms / cell (big shapes) |
|---|---|---|
| SS | 409 | 64–88 |
| HS_HPA | 147 | 84–85 |
| HH_HPA | 175 | 81 |
| HH | 103 | 57 |
| CC | 59 | 13–16 |
| DD | 58 | 16 |
| **ZZ** | **50** | **5** |

| tie cell | proposals | functional | rejected | slow | pending |
|---|---|---|---|---|---|
| CC:512 | 1 | 1 | 0 | 0 | 0 |
| DD:768 | 3 | 0 | 1 | 2 | 0 |
| DD:1024 | 0 | 0 | 0 | 0 | 0 |
| DD:1365 | 1 | 0 | 0 | 1 | 0 |
| DD:2048 | 0 | 0 | 0 | 0 | 0 |
| HH:1024 | 14 | 13 | 1 | 0 | 0 |
| HH:2048 | 8 | 6 | 2 | 0 | 0 |
| HH:4096 | 12 | 9 | 3 | 0 | 0 |
| HH_HPA:1024 | 40 | 28 | 5 | 3 | 4 |
| HH_HPA:2048 | 34 | 32 | 0 | 0 | 2 |
| HS_HPA:1024 | 27 | 18 | 4 | 5 | 0 |
| HS_HPA:2048 | 29 | 20 | 3 | 3 | 3 |
| SS:768 | 18 | 6 | 6 | 6 | 0 |
| SS:1000 | 24 | 14 | 6 | 4 | 0 |
| SS:1024 | 21 | 10 | 9 | 1 | 1 |
| SS:1365 | 19 | 10 | 7 | 2 | 0 |
| SS:2048 | 15 | 9 | 6 | 0 | 0 |
| SS:4096 | 13 | 8 | 4 | 1 | 0 |

What this says:

* **ZZ is under-searched by an order of magnitude** — 5 distinct geometries per
  cell against SS's 64–88 — and it is the family furthest from its ceiling
  (17–25 %). The `pending` count for ZZ is 0, so the draw queue is not the
  blocker; the **deck** is (5 rows is not a search). §R30 widens it.
* **The complex families carry the most `legal_slow`** (`DD:768` 2/3, `SS:768`
  6/18, `SS:1365` 2/19): the draws built, ran, and were slow — geometry
  saturated, not the gate.
* **The retile cells (`DD:1024/2048`) have zero proposals.** Their tie was found
  by the deck, not by the mutator; a tile probe is the untried lever (C3).
* **`HH_HPA`/`HS_HPA` have the deepest queues** (40/34/27/29 proposals) and the
  smallest margins — budget spent where there is nothing to beat.
* `phases` generation attempts per family sum to 409+58+50+59+103+175+147+19 =
  1020; the 38 pending proposals are unresolved draws the overnight run should
  now resolve (all gate-legal after §R24).

## R29 — which kernel types perform best (the pattern across all runs)

From the winners on this run (all 38 cells) and the corpus census:

* **Small cubes want a SMALL tile and many workgroups.** `SS:256` is won by
  `96x96x16 / 6x6 / VW2 / WGM8` at **+231 %** over the floor's `32x64` big tile;
  `HH:256` by `32x64x16 / 4x4 / VW4` at **+277 %**; `DD:192` by `32x32x8 / 2x2`
  at **+267 %**. The floor ships a rank-1 tile for a cube that cannot fill it.
* **Big real cubes (SS/HH ≥ 512) want the vendor rank-1 tile** —
  `128x128x8|16 / 8x8 / VW4|8`, `WGM4`. It wins at `HH:512` (+22 %) and `SS:512`
  (+10 %), and *ties* above; the only in-band gains left are `DU 16` at
  `SS:2048/4096`.
* **`DD` tracks the cube size** (`32x32` → `64x64` → retiles) and is at 94–100 %
  of ceiling once the cube is ≥ 768.
* **`CC` and `ZZ` are issue-bound, not area-bound.** Complex costs four real FMAs
  per complex MAC with no MFMA, and `ZZ` is FP64 at 1/16 rate; both run at
  17–31 % of ceiling and cannot be fixed by area (which is capped anyway, §R27).
  Their lever is **occupancy** — the smallest tiles already win (`CC 64x64/4x4`,
  `ZZ 32x32/2x2`).

The highest-yield band in the whole corpus is therefore the **small-shape band**
(`SS/HH/DD` at 192–512), where the floor is worst and the margins are +20 % to
+277 %. The big-shape band is a knob surface around a tile that is already the
vendor's.

## R30 — the deck changes for this run

* **`phases.yaml`: 4 dead rows replaced.** The `ZZ trialD3` rows
  (`mt128x128x8_tt4x4`, `mt128x64x8_tt4x4` at 512³ and 1024³) fail the workgroup
  register-file rule (`8·128·128 = 131072`, `8·128·64 = 65536`), so they can
  never generate. Replaced with the **widest legal ZZ tiles**, `128x32x8/4x4` and
  `32x128x8/4x4` (fingerprints recomputed). `oto check candidates --quiet` goes
  4 illegal → **0 illegal**.
* **`family_decks.py`:** the CC "widest legal MacroTile" rows `128x128x8/8x4`,
  `128x128x8/4x8`, `128x96x8/8x4` are replaced with `128x64x8/8x4|4x4` and
  `64x128x8/4x8` (VW2) — the *provable* widest legal CC tile, never emitted at
  VW2. The ZZ rows `128x128x8/4x4`, `128x64x8/4x4` become `128x32x8/4x4` and
  `32x128x8/4x4`. The narrow SS/HH/ZZ rows are made explicit (the VW4/VW8 rows
  silently clamped to VW2; the ZZ VW2 row is a duplicate of the bare one *and*
  unbuildable, so it is removed).
* **The same dead tiles had two further homes, both repaired.**
  `candidate_rows.py` `LADDER` carried `CC 128x128x8/4x4` (the register-file
  tile), `ZZ 128x64x8/4x2` and `ZZ 64x128x8/2x4` (GLVW does not divide the
  packed access) and `SS/HH 32x32x16/2x2` at VW4/VW8; they are repointed to the
  widest legal tiles (`CC 128x64x8/8x4`, `ZZ 128x32x8/4x4`, `ZZ 32x128x8/4x4`,
  VW2). `PLAN_BATCH`'s SS `128x128x16/8x8/VW4` `LocalSplitU=2` tie-adapt row
  needs a 131072 B reduction buffer against the 65536 ceiling, so the LSU probe
  moves to `128x64x16/8x4/VW2` — the widest legal LSU-2 SS tile. **0 rows in
  `FAMILY_DECKS`, `LADDER` or `PLAN_BATCH` are gate-refused**
  (`TestEveryDeckRowIsGenerative`).
* **`DECISION_TRIAL_TILES` D3** becomes the widest legal ZZ pair (D1/D2
  unchanged).
* **New model pins (tests):** `TestWorkgroupRegisterFile`,
  `TestLdsReductionBuffer` (`tests/test_occupancy_model_lds.py`);
  `test_generator_refuses_the_dead_perf_mode` and
  `test_no_legal_complex_tile_is_wider_than_the_measured_max`
  (`tests/test_knob_sweep.py`); `TestEveryDeckRowIsGenerative`
  (`tests/test_candidate_generator.py`), which pins that no deck, ladder or
  batch row is gate-refused under any contraction pattern.
* **Preflight is the authority, not a number written here.** `python3
  `oto check candidates --quiet` → `0 illegal`;
  `python3 -m oto.harness.candidate_generator --dry-run` → `0 refused`;
  `python3 -m oto preflight` → parity (38/38 cells).

## R31 — what to stop doing

* **Chasing a wider MacroTile for C and Z** — provably closed (§R27), not a
  budget question.
* **ThreadTile width ladders for C and Z** — the accumulator cap makes every
  wider tile illegal.
* **Stealing a gfx900 config for a TIE** — the tie *is* the stolen config; the
  route has nothing to add until a LOSS appears (§R26).
* **`MatrixInstruction` / `DirectToLds` / `WavefrontSize` / `-mllvm -amdgpu-*`** —
  rejected or harmful on gfx90c.
* **Hunting HPA ties** — no floor exists and native is at 123–129 % of ceiling.
* **Re-pinning `KNOB_SWEEP_BASES`** — the sweep tests index `[0]` and the D4
  widen needs CC at VW1; winner-geometry work goes in `PLAN_BATCH`.
* **`AggressivePerfMode = 2`** — now refused at the generator seam (§R24).
* **Reading a single `best`-seed sample as a verdict** — judge within-run, ≥3
  seeds, on the median, inside the report's tie band.

## R32 — the overnight command

```bash
# CPU-only, safe under GNOME (no GPU stress):
python3 -m oto check candidates --quiet
python3 -m oto.harness.candidate_generator --dry-run
python3 -m oto.harness.gate_calibration --population ours --fail-on-false-reject
python3 -m oto.harness.rule_calibration --fail-on-false-reject
python3 -m oto.harness.failure_triage
python3 -m oto preflight
python3 -m pytest -q tests/test_occupancy_model_lds.py tests/test_occupancy_model_vgpr.py tests/test_knob_sweep.py

# TTY only — the real run:
python3 -m oto tune --budget 10 --yes
```

The gate calibration must print `0 MISS` and `0 FALSE REJECTION`, and the rule
probe `0 FALSE REJECTION`; if either does not, a new phase is a gate bug, not a
kernel result.

## R33 — the literature's experiment order, mapped onto the routes above

The 2026-10-19 GCN5 GEMM literature review (mechanisms in
`docs/research/kernel_tuning.md` §3.4/§4/§5/§8.7, `docs/research/complex_gemm_brief.md`
§5–§11, `docs/search_philosophy.md` §S) proposes an eight-step order. It is **not a
new plan** — every step is already a route or a probe; this maps it and marks the
steps this port cannot reach:

1. **SS:256 WGM4/WGM8 + row/column, randomised order, repeats** — the ±4× anomaly,
   and the current straggler. Route: §R26 SS class + `candidate_rows.NARROW_NEIGHBOURS`
   WGM set; mechanism `docs/research/kernel_tuning.md` §3.4. **Reachable.**
2. **CPU predictor ranks tile candidates** (grid/tail/edge/residency) — a ranking
   tool, not an acceptance test (`docs/research/kernel_tuning.md` §3.4). **Reachable (CPU-only).**
3. **ZZ/FP64: keep 32×32, sweep thread tile and K depth independently** —
   `docs/research/complex_gemm_brief.md` §11. Route: §R30 widest-legal rows + `LADDER`
   ZZ rungs. **Reachable.**
4. **CC: 3-product vs 4-product, with error tests and all temporaries/launch costs** —
   high-value but *not* a config: no 3M path is forwarded, and the numerical caveat
   (`docs/research/complex_gemm_brief.md` §5) makes it a design change, not a draw. **Not reachable as a candidate.**
5. **LDS: model per-lane `ds_read_b64/b128` addresses/phases/banks, then pad/XOR** —
   `docs/research/kernel_tuning.md` §2/§8.1. Route: §R26/§R30 pad rows; XOR
   (`LdsBlockSizePerPad`) stays unforwarded. **Partly reachable.**
6. **Pipeline/cache: one knob at a time** (prefetch, buffers, wave-separated loads,
   NT), verifying each is forwarded — `docs/research/kernel_tuning.md` §4; forwarding
   surface is §R16. **Reachable for forwarded knobs only.**
7. **Underfilled shapes: non-atomic split-K / Stream-K, including workspace + fixup** —
   `docs/research/kernel_tuning.md` §8.7; **not forwarded** (no `GlobalSplitUAlgorithm`/
   workspace, StreamK MFMA-gated) → background. **Not reachable.**
8. **Tuner: legality/resource prune → mechanism-diverse shortlist → (surrogate
   selection) → replicate → statistical tie policy** — the prune + mechanism-diverse
   shortlist is Stage 0–2 (`docs/search_philosophy.md` §S); **surrogate selection is
   declined by policy**. **Partly reachable.**

The one literature finding that lands directly on the current straggler:
**14–25 configs/cell is a *small* shortlist** (`docs/search_philosophy.md` §S item 7),
and the near-duplicate failure mode is exactly the ZZ cell's 5 distinct geometries
(§R28). The steps above therefore re-rank the existing routes by the anomaly's
expected value; they add no route that §R26–§R30 did not already carry.

A second, 2026-10-19 literature pass answered the fourteen residual questions that
this route mapping left open. Every verdict is *closest-evidence-found, none
gfx90c-specific*, and each is now stated inline in its owner — Origami and the
grid predictor in `docs/research/kernel_tuning.md` §3.4, the LLVM VGPR-allocation rule in
§9.3, the MI250X non-temporal and StaggerU scoping in §4, the Stream-K knob names in
§8.7; the oneMKL/Higham 3M error bound in `docs/research/complex_gemm_brief.md` §5; and
the AMD warmup/sample methodology in `docs/knowledge_base.md` §8.3. **It changes no
route** — it converts four open [CHECK]s into cited "closest evidence, not
gfx90c-specific" statements, so the search is not repeated.

---

## Superseded: rewrite 5 (2026-10-17), kept below for history

Supersedes rewrite 4 (R10–R15, kept below for history). **What is new here** is
the straggler trace on the latest A/B, a per-cell **tie taxonomy** that separates
genuine work from measurement noise, the **launch-boundary forwarding surface**
that decides which of R15's "virgin axes" are real, the **adaptation routes**
(R18) that break the big-shape ties *without* stealing, and the deck rows that
carry them (R19).

**Owns:** the candidate deck, the routes, the search rules. Does not own:
ceilings and verdict bars (`docs/gfx90c_theoretical_limits.md` §5), measured evidence
(`docs/results.md`), hardware facts (`docs/gfx90c_theoretical_limits.md` §1–§3),
or the per-cell winners (`gfx90c_results/analysis/cells_resolved.full.txt`).

---

## R16 — the forwarding surface: which knobs actually reach Tensile

One fact, one home: `oto/tensile/config_writer.py` is the **only** place a knob
becomes Tensile YAML, and it now *declares* that surface as data —
`FORWARDED_KNOBS` (what reaches Tensile) and `NOT_FORWARDED_KNOBS` (valid
parameters it does not reach), pinned to the fork helpers by
`tests/test_writer_forwards_sweep_knobs.py`. The helpers behind them are
`_fork_thread_macro_workgroup`, `_fork_split_knobs`, `_fork_depth_u`,
`_fork_width_knobs`, `_fork_coalesced_loads`, `_fork_prefetch` and
`_fork_sweep_int_knobs`, plus the `FORWARDED_GROUP_C_KNOBS` tuple. A key outside
`FORWARDED_KNOBS` is silently dropped at the launch boundary and the candidate
then benchmarks at the Tensile default — a no-op that reads in the ledger as a
measured negative. This is the failure mode the module docstring calls out ("the
one place that has to answer for every silent-drop bug").

| group | knobs forwarded |
|---|---|
| tile | `MacroTile`, `ThreadTile`, `WorkGroup` (with `LocalSplitU` as element [2]), `DepthU` |
| width | `VectorWidth`, `GlobalLoadVectorWidthA/B` |
| split | `GlobalSplitU`, `WorkGroupMapping` |
| loads | `NumLoadsCoalescedA/B` (and the `NLCA` alias) |
| prefetch | `PrefetchGlobalRead` (int 0/1/2), `PrefetchLocalRead` (bool) |
| sweep ints | `UseSgprForGRO`, `InnerUnroll`, `MaxOccupancy`, `AggressivePerfMode`, `FractionalLoad`, `NonTemporalA/B`, `AssertFree1ElementMultiple` |
| Group C | `LdsPadA/B`, `AssertFree0ElementMultiple`, `StaggerU`/`StaggerUMapping`/`StaggerUStride`, `StoreCInUnroll` |

`GlobalReduceVectorWidth` is a trap in the *other* direction: `_fork_width_knobs`
emits it (reference metadata spells it `grvw`) and `_drop_unsupported` then strips
it, because it is not a Tensile parameter at all. It is in neither tuple.

**Not forwarded (`NOT_FORWARDED_KNOBS`) — dead letters until the launch boundary
is extended (R20):** `WaveSeparateGlobalReadA/B`, `ThreadSeparateGlobalReadA/B`,
`1LDSBuffer`, `TransposeLDS`, `UnrollMajorLDSA/B`, `GlobalReadPerMfma`,
`LocalWritePerMfma`, `DepthULdsDivisor`, `PersistentKernel`,
`LdsBlockSizePerPadA/B`, `DirectToVgprA/B`. The harness strips these at emit time
and *reports* the strip (`candidate_rows._NOT_FORWARDED_YET` is that tuple), so a
candidate carrying one is now a reported no-op rather than a silent one.

This corrects R15: its items 8 (`WaveSeparateGlobalRead`) and 9 (`1LDSBuffer`)
were listed as deck additions, but the writer does not forward either, so a
candidate carrying them would have benchmarked at the default, and the overnight
budget would have been spent on a placebo. Of R15's route-B table, only the
rows whose knob appears in the table above are executable.

## R17 — the tie taxonomy (latest A/B: 19 WIN / 19 TIE / 0 LOSS, 0 RED / 12 ORANGE)

The 19 ties are not one problem. `cell_resolver` reports the mechanical gap
between the native winner's config and the floor's as `cfg_gap` and the classes
it produces are the taxonomy below — so this split is now checkable, not read:

**(a) Same-geometry ties (`cfg_gap=identical`)** — native's winning tile is the
floor's, and at most a couple of non-tile knobs differ (and did not move the
needle): the tile is
byte-for-byte identical at `CC:256`, `CC:512`, `DD:768`, `HH:1024`, `SS:1000`,
`SS:1024`, `SS:1365`, and identical-but-for-`NLCA`/`PGR`/pad at `HH:2048`,
`HH:4096`, `SS:768`. This is the user's reading, confirmed against
`cells_resolved.full.txt`: the two complex/medium cells reproduce
`MT=[64,64] TT=[4,4] VW=2 DU=8` and the four wide cells reproduce
`MT=[128,128] TT=[8,8] VW∈{4,8} DU∈{8,16}`.

**(b) Near ties (`cfg_gap=near`)** — native's winner keeps the floor's tile and
differs only in a `VectorWidth` or `DepthU` step: `DD:2048` (VW 2 vs 1),
`SS:2048` and `SS:4096` (DU 16 vs 8).

**(b′) Re-tiles (`cfg_gap=retile`)** — native ties on a *different* tile than the
floor's, and a smaller one: `DD:1024` (`MT=[64,32] TT=[4,2] VW=1` against the
floor's `MT=[64,64] TT=[4,4] VW=2`) and `DD:1365` (`MT=[32,32] TT=[2,2] DU=16`
against `MT=[64,64] TT=[4,4] DU=8`). These were folded into (b) on the first
reading and that was wrong — the deficit they carry is a tile choice, not a
width step, so the lever is a *tile* probe, not a VW/DU probe.

**(c) HPA ties (`cfg_gap=no-floor`)** — `HH_HPA:1024/2048`, `HS_HPA:1024/2048`.
These carry **no floor at all** (the gfx900 chain ships no HPA kernels), so a
"tie" here is a comparison against the undone reference arm; native already sits
at 123–129 % of the family ceiling. Not a kernel deficit — do not over-invest.

**Why same-geometry ties exist.** gfx900 (56–60 CU, 2 MiB L2, HBM2) and gfx90c
(7 CU, 1 MiB L2, DDR4 UMA) differ *only* in CU count, L2 size and bandwidth.
The data-path shape — wave64, 64 KiB LDS/CU, the same VGPR file, no MFMA — is
identical, so the vendor's rank-1 tiles transfer unchanged. At k ≥ 768 the L2
difference stops biting (a 128×128 tile holds 16 KiB of LDS, not L2), which is
exactly where the ties live.

**Why nothing has beaten them.** The knob-sweep deck perturbs
`KNOB_SWEEP_BASES`, and both relevant bases are the *wrong* tile: CC's base is
`VectorWidth 1` while CC's winner is VW2 (the D4 paired-widen row pinned it to
VW1 deliberately), and HH's base is VW4 while HH's winner is VW8. So the twelve
sweep rows never once perturbed the geometry that ties. R19 fixes that where the
tile is explicit (PLAN_BATCH), not by re-pinning the sweep bases — the sweep
tests index `KNOB_SWEEP_BASES[family][0]` and the D4 row depends on CC staying
VW1.

**What the ties are not.** No tie is a RED cell and none is a LOSS. The twelve
ORANGE cells (< 50 % of the family ceiling) are yardstick artefacts: complex
pays four real FMAs per complex-MAC with no MFMA opcode, and 128³/256³ cubes
cannot fill 7 CUs — native is 1.1–3.8× the floor on all twelve. The one cell that
was a genuine shortcoming (CC:256, the only ever-LOSS) now reads TIE at +4.2 %.

## R18 — the executable adaptation routes (all knobs forwarded per R16)

These are the levers R17's analysis leaves standing. Each is a *single-knob or
small compound change on the measured winner geometry* — except for the two
re-tile cells (R17(b′): `DD:1024`/`DD:1365`), whose lever is a **tile** probe,
not a width probe.

| # | route | knobs | cells | mechanism |
|---|---|---|---|---|
| A | **L2 pollution** | `NonTemporalA/B ∈ {1}` | SS/HH big, DD 768+ | stream past the 1 MiB shared L2 instead of thrashing it; the floor ships 0 everywhere |
| B | **Residency clamp** | `MaxOccupancy ∈ {8,12}` | all ties | pads per-workgroup LDS to `DeviceLDS // N`; 7 CUs makes wave count scarcer than on the 60-CU parts AMD tuned for |
| C | **LDS-cap branch** | `AggressivePerfMode = 2` | all ties | described as a 2-waves/SIMD LDS cap; the corpus median is already 2 waves/SIMD, so it is either free or a real clamp |
| D | **Issue-slot reduction** | `InnerUnroll = 2`, `NumLoadsCoalescedA/B`, `UseSgprForGRO` | CC, ZZ, and the wide tiles | complex and ZZ are issue-bound; longer unroll and coalesced loads cut loop-control issues, `UseSgprForGRO` moves GRO offsets from VGPR to SGPR |
| E | **Wave-fill** | `LocalSplitU = 2`; `GlobalSplitU ∈ {2,4}` | LSU: all; GSU: **SS/DD only** | the 7-CU cliff. GSU is gate-refused for every half and complex family, so LSU (which splits the M extent inside one workgroup, no reduction kernel) is the legal equivalent there |
| F | **Bank conflicts** | `LdsPadA/B ∈ {1,2,4}` | CC, ZZ, DD, SS, HH, HPA | GCN LDS is 32 banks × 4 B, `bank = (addr/4) mod 32`, wave64 serviced in 8 phases of 8 lanes. **DD, CC and ZZ are never padded in the floor** — a blind spot shared by Tensile's own `Perf/*.yaml` — so this is the highest-yield untested axis for the complex families |
| G | **Swizzle** | `StaggerU ∈ {0,8,16}` + `StaggerUMapping ∈ {0,1,2}` + `StaggerUStride ∈ {0,128}` | all ties | `StaggerU = 32` was a 56-CU raster choice, pinned corpus-wide; `StaggerUStride = 256` silently rounds to `DepthU × bpe`, so the live stride values are 0/64/128 |
| H | **Prefetch depth** | `PrefetchGlobalRead ∈ {0,2}`, `PrefetchLocalRead ∈ {0}` | CC, ZZ, SS, HH | the floor never emits PGR 2; PGR 0 / PLR 0 halve register and LDS double-buffer pressure on the VGPR-bound complex tiles |
| I | **Negative WGM family** | `WorkGroupMapping ∈ {-1,-4}`, also `{1,2,3,8}` | all ties | WGM 8 asks for eight J-column workgroups before wrapping on a 7-CU part; the negative (I/J-swap) family has never been generated at all |

`MatrixInstruction`, `DirectToLds*`, `WavefrontSize` and the `-mllvm -amdgpu-*`
flags remain out of scope: on gfx90c they are `SolutionStructs`-rejected outright
or actively harmful (`DirectToLds` blocks `NLCA > 1`, forces `GLVW = 1` on 8/16-B
dtypes, and forces `1LDSBuffer`).

## R19 — the deck changes for this overnight run

* **PLAN_BATCH: +37 tie-adapt rows (36 net-new after fingerprint dedup).** R18 A–I applied to the *measured winner
  geometry* of each tie cell — SS `128x128x8/8x8/VW4/DU8` and
  `128x128x16/8x8/VW4/DU16`; HH `128x128x16/8x8/VW8/DU16`; DD `64x64x8/4x4/VW2/DU8`
  (the DD:768/2048 winner — DD:1024/1365 tie on *different, smaller* tiles per
  R17(b′), so those two get a tile probe next, not a width probe); and the
  HH_HPA / HS_HPA winners. Every row uses only forwarded knobs (R16), so
  none is a placebo; `iter_candidates` gate-verifies each against
  `validate_config` + `ldspad_feasible`, and a refusal is reported, never dropped
  silently. This is the same template the CC:256 steal batch uses, applied to the
  cells that actually tie.
* **`knob_sweep.py` repaired.** The module referenced `KNOB_SWEEPS` /
  `KNOB_SWEEP_BASES` at module scope without importing them, so its CLI raised
  `NameError` and three tests were red. Now imported; the sweep test file is green.
* **Preflight is the authority, not a number written here** (`claude.md`: never
  write a corpus count down). `python3 -m oto.harness.candidate_generator --dry-run`
  must report `0 refused`, `python3 -m oto check candidates --quiet` must report
  `0 illegal`, and `python3 -m oto preflight` must show
  full parity (38/38 shipped cells) before the run.

## R20 — the launch-boundary extension (ranked, deliberately NOT done here)

The three axes R15 wanted are real levers, but each is a `config_writer` change
plus a gate change, so they are a work item, not a deck row:

1. **`1LDSBuffer = 1`** — halves per-workgroup LDS, which doubles the resident
   workgroups that LDS capacity currently caps. Highest expected payoff because
   LDS *capacity* (not VGPR) is the binding constraint for the majority of
   kernels.
2. **`WaveSeparateGlobalReadA/B` (+ `ThreadSeparateGlobalReadA/B`)** — splits the
   LDS write by wave/thread, attacking cross-wave bank collisions on the wide tiles.
3. **`TransposeLDS` / `UnrollMajorLDSA/B`** — aligns the LDS layout with the VALU
   read order.

Each needs a one-line addition to `_fork_params` **and** the occupancy gate taught
the changed footprint, or the gate mis-predicts feasibility. Until then they stay
out of the deck: a candidate carrying them is a no-op (R16).

## R21 — what to stop doing

* **ThreadTile width ladders for C and Z** — the accumulator cap makes every
  wider tile illegal; pure rejects.
* **`MatrixInstruction` / `DirectToLds`** — rejected or harmful (R18).
* **Hunting HPA ties** — no floor exists to beat and native is already at 123–129 %
  of the ceiling (R17c).
* **Re-pinning `KNOB_SWEEP_BASES`** to chase a winner — the sweep tests index
  `[0]` and the D4 widen depends on CC VW1; put winner-geometry work in
  PLAN_BATCH instead (R17, R19).
* **Reading a single `best`-seed sample as a verdict** — judge within-run, ≥3
  seeds, on the median, ±2 % tie band.

## R22 — the overnight command

```bash
# CPU-only, safe under GNOME (no GPU stress):
python3 -m oto check candidates --quiet
python3 -m oto.harness.candidate_generator --dry-run
python3 -m oto preflight

# TTY only — the real run:
python3 -m oto tune --budget 10 --yes
```

The overlay `gfx90c_results/overlays/phases.seed.overlay.yaml` is a generated,
gitignored artifact; it has already been refreshed for this run with
`python3 -m oto.harness.candidate_generator` (no `--dry-run`), which appended the
tie-adapt rows.

Sizing is honest-estimate territory: the latest completed run took 8 h 39 m wall
clock, and the tie-adapt rows add ~36 phases on top of the existing deck, so plan
for a full overnight window. The full desktop (GNOME) session must not launch
this: ring timeouts and GPU resets under a loaded compositor are a known failure
mode — the run belongs in the user's TTY.

---

## R23 — the failed-candidate triage, and the two gates that now refuse them

Every failed candidate from every run was re-read CPU-only from three sources:
the ledger (`registry.db` `proposals`), every run directory's empty phases, and
the two latest live runs in full. The classes, worst first, with what happened to
each:

| class | evidence | disposition |
|---|---|---|
| **ZZ `VectorWidth=2` cleared the 16 B cap** | live `phase_cand_zz_..._vw2` refused by Tensile with `GlobalLoadVectorWidthA * DataType.numBytes() > 16`, 0 CSV; every other ZZ phase at VW1 built | **fixed.** The load gate's `Z` row held ComplexFloat's numbers (2 registers, 8 bytes) for complexDouble. It now reads 4/16 (Tensile `DataType`, ComplexDouble), and `tests/test_measurement_integrity.py` pins the whole row to Tensile so the load gate and `FAMILY_BYTES_PER_ELEMENT` cannot split again. It also fixes the derived default: with `reg=4`, an absent `VectorWidth` derives 1, matching the phases that built. |
| **`LocalSplitU=2` was never in the thread count** | 24 live phases: the 4 that built (CC `64x64x8/4x4`, HH `128x128x16/8x8`) vs 20 dead on `GlobalLoadVectorWidthA 2 % pv 4 != 0` (ZZ/DD `32x32x8/2x2`) and `Kernel Uses 131072 > 65536 bytes of LDS` (SS/HH_HPA `128x128x8/8x8`) | **fixed.** Tensile computes `NumThreads = SubGroup0 * SubGroup1 * LocalSplitU` (SolutionStructs:1964) and reads LSU from `WorkGroup[2]`; the gate read the tile alone, so the sweep looked legal. The gate now reads what Tensile will receive (see the shadowing row below). The sweep's family list is narrowed to the two that survive. |
| **`AggressivePerfMode=2` builds nothing** | every family and every tile, two runs: 0 `.hsaco`, 0 CSV, while the mode-1 control in the same run built 20 (one per target arch). Tensile writes the source, then fails to compile it | **removed** from the sweep, with the evidence recorded in `decks.py`. Not a gate: no tile property predicts it, so it is a deck decision like the retired `BufferLoad` row. |
| **GLVW coupling; NLCA/LDS/StaggerU coupling** | ~21–25 % of mutator draws were illegal before the fix | **already fixed** by R18's joint domains. |
| **A knob shadowed by an explicit `WorkGroup`** | the deck's two `CC` steal rows carried `WorkGroup: [16,16,1]` *and* `LocalSplitU: 2`, so they benchmarked at LSU 1 while their note claimed LSU 2 | **fixed on both sides.** `config_writer._fork_tile` emits an explicit `WorkGroup` verbatim and only folds `LocalSplitU` in when WorkGroup is absent — so `LocalSplitU` (declared honoured in R16) is a silent no-op beside one. The gate now reads the *emitted* value (a `WorkGroup` third element wins), and the two rows no longer pass an explicit WorkGroup, so their LSU lands. |
| **`Invalid parameter name: GlobalReduceVectorWidth`**, missing `configs/phase_*.yaml`, `resource_tracker` `ValueError` | historical only — the Sep-28 reference replays, the reference-resume path, and Python 3.14 joblib noise | already closed (`_drop_unsupported`, the resume path) or environmental; no action. |

Two Tensile rules were **measured and deliberately left un-gated**, because each
needs a new fact and neither refuses anything the fixes above do not already
refuse on this corpus:

1. The **LSU LDS reduction** — `ldsNumElementsReduction = LSU * MT0 * MT1`
   (SolutionStructs:4108), which is what makes the `131072 > 65536` rejects. It
   needs the *destination* element size per family, which is a new table.
2. The **NumThreads-aware VGPR budget** — `65536 // NumThreads` rather than the
   fixed 128 (which is only `65536 // 512`). Calibrating it against the corpus
   cost one false rejection on a measured kernel, and the last retired VGPR model
   died of exactly that overreach; it needs a config-exact VGPR table first.

Deck hygiene that follows from the two fixes: 24 dead rows left `phases.yaml`
(the `swAggressivePerfMode2` set and the now-refused `swLocalSplitU2` tiles), 9
left the seed overlay (the ZZ VW2 candidate, two `AggressivePerfMode=2`
candidates, and six `LocalSplitU=2` ones), and 8 left the `PLAN_BATCH`
hypotheses (the same two classes). Coverage parity is unchanged (38/38 cells)
because every removed row had a surviving sibling on the same tile and shape, and
`candidate_generator` now emits a fully gate-legal set with nothing refused.

The durable Tensile mechanics behind these fixes (NumThreads/LSU, the
shadowed-WorkGroup rule, the LSU LDS reduction, the 16-B cap check order, the
APM death) live in `docs/research/kernel_tuning.md` §4; §R23 keeps the triage
narrative and the disposition table.

---

## Superseded: rewrite 4 (2026-10-16), kept below for history

**What was new in rewrite 4** was a fresh A/B audit, a per-cell floor-vs-native
gap analysis, a kernel-type pattern read across `kernel_db.json`, and the
resulting route updates. Its numbers are superseded above; its mechanisms
(Routes A–F, the legality matrix, the open decisions) are still cited by §-number
from code comments, so they are retained verbatim below.

---

## R10 — latest A/B audit (2026-10-16, all runs folded)

30 cells total: **7 TIE / 23 UNGRADED** (no spoof floor data) / 0 WIN / 0 LOSS
on the `winner` basis. The 7 TIE cells, with the genuine gaps called out:

| cell | native | spoof | delta | verdict | cause |
|---|---|---|---|---|---|
| CC:192 | 118.2 | 43.2 | +173.2% | WIN | — |
| CC:256 | 210.8 | 214.0 | **−1.5%** | **TIE** | **the only genuine shortcoming** |
| CC:512 | 318.0 | 317.8 | +0.0% | TIE | at bar |
| CC:1024 | 344.0 | 301.4 | +14.1% | WIN | — |
| CC:2048 | 346.7 | 294.6 | +17.7% | WIN | — |
| DD:192 | 77.8 | 21.4 | +264.5% | WIN | — |
| DD:256 | 85.7 | 71.2 | +20.4% | WIN | — |
| DD:512 | 95.7 | 89.1 | +7.4% | WIN | — |
| DD:768 | 93.0 | 91.8 | +1.3% | TIE | at bar |
| DD:1024 | 92.9 | 91.4 | +1.5% | TIE | at bar |
| DD:1365 | 89.1 | 86.8 | +2.7% | TIE | at bar |
| DD:2048 | 98.6 | 96.8 | +1.8% | TIE | at bar |
| HH:256 | 763.4 | 201.5 | +278.9% | WIN | — |
| HH:512 | 1682.8 | 1388.7 | +21.2% | WIN | — |
| HH:1024 | 2581.9 | 2546.7 | +1.4% | TIE | at bar |
| HH:2048 | 2670.9 | 2658.0 | +0.5% | TIE | at bar |
| HH:4096 | 2749.3 | 2668.5 | +3.0% | TIE | at bar |
| SS:256 | 412.1 | 124.1 | +232.0% | WIN | — |
| SS:512 | 854.4 | 801.5 | +6.6% | WIN | — |
| SS:768 | 1105.4 | 1094.9 | +1.0% | TIE | at bar |
| SS:1000 | 1107.4 | 1075.2 | +3.0% | TIE | at bar |
| SS:1024 | 1135.1 | 1099.6 | +3.2% | TIE | at bar |
| SS:1365 | 1110.0 | 1073.0 | +3.4% | TIE | at bar |
| SS:2048 | 1164.0 | 1120.7 | +3.9% | TIE | at bar |
| SS:4096 | 1187.2 | 1109.8 | +7.0% | WIN | — |
| ZZ:128 | 16.8 | 4.9 | +242.9% | WIN | — |
| ZZ:192 | 20.8 | 14.8 | +40.8% | WIN | — |
| ZZ:256 | 22.2 | 17.5 | +27.0% | WIN | — |
| ZZ:512 | 23.9 | 20.6 | +16.4% | WIN | — |
| ZZ:1024 | 24.4 | 22.6 | +7.9% | WIN | — |

**The floor has no HPA families** (HH_HPA, HS_HPA) — those 8 cells are
UNGRADED because the spoof chain has no HPA kernels to compare against.
HH_HPA:512 reads 1447.0 native (no floor), HS_HPA:512 reads 1441.2 (no floor).

### Per-cell floor gap analysis (the TIE cells)

For each TIE cell, what the floor uses vs what native uses:

| cell | floor best config | native best config | gap |
|---|---|---|---|
| CC:256 | MT=[64,64] TT=[4,4] VW=2 DU=8 (214.0) | same config (210.8) | floor has MT=[128,128] (6 kernels) that native never generated; floor has TT=[8,8] (9 kernels) that native never generated |
| CC:512 | MT=[64,64] TT=[4,4] VW=2 DU=8 (317.8) | same config (318.0) | same gap: floor has MT=[128,128] + TT=[8,8] unexplored by native |
| DD:768–2048 | MT=[64,64] TT=[4,4] VW=2 DU=8 | same or MT=[64,32] TT=[4,2] VW=1 | same config class; native slightly ahead on all |
| HH:1024–4096 | MT=[128,128] TT=[8,8] VW=8 DU=16 | same config | native slightly ahead on all |
| SS:768–2048 | MT=[128,128] TT=[8,8] VW=4 DU=8 | same config or DU=16 | native slightly ahead on all |

**Key finding: the floor's CC advantage at 256/512 comes from MT=[128,128] tiles
(6 kernels, all at TT=[8,8]) that native never generated.** The floor's dominant
CC config (MT=[64,64] TT=[4,4] VW=2 DU=8) is identical to native's, and native
matches or beats it on every cell except CC:256 where the floor's 128×128 tiles
push it ahead.

### R11 — kernel-type patterns across all 25,671 kernels

From `kernel_db.json` (25,671 kernels, 11 runs):

| family | best tile | TT | VW | DU | best GF/s | pattern |
|---|---|---|---|---|---|---|
| HH | 128x128x16 | 8x8 | 8 | 16 | 2749.3 | large square, max TT area |
| SS | 128x128x8 | 8x8 | 4 | 16 | 1187.2 | large square, max TT area |
| DD | 64x64x8 | 4x4 | 2 | 8 | 98.6 | medium square, 4x4 TT |
| CC | 64x64x8 | 4x4 | 2 | 8 | 346.7 | medium square, 4x4 TT |
| ZZ | 32x32x8 | 2x2 | 1 | 8 | 24.4 | small square, 2x2 TT |

**The winning rule: ThreadTile area scales inversely with bytes-per-element.**
- 2 B (HH) → 8×8 = 64 accumulator VGPRs
- 4 B (SS) → 8×8 = 64 accumulator VGPRs (but 111 VGPR total, LDS-bound)
- 8 B (DD/CC) → 4×4 = 16 accumulator VGPRs
- 16 B (ZZ) → 2×2 = 4 accumulator VGPRs

Every family's winner sits at the largest TT satisfying `TT_area × bpe ≤ ~64`
accumulator VGPRs. This is the register-file budget, and it's why CC and ZZ are
stuck: their rule-implied TT (4×4 and 2×2) is already the winner, and the next
step up breaks the register file.

**Second pattern: LDS at the winner is always 16–25 KB, never 64 KB.** The
winners operate at 1/4 to 1/3 of the 64 KB LDS budget (2–4 resident workgroups).
That is the architectural sweet spot for this part.

**Third pattern: WorkGroupMapping is 4 or 8 at every winner, never 1.** WGM≥4
keeps neighbouring CUs on the same matrix B slice, which matters because L2 is
1 MiB shared. No winner uses WGM 2 or 16.

**Fourth pattern: the floor never pads CC/DD/ZZ.** The floor pads SS (110 LPA=2,
162 LPB=2 kernels) and HH (17 kernels) but **never pads DD, CC, or ZZ in a
single one of 2285 kernels**. Tensile's own `Perf/*.yaml` recipes likewise never
enumerate `LdsPadA/B`. That is a self-consistent blind spot in both the vendor
library and Tensile's recipes — the highest-yield untested axis.

**Fifth pattern: the floor never uses FractionalLoad=2, PGR=2,
WaveSeparateGlobalRead, or any of the other 11 "virgin" knobs.** All 2285 floor
kernels sit at the default for these. The vendor floor is aggressive on tile
geometry and conservative on everything else.

---

## R12 — gfx90c hardware read (confirmed from existing docs)

From `docs/gfx90c_tuning_guide.md` §1.1 (primary-source legal domains),
and `docs/gfx90c_theoretical_limits.md` §1:

| property | value | consequence |
|---|---|---|
| CUs | **7** | grid quantization cliff at small N |
| SIMDs/CU | 4 | 28 SIMDs total |
| Wavefront | 64 | 8 phases of 8 lanes per LDS access |
| FP32 lanes | 448 | 1613 GFLOPS peak (SS/DD/CC/ZZ) |
| Clock | 1800 MHz | 3226 GFLOPS packed-f16 peak (HH) |
| LDS | **64 KiB/CU** | 2 WG/CU budget at 32 KiB/WG |
| L1 | 16 KiB/CU | — |
| L2 | **1 MiB** shared | 16× smaller than gfx900's |
| DRAM | DDR4 UMA ~42 GB/s | machine balance 38 F/B at SS peak |
| MFMA | **absent** | MatrixInstruction rejected outright |
| WMMA | absent | — |
| 16 B load cap | verified | GLVW × bpe ≤ 16 |
| Max VGPR | 256/thread | accumulator budget is the binding constraint |
| Max LDS | 65536 B | LDS capacity binds 61.7% of kernels |

**The 7-CU occupancy cliff** (from `docs/gfx90c_tuning_guide.md` §1.2 and
`docs/gfx90c_tuning_guide.md` §1.2 (7-CU geometry)):

At 256³, a 128×128 macro tile yields 4 workgroups for 7 CUs — **6 of 7 CUs idle**.
No knob tuning recovers that; the only levers are a smaller MacroTile, more
GlobalSplitU, or LocalSplitU. At 512³, 128×128 yields 16 tiles (2.3/CU); at
1024³, 64 tiles (9/CU) — the cliff vanishes by N≥1024.

---

## R13 — route updates for the overnight run

### Route A (updated) — Spoof-steal for CC:256 only

The user's caveat is honoured: **only CC:256**, the single genuine shortcoming
(TIE −1.5%), and only because the floor already won the geometry there. The floor's
CC advantage comes from MT=[128,128] tiles that native never generated.

**Stolen-from-gfx900** (floor CC:256 winner):

| knob | floor winner | native winner today |
|---|---|---|
| MacroTile | **64 × 64** (dominant) + **128 × 128** (6 kernels) | 32 × 32 (dominant) |
| ThreadTile | 4 × 4 (55 kernels) + **8 × 8** (9 kernels) | 4 × 4 (965 kernels) |
| VectorWidth | 2 | 2 |
| WorkGroup | 16 × 16 × 1 | 8 × 8 × 1 |
| GlobalSplitU | 1 | 1 |
| DepthU | 8 | 8 |
| LdsPadA/B | 0 | 0 |
| measured | **214.0** | **210.8** (−1.5%) |

**The gfx900 → gfx90c port record** — what changes and why:

| knob | gfx900 value | gfx90c adaptation | why |
|---|---|---|---|
| MacroTile | 64×64 + 128×128 | **keep 64×64, add 128×128** | 128×128 is legal for CC at TT8x8 (128 accumulator VGPRs, within the 128 budget); the floor uses it and native never generated it |
| ThreadTile | 4×4 + 8×8 | **add 8×8** | 8×8 at 128×128 gives MT/TT self-consistency; accumulator VGPRs = 64, within budget |
| VectorWidth | 2 | **keep** | 2 × 8 B = 16 B, exactly on the verified cap |
| WorkGroup | 16×16×1 | **keep** | self-consistent with MT/TT |
| DepthU | 8 | **probe 8/16** | 16 needs 2× LDS; 8 is the safe choice on a 64 KiB/CU part |
| LdsPadA/B | 0 | **probe {1,2,4}** | CC never pads in the floor; GCN bank math says the row stride collides at power-of-2 tiles |
| StaggerU | 32 | **re-sweep 0/8/16** | 32 was chosen for a 56-CU raster |
| WorkGroupMapping | 4 | **probe {4, 8, −4}** | negative family untested; 8 is a 56-CU artefact but the floor uses it |

### Route B (updated) — The ten never-varied knobs

From the floor census (§R4):

| knob | floor value (2285/2285) | legal on gfx90c | why it could win |
|---|---|---|---|
| `LdsBlockSizePerPadA/B` | 0 | yes | per-block padding without redesigning the tile |
| `FractionalLoad=2` | 0 | yes | frees DepthU choice on ragged M/N/K |
| `PrefetchGlobalRead=2` | 0 | SS/HH only (bpe≥8 blocked) | deeper prefetch pipeline |
| `WaveSeparateGlobalReadA/B` | 0 | yes | LDS split by wave → fewer cross-wave bank collisions |
| `ThreadSeparateGlobalReadA/B` | 0 | yes | TSGR=2 works with WSGR |
| `TransposeLDS=1` | 0 | TLU=0 only | aligns LDS layout with VALU reads |
| `UnrollMajorLDSA/B=1` | 0 | yes | removes VgprForLocalReadPacking pressure |
| `1LDSBuffer=1` | 0 | SIA 2/3 only | halves LDS → doubles occupancy |
| `NonTemporalA/B = 1,2,3` | 0 | yes (glc/slc bits) | L2 pollution control on 1 MiB L2 |
| `GlobalReadPerMfma` | 1 | yes | schedules global reads between MFMAs |
| `LocalWritePerMfma` | −1 | yes | same for LDS writes |
| `PersistentKernel` | 0 | yes | amortises tile assignment on small grid |
| `MaxOccupancy < 40` | 40 | yes | artificially cap LDS to raise occupancy |
| `DepthULdsDivisor` | 1 | SIA=3 + TransposeLDS | cuts LDS usage by 2×/4× |

### Route C (updated) — Wave-quantisation ladder (SS/DD only)

From `docs/gfx90c_tuning_guide.md` §1.2 and the 7-CU cliff analysis:

| problem | MT | G (tiles) | G mod 7 | utilisation |
|---|---|---|---|---|
| 128³ | 16×16 | 64 | 1 | 91.4% |
| 128³ | 32×32 | 16 | 2 | 76.2% |
| 128³ | 64×64 | 4 | 4 | 57.1% |
| 256³ | 32×32 | 64 | 1 | 91.4% |
| 256³ | 64×64 | 16 | 2 | 76.2% |
| 256³ | 128×128 | 4 | 4 | 57.1% |
| 512³ | 64×64 | 64 | 1 | 91.4% |
| 512³ | 128×128 | 16 | 2 | 76.2% |
| 1024³ | 64×64 | 256 | 4 | 98.8% |
| 1024³ | 128×128 | 64 | 1 | 91.4% |

Route C is legal **only for SS and DD** (GlobalSplitU > 1 is gate-refused for
all half and complex families). For CC/ZZ/HH/HPA the equivalent fix is
LocalSplitU, or nothing.

### Route D — LDS-capacity ladder for Z

Z is the only family where the winner already uses ~25 KB LDS and still binds
LDS. Drop DepthU 16→8 and 8→4 to free capacity for a second resident workgroup.

### Route E — Split-complex (3 real GEMMs)

Carried forward. Reported split GFLOPS = (4/3)·R_real for CC ≈ 1513; for ZZ
≈ 127–131. This is the only route that can *beat* the 1613/101 BLAS ceiling
rather than approach it. Needs a harness change — separate work item, not a
deck entry. **Unmeasured — treat as hypothesis.**

### Route F — Persistent-kernel / fixed-grid

gfx90c has 7 CUs. A fixed 7-workgroup grid eliminates tail-wave idle by
construction. Tensile cannot express this — conceptual route for the
kernel-writer, not a deck entry.

---

## R14 — what to stop doing

Ceasing (per floor census):
- **ThreadTile width ladders for C and Z** — the accumulator cap makes every
  wider tile illegal; pure rejects.
- **LdsPad/LDS-layout work** for families where bandwidth is oversupplied — LDS
  *capacity* is better spent on residency.
- **MatrixInstruction / DirectToLds** — rejected outright or actively harmful
  (blocks NLCA>1, forces GLVW=1 on 8/16-byte dtypes).
- **MaxOccupancy/AggressivePerfMode assumptions** without measurement — never
  swept.

Now *starting*: MacroTile ladders for C and Z at the **existing** accumulator
width — the opposite direction to a ThreadTile ladder and the one the physics
asks for.

---

## R15 — the concrete deck for the overnight run

The existing deck (rewrite 3 §8) already contains:
- `KNOB_SWEEPS`: the sweep rows covering UseSgprForGRO, GLVW (CC paired),
  InnerUnroll, PGR, NLCA, MaxOccupancy, GSU (SS/DD), LSU, StaggerU,
  FractionalLoad, NonTemporal (APM was dropped — §R23)
- `FAMILY_DECKS`: 67 tile entries across 7 families
- `DECISION_TRIAL_TILES`: 4 trial entries (D1–D3)
- CC:256 steal batch: 14 rows in `PLAN_BATCH`

The overnight run adds:
1. **CC:128×128 tiles at TT8×8** — the floor's unexplored corner (Route A)
2. **CC:LdsPad {1,2,4}** — the never-padded family (Route B)
3. **ZZ:LdsPad {1,2,4}** — the never-padded family (Route B)
4. **DD:LdsPad {1,2,4}** — the never-padded family (Route B)
5. **SS:GSU {2,4} at small shapes** — wave quantisation (Route C)
6. **DD:GSU {2,4} at small shapes** — wave quantisation (Route C)
7. **FractionalLoad=2** — the never-emitted value (Route B)
8. **WaveSeparateGlobalRead {0,1}** — the virgin axis (Route B)
9. **1LDSBuffer {0,1}** — the virgin axis (Route B)
10. **NonTemporalA/B {1,2,3}** — the virgin axis (Route B)

All entries pass `validate_config` (CPU-only) and `ldspad_feasible`. The
overnight run command:

```bash
# CPU-only, from any session (safe under GNOME)
python3 -m oto check candidates --quiet
python3 -m oto.harness.candidate_generator --dry-run
python3 -m oto preflight

# TTY only — the real run
python3 -m oto tune --budget 10 --yes
```

Sizing: `phases.yaml` plus the seed overlay is what a run builds;
`python3 -m oto check candidates --quiet` prints the live deck count and refuses
anything illegal. The last run took 13 h 14 m wall clock for 7.95 h of phase-busy
time, so ~12–14 h is the honest estimate. Judge **within-run only**, ≥3 seeds,
median, ±2% tie band.

---

Supersedes rewrite 2 (2026-10-14, kept below). **What was new in rewrite 3** is a
re-grading of the corpus under *every* A/B basis the repo can express, the
decoded gfx900 floor knob census, a verified hardware read for gfx90c, and one
live attribution bug that was hiding 8 of the 38 contract cells. The rewrite-2
findings (F1–F5) stand; the revisions below supersede their *numbers*, not their
mechanisms.

**Owns: the candidate deck, the routes to beat the spoof floor, and the search
rules.** Does not own: acceptance bars/ceilings/verdicts (`docs/gfx90c_theoretical_limits.md`
§5), measured evidence (`docs/results.md`), or GCN hardware facts
(`docs/knowledge_base.md`).

---

## 0. Revision 3 — six findings that change the numbers, not the plan

### R0 — the verdict basis is inconsistent, and one path grades on the statistic
`ab_delta._stat` itself calls "seed-noisy, reference only".

Two graders exist in the tree and they do not agree:

| grader | statistic | used by |
|---|---|---|
| `ab_delta._pair_cells(..., agg="winner")` | **best per-kernel median**, both arms | `generate_acceptance_report` → `acceptance_report.json` |
| `ab_audit.audit` | **`r["GFLOPS"]` = max single raw sample**, both arms | other tooling |

`ab_delta._stat`'s own docstring ranks `best` (max raw sample) last: *"max single
raw sample (seed-noisy, reference only)"*. Grading a cell on best-of-many-draws is
an order statistic: **the more kernels an arm draws, the higher its expected max.**
The native arm carries 684–742 kernels per SS/HH cell; the spoof arm carries 26
for ZZ and 1166 for SS. That asymmetry is the whole content of some "wins".

The same data under every basis (`agg`, cells with both arms):

| basis | meaning | verdicts |
|---|---|---|
| `winner` (report) | native best-kernel vs spoof best-kernel | 38c: **29 W / 9 T / 0 L** |
| `median` | typical native vs typical spoof | 30c: **5 L / 3 T / 22 W** |
| `floor_best` | typical native vs spoof's BEST | 30c: **25 L / 3 T / 2 W** |
| `strict` | native worst vs spoof best | 30c: **30 L** |

**The five `median` losses are the real work list** (typical native → typical
spoof, %):

1. **CC:256 −63.6 %** (50.9 → 139.8) ← the only non-wall cell in the whole corpus
2. **SS:512 −46.4 %** (260.6 → 486.5, native ships 693 kernels, median = 30 % of its own winner)
3. **DD:256 −44.6 %** (34.7 → 62.7, 172 kernels, median = 41 % of winner)
4. **SS:256 −17.6 %** (74.7 → 90.7, 684 kernels, median = 18 % of winner)
5. **HH:256 −4.3 %** (156.7 → 163.7)

Read together: the *winner* on SS:512, SS:256, DD:256 is genuinely good (native
wins those cells outright on `winner`), but the surrounding 600+ kernels are junk
that drag the median to 18–41 % of the winner. **The deck is large enough that
its own winners are outliers inside it.** §7 (Rewrite 3) makes that actionable.

### R1 — an attribution bug was hiding 8 of 38 contract cells (fixed).

`oto/metrics/ab_records.py:phase_records` built records with
`analytics.aggregate_by_cell(...)`, which keys **(dtype, shape, fp)** — no family
dimension. `reporting._ab_records_from_csv` builds them with
`aggregate_by_cell_typecode(...)`, which keys **(dtype, shape, fp, family)** with
the §13.2 typecode-first resolver. Two consequences, both verified on the live
registry:

* HPA kernels have kernel typecode `HHS`/`HSS` → `family_from_kernel_name` returns
  `"HH"`; the HPA distinction lives *only* in the phase-level family stamp, which
  `_hpa_variant` reads off the explicit `family` field. With no `family` field the
  928 native HH_HPA + 717 HS_HPA rows and **5124 spoof HPA rows folded into HH**.
* Result: `arm_record_sets` → `_pair_cells` graded **30 cells, not 38** — the
  DB-hooked mutator was structurally blind to the `HH_HPA` 512/1024/2048/4096 and
  `HS_HPA` 512/2048 cells, and HH's medians were computed with HPA contamination.

Fixed (the typecode path plus `phase_family=extract_family_from_phase_id`), and
the contamination warning rate-limited to one line per (stamp, typecode) class —
the legacy `phase_auto_0_{S,Z}_*` pool would otherwise emit 100+ identical lines
per A/B load. After the fix:

| cell | native | spoof | Δ | note |
|---|---|---|---|---|
| HH_HPA 512 | 853.4 | 390.4 | **+118.6 %** | was invisible |
| HH_HPA 4096 | 1411.1 | 1277.8 | +10.4 % | was invisible |
| HS_HPA 512 | 820.4 | 384.4 | **+113.4 %** | was invisible |
| HS_HPA 2048 | 1388.9 | 1344.2 | +15.1 % | was invisible |
| HH_HPA 1024 | 1447.0 | 1445.5 | +0.1 % | TIE, at bar |
| HH_HPA 2048 | 1370.3 | 1381.1 | −0.8 % | TIE, at bar |

**HH_HPA is a 2.2× win that the mutator was never allowed to see.** Treat every
post-fix HH-family median as the new baseline; the pre-fix HH numbers in rewrite 2
§2 are contaminated.

### R2 — the twelve ORANGE cells: 11 are a yardstick artefact, 1 is real.

> **SUPERSEDED 2026-10-21 by §R47/§R48**: the "yardstick artefact" was a
> **4x unit error in the bar** (the client reports complex GEMMs at 2 flops per
> MAC), not a yardstick problem. The ORANGE list is **three** cells
> (`SS:256`, `HH:256`, `CC:192`), and the ten complex cells are at 80-97 % of
> the FMA roof. The table below is kept as it was measured on 2026-10-18.

`acceptance_report.json` reports **0 RED / 12 ORANGE (<50 % of the family's
realistic ceiling)**. Investigated on the latest data — the user's reading is
correct: they are non-blockers, and they are *bad kernels in absolute terms while
native already beats the floor everywhere except one cell*.

| cell | native %ceil | spoof %ceil | native vs floor | verdict |
|---|---|---|---|---|
| CC:192 | 10.6 | 3.9 | 118.2 vs 43.2 | WIN +173.6 % |
| CC:256 | 18.8 | 19.0 | 210.8 vs 212.3 | **TIE −0.7 %** ← the real one |
| CC:512 | 28.4 | 27.6 | 318.0 vs 308.4 | WIN +3.1 % |
| CC:1024 | 30.8 | 26.0 | 344.0 vs 290.8 | WIN +18.3 % |
| CC:2048 | 31.0 | 26.1 | 346.7 vs 292.3 | WIN +18.6 % |
| ZZ:128 | 17.1 | 5.0 | 16.8 vs 4.9 | WIN +241.4 % |
| ZZ:192 | 21.1 | 15.0 | 20.8 vs 14.8 | WIN +40.7 % |
| ZZ:256 | 22.5 | 17.7 | 22.2 vs 17.4 | WIN +27.3 % |
| ZZ:512 | 24.3 | 20.9 | 23.9 vs 20.6 | WIN +16.2 % |
| ZZ:1024 | 24.7 | 22.9 | 24.4 vs 22.6 | WIN +7.8 % |
| HH:256 | 31.0 | 8.2 | 763.4 vs 202.0 | WIN +277.9 % |
| SS:256 | 36.8 | 11.1 | 412.0 vs 124.3 | WIN +231.5 % |

Eleven are cells whose *ceiling* is the wrong bar: complex families pay 4 real
FMAs per complex-MAC with no complex-FMA and no MFMA on this part, and 128³/256³
cubes physically cannot fill 7 CUs. Native is 1.1–3.8× the floor on all eleven.
**CC:256 is the single genuine shortcoming**, and it is the one cell where native's
*typical* kernel is also behind (§0 R0).

### R3 — gfx90c verified hardware read: 7 CUs, MFMA absent, WGM 8 is wrong.

§1 of `docs/gfx90c_theoretical_limits.md` is the authority and is confirmed by the
research pass: gfx90c = ISA (9,0,12), **7 CUs / 28 SIMDs / 280 wave slots**, Wave64,
448 FP32 lanes, 1800 MHz, **LDS 64 KiB/CU**, L1 16 KiB/CU, L2 1 MiB, DDR4 UMA
~42 GB/s real. Tensile's own `AsmCaps.py` sets `HasMFMA: False` / `HasWMMA: False`
for ISA (9,0,0) and (9,0,6), so `SolutionStructs.py:3131-3134` **rejects
`EnableMatrixInstruction` outright**.

Two consequences the deck must act on:

1. **`MatrixInstruction` and `DirectToLds` are dead ends — record them, do not
   search them.** The whole ThreadTile→MFMA/VGPR-mapping literature is unreachable
   here. Worse, `DirectToLds` *blocks* `NumLoadsCoalesced > 1`, forces `GLVW=1` for
   8/16-byte dtypes, and forces `1LDSBuffer`. Every Draw spent on them is wasted.
2. **`WorkGroupMapping = 8` asks for 8 workgroups in the J-column before wrapping
   on a 7-CU part** — it is the floor's dominant value (1269 of 2285 shipped
   kernels) precisely because it was tuned for 56-60 CUs. The natural set for this
   hardware is `{1,2,3,4}` plus the **negative (I/J-swap) family** `{−1, −4}`, which
   the corpus has never generated at all.

The 7-CU occupancy cliff, per workgroups resident per CU
(`LDS = 2·(MT0+MT1)·DU·bpeAB`, budget 64 KiB/CU):

| config | LDS per WG | **WG/CU** |
|---|---|---|
| SS 128x128x8 | 16 KiB | 4 |
| SS 128x128x16 | 32 KiB | **2** |
| SS 128x128x32 | 64 KiB | **1** |
| DD 128x128x16 | 64 KiB | **1** |
| DD 128x64x16 | 32 KiB | 2 |
| HH 128x128x16 | 16 KiB | 4 |

At 256³ a 128×128 macro tile yields **4 workgroups for 7 CUs — 6 of 7 CUs idle.**
No knob tuning recovers that; the only levers are a smaller MacroTile, more
GlobalSplitU, or `LocalSplitU` (which fills waves *without* shrinking the tile —
rewrite 2 Route C's LocalSplitU note, now with the numbers above).

### R4 — the gfx900 floor's own knob census (2285 kernels decoded).

The floor (84 `.dat` entries → 2285 kernels,
`gfx90c_results/gfx900_shipped_manifest.json`) is **aggressive on tile geometry
and conservative on everything else**. Parameters with *zero* variance across all
2285 kernels: `LdsBlockSizePerPadA/B = 0`, `FractionalLoad = 2` (never emitted),
`PrefetchGlobalRead = 2` (never), `WaveSeparateGlobalRead = 0`,
`ThreadSeparateGlobalRead = 0`, `TransposeLDS = 0`, `UnrollMajorLDS = 0`,
`1LDSBuffer = 0`, `NonTemporal* = 0`, `PersistentKernel = 0`,
`GlobalReadPerMfma = 1`, `LocalWritePerMfma = −1`.

The padding asymmetry is the finding: **SS pads (LdsPadA=2 in 110 kernels,
LdsPadB=2 in 162, LdsPadB=4 in 55), HH pads in 17 — and DD, CC and ZZ never pad in
a single kernel.** Tensile's own `Perf/*.yaml` recipes likewise never enumerate
`LdsPadA/B`, `NumLoadsCoalesced`, `WaveSeparateGlobalRead`, `1LDSBuffer`,
`LocalWritePerMfma` or `GlobalReadPerMfma`. That is a **self-consistent blind spot
in both the vendor library and Tensile's recipes**, not a tuning decision — which
makes it the highest-yield untested axis for CC/ZZ/DD.

Also: `AssertFree0/1ElementMultiple` are 1 (no assertion) in essentially the whole
floor, while Tensile's own recipes set **8 for half, 4 for single, 2 for double**,
and every deck shape is divisible by 4 (all but 1000/1365 by 8). Setting them
unlocks `UseSgprForGRO` — which is the difference between 1 and 2 workgroups/CU on
a 256-VGPR part.

> **Correctness caveat, load-bearing:** `AssertFree*` is an *assertion*, not a hint.
> A wrong value produces **silently wrong results, not a crash**. Every AF-emitted
> row must be gated on exact shape divisibility (AF0EM = AF1EM = the largest power
> of two dividing both M and N; 1 for 1365) and the *first* AF row per cell must be
> validated against a reference GEMM before any of them is trusted.

### R5 — SOTA search strategy is a *budget-tiered* choice, and we are in the low tier.

From the TEVC 2022 Kernel Tuner study (arXiv:2210.01465 — 26 spaces × 9 GPUs ×
16 optimisers, GEMM in OpenCL on an AMD MI50):

| budget | what wins |
|---|---|
| ≤200 evaluations | **dual annealing**; Bayesian SMAC *"did not even beat random sampling for GEMM"* |
| 200–800 evaluations | first-improvement local search, simulated annealing |

Our per-configuration cost is a full Tensile generate + assemble + benchmark, so a
10-hour overnight is a few hundred evaluations at best: **we are squarely in the
low-budget regime.** The transferable conclusion is an **analytic pre-filter, then
first-improvement hill climbing**, *not* a surrogate model. Supporting: arXiv
2407.11488 finds AMD gains ~10× from autotuning where NVIDIA gains ~2×, and that
Nvidia-tuned configs do not transfer across vendors — i.e. honour the SS-pads /
DD-never-pads asymmetry above rather than averaging over it.

Practically, reorder §11's loop as: **prune by the analytic model first
(ceiling %, LDS WG/CU, TT-area × bpe) → hill-climb the surviving frontier
(1-knob deltas from the current winner) → only then draw diagonals.**

### R6 — two live wastes in the mutator's domain table (and one latent crash).

`oto/tensile/synthesis/donor_knobs.py:FORWARD_KNOB_DOMAINS`:

| current | problem | fix |
|---|---|---|
| `GlobalLoadVectorWidthA/B: (1,2,4)` | `4 × 8 B = 32 B` (DD/C) and `4 × 16 B = 64 B` (Z) both break the verified **16-B global-load cap**. The gate catches them CPU-side, but each is a wasted *draw slot* — the mutator has only 5 draws per iteration. | `S:(1,2,4)`, `H:(1,2,4,8)`, `D/C:(1,2)`, `Z:(1,)` |
| `WorkGroupMapping: (1,4,8)` | misses the negative (I/J-swap) family and the small-box set; 8 is wrong for 7 CUs (R3). | `(1,2,3,4,−1,−4)` |
| `StaggerUStride: (0,256,512)` | Tensile silently raises `StaggerUStride` to a whole multiple of `DepthU × bpe`, so **`256` becomes 64** for DU=16/bpe=4. Most of the domain collapses to one point. | `(0,64,128,256)` — 64/128 are already legal in `STAGGER_STRIDE_DOMAIN` |

Plus a latent crash: `oto/tensile/synthesis/donor_patterns.py` reads
`FORWARD_KNOB_DOMAINS["GSU"]` (twice) but the table keys it **`GlobalSplitU`** —
a `KeyError` the moment that branch is taken.

---

## 0.5 Rewrite 2 (2026-10-14) — kept in full below

### R7 — the deck-flood fix, and the new levers to spend the freed budget on

**The flood.** The native arm carries **684, 693, 742, 726, 668** kernels on
SS:256, SS:512, HH:512, HH:2048, SS:768 respectively — 30 cells, ~10 800 kernels
total, ~360 per cell. Their `median/winner` ratios are **18 % (SS:256), 30 %
(SS:512), 21 % (HH:256), 24 % (CC:256), 26 % (ZZ:128)**. A cell whose median is a
quarter of its own winner is a cell in which almost everything measured was junk:
near-duplicate mutants of a config already in the ledger, the same geometry
re-measured across seven runs, and the sweep-order defect of `docs/results.md` §13.4.

That is not a tuning problem, it is an **allocation** problem: the deck spends
10+ hours producing draws the acceptance basis then cherry-picks. Two changes:

1. **Bound the population per cell.** Cap distinct kernels per (family, cell) so
   the frontier is the top-K by the analytic model, and let the DB mutator mutate
   only the *active* survivors. `oto check library-parity --quiet` already proves the
   floor's 30 per-cell winners all pass every gate (todo 3 DONE), so the analytic
   pre-filter has a known-good reference set to imitate.
2. **Judge on a robust statistic, and report both.** The report should grade
   `agg="floor_best"` ("is a typical native kernel better than the floor's best
   kernel" — it *cannot* be won by cherry-picking one lucky config, because the
   native side is graded on its median) as a **co-primary** alongside `agg="winner"`.
   `ab_audit.audit`'s max-raw-sample basis should be dropped or renamed, since
   `ab_delta._stat` calls it reference-only.

**The new levers, ranked by expected payoff per GPU-minute.**

| # | lever | cells | mechanism | source |
|---|---|---|---|---|
| 1 | **`LdsPadA/B ∈ {1,2,4}` on CC, ZZ, DD winner geometries** | CC:256, ZZ all, DD:256 | GCN LDS = 32 banks × 4 B, `bank = (addr/4) mod 32`, wave64 serviced in 8 phases of 8 lanes; a 17.6 % gap means a second conflicting phase. The floor *never pads these families* — a blind spot in both the library and Tensile's own recipes. | R4 |
| 2 | **`AssertFree0/1ElementMultiple` = 4 (2 for double, 8 for half)** | all, gates exact shape divisibility | unlocks `UseSgprForGRO` (fewer VGPRs for addressing = the 1-vs-2 WG/CU step on a 256-VGPR part), removes shift/unshift code, widens tail-loop loads. Tensile's own recipes set exactly this; the floor ships 1 everywhere. | R4 |
| 3 | **MacroTile shrink + `LocalSplitU`** | SS:256/512, DD:256, HH:256 | 7-CU cliff: a 128×128 tile at 256³ is 4 workgroups for 7 CUs (57 %). `LocalSplitU` fills waves *without* paying the arithmetic-intensity cost of shrinking the tile. | R3 |
| 4 | **`WorkGroupMapping ∈ {1,2,3,4,−1,−4}`** | CC, HH_HPA, SS small | the negative (I/J-swap) family is never generated; WGM 8 is a 56-CU artefact. | R3/R4 |
| 5 | `FractionalLoad ∈ {0,1,2}` | SS, CC at 2048 | the only knob that changes load shape on non-divisible tails; the floor never emits 2. | R4 |
| 6 | `PrefetchGlobalRead ∈ {0,1,2}`, `PrefetchLocalRead 0/1` | all | PGR=2 never shipped; PGR=0 halves register pressure on VGPR-bound CC/ZZ. | R4 |
| 7 | `NonTemporalA/B ∈ {0,4,8}` | SS/HH 2048+ | avoids L2 (1 MiB) pollution on large squares; floor ships 0 everywhere. | R4 |
| 8 | `StaggerUStride ∈ {0,64,128,256}` | CC/ZZ/SS winners | 256 silently collapses to `DepthU × bpe`; 64/128 are live and already gate-legal. | R6 |

**Explicitly do NOT search** (R3): `MatrixInstruction`, `DirectToLds*`,
`WavefrontSize`. On gfx90c these are either `SolutionStructs`-rejected outright or
actively harmful (`DirectToLds` blocks `NLCA>1`, forces `GLVW=1` on 8/16-byte
dtypes, and forces `1LDSBuffer`).

### R8 — Route G: the CC:256 steal, with its port record (the one real shortcoming)

The user's caveat is honoured: **only CC:256**, the single non-wall cell, and only
because the floor already won the geometry there. Source is the locked gfx900
chain; the config was tuned for a 56-CU HBM part and is re-derived below.

**Stolen-from-gfx900** (`cells_resolved.json`, CC 256³):

| knob | floor winner | native winner today |
|---|---|---|
| `MacroTile` | **64 × 64** | 32 × 32 |
| `ThreadTile` | 4 × 4 | 4 × 4 |
| `VectorWidth` | 2 | 2 |
| `WorkGroup` | **16 × 16 × 1** | 8 × 8 × 1 |
| `WorkGroupMapping` | 4 | 4 |
| `GlobalSplitU` | 1 | 1 |
| `DepthU` | 8 | 8 |
| `GlobalLoadVectorWidthA/B` | **2 / 2** | absent (auto) |
| `LdsPadA` | 0 | 0 |
| measured | **212.34** | **193.77** (−8.7 %) |

Both kernels are `Ailk_Bjlk` (NT), so the gap is **pure tile area + load width**,
not contraction direction.

**The gfx900 → gfx90c port record** — what changes and why:

| knob | gfx900 value | gfx90c adaptation | why it changes |
|---|---|---|---|
| `MacroTile` 32×32 → **64×64** | 32×32 was native's own | **64×64, from the floor** | 4× the arithmetic intensity; LDS = `2·(64+64)·8·8 B = 8192 B/WG`, half the 16 KiB/WG budget |
| `WorkGroup` 8×8×1 → **16×16×1** | 8×8×1 | **16×16×1, from the floor** | `WG = MT/TT` self-consistently; 64 threads/WG keeps wavesPerCU legal |
| `GlobalLoadVectorWidthA/B` → **2/2** | absent | **2/2, from the floor** | `2 × 8 B = 16 B` sits exactly on the verified 16-B cap, so this is the widest legal global load for C — the one thing native's winner lacks |
| `StaggerU` 32 → **re-sweep 0/8/16** | 32 | 0/8/16 | 32 was chosen for a 56-CU raster order |
| `WorkGroupMapping` 4 → **probe {4, 8, −4}** | 4 | 4/8/−4 | CC:512 already prefers WGM8 within-run; the negative family is untested |
| `LdsPadA/B` 0 → **{1,2,4}** | 0 | 1/2/4 | CC never pads in the floor (R4); GCN bank math says the row stride, not the element |
| `AssertFree0/1ElementMultiple` → **4** | 1 | 4 | 256 is divisible by 4; unlocks `UseSgprForGRO`. **Gated on divisibility; verify against a reference GEMM first** (R4 caveat). |
| `PrefetchGlobalRead` → **{0,1}** | default 1 | 0/1 | CC is register-bound; PGR=0 relieves pressure |
| `LocalSplitU` → **probe {1,2}** | 1 | 1/2 | fills waves without shrinking the tile (R3) |
| `MultiBuffer` / `GlobalSplitU` | 1 | 1 | complex GSU is gate-refused on this port; LSU is the legal equivalent |

Only `MacroTile`, `WorkGroup` and `GLVW` are taken verbatim from gfx900 — all
three are *self-consistent consequences* of MT/TT/VW, not vendor magic numbers.
Everything else is re-swept because the part it was tuned for had 60 CUs and HBM2.

### R9 — everything from this point down is rewrite 2 (2026-10-14)

Everything from this point down is rewrite 2. It is superseded in its **numbers**
(the scoreboard, the tie causes, the per-cell winner table) by §0 above, and
retained in its **mechanisms** (Routes A–F, §8 legality matrix, §8.2 tiles,
§9 open decisions, §10 GUI-safe prep), which the revisions here extend rather than
replace.



---

## 1. Executive — five findings that change the plan

**F1. The spoof floor carries no clock telemetry, and that is a standing
property of the reference chain — not the cause of any single cell's verdict.**
`gfx90c_results/acceptance_report.json`: `spoof_clock_sclk_hz = 0.0`,
`spoof_clock_coverage = 0.0`, `clock_adjusted = False` on **every** cell, so no
verdict against the floor can be clock-corrected. Because the gap is uniform, it
cannot differentiate one cell from another and therefore explains no LOSS. The
only cell that ever read LOSS (CC 256³, run `run_20261013_214649`) was depressed
by a candidate-pool sweep-order defect, not by telemetry; the fix and the clean
re-run (`run_20261015_041159`, 19 W / 19 T / 0 L, CC:256 **TIE**) are in
`docs/results.md` §13.4. Do not silently widen the band.

**F2. Two knobs in the deck have only ever held ONE value, across all runs and
both arms.** `oto/tools/run_census.py` (`--json`), never-exercised-knobs section:
`GlobalSplitU = ['1']`, `StaggerU = ['32']`. Additionally, no winning config in
`cells_resolved.json` sets `PrefetchGlobalRead`, `AggressivePerfMode`,
`MaxOccupancy`, `LocalSplitU`, `BufferLoad`, `InnerUnroll`, `FractionalLoad`,
`UseSgprForGRO`, `LocalRead2A/B`, `GlobalRead2A/B`, `StorePriorityOpt`,
`GlobalLoadVectorWidthA/B` or `NumLoadsCoalescedB`. **Every tuning conclusion
drawn so far is a conclusion about MacroTile × ThreadTile × DepthU ×
VectorWidth × WorkGroupMapping only.** The tile axes are mined out; the other
eleven axes are untouched.

**But "never set" ≠ "never varied".** Tensile fills every absent knob from
`defaultBenchmarkCommonParameters`, so the base already carries `BufferLoad=True`,
`StaggerU=32`, `MaxOccupancy=40`, `AggressivePerfMode=1`, `PrefetchGlobalRead=1`,
`UseSgprForGRO=-1`, `GlobalLoadVectorWidth=-1`, `InnerUnroll=1`,
`FractionalLoad=0`. The experiments are the *non-default* values; a sweep value
equal to the default re-measures the baseline. Verified defaults:
`docs/knowledge_base.md` §7.1; machine-readable `TENSILE_KNOB_DEFAULTS` in
`oto/tensile/family_decks.py`, enforced by `tests/test_knob_sweep.py`.

**F3. The complex families are the two *narrowest* searches in the deck, which
is exactly backwards.** Measured distinct `(MacroTile, ThreadTile,
VectorWidth)` triples per family (`oto/tools/run_census.py`): SS 49 (16 distinct TT), HH 42
(12), HS_HPA 40, HH_HPA 36, DD 17 (7), **CC 17 (6)**, **ZZ 9 (5)**. CC and ZZ
are the worst performers AND the least searched. For CC the corpus only ever
emits ThreadTiles 2x2, 2x4, 4x2, 4x4, 4x8, 8x4 — and the *widest legal* corner,
**MT128x128x8 at TT8x4 and TT4x8, was never generated at all** (CC's largest
measured MacroTile is 128x64). For ZZ, **MT128x128x8/TT4x4 and MT128x64x8/TT4x4
are legal and were never generated** (the corpus's largest ZZ tiles are
128x32x16 and 32x128x16, both at 2x8).

The narrowness is partly structural, not lazy, and this decides what can be
tried: the legality gate caps the complex accumulator at
`ACCVGPR_BUDGET = 128`, so CC TT6x6 (144 accumulator VGPRs) and TT8x8 (256) are
refused with `Occupancy limit: ThreadTile 6x6 needs 144 accumulator VGPRs`, and
TT6x6 also fails `MacroTile 128x128x8 not divisible by ThreadTile 6x6`. Verified
through `validate_config`. **So the exploit is not a bigger ThreadTile — it is a
bigger MacroTile at the same accumulator width**, which raises arithmetic
intensity without touching the register file.

**F4. Occupancy is low, but not in the way the deck assumed — and the assumed
direction of the fix is inverted.** Measured from emitted code objects
(`python3 -m oto.harness.asm_occupancy`, 5757 kernels, GFLOP/s joined to 100%):
LDS strictly binds **61.7%**, VGPR strictly binds 22.4%, both cap identically in
15.9%; median 8 waves/CU; **121 kernels (2.1%) at ≤3 waves/CU**; 2810 (48.8%) at
≤3 *resident workgroups*/CU; **zero kernels spill to scratch**. The old deck's
M1/M2/M3 ("ALU saturation", "occupancy starvation", "VGPR pressure") is wrong in
its emphasis. Occupancy is *shape-limited*, not resource-starved, and the
binding constraint is LDS capacity — which is the one thing raising `ThreadTile`
makes worse.

**F5. SUPERSEDED 2026-10-21 (§R47): the complex families are at 80-97 % of
the FMA roof; the "20-25 % of the ceiling" was a 4x unit error in the bar.**
The text this finding replaced read: *CC's best measured kernel is 360.9 GF/s
(MT64x64x8/TT4x4, 79 VGPR, 12 waves/CU) against a 1118.7 bar; ZZ's is 24.7
(MT32x32x8/TT2x2, 63 VGPR, 8 waves/CU) against 98.6; the gap is not closable
by ThreadTile search alone.* Both bars were the BLAS-8 roof compared against a
client-reported number (Tensile charges 2 flops per complex MAC, so a reported
complex GFLOPS is ¼ of its BLAS-8 value). In the client's own unit the bars
are 279.7 and 24.65, and the corpus's 346.7 / 24.5 are **124 % / 99 % of
them** -- 86 % and 97 % of the FP32/FP64 FMA roofs
(`docs/gfx90c_theoretical_limits.md` §5.2). The conclusion is unchanged in *shape*
(the complex tile cap is real) and reversed in *sign* (the complex cells are not
short of headroom; the three small cells are).

---

## 2. Why each tie happens (per family, cause-coded)

Verdicts from `run_20261015_041159` (current): 19 WIN / 19 TIE / 0 LOSS. Reads as
"native already beats spoof" — and it does. But that is the wrong comparison: the
spoof floor is *also* mediocre on this part (CC 346.7 = 31% of ceiling). The real
gap in every family is **native vs. ceiling**, so §2 codes each family by what
limits it, and §8 targets that.

| family | verdict | best median | % ceiling | limiter | cause |
|---|---|---|---|---|---|
| CC | 3W/2T | 346.7 | 31.0% | **issue rate** | 4 real FMAs/complex-MAC, no complex-FMA opcode, no MFMA; 8 B/elem; ridge past legal TT (§6) |
| ZZ | 5W | 24.4 | 24.7% | **issue rate + VGPR** | 16 B/elem, 4 regs/elem → TT2x2 is the only tile with headroom; ridge at MT≈10, i.e. unreachable |
| HH | 2W/3T | 2749.3 | 111.7% | already at bar | — |
| HH_HPA | 2W/2T | 1447.0 | 129.4% | already at bar | — |
| HS_HPA | 2W/2T | 1441.2 | 128.8% | already at bar | — |
| SS | 2W/6T | 1187.2 | 106.1% | issue rate at high k | — |
| DD | 3W/4T | 98.0 | ~99% | at bar | — |

Cause codes for the 19 ties, individually:

- **CC:256 TIE** — was a candidate sweep-order defect (`docs/results.md` §13.4), not a
  kernel deficit. Do not add candidates for it.
- **CC:512 TIE** — real, +3.1%. Winner MT64x64/WGM4+NLCA1; the deck's
  128x128-class tiles were never generated for CC, so this is unexplored space.
- **DD 768/1024/1365/2048 TIE** — all ≤2.2%. DD's best measured kernel is
  99.9 GF/s at MT32x32x8/**TT2x2**, 35 VGPR, **28 waves/CU** — the highest
  occupancy in the corpus. DD is at its 98.6 bar already; residual gap is
  issue rate.
- **HH 1024/2048/4096 TIE** — +1.3 to +3.7%. HH's best is 2922.8 at
  MT128x128x16/TT8x8, 63 VGPR, 16 waves/CU. HH already exceeds its 2461 bar.
- **HH_HPA / HS_HPA 1024/2048 TIE** — −0.8% to +3.3%. At bar.
- **SS 768/1000/1024/1365/2048/4096 TIE** — +0.9% to +4.6%. SS's best measured
  is 1340.5 at MT128x128x8/TT8x8, 111 VGPR, 8 waves/CU; SS:4096 already exceeds
  its 1118.7 bar. **The residual SS gap is entirely in the small-shape rows**
  (k=32: 276.1 = 24.7%; k=192: 341.8 = 30.6%), which is wave quantization, not
  issue rate.

---

## 3. Occupancy — settled, and it is not the deck's problem

`python3 -m oto.harness.asm_occupancy --check-calibration` exits 0 (10/10 rows
of the AMD/ORNL GFX9 VGPR→waves/SIMD table reproduced, granule 4). The corpus
wide numbers above are from that model. Three consequences:

1. **There is no occupancy-starvation problem to fix.** Only 2.1% of kernels run
   at ≤3 waves/CU. The 48.8% figure the user noticed is *resident workgroups*,
   which is a different axis (a 1024-thread workgroup is 16 waves, so it reads
   as "1 workgroup" while occupying 16 of 40 wave slots). Both numbers are in
   `docs/gfx90c_theoretical_limits.md` §7.1.
2. **LDS capacity, not VGPR, is what caps residency** for 61.7% of kernels —
   which is why the `LDS_BUDGET` entry (§10) matters and why `LdsPad`/
   LDS-layout angles are deprioritised: bandwidth is ~8× oversupplied at
   TT4x4 FP32 (`docs/knowledge_base.md` §1 rate card), but *capacity* still decides how many
   workgroups fit, and `LdsPad` spends that capacity.
3. **No kernel spills.** Zero kernels carry a private segment. So there is no
   scratch-spill tax to recover, and `MinVgprNumber`/`MaxVgprNumber` tuning has
   no measured motivation.

---

## 4. Kernel-type patterns across all runs (the high-level answer)

From the 5757-kernel table, ranked by best measured GFLOP/s per family:

| family | best tile | TT | VGPR | waves/CU | LDS | best GF/s |
|---|---|---|---|---|---|---|
| H | 128x128x16 | 8x8 | 63 | 16 | 16384 | 2922.8 |
| S | 128x128x8 | 8x8 | 111 | 8 | 16384 | 1340.5 |
| D | 32x32x8 | 2x2 | 35 | 28 | 8192 | 99.9 |
| C | 64x64x8 | 4x4 | 79 | 12 | 16384 | 360.9 |
| Z | 32x32x8 | 2x2 | 63 | 8 | 24960 | 24.7 |

The pattern, stated as a rule: **the winning ThreadTile area scales inversely
with bytes-per-element.** 2 B → 8x8; 4 B → 4x4–8x8; 8 B → 4x4; 16 B → 2x2. That
is the accumulator register budget: `TT_area × bytesPerElement` must stay under
~64 accumulator VGPRs to leave room for A/B fragments and addressing. Every
family's winner sits at the largest TT satisfying that rule. **This is why CC
and ZZ are stuck: their rule-implied TT (4x4 and 2x2) is already the winner, and
the next step up breaks the register file.**

Second pattern — **waves/CU does not predict GFLOP/s.** D wins at 28 waves/CU
and H at 16, but C's 12 beats Z's 8 despite occupancy close to 2/3rds. What
predicts GFLOP/s is `bytesPerElement` × `flopsPerMac`, i.e. how much work each
FMA issue buys, which is fixed per family and not a knob.

Third — **LDS at the winner is always ≈16–25 KB, never 64 KB.** The winners
operate at 1/4 to 1/3 of the 64 KB LDS budget, i.e. 2–4 resident workgroups.
That is the architectural sweet spot for this part.

Fourth — **`WorkGroupMapping` is 4 or 8 at every winner, never 1.** WGM≥4 is
what keeps neighbouring CUs on the same matrix B slice, which matters because
L2 is 1 MB shared. No winner uses WGM 2 or 16.

---

## 5. Physics — why complex cannot reach its ceiling, and what that implies

Ridge for a tiled kernel (not the minimum-traffic figure the previous roofline
used):

```
AI = flopsPerMac · MT0·MT1 / ((MT0 + MT1) · bytesPerElement)
```

| family | bytes/elem | peak | ridge (F/B) | square MT at ridge | legal TT at that MT |
|---|---|---|---|---|---|
| S | 4 | 1613 | 38.4 | 154 | 8x8 ✓ |
| H | 2 | 3226 | 76.8 | 154 | 8x8 ✓ |
| D | 8 | 101 | 2.4 | 19 | 2x2 ✓ (already ALU-bound at MT≥32) |
| C | 8 | 1613 | 38.4 | 77 | 4x4 ✓ (MT77 needs MT≥96 to cross) |
| Z | 16 | 101 | 2.4 | 9.6 | 2x2 ✓ (ALU-bound everywhere) |

Two families are already past their ridge and still at 20–25% of ceiling: that
is the proof that **complex is issue-bound, not bandwidth-bound**. The
instruction-count argument: one complex MAC is four real FMAs and there is no
complex-FMA or MFMA opcode on gfx90c. Complex-MAC *throughput* is ÷4 relative to
a real MAC, but BLAS-8 accounting credits 8 flops per complex MAC, so the BLAS
ceiling is unchanged (`oto/tensile/gates/assembly.py`). Reaching it needs the
FMA pipe issuing every cycle, which needs the issue slots not spent on
addressing, LDS reads and loop overhead.

**Implication for the deck:** for C and Z the only levers that reduce
non-FMA issue slots are (a) more coalesced loads (`NumLoadsCoalescedA/B`),
(b) longer unroll (`InnerUnroll`, `DepthU`), (c) `UseSgprForGRO` — moving
global-read addresses from VGPR to SGPR frees registers, which is the scarce
resource for Z. Tiles are exhausted.

---

## 6. The routes (steal + alternatives)

### Route A — Spoof-steal, restricted to the two worst losers, with a port record

Sanctioned per the user's own caveat: **only CC and ZZ**, only the worst cells,
and each stolen config must be documented as derived-from-gfx900 with its
adaptation. gfx900 floor configs used verbatim (~1100 phases of the locked
chain) were tuned for a 56-CU HBM part; the three that must be adapted are
tile size (HBM-optimal tiles overshoot a 1 MB L2), `WorkGroupMapping` (tuned
for 56-CU raster order, not 7), and `GlobalSplitU` (a dGPU never needed it).

Restriction: **only MT64x64 and smaller may be stolen.** gfx900's rank-1
solutions cluster at MT 64x64 and below, and those are also the correct class for
a 1 MB L2. An MT128x128 gfx900 tile would be stealing a config tuned for a part
with ~16× the L2. **AMD's shipped library is not uniformly small-tiled** — the
same vega10 tree holds MT128×16 (FP32), MT064×064 (FP64) and MT016×016 (FP16) —
so "AMD prefers small tiles" is not a supportable generalisation; only the
*rank-1* rows are small, and those are the ones that transfer
(`docs/research/kernel_tuning.md` §9.1).

**The port record.** AMD's own rank-1 solutions for the sibling Vega parts
(gfx906/gfx900, wave64, 64 KB LDS/CU — the same data-path shape as this part with
60 CUs and ~900 GB/s HBM2 instead of 7 and 42 GB/s), from
`docs/research/kernel_tuning.md` §9.1:

| source family | rank-1 tile | TT | DU | WorkGroup | VW | BufferLoad | PGR | PLR | APM | MaxOcc |
|---|---|---|---|---|---|---|---|---|---|---|
| FP32 (`vega10…SB`) | 128x016 | 4x4 | 16 | 32x4x2 | 4 | 1 | 0 | 1 | 1 | 40 |
| FP64 (`vega20…DB`) | 064x064 | 4x4 | 4 | 16x16x1 | 2 | — | — | — | 1 | 40 |
| FP16 (`vega20…HB`) | 016x016 | 2x2 | 8 | 8x8x1 | 2 | — | — | — | — | 40 |

What transfers, and what must be re-derived for gfx90c:

| knob | AMD's gfx900 choice | keep / adapt for gfx90c | why |
|---|---|---|---|
| `ThreadTile` | 4x4 (FP64), 2x2 (FP16) | **keep** — matches this part's own measured winners (DD 2x2, ZZ 2x2) | accumulator register budget is a function of bytes-per-element, which is identical |
| `DepthU` | 4 (FP64), 8 (FP16) | **adapt down** — 16 (FP32's) would need 2× the LDS on a part with 1/60th the bandwidth | LDS capacity is the binding constraint here (61.7% of the corpus) |
| `WorkGroup` / `LocalSplitU` | `32x4x2` = LSU 2 on FP32 | **keep the LSU shape** — AMD itself splits the M extent | LSU is the one wave-fill knob legal for this part's complex families; `GlobalSplitU` is not (§8.1) |
| `StaggerU` | 32 | **re-sweep** 0/8/16 — 32 was chosen for a 56-CU raster | §8.1 sweeps it |
| `WorkGroupMapping` | (not overridden) | **re-sweep** 4/8 — this part's winners use 4 or 8 | 7 CUs with 1 MB L2 wants neighbours on the same B slice |
| `MaxOccupancy` | 40 (uncapped) | **re-sweep** 8/12/20 | 100% of shipped AMD uses 40; on 7 CUs wave count is scarcer |
| `AggressivePerfMode` | 1 | **re-sweep** 1/2 | mode 2 *may* cap LDS (comment says 2 waves/SIMD; branch unconfirmed at pinned commit — corpus3 Q-E ii), and 2 waves/SIMD is this part's measured median |
| `BufferLoad` | 1 (FP32) | **keep** | gates the StaggerU path |

The concrete stolen cells are the deck entries in §8.2 — the ones that exist only
because the floor won there and native never generated the tile.

### Route B — Pick up the ten knobs the corpus never *explicitly set* (highest yield, no steal)

§F2. **"No winner sets knob X" is not "knob X has never been varied."** Tensile
fills every absent knob from `defaultBenchmarkCommonParameters`, so several of
these are already active at a fixed value, and only their *non-default* values are
experiments. The verified default for each is in `docs/knowledge_base.md` §7.1;
`TENSILE_KNOB_DEFAULTS` in `oto/tensile/family_decks.py` is the machine-readable copy, and
`tests/test_knob_sweep.py` refuses a sweep row that offers no non-default value.
Concretely, per family, with the reason:

| knob | who | why |
|---|---|---|
| `NumLoadsCoalescedA/B` | C, Z | default 1; one phase in the entire corpus sets NLCA. |
| `UseSgprForGRO` | Z | default `-1` (auto). Z is VGPR-bound at TT2x2 (63 VGPR); moving GRO offsets to SGPR buys VGPR. Requires `BufferLoad=1`, which is the default. |
| `PrefetchGlobalRead` | S, C | default 1. The corpus has both `None` and explicit `False`; the experiments are 0 and 2, with 1 as the control. |
| `AggressivePerfMode` | all | default 1. Mode 2 is *described as* a 2-waves/SIMD LDS cap, but the explicit branch is unconfirmed at the pinned commit (corpus3 Q-E ii) — the row tests whether mode 2 differs at all; `docs/gfx90c_theoretical_limits.md` §7 puts the corpus median at 8 waves/CU = 2 waves/SIMD, so a real cap would be a free experiment in that direction. |
| `MaxOccupancy` | all | default 40 (uncapped). Lower values pad per-workgroup LDS to `DeviceLDS // N` (floor) — a pure occupancy clamp. |
| `LocalSplitU` | S, H at small k | default 1. Splits the MTA M extent across waves without a reduction kernel. `validate_config` accepts it for every family, so it is legal for complex on this gate. |
| `FractionalLoad` | S, C at 2048 | default 0; the only knob that changes the load shape for the non-divisible tails. |
| `GlobalSplitU` | S at k≤192, D at small k | default 1. **7-CU wave quantization**: `G = ceil(M/MT)·ceil(N/NT)`; at N=256, MT128 → 4 tiles on 7 CUs = 57% utilisation, MT32 → 64 tiles = 91%. GSU multiplies G, so it is the correct fix for the small-shape rows. |
| `InnerUnroll` | C, Z | default 1; directly reduces the fraction of issue slots spent on loop control. |

`BufferLoad` was on this list and is **not** a deck entry: its default is already
`True`, so sweeping `BufferLoad: True` re-measures the baseline. An explicit `False`
is the only real change and it also kills the `StaggerU` path, which confounds it.
Recorded, not swept.

`GlobalLoadVectorWidthA/B` is **not** a deck entry as an unpaired row (§9 D4):
unpaired, the only values Tensile will build are `1` and `== VectorWidth` (the pv
reduction also cancels a widen on most tiles). A *paired* widen — `GLVW=2` with
`AssertFree0/1ElementMultiple=2` — is legal for CC only, and *is* swept as a
trial (added 2026-10-14). See §8.1.

### Route C — Wave-quantisation ladder (small shapes only)

`GlobalSplitU` × tile-size pairs chosen so `G·S` lands near a multiple of 7.
Enumerate: for each cell, for `MT ∈ {16,32,64}` and `S ∈ {1,…,7}`, keep the pairs
where `G·S mod 7` is 0 or 1. This is a *narrow* route — few candidates, all in
the quantisation-optimal band.

**The arithmetic** (`G = ceil(M/MT) × ceil(N/NT)` tiles on 7 CUs; utilisation =
`G / (7 × ceil(G/7))`):

| problem | MT | G | G mod 7 | aggregate utilisation |
|---|---|---|---|---|
| 128x128 | 16x16 | 64 | 1 | 91.4% |
| 128x128 | 32x32 | 16 | 2 | 76.2% |
| 128x128 | 64x64 | 4 | 4 | 57.1% |
| 128x128 | 128x128 | 1 | 1 | 14.3% |
| 256x256 | 32x32 | 64 | 1 | 91.4% |
| 256x256 | 64x64 | 16 | 2 | 76.2% |
| 256x256 | 128x128 | 4 | 4 | 57.1% |
| 512x512 | 64x64 | 64 | 1 | 91.4% |
| 512x512 | 128x128 | 16 | 2 | 76.2% |
| 1024x1024 | 64x64 | 256 | 4 | 98.8% |
| 1024x1024 | 128x128 | 64 | 1 | 91.4% |
| 2048x2048 | 128x128 | 256 | 4 | 98.8% |

Three things this table settles, and they are counter-intuitive:

1. **MT128x128 at 256³ runs 4 tiles on 7 CUs = 57% of the machine**, while MT32x32
   runs 64 = 91%. The tail is not a rounding error at small N; it is a 34-point
   swing.
2. **The penalty vanishes by N ≥ 1024** (98.8% at MT64x64), so Route C applies to
   the small-shape rows only. Spending the budget on quantisation for 1024³+ is
   wasted.
3. **A bigger tile is *worse* for utilisation at small N but *better* for
   arithmetic intensity** — these pull in opposite directions, which is why the
   small-shape rows (SS k=32 at 24.7% of ceiling, SS k=192 at 30.6%) are hard and
   why `LocalSplitU` is the interesting knob: it fills waves **without** shrinking
   the tile, so it does not pay the arithmetic-intensity cost that MT16x16 does.

Route C is legal **only for SS and DD** (±8.1). For CC/ZZ/HH/HPA the equivalent
fix is `LocalSplitU`, or nothing.

### Route D — LDS-capacity ladder for Z

Z is the only family where the winner already uses ~25 KB LDS and still binds
LDS. Drop `DepthU` 16→8 and 8→4 to free capacity for a second resident
workgroup, and/or `LdsPad` 0 (deprecated, never spent). Z's LDS at the winner is
24960 B — 38% of the CU — so one more workgroup costs the remaining 62%.

### Route E — Split-complex (the "3 real GEMMs" route)

Carried forward from the previous rewrite and still unmeasured. Reported split
GFLOPS = (4/3)·R_real for CC (3 real GEMMs under BLAS-8), ≈1513; and
(4/3)·95–98 ≈ 127–131 for ZZ. This is the only route that can *beat* the
1613/101 BLAS ceiling rather than approach it, because it removes the
complex-MAC instruction penalty entirely. It needs a harness change (a
decomposed call sequence, not a Tensile solution), so it is a separate work
item, not a deck entry. **Unmeasured — treat as hypothesis.**

### Route F — Persistent-kernel / fixed-grid route

gfx90c has 7 CUs. A fixed 7-workgroup grid eliminates tail-wave idle by
construction. Tensile cannot express this (`WorkGroup` sizes the grid, not the
occupancy), so this is a conceptual route for the kernel-writer, not a deck
entry. Listed so it is not re-proposed as a knob.

---

## 7. What to stop doing

Ceasing: **ThreadTile** width ladders for C and Z (F3/F5 — the accumulator cap
makes every wider tile illegal, so they are pure rejects); `LdsPad`/LDS-layout
work (`docs/knowledge_base.md` §1 rate card — bandwidth ~8× oversupplied, and LDS *capacity*
is better spent on residency); any `-mllvm -amdgpu-*` or compiler-flag proposal
(no-op: Tensile emits ISA text to the assembler for ~93% of the shipped
library); `MaxOccupancy`/`AggressivePerfMode` *assumptions* without a
measurement (§F2 — never swept).

Now *starting*: MacroTile ladders for C and Z at the **existing** accumulator
width (F3). That is the opposite direction to a ThreadTile ladder and it is the
one the physics asks for.

---

## 8. The concrete deck additions

Every entry below was checked through `validate_config` (CPU-only) and reported
`Valid`; the rejections found along the way are recorded so they are not
re-proposed. Entries land in `oto/tensile/family_decks.py` `FAMILY_DECKS`, which is
where the generator reads them.

### 8.1 Legality matrix for the un-varied knobs (measured, 2026-10-14)

Each surviving sweep entry was checked as `the family's current winner tile +
the one knob change`, with the row's `width_override` applied where it has one
(NLCA needs it). Result: **every emitted cell is legal — 69/69 row×family
cells.** The ✗ cells below are knob/family pairs the deck deliberately does not
name, and each is a real, measured refusal.

| knob | CC | ZZ | SS | HH | DD | HH_HPA | HS_HPA |
|---|---|---|---|---|---|---|---|
| `NumLoadsCoalescedA/B=2` | ✓(vw1) | ✗ | ✓(vw1) | ✓(vw2) | ✗ | ✗ | ✗ |
| `UseSgprForGRO` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `PrefetchGlobalRead` 1 / 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `AggressivePerfMode` 1 / 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `MaxOccupancy` 8 / 12 / 20 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `LocalSplitU=2` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `StaggerU` 0/2/4/8/16/32 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `FractionalLoad=1` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `InnerUnroll=2` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `NonTemporalA/B` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GlobalSplitU=2/4` | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ |
| `GLVW=2` + `AF0/1EM=2` (paired) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

Two hard results worth stating plainly:

- **`GlobalSplitU` > 1 is illegal for every half and complex family on this
  repo's gate** — `Assembly class: GlobalSplitU=2 on complex C: illegal`, and
  the same for `half Assembly` and `half with f32 acc`. Only SS and DD may
  split K. This kills the wave-quantisation fix for HH/HPA at every small
  shape, and it means Route C applies to SS and DD only.
- **`NumLoadsCoalesced=2` needs the right width**: legal at CC vw1 (not vw2),
  SS vw1/vw2 (not vw4), HH vw2, and never for ZZ/DD/HPA. The rule is
  `NLCA ≤ NumLoads` where `NumLoads` comes from the width, so the deck entries
  pair the width with the coalesce count rather than assuming both.
- `StaggerU` is legal at *every* value with and without `BufferLoad`, so it is
  free to sweep — and it is currently pinned at 32 corpus-wide (§F2).

Two caveats that are **not** in this matrix:

- **`BufferLoad` is not a deck entry.** Its Tensile default is already `True`
  (`docs/knowledge_base.md` §7.1), so `BufferLoad=True` re-measures the baseline. It
  was removed from `KNOB_SWEEPS` on 2026-10-14.
- **`GlobalLoadVectorWidth` is no longer a deck entry (§9 D4, resolved 2026-10-14).**
  The gate models Tensile's *whole* rule, not just its first half: `GLVW !=
  VectorWidth and != 1` is refused **only when** `not bufferLoad or not
  GuaranteeNoPartialA`, where `GuaranteeNoPartialA` is
  `AssertFree0ElementMultiple % GLVW_A == 0` on a `TLUA` operand
  (`SolutionStructs.py:4584-4596` and `:4177-4183`), and `bufferLoad` is true only
  for a `KernelLanguage: Assembly` kernel. That is the branch the reference-rerun
  hashes `7f866dcf` / `a0edeb30` died on. With the default
  `AssertFree0ElementMultiple=1`, an *unpaired* `GLVW=2` is **refused** for
  CC/SS/HH/HPA and a **no-op** for ZZ (the pv reduction cancels it back to 1) and
  DD (already the derived default) — so the row was removed.
  
  The widen **is** realizable as a *pair*: `AssertFree0ElementMultiple=2` lifts
  `GuaranteeNoPartialA`, and where the pv reduction does not cancel it that is a
  real 8 B → 16 B load. Measured on the gate, that is **CC only** (VW1, pv=1); ZZ
  pv-cancels it, and for SS/HH/HPA (VW4) the pair is a *narrow*, not a widen. The
  paired CC row is swept as a trial (added 2026-10-14, §9 D4). Home:
  `oto/tensile/gates/loads.py` `_glvw_for` + `_Operand._restriction_active`,
  `tests/test_occupancy_model_vgpr.py::TestGlobalLoadVectorWidthRule`.

### 8.2 Tiles that are legal but were never generated (the real CC/ZZ headroom)

| family | MacroTile | ThreadTile | VW | why this corner |
|---|---|---|---|---|
| CC | 128x128x8 | 8x4 | 1 | widest legal accumulator (128 VGPR); AI 64 F/B = 167% of ridge; never generated |
| CC | 128x128x8 | 4x8 | 1 | transposed form of the above; never generated |
| CC | 128x96x8 | 8x4 | 1 | between the measured 128x64 and the unmeasured 128x128 |
| ZZ | 128x128x8 | 4x4 | 1 | AI 32 F/B = 13× ridge; never generated |
| ZZ | 128x64x8 | 4x4 | 1 | asymmetric, never generated |
| ZZ | 64x64x16 | 4x4 | 1 | longer unroll at the same width; never generated |
| DD | 128x128x8 | 8x8 | 1 | DD TT8x8 is legal (unlike CC); AI far past its 2.4 F/B ridge |
| DD | 64x128x16 | 4x8 | 1 | legal and never generated |

`StaggerU` 32 is the current constant; the sweep adds 0/8/16 to test whether the
7-CU geometry wants a different raster.

### 8.3 Route E and Route F are not deck entries

Route E (split-complex, 3 real GEMMs) and Route F (persistent fixed grid)
cannot be expressed as Tensile solution knobs — E needs a decomposed call
sequence in the harness, F needs a kernel-writer change. They are recorded in
§6 so they are not re-proposed as knobs, and are tracked as separate work items
(`incomplete_work.md`), not as deck rows.

---

## Sources

All numbers in §1–§8 are reproduced by repo tooling, which is the citation:
`oto/tools/run_census.py` (knob census, tile triples), `oto.harness.asm_occupancy` (5757-kernel
measured occupancy + GFLOP/s join), `oto.harness.cell_resolver` (per-cell
winners), `oto.harness.occupancy_bounds` (predicted residency), `validate_config`
(§8.1's legality matrix), and `gfx90c_results/acceptance_report.json` run
`run_20261013_214649`.
Architecture/ridge facts: `docs/knowledge_base.md`, `docs/gfx90c_theoretical_limits.md`.
Anti-transfer: arXiv:2505.03780, arXiv:2507.15277 (`docs/research/kernel_tuning.md` §6).

---

## 9. Open decisions (user-owned; do not act on these silently)

**D1 — CC:256's former LOSS closed as a candidate sweep-order defect
(resolved 2026-10-15).** The candidate pool emitted `ProblemSizes`
lexicographically (`1024, 192, 2048, 256, 512`), so 256³ was measured
immediately after the 2048³ kernel and its median absorbed the throttled clock
(`claude.md` §2.0.3). The clean re-run (`run_20261015_041159`) reads CC:256 as
**TIE** — native `210.772` vs floor `214.882`, −0.74 %. The floor arm still
carries no telemetry (`spoof_clock_coverage = 0.0`), so `clock_adjusted = False`
on every cell — a standing property of the reference chain, not a closure path
for this cell. Do not close it by widening a band; the verdict logic is not ours
to change.

**D2 — `BYTES_PER_ELEMENT["Z"]` vs `LDS_BUDGET`** (full record and measurement in
`docs/gfx90c_theoretical_limits.md` §6.1). Tensile's complexDouble is `'reg': 4` so
`numBytes() = 16`, and the same module already has `FAMILY_BYTES_PER_ELEMENT
["ZZ"] = 16` — three tables in one file say 16, one says 8, and ZZ is the only
family where the gate's byte count is half of Tensile's element width.

The 8 is **not** an over-admission: measured, 0 of 229 ZZ kernels that built and
ran exceed the 16384 budget at that reading, so the gate never wrongly let a ZZ
config through. What it does is understate ZZ's real LDS pressure by 2× on the
base footprint (the gate says 16384 where Tensile allocates 65536 for a 64x64x16
tile). Correcting the bytes alone refuses **67 of those 229** kernels, so the
baseline `"Z": 16` with budget 32768 must be decided as a pair.

**Resolved 2026-11-14 (owner decision):** `"Z": 16` with `LDS_BUDGET` kept at
16384. The six D2/D3 trial rows in `phases.yaml` (64x64x16, 128x32x8, 32x128x8 at
512/1024), the `DECISION_TRIAL_TILES` D2/D3 entries and the bare `64x64x16` ZZ
deck rows were retired/cleaned the same day, Tensile's solution-construction
verdict for those tiles was re-checked first (see changelog). The gate now
refuses every ZZ tile with (MT0+MT1)*DepthU > 1024 by design; the contract
"never admit Tensile's refuses" is the invariant preserved, not permissiveness.

**D3 — should the ZZ deck's 24.9 KB LDS winners be re-checked against the
`LDS_BUDGET` gate after D2?** If D2 lands, ZZ's own winners (24960 B base,
65536 B emitted) move above the budget. The deck generator refuses candidates the
append boundary judges illegal, so this can silently empty the ZZ deck. Resolve
with D2.

**Resolved 2026-11-14 with D2:** the shipped ZZ deck was emptied of the
above-budget tiles (64x64x16 rows retired; 128x32x8/32x128x8 retired). What
remains is the at-budget ladder (64x64x8/LdsPadB=1, 64x64x4, 32x32x16/DU16,
32x32x8). Whether Tensile itself accepts the retired tiles is recorded next to
the changelog entry; the gate policy stands regardless — the contract is
refusal, which the owner chose over permissiveness on 2026-11-14.

**D4 — the sweep deck's baseline and the paired widen (resolved 2026-10-14; D1–D3
trial tiles added the same day).**

*Baseline: explicit control, opt-in.* `generate_knob_sweep_phases` gains
`include_baseline`, and `knob_sweep` gains `--baseline`: the base tile is emitted
unchanged once per (family, pattern, shape), tagged `_base`, so every knob delta
has a same-run control. Default off (the implicit default-as-control rows
`PrefetchGlobalRead=1` / `AggressivePerfMode=1` still exist); the run book (§10)
passes `--baseline`.

*Paired CC widen: added as a trial row.* `GLVW=2` **with**
`AssertFree0/1ElementMultiple=2` is a real 8 B → 16 B load and is legal for CC only
(VW1, pv=1); ZZ pv-cancels it and for SS/HH/HPA it is a narrow. CC is the worst
family (31% of its ceiling) and issue-bound. It is a `KNOB_SWEEPS` row
(`GlobalLoadVectorWidth`, CC-only) — not a clean one-knob change
(`AssertFree0ElementMultiple=2` asserts `M % 2 == 0` and reaches other Tensile
paths), so it is labelled a trial and the run judges it. §8.1 matrix +1 (69/69).

*D1–D3 trials: `DECISION_TRIAL_TILES` + `--trials`.* Three decisions are not knob
changes, so they own tiles instead of rows (emitted unchanged, tagged
`_trialD<n>`; `generate_decision_trial_phases`):
- **D1** — CC `64x64x8/4x4/VW2` (the steal geometry) at `192`/`256`, the shallow
  cells CC:256 owns. The candidate re-measures; the sweep-order fix
  (`docs/results.md` §13.4) and the clean re-run close it.
- **D2** — ZZ `64x64x16/4x4/VW1` (the LDS-boundary tile). A ZZ VW2 "differentiator"
  row was decked and withdrawn the same day: Tensile's own `numBytes()` for
  complexDouble is 16, so `2 × 16 > 16` and Tensile refuses the phase at solution
  construction. `consolidate_deck.dtype_bytes` already reads that value from
  Tensile, and `tests/test_consolidate.py::TestLegalityGate::
  test_gate_catches_a_real_archived_zz_phase` locks the refusal against the
  archived deck — so the load-width half of D2 is settled by measurement and
  admits no trial. The budget half is what the boundary tile tests.
- **D3** — ZZ `128x128x8/4x4` and `128x64x8/4x4` (§8.2, never generated): the deck
  stays non-empty under either D2 reading.

No gate or verdict logic changed for any of this; the trials are *candidates*,
and the run decides. Dry-run: 246 sweep + 14 baselines + 8 trials = 268, 0 refusals.
Every candidate must pass **both** the append gate and
`consolidate_deck._is_legal`, which reads dtype bytes from Tensile itself rather
than from `BYTES_PER_ELEMENT`; `tests/test_knob_sweep.py::
test_no_emitted_candidate_passes_only_the_lenient_gate` enforces it.

*Resolved earlier (2026-10-14):* `GLVW=2` is not merely "maybe refused" — the gate now
models Tensile's shift-ptr rule in full, including the `GuaranteeNoPartialA`
escape hatch, so an *unpaired* `GLVW=2` is refused for CC/SS/HH/HPA and a no-op for
ZZ/DD. The unpaired row was removed. See §8.1 and
`oto/tensile/gates/loads.py::_glvw_for`.

---

## 10. GUI-safe prep for the 10h+ overnight run

Constraints: full Tensile benchmark runs are TTY-only and the user's to
launch. Agent work is CPU-only — deck generation, dry-run, gate checks.

1. **Deck** — `oto/tensile/family_decks.py` `FAMILY_DECKS` gains the §8.2 tiles and the
   §8.1 knob sweeps. Every entry is gated by `validate_config` at the append
   boundary, so an illegal row costs a rejection, never a crashed run.
   Emit with trials and controls:
   `python3 -m oto.tensile.knob_sweep --emit --baseline --trials`
   (dry-run default; 246 sweep + 14 baselines + 8 trials = 268, 0 refusals).
2. **Dry-run** — `oto tune --dry-run` (or
   `oto check candidates --deck <deck>.yaml`) to confirm the phase count and that
   no entry is silently dropped.
3. **Legality PoC only** — verify the new ZZ deck is non-empty after D2 lands
   (§9, D3). This is the one interaction that can empty a family.
4. **Clock hygiene** — pin the sclk level via sysfs
   (`power_dpm_force_performance_level` = `manual`, then `pp_dpm_sclk`), 25%
   warmup, L2 flush between repeats for memory-bound shapes, log median clock +
   temperature per phase, and interleave a reference kernel to detect drift.
   Full protocol: `docs/knowledge_base.md` §8.3. Without this the run repeats the F1
   artifact.
5. **Budget split** — the never-varied knobs (§8.1) are the high-yield spend;
   tile ladders (§8.2) are the second; Route E is a separate work item and gets
   no time here.
6. **Post-run read guide (corpus3 Q-E iii).** PGR 0/1/2 is measured on the
   complex winners in this run — read the winner through LDS bytes, VGPRs and
   load/wait counts, not the mode number: **0 wins** = buffering costs exceed
   overlap (consistent with issue-bound); **1 wins** = one stage suffices;
   **2 wins** = look-ahead matters on that shape (not a universal PGR=2 rule).
   APM 1-vs-2 is read through the LDS allocation diff first (cap unconfirmed).

The pass-3 brief (Q-A…Q-F) is folded; residual follow-ups are §9.4 of
`docs/research/kernel_tuning.md` and the protocol deltas are `docs/knowledge_base.md`
§8.3. The prompts themselves are archived at `archive/RESEARCH_PROMPT*.md`.

---

## 11. The 10 h+ overnight run — runbook (2026-10-16)

Everything below is CPU-verified. Real benchmarking happens in the USER's TTY,
never from this GNOME session (`docs/gfx90c_tuning_guide.md` §10.1).

### 11.1 The honest scoreboard first

Do **not** read the headline `19 WIN / 19 TIE / 0 LOSS` as "the floor is
beaten". That number grades on `agg="winner"` = **best per-kernel median**, which
is an order statistic: the arm that draws more kernels has a higher expected max.
The native arm carries ~28 configs per SS cell per run and ~143 accumulated;
ZZ's spoof arm carries 26. Re-grading the *same* data under every basis:

| basis | meaning | verdicts (38 cells now visible) |
|---|---|---|
| `winner` (report) | native best-kernel vs spoof best-kernel | **29 W / 9 T / 0 L** |
| `median` | typical native vs typical spoof | 5 L / 3 T / 22 W |
| `floor_best` | typical native vs spoof's BEST | 25 L / 3 T / 2 W |
| `strict` | native worst vs spoof best | 30 L |

**The five `median` losses are the work list.** `CC:256 −63.6 %`,
`SS:512 −46.4 %`, `DD:256 −44.6 %`, `SS:256 −17.6 %`, `HH:256 −4.3 %`. The first
three are cells where the *winner* is genuinely good (native wins them outright
on `winner`) but the surrounding 640+ accumulated kernels drag the median to
18–41 % of the winner. That is an allocation problem, not a tuning problem.

### 11.2 What changed since the last run

1. **The eight HPA contract cells are now visible to the mutator.**
   `ab_records.phase_records` keyed cells without the family dimension, so
   `HH_HPA`/`HS_HPA` kernels (typecode `HHS`/`HSS` → family `HH`) folded into the
   plain HH cells and `_pair_cells` graded **30 of 38** cells. The DB mutator was
   structurally blind to them. Fixed; now **38 cells, 29 W / 9 T / 0 L**, and
   `HH_HPA:512` reads **+118.6 %** — a 2.2× win the arm was never allowed to see.
   Every pre-fix HH-family median is contaminated and must be re-read.
2. **`FORWARD_KNOB_DOMAINS` is family-aware** (`forward_domain(family, knob)`).
   GLVW is now `S:(1,2,4)`, `H:(1,2,4,8)`, `D/C:(1,2)`, `Z:(1,)` against the
   verified 16-B global-load cap — previously every DD/CC/ZZ GLVW≥2 draw was a
   guaranteed gate refusal wasting one of five forward draws per iteration.
   `WorkGroupMapping` is `(1,2,3,4,−1,−4)` (8 is a 56-CU artefact; the negative
   I/J-swap family has never been generated). `StaggerUStride` is
   `(0,64,128,256)` because 256 silently rounds to `DepthU*bpe`.
   `AssertFree1ElementMultiple` joins `AssertFree0ElementMultiple`.
3. **The CC:256 steal batch is decked** (§0 R8): 14 candidates, all gate-legal
   through both `validate_config` and `ldspad_feasible` at 16 KB LDS/WG.
4. **Two latent crashes fixed**: `db_patterns` referenced a non-existent
   `FORWARD_KNOB_DOMAINS["GSU"]` (dead branches, now unreachable), and
   `driver.__init__` built the run dir before the registry.

### 11.3 The search strategy (from the SOTA read)

The TEVC 2022 Kernel Tuner study (arXiv:2210.01465, 26 spaces × 9 GPUs × 16
optimisers, GEMM/OpenCL on MI50): at **≤200 evaluations dual annealing wins and
Bayesian SMAC does not even beat random sampling for GEMM**; first-improvement
local search takes over at 200–800. A per-config cost of generate + assemble +
benchmark puts a 10-hour overnight at a few hundred evaluations — the low-budget
regime. So: **analytic pre-filter → hill-climb the surviving frontier → draw
diagonals last**, and no surrogate model. (arXiv 2407.11488: AMD gains ~10×
from autotuning where NVIDIA gains ~2×, and vendor-tuned configs do not
transfer — honour the SS-pads / DD-never-pads asymmetry rather than averaging.)

### 11.4 What to spend the budget on (ranked, payoff per GPU-minute)

| # | lever | cells | mechanism |
|---|---|---|---|
| 1 | `LdsPadA/B ∈ {1,2,4}` on **CC, ZZ, DD** winner geometries | CC:256, ZZ all, DD:256 | GCN LDS = 32 banks × 4 B, `bank = (addr/4) mod 32`, wave64 serviced in 8 phases of 8 lanes. The floor pads SS (110/162/55 kernels) and HH (17) but **never pads DD/CC/ZZ**, and Tensile's own `Perf/*.yaml` never enumerates pads either — a self-consistent blind spot in both the library and the recipes. |
| 2 | `AssertFree0/1ElementMultiple` = 4 (2 double, 8 half) | all | Tensile's own recipe value. Unlocks `UseSgprForGRO` — the 1-vs-2 WG/CU step on a 256-VGPR part. **Assertion: gate on exact shape divisibility and verify the first row against a reference GEMM.** |
| 3 | MacroTile shrink + `LocalSplitU` | SS:256/512, DD:256, HH:256 | 7-CU cliff: `SS 128x128x8`→4 WG/CU, `128x128x16`→2, `128x128x32`→1; `DD 128x128x16`→**1 WG/CU**. At 256³ a 128×128 tile is 4 workgroups on 7 CUs. LSU fills waves without paying the arithmetic-intensity cost of shrinking the tile. |
| 4 | `WorkGroupMapping ∈ {1,2,3,4,−1,−4}` | CC, HH_HPA, SS small | negative family never generated; 8 is a 56-CU artefact. |
| 5 | `FractionalLoad ∈ {0,1,2}`, `PGR ∈ {0,1,2}`, `PLR 0/1` | SS, CC at 2048 | the floor never emits `FractionalLoad=2` or `PGR=2`. |
| 6 | `NonTemporalA/B ∈ {0,4,8}` | SS/HH 2048+ | avoids L2 (1 MiB) pollution; floor ships 0 everywhere. |

**Do not search** `MatrixInstruction` or `DirectToLds*`: Tensile's `AsmCaps.py`
sets `HasMFMA: False` / `HasWMMA: False` for ISA (9,0,6), so
`SolutionStructs.py:3131-3134` rejects `EnableMatrixInstruction` outright, and
`DirectToLds` blocks `NLCA>1`, forces `GLVW=1` on 8/16-byte dtypes and forces
`1LDSBuffer`. Dead ends that cost search budget.

### 11.5 Deck flood — bound the population before the run

The measured distribution (both arms, folded DB):

| cell | native kernels | within 5 % of winner | median/winner |
|---|---|---|---|
| SS:256 | 684 | 4 | 18 % |
| SS:512 | 693 | 2 | 30 % |
| HH:512 | 742 | 1 | 19 % |
| CC:256 | 246 | 1 | 24 % |
| ZZ:128 | 218 | 1 | 26 % |
| SS:2048 | 668 | 10 | 58 % |

A cell whose median is a fifth of its own winner is a cell in which almost
everything measured was junk. Capping distinct configs per cell at K:

| K | configs retained | share of corpus |
|---|---|---|
| 16 | 523 | 14 % |
| 24 | 765 | 20 % |
| 32 | 1005 | 26 % |

Recommend **K = 24** for the overnight: measured over the folded DB, that
retains **765 of 3831 configs (20 %)** and **loses 0 of 35 cell winners**
(the cap is ranked by measured median, so every cell's frontier survives). `--max-fp N` on
`candidate_generator` is the round-robin knob; the run loop never applies it.

### 11.6 The command

```bash
# 1. CPU-only, from any session (safe under GNOME)
python3 -m oto check candidates --family CC --quiet   # legal, or it names the rows
python3 -m oto.harness.candidate_generator --dry-run  # prints the per-family tally
python3 -m oto preflight       # 38/38 parity, all OK

# 2. TTY only — the real run
python3 -m oto tune --budget 10 --yes
```

Sizing: `phases.yaml` plus the seed overlay is what a run builds;
`python3 -m oto check candidates --quiet` prints the live deck count and refuses
anything illegal. The last run took 13 h 14 m wall clock for 7.95 h of phase-busy
time (40 % overhead: config generation, Tensile build, queueing), so **~12–14 h**
is the honest estimate and `--budget 10` iterations of mutation on top. Judge
**within-run only**, ≥3 seeds, median, ±2 % tie band.

### 11.7 Read the results honestly

```bash
python3 -m oto.harness.kernel_db --rebuild
python3 -m oto.tools.run_census --json /tmp/opencode/post.json      # knob census + cells_resolved
python3 -m oto.runners.stage_cli --report --native-agg floor_best   # the strict basis
```

Report `agg="floor_best"` as a **co-primary** alongside `winner`: it grades the
native arm on its median, so a cherry-picked lucky kernel cannot win it.
`ab_audit.audit`'s max-raw-sample basis should be dropped — `ab_delta._stat`'s
own docstring calls `best` "seed-noisy, reference only".

---

## R42 — straggler classes and why they are stuck (2026-10-21)

The 2026-10-20 overnight run (frontier deck, §R40) landed at
**20 WIN / 18 TIE / 0 LOSS** (`run_20261018_004835` and the frontier follow-up).
The 18 ties are inside the ±16.45 % measurement band (§R36) and CC/ZZ sit at
10–31 % of their §5 bars. This section decomposes the laundry list into five
straggler classes, traces each through the database, and states the root cause
and the remaining lever. Nothing below re-derives hardware; it cites
`docs/gfx90c_theoretical_limits.md` (L), `docs/gfx90c_tuning_guide.md` (G),
`docs/research/kernel_tuning.md`, and the live corpus (`corpus_census`, `oto/tools/run_census.py`).

### R42.1 — The five classes

| class | cells | measured | §5 bar | verdict |
|---|---|---|---|---|
| **A. Complex memory/occupancy** | CC:192/256/512/1024/2048, ZZ:128/192/256/512/1024 | CC 118–347, ZZ 16.8–24.5 | 1118.7, 98.6 | **SUPERSEDED by §R47**: the bar was the BLAS-8 roof against a client-reported number (÷4), so CC/ZZ are at 80-97 % of the FMA roof and only **CC:192** is still ORANGE |
| **B. Small-cell residency** | SS:256 (412), HH:256 (763), DD:192 (76), CC:192 (118) | 36–79 % of bar | — | geometry cannot fill the machine (M2): 128³ at 256³ = 4 waves/SIMD |
| **C. Noise ties** | 18 cells (SS 3, HH 3, HPA 2, HS 2, DD 4, CC 1, ZZ 0 in the tie table) | ±0.1…+4.6 % | — | inside ±16.45 % band; need replication, not new geometry |
| **D. Unmeasured frontier** | SS/HH/HPA at 256×128/128×256 (32768 elements) | 802.2 (SS 256×128 TT16×8) | — | confounded: large tile × large thread tile; the §R40 deck separates area from register pressure |
| **E. Virgin knobs** | every family, every cell | 0 rows | — | 22 knobs with zero variance in the floor (§9.1); never separated from defaults |

### R42.2 — Class A: why CC and ZZ are stuck

**Root cause.** A complex MAC is four real FMAs (`docs/research/complex_gemm_brief.md` §1,
`KernelWriterAssembly.py:14975-14978`). The register file caps the MacroTile area at
`65536 / weight` with weight 4 (CC) / 8 (ZZ), so the largest legal tiles are
CC 128×64 (8192 elements) and ZZ 64×64 (4096 elements) — not the 16384–65536
elements the §5 bars assume. Every forwarded knob has already been probed on
those geometries at 0.83–0.98 of base (`docs/potential_configs.md` §R37/§R41), so
the gap is **not** a missing knob on the existing tile — it is the tile area
itself, which legality forbids.

**What was tried (trace).**
- CC: 17 distinct (MT,TT,VW) triples measured (`docs/results.md` §13.3); best
  346.7 @ 512³ at 64×64/4×4. Pads (LdsPadA/B {1,2,4}) measured 0.95–1.0 of
  base; PGR=0 measured 0.98; WGM8 measured 1.03; GLVW=1 measured 0.97; LSU=2
  measured 1.0 (§R37). No single knob moves CC by more than 5 %.
- ZZ: 9 distinct triples; best 24.5 @ 1024³ at 32×32/2×2. Pads on the du8 tile
  measured 0.96–1.0; PGR=0 measured 0.99. No knob moves ZZ by more than 4 %.
- The R8 steal (`CC:256` +7.8 %) was the only strict win; it landed by taking the
  floor's larger tile (64×64 vs native 32×32) — i.e. by **area**, the one thing
  the complex families cannot get more of.

**Conclusion.** Class A is not tunable within the existing tile. The two remaining
routes are (i) **restructure the GEMM** (3M/Karatsuba: 3 real GEMMs instead of 4,
`docs/research/complex_gemm_brief.md` §4–§5) and (ii) **non-atomic split-K** with a
workspace + reduction kernel (`docs/research/complex_gemm_brief.md` §9). Both are new
machinery, not config. The §5 bars for CC/ZZ should be re-derived on the
largest *legal* tile (user decision, §6 of theoretical_limits.md) so ORANGE stops
being a tuning-failure signal.

### R42.3 — Class B: small-cell residency

**Root cause.** A 256³ cube with a 128×128 tile produces 4 waves/SIMD at most;
the machine idles below 25 % residency (`docs/gfx90c_tuning_guide.md` §5 M2). The gap
between SS:256 (412) and SS:1024 (1135) **is** the residency gap.

**What was tried.** Smaller tiles (96×96/6×6, 64×64) measured 744–1039 GFLOPS on
SS:256; GSU {2,4} measured 936/740 (loses to GSU=1). HH:256 tried 32×64/4×4
(763). DD:192 tried 32×32/4×4 (76).

**Remaining lever.** `GlobalSplitU` is the only wave-fill knob legal on SS (and
DD via BufferStore). The frontier deck (§R40) carries 256×128/8×4 (32
accumulators, half the register pressure) which separates "area is bad" from
"registers ran out". WGM 2/3 (unmeasured) may improve CU–tile mapping on the
7-CU box.

### R42.4 — Class C: noise ties

**Root cause.** The measurement band is ±16.45 % (median-of-seeds, ≥3 seeds); 18
cells sit at +0.1…+4.6 %. The replication machinery does not exist:
`_should_execute_phase` skips already-passed fps, and the overlay bypass applies
only to `origin ∈ {overlay, seed_overlay}`. So a tie cannot be re-measured to
decide whether it is signal or noise.

**Remaining lever.** Add `--reseeds N` / a bypass that re-measures passed
configs N times and reports median + spread. Until that exists, treat all 18 as
ties (no action).

### R42.5 — Class D: unmeasured frontier

**Root cause.** Every tile above 16384 elements in the corpus carries TT 16×8 or
8×16 (128 accumulators), which halves residency vs the winner's 64 accumulators.
The §R40 deck (22 tiles × 4 patterns) is the clean experiment; results pending.

### R42.6 — Class E: virgin knobs (22 axes, zero variance)

**Root cause.** The floor never moves these knobs, so the mutator's draws are
confined to the same small space. The axes are listed in §9.1 of the tuning
guide with their legality status. None of them is a config today except
`LdsPadA/B`, `StaggerU/UMapping/UStride`, `AF0/1EM`, `StoreCInUnroll` (Group C,
forwarded 2026-10-09). The rest are in `NOT_FORWARDED_KNOBS`.

**Remaining lever.** Wire the most promising (1LDSBuffer, DepthULdsDivisor,
TransposeLDS, FractionalLoad, LdsBlockSizePerPad, Wave/ThreadSeparateGlobalRead,
UnrollMajorLDS, NonTemporal, MaxOccupancy, PersistentKernel, PrefetchGlobalRead=2,
StaggerUMapping, NLCA=-1, LdsPad=1, AssertFree) behind `ldspad_feasible` and
probe one row per case. **Updated 2026-10-22 (R47/R48):** of that list,
`TransposeLDS`, `UnrollMajorLDS*` and `LdsBlockSizePerPad*` are **unreachable**
(Tensile's classic path rejects them -- `SolutionStructs:2890-2892`, found by
the deck check), `LdsPad=1` is **closed** (measured, no effect), and the rest
were **wired and decked** by the R47 batch.

---

## R43 — New routes (2026-10-21)

Each route is a concrete candidate family. Routes 1–3 are new machinery (code,
not config); routes 4–8 are config-level and can be decked now.

### Route 1 — 3M (Karatsuba) split-complex for large-K CC/ZZ

**Mechanism.** Replace the 4-real-FMA complex MAC with the 3-multiply form:
3 real GEMMs + 5 matrix adds, cutting GEMM count 25 % (`docs/research/complex_gemm_brief.md`
§4–§5). MAGMA reached 79 % CGEMM / 71 % ZGEMM on Fermi with this scheme.

**When it helps.** Large K, where the O(MK+KN+MN) combine is negligible and the
three real GEMMs run near their own efficiency. On small K the combine dominates.

**Cost.** Extra passes + workspace + 3 launches; numerical stability caveat
(Higham: up to 25 % arithmetic saving but lower stability than 4M). Needs a
high-precision reference and cancellation-heavy inputs.

**Legality.** SS and DD real GEMMs are legal and fast (1119/98.6). The combine
is elementwise and LDS-free. No Tensile involvement — this is a hand-written
kernel, outside the deck.

**Deliverable.** A separate `complex_gemm_3m.py` (not Tensile) for CC/ZZ large
shapes, benchmarked against the Tensile floor. Not deckable; out of the
overnight run.

### Route 2 — Non-atomic split-K for complex (workspace + reduction)

**Mechanism.** K-partitioned GEMM: each workgroup writes its own complex partials
to a workspace; a second kernel reduces them in a fixed order (deterministic,
race-free). Cost: scratch writes/reads, second launch, reduction. For small
CC/ZZ the fill benefit may not cover it.

**Status.** New machinery (not a config). Tensile's GSU is the atomic path; this
port forwards neither `GlobalSplitUAlgorithm` nor a workspace. Needed for complex
because GSU>1 is gate-refused on gfx90c.

**Deliverable.** `splitk_complex.py` + reduction kernel; benchmark on CC:512 and
ZZ:512 only first.

### Route 3 — Occupancy/register tiling search (Class A)

**Mechanism.** Enumerate all legal (MT, TT, VW, DU) triples through the real
gate (already done: CC max 8192, ZZ max 4096). For each, compute waves/CU and
VGPR. Select the 3 with highest predicted waves/CU at the target shape, then
benchmark. Add PGR=0, LdsPad ∈ {1,2,4}, NLCA on 3-load tiles, WGM ∈ {1,2,3,4,-4},
LSU=2, and AssertFree ∈ {2,4} on top.

**Status.** Config-level; can be decked. The §R40 frontier deck already covers
the area frontier; this route adds the occupancy-optimised combinations on the
*complex* legal tiles (64×64/4×4 for CC, 32×32/2×2 for ZZ).

### Route 4 — Virgin knob sweep (Class E)

**Mechanism.** One row per (winner geometry, knob value) for each virgin knob,
gated by `ldspad_feasible` (or a new gate). The cheapest first pass is the
knobs already in the forward map but never drawn: `LdsPadA/B = 1`,
`StaggerUMapping ∈ {1,2}`, `PrefetchGlobalRead = 2`, `NLCA = -1`,
`MaxOccupancy ∈ {8,16,32}`. Then wire the `NOT_FORWARDED` knobs
(`1LDSBuffer`, `DepthULdsDivisor`, `TransposeLDS`, `FractionalLoad`,
`LdsBlockSizePerPad`, `Wave/ThreadSeparateGlobalRead`, `UnrollMajorLDS`,
`NonTemporal`, `PersistentKernel`) one at a time behind new gates.

**Status.** Partially decked (LdsPad, StaggerU). Needs config_writer + gate work
for the NOT_FORWARDED set.

### Route 5 — Replication (Class C)

**Mechanism.** Re-measure the 18 ties N times and report median + spread. If the
spread is < ±5 %, the tie is real; if > ±10 %, it is noise.

**Status.** Needs `--reseeds N` in the driver and a bypass of
`_should_execute_phase` for `origin ∈ {replication}`. New machinery.

### Route 6 — Non-temporal loads (memory-bound cells)

**Mechanism.** `NonTemporalA/B/C/D ∈ {1,2,3}` (glc/slc) on the C operand
read-modify-write and on single-K-pass kernels. On a 1 MB L2, pollution control
may matter more than on discrete parts.

**Status.** Config-level; one row per (winner, NT value) on SS:256/512 and
CC:512.

### Route 7 — L2 traversal order (WGM 2/3, negatives)

**Mechanism.** WGM 1/4/8/−4/−1 measured; 2 and 3 are unmeasured (§R40 deck
carries them). On a 7-CU box with a 1 MB L2, the traversal order of the tile
grid affects locality. The negative (I/J-swap) family is geometrically neutral
on square tiles but may help on rectangular ones.

**Status.** Decked (§R40), pending measurement.

### Route 8 — AssertFree on more geometries (Class A/B)

**Mechanism.** `AssertFree0/1ElementMultiple ∈ {2,4,8}` drops edge predication
and unlocks the full load width at 2× area. Measured on 8 winners; extend to
the complex legal tiles and the small-cell tiles.

**Status.** Decked (§R40), pending measurement.

---

## R44 — Legality improvements (2026-10-21)

The following illegal/placeholder configs have been observed or are at risk:

1. **NLCA = -1** is legal in Tensile (least-coalesced regime) but has never been
   emitted. Add it to `FORWARD_KNOB_DOMAINS["NLCA"]` and to the db_knobs domain.
   Gate: `gates/loads.py::_nlca_stage` already handles -1.
2. **LdsPad = 1** is in the forward domain but the corpus census shows only
   {0,2,4} measured (§9.1). Add 1 to the pad rows.
3. **PrefetchGlobalRead = 2** needs 2× LDS; gate by `ldspad_feasible` with the
   doubled footprint. Add a dedicated check.
4. **1LDSBuffer = 1** requires `ScheduleInnerAccuracy ∈ {2,3}`; the writer must
   emit both or neither. Add a coupled-forwarding rule like StaggerU.
5. **DepthULdsDivisor ∈ {2,4}** requires `ScheduleInnerAccuracy=3` +
   `TransposeLDS=1` + `PrefetchGlobalRead≠2` + `DirectToLds=0`. Add a coupled
   gate.
6. **AssertSummationElementMultiple** asserts K and must divide by GSU; add the
   `ASEM % GSU == 0` check to the occupancy gate.
7. **Z LDS byte count** (§6.1 of theoretical_limits.md) — the gate uses 8 bytes
   where Tensile uses 16. This is the most permissive family gate; correcting it
   would refuse 67 kernels including the ZZ winner. Decision pending (user).

Tests to add: `tests/test_legality_virgin.py` pinning each new gate; extend
`tests/test_occupancy_model_lds.py` with the new rules.

---

## R45 — Candidate batch for the next overnight run (2026-10-21)

New rows to add to `candidate_rows.py` (PLAN_BATCH) for the next 10 h+ run:

- **LdsPad=1** on every winner geometry (CC, ZZ, SS, HH, DD) — 5 families × 5
  pads × 4 patterns ≈ 100 rows.
- **NLCA=-1** on the 3-load tiles (96×96×16, 64×64×8 for CC, 32×32×8 for ZZ)
  — ≈ 12 rows.
- **PrefetchGlobalRead=2** on SS:512/1024 and HH:512/1024 (gated) — ≈ 8 rows.
- **StaggerUMapping ∈ {1,2}** on CC/ZZ winners — ≈ 8 rows.
- **MaxOccupancy ∈ {8,16}** on CC/ZZ winners — ≈ 8 rows.
- **NonTemporal=1/2/3** on C operand for SS:512 and CC:512 — ≈ 12 rows.

Total new rows ≈ 148, bringing the deck to ~850 candidates. At 78 s/executed
phase ≈ 3.2 h for the new rows alone, plus the §R40 frontier rows still pending.

---

## R46 — Questions for a read-only research agent (only if docs cannot answer)

The docs ecosystem answers everything above. The following remain genuinely
unanswered and are the only items worth external research:

1. Is there a published GCN5 (gfx900/90c) complex-GEMM tile optimum, or any
   guidance on register blocking for 1/16-rate FP64 on Wave64? (No such
   publication found — `docs/research/complex_gemm_brief.md` §8/§11 mark [CHECK].)
2. Does `NonTemporal` (glc/slc) actually bypass L2 on gfx90c, or only L1? The
   emitted ISA modifiers need verification.
3. What is the real L2 cache associativity/line size on gfx90c (1 MB, but
   unknown associativity) — affects traversal-order (WGM) predictions.
4. Is there a published optimal `WorkGroupMapping` for small CU counts (≤8) on
   GCN? All published guidance assumes ≥32 CUs.
5. Does `1LDSBuffer=1` with `ScheduleInnerAccuracy=2` actually halve LDS on
   gfx90c, or does Tensile ignore it on the assembly path?

---

## R47 — the straggler list, re-derived from the corpus (2026-10-21, 2nd-opinion pass)

§R42 answered the user's "same losers again" complaint by classifying the
stragglers into five classes and proposing eight routes. Three of those classes
were **wrong**, and two of the routes were aimed at a bar that did not exist.
This section is the corrected reading, with the evidence for every claim and
the batch spec for the next run.

**The three findings that change the plan.**

1. **CC and ZZ were never behind — they are at the hardware roof.** The report
   scored complex cells against the FP32/FP64 *BLAS-8* peaks (1613 / 101) while
   the Tensile client reports complex GEMMs at **2 flops per complex MAC** (it
   charges `2 * packing` flops, and packing is 1 for complex types --
   `ContractionProblem.cpp:1108`, `DataTypes.hpp:177`). Every benchmark CSV
   proves it: `TotalFlops == 2*M*N*K` for CC, ZZ, SS and DD alike. A complex MAC
   is *executed* as four real FMAs = 8 BLAS flops, so a reported complex GFLOPS
   is 1/4 of its BLAS-8 value, and the report divided every complex utilisation
   by four. The truth: **CC runs at 80-97 % of the FMA roof and ZZ at 96-97 %**
   (three independent checks in `docs/gfx90c_theoretical_limits.md` §5.2). The
   ORANGE list shrinks from **12 cells to 3**: `SS:256`, `HH:256`, `CC:192`.
   §R42.2 (Class A) and §R43 Routes 1-3 (3M/Karatsuba, non-atomic split-K) are
   **struck**: they were answers to a mis-scaled bar.
2. **Most ties carry no kernel difference at all.** `oto.harness.cell_resolver
   --taxonomy` groups the 38 cells by how far the two arms' winning configs are
   apart. Of the 15 ties: **9 are `identical`** (the native and floor arms run
   the *same* config -- the vendor's gfx900 tile transferred unchanged, which is
   the user's "you didn't alter a single bit" reading, confirmed), 4 are
   `no-floor` (the HPA columns ship no floor arm, so the "tie" is against a
   reference the report cannot resolve), 1 is `near` and 1 is `retile`. Only
   **two** ties are a real kernel difference, and both deltas (+2.2 %, +2.3 %)
   are inside the environment band.
3. **The environment band is 17.5 points wide, and the verdict band is 5.** On
   the 16 `identical` cells -- same binary in both arms -- the delta ranges
   **+1.1 % to +18.6 %**. That spread is *pure measurement* (different day,
   different clock, different thermal state), and it is what a tuning win has
   to clear. The floor arm carries **no clock telemetry at all** (it was
   measured on 2026-10-03; `spoof_clock_coverage` is 0.0 in every cell), so the
   A/B cannot be clock-corrected. The "wins" on identical cells (+18.6 % at
   CC:2048) are environment, exactly like the ties.

**So the 17-hour run did not fail to find tuning wins -- it could not have.**
It was chasing deltas an order of magnitude smaller than the noise of the
measurement protocol, on cells that were already at 85-97 % of the roof.

### R47.1 The classes, corrected

| class | cells | the truth | the lever |
|---|---|---|---|
| **A. Complex (CC/ZZ)** | 10 cells | **dissolved.** CC 80-97 % and ZZ 96-97 % of the FMA roof; the "ORANGE" was a 4x unit error. The one exception is **CC:192** (29 % of the roof), which is wave-fill-limited like the small SS/HH cells | none for CC:512+; CC:192 only |
| **B. Small-cell residency** | `SS:256` 25.5 %, `HH:256` 23.7 %, `CC:192` 29.3 % of the roof | **real and physical.** The problem does not fit the machine: a 256³ cube with a 128×128 tile is 4 workgroups for 7 CUs (57 % fill), and the cell then runs at 25-37 % of the roof. Every knob that adds waves (GSU 2/4/8) measures **40-61 GFLOPS against 412** -- the atomic reduction costs more than the wave fill wins | tile/pattern that multiplies the workgroup count without shrinking the tile: **smaller MT with the same TT** (SS 64×64/4×4 = 16 workgroups), and the WGM/traversal axis |
| **C. The ties** | 15 cells | **not a tuning problem.** 9 identical + 4 no-floor; the identical-cell spread is 17.5 points | **the measurement protocol**, not the kernel: re-measure the floor in-session, clock-normalise both arms, and report the environment band beside every verdict |
| **D. The frontier** | 256×128 / 128×256 tiles | **the control was impossible.** 256×128 at TT 8×4 is 1024 threads, where the file leaves 64 VGPRs/thread and the thread tile emits 77 -- Tensile's error 4. The 8 SS phases of the 2026-10-20 run died exactly there. The legal 256×128 (TT 8×8, 512 threads) was measured: **802 vs 1187** -- the area is worse, not better | none; the frontier is closed on this part |
| **E. Virgin knobs** | 22 axes | **partly never varied at all**: `StaggerU=0` was *refused* by a gate that read Tensile's FORCE as a reject (14 deck rows, 98 shape-records, zero measured); `TransposeLDS` and `NonTemporalC/D` were *declared forwarded but never emitted* (silent placebos). Both are fixed now | the real virgin batch is §R47.4 |

### R47.2 Route 1 (new, first): make the A/B able to see a win

Everything else is downstream of this. Today the acceptance verdict compares a
corpus measured on 2026-10-20/21 against a floor measured on 2026-10-03, with
no clock on the floor side (`spoof_clock_coverage` 0.0 in all 38 cells) and a
+/-5 % verdict band, while the same binary varies 17.5 points between the two
arms.

- **Re-measure the floor in the same session.** `python3 -m oto bench --refresh`
  re-benchmarks the shipped gfx900 kernels into a fresh `gfx900_ref_*` run, with
  telemetry, next to the native arm. The driver's auto loop already attempts
  the reference chain; the last run's report says the floor re-measurement was
  *declined*, which is why the run is marked PROVISIONAL. **Declining it is
  what makes the verdicts unreadable** -- it is the one thing this project can
  still get for free.
- **Clock-normalise both arms.** The native arm's busy-clock median in the
  2026-10-20 run was 1650 MHz (per-phase median 1624 MHz) against the 1800 MHz
  reference -- a 8-10 % systematic handicap on the native side. With telemetry on
  both arms the existing `ab_delta` clock correction can do its job (it needs
  >= 50 % coverage per arm; the native arm had 28.6 %).
- **Report the environment band.** `cell_resolver --taxonomy` prints it; the
  acceptance report should carry the identical-config spread next to the
  verdict band, so a "WIN" on an identical cell is visibly an environment win.

### R47.3 Route 2: the three cells that really are behind

`SS:256` (412 GFLOPS, 25.5 % of the roof), `HH:256` (763, 23.7 %) and
`CC:192` (118 reported = 473 BLAS-8, 29.3 %) are the only cells with real
headroom. The corpus answers most of it (best seed-median per geometry,
`kernel_db.json`):

| cell | winner | MT | TT | workgroups | nearest losers |
|---|---|---|---|---|---|
| SS:256 | 412.1 | 96x96 | 6x6 VW2 DU16 | 9 | 64x64/4x4 = 217.3, 128x128/8x8 = 110.0, 32x64/4x4 = 177.3 |
| HH:256 | 763.4 | 32x64 | 4x4 VW4 DU16 | 32 | 64x64/4x4 = 199.2, 32x32/4x4 = 201.5, 128x128/8x8 = 195.2 |
| CC:192 | 118.2 | 64x64 | 4x4 VW2 DU8 | 9 | 32x32/4x4 = 113.8, 64x32 = 43.5 |
| DD:192 | 77.8 | 32x32 | 2x2 VW2 DU8 | 36 | 32x32/4x4 = 58.9, 64x64/4x4 = 62.3 |

**What the table says.** HH:256's winner has *twice* the workgroups of its
nearest loser (32 against 16) and is 3.8x faster -- the cell is
wave-quantization-limited and the tile that produces more workgroups wins. SS:256
is the opposite trade: 96x96 has *fewer* workgroups (9) than 64x64 (16) and
still wins 1.9x, because S's 4-byte elements make the LDS traffic per FLOP
twice H's and the bigger tile buys the register blocking back. CC:192's 64x64
wins over 32x32 by 4 % -- the same workgroup-count trade, and at 9 workgroups
for 7 CUs the critical path is 2x the ideal.

**So the lever for the small cells is the workgroup count at a fixed FMA:LDS
ratio, and the two knobs that move it are the tile and the thread tile.**
`oto.harness.coverage_map` lists what is left: for SS:256 the *legal* 96x96
tile has never been measured with any thread tile other than 6x6 (4x6, 6x4,
6x8, 8x6 are legal, unmeasured, and all neighbours of the 412 winner). That is
the local minimum the map exists to find: the neighbourhood is fast and the
point itself is untried. Coverage across the deck is 8-13 % of the legal
geometry space (419 legal geometries for SS, 205 for CC, 302 for DD, 52 for
ZZ; 15-54 measured per cell) -- the corpus is a thin sample of a large legal
space, which is the quantitative form of "we are stuck in local minima".

**What is NOT the answer:** GlobalSplitU. Measured on SS:256, GSU 2/4/8 give
**40-61 GFLOPS against 412** -- the atomic C reduction costs far more than the
wave fill wins, so the split-K route is dead as a *config* route on this part.
A non-atomic split-K needs a workspace and a second kernel (new machinery),
and its ceiling is the 2x fill of CC:192.


### R47.4 Route 3: the virgin batch that is actually virgin now

With the placebos fixed (§R47.1 class E), these axes have *never* been measured
on this part and are legal:

| knob | values | on which cells | why it might move |
|---|---|---|---|
| `StaggerU=0` | 0 | every winner | the store stagger is off: on a 1 MB L2 with 7 CUs the 56-CU-tuned stagger may be spreading the wrong way. **Never measured** (the gate refused it) |
| `TransposeLDS=-1` | -1 | SS/HH/DD/CC/ZZ winners | **STRUCK 2026-10-22: unreachable.** The deck check asked Tensile and it refused: `-1` forces `UnrollMajorLDS`, and the classic (VALU) path rejects that outright ("didn't support UnrollMajorLDS in VALU mode yet", `SolutionStructs:2890`). `1` is the MFMA path, which gfx90c does not have. The whole unroll-major-LDS family (`UnrollMajorLDS*`, `LdsBlockSizePerPad*`, `TransposeLDS`) is therefore **unreachable on this part**, not virgin. The gate now refuses both values |
| `NonTemporalC/D` | 1, 2, 4 | SS:512/1024, CC:512, HH:1024 | glc/slc on the C operand: L2 pollution control on a 1 MB L2. **Never measured** (the knob was never emitted) |
| `LdsPadA/B` | 1, 2, 4 | every winner | bank conflicts on 8/16-B complex elements. Measured 0.95-1.0 of base -- closed |
| `PrefetchGlobalRead=2` | 2 | SS:512/1024, HH:512/1024 | 2-deep global prefetch: more latency hiding at the cost of LDS. Legal on the 64 KB LDS only where the doubled tile fits (gated) |
| `NLCA=-1` | -1 | 3-load tiles | least-coalesced regime. Measured once, no effect |
| `MaxOccupancy` | 16, 32 | every winner | Tensile reserves LDS to *limit* occupancy; the opposite of what this machine wants -- but it also caps the workgroups per CU, which may be the residency lever at the small cells |
| `StaggerUMapping` | 1, 2 | every winner | the swizzle's *mapping* (how the offset is applied) is a separate knob from the stride and has never been varied |
| `FractionalLoad` | 2 | every winner | ragged-edge loads; no effect on square cells |
| `WorkGroupMapping` | 2, 3, -1, -4 | SS:512/1024, HH:1024/2048, CC:512/1024, DD:1024 | the traversal order of the tile grid on a **7-CU** part: the gfx900 configs assume 56 CUs. This is the most gfx90c-specific knob in the deck |

Every one of these is a *config*, not new machinery, and every one is now
verified to reach Tensile (`oto.tensile.config_writer.FORWARDED_KNOBS` is
pinned to the fork surface by
`tests/test_writer_forwards_sweep_knobs.py`, which is what caught the
`TransposeLDS` placebo).

### R47.5 Route 4: what is struck, and why

- **3M / Karatsuba for complex** (§R43 Route 1): struck. At 80-97 % of the roof
  the 25 % instruction saving cannot be cashed in, and the O(MK+KN+MN) combine
  is pure overhead at these sizes.
- **Non-atomic split-K for complex** (§R43 Route 2): struck as a *near-term*
  route. The atomic GSU path is measured at 40-61 GFLOPS against 412 on
  SS:256, so the reduction cost dominates; a non-atomic split-K needs a
  workspace and a second kernel -- new machinery, and the only cell that could
  use it (CC:192) is worth 2x at most.
- **"Steal the gfx900 config and tweak it"** (§R26/§R30): still refused, and
  now with a *measurement* reason rather than a taste reason: the tied cells
  already run the floor's own config (9 identical cells), so there is nothing
  left to steal -- and the ones that differ are already at 85-97 % of the roof.
- **"Wider MacroTile"** (§R40): closed. The 256×128/128×256 control is illegal
  at 1024 threads (error 4), and the legal 256×128 measures 802 vs 1187.

### R47.6 Questions for a read-only research agent (only what the docs cannot answer)

§R46's five stand. Two more, and one of §R46's is now moot:

1. **(unchanged)** Is there a published GCN5 (gfx900/90c) complex-GEMM tile
   optimum, or guidance on register blocking for 1/16-rate FP64 on Wave64?
2. **(unchanged)** Does `NonTemporal` (glc/slc) actually bypass L2 on gfx90c,
   or only L1?
3. **(unchanged)** What is the real L2 associativity/line size on gfx90c?
4. **(unchanged)** Is there a published optimal `WorkGroupMapping` for small
   CU counts (<= 8) on GCN? All published guidance assumes >= 32 CUs. **This is
   the one question that matters most now**: WGM is the most gfx90c-specific
   knob in the deck and the corpus has 1/4/8 measured.
5. **(unchanged)** Does `1LDSBuffer=1` with `ScheduleInnerAccuracy=2` halve LDS
   on gfx90c, or does Tensile ignore it on the assembly path?
6. **(new)** For a wave-quantization-starved cell (a 256³ GEMM on 7 CUs), is
   there a known-good way to recover the missing waves on GCN5 -- a persistent
   kernel, a stream-K decomposition, or a two-tile schedule -- given that
   Tensile's GSU path is atomic and the atomics cost more than the fill wins?
7. **(new)** What is the published guidance on **measuring** GEMM kernels on a
   small, thermally-limited APU: how many repeats, what clock normalisation,
   and what inter-run variation should be treated as noise? The project is
   currently using a +/-5 % verdict band on a measurement whose run-to-run
   spread on identical binaries is 17.5 points, and the answer decides whether
   the next run can produce a single trustworthy WIN.

### R47.7 The batch for the next overnight run

Ordered by expected value, not by novelty:

1. **WGM 2/3/-1/-4 on the 7-CU tile grid** (SS:512/1024/2048, HH:1024/2048,
   CC:512/1024, DD:1024/2048) -- the only axis where the gfx900 floor is
   *structurally* wrong for this part.
2. **The floor re-measurement** (`oto bench --resume`) so the verdicts can be
   read at all.
3. **`StaggerU=0`, `TransposeLDS=-1`, `NonTemporalC/D`, `MaxOccupancy`,
   `StaggerUMapping`** on the winner geometry of every family -- the axes that
   have never actually been varied.
4. **The three small cells** re-measured with the *smaller* tiles the corpus
   says are better (SS 64×64/4×4, HH 64×64/8×8, CC 64×64 with WGM 2/3), so the
   cell's winner is chosen on equal footing with the 128×128 row.
5. **Nothing on CC:512+ and ZZ:512+** -- they are at 80-97 % of the roof.

Rows 1 and 3 are configs; row 2 is a protocol change; row 4 is a re-measure of
configurations that already exist in the corpus.

---

## R48 — the three remaining ORANGE cells, triaged (2026-10-21)

With the complex accounting corrected (§R47, `docs/gfx90c_theoretical_limits.md`
§5.2), the ORANGE list is **three cells**: `SS:256` (36.8 % of the ceiling),
`HH:256` (31.0 %) and `CC:192` (42.3 %). This section triages each one, with
the arithmetic that says how much is actually reachable and which config gets
it. The method: **the same binary at a shape that fills the machine** is the
control. A kernel that is merely "bad" would score badly at every size; a
kernel that is *fine* and *starved* scores badly only where the problem does
not fill 7 CUs.

### R48.1 The control experiment

| family | geometry | 192³ | 256³ | 512³ | 1024³ | 2048³ | 4096³ |
|---|---|---|---|---|---|---|---|
| SS | 96×96 6×6 vw2 | 341.8 | **412.1** | 682.4 | 921.9 | 895.7 | 981.4 |
| HH | 32×64 4×4 vw4 | – | **763.4** | 564.9 | 1304.4 | 1188.2 | 1201.3 |
| CC | 64×64 4×4 vw2 | **118.2** | 228.8 | 322.0 | 344.0 | 346.7 | – |

**The kernels are not bad.** The SS:256 winner scores 981 GFLOPS (61 % of the
roof) at 4096³; the HH:256 winner scores 1304 at 1024³; the CC:192 winner
scores 347 at 2048³. Each is a *good* kernel that the small shape cannot feed.

### R48.2 What the small shapes cost, exactly

For a tile `mt×mt` on a cube of side `S` on 7 CUs:

- workgroups `W = ceil(S/mt0) · ceil(S/mt1)`; waves `= ceil(W/7)`;
- **fill efficiency** `= W / (waves · 7)` (how evenly the waves fill the CUs);
- **edge waste** `= (ceil(S/mt0)·mt0 · ceil(S/mt1)·mt1) / S²` (a tile that does
  not divide the shape computes the corners twice);
- the bound below is *the same kernel's* big-shape number, scaled by fill and
  de-scaled by waste.

| cell | tile / thread tile | W | waves | fill | waste | bound | measured | % of bound |
|---|---|---|---|---|---|---|---|---|
| SS:256 | 96×96 / 6×6 | 9 | 2 | 64 % | 1.27 | 498 | **412.1** | **83 %** |
| SS:256 | 64×64 / 4×4 | 16 | 3 | 76 % | 1.00 | 922 | 217.3 | 24 % |
| SS:256 | 128×128 / 8×8 | 4 | 1 | 57 % | 1.00 | 691 | 110.0 | 16 % |
| HH:256 | 32×64 / 4×4 | 32 | 5 | 91 % | 1.00 | 1193 | **763.4** | **64 %** |
| HH:256 | 64×64 / 4×4 | 16 | 3 | 76 % | 1.00 | 1967 | 199.2 | 10 % |
| HH:256 | 32×32 / 4×4 | 64 | 10 | 91 % | 1.00 | 2361 | 201.5 | 9 % |
| CC:192 | 64×64 / 4×4 | 9 | 2 | 64 % | 1.00 | 223 | **118.2** | **53 %** |
| CC:192 | 32×32 / 4×4 | 36 | 6 | 86 % | 1.00 | 297 | 113.8 | 38 % |
| CC:192 | 32×32 / 2×2 | 36 | 6 | 86 % | 1.00 | 297 | 32.7 | 11 % |

Two readings fall out of the table:

1. **The cell's winner is already near its own bound** (83 % on SS:256), so the
   "36.8 % of the ceiling" is mostly *physics*, not a bad kernel: a 256³ GEMM
   cannot keep 7 CUs busy (9 workgroups for 7 CUs) and 96 does not divide 256.
2. **The losers lose for a different reason than the winner.** SS:256's
   64×64 tile has the *better* fill (76 %) and no waste, and still scores 24 %
   of its bound: its FMA:LDS ratio is 2.0 per float against the winner's 3.0,
   because 4×4 accumulators per thread fetch 4+4 floats. The 128×128 tile has
   the best ratio (4.0) and only 4 workgroups — 57 % fill — and scores 16 % of
   its bound. **The small cells want a large tile AND many workgroups, and
   those two wants fight**: the tile is bounded by the register file and by
   the wave count (a 64×64 tile at 4×4 is 256 threads = 4 waves; at 8×8 it is
   64 threads = 1 wave, which the corpus measured at 81 GFLOPS -- too few
   waves to hide anything).

### R48.3 What each cell can still win, and the config that wins it

| cell | reachable | the route | the configs (R48 batch) |
|---|---|---|---|
| **SS:256** | 412 → ~460-500 (1.1-1.2x) | keep the 96×96 tile (the fill and the waste are already paid for) and raise the **register blocking** inside it: 8×6 and 6×8 lift the FMA:LDS ratio from 3.0 to 3.4 per float at the same workgroup count | 96×96/8×6, 96×96/6×8 (DU8 and DU16), 96×96/4×6 |
| **HH:256** | 763 → ~950-1100 (1.25-1.45x) | keep the 32 workgroups (91 % fill, no waste) and raise the register blocking: 8×4 and 4×8 lift the ratio 2.0 → 2.67; and probe the **transposed tile** 64×32/4×8 (same 32 workgroups, a different wave layout) | 32×64/8×4, 32×64/4×8, 64×32/4×8, 64×32/8×4, 32×64/4×4 in the TT pattern |
| **CC:192** | 118 → ~160-180 (1.4-1.5x) | the fill is the binding term (9 workgroups, 64 %), so **more workgroups**: 32×64 (18) and 64×32 (24) at the winner's register blocking, plus the other thread tiles of 64×64 | 32×64/4×4, 64×32/4×4, 64×64/4×2, 64×64/2×4, 64×64/4×8, 64×64/8×4, 64×64/4×4 at DU16 |

The corpus has **never measured any of these 17 geometries on these three
cells** (checked against `kernel_db.json`); the coverage map lists them as the
top unexplored neighbours of each cell's winner. They are the whole of the
remaining headroom on the three ORANGE cells, and they cost 17 phases.

**What is NOT the answer: GlobalSplitU.** Measured on SS:256, GSU 2/4/8 give
**40-61 GFLOPS against 412**: the atomic C reduction costs far more than the
wave fill wins, on this part. And a non-atomic split-K (workspace + a second
kernel) is new machinery for a ≤1.5x gain on one cell. The one thing that
*would* fix the small cells is a **persistent / stream-K schedule** -- a
workgroup that walks several tiles so the machine is never idle -- and Tensile
exposes neither on the gfx90c path (`PersistentKernel` is in
`NOT_FORWARDED_KNOBS`, `StreamK` is not forwarded either).

### R48.4 The steal route, settled by measurement

The request was: for the *worst* native losers, take the gfx900 winner and
adapt it to gfx90c. The floor's own numbers on the three ORANGE cells:

| cell | floor best | native best | ratio |
|---|---|---|---|
| SS:256 | 124.3 | 412.1 | native **3.3x better** |
| HH:256 | 202.0 | 763.4 | native **3.8x better** |
| CC:192 | 43.2 | 118.2 | native **2.7x better** |

The floor's gfx900 configs are *worse* on exactly the cells that are behind,
because they were tuned for 56 CUs and a 1-D raster: on a 7-CU part with a
256³ problem they lose 3-4x. There is nothing to steal **into** these cells.
And on the cells where the floor *is* competitive (the big ones), the native
already runs the floor's own config (the nine `identical` ties, §R47) -- there
is nothing left to steal there either. **The steal route is closed by
measurement, not by taste**; the only "steal" that survives is the *tile shape*
the floor uses, which the corpus has already swept.

### R48.5 The ties, one by one

From `cell_resolver --taxonomy` (the gap is how far the two arms' winning
configs are apart):

| cell | native | floor | delta | gap | roof (theoretical) | reading |
|---|---|---|---|---|---|---|
| CC:512 | 322.0 | 308.4 | +4.4 % | identical | 79.9 % | environment, not tuning |
| DD:768 | 94.7 | 91.6 | +3.4 % | identical | 93.8 % | environment |
| DD:1024 | 94.1 | 91.7 | +2.6 % | identical | 93.2 % | environment |
| DD:1365 | 89.1 | 87.2 | +2.2 % | **retile** (32×32 vs 64×64) | 88.2 % | a real difference, inside the band |
| DD:2048 | 98.8 | 96.6 | +2.3 % | **near** (vw2 vs vw1) | 97.9 % | a real difference, inside the band |
| HH:1024 | 2581.9 | 2548.5 | +1.3 % | identical | 80.0 % | environment |
| HH:2048 | 2670.9 | 2575.2 | +3.7 % | identical | 82.8 % | environment |
| HH:4096 | 2749.3 | 2662.0 | +3.3 % | identical | 85.2 % | environment |
| HH_HPA:1024 | 1454.8 | 1445.5 | +0.6 % | **no floor** | 90.2 % | nothing to compare against |
| HH_HPA:2048 | 1388.0 | 1381.1 | +0.5 % | **no floor** | 86.0 % | nothing to compare against |
| HS_HPA:1024 | 1429.7 | 1428.7 | +0.1 % | **no floor** | 88.6 % | nothing to compare against |
| HS_HPA:2048 | 1388.9 | 1344.2 | +3.3 % | **no floor** | 86.1 % | nothing to compare against |
| SS:768 | 1108.2 | 1095.9 | +1.1 % | identical | 68.7 % | environment |
| SS:1365 | 1114.5 | 1069.8 | +4.2 % | identical | 69.1 % | environment |
| SS:2048 | 1168.3 | 1151.3 | +1.5 % | identical | 72.4 % | environment |

Read the "identical" rows as a *measurement* of the protocol, not of the
kernels: the two arms run the same binary and still differ by +1.1 % to
+4.4 %, and across the sixteen identical cells the spread is **17.5 points**
(+1.1 % to +18.6 %). A verdict band of ±5 % is therefore narrower than the
protocol's own noise: **a "WIN" on an identical cell is an environment win,
and a "TIE" is an absence of evidence.** The fix is the protocol (re-measure
the floor in-session, clock-normalise both arms -- §R47.2), not a new kernel.

The two cells with a *real* difference (DD:1365, DD:2048) are both at 88-98 %
of the FP64 roof, where the FP64 pipe is already the limit: DD is at 97.9 % of
its theoretical peak on DD:2048. There is no 5 % to find there.

### R48.6 The coverage graphs: the picture of the problem space

`python3 -m oto.harness.coverage_graph` draws the corpus's coverage of the
legal geometry space: one SVG per contract cell (plus an index page in
`gfx90c_results/analysis/coverage/`), the space projected onto (macro-tile area
x accumulators per thread), the measured part painted with the value it
reached, the legal-but-unmeasured part hatched, the local maxima ringed green
and the local minima ringed red. No dependency: the SVG is written by hand.

The picture says three things the numbers do not:

1. **The legal space is a band, not a box.** A big tile is only legal with
   many accumulators per thread (the register file), and a small tile only with
   few (the LDS and the load structure). The corpus has measured a **thin strip
   along the middle of that band**; the hatched regions above and below it --
   87 % of the space on SS, 92 % on HH and DD, 88 % on CC -- have never been
   visited. The "the deck already covers the space" feeling is exactly this
   strip.
2. **The traps sit inside the strip.** A red ring is a measured bucket whose
   measured neighbours are all faster. On SS:512 the 4k/8-accumulator bucket is
   a trap (every neighbour is 2-3x faster) -- the search keeps returning to it
   because it is *legal and different*, not because it is good.
3. **The peaks are on the band's edge.** The green rings sit where the legal
   space narrows: the 2k/32-accumulator bucket on SS:512 is a peak (a small
   tile, a modest register footprint) and it is the configuration a
   wave-quantization-limited cell wants (SS:256's winner, §R48.3, is exactly
   that kind of peak).

The exact per-cell numbers (legal / measured / unexplored, peaks, traps) are
the tool's text output and the index page's table; the two-dimensional
picture is what makes "86 % unexplored" mean something.

### R48.7 The batch for the next overnight run

1. **The 17 R48 rows** (the three ORANGE cells' untried geometries) -- the only
   rows that can move a graded cell.
2. **The R47 batch** (WGM 2/3/-1/-4, StaggerU=0, TransposeLDS=-1,
   NonTemporalC, MaxOccupancy, StaggerUMapping) -- the axes that have never
   been varied on the *tied* cells, where the tie is environment today and a
   real win needs a different binary.
3. **Nothing on CC:512+ and ZZ:512+**: 80-97 % of the FMA roof, no headroom.

---

## R50 — like-for-like: the verdict table is protocol-mixed, three wins are artefacts

### R50.1 The protocol split, proven same-config-same-client

The native arm's per-cell "winner" numbers come from two different client
invocations, and the A/B grades native (say, single-problem) against a floor
that only ever ran the other way:

* **single-problem phases** — `ClientParameters.ini` is the identical file
  (`num-benchmarks=8`, `num-warmups=0`, `num-enqueues-per-sync=1`,
  `num-syncs-per-benchmark=1`, `use-gpu-timer=True`, `sleep-percent=50`)
  with a **1-row problem list**: `phase_auto_0_S_256x256x256_42` (run 09-20)
  and the 10 iso phases of run_20261008_005217 measured the 256-cell kernels
  cold-start-to-cold-start, 8 back-to-back reps.
* **family-protocol phases** — the same INI with a **5–8-row problem list**
  (`ProblemSizes` = the contract shape list); every-floor phase and every
  `phase_cand_*`/`phase_ss_*` deck phase since 10-06.

Same config evidence, three independent:

1. SS 96x96x16/6x6/VW2/DU16/WGM8, within run_20260920_235815: **412.1** med in
   its single-problem phase, **98.5** med in the family phase — 4.18x, same
   binary, same process settings. (`00_Final.yaml` diff of the draft _42 kernel
   vs the modern deck kernel: only `WorkGroupMapping 8 vs 4` differs.)
2. HH 32x64x16/4x4/VW4/DU16 (WGM4): **763.4** single-problem (10-08_005217)
   vs **188.9 / 206.5 / 194.0** family (09-20 / 10-06 / 10-22) — 3.7–3.9x.
3. HH_HPA 128x128x8/8x8: **853.4** single (10-15) vs **440.8–537.7** family
   (10-06, 10-22) — 1.6–1.9x; HS_HPA 128x128x8: **820.4** vs **427.8**.

The mega-shapes invert: SS 96x96x16 single-problem read **404** at 1024 while
family-protocol reads **818–1210** there — short invocations never reach boost
clocks; this is the *under*-direction of the same clock artifact.

### R50.2 The regrade (family-protocol rows only, vs the family-protocol floor)

| cell | corpus "win" | protocol | like-for-like | floor | honest Δ vs floor | % bar honest |
|------|-------------|----------|---------------|-------|------------------|--------------|
| SS:256 | 403.6 | SINGLE | 129.9 | 124.1 | **+4.7% tie** (was +225%) | 11.6% |
| CC:192 | 118.2 | SINGLE | 45.0 | 43.2 | **+4.0% tie** (was +173%) | 16.1% |
| DD:192 | 77.8 | trio-era | 21.0 | 21.4 | **−1.7% tie** (was +264%) | 21.3% |
| HH:256 | 763.4 | SINGLE | 206.5 | 201.5 | **+2.5% tie** (was +279%) | 8.4% |
| HH_HPA:512 | 853.4 | SINGLE | 440.8 | — | no floor | 39.4% |
| HS_HPA:512 | 820.4 | SINGLE | 427.8 | — | no floor | 38.2% |
| ZZ:128 | 15.1 | SINGLE | 6.9 | 4.9 | **+39.7% WIN** | 27.8% |

Everything else keeps its verdict and now measures family-protocol on both
sides: **22 WIN / 16 TIE / 0 LOSS** (was graded 26/12). Whole-family honest
readings: SS 512−4096 +7.3 to +11.9% (WIN), CC 256/1024/2048 +6.9/+14.1/+17.7%,
ZZ 192/256/512/1024 +40.8/+28.1/+18.3/+8.1%, DD 256/512 +19.3/+6.5%, HH
512/2048/4096 +20.8/+5.0/+6.1%; ties per §R52. No cell is a LOSS like-for-like.

The wrong-protocol readings also caused two report-side consequences: the
ORANGE %bar for the small cubes dropped 2–3.6x (SS:256 36.1→11.6 %, HH:256
31.0→8.4 %, CC:192 42.3→16.1 %), and **DD:192 was never flagged at all** (its
79% bar came from a trio container phase) though it sits at 21.3 %.

### R50.3 Why the protocols differ — the clock hypothesis, and the TTY experiment

Single-problem invocations hold 8 back-to-back reps of one problem (seconds of
continuous work on large shapes, tens of ms on small ones); family-protocol
invocations interleave 8 problems with `sleep-percent=50` spacing and repeat per
seed. gfx90c is an iGPU on an always-on power domain: short kernels into
sleeps plausibly park SCLK. That one mechanism explains:
small shapes reading 2–4x LOW in family phases, big shapes reading HIGH there
(their problems run late in a long, warm process), and single-problem mega-shape
phases reading LOW (32 ms of work never leaves idle clocks).

CPU-side evidence cannot decide it. The TTY run §R55 carries three cheap
instrumented checks: (1) `hardware-monitor=True` on the SS 8-shape family
phase — log SCLK per problem; (2) the same phase with `sleep-percent=0`;
(3) `num-warmups=8` variant. If the 256 problem's reading moves with either
knob, the whole straggler class is a measurement problem, not a kernel problem.

### R50.4 What the regrade does NOT change

DD:192's +264% trio reading was also config-inconsistent (the trio container
phases ran 192/256/2048 only, 1 seed each, and the same config's 192/256
readings *swap* across runs — 77.8/30.3 in 10-15 vs 19.6/80.5 in 10-17, with
the problem ORDER differing between those runs' CSVs). Trio/aniso container
phases are unusable as evidence either way; treat every `phase_cand_*`
container with a partial shape list as unmeasured for verdict purposes.

## R51 — typed straggler classes (the tracker; each class's work)

| # | class | cells | honest state | the work that moves it |
|---|-------|-------|--------------|------------------------|
| P1 | protocol victims | SS:256, CC:192, DD:192, HH:256 | 11.6/16.1/21.3/8.4 % bar, ties at ±5% | R50a iso calibration rows + §R50.3 TTY instrument; config work closed (the winners already twin the floor, §R54.3) |
| P2 | HPA 512-band | HH_HPA:512, HS_HPA:512 | 39.4/38.2 % bar while :1024+ hold 123–130% | R50b geometry push (21 rows): the :1024+ winner family (64x128x16/4x8) needs its DU8/VW2/WGM variants measured at :512; coverage says 91% of 589-legal space unexplored |
| P3 | fill-starved micro-cubes | SS:256, HH:256, CC:192, DD:192, ZZ:128 | same rows as P1 + ZZ:128 (27.8% bar, honest WIN +40%) | R50c knob salvo: WGM/residency/pads/unroll on the measured winners — the geometry itself is at its fill-friendly minimum (9 WGs on 7 CUs for the 64-side tiles) |
| P4 | roof ties | SS:768, SS:1365, CC:512, DD:768/1024/1365/2048, HH:1024, HPA 1024/2048 | +0.2 to +3.9% over floor, 90–115% of bar | none — config work exhausted (§R52); only floor re-measurement tightens the verdict |
| P5 | non-contract measured | SS:128/192, ragged 32/64x4096x4096, 128x128x2048 | bookkeeping rows | none; keep out of verdict grading |
| P6 | measurement-integrity debt | all | floor was never single-problem measured; trio/1-seed containers trash reproducibility | §R55 TTY: floor iso replay under both protocols for the 5 shipped families; retire sub-4-seed container |

## R52 — the twelve ties are roof ties (config work exhausted)

With like-for-like medians against each family's empirical bar
(REALISTIC_CEILINGS): SS:768 99.1%, SS:1365 99.6%, CC:512 115%, DD:768 94.3%,
DD:1024 93.0%, DD:1365 90.4%, DD:2048 97.7%, HH:1024 104.9%, HH_HPA 1024/2048
130/124%, HS_HPA 1024/2048 127/124% — every tie ≥90% of the *empirical* roof
and the deltas (−0.5% to +4.7%) sit inside the ±5% band. Nothing in the
geometry/forward-knob space is untested on these cells: the R16 tie-adapt batch,
the R40 frontier (workgroup-residency duality), the R43/R47 axis batches and
the R44/R45 virgin knobs have all covered them (assertions, NonTemporal,
StaggerU, WGM, pads, LSU, PGR, InnerUnroll). The honest interpretation: the
native port is at the FMA roof on twelve cells and cannot move them by making a
*different kernel*; only floor re-measurement (protocol parity) can tighten a
verdict.

## R53 — which kernel types have won, family by family, 30 runs

* SS (fp32): since the R49 batch, **128x128x8 / 8x8 / VW4 / DU8** — won 512–4096
  (78.7–111% bar; 880–1242 vs floor 801–1121). WGM4 default; the DU16/16x8/8x16
  TT variants of the same tile all lost to DU8. PGR+NonTemporal variants did not
  beat the default.
* HH (fp16): **128x128x16 / 8x8 / VW8 / DU16** won 2048/4096 (2790/2831 =
  113–115% bar) and **256x128x16 / 8x8 / VW8 / DU16** won 1024 (2563 = 105%).
  VW8 (16 B loads) is the whole story: the VW4 twins read 4–13% less at every
  size ≥1024.
* CC (complex): **64x64x8 / 4x4 / VW2 / DU8** unchanged since 10-13; nothing
  has beaten it at any size; 512+ is at/above the complex roof.
* DD (fp64): **64x64x8 / 4x4 / VW2 / DU8** (+ the 64x32 family) — identical to
  the floor's own geometry; 94–98% of bar, ties.
* ZZ (complex double): **32x32x16 / 2x2 / VW1** — the 128 cell is 27.8% bar
  (both arms poor), 1024 holds 24.5 = 99.2% of its small empirical bar.
* HPA: **64x128x16 / 4x8 / VW4 / DU16** and 128x64x16/8x4 twins → 123–130% of
  the fp32-adapted bar at ≥1024. THE gap is at :512 only (39%): the same tiles
  read 404–540 there; no shallower/different-depth variant has been tried at
  VW4+GLVW4 (everything prior was GLVW-default-2 or VW2) — that is R50b.

## R54 — the committed R50 batch, cover maps, and the steal decision

### R54.1 The deck rows now in `oto/harness/candidate_rows.py` (52 emitted)

* **R50a — iso-protocol calibration (4 emitted, AUTO_EXPLICIT tier):**
  shapes-narrowed single-problem clones of the four affected cells'
  single-problem-winning configs (SS 96x96x16/6x6/WGM8, CC 64x64x8/4x4/WGM8,
  HH 32x64x16/4x4/WGM4, ZZ 32x32x16/2x2/VW1) so the NEXT run measures both
  protocols on the same configs. The three family-winner clones (SS 32x64x8,
  CC 32x32x8, DD 32x32x16) fingerprint-collapsed into their existing family
  rows — the wide rows already carry those shapes, so the iso view lives in
  the run's per-shape rows anyway.
* **R50b — HPA 512-band push (21 rows, 21 emitted):** 64x64x8/(16), 32x64x16,
  96x96x16, 128x64x16, 64x128x16 WGM2/WGM8/DU8 variants and the 128x128x16
  VW8 tile on both HPA families (GLVWA/B pinned, which the HPA template needs
  above VW2 — 5 rows were refused pre-fix and are documented as the GLVW%
  pv law's natural correction). One row is the first HPA VW8 tile ever
  scheduled.
* **R50c — micro-cube knob salvo (27 rows):** on each P3 cell's measured
  winner tile: WorkGroupMapping {2,8}, MaxOccupancy {4,8}, InnerUnroll 2,
  NonTemporalA, LdsPadA/B 1 (per-family gate-checked subset).

Preflight on the committed rows: `oto.harness.candidate_generator --dry-run` → pool 1141,
52 would-append; `oto check candidates` → **284 checked (phases.yaml) + 1146
checked (overlay), 0 illegal**; real-Tensile deck_probe probe → **52/52
built, 0 refusals** (`gfx90c_results/analysis/deck_probe_r50.log`; includes
the HPA VW8 tile). The unmeasured deck is exactly those 52 rows — everything
older was measured by run_20261022.

### R54.2 The cover maps, re-read under like-for-like

The per-cell coverage maps (`gfx90c_results/analysis/coverage/`) rank the
unexplored legal space, but colour by the same protocol-mixed "best" — the
measured rows that hold a flash point on the small cubes are the
single-problem readings. Under like-for-like: SS 87% / CC 88% / HH 92% /
DD 91–93% of legal space unexplored, HH_HPA:512 91% of 589, ZZ only 52 legal
cells (fully explored). Kernel-type insight: the SS:512 "trap" ring is the
4k/8-accumulator bucket whose 96x96-class neighbours all measure faster —
and the 96x96x16/6x6 tile that flashes at SS:256 is exactly a
protocol-artefact flash. The map's *ranks* (which neighbour of a winner is
unexplored) remain valid; its *colours* on P1 cells do not, until the
protocol is normalised.

### R54.3 The steal decision, post-regrade (worst-losers only)

The steal route (re-emit the floor's winning gfx900 config natively with
documented gfx90c adaptations) was reserved for cells the native corpus could
not approach. The regrade sharpened what "cannot approach" means, and the
floor winners are already twinned everywhere it matters:

| cell | floor winner (family-protocol) | native like-for-like | twin? |
|------|-------------------------------|---------------------|-------|
| SS:256 | 32x64x8 / 4x4 / VW4 / DU8 = 124.1 | 32x64x8 / 4x8 / VW4 / DU8 = 129.9 | yes (+4.7%) |
| HH:256 | 32x32x16 / 4x4 / VW4 / DU16 = 201.5 | 32x64x16 / 4x4 / VW4 / DU16 = 206.5 | yes (same 32-wide family, +2.5%) |
| CC:192 | 32x32x8 / 4x4 / VW2 / DU8 = 43.2 | same config = 45.0 | exact twin (+4.0%) |
| DD:192 | 64x64x8 / 4x4 / VW1 / DU8 = 21.4 | 64x64x8/4x4 = 20.7–21.1 native | yes (parity) |
| ZZ:128 | 64x64x16 / 4x4 / VW1 / DU16 = 4.9 | 32x32x16/2x2/1/16 = 6.9 | native beats it +40% |

Every floored straggler already contains the floor's winning geometry
natively; the *remaining* deficits are P1/P3/P2-class work (protocol parity,
HPA 512 geometry), not config theft. **The steal route stays closed for the
floored cells, opened for nothing new** — the documented adaptations that
would be needed (§R26) remain on file for the one class the corpus genuinely
cannot reach: none, after R50b.

## R55 — the overnight TTY run

Deck state after this session: 60 R50 rows authored (7 iso + 21 HPA + 32
knobs); the first draft refused 5 HPA rows on the load gate's GLVW law
(templates default GLVW=2 on fp16, so a VW4/8 row must pin
GlobalLoadVectorWidth{A,B}) — the final set is 0-refused; 3 winner-config iso
clones (SS:256 32x64x8, CC:192 32x32x8, DD:192 32x32x16) fingerprint-collapsed
into their existing family-wide rows, and the rest fingerprint-deduped —
**52 phases appended**, which is also exactly the unmeasured deck: everything
older has a measurement. Pool = 1141 fingerprinted candidates,
budget-trimmed by the round-robin to the
`--budget` value at launch. The run remains the standing TTY command:
`python3 -m oto tune --budget 10 --yes` (checklist in
`command.txt`, untracked). Post-run reads that this deck makes
more valuable than usual: (1) the R50a iso rows' single-problem medians vs
their family twins — quantifies the split natively, per cell, in one run;
(2) `hardware-monitor` on one family phase for the clock hypothesis (§R50.3);
(3) the R50b HPA rows at :512 (goal: >600 family-protocol, i.e. 52%+, moving
HH_HPA:512/HS_HPA:512 off the straggler list); (4) R50c knob deltas on the
micro-cubes; (5) re-run `oto.metrics.ab_audit` with the family-protocol
winner basis (§R56.3-B) so the next acceptance report grades like-for-like.

## R56 — failed-candidate triage and legality state

### R56.1 Gate calibration over the full corpus (2026-10-23)

`oto.harness.gate_calibration --population all`: 46 runs, 12545 phases, 10230
with a launch config. **OURS (native): 5662 phases — 0 MISS, 0 FALSE
REJECTION.** REFERENCE (gfx900 replay): 172 misses / 43 false rejections —
all from the 09-25→09-29 floor-replay campaign, a different template era
(GSU8, mt36, vw1-loads) that predates every rule; these remain documented as
not our generator's population. The decision rule (§R23: false-rejection
count ZERO on our corpus) holds.

### R56.2 The failed-candidate classes, triaged (failure_triage)

Per-run empties: 10-15 31/612, 10-17 31/395, 10-18 7/412, 10-20 8/715,
**10-22 0/1103**. Classes:

* `stderr non-empty: Traceback` — **muted noise**: Python 3.14 multiprocessing
  `resource_tracker` semlock teardown spam; the *real* stdout for those phases
  is "Generating kernel source resulted in error 4" (the error-4 class,
  already ruled 10-21 (4th)).
* `Kernel Uses 131072 > 65536 bytes of LDS` — 13 phases in the 10-15/10-17
  era, all PGR=1-template 128x128x16 fp32 tiles; the current template's
  allocator case (`lds_base * ku ≤ 16384` conservatively) plus PGR default now
  make the class dead: 10-22 (the first run fully on the current template)
  had ZERO of them. Closed by template change, not a new rule.
* `GlobalLoadVectorWidth* must be == VectorWidth` and `GLVW % pv` — 202+62+
  corpus-wide, all in old eras; the loads gate's GLVW verbatim + pv-stage
  rules now refuse them pre-Tensile. Verified live during this session's deck
  build: 5 HPA rows refused with exactly this text before touching Tensile.
* `Valid parameters are [...]` (128, all 10-15-ish) — unknown-knob typo era;
  NOT_FORWARDED strip prevents the class in the current template.
* error-4 on `128x256x8/4x8` rows — Tensile-writer refusal, 4–8 phases 10-20;
  rows dropped/superseded in the current deck by the R49 128x64/256x128
  frontier twins.

### R56.3 The two grading fixes to wire next (non-blocker, listed for the record)

**A (reporter): RESOLVED 2026-10-23 — like-for-like graded basis wired
end-to-end.** `oto/metrics/measurement_protocol.py` now owns the canonical
invocation-form classifier; every record, kernel_db row and report payload
carries it. The rule (verified against the corpus before locking):

- `FAMILY` — the invocation covers the family's graded cell list
  (`FAMILY_CELLS` (derived from the profile tables) and re-exported by the
  deck as `TARGET_CELLS`). This is deliberately not the benchmark contract
  (`FAMILY_SHAPES`): DD's contract has 7 sides but grades 6 cells, HS_HPA's 4
  but grades 3 — anchoring on the contract would exclude exactly the deck's
  own wide spans (and the R50b HPA-512 rows tonight) from the graded basis,
  which the run data shows is wrong.
- `SINGLE` — one problem (§R50 iso evidence). `PARTIAL` — the trio/pair
  containers and all-but-one narrows (§R53 showed their readings swap across
  runs). `UNKNOWN` — not derivable; never admitted to a graded basis.
- Ground truth used to settle it: all 3802 floor CSVs measure exactly their
  family contract (family-only arm by construction), and the twin phases
  `phase_auto_0_hh_256x256x256_4` (family, 5 problems in run_20261006_122020;
  single in run_20261008_005217) prove phase names never encode protocol —
  hence classification from declared/measured side sets, never names.

Grading (default basis `family`, `--protocol-basis` selects otherwise): the
verdict pairs only same-protocol records on both arms; the pre-basis
mixed winner and the isolated single-problem reading stay in the payload as
`native_best_any_protocol` / `native_isolated_best` (nothing previously
printed disappears). Stamps land in `ab_records`/`ab_delta`/`ab_audit`/
`ab_band`/`acceptance_reporting`/`corpus_loaders` (RED/ORANGE basis) /
`kernel_db` (`n_problems` + `protocol` per row) / `coverage_map`
(`--protocol`, default family). §56.3-B (per-cell protocol-normalised
quoting from the R50a iso twins) remains open pending tonight's run.

**B (calibration):** the deck's iso rows (R50a) plus the §R50.3 TTY
instrumentation decide the SS/HH/CC/DD five-cell story inside one run; after
that, verdicts can quote a per-cell protocol-normalised basis with the raw
both-protocol readings attached.

## R57 — the coverage maps re-read on the census: finding the last fill, and R50d (2026-10-24)

The per-cell SVGs in `gfx90c_results/analysis/coverage/` (§R48.6/R54.2 own the
drawing rules) are the 2026-10-22 snapshot, pre-R50 and pre-regrade — their
"best" column is mixed-protocol and their corner buckets wobble with the area
bucketing. So this pass re-reads them against the *authoritative* per-cell
config census: `coverage_map.measured_geometries()` post-§R56.3-A (family
protocol only). The census is what the deck dedupes against; the SVGs supply
the picture. Verdict per graded ORANGE cell:

| cell | census geoms | the picture says | the census says |
|------|----|----|----|
| SS:256 | 223 | 87 % unexplored; hot rung (8k,32); everything ≥16k slow | every legal class the load law admits outright is measured; near-winner gaps are DU/WGM-variant territory (R50c salvo) |
| CC:192 | 86 | 88 %; one 4k/16 ridge, holes at (4k,8/32/64) | the 64x64 acc-32/64 holes are the assertion-only axis (the frontier block: CC's no-assertion law forces TT=16 at 64 wide); 96x96 mirror measured-slower |
| DD:192 | 27 | wide band, 92 % unexplored | (2k,16)-(8k,16) ridge measured; unexplored = big-tile assertion cases DD cannot reach (no tile >16384 legal, §R48) |
| HH:256 | 213 | outlier sibling: cloud sits on small tiles, big-tile diagonal slow *at 256* | 128x128/4x4 measured 190.9, 8x8=183 at 256 (slower than the 32x64 winner family, not virgin); the acc-32 rung 128x64x8x4=193.6 is measured |
| ZZ:128 | **15** | tiniest terrain: 52 legal, 16 buckets | 15 of 52 configs measured; remaining classes violate the ZZ load law outright or sit under one wave — auto's neighbour finder owns them (ranks family-protocol now, §R56.3-A) |
| HH_HPA:512 | 106 | 91 % unexplored | one true hole left near the winner |
| HS_HPA:512 | 111 | 91 % unexplored | same hole |

**The hole the two views agree on (R50d).** On both HPA families, the
128x128-area column is measured fast at acc/thread 16 (HS 302–343, HH_HPA
302–323) and at acc/thread 64 (HS 256–343, HH_HPA 325–403) — and *nothing at
acc/thread 32*: ThreadTile 8x4 on a 128x128 tile (512 threads, one work-group,
32 accumulators a thread) has never been measured in either family at any
side, and it is not in R50b (which puts TT 4x8 and 8x8 on 128-wide tiles).
The load law (`MT1*GLVW == TT0*TT1*DepthU`, the frontier block) admits
128x128x8 / 8x4 / VW2 / DU8 outright (128·2 == 32·8), and the VW4 twin under
pinned `GlobalLoadVectorWidth{A,B}` (128·4 == 32·16). R50d is exactly those
four rows in `oto/harness/candidate_rows.py` (family-span shapes — the same
§R56.3-A rule stamps them `family`). Emits verified: pool 1141 → 1145, dry-run
would append exactly 4, zero refusals, no fingerprint collapses; full preflight
177 passed. Cost: ~7 min of the run.

**What was considered and refused to keep the deck honest:** a ZZ family
completion sweep (36 configs — cheap in absolute terms but each is a
law-violation or sub-wave tile, the worst odds on the deck); SS/CC/DD
micro-islands (knob territory — R50c already owns the legal salvo there);
256-wide tiles at :512 (the 2026-10-20 frontier already measured them —
census 267–337 at HS:512, 316–350 at HH_HPA:512 — the SVG's corner hatch was
the bucket-rounding illusion this section exists to dispel).

Post-run reading (extends §R55's list): the R50d rows' :512 medians against
the 427.8/440.8 family winners, then regenerate the maps
(`oto.harness.coverage_map` + `oto.harness.coverage_graph`) — the fresh SVGs
replace the stale mixed-basis colours wholesale.
