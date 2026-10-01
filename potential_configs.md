# gfx90c (Vega 7) — oto Candidate Deck

> **Role.** This file owns exactly one thing: **which candidate configs to
> benchmark next, and the measured evidence that each one is missing.** It is the
> input to the deterministic convergence loop.
>
> **It does not own** hardware ceilings, methodology, run history, or sources.
> Those live in the docs that own them, and this file links rather than repeats:
>
> | topic | owner |
> |---|---|
> | gfx90c ISA facts, ALU peaks, memory roofline, occupancy, acceptance bars | `gfx90c_theoretical_limits.md` |
> | Tensile concepts, solution space, kernel levers, measurement science, reporting | `knowledge_base.md` |
> | Tuning strategy, correctness gate, "AI must not decide" | `tensile_tuning_context.md` |
> | Native kernel levers that moved the needle (measured, frozen) | `mapping.md` §3 |
> | Run summaries, winners, acceptance reports, reference-floor triage | `results.md` |
> | Open work items | `incomplete_work.md` |
> | Audit findings register | `adversarial_review.md` |
> | Shipped-gfx900 replication contract | `mapping.md` §1–2 |
>
> **Hard rule.** No GPU workload may be executed from a GNOME desktop session.
> CPU-only legality proofs are permitted at any time; every performance number
> below is historical, not a live measurement.

---

## 1. Verdict under grading

Graded by `run_20260929_164520/acceptance_report.json`, `agg=winner`, tie band
±5%, against the recalled 3-run reference chain
(`gfx900_ref_20260929_164544_resume` ← `gfx900_ref_20260926_201843_resume` ←
`gfx900_ref_20260925_152942`).

| | cells |
|---|---|
| WIN | 11 |
| TIE | 11 |
| **LOSS** | **16** |
| overall | `false` (provisional floor) |

This recomputation was re-run from the current corpus and reproduces the stored
report **exactly — 0 of 38 cells changed**. The report is therefore current with
respect to the rebenchmark it was graded against; the reference floor is not
stale.

---

## 2. The finding that determines the whole deck

For each of the 16 losses, take the floor's winning kernel, read its **resolved
solution** out of that phase's own `2_BenchmarkData/Cijk_*.yaml` (not the phase
id, not the kernel name), and ask one question: **was that exact config ever
benchmarked natively?**

| answer | cells | what it means |
|---|---|---|
| **never run natively** | **13 of 16** | pure coverage gap. Native lost because it never tried the winning config. |
| **was run natively** | 3 of 16 (all CC) | a harder config gap — the winning config was run and still lost. See §5. |

13 of 16 losses are not tuning problems. They are missing rows.

### 2.1 Measured native width/tile coverage, per family

Parsed from every `phase_id` in the native arm (all run CSVs + registry).
**This is the pre-regeneration baseline** — the deck has since been rebuilt
(§2.2), so re-derive it from the new `phases.yaml` before drawing conclusions.

| family | configs ever benchmarked natively | max VW | missing vs floor |
|---|---|---|---|
| SS | 128x128x{8,16}/8x8 **VW2**, 64x64x16/4x4 **VW4**, +22 more | **2** at 128x128 | 128x128 VW4 |
| HH | 128x128x{8,16}/8x8 **VW4**, 64x64/4x4 VW4, +6 | **4** | 128x128 VW8 |
| HH_HPA | 128x128x16/8x8, 128x64x16/**8x4**, 64x128x16/4x8, 64x64x16/4x4 — **all VW4** | 4 | 128x64 VW2, 64x128 VW2 |
| HS_HPA | same four, all VW4 | 4 | — (ties only) |
| DD | 9 configs, **every one VW1** | **1** | 32x32 VW2, 64x64 VW2 |
| CC | 8 configs, VW1 and VW2 | 2 | 32x32 VW2 |
| ZZ | 40 configs across 4 contraction patterns, **all VW1** | 1 | — (native already wins) |

Read the max-VW column as the whole story: **SS tops out at 8 B, DD and ZZ at
8 B, HH at 8 B.** The floor wins SS and large HH only at the 16 B cap
(`gfx90c_common.GLOBAL_LOAD_BYTE_CAP`). The under-wide winners are *legal* —
Tensile accepts them — which is exactly why they were never flagged.

### 2.2 `family_decks` has half the answer; the deck that ran has none of it

`scheduler.family_decks` already carries `SS 128x128x16/8x8/vw4`,
`HH 128x128x16/8x8/vw8`, `DD 64x64x8/4x4/vw2`. But the shipped `phases.yaml` —
the deck that actually executed — contains **none** of them: SS's only VW4 phases
are `64x64x16`, HH's max VW is 4, and DD is 100% VW1 across all 44 DD phases.

So part of this deck is not a tuning proposal, it is a **regeneration**:
`CandidateGenerator.generate_family_phases(family, patterns, shapes)` for each
family in `SS DD HH CC ZZ HH_HPA HS_HPA` over all 4 contraction patterns and all
of `gfx90c_common.FAMILY_SHAPES[family]`, which appends through
`append_candidates_batch()`. That alone closed 3 of the 13 coverage gaps with no
new insight. Do that before spending GPU time on the rest.

**Done.** The deck rebuilt from 434 to 1522 phases, all `gfx90c`, all
`NumBenchmarks: 8`, 0 duplicate `phase_id`, and re-running the generator is a
no-op (0 added) so the manifest is idempotent. `phases.yaml.pre_overnight_backup`
holds the 434-phase original.

### 2.3 `cap_vector_width()` is wrong on two tiles (CPU-only bug) — fixed

The cap is `min(16 / bytes-per-element, MT0/TT0, MT1/TT1)`. It omits Tensile's
second constraint: **`ThreadTile` must be a multiple of `VectorWidth`**. A thread
cannot issue a VW-wide vector load out of a narrower per-thread extent.

| family | MT | TT | old `cap_vector_width()` | gate verdict at that cap |
|---|---|---|---|---|
| SS | 96x96x16 | 6x6 | 4 | **FAIL** — `TT0=6 or TT1=6 not multiple of VW=4`; highest accepted **2** |
| HH | 64x64x16 | 4x4 | 8 | **FAIL** — `TT0=4 or TT1=4 not multiple of VW=8`; highest accepted **4** |

Everywhere else the cap agreed with the gate (verified across every tile in
`family_decks`). Two of the generated phases were therefore wider than Tensile
would accept, and any consumer treating the cap as "widest legal width" was
wrong on exactly the non-power-of-two tiles SS uses most. The fix picks the
largest power of two `v` with `v <= 16/bpe`, `MT0/TT0 >= v`, `MT1/TT1 >= v`,
`TT0 % v == 0` and `TT1 % v == 0`. **No candidate in §3 depended on this fix** —
all 8 pass both the cap and the real gate — so it is a correctness fix, not a
blocker.

---

## 3. Candidate deck

Every row is a **measured gap**: the config is the floor's own winner at a named
cell, or an untried neighbour of it. Legality = CPU-only, via the project's own
`CandidateGenerator._validate_tensile_loads` plus `cap_vector_width`.

| id | target cells | family | MT | TT | VW | GLVW | DU | WGM | GSU | LdsPad | evidence | CPU gates |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **C1** | SS 768, 1000, 1024, 1365, 2048, 4096 (+512 tie) | SS | 128x128x8 | 8x8 | **4** | 4 | 8 | 4 | 1 | 0/0 | floor winner on all 7 cells; native never ran 128x128+VW4. Largest gap in corpus (SS:2048 −15.1%) | **PASS** (cap 4) |
| **C2** | HH 1024, 2048, 4096 | HH | 128x128x16 | 8x8 | **8** | 8 | 16 | 4 | 1 | 0/0 | floor winner on all 3; native never ran VW8 anywhere (−10.9/−14.6/−14.5%) | **PASS** (cap 8) |
| **C3** | DD 192 | DD | 32x32x8 | 4x4 | **2** | 2 | 8 | 4 | 1 | 0/0 | floor winner on DD:192 (−12.7%); native DD is VW1 at every tile | **PASS** (cap 2) |
| **C4** | DD 768 (+1024 variant) | DD | 64x64x8 | 4x4 | **2** | 2 | 8 | 4 | 1 | 0/0 | floor winner on DD:768 (−2.9% tie); native never ran 64x64+VW2 | **PASS** (cap 2) |
| **C5** | CC 192 | CC | 32x32x8 | 4x4 | **2** | 2 | 8 | 4 | 1 | 0/0 | floor winner on CC:192 (−6.4%); native only has 32x32 at VW1 | **PASS** (cap 2) |
| **C6** | HH_HPA 4096 | HH_HPA | 128x64x8 | **8x4** | **2** | 2 | 8 | 4 | 1 | 0/0 | floor winner on HH_HPA:4096 (−9.8%). Note **TT is 8x4**; `family_decks` has 128x64x16 with **TT 4x8** — a different config | **PASS** (cap 8) |
| **C7** | HH_HPA 2048 | HH_HPA | 64x128x8 | 4x8 | **2** | 2 | 8 | 4 | 1 | 0/0 | floor winner on HH_HPA:2048 (−7.7%); tile orientation absent from `family_decks` | **PASS** (cap 8) |
| **C8** | ZZ VW2 probe | ZZ | 64x64x8 | 4x4 | **2** | 2 | 8 | 4 | 1 | 0/0 | not a loss — the floor never wins ZZ above VW1. Probes whether 16 B is reachable for int8 at all | **PASS** (cap 2) |
| **C9** | SS 256 | SS | 32x64x8 | **4x8** | **4** | 4 | 8 | 4 | 1 | 0/0 | floor winner on SS:256. **Anisotropic** tile; no quantisation argument proposes it, and it was never generated. Note SS:256 is already a WIN (+226.9%) — this candidate targets utilisation (25.5% of roof), not conversion | **PASS** |
| **C10** | HH 256 | HH | **64x32**x16 | 4x4 | **4** | 4 | 16 | 4 | 1 | 0/0 | floor winner on HH:256. 128 threads vs 64 for 64x64 — an axis the quantisation ladder cannot see. Never generated. Already a WIN (+270.8%); targets 23.7% of roof | **PASS** |
| **C11** | ZZ 192 | ZZ | 32x32x8 | **4x4** | 1 | 1 | 8 | 4 | 1 | 0/0 | floor winner on ZZ:192. 4x4 complex double is TT0*TT1*8 = 128 accumulator VGPRs, exactly on budget. Already a WIN (+37.5%); targets 20.4% of roof | **PASS** |
| **C12** | ZZ 128 | ZZ | **64x64x16** | 4x4 | 1 | 1 | 16 | 4 | 1 | 0/0 | floor winner on ZZ:128. Already a WIN (+203.7%); targets 16.7% of roof, the worst-utilised cell in the corpus | **PASS** |
| **C13** | ZZ 512 | ZZ | 64x64x8 | 4x4 | 1 | 1 | 8 | 4 | 1 | 0/**1** | floor winner on ZZ:512 is C12's tile at DU8 plus `LdsPadB 1` — the only ZZ pad with measured support. Already a WIN (+8.3%), the thinnest margin of the six; targets 22.6% of roof | **PASS** |

`GLVW = VectorWidth` throughout: the stock `GLVW == VW or GLVW == 1` generator
restriction is satisfied without weakening it, so none of C1–C8 needs the
guard-relaxation route that HS_HPA required.

### 3.1 DepthU is not a free parameter — copy the floor's value

The floor's SS winner is `DepthU 8` at 128x128, not 16. Earlier revisions of this
deck specified DU16 for SS and were wrong. C1 carries DU8. The DU32/DU16
explorations below are deliberately *separate* candidates so a DU regression
cannot be mistaken for a VW regression.

### 3.2 Second tier — worth trying once C1–C7 land

Only if C1–C7 leave gaps. Ordered by expected value.

| id | target | change vs C* | why |
|---|---|---|---|
| X1 | SS 2048/4096 | C1 + `LdsPadB 2` | floor uses `LdsPad 0/0`; if C1 lands short, the pad is the next knob. GFX9 LDS bank = `(byte_addr/4) mod 32`, so a 128 B-aligned B row collides on every wave-phase |
| X2 | HH 2048/4096 | C2 + `DepthU 32` | DU32 is legal and never tried; HH:512's floor winner is `mt128-tt8-vw8-du16` while some HH_HPA winners use DU32 |
| X3 | CC 2048 | `64x64x8/4x4` VW2 + **`LdsPadA 2`** | CC:2048's floor winner is the C5/C5-neighbour tile with `LdsPadA 2, LdsPadB 0` — asymmetric, and the only CC row in the whole census with a non-zero pad |
| X4 | SS 2048 | C1 + `GlobalSplitU 2` | untried axis; gated class-illegal on HH-derived families but legal on SS |
| X5 | HS_HPA 1024/2048/4096 | `128x64x16/8x4` VW4 ± pad | all three are TIE (−0.7…+0.1%). Only 0.7% of headroom; lowest priority |
| X6 | best SS/HH cell | `WorkGroupMapping 2` | WGM has only ever been 1, 4, 8 |

### 3.3 Explicitly not proposed

- **ZZ width beyond VW1** beyond C8. The floor never wins ZZ above VW1 on any of
  its five cells, and native already wins 4 of 5 outright (+8.3…+203.7%). There
  is nothing to convert.
- **Any CC width above VW2.** `GLVW 4 × 8 B = 32 B` exceeds the 16 B cap. CC's
  ceiling is structural, not a tuning gap. See §5.
- **Stream-K, magic-algorithm variants, `PrefetchGlobalRead` on 128x128.** All
  were carried in earlier revisions of this deck and none targets a measured gap.
  `PrefetchGlobalRead` doubles the LDS footprint to 16 KB on a tile already at
  budget. Drop them unless C1–C7 land and the gaps persist.

---

## 4. Expected effect

| candidates | losses addressed | mechanism |
|---|---|---|
| C2 | 3 (HH 1024/2048/4096) | 8 B → 16 B global load |
| C1 | 6 (SS 768/1000/1024/1365/2048/4096) | 8 B → 16 B global load |
| C6 + C7 | 2 (HH_HPA 4096/2048) | tile orientation + width |
| C3 + C4 | 1 loss (DD 192), 1 tie (DD 768) | 8 B → 16 B |
| C5 | 1 (CC 192) | 8 B → 16 B |
| C5-neighbour | 3 CC losses (CC 256/1024/2048) | tile + `LdsPadA` — these **are** config gaps (§5), just ones the winning config was already run for |

13 of 16 losses are addressable by the C* configs. If C1–C7 each land at the
floor's own value, the remaining losses are CC:256/1024/2048, where the winning
config was already run and still lost — the harder case, and the one the widened
CC deck (measured winner tiles, the `LdsPadA=2` variant, and 32x32/16x16 ladder
tiles) exists to attack.

C9–C13 address no losses at all: all six of those cells are already WINs. They
are in the deck because the brief covers **winners below 50% of theoretical**,
and these sit at 16.7–25.5% of their roof. Their floor winners are the best
measured starting points available for raising utilisation.

**Ordering.** §2.2 regeneration — done. Then C1, C2 (largest margins, most
cells). Then C6, C7 (HH_HPA orientation). Then C3, C4, C5. Then C9–C13 (already
winning, so they cannot regress the report). Then X1–X6 only if gaps persist.

---

## 5. The 3 CC losses are real, not measurement noise

CC:256, CC:1024 and CC:2048 are the losses where the floor's winning config
**was** benchmarked natively and native still lost (−15.1%, −5.5%, −6.5%).
Comparing the *same kernel* (identical `fingerprint` — same tile, same width,
same pattern) across arms, where n is the number of distinct kernels and each
median is over 8 repeats:

| cell | kernel | native median | floor median | native vs floor | native kernels | floor kernels |
|---|---|---|---|---|---|---|
| CC:256 | `Ailk_Bjlk_CB_MT64x64x16` | 114.28 | 175.95 | **−35.1%** | 2 | 6 |
| CC:256 | `Alik_Bljk_CB_MT64x64x8` | 111.23 | 155.16 | −28.3% | 1 | 8 |
| CC:2048 | `Ailk_Bjlk_CB_MT32x32x8` | 165.65 | 267.78 | **−38.1%** | 1 | 8 |
| CC:1024 | `Ailk_Bjlk_CB_MT32x32x8` | 160.85 | 260.80 | −38.3% | 1 | 8 |

The same compiled kernel, on the same silicon, in the same session type, is
16–38% apart. That is not a tuning difference.

**Correction: this is NOT a sample-density artifact.** An earlier revision of
this document claimed the native arm ran 1–3 samples per kernel against the
floor's 4–8, and concluded the CC verdicts were ungraded. That was wrong: it
counted *records per fingerprint* — i.e. how many distinct kernels a cell has —
and mistook that for repeats. Measured directly from the `2_BenchmarkData`
CSVs, **every kernel on both arms has exactly 8 repeats**, and
`policy.aggregate_cell` takes the median of those 8 before the max. The deck
already sets `NumBenchmarks: 8` for every phase.

So the CC gap is real, and the −16…−38% is a genuine throughput difference on
the same source-level config. What actually separates the arms is narrower:

- **Clock telemetry.** The native arm carries no thermal/clock records, so its
  clocks are unadjusted; the spoof floor has partial clock coverage. An
  unadjusted arm drifts with the boost state of whatever ran before it.
- **ISA target.** The floor's solutions are `gfx900`-target code and the native
  ones are `gfx90c`-target, so "same kernel" means same source config, not the
  same binary — scheduling hints and VGPR allocation can differ.

**What this means for the deck.** CC is a genuine config gap, not a measurement
gap, so it *is* answerable with candidates — which is why the CC deck carries
the measured floor winners (`32x32x8/4x4/VW2`, `64x64x8/4x4/VW2`, and the
`LdsPadA=2` variant) instead of only ladder probes. No repeat-count change is
required. The clock-coverage asymmetry above still means single-run CC deltas
should be read with care.

---

## 6. Validation protocol

TTY only. Never from a GNOME session.

1. Regenerate `phases.yaml` from `scheduler.family_decks` (§2.2). — **done**
2. CPU legality sweep: every deck entry through `validate_config`,
   `occupancy_feasible` and `assembly_class_valid`; confirm no duplicate
   `phase_id` and no `Architecture != gfx90c`. — **done**
3. Benchmark the deck. Every phase already sets `NumBenchmarks: 8`, so
   `agg=winner` has 8 seeds to take a median over; no repeat change needed.
4. Re-grade. Acceptance requires `overall_pass: true` at the ±5% band.
5. Only then consider §3.2.

Per-run operational notes and resume triage belong in `results.md`; this section
is the acceptance bar only.

---

## 7. Decision log

Append-only. Earlier entries retained.

- **2026-10-01** — A/B reframed: both arms run on the same gfx90c APU, so
  "spoof" is a config deck, not a different device. Floor = recalled chain.
- **2026-10-01** — Recomputed all 38 cells against the shipped rebenchmark;
  reproduces the stored report exactly (0 changed). Report is current.
- **2026-10-01** — **Root cause of 13 of 16 losses identified: the floor's winning
  config was never benchmarked natively.** Deck reduced from 23 speculative
  candidates to 8 measured-gap candidates.
- **2026-10-01** — **The 3 remaining CC losses are a sample-density artifact**
  (native n=1 vs floor n=8 on identical kernels, −16…−38%), not a config gap.
  CC verdicts are UNGRADED pending a re-measure at n≥5.
  **Superseded 2026-10-02** — the n=1 vs n=8 reading was wrong. Both arms run 8
  repeats per kernel and median them; the count was of records (distinct
  kernels), not repeats. The CC gap is real, CC is answerable with candidates,
  and no repeat-count change is needed. See §5.
- **2026-10-01** — `phases.yaml` confirmed stale against `scheduler.family_decks`;
  the three headline candidates exist in the generator and not in the shipped
  deck. Regeneration is the first action item.
- **2026-10-01** — `cap_vector_width()` overstates the cap on `96x96x16/6x6`
  (says 4, gate rejects 4) and `64x64x16/4x4` half (says 8, gate rejects 8).
  Missing constraint is `ThreadTile % VectorWidth == 0` (`scheduler.py:338`).
  Fix required; no candidate in §3 depends on it.
- **2026-10-01** — Document deduplicated. Hardware/roofline/occupancy analysis
  moved to `gfx90c_theoretical_limits.md`; methodology to `knowledge_base.md`;
  run history to `results.md`; this file reduced to the candidate deck and its
  supporting evidence.
- **2026-10-02** — `cap_vector_width()` fixed to enforce `ThreadTile % VW == 0`.
  `generate_family_phases()` now steps an illegal width down to the widest
  value the gate accepts instead of dropping the phase, and records the clamp in
  `CandidateGenerator._clamped_widths`. Three entries clamp on purpose: SS
  `32x32x16/2x2` 4→2, HH `32x32x16/2x2` 8→2, HS_HPA `64x64x8/4x4` 4→2.
- **2026-10-02** — **Two silent-drop bugs found and fixed.**
  (1) `_dtype_char` had no mapping for the `HH_HPA`/`HS_HPA` family labels, so
  the register-file gate failed them closed and the whole HPA deck
  (256 candidates) would have been dropped from generation. (2) `phase_id` was
  built from MT/TT only, so a deck repeating a tile at two widths — or at the
  same width with different `LdsPad` — produced two configs on one output
  directory, and the second silently overwrote the first's results.
  `append_candidates_batch()` now binds a colliding id to its fingerprint and
  says so.
- **2026-10-02** — **Three "MEASURED" claims in the deck were wrong.** The floor
  winners for the sub-50% cells are `SS:256` = `32x64x8/4x8/VW4` and
  `HH:256` = `64x32x16/4x4/VW4` — both anisotropic tiles that no quantisation
  argument would have proposed, and neither was in the deck. `ZZ:192` wins on
  `32x32x8/4x4` (4x4 threads, not 2x2), `ZZ:128` on `64x64x16/4x4`, and
  `ZZ:512` needs `LdsPadB=1`. All four added. The earlier claim that
  `64x64x16/4x4/VW4` was the measured `HH:256` winner was an inference, not a
  measurement.
- **2026-10-02** — Deck regenerated: 434 → 1522 phases, 0 duplicate `phase_id`,
  0 non-gfx90c, all 8 repeats. 51 of 54 deck entries pass all three CPU gates
  outright; the 3 others are the deliberate clamps above. Full suite 147 tests,
  0 failures. Backup at `phases.yaml.pre_overnight_backup`.
- **2026-10-02** — `test_elapsed_is_head_run_not_chain_span` was a time bomb: it
  pinned a literal `2026-09-28` start and aged it against the real clock, so it
  began failing once wall time passed it. `build_report()` takes an optional
  `now`; the test pins the clock. Production behaviour is unchanged.
- **2026-10-02** — The acceptance report could score **the gfx900 floor against
  itself**. With no run directory (`--dry-run`, `--report`) the A/B subject came
  from `registry.latest_run_id()`, which returns the newest row in the runs
  table whatever its arm — and the newest row is normally the floor head. It is
  worse than a mislabel: `_reference_floor_runs()` *excludes the subject* when
  the subject is a `gfx900_ref` run, so the floor was compared against itself
  minus its own head. Every spoof kernel count halved and four verdicts moved
  with no error raised:

  | cell | mis-scoped | correct |
  |---|---|---|
  | CC:1024 | TIE +3.05 | LOSS -5.47 |
  | HH_HPA:4096 | WIN +17.87 | LOSS -9.76 |
  | HS_HPA:4096 | WIN +16.75 | TIE -0.67 |
  | ZZ:1024 | WIN +5.67 | TIE +4.64 |

  `11/11/16` read as `14/10/14` — a report that looked *better* because it was
  measuring a different thing. `latest_run_id(arm="native")` now scopes the
  default, and the A/B subject can no longer be the floor. Correct baseline is
  subject `run_20260929_164520` vs floor head
  `gfx900_ref_20260929_164544_resume` → **11 WIN / 11 TIE / 16 LOSS**.
- **2026-10-02** — Generated phases were missing `config.FamilyLabel`, so
  `cell_key()` returned `None` and the driver stamped every new record with **no
  cell key**. Not data loss — `analytics._cell_family` falls back to parsing the
  phase_id, and that fallback reads `hh_hpa`/`hs_hpa` correctly — but the
  documented identity path (the config) was absent, and the `DataType` fallback
  would have folded `HH`, `HH_HPA` and `HS_HPA` together since all three are
  `H`. The generator now emits `FamilyLabel`; all 7 families resolve a cell key.
- **2026-10-02** — The 1 duplicate `fingerprint` in `phases.yaml`
  (`phase_auto_0_zz_128x128x128_6` / `_25`) is pre-existing in the original 434
  from the AUTO generator, not introduced here. Distinct ids, so harmless, but
  it benchmarks the same ZZ config twice.